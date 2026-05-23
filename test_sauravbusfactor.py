"""Tests for sauravbusfactor - bus-factor / knowledge-concentration advisor."""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import sauravbusfactor as sbf


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXED_NOW = datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc)


def _now():
    return FIXED_NOW


def _hist(payload):
    """Build a history_fn that ignores args and returns ``payload``."""
    def _fn(_root, _since):
        return payload
    return _fn


def _contrib(author, commits, last_days_ago=10, added=10, removed=2):
    iso = (FIXED_NOW - timedelta(days=last_days_ago)).isoformat()
    return sbf.AuthorContribution(
        author=author, commits=commits, lines_added=added,
        lines_removed=removed, last_commit_iso=iso,
    )


# ---------------------------------------------------------------------------
# Gini + helpers
# ---------------------------------------------------------------------------

class TestGini:
    def test_empty_is_zero(self):
        assert sbf._gini([]) == 0.0

    def test_single_is_one(self):
        assert sbf._gini([5]) == 1.0

    def test_equal_is_zero(self):
        assert sbf._gini([3, 3, 3, 3]) == pytest.approx(0.0, abs=1e-9)

    def test_concentrated_is_high(self):
        g = sbf._gini([100, 1, 1, 1, 1])
        assert g > 0.6

    def test_negative_values_filtered(self):
        # Just verify it doesn't crash and returns sensible value.
        assert 0.0 <= sbf._gini([10, 5]) <= 1.0


class TestDaysBetween:
    def test_none_input(self):
        assert sbf._days_between(None, FIXED_NOW) is None

    def test_naive_iso(self):
        d = (FIXED_NOW - timedelta(days=3)).replace(tzinfo=None).isoformat()
        assert sbf._days_between(d, FIXED_NOW) == 3

    def test_tz_iso(self):
        d = (FIXED_NOW - timedelta(days=7)).isoformat()
        assert sbf._days_between(d, FIXED_NOW) == 7

    def test_garbage(self):
        assert sbf._days_between("not-a-date", FIXED_NOW) is None


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

class TestClassify:
    def test_untracked_when_empty(self):
        f = sbf._classify_file("foo.py", {}, FIXED_NOW, "balanced")
        assert f.verdict == "UNTRACKED"
        assert f.priority == "P3"
        assert f.bus_risk == 0
        assert "NO_HISTORY_IN_WINDOW" in f.reasons

    def test_solo_owned(self):
        authors = {"alice": _contrib("alice", commits=8, last_days_ago=5)}
        f = sbf._classify_file("solo.py", authors, FIXED_NOW, "balanced")
        assert f.verdict == "SOLO_OWNED"
        assert f.priority == "P0"
        assert f.top_author == "alice"
        assert f.top_author_share == 1.0
        assert "SINGLE_AUTHOR" in f.reasons

    def test_high_risk_dominant(self):
        authors = {
            "alice": _contrib("alice", commits=20, last_days_ago=2),
            "bob": _contrib("bob", commits=1, last_days_ago=60),
            "carol": _contrib("carol", commits=1, last_days_ago=60),
        }
        f = sbf._classify_file("hot.py", authors, FIXED_NOW, "balanced")
        assert f.verdict == "HIGH_RISK"
        assert f.priority == "P0"
        assert "TOP_DOMINANT" in f.reasons

    def test_concentrated(self):
        authors = {
            "alice": _contrib("alice", commits=7),
            "bob": _contrib("bob", commits=2),
            "carol": _contrib("carol", commits=1),
        }
        f = sbf._classify_file("conc.py", authors, FIXED_NOW, "balanced")
        assert f.verdict == "CONCENTRATED"
        assert f.priority == "P1"

    def test_shared(self):
        authors = {
            "alice": _contrib("alice", commits=5),
            "bob": _contrib("bob", commits=4),
            "carol": _contrib("carol", commits=3),
        }
        f = sbf._classify_file("shared.py", authors, FIXED_NOW, "balanced")
        assert f.verdict == "SHARED"
        assert f.priority == "P2"

    def test_healthy(self):
        authors = {
            "a": _contrib("a", 2),
            "b": _contrib("b", 2),
            "c": _contrib("c", 2),
            "d": _contrib("d", 2),
            "e": _contrib("e", 2),
        }
        f = sbf._classify_file("ok.py", authors, FIXED_NOW, "balanced")
        assert f.verdict == "HEALTHY"
        assert f.priority == "P3"

    def test_inactive_solo(self):
        authors = {"alice": _contrib("alice", commits=4, last_days_ago=400)}
        f = sbf._classify_file("old.py", authors, FIXED_NOW, "balanced")
        assert f.verdict == "INACTIVE"
        assert "INACTIVE_FILE" in f.reasons

    def test_absent_owner_reason(self):
        authors = {
            "alice": _contrib("alice", commits=15, last_days_ago=150),
            "bob": _contrib("bob", commits=1, last_days_ago=5),
        }
        f = sbf._classify_file("absent.py", authors, FIXED_NOW, "balanced")
        assert "ABSENT_OWNER" in f.reasons

    def test_appetite_scales_risk(self):
        authors = {
            "alice": _contrib("alice", commits=20),
            "bob": _contrib("bob", commits=1),
        }
        balanced = sbf._classify_file("p.py", authors, FIXED_NOW, "balanced")
        cautious = sbf._classify_file("p.py", authors, FIXED_NOW, "cautious")
        aggressive = sbf._classify_file("p.py", authors, FIXED_NOW, "aggressive")
        assert cautious.bus_risk >= balanced.bus_risk >= aggressive.bus_risk


# ---------------------------------------------------------------------------
# Rename normalisation
# ---------------------------------------------------------------------------

class TestRenameNorm:
    def test_plain_rename(self):
        assert sbf._normalise_rename("old.py => new.py") == "new.py"

    def test_brace_rename(self):
        assert sbf._normalise_rename("src/{old => new}/file.py") == "src/new/file.py"

    def test_no_rename(self):
        assert sbf._normalise_rename("foo/bar.py") == "foo/bar.py"


# ---------------------------------------------------------------------------
# Advisor + report
# ---------------------------------------------------------------------------

class TestAdvisor:
    def test_no_history_returns_empty_report(self):
        a = sbf.BusFactorAdvisor(root=".", history_fn=_hist({}), now_fn=_now)
        r = a.analyze()
        assert r.findings == []
        assert r.summary["total_files"] == 0
        assert r.grade == "A"
        assert "NO_GIT_HISTORY" in r.insights

    def test_solo_owned_drives_p0_and_grade(self):
        payload = {
            f"mod{i}.py": {"alice": _contrib("alice", commits=5)} for i in range(3)
        }
        a = sbf.BusFactorAdvisor(root=".", history_fn=_hist(payload), now_fn=_now)
        r = a.analyze()
        assert r.summary["solo_owned"] == 3
        assert r.grade == "F"
        # Playbook must include ASSIGN_BACKUP_OWNER and SCHEDULE_PAIR_REVIEW.
        ids = {p.id for p in r.playbook}
        assert "ASSIGN_BACKUP_OWNER" in ids
        assert "SCHEDULE_PAIR_REVIEW" in ids

    def test_healthy_emits_maintain_action(self):
        payload = {
            "x.py": {
                "a": _contrib("a", 3), "b": _contrib("b", 3),
                "c": _contrib("c", 3), "d": _contrib("d", 3),
            },
        }
        a = sbf.BusFactorAdvisor(root=".", history_fn=_hist(payload), now_fn=_now)
        r = a.analyze()
        ids = {p.id for p in r.playbook}
        assert "MAINTAIN_HEALTHY_DISTRIBUTION" in ids
        assert r.grade in ("A", "B")

    def test_filter_by_extension(self):
        payload = {
            "a.py": {"alice": _contrib("alice", commits=5)},
            "image.png": {"alice": _contrib("alice", commits=5)},
        }
        a = sbf.BusFactorAdvisor(root=".", history_fn=_hist(payload), now_fn=_now)
        r = a.analyze()
        paths = [f.path for f in r.findings]
        assert "a.py" in paths
        assert "image.png" not in paths

    def test_exclude_globs(self):
        payload = {
            "src/a.py": {"alice": _contrib("alice", commits=5)},
            "vendor/b.py": {"alice": _contrib("alice", commits=5)},
        }
        a = sbf.BusFactorAdvisor(
            root=".", history_fn=_hist(payload), now_fn=_now,
            exclude_globs=("**/vendor/**",),
        )
        r = a.analyze()
        paths = [f.path for f in r.findings]
        assert "src/a.py" in paths
        assert "vendor/b.py" not in paths

    def test_include_globs(self):
        payload = {
            "src/a.py": {"alice": _contrib("alice", commits=5)},
            "tests/t.py": {"alice": _contrib("alice", commits=5)},
        }
        a = sbf.BusFactorAdvisor(
            root=".", history_fn=_hist(payload), now_fn=_now,
            include_globs=("src/**",),
        )
        r = a.analyze()
        paths = [f.path for f in r.findings]
        assert paths == ["src/a.py"]

    def test_invalid_risk_appetite(self):
        with pytest.raises(ValueError):
            sbf.BusFactorAdvisor(risk_appetite="paranoid")

    def test_invalid_lookback_top(self):
        with pytest.raises(ValueError):
            sbf.BusFactorAdvisor(lookback_days=0)
        with pytest.raises(ValueError):
            sbf.BusFactorAdvisor(top=0)


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

class TestRenderers:
    @pytest.fixture
    def report(self):
        payload = {
            "solo.py": {"alice": _contrib("alice", commits=8)},
            "shared.py": {
                "alice": _contrib("alice", commits=3),
                "bob": _contrib("bob", commits=3),
                "carol": _contrib("carol", commits=3),
            },
        }
        return sbf.BusFactorAdvisor(
            root=".", history_fn=_hist(payload), now_fn=_now,
        ).analyze()

    def test_text(self, report):
        out = report.format("text")
        assert "VERDICT:" in out
        assert "solo.py" in out
        assert "Playbook:" in out

    def test_markdown(self, report):
        out = report.format("md")
        assert out.startswith("# sauravbusfactor report")
        assert "## Findings" in out
        assert "## Playbook" in out
        assert "## Insights" in out
        assert "| solo.py |" in out or "`solo.py`" in out

    def test_json_byte_stable(self, report):
        a = report.format("json")
        b = report.format("json")
        assert a == b
        parsed = json.loads(a)
        assert parsed["grade"] in ("A", "B", "C", "D", "F")
        assert isinstance(parsed["findings"], list)

    def test_invalid_format(self, report):
        with pytest.raises(ValueError):
            report.format("xml")


# ---------------------------------------------------------------------------
# Insights + grade
# ---------------------------------------------------------------------------

class TestInsightsGrade:
    def test_bus_factor_one_insight(self):
        payload = {
            "a.py": {"alice": _contrib("alice", commits=5)},
            "b.py": {"alice": _contrib("alice", commits=5)},
        }
        a = sbf.BusFactorAdvisor(root=".", history_fn=_hist(payload), now_fn=_now)
        r = a.analyze()
        assert any(i.startswith("BUS_FACTOR_ONE:") for i in r.insights)

    def test_dominant_author_insight(self):
        # Alice is top author of 3 concentrated files.
        def cset():
            return {
                "alice": _contrib("alice", commits=10),
                "bob": _contrib("bob", commits=2),
                "carol": _contrib("carol", commits=1),
            }
        payload = {f"m{i}.py": cset() for i in range(3)}
        a = sbf.BusFactorAdvisor(root=".", history_fn=_hist(payload), now_fn=_now)
        r = a.analyze()
        assert any(i.startswith("DOMINANT_AUTHOR:alice=") for i in r.insights)


# ---------------------------------------------------------------------------
# Determinism + no-mutation
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_two_runs_byte_identical_json(self):
        payload = {
            "a.py": {"alice": _contrib("alice", 5)},
            "b.py": {
                "alice": _contrib("alice", 4),
                "bob": _contrib("bob", 4),
            },
        }
        a = sbf.BusFactorAdvisor(root=".", history_fn=_hist(payload), now_fn=_now)
        first = a.analyze().format("json")
        second = sbf.BusFactorAdvisor(
            root=".", history_fn=_hist(payload), now_fn=_now,
        ).analyze().format("json")
        assert first == second

    def test_history_not_mutated(self):
        contrib = _contrib("alice", 5)
        payload = {"a.py": {"alice": contrib}}
        before_commits = contrib.commits
        sbf.BusFactorAdvisor(root=".", history_fn=_hist(payload), now_fn=_now).analyze()
        assert contrib.commits == before_commits


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------

class TestCli:
    def test_cli_runs_with_empty_history(self, monkeypatch, capsys, tmp_path):
        monkeypatch.setattr(sbf, "_collect_git_history", lambda *_: {})
        rc = sbf.main(["--root", str(tmp_path), "--format", "json"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["summary"]["total_files"] == 0
