"""Tests for sauravsentinel - the autonomous project health sentinel.

Focuses on the pure-Python pieces that have no UI:

* ``scan_file`` / ``scan_project`` - filesystem scanning that produces
  ``FileSnapshot`` / ``ProjectSnapshot`` records.
* ``_compute_health`` - the 0-100 health scoring formula.
* ``detect_regressions`` - the comparison engine that watches for
  health drops, complexity spikes, lint surges, declining trends, and
  per-file regressions.
* ``load_history`` / ``save_history`` and the goals counterparts -
  round-tripping the on-disk JSON store and tolerating corruption.
* ``check_goals`` - the goal-miss reporter, including the asymmetric
  semantics for ``health`` (target = floor) vs every other metric
  (target = ceiling).
* ``_grade`` and ``_quick_lint_from_path`` - small helpers that callers
  rely on for stable output.

These tests intentionally avoid the HTML/terminal-render functions and
the ``main`` CLI entry point - those exist purely for human consumption
and their formatting is allowed to evolve.
"""

from __future__ import annotations

import json
import os
import tempfile
import textwrap
import unittest
from dataclasses import asdict

import sauravsentinel as ss


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _make_snap(**overrides) -> ss.ProjectSnapshot:
    """Build a ProjectSnapshot with sane defaults for regression tests."""
    snap = ss.ProjectSnapshot(
        timestamp="2026-05-22T20:00:00",
        directory="/tmp/proj",
        total_files=3,
        total_lines=300,
        total_code_lines=240,
        total_functions=12,
        avg_complexity=10.0,
        max_complexity=15.0,
        health_score=85.0,
        lint_warnings=4,
        lint_errors=0,
        comment_ratio=15.0,
        files=[
            {"path": "a.srv", "lines": 100, "code_lines": 80,
             "complexity": 10.0, "functions": 4, "max_nesting": 2,
             "lint_warnings": 1, "hash": "aaaa"},
            {"path": "b.srv", "lines": 100, "code_lines": 80,
             "complexity": 12.0, "functions": 4, "max_nesting": 2,
             "lint_warnings": 2, "hash": "bbbb"},
            {"path": "c.srv", "lines": 100, "code_lines": 80,
             "complexity": 8.0, "functions": 4, "max_nesting": 2,
             "lint_warnings": 1, "hash": "cccc"},
        ],
    )
    for k, v in overrides.items():
        setattr(snap, k, v)
    return snap


# ---------------------------------------------------------------------------
# scan_file: single-file scanning
# ---------------------------------------------------------------------------

class ScanFileTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def _scan(self, name: str, body: str) -> ss.FileSnapshot:
        path = os.path.join(self.dir, name)
        _write(path, body)
        return ss.scan_file(path)

    def test_returns_filesnapshot(self):
        fs = self._scan("a.srv", "print 1\n")
        self.assertIsInstance(fs, ss.FileSnapshot)

    def test_records_file_hash(self):
        fs = self._scan("a.srv", "print 1\n")
        # MD5 truncated to 12 hex chars.
        self.assertEqual(len(fs.file_hash), 12)
        self.assertTrue(all(c in "0123456789abcdef" for c in fs.file_hash))

    def test_hash_changes_with_content(self):
        a = self._scan("a.srv", "print 1\n")
        b = self._scan("b.srv", "print 2\n")
        self.assertNotEqual(a.file_hash, b.file_hash)

    def test_missing_file_returns_blank_snapshot(self):
        fs = ss.scan_file(os.path.join(self.dir, "nope.srv"))
        self.assertEqual(fs.file_hash, "")
        self.assertEqual(fs.lines, 0)
        self.assertEqual(fs.code_lines, 0)

    def test_counts_lines_and_functions_when_present(self):
        body = textwrap.dedent("""\
            # this is a comment
            function add a b
                return a + b

            print add 1 2
        """)
        fs = self._scan("a.srv", body)
        self.assertGreater(fs.lines, 0)
        self.assertGreaterEqual(fs.code_lines, 1)


# ---------------------------------------------------------------------------
# _quick_lint_from_path: TODO/long-line/trailing-whitespace warnings
# ---------------------------------------------------------------------------

class QuickLintTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def _lint(self, body: str) -> int:
        path = os.path.join(self.dir, "x.srv")
        _write(path, body)
        return ss._quick_lint_from_path(path)

    def test_clean_file_has_zero_warnings(self):
        # Ends with a trailing newline (no warning) and no offences.
        self.assertEqual(self._lint("print 1\n"), 0)

    def test_trailing_whitespace_warns(self):
        # Two lines with trailing spaces.
        body = "print 1  \nprint 2\t\n"
        self.assertGreaterEqual(self._lint(body), 2)

    def test_long_line_warns(self):
        body = "print " + "x" * 200 + "\n"
        self.assertGreaterEqual(self._lint(body), 1)

    def test_todo_markers_warn(self):
        body = "# TODO: fix\n# FIXME later\n# regular comment\n"
        self.assertGreaterEqual(self._lint(body), 2)

    def test_missing_trailing_newline_warns(self):
        # Last line has content but file does not end with newline.
        body = "print 1"
        self.assertGreaterEqual(self._lint(body), 1)

    def test_missing_file_returns_zero(self):
        self.assertEqual(
            ss._quick_lint_from_path(os.path.join(self.dir, "ghost.srv")),
            0,
        )


# ---------------------------------------------------------------------------
# scan_project: directory scanning
# ---------------------------------------------------------------------------

class ScanProjectTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def test_empty_directory_health_is_zero(self):
        snap = ss.scan_project(self.dir)
        self.assertEqual(snap.total_files, 0)
        self.assertEqual(snap.health_score, 0.0)

    def test_aggregates_files(self):
        _write(os.path.join(self.dir, "a.srv"), "print 1\n")
        _write(os.path.join(self.dir, "b.srv"), "print 2\nprint 3\n")
        # A non-.srv file must be ignored.
        _write(os.path.join(self.dir, "README.md"), "# readme\n")

        snap = ss.scan_project(self.dir)
        self.assertEqual(snap.total_files, 2)
        self.assertGreater(snap.total_lines, 0)
        self.assertEqual(len(snap.files), 2)
        # Paths in the snapshot are relative to the scanned directory.
        rels = {f["path"] for f in snap.files}
        self.assertEqual(rels, {"a.srv", "b.srv"})

    def test_recurses_into_subdirectories(self):
        sub = os.path.join(self.dir, "deep")
        os.makedirs(sub)
        _write(os.path.join(sub, "x.srv"), "print 1\n")
        snap = ss.scan_project(self.dir)
        self.assertEqual(snap.total_files, 1)
        # Relative path retains the subdirectory.
        rel = snap.files[0]["path"]
        self.assertTrue(
            rel.endswith("x.srv") and ("deep" in rel),
            f"unexpected relative path: {rel!r}"
        )

    def test_timestamp_and_directory_recorded(self):
        _write(os.path.join(self.dir, "a.srv"), "print 1\n")
        snap = ss.scan_project(self.dir)
        self.assertTrue(snap.timestamp)
        self.assertEqual(snap.directory, os.path.abspath(self.dir))


# ---------------------------------------------------------------------------
# _compute_health: scoring formula
# ---------------------------------------------------------------------------

class ComputeHealthTest(unittest.TestCase):

    def test_no_files_is_zero(self):
        snap = ss.ProjectSnapshot()  # total_files = 0
        self.assertEqual(ss._compute_health(snap), 0.0)

    def test_clean_project_scores_high(self):
        snap = _make_snap()  # well-formed, low warnings, modest complexity
        score = ss._compute_health(snap)
        self.assertGreaterEqual(score, 85.0)
        self.assertLessEqual(score, 100.0)

    def test_lint_errors_drop_score(self):
        base = ss._compute_health(_make_snap())
        with_errors = ss._compute_health(_make_snap(lint_errors=3))
        self.assertLess(with_errors, base)

    def test_high_avg_complexity_penalised(self):
        base = ss._compute_health(_make_snap())
        # Bump avg_complexity above the 20.0 threshold.
        worse = ss._compute_health(_make_snap(avg_complexity=60.0))
        self.assertLess(worse, base)

    def test_large_files_penalised(self):
        files = [
            {"path": f"f{i}.srv", "lines": 500, "code_lines": 400,
             "complexity": 5.0, "functions": 1, "max_nesting": 1,
             "lint_warnings": 0, "hash": f"{i:012d}"}
            for i in range(3)
        ]
        snap = _make_snap(files=files, total_files=3)
        baseline = _make_snap()  # all files <300 lines
        self.assertLess(ss._compute_health(snap), ss._compute_health(baseline))

    def test_score_clamped_to_0_100(self):
        # Push every penalty knob as high as it will go.
        snap = _make_snap(
            avg_complexity=10_000.0,
            max_complexity=10_000.0,
            lint_warnings=10_000,
            lint_errors=10_000,
        )
        score = ss._compute_health(snap)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)


# ---------------------------------------------------------------------------
# detect_regressions
# ---------------------------------------------------------------------------

class DetectRegressionsTest(unittest.TestCase):

    def _hist_from(self, *snaps: ss.ProjectSnapshot) -> list:
        return [ss.snapshot_to_dict(s) for s in snaps]

    def test_no_history_returns_no_alerts(self):
        self.assertEqual(ss.detect_regressions(_make_snap(), []), [])

    def test_health_drop_warning_threshold(self):
        prev = _make_snap(health_score=90.0)
        cur = _make_snap(health_score=82.0)  # -8: warning, not critical
        alerts = ss.detect_regressions(cur, self._hist_from(prev))
        types = {a["type"] for a in alerts}
        self.assertIn("health_regression", types)
        ha = next(a for a in alerts if a["type"] == "health_regression")
        self.assertEqual(ha["severity"], "warning")

    def test_health_drop_critical_threshold(self):
        prev = _make_snap(health_score=95.0)
        cur = _make_snap(health_score=70.0)  # -25: critical
        alerts = ss.detect_regressions(cur, self._hist_from(prev))
        ha = next(a for a in alerts if a["type"] == "health_regression")
        self.assertEqual(ha["severity"], "critical")

    def test_small_health_drop_does_not_alert(self):
        prev = _make_snap(health_score=88.0)
        cur = _make_snap(health_score=86.0)  # -2 only
        alerts = ss.detect_regressions(cur, self._hist_from(prev))
        self.assertNotIn("health_regression", {a["type"] for a in alerts})

    def test_complexity_spike_alert(self):
        prev = _make_snap(avg_complexity=10.0, health_score=85.0)
        cur = _make_snap(avg_complexity=20.0, health_score=85.0)  # +100%
        alerts = ss.detect_regressions(cur, self._hist_from(prev))
        self.assertIn("complexity_spike", {a["type"] for a in alerts})

    def test_complexity_spike_requires_meaningful_baseline(self):
        # Baseline avg_complexity is <=5 so any spike is ignored as noise.
        prev = _make_snap(avg_complexity=2.0, health_score=85.0)
        cur = _make_snap(avg_complexity=40.0, health_score=85.0)
        alerts = ss.detect_regressions(cur, self._hist_from(prev))
        self.assertNotIn("complexity_spike", {a["type"] for a in alerts})

    def test_lint_surge_alert(self):
        prev = _make_snap(lint_warnings=2)
        cur = _make_snap(lint_warnings=20)  # +18 > 10 threshold
        alerts = ss.detect_regressions(cur, self._hist_from(prev))
        self.assertIn("lint_surge", {a["type"] for a in alerts})

    def test_max_complexity_blowup_alert(self):
        prev = _make_snap(max_complexity=20.0)
        cur = _make_snap(max_complexity=50.0)  # 2.5x and prev>10
        alerts = ss.detect_regressions(cur, self._hist_from(prev))
        ca = next(a for a in alerts if a["type"] == "complexity_blowup")
        self.assertEqual(ca["severity"], "critical")

    def test_file_level_regression_alert(self):
        # Same file, complexity 1.5x baseline (and baseline > 5).
        prev_files = [{"path": "hot.srv", "lines": 50, "code_lines": 40,
                       "complexity": 10.0, "functions": 2, "max_nesting": 1,
                       "lint_warnings": 0, "hash": "0000"}]
        cur_files = [{"path": "hot.srv", "lines": 50, "code_lines": 40,
                      "complexity": 20.0, "functions": 2, "max_nesting": 1,
                      "lint_warnings": 0, "hash": "1111"}]
        prev = _make_snap(files=prev_files, total_files=1)
        cur = _make_snap(files=cur_files, total_files=1)
        alerts = ss.detect_regressions(cur, self._hist_from(prev))
        file_alerts = [a for a in alerts if a["type"] == "file_regression"]
        self.assertTrue(file_alerts)
        self.assertIn("hot.srv", file_alerts[0]["message"])

    def test_declining_trend_alert(self):
        # Four-in-a-row strictly decreasing health: three history + current.
        hist = [
            ss.snapshot_to_dict(_make_snap(health_score=95.0)),
            ss.snapshot_to_dict(_make_snap(health_score=90.0)),
            ss.snapshot_to_dict(_make_snap(health_score=85.0)),
        ]
        cur = _make_snap(health_score=80.0)
        alerts = ss.detect_regressions(cur, hist)
        self.assertIn("declining_trend", {a["type"] for a in alerts})

    def test_no_alerts_for_healthy_run(self):
        prev = _make_snap()
        cur = _make_snap()  # identical → no alerts
        self.assertEqual(ss.detect_regressions(cur, self._hist_from(prev)), [])


# ---------------------------------------------------------------------------
# History I/O
# ---------------------------------------------------------------------------

class HistoryIOTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def test_history_roundtrips(self):
        data = [ss.snapshot_to_dict(_make_snap(health_score=80.0))]
        ss.save_history(self.dir, data)
        self.assertEqual(ss.load_history(self.dir), data)

    def test_missing_history_returns_empty_list(self):
        self.assertEqual(ss.load_history(self.dir), [])

    def test_corrupt_history_returns_empty_list(self):
        path = os.path.join(self.dir, ss.HISTORY_FILE)
        _write(path, "{not valid json")
        self.assertEqual(ss.load_history(self.dir), [])

    def test_snapshot_to_dict_preserves_core_fields(self):
        snap = _make_snap(health_score=77.5)
        d = ss.snapshot_to_dict(snap)
        for key in ("timestamp", "total_files", "total_lines",
                    "total_code_lines", "total_functions", "avg_complexity",
                    "max_complexity", "health_score", "lint_warnings",
                    "lint_errors", "comment_ratio", "files"):
            self.assertIn(key, d)
        self.assertEqual(d["health_score"], 77.5)
        # The serialised file list must be JSON-safe.
        json.dumps(d)


# ---------------------------------------------------------------------------
# Goals
# ---------------------------------------------------------------------------

class GoalsTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def test_goals_roundtrip(self):
        ss.save_goals(self.dir, {"health": 90})
        self.assertEqual(ss.load_goals(self.dir), {"health": 90})

    def test_missing_goals_returns_empty_dict(self):
        self.assertEqual(ss.load_goals(self.dir), {})

    def test_corrupt_goals_returns_empty_dict(self):
        _write(os.path.join(self.dir, ss.GOALS_FILE), "[corrupt")
        self.assertEqual(ss.load_goals(self.dir), {})

    def test_health_goal_is_a_floor(self):
        # Below the floor → alert.
        snap = _make_snap(health_score=80.0)
        alerts = ss.check_goals(snap, {"health": 90})
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["type"], "goal_miss")
        # Above the floor → no alert.
        snap = _make_snap(health_score=95.0)
        self.assertEqual(ss.check_goals(snap, {"health": 90}), [])

    def test_other_metrics_are_ceilings(self):
        # avg_complexity above ceiling → alert.
        snap = _make_snap(avg_complexity=50.0)
        alerts = ss.check_goals(snap, {"avg_complexity": 20})
        self.assertEqual(len(alerts), 1)
        # Below ceiling → no alert.
        snap = _make_snap(avg_complexity=10.0)
        self.assertEqual(ss.check_goals(snap, {"avg_complexity": 20}), [])

    def test_unknown_goal_keys_are_ignored(self):
        snap = _make_snap()
        self.assertEqual(ss.check_goals(snap, {"made_up_metric": 1}), [])


# ---------------------------------------------------------------------------
# _grade
# ---------------------------------------------------------------------------

class GradeTest(unittest.TestCase):

    def test_grade_boundaries(self):
        # Exact lower-bound for each grade.
        self.assertEqual(ss._grade(100.0), "A")
        self.assertEqual(ss._grade(90.0), "A")
        self.assertEqual(ss._grade(89.9), "B")
        self.assertEqual(ss._grade(80.0), "B")
        self.assertEqual(ss._grade(79.9), "C")
        self.assertEqual(ss._grade(70.0), "C")
        self.assertEqual(ss._grade(69.9), "D")
        self.assertEqual(ss._grade(60.0), "D")
        self.assertEqual(ss._grade(59.9), "F")
        self.assertEqual(ss._grade(0.0), "F")


# ---------------------------------------------------------------------------
# Dataclass smoke (cheap insurance against accidental field drops)
# ---------------------------------------------------------------------------

class DataclassShapeTest(unittest.TestCase):

    def test_filesnapshot_has_expected_fields(self):
        d = asdict(ss.FileSnapshot(path="x"))
        for key in ("path", "lines", "code_lines", "comment_lines",
                    "functions", "max_nesting", "complexity",
                    "lint_warnings", "lint_errors", "file_hash"):
            self.assertIn(key, d)

    def test_projectsnapshot_has_expected_fields(self):
        d = asdict(ss.ProjectSnapshot())
        for key in ("timestamp", "directory", "total_files", "total_lines",
                    "total_code_lines", "total_functions", "avg_complexity",
                    "max_complexity", "health_score", "lint_warnings",
                    "lint_errors", "comment_ratio", "files", "alerts"):
            self.assertIn(key, d)


if __name__ == "__main__":
    unittest.main()
