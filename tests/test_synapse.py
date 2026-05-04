"""Tests for sauravsynapse — autonomous code neural network analyzer."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from sauravsynapse import (
    Neuron, Synapse, SignalPath, Bottleneck, NetworkReport,
    parse_file, classify_neurons, map_synapses, analyze_propagation,
    compute_plasticity, detect_bottlenecks, compute_health_score,
    generate_insights, analyze, generate_html_report, main,
    _html_esc, SENSORY_CALLS, MOTOR_CALLS,
)


def _write_srv(content: str) -> str:
    """Write content to a temp .srv file and return path."""
    fd, path = tempfile.mkstemp(suffix='.srv')
    os.write(fd, content.encode('utf-8'))
    os.close(fd)
    return path


class TestParseFile(unittest.TestCase):
    """Test .srv file parsing into neurons."""

    def test_empty_file(self):
        path = _write_srv("")
        neurons = parse_file(path)
        self.assertEqual(neurons, [])
        os.unlink(path)

    def test_single_function(self):
        path = _write_srv("function hello\n    print(\"hi\")\n")
        neurons = parse_file(path)
        self.assertEqual(len(neurons), 1)
        self.assertEqual(neurons[0].name, "hello")
        os.unlink(path)

    def test_multiple_functions(self):
        code = "function a\n    x = 1\nfunction b\n    y = 2\nfunction c\n    z = 3\n"
        path = _write_srv(code)
        neurons = parse_file(path)
        self.assertEqual(len(neurons), 3)
        names = [n.name for n in neurons]
        self.assertIn("a", names)
        self.assertIn("b", names)
        self.assertIn("c", names)
        os.unlink(path)

    def test_fn_keyword(self):
        path = _write_srv("fn greet name\n    println(name)\n")
        neurons = parse_file(path)
        self.assertEqual(len(neurons), 1)
        self.assertEqual(neurons[0].name, "greet")
        os.unlink(path)

    def test_calls_detected(self):
        code = "function process\n    data = read_file(\"x.txt\")\n    result = transform(data)\n    write_file(result)\n"
        path = _write_srv(code)
        neurons = parse_file(path)
        self.assertEqual(len(neurons), 1)
        self.assertIn("read_file", neurons[0].calls_out)
        self.assertIn("transform", neurons[0].calls_out)
        self.assertIn("write_file", neurons[0].calls_out)
        os.unlink(path)

    def test_sensory_signals_counted(self):
        code = "function load_data\n    a = read_file(\"x\")\n    b = http_get(url)\n    c = parse_json(b)\n"
        path = _write_srv(code)
        neurons = parse_file(path)
        self.assertEqual(neurons[0].sensory_signals, 3)
        os.unlink(path)

    def test_motor_signals_counted(self):
        code = "function output\n    print(x)\n    println(y)\n    write_file(z)\n"
        path = _write_srv(code)
        neurons = parse_file(path)
        self.assertEqual(neurons[0].motor_signals, 3)
        os.unlink(path)

    def test_loc_counted(self):
        code = "function big\n    a = 1\n    b = 2\n    c = 3\n    d = 4\n    e = 5\n"
        path = _write_srv(code)
        neurons = parse_file(path)
        self.assertEqual(neurons[0].loc, 5)
        os.unlink(path)

    def test_complexity_branches(self):
        code = "function complex\n    if x > 0\n        while y < 10\n            for i in items\n                z = 1\n"
        path = _write_srv(code)
        neurons = parse_file(path)
        self.assertEqual(neurons[0].complexity, 4)  # 1 base + 3 branches
        os.unlink(path)

    def test_params_detected(self):
        code = "fn compute x y z\n    return x + y + z\n"
        path = _write_srv(code)
        neurons = parse_file(path)
        self.assertEqual(neurons[0].params, 3)
        os.unlink(path)

    def test_nonexistent_file(self):
        neurons = parse_file("/nonexistent/file.srv")
        self.assertEqual(neurons, [])

    def test_comments_skipped(self):
        code = "# comment\nfunction hello\n    # inner comment\n    x = 1\n"
        path = _write_srv(code)
        neurons = parse_file(path)
        self.assertEqual(len(neurons), 1)
        self.assertEqual(neurons[0].loc, 1)
        os.unlink(path)


class TestNeuronClassifier(unittest.TestCase):
    """Test S001: Neuron classification."""

    def test_sensory_classification(self):
        n = Neuron(name="loader", file="a.srv", line=1, sensory_signals=3, motor_signals=0)
        result = classify_neurons([n])
        self.assertEqual(result[0].neuron_type, "Sensory")

    def test_motor_classification(self):
        n = Neuron(name="writer", file="a.srv", line=1, sensory_signals=0, motor_signals=4)
        result = classify_neurons([n])
        self.assertEqual(result[0].neuron_type, "Motor")

    def test_interneuron_classification(self):
        n = Neuron(name="compute", file="a.srv", line=1, sensory_signals=0, motor_signals=0)
        result = classify_neurons([n])
        self.assertEqual(result[0].neuron_type, "Interneuron")

    def test_mixed_defaults_to_sensory(self):
        n = Neuron(name="mix", file="a.srv", line=1, sensory_signals=3, motor_signals=3)
        result = classify_neurons([n])
        self.assertEqual(result[0].neuron_type, "Sensory")  # >= means Sensory

    def test_hub_detection(self):
        # Create neurons where one has very high connectivity
        neurons = []
        hub = Neuron(name="hub", file="a.srv", line=1)
        hub.calls_out = ["a", "b", "c", "d", "e", "f", "g", "h"]
        neurons.append(hub)
        for name in "abcdefgh":
            n = Neuron(name=name, file="a.srv", line=1)
            n.calls_out = ["hub"]
            neurons.append(n)
        result = classify_neurons(neurons)
        hub_result = [n for n in result if n.name == "hub"][0]
        self.assertTrue(hub_result.is_hub)

    def test_isolated_detection(self):
        n1 = Neuron(name="connected", file="a.srv", line=1)
        n1.calls_out = ["isolated"]
        n2 = Neuron(name="isolated", file="a.srv", line=2)
        n3 = Neuron(name="lonely", file="a.srv", line=3)
        result = classify_neurons([n1, n2, n3])
        lonely = [n for n in result if n.name == "lonely"][0]
        self.assertTrue(lonely.is_isolated)

    def test_empty_list(self):
        result = classify_neurons([])
        self.assertEqual(result, [])

    def test_called_by_populated(self):
        n1 = Neuron(name="caller", file="a.srv", line=1)
        n1.calls_out = ["callee"]
        n2 = Neuron(name="callee", file="a.srv", line=2)
        result = classify_neurons([n1, n2])
        callee = [n for n in result if n.name == "callee"][0]
        self.assertIn("caller", callee.called_by)


class TestSynapseMapper(unittest.TestCase):
    """Test S002: Synapse mapping."""

    def test_basic_synapse(self):
        n1 = Neuron(name="a", file="x.srv", line=1)
        n1.calls_out = ["b"]
        n2 = Neuron(name="b", file="x.srv", line=5)
        synapses = map_synapses([n1, n2])
        self.assertEqual(len(synapses), 1)
        self.assertEqual(synapses[0].source, "a")
        self.assertEqual(synapses[0].target, "b")

    def test_weight_accumulation(self):
        n1 = Neuron(name="a", file="x.srv", line=1)
        n1.calls_out = ["b", "b", "b"]
        n2 = Neuron(name="b", file="x.srv", line=5)
        synapses = map_synapses([n1, n2])
        self.assertEqual(len(synapses), 1)
        self.assertEqual(synapses[0].weight, 3)

    def test_self_calls_excluded(self):
        n1 = Neuron(name="recurse", file="x.srv", line=1)
        n1.calls_out = ["recurse"]
        synapses = map_synapses([n1])
        self.assertEqual(len(synapses), 0)

    def test_unknown_targets_excluded(self):
        n1 = Neuron(name="a", file="x.srv", line=1)
        n1.calls_out = ["unknown_func"]
        synapses = map_synapses([n1])
        self.assertEqual(len(synapses), 0)

    def test_excitatory_type(self):
        n1 = Neuron(name="a", file="x.srv", line=1)
        n1.calls_out = ["b"]
        n1.guard_context_calls = 0
        n2 = Neuron(name="b", file="x.srv", line=5)
        synapses = map_synapses([n1, n2])
        self.assertEqual(synapses[0].synapse_type, "excitatory")

    def test_inhibitory_type(self):
        n1 = Neuron(name="validator", file="x.srv", line=1)
        n1.calls_out = ["check"]
        n1.guard_context_calls = 1  # All calls are in guard context
        n2 = Neuron(name="check", file="x.srv", line=5)
        synapses = map_synapses([n1, n2])
        self.assertEqual(synapses[0].synapse_type, "inhibitory")

    def test_no_neurons(self):
        self.assertEqual(map_synapses([]), [])

    def test_multiple_sources(self):
        n1 = Neuron(name="a", file="x.srv", line=1)
        n1.calls_out = ["c"]
        n2 = Neuron(name="b", file="x.srv", line=3)
        n2.calls_out = ["c"]
        n3 = Neuron(name="c", file="x.srv", line=5)
        synapses = map_synapses([n1, n2, n3])
        self.assertEqual(len(synapses), 2)


class TestSignalPropagation(unittest.TestCase):
    """Test S003: Signal propagation analysis."""

    def test_simple_path(self):
        n1 = Neuron(name="input", file="a.srv", line=1)
        n1.neuron_type = "Sensory"
        n2 = Neuron(name="process", file="a.srv", line=5)
        n2.neuron_type = "Interneuron"
        n3 = Neuron(name="output", file="a.srv", line=10)
        n3.neuron_type = "Motor"
        synapses = [
            Synapse(source="input", target="process"),
            Synapse(source="process", target="output"),
        ]
        paths = analyze_propagation([n1, n2, n3], synapses)
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0].length, 2)
        self.assertEqual(paths[0].path, ["input", "process", "output"])

    def test_no_paths(self):
        n1 = Neuron(name="a", file="a.srv", line=1)
        n1.neuron_type = "Interneuron"
        paths = analyze_propagation([n1], [])
        self.assertEqual(paths, [])

    def test_empty_input(self):
        self.assertEqual(analyze_propagation([], []), [])

    def test_multiple_paths(self):
        n1 = Neuron(name="s1", file="a.srv", line=1)
        n1.neuron_type = "Sensory"
        n2 = Neuron(name="s2", file="a.srv", line=2)
        n2.neuron_type = "Sensory"
        n3 = Neuron(name="m", file="a.srv", line=3)
        n3.neuron_type = "Motor"
        synapses = [
            Synapse(source="s1", target="m"),
            Synapse(source="s2", target="m"),
        ]
        paths = analyze_propagation([n1, n2, n3], synapses)
        self.assertEqual(len(paths), 2)

    def test_no_motor_neurons(self):
        n1 = Neuron(name="s", file="a.srv", line=1)
        n1.neuron_type = "Sensory"
        n2 = Neuron(name="i", file="a.srv", line=2)
        n2.neuron_type = "Interneuron"
        synapses = [Synapse(source="s", target="i")]
        paths = analyze_propagation([n1, n2], synapses)
        self.assertEqual(paths, [])

    def test_path_length_limit(self):
        # Create a long chain that exceeds 20 hops
        neurons = []
        synapses = []
        for i in range(25):
            n = Neuron(name=f"n{i}", file="a.srv", line=i)
            n.neuron_type = "Sensory" if i == 0 else ("Motor" if i == 24 else "Interneuron")
            neurons.append(n)
        for i in range(24):
            synapses.append(Synapse(source=f"n{i}", target=f"n{i+1}"))
        paths = analyze_propagation(neurons, synapses)
        # Should not find path since chain > 20
        self.assertEqual(len(paths), 0)


class TestPlasticity(unittest.TestCase):
    """Test S004: Plasticity analyzer."""

    def test_empty_returns_50(self):
        self.assertEqual(compute_plasticity([], []), 50.0)

    def test_simple_neurons(self):
        neurons = [Neuron(name="a", file="x.srv", line=1, loc=5, params=2, complexity=1)]
        score = compute_plasticity(neurons, [])
        self.assertGreater(score, 0)
        self.assertLessEqual(score, 100)

    def test_high_coupling_reduces_plasticity(self):
        # Many outgoing calls = lower plasticity
        n = Neuron(name="coupled", file="x.srv", line=1, loc=5)
        n.calls_out = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]
        low = compute_plasticity([n], [])

        n2 = Neuron(name="decoupled", file="x.srv", line=1, loc=5)
        n2.calls_out = ["a"]
        high = compute_plasticity([n2], [])

        self.assertGreater(high, low)

    def test_small_functions_more_plastic(self):
        small = [Neuron(name="s", file="x.srv", line=1, loc=5)]
        big = [Neuron(name="b", file="x.srv", line=1, loc=80)]
        self.assertGreater(compute_plasticity(small, []), compute_plasticity(big, []))

    def test_score_bounded(self):
        neurons = [Neuron(name=f"n{i}", file="x.srv", line=i, loc=100, complexity=20) for i in range(10)]
        score = compute_plasticity(neurons, [])
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)


class TestBottleneckDetector(unittest.TestCase):
    """Test S005: Bottleneck detection."""

    def test_empty(self):
        self.assertEqual(detect_bottlenecks([]), [])

    def test_no_bottlenecks(self):
        neurons = [Neuron(name=f"n{i}", file="x.srv", line=i) for i in range(3)]
        result = detect_bottlenecks(neurons)
        self.assertEqual(result, [])

    def test_chokepoint_detected(self):
        neurons = []
        # Create a chokepoint with high in/out degree
        choke = Neuron(name="choke", file="x.srv", line=1)
        choke.called_by = [f"caller{i}" for i in range(8)]
        choke.calls_out = ["target1", "target2", "target3", "target4"]
        neurons.append(choke)
        # Add normal neurons
        for i in range(5):
            n = Neuron(name=f"normal{i}", file="x.srv", line=i+2)
            neurons.append(n)
        result = detect_bottlenecks(neurons)
        chokepoints = [b for b in result if b.category == "chokepoint"]
        self.assertGreater(len(chokepoints), 0)

    def test_overloaded_hub(self):
        neurons = []
        hub = Neuron(name="hub", file="x.srv", line=1, is_hub=True)
        hub.called_by = ["a", "b"]
        hub.calls_out = ["c", "d"]
        neurons.append(hub)
        for i in range(5):
            neurons.append(Neuron(name=f"n{i}", file="x.srv", line=i+2))
        result = detect_bottlenecks(neurons)
        hubs = [b for b in result if b.category == "overloaded_hub"]
        self.assertGreater(len(hubs), 0)

    def test_starved_neuron(self):
        n = Neuron(name="starved", file="x.srv", line=1)
        n.called_by = []
        n.calls_out = ["something", "else"]
        n.neuron_type = "Interneuron"
        neurons = [n] + [Neuron(name=f"n{i}", file="x.srv", line=i+2) for i in range(3)]
        result = detect_bottlenecks(neurons)
        starved = [b for b in result if b.category == "starved"]
        self.assertGreater(len(starved), 0)


class TestHealthScorer(unittest.TestCase):
    """Test S006: Network health scoring."""

    def test_empty_returns_functional(self):
        score, tier = compute_health_score([], [], [], 50.0, [])
        self.assertEqual(score, 50.0)
        self.assertEqual(tier, "Functional")

    def test_healthy_network(self):
        neurons = [
            Neuron(name="s", file="x.srv", line=1),
            Neuron(name="i", file="x.srv", line=2),
            Neuron(name="m", file="x.srv", line=3),
        ]
        neurons[0].neuron_type = "Sensory"
        neurons[1].neuron_type = "Interneuron"
        neurons[2].neuron_type = "Motor"
        synapses = [Synapse(source="s", target="i"), Synapse(source="i", target="m")]
        paths = [SignalPath(path=["s", "i", "m"], length=2)]
        score, tier = compute_health_score(neurons, synapses, paths, 80.0, [])
        self.assertGreater(score, 50)

    def test_bottlenecks_reduce_score(self):
        neurons = [Neuron(name="n", file="x.srv", line=1)]
        neurons[0].neuron_type = "Interneuron"
        no_bn_score, _ = compute_health_score(neurons, [], [], 70.0, [])
        bns = [Bottleneck(neuron="n", category="chokepoint", severity="critical")]
        bn_score, _ = compute_health_score(neurons, [], [], 70.0, bns)
        self.assertGreater(no_bn_score, bn_score)

    def test_tier_boundaries(self):
        # Test that tier names are correct
        neurons = [Neuron(name="n", file="x.srv", line=1)]
        neurons[0].neuron_type = "Interneuron"
        _, tier = compute_health_score(neurons, [], [], 90.0, [])
        # Score will depend on all factors, just verify it returns a valid tier
        self.assertIn(tier, ["Genius", "Healthy", "Functional", "Degraded", "Damaged"])


class TestInsightGenerator(unittest.TestCase):
    """Test S007: Insight generation."""

    def test_no_neurons(self):
        insights = generate_insights([], [], [], [], 50.0, 50.0)
        self.assertIn("No neurons found", insights[0])

    def test_no_motor_insight(self):
        neurons = [Neuron(name="a", file="x.srv", line=1)]
        neurons[0].neuron_type = "Sensory"
        insights = generate_insights(neurons, [], [], [], 50.0, 50.0)
        self.assertTrue(any("motor" in i.lower() for i in insights))

    def test_no_sensory_insight(self):
        neurons = [Neuron(name="a", file="x.srv", line=1)]
        neurons[0].neuron_type = "Motor"
        insights = generate_insights(neurons, [], [], [], 50.0, 50.0)
        self.assertTrue(any("sensory" in i.lower() for i in insights))

    def test_low_plasticity_insight(self):
        neurons = [Neuron(name="a", file="x.srv", line=1)]
        neurons[0].neuron_type = "Interneuron"
        insights = generate_insights(neurons, [], [], [], 30.0, 50.0)
        self.assertTrue(any("plasticity" in i.lower() for i in insights))

    def test_chokepoint_insight(self):
        neurons = [Neuron(name="a", file="x.srv", line=1)]
        neurons[0].neuron_type = "Interneuron"
        bns = [Bottleneck(neuron="a::choke", category="chokepoint", severity="critical")]
        insights = generate_insights(neurons, [], [], bns, 70.0, 50.0)
        self.assertTrue(any("chokepoint" in i.lower() or "splitting" in i.lower() for i in insights))

    def test_high_health_praise(self):
        neurons = [Neuron(name="a", file="x.srv", line=1)]
        neurons[0].neuron_type = "Interneuron"
        insights = generate_insights(neurons, [], [], [], 90.0, 90.0)
        self.assertTrue(any("excellent" in i.lower() for i in insights))


class TestAnalyze(unittest.TestCase):
    """Test full analysis pipeline."""

    def test_analyze_empty_dir(self):
        with tempfile.TemporaryDirectory() as td:
            report = analyze([td])
            self.assertEqual(report.total_neurons, 0)
            self.assertEqual(report.files_scanned, 0)

    def test_analyze_single_file(self):
        with tempfile.TemporaryDirectory() as td:
            fpath = os.path.join(td, "test.srv")
            with open(fpath, 'w') as f:
                f.write("function hello\n    print(\"world\")\n")
            report = analyze([td])
            self.assertEqual(report.files_scanned, 1)
            self.assertEqual(report.total_neurons, 1)
            self.assertGreater(report.health_score, 0)

    def test_analyze_complex_project(self):
        with tempfile.TemporaryDirectory() as td:
            # Create a small project with multiple files
            with open(os.path.join(td, "input.srv"), 'w') as f:
                f.write("function load_data\n    data = read_file(\"data.txt\")\n    return process(data)\n")
            with open(os.path.join(td, "process.srv"), 'w') as f:
                f.write("function process data\n    result = transform(data)\n    return result\n")
            with open(os.path.join(td, "output.srv"), 'w') as f:
                f.write("function display result\n    print(result)\n    println(\"done\")\n")
            report = analyze([td])
            self.assertEqual(report.files_scanned, 3)
            self.assertEqual(report.total_neurons, 3)
            # Should have all three types
            self.assertIn("Sensory", report.neuron_distribution)
            self.assertIn("Motor", report.neuron_distribution)


class TestHtmlReport(unittest.TestCase):
    """Test HTML report generation."""

    def test_generates_valid_html(self):
        report = NetworkReport(
            timestamp="2026-05-03T23:00:00",
            files_scanned=1, total_neurons=2,
            health_score=75.0, health_tier="Healthy",
            plasticity_score=80.0,
            neuron_distribution={"Sensory": 1, "Motor": 1},
            neurons=[
                {'name': 'a', 'file': 'x.srv', 'type': 'Sensory', 'is_hub': False,
                 'is_isolated': False, 'in_degree': 0, 'out_degree': 1, 'complexity': 1},
            ],
            synapses=[{'source': 'a', 'target': 'b', 'weight': 1, 'type': 'excitatory'}],
            bottlenecks=[], signal_paths=[], insights=["Test insight"],
            avg_path_length=0, max_path_length=0, connectivity_density=0.5,
        )
        html = generate_html_report(report)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("sauravsynapse", html)
        self.assertIn("Neural Network Report", html)
        self.assertIn("75.0", html)
        self.assertIn("Healthy", html)

    def test_html_escaping(self):
        self.assertEqual(_html_esc("<script>"), "&lt;script&gt;")
        self.assertEqual(_html_esc('"hello"'), "&quot;hello&quot;")
        self.assertEqual(_html_esc("a & b"), "a &amp; b")


class TestCLI(unittest.TestCase):
    """Test CLI interface."""

    def test_json_output(self):
        with tempfile.TemporaryDirectory() as td:
            fpath = os.path.join(td, "test.srv")
            with open(fpath, 'w') as f:
                f.write("function test\n    x = 1\n")
            import io
            from contextlib import redirect_stdout
            buf = io.StringIO()
            with redirect_stdout(buf):
                main([td, '--json'])
            output = buf.getvalue()
            data = json.loads(output)
            self.assertIn('health_score', data)
            self.assertIn('neurons', data)
            self.assertIn('health_tier', data)

    def test_html_output(self):
        with tempfile.TemporaryDirectory() as td:
            fpath = os.path.join(td, "test.srv")
            with open(fpath, 'w') as f:
                f.write("function hello\n    print(\"hi\")\n")
            html_path = os.path.join(td, "report.html")
            main([td, '--html', html_path])
            self.assertTrue(os.path.exists(html_path))
            with open(html_path) as f:
                content = f.read()
            self.assertIn("<!DOCTYPE html>", content)

    def test_no_color_flag(self):
        import sauravsynapse
        old = sauravsynapse.USE_COLOR
        with tempfile.TemporaryDirectory() as td:
            main([td, '--no-color'])
        self.assertFalse(sauravsynapse.USE_COLOR)
        sauravsynapse.USE_COLOR = old

    def test_neurons_flag(self):
        with tempfile.TemporaryDirectory() as td:
            fpath = os.path.join(td, "test.srv")
            with open(fpath, 'w') as f:
                f.write("function a\n    b()\nfunction b\n    print(x)\n")
            # Should not raise
            import io
            from contextlib import redirect_stdout
            buf = io.StringIO()
            with redirect_stdout(buf):
                main([td, '--neurons', '--no-color'])
            self.assertIn("NEURON", buf.getvalue())

    def test_default_summary(self):
        with tempfile.TemporaryDirectory() as td:
            fpath = os.path.join(td, "test.srv")
            with open(fpath, 'w') as f:
                f.write("function x\n    y()\n")
            import io
            from contextlib import redirect_stdout
            buf = io.StringIO()
            with redirect_stdout(buf):
                main([td, '--no-color'])
            self.assertIn("Health Score", buf.getvalue())


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def test_single_function_no_calls(self):
        path = _write_srv("function lonely\n    x = 1\n")
        neurons = parse_file(path)
        neurons = classify_neurons(neurons)
        self.assertTrue(neurons[0].is_isolated)
        os.unlink(path)

    def test_circular_calls(self):
        n1 = Neuron(name="a", file="x.srv", line=1)
        n1.calls_out = ["b"]
        n2 = Neuron(name="b", file="x.srv", line=2)
        n2.calls_out = ["a"]
        synapses = map_synapses(classify_neurons([n1, n2]))
        self.assertEqual(len(synapses), 2)

    def test_deeply_nested_function(self):
        code = "function deep\n" + "".join(f"{'    ' * (i+1)}if x{i}\n" for i in range(10))
        path = _write_srv(code)
        neurons = parse_file(path)
        self.assertEqual(neurons[0].complexity, 11)  # 1 base + 10 branches
        os.unlink(path)

    def test_many_neurons_performance(self):
        # Verify analyze handles many functions
        neurons = [Neuron(name=f"fn{i}", file="x.srv", line=i) for i in range(100)]
        for i, n in enumerate(neurons):
            if i > 0:
                n.calls_out = [f"fn{i-1}"]
        classified = classify_neurons(neurons)
        self.assertEqual(len(classified), 100)

    def test_health_score_range(self):
        # Various configurations should always give 0-100
        for plasticity in [0, 25, 50, 75, 100]:
            score, tier = compute_health_score(
                [Neuron(name="n", file="x.srv", line=1)], [], [], plasticity, []
            )
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 100)
            self.assertIn(tier, ["Genius", "Healthy", "Functional", "Degraded", "Damaged"])


if __name__ == '__main__':
    unittest.main()
