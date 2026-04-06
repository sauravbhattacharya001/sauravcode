#!/usr/bin/env python3
"""sauravgolf — Code golf challenges for sauravcode (.srv).

Solve programming puzzles in the fewest characters possible!
Built-in challenges with personal best tracking and par scores.

Usage:
    python sauravgolf.py                          # List all golf challenges
    python sauravgolf.py --list                   # List with difficulty filter
    python sauravgolf.py --list --difficulty easy
    python sauravgolf.py --show 1                 # Show challenge details + par
    python sauravgolf.py --play 1 solution.srv    # Submit a solution
    python sauravgolf.py --play 1 --stdin         # Read solution from stdin
    python sauravgolf.py --leaderboard            # Show personal bests
    python sauravgolf.py --leaderboard --sort score  # Sort by score vs par
    python sauravgolf.py --stats                  # Overall golf stats
    python sauravgolf.py --reset                  # Reset all scores
    python sauravgolf.py --tips                   # Show sauravcode golf tips
    python sauravgolf.py --random                 # Pick random unsolved challenge
    python sauravgolf.py --export json             # Export results as JSON

Scoring: Characters in solution (excluding whitespace-only lines).
         Par = reference solution length. Beat par for bonus medals!
         [GOLD] = under par, [SILVER] = at par, [BRONZE] = over par but solved

Difficulties: easy (par 20-60), medium (par 40-100), hard (par 80-200)
"""

import sys
import os
import json
import argparse
import io
import tempfile
from datetime import datetime
from contextlib import redirect_stdout, redirect_stderr

# Import the sauravcode interpreter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from saurav import tokenize, Parser, Interpreter

# ── Golf challenge definitions ─────────────────────────────────────────

CHALLENGES = [
    {
        "id": 1,
        "title": "Hello World",
        "difficulty": "easy",
        "description": "Print exactly: Hello, World!",
        "par": 22,
        "tests": [
            {"input": "", "expected": "Hello, World!"}
        ],
        "hint": "The print function is your friend.",
    },
    {
        "id": 2,
        "title": "Sum 1 to N",
        "difficulty": "easy",
        "description": "Read a number N from the first line of input and print the sum of 1 to N.",
        "par": 45,
        "tests": [
            {"input": "5", "expected": "15"},
            {"input": "10", "expected": "55"},
            {"input": "1", "expected": "1"},
        ],
        "hint": "There's a formula for this...",
    },
    {
        "id": 3,
        "title": "Reverse String",
        "difficulty": "easy",
        "description": "Read a string and print it reversed.",
        "par": 35,
        "tests": [
            {"input": "hello", "expected": "olleh"},
            {"input": "abcdef", "expected": "fedcba"},
            {"input": "a", "expected": "a"},
        ],
        "hint": "Check built-in string functions.",
    },
    {
        "id": 4,
        "title": "FizzBuzz (1-20)",
        "difficulty": "easy",
        "description": "Print FizzBuzz for numbers 1 to 20. Print 'Fizz' for multiples of 3, 'Buzz' for multiples of 5, 'FizzBuzz' for both, or the number otherwise. One per line.",
        "par": 95,
        "tests": [
            {"input": "", "expected": "1\n2\nFizz\n4\nBuzz\nFizz\n7\n8\nFizz\nBuzz\n11\nFizz\n13\n14\nFizzBuzz\n16\n17\nFizz\n19\nBuzz"},
        ],
        "hint": "Modulo and conditionals. Can you avoid repeating yourself?",
    },
    {
        "id": 5,
        "title": "Count Vowels",
        "difficulty": "easy",
        "description": "Read a string and print the number of vowels (a, e, i, o, u — case insensitive).",
        "par": 55,
        "tests": [
            {"input": "hello", "expected": "2"},
            {"input": "AEIOU", "expected": "5"},
            {"input": "xyz", "expected": "0"},
        ],
        "hint": "Filter or count characters in a set.",
    },
    {
        "id": 6,
        "title": "Fibonacci N",
        "difficulty": "medium",
        "description": "Read N and print the first N Fibonacci numbers, space-separated. F(1)=0, F(2)=1, ...",
        "par": 75,
        "tests": [
            {"input": "5", "expected": "0 1 1 2 3"},
            {"input": "8", "expected": "0 1 1 2 3 5 8 13"},
            {"input": "1", "expected": "0"},
        ],
        "hint": "Loop and build up. Two variables tracking previous values.",
    },
    {
        "id": 7,
        "title": "Palindrome Check",
        "difficulty": "medium",
        "description": "Read a string and print 'true' if it's a palindrome (case insensitive, ignore spaces), 'false' otherwise.",
        "par": 70,
        "tests": [
            {"input": "racecar", "expected": "true"},
            {"input": "hello", "expected": "false"},
            {"input": "A man a plan a canal Panama", "expected": "true"},
        ],
        "hint": "Normalize then compare to reversed.",
    },
    {
        "id": 8,
        "title": "Diamond Pattern",
        "difficulty": "medium",
        "description": "Read N (odd, >= 1) and print a diamond of stars. N=5 means:\n  *\n ***\n*****\n ***\n  *",
        "par": 110,
        "tests": [
            {"input": "5", "expected": "  *\n ***\n*****\n ***\n  *"},
            {"input": "3", "expected": " *\n***\n *"},
            {"input": "1", "expected": "*"},
        ],
        "hint": "Two loops: expanding then contracting. Spaces for centering.",
    },
    {
        "id": 9,
        "title": "Prime Sieve",
        "difficulty": "medium",
        "description": "Read N and print all prime numbers up to N, space-separated.",
        "par": 90,
        "tests": [
            {"input": "20", "expected": "2 3 5 7 11 13 17 19"},
            {"input": "10", "expected": "2 3 5 7"},
            {"input": "2", "expected": "2"},
        ],
        "hint": "Sieve of Eratosthenes or trial division.",
    },
    {
        "id": 10,
        "title": "Caesar Cipher",
        "difficulty": "medium",
        "description": "Read two lines: a string and a shift N. Print the string with each letter shifted by N positions (wrap around, preserve case, leave non-letters alone).",
        "par": 120,
        "tests": [
            {"input": "hello\n3", "expected": "khoor"},
            {"input": "ABC\n1", "expected": "BCD"},
            {"input": "xyz\n3", "expected": "abc"},
        ],
        "hint": "Character codes and modular arithmetic.",
    },
    {
        "id": 11,
        "title": "Flatten Nested List",
        "difficulty": "hard",
        "description": "Read a JSON-style nested list (e.g. [1,[2,[3]],4]) and print all values space-separated, flattened.",
        "par": 85,
        "tests": [
            {"input": "[1,[2,[3]],4]", "expected": "1 2 3 4"},
            {"input": "[1,2,3]", "expected": "1 2 3"},
            {"input": "[[1,[2]],[3,[4,[5]]]]", "expected": "1 2 3 4 5"},
        ],
        "hint": "Recursion or a stack-based approach.",
    },
    {
        "id": 12,
        "title": "Run-Length Encode",
        "difficulty": "hard",
        "description": "Read a string and print its run-length encoding. E.g. 'aaabbc' → 'a3b2c1'.",
        "par": 95,
        "tests": [
            {"input": "aaabbc", "expected": "a3b2c1"},
            {"input": "abc", "expected": "a1b1c1"},
            {"input": "aaa", "expected": "a3"},
        ],
        "hint": "Track current char and count, emit on change.",
    },
    {
        "id": 13,
        "title": "Matrix Transpose",
        "difficulty": "hard",
        "description": "Read rows of space-separated numbers (one row per line) and print the transpose. Rows separated by newlines.",
        "par": 100,
        "tests": [
            {"input": "1 2 3\n4 5 6", "expected": "1 4\n2 5\n3 6"},
            {"input": "1 2\n3 4\n5 6", "expected": "1 3 5\n2 4 6"},
        ],
        "hint": "Nested loops, swap rows and columns.",
    },
    {
        "id": 14,
        "title": "Balanced Brackets",
        "difficulty": "hard",
        "description": "Read a string of brackets ()[]{}  and print 'true' if balanced, 'false' otherwise.",
        "par": 105,
        "tests": [
            {"input": "()[]{}", "expected": "true"},
            {"input": "([{}])", "expected": "true"},
            {"input": "([)]", "expected": "false"},
            {"input": "{", "expected": "false"},
        ],
        "hint": "Stack-based matching.",
    },
    {
        "id": 15,
        "title": "Spiral Numbers",
        "difficulty": "hard",
        "description": "Read N and print an NxN spiral matrix. Each row space-separated, rows on separate lines. Fill 1..N² clockwise from top-left.",
        "par": 180,
        "tests": [
            {"input": "3", "expected": "1 2 3\n8 9 4\n7 6 5"},
            {"input": "1", "expected": "1"},
        ],
        "hint": "Direction vectors and boundary tracking.",
    },
]

# ── Score file management ──────────────────────────────────────────────

SCORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".golf_scores.json")


def _load_scores():
    if os.path.exists(SCORE_FILE):
        try:
            with open(SCORE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"scores": {}, "attempts": {}}


def _save_scores(data):
    with open(SCORE_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ── Solution runner ────────────────────────────────────────────────────

def _count_chars(code):
    """Count golf score: all characters except blank lines."""
    lines = code.split("\n")
    scored_lines = [l for l in lines if l.strip()]
    return sum(len(l) for l in scored_lines)


def _run_solution(code, input_text="", timeout=10):
    """Run a .srv solution and capture output."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".srv", delete=False, encoding="utf-8") as f:
        f.write(code)
        f.flush()
        tmppath = f.name
    try:
        tokens = tokenize(code)
        parser = Parser(tokens)
        ast_nodes = parser.parse()
        interp = Interpreter()

        # Redirect stdin
        old_stdin = sys.stdin
        sys.stdin = io.StringIO(input_text)

        buf = io.StringIO()
        try:
            with redirect_stdout(buf), redirect_stderr(io.StringIO()):
                interp.execute_body(ast_nodes)
        finally:
            sys.stdin = old_stdin

        return buf.getvalue().rstrip("\n")
    except Exception as e:
        return f"ERROR: {e}"
    finally:
        try:
            os.unlink(tmppath)
        except OSError:
            pass


def _run_tests(challenge, code):
    """Run all tests for a challenge. Returns (passed, total, details)."""
    results = []
    for i, test in enumerate(challenge["tests"]):
        output = _run_solution(code, test.get("input", ""))
        expected = test["expected"]
        passed = output.strip() == expected.strip()
        results.append({
            "test": i + 1,
            "passed": passed,
            "expected": expected,
            "got": output,
        })
    passed = sum(1 for r in results if r["passed"])
    return passed, len(results), results


# ── Display helpers ────────────────────────────────────────────────────

def _medal(chars, par):
    if chars < par:
        return "[GOLD]"
    elif chars == par:
        return "[SILVER]"
    else:
        return "[BRONZE]"


def _difficulty_color(diff):
    colors = {"easy": "\033[32m", "medium": "\033[33m", "hard": "\033[31m"}
    return f"{colors.get(diff, '')}{diff}\033[0m"


def cmd_list(args):
    print("+" + "=" * 62 + "+")
    print("|              SAURAVCODE GOLF CHALLENGES                      |")
    print("+" + "=" * 62 + "+")
    print()

    scores = _load_scores()

    for ch in CHALLENGES:
        if args.difficulty and ch["difficulty"] != args.difficulty:
            continue
        sid = str(ch["id"])
        best = scores["scores"].get(sid)
        status = "  "
        if best is not None:
            status = _medal(best, ch["par"]) + " "
            best_str = f" [best: {best} chars]"
        else:
            best_str = ""

        diff = _difficulty_color(ch["difficulty"])
        print(f"  {status}#{ch['id']:>2}  {ch['title']:<25} {diff:<20} par: {ch['par']}{best_str}")

    print()
    solved = sum(1 for ch in CHALLENGES if str(ch["id"]) in scores["scores"])
    print(f"  Solved: {solved}/{len(CHALLENGES)}")
    print()


def cmd_show(args):
    ch = next((c for c in CHALLENGES if c["id"] == args.show), None)
    if not ch:
        print(f"Challenge #{args.show} not found.")
        return

    scores = _load_scores()
    best = scores["scores"].get(str(ch["id"]))

    print(f"\n  [GOLF] Challenge #{ch['id']}: {ch['title']}")
    print(f"  Difficulty: {_difficulty_color(ch['difficulty'])}")
    print(f"  Par: {ch['par']} characters")
    if best is not None:
        print(f"  Your best: {best} characters {_medal(best, ch['par'])}")
    print(f"\n  {ch['description']}")
    print(f"\n  [TIP] Hint: {ch['hint']}")
    print(f"\n  Test cases:")
    for i, t in enumerate(ch["tests"]):
        inp = t.get("input", "(none)")
        print(f"    {i+1}. Input: {inp!r} → Expected: {t['expected']!r}")
    print()


def cmd_play(args):
    ch = next((c for c in CHALLENGES if c["id"] == args.play), None)
    if not ch:
        print(f"Challenge #{args.play} not found.")
        return

    if args.stdin:
        code = sys.stdin.read()
    else:
        if not args.file:
            print("Provide a solution file or use --stdin.")
            return
        with open(args.file, "r", encoding="utf-8") as f:
            code = f.read()

    chars = _count_chars(code)
    print(f"\n  [GOLF] Challenge #{ch['id']}: {ch['title']}")
    print(f"  Solution: {chars} characters (par: {ch['par']})")
    print()

    passed, total, details = _run_tests(ch, code)

    for d in details:
        icon = "[PASS]" if d["passed"] else "[FAIL]"
        print(f"  {icon} Test {d['test']}: ", end="")
        if d["passed"]:
            print("PASS")
        else:
            print(f"FAIL — expected {d['expected']!r}, got {d['got']!r}")

    print()

    if passed == total:
        medal = _medal(chars, ch["par"])
        print(f"  {medal} ALL TESTS PASSED! Score: {chars} characters (par: {ch['par']})")

        if chars < ch["par"]:
            diff = ch["par"] - chars
            print(f"  [FIRE] {diff} characters UNDER par! Incredible!")
        elif chars == ch["par"]:
            print(f"  [CLAP] Exactly at par!")
        else:
            diff = chars - ch["par"]
            print(f"  [RULER] {diff} characters over par. Can you trim it down?")

        # Save score
        scores = _load_scores()
        sid = str(ch["id"])
        old_best = scores["scores"].get(sid)

        attempts = scores.get("attempts", {})
        attempts[sid] = attempts.get(sid, 0) + 1
        scores["attempts"] = attempts

        if old_best is None or chars < old_best:
            scores["scores"][sid] = chars
            if old_best is not None:
                print(f"  [PARTY] New personal best! (was {old_best})")
            else:
                print(f"  [PARTY] First solve!")
            _save_scores(scores)
        else:
            _save_scores(scores)
            print(f"  Personal best remains: {old_best} characters")
    else:
        print(f"  [FAIL] {passed}/{total} tests passed. Keep trying!")

    print()


def cmd_leaderboard(args):
    scores = _load_scores()
    if not scores["scores"]:
        print("\n  No scores yet! Try solving some challenges.\n")
        return

    print("\n  +" + "=" * 55 + "+")
    print("  |            GOLF LEADERBOARD                          |")
    print("  +" + "=" * 55 + "+\n")

    entries = []
    for ch in CHALLENGES:
        sid = str(ch["id"])
        if sid in scores["scores"]:
            best = scores["scores"][sid]
            vs_par = best - ch["par"]
            entries.append((ch, best, vs_par))

    if args.sort == "score":
        entries.sort(key=lambda e: e[2])
    else:
        entries.sort(key=lambda e: e[0]["id"])

    total_score = 0
    total_par = 0
    for ch, best, vs_par in entries:
        medal = _medal(best, ch["par"])
        sign = "+" if vs_par > 0 else ""
        diff_str = f"({sign}{vs_par})" if vs_par != 0 else "(=)"
        print(f"  {medal} #{ch['id']:>2} {ch['title']:<25} {best:>4} chars  par {ch['par']:>3}  {diff_str}")
        total_score += best
        total_par += ch["par"]

    print(f"\n  Total: {total_score} chars vs {total_par} par ({'+' if total_score > total_par else ''}{total_score - total_par})")
    print()


def cmd_stats(args):
    scores = _load_scores()
    solved = len(scores["scores"])
    total = len(CHALLENGES)
    attempts = scores.get("attempts", {})

    print(f"\n  [GOLF] Golf Stats")
    print(f"  Solved: {solved}/{total}")

    if solved > 0:
        under = sum(1 for ch in CHALLENGES if str(ch["id"]) in scores["scores"] and scores["scores"][str(ch["id"])] < ch["par"])
        at = sum(1 for ch in CHALLENGES if str(ch["id"]) in scores["scores"] and scores["scores"][str(ch["id"])] == ch["par"])
        over = solved - under - at

        print(f"  [GOLD] Under par: {under}")
        print(f"  [SILVER] At par: {at}")
        print(f"  [BRONZE] Over par: {over}")

        total_attempts = sum(attempts.values())
        print(f"  Total attempts: {total_attempts}")

        by_diff = {"easy": 0, "medium": 0, "hard": 0}
        by_diff_total = {"easy": 0, "medium": 0, "hard": 0}
        for ch in CHALLENGES:
            by_diff_total[ch["difficulty"]] += 1
            if str(ch["id"]) in scores["scores"]:
                by_diff[ch["difficulty"]] += 1

        print(f"\n  By difficulty:")
        for d in ["easy", "medium", "hard"]:
            print(f"    {_difficulty_color(d)}: {by_diff[d]}/{by_diff_total[d]}")

    print()


def cmd_tips(_args):
    tips = [
        "Use short variable names: x instead of counter",
        "Chain operations with the pipe operator |>",
        "Use list comprehensions instead of loops where possible",
        "f-strings can embed expressions directly",
        "Built-in functions often replace multi-line logic",
        "The ternary expression saves lines: x if cond else y",
        "Use string multiplication for repeated patterns: '*' * n",
        "join() is usually shorter than manual string building",
        "range() with step can skip explicit conditionals",
        "Math formulas beat loops: n*(n+1)/2 for sum to N",
    ]
    print("\n  [GOLF] Sauravcode Golf Tips\n")
    for i, tip in enumerate(tips, 1):
        print(f"  {i:>2}. {tip}")
    print()


def cmd_random(args):
    scores = _load_scores()
    unsolved = [ch for ch in CHALLENGES if str(ch["id"]) not in scores["scores"]]
    if args.difficulty:
        unsolved = [ch for ch in unsolved if ch["difficulty"] == args.difficulty]
    if not unsolved:
        print("\n  [GOLD] All matching challenges solved! You're a golf pro!\n")
        return
    import random
    ch = random.choice(unsolved)
    args.show = ch["id"]
    cmd_show(args)


def cmd_export(args):
    scores = _load_scores()
    data = []
    for ch in CHALLENGES:
        sid = str(ch["id"])
        entry = {
            "id": ch["id"],
            "title": ch["title"],
            "difficulty": ch["difficulty"],
            "par": ch["par"],
            "best": scores["scores"].get(sid),
            "attempts": scores.get("attempts", {}).get(sid, 0),
        }
        data.append(entry)

    if args.export == "json":
        print(json.dumps(data, indent=2))
    elif args.export == "csv":
        import csv as _csv
        w = _csv.writer(sys.stdout)
        w.writerow(["id", "title", "difficulty", "par", "best", "attempts"])
        for e in data:
            w.writerow([e["id"], e["title"], e["difficulty"], e["par"], e["best"] or "", e["attempts"]])


def cmd_reset(_args):
    if os.path.exists(SCORE_FILE):
        os.unlink(SCORE_FILE)
    print("\n  [TRASH]  All golf scores reset.\n")


def main():
    parser = argparse.ArgumentParser(description="sauravgolf — Code golf for sauravcode")
    parser.add_argument("--list", action="store_true", help="List challenges")
    parser.add_argument("--show", type=int, help="Show challenge details")
    parser.add_argument("--play", type=int, help="Submit a solution")
    parser.add_argument("file", nargs="?", help="Solution .srv file")
    parser.add_argument("--stdin", action="store_true", help="Read solution from stdin")
    parser.add_argument("--leaderboard", action="store_true", help="Show personal bests")
    parser.add_argument("--sort", choices=["id", "score"], default="id", help="Leaderboard sort")
    parser.add_argument("--stats", action="store_true", help="Show golf stats")
    parser.add_argument("--tips", action="store_true", help="Show golf tips")
    parser.add_argument("--random", action="store_true", help="Pick random unsolved challenge")
    parser.add_argument("--difficulty", choices=["easy", "medium", "hard"], help="Filter by difficulty")
    parser.add_argument("--export", choices=["json", "csv"], help="Export results")
    parser.add_argument("--reset", action="store_true", help="Reset all scores")

    args = parser.parse_args()

    if args.show:
        cmd_show(args)
    elif args.play:
        cmd_play(args)
    elif args.leaderboard:
        cmd_leaderboard(args)
    elif args.stats:
        cmd_stats(args)
    elif args.tips:
        cmd_tips(args)
    elif args.random:
        cmd_random(args)
    elif args.export:
        cmd_export(args)
    elif args.reset:
        cmd_reset(args)
    else:
        cmd_list(args)


if __name__ == "__main__":
    main()
