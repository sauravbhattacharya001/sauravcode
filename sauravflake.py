"""
sauravflake - Agentic flaky-test detector for sauravcode.

Analyzes a stream of test-run results (test_id, outcome, duration_ms,
timestamp, optional run_id) and emits per-test verdicts + a portfolio
playbook for handling flakes, new failures, slow-drifters, and stable
suites. 8th saurav* sibling to sauravgate / sauravreview / sauravchange /
sauravonboard / sauravprioritize / sauravsmoke / sauravcoach.

Agentic behavior
----------------
- **Awareness**: per-test pass-rate, intermittency (ABAB toggling),
  consecutive-failure tail, recent-window pass-rate vs older-window
  pass-rate, mean+stdev runtime, slow-drift slope, sample-size guard.
- **Inference**: each test gets a 0-100 ``flake_risk`` score and a
  verdict (STABLE / NEW_FAILURE / FLAKY / CONSISTENT_FAILURE /
  SLOW_DRIFT / UNDER_TESTED), modulated by ``risk_appetite``
  (cautious / balanced / aggressive).
- **Recommendation**: deduped P0-first playbook. Each action carries
  ``owner``, ``blast_radius`` (1-5), ``reversibility`` (low/medium/high).
- **Explainability**: every test carries structured ``reasons`` and
  evidence preserved in text / markdown / JSON renderers.

Public API
----------
- ``FlakeAdvisor(risk_appetite="balanced", now=None,
                 min_runs=5, slow_drift_pct=0.30,
                 recent_window=5, older_window=15)``
- ``FlakeAdvisor.analyze(runs)`` -> ``FlakeReport``
- ``FlakeReport.to_text() / to_markdown() / to_json()``
- ``FlakeReport.format(fmt)`` convenience

CLI
---
::

    python sauravflake.py runs.json --format md --risk balanced
    python sauravflake.py runs.json --format json --output flake.json

Pure stdlib. Never mutates inputs (deepcopy of run records). Deterministic
given a fixed ``now`` callable.
"""

from __future__ import annotations

import argparse
import copy
import json
import statistics
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RISK_APPETITES = ("cautious", "balanced", "aggressive")
_OUTCOME_PASS = {"pass", "passed", "ok", "success", "succeeded", True, 1}
_OUTCOME_FAIL = {"fail", "failed", "error", "errored", "failure", False, 0}
_OUTCOME_SKIP = {"skip", "skipped", "xfail", "xpass", "ignored"}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class FlakeFinding:
    test_id: str
    verdict: str
    flake_risk: int                 # 0-100
    priority: str                   # P0/P1/P2/P3
    pass_rate: float                # 0-1, over non-skipped runs
    recent_pass_rate: float
    older_pass_rate: float
    runs: int
    failures: int
    skipped: int
    intermittency: float            # 0-1 (toggle rate)
    consecutive_failures_tail: int
    mean_duration_ms: Optional[float]
    duration_drift_pct: Optional[float]
    reasons: List[str] = field(default_factory=list)
    last_outcome: Optional[str] = None
    last_seen_iso: Optional[str] = None


@dataclass
class FlakeAction:
    id: str
    priority: str                   # P0/P1/P2/P3
    label: str
    reason: str
    owner: str
    blast_radius: int               # 1-5
    reversibility: str              # low/medium/high
    related_tests: List[str] = field(default_factory=list)


@dataclass
class FlakeReport:
    summary: Dict[str, Any]
    findings: List[FlakeFinding]
    playbook: List[FlakeAction]
    insights: List[str]
    grade: str                      # A/B/C/D/F
    headline: str
    risk_appetite: str
    generated_at: str

    # ---- renderers --------------------------------------------------------

    def format(self, fmt: str = "text") -> str:
        f = (fmt or "text").lower()
        if f in ("text", "txt"):
            return self.to_text()
        if f in ("md", "markdown"):
            return self.to_markdown()
        if f == "json":
            return self.to_json()
        raise ValueError(f"unknown format: {fmt!r}")

    def to_json(self) -> str:
        payload = {
            "summary": self.summary,
            "findings": [asdict(f) for f in self.findings],
            "playbook": [asdict(a) for a in self.playbook],
            "insights": list(self.insights),
            "grade": self.grade,
            "headline": self.headline,
            "risk_appetite": self.risk_appetite,
            "generated_at": self.generated_at,
        }
        return json.dumps(payload, sort_keys=True, indent=2, default=str)

    def to_text(self) -> str:
        lines: List[str] = []
        lines.append(self.headline)
        lines.append("")
        lines.append(f"Grade        : {self.grade}")
        lines.append(f"Risk         : {self.risk_appetite}")
        lines.append(f"Generated at : {self.generated_at}")
        lines.append("")
        lines.append("Summary:")
        for k in (
            "total_tests",
            "total_runs",
            "stable",
            "flaky",
            "new_failure",
            "consistent_failure",
            "slow_drift",
            "under_tested",
            "p0",
            "p1",
            "p2",
            "p3",
        ):
            if k in self.summary:
                lines.append(f"  {k:<22}: {self.summary[k]}")
        lines.append("")
        lines.append("Findings (top 20 by flake_risk):")
        ranked = sorted(
            self.findings,
            key=lambda f: (-f.flake_risk, f.priority, f.test_id),
        )
        for f in ranked[:20]:
            lines.append(
                f"  [{f.priority}] {f.test_id} "
                f"verdict={f.verdict} risk={f.flake_risk} "
                f"pass={f.pass_rate:.2f} runs={f.runs} fails={f.failures}"
            )
            if f.reasons:
                lines.append(f"      reasons: {', '.join(f.reasons)}")
        lines.append("")
        lines.append("Playbook:")
        if not self.playbook:
            lines.append("  (no actions)")
        for a in self.playbook:
            lines.append(
                f"  [{a.priority}] {a.id}: {a.label} "
                f"(owner={a.owner}, blast={a.blast_radius}, rev={a.reversibility})"
            )
            lines.append(f"      reason: {a.reason}")
            if a.related_tests:
                lines.append(
                    "      tests: "
                    + ", ".join(a.related_tests[:5])
                    + (f" (+{len(a.related_tests) - 5} more)" if len(a.related_tests) > 5 else "")
                )
        lines.append("")
        lines.append("Insights:")
        if not self.insights:
            lines.append("  (none)")
        for ins in self.insights:
            lines.append(f"  - {ins}")
        return "\n".join(lines) + "\n"

    def to_markdown(self) -> str:
        lines: List[str] = []
        lines.append(f"# {self.headline}")
        lines.append("")
        lines.append(f"- **Grade**: {self.grade}")
        lines.append(f"- **Risk appetite**: {self.risk_appetite}")
        lines.append(f"- **Generated at**: {self.generated_at}")
        lines.append("")
        lines.append("## Summary")
        lines.append("")
        lines.append("| metric | value |")
        lines.append("|---|---|")
        for k in (
            "total_tests",
            "total_runs",
            "stable",
            "flaky",
            "new_failure",
            "consistent_failure",
            "slow_drift",
            "under_tested",
            "p0",
            "p1",
            "p2",
            "p3",
        ):
            if k in self.summary:
                lines.append(f"| {k} | {self.summary[k]} |")
        lines.append("")
        lines.append("## Findings")
        lines.append("")
        if not self.findings:
            lines.append("_No tests analyzed._")
        else:
            lines.append(
                "| priority | test_id | verdict | risk | pass | runs | fails | reasons |"
            )
            lines.append("|---|---|---|---|---|---|---|---|")
            ranked = sorted(
                self.findings,
                key=lambda f: (-f.flake_risk, f.priority, f.test_id),
            )
            for f in ranked:
                reasons = ", ".join(f.reasons) if f.reasons else "-"
                lines.append(
                    f"| {f.priority} | `{_md_escape(f.test_id)}` | {f.verdict} | "
                    f"{f.flake_risk} | {f.pass_rate:.2f} | {f.runs} | "
                    f"{f.failures} | {_md_escape(reasons)} |"
                )
        lines.append("")
        lines.append("## Playbook")
        lines.append("")
        if not self.playbook:
            lines.append("_No actions._")
        else:
            lines.append("| priority | id | label | owner | blast | reversibility | reason |")
            lines.append("|---|---|---|---|---|---|---|")
            for a in self.playbook:
                lines.append(
                    f"| {a.priority} | `{a.id}` | {_md_escape(a.label)} | "
                    f"{a.owner} | {a.blast_radius} | {a.reversibility} | "
                    f"{_md_escape(a.reason)} |"
                )
        lines.append("")
        lines.append("## Insights")
        lines.append("")
        if not self.insights:
            lines.append("_None._")
        else:
            for ins in self.insights:
                lines.append(f"- {ins}")
        lines.append("")
        return "\n".join(lines)


def _md_escape(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


# ---------------------------------------------------------------------------
# Advisor
# ---------------------------------------------------------------------------

class FlakeAdvisor:
    """Detect flakes and build a remediation playbook from test runs."""

    def __init__(
        self,
        risk_appetite: str = "balanced",
        now: Optional[Callable[[], datetime]] = None,
        min_runs: int = 5,
        slow_drift_pct: float = 0.30,
        recent_window: int = 5,
        older_window: int = 15,
    ):
        if risk_appetite not in _RISK_APPETITES:
            raise ValueError(
                f"risk_appetite must be one of {_RISK_APPETITES}, got {risk_appetite!r}"
            )
        if min_runs < 1:
            raise ValueError("min_runs must be >= 1")
        if recent_window < 1 or older_window < 1:
            raise ValueError("window sizes must be >= 1")
        self.risk_appetite = risk_appetite
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.min_runs = min_runs
        self.slow_drift_pct = slow_drift_pct
        self.recent_window = recent_window
        self.older_window = older_window

    # ----- public ---------------------------------------------------------

    def analyze(self, runs: Iterable[Any]) -> FlakeReport:
        normalized = self._normalize(runs)
        by_test: Dict[str, List[Dict[str, Any]]] = {}
        for r in normalized:
            by_test.setdefault(r["test_id"], []).append(r)

        # Sort each test's runs chronologically (ts asc, then run_id asc).
        for tid, rs in by_test.items():
            rs.sort(key=lambda r: (r["ts_sortkey"], r.get("run_id") or ""))

        findings: List[FlakeFinding] = []
        for tid in sorted(by_test):
            findings.append(self._score_test(tid, by_test[tid]))

        playbook = self._build_playbook(findings)
        summary = self._summarize(findings, normalized)
        insights = self._insights(findings, summary)
        grade = self._grade(findings, summary)
        headline = self._headline(grade, summary)

        return FlakeReport(
            summary=summary,
            findings=findings,
            playbook=playbook,
            insights=insights,
            grade=grade,
            headline=headline,
            risk_appetite=self.risk_appetite,
            generated_at=self._now().isoformat(),
        )

    # ----- normalization --------------------------------------------------

    def _normalize(self, runs: Iterable[Any]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for raw in runs:
            r = copy.deepcopy(raw) if isinstance(raw, dict) else dict(raw.__dict__)
            tid = r.get("test_id") or r.get("name") or r.get("nodeid")
            if not tid:
                continue
            outcome_raw = r.get("outcome", r.get("status"))
            outcome = self._classify_outcome(outcome_raw)
            ts = r.get("timestamp") or r.get("ts") or r.get("at")
            ts_iso, ts_sort = self._ts_pair(ts)
            duration = r.get("duration_ms")
            if duration is None and r.get("duration") is not None:
                # accept seconds as fallback
                try:
                    duration = float(r["duration"]) * 1000.0
                except (TypeError, ValueError):
                    duration = None
            out.append(
                {
                    "test_id": str(tid),
                    "outcome": outcome,
                    "duration_ms": float(duration) if duration is not None else None,
                    "ts_iso": ts_iso,
                    "ts_sortkey": ts_sort,
                    "run_id": r.get("run_id"),
                }
            )
        return out

    def _classify_outcome(self, raw: Any) -> str:
        if isinstance(raw, str):
            key = raw.strip().lower()
        else:
            key = raw
        if key in _OUTCOME_PASS:
            return "pass"
        if key in _OUTCOME_FAIL:
            return "fail"
        if isinstance(key, str) and key in _OUTCOME_SKIP:
            return "skip"
        # Treat unknown as fail to surface noise.
        return "fail"

    def _ts_pair(self, ts: Any) -> tuple:
        if ts is None:
            return (None, 0)
        if isinstance(ts, datetime):
            iso = ts.astimezone(timezone.utc).isoformat() if ts.tzinfo else ts.replace(tzinfo=timezone.utc).isoformat()
            return (iso, ts.timestamp() if ts.tzinfo else ts.replace(tzinfo=timezone.utc).timestamp())
        if isinstance(ts, (int, float)):
            try:
                dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                return (dt.isoformat(), float(ts))
            except (OverflowError, OSError, ValueError):
                return (None, 0)
        if isinstance(ts, str):
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return (dt.isoformat(), dt.timestamp())
            except ValueError:
                return (ts, 0)
        return (None, 0)

    # ----- scoring --------------------------------------------------------

    def _score_test(self, test_id: str, runs: List[Dict[str, Any]]) -> FlakeFinding:
        outcomes = [r["outcome"] for r in runs]
        non_skipped = [o for o in outcomes if o != "skip"]
        runs_count = len(non_skipped)
        failures = sum(1 for o in non_skipped if o == "fail")
        skipped = sum(1 for o in outcomes if o == "skip")
        pass_rate = (runs_count - failures) / runs_count if runs_count else 0.0

        # recent / older windows over non-skipped sequence
        recent = non_skipped[-self.recent_window :] if non_skipped else []
        older = (
            non_skipped[-(self.recent_window + self.older_window) : -self.recent_window]
            if len(non_skipped) > self.recent_window
            else []
        )
        recent_pass = (
            sum(1 for o in recent if o == "pass") / len(recent) if recent else pass_rate
        )
        older_pass = (
            sum(1 for o in older if o == "pass") / len(older) if older else pass_rate
        )

        # consecutive-failure tail
        tail_fails = 0
        for o in reversed(non_skipped):
            if o == "fail":
                tail_fails += 1
            else:
                break

        # toggle / intermittency rate
        toggles = sum(
            1
            for a, b in zip(non_skipped, non_skipped[1:])
            if a != b
        )
        intermittency = toggles / max(1, len(non_skipped) - 1) if len(non_skipped) > 1 else 0.0

        # duration drift (mean of last third vs first third)
        durations = [r["duration_ms"] for r in runs if r["duration_ms"] is not None]
        mean_dur: Optional[float] = None
        drift_pct: Optional[float] = None
        if len(durations) >= 6:
            third = max(2, len(durations) // 3)
            first_mean = statistics.fmean(durations[:third])
            last_mean = statistics.fmean(durations[-third:])
            mean_dur = statistics.fmean(durations)
            if first_mean > 0:
                drift_pct = (last_mean - first_mean) / first_mean
        elif durations:
            mean_dur = statistics.fmean(durations)

        verdict, base_risk, reasons = self._classify(
            runs_count=runs_count,
            failures=failures,
            pass_rate=pass_rate,
            recent_pass=recent_pass,
            older_pass=older_pass,
            tail_fails=tail_fails,
            intermittency=intermittency,
            drift_pct=drift_pct,
        )

        # risk_appetite multiplier
        appetite_mult = {"cautious": 1.15, "balanced": 1.0, "aggressive": 0.85}[
            self.risk_appetite
        ]
        risk = max(0, min(100, int(round(base_risk * appetite_mult))))
        priority = _priority_for(verdict, risk)

        last_outcome = non_skipped[-1] if non_skipped else (outcomes[-1] if outcomes else None)
        last_iso = runs[-1]["ts_iso"] if runs else None

        return FlakeFinding(
            test_id=test_id,
            verdict=verdict,
            flake_risk=risk,
            priority=priority,
            pass_rate=round(pass_rate, 4),
            recent_pass_rate=round(recent_pass, 4),
            older_pass_rate=round(older_pass, 4),
            runs=runs_count,
            failures=failures,
            skipped=skipped,
            intermittency=round(intermittency, 4),
            consecutive_failures_tail=tail_fails,
            mean_duration_ms=round(mean_dur, 2) if mean_dur is not None else None,
            duration_drift_pct=round(drift_pct, 4) if drift_pct is not None else None,
            reasons=reasons,
            last_outcome=last_outcome,
            last_seen_iso=last_iso,
        )

    def _classify(
        self,
        runs_count: int,
        failures: int,
        pass_rate: float,
        recent_pass: float,
        older_pass: float,
        tail_fails: int,
        intermittency: float,
        drift_pct: Optional[float],
    ) -> tuple:
        reasons: List[str] = []

        # UNDER_TESTED guard wins when sample too small to draw a conclusion.
        if runs_count < self.min_runs:
            reasons.append(f"only {runs_count} runs (<{self.min_runs})")
            risk = 30 if failures else 15
            return ("UNDER_TESTED", risk, reasons)

        # CONSISTENT_FAILURE: long tail of fails or pass_rate near 0 in recent window
        if tail_fails >= max(3, runs_count // 2) or recent_pass <= 0.05:
            reasons.append(f"{tail_fails} consecutive failures (tail)")
            if recent_pass <= 0.05:
                reasons.append(f"recent pass rate {recent_pass:.2f} <= 0.05")
            return ("CONSISTENT_FAILURE", 90, reasons)

        # NEW_FAILURE: previously stable, regressed in recent window
        if older_pass >= 0.95 and recent_pass <= 0.6 and tail_fails >= 1:
            reasons.append(
                f"recent pass rate {recent_pass:.2f} dropped from older {older_pass:.2f}"
            )
            return ("NEW_FAILURE", 80, reasons)

        # FLAKY: intermittent toggling or mid-band pass rate
        if intermittency >= 0.30 or 0.20 <= pass_rate <= 0.85:
            if intermittency >= 0.30:
                reasons.append(f"intermittency {intermittency:.2f} >= 0.30")
            if 0.20 <= pass_rate <= 0.85:
                reasons.append(f"pass rate {pass_rate:.2f} in flaky band")
            base = 50 + int(round(min(intermittency, 1.0) * 30))
            base += int(round((1.0 - pass_rate) * 10))
            return ("FLAKY", min(85, base), reasons)

        # SLOW_DRIFT: duration trending upward
        if drift_pct is not None and drift_pct >= self.slow_drift_pct:
            reasons.append(f"duration drift {drift_pct:.0%} >= {self.slow_drift_pct:.0%}")
            return ("SLOW_DRIFT", 45, reasons)

        # STABLE
        if pass_rate < 1.0:
            reasons.append(f"pass rate {pass_rate:.2f}, mostly stable")
        else:
            reasons.append("all runs passed")
        return ("STABLE", 5, reasons)

    # ----- playbook -------------------------------------------------------

    def _build_playbook(self, findings: List[FlakeFinding]) -> List[FlakeAction]:
        actions: List[FlakeAction] = []

        flaky = sorted([f for f in findings if f.verdict == "FLAKY"], key=lambda f: -f.flake_risk)
        new_fail = sorted(
            [f for f in findings if f.verdict == "NEW_FAILURE"], key=lambda f: -f.flake_risk
        )
        consistent = sorted(
            [f for f in findings if f.verdict == "CONSISTENT_FAILURE"],
            key=lambda f: -f.flake_risk,
        )
        slow = [f for f in findings if f.verdict == "SLOW_DRIFT"]
        under = [f for f in findings if f.verdict == "UNDER_TESTED"]

        if consistent:
            actions.append(
                FlakeAction(
                    id="FIX_CONSISTENT_FAILURES",
                    priority="P0",
                    label="Fix or revert consistently failing tests",
                    reason=f"{len(consistent)} tests are red in nearly every recent run",
                    owner="test_owner",
                    blast_radius=4,
                    reversibility="medium",
                    related_tests=[f.test_id for f in consistent],
                )
            )

        if new_fail:
            actions.append(
                FlakeAction(
                    id="INVESTIGATE_NEW_FAILURES",
                    priority="P0",
                    label="Bisect & fix newly regressed tests",
                    reason=f"{len(new_fail)} tests recently regressed from a stable baseline",
                    owner="release_engineer",
                    blast_radius=4,
                    reversibility="medium",
                    related_tests=[f.test_id for f in new_fail],
                )
            )

        if flaky:
            high_flaky = [f for f in flaky if f.flake_risk >= 70]
            if high_flaky:
                actions.append(
                    FlakeAction(
                        id="QUARANTINE_HIGH_FLAKES",
                        priority="P0" if self.risk_appetite == "cautious" else "P1",
                        label="Quarantine high-risk flaky tests",
                        reason=(
                            f"{len(high_flaky)} flakes with risk>=70; quarantining "
                            "prevents wasted CI signal while owners investigate"
                        ),
                        owner="test_owner",
                        blast_radius=2,
                        reversibility="high",
                        related_tests=[f.test_id for f in high_flaky],
                    )
                )
            mid_flaky = [f for f in flaky if f.flake_risk < 70]
            if mid_flaky:
                actions.append(
                    FlakeAction(
                        id="STABILIZE_MID_FLAKES",
                        priority="P1",
                        label="Stabilize medium-risk flaky tests",
                        reason=(
                            f"{len(mid_flaky)} flakes with risk<70; review for "
                            "race conditions, async waits, and shared fixtures"
                        ),
                        owner="test_owner",
                        blast_radius=2,
                        reversibility="high",
                        related_tests=[f.test_id for f in mid_flaky],
                    )
                )

        if slow:
            actions.append(
                FlakeAction(
                    id="OPTIMIZE_SLOW_DRIFT",
                    priority="P2",
                    label="Profile and optimize tests with rising duration",
                    reason=(
                        f"{len(slow)} tests show >= {self.slow_drift_pct:.0%} runtime "
                        "growth; left unchecked these become CI bottlenecks"
                    ),
                    owner="perf_owner",
                    blast_radius=2,
                    reversibility="high",
                    related_tests=[f.test_id for f in slow],
                )
            )

        if under:
            actions.append(
                FlakeAction(
                    id="GATHER_MORE_RUNS",
                    priority="P2",
                    label="Increase sample size for under-tested cases",
                    reason=(
                        f"{len(under)} tests have <{self.min_runs} runs; verdicts are "
                        "low-confidence until more samples accrue"
                    ),
                    owner="ci_owner",
                    blast_radius=1,
                    reversibility="high",
                    related_tests=[f.test_id for f in under],
                )
            )

        # Cautious always adds a scheduled review when grade is poor (computed later);
        # we add it conditionally when there is *any* P0/P1.
        has_p0_p1 = any(a.priority in ("P0", "P1") for a in actions)
        if self.risk_appetite == "cautious" and has_p0_p1:
            actions.append(
                FlakeAction(
                    id="SCHEDULE_FLAKE_AUDIT",
                    priority="P2",
                    label="Schedule a flake audit review",
                    reason="Cautious appetite: book a follow-up review until red/flaky counts return to zero",
                    owner="qa_lead",
                    blast_radius=1,
                    reversibility="high",
                    related_tests=[],
                )
            )

        # Aggressive: trim P2 if any P0 present (focus mode)
        if self.risk_appetite == "aggressive" and any(a.priority == "P0" for a in actions):
            actions = [a for a in actions if a.priority != "P2"]

        if not actions:
            actions.append(
                FlakeAction(
                    id="SUITE_HEALTHY",
                    priority="P3",
                    label="Suite healthy - maintain observability",
                    reason="No flakes, regressions, or runaway durations detected",
                    owner="qa_lead",
                    blast_radius=1,
                    reversibility="high",
                    related_tests=[],
                )
            )

        # Sort P0-first; stable on id
        order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        actions.sort(key=lambda a: (order.get(a.priority, 9), a.id))
        return actions

    # ----- summary / grade -------------------------------------------------

    def _summarize(
        self,
        findings: List[FlakeFinding],
        runs: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        verdict_counts: Dict[str, int] = {}
        priority_counts = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        for f in findings:
            verdict_counts[f.verdict] = verdict_counts.get(f.verdict, 0) + 1
            priority_counts[f.priority] = priority_counts.get(f.priority, 0) + 1
        summary = {
            "total_tests": len(findings),
            "total_runs": len(runs),
            "stable": verdict_counts.get("STABLE", 0),
            "flaky": verdict_counts.get("FLAKY", 0),
            "new_failure": verdict_counts.get("NEW_FAILURE", 0),
            "consistent_failure": verdict_counts.get("CONSISTENT_FAILURE", 0),
            "slow_drift": verdict_counts.get("SLOW_DRIFT", 0),
            "under_tested": verdict_counts.get("UNDER_TESTED", 0),
            "p0": priority_counts["P0"],
            "p1": priority_counts["P1"],
            "p2": priority_counts["P2"],
            "p3": priority_counts["P3"],
        }
        return summary

    def _insights(
        self, findings: List[FlakeFinding], summary: Dict[str, Any]
    ) -> List[str]:
        out: List[str] = []
        total = summary.get("total_tests", 0) or 1
        flaky_pct = summary.get("flaky", 0) / total
        if flaky_pct >= 0.20:
            out.append(f"FLAKE_HOTSPOT: {flaky_pct:.0%} of tests are flaky")
        if summary.get("consistent_failure", 0) >= 3:
            out.append(
                f"RED_BACKLOG: {summary['consistent_failure']} tests are persistently red"
            )
        if summary.get("new_failure", 0) >= 1:
            out.append(
                f"REGRESSION_WAVE: {summary['new_failure']} tests recently regressed"
            )
        if summary.get("slow_drift", 0) >= 3:
            out.append(
                f"PERF_DRIFT: {summary['slow_drift']} tests are getting slower run-over-run"
            )
        if summary.get("under_tested", 0) / total >= 0.30:
            out.append(
                f"LOW_CONFIDENCE: {summary['under_tested']} tests have insufficient sample size"
            )
        if not out and summary.get("total_tests", 0) > 0:
            out.append("HEALTHY_SUITE: no flakes, regressions, or drifts detected")
        if summary.get("total_tests", 0) == 0:
            out.append("EMPTY_INPUT: no test runs supplied")
        return out

    def _grade(self, findings: List[FlakeFinding], summary: Dict[str, Any]) -> str:
        if summary.get("total_tests", 0) == 0:
            return "F"
        total = summary["total_tests"]
        red = summary.get("consistent_failure", 0) + summary.get("new_failure", 0)
        flaky = summary.get("flaky", 0)
        if red >= 3 or red / total >= 0.20:
            return "F"
        if red >= 1 or flaky / total >= 0.30:
            return "D"
        if flaky / total >= 0.15 or summary.get("slow_drift", 0) / total >= 0.20:
            return "C"
        if flaky / total >= 0.05 or summary.get("under_tested", 0) / total >= 0.30:
            return "B"
        return "A"

    def _headline(self, grade: str, summary: Dict[str, Any]) -> str:
        return (
            f"VERDICT: grade={grade} tests={summary.get('total_tests', 0)} "
            f"flaky={summary.get('flaky', 0)} red="
            f"{summary.get('consistent_failure', 0) + summary.get('new_failure', 0)}"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _priority_for(verdict: str, risk: int) -> str:
    if verdict in ("CONSISTENT_FAILURE", "NEW_FAILURE"):
        return "P0"
    if verdict == "FLAKY":
        if risk >= 70:
            return "P1"
        return "P2"
    if verdict == "SLOW_DRIFT":
        return "P2"
    if verdict == "UNDER_TESTED":
        return "P3"
    return "P3"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_runs(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "runs" in data:
        data = data["runs"]
    if not isinstance(data, list):
        raise ValueError("input JSON must be a list of run records or {'runs': [...]} object")
    return data


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sauravflake",
        description="Agentic flaky-test detector for sauravcode (8th saurav* sibling).",
    )
    parser.add_argument(
        "input",
        nargs="?",
        help="Path to JSON file with a list of test-run records "
        "([{test_id, outcome, duration_ms, timestamp, run_id?}, ...]) "
        "or object with a 'runs' key. Omit to read JSON from stdin.",
    )
    parser.add_argument(
        "--format",
        "-f",
        default="text",
        choices=["text", "md", "markdown", "json"],
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--risk",
        default="balanced",
        choices=list(_RISK_APPETITES),
        help="Risk appetite (default: balanced).",
    )
    parser.add_argument(
        "--min-runs",
        type=int,
        default=5,
        help="Minimum runs needed before a test escapes UNDER_TESTED (default: 5).",
    )
    parser.add_argument(
        "--slow-drift-pct",
        type=float,
        default=0.30,
        help="Duration-drift threshold (default: 0.30 = 30%% slower).",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Write output to file instead of stdout.",
    )
    args = parser.parse_args(argv)

    # Windows UTF-8 stdout shim
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    if args.input:
        runs = _load_runs(args.input)
    else:
        raw = sys.stdin.read()
        if not raw.strip():
            print("error: no input provided", file=sys.stderr)
            return 2
        runs = json.loads(raw)
        if isinstance(runs, dict) and "runs" in runs:
            runs = runs["runs"]

    advisor = FlakeAdvisor(
        risk_appetite=args.risk,
        min_runs=args.min_runs,
        slow_drift_pct=args.slow_drift_pct,
    )
    report = advisor.analyze(runs)
    out = report.format(args.format)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out)
    else:
        sys.stdout.write(out)
        if not out.endswith("\n"):
            sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
