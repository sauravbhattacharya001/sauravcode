"""
sauravbusfactor - Agentic bus-factor / knowledge-concentration advisor.

Surfaces files whose history is dominated by a single author. A solo-owned
module is a project's biggest hidden risk: if that person leaves, takes
PTO, or burns out, nobody else can safely touch it. This module reads
``git log`` over a lookback window, computes per-file author distributions,
and recommends concrete dispersal actions (pair review, ghost commits,
documentation sprints, ownership rotation).

It is dependency-free (stdlib only) and **read-only** with respect to the
repository: it shells out to ``git`` for history but never writes or
mutates files.

Distinct from sauravhotspot (churn+complexity+fix-density), sauravcohort
(test coverage across the saurav* family), sauravflake (flaky tests),
and sauravstats (static size/complexity metrics): this module looks at
*who* edits each file, not *how often* or *how complex* it is.

Agentic behavior
----------------
- **Awareness**: walks ``git log --numstat --format=...`` over a lookback
  window to learn per-file commit counts and author identities.
- **Inference**: fuses top-author share, unique-author count, Gini
  concentration, recency, and absentee risk (top author hasn't committed
  recently) into a 0-100 ``bus_risk`` per file, then classifies into
  ``SOLO_OWNED`` / ``HIGH_RISK`` / ``CONCENTRATED`` / ``SHARED`` /
  ``HEALTHY`` / ``INACTIVE`` / ``UNTRACKED``.
- **Recommendation**: emits a deduped, P0-first playbook with owner,
  blast-radius and reversibility metadata.
- **Risk appetite**: ``cautious`` / ``balanced`` / ``aggressive`` shifts
  thresholds, multiplies risk, and trims low-priority noise.
- **Explainability**: every file finding carries structured ``reasons``
  (``SINGLE_AUTHOR``, ``TOP_DOMINANT``, ``ABSENT_OWNER``, etc.).

Public API
----------
- ``BusFactorAdvisor(root=".", lookback_days=180, top=20,
                     risk_appetite="balanced", include_globs=None,
                     exclude_globs=None, now_fn=None)``
- ``BusFactorAdvisor.analyze()`` -> ``BusFactorReport``
- ``BusFactorReport.format(fmt="text"|"md"|"json")``

CLI
---
::

    python -m sauravbusfactor --root . --lookback-days 180 --top 15 --format md
    python -m sauravbusfactor --risk cautious --format json
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import math
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

_DEFAULT_LOOKBACK_DAYS = 180
_DEFAULT_TOP = 20
_SOURCE_EXTS = {
    ".py", ".srv", ".js", ".ts", ".tsx", ".jsx", ".java", ".cs", ".c",
    ".cc", ".cpp", ".h", ".hpp", ".go", ".rs", ".rb", ".php", ".swift",
    ".kt", ".scala", ".ml", ".mli", ".dart",
}
_RISK_APPETITES = ("cautious", "balanced", "aggressive")

# Files we generally don't want to flag for bus-factor risk (data, lockfiles,
# generated assets, etc.).
_DEFAULT_EXCLUDE_GLOBS = (
    "**/.git/**", "**/node_modules/**", "**/__pycache__/**",
    "**/*.min.js", "**/*.lock", "**/package-lock.json", "**/poetry.lock",
    "**/dist/**", "**/build/**", "**/.venv/**", "**/venv/**",
)

# Owner -> action mapping for the playbook. Centralised so tests can assert
# the table stays consistent across releases.
_PLAYBOOK_OWNERS = {
    "ASSIGN_BACKUP_OWNER": "engineering_lead",
    "SCHEDULE_PAIR_REVIEW": "tech_lead",
    "DOCUMENT_TRIBAL_KNOWLEDGE": "owner_author",
    "REQUIRE_REVIEW_FROM_NEW_AUTHOR": "tech_lead",
    "ROTATE_OWNERSHIP": "engineering_lead",
    "REVIVE_ABSENT_OWNER_MODULE": "engineering_lead",
    "SCHEDULE_KNOWLEDGE_AUDIT": "engineering_lead",
    "MAINTAIN_HEALTHY_DISTRIBUTION": "engineering_lead",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AuthorContribution:
    """Per-author commit/line stats for a single file."""

    author: str
    commits: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    last_commit_iso: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "author": self.author,
            "commits": self.commits,
            "lines_added": self.lines_added,
            "lines_removed": self.lines_removed,
            "last_commit_iso": self.last_commit_iso,
        }


@dataclass
class FileFinding:
    """Per-file bus-factor finding."""

    path: str
    verdict: str
    priority: str  # P0..P3
    bus_risk: int  # 0..100
    top_author: Optional[str]
    top_author_share: float  # 0..1
    unique_authors: int
    total_commits: int
    gini: float  # 0..1, 1 = fully concentrated
    days_since_top_author_commit: Optional[int]
    days_since_any_commit: Optional[int]
    reasons: list[str] = field(default_factory=list)
    contributions: list[AuthorContribution] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "verdict": self.verdict,
            "priority": self.priority,
            "bus_risk": self.bus_risk,
            "top_author": self.top_author,
            "top_author_share": round(self.top_author_share, 4),
            "unique_authors": self.unique_authors,
            "total_commits": self.total_commits,
            "gini": round(self.gini, 4),
            "days_since_top_author_commit": self.days_since_top_author_commit,
            "days_since_any_commit": self.days_since_any_commit,
            "reasons": list(self.reasons),
            "contributions": [c.to_dict() for c in self.contributions],
        }


@dataclass
class PlaybookAction:
    id: str
    priority: str
    label: str
    reason: str
    owner: str
    blast_radius: int  # 1..5
    reversibility: str  # low/medium/high
    file_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BusFactorReport:
    grade: str
    portfolio_risk: int
    headline: str
    findings: list[FileFinding] = field(default_factory=list)
    playbook: list[PlaybookAction] = field(default_factory=list)
    insights: list[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    risk_appetite: str = "balanced"
    lookback_days: int = _DEFAULT_LOOKBACK_DAYS
    generated_at_iso: str = ""

    def to_dict(self) -> dict:
        return {
            "grade": self.grade,
            "portfolio_risk": self.portfolio_risk,
            "headline": self.headline,
            "summary": dict(self.summary),
            "findings": [f.to_dict() for f in self.findings],
            "playbook": [p.to_dict() for p in self.playbook],
            "insights": list(self.insights),
            "risk_appetite": self.risk_appetite,
            "lookback_days": self.lookback_days,
            "generated_at_iso": self.generated_at_iso,
        }

    def format(self, fmt: str = "text") -> str:
        fmt = fmt.lower()
        if fmt == "json":
            return json.dumps(self.to_dict(), indent=2, sort_keys=True, default=str)
        if fmt in ("md", "markdown"):
            return _render_markdown(self)
        if fmt == "text":
            return _render_text(self)
        raise ValueError(f"unknown format: {fmt}")


# ---------------------------------------------------------------------------
# Git history collection
# ---------------------------------------------------------------------------

def _run_git(args: list[str], cwd: str) -> str:
    """Run git with the given args. Returns stdout text or raises CalledProcessError."""
    proc = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.stdout


_LOG_FORMAT = "__COMMIT__%H%x09%an%x09%ae%x09%aI"


def _collect_git_history(root: str, since_iso: str) -> dict[str, dict[str, AuthorContribution]]:
    """Walk git log --numstat. Returns {path: {author: AuthorContribution}}.

    On any failure (no git, not a repo, etc.) returns an empty dict so the
    advisor degrades gracefully into the UNTRACKED case.
    """
    try:
        out = _run_git(
            [
                "log",
                f"--since={since_iso}",
                "--no-merges",
                "--numstat",
                f"--format={_LOG_FORMAT}",
            ],
            cwd=root,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}

    by_file: dict[str, dict[str, AuthorContribution]] = {}
    cur_author: Optional[str] = None
    cur_date: Optional[str] = None
    cur_sha: Optional[str] = None
    seen_commit_for_file: set[tuple[str, str, str]] = set()

    for raw_line in out.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        if line.startswith("__COMMIT__"):
            try:
                _, payload = line.split("__COMMIT__", 1)
                parts = payload.split("\t")
                cur_sha = parts[0]
                cur_author = parts[1] if len(parts) > 1 else ""
                cur_date = parts[3] if len(parts) > 3 else None
            except Exception:
                cur_sha = cur_author = cur_date = None
            continue
        if cur_author is None:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added_s, removed_s, path = parts[0], parts[1], parts[2]
        # Binary file rows are marked with "-". Skip them.
        try:
            added = 0 if added_s == "-" else int(added_s)
        except ValueError:
            added = 0
        try:
            removed = 0 if removed_s == "-" else int(removed_s)
        except ValueError:
            removed = 0
        # Rename rows look like "old => new" or "{a => b}/foo". Normalise to
        # the post-rename path.
        path = _normalise_rename(path)
        file_authors = by_file.setdefault(path, {})
        contrib = file_authors.get(cur_author)
        if contrib is None:
            contrib = AuthorContribution(author=cur_author)
            file_authors[cur_author] = contrib
        contrib.lines_added += added
        contrib.lines_removed += removed
        # Count one commit per (file, author, sha) tuple even if the rename
        # bookkeeping produces multiple rows.
        key = (path, cur_author, cur_sha or "")
        if key not in seen_commit_for_file:
            contrib.commits += 1
            seen_commit_for_file.add(key)
        if cur_date and (contrib.last_commit_iso is None or cur_date > contrib.last_commit_iso):
            contrib.last_commit_iso = cur_date

    return by_file


def _normalise_rename(path: str) -> str:
    """Collapse git's ``a => b`` rename notation to the post-rename path."""
    if "=>" not in path:
        return path
    # Handle "{old => new}/sub" style first
    if "{" in path and "}" in path:
        try:
            pre, rest = path.split("{", 1)
            inner, post = rest.split("}", 1)
            _, new = inner.split("=>", 1)
            return (pre + new.strip() + post).replace("//", "/")
        except ValueError:
            pass
    # Plain "old => new"
    try:
        _, new = path.split("=>", 1)
        return new.strip()
    except ValueError:
        return path


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _gini(values: list[int]) -> float:
    """Standard Gini coefficient. Empty/zero -> 0.0; single positive -> 1.0."""
    nonneg = [v for v in values if v >= 0]
    n = len(nonneg)
    total = sum(nonneg)
    if n == 0 or total <= 0:
        return 0.0
    if n == 1:
        return 1.0
    sorted_vals = sorted(nonneg)
    cum = 0.0
    for i, v in enumerate(sorted_vals, start=1):
        cum += i * v
    return max(0.0, min(1.0, (2.0 * cum) / (n * total) - (n + 1.0) / n))


def _appetite_mult(appetite: str) -> float:
    return {"cautious": 1.15, "balanced": 1.0, "aggressive": 0.85}[appetite]


def _days_between(iso_a: Optional[str], now: datetime) -> Optional[int]:
    if not iso_a:
        return None
    try:
        # git's --format=%aI is ISO 8601 with timezone offset
        dt = datetime.fromisoformat(iso_a.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    return max(0, int(delta.total_seconds() // 86400))


# ---------------------------------------------------------------------------
# Verdict + score derivation
# ---------------------------------------------------------------------------

def _classify_file(
    path: str,
    authors: dict[str, AuthorContribution],
    now: datetime,
    appetite: str,
) -> FileFinding:
    contribs = sorted(
        authors.values(),
        key=lambda c: (-c.commits, -(c.lines_added + c.lines_removed), c.author),
    )
    total_commits = sum(c.commits for c in contribs)
    unique = len(contribs)

    if total_commits == 0 or unique == 0:
        return FileFinding(
            path=path,
            verdict="UNTRACKED",
            priority="P3",
            bus_risk=0,
            top_author=None,
            top_author_share=0.0,
            unique_authors=0,
            total_commits=0,
            gini=0.0,
            days_since_top_author_commit=None,
            days_since_any_commit=None,
            reasons=["NO_HISTORY_IN_WINDOW"],
            contributions=[],
        )

    top = contribs[0]
    top_share = top.commits / total_commits
    gini = _gini([c.commits for c in contribs])
    last_overall_iso = max((c.last_commit_iso for c in contribs if c.last_commit_iso), default=None)
    days_since_any = _days_between(last_overall_iso, now)
    days_since_top = _days_between(top.last_commit_iso, now)

    # Base score: top-author share + concentration + low headcount penalty.
    base = 0.0
    reasons: list[str] = []

    if unique == 1:
        base += 65
        reasons.append("SINGLE_AUTHOR")
    elif unique == 2:
        base += 35
        reasons.append("TWO_AUTHORS_ONLY")

    if top_share >= 0.85:
        base += 25
        reasons.append("TOP_DOMINANT")
    elif top_share >= 0.65:
        base += 15
        reasons.append("TOP_CONCENTRATED")

    if gini >= 0.7 and unique >= 3:
        base += 10
        reasons.append("HIGH_GINI")

    # Absent-owner penalty: top author hasn't committed in a long time.
    if days_since_top is not None and days_since_top >= 120:
        base += 12
        reasons.append("ABSENT_OWNER")
    elif days_since_top is not None and days_since_top >= 60:
        base += 6
        reasons.append("STALE_OWNER")

    # Activity dampener: file hasn't moved in ages -> lower risk.
    inactive = days_since_any is not None and days_since_any >= 180
    if inactive:
        base -= 10
        reasons.append("INACTIVE_FILE")

    # Volume bonus: lots of commits make the concentration matter more.
    if total_commits >= 20 and top_share >= 0.6:
        base += 5
        reasons.append("HIGH_VOLUME_CONCENTRATED")

    risk = max(0.0, min(100.0, base)) * _appetite_mult(appetite)
    risk = int(round(max(0.0, min(100.0, risk))))

    # Verdict ladder.
    if inactive and unique == 1:
        verdict, priority = "INACTIVE", "P3"
    elif unique == 1 and total_commits >= 3:
        verdict, priority = "SOLO_OWNED", "P0"
    elif top_share >= 0.85 and total_commits >= 5:
        verdict, priority = "HIGH_RISK", "P0"
    elif top_share >= 0.65:
        verdict, priority = "CONCENTRATED", "P1"
    elif top_share >= 0.40:
        verdict, priority = "SHARED", "P2"
    else:
        verdict, priority = "HEALTHY", "P3"

    # Aggressive trims SHARED to P3 unless really dominant.
    if appetite == "aggressive" and verdict == "SHARED" and risk < 25:
        priority = "P3"
    # Cautious bumps SHARED-with-stale-owner to P1.
    if appetite == "cautious" and verdict == "SHARED" and "ABSENT_OWNER" in reasons:
        priority = "P1"

    return FileFinding(
        path=path,
        verdict=verdict,
        priority=priority,
        bus_risk=risk,
        top_author=top.author,
        top_author_share=top_share,
        unique_authors=unique,
        total_commits=total_commits,
        gini=gini,
        days_since_top_author_commit=days_since_top,
        days_since_any_commit=days_since_any,
        reasons=reasons,
        contributions=contribs[:5],  # cap for readability
    )


# ---------------------------------------------------------------------------
# Playbook + insights
# ---------------------------------------------------------------------------

def _build_playbook(
    findings: list[FileFinding],
    appetite: str,
) -> list[PlaybookAction]:
    actions: list[PlaybookAction] = []

    solo = [f for f in findings if f.verdict == "SOLO_OWNED"]
    high = [f for f in findings if f.verdict == "HIGH_RISK"]
    concentrated = [f for f in findings if f.verdict == "CONCENTRATED"]
    absent = [f for f in findings if "ABSENT_OWNER" in f.reasons or "STALE_OWNER" in f.reasons]

    if solo:
        actions.append(PlaybookAction(
            id="ASSIGN_BACKUP_OWNER",
            priority="P0",
            label="Assign a backup owner to every solo-owned module",
            reason=f"{len(solo)} file(s) have a single author in the lookback window",
            owner=_PLAYBOOK_OWNERS["ASSIGN_BACKUP_OWNER"],
            blast_radius=3,
            reversibility="high",
            file_paths=[f.path for f in solo[:10]],
        ))

    if high or solo:
        targets = (high + solo)[:10]
        actions.append(PlaybookAction(
            id="SCHEDULE_PAIR_REVIEW",
            priority="P0",
            label="Schedule pair-review sessions on the highest-risk modules",
            reason="Spread tacit knowledge by pairing the owner with at least one other contributor",
            owner=_PLAYBOOK_OWNERS["SCHEDULE_PAIR_REVIEW"],
            blast_radius=2,
            reversibility="high",
            file_paths=[f.path for f in targets],
        ))

    if high or solo:
        actions.append(PlaybookAction(
            id="DOCUMENT_TRIBAL_KNOWLEDGE",
            priority="P1",
            label="Have current owner write a design/runbook doc per hotspot",
            reason="Capture undocumented decisions before the owner is unavailable",
            owner=_PLAYBOOK_OWNERS["DOCUMENT_TRIBAL_KNOWLEDGE"],
            blast_radius=1,
            reversibility="high",
            file_paths=[f.path for f in (high + solo)[:10]],
        ))

    if concentrated:
        actions.append(PlaybookAction(
            id="REQUIRE_REVIEW_FROM_NEW_AUTHOR",
            priority="P1",
            label="Require a non-owner reviewer on every PR touching concentrated files",
            reason=f"{len(concentrated)} file(s) have >=65% top-author share",
            owner=_PLAYBOOK_OWNERS["REQUIRE_REVIEW_FROM_NEW_AUTHOR"],
            blast_radius=2,
            reversibility="high",
            file_paths=[f.path for f in concentrated[:10]],
        ))

    if absent:
        actions.append(PlaybookAction(
            id="REVIVE_ABSENT_OWNER_MODULE",
            priority="P1",
            label="Confirm staffing for modules whose top author has gone quiet",
            reason=f"{len(absent)} file(s) have an absent or stale owner",
            owner=_PLAYBOOK_OWNERS["REVIVE_ABSENT_OWNER_MODULE"],
            blast_radius=3,
            reversibility="high",
            file_paths=[f.path for f in absent[:10]],
        ))

    if (len(solo) + len(high)) >= 5:
        actions.append(PlaybookAction(
            id="ROTATE_OWNERSHIP",
            priority="P2",
            label="Plan a quarterly ownership rotation across high-risk modules",
            reason="Multiple modules carry single-owner risk; institutionalise rotation",
            owner=_PLAYBOOK_OWNERS["ROTATE_OWNERSHIP"],
            blast_radius=4,
            reversibility="high",
            file_paths=[f.path for f in (solo + high)[:10]],
        ))

    if appetite == "cautious":
        actions.append(PlaybookAction(
            id="SCHEDULE_KNOWLEDGE_AUDIT",
            priority="P2",
            label="Schedule a recurring knowledge-distribution audit",
            reason="Cautious appetite: keep recurring visibility on bus-factor risk",
            owner=_PLAYBOOK_OWNERS["SCHEDULE_KNOWLEDGE_AUDIT"],
            blast_radius=1,
            reversibility="high",
            file_paths=[],
        ))

    if not actions:
        actions.append(PlaybookAction(
            id="MAINTAIN_HEALTHY_DISTRIBUTION",
            priority="P3",
            label="Knowledge looks well-distributed; keep monitoring",
            reason="No solo-owned or highly concentrated modules detected",
            owner=_PLAYBOOK_OWNERS["MAINTAIN_HEALTHY_DISTRIBUTION"],
            blast_radius=1,
            reversibility="high",
            file_paths=[],
        ))

    if appetite == "aggressive":
        actions = [a for a in actions if not (a.priority == "P3" and any(b.priority in ("P0", "P1") for b in actions))]
        actions = [a for a in actions if not (a.id == "ROTATE_OWNERSHIP" and not any(b.priority == "P0" for b in actions))]

    # Deduplicate by id, keep highest priority instance.
    seen: dict[str, PlaybookAction] = {}
    prio_rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    for a in actions:
        prev = seen.get(a.id)
        if prev is None or prio_rank[a.priority] < prio_rank[prev.priority]:
            seen[a.id] = a
    return sorted(seen.values(), key=lambda x: (prio_rank[x.priority], x.id))


def _build_insights(findings: list[FileFinding], summary: dict) -> list[str]:
    insights: list[str] = []
    solo = summary.get("solo_owned", 0)
    high = summary.get("high_risk", 0)
    if solo == 0 and high == 0 and summary.get("total_files", 0) > 0:
        insights.append("HEALTHY_DISTRIBUTION")
    if solo >= 1:
        insights.append(f"BUS_FACTOR_ONE:{solo}")
    if high >= 1:
        insights.append(f"HIGH_RISK_MODULES:{high}")
    # Author concentration across all flagged files.
    top_author_counts: dict[str, int] = {}
    for f in findings:
        if f.top_author and f.priority in ("P0", "P1"):
            top_author_counts[f.top_author] = top_author_counts.get(f.top_author, 0) + 1
    if top_author_counts:
        dominant = max(top_author_counts.items(), key=lambda kv: (kv[1], kv[0]))
        if dominant[1] >= 3:
            insights.append(f"DOMINANT_AUTHOR:{dominant[0]}={dominant[1]}")
    absent = sum(1 for f in findings if "ABSENT_OWNER" in f.reasons)
    if absent >= 2:
        insights.append(f"ABSENT_OWNER_CLUSTER:{absent}")
    if summary.get("total_files", 0) == 0:
        insights.append("NO_GIT_HISTORY")
    return insights


# ---------------------------------------------------------------------------
# Advisor
# ---------------------------------------------------------------------------

class BusFactorAdvisor:
    def __init__(
        self,
        root: str | Path = ".",
        lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
        top: int = _DEFAULT_TOP,
        risk_appetite: str = "balanced",
        include_globs: Optional[Iterable[str]] = None,
        exclude_globs: Optional[Iterable[str]] = None,
        now_fn: Optional[Callable[[], datetime]] = None,
        history_fn: Optional[Callable[[str, str], dict]] = None,
    ) -> None:
        if risk_appetite not in _RISK_APPETITES:
            raise ValueError(f"risk_appetite must be one of {_RISK_APPETITES}")
        if lookback_days <= 0:
            raise ValueError("lookback_days must be positive")
        if top <= 0:
            raise ValueError("top must be positive")
        self.root = str(Path(root))
        self.lookback_days = lookback_days
        self.top = top
        self.risk_appetite = risk_appetite
        self.include_globs = tuple(include_globs) if include_globs else None
        self.exclude_globs = tuple(exclude_globs) if exclude_globs else _DEFAULT_EXCLUDE_GLOBS
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._history_fn = history_fn or _collect_git_history

    @staticmethod
    def _glob_match(path: str, pattern: str) -> bool:
        # fnmatch doesn't treat '**' specially. Approximate by matching the
        # raw pattern and by stripping leading '**/' / trailing '/**'.
        if fnmatch.fnmatch(path, pattern):
            return True
        # **/x => x or */.../x
        if pattern.startswith("**/"):
            suffix = pattern[3:]
            if fnmatch.fnmatch(path, suffix):
                return True
            # Match against any tail of the path segments.
            parts = path.split("/")
            for i in range(len(parts)):
                tail = "/".join(parts[i:])
                if fnmatch.fnmatch(tail, suffix):
                    return True
        # x/** => x or x/anything
        if pattern.endswith("/**"):
            prefix = pattern[:-3]
            if path == prefix or path.startswith(prefix + "/") or fnmatch.fnmatch(path, prefix):
                return True
        # Middle '**' (e.g. '**/vendor/**')
        if "/**/" in pattern:
            left, right = pattern.split("/**/", 1)
            # Strip leading **/ if present on left side.
            left_stripped = left[3:] if left.startswith("**/") else left
            parts = path.split("/")
            for i in range(len(parts)):
                for j in range(i, len(parts)):
                    mid = "/".join(parts[i:j + 1])
                    if mid == left_stripped or fnmatch.fnmatch(mid, left_stripped):
                        rest = "/".join(parts[j + 1:])
                        if BusFactorAdvisor._glob_match(rest, right) or fnmatch.fnmatch(rest, right):
                            return True
        return False

    def _match(self, path: str) -> bool:
        ext = Path(path).suffix.lower()
        if ext and ext not in _SOURCE_EXTS:
            return False
        if self.include_globs:
            if not any(self._glob_match(path, g) for g in self.include_globs):
                return False
        if any(self._glob_match(path, g) for g in self.exclude_globs):
            return False
        return True

    def analyze(self) -> BusFactorReport:
        now = self._now_fn()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        since_iso = (now.replace(microsecond=0) - _timedelta_days(self.lookback_days)).isoformat()
        history = self._history_fn(self.root, since_iso)

        findings: list[FileFinding] = []
        for path, authors in history.items():
            if not self._match(path):
                continue
            findings.append(_classify_file(path, authors, now, self.risk_appetite))

        # Sort: P0 first, then bus_risk desc, then path asc for determinism.
        prio_rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        findings.sort(key=lambda f: (prio_rank.get(f.priority, 9), -f.bus_risk, f.path))
        top_findings = findings[: self.top]

        summary = {
            "total_files": len(findings),
            "solo_owned": sum(1 for f in findings if f.verdict == "SOLO_OWNED"),
            "high_risk": sum(1 for f in findings if f.verdict == "HIGH_RISK"),
            "concentrated": sum(1 for f in findings if f.verdict == "CONCENTRATED"),
            "shared": sum(1 for f in findings if f.verdict == "SHARED"),
            "healthy": sum(1 for f in findings if f.verdict == "HEALTHY"),
            "inactive": sum(1 for f in findings if f.verdict == "INACTIVE"),
            "p0": sum(1 for f in findings if f.priority == "P0"),
            "p1": sum(1 for f in findings if f.priority == "P1"),
        }

        playbook = _build_playbook(findings, self.risk_appetite)
        insights = _build_insights(findings, summary)

        # Portfolio risk: weighted average of top 5 risks, clipped 0..100.
        top5 = sorted([f.bus_risk for f in findings], reverse=True)[:5]
        if top5:
            portfolio_risk = int(round(sum(top5) / len(top5)))
        else:
            portfolio_risk = 0

        grade = _grade(summary, portfolio_risk)
        headline = _build_headline(summary, grade, portfolio_risk)

        return BusFactorReport(
            grade=grade,
            portfolio_risk=portfolio_risk,
            headline=headline,
            findings=top_findings,
            playbook=playbook,
            insights=insights,
            summary=summary,
            risk_appetite=self.risk_appetite,
            lookback_days=self.lookback_days,
            generated_at_iso=now.isoformat(),
        )


def _grade(summary: dict, portfolio_risk: int) -> str:
    if summary.get("total_files", 0) == 0:
        return "A"
    if summary.get("solo_owned", 0) >= 3 or summary.get("p0", 0) >= 5 or portfolio_risk >= 80:
        return "F"
    if summary.get("solo_owned", 0) >= 1 or portfolio_risk >= 60:
        return "D"
    if summary.get("p1", 0) >= 3 or portfolio_risk >= 40:
        return "C"
    if summary.get("p1", 0) >= 1 or portfolio_risk >= 20:
        return "B"
    return "A"


def _build_headline(summary: dict, grade: str, portfolio_risk: int) -> str:
    return (
        f"VERDICT: grade={grade} files={summary.get('total_files', 0)} "
        f"solo={summary.get('solo_owned', 0)} high={summary.get('high_risk', 0)} "
        f"portfolio_risk={portfolio_risk}"
    )


def _timedelta_days(n: int):
    from datetime import timedelta
    return timedelta(days=n)


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def _render_text(report: BusFactorReport) -> str:
    lines = [
        report.headline,
        f"Lookback: {report.lookback_days}d | Appetite: {report.risk_appetite} | Generated: {report.generated_at_iso}",
        "",
        "Findings:",
    ]
    if not report.findings:
        lines.append("  (no files in scope)")
    for f in report.findings:
        share = f"{f.top_author_share * 100:.0f}%" if f.top_author else "n/a"
        owner = f.top_author or "unknown"
        lines.append(
            f"  [{f.priority}] {f.verdict:<13} risk={f.bus_risk:>3} {f.path}"
        )
        lines.append(
            f"        top={owner} share={share} authors={f.unique_authors} "
            f"commits={f.total_commits} reasons={','.join(f.reasons) or '-'}"
        )
    lines += ["", "Playbook:"]
    if not report.playbook:
        lines.append("  (no actions)")
    for a in report.playbook:
        lines.append(f"  [{a.priority}] {a.id} -> {a.owner} (blast={a.blast_radius}, rev={a.reversibility})")
        lines.append(f"        {a.label}")
        lines.append(f"        reason: {a.reason}")
    lines += ["", "Insights:"]
    if not report.insights:
        lines.append("  (none)")
    for ins in report.insights:
        lines.append(f"  - {ins}")
    return "\n".join(lines) + "\n"


def _render_markdown(report: BusFactorReport) -> str:
    lines = [
        f"# sauravbusfactor report",
        "",
        f"**{report.headline}**",
        "",
        f"- Lookback: {report.lookback_days} days",
        f"- Risk appetite: {report.risk_appetite}",
        f"- Generated: {report.generated_at_iso}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
    ]
    for k in ("total_files", "solo_owned", "high_risk", "concentrated", "shared", "healthy", "inactive", "p0", "p1"):
        lines.append(f"| {k} | {report.summary.get(k, 0)} |")
    lines.append(f"| portfolio_risk | {report.portfolio_risk} |")
    lines.append(f"| grade | {report.grade} |")
    lines += [
        "",
        "## Findings",
        "",
        "| Priority | Verdict | Risk | Path | Top author | Share | Authors | Commits | Reasons |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    if not report.findings:
        lines.append("| - | - | - | (no files) | - | - | - | - | - |")
    for f in report.findings:
        share = f"{f.top_author_share * 100:.0f}%" if f.top_author else "-"
        owner = (f.top_author or "-").replace("|", "/")
        path = f.path.replace("|", "/")
        reasons = ",".join(f.reasons) or "-"
        lines.append(
            f"| {f.priority} | {f.verdict} | {f.bus_risk} | `{path}` | {owner} | {share} | "
            f"{f.unique_authors} | {f.total_commits} | {reasons} |"
        )
    lines += ["", "## Playbook", "", "| Priority | Action | Owner | Blast | Reversibility | Reason |", "|---|---|---|---|---|---|"]
    if not report.playbook:
        lines.append("| - | (no actions) | - | - | - | - |")
    for a in report.playbook:
        lines.append(
            f"| {a.priority} | {a.id} | {a.owner} | {a.blast_radius} | {a.reversibility} | {a.reason} |"
        )
    lines += ["", "## Insights", ""]
    if not report.insights:
        lines.append("- (none)")
    else:
        for ins in report.insights:
            lines.append(f"- {ins}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sauravbusfactor",
        description="Agentic bus-factor / knowledge-concentration advisor.",
    )
    p.add_argument("--root", default=".", help="Path to the repo (default: cwd).")
    p.add_argument("--lookback-days", type=int, default=_DEFAULT_LOOKBACK_DAYS)
    p.add_argument("--top", type=int, default=_DEFAULT_TOP)
    p.add_argument("--risk", choices=_RISK_APPETITES, default="balanced", dest="risk_appetite")
    p.add_argument("--include", action="append", default=None, help="Glob to include (repeatable).")
    p.add_argument("--exclude", action="append", default=None, help="Glob to exclude (repeatable).")
    p.add_argument("--format", choices=("text", "md", "markdown", "json"), default="text")
    p.add_argument("--output", default=None, help="Write report to file instead of stdout.")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    # Windows UTF-8 stdout shim for emoji/markdown safety.
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    advisor = BusFactorAdvisor(
        root=args.root,
        lookback_days=args.lookback_days,
        top=args.top,
        risk_appetite=args.risk_appetite,
        include_globs=args.include,
        exclude_globs=args.exclude,
    )
    report = advisor.analyze()
    text = report.format(args.format)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
