#!/usr/bin/env python3
"""Tests for sauravcheat -- cheat sheet module."""

import os
import sys
import unittest
from io import StringIO

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import sauravcheat


class TestColorHelpers(unittest.TestCase):
    """Test ANSI color helper functions."""

    def test_color_wraps_text(self):
        """_c should wrap text in ANSI codes when color is enabled."""
        original = sauravcheat._NO_COLOR
        try:
            sauravcheat._NO_COLOR = False
            result = sauravcheat._c("1;36", "hello")
            self.assertIn("hello", result)
            self.assertIn("\033[1;36m", result)
            self.assertIn("\033[0m", result)
        finally:
            sauravcheat._NO_COLOR = original

    def test_no_color_returns_plain(self):
        """_c should return plain text when NO_COLOR is set."""
        original = sauravcheat._NO_COLOR
        try:
            sauravcheat._NO_COLOR = True
            result = sauravcheat._c("1;36", "hello")
            self.assertEqual(result, "hello")
        finally:
            sauravcheat._NO_COLOR = original

    def test_heading_helper(self):
        original = sauravcheat._NO_COLOR
        try:
            sauravcheat._NO_COLOR = True
            self.assertEqual(sauravcheat._h("test"), "test")
        finally:
            sauravcheat._NO_COLOR = original

    def test_keyword_helper(self):
        original = sauravcheat._NO_COLOR
        try:
            sauravcheat._NO_COLOR = True
            self.assertEqual(sauravcheat._k("fn"), "fn")
        finally:
            sauravcheat._NO_COLOR = original


class TestSections(unittest.TestCase):
    """Test cheat sheet content structure."""

    def test_sections_not_empty(self):
        self.assertGreater(len(sauravcheat.SECTIONS), 0)

    def test_section_structure(self):
        """Each section should be (key, title, entries)."""
        for section in sauravcheat.SECTIONS:
            self.assertEqual(len(section), 3)
            key, title, entries = section
            self.assertIsInstance(key, str)
            self.assertIsInstance(title, str)
            self.assertIsInstance(entries, list)
            for entry in entries:
                self.assertEqual(len(entry), 2)
                self.assertIsInstance(entry[0], str)  # label
                self.assertIsInstance(entry[1], str)  # code

    def test_section_keys_unique(self):
        keys = [s[0] for s in sauravcheat.SECTIONS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_known_sections_present(self):
        keys = {s[0] for s in sauravcheat.SECTIONS}
        for expected in ["variables", "functions", "control", "strings", "lists"]:
            self.assertIn(expected, keys)


class TestFormatCodeBlock(unittest.TestCase):
    def test_single_line(self):
        result = sauravcheat._format_code_block('x = 42')
        self.assertIn("x = 42", result)

    def test_multiline(self):
        result = sauravcheat._format_code_block('fn greet name\n    print name\nend')
        lines = result.split("\n")
        self.assertEqual(len(lines), 3)

    def test_keyword_highlighting_in_color_mode(self):
        original = sauravcheat._NO_COLOR
        try:
            sauravcheat._NO_COLOR = False
            result = sauravcheat._format_code_block('fn greet name')
            # Should contain ANSI codes for keyword highlighting
            self.assertIn("\033[", result)
        finally:
            sauravcheat._NO_COLOR = original


class TestPrintFunctions(unittest.TestCase):
    """Test print functions produce output."""

    def _capture(self, func, *args, **kwargs):
        old = sys.stdout
        sys.stdout = StringIO()
        try:
            func(*args, **kwargs)
            return sys.stdout.getvalue()
        finally:
            sys.stdout = old

    def test_print_header(self):
        output = self._capture(sauravcheat._print_header)
        self.assertIn("sauravcode", output)
        self.assertIn("Cheat Sheet", output)

    def test_print_footer(self):
        output = self._capture(sauravcheat._print_footer)
        self.assertIn("github.com", output)

    def test_print_section_normal(self):
        entries = [("Test label", "x = 42")]
        output = self._capture(sauravcheat._print_section, "test", "Test Section", entries, False)
        self.assertIn("Test Section", output)
        self.assertIn("x = 42", output)

    def test_print_section_compact(self):
        entries = [("Test label", "x = 42\ny = 10")]
        output = self._capture(sauravcheat._print_section, "test", "Test Section", entries, True)
        self.assertIn("Test label", output)
        # Compact mode should only show first line of code
        self.assertNotIn("y = 10", output)


class TestMainFunction(unittest.TestCase):
    """Test main() with various argument combinations."""

    def _run_main(self, args):
        old_argv = sys.argv
        old_stdout = sys.stdout
        sys.stdout = StringIO()
        try:
            sys.argv = ["sauravcheat.py"] + args
            sauravcheat.main()
            return sys.stdout.getvalue()
        finally:
            sys.argv = old_argv
            sys.stdout = old_stdout

    def test_list_sections(self):
        output = self._run_main(["--list"])
        self.assertIn("Available sections", output)
        self.assertIn("variables", output)

    def test_specific_section(self):
        output = self._run_main(["variables"])
        self.assertIn("Variables", output)

    def test_unknown_section(self):
        output = self._run_main(["nonexistent_section_xyz"])
        self.assertIn("Unknown section", output)

    def test_full_cheat_sheet(self):
        output = self._run_main([])
        self.assertIn("sauravcode", output)
        self.assertIn("Variables", output)
        self.assertIn("Functions", output)

    def test_compact_mode(self):
        output = self._run_main(["--compact", "variables"])
        self.assertIn("Variables", output)

    def test_partial_section_match(self):
        """Section lookup should match prefixes."""
        output = self._run_main(["var"])
        self.assertIn("Variables", output)


if __name__ == "__main__":
    unittest.main()
