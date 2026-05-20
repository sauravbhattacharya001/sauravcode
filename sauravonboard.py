"""
sauravonboard — Agentic onboarding-path planner for sauravcode learners.

Given (a) a user profile (experience level + learning goal + optional
time-per-week budget) and (b) the set of ``*_demo.srv`` files shipped with
this repo (or any supplied list), this module computes a *personalised*
curriculum: which demo to start with, what to do next, what to do in
parallel, what to skip, and what to attempt as a stretch challenge.

It is the missing piece between "look at the README" and "now write your
own .srv program": opinionated, prioritised, and explainable.

Agentic shape (matches the rest of the saurav* advisor family)
--------------------------------------------------------------
- per-demo **verdict**: ``START_HERE`` / ``NEXT`` / ``PARALLEL`` / ``SKIP``
  / ``CHALLENGE``
- 0-100 ``fit_score`` per demo plus an ``estimated_minutes`` time tag
- portfolio A-F ``grade`` describing how well the available demos cover
  the user's goal
- P0/P1/P2/P3 deduped **playbook** of coach actions
  (``BUILD_FOUNDATION_FIRST``, ``RUN_STARTER_SLATE``,
  ``ALTERNATE_WITH_REVIEW``, ``ATTEMPT_STRETCH_CHALLENGE``, ...)
- ``insights`` list (e.g. ``NARROW_TOPIC_COVERAGE``, ``DEEP_BENCH``,
  ``MISSING_PRACTICE_PROBLEM``)
- ``risk_appetite`` knob: ``cautious`` favours review + foundation,
  ``aggressive`` skips remedial work and front-loads challenges
- pure stdlib, deterministic (injectable ``now_fn``), never mutates inputs
- ``to_text`` / ``to_markdown`` / ``to_json`` renderers; JSON is byte-stable
  (``sort_keys=True, indent=2, default=str``)

CLI
---
::

    python sauravonboard.py --level novice --goal data --format md
    python sauravonboard.py --level expert --goal cli --root . --format json

Public API
----------
- ``OnboardingAdvisor(level, goal, minutes_per_week=120,
  risk_appetite="balanced", now_fn=None)``
- ``OnboardingAdvisor.analyze(demos)`` -> ``OnboardingReport``
- ``OnboardingReport.to_text() / .to_markdown() / .to_json()``
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

__all__ = [
    "OnboardingAdvisor",
    "OnboardingReport",
    "DemoPlan",
    "PlaybookAction",
    "discover_demos",
]

# ---------------------------------------------------------------------------
# Static knowledge about the .srv demo set
# ---------------------------------------------------------------------------

# Topic tag -> rough "weight" describing how foundational the topic is.
# Lower = more foundational. Used to keep novices on basics first.
_TOPIC_DEPTH = {
    "basics": 1,
    "control_flow": 1,
    "collections": 2,
    "strings": 2,
    "io": 2,
    "datetime": 2,
    "data": 3,
    "graph": 3,
    "math": 3,
    "concurrency": 4,
    "web": 3,
    "cli": 2,
    "testing": 3,
    "advanced": 5,
    "meta": 5,
}

# Coarse mapping from demo filename stems to topic tags.
# Each demo can have multiple tags. Anything not listed defaults to
# ``("advanced",)`` so unknown demos are deferred for novices but visible
# to experts.
_DEMO_TAGS: dict[str, tuple[str, ...]] = {
    "hello": ("basics",),
    "a": ("basics",),
    "test": ("basics", "testing"),
    "test_basics": ("basics", "testing"),
    "test_builtins": ("basics", "testing"),
    "test_all": ("testing",),
    "test_fstring": ("strings", "testing"),
    "import_demo": ("basics", "cli"),
    "import_utils": ("basics", "cli"),
    "break_continue_demo": ("control_flow",),
    "foreach_demo": ("control_flow", "collections"),
    "try_catch_demo": ("control_flow",),
    "assert_demo": ("control_flow", "testing"),
    "validation_demo": ("control_flow", "testing"),
    "fstring_demo": ("strings",),
    "regex_demo": ("strings",),
    "datetime_demo": ("datetime",),
    "csv_demo": ("io", "data"),
    "json_demo": ("io", "data"),
    "table_demo": ("data",),
    "stdlib_demo": ("basics",),
    "env_sys_demo": ("cli",),
    "logging_demo": ("cli",),
    "http_demo": ("web",),
    "canvas_demo": ("web",),
    "plot_demo": ("data",),
    "compression_demo": ("io",),
    "hash_demo": ("io",),
    "cipher_demo": ("io",),
    "random_data_demo": ("math", "data"),
    "number_theory_demo": ("math",),
    "combinatorics_demo": ("math",),
    "stack_queue_demo": ("collections",),
    "deque_demo": ("collections",),
    "linkedlist_demo": ("collections",),
    "trie_demo": ("collections",),
    "heap_demo": ("collections",),
    "ring_demo": ("collections",),
    "omap_demo": ("collections",),
    "map_demo": ("collections",),
    "graph_demo": ("graph",),
    "interval_demo": ("math",),
    "matrix_demo": ("math",),
    "bloom_demo": ("collections", "advanced"),
    "cache_demo": ("collections",),
    "slice_demo": ("collections",),
    "collection_demo": ("collections",),
    "generator_demo": ("advanced",),
    "pipe_demo": ("advanced",),
    "pack_demo": ("io",),
    "emitter_demo": ("advanced",),
    "fsm_demo": ("advanced",),
    "automata_demo": ("advanced",),
    "contract_demo": ("testing", "advanced"),
    "diagnose_demo": ("testing", "meta"),
    "doctor_demo": ("testing", "meta"),
    "heal_demo": ("meta",),
    "reflex_demo": ("meta", "concurrency"),
    "pulse_demo": ("meta", "concurrency"),
    "forecast_demo": ("data", "meta"),
    "fossil_demo": ("meta",),
    "mentor_demo": ("meta",),
    "mutant_demo": ("testing", "meta"),
    "autopatch_demo": ("meta",),
    "adapt_demo": ("meta",),
    "optimize_demo": ("meta",),
    "diplomacy_demo": ("meta",),
    "bounty_demo": ("meta",),
    "debt_demo": ("meta",),
    "impact_demo": ("meta",),
    "quest_demo": ("meta",),
    "clone_demo": ("meta",),
}

# Goal preset -> ordered list of topics it cares about.
_GOAL_PRESETS = {
    "general": ("basics", "control_flow", "collections", "strings", "io"),
    "web": ("basics", "strings", "io", "web", "cli", "data"),
    "data": ("basics", "collections", "io", "data", "math"),
    "cli": ("basics", "control_flow", "strings", "io", "cli"),
    "advanced": ("collections", "advanced", "concurrency", "meta"),
}

_LEVELS = ("novice", "intermediate", "expert")
_RISK = ("cautious", "balanced", "aggressive")

# Per-level estimated minutes per .srv demo.
_MINUTES_PER_DEMO = {"novice": 25, "intermediate": 15, "expert": 8}

_VERDICT_PRIORITY = {
    "START_HERE": "P0",
    "NEXT": "P1",
    "PARALLEL": "P2",
    "CHALLENGE": "P2",
    "SKIP": "P3",
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DemoPlan:
    demo_id: str          # filename stem, e.g. "csv_demo"
    filename: str         # e.g. "csv_demo.srv"
    verdict: str          # one of the VERDICT strings above
    priority: str         # P0..P3
    fit_score: int        # 0-100
    estimated_minutes: int
    topics: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PlaybookAction:
    id: str
    priority: str
    label: str
    reason: str
    owner: str            # e.g. "learner", "mentor", "coach"
    blast_radius: int     # 1..5
    reversibility: str    # low | medium | high
    related_demos: tuple[str, ...] = ()


@dataclass
class OnboardingReport:
    generated_at: str
    level: str
    goal: str
    risk_appetite: str
    minutes_per_week: int
    summary: str
    grade: str            # A..F
    coverage_score: int   # 0-100
    plans: list[DemoPlan]
    playbook: list[PlaybookAction]
    insights: list[str]

    # ------------------------------------------------------------------
    # Renderers
    # ------------------------------------------------------------------

    def to_json(self) -> str:
        payload = {
            "generated_at": self.generated_at,
            "level": self.level,
            "goal": self.goal,
            "risk_appetite": self.risk_appetite,
            "minutes_per_week": self.minutes_per_week,
            "summary": self.summary,
            "grade": self.grade,
            "coverage_score": self.coverage_score,
            "plans": [
                {
                    "demo_id": p.demo_id,
                    "filename": p.filename,
                    "verdict": p.verdict,
                    "priority": p.priority,
                    "fit_score": p.fit_score,
                    "estimated_minutes": p.estimated_minutes,
                    "topics": list(p.topics),
                    "reasons": list(p.reasons),
                }
                for p in self.plans
            ],
            "playbook": [
                {
                    "id": a.id,
                    "priority": a.priority,
                    "label": a.label,
                    "reason": a.reason,
                    "owner": a.owner,
                    "blast_radius": a.blast_radius,
                    "reversibility": a.reversibility,
                    "related_demos": list(a.related_demos),
                }
                for a in self.playbook
            ],
            "insights": list(self.insights),
        }
        return json.dumps(payload, sort_keys=True, indent=2, default=str)

    def to_text(self) -> str:
        lines = [
            f"Onboarding plan ({self.level} -> {self.goal}, "
            f"{self.risk_appetite}, {self.minutes_per_week} min/wk)",
            "=" * 60,
            f"Summary: {self.summary}",
            f"Grade: {self.grade}   Coverage score: {self.coverage_score}/100",
            "",
            "Demos:",
        ]
        if not self.plans:
            lines.append("  (no demos available)")
        for p in self.plans:
            lines.append(
                f"  [{p.priority}] {p.verdict:<10} {p.filename:<28} "
                f"fit={p.fit_score:>3} ~{p.estimated_minutes}min  "
                f"topics={','.join(p.topics)}"
            )
            for r in p.reasons:
                lines.append(f"      - {r}")
        lines.append("")
        lines.append("Playbook:")
        if not self.playbook:
            lines.append("  (no actions)")
        for a in self.playbook:
            lines.append(
                f"  [{a.priority}] {a.id}  ({a.owner}, blast={a.blast_radius}, "
                f"reversibility={a.reversibility})"
            )
            lines.append(f"      {a.label}")
            lines.append(f"      reason: {a.reason}")
            if a.related_demos:
                lines.append(
                    f"      demos: {', '.join(a.related_demos)}"
                )
        lines.append("")
        lines.append("Insights:")
        if not self.insights:
            lines.append("  (none)")
        for ins in self.insights:
            lines.append(f"  - {ins}")
        return "\n".join(lines)

    def to_markdown(self) -> str:
        lines = [
            f"# Onboarding plan — {self.level} → {self.goal}",
            "",
            f"_Generated: {self.generated_at}_  ",
            f"_Risk appetite: **{self.risk_appetite}**, "
            f"budget: **{self.minutes_per_week} min/week**_",
            "",
            "## Summary",
            "",
            f"- **Grade:** {self.grade}",
            f"- **Coverage score:** {self.coverage_score}/100",
            f"- {self.summary}",
            "",
            "## Demos",
            "",
            "| Priority | Verdict | Demo | Fit | ~min | Topics |",
            "|---|---|---|---|---|---|",
        ]
        if not self.plans:
            lines.append("| — | — | (no demos available) | — | — | — |")
        for p in self.plans:
            lines.append(
                f"| {p.priority} | {p.verdict} | `{p.filename}` | "
                f"{p.fit_score} | {p.estimated_minutes} | "
                f"{', '.join(p.topics)} |"
            )
        lines += ["", "## Playbook", ""]
        if not self.playbook:
            lines.append("_No actions — you are good to go._")
        else:
            lines.append("| Priority | Action | Owner | Blast | Reversible | Demos |")
            lines.append("|---|---|---|---|---|---|")
            for a in self.playbook:
                lines.append(
                    f"| {a.priority} | **{a.id}** — {a.label} | {a.owner} | "
                    f"{a.blast_radius} | {a.reversibility} | "
                    f"{', '.join(a.related_demos) or '—'} |"
                )
        lines += ["", "## Insights", ""]
        if not self.insights:
            lines.append("_No additional insights._")
        for ins in self.insights:
            lines.append(f"- {ins}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def discover_demos(root: str | os.PathLike[str] = ".") -> list[str]:
    """Return a sorted list of ``*_demo.srv`` filenames under ``root``.

    Pure filesystem read. Never mutates anything.
    """
    p = Path(root)
    if not p.exists():
        return []
    return sorted(f.name for f in p.glob("*_demo.srv") if f.is_file())


# ---------------------------------------------------------------------------
# Core advisor
# ---------------------------------------------------------------------------

class OnboardingAdvisor:
    """Plans a personalised demo curriculum.

    Parameters
    ----------
    level : str
        One of ``"novice"``, ``"intermediate"``, ``"expert"``.
    goal : str
        One of the keys in :data:`_GOAL_PRESETS` or any custom string
        (custom strings fall back to the ``"general"`` preset).
    minutes_per_week : int
        Time the learner can realistically commit. Used to compute the
        starter slate size and ``REDUCE_SCOPE`` warnings.
    risk_appetite : str
        ``"cautious"`` (default-safe, more review), ``"balanced"``, or
        ``"aggressive"`` (front-load challenges, skip remedial work).
    now_fn : callable
        Injectable clock for deterministic tests. Defaults to
        :func:`datetime.datetime.utcnow`.
    """

    def __init__(
        self,
        level: str,
        goal: str = "general",
        minutes_per_week: int = 120,
        risk_appetite: str = "balanced",
        now_fn: Optional[Callable[[], _dt.datetime]] = None,
    ):
        if level not in _LEVELS:
            raise ValueError(f"level must be one of {_LEVELS}, got {level!r}")
        if risk_appetite not in _RISK:
            raise ValueError(
                f"risk_appetite must be one of {_RISK}, got {risk_appetite!r}"
            )
        if minutes_per_week <= 0:
            raise ValueError("minutes_per_week must be positive")
        self.level = level
        self.goal = goal
        self.minutes_per_week = int(minutes_per_week)
        self.risk_appetite = risk_appetite
        self._now_fn = now_fn or _dt.datetime.utcnow

    # ------------------------------------------------------------------

    def analyze(self, demos: Iterable[str]) -> OnboardingReport:
        """Build an :class:`OnboardingReport` for ``demos``.

        ``demos`` is an iterable of filenames (e.g. ``"csv_demo.srv"``).
        Items that don't look like demos are silently dropped. Input is
        never mutated; the iterable is consumed exactly once.
        """
        demo_list = sorted({d for d in demos if isinstance(d, str) and d})
        goal_topics = _GOAL_PRESETS.get(self.goal, _GOAL_PRESETS["general"])
        per_demo_minutes = _MINUTES_PER_DEMO[self.level]

        plans: list[DemoPlan] = []
        for filename in demo_list:
            stem = filename[:-4] if filename.endswith(".srv") else filename
            topics = _DEMO_TAGS.get(stem, ("advanced",))
            fit, reasons, verdict = self._score_demo(stem, topics, goal_topics)
            est = self._estimate_minutes(per_demo_minutes, topics)
            plans.append(
                DemoPlan(
                    demo_id=stem,
                    filename=filename,
                    verdict=verdict,
                    priority=_VERDICT_PRIORITY[verdict],
                    fit_score=fit,
                    estimated_minutes=est,
                    topics=tuple(topics),
                    reasons=tuple(reasons),
                )
            )

        # Deterministic ordering: priority asc, fit desc, name asc.
        priority_rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        plans.sort(
            key=lambda p: (priority_rank[p.priority], -p.fit_score, p.demo_id)
        )

        coverage_score = self._coverage_score(plans, goal_topics)
        grade = self._grade(coverage_score, plans)
        playbook = self._playbook(plans, goal_topics, coverage_score)
        insights = self._insights(plans, goal_topics, coverage_score)
        summary = self._summary(plans, grade, coverage_score)

        return OnboardingReport(
            generated_at=self._now_fn().isoformat(),
            level=self.level,
            goal=self.goal,
            risk_appetite=self.risk_appetite,
            minutes_per_week=self.minutes_per_week,
            summary=summary,
            grade=grade,
            coverage_score=coverage_score,
            plans=plans,
            playbook=playbook,
            insights=insights,
        )

    # ------------------------------------------------------------------
    # Scoring helpers
    # ------------------------------------------------------------------

    def _score_demo(
        self,
        stem: str,
        topics: tuple[str, ...] | list[str],
        goal_topics: tuple[str, ...],
    ) -> tuple[int, list[str], str]:
        reasons: list[str] = []
        topics = tuple(topics)
        depth = min((_TOPIC_DEPTH.get(t, 3) for t in topics), default=3)
        max_depth = max((_TOPIC_DEPTH.get(t, 3) for t in topics), default=3)
        goal_set = set(goal_topics)
        overlap = sum(1 for t in topics if t in goal_set)

        # Base score from goal relevance: 30 per matching topic, capped.
        base = min(60, 30 * overlap)
        if overlap == 0:
            reasons.append("GOAL_MISMATCH")
        else:
            reasons.append(f"GOAL_OVERLAP={overlap}")

        # Level-fit adjustment.
        if self.level == "novice":
            if depth <= 2:
                base += 25
                reasons.append("FOUNDATIONAL")
            elif max_depth >= 4:
                base -= 25
                reasons.append("TOO_ADVANCED_FOR_NOVICE")
        elif self.level == "intermediate":
            if 2 <= depth <= 3:
                base += 15
                reasons.append("LEVEL_FIT")
            elif max_depth >= 5:
                base -= 10
                reasons.append("META_TOPIC")
        else:  # expert
            if max_depth >= 4:
                base += 15
                reasons.append("STRETCH_MATERIAL")
            elif depth == 1 and overlap == 0:
                base -= 20
                reasons.append("LIKELY_BORING_FOR_EXPERT")

        # Risk-appetite modulation.
        if self.risk_appetite == "cautious":
            if max_depth >= 4:
                base -= 10
                reasons.append("CAUTIOUS_PENALTY_ON_ADVANCED")
        elif self.risk_appetite == "aggressive":
            if depth == 1 and self.level != "novice":
                base -= 10
                reasons.append("AGGRESSIVE_SKIP_BASICS")
            if max_depth >= 4:
                base += 5
                reasons.append("AGGRESSIVE_FAVOURS_DEPTH")

        fit = max(0, min(100, base))
        verdict = self._verdict(fit, depth, max_depth, overlap)
        return fit, reasons, verdict

    def _verdict(
        self, fit: int, depth: int, max_depth: int, overlap: int
    ) -> str:
        # Novices: hard floor on depth.
        if self.level == "novice" and max_depth >= 5 and overlap == 0:
            return "SKIP"
        if fit >= 80 and depth <= 2:
            return "START_HERE"
        if fit >= 65:
            return "NEXT"
        if fit >= 45:
            return "PARALLEL"
        # Experts get to attempt high-depth low-fit items as challenges.
        if self.level == "expert" and max_depth >= 4:
            return "CHALLENGE"
        if (
            self.level == "intermediate"
            and max_depth >= 4
            and self.risk_appetite == "aggressive"
        ):
            return "CHALLENGE"
        return "SKIP"

    def _estimate_minutes(
        self, base: int, topics: tuple[str, ...] | list[str]
    ) -> int:
        max_depth = max((_TOPIC_DEPTH.get(t, 3) for t in topics), default=3)
        # Bigger topics take longer to digest.
        mult = 1.0 + 0.15 * max(0, max_depth - 2)
        return max(1, int(round(base * mult)))

    # ------------------------------------------------------------------
    # Portfolio metrics
    # ------------------------------------------------------------------

    def _coverage_score(
        self, plans: list[DemoPlan], goal_topics: tuple[str, ...]
    ) -> int:
        if not plans or not goal_topics:
            return 0
        covered: set[str] = set()
        for p in plans:
            if p.verdict in ("SKIP",):
                continue
            for t in p.topics:
                if t in goal_topics:
                    covered.add(t)
        ratio = len(covered) / len(goal_topics)
        return int(round(min(100.0, ratio * 100)))

    def _grade(self, coverage_score: int, plans: list[DemoPlan]) -> str:
        starters = sum(1 for p in plans if p.verdict == "START_HERE")
        actionable = sum(1 for p in plans if p.verdict != "SKIP")
        if not plans or actionable == 0:
            return "F"
        if self.level == "novice" and starters == 0:
            return "D"
        if coverage_score >= 85 and starters >= 1:
            return "A"
        if coverage_score >= 70:
            return "B"
        if coverage_score >= 50:
            return "C"
        if coverage_score >= 30:
            return "D"
        return "F"

    # ------------------------------------------------------------------
    # Playbook + insights
    # ------------------------------------------------------------------

    def _playbook(
        self,
        plans: list[DemoPlan],
        goal_topics: tuple[str, ...],
        coverage_score: int,
    ) -> list[PlaybookAction]:
        actions: list[PlaybookAction] = []
        starters = [p for p in plans if p.verdict == "START_HERE"]
        nexts = [p for p in plans if p.verdict == "NEXT"]
        parallels = [p for p in plans if p.verdict == "PARALLEL"]
        challenges = [p for p in plans if p.verdict == "CHALLENGE"]
        actionable = [p for p in plans if p.verdict != "SKIP"]

        # ---- P0 actions ------------------------------------------------
        if self.level == "novice" and not starters and actionable:
            # No clear "start here" demo — flag it.
            actions.append(PlaybookAction(
                id="BUILD_FOUNDATION_FIRST",
                priority="P0",
                label="Find or write a basics-tagged demo before starting",
                reason=(
                    "No START_HERE demo was found for a novice profile; "
                    "without a basics anchor the learner will bounce."
                ),
                owner="mentor",
                blast_radius=4,
                reversibility="medium",
                related_demos=tuple(p.filename for p in actionable[:3]),
            ))

        if starters:
            actions.append(PlaybookAction(
                id="RUN_STARTER_SLATE",
                priority="P0",
                label="Run the START_HERE demos in order before anything else",
                reason=(
                    f"{len(starters)} foundational demo(s) directly match "
                    f"your goal '{self.goal}'."
                ),
                owner="learner",
                blast_radius=2,
                reversibility="high",
                related_demos=tuple(p.filename for p in starters),
            ))

        if not actionable:
            actions.append(PlaybookAction(
                id="REQUEST_DEMO_SET",
                priority="P0",
                label="Ask for a demo set — nothing actionable was supplied",
                reason="The advisor received no usable demo filenames.",
                owner="coach",
                blast_radius=3,
                reversibility="high",
            ))

        # ---- P1 actions ------------------------------------------------
        if nexts:
            actions.append(PlaybookAction(
                id="QUEUE_NEXT_BATCH",
                priority="P1",
                label="Schedule the NEXT demos after the starter slate",
                reason=(
                    f"{len(nexts)} demo(s) build directly on starter material."
                ),
                owner="learner",
                blast_radius=2,
                reversibility="high",
                related_demos=tuple(p.filename for p in nexts[:5]),
            ))

        weekly_slate = self._weekly_slate(plans)
        weekly_minutes = sum(p.estimated_minutes for p in weekly_slate)
        if weekly_minutes > self.minutes_per_week:
            actions.append(PlaybookAction(
                id="REDUCE_SCOPE",
                priority="P1",
                label=(
                    f"Trim weekly slate: planned {weekly_minutes} min vs "
                    f"budget {self.minutes_per_week} min"
                ),
                reason="Estimated time exceeds the learner's stated budget.",
                owner="coach",
                blast_radius=3,
                reversibility="high",
                related_demos=tuple(p.filename for p in weekly_slate),
            ))

        # ---- P2 actions ------------------------------------------------
        if parallels and self.risk_appetite != "aggressive":
            actions.append(PlaybookAction(
                id="ALTERNATE_WITH_REVIEW",
                priority="P2",
                label="Alternate PARALLEL demos with starter review sessions",
                reason="Mixing review with new material aids retention.",
                owner="learner",
                blast_radius=1,
                reversibility="high",
                related_demos=tuple(p.filename for p in parallels[:3]),
            ))

        if challenges and self.risk_appetite != "cautious":
            actions.append(PlaybookAction(
                id="ATTEMPT_STRETCH_CHALLENGE",
                priority="P2",
                label="Attempt one CHALLENGE demo per cycle",
                reason=(
                    "Stretch material drives skill growth once the basics "
                    "are stable."
                ),
                owner="learner",
                blast_radius=2,
                reversibility="high",
                related_demos=tuple(p.filename for p in challenges[:3]),
            ))

        if coverage_score < 50 and actionable:
            actions.append(PlaybookAction(
                id="BROADEN_DEMO_SET",
                priority="P2",
                label="Pull in more demos covering missing goal topics",
                reason=(
                    f"Coverage is {coverage_score}/100 for goal "
                    f"'{self.goal}'."
                ),
                owner="coach",
                blast_radius=3,
                reversibility="high",
            ))

        # ---- P3 fallback ----------------------------------------------
        if not actions:
            actions.append(PlaybookAction(
                id="MAINTAIN_CURRENT_PATH",
                priority="P3",
                label="Stay the course — the current set looks sufficient",
                reason="No higher-priority interventions detected.",
                owner="coach",
                blast_radius=1,
                reversibility="high",
            ))
        elif self.risk_appetite == "cautious" and self._grade(
            coverage_score, plans
        ) in ("C", "D", "F"):
            actions.append(PlaybookAction(
                id="SCHEDULE_CHECK_IN",
                priority="P3",
                label="Schedule a mentor check-in after the first slate",
                reason=(
                    "Cautious appetite plus mid-tier grade — confirm "
                    "comprehension before advancing."
                ),
                owner="mentor",
                blast_radius=1,
                reversibility="high",
            ))

        # Aggressive trims P3 / lone P2 noise when there is real work.
        if self.risk_appetite == "aggressive":
            has_real = any(a.priority in ("P0", "P1") for a in actions)
            if has_real:
                actions = [
                    a for a in actions
                    if a.priority != "P3"
                    and not (a.priority == "P2" and a.id == "ALTERNATE_WITH_REVIEW")
                ]

        # Dedup by id, keeping the first (which preserves priority order
        # because we appended P0->P3).
        seen: set[str] = set()
        deduped: list[PlaybookAction] = []
        for a in actions:
            if a.id in seen:
                continue
            seen.add(a.id)
            deduped.append(a)

        # Final ordering: P0 first, then by insertion order.
        priority_rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        deduped.sort(key=lambda a: (priority_rank[a.priority], a.id))
        return deduped

    def _weekly_slate(self, plans: list[DemoPlan]) -> list[DemoPlan]:
        """Greedy slate fitting within ``minutes_per_week``."""
        slate: list[DemoPlan] = []
        spent = 0
        for p in plans:
            if p.verdict == "SKIP":
                continue
            slate.append(p)
            spent += p.estimated_minutes
            if spent >= self.minutes_per_week:
                break
        return slate

    def _insights(
        self,
        plans: list[DemoPlan],
        goal_topics: tuple[str, ...],
        coverage_score: int,
    ) -> list[str]:
        out: list[str] = []
        actionable = [p for p in plans if p.verdict != "SKIP"]
        if not plans:
            out.append("EMPTY_DEMO_SET")
            return out
        if not actionable:
            out.append("NO_ACTIONABLE_DEMOS")
        topics_seen = {t for p in actionable for t in p.topics}
        missing = [t for t in goal_topics if t not in topics_seen]
        if missing:
            out.append(f"MISSING_TOPICS:{','.join(missing)}")
        if coverage_score >= 85:
            out.append("DEEP_BENCH")
        elif coverage_score < 40:
            out.append("NARROW_TOPIC_COVERAGE")
        # Practice-problem detection: testing demos present?
        if not any("testing" in p.topics for p in actionable):
            out.append("MISSING_PRACTICE_PROBLEM")
        if self.level == "novice" and any(
            p.verdict == "CHALLENGE" for p in plans
        ):
            out.append("CHALLENGE_SUPPRESSED_FOR_NOVICE")
        if self.level == "expert" and all(
            p.verdict in ("SKIP", "START_HERE", "NEXT") for p in actionable
        ) and actionable:
            out.append("NO_STRETCH_AVAILABLE")
        return out

    def _summary(
        self,
        plans: list[DemoPlan],
        grade: str,
        coverage_score: int,
    ) -> str:
        counts = {v: 0 for v in (
            "START_HERE", "NEXT", "PARALLEL", "CHALLENGE", "SKIP"
        )}
        for p in plans:
            counts[p.verdict] += 1
        return (
            f"grade={grade} coverage={coverage_score}/100 "
            f"start_here={counts['START_HERE']} "
            f"next={counts['NEXT']} parallel={counts['PARALLEL']} "
            f"challenge={counts['CHALLENGE']} skip={counts['SKIP']}"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sauravonboard",
        description="Plan a personalised onboarding curriculum over the "
                    "sauravcode demo set.",
    )
    p.add_argument(
        "--level", choices=_LEVELS, default="novice",
        help="Learner experience level (default: novice)",
    )
    p.add_argument(
        "--goal", default="general",
        help="Learning goal preset (general/web/data/cli/advanced) or "
             "custom string (falls back to general).",
    )
    p.add_argument(
        "--minutes-per-week", type=int, default=120,
        help="Time the learner can commit per week (default: 120).",
    )
    p.add_argument(
        "--risk", choices=_RISK, default="balanced",
        help="Risk appetite for the curriculum (default: balanced).",
    )
    p.add_argument(
        "--root", default=".",
        help="Directory to scan for *_demo.srv files (default: cwd).",
    )
    p.add_argument(
        "--demos", nargs="*",
        help="Explicit demo filenames; if given, --root is ignored.",
    )
    p.add_argument(
        "--format", choices=("text", "md", "json"), default="text",
        help="Output format (default: text).",
    )
    p.add_argument(
        "--output",
        help="Write rendered output to this file instead of stdout.",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    # Windows console UTF-8 shim, matching the rest of the saurav* family.
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass

    args = _build_parser().parse_args(argv)
    demos = args.demos if args.demos is not None else discover_demos(args.root)

    advisor = OnboardingAdvisor(
        level=args.level,
        goal=args.goal,
        minutes_per_week=args.minutes_per_week,
        risk_appetite=args.risk,
    )
    report = advisor.analyze(demos)

    if args.format == "json":
        rendered = report.to_json()
    elif args.format == "md":
        rendered = report.to_markdown()
    else:
        rendered = report.to_text()

    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
