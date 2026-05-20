"""Tests for sauravonboard onboarding-path planner."""

from __future__ import annotations

import copy
import datetime as _dt
import json
import sys
from pathlib import Path

import pytest

# Ensure repo root is on sys.path so we can import the top-level module.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sauravonboard import (  # noqa: E402
    OnboardingAdvisor,
    OnboardingReport,
    discover_demos,
)


FIXED_NOW = _dt.datetime(2026, 5, 20, 21, 14, 0)


def _now():
    return FIXED_NOW


SAMPLE_DEMOS = [
    "hello.srv",
    "test_basics.srv",
    "csv_demo.srv",
    "json_demo.srv",
    "graph_demo.srv",
    "http_demo.srv",
    "reflex_demo.srv",
    "diplomacy_demo.srv",
    "stack_queue_demo.srv",
]


def _advisor(**kw):
    kw.setdefault("level", "novice")
    kw.setdefault("goal", "data")
    kw.setdefault("now_fn", _now)
    return OnboardingAdvisor(**kw)


def test_novice_data_goal_has_start_here_and_grade():
    advisor = _advisor(level="novice", goal="data")
    report = advisor.analyze(SAMPLE_DEMOS)
    assert isinstance(report, OnboardingReport)
    starts = [p for p in report.plans if p.verdict == "START_HERE"]
    assert starts, "novice data goal should have at least one START_HERE"
    # Coverage > 0 and grade is A-F.
    assert 0 <= report.coverage_score <= 100
    assert report.grade in {"A", "B", "C", "D", "F"}


def test_novice_skips_meta_topics():
    advisor = _advisor(level="novice", goal="data")
    report = advisor.analyze(["diplomacy_demo.srv", "reflex_demo.srv"])
    for p in report.plans:
        assert p.verdict == "SKIP", f"{p.filename} should be SKIP for novice"


def test_expert_gets_challenge_for_advanced_demos():
    advisor = _advisor(level="expert", goal="general")
    report = advisor.analyze(
        ["hello.srv", "reflex_demo.srv", "diplomacy_demo.srv"]
    )
    challenges = [p for p in report.plans if p.verdict == "CHALLENGE"]
    assert challenges, "expert should attempt advanced demos as CHALLENGE"


def test_empty_demo_set_produces_request_action():
    advisor = _advisor()
    report = advisor.analyze([])
    ids = {a.id for a in report.playbook}
    assert "REQUEST_DEMO_SET" in ids
    assert report.grade == "F"
    assert "EMPTY_DEMO_SET" in report.insights


def test_playbook_priorities_p0_first():
    advisor = _advisor(level="novice", goal="data")
    report = advisor.analyze(SAMPLE_DEMOS)
    priorities = [a.priority for a in report.playbook]
    rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    sorted_priorities = sorted(priorities, key=lambda p: rank[p])
    assert priorities == sorted_priorities


def test_json_is_byte_stable_and_deterministic():
    advisor1 = _advisor(level="intermediate", goal="cli")
    advisor2 = _advisor(level="intermediate", goal="cli")
    r1 = advisor1.analyze(SAMPLE_DEMOS).to_json()
    r2 = advisor2.analyze(SAMPLE_DEMOS).to_json()
    assert r1 == r2
    # Sort_keys: top-level keys are sorted alphabetically.
    payload = json.loads(r1)
    assert list(payload.keys()) == sorted(payload.keys())


def test_inputs_not_mutated():
    demos = list(SAMPLE_DEMOS)
    snap = copy.deepcopy(demos)
    advisor = _advisor()
    advisor.analyze(demos)
    assert demos == snap


def test_risk_appetite_changes_recommendations():
    cautious = _advisor(level="expert", goal="advanced",
                        risk_appetite="cautious").analyze(SAMPLE_DEMOS)
    aggressive = _advisor(level="expert", goal="advanced",
                          risk_appetite="aggressive").analyze(SAMPLE_DEMOS)
    # Different risk appetites should yield different reports somewhere.
    assert (cautious.to_json() != aggressive.to_json()), (
        "risk appetite should alter the report"
    )


def test_aggressive_trims_p3_when_real_work_present():
    advisor = _advisor(level="intermediate", goal="data",
                       risk_appetite="aggressive")
    report = advisor.analyze(SAMPLE_DEMOS)
    has_real = any(a.priority in ("P0", "P1") for a in report.playbook)
    if has_real:
        assert all(a.priority != "P3" for a in report.playbook)


def test_budget_overrun_triggers_reduce_scope():
    advisor = _advisor(level="novice", goal="data", minutes_per_week=10)
    report = advisor.analyze(SAMPLE_DEMOS)
    ids = {a.id for a in report.playbook}
    assert "REDUCE_SCOPE" in ids


def test_invalid_level_raises():
    with pytest.raises(ValueError):
        OnboardingAdvisor(level="guru", goal="data")


def test_invalid_risk_appetite_raises():
    with pytest.raises(ValueError):
        OnboardingAdvisor(level="novice", goal="data", risk_appetite="yolo")


def test_invalid_minutes_raises():
    with pytest.raises(ValueError):
        OnboardingAdvisor(level="novice", goal="data", minutes_per_week=0)


def test_renderers_produce_strings_with_expected_sections():
    report = _advisor().analyze(SAMPLE_DEMOS)
    text = report.to_text()
    md = report.to_markdown()
    js = report.to_json()
    assert "Demos:" in text and "Playbook:" in text and "Insights:" in text
    assert "## Demos" in md and "## Playbook" in md and "## Insights" in md
    payload = json.loads(js)
    assert {"plans", "playbook", "insights", "grade"}.issubset(payload.keys())


def test_unknown_goal_falls_back_to_general():
    # Should not raise; should still produce a report.
    advisor = _advisor(goal="quantum-leap")
    report = advisor.analyze(SAMPLE_DEMOS)
    assert report.goal == "quantum-leap"
    # 'general' preset includes basics+control_flow+collections+strings+io
    assert any(p.verdict in ("START_HERE", "NEXT", "PARALLEL")
               for p in report.plans)


def test_priority_ordering_within_plans():
    advisor = _advisor(level="novice", goal="data")
    report = advisor.analyze(SAMPLE_DEMOS)
    rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    ranks = [rank[p.priority] for p in report.plans]
    assert ranks == sorted(ranks)


def test_discover_demos_returns_sorted_unique(tmp_path):
    (tmp_path / "alpha_demo.srv").write_text("ok", encoding="utf-8")
    (tmp_path / "beta_demo.srv").write_text("ok", encoding="utf-8")
    (tmp_path / "notademo.srv").write_text("ok", encoding="utf-8")
    (tmp_path / "readme.txt").write_text("ok", encoding="utf-8")
    found = discover_demos(tmp_path)
    assert found == ["alpha_demo.srv", "beta_demo.srv"]


def test_missing_root_returns_empty_list(tmp_path):
    missing = tmp_path / "does-not-exist"
    assert discover_demos(missing) == []


def test_now_fn_is_used_in_generated_at():
    fixed = _dt.datetime(2030, 1, 1, 0, 0, 0)
    advisor = OnboardingAdvisor(level="novice", goal="data",
                                now_fn=lambda: fixed)
    report = advisor.analyze(SAMPLE_DEMOS)
    assert report.generated_at == fixed.isoformat()


def test_insufficient_starters_for_novice_grades_down():
    advisor = _advisor(level="novice", goal="advanced")
    # All advanced/meta demos -> no foundational starter.
    report = advisor.analyze(["reflex_demo.srv", "diplomacy_demo.srv",
                              "bounty_demo.srv"])
    assert report.grade in {"D", "F"}
    ids = {a.id for a in report.playbook}
    assert "BUILD_FOUNDATION_FIRST" in ids or "REQUEST_DEMO_SET" in ids
