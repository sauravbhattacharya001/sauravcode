#!/usr/bin/env python3
"""Tests for sauravchallenge.py — coding challenge runner."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from io import StringIO

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sauravchallenge as sc


class TestChallengeData(unittest.TestCase):
    """Test challenge definitions are well-formed."""

    def test_all_challenges_have_required_fields(self):
        for c in sc.CHALLENGES:
            for field in ("id", "title", "category", "difficulty", "description", "hint", "starter", "tests"):
                self.assertIn(field, c, f"Challenge {c.get('id', '?')} missing {field}")

    def test_unique_ids(self):
        ids = [c["id"] for c in sc.CHALLENGES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_sequential_ids(self):
        ids = [c["id"] for c in sc.CHALLENGES]
        self.assertEqual(ids, list(range(1, len(ids) + 1)))

    def test_valid_difficulties(self):
        for c in sc.CHALLENGES:
            self.assertIn(c["difficulty"], sc.DIFFICULTIES)

    def test_valid_categories(self):
        for c in sc.CHALLENGES:
            self.assertIn(c["category"], sc.CATEGORIES)

    def test_all_tests_have_expected_output(self):
        for c in sc.CHALLENGES:
            for t in c["tests"]:
                self.assertIn("expected_output", t)

    def test_at_least_30_challenges(self):
        self.assertGreaterEqual(len(sc.CHALLENGES), 30)

    def test_multiple_categories(self):
        self.assertGreaterEqual(len(sc.CATEGORIES), 5)

    def test_multiple_difficulties(self):
        for d in ["easy", "medium", "hard"]:
            count = sum(1 for c in sc.CHALLENGES if c["difficulty"] == d)
            self.assertGreater(count, 0, f"No {d} challenges")


class TestGetChallenge(unittest.TestCase):
    def test_valid_id(self):
        c = sc._get_challenge(1)
        self.assertIsNotNone(c)
        self.assertEqual(c["id"], 1)

    def test_invalid_id(self):
        self.assertIsNone(sc._get_challenge(9999))

    def test_zero_id(self):
        self.assertIsNone(sc._get_challenge(0))


class TestProgress(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orig = sc._progress_file
        self.pf = Path(self.tmpdir) / "progress.json"
        sc._progress_file = lambda: self.pf

    def tearDown(self):
        sc._progress_file = self.orig
        if self.pf.exists():
            self.pf.unlink()
        os.rmdir(self.tmpdir)

    def test_load_empty(self):
        p = sc._load_progress()
        self.assertEqual(p["solved"], [])

    def test_save_and_load(self):
        sc._save_progress({"solved": [1, 2], "attempts": {"1": 3}})
        p = sc._load_progress()
        self.assertEqual(p["solved"], [1, 2])
        self.assertEqual(p["attempts"]["1"], 3)

    def test_reset(self):
        sc._save_progress({"solved": [1], "attempts": {}})
        sc._reset_progress()
        self.assertFalse(self.pf.exists())

    def test_corrupt_file(self):
        self.pf.write_text("not json", encoding="utf-8")
        p = sc._load_progress()
        self.assertEqual(p["solved"], [])


class TestListChallenges(unittest.TestCase):
    def test_list_all(self):
        with patch("sys.stdout", new_callable=StringIO) as out:
            sc.list_challenges(show_status=False)
        output = out.getvalue()
        self.assertIn("Hello World", output)
        self.assertIn("Merge Sort", output)

    def test_filter_difficulty(self):
        with patch("sys.stdout", new_callable=StringIO) as out:
            sc.list_challenges(difficulty="hard", show_status=False)
        output = out.getvalue()
        self.assertIn("hard", output)
        self.assertNotIn("easy", output.split("solved")[0].lower().replace("hard", ""))

    def test_filter_category(self):
        with patch("sys.stdout", new_callable=StringIO) as out:
            sc.list_challenges(category="algorithms", show_status=False)
        output = out.getvalue()
        self.assertIn("Bubble Sort", output)

    def test_no_matches(self):
        with patch("sys.stdout", new_callable=StringIO) as out:
            sc.list_challenges(difficulty="easy", category="algorithms", show_status=False)
        # algorithms has no easy challenges
        output = out.getvalue()
        self.assertIn("No challenges", output)


class TestShowChallenge(unittest.TestCase):
    def test_show_valid(self):
        with patch("sys.stdout", new_callable=StringIO) as out:
            sc.show_challenge(1)
        output = out.getvalue()
        self.assertIn("Hello World", output)
        self.assertIn("Hint", output)

    def test_show_invalid(self):
        with patch("sys.stdout", new_callable=StringIO) as out:
            sc.show_challenge(9999)
        self.assertIn("not found", out.getvalue())


class TestShowStarter(unittest.TestCase):
    def test_starter_code(self):
        with patch("sys.stdout", new_callable=StringIO) as out:
            sc.show_starter(1)
        output = out.getvalue()
        self.assertIn("Hello World", output)

    def test_invalid(self):
        with patch("sys.stdout", new_callable=StringIO) as out:
            sc.show_starter(9999)
        self.assertIn("not found", out.getvalue())


class TestStats(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orig = sc._progress_file
        self.pf = Path(self.tmpdir) / "progress.json"
        sc._progress_file = lambda: self.pf

    def tearDown(self):
        sc._progress_file = self.orig
        if self.pf.exists():
            self.pf.unlink()
        os.rmdir(self.tmpdir)

    def test_stats_empty(self):
        with patch("sys.stdout", new_callable=StringIO) as out:
            sc.show_stats()
        self.assertIn("0/", out.getvalue())

    def test_stats_with_progress(self):
        sc._save_progress({"solved": [1, 2, 3], "attempts": {"1": 1, "2": 3, "3": 2}})
        with patch("sys.stdout", new_callable=StringIO) as out:
            sc.show_stats()
        output = out.getvalue()
        self.assertIn("3/", output)
        self.assertIn("Total attempts: 6", output)


class TestRandomChallenge(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orig = sc._progress_file
        self.pf = Path(self.tmpdir) / "progress.json"
        sc._progress_file = lambda: self.pf

    def tearDown(self):
        sc._progress_file = self.orig
        if self.pf.exists():
            self.pf.unlink()
        os.rmdir(self.tmpdir)

    def test_random_picks_unsolved(self):
        sc._save_progress({"solved": [1], "attempts": {}})
        with patch("sys.stdout", new_callable=StringIO) as out:
            sc.random_challenge()
        output = out.getvalue()
        self.assertNotIn("Challenge #1:", output)

    def test_all_solved(self):
        all_ids = [c["id"] for c in sc.CHALLENGES]
        sc._save_progress({"solved": all_ids, "attempts": {}})
        with patch("sys.stdout", new_callable=StringIO) as out:
            sc.random_challenge()
        self.assertIn("mastered", out.getvalue())


class TestExport(unittest.TestCase):
    def test_json_export(self):
        with patch("sys.stdout", new_callable=StringIO) as out:
            sc.export_challenges("json")
        data = json.loads(out.getvalue())
        self.assertEqual(len(data), len(sc.CHALLENGES))

    def test_csv_export(self):
        with patch("sys.stdout", new_callable=StringIO) as out:
            sc.export_challenges("csv")
        output = out.getvalue().strip()
        # CSV may have multi-line fields; just check header and that data exists
        self.assertIn("id,title,category,difficulty", output)
        self.assertIn("Hello World", output)

    def test_unknown_format(self):
        with patch("sys.stdout", new_callable=StringIO) as out:
            sc.export_challenges("xml")
        self.assertIn("Unknown", out.getvalue())


class TestColorize(unittest.TestCase):
    def test_easy(self):
        result = sc._colorize_diff("easy")
        self.assertIn("easy", result)

    def test_unknown(self):
        result = sc._colorize_diff("unknown")
        self.assertIn("unknown", result)


class TestAttemptChallenge(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orig = sc._progress_file
        self.pf = Path(self.tmpdir) / "progress.json"
        sc._progress_file = lambda: self.pf

    def tearDown(self):
        sc._progress_file = self.orig
        if self.pf.exists():
            self.pf.unlink()
        try:
            os.rmdir(self.tmpdir)
        except OSError:
            pass

    def test_invalid_challenge(self):
        with patch("sys.stdout", new_callable=StringIO):
            result = sc.attempt_challenge(9999, "fake.srv")
        self.assertFalse(result)

    def test_missing_file(self):
        with patch("sys.stdout", new_callable=StringIO):
            result = sc.attempt_challenge(1, "nonexistent.srv")
        self.assertFalse(result)

    def test_no_solution_provided(self):
        with patch("sys.stdout", new_callable=StringIO):
            result = sc.attempt_challenge(1)
        self.assertFalse(result)

    def test_correct_solution(self):
        sol = Path(self.tmpdir) / "sol.srv"
        sol.write_text('print("Hello, World!")\n', encoding="utf-8")
        with patch("sys.stdout", new_callable=StringIO) as out:
            result = sc.attempt_challenge(1, str(sol))
        self.assertTrue(result)
        self.assertIn("SOLVED", out.getvalue())

    def test_wrong_solution(self):
        sol = Path(self.tmpdir) / "sol.srv"
        sol.write_text('print("Wrong!")\n', encoding="utf-8")
        with patch("sys.stdout", new_callable=StringIO) as out:
            result = sc.attempt_challenge(1, str(sol))
        self.assertFalse(result)
        self.assertIn("FAILED", out.getvalue())

    def test_attempt_increments(self):
        sol = Path(self.tmpdir) / "sol.srv"
        sol.write_text('print("Wrong!")\n', encoding="utf-8")
        with patch("sys.stdout", new_callable=StringIO):
            sc.attempt_challenge(1, str(sol))
            sc.attempt_challenge(1, str(sol))
        p = sc._load_progress()
        self.assertEqual(p["attempts"]["1"], 2)


if __name__ == "__main__":
    unittest.main()
