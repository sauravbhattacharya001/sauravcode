#!/usr/bin/env python3
"""Tests for sauravprophet — Autonomous Test Case Generator."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sauravprophet import (
    discover_functions, generate_test_values, predict_output,
    generate_test_srv, generate_html_report, analyze_file,
    _boundary_values, _infer_param_type, _cartesian_product,
    _parse_num, _format_arg, FuncInfo, TestCase, ProphetReport,
)


class TestFunctionDiscovery(unittest.TestCase):
    """Test function discovery from .srv source."""

    def test_simple_function(self):
        src = "function add x y\n    return x + y\n"
        funcs = discover_functions(src)
        self.assertEqual(len(funcs), 1)
        self.assertEqual(funcs[0].name, "add")
        self.assertEqual(funcs[0].params, ["x", "y"])

    def test_no_params(self):
        src = "function greet\n    print \"hello\"\n"
        funcs = discover_functions(src)
        self.assertEqual(len(funcs), 1)
        self.assertEqual(funcs[0].params, [])

    def test_multiple_functions(self):
        src = ("function add x y\n    return x + y\n\n"
               "function sub x y\n    return x - y\n")
        funcs = discover_functions(src)
        self.assertEqual(len(funcs), 2)
        self.assertEqual(funcs[0].name, "add")
        self.assertEqual(funcs[1].name, "sub")

    def test_recursive_detection(self):
        src = "function factorial n\n    if n <= 1\n        return 1\n    return n * factorial (n - 1)\n"
        funcs = discover_functions(src)
        self.assertTrue(funcs[0].is_recursive)

    def test_non_recursive(self):
        src = "function double x\n    return x * 2\n"
        funcs = discover_functions(src)
        self.assertFalse(funcs[0].is_recursive)

    def test_conditional_detection(self):
        src = "function abs x\n    if x < 0\n        return 0 - x\n    return x\n"
        funcs = discover_functions(src)
        self.assertTrue(funcs[0].has_conditionals)

    def test_no_conditionals(self):
        src = "function add x y\n    return x + y\n"
        funcs = discover_functions(src)
        self.assertFalse(funcs[0].has_conditionals)

    def test_comparison_extraction(self):
        src = "function check x\n    if x > 10\n        return 1\n    return 0\n"
        funcs = discover_functions(src)
        self.assertEqual(len(funcs[0].comparisons), 1)
        self.assertEqual(funcs[0].comparisons[0]['var'], 'x')
        self.assertEqual(funcs[0].comparisons[0]['op'], '>')
        self.assertEqual(funcs[0].comparisons[0]['value'], '10')

    def test_string_usage(self):
        src = 'function greet name\n    return "Hello " + name\n'
        funcs = discover_functions(src)
        self.assertTrue(funcs[0].uses_strings)

    def test_math_usage(self):
        src = "function calc x\n    return x * 2 + 1\n"
        funcs = discover_functions(src)
        self.assertTrue(funcs[0].uses_math)

    def test_empty_source(self):
        funcs = discover_functions("")
        self.assertEqual(len(funcs), 0)

    def test_no_functions(self):
        src = "x = 5\nprint x\n"
        funcs = discover_functions(src)
        self.assertEqual(len(funcs), 0)

    def test_return_count(self):
        src = "function abs x\n    if x < 0\n        return 0 - x\n    return x\n"
        funcs = discover_functions(src)
        self.assertEqual(funcs[0].return_count, 2)

    def test_line_number(self):
        src = "# comment\n\nfunction foo x\n    return x\n"
        funcs = discover_functions(src)
        self.assertEqual(funcs[0].line_number, 3)

    def test_single_param(self):
        src = "function square n\n    return n * n\n"
        funcs = discover_functions(src)
        self.assertEqual(funcs[0].params, ["n"])

    def test_many_params(self):
        src = "function calc a b c d e\n    return a + b + c + d + e\n"
        funcs = discover_functions(src)
        self.assertEqual(len(funcs[0].params), 5)


class TestBoundaryValues(unittest.TestCase):
    """Test boundary value extraction."""

    def test_greater_than(self):
        cmps = [{'var': 'x', 'op': '>', 'value': '10'}]
        vals = _boundary_values(cmps, 'x')
        self.assertIn(10, vals)
        self.assertIn(9, vals)
        self.assertIn(11, vals)

    def test_less_than(self):
        cmps = [{'var': 'x', 'op': '<', 'value': '5'}]
        vals = _boundary_values(cmps, 'x')
        self.assertIn(5, vals)
        self.assertIn(4, vals)
        self.assertIn(6, vals)

    def test_equality(self):
        cmps = [{'var': 'n', 'op': '==', 'value': '0'}]
        vals = _boundary_values(cmps, 'n')
        self.assertIn(0, vals)
        self.assertIn(-1, vals)
        self.assertIn(1, vals)

    def test_wrong_param(self):
        cmps = [{'var': 'x', 'op': '>', 'value': '10'}]
        vals = _boundary_values(cmps, 'y')
        self.assertEqual(vals, [])

    def test_non_numeric(self):
        cmps = [{'var': 'x', 'op': '==', 'value': 'hello'}]
        vals = _boundary_values(cmps, 'x')
        self.assertEqual(vals, [])


class TestValueGeneration(unittest.TestCase):
    """Test test value generation."""

    def test_smart_numeric(self):
        func = FuncInfo(name="f", params=["x"], body_lines=["    return x + 1"],
                        line_number=1, file_path="t.srv")
        combos = generate_test_values(func, "smart")
        self.assertGreater(len(combos), 0)

    def test_edge_strategy(self):
        func = FuncInfo(name="f", params=["x"], body_lines=["    return x"],
                        line_number=1, file_path="t.srv")
        combos = generate_test_values(func, "edge")
        flat = [c[0] for c in combos]
        self.assertIn(0, flat)
        self.assertIn(-1, flat)

    def test_random_strategy(self):
        func = FuncInfo(name="f", params=["x"], body_lines=["    return x"],
                        line_number=1, file_path="t.srv")
        combos = generate_test_values(func, "random")
        self.assertGreater(len(combos), 0)

    def test_no_params(self):
        func = FuncInfo(name="f", params=[], body_lines=["    return 42"],
                        line_number=1, file_path="t.srv")
        combos = generate_test_values(func, "smart")
        self.assertEqual(combos, [[]])

    def test_boundary_integration(self):
        func = FuncInfo(name="f", params=["x"], body_lines=["    if x > 10", "        return 1"],
                        line_number=1, file_path="t.srv", has_conditionals=True,
                        comparisons=[{'var': 'x', 'op': '>', 'value': '10'}])
        combos = generate_test_values(func, "smart")
        flat = [c[0] for c in combos]
        self.assertIn(10, flat)

    def test_max_combos_cap(self):
        func = FuncInfo(name="f", params=["a", "b", "c", "d"],
                        body_lines=["    return a"], line_number=1, file_path="t.srv")
        combos = generate_test_values(func, "edge")
        self.assertLessEqual(len(combos), 30)


class TestPrediction(unittest.TestCase):
    """Test output prediction."""

    def test_simple_addition(self):
        func = FuncInfo(name="add", params=["x", "y"],
                        body_lines=["    return x + y"], line_number=1, file_path="t.srv",
                        return_count=1)
        pred, conf = predict_output(func, [3, 5])
        self.assertEqual(pred, 8)
        self.assertEqual(conf, "high")

    def test_multiplication(self):
        func = FuncInfo(name="mul", params=["a", "b"],
                        body_lines=["    return a * b"], line_number=1, file_path="t.srv",
                        return_count=1)
        pred, conf = predict_output(func, [4, 7])
        self.assertEqual(pred, 28)

    def test_recursive_no_predict(self):
        func = FuncInfo(name="fact", params=["n"],
                        body_lines=["    if n <= 1", "        return 1",
                                    "    return n * fact (n - 1)"],
                        line_number=1, file_path="t.srv", is_recursive=True,
                        has_conditionals=True, return_count=2)
        pred, conf = predict_output(func, [5])
        self.assertIsNone(pred)
        self.assertEqual(conf, "low")

    def test_conditional_no_predict(self):
        func = FuncInfo(name="abs", params=["x"],
                        body_lines=["    if x < 0", "        return 0 - x", "    return x"],
                        line_number=1, file_path="t.srv", has_conditionals=True,
                        return_count=2)
        pred, conf = predict_output(func, [5])
        self.assertIsNone(pred)


class TestSrvGeneration(unittest.TestCase):
    """Test .srv test file generation."""

    def test_generates_valid_header(self):
        func = FuncInfo(name="add", params=["x", "y"],
                        body_lines=["    return x + y"], line_number=1, file_path="t.srv")
        tc = TestCase(func_name="add", args=[1, 2], arg_descriptions=["x=1", "y=2"],
                      strategy="smart")
        source_lines = ["function add x y", "    return x + y"]
        srv = generate_test_srv(func, [tc], source_lines)
        self.assertIn("# Auto-generated test file by sauravprophet", srv)
        self.assertIn("function add x y", srv)

    def test_generates_test_calls(self):
        func = FuncInfo(name="add", params=["x", "y"],
                        body_lines=["    return x + y"], line_number=1, file_path="t.srv")
        tc = TestCase(func_name="add", args=[3, 5], arg_descriptions=["x=3", "y=5"],
                      strategy="smart")
        source_lines = ["function add x y", "    return x + y"]
        srv = generate_test_srv(func, [tc], source_lines)
        self.assertIn("_result_0 = add 3 5", srv)
        self.assertIn("print _result_0", srv)


class TestHtmlReport(unittest.TestCase):
    """Test HTML report generation."""

    def test_generates_html(self):
        func = FuncInfo(name="f", params=["x"], body_lines=["    return x"],
                        line_number=1, file_path="t.srv")
        tc = TestCase(func_name="f", args=[1], arg_descriptions=["x=1"],
                      strategy="smart", passed=True, actual_output="1")
        report = ProphetReport(file_path="t.srv", functions=[func], test_cases=[tc],
                               total_functions=1, total_tests=1, tests_run=1, tests_passed=1)
        html = generate_html_report([report])
        self.assertIn("sauravprophet", html)
        self.assertIn("<!DOCTYPE html>", html)

    def test_html_escaping(self):
        func = FuncInfo(name="f", params=["x"], body_lines=["    return x"],
                        line_number=1, file_path="<bad>.srv")
        tc = TestCase(func_name="f", args=[1], arg_descriptions=["x=1"],
                      strategy="smart")
        report = ProphetReport(file_path="<bad>.srv", functions=[func], test_cases=[tc],
                               total_functions=1, total_tests=1)
        html = generate_html_report([report])
        self.assertNotIn("<bad>", html)
        self.assertIn("&lt;bad&gt;", html)


class TestHelpers(unittest.TestCase):
    """Test helper functions."""

    def test_parse_num_int(self):
        self.assertEqual(_parse_num("42"), 42)

    def test_parse_num_float(self):
        self.assertEqual(_parse_num("3.14"), 3.14)

    def test_parse_num_invalid(self):
        self.assertIsNone(_parse_num("hello"))

    def test_format_arg_int(self):
        self.assertEqual(_format_arg(5), "5")

    def test_format_arg_string(self):
        self.assertEqual(_format_arg('"hello"'), '"hello"')

    def test_cartesian_product(self):
        result = _cartesian_product([[1, 2], [3, 4]])
        self.assertEqual(len(result), 4)
        self.assertIn([1, 3], result)

    def test_cartesian_product_cap(self):
        result = _cartesian_product([[1,2,3,4,5,6,7,8,9,10]] * 3, max_combos=5)
        self.assertLessEqual(len(result), 5)

    def test_cartesian_product_empty(self):
        result = _cartesian_product([])
        self.assertEqual(result, [[]])


class TestAnalyzeFile(unittest.TestCase):
    """Test end-to-end file analysis."""

    def test_analyze_simple_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.srv', delete=False,
                                         encoding='utf-8') as f:
            f.write("function add x y\n    return x + y\n")
            path = f.name
        try:
            report = analyze_file(path, strategy="smart", max_tests=10)
            self.assertEqual(report.total_functions, 1)
            self.assertGreater(report.total_tests, 0)
        finally:
            os.unlink(path)

    def test_analyze_with_predict(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.srv', delete=False,
                                         encoding='utf-8') as f:
            f.write("function mul a b\n    return a * b\n")
            path = f.name
        try:
            report = analyze_file(path, strategy="smart", max_tests=10, do_predict=True)
            predicted = [tc for tc in report.test_cases if tc.predicted_output is not None]
            self.assertGreater(len(predicted), 0)
        finally:
            os.unlink(path)

    def test_analyze_empty_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.srv', delete=False,
                                         encoding='utf-8') as f:
            f.write("# just a comment\n")
            path = f.name
        try:
            report = analyze_file(path)
            self.assertEqual(report.total_functions, 0)
            self.assertEqual(report.total_tests, 0)
        finally:
            os.unlink(path)

    def test_max_tests_limit(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.srv', delete=False,
                                         encoding='utf-8') as f:
            f.write("function a x\n    return x\n\n"
                    "function b x\n    return x\n\n"
                    "function c x\n    return x\n")
            path = f.name
        try:
            report = analyze_file(path, max_tests=5)
            self.assertLessEqual(report.total_tests, 5)
        finally:
            os.unlink(path)


class TestParamTypeInference(unittest.TestCase):
    """Test parameter type inference."""

    def test_string_param(self):
        func = FuncInfo(name="f", params=["s"],
                        body_lines=['    if s == "hello"', '        return 1'],
                        line_number=1, file_path="t.srv")
        self.assertEqual(_infer_param_type(func, "s"), "string")

    def test_list_param(self):
        func = FuncInfo(name="f", params=["lst"],
                        body_lines=["    x = len lst", "    return x"],
                        line_number=1, file_path="t.srv")
        self.assertEqual(_infer_param_type(func, "lst"), "list")

    def test_bool_param(self):
        func = FuncInfo(name="f", params=["flag"],
                        body_lines=["    if flag == true", "        return 1"],
                        line_number=1, file_path="t.srv")
        self.assertEqual(_infer_param_type(func, "flag"), "bool")

    def test_numeric_default(self):
        func = FuncInfo(name="f", params=["x"],
                        body_lines=["    return x + 1"],
                        line_number=1, file_path="t.srv")
        self.assertEqual(_infer_param_type(func, "x"), "numeric")


if __name__ == '__main__':
    unittest.main()
