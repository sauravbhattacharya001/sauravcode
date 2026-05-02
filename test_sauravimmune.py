#!/usr/bin/env python3
"""Tests for sauravimmune — autonomous code immune system."""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from io import StringIO

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sauravimmune import (
    FuncInfo, Pathogen, Antibody, ImmuneMemoryEntry, AutoimmuneIssue, ImmuneReport,
    _parse_functions, _scan_pathogens, _generate_antibodies, _load_memory,
    _save_memory, _update_memory, _run_vaccinations, _detect_autoimmune,
    _compute_immune_score, _score_tier, _generate_insights, _generate_html,
    analyze_immune, _reset_pathogen_counter, main, MEMORY_FILE
)


def _write_srv(tmpdir, name, content):
    path = os.path.join(tmpdir, name)
    with open(path, 'w') as f:
        f.write(content)
    return path


# ── Test .srv Content ─────────────────────────────────────────────────

SIMPLE_SRV = """\
function greet name
    print "Hello " + name

function add a b
    return a + b
"""

GOD_FUNCTION_SRV = """\
function monster data x y z
    if data
        for item in data
            if item > 0
                while item > 10
                    item = item - 1
                    if item == 5
                        print "a"
                    elif item == 3
                        print "b"
                    elif item == 1
                        print "c"
            elif item < 0
                for x in range(10)
                    if x > 5
                        print x
                    elif x > 3
                        print x
    if x
        for j in range(x)
            if j > 0
                while j > 5
                    j = j - 1
                    if j == 2
                        print "d"
    if y
        for k in range(y)
            if k > 0
                if k < 10
                    print k
    if z
        for m in range(z)
            if m > 0
                if m < 10
                    print m
    print "line1"
    print "line2"
    print "line3"
    print "line4"
    print "line5"
    print "line6"
    print "line7"
    print "line8"
    print "line9"
    print "line10"
    print "line11"
    print "line12"
    print "line13"
    print "line14"
    print "line15"
    print "line16"
    print "line17"
    print "line18"
    print "line19"
    print "line20"
    return data
"""

DEAD_PARAM_SRV = """\
function process a b c
    print a
    return a + 1
"""

MAGIC_NUMBER_SRV = """\
function calculate x
    result = x * 42
    offset = result + 137
    return offset
"""

DEEP_NESTING_SRV = """\
function deeply_nested x
    if x
        if x > 0
            if x > 1
                if x > 2
                    if x > 3
                        if x > 4
                            print "deep"
"""

MISSING_ERROR_SRV = """\
function risky_read path
    data = open(path)
    content = read(data)
    return content
"""

ORPHAN_SRV = """\
function used_function x
    return x + 1

function caller
    result = used_function(5)
    return result

function lonely_orphan
    return 42
"""

OVERLOADED_SRV = """\
function too_many a b c d e f g
    return a + b + c + d + e + f + g
"""

NAMING_SRV = """\
function bad_names x
    a = x + 1
    b = a + 2
    return b
"""

RECURSION_SRV = """\
function recurse_bad n
    result = recurse_bad(n - 1)
    return result

function recurse_good n
    if n <= 0
        return 1
    return recurse_good(n - 1)
"""

AUTOIMMUNE_OVER_VALIDATE_SRV = """\
function over_check x
    if x > 0
        print "positive"
    if x > 0
        print "still positive"
    if x > 0
        print "yes positive"
"""

AUTOIMMUNE_EXCESSIVE_CATCH_SRV = """\
function catch_happy x
    try
        catch
            print "err1"
        catch
            print "err2"
        catch
            print "err3"
        catch
            print "err4"
    return x
"""

AUTOIMMUNE_REDUNDANT_SRV = """\
function tautology x
    if true
        return x
"""

AUTOIMMUNE_OVER_ABSTRACT_SRV = """\
function wrapper x
    return helper(x)
"""

DUPLICATED_SRV = """\
function dup_a items
    for item in items
        if item > 0
            print item
    return items

function dup_b items
    for item in items
        if item > 0
            print item
    return items
"""


class TestParseFunctions(unittest.TestCase):
    def test_simple_parse(self):
        d = tempfile.mkdtemp()
        p = _write_srv(d, "simple.srv", SIMPLE_SRV)
        funcs = _parse_functions(p)
        self.assertEqual(len(funcs), 2)
        self.assertEqual(funcs[0].name, "greet")
        self.assertEqual(funcs[1].name, "add")

    def test_params_extracted(self):
        d = tempfile.mkdtemp()
        p = _write_srv(d, "params.srv", DEAD_PARAM_SRV)
        funcs = _parse_functions(p)
        self.assertEqual(funcs[0].params, ["a", "b", "c"])

    def test_complexity_counted(self):
        d = tempfile.mkdtemp()
        p = _write_srv(d, "deep.srv", DEEP_NESTING_SRV)
        funcs = _parse_functions(p)
        self.assertGreater(funcs[0].complexity, 1)

    def test_empty_file(self):
        d = tempfile.mkdtemp()
        p = _write_srv(d, "empty.srv", "# just a comment\n")
        funcs = _parse_functions(p)
        self.assertEqual(len(funcs), 0)

    def test_nonexistent_file(self):
        funcs = _parse_functions("/nonexistent/path.srv")
        self.assertEqual(len(funcs), 0)

    def test_try_catch_detected(self):
        d = tempfile.mkdtemp()
        srv = "function safe x\n    try\n        risky(x)\n    catch\n        print \"err\"\n"
        p = _write_srv(d, "safe.srv", srv)
        funcs = _parse_functions(p)
        self.assertTrue(funcs[0].has_try_catch)


class TestPathogenScanner(unittest.TestCase):
    def setUp(self):
        _reset_pathogen_counter()

    def test_god_function(self):
        d = tempfile.mkdtemp()
        p = _write_srv(d, "god.srv", GOD_FUNCTION_SRV)
        funcs = _parse_functions(p)
        pathogens = _scan_pathogens(funcs, set())
        cats = [pg.category for pg in pathogens]
        self.assertIn("god_function", cats)

    def test_dead_parameter(self):
        d = tempfile.mkdtemp()
        p = _write_srv(d, "dead.srv", DEAD_PARAM_SRV)
        funcs = _parse_functions(p)
        pathogens = _scan_pathogens(funcs, {"process"})
        dead = [pg for pg in pathogens if pg.category == "dead_parameter"]
        # 'b' and 'c' are dead params (not used in body), 'a' is used
        dead_params = [pg.evidence for pg in dead]
        self.assertTrue(any("b" in e for e in dead_params))
        self.assertTrue(any("c" in e for e in dead_params))

    def test_magic_number(self):
        d = tempfile.mkdtemp()
        p = _write_srv(d, "magic.srv", MAGIC_NUMBER_SRV)
        funcs = _parse_functions(p)
        pathogens = _scan_pathogens(funcs, {"calculate"})
        cats = [pg.category for pg in pathogens]
        self.assertIn("magic_number", cats)

    def test_deep_nesting(self):
        d = tempfile.mkdtemp()
        p = _write_srv(d, "deep.srv", DEEP_NESTING_SRV)
        funcs = _parse_functions(p)
        pathogens = _scan_pathogens(funcs, {"deeply_nested"})
        cats = [pg.category for pg in pathogens]
        self.assertIn("deep_nesting", cats)

    def test_missing_error_handling(self):
        d = tempfile.mkdtemp()
        p = _write_srv(d, "risky.srv", MISSING_ERROR_SRV)
        funcs = _parse_functions(p)
        pathogens = _scan_pathogens(funcs, {"risky_read"})
        cats = [pg.category for pg in pathogens]
        self.assertIn("missing_error_handling", cats)

    def test_orphan_function(self):
        d = tempfile.mkdtemp()
        p = _write_srv(d, "orphan.srv", ORPHAN_SRV)
        funcs = _parse_functions(p)
        all_targets = set()
        for fn in funcs:
            all_targets.update(fn.calls)
        pathogens = _scan_pathogens(funcs, all_targets)
        orphans = [pg for pg in pathogens if pg.category == "orphan_function"]
        orphan_locs = [pg.location for pg in orphans]
        self.assertTrue(any("lonely_orphan" in loc for loc in orphan_locs))

    def test_overloaded_params(self):
        d = tempfile.mkdtemp()
        p = _write_srv(d, "overloaded.srv", OVERLOADED_SRV)
        funcs = _parse_functions(p)
        pathogens = _scan_pathogens(funcs, {"too_many"})
        cats = [pg.category for pg in pathogens]
        self.assertIn("overloaded_params", cats)

    def test_naming_violation(self):
        d = tempfile.mkdtemp()
        p = _write_srv(d, "naming.srv", NAMING_SRV)
        funcs = _parse_functions(p)
        pathogens = _scan_pathogens(funcs, {"bad_names"})
        cats = [pg.category for pg in pathogens]
        self.assertIn("naming_violation", cats)

    def test_unguarded_recursion(self):
        d = tempfile.mkdtemp()
        p = _write_srv(d, "recurse.srv", RECURSION_SRV)
        funcs = _parse_functions(p)
        pathogens = _scan_pathogens(funcs, set())
        unguarded = [pg for pg in pathogens if pg.category == "unguarded_recursion"]
        locs = [pg.location for pg in unguarded]
        self.assertTrue(any("recurse_bad" in l for l in locs))
        # recurse_good should NOT have unguarded recursion
        self.assertFalse(any("recurse_good" in l for l in locs))

    def test_duplicated_logic(self):
        d = tempfile.mkdtemp()
        p = _write_srv(d, "dup.srv", DUPLICATED_SRV)
        funcs = _parse_functions(p)
        targets = set()
        for fn in funcs:
            targets.update(fn.calls)
        pathogens = _scan_pathogens(funcs, targets)
        cats = [pg.category for pg in pathogens]
        self.assertIn("duplicated_logic", cats)

    def test_no_pathogens_simple(self):
        d = tempfile.mkdtemp()
        p = _write_srv(d, "clean.srv", SIMPLE_SRV)
        funcs = _parse_functions(p)
        targets = set()
        for fn in funcs:
            targets.update(fn.calls)
        pathogens = _scan_pathogens(funcs, targets)
        # Simple code should have few/no critical pathogens
        crits = [pg for pg in pathogens if pg.severity == "critical"]
        self.assertEqual(len(crits), 0)


class TestAntibodyGenerator(unittest.TestCase):
    def test_antibody_per_pathogen(self):
        pathogens = [
            Pathogen("P001", "god_function", "critical", "f.srv::big", "Big fn", "LOC=60"),
            Pathogen("P002", "dead_parameter", "medium", "f.srv::fn", "Dead param", "x"),
        ]
        antibodies = _generate_antibodies(pathogens)
        self.assertEqual(len(antibodies), 2)
        self.assertEqual(antibodies[0].pathogen_id, "P001")
        self.assertIn("smaller", antibodies[0].remedy.lower())

    def test_auto_fixable(self):
        pathogens = [
            Pathogen("P001", "dead_parameter", "medium", "f::fn", "d", "x"),
            Pathogen("P002", "naming_violation", "low", "f::fn", "n", "a"),
        ]
        antibodies = _generate_antibodies(pathogens)
        self.assertTrue(antibodies[0].auto_fixable)
        self.assertTrue(antibodies[1].auto_fixable)

    def test_non_auto_fixable(self):
        pathogens = [
            Pathogen("P001", "god_function", "critical", "f::fn", "big", "LOC=80"),
        ]
        antibodies = _generate_antibodies(pathogens)
        self.assertFalse(antibodies[0].auto_fixable)


class TestImmuneMemory(unittest.TestCase):
    def test_load_missing(self):
        d = tempfile.mkdtemp()
        mem = _load_memory(d)
        self.assertEqual(mem["version"], 1)
        self.assertEqual(len(mem["scans"]), 0)

    def test_save_and_load(self):
        d = tempfile.mkdtemp()
        mem = {"version": 1, "scans": [{"timestamp": "t1", "score": 80, "pathogens": 2, "files": 1}],
               "pathogens": {}}
        _save_memory(d, mem)
        loaded = _load_memory(d)
        self.assertEqual(len(loaded["scans"]), 1)
        self.assertEqual(loaded["scans"][0]["score"], 80)

    def test_update_new_pathogens(self):
        mem = {"version": 1, "scans": [], "pathogens": {}}
        pathogens = [
            Pathogen("P001", "god_function", "critical", "f.srv::big", "Big", "LOC=60"),
        ]
        entries = _update_memory(mem, pathogens, 70.0, 1)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].occurrences, 1)
        self.assertFalse(entries[0].resolved)

    def test_update_recurring_pathogen(self):
        mem = {"version": 1, "scans": [], "pathogens": {
            "f.srv::big::god_function": {
                "first_seen": "2026-01-01", "last_seen": "2026-01-01",
                "occurrences": 2, "resolved": False,
                "pathogen_category": "god_function", "file": "f.srv"
            }
        }}
        pathogens = [
            Pathogen("P001", "god_function", "critical", "f.srv::big", "Big", "LOC=60"),
        ]
        entries = _update_memory(mem, pathogens, 65.0, 1)
        matching = [e for e in entries if e.pathogen_category == "god_function"]
        self.assertEqual(matching[0].occurrences, 3)

    def test_resolved_pathogen(self):
        mem = {"version": 1, "scans": [], "pathogens": {
            "f.srv::big::god_function": {
                "first_seen": "2026-01-01", "last_seen": "2026-01-01",
                "occurrences": 2, "resolved": False,
                "pathogen_category": "god_function", "file": "f.srv"
            }
        }}
        # No pathogens in current scan → old one should be resolved
        entries = _update_memory(mem, [], 90.0, 1)
        matching = [e for e in entries if e.pathogen_category == "god_function"]
        self.assertTrue(matching[0].resolved)

    def test_memory_scan_limit(self):
        mem = {"version": 1,
               "scans": [{"timestamp": f"t{i}", "score": 80, "pathogens": 0, "files": 1}
                         for i in range(100)],
               "pathogens": {}}
        _update_memory(mem, [], 80.0, 1)
        self.assertLessEqual(len(mem["scans"]), 100)


class TestVaccination(unittest.TestCase):
    def test_no_warnings_clean(self):
        d = tempfile.mkdtemp()
        p = _write_srv(d, "clean.srv", SIMPLE_SRV)
        funcs = _parse_functions(p)
        mem = {"version": 1, "scans": [], "pathogens": {}}
        vacc = _run_vaccinations(funcs, mem)
        self.assertEqual(len(vacc), 0)

    def test_preventive_warning(self):
        d = tempfile.mkdtemp()
        # A function with 35 LOC (approaching god_function threshold)
        lines = ["function big_fn x\n"] + [f"    print \"{i}\"\n" for i in range(35)]
        p = _write_srv(d, "big.srv", "".join(lines))
        funcs = _parse_functions(p)
        mem = {"version": 1, "scans": [], "pathogens": {
            "old::god_function": {
                "first_seen": "t1", "last_seen": "t2",
                "occurrences": 3, "resolved": False,
                "pathogen_category": "god_function", "file": "old.srv"
            }
        }}
        vacc = _run_vaccinations(funcs, mem)
        self.assertTrue(any(v["type"] == "preventive" for v in vacc))

    def test_systemic_warning(self):
        mem = {"version": 1, "scans": [
            {"timestamp": "t1", "score": 40, "pathogens": 10, "files": 5},
            {"timestamp": "t2", "score": 45, "pathogens": 9, "files": 5},
            {"timestamp": "t3", "score": 50, "pathogens": 8, "files": 5},
        ], "pathogens": {}}
        vacc = _run_vaccinations([], mem)
        self.assertTrue(any(v["type"] == "systemic" for v in vacc))


class TestAutoimmune(unittest.TestCase):
    def test_over_validation(self):
        d = tempfile.mkdtemp()
        p = _write_srv(d, "ov.srv", AUTOIMMUNE_OVER_VALIDATE_SRV)
        funcs = _parse_functions(p)
        issues = _detect_autoimmune(funcs)
        cats = [i.category for i in issues]
        self.assertIn("over_validation", cats)

    def test_redundant_guard(self):
        d = tempfile.mkdtemp()
        p = _write_srv(d, "rd.srv", AUTOIMMUNE_REDUNDANT_SRV)
        funcs = _parse_functions(p)
        issues = _detect_autoimmune(funcs)
        cats = [i.category for i in issues]
        self.assertIn("redundant_guard", cats)

    def test_over_abstraction(self):
        d = tempfile.mkdtemp()
        p = _write_srv(d, "oa.srv", AUTOIMMUNE_OVER_ABSTRACT_SRV)
        funcs = _parse_functions(p)
        issues = _detect_autoimmune(funcs)
        cats = [i.category for i in issues]
        self.assertIn("over_abstraction", cats)

    def test_no_autoimmune_clean(self):
        d = tempfile.mkdtemp()
        p = _write_srv(d, "clean.srv", SIMPLE_SRV)
        funcs = _parse_functions(p)
        issues = _detect_autoimmune(funcs)
        self.assertEqual(len(issues), 0)


class TestImmuneScore(unittest.TestCase):
    def test_perfect_score(self):
        # No functions → perfect score
        score = _compute_immune_score([], [], {}, [], [])
        self.assertEqual(score, 100.0)

    def test_score_range(self):
        d = tempfile.mkdtemp()
        p = _write_srv(d, "god.srv", GOD_FUNCTION_SRV)
        funcs = _parse_functions(p)
        _reset_pathogen_counter()
        pathogens = _scan_pathogens(funcs, set())
        score = _compute_immune_score(funcs, pathogens, {}, [], [])
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_clean_scores_high(self):
        d = tempfile.mkdtemp()
        p = _write_srv(d, "clean.srv", SIMPLE_SRV)
        funcs = _parse_functions(p)
        _reset_pathogen_counter()
        pathogens = _scan_pathogens(funcs, set())
        score = _compute_immune_score(funcs, pathogens, {}, [], [])
        self.assertGreater(score, 50)


class TestScoreTier(unittest.TestCase):
    def test_fortified(self):
        self.assertEqual(_score_tier(90), "Fortified")

    def test_healthy(self):
        self.assertEqual(_score_tier(75), "Healthy")

    def test_vulnerable(self):
        self.assertEqual(_score_tier(60), "Vulnerable")

    def test_compromised(self):
        self.assertEqual(_score_tier(45), "Compromised")

    def test_critical(self):
        self.assertEqual(_score_tier(20), "Critical")


class TestInsights(unittest.TestCase):
    def test_critical_insight(self):
        report = ImmuneReport()
        report.pathogens = [Pathogen("P1", "god_function", "critical", "f::fn", "d", "e")]
        report.antibodies = [Antibody("P1", "fix", "high", False)]
        report.pathogen_summary = {"god_function": 1}
        mem = {"scans": [], "pathogens": {}}
        ins = _generate_insights(report, mem)
        self.assertTrue(any("critical" in i.lower() or "urgent" in i.lower() for i in ins))

    def test_trend_insight(self):
        report = ImmuneReport()
        report.pathogens = []
        report.antibodies = []
        report.pathogen_summary = {}
        report.vaccinations = []
        report.autoimmune_issues = []
        report.immune_score = 85
        mem = {"scans": [
            {"timestamp": "t1", "score": 60, "pathogens": 5, "files": 1},
            {"timestamp": "t2", "score": 85, "pathogens": 1, "files": 1},
        ], "pathogens": {}}
        ins = _generate_insights(report, mem)
        self.assertTrue(any("improved" in i.lower() for i in ins))


class TestAnalyzeImmune(unittest.TestCase):
    def test_full_pipeline(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "test.srv", SIMPLE_SRV)
        _write_srv(d, "god.srv", GOD_FUNCTION_SRV)
        report = analyze_immune([d], scan_dir=d)
        self.assertGreater(report.files_scanned, 0)
        self.assertGreater(report.total_functions, 0)
        self.assertIsInstance(report.immune_score, float)
        self.assertTrue(len(report.pathogens) > 0)
        self.assertEqual(len(report.antibodies), len(report.pathogens))

    def test_memory_created(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "test.srv", SIMPLE_SRV)
        analyze_immune([d], scan_dir=d)
        self.assertTrue(os.path.isfile(os.path.join(d, MEMORY_FILE)))

    def test_empty_directory(self):
        d = tempfile.mkdtemp()
        report = analyze_immune([d], scan_dir=d)
        self.assertEqual(report.files_scanned, 0)
        self.assertEqual(report.total_functions, 0)
        self.assertEqual(report.immune_score, 100.0)


class TestHTMLGeneration(unittest.TestCase):
    def test_html_contains_structure(self):
        report = ImmuneReport(
            timestamp="2026-01-01 00:00:00",
            files_scanned=1, total_functions=2,
            pathogens=[], antibodies=[],
            memory_entries=[], vaccinations=[],
            autoimmune_issues=[], immune_score=85.0,
            insights=["Test insight"], pathogen_summary={}
        )
        html = _generate_html(report)
        self.assertIn("sauravimmune", html)
        self.assertIn("85.0", html)
        self.assertIn("Fortified", html)
        self.assertIn("Test insight", html)

    def test_html_with_data(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "test.srv", GOD_FUNCTION_SRV)
        report = analyze_immune([d], scan_dir=d)
        html = _generate_html(report)
        self.assertIn("<table>", html)
        self.assertIn("god_function", html)


class TestCLI(unittest.TestCase):
    def test_json_output(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "test.srv", SIMPLE_SRV)
        with patch('sys.stdout', new_callable=StringIO) as mock:
            ret = main([d, "--json", "--no-color"])
        self.assertEqual(ret, 0)
        out = mock.getvalue()
        data = json.loads(out)
        self.assertIn("immune_score", data)
        self.assertIn("pathogens", data)

    def test_html_output(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "test.srv", SIMPLE_SRV)
        html_path = os.path.join(d, "report.html")
        ret = main([d, "--html", html_path, "--no-color"])
        self.assertEqual(ret, 0)
        self.assertTrue(os.path.isfile(html_path))

    def test_pathogens_filter(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "test.srv", GOD_FUNCTION_SRV)
        with patch('sys.stdout', new_callable=StringIO):
            ret = main([d, "--pathogens", "--no-color"])
        self.assertEqual(ret, 0)

    def test_antibodies_filter(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "test.srv", GOD_FUNCTION_SRV)
        with patch('sys.stdout', new_callable=StringIO):
            ret = main([d, "--antibodies", "--no-color"])
        self.assertEqual(ret, 0)

    def test_memory_filter(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "test.srv", SIMPLE_SRV)
        with patch('sys.stdout', new_callable=StringIO):
            ret = main([d, "--memory", "--no-color"])
        self.assertEqual(ret, 0)

    def test_vaccinate_filter(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "test.srv", SIMPLE_SRV)
        with patch('sys.stdout', new_callable=StringIO):
            ret = main([d, "--vaccinate", "--no-color"])
        self.assertEqual(ret, 0)

    def test_autoimmune_filter(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "test.srv", AUTOIMMUNE_OVER_VALIDATE_SRV)
        with patch('sys.stdout', new_callable=StringIO):
            ret = main([d, "--autoimmune", "--no-color"])
        self.assertEqual(ret, 0)

    def test_top_filter(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "test.srv", GOD_FUNCTION_SRV)
        with patch('sys.stdout', new_callable=StringIO):
            ret = main([d, "--top", "5", "--no-color"])
        self.assertEqual(ret, 0)

    def test_reset_memory(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "test.srv", SIMPLE_SRV)
        analyze_immune([d], scan_dir=d)  # create memory
        self.assertTrue(os.path.isfile(os.path.join(d, MEMORY_FILE)))
        with patch('sys.stdout', new_callable=StringIO):
            ret = main([d, "--reset-memory"])
        self.assertEqual(ret, 0)
        self.assertFalse(os.path.isfile(os.path.join(d, MEMORY_FILE)))

    def test_full_report(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "test.srv", SIMPLE_SRV)
        with patch('sys.stdout', new_callable=StringIO):
            ret = main([d, "--no-color"])
        self.assertEqual(ret, 0)

    def test_critical_filter(self):
        d = tempfile.mkdtemp()
        _write_srv(d, "test.srv", GOD_FUNCTION_SRV)
        with patch('sys.stdout', new_callable=StringIO):
            ret = main([d, "--pathogens", "--critical", "--no-color"])
        self.assertEqual(ret, 0)


if __name__ == "__main__":
    unittest.main()
