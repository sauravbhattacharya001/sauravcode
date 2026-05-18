"""
sauravgate - Agentic merge/release-readiness gate advisor for sauravcode.

Scans the current git working tree + repo state and emits a 0-100
readiness score with a structured verdict (SHIP / STAGE / HOLD / BLOCK),
per-signal reasons, and a P0/P1/P2/P3 action playbook.

Agentic behavior
----------------
- **Awareness**: introspects git status, diff, branch lineage, and the
  working tree for risk markers (TODOs, debug prints, merge conflicts,
  untested new files, doc drift, churn hotspots, staleness).
- **Inference**: each signal scored 0-100 with a tunable weight; weighted
  severity rolled up into a single readiness_score modulated by
  risk_appetite (cautious / balanced / aggressive).
- **Recommendation**: emits a deduped, P0-first action playbook with
  owner, blast_radius (1-5), and reversibility metadata.
- **Explainability**: every signal carries evidence rows + a human reason
  surfaced in text / markdown / JSON renderers.

Public API
----------
- ``ReleaseGate(root=".", branch=None, target_branch=None,
                 risk_appetite="balanced", now=None)``
- ``ReleaseGate.scan()`` -> ``GateReport``
- ``GateReport.format(fmt="text"|"md"|"json")``

CLI
---
::

    python sauravgate.py --root . --format md --risk balanced
    python sauravgate.py --target origin/master --format json --output gate.json

Pure stdlib. No mutation of any repo state. Deterministic given a fixed
now() callable (only ``generated_at`` carries wall-clock state in the
non-JSON renderers).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, List, Optional


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

_RISK_APPETITES = ("cautious", "balanced", "aggressive")
_DEFAULT_TARGETS = ("origin/main", "origin/master", "main", "master")
_TODO_RE = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b")
_PRINT_RE = re.compile(r"\bprint\s*\(")
_CONFLICT_MARKERS = ("<<<<<<<", "=======", ">>>>>>>")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Signal:
    code: str
    label: str
    severity: int            # 0-100
    weight: float
    evidence: List[str] = field(default_factory=list)
    priority: str = "P3"     # P0/P1/P2/P3


@dataclass
class Action:
    id: str
    priority: str            # P0/P1/P2/P3
    label: str
    reason: str
    owner: str
    blast_radius: int        # 1-5
    reversibility: str       # low/medium/high


@dataclass
class GateReport:
    verdict: str             # SHIP / STAGE / HOLD / BLOCK
    readiness_score: int     # 0-100
    grade: str               # A-F
    risk_appetite: str
    summary: str
    signals: List[Signal] = field(default_factory=list)
    actions: List[Action] = field(default_factory=list)
    insights: List[str] = field(default_factory=list)
    generated_at: Optional[str] = None

    # ----- renderers -----

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "readiness_score": self.readiness_score,
            "grade": self.grade,
            "risk_appetite": self.risk_appetite,
            "summary": self.summary,
            "signals": [asdict(s) for s in self.signals],
            "actions": [asdict(a) for a in self.actions],
            "insights": list(self.insights),
            "generated_at": self.generated_at,
        }

    def format(self, fmt: str = "text") -> str:
        fmt = (fmt or "text").lower()
        if fmt == "json":
            return json.dumps(self.to_dict(), sort_keys=True, indent=2, default=str)
        if fmt in ("md", "markdown"):
            return self._render_markdown()
        if fmt == "text":
            return self._render_text()
        raise ValueError(f"unknown format: {fmt!r}")

    def _render_text(self) -> str:
        lines = []
        lines.append(self.summary)
        lines.append(f"verdict={self.verdict} score={self.readiness_score} grade={self.grade} risk={self.risk_appetite}")
        if self.generated_at:
            lines.append(f"generated_at={self.generated_at}")
        if self.signals:
            lines.append("")
            lines.append("Signals:")
            for s in self.signals:
                ev = f" [{'; '.join(s.evidence)}]" if s.evidence else ""
                lines.append(f"  - [{s.priority}] {s.code} sev={s.severity} w={s.weight} {s.label}{ev}")
        if self.actions:
            lines.append("")
            lines.append("Playbook:")
            for a in self.actions:
                lines.append(f"  - [{a.priority}] {a.id}: {a.label} (owner={a.owner}, blast={a.blast_radius}, reversibility={a.reversibility})")
                lines.append(f"      reason: {a.reason}")
        if self.insights:
            lines.append("")
            lines.append("Insights:")
            for i in self.insights:
                lines.append(f"  - {i}")
        return "\n".join(lines)

    def _render_markdown(self) -> str:
        lines = []
        lines.append(f"# Release Gate Report")
        lines.append("")
        lines.append(f"**{self.summary}**")
        lines.append("")
        lines.append(f"- verdict: `{self.verdict}`")
        lines.append(f"- readiness_score: **{self.readiness_score}/100** (grade {self.grade})")
        lines.append(f"- risk_appetite: `{self.risk_appetite}`")
        if self.generated_at:
            lines.append(f"- generated_at: `{self.generated_at}`")
        lines.append("")
        lines.append("## Signals")
        if not self.signals:
            lines.append("_no signals fired_")
        else:
            lines.append("")
            lines.append("| Priority | Code | Sev | Weight | Label |")
            lines.append("|---|---|---:|---:|---|")
            for s in self.signals:
                lines.append(f"| {s.priority} | `{s.code}` | {s.severity} | {s.weight} | {s.label} |")
            for s in self.signals:
                if s.evidence:
                    lines.append("")
                    lines.append(f"<details><summary>{s.code} evidence ({len(s.evidence)})</summary>")
                    lines.append("")
                    for e in s.evidence:
                        lines.append(f"- {e}")
                    lines.append("")
                    lines.append("</details>")
        lines.append("")
        lines.append("## Playbook")
        if not self.actions:
            lines.append("_no actions recommended_")
        else:
            for a in self.actions:
                lines.append(f"- **[{a.priority}] {a.id}** — {a.label}")
                lines.append(f"    - reason: {a.reason}")
                lines.append(f"    - owner: `{a.owner}` · blast: {a.blast_radius} · reversibility: {a.reversibility}")
        lines.append("")
        lines.append("## Insights")
        if not self.insights:
            lines.append("_no cross-signal insights_")
        else:
            for i in self.insights:
                lines.append(f"- {i}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _priority_for(sev: int) -> str:
    if sev >= 80:
        return "P0"
    if sev >= 60:
        return "P1"
    if sev >= 30:
        return "P2"
    return "P3"


def _run_git(args: List[str], cwd: str) -> Optional[subprocess.CompletedProcess]:
    try:
        cp = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    return cp


def _git_ok(cp: Optional[subprocess.CompletedProcess]) -> bool:
    return cp is not None and cp.returncode == 0


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

class ReleaseGate:
    """Agentic merge/release-readiness gate advisor."""

    def __init__(
        self,
        root: str = ".",
        branch: Optional[str] = None,
        target_branch: Optional[str] = None,
        risk_appetite: str = "balanced",
        now: Optional[Callable[[], datetime]] = None,
    ):
        self.root = str(root)
        self.branch = branch
        self.target_branch_pref = target_branch
        if risk_appetite not in _RISK_APPETITES:
            raise ValueError(f"risk_appetite must be one of {_RISK_APPETITES}")
        self.risk_appetite = risk_appetite
        self.now = now or (lambda: datetime.now(timezone.utc))

        self._insights: List[str] = []
        self._is_git_repo = self._detect_git()

    # ---------- detection ----------

    def _detect_git(self) -> bool:
        cp = _run_git(["rev-parse", "--is-inside-work-tree"], self.root)
        return _git_ok(cp) and (cp.stdout.strip() == "true")

    def _resolve_target(self) -> Optional[str]:
        if not self._is_git_repo:
            return None
        prefs: List[str] = []
        if self.target_branch_pref:
            prefs.append(self.target_branch_pref)
        prefs.extend(_DEFAULT_TARGETS)
        for p in prefs:
            cp = _run_git(["rev-parse", "--verify", "--quiet", p], self.root)
            if _git_ok(cp) and cp.stdout.strip():
                return p
        return None

    # ---------- signal collection ----------

    def _signal_uncommitted(self) -> Optional[Signal]:
        if not self._is_git_repo:
            return None
        cp = _run_git(["status", "--porcelain"], self.root)
        if not _git_ok(cp):
            self._insights.append("git_unavailable: UNCOMMITTED_CHANGES")
            return None
        lines = [ln for ln in cp.stdout.splitlines() if ln.strip()]
        n = len(lines)
        sev = min(80, n * 10)
        evidence = [ln.strip() for ln in lines[:5]]
        if n > 5:
            evidence.append(f"... and {n - 5} more")
        return Signal(
            code="UNCOMMITTED_CHANGES",
            label=f"{n} uncommitted change(s) in working tree",
            severity=sev,
            weight=1.0,
            evidence=evidence,
            priority=_priority_for(sev),
        )

    def _signal_unpushed(self) -> Optional[Signal]:
        if not self._is_git_repo:
            return None
        cp = _run_git(["rev-list", "@{u}..HEAD", "--count"], self.root)
        if not _git_ok(cp):
            # No upstream configured.
            return Signal(
                code="UNPUSHED_COMMITS",
                label="no upstream tracking branch configured",
                severity=0,
                weight=0.7,
                evidence=[],
                priority="P3",
            )
        try:
            n = int(cp.stdout.strip() or "0")
        except ValueError:
            n = 0
        sev = min(60, n * 10)
        return Signal(
            code="UNPUSHED_COMMITS",
            label=f"{n} local commit(s) not yet pushed",
            severity=sev,
            weight=0.7,
            evidence=[],
            priority=_priority_for(sev),
        )

    def _signal_large_diff(self, target: Optional[str]) -> Optional[Signal]:
        if not self._is_git_repo:
            return None
        if not target:
            self._insights.append("no target branch resolved for LARGE_DIFF")
            return None
        cp = _run_git(["diff", "--numstat", f"{target}..HEAD"], self.root)
        if not _git_ok(cp):
            self._insights.append("git_unavailable: LARGE_DIFF")
            return None
        added = 0
        deleted = 0
        for ln in cp.stdout.splitlines():
            parts = ln.split("\t")
            if len(parts) < 3:
                continue
            a, d = parts[0], parts[1]
            try:
                added += int(a) if a != "-" else 0
                deleted += int(d) if d != "-" else 0
            except ValueError:
                continue
        total = added + deleted
        if total >= 2000:
            sev = 90
        elif total >= 1000:
            sev = 75
        elif total >= 500:
            sev = 55
        elif total >= 200:
            sev = 30
        else:
            sev = 0
        return Signal(
            code="LARGE_DIFF",
            label=f"diff vs {target}: +{added}/-{deleted} ({total} lines)",
            severity=sev,
            weight=0.8,
            evidence=[],
            priority=_priority_for(sev),
        )

    def _diff_name_status(self, target: Optional[str]) -> List[tuple]:
        if not target or not self._is_git_repo:
            return []
        cp = _run_git(["diff", "--name-status", f"{target}..HEAD"], self.root)
        if not _git_ok(cp):
            return []
        out = []
        for ln in cp.stdout.splitlines():
            parts = ln.split("\t")
            if len(parts) >= 2:
                out.append((parts[0], parts[-1]))
        return out

    def _signal_new_files_no_tests(self, target: Optional[str]) -> Optional[Signal]:
        if not target or not self._is_git_repo:
            return None
        name_status = self._diff_name_status(target)
        added_py = [p for st, p in name_status if st.startswith("A") and p.endswith(".py") and not Path(p).name.startswith("test_")]
        untested: List[str] = []
        for path in added_py:
            stem = Path(path).stem
            candidates = [f"test_{stem}.py"]
            found = False
            for cand in candidates:
                for _ in Path(self.root).rglob(cand):
                    found = True
                    break
                if found:
                    break
            if not found:
                untested.append(path)
        n = len(untested)
        sev = min(70, n * 15)
        return Signal(
            code="NEW_FILES_NO_TESTS",
            label=f"{n} new python file(s) without matching test_*.py",
            severity=sev,
            weight=0.9,
            evidence=untested[:5],
            priority=_priority_for(sev),
        )

    def _signal_missing_doc_update(self, target: Optional[str]) -> Optional[Signal]:
        if not target or not self._is_git_repo:
            return None
        name_status = self._diff_name_status(target)
        if not name_status:
            return None
        touched_py = any(p.endswith(".py") for _, p in name_status)
        touched_md = any(p.endswith(".md") for _, p in name_status)
        if not touched_py:
            return None
        sev = 0 if touched_md else 35
        return Signal(
            code="MISSING_DOC_UPDATE",
            label="python changes without accompanying *.md updates" if sev else "docs updated alongside code",
            severity=sev,
            weight=0.5,
            evidence=[],
            priority=_priority_for(sev),
        )

    def _diff_added_lines(self, target: Optional[str]) -> List[tuple]:
        """Return list of (path, line_text) for lines starting with '+' (excluding +++ headers)."""
        if not target or not self._is_git_repo:
            return []
        cp = _run_git(["diff", f"{target}..HEAD"], self.root)
        if not _git_ok(cp):
            return []
        out = []
        current = None
        for ln in cp.stdout.splitlines():
            if ln.startswith("+++ b/"):
                current = ln[6:]
                continue
            if ln.startswith("+++") or ln.startswith("---"):
                continue
            if ln.startswith("diff --git"):
                current = None
                continue
            if ln.startswith("+") and current is not None and not ln.startswith("+++"):
                out.append((current, ln[1:]))
        return out

    def _signal_todo_fixme(self, target: Optional[str]) -> Optional[Signal]:
        added = self._diff_added_lines(target)
        if not added:
            return None
        hits = [(p, ln) for (p, ln) in added if _TODO_RE.search(ln)]
        n = len(hits)
        sev = min(50, n * 8)
        return Signal(
            code="TODO_FIXME_INTRODUCED",
            label=f"{n} new TODO/FIXME/XXX/HACK marker(s) in diff",
            severity=sev,
            weight=0.6,
            evidence=[f"{p}: {ln.strip()[:80]}" for p, ln in hits[:5]],
            priority=_priority_for(sev),
        )

    def _signal_debug_print(self, target: Optional[str]) -> Optional[Signal]:
        added = self._diff_added_lines(target)
        if not added:
            return None
        hits = [(p, ln) for (p, ln) in added if p.endswith(".py") and _PRINT_RE.search(ln)]
        n = len(hits)
        sev = min(40, n * 5)
        return Signal(
            code="DEBUG_PRINT_INTRODUCED",
            label=f"{n} new print(...) line(s) in python files",
            severity=sev,
            weight=0.4,
            evidence=[f"{p}: {ln.strip()[:80]}" for p, ln in hits[:5]],
            priority=_priority_for(sev),
        )

    def _signal_behind_target(self, target: Optional[str]) -> Optional[Signal]:
        if not target or not self._is_git_repo:
            return None
        cp = _run_git(["rev-list", f"HEAD..{target}", "--count"], self.root)
        if not _git_ok(cp):
            return None
        try:
            n = int(cp.stdout.strip() or "0")
        except ValueError:
            n = 0
        sev = min(60, n * 8)
        return Signal(
            code="BRANCH_BEHIND_TARGET",
            label=f"branch behind {target} by {n} commit(s)",
            severity=sev,
            weight=0.7,
            evidence=[],
            priority=_priority_for(sev),
        )

    def _signal_stale_branch(self) -> Optional[Signal]:
        if not self._is_git_repo:
            return None
        cp = _run_git(["log", "-1", "--format=%ct"], self.root)
        if not _git_ok(cp):
            return None
        try:
            last = int(cp.stdout.strip())
        except ValueError:
            return None
        now_ts = int(self.now().timestamp())
        days = max(0, (now_ts - last) // 86400)
        sev = min(60, max(0, (days - 7) * 4))
        return Signal(
            code="STALE_BRANCH",
            label=f"last commit {days} day(s) ago",
            severity=int(sev),
            weight=0.4,
            evidence=[],
            priority=_priority_for(int(sev)),
        )

    def _signal_churn_hotspot(self, target: Optional[str]) -> Optional[Signal]:
        if not target or not self._is_git_repo:
            return None
        cp = _run_git(["diff", "--numstat", f"{target}..HEAD"], self.root)
        if not _git_ok(cp):
            return None
        hotspots = []
        for ln in cp.stdout.splitlines():
            parts = ln.split("\t")
            if len(parts) < 3:
                continue
            try:
                a = int(parts[0]) if parts[0] != "-" else 0
                d = int(parts[1]) if parts[1] != "-" else 0
            except ValueError:
                continue
            if a + d > 300:
                hotspots.append((parts[2], a + d))
        n = len(hotspots)
        if n == 0:
            return None
        sev = min(70, 40 + (n - 1) * 10)
        hotspots.sort(key=lambda x: x[1], reverse=True)
        return Signal(
            code="CHURN_HOTSPOT",
            label=f"{n} file(s) with >300 changed lines",
            severity=sev,
            weight=0.6,
            evidence=[f"{p}: {ch} lines" for p, ch in hotspots[:5]],
            priority=_priority_for(sev),
        )

    def _signal_conflict_markers(self) -> Optional[Signal]:
        """Scan tracked files for merge conflict markers."""
        files: List[str] = []
        if self._is_git_repo:
            cp = _run_git(["ls-files"], self.root)
            if _git_ok(cp):
                files = [ln for ln in cp.stdout.splitlines() if ln.strip()]
        if not files:
            # Fall back to walking the tree (skip .git)
            root = Path(self.root)
            for p in root.rglob("*"):
                if p.is_file() and ".git" not in p.parts:
                    try:
                        files.append(str(p.relative_to(root)))
                    except ValueError:
                        continue
        conflicted: List[str] = []
        for rel in files:
            fp = Path(self.root) / rel
            try:
                if fp.stat().st_size > 2_000_000:
                    continue
                text = fp.read_text(encoding="utf-8", errors="ignore")
            except (OSError, UnicodeDecodeError):
                continue
            if all(m in text for m in _CONFLICT_MARKERS):
                conflicted.append(rel)
        n = len(conflicted)
        if n == 0:
            return None
        return Signal(
            code="MERGE_CONFLICT_MARKERS",
            label=f"{n} file(s) contain merge conflict markers",
            severity=95,
            weight=1.0,
            evidence=conflicted[:5],
            priority="P0",
        )

    # ---------- aggregation ----------

    def _build_actions(self, signals: List[Signal]) -> List[Action]:
        by_code = {s.code: s for s in signals}
        actions: List[Action] = []

        s = by_code.get("MERGE_CONFLICT_MARKERS")
        if s and s.severity > 0:
            actions.append(Action(
                id="RESOLVE_MERGE_CONFLICTS",
                priority="P0",
                label="Resolve merge conflict markers before any push",
                reason=s.label,
                owner="author",
                blast_radius=5,
                reversibility="low",
            ))

        s = by_code.get("UNCOMMITTED_CHANGES")
        if s and s.severity >= 80:
            actions.append(Action(
                id="COMMIT_OR_STASH_CHANGES",
                priority="P0",
                label="Commit or stash dirty working tree",
                reason=s.label,
                owner="author",
                blast_radius=2,
                reversibility="high",
            ))

        s = by_code.get("UNPUSHED_COMMITS")
        if s and s.severity > 0:
            actions.append(Action(
                id="PUSH_LOCAL_COMMITS",
                priority="P1",
                label="Push local commits to remote",
                reason=s.label,
                owner="author",
                blast_radius=1,
                reversibility="high",
            ))

        s = by_code.get("LARGE_DIFF")
        if s and s.severity >= 75:
            actions.append(Action(
                id="SPLIT_LARGE_DIFF",
                priority="P1",
                label="Split large diff into reviewable chunks",
                reason=s.label,
                owner="author",
                blast_radius=3,
                reversibility="medium",
            ))

        s = by_code.get("NEW_FILES_NO_TESTS")
        if s and s.severity > 0:
            files = ", ".join(s.evidence[:5]) if s.evidence else "see signal evidence"
            actions.append(Action(
                id="ADD_TESTS_FOR_NEW_FILES",
                priority="P1",
                label="Add tests for newly added python files",
                reason=f"{s.label}: {files}",
                owner="author",
                blast_radius=2,
                reversibility="high",
            ))

        s = by_code.get("BRANCH_BEHIND_TARGET")
        if s and s.severity >= 40:
            actions.append(Action(
                id="REBASE_OR_MERGE_TARGET",
                priority="P1",
                label="Rebase/merge target branch before pushing",
                reason=s.label,
                owner="author",
                blast_radius=3,
                reversibility="medium",
            ))

        s = by_code.get("MISSING_DOC_UPDATE")
        if s and s.severity > 0:
            actions.append(Action(
                id="UPDATE_DOCUMENTATION",
                priority="P2",
                label="Update documentation to reflect code changes",
                reason=s.label,
                owner="author",
                blast_radius=1,
                reversibility="high",
            ))

        s = by_code.get("DEBUG_PRINT_INTRODUCED")
        if s and s.severity >= 20:
            actions.append(Action(
                id="STRIP_DEBUG_PRINTS",
                priority="P2",
                label="Strip stray debug print() statements",
                reason=s.label,
                owner="author",
                blast_radius=1,
                reversibility="high",
            ))

        s = by_code.get("TODO_FIXME_INTRODUCED")
        if s and s.severity >= 30:
            actions.append(Action(
                id="RESOLVE_OR_FILE_TODOS",
                priority="P2",
                label="Resolve newly-introduced TODOs or file tracking issues",
                reason=s.label,
                owner="author",
                blast_radius=1,
                reversibility="high",
            ))

        s = by_code.get("CHURN_HOTSPOT")
        if s and s.severity > 0:
            actions.append(Action(
                id="REVIEW_CHURN_HOTSPOTS",
                priority="P2",
                label="Pair-review the high-churn files",
                reason=s.label,
                owner="reviewer",
                blast_radius=2,
                reversibility="high",
            ))

        s = by_code.get("STALE_BRANCH")
        if s and s.severity > 0:
            actions.append(Action(
                id="REFRESH_STALE_BRANCH",
                priority="P3",
                label="Refresh branch / re-run tests against latest target",
                reason=s.label,
                owner="author",
                blast_radius=1,
                reversibility="high",
            ))

        # Dedup by id, P0-first stable ordering.
        priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        seen = set()
        ordered = []
        for a in sorted(actions, key=lambda a: (priority_order[a.priority], a.id)):
            if a.id in seen:
                continue
            seen.add(a.id)
            ordered.append(a)
        return ordered

    def _build_insights(self, signals: List[Signal], target: Optional[str]) -> List[str]:
        out = list(self._insights)
        by_code = {s.code: s for s in signals}
        nf = by_code.get("NEW_FILES_NO_TESTS")
        if nf and nf.severity > 0:
            out.append(f"{len(nf.evidence)} file(s) added, all untested")
        stale = by_code.get("STALE_BRANCH")
        if stale and stale.severity > 0:
            out.append(stale.label)
        behind = by_code.get("BRANCH_BEHIND_TARGET")
        if behind and behind.severity > 0 and target:
            out.append(behind.label)
        unc = by_code.get("UNCOMMITTED_CHANGES")
        if unc and unc.severity > 0:
            out.append(unc.label)
        return out

    # ---------- scoring ----------

    def _compute_score(self, signals: List[Signal]) -> int:
        active = [s for s in signals if s.severity > 0]
        if not active:
            base = 100
        else:
            total_w = sum(s.weight for s in active)
            if total_w <= 0:
                base = 100
            else:
                weighted = sum(s.severity * s.weight for s in active) / total_w
                base = max(0, int(round(100 - weighted)))
        if self.risk_appetite == "cautious":
            base -= 8
        elif self.risk_appetite == "aggressive":
            base += 8
        return max(0, min(100, base))

    def _verdict_and_grade(self, score: int, signals: List[Signal]) -> tuple:
        has_block_signal = any(s.severity >= 90 for s in signals)
        if has_block_signal or score < 30:
            verdict = "BLOCK"
        elif score < 50:
            verdict = "HOLD"
        elif score < 75:
            verdict = "STAGE"
        else:
            verdict = "SHIP"
        if verdict == "BLOCK":
            grade = "F"
        elif score >= 85:
            grade = "A"
        elif score >= 70:
            grade = "B"
        elif score >= 55:
            grade = "C"
        elif score >= 40:
            grade = "D"
        else:
            grade = "F"
        return verdict, grade

    # ---------- top-level ----------

    def scan(self) -> GateReport:
        self._insights = []
        if not self._is_git_repo:
            self._insights.append("not a git repository: most signals skipped")

        target = self._resolve_target()
        if self._is_git_repo and target is None:
            self._insights.append("no target branch available; diff-based signals skipped")

        collectors = [
            self._signal_conflict_markers(),
            self._signal_uncommitted(),
            self._signal_unpushed(),
            self._signal_large_diff(target),
            self._signal_new_files_no_tests(target),
            self._signal_missing_doc_update(target),
            self._signal_todo_fixme(target),
            self._signal_debug_print(target),
            self._signal_behind_target(target),
            self._signal_stale_branch(),
            self._signal_churn_hotspot(target),
        ]
        signals = [s for s in collectors if s is not None]

        priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        signals.sort(key=lambda s: (priority_order[s.priority], -s.severity, s.code))

        score = self._compute_score(signals)
        verdict, grade = self._verdict_and_grade(score, signals)

        actions = self._build_actions(signals)
        insights = self._build_insights(signals, target)

        p0 = sum(1 for a in actions if a.priority == "P0")
        p1 = sum(1 for a in actions if a.priority == "P1")
        summary = f"{verdict}: {score}/100 readiness — {p0} P0, {p1} P1 issues"

        return GateReport(
            verdict=verdict,
            readiness_score=score,
            grade=grade,
            risk_appetite=self.risk_appetite,
            summary=summary,
            signals=signals,
            actions=actions,
            insights=insights,
            generated_at=self.now().isoformat(),
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sauravgate",
        description="Agentic merge/release-readiness gate advisor for sauravcode.",
    )
    p.add_argument("--root", default=".", help="repository root (default: .)")
    p.add_argument("--target", default=None, help="target branch (default: auto-detect origin/main/master)")
    p.add_argument("--risk", choices=list(_RISK_APPETITES), default="balanced", help="risk appetite")
    p.add_argument("--format", choices=["text", "md", "json"], default="text", help="output format")
    p.add_argument("--output", default=None, help="optional output path; otherwise prints to stdout")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_argparser().parse_args(argv)
    gate = ReleaseGate(
        root=args.root,
        target_branch=args.target,
        risk_appetite=args.risk,
    )
    report = gate.scan()
    text = report.format(args.format)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        try:
            sys.stdout.write(text + "\n")
        except UnicodeEncodeError:
            sys.stdout.buffer.write((text + "\n").encode("utf-8", errors="replace"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
