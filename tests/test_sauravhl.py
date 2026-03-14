#!/usr/bin/env python3
"""Tests for sauravhl.py — syntax highlighter for sauravcode."""

import sys
import os
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from sauravhl import (
    tokenize, _classify_token, highlight_ansi, highlight_html,
    find_srv_files, BUILTINS, TYPE_KEYWORDS, CONTROL_KEYWORDS,
    DECL_KEYWORDS, LITERAL_KEYWORDS, THEMES_ANSI, THEMES_HTML
)


class TestTokenClassification(unittest.TestCase):
    """Test token classification logic."""

    def test_comment(self):
        self.assertEqual(_classify_token('COMMENT', '# hello'), 'comment')

    def test_string(self):
        self.assertEqual(_classify_token('STRING', '"hello"'), 'string')

    def test_fstring(self):
        self.assertEqual(_classify_token('FSTRING', 'f"hello {x}"'), 'fstring')

    def test_number(self):
        self.assertEqual(_classify_token('NUMBER', '42'), 'number')

    def test_control_keywords(self):
        for kw in ('if', 'else', 'while', 'for', 'return', 'break', 'continue'):
            self.assertEqual(_classify_token('KEYWORD', kw), 'keyword_control', kw)

    def test_decl_keywords(self):
        for kw in ('function', 'class', 'enum', 'import', 'lambda'):
            self.assertEqual(_classify_token('KEYWORD', kw), 'keyword_decl', kw)

    def test_type_keywords(self):
        for kw in ('int', 'float', 'bool', 'string', 'list'):
            self.assertEqual(_classify_token('KEYWORD', kw), 'keyword_type', kw)

    def test_literal_keywords(self):
        self.assertEqual(_classify_token('KEYWORD', 'true'), 'keyword_literal')
        self.assertEqual(_classify_token('KEYWORD', 'false'), 'keyword_literal')

    def test_other_keywords(self):
        for kw in ('and', 'or', 'not'):
            self.assertEqual(_classify_token('KEYWORD', kw), 'keyword_other', kw)

    def test_builtin_ident(self):
        self.assertEqual(_classify_token('IDENT', 'print'), 'builtin')
        self.assertEqual(_classify_token('IDENT', 'len'), 'builtin')

    def test_regular_ident(self):
        self.assertEqual(_classify_token('IDENT', 'myVar'), 'identifier')

    def test_operators(self):
        for op_type in ('OP', 'ASSIGN', 'EQ', 'NEQ', 'LTE', 'GTE', 'LT', 'GT', 'ARROW', 'PIPE'):
            self.assertEqual(_classify_token(op_type, '+'), 'operator')

    def test_punctuation(self):
        for p_type in ('LPAREN', 'RPAREN', 'LBRACKET', 'RBRACKET', 'COLON', 'COMMA', 'DOT'):
            self.assertEqual(_classify_token(p_type, '('), 'punctuation')

    def test_space_none(self):
        self.assertIsNone(_classify_token('SPACE', ' '))

    def test_newline_none(self):
        self.assertIsNone(_classify_token('NEWLINE', '\n'))


class TestTokenize(unittest.TestCase):
    """Test the tokenizer."""

    def test_simple_print(self):
        tokens = tokenize('print "hello"')
        types = [(t, v) for t, v, c in tokens if t not in ('SPACE',)]
        self.assertEqual(types[0], ('KEYWORD', 'print'))
        self.assertEqual(types[1], ('STRING', '"hello"'))

    def test_assignment(self):
        tokens = tokenize('x = 42')
        non_space = [(t, v) for t, v, c in tokens if t != 'SPACE']
        self.assertEqual(non_space[0], ('IDENT', 'x'))
        self.assertEqual(non_space[1], ('ASSIGN', '='))
        self.assertEqual(non_space[2][0], 'NUMBER')

    def test_function_def(self):
        tokens = tokenize('function add x y')
        non_space = [(t, v) for t, v, c in tokens if t != 'SPACE']
        self.assertEqual(non_space[0], ('KEYWORD', 'function'))
        self.assertEqual(non_space[1], ('IDENT', 'add'))

    def test_comment(self):
        tokens = tokenize('# this is a comment')
        self.assertEqual(tokens[0][0], 'COMMENT')

    def test_fstring(self):
        tokens = tokenize('f"value is {x}"')
        self.assertEqual(tokens[0][0], 'FSTRING')

    def test_comparison_ops(self):
        tokens = tokenize('x == y != z <= w >= v < u > t')
        ops = [v for t, v, c in tokens if c == 'operator']
        self.assertEqual(ops, ['==', '!=', '<=', '>=', '<', '>', ])

    def test_arrow_and_pipe(self):
        tokens = tokenize('-> |>')
        ops = [v for t, v, c in tokens if c == 'operator']
        self.assertIn('->', ops)
        self.assertIn('|>', ops)

    def test_empty_source(self):
        self.assertEqual(tokenize(''), [])


class TestHighlightAnsi(unittest.TestCase):
    """Test ANSI output."""

    def test_basic_output(self):
        result = highlight_ansi('print "hello"')
        self.assertIn('\033[', result)  # Has ANSI codes
        self.assertIn('print', result)
        self.assertIn('hello', result)

    def test_line_numbers(self):
        result = highlight_ansi('x = 1\ny = 2', line_numbers=True)
        self.assertIn('1', result)
        self.assertIn('2', result)

    def test_all_themes(self):
        source = 'function add x y\n  return x + y'
        for theme in THEMES_ANSI:
            result = highlight_ansi(source, theme_name=theme)
            self.assertIn('function', result)
            self.assertIn('add', result)

    def test_unknown_theme_falls_back(self):
        result = highlight_ansi('print 42', theme_name='nonexistent')
        self.assertIn('print', result)

    def test_multiline(self):
        source = 'x = 1\ny = 2\nprint x + y'
        result = highlight_ansi(source)
        self.assertEqual(result.count('\n'), 2)


class TestHighlightHtml(unittest.TestCase):
    """Test HTML output."""

    def test_standalone_page(self):
        result = highlight_html('print "hello"')
        self.assertIn('<!DOCTYPE html>', result)
        self.assertIn('<html', result)
        self.assertIn('srv-highlight', result)

    def test_fragment_mode(self):
        result = highlight_html('print 42', standalone=False)
        self.assertNotIn('<!DOCTYPE html>', result)
        self.assertIn('<style>', result)
        self.assertIn('srv-highlight', result)

    def test_line_numbers(self):
        result = highlight_html('x = 1\ny = 2', line_numbers=True)
        self.assertIn('srv-lineno', result)

    def test_html_escaping(self):
        result = highlight_html('x = 1\nif x < 2')
        self.assertIn('&lt;', result)  # < must be escaped

    def test_custom_title(self):
        result = highlight_html('x = 1', title='My Program')
        self.assertIn('My Program', result)

    def test_all_themes(self):
        for theme in THEMES_HTML:
            result = highlight_html('print 42', theme_name=theme)
            self.assertIn('srv-highlight', result)

    def test_css_classes(self):
        result = highlight_html('function add x y\n  return x + y\n# comment\nprint "hi"')
        self.assertIn('srv-keyword_decl', result)
        self.assertIn('srv-keyword_control', result)
        self.assertIn('srv-comment', result)
        self.assertIn('srv-string', result)

    def test_string_escaping(self):
        # Ensure quotes in strings are properly escaped
        result = highlight_html('x = "a & b"')
        self.assertIn('&amp;', result)


class TestFindSrvFiles(unittest.TestCase):
    """Test file discovery."""

    def test_single_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = __import__('pathlib').Path(d) / 'test.srv'
            p.write_text('print "test"')
            files = find_srv_files(str(p))
            self.assertEqual(len(files), 1)

    def test_directory(self):
        with tempfile.TemporaryDirectory() as d:
            (p := __import__('pathlib').Path(d) / 'a.srv').write_text('x = 1')
            (p2 := __import__('pathlib').Path(d) / 'b.txt').write_text('not srv')
            files = find_srv_files(d)
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].name, 'a.srv')

    def test_recursive(self):
        with tempfile.TemporaryDirectory() as d:
            sub = __import__('pathlib').Path(d) / 'sub'
            sub.mkdir()
            (__import__('pathlib').Path(d) / 'a.srv').write_text('x = 1')
            (sub / 'b.srv').write_text('y = 2')
            files = find_srv_files(d, recursive=True)
            self.assertEqual(len(files), 2)

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as d:
            files = find_srv_files(d)
            self.assertEqual(len(files), 0)


class TestThemeConsistency(unittest.TestCase):
    """Ensure all themes have the same keys."""

    def test_ansi_themes_same_keys(self):
        base_keys = set(THEMES_ANSI['default'].keys())
        for name, theme in THEMES_ANSI.items():
            self.assertEqual(set(theme.keys()), base_keys, f'Theme {name} key mismatch')

    def test_html_themes_same_keys(self):
        base_keys = set(THEMES_HTML['default'].keys())
        for name, theme in THEMES_HTML.items():
            self.assertEqual(set(theme.keys()), base_keys, f'Theme {name} key mismatch')

    def test_same_theme_names(self):
        self.assertEqual(set(THEMES_ANSI.keys()), set(THEMES_HTML.keys()))


class TestEdgeCases(unittest.TestCase):
    """Edge cases and complex inputs."""

    def test_nested_structures(self):
        source = 'x = [1, 2, {"a": 3}]'
        result = highlight_ansi(source)
        self.assertIn('x', result)

    def test_lambda(self):
        tokens = tokenize('lambda x -> x + 1')
        cats = [c for _, _, c in tokens if c]
        self.assertIn('keyword_decl', cats)
        self.assertIn('operator', cats)

    def test_match_case(self):
        source = 'match x\n  case 1\n    print "one"'
        tokens = tokenize(source)
        kw_values = [v for t, v, c in tokens if c and 'keyword' in c]
        self.assertIn('match', kw_values)
        self.assertIn('case', kw_values)

    def test_all_builtins_classified(self):
        for b in BUILTINS:
            self.assertEqual(_classify_token('IDENT', b), 'builtin', b)


if __name__ == '__main__':
    unittest.main()
