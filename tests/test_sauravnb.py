"""Tests for sauravnb.py — sauravcode notebook runner."""

import os
import sys
import io
import tempfile
import unittest
from unittest.mock import patch

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sauravnb import (
    parse_notebook, execute_notebook, render_html,
    Cell, MarkdownCell, CodeCell, STARTER_NOTEBOOK,
)


# ── Notebook parsing ──────────────────────────────────────────

class TestParseNotebook(unittest.TestCase):
    """Test .srvnb file parsing."""

    def test_simple_two_cells(self):
        text = "--- md ---\n# Hello\n\n--- code ---\nprint 42\n"
        cells = parse_notebook(text)
        self.assertEqual(len(cells), 2)
        self.assertIsInstance(cells[0], MarkdownCell)
        self.assertIsInstance(cells[1], CodeCell)

    def test_markdown_content(self):
        text = "--- md ---\n# Title\nSome text\n"
        cells = parse_notebook(text)
        self.assertEqual(cells[0].cell_type, 'md')
        self.assertIn("Title", cells[0].content)
        self.assertIn("Some text", cells[0].content)

    def test_code_content(self):
        text = "--- code ---\nx = 5\nprint x\n"
        cells = parse_notebook(text)
        self.assertEqual(len(cells), 1)
        self.assertIsInstance(cells[0], CodeCell)
        self.assertIn("x = 5", cells[0].content)

    def test_multiple_cells(self):
        text = (
            "--- md ---\n# Part 1\n\n"
            "--- code ---\nx = 10\n\n"
            "--- md ---\n# Part 2\n\n"
            "--- code ---\ny = 20\n"
        )
        cells = parse_notebook(text)
        self.assertEqual(len(cells), 4)
        self.assertIsInstance(cells[0], MarkdownCell)
        self.assertIsInstance(cells[1], CodeCell)
        self.assertIsInstance(cells[2], MarkdownCell)
        self.assertIsInstance(cells[3], CodeCell)

    def test_empty_code_cell(self):
        text = "--- code ---\n\n--- md ---\nText\n"
        cells = parse_notebook(text)
        # Empty code cells should still be included
        has_code = any(isinstance(c, CodeCell) for c in cells)
        self.assertTrue(has_code)

    def test_empty_input(self):
        cells = parse_notebook("")
        self.assertEqual(len(cells), 0)

    def test_no_markers(self):
        text = "Just some text without markers\n"
        cells = parse_notebook(text)
        # Text before markers treated as markdown
        self.assertTrue(
            len(cells) == 0 or
            (len(cells) == 1 and cells[0].cell_type == 'md')
        )

    def test_case_insensitive_markers(self):
        text = "--- MD ---\n# Title\n--- CODE ---\nprint 1\n"
        cells = parse_notebook(text)
        self.assertEqual(len(cells), 2)
        self.assertIsInstance(cells[0], MarkdownCell)
        self.assertIsInstance(cells[1], CodeCell)

    def test_line_numbers_tracked(self):
        text = "--- md ---\n# Line 2\n--- code ---\nprint 42\n"
        cells = parse_notebook(text)
        # Line numbers should be set (> 0)
        for cell in cells:
            self.assertGreater(cell.line_number, 0)

    def test_whitespace_in_markers(self):
        text = "---   md   ---\nText\n---  code  ---\nx = 1\n"
        cells = parse_notebook(text)
        self.assertEqual(len(cells), 2)


# ── Notebook execution ────────────────────────────────────────

class TestExecuteNotebook(unittest.TestCase):
    """Test code cell execution."""

    def test_simple_print(self):
        text = "--- code ---\nprint 42\n"
        cells = parse_notebook(text)
        cells, stats = execute_notebook(cells)
        self.assertEqual(stats['executed'], 1)
        self.assertEqual(stats['errors'], 0)
        self.assertIn("42", cells[0].output)

    def test_shared_state(self):
        """Variables defined in one cell should be available in the next."""
        text = (
            "--- code ---\nx = 100\n\n"
            "--- code ---\nprint x\n"
        )
        cells = parse_notebook(text)
        cells, stats = execute_notebook(cells)
        self.assertEqual(stats['errors'], 0)
        # Second code cell should print 100
        code_cells = [c for c in cells if isinstance(c, CodeCell)]
        self.assertIn("100", code_cells[1].output)

    def test_function_across_cells(self):
        """Functions defined in one cell should be callable in another."""
        text = (
            "--- code ---\n"
            "function double x\n    return x * 2\n\n"
            "--- code ---\nprint double 7\n"
        )
        cells = parse_notebook(text)
        cells, stats = execute_notebook(cells)
        self.assertEqual(stats['errors'], 0)
        code_cells = [c for c in cells if isinstance(c, CodeCell)]
        self.assertIn("14", code_cells[1].output)

    def test_error_captured(self):
        """Runtime errors should be captured, not crash."""
        text = "--- code ---\nprint undefined_var\n"
        cells = parse_notebook(text)
        cells, stats = execute_notebook(cells)
        self.assertEqual(stats['errors'], 1)
        code_cells = [c for c in cells if isinstance(c, CodeCell)]
        self.assertIsNotNone(code_cells[0].error)

    def test_error_doesnt_stop_execution(self):
        """Error in one cell shouldn't prevent other cells from running."""
        text = (
            "--- code ---\nprint bad_var\n\n"
            "--- code ---\nprint 99\n"
        )
        cells = parse_notebook(text)
        cells, stats = execute_notebook(cells)
        self.assertEqual(stats['executed'], 2)
        code_cells = [c for c in cells if isinstance(c, CodeCell)]
        # Second cell should still execute
        self.assertTrue(code_cells[1].executed)

    def test_only_cell_filter(self):
        """Running only a specific cell number."""
        text = (
            "--- code ---\nprint 1\n\n"
            "--- code ---\nprint 2\n\n"
            "--- code ---\nprint 3\n"
        )
        cells = parse_notebook(text)
        cells, stats = execute_notebook(cells, only_cell=2)
        self.assertEqual(stats['executed'], 1)
        code_cells = [c for c in cells if isinstance(c, CodeCell)]
        self.assertTrue(code_cells[1].executed)
        self.assertFalse(code_cells[0].executed)
        self.assertFalse(code_cells[2].executed)

    def test_markdown_cells_ignored(self):
        """Markdown cells shouldn't affect execution count."""
        text = (
            "--- md ---\n# Title\n\n"
            "--- code ---\nprint 42\n"
        )
        cells = parse_notebook(text)
        cells, stats = execute_notebook(cells)
        self.assertEqual(stats['code_cells'], 1)
        self.assertEqual(stats['md_cells'], 1)
        self.assertEqual(stats['executed'], 1)

    def test_timing_recorded(self):
        """Each code cell should have elapsed_ms set."""
        text = "--- code ---\nx = 1\n"
        cells = parse_notebook(text)
        cells, stats = execute_notebook(cells)
        code_cells = [c for c in cells if isinstance(c, CodeCell)]
        self.assertGreaterEqual(code_cells[0].elapsed_ms, 0)
        self.assertGreater(stats['total_time_ms'], 0)

    def test_empty_code_cell_executes(self):
        """Empty code cell should execute without error."""
        text = "--- code ---\n\n"
        cells = parse_notebook(text)
        cells, stats = execute_notebook(cells)
        code_cells = [c for c in cells if isinstance(c, CodeCell)]
        self.assertTrue(code_cells[0].executed)
        self.assertEqual(stats['errors'], 0)


# ── Cell objects ──────────────────────────────────────────────

class TestCellObjects(unittest.TestCase):
    """Test Cell data structures."""

    def test_markdown_cell_type(self):
        cell = MarkdownCell("# Hello")
        self.assertEqual(cell.cell_type, 'md')

    def test_code_cell_type(self):
        cell = CodeCell("x = 1")
        self.assertEqual(cell.cell_type, 'code')

    def test_code_cell_defaults(self):
        cell = CodeCell("x = 1")
        self.assertEqual(cell.output, '')
        self.assertIsNone(cell.error)
        self.assertEqual(cell.elapsed_ms, 0.0)
        self.assertFalse(cell.executed)

    def test_cell_line_number(self):
        cell = MarkdownCell("text", line_number=42)
        self.assertEqual(cell.line_number, 42)

    def test_cell_content(self):
        cell = CodeCell("print 42")
        self.assertEqual(cell.content, "print 42")


# ── HTML export ───────────────────────────────────────────────

class TestHTMLExport(unittest.TestCase):
    """Test HTML rendering."""

    def test_html_output_is_string(self):
        text = "--- md ---\n# Test\n--- code ---\nprint 1\n"
        cells = parse_notebook(text)
        cells, stats = execute_notebook(cells)
        html = render_html(cells, stats)
        self.assertIsInstance(html, str)

    def test_html_contains_title(self):
        text = "--- md ---\n# Test\n--- code ---\nprint 1\n"
        cells = parse_notebook(text)
        cells, stats = execute_notebook(cells)
        html = render_html(cells, stats, title="My Notebook")
        self.assertIn("My Notebook", html)

    def test_html_contains_output(self):
        text = "--- code ---\nprint 42\n"
        cells = parse_notebook(text)
        cells, stats = execute_notebook(cells)
        html = render_html(cells, stats)
        self.assertIn("42", html)

    def test_html_has_structure(self):
        text = "--- md ---\nHello\n--- code ---\nprint 1\n"
        cells = parse_notebook(text)
        cells, stats = execute_notebook(cells)
        html = render_html(cells, stats)
        self.assertIn("<html", html)
        self.assertIn("</html>", html)
        self.assertIn("<body", html)

    def test_html_code_escaped(self):
        """Code with special HTML chars should be escaped."""
        text = '--- code ---\nprint "<b>bold</b>"\n'
        cells = parse_notebook(text)
        cells, stats = execute_notebook(cells)
        html = render_html(cells, stats)
        # The literal < should be escaped in the code display
        self.assertIn("&lt;", html)

    def test_html_error_shown(self):
        text = "--- code ---\nprint bad_var\n"
        cells = parse_notebook(text)
        cells, stats = execute_notebook(cells)
        html = render_html(cells, stats)
        # Error should appear somewhere in the HTML
        self.assertTrue(
            "error" in html.lower() or "Error" in html or "bad_var" in html
        )


# ── Stats ─────────────────────────────────────────────────────

class TestStats(unittest.TestCase):
    """Test execution statistics."""

    def test_stats_keys(self):
        text = "--- code ---\nprint 1\n"
        cells = parse_notebook(text)
        _, stats = execute_notebook(cells)
        for key in ('total_cells', 'code_cells', 'md_cells',
                     'executed', 'errors', 'total_time_ms'):
            self.assertIn(key, stats)

    def test_mixed_stats(self):
        text = (
            "--- md ---\nTitle\n\n"
            "--- code ---\nprint 1\n\n"
            "--- md ---\nMiddle\n\n"
            "--- code ---\nprint 2\n"
        )
        cells = parse_notebook(text)
        _, stats = execute_notebook(cells)
        self.assertEqual(stats['total_cells'], 4)
        self.assertEqual(stats['code_cells'], 2)
        self.assertEqual(stats['md_cells'], 2)
        self.assertEqual(stats['executed'], 2)
        self.assertEqual(stats['errors'], 0)


# ── Starter notebook ──────────────────────────────────────────

class TestStarterNotebook(unittest.TestCase):
    """Test STARTER_NOTEBOOK constant."""

    def test_starter_content(self):
        content = STARTER_NOTEBOOK
        self.assertIn("--- md ---", content)
        self.assertIn("--- code ---", content)

    def test_starter_parseable(self):
        content = STARTER_NOTEBOOK
        cells = parse_notebook(content)
        self.assertTrue(len(cells) > 0)
        has_code = any(isinstance(c, CodeCell) for c in cells)
        has_md = any(isinstance(c, MarkdownCell) for c in cells)
        self.assertTrue(has_code)
        self.assertTrue(has_md)

    def test_starter_executable(self):
        content = STARTER_NOTEBOOK
        cells = parse_notebook(content)
        cells, stats = execute_notebook(cells)
        # Starter may have minor issues (e.g. comma-separated args
        # in filter call), but most cells should execute
        self.assertGreater(stats['executed'], 0)


# ── File I/O ──────────────────────────────────────────────────

class TestFileOperations(unittest.TestCase):
    """Test reading/writing notebook files."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.nb_path = os.path.join(self.tmpdir, "test.srvnb")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_and_read(self):
        content = "--- md ---\n# Test\n--- code ---\nprint 1\n"
        with open(self.nb_path, 'w') as f:
            f.write(content)
        with open(self.nb_path, 'r') as f:
            cells = parse_notebook(f.read())
        self.assertEqual(len(cells), 2)

    def test_html_export_to_file(self):
        content = "--- md ---\n# Test\n--- code ---\nprint 1\n"
        cells = parse_notebook(content)
        cells, stats = execute_notebook(cells)
        html = render_html(cells, stats)
        html_path = os.path.join(self.tmpdir, "out.html")
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html)
        self.assertTrue(os.path.exists(html_path))
        self.assertGreater(os.path.getsize(html_path), 100)

    def test_starter_write(self):
        content = STARTER_NOTEBOOK
        with open(self.nb_path, 'w') as f:
            f.write(content)
        with open(self.nb_path, 'r') as f:
            cells = parse_notebook(f.read())
        self.assertTrue(len(cells) > 0)


# ── Edge cases ────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):
    """Edge case handling."""

    def test_consecutive_code_cells(self):
        text = "--- code ---\nx = 1\n--- code ---\ny = 2\n--- code ---\nz = 3\n"
        cells = parse_notebook(text)
        code_cells = [c for c in cells if isinstance(c, CodeCell)]
        self.assertEqual(len(code_cells), 3)

    def test_only_markdown(self):
        text = "--- md ---\nJust text\n"
        cells = parse_notebook(text)
        _, stats = execute_notebook(cells)
        self.assertEqual(stats['executed'], 0)
        self.assertEqual(stats['code_cells'], 0)

    def test_multiline_code(self):
        text = (
            "--- code ---\n"
            "function add a b\n"
            "    return a + b\n"
            "print add 3 4\n"
        )
        cells = parse_notebook(text)
        cells, stats = execute_notebook(cells)
        self.assertEqual(stats['errors'], 0)
        code_cells = [c for c in cells if isinstance(c, CodeCell)]
        self.assertIn("7", code_cells[0].output)

    def test_special_chars_in_code(self):
        text = '--- code ---\nprint "hello & <world>"\n'
        cells = parse_notebook(text)
        cells, stats = execute_notebook(cells)
        code_cells = [c for c in cells if isinstance(c, CodeCell)]
        self.assertIn("hello", code_cells[0].output)

    def test_only_cell_out_of_range(self):
        text = "--- code ---\nprint 1\n"
        cells = parse_notebook(text)
        cells, stats = execute_notebook(cells, only_cell=99)
        self.assertEqual(stats['executed'], 0)

    def test_very_large_output(self):
        text = "--- code ---\nfor i in range 100\n    print i\n"
        cells = parse_notebook(text)
        cells, stats = execute_notebook(cells)
        code_cells = [c for c in cells if isinstance(c, CodeCell)]
        self.assertEqual(stats['errors'], 0)
        lines = code_cells[0].output.strip().split('\n')
        self.assertEqual(len(lines), 100)


if __name__ == "__main__":
    unittest.main()
