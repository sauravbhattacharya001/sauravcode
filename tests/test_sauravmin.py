#!/usr/bin/env python3
"""Tests for sauravmin - sauravcode minifier."""

import json
import os
import sys
import tempfile
import textwrap
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sauravmin import (
    minify, minify_file, _strip_comments, _collect_identifiers,
    _build_rename_map, _id_generator, _apply_renames, RESERVED,
)


class TestStripComments(unittest.TestCase):
    def test_simple_comment(self):
        self.assertEqual(_strip_comments('x = 1 # assign'), 'x = 1')

    def test_no_comment(self):
        self.assertEqual(_strip_comments('x = 1'), 'x = 1')

    def test_full_line_comment(self):
        self.assertEqual(_strip_comments('# full comment'), '')

    def test_hash_in_double_string(self):
        self.assertEqual(_strip_comments('x = "hello # world"'), 'x = "hello # world"')

    def test_hash_in_single_string(self):
        self.assertEqual(_strip_comments("x = 'test#val'"), "x = 'test#val'")

    def test_string_then_comment(self):
        self.assertEqual(_strip_comments('x = "a#b" # comment'), 'x = "a#b"')

    def test_escaped_quote(self):
        self.assertEqual(_strip_comments(r'x = "he\"llo" # c'), r'x = "he\"llo"')

    def test_empty_line(self):
        self.assertEqual(_strip_comments(''), '')


class TestLevel0(unittest.TestCase):
    def test_strips_comments(self):
        src = "x = 1  # assign\ny = 2\n# full comment\nprint x\n"
        out, stats, _ = minify(src, level=0)
        self.assertNotIn('# assign', out)
        self.assertNotIn('# full comment', out)
        self.assertIn('x = 1', out)
        self.assertIn('print x', out)

    def test_strips_trailing_whitespace(self):
        src = "x = 1   \ny = 2\t  \n"
        out, _, _ = minify(src, level=0)
        for line in out.split('\n'):
            self.assertEqual(line, line.rstrip())

    def test_preserves_blank_lines(self):
        src = "x = 1\n\n\ny = 2\n"
        out, _, _ = minify(src, level=0)
        self.assertIn('\n\n', out)


class TestLevel1(unittest.TestCase):
    def test_collapses_blank_runs(self):
        src = "x = 1\n\n\n\ny = 2\n\nz = 3\n"
        out, _, _ = minify(src, level=1)
        self.assertNotIn('\n\n\n', out)
        self.assertIn('x = 1\n\ny = 2', out)

    def test_single_blank_preserved(self):
        src = "a = 1\n\nb = 2\n"
        out, _, _ = minify(src, level=1)
        self.assertIn('a = 1\n\nb = 2', out)


class TestLevel2(unittest.TestCase):
    def test_no_blank_lines(self):
        src = "x = 1\n\n\ny = 2\n# comment\n\nz = 3\n"
        out, _, _ = minify(src, level=2)
        self.assertNotIn('\n\n', out)
        self.assertIn('x = 1', out)
        self.assertIn('y = 2', out)
        self.assertIn('z = 3', out)

    def test_comments_removed(self):
        src = "# header\nx = 1\n# inline\ny = 2\n"
        out, _, _ = minify(src, level=2)
        self.assertNotIn('#', out)

    def test_indentation_preserved(self):
        src = "function foo x\n    return x + 1\nprint foo 5\n"
        out, _, _ = minify(src, level=2)
        self.assertIn('    return', out)


class TestLevel3(unittest.TestCase):
    def test_renames_identifiers(self):
        src = textwrap.dedent("""\
            function calculate_total price quantity
                tax_rate = 0.08
                subtotal = price * quantity
                tax = subtotal * tax_rate
                return subtotal + tax
            result = calculate_total 10 5
            print result
        """)
        out, stats, rmap = minify(src, level=3)
        self.assertGreater(stats['identifiers_renamed'], 0)
        self.assertNotIn('calculate_total', out)
        self.assertNotIn('tax_rate', out)
        self.assertIn('function', out)
        self.assertIn('print', out)
        self.assertIn('return', out)
        self.assertLess(len(out), len(src))

    def test_rename_map_has_originals(self):
        src = "my_var = 42\nprint my_var\n"
        _, _, rmap = minify(src, level=3)
        self.assertIn('my_var', rmap)

    def test_consistent_rename(self):
        src = "counter = 0\ncounter = counter + 1\nprint counter\n"
        out, _, rmap = minify(src, level=3)
        self.assertNotIn('counter', out)
        renamed = rmap['counter']
        self.assertEqual(out.count(renamed), 4)

    def test_keywords_preserved(self):
        src = "if true\n    print 1\nelse\n    print 2\n"
        out, _, _ = minify(src, level=3)
        self.assertIn('if', out)
        self.assertIn('true', out)
        self.assertIn('else', out)
        self.assertIn('print', out)

    def test_builtins_preserved(self):
        src = 'x = len "hello"\nprint x\n'
        out, _, _ = minify(src, level=3)
        self.assertIn('len', out)
        self.assertIn('print', out)


class TestStats(unittest.TestCase):
    def test_stats_fields(self):
        src = "# comment\nx = 1\n\n\ny = 2\n"
        _, stats, _ = minify(src, level=2)
        self.assertEqual(stats['original_bytes'], len(src))
        self.assertGreater(stats['compression_pct'], 0)
        self.assertGreater(stats['removed_lines'], 0)
        self.assertEqual(stats['level'], 2)

    def test_stats_level3(self):
        src = "my_variable = 42\nprint my_variable\n"
        _, stats, _ = minify(src, level=3)
        self.assertGreater(stats['identifiers_renamed'], 0)


class TestEdgeCases(unittest.TestCase):
    def test_empty_source(self):
        out, stats, _ = minify("", level=2)
        self.assertEqual(stats['original_bytes'], 0)

    def test_only_comments(self):
        out, _, _ = minify("# hello\n# world\n", level=2)
        self.assertEqual(out.strip(), '')

    def test_hash_in_string(self):
        src = 'x = "hello # world"\nprint x\n'
        out, _, _ = minify(src, level=2)
        self.assertIn('"hello # world"', out)

    def test_fstring_preserved(self):
        src = 'name = "Alice"\nprint f"Hello, {name}!"\n'
        out, _, _ = minify(src, level=2)
        self.assertIn('f"Hello,', out)

    def test_single_line(self):
        src = "print 42\n"
        out, _, _ = minify(src, level=2)
        self.assertEqual(out.strip(), 'print 42')


class TestIdGenerator(unittest.TestCase):
    def test_unique(self):
        gen = _id_generator()
        ids = [next(gen) for _ in range(50)]
        self.assertEqual(len(set(ids)), 50)

    def test_start_with_underscore(self):
        gen = _id_generator()
        for _ in range(30):
            self.assertTrue(next(gen).startswith('_'))

    def test_no_reserved(self):
        gen = _id_generator()
        for _ in range(100):
            self.assertNotIn(next(gen), RESERVED)


class TestCollectIdentifiers(unittest.TestCase):
    def test_finds_user_ids(self):
        ids = _collect_identifiers('x = 1\ny = x + 2\nprint y\n')
        self.assertIn('x', ids)
        self.assertIn('y', ids)

    def test_excludes_builtins(self):
        ids = _collect_identifiers('x = len "hello"\nprint x\n')
        self.assertNotIn('len', ids)
        self.assertNotIn('print', ids)

    def test_excludes_keywords(self):
        ids = _collect_identifiers('if true\n    return 1\n')
        self.assertNotIn('if', ids)
        self.assertNotIn('true', ids)
        self.assertNotIn('return', ids)

    def test_frequency_sorted(self):
        ids = _collect_identifiers('a = 1\nb = a\nc = a + b\na = a + 1\n')
        keys = list(ids.keys())
        self.assertEqual(keys[0], 'a')  # most frequent


class TestApplyRenames(unittest.TestCase):
    def test_basic_rename(self):
        result = _apply_renames('foo = 1\nprint foo\n', {'foo': '_a'})
        self.assertEqual(result, '_a = 1\nprint _a\n')

    def test_preserves_strings(self):
        result = _apply_renames('foo = "foo is cool"\n', {'foo': '_a'})
        self.assertIn('"foo is cool"', result)
        self.assertTrue(result.startswith('_a'))

    def test_preserves_comments(self):
        result = _apply_renames('foo = 1 # foo comment\n', {'foo': '_a'})
        self.assertIn('# foo comment', result)
        self.assertTrue(result.startswith('_a'))


class TestMinifyFile(unittest.TestCase):
    def test_file_round_trip(self):
        src = "# header\nx = 1\n\ny = 2\nprint x + y\n"
        with tempfile.NamedTemporaryFile(mode='w', suffix='.srv',
                                         delete=False, encoding='utf-8') as f:
            f.write(src)
            f.flush()
            tmp_in = f.name
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.srv',
                                             delete=False, encoding='utf-8') as f:
                tmp_out = f.name
            stats = minify_file(tmp_in, output=tmp_out, level=2)
            with open(tmp_out, 'r', encoding='utf-8') as f:
                result = f.read()
            self.assertNotIn('#', result)
            self.assertNotIn('\n\n', result)
            self.assertIn('x = 1', result)
            self.assertGreater(stats['compression_pct'], 0)
        finally:
            os.unlink(tmp_in)
            if os.path.exists(tmp_out):
                os.unlink(tmp_out)

    def test_dry_run(self):
        src = "x = 1\n"
        with tempfile.NamedTemporaryFile(mode='w', suffix='.srv',
                                         delete=False, encoding='utf-8') as f:
            f.write(src)
            tmp = f.name
        try:
            stats = minify_file(tmp, dry_run=True, level=2)
            self.assertIn('file', stats)
        finally:
            os.unlink(tmp)

    def test_map_export(self):
        src = "my_var = 42\nprint my_var\n"
        with tempfile.NamedTemporaryFile(mode='w', suffix='.srv',
                                         delete=False, encoding='utf-8') as f:
            f.write(src)
            tmp_in = f.name
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                             delete=False, encoding='utf-8') as f:
                tmp_map = f.name
            with tempfile.NamedTemporaryFile(mode='w', suffix='.srv',
                                             delete=False, encoding='utf-8') as f:
                tmp_out = f.name
            minify_file(tmp_in, output=tmp_out, level=3, map_path=tmp_map)
            with open(tmp_map, 'r', encoding='utf-8') as f:
                rmap = json.load(f)
            self.assertIn('my_var', rmap)
        finally:
            for p in [tmp_in, tmp_map, tmp_out]:
                if os.path.exists(p):
                    os.unlink(p)


if __name__ == '__main__':
    unittest.main()
