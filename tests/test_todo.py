#!/usr/bin/env python3
"""Tests for sauravtodo — TODO/FIXME comment tracker."""

import json
import os
import sys
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sauravtodo import (
    TodoItem, scan_file, scan_paths, filter_items, sort_items,
    group_items, format_json, format_csv, format_text, format_summary,
    format_stats, count_srv_files, main, KNOWN_TAGS, TAG_PATTERN,
)


class TestTagPattern(unittest.TestCase):
    """Test the regex pattern for matching tagged comments."""

    def test_simple_todo(self):
        m = TAG_PATTERN.search("# TODO: implement this")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1).upper(), "TODO")
        self.assertEqual(m.group(3).strip(), "implement this")

    def test_fixme_no_colon(self):
        m = TAG_PATTERN.search("# FIXME broken logic here")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1).upper(), "FIXME")

    def test_todo_with_author(self):
        m = TAG_PATTERN.search("# TODO(alice): fix the parser")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1).upper(), "TODO")
        self.assertEqual(m.group(2).strip(), "alice")
        self.assertEqual(m.group(3).strip(), "fix the parser")

    def test_hack_tag(self):
        m = TAG_PATTERN.search("# HACK: workaround for bug #42")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1).upper(), "HACK")

    def test_note_tag(self):
        m = TAG_PATTERN.search("# NOTE: this is important")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1).upper(), "NOTE")

    def test_xxx_tag(self):
        m = TAG_PATTERN.search("# XXX: dangerous code")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1).upper(), "XXX")

    def test_optimize_tag(self):
        m = TAG_PATTERN.search("# OPTIMIZE: use binary search")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1).upper(), "OPTIMIZE")

    def test_review_tag(self):
        m = TAG_PATTERN.search("# REVIEW: check edge cases")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1).upper(), "REVIEW")

    def test_deprecated_tag(self):
        m = TAG_PATTERN.search("# DEPRECATED: use new_func instead")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1).upper(), "DEPRECATED")

    def test_case_insensitive(self):
        m = TAG_PATTERN.search("# todo: lowercase works")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1).upper(), "TODO")

    def test_dash_separator(self):
        m = TAG_PATTERN.search("# TODO - implement later")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(3).strip(), "implement later")

    def test_no_match_normal_comment(self):
        m = TAG_PATTERN.search("# this is a normal comment")
        self.assertIsNone(m)

    def test_no_match_code_line(self):
        m = TAG_PATTERN.search('x = 5')
        self.assertIsNone(m)

    def test_inline_comment(self):
        m = TAG_PATTERN.search('x = 5  # TODO: fix default')
        self.assertIsNotNone(m)


class TestScanFile(unittest.TestCase):
    """Test file scanning."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _write(self, name, content):
        path = os.path.join(self.tmpdir, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_scan_empty_file(self):
        path = self._write("empty.srv", "")
        items = scan_file(path)
        self.assertEqual(len(items), 0)

    def test_scan_no_todos(self):
        path = self._write("clean.srv", "# just a comment\nx = 5\nprint x\n")
        items = scan_file(path)
        self.assertEqual(len(items), 0)

    def test_scan_single_todo(self):
        path = self._write("one.srv", "# TODO: implement this\nprint 1\n")
        items = scan_file(path)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].tag, "TODO")
        self.assertEqual(items[0].line, 1)
        self.assertEqual(items[0].text, "implement this")

    def test_scan_multiple_tags(self):
        content = "# TODO: first\n# FIXME: second\n# NOTE: third\n"
        path = self._write("multi.srv", content)
        items = scan_file(path)
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0].tag, "TODO")
        self.assertEqual(items[1].tag, "FIXME")
        self.assertEqual(items[2].tag, "NOTE")

    def test_scan_with_author(self):
        path = self._write("auth.srv", "# TODO(bob): fix this\n")
        items = scan_file(path)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].author, "bob")

    def test_priority_assignment(self):
        content = "# TODO: med\n# FIXME: high\n# NOTE: low\n# XXX: high\n"
        path = self._write("prio.srv", content)
        items = scan_file(path)
        self.assertEqual(items[0].priority, "medium")
        self.assertEqual(items[1].priority, "high")
        self.assertEqual(items[2].priority, "low")
        self.assertEqual(items[3].priority, "high")

    def test_line_numbers(self):
        content = "x = 1\ny = 2\n# TODO: on line 3\nz = 3\n# FIXME: on line 5\n"
        path = self._write("lines.srv", content)
        items = scan_file(path)
        self.assertEqual(items[0].line, 3)
        self.assertEqual(items[1].line, 5)

    def test_nonexistent_file(self):
        items = scan_file("/nonexistent/path.srv")
        self.assertEqual(items, [])


class TestScanPaths(unittest.TestCase):
    """Test directory scanning."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_scan_directory(self):
        for name in ["a.srv", "b.srv"]:
            with open(os.path.join(self.tmpdir, name), "w") as f:
                f.write(f"# TODO: in {name}\n")
        items = scan_paths([self.tmpdir])
        self.assertEqual(len(items), 2)

    def test_scan_recursive(self):
        subdir = os.path.join(self.tmpdir, "sub")
        os.makedirs(subdir)
        with open(os.path.join(self.tmpdir, "top.srv"), "w") as f:
            f.write("# TODO: top level\n")
        with open(os.path.join(subdir, "deep.srv"), "w") as f:
            f.write("# TODO: nested\n")
        items = scan_paths([self.tmpdir], recursive=True)
        self.assertEqual(len(items), 2)

    def test_scan_non_recursive(self):
        subdir = os.path.join(self.tmpdir, "sub")
        os.makedirs(subdir)
        with open(os.path.join(self.tmpdir, "top.srv"), "w") as f:
            f.write("# TODO: top level\n")
        with open(os.path.join(subdir, "deep.srv"), "w") as f:
            f.write("# TODO: nested\n")
        items = scan_paths([self.tmpdir], recursive=False)
        self.assertEqual(len(items), 1)

    def test_dedup_files(self):
        path = os.path.join(self.tmpdir, "dup.srv")
        with open(path, "w") as f:
            f.write("# TODO: only once\n")
        items = scan_paths([path, path])
        self.assertEqual(len(items), 1)

    def test_ignores_non_srv(self):
        with open(os.path.join(self.tmpdir, "readme.md"), "w") as f:
            f.write("# TODO: in markdown\n")
        items = scan_paths([self.tmpdir])
        self.assertEqual(len(items), 0)


class TestFilter(unittest.TestCase):
    """Test filtering."""

    def _items(self):
        return [
            TodoItem(file="a.srv", line=1, tag="TODO", text="t1", priority="medium", author="alice"),
            TodoItem(file="b.srv", line=2, tag="FIXME", text="t2", priority="high", author="bob"),
            TodoItem(file="c.srv", line=3, tag="NOTE", text="t3", priority="low"),
            TodoItem(file="d.srv", line=4, tag="TODO", text="t4", priority="medium"),
        ]

    def test_filter_by_tag(self):
        result = filter_items(self._items(), tags={"TODO"})
        self.assertEqual(len(result), 2)

    def test_filter_by_priority(self):
        result = filter_items(self._items(), priority="high")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].tag, "FIXME")

    def test_filter_by_author(self):
        result = filter_items(self._items(), author="alice")
        self.assertEqual(len(result), 1)

    def test_filter_combined(self):
        result = filter_items(self._items(), tags={"TODO"}, author="alice")
        self.assertEqual(len(result), 1)

    def test_filter_no_match(self):
        result = filter_items(self._items(), tags={"XXX"})
        self.assertEqual(len(result), 0)


class TestSort(unittest.TestCase):
    """Test sorting."""

    def _items(self):
        return [
            TodoItem(file="b.srv", line=3, tag="NOTE", text="t1", priority="low"),
            TodoItem(file="a.srv", line=1, tag="FIXME", text="t2", priority="high"),
            TodoItem(file="c.srv", line=2, tag="TODO", text="t3", priority="medium"),
        ]

    def test_sort_by_file(self):
        result = sort_items(self._items(), "file")
        self.assertEqual(result[0].file, "a.srv")

    def test_sort_by_priority(self):
        result = sort_items(self._items(), "priority")
        self.assertEqual(result[0].priority, "high")
        self.assertEqual(result[-1].priority, "low")

    def test_sort_by_tag(self):
        result = sort_items(self._items(), "tag")
        self.assertEqual(result[0].tag, "FIXME")


class TestGroup(unittest.TestCase):
    """Test grouping."""

    def _items(self):
        return [
            TodoItem(file="a.srv", line=1, tag="TODO", text="t1", priority="medium"),
            TodoItem(file="a.srv", line=2, tag="FIXME", text="t2", priority="high"),
            TodoItem(file="b.srv", line=1, tag="TODO", text="t3", priority="medium"),
        ]

    def test_group_by_tag(self):
        groups = group_items(self._items(), "tag")
        self.assertEqual(len(groups["TODO"]), 2)
        self.assertEqual(len(groups["FIXME"]), 1)

    def test_group_by_file(self):
        groups = group_items(self._items(), "file")
        self.assertEqual(len(groups["a.srv"]), 2)
        self.assertEqual(len(groups["b.srv"]), 1)

    def test_group_by_priority(self):
        groups = group_items(self._items(), "priority")
        self.assertIn("medium", groups)
        self.assertIn("high", groups)


class TestFormatters(unittest.TestCase):
    """Test output formatters."""

    def _items(self):
        return [
            TodoItem(file="main.srv", line=5, tag="TODO", text="add feature", priority="medium"),
            TodoItem(file="main.srv", line=10, tag="FIXME", text="broken", priority="high"),
        ]

    def test_format_json(self):
        output = format_json(self._items())
        data = json.loads(output)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["tag"], "TODO")
        self.assertEqual(data[1]["tag"], "FIXME")

    def test_format_csv(self):
        output = format_csv(self._items())
        lines = output.strip().split("\n")
        self.assertEqual(len(lines), 3)  # header + 2 rows
        self.assertIn("file,line,tag", lines[0])

    def test_format_text_no_color(self):
        output = format_text(self._items(), color=False)
        self.assertIn("TODO", output)
        self.assertIn("FIXME", output)
        self.assertIn("main.srv:5", output)

    def test_format_summary(self):
        output = format_summary(self._items(), 5)
        self.assertIn("Files scanned: 5", output)
        self.assertIn("Total items:   2", output)
        self.assertIn("TODO", output)

    def test_format_grouped(self):
        groups = group_items(self._items(), "tag")
        output = format_text(self._items(), grouped=groups, color=False)
        self.assertIn("FIXME", output)
        self.assertIn("TODO", output)

    def test_format_stats(self):
        output = format_stats(self._items(), 3)
        self.assertIn("Files scanned: 3", output)
        self.assertIn("By priority", output)

    def test_empty_items(self):
        output = format_json([])
        self.assertEqual(json.loads(output), [])


class TestTodoItemDict(unittest.TestCase):
    """Test TodoItem serialization."""

    def test_basic_dict(self):
        item = TodoItem(file="f.srv", line=1, tag="TODO", text="hi", priority="medium")
        d = item.to_dict()
        self.assertEqual(d["file"], "f.srv")
        self.assertNotIn("author", d)

    def test_dict_with_author(self):
        item = TodoItem(file="f.srv", line=1, tag="TODO", text="hi",
                       priority="medium", author="alice")
        d = item.to_dict()
        self.assertEqual(d["author"], "alice")

    def test_dict_with_blame(self):
        item = TodoItem(file="f.srv", line=1, tag="TODO", text="hi",
                       priority="medium", blame_author="bob", blame_date="2025-01-01")
        d = item.to_dict()
        self.assertEqual(d["blame_author"], "bob")


class TestCountFiles(unittest.TestCase):
    """Test file counting."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_count(self):
        for name in ["a.srv", "b.srv", "c.txt"]:
            with open(os.path.join(self.tmpdir, name), "w") as f:
                f.write("")
        self.assertEqual(count_srv_files([self.tmpdir]), 2)


class TestCLI(unittest.TestCase):
    """Test CLI integration."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.srv = os.path.join(self.tmpdir, "test.srv")
        with open(self.srv, "w") as f:
            f.write("# TODO: first task\n# FIXME: critical bug\n# NOTE: remember this\n")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_basic_run(self):
        rc = main([self.srv, "--no-color"])
        self.assertEqual(rc, 0)

    def test_check_mode_finds_items(self):
        rc = main([self.srv, "--check"])
        self.assertEqual(rc, 1)

    def test_check_mode_no_items(self):
        empty = os.path.join(self.tmpdir, "empty.srv")
        with open(empty, "w") as f:
            f.write("x = 1\n")
        rc = main([empty, "--check"])
        self.assertEqual(rc, 0)

    def test_json_output(self):
        rc = main([self.srv, "--json"])
        self.assertEqual(rc, 0)

    def test_csv_output(self):
        rc = main([self.srv, "--csv"])
        self.assertEqual(rc, 0)

    def test_summary_output(self):
        rc = main([self.srv, "--summary"])
        self.assertEqual(rc, 0)

    def test_stats_output(self):
        rc = main([self.srv, "--stats"])
        self.assertEqual(rc, 0)

    def test_filter_by_tag(self):
        rc = main([self.srv, "--tag", "FIXME", "--json"])
        self.assertEqual(rc, 0)

    def test_sort_priority(self):
        rc = main([self.srv, "--sort", "priority", "--no-color"])
        self.assertEqual(rc, 0)

    def test_group_by_tag(self):
        rc = main([self.srv, "--group", "tag", "--no-color"])
        self.assertEqual(rc, 0)

    def test_check_with_tag_filter(self):
        rc = main([self.srv, "--check", "--tag", "FIXME"])
        self.assertEqual(rc, 1)

    def test_check_with_nonexistent_tag(self):
        rc = main([self.srv, "--check", "--tag", "XXX"])
        self.assertEqual(rc, 0)

    def test_directory_scan(self):
        rc = main([self.tmpdir, "--no-color"])
        self.assertEqual(rc, 0)


class TestKnownTags(unittest.TestCase):
    """Test tag definitions."""

    def test_all_tags_have_priority(self):
        for tag, info in KNOWN_TAGS.items():
            self.assertIn("priority", info, f"{tag} missing priority")

    def test_all_tags_have_description(self):
        for tag, info in KNOWN_TAGS.items():
            self.assertIn("description", info, f"{tag} missing description")

    def test_priorities_valid(self):
        valid = {"critical", "high", "medium", "low"}
        for tag, info in KNOWN_TAGS.items():
            self.assertIn(info["priority"], valid, f"{tag} has invalid priority")


if __name__ == "__main__":
    unittest.main()
