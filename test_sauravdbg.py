#!/usr/bin/env python3
"""Tests for sauravdbg — Sauravcode debugger."""

import sys
import os
import unittest
from unittest.mock import patch
from io import StringIO

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sauravdbg import (
    Breakpoint, DebugInterpreter, annotate_line_numbers,
    _format_value, _infer_line, RestartSignal
)
from saurav import tokenize, Parser, ASTNode


class TestBreakpoint(unittest.TestCase):
    def test_basic_breakpoint(self):
        bp = Breakpoint(10)
        self.assertEqual(bp.line, 10)
        self.assertIsNone(bp.condition)
        self.assertEqual(bp.hit_count, 0)
        self.assertTrue(bp.enabled)

    def test_conditional_breakpoint(self):
        bp = Breakpoint(5, condition="x > 3")
        self.assertEqual(bp.condition, "x > 3")

    def test_repr(self):
        bp = Breakpoint(10)
        self.assertIn("line=10", repr(bp))
        bp.hit_count = 3
        self.assertIn("hits=3", repr(bp))

    def test_conditional_repr(self):
        bp = Breakpoint(5, condition="x > 3")
        self.assertIn("if x > 3", repr(bp))


class TestFormatValue(unittest.TestCase):
    def test_string(self):
        self.assertEqual(_format_value("hello"), "'hello'")

    def test_number(self):
        self.assertEqual(_format_value(42), "42")

    def test_short_list(self):
        self.assertIn("[1, 2, 3]", _format_value([1, 2, 3]))

    def test_long_list_truncated(self):
        val = list(range(20))
        result = _format_value(val)
        self.assertIn("20 items", result)
        self.assertIn("...", result)

    def test_short_dict(self):
        self.assertIn("'a': 1", _format_value({"a": 1}))

    def test_long_dict_truncated(self):
        val = {f"k{i}": i for i in range(10)}
        result = _format_value(val)
        self.assertIn("10 keys", result)

    def test_max_length_truncation(self):
        result = _format_value("x" * 200, max_len=30)
        self.assertLessEqual(len(result), 30)
        self.assertTrue(result.endswith("..."))


class TestDebugInterpreter(unittest.TestCase):
    def _make_interp(self, source):
        lines = source.split('\n')
        return DebugInterpreter(lines), lines

    def test_init_defaults(self):
        interp, _ = self._make_interp("x = 1")
        self.assertTrue(interp.stepping)
        self.assertFalse(interp.step_over)
        self.assertEqual(interp.call_stack, [])
        self.assertEqual(interp.breakpoints, {})
        self.assertEqual(interp.watchlist, set())

    def test_breakpoint_management(self):
        interp, _ = self._make_interp("x = 1\ny = 2\nz = 3")
        interp.breakpoints[2] = Breakpoint(2)
        self.assertIn(2, interp.breakpoints)
        del interp.breakpoints[2]
        self.assertNotIn(2, interp.breakpoints)

    def test_eval_condition_true(self):
        interp, _ = self._make_interp("")
        interp.variables['x'] = 10
        self.assertTrue(interp._eval_condition("x > 5"))

    def test_eval_condition_false(self):
        interp, _ = self._make_interp("")
        interp.variables['x'] = 2
        self.assertFalse(interp._eval_condition("x > 5"))

    def test_eval_condition_error(self):
        interp, _ = self._make_interp("")
        self.assertFalse(interp._eval_condition("undefined_var > 5"))

    def test_run_simple_program_with_continue(self):
        """Test that a simple program runs to completion in continue mode."""
        source = "x = 42\nprint x"
        interp, lines = self._make_interp(source)
        interp.stepping = False  # Don't stop

        tokens = tokenize(source)
        parser = Parser(tokens)
        ast = parser.parse()
        annotate_line_numbers(ast, lines)

        out = StringIO()
        with patch('sys.stdout', out):
            for node in ast:
                interp.interpret(node)

        self.assertEqual(interp.variables.get('x'), 42)
        self.assertIn("42", out.getvalue())

    def test_breakpoint_hit_count(self):
        """Verify breakpoint hit count increments."""
        bp = Breakpoint(1)
        bp.hit_count += 1
        bp.hit_count += 1
        self.assertEqual(bp.hit_count, 2)

    def test_watchlist(self):
        interp, _ = self._make_interp("")
        interp.watchlist.add('x')
        interp.watchlist.add('y')
        self.assertEqual(len(interp.watchlist), 2)
        interp.watchlist.discard('x')
        self.assertEqual(len(interp.watchlist), 1)

    def test_show_source_line(self):
        source = "x = 1\ny = 2\nz = 3"
        interp, _ = self._make_interp(source)
        out = StringIO()
        with patch('sys.stdout', out):
            interp._show_source_line(2)
        output = out.getvalue()
        self.assertIn("y = 2", output)

    def test_show_context(self):
        source = "\n".join(f"line{i} = {i}" for i in range(1, 11))
        interp, _ = self._make_interp(source)
        out = StringIO()
        with patch('sys.stdout', out):
            interp._show_context(5, radius=2)
        output = out.getvalue()
        self.assertIn("line3", output)
        self.assertIn("line5", output)
        self.assertIn("line7", output)

    def test_cmd_vars(self):
        interp, _ = self._make_interp("")
        interp.variables['a'] = 1
        interp.variables['b'] = "hello"
        out = StringIO()
        with patch('sys.stdout', out):
            interp._cmd_vars()
        output = out.getvalue()
        self.assertIn("a", output)
        self.assertIn("b", output)

    def test_cmd_vars_empty(self):
        interp, _ = self._make_interp("")
        out = StringIO()
        with patch('sys.stdout', out):
            interp._cmd_vars()
        self.assertIn("no variables", out.getvalue())

    def test_cmd_stack_empty(self):
        interp, _ = self._make_interp("")
        out = StringIO()
        with patch('sys.stdout', out):
            interp._cmd_stack()
        self.assertIn("top-level", out.getvalue())

    def test_cmd_stack_with_entries(self):
        interp, _ = self._make_interp("")
        interp.call_stack.append(("foo", 5))
        interp.call_stack.append(("bar", 10))
        out = StringIO()
        with patch('sys.stdout', out):
            interp._cmd_stack()
        output = out.getvalue()
        self.assertIn("foo", output)
        self.assertIn("bar", output)

    def test_cmd_print_variable(self):
        interp, _ = self._make_interp("")
        interp.variables['x'] = 42
        out = StringIO()
        with patch('sys.stdout', out):
            interp._cmd_print("x")
        self.assertIn("42", out.getvalue())

    def test_cmd_print_unknown(self):
        interp, _ = self._make_interp("")
        out = StringIO()
        with patch('sys.stdout', out):
            interp._cmd_print("nonexistent")
        self.assertIn("Cannot evaluate", out.getvalue())

    def test_cmd_list_breakpoints_empty(self):
        interp, _ = self._make_interp("")
        out = StringIO()
        with patch('sys.stdout', out):
            interp._cmd_list_breakpoints()
        self.assertIn("No breakpoints", out.getvalue())

    def test_cmd_list_breakpoints(self):
        interp, _ = self._make_interp("a = 1\nb = 2\nc = 3")
        interp.breakpoints[2] = Breakpoint(2, condition="x > 0")
        out = StringIO()
        with patch('sys.stdout', out):
            interp._cmd_list_breakpoints()
        output = out.getvalue()
        self.assertIn("Line 2", output)
        self.assertIn("if x > 0", output)


class TestAnnotateLineNumbers(unittest.TestCase):
    def test_simple_assignment(self):
        source = "x = 42"
        tokens = tokenize(source)
        parser = Parser(tokens)
        ast = parser.parse()
        annotate_line_numbers(ast, source.split('\n'))
        self.assertIsNotNone(ast[0].line_num)

    def test_function_body(self):
        source = "function add a b\n    return a + b"
        tokens = tokenize(source)
        parser = Parser(tokens)
        ast = parser.parse()
        annotate_line_numbers(ast, source.split('\n'))
        # Function node should have a line number
        self.assertIsNotNone(ast[0].line_num)

    def test_multiline(self):
        source = "x = 1\ny = 2\nz = 3"
        tokens = tokenize(source)
        parser = Parser(tokens)
        ast = parser.parse()
        annotate_line_numbers(ast, source.split('\n'))
        # Each node should have a line number
        for node in ast:
            self.assertIsNotNone(node.line_num)


class TestRestartSignal(unittest.TestCase):
    def test_is_exception(self):
        with self.assertRaises(RestartSignal):
            raise RestartSignal()


if __name__ == '__main__':
    unittest.main()
