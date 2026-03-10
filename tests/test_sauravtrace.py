#!/usr/bin/env python3
"""Tests for sauravtrace — execution tracer."""

import json
import os
import sys
import unittest

_dir = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_dir)
sys.path.insert(0, _root)

from sauravtrace import run_trace, TracingInterpreter, TraceEvent, _safe_repr


class TestTraceBasic(unittest.TestCase):
    """Test basic tracing of simple programs."""

    def test_trace_assignment(self):
        interp, _ = run_trace('x = 42')
        events = interp.trace
        assigns = [e for e in events if e.kind == 'assign']
        self.assertGreaterEqual(len(assigns), 1)
        self.assertIn('x', assigns[0].detail)

    def test_trace_print(self):
        interp, output = run_trace('print "hello"')
        prints = [e for e in interp.trace if e.kind == 'print']
        self.assertGreaterEqual(len(prints), 1)
        self.assertIn('hello', output)

    def test_trace_multiple_statements(self):
        code = 'x = 1\ny = 2\nprint x + y'
        interp, output = run_trace(code)
        self.assertGreaterEqual(len(interp.trace), 3)
        self.assertIn('3', output)

    def test_trace_function_def_and_call(self):
        code = 'function add a b\n    return a + b\nprint add 3 4'
        interp, output = run_trace(code)
        calls = [e for e in interp.trace if e.kind == 'call']
        returns = [e for e in interp.trace if e.kind == 'return']
        self.assertGreaterEqual(len(calls), 1)
        self.assertGreaterEqual(len(returns), 1)
        self.assertIn('7', output)

    def test_trace_if_statement(self):
        code = 'x = 5\nif x > 3\n    print "big"\nelse\n    print "small"'
        interp, output = run_trace(code)
        stmts = [e for e in interp.trace if e.kind == 'statement']
        self.assertTrue(any('if' in e.detail for e in stmts))
        self.assertIn('big', output)

    def test_trace_while_loop(self):
        code = 'i = 0\nwhile i < 3\n    i = i + 1\nprint i'
        interp, output = run_trace(code)
        self.assertIn('3', output)
        assigns = [e for e in interp.trace if e.kind == 'assign']
        self.assertGreaterEqual(len(assigns), 2)  # initial + loop iterations

    def test_trace_empty_program(self):
        interp, output = run_trace('')
        self.assertEqual(len(interp.trace), 0)
        self.assertEqual(output, '')


class TestTraceOptions(unittest.TestCase):
    """Test trace options (vars, calls_only, no_builtins, limit)."""

    def test_track_vars(self):
        code = 'x = 10\ny = 20\nprint x + y'
        interp, _ = run_trace(code, track_vars=True)
        var_events = [e for e in interp.trace if e.variables is not None]
        self.assertGreater(len(var_events), 0)
        # The print event should have both x and y in scope
        print_events = [e for e in interp.trace if e.kind == 'print' and e.variables]
        self.assertGreater(len(print_events), 0)
        self.assertIn('x', print_events[0].variables)

    def test_calls_only(self):
        code = 'x = 1\nfunction f\n    return 42\nprint f'
        interp, _ = run_trace(code, calls_only=True)
        kinds = set(e.kind for e in interp.trace)
        # Should only have call and return, no assign/print/statement
        self.assertFalse(kinds & {'assign', 'print', 'statement'})

    def test_no_builtins(self):
        code = 'print type_of 42'
        interp_with, _ = run_trace(code, no_builtins=False)
        interp_without, _ = run_trace(code, no_builtins=True)
        calls_with = [e for e in interp_with.trace if e.kind == 'call']
        calls_without = [e for e in interp_without.trace if e.kind == 'call']
        self.assertGreater(len(calls_with), len(calls_without))

    def test_limit(self):
        code = 'i = 0\nwhile i < 100\n    i = i + 1'
        interp, _ = run_trace(code, limit=10)
        self.assertLessEqual(len(interp.trace), 10)

    def test_limit_one(self):
        code = 'x = 1\ny = 2\nprint x'
        interp, _ = run_trace(code, limit=1)
        self.assertEqual(len(interp.trace), 1)


class TestTraceSummary(unittest.TestCase):
    """Test execution summary statistics."""

    def test_summary_keys(self):
        interp, _ = run_trace('x = 1\nprint x')
        s = interp.summary()
        expected_keys = ['total_steps', 'function_calls', 'assignments',
                         'prints', 'max_depth', 'unique_variables', 'trace_events']
        for key in expected_keys:
            self.assertIn(key, s)

    def test_summary_counts(self):
        code = 'x = 1\ny = 2\nprint x\nprint y'
        interp, _ = run_trace(code)
        s = interp.summary()
        self.assertEqual(s['assignments'], 2)
        self.assertEqual(s['prints'], 2)
        self.assertEqual(s['total_steps'], 4)

    def test_summary_function_calls(self):
        code = 'function f\n    return 1\nf\nf\nf'
        interp, _ = run_trace(code)
        s = interp.summary()
        self.assertEqual(s['function_calls'], 3)

    def test_summary_max_depth(self):
        code = 'function double x\n    return x * 2\nprint double 5'
        interp, _ = run_trace(code)
        s = interp.summary()
        self.assertGreaterEqual(s['max_depth'], 1)

    def test_summary_unique_variables(self):
        code = 'x = 1\ny = 2\nx = 3'
        interp, _ = run_trace(code)
        s = interp.summary()
        self.assertEqual(s['unique_variables'], 2)  # x and y


class TestTraceEvent(unittest.TestCase):
    """Test TraceEvent object."""

    def test_to_dict(self):
        e = TraceEvent(1, 'assign', 5, 'x = 42', 0)
        d = e.to_dict()
        self.assertEqual(d['step'], 1)
        self.assertEqual(d['kind'], 'assign')
        self.assertEqual(d['line'], 5)
        self.assertEqual(d['detail'], 'x = 42')
        self.assertEqual(d['depth'], 0)
        self.assertNotIn('variables', d)

    def test_to_dict_with_variables(self):
        e = TraceEvent(1, 'assign', 5, 'x = 42', 0, variables={'x': '42'})
        d = e.to_dict()
        self.assertIn('variables', d)
        self.assertEqual(d['variables']['x'], '42')


class TestSafeRepr(unittest.TestCase):
    """Test _safe_repr helper."""

    def test_string(self):
        self.assertEqual(_safe_repr('hello'), "'hello'")

    def test_integer_float(self):
        self.assertEqual(_safe_repr(42.0), '42')

    def test_bool(self):
        self.assertEqual(_safe_repr(True), 'true')
        self.assertEqual(_safe_repr(False), 'false')

    def test_none(self):
        self.assertEqual(_safe_repr(None), 'null')

    def test_list_short(self):
        self.assertEqual(_safe_repr([1, 2, 3]), '[1, 2, 3]')

    def test_list_long(self):
        r = _safe_repr(list(range(20)))
        self.assertIn('20 items', r)

    def test_dict_short(self):
        r = _safe_repr({'a': 1})
        self.assertIn('a', r)

    def test_dict_long(self):
        r = _safe_repr({str(i): i for i in range(10)})
        self.assertIn('entries', r)

    def test_callable(self):
        self.assertEqual(_safe_repr(lambda: None), '<function>')

    def test_truncation(self):
        r = _safe_repr('x' * 200, max_len=50)
        self.assertLessEqual(len(r), 50)
        self.assertTrue(r.endswith('...'))


class TestTraceErrors(unittest.TestCase):
    """Test tracing of error conditions."""

    def test_uncaught_throw(self):
        code = 'throw "boom"'
        interp, _ = run_trace(code)
        errors = [e for e in interp.trace if e.kind == 'error']
        self.assertGreaterEqual(len(errors), 1)
        self.assertIn('boom', errors[0].detail)

    def test_runtime_error(self):
        code = 'print x'  # undefined variable
        interp, _ = run_trace(code)
        errors = [e for e in interp.trace if e.kind == 'error']
        self.assertGreaterEqual(len(errors), 1)


class TestTraceCallDepth(unittest.TestCase):
    """Test call depth tracking."""

    def test_nested_calls(self):
        code = ('function double x\n    return x * 2\n'
                'function quad x\n    return double (double x)\n'
                'print quad 3')
        interp, output = run_trace(code)
        self.assertIn('12', output)
        max_depth = max(e.depth for e in interp.trace)
        self.assertGreaterEqual(max_depth, 1)

    def test_depth_returns_to_zero(self):
        code = 'function f\n    return 1\nf\nprint "done"'
        interp, _ = run_trace(code)
        last = interp.trace[-1]
        self.assertEqual(last.depth, 0)


class TestTraceJsonOutput(unittest.TestCase):
    """Test JSON output format."""

    def test_json_serializable(self):
        interp, _ = run_trace('x = 1\nprint x')
        dicts = [e.to_dict() for e in interp.trace]
        result = json.dumps(dicts)
        parsed = json.loads(result)
        self.assertIsInstance(parsed, list)
        self.assertGreater(len(parsed), 0)

    def test_json_has_expected_fields(self):
        interp, _ = run_trace('x = 1')
        d = interp.trace[0].to_dict()
        for field in ('step', 'kind', 'detail', 'depth'):
            self.assertIn(field, d)


if __name__ == '__main__':
    unittest.main()
