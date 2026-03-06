"""Tests for sauravcov.py — code coverage tool for sauravcode."""

import os
import sys
import json
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sauravcov import (
    CoverageData, CoverageCollector, CoverageReporter, run_coverage,
    LineTrackingParser
)
from saurav import tokenize


class TestCoverageData(unittest.TestCase):
    """Test the CoverageData storage class."""

    def _make_data(self, n_lines=10):
        return CoverageData(['line ' + str(i) for i in range(n_lines)], 'test.srv')

    def test_record_line(self):
        d = self._make_data()
        d.register_executable(1)
        d.register_executable(2)
        d.record_line(1)
        self.assertEqual(d.line_hits[1], 1)
        d.record_line(1)
        self.assertEqual(d.line_hits[1], 2)

    def test_hit_and_missed_lines(self):
        d = self._make_data()
        d.register_executable(1)
        d.register_executable(2)
        d.register_executable(3)
        d.record_line(1)
        d.record_line(3)
        self.assertEqual(d.hit_lines, {1, 3})
        self.assertEqual(d.missed_lines, {2})

    def test_coverage_pct_full(self):
        d = self._make_data()
        d.register_executable(1)
        d.register_executable(2)
        d.record_line(1)
        d.record_line(2)
        self.assertAlmostEqual(d.line_coverage_pct, 100.0)

    def test_coverage_pct_partial(self):
        d = self._make_data()
        d.register_executable(1)
        d.register_executable(2)
        d.record_line(1)
        self.assertAlmostEqual(d.line_coverage_pct, 50.0)

    def test_coverage_pct_empty(self):
        d = self._make_data()
        self.assertAlmostEqual(d.line_coverage_pct, 100.0)

    def test_uncovered_ranges_contiguous(self):
        d = self._make_data()
        for i in range(1, 8):
            d.register_executable(i)
        d.record_line(1)
        d.record_line(2)
        d.record_line(7)
        ranges = d.uncovered_ranges()
        self.assertEqual(ranges, [(3, 6)])

    def test_uncovered_ranges_multiple(self):
        d = self._make_data()
        for i in [1, 2, 3, 5, 6, 8]:
            d.register_executable(i)
        d.record_line(1)
        d.record_line(5)
        ranges = d.uncovered_ranges()
        self.assertIn((2, 3), ranges)
        self.assertIn((6, 6), ranges)
        self.assertIn((8, 8), ranges)

    def test_uncovered_ranges_empty(self):
        d = self._make_data()
        d.register_executable(1)
        d.record_line(1)
        self.assertEqual(d.uncovered_ranges(), [])

    def test_record_line_none(self):
        d = self._make_data()
        d.record_line(None)
        self.assertEqual(len(d.line_hits), 0)

    def test_register_function(self):
        d = self._make_data()
        d.register_function('foo', {1, 2, 3})
        self.assertEqual(d.function_lines['foo'], {1, 2, 3})
        self.assertEqual(d.function_hits['foo'], set())

    def test_record_function_line(self):
        d = self._make_data()
        d.register_function('foo', {1, 2})
        d.record_function_line('foo', 1)
        self.assertEqual(d.function_hits['foo'], {1})

    def test_branch_coverage_pct(self):
        d = self._make_data()
        d.branches.add((1, 'true'))
        d.branches.add((1, 'false'))
        d.branch_hits[(1, 'true')] = 1
        self.assertAlmostEqual(d.branch_coverage_pct, 50.0)

    def test_branch_coverage_pct_empty(self):
        d = self._make_data()
        self.assertAlmostEqual(d.branch_coverage_pct, 100.0)


class TestLineTrackingParser(unittest.TestCase):
    """Test that LineTrackingParser tags nodes with line numbers."""

    def test_nodes_have_line_numbers(self):
        code = "x = 5\nprint x"
        tokens = tokenize(code)
        parser = LineTrackingParser(tokens)
        ast = parser.parse()
        self.assertTrue(len(ast) >= 2)
        self.assertEqual(ast[0].line_num, 1)
        self.assertEqual(ast[1].line_num, 2)

    def test_function_has_line_number(self):
        code = "function foo x\n    return x"
        tokens = tokenize(code)
        parser = LineTrackingParser(tokens)
        ast = parser.parse()
        self.assertEqual(ast[0].line_num, 1)


class TestRunCoverage(unittest.TestCase):
    """Integration tests running actual .srv programs."""

    def _run_code(self, code):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.srv',
                                         delete=False, encoding='utf-8') as f:
            f.write(code)
            f.flush()
            fname = f.name
        try:
            return run_coverage(fname, quiet=True)
        finally:
            os.unlink(fname)

    def test_simple_assignment(self):
        data = self._run_code("x = 5\ny = 10\nprint x + y")
        self.assertGreater(data.line_coverage_pct, 0)
        self.assertIn(1, data.hit_lines)

    def test_function_call(self):
        code = "function add a b\n    return a + b\nadd 3 5"
        data = self._run_code(code)
        self.assertGreater(len(data.hit_lines), 0)

    def test_uncalled_function(self):
        code = "function foo x\n    return x\nx = 5"
        data = self._run_code(code)
        # foo is defined but never called
        self.assertLess(data.line_coverage_pct, 100.0)

    def test_if_branch(self):
        code = "x = 5\nif x > 3\n    print x"
        data = self._run_code(code)
        self.assertIn(3, data.hit_lines)

    def test_if_else_branch(self):
        code = "x = 5\nif x > 10\n    print x\nelse\n    print 0"
        data = self._run_code(code)
        # Only the else branch runs
        self.assertIn(5, data.hit_lines)

    def test_while_loop(self):
        code = "i = 0\nwhile i < 3\n    i = i + 1"
        data = self._run_code(code)
        self.assertGreater(data.line_hits.get(3, 0), 1)

    def test_for_loop(self):
        code = "for i 0 3\n    print i"
        data = self._run_code(code)
        self.assertGreater(len(data.hit_lines), 0)

    def test_100_percent_coverage(self):
        code = "x = 5\nprint x"
        data = self._run_code(code)
        self.assertAlmostEqual(data.line_coverage_pct, 100.0)

    def test_per_function_tracking(self):
        code = ("function add a b\n    return a + b\n"
                "function unused x\n    return x\n"
                "add 1 2")
        data = self._run_code(code)
        self.assertIn('add', data.function_lines)
        self.assertIn('unused', data.function_lines)

    def test_error_handling(self):
        """Programs that raise errors still produce coverage."""
        code = "x = 5\nprint x\nprint y"  # y is undefined
        data = self._run_code(code)
        self.assertGreater(len(data.hit_lines), 0)


class TestCoverageReporter(unittest.TestCase):
    """Test report formatting."""

    def _make_data(self):
        d = CoverageData(['line1', 'line2', 'line3', 'line4', 'line5'],
                         'test.srv')
        d.register_executable(1)
        d.register_executable(2)
        d.register_executable(3)
        d.register_executable(4)
        d.record_line(1)
        d.record_line(2)
        d.record_line(3)
        return d

    def test_format_summary(self):
        d = self._make_data()
        r = CoverageReporter(d, use_color=False)
        report = r.format_summary()
        self.assertIn('Coverage Report', report)
        self.assertIn('75.0%', report)
        self.assertIn('3/4', report)

    def test_format_summary_with_functions(self):
        d = self._make_data()
        d.register_function('foo', {1, 2})
        d.record_function_line('foo', 1)
        r = CoverageReporter(d, use_color=False)
        report = r.format_summary()
        self.assertIn('foo', report)

    def test_format_annotated(self):
        d = self._make_data()
        r = CoverageReporter(d, use_color=False)
        report = r.format_annotated()
        self.assertIn('Annotated Source', report)
        self.assertIn('line1', report)
        self.assertIn('!', report)  # uncovered marker

    def test_to_json(self):
        d = self._make_data()
        r = CoverageReporter(d, use_color=False)
        j = json.loads(r.to_json())
        self.assertEqual(j['filename'], 'test.srv')
        self.assertAlmostEqual(j['line_coverage_pct'], 75.0)
        self.assertEqual(j['covered_lines'], 3)
        self.assertIn(4, j['missed_lines'])

    def test_to_json_with_branches(self):
        d = self._make_data()
        d.branches.add((1, 'true'))
        d.branch_hits[(1, 'true')] = 1
        r = CoverageReporter(d, use_color=False)
        j = json.loads(r.to_json(include_branches=True))
        self.assertIn('branch_coverage_pct', j)

    def test_to_html(self):
        d = self._make_data()
        r = CoverageReporter(d, use_color=False)
        html = r.to_html()
        self.assertIn('<!DOCTYPE html>', html)
        self.assertIn('Coverage Report', html)
        self.assertIn('75.0%', html)
        self.assertIn('covered', html)
        self.assertIn('uncovered', html)

    def test_uncovered_ranges_in_summary(self):
        d = self._make_data()
        r = CoverageReporter(d, use_color=False)
        report = r.format_summary()
        self.assertIn('Line 4', report)

    def test_color_grading(self):
        r = CoverageReporter(self._make_data(), use_color=True)
        # 90+ = green
        self.assertIn('92m', r._pct_color(95))
        # 70-89 = yellow
        self.assertIn('93m', r._pct_color(80))
        # <70 = red
        self.assertIn('91m', r._pct_color(50))

    def test_bar_rendering(self):
        r = CoverageReporter(self._make_data(), use_color=False)
        bar = r._bar(50, width=10)
        self.assertEqual(len(bar), 10)


class TestRunCoverageFile(unittest.TestCase):
    """Test run_coverage with actual test files."""

    def test_test_srv(self):
        test_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'test.srv')
        if not os.path.isfile(test_file):
            self.skipTest('test.srv not found')
        data = run_coverage(test_file, quiet=True)
        self.assertGreater(data.line_coverage_pct, 0)
        self.assertGreater(len(data.executable_lines), 0)

    def test_test_all_srv(self):
        test_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'test_all.srv')
        if not os.path.isfile(test_file):
            self.skipTest('test_all.srv not found')
        data = run_coverage(test_file, quiet=True)
        self.assertGreater(data.line_coverage_pct, 0)
        self.assertGreater(len(data.function_lines), 0)


if __name__ == '__main__':
    unittest.main()
