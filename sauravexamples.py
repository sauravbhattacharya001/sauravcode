"""
sauravexamples - Agentic quality auditor for sauravcode ``.srv`` demo files.

Where :mod:`sauravsmoke` solves *coverage* ("pick a minimal slate that exercises
the most language features") and :mod:`sauravprioritize` ranks ``.srv`` files
for execution priority, ``sauravexamples`` focuses on the *quality of each
demo as documentation*: is it small enough to read at a glance? Does it have a
short header comment explaining what it shows? Does it print *something* so a
new reader can run it and see a result? Are two demos near-duplicates that
should be merged?

Agentic behavior
----------------
- **Awareness**: scans every ``.srv`` file under ``root`` and extracts shape
  metrics (line count, comment density, print-statement presence, function
  count, near-duplicate signature).
- **Inference**: assigns each demo a 0-100 ``quality_score`` and a structured
  verdict (EXEMPLARY / GOOD / NEEDS_HEADER / NEEDS_OUTPUT / TOO_LONG /
  TOO_SHORT_STUB / NEAR_DUPLICATE_OF / EMPTY).
- **Recommendation**: emits a P0-first deduped playbook (DELETE_EMPTY,
  MERGE_DUPLICATES, ADD_HEADER_COMMENT, ADD_PRINT_OUTPUT, SPLIT_LARGE_DEMO,
  EXPAND_STUB, SCHEDULE_DEMO_REVIEW). risk_appetite tunes thresholds.
- **Explainability**: every finding carries structured reasons and a paste-
  ready suggested action.

Public API
----------
- ``DemoAuditor(root=".")``
- ``DemoAuditor.scan()`` -> ``list[DemoFinding]``
- ``DemoAuditor.report(risk_appetite="balanced")`` -> ``DemoReport``
- ``DemoReport.format("text"|"md"|"json")``

CLI
---
::

    python -m sauravexamples --root . --format md
    python -m sauravexamples --root demos --format json --risk cautious

Pure-stdlib (no third-party deps) so it runs in CI, pre-commit, or constrained
containers without pulling in the rest of the sauravcode runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable

__all__ = [
    "DEFAULT_OPTIONS",
    "DemoAuditor",
    "DemoFinding",
    "DemoMetrics",
    "DemoReport",
    "PlaybookAction",
    "scan_demos",
]


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------


DEFAULT_OPTIONS: dict = {
    # A demo with fewer non-blank, non-comment lines than this is a stub.
    "stub_max_loc": 3,
    # A demo with more LOC than this is "too long to scan quickly".
    "too_long_loc": 120,
    # Minimum desired ratio of comment lines to code lines.
    "min_comment_ratio": 0.05,
    # Two demos with the same normalized signature are flagged as duplicates.
    "dup_signature_chars": 96,
    # Cap on how many findings make it into the slate (rest in `.tail`).
    "top_n": 25,
}

_RISK_APPETITES = ("cautious", "balanced", "aggressive")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class DemoMetrics:
    """Shape metrics extracted from a single ``.srv`` file."""

    path: str
    total_lines: int
    code_lines: int
    comment_lines: int
    blank_lines: int
    has_header_comment: bool
    has_print: bool
    function_count: int
    signature: str  # short hash of normalized text used for duplicate grouping

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class DemoFinding:
    """A per-demo quality finding."""

    path: str
    verdict: str            # see VERDICTS below
    priority: str           # P0 / P1 / P2 / P3
    quality_score: int      # 0..100, higher is better
    reasons: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)  # e.g. duplicate group
    suggested_action: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class PlaybookAction:
    """A cross-demo action recommended by the auditor."""

    id: str
    priority: str        # P0 / P1 / P2 / P3
    label: str
    reason: str
    owner: str
    blast_radius: int    # 1..5
    reversibility: str   # low / medium / high
    related_paths: list[str] = field(default_factory=list)
    suggested_value: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class DemoReport:
    """Portfolio-level report returned by :meth:`DemoAuditor.report`."""

    headline: str
    grade: str                  # A / B / C / D / F
    portfolio_score: int        # 0..100, higher is better
    risk_appetite: str
    findings: list[DemoFinding] = field(default_factory=list)
    playbook: list[PlaybookAction] = field(default_factory=list)
    insights: list[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "headline": self.headline,
            "grade": self.grade,
            "portfolio_score": self.portfolio_score,
            "risk_appetite": self.risk_appetite,
            "summary": self.summary,
            "findings": [f.as_dict() for f in self.findings],
            "playbook": [a.as_dict() for a in self.playbook],
            "insights": list(self.insights),
        }

    def format(self, fmt: str = "text") -> str:
        fmt = (fmt or "text").lower()
        if fmt == "json":
            return json.dumps(self.as_dict(), sort_keys=True, indent=2, default=str)
        if fmt in ("md", "markdown"):
            return _render_markdown(self)
        return _render_text(self)


# ---------------------------------------------------------------------------
# Verdict ladder (highest priority match wins)
# ---------------------------------------------------------------------------


VERDICTS = (
    "EMPTY",
    "NEAR_DUPLICATE_OF",
    "TOO_SHORT_STUB",
    "TOO_LONG",
    "NEEDS_HEADER",
    "NEEDS_OUTPUT",
    "GOOD",
    "EXEMPLARY",
)

_VERDICT_BASE_PRIORITY = {
    "EMPTY": "P0",
    "NEAR_DUPLICATE_OF": "P1",
    "TOO_SHORT_STUB": "P2",
    "TOO_LONG": "P2",
    "NEEDS_HEADER": "P2",
    "NEEDS_OUTPUT": "P2",
    "GOOD": "P3",
    "EXEMPLARY": "P3",
}

# Quality score deductions per verdict (subtracted from 100).
_VERDICT_PENALTY = {
    "EMPTY": 95,
    "NEAR_DUPLICATE_OF": 55,
    "TOO_SHORT_STUB": 45,
    "TOO_LONG": 35,
    "NEEDS_HEADER": 25,
    "NEEDS_OUTPUT": 20,
    "GOOD": 5,
    "EXEMPLARY": 0,
}


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


_COMMENT_RE = re.compile(r"^\s*#")
_FUNCTION_RE = re.compile(r"^\s*function\s+\w+")
_PRINT_RE = re.compile(r"^\s*print\b")
_TOKEN_RE = re.compile(r"[A-Za-z_]\w*")


def scan_demos(root: Path | str) -> list[DemoMetrics]:
    """Return :class:`DemoMetrics` for every ``.srv`` file under *root*.

    Hidden directories and ``__pycache__`` are skipped. ``test_*.srv`` files
    are included (they are demos too — they show how features behave).
    """

    root_path = Path(root)
    metrics: list[DemoMetrics] = []
    for path in sorted(root_path.rglob("*.srv")):
        # Skip hidden / cache dirs.
        if any(part.startswith(".") or part == "__pycache__" for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        metrics.append(_extract_metrics(path, text, root_path))
    return metrics


def _extract_metrics(path: Path, text: str, root: Path) -> DemoMetrics:
    lines = text.splitlines()
    total = len(lines)
    code_lines = 0
    comment_lines = 0
    blank_lines = 0
    function_count = 0
    has_print = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            blank_lines += 1
        elif _COMMENT_RE.match(line):
            comment_lines += 1
        else:
            code_lines += 1
            if _FUNCTION_RE.match(line):
                function_count += 1
            if _PRINT_RE.match(line):
                has_print = True

    has_header_comment = False
    for line in lines[:5]:
        if _COMMENT_RE.match(line):
            has_header_comment = True
            break

    signature = _signature(lines)
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        rel = path.as_posix()

    return DemoMetrics(
        path=rel,
        total_lines=total,
        code_lines=code_lines,
        comment_lines=comment_lines,
        blank_lines=blank_lines,
        has_header_comment=has_header_comment,
        has_print=has_print,
        function_count=function_count,
        signature=signature,
    )


def _signature(lines: Iterable[str]) -> str:
    """Normalized identifier-only fingerprint, used for duplicate grouping."""
    tokens: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or _COMMENT_RE.match(line):
            continue
        for tok in _TOKEN_RE.findall(stripped):
            tokens.append(tok)
    if not tokens:
        return ""
    joined = " ".join(tokens[: DEFAULT_OPTIONS["dup_signature_chars"]])
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Auditor
# ---------------------------------------------------------------------------


class DemoAuditor:
    """Agentic auditor over a directory of ``.srv`` demo files."""

    def __init__(
        self,
        root: Path | str = ".",
        options: dict | None = None,
    ) -> None:
        self.root = Path(root)
        merged: dict = dict(DEFAULT_OPTIONS)
        if options:
            merged.update(options)
        self.options = merged

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan(self) -> list[DemoMetrics]:
        return scan_demos(self.root)

    def report(self, risk_appetite: str = "balanced") -> DemoReport:
        appetite = risk_appetite if risk_appetite in _RISK_APPETITES else "balanced"
        metrics = self.scan()
        findings = self._classify(metrics, appetite)
        playbook = self._build_playbook(findings, appetite)
        insights = self._build_insights(metrics, findings)
        summary, grade, score, headline = self._build_summary(metrics, findings, appetite)

        return DemoReport(
            headline=headline,
            grade=grade,
            portfolio_score=score,
            risk_appetite=appetite,
            findings=findings,
            playbook=playbook,
            insights=insights,
            summary=summary,
        )

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _classify(self, metrics: list[DemoMetrics], appetite: str) -> list[DemoFinding]:
        opts = self.options
        stub_max = opts["stub_max_loc"]
        too_long = opts["too_long_loc"]
        min_comment_ratio = opts["min_comment_ratio"]

        # Appetite knobs: cautious tightens thresholds, aggressive loosens.
        if appetite == "cautious":
            too_long = max(60, int(too_long * 0.75))
            stub_max = stub_max + 1
            min_comment_ratio = min_comment_ratio + 0.02
        elif appetite == "aggressive":
            too_long = int(too_long * 1.5)
            stub_max = max(1, stub_max - 1)
            min_comment_ratio = max(0.0, min_comment_ratio - 0.02)

        # Group by duplicate signature.
        sig_to_paths: dict[str, list[str]] = {}
        for m in metrics:
            if not m.signature:
                continue
            sig_to_paths.setdefault(m.signature, []).append(m.path)

        findings: list[DemoFinding] = []
        for m in metrics:
            verdict, reasons, related, action = self._verdict_for(
                m,
                sig_to_paths.get(m.signature, []),
                stub_max=stub_max,
                too_long=too_long,
                min_comment_ratio=min_comment_ratio,
            )
            score = max(0, 100 - _VERDICT_PENALTY[verdict])
            priority = _VERDICT_BASE_PRIORITY[verdict]
            # Cautious bumps GOOD demos with no print to NEEDS_OUTPUT severity.
            findings.append(
                DemoFinding(
                    path=m.path,
                    verdict=verdict,
                    priority=priority,
                    quality_score=score,
                    reasons=reasons,
                    related=related,
                    suggested_action=action,
                )
            )

        # Stable order: priority asc (P0 first), score asc (worst first), path asc.
        findings.sort(
            key=lambda f: (_priority_rank(f.priority), f.quality_score, f.path)
        )
        return findings

    def _verdict_for(
        self,
        m: DemoMetrics,
        siblings: list[str],
        *,
        stub_max: int,
        too_long: int,
        min_comment_ratio: float,
    ) -> tuple[str, list[str], list[str], str]:
        reasons: list[str] = []
        related: list[str] = []

        # EMPTY beats everything.
        if m.code_lines == 0:
            return (
                "EMPTY",
                ["NO_CODE_LINES"],
                [],
                "Delete this demo or replace it with a meaningful example.",
            )

        # Near-duplicate (same normalized signature as >=1 other demo).
        peer_paths = [p for p in siblings if p != m.path]
        if peer_paths:
            related = peer_paths
            reasons.append(f"SAME_SIGNATURE_AS:{','.join(peer_paths[:3])}")
            return (
                "NEAR_DUPLICATE_OF",
                reasons,
                related,
                "Merge with sibling(s) or differentiate this demo with a unique scenario.",
            )

        # Too short stub.
        if m.code_lines <= stub_max:
            reasons.append(f"ONLY_{m.code_lines}_CODE_LINES")
            if not m.has_print:
                reasons.append("NO_PRINT_OUTPUT")
            return (
                "TOO_SHORT_STUB",
                reasons,
                [],
                "Expand into a runnable scenario that prints a result a reader can verify.",
            )

        # Too long.
        if m.code_lines > too_long:
            reasons.append(f"{m.code_lines}_CODE_LINES_EXCEEDS_{too_long}")
            return (
                "TOO_LONG",
                reasons,
                [],
                "Split this demo into two or three focused files (one feature per demo).",
            )

        # Missing header comment.
        if not m.has_header_comment:
            reasons.append("NO_HEADER_COMMENT_IN_FIRST_5_LINES")
            return (
                "NEEDS_HEADER",
                reasons,
                [],
                "Add a leading `# What this demo shows: ...` comment so readers know the point.",
            )

        # Missing print output.
        if not m.has_print:
            reasons.append("NO_PRINT_STATEMENT")
            return (
                "NEEDS_OUTPUT",
                reasons,
                [],
                "Add a `print` call so running this file produces visible output.",
            )

        # Otherwise GOOD or EXEMPLARY.
        comment_ratio = m.comment_lines / max(1, m.code_lines)
        if (
            comment_ratio >= min_comment_ratio
            and m.code_lines >= max(5, stub_max + 2)
            and m.has_print
            and m.has_header_comment
        ):
            return (
                "EXEMPLARY",
                ["WELL_COMMENTED", "HAS_OUTPUT", "BALANCED_LENGTH"],
                [],
                "Keep as-is. Consider linking from STDLIB.md or README as a canonical example.",
            )
        return (
            "GOOD",
            ["MEETS_BASELINE"],
            [],
            "No action required.",
        )

    # ------------------------------------------------------------------
    # Playbook
    # ------------------------------------------------------------------

    def _build_playbook(
        self, findings: list[DemoFinding], appetite: str
    ) -> list[PlaybookAction]:
        by_verdict: dict[str, list[DemoFinding]] = {}
        for f in findings:
            by_verdict.setdefault(f.verdict, []).append(f)

        actions: list[PlaybookAction] = []

        empties = by_verdict.get("EMPTY", [])
        if empties:
            actions.append(
                PlaybookAction(
                    id="DELETE_EMPTY_DEMOS",
                    priority="P0",
                    label=f"Delete or rewrite {len(empties)} empty `.srv` file(s)",
                    reason="Empty demo files confuse new readers and inflate the demo count.",
                    owner="maintainer",
                    blast_radius=2,
                    reversibility="high",
                    related_paths=sorted(f.path for f in empties),
                )
            )

        duplicates = by_verdict.get("NEAR_DUPLICATE_OF", [])
        if duplicates:
            groups: dict[str, list[str]] = {}
            for f in duplicates:
                key = ",".join(sorted([f.path] + list(f.related)))
                groups.setdefault(key, sorted({f.path, *f.related}))
            actions.append(
                PlaybookAction(
                    id="MERGE_DUPLICATE_DEMOS",
                    priority="P1",
                    label=f"Merge {len(groups)} duplicate demo group(s)",
                    reason="Near-duplicate demos add noise without teaching anything new.",
                    owner="docs",
                    blast_radius=2,
                    reversibility="high",
                    related_paths=sorted({p for g in groups.values() for p in g}),
                )
            )

        too_long = by_verdict.get("TOO_LONG", [])
        if too_long:
            actions.append(
                PlaybookAction(
                    id="SPLIT_LARGE_DEMOS",
                    priority="P2",
                    label=f"Split {len(too_long)} oversized demo(s)",
                    reason="Demos that exceed the length budget are hard to read at a glance.",
                    owner="docs",
                    blast_radius=2,
                    reversibility="high",
                    related_paths=sorted(f.path for f in too_long),
                )
            )

        needs_header = by_verdict.get("NEEDS_HEADER", [])
        if needs_header:
            actions.append(
                PlaybookAction(
                    id="ADD_HEADER_COMMENTS",
                    priority="P2",
                    label=f"Add header comments to {len(needs_header)} demo(s)",
                    reason="A one-line `# What this demo shows: ...` is the cheapest documentation.",
                    owner="docs",
                    blast_radius=1,
                    reversibility="high",
                    related_paths=sorted(f.path for f in needs_header),
                )
            )

        needs_output = by_verdict.get("NEEDS_OUTPUT", [])
        if needs_output:
            actions.append(
                PlaybookAction(
                    id="ADD_PRINT_OUTPUT",
                    priority="P2",
                    label=f"Add a `print` call to {len(needs_output)} silent demo(s)",
                    reason="Demos with no output give readers no signal that they ran correctly.",
                    owner="docs",
                    blast_radius=1,
                    reversibility="high",
                    related_paths=sorted(f.path for f in needs_output),
                )
            )

        stubs = by_verdict.get("TOO_SHORT_STUB", [])
        if stubs:
            actions.append(
                PlaybookAction(
                    id="EXPAND_STUB_DEMOS",
                    priority="P2",
                    label=f"Expand {len(stubs)} stub demo(s) into runnable scenarios",
                    reason="Two-line demos do not teach a feature — they only mention it.",
                    owner="docs",
                    blast_radius=2,
                    reversibility="high",
                    related_paths=sorted(f.path for f in stubs),
                )
            )

        # Cautious + middling grade -> schedule a review.
        if appetite == "cautious" and any(
            f.priority in ("P0", "P1", "P2") for f in findings
        ):
            actions.append(
                PlaybookAction(
                    id="SCHEDULE_DEMO_REVIEW",
                    priority="P2",
                    label="Schedule a `.srv` demo-quality review next sprint",
                    reason="Cautious risk appetite: queue a documentation pass.",
                    owner="docs",
                    blast_radius=1,
                    reversibility="high",
                )
            )

        # Healthy fallback.
        if not actions:
            actions.append(
                PlaybookAction(
                    id="HEALTHY_DEMO_FLEET",
                    priority="P3",
                    label="Demo fleet is healthy — no action required.",
                    reason="No demos triggered a quality finding.",
                    owner="maintainer",
                    blast_radius=1,
                    reversibility="high",
                )
            )

        # Aggressive: trim the P3 fallback when any real action is present.
        if appetite == "aggressive" and len(actions) > 1:
            actions = [a for a in actions if a.priority != "P3"]

        # P0-first, stable by id.
        actions.sort(key=lambda a: (_priority_rank(a.priority), a.id))
        return actions

    # ------------------------------------------------------------------
    # Insights & summary
    # ------------------------------------------------------------------

    def _build_insights(
        self,
        metrics: list[DemoMetrics],
        findings: list[DemoFinding],
    ) -> list[str]:
        insights: list[str] = []
        if not metrics:
            return ["NO_DEMOS_FOUND"]

        verdict_counts: dict[str, int] = {}
        for f in findings:
            verdict_counts[f.verdict] = verdict_counts.get(f.verdict, 0) + 1

        total = len(metrics)
        if verdict_counts.get("EMPTY", 0) >= 1:
            insights.append("EMPTY_DEMO_FILES_PRESENT")
        if verdict_counts.get("NEAR_DUPLICATE_OF", 0) >= 2:
            insights.append("NEAR_DUPLICATE_CLUSTER")
        if verdict_counts.get("TOO_LONG", 0) >= 2:
            insights.append("OVERSIZED_DEMOS_PATTERN")
        if verdict_counts.get("NEEDS_HEADER", 0) >= max(3, total // 5):
            insights.append("WIDESPREAD_MISSING_HEADERS")
        if verdict_counts.get("NEEDS_OUTPUT", 0) >= max(3, total // 5):
            insights.append("WIDESPREAD_SILENT_DEMOS")
        if verdict_counts.get("EXEMPLARY", 0) >= max(3, total // 4):
            insights.append("STRONG_EXEMPLAR_BENCH")
        avg_loc = sum(m.code_lines for m in metrics) / total
        if avg_loc > self.options["too_long_loc"] * 0.7:
            insights.append("FLEET_RUNNING_LONG")
        if not insights:
            insights.append("DEMOS_LOOK_HEALTHY")
        return insights

    def _build_summary(
        self,
        metrics: list[DemoMetrics],
        findings: list[DemoFinding],
        appetite: str,
    ) -> tuple[dict, str, int, str]:
        total = len(metrics)
        if total == 0:
            summary = {
                "total_demos": 0,
                "verdict_counts": {},
                "mean_quality": 0,
            }
            return summary, "F", 0, "VERDICT: grade=F N=0 mean_quality=0 (no demos found)"

        verdict_counts: dict[str, int] = {v: 0 for v in VERDICTS}
        for f in findings:
            verdict_counts[f.verdict] = verdict_counts.get(f.verdict, 0) + 1
        mean_quality = round(sum(f.quality_score for f in findings) / total)

        # Appetite shift +/-5 on the portfolio score.
        if appetite == "cautious":
            mean_quality = max(0, mean_quality - 5)
        elif appetite == "aggressive":
            mean_quality = min(100, mean_quality + 5)

        # Grade ladder.
        p0 = sum(1 for f in findings if f.priority == "P0")
        if mean_quality >= 85 and p0 == 0:
            grade = "A"
        elif mean_quality >= 70 and p0 == 0:
            grade = "B"
        elif mean_quality >= 55:
            grade = "C"
        elif mean_quality >= 40:
            grade = "D"
        else:
            grade = "F"
        if p0 >= max(3, total // 4):
            grade = "F"

        summary = {
            "total_demos": total,
            "verdict_counts": verdict_counts,
            "mean_quality": mean_quality,
            "p0_count": p0,
            "p1_count": sum(1 for f in findings if f.priority == "P1"),
            "p2_count": sum(1 for f in findings if f.priority == "P2"),
            "p3_count": sum(1 for f in findings if f.priority == "P3"),
            "mean_code_lines": round(sum(m.code_lines for m in metrics) / total, 1),
        }
        headline = (
            f"VERDICT: grade={grade} N={total} "
            f"P0={summary['p0_count']} P1={summary['p1_count']} "
            f"mean_quality={mean_quality}"
        )
        return summary, grade, mean_quality, headline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def _priority_rank(p: str) -> int:
    return _PRIORITY_RANK.get(p, 9)


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def _render_text(report: DemoReport) -> str:
    lines: list[str] = [report.headline, ""]
    s = report.summary
    if s:
        vc = s.get("verdict_counts", {})
        lines.append(
            f"Summary: total={s.get('total_demos', 0)} "
            f"P0={s.get('p0_count', 0)} P1={s.get('p1_count', 0)} "
            f"P2={s.get('p2_count', 0)} P3={s.get('p3_count', 0)} "
            f"mean_quality={s.get('mean_quality', 0)} "
            f"mean_LOC={s.get('mean_code_lines', 0)}"
        )
        if vc:
            parts = [f"{k}={v}" for k, v in vc.items() if v]
            if parts:
                lines.append("Verdicts: " + " ".join(parts))
        lines.append("")
    if report.findings:
        lines.append("Findings (worst first):")
        for f in report.findings[:25]:
            lines.append(
                f"  [{f.priority}] {f.path} -- {f.verdict} (score={f.quality_score})"
            )
            if f.reasons:
                lines.append("    reasons: " + ", ".join(f.reasons))
            if f.suggested_action:
                lines.append("    action:  " + f.suggested_action)
    if report.playbook:
        lines.append("")
        lines.append("Playbook:")
        for a in report.playbook:
            lines.append(f"  [{a.priority}] {a.id}: {a.label}")
            if a.reason:
                lines.append("    reason: " + a.reason)
    if report.insights:
        lines.append("")
        lines.append("Insights: " + ", ".join(report.insights))
    return "\n".join(lines).rstrip() + "\n"


def _render_markdown(report: DemoReport) -> str:
    s = report.summary
    out: list[str] = [f"# Demo Quality Report", "", report.headline, ""]
    out.append("## Summary")
    out.append("")
    out.append("| metric | value |")
    out.append("| --- | --- |")
    out.append(f"| grade | {report.grade} |")
    out.append(f"| portfolio_score | {report.portfolio_score} |")
    out.append(f"| risk_appetite | {report.risk_appetite} |")
    out.append(f"| total_demos | {s.get('total_demos', 0)} |")
    out.append(f"| mean_code_lines | {s.get('mean_code_lines', 0)} |")
    out.append(f"| P0 | {s.get('p0_count', 0)} |")
    out.append(f"| P1 | {s.get('p1_count', 0)} |")
    out.append(f"| P2 | {s.get('p2_count', 0)} |")
    out.append(f"| P3 | {s.get('p3_count', 0)} |")
    out.append("")

    out.append("## Findings")
    out.append("")
    if report.findings:
        out.append("| priority | path | verdict | score | reasons |")
        out.append("| --- | --- | --- | --- | --- |")
        for f in report.findings[:50]:
            reasons = "; ".join(f.reasons) if f.reasons else ""
            out.append(
                f"| {f.priority} | `{f.path}` | {f.verdict} | {f.quality_score} | {reasons} |"
            )
    else:
        out.append("_No findings._")
    out.append("")

    out.append("## Playbook")
    out.append("")
    if report.playbook:
        out.append("| priority | id | label | owner |")
        out.append("| --- | --- | --- | --- |")
        for a in report.playbook:
            out.append(f"| {a.priority} | {a.id} | {a.label} | {a.owner} |")
    else:
        out.append("_No actions._")
    out.append("")

    out.append("## Insights")
    out.append("")
    if report.insights:
        for ins in report.insights:
            out.append(f"- {ins}")
    else:
        out.append("_No insights._")
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sauravexamples",
        description="Agentic quality auditor for sauravcode .srv demo files.",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Directory to scan for .srv files (default: current dir).",
    )
    parser.add_argument(
        "--format",
        choices=("text", "md", "markdown", "json"),
        default="text",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--risk",
        choices=_RISK_APPETITES,
        default="balanced",
        help="Risk appetite knob: cautious | balanced | aggressive.",
    )
    parser.add_argument(
        "--output",
        help="Write report to this file instead of stdout.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    # Best-effort UTF-8 stdout shim for Windows consoles.
    try:
        if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    auditor = DemoAuditor(root=args.root)
    report = auditor.report(risk_appetite=args.risk)
    rendered = report.format(args.format)
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered if rendered.endswith("\n") else rendered + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
