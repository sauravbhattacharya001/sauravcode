#!/usr/bin/env python3
"""sauravimpact — Autonomous Change Impact Analyzer for sauravcode.

Analyzes the blast radius of potential changes to .srv programs: which
functions/files depend on a target, cascade depth, risk scoring, and
suggested test coverage.  Helps developers understand consequences
before making changes.

Analysis engines (8):
    I001  Direct Dependency Scan       Functions that directly call the target
    I002  Transitive Dependency Chain  Full reachability via call graph
    I003  Variable Flow Analysis       Shared/global variable coupling
    I004  Import Ripple Detector       Downstream importers of a file
    I005  Structural Coupling Score    Bidirectional coupling measurement
    I006  Change Cascade Simulator     Breakage if signature changes
    I007  Test Coverage Gap Finder     Affected functions without tests
    I008  Risk Scorecard               Composite 0–100 risk score

Usage:
    python sauravimpact.py target.srv                    # Analyze all functions
    python sauravimpact.py target.srv --function myfunc  # Specific function
    python sauravimpact.py . --function myfunc           # Search all .srv files
    python sauravimpact.py . --recursive                 # Deep scan
    python sauravimpact.py target.srv --html report.html # Interactive HTML dashboard
    python sauravimpact.py target.srv --json             # JSON output
    python sauravimpact.py target.srv --graph            # ASCII call graph
    python sauravimpact.py . --hotspots                  # Highest blast radius functions
    python sauravimpact.py . --safe-changes              # Low-impact safe-to-modify functions
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

# ── Data Structures ──────────────────────────────────────────────────


@dataclass
class FuncInfo:
    """Parsed function information."""
    name: str
    file: str
    line: int
    params: List[str]
    body_lines: List[str]
    callees: List[str] = field(default_factory=list)
    variables_written: Set[str] = field(default_factory=set)
    variables_read: Set[str] = field(default_factory=set)


@dataclass
class ImpactNode:
    """A single entity affected by a change."""
    name: str
    file: str
    line: int
    impact_type: str  # direct_caller, transitive, variable_reader, importer, etc.
    depth: int
    risk: int  # 1-10
    description: str


@dataclass
class ImpactReport:
    """Complete impact analysis result."""
    target: str
    target_file: str
    nodes: List[ImpactNode] = field(default_factory=list)
    call_graph: Dict[str, List[str]] = field(default_factory=dict)
    risk_score: int = 0          # 0-100
    risk_level: str = "safe"     # safe/caution/warning/danger
    test_coverage: float = 0.0   # 0.0-1.0
    cascade_depth: int = 0
    total_affected: int = 0
    scan_time: float = 0.0
    files_scanned: int = 0
    total_lines: int = 0
    engine_results: Dict[str, Any] = field(default_factory=dict)

    @property
    def risk_color(self) -> str:
        if self.risk_score <= 25:
            return "green"
        elif self.risk_score <= 50:
            return "yellow"
        elif self.risk_score <= 75:
            return "orange"
        return "red"


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
            start = i
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
            # Analyze calls
            callees = set()
            vars_written = set()
            vars_read = set()
            for bline in body:
                stripped = bline.strip()
                if stripped.startswith("#"):
                    continue
                for cm in CALL_RE.finditer(stripped):
                    callee = cm.group(1)
                    if callee not in ("if", "while", "for", "print", "len", "str",
                                      "int", "float", "type", "range", "list",
                                      "dict", "set", "map", "filter", "sorted",
                                      "enumerate", "zip", "abs", "min", "max",
                                      "round", "input", "format", "open",
                                      "append", "push", "pop", "keys", "values"):
                        callees.add(callee)
                am = ASSIGN_RE.match(bline)
                if am:
                    vars_written.add(am.group(1))
                for im in IDENT_RE.finditer(stripped):
                    ident = im.group(1)
                    if ident not in params and ident != name:
                        vars_read.add(ident)

            funcs.append(FuncInfo(
                name=name, file=filepath, line=start + 1,
                params=params, body_lines=body,
                callees=list(callees),
                variables_written=vars_written,
                variables_read=vars_read,
            ))
            i = j
        else:
            i += 1
    return funcs


def _parse_imports(lines: List[str]) -> List[str]:
    """Extract imported file paths."""
    imports = []
    for line in lines:
        m = IMPORT_RE.search(line)
        if m:
            imports.append(m.group(1))
    return imports


def _read_file(filepath: str) -> List[str]:
    """Read file lines safely."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            return f.readlines()
    except (IOError, OSError):
        return []


# ── Call Graph ────────────────────────────────────────────────────────

def build_call_graph(all_funcs: List[FuncInfo]) -> Dict[str, List[str]]:
    """Build caller -> [callees] graph."""
    func_names = {f.name for f in all_funcs}
    graph = {}
    for f in all_funcs:
        graph[f.name] = [c for c in f.callees if c in func_names]
    return graph


def build_reverse_graph(graph: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """Build callee -> [callers] reverse graph."""
    reverse = defaultdict(list)
    for caller, callees in graph.items():
        for callee in callees:
            reverse[callee].append(caller)
    return dict(reverse)


def _bfs_reachable(graph: Dict[str, List[str]], start: str) -> Dict[str, int]:
    """BFS from start, return {node: depth}."""
    visited = {}
    queue = [(start, 0)]
    while queue:
        node, depth = queue.pop(0)
        if node in visited:
            continue
        visited[node] = depth
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                queue.append((neighbor, depth + 1))
    return visited


# ── Analysis Engines ──────────────────────────────────────────────────

def _engine_i001_direct_deps(target: str, reverse_graph: Dict[str, List[str]],
                              func_map: Dict[str, FuncInfo]) -> List[ImpactNode]:
    """I001: Direct callers of the target function."""
    nodes = []
    for caller in reverse_graph.get(target, []):
        fi = func_map.get(caller)
        if fi:
            nodes.append(ImpactNode(
                name=caller, file=fi.file, line=fi.line,
                impact_type="direct_caller", depth=1, risk=6,
                description=f"Directly calls {target}()",
            ))
    return nodes


def _engine_i002_transitive(target: str, reverse_graph: Dict[str, List[str]],
                             func_map: Dict[str, FuncInfo]) -> Tuple[List[ImpactNode], int]:
    """I002: Transitive callers via reverse call graph."""
    reachable = _bfs_reachable(reverse_graph, target)
    nodes = []
    max_depth = 0
    for name, depth in reachable.items():
        if name == target or depth <= 1:
            continue  # depth=1 handled by I001
        fi = func_map.get(name)
        if fi:
            risk = min(10, 3 + depth)
            nodes.append(ImpactNode(
                name=name, file=fi.file, line=fi.line,
                impact_type="transitive", depth=depth, risk=risk,
                description=f"Transitively depends on {target}() (depth {depth})",
            ))
            max_depth = max(max_depth, depth)
    return nodes, max_depth


def _engine_i003_variable_flow(target: str, all_funcs: List[FuncInfo],
                                func_map: Dict[str, FuncInfo]) -> List[ImpactNode]:
    """I003: Functions that read variables written by the target."""
    target_fi = func_map.get(target)
    if not target_fi:
        return []
    written = target_fi.variables_written
    if not written:
        return []
    nodes = []
    for f in all_funcs:
        if f.name == target:
            continue
        shared = written & f.variables_read
        if shared:
            nodes.append(ImpactNode(
                name=f.name, file=f.file, line=f.line,
                impact_type="variable_reader", depth=1, risk=7,
                description=f"Reads variable(s) {', '.join(sorted(shared))} written by {target}()",
            ))
    return nodes


def _engine_i004_import_ripple(target_file: str, file_imports: Dict[str, List[str]],
                                file_funcs: Dict[str, List[FuncInfo]]) -> List[ImpactNode]:
    """I004: Files that import the target file."""
    nodes = []
    target_base = os.path.splitext(os.path.basename(target_file))[0]
    for filepath, imports in file_imports.items():
        if filepath == target_file:
            continue
        for imp in imports:
            imp_base = os.path.splitext(os.path.basename(imp))[0]
            if imp_base == target_base or imp == target_file:
                for f in file_funcs.get(filepath, []):
                    nodes.append(ImpactNode(
                        name=f.name, file=filepath, line=f.line,
                        impact_type="importer", depth=1, risk=5,
                        description=f"In file that imports {target_base}",
                    ))
                if not file_funcs.get(filepath):
                    nodes.append(ImpactNode(
                        name=os.path.basename(filepath), file=filepath, line=1,
                        impact_type="importer", depth=1, risk=4,
                        description=f"File imports {target_base}",
                    ))
                break
    return nodes


def _engine_i005_coupling(target: str, graph: Dict[str, List[str]],
                           reverse_graph: Dict[str, List[str]],
                           func_map: Dict[str, FuncInfo]) -> Tuple[float, str]:
    """I005: Structural coupling score."""
    outgoing = len(graph.get(target, []))
    incoming = len(reverse_graph.get(target, []))
    fi = func_map.get(target)
    shared_vars = 0
    if fi:
        for other in func_map.values():
            if other.name != target:
                shared_vars += len(fi.variables_written & other.variables_read)
                shared_vars += len(fi.variables_read & other.variables_written)
    coupling = outgoing + incoming + shared_vars
    if coupling == 0:
        return 0.0, "isolated"
    elif coupling <= 3:
        return coupling / 10.0, "low"
    elif coupling <= 8:
        return coupling / 10.0, "moderate"
    else:
        return min(1.0, coupling / 15.0), "high"


def _engine_i006_cascade(target: str, graph: Dict[str, List[str]],
                          reverse_graph: Dict[str, List[str]],
                          func_map: Dict[str, FuncInfo]) -> List[ImpactNode]:
    """I006: Simulate signature change breakage."""
    nodes = []
    target_fi = func_map.get(target)
    if not target_fi:
        return nodes
    param_count = len(target_fi.params)
    for caller in reverse_graph.get(target, []):
        caller_fi = func_map.get(caller)
        if not caller_fi:
            continue
        # Count how many times caller calls target
        call_count = sum(1 for line in caller_fi.body_lines
                        if re.search(rf"\b{re.escape(target)}\s*\(", line))
        risk = min(10, 4 + call_count + (1 if param_count > 3 else 0))
        nodes.append(ImpactNode(
            name=caller, file=caller_fi.file, line=caller_fi.line,
            impact_type="cascade_break", depth=1, risk=risk,
            description=f"Would break if {target}() signature changes ({call_count} call site(s))",
        ))
    return nodes


def _engine_i007_test_coverage(affected_funcs: Set[str], test_files: List[str]) -> Tuple[float, List[str]]:
    """I007: Check test coverage of affected functions."""
    if not affected_funcs:
        return 1.0, []
    tested = set()
    for tf in test_files:
        lines = _read_file(tf)
        content = "".join(lines)
        for func in affected_funcs:
            if func in content:
                tested.add(func)
    untested = sorted(affected_funcs - tested)
    coverage = len(tested) / len(affected_funcs) if affected_funcs else 1.0
    return coverage, untested


def _engine_i008_risk_score(direct_count: int, transitive_count: int,
                             var_flow_count: int, import_count: int,
                             coupling_score: float, cascade_count: int,
                             test_coverage: float, cascade_depth: int) -> Tuple[int, str]:
    """I008: Composite risk score 0-100."""
    score = 0.0
    score += min(25, direct_count * 5)
    score += min(15, transitive_count * 2)
    score += min(15, var_flow_count * 5)
    score += min(10, import_count * 3)
    score += coupling_score * 15
    score += min(10, cascade_count * 3)
    score += (1.0 - test_coverage) * 10
    score += min(5, cascade_depth)
    score = int(min(100, max(0, score)))
    if score <= 25:
        level = "safe"
    elif score <= 50:
        level = "caution"
    elif score <= 75:
        level = "warning"
    else:
        level = "danger"
    return score, level


# ── Main Analysis ─────────────────────────────────────────────────────

def analyze(paths: List[str], target_function: Optional[str] = None,
            recursive: bool = False) -> List[ImpactReport]:
    """Run full impact analysis."""
    import time
    start_time = time.time()

    files = _find_srv_files(paths, recursive=recursive)
    if not files:
        return []

    # Parse all files
    all_funcs: List[FuncInfo] = []
    file_funcs: Dict[str, List[FuncInfo]] = {}
    file_imports: Dict[str, List[str]] = {}
    total_lines = 0

    for filepath in files:
        lines = _read_file(filepath)
        total_lines += len(lines)
        funcs = _parse_functions(lines, filepath)
        all_funcs.extend(funcs)
        file_funcs[filepath] = funcs
        file_imports[filepath] = _parse_imports(lines)

    func_map = {f.name: f for f in all_funcs}
    graph = build_call_graph(all_funcs)
    reverse_graph = build_reverse_graph(graph)

    # Find test files
    test_files = []
    for filepath in files:
        base = os.path.basename(filepath)
        if base.startswith("test_") or base.endswith("_test.srv"):
            test_files.append(filepath)

    # Determine targets
    targets = []
    if target_function:
        if target_function in func_map:
            targets.append(target_function)
        else:
            return []
    else:
        # Analyze all non-test functions in the specified paths
        for filepath in files:
            base = os.path.basename(filepath)
            if base.startswith("test_") or base.endswith("_test.srv"):
                continue
            for f in file_funcs.get(filepath, []):
                targets.append(f.name)

    reports = []
    for target in targets:
        fi = func_map.get(target)
        if not fi:
            continue
        # I001
        i001_nodes = _engine_i001_direct_deps(target, reverse_graph, func_map)
        # I002
        i002_nodes, cascade_depth = _engine_i002_transitive(target, reverse_graph, func_map)
        # I003
        i003_nodes = _engine_i003_variable_flow(target, all_funcs, func_map)
        # I004
        i004_nodes = _engine_i004_import_ripple(fi.file, file_imports, file_funcs)
        # I005
        coupling_score, coupling_level = _engine_i005_coupling(target, graph, reverse_graph, func_map)
        # I006
        i006_nodes = _engine_i006_cascade(target, graph, reverse_graph, func_map)
        # I007
        affected_names = {n.name for n in i001_nodes + i002_nodes + i003_nodes + i006_nodes}
        affected_names.add(target)
        test_cov, untested = _engine_i007_test_coverage(affected_names, test_files)
        # I008
        risk_score, risk_level = _engine_i008_risk_score(
            len(i001_nodes), len(i002_nodes), len(i003_nodes),
            len(i004_nodes), coupling_score, len(i006_nodes),
            test_cov, cascade_depth,
        )

        all_nodes = i001_nodes + i002_nodes + i003_nodes + i004_nodes + i006_nodes
        # Deduplicate by name
        seen = set()
        unique_nodes = []
        for n in all_nodes:
            if n.name not in seen:
                seen.add(n.name)
                unique_nodes.append(n)

        report = ImpactReport(
            target=target,
            target_file=fi.file,
            nodes=unique_nodes,
            call_graph=graph,
            risk_score=risk_score,
            risk_level=risk_level,
            test_coverage=test_cov,
            cascade_depth=cascade_depth,
            total_affected=len(unique_nodes),
            scan_time=time.time() - start_time,
            files_scanned=len(files),
            total_lines=total_lines,
            engine_results={
                "I001_direct": len(i001_nodes),
                "I002_transitive": len(i002_nodes),
                "I003_variable_flow": len(i003_nodes),
                "I004_import_ripple": len(i004_nodes),
                "I005_coupling": {"score": coupling_score, "level": coupling_level},
                "I006_cascade": len(i006_nodes),
                "I007_test_coverage": {"coverage": round(test_cov, 2), "untested": untested},
                "I008_risk": {"score": risk_score, "level": risk_level},
            },
        )
        reports.append(report)

    return reports


# ── Hotspot / Safe-Change ─────────────────────────────────────────────

def find_hotspots(reports: List[ImpactReport], top: int = 10) -> List[ImpactReport]:
    """Return top N functions with highest blast radius."""
    return sorted(reports, key=lambda r: -r.risk_score)[:top]


def find_safe_changes(reports: List[ImpactReport]) -> List[ImpactReport]:
    """Return functions safe to modify (risk <= 25)."""
    return [r for r in reports if r.risk_score <= 25]


# ── Terminal Output ───────────────────────────────────────────────────

def _risk_badge(level: str) -> str:
    badges = {
        "safe": _C.green("● SAFE"),
        "caution": _C.yellow("◐ CAUTION"),
        "warning": _C.magenta("◑ WARNING"),
        "danger": _C.red("● DANGER"),
    }
    return badges.get(level, level)


def print_report(report: ImpactReport) -> None:
    """Print a single function impact report."""
    print()
    print(_C.bold(f"  ═══ Impact Analysis: {report.target}() ═══"))
    print(f"  File: {_C.cyan(report.target_file)}  │  Risk: {_risk_badge(report.risk_level)} ({report.risk_score}/100)")
    print(f"  Affected: {_C.bold(str(report.total_affected))} functions  │  Cascade depth: {report.cascade_depth}  │  Test coverage: {int(report.test_coverage * 100)}%")
    print()

    if report.nodes:
        # Group by type
        by_type: Dict[str, List[ImpactNode]] = defaultdict(list)
        for n in report.nodes:
            by_type[n.impact_type].append(n)

        type_labels = {
            "direct_caller": "I001 · Direct Callers",
            "transitive": "I002 · Transitive Dependencies",
            "variable_reader": "I003 · Variable Flow",
            "importer": "I004 · Import Ripple",
            "cascade_break": "I006 · Cascade Breakage",
        }
        for itype, label in type_labels.items():
            items = by_type.get(itype, [])
            if items:
                print(f"  {_C.bold(label)} ({len(items)})")
                for n in sorted(items, key=lambda x: -x.risk):
                    risk_color = _C.red if n.risk >= 7 else (_C.yellow if n.risk >= 4 else _C.green)
                    print(f"    {risk_color(f'[{n.risk}]')} {n.name}  {_C.dim(n.description)}")
                    print(f"        {_C.dim(f'{n.file}:{n.line}')}")
                print()

    # Coupling
    coupling = report.engine_results.get("I005_coupling", {})
    if coupling:
        print(f"  {_C.bold('I005 · Structural Coupling')}: {coupling.get('level', 'unknown')} ({coupling.get('score', 0):.2f})")

    # Test gaps
    test_info = report.engine_results.get("I007_test_coverage", {})
    untested = test_info.get("untested", [])
    if untested:
        print(f"\n  {_C.bold('I007 · Test Coverage Gaps')} ({len(untested)} untested)")
        for name in untested[:10]:
            print(f"    {_C.red('✗')} {name}")
        if len(untested) > 10:
            print(f"    {_C.dim(f'  ... and {len(untested) - 10} more')}")
    print()


def print_hotspots(reports: List[ImpactReport]) -> None:
    """Print hotspot summary."""
    hotspots = find_hotspots(reports)
    print(_C.bold("\n  ═══ Impact Hotspots (highest blast radius) ═══\n"))
    print(f"  {'Rank':<6}{'Function':<30}{'Risk':>6}  {'Level':<10}{'Affected':>8}  {'File'}")
    print(f"  {'─' * 6}{'─' * 30}{'─' * 6}  {'─' * 10}{'─' * 8}  {'─' * 20}")
    for i, r in enumerate(hotspots, 1):
        print(f"  {i:<6}{r.target:<30}{r.risk_score:>6}  {r.risk_level:<10}{r.total_affected:>8}  {_C.dim(r.target_file)}")
    print()


def print_safe_changes(reports: List[ImpactReport]) -> None:
    """Print safe-to-modify functions."""
    safe = find_safe_changes(reports)
    print(_C.bold(f"\n  ═══ Safe to Modify ({len(safe)} functions) ═══\n"))
    if not safe:
        print("  No safe-to-modify functions found (all have dependencies).\n")
        return
    for r in sorted(safe, key=lambda x: x.risk_score):
        print(f"  {_C.green('✓')} {r.target}  risk={r.risk_score}  {_C.dim(r.target_file)}")
    print()


def print_graph(report: ImpactReport) -> None:
    """Print ASCII call graph for a function."""
    print(_C.bold(f"\n  ═══ Call Graph: {report.target}() ═══\n"))
    print(f"  {_C.cyan(report.target)}")
    by_depth: Dict[int, List[ImpactNode]] = defaultdict(list)
    for n in report.nodes:
        by_depth[n.depth].append(n)
    for depth in sorted(by_depth.keys()):
        items = by_depth[depth]
        for i, n in enumerate(items):
            prefix = "  " + "│   " * (depth - 1)
            connector = "├── " if i < len(items) - 1 else "└── "
            risk_color = _C.red if n.risk >= 7 else (_C.yellow if n.risk >= 4 else _C.green)
            print(f"{prefix}{connector}{risk_color(n.name)} {_C.dim(f'[{n.impact_type}]')}")
    print()


# ── JSON Output ───────────────────────────────────────────────────────

def to_json(reports: List[ImpactReport]) -> dict:
    """Convert reports to JSON-serialisable dict."""
    return {
        "version": __version__,
        "timestamp": datetime.now().isoformat(),
        "reports": [
            {
                "target": r.target,
                "target_file": r.target_file,
                "risk_score": r.risk_score,
                "risk_level": r.risk_level,
                "test_coverage": round(r.test_coverage, 2),
                "cascade_depth": r.cascade_depth,
                "total_affected": r.total_affected,
                "scan_time": round(r.scan_time, 3),
                "files_scanned": r.files_scanned,
                "total_lines": r.total_lines,
                "engine_results": r.engine_results,
                "nodes": [
                    {
                        "name": n.name, "file": n.file, "line": n.line,
                        "impact_type": n.impact_type, "depth": n.depth,
                        "risk": n.risk, "description": n.description,
                    }
                    for n in r.nodes
                ],
            }
            for r in reports
        ],
    }


# ── HTML Dashboard ────────────────────────────────────────────────────

def _html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def generate_html(reports: List[ImpactReport], output_path: str) -> None:
    """Generate interactive HTML dashboard."""
    # Aggregate stats
    total_funcs = len(reports)
    avg_risk = sum(r.risk_score for r in reports) / max(1, total_funcs)
    danger_count = sum(1 for r in reports if r.risk_level == "danger")
    warning_count = sum(1 for r in reports if r.risk_level == "warning")
    caution_count = sum(1 for r in reports if r.risk_level == "caution")
    safe_count = sum(1 for r in reports if r.risk_level == "safe")

    hotspots = find_hotspots(reports, 20)

    # Build rows
    hotspot_rows = ""
    for i, r in enumerate(hotspots, 1):
        level_class = r.risk_level
        hotspot_rows += f"""<tr class="{level_class}">
            <td>{i}</td><td>{_html_escape(r.target)}</td>
            <td>{r.risk_score}</td><td><span class="badge {level_class}">{r.risk_level.upper()}</span></td>
            <td>{r.total_affected}</td><td>{r.cascade_depth}</td>
            <td>{int(r.test_coverage * 100)}%</td>
            <td class="dim">{_html_escape(r.target_file)}</td></tr>\n"""

    # Risk distribution for chart
    risk_dist = [0] * 10
    for r in reports:
        bucket = min(9, r.risk_score // 10)
        risk_dist[bucket] += 1
    max_bar = max(risk_dist) if risk_dist else 1

    bars_html = ""
    for i, count in enumerate(risk_dist):
        pct = (count / max_bar * 100) if max_bar > 0 else 0
        label = f"{i * 10}-{i * 10 + 9}"
        color = "#22c55e" if i < 3 else ("#eab308" if i < 5 else ("#f97316" if i < 8 else "#ef4444"))
        bars_html += f'''<div class="bar-group"><div class="bar" style="height:{pct}%;background:{color}"
            title="{count} functions"></div><div class="bar-label">{label}</div></div>\n'''

    html = f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>sauravimpact — Change Impact Dashboard</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;padding:24px}}
h1{{font-size:28px;margin-bottom:8px;color:#f8fafc}}
.subtitle{{color:#94a3b8;margin-bottom:24px;font-size:14px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:32px}}
.card{{background:#1e293b;border-radius:12px;padding:20px;text-align:center}}
.card .value{{font-size:32px;font-weight:700}}
.card .label{{color:#94a3b8;font-size:13px;margin-top:4px}}
.card.danger .value{{color:#ef4444}}
.card.warning .value{{color:#f97316}}
.card.caution .value{{color:#eab308}}
.card.safe .value{{color:#22c55e}}
.gauge-container{{display:flex;justify-content:center;margin:24px 0}}
.gauge{{width:200px;height:100px;position:relative}}
.gauge-arc{{fill:none;stroke-width:20;stroke-linecap:round}}
.gauge-bg{{stroke:#334155}}
.gauge-fill{{transition:stroke-dashoffset 1s ease}}
.gauge-value{{position:absolute;bottom:0;width:100%;text-align:center;font-size:36px;font-weight:700}}
.gauge-label{{text-align:center;color:#94a3b8;font-size:13px;margin-top:4px}}
.section{{margin-bottom:32px}}
.section h2{{font-size:20px;margin-bottom:16px;color:#f8fafc}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;padding:10px 12px;background:#1e293b;color:#94a3b8;font-weight:600;border-bottom:1px solid #334155}}
td{{padding:10px 12px;border-bottom:1px solid #1e293b}}
tr:hover td{{background:#1e293b}}
.badge{{padding:2px 8px;border-radius:6px;font-size:11px;font-weight:600;text-transform:uppercase}}
.badge.safe{{background:#166534;color:#86efac}}
.badge.caution{{background:#854d0e;color:#fde047}}
.badge.warning{{background:#9a3412;color:#fdba74}}
.badge.danger{{background:#991b1b;color:#fca5a5}}
.dim{{color:#64748b}}
.chart{{display:flex;align-items:flex-end;gap:8px;height:120px;padding:16px 0}}
.bar-group{{display:flex;flex-direction:column;align-items:center;flex:1}}
.bar{{width:100%;min-height:4px;border-radius:4px 4px 0 0;transition:height .5s ease}}
.bar-label{{font-size:10px;color:#64748b;margin-top:4px}}
.filter-bar{{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}}
.filter-btn{{padding:6px 14px;border-radius:8px;border:1px solid #334155;background:#1e293b;color:#e2e8f0;cursor:pointer;font-size:12px}}
.filter-btn:hover,.filter-btn.active{{background:#334155;border-color:#64748b}}
</style></head><body>

<h1>⚡ sauravimpact — Change Impact Dashboard</h1>
<p class="subtitle">Analyzed {total_funcs} functions across {reports[0].files_scanned if reports else 0} files
({reports[0].total_lines if reports else 0} lines) • Generated {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>

<div class="cards">
  <div class="card"><div class="value">{total_funcs}</div><div class="label">Functions Analyzed</div></div>
  <div class="card {'danger' if avg_risk > 50 else 'caution' if avg_risk > 25 else 'safe'}"><div class="value">{avg_risk:.0f}</div><div class="label">Avg Risk Score</div></div>
  <div class="card danger"><div class="value">{danger_count}</div><div class="label">Danger</div></div>
  <div class="card warning"><div class="value">{warning_count}</div><div class="label">Warning</div></div>
  <div class="card caution"><div class="value">{caution_count}</div><div class="label">Caution</div></div>
  <div class="card safe"><div class="value">{safe_count}</div><div class="label">Safe</div></div>
</div>

<div class="section">
  <h2>📊 Risk Distribution</h2>
  <div class="chart">{bars_html}</div>
</div>

<div class="section">
  <h2>🔥 Impact Hotspots</h2>
  <div class="filter-bar">
    <button class="filter-btn active" onclick="filterTable('all')">All</button>
    <button class="filter-btn" onclick="filterTable('danger')">Danger</button>
    <button class="filter-btn" onclick="filterTable('warning')">Warning</button>
    <button class="filter-btn" onclick="filterTable('caution')">Caution</button>
    <button class="filter-btn" onclick="filterTable('safe')">Safe</button>
  </div>
  <table id="hotspots">
    <thead><tr><th>#</th><th>Function</th><th>Risk</th><th>Level</th><th>Affected</th><th>Depth</th><th>Coverage</th><th>File</th></tr></thead>
    <tbody>{hotspot_rows}</tbody>
  </table>
</div>

<script>
function filterTable(level){{
  document.querySelectorAll('.filter-btn').forEach(b=>b.classList.remove('active'));
  event.target.classList.add('active');
  document.querySelectorAll('#hotspots tbody tr').forEach(tr=>{{
    tr.style.display=(level==='all'||tr.classList.contains(level))?'':'none';
  }});
}}
</script>

<div style="text-align:center;color:#475569;margin-top:40px;font-size:12px">
  Generated by sauravimpact v{__version__} • {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
</div>
</body></html>'''

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(html)


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="sauravimpact",
        description="Autonomous Change Impact Analyzer for sauravcode",
    )
    parser.add_argument("paths", nargs="*", default=["."],
                        help="Files or directories to scan")
    parser.add_argument("--function", "-f", metavar="NAME",
                        help="Analyze a specific function")
    parser.add_argument("--recursive", "-r", action="store_true",
                        help="Scan subdirectories")
    parser.add_argument("--html", metavar="FILE",
                        help="Generate interactive HTML dashboard")
    parser.add_argument("--json", action="store_true",
                        help="JSON output")
    parser.add_argument("--graph", action="store_true",
                        help="Show ASCII call graph")
    parser.add_argument("--hotspots", action="store_true",
                        help="Show highest blast-radius functions")
    parser.add_argument("--safe-changes", action="store_true",
                        help="Show safe-to-modify functions")
    parser.add_argument("--version", action="version",
                        version=f"sauravimpact {__version__}")

    args = parser.parse_args()

    reports = analyze(args.paths, target_function=args.function, recursive=args.recursive)

    if not reports:
        print(_C.yellow("  No functions found to analyze."))
        return

    if args.json:
        print(json.dumps(to_json(reports), indent=2))
        return

    if args.html:
        generate_html(reports, args.html)
        print(_C.green(f"  ✓ HTML dashboard written to {args.html}"))
        return

    if args.hotspots:
        print_hotspots(reports)
        return

    if args.safe_changes:
        print_safe_changes(reports)
        return

    if args.graph and len(reports) == 1:
        print_graph(reports[0])
        return

    # Default: print all reports (or just one if --function specified)
    if args.function:
        print_report(reports[0])
    else:
        # Summary mode for multiple functions
        print(_C.bold(f"\n  ═══ Change Impact Analysis ═══"))
        print(f"  Scanned {reports[0].files_scanned} files ({reports[0].total_lines} lines)\n")
        print_hotspots(reports)


if __name__ == "__main__":
    main()
