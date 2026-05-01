#!/usr/bin/env python3
"""sauravfossil — Autonomous Code Fossil Record Analyzer for sauravcode.

Examines .srv programs like geological strata: identifies dead code,
orphaned functions, vestigial logic, unreachable branches, and
evolutionary layers. Produces excavation plans for safe removal and
dates code into temporal layers based on complexity and style patterns.

Analysis engines (8):
    F001  Dead Function Detector       Functions never called anywhere
    F002  Orphaned Variable Finder     Variables assigned but never read
    F003  Vestigial Branch Detector    Conditions that are always true/false
    F004  Unreachable Code Scanner     Code after return/break/continue
    F005  Redundant Import Finder      Imports whose exports aren't used
    F006  Code Layer Dating            Groups code into evolutionary epochs
    F007  Fossil Dependency Mapper     Dead code that references other dead code
    F008  Excavation Planner           Safe removal plan with risk assessment

Usage:
    python sauravfossil.py target.srv                  # Full fossil analysis
    python sauravfossil.py . --recursive               # Deep scan all .srv files
    python sauravfossil.py target.srv --html report.html  # Interactive HTML dashboard
    python sauravfossil.py target.srv --json           # JSON output
    python sauravfossil.py . --excavate                # Show safe removal plan
    python sauravfossil.py . --layers                  # Show evolutionary layers
    python sauravfossil.py . --summary                 # Quick fossil count
"""

import sys
import os
import re
import json
import math
import argparse
import hashlib
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

# ── Regex ─────────────────────────────────────────────────────────────

FUNC_DEF_RE = re.compile(r"^(\s*)(?:function|fn)\s+(\w+)\s*(.*)")
CALL_RE = re.compile(r"\b([a-zA-Z_]\w*)\s*\(")
IMPORT_RE = re.compile(r'''import\s+["']([^"']+)["']''')
ASSIGN_RE = re.compile(r"^\s*([a-zA-Z_]\w*)\s*=")
IDENT_RE = re.compile(r"\b([a-zA-Z_]\w*)\b")
COMMENT_RE = re.compile(r"^\s*#")
RETURN_RE = re.compile(r"^\s*(return|break|continue)\b")
IF_RE = re.compile(r"^\s*if\s+(.*?):")
ELSE_RE = re.compile(r"^\s*else\s*:")
ELIF_RE = re.compile(r"^\s*elif\s+(.*?):")
WHILE_RE = re.compile(r"^\s*while\s+(.*?):")

BUILTIN_FUNCS = frozenset({
    "if", "while", "for", "print", "len", "str", "int", "float", "type",
    "range", "list", "dict", "set", "map", "filter", "sorted", "enumerate",
    "zip", "abs", "min", "max", "round", "input", "format", "open",
    "append", "push", "pop", "keys", "values", "split", "join", "strip",
    "replace", "find", "upper", "lower", "startswith", "endswith", "contains",
    "slice", "insert", "remove", "reverse", "sort", "clear", "copy",
    "typeof", "tostring", "toint", "tofloat", "tolist", "todict",
    "assert", "error", "throw", "catch", "try", "finally",
})

# ── Data Structures ──────────────────────────────────────────────────


@dataclass
class FuncInfo:
    """Parsed function information."""
    name: str
    file: str
    line: int
    end_line: int
    params: List[str]
    body_lines: List[str]
    callees: Set[str] = field(default_factory=set)
    variables_written: Set[str] = field(default_factory=set)
    variables_read: Set[str] = field(default_factory=set)
    complexity: int = 1  # cyclomatic approximation


@dataclass
class Fossil:
    """A single identified code fossil."""
    fossil_id: str         # F001-F008
    category: str          # dead_function, orphaned_variable, etc.
    name: str              # function/variable name
    file: str
    line: int
    end_line: int
    description: str
    severity: str          # info, low, medium, high
    confidence: float      # 0.0-1.0
    removable_lines: int   # how many lines can be excavated
    dependencies: List[str] = field(default_factory=list)  # other fossils it touches
    layer: str = "unknown"  # evolutionary layer


@dataclass
class CodeLayer:
    """An evolutionary epoch in the code."""
    name: str
    era: str               # e.g., "primordial", "classic", "modern"
    functions: List[str]
    avg_complexity: float
    avg_line_length: float
    style_markers: List[str]
    line_range: Tuple[int, int] = (0, 0)
    fossil_density: float = 0.0  # fossils per 100 lines


@dataclass
class ExcavationPlan:
    """A safe removal plan for fossils."""
    target: Fossil
    safe_to_remove: bool
    risk_level: str        # safe, caution, risky
    blocked_by: List[str]  # other code that might break
    lines_recoverable: int
    instructions: str


@dataclass
class FossilReport:
    """Complete fossil analysis result."""
    fossils: List[Fossil] = field(default_factory=list)
    layers: List[CodeLayer] = field(default_factory=list)
    excavation_plans: List[ExcavationPlan] = field(default_factory=list)
    total_lines: int = 0
    fossil_lines: int = 0
    fossil_ratio: float = 0.0  # proportion of code that's fossil
    health_score: int = 100    # 0-100, lower = more fossilized
    files_scanned: int = 0
    functions_found: int = 0
    scan_time: float = 0.0
    engine_results: Dict[str, Any] = field(default_factory=dict)

    @property
    def health_level(self) -> str:
        if self.health_score >= 80:
            return "pristine"
        elif self.health_score >= 60:
            return "healthy"
        elif self.health_score >= 40:
            return "weathered"
        elif self.health_score >= 20:
            return "eroded"
        return "fossilized"


# ── Parsing ───────────────────────────────────────────────────────────

def _indent_level(line: str) -> int:
    count = 0
    for ch in line:
        if ch == " ":
            count += 1
        elif ch == "\t":
            count += 4
        else:
            break
    return count


def _parse_functions(lines: List[str], filepath: str) -> List[FuncInfo]:
    """Extract functions with call/variable analysis."""
    funcs = []
    i = 0
    while i < len(lines):
        m = FUNC_DEF_RE.match(lines[i])
        if m:
            indent = _indent_level(lines[i])
            name = m.group(2)
            params_raw = m.group(3).strip().strip("()")
            params = [p.strip() for p in re.split(r"[,\s]+", params_raw) if p.strip()]
            body_start = i + 1
            j = body_start
            while j < len(lines):
                stripped = lines[j].strip()
                if stripped == "":
                    j += 1
                    continue
                if _indent_level(lines[j]) <= indent and stripped:
                    break
                j += 1
            body = lines[body_start:j]
            # Analysis
            callees = set()
            vars_written = set()
            vars_read = set()
            complexity = 1
            for bline in body:
                stripped = bline.strip()
                if stripped.startswith("#"):
                    continue
                for cm in CALL_RE.finditer(stripped):
                    callee = cm.group(1)
                    if callee not in BUILTIN_FUNCS:
                        callees.add(callee)
                am = ASSIGN_RE.match(bline)
                if am:
                    vars_written.add(am.group(1))
                for im in IDENT_RE.finditer(stripped):
                    ident = im.group(1)
                    if ident not in BUILTIN_FUNCS and ident != name:
                        vars_read.add(ident)
                # Cyclomatic complexity
                if re.match(r"\s*(if|elif|while|for|and|or)\b", stripped):
                    complexity += 1

            funcs.append(FuncInfo(
                name=name, file=filepath, line=i + 1, end_line=j,
                params=params, body_lines=body, callees=callees,
                variables_written=vars_written, variables_read=vars_read,
                complexity=complexity,
            ))
            i = j
        else:
            i += 1
    return funcs


def _collect_all_calls(lines: List[str]) -> Set[str]:
    """Collect all function calls in a file (top-level + inside functions)."""
    calls = set()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # Skip function definition lines — they aren't calls
        if FUNC_DEF_RE.match(stripped):
            continue
        for m in CALL_RE.finditer(stripped):
            callee = m.group(1)
            if callee not in BUILTIN_FUNCS:
                calls.add(callee)
    return calls


def _collect_all_identifiers(lines: List[str]) -> Set[str]:
    """Collect all identifiers referenced in a file."""
    idents = set()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for m in IDENT_RE.finditer(stripped):
            idents.add(m.group(1))
    return idents


def _collect_calls_and_idents(lines: List[str]) -> Tuple[Set[str], Set[str]]:
    """Single-pass collection of both function calls and identifiers.

    Replaces calling _collect_all_calls + _collect_all_identifiers separately,
    which would iterate all lines twice applying regex on each.
    """
    calls: Set[str] = set()
    idents: Set[str] = set()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        is_func_def = bool(FUNC_DEF_RE.match(stripped))
        for m in IDENT_RE.finditer(stripped):
            idents.add(m.group(1))
        if not is_func_def:
            for m in CALL_RE.finditer(stripped):
                callee = m.group(1)
                if callee not in BUILTIN_FUNCS:
                    calls.add(callee)
    return calls, idents


# ── Engine F001: Dead Function Detector ──────────────────────────────

def _engine_dead_functions(all_funcs: List[FuncInfo],
                           all_calls: Dict[str, Set[str]],
                           entry_points: Set[str]) -> List[Fossil]:
    """Find functions that are never called anywhere."""
    fossils = []
    defined_names = {f.name for f in all_funcs}
    called_names = set()
    for calls in all_calls.values():
        called_names.update(calls)

    for func in all_funcs:
        if func.name in called_names:
            continue
        if func.name in entry_points:
            continue
        # High confidence dead function
        lines_count = func.end_line - func.line
        fossils.append(Fossil(
            fossil_id="F001",
            category="dead_function",
            name=func.name,
            file=func.file,
            line=func.line,
            end_line=func.end_line,
            description=f"Function '{func.name}' is defined but never called",
            severity="medium" if lines_count > 10 else "low",
            confidence=0.9,
            removable_lines=lines_count,
        ))
    return fossils


# ── Engine F002: Orphaned Variable Finder ────────────────────────────

def _engine_orphaned_variables(all_funcs: List[FuncInfo],
                               file_lines: Dict[str, List[str]]) -> List[Fossil]:
    """Find variables assigned but never read."""
    fossils = []

    for func in all_funcs:
        # Variables written in this function
        written = func.variables_written - set(func.params)
        # Variables read anywhere in the function body
        read_in_body = set()
        for bline in func.body_lines:
            stripped = bline.strip()
            if stripped.startswith("#"):
                continue
            # Don't count assignment LHS as read
            am = ASSIGN_RE.match(bline)
            lhs = am.group(1) if am else None
            for m in IDENT_RE.finditer(stripped):
                ident = m.group(1)
                if ident != lhs:
                    read_in_body.add(ident)

        orphans = written - read_in_body - func.callees
        for var_name in orphans:
            # Find the assignment line
            var_line = func.line
            for idx, bline in enumerate(func.body_lines):
                if re.match(rf"^\s*{re.escape(var_name)}\s*=", bline):
                    var_line = func.line + idx + 1
                    break
            fossils.append(Fossil(
                fossil_id="F002",
                category="orphaned_variable",
                name=f"{func.name}.{var_name}",
                file=func.file,
                line=var_line,
                end_line=var_line,
                description=f"Variable '{var_name}' in '{func.name}' is assigned but never read",
                severity="info",
                confidence=0.75,
                removable_lines=1,
            ))
    return fossils


# ── Engine F003: Vestigial Branch Detector ───────────────────────────

def _engine_vestigial_branches(file_lines: Dict[str, List[str]]) -> List[Fossil]:
    """Find conditions that are always true or always false."""
    fossils = []
    always_true = {"true", "True", "1", "yes"}
    always_false = {"false", "False", "0", "no", "nil", "null", "none", "None"}

    for filepath, lines in file_lines.items():
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            # Check if/while conditions
            for pattern, kw in [(IF_RE, "if"), (ELIF_RE, "elif"), (WHILE_RE, "while")]:
                m = pattern.match(stripped)
                if m:
                    cond = m.group(1).strip()
                    if cond in always_true:
                        fossils.append(Fossil(
                            fossil_id="F003",
                            category="vestigial_branch",
                            name=f"always_true_{kw}",
                            file=filepath,
                            line=i + 1,
                            end_line=i + 1,
                            description=f"'{kw} {cond}' is always true — branch is vestigial",
                            severity="low",
                            confidence=0.95,
                            removable_lines=0,  # can't remove, but can simplify
                        ))
                    elif cond in always_false:
                        # Find extent of dead branch
                        indent = _indent_level(line)
                        j = i + 1
                        while j < len(lines):
                            if lines[j].strip() == "":
                                j += 1
                                continue
                            if _indent_level(lines[j]) <= indent:
                                break
                            j += 1
                        dead_lines = j - i
                        fossils.append(Fossil(
                            fossil_id="F003",
                            category="vestigial_branch",
                            name=f"always_false_{kw}",
                            file=filepath,
                            line=i + 1,
                            end_line=j,
                            description=f"'{kw} {cond}' is always false — entire block is dead",
                            severity="medium",
                            confidence=0.95,
                            removable_lines=dead_lines,
                        ))
    return fossils


# ── Engine F004: Unreachable Code Scanner ────────────────────────────

def _engine_unreachable_code(all_funcs: List[FuncInfo],
                             file_lines: Dict[str, List[str]]) -> List[Fossil]:
    """Find code after return/break/continue at same indent level."""
    fossils = []

    for func in all_funcs:
        in_unreachable = False
        unreachable_start = -1
        prev_indent = -1

        for idx, bline in enumerate(func.body_lines):
            stripped = bline.strip()
            if stripped == "":
                continue
            curr_indent = _indent_level(bline)

            if in_unreachable:
                if curr_indent <= prev_indent and not stripped.startswith(("else", "elif", "catch", "finally")):
                    # End of unreachable zone — exited the block
                    in_unreachable = False
                elif curr_indent == prev_indent + 4 or curr_indent == prev_indent:
                    # Still unreachable at same or deeper level
                    continue

            rm = RETURN_RE.match(stripped)
            if rm and not in_unreachable:
                # Check if next non-empty line at same indent exists
                k = idx + 1
                while k < len(func.body_lines):
                    next_stripped = func.body_lines[k].strip()
                    if next_stripped == "":
                        k += 1
                        continue
                    next_indent = _indent_level(func.body_lines[k])
                    if next_indent < curr_indent:
                        break  # Back to outer scope — fine
                    if next_indent == curr_indent and not next_stripped.startswith(("else", "elif", "catch", "finally")):
                        # Unreachable!
                        in_unreachable = True
                        unreachable_start = func.line + k
                        prev_indent = curr_indent
                        # Count unreachable lines
                        end_k = k
                        while end_k < len(func.body_lines):
                            es = func.body_lines[end_k].strip()
                            if es and _indent_level(func.body_lines[end_k]) < curr_indent:
                                break
                            end_k += 1
                        dead_count = end_k - k
                        fossils.append(Fossil(
                            fossil_id="F004",
                            category="unreachable_code",
                            name=f"{func.name}_after_{rm.group(1)}",
                            file=func.file,
                            line=unreachable_start,
                            end_line=func.line + end_k,
                            description=f"Code after '{rm.group(1)}' in '{func.name}' is unreachable",
                            severity="medium",
                            confidence=0.85,
                            removable_lines=dead_count,
                        ))
                    break
    return fossils


# ── Engine F005: Redundant Import Finder ─────────────────────────────

def _engine_redundant_imports(file_lines: Dict[str, List[str]],
                              all_idents: Dict[str, Set[str]]) -> List[Fossil]:
    """Find imports whose symbols are never referenced."""
    fossils = []

    for filepath, lines in file_lines.items():
        idents = all_idents.get(filepath, set())
        # Build full text once per file for substring checks (module names
        # that aren't valid identifiers or appear as substrings).
        # Previously this joined all non-import lines per import — O(I×N).
        full_text = " ".join(lines)
        for i, line in enumerate(lines):
            m = IMPORT_RE.match(line.strip())
            if m:
                imported_path = m.group(1)
                # Extract module name from path
                module_name = os.path.splitext(os.path.basename(imported_path))[0]
                # Fast path: check pre-collected identifier set first (O(1)).
                # Fall back to substring search in full text for non-identifier
                # module names (rare).
                if module_name not in idents and module_name not in full_text:
                    fossils.append(Fossil(
                        fossil_id="F005",
                        category="redundant_import",
                        name=imported_path,
                        file=filepath,
                        line=i + 1,
                        end_line=i + 1,
                        description=f"Import '{imported_path}' appears unused",
                        severity="info",
                        confidence=0.7,
                        removable_lines=1,
                    ))
    return fossils


# ── Engine F006: Code Layer Dating ───────────────────────────────────

def _engine_layer_dating(all_funcs: List[FuncInfo],
                         file_lines: Dict[str, List[str]]) -> List[CodeLayer]:
    """Group code into evolutionary epochs based on style and complexity."""
    if not all_funcs:
        return []

    # Compute per-function metrics
    func_metrics = []
    for func in all_funcs:
        avg_line_len = (sum(len(l) for l in func.body_lines) / max(len(func.body_lines), 1))
        has_comments = any(l.strip().startswith("#") for l in func.body_lines)
        uses_fstrings = any("f\"" in l or "f'" in l for l in func.body_lines)
        uses_list_comp = any("[" in l and "for" in l and "in" in l for l in func.body_lines)
        nesting = max((_indent_level(l) for l in func.body_lines if l.strip()), default=0)

        func_metrics.append({
            "func": func,
            "complexity": func.complexity,
            "avg_line_len": avg_line_len,
            "has_comments": has_comments,
            "uses_fstrings": uses_fstrings,
            "uses_list_comp": uses_list_comp,
            "nesting": nesting,
            "line_count": len(func.body_lines),
        })

    # Classify into layers by complexity bands
    layers = []

    # Primordial: simple, short, no advanced features
    primordial = [m for m in func_metrics
                  if m["complexity"] <= 2 and m["line_count"] <= 5
                  and not m["uses_fstrings"] and not m["uses_list_comp"]]
    if primordial:
        layers.append(CodeLayer(
            name="Primordial",
            era="primordial",
            functions=[m["func"].name for m in primordial],
            avg_complexity=sum(m["complexity"] for m in primordial) / len(primordial),
            avg_line_length=sum(m["avg_line_len"] for m in primordial) / len(primordial),
            style_markers=["simple", "short", "no_advanced_features"],
        ))

    # Classic: moderate complexity, some patterns
    classic = [m for m in func_metrics
               if 2 < m["complexity"] <= 5 or (m["line_count"] > 5 and m["complexity"] <= 3)]
    if classic:
        markers = []
        if any(m["has_comments"] for m in classic):
            markers.append("documented")
        if any(m["uses_list_comp"] for m in classic):
            markers.append("list_comprehensions")
        layers.append(CodeLayer(
            name="Classic",
            era="classic",
            functions=[m["func"].name for m in classic],
            avg_complexity=sum(m["complexity"] for m in classic) / len(classic),
            avg_line_length=sum(m["avg_line_len"] for m in classic) / len(classic),
            style_markers=markers or ["structured"],
        ))

    # Modern: high complexity, advanced features
    modern = [m for m in func_metrics
              if m["complexity"] > 5 or m["uses_fstrings"] or m["nesting"] > 12]
    if modern:
        markers = []
        if any(m["uses_fstrings"] for m in modern):
            markers.append("f-strings")
        if any(m["nesting"] > 12 for m in modern):
            markers.append("deep_nesting")
        markers.append("high_complexity")
        layers.append(CodeLayer(
            name="Modern",
            era="modern",
            functions=[m["func"].name for m in modern],
            avg_complexity=sum(m["complexity"] for m in modern) / len(modern),
            avg_line_length=sum(m["avg_line_len"] for m in modern) / len(modern),
            style_markers=markers,
        ))

    # Handle uncategorized
    categorized = set()
    for layer in layers:
        categorized.update(layer.functions)
    uncategorized = [m for m in func_metrics if m["func"].name not in categorized]
    if uncategorized:
        layers.append(CodeLayer(
            name="Transitional",
            era="transitional",
            functions=[m["func"].name for m in uncategorized],
            avg_complexity=sum(m["complexity"] for m in uncategorized) / len(uncategorized),
            avg_line_length=sum(m["avg_line_len"] for m in uncategorized) / len(uncategorized),
            style_markers=["mixed_era"],
        ))

    return layers


# ── Engine F007: Fossil Dependency Mapper ────────────────────────────

def _engine_fossil_dependencies(fossils: List[Fossil],
                                all_funcs: List[FuncInfo]) -> List[Fossil]:
    """Map dependencies between fossils — dead code referencing other dead code."""
    dead_names = {f.name.split(".")[0] if "." in f.name else f.name
                  for f in fossils if f.category == "dead_function"}

    func_map = {f.name: f for f in all_funcs}

    for fossil in fossils:
        if fossil.category == "dead_function":
            func = func_map.get(fossil.name)
            if func:
                # Check if this dead function calls other dead functions
                dead_callees = func.callees & dead_names
                fossil.dependencies = list(dead_callees)

    return fossils


# ── Engine F008: Excavation Planner ──────────────────────────────────

def _engine_excavation_planner(fossils: List[Fossil],
                               all_funcs: List[FuncInfo],
                               all_calls: Dict[str, Set[str]]) -> List[ExcavationPlan]:
    """Generate safe removal plans for each fossil."""
    plans = []
    all_called = set()
    for calls in all_calls.values():
        all_called.update(calls)

    func_map = {f.name: f for f in all_funcs}

    for fossil in fossils:
        if fossil.category == "dead_function":
            # Check if anything depends on this (shouldn't, but verify)
            dependents = []
            for func in all_funcs:
                if fossil.name in func.callees and func.name != fossil.name:
                    dependents.append(func.name)

            safe = len(dependents) == 0
            risk = "safe" if safe else "risky"
            instructions = (
                f"Remove lines {fossil.line}-{fossil.end_line} from {fossil.file}"
                if safe else
                f"WARNING: Referenced by {', '.join(dependents)} — verify before removal"
            )
            plans.append(ExcavationPlan(
                target=fossil,
                safe_to_remove=safe,
                risk_level=risk,
                blocked_by=dependents,
                lines_recoverable=fossil.removable_lines,
                instructions=instructions,
            ))
        elif fossil.category == "orphaned_variable":
            plans.append(ExcavationPlan(
                target=fossil,
                safe_to_remove=True,
                risk_level="safe",
                blocked_by=[],
                lines_recoverable=1,
                instructions=f"Remove assignment at line {fossil.line} in {fossil.file}",
            ))
        elif fossil.category in ("unreachable_code", "vestigial_branch"):
            plans.append(ExcavationPlan(
                target=fossil,
                safe_to_remove=fossil.confidence >= 0.85,
                risk_level="safe" if fossil.confidence >= 0.85 else "caution",
                blocked_by=[],
                lines_recoverable=fossil.removable_lines,
                instructions=f"Remove lines {fossil.line}-{fossil.end_line} from {fossil.file}",
            ))
        elif fossil.category == "redundant_import":
            plans.append(ExcavationPlan(
                target=fossil,
                safe_to_remove=True,
                risk_level="safe",
                blocked_by=[],
                lines_recoverable=1,
                instructions=f"Remove import at line {fossil.line} in {fossil.file}",
            ))

    return plans


# ── Main Analyzer ────────────────────────────────────────────────────

class FossilAnalyzer:
    """Orchestrates all fossil detection engines."""

    # Common entry points that shouldn't be flagged as dead
    ENTRY_POINTS = {"main", "init", "setup", "run", "start", "test", "demo",
                    "configure", "handle", "process", "execute", "serve"}

    def __init__(self, paths: List[str], recursive: bool = False):
        self.files = _find_srv_files(paths, recursive=recursive)
        self.file_lines: Dict[str, List[str]] = {}
        self.all_funcs: List[FuncInfo] = []
        self.all_calls: Dict[str, Set[str]] = {}
        self.all_idents: Dict[str, Set[str]] = {}

    def parse(self):
        """Parse all files."""
        for filepath in self.files:
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
            except (IOError, OSError):
                continue
            self.file_lines[filepath] = lines
            funcs = _parse_functions(lines, filepath)
            self.all_funcs.extend(funcs)
            calls, idents = _collect_calls_and_idents(lines)
            self.all_calls[filepath] = calls
            self.all_idents[filepath] = idents

    def analyze(self) -> FossilReport:
        """Run all engines and produce a report."""
        import time
        start = time.time()
        self.parse()

        report = FossilReport()
        report.files_scanned = len(self.files)
        report.functions_found = len(self.all_funcs)
        report.total_lines = sum(len(lines) for lines in self.file_lines.values())

        # F001: Dead functions
        dead_funcs = _engine_dead_functions(
            self.all_funcs, self.all_calls, self.ENTRY_POINTS)
        report.fossils.extend(dead_funcs)
        report.engine_results["F001_dead_functions"] = len(dead_funcs)

        # F002: Orphaned variables
        orphans = _engine_orphaned_variables(self.all_funcs, self.file_lines)
        report.fossils.extend(orphans)
        report.engine_results["F002_orphaned_variables"] = len(orphans)

        # F003: Vestigial branches
        vestigial = _engine_vestigial_branches(self.file_lines)
        report.fossils.extend(vestigial)
        report.engine_results["F003_vestigial_branches"] = len(vestigial)

        # F004: Unreachable code
        unreachable = _engine_unreachable_code(self.all_funcs, self.file_lines)
        report.fossils.extend(unreachable)
        report.engine_results["F004_unreachable_code"] = len(unreachable)

        # F005: Redundant imports
        redundant = _engine_redundant_imports(self.file_lines, self.all_idents)
        report.fossils.extend(redundant)
        report.engine_results["F005_redundant_imports"] = len(redundant)

        # F006: Layer dating
        layers = _engine_layer_dating(self.all_funcs, self.file_lines)
        report.layers = layers
        report.engine_results["F006_layers_detected"] = len(layers)

        # F007: Fossil dependencies
        report.fossils = _engine_fossil_dependencies(report.fossils, self.all_funcs)
        dep_count = sum(1 for f in report.fossils if f.dependencies)
        report.engine_results["F007_fossil_dependencies"] = dep_count

        # F008: Excavation plans
        plans = _engine_excavation_planner(
            report.fossils, self.all_funcs, self.all_calls)
        report.excavation_plans = plans
        report.engine_results["F008_excavation_plans"] = len(plans)

        # Assign layers to fossils
        layer_map = {}
        for layer in layers:
            for fname in layer.functions:
                layer_map[fname] = layer.era
        for fossil in report.fossils:
            base_name = fossil.name.split(".")[0] if "." in fossil.name else fossil.name
            fossil.layer = layer_map.get(base_name, "unknown")

        # Compute summary metrics
        report.fossil_lines = sum(f.removable_lines for f in report.fossils)
        report.fossil_ratio = (report.fossil_lines / max(report.total_lines, 1))
        # Health: start at 100, deduct for fossils
        deduction = min(80, int(report.fossil_ratio * 200) +
                        len([f for f in report.fossils if f.severity == "high"]) * 5 +
                        len([f for f in report.fossils if f.severity == "medium"]) * 2)
        report.health_score = max(0, 100 - deduction)
        report.scan_time = time.time() - start

        return report


# ── Output Formatting ────────────────────────────────────────────────

def _severity_color(severity: str) -> str:
    if severity == "high":
        return _C.red(severity.upper())
    elif severity == "medium":
        return _C.yellow(severity.upper())
    elif severity == "low":
        return _C.cyan(severity.upper())
    return _C.dim(severity.upper())


def _print_report(report: FossilReport, show_layers: bool = False,
                  show_excavation: bool = False):
    """Print the fossil report to terminal."""
    # Header
    print()
    print(_C.bold("🦴 SAURAVFOSSIL — Code Fossil Record Analyzer"))
    print(_C.dim("═" * 55))
    print()

    # Summary
    health_color = (_C.green if report.health_score >= 60 else
                    _C.yellow if report.health_score >= 40 else _C.red)
    print(f"  📊 Files scanned:     {report.files_scanned}")
    print(f"  📊 Functions found:   {report.functions_found}")
    print(f"  📊 Total lines:       {report.total_lines:,}")
    print(f"  🦴 Fossils detected:  {_C.bold(str(len(report.fossils)))}")
    print(f"  🗑️  Removable lines:   {report.fossil_lines:,} ({report.fossil_ratio:.1%})")
    print(f"  💚 Health score:      {health_color(f'{report.health_score}/100')} [{report.health_level}]")
    print(f"  ⏱️  Scan time:         {report.scan_time:.3f}s")
    print()

    # Engine breakdown
    print(_C.bold("  Engine Results:"))
    engine_labels = {
        "F001_dead_functions": "F001 Dead Functions",
        "F002_orphaned_variables": "F002 Orphaned Variables",
        "F003_vestigial_branches": "F003 Vestigial Branches",
        "F004_unreachable_code": "F004 Unreachable Code",
        "F005_redundant_imports": "F005 Redundant Imports",
        "F006_layers_detected": "F006 Evolutionary Layers",
        "F007_fossil_dependencies": "F007 Fossil Dependencies",
        "F008_excavation_plans": "F008 Excavation Plans",
    }
    for key, label in engine_labels.items():
        count = report.engine_results.get(key, 0)
        indicator = _C.green("●") if count == 0 else _C.yellow("●") if count < 5 else _C.red("●")
        print(f"    {indicator} {label}: {count}")
    print()

    # Fossils by category
    if report.fossils:
        print(_C.bold("  🦴 Fossil Inventory:"))
        print(_C.dim("  " + "─" * 50))
        by_category = defaultdict(list)
        for f in report.fossils:
            by_category[f.category].append(f)

        cat_icons = {
            "dead_function": "💀",
            "orphaned_variable": "👻",
            "vestigial_branch": "🌿",
            "unreachable_code": "🚫",
            "redundant_import": "📦",
        }
        for cat, items in sorted(by_category.items()):
            icon = cat_icons.get(cat, "🔍")
            print(f"\n    {icon} {cat.replace('_', ' ').title()} ({len(items)}):")
            for item in items[:10]:  # limit display
                loc = f"{os.path.basename(item.file)}:{item.line}"
                sev = _severity_color(item.severity)
                conf = f"{item.confidence:.0%}"
                print(f"      [{sev}] {item.name} @ {loc} (conf:{conf}, {item.removable_lines} lines)")
                if item.dependencies:
                    print(f"            ↳ depends on: {', '.join(item.dependencies[:5])}")
            if len(items) > 10:
                print(f"      ... and {len(items) - 10} more")

    # Layers
    if show_layers and report.layers:
        print()
        print(_C.bold("  🪨 Evolutionary Layers:"))
        print(_C.dim("  " + "─" * 50))
        era_icons = {"primordial": "🌋", "classic": "🏛️", "modern": "🚀", "transitional": "🔀"}
        for layer in report.layers:
            icon = era_icons.get(layer.era, "📐")
            print(f"\n    {icon} {layer.name} Era ({len(layer.functions)} functions)")
            print(f"      Avg complexity: {layer.avg_complexity:.1f}")
            print(f"      Avg line length: {layer.avg_line_length:.0f} chars")
            print(f"      Style: {', '.join(layer.style_markers)}")
            if layer.functions[:8]:
                print(f"      Functions: {', '.join(layer.functions[:8])}")
                if len(layer.functions) > 8:
                    print(f"                 ... +{len(layer.functions) - 8} more")

    # Excavation plans
    if show_excavation and report.excavation_plans:
        print()
        print(_C.bold("  ⛏️  Excavation Plan:"))
        print(_C.dim("  " + "─" * 50))
        safe_plans = [p for p in report.excavation_plans if p.safe_to_remove]
        risky_plans = [p for p in report.excavation_plans if not p.safe_to_remove]
        total_recoverable = sum(p.lines_recoverable for p in safe_plans)

        print(f"\n    ✅ Safe to remove: {len(safe_plans)} fossils ({total_recoverable} lines)")
        for plan in safe_plans[:15]:
            print(f"      • {plan.instructions}")
        if len(safe_plans) > 15:
            print(f"      ... +{len(safe_plans) - 15} more")

        if risky_plans:
            print(f"\n    ⚠️  Needs verification: {len(risky_plans)} fossils")
            for plan in risky_plans[:5]:
                print(f"      • {plan.instructions}")
                print(f"        Blocked by: {', '.join(plan.blocked_by[:3])}")

    print()


# ── HTML Dashboard ───────────────────────────────────────────────────

def _generate_html(report: FossilReport) -> str:
    """Generate an interactive HTML dashboard."""
    fossils_json = json.dumps([{
        "id": f.fossil_id,
        "category": f.category,
        "name": f.name,
        "file": os.path.basename(f.file),
        "line": f.line,
        "severity": f.severity,
        "confidence": f.confidence,
        "removable_lines": f.removable_lines,
        "description": f.description,
        "dependencies": f.dependencies,
        "layer": f.layer,
    } for f in report.fossils], indent=2)

    layers_json = json.dumps([{
        "name": l.name,
        "era": l.era,
        "functions": l.functions[:20],
        "avg_complexity": round(l.avg_complexity, 2),
        "style_markers": l.style_markers,
    } for l in report.layers], indent=2)

    plans_json = json.dumps([{
        "name": p.target.name,
        "safe": p.safe_to_remove,
        "risk": p.risk_level,
        "lines": p.lines_recoverable,
        "instructions": p.instructions,
        "blocked_by": p.blocked_by,
    } for p in report.excavation_plans], indent=2)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>sauravfossil — Code Fossil Record</title>
<style>
:root {{ --bg: #0d1117; --card: #161b22; --border: #30363d; --text: #c9d1d9;
         --accent: #58a6ff; --green: #3fb950; --yellow: #d29922; --red: #f85149;
         --purple: #bc8cff; --cyan: #39c5cf; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: var(--bg); color: var(--text); padding: 2rem; }}
h1 {{ color: var(--accent); margin-bottom: 0.5rem; font-size: 1.8rem; }}
.subtitle {{ color: #8b949e; margin-bottom: 2rem; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin: 1.5rem 0; }}
.card {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 1.2rem; }}
.card h3 {{ font-size: 0.85rem; color: #8b949e; text-transform: uppercase; margin-bottom: 0.5rem; }}
.card .value {{ font-size: 1.8rem; font-weight: bold; }}
.health-pristine {{ color: var(--green); }} .health-healthy {{ color: var(--green); }}
.health-weathered {{ color: var(--yellow); }} .health-eroded {{ color: var(--red); }}
.health-fossilized {{ color: var(--red); }}
.tabs {{ display: flex; gap: 0; margin: 2rem 0 0; border-bottom: 1px solid var(--border); }}
.tab {{ padding: 0.8rem 1.5rem; cursor: pointer; border-bottom: 2px solid transparent; color: #8b949e; }}
.tab.active {{ color: var(--accent); border-bottom-color: var(--accent); }}
.tab-content {{ display: none; padding: 1.5rem 0; }}
.tab-content.active {{ display: block; }}
table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; }}
th, td {{ padding: 0.6rem 0.8rem; text-align: left; border-bottom: 1px solid var(--border); font-size: 0.9rem; }}
th {{ color: #8b949e; font-weight: 600; }}
.sev-high {{ color: var(--red); }} .sev-medium {{ color: var(--yellow); }}
.sev-low {{ color: var(--cyan); }} .sev-info {{ color: #8b949e; }}
.layer-badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.75rem; }}
.era-primordial {{ background: #3d2200; color: #ffa657; }}
.era-classic {{ background: #1a2332; color: var(--accent); }}
.era-modern {{ background: #1a3320; color: var(--green); }}
.era-transitional {{ background: #2d1a33; color: var(--purple); }}
.bar {{ height: 8px; border-radius: 4px; background: var(--border); margin-top: 0.3rem; }}
.bar-fill {{ height: 100%; border-radius: 4px; }}
.safe {{ color: var(--green); }} .risky {{ color: var(--red); }} .caution {{ color: var(--yellow); }}
.filter-bar {{ margin: 1rem 0; display: flex; gap: 0.5rem; flex-wrap: wrap; }}
.filter-btn {{ padding: 4px 12px; border-radius: 16px; border: 1px solid var(--border);
               background: var(--card); color: var(--text); cursor: pointer; font-size: 0.8rem; }}
.filter-btn.active {{ border-color: var(--accent); background: #1a2736; }}
</style>
</head>
<body>
<h1>🦴 Code Fossil Record</h1>
<p class="subtitle">sauravfossil v{__version__} — Autonomous dead code archaeology</p>

<div class="grid">
  <div class="card"><h3>Fossils Found</h3><div class="value">{len(report.fossils)}</div></div>
  <div class="card"><h3>Recoverable Lines</h3><div class="value">{report.fossil_lines:,}</div></div>
  <div class="card"><h3>Fossil Ratio</h3><div class="value">{report.fossil_ratio:.1%}</div></div>
  <div class="card"><h3>Health Score</h3><div class="value health-{report.health_level}">{report.health_score}/100</div>
    <div class="bar"><div class="bar-fill" style="width:{report.health_score}%;background:var(--{'green' if report.health_score >= 60 else 'yellow' if report.health_score >= 40 else 'red'})"></div></div>
  </div>
  <div class="card"><h3>Files Scanned</h3><div class="value">{report.files_scanned}</div></div>
  <div class="card"><h3>Functions Found</h3><div class="value">{report.functions_found}</div></div>
</div>

<div class="tabs">
  <div class="tab active" onclick="showTab('fossils')">🦴 Fossils</div>
  <div class="tab" onclick="showTab('layers')">🪨 Layers</div>
  <div class="tab" onclick="showTab('excavation')">⛏️ Excavation</div>
  <div class="tab" onclick="showTab('engines')">⚙️ Engines</div>
</div>

<div id="tab-fossils" class="tab-content active">
  <div class="filter-bar" id="filters"></div>
  <table><thead><tr><th>ID</th><th>Category</th><th>Name</th><th>File</th><th>Line</th><th>Severity</th><th>Confidence</th><th>Lines</th><th>Layer</th></tr></thead>
  <tbody id="fossil-body"></tbody></table>
</div>

<div id="tab-layers" class="tab-content">
  <div id="layers-content"></div>
</div>

<div id="tab-excavation" class="tab-content">
  <table><thead><tr><th>Target</th><th>Risk</th><th>Lines</th><th>Instructions</th><th>Blocked By</th></tr></thead>
  <tbody id="excavation-body"></tbody></table>
</div>

<div id="tab-engines" class="tab-content">
  <table><thead><tr><th>Engine</th><th>Findings</th></tr></thead>
  <tbody id="engine-body"></tbody></table>
</div>

<script>
const fossils = {fossils_json};
const layers = {layers_json};
const plans = {plans_json};
const engines = {json.dumps(report.engine_results)};

function showTab(name) {{
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  event.target.classList.add('active');
}}

// Fossils table
let activeFilter = 'all';
const categories = [...new Set(fossils.map(f => f.category))];
const filterBar = document.getElementById('filters');
filterBar.innerHTML = '<div class="filter-btn active" onclick="filterFossils(\\'all\\')">All</div>' +
  categories.map(c => `<div class="filter-btn" onclick="filterFossils('${{c}}')">${{c.replace(/_/g,' ')}}</div>`).join('');

function filterFossils(cat) {{
  activeFilter = cat;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  renderFossils();
}}

function renderFossils() {{
  const filtered = activeFilter === 'all' ? fossils : fossils.filter(f => f.category === activeFilter);
  document.getElementById('fossil-body').innerHTML = filtered.map(f => `<tr>
    <td>${{f.id}}</td><td>${{f.category.replace(/_/g,' ')}}</td><td>${{f.name}}</td>
    <td>${{f.file}}</td><td>${{f.line}}</td>
    <td class="sev-${{f.severity}}">${{f.severity}}</td>
    <td>${{(f.confidence*100).toFixed(0)}}%</td><td>${{f.removable_lines}}</td>
    <td><span class="layer-badge era-${{f.layer}}">${{f.layer}}</span></td>
  </tr>`).join('');
}}
renderFossils();

// Layers
document.getElementById('layers-content').innerHTML = layers.map(l => `
  <div class="card" style="margin:1rem 0">
    <h3><span class="layer-badge era-${{l.era}}">${{l.era}}</span> ${{l.name}} Era</h3>
    <p>Functions: ${{l.functions.length}} | Avg complexity: ${{l.avg_complexity}}</p>
    <p style="color:#8b949e;font-size:0.85rem">Style: ${{l.style_markers.join(', ')}}</p>
    <p style="margin-top:0.5rem;font-size:0.85rem">${{l.functions.slice(0,10).join(', ')}}${{l.functions.length > 10 ? '...' : ''}}</p>
  </div>
`).join('');

// Excavation
document.getElementById('excavation-body').innerHTML = plans.map(p => `<tr>
  <td>${{p.name}}</td>
  <td class="${{p.risk}}">${{p.risk}}</td>
  <td>${{p.lines}}</td>
  <td style="font-size:0.85rem">${{p.instructions}}</td>
  <td>${{p.blocked_by.join(', ') || '—'}}</td>
</tr>`).join('');

// Engines
document.getElementById('engine-body').innerHTML = Object.entries(engines).map(([k,v]) => `<tr>
  <td>${{k.replace(/_/g,' ')}}</td><td>${{v}}</td>
</tr>`).join('');
</script>
</body>
</html>"""


# ── CLI ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="sauravfossil",
        description="Autonomous Code Fossil Record Analyzer for sauravcode",
    )
    parser.add_argument("paths", nargs="*", default=["."],
                        help="Files or directories to analyze")
    parser.add_argument("--recursive", "-r", action="store_true",
                        help="Recurse into subdirectories")
    parser.add_argument("--html", metavar="FILE",
                        help="Generate interactive HTML dashboard")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    parser.add_argument("--layers", action="store_true",
                        help="Show evolutionary layer analysis")
    parser.add_argument("--excavate", action="store_true",
                        help="Show excavation/removal plan")
    parser.add_argument("--summary", action="store_true",
                        help="Quick fossil count only")
    parser.add_argument("--min-confidence", type=float, default=0.0,
                        help="Minimum confidence threshold (0.0-1.0)")
    parser.add_argument("--severity", choices=["info", "low", "medium", "high"],
                        help="Filter by minimum severity")
    parser.add_argument("--category", choices=[
                            "dead_function", "orphaned_variable",
                            "vestigial_branch", "unreachable_code",
                            "redundant_import"],
                        help="Filter by fossil category")
    args = parser.parse_args()

    analyzer = FossilAnalyzer(args.paths, recursive=args.recursive)
    report = analyzer.analyze()

    # Filter by confidence
    if args.min_confidence > 0:
        report.fossils = [f for f in report.fossils if f.confidence >= args.min_confidence]

    # Filter by severity
    severity_order = {"info": 0, "low": 1, "medium": 2, "high": 3}
    if args.severity:
        min_sev = severity_order[args.severity]
        report.fossils = [f for f in report.fossils if severity_order.get(f.severity, 0) >= min_sev]

    # Filter by category
    if args.category:
        report.fossils = [f for f in report.fossils if f.category == args.category]

    # Output
    if args.json:
        output = {
            "version": __version__,
            "timestamp": datetime.now().isoformat(),
            "health_score": report.health_score,
            "health_level": report.health_level,
            "total_lines": report.total_lines,
            "fossil_lines": report.fossil_lines,
            "fossil_ratio": round(report.fossil_ratio, 4),
            "files_scanned": report.files_scanned,
            "functions_found": report.functions_found,
            "scan_time": round(report.scan_time, 3),
            "engine_results": report.engine_results,
            "fossils": [{
                "id": f.fossil_id, "category": f.category, "name": f.name,
                "file": f.file, "line": f.line, "end_line": f.end_line,
                "severity": f.severity, "confidence": f.confidence,
                "removable_lines": f.removable_lines, "description": f.description,
                "dependencies": f.dependencies, "layer": f.layer,
            } for f in report.fossils],
            "layers": [{
                "name": l.name, "era": l.era, "functions": l.functions,
                "avg_complexity": round(l.avg_complexity, 2),
                "style_markers": l.style_markers,
            } for l in report.layers],
            "excavation_plans": [{
                "target": p.target.name, "safe": p.safe_to_remove,
                "risk": p.risk_level, "lines": p.lines_recoverable,
                "instructions": p.instructions, "blocked_by": p.blocked_by,
            } for p in report.excavation_plans],
        }
        print(json.dumps(output, indent=2))
    elif args.html:
        html = _generate_html(report)
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  ✅ HTML dashboard written to: {args.html}")
    elif args.summary:
        print(f"🦴 Fossils: {len(report.fossils)} | "
              f"Lines: {report.fossil_lines} | "
              f"Health: {report.health_score}/100 [{report.health_level}]")
    else:
        _print_report(report, show_layers=args.layers, show_excavation=args.excavate)

    # Exit code: non-zero if health is poor
    sys.exit(0 if report.health_score >= 40 else 1)


if __name__ == "__main__":
    main()
