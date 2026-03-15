#!/usr/bin/env python3
"""Tests for sauravmetrics — code complexity analyzer."""

import json
import os
import sys
import tempfile
import unittest

# Add project root to path
_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_root))
sys.path.insert(0, _root)

# Re-add parent since sauravmetrics is at project root
sys.path.insert(0, os.path.join(os.path.dirname(_root)))

import importlib.util
spec = importlib.util.spec_from_file_location(
    "sauravmetrics",
    os.path.join(os.path.dirname(_root), "sauravmetrics.py")
)
sauravmetrics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sauravmetrics)

analyze_file = sauravmetrics.analyze_file
find_srv_files = sauravmetrics.find_srv_files
FunctionMetrics = sauravmetrics.FunctionMetrics
FileMetrics = sauravmetrics.FileMetrics


def _write_temp(code):
    """Write code to a temp .srv file and return the path."""
    fd, path = tempfile.mkstemp(suffix='.srv')
    with os.fdopen(fd, 'w') as f:
        f.write(code)
    return path


class TestLineClassification(unittest.TestCase):
    def test_blank_lines(self):
        path = _write_temp("\n\n\n")
        m = analyze_file(path)
        self.assertEqual(m.blank_lines, 3)
        self.assertEqual(m.code_lines, 0)
        os.unlink(path)

    def test_comment_lines(self):
        path = _write_temp("# comment\n# another\ncode = 1\n")
        m = analyze_file(path)
        self.assertEqual(m.comment_lines, 2)
        self.assertEqual(m.code_lines, 1)
        os.unlink(path)

    def test_total_lines(self):
        path = _write_temp("a = 1\nb = 2\n# c\n\n")
        m = analyze_file(path)
        self.assertEqual(m.total_lines, 4)
        os.unlink(path)


class TestFunctionDetection(unittest.TestCase):
    def test_function_count(self):
        code = 'function add x y\n    return x + y\n\nfunction sub x y\n    return x - y\n'
        path = _write_temp(code)
        m = analyze_file(path)
        self.assertEqual(len(m.functions), 2)
        os.unlink(path)

    def test_function_name(self):
        code = 'function greet name\n    print name\n'
        path = _write_temp(code)
        m = analyze_file(path)
        self.assertEqual(m.functions[0].name, 'greet')
        os.unlink(path)

    def test_fn_keyword(self):
        code = 'fn square x\n    return x * x\n'
        path = _write_temp(code)
        m = analyze_file(path)
        self.assertEqual(len(m.functions), 1)
        self.assertEqual(m.functions[0].name, 'square')
        os.unlink(path)

    def test_function_params(self):
        code = 'function calc a b c\n    return a + b + c\n'
        path = _write_temp(code)
        m = analyze_file(path)
        self.assertEqual(m.functions[0].params, 3)
        os.unlink(path)

    def test_function_loc(self):
        code = 'function big x\n    a = x + 1\n    b = a * 2\n    return b\n'
        path = _write_temp(code)
        m = analyze_file(path)
        self.assertEqual(m.functions[0].loc, 3)
        os.unlink(path)


class TestComplexity(unittest.TestCase):
    def test_simple_function(self):
        code = 'function id x\n    return x\n'
        path = _write_temp(code)
        m = analyze_file(path)
        self.assertEqual(m.functions[0].complexity, 1)
        os.unlink(path)

    def test_if_branch(self):
        code = 'function check x\n    if x > 0\n        return x\n    return 0\n'
        path = _write_temp(code)
        m = analyze_file(path)
        self.assertEqual(m.functions[0].complexity, 2)
        os.unlink(path)

    def test_multiple_branches(self):
        code = ('function classify x\n'
                '    if x > 10\n'
                '        return "high"\n'
                '    elif x > 5\n'
                '        return "mid"\n'
                '    return "low"\n')
        path = _write_temp(code)
        m = analyze_file(path)
        self.assertEqual(m.functions[0].complexity, 3)
        os.unlink(path)

    def test_loop_adds_complexity(self):
        code = 'function sum_list items\n    total = 0\n    for i 0 10\n        total = total + i\n    return total\n'
        path = _write_temp(code)
        m = analyze_file(path)
        self.assertEqual(m.functions[0].complexity, 2)
        os.unlink(path)

    def test_total_complexity(self):
        code = ('function a x\n    if x > 0\n        return x\n    return 0\n\n'
                'function b x\n    while x > 0\n        x = x - 1\n    return x\n')
        path = _write_temp(code)
        m = analyze_file(path)
        self.assertEqual(m.total_complexity, 4)
        os.unlink(path)


class TestNesting(unittest.TestCase):
    def test_max_depth(self):
        code = ('function deep x\n'
                '    if x > 0\n'
                '        for i 0 x\n'
                '            if i > 5\n'
                '                print i\n')
        path = _write_temp(code)
        m = analyze_file(path)
        self.assertTrue(m.max_depth >= 3)
        os.unlink(path)


class TestVariables(unittest.TestCase):
    def test_global_vars(self):
        code = 'x = 1\ny = 2\nz = x + y\n'
        path = _write_temp(code)
        m = analyze_file(path)
        self.assertEqual(len(m.global_variables), 3)
        os.unlink(path)


class TestImports(unittest.TestCase):
    def test_import_count(self):
        code = 'import utils\nimport math\nx = 1\n'
        path = _write_temp(code)
        m = analyze_file(path)
        self.assertEqual(m.imports, 2)
        os.unlink(path)


class TestMaintainability(unittest.TestCase):
    def test_score_range(self):
        code = 'x = 1\nprint x\n'
        path = _write_temp(code)
        m = analyze_file(path)
        self.assertTrue(0 <= m.maintainability_index <= 100)
        os.unlink(path)

    def test_simple_code_higher_score(self):
        simple = _write_temp('x = 1\n')
        complex_code = _write_temp(
            'function a x\n    if x > 0\n        if x > 10\n            return x\n    return 0\n' * 5
        )
        ms = analyze_file(simple)
        mc = analyze_file(complex_code)
        self.assertGreater(ms.maintainability_index, mc.maintainability_index)
        os.unlink(simple)
        os.unlink(complex_code)


class TestFileDiscovery(unittest.TestCase):
    def test_find_srv_files(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, 'a.srv'), 'w').close()
            open(os.path.join(d, 'b.srv'), 'w').close()
            open(os.path.join(d, 'c.py'), 'w').close()
            files = find_srv_files([d])
            self.assertEqual(len(files), 2)

    def test_recursive(self):
        with tempfile.TemporaryDirectory() as d:
            sub = os.path.join(d, 'sub')
            os.makedirs(sub)
            open(os.path.join(d, 'a.srv'), 'w').close()
            open(os.path.join(sub, 'b.srv'), 'w').close()
            files = find_srv_files([d], recursive=True)
            self.assertEqual(len(files), 2)


class TestProperties(unittest.TestCase):
    def test_avg_complexity_no_functions(self):
        m = FileMetrics("test.srv")
        self.assertEqual(m.avg_complexity, 0)

    def test_avg_function_loc_no_functions(self):
        m = FileMetrics("test.srv")
        self.assertEqual(m.avg_function_loc, 0)


if __name__ == '__main__':
    unittest.main()
