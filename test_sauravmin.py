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
    _bijective_base26,
    _collapse_consecutive_blank_lines,
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


class TestBijectiveBase26(unittest.TestCase):
    """Verify the helper used to mint short identifier suffixes."""

    def test_first_26_are_single_letters(self):
        self.assertEqual(_bijective_base26(0), "a")
        self.assertEqual(_bijective_base26(1), "b")
        self.assertEqual(_bijective_base26(25), "z")

    def test_wraps_to_two_letters(self):
        # 26 must be 'aa' (bijective base-26, no zero digit)
        self.assertEqual(_bijective_base26(26), "aa")
        self.assertEqual(_bijective_base26(27), "ab")
        self.assertEqual(_bijective_base26(51), "az")
        self.assertEqual(_bijective_base26(52), "ba")

    def test_three_letter_boundary(self):
        # 26 + 26*26 = 702 is the first three-letter ('aaa')
        self.assertEqual(_bijective_base26(26 + 26 * 26), "aaa")

    def test_uniqueness_over_first_1000(self):
        names = [_bijective_base26(i) for i in range(1000)]
        self.assertEqual(len(set(names)), 1000)
        # all non-empty, all lowercase a-z
        for n in names:
            self.assertTrue(n)
            self.assertTrue(all(c in "abcdefghijklmnopqrstuvwxyz" for c in n))

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            _bijective_base26(-1)


class TestIdGenerator(unittest.TestCase):
    """Sanity checks for the public identifier generator."""

    def test_starts_with_underscore_a(self):
        gen = _id_generator()
        self.assertEqual(next(gen), "_a")
        self.assertEqual(next(gen), "_b")

    def test_yields_unique_values(self):
        gen = _id_generator()
        seen = [next(gen) for _ in range(500)]
        self.assertEqual(len(set(seen)), 500)

    def test_skips_reserved_words(self):
        # 'if', 'in', 'or' etc. are reserved -- but our names start with '_',
        # so collisions only happen if RESERVED gains a name starting with '_'.
        # Inject a known reserved name with the same shape and verify it's
        # skipped.
        import sauravmin as sm
        sm.RESERVED.add("_a")
        try:
            gen = sm._id_generator()
            first = next(gen)
            self.assertNotEqual(first, "_a")
            self.assertEqual(first, "_b")
        finally:
            sm.RESERVED.discard("_a")


class TestCollapseConsecutiveBlankLines(unittest.TestCase):
    """Verify the extracted blank-line-collapsing helper."""

    def test_no_blanks_unchanged(self):
        lines = ["a", "b", "c"]
        self.assertEqual(_collapse_consecutive_blank_lines(lines), lines)

    def test_single_blank_preserved(self):
        self.assertEqual(
            _collapse_consecutive_blank_lines(["a", "", "b"]),
            ["a", "", "b"],
        )

    def test_run_of_blanks_collapsed(self):
        self.assertEqual(
            _collapse_consecutive_blank_lines(["a", "", "", "", "b"]),
            ["a", "", "b"],
        )

    def test_whitespace_only_counts_as_blank(self):
        self.assertEqual(
            _collapse_consecutive_blank_lines(["a", "   ", "\t", "b"]),
            ["a", "   ", "b"],
        )

    def test_leading_and_trailing_blanks(self):
        self.assertEqual(
            _collapse_consecutive_blank_lines(["", "", "a", "", ""]),
            ["", "a", ""],
        )

    def test_empty_input(self):
        self.assertEqual(_collapse_consecutive_blank_lines([]), [])

    def test_all_blank(self):
        self.assertEqual(
            _collapse_consecutive_blank_lines(["", "", ""]),
            [""],
        )


if __name__ == "__main__":
    unittest.main()
