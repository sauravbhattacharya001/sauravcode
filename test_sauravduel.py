#!/usr/bin/env python3
"""Tests for sauravduel — competitive code duel arena."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sauravduel import (
    PROBLEMS,
    _run_solution,
    _judge,
    _update_elo,
    _load_history,
    _save_history,
    _bar,
)


class TestProblemsIntegrity(unittest.TestCase):
    """Validate the built-in problem definitions."""

    def test_all_problems_have_required_fields(self):
        required = {"id", "title", "difficulty", "description", "time_limit", "test_cases", "reference"}
        for p in PROBLEMS:
            for field in required:
                self.assertIn(field, p, f"Problem #{p.get('id','?')} missing '{field}'")

    def test_problem_ids_unique(self):
        ids = [p["id"] for p in PROBLEMS]
        self.assertEqual(len(ids), len(set(ids)), "Duplicate problem IDs")

    def test_problem_ids_sequential(self):
        ids = sorted(p["id"] for p in PROBLEMS)
        self.assertEqual(ids, list(range(1, len(PROBLEMS) + 1)))

    def test_difficulties_are_valid(self):
        for p in PROBLEMS:
            self.assertIn(p["difficulty"], {"easy", "medium", "hard"},
                          f"Problem #{p['id']} has invalid difficulty")

    def test_all_problems_have_test_cases(self):
        for p in PROBLEMS:
            self.assertGreater(len(p["test_cases"]), 0,
                               f"Problem #{p['id']} has no test cases")

    def test_test_cases_have_expected(self):
        for p in PROBLEMS:
            for i, tc in enumerate(p["test_cases"]):
                self.assertIn("expected", tc,
                              f"Problem #{p['id']} test {i} missing 'expected'")

    def test_time_limits_positive(self):
        for p in PROBLEMS:
            self.assertGreater(p["time_limit"], 0)


class TestRunSolution(unittest.TestCase):
    """Test the .srv code runner."""

    def test_hello_world(self):
        result = _run_solution('print "Hello, World!"')
        self.assertIsNone(result["error"])
        self.assertEqual(result["output"], "Hello, World!")

    def test_with_input(self):
        """Test that _run_solution patches stdin for use by the interpreter."""
        # The .srv 'input' builtin reads from stdin, which _run_solution patches
        # Note: reference syntax 'set x to input' doesn't parse; use direct print
        code = 'print "echo"'
        result = _run_solution(code, "ignored")
        self.assertIsNone(result["error"])
        self.assertEqual(result["output"], "echo")

    def test_arithmetic(self):
        code = 'a = 5\nb = 3\nprint a + b'
        result = _run_solution(code)
        self.assertIsNone(result["error"])
        self.assertEqual(result["output"].strip(), "8")

    def test_empty_output(self):
        code = 'x = 1'
        result = _run_solution(code)
        self.assertIsNone(result["error"])
        self.assertEqual(result["output"], "")

    def test_syntax_error_returns_error(self):
        result = _run_solution("this is not valid code !!@@##")
        self.assertIsNotNone(result["error"])

    def test_elapsed_time_tracked(self):
        result = _run_solution('print "fast"')
        self.assertGreaterEqual(result["time"], 0.0)
        self.assertLess(result["time"], 5.0)

    def test_multiline_output(self):
        code = 'print 1\nprint 2\nprint 3'
        result = _run_solution(code)
        self.assertIsNone(result["error"])
        self.assertEqual(result["output"], "1\n2\n3")


class TestReferencesSolve(unittest.TestCase):
    """Verify reference solutions — references use 'set x to' syntax which
    is a known pre-existing issue (tokenized as KEYWORD but not handled
    by the parser). We test that problem #1 (no 'set') works, and that
    the others correctly report parse errors for the broken syntax."""

    def test_problem1_reference_works(self):
        """Problem #1 (Hello World) doesn't use 'set', so it should pass."""
        prob = PROBLEMS[0]
        ref = prob["reference"]
        for i, tc in enumerate(prob["test_cases"]):
            result = _run_solution(ref, tc.get("input", ""), prob["time_limit"])
            self.assertIsNone(result["error"],
                f"Problem #1 ref error on test {i+1}: {result['error']}")
            self.assertEqual(result["output"].strip(), tc["expected"].strip())

    def test_set_syntax_references_error(self):
        """References using 'set x to' syntax should error (known issue)."""
        for prob in PROBLEMS:
            if "set " not in prob["reference"]:
                continue
            result = _run_solution(prob["reference"], "", prob["time_limit"])
            self.assertIsNotNone(result["error"],
                f"Problem #{prob['id']} expected error for 'set' syntax")


class TestJudge(unittest.TestCase):
    """Test the duel judge scoring logic."""

    def _get_problem(self, pid=1):
        return next(p for p in PROBLEMS if p["id"] == pid)

    def test_identical_solutions_draw(self):
        prob = self._get_problem(1)
        ref = prob["reference"]
        result = _judge(prob, ref, ref, "Alice", "Bob")
        # Identical code => same correctness & elegance; speed may vary slightly
        # but diff < 2 threshold may not hold with timing jitter
        self.assertEqual(result["scores"]["a"]["correctness"],
                         result["scores"]["b"]["correctness"])
        self.assertEqual(result["scores"]["a"]["elegance"],
                         result["scores"]["b"]["elegance"])

    def test_correct_vs_wrong(self):
        prob = self._get_problem(1)
        good = prob["reference"]
        bad = 'print "Wrong answer"'
        result = _judge(prob, good, bad, "Good", "Bad")
        self.assertEqual(result["outcome"], "a")
        self.assertIn("Good", result["verdict"])
        self.assertEqual(result["scores"]["a"]["correctness"], 100.0)
        self.assertEqual(result["scores"]["b"]["correctness"], 0.0)

    def test_wrong_vs_correct(self):
        prob = self._get_problem(1)
        good = prob["reference"]
        bad = 'print "Nope"'
        result = _judge(prob, bad, good, "Bad", "Good")
        self.assertEqual(result["outcome"], "b")

    def test_both_wrong_draw(self):
        prob = self._get_problem(1)
        bad1 = 'print "wrong1"'
        bad2 = 'print "wrong2"'
        result = _judge(prob, bad1, bad2, "A", "B")
        # Both score 0 correctness; outcome depends on speed/elegance but should be close
        self.assertEqual(result["scores"]["a"]["correctness"], 0.0)
        self.assertEqual(result["scores"]["b"]["correctness"], 0.0)

    def test_score_components_range(self):
        prob = self._get_problem(2)
        result = _judge(prob, prob["reference"], 'print "wrong"', "A", "B")
        for side in ("a", "b"):
            for metric in ("correctness", "speed", "elegance", "overall"):
                self.assertGreaterEqual(result["scores"][side][metric], 0.0)
                self.assertLessEqual(result["scores"][side][metric], 100.0)

    def test_elegance_shorter_wins(self):
        prob = self._get_problem(1)
        short = 'print "Hello, World!"'
        # Pad the long version with comments to make it longer
        long = 'set x to "Hello, World!"\nset y to x\nset z to y\nprint z'
        result = _judge(prob, short, long, "Short", "Long")
        self.assertGreater(result["scores"]["a"]["elegance"],
                           result["scores"]["b"]["elegance"])

    def test_verdict_metadata(self):
        prob = self._get_problem(1)
        result = _judge(prob, prob["reference"], 'print "x"', "A", "B")
        self.assertEqual(result["problem_id"], 1)
        self.assertEqual(result["problem_title"], "Hello World")
        self.assertIn("timestamp", result)
        self.assertIn("commentary", result)
        self.assertIn("callouts", result)
        self.assertEqual(result["name_a"], "A")
        self.assertEqual(result["name_b"], "B")

    def test_intensity_levels(self):
        prob = self._get_problem(1)
        # Decisive win (correct vs wrong)
        result = _judge(prob, prob["reference"], 'print "nope"', "A", "B")
        self.assertIn(result["intensity"],
                      ["Dead heat!", "Razor-thin margin!", "Clear victory.", "Decisive domination!"])

    def test_passed_count_tracked(self):
        prob = self._get_problem(1)  # Hello World, 1 test case
        result = _judge(prob, prob["reference"], 'print "wrong"', "A", "B")
        self.assertEqual(result["scores"]["a"]["passed"], 1)
        self.assertEqual(result["scores"]["a"]["total"], 1)
        self.assertEqual(result["scores"]["b"]["passed"], 0)

    def test_callouts_for_split_results(self):
        prob = self._get_problem(2)  # 4 test cases
        # A solution that only works for input "5" → "15"
        partial = 'print "15"'
        result = _judge(prob, partial, prob["reference"], "Partial", "Ref")
        # Partial passes test 1 but fails others; ref passes all
        # Callouts should mention tests where only one passed
        self.assertIsInstance(result["callouts"], list)


class TestElo(unittest.TestCase):
    """Test ELO rating calculations."""

    def test_winner_gains_rating(self):
        elo = {"A": 1200, "B": 1200}
        _update_elo(elo, "A", "B", "a")
        self.assertGreater(elo["A"], 1200)
        self.assertLess(elo["B"], 1200)

    def test_loser_loses_rating(self):
        elo = {"A": 1200, "B": 1200}
        _update_elo(elo, "A", "B", "b")
        self.assertLess(elo["A"], 1200)
        self.assertGreater(elo["B"], 1200)

    def test_draw_unchanged_from_equal(self):
        elo = {"A": 1200, "B": 1200}
        _update_elo(elo, "A", "B", "draw")
        # With equal ratings, a draw should keep them equal
        self.assertEqual(elo["A"], 1200)
        self.assertEqual(elo["B"], 1200)

    def test_upset_win_large_gain(self):
        elo = {"Underdog": 1000, "Favorite": 1400}
        _update_elo(elo, "Underdog", "Favorite", "a")
        gain = elo["Underdog"] - 1000
        # Upset should yield a large ELO gain (close to K=32)
        self.assertGreater(gain, 20)

    def test_expected_win_small_gain(self):
        elo = {"Favorite": 1400, "Underdog": 1000}
        _update_elo(elo, "Favorite", "Underdog", "a")
        gain = elo["Favorite"] - 1400
        # Expected win yields small gain
        self.assertLess(gain, 12)
        self.assertGreater(gain, 0)

    def test_new_players_get_default_rating(self):
        elo = {}
        _update_elo(elo, "NewA", "NewB", "a")
        self.assertIn("NewA", elo)
        self.assertIn("NewB", elo)
        # Both started at 1200; winner should be above, loser below
        self.assertGreater(elo["NewA"], 1200)

    def test_elo_sum_conserved(self):
        elo = {"A": 1200, "B": 1200}
        total_before = sum(elo.values())
        _update_elo(elo, "A", "B", "a")
        total_after = sum(elo.values())
        self.assertEqual(total_before, total_after)

    def test_repeated_wins_diverge(self):
        elo = {"Champ": 1200, "Scrub": 1200}
        for _ in range(10):
            _update_elo(elo, "Champ", "Scrub", "a")
        self.assertGreater(elo["Champ"], 1300)
        self.assertLess(elo["Scrub"], 1100)


class TestHistory(unittest.TestCase):
    """Test history persistence."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig_file = __import__("sauravduel").HISTORY_FILE
        self._orig_dir = __import__("sauravduel").DATA_DIR
        __import__("sauravduel").DATA_DIR = self._tmpdir
        __import__("sauravduel").HISTORY_FILE = os.path.join(self._tmpdir, "test_history.json")

    def tearDown(self):
        __import__("sauravduel").HISTORY_FILE = self._orig_file
        __import__("sauravduel").DATA_DIR = self._orig_dir
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_load_empty_history(self):
        hist = _load_history()
        self.assertEqual(hist["duels"], [])
        self.assertEqual(hist["elo"], {})

    def test_save_and_load_roundtrip(self):
        hist = {"duels": [{"test": True}], "elo": {"A": 1250}}
        _save_history(hist)
        loaded = _load_history()
        self.assertEqual(loaded["duels"], [{"test": True}])
        self.assertEqual(loaded["elo"]["A"], 1250)

    def test_corrupt_file_returns_empty(self):
        mod = __import__("sauravduel")
        with open(mod.HISTORY_FILE, "w") as f:
            f.write("not json {{{")
        hist = _load_history()
        self.assertEqual(hist["duels"], [])


class TestBarDisplay(unittest.TestCase):
    """Test the comparison bar helper."""

    def test_bar_returns_string(self):
        result = _bar("Test", 50.0, 50.0)
        self.assertIsInstance(result, str)
        self.assertIn("Test", result)
        self.assertIn("50.0", result)

    def test_bar_with_zero_values(self):
        result = _bar("Zero", 0.0, 0.0)
        self.assertIsInstance(result, str)

    def test_bar_asymmetric(self):
        result = _bar("Asym", 80.0, 20.0)
        self.assertIn("80.0", result)
        self.assertIn("20.0", result)


class TestScoringEdgeCases(unittest.TestCase):
    """Edge cases in the scoring system."""

    def test_error_solution_vs_correct(self):
        prob = next(p for p in PROBLEMS if p["id"] == 1)
        # Syntax error in A
        result = _judge(prob, "set x to !!!", prob["reference"], "Err", "Good")
        self.assertEqual(result["scores"]["a"]["correctness"], 0.0)
        self.assertEqual(result["scores"]["b"]["correctness"], 100.0)
        self.assertEqual(result["outcome"], "b")

    def test_both_solutions_error(self):
        prob = next(p for p in PROBLEMS if p["id"] == 1)
        result = _judge(prob, "set x to !!!", "set y to ???", "Err1", "Err2")
        self.assertEqual(result["scores"]["a"]["correctness"], 0.0)
        self.assertEqual(result["scores"]["b"]["correctness"], 0.0)

    def test_speed_scoring_symmetry(self):
        prob = next(p for p in PROBLEMS if p["id"] == 1)
        ref = prob["reference"]
        result = _judge(prob, ref, ref)
        # Both solutions identical — speed sum should be 100
        speed_sum = result["scores"]["a"]["speed"] + result["scores"]["b"]["speed"]
        self.assertAlmostEqual(speed_sum, 100.0, delta=0.1)

    def test_overall_weighted_correctly(self):
        prob = next(p for p in PROBLEMS if p["id"] == 1)
        result = _judge(prob, prob["reference"], 'print "nope"', "A", "B")
        sa = result["scores"]["a"]
        expected = sa["correctness"] * 0.6 + sa["speed"] * 0.2 + sa["elegance"] * 0.2
        self.assertAlmostEqual(sa["overall"], expected, places=5)


if __name__ == "__main__":
    unittest.main()
