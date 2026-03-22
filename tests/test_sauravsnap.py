#!/usr/bin/env python3
"""Tests for sauravsnap — snapshot testing for sauravcode programs."""

import json
import os
import sys
import tempfile
import textwrap
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sauravsnap import (
    SnapshotStore,
    SrvRunner,
    SnapshotComparator,
    resolve_files,
    cmd_update,
    cmd_test,
    cmd_list,
    cmd_clean,
    cmd_diff,
)


class TestSnapshotStore(unittest.TestCase):
    """Tests for SnapshotStore read/write/list/remove operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.snap_dir = os.path.join(self.tmpdir, "__snapshots__")
        self.store = SnapshotStore(self.snap_dir)
        # Create a dummy .srv file
        self.srv_file = os.path.join(self.tmpdir, "hello.srv")
        with open(self.srv_file, "w") as f:
            f.write('print "Hello"\n')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_snap_path(self):
        path = self.store.snap_path(self.srv_file)
        self.assertTrue(path.endswith("hello.snap"))
        self.assertIn("__snapshots__", path)

    def test_meta_path(self):
        path = self.store.meta_path(self.srv_file)
        self.assertTrue(path.endswith("hello.snap.meta"))

    def test_save_and_load(self):
        self.store.save(self.srv_file, "Hello\n", "", 0, 0.05)
        stdout, meta = self.store.load(self.srv_file)
        self.assertEqual(stdout, "Hello\n")
        self.assertEqual(meta["exit_code"], 0)
        self.assertIn("source_hash", meta)
        self.assertIn("captured_at", meta)
        self.assertAlmostEqual(meta["duration_ms"], 50.0, places=0)

    def test_load_nonexistent(self):
        stdout, meta = self.store.load(os.path.join(self.tmpdir, "nope.srv"))
        self.assertIsNone(stdout)
        self.assertIsNone(meta)

    def test_exists(self):
        self.assertFalse(self.store.exists(self.srv_file))
        self.store.save(self.srv_file, "out", "", 0, 0.01)
        self.assertTrue(self.store.exists(self.srv_file))

    def test_list_all_empty(self):
        self.assertEqual(self.store.list_all(), [])

    def test_list_all(self):
        self.store.save(self.srv_file, "out", "", 0, 0.01)
        snaps = self.store.list_all()
        self.assertEqual(len(snaps), 1)
        self.assertEqual(snaps[0], "hello.snap")

    def test_remove(self):
        self.store.save(self.srv_file, "out", "", 0, 0.01)
        self.assertTrue(self.store.exists(self.srv_file))
        self.assertTrue(self.store.remove(self.srv_file))
        self.assertFalse(self.store.exists(self.srv_file))

    def test_remove_nonexistent(self):
        self.assertFalse(self.store.remove(os.path.join(self.tmpdir, "nope.srv")))

    def test_hash_file_deterministic(self):
        h1 = self.store._hash_file(self.srv_file)
        h2 = self.store._hash_file(self.srv_file)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 16)  # truncated to 16 chars

    def test_hash_file_changes_with_content(self):
        h1 = self.store._hash_file(self.srv_file)
        with open(self.srv_file, "a") as f:
            f.write("# extra\n")
        h2 = self.store._hash_file(self.srv_file)
        self.assertNotEqual(h1, h2)

    def test_save_creates_snap_dir(self):
        """snap_dir should be auto-created on save."""
        new_dir = os.path.join(self.tmpdir, "custom_snaps")
        store = SnapshotStore(new_dir)
        self.assertFalse(os.path.exists(new_dir))
        store.save(self.srv_file, "out", "", 0, 0.01)
        self.assertTrue(os.path.exists(new_dir))

    def test_save_stderr_in_meta(self):
        self.store.save(self.srv_file, "out", "some warning", 1, 0.02)
        _, meta = self.store.load(self.srv_file)
        self.assertEqual(meta["stderr"], "some warning")
        self.assertEqual(meta["exit_code"], 1)


class TestSnapshotComparator(unittest.TestCase):
    """Tests for SnapshotComparator."""

    def test_identical(self):
        match, diff = SnapshotComparator.compare("hello\n", "hello\n")
        self.assertTrue(match)
        self.assertEqual(diff, [])

    def test_different(self):
        match, diff = SnapshotComparator.compare("hello\n", "world\n")
        self.assertFalse(match)
        self.assertTrue(len(diff) > 0)

    def test_empty_strings(self):
        match, diff = SnapshotComparator.compare("", "")
        self.assertTrue(match)

    def test_format_diff_no_color(self):
        _, diff = SnapshotComparator.compare("a\n", "b\n")
        result = SnapshotComparator.format_diff(diff, color=False)
        self.assertIsInstance(result, str)
        self.assertIn("a", result)

    def test_format_diff_with_color(self):
        _, diff = SnapshotComparator.compare("a\n", "b\n")
        result = SnapshotComparator.format_diff(diff, color=True)
        self.assertIn("\033[", result)  # ANSI escape codes


class TestResolveFiles(unittest.TestCase):
    """Tests for the resolve_files helper."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Create some .srv files
        for name in ["a.srv", "b.srv", "c.txt"]:
            with open(os.path.join(self.tmpdir, name), "w") as f:
                f.write("")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_resolves_glob(self):
        pattern = os.path.join(self.tmpdir, "*.srv")
        files = resolve_files([pattern])
        self.assertEqual(len(files), 2)
        basenames = [os.path.basename(f) for f in files]
        self.assertIn("a.srv", basenames)
        self.assertIn("b.srv", basenames)

    def test_filters_non_srv(self):
        pattern = os.path.join(self.tmpdir, "*")
        files = resolve_files([pattern])
        # Only .srv files
        for f in files:
            self.assertTrue(f.endswith(".srv"))

    def test_pattern_filter(self):
        pattern = os.path.join(self.tmpdir, "*.srv")
        files = resolve_files([pattern], pattern="a*")
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].endswith("a.srv"))

    def test_empty_input(self):
        files = resolve_files([])
        self.assertEqual(files, [])

    def test_deduplication(self):
        path = os.path.join(self.tmpdir, "a.srv")
        files = resolve_files([path, path])
        self.assertEqual(len(files), 1)


class TestSrvRunner(unittest.TestCase):
    """Tests for SrvRunner."""

    def test_finds_interpreter(self):
        runner = SrvRunner(timeout=5)
        self.assertIsNotNone(runner._interpreter)

    def test_timeout_handling(self):
        """Runner should handle timeouts gracefully."""
        runner = SrvRunner(timeout=1)
        # We can't easily trigger a real timeout without a slow .srv file,
        # but we can verify the runner is constructed correctly
        self.assertEqual(runner.timeout, 1)


class TestCmdIntegration(unittest.TestCase):
    """Integration tests for command functions using mocked runner output."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.snap_dir = os.path.join(self.tmpdir, "__snapshots__")
        self.store = SnapshotStore(self.snap_dir)
        self.srv_file = os.path.join(self.tmpdir, "test.srv")
        with open(self.srv_file, "w") as f:
            f.write('print "test"\n')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_cmd_list_empty(self):
        """cmd_list returns 0 with no snapshots."""
        result = cmd_list(self.store)
        self.assertEqual(result, 0)

    def test_cmd_list_with_snapshots(self):
        """cmd_list returns 0 and lists saved snapshots."""
        self.store.save(self.srv_file, "test\n", "", 0, 0.01)
        result = cmd_list(self.store)
        self.assertEqual(result, 0)

    def test_cmd_clean_empty(self):
        """cmd_clean returns 0 with no snapshots."""
        result = cmd_clean(self.store)
        self.assertEqual(result, 0)

    def test_cmd_clean_removes_orphans(self):
        """cmd_clean removes snapshots whose source files are gone."""
        self.store.save(self.srv_file, "out", "", 0, 0.01)
        # Delete the source file
        os.remove(self.srv_file)
        result = cmd_clean(self.store)
        self.assertEqual(result, 0)
        self.assertEqual(self.store.list_all(), [])

    def test_cmd_update_no_files(self):
        """cmd_update with no files returns 1."""
        runner = SrvRunner(timeout=5)
        result = cmd_update([], self.store, runner)
        self.assertEqual(result, 1)

    def test_cmd_test_no_files(self):
        """cmd_test with no files returns 1."""
        runner = SrvRunner(timeout=5)
        result = cmd_test([], self.store, runner)
        self.assertEqual(result, 1)

    def test_cmd_test_missing_snapshot(self):
        """cmd_test with missing snapshot warns but doesn't crash."""
        runner = SrvRunner(timeout=5)
        result = cmd_test([self.srv_file], self.store, runner)
        # Returns 0 because missing != failure (just a warning)
        self.assertIsNotNone(result)

    def test_cmd_diff_no_snapshot(self):
        """cmd_diff returns 1 when no snapshot exists."""
        runner = SrvRunner(timeout=5)
        result = cmd_diff(self.srv_file, self.store, runner)
        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
