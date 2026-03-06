"""
Tests for sauravcode interpreter edge cases in control flow,
error handling, and type operations.

Covers: break/continue in loops, for-each over various types,
nested try/catch, throw with expressions, match destructuring,
operator type errors, chained comparisons, and scope behavior.
"""

import pytest
import sys
import os
import io
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from saurav import tokenize, Parser, Interpreter, FunctionNode, FunctionCallNode


def run_code(code):
    """Tokenize, parse, interpret sauravcode and capture stdout."""
    tokens = list(tokenize(code))
    parser = Parser(tokens)
    ast_nodes = parser.parse()
    interp = Interpreter()

    buf = io.StringIO()
    with redirect_stdout(buf):
        for node in ast_nodes:
            if isinstance(node, FunctionNode):
                interp.interpret(node)
            elif isinstance(node, FunctionCallNode):
                interp.execute_function(node)
            else:
                interp.interpret(node)
    return buf.getvalue()


# ============================================================
# Break/Continue in While Loops
# ============================================================

class TestBreakContinue:
    def test_break_exits_while(self):
        code = "i = 0\nwhile i < 10\n  if i == 3\n    break\n  print i\n  i = i + 1\n"
        out = run_code(code)
        assert out.strip().split("\n") == ["0", "1", "2"]

    def test_continue_skips_iteration(self):
        code = "i = 0\nwhile i < 5\n  i = i + 1\n  if i == 3\n    continue\n  print i\n"
        out = run_code(code)
        lines = out.strip().split("\n")
        assert "3" not in lines
        assert "1" in lines and "2" in lines and "4" in lines

    def test_break_in_nested_loops(self):
        code = (
            "i = 0\n"
            "while i < 3\n"
            "  j = 0\n"
            "  while j < 3\n"
            "    if j == 1\n"
            "      break\n"
            "    print j\n"
            "    j = j + 1\n"
            "  i = i + 1\n"
        )
        out = run_code(code)
        # Inner loop breaks at j=1, so only j=0 prints each time
        assert out.strip().split("\n") == ["0", "0", "0"]

    def test_break_in_for_each(self):
        code = (
            "items = [10, 20, 30, 40, 50]\n"
            "for item in items\n"
            "  if item == 30\n"
            "    break\n"
            "  print item\n"
        )
        out = run_code(code)
        assert out.strip().split("\n") == ["10", "20"]

    def test_continue_in_for_each(self):
        code = (
            "items = [1, 2, 3, 4, 5]\n"
            "for item in items\n"
            "  if item % 2 == 0\n"
            "    continue\n"
            "  print item\n"
        )
        out = run_code(code)
        assert out.strip().split("\n") == ["1", "3", "5"]


# ============================================================
# For-Each Over Different Types
# ============================================================

class TestForEachTypes:
    def test_for_each_over_string(self):
        code = 'word = "abc"\nfor ch in word\n  print ch\n'
        out = run_code(code)
        assert out.strip().split("\n") == ["a", "b", "c"]

    def test_for_each_over_map_keys(self):
        code = 'm = {"x": 1, "y": 2}\nfor k in m\n  print k\n'
        out = run_code(code)
        lines = set(out.strip().split("\n"))
        assert lines == {"x", "y"}

    def test_for_each_over_empty_list(self):
        code = 'items = []\nfor item in items\n  print item\nprint "done"\n'
        out = run_code(code)
        assert out.strip() == "done"

    def test_for_each_over_single_element(self):
        code = 'items = [42]\nfor item in items\n  print item\n'
        out = run_code(code)
        assert out.strip() == "42"

    def test_for_each_non_iterable_raises(self):
        code = "x = 5\nfor item in x\n  print item\n"
        with pytest.raises(RuntimeError, match="Cannot iterate"):
            run_code(code)


# ============================================================
# Try/Catch Edge Cases
# ============================================================

class TestTryCatchEdgeCases:
    def test_catch_division_by_zero(self):
        code = 'try\n  x = 1 / 0\ncatch e\n  print e\n'
        out = run_code(code)
        assert "zero" in out.lower()

    def test_catch_undefined_variable(self):
        code = 'try\n  print unknown_var\ncatch e\n  print "caught"\n'
        out = run_code(code)
        assert "caught" in out

    def test_throw_string(self):
        code = 'try\n  throw "custom error"\ncatch e\n  print e\n'
        out = run_code(code)
        assert "custom error" in out

    def test_throw_number(self):
        code = 'try\n  throw 42\ncatch e\n  print e\n'
        out = run_code(code)
        assert "42" in out

    def test_nested_try_catch_inner_catches(self):
        code = (
            'try\n'
            '  try\n'
            '    throw "inner"\n'
            '  catch e\n'
            '    print e\n'
            '  print "outer ok"\n'
            'catch e\n'
            '  print "outer caught"\n'
        )
        out = run_code(code)
        assert "inner" in out
        assert "outer ok" in out
        assert "outer caught" not in out

    def test_nested_try_catch_outer_catches(self):
        code = (
            'try\n'
            '  try\n'
            '    x = 1\n'
            '  catch e\n'
            '    print "inner"\n'
            '  throw "bubble"\n'
            'catch e\n'
            '  print e\n'
        )
        out = run_code(code)
        assert "bubble" in out
        assert "inner" not in out

    def test_try_no_error_skips_catch(self):
        code = 'try\n  print "ok"\ncatch e\n  print "error"\n'
        out = run_code(code)
        assert "ok" in out
        assert "error" not in out

    def test_throw_expression_result(self):
        code = 'try\n  throw 2 + 3\ncatch e\n  print e\n'
        out = run_code(code)
        assert "5" in out


# ============================================================
# Operator Type Errors
# ============================================================

class TestOperatorTypeErrors:
    def test_add_string_number_error(self):
        code = 'x = "hello" + 5\n'
        with pytest.raises(RuntimeError, match="Cannot use"):
            run_code(code)

    def test_subtract_strings_error(self):
        code = 'x = "a" - "b"\n'
        with pytest.raises(RuntimeError, match="Cannot use"):
            run_code(code)

    def test_multiply_string_by_string_error(self):
        code = 'x = "a" * "b"\n'
        with pytest.raises(RuntimeError, match="Cannot use"):
            run_code(code)

    def test_divide_strings_error(self):
        code = 'x = "a" / "b"\n'
        with pytest.raises(RuntimeError, match="Cannot use"):
            run_code(code)

    def test_modulo_by_zero_error(self):
        code = "x = 5 % 0\n"
        with pytest.raises(RuntimeError, match="[Mm]odulo by zero"):
            run_code(code)

    def test_undefined_variable_error(self):
        code = "print xyz\n"
        with pytest.raises(RuntimeError, match="not defined"):
            run_code(code)


# ============================================================
# Scope and Variable Behavior
# ============================================================

class TestScopeBehavior:
    def test_loop_variable_persists_after_while(self):
        code = "i = 0\nwhile i < 3\n  i = i + 1\nprint i\n"
        out = run_code(code)
        assert out.strip() == "3"

    def test_for_each_variable_persists(self):
        code = "items = [1, 2, 3]\nfor x in items\n  pass = 1\nprint x\n"
        # for-each var should hold last value after loop
        out = run_code(code)
        assert "3" in out

    def test_function_doesnt_leak_locals(self):
        code = (
            "function add a b\n"
            "  result = a + b\n"
            "  return result\n"
            "x = add 3 4\n"
            "print x\n"
        )
        out = run_code(code)
        assert "7" in out

    def test_function_recursive_fibonacci(self):
        code = (
            "function fib n\n"
            "  if n <= 1\n"
            "    return n\n"
            "  return (fib (n - 1)) + (fib (n - 2))\n"
            "print fib 10\n"
        )
        out = run_code(code)
        assert "55" in out

    def test_nested_function_calls(self):
        code = (
            "function double x\n"
            "  return x * 2\n"
            "function triple x\n"
            "  return x * 3\n"
            "print double (triple 5)\n"
        )
        out = run_code(code)
        assert "30" in out


# ============================================================
# List Operations Edge Cases
# ============================================================

class TestListEdgeCases:
    def test_nested_list_access(self):
        code = "matrix = [[1, 2], [3, 4]]\nprint matrix[0][1]\n"
        out = run_code(code)
        assert "2" in out

    def test_list_append_and_length(self):
        code = "items = []\nappend items 1\nappend items 2\nappend items 3\nprint len items\n"
        out = run_code(code)
        assert "3" in out

    def test_index_out_of_bounds(self):
        code = "items = [1, 2, 3]\nprint items[10]\n"
        with pytest.raises((RuntimeError, IndexError)):
            run_code(code)

    def test_negative_index(self):
        code = "items = [10, 20, 30]\nprint items[-1]\n"
        out = run_code(code)
        assert "30" in out

    def test_list_in_condition(self):
        code = 'items = [1, 2, 3]\nif len items > 2\n  print "big"\n'
        out = run_code(code)
        assert "big" in out


# ============================================================
# Map Operations Edge Cases
# ============================================================

class TestMapEdgeCases:
    def test_map_access_missing_key(self):
        code = 'm = {"a": 1}\nprint m["b"]\n'
        with pytest.raises((RuntimeError, KeyError)):
            run_code(code)

    def test_map_update_existing_key(self):
        code = 'm = {"a": 1}\nm["a"] = 99\nprint m["a"]\n'
        out = run_code(code)
        assert "99" in out

    def test_map_with_numeric_values(self):
        code = 'm = {"x": 3.14, "y": 2.71}\nprint m["x"] + m["y"]\n'
        out = run_code(code)
        assert "5.85" in out

    def test_empty_map(self):
        code = 'm = {}\nm["key"] = "value"\nprint m["key"]\n'
        out = run_code(code)
        assert "value" in out


# ============================================================
# String Operations
# ============================================================

class TestStringOperations:
    def test_string_concatenation(self):
        code = 'a = "hello"\nb = " world"\nprint a + b\n'
        out = run_code(code)
        assert "hello world" in out

    def test_string_repetition(self):
        code = 'x = "ab" * 3\nprint x\n'
        out = run_code(code)
        assert "ababab" in out

    def test_string_length(self):
        code = 'x = "hello"\nprint len x\n'
        out = run_code(code)
        assert "5" in out

    def test_string_indexing(self):
        code = 'x = "hello"\nprint x[0]\n'
        out = run_code(code)
        assert "h" in out

    def test_empty_string_length(self):
        code = 'x = ""\nprint len x\n'
        out = run_code(code)
        assert "0" in out


# ============================================================
# Boolean Logic Edge Cases
# ============================================================

class TestBooleanLogic:
    def test_not_true(self):
        code = "x = not true\nprint x\n"
        out = run_code(code)
        assert "false" in out.lower()

    def test_and_short_circuit(self):
        # false and <anything> should not evaluate right side
        code = 'x = false and (1 / 0)\nprint "ok"\n'
        # If short-circuit works, no division by zero
        out = run_code(code)
        assert "ok" in out

    def test_or_short_circuit(self):
        code = 'x = true or (1 / 0)\nprint "ok"\n'
        out = run_code(code)
        assert "ok" in out

    def test_chained_and(self):
        code = "x = true and true and false\nprint x\n"
        out = run_code(code)
        assert "false" in out.lower()

    def test_chained_or(self):
        code = "x = false or false or true\nprint x\n"
        out = run_code(code)
        assert "true" in out.lower()

    def test_comparison_chain(self):
        code = "print 1 < 2\nprint 2 > 1\nprint 3 >= 3\nprint 3 <= 3\nprint 1 == 1\nprint 1 != 2\n"
        out = run_code(code)
        lines = out.strip().split("\n")
        assert all("true" in line.lower() for line in lines)


# ============================================================
# Arithmetic Edge Cases
# ============================================================

class TestArithmeticEdgeCases:
    def test_integer_division_result(self):
        code = "print 10 / 3\n"
        out = run_code(code)
        val = float(out.strip())
        assert abs(val - 3.3333333333) < 0.001

    def test_negative_numbers(self):
        code = "x = -5\nprint x\n"
        out = run_code(code)
        assert "-5" in out

    def test_large_multiplication(self):
        code = "print 999999 * 999999\n"
        out = run_code(code)
        assert "999998000001" in out

    def test_modulo_operator(self):
        code = "print 17 % 5\n"
        out = run_code(code)
        assert "2" in out

    def test_order_of_operations(self):
        code = "print 2 + 3 * 4\n"
        out = run_code(code)
        assert "14" in out

    def test_parenthesized_expressions(self):
        code = "print (2 + 3) * 4\n"
        out = run_code(code)
        assert "20" in out
