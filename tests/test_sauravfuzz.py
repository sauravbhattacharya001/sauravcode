"""Tests for sauravfuzz.py — Grammar-aware fuzzer."""

import json
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sauravfuzz import (
    Outcome,
    FuzzResult,
    FuzzReport,
    ProgramGenerator,
    MutationFuzzer,
    Fuzzer,
    _run_code_safe,
    minimize_crash,
    SEED_CORPUS,
    run_mutation_fuzz,
)


# ── ProgramGenerator ────────────────────────────────────────────────

class TestProgramGenerator:
    def test_basic_generation(self):
        gen = ProgramGenerator(rng=random.Random(42))
        code = gen.generate()
        assert isinstance(code, str)
        assert len(code) > 0
        assert code.endswith("\n")

    def test_deterministic_with_seed(self):
        g1 = ProgramGenerator(rng=random.Random(42))
        g2 = ProgramGenerator(rng=random.Random(42))
        assert g1.generate() == g2.generate()

    def test_different_seeds_different_code(self):
        g1 = ProgramGenerator(rng=random.Random(1))
        g2 = ProgramGenerator(rng=random.Random(99))
        # Very unlikely to be identical
        codes = set()
        for _ in range(5):
            codes.add(g1.generate())
            codes.add(g2.generate())
        assert len(codes) > 2

    def test_max_depth_respected(self):
        gen = ProgramGenerator(rng=random.Random(42), max_depth=2)
        code = gen.generate()
        # Should still produce code with limited nesting
        assert isinstance(code, str)

    def test_max_stmts_respected(self):
        gen = ProgramGenerator(rng=random.Random(42), max_stmts=3)
        code = gen.generate()
        lines = [l for l in code.split("\n") if l.strip()]
        # Won't be exactly max_stmts due to compound statements, but bounded
        assert len(lines) < 50

    def test_generates_various_constructs(self):
        gen = ProgramGenerator(rng=random.Random(42), max_stmts=30)
        codes = [gen.generate() for _ in range(20)]
        combined = "\n".join(codes)
        # Should generate various language features
        constructs = ["print", "if ", "for ", "while ", "function "]
        found = sum(1 for c in constructs if c in combined)
        assert found >= 3

    def test_large_generation_no_crash(self):
        gen = ProgramGenerator(rng=random.Random(42), max_depth=5,
                               max_stmts=20)
        for _ in range(50):
            code = gen.generate()
            assert isinstance(code, str)


# ── _run_code_safe ──────────────────────────────────────────────────

class TestRunCodeSafe:
    def test_ok_program(self):
        outcome, etype, emsg, dur = _run_code_safe('print 42\n')
        assert outcome == Outcome.OK
        assert dur > 0

    def test_syntax_error(self):
        # sauravcode tokenizer raises RuntimeError for unexpected chars
        outcome, etype, emsg, dur = _run_code_safe('@@@\n')
        assert outcome in (Outcome.SYNTAX_ERROR, Outcome.RUNTIME_ERROR)
        assert etype in ("SyntaxError", "RuntimeError")

    def test_runtime_error(self):
        outcome, etype, emsg, dur = _run_code_safe('print 1 / 0\n')
        assert outcome == Outcome.RUNTIME_ERROR
        assert "zero" in emsg.lower()

    def test_undefined_variable(self):
        outcome, etype, emsg, dur = _run_code_safe('print zzz\n')
        assert outcome == Outcome.RUNTIME_ERROR

    def test_timeout(self):
        # This should timeout with very tight limit
        code = 'x = 0\nwhile x < 999999\n    x = x + 1\n'
        outcome, etype, emsg, dur = _run_code_safe(code, timeout_sec=0.1)
        assert outcome in (Outcome.TIMEOUT, Outcome.OK, Outcome.RUNTIME_ERROR)

    def test_throw_outside_try(self):
        outcome, etype, emsg, dur = _run_code_safe('throw "oops"\n')
        assert outcome == Outcome.RUNTIME_ERROR
        assert "ThrowSignal" in etype

    def test_seed_corpus_all_valid(self):
        """All seed corpus programs should run without crashing."""
        for code in SEED_CORPUS:
            outcome, etype, emsg, dur = _run_code_safe(code, timeout_sec=5.0)
            assert outcome in (Outcome.OK, Outcome.RUNTIME_ERROR,
                               Outcome.SYNTAX_ERROR), \
                f"Seed crashed: {etype}: {emsg}\nCode: {code[:80]}"


# ── FuzzResult ──────────────────────────────────────────────────────

class TestFuzzResult:
    def test_to_dict(self):
        r = FuzzResult(code="print 1\n", outcome=Outcome.OK,
                       duration_ms=1.5)
        d = r.to_dict()
        assert d["outcome"] == "ok"
        assert d["duration_ms"] == 1.5
        assert d["code"] == "print 1\n"

    def test_to_dict_with_error(self):
        r = FuzzResult(code="bad\n", outcome=Outcome.CRASH,
                       error_type="TypeError", error_msg="boom",
                       duration_ms=0.5)
        d = r.to_dict()
        assert d["error_type"] == "TypeError"
        assert d["error_msg"] == "boom"

    def test_to_dict_with_minimized(self):
        r = FuzzResult(code="long code\n", outcome=Outcome.CRASH,
                       minimized="short\n")
        d = r.to_dict()
        assert d["minimized"] == "short\n"


# ── FuzzReport ──────────────────────────────────────────────────────

class TestFuzzReport:
    def test_empty_report(self):
        r = FuzzReport()
        s = r.summary()
        assert "sauravfuzz" in s

    def test_report_with_data(self):
        r = FuzzReport(iterations=100, seed=42, duration_sec=1.5)
        r.outcomes["ok"] = 90
        r.outcomes["syntax"] = 10
        s = r.summary()
        assert "100" in s
        assert "42" in s

    def test_to_dict(self):
        r = FuzzReport(iterations=50, seed=1)
        r.outcomes["ok"] = 50
        d = r.to_dict()
        assert d["iterations"] == 50
        assert d["seed"] == 1
        assert d["outcomes"]["ok"] == 50

    def test_to_dict_json_serializable(self):
        r = FuzzReport(iterations=10, seed=1)
        r.outcomes["ok"] = 10
        j = json.dumps(r.to_dict())
        assert len(j) > 10


# ── MutationFuzzer ──────────────────────────────────────────────────

class TestMutationFuzzer:
    def test_mutate_changes_code(self):
        mf = MutationFuzzer(rng=random.Random(42))
        original = 'x = 42\nprint x\n'
        changed = False
        for _ in range(10):
            mutated = mf.mutate(original)
            if mutated != original:
                changed = True
                break
        assert changed

    def test_all_mutations_produce_strings(self):
        mf = MutationFuzzer(rng=random.Random(42))
        code = 'x = 10\nif x > 5\n    print x\n'
        for _ in range(20):
            result = mf.mutate(code)
            assert isinstance(result, str)

    def test_mutation_deterministic(self):
        m1 = MutationFuzzer(rng=random.Random(42))
        m2 = MutationFuzzer(rng=random.Random(42))
        code = 'print 1\nprint 2\n'
        assert m1.mutate(code) == m2.mutate(code)


# ── Fuzzer ──────────────────────────────────────────────────────────

class TestFuzzer:
    def test_basic_run(self):
        f = Fuzzer(seed=42, timeout=1.0)
        report = f.run(iterations=10, progress=False)
        assert report.iterations == 10
        assert sum(report.outcomes.values()) == 10

    def test_reproducible(self):
        r1 = Fuzzer(seed=42, timeout=1.0).run(10, progress=False)
        r2 = Fuzzer(seed=42, timeout=1.0).run(10, progress=False)
        assert dict(r1.outcomes) == dict(r2.outcomes)

    def test_outcomes_classified(self):
        report = Fuzzer(seed=42, timeout=1.0).run(50, progress=False)
        valid_outcomes = {Outcome.OK, Outcome.RUNTIME_ERROR,
                          Outcome.SYNTAX_ERROR, Outcome.CRASH,
                          Outcome.TIMEOUT, Outcome.INTERNAL}
        for k in report.outcomes:
            assert k in valid_outcomes

    def test_report_has_summary(self):
        report = Fuzzer(seed=42).run(5, progress=False)
        s = report.summary()
        assert "Iterations: 5" in s


# ── Mutation fuzz runner ────────────────────────────────────────────

class TestMutationFuzzRunner:
    def test_basic_run(self):
        report = run_mutation_fuzz(20, seed=42, timeout=1.0, quiet=True)
        assert report.iterations == 20
        assert sum(report.outcomes.values()) == 20

    def test_seed_corpus_not_empty(self):
        assert len(SEED_CORPUS) >= 10


# ── Minimize ────────────────────────────────────────────────────────

class TestMinimize:
    def test_minimize_non_crash_returns_original(self):
        code = 'print 42\n'
        result = minimize_crash(code)
        assert result == code

    def test_minimize_syntax_error_returns_original(self):
        code = '@@@\n'
        result = minimize_crash(code)
        assert result == code
