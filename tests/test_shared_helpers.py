"""Comprehensive test suite for the two shared helper modules at the
repository root: ``_srv_utils`` and ``_termcolors``.

These modules are imported by several of the ``sauravX`` analysis tools but
were previously untested.  Adding coverage here protects refactors that pull
duplicated helpers into shared modules from silently regressing.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import sys
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Helpers to import the underscore-prefixed modules from the repo root.
# They are not exposed as installed packages, so we load them by file path.
# ---------------------------------------------------------------------------

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name: str):
    path = ROOT / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


srv_utils = _load("_srv_utils")
termcolors = _load("_termcolors")


# ===========================================================================
# _srv_utils.get_indent
# ===========================================================================

class TestGetIndent:
    def test_no_indent(self):
        assert srv_utils.get_indent("def foo:") == 0

    def test_empty_string(self):
        assert srv_utils.get_indent("") == 0

    def test_spaces_only(self):
        assert srv_utils.get_indent("    pass") == 4

    def test_single_space(self):
        assert srv_utils.get_indent(" x") == 1

    def test_tabs_count_as_four(self):
        assert srv_utils.get_indent("\tpass") == 4
        assert srv_utils.get_indent("\t\tpass") == 8

    def test_mixed_tabs_and_spaces(self):
        # space, tab, space, then content => 1 + 4 + 1 = 6
        assert srv_utils.get_indent(" \t x") == 6

    def test_stops_at_first_non_whitespace(self):
        # the tab AFTER the 'x' must not be counted
        assert srv_utils.get_indent("  x\t") == 2

    def test_only_whitespace_line(self):
        # whole line is whitespace – every char counts
        assert srv_utils.get_indent("    ") == 4
        assert srv_utils.get_indent("\t\t") == 8

    def test_other_whitespace_chars_break(self):
        # carriage return / form-feed / newline are not space or tab,
        # so they stop the count.
        assert srv_utils.get_indent("\nfoo") == 0
        assert srv_utils.get_indent("  \nfoo") == 2


# ===========================================================================
# _srv_utils.find_srv_files
# ===========================================================================

@pytest.fixture
def srv_tree(tmp_path: pathlib.Path):
    """Create a small directory tree containing .srv and non-.srv files."""
    # Top-level files
    (tmp_path / "a.srv").write_text("# a")
    (tmp_path / "z.srv").write_text("# z")
    (tmp_path / "m.srv").write_text("# m")
    (tmp_path / "notes.txt").write_text("ignore me")
    (tmp_path / "README.md").write_text("ignore me")

    # Nested directory (should only be visited recursively)
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "nested.srv").write_text("# nested")
    (sub / "other.py").write_text("# py")

    # Hidden + ignored directories must be skipped by recursive walks
    for skipped in [".hidden", "__pycache__", "__snapshots__", "node_modules"]:
        d = tmp_path / skipped
        d.mkdir()
        (d / "should_skip.srv").write_text("# nope")

    return tmp_path


class TestFindSrvFiles:
    def test_single_file_string_keeps_srv(self, srv_tree):
        files = srv_utils.find_srv_files(str(srv_tree / "a.srv"))
        assert files == [str(srv_tree / "a.srv")]

    def test_single_file_string_rejects_non_srv(self, srv_tree):
        assert srv_utils.find_srv_files(str(srv_tree / "notes.txt")) == []

    def test_non_recursive_lists_only_top_level(self, srv_tree):
        files = srv_utils.find_srv_files(str(srv_tree))
        names = [os.path.basename(f) for f in files]
        assert names == ["a.srv", "m.srv", "z.srv"]  # sorted, no nested

    def test_recursive_descends(self, srv_tree):
        files = srv_utils.find_srv_files(str(srv_tree), recursive=True)
        names = sorted(os.path.basename(f) for f in files)
        # nested file appears; hidden / pycache / snapshots / node_modules skipped
        assert "nested.srv" in names
        assert all("should_skip" not in n for n in names)
        assert "a.srv" in names and "z.srv" in names

    def test_recursive_skips_special_dirs(self, srv_tree):
        files = srv_utils.find_srv_files(str(srv_tree), recursive=True)
        for f in files:
            parts = pathlib.Path(f).parts
            assert "__pycache__" not in parts
            assert "__snapshots__" not in parts
            assert "node_modules" not in parts
            assert not any(p.startswith(".") and p != "." for p in parts)

    def test_iterable_of_paths(self, srv_tree):
        files = srv_utils.find_srv_files(
            [str(srv_tree / "a.srv"), str(srv_tree / "z.srv")]
        )
        assert files == [str(srv_tree / "a.srv"), str(srv_tree / "z.srv")]

    def test_missing_path_is_silently_ignored(self, srv_tree):
        # behaviour: non-existent path is simply not included (no exception)
        files = srv_utils.find_srv_files(str(srv_tree / "does_not_exist"))
        assert files == []

    def test_mixed_files_and_dirs(self, srv_tree):
        files = srv_utils.find_srv_files(
            [str(srv_tree / "a.srv"), str(srv_tree / "sub")],
            recursive=True,
        )
        names = sorted(os.path.basename(f) for f in files)
        assert names == ["a.srv", "nested.srv"]

    def test_empty_directory(self, tmp_path):
        assert srv_utils.find_srv_files(str(tmp_path)) == []
        assert srv_utils.find_srv_files(str(tmp_path), recursive=True) == []


# ===========================================================================
# _termcolors.ansi
# ===========================================================================

class TestAnsi:
    def test_disabled_returns_plain_str(self):
        assert termcolors.ansi("31", "hi", enabled=False) == "hi"

    def test_disabled_stringifies_non_str(self):
        assert termcolors.ansi("31", 42, enabled=False) == "42"

    def test_enabled_wraps_with_escape(self):
        out = termcolors.ansi("31", "hi", enabled=True)
        assert out == "\033[31mhi\033[0m"

    def test_default_enabled_is_true(self):
        assert termcolors.ansi("32", "x").startswith("\033[32m")

    def test_enabled_with_int(self):
        assert termcolors.ansi("1", 7) == "\033[1m7\033[0m"


# ===========================================================================
# _termcolors.Colors
# ===========================================================================

class TestColorsClass:
    @pytest.mark.parametrize(
        "method,code",
        [
            ("green", "32"),
            ("red", "31"),
            ("yellow", "33"),
            ("cyan", "36"),
            ("magenta", "35"),
            ("bold", "1"),
            ("dim", "2"),
        ],
    )
    def test_named_colors_when_enabled(self, method, code):
        c = termcolors.Colors(enabled=True)
        out = getattr(c, method)("ok")
        assert out == f"\033[{code}mok\033[0m"

    @pytest.mark.parametrize(
        "method", ["green", "red", "yellow", "cyan", "magenta", "bold", "dim"]
    )
    def test_named_colors_when_disabled(self, method):
        c = termcolors.Colors(enabled=False)
        assert getattr(c, method)("ok") == "ok"

    def test_nested_calls(self):
        c = termcolors.Colors(enabled=True)
        # bold(red(...)) wraps twice
        inner = c.red("FAIL")
        outer = c.bold(inner)
        assert outer == f"\033[1m{inner}\033[0m"

    def test_slots(self):
        # __slots__ means no arbitrary attribute assignment
        c = termcolors.Colors(enabled=True)
        with pytest.raises(AttributeError):
            c.new_attr = "nope"

    def test_low_level_c_helper(self):
        c = termcolors.Colors(enabled=True)
        assert c.c("4", "u") == "\033[4mu\033[0m"
        c.enabled = False
        assert c.c("4", "u") == "u"


# ===========================================================================
# _termcolors.colors() factory
# ===========================================================================

class TestColorsFactory:
    def test_force_enabled(self):
        c = termcolors.colors(enabled=True)
        assert isinstance(c, termcolors.Colors)
        assert c.enabled is True

    def test_force_disabled(self):
        c = termcolors.colors(enabled=False)
        assert c.enabled is False

    def test_autodetect_when_not_tty(self, monkeypatch):
        # When stdout is not a tty (pytest captures by default), should be off
        monkeypatch.setattr(
            termcolors.sys.stdout, "isatty", lambda: False, raising=False
        )
        c = termcolors.colors()
        assert c.enabled is False

    def test_autodetect_when_tty(self, monkeypatch):
        monkeypatch.setattr(
            termcolors.sys.stdout, "isatty", lambda: True, raising=False
        )
        # ensure TERM is set so the second clause is truthy
        monkeypatch.setenv("TERM", "xterm-256color")
        c = termcolors.colors()
        assert c.enabled is True

    def test_autodetect_tty_but_no_term_env(self, monkeypatch):
        # bool(os.environ.get("TERM", True)) is True when TERM missing because
        # the default is True. If TERM exists but is empty string, this flips.
        monkeypatch.setattr(
            termcolors.sys.stdout, "isatty", lambda: True, raising=False
        )
        monkeypatch.setenv("TERM", "")
        c = termcolors.colors()
        assert c.enabled is False


# ===========================================================================
# Module surface
# ===========================================================================

def test_termcolors_all_exports():
    assert set(termcolors.__all__) == {"Colors", "colors", "ansi"}
