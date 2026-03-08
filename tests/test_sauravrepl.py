"""Tests for sauravrepl.py — the sauravcode REPL."""

import os
import sys
import io
import unittest
from unittest.mock import patch, MagicMock

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Ensure we're in the repo root for imports
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sauravrepl import (
    SauravRepl, _starts_block, _is_continuation,
    _format_value, _KEYWORDS, _Completer,
)


class TestBlockDetection(unittest.TestCase):
    """Test multi-line block detection."""

    def test_fn_starts_block(self):
        self.assertTrue(_starts_block("fn add x y"))

    def test_if_starts_block(self):
        self.assertTrue(_starts_block("if x > 5"))

    def test_while_starts_block(self):
        self.assertTrue(_starts_block("while true"))

    def test_for_starts_block(self):
        self.assertTrue(_starts_block("for i in range 10"))

    def test_match_starts_block(self):
        self.assertTrue(_starts_block("match x"))

    def test_try_starts_block(self):
        self.assertTrue(_starts_block("try"))

    def test_enum_starts_block(self):
        self.assertTrue(_starts_block("enum Color"))

    def test_assignment_not_block(self):
        self.assertFalse(_starts_block("x = 5"))

    def test_print_not_block(self):
        self.assertFalse(_starts_block("print 42"))

    def test_empty_not_block(self):
        self.assertFalse(_starts_block(""))

    def test_comment_not_block(self):
        self.assertFalse(_starts_block("# fn fake"))

    def test_elif_is_continuation(self):
        self.assertTrue(_is_continuation("elif x > 0"))

    def test_else_is_continuation(self):
        self.assertTrue(_is_continuation("else"))

    def test_catch_is_continuation(self):
        self.assertTrue(_is_continuation("catch e"))

    def test_regular_not_continuation(self):
        self.assertFalse(_is_continuation("x = 5"))

    def test_empty_not_continuation(self):
        self.assertFalse(_is_continuation(""))


class TestFormatValue(unittest.TestCase):
    """Test value formatting."""

    def test_string(self):
        self.assertEqual(_format_value("hello"), "'hello'")

    def test_integer(self):
        self.assertEqual(_format_value(42), "42")

    def test_float(self):
        self.assertEqual(_format_value(3.14), "3.14")

    def test_list(self):
        result = _format_value([1, 2, 3])
        self.assertIn("1", result)
        self.assertIn("3", result)

    def test_bool(self):
        self.assertEqual(_format_value(True), "True")

    def test_none(self):
        self.assertEqual(_format_value(None), "None")

    def test_truncation(self):
        long_str = "x" * 300
        result = _format_value(long_str, max_len=50)
        self.assertTrue(result.endswith("..."))
        self.assertTrue(len(result) <= 55)  # some slack for quotes


class TestCompleter(unittest.TestCase):
    """Test tab completion."""

    def setUp(self):
        from saurav import Interpreter
        self.interp = Interpreter()
        self.completer = _Completer(self.interp)

    def test_keyword_completion(self):
        result = self.completer.complete("pri", 0)
        self.assertEqual(result, "print")

    def test_variable_completion(self):
        self.interp.variables["myvar"] = 42
        result = self.completer.complete("myv", 0)
        self.assertEqual(result, "myvar")

    def test_command_completion(self):
        result = self.completer.complete(".he", 0)
        self.assertEqual(result, ".help")

    def test_no_match(self):
        result = self.completer.complete("zzzzzzz", 0)
        self.assertIsNone(result)

    def test_multiple_matches(self):
        # "for" and "float" and "filter" and "floor" all start with "f"
        first = self.completer.complete("f", 0)
        self.assertIsNotNone(first)
        # Should have at least 2 matches
        second = self.completer.complete("f", 1)
        self.assertIsNotNone(second)

    def test_state_exhaustion(self):
        # Eventually returns None
        i = 0
        while self.completer.complete("fn", i) is not None:
            i += 1
        self.assertIsNone(self.completer.complete("fn", i))


class TestReplExecution(unittest.TestCase):
    """Test the REPL's execute method."""

    def setUp(self):
        self.repl = SauravRepl(use_color=False)

    def test_simple_assignment(self):
        self.repl._execute("x = 42")
        self.assertEqual(self.repl.interpreter.variables["x"], 42)

    def test_expression_auto_print(self):
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            self.repl._execute("5 + 3")
            output = mock_out.getvalue()
            self.assertIn("8", output)

    def test_string_expression(self):
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            self.repl._execute('"hello"')
            output = mock_out.getvalue()
            self.assertIn("hello", output)

    def test_variable_persists(self):
        self.repl._execute("name = \"Alice\"")
        self.repl._execute("age = 30")
        self.assertEqual(self.repl.interpreter.variables["name"], "Alice")
        self.assertEqual(self.repl.interpreter.variables["age"], 30)

    def test_function_definition(self):
        self.repl._execute("function add x y\n    return x + y")
        self.assertIn("add", self.repl.interpreter.functions)

    def test_function_call(self):
        self.repl._execute("function double x\n    return x * 2")
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            self.repl._execute("double 5")
            output = mock_out.getvalue()
            self.assertIn("10", output)

    def test_syntax_error_recovery(self):
        # Should not crash — just print error
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            self.repl._execute("fn")  # incomplete
            # REPL should still be alive
            self.repl._execute("x = 99")
            self.assertEqual(self.repl.interpreter.variables["x"], 99)

    def test_runtime_error_recovery(self):
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            self.repl._execute("y + 1")  # y not defined
            # Should recover
            self.repl._execute("y = 10")
            self.assertEqual(self.repl.interpreter.variables["y"], 10)

    def test_print_statement(self):
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            self.repl._execute('print "hello world"')
            output = mock_out.getvalue()
            self.assertIn("hello world", output)

    def test_list_creation(self):
        self.repl._execute("nums = [1, 2, 3]")
        self.assertEqual(self.repl.interpreter.variables["nums"], [1, 2, 3])

    def test_empty_code_ignored(self):
        self.repl._execute("")
        self.repl._execute("   ")
        # No crash

    def test_multiline_if(self):
        code = "x = 10\nif x > 5\n    y = 100"
        self.repl._execute(code)
        self.assertEqual(self.repl.interpreter.variables.get("y"), 100)


class TestReplCommands(unittest.TestCase):
    """Test REPL dot-commands."""

    def setUp(self):
        self.repl = SauravRepl(use_color=False)

    def test_help_command(self):
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            result = self.repl._handle_command(".help")
            self.assertTrue(result)
            output = mock_out.getvalue()
            self.assertIn(".vars", output)
            self.assertIn(".fns", output)

    def test_vars_empty(self):
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            self.repl._handle_command(".vars")
            output = mock_out.getvalue()
            self.assertIn("No variables", output)

    def test_vars_with_data(self):
        self.repl._execute("x = 42")
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            self.repl._handle_command(".vars")
            output = mock_out.getvalue()
            self.assertIn("x", output)
            self.assertIn("42", output)

    def test_fns_empty(self):
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            self.repl._handle_command(".fns")
            output = mock_out.getvalue()
            self.assertIn("No user-defined", output)

    def test_fns_with_data(self):
        self.repl._execute("function greet name\n    print name")
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            self.repl._handle_command(".fns")
            output = mock_out.getvalue()
            self.assertIn("greet", output)

    def test_reset_command(self):
        self.repl._execute("x = 42")
        self.repl._handle_command(".reset")
        self.assertNotIn("x", self.repl.interpreter.variables)

    def test_ast_command(self):
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            self.repl._handle_command(".ast x = 5")
            output = mock_out.getvalue()
            self.assertIn("Assignment", output)

    def test_ast_no_arg(self):
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            self.repl._handle_command(".ast")
            output = mock_out.getvalue()
            self.assertIn("Usage", output)

    def test_time_toggle(self):
        self.assertFalse(self.repl._show_timing)
        self.repl._handle_command(".time")
        self.assertTrue(self.repl._show_timing)
        self.repl._handle_command(".time")
        self.assertFalse(self.repl._show_timing)

    def test_time_with_code(self):
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            self.repl._handle_command(".time 5 + 3")
            output = mock_out.getvalue()
            self.assertIn("8", output)
            self.assertIn("ms", output)

    def test_load_missing_file(self):
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            self.repl._handle_command(".load nonexistent.srv")
            output = mock_out.getvalue()
            self.assertIn("not found", output)

    def test_load_no_arg(self):
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            self.repl._handle_command(".load")
            output = mock_out.getvalue()
            self.assertIn("Usage", output)

    def test_save_no_arg(self):
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            self.repl._handle_command(".save")
            output = mock_out.getvalue()
            self.assertIn("Usage", output)

    def test_exit_command(self):
        with self.assertRaises(SystemExit):
            self.repl._handle_command(".exit")

    def test_quit_command(self):
        with self.assertRaises(SystemExit):
            self.repl._handle_command(".quit")

    def test_unknown_command_falls_through(self):
        result = self.repl._handle_command(".unknown")
        self.assertFalse(result)


class TestReplEval(unittest.TestCase):
    """Test the -e (eval) mode."""

    def test_eval_expression(self):
        repl = SauravRepl(use_color=False)
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            repl._execute("3 * 7")
            output = mock_out.getvalue()
            self.assertIn("21", output)

    def test_eval_multiple_lines(self):
        repl = SauravRepl(use_color=False)
        repl._execute("x = 10")
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            repl._execute("x + 5")
            output = mock_out.getvalue()
            self.assertIn("15", output)


class TestKeywords(unittest.TestCase):
    """Test that keyword list is populated."""

    def test_keywords_not_empty(self):
        self.assertTrue(len(_KEYWORDS) > 20)

    def test_core_keywords_present(self):
        for kw in ["fn", "if", "while", "for", "print", "return"]:
            self.assertIn(kw, _KEYWORDS)


class TestSaveLoad(unittest.TestCase):
    """Test file save/load."""

    def setUp(self):
        self.repl = SauravRepl(use_color=False)
        self.test_file = "_test_repl_save.srv"

    def tearDown(self):
        if os.path.exists(self.test_file):
            os.remove(self.test_file)

    def test_save_and_load(self):
        self.repl.history = ['x = 42', 'print x']
        with patch("sys.stdout", new_callable=io.StringIO):
            self.repl._handle_command(".save " + self.test_file)

        self.assertTrue(os.path.exists(self.test_file))
        with open(self.test_file) as f:
            content = f.read()
        self.assertIn("x = 42", content)

    def test_load_real_file(self):
        with open(self.test_file, "w") as f:
            f.write("z = 999\n")
        with patch("sys.stdout", new_callable=io.StringIO):
            self.repl._handle_command(".load " + self.test_file)
        self.assertEqual(self.repl.interpreter.variables.get("z"), 999)


if __name__ == "__main__":
    unittest.main()
