#!/usr/bin/env python3
"""sauravchange - Agentic changelog / release-notes drafter for sauravcode.

Scans the git log between two refs (default: last tag -> HEAD) and produces a
classified, prioritised release-notes draft plus a pre-release readiness
playbook telling the author WHAT TO DO BEFORE TAGGING.

Sibling to ``sauravgate`` / ``sauravreview`` / ``sauravprioritize`` /
``sauravsmoke`` / ``sauravcoach``.

Public API
----------
- ``ChangelogAdvisor(root=".", from_ref=None, to_ref="HEAD",
                     risk_appetite="balanced", now=None, log_provider=None,
                     repo_provider=None)``
- ``ChangelogAdvisor.scan()`` -> ``ChangelogReport``
- ``ChangelogReport.to_text() / to_markdown() / to_json()``

CLI
---
::

    python sauravchange.py --root . --from v1.0.0 --to HEAD --format md
    python sauravchange.py --root . --risk cautious --output RELEASE_NOTES.md

Pure stdlib. No mutation of any repo state. Deterministic given a fixed
``now`` callable and pinned refs.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

_RISK_APPETITES = ("cautious", "balanced", "aggressive")

# Conventional-commit prefix -> canonical type
_CC_RE = re.compile(
    r"^(?P<type>feat|feature|fix|bugfix|perf|performance|refactor|docs?|"
    r"style|test|tests|build|ci|chore|revert|deprecate|sec|security)"
    r"(?:\((?P<scope>[^)]+)\))?(?P<bang>!)?:\s*(?P<rest>.+)$",
    re.IGNORECASE,
)

_BREAKING_TRAILER_RE = re.compile(r"BREAKING[ \-]CHANGE\s*:", re.IGNORECASE)
_BREAKING_WORDS_RE = re.compile(
    r"\b(breaking|incompatible|backwards?[- ]incompat|remove[ds]?\s+\w+\s+api|drop\s+support|"
    r"no longer supports?)\b",
    re.IGNORECASE,
)
_SECURITY_WORDS_RE = re.compile(
    r"\b(cve|vulnerab|exploit|rce|xss|csrf|ssrf|sql\s*injection|auth\s*bypass|"
    r"privilege\s*escalat|security\s+fix|secret\s+leak|sandbox\s+escape)\b",
    re.IGNORECASE,
)
_PERF_WORDS_RE = re.compile(
    r"\b(faster|speed[- ]?up|optimi[sz]e|throughput|latency|reduce\s+(?:memory|alloc|cpu))\b",
    re.IGNORECASE,
)
_FIX_WORDS_RE = re.compile(
    r"\b(fix(?:es|ed)?|bug|crash|hang|deadlock|race|leak|regression|panic|"
    r"resolves?|closes?\s+#\d+)\b",
    re.IGNORECASE,
)
_FEATURE_WORDS_RE = re.compile(
    r"\b(add(?:s|ed)?|introduce[ds]?|implement(?:s|ed)?|new\s+(?:command|api|flag|option|"
    r"endpoint|module)|support\s+for|enable[ds]?)\b",
    re.IGNORECASE,
)
_DEPRECATE_WORDS_RE = re.compile(r"\bdeprecat", re.IGNORECASE)
_DOCS_WORDS_RE = re.compile(r"\b(docs?|readme|changelog|tutorial|guide|comments?)\b", re.IGNORECASE)
_REVERT_RE = re.compile(r'^revert\b|^revert\s+"', re.IGNORECASE)
_MERGE_RE = re.compile(r"^Merge\s+(branch|pull request|remote-tracking)", re.IGNORECASE)
_ISSUE_RE = re.compile(r"#(\d+)")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class CommitInfo:
    sha: str
    subject: str
    body: str
    author: str
    timestamp: int  # unix seconds
    files: List[str] = field(default_factory=list)
    insertions: int = 0
    deletions: int = 0


@dataclass
class ChangelogEntry:
    sha: str
    short_sha: str
    subject: str
    verdict: str  # BREAKING/SECURITY/FEATURE/FIX/PERF/DEPRECATION/REFACTOR/DOCS/TEST/INTERNAL/REVERT/CHORE
    priority: str  # P0..P3
    user_impact: int  # 0..100
    type_label: str
    scope: Optional[str]
    breaking: bool
    reasons: List[Dict[str, object]] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    files_touched: int = 0
    diff_size: int = 0
    author: str = ""


@dataclass
class ChangelogReport:
    entries: List[ChangelogEntry]
    sections: Dict[str, List[ChangelogEntry]]
    headline: str
    grade: str  # A..F
    release_verdict: str  # READY/PILOT/HOLD/BLOCK
    suggested_bump: str  # major/minor/patch/none
    playbook: List[Dict[str, object]]
    insights: List[str]
    risk_appetite: str
    from_ref: Optional[str]
    to_ref: str
    generated_at: str
    summary: Dict[str, int]

    # -------------------- renderers --------------------

    def to_text(self) -> str:
        out: List[str] = []
        out.append(self.headline)
        out.append(
            f"Grade: {self.grade}   Verdict: {self.release_verdict}   "
            f"Suggested bump: {self.suggested_bump}   Risk: {self.risk_appetite}"
        )
        out.append(
            f"Range: {self.from_ref or '<root>'} .. {self.to_ref}    "
            f"Commits: {self.summary.get('total', 0)}"
        )
        out.append("")
        if not self.entries:
            out.append("(no commits in range)")
        else:
            for section_key in _SECTION_ORDER:
                items = self.sections.get(section_key, [])
                if not items:
                    continue
                out.append(f"## {_SECTION_TITLES[section_key]}")
                for e in items:
                    line = f"  [{e.priority}] ({e.short_sha}) {e.subject}"
                    if e.scope:
                        line += f"  [scope: {e.scope}]"
                    if e.breaking:
                        line += "  ⚠ BREAKING"
                    out.append(line)
                out.append("")
        if self.playbook:
            out.append("## Pre-release playbook")
            for a in self.playbook:
                out.append(
                    f"  [{a['priority']}] {a['label']} — {a['reason']} "
                    f"(owner={a['owner']}, blast={a['blast_radius']}, "
                    f"reversibility={a['reversibility']})"
                )
            out.append("")
        if self.insights:
            out.append("## Insights")
            for ins in self.insights:
                out.append(f"  - {ins}")
        return "\n".join(out).rstrip() + "\n"

    def to_markdown(self) -> str:
        out: List[str] = []
        out.append(f"# Release Notes Draft")
        out.append("")
        out.append(f"**{self.headline}**")
        out.append("")
        out.append(
            f"- Grade: **{self.grade}** | Verdict: **{self.release_verdict}** | "
            f"Suggested bump: **{self.suggested_bump}** | Risk appetite: `{self.risk_appetite}`"
        )
        out.append(f"- Range: `{self.from_ref or '<root>'} .. {self.to_ref}`")
        out.append(
            f"- Commits: {self.summary.get('total', 0)} "
            f"(breaking {self.summary.get('breaking', 0)}, "
            f"features {self.summary.get('feature', 0)}, "
            f"fixes {self.summary.get('fix', 0)}, "
            f"security {self.summary.get('security', 0)})"
        )
        out.append("")
        if not self.entries:
            out.append("_No commits in range._")
        else:
            for section_key in _SECTION_ORDER:
                items = self.sections.get(section_key, [])
                if not items:
                    continue
                out.append(f"## {_SECTION_TITLES[section_key]}")
                out.append("")
                for e in items:
                    bang = " ⚠ **BREAKING**" if e.breaking else ""
                    scope = f" _({e.scope})_" if e.scope else ""
                    issues = (
                        "  " + " ".join(f"#{i}" for i in e.issues) if e.issues else ""
                    )
                    out.append(
                        f"- **[{e.priority}]**{scope} {e.subject} "
                        f"`{e.short_sha}`{bang}{issues}"
                    )
                out.append("")
        out.append("## Pre-release playbook")
        out.append("")
        if not self.playbook:
            out.append("_Nothing required._")
        else:
            out.append("| Priority | Action | Reason | Owner | Blast | Reversibility |")
            out.append("|---|---|---|---|---|---|")
            for a in self.playbook:
                out.append(
                    f"| {a['priority']} | {a['label']} | {a['reason']} | "
                    f"{a['owner']} | {a['blast_radius']} | {a['reversibility']} |"
                )
        out.append("")
        out.append("## Insights")
        out.append("")
        if not self.insights:
            out.append("_None._")
        else:
            for ins in self.insights:
                out.append(f"- {ins}")
        out.append("")
        return "\n".join(out)

    def to_json(self) -> str:
        payload = {
            "headline": self.headline,
            "grade": self.grade,
            "release_verdict": self.release_verdict,
            "suggested_bump": self.suggested_bump,
            "risk_appetite": self.risk_appetite,
            "from_ref": self.from_ref,
            "to_ref": self.to_ref,
            "generated_at": self.generated_at,
            "summary": self.summary,
            "entries": [asdict(e) for e in self.entries],
            "sections": {
                k: [asdict(e) for e in v]
                for k, v in self.sections.items()
            },
            "playbook": self.playbook,
            "insights": self.insights,
        }
        return json.dumps(payload, sort_keys=True, indent=2, default=str)


_SECTION_ORDER = (
    "BREAKING",
    "SECURITY",
    "FEATURE",
    "FIX",
    "PERF",
    "DEPRECATION",
    "REFACTOR",
    "DOCS",
    "TEST",
    "INTERNAL",
    "REVERT",
    "CHORE",
)

_SECTION_TITLES = {
    "BREAKING": "💥 Breaking changes",
    "SECURITY": "🔐 Security",
    "FEATURE": "✨ Features",
    "FIX": "🐛 Bug fixes",
    "PERF": "⚡ Performance",
    "DEPRECATION": "⚠️ Deprecations",
    "REFACTOR": "♻️ Refactoring",
    "DOCS": "📝 Documentation",
    "TEST": "🧪 Tests",
    "INTERNAL": "🔧 Internal",
    "REVERT": "↩️ Reverts",
    "CHORE": "🧹 Chores",
}


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

def _run_git(args: Sequence[str], cwd: str) -> Tuple[int, str, str]:
    try:
        cp = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        return cp.returncode, cp.stdout or "", cp.stderr or ""
    except FileNotFoundError:
        return 127, "", "git not installed"


def default_repo_provider(root: str) -> Dict[str, object]:
    rc, out, _ = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=root)
    is_repo = rc == 0 and out.strip() == "true"
    if not is_repo:
        return {"is_repo": False, "last_tag": None}
    rc2, tag_out, _ = _run_git(["describe", "--tags", "--abbrev=0"], cwd=root)
    last_tag = tag_out.strip() if rc2 == 0 and tag_out.strip() else None
    return {"is_repo": True, "last_tag": last_tag}


_COMMIT_DELIM = "\x1eEOC\x1e"
_FIELD_DELIM = "\x1fFLD\x1f"


def default_log_provider(
    root: str,
    from_ref: Optional[str],
    to_ref: str,
) -> List[CommitInfo]:
    rev_range = f"{from_ref}..{to_ref}" if from_ref else to_ref
    fmt = _FIELD_DELIM.join(["%H", "%an", "%ct", "%s", "%b"]) + _COMMIT_DELIM
    rc, out, _ = _run_git(
        ["log", "--no-merges", "--numstat", f"--pretty=format:{fmt}", rev_range],
        cwd=root,
    )
    if rc != 0:
        return []
    commits: List[CommitInfo] = []
    # Each commit ends in _COMMIT_DELIM, followed by numstat lines, then next commit.
    chunks = out.split(_COMMIT_DELIM)
    for chunk in chunks:
        chunk = chunk.strip("\n\r ")
        if not chunk:
            continue
        # First line(s) up to numstat is the pretty format; split header & numstat.
        # Header is the first _FIELD_DELIM-joined block which may span newlines (%b).
        header_end = chunk.find(_FIELD_DELIM)
        if header_end < 0:
            continue
        # Reconstruct header by finding 4 _FIELD_DELIM separators (5 fields).
        # Then numstat follows after a trailing newline.
        parts = chunk.split(_FIELD_DELIM, 4)
        if len(parts) < 5:
            continue
        sha, author, ts_str, subject, rest = parts
        # ``rest`` is body + (maybe) blank line + numstat lines.
        rest_lines = rest.splitlines()
        body_lines: List[str] = []
        numstat_lines: List[str] = []
        in_numstat = False
        for line in rest_lines:
            if not in_numstat:
                # numstat lines look like "12\t3\tpath" or "-\t-\tbin/file"
                if re.match(r"^(\d+|-)\t(\d+|-)\t.+$", line):
                    in_numstat = True
                    numstat_lines.append(line)
                else:
                    body_lines.append(line)
            else:
                if line.strip():
                    numstat_lines.append(line)
        ins = 0
        dels = 0
        files: List[str] = []
        for ns in numstat_lines:
            try:
                a, b, path = ns.split("\t", 2)
                if a != "-":
                    ins += int(a)
                if b != "-":
                    dels += int(b)
                files.append(path)
            except (ValueError, IndexError):
                continue
        try:
            ts = int(ts_str)
        except ValueError:
            ts = 0
        commits.append(
            CommitInfo(
                sha=sha.strip(),
                subject=subject.strip(),
                body="\n".join(body_lines).strip(),
                author=author.strip(),
                timestamp=ts,
                files=files,
                insertions=ins,
                deletions=dels,
            )
        )
    return commits


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

_TYPE_TO_VERDICT = {
    "feat": "FEATURE",
    "feature": "FEATURE",
    "fix": "FIX",
    "bugfix": "FIX",
    "perf": "PERF",
    "performance": "PERF",
    "refactor": "REFACTOR",
    "doc": "DOCS",
    "docs": "DOCS",
    "style": "INTERNAL",
    "test": "TEST",
    "tests": "TEST",
    "build": "INTERNAL",
    "ci": "INTERNAL",
    "chore": "CHORE",
    "revert": "REVERT",
    "deprecate": "DEPRECATION",
    "sec": "SECURITY",
    "security": "SECURITY",
}


def _classify(commit: CommitInfo) -> Tuple[str, str, Optional[str], bool, List[Dict[str, object]]]:
    """Return (verdict, type_label, scope, breaking, reasons)."""
    reasons: List[Dict[str, object]] = []
    subj = commit.subject or ""
    body = commit.body or ""
    text = subj + "\n" + body

    scope: Optional[str] = None
    type_label = "other"
    verdict: Optional[str] = None
    breaking = False

    m = _CC_RE.match(subj)
    if m:
        raw_type = m.group("type").lower()
        scope = m.group("scope")
        bang = bool(m.group("bang"))
        type_label = raw_type
        verdict = _TYPE_TO_VERDICT.get(raw_type, "INTERNAL")
        if bang:
            breaking = True
            reasons.append({"code": "CC_BANG", "label": "Conventional-commit '!' marker", "weight": 60})
        reasons.append({"code": "CC_PARSED", "label": f"Conventional type: {raw_type}", "weight": 10})

    # BREAKING-CHANGE trailer / body keyword
    if _BREAKING_TRAILER_RE.search(text):
        breaking = True
        reasons.append({"code": "BREAKING_TRAILER", "label": "Body contains BREAKING CHANGE trailer", "weight": 80})
    elif _BREAKING_WORDS_RE.search(text) and verdict not in ("DOCS", "TEST", "CHORE"):
        # Heuristic — softer signal
        reasons.append({"code": "BREAKING_HINT", "label": "Subject/body mentions breaking change", "weight": 35})
        if verdict in (None, "INTERNAL", "REFACTOR", "FEATURE", "FIX"):
            breaking = True

    # Security wins over CC type
    if _SECURITY_WORDS_RE.search(text):
        verdict = "SECURITY"
        reasons.append({"code": "SECURITY_KEYWORD", "label": "Security-relevant keyword detected", "weight": 70})

    if _REVERT_RE.match(subj):
        verdict = "REVERT"
        type_label = "revert"
        reasons.append({"code": "REVERT", "label": "Revert commit", "weight": 40})

    if _DEPRECATE_WORDS_RE.search(text) and verdict not in ("BREAKING", "SECURITY"):
        verdict = "DEPRECATION"
        reasons.append({"code": "DEPRECATION_KEYWORD", "label": "Marks a deprecation", "weight": 35})

    if _PERF_WORDS_RE.search(text) and verdict in (None, "INTERNAL", "REFACTOR"):
        verdict = "PERF"
        reasons.append({"code": "PERF_KEYWORD", "label": "Performance improvement keywords", "weight": 25})

    if verdict is None:
        if _FIX_WORDS_RE.search(subj):
            verdict = "FIX"
            reasons.append({"code": "FIX_KEYWORD", "label": "Subject describes a fix", "weight": 25})
        elif _FEATURE_WORDS_RE.search(subj):
            verdict = "FEATURE"
            reasons.append({"code": "FEATURE_KEYWORD", "label": "Subject describes new functionality", "weight": 25})
        elif _DOCS_WORDS_RE.search(subj) and not _FIX_WORDS_RE.search(subj):
            verdict = "DOCS"
            reasons.append({"code": "DOCS_KEYWORD", "label": "Subject scoped to docs", "weight": 10})
        else:
            verdict = "INTERNAL"
            reasons.append({"code": "DEFAULT_INTERNAL", "label": "No user-facing signal detected", "weight": 5})

    if breaking:
        # When breaking and verdict is internal-ish, escalate to BREAKING section
        if verdict not in ("BREAKING", "SECURITY"):
            verdict_section = "BREAKING"
        else:
            verdict_section = verdict
    else:
        verdict_section = verdict

    return verdict_section, type_label, scope, breaking, reasons


def _user_impact(
    verdict: str,
    breaking: bool,
    diff_size: int,
    files_touched: int,
    reasons: List[Dict[str, object]],
    risk_mult: float,
) -> int:
    base = {
        "BREAKING": 90,
        "SECURITY": 85,
        "FEATURE": 60,
        "FIX": 50,
        "PERF": 40,
        "DEPRECATION": 55,
        "REFACTOR": 20,
        "DOCS": 15,
        "TEST": 10,
        "INTERNAL": 8,
        "REVERT": 45,
        "CHORE": 5,
    }.get(verdict, 10)
    if breaking and verdict != "BREAKING":
        base += 20
    # Diff-size bump (scales user-visibility a bit)
    if diff_size >= 1000:
        base += 8
    elif diff_size >= 300:
        base += 4
    if files_touched >= 15:
        base += 5
    # Modulate
    score = int(round(base * risk_mult))
    return max(0, min(100, score))


def _priority_from_impact(verdict: str, impact: int) -> str:
    if verdict in ("BREAKING", "SECURITY") or impact >= 75:
        return "P0"
    if impact >= 55 or verdict in ("FEATURE", "DEPRECATION"):
        return "P1"
    if impact >= 30 or verdict in ("FIX", "PERF", "REVERT"):
        return "P2"
    return "P3"


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class ChangelogAdvisor:
    def __init__(
        self,
        root: str = ".",
        from_ref: Optional[str] = None,
        to_ref: str = "HEAD",
        risk_appetite: str = "balanced",
        now: Optional[Callable[[], datetime]] = None,
        log_provider: Optional[Callable[[str, Optional[str], str], List[CommitInfo]]] = None,
        repo_provider: Optional[Callable[[str], Dict[str, object]]] = None,
    ):
        if risk_appetite not in _RISK_APPETITES:
            raise ValueError(
                f"risk_appetite must be one of {_RISK_APPETITES}, got {risk_appetite!r}"
            )
        self.root = root
        self.from_ref = from_ref
        self.to_ref = to_ref
        self.risk_appetite = risk_appetite
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._log_provider = log_provider or default_log_provider
        self._repo_provider = repo_provider or default_repo_provider

    # -------------------- public --------------------

    def scan(self) -> ChangelogReport:
        repo_info = self._repo_provider(self.root)
        insights: List[str] = []
        if not repo_info.get("is_repo", False):
            return self._empty_report(
                headline="Not a git repository: nothing to draft.",
                insights=["not_a_git_repository"],
            )

        from_ref = self.from_ref
        auto_from = False
        if from_ref is None and repo_info.get("last_tag"):
            from_ref = str(repo_info["last_tag"])
            auto_from = True

        commits = self._log_provider(self.root, from_ref, self.to_ref)
        if auto_from:
            insights.append(f"auto-selected from_ref: previous tag '{from_ref}'")

        if not commits:
            return self._empty_report(
                headline=(
                    f"No commits in {from_ref or '<root>'}..{self.to_ref}: "
                    "nothing to release."
                ),
                from_ref=from_ref,
                insights=insights + ["empty_range"],
            )

        risk_mult = {"cautious": 1.10, "balanced": 1.0, "aggressive": 0.90}[
            self.risk_appetite
        ]

        entries: List[ChangelogEntry] = []
        for c in commits:
            verdict, type_label, scope, breaking, reasons = _classify(c)
            diff_size = c.insertions + c.deletions
            files_touched = len(c.files)
            impact = _user_impact(
                verdict, breaking, diff_size, files_touched, reasons, risk_mult
            )
            # Large diff signal
            if diff_size >= 1000:
                reasons.append(
                    {"code": "LARGE_DIFF", "label": f"{diff_size} LOC across {files_touched} files", "weight": 30}
                )
            # No-tests heuristic: feature touches src but no test files
            if verdict in ("FEATURE", "FIX") and files_touched >= 1:
                has_test_change = any(
                    "test" in p.lower() or p.lower().startswith("tests/")
                    for p in c.files
                )
                has_src_change = any(
                    p.lower().endswith((".py", ".srv", ".js", ".ts", ".java", ".cs"))
                    and "test" not in p.lower()
                    for p in c.files
                )
                if has_src_change and not has_test_change:
                    reasons.append(
                        {"code": "NO_TEST_FILES_TOUCHED", "label": "Commit changes code but no test files", "weight": 25}
                    )

            priority = _priority_from_impact(verdict, impact)
            # Risk-appetite priority shifts
            if self.risk_appetite == "cautious" and verdict in ("DEPRECATION", "REFACTOR") and priority == "P3":
                priority = "P2"
            if self.risk_appetite == "aggressive" and priority == "P2" and verdict in ("REFACTOR", "DOCS", "TEST"):
                priority = "P3"

            issues = sorted({m for m in _ISSUE_RE.findall(c.subject + " " + c.body)})

            entries.append(
                ChangelogEntry(
                    sha=c.sha,
                    short_sha=c.sha[:7],
                    subject=c.subject,
                    verdict=verdict,
                    priority=priority,
                    user_impact=impact,
                    type_label=type_label,
                    scope=scope,
                    breaking=breaking,
                    reasons=reasons,
                    issues=issues,
                    files_touched=files_touched,
                    diff_size=diff_size,
                    author=c.author,
                )
            )

        # Sort each section by priority (P0 first) then user_impact desc then sha
        entries_sorted = sorted(
            entries,
            key=lambda e: (_PRI_RANK[e.priority], -e.user_impact, e.sha),
        )

        sections: Dict[str, List[ChangelogEntry]] = {k: [] for k in _SECTION_ORDER}
        for e in entries_sorted:
            sections.setdefault(e.verdict, []).append(e)

        summary = self._summarize(entries)
        suggested_bump = self._suggest_bump(summary)
        release_verdict, grade = self._release_verdict_and_grade(summary, suggested_bump)
        playbook = self._build_playbook(entries, summary, suggested_bump, release_verdict)
        cross_insights = self._build_insights(entries, summary)
        insights.extend(cross_insights)

        headline = (
            f"Release draft: {summary['total']} commits "
            f"({summary['feature']} feat / {summary['fix']} fix / "
            f"{summary['breaking']} breaking / {summary['security']} security) "
            f"→ bump '{suggested_bump}', verdict {release_verdict}, grade {grade}."
        )

        return ChangelogReport(
            entries=entries_sorted,
            sections={k: sections.get(k, []) for k in _SECTION_ORDER},
            headline=headline,
            grade=grade,
            release_verdict=release_verdict,
            suggested_bump=suggested_bump,
            playbook=playbook,
            insights=insights,
            risk_appetite=self.risk_appetite,
            from_ref=from_ref,
            to_ref=self.to_ref,
            generated_at=self._now().isoformat(),
            summary=summary,
        )

    # -------------------- internals --------------------

    def _empty_report(
        self,
        headline: str,
        from_ref: Optional[str] = None,
        insights: Optional[List[str]] = None,
    ) -> ChangelogReport:
        return ChangelogReport(
            entries=[],
            sections={k: [] for k in _SECTION_ORDER},
            headline=headline,
            grade="A",
            release_verdict="READY",
            suggested_bump="none",
            playbook=[],
            insights=list(insights or []),
            risk_appetite=self.risk_appetite,
            from_ref=from_ref,
            to_ref=self.to_ref,
            generated_at=self._now().isoformat(),
            summary={
                "total": 0, "breaking": 0, "security": 0, "feature": 0, "fix": 0,
                "perf": 0, "deprecation": 0, "refactor": 0, "docs": 0,
                "test": 0, "internal": 0, "revert": 0, "chore": 0,
            },
        )

    def _summarize(self, entries: Sequence[ChangelogEntry]) -> Dict[str, int]:
        summary = {
            "total": len(entries),
            "breaking": 0, "security": 0, "feature": 0, "fix": 0, "perf": 0,
            "deprecation": 0, "refactor": 0, "docs": 0, "test": 0,
            "internal": 0, "revert": 0, "chore": 0,
            "no_test_files_touched": 0, "large_diff": 0,
        }
        for e in entries:
            summary[e.verdict.lower()] = summary.get(e.verdict.lower(), 0) + 1
            for r in e.reasons:
                if r.get("code") == "NO_TEST_FILES_TOUCHED":
                    summary["no_test_files_touched"] += 1
                if r.get("code") == "LARGE_DIFF":
                    summary["large_diff"] += 1
        return summary

    def _suggest_bump(self, summary: Dict[str, int]) -> str:
        if summary["total"] == 0:
            return "none"
        if summary["breaking"] >= 1:
            return "major"
        if summary["feature"] >= 1 or summary["deprecation"] >= 1:
            return "minor"
        if summary["fix"] >= 1 or summary["perf"] >= 1 or summary["security"] >= 1:
            return "patch"
        return "patch"

    def _release_verdict_and_grade(
        self, summary: Dict[str, int], bump: str
    ) -> Tuple[str, str]:
        # Risk score
        risk = 0
        risk += 30 * summary["breaking"]
        risk += 20 * summary["security"]
        risk += 10 * summary["no_test_files_touched"]
        risk += 5 * summary["large_diff"]
        if self.risk_appetite == "cautious":
            risk = int(round(risk * 1.15))
        elif self.risk_appetite == "aggressive":
            risk = int(round(risk * 0.85))

        if summary["total"] == 0:
            return "READY", "A"

        if summary["breaking"] >= 2 and summary["no_test_files_touched"] >= 2:
            return "BLOCK", "F"
        if risk >= 80:
            return "HOLD", "D"
        if risk >= 50 or summary["breaking"] >= 1:
            return "PILOT", "C"
        if risk >= 25:
            return "PILOT", "B"
        return "READY", "A"

    def _build_playbook(
        self,
        entries: Sequence[ChangelogEntry],
        summary: Dict[str, int],
        bump: str,
        verdict: str,
    ) -> List[Dict[str, object]]:
        actions: List[Dict[str, object]] = []

        if summary["breaking"] >= 1:
            actions.append({
                "id": "ADD_MIGRATION_GUIDE",
                "priority": "P0",
                "label": "Write migration guide for breaking changes",
                "reason": (
                    f"{summary['breaking']} breaking commit(s) detected; users must be "
                    "told what changed and how to upgrade."
                ),
                "owner": "release_manager",
                "blast_radius": 5,
                "reversibility": "low",
            })
            actions.append({
                "id": "BUMP_MAJOR_VERSION",
                "priority": "P0",
                "label": "Cut a major-version release",
                "reason": "Breaking changes require a SemVer-major bump.",
                "owner": "release_manager",
                "blast_radius": 5,
                "reversibility": "low",
            })

        if summary["security"] >= 1:
            actions.append({
                "id": "HIGHLIGHT_SECURITY_FIXES",
                "priority": "P0",
                "label": "Coordinate disclosure / advisory for security fixes",
                "reason": (
                    f"{summary['security']} security-relevant commit(s); pin CVE refs "
                    "and credit reporters before publishing notes."
                ),
                "owner": "security",
                "blast_radius": 5,
                "reversibility": "low",
            })

        if summary["deprecation"] >= 1:
            actions.append({
                "id": "ANNOUNCE_DEPRECATIONS",
                "priority": "P1",
                "label": "Add deprecation notice with sunset timeline",
                "reason": (
                    f"{summary['deprecation']} deprecation(s); give users >=1 release "
                    "of advance notice before removal."
                ),
                "owner": "release_manager",
                "blast_radius": 3,
                "reversibility": "medium",
            })

        if summary["no_test_files_touched"] >= 1:
            actions.append({
                "id": "VERIFY_TEST_COVERAGE",
                "priority": "P1" if summary["no_test_files_touched"] >= 3 else "P2",
                "label": "Backfill tests for untested feature/fix commits",
                "reason": (
                    f"{summary['no_test_files_touched']} commit(s) changed code "
                    "without touching any test files."
                ),
                "owner": "engineering",
                "blast_radius": 2,
                "reversibility": "high",
            })

        if summary["large_diff"] >= 2:
            actions.append({
                "id": "SOLICIT_EXTRA_REVIEW",
                "priority": "P2",
                "label": "Request a second reviewer for large-diff commits",
                "reason": (
                    f"{summary['large_diff']} commit(s) exceed 1k LOC; long diffs "
                    "are higher-risk than short ones."
                ),
                "owner": "engineering",
                "blast_radius": 2,
                "reversibility": "high",
            })

        if summary["revert"] >= 1:
            actions.append({
                "id": "DOCUMENT_REVERTS",
                "priority": "P2",
                "label": "Call out reverted commits explicitly in release notes",
                "reason": "Reverts surprise users who upgraded across the original.",
                "owner": "release_manager",
                "blast_radius": 2,
                "reversibility": "high",
            })

        if verdict == "BLOCK":
            actions.append({
                "id": "DO_NOT_RELEASE_YET",
                "priority": "P0",
                "label": "Block the release until risks are addressed",
                "reason": "Multiple high-risk signals; ship a smaller scoped release first.",
                "owner": "release_manager",
                "blast_radius": 5,
                "reversibility": "high",
            })
        elif verdict == "HOLD":
            actions.append({
                "id": "RUN_PRE_RELEASE_QA",
                "priority": "P1",
                "label": "Run a full pre-release QA / smoke pass",
                "reason": "Risk score is elevated; manual smoke tests pay off here.",
                "owner": "qa",
                "blast_radius": 3,
                "reversibility": "high",
            })
        elif verdict == "PILOT":
            actions.append({
                "id": "PILOT_RELEASE",
                "priority": "P1",
                "label": "Ship as pre-release / pilot first, then promote",
                "reason": "Mid-risk release benefits from staged rollout.",
                "owner": "release_manager",
                "blast_radius": 3,
                "reversibility": "high",
            })

        if not actions and summary["total"] > 0:
            actions.append({
                "id": "TAG_AND_RELEASE",
                "priority": "P3",
                "label": "Tag the release and publish notes",
                "reason": "No risk signals detected; safe to release.",
                "owner": "release_manager",
                "blast_radius": 2,
                "reversibility": "high",
            })

        # Risk-appetite trims
        if self.risk_appetite == "aggressive":
            actions = [a for a in actions if a["priority"] != "P3" or len(actions) == 1]
            if any(a["priority"] in ("P0", "P1") for a in actions):
                actions = [a for a in actions if a["priority"] != "P2" or _action_is_critical(a)]
        elif self.risk_appetite == "cautious":
            if any(a["priority"] in ("P0", "P1") for a in actions) and not any(
                a["id"] == "REQUEST_QA_SIGNOFF" for a in actions
            ):
                actions.append({
                    "id": "REQUEST_QA_SIGNOFF",
                    "priority": "P2",
                    "label": "Request explicit QA sign-off before tagging",
                    "reason": "Cautious posture: don't tag without a second pair of eyes.",
                    "owner": "qa",
                    "blast_radius": 2,
                    "reversibility": "high",
                })

        # P0-first, then id
        actions.sort(key=lambda a: (_PRI_RANK[a["priority"]], a["id"]))
        # Dedup by id
        seen: set = set()
        deduped: List[Dict[str, object]] = []
        for a in actions:
            if a["id"] in seen:
                continue
            seen.add(a["id"])
            deduped.append(a)
        return deduped

    def _build_insights(
        self,
        entries: Sequence[ChangelogEntry],
        summary: Dict[str, int],
    ) -> List[str]:
        insights: List[str] = []
        if summary["breaking"] >= 1:
            insights.append(
                f"breaking_changes_present:{summary['breaking']}"
            )
        if summary["security"] >= 1:
            insights.append(f"security_fixes_present:{summary['security']}")
        if summary["feature"] >= 1 and summary["fix"] == 0:
            insights.append("feature_dominated_release")
        if summary["fix"] >= 1 and summary["feature"] == 0:
            insights.append("maintenance_release")
        if summary["no_test_files_touched"] >= max(3, summary["total"] // 2):
            insights.append("test_coverage_gap")
        if summary["docs"] == 0 and (summary["feature"] >= 1 or summary["breaking"] >= 1):
            insights.append("no_docs_updates_for_user_facing_changes")
        if summary["chore"] + summary["internal"] + summary["test"] >= summary["total"] * 0.8 and summary["total"] >= 5:
            insights.append("internal_only_release")
        # Author diversity
        authors = {e.author for e in entries if e.author}
        if len(authors) >= 3:
            insights.append(f"multi_author_release:{len(authors)}")
        elif len(authors) == 1:
            insights.append("single_author_release")
        return insights


def _action_is_critical(a: Dict[str, object]) -> bool:
    return str(a.get("id", "")).startswith(("HIGHLIGHT_SECURITY", "ADD_MIGRATION", "BUMP_MAJOR"))


_PRI_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _windows_utf8_stdout() -> None:
    if sys.platform.startswith("win"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            try:
                sys.stdout = io.TextIOWrapper(  # type: ignore[assignment]
                    sys.stdout.buffer, encoding="utf-8", errors="replace"
                )
            except Exception:
                pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    _windows_utf8_stdout()
    parser = argparse.ArgumentParser(
        prog="sauravchange",
        description="Agentic changelog / release-notes drafter for sauravcode.",
    )
    parser.add_argument("--root", default=".", help="Repository root (default: cwd)")
    parser.add_argument(
        "--from", dest="from_ref", default=None,
        help="Start ref (exclusive). Defaults to last tag if available.",
    )
    parser.add_argument("--to", dest="to_ref", default="HEAD", help="End ref (default HEAD)")
    parser.add_argument(
        "--risk", choices=_RISK_APPETITES, default="balanced",
        help="Risk appetite (cautious/balanced/aggressive)",
    )
    parser.add_argument(
        "--format", choices=("text", "md", "markdown", "json"), default="text",
        help="Output format",
    )
    parser.add_argument("--output", default=None, help="Write to this file instead of stdout")
    args = parser.parse_args(argv)

    advisor = ChangelogAdvisor(
        root=args.root,
        from_ref=args.from_ref,
        to_ref=args.to_ref,
        risk_appetite=args.risk,
    )
    report = advisor.scan()

    fmt = args.format
    if fmt in ("md", "markdown"):
        rendered = report.to_markdown()
    elif fmt == "json":
        rendered = report.to_json()
    else:
        rendered = report.to_text()

    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
