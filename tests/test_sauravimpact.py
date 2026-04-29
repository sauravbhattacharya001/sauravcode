#!/usr/bin/env python3
"""Tests for sauravimpact — Change Impact Analyzer."""

import json
import os
import sys
import tempfile
import shutil
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sauravimpact import (
    FuncInfo, ImpactNode, ImpactReport,
    _parse_functions, _parse_imports, _read_file,
    build_call_graph, build_reverse_graph, _bfs_reachable,
    _engine_i001_direct_deps, _engine_i002_transitive,
    _engine_i003_variable_flow, _engine_i005_coupling,
    _engine_i006_cascade, _engine_i007_test_coverage,
    _engine_i008_risk_score,
    analyze, find_hotspots, find_safe_changes, to_json,
    generate_html, _indent_level, _html_escape,
)


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def tmpdir():
    d = tempfile.mkdtemp(prefix="sauravimpact_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


SAMPLE_CODE = """\
function greet(name)
    msg = "Hello " + name
    print(msg)

function helper()
    greet("world")
    compute(10)

function compute(x)
    result = x * 2
    return result

function standalone()
    y = 42
    return y
"""

SAMPLE_CODE_B = """\
import "main.srv"

function wrapper()
    helper()
"""

TEST_CODE = """\
function test_greet()
    greet("test")

function test_compute()
    compute(5)
"""


# ── Parsing Tests ─────────────────────────────────────────────────────

class TestParsing:
    def test_parse_functions_count(self):
        lines = SAMPLE_CODE.splitlines(True)
        funcs = _parse_functions(lines, "test.srv")
        assert len(funcs) == 4

    def test_parse_function_names(self):
        lines = SAMPLE_CODE.splitlines(True)
        funcs = _parse_functions(lines, "test.srv")
        names = [f.name for f in funcs]
        assert "greet" in names
        assert "helper" in names
        assert "compute" in names
        assert "standalone" in names

    def test_parse_function_params(self):
        lines = SAMPLE_CODE.splitlines(True)
        funcs = _parse_functions(lines, "test.srv")
        func_map = {f.name: f for f in funcs}
        assert func_map["greet"].params == ["name"]
        assert func_map["compute"].params == ["x"]
        assert func_map["standalone"].params == []

    def test_parse_callees(self):
        lines = SAMPLE_CODE.splitlines(True)
        funcs = _parse_functions(lines, "test.srv")
        func_map = {f.name: f for f in funcs}
        assert "greet" in func_map["helper"].callees
        assert "compute" in func_map["helper"].callees

    def test_parse_variables_written(self):
        lines = SAMPLE_CODE.splitlines(True)
        funcs = _parse_functions(lines, "test.srv")
        func_map = {f.name: f for f in funcs}
        assert "msg" in func_map["greet"].variables_written
        assert "result" in func_map["compute"].variables_written

    def test_parse_imports(self):
        lines = SAMPLE_CODE_B.splitlines(True)
        imports = _parse_imports(lines)
        assert imports == ["main.srv"]

    def test_parse_empty_file(self):
        funcs = _parse_functions([], "empty.srv")
        assert funcs == []

    def test_parse_fn_keyword(self):
        code = "fn add(a, b)\n    return a + b\n"
        funcs = _parse_functions(code.splitlines(True), "test.srv")
        assert len(funcs) == 1
        assert funcs[0].name == "add"

    def test_indent_level(self):
        assert _indent_level("    hello") == 4
        assert _indent_level("hello") == 0
        assert _indent_level("\thello") == 4
        assert _indent_level("") == 0


# ── Call Graph Tests ──────────────────────────────────────────────────

class TestCallGraph:
    def test_build_call_graph(self):
        lines = SAMPLE_CODE.splitlines(True)
        funcs = _parse_functions(lines, "test.srv")
        graph = build_call_graph(funcs)
        assert "greet" in graph.get("helper", [])
        assert "compute" in graph.get("helper", [])

    def test_reverse_graph(self):
        graph = {"a": ["b", "c"], "b": ["c"]}
        rev = build_reverse_graph(graph)
        assert "a" in rev["b"]
        assert "a" in rev["c"]
        assert "b" in rev["c"]

    def test_bfs_reachable(self):
        graph = {"a": ["b"], "b": ["c"], "c": []}
        reached = _bfs_reachable(graph, "a")
        assert reached == {"a": 0, "b": 1, "c": 2}

    def test_bfs_cycle(self):
        graph = {"a": ["b"], "b": ["a"]}
        reached = _bfs_reachable(graph, "a")
        assert "a" in reached and "b" in reached

    def test_bfs_isolated(self):
        graph = {"a": []}
        reached = _bfs_reachable(graph, "a")
        assert reached == {"a": 0}


# ── Engine Tests ──────────────────────────────────────────────────────

class TestEngines:
    def _setup_funcs(self):
        lines = SAMPLE_CODE.splitlines(True)
        funcs = _parse_functions(lines, "test.srv")
        func_map = {f.name: f for f in funcs}
        graph = build_call_graph(funcs)
        rev = build_reverse_graph(graph)
        return funcs, func_map, graph, rev

    def test_i001_direct_callers(self):
        funcs, func_map, graph, rev = self._setup_funcs()
        nodes = _engine_i001_direct_deps("greet", rev, func_map)
        names = [n.name for n in nodes]
        assert "helper" in names

    def test_i001_no_callers(self):
        funcs, func_map, graph, rev = self._setup_funcs()
        nodes = _engine_i001_direct_deps("standalone", rev, func_map)
        assert len(nodes) == 0

    def test_i002_transitive(self):
        # Setup a deeper chain
        code = """\
function a()
    b()

function b()
    c()

function c()
    d()

function d()
    return 1
"""
        funcs = _parse_functions(code.splitlines(True), "t.srv")
        func_map = {f.name: f for f in funcs}
        graph = build_call_graph(funcs)
        rev = build_reverse_graph(graph)
        nodes, depth = _engine_i002_transitive("d", rev, func_map)
        names = [n.name for n in nodes]
        assert "a" in names
        assert depth >= 2

    def test_i003_variable_flow(self):
        funcs, func_map, graph, rev = self._setup_funcs()
        nodes = _engine_i003_variable_flow("greet", funcs, func_map)
        # msg is written by greet; other funcs may or may not read it
        assert isinstance(nodes, list)

    def test_i003_no_shared_vars(self):
        code = "function isolated()\n    x = 1\n    return x\n"
        funcs = _parse_functions(code.splitlines(True), "t.srv")
        func_map = {f.name: f for f in funcs}
        nodes = _engine_i003_variable_flow("isolated", funcs, func_map)
        assert nodes == []

    def test_i005_coupling_isolated(self):
        graph = {"lone": []}
        rev = build_reverse_graph(graph)
        fi = FuncInfo("lone", "t.srv", 1, [], [], [], set(), set())
        func_map = {"lone": fi}
        score, level = _engine_i005_coupling("lone", graph, rev, func_map)
        assert score == 0.0
        assert level == "isolated"

    def test_i005_coupling_high(self):
        graph = {"hub": ["a", "b", "c", "d", "e"]}
        rev = build_reverse_graph(graph)
        rev["hub"] = ["x", "y", "z"]
        fi = FuncInfo("hub", "t.srv", 1, [], [], ["a", "b", "c", "d", "e"], set(), set())
        func_map = {"hub": fi}
        for n in ["a", "b", "c", "d", "e", "x", "y", "z"]:
            func_map[n] = FuncInfo(n, "t.srv", 1, [], [], [], set(), set())
        score, level = _engine_i005_coupling("hub", graph, rev, func_map)
        assert score > 0.3

    def test_i006_cascade(self):
        funcs, func_map, graph, rev = self._setup_funcs()
        nodes = _engine_i006_cascade("greet", graph, rev, func_map)
        names = [n.name for n in nodes]
        assert "helper" in names

    def test_i007_coverage_full(self):
        cov, untested = _engine_i007_test_coverage(set(), [])
        assert cov == 1.0
        assert untested == []

    def test_i007_coverage_with_tests(self, tmpdir):
        test_file = os.path.join(tmpdir, "test_main.srv")
        _write(test_file, TEST_CODE)
        cov, untested = _engine_i007_test_coverage({"greet", "compute", "helper"}, [test_file])
        assert "greet" not in untested
        assert "compute" not in untested
        assert "helper" in untested
        assert cov < 1.0

    def test_i008_safe_score(self):
        score, level = _engine_i008_risk_score(0, 0, 0, 0, 0.0, 0, 1.0, 0)
        assert score == 0
        assert level == "safe"

    def test_i008_danger_score(self):
        score, level = _engine_i008_risk_score(10, 10, 5, 5, 1.0, 5, 0.0, 5)
        assert score > 50
        assert level in ("warning", "danger")

    def test_i008_levels(self):
        for expected_level, args in [
            ("safe", (0, 0, 0, 0, 0.0, 0, 1.0, 0)),
            ("caution", (2, 1, 1, 1, 0.1, 1, 0.7, 1)),
        ]:
            _, level = _engine_i008_risk_score(*args)
            assert level == expected_level


# ── Integration Tests ─────────────────────────────────────────────────

class TestAnalyze:
    def test_analyze_file(self, tmpdir):
        path = os.path.join(tmpdir, "main.srv")
        _write(path, SAMPLE_CODE)
        reports = analyze([tmpdir])
        assert len(reports) == 4
        names = [r.target for r in reports]
        assert "greet" in names

    def test_analyze_specific_function(self, tmpdir):
        path = os.path.join(tmpdir, "main.srv")
        _write(path, SAMPLE_CODE)
        reports = analyze([tmpdir], target_function="helper")
        assert len(reports) == 1
        assert reports[0].target == "helper"

    def test_analyze_missing_function(self, tmpdir):
        path = os.path.join(tmpdir, "main.srv")
        _write(path, SAMPLE_CODE)
        reports = analyze([tmpdir], target_function="nonexistent")
        assert reports == []

    def test_analyze_empty_dir(self, tmpdir):
        reports = analyze([tmpdir])
        assert reports == []

    def test_analyze_report_fields(self, tmpdir):
        path = os.path.join(tmpdir, "main.srv")
        _write(path, SAMPLE_CODE)
        reports = analyze([tmpdir], target_function="helper")
        r = reports[0]
        assert r.risk_score >= 0
        assert r.risk_level in ("safe", "caution", "warning", "danger")
        assert r.files_scanned >= 1
        assert r.total_lines > 0

    def test_hotspots(self, tmpdir):
        path = os.path.join(tmpdir, "main.srv")
        _write(path, SAMPLE_CODE)
        reports = analyze([tmpdir])
        hotspots = find_hotspots(reports, 2)
        assert len(hotspots) <= 2
        if len(hotspots) >= 2:
            assert hotspots[0].risk_score >= hotspots[1].risk_score

    def test_safe_changes(self, tmpdir):
        path = os.path.join(tmpdir, "main.srv")
        _write(path, SAMPLE_CODE)
        reports = analyze([tmpdir])
        safe = find_safe_changes(reports)
        for r in safe:
            assert r.risk_score <= 25


# ── Output Tests ──────────────────────────────────────────────────────

class TestOutput:
    def test_to_json(self, tmpdir):
        path = os.path.join(tmpdir, "main.srv")
        _write(path, SAMPLE_CODE)
        reports = analyze([tmpdir])
        result = to_json(reports)
        assert result["version"] == "1.0.0"
        assert len(result["reports"]) == 4
        assert "risk_score" in result["reports"][0]

    def test_json_serializable(self, tmpdir):
        path = os.path.join(tmpdir, "main.srv")
        _write(path, SAMPLE_CODE)
        reports = analyze([tmpdir])
        result = to_json(reports)
        s = json.dumps(result)
        assert isinstance(s, str)

    def test_html_generation(self, tmpdir):
        path = os.path.join(tmpdir, "main.srv")
        _write(path, SAMPLE_CODE)
        reports = analyze([tmpdir])
        html_path = os.path.join(tmpdir, "report.html")
        generate_html(reports, html_path)
        assert os.path.exists(html_path)
        content = open(html_path, encoding="utf-8").read()
        assert "sauravimpact" in content
        assert "Risk Distribution" in content

    def test_html_escape(self):
        assert _html_escape('<script>') == '&lt;script&gt;'
        assert _html_escape('"hello"') == '&quot;hello&quot;'

    def test_impact_report_risk_color(self):
        r = ImpactReport(target="t", target_file="f.srv", risk_score=10)
        assert r.risk_color == "green"
        r.risk_score = 30
        assert r.risk_color == "yellow"
        r.risk_score = 60
        assert r.risk_color == "orange"
        r.risk_score = 80
        assert r.risk_color == "red"
