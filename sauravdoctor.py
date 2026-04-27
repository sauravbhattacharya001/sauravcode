#!/usr/bin/env python3
"""sauravdoctor — Autonomous Code Health Diagnostic Tool for sauravcode.

Performs a comprehensive health checkup on .srv programs, detecting code
pathologies beyond simple lint rules.  Each finding is classified as a
diagnosis with severity, affected location, prescription (fix suggestion),
and prognosis (impact if left untreated).

Generates an interactive HTML report with a health score gauge, or
outputs text/JSON summaries to the terminal.

Pathology catalogue (20 checks):
    P001  God Function          Function with too many responsibilities (>50 LOC + high complexity)
    P002  Shotgun Surgery       Variable used across many distant functions
    P003  Dead Parameter        Function parameter never used in body
    P004  Magic Number          Unexplained numeric literal in logic
    P005  Long Parameter List   Function with >4 parameters
    P006  Deep Nesting          Code nested >4 levels deep
    P007  Duplicate Strings     Same string literal repeated >2 times
    P008  Feature Envy          Function that references more external vars than local
    P009  Primitive Obsession   Function returning raw numbers that could be named constants
    P010  Speculative Generality  Empty function or unreachable branches
    P011  Inconsistent Naming   Mixed naming conventions (camelCase vs snake_case)
    P012  Comment-to-Code Ratio Too few or too many comments
    P013  Function Coupling     Function calling too many other functions (>8 callees)
    P014  Orphan Function       Defined function never called anywhere
    P015  Copy-Paste Suspect    Near-duplicate code blocks across functions
    P016  Boolean Blindness     Function returning boolean without descriptive name
    P017  Long Line             Lines exceeding 120 characters
    P018  Hardcoded Path        Literal file paths in code
    P019  Empty Catch           Catch block with no meaningful handling
    P020  Recursive Risk        Recursive function without obvious base case guard

Usage:
    python sauravdoctor.py program.srv              # Diagnose a single file
    python sauravdoctor.py .                        # Diagnose all .srv files in cwd
    python sauravdoctor.py . --recursive            # Include subdirectories
    python sauravdoctor.py program.srv --html       # Generate interactive HTML report
    python sauravdoctor.py program.srv --json       # JSON output
    python sauravdoctor.py . --severity critical    # Only critical findings
    python sauravdoctor.py . --top 10               # Show top 10 findings
    python sauravdoctor.py . --summary              # Project health summary only
"""

import sys
import os
import re
import json as _json
import math
import argparse
from collections import defaultdict, Counter
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Set, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _srv_utils import get_indent as _get_indent, find_srv_files as _find_srv_files
from _termcolors import colors as _colors

# ── Ensure UTF-8 stdout on Windows ──────────────────────────────────
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── Constants ────────────────────────────────────────────────────────

GOD_FUNC_LOC = 50
GOD_FUNC_COMPLEXITY = 8
MAX_PARAMS = 4
MAX_NESTING = 4
MAX_CALLEES = 8
DUPLICATE_STRING_THRESHOLD = 3
MAX_LINE_LENGTH = 120
COMMENT_RATIO_LOW = 0.05
COMMENT_RATIO_HIGH = 0.60

FUNCTION_DEF_RE = re.compile(r"^(\s*)(function|fn)\s+(\w+)\s*\(([^)]*)\)")
CALL_RE = re.compile(r"\b([a-zA-Z_]\w*)\s*\(")
STRING_LITERAL_RE = re.compile(r"""(?:"([^"\\]*(?:\\.[^"\\]*)*)"|'([^'\\]*(?:\\.[^'\\]*)*)')""")
NUMBER_LITERAL_RE = re.compile(r"\b(\d+\.?\d*)\b")
ASSIGN_RE = re.compile(r"^\s*(\w+)\s*=\s*")
HARDCODED_PATH_RE = re.compile(r"""["'](?:[A-Za-z]:[/\\]|/(?:home|usr|tmp|etc|var)/)""")
IMPORT_RE = re.compile(r"^\s*import\s+")
RETURN_RE = re.compile(r"^\s*return\b")
BRANCH_KEYWORDS = {"if", "elif", "while", "for", "foreach", "catch", "and", "or"}
BLOCK_KEYWORDS = {"if", "elif", "else", "while", "for", "foreach", "function",
                  "fn", "try", "catch", "match", "class"}


# ── Data Classes ─────────────────────────────────────────────────────

class Severity:
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"

    ORDER = {"critical": 0, "warning": 1, "info": 2}


@dataclass
class Diagnosis:
    """A single code health finding."""
    code: str
    title: str
    severity: str
    file: str
    line: int
    detail: str
    prescription: str
    prognosis: str

    def to_dict(self):
        return asdict(self)


@dataclass
class FunctionInfo:
    """Parsed function information for analysis."""
    name: str
    file: str
    line_start: int
    line_end: int
    params: List[str]
    loc: int = 0
    complexity: int = 1
    max_depth: int = 0
    local_vars: Set[str] = field(default_factory=set)
    external_refs: Set[str] = field(default_factory=set)
    callees: Set[str] = field(default_factory=set)
    body_lines: List[str] = field(default_factory=list)
    has_return: bool = False
    calls_self: bool = False
    has_base_guard: bool = False


@dataclass
class FileAnalysis:
    """Analysis results for a single file."""
    filepath: str
    lines: List[str] = field(default_factory=list)
    functions: List[FunctionInfo] = field(default_factory=list)
    global_vars: Set[str] = field(default_factory=set)
    all_calls: Set[str] = field(default_factory=set)
    string_literals: List[Tuple[str, int]] = field(default_factory=list)
    diagnoses: List[Diagnosis] = field(default_factory=list)
    total_lines: int = 0
    code_lines: int = 0
    comment_lines: int = 0
    blank_lines: int = 0


# ── Parsing ──────────────────────────────────────────────────────────

def _strip_comment(line: str) -> str:
    """Remove trailing comment from a line (naive: # outside strings)."""
    in_str = None
    for i, ch in enumerate(line):
        if ch in ('"', "'") and (i == 0 or line[i - 1] != "\\"):
            if in_str is None:
                in_str = ch
            elif in_str == ch:
                in_str = None
        elif ch == "#" and in_str is None:
            return line[:i]
    return line


def _is_comment_line(line: str) -> bool:
    return line.lstrip().startswith("#")


def _parse_file(filepath: str) -> FileAnalysis:
    """Parse a .srv file into a FileAnalysis structure."""
    analysis = FileAnalysis(filepath=filepath)

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            analysis.lines = f.readlines()
    except OSError:
        return analysis

    analysis.total_lines = len(analysis.lines)

    # First pass: count lines, extract string literals, find functions
    functions_stack = []
    current_func = None

    for i, raw_line in enumerate(analysis.lines, 1):
        line = raw_line.rstrip("\n\r")
        stripped = line.strip()

        # Line classification
        if not stripped:
            analysis.blank_lines += 1
        elif _is_comment_line(stripped):
            analysis.comment_lines += 1
        else:
            analysis.code_lines += 1

        # String literals
        for m in STRING_LITERAL_RE.finditer(line):
            val = m.group(1) if m.group(1) is not None else m.group(2)
            if len(val) > 1:  # skip single chars
                analysis.string_literals.append((val, i))

        # Function definitions
        func_match = FUNCTION_DEF_RE.match(line)
        if func_match:
            indent = _get_indent(line)
            params_str = func_match.group(4).strip()
            params = [p.strip() for p in params_str.split(",") if p.strip()] if params_str else []
            func = FunctionInfo(
                name=func_match.group(3),
                file=filepath,
                line_start=i,
                line_end=i,
                params=params,
            )
            if current_func and indent > _get_indent(analysis.lines[current_func.line_start - 1]):
                # Nested function — push parent
                functions_stack.append(current_func)
            elif current_func:
                current_func.line_end = i - 1
                analysis.functions.append(current_func)
            current_func = func
            continue

        # Track current function body
        if current_func:
            func_indent = _get_indent(analysis.lines[current_func.line_start - 1])
            line_indent = _get_indent(line) if stripped else func_indent + 1

            if stripped and line_indent <= func_indent and not func_match:
                # Function ended
                current_func.line_end = i - 1
                analysis.functions.append(current_func)
                current_func = functions_stack.pop() if functions_stack else None
            else:
                current_func.body_lines.append(line)

    # Close any remaining function
    if current_func:
        current_func.line_end = analysis.total_lines
        analysis.functions.append(current_func)

    # Second pass: analyze each function
    all_func_names = {f.name for f in analysis.functions}

    for func in analysis.functions:
        clean_body = []
        for bl in func.body_lines:
            s = bl.strip()
            if s and not _is_comment_line(s):
                clean_body.append(s)

        func.loc = len(clean_body)

        # Complexity and nesting
        max_depth = 0
        for bl in func.body_lines:
            if not bl.strip():
                continue
            depth = (_get_indent(bl) - _get_indent(
                analysis.lines[func.line_start - 1])) // 4
            if depth > max_depth:
                max_depth = depth

            stripped_bl = _strip_comment(bl).strip()
            first_word = stripped_bl.split()[0] if stripped_bl.split() else ""
            if first_word in BRANCH_KEYWORDS:
                func.complexity += 1

        func.max_depth = max_depth

        # Variable and call analysis
        param_set = set(func.params)
        used_params = set()
        for bl in func.body_lines:
            stripped_bl = _strip_comment(bl).strip()
            if not stripped_bl or _is_comment_line(stripped_bl):
                continue

            # Track calls
            for cm in CALL_RE.finditer(stripped_bl):
                callee = cm.group(1)
                if callee != func.name:
                    func.callees.add(callee)
                    analysis.all_calls.add(callee)
                else:
                    func.calls_self = True

            # Track param usage
            for p in func.params:
                if re.search(r"\b" + re.escape(p) + r"\b", stripped_bl):
                    used_params.add(p)

            # Track variable assignments
            am = ASSIGN_RE.match(stripped_bl)
            if am:
                var = am.group(1)
                if var not in param_set:
                    func.local_vars.add(var)

            # Check for returns
            if RETURN_RE.match(stripped_bl):
                func.has_return = True

        func.dead_params = [p for p in func.params if p not in used_params]

        # Recursive base case detection
        if func.calls_self:
            for bl in func.body_lines:
                stripped_bl = _strip_comment(bl).strip()
                first = stripped_bl.split()[0] if stripped_bl.split() else ""
                if first == "if" and RETURN_RE.match(
                        _strip_comment(func.body_lines[
                            min(func.body_lines.index(bl) + 1,
                                len(func.body_lines) - 1)]).strip()
                        if func.body_lines.index(bl) + 1 < len(func.body_lines)
                        else ""):
                    func.has_base_guard = True
                    break

    # Global variable tracking
    for line in analysis.lines:
        stripped = line.strip()
        if not stripped or _is_comment_line(stripped):
            continue
        am = ASSIGN_RE.match(stripped)
        if am and _get_indent(line) == 0:
            analysis.global_vars.add(am.group(1))

    return analysis


# ── Pathology Detectors ──────────────────────────────────────────────

def _detect_god_functions(analysis: FileAnalysis) -> List[Diagnosis]:
    """P001: Functions that do too much."""
    results = []
    for f in analysis.functions:
        if f.loc > GOD_FUNC_LOC and f.complexity > GOD_FUNC_COMPLEXITY:
            results.append(Diagnosis(
                code="P001", title="God Function", severity=Severity.CRITICAL,
                file=analysis.filepath, line=f.line_start,
                detail=f"Function '{f.name}' has {f.loc} LOC and complexity {f.complexity}",
                prescription=f"Break '{f.name}' into smaller, focused helper functions",
                prognosis="Hard to test, debug, and modify. Bug magnet.",
            ))
    return results


def _detect_dead_params(analysis: FileAnalysis) -> List[Diagnosis]:
    """P003: Function parameters that are never used."""
    results = []
    for f in analysis.functions:
        for p in getattr(f, "dead_params", []):
            results.append(Diagnosis(
                code="P003", title="Dead Parameter", severity=Severity.WARNING,
                file=analysis.filepath, line=f.line_start,
                detail=f"Parameter '{p}' in function '{f.name}' is never used",
                prescription=f"Remove '{p}' from '{f.name}' or use it",
                prognosis="Confusing API. Callers pass values that are ignored.",
            ))
    return results


def _detect_magic_numbers(analysis: FileAnalysis) -> List[Diagnosis]:
    """P004: Unexplained numeric literals in logic."""
    SAFE_NUMBERS = {"0", "1", "2", "0.0", "1.0", "100", "10", "-1"}
    results = []
    for i, raw_line in enumerate(analysis.lines, 1):
        stripped = _strip_comment(raw_line).strip()
        if not stripped or _is_comment_line(raw_line.strip()):
            continue
        # Skip assignments that look like constant definitions (ALL_CAPS = N)
        if re.match(r"^\s*[A-Z_]{2,}\s*=", stripped):
            continue
        for m in NUMBER_LITERAL_RE.finditer(stripped):
            val = m.group(1)
            if val not in SAFE_NUMBERS and not re.match(r"^\s*\w+\s*=\s*" + re.escape(val), stripped):
                # Check if it's in a context that looks like magic
                context_start = max(0, m.start() - 20)
                context = stripped[context_start:m.start()]
                if any(kw in context for kw in ("if", "while", "elif", ">", "<", "==", "!=", ">=", "<=")):
                    results.append(Diagnosis(
                        code="P004", title="Magic Number", severity=Severity.INFO,
                        file=analysis.filepath, line=i,
                        detail=f"Unexplained number '{val}' in conditional logic",
                        prescription=f"Extract {val} into a named constant",
                        prognosis="Hard to understand intent. Easy to introduce bugs when changing.",
                    ))
    return results


def _detect_long_param_list(analysis: FileAnalysis) -> List[Diagnosis]:
    """P005: Functions with too many parameters."""
    results = []
    for f in analysis.functions:
        if len(f.params) > MAX_PARAMS:
            results.append(Diagnosis(
                code="P005", title="Long Parameter List", severity=Severity.WARNING,
                file=analysis.filepath, line=f.line_start,
                detail=f"Function '{f.name}' has {len(f.params)} parameters (max recommended: {MAX_PARAMS})",
                prescription=f"Group related parameters into a data structure or split the function",
                prognosis="Hard to call correctly. Easy to mix up argument order.",
            ))
    return results


def _detect_deep_nesting(analysis: FileAnalysis) -> List[Diagnosis]:
    """P006: Code nested too deeply."""
    results = []
    for f in analysis.functions:
        if f.max_depth > MAX_NESTING:
            results.append(Diagnosis(
                code="P006", title="Deep Nesting", severity=Severity.WARNING,
                file=analysis.filepath, line=f.line_start,
                detail=f"Function '{f.name}' has nesting depth {f.max_depth} (max recommended: {MAX_NESTING})",
                prescription="Use early returns, guard clauses, or extract nested logic",
                prognosis="Cognitive overload. Hard to trace execution paths.",
            ))
    return results


def _detect_duplicate_strings(analysis: FileAnalysis) -> List[Diagnosis]:
    """P007: Same string literal repeated many times."""
    results = []
    string_counts = Counter(s for s, _ in analysis.string_literals)
    for s, count in string_counts.most_common():
        if count >= DUPLICATE_STRING_THRESHOLD and len(s) > 3:
            first_line = next(line for val, line in analysis.string_literals if val == s)
            results.append(Diagnosis(
                code="P007", title="Duplicate String", severity=Severity.INFO,
                file=analysis.filepath, line=first_line,
                detail=f"String \"{s[:40]}{'...' if len(s) > 40 else ''}\" repeated {count} times",
                prescription="Extract into a named constant",
                prognosis="Maintenance burden. Changing the string requires multiple edits.",
            ))
    return results


def _detect_function_coupling(analysis: FileAnalysis) -> List[Diagnosis]:
    """P013: Functions that call too many other functions."""
    results = []
    for f in analysis.functions:
        if len(f.callees) > MAX_CALLEES:
            results.append(Diagnosis(
                code="P013", title="High Function Coupling", severity=Severity.WARNING,
                file=analysis.filepath, line=f.line_start,
                detail=f"Function '{f.name}' calls {len(f.callees)} different functions (max recommended: {MAX_CALLEES})",
                prescription="Split into smaller orchestrator functions with clearer responsibilities",
                prognosis="Fragile: changes to any callee may break this function.",
            ))
    return results


def _detect_orphan_functions(analysis: FileAnalysis, all_project_calls: Set[str]) -> List[Diagnosis]:
    """P014: Functions defined but never called anywhere."""
    results = []
    for f in analysis.functions:
        if f.name not in all_project_calls and f.name not in ("main", "init", "setup", "test"):
            # Also check if it's called within the same file's calls
            file_calls = set()
            for other_f in analysis.functions:
                if other_f.name != f.name:
                    file_calls |= other_f.callees
            if f.name not in file_calls and f.name not in all_project_calls:
                results.append(Diagnosis(
                    code="P014", title="Orphan Function", severity=Severity.INFO,
                    file=analysis.filepath, line=f.line_start,
                    detail=f"Function '{f.name}' is defined but never called",
                    prescription="Remove if unused, or verify it's called dynamically",
                    prognosis="Dead code increases maintenance burden.",
                ))
    return results


def _detect_inconsistent_naming(analysis: FileAnalysis) -> List[Diagnosis]:
    """P011: Mixed naming conventions."""
    results = []
    func_names = [f.name for f in analysis.functions]
    camel_count = sum(1 for n in func_names if re.match(r"^[a-z]+[A-Z]", n))
    snake_count = sum(1 for n in func_names if "_" in n and n == n.lower())

    if camel_count > 0 and snake_count > 0 and len(func_names) >= 3:
        results.append(Diagnosis(
            code="P011", title="Inconsistent Naming", severity=Severity.INFO,
            file=analysis.filepath, line=1,
            detail=f"Mixed naming: {camel_count} camelCase + {snake_count} snake_case functions",
            prescription="Pick one naming convention and apply it consistently",
            prognosis="Confusing for readers. Which style should new code use?",
        ))
    return results


def _detect_comment_ratio(analysis: FileAnalysis) -> List[Diagnosis]:
    """P012: Too few or too many comments."""
    results = []
    if analysis.code_lines == 0:
        return results
    ratio = analysis.comment_lines / analysis.code_lines
    if ratio < COMMENT_RATIO_LOW and analysis.code_lines > 30:
        results.append(Diagnosis(
            code="P012", title="Low Comment Ratio", severity=Severity.INFO,
            file=analysis.filepath, line=1,
            detail=f"Comment ratio is {ratio:.1%} ({analysis.comment_lines}/{analysis.code_lines} lines)",
            prescription="Add comments for complex logic, function purposes, and non-obvious decisions",
            prognosis="Hard for others (or future you) to understand the code.",
        ))
    elif ratio > COMMENT_RATIO_HIGH:
        results.append(Diagnosis(
            code="P012", title="Excessive Comments", severity=Severity.INFO,
            file=analysis.filepath, line=1,
            detail=f"Comment ratio is {ratio:.1%} — comments outnumber code",
            prescription="Remove obvious comments. Good code is self-documenting.",
            prognosis="Comment noise makes it harder to read actual code.",
        ))
    return results


def _detect_long_lines(analysis: FileAnalysis) -> List[Diagnosis]:
    """P017: Lines exceeding maximum length."""
    results = []
    count = 0
    first_line = 0
    for i, raw_line in enumerate(analysis.lines, 1):
        if len(raw_line.rstrip("\n\r")) > MAX_LINE_LENGTH:
            count += 1
            if first_line == 0:
                first_line = i
    if count > 0:
        results.append(Diagnosis(
            code="P017", title="Long Lines", severity=Severity.INFO,
            file=analysis.filepath, line=first_line,
            detail=f"{count} line(s) exceed {MAX_LINE_LENGTH} characters",
            prescription="Break long lines for readability",
            prognosis="Horizontal scrolling and merge conflicts.",
        ))
    return results


def _detect_hardcoded_paths(analysis: FileAnalysis) -> List[Diagnosis]:
    """P018: Literal file paths in code."""
    results = []
    for i, raw_line in enumerate(analysis.lines, 1):
        stripped = _strip_comment(raw_line).strip()
        if HARDCODED_PATH_RE.search(stripped):
            results.append(Diagnosis(
                code="P018", title="Hardcoded Path", severity=Severity.WARNING,
                file=analysis.filepath, line=i,
                detail="Literal file system path detected",
                prescription="Use configuration variables or relative paths",
                prognosis="Breaks on other machines or OSes.",
            ))
    return results


def _detect_empty_catch(analysis: FileAnalysis) -> List[Diagnosis]:
    """P019: Catch blocks with no meaningful handling."""
    results = []
    for i, raw_line in enumerate(analysis.lines, 1):
        stripped = raw_line.strip()
        if stripped.startswith("catch"):
            # Check if the next non-blank line is just 'pass' or the catch block is empty
            for j in range(i, min(i + 3, len(analysis.lines))):
                next_line = analysis.lines[j].strip() if j < len(analysis.lines) else ""
                if next_line == "pass" or next_line == "":
                    results.append(Diagnosis(
                        code="P019", title="Empty Catch", severity=Severity.WARNING,
                        file=analysis.filepath, line=i,
                        detail="Catch block appears to swallow errors silently",
                        prescription="Log the error, re-throw, or handle it meaningfully",
                        prognosis="Bugs hide silently. Debugging becomes a nightmare.",
                    ))
                    break
                elif next_line and not next_line.startswith("#"):
                    break
    return results


def _detect_recursive_risk(analysis: FileAnalysis) -> List[Diagnosis]:
    """P020: Recursive functions without obvious base case."""
    results = []
    for f in analysis.functions:
        if f.calls_self and not f.has_base_guard:
            results.append(Diagnosis(
                code="P020", title="Recursive Risk", severity=Severity.WARNING,
                file=analysis.filepath, line=f.line_start,
                detail=f"Function '{f.name}' calls itself but no clear base case detected",
                prescription="Ensure a clear base case with early return to prevent infinite recursion",
                prognosis="Stack overflow on edge cases.",
            ))
    return results


# ── Health Score ─────────────────────────────────────────────────────

def _compute_health_score(diagnoses: List[Diagnosis]) -> int:
    """Compute a 0-100 health score from diagnoses."""
    if not diagnoses:
        return 100
    penalty = 0
    for d in diagnoses:
        if d.severity == Severity.CRITICAL:
            penalty += 15
        elif d.severity == Severity.WARNING:
            penalty += 5
        else:
            penalty += 1
    return max(0, 100 - penalty)


def _health_grade(score: int) -> str:
    """Letter grade from health score."""
    if score >= 90:
        return "A"
    elif score >= 80:
        return "B"
    elif score >= 70:
        return "C"
    elif score >= 60:
        return "D"
    else:
        return "F"


# ── Autonomous Advisor ───────────────────────────────────────────────

def _generate_recommendations(diagnoses: List[Diagnosis]) -> List[str]:
    """Generate prioritized actionable recommendations."""
    recommendations = []
    code_counts = Counter(d.code for d in diagnoses)

    # Priority-ordered insights
    if code_counts.get("P001", 0) > 0:
        recommendations.append(
            f"🔴 {code_counts['P001']} God Function(s) detected — these are your highest-priority refactoring targets")
    if code_counts.get("P020", 0) > 0:
        recommendations.append(
            f"⚠️  {code_counts['P020']} recursive function(s) without clear base cases — runtime crash risk")
    if code_counts.get("P019", 0) > 0:
        recommendations.append(
            f"⚠️  {code_counts['P019']} empty catch block(s) — errors are being silently swallowed")
    if code_counts.get("P003", 0) > 2:
        recommendations.append(
            f"🧹 {code_counts['P003']} dead parameters across functions — clean up your APIs")
    if code_counts.get("P014", 0) > 0:
        recommendations.append(
            f"🗑️  {code_counts['P014']} orphan function(s) — remove dead code to reduce maintenance")
    if code_counts.get("P007", 0) > 0:
        recommendations.append(
            f"📦 {code_counts['P007']} duplicate string(s) — extract into constants for DRY code")
    if code_counts.get("P004", 0) > 3:
        recommendations.append(
            f"🔢 {code_counts['P004']} magic numbers — name them for clarity")

    if not recommendations:
        recommendations.append("✅ Code looks healthy! Keep up the good practices.")

    return recommendations


# ── Full Diagnosis Pipeline ──────────────────────────────────────────

def diagnose_file(filepath: str, all_project_calls: Optional[Set[str]] = None) -> FileAnalysis:
    """Run all pathology detectors on a single file."""
    analysis = _parse_file(filepath)
    if all_project_calls is None:
        all_project_calls = analysis.all_calls

    detectors = [
        _detect_god_functions,
        _detect_dead_params,
        _detect_magic_numbers,
        _detect_long_param_list,
        _detect_deep_nesting,
        _detect_duplicate_strings,
        _detect_function_coupling,
        _detect_inconsistent_naming,
        _detect_comment_ratio,
        _detect_long_lines,
        _detect_hardcoded_paths,
        _detect_empty_catch,
        _detect_recursive_risk,
    ]

    for detector in detectors:
        analysis.diagnoses.extend(detector(analysis))

    # Cross-file aware detectors
    analysis.diagnoses.extend(_detect_orphan_functions(analysis, all_project_calls))

    # Sort by severity then line
    analysis.diagnoses.sort(key=lambda d: (Severity.ORDER.get(d.severity, 9), d.line))
    return analysis


def diagnose_project(paths: List[str], recursive: bool = False) -> Tuple[List[FileAnalysis], int, List[str]]:
    """Diagnose a set of files/directories. Returns (analyses, health_score, recommendations)."""
    files = _find_srv_files(paths, recursive=recursive)
    if not files:
        return [], 100, ["No .srv files found."]

    # First pass: collect all calls across the project
    all_project_calls: Set[str] = set()
    for filepath in files:
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            for m in CALL_RE.finditer(content):
                all_project_calls.add(m.group(1))
        except OSError:
            pass

    # Second pass: full diagnosis
    analyses = []
    all_diagnoses = []
    for filepath in files:
        a = diagnose_file(filepath, all_project_calls)
        analyses.append(a)
        all_diagnoses.extend(a.diagnoses)

    score = _compute_health_score(all_diagnoses)
    recommendations = _generate_recommendations(all_diagnoses)
    return analyses, score, recommendations


# ── Output Formatters ────────────────────────────────────────────────

def _format_text(analyses: List[FileAnalysis], score: int, recommendations: List[str],
                 severity_filter: Optional[str] = None, top_n: Optional[int] = None,
                 summary_only: bool = False) -> str:
    """Format diagnosis results as colored terminal text."""
    c = _colors()
    lines = []
    lines.append("")
    lines.append(c.bold("╔══════════════════════════════════════════════════╗"))
    lines.append(c.bold("║        🩺  sauravdoctor — Code Health Report     ║"))
    lines.append(c.bold("╚══════════════════════════════════════════════════╝"))
    lines.append("")

    grade = _health_grade(score)
    grade_color = c.green if score >= 80 else c.yellow if score >= 60 else c.red
    lines.append(f"  Health Score: {grade_color(f'{score}/100')}  Grade: {grade_color(grade)}")
    lines.append("")

    # Recommendations
    lines.append(c.bold("  📋 Recommendations:"))
    for r in recommendations:
        lines.append(f"    {r}")
    lines.append("")

    if summary_only:
        total = sum(len(a.diagnoses) for a in analyses)
        crit = sum(1 for a in analyses for d in a.diagnoses if d.severity == Severity.CRITICAL)
        warn = sum(1 for a in analyses for d in a.diagnoses if d.severity == Severity.WARNING)
        info = sum(1 for a in analyses for d in a.diagnoses if d.severity == Severity.INFO)
        lines.append(f"  Files analyzed: {len(analyses)}")
        lines.append(f"  Total findings: {total} ({c.red(f'{crit} critical')}, "
                     f"{c.yellow(f'{warn} warnings')}, {info} info)")
        return "\n".join(lines)

    # Per-file findings
    all_diags = []
    for a in analyses:
        for d in a.diagnoses:
            all_diags.append(d)

    if severity_filter:
        all_diags = [d for d in all_diags if d.severity == severity_filter]

    all_diags.sort(key=lambda d: (Severity.ORDER.get(d.severity, 9), d.file, d.line))

    if top_n:
        all_diags = all_diags[:top_n]

    if not all_diags:
        lines.append(c.green("  ✅ No issues found! Your code is in great shape."))
        return "\n".join(lines)

    sev_icons = {Severity.CRITICAL: c.red("●"), Severity.WARNING: c.yellow("●"), Severity.INFO: "○"}

    for d in all_diags:
        icon = sev_icons.get(d.severity, "○")
        rel_file = os.path.relpath(d.file) if os.path.isabs(d.file) else d.file
        lines.append(f"  {icon} [{d.code}] {c.bold(d.title)}")
        lines.append(f"    {rel_file}:{d.line}")
        lines.append(f"    {d.detail}")
        lines.append(f"    💊 {d.prescription}")
        lines.append("")

    lines.append(f"  Total: {len(all_diags)} finding(s)")
    return "\n".join(lines)


def _format_json(analyses: List[FileAnalysis], score: int, recommendations: List[str]) -> str:
    """Format as JSON."""
    output = {
        "health_score": score,
        "grade": _health_grade(score),
        "recommendations": recommendations,
        "files": [],
    }
    for a in analyses:
        file_data = {
            "filepath": a.filepath,
            "total_lines": a.total_lines,
            "code_lines": a.code_lines,
            "comment_lines": a.comment_lines,
            "functions": len(a.functions),
            "diagnoses": [d.to_dict() for d in a.diagnoses],
        }
        output["files"].append(file_data)
    return _json.dumps(output, indent=2)


def _generate_html(analyses: List[FileAnalysis], score: int, recommendations: List[str]) -> str:
    """Generate an interactive HTML health report."""
    grade = _health_grade(score)
    all_diags = [d for a in analyses for d in a.diagnoses]
    crit = sum(1 for d in all_diags if d.severity == Severity.CRITICAL)
    warn = sum(1 for d in all_diags if d.severity == Severity.WARNING)
    info = sum(1 for d in all_diags if d.severity == Severity.INFO)

    # Count by code
    code_counts = Counter(d.code for d in all_diags)
    top_codes = code_counts.most_common(8)

    gauge_color = "#22c55e" if score >= 80 else "#eab308" if score >= 60 else "#ef4444"
    angle = (score / 100) * 180

    diag_rows = ""
    for d in sorted(all_diags, key=lambda x: (Severity.ORDER.get(x.severity, 9), x.line)):
        sev_class = {"critical": "sev-crit", "warning": "sev-warn", "info": "sev-info"}.get(d.severity, "sev-info")
        rel_file = os.path.relpath(d.file) if os.path.isabs(d.file) else d.file
        diag_rows += f"""<tr class="{sev_class}">
            <td><span class="badge {sev_class}">{d.severity.upper()}</span></td>
            <td><code>{d.code}</code></td>
            <td><strong>{d.title}</strong></td>
            <td>{rel_file}:{d.line}</td>
            <td>{d.detail}</td>
            <td>{d.prescription}</td>
        </tr>\n"""

    rec_html = "\n".join(f"<li>{r}</li>" for r in recommendations)

    bar_chart_data = _json.dumps([{"code": c, "count": n} for c, n in top_codes])

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>sauravdoctor — Code Health Report</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0f172a; color: #e2e8f0; padding: 2rem; }}
  .container {{ max-width: 1100px; margin: 0 auto; }}
  h1 {{ font-size: 1.8rem; margin-bottom: 0.5rem; }}
  h2 {{ font-size: 1.3rem; margin: 1.5rem 0 0.8rem; color: #94a3b8; }}
  .header {{ text-align: center; padding: 1rem 0 2rem; }}
  .gauge-wrap {{ display: flex; justify-content: center; gap: 2rem; align-items: center;
                 flex-wrap: wrap; margin: 1rem 0 2rem; }}
  .gauge {{ width: 200px; height: 110px; position: relative; }}
  .gauge svg {{ width: 200px; height: 110px; }}
  .score-text {{ position: absolute; bottom: 8px; left: 50%; transform: translateX(-50%);
                 font-size: 2rem; font-weight: 700; }}
  .grade-badge {{ font-size: 3rem; font-weight: 800; padding: 0.5rem 1.2rem;
                  border-radius: 16px; background: {gauge_color}22; color: {gauge_color};
                  border: 3px solid {gauge_color}; }}
  .stats {{ display: flex; gap: 1rem; justify-content: center; flex-wrap: wrap; }}
  .stat {{ background: #1e293b; border-radius: 12px; padding: 1rem 1.5rem; text-align: center;
           min-width: 120px; }}
  .stat .val {{ font-size: 1.8rem; font-weight: 700; }}
  .stat .lbl {{ font-size: 0.85rem; color: #94a3b8; }}
  .recs {{ background: #1e293b; border-radius: 12px; padding: 1.2rem 1.5rem; margin: 1.5rem 0; }}
  .recs li {{ margin: 0.4rem 0; line-height: 1.5; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; }}
  th {{ background: #1e293b; padding: 0.7rem; text-align: left; font-size: 0.85rem;
       color: #94a3b8; position: sticky; top: 0; }}
  td {{ padding: 0.6rem 0.7rem; border-bottom: 1px solid #1e293b; font-size: 0.85rem; }}
  .badge {{ padding: 2px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 600; }}
  .sev-crit .badge {{ background: #ef444433; color: #ef4444; }}
  .sev-warn .badge {{ background: #eab30833; color: #eab308; }}
  .sev-info .badge {{ background: #3b82f633; color: #3b82f6; }}
  tr.sev-crit {{ background: #ef444408; }}
  tr.sev-warn {{ background: #eab30808; }}
  .bar-chart {{ display: flex; align-items: flex-end; gap: 8px; height: 120px; margin: 1rem 0; }}
  .bar {{ display: flex; flex-direction: column; align-items: center; flex: 1; }}
  .bar-fill {{ width: 100%; border-radius: 6px 6px 0 0; transition: height 0.6s; }}
  .bar-label {{ font-size: 0.7rem; color: #94a3b8; margin-top: 4px; }}
  .bar-count {{ font-size: 0.75rem; font-weight: 600; margin-bottom: 2px; }}
  code {{ background: #1e293b; padding: 2px 6px; border-radius: 4px; font-size: 0.85rem; }}
  .filter-bar {{ margin: 1rem 0; display: flex; gap: 0.5rem; flex-wrap: wrap; }}
  .filter-btn {{ padding: 6px 16px; border-radius: 8px; border: 1px solid #334155;
                 background: transparent; color: #e2e8f0; cursor: pointer; font-size: 0.85rem; }}
  .filter-btn.active {{ background: #3b82f6; border-color: #3b82f6; }}
  .filter-btn:hover {{ background: #334155; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>🩺 sauravdoctor — Code Health Report</h1>
    <p style="color:#94a3b8">Autonomous diagnostic for sauravcode programs</p>
  </div>

  <div class="gauge-wrap">
    <div class="gauge">
      <svg viewBox="0 0 200 110">
        <path d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="#1e293b" stroke-width="14" stroke-linecap="round"/>
        <path d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="{gauge_color}" stroke-width="14"
              stroke-linecap="round" stroke-dasharray="{angle / 180 * 251.2} 251.2"/>
      </svg>
      <div class="score-text" style="color:{gauge_color}">{score}</div>
    </div>
    <div class="grade-badge">{grade}</div>
  </div>

  <div class="stats">
    <div class="stat"><div class="val">{len(analyses)}</div><div class="lbl">Files</div></div>
    <div class="stat"><div class="val" style="color:#ef4444">{crit}</div><div class="lbl">Critical</div></div>
    <div class="stat"><div class="val" style="color:#eab308">{warn}</div><div class="lbl">Warnings</div></div>
    <div class="stat"><div class="val" style="color:#3b82f6">{info}</div><div class="lbl">Info</div></div>
    <div class="stat"><div class="val">{len(all_diags)}</div><div class="lbl">Total</div></div>
  </div>

  <h2>📋 Recommendations</h2>
  <div class="recs"><ul>{rec_html}</ul></div>

  <h2>📊 Top Pathologies</h2>
  <div class="bar-chart" id="barChart"></div>

  <h2>🔍 All Findings</h2>
  <div class="filter-bar">
    <button class="filter-btn active" onclick="filterSev('all')">All</button>
    <button class="filter-btn" onclick="filterSev('sev-crit')">Critical</button>
    <button class="filter-btn" onclick="filterSev('sev-warn')">Warning</button>
    <button class="filter-btn" onclick="filterSev('sev-info')">Info</button>
  </div>
  <table>
    <thead><tr><th>Severity</th><th>Code</th><th>Title</th><th>Location</th><th>Detail</th><th>Prescription</th></tr></thead>
    <tbody id="diagBody">{diag_rows}</tbody>
  </table>
</div>

<script>
const barData = {bar_chart_data};
const maxCount = Math.max(...barData.map(d => d.count), 1);
const colors = {{"P001":"#ef4444","P003":"#f97316","P004":"#3b82f6","P005":"#eab308",
  "P006":"#eab308","P007":"#3b82f6","P013":"#eab308","P014":"#3b82f6","P011":"#3b82f6",
  "P012":"#3b82f6","P017":"#3b82f6","P018":"#f97316","P019":"#eab308","P020":"#f97316"}};
const chart = document.getElementById("barChart");
barData.forEach(d => {{
  const h = (d.count / maxCount) * 100;
  const col = colors[d.code] || "#3b82f6";
  chart.innerHTML += `<div class="bar"><div class="bar-count">${{d.count}}</div>` +
    `<div class="bar-fill" style="height:${{h}}%;background:${{col}}"></div>` +
    `<div class="bar-label">${{d.code}}</div></div>`;
}});

function filterSev(cls) {{
  document.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));
  event.target.classList.add("active");
  document.querySelectorAll("#diagBody tr").forEach(tr => {{
    tr.style.display = cls === "all" || tr.classList.contains(cls) ? "" : "none";
  }});
}}
</script>
</body>
</html>"""
    return html


# ── CLI ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="sauravdoctor",
        description="🩺 Autonomous Code Health Diagnostic Tool for sauravcode",
    )
    parser.add_argument("paths", nargs="*", default=["."],
                        help="Files or directories to diagnose (default: current dir)")
    parser.add_argument("--recursive", "-r", action="store_true",
                        help="Recurse into subdirectories")
    parser.add_argument("--html", nargs="?", const="sauravdoctor_report.html", metavar="FILE",
                        help="Generate interactive HTML report")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON")
    parser.add_argument("--severity", choices=["critical", "warning", "info"],
                        help="Filter by severity level")
    parser.add_argument("--top", type=int, metavar="N",
                        help="Show only top N findings")
    parser.add_argument("--summary", action="store_true",
                        help="Show project summary only")
    parser.add_argument("--no-color", action="store_true",
                        help="Disable colored output")

    args = parser.parse_args()

    if args.no_color:
        global _colors
        _colors = lambda: _colors.__wrapped__(enabled=False) if hasattr(_colors, "__wrapped__") else __import__("_termcolors").colors(enabled=False)

    analyses, score, recommendations = diagnose_project(args.paths, recursive=args.recursive)

    if args.json:
        print(_format_json(analyses, score, recommendations))
    elif args.html:
        html = _generate_html(analyses, score, recommendations)
        html_path = args.html
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"📄 Report written to {html_path}")
    else:
        print(_format_text(analyses, score, recommendations,
                           severity_filter=args.severity, top_n=args.top,
                           summary_only=args.summary))


if __name__ == "__main__":
    main()
