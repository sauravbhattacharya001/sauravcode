"""Tests for sauravsmoke - feature detection, cost estimation, and slate building."""

import json
import os
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import sauravsmoke as sm


# ── detect_features ────────────────────────────────────────────────────────

class TestDetectFeatures:
    def test_empty_source_returns_empty_list(self):
        assert sm.detect_features("") == []

    def test_returns_sorted(self):
        src = "for x = 1 to 10\nif a then b\nprint x\n"
        hits = sm.detect_features(src)
        assert hits == sorted(hits)

    def test_detects_if_else(self):
        assert "if_else" in sm.detect_features("if x then y\n")

    def test_detects_while_for(self):
        src = "while c\n  for x = 1 to 5\n    print x\n"
        hits = sm.detect_features(src)
        assert "while_loop" in hits
        assert "for_range" in hits

    def test_detects_for_each(self):
        assert "for_each" in sm.detect_features("for item in items\n  print item\n")

    def test_detects_function_def(self):
        assert "function_def" in sm.detect_features("function greet(name)\n  print name\n")

    def test_detects_lambda(self):
        assert "lambda" in sm.detect_features("f = lambda x: x*2\n")

    def test_detects_pipe(self):
        assert "pipe" in sm.detect_features("xs |> filter |> map\n")

    def test_detects_fstring(self):
        assert "fstring" in sm.detect_features('s = f"hello {name}!"\n')

    def test_detects_try_catch(self):
        hits = sm.detect_features("try\n  risky()\ncatch e\n  print e\n")
        assert "try_catch" in hits

    def test_detects_json_helpers(self):
        assert "json" in sm.detect_features("data = json_loads(text)\n")

    def test_detects_break_continue(self):
        hits = sm.detect_features("while x\n  break\n  continue\n")
        assert "break_continue" in hits

    def test_no_false_positive_for_unrelated_text(self):
        # Plain prose shouldn't trigger structured-language features.
        hits = sm.detect_features("This is plain English with no code.\n")
        assert "function_def" not in hits
        assert "while_loop" not in hits
        assert "for_range" not in hits


# ── estimate_cost_seconds ──────────────────────────────────────────────────

class TestEstimateCost:
    def test_empty_source_has_floor(self):
        # Floor guarantees minimum 0.2s even for empty input.
        assert sm.estimate_cost_seconds("") == 0.2

    def test_pure_comments_only_charge_floor(self):
        src = "# comment one\n# comment two\n# comment three\n"
        assert sm.estimate_cost_seconds(src) == 0.2

    def test_blank_lines_dont_count(self):
        src = "\n\n\n\n"
        assert sm.estimate_cost_seconds(src) == 0.2

    def test_cost_scales_with_code_lines(self):
        small = "print 1\n"
        big = "print 1\n" * 50
        assert sm.estimate_cost_seconds(big) > sm.estimate_cost_seconds(small)

    def test_loops_add_extra_cost(self):
        no_loop = "print 1\nprint 2\nprint 3\nprint 4\nprint 5\n"
        with_loop = "for x = 1 to 5\nprint 1\nprint 2\nprint 3\nprint 4\n"
        assert sm.estimate_cost_seconds(with_loop) > sm.estimate_cost_seconds(no_loop)

    def test_cost_is_capped(self):
        huge = "print x\n" * 5000
        assert sm.estimate_cost_seconds(huge) <= 8.0

    def test_returns_float(self):
        assert isinstance(sm.estimate_cost_seconds("print 1\n"), float)


# ── SmokeCandidate / SmokePick / SmokeSlate dataclasses ───────────────────

class TestDataclasses:
    def test_candidate_as_dict_round_trip(self):
        c = sm.SmokeCandidate(
            path="x.srv", is_test=False, line_count=10,
            feature_ids=["if_else"], cost_seconds=0.5, feature_weight=5,
        )
        d = c.as_dict()
        assert d["path"] == "x.srv"
        assert d["feature_ids"] == ["if_else"]
        assert d["feature_weight"] == 5

    def test_pick_as_dict(self):
        p = sm.SmokePick(
            path="t.srv", tier="P0", new_features=["if_else"],
            cumulative_features=1, cost_seconds=0.3, rationale="tests must run",
        )
        d = p.as_dict()
        assert d["tier"] == "P0"
        assert d["rationale"] == "tests must run"

    def test_slate_as_dict_defaults(self):
        s = sm.SmokeSlate(
            root=".", total_candidates=0, total_features_available=10,
        )
        d = s.as_dict()
        assert d["picks"] == []
        assert d["covered_features"] == []
        assert d["coverage_score"] == 0.0


# ── SmokeSlate.format ─────────────────────────────────────────────────────

class TestSlateFormat:
    def _slate(self, tmp_path):
        # Build a real slate by scanning a tiny demo tree.
        (tmp_path / "test_a.srv").write_text("if x then y\nprint 1\n", encoding="utf-8")
        (tmp_path / "demo.srv").write_text(
            "function f()\n  for i in xs\n    print i\n", encoding="utf-8"
        )
        return sm.Smoker(root=tmp_path).recommend()

    def test_text_format_mentions_root(self, tmp_path):
        out = self._slate(tmp_path).format("text")
        assert "sauravsmoke" in out
        assert "coverage" in out

    def test_md_format_has_table_header(self, tmp_path):
        out = self._slate(tmp_path).format("md")
        assert "| # | Tier | File |" in out
        assert "## Slate" in out

    def test_json_format_is_valid_json(self, tmp_path):
        out = self._slate(tmp_path).format("json")
        obj = json.loads(out)
        assert obj["total_features_available"] == len(sm.FEATURE_CATALOGUE)
        assert "picks" in obj

    def test_unknown_format_raises(self, tmp_path):
        slate = self._slate(tmp_path)
        with pytest.raises(ValueError):
            slate.format("xml")

    def test_default_format_is_text(self, tmp_path):
        s = self._slate(tmp_path)
        assert s.format() == s.format("text")


# ── Smoker.scan ────────────────────────────────────────────────────────────

class TestScan:
    def test_scan_missing_root_returns_empty(self):
        cands = sm.Smoker(root="/definitely/does/not/exist/anywhere").scan()
        assert cands == []

    def test_scan_finds_srv_files(self, tmp_path):
        (tmp_path / "a.srv").write_text("print 1\n", encoding="utf-8")
        (tmp_path / "b.srv").write_text("for x in xs\n", encoding="utf-8")
        (tmp_path / "ignored.txt").write_text("print 1\n", encoding="utf-8")
        cands = sm.Smoker(root=tmp_path).scan()
        names = sorted(c.path for c in cands)
        assert names == ["a.srv", "b.srv"]

    def test_scan_is_deterministic(self, tmp_path):
        for n in ["z.srv", "a.srv", "m.srv"]:
            (tmp_path / n).write_text("print 1\n", encoding="utf-8")
        a = [c.path for c in sm.Smoker(root=tmp_path).scan()]
        b = [c.path for c in sm.Smoker(root=tmp_path).scan()]
        assert a == b == sorted(a)

    def test_scan_detects_test_files(self, tmp_path):
        (tmp_path / "test_things.srv").write_text("assert 1\n", encoding="utf-8")
        (tmp_path / "demo.srv").write_text("print 1\n", encoding="utf-8")
        cands = {c.path: c for c in sm.Smoker(root=tmp_path).scan()}
        assert cands["test_things.srv"].is_test is True
        assert cands["demo.srv"].is_test is False

    def test_scan_no_subdirs(self, tmp_path):
        (tmp_path / "a.srv").write_text("print 1\n", encoding="utf-8")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.srv").write_text("print 1\n", encoding="utf-8")
        cands = sm.Smoker(root=tmp_path, include_subdirs=False).scan()
        assert [c.path for c in cands] == ["a.srv"]

    def test_scan_recursive_default(self, tmp_path):
        (tmp_path / "a.srv").write_text("print 1\n", encoding="utf-8")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.srv").write_text("print 1\n", encoding="utf-8")
        cands = sm.Smoker(root=tmp_path).scan()
        assert {c.path for c in cands} == {"a.srv", "sub/b.srv"}

    def test_scan_feature_weight_uses_overrides(self, tmp_path):
        (tmp_path / "a.srv").write_text("if x then y\n", encoding="utf-8")
        # Default weight for if_else is 5; override to 99
        base = sm.Smoker(root=tmp_path).scan()[0].feature_weight
        boosted = sm.Smoker(
            root=tmp_path, feature_weights={"if_else": 99}
        ).scan()[0].feature_weight
        assert boosted == base + (99 - 5)


# ── Smoker.recommend ──────────────────────────────────────────────────────

class TestRecommend:
    def test_recommend_empty_root(self, tmp_path):
        slate = sm.Smoker(root=tmp_path).recommend()
        assert slate.total_candidates == 0
        assert slate.picks == []
        assert slate.coverage_score == 0.0
        assert slate.estimated_seconds == 0.0
        # All catalogue features are uncovered.
        assert len(slate.uncovered_features) == len(sm.FEATURE_CATALOGUE)

    def test_p0_tests_always_first(self, tmp_path):
        (tmp_path / "demo.srv").write_text(
            "if a then b\nfor x in xs\n  print x\n", encoding="utf-8"
        )
        (tmp_path / "test_x.srv").write_text("assert 1 == 1\n", encoding="utf-8")
        slate = sm.Smoker(root=tmp_path).recommend()
        assert slate.picks[0].tier == "P0"
        assert slate.picks[0].path == "test_x.srv"

    def test_no_duplicate_paths_picked(self, tmp_path):
        for i in range(5):
            (tmp_path / f"d{i}.srv").write_text(
                f"function f{i}()\n  print {i}\n", encoding="utf-8"
            )
        slate = sm.Smoker(root=tmp_path).recommend()
        paths = [p.path for p in slate.picks]
        assert len(paths) == len(set(paths))

    def test_budget_is_respected(self, tmp_path):
        # Each file uses ~0.2s (floor). Budget of 0.5s should cap picks tightly.
        for i in range(20):
            (tmp_path / f"d{i}.srv").write_text(
                f"function f{i}()\n", encoding="utf-8"
            )
        slate = sm.Smoker(root=tmp_path).recommend(budget_seconds=0.5)
        # Allow slight overshoot only when the very first greedy pick must seed
        # coverage; never more than one extra file beyond budget.
        assert slate.estimated_seconds <= 0.5 + 0.3

    def test_top_caps_picks(self, tmp_path):
        for i in range(10):
            (tmp_path / f"d{i}.srv").write_text(
                f"function f{i}()\n  print {i}\nfor x in xs\n  break\n",
                encoding="utf-8",
            )
        slate = sm.Smoker(root=tmp_path).recommend(top=3)
        assert len(slate.picks) == 3

    def test_p3_fills_tail_when_top_exceeds_useful_picks(self, tmp_path):
        # Two demos with identical coverage → only one is "useful";
        # asking for top=3 should fill the rest with P3 duplicate-coverage picks.
        (tmp_path / "a.srv").write_text("if x then y\n", encoding="utf-8")
        (tmp_path / "b.srv").write_text("if x then y\n", encoding="utf-8")
        (tmp_path / "c.srv").write_text("if x then y\n", encoding="utf-8")
        slate = sm.Smoker(root=tmp_path).recommend(top=3)
        tiers = [p.tier for p in slate.picks]
        assert tiers.count("P3") >= 1
        assert len(slate.picks) == 3

    def test_coverage_score_increases_with_coverage(self, tmp_path):
        (tmp_path / "narrow.srv").write_text("print 1\n", encoding="utf-8")
        narrow = sm.Smoker(root=tmp_path).recommend()

        (tmp_path / "wide.srv").write_text(
            textwrap.dedent("""\
                function f()
                  for x in xs
                    if x then y
                    while c
                      break
                  print x
                  try
                    risky()
                  catch e
                    print e
                """),
            encoding="utf-8",
        )
        wide = sm.Smoker(root=tmp_path).recommend()
        assert wide.coverage_score > narrow.coverage_score

    def test_coverage_score_is_normalized_0_to_1(self, tmp_path):
        (tmp_path / "a.srv").write_text("if x then y\n", encoding="utf-8")
        slate = sm.Smoker(root=tmp_path).recommend()
        assert 0.0 <= slate.coverage_score <= 1.0

    def test_p1_tier_for_high_yield_picks(self, tmp_path):
        # A single demo that touches 3+ new features should be P1.
        (tmp_path / "rich.srv").write_text(
            textwrap.dedent("""\
                function f()
                  for x in xs
                    if x then y
                """),
            encoding="utf-8",
        )
        slate = sm.Smoker(root=tmp_path).recommend()
        # Skip any P0s; first non-P0 should be P1.
        non_p0 = [p for p in slate.picks if p.tier != "P0"]
        assert non_p0 and non_p0[0].tier == "P1"

    def test_p2_for_small_incremental_pick(self, tmp_path):
        # One rich file claims most features; a second file adds just one.
        (tmp_path / "rich.srv").write_text(
            "function f()\n  for x in xs\n    if x then y\n", encoding="utf-8"
        )
        (tmp_path / "tiny.srv").write_text("xs |> map\n", encoding="utf-8")
        slate = sm.Smoker(root=tmp_path).recommend()
        non_p0 = [p for p in slate.picks if p.tier != "P0"]
        tiers = [p.tier for p in non_p0]
        assert "P1" in tiers
        # The tiny pipe-only file adds only one feature → P2
        assert "P2" in tiers

    def test_uncovered_features_disjoint_from_covered(self, tmp_path):
        (tmp_path / "a.srv").write_text(
            "function f()\n  for x in xs\n    if x then y\n", encoding="utf-8"
        )
        slate = sm.Smoker(root=tmp_path).recommend()
        assert set(slate.covered_features).isdisjoint(set(slate.uncovered_features))
        assert (
            set(slate.covered_features) | set(slate.uncovered_features)
            == set(sm.FEATURE_CATALOGUE)
        )


# ── CLI ────────────────────────────────────────────────────────────────────

class TestCli:
    def test_main_runs_on_empty_dir(self, tmp_path, capsys):
        rc = sm.main(["--root", str(tmp_path)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "sauravsmoke" in out

    def test_main_json_format(self, tmp_path, capsys):
        (tmp_path / "a.srv").write_text("if x then y\n", encoding="utf-8")
        rc = sm.main(["--root", str(tmp_path), "--format", "json"])
        out = capsys.readouterr().out
        assert rc == 0
        obj = json.loads(out)
        assert obj["total_candidates"] == 1

    def test_main_respects_budget(self, tmp_path, capsys):
        for i in range(5):
            (tmp_path / f"d{i}.srv").write_text("print 1\n", encoding="utf-8")
        rc = sm.main(["--root", str(tmp_path), "--budget", "0.3"])
        assert rc == 0

    def test_main_respects_top(self, tmp_path, capsys):
        for i in range(5):
            (tmp_path / f"d{i}.srv").write_text(
                f"function f{i}()\n", encoding="utf-8"
            )
        rc = sm.main(["--root", str(tmp_path), "--top", "2", "--format", "json"])
        out = capsys.readouterr().out
        obj = json.loads(out)
        assert len(obj["picks"]) <= 2
        assert rc == 0

    def test_main_no_subdirs(self, tmp_path, capsys):
        (tmp_path / "a.srv").write_text("print 1\n", encoding="utf-8")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.srv").write_text("print 1\n", encoding="utf-8")
        rc = sm.main([
            "--root", str(tmp_path), "--no-subdirs", "--format", "json",
        ])
        out = capsys.readouterr().out
        obj = json.loads(out)
        assert obj["total_candidates"] == 1
        assert rc == 0
