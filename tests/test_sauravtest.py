"""Tests for sauravtest.py — the sauravcode test runner."""

import os
import sys
import tempfile
import pytest

_script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _script_dir)

from sauravtest import TestRunner


@pytest.fixture
def tmp_test_dir(tmp_path):
    """Create temporary directory with sample test files."""
    # Passing test file
    (tmp_path / "test_pass.srv").write_text(
        'function test_basic\n'
        '    x = 42\n'
        '    assert x == 42\n'
        '\n'
        'function test_strings\n'
        '    s = "hello"\n'
        '    assert len(s) == 5\n'
    )

    # Failing test file
    (tmp_path / "test_fail.srv").write_text(
        'function test_will_fail\n'
        '    assert 1 == 2 "one should not equal two"\n'
    )

    # Non-test file (should be skipped by default pattern)
    (tmp_path / "helpers.srv").write_text(
        'function helper\n'
        '    return 42\n'
    )

    return tmp_path


class TestTestRunner:
    def test_discover(self, tmp_test_dir):
        runner = TestRunner()
        files = runner.discover([str(tmp_test_dir)])
        names = [os.path.basename(f) for f in files]
        assert "test_pass.srv" in names
        assert "test_fail.srv" in names
        assert "helpers.srv" not in names

    def test_discover_all_pattern(self, tmp_test_dir):
        runner = TestRunner()
        files = runner.discover([str(tmp_test_dir)], pattern="*.srv")
        names = [os.path.basename(f) for f in files]
        assert "helpers.srv" in names

    def test_passing_tests(self, tmp_test_dir):
        runner = TestRunner()
        files = runner.discover([str(tmp_test_dir)], pattern="test_pass.srv")
        success = runner.run_all(files)
        assert success is True
        assert len(runner.results) == 2
        assert all(r.passed for r in runner.results)

    def test_failing_tests(self, tmp_test_dir):
        runner = TestRunner()
        files = runner.discover([str(tmp_test_dir)], pattern="test_fail.srv")
        success = runner.run_all(files)
        assert success is False
        assert any(not r.passed for r in runner.results)

    def test_filter(self, tmp_test_dir):
        runner = TestRunner(filter_pattern="strings")
        files = runner.discover([str(tmp_test_dir)], pattern="test_pass.srv")
        runner.run_all(files)
        assert len(runner.results) == 1
        assert runner.results[0].name == "test_strings"

    def test_fail_fast(self, tmp_test_dir):
        runner = TestRunner(fail_fast=True)
        files = runner.discover([str(tmp_test_dir)], pattern="test_fail.srv")
        success = runner.run_all(files)
        assert success is False
        failed = [r for r in runner.results if not r.passed]
        assert len(failed) == 1

    def test_empty_dir(self, tmp_path):
        runner = TestRunner()
        files = runner.discover([str(tmp_path)])
        success = runner.run_all(files)
        assert success is True

    def test_specific_file(self, tmp_test_dir):
        runner = TestRunner()
        filepath = str(tmp_test_dir / "test_pass.srv")
        files = runner.discover([filepath])
        assert len(files) == 1
        success = runner.run_all(files)
        assert success is True
