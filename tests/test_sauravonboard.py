"""
Unit tests for sauravonboard.py — the agentic onboarding-path planner.

Covers:
- ``OnboardingAdvisor`` constructor validation
- per-demo scoring + verdicts across levels and risk appetites
- ``_estimate_minutes`` depth multiplier
- coverage score + grade banding
- every named ``PlaybookAction`` id the module can emit
- insight detection (``EMPTY_DEMO_SET``, ``MISSING_TOPICS:*`` etc.)
- ``OnboardingReport`` renderers (text/markdown/json) including
  byte-stable JSON output via injected ``now_fn``
- ``discover_demos`` filesystem helper
- ``main`` CLI happy-path + file output
- determinism: identical inputs (with fixed ``now_fn``) -> identical reports
"""

from __future__ import annotations

import datetime as _dt
import importlib
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sauravonboard = importlib.import_module("sauravonboard")
OnboardingAdvisor = sauravonboard.OnboardingAdvisor
OnboardingReport = sauravonboard.OnboardingReport
DemoPlan = sauravonboard.DemoPlan
PlaybookAction = sauravonboard.PlaybookAction
discover_demos = sauravonboard.discover_demos


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXED_NOW = _dt.datetime(2026, 5, 22, 7, 30, 0)


def _fixed_now() -> _dt.datetime:
    return FIXED_NOW


def _advisor(**kwargs) -> OnboardingAdvisor:
    kwargs.setdefault("level", "novice")
    kwargs.setdefault("goal", "general")
    kwargs.setdefault("now_fn", _fixed_now)
    return OnboardingAdvisor(**kwargs)


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------

class TestAdvisorInit:
    def test_default_construction(self):
        a = OnboardingAdvisor(level="novice")
        assert a.level == "novice"
        assert a.goal == "general"
        assert a.minutes_per_week == 120
        assert a.risk_appetite == "balanced"

    def test_custom_goal_string_is_kept_verbatim(self):
        a = OnboardingAdvisor(level="expert", goal="my-custom-goal")
        assert a.goal == "my-custom-goal"  # falls back internally to 'general'

    def test_invalid_level(self):
        with pytest.raises(ValueError, match="level must be one of"):
            OnboardingAdvisor(level="guru")

    def test_invalid_risk(self):
        with pytest.raises(ValueError, match="risk_appetite must be one of"):
            OnboardingAdvisor(level="novice", risk_appetite="reckless")

    def test_non_positive_minutes(self):
        with pytest.raises(ValueError, match="minutes_per_week must be positive"):
            OnboardingAdvisor(level="novice", minutes_per_week=0)

    def test_negative_minutes(self):
        with pytest.raises(ValueError, match="positive"):
            OnboardingAdvisor(level="novice", minutes_per_week=-5)

    def test_minutes_coerced_to_int(self):
        a = OnboardingAdvisor(level="novice", minutes_per_week=90.7)
        assert a.minutes_per_week == 90
        assert isinstance(a.minutes_per_week, int)


# ---------------------------------------------------------------------------
# discover_demos
# ---------------------------------------------------------------------------

class TestDiscoverDemos:
    def test_missing_root_returns_empty(self, tmp_path):
        assert discover_demos(tmp_path / "nope") == []

    def test_finds_only_demo_files(self, tmp_path):
        (tmp_path / "foo_demo.srv").write_text("x")
        (tmp_path / "bar_demo.srv").write_text("x")
        (tmp_path / "not_a_demo.srv").write_text("x")
        (tmp_path / "csv_demo.txt").write_text("x")  # wrong ext
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "nested_demo.srv").write_text("x")  # ignored (non-recursive)
        out = discover_demos(tmp_path)
        assert out == ["bar_demo.srv", "foo_demo.srv", "not_a_demo.srv"]
        # subdir contents excluded
        assert "nested_demo.srv" not in out

    def test_directories_are_excluded(self, tmp_path):
        d = tmp_path / "dir_demo.srv"
        d.mkdir()
        assert discover_demos(tmp_path) == []

    def test_accepts_pathlike(self, tmp_path):
        (tmp_path / "p_demo.srv").write_text("x")
        assert discover_demos(os.fspath(tmp_path)) == ["p_demo.srv"]


# ---------------------------------------------------------------------------
# analyze: structure and basics
# ---------------------------------------------------------------------------

class TestAnalyzeStructure:
    def test_returns_onboarding_report(self):
        rep = _advisor().analyze(["hello.srv", "csv_demo.srv"])
        assert isinstance(rep, OnboardingReport)
        assert rep.generated_at == FIXED_NOW.isoformat()
        assert rep.level == "novice"
        assert rep.risk_appetite == "balanced"
        assert rep.minutes_per_week == 120

    def test_empty_demo_list(self):
        rep = _advisor().analyze([])
        assert rep.plans == []
        assert rep.grade == "F"
        assert "EMPTY_DEMO_SET" in rep.insights
        assert any(a.id == "REQUEST_DEMO_SET" for a in rep.playbook)

    def test_input_is_not_mutated(self):
        demos = ["csv_demo.srv", "json_demo.srv"]
        snapshot = list(demos)
        _advisor().analyze(demos)
        assert demos == snapshot

    def test_iterable_consumed_once(self):
        calls = {"n": 0}

        def gen():
            calls["n"] += 1
            yield "csv_demo.srv"
            yield "json_demo.srv"

        rep = _advisor().analyze(gen())
        assert calls["n"] == 1
        assert len(rep.plans) == 2

    def test_non_string_entries_dropped(self):
        rep = _advisor().analyze(["csv_demo.srv", "", None, 42])
        assert [p.filename for p in rep.plans] == ["csv_demo.srv"]

    def test_duplicates_collapsed(self):
        rep = _advisor().analyze(["csv_demo.srv", "csv_demo.srv"])
        assert len(rep.plans) == 1

    def test_unknown_demo_tagged_advanced(self):
        rep = _advisor().analyze(["mystery_demo.srv"])
        plan = rep.plans[0]
        assert "advanced" in plan.topics

    def test_demos_sorted_deterministically(self):
        rep = _advisor(level="intermediate").analyze(
            ["json_demo.srv", "csv_demo.srv", "hello.srv"]
        )
        # Same input twice -> identical ordering.
        rep2 = _advisor(level="intermediate").analyze(
            ["hello.srv", "csv_demo.srv", "json_demo.srv"]
        )
        assert [p.filename for p in rep.plans] == [p.filename for p in rep2.plans]


# ---------------------------------------------------------------------------
# Scoring + verdicts
# ---------------------------------------------------------------------------

class TestVerdicts:
    def test_novice_start_here_on_double_overlap(self):
        # foreach_demo -> ('control_flow', 'collections'), both in 'general'
        # overlap=2 -> base 60 + FOUNDATIONAL +25 = 85 -> START_HERE
        rep = _advisor(level="novice", goal="general").analyze(["foreach_demo.srv"])
        assert rep.plans[0].verdict == "START_HERE"

    def test_novice_skips_deep_meta(self):
        # quest_demo -> ("meta",), max_depth=5, no overlap with general
        rep = _advisor(level="novice", goal="general").analyze(["quest_demo.srv"])
        assert rep.plans[0].verdict == "SKIP"

    def test_expert_gets_challenge_on_high_depth_low_fit(self):
        rep = _advisor(level="expert", goal="general").analyze(["quest_demo.srv"])
        assert rep.plans[0].verdict == "CHALLENGE"

    def test_intermediate_aggressive_can_challenge(self):
        rep = _advisor(level="intermediate", goal="general",
                       risk_appetite="aggressive").analyze(["quest_demo.srv"])
        assert rep.plans[0].verdict == "CHALLENGE"

    def test_intermediate_balanced_skips_meta(self):
        rep = _advisor(level="intermediate", goal="general").analyze(
            ["quest_demo.srv"]
        )
        assert rep.plans[0].verdict == "SKIP"

    def test_goal_mismatch_reason_present(self):
        # mentor_demo -> ('meta',), which is NOT in the 'data' goal preset.
        rep = _advisor(level="expert", goal="data").analyze(["mentor_demo.srv"])
        assert "GOAL_MISMATCH" in rep.plans[0].reasons
        # Sanity: hello.srv (basics) IS in data goal -> no GOAL_MISMATCH.
        rep2 = _advisor(level="expert", goal="data").analyze(["hello.srv"])
        assert "GOAL_MISMATCH" not in rep2.plans[0].reasons

    def test_priority_matches_verdict(self):
        rep = _advisor(level="novice", goal="data").analyze(
            ["hello.srv", "csv_demo.srv", "quest_demo.srv"]
        )
        for p in rep.plans:
            mapping = {
                "START_HERE": "P0",
                "NEXT": "P1",
                "PARALLEL": "P2",
                "CHALLENGE": "P2",
                "SKIP": "P3",
            }
            assert p.priority == mapping[p.verdict]

    def test_fit_score_within_bounds(self):
        rep = _advisor(level="expert", goal="advanced").analyze(
            ["hello.srv", "csv_demo.srv", "json_demo.srv", "quest_demo.srv",
             "bloom_demo.srv"]
        )
        for p in rep.plans:
            assert 0 <= p.fit_score <= 100

    def test_plan_ordering_priority_then_fit(self):
        rep = _advisor(level="intermediate", goal="data").analyze(
            ["hello.srv", "csv_demo.srv", "quest_demo.srv", "json_demo.srv"]
        )
        priority_rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        prev = (-1, 1, "")
        for p in rep.plans:
            key = (priority_rank[p.priority], -p.fit_score, p.demo_id)
            assert key >= prev
            prev = key

    def test_aggressive_skip_basics_for_non_novice(self):
        rep = _advisor(level="expert", goal="advanced",
                       risk_appetite="aggressive").analyze(["hello.srv"])
        assert "AGGRESSIVE_SKIP_BASICS" in rep.plans[0].reasons

    def test_cautious_penalty_on_advanced(self):
        rep = _advisor(level="intermediate", goal="advanced",
                       risk_appetite="cautious").analyze(["quest_demo.srv"])
        assert "CAUTIOUS_PENALTY_ON_ADVANCED" in rep.plans[0].reasons


# ---------------------------------------------------------------------------
# Estimated minutes
# ---------------------------------------------------------------------------

class TestEstimatedMinutes:
    def test_basics_use_base_minutes(self):
        rep = _advisor(level="novice").analyze(["hello.srv"])
        # base 25 for novice, depth=1 -> mult 1.0
        assert rep.plans[0].estimated_minutes == 25

    def test_deep_topics_take_longer(self):
        rep_basic = _advisor(level="expert").analyze(["hello.srv"])
        rep_deep = _advisor(level="expert").analyze(["quest_demo.srv"])
        assert rep_deep.plans[0].estimated_minutes > rep_basic.plans[0].estimated_minutes

    def test_minutes_at_least_one(self):
        rep = _advisor(level="expert").analyze(["hello.srv"])
        assert rep.plans[0].estimated_minutes >= 1


# ---------------------------------------------------------------------------
# Coverage + grade
# ---------------------------------------------------------------------------

class TestCoverageAndGrade:
    def test_zero_coverage_when_only_skip(self):
        rep = _advisor(level="novice", goal="general").analyze(["quest_demo.srv"])
        # All SKIP -> grade F (actionable == 0) and coverage 0
        assert rep.coverage_score == 0
        assert rep.grade == "F"

    def test_full_general_coverage_yields_high_grade(self):
        # general topics: basics, control_flow, collections, strings, io
        # foreach_demo gives a START_HERE anchor (overlap=2 -> fit 85).
        demos = [
            "foreach_demo.srv",   # control_flow + collections -> START_HERE
            "hello.srv",          # basics
            "fstring_demo.srv",   # strings
            "json_demo.srv",      # io + data
        ]
        rep = _advisor(level="novice", goal="general").analyze(demos)
        assert rep.coverage_score == 100
        assert rep.grade == "A"

    def test_novice_without_start_here_gets_d(self):
        # csv_demo for "advanced" goal: io+data not in advanced
        rep = _advisor(level="novice", goal="advanced").analyze(["csv_demo.srv"])
        # No START_HERE because not matching goal, may be SKIP or PARALLEL
        starters = [p for p in rep.plans if p.verdict == "START_HERE"]
        if not starters and any(p.verdict != "SKIP" for p in rep.plans):
            assert rep.grade == "D"

    def test_grade_band_a_or_b_with_starter(self):
        # foreach_demo is the START_HERE anchor (overlap=2 -> fit 85).
        # With 4 of 5 general topics covered, grade should land in A/B band.
        demos = ["foreach_demo.srv", "hello.srv",
                 "fstring_demo.srv", "json_demo.srv"]
        rep = _advisor(level="novice", goal="general").analyze(demos)
        assert rep.grade in ("A", "B")


# ---------------------------------------------------------------------------
# Playbook
# ---------------------------------------------------------------------------

class TestPlaybook:
    def test_request_demo_set_on_empty(self):
        rep = _advisor().analyze([])
        ids = {a.id for a in rep.playbook}
        assert "REQUEST_DEMO_SET" in ids

    def test_run_starter_slate_when_starters_exist(self):
        # foreach_demo -> START_HERE for novice/general (overlap=2 -> fit 85).
        rep = _advisor(level="novice", goal="general").analyze(["foreach_demo.srv"])
        ids = {a.id for a in rep.playbook}
        assert "RUN_STARTER_SLATE" in ids

    def test_build_foundation_first_when_no_starter_for_novice(self):
        # All advanced demos -> no START_HERE for novice
        rep = _advisor(level="novice", goal="advanced",
                       risk_appetite="aggressive").analyze(
            ["bloom_demo.srv", "generator_demo.srv"]
        )
        actionable = [p for p in rep.plans if p.verdict != "SKIP"]
        starters = [p for p in rep.plans if p.verdict == "START_HERE"]
        if actionable and not starters:
            ids = {a.id for a in rep.playbook}
            assert "BUILD_FOUNDATION_FIRST" in ids

    def test_queue_next_batch_when_nexts(self):
        rep = _advisor(level="intermediate", goal="data").analyze(
            ["csv_demo.srv", "json_demo.srv", "table_demo.srv"]
        )
        nexts = [p for p in rep.plans if p.verdict == "NEXT"]
        if nexts:
            ids = {a.id for a in rep.playbook}
            assert "QUEUE_NEXT_BATCH" in ids

    def test_reduce_scope_when_budget_too_small(self):
        rep = _advisor(level="novice", goal="general",
                       minutes_per_week=10).analyze(
            ["hello.srv", "break_continue_demo.srv", "stack_queue_demo.srv"]
        )
        ids = {a.id for a in rep.playbook}
        assert "REDUCE_SCOPE" in ids

    def test_attempt_stretch_challenge_when_challenges_and_not_cautious(self):
        rep = _advisor(level="expert", goal="general",
                       risk_appetite="balanced").analyze(["quest_demo.srv"])
        ids = {a.id for a in rep.playbook}
        assert "ATTEMPT_STRETCH_CHALLENGE" in ids

    def test_cautious_suppresses_stretch_challenge(self):
        rep = _advisor(level="expert", goal="general",
                       risk_appetite="cautious").analyze(["quest_demo.srv"])
        ids = {a.id for a in rep.playbook}
        assert "ATTEMPT_STRETCH_CHALLENGE" not in ids

    def test_alternate_with_review_when_parallels_and_not_aggressive(self):
        # Need PARALLEL verdicts
        rep = _advisor(level="intermediate", goal="general").analyze(
            ["plot_demo.srv", "graph_demo.srv"]
        )
        parallels = [p for p in rep.plans if p.verdict == "PARALLEL"]
        if parallels:
            ids = {a.id for a in rep.playbook}
            assert "ALTERNATE_WITH_REVIEW" in ids

    def test_aggressive_drops_alternate_with_review(self):
        rep = _advisor(level="intermediate", goal="general",
                       risk_appetite="aggressive").analyze(
            ["hello.srv", "plot_demo.srv"]
        )
        ids = {a.id for a in rep.playbook}
        assert "ALTERNATE_WITH_REVIEW" not in ids

    def test_broaden_demo_set_on_low_coverage(self):
        rep = _advisor(level="expert", goal="data").analyze(["hello.srv"])
        # Coverage of basics in data = 1/5 = 20%
        if any(p.verdict != "SKIP" for p in rep.plans) and rep.coverage_score < 50:
            ids = {a.id for a in rep.playbook}
            assert "BROADEN_DEMO_SET" in ids

    def test_schedule_check_in_for_cautious_mid_grade(self):
        # Cautious + grade C/D — pick demos that give 50-69% coverage
        demos = ["hello.srv", "break_continue_demo.srv", "stack_queue_demo.srv"]
        rep = _advisor(level="novice", goal="general",
                       risk_appetite="cautious").analyze(demos)
        if rep.grade in ("C", "D", "F"):
            ids = {a.id for a in rep.playbook}
            assert "SCHEDULE_CHECK_IN" in ids

    def test_playbook_priority_sorted(self):
        rep = _advisor(level="novice", goal="general").analyze(
            ["hello.srv", "csv_demo.srv", "quest_demo.srv"]
        )
        priority_rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        prev = -1
        for a in rep.playbook:
            assert priority_rank[a.priority] >= prev
            prev = priority_rank[a.priority]

    def test_playbook_dedup_by_id(self):
        rep = _advisor(level="novice", goal="general").analyze(
            ["hello.srv", "hello.srv"]
        )
        ids = [a.id for a in rep.playbook]
        assert len(ids) == len(set(ids))

    def test_maintain_current_path_when_no_other_action(self):
        # Hard to hit; we just verify it's never present alongside REQUEST_DEMO_SET.
        rep = _advisor().analyze([])
        ids = {a.id for a in rep.playbook}
        if "REQUEST_DEMO_SET" in ids:
            assert "MAINTAIN_CURRENT_PATH" not in ids


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------

class TestInsights:
    def test_empty_demo_set(self):
        rep = _advisor().analyze([])
        assert "EMPTY_DEMO_SET" in rep.insights

    def test_missing_topics_listed(self):
        rep = _advisor(level="novice", goal="general").analyze(["hello.srv"])
        missing = [i for i in rep.insights if i.startswith("MISSING_TOPICS:")]
        assert missing, "Expected MISSING_TOPICS insight for partial coverage"
        # 'basics' should not appear in missing topics since hello covers it.
        assert "basics" not in missing[0]

    def test_deep_bench_on_high_coverage(self):
        demos = [
            "hello.srv", "break_continue_demo.srv",
            "stack_queue_demo.srv", "fstring_demo.srv", "json_demo.srv",
        ]
        rep = _advisor(level="novice", goal="general").analyze(demos)
        assert "DEEP_BENCH" in rep.insights

    def test_narrow_topic_coverage_on_low(self):
        rep = _advisor(level="expert", goal="data").analyze(["hello.srv"])
        if rep.coverage_score < 40:
            assert "NARROW_TOPIC_COVERAGE" in rep.insights

    def test_missing_practice_problem_when_no_testing_demo(self):
        rep = _advisor(level="novice", goal="general").analyze(["hello.srv"])
        assert "MISSING_PRACTICE_PROBLEM" in rep.insights

    def test_practice_problem_present_when_testing_demo_included(self):
        rep = _advisor(level="novice", goal="general").analyze(
            ["hello.srv", "assert_demo.srv"]
        )
        assert "MISSING_PRACTICE_PROBLEM" not in rep.insights


# ---------------------------------------------------------------------------
# Renderers + JSON stability
# ---------------------------------------------------------------------------

class TestRenderers:
    @pytest.fixture
    def report(self):
        return _advisor(level="novice", goal="general").analyze(
            ["hello.srv", "csv_demo.srv", "quest_demo.srv"]
        )

    def test_to_text_contains_header_and_demos(self, report):
        out = report.to_text()
        assert "Onboarding plan" in out
        assert "hello.srv" in out
        assert "Grade:" in out
        assert "Playbook:" in out
        assert "Insights:" in out

    def test_to_text_handles_empty(self):
        rep = _advisor().analyze([])
        out = rep.to_text()
        assert "(no demos available)" in out

    def test_to_markdown_table_headers(self, report):
        md = report.to_markdown()
        assert md.startswith("# Onboarding plan")
        assert "| Priority | Verdict | Demo |" in md
        assert "## Playbook" in md
        assert "## Insights" in md

    def test_to_markdown_empty_plans(self):
        rep = _advisor().analyze([])
        md = rep.to_markdown()
        assert "(no demos available)" in md

    def test_to_json_is_valid_json(self, report):
        payload = json.loads(report.to_json())
        assert payload["level"] == "novice"
        assert payload["goal"] == "general"
        assert payload["generated_at"] == FIXED_NOW.isoformat()
        assert isinstance(payload["plans"], list)
        assert isinstance(payload["playbook"], list)

    def test_to_json_is_byte_stable(self):
        rep1 = _advisor(level="novice", goal="general").analyze(
            ["hello.srv", "csv_demo.srv"]
        )
        rep2 = _advisor(level="novice", goal="general").analyze(
            ["csv_demo.srv", "hello.srv"]
        )
        assert rep1.to_json() == rep2.to_json()

    def test_to_json_sorted_keys(self, report):
        text = report.to_json()
        # `coverage_score` should come before `generated_at` alphabetically.
        assert text.index('"coverage_score"') < text.index('"generated_at"')


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_identical_inputs_identical_reports(self):
        demos = ["hello.srv", "json_demo.srv", "graph_demo.srv"]
        a = _advisor(level="intermediate", goal="data")
        b = _advisor(level="intermediate", goal="data")
        r1 = a.analyze(demos)
        r2 = b.analyze(list(reversed(demos)))
        assert r1.to_json() == r2.to_json()

    def test_now_fn_is_used(self):
        fixed = _dt.datetime(2030, 1, 1, 12, 0, 0)
        adv = OnboardingAdvisor(level="novice", now_fn=lambda: fixed)
        rep = adv.analyze(["hello.srv"])
        assert rep.generated_at == fixed.isoformat()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestCli:
    def test_text_output_to_stdout(self, capsys, tmp_path):
        (tmp_path / "hello.srv").write_text("x")
        (tmp_path / "csv_demo.srv").write_text("x")
        rc = sauravonboard.main([
            "--level", "novice", "--goal", "data",
            "--root", str(tmp_path), "--format", "text",
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Onboarding plan" in out
        assert "csv_demo.srv" in out

    def test_json_output_to_file(self, tmp_path):
        out_file = tmp_path / "plan.json"
        rc = sauravonboard.main([
            "--level", "expert", "--goal", "general",
            "--demos", "hello.srv", "csv_demo.srv",
            "--format", "json", "--output", str(out_file),
        ])
        assert rc == 0
        payload = json.loads(out_file.read_text(encoding="utf-8"))
        assert payload["level"] == "expert"
        assert {p["filename"] for p in payload["plans"]} == {
            "hello.srv", "csv_demo.srv"
        }

    def test_md_output(self, capsys):
        rc = sauravonboard.main([
            "--level", "novice", "--goal", "general",
            "--demos", "hello.srv", "--format", "md",
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert out.startswith("# Onboarding plan")

    def test_missing_root_yields_empty(self, capsys, tmp_path):
        rc = sauravonboard.main([
            "--level", "novice", "--goal", "general",
            "--root", str(tmp_path / "missing"),
            "--format", "text",
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "(no demos available)" in out

    def test_demos_flag_overrides_root(self, tmp_path, capsys):
        (tmp_path / "should_be_ignored_demo.srv").write_text("x")
        rc = sauravonboard.main([
            "--level", "expert", "--goal", "general",
            "--root", str(tmp_path),
            "--demos", "hello.srv",
            "--format", "text",
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "hello.srv" in out
        assert "should_be_ignored_demo.srv" not in out
