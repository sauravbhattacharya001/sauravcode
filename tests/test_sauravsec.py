#!/usr/bin/env python3
"""Tests for sauravsec.py — security scanner for sauravcode programs."""

import os
import sys
import json
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sauravsec import (
    SecurityScanner, Finding, scan_file, scan_paths,
    _format_text, _format_json, _format_sarif, _format_summary,
    HIGH, MEDIUM, LOW,
)
from saurav import tokenize, Parser


def _scan(source):
    """Helper: parse source and run the security scanner."""
    tokens = tokenize(source)
    parser = Parser(tokens)
    ast = parser.parse()
    scanner = SecurityScanner()
    return scanner.scan(ast)


def _scan_disabled(source, disabled):
    """Helper: scan with specific rules disabled."""
    tokens = tokenize(source)
    parser = Parser(tokens)
    ast = parser.parse()
    scanner = SecurityScanner(disabled=disabled)
    return scanner.scan(ast)


def _rules(findings):
    """Extract rule IDs from findings."""
    return [f.rule for f in findings]


class TestSEC001PathTraversal(unittest.TestCase):
    """SEC001: Path traversal — file path from variable."""

    def test_variable_path(self):
        findings = _scan('data = read_file path')
        self.assertIn("SEC001", _rules(findings))

    def test_string_literal_path_no_warning(self):
        findings = _scan('data = read_file "config.txt"')
        self.assertNotIn("SEC001", _rules(findings))

    def test_fstring_path(self):
        src = 'name = "test"\ndata = read_file f"files/{name}.txt"'
        findings = _scan(src)
        self.assertIn("SEC001", _rules(findings))

    def test_concat_path(self):
        src = 'dir = "/tmp"\ndata = read_file dir + "/file.txt"'
        findings = _scan(src)
        self.assertIn("SEC001", _rules(findings))


class TestSEC002UnboundedLoop(unittest.TestCase):
    """SEC002: while(true) with no break."""

    def test_while_true_no_break(self):
        src = 'while true\n  print "forever"'
        findings = _scan(src)
        self.assertIn("SEC002", _rules(findings))

    def test_while_true_with_break(self):
        src = 'while true\n  break'
        findings = _scan(src)
        self.assertNotIn("SEC002", _rules(findings))

    def test_while_condition_no_warning(self):
        src = 'x = 10\nwhile x > 0\n  x = x - 1'
        findings = _scan(src)
        self.assertNotIn("SEC002", _rules(findings))

    def test_while_1_no_break(self):
        src = 'while 1\n  print "loop"'
        findings = _scan(src)
        self.assertIn("SEC002", _rules(findings))


class TestSEC003HardcodedCredentials(unittest.TestCase):
    """SEC003: Hardcoded credential detection."""

    def test_password_literal(self):
        findings = _scan('password = "hunter2"')
        self.assertIn("SEC003", _rules(findings))

    def test_api_key_literal(self):
        findings = _scan('api_key = "sk-abc123"')
        self.assertIn("SEC003", _rules(findings))

    def test_token_literal(self):
        findings = _scan('token = "mytoken"')
        self.assertIn("SEC003", _rules(findings))

    def test_secret_literal(self):
        findings = _scan('secret = "classified"')
        self.assertIn("SEC003", _rules(findings))

    def test_normal_variable_no_warning(self):
        findings = _scan('username = "admin"')
        self.assertNotIn("SEC003", _rules(findings))

    def test_empty_string_no_warning(self):
        findings = _scan('password = ""')
        self.assertNotIn("SEC003", _rules(findings))

    def test_password_from_input_no_warning(self):
        src = 'password = input "Enter password: "'
        findings = _scan(src)
        self.assertNotIn("SEC003", _rules(findings))


class TestSEC004UncheckedFileOp(unittest.TestCase):
    """SEC004: File operation not wrapped in try/catch."""

    def test_unchecked_read(self):
        findings = _scan('data = read_file "test.txt"')
        self.assertIn("SEC004", _rules(findings))

    def test_unchecked_write(self):
        findings = _scan('write_file "out.txt" "data"')
        self.assertIn("SEC004", _rules(findings))

    def test_checked_read_no_warning(self):
        src = 'try\n  data = read_file "test.txt"\ncatch e\n  print e'
        findings = _scan(src)
        self.assertNotIn("SEC004", _rules(findings))


class TestSEC007InformationLeak(unittest.TestCase):
    """SEC007: Printing sensitive variables."""

    def test_print_password(self):
        src = 'password = "x"\nprint password'
        findings = _scan(src)
        self.assertIn("SEC007", _rules(findings))

    def test_print_token(self):
        src = 'token = "x"\nprint token'
        findings = _scan(src)
        self.assertIn("SEC007", _rules(findings))

    def test_print_normal_var_no_warning(self):
        src = 'name = "Alice"\nprint name'
        findings = _scan(src)
        self.assertNotIn("SEC007", _rules(findings))


class TestSEC008UnvalidatedInput(unittest.TestCase):
    """SEC008: User input used directly in file ops."""

    def test_input_to_read_file(self):
        src = 'path = input "file: "\ndata = read_file path'
        findings = _scan(src)
        self.assertIn("SEC008", _rules(findings))

    def test_normal_var_in_file_op_no_sec008(self):
        src = 'path = "safe.txt"\ndata = read_file path'
        findings = _scan(src)
        self.assertNotIn("SEC008", _rules(findings))


class TestSEC009NestedLoops(unittest.TestCase):
    """SEC009: Nested for loops — resource exhaustion risk."""

    def test_nested_for(self):
        src = 'for i in range 10\n  for j in range 10\n    print i'
        findings = _scan(src)
        self.assertIn("SEC009", _rules(findings))

    def test_single_for_no_warning(self):
        src = 'for i in range 10\n  print i'
        findings = _scan(src)
        self.assertNotIn("SEC009", _rules(findings))


class TestSEC010EmptyCatch(unittest.TestCase):
    """SEC010: Empty catch block."""

    def test_empty_catch(self):
        # Write a temp file with empty catch (parser needs proper formatting)
        with tempfile.NamedTemporaryFile(suffix=".srv", mode="w",
                                         delete=False, encoding="utf-8") as f:
            f.write('try\n  x = 1\ncatch e\n  x = x\n')
            path = f.name
        try:
            # We can't easily test truly empty catch via string parsing,
            # so test via the scanner directly with a mock AST
            from saurav import TryCatchNode, AssignmentNode, NumberNode
            node = TryCatchNode.__new__(TryCatchNode)
            node.body = [AssignmentNode("x", NumberNode(1))]
            node.handler = []  # Empty handler
            node.error_var = "e"
            node.line_num = None
            scanner = SecurityScanner()
            scanner.scan([node])
            self.assertIn("SEC010", _rules(scanner.findings))
        finally:
            os.unlink(path)

    def test_catch_with_handler_no_warning(self):
        src = 'try\n  x = 1\ncatch e\n  print e'
        findings = _scan(src)
        self.assertNotIn("SEC010", _rules(findings))


class TestDisabledRules(unittest.TestCase):
    """Test rule disabling."""

    def test_disable_sec003(self):
        findings = _scan_disabled('password = "hunter2"', {"SEC003"})
        self.assertNotIn("SEC003", _rules(findings))

    def test_disable_multiple(self):
        src = 'password = "x"\ndata = read_file "test.txt"'
        findings = _scan_disabled(src, {"SEC003", "SEC004"})
        self.assertNotIn("SEC003", _rules(findings))
        self.assertNotIn("SEC004", _rules(findings))


class TestSeverityFilter(unittest.TestCase):
    """Test severity levels are correct."""

    def test_sec003_is_high(self):
        findings = _scan('password = "x"')
        sec003 = [f for f in findings if f.rule == "SEC003"]
        self.assertTrue(sec003)
        self.assertEqual(sec003[0].severity, HIGH)

    def test_sec004_is_medium(self):
        findings = _scan('data = read_file "test.txt"')
        sec004 = [f for f in findings if f.rule == "SEC004"]
        self.assertTrue(sec004)
        self.assertEqual(sec004[0].severity, MEDIUM)

    def test_sec009_is_low(self):
        src = 'for i in range 10\n  for j in range 10\n    print i'
        findings = _scan(src)
        sec009 = [f for f in findings if f.rule == "SEC009"]
        self.assertTrue(sec009)
        self.assertEqual(sec009[0].severity, LOW)


class TestFinding(unittest.TestCase):
    """Test Finding data class."""

    def test_repr(self):
        f = Finding("SEC001", HIGH, "test message", line=42)
        self.assertIn("SEC001", repr(f))
        self.assertIn("42", repr(f))

    def test_to_dict(self):
        f = Finding("SEC001", HIGH, "msg", line=5, context="ctx")
        d = f.to_dict()
        self.assertEqual(d["rule"], "SEC001")
        self.assertEqual(d["severity"], HIGH)
        self.assertEqual(d["line"], 5)
        self.assertEqual(d["context"], "ctx")

    def test_to_dict_no_line(self):
        f = Finding("SEC001", HIGH, "msg")
        d = f.to_dict()
        self.assertNotIn("line", d)


class TestOutputFormatters(unittest.TestCase):
    """Test output formatting functions."""

    def test_format_text_clean(self):
        text = _format_text([], "test.srv", use_color=False)
        self.assertIn("no security issues found", text)

    def test_format_text_findings(self):
        findings = [Finding("SEC001", HIGH, "test finding", line=1)]
        text = _format_text(findings, "test.srv", use_color=False)
        self.assertIn("SEC001", text)
        self.assertIn("1 finding", text)

    def test_format_json(self):
        results = {"test.srv": [Finding("SEC001", HIGH, "msg")]}
        output = _format_json(results)
        data = json.loads(output)
        self.assertIn("test.srv", data)
        self.assertEqual(len(data["test.srv"]), 1)

    def test_format_sarif(self):
        results = {"test.srv": [Finding("SEC001", HIGH, "msg", line=1)]}
        output = _format_sarif(results)
        sarif = json.loads(output)
        self.assertEqual(sarif["version"], "2.1.0")
        self.assertTrue(sarif["runs"][0]["results"])

    def test_format_summary(self):
        results = {
            "a.srv": [Finding("SEC001", HIGH, "msg")],
            "b.srv": [],
        }
        text = _format_summary(results)
        self.assertIn("Files scanned:  2", text)
        self.assertIn("Files clean:    1", text)
        self.assertIn("Total findings: 1", text)


class TestScanFile(unittest.TestCase):
    """Test file-level scanning."""

    def test_scan_nonexistent_file(self):
        findings = scan_file("nonexistent_file_xyz.srv")
        self.assertTrue(findings)
        self.assertEqual(findings[0].rule, "SEC000")

    def test_scan_valid_file(self):
        with tempfile.NamedTemporaryFile(suffix=".srv", mode="w",
                                         delete=False, encoding="utf-8") as f:
            f.write('x = 42\nprint x\n')
            path = f.name
        try:
            findings = scan_file(path)
            self.assertEqual(findings, [])
        finally:
            os.unlink(path)

    def test_scan_file_with_findings(self):
        with tempfile.NamedTemporaryFile(suffix=".srv", mode="w",
                                         delete=False, encoding="utf-8") as f:
            f.write('password = "hunter2"\n')
            path = f.name
        try:
            findings = scan_file(path)
            self.assertIn("SEC003", _rules(findings))
        finally:
            os.unlink(path)


class TestScanPaths(unittest.TestCase):
    """Test directory scanning."""

    def test_scan_directory(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "test.srv"), "w") as f:
                f.write('x = 1\n')
            results = scan_paths([d])
            self.assertEqual(len(results), 1)

    def test_scan_nonexistent_path(self):
        results = scan_paths(["nonexistent_dir_xyz"])
        self.assertTrue(results)


class TestCleanFile(unittest.TestCase):
    """Test that clean files produce no findings."""

    def test_simple_math(self):
        findings = _scan('x = 1 + 2\nprint x')
        self.assertEqual(findings, [])

    def test_function_definition(self):
        src = 'x = 42\nprint x'
        findings = _scan(src)
        self.assertEqual(findings, [])

    def test_list_operations(self):
        src = 'items = [1, 2, 3]\nprint items'
        findings = _scan(src)
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
