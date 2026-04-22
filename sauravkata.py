#!/usr/bin/env python3
"""sauravkata — Coding kata exercises for sauravcode (.srv).

Practice problem-solving with progressive challenges, automated testing,
timed sessions, hints, and streak tracking. Unlike golf (fewest chars),
katas reward correctness and consistency.

Usage:
    python sauravkata.py                          # Dashboard with progress
    python sauravkata.py --list                   # List all katas
    python sauravkata.py --list --tier warm-up    # Filter by tier
    python sauravkata.py --show 1                 # Show kata description + examples
    python sauravkata.py --show 1 --hint          # Reveal progressive hints
    python sauravkata.py --solve 1 solution.srv   # Submit solution
    python sauravkata.py --solve 1 --stdin        # Read solution from stdin
    python sauravkata.py --daily                  # Today's daily kata
    python sauravkata.py --streak                 # View streak stats
    python sauravkata.py --history                # Solution history
    python sauravkata.py --reset                  # Reset all progress
    python sauravkata.py --export json            # Export progress

Tiers: warm-up, practice, challenge, master

Each kata has:
  - Description and examples
  - Test cases (visible + hidden)
  - Up to 3 progressive hints
  - Time tracking per attempt
  - Difficulty tier rating
"""

import sys
import os
import json
import argparse
import io
import time
import hashlib
from datetime import datetime, date
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Color helpers (shared via _termcolors) ────────────────────────

from _termcolors import Colors as _Colors

_NO_COLOR = os.environ.get("NO_COLOR") is not None
_TC = _Colors(not _NO_COLOR)
_c = _TC.c
_green = _TC.green
_red = _TC.red
_cyan = _TC.cyan
_yellow = _TC.yellow
_dim = _TC.dim
_bold = _TC.bold
_mag = _TC.magenta

TIER_COLORS = {
    "warm-up": _green,
    "practice": _cyan,
    "challenge": _yellow,
    "master": _red,
}

TIER_EMOJI = {
    "warm-up": "🟢",
    "practice": "🔵",
    "challenge": "🟡",
    "master": "🔴",
}

# ── Kata Definitions ──────────────────────────────────────────────
# NOTE: sauravcode's for-loop parser does not support elif inside for blocks.
# Use nested if/else instead. Also: range(n) gives 0..n-1,
# for i START END gives START..END-1, function args are space-separated.

KATAS = [
    {
        "id": 1,
        "title": "FizzBuzz",
        "tier": "warm-up",
        "desc": "Print numbers 1 to N. For multiples of 3 print 'Fizz', multiples of 5 print 'Buzz', both print 'FizzBuzz'.",
        "examples": [
            {"input": "5", "output": "1\n2\nFizz\n4\nBuzz"},
        ],
        "tests": [
            {"input": "3", "output": "1\n2\nFizz"},
            {"input": "1", "output": "1"},
            {"input": "15", "output": "1\n2\nFizz\n4\nBuzz\nFizz\n7\n8\nFizz\nBuzz\n11\nFizz\n13\n14\nFizzBuzz"},
        ],
        "hints": [
            "Use 'for i in range(n)' and compute x = i + 1.",
            "Check divisibility with %. Check 15 first (both 3 and 5).",
            "Use nested if/else (not elif inside for). if x % 15 == 0 ... else if x % 3 == 0 ...",
        ],
        "setup": "# Variable 'n' is set for you\n# Print FizzBuzz from 1 to n\n# Tip: use nested if/else, not elif inside for\n",
        "wrapper": 'n = {input}\n{code}',
    },
    {
        "id": 2,
        "title": "Reverse a String",
        "tier": "warm-up",
        "desc": "Given a string, print it reversed.",
        "examples": [
            {"input": '"hello"', "output": "olleh"},
            {"input": '"abc"', "output": "cba"},
        ],
        "tests": [
            {"input": '"hello"', "output": "olleh"},
            {"input": '"a"', "output": "a"},
            {"input": '""', "output": ""},
            {"input": '"abcdef"', "output": "fedcba"},
        ],
        "hints": [
            "Iterate over the string character by character using indexing.",
            "Build a new string by prepending each character.",
            'result = ""\nfor i in range(len(s))\n    result = s[i] + result\nprint result',
        ],
        "setup": "# Variable 's' contains the input string\n# Print it reversed\n",
        "wrapper": 's = {input}\n{code}',
    },
    {
        "id": 3,
        "title": "Sum of Digits",
        "tier": "warm-up",
        "desc": "Given a non-negative integer, print the sum of its digits.",
        "examples": [
            {"input": "123", "output": "6"},
            {"input": "9999", "output": "36"},
        ],
        "tests": [
            {"input": "0", "output": "0"},
            {"input": "5", "output": "5"},
            {"input": "123", "output": "6"},
            {"input": "9999", "output": "36"},
            {"input": "1000", "output": "1"},
        ],
        "hints": [
            "Convert the number to a string with to_string(n) to access individual digits.",
            "Loop through each character, convert back to number with to_number(), and sum.",
            "s = to_string(n), total = 0, for i in range(len(s)): total = total + to_number(s[i])",
        ],
        "setup": "# Variable 'n' contains the input number\n# Print the sum of its digits\n",
        "wrapper": 'n = {input}\n{code}',
    },
    {
        "id": 4,
        "title": "Fibonacci Sequence",
        "tier": "practice",
        "desc": "Print the first N Fibonacci numbers (starting 0, 1, 1, 2, 3, ...), each on a new line.",
        "examples": [
            {"input": "5", "output": "0\n1\n1\n2\n3"},
        ],
        "tests": [
            {"input": "1", "output": "0"},
            {"input": "2", "output": "0\n1"},
            {"input": "5", "output": "0\n1\n1\n2\n3"},
            {"input": "10", "output": "0\n1\n1\n2\n3\n5\n8\n13\n21\n34"},
        ],
        "hints": [
            "Start with a = 0, b = 1 and iterate n times.",
            "Each step: print a, then temp = a + b, a = b, b = temp.",
            "Use 'for i in range(n)' to count iterations.",
        ],
        "setup": "# Variable 'n' contains the count\n# Print the first n Fibonacci numbers\n",
        "wrapper": 'n = {input}\n{code}',
    },
    {
        "id": 5,
        "title": "Count Vowels",
        "tier": "practice",
        "desc": "Given a string, print the number of vowels (a, e, i, o, u — case-insensitive).",
        "examples": [
            {"input": '"hello"', "output": "2"},
            {"input": '"AEIOU"', "output": "5"},
        ],
        "tests": [
            {"input": '"hello"', "output": "2"},
            {"input": '"AEIOU"', "output": "5"},
            {"input": '"xyz"', "output": "0"},
            {"input": '"sauravcode"', "output": "5"},
            {"input": '""', "output": "0"},
        ],
        "hints": [
            "Use lower(s) to convert to lowercase first.",
            "Loop through each character and check if it matches a, e, i, o, or u.",
            "count = 0, lo = lower(s), check each char with == comparisons.",
        ],
        "setup": "# Variable 's' contains the input string\n# Print the vowel count\n",
        "wrapper": 's = {input}\n{code}',
    },
    {
        "id": 6,
        "title": "Factorial",
        "tier": "practice",
        "desc": "Given a non-negative integer N, print N! (factorial). 0! = 1.",
        "examples": [
            {"input": "5", "output": "120"},
            {"input": "0", "output": "1"},
        ],
        "tests": [
            {"input": "0", "output": "1"},
            {"input": "1", "output": "1"},
            {"input": "5", "output": "120"},
            {"input": "10", "output": "3628800"},
        ],
        "hints": [
            "Start with result = 1, multiply by each number from 1 to n.",
            "Use 'for i in range(n)' and multiply by (i + 1).",
            "result = 1, for i in range(n): result = result * (i + 1), print result",
        ],
        "setup": "# Variable 'n' contains the number\n# Print n!\n",
        "wrapper": 'n = {input}\n{code}',
    },
    {
        "id": 7,
        "title": "Prime Checker",
        "tier": "practice",
        "desc": "Given an integer N >= 1, print 'true' if N is prime, 'false' otherwise.",
        "examples": [
            {"input": "7", "output": "true"},
            {"input": "4", "output": "false"},
        ],
        "tests": [
            {"input": "1", "output": "false"},
            {"input": "2", "output": "true"},
            {"input": "3", "output": "true"},
            {"input": "4", "output": "false"},
            {"input": "17", "output": "true"},
            {"input": "25", "output": "false"},
        ],
        "hints": [
            "1 is not prime. 2 is prime. Check edge cases first.",
            "For n > 2, check if any number from 2 to n-1 divides n evenly.",
            "Set is_prime = true, loop from 2 to n, if n % i == 0 then is_prime = false.",
        ],
        "setup": "# Variable 'n' contains the number\n# Print 'true' or 'false'\n",
        "wrapper": 'n = {input}\n{code}',
    },
    {
        "id": 8,
        "title": "Triangle Pattern",
        "tier": "challenge",
        "desc": "Print a right triangle of stars with N rows. Row i (1-indexed) has i stars. No trailing spaces.",
        "examples": [
            {"input": "3", "output": "*\n**\n***"},
            {"input": "5", "output": "*\n**\n***\n****\n*****"},
        ],
        "tests": [
            {"input": "1", "output": "*"},
            {"input": "3", "output": "*\n**\n***"},
            {"input": "5", "output": "*\n**\n***\n****\n*****"},
        ],
        "hints": [
            "Use a for loop from 0 to n, build each row.",
            "For row i (0-indexed), you need i+1 stars.",
            "Build row string by concatenating '*' in an inner loop, then print it.",
        ],
        "setup": "# Variable 'n' contains the row count\n# Print a right triangle of '*'\n",
        "wrapper": 'n = {input}\n{code}',
    },
    {
        "id": 9,
        "title": "Count Words",
        "tier": "challenge",
        "desc": "Given a string of space-separated words, print the number of words. An empty string has 0 words.",
        "examples": [
            {"input": '"hello world"', "output": "2"},
            {"input": '"one two three four"', "output": "4"},
        ],
        "tests": [
            {"input": '""', "output": "0"},
            {"input": '"hello"', "output": "1"},
            {"input": '"hello world"', "output": "2"},
            {"input": '"one two three four"', "output": "4"},
        ],
        "hints": [
            "Use split(s) to break the string into a list of words.",
            "Then use len() on the resulting list.",
            "Handle the empty string case: split(\"\") may give [\"\"], check for it.",
        ],
        "setup": "# Variable 's' contains the input string\n# Print the word count\n",
        "wrapper": 's = {input}\n{code}',
    },
    {
        "id": 10,
        "title": "Caesar Cipher",
        "tier": "challenge",
        "desc": "Encrypt a string with Caesar cipher (shift=3). Only shift a-z and A-Z, wrap around. Non-letters stay unchanged. Print the result.",
        "examples": [
            {"input": '"abc"', "output": "def"},
            {"input": '"xyz"', "output": "abc"},
        ],
        "tests": [
            {"input": '"abc"', "output": "def"},
            {"input": '"xyz"', "output": "abc"},
            {"input": '"Hello World!"', "output": "Khoor Zruog!"},
            {"input": '""', "output": ""},
            {"input": '"123"', "output": "123"},
        ],
        "hints": [
            "Use char_code(c) and from_char_code(n) to work with ASCII values.",
            "For lowercase: new = (code - 97 + 3) % 26 + 97. Similar for uppercase (65).",
            "Check if each char is a letter by its code range before shifting.",
        ],
        "setup": "# Variable 's' contains the input string\n# Print the Caesar-cipher encrypted result (shift=3)\n",
        "wrapper": 's = {input}\n{code}',
    },
    {
        "id": 11,
        "title": "Run-Length Encoding",
        "tier": "challenge",
        "desc": "Compress a string using run-length encoding. Consecutive identical chars become count+char. Omit count when it's 1.",
        "examples": [
            {"input": '"aaabbc"', "output": "3a2bc"},
            {"input": '"aabbcc"', "output": "2a2b2c"},
        ],
        "tests": [
            {"input": '"aaabbc"', "output": "3a2bc"},
            {"input": '"aabbcc"', "output": "2a2b2c"},
            {"input": '"a"', "output": "a"},
            {"input": '"aaaa"', "output": "4a"},
            {"input": '"abcd"', "output": "abcd"},
        ],
        "hints": [
            "Track the current character and a count as you iterate.",
            "When the character changes, emit count + char (skip count if 1), reset.",
            "Don't forget to emit the last group after the loop ends.",
        ],
        "setup": "# Variable 's' contains the input string\n# Print the run-length encoded result\n",
        "wrapper": 's = {input}\n{code}',
    },
    {
        "id": 12,
        "title": "Diamond Pattern",
        "tier": "master",
        "desc": "Given an odd number N, print an N-row diamond of stars centered with spaces. Each row has the right count of stars, centered.",
        "examples": [
            {"input": "5", "output": "  *\n ***\n*****\n ***\n  *"},
        ],
        "tests": [
            {"input": "1", "output": "*"},
            {"input": "3", "output": " *\n***\n *"},
            {"input": "5", "output": "  *\n ***\n*****\n ***\n  *"},
        ],
        "hints": [
            "The middle row has N stars. Rows above and below have 1, 3, 5, ... stars.",
            "For each row, calculate how many spaces to prepend for centering.",
            "Top half: for i 0 to mid, stars = 2*i+1, spaces = mid-i. Bottom half: mirror.",
        ],
        "setup": "# Variable 'n' contains the diamond size (odd number)\n# Print the diamond pattern\n",
        "wrapper": 'n = {input}\n{code}',
    },
]

# ── Progress persistence ──────────────────────────────────────────

PROGRESS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".kata_progress.json")

def _load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"solved": {}, "attempts": {}, "streaks": {"current": 0, "best": 0, "last_date": None}, "history": []}

def _save_progress(prog):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(prog, f, indent=2)

# ── Runner ────────────────────────────────────────────────────────

def _run_code(code, timeout=10):
    """Execute sauravcode and capture stdout."""
    from saurav import tokenize, Parser, Interpreter, FunctionCallNode
    out = io.StringIO()
    err = io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            tokens = tokenize(code)
            parser = Parser(tokens)
            ast = parser.parse()
            interp = Interpreter()
            for node in ast:
                if isinstance(node, FunctionCallNode):
                    interp.execute_function(node)
                else:
                    interp.interpret(node)
    except SystemExit:
        pass
    except Exception as e:
        return None, str(e)
    return out.getvalue(), None

def _check_solution(kata, code_text):
    """Run all tests for a kata, return (passed, total, details)."""
    wrapper = kata["wrapper"]
    results = []
    for i, tc in enumerate(kata["tests"]):
        full_code = wrapper.format(input=tc["input"], code=code_text)
        output, err = _run_code(full_code)
        if err:
            results.append({"pass": False, "input": tc["input"], "expected": tc["output"],
                            "got": f"ERROR: {err}", "hidden": i >= len(kata.get("examples", []))})
            continue
        actual = output.rstrip("\n")
        expected = tc["output"]
        passed = actual == expected
        results.append({"pass": passed, "input": tc["input"], "expected": expected,
                        "got": actual, "hidden": i >= len(kata.get("examples", []))})
    total_pass = sum(1 for r in results if r["pass"])
    return total_pass, len(results), results

# ── Daily kata ────────────────────────────────────────────────────

def _daily_kata_id():
    d = date.today()
    h = int(hashlib.md5(d.isoformat().encode()).hexdigest(), 16)
    return (h % len(KATAS)) + 1

# ── Display ───────────────────────────────────────────────────────

def _tier_label(tier):
    color_fn = TIER_COLORS.get(tier, str)
    emoji = TIER_EMOJI.get(tier, "")
    return f"{emoji} {color_fn(tier.upper())}"

def cmd_list(args):
    prog = _load_progress()
    print(_bold("=== SAURAVCODE KATAS ==="))
    print()
    for k in KATAS:
        if args.tier and k["tier"] != args.tier:
            continue
        solved = str(k["id"]) in prog["solved"]
        status = _green("*") if solved else _dim("o")
        tier = _tier_label(k["tier"])
        print(f"  {status}  #{k['id']:2d}  {tier:30s}  {k['title']}")
    solved_count = sum(1 for k in KATAS if str(k["id"]) in prog["solved"])
    print(f"\n  Progress: {_bold(f'{solved_count}/{len(KATAS)}')} katas solved")

def cmd_show(args):
    kata = next((k for k in KATAS if k["id"] == args.show), None)
    if not kata:
        print(_red(f"Kata #{args.show} not found."))
        return
    prog = _load_progress()
    solved = str(kata["id"]) in prog["solved"]

    print(_bold(f"=== KATA #{kata['id']}: {kata['title']} ==="))
    print(f"Tier: {_tier_label(kata['tier'])}")
    print(f"Status: {_green('SOLVED') if solved else _yellow('UNSOLVED')}")
    print()
    print(_bold("Description:"))
    print(f"  {kata['desc']}")
    print()
    print(_bold("Examples:"))
    for ex in kata.get("examples", [])[:2]:
        print(f"  Input:    {_cyan(ex['input'])}")
        print(f"  Expected: {_green(ex['output'])}")
        print()
    print(_bold("Setup:"))
    print(_dim(kata["setup"]))

    if args.hint:
        hints = kata.get("hints", [])
        attempts = prog.get("attempts", {}).get(str(kata["id"]), 0)
        show_count = min(max(1, attempts), len(hints))
        print(_bold(f"\nHints ({show_count}/{len(hints)} unlocked):"))
        for i in range(show_count):
            print(f"  {_yellow(f'Hint {i+1}:')} {hints[i]}")
        if show_count < len(hints):
            print(_dim(f"  (attempt more to unlock {len(hints) - show_count} more hint(s))"))

def cmd_solve(args):
    kata = next((k for k in KATAS if k["id"] == args.solve), None)
    if not kata:
        print(_red(f"Kata #{args.solve} not found."))
        return

    if args.stdin:
        code_text = sys.stdin.read()
    else:
        if not args.file:
            print(_red("Provide a solution file or use --stdin."))
            return
        with open(args.file, "r") as f:
            code_text = f.read()

    prog = _load_progress()
    kata_id = str(kata["id"])

    prog.setdefault("attempts", {})
    prog["attempts"][kata_id] = prog["attempts"].get(kata_id, 0) + 1

    print(_bold(f"=== KATA #{kata['id']}: {kata['title']} ==="))
    print(f"Attempt #{prog['attempts'][kata_id]}")
    print()

    start = time.time()
    passed, total, details = _check_solution(kata, code_text)
    elapsed = time.time() - start

    for i, r in enumerate(details):
        label = f"Test {i+1}"
        if r["hidden"]:
            label += " (hidden)"
        if r["pass"]:
            print(f"  {_green('PASS')} {label}")
        else:
            print(f"  {_red('FAIL')} {label}")
            if not r["hidden"]:
                print(f"    Input:    {r['input']}")
                print(f"    Expected: {_green(r['expected'])}")
                print(f"    Got:      {_red(r['got'])}")

    print()
    if passed == total:
        print(_green(_bold(f"ALL {total} TESTS PASSED! ({elapsed:.2f}s)")))
        already_solved = kata_id in prog.get("solved", {})
        prog.setdefault("solved", {})
        prog["solved"][kata_id] = {
            "date": datetime.now().isoformat(),
            "attempts": prog["attempts"][kata_id],
            "time": round(elapsed, 3),
        }
        today = date.today().isoformat()
        streaks = prog.setdefault("streaks", {"current": 0, "best": 0, "last_date": None})
        if streaks["last_date"] != today:
            yesterday = date.fromordinal(date.today().toordinal() - 1).isoformat()
            if streaks["last_date"] == yesterday:
                streaks["current"] += 1
            else:
                streaks["current"] = 1
            streaks["last_date"] = today
            streaks["best"] = max(streaks["best"], streaks["current"])

        prog.setdefault("history", [])
        prog["history"].append({
            "kata_id": kata["id"], "title": kata["title"],
            "date": datetime.now().isoformat(), "passed": True,
            "attempts": prog["attempts"][kata_id],
        })

        if not already_solved:
            solved_count = len(prog["solved"])
            print(f"  Kata #{kata['id']} complete! ({solved_count}/{len(KATAS)} total)")
            print(f"  Streak: {streaks['current']} day(s) | Best: {streaks['best']}")
    else:
        print(_red(f"  {passed}/{total} tests passed. Keep trying!"))
        prog.setdefault("history", [])
        prog["history"].append({
            "kata_id": kata["id"], "title": kata["title"],
            "date": datetime.now().isoformat(), "passed": False,
            "score": f"{passed}/{total}",
        })

    _save_progress(prog)

def cmd_daily(args):
    kid = _daily_kata_id()
    kata = next(k for k in KATAS if k["id"] == kid)
    prog = _load_progress()
    solved = str(kid) in prog.get("solved", {})
    print(_bold("=== TODAY'S DAILY KATA ==="))
    print(f"  #{kata['id']}  {_tier_label(kata['tier'])}  {kata['title']}")
    print(f"  Status: {_green('SOLVED') if solved else _yellow('UNSOLVED')}")
    print(f"\n  {kata['desc']}")
    print(f"\n  Solve: python sauravkata.py --solve {kata['id']} solution.srv")

def cmd_streak(args):
    prog = _load_progress()
    s = prog.get("streaks", {"current": 0, "best": 0, "last_date": None})
    today = date.today().isoformat()
    yesterday = date.fromordinal(date.today().toordinal() - 1).isoformat()
    if s["last_date"] not in (today, yesterday):
        s["current"] = 0

    print(_bold("=== STREAK STATS ==="))
    print(f"  Current streak: {_bold(str(s['current']))} day(s)")
    print(f"  Best streak:    {_bold(str(s['best']))} day(s)")
    print(f"  Last solved:    {s['last_date'] or 'never'}")
    solved_count = len(prog.get("solved", {}))
    print(f"  Total solved:   {solved_count}/{len(KATAS)}")

def cmd_history(args):
    prog = _load_progress()
    history = prog.get("history", [])
    if not history:
        print(_dim("No history yet. Solve your first kata!"))
        return
    print(_bold("=== SOLUTION HISTORY ==="))
    for entry in reversed(history[-20:]):
        status = _green("PASS") if entry.get("passed") else _red("FAIL")
        dt = entry.get("date", "?")[:16].replace("T", " ")
        print(f"  {status}  {dt}  #{entry['kata_id']}  {entry['title']}")

def cmd_dashboard(args):
    prog = _load_progress()
    solved = prog.get("solved", {})
    s = prog.get("streaks", {"current": 0, "best": 0, "last_date": None})

    print(_bold("+---------------------------------------+"))
    print(_bold("|       SAURAVCODE KATA DASHBOARD       |"))
    print(_bold("+---------------------------------------+"))
    print()
    print(f"  Solved: {_bold(f'{len(solved)}/{len(KATAS)}')}    Streak: {s.get('current', 0)}d    Best: {s.get('best', 0)}d")
    print()

    for tier in ["warm-up", "practice", "challenge", "master"]:
        tier_katas = [k for k in KATAS if k["tier"] == tier]
        tier_solved = sum(1 for k in tier_katas if str(k["id"]) in solved)
        bar = "".join(_green("#") if str(k["id"]) in solved else _dim(".") for k in tier_katas)
        print(f"  {_tier_label(tier):30s}  {bar}  {tier_solved}/{len(tier_katas)}")
    print()

    kid = _daily_kata_id()
    kata = next(k for k in KATAS if k["id"] == kid)
    daily_solved = str(kid) in solved
    ds = "DONE" if daily_solved else "python sauravkata.py --daily"
    print(f"  Daily: #{kata['id']} {kata['title']} -> {ds}")
    print()
    print(_dim("  Commands: --list | --show N | --solve N file.srv | --daily | --streak | --history"))

def cmd_export(args):
    prog = _load_progress()
    if args.export.lower() == "json":
        print(json.dumps(prog, indent=2))
    else:
        print(_red(f"Unknown format: {args.export}. Use 'json'."))

def cmd_reset(args):
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
    print(_green("Progress reset."))

# ── Main ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Coding kata exercises for sauravcode")
    parser.add_argument("--list", action="store_true", help="List all katas")
    parser.add_argument("--tier", choices=["warm-up", "practice", "challenge", "master"])
    parser.add_argument("--show", type=int, help="Show kata details")
    parser.add_argument("--hint", action="store_true", help="Show hints (with --show)")
    parser.add_argument("--solve", type=int, help="Submit solution for kata")
    parser.add_argument("file", nargs="?", help="Solution .srv file")
    parser.add_argument("--stdin", action="store_true", help="Read solution from stdin")
    parser.add_argument("--daily", action="store_true", help="Today's daily kata")
    parser.add_argument("--streak", action="store_true", help="Streak stats")
    parser.add_argument("--history", action="store_true", help="Solution history")
    parser.add_argument("--export", type=str, help="Export progress (json)")
    parser.add_argument("--reset", action="store_true", help="Reset all progress")
    args = parser.parse_args()

    if args.list:
        cmd_list(args)
    elif args.show:
        cmd_show(args)
    elif args.solve:
        cmd_solve(args)
    elif args.daily:
        cmd_daily(args)
    elif args.streak:
        cmd_streak(args)
    elif args.history:
        cmd_history(args)
    elif args.export:
        cmd_export(args)
    elif args.reset:
        cmd_reset(args)
    else:
        cmd_dashboard(args)

if __name__ == "__main__":
    main()
