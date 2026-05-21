"""Tests for sauravflake."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

import sauravflake
from sauravflake import FlakeAdvisor, FlakeReport


FIXED_NOW = lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)


def _runs(test_id: str, pattern: str, base_ts: int = 1_700_000_000, duration_ms: float = 100.0):
    """Build run dicts from a P/F/S string pattern."""
    out = []
    for i, ch in enumerate(pattern):
        outcome = {"P": "pass", "F": "fail", "S": "skip"}[ch]
        out.append(
            {
                "test_id": test_id,
                "outcome": outcome,
                "duration_ms": duration_ms,
                "timestamp": base_ts + i * 60,
                "run_id": f"r{i:03d}",
            }
        )
    return out


def test_stable_test_is_stable():
    advisor = FlakeAdvisor(now=FIXED_NOW)
    report = advisor.analyze(_runs("test_a", "P" * 10))
    assert len(report.findings) == 1
    f = report.findings[0]
    assert f.verdict == "STABLE"
    assert f.flake_risk <= 10
    assert f.priority == "P3"
    assert report.grade == "A"


def test_flaky_intermittent():
    advisor = FlakeAdvisor(now=FIXED_NOW)
    report = advisor.analyze(_runs("test_flaky", "PFPFPFPFPF"))
    f = report.findings[0]
    assert f.verdict == "FLAKY"
    assert f.intermittency >= 0.30
    assert f.flake_risk >= 50


def test_consistent_failure():
    advisor = FlakeAdvisor(now=FIXED_NOW)
    report = advisor.analyze(_runs("test_red", "F" * 10))
    f = report.findings[0]
    assert f.verdict == "CONSISTENT_FAILURE"
    assert f.priority == "P0"
    assert f.flake_risk >= 80


def test_new_failure_after_stable_baseline():
    advisor = FlakeAdvisor(now=FIXED_NOW)
    pattern = "P" * 18 + "F" * 3
    report = advisor.analyze(_runs("test_regression", pattern))
    f = report.findings[0]
    assert f.verdict == "NEW_FAILURE"
    assert f.priority == "P0"


def test_under_tested_when_few_runs():
    advisor = FlakeAdvisor(now=FIXED_NOW, min_runs=5)
    report = advisor.analyze(_runs("test_short", "PP"))
    f = report.findings[0]
    assert f.verdict == "UNDER_TESTED"
    assert f.priority == "P3"


def test_slow_drift_detected():
    runs = []
    for i in range(12):
        runs.append(
            {
                "test_id": "test_slow",
                "outcome": "pass",
                # ramp duration 100ms -> ~250ms
                "duration_ms": 100.0 + i * 15,
                "timestamp": 1_700_000_000 + i * 60,
            }
        )
    advisor = FlakeAdvisor(now=FIXED_NOW, slow_drift_pct=0.30)
    report = advisor.analyze(runs)
    f = report.findings[0]
    assert f.verdict == "SLOW_DRIFT"
    assert f.duration_drift_pct is not None
    assert f.duration_drift_pct >= 0.30


def test_skipped_runs_excluded_from_pass_rate():
    advisor = FlakeAdvisor(now=FIXED_NOW)
    report = advisor.analyze(_runs("test_skips", "PPPPPSSS"))
    f = report.findings[0]
    assert f.skipped == 3
    assert f.runs == 5
    assert f.pass_rate == 1.0


def test_playbook_p0_first_and_dedup():
    runs = (
        _runs("t_red1", "F" * 10)
        + _runs("t_red2", "F" * 10)
        + _runs("t_red3", "F" * 10)
        + _runs("t_flaky", "PFPFPFPFPF")
    )
    advisor = FlakeAdvisor(now=FIXED_NOW)
    report = advisor.analyze(runs)
    priorities = [a.priority for a in report.playbook]
    assert priorities == sorted(priorities)
    ids = [a.id for a in report.playbook]
    assert "FIX_CONSISTENT_FAILURES" in ids
    # the consistent failures action lists all 3 reds
    fix = next(a for a in report.playbook if a.id == "FIX_CONSISTENT_FAILURES")
    assert set(fix.related_tests) == {"t_red1", "t_red2", "t_red3"}


def test_grade_f_when_many_red():
    runs = (
        _runs("t_red1", "F" * 10)
        + _runs("t_red2", "F" * 10)
        + _runs("t_red3", "F" * 10)
    )
    advisor = FlakeAdvisor(now=FIXED_NOW)
    report = advisor.analyze(runs)
    assert report.grade == "F"


def test_risk_appetite_monotonic():
    runs = _runs("t_flaky", "PFPFPFPFPF")
    cautious = FlakeAdvisor(now=FIXED_NOW, risk_appetite="cautious").analyze(runs)
    balanced = FlakeAdvisor(now=FIXED_NOW, risk_appetite="balanced").analyze(runs)
    aggressive = FlakeAdvisor(now=FIXED_NOW, risk_appetite="aggressive").analyze(runs)
    c_risk = cautious.findings[0].flake_risk
    b_risk = balanced.findings[0].flake_risk
    a_risk = aggressive.findings[0].flake_risk
    assert c_risk >= b_risk >= a_risk


def test_cautious_adds_audit_when_p0_or_p1():
    runs = _runs("t_red", "F" * 10)
    advisor = FlakeAdvisor(now=FIXED_NOW, risk_appetite="cautious")
    report = advisor.analyze(runs)
    ids = [a.id for a in report.playbook]
    assert "SCHEDULE_FLAKE_AUDIT" in ids


def test_aggressive_trims_p2_when_p0():
    runs = (
        _runs("t_red", "F" * 10)
        + _runs("t_under", "PP")  # under_tested -> P2 action
    )
    advisor = FlakeAdvisor(now=FIXED_NOW, risk_appetite="aggressive")
    report = advisor.analyze(runs)
    priorities = {a.priority for a in report.playbook}
    assert "P0" in priorities
    assert "P2" not in priorities  # GATHER_MORE_RUNS trimmed


def test_empty_input_grade_f():
    advisor = FlakeAdvisor(now=FIXED_NOW)
    report = advisor.analyze([])
    assert report.grade == "F"
    assert report.summary["total_tests"] == 0
    assert any("EMPTY_INPUT" in i for i in report.insights)


def test_json_byte_stable():
    runs = _runs("t_a", "PFPF" * 3)
    advisor = FlakeAdvisor(now=FIXED_NOW)
    a = advisor.analyze(runs).to_json()
    b = advisor.analyze(runs).to_json()
    assert a == b


def test_text_renderer_has_headline_and_sections():
    runs = _runs("t_a", "P" * 10)
    advisor = FlakeAdvisor(now=FIXED_NOW)
    text = advisor.analyze(runs).to_text()
    assert "VERDICT" in text
    assert "Summary:" in text
    assert "Findings" in text
    assert "Playbook" in text
    assert "Insights" in text


def test_markdown_renderer_has_tables():
    runs = _runs("t_a", "P" * 10)
    advisor = FlakeAdvisor(now=FIXED_NOW)
    md = advisor.analyze(runs).to_markdown()
    assert "## Summary" in md
    assert "## Findings" in md
    assert "## Playbook" in md
    assert "## Insights" in md
    assert "| metric | value |" in md


def test_format_dispatches_correctly():
    runs = _runs("t_a", "P" * 10)
    report = FlakeAdvisor(now=FIXED_NOW).analyze(runs)
    assert "VERDICT" in report.format("text")
    assert "## Summary" in report.format("md")
    assert "## Summary" in report.format("markdown")
    assert report.format("json").lstrip().startswith("{")


def test_format_unknown_raises():
    runs = _runs("t_a", "PPPPP")
    report = FlakeAdvisor(now=FIXED_NOW).analyze(runs)
    with pytest.raises(ValueError):
        report.format("xml")


def test_input_is_not_mutated():
    runs = _runs("t_a", "PFPFPF")
    snap = json.dumps(runs, sort_keys=True)
    advisor = FlakeAdvisor(now=FIXED_NOW)
    advisor.analyze(runs)
    assert json.dumps(runs, sort_keys=True) == snap


def test_invalid_risk_appetite_raises():
    with pytest.raises(ValueError):
        FlakeAdvisor(risk_appetite="reckless")


def test_invalid_min_runs_raises():
    with pytest.raises(ValueError):
        FlakeAdvisor(min_runs=0)


def test_string_iso_timestamp_supported():
    runs = [
        {
            "test_id": "t_a",
            "outcome": "pass",
            "timestamp": "2026-01-01T00:00:00Z",
            "duration_ms": 100,
        },
        {
            "test_id": "t_a",
            "outcome": "pass",
            "timestamp": "2026-01-01T00:01:00Z",
            "duration_ms": 100,
        },
    ]
    advisor = FlakeAdvisor(now=FIXED_NOW, min_runs=2)
    report = advisor.analyze(runs)
    assert report.findings[0].runs == 2


def test_cli_prints_verdict(tmp_path: Path):
    runs_path = tmp_path / "runs.json"
    runs_path.write_text(json.dumps(_runs("t_a", "P" * 10)), encoding="utf-8")
    cp = subprocess.run(
        [sys.executable, "sauravflake.py", str(runs_path), "--format", "text"],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parent),
    )
    assert cp.returncode == 0, cp.stderr
    assert "VERDICT" in cp.stdout


def test_cli_json_round_trip(tmp_path: Path):
    runs_path = tmp_path / "runs.json"
    runs_path.write_text(json.dumps(_runs("t_a", "PPPPP")), encoding="utf-8")
    out_path = tmp_path / "out.json"
    cp = subprocess.run(
        [
            sys.executable,
            "sauravflake.py",
            str(runs_path),
            "--format",
            "json",
            "--output",
            str(out_path),
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parent),
    )
    assert cp.returncode == 0, cp.stderr
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["grade"] == "A"
    assert payload["summary"]["total_tests"] == 1
