#!/usr/bin/env python3
"""Tests for sauravtodo — TODO/FIXME comment tracker."""

import os
import sys
import json
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sauravtodo import (
    TodoItem, scan_file, scan_paths, filter_items, sort_items,
    group_items, KNOWN_TAGS, PRIORITY_ORDER, TAG_PATTERN,
)


# ── Helpers ──────────────────────────────────────────────────────

def _write_srv(tmpdir, name, content):
    """Write a .srv file and return its path."""
    path = os.path.join(tmpdir, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


# ── TAG_PATTERN regex tests ──────────────────────────────────────

def test_tag_pattern_basic_todo():
    m = TAG_PATTERN.search("# TODO: fix this")
    assert m is not None
    assert m.group(1).upper() == "TODO"
    assert m.group(3).strip() == "fix this"

def test_tag_pattern_fixme_no_colon():
    m = TAG_PATTERN.search("# FIXME handle edge case")
    assert m is not None
    assert m.group(1).upper() == "FIXME"
    assert "handle edge case" in m.group(3).strip()

def test_tag_pattern_with_author():
    m = TAG_PATTERN.search("# TODO(alice): implement caching")
    assert m is not None
    assert m.group(2).strip() == "alice"
    assert "implement caching" in m.group(3).strip()

def test_tag_pattern_case_insensitive():
    m = TAG_PATTERN.search("# todo: lower case")
    assert m is not None
    assert m.group(1).upper() == "TODO"

def test_tag_pattern_all_known_tags():
    for tag in KNOWN_TAGS:
        m = TAG_PATTERN.search(f"# {tag}: some text here")
        assert m is not None, f"Pattern should match {tag}"
        assert m.group(1).upper() == tag

def test_tag_pattern_no_match():
    m = TAG_PATTERN.search("x = 42  # just a regular comment")
    assert m is None

def test_tag_pattern_hack():
    m = TAG_PATTERN.search("# HACK — workaround for bug #123")
    assert m is not None
    assert m.group(1).upper() == "HACK"


# ── scan_file tests ──────────────────────────────────────────────

def test_scan_file_single_todo():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = _write_srv(tmpdir, "a.srv", "x = 1\n# TODO: refactor\ny = 2\n")
        items = scan_file(path)
        assert len(items) == 1
        assert items[0].tag == "TODO"
        assert items[0].line == 2
        assert "refactor" in items[0].text

def test_scan_file_multiple_tags():
    with tempfile.TemporaryDirectory() as tmpdir:
        src = "# TODO: first\nx = 1\n# FIXME: second\n# NOTE: third\n"
        path = _write_srv(tmpdir, "b.srv", src)
        items = scan_file(path)
        assert len(items) == 3
        tags = [i.tag for i in items]
        assert "TODO" in tags
        assert "FIXME" in tags
        assert "NOTE" in tags

def test_scan_file_no_todos():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = _write_srv(tmpdir, "c.srv", "x = 1\ny = 2\n# just a comment\n")
        items = scan_file(path)
        assert len(items) == 0

def test_scan_file_with_author():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = _write_srv(tmpdir, "d.srv", "# TODO(bob): fix login\n")
        items = scan_file(path)
        assert len(items) == 1
        assert items[0].author == "bob"

def test_scan_file_nonexistent():
    items = scan_file("/nonexistent/path/fake.srv")
    assert items == []

def test_scan_file_priority_from_tag():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = _write_srv(tmpdir, "e.srv", "# FIXME: critical bug\n# NOTE: fyi\n")
        items = scan_file(path)
        fixme = [i for i in items if i.tag == "FIXME"][0]
        note = [i for i in items if i.tag == "NOTE"][0]
        assert fixme.priority == "high"
        assert note.priority == "low"


# ── scan_paths tests ─────────────────────────────────────────────

def test_scan_paths_directory():
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_srv(tmpdir, "a.srv", "# TODO: one\n")
        _write_srv(tmpdir, "b.srv", "# FIXME: two\n")
        items = scan_paths([tmpdir], recursive=False)
        assert len(items) == 2

def test_scan_paths_recursive():
    with tempfile.TemporaryDirectory() as tmpdir:
        subdir = os.path.join(tmpdir, "sub")
        os.makedirs(subdir)
        _write_srv(tmpdir, "a.srv", "# TODO: top\n")
        _write_srv(subdir, "b.srv", "# TODO: nested\n")
        items = scan_paths([tmpdir], recursive=True)
        assert len(items) == 2

def test_scan_paths_single_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = _write_srv(tmpdir, "a.srv", "# TODO: check\n")
        items = scan_paths([path])
        assert len(items) == 1

def test_scan_paths_deduplication():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = _write_srv(tmpdir, "a.srv", "# TODO: once\n")
        items = scan_paths([path, path])  # same file twice
        assert len(items) == 1


# ── filter_items tests ───────────────────────────────────────────

def _sample_items():
    return [
        TodoItem(file="a.srv", line=1, tag="TODO", text="one", priority="medium"),
        TodoItem(file="a.srv", line=5, tag="FIXME", text="two", priority="high"),
        TodoItem(file="b.srv", line=2, tag="NOTE", text="three", priority="low", author="alice"),
        TodoItem(file="b.srv", line=8, tag="TODO", text="four", priority="medium", author="bob"),
    ]

def test_filter_by_tag():
    items = filter_items(_sample_items(), tags={"TODO"})
    assert len(items) == 2
    assert all(i.tag == "TODO" for i in items)

def test_filter_by_priority():
    items = filter_items(_sample_items(), priority="high")
    assert len(items) == 1
    assert items[0].tag == "FIXME"

def test_filter_by_author():
    items = filter_items(_sample_items(), author="alice")
    assert len(items) == 1
    assert items[0].text == "three"

def test_filter_combined():
    items = filter_items(_sample_items(), tags={"TODO"}, author="bob")
    assert len(items) == 1
    assert items[0].text == "four"

def test_filter_no_match():
    items = filter_items(_sample_items(), tags={"DEPRECATED"})
    assert len(items) == 0


# ── sort_items tests ─────────────────────────────────────────────

def test_sort_by_priority():
    items = sort_items(_sample_items(), key="priority")
    assert items[0].priority == "high"
    assert items[-1].priority == "low"

def test_sort_by_tag():
    items = sort_items(_sample_items(), key="tag")
    tags = [i.tag for i in items]
    assert tags == sorted(tags)

def test_sort_by_file():
    items = sort_items(_sample_items(), key="file")
    assert items[0].file == "a.srv"
    assert items[-1].file == "b.srv"


# ── group_items tests ────────────────────────────────────────────

def test_group_by_tag():
    groups = group_items(_sample_items(), key="tag")
    assert "TODO" in groups
    assert "FIXME" in groups
    assert len(groups["TODO"]) == 2

def test_group_by_file():
    groups = group_items(_sample_items(), key="file")
    assert "a.srv" in groups
    assert "b.srv" in groups

def test_group_by_priority():
    groups = group_items(_sample_items(), key="priority")
    assert "high" in groups
    assert "medium" in groups
    assert "low" in groups

def test_group_by_author():
    groups = group_items(_sample_items(), key="author")
    assert "alice" in groups
    assert "bob" in groups
    assert "(unknown)" in groups  # items without author


# ── TodoItem.to_dict tests ───────────────────────────────────────

def test_todo_item_to_dict_basic():
    item = TodoItem(file="x.srv", line=3, tag="TODO", text="do stuff", priority="medium")
    d = item.to_dict()
    assert d["file"] == "x.srv"
    assert d["line"] == 3
    assert d["tag"] == "TODO"
    assert "author" not in d
    assert "blame_author" not in d

def test_todo_item_to_dict_with_author():
    item = TodoItem(file="x.srv", line=1, tag="FIXME", text="fix", priority="high", author="eve")
    d = item.to_dict()
    assert d["author"] == "eve"

def test_todo_item_to_dict_with_blame():
    item = TodoItem(file="x.srv", line=1, tag="TODO", text="t", priority="medium",
                    blame_author="Charlie", blame_date="2025-01-15")
    d = item.to_dict()
    assert d["blame_author"] == "Charlie"
    assert d["blame_date"] == "2025-01-15"


# ── Constants/config tests ───────────────────────────────────────

def test_known_tags_have_priority():
    for tag, info in KNOWN_TAGS.items():
        assert "priority" in info
        assert info["priority"] in PRIORITY_ORDER

def test_priority_order_complete():
    all_priorities = {info["priority"] for info in KNOWN_TAGS.values()}
    for p in all_priorities:
        assert p in PRIORITY_ORDER


# ── Edge cases ───────────────────────────────────────────────────

def test_scan_empty_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = _write_srv(tmpdir, "empty.srv", "")
        items = scan_file(path)
        assert items == []

def test_scan_file_todo_at_end_no_newline():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = _write_srv(tmpdir, "end.srv", "x = 1\n# TODO: at end")
        items = scan_file(path)
        assert len(items) == 1
        assert "at end" in items[0].text

def test_scan_file_preserves_source_line():
    with tempfile.TemporaryDirectory() as tmpdir:
        line = "    # TODO: indented task"
        path = _write_srv(tmpdir, "indent.srv", f"x = 1\n{line}\n")
        items = scan_file(path)
        assert len(items) == 1
        assert items[0].source_line == line


# ── Run ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
