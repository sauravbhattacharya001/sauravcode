#!/usr/bin/env python3
"""Tests for sauravlearn.py — Interactive tutorial system."""

import importlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

import sauravlearn


class TestRunCode(unittest.TestCase):
    """Test the code runner."""

    def test_simple_print(self):
        out, err = sauravlearn.run_code('print "hello"')
        self.assertIn("hello", out)
        self.assertIsNone(err)

    def test_arithmetic(self):
        out, err = sauravlearn.run_code("print 3 + 4")
        self.assertIn("7", out)
        self.assertIsNone(err)

    def test_variable(self):
        out, err = sauravlearn.run_code("x = 10\nprint x")
        self.assertIn("10", out)
        self.assertIsNone(err)

    def test_error_capture(self):
        out, err = sauravlearn.run_code("x = 1 / 0")
        self.assertIsNotNone(err)

    def test_multiline(self):
        code = "a = 5\nb = 10\nprint a + b"
        out, err = sauravlearn.run_code(code)
        self.assertIn("15", out)
        self.assertIsNone(err)

    def test_empty_code(self):
        out, err = sauravlearn.run_code("")
        self.assertEqual(out.strip(), "")


class TestLessons(unittest.TestCase):
    """Test lesson structure and content."""

    def test_lessons_exist(self):
        lessons = sauravlearn._lessons()
        self.assertGreaterEqual(len(lessons), 10)

    def test_lesson_structure(self):
        for lesson in sauravlearn._lessons():
            self.assertIn("title", lesson)
            self.assertIn("explanation", lesson)
            self.assertIn("examples", lesson)
            self.assertIn("exercises", lesson)
            self.assertIsInstance(lesson["title"], str)
            self.assertIsInstance(lesson["explanation"], str)
            self.assertIsInstance(lesson["examples"], list)
            self.assertIsInstance(lesson["exercises"], list)

    def test_exercises_have_required_fields(self):
        for lesson in sauravlearn._lessons():
            for ex in lesson["exercises"]:
                self.assertIn("prompt", ex)
                self.assertIn("hint", ex)
                self.assertIn("check", ex)
                self.assertTrue(callable(ex["check"]))

    def test_lesson_titles_unique(self):
        titles = [l["title"] for l in sauravlearn._lessons()]
        self.assertEqual(len(titles), len(set(titles)))

    def test_examples_run_successfully(self):
        """Every example in every lesson should run without error."""
        for lesson in sauravlearn._lessons():
            for code, _ in lesson["examples"]:
                out, err = sauravlearn.run_code(code)
                self.assertIsNone(err, f"Example failed in '{lesson['title']}': {code}\nError: {err}")

    def test_hints_solve_exercises(self):
        """Every hint should pass its exercise check."""
        for lesson in sauravlearn._lessons():
            for ex in lesson["exercises"]:
                out, err = sauravlearn.run_code(ex["hint"])
                self.assertTrue(
                    ex["check"](out, err),
                    f"Hint failed in '{lesson['title']}': {ex['hint']}\nOutput: {out!r}, Error: {err}"
                )

    def test_lesson_count(self):
        self.assertEqual(len(sauravlearn._lessons()), 12)


class TestProgress(unittest.TestCase):
    """Test progress persistence."""

    def setUp(self):
        self._orig = sauravlearn.PROGRESS_FILE
        self._tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        self._tmp.close()
        sauravlearn.PROGRESS_FILE = self._tmp.name

    def tearDown(self):
        sauravlearn.PROGRESS_FILE = self._orig
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_load_empty(self):
        os.unlink(self._tmp.name)
        progress = sauravlearn._load_progress()
        self.assertEqual(progress, {"completed": []})

    def test_save_and_load(self):
        sauravlearn._save_progress({"completed": [0, 1, 2]})
        progress = sauravlearn._load_progress()
        self.assertEqual(progress["completed"], [0, 1, 2])

    def test_corrupted_file(self):
        with open(self._tmp.name, "w") as f:
            f.write("not json")
        progress = sauravlearn._load_progress()
        self.assertEqual(progress, {"completed": []})

    def test_save_overwrite(self):
        sauravlearn._save_progress({"completed": [0]})
        sauravlearn._save_progress({"completed": [0, 1]})
        progress = sauravlearn._load_progress()
        self.assertEqual(len(progress["completed"]), 2)


class TestColorHelpers(unittest.TestCase):
    """Test color formatting."""

    def test_color_on(self):
        sauravlearn._use_color = True
        result = sauravlearn._green("hello")
        self.assertIn("hello", result)
        self.assertIn("\033[", result)

    def test_color_off(self):
        sauravlearn._use_color = False
        result = sauravlearn._green("hello")
        self.assertEqual(result, "hello")

    def test_all_colors(self):
        sauravlearn._use_color = True
        for fn in [sauravlearn._green, sauravlearn._red, sauravlearn._cyan,
                    sauravlearn._yellow, sauravlearn._bold, sauravlearn._dim,
                    sauravlearn._magenta]:
            result = fn("test")
            self.assertIn("test", result)

    def tearDown(self):
        sauravlearn._use_color = True


class TestCLI(unittest.TestCase):
    """Test CLI argument handling."""

    def setUp(self):
        self._orig = sauravlearn.PROGRESS_FILE
        self._tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        self._tmp.close()
        sauravlearn.PROGRESS_FILE = self._tmp.name
        sauravlearn._save_progress({"completed": [0, 1]})

    def tearDown(self):
        sauravlearn.PROGRESS_FILE = self._orig
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_list(self):
        with patch("sys.argv", ["sauravlearn.py", "--list"]):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                sauravlearn.main()
            output = buf.getvalue()
            self.assertIn("Lessons", output)

    def test_progress(self):
        with patch("sys.argv", ["sauravlearn.py", "--progress"]):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                sauravlearn.main()
            output = buf.getvalue()
            self.assertIn("2/12", output)

    def test_reset(self):
        with patch("sys.argv", ["sauravlearn.py", "--reset"]):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                sauravlearn.main()
            progress = sauravlearn._load_progress()
            self.assertEqual(progress["completed"], [])

    def test_invalid_lesson(self):
        with patch("sys.argv", ["sauravlearn.py", "--lesson", "99"]):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                sauravlearn.main()
            self.assertIn("doesn't exist", buf.getvalue())


import contextlib

if __name__ == "__main__":
    unittest.main()
