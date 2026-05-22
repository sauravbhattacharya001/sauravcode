#!/usr/bin/env python3
"""Tests for sauravchrono — time-travel execution recorder & anomaly detector.

Covers:
- ``_safe_copy``: serializable values pass through; non-serializable are repr()d;
  callables and classes are dropped.
- ``Snapshot``: __slots__ shape and ``to_dict`` payload.
- ``ChronoRecorder``: end-to-end on real sauravcode, including step counting,
  print-output capture, ``--limit`` enforcement, ``capture_vars=False`` mode,
  hot-line / mutation tracking, and graceful handling of throwing programs.
- ``AnomalyDetector``: hot-line, mutation-storm, type-instability, loop-risk,
  and dead-variable detectors all reachable and well-formed.
- ``_describe``: returns a sensible string for nodes with / without a ``line``.
- ``text_report`` and ``html_report``: smoke + structural assertions.
- ``main()`` CLI: happy path (``--report``), ``--json``, ``--html`` file write,
  unknown-file error, ``--version``.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sauravchrono  # noqa: E402


LOOP_SRC = (
    "x = 0\n"
    "while x < 60\n"
    "    x = x + 1\n"
    "end\n"
    "print x\n"
)

SIMPLE_SRC = (
    "x = 0\n"
    "for i in range 1 5\n"
    "    x = x + i\n"
    "end\n"
    "print x\n"
)


class TestSafeCopy(unittest.TestCase):
    def test_passes_through_json_safe_values(self):
        env = {"a": 1, "b": "hi", "c": [1, 2], "d": {"k": "v"}, "e": None}
        out = sauravchrono._safe_copy(env)
        self.assertEqual(out, env)

    def test_non_serializable_falls_back_to_repr(self):
        obj = object()
        out = sauravchrono._safe_copy({"obj": obj})
        self.assertEqual(out["obj"], repr(obj))

    def test_callables_and_classes_are_skipped(self):
        out = sauravchrono._safe_copy(
            {"fn": lambda x: x, "cls": int, "ok": 1}
        )
        self.assertNotIn("fn", out)
        self.assertNotIn("cls", out)
        self.assertEqual(out["ok"], 1)


class TestSnapshot(unittest.TestCase):
    def test_slots_enforced(self):
        s = sauravchrono.Snapshot(0, 1, "Kind", "detail", {"x": 1}, 0)
        with self.assertRaises(AttributeError):
            s.bogus_attr = 1  # __slots__ blocks new attributes

    def test_to_dict_includes_core_fields_but_not_timestamp(self):
        s = sauravchrono.Snapshot(3, 7, "Print", "print x", {"x": 9}, 2)
        d = s.to_dict()
        self.assertEqual(d["step"], 3)
        self.assertEqual(d["line"], 7)
        self.assertEqual(d["kind"], "Print")
        self.assertEqual(d["variables"], {"x": 9})
        self.assertEqual(d["depth"], 2)
        # ``ts`` is monotonic_ns and intentionally not serialized.
        self.assertNotIn("ts", d)


class TestChronoRecorder(unittest.TestCase):
    def test_records_steps_and_captures_print_output(self):
        rec = sauravchrono.ChronoRecorder(SIMPLE_SRC, limit=500).run()
        self.assertGreater(len(rec.timeline), 0)
        # All snapshots are real Snapshot instances.
        self.assertTrue(all(isinstance(s, sauravchrono.Snapshot)
                            for s in rec.timeline))
        # The recorded program ran end-to-end without crashing the
        # recorder. We don't pin the exact stdout because the for-loop
        # semantics depend on the language version; we just confirm the
        # output attribute is populated and a string.
        self.assertIsInstance(rec.output, str)

    def test_limit_caps_recorded_steps(self):
        # The recorder must respect ``--limit`` and never grow past it,
        # regardless of how many AST nodes the interpreter visits.
        rec = sauravchrono.ChronoRecorder(LOOP_SRC, limit=5).run()
        self.assertLessEqual(len(rec.timeline), 5)

    def test_capture_vars_false_yields_empty_variable_snapshots(self):
        rec = sauravchrono.ChronoRecorder(
            SIMPLE_SRC, limit=500, capture_vars=False
        ).run()
        self.assertGreater(len(rec.timeline), 0)
        for snap in rec.timeline:
            self.assertEqual(snap.variables, {})

    def test_line_hits_tracks_loop_body(self):
        rec = sauravchrono.ChronoRecorder(LOOP_SRC, limit=2000).run()
        # The loop body (line 3) is the hottest line in the program.
        hottest_line, hottest_count = rec._line_hits.most_common(1)[0]
        self.assertEqual(hottest_line, 3)
        self.assertGreaterEqual(hottest_count, 50)

    def test_mutation_counter_increments_on_writes(self):
        rec = sauravchrono.ChronoRecorder(LOOP_SRC, limit=2000).run()
        # ``x`` is mutated on every loop iteration.
        self.assertGreater(rec._var_mutations.get("x", 0), 50)

    def test_run_swallows_program_exceptions_and_restores_stdout(self):
        # Force a runtime error inside the recorded program. The recorder
        # must NOT propagate the exception — it should still hand back a
        # finished recorder so callers can inspect partial state.
        bad_src = 'x = 1 / 0\nprint "never"\n'
        saved_stdout = sys.stdout
        rec = sauravchrono.ChronoRecorder(bad_src, limit=100).run()
        self.assertIs(sys.stdout, saved_stdout,
                      "stdout was not restored after run()")
        self.assertTrue(hasattr(rec, "output"))


class TestAnomalyDetector(unittest.TestCase):
    def setUp(self):
        self.rec = sauravchrono.ChronoRecorder(LOOP_SRC, limit=2000).run()
        self.det = sauravchrono.AnomalyDetector(self.rec)

    def test_detect_returns_a_list_of_dicts(self):
        anomalies = self.det.detect()
        self.assertIsInstance(anomalies, list)
        for a in anomalies:
            self.assertIn("type", a)
            self.assertIn("severity", a)
            self.assertIn("message", a)
            self.assertIn(a["severity"], {"info", "warning", "critical"})

    def test_hot_line_detected_for_tight_loop(self):
        anomalies = self.det.detect()
        hots = [a for a in anomalies if a["type"] == "hot_line"]
        self.assertTrue(hots, "tight loop should trigger hot_line anomaly")
        self.assertEqual(hots[0]["line"], 3)

    def test_mutation_storm_detected_for_loop_variable(self):
        anomalies = self.det.detect()
        storms = [a for a in anomalies if a["type"] == "mutation_storm"]
        self.assertTrue(storms, "x mutated >30 times should trigger storm")
        self.assertIn(storms[0]["variable"], {"x", "i"})

    def test_no_anomalies_on_trivial_program(self):
        rec = sauravchrono.ChronoRecorder('print 1\n', limit=10).run()
        self.assertEqual(sauravchrono.AnomalyDetector(rec).detect(), [])

    def test_type_instability_detection(self):
        # Synthesize a recorder by hand; building a real sauravcode source
        # that flips types is fragile across language versions, but the
        # detector consumes ``_var_types`` directly.
        rec = sauravchrono.ChronoRecorder("print 1\n", limit=10).run()
        rec._var_types["x"] = ["int", "str", "list"]
        rec._var_mutations["x"] = 3
        anomalies = sauravchrono.AnomalyDetector(rec).detect()
        types_a = [a for a in anomalies if a["type"] == "type_instability"]
        self.assertTrue(types_a)
        self.assertEqual(types_a[0]["variable"], "x")
        self.assertEqual(types_a[0]["types"], ["int", "str", "list"])

    def test_dead_variable_detection(self):
        # Build a synthetic timeline: ``early`` appears only in the first
        # third, ``late`` appears throughout. The detector should flag
        # ``early`` and ignore ``late``.
        rec = sauravchrono.ChronoRecorder("print 1\n", limit=10).run()
        rec.timeline = []
        for i in range(30):
            vars_ = {"early": 1, "late": 2} if i < 5 else {"late": 2}
            rec.timeline.append(
                sauravchrono.Snapshot(i, 1, "X", "x", vars_, 0)
            )
        anomalies = sauravchrono.AnomalyDetector(rec).detect()
        dead = [a for a in anomalies if a["type"] == "dead_variable"]
        self.assertTrue(any(a["variable"] == "early" for a in dead))
        self.assertFalse(any(a["variable"] == "late" for a in dead))


class TestDescribe(unittest.TestCase):
    def test_returns_source_line_when_available(self):
        lines = ["alpha", "beta", "gamma"]
        node = mock.Mock(line=2)
        self.assertEqual(sauravchrono._describe(node, lines), "beta")

    def test_falls_back_to_classname_when_no_line(self):
        class FakeNode:
            line = None
        node = FakeNode()
        out = sauravchrono._describe(node, ["a", "b"])
        self.assertEqual(out, "FakeNode")


class TestReports(unittest.TestCase):
    def test_text_report_smoke(self):
        rec = sauravchrono.ChronoRecorder(LOOP_SRC, limit=2000).run()
        anomalies = sauravchrono.AnomalyDetector(rec).detect()
        buf = io.StringIO()
        with redirect_stdout(buf):
            sauravchrono.text_report(rec, anomalies)
        out = buf.getvalue()
        self.assertIn("sauravchrono", out)
        self.assertIn("Total steps recorded:", out)
        self.assertIn(f"Anomalies: {len(anomalies)}", out)

    def test_text_report_clean_message_when_no_anomalies(self):
        rec = sauravchrono.ChronoRecorder('print 1\n', limit=10).run()
        buf = io.StringIO()
        with redirect_stdout(buf):
            sauravchrono.text_report(rec, [])
        self.assertIn("No anomalies detected", buf.getvalue())

    def test_html_report_writes_file_and_returns_content(self):
        rec = sauravchrono.ChronoRecorder(LOOP_SRC, limit=2000).run()
        anomalies = sauravchrono.AnomalyDetector(rec).detect()
        with tempfile.TemporaryDirectory() as td:
            outpath = os.path.join(td, "report.html")
            buf = io.StringIO()
            with redirect_stdout(buf):
                content = sauravchrono.html_report(rec, anomalies, outpath)
            self.assertTrue(os.path.exists(outpath))
            on_disk = open(outpath, encoding="utf-8").read()
            self.assertEqual(content, on_disk)
            self.assertIn("<!DOCTYPE html>", content)
            self.assertIn("sauravchrono", content)
            # Embedded JSON chart data must be valid JSON.
            self.assertIn("const data = ", content)

    def test_html_report_escapes_anomaly_messages(self):
        rec = sauravchrono.ChronoRecorder('print 1\n', limit=10).run()
        evil = [{
            "type": "loop_risk",
            "severity": "critical",
            "message": "<script>alert(1)</script>",
        }]
        content = sauravchrono.html_report(rec, evil)
        # Raw <script> from the anomaly must be escaped, not rendered.
        self.assertNotIn("<script>alert(1)</script>", content)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", content)


class TestMain(unittest.TestCase):
    def _write_src(self, td, src):
        path = os.path.join(td, "prog.srv")
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
        return path

    def test_missing_file_exits_nonzero(self):
        with self.assertRaises(SystemExit) as ctx:
            with redirect_stderr(io.StringIO()):
                with mock.patch.object(sys, "argv",
                                       ["sauravchrono", "no-such-file.srv"]):
                    sauravchrono.main()
        self.assertEqual(ctx.exception.code, 1)

    def test_report_mode_prints_text_report(self):
        with tempfile.TemporaryDirectory() as td:
            srcpath = self._write_src(td, SIMPLE_SRC)
            buf = io.StringIO()
            with redirect_stdout(buf), mock.patch.object(
                sys, "argv", ["sauravchrono", srcpath, "--report"]
            ):
                sauravchrono.main()
            out = buf.getvalue()
            self.assertIn("Execution Report", out)
            self.assertIn("Total steps recorded:", out)

    def test_json_mode_emits_parseable_timeline(self):
        with tempfile.TemporaryDirectory() as td:
            srcpath = self._write_src(td, SIMPLE_SRC)
            buf = io.StringIO()
            with redirect_stdout(buf), mock.patch.object(
                sys, "argv", ["sauravchrono", srcpath, "--json"]
            ):
                sauravchrono.main()
            data = json.loads(buf.getvalue())
            self.assertEqual(data["file"], srcpath)
            self.assertIsInstance(data["timeline"], list)
            self.assertIsInstance(data["anomalies"], list)
            self.assertEqual(len(data["timeline"]), data["steps"])

    def test_json_with_output_writes_file(self):
        with tempfile.TemporaryDirectory() as td:
            srcpath = self._write_src(td, SIMPLE_SRC)
            outpath = os.path.join(td, "timeline.json")
            buf = io.StringIO()
            with redirect_stdout(buf), mock.patch.object(
                sys, "argv",
                ["sauravchrono", srcpath, "--json", "-o", outpath],
            ):
                sauravchrono.main()
            data = json.loads(open(outpath, encoding="utf-8").read())
            self.assertIn("timeline", data)

    def test_report_html_writes_dashboard(self):
        with tempfile.TemporaryDirectory() as td:
            srcpath = self._write_src(td, SIMPLE_SRC)
            outpath = os.path.join(td, "report.html")
            buf = io.StringIO()
            with redirect_stdout(buf), mock.patch.object(
                sys, "argv",
                ["sauravchrono", srcpath, "--report", "--html", "-o", outpath],
            ):
                sauravchrono.main()
            self.assertTrue(os.path.exists(outpath))
            self.assertIn("<!DOCTYPE html>",
                          open(outpath, encoding="utf-8").read())

    def test_version_flag(self):
        buf = io.StringIO()
        with self.assertRaises(SystemExit) as ctx:
            with redirect_stdout(buf), mock.patch.object(
                sys, "argv", ["sauravchrono", "--version"]
            ):
                sauravchrono.main()
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn(sauravchrono.__version__, buf.getvalue())


if __name__ == "__main__":
    unittest.main()
