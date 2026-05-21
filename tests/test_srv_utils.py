"""Direct tests for the shared helpers in ``_srv_utils``.

The helpers (``get_indent`` and ``find_srv_files``) are consumed by
sauravmetrics, sauravstats, sauravlint, sauravhl, and sauravfmt. Until
now they only had *indirect* coverage through those modules' integration
tests. These tests exercise the helpers directly so a regression in the
shared layer is caught at its source rather than as a confusing failure
several modules deep.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# _srv_utils lives at the repo root, next to saurav.py.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import _srv_utils  # noqa: E402  (intentional after path insert)


# ───────────────────────────────────────────────────────────── get_indent ──

class TestGetIndent:
    def test_no_leading_whitespace(self):
        assert _srv_utils.get_indent("hello") == 0

    def test_empty_string(self):
        assert _srv_utils.get_indent("") == 0

    def test_only_whitespace(self):
        assert _srv_utils.get_indent("    ") == 4

    def test_spaces(self):
        assert _srv_utils.get_indent("    x = 1") == 4

    def test_single_tab_counts_as_four(self):
        assert _srv_utils.get_indent("\tx") == 4

    def test_multiple_tabs(self):
        assert _srv_utils.get_indent("\t\tx") == 8

    def test_mixed_spaces_then_tab(self):
        # 2 spaces + 1 tab = 2 + 4 = 6
        assert _srv_utils.get_indent("  \tx") == 6

    def test_mixed_tab_then_spaces(self):
        # 1 tab + 2 spaces = 4 + 2 = 6
        assert _srv_utils.get_indent("\t  x") == 6

    def test_stops_at_first_non_whitespace(self):
        # Whitespace after content must NOT be counted.
        assert _srv_utils.get_indent("x    y") == 0

    def test_blank_line_with_only_newline(self):
        # A pure newline has no leading space chars before the newline,
        # and '\n' is neither ' ' nor '\t' → stops immediately.
        assert _srv_utils.get_indent("\n") == 0


# ─────────────────────────────────────────────────────────── find_srv_files ─

class TestFindSrvFiles:
    def test_single_srv_file_returned(self, tmp_path: Path):
        f = tmp_path / "hello.srv"
        f.write_text("print 1")
        result = _srv_utils.find_srv_files(str(f))
        assert result == [str(f)]

    def test_non_srv_file_filtered_out(self, tmp_path: Path):
        f = tmp_path / "hello.txt"
        f.write_text("nope")
        assert _srv_utils.find_srv_files(str(f)) == []

    def test_directory_non_recursive_only_top_level(self, tmp_path: Path):
        (tmp_path / "a.srv").write_text("")
        (tmp_path / "b.srv").write_text("")
        (tmp_path / "ignore.txt").write_text("")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.srv").write_text("")

        result = _srv_utils.find_srv_files(str(tmp_path))
        # Top-level .srv files only, sorted, no recursion.
        assert result == [str(tmp_path / "a.srv"), str(tmp_path / "b.srv")]

    def test_directory_recursive_descends(self, tmp_path: Path):
        (tmp_path / "a.srv").write_text("")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.srv").write_text("")

        result = _srv_utils.find_srv_files(str(tmp_path), recursive=True)
        assert str(tmp_path / "a.srv") in result
        assert str(sub / "deep.srv") in result
        assert len(result) == 2

    def test_recursive_skips_hidden_and_cache_dirs(self, tmp_path: Path):
        (tmp_path / "keep.srv").write_text("")
        for skip in (".git", "__pycache__", "__snapshots__", "node_modules"):
            d = tmp_path / skip
            d.mkdir()
            (d / "hidden.srv").write_text("")

        result = _srv_utils.find_srv_files(str(tmp_path), recursive=True)
        assert result == [str(tmp_path / "keep.srv")]

    def test_accepts_list_of_paths(self, tmp_path: Path):
        f1 = tmp_path / "a.srv"
        f2 = tmp_path / "b.srv"
        f1.write_text("")
        f2.write_text("")
        result = _srv_utils.find_srv_files([str(f1), str(f2)])
        # Order matches input order (each entry resolved independently).
        assert result == [str(f1), str(f2)]

    def test_nonexistent_path_silently_skipped(self, tmp_path: Path):
        missing = tmp_path / "does-not-exist"
        # Should not raise: nothing matches but the call is still valid.
        assert _srv_utils.find_srv_files(str(missing)) == []

    def test_returns_sorted_within_directory(self, tmp_path: Path):
        # Write files out of order; verify alphabetical ordering.
        for name in ("zeta.srv", "alpha.srv", "mu.srv"):
            (tmp_path / name).write_text("")
        result = _srv_utils.find_srv_files(str(tmp_path))
        assert [os.path.basename(p) for p in result] == [
            "alpha.srv", "mu.srv", "zeta.srv",
        ]

    def test_mixed_files_and_dirs_in_list(self, tmp_path: Path):
        f = tmp_path / "lone.srv"
        f.write_text("")
        d = tmp_path / "pkg"
        d.mkdir()
        (d / "inner.srv").write_text("")

        result = _srv_utils.find_srv_files([str(f), str(d)])
        # The lone file plus the (non-recursive) directory listing.
        assert result == [str(f), str(d / "inner.srv")]
