"""Tests for sauravpulse — autonomous codebase vital signs monitor."""

import math
import os
import sys
import tempfile
import shutil

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sauravpulse import (
    FunctionInfo,
    VitalSign,
    Correlation,
    PulseReport,
    compute_heart_rate,
    compute_blood_pressure,
    compute_temperature,
    compute_respiratory_rate,
    compute_oxygen_saturation,
    compute_reflexes,
    compute_immune_response,
    compute_neural_activity,
    detect_correlations,
    compute_pulse_score,
    generate_insights,
    rank_worst_functions,
    load_history,
    save_history,
    clear_history,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _fn(name="foo", loc=10, complexity=2, max_depth=2, params=1,
        calls=None, has_doc_comment=False, risky_calls=0,
        try_catch_blocks=0, guard_count=0, nesting_sum=10, file="test.srv"):
    """Build a FunctionInfo with sensible defaults."""
    return FunctionInfo(
        name=name, file=file, line=1, loc=loc,
        complexity=complexity, max_depth=max_depth, params=params,
        calls=calls or [], has_doc_comment=has_doc_comment,
        risky_calls=risky_calls, try_catch_blocks=try_catch_blocks,
        guard_count=guard_count, nesting_sum=nesting_sum,
    )


def _file_data(*specs):
    """Create file_data dict from (filename, [FunctionInfo...]) pairs."""
    return {name: fns for name, fns in specs}


# ── VitalSign Tests ──────────────────────────────────────────────────

class TestVitalSign:
    def test_classify_optimal(self):
        v = VitalSign(code="P001", name="Test", score=90)
        v.classify()
        assert v.status == "Optimal"

    def test_classify_normal(self):
        v = VitalSign(code="P001", name="Test", score=65)
        v.classify()
        assert v.status == "Normal"

    def test_classify_concerning(self):
        v = VitalSign(code="P001", name="Test", score=45)
        v.classify()
        assert v.status == "Concerning"

    def test_classify_critical(self):
        v = VitalSign(code="P001", name="Test", score=20)
        v.classify()
        assert v.status == "Critical"

    def test_classify_boundary_80(self):
        v = VitalSign(code="P001", name="Test", score=80)
        v.classify()
        assert v.status == "Optimal"

    def test_classify_boundary_60(self):
        v = VitalSign(code="P001", name="Test", score=60)
        v.classify()
        assert v.status == "Normal"

    def test_classify_boundary_40(self):
        v = VitalSign(code="P001", name="Test", score=40)
        v.classify()
        assert v.status == "Concerning"


# ── P001: Heart Rate Tests ───────────────────────────────────────────

class TestHeartRate:
    def test_empty_data(self):
        vs = compute_heart_rate({})
        assert vs.score == 0.0
        assert vs.status == "Critical"
        assert vs.code == "P001"

    def test_single_file_single_function(self):
        data = {"a.srv": [_fn()]}
        vs = compute_heart_rate(data)
        # avg_density=1, density_score=40, file_factor=0.7+0.2*1=0.7+0.06=0.76
        assert 0 < vs.score <= 100
        assert vs.status in ("Critical", "Concerning", "Normal", "Optimal")

    def test_optimal_density(self):
        """5 functions per file across 5 files → sweet spot."""
        data = {f"f{i}.srv": [_fn(name=f"fn{j}") for j in range(5)] for i in range(5)}
        vs = compute_heart_rate(data)
        # avg_density=5, in 3-8 range → density_score = 70 + (5-3)*6 = 82
        # file_factor = min(1,5/5)*0.3+0.7 = 1.0
        assert vs.score >= 70
        assert vs.status in ("Normal", "Optimal")

    def test_overcrowded_files(self):
        """20 functions per file → penalty."""
        data = {"big.srv": [_fn(name=f"fn{j}") for j in range(20)]}
        vs = compute_heart_rate(data)
        # avg_density=20 → density_score = max(20, 79 - (20-15)*2) = 69
        # But file_factor = min(1,1/5)*0.3+0.7 = 0.76
        assert vs.score < 80

    def test_per_file_present(self):
        data = {"a.srv": [_fn(), _fn(name="bar")], "b.srv": [_fn()]}
        vs = compute_heart_rate(data)
        assert "a.srv" in vs.per_file
        assert "b.srv" in vs.per_file

    def test_score_clamped_0_100(self):
        # Edge case: extreme density
        data = {"x.srv": [_fn(name=f"f{i}") for i in range(100)]}
        vs = compute_heart_rate(data)
        assert 0 <= vs.score <= 100


# ── P002: Blood Pressure Tests ───────────────────────────────────────

class TestBloodPressure:
    def test_no_functions(self):
        vs = compute_blood_pressure({}, {}, {})
        assert vs.score == 50.0
        assert vs.code == "P002"

    def test_low_complexity_high_docs(self):
        """Well-documented, low-complexity code → good score."""
        fns = [_fn(complexity=2, has_doc_comment=True) for _ in range(5)]
        data = {"a.srv": fns}
        comment_counts = {"a.srv": 20}
        line_counts = {"a.srv": 100}
        vs = compute_blood_pressure(data, comment_counts, line_counts)
        assert vs.score > 50

    def test_high_complexity_no_docs(self):
        """Complex, undocumented code → low score."""
        fns = [_fn(complexity=10, has_doc_comment=False) for _ in range(5)]
        data = {"a.srv": fns}
        comment_counts = {"a.srv": 0}
        line_counts = {"a.srv": 100}
        vs = compute_blood_pressure(data, comment_counts, line_counts)
        assert vs.score < 50

    def test_details_populated(self):
        fns = [_fn(complexity=3, has_doc_comment=True)]
        vs = compute_blood_pressure({"a.srv": fns}, {"a.srv": 5}, {"a.srv": 50})
        assert "complexity" in vs.details.lower()
        assert "documented" in vs.details.lower()


# ── P003: Temperature Tests ──────────────────────────────────────────

class TestTemperature:
    def test_no_functions(self):
        vs = compute_temperature({})
        assert vs.score == 80.0

    def test_no_hotspots(self):
        """Small simple functions → no hotspots → high score."""
        fns = [_fn(loc=10, complexity=2, max_depth=2) for _ in range(10)]
        vs = compute_temperature({"a.srv": fns})
        assert vs.score >= 80

    def test_all_hotspots(self):
        """Every function is a hotspot → very low score."""
        fns = [_fn(loc=50, complexity=8, max_depth=5, calls=["x"] * 12) for _ in range(5)]
        vs = compute_temperature({"a.srv": fns})
        assert vs.score < 20

    def test_mixed_functions(self):
        good = [_fn(loc=10, complexity=2, max_depth=2) for _ in range(8)]
        bad = [_fn(loc=50, complexity=8, max_depth=5, calls=["x"] * 12) for _ in range(2)]
        vs = compute_temperature({"a.srv": good + bad})
        # 2/10 hotspots = 20% → score = 100 - 0.2*200 = 60
        assert 40 <= vs.score <= 80


# ── P004: Respiratory Rate Tests ─────────────────────────────────────

class TestRespiratoryRate:
    def test_too_few_functions(self):
        vs = compute_respiratory_rate({"a.srv": [_fn()]})
        assert vs.score == 70.0

    def test_uniform_sizes(self):
        """All same size → CV=0 → great rhythm."""
        fns = [_fn(name=f"fn_{i}", loc=10) for i in range(10)]
        vs = compute_respiratory_rate({"a.srv": fns})
        # CV=0, naming consistent (snake_case) → high score
        assert vs.score >= 80

    def test_wildly_varying_sizes(self):
        """Huge variance → high CV → poor rhythm."""
        fns = [_fn(name=f"fn_{i}", loc=i * 20) for i in range(1, 11)]
        vs = compute_respiratory_rate({"a.srv": fns})
        # High CV → lower score
        assert vs.score < 90

    def test_naming_consistency_snake(self):
        """All snake_case → consistent naming."""
        fns = [_fn(name=f"do_thing_{i}", loc=10) for i in range(5)]
        vs = compute_respiratory_rate({"a.srv": fns})
        assert vs.score >= 80

    def test_mixed_naming(self):
        """Mix of snake_case and camelCase → lower naming score."""
        fns = [
            _fn(name="do_thing", loc=10),
            _fn(name="doThing", loc=10),
            _fn(name="make_stuff", loc=10),
            _fn(name="makeStuff", loc=10),
        ]
        vs = compute_respiratory_rate({"a.srv": fns})
        # 50% consistency → naming_score ~50, but CV=0 → still decent
        assert vs.score < 95


# ── P005: Oxygen Saturation Tests ────────────────────────────────────

class TestOxygenSaturation:
    def test_no_functions(self):
        vs = compute_oxygen_saturation({}, {})
        assert vs.score == 50.0

    def test_all_tested(self):
        fns = [_fn(name="compute_x"), _fn(name="do_y")]
        data = {"main.srv": fns}
        contents = {"test_main.srv": "compute_x do_y"}
        vs = compute_oxygen_saturation(data, contents)
        assert vs.score >= 90

    def test_none_tested(self):
        fns = [_fn(name="compute_x"), _fn(name="do_y")]
        data = {"main.srv": fns}
        contents = {"test_main.srv": "something_else entirely"}
        vs = compute_oxygen_saturation(data, contents)
        assert vs.score == 0.0

    def test_partial_coverage(self):
        fns = [_fn(name="compute_x"), _fn(name="do_y")]
        data = {"main.srv": fns}
        contents = {"test_main.srv": "compute_x tested here"}
        vs = compute_oxygen_saturation(data, contents)
        # 50% coverage → score = 0.5 * 120 = 60
        assert 50 <= vs.score <= 70


# ── P006: Reflexes Tests ─────────────────────────────────────────────

class TestReflexes:
    def test_no_functions(self):
        vs = compute_reflexes({})
        assert vs.score == 90.0  # No risky operations → high score

    def test_all_guarded_with_try(self):
        """Functions with risky calls all have try/catch → good reflexes."""
        fns = [_fn(risky_calls=2, try_catch_blocks=1) for _ in range(5)]
        vs = compute_reflexes({"a.srv": fns})
        assert vs.score > 60

    def test_no_risky_calls(self):
        """No risky calls → no try needed → good score."""
        fns = [_fn(risky_calls=0, try_catch_blocks=0) for _ in range(5)]
        vs = compute_reflexes({"a.srv": fns})
        assert vs.score >= 60

    def test_unguarded_risky_calls(self):
        """Risky calls without error handling → bad reflexes."""
        fns = [_fn(risky_calls=3, try_catch_blocks=0) for _ in range(5)]
        vs = compute_reflexes({"a.srv": fns})
        assert vs.score < 60


# ── P007: Immune Response Tests ──────────────────────────────────────

class TestImmuneResponse:
    def test_no_functions(self):
        vs = compute_immune_response({})
        assert vs.score == 50.0

    def test_high_guard_count(self):
        """Functions with many guards → strong immune system."""
        fns = [_fn(guard_count=3, params=2) for _ in range(5)]
        vs = compute_immune_response({"a.srv": fns})
        assert vs.score > 50

    def test_no_guards(self):
        """No input validation → weak immune system."""
        fns = [_fn(guard_count=0, params=4) for _ in range(5)]
        vs = compute_immune_response({"a.srv": fns})
        assert vs.score < 70


# ── P008: Neural Activity Tests ──────────────────────────────────────

class TestNeuralActivity:
    def test_no_functions(self):
        vs = compute_neural_activity({})
        assert vs.score == 80.0  # No functions → baseline

    def test_simple_functions(self):
        """Low complexity + shallow nesting → good neural score."""
        fns = [_fn(complexity=2, max_depth=1, nesting_sum=5, loc=10) for _ in range(5)]
        vs = compute_neural_activity({"a.srv": fns})
        assert vs.score > 60

    def test_complex_deep_functions(self):
        """High complexity + deep nesting → cognitive overload."""
        fns = [_fn(complexity=12, max_depth=7, nesting_sum=80, loc=50) for _ in range(5)]
        vs = compute_neural_activity({"a.srv": fns})
        assert vs.score < 50


# ── Correlations Tests ───────────────────────────────────────────────

class TestDetectCorrelations:
    def test_no_vitals(self):
        corrs = detect_correlations({})
        # With no vitals, defaults trigger some warning correlations
        assert all(c.severity in ('info', 'warning', 'critical') for c in corrs)

    def test_healthy_no_critical_correlations(self):
        vitals = {
            "P001": VitalSign(code="P001", name="HR", score=85),
            "P002": VitalSign(code="P002", name="BP", score=80),
            "P003": VitalSign(code="P003", name="Temp", score=90),
        }
        corrs = detect_correlations(vitals)
        # All healthy → no critical correlations expected
        critical = [c for c in corrs if c.severity == "critical"]
        assert len(critical) == 0

    def test_all_critical_produces_correlations(self):
        vitals = {
            "P001": VitalSign(code="P001", name="HR", score=20),
            "P002": VitalSign(code="P002", name="BP", score=15),
            "P003": VitalSign(code="P003", name="Temp", score=10),
            "P005": VitalSign(code="P005", name="O2", score=5),
            "P006": VitalSign(code="P006", name="Reflex", score=10),
            "P008": VitalSign(code="P008", name="Neural", score=15),
        }
        corrs = detect_correlations(vitals)
        # Multiple simultaneous failures → should detect some correlations
        assert len(corrs) > 0


# ── Pulse Score Tests ────────────────────────────────────────────────

class TestPulseScore:
    def test_empty(self):
        score, cls = compute_pulse_score([])
        assert score == 0.0
        assert cls == "Critical"

    def test_all_optimal(self):
        vitals = [VitalSign(code=f"P00{i}", name=f"V{i}", score=95) for i in range(1, 9)]
        score, cls = compute_pulse_score(vitals)
        assert score >= 85
        assert cls == "Thriving"

    def test_all_critical(self):
        vitals = [VitalSign(code=f"P00{i}", name=f"V{i}", score=10) for i in range(1, 9)]
        score, cls = compute_pulse_score(vitals)
        assert score < 40
        assert cls == "Critical"

    def test_mixed_scores(self):
        vitals = [
            VitalSign(code="P001", name="HR", score=80),
            VitalSign(code="P002", name="BP", score=40),
            VitalSign(code="P003", name="Temp", score=60),
        ]
        score, cls = compute_pulse_score(vitals)
        assert 40 <= score <= 80
        assert cls in ("Stable", "Healthy", "Stressed")

    def test_classification_thresholds(self):
        # Test each classification boundary
        v85 = [VitalSign(code="P001", name="V", score=85)]
        _, cls85 = compute_pulse_score(v85)
        assert cls85 == "Thriving"

        v70 = [VitalSign(code="P001", name="V", score=70)]
        _, cls70 = compute_pulse_score(v70)
        assert cls70 == "Healthy"

        v55 = [VitalSign(code="P001", name="V", score=55)]
        _, cls55 = compute_pulse_score(v55)
        assert cls55 == "Stable"

        v40 = [VitalSign(code="P001", name="V", score=40)]
        _, cls40 = compute_pulse_score(v40)
        assert cls40 == "Stressed"

        v20 = [VitalSign(code="P001", name="V", score=20)]
        _, cls20 = compute_pulse_score(v20)
        assert cls20 == "Critical"


# ── Insights Tests ───────────────────────────────────────────────────

class TestInsights:
    def test_all_healthy(self):
        vitals = [VitalSign(code=f"P00{i}", name=f"V{i}", score=90, status="Optimal") for i in range(1, 9)]
        insights = generate_insights(vitals, [], 90)
        assert any("healthy" in i.lower() or "good work" in i.lower() for i in insights)

    def test_critical_vitals_flagged(self):
        vitals = [VitalSign(code="P003", name="Temperature", score=20, status="Critical")]
        insights = generate_insights(vitals, [], 30)
        assert any("urgent" in i.lower() or "critical" in i.lower() for i in insights)

    def test_low_oxygen_recommends_tests(self):
        vitals = [VitalSign(code="P005", name="O2 Sat", score=30, status="Critical")]
        insights = generate_insights(vitals, [], 30)
        assert any("test" in i.lower() for i in insights)

    def test_critical_correlations_mentioned(self):
        vitals = [VitalSign(code="P001", name="HR", score=50, status="Concerning")]
        corrs = [Correlation(vital_a="P001", vital_b="P002", description="test", severity="critical")]
        insights = generate_insights(vitals, corrs, 50)
        assert any("correlation" in i.lower() for i in insights)

    def test_thriving_score_encouragement(self):
        vitals = [VitalSign(code="P001", name="HR", score=90, status="Optimal")]
        insights = generate_insights(vitals, [], 90)
        assert any("thriving" in i.lower() or "ambitious" in i.lower() for i in insights)


# ── Worst Functions Tests ────────────────────────────────────────────

class TestRankWorstFunctions:
    def test_empty(self):
        result = rank_worst_functions({})
        assert result == []

    def test_ranks_by_health(self):
        good = _fn(name="simple", file="a.srv", loc=5, complexity=1, max_depth=1, nesting_sum=3)
        bad = _fn(name="monster", file="a.srv", loc=80, complexity=12, max_depth=6, nesting_sum=200,
                  calls=["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l"])
        result = rank_worst_functions({"a.srv": [good, bad]}, top_n=2)
        assert len(result) == 2
        # Bad function should be first (lower health)
        assert result[0]["fqn"] == "a.srv::monster"
        assert result[0]["health"] < result[1]["health"]

    def test_top_n_limits(self):
        fns = [_fn(name=f"fn{i}") for i in range(20)]
        result = rank_worst_functions({"a.srv": fns}, top_n=5)
        assert len(result) == 5

    def test_documented_bonus(self):
        undoc = _fn(name="undoc", file="a.srv", loc=20, complexity=5, has_doc_comment=False)
        doc = _fn(name="documented", file="a.srv", loc=20, complexity=5, has_doc_comment=True)
        result = rank_worst_functions({"a.srv": [undoc, doc]}, top_n=2)
        # Documented fn should have higher health
        doc_entry = next(r for r in result if r["fqn"] == "a.srv::documented")
        undoc_entry = next(r for r in result if r["fqn"] == "a.srv::undoc")
        assert doc_entry["health"] > undoc_entry["health"]


# ── History (save/load/clear) Tests ──────────────────────────────────

class TestHistory:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_empty(self):
        history = load_history(self.tmpdir)
        assert history == []

    def test_save_and_load(self):
        report = PulseReport(
            timestamp="2026-05-01T12:00:00",
            files_scanned=3,
            total_functions=15,
            pulse_score=72.5,
            pulse_class="Healthy",
        )
        save_history(self.tmpdir, report)
        history = load_history(self.tmpdir)
        assert len(history) >= 1
        assert history[-1]["pulse_score"] == 72.5

    def test_clear_history(self):
        report = PulseReport(timestamp="2026-05-01", pulse_score=50.0, pulse_class="Stable")
        save_history(self.tmpdir, report)
        clear_history(self.tmpdir)
        history = load_history(self.tmpdir)
        assert history == []

    def test_multiple_saves_accumulate(self):
        for i in range(3):
            r = PulseReport(timestamp=f"2026-05-0{i+1}", pulse_score=50 + i * 10, pulse_class="Stable")
            save_history(self.tmpdir, r)
        history = load_history(self.tmpdir)
        assert len(history) == 3


# ── FunctionInfo Tests ───────────────────────────────────────────────

class TestFunctionInfo:
    def test_fqn(self):
        fn = _fn(name="hello", file="main.srv")
        assert fn.fqn == "main.srv::hello"

    def test_defaults(self):
        fn = FunctionInfo(name="x", file="f.srv", line=1)
        assert fn.loc == 0
        assert fn.complexity == 1
        assert fn.calls == []
        assert fn.has_doc_comment is False


# ── Integration: Score Consistency ───────────────────────────────────

class TestScoreConsistency:
    """Ensure vital sign scores are always in [0, 100]."""

    def test_heart_rate_bounds(self):
        for n in [0, 1, 5, 50, 200]:
            data = {f"f{i}.srv": [_fn(name=f"fn{j}") for j in range(max(1, n // 5))]
                    for i in range(max(1, n))}
            vs = compute_heart_rate(data)
            assert 0 <= vs.score <= 100

    def test_temperature_bounds(self):
        for hot_ratio in [0, 0.3, 0.7, 1.0]:
            n = 10
            fns = []
            for i in range(n):
                if i < n * hot_ratio:
                    fns.append(_fn(loc=50, complexity=8, max_depth=5, calls=["x"] * 12))
                else:
                    fns.append(_fn(loc=5, complexity=1, max_depth=1))
            vs = compute_temperature({"a.srv": fns})
            assert 0 <= vs.score <= 100

    def test_pulse_score_bounds(self):
        for s in [0, 25, 50, 75, 100]:
            vitals = [VitalSign(code=f"P00{i}", name=f"V{i}", score=s) for i in range(1, 9)]
            score, _ = compute_pulse_score(vitals)
            assert 0 <= score <= 100
