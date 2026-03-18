"""Tests for sauravtranspile — the sauravcode-to-Python transpiler."""

import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sauravtranspile import PythonTranspiler, RUNTIME_PREAMBLE


@pytest.fixture
def transpiler():
    return PythonTranspiler(include_preamble=False)


@pytest.fixture
def transpiler_with_preamble():
    return PythonTranspiler(include_preamble=True)


# ── Basic statements ────────────────────────────────────────────────

class TestAssignment:
    def test_simple_assignment(self, transpiler):
        result = transpiler.transpile('x = 42')
        assert 'x = 42' in result

    def test_string_assignment(self, transpiler):
        result = transpiler.transpile('name = "hello"')
        assert 'name =' in result and 'hello' in result

    def test_bool_assignment(self, transpiler):
        result = transpiler.transpile('flag = true')
        assert 'flag = True' in result

    def test_list_assignment(self, transpiler):
        result = transpiler.transpile('xs = [1, 2, 3]')
        assert 'xs = [1, 2, 3]' in result


class TestPrint:
    def test_print_number(self, transpiler):
        result = transpiler.transpile('print 42')
        assert '_srv_print(42)' in result

    def test_print_string(self, transpiler):
        result = transpiler.transpile('print "hello"')
        assert '_srv_print(' in result

    def test_print_expression(self, transpiler):
        result = transpiler.transpile('print 2 + 3')
        assert '_srv_print(' in result


# ── Functions ───────────────────────────────────────────────────────

class TestFunctions:
    def test_simple_function(self, transpiler):
        src = 'function add a b\n    return a + b'
        result = transpiler.transpile(src)
        assert 'def add(a, b):' in result
        assert 'return (a + b)' in result

    def test_function_call(self, transpiler):
        src = 'function greet name\n    return "hi"\ngreet "world"'
        result = transpiler.transpile(src)
        assert 'def greet(name):' in result

    def test_no_param_function(self, transpiler):
        src = 'function hello\n    print "hi"'
        result = transpiler.transpile(src)
        assert 'def hello():' in result


# ── Control flow ────────────────────────────────────────────────────

class TestControlFlow:
    def test_if_statement(self, transpiler):
        src = 'if true\n    print "yes"'
        result = transpiler.transpile(src)
        assert 'if True:' in result

    def test_if_else(self, transpiler):
        src = 'if false\n    print "no"\nelse\n    print "yes"'
        result = transpiler.transpile(src)
        assert 'if False:' in result
        assert 'else:' in result

    def test_while_loop(self, transpiler):
        src = 'x = 0\nwhile x < 10\n    x = x + 1'
        result = transpiler.transpile(src)
        assert 'while (x < 10):' in result

    def test_for_loop(self, transpiler):
        src = 'for i 0 5\n    print i'
        result = transpiler.transpile(src)
        assert 'for i in range(0, 5):' in result

    def test_for_each(self, transpiler):
        src = 'items = [1, 2, 3]\nfor item in items\n    print item'
        result = transpiler.transpile(src)
        assert 'for item in items:' in result

    def test_break_continue(self, transpiler):
        src = 'for i 0 10\n    if i == 5\n        break\n    if i == 3\n        continue'
        result = transpiler.transpile(src)
        assert 'break' in result
        assert 'continue' in result


# ── Expressions ─────────────────────────────────────────────────────

class TestExpressions:
    def test_binary_ops(self, transpiler):
        result = transpiler.transpile('x = 2 + 3 * 4')
        assert 'x =' in result

    def test_comparison(self, transpiler):
        result = transpiler.transpile('x = 1 == 1')
        assert '==' in result

    def test_logical_and(self, transpiler):
        src = 'if true and false\n    print "no"'
        result = transpiler.transpile(src)
        assert 'and' in result

    def test_logical_or(self, transpiler):
        src = 'if true or false\n    print "yes"'
        result = transpiler.transpile(src)
        assert 'or' in result

    def test_unary_not(self, transpiler):
        result = transpiler.transpile('x = not true')
        assert 'not' in result

    def test_unary_negative(self, transpiler):
        result = transpiler.transpile('x = -5')
        assert '-5' in result

    def test_list_index(self, transpiler):
        src = 'xs = [10, 20, 30]\ny = xs[1]'
        result = transpiler.transpile(src)
        assert 'xs[1]' in result

    def test_map_literal(self, transpiler):
        src = 'data = {"a": 1, "b": 2}'
        result = transpiler.transpile(src)
        assert '{' in result and '}' in result

    def test_fstring(self, transpiler):
        src = 'name = "world"\nmsg = f"hello {name}"'
        result = transpiler.transpile(src)
        assert 'f"' in result or "f'" in result


# ── Error handling ──────────────────────────────────────────────────

class TestErrorHandling:
    def test_try_catch(self, transpiler):
        src = 'try\n    x = 1 / 0\ncatch e\n    print e'
        result = transpiler.transpile(src)
        assert 'try:' in result
        assert 'except Exception as _exc:' in result

    def test_throw(self, transpiler):
        result = transpiler.transpile('throw "something went wrong"')
        assert 'raise RuntimeError(' in result


# ── Enums ───────────────────────────────────────────────────────────

class TestEnums:
    def test_enum_definition(self, transpiler):
        src = 'enum Color\n    Red\n    Green\n    Blue'
        result = transpiler.transpile(src)
        assert 'class Color(_IntEnum):' in result
        assert 'Red = 0' in result
        assert 'Green = 1' in result
        assert 'Blue = 2' in result

    def test_enum_access(self, transpiler):
        src = 'enum Color\n    Red\n    Green\n    Blue\nc = Color.Red'
        result = transpiler.transpile(src)
        assert 'Color.Red' in result


# ── Advanced features ───────────────────────────────────────────────

class TestAdvancedFeatures:
    def test_lambda(self, transpiler):
        src = 'double = lambda x -> x * 2'
        result = transpiler.transpile(src)
        assert 'lambda x:' in result

    def test_pipe(self, transpiler):
        src = 'function double x\n    return x * 2\nresult = 5 |> double'
        result = transpiler.transpile(src)
        assert 'double(5)' in result

    def test_list_comprehension(self, transpiler):
        src = 'squares = [x * x for x in range(10)]'
        result = transpiler.transpile(src)
        assert 'for' in result and 'in' in result

    def test_assert_statement(self, transpiler):
        src = 'assert 1 == 1'
        result = transpiler.transpile(src)
        assert 'assert' in result


# ── List operations ─────────────────────────────────────────────────

class TestListOps:
    def test_append(self, transpiler):
        src = 'xs = []\nappend xs 42'
        result = transpiler.transpile(src)
        assert 'xs.append(42)' in result

    def test_pop(self, transpiler):
        src = 'xs = [1, 2, 3]\npop xs'
        result = transpiler.transpile(src)
        assert 'xs.pop()' in result

    def test_indexed_assignment(self, transpiler):
        src = 'xs = [1, 2, 3]\nxs[0] = 10'
        result = transpiler.transpile(src)
        assert 'xs[0] = 10' in result


# ── Preamble ────────────────────────────────────────────────────────

class TestPreamble:
    def test_preamble_included_when_print_used(self, transpiler_with_preamble):
        result = transpiler_with_preamble.transpile('print "hello"')
        assert '_srv_print' in result
        assert RUNTIME_PREAMBLE in result

    def test_preamble_skipped_when_disabled(self, transpiler):
        result = transpiler.transpile('print "hello"')
        assert '_srv_print(' in result
        assert RUNTIME_PREAMBLE not in result

    def test_no_preamble_for_simple_assignment(self, transpiler_with_preamble):
        result = transpiler_with_preamble.transpile('x = 42')
        assert RUNTIME_PREAMBLE not in result


# ── Match/case ──────────────────────────────────────────────────────

class TestMatch:
    def test_match_basic(self, transpiler):
        src = 'x = 1\nmatch x\n    case 1\n        print "one"\n    case 2\n        print "two"'
        result = transpiler.transpile(src)
        assert 'match x:' in result
        assert 'case 1:' in result
        assert 'case 2:' in result


# ── Import ──────────────────────────────────────────────────────────

class TestImport:
    def test_import_generates_comment(self, transpiler):
        src = 'import "utils.srv"'
        result = transpiler.transpile(src)
        assert '# import' in result
        assert 'TODO' in result


# ── Integration: transpile real .srv files ──────────────────────────

class TestRealFiles:
    """Smoke tests: transpile actual .srv files from the repo without errors."""

    @pytest.fixture
    def repo_root(self):
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _transpile_file(self, path):
        with open(path, 'r', encoding='utf-8') as f:
            source = f.read()
        t = PythonTranspiler(include_preamble=True)
        result = t.transpile(source)
        assert isinstance(result, str)
        assert len(result) > 0
        return result

    def test_transpile_hello(self, repo_root):
        path = os.path.join(repo_root, 'hello.srv')
        if os.path.exists(path):
            result = self._transpile_file(path)
            assert '_srv_print' in result

    def test_transpile_break_continue_demo(self, repo_root):
        path = os.path.join(repo_root, 'break_continue_demo.srv')
        if os.path.exists(path):
            result = self._transpile_file(path)
            assert 'break' in result
            assert 'continue' in result

    def test_transpile_foreach_demo(self, repo_root):
        path = os.path.join(repo_root, 'foreach_demo.srv')
        if os.path.exists(path):
            result = self._transpile_file(path)
            assert 'for' in result

    def test_transpile_collection_demo(self, repo_root):
        path = os.path.join(repo_root, 'collection_demo.srv')
        if os.path.exists(path):
            result = self._transpile_file(path)
            assert len(result) > 50
