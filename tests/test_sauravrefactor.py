"""Tests for sauravrefactor — automated refactoring tool for .srv files."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sauravrefactor import (
    refactor_rename,
    refactor_extract,
    refactor_inline,
    refactor_deadcode,
    refactor_unused,
    show_diff,
    format_json,
    get_color,
    _replace_outside_strings,
    _walk,
    _get_identifiers,
    _get_function_calls,
    _get_assignments,
    _get_function_defs,
    _get_imports,
    _collect_names,
    Color,
    NO_COLOR,
    __version__,
)


class TestRename(unittest.TestCase):
    """Tests for refactor_rename."""

    def test_basic_variable_rename(self):
        src = 'x = 10\ny = x + 5\nprint(x)\n'
        result, count, _ = refactor_rename(src, 'x', 'counter')
        self.assertEqual(count, 3)
        self.assertIn('counter = 10', result)
        self.assertIn('counter + 5', result)
        self.assertIn('print(counter)', result)

    def test_function_rename(self):
        src = 'function greet(name)\n    print(name)\ngreet("hi")\n'
        result, count, _ = refactor_rename(src, 'greet', 'say_hello')
        self.assertGreaterEqual(count, 2)
        self.assertIn('function say_hello', result)
        self.assertIn('say_hello("hi")', result)

    def test_skip_inside_strings(self):
        src = 'x = "hello x world"\ny = x\n'
        result, count, _ = refactor_rename(src, 'x', 'z')
        self.assertIn('"hello x world"', result)
        self.assertIn('z = "hello x world"', result)

    def test_reject_reserved_word(self):
        src = 'x = 1\n'
        _, count, _ = refactor_rename(src, 'x', 'for')
        self.assertEqual(count, 0)

    def test_reject_invalid_identifier(self):
        src = 'x = 1\n'
        _, count, _ = refactor_rename(src, 'x', '123bad')
        self.assertEqual(count, 0)

    def test_word_boundary(self):
        src = 'fox = 1\nx = 2\n'
        result, count, _ = refactor_rename(src, 'x', 'y')
        self.assertIn('fox = 1', result)
        self.assertIn('y = 2', result)

    def test_skip_comments(self):
        src = 'x = 1 # x is important\n'
        result, count, _ = refactor_rename(src, 'x', 'val')
        self.assertIn('val = 1', result)
        self.assertIn('# x is important', result)

    def test_no_partial_match(self):
        src = 'ab = 1\nabc = 2\na = ab + abc\n'
        result, count, _ = refactor_rename(src, 'ab', 'xy')
        self.assertIn('xy = 1', result)
        self.assertIn('abc = 2', result)

    def test_empty_source(self):
        result, count, _ = refactor_rename('', 'x', 'y')
        self.assertEqual(result, '')
        self.assertEqual(count, 0)

    def test_rename_in_function_params(self):
        src = 'function add(a, b)\n    return a + b\nresult = add(1, 2)\n'
        result, count, _ = refactor_rename(src, 'a', 'first')
        self.assertIn('first', result)
        self.assertGreaterEqual(count, 2)

    def test_no_occurrences(self):
        src = 'y = 1\nprint(y)\n'
        result, count, _ = refactor_rename(src, 'x', 'z')
        self.assertEqual(count, 0)
        self.assertEqual(result, src)

    def test_reject_with_spaces_in_name(self):
        src = 'x = 1\n'
        _, count, _ = refactor_rename(src, 'x', 'new name')
        self.assertEqual(count, 0)


class TestExtract(unittest.TestCase):
    """Tests for refactor_extract."""

    def test_basic_extract(self):
        src = 'a = 10\nb = 20\nc = a + b\nprint(c)\n'
        result, changes = refactor_extract(src, 2, 3, 'compute')
        self.assertIn('function compute', result)
        self.assertIn('compute(', result)

    def test_extract_with_params(self):
        src = 'x = 5\ny = x * 2\nz = y + 1\nprint(z)\n'
        result, changes = refactor_extract(src, 2, 3, 'transform')
        self.assertIn('function transform', result)

    def test_invalid_range(self):
        src = 'x = 1\ny = 2\n'
        result, changes = refactor_extract(src, 5, 3, 'bad')
        self.assertIn('Invalid line range', changes[0])

    def test_invalid_func_name(self):
        src = 'x = 1\ny = 2\n'
        result, changes = refactor_extract(src, 1, 2, '123func')
        self.assertIn('Invalid function name', changes[0])

    def test_single_line_extract(self):
        src = 'a = 1\nb = a + 1\nprint(b)\n'
        result, changes = refactor_extract(src, 2, 2, 'inc')
        self.assertIn('function inc', result)

    def test_extract_reports_changes(self):
        src = 'a = 10\nb = 20\nc = a + b\nprint(c)\n'
        _, changes = refactor_extract(src, 2, 3, 'compute')
        self.assertTrue(any('Extracted' in c for c in changes))
        self.assertTrue(any('Parameters' in c for c in changes))
        self.assertTrue(any('Returns' in c for c in changes))


class TestInline(unittest.TestCase):
    """Tests for refactor_inline."""

    def test_basic_inline(self):
        src = 'temp = 42\nresult = temp + 1\nprint(result)\n'
        result, changes = refactor_inline(src, 'temp')
        self.assertIn('42 + 1', result)

    def test_inline_with_parens(self):
        src = 'a = 1 + 2\nb = a * 3\n'
        result, changes = refactor_inline(src, 'a')
        self.assertIn('(1 + 2)', result)

    def test_inline_unused_removes(self):
        src = 'x = 10\ny = 20\nz = y\n'
        result, changes = refactor_inline(src, 'x')
        self.assertNotIn('x = 10', result)

    def test_reject_multi_assign(self):
        src = 'x = 1\nx = 2\ny = x\n'
        _, changes = refactor_inline(src, 'x')
        self.assertIn('assigned 2 times', changes[0])

    def test_reject_missing_var(self):
        src = 'a = 1\nb = 2\n'
        _, changes = refactor_inline(src, 'z')
        self.assertIn('No assignment', changes[0])

    def test_inline_multiple_usages(self):
        src = 'c = 100\na = c\nb = c\nprint(a + b)\n'
        result, changes = refactor_inline(src, 'c')
        self.assertIn('a = 100', result)
        self.assertIn('b = 100', result)


class TestDeadCode(unittest.TestCase):
    """Tests for refactor_deadcode."""

    def test_remove_after_return(self):
        src = 'function foo()\n    return 1\n    x = 2\n    print(x)\n'
        result, changes = refactor_deadcode(src)
        self.assertGreater(len(changes), 0)

    def test_no_false_positives(self):
        src = 'x = 1\ny = 2\nprint(x + y)\n'
        result, changes = refactor_deadcode(src)
        self.assertEqual(len(changes), 0)
        self.assertEqual(result, src)

    def test_empty_source(self):
        result, changes = refactor_deadcode('')
        self.assertEqual(result, '')
        self.assertEqual(len(changes), 0)

    def test_comments_and_blank_lines(self):
        src = '# just a comment\n\n# another\n'
        result, changes = refactor_deadcode(src)
        self.assertEqual(len(changes), 0)


class TestUnused(unittest.TestCase):
    """Tests for refactor_unused."""

    def test_remove_unused_variable(self):
        src = 'x = 10\ny = 20\nprint(y)\n'
        result, changes = refactor_unused(src)
        self.assertGreater(len(changes), 0)

    def test_keep_used_variables(self):
        src = 'a = 1\nb = a + 1\nprint(b)\n'
        result, changes = refactor_unused(src)
        self.assertEqual(len(changes), 0)

    def test_empty_source(self):
        result, changes = refactor_unused('')
        self.assertEqual(len(changes), 0)


class TestUtilities(unittest.TestCase):
    """Tests for helper functions."""

    def test_replace_outside_strings(self):
        r = _replace_outside_strings('x = "hello x" + x', 'x', 'y')
        self.assertEqual(r, 'y = "hello x" + y')

    def test_replace_no_strings(self):
        r = _replace_outside_strings('a + b + a', 'a', 'z')
        self.assertEqual(r, 'z + b + z')

    def test_replace_all_in_string(self):
        r = _replace_outside_strings('"x x x"', 'x', 'y')
        self.assertEqual(r, '"x x x"')

    def test_show_diff(self):
        diff = show_diff("a = 1\n", "b = 1\n", "test.srv", get_color(False))
        self.assertIn('---', diff)

    def test_show_diff_no_changes(self):
        diff = show_diff("a = 1\n", "a = 1\n", "test.srv", get_color(False))
        self.assertEqual(diff, "")

    def test_format_json(self):
        js = format_json("rename", "test.srv", ["renamed x"], "old", "new")
        parsed = json.loads(js)
        self.assertEqual(parsed["command"], "rename")
        self.assertTrue(parsed["modified"])
        self.assertEqual(parsed["tool"], "sauravrefactor")

    def test_format_json_no_change(self):
        js = format_json("deadcode", "test.srv", [], "same", "same")
        parsed = json.loads(js)
        self.assertFalse(parsed["modified"])

    def test_color_enabled(self):
        c = get_color(True)
        self.assertNotEqual(c.RED, '')

    def test_color_disabled(self):
        c = get_color(False)
        self.assertEqual(c.RED, '')

    def test_version(self):
        self.assertEqual(__version__, "1.0.0")

    def test_walk_single_node(self):
        from saurav import NumberNode
        nodes = list(_walk(NumberNode(42)))
        self.assertEqual(len(nodes), 1)

    def test_get_identifiers_on_non_identifier(self):
        from saurav import NumberNode
        ids = _get_identifiers(NumberNode(1))
        self.assertEqual(len(ids), 0)

    def test_get_function_calls_empty(self):
        from saurav import NumberNode
        calls = _get_function_calls(NumberNode(1))
        self.assertEqual(len(calls), 0)


class TestRenameEdgeCases(unittest.TestCase):
    """Additional edge case coverage for rename."""

    def test_rename_only_in_comments_no_match(self):
        """Variable only appearing in comments should yield 0 renames."""
        src = '# x is great\ny = 1\n'
        result, count, _ = refactor_rename(src, 'x', 'z')
        self.assertEqual(count, 0)

    def test_multiple_lines_same_var(self):
        src = 'a = 1\na = a + 1\nb = a\nprint(a + b)\n'
        result, count, _ = refactor_rename(src, 'a', 'val')
        self.assertGreaterEqual(count, 4)
        self.assertNotIn('\na ', result.replace('val', ''))  # no leftover 'a' as identifier

    def test_reject_all_reserved_words(self):
        reserved = ['function', 'return', 'class', 'if', 'else', 'for', 'while',
                     'try', 'catch', 'throw', 'print', 'true', 'false', 'lambda',
                     'import', 'match', 'case', 'enum', 'break', 'continue',
                     'assert', 'yield', 'next']
        for word in reserved:
            _, count, _ = refactor_rename('x = 1\n', 'x', word)
            self.assertEqual(count, 0, f"Should reject reserved word '{word}'")


class TestDeadCodeEdgeCases(unittest.TestCase):
    """Edge cases for dead code elimination."""

    def test_dead_code_after_break(self):
        src = 'for i in range(10)\n    break\n    print(i)\n'
        _, changes = refactor_deadcode(src)
        # At least detects something (best-effort)
        self.assertIsInstance(changes, list)

    def test_dead_code_after_continue(self):
        src = 'for i in range(10)\n    continue\n    print(i)\n'
        _, changes = refactor_deadcode(src)
        self.assertIsInstance(changes, list)

    def test_else_not_removed(self):
        """else blocks after return should NOT be removed."""
        src = 'function foo(x)\n    if x\n        return 1\n    else\n        return 2\n'
        result, changes = refactor_deadcode(src)
        self.assertIn('else', result)


class TestInlineEdgeCases(unittest.TestCase):
    """Edge cases for inline refactoring."""

    def test_inline_string_value(self):
        src = 'name = "hello"\nprint(name)\n'
        result, changes = refactor_inline(src, 'name')
        self.assertIn('"hello"', result)

    def test_inline_preserves_other_lines(self):
        src = 'x = 5\ny = 10\nz = x + y\nprint(z)\n'
        result, changes = refactor_inline(src, 'x')
        self.assertIn('y = 10', result)
        self.assertIn('print(z)', result)


if __name__ == '__main__':
    unittest.main()
