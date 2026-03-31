#!/usr/bin/env python3
"""Tests for sauravwatch -- file watcher module."""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sauravwatch import FileTracker, RunStats, discover_srv_files


class TestFileTracker(unittest.TestCase):
    """Test FileTracker change detection."""

    def test_new_file_detected(self):
        tracker = FileTracker()
        with tempfile.NamedTemporaryFile(suffix=".srv", delete=False, mode="w") as f:
            f.write("print 1")
            path = f.name
        try:
            changes = tracker.detect_changes([path])
            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0][0], "new")
            self.assertEqual(changes[0][1], path)
        finally:
            os.unlink(path)

    def test_no_changes_on_second_check(self):
        tracker = FileTracker()
        with tempfile.NamedTemporaryFile(suffix=".srv", delete=False, mode="w") as f:
            f.write("print 1")
            path = f.name
        try:
            tracker.detect_changes([path])
            changes = tracker.detect_changes([path])
            self.assertEqual(len(changes), 0)
        finally:
            os.unlink(path)

    def test_modified_file_detected(self):
        tracker = FileTracker()
        with tempfile.NamedTemporaryFile(suffix=".srv", delete=False, mode="w") as f:
            f.write("print 1")
            path = f.name
        try:
            tracker.detect_changes([path])
            time.sleep(0.05)
            with open(path, "w") as f:
                f.write("print 2")
            # Force mtime change
            os.utime(path, (time.time() + 1, time.time() + 1))
            changes = tracker.detect_changes([path])
            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0][0], "modified")
        finally:
            os.unlink(path)

    def test_deleted_file_detected(self):
        tracker = FileTracker()
        with tempfile.NamedTemporaryFile(suffix=".srv", delete=False, mode="w") as f:
            f.write("print 1")
            path = f.name
        try:
            tracker.detect_changes([path])
            os.unlink(path)
            changes = tracker.detect_changes([])
            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0][0], "deleted")
        except Exception:
            if os.path.exists(path):
                os.unlink(path)
            raise

    def test_empty_paths(self):
        tracker = FileTracker()
        changes = tracker.detect_changes([])
        self.assertEqual(changes, [])

    def test_nonexistent_file_ignored(self):
        tracker = FileTracker()
        changes = tracker.detect_changes(["/nonexistent/path/foo.srv"])
        self.assertEqual(changes, [])

    def test_snapshot_returns_dict(self):
        tracker = FileTracker()
        with tempfile.NamedTemporaryFile(suffix=".srv", delete=False, mode="w") as f:
            f.write("x = 1")
            path = f.name
        try:
            state = tracker.snapshot([path])
            self.assertIn(path, state)
            mtime, content_hash = state[path]
            self.assertIsInstance(mtime, float)
            self.assertIsInstance(content_hash, str)
            self.assertEqual(len(content_hash), 32)  # MD5 hex digest
        finally:
            os.unlink(path)


class TestRunStats(unittest.TestCase):
    """Test RunStats tracking."""

    def test_initial_state(self):
        stats = RunStats()
        self.assertEqual(stats.total_runs, 0)
        self.assertEqual(stats.successes, 0)
        self.assertEqual(stats.failures, 0)

    def test_record_success(self):
        stats = RunStats()
        stats.record(150, True, "test.srv")
        self.assertEqual(stats.total_runs, 1)
        self.assertEqual(stats.successes, 1)
        self.assertEqual(stats.failures, 0)
        self.assertEqual(stats.total_time_ms, 150)

    def test_record_failure(self):
        stats = RunStats()
        stats.record(200, False, "test.srv")
        self.assertEqual(stats.total_runs, 1)
        self.assertEqual(stats.successes, 0)
        self.assertEqual(stats.failures, 1)

    def test_multiple_records(self):
        stats = RunStats()
        stats.record(100, True, "a.srv")
        stats.record(200, False, "b.srv")
        stats.record(150, True, "a.srv")
        self.assertEqual(stats.total_runs, 3)
        self.assertEqual(stats.successes, 2)
        self.assertEqual(stats.failures, 1)
        self.assertEqual(stats.total_time_ms, 450)

    def test_run_history_tracked(self):
        stats = RunStats()
        stats.record(100, True, "test.srv")
        self.assertEqual(len(stats.run_history), 1)
        entry = stats.run_history[0]
        self.assertEqual(entry[1], 100)
        self.assertTrue(entry[2])
        self.assertEqual(entry[3], "test.srv")


class TestDiscoverSrvFiles(unittest.TestCase):
    """Test file discovery."""

    def test_single_srv_file(self):
        with tempfile.NamedTemporaryFile(suffix=".srv", delete=False) as f:
            path = f.name
        try:
            result = discover_srv_files(path)
            self.assertEqual(result, [path])
        finally:
            os.unlink(path)

    def test_non_srv_file_excluded(self):
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            path = f.name
        try:
            result = discover_srv_files(path)
            self.assertEqual(result, [])
        finally:
            os.unlink(path)

    def test_directory_discovery(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.srv").write_text("x = 1")
            (Path(tmpdir) / "b.srv").write_text("y = 2")
            (Path(tmpdir) / "c.py").write_text("# not srv")
            result = discover_srv_files(tmpdir)
            self.assertEqual(len(result), 2)
            self.assertTrue(all(r.endswith(".srv") for r in result))

    def test_recursive_discovery(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sub = Path(tmpdir) / "sub"
            sub.mkdir()
            (Path(tmpdir) / "a.srv").write_text("x = 1")
            (sub / "b.srv").write_text("y = 2")
            non_recursive = discover_srv_files(tmpdir, recursive=False)
            recursive = discover_srv_files(tmpdir, recursive=True)
            self.assertEqual(len(non_recursive), 1)
            self.assertEqual(len(recursive), 2)

    def test_nonexistent_path(self):
        result = discover_srv_files("/nonexistent/path")
        self.assertEqual(result, [])

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = discover_srv_files(tmpdir)
            self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
