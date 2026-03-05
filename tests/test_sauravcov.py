#!/usr/bin/env python3
"""Tests for sauravcov.py - Code coverage tool for sauravcode."""

import os
import sys
import json
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sauravcov import (
    CoverageData, CoverageInterpreter, run_with_coverage,
    format_text_report, format_json_report, format_html_report,
    merge_coverage, collect_srv_files, _find_executable_lines,
    _collect_node_lines,
)
from saurav import tokenize, ASTNode, IfNode, FunctionNode
from sauravdb import LineTrackingParser


class TestCoverageData(unittest.TestCase):
    """Tests for CoverageData class."""

    def test_empty_coverage(self):
        cov = CoverageData("test.srv", [])
        self.assertEqual(cov.total_executable, 0)
        self.assertEqual(cov.total_executed, 0)
        self.assertEqual(cov.coverage_percent, 100.0)

    def test_full_coverage(self):
        cov = CoverageData("test.srv", ["x = 1", "y = 2"])
        cov.executable_lines = {1, 2}
        cov.executed_lines = {1, 2}
        self.assertEqual(cov.coverage_percent, 100.0)
        self.assertEqual(cov.missing_lines, [])

    def test_partial_coverage(self):
        cov = CoverageData("test.srv", ["x = 1", "y = 2", "z = 3"])
        cov.executable_lines = {1, 2, 3}
        cov.executed_lines = {1, 3}
        self.assertAlmostEqual(cov.coverage_percent, 66.67, places=1)
        self.assertEqual(cov.missing_lines, [2])

    def test_no_coverage(self):
        cov = CoverageData("test.srv", ["x = 1"])
        cov.executable_lines = {1}
        cov.executed_lines = set()
        self.assertEqual(cov.coverage_percent, 0.0)

    def test_missing_ranges_single(self):
        cov = CoverageData("test.srv", [""] * 5)
        cov.executable_lines = {1, 2, 3, 4, 5}
        cov.executed_lines = {1, 3, 5}
        self.assertEqual(cov.missing_ranges(), "2, 4")

    def test_missing_ranges_contiguous(self):
        cov = CoverageData("test.srv", [""] * 10)
        cov.executable_lines = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}
        cov.executed_lines = {1, 2, 7, 8, 9, 10}
        self.assertEqual(cov.missing_ranges(), "3-6")

    def test_missing_ranges_mixed(self):
        cov = CoverageData("test.srv", [""] * 10)
        cov.executable_lines = set(range(1, 11))
        cov.executed_lines = {1, 4, 5, 9}
        self.assertEqual(cov.missing_ranges(), "2-3, 6-8, 10")

    def test_missing_ranges_empty(self):
        cov = CoverageData("test.srv", ["x = 1"])
        cov.executable_lines = {1}
        cov.executed_lines = {1}
        self.assertEqual(cov.missing_ranges(), "")

    def test_executed_lines_intersection(self):
        """executed_lines outside executable_lines don't count."""
        cov = CoverageData("test.srv", ["x = 1", "# comment"])
        cov.executable_lines = {1}
        cov.executed_lines = {1, 2, 99}
        self.assertEqual(cov.total_executed, 1)
        self.assertEqual(cov.coverage_percent, 100.0)

    def test_branch_coverage_empty(self):
        cov = CoverageData("test.srv", [])
        self.assertEqual(cov.branch_coverage_percent(), 100.0)

    def test_branch_coverage_partial(self):
        cov = CoverageData("test.srv", [])
        cov.branch_total = 4
        cov.branch_taken = 3
        self.assertEqual(cov.branch_coverage_percent(), 75.0)


class TestFindExecutableLines(unittest.TestCase):
    """Tests for _find_executable_lines."""

    def test_simple(self):
        src = "x = 1\n# comment\ny = 2\n\nz = 3"
        result = _find_executable_lines(src)
        self.assertEqual(result, {1, 3, 5})

    def test_all_comments(self):
        src = "# line 1\n# line 2\n"
        result = _find_executable_lines(src)
        self.assertEqual(result, set())

    def test_empty(self):
        result = _find_executable_lines("")
        self.assertEqual(result, set())

    def test_blank_lines(self):
        src = "\n\n\n"
        result = _find_executable_lines(src)
        self.assertEqual(result, set())

    def test_indented_code(self):
        src = "if x == 1\n    y = 2\n    z = 3"
        result = _find_executable_lines(src)
        self.assertEqual(result, {1, 2, 3})

    def test_comment_after_code(self):
        """Lines with code + comment are executable."""
        src = "x = 1  # assign x"
        result = _find_executable_lines(src)
        self.assertEqual(result, {1})


class TestRunWithCoverage(unittest.TestCase):
    """Tests for run_with_coverage with actual .srv programs."""

    def _run(self, code, **kwargs):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.srv',
                                          delete=False, encoding='utf-8') as f:
            f.write(code)
            f.flush()
            name = f.name
        try:
            return run_with_coverage(name, code, **kwargs)
        finally:
            os.unlink(name)

    def test_simple_assignment(self):
        cov = self._run("x = 5\ny = 10\nprint x + y")
        self.assertEqual(cov.total_executed, cov.total_executable)
        self.assertEqual(cov.coverage_percent, 100.0)

    def test_if_true_branch(self):
        code = "x = 10\nif x > 5\n    print x\n"
        cov = self._run(code)
        self.assertIn(1, cov.executed_lines)
        self.assertIn(2, cov.executed_lines)
        self.assertIn(3, cov.executed_lines)

    def test_if_false_branch_uncovered(self):
        code = "x = 1\nif x > 5\n    print x\n"
        cov = self._run(code)
        self.assertIn(1, cov.executed_lines)
        self.assertIn(2, cov.executed_lines)
        self.assertNotIn(3, cov.executed_lines)

    def test_if_else(self):
        code = "x = 1\nif x > 5\n    print x\nelse\n    print 0\n"
        cov = self._run(code)
        self.assertIn(5, cov.executed_lines)
        self.assertNotIn(3, cov.executed_lines)

    def test_while_loop(self):
        code = "x = 0\nwhile x < 3\n    x = x + 1\nprint x\n"
        cov = self._run(code)
        self.assertEqual(cov.coverage_percent, 100.0)

    def test_while_never_entered(self):
        code = "x = 10\nwhile x < 3\n    x = x + 1\nprint x\n"
        cov = self._run(code)
        self.assertNotIn(3, cov.executed_lines)

    def test_for_loop(self):
        code = "for i 0 to 3\n    print i\n"
        cov = self._run(code)
        self.assertIn(1, cov.executed_lines)

    def test_function_def_and_call(self):
        code = "function add a b\n    return a + b\nx = add 3 4\nprint x\n"
        cov = self._run(code)
        self.assertIn(1, cov.executed_lines)
        self.assertIn(2, cov.executed_lines)

    def test_function_not_called(self):
        code = "function foo\n    print 1\nprint 2\n"
        cov = self._run(code)
        self.assertNotIn(2, cov.executed_lines)
        self.assertIn(3, cov.executed_lines)

    def test_runtime_error_captured(self):
        code = "x = 1 / 0\n"
        cov = self._run(code)
        self.assertTrue(hasattr(cov, 'runtime_error'))

    def test_branch_tracking(self):
        code = "x = 10\nif x > 5\n    print x\n"
        cov = self._run(code, track_branches=True)
        self.assertGreater(cov.branch_total, 0)

    def test_multiple_statements(self):
        code = "a = 1\nb = 2\nc = 3\nd = 4\ne = 5\n"
        cov = self._run(code)
        self.assertEqual(cov.total_executable, 5)
        self.assertEqual(cov.total_executed, 5)
        self.assertEqual(cov.coverage_percent, 100.0)

    def test_nested_if(self):
        code = "x = 10\nif x > 5\n    if x > 20\n        print 1\n    else\n        print 2\n"
        cov = self._run(code)
        self.assertNotIn(4, cov.executed_lines)
        self.assertIn(6, cov.executed_lines)

    def test_string_operations(self):
        code = 'name = "hello"\nprint name\n'
        cov = self._run(code)
        self.assertEqual(cov.coverage_percent, 100.0)

    def test_empty_program(self):
        cov = self._run("")
        self.assertEqual(cov.coverage_percent, 100.0)

    def test_comment_only(self):
        cov = self._run("# just a comment\n# another one\n")
        self.assertEqual(cov.total_executable, 0)
        self.assertEqual(cov.coverage_percent, 100.0)

    def test_try_catch_no_error(self):
        code = "try\n    x = 5\ncatch e\n    print e\nprint x\n"
        cov = self._run(code)
        self.assertIn(2, cov.executed_lines)
        self.assertNotIn(4, cov.executed_lines)

    def test_list_operations(self):
        code = "nums = [1, 2, 3]\nappend nums 4\nprint len nums\n"
        cov = self._run(code)
        self.assertEqual(cov.coverage_percent, 100.0)

    def test_coverage_percent_rounding(self):
        cov = CoverageData("test.srv", [""] * 3)
        cov.executable_lines = {1, 2, 3}
        cov.executed_lines = {1}
        self.assertAlmostEqual(cov.coverage_percent, 33.33, places=1)


class TestFormatTextReport(unittest.TestCase):
    """Tests for format_text_report."""

    def _make_cov(self, name, total, executed):
        cov = CoverageData(name, [""] * total)
        cov.executable_lines = set(range(1, total + 1))
        cov.executed_lines = set(range(1, executed + 1))
        return cov

    def test_single_file_full(self):
        report = format_text_report([self._make_cov("a.srv", 10, 10)])
        self.assertIn("100.0%", report)
        self.assertIn("a.srv", report)

    def test_single_file_partial(self):
        report = format_text_report([self._make_cov("b.srv", 10, 5)])
        self.assertIn("50.0%", report)

    def test_multiple_files(self):
        covs = [self._make_cov("a.srv", 10, 10), self._make_cov("b.srv", 10, 5)]
        report = format_text_report(covs)
        self.assertIn("a.srv", report)
        self.assertIn("b.srv", report)
        self.assertIn("TOTAL", report)

    def test_show_missing(self):
        cov = CoverageData("x.srv", [""] * 5)
        cov.executable_lines = {1, 2, 3, 4, 5}
        cov.executed_lines = {1, 2}
        report = format_text_report([cov], show_missing=True)
        self.assertIn("3-5", report)

    def test_total_line_present(self):
        report = format_text_report([self._make_cov("a.srv", 5, 5)])
        self.assertIn("TOTAL", report)

    def test_header_present(self):
        report = format_text_report([self._make_cov("a.srv", 5, 5)])
        self.assertIn("File", report)
        self.assertIn("Stmts", report)
        self.assertIn("Cover", report)


class TestFormatJsonReport(unittest.TestCase):
    """Tests for format_json_report."""

    def _make_cov(self, name, total, executed):
        cov = CoverageData(name, [""] * total)
        cov.executable_lines = set(range(1, total + 1))
        cov.executed_lines = set(range(1, executed + 1))
        return cov

    def test_valid_json(self):
        report = format_json_report([self._make_cov("a.srv", 10, 10)])
        data = json.loads(report)
        self.assertIn("files", data)
        self.assertIn("totals", data)

    def test_file_data_structure(self):
        report = format_json_report([self._make_cov("test.srv", 5, 3)])
        data = json.loads(report)
        f = data["files"]["test.srv"]
        self.assertEqual(f["num_statements"], 5)
        self.assertEqual(f["num_executed"], 3)
        self.assertEqual(f["num_missing"], 2)
        self.assertEqual(f["coverage_percent"], 60.0)

    def test_missing_lines_correct(self):
        cov = CoverageData("x.srv", [""] * 5)
        cov.executable_lines = {1, 2, 3, 4, 5}
        cov.executed_lines = {1, 3, 5}
        report = format_json_report([cov])
        data = json.loads(report)
        self.assertEqual(data["files"]["x.srv"]["missing_lines"], [2, 4])

    def test_totals(self):
        covs = [self._make_cov("a.srv", 10, 8), self._make_cov("b.srv", 10, 6)]
        report = format_json_report(covs)
        data = json.loads(report)
        self.assertEqual(data["totals"]["num_statements"], 20)
        self.assertEqual(data["totals"]["num_executed"], 14)

    def test_runtime_error_included(self):
        cov = self._make_cov("err.srv", 5, 2)
        cov.runtime_error = "division by zero"
        report = format_json_report([cov])
        data = json.loads(report)
        self.assertIn("runtime_error", data["files"]["err.srv"])

    def test_branch_data_included(self):
        cov = self._make_cov("b.srv", 5, 5)
        cov.branch_total = 4
        cov.branch_taken = 3
        report = format_json_report([cov])
        data = json.loads(report)
        self.assertEqual(data["files"]["b.srv"]["branches_total"], 4)


class TestFormatHtmlReport(unittest.TestCase):
    """Tests for format_html_report."""

    def _make_cov(self, name, total, executed):
        cov = CoverageData(name, [f"line {i}" for i in range(total)])
        cov.executable_lines = set(range(1, total + 1))
        cov.executed_lines = set(range(1, executed + 1))
        return cov

    def test_valid_html(self):
        html = format_html_report([self._make_cov("a.srv", 5, 5)])
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("</html>", html)

    def test_file_name_in_html(self):
        html = format_html_report([self._make_cov("demo.srv", 3, 2)])
        self.assertIn("demo.srv", html)

    def test_hit_class_present(self):
        html = format_html_report([self._make_cov("a.srv", 3, 3)])
        self.assertIn('class="line hit"', html)

    def test_miss_class_present(self):
        cov = CoverageData("a.srv", ["x = 1", "y = 2"])
        cov.executable_lines = {1, 2}
        cov.executed_lines = {1}
        html = format_html_report([cov])
        self.assertIn('class="line miss"', html)

    def test_coverage_percent_in_html(self):
        html = format_html_report([self._make_cov("a.srv", 10, 8)])
        self.assertIn("80.0%", html)

    def test_summary_bar(self):
        html = format_html_report([self._make_cov("a.srv", 5, 5)])
        self.assertIn("summary-bar", html)

    def test_html_escaping(self):
        cov = CoverageData("test.srv", ['if x < 5'])
        cov.executable_lines = {1}
        cov.executed_lines = {1}
        html = format_html_report([cov])
        self.assertIn("&lt;", html)


class TestMergeCoverage(unittest.TestCase):
    """Tests for merge_coverage."""

    def _make_cov(self, name, exec_lines, executed):
        cov = CoverageData(name, [])
        cov.executable_lines = set(exec_lines)
        cov.executed_lines = set(executed)
        return cov

    def test_merge_new_file(self):
        cov = self._make_cov("a.srv", [1, 2, 3], [1, 2])
        result = merge_coverage(None, [cov])
        self.assertIn("a.srv", result["files"])
        self.assertEqual(result["files"]["a.srv"]["num_executed"], 2)

    def test_merge_existing_file(self):
        existing = {
            "files": {
                "a.srv": {
                    "executable_lines": [1, 2, 3],
                    "executed_lines": [1],
                    "missing_lines": [2, 3],
                    "num_statements": 3,
                    "num_executed": 1,
                    "num_missing": 2,
                    "coverage_percent": 33.33,
                }
            },
            "totals": {}
        }
        cov = self._make_cov("a.srv", [1, 2, 3], [2, 3])
        result = merge_coverage(existing, [cov])
        self.assertEqual(result["files"]["a.srv"]["num_executed"], 3)
        self.assertEqual(result["files"]["a.srv"]["coverage_percent"], 100.0)

    def test_merge_totals_updated(self):
        cov1 = self._make_cov("a.srv", [1, 2], [1])
        cov2 = self._make_cov("b.srv", [1, 2, 3], [1, 2, 3])
        result = merge_coverage(None, [cov1, cov2])
        self.assertEqual(result["totals"]["num_statements"], 5)
        self.assertEqual(result["totals"]["num_executed"], 4)

    def test_merge_preserves_existing_other_files(self):
        existing = {
            "files": {
                "old.srv": {
                    "executable_lines": [1], "executed_lines": [1],
                    "missing_lines": [], "num_statements": 1,
                    "num_executed": 1, "num_missing": 0,
                    "coverage_percent": 100.0,
                }
            },
            "totals": {}
        }
        cov = self._make_cov("new.srv", [1, 2], [1])
        result = merge_coverage(existing, [cov])
        self.assertIn("old.srv", result["files"])
        self.assertIn("new.srv", result["files"])


class TestCollectSrvFiles(unittest.TestCase):
    """Tests for collect_srv_files."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_collect_single_file(self):
        p = os.path.join(self.tmpdir, "a.srv")
        open(p, 'w').close()
        result = collect_srv_files([p])
        self.assertEqual(result, [p])

    def test_collect_from_directory(self):
        for name in ["a.srv", "b.srv", "c.txt"]:
            open(os.path.join(self.tmpdir, name), 'w').close()
        result = collect_srv_files([self.tmpdir])
        self.assertEqual(len(result), 2)

    def test_collect_nested_directory(self):
        subdir = os.path.join(self.tmpdir, "sub")
        os.makedirs(subdir)
        open(os.path.join(subdir, "deep.srv"), 'w').close()
        result = collect_srv_files([self.tmpdir])
        self.assertEqual(len(result), 1)

    def test_collect_no_srv_files(self):
        open(os.path.join(self.tmpdir, "readme.txt"), 'w').close()
        result = collect_srv_files([self.tmpdir])
        self.assertEqual(result, [])

    def test_collect_deduplicates(self):
        p = os.path.join(self.tmpdir, "a.srv")
        open(p, 'w').close()
        result = collect_srv_files([p, p, p])
        self.assertEqual(len(result), 1)

    def test_non_srv_file_ignored(self):
        result = collect_srv_files(["readme.txt"])
        self.assertEqual(result, [])


class TestLineTrackingIntegration(unittest.TestCase):
    """Tests for LineTrackingParser integration with coverage."""

    def test_parser_sets_line_numbers(self):
        code = "x = 1\ny = 2\n"
        tokens = tokenize(code)
        parser = LineTrackingParser(tokens)
        nodes = parser.parse()
        # At least one node should have a line number
        has_line = any(n.line_num is not None for n in nodes)
        self.assertTrue(has_line)

    def test_if_node_has_line(self):
        code = "x = 1\nif x == 1\n    print x\n"
        tokens = tokenize(code)
        parser = LineTrackingParser(tokens)
        nodes = parser.parse()
        if_nodes = [n for n in nodes if isinstance(n, IfNode)]
        self.assertTrue(len(if_nodes) > 0)
        self.assertIsNotNone(if_nodes[0].line_num)

    def test_function_node_has_line(self):
        code = "function greet name\n    print name\n"
        tokens = tokenize(code)
        parser = LineTrackingParser(tokens)
        nodes = parser.parse()
        fn_nodes = [n for n in nodes if isinstance(n, FunctionNode)]
        self.assertTrue(len(fn_nodes) > 0)
        self.assertIsNotNone(fn_nodes[0].line_num)


class TestCoverageInterpreter(unittest.TestCase):
    """Tests for CoverageInterpreter behavior."""

    def _run(self, code, **kwargs):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.srv',
                                          delete=False, encoding='utf-8') as f:
            f.write(code)
            f.flush()
            name = f.name
        try:
            return run_with_coverage(name, code, **kwargs)
        finally:
            os.unlink(name)

    def test_while_branch_entered(self):
        code = "x = 0\nwhile x < 2\n    x = x + 1\n"
        cov = self._run(code, track_branches=True)
        self.assertIn(2, cov.executed_lines)

    def test_while_branch_skipped(self):
        code = "x = 10\nwhile x < 2\n    x = x + 1\n"
        cov = self._run(code, track_branches=True)
        self.assertIn(2, cov.executed_lines)  # while line itself is visited
        self.assertNotIn(3, cov.executed_lines)

    def test_if_branch_tracking(self):
        code = "x = 5\nif x > 3\n    print 1\n"
        cov = self._run(code, track_branches=True)
        self.assertGreater(cov.branch_total, 0)
        self.assertGreater(cov.branch_taken, 0)

    def test_for_each_coverage(self):
        code = "items = [1, 2, 3]\nfor item in items\n    print item\n"
        cov = self._run(code)
        self.assertIn(1, cov.executed_lines)

    def test_break_in_loop(self):
        code = "x = 0\nwhile true\n    x = x + 1\n    if x == 3\n        break\nprint x\n"
        cov = self._run(code)
        self.assertIn(6, cov.executed_lines)

    def test_multiple_functions(self):
        code = ("function add a b\n    return a + b\n"
                "function mul a b\n    return a * b\n"
                "print add 1 2\n")
        cov = self._run(code)
        # mul never called
        self.assertNotIn(4, cov.executed_lines)
        self.assertIn(2, cov.executed_lines)

    def test_match_coverage(self):
        code = "x = 2\nmatch x\n    case 1\n        print 1\n    case 2\n        print 2\n    case 3\n        print 3\n"
        cov = self._run(code)
        self.assertIn(6, cov.executed_lines)
        self.assertNotIn(4, cov.executed_lines)

    def test_elif_coverage(self):
        code = "x = 5\nif x > 10\n    print 1\nelse if x > 3\n    print 2\nelse\n    print 3\n"
        cov = self._run(code)
        self.assertIn(5, cov.executed_lines)
        self.assertNotIn(3, cov.executed_lines)
        self.assertNotIn(7, cov.executed_lines)

    def test_nested_loops(self):
        code = "for i 0 to 2\n    for j 0 to 2\n        print i + j\n"
        cov = self._run(code)
        self.assertIn(1, cov.executed_lines)


class TestCLIIntegration(unittest.TestCase):
    """Tests for CLI main() behavior via subprocess."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.srv_path = os.path.join(self.tmpdir, "test_prog.srv")
        with open(self.srv_path, 'w') as f:
            f.write("x = 1\ny = 2\nprint x + y\n")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_cli_text_output(self):
        import subprocess
        script = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sauravcov.py")
        result = subprocess.run(
            [sys.executable, script, self.srv_path, "--quiet"],
            capture_output=True, text=True, timeout=15
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("TOTAL", result.stdout)
        self.assertIn("100.0%", result.stdout)

    def test_cli_json_output(self):
        import subprocess
        script = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sauravcov.py")
        result = subprocess.run(
            [sys.executable, script, self.srv_path, "--json", "--quiet"],
            capture_output=True, text=True, timeout=15
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertIn("totals", data)

    def test_cli_html_output(self):
        import subprocess
        html_path = os.path.join(self.tmpdir, "cov.html")
        script = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sauravcov.py")
        result = subprocess.run(
            [sys.executable, script, self.srv_path, "--html", html_path, "--quiet"],
            capture_output=True, text=True, timeout=15
        )
        self.assertEqual(result.returncode, 0)
        self.assertTrue(os.path.exists(html_path))

    def test_cli_min_coverage_pass(self):
        import subprocess
        script = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sauravcov.py")
        result = subprocess.run(
            [sys.executable, script, self.srv_path, "--min-coverage", "50", "--quiet"],
            capture_output=True, text=True, timeout=15
        )
        self.assertEqual(result.returncode, 0)

    def test_cli_min_coverage_fail(self):
        import subprocess
        # Write a program where some code isn't reached
        srv = os.path.join(self.tmpdir, "partial.srv")
        with open(srv, 'w') as f:
            f.write("x = 1\nif x > 10\n    print x\n    print x\n    print x\n")
        script = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sauravcov.py")
        result = subprocess.run(
            [sys.executable, script, srv, "--min-coverage", "99", "--quiet"],
            capture_output=True, text=True, timeout=15
        )
        self.assertEqual(result.returncode, 2)

    def test_cli_merge(self):
        import subprocess
        merge_path = os.path.join(self.tmpdir, "merged.json")
        script = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sauravcov.py")
        result = subprocess.run(
            [sys.executable, script, self.srv_path, "--merge", merge_path, "--quiet"],
            capture_output=True, text=True, timeout=15
        )
        self.assertEqual(result.returncode, 0)
        self.assertTrue(os.path.exists(merge_path))
        with open(merge_path) as f:
            data = json.load(f)
        self.assertIn("totals", data)

    def test_cli_show_missing(self):
        import subprocess
        script = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sauravcov.py")
        result = subprocess.run(
            [sys.executable, script, self.srv_path, "--show-missing", "--quiet"],
            capture_output=True, text=True, timeout=15
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Missing", result.stdout)


if __name__ == "__main__":
    unittest.main()
