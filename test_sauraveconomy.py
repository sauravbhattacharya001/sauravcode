#!/usr/bin/env python3
"""Tests for sauraveconomy - Autonomous Code Economy Analyzer."""

import sys
import os
import json
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sauraveconomy import (
    parse_module, calculate_gdp, analyze_labor_market, analyze_trade,
    track_inflation, analyze_supply_chain, score_efficiency,
    generate_insights, compute_health_score, analyze,
    format_text, format_json, generate_html,
    ModuleInfo, FunctionInfo, GDPReport, LaborReport, TradeReport,
    InflationReport, SupplyChainReport, EfficiencyReport, EconomyReport,
    FUNC_DEF_RE, IMPORT_RE, ASSIGN_RE, IDENT_RE, KEYWORDS,
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
        check("parse empty: lines", mod.lines == 0)
        check("parse empty: no functions", len(mod.functions) == 0)
        check("parse empty: no imports", len(mod.imports) == 0)
    finally:
        shutil.rmtree(d)


def test_parse_single_function():
    code = """function greet(name)
    msg = "Hello " + name
    return msg
"""
    path, d = make_srv(code)
    try:
        mod = parse_module(path)
        check("single fn: count", len(mod.functions) == 1)
        check("single fn: name", mod.functions[0].name == "greet")
        check("single fn: param count", mod.functions[0].param_count == 1)
        check("single fn: has return", mod.functions[0].has_return is True)
    finally:
        shutil.rmtree(d)


def test_parse_imports():
    code = """import "utils.srv"
import "helpers.srv"

function main()
    x = 1
"""
    path, d = make_srv(code)
    try:
        mod = parse_module(path)
        check("imports: count", len(mod.imports) == 2)
        check("imports: names", "utils" in mod.imports and "helpers" in mod.imports)
    finally:
        shutil.rmtree(d)


def test_parse_variables():
    code = """x = 10
y = 20

function calc()
    z = x + y
    return z
"""
    path, d = make_srv(code)
    try:
        mod = parse_module(path)
        check("vars: x defined", "x" in mod.variables_defined)
        check("vars: y defined", "y" in mod.variables_defined)
    finally:
        shutil.rmtree(d)


def test_parse_multiple_functions():
    code = """function add(a, b)
    return a + b

function sub(a, b)
    return a - b

function noop()
    x = 1
"""
    path, d = make_srv(code)
    try:
        mod = parse_module(path)
        check("multi fn: count", len(mod.functions) == 3)
        names = [f.name for f in mod.functions]
        check("multi fn: add", "add" in names)
        check("multi fn: sub", "sub" in names)
        check("multi fn: noop", "noop" in names)
    finally:
        shutil.rmtree(d)


def test_parse_fn_keyword():
    code = """fn square(x)
    return x * x
"""
    path, d = make_srv(code)
    try:
        mod = parse_module(path)
        check("fn keyword: count", len(mod.functions) == 1)
        check("fn keyword: name", mod.functions[0].name == "square")
    finally:
        shutil.rmtree(d)


def test_parse_calls():
    code = """function main()
    result = add(1, 2)
    print(result)
"""
    path, d = make_srv(code)
    try:
        mod = parse_module(path)
        check("calls: has add", "add" in mod.functions[0].calls)
    finally:
        shutil.rmtree(d)


# ── Test: E001 GDP Calculator ────────────────────────────────────────

def test_gdp_empty():
    gdp = calculate_gdp([])
    check("gdp empty: score 0", gdp.score == 0.0)
    check("gdp empty: modules 0", gdp.total_modules == 0)


def test_gdp_basic():
    code = """function producer()
    return 42

function consumer()
    x = 1
"""
    path, d = make_srv(code)
    try:
        mod = parse_module(path)
        gdp = calculate_gdp([mod])
        check("gdp basic: functions", gdp.total_functions == 2)
        check("gdp basic: productive", gdp.productive_functions == 1)
        check("gdp basic: consumption", gdp.consumption_functions == 1)
        check("gdp basic: ratio", abs(gdp.output_input_ratio - 0.5) < 0.01)
        check("gdp basic: capita", gdp.gdp_per_capita == 2.0)
        check("gdp basic: score > 0", gdp.score > 0)
    finally:
        shutil.rmtree(d)


def test_gdp_all_productive():
    code = """function a()
    return 1

function b()
    return 2

function c()
    return 3
"""
    path, d = make_srv(code)
    try:
        mod = parse_module(path)
        gdp = calculate_gdp([mod])
        check("gdp all productive: ratio 1.0", abs(gdp.output_input_ratio - 1.0) < 0.01)
        check("gdp all productive: high score", gdp.score > 50)
    finally:
        shutil.rmtree(d)


# ── Test: E002 Labor Market ──────────────────────────────────────────

def test_labor_empty():
    labor = analyze_labor_market([])
    check("labor empty: workers 0", labor.total_workers == 0)
    check("labor empty: rate 0", labor.unemployment_rate == 0.0)


def test_labor_with_calls():
    d = make_project({
        "utils.srv": """function helper()
    return 1
""",
        "main.srv": """import "utils.srv"

function main()
    x = helper()
    return x

function unused()
    y = 1
""",
    })
    try:
        mods = [parse_module(os.path.join(d, f)) for f in ["utils.srv", "main.srv"]]
        labor = analyze_labor_market(mods)
        check("labor calls: workers >= 3", labor.total_workers >= 3)
        check("labor calls: some employed", labor.employed > 0)
        check("labor calls: some unemployed", labor.unemployed > 0)
        check("labor calls: rate > 0", labor.unemployment_rate > 0)
    finally:
        shutil.rmtree(d)


def test_labor_gini():
    code = """function hot()
    return 1

function cold()
    return 2

function main()
    a = hot()
    b = hot()
    c = hot()
    d = hot()
    e = hot()
"""
    path, d = make_srv(code)
    try:
        mod = parse_module(path)
        labor = analyze_labor_market([mod])
        check("labor gini: coefficient >= 0", labor.gini_coefficient >= 0)
        check("labor gini: coefficient <= 1", labor.gini_coefficient <= 1)
    finally:
        shutil.rmtree(d)


# ── Test: E003 Trade Balance ─────────────────────────────────────────

def test_trade_empty():
    trade = analyze_trade([])
    check("trade empty: trades 0", trade.total_trades == 0)
    check("trade empty: score 0", trade.score == 0.0)


def test_trade_basic():
    d = make_project({
        "lib.srv": """function util()
    return 1
""",
        "app.srv": """import "lib.srv"

function main()
    x = util()
""",
    })
    try:
        mods = [parse_module(os.path.join(d, f)) for f in ["lib.srv", "app.srv"]]
        trade = analyze_trade(mods)
        check("trade basic: trades > 0", trade.total_trades > 0)
        check("trade basic: has balances", len(trade.balances) == 2)
    finally:
        shutil.rmtree(d)


def test_trade_autarky():
    d = make_project({
        "island1.srv": """function alone()
    return 1
""",
        "island2.srv": """function solo()
    return 2
""",
    })
    try:
        mods = [parse_module(os.path.join(d, f)) for f in ["island1.srv", "island2.srv"]]
        trade = analyze_trade(mods)
        check("trade autarky: both isolated", len(trade.autarkic_modules) == 2)
    finally:
        shutil.rmtree(d)


def test_trade_surplus_deficit():
    d = make_project({
        "exporter.srv": """function a()
    return 1

function b()
    return 2
""",
        "importer1.srv": """import "exporter.srv"

function use1()
    return a()
""",
        "importer2.srv": """import "exporter.srv"

function use2()
    return b()
""",
    })
    try:
        mods = [parse_module(os.path.join(d, f)) for f in
                ["exporter.srv", "importer1.srv", "importer2.srv"]]
        trade = analyze_trade(mods)
        check("trade surplus: exporter has surplus",
              any(s["module"] == "exporter" for s in trade.surplus_modules))
        check("trade deficit: importers have deficit",
              len(trade.deficit_modules) >= 1)
    finally:
        shutil.rmtree(d)


# ── Test: E004 Inflation Tracker ─────────────────────────────────────

def test_inflation_empty():
    inf = track_inflation([])
    check("inflation empty: score 100", inf.score == 100.0)
    check("inflation empty: cpi 0", inf.cpi == 0.0)


def test_inflation_lean_code():
    code = """function a(x)
    return x + 1

function b(y)
    return y * 2
"""
    path, d = make_srv(code)
    try:
        mod = parse_module(path)
        inf = track_inflation([mod])
        check("inflation lean: low cpi", inf.cpi < 50)
        check("inflation lean: high score", inf.score > 50)
    finally:
        shutil.rmtree(d)


def test_inflation_bloated_code():
    # Long function with many params and deep nesting
    lines = ["function bloated(a, b, c, d, e, f, g, h)"]
    for i in range(50):
        lines.append(f"    {'    ' * (i % 5)}x{i} = {i}")
    lines.append("    return x0")
    code = "\n".join(lines)
    path, d = make_srv(code)
    try:
        mod = parse_module(path)
        inf = track_inflation([mod])
        check("inflation bloated: high cpi", inf.cpi > 20)
        check("inflation bloated: param index > 0", inf.parameter_index > 0)
    finally:
        shutil.rmtree(d)


# ── Test: E005 Supply Chain ──────────────────────────────────────────

def test_supply_chain_empty():
    sc = analyze_supply_chain([])
    check("supply empty: vars 0", sc.total_variables == 0)
    check("supply empty: score 50", sc.score == 50.0)


def test_supply_chain_basic():
    code = """config = "default"

function a()
    x = config
    return x

function b()
    y = config
    return y
"""
    path, d = make_srv(code)
    try:
        mod = parse_module(path)
        sc = analyze_supply_chain([mod])
        check("supply basic: vars > 0", sc.total_variables > 0)
        check("supply basic: score > 0", sc.score > 0)
    finally:
        shutil.rmtree(d)


# ── Test: E006 Market Efficiency ─────────────────────────────────────

def test_efficiency_empty():
    eff = score_efficiency([])
    check("efficiency empty: dead 0", eff.dead_code_count == 0)
    check("efficiency empty: ratio 1.0", eff.efficiency_ratio == 1.0)
    check("efficiency empty: score 100", eff.score == 100.0)


def test_efficiency_with_dead_code():
    code = """function used()
    return 1

function dead_fn()
    return 2

function main()
    x = used()
"""
    path, d = make_srv(code)
    try:
        mod = parse_module(path)
        eff = score_efficiency([mod])
        check("efficiency dead: some dead", eff.dead_code_count >= 1)
        check("efficiency dead: ratio < 1", eff.efficiency_ratio < 1.0)
    finally:
        shutil.rmtree(d)


def test_efficiency_unused_imports():
    d = make_project({
        "lib.srv": """function util()
    return 1
""",
        "main.srv": """import "lib.srv"

function main()
    x = 1
""",
    })
    try:
        mods = [parse_module(os.path.join(d, f)) for f in ["lib.srv", "main.srv"]]
        eff = score_efficiency(mods)
        check("efficiency imports: unused >= 1", eff.unused_import_count >= 1)
    finally:
        shutil.rmtree(d)


# ── Test: E007 Insights ─────────────────────────────────────────────

def test_insights_generated():
    code = """function only_return()
    return 42

function dead1()
    x = 1

function dead2()
    y = 2

function dead3()
    z = 3

function dead4()
    w = 4
"""
    path, d = make_srv(code)
    try:
        mod = parse_module(path)
        mods = [mod]
        gdp = calculate_gdp(mods)
        labor = analyze_labor_market(mods)
        trade = analyze_trade(mods)
        inf = track_inflation(mods)
        sc = analyze_supply_chain(mods)
        eff = score_efficiency(mods)
        insights = generate_insights(gdp, labor, trade, inf, sc, eff, mods)
        check("insights: non-empty", len(insights) > 0)
        check("insights: have types", all("type" in i for i in insights))
        check("insights: have titles", all("title" in i for i in insights))
        check("insights: have descriptions", all("description" in i for i in insights))
        check("insights: have policy", all("policy" in i for i in insights))
    finally:
        shutil.rmtree(d)


def test_insights_high_unemployment():
    code = """function a()
    return 1

function b()
    return 2

function c()
    return 3
"""
    path, d = make_srv(code)
    try:
        mod = parse_module(path)
        labor = analyze_labor_market([mod])
        # All functions are "unemployed" (none call each other)
        gdp = calculate_gdp([mod])
        trade = analyze_trade([mod])
        inf = track_inflation([mod])
        sc = analyze_supply_chain([mod])
        eff = score_efficiency([mod])
        insights = generate_insights(gdp, labor, trade, inf, sc, eff, [mod])
        unemployment_insights = [i for i in insights if "Unemployment" in i.get("title", "")]
        check("insights unemployment: detected", len(unemployment_insights) > 0)
    finally:
        shutil.rmtree(d)


# ── Test: Composite Health Score ─────────────────────────────────────

def test_health_score_range():
    gdp = GDPReport(score=80)
    labor = LaborReport(score=70)
    trade = TradeReport(score=60)
    inf = InflationReport(score=90)
    sc = SupplyChainReport(score=50)
    eff = EfficiencyReport(score=75)
    score, tier, subs = compute_health_score(gdp, labor, trade, inf, sc, eff)
    check("health: 0-100", 0 <= score <= 100)
    check("health: tier is string", isinstance(tier, str))
    check("health: has sub scores", len(subs) == 6)


def test_health_tiers():
    for target_score, expected_tier in [(90, "Thriving"), (65, "Stable"),
                                         (45, "Stagnant"), (25, "Recession"),
                                         (10, "Depression")]:
        gdp = GDPReport(score=target_score)
        labor = LaborReport(score=target_score)
        trade = TradeReport(score=target_score)
        inf = InflationReport(score=target_score)
        sc = SupplyChainReport(score=target_score)
        eff = EfficiencyReport(score=target_score)
        score, tier, _ = compute_health_score(gdp, labor, trade, inf, sc, eff)
        check(f"tier {expected_tier}: correct", tier == expected_tier)


# ── Test: Full Analysis Pipeline ─────────────────────────────────────

def test_analyze_empty_dir():
    d = tempfile.mkdtemp()
    try:
        report = analyze(d)
        check("analyze empty: modules 0", report.total_modules == 0)
        check("analyze empty: has timestamp", len(report.timestamp) > 0)
    finally:
        shutil.rmtree(d)


def test_analyze_single_file():
    code = """function main()
    return 42
"""
    path, d = make_srv(code)
    try:
        report = analyze(d)
        check("analyze single: modules 1", report.total_modules == 1)
        check("analyze single: functions 1", report.total_functions == 1)
        check("analyze single: has health", 0 <= report.health_score <= 100)
        check("analyze single: has tier", report.health_tier in
              ["Thriving", "Stable", "Stagnant", "Recession", "Depression"])
    finally:
        shutil.rmtree(d)


def test_analyze_multi_file():
    d = make_project({
        "lib.srv": """function helper(x)
    return x * 2

function unused()
    y = 1
""",
        "app.srv": """import "lib.srv"

function main()
    result = helper(21)
    return result
""",
    })
    try:
        report = analyze(d)
        check("analyze multi: modules 2", report.total_modules == 2)
        check("analyze multi: functions >= 3", report.total_functions >= 3)
        check("analyze multi: has gdp", "total_functions" in report.gdp)
        check("analyze multi: has labor", "total_workers" in report.labor)
        check("analyze multi: has trade", "total_trades" in report.trade)
        check("analyze multi: has inflation", "cpi" in report.inflation)
        check("analyze multi: has supply", "total_variables" in report.supply_chain)
        check("analyze multi: has efficiency", "dead_code_count" in report.efficiency)
        check("analyze multi: has insights", len(report.insights) > 0)
    finally:
        shutil.rmtree(d)


# ── Test: Output Formatters ──────────────────────────────────────────

def test_format_text():
    d = make_project({
        "test.srv": """function a()
    return 1
""",
    })
    try:
        report = analyze(d)
        text = format_text(report)
        check("text: has GDP", "GDP" in text)
        check("text: has Labor", "Labor" in text)
        check("text: has Trade", "Trade" in text)
        check("text: has Inflation", "Inflation" in text)
        check("text: has Supply", "Supply" in text)
        check("text: has Efficiency", "Efficiency" in text)
        check("text: has Economy Health", "Economy Health" in text)
    finally:
        shutil.rmtree(d)


def test_format_json():
    d = make_project({
        "test.srv": """function a()
    return 1
""",
    })
    try:
        report = analyze(d)
        j = format_json(report)
        data = json.loads(j)
        check("json: valid", isinstance(data, dict))
        check("json: has health_score", "health_score" in data)
        check("json: has gdp", "gdp" in data)
        check("json: has insights", "insights" in data)
    finally:
        shutil.rmtree(d)


def test_generate_html():
    d = make_project({
        "test.srv": """function a()
    return 1

function b()
    x = a()
""",
    })
    try:
        report = analyze(d)
        html = generate_html(report)
        check("html: has DOCTYPE", "<!DOCTYPE html>" in html)
        check("html: has sauraveconomy", "sauraveconomy" in html)
        check("html: has tabs", "showTab" in html)
        check("html: has GDP tab", "tab-gdp" in html)
        check("html: has Labor tab", "tab-labor" in html)
        check("html: has Trade tab", "tab-trade" in html)
        check("html: has Inflation tab", "tab-inflation" in html)
        check("html: has Supply tab", "tab-supply" in html)
        check("html: has Insights tab", "tab-insights" in html)
        check("html: has REPORT_DATA", "REPORT_DATA" in html)
        check("html: has score", str(int(report.health_score)) in html)
    finally:
        shutil.rmtree(d)


# ── Test: Regex patterns ────────────────────────────────────────────

def test_regex_func_def():
    check("regex: function match", FUNC_DEF_RE.match("function foo(x)") is not None)
    check("regex: fn match", FUNC_DEF_RE.match("fn bar()") is not None)
    check("regex: indented fn", FUNC_DEF_RE.match("  function nested()") is not None)
    check("regex: no match", FUNC_DEF_RE.match("x = function") is None)


def test_regex_import():
    check("regex: import match", IMPORT_RE.match('import "foo.srv"') is not None)
    check("regex: import path", IMPORT_RE.match('import "path/to/bar.srv"').group(1) == "path/to/bar.srv")


def test_regex_assign():
    check("regex: assign match", ASSIGN_RE.match("  x = 10") is not None)
    check("regex: assign name", ASSIGN_RE.match("  myVar = 42").group(1) == "myVar")


def test_keywords():
    check("keywords: if", "if" in KEYWORDS)
    check("keywords: function", "function" in KEYWORDS)
    check("keywords: not foo", "foo" not in KEYWORDS)


# ── Test: Edge Cases ─────────────────────────────────────────────────

def test_comments_ignored():
    code = """# This is a comment
// Another comment
function real()
    return 1
"""
    path, d = make_srv(code)
    try:
        mod = parse_module(path)
        check("comments: code_lines < lines", mod.code_lines < mod.lines)
        check("comments: function found", len(mod.functions) == 1)
    finally:
        shutil.rmtree(d)


def test_no_return_functions():
    code = """function sideeffect()
    print("hello")

function another()
    x = 42
"""
    path, d = make_srv(code)
    try:
        mod = parse_module(path)
        gdp = calculate_gdp([mod])
        check("no return: productive 0", gdp.productive_functions == 0)
        check("no return: consumption 2", gdp.consumption_functions == 2)
    finally:
        shutil.rmtree(d)


def test_single_function_codebase():
    code = """function lonely()
    return 1
"""
    path, d = make_srv(code)
    try:
        report = analyze(d)
        check("single fn: health valid", 0 <= report.health_score <= 100)
        check("single fn: tier valid", report.health_tier in
              ["Thriving", "Stable", "Stagnant", "Recession", "Depression"])
    finally:
        shutil.rmtree(d)


# ── Run ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Testing sauraveconomy...")
    print("")

    test_parse_empty_file()
    test_parse_single_function()
    test_parse_imports()
    test_parse_variables()
    test_parse_multiple_functions()
    test_parse_fn_keyword()
    test_parse_calls()

    test_gdp_empty()
    test_gdp_basic()
    test_gdp_all_productive()

    test_labor_empty()
    test_labor_with_calls()
    test_labor_gini()

    test_trade_empty()
    test_trade_basic()
    test_trade_autarky()
    test_trade_surplus_deficit()

    test_inflation_empty()
    test_inflation_lean_code()
    test_inflation_bloated_code()

    test_supply_chain_empty()
    test_supply_chain_basic()

    test_efficiency_empty()
    test_efficiency_with_dead_code()
    test_efficiency_unused_imports()

    test_insights_generated()
    test_insights_high_unemployment()

    test_health_score_range()
    test_health_tiers()

    test_analyze_empty_dir()
    test_analyze_single_file()
    test_analyze_multi_file()

    test_format_text()
    test_format_json()
    test_generate_html()

    test_regex_func_def()
    test_regex_import()
    test_regex_assign()
    test_keywords()

    test_comments_ignored()
    test_no_return_functions()
    test_single_function_codebase()

    print("")
    print(f"  {PASS} passed, {FAIL} failed, {PASS + FAIL} total")
    if FAIL:
        sys.exit(1)
    else:
        print("  All tests passed!")
        sys.exit(0)
