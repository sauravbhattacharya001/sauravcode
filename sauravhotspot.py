"""
sauravhotspot - Agentic code hotspot / risk advisor for sauravcode projects.

Surfaces high-risk files that combine *high churn* (frequently changed),
*high complexity* (large / dense), and *high bug-fix density* (commits with
fix/bug/regression/hotfix keywords). These are classic refactor targets:
modules where a small change is most likely to break something.

It is dependency-free (stdlib only) and *read-only* with respect to the
repository: it shells out to ``git`` for history but never writes or
mutates files.

Agentic behavior
----------------
- **Awareness**: walks ``git log --numstat`` over a lookback window to learn
  which files churn and how often a change to them is a *fix*.
- **Inference**: fuses churn, complexity, fix-density, and recency into a
  single 0-100 ``risk_score`` per file, then classifies into
  ``HOTSPOT/WARM/COOL/STABLE/UNTRACKED``.
- **Recommendation**: emits a deduped, P0-first playbook
  (REFACTOR_HOTSPOT / ADD_REGRESSION_TESTS / FREEZE_AND_REVIEW /
  SPLIT_OVERSIZED_MODULE / AUDIT_FIX_DENSITY / SCHEDULE_HOTSPOT_REVIEW /
  HEALTHY_PORTFOLIO) with owner + blast_radius + reversibility metadata.
- **Risk appetite**: ``cautious``/``balanced``/``aggressive`` modulates
  thresholds and trims low-priority noise.
- **Explainability**: every finding carries structured ``reasons``.

Public API
----------
- ``HotspotAdvisor(root=".", lookback_days=90, top=20,
                   risk_appetite="balanced", include_globs=None,
                   exclude_globs=None, now_fn=None)``
- ``HotspotAdvisor.analyze()`` -> ``HotspotReport``
- ``HotspotReport.format(fmt="text"|"md"|"json")``

CLI
---
::

    python -m sauravhotspot --root . --lookback-days 90 --top 15 --format md
    python -m sauravhotspot --risk cautious --format json

The module is intentionally standalone; importing it does not pull in the
rest of the sauravcode runtime.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_LOOKBACK_DAYS = 90
_DEFAULT_TOP = 20
_FIX_RE = re.compile(
    r"\b(fix|fixes|fixed|fixing|bug|bugfix|regress|regression|hotfix|"
    r"patch|revert|broken|crash|defect)\b",
    re.IGNORECASE,
)
_SOURCE_EXTS = {
    ".py", ".srv", ".js", ".ts", ".tsx", ".jsx", ".java", ".cs", ".c",
    ".cc", ".cpp", ".h", ".hpp", ".go", ".rs", ".rb", ".php", ".swift",
    ".kt", ".scala", ".ml", ".mli", ".dart",
}
_RISK_APPETITES = ("cautious", "balanced", "aggressive")

# Default exclude globs used when callers don't override them. Exposed as a
# module-level constant so the CLI (and other callers) can extend it without
# needing to instantiate a HotspotAdvisor just to read the defaults.
DEFAULT_EXCLUDE_GLOBS: tuple[str, ...] = (
    ".git/*", "node_modules/*", "dist/*", "build/*", "*.min.js",
    "*.lock", "__pycache__/*",
)

# Verdicts (ordered, lowest risk first)
V_UNTRACKED = "UNTRACKED"
V_STABLE = "STABLE"
V_COOL = "COOL"
V_WARM = "WARM"
V_HOTSPOT = "HOTSPOT"

# Priorities
P0, P1, P2, P3 = 0, 1, 2, 3


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class FileStats:
    path: str
    commits: int = 0
    fix_commits: int = 0
    insertions: int = 0
    deletions: int = 0
    distinct_authors: int = 0
    last_change_days: Optional[float] = None
    line_count: int = 0
    size_bytes: int = 0
    exists: bool = True


@dataclass
class HotspotFinding:
    path: str
    verdict: str
    priority: int
    risk_score: float
    churn_score: float
    complexity_score: float
    fix_density_score: float
    recency_score: float
    reasons: list[str] = field(default_factory=list)
    stats: FileStats = field(default_factory=lambda: FileStats(path=""))


@dataclass
class PlaybookAction:
    id: str
    priority: int
    label: str
    reason: str
    owner: str
    blast_radius: int  # 1..5
    reversibility: str  # low / medium / high
    related_paths: list[str] = field(default_factory=list)


@dataclass
class HotspotReport:
    root: str
    lookback_days: int
    risk_appetite: str
    generated_at: str
    findings: list[HotspotFinding]
    playbook: list[PlaybookAction]
    insights: list[str]
    portfolio_risk_score: float
    grade: str
    summary: str

    # ----- formatters -----

    def format(self, fmt: str = "text") -> str:
        fmt = (fmt or "text").lower()
        if fmt in ("md", "markdown"):
            return self._format_markdown()
        if fmt == "json":
            return self._format_json()
        return self._format_text()

    def _format_text(self) -> str:
        lines = [self.summary, ""]
        if self.findings:
            lines.append("Top hotspots:")
            for f in self.findings[:10]:
                lines.append(
                    f"  [{_pname(f.priority)}] {f.verdict:<8} "
                    f"risk={f.risk_score:5.1f}  {f.path}"
                )
                if f.reasons:
                    lines.append(f"      reasons: {', '.join(f.reasons[:4])}")
        else:
            lines.append("(no candidate files in lookback window)")
        if self.playbook:
            lines.append("")
            lines.append("Playbook:")
            for a in self.playbook:
                lines.append(
                    f"  [{_pname(a.priority)}] {a.label} ({a.owner}) - {a.reason}"
                )
        if self.insights:
            lines.append("")
            lines.append("Insights:")
            for i in self.insights:
                lines.append(f"  * {i}")
        return "\n".join(lines)

    def _format_markdown(self) -> str:
        out = [f"# Hotspot report\n", self.summary, ""]
        out.append("## Summary")
        out.append("")
        out.append("| Metric | Value |")
        out.append("|---|---|")
        out.append(f"| Root | `{self.root}` |")
        out.append(f"| Lookback (days) | {self.lookback_days} |")
        out.append(f"| Risk appetite | {self.risk_appetite} |")
        out.append(f"| Portfolio risk | {self.portfolio_risk_score:.1f} |")
        out.append(f"| Grade | **{self.grade}** |")
        out.append(f"| Files analyzed | {len(self.findings)} |")
        out.append("")
        out.append("## Top hotspots")
        out.append("")
        if self.findings:
            out.append("| Priority | Verdict | Risk | Commits | Fix% | Lines | File | Reasons |")
            out.append("|---|---|---|---|---|---|---|---|")
            for f in self.findings[:20]:
                fix_pct = (
                    (f.stats.fix_commits / f.stats.commits * 100)
                    if f.stats.commits else 0.0
                )
                reasons = ", ".join(f.reasons[:4]) or "-"
                out.append(
                    f"| {_pname(f.priority)} | {f.verdict} | "
                    f"{f.risk_score:.1f} | {f.stats.commits} | "
                    f"{fix_pct:.0f}% | {f.stats.line_count} | "
                    f"`{f.path}` | {reasons} |"
                )
        else:
            out.append("_No candidate files in lookback window._")
        out.append("")
        out.append("## Playbook")
        out.append("")
        if self.playbook:
            out.append("| Priority | Action | Owner | Blast | Reversibility | Reason |")
            out.append("|---|---|---|---|---|---|")
            for a in self.playbook:
                out.append(
                    f"| {_pname(a.priority)} | {a.label} | {a.owner} | "
                    f"{a.blast_radius} | {a.reversibility} | {a.reason} |"
                )
        else:
            out.append("_No actions._")
        out.append("")
        out.append("## Insights")
        out.append("")
        if self.insights:
            for i in self.insights:
                out.append(f"- {i}")
        else:
            out.append("- (none)")
        return "\n".join(out) + "\n"

    def _format_json(self) -> str:
        payload = {
            "root": self.root,
            "lookback_days": self.lookback_days,
            "risk_appetite": self.risk_appetite,
            "generated_at": self.generated_at,
            "portfolio_risk_score": round(self.portfolio_risk_score, 2),
            "grade": self.grade,
            "summary": self.summary,
            "findings": [
                {
                    "path": f.path,
                    "verdict": f.verdict,
                    "priority": f.priority,
                    "priority_label": _pname(f.priority),
                    "risk_score": round(f.risk_score, 2),
                    "churn_score": round(f.churn_score, 2),
                    "complexity_score": round(f.complexity_score, 2),
                    "fix_density_score": round(f.fix_density_score, 2),
                    "recency_score": round(f.recency_score, 2),
                    "reasons": list(f.reasons),
                    "stats": asdict(f.stats),
                }
                for f in self.findings
            ],
            "playbook": [
                {
                    "id": a.id,
                    "priority": a.priority,
                    "priority_label": _pname(a.priority),
                    "label": a.label,
                    "reason": a.reason,
                    "owner": a.owner,
                    "blast_radius": a.blast_radius,
                    "reversibility": a.reversibility,
                    "related_paths": list(a.related_paths),
                }
                for a in self.playbook
            ],
            "insights": list(self.insights),
        }
        return json.dumps(payload, sort_keys=True, indent=2, default=str)


def _pname(p: int) -> str:
    return f"P{p}"


# ---------------------------------------------------------------------------
# Advisor
# ---------------------------------------------------------------------------


class HotspotAdvisor:
    """Agentic hotspot / churn-risk advisor.

    Parameters
    ----------
    root:
        Path to the project root (a git checkout). Defaults to ``"."``.
    lookback_days:
        How many days of history to consider (default: 90).
    top:
        Cap on the number of findings returned (default: 20).
    risk_appetite:
        ``"cautious"``, ``"balanced"`` (default), or ``"aggressive"``.
    include_globs / exclude_globs:
        Optional path globs (POSIX-style, matched against repo-relative
        paths). ``include`` is applied first if provided; ``exclude``
        always runs.
    now_fn:
        Optional callable returning a timezone-aware datetime (for
        deterministic tests).
    """

    def __init__(
        self,
        root: str | Path = ".",
        lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
        top: int = _DEFAULT_TOP,
        risk_appetite: str = "balanced",
        include_globs: Optional[Iterable[str]] = None,
        exclude_globs: Optional[Iterable[str]] = None,
        now_fn: Optional[Callable[[], datetime]] = None,
    ) -> None:
        if risk_appetite not in _RISK_APPETITES:
            raise ValueError(
                f"risk_appetite must be one of {_RISK_APPETITES}, got "
                f"{risk_appetite!r}"
            )
        if lookback_days <= 0:
            raise ValueError("lookback_days must be positive")
        if top <= 0:
            raise ValueError("top must be positive")
        self.root = Path(root).resolve()
        self.lookback_days = int(lookback_days)
        self.top = int(top)
        self.risk_appetite = risk_appetite
        self.include_globs = tuple(include_globs) if include_globs else ()
        self.exclude_globs = tuple(exclude_globs) if exclude_globs else DEFAULT_EXCLUDE_GLOBS
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    # ----- public entry point -----

    def analyze(self) -> HotspotReport:
        now = self._now_fn()
        stats = self._collect_stats(now)
        findings = [self._score_file(s) for s in stats.values()]
        findings.sort(
            key=lambda f: (-f.risk_score, f.path),
        )
        capped = findings[: self.top]
        playbook = self._build_playbook(capped)
        insights = self._build_insights(capped, stats)
        portfolio = self._portfolio_score(capped)
        grade = self._grade(portfolio, capped)
        summary = self._headline(grade, portfolio, capped)
        return HotspotReport(
            root=str(self.root),
            lookback_days=self.lookback_days,
            risk_appetite=self.risk_appetite,
            generated_at=now.isoformat(),
            findings=capped,
            playbook=playbook,
            insights=insights,
            portfolio_risk_score=portfolio,
            grade=grade,
            summary=summary,
        )

    # ----- git plumbing -----

    def _git(self, *args: str) -> str:
        try:
            res = subprocess.run(
                ["git", *args],
                cwd=str(self.root),
                capture_output=True,
                text=True,
                check=False,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError:
            return ""
        if res.returncode != 0:
            return ""
        return res.stdout or ""

    def _collect_stats(self, now: datetime) -> dict[str, FileStats]:
        since = f"--since={self.lookback_days}.days.ago"
        # Use a NUL-separated commit boundary marker so file names with
        # spaces / quotes don't break parsing.
        log = self._git(
            "log", since, "--no-merges", "--numstat",
            "--pretty=format:%x00COMMIT%x00%H%x00%an%x00%at%x00%s",
        )
        stats: dict[str, FileStats] = {}
        current_is_fix = False
        current_ts: Optional[int] = None
        current_author: Optional[str] = None
        # Authors per file (use set, then collapse at end)
        authors: dict[str, set[str]] = {}
        # ---- Perf: hoist invariants out of the hot loop ----
        # ``now.timestamp()`` and a freshly-bound ``self._is_excluded`` were
        # being recomputed/looked-up per diff line. For repos with tens of
        # thousands of numstat rows this is the bulk of the work.
        now_ts = now.timestamp()
        lookback = self.lookback_days
        is_excluded = self._is_excluded
        # Memoize per-path filter decisions: exclusion + extension. Same path
        # appears many times across commits, so caching dominates.
        path_filter_cache: dict[str, bool] = {}
        source_exts = _SOURCE_EXTS
        fix_re_search = _FIX_RE.search
        COMMIT_MARKER = "\x00COMMIT\x00"
        for raw in log.splitlines():
            line = raw.rstrip("\r")
            if line.startswith(COMMIT_MARKER):
                _, _, sha, author, ts, *subj = line.split("\x00")
                subject = subj[0] if subj else ""
                current_is_fix = bool(fix_re_search(subject))
                try:
                    current_ts = int(ts)
                except ValueError:
                    current_ts = None
                current_author = author or "?"
                continue
            if not line or not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            ins_s, del_s, path = parts
            if not path:
                continue
            keep = path_filter_cache.get(path)
            if keep is None:
                if is_excluded(path):
                    keep = False
                else:
                    # Cheap suffix extraction without constructing a Path.
                    dot = path.rfind(".")
                    slash = max(path.rfind("/"), path.rfind("\\"))
                    if dot > slash and dot != -1:
                        ext = path[dot:].lower()
                        keep = (not ext) or (ext in source_exts)
                    else:
                        # No extension - keep (matches old behavior where
                        # Path(path).suffix returned "").
                        keep = True
                path_filter_cache[path] = keep
            if not keep:
                continue
            # binary diffs report "-"
            try:
                ins = int(ins_s) if ins_s != "-" else 0
                dele = int(del_s) if del_s != "-" else 0
            except ValueError:
                ins, dele = 0, 0
            st = stats.get(path)
            if st is None:
                st = FileStats(path=path)
                stats[path] = st
            st.commits += 1
            st.insertions += ins
            st.deletions += dele
            if current_is_fix:
                st.fix_commits += 1
            if current_ts is not None:
                age_days = (now_ts - float(current_ts)) / 86400.0
                if st.last_change_days is None or age_days < st.last_change_days:
                    st.last_change_days = age_days
            if current_author:
                author_set = authors.get(path)
                if author_set is None:
                    author_set = set()
                    authors[path] = author_set
                author_set.add(current_author)
        for path, st in stats.items():
            st.distinct_authors = len(authors.get(path, ()))
            self._fill_file_metrics(st)
        return stats

    def _is_excluded(self, path: str) -> bool:
        # Include filter wins first
        if self.include_globs:
            if not any(fnmatch.fnmatch(path, g) for g in self.include_globs):
                return True
        for g in self.exclude_globs:
            if fnmatch.fnmatch(path, g):
                return True
        return False

    def _fill_file_metrics(self, st: FileStats) -> None:
        p = self.root / st.path
        try:
            if not p.is_file():
                st.exists = False
                return
            data = p.read_bytes()
            st.size_bytes = len(data)
            # Count lines without decoding the whole file twice
            st.line_count = data.count(b"\n") + (
                1 if data and not data.endswith(b"\n") else 0
            )
        except OSError:
            st.exists = False

    # ----- scoring -----

    def _score_file(self, st: FileStats) -> HotspotFinding:
        # Per-component scaling: each ends in 0..100 before fusion.
        commit_cap = 30
        churn = min(100.0, (st.commits / commit_cap) * 100.0)
        # Complexity from line count (anything >2000 saturates)
        lc = max(0, st.line_count)
        if lc <= 0:
            complexity = 0.0
        else:
            complexity = min(100.0, (lc / 2000.0) * 100.0)
        # Fix density
        if st.commits <= 0:
            fix_density = 0.0
        else:
            fix_density = min(100.0, (st.fix_commits / st.commits) * 150.0)
        # Recency: 0 days -> 100, lookback -> 0
        if st.last_change_days is None:
            recency = 0.0
        else:
            ratio = max(0.0, min(1.0, 1.0 - st.last_change_days / self.lookback_days))
            recency = ratio * 100.0
        # Author churn boost (more authors = more risk of breakage)
        author_boost = min(15.0, max(0, st.distinct_authors - 1) * 3.0)

        # Risk appetite weight tuning
        if self.risk_appetite == "cautious":
            w_churn, w_complex, w_fix, w_recency = 0.32, 0.18, 0.32, 0.18
            appetite_mult = 1.15
        elif self.risk_appetite == "aggressive":
            w_churn, w_complex, w_fix, w_recency = 0.40, 0.25, 0.20, 0.15
            appetite_mult = 0.85
        else:  # balanced
            w_churn, w_complex, w_fix, w_recency = 0.35, 0.22, 0.28, 0.15
            appetite_mult = 1.0

        base = (
            churn * w_churn
            + complexity * w_complex
            + fix_density * w_fix
            + recency * w_recency
        )
        risk = max(0.0, min(100.0, (base + author_boost) * appetite_mult))

        reasons = self._reasons(st, churn, complexity, fix_density, recency)
        verdict = self._verdict(risk, st)
        priority = self._priority(verdict, fix_density, st)

        return HotspotFinding(
            path=st.path,
            verdict=verdict,
            priority=priority,
            risk_score=risk,
            churn_score=churn,
            complexity_score=complexity,
            fix_density_score=fix_density,
            recency_score=recency,
            reasons=reasons,
            stats=st,
        )

    def _reasons(
        self,
        st: FileStats,
        churn: float,
        complexity: float,
        fix_density: float,
        recency: float,
    ) -> list[str]:
        out: list[str] = []
        if not st.exists:
            out.append("FILE_DELETED")
        if churn >= 70:
            out.append("HIGH_CHURN")
        elif churn >= 40:
            out.append("MODERATE_CHURN")
        if complexity >= 70:
            out.append("LARGE_MODULE")
        elif complexity >= 40:
            out.append("MEDIUM_MODULE")
        if fix_density >= 60:
            out.append("BUG_PRONE")
        elif fix_density >= 30:
            out.append("FIX_HEAVY")
        if recency >= 70:
            out.append("RECENTLY_CHANGED")
        if st.distinct_authors >= 4:
            out.append("MULTI_AUTHOR")
        return out

    def _verdict(self, risk: float, st: FileStats) -> str:
        if not st.exists:
            return V_UNTRACKED
        if risk >= 70:
            return V_HOTSPOT
        if risk >= 50:
            return V_WARM
        if risk >= 30:
            return V_COOL
        return V_STABLE

    def _priority(self, verdict: str, fix_density: float, st: FileStats) -> int:
        if verdict == V_HOTSPOT:
            return P0
        if verdict == V_WARM:
            return P1
        if verdict == V_COOL:
            # Promote to P1 if a smaller module is unusually bug-prone
            if fix_density >= 60 and st.commits >= 3:
                return P1
            return P2
        return P3

    # ----- playbook / insights -----

    def _build_playbook(
        self,
        findings: list[HotspotFinding],
    ) -> list[PlaybookAction]:
        actions: list[PlaybookAction] = []
        hotspots = [f for f in findings if f.verdict == V_HOTSPOT]
        warm = [f for f in findings if f.verdict == V_WARM]
        bug_prone = [
            f for f in findings
            if f.fix_density_score >= 60 and f.stats.commits >= 3
        ]
        oversized = [
            f for f in findings
            if f.complexity_score >= 70 and f.stats.line_count >= 1500
        ]

        if hotspots:
            actions.append(PlaybookAction(
                id="REFACTOR_HOTSPOT",
                priority=P0,
                label="Refactor top hotspots",
                reason=(
                    f"{len(hotspots)} file(s) combine high churn, complexity, "
                    "and fix-density. Plan a focused refactor sprint."
                ),
                owner="engineering_lead",
                blast_radius=4,
                reversibility="low",
                related_paths=[f.path for f in hotspots[:5]],
            ))
            actions.append(PlaybookAction(
                id="ADD_REGRESSION_TESTS",
                priority=P0,
                label="Add regression tests for hotspots",
                reason=(
                    "Hotspot files change often and have a history of fixes; "
                    "lock current behavior with new tests before refactoring."
                ),
                owner="qa",
                blast_radius=2,
                reversibility="high",
                related_paths=[f.path for f in hotspots[:5]],
            ))

        if bug_prone:
            actions.append(PlaybookAction(
                id="AUDIT_FIX_DENSITY",
                priority=P1,
                label="Audit bug-prone modules",
                reason=(
                    f"{len(bug_prone)} file(s) have a fix-commit ratio > 40%. "
                    "Walk recent fix commits to find a common root cause."
                ),
                owner="engineering_lead",
                blast_radius=2,
                reversibility="high",
                related_paths=[f.path for f in bug_prone[:5]],
            ))

        if oversized:
            actions.append(PlaybookAction(
                id="SPLIT_OVERSIZED_MODULE",
                priority=P1,
                label="Split oversized modules",
                reason=(
                    f"{len(oversized)} module(s) exceed 1500 lines and churn "
                    "frequently. Splitting reduces blast radius."
                ),
                owner="engineering_lead",
                blast_radius=3,
                reversibility="medium",
                related_paths=[f.path for f in oversized[:5]],
            ))

        if warm:
            actions.append(PlaybookAction(
                id="FREEZE_AND_REVIEW",
                priority=P1,
                label="Require extra review on warm files",
                reason=(
                    f"{len(warm)} warm file(s) sit just below the hotspot "
                    "threshold; require a second reviewer for non-trivial "
                    "changes until risk recedes."
                ),
                owner="release_mgr",
                blast_radius=2,
                reversibility="high",
                related_paths=[f.path for f in warm[:5]],
            ))

        if self.risk_appetite == "cautious" and findings:
            actions.append(PlaybookAction(
                id="SCHEDULE_HOTSPOT_REVIEW",
                priority=P2,
                label="Schedule weekly hotspot review",
                reason=(
                    "Cautious mode: surface this report in a recurring review "
                    "so risk does not accumulate silently."
                ),
                owner="engineering_lead",
                blast_radius=1,
                reversibility="high",
                related_paths=[],
            ))

        if not actions:
            actions.append(PlaybookAction(
                id="HEALTHY_PORTFOLIO",
                priority=P3,
                label="No hotspots detected",
                reason=(
                    "Churn, complexity, and fix-density are all within "
                    "healthy bands for the lookback window."
                ),
                owner="engineering_lead",
                blast_radius=1,
                reversibility="high",
                related_paths=[],
            ))

        if self.risk_appetite == "aggressive":
            # Trim P3 noise when higher-priority actions exist
            has_high = any(a.priority <= P1 for a in actions)
            if has_high:
                actions = [a for a in actions if a.priority < P3]

        # Stable order: priority asc, id asc
        actions.sort(key=lambda a: (a.priority, a.id))
        return actions

    def _build_insights(
        self,
        findings: list[HotspotFinding],
        all_stats: dict[str, FileStats],
    ) -> list[str]:
        out: list[str] = []
        hotspots = [f for f in findings if f.verdict == V_HOTSPOT]
        if not all_stats:
            out.append("EMPTY_HISTORY")
            return out
        if hotspots:
            out.append(f"HOTSPOT_CLUSTER:{len(hotspots)}")
        bug_prone = [
            f for f in findings
            if f.fix_density_score >= 60 and f.stats.commits >= 3
        ]
        if bug_prone:
            out.append(f"BUG_DENSE_FILES:{len(bug_prone)}")
        recent = [f for f in findings if f.recency_score >= 70]
        if len(recent) >= 5:
            out.append(f"ACTIVE_DEVELOPMENT_ZONE:{len(recent)}")
        if findings and not hotspots:
            out.append("NO_HOTSPOTS")
        # Single-author concentration warning
        single = [
            f for f in findings
            if f.stats.distinct_authors <= 1 and f.stats.commits >= 5
        ]
        if len(single) >= 3:
            out.append(f"SINGLE_AUTHOR_CONCENTRATION:{len(single)}")
        if not out:
            out.append("PORTFOLIO_HEALTHY")
        return out

    def _portfolio_score(self, findings: list[HotspotFinding]) -> float:
        if not findings:
            return 0.0
        # Weighted: top file dominates, plus mean of remainder
        top = max(f.risk_score for f in findings)
        rest = [f.risk_score for f in findings if f.risk_score < top]
        mean_rest = sum(rest) / len(rest) if rest else top
        score = 0.6 * top + 0.4 * mean_rest
        return round(max(0.0, min(100.0, score)), 2)

    def _grade(self, portfolio: float, findings: list[HotspotFinding]) -> str:
        hotspots = sum(1 for f in findings if f.verdict == V_HOTSPOT)
        if hotspots >= 3 or portfolio >= 75:
            return "F"
        if hotspots >= 1 or portfolio >= 55:
            return "D"
        if portfolio >= 40:
            return "C"
        if portfolio >= 20:
            return "B"
        return "A"

    def _headline(
        self,
        grade: str,
        portfolio: float,
        findings: list[HotspotFinding],
    ) -> str:
        hotspots = sum(1 for f in findings if f.verdict == V_HOTSPOT)
        warm = sum(1 for f in findings if f.verdict == V_WARM)
        return (
            f"Hotspot grade {grade} | portfolio_risk={portfolio:.1f} | "
            f"hotspots={hotspots} warm={warm} analyzed={len(findings)} "
            f"(lookback={self.lookback_days}d, risk={self.risk_appetite})"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sauravhotspot",
        description=(
            "Agentic code-hotspot advisor: fuses git churn, complexity, and "
            "bug-fix density into a ranked refactor playbook."
        ),
    )
    p.add_argument("--root", default=".", help="project root (default: cwd)")
    p.add_argument(
        "--lookback-days", type=int, default=_DEFAULT_LOOKBACK_DAYS,
        help=f"history window in days (default: {_DEFAULT_LOOKBACK_DAYS})",
    )
    p.add_argument(
        "--top", type=int, default=_DEFAULT_TOP,
        help=f"max findings to report (default: {_DEFAULT_TOP})",
    )
    p.add_argument(
        "--risk", choices=_RISK_APPETITES, default="balanced",
        help="risk appetite (default: balanced)",
    )
    p.add_argument(
        "--include", nargs="*", default=None,
        help="optional path globs to include (POSIX-style)",
    )
    p.add_argument(
        "--exclude", nargs="*", default=None,
        help="extra path globs to exclude (POSIX-style)",
    )
    p.add_argument(
        "--format", choices=("text", "md", "json"), default="text",
        help="output format (default: text)",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    excludes: Optional[list[str]] = None
    if args.exclude is not None:
        # Start from defaults and extend. Use the module-level default tuple
        # so we don't have to instantiate a throwaway HotspotAdvisor (which
        # would resolve ``root`` and do extra work just to read constants).
        excludes = list(DEFAULT_EXCLUDE_GLOBS) + list(args.exclude)
    advisor = HotspotAdvisor(
        root=args.root,
        lookback_days=args.lookback_days,
        top=args.top,
        risk_appetite=args.risk,
        include_globs=args.include,
        exclude_globs=excludes,
    )
    report = advisor.analyze()
    # Windows console UTF-8 best-effort
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover - defensive
        pass
    print(report.format(args.format))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
