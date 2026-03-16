#!/usr/bin/env python3
"""Tests for sauravci.py — Local CI runner."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sauravci


class TestTryParseJson(unittest.TestCase):
    def test_valid_json_object(self):
        self.assertEqual(sauravci._try_parse_json('{"a": 1}'), {"a": 1})

    def test_valid_json_array(self):
        self.assertEqual(sauravci._try_parse_json('[1, 2]'), [1, 2])

    def test_json_mixed_with_text(self):
        text = 'Some output\n{"key": "val"}\nmore text'
        self.assertEqual(sauravci._try_parse_json(text), {"key": "val"})

    def test_invalid_json(self):
        self.assertIsNone(sauravci._try_parse_json('not json at all'))

    def test_empty_string(self):
        self.assertIsNone(sauravci._try_parse_json(''))


class TestParseLint(unittest.TestCase):
    def test_lint_with_issues(self):
        proc = MagicMock()
        proc.stdout = json.dumps([
            {"severity": "error", "message": "bad"},
            {"severity": "warning", "message": "meh"},
            {"severity": "style", "message": "nit"},
        ])
        proc.returncode = 1
        result = {'name': 'lint', 'errors': 0, 'warnings': 0, 'details': {}, 'status': 'skip'}
        result = sauravci._parse_lint(result, proc)
        self.assertEqual(result['errors'], 1)
        self.assertEqual(result['warnings'], 1)
        self.assertEqual(result['details']['issues'], 3)

    def test_lint_clean(self):
        proc = MagicMock()
        proc.stdout = '[]'
        proc.returncode = 0
        result = {'name': 'lint', 'errors': 0, 'warnings': 0, 'details': {}, 'status': 'skip'}
        result = sauravci._parse_lint(result, proc)
        self.assertEqual(result['errors'], 0)

    def test_lint_non_json(self):
        proc = MagicMock()
        proc.stdout = 'some error text'
        proc.returncode = 1
        result = {'name': 'lint', 'errors': 0, 'warnings': 0, 'details': {}, 'status': 'skip'}
        result = sauravci._parse_lint(result, proc)
        self.assertEqual(result['errors'], 1)


class TestParseSecurity(unittest.TestCase):
    def test_security_findings(self):
        proc = MagicMock()
        proc.stdout = json.dumps([
            {"severity": "high", "rule": "SEC001"},
            {"severity": "medium", "rule": "SEC002"},
            {"severity": "low", "rule": "SEC003"},
        ])
        proc.returncode = 1
        result = {'name': 'security', 'errors': 0, 'warnings': 0, 'details': {}, 'status': 'skip'}
        result = sauravci._parse_security(result, proc)
        self.assertEqual(result['errors'], 1)
        self.assertEqual(result['warnings'], 2)
        self.assertEqual(result['details']['high'], 1)

    def test_security_clean(self):
        proc = MagicMock()
        proc.stdout = '[]'
        proc.returncode = 0
        result = {'name': 'security', 'errors': 0, 'warnings': 0, 'details': {}, 'status': 'skip'}
        result = sauravci._parse_security(result, proc)
        self.assertEqual(result['errors'], 0)


class TestParseMetrics(unittest.TestCase):
    def test_metrics_with_score(self):
        proc = MagicMock()
        proc.stdout = json.dumps({"average_maintainability": 75, "total_loc": 1000})
        proc.returncode = 0
        result = {'name': 'metrics', 'errors': 0, 'warnings': 0, 'details': {}, 'status': 'skip'}
        result = sauravci._parse_metrics(result, proc)
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(result['details']['average_maintainability'], 75)

    def test_metrics_low_score_warns(self):
        proc = MagicMock()
        proc.stdout = json.dumps({"average_maintainability": 15})
        proc.returncode = 0
        result = {'name': 'metrics', 'errors': 0, 'warnings': 0, 'details': {}, 'status': 'skip'}
        result = sauravci._parse_metrics(result, proc)
        self.assertEqual(result['warnings'], 1)


class TestParseTest(unittest.TestCase):
    def test_test_results(self):
        proc = MagicMock()
        proc.stdout = json.dumps({"total": 10, "passed": 8, "failed": 2, "skipped": 0})
        proc.returncode = 1
        result = {'name': 'test', 'errors': 0, 'warnings': 0, 'details': {}, 'status': 'skip'}
        result = sauravci._parse_test(result, proc, '.')
        self.assertEqual(result['errors'], 2)
        self.assertEqual(result['details']['passed'], 8)

    def test_test_all_pass(self):
        proc = MagicMock()
        proc.stdout = json.dumps({"total": 5, "passed": 5, "failed": 0, "skipped": 0})
        proc.returncode = 0
        result = {'name': 'test', 'errors': 0, 'warnings': 0, 'details': {}, 'status': 'skip'}
        result = sauravci._parse_test(result, proc, '.')
        self.assertEqual(result['errors'], 0)


class TestParseTypecheck(unittest.TestCase):
    def test_typecheck_issues(self):
        proc = MagicMock()
        proc.stdout = json.dumps({"issues": [
            {"severity": "error", "msg": "type mismatch"},
            {"severity": "warning", "msg": "unused var"},
        ]})
        proc.returncode = 1
        result = {'name': 'typecheck', 'errors': 0, 'warnings': 0, 'details': {}, 'status': 'skip'}
        result = sauravci._parse_typecheck(result, proc)
        self.assertEqual(result['errors'], 1)
        self.assertEqual(result['warnings'], 1)

    def test_typecheck_clean(self):
        proc = MagicMock()
        proc.stdout = json.dumps({"issues": []})
        proc.returncode = 0
        result = {'name': 'typecheck', 'errors': 0, 'warnings': 0, 'details': {}, 'status': 'skip'}
        result = sauravci._parse_typecheck(result, proc)
        self.assertEqual(result['errors'], 0)


class TestStageNames(unittest.TestCase):
    def test_all_stages_present(self):
        self.assertEqual(sauravci.STAGE_NAMES, ['lint', 'typecheck', 'security', 'metrics', 'test'])

    def test_stages_have_required_fields(self):
        for s in sauravci.STAGES:
            self.assertIn('name', s)
            self.assertIn('label', s)
            self.assertIn('description', s)
            self.assertIn('command', s)
            self.assertIn('tool', s)


class TestColorHelper(unittest.TestCase):
    def test_color_enabled(self):
        result = sauravci._c('hello', 'green', True)
        self.assertIn('\033[32m', result)
        self.assertIn('hello', result)

    def test_color_disabled(self):
        result = sauravci._c('hello', 'green', False)
        self.assertEqual(result, 'hello')


class TestListStages(unittest.TestCase):
    def test_list_stages_exits_zero(self):
        ret = sauravci.main(['--list-stages'])
        self.assertEqual(ret, 0)


class TestHtmlGeneration(unittest.TestCase):
    def test_html_contains_stages(self):
        results = [
            {'name': 'lint', 'label': 'Lint', 'description': 'Static analysis',
             'status': 'pass', 'duration': 1.0, 'output': '', 'errors': 0, 'warnings': 0, 'details': {}},
            {'name': 'test', 'label': 'Tests', 'description': 'Test suite',
             'status': 'fail', 'duration': 2.0, 'output': 'FAIL: test_x', 'errors': 1, 'warnings': 0,
             'details': {'total': 5, 'passed': 4, 'failed': 1, 'skipped': 0}},
        ]
        html = sauravci.generate_html(results, 3.0, ['.'])
        self.assertIn('sauravci Report', html)
        self.assertIn('Lint', html)
        self.assertIn('FAILED', html)
        self.assertIn('1 errors', html)

    def test_html_all_pass(self):
        results = [
            {'name': 'lint', 'label': 'Lint', 'description': 'x',
             'status': 'pass', 'duration': 0.5, 'output': '', 'errors': 0, 'warnings': 0, 'details': {}},
        ]
        html = sauravci.generate_html(results, 0.5, ['.'])
        self.assertIn('PASSED', html)


class TestConfigLoading(unittest.TestCase):
    def test_load_valid_config(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({'skip': ['metrics'], 'strict': True}, f)
            f.flush()
            config = sauravci.load_config(f.name)
        os.unlink(f.name)
        self.assertEqual(config['skip'], ['metrics'])
        self.assertTrue(config['strict'])

    def test_load_missing_config(self):
        config = sauravci.load_config('/nonexistent/config.json')
        self.assertEqual(config, {})

    def test_load_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('not json{{{')
            f.flush()
            config = sauravci.load_config(f.name)
        os.unlink(f.name)
        self.assertEqual(config, {})


class TestMainSkipOnly(unittest.TestCase):
    @patch('sauravci.run_stage')
    def test_skip_stages(self, mock_run):
        mock_run.return_value = {
            'name': 'test', 'label': 'Tests', 'description': 'x',
            'status': 'pass', 'duration': 0.1, 'output': '',
            'errors': 0, 'warnings': 0, 'details': {},
        }
        ret = sauravci.main(['--skip', 'lint,typecheck,security,metrics', '--no-color', '.'])
        self.assertEqual(ret, 0)
        # Only test stage should run
        self.assertEqual(mock_run.call_count, 1)
        called_stage = mock_run.call_args[0][0]
        self.assertEqual(called_stage['name'], 'test')

    @patch('sauravci.run_stage')
    def test_only_stages(self, mock_run):
        mock_run.return_value = {
            'name': 'lint', 'label': 'Lint', 'description': 'x',
            'status': 'pass', 'duration': 0.1, 'output': '',
            'errors': 0, 'warnings': 0, 'details': {},
        }
        ret = sauravci.main(['--only', 'lint', '--no-color', '.'])
        self.assertEqual(ret, 0)
        self.assertEqual(mock_run.call_count, 1)

    @patch('sauravci.run_stage')
    def test_failure_exit_code(self, mock_run):
        mock_run.return_value = {
            'name': 'lint', 'label': 'Lint', 'description': 'x',
            'status': 'fail', 'duration': 0.1, 'output': 'error',
            'errors': 3, 'warnings': 0, 'details': {},
        }
        ret = sauravci.main(['--only', 'lint', '--no-color', '.'])
        self.assertEqual(ret, 1)


class TestJsonOutput(unittest.TestCase):
    @patch('sauravci.run_stage')
    def test_json_output(self, mock_run):
        mock_run.return_value = {
            'name': 'lint', 'label': 'Lint', 'description': 'x',
            'status': 'pass', 'duration': 0.5, 'output': '',
            'errors': 0, 'warnings': 0, 'details': {},
        }
        from io import StringIO
        with patch('sys.stdout', new_callable=StringIO) as mock_out:
            ret = sauravci.main(['--only', 'lint', '--json', '.'])
        output = mock_out.getvalue()
        data = json.loads(output)
        self.assertEqual(data['overall'], 'pass')
        self.assertEqual(len(data['stages']), 1)
        self.assertEqual(ret, 0)


class TestHtmlFileOutput(unittest.TestCase):
    @patch('sauravci.run_stage')
    def test_html_file_created(self, mock_run):
        mock_run.return_value = {
            'name': 'lint', 'label': 'Lint', 'description': 'x',
            'status': 'pass', 'duration': 0.3, 'output': '',
            'errors': 0, 'warnings': 0, 'details': {},
        }
        with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as f:
            html_path = f.name
        try:
            ret = sauravci.main(['--only', 'lint', '--html', html_path, '--no-color', '.'])
            self.assertEqual(ret, 0)
            content = Path(html_path).read_text(encoding='utf-8')
            self.assertIn('sauravci Report', content)
        finally:
            os.unlink(html_path)


class TestNoStages(unittest.TestCase):
    def test_no_stages_returns_2(self):
        ret = sauravci.main(['--only', 'nonexistent', '--no-color'])
        self.assertEqual(ret, 2)


class TestFindTool(unittest.TestCase):
    def test_find_existing_tool(self):
        tool_dir = str(Path(__file__).resolve().parent.parent)
        result = sauravci._find_tool('sauravci.py', tool_dir)
        self.assertIsNotNone(result)

    def test_find_nonexistent_tool(self):
        result = sauravci._find_tool('nonexistent_tool.py', '/tmp')
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
