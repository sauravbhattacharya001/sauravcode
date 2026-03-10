"""Tests for sauravtranspile — sauravcode to Python transpiler."""

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sauravtranspile import transpile, transpile_file, PythonTranspiler


class TestBasicTranspile(unittest.TestCase):
    """Test basic language constructs transpile correctly."""

    def test_hello_world(self):
        code = transpile('print "Hello, World!"', include_preamble=False)
        self.assertIn('_srv_print', code)
        self.assertIn("Hello, World!", code)

    def test_assignment(self):
        code = transpile('x = 42', include_preamble=False)
        self.assertIn('x = 42', code)

    def test_multiple_assignments(self):
        code = transpile('x = 1\ny = 2\nz = 3', include_preamble=False)
        self.assertIn('x = 1', code)
        self.assertIn('y = 2', code)
        self.assertIn('z = 3', code)

    def test_string_assignment(self):
        code = transpile('name = "Alice"', include_preamble=False)
        self.assertIn("name = 'Alice'", code)

    def test_boolean_true(self):
        code = transpile('x = true', include_preamble=False)
        self.assertIn('x = True', code)

    def test_boolean_false(self):
        code = transpile('x = false', include_preamble=False)
        self.assertIn('x = False', code)

    def test_binary_ops(self):
        code = transpile('x = 3 + 4\ny = 10 - 2\nz = 6 * 7', include_preamble=False)
        self.assertIn('(3 + 4)', code)
        self.assertIn('(10 - 2)', code)
        self.assertIn('(6 * 7)', code)


class TestFunctions(unittest.TestCase):

    def test_simple_function(self):
        src = 'function greet name\n    print name\n'
        code = transpile(src, include_preamble=False)
        self.assertIn('def greet(name):', code)

    def test_function_return(self):
        src = 'function add x y\n    return x + y\n'
        code = transpile(src, include_preamble=False)
        self.assertIn('def add(x, y):', code)
        self.assertIn('return (x + y)', code)

    def test_function_call(self):
        src = 'function square x\n    return x * x\nsquare 5'
        code = transpile(src, include_preamble=False)
        self.assertIn('square(5)', code)

    def test_lambda(self):
        src = 'f = lambda x -> x * 2'
        code = transpile(src, include_preamble=False)
        self.assertIn('lambda x:', code)


class TestControlFlow(unittest.TestCase):

    def test_if(self):
        src = 'if true\n    print "yes"\n'
        code = transpile(src, include_preamble=False)
        self.assertIn('if True:', code)

    def test_if_else(self):
        src = 'if false\n    print "no"\nelse\n    print "yes"\n'
        code = transpile(src, include_preamble=False)
        self.assertIn('if False:', code)
        self.assertIn('else:', code)

    def test_elif(self):
        src = 'x = 5\nif x == 1\n    print "one"\nelse if x == 5\n    print "five"\nelse\n    print "other"\n'
        code = transpile(src, include_preamble=False)
        self.assertIn('elif', code)
        self.assertIn('else:', code)

    def test_while(self):
        src = 'x = 0\nwhile x < 5\n    x = x + 1\n'
        code = transpile(src, include_preamble=False)
        self.assertIn('while (x < 5):', code)

    def test_for(self):
        src = 'for i 0 5\n    print i\n'
        code = transpile(src, include_preamble=False)
        self.assertIn('for i in range(0, 5):', code)

    def test_for_each(self):
        src = 'items = [1, 2, 3]\nfor x in items\n    print x\n'
        code = transpile(src, include_preamble=False)
        self.assertIn('for x in items:', code)

    def test_break(self):
        src = 'while true\n    break\n'
        code = transpile(src, include_preamble=False)
        self.assertIn('break', code)

    def test_continue(self):
        src = 'for i 0 10\n    continue\n'
        code = transpile(src, include_preamble=False)
        self.assertIn('continue', code)


class TestCollections(unittest.TestCase):

    def test_list(self):
        code = transpile('nums = [1, 2, 3]', include_preamble=False)
        self.assertIn('[1, 2, 3]', code)

    def test_map_literal(self):
        src = 'config = {"host": "localhost", "port": 8080}'
        code = transpile(src, include_preamble=False)
        self.assertIn("'host':", code)
        self.assertIn("'localhost'", code)

    def test_append(self):
        src = 'items = [1]\nappend items 2'
        code = transpile(src, include_preamble=False)
        self.assertIn('items.append(2)', code)

    def test_index(self):
        src = 'items = [10, 20, 30]\nx = items[1]'
        code = transpile(src, include_preamble=False)
        self.assertIn('items[1]', code)

    def test_slice(self):
        src = 'items = [1, 2, 3, 4, 5]\npart = items[1:3]'
        code = transpile(src, include_preamble=False)
        self.assertIn('items[1:3]', code)

    def test_indexed_assignment(self):
        src = 'items = [1, 2, 3]\nitems[0] = 99'
        code = transpile(src, include_preamble=False)
        self.assertIn('items[0] = 99', code)

    def test_list_comprehension(self):
        src = 'squares = [x * x for x in [1, 2, 3]]'
        code = transpile(src, include_preamble=False)
        self.assertIn('for x in', code)

    def test_list_comprehension_filter(self):
        src = 'evens = [x for x in [1, 2, 3, 4] if x % 2 == 0]'
        code = transpile(src, include_preamble=False)
        self.assertIn('if', code)
        self.assertIn('for x in', code)


class TestErrorHandling(unittest.TestCase):

    def test_try_catch(self):
        src = 'try\n    throw "oops"\ncatch e\n    print e\n'
        code = transpile(src, include_preamble=False)
        self.assertIn('try:', code)
        self.assertIn('except Exception as _exc:', code)
        self.assertIn('e = str(_exc)', code)

    def test_throw(self):
        src = 'throw "something failed"'
        code = transpile(src, include_preamble=False)
        self.assertIn('raise RuntimeError', code)

    def test_assert(self):
        code = transpile('assert 1 == 1', include_preamble=False)
        self.assertIn('assert', code)

    def test_assert_with_message(self):
        src = 'assert x > 0 "must be positive"'
        code = transpile(src, include_preamble=False)
        self.assertIn('assert', code)


class TestAdvancedFeatures(unittest.TestCase):

    def test_fstring(self):
        src = 'name = "World"\nprint f"Hello {name}!"'
        code = transpile(src, include_preamble=False)
        self.assertIn('f"Hello {name}!"', code)

    def test_pipe_operator(self):
        src = 'function double x\n    return x * 2\nresult = 5 |> double'
        code = transpile(src, include_preamble=False)
        self.assertIn('double(5)', code)

    def test_enum(self):
        src = 'enum Color\n    RED\n    GREEN\n    BLUE\n'
        code = transpile(src, include_preamble=False)
        self.assertIn('class Color(_IntEnum):', code)
        self.assertIn('RED = 0', code)
        self.assertIn('GREEN = 1', code)
        self.assertIn('BLUE = 2', code)

    def test_enum_access(self):
        src = 'enum Color\n    RED\n    GREEN\nx = Color.RED'
        code = transpile(src, include_preamble=False)
        self.assertIn('Color.RED', code)

    def test_match(self):
        src = 'x = 5\nmatch x\n    case 1\n        print "one"\n    case 5\n        print "five"\n'
        code = transpile(src, include_preamble=False)
        self.assertIn('match x:', code)
        self.assertIn('case 1:', code)
        self.assertIn('case 5:', code)

    def test_ternary(self):
        src = 'x = 10\ny = "big" if x > 5 else "small"'
        code = transpile(src, include_preamble=False)
        self.assertIn('if', code)
        self.assertIn('else', code)

    def test_yield(self):
        src = 'function gen\n    yield 1\n    yield 2\n'
        code = transpile(src, include_preamble=False)
        self.assertIn('yield 1', code)
        self.assertIn('yield 2', code)

    def test_import(self):
        src = 'import "utils"'
        code = transpile(src, include_preamble=False)
        self.assertIn('# import "utils"', code)
        self.assertIn('TODO', code)


class TestBuiltins(unittest.TestCase):

    def test_len(self):
        src = 'items = [1, 2, 3]\nn = len items'
        code = transpile(src, include_preamble=False)
        self.assertIn('len(items)', code)

    def test_contains(self):
        src = 'x = contains "hello" "ell"'
        code = transpile(src, include_preamble=False)
        self.assertIn('_srv_contains', code)

    def test_upper(self):
        src = 'x = upper "hello"'
        code = transpile(src, include_preamble=False)
        self.assertIn(".upper()", code)

    def test_sort(self):
        src = 'x = sort [3, 1, 2]'
        code = transpile(src, include_preamble=False)
        self.assertIn('sorted(', code)

    def test_map_builtin(self):
        src = 'result = map (lambda x -> x * 2) [1, 2, 3]'
        code = transpile(src, include_preamble=False)
        self.assertIn('list(map(', code)

    def test_filter_builtin(self):
        src = 'result = filter (lambda x -> x > 2) [1, 2, 3, 4]'
        code = transpile(src, include_preamble=False)
        self.assertIn('list(filter(', code)

    def test_range_builtin(self):
        src = 'nums = range 10'
        code = transpile(src, include_preamble=False)
        self.assertIn('list(range(10))', code)

    def test_type_of(self):
        src = 'x = type_of 42'
        code = transpile(src, include_preamble=False)
        self.assertIn('_srv_type_of(42)', code)


class TestPreamble(unittest.TestCase):

    def test_preamble_included_when_needed(self):
        code = transpile('print "hello"', include_preamble=True)
        self.assertIn('def _srv_print', code)

    def test_no_preamble_when_disabled(self):
        code = transpile('print "hello"', include_preamble=False)
        self.assertNotIn('import math', code)

    def test_preamble_has_runtime_helpers(self):
        code = transpile('x = contains "hello" "ell"', include_preamble=True)
        self.assertIn('def _srv_contains', code)


class TestOutputExecution(unittest.TestCase):
    """Test that transpiled output actually runs correctly."""

    def _run_python(self, source):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False,
                                         encoding='utf-8') as f:
            f.write(source)
            path = f.name
        try:
            result = subprocess.run(
                [sys.executable, path],
                capture_output=True, text=True, timeout=10,
            )
            return result.stdout, result.stderr, result.returncode
        finally:
            os.unlink(path)

    def test_hello_runs(self):
        code = transpile('print "Hello!"')
        out, err, rc = self._run_python(code)
        self.assertEqual(rc, 0, f"stderr: {err}")
        self.assertIn("Hello!", out)

    def test_arithmetic_runs(self):
        code = transpile('print 3 + 4')
        out, err, rc = self._run_python(code)
        self.assertEqual(rc, 0, f"stderr: {err}")
        self.assertIn("7", out)

    def test_function_runs(self):
        src = 'function square x\n    return x * x\nprint square 5'
        code = transpile(src)
        out, err, rc = self._run_python(code)
        self.assertEqual(rc, 0, f"stderr: {err}")
        self.assertIn("25", out)

    def test_for_loop_runs(self):
        src = 'total = 0\nfor i 1 6\n    total = total + i\nprint total'
        code = transpile(src)
        out, err, rc = self._run_python(code)
        self.assertEqual(rc, 0, f"stderr: {err}")
        self.assertIn("15", out)

    def test_list_operations_run(self):
        src = 'items = [10, 20, 30]\nappend items 40\nprint len items'
        code = transpile(src)
        out, err, rc = self._run_python(code)
        self.assertEqual(rc, 0, f"stderr: {err}")
        self.assertIn("4", out)

    def test_fstring_runs(self):
        src = 'name = "World"\nprint f"Hello {name}!"'
        code = transpile(src)
        out, err, rc = self._run_python(code)
        self.assertEqual(rc, 0, f"stderr: {err}")
        self.assertIn("Hello World!", out)

    def test_try_catch_runs(self):
        src = 'try\n    throw "boom"\ncatch e\n    print e'
        code = transpile(src)
        out, err, rc = self._run_python(code)
        self.assertEqual(rc, 0, f"stderr: {err}")
        self.assertIn("boom", out)

    def test_if_else_runs(self):
        src = 'x = 10\nif x > 5\n    print "big"\nelse\n    print "small"'
        code = transpile(src)
        out, err, rc = self._run_python(code)
        self.assertEqual(rc, 0, f"stderr: {err}")
        self.assertIn("big", out)

    def test_while_loop_runs(self):
        src = 'x = 0\nwhile x < 3\n    x = x + 1\nprint x'
        code = transpile(src)
        out, err, rc = self._run_python(code)
        self.assertEqual(rc, 0, f"stderr: {err}")
        self.assertIn("3", out)

    def test_enum_runs(self):
        src = 'enum Color\n    RED\n    GREEN\n    BLUE\nprint Color.GREEN'
        code = transpile(src)
        out, err, rc = self._run_python(code)
        self.assertEqual(rc, 0, f"stderr: {err}")
        self.assertIn("1", out)


class TestTranspileFile(unittest.TestCase):

    def test_transpile_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.srv', delete=False,
                                         encoding='utf-8') as f:
            f.write('print "file test"')
            srv_path = f.name

        try:
            py_path = srv_path.replace('.srv', '.py')
            code = transpile_file(srv_path, py_path)
            self.assertTrue(os.path.exists(py_path))
            self.assertIn('_srv_print', code)
        finally:
            os.unlink(srv_path)
            if os.path.exists(py_path):
                os.unlink(py_path)


if __name__ == "__main__":
    unittest.main()
