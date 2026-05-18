#!/usr/bin/env python3
"""sauravreview - Agentic code-review focus advisor for sauravcode.

Scans the git diff between HEAD and a target ref and produces a per-changed-
function review-focus plan plus a cross-file review playbook telling a human
reviewer WHERE TO SPEND ATTENTION.

Sibling to sauravgate.py / sauravprioritize.py / sauravsmoke.py / sauravcoach.py.

Public API
----------
- ``ReviewFocusAdvisor(root=".", target_branch=None, risk_appetite="balanced",
                       now=None, diff_provider=None, repo_provider=None)``
- ``ReviewFocusAdvisor.scan()`` -> ``ReviewFocusReport``
- ``ReviewFocusReport.to_text() / to_markdown() / to_json()``

CLI
---
::

    python sauravreview.py --root . --target origin/main --format md --output review.md

Pure stdlib. No mutation of any repo state. Deterministic given a fixed
now() callable (only ``generated_at`` carries wall-clock state).
"""

from __future__ import annotations

import argparse
import io
import json
import os
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
_DEFAULT_TARGETS = ("origin/main", "origin/master", "main", "master")

_AUTH_TOKENS = (
    "auth", "login", "password", "token", "secret", "api_key", "bearer",
    "permission", "role", "admin", "jwt", "oauth", "hash", "hmac", "sign",
)
_AUTH_RE = re.compile(r"\b(" + "|".join(_AUTH_TOKENS) + r")\b", re.IGNORECASE)

_SECRET_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"\b[0-9a-fA-F]{32,}\b"),
    re.compile(r"BEGIN PRIVATE KEY"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}"),
    re.compile(r"""password\s*=\s*["'][^"']{4,}["']""", re.IGNORECASE),
)

_EVAL_RE = re.compile(r"(?<![\w.])eval\(|(?<![\w.])exec\(")
_TODO_RE = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b")
_PRINT_RE = re.compile(r"\bprint\s*\(")
_IO_RE = re.compile(r"\b(open\(|read\(|write\(|Path\(|os\.|subprocess)")
_NET_RE = re.compile(r"\b(http[s]?://|socket\.|requests\.|urllib|aiohttp|urlopen)")
_ERR_RE = re.compile(r"\b(try|catch|except|assert|raise|throw)\b")
_COMPLEXITY_RE = re.compile(r"\b(if|elif|while|for|and|or|catch|except|case|match)\b|\?")

_FUNC_DEF_RE = re.compile(r"^\s*(?:def|func|function|fn)\s+([A-Za-z_][A-Za-z0-9_]*)")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ReviewItem:
    file: str
    function: str
    verdict: str
    priority: str
    review_priority_score: int
    estimated_review_minutes: int
    reasons: List[Dict[str, object]] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)


@dataclass
class ReviewFocusReport:
    items: List[ReviewItem]
    headline: str
    grade: str
    playbook: List[Dict[str, object]]
    insights: List[str]
    risk_appetite: str
    generated_at: str
    target_branch: Optional[str]

    def to_text(self) -> str:
        out: List[str] = []
        out.append(self.headline)
        out.append(f"Grade: {self.grade}   Risk appetite: {self.risk_appetite}")
        if self.target_branch:
            out.append(f"Target branch: {self.target_branch}")
        out.append("")
        if not self.items:
            out.append("(no changed functions detected)")
        else:
            out.append("Review focus:")
            for it in self.items:
                out.append(
                    f"  [{it.priority}] {it.verdict} {it.file}::{it.function} "
                    f"score={it.review_priority_score} est={it.estimated_review_minutes}min"
                )
                for r in it.reasons[:3]:
                    out.append(f"      - {r.get('code')}: {r.get('label')}")
        if self.playbook:
            out.append("")
            out.append("Playbook:")
            for p in self.playbook:
                out.append(
                    f"  [{p['priority']}] {p['id']} (owner={p['owner']}, "
                    f"blast={p['blast_radius']}, rev={p['reversibility']})"
                )
                out.append(f"      reason: {p['reason']}")
        if self.insights:
            out.append("")
            out.append("Insights: " + ", ".join(self.insights))
        return "\n".join(out)

    def to_markdown(self) -> str:
        out: List[str] = []
        out.append(f"# Review Focus Report")
        out.append("")
        out.append(f"**Headline:** {self.headline}")
        out.append(f"**Grade:** {self.grade}    **Risk appetite:** {self.risk_appetite}")
        if self.target_branch:
            out.append(f"**Target branch:** `{self.target_branch}`")
        out.append("")
        out.append("## Items")
        out.append("")
        if not self.items:
            out.append("_no changed functions detected_")
        else:
            out.append("| Priority | Verdict | File::Function | Score | Est. min | Top reasons |")
            out.append("|---|---|---|---|---|---|")
            for it in self.items:
                reasons = "; ".join(str(r.get("code")) for r in it.reasons[:3]) or "-"
                out.append(
                    f"| {it.priority} | {it.verdict} | `{it.file}::{it.function}` | "
                    f"{it.review_priority_score} | {it.estimated_review_minutes} | {reasons} |"
                )
        out.append("")
        out.append("## Playbook")
        out.append("")
        if not self.playbook:
            out.append("_empty_")
        else:
            for p in self.playbook:
                out.append(
                    f"- **[{p['priority']}] {p['id']}** — {p['reason']} "
                    f"_(owner={p['owner']}, blast={p['blast_radius']}, "
                    f"rev={p['reversibility']})_"
                )
        out.append("")
        out.append("## Insights")
        out.append("")
        if not self.insights:
            out.append("_none_")
        else:
            for ins in self.insights:
                out.append(f"- {ins}")
        return "\n".join(out)

    def to_json(self) -> str:
        payload = {
            "headline": self.headline,
            "grade": self.grade,
            "risk_appetite": self.risk_appetite,
            "target_branch": self.target_branch,
            "generated_at": self.generated_at,
            "items": [asdict(i) for i in self.items],
            "playbook": list(self.playbook),
            "insights": list(self.insights),
        }
        return json.dumps(payload, sort_keys=True, indent=2, default=str)


# ---------------------------------------------------------------------------
# Diff parsing helpers
# ---------------------------------------------------------------------------

@dataclass
class FunctionChange:
    file: str
    function: str
    added_lines: List[str] = field(default_factory=list)
    removed_lines: List[str] = field(default_factory=list)
    is_new: bool = False
    is_comment_only: bool = False
    is_trivial_rename: bool = False


def _parse_unified_diff(diff_text: str) -> List[FunctionChange]:
    """Parse a `git diff --unified=0` text blob into per-function changes.

    Pure stdlib. Heuristic: associate each hunk with the most recent
    function-def line seen via the hunk header `@@ ... @@ <ctx>` if present,
    or by scanning for added function-def lines inside the hunk.
    """
    if not diff_text:
        return []
    changes: Dict[Tuple[str, str], FunctionChange] = {}
    cur_file: Optional[str] = None
    cur_func: Optional[str] = None
    cur_func_is_new = False
    file_re = re.compile(r"^\+\+\+ b/(.+)$")
    hunk_re = re.compile(r"^@@ [^@]+ @@\s*(.*)$")
    for raw in diff_text.splitlines():
        m = file_re.match(raw)
        if m:
            cur_file = m.group(1).strip()
            cur_func = None
            cur_func_is_new = False
            continue
        if raw.startswith("--- "):
            continue
        if raw.startswith("diff "):
            cur_file = None
            cur_func = None
            cur_func_is_new = False
            continue
        if cur_file is None:
            continue
        hm = hunk_re.match(raw)
        if hm:
            ctx = hm.group(1).strip()
            fm = _FUNC_DEF_RE.search(ctx) if ctx else None
            if fm:
                cur_func = fm.group(1)
                cur_func_is_new = False
            # else keep the previous cur_func until a def line shows up
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            line = raw[1:]
            fm = _FUNC_DEF_RE.match(line)
            if fm:
                cur_func = fm.group(1)
                cur_func_is_new = True
            fn = cur_func or "<file-level>"
            key = (cur_file, fn)
            ch = changes.get(key)
            if ch is None:
                ch = FunctionChange(file=cur_file, function=fn, is_new=cur_func_is_new)
                changes[key] = ch
            ch.added_lines.append(line)
            if cur_func_is_new and fn == cur_func:
                ch.is_new = True
        elif raw.startswith("-") and not raw.startswith("---"):
            line = raw[1:]
            fn = cur_func or "<file-level>"
            key = (cur_file, fn)
            ch = changes.get(key)
            if ch is None:
                ch = FunctionChange(file=cur_file, function=fn)
                changes[key] = ch
            ch.removed_lines.append(line)

    # post-process: comment-only / trivial-rename heuristics
    out: List[FunctionChange] = []
    for ch in changes.values():
        all_changed = ch.added_lines + ch.removed_lines
        non_empty = [l for l in all_changed if l.strip()]
        if non_empty and all(
            l.lstrip().startswith("#") or l.lstrip().startswith('"""') or l.lstrip().startswith("'''")
            for l in non_empty
        ):
            ch.is_comment_only = True
        # trivial rename heuristic: equal counts, each pair differs by one token
        if (
            not ch.is_new
            and len(ch.added_lines) == len(ch.removed_lines)
            and ch.added_lines
            and len(ch.added_lines) <= 6
        ):
            def _toks(s: str) -> List[str]:
                return re.findall(r"[A-Za-z_][A-Za-z0-9_]*", s)
            diffs = 0
            for a, r in zip(ch.added_lines, ch.removed_lines):
                ta, tr = _toks(a), _toks(r)
                if len(ta) != len(tr):
                    diffs = 99
                    break
                pair_diff = sum(1 for x, y in zip(ta, tr) if x != y)
                diffs += pair_diff
            if 0 < diffs <= 2:
                ch.is_trivial_rename = True
        out.append(ch)
    return out


# ---------------------------------------------------------------------------
# Repo state provider (mockable for tests)
# ---------------------------------------------------------------------------

@dataclass
class RepoState:
    is_git: bool = True
    target_branch: Optional[str] = None
    test_files: List[str] = field(default_factory=list)   # paths
    test_corpus_text: str = ""                            # concatenated content
    srv_files: Dict[str, str] = field(default_factory=dict)  # path -> text (for callee scan)
    recently_rewritten: Dict[Tuple[str, str], bool] = field(default_factory=dict)


def _run_git(root: str, args: Sequence[str]) -> Tuple[int, str]:
    try:
        res = subprocess.run(
            ["git", "-C", root, *args],
            check=False,
            capture_output=True,
            text=True,
        )
        return res.returncode, (res.stdout or "")
    except (FileNotFoundError, OSError):
        return 1, ""


def _default_repo_state(root: str, target_branch: Optional[str]) -> RepoState:
    rc, _ = _run_git(root, ["rev-parse", "--git-dir"])
    if rc != 0:
        return RepoState(is_git=False)
    tb = target_branch
    if not tb:
        for cand in _DEFAULT_TARGETS:
            rc2, _ = _run_git(root, ["rev-parse", "--verify", cand])
            if rc2 == 0:
                tb = cand
                break
    state = RepoState(is_git=True, target_branch=tb)
    # collect tests
    test_paths: List[str] = []
    test_text = io.StringIO()
    try:
        for p in Path(root).rglob("test_*.py"):
            if any(part.startswith(".") for part in p.parts):
                continue
            test_paths.append(str(p.relative_to(root)).replace("\\", "/"))
            try:
                test_text.write(p.read_text(encoding="utf-8", errors="ignore"))
                test_text.write("\n")
            except OSError:
                pass
    except OSError:
        pass
    state.test_files = test_paths
    state.test_corpus_text = test_text.getvalue()
    # collect .srv corpus for blast-radius scan
    srv: Dict[str, str] = {}
    try:
        for p in Path(root).rglob("*.srv"):
            if any(part.startswith(".") for part in p.parts):
                continue
            rel = str(p.relative_to(root)).replace("\\", "/")
            try:
                srv[rel] = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                srv[rel] = ""
    except OSError:
        pass
    state.srv_files = srv
    return state


def _default_diff_provider(root: str, target_branch: Optional[str]) -> str:
    if not target_branch:
        # diff against HEAD only (unstaged + staged)
        rc, out = _run_git(root, ["diff", "HEAD", "--unified=0", "--", "*.srv"])
        return out if rc == 0 else ""
    rc, out = _run_git(
        root,
        ["diff", f"{target_branch}...HEAD", "--unified=0", "--", "*.srv"],
    )
    return out if rc == 0 else ""


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _complexity_count(lines: Sequence[str]) -> int:
    n = 0
    for ln in lines:
        n += len(_COMPLEXITY_RE.findall(ln))
    return n


def _score_change(ch: FunctionChange, state: RepoState) -> Tuple[int, List[Dict[str, object]], List[str], List[str]]:
    """Return (raw_score, reasons, evidence, verdict_forcers)."""
    reasons: List[Dict[str, object]] = []
    evidence: List[str] = []
    score = 0
    forcers: List[str] = []  # verdict overrides, applied later

    add_lines = ch.added_lines
    rm_lines = ch.removed_lines
    churn = len(add_lines) + len(rm_lines)

    # --- TRIVIAL_RENAME / COMMENT_ONLY (early caps applied after sum) ---
    if ch.is_trivial_rename:
        reasons.append({"code": "TRIVIAL_RENAME", "label": "looks like a rename only", "severity": 0})
    if ch.is_comment_only:
        reasons.append({"code": "COMMENT_ONLY_CHANGE", "label": "only comments/docstring touched", "severity": 0})

    # 1. CHURN
    if churn:
        if churn < 10:
            csev = 5
        elif churn < 40:
            csev = 25
        elif churn < 100:
            csev = 50
        elif churn < 250:
            csev = 70
        else:
            csev = 90
        score += csev
        reasons.append({"code": "LARGE_CHURN" if csev >= 50 else "CHURN",
                        "label": f"{churn} lines changed",
                        "severity": csev})

    # 2. COMPLEXITY_DELTA
    delta = _complexity_count(add_lines) - _complexity_count(rm_lines)
    if delta >= 10:
        score += 75
        reasons.append({"code": "HIGH_COMPLEXITY_DELTA", "label": f"+{delta} branches", "severity": 75})
    elif delta >= 6:
        score += 55
        reasons.append({"code": "HIGH_COMPLEXITY_DELTA", "label": f"+{delta} branches", "severity": 55})
    elif delta >= 3:
        score += 35
        reasons.append({"code": "HIGH_COMPLEXITY_DELTA", "label": f"+{delta} branches", "severity": 35})

    # 3. NEW_FUNCTION
    if ch.is_new:
        score += 55
        reasons.append({"code": "NEW_FUNCTION", "label": "function newly added", "severity": 55})
        forcers.append("NEW_FUNCTION")

    # 4. REMOVED_ERROR_HANDLING
    err_added = sum(1 for l in add_lines if _ERR_RE.search(l))
    err_removed = sum(1 for l in rm_lines if _ERR_RE.search(l))
    if err_removed > err_added:
        score += 30
        reasons.append({"code": "REMOVED_ERROR_HANDLING",
                        "label": f"removed {err_removed - err_added} error-handling line(s)",
                        "severity": 30})

    # 5. AUTH_KEYWORDS_TOUCHED
    auth_hits = [l for l in add_lines + rm_lines if _AUTH_RE.search(l)]
    if auth_hits:
        score += 25
        reasons.append({"code": "AUTH_KEYWORDS_TOUCHED",
                        "label": f"{len(auth_hits)} auth-related line(s)",
                        "severity": 25})
        forcers.append("AUTH_KEYWORDS_TOUCHED")
        for h in auth_hits[:2]:
            evidence.append(f"auth: {h.strip()[:120]}")

    # 6. SECRET_LIKE_LITERAL
    secret_hits: List[str] = []
    for l in add_lines:
        for pat in _SECRET_PATTERNS:
            if pat.search(l):
                secret_hits.append(l)
                break
    if secret_hits:
        score += 50
        reasons.append({"code": "SECRET_LIKE_LITERAL",
                        "label": f"{len(secret_hits)} possible secret literal(s)",
                        "severity": 50})
        forcers.append("SECRET_LIKE_LITERAL")
        for h in secret_hits[:2]:
            evidence.append(f"secret: {h.strip()[:120]}")

    # 11. EVAL_OR_EXEC
    eval_hits = [l for l in add_lines if _EVAL_RE.search(l)]
    if eval_hits:
        score += 45
        reasons.append({"code": "EVAL_OR_EXEC",
                        "label": f"{len(eval_hits)} eval/exec call(s) introduced",
                        "severity": 45})
        forcers.append("EVAL_OR_EXEC")
        for h in eval_hits[:2]:
            evidence.append(f"eval/exec: {h.strip()[:120]}")

    # 7. NO_TEST_COVERAGE
    file = ch.file
    stem = Path(file).stem
    is_test_file = stem.startswith("test_") or "/tests/" in file or file.startswith("tests/")
    if not is_test_file:
        expected_test = f"test_{stem}.py"
        covered_by_file = any(tf.endswith(expected_test) for tf in state.test_files)
        covered_by_name = bool(ch.function) and (ch.function in state.test_corpus_text)
        if not covered_by_file and not covered_by_name:
            score += 20
            reasons.append({"code": "NO_TEST_COVERAGE",
                            "label": "no matching test file or test reference",
                            "severity": 20})

    # 8. HIGH_BLAST_RADIUS — count fn name as callee in OTHER .srv files
    callee = 0
    if ch.function and ch.function != "<file-level>":
        pat = re.compile(r"\b" + re.escape(ch.function) + r"\s*\(")
        for path, text in state.srv_files.items():
            if path == ch.file:
                continue
            callee += len(pat.findall(text))
    if callee >= 25:
        score += 60
        reasons.append({"code": "HIGH_BLAST_RADIUS",
                        "label": f"{callee} caller(s) across .srv corpus",
                        "severity": 60})
    elif callee >= 10:
        score += 40
        reasons.append({"code": "HIGH_BLAST_RADIUS",
                        "label": f"{callee} caller(s) across .srv corpus",
                        "severity": 40})
    elif callee >= 3:
        score += 20
        reasons.append({"code": "HIGH_BLAST_RADIUS",
                        "label": f"{callee} caller(s) across .srv corpus",
                        "severity": 20})

    # 9. IO_TOUCHED
    if any(_IO_RE.search(l) for l in add_lines):
        score += 12
        reasons.append({"code": "IO_TOUCHED", "label": "file/process I/O touched", "severity": 12})

    # 10. NETWORK_TOUCHED
    if any(_NET_RE.search(l) for l in add_lines):
        score += 18
        reasons.append({"code": "NETWORK_TOUCHED", "label": "network calls touched", "severity": 18})

    # 12. TODO_INTRODUCED
    todo_hits = sum(len(_TODO_RE.findall(l)) for l in add_lines)
    if todo_hits:
        sev = min(30, 10 * todo_hits)
        score += sev
        reasons.append({"code": "TODO_INTRODUCED",
                        "label": f"{todo_hits} TODO/FIXME marker(s) added",
                        "severity": sev})

    # 13. DEBUG_PRINT_INTRODUCED
    if "_demo" not in ch.file and not ch.file.endswith("demo.srv"):
        debug_hits = sum(1 for l in add_lines if _PRINT_RE.search(l))
        if debug_hits:
            sev = min(20, 6 * debug_hits)
            score += sev
            reasons.append({"code": "DEBUG_PRINT_INTRODUCED",
                            "label": f"{debug_hits} print() call(s) added",
                            "severity": sev})

    # 16. RECENTLY_REWRITTEN
    if state.recently_rewritten.get((ch.file, ch.function)):
        score += 15
        reasons.append({"code": "RECENTLY_REWRITTEN",
                        "label": "function hot in last 14 days",
                        "severity": 15})

    return score, reasons, evidence, forcers


def _verdict_for(score: int, forcers: Sequence[str]) -> str:
    if "SECRET_LIKE_LITERAL" in forcers or "EVAL_OR_EXEC" in forcers:
        return "BLOCK_REVIEW"
    if "AUTH_KEYWORDS_TOUCHED" in forcers:
        return "SECURITY_REVIEW"
    if "NEW_FUNCTION" in forcers and score >= 55:
        return "NEW_HOTSPOT"
    if score >= 70:
        return "DEEP_REVIEW"
    if score >= 40:
        return "STANDARD_REVIEW"
    if score >= 15:
        return "SKIM"
    return "RUBBER_STAMP"


def _priority_for(verdict: str) -> str:
    if verdict in ("BLOCK_REVIEW", "SECURITY_REVIEW", "NEW_HOTSPOT"):
        return "P0"
    if verdict == "DEEP_REVIEW":
        return "P1"
    if verdict == "STANDARD_REVIEW":
        return "P2"
    return "P3"


def _minutes_for(priority: str, reasons: Sequence[Dict[str, object]]) -> int:
    base = {"P0": 60, "P1": 30, "P2": 15, "P3": 5}.get(priority, 5)
    has_high_blast = any(
        r.get("code") == "HIGH_BLAST_RADIUS" and int(r.get("severity") or 0) >= 40
        for r in reasons
    )
    if has_high_blast:
        return int(base * 1.5)
    return base


# ---------------------------------------------------------------------------
# Playbook + grade
# ---------------------------------------------------------------------------

_PRI_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def _build_playbook(items: List[ReviewItem], risk_appetite: str) -> List[Dict[str, object]]:
    actions: List[Dict[str, object]] = []
    by_files: Dict[str, List[str]] = {}
    for it in items:
        by_files.setdefault(it.verdict, []).append(it.file)

    block = [it for it in items if it.verdict == "BLOCK_REVIEW"]
    sec = [it for it in items
           if any(r.get("code") in ("SECRET_LIKE_LITERAL", "EVAL_OR_EXEC")
                  for r in it.reasons)]
    new_hot = [it for it in items if it.verdict == "NEW_HOTSPOT"]
    no_test = [it for it in items
               if any(r.get("code") == "NO_TEST_COVERAGE" for r in it.reasons)]
    todos = sum(int(r.get("severity") or 0) // 10
                for it in items for r in it.reasons
                if r.get("code") == "TODO_INTRODUCED")
    total_churn_proxy = sum(
        int(r.get("severity") or 0)
        for it in items for r in it.reasons
        if r.get("code") in ("LARGE_CHURN", "CHURN")
    )
    high_blast = [it for it in items
                  if any(r.get("code") == "HIGH_BLAST_RADIUS"
                         and int(r.get("severity") or 0) >= 40
                         for r in it.reasons)]
    n_files = len({it.file for it in items})

    if sec:
        actions.append({
            "id": "SECURITY_DEEP_DIVE",
            "priority": "P0",
            "label": "Pull in security reviewer; trace secret/eval origin and rotation path",
            "owner": "security",
            "blast_radius": 4,
            "reversibility": "low",
            "reason": f"{len(sec)} item(s) trip SECRET_LIKE_LITERAL or EVAL_OR_EXEC",
            "files": sorted({it.file for it in sec}),
        })
    if block:
        actions.append({
            "id": "RESET_BEFORE_MERGE",
            "priority": "P0",
            "label": "Do not merge until BLOCK_REVIEW items are resolved",
            "owner": "author",
            "blast_radius": 5,
            "reversibility": "low",
            "reason": f"{len(block)} item(s) at BLOCK_REVIEW verdict",
            "files": sorted({it.file for it in block}),
        })
    if len(new_hot) >= 2:
        actions.append({
            "id": "PAIR_REVIEW_WITH_ORIGINAL_AUTHOR",
            "priority": "P0",
            "label": "Schedule a synchronous walk-through with the change author",
            "owner": "reviewer",
            "blast_radius": 3,
            "reversibility": "medium",
            "reason": f"{len(new_hot)} new hotspots introduced together",
            "files": sorted({it.file for it in new_hot}),
        })
    if len(no_test) >= 2:
        actions.append({
            "id": "ADD_TESTS_FIRST",
            "priority": "P1",
            "label": "Ask author to add tests covering the new/changed functions before re-review",
            "owner": "author",
            "blast_radius": 2,
            "reversibility": "high",
            "reason": f"{len(no_test)} function(s) lack test coverage",
            "files": sorted({it.file for it in no_test}),
        })
    if total_churn_proxy > 600 or n_files > 8:
        actions.append({
            "id": "SPLIT_PR_FOR_FOCUS",
            "priority": "P1",
            "label": "Request that the change be split into reviewable slices",
            "owner": "author",
            "blast_radius": 2,
            "reversibility": "high",
            "reason": f"large change surface ({n_files} files, churn proxy {total_churn_proxy})",
            "files": [],
        })
    if high_blast:
        actions.append({
            "id": "REVIEW_CALLERS_TOGETHER",
            "priority": "P1",
            "label": "Open callers in a split view alongside the changed function",
            "owner": "reviewer",
            "blast_radius": 3,
            "reversibility": "high",
            "reason": f"{len(high_blast)} function(s) with high blast radius",
            "files": sorted({it.file for it in high_blast}),
        })
    if todos >= 3:
        actions.append({
            "id": "SCHEDULE_FOLLOWUP_FOR_TODOS",
            "priority": "P2",
            "label": "File follow-up tickets for new TODO/FIXME markers",
            "owner": "author",
            "blast_radius": 1,
            "reversibility": "high",
            "reason": f"{todos} TODO/FIXME marker(s) introduced",
            "files": [],
        })
    if new_hot or block:
        actions.append({
            "id": "ASK_FOR_CHANGELOG_NOTE",
            "priority": "P2",
            "label": "Request a CHANGELOG line for the new/blocking changes",
            "owner": "author",
            "blast_radius": 1,
            "reversibility": "high",
            "reason": "user-visible new code or blocked merge in flight",
            "files": [],
        })

    if items and all(it.verdict in ("SKIM", "RUBBER_STAMP") for it in items):
        actions.append({
            "id": "LGTM_FAST_PATH",
            "priority": "P3",
            "label": "Skim, approve, move on",
            "owner": "reviewer",
            "blast_radius": 1,
            "reversibility": "high",
            "reason": "all items are SKIM/RUBBER_STAMP",
            "files": [],
        })

    # appetite tweaks
    any_p0 = any(a["priority"] == "P0" for a in actions)
    any_p1 = any(a["priority"] == "P1" for a in actions)
    if risk_appetite == "cautious" and any_p0:
        actions.append({
            "id": "SOLICIT_SECOND_REVIEWER",
            "priority": "P2",
            "label": "Bring in a second reviewer before approving",
            "owner": "reviewer",
            "blast_radius": 2,
            "reversibility": "high",
            "reason": "cautious appetite + P0 present",
            "files": [],
        })
    if risk_appetite == "aggressive" and any_p1:
        actions = [a for a in actions if a["id"] != "LGTM_FAST_PATH"]

    # dedupe by id keeping first occurrence, then sort by priority then id
    seen = set()
    deduped: List[Dict[str, object]] = []
    for a in actions:
        if a["id"] in seen:
            continue
        seen.add(a["id"])
        deduped.append(a)
    deduped.sort(key=lambda a: (_PRI_RANK.get(str(a["priority"]), 9), str(a["id"])))
    return deduped


def _grade(items: List[ReviewItem], total_minutes: int, p0_count: int,
           risk_appetite: str, has_block: bool) -> str:
    if p0_count >= 3 or has_block:
        grade = "F"
    elif p0_count >= 2 or total_minutes > 300:
        grade = "D"
    elif p0_count >= 1 or total_minutes > 150:
        grade = "C"
    elif total_minutes > 60:
        grade = "B"
    else:
        grade = "A"

    bands = ["A", "B", "C", "D", "F"]
    idx = bands.index(grade)
    if risk_appetite == "cautious" and p0_count >= 1 and idx < 4:
        idx += 1
    if risk_appetite == "aggressive" and p0_count == 0 and idx > 0:
        idx -= 1
    return bands[idx]


def _insights(items: List[ReviewItem]) -> List[str]:
    out: List[str] = []
    if not items:
        out.append("QUIET_PR")
        return out
    n = len(items)
    if any(any(r.get("code") in ("SECRET_LIKE_LITERAL", "EVAL_OR_EXEC", "AUTH_KEYWORDS_TOUCHED")
               for r in it.reasons) for it in items):
        out.append("SECURITY_HOTSPOT_PRESENT")
    new_n = sum(1 for it in items
                if any(r.get("code") == "NEW_FUNCTION" for r in it.reasons))
    if new_n / n >= 0.5:
        out.append("NEW_CODE_DOMINANT")
    no_test_n = sum(1 for it in items
                    if any(r.get("code") == "NO_TEST_COVERAGE" for r in it.reasons))
    if no_test_n / n >= 0.5:
        out.append("TEST_DESERT")
    high_blast_n = sum(1 for it in items
                       if any(r.get("code") == "HIGH_BLAST_RADIUS"
                              and int(r.get("severity") or 0) >= 40
                              for r in it.reasons))
    if high_blast_n >= 2:
        out.append("HIGH_FANOUT_CHANGES")
    todos = sum(int(r.get("severity") or 0) // 10
                for it in items for r in it.reasons
                if r.get("code") == "TODO_INTRODUCED")
    if todos >= 3:
        out.append("TODO_BACKLOG_GROWING")
    refactor_n = sum(1 for it in items
                     if any(r.get("code") in ("TRIVIAL_RENAME", "COMMENT_ONLY_CHANGE")
                            for r in it.reasons))
    if n >= 1 and refactor_n / n >= 0.6:
        out.append("REFACTOR_HEAVY")
    return out


# ---------------------------------------------------------------------------
# Advisor
# ---------------------------------------------------------------------------

class ReviewFocusAdvisor:
    def __init__(
        self,
        root: str = ".",
        target_branch: Optional[str] = None,
        risk_appetite: str = "balanced",
        now: Optional[Callable[[], datetime]] = None,
        diff_provider: Optional[Callable[[str, Optional[str]], str]] = None,
        repo_provider: Optional[Callable[[str, Optional[str]], RepoState]] = None,
    ) -> None:
        if risk_appetite not in _RISK_APPETITES:
            raise ValueError(f"risk_appetite must be one of {_RISK_APPETITES}")
        self.root = root
        self.target_branch = target_branch
        self.risk_appetite = risk_appetite
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._diff_provider = diff_provider or _default_diff_provider
        self._repo_provider = repo_provider or _default_repo_state

    def scan(self) -> ReviewFocusReport:
        state = self._repo_provider(self.root, self.target_branch)
        gen_at = self._now().isoformat()
        if not state.is_git:
            return ReviewFocusReport(
                items=[],
                headline="VERDICT: not a git repository",
                grade="A",
                playbook=[],
                insights=["not_a_git_repository"],
                risk_appetite=self.risk_appetite,
                generated_at=gen_at,
                target_branch=None,
            )

        tb = state.target_branch or self.target_branch
        diff_text = self._diff_provider(self.root, tb)
        changes = _parse_unified_diff(diff_text)
        mult = {"cautious": 1.15, "balanced": 1.00, "aggressive": 0.85}[self.risk_appetite]

        items: List[ReviewItem] = []
        for ch in changes:
            raw, reasons, evidence, forcers = _score_change(ch, state)
            score = int(round(raw * mult))
            if ch.is_trivial_rename:
                score = min(score, 20)
            if ch.is_comment_only:
                score = min(score, 10)
            score = max(0, min(100, score))
            verdict = _verdict_for(score, forcers)
            # comment-only / trivial-rename floor on verdict
            if ch.is_comment_only and verdict in ("DEEP_REVIEW", "STANDARD_REVIEW"):
                verdict = "RUBBER_STAMP"
            if ch.is_trivial_rename and verdict in ("DEEP_REVIEW", "STANDARD_REVIEW"):
                verdict = "SKIM"
            priority = _priority_for(verdict)
            minutes = _minutes_for(priority, reasons)
            items.append(ReviewItem(
                file=ch.file,
                function=ch.function,
                verdict=verdict,
                priority=priority,
                review_priority_score=score,
                estimated_review_minutes=minutes,
                reasons=sorted(reasons, key=lambda r: -int(r.get("severity") or 0)),
                evidence=evidence,
            ))

        items.sort(key=lambda it: (_PRI_RANK.get(it.priority, 9),
                                   -it.review_priority_score,
                                   it.file, it.function))

        p0_count = sum(1 for it in items if it.priority == "P0")
        p1_count = sum(1 for it in items if it.priority == "P1")
        total_min = sum(it.estimated_review_minutes for it in items)
        has_block = any(it.verdict == "BLOCK_REVIEW" for it in items)

        headline = (
            f"VERDICT: {len(items)} items - P0 {p0_count}, P1 {p1_count} "
            f"(est. {total_min} min total)"
        )
        playbook = _build_playbook(items, self.risk_appetite)
        insights = _insights(items)
        grade = _grade(items, total_min, p0_count, self.risk_appetite, has_block)

        return ReviewFocusReport(
            items=items,
            headline=headline,
            grade=grade,
            playbook=playbook,
            insights=insights,
            risk_appetite=self.risk_appetite,
            generated_at=gen_at,
            target_branch=tb,
        )


def format_report(report: ReviewFocusReport, fmt: str) -> str:
    fmt = (fmt or "text").lower()
    if fmt in ("text", "txt"):
        return report.to_text()
    if fmt in ("md", "markdown"):
        return report.to_markdown()
    if fmt == "json":
        return report.to_json()
    raise ValueError(f"unknown format: {fmt}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _maybe_utf8_stdout() -> None:
    if sys.platform.startswith("win"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    _maybe_utf8_stdout()
    parser = argparse.ArgumentParser(
        prog="sauravreview",
        description="Agentic code-review focus advisor for sauravcode (.srv) changes.",
    )
    parser.add_argument("--root", default=".", help="repo root")
    parser.add_argument("--target", dest="target", default=None,
                        help="target branch to diff against (default: auto-detect)")
    parser.add_argument("--risk", default="balanced", choices=list(_RISK_APPETITES),
                        help="risk appetite")
    parser.add_argument("--format", default="text", choices=("text", "md", "json"),
                        help="output format")
    parser.add_argument("--output", default=None, help="write to file instead of stdout")
    args = parser.parse_args(argv)

    advisor = ReviewFocusAdvisor(
        root=args.root,
        target_branch=args.target,
        risk_appetite=args.risk,
    )
    report = advisor.scan()
    text = format_report(report, args.format)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
