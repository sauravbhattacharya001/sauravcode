#!/usr/bin/env python3
"""Tests for sauravmigrate.py — Python-to-sauravcode transpiler."""

import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sauravmigrate import migrate_source


class TestBasicStatements:
    def test_assignment(self):
        result = migrate_source("x = 42")
        assert "x = 42" in result

    def test_string_assignment(self):
        result = migrate_source('name = "hello"')
        assert 'name = "hello"' in result

    def test_boolean(self):
        result = migrate_source("flag = True")
        assert "flag = true" in result

    def test_none_to_zero(self):
        result = migrate_source("x = None")
        assert "x = 0" in result

    def test_augmented_assign(self):
        result = migrate_source("x += 5")
        assert "x = x + 5" in result


class TestFunctions:
    def test_simple_function(self):
        result = migrate_source("def greet(name):\n    print(name)")
        assert "function greet name" in result
        assert "print name" in result

    def test_no_params(self):
        result = migrate_source("def hello():\n    print('hi')")
        assert "function hello" in result

    def test_return(self):
        result = migrate_source("def add(a, b):\n    return a + b")
        assert "function add a b" in result
        assert "return a + b" in result

    def test_recursive_call(self):
        src = "def fib(n):\n    return fib(n - 1) + fib(n - 2)"
        result = migrate_source(src)
        assert "(fib (n - 1))" in result
        assert "(fib (n - 2))" in result


class TestControlFlow:
    def test_if_else(self):
        src = "if x > 5:\n    print(x)\nelse:\n    print(0)"
        result = migrate_source(src)
        assert "if x > 5" in result
        assert "else" in result

    def test_elif(self):
        src = "if x > 5:\n    y = 1\nelif x > 0:\n    y = 2\nelse:\n    y = 3"
        result = migrate_source(src)
        assert "else if x > 0" in result

    def test_while(self):
        result = migrate_source("while x > 0:\n    x = x - 1")
        assert "while x > 0" in result

    def test_for_range(self):
        result = migrate_source("for i in range(10):\n    print(i)")
        assert "for i 0 10" in result

    def test_for_range_two_args(self):
        result = migrate_source("for i in range(1, 5):\n    print(i)")
        assert "for i 1 5" in result

    def test_for_range_positive_step_emits_while_loop(self):
        # Regression for #125: range(start, stop, step) with a positive
        # literal step used to silently drop the step and emit a 2-arg
        # `for` that iterated the wrong number of times. The migrator now
        # emits an equivalent while-loop so iteration count matches Python.
        result = migrate_source("for i in range(0, 10, 2):\n    print(i)")
        # No "for i 0 10" — that was the buggy output.
        assert "for i 0 10" not in result
        # While-loop equivalent must include the start assignment, the
        # `<` comparator (positive step), and the in-loop increment.
        assert "i = 0" in result
        assert "while i < 10" in result
        assert "i = i + 2" in result

    def test_for_range_negative_step_uses_greater_than(self):
        # Negative step (countdown) needs the comparator flipped to `>`,
        # otherwise the loop would iterate zero times or the wrong way.
        # The migrator's expression emitter renders -1 as the binary
        # form `0 - 1`, so checking "i = i + 0 - 1" is the literal output;
        # functionally equivalent to `i = i + -1`.
        result = migrate_source("for i in range(10, 0, -1):\n    print(i)")
        assert "i = 10" in result
        assert "while i > 0" in result
        assert "i = i + 0 - 1" in result

    def test_for_range_non_literal_step_emits_todo(self):
        # When the step is a runtime expression we can't decide the
        # comparator at migration time, so the migrator must fail loudly
        # with a manual-migration TODO rather than silently produce a
        # 2-arg `for` that runs forward.
        src = "step = -1\nfor i in range(10, 0, step):\n    print(i)"
        result = migrate_source(src)
        assert "TODO MANUAL MIGRATION" in result
        # No buggy 2-arg fallback should leak through.
        assert "for i 10 0" not in result

    def test_for_range_zero_step_emits_todo(self):
        # range(_, _, 0) raises ValueError in Python at call time. The
        # migrator should not silently emit a runnable loop for it.
        result = migrate_source("for i in range(0, 10, 0):\n    print(i)")
        assert "TODO MANUAL MIGRATION" in result
        assert "while i" not in result

    def test_for_each(self):
        result = migrate_source("for x in items:\n    print(x)")
        assert "for x in items" in result

    def test_break_continue(self):
        src = "while True:\n    break\n    continue"
        result = migrate_source(src)
        assert "break" in result
        assert "continue" in result


class TestErrorHandling:
    def test_try_catch(self):
        src = "try:\n    x = 1 / 0\nexcept Exception as e:\n    print(e)"
        result = migrate_source(src)
        assert "try" in result
        assert "catch e" in result

    def test_raise(self):
        src = 'raise Exception("boom")'
        result = migrate_source(src)
        assert 'throw "boom"' in result


class TestExpressions:
    def test_fstring(self):
        result = migrate_source('print(f"Hello {name}")')
        assert 'f"Hello {name}"' in result

    def test_list(self):
        result = migrate_source("xs = [1, 2, 3]")
        assert "xs = [1, 2, 3]" in result

    def test_dict(self):
        result = migrate_source('d = {"a": 1, "b": 2}')
        assert '"a": 1' in result

    def test_lambda(self):
        result = migrate_source("f = lambda x: x * 2")
        assert "lambda x -> x * 2" in result

    def test_list_comprehension(self):
        result = migrate_source("squares = [x * x for x in nums]")
        assert "[x * x for x in nums]" in result

    def test_negation(self):
        result = migrate_source("x = -5")
        assert "x = 0 - 5" in result

    def test_not(self):
        result = migrate_source("if not done:\n    pass")
        assert "not done" in result

    def test_comparison_chain(self):
        result = migrate_source("if a == b:\n    pass")
        assert "a == b" in result

    def test_and_or(self):
        result = migrate_source("if a and b:\n    pass")
        assert "a and b" in result

    def test_subscript(self):
        result = migrate_source("x = items[0]")
        assert "items[0]" in result


class TestBuiltinMapping:
    def test_len(self):
        result = migrate_source("n = len(xs)")
        assert "len xs" in result

    def test_str_to_to_string(self):
        result = migrate_source("s = str(42)")
        assert "to_string 42" in result

    def test_int_to_to_int(self):
        result = migrate_source('n = int("5")')
        assert 'to_int "5"' in result


class TestWarnings:
    def test_import_warning(self):
        result = migrate_source("import os")
        assert "Migration Warnings" in result
        assert "import os" in result

    def test_kwargs_warning(self):
        result = migrate_source("foo(x=1)")
        assert "Keyword arguments" in result


class TestMigrateSource:
    def test_empty(self):
        result = migrate_source("")
        assert result.strip() == ""

    def test_comment_preservation(self):
        result = migrate_source("# Hello world\nx = 1")
        assert "# Hello world" in result

    def test_pass(self):
        result = migrate_source("if True:\n    pass")
        assert "# pass" in result

    def test_assert(self):
        result = migrate_source("assert x > 0")
        assert "assert x > 0" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
