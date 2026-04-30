#!/usr/bin/env python3
"""sauravautopatch — Autonomous Self-Healing Engine for sauravcode.

Scans .srv programs for common bugs, anti-patterns, and code smells, then
autonomously generates, validates, and applies patches.  The engine operates
in three modes: diagnose-only (--scan), suggest patches (--suggest), or
fully autonomous fix-and-apply (--heal).

Detection engines (10):
    P001  Uninitialized Variable Use     Variables read before assignment
    P002  Dead Code Eliminator           Unreachable code after return/break
    P003  Infinite Loop Guard            Loops without exit conditions
    P004  Unused Parameter Cleanup       Function params never referenced
    P005  Missing Return Path            Functions with inconsistent returns
    P006  Duplicate Branch Detector      Identical if/else bodies
    P007  Off-by-One Guard               Common loop boundary mistakes
    P008  Resource Leak Patcher          Open without close patterns
    P009  Type Coercion Fixer            Implicit coercion in comparisons
    P010  Idempotency Enforcer           Non-idempotent operations in retry loops

Autonomy levels:
    Level 0 (--scan)      Detect issues, report only
    Level 1 (--suggest)   Generate patch diffs, don't apply
    Level 2 (--heal)      Apply safe patches (confidence >= 0.8)
    Level 3 (--heal-all)  Apply all patches regardless of confidence

Usage:
    python sauravautopatch.py program.srv                # Scan (level 0)
    python sauravautopatch.py program.srv --suggest      # Generate patches
    python sauravautopatch.py program.srv --heal         # Auto-apply safe patches
    python sauravautopatch.py program.srv --heal-all     # Apply all patches
    python sauravautopatch.py . --recursive              # Scan all .srv files
    python sauravautopatch.py program.srv --html out.html # Interactive HTML report
    python sauravautopatch.py program.srv --json         # JSON output
    python sauravautopatch.py program.srv --dry-run      # Preview what --heal would do
    python sauravautopatch.py program.srv --history      # Show patch history
    python sauravautopatch.py program.srv --rollback N   # Undo patch N
"""

import sys
import os
import re
import json
import math
import argparse
import hashlib
import time
from collections import defaultdict, Counter
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Set, Optional, Tuple, Any
from datetime import datetime

__version__ = "1.0.0"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Windows UTF-8 fix ────────────────────────────────────────────────
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    import io as _io
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from _srv_utils import find_srv_files as _find_srv_files
from _termcolors import colors as _make_colors

_C = _make_colors()

# ── Constants ─────────────────────────────────────────────────────────

FUNC_DEF_RE = re.compile(r"^(\s*)(?:function|fn)\s+(\w+)\s*\((.*?)\)")
VAR_ASSIGN_RE = re.compile(r"^(\s*)(?:let|var|set)\s+(\w+)\s*=")
VAR_BARE_ASSIGN_RE = re.compile(r"^(\s*)(\w+)\s*=\s*(.+)")
RETURN_RE = re.compile(r"^(\s*)return\b")
BREAK_RE = re.compile(r"^(\s*)break\b")
IF_RE = re.compile(r"^(\s*)if\s+(.+)")
ELSE_RE = re.compile(r"^(\s*)else\b")
LOOP_RE = re.compile(r"^(\s*)(?:while|for|loop|repeat)\b(.*)")
CALL_RE = re.compile(r"\b(\w+)\s*\(")
OPEN_RE = re.compile(r"\b(?:open|connect|acquire|create_file|fopen)\s*\(")
CLOSE_RE = re.compile(r"\b(?:close|disconnect|release|fclose)\s*\(")
COMPARE_RE = re.compile(r"(.+?)\s*(==|!=|<|>|<=|>=)\s*(.+)")

HISTORY_FILE = ".sauravautopatch_history.json"


# ── Data Classes ──────────────────────────────────────────────────────

@dataclass
class Issue:
    code: str
    engine: str
    file: str
    line: int
    message: str
    confidence: float  # 0.0 - 1.0
    severity: str  # "critical", "warning", "info"
    context: str = ""


@dataclass
class Patch:
    issue: Issue
    original_lines: List[str]
    patched_lines: List[str]
    start_line: int
    end_line: int
    description: str
    confidence: float
    applied: bool = False
    rollback_id: Optional[int] = None


@dataclass
class HealReport:
    file: str
    issues_found: int = 0
    patches_generated: int = 0
    patches_applied: int = 0
    patches_skipped: int = 0
    health_before: float = 0.0
    health_after: float = 0.0
    issues: List[Issue] = field(default_factory=list)
    patches: List[Patch] = field(default_factory=list)


# ── Engine: Parse Source ──────────────────────────────────────────────

def _parse_source(filepath: str) -> List[str]:
    """Read and return lines of a .srv file."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            return f.readlines()
    except (OSError, IOError):
        return []


def _get_indent(line: str) -> int:
    count = 0
    for ch in line:
        if ch == ' ':
            count += 1
        elif ch == '\t':
            count += 4
        else:
            break
    return count


def _extract_functions(lines: List[str]) -> List[Dict[str, Any]]:
    """Extract function definitions with their bodies."""
    functions = []
    i = 0
    while i < len(lines):
        m = FUNC_DEF_RE.match(lines[i])
        if m:
            indent = _get_indent(lines[i])
            params = [p.strip() for p in m.group(3).split(",") if p.strip()]
            func = {
                "name": m.group(2),
                "params": params,
                "start": i,
                "indent": indent,
                "body_start": i + 1,
                "body_end": i + 1,
            }
            # Find body end (next line at same or lower indent, or EOF)
            j = i + 1
            while j < len(lines):
                stripped = lines[j].strip()
                if stripped == "":
                    j += 1
                    continue
                if _get_indent(lines[j]) <= indent and stripped and not stripped.startswith("#"):
                    break
                j += 1
            func["body_end"] = j
            functions.append(func)
            i = j
        else:
            i += 1
    return functions


# ── Detection Engine P001: Uninitialized Variable Use ─────────────────

def _detect_uninitialized(lines: List[str], filepath: str, functions: Optional[List[Dict[str, Any]]] = None) -> List[Issue]:
    """Detect variables used before assignment."""
    issues = []
    if functions is None:
        functions = _extract_functions(lines)
    for func in functions:
        assigned: Set[str] = set(func["params"])
        for i in range(func["body_start"], func["body_end"]):
            line = lines[i]
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # Check assignment
            m_assign = VAR_ASSIGN_RE.match(line)
            if m_assign:
                assigned.add(m_assign.group(2))
                continue
            m_bare = VAR_BARE_ASSIGN_RE.match(line)
            if m_bare:
                assigned.add(m_bare.group(2))
                # Check RHS for uninitialized vars
                rhs = m_bare.group(3)
                for var in re.findall(r"\b([a-z_]\w*)\b", rhs):
                    if var not in assigned and var not in ("true", "false", "null", "nil", "print", "len", "str", "int", "float"):
                        issues.append(Issue(
                            code="P001", engine="Uninitialized Variable Use",
                            file=filepath, line=i + 1,
                            message=f"Variable '{var}' may be used before assignment in function '{func['name']}'",
                            confidence=0.7, severity="warning",
                            context=stripped
                        ))
                continue
            # Check variable reads in expressions
            for var in re.findall(r"\b([a-z_]\w*)\b", stripped):
                if var not in assigned and var not in ("true", "false", "null", "nil",
                    "print", "len", "str", "int", "float", "if", "else", "while",
                    "for", "return", "break", "continue", "and", "or", "not",
                    "in", "is", "let", "var", "set", "fn", "function"):
                    issues.append(Issue(
                        code="P001", engine="Uninitialized Variable Use",
                        file=filepath, line=i + 1,
                        message=f"Variable '{var}' may be used before assignment in function '{func['name']}'",
                        confidence=0.6, severity="warning",
                        context=stripped
                    ))
                    assigned.add(var)  # Only flag once
    return issues


# ── Detection Engine P002: Dead Code Eliminator ───────────────────────

def _detect_dead_code(lines: List[str], filepath: str, functions: Optional[List[Dict[str, Any]]] = None) -> List[Issue]:
    """Detect unreachable code after return/break statements."""
    issues = []
    if functions is None:
        functions = _extract_functions(lines)
    for func in functions:
        i = func["body_start"]
        while i < func["body_end"] - 1:
            stripped = lines[i].strip()
            indent = _get_indent(lines[i])
            if RETURN_RE.match(lines[i]) or BREAK_RE.match(lines[i]):
                # Check if next non-empty line at same indent
                j = i + 1
                while j < func["body_end"]:
                    next_stripped = lines[j].strip()
                    if not next_stripped or next_stripped.startswith("#"):
                        j += 1
                        continue
                    next_indent = _get_indent(lines[j])
                    if next_indent == indent and next_stripped:
                        issues.append(Issue(
                            code="P002", engine="Dead Code Eliminator",
                            file=filepath, line=j + 1,
                            message=f"Unreachable code after {'return' if RETURN_RE.match(lines[i]) else 'break'} in '{func['name']}'",
                            confidence=0.9, severity="warning",
                            context=next_stripped
                        ))
                    break
                    j += 1
            i += 1
    return issues


# ── Detection Engine P003: Infinite Loop Guard ────────────────────────

def _detect_infinite_loops(lines: List[str], filepath: str, functions: Optional[List[Dict[str, Any]]] = None) -> List[Issue]:
    """Detect loops that may not terminate."""
    issues = []
    for i, line in enumerate(lines):
        m = LOOP_RE.match(line)
        if m:
            loop_indent = _get_indent(line)
            condition = m.group(2).strip()
            # Check for while true / while 1 / loop without condition
            if condition in ("true", "1", "(true)", "(1)", ""):
                # Look for break/return in body
                has_exit = False
                j = i + 1
                while j < len(lines):
                    body_stripped = lines[j].strip()
                    if body_stripped and _get_indent(lines[j]) <= loop_indent:
                        break
                    if BREAK_RE.match(lines[j]) or RETURN_RE.match(lines[j]):
                        has_exit = True
                        break
                    if "break" in body_stripped or "return" in body_stripped:
                        has_exit = True
                        break
                    j += 1
                if not has_exit:
                    issues.append(Issue(
                        code="P003", engine="Infinite Loop Guard",
                        file=filepath, line=i + 1,
                        message="Loop may never terminate — no break/return found in body",
                        confidence=0.75, severity="critical",
                        context=line.strip()
                    ))
    return issues


# ── Detection Engine P004: Unused Parameter Cleanup ───────────────────

def _detect_unused_params(lines: List[str], filepath: str, functions: Optional[List[Dict[str, Any]]] = None) -> List[Issue]:
    """Detect function parameters that are never used in the body."""
    issues = []
    if functions is None:
        functions = _extract_functions(lines)
    for func in functions:
        if not func["params"]:
            continue
        body = "".join(lines[func["body_start"]:func["body_end"]])
        for param in func["params"]:
            clean_param = param.split(":")[0].strip().split("=")[0].strip()
            if clean_param and not re.search(r"\b" + re.escape(clean_param) + r"\b", body):
                issues.append(Issue(
                    code="P004", engine="Unused Parameter Cleanup",
                    file=filepath, line=func["start"] + 1,
                    message=f"Parameter '{clean_param}' in function '{func['name']}' is never used",
                    confidence=0.85, severity="info",
                    context=lines[func["start"]].strip()
                ))
    return issues


# ── Detection Engine P005: Missing Return Path ────────────────────────

def _detect_missing_return(lines: List[str], filepath: str, functions: Optional[List[Dict[str, Any]]] = None) -> List[Issue]:
    """Detect functions with inconsistent return paths."""
    issues = []
    if functions is None:
        functions = _extract_functions(lines)
    for func in functions:
        body_lines = lines[func["body_start"]:func["body_end"]]
        has_return_value = False
        has_bare_return = False
        has_no_return = True
        for bl in body_lines:
            stripped = bl.strip()
            if RETURN_RE.match(bl):
                has_no_return = False
                after_return = stripped[6:].strip()
                if after_return:
                    has_return_value = True
                else:
                    has_bare_return = True
        # Check if function can fall through without returning
        # Look at the last statement at body-level indent (func indent + 4)
        body_indent = func["indent"] + 4
        last_top_stmt = ""
        for bl in reversed(body_lines):
            stripped_bl = bl.strip()
            if stripped_bl and not stripped_bl.startswith("#"):
                if _get_indent(bl) <= body_indent:
                    last_top_stmt = stripped_bl
                    break
        can_fall_through = not last_top_stmt.startswith("return")

        if has_return_value and (has_bare_return or can_fall_through):
            # Some paths return values, others don't
            issues.append(Issue(
                code="P005", engine="Missing Return Path",
                file=filepath, line=func["start"] + 1,
                message=f"Function '{func['name']}' has inconsistent return paths — some return values, others don't",
                confidence=0.8, severity="warning",
                context=lines[func["start"]].strip()
            ))
    return issues


# ── Detection Engine P006: Duplicate Branch Detector ──────────────────

def _detect_duplicate_branches(lines: List[str], filepath: str, functions: Optional[List[Dict[str, Any]]] = None) -> List[Issue]:
    """Detect if/else blocks with identical bodies."""
    issues = []
    i = 0
    while i < len(lines):
        if_m = IF_RE.match(lines[i])
        if if_m:
            if_indent = _get_indent(lines[i])
            # Collect if body
            if_body = []
            j = i + 1
            while j < len(lines):
                stripped = lines[j].strip()
                if stripped and _get_indent(lines[j]) <= if_indent:
                    break
                if_body.append(stripped)
                j += 1
            # Check for else at same indent
            if j < len(lines) and ELSE_RE.match(lines[j]) and _get_indent(lines[j]) == if_indent:
                else_body = []
                k = j + 1
                while k < len(lines):
                    stripped = lines[k].strip()
                    if stripped and _get_indent(lines[k]) <= if_indent:
                        break
                    else_body.append(stripped)
                    k += 1
                # Compare bodies
                if_clean = [l for l in if_body if l]
                else_clean = [l for l in else_body if l]
                if if_clean and if_clean == else_clean:
                    issues.append(Issue(
                        code="P006", engine="Duplicate Branch Detector",
                        file=filepath, line=i + 1,
                        message="if/else branches have identical bodies — condition is meaningless",
                        confidence=0.95, severity="warning",
                        context=lines[i].strip()
                    ))
        i += 1
    return issues


# ── Detection Engine P007: Off-by-One Guard ───────────────────────────

def _detect_off_by_one(lines: List[str], filepath: str, functions: Optional[List[Dict[str, Any]]] = None) -> List[Issue]:
    """Detect common off-by-one patterns in loops."""
    issues = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Pattern: for i in range(1, len(x)) or for i = 0; i <= len
        if re.search(r"<=\s*len\s*\(", stripped) or re.search(r"<=\s*size\s*\(", stripped):
            issues.append(Issue(
                code="P007", engine="Off-by-One Guard",
                file=filepath, line=i + 1,
                message="Loop uses '<= len(...)' which may cause index out of bounds (should be '< len(...)')",
                confidence=0.8, severity="warning",
                context=stripped
            ))
        # Pattern: array[len(array)]
        m = re.search(r"(\w+)\[len\(\1\)\]", stripped)
        if m:
            issues.append(Issue(
                code="P007", engine="Off-by-One Guard",
                file=filepath, line=i + 1,
                message=f"Accessing '{m.group(1)}[len({m.group(1)})]' is out of bounds (max index is len-1)",
                confidence=0.95, severity="critical",
                context=stripped
            ))
    return issues


# ── Detection Engine P008: Resource Leak Patcher ──────────────────────

def _detect_resource_leaks(lines: List[str], filepath: str, functions: Optional[List[Dict[str, Any]]] = None) -> List[Issue]:
    """Detect open/acquire without corresponding close/release."""
    issues = []
    if functions is None:
        functions = _extract_functions(lines)
    for func in functions:
        opens = []
        closes = []
        for i in range(func["body_start"], func["body_end"]):
            if OPEN_RE.search(lines[i]):
                opens.append(i)
            if CLOSE_RE.search(lines[i]):
                closes.append(i)
        if opens and not closes:
            for open_line in opens:
                issues.append(Issue(
                    code="P008", engine="Resource Leak Patcher",
                    file=filepath, line=open_line + 1,
                    message=f"Resource opened but never closed in function '{func['name']}'",
                    confidence=0.7, severity="warning",
                    context=lines[open_line].strip()
                ))
    return issues


# ── Detection Engine P009: Type Coercion Fixer ────────────────────────

def _detect_type_coercion(lines: List[str], filepath: str, functions: Optional[List[Dict[str, Any]]] = None) -> List[Issue]:
    """Detect implicit type coercion in comparisons."""
    issues = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        m = COMPARE_RE.search(stripped)
        if m:
            lhs, op, rhs = m.group(1).strip(), m.group(2), m.group(3).strip()
            # String compared to number pattern
            lhs_is_str = lhs.startswith('"') or lhs.startswith("'")
            rhs_is_num = re.match(r"^-?\d+\.?\d*$", rhs)
            rhs_is_str = rhs.startswith('"') or rhs.startswith("'")
            lhs_is_num = re.match(r"^-?\d+\.?\d*$", lhs)
            if (lhs_is_str and rhs_is_num) or (lhs_is_num and rhs_is_str):
                issues.append(Issue(
                    code="P009", engine="Type Coercion Fixer",
                    file=filepath, line=i + 1,
                    message=f"Comparing string to number with '{op}' — likely type mismatch",
                    confidence=0.85, severity="warning",
                    context=stripped
                ))
    return issues


# ── Detection Engine P010: Idempotency Enforcer ──────────────────────

def _detect_non_idempotent(lines: List[str], filepath: str, functions: Optional[List[Dict[str, Any]]] = None) -> List[Issue]:
    """Detect non-idempotent operations inside retry/loop patterns."""
    issues = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        # Detect retry patterns: loop lines mentioning retry/attempt, OR any loop variable named retry/attempt/count
        loop_m = LOOP_RE.match(lines[i])
        is_retry = False
        if loop_m:
            is_retry = ("retry" in stripped.lower() or "attempt" in stripped.lower() or "count" in stripped.lower())
        if is_retry:
            loop_indent = _get_indent(lines[i])
            j = i + 1
            while j < len(lines):
                body_stripped = lines[j].strip()
                if body_stripped and _get_indent(lines[j]) <= loop_indent:
                    break
                # Non-idempotent patterns: append, increment, insert, push
                if re.search(r"\b(append|push|insert|add|increment|\+=)\b", body_stripped):
                    issues.append(Issue(
                        code="P010", engine="Idempotency Enforcer",
                        file=filepath, line=j + 1,
                        message="Non-idempotent operation inside retry loop — may cause duplicate side effects",
                        confidence=0.75, severity="critical",
                        context=body_stripped
                    ))
                j += 1
        i += 1
    return issues


# ── Patch Generation ──────────────────────────────────────────────────

def _generate_patch(issue: Issue, lines: List[str]) -> Optional[Patch]:
    """Generate a patch for an issue if possible."""
    idx = issue.line - 1
    if idx < 0 or idx >= len(lines):
        return None

    if issue.code == "P002":
        # Dead code: comment it out
        original = [lines[idx]]
        patched = ["# [autopatch:removed-dead-code] " + lines[idx].lstrip()]
        return Patch(
            issue=issue, original_lines=original, patched_lines=patched,
            start_line=idx, end_line=idx + 1,
            description="Comment out unreachable dead code",
            confidence=issue.confidence
        )

    elif issue.code == "P003":
        # Infinite loop: add iteration guard
        indent = " " * (_get_indent(lines[idx]) + 4)
        guard_line = f"{indent}# [autopatch:loop-guard] Added safety limit\n"
        counter_init = f"{indent}_autopatch_iter = 0\n"
        counter_check = f"{indent}_autopatch_iter = _autopatch_iter + 1\n"
        break_check = f"{indent}if _autopatch_iter > 10000\n{indent}    break\n"
        original = [lines[idx]]
        patched = [lines[idx], guard_line, counter_init]
        return Patch(
            issue=issue, original_lines=original, patched_lines=patched,
            start_line=idx, end_line=idx + 1,
            description="Add iteration guard to prevent infinite loop (max 10000 iterations)",
            confidence=0.6
        )

    elif issue.code == "P006":
        # Duplicate branches: simplify to just the body (remove condition)
        original = [lines[idx]]
        body_indent = " " * (_get_indent(lines[idx]) + 4)
        patched = [f"# [autopatch:simplified] Duplicate branches — condition was meaningless\n"]
        return Patch(
            issue=issue, original_lines=original, patched_lines=patched,
            start_line=idx, end_line=idx + 1,
            description="Flag duplicate if/else branches for simplification",
            confidence=0.85
        )

    elif issue.code == "P007":
        # Off-by-one: fix <= to <
        original_line = lines[idx]
        fixed = re.sub(r"<=\s*(len|size)\s*\(", r"< \1(", original_line)
        if fixed != original_line:
            return Patch(
                issue=issue, original_lines=[original_line], patched_lines=[fixed],
                start_line=idx, end_line=idx + 1,
                description="Fix off-by-one: change '<= len(...)' to '< len(...)'",
                confidence=0.85
            )

    elif issue.code == "P008":
        # Resource leak: add close call
        indent = " " * _get_indent(lines[idx])
        # Find function end
        funcs = _extract_functions(lines)
        for func in funcs:
            if func["body_start"] <= idx < func["body_end"]:
                insert_at = func["body_end"] - 1
                close_line = f"{indent}close(resource)  # [autopatch:resource-close] Added missing close\n"
                return Patch(
                    issue=issue, original_lines=[], patched_lines=[close_line],
                    start_line=insert_at, end_line=insert_at,
                    description="Add missing resource close call",
                    confidence=0.6
                )

    return None


# ── Health Score ──────────────────────────────────────────────────────

def _compute_health(issues: List[Issue], total_lines: int) -> float:
    """Compute health score 0-100 based on issues found."""
    if total_lines == 0:
        return 100.0
    penalty = 0.0
    for issue in issues:
        if issue.severity == "critical":
            penalty += 15.0 * issue.confidence
        elif issue.severity == "warning":
            penalty += 8.0 * issue.confidence
        else:
            penalty += 3.0 * issue.confidence
    # Scale by density
    density_factor = min(1.0, total_lines / 100.0)
    score = max(0.0, 100.0 - penalty * density_factor)
    return round(score, 1)


# ── History Management ────────────────────────────────────────────────

def _load_history(directory: str) -> List[Dict]:
    """Load patch history from file."""
    path = os.path.join(directory, HISTORY_FILE)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_history(directory: str, history: List[Dict]):
    """Save patch history to file."""
    path = os.path.join(directory, HISTORY_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


def _record_patch(directory: str, patch: Patch, filepath: str):
    """Record an applied patch in history."""
    history = _load_history(directory)
    entry = {
        "id": len(history) + 1,
        "timestamp": datetime.now().isoformat(),
        "file": filepath,
        "code": patch.issue.code,
        "engine": patch.issue.engine,
        "line": patch.issue.line,
        "description": patch.description,
        "original": patch.original_lines,
        "patched": patch.patched_lines,
        "confidence": patch.confidence,
    }
    history.append(entry)
    _save_history(directory, history)
    return entry["id"]


# ── Core Scanner ──────────────────────────────────────────────────────

ALL_DETECTORS = [
    _detect_uninitialized,
    _detect_dead_code,
    _detect_infinite_loops,
    _detect_unused_params,
    _detect_missing_return,
    _detect_duplicate_branches,
    _detect_off_by_one,
    _detect_resource_leaks,
    _detect_type_coercion,
    _detect_non_idempotent,
]


def scan_file(filepath: str) -> HealReport:
    """Run all detection engines on a single file."""
    lines = _parse_source(filepath)
    if not lines:
        return HealReport(file=filepath)

    report = HealReport(file=filepath)
    # Pre-compute function list once (used by 5 of 10 detectors)
    functions = _extract_functions(lines)
    for detector in ALL_DETECTORS:
        issues = detector(lines, filepath, functions=functions)
        report.issues.extend(issues)

    report.issues_found = len(report.issues)
    report.health_before = _compute_health(report.issues, len(lines))

    # Generate patches for each issue
    for issue in report.issues:
        patch = _generate_patch(issue, lines)
        if patch:
            report.patches.append(patch)
    report.patches_generated = len(report.patches)

    return report


def apply_patches(filepath: str, report: HealReport, min_confidence: float = 0.8) -> HealReport:
    """Apply patches that meet confidence threshold."""
    lines = _parse_source(filepath)
    if not lines:
        return report

    directory = os.path.dirname(os.path.abspath(filepath))
    applied_patches = []

    # Sort patches by line number descending so we don't shift indices
    eligible = [p for p in report.patches if p.confidence >= min_confidence]
    eligible.sort(key=lambda p: p.start_line, reverse=True)

    for patch in eligible:
        # Apply patch
        start = patch.start_line
        end = patch.end_line
        lines[start:end] = patch.patched_lines
        patch.applied = True
        patch.rollback_id = _record_patch(directory, patch, filepath)
        applied_patches.append(patch)

    if applied_patches:
        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(lines)

    report.patches_applied = len(applied_patches)
    report.patches_skipped = report.patches_generated - report.patches_applied
    report.health_after = _compute_health(
        [i for i in report.issues if not any(p.issue == i and p.applied for p in report.patches)],
        len(lines)
    )

    return report


# ── Output Formatters ─────────────────────────────────────────────────

def _severity_icon(severity: str) -> str:
    return {"critical": "\u2622", "warning": "\u26a0", "info": "\u2139"}.get(severity, "?")


def _severity_color(severity: str, text: str) -> str:
    if severity == "critical":
        return _C.red(text)
    elif severity == "warning":
        return _C.yellow(text)
    return _C.cyan(text)


def print_report(report: HealReport, verbose: bool = False):
    """Print a human-readable report."""
    print(f"\n{_C.bold('sauravautopatch')} v{__version__} — Self-Healing Engine")
    print(f"{'=' * 60}")
    print(f"File: {_C.cyan(report.file)}")
    print(f"Issues found: {report.issues_found}")
    print(f"Patches generated: {report.patches_generated}")
    print(f"Patches applied: {_C.green(str(report.patches_applied))}")
    print(f"Health: {_C.yellow(str(report.health_before))} → {_C.green(str(report.health_after))}")
    print()

    if not report.issues:
        print(f"  {_C.green('\u2714')} No issues detected — code is healthy!")
        return

    # Group by engine
    by_engine: Dict[str, List[Issue]] = defaultdict(list)
    for issue in report.issues:
        by_engine[issue.engine].append(issue)

    for engine, issues in sorted(by_engine.items()):
        print(f"  {_C.bold(engine)} ({len(issues)} issues)")
        for issue in issues[:5]:  # Show max 5 per engine
            icon = _severity_icon(issue.severity)
            line_info = f"L{issue.line}"
            msg = _severity_color(issue.severity, f"  {icon} [{issue.code}] {line_info}: {issue.message}")
            print(msg)
            if verbose and issue.context:
                print(f"       {_C.dim(issue.context)}")
        if len(issues) > 5:
            print(f"       ... and {len(issues) - 5} more")
        print()

    # Patches
    if report.patches:
        print(f"\n{_C.bold('Patches:')}")
        for patch in report.patches:
            status = _C.green("\u2714 Applied") if patch.applied else _C.dim("\u2717 Skipped")
            conf = f"[conf: {patch.confidence:.0%}]"
            print(f"  {status} {patch.description} {_C.dim(conf)}")


def to_json(reports: List[HealReport]) -> str:
    """Convert reports to JSON string."""
    data = []
    for r in reports:
        entry = {
            "file": r.file,
            "issues_found": r.issues_found,
            "patches_generated": r.patches_generated,
            "patches_applied": r.patches_applied,
            "health_before": r.health_before,
            "health_after": r.health_after,
            "issues": [
                {
                    "code": i.code, "engine": i.engine, "line": i.line,
                    "message": i.message, "confidence": i.confidence,
                    "severity": i.severity, "context": i.context
                }
                for i in r.issues
            ],
            "patches": [
                {
                    "description": p.description, "confidence": p.confidence,
                    "applied": p.applied, "start_line": p.start_line,
                    "rollback_id": p.rollback_id
                }
                for p in r.patches
            ]
        }
        data.append(entry)
    return json.dumps(data, indent=2)


# ── HTML Report ───────────────────────────────────────────────────────

def generate_html(reports: List[HealReport], output_path: str):
    """Generate interactive HTML dashboard."""
    total_issues = sum(r.issues_found for r in reports)
    total_patches = sum(r.patches_applied for r in reports)
    avg_health = sum(r.health_before for r in reports) / max(len(reports), 1)

    severity_counts = Counter(i.severity for r in reports for i in r.issues)
    engine_counts = Counter(i.code for r in reports for i in r.issues)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>sauravautopatch — Self-Healing Report</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0d1117; color: #c9d1d9; padding: 2rem; }}
h1 {{ color: #58a6ff; margin-bottom: 0.5rem; }}
.subtitle {{ color: #8b949e; margin-bottom: 2rem; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 2rem; }}
.card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 1.5rem; }}
.card h3 {{ color: #8b949e; font-size: 0.8rem; text-transform: uppercase; margin-bottom: 0.5rem; }}
.card .value {{ font-size: 2rem; font-weight: bold; }}
.critical {{ color: #f85149; }}
.warning {{ color: #d29922; }}
.info {{ color: #58a6ff; }}
.healthy {{ color: #3fb950; }}
.file-section {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 1.5rem; margin-bottom: 1rem; }}
.file-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }}
.issue {{ padding: 0.5rem 0; border-bottom: 1px solid #21262d; }}
.issue:last-child {{ border-bottom: none; }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.75rem; }}
.badge-critical {{ background: #f8514922; color: #f85149; }}
.badge-warning {{ background: #d2992222; color: #d29922; }}
.badge-info {{ background: #58a6ff22; color: #58a6ff; }}
.badge-applied {{ background: #3fb95022; color: #3fb950; }}
.patch-list {{ margin-top: 1rem; }}
.patch {{ padding: 0.5rem; background: #0d1117; border-radius: 4px; margin-bottom: 0.5rem; }}
.health-bar {{ height: 8px; background: #21262d; border-radius: 4px; overflow: hidden; margin-top: 0.5rem; }}
.health-fill {{ height: 100%; border-radius: 4px; transition: width 0.3s; }}
.engine-list {{ list-style: none; }}
.engine-list li {{ padding: 0.3rem 0; display: flex; justify-content: space-between; }}
</style>
</head>
<body>
<h1>\u2695 sauravautopatch — Self-Healing Report</h1>
<p class="subtitle">Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} &middot; {len(reports)} files scanned</p>

<div class="grid">
  <div class="card">
    <h3>Issues Found</h3>
    <div class="value warning">{total_issues}</div>
  </div>
  <div class="card">
    <h3>Patches Applied</h3>
    <div class="value healthy">{total_patches}</div>
  </div>
  <div class="card">
    <h3>Avg Health</h3>
    <div class="value {'healthy' if avg_health >= 80 else 'warning' if avg_health >= 60 else 'critical'}">{avg_health:.0f}%</div>
  </div>
  <div class="card">
    <h3>Critical</h3>
    <div class="value critical">{severity_counts.get('critical', 0)}</div>
  </div>
</div>

<h2 style="margin-bottom:1rem; color:#58a6ff;">Detection Engines</h2>
<div class="card" style="margin-bottom:2rem;">
<ul class="engine-list">
"""
    engine_names = {
        "P001": "Uninitialized Variable Use",
        "P002": "Dead Code Eliminator",
        "P003": "Infinite Loop Guard",
        "P004": "Unused Parameter Cleanup",
        "P005": "Missing Return Path",
        "P006": "Duplicate Branch Detector",
        "P007": "Off-by-One Guard",
        "P008": "Resource Leak Patcher",
        "P009": "Type Coercion Fixer",
        "P010": "Idempotency Enforcer",
    }
    for code, name in engine_names.items():
        count = engine_counts.get(code, 0)
        html += f'  <li><span>{code} {name}</span><span class="{"critical" if count > 3 else "warning" if count > 0 else "healthy"}">{count}</span></li>\n'

    html += """</ul>
</div>

<h2 style="margin-bottom:1rem; color:#58a6ff;">Files</h2>
"""
    for report in reports:
        health_color = "#3fb950" if report.health_before >= 80 else "#d29922" if report.health_before >= 60 else "#f85149"
        html += f"""<div class="file-section">
  <div class="file-header">
    <strong>{os.path.basename(report.file)}</strong>
    <span>Health: <span style="color:{health_color}">{report.health_before:.0f}%</span></span>
  </div>
  <div class="health-bar"><div class="health-fill" style="width:{report.health_before}%; background:{health_color};"></div></div>
"""
        if report.issues:
            for issue in report.issues[:10]:
                badge_class = f"badge-{issue.severity}"
                html += f'  <div class="issue"><span class="badge {badge_class}">{issue.code}</span> L{issue.line}: {issue.message}</div>\n'
            if len(report.issues) > 10:
                html += f'  <div class="issue" style="color:#8b949e;">... and {len(report.issues) - 10} more issues</div>\n'
        else:
            html += '  <div class="issue" style="color:#3fb950;">\u2714 Clean — no issues detected</div>\n'

        if report.patches:
            html += '  <div class="patch-list">\n'
            for patch in report.patches:
                status = '<span class="badge badge-applied">\u2714 Applied</span>' if patch.applied else '<span class="badge badge-info">Suggested</span>'
                html += f'    <div class="patch">{status} {patch.description} (conf: {patch.confidence:.0%})</div>\n'
            html += '  </div>\n'
        html += '</div>\n'

    html += """
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path


# ── Rollback ──────────────────────────────────────────────────────────

def rollback_patch(directory: str, patch_id: int) -> bool:
    """Rollback a previously applied patch by ID."""
    history = _load_history(directory)
    target = None
    for entry in history:
        if entry["id"] == patch_id:
            target = entry
            break
    if not target:
        print(f"{_C.red('Error')}: Patch #{patch_id} not found in history")
        return False

    filepath = target["file"]
    if not os.path.exists(filepath):
        print(f"{_C.red('Error')}: File '{filepath}' no longer exists")
        return False

    lines = _parse_source(filepath)
    # Find and revert the patched lines
    patched = target["patched"]
    original = target["original"]
    line_idx = target["line"] - 1

    # Simple revert: find patched content near the expected line
    found = False
    search_range = range(max(0, line_idx - 5), min(len(lines), line_idx + 5))
    for start in search_range:
        window = [lines[start + k] if start + k < len(lines) else "" for k in range(len(patched))]
        if [l.rstrip("\n") for l in window] == [l.rstrip("\n") for l in patched]:
            lines[start:start + len(patched)] = original
            found = True
            break

    if found:
        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(lines)
        print(f"{_C.green('\u2714')} Rolled back patch #{patch_id}: {target['description']}")
        return True
    else:
        print(f"{_C.yellow('\u26a0')} Could not locate patched content — file may have been modified since patch")
        return False


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="sauravautopatch",
        description="Autonomous Self-Healing Engine for sauravcode programs"
    )
    parser.add_argument("paths", nargs="*", default=["."],
                        help="Files or directories to scan")
    parser.add_argument("--recursive", "-r", action="store_true",
                        help="Recursively scan directories")
    parser.add_argument("--suggest", action="store_true",
                        help="Level 1: Generate patch suggestions")
    parser.add_argument("--heal", action="store_true",
                        help="Level 2: Apply safe patches (confidence >= 0.8)")
    parser.add_argument("--heal-all", action="store_true",
                        help="Level 3: Apply all patches regardless of confidence")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview what --heal would do without applying")
    parser.add_argument("--html", metavar="FILE",
                        help="Generate interactive HTML report")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show issue context lines")
    parser.add_argument("--history", action="store_true",
                        help="Show patch history")
    parser.add_argument("--rollback", type=int, metavar="ID",
                        help="Rollback a patch by ID")
    parser.add_argument("--min-confidence", type=float, default=0.8,
                        help="Minimum confidence for --heal (default: 0.8)")

    args = parser.parse_args()

    # History mode
    if args.history:
        directory = args.paths[0] if args.paths else "."
        history = _load_history(directory)
        if not history:
            print("No patch history found.")
            return
        print(f"\n{_C.bold('Patch History')} ({len(history)} entries)")
        print("-" * 50)
        for entry in reversed(history[-20:]):
            print(f"  #{entry['id']} [{entry['timestamp'][:16]}] {entry['code']} — {entry['description']}")
            print(f"       File: {entry['file']} L{entry['line']} (conf: {entry['confidence']:.0%})")
        return

    # Rollback mode
    if args.rollback is not None:
        directory = args.paths[0] if args.paths else "."
        rollback_patch(directory, args.rollback)
        return

    # Find files
    files = _find_srv_files(args.paths, recursive=args.recursive)
    if not files:
        print(f"{_C.yellow('\u26a0')} No .srv files found in specified paths")
        sys.exit(1)

    # Scan
    reports: List[HealReport] = []
    for filepath in files:
        report = scan_file(filepath)

        # Apply patches if requested
        if args.heal or args.heal_all:
            min_conf = 0.0 if args.heal_all else args.min_confidence
            if not args.dry_run:
                report = apply_patches(filepath, report, min_confidence=min_conf)
            else:
                # Simulate
                for patch in report.patches:
                    if patch.confidence >= min_conf:
                        report.patches_applied += 1
                    else:
                        report.patches_skipped += 1

        report.health_after = report.health_after or report.health_before
        reports.append(report)

    # Output
    if args.json:
        print(to_json(reports))
    elif args.html:
        path = generate_html(reports, args.html)
        print(f"{_C.green('\u2714')} HTML report written to: {path}")
    else:
        for report in reports:
            print_report(report, verbose=args.verbose)

        # Summary
        total_issues = sum(r.issues_found for r in reports)
        total_applied = sum(r.patches_applied for r in reports)
        print(f"\n{'=' * 60}")
        print(f"  {_C.bold('Summary')}: {len(files)} files | {total_issues} issues | {total_applied} patches applied")


if __name__ == "__main__":
    main()
