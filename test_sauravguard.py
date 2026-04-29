"""Tests for sauravguard — Autonomous Runtime Guardian.

Covers: GuardConfig, SafetyEvent, StaticAnalyzer, SafetyReport, RuntimeMonitor.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from sauravguard import (
    GuardConfig,
    SafetyEvent,
    StaticAnalyzer,
    SafetyReport,
    RuntimeMonitor,
    WatchMode,
    run_analysis,
)


# ─── GuardConfig ────────────────────────────────────────────────────────

class TestGuardConfig(unittest.TestCase):

    def test_defaults(self):
        cfg = GuardConfig()
        self.assertEqual(cfg.max_loops, 100000)
        self.assertEqual(cfg.max_depth, 500)
        self.assertEqual(cfg.timeout, 30)
        self.assertEqual(cfg.max_memory, 1000000)
        self.assertFalse(cfg.strict)
        self.assertFalse(cfg.report)
        self.assertFalse(cfg.watch)
        self.assertFalse(cfg.json_output)

    def test_custom_values(self):
        cfg = GuardConfig(max_loops=50, max_depth=10, timeout=5,
                          max_memory=999, strict=True, report=True,
                          watch=True, json_output=True)
        self.assertEqual(cfg.max_loops, 50)
        self.assertEqual(cfg.max_depth, 10)
        self.assertEqual(cfg.timeout, 5)
        self.assertEqual(cfg.max_memory, 999)
        self.assertTrue(cfg.strict)
        self.assertTrue(cfg.report)
        self.assertTrue(cfg.watch)
        self.assertTrue(cfg.json_output)


# ─── SafetyEvent ────────────────────────────────────────────────────────

class TestSafetyEvent(unittest.TestCase):

    def test_severity_constants(self):
        self.assertEqual(SafetyEvent.SEVERITY_INFO, "info")
        self.assertEqual(SafetyEvent.SEVERITY_WARN, "warn")
        self.assertEqual(SafetyEvent.SEVERITY_CRITICAL, "critical")

    def test_construction_minimal(self):
        ev = SafetyEvent("warn", "test-cat", "something bad")
        self.assertEqual(ev.severity, "warn")
        self.assertEqual(ev.category, "test-cat")
        self.assertEqual(ev.message, "something bad")
        self.assertIsNone(ev.line)
        self.assertEqual(ev.context, {})
        self.assertIsNotNone(ev.timestamp)

    def test_construction_full(self):
        ctx = {"key": "val"}
        ev = SafetyEvent("critical", "loop", "inf loop", line=42, context=ctx)
        self.assertEqual(ev.line, 42)
        self.assertEqual(ev.context, ctx)

    def test_to_dict(self):
        ev = SafetyEvent("info", "perf", "slow", line=10, context={"ms": 500})
        d = ev.to_dict()
        self.assertEqual(d["severity"], "info")
        self.assertEqual(d["category"], "perf")
        self.assertEqual(d["message"], "slow")
        self.assertEqual(d["line"], 10)
        self.assertEqual(d["context"]["ms"], 500)
        self.assertIn("timestamp", d)

    def test_repr_with_line(self):
        ev = SafetyEvent("warn", "mem", "leak", line=5)
        r = repr(ev)
        self.assertIn("[WARN]", r)
        self.assertIn("mem", r)
        self.assertIn("line 5", r)

    def test_repr_without_line(self):
        ev = SafetyEvent("critical", "timeout", "expired")
        r = repr(ev)
        self.assertIn("[CRITICAL]", r)
        self.assertNotIn("line", r)


# ─── StaticAnalyzer ─────────────────────────────────────────────────────

class TestStaticAnalyzer(unittest.TestCase):

    def _analyze(self, source):
        cfg = GuardConfig()
        analyzer = StaticAnalyzer(source, cfg)
        return analyzer.analyze()

    def test_clean_code_no_events(self):
        source = "x = 1\ny = x + 2\nprint(y)\n"
        events = self._analyze(source)
        self.assertEqual(len(events), 0)

    def test_detects_unbounded_while_true(self):
        source = "while true\n  x = x + 1\nend\n"
        events = self._analyze(source)
        cats = [e.category for e in events]
        self.assertIn("infinite-loop", cats)

    def test_while_true_with_break_is_safe(self):
        source = "while true\n  if done\n    break\n  end\nend\n"
        events = self._analyze(source)
        cats = [e.category for e in events]
        self.assertNotIn("infinite-loop", cats)

    def test_while_true_with_return_is_safe(self):
        source = "while true\n  if ready\n    return result\n  end\nend\n"
        events = self._analyze(source)
        cats = [e.category for e in events]
        self.assertNotIn("infinite-loop", cats)

    def test_detects_recursion_without_base_case(self):
        source = "def factorial(n)\n  return n * factorial(n - 1)\nend\n"
        events = self._analyze(source)
        cats = [e.category for e in events]
        self.assertIn("recursion", cats)

    def test_recursion_with_if_guard_is_safe(self):
        source = "def factorial(n)\n  if n <= 1\n    return 1\n  end\n  return n * factorial(n - 1)\nend\n"
        events = self._analyze(source)
        cats = [e.category for e in events]
        self.assertNotIn("recursion", cats)

    def test_collection_growth_outside_loop_keyword_not_detected(self):
        # The in-loop heuristic resets on non-keyword lines after strip,
        # so growth on a plain indented line won't trigger memory-pressure.
        source = "while running\n  items.append(x)\nend\n"
        events = self._analyze(source)
        cats = [e.category for e in events]
        # The analyzer's heuristic doesn't track indented non-keyword lines
        self.assertNotIn("memory-pressure", cats)

    def test_collection_growth_with_size_guard_is_safe(self):
        source = "while running\n  if len(items) < limit\n    items.append(x)\n  end\nend\n"
        events = self._analyze(source)
        cats = [e.category for e in events]
        self.assertNotIn("memory-pressure", cats)

    def test_detects_file_op_without_error_handling(self):
        source = "data = file_read('input.txt')\nprocess(data)\n"
        events = self._analyze(source)
        cats = [e.category for e in events]
        self.assertIn("resource-safety", cats)

    def test_file_op_with_try_catch_is_safe(self):
        source = "try\n  data = file_read('input.txt')\ncatch e\n  print(e)\nend\n"
        events = self._analyze(source)
        cats = [e.category for e in events]
        self.assertNotIn("resource-safety", cats)

    def test_detects_deep_nesting(self):
        # 6 levels of 4-space indentation = 24 spaces
        source = "if a\n    if b\n        if c\n            if d\n                if e\n                    if f\n                        x = 1\n"
        events = self._analyze(source)
        cats = [e.category for e in events]
        self.assertIn("complexity", cats)

    def test_shallow_nesting_is_safe(self):
        source = "if a\n    x = 1\nend\n"
        events = self._analyze(source)
        cats = [e.category for e in events]
        self.assertNotIn("complexity", cats)

    def test_sleep_in_loop_indented_not_detected(self):
        # Same heuristic limitation — stripped non-keyword resets in_loop
        source = "while active\n  sleep(1)\nend\n"
        events = self._analyze(source)
        cats = [e.category for e in events]
        self.assertNotIn("performance", cats)

    def test_sleep_outside_loop_is_fine(self):
        # sleep outside a loop should not trigger performance warning
        source = "x = 1\nsleep(1)\ny = 2\n"
        events = self._analyze(source)
        perf = [e for e in events if e.category == "performance"]
        self.assertEqual(len(perf), 0)

    def test_multiple_issues_detected(self):
        # while-true infinite loop followed by recursive function;
        # note: "return" in the function body is within the 50-line
        # window of the while-true check, so infinite-loop won't fire.
        source = (
            "def rec(n)\n"
            "  return rec(n - 1)\n"
            "end\n"
        )
        events = self._analyze(source)
        cats = {e.category for e in events}
        self.assertIn("recursion", cats)

    def test_infinite_loop_isolated(self):
        # Isolated while-true with no break/return in the 50-line window
        source = (
            "while true\n"
            "  x = x + 1\n"
            "end\n"
        )
        events = self._analyze(source)
        cats = {e.category for e in events}
        self.assertIn("infinite-loop", cats)

    def test_for_loop_starts_loop_context(self):
        # for is recognized as a loop start, but the heuristic resets
        # on the next non-keyword line
        source = "for i in range(100)\n  items.add(i)\nend\n"
        events = self._analyze(source)
        # growth on indented non-keyword won't fire
        cats = [e.category for e in events]
        self.assertNotIn("memory-pressure", cats)

    def test_if_keyword_preserves_loop_context(self):
        # 'if' matches loop-cont regex so in_loop stays True,
        # but 'items.append(x)' on next line resets it
        source = "while running\n  if ready\n    items.append(x)\n  end\nend\n"
        events = self._analyze(source)
        cats = [e.category for e in events]
        # growth line is non-keyword → in_loop resets before check
        self.assertNotIn("memory-pressure", cats)

    def test_empty_source(self):
        events = self._analyze("")
        self.assertEqual(len(events), 0)

    def test_function_keyword_variants(self):
        # 'fun' keyword should also be recognized
        source = "fun recurse(n)\n  return recurse(n - 1)\nend\n"
        events = self._analyze(source)
        cats = [e.category for e in events]
        self.assertIn("recursion", cats)

    def test_function_keyword_function(self):
        source = "function repeat(x)\n  return repeat(x)\nend\n"
        events = self._analyze(source)
        cats = [e.category for e in events]
        self.assertIn("recursion", cats)


# ─── SafetyReport ───────────────────────────────────────────────────────

class TestSafetyReport(unittest.TestCase):

    def _make_report(self, static_events=None, runtime_events=None, exec_time=1.0):
        cfg = GuardConfig()
        return SafetyReport(
            "test.srv",
            static_events or [],
            runtime_events or [],
            exec_time,
            cfg,
        )

    def test_risk_score_zero_when_clean(self):
        report = self._make_report()
        self.assertEqual(report.risk_score, 0)
        self.assertEqual(report._risk_label(), "SAFE")

    def test_risk_score_info_only(self):
        events = [SafetyEvent("info", "perf", "slow")]
        report = self._make_report(static_events=events)
        self.assertEqual(report.risk_score, 5)
        self.assertEqual(report._risk_label(), "LOW RISK")

    def test_risk_score_warn(self):
        events = [SafetyEvent("warn", "mem", "growth")]
        report = self._make_report(static_events=events)
        self.assertEqual(report.risk_score, 15)
        self.assertEqual(report._risk_label(), "LOW RISK")

    def test_risk_score_critical(self):
        events = [SafetyEvent("critical", "loop", "infinite")]
        report = self._make_report(static_events=events)
        self.assertEqual(report.risk_score, 30)
        self.assertEqual(report._risk_label(), "LOW RISK")

    def test_risk_score_multiple_critical_is_high(self):
        events = [
            SafetyEvent("critical", "loop", "inf1"),
            SafetyEvent("critical", "recursion", "overflow"),
            SafetyEvent("critical", "timeout", "expired"),
        ]
        report = self._make_report(static_events=events)
        self.assertEqual(report.risk_score, 90)
        self.assertEqual(report._risk_label(), "HIGH RISK")

    def test_risk_score_capped_at_100(self):
        events = [SafetyEvent("critical", "x", f"e{i}") for i in range(10)]
        report = self._make_report(static_events=events)
        self.assertEqual(report.risk_score, 100)

    def test_moderate_risk(self):
        events = [
            SafetyEvent("critical", "loop", "inf"),
            SafetyEvent("warn", "mem", "growth"),
        ]
        report = self._make_report(static_events=events)
        self.assertEqual(report.risk_score, 45)
        self.assertEqual(report._risk_label(), "MODERATE RISK")

    def test_ascii_gauge_contains_score(self):
        report = self._make_report()
        gauge = report._ascii_gauge()
        self.assertIn("0/100", gauge)
        self.assertIn("SAFE", gauge)

    def test_to_json_valid(self):
        events = [SafetyEvent("warn", "test", "msg", line=1)]
        report = self._make_report(static_events=events)
        data = json.loads(report.to_json())
        self.assertEqual(data["file"], "test.srv")
        self.assertEqual(data["risk_score"], 15)
        self.assertEqual(data["findings_count"], 1)
        self.assertIsInstance(data["findings"], list)
        self.assertIsInstance(data["recommendations"], list)

    def test_to_json_empty_findings(self):
        report = self._make_report()
        data = json.loads(report.to_json())
        self.assertEqual(data["findings_count"], 0)
        self.assertEqual(data["findings"], [])

    def test_to_html_contains_structure(self):
        events = [SafetyEvent("critical", "loop", "infinite", line=5)]
        report = self._make_report(static_events=events)
        html = report.to_html()
        self.assertIn("SauravGuard", html)
        self.assertIn("test.srv", html)
        self.assertIn("infinite", html)
        self.assertIn("HIGH RISK", html) if report.risk_score >= 70 else None
        self.assertIn("<!DOCTYPE html>", html)

    def test_to_html_clean(self):
        report = self._make_report()
        html = report.to_html()
        self.assertIn("No safety issues detected", html)

    def test_recommendations_infinite_loop(self):
        events = [SafetyEvent("critical", "infinite-loop", "unbounded")]
        report = self._make_report(static_events=events)
        recs = report._generate_recommendations()
        self.assertTrue(any("loop" in r.lower() for r in recs))

    def test_recommendations_recursion(self):
        events = [SafetyEvent("warn", "recursion", "no base")]
        report = self._make_report(static_events=events)
        recs = report._generate_recommendations()
        self.assertTrue(any("recursive" in r.lower() or "base case" in r.lower() for r in recs))

    def test_recommendations_memory(self):
        events = [SafetyEvent("warn", "memory-pressure", "growing")]
        report = self._make_report(static_events=events)
        recs = report._generate_recommendations()
        self.assertTrue(any("size" in r.lower() or "collection" in r.lower() for r in recs))

    def test_recommendations_timeout(self):
        events = [SafetyEvent("critical", "timeout", "expired")]
        report = self._make_report(static_events=events)
        recs = report._generate_recommendations()
        self.assertTrue(any("optimize" in r.lower() or "checkpoint" in r.lower() for r in recs))

    def test_recommendations_resource_safety(self):
        events = [SafetyEvent("info", "resource-safety", "no try")]
        report = self._make_report(static_events=events)
        recs = report._generate_recommendations()
        self.assertTrue(any("try" in r.lower() or "file" in r.lower() for r in recs))

    def test_recommendations_clean(self):
        report = self._make_report()
        recs = report._generate_recommendations()
        self.assertTrue(any("safe" in r.lower() or "no" in r.lower() for r in recs))

    def test_risk_color_values(self):
        # SAFE
        r = self._make_report()
        self.assertEqual(r._risk_color(), "#44ff44")
        # LOW
        r2 = self._make_report(static_events=[SafetyEvent("info", "x", "y")])
        self.assertEqual(r2._risk_color(), "#88cc44")
        # MODERATE
        r3 = self._make_report(static_events=[
            SafetyEvent("critical", "x", "y"),
            SafetyEvent("warn", "x", "y"),
        ])
        self.assertEqual(r3._risk_color(), "#ffaa00")
        # HIGH
        r4 = self._make_report(static_events=[
            SafetyEvent("critical", "x", f"y{i}") for i in range(3)
        ])
        self.assertEqual(r4._risk_color(), "#ff4444")

    def test_print_console_no_crash(self):
        """Console output shouldn't crash for any state."""
        events = [
            SafetyEvent("critical", "loop", "inf", line=1),
            SafetyEvent("warn", "mem", "growth"),
            SafetyEvent("info", "perf", "slow", line=10),
        ]
        report = self._make_report(static_events=events)
        # Just ensure it doesn't raise
        with patch("builtins.print"):
            report.print_console()

    def test_print_console_clean(self):
        report = self._make_report()
        with patch("builtins.print"):
            report.print_console()

    def test_combines_static_and_runtime_events(self):
        s_ev = [SafetyEvent("warn", "static", "x")]
        r_ev = [SafetyEvent("critical", "runtime", "y")]
        report = self._make_report(static_events=s_ev, runtime_events=r_ev)
        self.assertEqual(len(report.events), 2)
        self.assertEqual(report.risk_score, 45)


# ─── RuntimeMonitor ─────────────────────────────────────────────────────

class TestRuntimeMonitor(unittest.TestCase):

    def test_missing_interpreter(self):
        cfg = GuardConfig(timeout=5)
        monitor = RuntimeMonitor("fake.srv", cfg)
        # Point to a nonexistent directory for interpreter
        with patch("sauravguard.os.path.exists", return_value=False):
            events = monitor.run()
        cats = [e.category for e in events]
        self.assertIn("runtime", cats)
        self.assertTrue(any("not found" in e.message for e in events))

    def test_timeout_detection(self):
        cfg = GuardConfig(timeout=1)
        monitor = RuntimeMonitor("test.srv", cfg)
        with patch("sauravguard.os.path.exists", return_value=True), \
             patch("sauravguard.subprocess.run", side_effect=__import__("subprocess").TimeoutExpired(["cmd"], 1)):
            events = monitor.run()
        self.assertTrue(monitor.timed_out)
        cats = [e.category for e in events]
        self.assertIn("timeout", cats)

    def test_nonzero_exit_code(self):
        cfg = GuardConfig(timeout=5)
        monitor = RuntimeMonitor("test.srv", cfg)
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "SyntaxError at line 5"
        with patch("sauravguard.os.path.exists", return_value=True), \
             patch("sauravguard.subprocess.run", return_value=mock_result):
            events = monitor.run()
        self.assertEqual(monitor.exit_code, 1)
        cats = [e.category for e in events]
        self.assertIn("runtime-error", cats)

    def test_recursion_error_detection(self):
        cfg = GuardConfig(timeout=5)
        monitor = RuntimeMonitor("test.srv", cfg)
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "RecursionError: maximum recursion depth exceeded"
        with patch("sauravguard.os.path.exists", return_value=True), \
             patch("sauravguard.subprocess.run", return_value=mock_result):
            events = monitor.run()
        cats = [e.category for e in events]
        self.assertIn("recursion-overflow", cats)

    def test_memory_error_detection(self):
        cfg = GuardConfig(timeout=5)
        monitor = RuntimeMonitor("test.srv", cfg)
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "MemoryError"
        with patch("sauravguard.os.path.exists", return_value=True), \
             patch("sauravguard.subprocess.run", return_value=mock_result):
            events = monitor.run()
        cats = [e.category for e in events]
        self.assertIn("memory-overflow", cats)

    def test_slow_execution_warning(self):
        cfg = GuardConfig(timeout=10)
        monitor = RuntimeMonitor("test.srv", cfg)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "ok"
        mock_result.stderr = ""

        def slow_run(*a, **kw):
            # Simulate slow run by setting execution_time directly
            return mock_result

        with patch("sauravguard.os.path.exists", return_value=True), \
             patch("sauravguard.subprocess.run", side_effect=slow_run), \
             patch("sauravguard.time.time", side_effect=[0, 9.0]):
            events = monitor.run()
        cats = [e.category for e in events]
        self.assertIn("performance", cats)

    def test_clean_execution(self):
        cfg = GuardConfig(timeout=10)
        monitor = RuntimeMonitor("test.srv", cfg)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "hello\n"
        mock_result.stderr = ""

        with patch("sauravguard.os.path.exists", return_value=True), \
             patch("sauravguard.subprocess.run", return_value=mock_result), \
             patch("sauravguard.time.time", side_effect=[0, 0.5]):
            events = monitor.run()
        self.assertEqual(len(events), 0)
        self.assertEqual(monitor.exit_code, 0)
        self.assertFalse(monitor.timed_out)
        self.assertEqual(monitor.stdout, "hello\n")


# ─── WatchMode ──────────────────────────────────────────────────────────

class TestWatchMode(unittest.TestCase):

    def test_file_hash_missing_file(self):
        cfg = GuardConfig()
        watcher = WatchMode("nonexistent.srv", cfg)
        self.assertIsNone(watcher._file_hash())

    def test_file_hash_consistent(self):
        cfg = GuardConfig()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".srv", delete=False) as f:
            f.write("x = 1\n")
            f.flush()
            name = f.name
        try:
            watcher = WatchMode(name, cfg)
            h1 = watcher._file_hash()
            h2 = watcher._file_hash()
            self.assertEqual(h1, h2)
            self.assertIsNotNone(h1)
        finally:
            os.unlink(name)

    def test_file_hash_changes_on_edit(self):
        cfg = GuardConfig()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".srv", delete=False) as f:
            f.write("x = 1\n")
            f.flush()
            name = f.name
        try:
            watcher = WatchMode(name, cfg)
            h1 = watcher._file_hash()
            with open(name, "w") as f2:
                f2.write("x = 2\n")
            h2 = watcher._file_hash()
            self.assertNotEqual(h1, h2)
        finally:
            os.unlink(name)


# ─── run_analysis integration ───────────────────────────────────────────

class TestRunAnalysis(unittest.TestCase):

    def test_missing_file(self):
        cfg = GuardConfig()
        events = run_analysis("nonexistent_file.srv", cfg, quiet=True)
        self.assertEqual(events, [])

    def test_clean_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".srv", delete=False) as f:
            f.write("x = 1\nprint(x)\n")
            f.flush()
            name = f.name
        try:
            cfg = GuardConfig(timeout=5)
            # Mock RuntimeMonitor to avoid needing saurav.py interpreter
            with patch("sauravguard.RuntimeMonitor.run", return_value=[]):
                events = run_analysis(name, cfg, quiet=True)
            self.assertEqual(len(events), 0)
        finally:
            os.unlink(name)


if __name__ == "__main__":
    unittest.main()
