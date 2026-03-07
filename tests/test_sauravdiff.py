#!/usr/bin/env python3
"""Tests for sauravdiff.py — semantic diff tool."""

import sys
import os
import json
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sauravdiff import (
    parse_file, compute_diff, DiffEntry,
    format_diff, format_summary, format_json,
    _node_hash, _node_signature, _statement_key, _is_noise_node,
)
from saurav import tokenize, Parser


def _parse(code):
    tokens = tokenize(code)
    return Parser(tokens).parse()


def _write_srv(content):
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.srv', delete=False, encoding='utf-8')
    f.write(content)
    f.close()
    return f.name


class TestNodeHash(unittest.TestCase):
    def test_identical_code_same_hash(self):
        a = _parse("x = 5")
        b = _parse("x = 5")
        self.assertEqual(_node_hash(a[0]), _node_hash(b[0]))

    def test_different_value_different_hash(self):
        a = _parse("x = 5")
        b = _parse("x = 10")
        self.assertNotEqual(_node_hash(a[0]), _node_hash(b[0]))

    def test_whitespace_irrelevant(self):
        a = _parse("x  =  5")
        b = _parse("x = 5")
        self.assertEqual(_node_hash(a[0]), _node_hash(b[0]))

    def test_different_vars_different_hash(self):
        a = _parse("x = 5")
        b = _parse("y = 5")
        self.assertNotEqual(_node_hash(a[0]), _node_hash(b[0]))


class TestNodeSignature(unittest.TestCase):
    def test_function_signature(self):
        nodes = _parse("function foo\n    return 1\nend")
        sig = _node_signature(nodes[0])
        self.assertEqual(sig, "FunctionNode(foo)")

    def test_assignment_signature(self):
        nodes = _parse("x = 5")
        sig = _node_signature(nodes[0])
        self.assertIn("AssignmentNode", sig)
        self.assertIn("x", sig)

    def test_number_signature(self):
        from saurav import NumberNode
        n = NumberNode(42.0)
        sig = _node_signature(n)
        self.assertIn("42.0", sig)


class TestStatementKey(unittest.TestCase):
    def test_function_key(self):
        nodes = _parse("function bar\n    return 1\nend")
        key = _statement_key(nodes[0])
        self.assertEqual(key, ('function', 'bar'))

    def test_assignment_key(self):
        nodes = _parse("x = 5")
        key = _statement_key(nodes[0])
        self.assertEqual(key, ('assign', 'x'))

    def test_print_has_no_key(self):
        nodes = _parse("print 5")
        key = _statement_key(nodes[0])
        self.assertIsNone(key)


class TestIsNoiseNode(unittest.TestCase):
    def test_end_is_noise(self):
        # Parser sometimes produces FunctionCallNode(end) at top level
        nodes = _parse("function foo\n    return 1\nend")
        noise = [n for n in nodes if _is_noise_node(n)]
        # end nodes should be detected as noise
        for n in noise:
            self.assertEqual(type(n).__name__, 'FunctionCallNode')

    def test_real_call_not_noise(self):
        nodes = _parse("print 5")
        for n in nodes:
            self.assertFalse(_is_noise_node(n))


class TestComputeDiff(unittest.TestCase):
    def test_identical(self):
        code = "x = 5\ny = 10"
        entries = compute_diff(_parse(code), _parse(code))
        for e in entries:
            self.assertEqual(e.kind, DiffEntry.UNCHANGED)

    def test_added_statement(self):
        old = _parse("x = 5")
        new = _parse("x = 5\ny = 10")
        entries = compute_diff(old, new)
        kinds = [e.kind for e in entries]
        self.assertIn(DiffEntry.ADDED, kinds)
        self.assertIn(DiffEntry.UNCHANGED, kinds)

    def test_removed_statement(self):
        old = _parse("x = 5\ny = 10")
        new = _parse("x = 5")
        entries = compute_diff(old, new)
        kinds = [e.kind for e in entries]
        self.assertIn(DiffEntry.REMOVED, kinds)

    def test_modified_statement(self):
        old = _parse("x = 5")
        new = _parse("x = 10")
        entries = compute_diff(old, new)
        kinds = [e.kind for e in entries]
        self.assertIn(DiffEntry.MODIFIED, kinds)

    def test_function_matched_by_name(self):
        old = _parse("function add a b\n    return a + b\nend")
        new = _parse("function add a b\n    return a + b + 1\nend")
        entries = compute_diff(old, new)
        modified = [e for e in entries if e.kind == DiffEntry.MODIFIED]
        self.assertEqual(len(modified), 1)
        self.assertIn("add", modified[0].signature)

    def test_function_added(self):
        old = _parse("function add a b\n    return a + b\nend")
        new = _parse("function add a b\n    return a + b\nend\nfunction mul a b\n    return a * b\nend")
        entries = compute_diff(old, new)
        added = [e for e in entries if e.kind == DiffEntry.ADDED]
        self.assertTrue(any("mul" in e.signature for e in added))

    def test_function_removed(self):
        old = _parse("function add a b\n    return a + b\nend\nfunction mul a b\n    return a * b\nend")
        new = _parse("function add a b\n    return a + b\nend")
        entries = compute_diff(old, new)
        removed = [e for e in entries if e.kind == DiffEntry.REMOVED]
        self.assertTrue(any("mul" in e.signature for e in removed))

    def test_whitespace_only_no_changes(self):
        old = _parse("x = 5\ny = 10")
        new = _parse("x   =   5\ny  =  10")
        entries = compute_diff(old, new)
        for e in entries:
            self.assertEqual(e.kind, DiffEntry.UNCHANGED)

    def test_empty_to_code(self):
        old = _parse("")
        new = _parse("x = 5")
        entries = compute_diff(old, new)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].kind, DiffEntry.ADDED)

    def test_code_to_empty(self):
        old = _parse("x = 5")
        new = _parse("")
        entries = compute_diff(old, new)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].kind, DiffEntry.REMOVED)

    def test_noise_filtered(self):
        old = _parse("function f\n    return 1\nend")
        new = _parse("function f\n    return 2\nend")
        entries = compute_diff(old, new)
        # Should not have FunctionCallNode(end) in the diff
        sigs = [e.signature for e in entries]
        for s in sigs:
            self.assertNotIn("end", s.lower().split("(")[-1] if "(" in s else "")


class TestModifiedDetails(unittest.TestCase):
    def test_details_show_change(self):
        old = _parse("x = 5")
        new = _parse("x = 99")
        entries = compute_diff(old, new)
        modified = [e for e in entries if e.kind == DiffEntry.MODIFIED]
        self.assertEqual(len(modified), 1)
        self.assertTrue(len(modified[0].details) > 0)
        self.assertTrue(any("expression" in d for d in modified[0].details))

    def test_details_for_body_change(self):
        old = _parse("function f\n    return 1\nend")
        new = _parse("function f\n    return 2\nend")
        entries = compute_diff(old, new)
        modified = [e for e in entries if e.kind == DiffEntry.MODIFIED]
        self.assertTrue(len(modified) > 0)
        self.assertTrue(any("body" in d for d in modified[0].details))


class TestFormatDiff(unittest.TestCase):
    def test_no_changes_output(self):
        entries = compute_diff(_parse("x = 5"), _parse("x = 5"))
        out = format_diff(entries, use_color=False)
        self.assertIn("unchanged", out)

    def test_added_shows_plus(self):
        entries = compute_diff(_parse(""), _parse("x = 5"))
        out = format_diff(entries, use_color=False)
        self.assertIn("+", out)
        self.assertIn("added", out)

    def test_removed_shows_minus(self):
        entries = compute_diff(_parse("x = 5"), _parse(""))
        out = format_diff(entries, use_color=False)
        self.assertIn("-", out)
        self.assertIn("removed", out)

    def test_show_unchanged(self):
        entries = compute_diff(_parse("x = 5\ny = 10"), _parse("x = 5\ny = 20"))
        out_with = format_diff(entries, use_color=False, show_unchanged=True)
        out_without = format_diff(entries, use_color=False, show_unchanged=False)
        # With --all, we should see more lines
        self.assertGreater(len(out_with.split('\n')), len(out_without.split('\n')))


class TestFormatSummary(unittest.TestCase):
    def test_no_changes(self):
        entries = compute_diff(_parse("x = 5"), _parse("x = 5"))
        summary = format_summary(entries)
        self.assertIn("No semantic changes", summary)

    def test_with_changes(self):
        entries = compute_diff(_parse("x = 5"), _parse("x = 10\ny = 20"))
        summary = format_summary(entries)
        self.assertIn("~", summary)
        self.assertIn("+", summary)

    def test_counts_correct(self):
        entries = compute_diff(_parse("x = 5\ny = 10"), _parse("x = 99"))
        summary = format_summary(entries)
        self.assertIn("-1", summary)  # y removed
        self.assertIn("~1", summary)  # x modified


class TestFormatJson(unittest.TestCase):
    def test_valid_json(self):
        entries = compute_diff(_parse("x = 5"), _parse("x = 10"))
        out = format_json(entries)
        data = json.loads(out)
        self.assertIn("summary", data)
        self.assertIn("changes", data)

    def test_summary_counts(self):
        entries = compute_diff(_parse("x = 5"), _parse("x = 10\ny = 20"))
        data = json.loads(format_json(entries))
        self.assertEqual(data["summary"]["modified"], 1)
        self.assertEqual(data["summary"]["added"], 1)

    def test_no_changes_empty_list(self):
        entries = compute_diff(_parse("x = 5"), _parse("x = 5"))
        data = json.loads(format_json(entries))
        self.assertEqual(len(data["changes"]), 0)
        self.assertEqual(data["summary"]["unchanged"], 1)

    def test_change_has_old_new(self):
        entries = compute_diff(_parse("x = 5"), _parse("x = 10"))
        data = json.loads(format_json(entries))
        change = data["changes"][0]
        self.assertIn("old", change)
        self.assertIn("new", change)


class TestParseFile(unittest.TestCase):
    def test_parse_valid_file(self):
        path = _write_srv("x = 5\nprint x")
        try:
            ast = parse_file(path)
            self.assertTrue(len(ast) > 0)
        finally:
            os.unlink(path)

    def test_parse_nonexistent_exits(self):
        with self.assertRaises(SystemExit):
            parse_file("nonexistent_file_1234.srv")


class TestEdgeCases(unittest.TestCase):
    def test_both_empty(self):
        entries = compute_diff(_parse(""), _parse(""))
        self.assertEqual(len(entries), 0)

    def test_complex_code(self):
        old = """
x = 5
y = [1, 2, 3]
function fib n
    if n < 2
        return n
    end
    return (fib (n - 1)) + (fib (n - 2))
end
print (fib 10)
"""
        new = """
x = 5
y = [1, 2, 3, 4]
function fib n
    if n < 2
        return n
    end
    return (fib (n - 1)) + (fib (n - 2))
end
function factorial n
    if n < 2
        return 1
    end
    return n * (factorial (n - 1))
end
print (fib 10)
print (factorial 5)
"""
        entries = compute_diff(_parse(old), _parse(new))
        added = [e for e in entries if e.kind == DiffEntry.ADDED]
        modified = [e for e in entries if e.kind == DiffEntry.MODIFIED]
        unchanged = [e for e in entries if e.kind == DiffEntry.UNCHANGED]

        # fib should be unchanged
        self.assertTrue(any("fib" in e.signature for e in unchanged))
        # factorial should be added
        self.assertTrue(any("factorial" in e.signature for e in added))
        # y should be modified (different list)
        self.assertTrue(any("y" in e.signature for e in modified))

    def test_reorder_functions_detected(self):
        old = "function a\n    return 1\nend\nfunction b\n    return 2\nend"
        new = "function b\n    return 2\nend\nfunction a\n    return 1\nend"
        entries = compute_diff(_parse(old), _parse(new))
        # Functions match by name, so both should be unchanged
        for e in entries:
            self.assertEqual(e.kind, DiffEntry.UNCHANGED)


if __name__ == '__main__':
    unittest.main()
