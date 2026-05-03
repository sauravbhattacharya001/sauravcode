#!/usr/bin/env python3
"""Tests for sauravdiplomacy — Code Diplomacy Engine."""

import os
import sys
import json
import tempfile
import unittest
from dataclasses import asdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sauravdiplomacy import (
    parse_module, parse_codebase, analyze_sovereignty, detect_alliances,
    detect_embargoes, analyze_treaties, detect_conflicts, score_health,
    generate_insights, analyze, generate_html, ModuleNation, FunctionInfo,
    SovereigntyReport, AllianceReport, EmbargoReport, TreatyReport,
    ConflictReport, _jaccard,
)


class _TempSrvMixin:
    """Helper to create temporary .srv files."""

    def _write_srv(self, name: str, content: str, directory: str = None) -> str:
        d = directory or self._tmpdir
        path = os.path.join(d, f"{name}.srv")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)


# ── Parsing Tests ────────────────────────────────────────────────────


class TestParsing(_TempSrvMixin, unittest.TestCase):

    def test_parse_empty_file(self):
        path = self._write_srv("empty", "")
        m = parse_module(path)
        self.assertEqual(m.name, "empty")
        self.assertEqual(m.lines, 0)
        self.assertEqual(len(m.functions), 0)

    def test_parse_single_function(self):
        path = self._write_srv("single", "function greet(name)\n  print(name)\n")
        m = parse_module(path)
        self.assertEqual(len(m.functions), 1)
        self.assertEqual(m.functions[0].name, "greet")
        self.assertEqual(m.functions[0].param_count, 1)

    def test_parse_multiple_functions(self):
        code = "function foo()\n  return 1\n\nfunction bar(x, y)\n  return x\n"
        path = self._write_srv("multi", code)
        m = parse_module(path)
        self.assertEqual(len(m.functions), 2)
        names = {f.name for f in m.functions}
        self.assertEqual(names, {"foo", "bar"})

    def test_parse_imports(self):
        code = 'import "utils.srv"\nimport "helpers.srv"\nfunction main()\n  print("hi")\n'
        path = self._write_srv("importer", code)
        m = parse_module(path)
        self.assertEqual(m.imports, ["utils", "helpers"])

    def test_parse_function_calls(self):
        code = "function process()\n  result = compute(data)\n  display(result)\n"
        path = self._write_srv("caller", code)
        m = parse_module(path)
        self.assertIn("compute", m.all_calls)
        self.assertIn("display", m.all_calls)

    def test_parse_variables(self):
        code = "x = 10\nfunction init()\n  y = 20\n"
        path = self._write_srv("vars", code)
        m = parse_module(path)
        self.assertIn("x", m.variables_defined)

    def test_parse_exports(self):
        code = "function alpha()\n  return 1\n\nfunction beta()\n  return 2\n"
        path = self._write_srv("exports", code)
        m = parse_module(path)
        self.assertEqual(m.exports, {"alpha", "beta"})

    def test_parse_codebase(self):
        self._write_srv("a", "function fa()\n  return 1\n")
        self._write_srv("b", "function fb()\n  return 2\n")
        nations = parse_codebase([self._tmpdir])
        self.assertEqual(len(nations), 2)

    def test_parse_fn_keyword(self):
        path = self._write_srv("fntest", "fn compute(x)\n  return x * 2\n")
        m = parse_module(path)
        self.assertEqual(len(m.functions), 1)
        self.assertEqual(m.functions[0].name, "compute")

    def test_parse_code_lines(self):
        code = "# comment\nfunction f()\n  x = 1\n\n  # another comment\n  return x\n"
        path = self._write_srv("lines", code)
        m = parse_module(path)
        # code lines: function f(), x = 1, return x = 3
        self.assertGreater(m.code_lines, 0)

    def test_parse_nonexistent_file(self):
        m = parse_module("/nonexistent/file.srv")
        self.assertEqual(m.lines, 0)


# ── Sovereignty Tests ────────────────────────────────────────────────


class TestSovereignty(_TempSrvMixin, unittest.TestCase):

    def test_single_independent_module(self):
        self._write_srv("solo", "function a()\n  return 1\nfunction b()\n  return 2\n")
        nations = parse_codebase([self._tmpdir])
        report = analyze_sovereignty(nations)
        self.assertGreater(report.rankings[0]["sovereignty"], 50)

    def test_dependent_module_scores_lower(self):
        self._write_srv("core", "function helper()\n  return 1\n")
        self._write_srv("dependent",
                        'import "core.srv"\nimport "other.srv"\nimport "lib.srv"\n'
                        "function use()\n  helper()\n")
        nations = parse_codebase([self._tmpdir])
        report = analyze_sovereignty(nations)
        scores = {r["module"]: r["sovereignty"] for r in report.rankings}
        self.assertGreater(scores["core"], scores["dependent"])

    def test_empty_codebase(self):
        report = analyze_sovereignty([])
        self.assertEqual(report.score, 100.0)

    def test_tier_assignment(self):
        self._write_srv("big", "\n".join(
            [f"function f{i}()\n  return {i}" for i in range(10)]
        ))
        nations = parse_codebase([self._tmpdir])
        report = analyze_sovereignty(nations)
        self.assertIn(report.rankings[0]["tier"],
                      ["Superpower", "Independent", "Aligned", "Dependent", "Vassal"])

    def test_most_independent(self):
        self._write_srv("a", "function x()\n  return 1\n")
        self._write_srv("b", 'import "a.srv"\nimport "c.srv"\nfunction y()\n  x()\n')
        nations = parse_codebase([self._tmpdir])
        report = analyze_sovereignty(nations)
        self.assertEqual(report.most_independent, "a")


# ── Alliance Tests ───────────────────────────────────────────────────


class TestAlliances(_TempSrvMixin, unittest.TestCase):

    def test_mutual_import_alliance(self):
        self._write_srv("alpha", 'import "beta.srv"\nfunction a1()\n  b1()\n')
        self._write_srv("beta", 'import "alpha.srv"\nfunction b1()\n  a1()\n')
        nations = parse_codebase([self._tmpdir])
        report = detect_alliances(nations)
        self.assertGreater(report.total_alliances, 0)

    def test_no_alliances_isolated(self):
        self._write_srv("x", "function fx()\n  return 1\n")
        self._write_srv("y", "function fy()\n  return 2\n")
        nations = parse_codebase([self._tmpdir])
        report = detect_alliances(nations)
        self.assertEqual(report.total_alliances, 0)

    def test_single_module(self):
        self._write_srv("solo", "function f()\n  return 1\n")
        nations = parse_codebase([self._tmpdir])
        report = detect_alliances(nations)
        self.assertEqual(report.score, 100.0)

    def test_jaccard_identical(self):
        self.assertAlmostEqual(_jaccard({1, 2, 3}, {1, 2, 3}), 1.0)

    def test_jaccard_disjoint(self):
        self.assertAlmostEqual(_jaccard({1, 2}, {3, 4}), 0.0)

    def test_jaccard_empty(self):
        self.assertAlmostEqual(_jaccard(set(), set()), 0.0)

    def test_alliance_type(self):
        # 3 modules all importing each other
        self._write_srv("m1", 'import "m2.srv"\nimport "m3.srv"\nfunction f1()\n  f2()\n  f3()\n')
        self._write_srv("m2", 'import "m1.srv"\nimport "m3.srv"\nfunction f2()\n  f1()\n  f3()\n')
        self._write_srv("m3", 'import "m1.srv"\nimport "m2.srv"\nfunction f3()\n  f1()\n  f2()\n')
        nations = parse_codebase([self._tmpdir])
        report = detect_alliances(nations)
        # Should form a multilateral alliance
        if report.alliances:
            types = [a["type"] for a in report.alliances]
            self.assertTrue(any(t == "multilateral" for t in types) or len(report.alliances) >= 2)


# ── Embargo Tests ────────────────────────────────────────────────────


class TestEmbargoes(_TempSrvMixin, unittest.TestCase):

    def test_naming_similarity_embargo(self):
        # Modules with shared prefix but no imports
        self._write_srv("saurav_core", "function setup()\n  return 1\n")
        self._write_srv("saurav_util", "function setup()\n  return 2\n")
        nations = parse_codebase([self._tmpdir])
        report = detect_embargoes(nations)
        self.assertGreater(report.total_embargoes, 0)

    def test_connected_modules_no_embargo(self):
        self._write_srv("lib", "function helper()\n  return 1\n")
        self._write_srv("app", 'import "lib.srv"\nfunction main()\n  helper()\n')
        nations = parse_codebase([self._tmpdir])
        report = detect_embargoes(nations)
        # Should not flag lib-app since they're connected
        embargo_pairs = [(e["module_a"], e["module_b"]) for e in report.embargoes]
        self.assertNotIn(("app", "lib"), embargo_pairs)
        self.assertNotIn(("lib", "app"), embargo_pairs)

    def test_single_module_no_embargo(self):
        self._write_srv("only", "function f()\n  return 1\n")
        nations = parse_codebase([self._tmpdir])
        report = detect_embargoes(nations)
        self.assertEqual(report.total_embargoes, 0)

    def test_calls_without_import(self):
        self._write_srv("provider", "function compute(x)\n  return x * 2\n")
        self._write_srv("consumer", "function main()\n  result = compute(5)\n")
        nations = parse_codebase([self._tmpdir])
        report = detect_embargoes(nations)
        # consumer calls compute which is in provider but doesn't import it
        found = any(
            (e["module_a"] in ("provider", "consumer") and e["module_b"] in ("provider", "consumer"))
            for e in report.embargoes
        )
        self.assertTrue(found)


# ── Treaty Tests ─────────────────────────────────────────────────────


class TestTreaties(_TempSrvMixin, unittest.TestCase):

    def test_one_sided_treaty(self):
        self._write_srv("lib", "function helper()\n  return 1\n")
        self._write_srv("app", 'import "lib.srv"\nfunction main()\n  helper()\n')
        nations = parse_codebase([self._tmpdir])
        report = analyze_treaties(nations)
        self.assertEqual(report.total_treaties, 1)
        self.assertTrue(report.treaties[0]["is_one_sided"])

    def test_mutual_treaty(self):
        self._write_srv("a", 'import "b.srv"\nfunction fa()\n  fb()\n')
        self._write_srv("b", 'import "a.srv"\nfunction fb()\n  fa()\n')
        nations = parse_codebase([self._tmpdir])
        report = analyze_treaties(nations)
        # Both should have treaties, at least one should not be one-sided
        one_sided = [t for t in report.treaties if not t["is_one_sided"]]
        self.assertGreater(len(one_sided), 0)

    def test_no_treaties(self):
        self._write_srv("isolated", "function f()\n  return 1\n")
        nations = parse_codebase([self._tmpdir])
        report = analyze_treaties(nations)
        self.assertEqual(report.total_treaties, 0)

    def test_treaty_functions_used(self):
        self._write_srv("core", "function alpha()\n  return 1\nfunction beta()\n  return 2\n")
        self._write_srv("user", 'import "core.srv"\nfunction main()\n  alpha()\n  beta()\n')
        nations = parse_codebase([self._tmpdir])
        report = analyze_treaties(nations)
        self.assertEqual(len(report.treaties), 1)
        self.assertIn("alpha", report.treaties[0]["functions_used"])
        self.assertIn("beta", report.treaties[0]["functions_used"])

    def test_fairness_ratio(self):
        self._write_srv("lib", "function h()\n  return 1\n")
        self._write_srv("app", 'import "lib.srv"\nfunction m()\n  h()\n')
        nations = parse_codebase([self._tmpdir])
        report = analyze_treaties(nations)
        # One treaty, one-sided → fairness = 0.0
        self.assertEqual(report.fairness_ratio, 0.0)


# ── Conflict Tests ───────────────────────────────────────────────────


class TestConflicts(_TempSrvMixin, unittest.TestCase):

    def test_naming_collision(self):
        self._write_srv("mod_a", "function process()\n  return 1\n")
        self._write_srv("mod_b", "function process()\n  return 2\n")
        nations = parse_codebase([self._tmpdir])
        report = detect_conflicts(nations)
        naming = [c for c in report.conflicts if c["type"] == "naming"]
        self.assertGreater(len(naming), 0)

    def test_no_conflicts(self):
        self._write_srv("mod_a", "function alpha()\n  return 1\n")
        self._write_srv("mod_b", "function beta()\n  return 2\n")
        nations = parse_codebase([self._tmpdir])
        report = detect_conflicts(nations)
        naming = [c for c in report.conflicts if c["type"] == "naming"]
        self.assertEqual(len(naming), 0)

    def test_implementation_conflict(self):
        self._write_srv("v1", "function calc(x)\n  return x\n")
        self._write_srv("v2", "function calc(x, y)\n  return x + y\n")
        nations = parse_codebase([self._tmpdir])
        report = detect_conflicts(nations)
        impl = [c for c in report.conflicts if c["type"] == "implementation"]
        self.assertGreater(len(impl), 0)

    def test_single_module_no_conflicts(self):
        self._write_srv("solo", "function f()\n  return 1\n")
        nations = parse_codebase([self._tmpdir])
        report = detect_conflicts(nations)
        self.assertEqual(report.total_conflicts, 0)


# ── Health Scoring Tests ─────────────────────────────────────────────


class TestHealthScoring(unittest.TestCase):

    def test_perfect_scores(self):
        sov = SovereigntyReport(score=100)
        ali = AllianceReport(score=100)
        emb = EmbargoReport(score=100)
        tre = TreatyReport(score=100)
        con = ConflictReport(score=100)
        health, tier, _ = score_health(sov, ali, emb, tre, con)
        self.assertEqual(health, 100.0)
        self.assertEqual(tier, "Utopia")

    def test_zero_scores(self):
        sov = SovereigntyReport(score=0)
        ali = AllianceReport(score=0)
        emb = EmbargoReport(score=0)
        tre = TreatyReport(score=0)
        con = ConflictReport(score=0)
        health, tier, _ = score_health(sov, ali, emb, tre, con)
        self.assertEqual(health, 0.0)
        self.assertEqual(tier, "Failed State")

    def test_tense_tier(self):
        sov = SovereigntyReport(score=50)
        ali = AllianceReport(score=50)
        emb = EmbargoReport(score=50)
        tre = TreatyReport(score=50)
        con = ConflictReport(score=50)
        health, tier, _ = score_health(sov, ali, emb, tre, con)
        self.assertEqual(tier, "Tense")

    def test_sub_scores_returned(self):
        sov = SovereigntyReport(score=80)
        ali = AllianceReport(score=60)
        emb = EmbargoReport(score=70)
        tre = TreatyReport(score=90)
        con = ConflictReport(score=50)
        _, _, sub = score_health(sov, ali, emb, tre, con)
        self.assertEqual(sub["sovereignty"], 80)
        self.assertEqual(sub["alliances"], 60)

    def test_crisis_tier(self):
        sov = SovereigntyReport(score=25)
        ali = AllianceReport(score=25)
        emb = EmbargoReport(score=25)
        tre = TreatyReport(score=25)
        con = ConflictReport(score=25)
        health, tier, _ = score_health(sov, ali, emb, tre, con)
        self.assertEqual(tier, "Crisis")


# ── Insight Tests ────────────────────────────────────────────────────


class TestInsights(_TempSrvMixin, unittest.TestCase):

    def test_vassal_warning(self):
        # Create external modules so calls are counted as external
        for name in ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k']:
            self._write_srv(name, f"function {name}()\n  return 1\n")
        self._write_srv("dependent",
                        'import "a.srv"\nimport "b.srv"\nimport "c.srv"\n'
                        'import "d.srv"\nimport "e.srv"\nimport "f.srv"\n'
                        'import "g.srv"\nimport "h.srv"\nimport "i.srv"\n'
                        'import "j.srv"\nimport "k.srv"\n'
                        "function dep()\n  a()\n  b()\n  c()\n  d()\n  e()\n")
        nations = parse_codebase([self._tmpdir])
        sov = analyze_sovereignty(nations)
        insights = generate_insights(
            nations, sov, AllianceReport(), EmbargoReport(),
            TreatyReport(), ConflictReport(), 50, "Tense"
        )
        warnings = [i for i in insights if i["type"] == "sovereignty_warning"]
        self.assertGreater(len(warnings), 0)

    def test_critical_health_insight(self):
        insights = generate_insights(
            [], SovereigntyReport(), AllianceReport(), EmbargoReport(),
            TreatyReport(), ConflictReport(), 10, "Failed State"
        )
        critical = [i for i in insights if i["type"] == "critical_warning"]
        self.assertGreater(len(critical), 0)

    def test_utopia_praise(self):
        insights = generate_insights(
            [], SovereigntyReport(), AllianceReport(), EmbargoReport(),
            TreatyReport(), ConflictReport(), 90, "Utopia"
        )
        praise = [i for i in insights if i["type"] == "health_praise"]
        self.assertGreater(len(praise), 0)

    def test_embargo_insight(self):
        emb = EmbargoReport(embargoes=[{
            "module_a": "x", "module_b": "y", "reason": "shared prefix",
            "severity": 0.7, "shared_patterns": ["shared prefix 'saurav'"],
        }])
        insights = generate_insights(
            [], SovereigntyReport(), AllianceReport(), emb,
            TreatyReport(), ConflictReport(), 50, "Tense"
        )
        resolutions = [i for i in insights if i["type"] == "embargo_resolution"]
        self.assertGreater(len(resolutions), 0)

    def test_treaty_imbalance_insight(self):
        tre = TreatyReport(treaties=[{
            "exporter": "lib", "importer": "app",
            "functions_used": ["a", "b", "c"],
            "complexity": 0.5, "is_one_sided": True,
        }])
        insights = generate_insights(
            [], SovereigntyReport(), AllianceReport(), EmbargoReport(),
            tre, ConflictReport(), 50, "Tense"
        )
        imbalance = [i for i in insights if i["type"] == "treaty_imbalance"]
        self.assertGreater(len(imbalance), 0)


# ── Full Analysis Tests ──────────────────────────────────────────────


class TestFullAnalysis(_TempSrvMixin, unittest.TestCase):

    def test_full_analysis(self):
        self._write_srv("core", "function init()\n  return 1\nfunction run()\n  init()\n")
        self._write_srv("app", 'import "core.srv"\nfunction main()\n  init()\n  run()\n')
        report = analyze([self._tmpdir])
        self.assertEqual(report.total_modules, 2)
        self.assertGreater(report.total_functions, 0)
        self.assertIn(report.health_tier,
                      ["Utopia", "Stable", "Tense", "Crisis", "Failed State"])

    def test_empty_directory(self):
        report = analyze([self._tmpdir])
        self.assertEqual(report.total_modules, 0)

    def test_report_has_all_fields(self):
        self._write_srv("m", "function f()\n  return 1\n")
        report = analyze([self._tmpdir])
        d = asdict(report)
        for key in ["sovereignty", "alliances", "embargoes", "treaties",
                     "conflicts", "health_score", "health_tier", "insights"]:
            self.assertIn(key, d)


# ── HTML Tests ───────────────────────────────────────────────────────


class TestHTML(_TempSrvMixin, unittest.TestCase):

    def test_html_generation(self):
        self._write_srv("mod", "function f()\n  return 1\n")
        report = analyze([self._tmpdir])
        html = generate_html(report)
        self.assertIn("sauravdiplomacy", html)
        self.assertIn("Sovereignty", html)
        self.assertIn("</html>", html)

    def test_html_contains_score(self):
        self._write_srv("mod", "function f()\n  return 1\n")
        report = analyze([self._tmpdir])
        html = generate_html(report)
        self.assertIn(str(int(report.health_score)), html)

    def test_html_write_to_file(self):
        self._write_srv("mod", "function f()\n  return 1\n")
        report = analyze([self._tmpdir])
        html = generate_html(report)
        out_path = os.path.join(self._tmpdir, "report.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        self.assertTrue(os.path.exists(out_path))


# ── Edge Case Tests ──────────────────────────────────────────────────


class TestEdgeCases(_TempSrvMixin, unittest.TestCase):

    def test_comment_only_file(self):
        self._write_srv("comments", "# This is a comment\n# Another comment\n")
        nations = parse_codebase([self._tmpdir])
        # File has lines but no code lines
        self.assertEqual(len(nations), 1)
        self.assertEqual(nations[0].code_lines, 0)

    def test_deeply_nested_functions(self):
        code = "function outer()\n  function inner()\n    return 1\n  inner()\n"
        path = self._write_srv("nested", code)
        m = parse_module(path)
        self.assertGreater(len(m.functions), 0)

    def test_duplicate_import(self):
        code = 'import "utils.srv"\nimport "utils.srv"\nfunction f()\n  return 1\n'
        path = self._write_srv("dupimp", code)
        m = parse_module(path)
        self.assertEqual(m.imports.count("utils"), 1)


if __name__ == "__main__":
    unittest.main()
