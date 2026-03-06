#!/usr/bin/env python3
"""Tests for sauravbench.py benchmarking tool."""

import os
import sys
import json
import math
import tempfile
import shutil
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sauravbench import (
    run_once, benchmark, compute_stats, percentile,
    format_time, save_baseline, load_baselines, check_baseline,
    REGRESSION_THRESHOLD,
)


# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def simple_srv(tmp_path):
    """Create a simple .srv program."""
    f = tmp_path / "simple.srv"
    f.write_text('x = 1 + 2\nprint x\n')
    return str(f)


@pytest.fixture
def error_srv(tmp_path):
    """Create a .srv program that raises an error."""
    f = tmp_path / "bad.srv"
    f.write_text('print undefined_var\n')
    return str(f)


@pytest.fixture
def loop_srv(tmp_path):
    """Create a .srv program with a loop (more measurable time)."""
    f = tmp_path / "loop.srv"
    f.write_text('i = 0\nwhile i < 100\n    i = i + 1\n')
    return str(f)


@pytest.fixture
def baseline_dir(tmp_path, monkeypatch):
    """Override baseline directory to use tmp_path."""
    import sauravbench
    bd = str(tmp_path / ".sauravbench")
    monkeypatch.setattr(sauravbench, "BASELINE_DIR", bd)
    return bd


# ── run_once ─────────────────────────────────────────────────────

class TestRunOnce:
    def test_success(self, simple_srv):
        with open(simple_srv) as f:
            code = f.read()
        elapsed, ok, err = run_once(code, simple_srv)
        assert ok is True
        assert err is None
        assert elapsed > 0

    def test_error_program(self, error_srv):
        with open(error_srv) as f:
            code = f.read()
        elapsed, ok, err = run_once(code, error_srv)
        assert ok is False
        assert err is not None
        assert elapsed > 0

    def test_captures_stdout(self, simple_srv, capsys):
        with open(simple_srv) as f:
            code = f.read()
        run_once(code, simple_srv)
        captured = capsys.readouterr()
        # stdout should be captured, not leaked
        assert "3" not in captured.out


# ── benchmark ────────────────────────────────────────────────────

class TestBenchmark:
    def test_basic_stats(self, simple_srv):
        with open(simple_srv) as f:
            code = f.read()
        stats = benchmark(code, simple_srv, iterations=5, warmup=1)
        assert "error" not in stats
        assert stats["successful"] == 5
        assert stats["errors"] == 0
        assert stats["warmup"] == 1
        assert stats["iterations"] == 5

    def test_timing_values(self, simple_srv):
        with open(simple_srv) as f:
            code = f.read()
        stats = benchmark(code, simple_srv, iterations=5, warmup=0)
        assert stats["min_ms"] > 0
        assert stats["max_ms"] >= stats["min_ms"]
        assert stats["mean_ms"] >= stats["min_ms"]
        assert stats["mean_ms"] <= stats["max_ms"]

    def test_median_between_min_max(self, simple_srv):
        with open(simple_srv) as f:
            code = f.read()
        stats = benchmark(code, simple_srv, iterations=10, warmup=0)
        assert stats["min_ms"] <= stats["median_ms"] <= stats["max_ms"]

    def test_total_equals_sum(self, simple_srv):
        with open(simple_srv) as f:
            code = f.read()
        stats = benchmark(code, simple_srv, iterations=5, warmup=0)
        expected = sum(stats["raw_times_ms"])
        assert abs(stats["total_ms"] - expected) < 0.001

    def test_percentiles_ordered(self, simple_srv):
        with open(simple_srv) as f:
            code = f.read()
        stats = benchmark(code, simple_srv, iterations=10, warmup=0)
        assert stats["p50_ms"] <= stats["p90_ms"]
        assert stats["p90_ms"] <= stats["p95_ms"]
        assert stats["p95_ms"] <= stats["p99_ms"]

    def test_warmup_failure(self, error_srv):
        with open(error_srv) as f:
            code = f.read()
        stats = benchmark(code, error_srv, iterations=5, warmup=1)
        assert "error" in stats
        assert "Warmup failed" in stats["error"]

    def test_zero_warmup(self, simple_srv):
        with open(simple_srv) as f:
            code = f.read()
        stats = benchmark(code, simple_srv, iterations=3, warmup=0)
        assert stats["warmup"] == 0
        assert stats["successful"] == 3

    def test_raw_times_count(self, simple_srv):
        with open(simple_srv) as f:
            code = f.read()
        stats = benchmark(code, simple_srv, iterations=7, warmup=0)
        assert len(stats["raw_times_ms"]) == 7

    def test_file_name_in_stats(self, simple_srv):
        with open(simple_srv) as f:
            code = f.read()
        stats = benchmark(code, simple_srv, iterations=3, warmup=0)
        assert stats["file"] == os.path.basename(simple_srv)


# ── compute_stats ────────────────────────────────────────────────

class TestComputeStats:
    def test_known_values(self):
        times = [0.010, 0.020, 0.030, 0.040, 0.050]
        stats = compute_stats(times, errors=0, iterations=5, warmup=0, filename="test.srv")
        assert stats["min_ms"] == pytest.approx(10.0)
        assert stats["max_ms"] == pytest.approx(50.0)
        assert stats["mean_ms"] == pytest.approx(30.0)
        assert stats["median_ms"] == pytest.approx(30.0)
        assert stats["successful"] == 5

    def test_single_value(self):
        stats = compute_stats([0.025], errors=0, iterations=1, warmup=0, filename="x.srv")
        assert stats["min_ms"] == stats["max_ms"] == stats["mean_ms"]
        assert stats["stddev_ms"] == 0

    def test_errors_tracked(self):
        stats = compute_stats([0.01, 0.02], errors=3, iterations=5, warmup=0, filename="e.srv")
        assert stats["errors"] == 3
        assert stats["successful"] == 2

    def test_cv_zero_for_identical(self):
        stats = compute_stats([0.01, 0.01, 0.01], errors=0, iterations=3, warmup=0, filename="c.srv")
        assert stats["cv_percent"] == 0

    def test_cv_nonzero_for_varied(self):
        stats = compute_stats([0.01, 0.1], errors=0, iterations=2, warmup=0, filename="v.srv")
        assert stats["cv_percent"] > 0


# ── percentile ───────────────────────────────────────────────────

class TestPercentile:
    def test_p50_is_median(self):
        assert percentile([1, 2, 3, 4, 5], 50) == 3

    def test_p0_is_min(self):
        assert percentile([10, 20, 30], 0) == 10

    def test_p100_is_max(self):
        assert percentile([10, 20, 30], 100) == 30

    def test_empty_returns_zero(self):
        assert percentile([], 50) == 0

    def test_single_element(self):
        assert percentile([42], 50) == 42
        assert percentile([42], 0) == 42
        assert percentile([42], 100) == 42

    def test_interpolation(self):
        # [1, 2, 3, 4] p25 = 1.75
        result = percentile([1, 2, 3, 4], 25)
        assert result == pytest.approx(1.75)


# ── format_time ──────────────────────────────────────────────────

class TestFormatTime:
    def test_microseconds(self):
        result = format_time(0.5)
        assert "us" in result

    def test_milliseconds(self):
        result = format_time(25.0)
        assert "ms" in result

    def test_seconds(self):
        result = format_time(1500.0)
        assert "s" in result

    def test_zero(self):
        result = format_time(0)
        assert "us" in result


# ── Baseline operations ─────────────────────────────────────────

class TestBaseline:
    def test_save_and_load(self, baseline_dir):
        stats = {
            "file": "test.srv",
            "mean_ms": 25.0,
            "median_ms": 24.0,
            "min_ms": 20.0,
            "stddev_ms": 3.0,
            "iterations": 10,
        }
        save_baseline(stats)
        loaded = load_baselines()
        assert "test.srv" in loaded
        assert loaded["test.srv"]["mean_ms"] == 25.0

    def test_load_empty(self, baseline_dir):
        loaded = load_baselines()
        assert loaded == {}

    def test_check_no_baseline(self, baseline_dir):
        stats = {"file": "missing.srv", "mean_ms": 10.0}
        passed, msg = check_baseline(stats)
        assert passed is None
        assert "No baseline" in msg

    def test_check_no_regression(self, baseline_dir):
        # Save baseline
        stats = {
            "file": "ok.srv",
            "mean_ms": 25.0,
            "median_ms": 24.0,
            "min_ms": 20.0,
            "stddev_ms": 3.0,
            "iterations": 10,
        }
        save_baseline(stats)
        # Check with similar value (within 10%)
        stats["mean_ms"] = 26.0  # +4%
        passed, msg = check_baseline(stats)
        assert passed is True
        assert "OK" in msg

    def test_check_regression(self, baseline_dir):
        stats = {
            "file": "slow.srv",
            "mean_ms": 25.0,
            "median_ms": 24.0,
            "min_ms": 20.0,
            "stddev_ms": 3.0,
            "iterations": 10,
        }
        save_baseline(stats)
        stats["mean_ms"] = 30.0  # +20%
        passed, msg = check_baseline(stats)
        assert passed is False
        assert "REGRESSION" in msg

    def test_check_improvement(self, baseline_dir):
        stats = {
            "file": "fast.srv",
            "mean_ms": 25.0,
            "median_ms": 24.0,
            "min_ms": 20.0,
            "stddev_ms": 3.0,
            "iterations": 10,
        }
        save_baseline(stats)
        stats["mean_ms"] = 20.0  # -20%
        passed, msg = check_baseline(stats)
        assert passed is True
        assert "IMPROVEMENT" in msg

    def test_custom_threshold(self, baseline_dir):
        stats = {
            "file": "thresh.srv",
            "mean_ms": 100.0,
            "median_ms": 100.0,
            "min_ms": 90.0,
            "stddev_ms": 5.0,
            "iterations": 10,
        }
        save_baseline(stats)
        stats["mean_ms"] = 106.0  # +6%, would pass at 10% but fail at 5%
        passed, msg = check_baseline(stats, threshold=0.05)
        assert passed is False
        assert "REGRESSION" in msg

    def test_multiple_baselines(self, baseline_dir):
        for name in ["a.srv", "b.srv", "c.srv"]:
            stats = {
                "file": name,
                "mean_ms": 10.0,
                "median_ms": 10.0,
                "min_ms": 9.0,
                "stddev_ms": 1.0,
                "iterations": 5,
            }
            save_baseline(stats)
        loaded = load_baselines()
        assert len(loaded) == 3


# ── Integration ──────────────────────────────────────────────────

class TestIntegration:
    def test_loop_benchmark(self, loop_srv):
        with open(loop_srv) as f:
            code = f.read()
        stats = benchmark(code, loop_srv, iterations=5, warmup=1)
        assert "error" not in stats
        assert stats["successful"] == 5
        # Loop should take measurable time
        assert stats["mean_ms"] > 0

    def test_benchmark_save_check_roundtrip(self, simple_srv, baseline_dir):
        with open(simple_srv) as f:
            code = f.read()
        stats = benchmark(code, simple_srv, iterations=5, warmup=0)
        save_baseline(stats)

        # Re-benchmark and check
        stats2 = benchmark(code, simple_srv, iterations=5, warmup=0)
        passed, msg = check_baseline(stats2, threshold=5.0)  # generous threshold
        assert passed is True
