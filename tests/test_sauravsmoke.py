"""Tests for sauravsmoke."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import sauravsmoke as ss


@pytest.fixture
def project(tmp_path: Path) -> Path:
    # A test file - must always make it into the slate as P0
    (tmp_path / "test_basics.srv").write_text(
        "assert 1 + 1 == 2\nprint \"ok\"\n", encoding="utf-8"
    )
    # A demo with rich language coverage
    (tmp_path / "control_demo.srv").write_text(
        'function double x\n'
        '    return x * 2\n'
        'for i = 0 to 5\n'
        '    if i > 2\n'
        '        print i\n'
        'nums = [1, 2, 3]\n'
        'for n in nums\n'
        '    print f"item {n}"\n'
        'doubled = map (double) nums\n'
        'piped = "hi" |> upper\n'
        'sq = lambda x -> x * x\n',
        encoding="utf-8",
    )
    # A demo with very small extra coverage
    (tmp_path / "small_demo.srv").write_text(
        'print "hello"\n', encoding="utf-8"
    )
    # A demo that duplicates the rich one
    (tmp_path / "dup_demo.srv").write_text(
        'for i = 0 to 3\n    print i\n', encoding="utf-8"
    )
    return tmp_path


def test_scan_discovers_all_srv(project: Path) -> None:
    sm = ss.Smoker(root=project)
    cands = sm.scan()
    paths = sorted(c.path for c in cands)
    assert paths == ["control_demo.srv", "dup_demo.srv",
                     "small_demo.srv", "test_basics.srv"]


def test_test_files_become_p0(project: Path) -> None:
    plan = ss.Smoker(root=project).recommend()
    p0 = [p for p in plan.picks if p.tier == "P0"]
    assert len(p0) == 1
    assert p0[0].path == "test_basics.srv"


def test_rich_demo_picked_before_small(project: Path) -> None:
    plan = ss.Smoker(root=project).recommend()
    non_p0 = [p for p in plan.picks if p.tier != "P0"]
    assert non_p0, "expected at least one greedy pick"
    # The rich control demo should be the first greedy pick
    assert non_p0[0].path == "control_demo.srv"
    assert non_p0[0].tier in {"P1", "P2"}
    assert len(non_p0[0].new_features) >= 3


def test_coverage_grows_monotonically(project: Path) -> None:
    plan = ss.Smoker(root=project).recommend()
    cums = [p.cumulative_features for p in plan.picks]
    assert cums == sorted(cums)


def test_uncovered_reported(project: Path) -> None:
    plan = ss.Smoker(root=project).recommend()
    # We didn't touch http / regex / csv in fixtures, expect gaps
    assert "http" in plan.uncovered_features
    assert "regex" in plan.uncovered_features


def test_budget_caps_total_seconds(project: Path) -> None:
    # Tiny budget should keep us tight; tests still run (P0 is unconditional)
    plan = ss.Smoker(root=project).recommend(budget_seconds=0.5)
    # P0 always runs but greedy may stop early
    assert plan.estimated_seconds >= 0
    # Should not have picked the duplicate
    assert "dup_demo.srv" not in [p.path for p in plan.picks]


def test_top_caps_pick_count(project: Path) -> None:
    plan = ss.Smoker(root=project).recommend(top=2)
    assert len(plan.picks) <= 2


def test_top_fills_with_p3_when_room_remains(project: Path) -> None:
    # No budget, large top -> P3 tail picks up duplicate-coverage demos
    plan = ss.Smoker(root=project).recommend(top=10)
    tiers = [p.tier for p in plan.picks]
    # We should see at least one P3 (the dup demo)
    assert "P3" in tiers
    p3_paths = {p.path for p in plan.picks if p.tier == "P3"}
    assert "dup_demo.srv" in p3_paths


def test_no_files(tmp_path: Path) -> None:
    plan = ss.Smoker(root=tmp_path).recommend()
    assert plan.total_candidates == 0
    assert plan.picks == []
    assert plan.coverage_score == 0.0


def test_format_text(project: Path) -> None:
    plan = ss.Smoker(root=project).recommend()
    txt = plan.format("text")
    assert "sauravsmoke" in txt
    assert "test_basics.srv" in txt
    assert "[P0]" in txt


def test_format_md(project: Path) -> None:
    plan = ss.Smoker(root=project).recommend()
    md = plan.format("md")
    assert md.startswith("# sauravsmoke slate")
    assert "| # |" in md
    assert "`test_basics.srv`" in md


def test_format_json_roundtrip(project: Path) -> None:
    plan = ss.Smoker(root=project).recommend()
    data = json.loads(plan.format("json"))
    assert data["total_candidates"] == 4
    assert {p["path"] for p in data["picks"]} >= {"test_basics.srv",
                                                  "control_demo.srv"}
    assert 0.0 <= data["coverage_score"] <= 1.0


def test_unknown_format_raises(project: Path) -> None:
    plan = ss.Smoker(root=project).recommend()
    with pytest.raises(ValueError):
        plan.format("xml")


def test_cli_runs(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = ss.main(["--root", str(project), "--format", "json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["total_candidates"] == 4


def test_detect_features_picks_obvious_things() -> None:
    src = (
        'function add x y\n    return x + y\n'
        'for i = 0 to 3\n    print i\n'
        'sq = lambda x -> x * x\n'
        'msg = f"hi {sq 2}"\n'
        '"hello" |> upper\n'
    )
    feats = set(ss.detect_features(src))
    assert {"function_def", "for_range", "lambda", "fstring", "pipe"} <= feats
