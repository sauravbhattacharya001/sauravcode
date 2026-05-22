#!/usr/bin/env python3
"""sauravcohort - Agentic coverage auditor for the saurav* module family.

Scans the repository for ``saurav*.py`` modules and cross-references each one
against the four artifacts that *should* travel alongside an advisor:

  1. a companion ``*_demo.srv`` in the demos catalogue
  2. a ``test_<module>.py`` in ``tests/`` (or the repo root)
  3. a CLI entrypoint (an ``argparse.ArgumentParser`` and an
     ``if __name__ == "__main__":`` block)
  4. at least one mention in ``README.md`` / ``STDLIB.md`` / ``mkdocs.yml``

It then produces a per-module verdict, a portfolio grade, and a prioritised
playbook of what to add next so the ecosystem stays consistent.

Sibling to ``sauravchange`` / ``sauravreview`` / ``sauravgate`` /
``sauravprioritize`` / ``sauravsmoke`` / ``sauravcoach`` / ``sauravonboard``.

Public API
----------
- ``CohortAdvisor(root=".", risk_appetite="balanced", now_fn=None,
                  module_globs=("saurav*.py",))``
- ``CohortAdvisor.scan()`` -> ``CohortReport``
- ``CohortReport.to_text() / .to_markdown() / .to_json()``

CLI
---
::

    python sauravcohort.py --root . --format md
    python sauravcohort.py --risk aggressive --format json --output cohort.json
    python sauravcohort.py --only sauravchange,sauravgate --format text

Pure stdlib. No mutation of any repo state. Deterministic given a fixed
``now_fn``; JSON output is byte-stable (``sort_keys=True, indent=2,
default=str``).
"""

from __future__ import annotations

import argparse
import fnmatch
import io
import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple


__all__ = [
    "CohortAdvisor",
    "CohortReport",
    "ModuleCoverage",
    "CohortAction",
]


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

_RISK_APPETITES = ("cautious", "balanced", "aggressive")

# Per-artifact weight toward the 0..100 health_score.
_WEIGHTS = {
    "demo": 25,
    "tests": 30,
    "cli": 20,
    "docs": 15,
    "docstring": 10,
}
assert sum(_WEIGHTS.values()) == 100

# Min docstring length (chars) to be counted as "documented in source".
_MIN_DOCSTRING_CHARS = 80

# Verdicts (ordered worst -> best for stable presentation).
_VERDICT_ORDER = (
    "ORPHAN",
    "HIDDEN",
    "UNTESTED",
    "UNDER_DOCUMENTED",
    "PARTIAL",
    "HEALTHY",
    "COMPLETE",
)

# Doc files that count toward "mentioned in docs".
_DOC_FILES = ("README.md", "STDLIB.md", "mkdocs.yml", "CHANGELOG.md")

# Reasons codes (structured).
_R_NO_DEMO = "no_demo"
_R_NO_TESTS = "no_tests"
_R_NO_CLI = "no_cli"
_R_NOT_IN_DOCS = "not_in_docs"
_R_THIN_DOCSTRING = "thin_docstring"
_R_HAS_DEMO = "has_demo"
_R_HAS_TESTS = "has_tests"
_R_HAS_CLI = "has_cli"
_R_IN_DOCS = "in_docs"
_R_GOOD_DOCSTRING = "good_docstring"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ModuleCoverage:
    name: str                # e.g. "sauravchange"
    path: str                # repo-relative module path
    has_demo: bool
    demo_path: Optional[str]
    has_tests: bool
    tests_path: Optional[str]
    has_cli: bool
    has_argparse: bool
    has_main_block: bool
    has_docstring: bool
    docstring_chars: int
    doc_mentions: List[str]  # list of doc files mentioning this module
    line_count: int
    health_score: int        # 0..100
    verdict: str
    priority: str            # P0..P3
    reasons: List[str] = field(default_factory=list)


@dataclass
class CohortAction:
    id: str
    label: str
    priority: str
    reason: str
    owner: str
    blast_radius: int        # 1..5
    reversibility: str       # low/medium/high
    related_modules: List[str] = field(default_factory=list)


@dataclass
class CohortReport:
    modules: List[ModuleCoverage]
    playbook: List[CohortAction]
    insights: List[str]
    headline: str
    grade: str               # A..F
    portfolio_score: int     # 0..100
    portfolio_verdict: str   # HEALTHY/PARTIAL/UNDER_DEVELOPED/AT_RISK/UNHEALTHY
    summary: Dict[str, int]
    risk_appetite: str
    root: str
    generated_at: str

    # ---- renderers ---------------------------------------------------------

    def to_text(self) -> str:
        out: List[str] = []
        out.append(self.headline)
        out.append(
            f"Grade: {self.grade}   Portfolio: {self.portfolio_score}/100   "
            f"Verdict: {self.portfolio_verdict}   Risk: {self.risk_appetite}"
        )
        s = self.summary
        out.append(
            f"Modules: {s.get('total', 0)} "
            f"(complete {s.get('complete', 0)}, healthy {s.get('healthy', 0)}, "
            f"partial {s.get('partial', 0)}, under-documented {s.get('under_documented', 0)}, "
            f"untested {s.get('untested', 0)}, hidden {s.get('hidden', 0)}, "
            f"orphan {s.get('orphan', 0)})"
        )
        out.append("")
        if not self.modules:
            out.append("(no saurav* modules found)")
        else:
            out.append("## Modules")
            for m in self.modules:
                flags = "".join([
                    "D" if m.has_demo else "-",
                    "T" if m.has_tests else "-",
                    "C" if m.has_cli else "-",
                    "K" if m.doc_mentions else "-",
                    "S" if m.has_docstring and m.docstring_chars >= _MIN_DOCSTRING_CHARS else "-",
                ])
                out.append(
                    f"  [{m.priority}] {m.verdict:<16} {m.name:<24} "
                    f"score={m.health_score:>3}  flags={flags}"
                )
            out.append("")
        if self.playbook:
            out.append("## Playbook")
            for a in self.playbook:
                out.append(
                    f"  [{a.priority}] {a.label} - {a.reason} "
                    f"(owner={a.owner}, blast={a.blast_radius}, "
                    f"reversibility={a.reversibility})"
                )
            out.append("")
        if self.insights:
            out.append("## Insights")
            for ins in self.insights:
                out.append(f"  - {ins}")
        return "\n".join(out).rstrip() + "\n"

    def to_markdown(self) -> str:
        out: List[str] = []
        out.append("# Module Cohort Coverage")
        out.append("")
        out.append(f"**{self.headline}**")
        out.append("")
        out.append(
            f"- Grade: **{self.grade}** | Portfolio: **{self.portfolio_score}/100** | "
            f"Verdict: **{self.portfolio_verdict}** | Risk appetite: `{self.risk_appetite}`"
        )
        s = self.summary
        out.append(
            f"- Modules: {s.get('total', 0)} "
            f"(complete {s.get('complete', 0)}, healthy {s.get('healthy', 0)}, "
            f"partial {s.get('partial', 0)}, under-documented {s.get('under_documented', 0)}, "
            f"untested {s.get('untested', 0)}, hidden {s.get('hidden', 0)}, "
            f"orphan {s.get('orphan', 0)})"
        )
        out.append("")
        if self.modules:
            out.append("## Modules")
            out.append("")
            out.append("| Pri | Verdict | Module | Score | Demo | Tests | CLI | Docs | Docstring |")
            out.append("|-----|---------|--------|------:|:----:|:-----:|:---:|:----:|:---------:|")
            for m in self.modules:
                out.append(
                    "| {pri} | {verdict} | `{name}` | {score} | {demo} | {tests} | {cli} | {docs} | {ds} |".format(
                        pri=m.priority,
                        verdict=m.verdict,
                        name=m.name,
                        score=m.health_score,
                        demo="Y" if m.has_demo else ".",
                        tests="Y" if m.has_tests else ".",
                        cli="Y" if m.has_cli else ".",
                        docs="Y" if m.doc_mentions else ".",
                        ds="Y" if (m.has_docstring and m.docstring_chars >= _MIN_DOCSTRING_CHARS) else ".",
                    )
                )
            out.append("")
        if self.playbook:
            out.append("## Playbook")
            out.append("")
            out.append("| Pri | Action | Owner | Blast | Reversibility | Reason |")
            out.append("|-----|--------|-------|------:|:-------------:|--------|")
            for a in self.playbook:
                out.append(
                    "| {pri} | {lab} | {own} | {b} | {rev} | {why} |".format(
                        pri=a.priority,
                        lab=a.label,
                        own=a.owner,
                        b=a.blast_radius,
                        rev=a.reversibility,
                        why=a.reason.replace("|", "\\|"),
                    )
                )
            out.append("")
        if self.insights:
            out.append("## Insights")
            out.append("")
            for ins in self.insights:
                out.append(f"- {ins}")
            out.append("")
        return "\n".join(out).rstrip() + "\n"

    def to_json(self) -> str:
        payload = {
            "headline": self.headline,
            "grade": self.grade,
            "portfolio_score": self.portfolio_score,
            "portfolio_verdict": self.portfolio_verdict,
            "summary": self.summary,
            "risk_appetite": self.risk_appetite,
            "root": self.root,
            "generated_at": self.generated_at,
            "modules": [asdict(m) for m in self.modules],
            "playbook": [asdict(a) for a in self.playbook],
            "insights": list(self.insights),
        }
        return json.dumps(payload, sort_keys=True, indent=2, default=str)


# ---------------------------------------------------------------------------
# Providers (injectable for tests)
# ---------------------------------------------------------------------------


def _default_walker(root: Path, globs: Sequence[str]) -> List[Path]:
    out: List[Path] = []
    for g in globs:
        out.extend(sorted(root.glob(g)))
    # Stable order, de-dupe.
    seen = set()
    uniq: List[Path] = []
    for p in out:
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return uniq


# ---------------------------------------------------------------------------
# Source-introspection helpers
# ---------------------------------------------------------------------------

_DOCSTRING_RE = re.compile(r'^\s*("""|\'\'\')(.*?)(\1)', re.DOTALL)
_ARGPARSE_RE = re.compile(r"\bargparse\.ArgumentParser\b")
_MAIN_BLOCK_RE = re.compile(r'^if\s+__name__\s*==\s*[\'\"]__main__[\'\"]\s*:', re.MULTILINE)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _extract_module_docstring(source: str) -> Tuple[bool, int]:
    """Return (has_docstring, char_count). Skips a shebang and ``from __future__``."""
    # Strip leading shebang/blank lines/comments and skip ``from __future__`` imports
    # to find the first string literal at top level.
    lines = source.splitlines()
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not s or s.startswith("#") or s.startswith("from __future__"):
            i += 1
            continue
        break
    cleaned = "\n".join(lines[i:])
    m = _DOCSTRING_RE.match(cleaned)
    if not m:
        return False, 0
    return True, len(m.group(2).strip())


def _has_cli(source: str) -> Tuple[bool, bool, bool]:
    has_argparse = bool(_ARGPARSE_RE.search(source))
    has_main = bool(_MAIN_BLOCK_RE.search(source))
    return (has_argparse and has_main), has_argparse, has_main


# ---------------------------------------------------------------------------
# Advisor
# ---------------------------------------------------------------------------


class CohortAdvisor:
    """Audit the saurav* module family for ecosystem-coverage gaps."""

    def __init__(
        self,
        root: str | os.PathLike = ".",
        risk_appetite: str = "balanced",
        module_globs: Sequence[str] = ("saurav*.py",),
        now_fn: Optional[Callable[[], datetime]] = None,
        walker: Optional[Callable[[Path, Sequence[str]], List[Path]]] = None,
        file_reader: Optional[Callable[[Path], str]] = None,
    ) -> None:
        if risk_appetite not in _RISK_APPETITES:
            raise ValueError(
                f"risk_appetite must be one of {_RISK_APPETITES}, got {risk_appetite!r}"
            )
        self.root = Path(root)
        self.risk_appetite = risk_appetite
        self.module_globs = tuple(module_globs)
        self._now = now_fn or (lambda: datetime.now(timezone.utc))
        self._walker = walker or _default_walker
        self._read = file_reader or _read_text

    # -- public ------------------------------------------------------------

    def scan(self) -> CohortReport:
        modules = self._walker(self.root, self.module_globs)

        demo_index = self._index_demos()
        test_index = self._index_tests()
        doc_index = self._index_docs()

        coverages: List[ModuleCoverage] = []
        for path in modules:
            cov = self._inspect_module(path, demo_index, test_index, doc_index)
            coverages.append(cov)

        # Sort by (priority asc, health_score asc, name asc) so worst-first.
        coverages.sort(key=lambda m: (m.priority, m.health_score, m.name))

        summary = self._summarise(coverages)
        portfolio_score, grade, verdict = self._score_portfolio(coverages, summary)
        insights = self._derive_insights(coverages, summary)
        playbook = self._build_playbook(coverages, summary, verdict, grade)
        headline = self._headline(coverages, summary, grade, verdict)

        return CohortReport(
            modules=coverages,
            playbook=playbook,
            insights=insights,
            headline=headline,
            grade=grade,
            portfolio_score=portfolio_score,
            portfolio_verdict=verdict,
            summary=summary,
            risk_appetite=self.risk_appetite,
            root=str(self.root),
            generated_at=self._now().isoformat(),
        )

    # -- indexing ----------------------------------------------------------

    def _index_demos(self) -> Dict[str, Path]:
        idx: Dict[str, Path] = {}
        for src in sorted(self.root.glob("*_demo.srv")):
            stem = src.stem  # e.g. "forecast_demo"
            if stem.endswith("_demo"):
                topic = stem[: -len("_demo")]
                idx[topic.lower()] = src
        return idx

    def _index_tests(self) -> Dict[str, Path]:
        idx: Dict[str, Path] = {}
        candidates: List[Path] = []
        for d in (self.root, self.root / "tests"):
            if d.is_dir():
                candidates.extend(sorted(d.glob("test_*.py")))
        for tp in candidates:
            stem = tp.stem  # "test_sauravchange"
            if stem.startswith("test_"):
                idx[stem[len("test_"):].lower()] = tp
        return idx

    def _index_docs(self) -> Dict[str, str]:
        """Map doc-file name -> lowercased text content."""
        idx: Dict[str, str] = {}
        for name in _DOC_FILES:
            p = self.root / name
            if p.is_file():
                idx[name] = self._read(p).lower()
        return idx

    # -- inspection --------------------------------------------------------

    def _inspect_module(
        self,
        path: Path,
        demo_index: Dict[str, Path],
        test_index: Dict[str, Path],
        doc_index: Dict[str, str],
    ) -> ModuleCoverage:
        name = path.stem  # "sauravchange"
        source = self._read(path)
        line_count = source.count("\n") + (1 if source and not source.endswith("\n") else 0)

        # Demo lookup: try short name (drop "saurav" prefix) then full name.
        short = name[len("saurav"):] if name.startswith("saurav") else name
        demo_path = demo_index.get(short.lower()) or demo_index.get(name.lower())
        has_demo = demo_path is not None

        # Tests lookup: ``test_<name>.py``.
        tests_path = test_index.get(name.lower())
        has_tests = tests_path is not None

        # CLI introspection.
        has_cli, has_argparse, has_main = _has_cli(source)

        # Docstring introspection.
        has_doc, ds_chars = _extract_module_docstring(source)

        # Doc mentions: substring of either the full name or the short name.
        mentions: List[str] = []
        needles = {name.lower()}
        if short and short != name:
            needles.add(short.lower())
        for doc_name, text in doc_index.items():
            if any(n in text for n in needles if n):
                mentions.append(doc_name)

        # Score the module 0..100.
        score = 0
        reasons: List[str] = []
        if has_demo:
            score += _WEIGHTS["demo"]
            reasons.append(_R_HAS_DEMO)
        else:
            reasons.append(_R_NO_DEMO)
        if has_tests:
            score += _WEIGHTS["tests"]
            reasons.append(_R_HAS_TESTS)
        else:
            reasons.append(_R_NO_TESTS)
        if has_cli:
            score += _WEIGHTS["cli"]
            reasons.append(_R_HAS_CLI)
        else:
            reasons.append(_R_NO_CLI)
        if mentions:
            score += _WEIGHTS["docs"]
            reasons.append(_R_IN_DOCS)
        else:
            reasons.append(_R_NOT_IN_DOCS)
        if has_doc and ds_chars >= _MIN_DOCSTRING_CHARS:
            score += _WEIGHTS["docstring"]
            reasons.append(_R_GOOD_DOCSTRING)
        else:
            reasons.append(_R_THIN_DOCSTRING)
        score = max(0, min(100, score))

        verdict, priority = self._classify(
            has_demo=has_demo,
            has_tests=has_tests,
            has_cli=has_cli,
            has_docs=bool(mentions),
            has_doc=has_doc and ds_chars >= _MIN_DOCSTRING_CHARS,
            score=score,
        )

        try:
            rel = str(path.relative_to(self.root))
        except ValueError:
            rel = str(path)
        try:
            demo_rel = str(demo_path.relative_to(self.root)) if demo_path else None
        except ValueError:
            demo_rel = str(demo_path) if demo_path else None
        try:
            tests_rel = str(tests_path.relative_to(self.root)) if tests_path else None
        except ValueError:
            tests_rel = str(tests_path) if tests_path else None

        return ModuleCoverage(
            name=name,
            path=rel.replace("\\", "/"),
            has_demo=has_demo,
            demo_path=demo_rel.replace("\\", "/") if demo_rel else None,
            has_tests=has_tests,
            tests_path=tests_rel.replace("\\", "/") if tests_rel else None,
            has_cli=has_cli,
            has_argparse=has_argparse,
            has_main_block=has_main,
            has_docstring=has_doc,
            docstring_chars=ds_chars,
            doc_mentions=sorted(mentions),
            line_count=line_count,
            health_score=score,
            verdict=verdict,
            priority=priority,
            reasons=reasons,
        )

    # -- classify ---------------------------------------------------------

    def _classify(
        self,
        *,
        has_demo: bool,
        has_tests: bool,
        has_cli: bool,
        has_docs: bool,
        has_doc: bool,
        score: int,
    ) -> Tuple[str, str]:
        # Worst first.
        if not has_docs and not has_demo and not has_tests:
            return "ORPHAN", "P0"
        if not has_docs and (has_tests or has_demo):
            return "HIDDEN", "P1"
        if not has_tests:
            return "UNTESTED", "P0" if has_cli else "P1"
        if not has_doc:
            return "UNDER_DOCUMENTED", "P2"
        if has_demo and has_tests and has_cli and has_docs and has_doc:
            return "COMPLETE", "P3"
        if score >= 80:
            return "HEALTHY", "P3"
        return "PARTIAL", "P2"

    # -- summary / score --------------------------------------------------

    def _summarise(self, coverages: Sequence[ModuleCoverage]) -> Dict[str, int]:
        s: Dict[str, int] = {
            "total": len(coverages),
            "complete": 0,
            "healthy": 0,
            "partial": 0,
            "under_documented": 0,
            "untested": 0,
            "hidden": 0,
            "orphan": 0,
            "has_demo": 0,
            "has_tests": 0,
            "has_cli": 0,
            "in_docs": 0,
            "good_docstring": 0,
        }
        for m in coverages:
            key = m.verdict.lower()
            if key in s:
                s[key] += 1
            if m.has_demo:
                s["has_demo"] += 1
            if m.has_tests:
                s["has_tests"] += 1
            if m.has_cli:
                s["has_cli"] += 1
            if m.doc_mentions:
                s["in_docs"] += 1
            if m.has_docstring and m.docstring_chars >= _MIN_DOCSTRING_CHARS:
                s["good_docstring"] += 1
        return s

    def _score_portfolio(
        self,
        coverages: Sequence[ModuleCoverage],
        summary: Dict[str, int],
    ) -> Tuple[int, str, str]:
        if not coverages:
            return 0, "F", "UNHEALTHY"
        avg = sum(m.health_score for m in coverages) / len(coverages)
        appetite_mult = {"cautious": 0.95, "balanced": 1.0, "aggressive": 1.05}[self.risk_appetite]
        portfolio_score = int(round(max(0.0, min(100.0, avg * appetite_mult))))

        orphans = summary["orphan"]
        untested = summary["untested"]
        total = summary["total"]

        # Grade A-F with hard gates on orphans/untested ratios.
        untested_ratio = untested / max(total, 1)
        if orphans >= 1 or untested_ratio >= 0.40:
            grade = "F"
        elif untested_ratio >= 0.20:
            grade = "D"
        elif portfolio_score >= 90:
            grade = "A"
        elif portfolio_score >= 78:
            grade = "B"
        elif portfolio_score >= 64:
            grade = "C"
        elif portfolio_score >= 50:
            grade = "D"
        else:
            grade = "F"

        if grade in ("A", "B") and orphans == 0 and untested_ratio <= 0.10:
            verdict = "HEALTHY"
        elif grade == "C":
            verdict = "PARTIAL"
        elif grade == "D":
            verdict = "UNDER_DEVELOPED" if orphans == 0 else "AT_RISK"
        elif orphans >= 2 or untested_ratio >= 0.50:
            verdict = "UNHEALTHY"
        else:
            verdict = "AT_RISK"
        return portfolio_score, grade, verdict

    # -- insights ---------------------------------------------------------

    def _derive_insights(
        self,
        coverages: Sequence[ModuleCoverage],
        summary: Dict[str, int],
    ) -> List[str]:
        out: List[str] = []
        total = summary["total"]
        if total == 0:
            out.append("EMPTY_COHORT")
            return out
        if summary["orphan"] >= 1:
            out.append("ORPHANED_MODULES_PRESENT")
        if summary["hidden"] >= 1:
            out.append("HIDDEN_MODULES_NOT_IN_DOCS")
        if summary["untested"] / total >= 0.20:
            out.append("TESTING_GAP")
        if summary["has_demo"] / total < 0.50:
            out.append("DEMO_COVERAGE_THIN")
        if summary["has_cli"] / total >= 0.80:
            out.append("CLI_FIRST_FAMILY")
        if summary["good_docstring"] / total >= 0.85:
            out.append("DOCSTRING_DISCIPLINE_STRONG")
        if summary["complete"] / total >= 0.50:
            out.append("DEEP_BENCH_OF_COMPLETE_MODULES")
        if summary["healthy"] + summary["complete"] == total:
            out.append("FULL_COVERAGE")
        return out

    # -- playbook ---------------------------------------------------------

    def _build_playbook(
        self,
        coverages: Sequence[ModuleCoverage],
        summary: Dict[str, int],
        portfolio_verdict: str,
        grade: str,
    ) -> List[CohortAction]:
        actions: List[CohortAction] = []
        by_v: Dict[str, List[ModuleCoverage]] = {}
        for m in coverages:
            by_v.setdefault(m.verdict, []).append(m)

        # P0 - existential gaps.
        orphans = by_v.get("ORPHAN", [])
        if orphans:
            actions.append(CohortAction(
                id="audit_orphan_modules",
                label="Audit orphan modules for delete-or-rescue",
                priority="P0",
                reason=(
                    f"{len(orphans)} module(s) have no demo, no tests, and no docs - "
                    "either remove them or wire them into the ecosystem"
                ),
                owner="maintainer",
                blast_radius=5,
                reversibility="low",
                related_modules=sorted(m.name for m in orphans),
            ))
        untested = by_v.get("UNTESTED", [])
        if untested:
            actions.append(CohortAction(
                id="add_tests_for_untested",
                label="Add test_<module>.py for untested modules",
                priority="P0",
                reason=(
                    f"{len(untested)} module(s) ship without any test file - "
                    "regression risk on every refactor"
                ),
                owner="engineering",
                blast_radius=4,
                reversibility="high",
                related_modules=sorted(m.name for m in untested),
            ))

        # P1 - visibility / discoverability.
        hidden = by_v.get("HIDDEN", [])
        if hidden:
            actions.append(CohortAction(
                id="mention_hidden_in_docs",
                label="Mention hidden modules in README/STDLIB.md",
                priority="P1",
                reason=(
                    f"{len(hidden)} module(s) are not mentioned in any doc - "
                    "users cannot discover them"
                ),
                owner="docs",
                blast_radius=2,
                reversibility="high",
                related_modules=sorted(m.name for m in hidden),
            ))
        no_demo = [m for m in coverages if not m.has_demo]
        # Threshold scales with risk appetite.
        no_demo_thresh = {"cautious": 1, "balanced": 2, "aggressive": 3}[self.risk_appetite]
        if len(no_demo) >= no_demo_thresh:
            actions.append(CohortAction(
                id="add_demo_for_no_demo",
                label="Add *_demo.srv companions for advisor modules",
                priority="P1",
                reason=(
                    f"{len(no_demo)} module(s) lack a *_demo.srv companion - "
                    "onboarding curriculum is incomplete"
                ),
                owner="docs",
                blast_radius=2,
                reversibility="high",
                related_modules=sorted(m.name for m in no_demo)[:10],
            ))

        # P2 - polish.
        under_doc = by_v.get("UNDER_DOCUMENTED", [])
        if under_doc:
            actions.append(CohortAction(
                id="expand_module_docstrings",
                label="Expand thin module docstrings to >=80 chars",
                priority="P2",
                reason=(
                    f"{len(under_doc)} module(s) have a thin or missing module docstring"
                ),
                owner="engineering",
                blast_radius=1,
                reversibility="high",
                related_modules=sorted(m.name for m in under_doc),
            ))
        partial = by_v.get("PARTIAL", [])
        if partial:
            actions.append(CohortAction(
                id="close_partial_gaps",
                label="Close remaining gaps on PARTIAL modules",
                priority="P2",
                reason=(
                    f"{len(partial)} module(s) are partially covered - "
                    "address per-module reasons to reach COMPLETE"
                ),
                owner="engineering",
                blast_radius=2,
                reversibility="high",
                related_modules=sorted(m.name for m in partial)[:10],
            ))
        if self.risk_appetite == "cautious" and grade in ("C", "D", "F"):
            actions.append(CohortAction(
                id="schedule_cohort_audit",
                label="Schedule a recurring cohort coverage audit",
                priority="P2",
                reason="Cautious risk appetite + non-A/B grade warrants a recurring check",
                owner="maintainer",
                blast_radius=1,
                reversibility="high",
                related_modules=[],
            ))

        # P3 - fallback when nothing else needs doing.
        if not actions:
            actions.append(CohortAction(
                id="maintain_cohort_discipline",
                label="Maintain current cohort discipline",
                priority="P3",
                reason="No coverage gaps detected; keep the ecosystem balanced",
                owner="maintainer",
                blast_radius=1,
                reversibility="high",
                related_modules=[],
            ))

        # Aggressive: trim lone P2 when P0/P1 exist; trim P3 fallback unless empty.
        if self.risk_appetite == "aggressive":
            has_high = any(a.priority in ("P0", "P1") for a in actions)
            if has_high:
                actions = [a for a in actions if a.priority != "P2" or a.id == "close_partial_gaps"]
            # never drop the fallback if it is the only action
            if any(a.priority != "P3" for a in actions):
                actions = [a for a in actions if a.priority != "P3"]

        # Stable order: priority asc, id asc; dedupe by id.
        seen: set = set()
        deduped: List[CohortAction] = []
        for a in sorted(actions, key=lambda x: (x.priority, x.id)):
            if a.id in seen:
                continue
            seen.add(a.id)
            deduped.append(a)
        return deduped

    # -- headline ---------------------------------------------------------

    def _headline(
        self,
        coverages: Sequence[ModuleCoverage],
        summary: Dict[str, int],
        grade: str,
        verdict: str,
    ) -> str:
        total = summary["total"]
        complete = summary["complete"]
        return (
            f"Cohort: {total} module(s), {complete} complete, "
            f"{summary['untested']} untested, {summary['orphan']} orphan "
            f"-> grade {grade} ({verdict})"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _stdout_writer():
    if sys.platform.startswith("win"):
        try:
            return io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="", write_through=True)
        except Exception:
            return sys.stdout
    return sys.stdout


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit the saurav* module family for ecosystem-coverage gaps.",
    )
    parser.add_argument("--root", default=".", help="Repository root (default: .)")
    parser.add_argument(
        "--risk",
        default="balanced",
        choices=_RISK_APPETITES,
        help="Risk appetite (cautious/balanced/aggressive)",
    )
    parser.add_argument(
        "--format",
        default="text",
        choices=("text", "md", "markdown", "json"),
        help="Output format",
    )
    parser.add_argument(
        "--only",
        default=None,
        help="Comma-separated module names (or shell-style globs) to keep",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write to this file instead of stdout",
    )
    args = parser.parse_args(argv)

    advisor = CohortAdvisor(root=args.root, risk_appetite=args.risk)
    report = advisor.scan()

    if args.only:
        wanted = [tok.strip() for tok in args.only.split(",") if tok.strip()]
        kept: List[ModuleCoverage] = []
        for m in report.modules:
            for pat in wanted:
                if fnmatch.fnmatch(m.name, pat):
                    kept.append(m)
                    break
        # Rebuild a filtered report (preserve original portfolio metrics
        # so the filter view does not lie about the overall grade).
        report = CohortReport(
            modules=kept,
            playbook=report.playbook,
            insights=report.insights,
            headline=report.headline,
            grade=report.grade,
            portfolio_score=report.portfolio_score,
            portfolio_verdict=report.portfolio_verdict,
            summary=report.summary,
            risk_appetite=report.risk_appetite,
            root=report.root,
            generated_at=report.generated_at,
        )

    if args.format in ("md", "markdown"):
        rendered = report.to_markdown()
    elif args.format == "json":
        rendered = report.to_json()
    else:
        rendered = report.to_text()

    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        out = _stdout_writer()
        out.write(rendered)
        try:
            out.flush()
        except Exception:
            pass
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
