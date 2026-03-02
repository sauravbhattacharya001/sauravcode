"""Comprehensive feature tests for SauravCode — builtins with inline list arguments,
dictionary operations, string operations, control flow, error handling, and more.

Tests the parser fix for builtins like sort/reverse/join/contains with inline
list literal arguments (previously misparse as indexing — Fixes #18).
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from saurav import tokenize, Parser, Interpreter
import io
from contextlib import redirect_stdout


def run(code):
    """Helper to run SauravCode and capture output."""
    tokens = tokenize(code)
    parser = Parser(tokens)
    ast = parser.parse()
    interp = Interpreter()
    buf = io.StringIO()
    with redirect_stdout(buf):
        for node in ast:
            interp.interpret(node)
    return buf.getvalue().strip()


# ── Builtins with inline list arguments (Fixes #18) ──────────────

class TestBuiltinsWithInlineList:
    """Builtin functions must accept inline list literals as arguments."""

    def test_sort_inline_numbers(self):
        assert run('print sort [3, 1, 2]') == "[1, 2, 3]"

    def test_sort_inline_strings(self):
        assert run('print sort ["c", "a", "b"]') == '["a", "b", "c"]'

    def test_sort_with_variable(self):
        assert run('a = [3, 1, 2]\nprint sort a') == "[1, 2, 3]"

    def test_reverse_inline(self):
        assert run('print reverse [1, 2, 3]') == "[3, 2, 1]"

    def test_reverse_variable(self):
        assert run('a = [1, 2, 3]\nprint reverse a') == "[3, 2, 1]"

    def test_contains_inline_list(self):
        assert run('print contains [1, 2, 3] 2') == "true"

    def test_contains_inline_list_false(self):
        assert run('print contains [1, 2, 3] 5') == "false"

    def test_join_inline_list(self):
        assert run('print join ", " ["a", "b", "c"]') == "a, b, c"

    def test_map_inline_list(self):
        assert run('print map (lambda x -> x * 2) [1, 2, 3]') == "[2, 4, 6]"

    def test_filter_inline_list(self):
        assert run('print filter (lambda x -> x > 2) [1, 2, 3, 4]') == "[3, 4]"

    def test_reduce_inline_list(self):
        assert run('print reduce (lambda a x -> a + x) [1, 2, 3] 0') == "6"

    def test_keys_inline_dict(self):
        assert run('print keys {"a": 1, "b": 2}') == '["a", "b"]'

    def test_values_inline_dict(self):
        assert run('print values {"x": 10}') == '[10]'


# ── Variable indexing still works ─────────────────────────────────

class TestIndexingNotBroken:
    """Ensure variable[index] still works after the builtin-list fix."""

    def test_list_index(self):
        assert run('a = [10, 20, 30]\nprint a[1]') == "20"

    def test_string_index(self):
        assert run('s = "hello"\nprint s[0]') == "h"

    def test_dict_index(self):
        assert run('d = {"a": 1}\nprint d["a"]') == "1"

    def test_nested_list_index(self):
        assert run('a = [[1, 2], [3, 4]]\nprint a[1][0]') == "3"

    def test_negative_index(self):
        assert run('a = [10, 20, 30]\nprint a[-1]') == "30"

    def test_string_negative_index(self):
        assert run('s = "hello"\nprint s[-1]') == "o"


# ── Nested data structures ───────────────────────────────────────

class TestNestedStructures:
    def test_nested_dict_read(self):
        assert run('d = {"a": {"b": 42}}\nprint d["a"]["b"]') == "42"

    def test_dict_with_list_value(self):
        assert run('d = {"x": [10, 20, 30]}\nprint d["x"][1]') == "20"

    def test_list_of_dicts(self):
        assert run('items = [{"n": 1}, {"n": 2}]\nprint items[1]["n"]') == "2"

    def test_dict_int_keys(self):
        assert run('d = {1: "one", 2: "two"}\nprint d[1]') == "one"

    def test_empty_dict(self):
        assert run('d = {}\nprint d') == "{}"


# ── String builtins ──────────────────────────────────────────────

class TestStringBuiltins:
    def test_upper(self):
        assert run('print upper "hello"') == "HELLO"

    def test_lower(self):
        assert run('print lower "HELLO"') == "hello"

    def test_trim(self):
        assert run('print trim "  hello  "') == "hello"

    def test_replace(self):
        assert run('print replace "hello world" "world" "earth"') == "hello earth"

    def test_split(self):
        assert run('parts = split "a,b,c" ","\nprint parts[1]') == "b"

    def test_contains_string(self):
        assert run('print contains "hello" "ell"') == "true"

    def test_starts_with(self):
        assert run('print starts_with "hello" "hel"') == "true"

    def test_ends_with(self):
        assert run('print ends_with "hello" "llo"') == "true"

    def test_substring(self):
        assert run('print substring "hello" 1 3') == "el"

    def test_index_of(self):
        assert run('print index_of "hello" "ll"') == "2"

    def test_char_at(self):
        assert run('print char_at "hello" 1') == "e"

    def test_join(self):
        assert run('print join "-" ["a", "b", "c"]') == "a-b-c"

    def test_to_string(self):
        assert run('print to_string 42') == "42"

    def test_string_concat_with_number(self):
        assert run('print "value: " + (to_string 42)') == "value: 42"


# ── Type builtins ────────────────────────────────────────────────

class TestTypeBuiltins:
    def test_type_of_number(self):
        assert run('print type_of 42') == "number"

    def test_type_of_string(self):
        assert run('print type_of "hello"') == "string"

    def test_type_of_bool(self):
        assert run('print type_of true') == "bool"

    def test_type_of_list(self):
        assert run('print type_of [1, 2]') == "list"

    def test_type_of_dict(self):
        assert run('print type_of {"a": 1}') == "map"

    def test_to_number(self):
        assert run('print to_number "42"') == "42"


# ── Math builtins ────────────────────────────────────────────────

class TestMathBuiltins:
    def test_abs_negative(self):
        assert run('x = -5\nprint abs x') == "5"

    def test_sqrt(self):
        assert run('print sqrt 9') == "3"

    def test_power(self):
        assert run('print power 2 10') == "1024"

    def test_round(self):
        assert run('print round 3.7') == "4"

    def test_floor(self):
        assert run('print floor 3.7') == "3"

    def test_ceil(self):
        assert run('print ceil 3.2') == "4"

    def test_modulo(self):
        assert run('print 10 % 3') == "1"


# ── Dict builtins ────────────────────────────────────────────────

class TestDictBuiltins:
    def test_keys(self):
        code = 'd = {"a": 1, "b": 2}\nk = keys d\nprint len k'
        assert run(code) == "2"

    def test_values(self):
        code = 'd = {"a": 10, "b": 20}\nvals = values d\nprint len vals'
        assert run(code) == "2"

    def test_has_key_true(self):
        assert run('print has_key {"a": 1} "a"') == "true"

    def test_has_key_false(self):
        assert run('print has_key {"a": 1} "z"') == "false"

    def test_dict_update(self):
        assert run('d = {"a": 1}\nd["a"] = 99\nprint d["a"]') == "99"


# ── Control flow ─────────────────────────────────────────────────

class TestControlFlow:
    def test_while_break(self):
        code = 'i = 0\nwhile i < 100\n    if i == 5\n        break\n    i = i + 1\nprint i'
        assert run(code) == "5"

    def test_for_range(self):
        code = 'total = 0\nfor i 0 5\n    total = total + i\nprint total'
        assert run(code) == "10"

    def test_for_in(self):
        code = 'items = [10, 20, 30]\ntotal = 0\nfor item in items\n    total = total + item\nprint total'
        assert run(code) == "60"

    def test_while_false_never_executes(self):
        assert run('x = 0\nwhile false\n    x = 1\nprint x') == "0"

    def test_ternary_true(self):
        assert run('x = 5 if true else 10\nprint x') == "5"

    def test_ternary_false(self):
        assert run('x = 5 if false else 10\nprint x') == "10"

    def test_ternary_with_condition(self):
        assert run('x = 5\nresult = "big" if x > 3 else "small"\nprint result') == "big"


# ── Functions ────────────────────────────────────────────────────

class TestFunctions:
    def test_recursive_fibonacci(self):
        code = 'function fib n\n    if n <= 1\n        return n\n    return (fib (n - 1)) + (fib (n - 2))\n\nprint fib 10'
        assert run(code) == "55"

    def test_function_with_string_arg(self):
        code = 'function greet name\n    return "Hello " + name\n\nprint greet "World"'
        assert run(code) == "Hello World"

    def test_closure_captures_variable(self):
        code = 'x = 10\nfunction add_x n\n    return n + x\n\nprint add_x 5'
        assert run(code) == "15"


# ── Comparisons ──────────────────────────────────────────────────

class TestComparisons:
    def test_equal(self):
        assert run('print 5 == 5') == "true"

    def test_not_equal(self):
        assert run('print 5 != 3') == "true"

    def test_less_than(self):
        assert run('print 3 < 5') == "true"

    def test_greater_than(self):
        assert run('print 5 > 3') == "true"

    def test_string_equality(self):
        assert run('print "hello" == "hello"') == "true"


# ── Logical operators ────────────────────────────────────────────

class TestLogicalOps:
    def test_and_true(self):
        assert run('print true and true') == "true"

    def test_and_false(self):
        assert run('print true and false') == "false"

    def test_or_true(self):
        assert run('print false or true') == "true"

    def test_not_true(self):
        assert run('print not true') == "false"


# ── Error handling ───────────────────────────────────────────────

class TestErrorHandling:
    def test_try_catch(self):
        code = 'try\n    x = 1 / 0\ncatch e\n    print "caught"'
        assert run(code) == "caught"


# ── List comprehension ───────────────────────────────────────────

class TestListComprehension:
    def test_basic(self):
        assert run('result = [x * 2 for x in [1, 2, 3]]\nprint result') == "[2, 4, 6]"

    def test_with_filter(self):
        assert run('result = [x for x in [1, 2, 3, 4, 5] if x > 3]\nprint result') == "[4, 5]"

    def test_with_transform_and_filter(self):
        assert run('result = [x * x for x in [1, 2, 3, 4, 5] if x % 2 == 0]\nprint result') == "[4, 16]"


# ── F-strings ────────────────────────────────────────────────────

class TestFStrings:
    def test_basic_fstring(self):
        assert run('x = 42\nprint f"value is {x}"') == "value is 42"

    def test_fstring_with_expression(self):
        assert run('x = 3\nprint f"{x} * 2 = {x * 2}"') == "3 * 2 = 6"
