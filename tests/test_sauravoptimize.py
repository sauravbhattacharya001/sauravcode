"""Tests for sauravoptimize — the autonomous code optimizer.

Covers: SourceAnalyzer (P003/P004/P006/P007/P009), ASTAnalyzer
(P001/P002/P006/P010), OptFinding/OptReport data classes, score
computation, severity filtering, deduplication, HTML report generation,
rule explanations, and the full analyze_file pipeline.
"""

import os
import sys
import json
import tempfile
import textwrap
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sauravoptimize import (
    Severity,
    OptFinding,
    OptReport,
    SourceAnalyzer,
    ASTAnalyzer,
    RULE_EXPLANATIONS,
    SEVERITY_PENALTY,
    compute_score,
    generate_html,
    analyze_file,
)


# ── Helpers ───────────────────────────────────────────────────────────

def _src(code: str) -> str:
    """Dedent a code block for clean test fixtures."""
    return textwrap.dedent(code).strip()


def _write_srv(tmp_path, name: str, code: str) -> str:
    """Write a .srv file and return its path."""
    p = os.path.join(str(tmp_path), name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(_src(code))
    return p


# ── OptFinding tests ─────────────────────────────────────────────────

class TestOptFinding:
    def test_to_dict_roundtrip(self):
        f = OptFinding(
            rule="P001",
            severity=Severity.HIGH,
            line=10,
            message="test msg",
            suggestion="fix it",
            estimated_speedup="2x",
            auto_fixable=True,
        )
        d = f.to_dict()
        assert d["rule"] == "P001"
        assert d["severity"] == "high"
        assert d["line"] == 10
        assert d["auto_fixable"] is True
        assert d["estimated_speedup"] == "2x"

    def test_str_high_fixable(self):
        f = OptFinding(
            rule="P003", severity=Severity.HIGH, line=5,
            message="string concat", suggestion="use join",
            auto_fixable=True,
        )
        s = str(f)
        assert "H" in s
        assert "P003" in s
        assert "[fixable]" in s

    def test_str_low_not_fixable(self):
        f = OptFinding(
            rule="P010", severity=Severity.LOW, line=1,
            message="unused index", suggestion="rename",
        )
        s = str(f)
        assert "L" in s
        assert "[fixable]" not in s


# ── OptReport tests ──────────────────────────────────────────────────

class TestOptReport:
    def test_empty_report(self):
        r = OptReport(file="test.srv")
        assert r.score == 100
        assert r.summary()["total"] == 0

    def test_summary_counts(self):
        r = OptReport(file="x.srv", findings=[
            OptFinding(rule="P001", severity=Severity.HIGH, line=1,
                       message="a", suggestion="b", auto_fixable=True),
            OptFinding(rule="P002", severity=Severity.MEDIUM, line=2,
                       message="c", suggestion="d"),
            OptFinding(rule="P003", severity=Severity.HIGH, line=3,
                       message="e", suggestion="f", auto_fixable=True),
        ])
        s = r.summary()
        assert s["total"] == 3
        assert s["high"] == 2
        assert s["medium"] == 1
        assert s["low"] == 0
        assert s["fixable"] == 2

    def test_to_dict_has_all_keys(self):
        r = OptReport(file="z.srv", score=85, parse_error="")
        d = r.to_dict()
        assert "file" in d
        assert "score" in d
        assert "findings" in d
        assert "summary" in d


# ── compute_score tests ──────────────────────────────────────────────

class TestComputeScore:
    def test_no_findings(self):
        assert compute_score([]) == 100

    def test_single_high(self):
        f = [OptFinding(rule="P001", severity=Severity.HIGH, line=1,
                        message="x", suggestion="y")]
        assert compute_score(f) == 100 - SEVERITY_PENALTY["high"]

    def test_mixed_findings(self):
        findings = [
            OptFinding(rule="P001", severity=Severity.HIGH, line=1,
                       message="a", suggestion="b"),
            OptFinding(rule="P002", severity=Severity.MEDIUM, line=2,
                       message="c", suggestion="d"),
            OptFinding(rule="P010", severity=Severity.LOW, line=3,
                       message="e", suggestion="f"),
        ]
        expected = 100 - SEVERITY_PENALTY["high"] - SEVERITY_PENALTY["medium"] - SEVERITY_PENALTY["low"]
        assert compute_score(findings) == expected

    def test_floor_at_zero(self):
        """Score never goes below 0 regardless of how many findings."""
        many = [OptFinding(rule="P001", severity=Severity.HIGH, line=i,
                           message="x", suggestion="y") for i in range(20)]
        assert compute_score(many) == 0


# ── SourceAnalyzer tests ─────────────────────────────────────────────

class TestSourceAnalyzer:
    def test_p003_string_concat_in_loop(self):
        code = _src('''
            result = ""
            for item in items
              result = result + item
        ''')
        sa = SourceAnalyzer(code, "test.srv")
        findings = sa.analyze()
        p003 = [f for f in findings if f.rule == "P003"]
        assert len(p003) >= 1
        assert p003[0].severity == Severity.HIGH
        assert "O(n²)" in p003[0].message

    def test_p003_no_false_positive_outside_loop(self):
        code = _src('''
            result = ""
            result = result + "hello"
        ''')
        sa = SourceAnalyzer(code, "test.srv")
        findings = sa.analyze()
        p003 = [f for f in findings if f.rule == "P003"]
        assert len(p003) == 0

    def test_p004_list_concat_in_loop(self):
        code = _src('''
            for x in data
              items = items + [x]
        ''')
        sa = SourceAnalyzer(code, "test.srv")
        findings = sa.analyze()
        p004 = [f for f in findings if f.rule == "P004"]
        assert len(p004) >= 1
        assert p004[0].auto_fixable is True

    def test_p006_recursive_no_memo(self):
        code = _src('''
            fun fib n
              if n <= 1
                return n
              return fib n - 1 + fib n - 2
        ''')
        sa = SourceAnalyzer(code, "test.srv")
        findings = sa.analyze()
        p006 = [f for f in findings if f.rule == "P006"]
        assert len(p006) >= 1
        assert "fib" in p006[0].message
        assert p006[0].severity == Severity.HIGH

    def test_p006_no_alert_when_memoized(self):
        code = _src('''
            memo = {}
            fun fib n
              if contains memo n
                return memo[n]
              result = fib n - 1 + fib n - 2
              memo[n] = result
              return result
        ''')
        sa = SourceAnalyzer(code, "test.srv")
        findings = sa.analyze()
        p006 = [f for f in findings if f.rule == "P006"]
        assert len(p006) == 0

    def test_p007_dead_store(self):
        code = _src('''
            x = 42
            x = 99
            print x
        ''')
        sa = SourceAnalyzer(code, "test.srv")
        findings = sa.analyze()
        p007 = [f for f in findings if f.rule == "P007"]
        assert len(p007) >= 1
        assert "Dead store" in p007[0].message

    def test_p007_no_false_positive_when_read(self):
        code = _src('''
            x = 42
            print x
            x = 99
        ''')
        sa = SourceAnalyzer(code, "test.srv")
        findings = sa.analyze()
        p007 = [f for f in findings if f.rule == "P007"]
        assert len(p007) == 0

    def test_p009_repeated_access(self):
        code = _src('''
            a = data["name"]
            b = data["name"]
            c = data["name"]
        ''')
        sa = SourceAnalyzer(code, "test.srv")
        findings = sa.analyze()
        p009 = [f for f in findings if f.rule == "P009"]
        assert len(p009) >= 1
        assert "3 times" in p009[0].message

    def test_p009_no_alert_for_single_access(self):
        code = _src('''
            a = data["name"]
            b = data["age"]
        ''')
        sa = SourceAnalyzer(code, "test.srv")
        findings = sa.analyze()
        p009 = [f for f in findings if f.rule == "P009"]
        assert len(p009) == 0

    def test_comments_ignored(self):
        code = _src('''
            # result = result + item
            # items = items + [x]
        ''')
        sa = SourceAnalyzer(code, "test.srv")
        findings = sa.analyze()
        assert len(findings) == 0


# ── ASTAnalyzer tests (source-level path) ────────────────────────────

class TestASTAnalyzer:
    def _analyze_source(self, code: str):
        """Run ASTAnalyzer with empty AST (exercises source-level paths)."""
        src = _src(code)
        aa = ASTAnalyzer([], src, "test.srv")
        return aa.analyze()

    def test_p006_via_ast_analyzer(self):
        code = '''
            fun factorial n
              if n <= 1
                return 1
              return n * factorial n - 1 + factorial n - 2
        '''
        findings = self._analyze_source(code)
        p006 = [f for f in findings if f.rule == "P006"]
        assert len(p006) >= 1

    def test_p010_unused_index(self):
        code = '''
            for i in range 10
              print "hello"
        '''
        findings = self._analyze_source(code)
        p010 = [f for f in findings if f.rule == "P010"]
        assert len(p010) >= 1
        assert "never used" in p010[0].message

    def test_p010_used_index_no_alert(self):
        code = '''
            for i in range 10
              print i
        '''
        findings = self._analyze_source(code)
        p010 = [f for f in findings if f.rule == "P010"]
        assert len(p010) == 0

    def test_p001_loop_invariant(self):
        code = '''
            total = 100
            for i in range 10
              x = total + 5
              print x
        '''
        findings = self._analyze_source(code)
        p001 = [f for f in findings if f.rule == "P001"]
        assert len(p001) >= 1
        assert "hoisted" in p001[0].message.lower() or "hoist" in p001[0].suggestion.lower()


# ── Rule Explanations ────────────────────────────────────────────────

class TestRuleExplanations:
    def test_all_rules_documented(self):
        expected_rules = [f"P{i:03d}" for i in range(1, 11)]
        for rule in expected_rules:
            assert rule in RULE_EXPLANATIONS, f"Missing explanation for {rule}"

    def test_explanation_structure(self):
        for rule, info in RULE_EXPLANATIONS.items():
            assert "name" in info, f"{rule} missing 'name'"
            assert "description" in info, f"{rule} missing 'description'"
            assert "example" in info, f"{rule} missing 'example'"
            assert "impact" in info, f"{rule} missing 'impact'"
            assert len(info["description"]) > 20, f"{rule} description too short"


# ── HTML Report ──────────────────────────────────────────────────────

class TestHTMLReport:
    def test_empty_report_html(self):
        html = generate_html([])
        assert "sauravoptimize" in html
        assert "No optimization findings" in html

    def test_html_contains_findings(self):
        r = OptReport(file="test.srv", score=70, findings=[
            OptFinding(rule="P003", severity=Severity.HIGH, line=5,
                       message="string concat in loop", suggestion="use join",
                       auto_fixable=True, estimated_speedup="O(n²)→O(n)"),
        ])
        html = generate_html([r])
        assert "P003" in html
        assert "string concat in loop" in html
        assert "fixable" in html
        assert "sev-high" in html

    def test_html_score_classes(self):
        good = OptReport(file="a.srv", score=90)
        html = generate_html([good])
        assert "score-good" in html


# ── Full Pipeline (analyze_file) ─────────────────────────────────────

class TestAnalyzeFile:
    def test_analyze_nonexistent_file(self):
        report = analyze_file("/nonexistent/path/x.srv")
        assert report.parse_error != ""

    def test_analyze_empty_file(self, tmp_path):
        p = _write_srv(tmp_path, "empty.srv", "")
        report = analyze_file(p)
        assert report.score == 100
        assert len(report.findings) == 0

    def test_analyze_clean_code(self, tmp_path):
        code = '''
            x = 10
            y = 20
            print x + y
        '''
        p = _write_srv(tmp_path, "clean.srv", code)
        report = analyze_file(p)
        assert report.score >= 80

    def test_analyze_with_severity_filter(self, tmp_path):
        code = '''
            result = ""
            for item in items
              result = result + item
            x = 42
            x = 99
        '''
        p = _write_srv(tmp_path, "mixed.srv", code)

        # Only high
        report_high = analyze_file(p, severity_filter="high")
        for f in report_high.findings:
            assert f.severity == Severity.HIGH

        # Only low
        report_low = analyze_file(p, severity_filter="low")
        for f in report_low.findings:
            assert f.severity == Severity.LOW

    def test_deduplication(self, tmp_path):
        """Same rule+line should not appear twice."""
        code = '''
            fun fib n
              if n <= 1
                return n
              return fib n - 1 + fib n - 2
        '''
        p = _write_srv(tmp_path, "dedup.srv", code)
        report = analyze_file(p)
        keys = [(f.rule, f.line) for f in report.findings]
        assert len(keys) == len(set(keys)), "Duplicate findings detected"

    def test_findings_sorted_by_severity_then_line(self, tmp_path):
        code = '''
            x = 42
            x = 99
            result = ""
            for item in items
              result = result + item
        '''
        p = _write_srv(tmp_path, "sorted.srv", code)
        report = analyze_file(p)
        sev_order = {"high": 0, "medium": 1, "low": 2}
        for i in range(len(report.findings) - 1):
            a = report.findings[i]
            b = report.findings[i + 1]
            assert (sev_order.get(a.severity, 9), a.line) <= \
                   (sev_order.get(b.severity, 9), b.line), \
                   f"Findings not sorted: {a.rule}@{a.line} ({a.severity}) before {b.rule}@{b.line} ({b.severity})"

    def test_report_to_dict_json_serializable(self, tmp_path):
        code = '''
            for i in range 10
              print "hello"
        '''
        p = _write_srv(tmp_path, "json.srv", code)
        report = analyze_file(p)
        d = report.to_dict()
        # Should be JSON-serializable
        s = json.dumps(d)
        assert isinstance(json.loads(s), dict)


# ── Severity Constants ───────────────────────────────────────────────

class TestSeverity:
    def test_values(self):
        assert Severity.HIGH == "high"
        assert Severity.MEDIUM == "medium"
        assert Severity.LOW == "low"

    def test_penalty_map_complete(self):
        for sev in [Severity.HIGH, Severity.MEDIUM, Severity.LOW]:
            assert sev in SEVERITY_PENALTY
