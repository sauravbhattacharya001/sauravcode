"""Unit tests for ``sauravhotspot`` - the agentic churn/risk advisor.

These tests stub out git by monkey-patching ``HotspotAdvisor._git`` so they
run in an arbitrary temp directory and do not depend on the repo's real
history. Filesystem-backed metrics (line count, existence) use real files
written to ``tmp_path``.
"""

from __future__ import annotations

import json
import textwrap
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import sauravhotspot as sh


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_FIXED_NOW = datetime(2026, 5, 23, 0, 0, 0, tzinfo=timezone.utc)


def _now() -> datetime:
    return _FIXED_NOW


def _commit_line(sha: str, author: str, ts: int, subject: str) -> str:
    # Matches the --pretty=format:%x00COMMIT%x00%H%x00%an%x00%at%x00%s
    return f"\x00COMMIT\x00{sha}\x00{author}\x00{ts}\x00{subject}"


def _numstat(ins: int, dele: int, path: str) -> str:
    return f"{ins}\t{dele}\t{path}"


def _build_log(*lines: str) -> str:
    return "\n".join(lines)


def _ts(days_ago: float) -> int:
    return int(_FIXED_NOW.timestamp() - days_ago * 86400)


def _make_advisor(
    tmp_path: Path,
    log_text: str,
    *,
    lookback_days: int = 90,
    top: int = 20,
    risk_appetite: str = "balanced",
    include_globs=None,
    exclude_globs=None,
) -> sh.HotspotAdvisor:
    advisor = sh.HotspotAdvisor(
        root=tmp_path,
        lookback_days=lookback_days,
        top=top,
        risk_appetite=risk_appetite,
        include_globs=include_globs,
        exclude_globs=exclude_globs,
        now_fn=_now,
    )

    def fake_git(*args: str) -> str:
        if args and args[0] == "log":
            return log_text
        return ""

    advisor._git = fake_git  # type: ignore[assignment]
    return advisor


def _touch(tmp_path: Path, rel: str, *, lines: int = 10) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x = 1\n" * lines, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Configuration / constructor
# ---------------------------------------------------------------------------


class TestConfiguration(unittest.TestCase):
    def test_default_exclude_globs_constant_exposed(self):
        self.assertIn(".git/*", sh.DEFAULT_EXCLUDE_GLOBS)
        self.assertIn("node_modules/*", sh.DEFAULT_EXCLUDE_GLOBS)
        # Constant must be a tuple so it cannot be mutated by callers
        self.assertIsInstance(sh.DEFAULT_EXCLUDE_GLOBS, tuple)

    def test_advisor_uses_default_excludes_when_none_passed(self):
        adv = sh.HotspotAdvisor(root=".", now_fn=_now)
        self.assertEqual(adv.exclude_globs, sh.DEFAULT_EXCLUDE_GLOBS)

    def test_advisor_overrides_excludes(self):
        adv = sh.HotspotAdvisor(root=".", exclude_globs=["custom/*"], now_fn=_now)
        self.assertEqual(adv.exclude_globs, ("custom/*",))

    def test_invalid_risk_appetite_raises(self):
        with self.assertRaises(ValueError):
            sh.HotspotAdvisor(root=".", risk_appetite="reckless", now_fn=_now)

    def test_invalid_lookback_raises(self):
        with self.assertRaises(ValueError):
            sh.HotspotAdvisor(root=".", lookback_days=0, now_fn=_now)
        with self.assertRaises(ValueError):
            sh.HotspotAdvisor(root=".", lookback_days=-3, now_fn=_now)

    def test_invalid_top_raises(self):
        with self.assertRaises(ValueError):
            sh.HotspotAdvisor(root=".", top=0, now_fn=_now)

    def test_priority_label_helper(self):
        self.assertEqual(sh._pname(0), "P0")
        self.assertEqual(sh._pname(3), "P3")


# ---------------------------------------------------------------------------
# Empty / minimal history
# ---------------------------------------------------------------------------


class TestEmptyHistory(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_empty_log_produces_healthy_report(self):
        adv = _make_advisor(self.tmp_path, "")
        rep = adv.analyze()
        self.assertEqual(rep.findings, [])
        self.assertEqual(rep.portfolio_risk_score, 0.0)
        self.assertEqual(rep.grade, "A")
        self.assertIn("EMPTY_HISTORY", rep.insights)
        # Healthy portfolio playbook entry
        ids = [a.id for a in rep.playbook]
        self.assertIn("HEALTHY_PORTFOLIO", ids)

    def test_empty_log_text_format_mentions_no_candidates(self):
        adv = _make_advisor(self.tmp_path, "")
        text = adv.analyze().format("text")
        self.assertIn("no candidate files", text)

    def test_empty_log_markdown_format(self):
        adv = _make_advisor(self.tmp_path, "")
        md = adv.analyze().format("md")
        self.assertIn("# Hotspot report", md)
        self.assertIn("No candidate files", md)

    def test_empty_log_json_format_parses(self):
        adv = _make_advisor(self.tmp_path, "")
        payload = json.loads(adv.analyze().format("json"))
        self.assertEqual(payload["findings"], [])
        self.assertEqual(payload["grade"], "A")


# ---------------------------------------------------------------------------
# Path / glob filtering
# ---------------------------------------------------------------------------


class TestPathFiltering(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_default_excludes_drop_git_and_node_modules(self):
        _touch(self.tmp_path, "src/app.py", lines=50)
        log = _build_log(
            _commit_line("a", "alice", _ts(1), "feat"),
            _numstat(10, 0, "src/app.py"),
            _numstat(5, 0, "node_modules/lib/index.js"),
            _numstat(3, 0, ".git/hooks/pre-commit"),
        )
        adv = _make_advisor(self.tmp_path, log)
        paths = [f.path for f in adv.analyze().findings]
        self.assertIn("src/app.py", paths)
        self.assertNotIn("node_modules/lib/index.js", paths)
        self.assertNotIn(".git/hooks/pre-commit", paths)

    def test_non_source_extension_dropped(self):
        log = _build_log(
            _commit_line("a", "alice", _ts(1), "data"),
            _numstat(1, 0, "data/x.bin"),
        )
        adv = _make_advisor(self.tmp_path, log)
        rep = adv.analyze()
        self.assertEqual(rep.findings, [])

    def test_no_extension_kept(self):
        # Files without extensions (e.g. "Makefile", "Dockerfile") used to
        # pass the suffix check; verify the optimized path preserves that.
        _touch(self.tmp_path, "Makefile", lines=20)
        log = _build_log(
            _commit_line("a", "alice", _ts(1), "build"),
            _numstat(2, 0, "Makefile"),
        )
        adv = _make_advisor(self.tmp_path, log)
        paths = [f.path for f in adv.analyze().findings]
        self.assertIn("Makefile", paths)

    def test_include_glob_restricts_set(self):
        _touch(self.tmp_path, "src/app.py", lines=20)
        _touch(self.tmp_path, "scripts/build.py", lines=20)
        log = _build_log(
            _commit_line("a", "alice", _ts(1), "feat"),
            _numstat(1, 0, "src/app.py"),
            _numstat(1, 0, "scripts/build.py"),
        )
        adv = _make_advisor(self.tmp_path, log, include_globs=["src/*"])
        paths = [f.path for f in adv.analyze().findings]
        self.assertEqual(paths, ["src/app.py"])

    def test_user_exclude_glob_applied(self):
        log = _build_log(
            _commit_line("a", "alice", _ts(1), "feat"),
            _numstat(1, 0, "src/app.py"),
            _numstat(1, 0, "src/legacy.py"),
        )
        adv = _make_advisor(
            self.tmp_path, log,
            exclude_globs=list(sh.DEFAULT_EXCLUDE_GLOBS) + ["*/legacy.py"],
        )
        paths = [f.path for f in adv.analyze().findings]
        self.assertNotIn("src/legacy.py", paths)

    def test_extension_case_insensitive(self):
        _touch(self.tmp_path, "src/App.PY", lines=10)
        log = _build_log(
            _commit_line("a", "alice", _ts(1), "feat"),
            _numstat(1, 0, "src/App.PY"),
        )
        adv = _make_advisor(self.tmp_path, log)
        paths = [f.path for f in adv.analyze().findings]
        self.assertIn("src/App.PY", paths)

    def test_path_with_dot_in_directory_only(self):
        # "scripts.old/build" - the only dot is in the directory, not the
        # filename. Optimized suffix-extraction must NOT mistake "scripts.old/build"
        # for an extension of ".old/build".
        _touch(self.tmp_path, "scripts.old/build", lines=5)
        log = _build_log(
            _commit_line("a", "alice", _ts(1), "feat"),
            _numstat(1, 0, "scripts.old/build"),
        )
        adv = _make_advisor(self.tmp_path, log)
        paths = [f.path for f in adv.analyze().findings]
        self.assertIn("scripts.old/build", paths)


# ---------------------------------------------------------------------------
# Stats aggregation
# ---------------------------------------------------------------------------


class TestStatsAggregation(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_commits_and_authors_aggregate(self):
        _touch(self.tmp_path, "src/app.py", lines=10)
        log = _build_log(
            _commit_line("a", "alice", _ts(2), "feat: thing"),
            _numstat(10, 1, "src/app.py"),
            _commit_line("b", "bob", _ts(1), "fix: bug in app"),
            _numstat(2, 2, "src/app.py"),
        )
        adv = _make_advisor(self.tmp_path, log)
        rep = adv.analyze()
        f = next(f for f in rep.findings if f.path == "src/app.py")
        self.assertEqual(f.stats.commits, 2)
        self.assertEqual(f.stats.fix_commits, 1)
        self.assertEqual(f.stats.insertions, 12)
        self.assertEqual(f.stats.deletions, 3)
        self.assertEqual(f.stats.distinct_authors, 2)

    def test_fix_regex_matches_keywords(self):
        for subject in [
            "fix: NPE",
            "bugfix for parser",
            "regression in CLI",
            "hotfix release",
            "Patch crash on startup",
            "revert bad refactor",
        ]:
            self.assertTrue(sh._FIX_RE.search(subject), subject)

    def test_fix_regex_ignores_unrelated_words(self):
        for subject in ["feat: new module", "docs: tidy README", "test: add coverage"]:
            self.assertFalse(sh._FIX_RE.search(subject), subject)

    def test_binary_diff_dashes_handled(self):
        _touch(self.tmp_path, "img/logo.py", lines=10)
        log = _build_log(
            _commit_line("a", "alice", _ts(1), "feat"),
            _numstat_raw := "-\t-\timg/logo.py",
        )
        adv = _make_advisor(self.tmp_path, log)
        rep = adv.analyze()
        f = next(f for f in rep.findings if f.path == "img/logo.py")
        self.assertEqual(f.stats.insertions, 0)
        self.assertEqual(f.stats.deletions, 0)
        self.assertEqual(f.stats.commits, 1)

    def test_last_change_days_tracks_most_recent(self):
        _touch(self.tmp_path, "a.py", lines=5)
        log = _build_log(
            _commit_line("a", "alice", _ts(60), "feat"),
            _numstat(1, 0, "a.py"),
            _commit_line("b", "alice", _ts(2), "feat"),
            _numstat(1, 0, "a.py"),
        )
        adv = _make_advisor(self.tmp_path, log)
        rep = adv.analyze()
        f = next(f for f in rep.findings if f.path == "a.py")
        self.assertIsNotNone(f.stats.last_change_days)
        # The MIN age is the most-recent commit (2 days ago)
        self.assertLess(f.stats.last_change_days, 3)

    def test_bad_timestamp_does_not_crash(self):
        _touch(self.tmp_path, "a.py", lines=5)
        log = _build_log(
            "\x00COMMIT\x00a\x00alice\x00notanint\x00feat",
            _numstat(1, 0, "a.py"),
        )
        adv = _make_advisor(self.tmp_path, log)
        rep = adv.analyze()
        f = next(f for f in rep.findings if f.path == "a.py")
        self.assertIsNone(f.stats.last_change_days)

    def test_missing_subject_no_crash(self):
        # subject field empty
        log = "\x00COMMIT\x00a\x00alice\x00" + str(_ts(1)) + "\x00\n" + _numstat(1, 0, "a.py")
        _touch(self.tmp_path, "a.py", lines=5)
        adv = _make_advisor(self.tmp_path, log)
        rep = adv.analyze()
        f = next(f for f in rep.findings if f.path == "a.py")
        self.assertEqual(f.stats.fix_commits, 0)

    def test_malformed_numstat_line_skipped(self):
        log = _build_log(
            _commit_line("a", "alice", _ts(1), "feat"),
            "not-a-numstat-line",
            _numstat(1, 0, "a.py"),
        )
        _touch(self.tmp_path, "a.py", lines=5)
        adv = _make_advisor(self.tmp_path, log)
        rep = adv.analyze()
        # One file recorded, not three
        self.assertEqual(len([f for f in rep.findings if f.stats.commits > 0]), 1)

    def test_missing_file_marked_not_exists(self):
        # file referenced in log but absent on disk -> exists=False, UNTRACKED
        log = _build_log(
            _commit_line("a", "alice", _ts(1), "feat"),
            _numstat(1, 0, "gone.py"),
        )
        adv = _make_advisor(self.tmp_path, log)
        rep = adv.analyze()
        f = next(f for f in rep.findings if f.path == "gone.py")
        self.assertFalse(f.stats.exists)
        self.assertEqual(f.verdict, sh.V_UNTRACKED)


# ---------------------------------------------------------------------------
# Scoring / verdicts / priority
# ---------------------------------------------------------------------------


class TestScoring(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _hot_log(self, path: str, *, commits: int, fix_ratio: float = 0.5) -> str:
        lines = []
        for i in range(commits):
            is_fix = i < int(commits * fix_ratio)
            subj = "fix: bug" if is_fix else "feat: thing"
            lines.append(_commit_line(f"sha{i:03d}", f"author{i % 5}", _ts(i + 1), subj))
            lines.append(_numstat(20, 5, path))
        return "\n".join(lines)

    def test_hotspot_classification(self):
        _touch(self.tmp_path, "hot.py", lines=2500)  # max complexity
        log = self._hot_log("hot.py", commits=40, fix_ratio=0.7)
        adv = _make_advisor(self.tmp_path, log)
        rep = adv.analyze()
        f = next(f for f in rep.findings if f.path == "hot.py")
        self.assertEqual(f.verdict, sh.V_HOTSPOT)
        self.assertEqual(f.priority, sh.P0)
        self.assertGreaterEqual(f.risk_score, 70)
        self.assertIn("HIGH_CHURN", f.reasons)
        self.assertIn("LARGE_MODULE", f.reasons)
        self.assertIn("BUG_PRONE", f.reasons)

    def test_stable_low_risk_file(self):
        _touch(self.tmp_path, "tiny.py", lines=20)
        log = _build_log(
            _commit_line("a", "alice", _ts(80), "feat"),
            _numstat(2, 0, "tiny.py"),
        )
        adv = _make_advisor(self.tmp_path, log)
        rep = adv.analyze()
        f = next(f for f in rep.findings if f.path == "tiny.py")
        self.assertIn(f.verdict, (sh.V_STABLE, sh.V_COOL))
        self.assertGreaterEqual(f.priority, sh.P2)

    def test_risk_score_bounded_0_100(self):
        _touch(self.tmp_path, "x.py", lines=5000)
        log = self._hot_log("x.py", commits=200, fix_ratio=0.99)
        adv = _make_advisor(self.tmp_path, log)
        rep = adv.analyze()
        for f in rep.findings:
            self.assertGreaterEqual(f.risk_score, 0.0)
            self.assertLessEqual(f.risk_score, 100.0)

    def test_cautious_appetite_raises_risk(self):
        _touch(self.tmp_path, "m.py", lines=400)
        log = self._hot_log("m.py", commits=8, fix_ratio=0.4)
        balanced = _make_advisor(self.tmp_path, log, risk_appetite="balanced").analyze()
        cautious = _make_advisor(self.tmp_path, log, risk_appetite="cautious").analyze()
        b = next(f.risk_score for f in balanced.findings if f.path == "m.py")
        c = next(f.risk_score for f in cautious.findings if f.path == "m.py")
        self.assertGreater(c, b)

    def test_aggressive_appetite_lowers_risk(self):
        _touch(self.tmp_path, "m.py", lines=400)
        log = self._hot_log("m.py", commits=8, fix_ratio=0.4)
        balanced = _make_advisor(self.tmp_path, log, risk_appetite="balanced").analyze()
        aggressive = _make_advisor(self.tmp_path, log, risk_appetite="aggressive").analyze()
        b = next(f.risk_score for f in balanced.findings if f.path == "m.py")
        a = next(f.risk_score for f in aggressive.findings if f.path == "m.py")
        self.assertLess(a, b)

    def test_bug_prone_small_file_promoted_to_p1(self):
        # Small file (low complexity) but very fix-heavy and modest commit count
        _touch(self.tmp_path, "b.py", lines=80)
        log = self._hot_log("b.py", commits=5, fix_ratio=1.0)
        rep = _make_advisor(self.tmp_path, log).analyze()
        f = next(f for f in rep.findings if f.path == "b.py")
        # Verdict ought to be at most WARM (no high complexity) - but priority
        # for COOL bug-prone files is promoted to P1 by the advisor.
        if f.verdict == sh.V_COOL:
            self.assertEqual(f.priority, sh.P1)

    def test_findings_ordered_by_risk_desc(self):
        _touch(self.tmp_path, "hi.py", lines=2000)
        _touch(self.tmp_path, "lo.py", lines=10)
        log = "\n".join([
            self._hot_log("hi.py", commits=30, fix_ratio=0.6),
            self._hot_log("lo.py", commits=2, fix_ratio=0.0),
        ])
        adv = _make_advisor(self.tmp_path, log)
        rep = adv.analyze()
        scores = [f.risk_score for f in rep.findings]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_top_cap_respected(self):
        log_lines = []
        for i in range(15):
            _touch(self.tmp_path, f"f{i}.py", lines=10)
            log_lines.append(_commit_line(f"s{i}", "alice", _ts(i + 1), "feat"))
            log_lines.append(_numstat(1, 0, f"f{i}.py"))
        adv = _make_advisor(self.tmp_path, "\n".join(log_lines), top=5)
        rep = adv.analyze()
        self.assertEqual(len(rep.findings), 5)


# ---------------------------------------------------------------------------
# Playbook / insights / portfolio
# ---------------------------------------------------------------------------


class TestPlaybookAndInsights(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_hotspot_triggers_refactor_and_regression_actions(self):
        _touch(self.tmp_path, "hot.py", lines=2500)
        log_lines = []
        for i in range(40):
            log_lines.append(_commit_line(f"s{i}", f"a{i % 4}", _ts(i + 1), "fix: bug"))
            log_lines.append(_numstat(10, 2, "hot.py"))
        adv = _make_advisor(self.tmp_path, "\n".join(log_lines))
        rep = adv.analyze()
        ids = {a.id for a in rep.playbook}
        self.assertIn("REFACTOR_HOTSPOT", ids)
        self.assertIn("ADD_REGRESSION_TESTS", ids)

    def test_oversized_module_triggers_split_action(self):
        _touch(self.tmp_path, "huge.py", lines=2000)
        log_lines = []
        for i in range(40):
            log_lines.append(_commit_line(f"s{i}", "a", _ts(i + 1), "fix" if i % 2 else "feat"))
            log_lines.append(_numstat(5, 1, "huge.py"))
        adv = _make_advisor(self.tmp_path, "\n".join(log_lines))
        rep = adv.analyze()
        ids = {a.id for a in rep.playbook}
        self.assertIn("SPLIT_OVERSIZED_MODULE", ids)

    def test_cautious_appetite_adds_weekly_review(self):
        _touch(self.tmp_path, "a.py", lines=100)
        log = _build_log(
            _commit_line("a", "alice", _ts(1), "feat"),
            _numstat(1, 0, "a.py"),
        )
        adv = _make_advisor(self.tmp_path, log, risk_appetite="cautious")
        rep = adv.analyze()
        ids = {a.id for a in rep.playbook}
        self.assertIn("SCHEDULE_HOTSPOT_REVIEW", ids)

    def test_aggressive_trims_p3_when_higher_priority_present(self):
        _touch(self.tmp_path, "hot.py", lines=2500)
        log_lines = []
        for i in range(40):
            log_lines.append(_commit_line(f"s{i}", f"a{i % 4}", _ts(i + 1), "fix: bug"))
            log_lines.append(_numstat(10, 2, "hot.py"))
        adv = _make_advisor(self.tmp_path, "\n".join(log_lines), risk_appetite="aggressive")
        rep = adv.analyze()
        for a in rep.playbook:
            self.assertLess(a.priority, sh.P3)

    def test_healthy_portfolio_action_when_no_risk(self):
        _touch(self.tmp_path, "a.py", lines=10)
        log = _build_log(
            _commit_line("a", "alice", _ts(80), "feat"),
            _numstat(1, 0, "a.py"),
        )
        adv = _make_advisor(self.tmp_path, log)
        rep = adv.analyze()
        ids = {a.id for a in rep.playbook}
        self.assertIn("HEALTHY_PORTFOLIO", ids)

    def test_playbook_sorted_by_priority(self):
        _touch(self.tmp_path, "hot.py", lines=2500)
        log_lines = []
        for i in range(40):
            log_lines.append(_commit_line(f"s{i}", f"a{i % 4}", _ts(i + 1), "fix: bug"))
            log_lines.append(_numstat(10, 2, "hot.py"))
        rep = _make_advisor(self.tmp_path, "\n".join(log_lines)).analyze()
        prios = [a.priority for a in rep.playbook]
        self.assertEqual(prios, sorted(prios))

    def test_active_development_zone_insight(self):
        # 5+ recently-changed files
        log_lines = []
        for i in range(6):
            _touch(self.tmp_path, f"r{i}.py", lines=200)
            for j in range(5):
                log_lines.append(_commit_line(f"s{i}_{j}", "a", _ts(j + 1), "feat"))
                log_lines.append(_numstat(1, 0, f"r{i}.py"))
        rep = _make_advisor(self.tmp_path, "\n".join(log_lines)).analyze()
        self.assertTrue(any(i.startswith("ACTIVE_DEVELOPMENT_ZONE") for i in rep.insights))

    def test_single_author_concentration_insight(self):
        log_lines = []
        for i in range(4):
            _touch(self.tmp_path, f"s{i}.py", lines=10)
            for j in range(6):
                log_lines.append(_commit_line(f"c{i}_{j}", "solo", _ts(j + 1), "feat"))
                log_lines.append(_numstat(1, 0, f"s{i}.py"))
        rep = _make_advisor(self.tmp_path, "\n".join(log_lines)).analyze()
        self.assertTrue(any(i.startswith("SINGLE_AUTHOR_CONCENTRATION") for i in rep.insights))

    def test_portfolio_score_and_grade(self):
        _touch(self.tmp_path, "a.py", lines=20)
        log = _build_log(
            _commit_line("a", "alice", _ts(80), "feat"),
            _numstat(1, 0, "a.py"),
        )
        rep = _make_advisor(self.tmp_path, log).analyze()
        self.assertGreaterEqual(rep.portfolio_risk_score, 0.0)
        self.assertLessEqual(rep.portfolio_risk_score, 100.0)
        self.assertIn(rep.grade, list("ABCDF"))


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------


class TestFormatters(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        _touch(self.tmp_path, "a.py", lines=200)
        log = _build_log(
            _commit_line("a", "alice", _ts(1), "fix: bug"),
            _numstat(5, 1, "a.py"),
        )
        self.report = _make_advisor(self.tmp_path, log).analyze()

    def tearDown(self):
        self._tmp.cleanup()

    def test_text_format_has_summary(self):
        txt = self.report.format("text")
        self.assertIn("Hotspot grade", txt)

    def test_markdown_format_has_tables(self):
        md = self.report.format("md")
        self.assertIn("# Hotspot report", md)
        self.assertIn("| Metric | Value |", md)

    def test_json_format_round_trips(self):
        payload = json.loads(self.report.format("json"))
        self.assertEqual(payload["grade"], self.report.grade)
        self.assertEqual(len(payload["findings"]), len(self.report.findings))

    def test_unknown_format_falls_back_to_text(self):
        out = self.report.format("yaml")
        self.assertIn("Hotspot grade", out)

    def test_format_none_defaults_to_text(self):
        out = self.report.format(None)  # type: ignore[arg-type]
        self.assertIn("Hotspot grade", out)


# ---------------------------------------------------------------------------
# git plumbing
# ---------------------------------------------------------------------------


class TestGitPlumbing(unittest.TestCase):
    def test_git_returns_empty_when_git_not_installed(self):
        adv = sh.HotspotAdvisor(root=".", now_fn=_now)
        with mock.patch("sauravhotspot.subprocess.run", side_effect=FileNotFoundError):
            self.assertEqual(adv._git("log"), "")

    def test_git_returns_empty_on_nonzero_exit(self):
        adv = sh.HotspotAdvisor(root=".", now_fn=_now)
        fake = mock.Mock(returncode=128, stdout="oops")
        with mock.patch("sauravhotspot.subprocess.run", return_value=fake):
            self.assertEqual(adv._git("log"), "")

    def test_git_returns_stdout_on_success(self):
        adv = sh.HotspotAdvisor(root=".", now_fn=_now)
        fake = mock.Mock(returncode=0, stdout="hello")
        with mock.patch("sauravhotspot.subprocess.run", return_value=fake):
            self.assertEqual(adv._git("log"), "hello")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_arg_parser_defaults(self):
        p = sh._build_arg_parser()
        ns = p.parse_args([])
        self.assertEqual(ns.root, ".")
        self.assertEqual(ns.lookback_days, 90)
        self.assertEqual(ns.top, 20)
        self.assertEqual(ns.risk, "balanced")
        self.assertEqual(ns.format, "text")

    def test_arg_parser_overrides(self):
        p = sh._build_arg_parser()
        ns = p.parse_args(["--lookback-days", "30", "--top", "5", "--risk", "cautious", "--format", "json"])
        self.assertEqual(ns.lookback_days, 30)
        self.assertEqual(ns.top, 5)
        self.assertEqual(ns.risk, "cautious")
        self.assertEqual(ns.format, "json")

    def test_main_runs_and_prints_report(self):
        # Patch HotspotAdvisor.analyze to a stub report so we don't depend on
        # the surrounding git history.
        from io import StringIO
        captured = StringIO()
        stub_report = mock.Mock(spec=sh.HotspotReport)
        stub_report.format.return_value = "STUB-OUTPUT"
        with mock.patch.object(sh.HotspotAdvisor, "analyze", return_value=stub_report), \
             mock.patch("sys.stdout", captured):
            rc = sh.main(["--format", "text"])
        self.assertEqual(rc, 0)
        self.assertIn("STUB-OUTPUT", captured.getvalue())

    def test_main_extends_default_excludes(self):
        # When --exclude is passed, main() should start from
        # DEFAULT_EXCLUDE_GLOBS and extend, not from a freshly-constructed
        # HotspotAdvisor.
        captured = {}

        def spy_init(self, **kwargs):
            captured["exclude_globs"] = kwargs.get("exclude_globs")
            self.root = Path(kwargs.get("root", "."))
            self.lookback_days = kwargs.get("lookback_days", 90)
            self.top = kwargs.get("top", 20)
            self.risk_appetite = kwargs.get("risk_appetite", "balanced")
            self.include_globs = ()
            self.exclude_globs = tuple(kwargs.get("exclude_globs") or ())
            self._now_fn = _now

        stub_report = mock.Mock()
        stub_report.format.return_value = "OK"
        with mock.patch.object(sh.HotspotAdvisor, "__init__", spy_init), \
             mock.patch.object(sh.HotspotAdvisor, "analyze", return_value=stub_report), \
             mock.patch("sys.stdout", new_callable=lambda: __import__("io").StringIO()):
            sh.main(["--exclude", "tests/*"])
        self.assertIsNotNone(captured["exclude_globs"])
        self.assertIn("tests/*", captured["exclude_globs"])
        # Default excludes preserved
        self.assertIn(".git/*", captured["exclude_globs"])


# ---------------------------------------------------------------------------
# Perf-related caching behaviour
# ---------------------------------------------------------------------------


class TestPathFilterCache(unittest.TestCase):
    """Indirectly verify the per-path filter cache by asserting that the
    behaviour for repeated path occurrences matches a single-pass evaluation.
    """

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_repeated_path_aggregates_consistently(self):
        _touch(self.tmp_path, "core/util.py", lines=30)
        log_lines = []
        # 50 commits all touching the same path
        for i in range(50):
            log_lines.append(_commit_line(f"s{i:03d}", f"a{i % 7}", _ts(i + 1), "feat"))
            log_lines.append(_numstat(3, 1, "core/util.py"))
        rep = _make_advisor(self.tmp_path, "\n".join(log_lines)).analyze()
        f = next(f for f in rep.findings if f.path == "core/util.py")
        self.assertEqual(f.stats.commits, 50)
        self.assertEqual(f.stats.insertions, 150)
        self.assertEqual(f.stats.deletions, 50)
        self.assertEqual(f.stats.distinct_authors, 7)


if __name__ == "__main__":
    unittest.main()
