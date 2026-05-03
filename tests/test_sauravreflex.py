"""Tests for sauravreflex — Reactive Programming Engine.

Tests cover ReactiveVar, Computed, Effect, Stream, ReactiveGraph,
and ReflexAnalyzer (the .srv source analyzer).
"""

import sys
import os
import unittest

# Ensure repo root on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + os.sep + "..")

from sauravreflex import (
    ReactiveVar,
    Computed,
    Effect,
    Stream,
    ReactiveGraph,
    ReflexAnalyzer,
)


# ── ReactiveVar ──────────────────────────────────────────────────────────


class TestReactiveVar(unittest.TestCase):
    """ReactiveVar: observable variable with change notification."""

    def test_initial_value(self):
        v = ReactiveVar("x", 42)
        self.assertEqual(v.value, 42)
        self.assertEqual(v.name, "x")

    def test_none_default(self):
        v = ReactiveVar("y")
        self.assertIsNone(v.value)

    def test_set_value_updates(self):
        v = ReactiveVar("a", 1)
        v.value = 2
        self.assertEqual(v.value, 2)

    def test_history_tracks_changes(self):
        v = ReactiveVar("h", 0)
        v.value = 1
        v.value = 2
        # initial + 2 changes = 3 entries
        self.assertEqual(len(v.history), 3)
        self.assertEqual(v.history[0][1], 0)
        self.assertEqual(v.history[1][1], 1)
        self.assertEqual(v.history[2][1], 2)

    def test_no_notification_when_same_value(self):
        """Setting the same value should NOT notify dependents."""
        v = ReactiveVar("s", 5)
        notified = []

        class FakeDep:
            name = "fake"
            def notify(self, src):
                notified.append(src.name)

        v.dependents.add(FakeDep())
        v.value = 5  # same value
        self.assertEqual(notified, [])

    def test_notification_on_change(self):
        v = ReactiveVar("n", 0)
        notified = []

        class Dep:
            name = "dep"
            def notify(self, src):
                notified.append(src.value)

        v.dependents.add(Dep())
        v.value = 10
        self.assertEqual(notified, [10])

    def test_to_dict(self):
        v = ReactiveVar("d", "hello")
        d = v.to_dict()
        self.assertEqual(d["type"], "ReactiveVar")
        self.assertEqual(d["name"], "d")
        self.assertIn("hello", d["value"])
        self.assertEqual(d["changes"], 1)

    def test_multiple_dependents_notified(self):
        v = ReactiveVar("m", 0)
        names = []

        class DepA:
            name = "a"
            dependents = set()
            def notify(self, src):
                names.append("a")

        class DepB:
            name = "b"
            dependents = set()
            def notify(self, src):
                names.append("b")

        v.dependents.add(DepA())
        v.dependents.add(DepB())
        v.value = 1
        self.assertEqual(sorted(names), ["a", "b"])


# ── Computed ─────────────────────────────────────────────────────────────


class TestComputed(unittest.TestCase):
    """Computed: derived value that auto-recomputes on dependency change."""

    def test_lazy_evaluation(self):
        a = ReactiveVar("a", 3)
        c = Computed("double", [a], lambda x: x * 2)
        self.assertEqual(c.value, 6)

    def test_recompute_on_dep_change(self):
        a = ReactiveVar("a", 1)
        b = ReactiveVar("b", 2)
        s = Computed("sum", [a, b], lambda x, y: x + y)
        self.assertEqual(s.value, 3)
        a.value = 10
        self.assertEqual(s.value, 12)

    def test_recompute_count(self):
        a = ReactiveVar("a", 0)
        c = Computed("c", [a], lambda x: x + 1)
        self.assertEqual(c.recompute_count, 0)
        a.value = 1
        self.assertEqual(c.recompute_count, 1)
        a.value = 2
        self.assertEqual(c.recompute_count, 2)

    def test_chain_propagation(self):
        """Computed -> Computed chain propagates correctly."""
        a = ReactiveVar("a", 2)
        b = Computed("b", [a], lambda x: x * 3)
        c = Computed("c", [b], lambda x: x + 10)
        self.assertEqual(c.value, 16)  # 2*3+10
        a.value = 5
        self.assertEqual(c.value, 25)  # 5*3+10

    def test_registers_as_dependent(self):
        a = ReactiveVar("a", 0)
        c = Computed("c", [a], lambda x: x)
        self.assertIn(c, a.dependents)

    def test_to_dict(self):
        a = ReactiveVar("a", 1)
        c = Computed("c", [a], lambda x: x + 1)
        _ = c.value  # force compute
        d = c.to_dict()
        self.assertEqual(d["type"], "Computed")
        self.assertEqual(d["name"], "c")
        self.assertEqual(d["deps"], ["a"])
        self.assertEqual(d["recomputes"], 0)

    def test_multiple_deps(self):
        x = ReactiveVar("x", 10)
        y = ReactiveVar("y", 20)
        z = ReactiveVar("z", 30)
        total = Computed("total", [x, y, z], lambda a, b, c: a + b + c)
        self.assertEqual(total.value, 60)
        y.value = 100
        self.assertEqual(total.value, 140)


# ── Effect ───────────────────────────────────────────────────────────────


class TestEffect(unittest.TestCase):
    """Effect: side-effect triggered on dependency change."""

    def test_trigger_on_change(self):
        a = ReactiveVar("a", 0)
        log = []
        Effect("log", [a], lambda src, vals: log.append((src, vals["a"])))
        a.value = 5
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0], ("a", 5))

    def test_trigger_count(self):
        a = ReactiveVar("a", 0)
        e = Effect("e", [a], lambda s, v: None)
        a.value = 1
        a.value = 2
        a.value = 3
        self.assertEqual(e.trigger_count, 3)

    def test_no_trigger_same_value(self):
        a = ReactiveVar("a", 7)
        e = Effect("e", [a], lambda s, v: None)
        a.value = 7  # same
        self.assertEqual(e.trigger_count, 0)

    def test_multiple_deps(self):
        a = ReactiveVar("a", 1)
        b = ReactiveVar("b", 2)
        snapshots = []
        Effect("snap", [a, b], lambda src, vals: snapshots.append(dict(vals)))
        a.value = 10
        self.assertEqual(snapshots[-1], {"a": 10, "b": 2})
        b.value = 20
        self.assertEqual(snapshots[-1], {"a": 10, "b": 20})

    def test_to_dict(self):
        a = ReactiveVar("a", 0)
        e = Effect("eff", [a], lambda s, v: None)
        d = e.to_dict()
        self.assertEqual(d["type"], "Effect")
        self.assertEqual(d["deps"], ["a"])
        self.assertEqual(d["triggers"], 0)

    def test_registers_in_dependents(self):
        a = ReactiveVar("a", 0)
        e = Effect("e", [a], lambda s, v: None)
        self.assertIn(e, a.dependents)


# ── Stream ───────────────────────────────────────────────────────────────


class TestStream(unittest.TestCase):
    """Stream: event stream with functional operators."""

    def test_emit_and_subscribe(self):
        s = Stream("clicks")
        received = []
        s.subscribe(lambda v: received.append(v))
        s.emit("click1")
        s.emit("click2")
        self.assertEqual(received, ["click1", "click2"])

    def test_map(self):
        s = Stream("nums")
        doubled = s.map(lambda x: x * 2)
        results = []
        doubled.subscribe(lambda v: results.append(v))
        s.emit(3)
        s.emit(5)
        self.assertEqual(results, [6, 10])

    def test_filter(self):
        s = Stream("all")
        evens = s.filter(lambda x: x % 2 == 0)
        results = []
        evens.subscribe(lambda v: results.append(v))
        for i in range(6):
            s.emit(i)
        self.assertEqual(results, [0, 2, 4])

    def test_merge(self):
        a = Stream("a")
        b = Stream("b")
        merged = a.merge(b, name="merged")
        results = []
        merged.subscribe(lambda v: results.append(v))
        a.emit(1)
        b.emit(2)
        a.emit(3)
        self.assertEqual(results, [1, 2, 3])

    def test_chain_map_filter(self):
        s = Stream("raw")
        pipe = s.map(lambda x: x * 10).filter(lambda x: x > 25)
        results = []
        pipe.subscribe(lambda v: results.append(v))
        for i in range(5):
            s.emit(i)
        self.assertEqual(results, [30, 40])

    def test_history(self):
        s = Stream("h")
        s.emit("a")
        s.emit("b")
        self.assertEqual(len(s.history), 2)
        self.assertEqual(s.history[0][1], "a")

    def test_to_dict(self):
        s = Stream("test")
        s.emit(1)
        s.subscribe(lambda v: None)
        d = s.to_dict()
        self.assertEqual(d["type"], "Stream")
        self.assertEqual(d["name"], "test")
        self.assertEqual(d["events"], 1)
        # 1 subscriber added after emit
        self.assertEqual(d["subscribers"], 1)

    def test_empty_stream(self):
        s = Stream("empty")
        self.assertEqual(s.history, [])
        self.assertEqual(len(s.subscribers), 0)


# ── ReactiveGraph ────────────────────────────────────────────────────────


class TestReactiveGraph(unittest.TestCase):
    """ReactiveGraph: manages nodes and dependency edges."""

    def _build_graph(self):
        g = ReactiveGraph()
        a = g.add(ReactiveVar("a", 1))
        b = g.add(ReactiveVar("b", 2))
        s = g.add(Computed("sum", [a, b], lambda x, y: x + y))
        return g, a, b, s

    def test_add_and_edges(self):
        g, a, b, s = self._build_graph()
        self.assertIn("a", g.nodes)
        self.assertIn("sum", g.nodes)
        self.assertIn(("a", "sum"), g.edges)
        self.assertIn(("b", "sum"), g.edges)

    def test_topological_order(self):
        g, a, b, s = self._build_graph()
        order = g.topological_order()
        self.assertLess(order.index("a"), order.index("sum"))
        self.assertLess(order.index("b"), order.index("sum"))

    def test_no_cycles_in_dag(self):
        g, *_ = self._build_graph()
        self.assertEqual(g.detect_cycles(), [])

    def test_cycle_detection(self):
        g = ReactiveGraph()
        # Manually add cycle edges
        a = ReactiveVar("a", 0)
        b = ReactiveVar("b", 0)
        g.nodes["a"] = a
        g.nodes["b"] = b
        g.edges = [("a", "b"), ("b", "a")]
        cycles = g.detect_cycles()
        self.assertTrue(len(cycles) > 0)

    def test_to_dict(self):
        g, *_ = self._build_graph()
        d = g.to_dict()
        self.assertIn("nodes", d)
        self.assertIn("edges", d)
        self.assertIn("cycles", d)
        self.assertIn("topologicalOrder", d)

    def test_single_node(self):
        g = ReactiveGraph()
        g.add(ReactiveVar("solo", 99))
        self.assertEqual(len(g.nodes), 1)
        self.assertEqual(g.edges, [])
        self.assertEqual(g.topological_order(), ["solo"])

    def test_diamond_dependency(self):
        """Diamond: a -> b, a -> c, b -> d, c -> d."""
        g = ReactiveGraph()
        a = g.add(ReactiveVar("a", 1))
        b = g.add(Computed("b", [a], lambda x: x + 1))
        c = g.add(Computed("c", [a], lambda x: x * 2))
        d = g.add(Computed("d", [b, c], lambda x, y: x + y))
        order = g.topological_order()
        self.assertLess(order.index("a"), order.index("b"))
        self.assertLess(order.index("a"), order.index("c"))
        self.assertLess(order.index("b"), order.index("d"))
        self.assertLess(order.index("c"), order.index("d"))
        self.assertEqual(d.value, 4)  # (1+1) + (1*2) = 4


# ── ReflexAnalyzer ───────────────────────────────────────────────────────


class TestReflexAnalyzer(unittest.TestCase):
    """ReflexAnalyzer: static analysis of .srv source for reactive patterns."""

    def test_empty_source(self):
        a = ReflexAnalyzer("", "<test>").analyze()
        self.assertEqual(a.score, 0)
        self.assertEqual(len(a.assignments), 0)

    def test_detects_assignments(self):
        src = "x = 1\ny = 2\nx = 3"
        a = ReflexAnalyzer(src).analyze()
        self.assertIn("x", a.assignments)
        self.assertEqual(len(a.assignments["x"]), 2)

    def test_detects_set_keyword(self):
        src = "set counter = 0\nset counter = 1\nset counter = 2"
        a = ReflexAnalyzer(src).analyze()
        self.assertIn("counter", a.assignments)
        self.assertEqual(len(a.assignments["counter"]), 3)

    def test_detects_computations_with_deps(self):
        src = "a = 1\nb = 2\nc = a + b"
        a = ReflexAnalyzer(src).analyze()
        # c depends on a, b
        comp_targets = [t for _, t, _ in a.computations]
        self.assertIn("c", comp_targets)
        for line, target, deps in a.computations:
            if target == "c":
                self.assertTrue({"a", "b"}.issubset(deps))

    def test_detects_loops(self):
        src = "while running\n  x = x + 1\n  y = y * 2"
        a = ReflexAnalyzer(src).analyze()
        self.assertTrue(len(a.loops) >= 1)

    def test_detects_callbacks(self):
        src = "on_click handler\nsubscribe to events\nemit update"
        a = ReflexAnalyzer(src).analyze()
        self.assertTrue(len(a.callbacks) >= 2)

    def test_score_is_bounded(self):
        # Generate a source with many reactive patterns to max score
        lines = []
        for i in range(20):
            lines.append(f"x{i} = x{i} + 1")
            lines.append(f"set x{i} = x{i} * 2")
        lines.extend(["while true", "  val = val + 1"] * 5)
        lines.extend(["on_click fire", "subscribe events", "emit done"] * 3)
        a = ReflexAnalyzer("\n".join(lines)).analyze()
        self.assertLessEqual(a.score, 100)
        self.assertGreater(a.score, 0)

    def test_suggestions_for_reassigned_vars(self):
        src = "x = 1\nx = 2\nx = 3"
        a = ReflexAnalyzer(src).analyze()
        suggestions = [s for s in a.suggestions if s["variable"] == "x"]
        self.assertTrue(len(suggestions) >= 1)
        self.assertEqual(suggestions[0]["type"], "reactive_var")
        # 3 assignments => medium severity (high requires >= 5)
        self.assertEqual(suggestions[0]["severity"], "medium")

    def test_suggestions_severity_levels(self):
        # 2 assignments = low severity
        src = "y = 1\ny = 2"
        a = ReflexAnalyzer(src).analyze()
        y_sugg = [s for s in a.suggestions if s["variable"] == "y"]
        self.assertTrue(any(s["severity"] == "low" for s in y_sugg))

    def test_high_severity_for_many_reassignments(self):
        src = "\n".join(f"z = {i}" for i in range(6))
        a = ReflexAnalyzer(src).analyze()
        z_sugg = [s for s in a.suggestions if s["variable"] == "z"]
        self.assertTrue(any(s["severity"] == "high" for s in z_sugg))

    def test_no_self_dependency(self):
        """Variable should not list itself as a dependency in computations."""
        src = "x = x + 1"
        a = ReflexAnalyzer(src).analyze()
        for _, target, deps in a.computations:
            if target == "x":
                self.assertNotIn("x", deps)

    def test_filters_keywords_from_deps(self):
        src = "result = if true and len"
        a = ReflexAnalyzer(src).analyze()
        for _, target, deps in a.computations:
            if target == "result":
                for kw in ("if", "true", "and", "len"):
                    self.assertNotIn(kw, deps)


# ── Integration: Full reactive pipeline ──────────────────────────────────


class TestReactiveIntegration(unittest.TestCase):
    """End-to-end reactive pipeline tests."""

    def test_full_pipeline(self):
        """Build a reactive graph and verify propagation end-to-end."""
        g = ReactiveGraph()
        price = g.add(ReactiveVar("price", 100))
        qty = g.add(ReactiveVar("qty", 5))
        subtotal = g.add(Computed("subtotal", [price, qty], lambda p, q: p * q))
        tax = g.add(Computed("tax", [subtotal], lambda s: s * 0.1))
        total = g.add(Computed("total", [subtotal, tax], lambda s, t: s + t))

        self.assertEqual(total.value, 550.0)  # 500 + 50

        price.value = 200
        self.assertEqual(subtotal.value, 1000)
        self.assertEqual(tax.value, 100.0)
        self.assertEqual(total.value, 1100.0)

    def test_effect_in_pipeline(self):
        g = ReactiveGraph()
        temp = g.add(ReactiveVar("temp", 20))
        alerts = []
        g.add(Effect("alert", [temp], lambda src, vals: alerts.append(vals["temp"]) if vals["temp"] > 30 else None))
        temp.value = 25  # no alert
        self.assertEqual(len(alerts), 0)
        temp.value = 35  # alert
        self.assertEqual(alerts, [35])

    def test_stream_to_reactive_bridge(self):
        """Stream events update a ReactiveVar, propagating through graph."""
        counter = ReactiveVar("counter", 0)
        clicks = Stream("clicks")
        clicks.subscribe(lambda _: setattr(counter, 'value', counter.value + 1))

        computed_label = Computed("label", [counter], lambda c: f"Clicks: {c}")

        clicks.emit("click")
        clicks.emit("click")
        clicks.emit("click")
        self.assertEqual(counter.value, 3)
        self.assertEqual(computed_label.value, "Clicks: 3")


if __name__ == "__main__":
    unittest.main()
