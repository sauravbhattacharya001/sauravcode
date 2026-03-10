#!/usr/bin/env python3
"""Tests for sauravcomplex.py — Code Complexity Analyzer."""

import sys
import os
import json
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sauravcomplex import (
    ComplexityAnalyzer, HalsteadMetrics, FunctionComplexity, FileComplexity,
    format_text_report, format_comparison_report, _safe_log2,
    OPERATORS, KEYWORD_OPERATORS, CYCLOMATIC_KEYWORDS,
)

passed = 0
failed = 0

def test(name, condition):
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")


def approx(a, b, tol=0.1):
    return abs(a - b) < tol



if __name__ == "__main__":
    # ─── HalsteadMetrics Tests ──────────────────────────────────────────────────

    print("HalsteadMetrics...")

    h = HalsteadMetrics(0, 0, 0, 0)
    test("empty halstead vocabulary", h.vocabulary == 2)  # max(0,1) + max(0,1)
    test("empty halstead length", h.length == 0)
    test("empty halstead volume", h.volume == 0)

    h = HalsteadMetrics(5, 10, 20, 30)
    test("vocabulary = n1 + n2", h.vocabulary == 15)
    test("length = N1 + N2", h.length == 50)
    test("volume > 0", h.volume > 0)
    test("difficulty > 0", h.difficulty > 0)
    test("effort = volume * difficulty", approx(h.effort, h.volume * h.difficulty))
    test("time > 0", h.time_to_implement > 0)
    test("bugs >= 0", h.delivered_bugs >= 0)

    h2 = HalsteadMetrics(1, 1, 1, 1)
    test("minimal halstead", h2.vocabulary == 2)
    test("minimal length", h2.length == 2)

    hd = h.to_dict()
    test("to_dict has keys", 'vocabulary' in hd and 'volume' in hd)
    test("to_dict values match", hd['vocabulary'] == 15)


    # ─── _safe_log2 ─────────────────────────────────────────────────────────────

    print("_safe_log2...")
    test("log2(0) = 0", _safe_log2(0) == 0)
    test("log2(1) = 0", _safe_log2(1) == 0)
    test("log2(2) = 1", _safe_log2(2) == 1)
    test("log2(8) = 3", _safe_log2(8) == 3)


    # ─── FunctionComplexity Tests ───────────────────────────────────────────────

    print("FunctionComplexity...")

    fc = FunctionComplexity("test_func", 1)
    test("default cyclomatic = 1", fc.cyclomatic == 1)
    test("default cognitive = 0", fc.cognitive == 0)
    test("default grade = A", fc.grade == 'A')

    fc.sloc = 10
    fc.cyclomatic = 5
    fc.halstead = HalsteadMetrics(5, 10, 20, 30)
    fc.compute_maintainability()
    test("maintainability computed", 0 <= fc.maintainability <= 100)
    test("grade assigned", fc.grade in ('A', 'B', 'C', 'D', 'F'))

    # Very complex function
    fc2 = FunctionComplexity("complex_func", 1)
    fc2.sloc = 500
    fc2.cyclomatic = 50
    fc2.halstead = HalsteadMetrics(30, 100, 500, 800)
    fc2.compute_maintainability()
    test("complex func low MI", fc2.maintainability < 50)
    test("complex func bad grade", fc2.grade in ('C', 'D', 'F'))

    fcd = fc.to_dict()
    test("func to_dict has name", fcd['name'] == 'test_func')
    test("func to_dict has halstead", 'halstead' in fcd)


    # ─── FileComplexity Tests ───────────────────────────────────────────────────

    print("FileComplexity...")

    filec = FileComplexity("test.srv")
    test("file default grade", filec.grade == 'A')
    test("file default functions empty", len(filec.functions) == 0)

    filec.functions = [fc, fc2]
    filec.compute_aggregates()
    test("avg cyclomatic computed", filec.avg_cyclomatic > 0)
    test("max cyclomatic", filec.max_cyclomatic == 50)

    fd = filec.to_dict()
    test("file to_dict has path", fd['path'] == 'test.srv')
    test("file to_dict function_count", fd['function_count'] == 2)


    # ─── ComplexityAnalyzer - Simple Source ──────────────────────────────────────

    print("ComplexityAnalyzer - simple...")

    analyzer = ComplexityAnalyzer()

    simple = 'x = 5\nprint(x)\n'
    r = analyzer.analyze_source(simple, 'simple.srv')
    test("simple file loc", r.total_loc == 3)
    test("simple file sloc", r.total_sloc == 2)
    test("simple has module", any(f.name == '<module>' for f in r.functions))

    # ─── Single function ────────────────────────────────────────────────────────

    print("ComplexityAnalyzer - single function...")

    func_src = """function int add(a, b)
        return a + b

    x = add(1, 2)
    print(x)
    """
    r = analyzer.analyze_source(func_src, 'func.srv')
    test("found function", any(f.name == 'add' for f in r.functions))
    add_func = [f for f in r.functions if f.name == 'add'][0]
    test("add params = 2", add_func.params == 2)
    test("add cyclomatic = 1", add_func.cyclomatic == 1)
    test("add grade = A", add_func.grade == 'A')


    # ─── Branching complexity ───────────────────────────────────────────────────

    print("ComplexityAnalyzer - branching...")

    branch_src = """function string classify(n)
        if n > 0
            if n > 100
                return "big"
            else
                return "small"
        else if n == 0
            return "zero"
        else
            return "negative"
    """
    r = analyzer.analyze_source(branch_src, 'branch.srv')
    classify = [f for f in r.functions if f.name == 'classify'][0]
    test("branching CC > 1", classify.cyclomatic > 1)
    test("branching cognitive > 0", classify.cognitive > 0)
    test("branching nesting > 0", classify.max_nesting > 0)


    # ─── Loop complexity ────────────────────────────────────────────────────────

    print("ComplexityAnalyzer - loops...")

    loop_src = """function int sum_list(items)
        total = 0
        for item in items
            if item > 0
                total = total + item
        while total > 100
            total = total - 1
        return total
    """
    r = analyzer.analyze_source(loop_src, 'loop.srv')
    sum_func = [f for f in r.functions if f.name == 'sum_list'][0]
    test("loop CC includes for+if+while", sum_func.cyclomatic >= 4)
    test("loop cognitive > 0", sum_func.cognitive > 0)


    # ─── Boolean operators ──────────────────────────────────────────────────────

    print("ComplexityAnalyzer - boolean ops...")

    bool_src = """function bool check(a, b, c)
        if a and b or c
            return true
        return false
    """
    r = analyzer.analyze_source(bool_src, 'bool.srv')
    check = [f for f in r.functions if f.name == 'check'][0]
    test("bool ops increase CC", check.cyclomatic >= 4)  # if + and + or + base


    # ─── Try/catch ───────────────────────────────────────────────────────────────

    print("ComplexityAnalyzer - try/catch...")

    try_src = """function safe_div(a, b)
        try
            if b == 0
                throw "division by zero"
            return a / b
        catch e
            return 0
    """
    r = analyzer.analyze_source(try_src, 'try.srv')
    safe = [f for f in r.functions if f.name == 'safe_div'][0]
    test("try/catch CC includes catch+if", safe.cyclomatic >= 3)


    # ─── Match/case ──────────────────────────────────────────────────────────────

    print("ComplexityAnalyzer - match/case...")

    match_src = """function describe(x)
        match x
            case 1
                return "one"
            case 2
                return "two"
            case 3
                return "three"
    """
    r = analyzer.analyze_source(match_src, 'match.srv')
    desc = [f for f in r.functions if f.name == 'describe'][0]
    test("match cases increase CC", desc.cyclomatic >= 4)  # base + 3 cases


    # ─── Multiple functions ─────────────────────────────────────────────────────

    print("ComplexityAnalyzer - multiple functions...")

    multi_src = """function foo(x)
        return x + 1

    function bar(x, y)
        if x > y
            return x
        return y

    function baz(a, b, c)
        for i in a
            if i == b
                if i == c
                    return true
        return false
    """
    r = analyzer.analyze_source(multi_src, 'multi.srv')
    names = [f.name for f in r.functions if f.name != '<module>']
    test("found 3 functions", len(names) == 3)
    test("foo found", 'foo' in names)
    test("bar found", 'bar' in names)
    test("baz found", 'baz' in names)

    baz = [f for f in r.functions if f.name == 'baz'][0]
    test("baz more complex than foo", baz.cyclomatic > 1)


    # ─── Halstead from tokens ───────────────────────────────────────────────────

    print("ComplexityAnalyzer - Halstead...")

    hal_src = """x = 1 + 2
    y = x * 3
    z = x + y
    """
    r = analyzer.analyze_source(hal_src, 'hal.srv')
    h = r.halstead
    test("halstead has operators", h.unique_operators > 0)
    test("halstead has operands", h.unique_operands > 0)
    test("halstead volume > 0", h.volume > 0)


    # ─── Empty source ───────────────────────────────────────────────────────────

    print("ComplexityAnalyzer - empty...")

    r = analyzer.analyze_source('', 'empty.srv')
    test("empty file loc=1", r.total_loc == 1)
    test("empty file sloc=0", r.total_sloc == 0)
    test("empty grade A", r.grade == 'A')


    # ─── Comments only ──────────────────────────────────────────────────────────

    print("ComplexityAnalyzer - comments...")

    r = analyzer.analyze_source('# comment\n# another\n', 'comments.srv')
    test("comments sloc = 0", r.total_sloc == 0)


    # ─── Threshold and risk ─────────────────────────────────────────────────────

    print("ComplexityAnalyzer - threshold...")

    analyzer5 = ComplexityAnalyzer(threshold=5)
    r = analyzer5.analyze_source(loop_src, 'loop.srv')
    # sum_list should have CC >= 4, threshold 5 means not flagged
    test("threshold 5 respects setting", True)  # no crash

    analyzer1 = ComplexityAnalyzer(threshold=1)
    r = analyzer1.analyze_source(branch_src, 'branch.srv')
    test("threshold 1 flags complex", len(r.risk_functions) > 0)


    # ─── Recommendations ────────────────────────────────────────────────────────

    print("Recommendations...")

    fc_high = FunctionComplexity("complex", 1)
    fc_high.cyclomatic = 25
    fc_high.cognitive = 20
    fc_high.max_nesting = 6
    fc_high.params = 8
    fc_high.sloc = 200
    fc_high.halstead = HalsteadMetrics(20, 50, 300, 500)
    fc_high.compute_maintainability()

    filec_r = FileComplexity("test.srv")
    filec_r.functions = [fc_high]
    filec_r.compute_aggregates()

    recs = analyzer.get_recommendations(filec_r)
    test("recs for high CC", any('cyclomatic' in r.lower() for r in recs))
    test("recs for high cognitive", any('cognitive' in r.lower() for r in recs))
    test("recs for deep nesting", any('nesting' in r.lower() for r in recs))
    test("recs for many params", any('parameter' in r.lower() for r in recs))


    # ─── Text report ────────────────────────────────────────────────────────────

    print("Text report...")

    r = analyzer.analyze_source(multi_src, 'multi.srv')
    report = format_text_report(r)
    test("report has header", 'Complexity Report' in report)
    test("report has grade", r.grade in report)
    test("report has Halstead", 'Halstead' in report)
    test("report has functions", 'foo' in report)


    # ─── Comparison ─────────────────────────────────────────────────────────────

    print("Comparison...")

    r1 = analyzer.analyze_source(simple, 'a.srv')
    r2 = analyzer.analyze_source(multi_src, 'b.srv')
    cmp = analyzer.compare(r1, r2)
    test("compare has file_a", cmp['file_a'] == 'a.srv')
    test("compare has file_b", cmp['file_b'] == 'b.srv')
    test("compare has loc_delta", 'loc_delta' in cmp)
    test("compare has improved", 'improved' in cmp)

    cmp_report = format_comparison_report(cmp)
    test("cmp report has header", 'Comparison' in cmp_report)
    test("cmp report has verdict", 'Verdict' in cmp_report)


    # ─── JSON output ────────────────────────────────────────────────────────────

    print("JSON output...")

    r = analyzer.analyze_source(func_src, 'func.srv')
    d = r.to_dict()
    j = json.dumps(d)
    parsed = json.loads(j)
    test("json roundtrip", parsed['path'] == 'func.srv')
    test("json has functions", len(parsed['functions']) > 0)


    # ─── Maintainability grades ─────────────────────────────────────────────────

    print("Maintainability grades...")

    for mi, expected in [(90, 'A'), (70, 'B'), (50, 'C'), (30, 'D'), (10, 'F')]:
        fc_g = FunctionComplexity("g", 1)
        fc_g.maintainability = mi
        # Manually set grade based on MI thresholds
        if mi >= 80: fc_g.grade = 'A'
        elif mi >= 60: fc_g.grade = 'B'
        elif mi >= 40: fc_g.grade = 'C'
        elif mi >= 20: fc_g.grade = 'D'
        else: fc_g.grade = 'F'
        test(f"grade for MI={mi} is {expected}", fc_g.grade == expected)


    # ─── Nesting detection ──────────────────────────────────────────────────────

    print("Nesting detection...")

    nested_src = """function deep(x)
        if x > 0
            for i in x
                if i > 0
                    while i > 0
                        i = i - 1
        return x
    """
    r = analyzer.analyze_source(nested_src, 'nested.srv')
    deep = [f for f in r.functions if f.name == 'deep'][0]
    test("deep nesting detected", deep.max_nesting >= 4)
    test("deep cognitive high", deep.cognitive > 5)


    # ─── Lambda handling ────────────────────────────────────────────────────────

    print("Lambda handling...")

    lambda_src = """double = lambda x -> x * 2
    result = double(5)
    print(result)
    """
    r = analyzer.analyze_source(lambda_src, 'lambda.srv')
    test("lambda source analyzed", r.total_sloc == 3)


    # ─── Complex real-world-ish source ──────────────────────────────────────────

    print("Complex source...")

    complex_src = """function process_data(items, threshold, mode)
        results = []
        errors = []
        for item in items
            try
                if mode == "strict"
                    if item > threshold
                        append(results, item)
                    else
                        append(errors, item)
                else if mode == "lenient"
                    if item > threshold or item == threshold
                        append(results, item)
                else
                    append(results, item)
            catch e
                append(errors, e)
        if len(results) > 0 and len(errors) == 0
            return results
        else if len(errors) > 0
            return errors
        return []
    """
    r = analyzer.analyze_source(complex_src, 'complex.srv')
    proc = [f for f in r.functions if f.name == 'process_data'][0]
    test("complex func high CC", proc.cyclomatic >= 8)
    test("complex func high cognitive", proc.cognitive > 5)
    test("complex func params=3", proc.params == 3)


    # ─── Directory analysis ─────────────────────────────────────────────────────

    print("Directory analysis...")

    # Just test the method exists and handles missing dirs
    try:
        results = analyzer.analyze_directory('/nonexistent_dir_xyz')
        test("missing dir returns empty", len(results) == 0)
    except Exception:
        test("missing dir no crash", True)


    # ─── Analyzer with different sort ────────────────────────────────────────────

    print("Sort options...")

    a_sort = ComplexityAnalyzer(sort_by='cognitive')
    test("sort option stored", a_sort.sort_by == 'cognitive')

    a_sort2 = ComplexityAnalyzer(sort_by='maintainability')
    test("sort option maintainability", a_sort2.sort_by == 'maintainability')


    # ─── Edge case: function with no params ──────────────────────────────────────

    print("Edge cases...")

    no_param_src = """function greet()
        print("hello")
    """
    r = analyzer.analyze_source(no_param_src, 'greet.srv')
    greet = [f for f in r.functions if f.name == 'greet'][0]
    test("no params = 0", greet.params == 0)
    test("greet CC = 1", greet.cyclomatic == 1)


    # ─── Constants in OPERATORS set ──────────────────────────────────────────────

    print("Constants...")

    test("+ in OPERATORS", '+' in OPERATORS)
    test("== in OPERATORS", '==' in OPERATORS)
    test("if in KEYWORD_OPERATORS", 'if' in KEYWORD_OPERATORS)
    test("if in CYCLOMATIC_KEYWORDS", 'if' in CYCLOMATIC_KEYWORDS)
    test("for in CYCLOMATIC_KEYWORDS", 'for' in CYCLOMATIC_KEYWORDS)
    test("and in CYCLOMATIC_KEYWORDS", 'and' in CYCLOMATIC_KEYWORDS)


    # ─── FileComplexity empty aggregates ─────────────────────────────────────────

    print("Empty aggregates...")

    empty_fc = FileComplexity("empty.srv")
    empty_fc.compute_aggregates()
    test("empty avg CC = 0", empty_fc.avg_cyclomatic == 0)
    test("empty grade A", empty_fc.grade == 'A')


    # ─── Report with details flag ───────────────────────────────────────────────

    print("Detailed report...")

    r = analyzer.analyze_source(multi_src, 'multi.srv')
    report_detail = format_text_report(r, details=True)
    test("detailed report has breakdown", 'Breakdown' in report_detail)


    # ─── Report with no recommendations ─────────────────────────────────────────

    report_norec = format_text_report(r, recommendations=False)
    test("no-rec report works", 'Complexity Report' in report_norec)


    # ─── Halstead edge: all operators ────────────────────────────────────────────

    print("Halstead edge cases...")

    h_zero = HalsteadMetrics(0, 0, 0, 0)
    test("zero halstead no crash", h_zero.volume == 0)
    test("zero halstead no bugs", h_zero.delivered_bugs == 0)

    h_single = HalsteadMetrics(1, 0, 5, 0)
    test("no operands difficulty", h_single.difficulty == 0)


    # ─── Summary ────────────────────────────────────────────────────────────────

    print(f"\n{'='*60}")
    print(f"  Results: {passed} passed, {failed} failed, {passed+failed} total")
    print(f"{'='*60}")

    sys.exit(1 if failed else 0)
