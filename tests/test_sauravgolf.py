#!/usr/bin/env python3
"""Tests for sauravgolf — code-golf challenge harness.

Covers the static challenge data (no dupes, monotonically increasing IDs, valid
difficulty + par ranges, every test entry has an expected output), the scoring
helpers (`_count_chars`, `_medal`), score-file load/save (including corrupt-file
recovery), running a real .srv solution end-to-end through `_run_solution` and
`_run_tests`, and the CLI dispatch surface (`--list`, `--show`, `--tips`,
`--stats`, `--leaderboard`, `--reset`, `--export`, `--random`).

Score persistence is rerouted into a temp directory so the suite never touches
the developer's `.golf_scores.json`.
"""

import importlib
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh_golf(tmp_score_path):
    """Import (or re-import) sauravgolf with SCORE_FILE pointed at a tmp path."""
    if "sauravgolf" in sys.modules:
        del sys.modules["sauravgolf"]
    mod = importlib.import_module("sauravgolf")
    mod.SCORE_FILE = tmp_score_path
    return mod


class TestChallengeData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)  # start without scores
        self.mod = _fresh_golf(self.tmp.name)

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_ids_are_unique_and_sequential(self):
        ids = [c["id"] for c in self.mod.CHALLENGES]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(ids), len(set(ids)))
        # First challenge starts at 1, no gaps.
        self.assertEqual(ids[0], 1)
        self.assertEqual(ids, list(range(1, len(ids) + 1)))

    def test_titles_are_unique(self):
        titles = [c["title"] for c in self.mod.CHALLENGES]
        self.assertEqual(len(titles), len(set(titles)))

    def test_each_challenge_has_required_fields(self):
        required = {"id", "title", "difficulty", "description",
                    "par", "tests", "hint"}
        for ch in self.mod.CHALLENGES:
            with self.subTest(challenge=ch["id"]):
                self.assertTrue(required.issubset(ch.keys()))
                self.assertIn(ch["difficulty"], {"easy", "medium", "hard"})
                self.assertIsInstance(ch["par"], int)
                self.assertGreater(ch["par"], 0)
                self.assertTrue(ch["tests"], "challenge must have ≥1 test")
                for t in ch["tests"]:
                    self.assertIn("expected", t)

    def test_par_ranges_match_difficulty(self):
        # Soft sanity ranges — guard against typos like par=1000 on an easy.
        bounds = {"easy": (10, 100), "medium": (40, 130), "hard": (60, 250)}
        for ch in self.mod.CHALLENGES:
            lo, hi = bounds[ch["difficulty"]]
            self.assertGreaterEqual(ch["par"], lo,
                                    f"par too low for {ch['difficulty']} #{ch['id']}")
            self.assertLessEqual(ch["par"], hi,
                                 f"par too high for {ch['difficulty']} #{ch['id']}")


class TestScoringHelpers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.mod = _fresh_golf(self.tmp.name)

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_count_chars_ignores_blank_lines(self):
        # Blank / whitespace-only lines must not contribute to the score.
        code = "print 1\n\n   \nprint 2\n"
        # "print 1" = 7, "print 2" = 7  → 14
        self.assertEqual(self.mod._count_chars(code), 14)

    def test_count_chars_counts_whitespace_within_a_nonblank_line(self):
        # Per the docstring, only fully-blank lines are skipped — leading
        # indentation on a coded line still costs you.
        code = "    x = 1"
        self.assertEqual(self.mod._count_chars(code), len("    x = 1"))

    def test_medal_thresholds(self):
        self.assertEqual(self.mod._medal(10, 20), "[GOLD]")
        self.assertEqual(self.mod._medal(20, 20), "[SILVER]")
        self.assertEqual(self.mod._medal(21, 20), "[BRONZE]")


class TestScorePersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.mod = _fresh_golf(self.tmp.name)

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_load_returns_empty_when_file_missing(self):
        data = self.mod._load_scores()
        self.assertEqual(data, {"scores": {}, "attempts": {}})

    def test_save_then_load_roundtrip(self):
        payload = {"scores": {"1": 18}, "attempts": {"1": 3}}
        self.mod._save_scores(payload)
        self.assertEqual(self.mod._load_scores(), payload)

    def test_load_recovers_from_corrupt_json(self):
        with open(self.tmp.name, "w") as f:
            f.write("{not valid json")
        data = self.mod._load_scores()
        # Corrupt files must not crash callers — fall back to empty defaults.
        self.assertEqual(data, {"scores": {}, "attempts": {}})


class TestSolutionRunner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.mod = _fresh_golf(self.tmp.name)

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_hello_world_solution_passes(self):
        ch = next(c for c in self.mod.CHALLENGES if c["title"] == "Hello World")
        code = 'print "Hello, World!"'
        passed, total, _ = self.mod._run_tests(ch, code)
        self.assertEqual(passed, total)
        self.assertEqual(total, len(ch["tests"]))

    def test_failing_solution_reports_diff(self):
        ch = next(c for c in self.mod.CHALLENGES if c["title"] == "Hello World")
        passed, total, details = self.mod._run_tests(ch, 'print "nope"')
        self.assertEqual(passed, 0)
        self.assertFalse(details[0]["passed"])
        self.assertIn("nope", details[0]["got"])

    def test_run_solution_returns_error_string_on_parse_failure(self):
        # Malformed sauravcode source: unterminated string literal.
        out = self.mod._run_solution('print "unterminated')
        self.assertTrue(out.startswith("ERROR:"), f"got: {out!r}")


class TestCLI(unittest.TestCase):
    """End-to-end CLI dispatch via `cmd_*` helpers, with stdout captured."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.mod = _fresh_golf(self.tmp.name)

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def _capture(self, fn, args_obj):
        buf = io.StringIO()
        with redirect_stdout(buf):
            fn(args_obj)
        return buf.getvalue()

    def test_cmd_list_shows_all_challenges_and_unsolved_counter(self):
        args = mock.Mock(difficulty=None)
        out = self._capture(self.mod.cmd_list, args)
        for ch in self.mod.CHALLENGES:
            self.assertIn(ch["title"], out)
        self.assertIn(f"Solved: 0/{len(self.mod.CHALLENGES)}", out)

    def test_cmd_list_difficulty_filter(self):
        args = mock.Mock(difficulty="easy")
        out = self._capture(self.mod.cmd_list, args)
        # An easy title must show; a hard title must not.
        easy_titles = [c["title"] for c in self.mod.CHALLENGES if c["difficulty"] == "easy"]
        hard_titles = [c["title"] for c in self.mod.CHALLENGES if c["difficulty"] == "hard"]
        self.assertTrue(any(t in out for t in easy_titles))
        self.assertFalse(any(t in out for t in hard_titles))

    def test_cmd_show_unknown_id_does_not_crash(self):
        out = self._capture(self.mod.cmd_show, mock.Mock(show=9999))
        self.assertIn("not found", out)

    def test_cmd_show_known_id_includes_par_and_hint(self):
        out = self._capture(self.mod.cmd_show, mock.Mock(show=1))
        self.assertIn("Hello World", out)
        self.assertIn("Par:", out)
        self.assertIn("Hint:", out)

    def test_cmd_tips_prints_numbered_list(self):
        out = self._capture(self.mod.cmd_tips, None)
        self.assertIn("1.", out)
        self.assertIn("2.", out)

    def test_cmd_stats_handles_zero_solves(self):
        out = self._capture(self.mod.cmd_stats, None)
        self.assertIn("Solved: 0", out)

    def test_cmd_leaderboard_empty(self):
        out = self._capture(self.mod.cmd_leaderboard, mock.Mock(sort="id"))
        self.assertIn("No scores yet", out)

    def test_cmd_leaderboard_with_a_score(self):
        self.mod._save_scores({"scores": {"1": 18}, "attempts": {"1": 1}})
        out = self._capture(self.mod.cmd_leaderboard, mock.Mock(sort="id"))
        self.assertIn("Hello World", out)
        # Par for Hello World is 22; 18 chars beats it → GOLD medal + (-4) diff.
        self.assertIn("[GOLD]", out)
        self.assertIn("(-4)", out)

    def test_cmd_reset_removes_score_file(self):
        self.mod._save_scores({"scores": {"1": 18}, "attempts": {"1": 1}})
        self.assertTrue(os.path.exists(self.tmp.name))
        self._capture(self.mod.cmd_reset, None)
        self.assertFalse(os.path.exists(self.tmp.name))

    def test_cmd_export_json_outputs_one_entry_per_challenge(self):
        args = mock.Mock(export="json")
        out = self._capture(self.mod.cmd_export, args)
        data = json.loads(out)
        self.assertEqual(len(data), len(self.mod.CHALLENGES))
        for entry in data:
            self.assertIn("id", entry)
            self.assertIn("par", entry)

    def test_cmd_export_csv_has_header_and_one_row_per_challenge(self):
        args = mock.Mock(export="csv")
        out = self._capture(self.mod.cmd_export, args)
        # Header + N rows. Use splitlines() to be robust to trailing newline.
        rows = [r for r in out.splitlines() if r.strip()]
        self.assertEqual(rows[0].split(",")[0], "id")
        self.assertEqual(len(rows), 1 + len(self.mod.CHALLENGES))

    def test_cmd_random_when_all_solved_returns_congratulations(self):
        scores = {str(c["id"]): c["par"] for c in self.mod.CHALLENGES}
        self.mod._save_scores({"scores": scores, "attempts": {}})
        out = self._capture(self.mod.cmd_random, mock.Mock(difficulty=None, show=None))
        self.assertIn("All matching challenges solved", out)


class TestPlayUpdatesScores(unittest.TestCase):
    """`cmd_play` should record a new personal best on a passing solution."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.mod = _fresh_golf(self.tmp.name)
        # Write a real solution file so cmd_play takes the file branch.
        self.solfile = tempfile.NamedTemporaryFile(
            suffix=".srv", mode="w", delete=False, encoding="utf-8")
        self.solfile.write('print "Hello, World!"')
        self.solfile.close()

    def tearDown(self):
        for p in (self.tmp.name, self.solfile.name):
            if os.path.exists(p):
                os.unlink(p)

    def test_play_records_personal_best(self):
        args = mock.Mock(play=1, stdin=False, file=self.solfile.name)
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.mod.cmd_play(args)
        out = buf.getvalue()
        self.assertIn("ALL TESTS PASSED", out)
        scores = self.mod._load_scores()
        # Solution is `print "Hello, World!"` = 21 chars (no trailing newline
        # in the file). We don't hard-code the exact number — just assert that
        # *a* best score was recorded for challenge #1.
        self.assertIn("1", scores["scores"])
        self.assertEqual(scores["attempts"]["1"], 1)


if __name__ == "__main__":
    unittest.main()
