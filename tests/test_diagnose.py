"""Tests for sauravdiagnose — autonomous runtime error diagnosis engine."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from sauravdiagnose import (
    DiagnosisEngine, KnowledgeBase, ErrorCategory, ErrorPattern,
    ERROR_PATTERNS, Diagnosis, apply_fixes, generate_html_report,
    main, _html_esc,
)


class TestErrorPatternDatabase(unittest.TestCase):
    """Test the error pattern definitions."""

    def test_all_patterns_have_required_fields(self):
        for p in ERROR_PATTERNS:
            self.assertIsInstance(p.category, str)
            self.assertIsInstance(p.pattern, str)
            self.assertIsInstance(p.description, str)
            self.assertIsInstance(p.suggestion_template, str)
            self.assertGreater(p.confidence, 0)
            self.assertLessEqual(p.confidence, 1.0)

    def test_patterns_compile(self):
        import re
        for p in ERROR_PATTERNS:
            try:
                re.compile(p.pattern, re.IGNORECASE)
            except re.error:
                self.fail(f"Pattern '{p.pattern}' failed to compile")

    def test_unique_categories_covered(self):
        categories = {p.category for p in ERROR_PATTERNS}
        expected = {
            ErrorCategory.UNDEFINED_VAR, ErrorCategory.TYPE_ERROR,
            ErrorCategory.INDEX_OOB, ErrorCategory.DIVISION_ZERO,
            ErrorCategory.STACK_OVERFLOW, ErrorCategory.SYNTAX_ERROR,
            ErrorCategory.EMPTY_COLLECTION, ErrorCategory.ARGUMENT_ERROR,
        }
        for cat in expected:
            self.assertIn(cat, categories, f"Missing pattern for {cat}")

    def test_auto_fixable_have_templates(self):
        for p in ERROR_PATTERNS:
            if p.auto_fixable:
                self.assertTrue(p.fix_template,
                                f"Auto-fixable pattern {p.category} missing fix_template")


class TestKnowledgeBase(unittest.TestCase):
    """Test the persistent knowledge base."""

    def setUp(self):
        self.kb = KnowledgeBase()

    def test_empty_kb(self):
        self.assertEqual(self.kb.total_diagnoses, 0)
        self.assertEqual(self.kb.error_counts, {})
        self.assertEqual(self.kb.get_top_errors(), [])

    def test_record_diagnosis(self):
        d = Diagnosis(
            file="test.srv", line=5, category=ErrorCategory.TYPE_ERROR,
            error_message="Type mismatch", source_context=[],
            suggestions=[{"text": "fix it", "confidence": 0.8, "fix": "use to_int"}],
            confidence=0.85, auto_fixable=False,
        )
        self.kb.record(d)
        self.assertEqual(self.kb.total_diagnoses, 1)
        self.assertEqual(self.kb.error_counts[ErrorCategory.TYPE_ERROR], 1)
        self.assertEqual(self.kb.file_error_counts["test.srv"], 1)

    def test_multiple_records(self):
        for i in range(5):
            d = Diagnosis(
                file="a.srv", line=i, category=ErrorCategory.TYPE_ERROR,
                error_message=f"Error {i}", source_context=[],
                suggestions=[], confidence=0.8, auto_fixable=False,
            )
            self.kb.record(d)
        self.assertEqual(self.kb.total_diagnoses, 5)
        self.assertEqual(self.kb.error_counts[ErrorCategory.TYPE_ERROR], 5)

    def test_save_and_load(self):
        d = Diagnosis(
            file="test.srv", line=1, category=ErrorCategory.DIVISION_ZERO,
            error_message="div by zero", source_context=[],
            suggestions=[{"text": "check divisor", "confidence": 0.9, "fix": "guard"}],
            confidence=0.95, auto_fixable=True,
        )
        self.kb.record(d)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            path = f.name
        try:
            self.kb.save(path)
            loaded = KnowledgeBase.load(path)
            self.assertEqual(loaded.total_diagnoses, 1)
            self.assertEqual(loaded.error_counts[ErrorCategory.DIVISION_ZERO], 1)
        finally:
            os.unlink(path)

    def test_load_nonexistent(self):
        kb = KnowledgeBase.load("nonexistent_file_xyz.json")
        self.assertEqual(kb.total_diagnoses, 0)

    def test_load_corrupt(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("not json")
            path = f.name
        try:
            kb = KnowledgeBase.load(path)
            self.assertEqual(kb.total_diagnoses, 0)
        finally:
            os.unlink(path)

    def test_top_errors(self):
        self.kb.error_counts = {
            ErrorCategory.TYPE_ERROR: 10,
            ErrorCategory.INDEX_OOB: 5,
            ErrorCategory.DIVISION_ZERO: 3,
        }
        top = self.kb.get_top_errors(2)
        self.assertEqual(len(top), 2)
        self.assertEqual(top[0][0], ErrorCategory.TYPE_ERROR)

    def test_hotspot_files(self):
        self.kb.file_error_counts = {"a.srv": 10, "b.srv": 5, "c.srv": 1}
        hotspots = self.kb.get_hotspot_files(2)
        self.assertEqual(len(hotspots), 2)
        self.assertEqual(hotspots[0][0], "a.srv")

    def test_trend_stable(self):
        trend = self.kb.get_trend(ErrorCategory.TYPE_ERROR)
        self.assertEqual(trend, "stable")

    def test_history_capped(self):
        for i in range(250):
            d = Diagnosis(
                file="a.srv", line=1, category=ErrorCategory.TYPE_ERROR,
                error_message=f"err{i}", source_context=[],
                suggestions=[], confidence=0.8, auto_fixable=False,
            )
            self.kb.record(d)
        self.assertLessEqual(len(self.kb.error_history), 200)

    def test_common_fixes_tracked(self):
        d = Diagnosis(
            file="a.srv", line=1, category=ErrorCategory.TYPE_ERROR,
            error_message="type error", source_context=[],
            suggestions=[{"text": "use to_int", "confidence": 0.8, "fix": "to_int(x)"}],
            confidence=0.8, auto_fixable=False,
        )
        self.kb.record(d)
        self.assertIn("to_int(x)", self.kb.common_fixes[ErrorCategory.TYPE_ERROR])


class TestDiagnosisEngine(unittest.TestCase):
    """Test the diagnosis engine."""

    def setUp(self):
        self.engine = DiagnosisEngine(kb=KnowledgeBase())

    def test_diagnose_nonexistent_file(self):
        diags = self.engine.diagnose_file("nonexistent_xyz.srv")
        self.assertEqual(len(diags), 1)
        self.assertEqual(diags[0].category, ErrorCategory.IMPORT_ERROR)

    def test_diagnose_valid_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.srv',
                                          delete=False, encoding='utf-8') as f:
            f.write('x = 42\nprint x\n')
            path = f.name
        try:
            diags = self.engine.diagnose_file(path)
            # Valid sauravcode should have no runtime errors
            self.assertEqual(len(diags), 0)
        finally:
            os.unlink(path)

    def test_classify_undefined_var(self):
        diag = self.engine._classify_error(
            "test.srv", ["print x"],
            "Undefined variable 'x'", ""
        )
        self.assertEqual(diag.category, ErrorCategory.UNDEFINED_VAR)
        self.assertGreater(diag.confidence, 0.5)

    def test_classify_type_error(self):
        diag = self.engine._classify_error(
            "test.srv", ['set x to "hi" + 5'],
            "unsupported operand type for +: str and int", ""
        )
        self.assertEqual(diag.category, ErrorCategory.TYPE_ERROR)

    def test_classify_index_oob(self):
        diag = self.engine._classify_error(
            "test.srv", ["set x to items[10]"],
            "Index 10 out of range", ""
        )
        self.assertEqual(diag.category, ErrorCategory.INDEX_OOB)

    def test_classify_division_zero(self):
        diag = self.engine._classify_error(
            "test.srv", ["set x to 10 / 0"],
            "Division by zero", ""
        )
        self.assertEqual(diag.category, ErrorCategory.DIVISION_ZERO)
        self.assertGreaterEqual(diag.confidence, 0.9)

    def test_classify_stack_overflow(self):
        diag = self.engine._classify_error(
            "test.srv", ["function f", "  f()", "end"],
            "maximum recursion depth exceeded", ""
        )
        self.assertEqual(diag.category, ErrorCategory.STACK_OVERFLOW)

    def test_classify_empty_collection(self):
        diag = self.engine._classify_error(
            "test.srv", ["stack_pop(s)"],
            "stack_pop: stack is empty", ""
        )
        self.assertEqual(diag.category, ErrorCategory.EMPTY_COLLECTION)

    def test_classify_argument_error(self):
        diag = self.engine._classify_error(
            "test.srv", ["greet()"],
            "Function 'greet' expects 1 argument but got 0", ""
        )
        self.assertEqual(diag.category, ErrorCategory.ARGUMENT_ERROR)

    def test_classify_import_error(self):
        diag = self.engine._classify_error(
            "test.srv", ['import "missing.srv"'],
            "Cannot import 'missing.srv': not found", ""
        )
        self.assertEqual(diag.category, ErrorCategory.IMPORT_ERROR)

    def test_classify_generic_fallback(self):
        diag = self.engine._classify_error(
            "test.srv", ["???"],
            "Something totally unexpected happened XYZ123", ""
        )
        self.assertEqual(diag.category, ErrorCategory.RUNTIME_GENERIC)
        self.assertLess(diag.confidence, 0.5)

    def test_extract_line_from_message(self):
        line = self.engine._extract_line("Error on line 42", "")
        self.assertEqual(line, 42)

    def test_extract_line_from_traceback(self):
        tb = 'File "test.py", line 10\nFile "test.py", line 25'
        line = self.engine._extract_line("unknown", tb)
        self.assertEqual(line, 25)

    def test_extract_line_none(self):
        line = self.engine._extract_line("no line info", "no info")
        self.assertIsNone(line)

    def test_get_context(self):
        lines = [f"line {i}" for i in range(10)]
        ctx = self.engine._get_context(lines, 5, radius=2)
        self.assertTrue(any(">>>" in c for c in ctx))

    def test_get_context_edge(self):
        lines = ["only line"]
        ctx = self.engine._get_context(lines, 1)
        self.assertGreater(len(ctx), 0)

    def test_suggestions_include_kb_fixes(self):
        self.engine.kb.common_fixes[ErrorCategory.TYPE_ERROR] = ["use to_int()"]
        diag = self.engine._classify_error(
            "test.srv", ["bad"],
            "unsupported operand type", ""
        )
        fix_texts = [s.get("fix", "") for s in diag.suggestions]
        self.assertTrue(any("to_int" in f for f in fix_texts))

    def test_diagnose_directory_empty(self):
        with tempfile.TemporaryDirectory() as td:
            results = self.engine.diagnose_directory(td)
            self.assertEqual(len(results), 0)


class TestStaticAnalysis(unittest.TestCase):
    """Test static analysis checks."""

    def setUp(self):
        self.engine = DiagnosisEngine(kb=KnowledgeBase())

    def test_unclosed_string(self):
        diags = self.engine._static_analysis(
            "test.srv", 'set x to "hello\n', ['set x to "hello']
        )
        string_diags = [d for d in diags if d.category == ErrorCategory.SYNTAX_ERROR]
        self.assertGreater(len(string_diags), 0)

    def test_clean_code(self):
        diags = self.engine._static_analysis(
            "test.srv", 'print "hello"\n', ['print "hello"']
        )
        self.assertEqual(len(diags), 0)

    def test_comments_ignored(self):
        diags = self.engine._static_analysis(
            "test.srv", '# this is "fine\n', ['# this is "fine']
        )
        self.assertEqual(len(diags), 0)


class TestApplyFixes(unittest.TestCase):
    """Test the auto-fix mechanism."""

    def test_apply_fixes_dry_run(self):
        d = Diagnosis(
            file="test.srv", line=1, category=ErrorCategory.UNDEFINED_VAR,
            error_message="Undefined variable 'x'", source_context=[],
            suggestions=[], confidence=0.9, auto_fixable=True,
            fix_patch={"old": "print x", "new": "set x to 0\nprint x"},
        )
        applied = apply_fixes([d], dry_run=True)
        self.assertTrue(all("DRY-RUN" in a for a in applied))

    def test_apply_fixes_no_fixable(self):
        d = Diagnosis(
            file="test.srv", line=1, category=ErrorCategory.TYPE_ERROR,
            error_message="type error", source_context=[],
            suggestions=[], confidence=0.8, auto_fixable=False,
        )
        applied = apply_fixes([d])
        self.assertEqual(len(applied), 0)


class TestHTMLReport(unittest.TestCase):
    """Test HTML report generation."""

    def test_generates_valid_html(self):
        diags = {
            "test.srv": [
                Diagnosis(
                    file="test.srv", line=5,
                    category=ErrorCategory.TYPE_ERROR,
                    error_message="type mismatch",
                    source_context=["   5 | set x to 1 + \"hi\""],
                    suggestions=[{"text": "use to_str", "confidence": 0.8}],
                    confidence=0.85, auto_fixable=False,
                )
            ]
        }
        html = generate_html_report(diags, KnowledgeBase())
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("sauravdiagnose", html)
        self.assertIn("type_error", html)

    def test_empty_report(self):
        html = generate_html_report({}, KnowledgeBase())
        self.assertIn("No issues found", html)

    def test_html_escaping(self):
        self.assertEqual(_html_esc('<script>'), '&lt;script&gt;')
        self.assertEqual(_html_esc('"test"'), '&quot;test&quot;')

    def test_auto_fixable_badge(self):
        diags = {
            "b.srv": [Diagnosis(
                file="b.srv", line=2, category=ErrorCategory.INDEX_OOB,
                error_message="err2", source_context=[],
                suggestions=[], confidence=0.9, auto_fixable=True,
            )],
        }
        html = generate_html_report(diags, KnowledgeBase())
        self.assertIn("AUTO-FIXABLE", html)


class TestCLI(unittest.TestCase):
    """Test CLI entry points."""

    def test_kb_stats_empty(self):
        import io
        old = sys.stdout
        sys.stdout = io.StringIO()
        try:
            main(["--kb"])
        except SystemExit:
            pass
        finally:
            sys.stdout = old

    def test_top_errors_empty(self):
        import io
        old = sys.stdout
        sys.stdout = io.StringIO()
        try:
            main(["--top", "3"])
        except SystemExit:
            pass
        finally:
            sys.stdout = old

    def test_json_output(self):
        import io
        with tempfile.NamedTemporaryFile(mode='w', suffix='.srv',
                                          delete=False, encoding='utf-8') as f:
            f.write('x = 1\nprint x\n')
            path = f.name
        try:
            old = sys.stdout
            sys.stdout = io.StringIO()
            try:
                main([path, "--json"])
            except SystemExit:
                pass
            output = sys.stdout.getvalue()
            sys.stdout = old
            data = json.loads(output)
            self.assertIn("total_issues", data)
        finally:
            os.unlink(path)

    def test_html_output(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.srv',
                                          delete=False, encoding='utf-8') as f:
            f.write('x = 1\nprint x\n')
            srv_path = f.name
        html_path = srv_path + ".html"
        try:
            import io
            old = sys.stdout
            sys.stdout = io.StringIO()
            try:
                main([srv_path, "--html", html_path])
            except SystemExit:
                pass
            sys.stdout = old
            self.assertTrue(os.path.exists(html_path))
        finally:
            os.unlink(srv_path)
            if os.path.exists(html_path):
                os.unlink(html_path)


if __name__ == "__main__":
    unittest.main()
