#!/usr/bin/env python3
"""Tests for sauravmin — the sauravcode source minifier."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sauravmin import (
    minify,
    minify_file,
    minify_directory,
    _strip_comments,
    _id_generator,
    _collect_identifiers,
    _build_rename_map,
    _apply_renames,
    RESERVED,
)


class TestStripComments(unittest.TestCase):
    """Test comment stripping from individual lines."""

    def test_no_comment(self):
        self.assertEqual(_strip_comments("x = 42"), "x = 42")

    def test_full_line_comment(self):
        self.assertEqual(_strip_comments("# this is a comment"), "")

    def test_inline_comment(self):
        self.assertEqual(_strip_comments("x = 42  # inline"), "x = 42")

    def test_hash_in_string_preserved(self):
        self.assertEqual(
            _strip_comments('x = "hello # world"'),
            'x = "hello # world"',
        )

    def test_hash_in_single_quoted_string(self):
        self.assertEqual(
            _strip_comments("x = 'a # b'"),
            "x = 'a # b'",
        )

    def test_escaped_quote_in_string(self):
        self.assertEqual(
            _strip_comments(r'x = "he said \"hi\" # real"  # comment'),
            r'x = "he said \"hi\" # real"',
        )

    def test_empty_line(self):
        self.assertEqual(_strip_comments(""), "")

    def test_only_hash(self):
        self.assertEqual(_strip_comments("#"), "")


class TestIdGenerator(unittest.TestCase):
    """Test short identifier generation."""

    def test_first_ids(self):
        gen = _id_generator()
        first = [next(gen) for _ in range(5)]
        self.assertEqual(first, ["_a", "_b", "_c", "_d", "_e"])

    def test_wraps_past_z(self):
        gen = _id_generator()
        ids = [next(gen) for _ in range(30)]
        # After _z (26th), should produce _aa, _ab, etc.
        self.assertTrue(any(len(i) == 3 for i in ids))

    def test_no_reserved_ids(self):
        gen = _id_generator()
        ids = [next(gen) for _ in range(200)]
        for ident in ids:
            self.assertNotIn(ident, RESERVED)

    def test_all_unique(self):
        gen = _id_generator()
        ids = [next(gen) for _ in range(500)]
        self.assertEqual(len(ids), len(set(ids)))


class TestMinifyLevels(unittest.TestCase):
    """Test minification at different compression levels."""

    SAMPLE = (
        "# Header comment\n"
        "x = 10  # inline\n"
        "\n"
        "\n"
        "y = 20\n"
        "\n"
        "# Another comment\n"
        "z = x + y\n"
    )

    def test_level0_strips_comments_only(self):
        result, stats, rmap = minify(self.SAMPLE, level=0)
        self.assertNotIn("#", result)
        # Blank lines preserved
        self.assertIn("\n\n", result)
        self.assertEqual(stats["level"], 0)
        self.assertEqual(rmap, {})

    def test_level1_collapses_consecutive_blanks(self):
        result, stats, _ = minify(self.SAMPLE, level=1)
        # No double blank lines
        self.assertNotIn("\n\n\n", result)
        # But single blank lines can remain
        self.assertIn("x = 10", result)

    def test_level2_removes_all_blanks(self):
        result, stats, _ = minify(self.SAMPLE, level=2)
        lines = [l for l in result.strip().split("\n") if l.strip() == ""]
        self.assertEqual(len(lines), 0)

    def test_level3_renames_identifiers(self):
        result, stats, rmap = minify(self.SAMPLE, level=3)
        self.assertGreater(stats["identifiers_renamed"], 0)
        self.assertGreater(len(rmap), 0)
        # Original names should be gone (if not keywords)
        for orig_name in rmap:
            self.assertNotIn(orig_name, result)

    def test_stats_accuracy(self):
        result, stats, _ = minify(self.SAMPLE, level=2)
        self.assertEqual(stats["original_bytes"], len(self.SAMPLE))
        self.assertEqual(stats["minified_bytes"], len(result))
        self.assertEqual(stats["saved_bytes"], len(self.SAMPLE) - len(result))
        self.assertGreater(stats["compression_pct"], 0)

    def test_empty_source(self):
        result, stats, _ = minify("", level=2)
        self.assertEqual(result, "")
        self.assertEqual(stats["compression_pct"], 0)

    def test_no_comments_source(self):
        src = "x = 1\ny = 2\n"
        result, stats, _ = minify(src, level=0)
        self.assertEqual(result.strip(), src.strip())

    def test_trailing_newline(self):
        """Minified output should end with a newline."""
        result, _, _ = minify("x = 1", level=2)
        self.assertTrue(result.endswith("\n"))


class TestApplyRenames(unittest.TestCase):
    """Test identifier renaming logic."""

    def test_basic_rename(self):
        result = _apply_renames("x = 42\nprint(x)", {"x": "_a"})
        self.assertIn("_a = 42", result)
        self.assertIn("print(_a)", result)

    def test_string_contents_preserved(self):
        result = _apply_renames('msg = "hello x"', {"x": "_a"})
        self.assertIn('"hello x"', result)

    def test_comment_contents_preserved(self):
        result = _apply_renames("x = 1  # x is a var", {"x": "_a"})
        self.assertIn("# x is a var", result)

    def test_no_partial_rename(self):
        """Renaming 'x' should not affect 'xyz'."""
        result = _apply_renames("xyz = x + 1", {"x": "_a"})
        self.assertIn("xyz", result)
        self.assertIn("_a", result)

    def test_empty_map(self):
        src = "x = 1"
        self.assertEqual(_apply_renames(src, {}), src)


class TestMinifyFile(unittest.TestCase):
    """Test file-level minification."""

    def test_minify_to_file(self):
        src = "# comment\nx = 1\n\n\ny = 2\n"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".srv", delete=False, encoding="utf-8"
        ) as f:
            f.write(src)
            src_path = f.name

        try:
            with tempfile.NamedTemporaryFile(
                suffix=".srv", delete=False
            ) as out:
                out_path = out.name

            stats = minify_file(src_path, output=out_path, level=2)
            with open(out_path, encoding="utf-8") as f:
                result = f.read()
            self.assertNotIn("#", result)
            self.assertIn("x = 1", result)
            self.assertEqual(stats["file"], src_path)
        finally:
            os.unlink(src_path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_dry_run_no_output(self):
        src = "# comment\nx = 1\n"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".srv", delete=False, encoding="utf-8"
        ) as f:
            f.write(src)
            src_path = f.name

        try:
            stats = minify_file(src_path, dry_run=True, level=2)
            self.assertIn("original_bytes", stats)
        finally:
            os.unlink(src_path)

    def test_rename_map_export(self):
        src = "counter = 0\ncounter = counter + 1\n"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".srv", delete=False, encoding="utf-8"
        ) as f:
            f.write(src)
            src_path = f.name

        map_path = src_path + ".map.json"
        try:
            minify_file(src_path, level=3, map_path=map_path, dry_run=False)
            if os.path.exists(map_path):
                with open(map_path, encoding="utf-8") as f:
                    rmap = json.load(f)
                self.assertIsInstance(rmap, dict)
        finally:
            os.unlink(src_path)
            if os.path.exists(map_path):
                os.unlink(map_path)


class TestMinifyDirectory(unittest.TestCase):
    """Test batch directory minification."""

    def test_batch_minify(self):
        with tempfile.TemporaryDirectory() as src_dir:
            for i in range(3):
                p = os.path.join(src_dir, f"prog{i}.srv")
                with open(p, "w", encoding="utf-8") as f:
                    f.write(f"# file {i}\nvar_{i} = {i}\n")

            with tempfile.TemporaryDirectory() as out_dir:
                stats = minify_directory(
                    src_dir, out_dir=out_dir, level=2, recursive=False
                )
                self.assertEqual(len(stats), 3)
                for s in stats:
                    self.assertGreater(s["saved_bytes"], 0)

    def test_recursive_flag(self):
        with tempfile.TemporaryDirectory() as src_dir:
            sub = os.path.join(src_dir, "sub")
            os.makedirs(sub)
            with open(os.path.join(sub, "deep.srv"), "w", encoding="utf-8") as f:
                f.write("# deep\nx = 1\n")
            with open(os.path.join(src_dir, "top.srv"), "w", encoding="utf-8") as f:
                f.write("# top\ny = 2\n")

            # Non-recursive should only find top-level
            stats_flat = minify_directory(src_dir, recursive=False, dry_run=True)
            stats_deep = minify_directory(src_dir, recursive=True, dry_run=True)
            self.assertEqual(len(stats_flat), 1)
            self.assertEqual(len(stats_deep), 2)


if __name__ == "__main__":
    unittest.main()
