#!/usr/bin/env python3
"""Tests for sauravpulse — autonomous codebase vital signs monitor."""

import json
import math
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from io import StringIO

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sauravpulse import (
    FunctionInfo, VitalSign, Correlation, PulseReport,
    _parse_file, compute_heart_rate, compute_blood_pressure,
    compute_temperature, compute_respiratory_rate, compute_oxygen_saturation,
    compute_reflexes, compute_immune_response, compute_neural_activity,
    detect_correlations, compute_pulse_score, generate_insights,
    rank_worst_functions, analyze_pulse, _generate_html, main,
    load_history, save_history, clear_history,
)


def _write_srv(tmpdir, name, content):
    path = os.path.join(tmpdir, name)
    with open(path, 'w') as f:
        f.write(content)
    return path


SIMPLE_SRV = """\
# A simple program
function greet name
    println "Hello " + name
end

function add x y
    result = x + y
    return result
end
"""

COMPLEX_SRV = """\
function beast a b c d e
    if a > 0
        if b > 0
            if c > 0
                for i in range(d)
                    if e > i
                        val = compute(a, b, c)
                        data = read_file("x.txt")
                    end
                end
            end
        end
    end
end

function another_beast x
    if x > 0
        if x > 10
            if x > 100
                for j in range(x)
                    while j > 0
                        process(j)
                    end
                end
            end
        end
    end
end
"""

GUARDED_SRV = """\
# Well-guarded function
function safe_process input
    assert input != null
    if len(input) == 0
        throw "empty input"
    end
    if len(input) > 1000
        throw "input too large"
    end
    return process(input)
end

# Another guarded function
function safe_read path
    assert path != null
    try
        data = read_file(path)
    catch err
        throw "read failed: " + err
    end
    return data
end
"""

MIXED_SRV = """\
function tiny
    return 1
end

function medium_one a b
    if a > b
        result = a - b
    elif b > a
        result = b - a
    end
    return result
end

function bigFunction x y z w
    data = read_file("config.txt")
    parsed = parse_json(data)
    result = compute(x, y)
    if result > 0
        for i in range(z)
            if i > w
                process(i, result)
            end
        end
    end
    return result
end
"""


class TestParseFile(unittest.TestCase):
    def test_parse_simple(self):
        d = tempfile.mkdtemp()
        path = _write_srv(d, "simple.srv", SIMPLE_SRV)
        fns, total, comments = _parse_file(path)
        self.assertEqual(len(fns), 2)
        self.assertEqual(fns[0].name, "greet")
        self.assertEqual(fns[1].name, "add")
        self.assertGreater(total, 0)
        self.assertGreater(comments, 0)

    def test_parse_complex(self):
        d = tempfile.mkdtemp()
        path = _write_srv(d, "complex.srv", COMPLEX_SRV)
        fns, _, _ = _parse_file(path)
        self.assertEqual(len(fns), 2)
        self.assertGreater(fns[0].complexity, 3)
        self.assertGreater(fns[0].max_depth, 2)

    def test_parse_empty_file(self):
        d = tempfile.mkdtemp()
        path = _write_srv(d, "empty.srv", "")
        fns, total, comments = _parse_file(path)
        self.assertEqual(len(fns), 0)
        self.assertEqual(total, 0)

    def test_parse_no_functions(self):
        d = tempfile.mkdtemp()
        path = _write_srv(d, "nofn.srv", "# Just comments\n# More comments\nx = 1\n")
        fns, _, comments = _parse_file(path)
        self.assertEqual(len(fns), 0)
        self.assertEqual(comments, 2)

    def test_parse_guarded(self):
        d = tempfile.mkdtemp()
        path = _write_srv(d, "guarded.srv", GUARDED_SRV)
        fns, _, _ = _parse_file(path)
        self.assertEqual(len(fns), 2)
        self.assertGreater(fns[0].guard_count, 0)
        self.assertTrue(fns[0].has_doc_comment)

    def test_parse_risky_calls(self):
        d = tempfile.mkdtemp()
        path = _write_srv(d, "risky.srv", MIXED_SRV)
        fns, _, _ = _parse_file(path)
        big = [f for f in fns if f.name == "bigFunction"][0]
        self.assertGreater(big.risky_calls, 0)

    def test_nonexistent_file(self):
        fns, total, comments = _parse_file("/nonexistent/file.srv")
        self.assertEqual(len(fns), 0)
        self.assertEqual(total, 0)


class TestVitalSignClassify(unittest.TestCase):
    def test_optimal(self):
        v = VitalSign(code="P001", name="Test", score=85)
        v.classify()
        self.assertEqual(v.status, "Optimal")

    def test_normal(self):
        v = VitalSign(code="P001", name="Test", score=65)
        v.classify()
        self.assertEqual(v.status, "Normal")

    def test_concerning(self):
        v = VitalSign(code="P001", name="Test", score=45)
        v.classify()
        self.assertEqual(v.status, "Concerning")

    def test_critical(self):
        v = VitalSign(code="P001", name="Test", score=20)
        v.classify()
        self.assertEqual(v.status, "Critical")


class TestHeartRate(unittest.TestCase):
    def test_empty(self):
        vs = compute_heart_rate({})
        self.assertEqual(vs.score, 0.0)

    def test_single_file_few_fns(self):
        fns = [FunctionInfo(name=f"fn{i}", file="a.srv", line=i) for i in range(3)]
        vs = compute_heart_rate({"a.srv": fns})
        self.assertGreater(vs.score, 0)

    def test_multiple_files(self):
        d = {f"f{i}.srv": [FunctionInfo(name=f"fn{j}", file=f"f{i}.srv", line=j)
                           for j in range(5)]
             for i in range(3)}
        vs = compute_heart_rate(d)
        self.assertGreater(vs.score, 50)


class TestBloodPressure(unittest.TestCase):
    def test_empty(self):
        vs = compute_blood_pressure({}, {}, {})
        self.assertEqual(vs.score, 50.0)

    def test_well_documented(self):
        fns = [FunctionInfo(name="f1", file="a.srv", line=1, complexity=2, has_doc_comment=True),
               FunctionInfo(name="f2", file="a.srv", line=5, complexity=1, has_doc_comment=True)]
        vs = compute_blood_pressure({"a.srv": fns}, {"a.srv": 5}, {"a.srv": 20})
        self.assertGreater(vs.score, 40)

    def test_high_complexity_undocumented(self):
        fns = [FunctionInfo(name="f1", file="a.srv", line=1, complexity=10, has_doc_comment=False)]
        vs = compute_blood_pressure({"a.srv": fns}, {"a.srv": 0}, {"a.srv": 50})
        self.assertLess(vs.score, 60)


class TestTemperature(unittest.TestCase):
    def test_no_hotspots(self):
        fns = [FunctionInfo(name="f1", file="a.srv", line=1, loc=10, complexity=2, max_depth=1)]
        vs = compute_temperature({"a.srv": fns})
        self.assertGreater(vs.score, 70)

    def test_all_hotspots(self):
        fns = [FunctionInfo(name="f1", file="a.srv", line=1, loc=50, complexity=8, max_depth=5,
                            calls=list(range(12)))]
        vs = compute_temperature({"a.srv": fns})
        self.assertLess(vs.score, 50)

    def test_empty(self):
        vs = compute_temperature({})
        self.assertEqual(vs.score, 80.0)


class TestRespiratoryRate(unittest.TestCase):
    def test_consistent_sizes(self):
        fns = [FunctionInfo(name=f"fn_{i}", file="a.srv", line=i, loc=10) for i in range(5)]
        vs = compute_respiratory_rate({"a.srv": fns})
        self.assertGreater(vs.score, 60)

    def test_wildly_inconsistent(self):
        fns = [FunctionInfo(name=f"fn_{i}", file="a.srv", line=i, loc=i * 50 + 1) for i in range(5)]
        vs = compute_respiratory_rate({"a.srv": fns})
        # Should have lower score due to high CV
        self.assertLess(vs.score, 90)

    def test_too_few(self):
        fns = [FunctionInfo(name="fn_one", file="a.srv", line=1, loc=10)]
        vs = compute_respiratory_rate({"a.srv": fns})
        self.assertEqual(vs.score, 70.0)


class TestOxygenSaturation(unittest.TestCase):
    def test_all_tested(self):
        fns = [FunctionInfo(name="greet", file="a.srv", line=1),
               FunctionInfo(name="add", file="a.srv", line=5)]
        contents = {"a.srv": "", "test_a.srv": "test greet add function calls"}
        vs = compute_oxygen_saturation({"a.srv": fns}, contents)
        self.assertGreater(vs.score, 50)

    def test_none_tested(self):
        fns = [FunctionInfo(name="unique_func_xyz", file="a.srv", line=1)]
        contents = {"a.srv": "", "test_a.srv": "nothing relevant here"}
        vs = compute_oxygen_saturation({"a.srv": fns}, contents)
        self.assertEqual(vs.score, 0.0)

    def test_empty(self):
        vs = compute_oxygen_saturation({}, {})
        self.assertEqual(vs.score, 50.0)


class TestReflexes(unittest.TestCase):
    def test_no_risky_calls(self):
        fns = [FunctionInfo(name="f1", file="a.srv", line=1)]
        vs = compute_reflexes({"a.srv": fns})
        self.assertEqual(vs.score, 90.0)

    def test_risky_with_handling(self):
        fns = [FunctionInfo(name="f1", file="a.srv", line=1, risky_calls=2, try_catch_blocks=1)]
        vs = compute_reflexes({"a.srv": fns})
        self.assertEqual(vs.score, 100.0)

    def test_risky_without_handling(self):
        fns = [FunctionInfo(name="f1", file="a.srv", line=1, risky_calls=2, try_catch_blocks=0)]
        vs = compute_reflexes({"a.srv": fns})
        self.assertEqual(vs.score, 0.0)


class TestImmuneResponse(unittest.TestCase):
    def test_guarded(self):
        fns = [FunctionInfo(name="f1", file="a.srv", line=1, guard_count=3),
               FunctionInfo(name="f2", file="a.srv", line=5, guard_count=1)]
        vs = compute_immune_response({"a.srv": fns})
        self.assertGreater(vs.score, 50)

    def test_unguarded(self):
        fns = [FunctionInfo(name="f1", file="a.srv", line=1, guard_count=0)]
        vs = compute_immune_response({"a.srv": fns})
        self.assertLess(vs.score, 20)

    def test_empty(self):
        vs = compute_immune_response({})
        self.assertEqual(vs.score, 50.0)


class TestNeuralActivity(unittest.TestCase):
    def test_simple_functions(self):
        fns = [FunctionInfo(name="f1", file="a.srv", line=1, loc=5, complexity=1,
                            max_depth=1, nesting_sum=3, calls=["a"])]
        vs = compute_neural_activity({"a.srv": fns})
        self.assertGreater(vs.score, 50)

    def test_complex_functions(self):
        fns = [FunctionInfo(name="f1", file="a.srv", line=1, loc=5, complexity=10,
                            max_depth=6, nesting_sum=100, calls=list("abcdefghij"))]
        vs = compute_neural_activity({"a.srv": fns})
        self.assertLess(vs.score, 50)

    def test_empty(self):
        vs = compute_neural_activity({})
        self.assertEqual(vs.score, 80.0)


class TestCorrelations(unittest.TestCase):
    def _vs(self, code, score):
        v = VitalSign(code=code, name=code, score=score)
        v.classify()
        return v

    def test_untested_hotspots(self):
        vitals = {
            'P003': self._vs('P003', 30),
            'P005': self._vs('P005', 30),
        }
        corrs = detect_correlations(vitals)
        critical = [c for c in corrs if c.severity == "critical"]
        self.assertGreater(len(critical), 0)

    def test_fragile_core(self):
        vitals = {
            'P002': self._vs('P002', 30),
            'P007': self._vs('P007', 30),
        }
        corrs = detect_correlations(vitals)
        self.assertGreater(len(corrs), 0)

    def test_no_correlations_healthy(self):
        vitals = {f'P00{i}': self._vs(f'P00{i}', 90) for i in range(1, 9)}
        corrs = detect_correlations(vitals)
        self.assertEqual(len(corrs), 0)

    def test_cognitive_chaos(self):
        vitals = {
            'P004': self._vs('P004', 30),
            'P008': self._vs('P008', 30),
        }
        corrs = detect_correlations(vitals)
        has_chaos = any("cognitive chaos" in c.description.lower() or "chaos" in c.description.lower()
                        for c in corrs)
        self.assertTrue(has_chaos)

    def test_no_safety_net(self):
        vitals = {
            'P006': self._vs('P006', 30),
            'P007': self._vs('P007', 30),
        }
        corrs = detect_correlations(vitals)
        has_safety = any("safety net" in c.description.lower() for c in corrs)
        self.assertTrue(has_safety)


class TestPulseScore(unittest.TestCase):
    def test_all_high(self):
        vitals = [VitalSign(code=f"P00{i}", name=f"V{i}", score=90) for i in range(1, 9)]
        score, cls = compute_pulse_score(vitals)
        self.assertGreaterEqual(score, 85)
        self.assertEqual(cls, "Thriving")

    def test_all_low(self):
        vitals = [VitalSign(code=f"P00{i}", name=f"V{i}", score=20) for i in range(1, 9)]
        score, cls = compute_pulse_score(vitals)
        self.assertLess(score, 40)
        self.assertEqual(cls, "Critical")

    def test_empty(self):
        score, cls = compute_pulse_score([])
        self.assertEqual(score, 0.0)

    def test_mixed(self):
        vitals = [VitalSign(code=f"P00{i}", name=f"V{i}", score=60) for i in range(1, 9)]
        score, cls = compute_pulse_score(vitals)
        self.assertGreater(score, 50)
        self.assertLess(score, 70)


class TestInsights(unittest.TestCase):
    def test_healthy_insights(self):
        vitals = [VitalSign(code=f"P00{i}", name=f"V{i}", score=90, status="Optimal") for i in range(1, 9)]
        ins = generate_insights(vitals, [], 90)
        self.assertTrue(any("healthy" in i.lower() or "good work" in i.lower() for i in ins))

    def test_critical_insights(self):
        v = VitalSign(code="P002", name="Blood Pressure", score=30, status="Critical")
        ins = generate_insights([v], [], 30)
        self.assertTrue(any("documentation" in i.lower() or "urgent" in i.lower() for i in ins))


class TestWorstFunctions(unittest.TestCase):
    def test_ranking(self):
        fns = {
            "a.srv": [
                FunctionInfo(name="good", file="a.srv", line=1, loc=5, complexity=1),
                FunctionInfo(name="bad", file="a.srv", line=10, loc=60, complexity=10,
                             max_depth=6, nesting_sum=120, calls=list("abcdefgh")),
            ]
        }
        ranked = rank_worst_functions(fns, top_n=2)
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0]["fqn"], "a.srv::bad")

    def test_empty(self):
        ranked = rank_worst_functions({}, top_n=5)
        self.assertEqual(len(ranked), 0)


class TestAnalyzePulse(unittest.TestCase):
    def test_full_analysis(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "app.srv", SIMPLE_SRV)
        report = analyze_pulse([d])
        self.assertEqual(report.files_scanned, 1)
        self.assertEqual(report.total_functions, 2)
        self.assertEqual(len(report.vitals), 8)
        self.assertGreater(report.pulse_score, 0)
        self.assertIn(report.pulse_class, ["Thriving", "Healthy", "Stable", "Stressed", "Critical"])

    def test_multiple_files(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "simple.srv", SIMPLE_SRV)
        _write_srv(d, "complex.srv", COMPLEX_SRV)
        report = analyze_pulse([d])
        self.assertEqual(report.files_scanned, 2)
        self.assertEqual(report.total_functions, 4)

    def test_no_files(self):
        d = tempfile.mkdtemp()
        report = analyze_pulse([d])
        self.assertEqual(report.pulse_score, 0.0)
        self.assertEqual(report.pulse_class, "Critical")

    def test_guarded_file(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "guarded.srv", GUARDED_SRV)
        report = analyze_pulse([d])
        immune = [v for v in report.vitals if v.code == "P007"][0]
        self.assertGreater(immune.score, 30)


class TestHTMLGeneration(unittest.TestCase):
    def test_generates_html(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "app.srv", SIMPLE_SRV)
        report = analyze_pulse([d])
        html = _generate_html(report)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("sauravpulse", html)
        self.assertIn("Vital Signs", html)

    def test_html_with_correlations(self):
        report = PulseReport(
            timestamp="2025-01-01T00:00:00",
            files_scanned=1, total_functions=5,
            vitals=[VitalSign(code="P001", name="Heart Rate", score=50, status="Concerning")],
            correlations=[Correlation(vital_a="P005", vital_b="P003",
                                      description="Test", severity="critical")],
            pulse_score=50, pulse_class="Stressed",
        )
        html = _generate_html(report)
        self.assertIn("critical", html.lower())


class TestHistory(unittest.TestCase):
    def test_save_load(self):
        d = tempfile.mkdtemp()
        report = PulseReport(
            timestamp="2025-01-01T00:00:00",
            pulse_score=75.0, pulse_class="Healthy",
            files_scanned=3, total_functions=10,
            vitals=[VitalSign(code="P001", name="HR", score=80, status="Optimal")],
        )
        save_history(d, report)
        history = load_history(d)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["pulse_score"], 75.0)

    def test_clear(self):
        d = tempfile.mkdtemp()
        report = PulseReport(timestamp="t", pulse_score=50, pulse_class="Stressed",
                             vitals=[])
        save_history(d, report)
        clear_history(d)
        self.assertEqual(len(load_history(d)), 0)

    def test_load_empty(self):
        d = tempfile.mkdtemp()
        self.assertEqual(len(load_history(d)), 0)


class TestCLI(unittest.TestCase):
    def test_default_run(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "app.srv", SIMPLE_SRV)
        with patch('sys.stdout', new_callable=StringIO) as mock_out:
            rc = main([d, "--no-color"])
        self.assertEqual(rc, 0)
        out = mock_out.getvalue()
        self.assertIn("PULSE SCORE", out)

    def test_json_output(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "app.srv", SIMPLE_SRV)
        with patch('sys.stdout', new_callable=StringIO) as mock_out:
            rc = main([d, "--json"])
        self.assertEqual(rc, 0)
        data = json.loads(mock_out.getvalue())
        self.assertIn("pulse_score", data)
        self.assertEqual(len(data["vitals"]), 8)

    def test_html_output(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "app.srv", SIMPLE_SRV)
        html_path = os.path.join(d, "report.html")
        with patch('sys.stdout', new_callable=StringIO):
            rc = main([d, "--html", html_path])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(html_path))

    def test_vital_filter(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "app.srv", SIMPLE_SRV)
        with patch('sys.stdout', new_callable=StringIO) as mock_out:
            rc = main([d, "--vital", "heart-rate", "--no-color"])
        self.assertEqual(rc, 0)
        self.assertIn("Heart Rate", mock_out.getvalue())

    def test_critical_filter(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "app.srv", SIMPLE_SRV)
        with patch('sys.stdout', new_callable=StringIO) as mock_out:
            rc = main([d, "--critical", "--no-color"])
        self.assertEqual(rc, 0)

    def test_top_n(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "app.srv", MIXED_SRV)
        with patch('sys.stdout', new_callable=StringIO) as mock_out:
            rc = main([d, "--top", "5", "--no-color"])
        self.assertEqual(rc, 0)

    def test_reset(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "app.srv", SIMPLE_SRV)
        with patch('sys.stdout', new_callable=StringIO):
            main([d])
        with patch('sys.stdout', new_callable=StringIO) as mock_out:
            rc = main([d, "--reset"])
        self.assertEqual(rc, 0)
        self.assertIn("cleared", mock_out.getvalue().lower())

    def test_timeline_empty(self):
        d = tempfile.mkdtemp()
        with patch('sys.stdout', new_callable=StringIO) as mock_out:
            # Clear any auto-saved history first
            clear_history(d)
            # Need at least one srv file to avoid early exit before timeline check
            _write_srv(d, "app.srv", SIMPLE_SRV)
            # Run once to generate history, then clear, then check timeline
            main([d])
            clear_history(d)
            rc = main([d, "--timeline", "--no-color"])
        # After clearing, the timeline run re-saves, so it should show 1 entry
        self.assertEqual(rc, 0)

    def test_correlations_flag(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "app.srv", SIMPLE_SRV)
        with patch('sys.stdout', new_callable=StringIO) as mock_out:
            rc = main([d, "--correlations", "--no-color"])
        self.assertEqual(rc, 0)


class TestEdgeCases(unittest.TestCase):
    def test_single_function(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "one.srv", "function only_one\n    return 1\nend\n")
        report = analyze_pulse([d])
        self.assertEqual(report.total_functions, 1)
        self.assertEqual(len(report.vitals), 8)

    def test_comments_only(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "comments.srv", "# Just\n# Comments\n# Here\n")
        report = analyze_pulse([d])
        self.assertEqual(report.total_functions, 0)

    def test_recursive(self):
        d = tempfile.mkdtemp()
        sub = os.path.join(d, "sub")
        os.makedirs(sub)
        _write_srv(d, "root.srv", SIMPLE_SRV)
        _write_srv(sub, "child.srv", GUARDED_SRV)
        report = analyze_pulse([d], recursive=True)
        self.assertEqual(report.files_scanned, 2)


if __name__ == "__main__":
    unittest.main()
