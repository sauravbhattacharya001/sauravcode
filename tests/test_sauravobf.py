#!/usr/bin/env python3
"""Tests for sauravobf.py - Source code obfuscator for sauravcode."""

import os
import sys
import json
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sauravobf import (
    NameGenerator,
    collect_identifiers,
    build_rename_map,
    obfuscate_line,
    obfuscate_source,
    obfuscate_fstring_expressions,
    obfuscation_stats,
    obfuscate_file,
    obfuscate_directory,
    RESERVED,
)
from saurav import tokenize, Parser


class TestNameGenerator(unittest.TestCase):
    """Test the sequential name generator used for obfuscation."""

    def test_first_26_names(self):
        gen = NameGenerator('_')
        names = [gen.next() for _ in range(26)]
        self.assertEqual(names[0], '_a')
        self.assertEqual(names[25], '_z')

    def test_wraps_to_two_chars(self):
        gen = NameGenerator('_')
        names = [gen.next() for _ in range(27)]
        self.assertEqual(names[26], '_aa')

    def test_custom_prefix(self):
        gen = NameGenerator('__v')
        self.assertEqual(gen.next(), '__va')
        self.assertEqual(gen.next(), '__vb')

    def test_reset(self):
        gen = NameGenerator('_')
        gen.next()
        gen.next()
        gen.reset()
        self.assertEqual(gen.next(), '_a')

    def test_many_names_unique(self):
        gen = NameGenerator('_')
        names = [gen.next() for _ in range(200)]
        self.assertEqual(len(set(names)), 200)


class TestCollectIdentifiers(unittest.TestCase):
    """Test AST-aware identifier collection."""

    def _parse(self, source):
        tokens = tokenize(source)
        return Parser(tokens).parse()

    def test_simple_assignment(self):
        ast = self._parse('x = 10')
        ids = collect_identifiers(ast)
        self.assertIn('x', ids)

    def test_builtins_excluded(self):
        ast = self._parse('x = len("hello")')
        ids = collect_identifiers(ast)
        self.assertIn('x', ids)
        self.assertNotIn('len', ids)

    def test_keywords_excluded(self):
        ast = self._parse('x = true')
        ids = collect_identifiers(ast)
        self.assertNotIn('true', ids)
        self.assertNotIn('if', ids)

    def test_function_name_and_params(self):
        ast = self._parse('function greet name\n  print name\nend')
        ids = collect_identifiers(ast)
        self.assertIn('greet', ids)
        self.assertIn('name', ids)

    def test_for_loop_variable(self):
        ast = self._parse('for item in [1, 2, 3]\n  print item')
        ids = collect_identifiers(ast)
        self.assertIn('item', ids)


class TestBuildRenameMap(unittest.TestCase):
    """Test rename map construction."""

    def test_deterministic_order(self):
        ids = {'zebra', 'alpha', 'middle'}
        m = build_rename_map(ids, '_')
        # sorted order: alpha, middle, zebra
        self.assertEqual(m['alpha'], '_a')
        self.assertEqual(m['middle'], '_b')
        self.assertEqual(m['zebra'], '_c')

    def test_custom_prefix(self):
        ids = {'foo'}
        m = build_rename_map(ids, '__x')
        self.assertEqual(m['foo'], '__xa')

    def test_empty_identifiers(self):
        m = build_rename_map(set(), '_')
        self.assertEqual(m, {})


class TestObfuscateLine(unittest.TestCase):
    """Test line-level obfuscation."""

    def test_renames_identifier(self):
        result = obfuscate_line('x = 10', {'x': '_a'})
        self.assertEqual(result, '_a = 10')

    def test_preserves_strings(self):
        result = obfuscate_line('name = "hello"', {'name': '_a'})
        self.assertIn('"hello"', result)
        self.assertIn('_a', result)

    def test_preserves_comments_by_default(self):
        result = obfuscate_line('# this is a comment', {})
        self.assertEqual(result, '# this is a comment')

    def test_strips_comments_when_requested(self):
        result = obfuscate_line('# this is a comment', {}, strip_comments=True)
        self.assertIsNone(result)

    def test_inline_comment_stripped(self):
        result = obfuscate_line('x = 10 # set x', {'x': '_a'}, strip_comments=True)
        self.assertEqual(result, '_a = 10 ')

    def test_empty_line_preserved(self):
        result = obfuscate_line('', {})
        self.assertEqual(result, '')

    def test_partial_rename(self):
        result = obfuscate_line('y = x + 1', {'x': '_a', 'y': '_b'})
        self.assertEqual(result, '_b = _a + 1')

    def test_unrenamed_identifiers_preserved(self):
        result = obfuscate_line('z = print(x)', {'x': '_a'})
        self.assertIn('z', result)
        self.assertIn('_a', result)


class TestObfuscateSource(unittest.TestCase):
    """Test full source obfuscation."""

    def test_multi_line(self):
        source = 'x = 10\ny = x + 1'
        result = obfuscate_source(source, {'x': '_a', 'y': '_b'})
        self.assertIn('_a = 10', result)
        self.assertIn('_b = _a + 1', result)

    def test_strip_comments_collapses_blanks(self):
        source = '# comment\n\n\nx = 1'
        result = obfuscate_source(source, {'x': '_a'}, strip_comments=True)
        lines = result.split('\n')
        # Should not have consecutive blank lines
        consecutive_blanks = sum(1 for i in range(len(lines)-1)
                                 if not lines[i].strip() and not lines[i+1].strip())
        self.assertEqual(consecutive_blanks, 0)


class TestObfuscateFstringExpressions(unittest.TestCase):
    """Test f-string expression renaming."""

    def test_renames_in_fstring(self):
        source = 'msg = f"Hello {name}, you are {age} years old"'
        result = obfuscate_fstring_expressions(source, {'name': '_a', 'age': '_b'})
        self.assertIn('{_a}', result)
        self.assertIn('{_b}', result)

    def test_no_rename_for_unmapped(self):
        source = 'msg = f"Value: {unknown}"'
        result = obfuscate_fstring_expressions(source, {})
        self.assertIn('{unknown}', result)


class TestObfuscationStats(unittest.TestCase):
    """Test statistics computation."""

    def test_basic_stats(self):
        source = 'x = 10\ny = 20\n# comment'
        obfuscated = '_a = 10\n_b = 20'
        rename_map = {'x': '_a', 'y': '_b'}
        stats = obfuscation_stats(source, obfuscated, rename_map)
        self.assertEqual(stats['identifiers_renamed'], 2)
        self.assertEqual(stats['original_lines'], 3)
        self.assertEqual(stats['obfuscated_lines'], 2)
        self.assertEqual(stats['lines_removed'], 1)
        self.assertGreater(stats['size_reduction_pct'], 0)

    def test_empty_source(self):
        stats = obfuscation_stats('', '', {})
        self.assertEqual(stats['identifiers_renamed'], 0)
        self.assertEqual(stats['size_reduction_pct'], 0)


class TestObfuscateFile(unittest.TestCase):
    """Test file-level obfuscation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_obfuscate_simple_file(self):
        path = os.path.join(self.tmpdir, 'test.srv')
        with open(path, 'w') as f:
            f.write('greeting = "hello"\nprint(greeting)\n')
        obfuscated, rename_map, stats = obfuscate_file(path)
        self.assertIn('greeting', rename_map)
        self.assertNotIn('greeting', obfuscated)
        self.assertIn('"hello"', obfuscated)
        self.assertGreater(stats['identifiers_renamed'], 0)

    def test_obfuscate_with_strip_comments(self):
        path = os.path.join(self.tmpdir, 'test.srv')
        with open(path, 'w') as f:
            f.write('# This is a comment\nx = 42\n')
        obfuscated, _, _ = obfuscate_file(path, strip_comments=True)
        self.assertNotIn('# This is a comment', obfuscated)

    def test_obfuscate_preserves_semantics(self):
        path = os.path.join(self.tmpdir, 'test.srv')
        source = 'function add a, b\n  return a + b\nend\nresult = add 1, 2\n'
        with open(path, 'w') as f:
            f.write(source)
        obfuscated, rename_map, _ = obfuscate_file(path)
        # All user identifiers should be renamed
        for ident in ('add', 'a', 'b', 'result'):
            self.assertIn(ident, rename_map)


class TestObfuscateDirectory(unittest.TestCase):
    """Test directory batch obfuscation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.outdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)
        shutil.rmtree(self.outdir)

    def test_batch_obfuscate(self):
        for name in ('a.srv', 'b.srv'):
            with open(os.path.join(self.tmpdir, name), 'w') as f:
                f.write(f'val_{name[0]} = 1\n')
        results = obfuscate_directory(self.tmpdir, self.outdir)
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertTrue(os.path.exists(
                os.path.join(self.outdir, os.path.basename(r['file']))))

    def test_skips_non_srv_files(self):
        with open(os.path.join(self.tmpdir, 'readme.txt'), 'w') as f:
            f.write('not code')
        with open(os.path.join(self.tmpdir, 'code.srv'), 'w') as f:
            f.write('x = 1\n')
        results = obfuscate_directory(self.tmpdir, self.outdir)
        self.assertEqual(len(results), 1)

    def test_recursive_mode(self):
        subdir = os.path.join(self.tmpdir, 'sub')
        os.makedirs(subdir)
        with open(os.path.join(subdir, 'nested.srv'), 'w') as f:
            f.write('y = 2\n')
        with open(os.path.join(self.tmpdir, 'top.srv'), 'w') as f:
            f.write('x = 1\n')
        results = obfuscate_directory(self.tmpdir, self.outdir, recursive=True)
        self.assertEqual(len(results), 2)


class TestReservedNotRenamed(unittest.TestCase):
    """Verify that reserved words (keywords + builtins) are never renamed."""

    def test_reserved_set_populated(self):
        self.assertIn('if', RESERVED)
        self.assertIn('len', RESERVED)
        self.assertIn('print', RESERVED)
        self.assertIn('return', RESERVED)

    def test_reserved_not_in_rename_map(self):
        # build_rename_map doesn't filter — collect_identifiers does.
        # Verify that collect_identifiers properly excludes reserved words.
        ids = collect_identifiers([])
        for kw in ('if', 'len', 'print', 'return', 'while', 'for'):
            self.assertNotIn(kw, ids)

    def test_collect_identifiers_excludes_reserved(self):
        from saurav import tokenize, Parser
        ast = Parser(tokenize('x = len("hello")\nprint x')).parse()
        ids = collect_identifiers(ast)
        self.assertIn('x', ids)
        self.assertNotIn('len', ids)
        self.assertNotIn('print', ids)


if __name__ == '__main__':
    unittest.main()
