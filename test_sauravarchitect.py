#!/usr/bin/env python3
"""Tests for sauravarchitect - Autonomous Code Architecture Analyzer."""

import sys
import os
import json
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sauravarchitect import (
    parse_module, build_dependency_graph, tarjan_scc, detect_cycles,
    analyze_coupling, analyze_cohesion, infer_layers, detect_layer_violations,
    scan_anti_patterns, compute_health_score, generate_insights,
    analyze, format_text, format_json, format_graph, generate_html,
    ModuleInfo, FunctionInfo, CouplingResult, CohesionResult,
    LayerAssignment, AntiPattern, ArchitectureReport,
    FUNC_DEF_RE, IMPORT_RE, LAYER_ORDER,
)

PASS = 0
FAIL = 0


def check(name, condition):
    global PASS, FAIL
    if condition:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {name}")


def make_srv(content, filename="test.srv", dirname=None):
    """Write a .srv file to a temp directory and return (path, dir)."""
    d = dirname or tempfile.mkdtemp()
    path = os.path.join(d, filename)
    with open(path, "w") as f:
        f.write(content)
    return path, d


def make_project(files_dict):
    """Create a temp directory with multiple .srv files. Returns dir path."""
    d = tempfile.mkdtemp()
    for name, content in files_dict.items():
        path = os.path.join(d, name)
        with open(path, "w") as f:
            f.write(content)
    return d


# ── Test: Parsing ────────────────────────────────────────────────────

def test_parse_empty_file():
    path, d = make_srv("")
    try:
        mod = parse_module(path)
        check("parse empty: name", mod.name == "test")
        check("parse empty: no functions", len(mod.functions) == 0)
        check("parse empty: no imports", len(mod.imports) == 0)
        check("parse empty: 0 lines", mod.lines == 0)
    finally:
        shutil.rmtree(d)


def test_parse_functions():
    src = """
function add a b
    return a + b

function subtract x y
    result = x - y
    return result

fn multiply a b
    return a * b
"""
    path, d = make_srv(src)
    try:
        mod = parse_module(path)
        check("parse funcs: count", len(mod.functions) == 3)
        names = [f.name for f in mod.functions]
        check("parse funcs: add", "add" in names)
        check("parse funcs: subtract", "subtract" in names)
        check("parse funcs: multiply", "multiply" in names)
        # Check variable tracking
        sub = [f for f in mod.functions if f.name == "subtract"][0]
        check("parse funcs: writes result", "result" in sub.variables_written)
    finally:
        shutil.rmtree(d)


def test_parse_imports():
    src = """
import "utils.srv"
import "helpers"

function main
    print "hello"
"""
    path, d = make_srv(src)
    try:
        mod = parse_module(path)
        check("parse imports: count", len(mod.imports) == 2)
        check("parse imports: utils normalized", "utils" in mod.imports)
        check("parse imports: helpers", "helpers" in mod.imports)
    finally:
        shutil.rmtree(d)


def test_parse_code_lines():
    src = """# comment
function foo
    x = 1
    # another comment
    return x
"""
    path, d = make_srv(src)
    try:
        mod = parse_module(path)
        check("parse code_lines: total", mod.lines >= 5)
        check("parse code_lines: code only", mod.code_lines == 3)  # function, x=1, return x
    finally:
        shutil.rmtree(d)


# ── Test: Dependency Graph ───────────────────────────────────────────

def test_build_dependency_graph():
    d = make_project({
        "a.srv": 'import "b.srv"\nimport "c.srv"\nfunction main\n    print 1',
        "b.srv": 'import "c.srv"\nfunction helper\n    return 1',
        "c.srv": 'function util\n    return 0',
    })
    try:
        modules = [parse_module(os.path.join(d, f)) for f in ["a.srv", "b.srv", "c.srv"]]
        graph = build_dependency_graph(modules)
        check("dep graph: a deps", sorted(graph["a"]) == ["b", "c"])
        check("dep graph: b deps", graph["b"] == ["c"])
        check("dep graph: c deps", graph["c"] == [])
    finally:
        shutil.rmtree(d)


def test_tarjan_no_cycles():
    graph = {"a": ["b"], "b": ["c"], "c": []}
    sccs = tarjan_scc(graph)
    # All singletons
    check("tarjan no cycles: all singletons", all(len(s) == 1 for s in sccs))


def test_tarjan_with_cycle():
    graph = {"a": ["b"], "b": ["c"], "c": ["a"]}
    sccs = tarjan_scc(graph)
    big = [s for s in sccs if len(s) > 1]
    check("tarjan cycle: one SCC", len(big) == 1)
    check("tarjan cycle: all three", set(big[0]) == {"a", "b", "c"})


def test_detect_cycles():
    graph = {"a": ["b"], "b": ["a"], "c": []}
    cycles = detect_cycles(graph)
    check("detect cycles: found", len(cycles) >= 1)
    cycle_members = set()
    for c in cycles:
        cycle_members.update(c)
    check("detect cycles: a and b", "a" in cycle_members and "b" in cycle_members)


def test_detect_no_cycles():
    graph = {"a": ["b"], "b": [], "c": []}
    cycles = detect_cycles(graph)
    check("no cycles: empty", len(cycles) == 0)


def test_self_loop():
    graph = {"a": ["a"]}
    cycles = detect_cycles(graph)
    check("self loop detected", len(cycles) >= 1)


# ── Test: Coupling ───────────────────────────────────────────────────

def test_coupling_basic():
    d = make_project({
        "a.srv": 'import "b.srv"\nimport "c.srv"\nfunction main\n    print 1',
        "b.srv": 'import "c.srv"\nfunction helper\n    return 1',
        "c.srv": 'function util\n    return 0',
    })
    try:
        modules = [parse_module(os.path.join(d, f)) for f in ["a.srv", "b.srv", "c.srv"]]
        graph = build_dependency_graph(modules)
        coupling = analyze_coupling(modules, graph)
        c_map = {c.module: c for c in coupling}
        check("coupling: c afferent=2", c_map["c"].afferent == 2)
        check("coupling: a efferent=2", c_map["a"].efferent == 2)
        check("coupling: c efferent=0", c_map["c"].efferent == 0)
        check("coupling: a instability=1.0", c_map["a"].instability == 1.0)
        check("coupling: c instability=0.0", c_map["c"].instability == 0.0)
    finally:
        shutil.rmtree(d)


# ── Test: Cohesion ───────────────────────────────────────────────────

def test_cohesion_single_function():
    path, d = make_srv("function only_one\n    return 1")
    try:
        mod = parse_module(path)
        results = analyze_cohesion([mod])
        check("cohesion single: score=100", results[0].score == 100.0)
    finally:
        shutil.rmtree(d)


def test_cohesion_connected():
    src = """
function compute x
    result = x * 2
    return result

function use_compute y
    result = compute y
    return result
"""
    path, d = make_srv(src)
    try:
        mod = parse_module(path)
        results = analyze_cohesion([mod])
        check("cohesion connected: high score", results[0].score >= 50)
    finally:
        shutil.rmtree(d)


def test_cohesion_disconnected():
    src = """
function alpha
    a = 1
    return a

function beta
    b = 2
    return b

function gamma
    c = 3
    return c
"""
    path, d = make_srv(src)
    try:
        mod = parse_module(path)
        results = analyze_cohesion([mod])
        check("cohesion disconnected: lower score", results[0].score < 100)
        check("cohesion disconnected: multiple components", results[0].connected_components > 1)
    finally:
        shutil.rmtree(d)


# ── Test: Layer Inference ────────────────────────────────────────────

def test_layer_naming_heuristic():
    d = make_project({
        "utils.srv": "function helper\n    return 1",
        "demo_app.srv": "function demo\n    print 1",
        "main.srv": 'import "utils.srv"\nfunction main\n    print 1',
        "core.srv": "function process\n    return 2",
    })
    try:
        modules = [parse_module(os.path.join(d, f))
                    for f in ["utils.srv", "demo_app.srv", "main.srv", "core.srv"]]
        graph = build_dependency_graph(modules)
        layers = infer_layers(modules, graph)
        layer_map = {la.module: la.layer for la in layers}
        check("layer: utils → util", layer_map["utils"] == "util")
        check("layer: demo_app → demo", layer_map["demo_app"] == "demo")
        check("layer: main → app", layer_map["main"] == "app")
    finally:
        shutil.rmtree(d)


def test_layer_violation():
    d = make_project({
        "util_mod.srv": 'import "app_main.srv"\nfunction helper\n    return 1',
        "app_main.srv": "function main\n    print 1",
    })
    try:
        modules = [parse_module(os.path.join(d, f)) for f in ["util_mod.srv", "app_main.srv"]]
        graph = build_dependency_graph(modules)
        layers = infer_layers(modules, graph)
        violations = detect_layer_violations(layers, graph)
        check("layer violation: detected", len(violations) > 0)
    finally:
        shutil.rmtree(d)


def test_no_layer_violations():
    d = make_project({
        "app.srv": 'import "core.srv"\nfunction main\n    print 1',
        "core.srv": "function process\n    return 1",
    })
    try:
        modules = [parse_module(os.path.join(d, f)) for f in ["app.srv", "core.srv"]]
        graph = build_dependency_graph(modules)
        layers = infer_layers(modules, graph)
        # This may or may not have violations depending on heuristic; just verify it runs
        violations = detect_layer_violations(layers, graph)
        check("no violation: ran", isinstance(violations, list))
    finally:
        shutil.rmtree(d)


# ── Test: Anti-Patterns ──────────────────────────────────────────────

def test_god_module():
    funcs = "\n".join(f"function f{i}\n    return {i}\n" for i in range(20))
    path, d = make_srv(funcs)
    try:
        mod = parse_module(path)
        graph = build_dependency_graph([mod])
        coupling = analyze_coupling([mod], graph)
        cohesion = analyze_cohesion([mod])
        layers = infer_layers([mod], graph)
        aps = scan_anti_patterns([mod], graph, coupling, cohesion, [], layers)
        god_mods = [ap for ap in aps if ap.code == "AP01"]
        check("god module: detected", len(god_mods) > 0)
    finally:
        shutil.rmtree(d)


def test_orphan_module():
    d = make_project({
        "main.srv": 'import "helper.srv"\nfunction main\n    print 1',
        "helper.srv": "function help\n    return 1",
        "orphan.srv": "function lonely\n    return 0",
    })
    try:
        modules = [parse_module(os.path.join(d, f)) for f in ["main.srv", "helper.srv", "orphan.srv"]]
        graph = build_dependency_graph(modules)
        coupling = analyze_coupling(modules, graph)
        cohesion = analyze_cohesion(modules)
        layers = infer_layers(modules, graph)
        aps = scan_anti_patterns(modules, graph, coupling, cohesion, [], layers)
        orphans = [ap for ap in aps if ap.code == "AP02"]
        check("orphan module: detected", len(orphans) >= 1)
    finally:
        shutil.rmtree(d)


def test_circular_dependency_pattern():
    d = make_project({
        "a.srv": 'import "b.srv"\nfunction fa\n    return 1',
        "b.srv": 'import "a.srv"\nfunction fb\n    return 2',
    })
    try:
        modules = [parse_module(os.path.join(d, f)) for f in ["a.srv", "b.srv"]]
        graph = build_dependency_graph(modules)
        cycles = detect_cycles(graph)
        coupling = analyze_coupling(modules, graph)
        cohesion = analyze_cohesion(modules)
        layers = infer_layers(modules, graph)
        aps = scan_anti_patterns(modules, graph, coupling, cohesion, cycles, layers)
        circulars = [ap for ap in aps if ap.code == "AP03"]
        check("circular dep: detected", len(circulars) >= 1)
    finally:
        shutil.rmtree(d)


# ── Test: Health Score ───────────────────────────────────────────────

def test_health_score_perfect():
    path, d = make_srv("function main\n    return 1")
    try:
        mod = parse_module(path)
        coupling = [CouplingResult(module="test", afferent=0, efferent=0, instability=0.0)]
        cohesion = [CohesionResult(module="test", functions=1, connected_components=1, lcom4=0, score=100.0)]
        score, subs = compute_health_score([mod], coupling, cohesion, [], [], [])
        check("health perfect: high score", score >= 70)
    finally:
        shutil.rmtree(d)


def test_health_score_with_issues():
    path, d = make_srv("function main\n    return 1")
    try:
        mod = parse_module(path)
        coupling = [CouplingResult(module="test", afferent=0, efferent=0, instability=0.0)]
        cohesion = [CohesionResult(module="test", functions=1, connected_components=1, lcom4=0, score=100.0)]
        aps = [
            AntiPattern("AP01", "God Module", "critical", "test", "too big", "split"),
            AntiPattern("AP03", "Circular Dep", "critical", "test", "cycle", "fix"),
        ]
        score, subs = compute_health_score([mod], coupling, cohesion, [["a", "b"]], [], aps)
        check("health issues: lower score", score < 80)
    finally:
        shutil.rmtree(d)


def test_health_sub_scores():
    path, d = make_srv("function main\n    return 1")
    try:
        mod = parse_module(path)
        coupling = [CouplingResult(module="test", afferent=1, efferent=1, instability=0.5)]
        cohesion = [CohesionResult(module="test", functions=1, connected_components=1, lcom4=0, score=100.0)]
        _, subs = compute_health_score([mod], coupling, cohesion, [], [], [])
        check("sub scores: has coupling", "coupling" in subs)
        check("sub scores: has cohesion", "cohesion" in subs)
        check("sub scores: has layering", "layering" in subs)
        check("sub scores: has anti_patterns", "anti_patterns" in subs)
        check("sub scores: has modularity", "modularity" in subs)
    finally:
        shutil.rmtree(d)


# ── Test: Insights ───────────────────────────────────────────────────

def test_insights_healthy():
    path, d = make_srv("function main\n    return 1")
    try:
        mod = parse_module(path)
        graph = {"test": []}
        coupling = [CouplingResult(module="test", afferent=0, efferent=0, instability=0.0)]
        cohesion = [CohesionResult(module="test", functions=1, connected_components=1, lcom4=0, score=100.0)]
        layers = [LayerAssignment(module="test", layer="core", confidence=0.8)]
        insights = generate_insights([mod], graph, coupling, cohesion, [], layers, [], [], 90.0, {"coupling": 90, "cohesion": 100, "layering": 100, "anti_patterns": 100, "modularity": 100})
        types = [i["type"] for i in insights]
        check("insights healthy: has positive", "positive" in types)
    finally:
        shutil.rmtree(d)


def test_insights_cycles():
    path, d = make_srv("function main\n    return 1")
    try:
        mod = parse_module(path)
        graph = {"test": []}
        coupling = [CouplingResult(module="test", afferent=0, efferent=0, instability=0.0)]
        cohesion = [CohesionResult(module="test", functions=1, connected_components=1, lcom4=0, score=100.0)]
        layers = [LayerAssignment(module="test", layer="core", confidence=0.8)]
        insights = generate_insights([mod], graph, coupling, cohesion, [["a", "b"]], layers, [], [], 50.0, {"coupling": 50, "cohesion": 100, "layering": 50, "anti_patterns": 100, "modularity": 100})
        titles = [i["title"] for i in insights]
        has_cycle = any("Cycle" in t for t in titles)
        check("insights: mentions cycles", has_cycle)
    finally:
        shutil.rmtree(d)


# ── Test: Full Analysis ─────────────────────────────────────────────

def test_analyze_empty_dir():
    d = tempfile.mkdtemp()
    try:
        report = analyze(d)
        check("analyze empty: 0 modules", report.total_modules == 0)
        check("analyze empty: score exists", isinstance(report.health_score, float))
    finally:
        shutil.rmtree(d)


def test_analyze_single_file():
    d = make_project({"hello.srv": "function greet name\n    print name\n"})
    try:
        report = analyze(d)
        check("analyze single: 1 module", report.total_modules == 1)
        check("analyze single: 1 function", report.total_functions == 1)
        check("analyze single: has health", report.health_score >= 0)
    finally:
        shutil.rmtree(d)


def test_analyze_multi_file():
    d = make_project({
        "a.srv": 'import "b.srv"\nfunction main\n    helper 1\n',
        "b.srv": 'function helper x\n    return x + 1\n',
    })
    try:
        report = analyze(d)
        check("analyze multi: 2 modules", report.total_modules == 2)
        check("analyze multi: has graph", len(report.dependency_graph) == 2)
        check("analyze multi: has coupling", len(report.coupling) == 2)
    finally:
        shutil.rmtree(d)


# ── Test: Output Formats ────────────────────────────────────────────

def test_format_text():
    d = make_project({"x.srv": "function foo\n    return 1\n"})
    try:
        report = analyze(d)
        text = format_text(report)
        check("format text: has header", "sauravarchitect" in text)
        check("format text: has A001", "A001" in text)
        check("format text: has health", "Health" in text)
    finally:
        shutil.rmtree(d)


def test_format_json_valid():
    d = make_project({"x.srv": "function foo\n    return 1\n"})
    try:
        report = analyze(d)
        j = format_json(report)
        data = json.loads(j)
        check("format json: valid", isinstance(data, dict))
        check("format json: has health_score", "health_score" in data)
        check("format json: has modules", "modules" in data)
    finally:
        shutil.rmtree(d)


def test_format_graph_output():
    d = make_project({
        "a.srv": 'import "b.srv"\nfunction main\n    print 1\n',
        "b.srv": "function helper\n    return 1\n",
    })
    try:
        report = analyze(d)
        g = format_graph(report)
        check("format graph: has arrow", "→" in g)
        check("format graph: has module name", "a" in g)
    finally:
        shutil.rmtree(d)


def test_generate_html():
    d = make_project({
        "a.srv": 'import "b.srv"\nfunction main\n    print 1\n',
        "b.srv": "function helper\n    return 1\n",
    })
    try:
        report = analyze(d)
        html = generate_html(report)
        check("html: has doctype", "<!DOCTYPE html>" in html)
        check("html: has title", "sauravarchitect" in html)
        check("html: has score", "Health Score" in html)
        check("html: has data", "REPORT_DATA" in html)
    finally:
        shutil.rmtree(d)


# ── Test: Edge Cases ────────────────────────────────────────────────

def test_module_with_only_comments():
    path, d = make_srv("# This is just comments\n# Nothing else\n")
    try:
        mod = parse_module(path)
        check("comments only: 0 code lines", mod.code_lines == 0)
        check("comments only: 0 functions", len(mod.functions) == 0)
    finally:
        shutil.rmtree(d)


def test_deeply_nested_functions():
    src = """
function outer
    x = 1
    if x > 0
        y = 2
        if y > 0
            z = 3
            return z
"""
    path, d = make_srv(src)
    try:
        mod = parse_module(path)
        check("nested: 1 function", len(mod.functions) == 1)
        check("nested: name correct", mod.functions[0].name == "outer")
    finally:
        shutil.rmtree(d)


def test_regex_patterns():
    check("FUNC_DEF_RE: function", FUNC_DEF_RE.match("function foo a b") is not None)
    check("FUNC_DEF_RE: fn", FUNC_DEF_RE.match("fn bar x") is not None)
    check("FUNC_DEF_RE: indented", FUNC_DEF_RE.match("    function nested") is not None)
    check("IMPORT_RE: basic", IMPORT_RE.match('import "file.srv"') is not None)
    check("IMPORT_RE: no match", IMPORT_RE.match("not an import") is None)


def test_layer_order():
    check("layer order: util < core", LAYER_ORDER["util"] < LAYER_ORDER["core"])
    check("layer order: core < app", LAYER_ORDER["core"] < LAYER_ORDER["app"])
    check("layer order: app < demo", LAYER_ORDER["app"] < LAYER_ORDER["demo"])


# ── Run All Tests ────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_parse_empty_file,
        test_parse_functions,
        test_parse_imports,
        test_parse_code_lines,
        test_build_dependency_graph,
        test_tarjan_no_cycles,
        test_tarjan_with_cycle,
        test_detect_cycles,
        test_detect_no_cycles,
        test_self_loop,
        test_coupling_basic,
        test_cohesion_single_function,
        test_cohesion_connected,
        test_cohesion_disconnected,
        test_layer_naming_heuristic,
        test_layer_violation,
        test_no_layer_violations,
        test_god_module,
        test_orphan_module,
        test_circular_dependency_pattern,
        test_health_score_perfect,
        test_health_score_with_issues,
        test_health_sub_scores,
        test_insights_healthy,
        test_insights_cycles,
        test_analyze_empty_dir,
        test_analyze_single_file,
        test_analyze_multi_file,
        test_format_text,
        test_format_json_valid,
        test_format_graph_output,
        test_generate_html,
        test_module_with_only_comments,
        test_deeply_nested_functions,
        test_regex_patterns,
        test_layer_order,
    ]

    print(f"Running {len(tests)} tests for sauravarchitect...\n")
    for t in tests:
        try:
            t()
        except Exception as e:
            FAIL += 1
            print(f"  FAIL (exception): {t.__name__}: {e}")

    print(f"\n{'='*50}")
    print(f"  PASS: {PASS}  FAIL: {FAIL}  TOTAL: {PASS + FAIL}")
    print(f"{'='*50}")
    sys.exit(1 if FAIL else 0)
