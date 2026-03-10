#!/usr/bin/env python3
"""Tests for sauravstats.py"""

import os
import sys
import json
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import sauravstats as ss

_pass = 0
_fail = 0

def check(label, condition):
    global _pass, _fail
    if condition:
        _pass += 1
    else:
        _fail += 1
        print(f"  FAIL: {label}")

def make_file(d, name, content):
    p = os.path.join(d, name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w') as f:
        f.write(content)
    return p

SAMPLE = """\
# A sample program
import "utils"

function greet(name)
    if name == "World"
        print("Hello, World!")
    else
        print("Hello, " + name)

function add(a, b)
    return a + b

class Animal
    function init(name)
        self.name = name

enum Color
    Red
    Blue

for i in range(10)
    x = add(i, 1)

while x > 0
    x = x - 1

lambda x -> x * 2

try:
    result = add(1, 2)
catch e
    print(e)

assert add(1, 2) == 3
"""

SIMPLE = "print(\"hello\")\n"
EMPTY = ""

COMPLEX = """\
function outer()
    function inner()
        for i in range(10)
            if i > 5
                if i > 8
                    while true
                        break
    for j in range(5)
        match j
            case 1
                print(1)
            case 2
                print(2)
    try:
        throw "err"
    catch e
        print(e)

function gen()
    yield 1
    yield 2
    return
"""

# -- FileMetrics --
print("FileMetrics analysis...")
with tempfile.TemporaryDirectory() as td:
    fp = make_file(td, 'sample.srv', SAMPLE)
    fm = ss.analyze_file(fp, td)
    check("total_lines > 0", fm.total_lines > 0)
    check("code_lines > 0", fm.code_lines > 0)
    check("comment_lines == 1", fm.comment_lines == 1)
    check("functions == 3", fm.functions == 3)
    check("classes == 1", fm.classes == 1)
    check("enums == 1", fm.enums == 1)
    check("imports == 1", fm.imports == 1)
    check("loops >= 2", fm.loops >= 2)
    check("branches >= 1", fm.branches >= 1)
    check("lambdas == 1", fm.lambdas == 1)
    check("try_catches >= 1", fm.try_catches >= 1)
    check("asserts == 1", fm.asserts == 1)
    check("returns == 1", fm.returns == 1)
    check("prints >= 1", fm.prints >= 1)
    check("function_names has greet", 'greet' in fm.function_names)
    check("class_names has Animal", 'Animal' in fm.class_names)
    check("enum_names has Color", 'Color' in fm.enum_names)
    check("comment_ratio > 0", fm.comment_ratio > 0)
    check("code_ratio > 0", fm.code_ratio > 0)
    check("to_dict has path", 'path' in fm.to_dict())
    check("complexity_score > 0", fm.complexity_score > 0)

print("Empty file...")
with tempfile.TemporaryDirectory() as td:
    fp = make_file(td, 'empty.srv', EMPTY)
    fm = ss.analyze_file(fp, td)
    check("empty total_lines == 0", fm.total_lines == 0)
    check("empty code_lines == 0", fm.code_lines == 0)
    check("empty complexity == 0", fm.complexity_score == 0)

print("Simple file...")
with tempfile.TemporaryDirectory() as td:
    fp = make_file(td, 'simple.srv', SIMPLE)
    fm = ss.analyze_file(fp, td)
    check("simple has 1 line", fm.total_lines == 1)
    check("simple prints == 1", fm.prints == 1)

print("Complex file...")
with tempfile.TemporaryDirectory() as td:
    fp = make_file(td, 'complex.srv', COMPLEX)
    fm = ss.analyze_file(fp, td)
    check("nested_functions >= 1", fm.nested_functions >= 1)
    check("yields >= 2", fm.yields >= 2)
    check("throws >= 1", fm.throws >= 1)
    check("match_cases >= 1", fm.match_cases >= 1)
    check("max_depth > 0", fm.max_depth > 0)
    check("max_func_length > 0", fm.max_func_length > 0)
    check("complexity > 5", fm.complexity_score > 5)

print("Directory scanning...")
with tempfile.TemporaryDirectory() as td:
    make_file(td, 'a.srv', SAMPLE)
    make_file(td, 'sub/b.srv', SIMPLE)
    make_file(td, 'readme.txt', 'not srv')
    make_file(td, '.hidden/c.srv', 'hidden')
    files = ss.find_srv_files(td)
    check("finds 2 srv files", len(files) == 2)
    metrics = ss.analyze_path(td)
    check("analyze_path returns 2", len(metrics) == 2)

print("ProjectSummary...")
with tempfile.TemporaryDirectory() as td:
    make_file(td, 'a.srv', SAMPLE)
    make_file(td, 'b.srv', COMPLEX)
    metrics = ss.analyze_path(td)
    summary = ss.ProjectSummary(metrics)
    check("file_count == 2", summary.file_count == 2)
    check("total_lines > 0", summary.total_lines > 0)
    check("functions > 0", summary.functions > 0)
    check("health_score <= 100", summary.health_score <= 100)
    check("health_score >= 0", summary.health_score >= 0)
    check("health_grade in ABCDF", summary.health_grade in 'ABCDF')
    check("to_dict has health_score", 'health_score' in summary.to_dict())
    check("avg_complexity > 0", summary.avg_complexity > 0)

print("Hotspot detection...")
with tempfile.TemporaryDirectory() as td:
    make_file(td, 'simple.srv', SIMPLE)
    make_file(td, 'complex.srv', COMPLEX)
    metrics = ss.analyze_path(td)
    hotspots = ss.find_hotspots(metrics)
    check("complex is a hotspot", any('complex' in h.rel_path for h in hotspots))

print("Treemap rendering...")
with tempfile.TemporaryDirectory() as td:
    make_file(td, 'a.srv', SAMPLE)
    make_file(td, 'b.srv', SIMPLE)
    metrics = ss.analyze_path(td)
    tree = ss.render_treemap(metrics)
    check("treemap has LOC", 'LOC' in tree)
    check("treemap has bars", '#' in tree)
check("treemap empty list", 'No files' in ss.render_treemap([]))

print("History comparison...")
with tempfile.TemporaryDirectory() as td:
    make_file(td, 'a.srv', SAMPLE)
    metrics = ss.analyze_path(td)
    s1 = ss.ProjectSummary(metrics)
    ss.save_snapshot(s1, td)
    prev = ss.load_previous(td)
    check("snapshot saved", prev is not None)
    check("snapshot has timestamp", 'timestamp' in prev)
    diffs = ss.compare_snapshots(s1.to_dict(), prev)
    check("no changes = None", diffs is None)
    fake_prev = s1.to_dict()
    fake_prev['code_lines'] = 0
    diffs2 = ss.compare_snapshots(s1.to_dict(), fake_prev)
    check("change detected", diffs2 is not None)
    check("code_lines changed", 'code_lines' in diffs2)

print("Badge generation...")
with tempfile.TemporaryDirectory() as td:
    make_file(td, 'a.srv', SAMPLE)
    metrics = ss.analyze_path(td)
    summary = ss.ProjectSummary(metrics)
    badge = ss.generate_badge(summary)
    check("badge has Health", 'Health' in badge)
    check("badge has /100", '/100' in badge)

print("JSON output...")
with tempfile.TemporaryDirectory() as td:
    make_file(td, 'a.srv', SAMPLE)
    metrics = ss.analyze_path(td)
    summary = ss.ProjectSummary(metrics)
    class Args: summary = False; sort = 'loc'; top = None
    out = ss.format_json(metrics, summary, Args())
    parsed = json.loads(out)
    check("json has summary", 'summary' in parsed)
    check("json has files", 'files' in parsed)
    check("json has grade", 'summary_grade' in parsed)
    Args.summary = True
    out2 = ss.format_json(metrics, summary, Args())
    parsed2 = json.loads(out2)
    check("json summary-only no files", 'files' not in parsed2)

print("CSV output...")
with tempfile.TemporaryDirectory() as td:
    make_file(td, 'a.srv', SAMPLE)
    make_file(td, 'b.srv', COMPLEX)
    metrics = ss.analyze_path(td)
    summary = ss.ProjectSummary(metrics)
    class Args2: summary = False; sort = 'loc'; top = None
    out = ss.format_csv(metrics, summary, Args2())
    lines = out.strip().split('\n')
    check("csv header + 2 rows", len(lines) == 3)
    check("csv has file column", 'file' in lines[0])

print("Text output...")
with tempfile.TemporaryDirectory() as td:
    make_file(td, 'a.srv', SAMPLE)
    metrics = ss.analyze_path(td)
    summary = ss.ProjectSummary(metrics)
    class Args3: summary = False; sort = 'loc'; top = None
    out = ss.format_text(metrics, summary, Args3())
    check("text has Project Summary", 'Project Summary' in out)
    check("text has File header", 'File' in out)
    check("text has Health", 'Health' in out)

print("Sort options...")
check("sort keys >= 6", len(ss.SORT_KEYS) >= 6)
check("loc sort key", 'loc' in ss.SORT_KEYS)
check("complexity sort key", 'complexity' in ss.SORT_KEYS)

print("Hotspot formatting...")
with tempfile.TemporaryDirectory() as td:
    make_file(td, 'a.srv', SIMPLE)
    metrics = ss.analyze_path(td)
    summary = ss.ProjectSummary(metrics)
    class Args4: summary = False; sort = 'loc'; top = None
    out = ss.format_hotspots(metrics, summary, Args4())
    check("clean or hotspot msg", 'clean' in out.lower() or 'hotspot' in out.lower())

print("CLI main...")
with tempfile.TemporaryDirectory() as td:
    make_file(td, 'a.srv', SAMPLE)
    check("main ok", ss.main([td]) == 0)
    check("main --json", ss.main([td, '--json']) == 0)
    check("main --csv", ss.main([td, '--csv']) == 0)
    check("main --hotspots", ss.main([td, '--hotspots']) == 0)
    check("main --summary", ss.main([td, '--summary']) == 0)
    check("main --treemap", ss.main([td, '--treemap']) == 0)
    check("main --badge", ss.main([td, '--badge']) == 0)
    check("main --history", ss.main([td, '--history']) == 0)
    check("main nonexistent", ss.main([os.path.join(td, 'nope')]) == 1)

print("Edge cases...")
check("indent spaces", ss._indent_level('    hello') == 4)
check("indent tabs", ss._indent_level('\thello') == 4)
check("indent mixed", ss._indent_level('\t  hello') == 6)
check("indent none", ss._indent_level('hello') == 0)
check("delta +", ss._delta_str(5) == '+5')
check("delta -", ss._delta_str(-3) == '-3')
check("delta 0", ss._delta_str(0) == '0')

with tempfile.TemporaryDirectory() as td:
    make_file(td, 'readme.txt', 'hello')
    check("no srv returns 1", ss.main([td]) == 1)

with tempfile.TemporaryDirectory() as td:
    fp = make_file(td, 'test.srv', SAMPLE)
    check("single file mode", len(ss.find_srv_files(fp)) == 1)
    fp2 = make_file(td, 'test.txt', 'nope')
    check("non-srv empty", len(ss.find_srv_files(fp2)) == 0)

check("load_previous nonexistent", ss.load_previous('/tmp/nonexistent_xyz') is None)
check("compare with None", ss.compare_snapshots({}, None) is None)

print("Health score edges...")
with tempfile.TemporaryDirectory() as td:
    make_file(td, 'big.srv', "function big()\n" + "    x = 1\n" * 120)
    metrics = ss.analyze_path(td)
    s = ss.ProjectSummary(metrics)
    check("low comment penalized", s.health_score < 100)

s_empty = ss.ProjectSummary([])
check("empty summary file_count 0", s_empty.file_count == 0)
check("empty summary health <= 100", s_empty.health_score <= 100)

print(f"\n{'='*40}")
print(f"  Results: {_pass} passed, {_fail} failed")
print(f"{'='*40}")
sys.exit(1 if _fail else 0)
