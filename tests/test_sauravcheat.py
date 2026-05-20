#!/usr/bin/env python3
"""Tests for sauravcheat - terminal cheat sheet for the sauravcode language.

Covers the formatting helpers, section printer, CLI dispatch (--list, --help,
section query, full output), color toggling via NO_COLOR / --no-color, and the
fallback path for an unknown section query.

These tests intentionally exercise `main()` end-to-end so that any drift in
argv parsing, the SECTIONS structure, or the keyword-highlight loop in
`_format_code_block` (which has a non-obvious break-on-first-keyword
contract) is caught.
"""

import importlib
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _reload_module(no_color=False, argv=None):
    """Reload sauravcheat with a controlled environment / argv.

    sauravcheat captures NO_COLOR + ``--no-color`` at *import time*, so a clean
    reimport is the only honest way to test color behavior. We mutate
    ``sys.argv`` and ``os.environ`` for the duration of the import and restore
    them afterwards (we cannot use a ``with`` block because the module captures
    state at import time and would otherwise see the restore happen before the
    caller observes it).
    """
    new_argv = list(argv) if argv is not None else ["sauravcheat.py"]
    saved_argv = sys.argv
    saved_no_color = os.environ.get("NO_COLOR")
    try:
        sys.argv = new_argv
        if no_color:
            os.environ["NO_COLOR"] = "1"
        else:
            os.environ.pop("NO_COLOR", None)
        if "sauravcheat" in sys.modules:
            del sys.modules["sauravcheat"]
        return importlib.import_module("sauravcheat")
    finally:
        sys.argv = saved_argv
        if saved_no_color is None:
            os.environ.pop("NO_COLOR", None)
        else:
            os.environ["NO_COLOR"] = saved_no_color


class TestColorHelpers(unittest.TestCase):
    def test_color_wraps_when_enabled(self):
        mod = _reload_module(no_color=False)
        out = mod._c("31", "hi")
        self.assertEqual(out, "\033[31mhi\033[0m")

    def test_color_passthrough_when_no_color_env(self):
        mod = _reload_module(no_color=True)
        self.assertEqual(mod._c("31", "hi"), "hi")
        # Convenience wrappers must respect the same flag.
        self.assertEqual(mod._h("title"), "title")
        self.assertEqual(mod._k("kw"), "kw")
        self.assertEqual(mod._s("val"), "val")
        self.assertEqual(mod._d("dim"), "dim")
        self.assertEqual(mod._b("bold"), "bold")

    def test_color_passthrough_when_no_color_arg(self):
        mod = _reload_module(no_color=False,
                             argv=["sauravcheat.py", "--no-color"])
        self.assertEqual(mod._c("32", "x"), "x")

    def test_convenience_wrappers_use_distinct_codes(self):
        mod = _reload_module(no_color=False)
        # Codes are intentional; if someone changes them, this test should
        # break and prompt an update to docs/screenshots.
        self.assertIn("1;36", mod._h("x"))   # bold cyan heading
        self.assertIn("33", mod._k("x"))     # yellow keyword
        self.assertIn("32", mod._s("x"))     # green value
        self.assertIn("2m", mod._d("x"))     # dim
        self.assertTrue(mod._b("x").startswith("\033[1m"))


class TestSectionsStructure(unittest.TestCase):
    """SECTIONS is the source of truth for --list output. Pin its shape."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _reload_module(no_color=True)

    def test_sections_nonempty(self):
        self.assertGreater(len(self.mod.SECTIONS), 0)

    def test_section_tuple_shape(self):
        for entry in self.mod.SECTIONS:
            self.assertEqual(len(entry), 3,
                             f"each SECTIONS entry must be (key, title, entries): {entry!r}")
            key, title, entries = entry
            self.assertIsInstance(key, str)
            self.assertIsInstance(title, str)
            self.assertIsInstance(entries, list)
            self.assertGreater(len(entries), 0,
                               f"section {key!r} is empty")
            for row in entries:
                self.assertEqual(len(row), 2,
                                 f"entry in section {key!r} must be (label, code): {row!r}")
                label, code = row
                self.assertIsInstance(label, str)
                self.assertIsInstance(code, str)
                self.assertTrue(label.strip(), f"empty label in section {key!r}")
                self.assertTrue(code.strip(), f"empty code in section {key!r}")

    def test_section_keys_unique(self):
        keys = [s[0] for s in self.mod.SECTIONS]
        self.assertEqual(len(keys), len(set(keys)),
                         "SECTIONS keys must be unique so --list / prefix match are deterministic")

    def test_section_keys_lowercase(self):
        # The CLI lowercases the user's query before prefix matching, so keys
        # must already be lowercase or some sections become unreachable.
        for key, _, _ in self.mod.SECTIONS:
            self.assertEqual(key, key.lower(),
                             f"section key {key!r} is not lowercase; CLI prefix match would miss it")


class TestFormatCodeBlock(unittest.TestCase):
    def setUp(self):
        self.mod = _reload_module(no_color=True)

    def test_indents_every_line(self):
        out = self.mod._format_code_block("a\nb\nc")
        for line in out.split("\n"):
            self.assertTrue(line.startswith("      "),
                            f"line not indented: {line!r}")

    def test_preserves_line_count(self):
        src = "line1\nline2\nline3\nline4"
        out = self.mod._format_code_block(src)
        self.assertEqual(out.count("\n"), src.count("\n"))

    def test_no_color_leaves_keywords_intact(self):
        # With NO_COLOR active, _k(...) is identity, so keywords appear raw.
        out = self.mod._format_code_block("fn greet name")
        self.assertIn("fn greet name", out)

    def test_with_color_highlights_first_matching_keyword(self):
        mod = _reload_module(no_color=False)
        out = mod._format_code_block("fn greet name")
        # The yellow keyword color (33) must wrap "fn".
        self.assertIn("\033[33mfn\033[0m", out)

    def test_handles_empty_string(self):
        out = self.mod._format_code_block("")
        # Empty input still produces a single (indented) empty line.
        self.assertEqual(out, "      ")


class TestPrintSection(unittest.TestCase):
    def setUp(self):
        self.mod = _reload_module(no_color=True)

    def _capture(self, *args, **kwargs):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.mod._print_section(*args, **kwargs)
        return buf.getvalue()

    def test_prints_title(self):
        out = self._capture("variables", "Variables & Types",
                            [("Assign", "x = 42")])
        self.assertIn("Variables & Types", out)
        self.assertIn("x = 42", out)
        self.assertIn("# Assign", out)

    def test_compact_mode_uses_first_line_only(self):
        entries = [("Two-line", "first\nsecond")]
        out = self._capture("k", "Title", entries, compact=True)
        self.assertIn("first", out)
        self.assertNotIn("second", out,
                         "compact mode should only render the first line of multi-line code")
        # Compact mode must not emit the '# label' comment marker used by full mode.
        self.assertNotIn("# Two-line", out)

    def test_full_mode_renders_multi_line(self):
        entries = [("Loop", "for i in range 1 3\n    print i\nend")]
        out = self._capture("k", "Title", entries, compact=False)
        self.assertIn("for i in range 1 3", out)
        self.assertIn("    print i", out)
        self.assertIn("end", out)

    def test_handles_empty_entries(self):
        out = self._capture("k", "Empty Section", [])
        # Title still rendered, no entry rows.
        self.assertIn("Empty Section", out)


class TestMainCLI(unittest.TestCase):
    def _run_main(self, argv, no_color=True):
        # Import-time argv only matters for the ``--no-color`` flag detection;
        # ``main()`` re-reads sys.argv at call time, so we re-apply argv right
        # around the call.
        mod = _reload_module(no_color=no_color, argv=argv)
        buf = io.StringIO()
        saved_argv = sys.argv
        try:
            sys.argv = list(argv)
            with redirect_stdout(buf):
                mod.main()
        finally:
            sys.argv = saved_argv
        return buf.getvalue(), mod

    def test_list_flag_prints_every_section_key(self):
        out, mod = self._run_main(["sauravcheat.py", "--list"])
        for key, _, _ in mod.SECTIONS:
            self.assertIn(key, out, f"--list missed section key {key!r}")
        self.assertIn("Available sections", out)

    def test_help_flag_prints_docstring(self):
        out, mod = self._run_main(["sauravcheat.py", "--help"])
        self.assertEqual(out.strip(), (mod.__doc__ or "").strip())

    def test_short_help_flag(self):
        out, mod = self._run_main(["sauravcheat.py", "-h"])
        self.assertEqual(out.strip(), (mod.__doc__ or "").strip())

    def test_full_output_when_no_args(self):
        out, mod = self._run_main(["sauravcheat.py"])
        # Header banner and footer links should both be present.
        self.assertIn("sauravcode", out)
        self.assertIn("github.com/sauravbhattacharya001/sauravcode", out)
        # Every section title must appear in the full dump.
        for _, title, _ in mod.SECTIONS:
            self.assertIn(title, out, f"full dump missing section title {title!r}")

    def test_section_query_exact_match(self):
        _, mod = self._run_main(["sauravcheat.py", "--list"])
        # Pick the first key deterministically and query it.
        key, title, _ = mod.SECTIONS[0]
        out, _ = self._run_main(["sauravcheat.py", key])
        self.assertIn(title, out)

    def test_section_query_prefix_match(self):
        _, mod = self._run_main(["sauravcheat.py", "--list"])
        key, title, _ = mod.SECTIONS[0]
        # Prefix of length 1 must still resolve via startswith().
        out, _ = self._run_main(["sauravcheat.py", key[:1]])
        self.assertIn(title, out)

    def test_section_query_case_insensitive(self):
        _, mod = self._run_main(["sauravcheat.py", "--list"])
        key, title, _ = mod.SECTIONS[0]
        out, _ = self._run_main(["sauravcheat.py", key.upper()])
        self.assertIn(title, out)

    def test_unknown_section_reports_error(self):
        out, _ = self._run_main(["sauravcheat.py", "definitely-not-a-section-xyz"])
        self.assertIn("Unknown section", out)
        self.assertIn("--list", out)

    def test_compact_flag_shortens_output(self):
        full, _ = self._run_main(["sauravcheat.py"])
        compact, _ = self._run_main(["sauravcheat.py", "--compact"])
        # Compact mode must produce strictly less output (drops the '# label'
        # comment rows and trims multi-line code to first line).
        self.assertLess(len(compact), len(full),
                        "--compact must be shorter than the full cheat sheet")

    def test_flags_are_excluded_from_section_args(self):
        # ``--no-color`` is a flag, not a section query. Passing only flags
        # should fall through to the full cheat sheet path, not "unknown
        # section".
        out, _ = self._run_main(
            ["sauravcheat.py", "--no-color"], no_color=False
        )
        self.assertNotIn("Unknown section", out)
        self.assertIn("sauravcode", out)


if __name__ == "__main__":
    unittest.main()
