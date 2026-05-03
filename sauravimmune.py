#!/usr/bin/env python3
"""sauravimmune — Autonomous Code Immune System for sauravcode.

Models a .srv codebase as a living organism with an immune system that
detects, remembers, and responds to code "pathogens" (anti-patterns,
quality issues, vulnerabilities).  Unlike one-shot linters, sauravimmune
maintains persistent *immune memory* that tracks pathogen history across
scans, enabling trend analysis and proactive vaccination.

Analysis Engines (7):
    I001  Pathogen Scanner      Detect 10+ categories of code anti-patterns
    I002  Antibody Generator    Produce targeted remediation rules per pathogen
    I003  Immune Memory         Persistent cross-scan pathogen tracking & resolution
    I004  Vaccination Engine    Proactive checks that prevent new pathogen introduction
    I005  Autoimmune Detector   Find harmful over-defensive patterns (false positives)
    I006  Immune Response Scorer Composite health score 0-100 with 5 tiers
    I007  Insight Generator     Autonomous trend analysis & recommendations

Pathogen Categories (10):
    god_function         Function > 50 LOC with high complexity
    dead_parameter       Declared parameter never used in body
    magic_number         Literal numeric constants (not 0/1) without context
    deep_nesting         Nesting depth exceeds 5 levels
    duplicated_logic     Repeated code blocks across functions
    missing_error_handling Risky operations without try/catch
    orphan_function      Defined but never called from anywhere
    overloaded_params    Function with > 5 parameters
    naming_violation     Single-character non-loop variable names
    unguarded_recursion  Recursive call without visible base case guard

Immune Score Tiers:
    Fortified   85-100   Strong defenses
    Healthy     70-84    Good condition
    Vulnerable  55-69    Needs attention
    Compromised 40-54    Significant issues
    Critical    0-39     Immediate action required

Usage:
    python sauravimmune.py program.srv              # Full immune scan
    python sauravimmune.py .                        # Scan all .srv in cwd
    python sauravimmune.py . --recursive            # Include subdirectories
    python sauravimmune.py . --html report.html     # Interactive HTML dashboard
    python sauravimmune.py . --json                 # JSON output
    python sauravimmune.py . --pathogens            # Show only pathogens
    python sauravimmune.py . --antibodies           # Show antibodies
    python sauravimmune.py . --memory               # Show immune memory
    python sauravimmune.py . --vaccinate            # Run vaccination checks
    python sauravimmune.py . --autoimmune           # Show autoimmune issues
    python sauravimmune.py . --critical             # Only critical/high severity
    python sauravimmune.py . --top N                # Top N worst pathogens
    python sauravimmune.py . --reset-memory         # Clear immune memory
    python sauravimmune.py . --no-color             # Disable colors
"""

import sys
import os
import re
import json
import math
import argparse
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

from _srv_utils import get_indent as _get_indent, find_srv_files as _find_srv_files

# ── ANSI Colors ──────────────────────────────────────────────────────

USE_COLOR = True


def _c(code, t):
    return f"\033[{code}m{t}\033[0m" if USE_COLOR else str(t)


def red(t):     return _c("31", t)
def green(t):   return _c("32", t)
def yellow(t):  return _c("33", t)
def cyan(t):    return _c("36", t)
def bold(t):    return _c("1", t)
def dim(t):     return _c("2", t)
def magenta(t): return _c("35", t)


FUNCTION_DEF = re.compile(r'^(\s*)(function|fn)\s+(\w+)')
CALL_PATTERN = re.compile(r'\b([a-zA-Z_]\w*)\s*\(')
MAGIC_NUMBER = re.compile(r'(?<!\w)(\d+\.?\d*)(?!\w)')
BRANCH_KEYWORDS = {'if', 'elif', 'while', 'for', 'foreach', 'catch', 'and', 'or'}
RISKY_OPS = {'open', 'read', 'write', 'delete', 'remove', 'http', 'fetch',
             'connect', 'exec', 'eval', 'send', 'recv'}
RISKY_OPS_RE = re.compile(r'\b(?:' + '|'.join(RISKY_OPS) + r')\b', re.IGNORECASE)
ASSIGN_RE = re.compile(r'^([a-zA-Z_]\w*)\s*=')
LOOP_VARS = {'i', 'j', 'k', 'x', 'y', 'n', '_'}
BUILTINS = {'print', 'len', 'str', 'int', 'float', 'input', 'range', 'type',
            'list', 'dict', 'set', 'abs', 'min', 'max', 'sum', 'append',
            'push', 'pop', 'keys', 'values', 'items', 'sort', 'reverse',
            'map', 'filter', 'reduce', 'split', 'join', 'strip', 'replace',
            'format', 'upper', 'lower', 'contains', 'startswith', 'endswith',
            'true', 'false', 'null', 'none', 'self', 'this',
            'if', 'while', 'for', 'elif', 'foreach'}

MEMORY_FILE = ".sauravimmune_memory.json"

# ── Data Classes ─────────────────────────────────────────────────────


@dataclass
class FuncInfo:
    """Parsed function information."""
    name: str
    file: str
    line: int
    loc: int = 0
    params: List[str] = field(default_factory=list)
    body_lines: List[str] = field(default_factory=list)
    max_depth: int = 0
    complexity: int = 1
    calls: List[str] = field(default_factory=list)
    has_try_catch: bool = False
    has_return_guard: bool = False

    @property
    def fqn(self):
        return f"{self.file}::{self.name}"


@dataclass
class Pathogen:
    """A detected code anti-pattern."""
    id: str
    category: str
    severity: str  # critical/high/medium/low
    location: str
    description: str
    evidence: str


@dataclass
class Antibody:
    """A remediation rule for a pathogen."""
    pathogen_id: str
    remedy: str
    effort: str  # low/medium/high
    auto_fixable: bool


@dataclass
class ImmuneMemoryEntry:
    """Persistent memory of a pathogen occurrence."""
    first_seen: str
    last_seen: str
    occurrences: int
    resolved: bool
    pathogen_category: str
    file: str


@dataclass
class AutoimmuneIssue:
    """A harmful over-defensive pattern."""
    category: str
    location: str
    description: str
    severity: str


@dataclass
class ImmuneReport:
    """Full immune system analysis report."""
    timestamp: str = ""
    files_scanned: int = 0
    total_functions: int = 0
    pathogens: List[Pathogen] = field(default_factory=list)
    antibodies: List[Antibody] = field(default_factory=list)
    memory_entries: List[ImmuneMemoryEntry] = field(default_factory=list)
    vaccinations: List[Dict] = field(default_factory=list)
    autoimmune_issues: List[AutoimmuneIssue] = field(default_factory=list)
    immune_score: float = 0.0
    insights: List[str] = field(default_factory=list)
    pathogen_summary: Dict[str, int] = field(default_factory=dict)
    memory_stats: Dict[str, Any] = field(default_factory=dict)


# ── File Parsing ─────────────────────────────────────────────────────

def _parse_functions(filepath: str) -> List[FuncInfo]:
    """Parse a .srv file and extract function-level information."""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
    except OSError:
        return []

    funcs = []
    current = None
    base_indent = 0

    for i, raw in enumerate(lines):
        line = raw.rstrip()
        stripped = line.lstrip()
        if not stripped or stripped.startswith('#'):
            continue

        indent = _get_indent(raw)
        m = FUNCTION_DEF.match(line)
        if m:
            current = FuncInfo(
                name=m.group(3), file=os.path.basename(filepath), line=i + 1
            )
            base_indent = indent
            after = line[m.end():].strip()
            if after:
                current.params = after.split()
            funcs.append(current)
            continue

        if current is not None:
            if indent > base_indent:
                current.loc += 1
                current.body_lines.append(stripped)
                fn_depth = (indent - base_indent) // 4
                if fn_depth < 1:
                    fn_depth = (indent - base_indent) // 2
                if fn_depth < 1:
                    fn_depth = 1
                if fn_depth > current.max_depth:
                    current.max_depth = fn_depth

                first_word = stripped.split()[0] if stripped else ""
                if first_word in BRANCH_KEYWORDS:
                    current.complexity += 1

                if first_word in ('try', 'catch'):
                    current.has_try_catch = True

                if stripped.startswith('if') and ('return' in stripped or
                        (i + 1 < len(lines) and 'return' in lines[i + 1])):
                    current.has_return_guard = True

                for cm in CALL_PATTERN.finditer(stripped):
                    callee = cm.group(1)
                    if callee not in BUILTINS and callee not in current.calls:
                        current.calls.append(callee)
            else:
                current = None

    return funcs


# ── I001: Pathogen Scanner ───────────────────────────────────────────

_pathogen_counter = 0


def _next_pathogen_id():
    global _pathogen_counter
    _pathogen_counter += 1
    return f"PATH-{_pathogen_counter:03d}"


def _reset_pathogen_counter():
    global _pathogen_counter
    _pathogen_counter = 0


def _scan_pathogens(funcs: List[FuncInfo], all_call_targets: Set[str]) -> List[Pathogen]:
    """Detect code anti-patterns across all parsed functions."""
    pathogens = []

    for fn in funcs:
        # god_function: >50 LOC + complexity > 8
        if fn.loc > 50 and fn.complexity > 8:
            pathogens.append(Pathogen(
                id=_next_pathogen_id(), category="god_function",
                severity="critical", location=fn.fqn,
                description=f"God function: {fn.loc} LOC, complexity {fn.complexity}",
                evidence=f"LOC={fn.loc}, CC={fn.complexity}"
            ))

        # dead_parameter: param never referenced in body
        body_text = " ".join(fn.body_lines)
        for param in fn.params:
            if param not in body_text:
                pathogens.append(Pathogen(
                    id=_next_pathogen_id(), category="dead_parameter",
                    severity="medium", location=fn.fqn,
                    description=f"Parameter '{param}' is never used in function body",
                    evidence=f"param={param}"
                ))

        # magic_number: literals other than 0, 1, 2, 10, 100
        safe_numbers = {'0', '1', '2', '10', '100', '0.0', '1.0'}
        magic_found = False
        for line in fn.body_lines:
            if magic_found:
                break
            for m in MAGIC_NUMBER.finditer(line):
                num_str = m.group(1)
                if num_str not in safe_numbers and not line.lstrip().startswith('#'):
                    pathogens.append(Pathogen(
                        id=_next_pathogen_id(), category="magic_number",
                        severity="low", location=f"{fn.fqn}",
                        description=f"Magic number {num_str} in function body",
                        evidence=line.strip()
                    ))
                    magic_found = True
                    break  # one per function is enough

        # deep_nesting: max_depth > 5
        if fn.max_depth > 5:
            pathogens.append(Pathogen(
                id=_next_pathogen_id(), category="deep_nesting",
                severity="high", location=fn.fqn,
                description=f"Nesting depth {fn.max_depth} exceeds limit of 5",
                evidence=f"max_depth={fn.max_depth}"
            ))

        # missing_error_handling: risky ops without try/catch
        if not fn.has_try_catch:
            for line in fn.body_lines:
                if RISKY_OPS_RE.search(line):
                    pathogens.append(Pathogen(
                        id=_next_pathogen_id(), category="missing_error_handling",
                        severity="high", location=fn.fqn,
                        description=f"Risky operation without try/catch",
                        evidence=line.strip()
                    ))
                    break

        # overloaded_params: > 5 parameters
        if len(fn.params) > 5:
            pathogens.append(Pathogen(
                id=_next_pathogen_id(), category="overloaded_params",
                severity="medium", location=fn.fqn,
                description=f"Function has {len(fn.params)} parameters (max recommended: 5)",
                evidence=f"params={', '.join(fn.params)}"
            ))

        # naming_violation: single-char non-loop variable assignments
        for line in fn.body_lines:
            assign_m = ASSIGN_RE.match(line)
            if assign_m:
                var_name = assign_m.group(1)
                if len(var_name) == 1 and var_name not in LOOP_VARS:
                    pathogens.append(Pathogen(
                        id=_next_pathogen_id(), category="naming_violation",
                        severity="low", location=fn.fqn,
                        description=f"Single-character variable '{var_name}' outside loop context",
                        evidence=line.strip()
                    ))
                    break

        # unguarded_recursion: calls itself without visible base case
        if fn.name in fn.calls and not fn.has_return_guard:
            pathogens.append(Pathogen(
                id=_next_pathogen_id(), category="unguarded_recursion",
                severity="critical", location=fn.fqn,
                description=f"Recursive call to '{fn.name}' without visible base case guard",
                evidence=f"self-call without early return"
            ))

    # orphan_function: defined but never called (need cross-function check)
    defined_names = {fn.name for fn in funcs}
    for fn in funcs:
        if fn.name not in all_call_targets and fn.name not in ('main', 'init', 'setup', 'run', 'start', 'test'):
            pathogens.append(Pathogen(
                id=_next_pathogen_id(), category="orphan_function",
                severity="low", location=fn.fqn,
                description=f"Function '{fn.name}' is defined but never called",
                evidence=f"no references found"
            ))

    # duplicated_logic: detect similar body patterns across functions
    body_hashes = defaultdict(list)
    for fn in funcs:
        if fn.loc >= 3:
            # Hash normalized body (strip whitespace, lowercase)
            normalized = " ".join(l.strip().lower() for l in fn.body_lines[:20])
            sig = hash(normalized)
            body_hashes[sig].append(fn)

    for sig, fns_group in body_hashes.items():
        if len(fns_group) >= 2:
            names = [f.fqn for f in fns_group]
            for fqn in names:
                pathogens.append(Pathogen(
                    id=_next_pathogen_id(), category="duplicated_logic",
                    severity="medium", location=fqn,
                    description=f"Duplicated logic pattern shared with {len(names)-1} other function(s)",
                    evidence=f"cluster: {', '.join(names)}"
                ))

    return pathogens


# ── I002: Antibody Generator ─────────────────────────────────────────

_ANTIBODY_RULES = {
    "god_function":           ("Break into smaller, focused functions with single responsibilities", "high", False),
    "dead_parameter":         ("Remove unused parameter or use it in the function body", "low", True),
    "magic_number":           ("Extract magic number into a named constant", "low", True),
    "deep_nesting":           ("Flatten with early returns, guard clauses, or extract nested logic", "medium", False),
    "duplicated_logic":       ("Extract shared logic into a common helper function", "medium", False),
    "missing_error_handling": ("Wrap risky operations in try/catch blocks", "medium", False),
    "orphan_function":        ("Remove dead function or add a call site", "low", True),
    "overloaded_params":      ("Group related parameters into a data structure or split function", "medium", False),
    "naming_violation":       ("Use descriptive variable names (>= 2 characters)", "low", True),
    "unguarded_recursion":    ("Add explicit base case check with early return before recursive call", "medium", False),
}


def _generate_antibodies(pathogens: List[Pathogen]) -> List[Antibody]:
    """Generate remediation antibodies for each detected pathogen."""
    antibodies = []
    for p in pathogens:
        rule = _ANTIBODY_RULES.get(p.category, ("Review and fix this issue", "medium", False))
        antibodies.append(Antibody(
            pathogen_id=p.id,
            remedy=rule[0],
            effort=rule[1],
            auto_fixable=rule[2]
        ))
    return antibodies


# ── I003: Immune Memory ──────────────────────────────────────────────

def _load_memory(scan_dir: str) -> Dict:
    """Load immune memory from persistent storage."""
    path = os.path.join(scan_dir, MEMORY_FILE)
    if os.path.isfile(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"version": 1, "scans": [], "pathogens": {}}


def _save_memory(scan_dir: str, memory: Dict) -> None:
    """Save immune memory to persistent storage."""
    path = os.path.join(scan_dir, MEMORY_FILE)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(memory, f, indent=2)
    except OSError:
        pass


def _update_memory(memory: Dict, pathogens: List[Pathogen],
                   score: float, files_scanned: int) -> List[ImmuneMemoryEntry]:
    """Update immune memory with current scan results."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Record this scan
    memory["scans"].append({
        "timestamp": now,
        "score": round(score, 1),
        "pathogens": len(pathogens),
        "files": files_scanned
    })
    # Keep last 100 scans
    if len(memory["scans"]) > 100:
        memory["scans"] = memory["scans"][-100:]

    # Current pathogen keys
    current_keys = set()
    for p in pathogens:
        key = f"{p.location}::{p.category}"
        current_keys.add(key)
        if key in memory["pathogens"]:
            entry = memory["pathogens"][key]
            entry["last_seen"] = now
            entry["occurrences"] += 1
            entry["resolved"] = False
        else:
            memory["pathogens"][key] = {
                "first_seen": now,
                "last_seen": now,
                "occurrences": 1,
                "resolved": False,
                "pathogen_category": p.category,
                "file": p.location.split("::")[0] if "::" in p.location else ""
            }

    # Mark resolved pathogens
    for key, entry in memory["pathogens"].items():
        if key not in current_keys and not entry["resolved"]:
            entry["resolved"] = True

    # Build memory entry list
    entries = []
    for key, entry in memory["pathogens"].items():
        entries.append(ImmuneMemoryEntry(
            first_seen=entry["first_seen"],
            last_seen=entry["last_seen"],
            occurrences=entry["occurrences"],
            resolved=entry["resolved"],
            pathogen_category=entry["pathogen_category"],
            file=entry.get("file", "")
        ))

    return entries


# ── I004: Vaccination Engine ──────────────────────────────────────────

def _run_vaccinations(funcs: List[FuncInfo], memory: Dict) -> List[Dict]:
    """Proactive checks based on immune memory — prevent recurring pathogens."""
    vaccinations = []

    # Extract recurring pathogen categories from memory
    recurring_categories = Counter()
    for key, entry in memory.get("pathogens", {}).items():
        if entry["occurrences"] >= 2 and not entry["resolved"]:
            recurring_categories[entry["pathogen_category"]] += 1

    # Check new/recent functions against recurring patterns
    for fn in funcs:
        # If god_functions are recurring, warn about growing functions
        if recurring_categories.get("god_function", 0) > 0 and fn.loc > 30:
            vaccinations.append({
                "type": "preventive",
                "target": fn.fqn,
                "warning": f"Function approaching god_function threshold ({fn.loc} LOC)",
                "recommendation": "Consider splitting before it grows further"
            })

        # If deep_nesting is recurring, warn about moderate nesting
        if recurring_categories.get("deep_nesting", 0) > 0 and fn.max_depth > 3:
            vaccinations.append({
                "type": "preventive",
                "target": fn.fqn,
                "warning": f"Nesting depth {fn.max_depth} trending toward deep_nesting",
                "recommendation": "Flatten with guard clauses proactively"
            })

        # If overloaded_params is recurring, warn about 4+ params
        if recurring_categories.get("overloaded_params", 0) > 0 and len(fn.params) >= 4:
            vaccinations.append({
                "type": "preventive",
                "target": fn.fqn,
                "warning": f"Function has {len(fn.params)} params, approaching overload",
                "recommendation": "Group related parameters"
            })

    # General vaccination based on memory patterns
    if len(memory.get("scans", [])) >= 3:
        recent_scores = [s["score"] for s in memory["scans"][-3:]]
        if all(s < 60 for s in recent_scores):
            vaccinations.append({
                "type": "systemic",
                "target": "codebase",
                "warning": "Immune score consistently below 60 for 3+ scans",
                "recommendation": "Schedule a dedicated code health sprint"
            })

    return vaccinations


# ── I005: Autoimmune Detector ─────────────────────────────────────────

def _detect_autoimmune(funcs: List[FuncInfo]) -> List[AutoimmuneIssue]:
    """Detect harmful over-defensive patterns."""
    issues = []

    for fn in funcs:
        # Over-validation: checking same condition multiple times
        conditions = []
        for line in fn.body_lines:
            if line.lstrip().startswith('if '):
                cond = line.strip()
                conditions.append(cond)
        cond_counter = Counter(conditions)
        for cond, count in cond_counter.items():
            if count >= 2:
                issues.append(AutoimmuneIssue(
                    category="over_validation",
                    location=fn.fqn,
                    description=f"Same condition checked {count} times: {cond[:60]}",
                    severity="medium"
                ))

        # Excessive error handling: more catch blocks than logic
        catch_count = sum(1 for l in fn.body_lines if l.strip().startswith('catch'))
        logic_lines = fn.loc - catch_count
        if catch_count >= 3 and catch_count > logic_lines * 0.3:
            issues.append(AutoimmuneIssue(
                category="excessive_error_handling",
                location=fn.fqn,
                description=f"{catch_count} catch blocks in {fn.loc} LOC — error handling dominates logic",
                severity="medium"
            ))

        # Redundant guards: return immediately after checking for obvious truths
        for i, line in enumerate(fn.body_lines):
            if ('if true' in line.lower() or 'if 1' in line.lower() or
                    'if not false' in line.lower()):
                issues.append(AutoimmuneIssue(
                    category="redundant_guard",
                    location=fn.fqn,
                    description=f"Tautological guard: {line.strip()[:60]}",
                    severity="low"
                ))

        # Over-abstraction: very tiny wrapper (1-2 LOC) that just calls another function
        if fn.loc <= 2 and len(fn.calls) == 1 and len(fn.body_lines) <= 2:
            call_line = fn.body_lines[0] if fn.body_lines else ""
            if 'return' in call_line or fn.calls[0] in call_line:
                issues.append(AutoimmuneIssue(
                    category="over_abstraction",
                    location=fn.fqn,
                    description=f"Trivial wrapper around '{fn.calls[0]}' adds indirection without value",
                    severity="low"
                ))

    return issues


# ── I006: Immune Response Scorer ──────────────────────────────────────

def _compute_immune_score(funcs: List[FuncInfo], pathogens: List[Pathogen],
                          memory: Dict, vaccinations: List[Dict],
                          autoimmune_issues: List[AutoimmuneIssue]) -> float:
    """Compute composite immune health score 0-100."""
    if not funcs:
        return 100.0

    # Pathogen density (40% weight)
    severity_weights = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    total_severity = sum(severity_weights.get(p.severity, 1) for p in pathogens)
    max_severity = len(funcs) * 4  # worst case: every function has a critical pathogen
    pathogen_score = max(0, 100 - (total_severity / max(max_severity, 1)) * 100)

    # Memory maturity (15% weight) — reward resolved pathogens
    mem_pathogens = memory.get("pathogens", {})
    if mem_pathogens:
        resolved = sum(1 for e in mem_pathogens.values() if e["resolved"])
        memory_score = (resolved / len(mem_pathogens)) * 100
    else:
        memory_score = 50  # neutral when no history

    # Vaccination readiness (15% weight) — fewer preventive warnings = better
    if vaccinations:
        vax_warnings = len([v for v in vaccinations if v["type"] == "preventive"])
        vax_score = max(0, 100 - vax_warnings * 15)
    else:
        vax_score = 90  # no warnings needed

    # Autoimmune risk (15% weight)
    if autoimmune_issues:
        auto_penalty = sum(2 if a.severity == "medium" else 1 for a in autoimmune_issues)
        auto_score = max(0, 100 - auto_penalty * 10)
    else:
        auto_score = 100

    # Defense coverage (15% weight) — proportion of functions with error handling
    defended = sum(1 for fn in funcs if fn.has_try_catch or fn.has_return_guard)
    defense_score = (defended / len(funcs)) * 100 if funcs else 50

    composite = (pathogen_score * 0.40 +
                 memory_score * 0.15 +
                 vax_score * 0.15 +
                 auto_score * 0.15 +
                 defense_score * 0.15)

    return round(min(100, max(0, composite)), 1)


def _score_tier(score: float) -> str:
    if score >= 85:
        return "Fortified"
    elif score >= 70:
        return "Healthy"
    elif score >= 55:
        return "Vulnerable"
    elif score >= 40:
        return "Compromised"
    return "Critical"


# ── I007: Insight Generator ──────────────────────────────────────────

def _generate_insights(report: ImmuneReport, memory: Dict) -> List[str]:
    """Generate autonomous insights about immune system health."""
    insights = []

    # Pathogen distribution
    if report.pathogen_summary:
        top = max(report.pathogen_summary, key=report.pathogen_summary.get)
        insights.append(f"Most common pathogen: {top} ({report.pathogen_summary[top]} occurrences)")

    # Critical pathogens
    crits = [p for p in report.pathogens if p.severity == "critical"]
    if crits:
        insights.append(f"URGENT: {len(crits)} critical pathogen(s) require immediate attention")

    # Auto-fixable ratio
    auto_fix = [a for a in report.antibodies if a.auto_fixable]
    if auto_fix:
        pct = len(auto_fix) / max(len(report.antibodies), 1) * 100
        insights.append(f"{len(auto_fix)} pathogens ({pct:.0f}%) are auto-fixable — quick wins available")

    # Memory trends
    scans = memory.get("scans", [])
    if len(scans) >= 2:
        prev = scans[-2]["score"]
        curr = scans[-1]["score"]
        delta = curr - prev
        if delta > 5:
            insights.append(f"Immune score improved by {delta:.1f} points since last scan")
        elif delta < -5:
            insights.append(f"WARNING: Immune score dropped {abs(delta):.1f} points since last scan")

    # Recurring pathogens
    recurring = [k for k, v in memory.get("pathogens", {}).items()
                 if v["occurrences"] >= 3 and not v["resolved"]]
    if recurring:
        insights.append(f"{len(recurring)} chronic pathogen(s) have persisted for 3+ scans — consider prioritizing")

    # Resolved pathogens
    resolved = [k for k, v in memory.get("pathogens", {}).items() if v["resolved"]]
    if resolved:
        insights.append(f"{len(resolved)} pathogen(s) successfully resolved — immune system learning")

    # Vaccination warnings
    systemic = [v for v in report.vaccinations if v["type"] == "systemic"]
    if systemic:
        insights.append("Systemic warning: codebase health trending down across multiple scans")

    # Autoimmune correlation
    if report.autoimmune_issues and len(report.pathogens) < 3:
        insights.append("Low pathogen count but autoimmune issues detected — defenses may be overly aggressive")

    # Score tier insight
    tier = _score_tier(report.immune_score)
    insights.append(f"Immune Status: {tier} ({report.immune_score:.1f}/100)")

    return insights


# ── HTML Dashboard ────────────────────────────────────────────────────

def _generate_html(report: ImmuneReport) -> str:
    """Generate an interactive HTML dashboard."""
    pathogens_json = json.dumps([{
        "id": p.id, "category": p.category, "severity": p.severity,
        "location": p.location, "description": p.description, "evidence": p.evidence
    } for p in report.pathogens])

    antibodies_json = json.dumps([{
        "pathogen_id": a.pathogen_id, "remedy": a.remedy,
        "effort": a.effort, "auto_fixable": a.auto_fixable
    } for a in report.antibodies])

    memory_json = json.dumps([{
        "first_seen": m.first_seen, "last_seen": m.last_seen,
        "occurrences": m.occurrences, "resolved": m.resolved,
        "category": m.pathogen_category, "file": m.file
    } for m in report.memory_entries])

    autoimmune_json = json.dumps([{
        "category": a.category, "location": a.location,
        "description": a.description, "severity": a.severity
    } for a in report.autoimmune_issues])

    insights_json = json.dumps(report.insights)
    summary_json = json.dumps(report.pathogen_summary)
    score = report.immune_score
    tier = _score_tier(score)

    tier_colors = {"Fortified": "#22c55e", "Healthy": "#3b82f6",
                   "Vulnerable": "#eab308", "Compromised": "#f97316", "Critical": "#ef4444"}
    tier_color = tier_colors.get(tier, "#6b7280")

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>sauravimmune — Code Immune System</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:system-ui,-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;padding:20px}}
h1{{text-align:center;margin:10px 0;font-size:1.8em}}
.tabs{{display:flex;gap:8px;justify-content:center;margin:16px 0}}
.tab{{padding:8px 20px;border-radius:8px;cursor:pointer;background:#1e293b;border:1px solid #334155;font-size:14px;color:#94a3b8}}
.tab.active{{background:#3b82f6;color:#fff;border-color:#3b82f6}}
.panel{{display:none;background:#1e293b;border-radius:12px;padding:20px;margin-top:10px}}
.panel.active{{display:block}}
.gauge{{text-align:center;margin:20px 0}}
.score{{font-size:3em;font-weight:bold;color:{tier_color}}}
.tier{{font-size:1.3em;color:{tier_color};margin:5px 0}}
table{{width:100%;border-collapse:collapse;margin:10px 0}}
th,td{{padding:8px 12px;text-align:left;border-bottom:1px solid #334155;font-size:13px}}
th{{background:#0f172a;color:#94a3b8;font-weight:600}}
.badge{{padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600}}
.badge-critical{{background:#fee2e2;color:#991b1b}}
.badge-high{{background:#ffedd5;color:#9a3412}}
.badge-medium{{background:#fef9c3;color:#854d0e}}
.badge-low{{background:#dcfce7;color:#166534}}
.badge-resolved{{background:#d1fae5;color:#065f46}}
.badge-active{{background:#fecaca;color:#991b1b}}
.insight{{padding:8px 12px;margin:6px 0;border-left:3px solid #3b82f6;background:#0f172a;border-radius:0 6px 6px 0;font-size:13px}}
.chart-bar{{display:flex;align-items:center;margin:4px 0}}
.chart-bar .label{{width:160px;font-size:12px;color:#94a3b8}}
.chart-bar .bar{{height:20px;border-radius:4px;min-width:2px}}
.chart-bar .count{{margin-left:8px;font-size:12px;color:#94a3b8}}
</style></head><body>
<h1>&#x1f9ec; sauravimmune — Code Immune System</h1>
<p style="text-align:center;color:#64748b">{report.timestamp} | {report.files_scanned} files | {report.total_functions} functions | {len(report.pathogens)} pathogens</p>

<div class="tabs">
<div class="tab active" onclick="showTab('health')">Health</div>
<div class="tab" onclick="showTab('pathogens')">Pathogens</div>
<div class="tab" onclick="showTab('memory')">Memory</div>
<div class="tab" onclick="showTab('autoimmune')">Autoimmune</div>
</div>

<div id="panel-health" class="panel active"></div>
<div id="panel-pathogens" class="panel"></div>
<div id="panel-memory" class="panel"></div>
<div id="panel-autoimmune" class="panel"></div>

<script>
const pathogens={pathogens_json};
const antibodies={antibodies_json};
const memEntries={memory_json};
const autoimmune={autoimmune_json};
const insights={insights_json};
const summary={summary_json};
const score={score};
const tier="{tier}";

function showTab(name){{
  document.querySelectorAll('.tab').forEach((t,i)=>t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  document.getElementById('panel-'+name).classList.add('active');
  event.target.classList.add('active');
}}

// Health panel
(function(){{
  const colors={{god_function:'#ef4444',dead_parameter:'#f97316',magic_number:'#eab308',
    deep_nesting:'#a855f7',duplicated_logic:'#ec4899',missing_error_handling:'#3b82f6',
    orphan_function:'#6b7280',overloaded_params:'#14b8a6',naming_violation:'#84cc16',
    unguarded_recursion:'#f43f5e'}};
  let maxC=Math.max(1,...Object.values(summary));
  let bars='';
  for(let[cat,cnt]of Object.entries(summary)){{
    let w=Math.round((cnt/maxC)*300);
    let c=colors[cat]||'#64748b';
    bars+=`<div class="chart-bar"><span class="label">${{cat}}</span><div class="bar" style="width:${{w}}px;background:${{c}}"></div><span class="count">${{cnt}}</span></div>`;
  }}
  let ins='';
  insights.forEach(i=>{{ins+=`<div class="insight">${{i}}</div>`}});
  document.getElementById('panel-health').innerHTML=`
    <div class="gauge"><div class="score">${{score}}</div><div class="tier">${{tier}}</div></div>
    <h3 style="margin:16px 0 8px">Pathogen Breakdown</h3>${{bars}}
    <h3 style="margin:16px 0 8px">Autonomous Insights</h3>${{ins}}`;
}})();

// Pathogens panel
(function(){{
  const abMap={{}};
  antibodies.forEach(a=>abMap[a.pathogen_id]=a);
  let rows='';
  pathogens.forEach(p=>{{
    let ab=abMap[p.id]||{{}};
    rows+=`<tr><td>${{p.id}}</td><td><span class="badge badge-${{p.severity}}">${{p.severity}}</span></td>
      <td>${{p.category}}</td><td>${{p.location}}</td><td>${{p.description}}</td>
      <td>${{ab.remedy||'-'}}</td><td>${{ab.effort||'-'}}</td></tr>`;
  }});
  document.getElementById('panel-pathogens').innerHTML=`<table><tr><th>ID</th><th>Severity</th>
    <th>Category</th><th>Location</th><th>Description</th><th>Remedy</th><th>Effort</th></tr>${{rows}}</table>`;
}})();

// Memory panel
(function(){{
  let rows='';
  memEntries.forEach(m=>{{
    let badge=m.resolved?'<span class="badge badge-resolved">resolved</span>':'<span class="badge badge-active">active</span>';
    rows+=`<tr><td>${{m.category}}</td><td>${{m.file}}</td><td>${{m.occurrences}}</td>
      <td>${{m.first_seen}}</td><td>${{m.last_seen}}</td><td>${{badge}}</td></tr>`;
  }});
  document.getElementById('panel-memory').innerHTML=`<table><tr><th>Category</th><th>File</th>
    <th>Occurrences</th><th>First Seen</th><th>Last Seen</th><th>Status</th></tr>${{rows}}</table>`;
}})();

// Autoimmune panel
(function(){{
  let rows='';
  autoimmune.forEach(a=>{{
    rows+=`<tr><td><span class="badge badge-${{a.severity}}">${{a.severity}}</span></td>
      <td>${{a.category}}</td><td>${{a.location}}</td><td>${{a.description}}</td></tr>`;
  }});
  document.getElementById('panel-autoimmune').innerHTML=rows?
    `<table><tr><th>Severity</th><th>Category</th><th>Location</th><th>Description</th></tr>${{rows}}</table>`:
    '<p style="text-align:center;color:#64748b;padding:20px">No autoimmune issues detected — healthy balance</p>';
}})();
</script></body></html>"""


# ── Main Analysis Pipeline ────────────────────────────────────────────

def analyze_immune(paths: List[str], recursive: bool = False,
                   scan_dir: str = ".") -> ImmuneReport:
    """Run full immune system analysis pipeline."""
    _reset_pathogen_counter()
    srv_files = _find_srv_files(paths, recursive=recursive)
    report = ImmuneReport(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        files_scanned=len(srv_files)
    )

    # Parse all functions
    all_funcs: List[FuncInfo] = []
    for fp in srv_files:
        all_funcs.extend(_parse_functions(fp))

    report.total_functions = len(all_funcs)

    # Build cross-function call targets
    all_call_targets: Set[str] = set()
    for fn in all_funcs:
        for callee in fn.calls:
            all_call_targets.add(callee)

    # I001: Pathogen Scanner
    report.pathogens = _scan_pathogens(all_funcs, all_call_targets)

    # I002: Antibody Generator
    report.antibodies = _generate_antibodies(report.pathogens)

    # Pathogen summary
    report.pathogen_summary = dict(Counter(p.category for p in report.pathogens))

    # I003: Immune Memory
    memory = _load_memory(scan_dir)

    # I006: Immune Score (need it before memory update to record)
    report.immune_score = _compute_immune_score(
        all_funcs, report.pathogens, memory,
        [], []  # vaccinations and autoimmune not yet computed
    )

    # Update memory with current scan
    report.memory_entries = _update_memory(
        memory, report.pathogens, report.immune_score, report.files_scanned
    )
    _save_memory(scan_dir, memory)
    report.memory_stats = {
        "total_scans": len(memory.get("scans", [])),
        "tracked_pathogens": len(memory.get("pathogens", {})),
        "resolved": sum(1 for v in memory.get("pathogens", {}).values() if v["resolved"]),
        "active": sum(1 for v in memory.get("pathogens", {}).values() if not v["resolved"])
    }

    # I004: Vaccination Engine
    report.vaccinations = _run_vaccinations(all_funcs, memory)

    # I005: Autoimmune Detector
    report.autoimmune_issues = _detect_autoimmune(all_funcs)

    # Recompute score with all data
    report.immune_score = _compute_immune_score(
        all_funcs, report.pathogens, memory,
        report.vaccinations, report.autoimmune_issues
    )

    # I007: Insights
    report.insights = _generate_insights(report, memory)

    return report


# ── CLI Print ─────────────────────────────────────────────────────────

def _severity_icon(s):
    return {"critical": red("!!!"), "high": yellow("!! "),
            "medium": cyan("!  "), "low": dim("o  ")}.get(s, "   ")


def _print_report(report: ImmuneReport) -> None:
    """Print full report to terminal."""
    tier = _score_tier(report.immune_score)
    tier_colors = {"Fortified": green, "Healthy": cyan, "Vulnerable": yellow,
                   "Compromised": yellow, "Critical": red}
    color_fn = tier_colors.get(tier, dim)

    print(bold(f"\n  {'='*55}"))
    print(bold(f"  sauravimmune — Code Immune System"))
    print(bold(f"  {'='*55}"))
    print(f"  {report.timestamp}")
    print(f"  Files: {report.files_scanned}  |  Functions: {report.total_functions}")
    print(f"  Immune Score: {color_fn(f'{report.immune_score:.1f}/100')} — {color_fn(tier)}")
    print()

    # Pathogen summary
    if report.pathogen_summary:
        print(bold("  Pathogen Summary:"))
        for cat, count in sorted(report.pathogen_summary.items(), key=lambda x: -x[1]):
            bar = "#" * min(count, 30)
            print(f"    {cat:28s} {count:3d}  {yellow(bar)}")
        print()

    # Top pathogens
    crits = [p for p in report.pathogens if p.severity in ("critical", "high")]
    if crits:
        print(bold(f"  Critical/High Pathogens ({len(crits)}):"))
        for p in crits[:10]:
            print(f"    {_severity_icon(p.severity)} {p.id} [{p.category}] {p.location}")
            print(f"        {dim(p.description)}")
        print()

    # Autoimmune issues
    if report.autoimmune_issues:
        print(bold(f"  Autoimmune Issues ({len(report.autoimmune_issues)}):"))
        for a in report.autoimmune_issues[:5]:
            print(f"    {magenta('~')} [{a.category}] {a.location}")
            print(f"        {dim(a.description)}")
        print()

    # Vaccinations
    if report.vaccinations:
        print(bold(f"  Vaccination Warnings ({len(report.vaccinations)}):"))
        for v in report.vaccinations[:5]:
            print(f"    {cyan('+')} {v['target']}: {v['warning']}")
        print()

    # Memory stats
    ms = report.memory_stats
    if ms:
        print(bold("  Immune Memory:"))
        print(f"    Scans: {ms.get('total_scans', 0)}  |  "
              f"Tracked: {ms.get('tracked_pathogens', 0)}  |  "
              f"Resolved: {green(ms.get('resolved', 0))}  |  "
              f"Active: {red(ms.get('active', 0))}")
        print()

    # Insights
    if report.insights:
        print(bold("  Autonomous Insights:"))
        for ins in report.insights:
            print(f"    {cyan('>')} {ins}")
        print()


# ── CLI ───────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sauravimmune",
        description="Autonomous code immune system for sauravcode"
    )
    parser.add_argument("paths", nargs="*", default=["."],
                        help=".srv files or directories to scan")
    parser.add_argument("--recursive", "-r", action="store_true",
                        help="Recurse into subdirectories")
    parser.add_argument("--html", metavar="FILE",
                        help="Generate interactive HTML dashboard")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON report")
    parser.add_argument("--pathogens", action="store_true",
                        help="Show only pathogens")
    parser.add_argument("--antibodies", action="store_true",
                        help="Show antibodies for each pathogen")
    parser.add_argument("--memory", action="store_true",
                        help="Show immune memory history")
    parser.add_argument("--vaccinate", action="store_true",
                        help="Run proactive vaccination checks")
    parser.add_argument("--autoimmune", action="store_true",
                        help="Show autoimmune issues")
    parser.add_argument("--critical", action="store_true",
                        help="Only show critical/high severity pathogens")
    parser.add_argument("--top", type=int, default=0,
                        help="Show top N pathogens by severity")
    parser.add_argument("--reset-memory", action="store_true",
                        help="Clear immune memory and start fresh")
    parser.add_argument("--no-color", action="store_true",
                        help="Disable colored output")

    args = parser.parse_args(argv)

    global USE_COLOR
    if args.no_color:
        USE_COLOR = False

    scan_dir = args.paths[0] if args.paths else "."
    if os.path.isfile(scan_dir):
        scan_dir = os.path.dirname(scan_dir) or "."

    # Reset memory if requested
    if args.reset_memory:
        mem_path = os.path.join(scan_dir, MEMORY_FILE)
        if os.path.isfile(mem_path):
            os.remove(mem_path)
            print("  Immune memory cleared.")
        else:
            print("  No immune memory to clear.")
        return 0

    report = analyze_immune(args.paths, recursive=args.recursive, scan_dir=scan_dir)

    # JSON output
    if args.json:
        out = {
            "timestamp": report.timestamp,
            "files_scanned": report.files_scanned,
            "total_functions": report.total_functions,
            "immune_score": report.immune_score,
            "pathogen_summary": report.pathogen_summary,
            "pathogens": [{"id": p.id, "category": p.category, "severity": p.severity,
                           "location": p.location, "description": p.description,
                           "evidence": p.evidence} for p in report.pathogens],
            "antibodies": [{"pathogen_id": a.pathogen_id, "remedy": a.remedy,
                            "effort": a.effort, "auto_fixable": a.auto_fixable}
                           for a in report.antibodies],
            "memory_entries": [{"first_seen": m.first_seen, "last_seen": m.last_seen,
                                "occurrences": m.occurrences, "resolved": m.resolved,
                                "category": m.pathogen_category, "file": m.file}
                               for m in report.memory_entries],
            "vaccinations": report.vaccinations,
            "autoimmune_issues": [{"category": a.category, "location": a.location,
                                   "description": a.description, "severity": a.severity}
                                  for a in report.autoimmune_issues],
            "insights": report.insights,
            "memory_stats": report.memory_stats
        }
        print(json.dumps(out, indent=2))
        return 0

    # HTML output
    if args.html:
        html = _generate_html(report)
        with open(args.html, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"  HTML immune dashboard -> {args.html}")
        return 0

    # Filtered views
    if args.pathogens:
        items = report.pathogens
        if args.critical:
            items = [p for p in items if p.severity in ("critical", "high")]
        print(bold(f"\n  Pathogens ({len(items)}):"))
        for p in items:
            print(f"    {_severity_icon(p.severity)} {p.id} [{p.category}] {p.location}")
            print(f"        {p.description}")
        return 0

    if args.antibodies:
        ab_map = {a.pathogen_id: a for a in report.antibodies}
        print(bold(f"\n  Antibodies ({len(report.antibodies)}):"))
        for p in report.pathogens:
            ab = ab_map.get(p.id)
            if ab:
                fix = green("auto-fix") if ab.auto_fixable else dim("manual")
                print(f"    {p.id} [{p.category}] -> {ab.remedy} ({ab.effort}, {fix})")
        return 0

    if args.memory:
        print(bold(f"\n  Immune Memory ({len(report.memory_entries)} entries):"))
        for m in report.memory_entries:
            status = green("resolved") if m.resolved else red("active")
            print(f"    [{m.pathogen_category}] {m.file} — seen {m.occurrences}x — {status}")
            print(f"        first: {m.first_seen}  last: {m.last_seen}")
        return 0

    if args.vaccinate:
        print(bold(f"\n  Vaccination Report ({len(report.vaccinations)} warnings):"))
        for v in report.vaccinations:
            print(f"    [{v['type']}] {v['target']}")
            print(f"        {v['warning']}")
            print(f"        Rx: {v['recommendation']}")
        return 0

    if args.autoimmune:
        print(bold(f"\n  Autoimmune Issues ({len(report.autoimmune_issues)}):"))
        for a in report.autoimmune_issues:
            print(f"    {_severity_icon(a.severity)} [{a.category}] {a.location}")
            print(f"        {a.description}")
        return 0

    if args.top > 0:
        sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        sorted_p = sorted(report.pathogens, key=lambda p: sev_order.get(p.severity, 9))
        for i, p in enumerate(sorted_p[:args.top], 1):
            print(f"    {i:2d}. {_severity_icon(p.severity)} [{p.category}] {p.location} — {p.description}")
        return 0

    # Full report
    _print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
