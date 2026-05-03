#!/usr/bin/env python3
"""sauravarchitect — Autonomous Code Architecture Analyzer for sauravcode.

Maps module structure, coupling/cohesion patterns, layering violations,
and architectural anti-patterns across .srv projects.  Generates an
interactive HTML dashboard with dependency graphs, heatmaps, and
actionable restructuring recommendations.

Analysis engines (7):
    A001  Module Dependency Graph      Import graph, cycle detection (Tarjan SCC)
    A002  Coupling Analyzer            Afferent/efferent coupling, instability metric
    A003  Cohesion Scorer              LCOM4-style intra-module cohesion
    A004  Layer Violation Detector     Infer layers, detect upward dependency violations
    A005  Anti-Pattern Scanner         8 architectural anti-pattern categories
    A006  Architecture Health Scorer   Composite 0-100 weighted score
    A007  Insight Generator            Autonomous restructuring recommendations

Usage:
    python sauravarchitect.py                         # Analyze current directory
    python sauravarchitect.py path/to/project         # Analyze specific directory
    python sauravarchitect.py path --html report.html # Interactive HTML dashboard
    python sauravarchitect.py path --json             # JSON output
    python sauravarchitect.py path --recursive        # Deep scan
    python sauravarchitect.py path --graph            # ASCII dependency graph
    python sauravarchitect.py path --hotspots         # Highest coupling modules
    python sauravarchitect.py path --layers           # Show layer assignments
"""

import sys
import os
import re
import json
import math
import argparse
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Set, Tuple, Any, Optional
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
IMPORT_RE = re.compile(r'^import\s+"([^"]+)"')
ASSIGN_RE = re.compile(r"^\s*(\w+)\s*=\s*")
IDENT_RE = re.compile(r"\b([a-zA-Z_]\w*)\b")

# ── Data Structures ──────────────────────────────────────────────────

@dataclass
class FunctionInfo:
    """Metadata for a single function parsed from a .srv module.

    Tracks variable reads/writes and outgoing calls for cohesion analysis.
    """

    name: str
    start_line: int
    end_line: int
    variables_written: Set[str] = field(default_factory=set)
    variables_read: Set[str] = field(default_factory=set)
    calls: Set[str] = field(default_factory=set)

@dataclass
class ModuleInfo:
    """Aggregated info for one .srv module — imports, functions, and line counts."""

    path: str
    name: str
    imports: List[str] = field(default_factory=list)
    functions: List[FunctionInfo] = field(default_factory=list)
    lines: int = 0
    code_lines: int = 0

@dataclass
class CouplingResult:
    """Afferent/efferent coupling and instability metric for a module.

    Instability = Ce / (Ca + Ce); ranges from 0 (maximally stable) to
    1 (maximally unstable).
    """

    module: str
    afferent: int = 0   # incoming dependencies (Ca)
    efferent: int = 0   # outgoing dependencies (Ce)
    instability: float = 0.0  # Ce / (Ca + Ce)

@dataclass
class CohesionResult:
    """LCOM4-style cohesion result for a module.

    ``connected_components`` counts disjoint groups of functions sharing
    variables; ``score`` inverts LCOM4 to a 0–100 readability scale.
    """

    module: str
    functions: int = 0
    connected_components: int = 0
    lcom4: float = 0.0  # 0 = perfect cohesion, higher = worse
    score: float = 100.0  # 0-100 inverted for readability

@dataclass
class LayerAssignment:
    """Inferred architectural layer (util/core/app/demo) for a module."""

    module: str
    layer: str  # util, core, app, demo
    confidence: float = 0.0

@dataclass
class AntiPattern:
    """A detected architectural anti-pattern with severity and remediation advice."""

    code: str
    name: str
    severity: str  # critical, warning, info
    module: str
    description: str
    suggestion: str

@dataclass
class ArchitectureReport:
    """Top-level report aggregating all architecture analysis results."""

    timestamp: str = ""
    directory: str = ""
    total_modules: int = 0
    total_functions: int = 0
    total_lines: int = 0
    modules: List[dict] = field(default_factory=list)
    dependency_graph: Dict[str, List[str]] = field(default_factory=dict)
    cycles: List[List[str]] = field(default_factory=list)
    coupling: List[dict] = field(default_factory=list)
    cohesion: List[dict] = field(default_factory=list)
    layers: List[dict] = field(default_factory=list)
    layer_violations: List[dict] = field(default_factory=list)
    anti_patterns: List[dict] = field(default_factory=list)
    health_score: float = 0.0
    sub_scores: Dict[str, float] = field(default_factory=dict)
    insights: List[dict] = field(default_factory=list)


# ── Parsing ──────────────────────────────────────────────────────────

KEYWORDS = {
    "if", "else", "elif", "while", "for", "foreach", "function", "fn",
    "return", "import", "try", "catch", "throw", "match", "case",
    "break", "continue", "true", "false", "null", "and", "or", "not",
    "in", "print", "input", "len", "append", "pop", "push", "set",
    "get", "delete", "has", "keys", "values", "type", "str", "int",
    "float", "bool", "list", "dict", "range", "map", "filter",
}


def parse_module(path: str) -> ModuleInfo:
    """Parse a .srv file into a ModuleInfo structure."""
    name = os.path.splitext(os.path.basename(path))[0]
    mod = ModuleInfo(path=path, name=name)

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except (IOError, OSError):
        return mod

    mod.lines = len(lines)
    mod.code_lines = sum(
        1 for ln in lines
        if ln.strip() and not ln.strip().startswith("#") and not ln.strip().startswith("//")
    )

    # Extract imports
    for ln in lines:
        m = IMPORT_RE.match(ln.strip())
        if m:
            imp = m.group(1)
            # Normalize: remove .srv extension if present
            if imp.endswith(".srv"):
                imp = imp[:-4]
            mod.imports.append(imp)

    # Extract functions with their variable usage
    current_func: Optional[FunctionInfo] = None
    func_indent = 0
    all_func_names: Set[str] = set()

    # First pass: collect all function names
    for ln in lines:
        fm = FUNC_DEF_RE.match(ln)
        if fm:
            all_func_names.add(fm.group(2))

    # Second pass: detailed extraction
    for i, ln in enumerate(lines):
        fm = FUNC_DEF_RE.match(ln)
        if fm:
            if current_func is not None:
                current_func.end_line = i - 1
                mod.functions.append(current_func)
            indent = len(fm.group(1).replace("\t", "    "))
            fname = fm.group(2)
            current_func = FunctionInfo(name=fname, start_line=i, end_line=i)
            func_indent = indent
            # Parse parameters as written variables
            params = fm.group(3).strip()
            if params:
                for p in params.split():
                    p = p.strip(",")
                    if p and p.isidentifier():
                        current_func.variables_written.add(p)
            continue

        if current_func is not None:
            stripped = ln.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("//"):
                continue

            line_indent = len(ln) - len(ln.lstrip())
            line_indent = sum(4 if c == "\t" else 1 for c in ln[: len(ln) - len(ln.lstrip())])

            # Check if we've exited the function
            if stripped and line_indent <= func_indent and not FUNC_DEF_RE.match(ln):
                # Could be still in function if it's a continuation
                if i > current_func.start_line + 1:
                    current_func.end_line = i - 1
                    mod.functions.append(current_func)
                    current_func = None
                    continue

            # Track variable assignments
            am = ASSIGN_RE.match(ln)
            if am:
                var = am.group(1)
                if var not in KEYWORDS:
                    current_func.variables_written.add(var)

            # Track variable reads and function calls
            for ident_match in IDENT_RE.finditer(stripped):
                ident = ident_match.group(1)
                if ident in KEYWORDS:
                    continue
                if ident in all_func_names and ident != current_func.name:
                    current_func.calls.add(ident)
                elif ident not in current_func.variables_written:
                    current_func.variables_read.add(ident)

    if current_func is not None:
        current_func.end_line = len(lines) - 1
        mod.functions.append(current_func)

    return mod


# ── A001: Module Dependency Graph (Tarjan SCC) ───────────────────────

def build_dependency_graph(modules: List[ModuleInfo]) -> Dict[str, List[str]]:
    """Build directed dependency graph from import statements."""
    names = {m.name for m in modules}
    graph: Dict[str, List[str]] = {m.name: [] for m in modules}
    for m in modules:
        for imp in m.imports:
            target = os.path.splitext(os.path.basename(imp))[0]
            if target in names:
                graph[m.name].append(target)
    return graph


def tarjan_scc(graph: Dict[str, List[str]]) -> List[List[str]]:
    """Tarjan's strongly connected components algorithm."""
    index_counter = [0]
    stack: List[str] = []
    lowlink: Dict[str, int] = {}
    index: Dict[str, int] = {}
    on_stack: Dict[str, bool] = {}
    sccs: List[List[str]] = []

    def strongconnect(v: str):
        index[v] = index_counter[0]
        lowlink[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack[v] = True

        for w in graph.get(v, []):
            if w not in index:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif on_stack.get(w, False):
                lowlink[v] = min(lowlink[v], index[w])

        if lowlink[v] == index[v]:
            component: List[str] = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                component.append(w)
                if w == v:
                    break
            sccs.append(component)

    for v in graph:
        if v not in index:
            strongconnect(v)

    return sccs


def detect_cycles(graph: Dict[str, List[str]]) -> List[List[str]]:
    """Return only SCCs with more than one node (actual cycles)."""
    sccs = tarjan_scc(graph)
    cycles = [scc for scc in sccs if len(scc) > 1]
    # Also detect self-loops
    for node, deps in graph.items():
        if node in deps:
            cycles.append([node])
    return cycles


# ── A002: Coupling Analyzer ──────────────────────────────────────────

def analyze_coupling(
    modules: List[ModuleInfo], graph: Dict[str, List[str]]
) -> List[CouplingResult]:
    """Compute afferent/efferent coupling and instability for each module."""
    names = {m.name for m in modules}
    results: List[CouplingResult] = []

    # Afferent: who depends on me
    afferent: Dict[str, int] = defaultdict(int)
    for src, deps in graph.items():
        for dep in deps:
            if dep in names:
                afferent[dep] += 1

    for m in modules:
        ca = afferent.get(m.name, 0)
        ce = len([d for d in graph.get(m.name, []) if d in names])
        total = ca + ce
        instability = ce / total if total > 0 else 0.0
        results.append(CouplingResult(
            module=m.name, afferent=ca, efferent=ce, instability=round(instability, 3)
        ))

    return results


# ── A003: Cohesion Scorer ────────────────────────────────────────────

def analyze_cohesion(modules: List[ModuleInfo]) -> List[CohesionResult]:
    """LCOM4-style cohesion: connected components in function-variable graph."""
    results: List[CohesionResult] = []

    for mod in modules:
        funcs = mod.functions
        if len(funcs) <= 1:
            results.append(CohesionResult(
                module=mod.name, functions=len(funcs),
                connected_components=max(1, len(funcs)),
                lcom4=0.0, score=100.0
            ))
            continue

        # Build adjacency: two functions are connected if they share variables
        adj: Dict[str, Set[str]] = {f.name: set() for f in funcs}
        for i, f1 in enumerate(funcs):
            vars1 = f1.variables_written | f1.variables_read
            for j, f2 in enumerate(funcs):
                if i >= j:
                    continue
                vars2 = f2.variables_written | f2.variables_read
                shared = vars1 & vars2
                if shared:
                    adj[f1.name].add(f2.name)
                    adj[f2.name].add(f1.name)

        # Also connect functions that call each other
        func_names = {f.name for f in funcs}
        for f in funcs:
            for call in f.calls:
                if call in func_names and call != f.name:
                    adj[f.name].add(call)
                    adj[call].add(f.name)

        # Count connected components (BFS)
        visited: Set[str] = set()
        components = 0
        for fname in adj:
            if fname in visited:
                continue
            components += 1
            queue = [fname]
            while queue:
                node = queue.pop(0)
                if node in visited:
                    continue
                visited.add(node)
                for neighbor in adj.get(node, set()):
                    if neighbor not in visited:
                        queue.append(neighbor)

        lcom4 = max(0, components - 1)
        # Score: 100 for 1 component, decreases as components increase
        max_components = len(funcs)
        score = 100.0 * (1.0 - lcom4 / max(max_components, 1))
        score = max(0.0, min(100.0, score))

        results.append(CohesionResult(
            module=mod.name, functions=len(funcs),
            connected_components=components,
            lcom4=lcom4, score=round(score, 1)
        ))

    return results


# ── A004: Layer Violation Detector ───────────────────────────────────

LAYER_ORDER = {"util": 0, "core": 1, "app": 2, "demo": 3}


def infer_layers(
    modules: List[ModuleInfo], graph: Dict[str, List[str]]
) -> List[LayerAssignment]:
    """Heuristic layer inference based on naming and dependency patterns."""
    results: List[LayerAssignment] = []
    names = {m.name for m in modules}

    # Count how many others depend on each module
    dependents: Dict[str, int] = defaultdict(int)
    for src, deps in graph.items():
        for dep in deps:
            if dep in names:
                dependents[dep] += 1

    for mod in modules:
        n = mod.name.lower()
        confidence = 0.8

        # Naming heuristics
        if any(kw in n for kw in ("util", "helper", "common", "shared", "lib", "base")):
            layer = "util"
            confidence = 0.9
        elif any(kw in n for kw in ("demo", "test", "example", "sample", "bench")):
            layer = "demo"
            confidence = 0.9
        elif any(kw in n for kw in ("main", "app", "cli", "run", "entry")):
            layer = "app"
            confidence = 0.85
        else:
            # Dependency-based heuristic
            efferent = len(graph.get(mod.name, []))
            afferent = dependents.get(mod.name, 0)

            if afferent > 2 and efferent == 0:
                layer = "util"
                confidence = 0.7
            elif efferent > 3 and afferent == 0:
                layer = "app"
                confidence = 0.7
            elif afferent > efferent:
                layer = "core"
                confidence = 0.6
            else:
                layer = "core"
                confidence = 0.5

        results.append(LayerAssignment(
            module=mod.name, layer=layer, confidence=round(confidence, 2)
        ))

    return results


def detect_layer_violations(
    layers: List[LayerAssignment], graph: Dict[str, List[str]]
) -> List[dict]:
    """Detect upward dependency violations (lower layers depending on higher)."""
    layer_map = {la.module: la.layer for la in layers}
    violations: List[dict] = []

    for src, deps in graph.items():
        src_layer = layer_map.get(src, "core")
        src_order = LAYER_ORDER.get(src_layer, 1)
        for dep in deps:
            dep_layer = layer_map.get(dep, "core")
            dep_order = LAYER_ORDER.get(dep_layer, 1)
            if dep_order > src_order:
                violations.append({
                    "source": src,
                    "source_layer": src_layer,
                    "target": dep,
                    "target_layer": dep_layer,
                    "description": f"{src} ({src_layer}) depends on {dep} ({dep_layer}) — upward dependency",
                })

    return violations


# ── A005: Anti-Pattern Scanner ───────────────────────────────────────

def scan_anti_patterns(
    modules: List[ModuleInfo],
    graph: Dict[str, List[str]],
    coupling: List[CouplingResult],
    cohesion: List[CohesionResult],
    cycles: List[List[str]],
    layers: List[LayerAssignment],
) -> List[AntiPattern]:
    """Detect 8 architectural anti-patterns."""
    patterns: List[AntiPattern] = []
    names = {m.name for m in modules}
    mod_map = {m.name: m for m in modules}
    coupling_map = {c.module: c for c in coupling}
    cohesion_map = {c.module: c for c in cohesion}
    layer_map = {la.module: la.layer for la in layers}

    # 1. God Module — too many functions + high coupling
    for m in modules:
        if len(m.functions) > 15 or (len(m.functions) > 10 and m.code_lines > 300):
            c = coupling_map.get(m.name)
            patterns.append(AntiPattern(
                code="AP01", name="God Module", severity="critical",
                module=m.name,
                description=f"{m.name} has {len(m.functions)} functions and {m.code_lines} code lines",
                suggestion=f"Split {m.name} into smaller, focused modules",
            ))

    # 2. Orphan Module — no imports and not imported by anyone
    for m in modules:
        c = coupling_map.get(m.name)
        if c and c.afferent == 0 and c.efferent == 0 and len(modules) > 1:
            patterns.append(AntiPattern(
                code="AP02", name="Orphan Module", severity="info",
                module=m.name,
                description=f"{m.name} has no connections to other modules",
                suggestion=f"Consider integrating {m.name} or removing if unused",
            ))

    # 3. Circular Dependency
    for cycle in cycles:
        if len(cycle) > 1:
            cycle_str = " → ".join(cycle + [cycle[0]])
            patterns.append(AntiPattern(
                code="AP03", name="Circular Dependency", severity="critical",
                module=cycle[0],
                description=f"Cycle detected: {cycle_str}",
                suggestion="Break cycle by extracting shared code into a common module",
            ))

    # 4. Hub-and-Spoke — one module with extremely high afferent coupling
    if len(modules) > 3:
        for c in coupling:
            if c.afferent > len(modules) * 0.6:
                patterns.append(AntiPattern(
                    code="AP04", name="Hub-and-Spoke", severity="warning",
                    module=c.module,
                    description=f"{c.module} is depended on by {c.afferent} of {len(modules)} modules",
                    suggestion=f"Consider splitting {c.module} interface to reduce central dependency",
                ))

    # 5. Shotgun Surgery — changing one module likely affects many others
    for c in coupling:
        if c.afferent > 4 and c.efferent > 2:
            patterns.append(AntiPattern(
                code="AP05", name="Shotgun Surgery Risk", severity="warning",
                module=c.module,
                description=f"{c.module} has high bidirectional coupling (Ca={c.afferent}, Ce={c.efferent})",
                suggestion=f"Introduce interfaces/abstractions to reduce coupling on {c.module}",
            ))

    # 6. Feature Envy — function calls predominantly go to one other module
    for m in modules:
        external_calls: Dict[str, int] = defaultdict(int)
        func_names_in_mod = {f.name for f in m.functions}
        for func in m.functions:
            for call in func.calls:
                if call not in func_names_in_mod:
                    # Try to find which module owns this function
                    for other in modules:
                        if other.name == m.name:
                            continue
                        if any(f.name == call for f in other.functions):
                            external_calls[other.name] += 1

        for target, count in external_calls.items():
            if count > 3:
                patterns.append(AntiPattern(
                    code="AP06", name="Feature Envy", severity="info",
                    module=m.name,
                    description=f"{m.name} calls {count} functions from {target}",
                    suggestion=f"Consider moving related functions from {m.name} to {target}",
                ))

    # 7. Layer Skip — app layer directly using util layer (skipping core)
    for la in layers:
        if la.layer == "app":
            for dep in graph.get(la.module, []):
                dep_layer = layer_map.get(dep, "core")
                if dep_layer == "util":
                    # Check if there's a core module that wraps this
                    patterns.append(AntiPattern(
                        code="AP07", name="Layer Skip", severity="info",
                        module=la.module,
                        description=f"{la.module} (app) directly depends on {dep} (util), skipping core",
                        suggestion=f"Route through a core module for better separation",
                    ))

    # 8. Spaghetti Coupling — high total coupling across the project
    if len(modules) > 3:
        total_edges = sum(len(deps) for deps in graph.values())
        max_edges = len(modules) * (len(modules) - 1)
        density = total_edges / max_edges if max_edges > 0 else 0
        if density > 0.4:
            patterns.append(AntiPattern(
                code="AP08", name="Spaghetti Coupling", severity="critical",
                module="(project-wide)",
                description=f"Dependency density is {density:.1%} ({total_edges}/{max_edges} possible edges)",
                suggestion="Introduce clearer module boundaries and dependency rules",
            ))

    return patterns


# ── A006: Architecture Health Scorer ─────────────────────────────────

def compute_health_score(
    modules: List[ModuleInfo],
    coupling: List[CouplingResult],
    cohesion: List[CohesionResult],
    cycles: List[List[str]],
    layer_violations: List[dict],
    anti_patterns: List[AntiPattern],
) -> Tuple[float, Dict[str, float]]:
    """Composite 0-100 architecture health score."""
    sub_scores: Dict[str, float] = {}

    # Coupling score (25%): average instability near 0.5 is ideal (balanced)
    if coupling:
        avg_inst = sum(c.instability for c in coupling) / len(coupling)
        # Ideal is 0.3-0.7 range; penalize extremes
        coupling_score = 100.0 * (1.0 - abs(avg_inst - 0.5) * 1.5)
        coupling_score = max(0.0, min(100.0, coupling_score))
        # Penalize high max coupling
        max_efferent = max(c.efferent for c in coupling) if coupling else 0
        if max_efferent > 8:
            coupling_score *= 0.8
    else:
        coupling_score = 100.0
    sub_scores["coupling"] = round(coupling_score, 1)

    # Cohesion score (20%): average cohesion score
    if cohesion:
        cohesion_score = sum(c.score for c in cohesion) / len(cohesion)
    else:
        cohesion_score = 100.0
    sub_scores["cohesion"] = round(cohesion_score, 1)

    # Layering score (20%): penalize violations
    if modules:
        violation_ratio = len(layer_violations) / max(len(modules), 1)
        layering_score = 100.0 * max(0, 1.0 - violation_ratio * 2)
    else:
        layering_score = 100.0
    # Penalize cycles heavily
    if cycles:
        cycle_penalty = min(50, len(cycles) * 15)
        layering_score = max(0, layering_score - cycle_penalty)
    sub_scores["layering"] = round(layering_score, 1)

    # Anti-pattern score (25%): penalize by severity
    severity_weights = {"critical": 15, "warning": 8, "info": 3}
    total_penalty = sum(severity_weights.get(ap.severity, 5) for ap in anti_patterns)
    ap_score = max(0, 100.0 - total_penalty)
    sub_scores["anti_patterns"] = round(ap_score, 1)

    # Modularity score (10%): file count vs function distribution
    if modules:
        func_counts = [len(m.functions) for m in modules]
        if func_counts:
            avg_funcs = sum(func_counts) / len(func_counts)
            variance = sum((f - avg_funcs) ** 2 for f in func_counts) / len(func_counts)
            std_dev = math.sqrt(variance)
            # Lower std_dev relative to mean = better distribution
            cv = std_dev / avg_funcs if avg_funcs > 0 else 0
            modularity_score = 100.0 * max(0, 1.0 - cv * 0.5)
        else:
            modularity_score = 100.0
    else:
        modularity_score = 100.0
    sub_scores["modularity"] = round(modularity_score, 1)

    # Weighted composite
    weights = {
        "coupling": 0.25,
        "cohesion": 0.20,
        "layering": 0.20,
        "anti_patterns": 0.25,
        "modularity": 0.10,
    }
    health = sum(sub_scores[k] * weights[k] for k in weights)
    return round(max(0.0, min(100.0, health)), 1), sub_scores


# ── A007: Insight Generator ──────────────────────────────────────────

def generate_insights(
    modules: List[ModuleInfo],
    graph: Dict[str, List[str]],
    coupling: List[CouplingResult],
    cohesion: List[CohesionResult],
    cycles: List[List[str]],
    layers: List[LayerAssignment],
    layer_violations: List[dict],
    anti_patterns: List[AntiPattern],
    health_score: float,
    sub_scores: Dict[str, float],
) -> List[dict]:
    """Generate autonomous restructuring recommendations."""
    insights: List[dict] = []

    # Health-based insights
    if health_score >= 85:
        insights.append({
            "type": "positive",
            "title": "Healthy Architecture",
            "description": "The codebase has a well-structured architecture with good separation of concerns.",
        })
    elif health_score < 50:
        insights.append({
            "type": "critical",
            "title": "Architecture Needs Attention",
            "description": "Multiple structural issues detected. Prioritize breaking cycles and reducing coupling.",
        })

    # Cycle-specific insights
    if cycles:
        total_in_cycles = len(set(m for cycle in cycles for m in cycle))
        insights.append({
            "type": "warning",
            "title": f"{len(cycles)} Dependency Cycle(s) Found",
            "description": f"{total_in_cycles} modules involved in circular dependencies. Extract shared interfaces to break cycles.",
        })

    # Coupling insights
    high_coupling = [c for c in coupling if c.afferent > 3]
    if high_coupling:
        top = sorted(high_coupling, key=lambda c: c.afferent, reverse=True)[:3]
        names = ", ".join(c.module for c in top)
        insights.append({
            "type": "info",
            "title": "High-Dependency Modules",
            "description": f"Modules with most dependents: {names}. Changes here have wide blast radius.",
        })

    # Cohesion insights
    low_cohesion = [c for c in cohesion if c.score < 50 and c.functions > 2]
    if low_cohesion:
        names = ", ".join(c.module for c in low_cohesion[:3])
        insights.append({
            "type": "warning",
            "title": "Low Cohesion Detected",
            "description": f"Modules with dispersed responsibilities: {names}. Consider splitting into focused modules.",
        })

    # Layer violation insights
    if layer_violations:
        insights.append({
            "type": "warning",
            "title": f"{len(layer_violations)} Layer Violation(s)",
            "description": "Lower-layer modules depend on higher-layer modules. Invert these dependencies.",
        })

    # Anti-pattern summary
    critical_aps = [ap for ap in anti_patterns if ap.severity == "critical"]
    if critical_aps:
        insights.append({
            "type": "critical",
            "title": f"{len(critical_aps)} Critical Anti-Pattern(s)",
            "description": "Address critical patterns first: " + ", ".join(
                set(ap.name for ap in critical_aps)
            ),
        })

    # Sub-score specific recommendations
    weakest = min(sub_scores, key=sub_scores.get) if sub_scores else None
    if weakest and sub_scores.get(weakest, 100) < 60:
        recommendations = {
            "coupling": "Reduce module interdependencies by introducing facade patterns.",
            "cohesion": "Group related functions into focused modules.",
            "layering": "Enforce dependency direction: util ← core ← app ← demo.",
            "anti_patterns": "Address detected anti-patterns starting with critical severity.",
            "modularity": "Balance function distribution across modules more evenly.",
        }
        insights.append({
            "type": "recommendation",
            "title": f"Focus Area: {weakest.replace('_', ' ').title()}",
            "description": recommendations.get(weakest, "Improve this dimension."),
        })

    # Positive: orphan-free
    orphans = [m for m in modules if not graph.get(m.name, []) and
               not any(m.name in deps for deps in graph.values())]
    if not orphans and len(modules) > 2:
        insights.append({
            "type": "positive",
            "title": "No Orphan Modules",
            "description": "All modules are connected in the dependency graph.",
        })

    return insights


# ── Full Analysis ────────────────────────────────────────────────────

def analyze(paths, *, recursive: bool = False) -> ArchitectureReport:
    """Run all 7 analysis engines and produce a complete report."""
    if isinstance(paths, str):
        paths = [paths]

    files = _find_srv_files(paths, recursive=recursive)
    modules = [parse_module(f) for f in files]

    report = ArchitectureReport(
        timestamp=datetime.now().isoformat(),
        directory=paths[0] if paths else ".",
        total_modules=len(modules),
        total_functions=sum(len(m.functions) for m in modules),
        total_lines=sum(m.lines for m in modules),
    )

    report.modules = [
        {
            "name": m.name,
            "path": m.path,
            "lines": m.lines,
            "code_lines": m.code_lines,
            "functions": len(m.functions),
            "imports": m.imports,
        }
        for m in modules
    ]

    # A001: Dependency Graph + Cycles
    graph = build_dependency_graph(modules)
    report.dependency_graph = graph
    cycles = detect_cycles(graph)
    report.cycles = cycles

    # A002: Coupling
    coupling_results = analyze_coupling(modules, graph)
    report.coupling = [asdict(c) for c in coupling_results]

    # A003: Cohesion
    cohesion_results = analyze_cohesion(modules)
    report.cohesion = [asdict(c) for c in cohesion_results]

    # A004: Layers
    layer_results = infer_layers(modules, graph)
    report.layers = [asdict(la) for la in layer_results]
    violations = detect_layer_violations(layer_results, graph)
    report.layer_violations = violations

    # A005: Anti-Patterns
    ap_results = scan_anti_patterns(
        modules, graph, coupling_results, cohesion_results, cycles, layer_results
    )
    report.anti_patterns = [asdict(ap) for ap in ap_results]

    # A006: Health Score
    health, sub_scores = compute_health_score(
        modules, coupling_results, cohesion_results, cycles, violations, ap_results
    )
    report.health_score = health
    report.sub_scores = sub_scores

    # A007: Insights
    insights = generate_insights(
        modules, graph, coupling_results, cohesion_results, cycles,
        layer_results, violations, ap_results, health, sub_scores
    )
    report.insights = insights

    return report


# ── Output Formatters ────────────────────────────────────────────────

def format_text(report: ArchitectureReport) -> str:
    """Format report as colored terminal text."""
    lines: List[str] = []
    lines.append("")
    lines.append(_C.bold("╔══════════════════════════════════════════════════════════╗"))
    lines.append(_C.bold("║      sauravarchitect — Architecture Analysis            ║"))
    lines.append(_C.bold("╚══════════════════════════════════════════════════════════╝"))
    lines.append("")

    # Overview
    lines.append(_C.bold(_C.cyan("📊 Overview")))
    lines.append(f"  Modules:   {report.total_modules}")
    lines.append(f"  Functions: {report.total_functions}")
    lines.append(f"  Lines:     {report.total_lines}")
    lines.append("")

    # A001: Dependencies
    lines.append(_C.bold(_C.cyan("A001 — Module Dependency Graph")))
    edge_count = sum(len(deps) for deps in report.dependency_graph.values())
    lines.append(f"  Edges: {edge_count}")
    if report.cycles:
        lines.append(f"  {_C.red('⚠ Cycles: ' + str(len(report.cycles)))}")
        for cycle in report.cycles:
            lines.append(f"    {_C.yellow(' → '.join(cycle))}")
    else:
        lines.append(f"  {_C.green('✓ No cycles detected')}")
    lines.append("")

    # A002: Coupling
    lines.append(_C.bold(_C.cyan("A002 — Coupling Analysis")))
    sorted_coupling = sorted(report.coupling, key=lambda c: c["efferent"], reverse=True)
    for c in sorted_coupling[:10]:
        inst_val = c["instability"]
        inst_color = _C.green if inst_val < 0.7 else _C.yellow
        inst_str = inst_color(f"{inst_val:.2f}")
        lines.append(
            f"  {c['module']:30s}  Ca={c['afferent']:2d}  Ce={c['efferent']:2d}  "
            f"I={inst_str}"
        )
    lines.append("")

    # A003: Cohesion
    lines.append(_C.bold(_C.cyan("A003 — Cohesion Scores")))
    sorted_cohesion = sorted(report.cohesion, key=lambda c: c["score"])
    for c in sorted_cohesion[:10]:
        score = c["score"]
        sc = _C.green if score >= 70 else (_C.yellow if score >= 40 else _C.red)
        lines.append(
            f"  {c['module']:30s}  funcs={c['functions']:2d}  "
            f"components={c['connected_components']}  score={sc(f'{score:.0f}')}"
        )
    lines.append("")

    # A004: Layers
    lines.append(_C.bold(_C.cyan("A004 — Layer Assignments")))
    layer_groups: Dict[str, List[str]] = defaultdict(list)
    for la in report.layers:
        layer_groups[la["layer"]].append(la["module"])
    for layer in ["demo", "app", "core", "util"]:
        mods = layer_groups.get(layer, [])
        if mods:
            lines.append(f"  [{layer.upper():5s}]  {', '.join(mods[:8])}" +
                         (f" (+{len(mods)-8} more)" if len(mods) > 8 else ""))
    if report.layer_violations:
        lines.append(f"  {_C.yellow(f'⚠ {len(report.layer_violations)} layer violation(s)')}")
        for v in report.layer_violations[:5]:
            lines.append(f"    {v['description']}")
    else:
        lines.append(f"  {_C.green('✓ No layer violations')}")
    lines.append("")

    # A005: Anti-Patterns
    lines.append(_C.bold(_C.cyan("A005 — Anti-Pattern Scan")))
    if report.anti_patterns:
        for ap in report.anti_patterns:
            sev = ap["severity"]
            if sev == "critical":
                badge = _C.red("CRIT")
            elif sev == "warning":
                badge = _C.yellow("WARN")
            else:
                badge = _C.dim("INFO")
            lines.append(f"  [{badge}] {ap['code']} {ap['name']}: {ap['description']}")
    else:
        lines.append(f"  {_C.green('✓ No anti-patterns detected')}")
    lines.append("")

    # A006: Health Score
    lines.append(_C.bold(_C.cyan("A006 — Architecture Health Score")))
    score = report.health_score
    if score >= 80:
        gauge = _C.green(f"█████████ {score:.0f}/100")
    elif score >= 60:
        gauge = _C.yellow(f"██████░░░ {score:.0f}/100")
    elif score >= 40:
        gauge = _C.yellow(f"████░░░░░ {score:.0f}/100")
    else:
        gauge = _C.red(f"██░░░░░░░ {score:.0f}/100")
    lines.append(f"  {gauge}")
    for k, v in report.sub_scores.items():
        label = k.replace("_", " ").title()
        lines.append(f"    {label:20s} {v:.0f}")
    lines.append("")

    # A007: Insights
    lines.append(_C.bold(_C.cyan("A007 — Insights & Recommendations")))
    for ins in report.insights:
        tp = ins["type"]
        if tp == "critical":
            icon = _C.red("🔴")
        elif tp == "warning":
            icon = _C.yellow("🟡")
        elif tp == "positive":
            icon = _C.green("🟢")
        elif tp == "recommendation":
            icon = _C.cyan("💡")
        else:
            icon = "ℹ️"
        lines.append(f"  {icon} {_C.bold(ins['title'])}")
        lines.append(f"     {ins['description']}")
    lines.append("")

    return "\n".join(lines)


def format_json(report: ArchitectureReport) -> str:
    """Format report as JSON."""
    return json.dumps(asdict(report), indent=2, default=str)


def format_graph(report: ArchitectureReport) -> str:
    """ASCII dependency graph."""
    lines: List[str] = []
    lines.append(_C.bold("Dependency Graph:"))
    lines.append("")

    graph = report.dependency_graph
    if not graph:
        lines.append("  (empty)")
        return "\n".join(lines)

    for mod, deps in sorted(graph.items()):
        if deps:
            for dep in deps:
                lines.append(f"  {mod} → {dep}")
        else:
            lines.append(f"  {mod} (no dependencies)")

    return "\n".join(lines)


def generate_html(report: ArchitectureReport) -> str:
    """Generate self-contained interactive HTML dashboard."""
    data_json = json.dumps(asdict(report), indent=2, default=str)
    score = report.health_score
    score_color = "#2ecc71" if score >= 80 else ("#f39c12" if score >= 50 else "#e74c3c")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>sauravarchitect — Architecture Report</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #0d1117; color: #c9d1d9; padding: 20px; }}
  .header {{ text-align: center; padding: 30px 0; }}
  .header h1 {{ font-size: 2em; color: #58a6ff; }}
  .header .subtitle {{ color: #8b949e; margin-top: 8px; }}
  .score-gauge {{ text-align: center; margin: 30px 0; }}
  .score-circle {{ width: 150px; height: 150px; border-radius: 50%; margin: 0 auto;
                   display: flex; align-items: center; justify-content: center;
                   font-size: 2.5em; font-weight: bold; color: white;
                   background: conic-gradient({score_color} {score * 3.6}deg, #21262d {score * 3.6}deg); }}
  .score-inner {{ width: 120px; height: 120px; border-radius: 50%; background: #0d1117;
                  display: flex; align-items: center; justify-content: center; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 20px; margin: 20px 0; }}
  .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; }}
  .card h2 {{ color: #58a6ff; font-size: 1.1em; margin-bottom: 15px; border-bottom: 1px solid #30363d; padding-bottom: 8px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.9em; }}
  th {{ text-align: left; color: #8b949e; padding: 6px; border-bottom: 1px solid #30363d; }}
  td {{ padding: 6px; border-bottom: 1px solid #21262d; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.8em; font-weight: 600; }}
  .badge-critical {{ background: #da3633; color: white; }}
  .badge-warning {{ background: #d29922; color: black; }}
  .badge-info {{ background: #388bfd; color: white; }}
  .badge-positive {{ background: #238636; color: white; }}
  .bar {{ height: 8px; border-radius: 4px; background: #21262d; margin-top: 4px; }}
  .bar-fill {{ height: 100%; border-radius: 4px; }}
  .insight {{ padding: 12px; margin: 8px 0; border-radius: 6px; border-left: 4px solid; }}
  .insight-critical {{ border-color: #da3633; background: rgba(218,54,51,0.1); }}
  .insight-warning {{ border-color: #d29922; background: rgba(210,153,34,0.1); }}
  .insight-positive {{ border-color: #238636; background: rgba(35,134,54,0.1); }}
  .insight-recommendation {{ border-color: #388bfd; background: rgba(56,139,253,0.1); }}
  .insight-info {{ border-color: #388bfd; background: rgba(56,139,253,0.1); }}
  .dep-graph {{ font-family: monospace; font-size: 0.85em; line-height: 1.6; }}
  .dep-edge {{ color: #58a6ff; }}
  .sub-scores {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }}
  .sub-score {{ text-align: center; padding: 10px; }}
  .sub-score .label {{ color: #8b949e; font-size: 0.85em; }}
  .sub-score .value {{ font-size: 1.5em; font-weight: bold; }}
</style>
</head>
<body>
<div class="header">
  <h1>🏗️ sauravarchitect</h1>
  <div class="subtitle">Architecture Analysis — {report.total_modules} modules, {report.total_functions} functions, {report.total_lines} lines</div>
  <div class="subtitle">{report.timestamp}</div>
</div>

<div class="score-gauge">
  <div class="score-circle"><div class="score-inner">{score:.0f}</div></div>
  <div style="margin-top:10px;color:{score_color};font-weight:bold">Architecture Health Score</div>
</div>

<div class="sub-scores">
"""

    for k, v in report.sub_scores.items():
        sc = "#2ecc71" if v >= 70 else ("#f39c12" if v >= 40 else "#e74c3c")
        label = k.replace("_", " ").title()
        html += f"""  <div class="sub-score">
    <div class="value" style="color:{sc}">{v:.0f}</div>
    <div class="label">{label}</div>
    <div class="bar"><div class="bar-fill" style="width:{v}%;background:{sc}"></div></div>
  </div>\n"""

    html += """</div>\n<div class="grid">\n"""

    # Dependency Graph card
    html += """<div class="card"><h2>A001 — Dependency Graph</h2><div class="dep-graph">"""
    for mod, deps in sorted(report.dependency_graph.items()):
        if deps:
            for dep in deps:
                html += f'<div><span class="dep-edge">{mod} → {dep}</span></div>'
        else:
            html += f"<div>{mod} <span style='color:#8b949e'>(no deps)</span></div>"
    if report.cycles:
        html += f'<div style="margin-top:10px;color:#da3633">⚠ {len(report.cycles)} cycle(s) detected</div>'
    html += """</div></div>\n"""

    # Coupling card
    html += """<div class="card"><h2>A002 — Coupling Analysis</h2><table>
<tr><th>Module</th><th>Ca</th><th>Ce</th><th>Instability</th></tr>"""
    for c in sorted(report.coupling, key=lambda x: x["efferent"], reverse=True)[:15]:
        ic = "#2ecc71" if c["instability"] < 0.7 else "#f39c12"
        html += f'<tr><td>{c["module"]}</td><td>{c["afferent"]}</td><td>{c["efferent"]}</td>'
        html += f'<td style="color:{ic}">{c["instability"]:.2f}</td></tr>'
    html += """</table></div>\n"""

    # Cohesion card
    html += """<div class="card"><h2>A003 — Cohesion Scores</h2><table>
<tr><th>Module</th><th>Functions</th><th>Components</th><th>Score</th></tr>"""
    for c in sorted(report.cohesion, key=lambda x: x["score"])[:15]:
        sc = "#2ecc71" if c["score"] >= 70 else ("#f39c12" if c["score"] >= 40 else "#e74c3c")
        html += f'<tr><td>{c["module"]}</td><td>{c["functions"]}</td><td>{c["connected_components"]}</td>'
        html += f'<td style="color:{sc}">{c["score"]:.0f}</td></tr>'
    html += """</table></div>\n"""

    # Layers card
    html += """<div class="card"><h2>A004 — Architectural Layers</h2>"""
    layer_groups: Dict[str, List[str]] = defaultdict(list)
    for la in report.layers:
        layer_groups[la["layer"]].append(la["module"])
    layer_colors = {"demo": "#da3633", "app": "#f39c12", "core": "#58a6ff", "util": "#2ecc71"}
    for layer in ["demo", "app", "core", "util"]:
        mods = layer_groups.get(layer, [])
        if mods:
            lc = layer_colors.get(layer, "#8b949e")
            html += f'<div style="margin:8px 0"><span class="badge" style="background:{lc};color:white">{layer.upper()}</span> '
            html += ", ".join(mods[:12])
            if len(mods) > 12:
                html += f" (+{len(mods)-12} more)"
            html += "</div>"
    if report.layer_violations:
        html += f'<div style="margin-top:10px;color:#d29922">⚠ {len(report.layer_violations)} violation(s)</div>'
        for v in report.layer_violations[:5]:
            html += f'<div style="font-size:0.85em;color:#8b949e;margin-left:10px">{v["description"]}</div>'
    html += """</div>\n"""

    # Anti-patterns card
    html += """<div class="card"><h2>A005 — Anti-Patterns</h2>"""
    if report.anti_patterns:
        for ap in report.anti_patterns:
            badge_class = f"badge-{ap['severity']}"
            html += f'<div style="margin:8px 0"><span class="badge {badge_class}">{ap["severity"].upper()}</span> '
            html += f'<strong>{ap["code"]} {ap["name"]}</strong>: {ap["description"]}'
            html += f'<div style="font-size:0.85em;color:#8b949e;margin-left:10px">💡 {ap["suggestion"]}</div></div>'
    else:
        html += '<div style="color:#2ecc71">✓ No anti-patterns detected</div>'
    html += """</div>\n"""

    # Insights card
    html += """<div class="card" style="grid-column:1/-1"><h2>A007 — Insights & Recommendations</h2>"""
    for ins in report.insights:
        html += f'<div class="insight insight-{ins["type"]}">'
        html += f'<strong>{ins["title"]}</strong><br>{ins["description"]}</div>'
    html += """</div>\n"""

    html += f"""</div>
<script>const REPORT_DATA = {data_json};</script>
</body>
</html>"""

    return html


# ── CLI ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="sauravarchitect",
        description="Autonomous code architecture analyzer for sauravcode projects",
    )
    parser.add_argument("path", nargs="?", default=".", help="Directory or file to analyze")
    parser.add_argument("--recursive", "-r", action="store_true", help="Recurse into subdirectories")
    parser.add_argument("--html", metavar="FILE", help="Generate interactive HTML dashboard")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--graph", action="store_true", help="Show ASCII dependency graph")
    parser.add_argument("--hotspots", action="store_true", help="Show highest-coupling modules")
    parser.add_argument("--layers", action="store_true", help="Show layer assignments only")
    parser.add_argument("--version", action="version", version=f"sauravarchitect {__version__}")
    args = parser.parse_args()

    report = analyze(args.path, recursive=args.recursive)

    if args.json:
        print(format_json(report))
    elif args.graph:
        print(format_graph(report))
    elif args.hotspots:
        print(_C.bold("Coupling Hotspots (highest efferent):"))
        print("")
        sorted_c = sorted(report.coupling, key=lambda c: c["efferent"], reverse=True)
        for c in sorted_c[:15]:
            print(f"  {c['module']:30s}  Ca={c['afferent']:2d}  Ce={c['efferent']:2d}  I={c['instability']:.2f}")
    elif args.layers:
        print(_C.bold("Layer Assignments:"))
        print("")
        layer_groups: Dict[str, List[str]] = defaultdict(list)
        for la in report.layers:
            layer_groups[la["layer"]].append(la["module"])
        for layer in ["demo", "app", "core", "util"]:
            mods = layer_groups.get(layer, [])
            if mods:
                print(f"  [{layer.upper():5s}]  {', '.join(sorted(mods))}")
    else:
        print(format_text(report))

    if args.html:
        html = generate_html(report)
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\n  HTML dashboard saved to {args.html}")

    # Exit code based on health
    if report.health_score < 30:
        sys.exit(2)
    elif report.health_score < 60:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
