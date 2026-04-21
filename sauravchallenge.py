#!/usr/bin/env python3
"""sauravchallenge — Coding challenge runner for sauravcode (.srv).

A built-in set of programming challenges to help learn sauravcode.
Each challenge has a description, difficulty, starter code, and test
cases that validate the solution by running it through the interpreter.

Usage:
    python sauravchallenge.py                        # List all challenges
    python sauravchallenge.py --list                 # List with filtering
    python sauravchallenge.py --list --difficulty easy
    python sauravchallenge.py --list --category loops
    python sauravchallenge.py --show 1               # Show challenge details
    python sauravchallenge.py --attempt 1 sol.srv    # Test solution
    python sauravchallenge.py --attempt 1 --stdin    # Read solution from stdin
    python sauravchallenge.py --starter 1            # Print starter code
    python sauravchallenge.py --stats                # Show progress stats
    python sauravchallenge.py --reset                # Reset progress
    python sauravchallenge.py --random               # Pick a random unsolved challenge
    python sauravchallenge.py --random --difficulty medium
    python sauravchallenge.py --export json           # Export challenges as JSON
    python sauravchallenge.py --export csv            # Export challenges as CSV

Categories: basics, functions, loops, collections, strings, classes, patterns, algorithms
Difficulties: easy, medium, hard
"""

import sys
import os
import json
import csv
import io
import re
import argparse
import random as _random
import tempfile
from pathlib import Path

# ── Challenge definitions ──────────────────────────────────────────────

CHALLENGES = [
    # === BASICS (1-5) ===
    {
        "id": 1,
        "title": "Hello World",
        "category": "basics",
        "difficulty": "easy",
        "description": "Print \"Hello, World!\" to the console.",
        "hint": "Use the print() function.",
        "starter": '# Print "Hello, World!" to the console\n',
        "tests": [
            {"input": "", "expected_output": "Hello, World!"}
        ]
    },
    {
        "id": 2,
        "title": "Variable Swap",
        "category": "basics",
        "difficulty": "easy",
        "description": "Given variables a=5 and b=10, swap their values and print both.\nExpected output:\n  10\n  5",
        "hint": "Use a temporary variable.",
        "starter": "a = 5\nb = 10\n# Swap a and b, then print a and print b\n",
        "tests": [
            {"input": "", "expected_output": "10\n5"}
        ]
    },
    {
        "id": 3,
        "title": "Temperature Converter",
        "category": "basics",
        "difficulty": "easy",
        "description": "Write a function celsius_to_fahrenheit(c) that returns the Fahrenheit value.\nFormula: F = C * 9/5 + 32\nPrint the result of calling it with 100.",
        "hint": "Define a function with the formula and call it.",
        "starter": "# Define celsius_to_fahrenheit(c) and print the result for 100\n",
        "tests": [
            {"input": "", "expected_output": "212"}
        ]
    },
    {
        "id": 4,
        "title": "Even or Odd",
        "category": "basics",
        "difficulty": "easy",
        "description": "Write a function is_even(n) that returns true if n is even, false otherwise.\nPrint the results for 4, 7, and 0.",
        "hint": "Use the modulo operator %.",
        "starter": "# Define is_even(n) and print results for 4, 7, 0\n",
        "tests": [
            {"input": "", "expected_output": "true\nfalse\ntrue"}
        ]
    },
    {
        "id": 5,
        "title": "Absolute Value",
        "category": "basics",
        "difficulty": "easy",
        "description": "Write a function abs_val(n) that returns the absolute value of n.\nPrint results for -5, 3, and 0.",
        "hint": "If n < 0, return -n.",
        "starter": "# Define abs_val(n) and print results for -5, 3, 0\n",
        "tests": [
            {"input": "", "expected_output": "5\n3\n0"}
        ]
    },
    # === FUNCTIONS (6-10) ===
    {
        "id": 6,
        "title": "Factorial",
        "category": "functions",
        "difficulty": "easy",
        "description": "Write a recursive function factorial(n) that returns n!.\nPrint factorial(5) and factorial(0).",
        "hint": "Base case: 0! = 1. Recursive: n! = n * (n-1)!",
        "starter": "# Define factorial(n) recursively\n# Print factorial(5) and factorial(0)\n",
        "tests": [
            {"input": "", "expected_output": "120\n1"}
        ]
    },
    {
        "id": 7,
        "title": "Fibonacci",
        "category": "functions",
        "difficulty": "medium",
        "description": "Write a function fib(n) that returns the nth Fibonacci number (0-indexed).\nfib(0)=0, fib(1)=1, fib(2)=1, etc.\nPrint fib(0), fib(1), fib(5), fib(10).",
        "hint": "Use recursion or a loop. fib(n) = fib(n-1) + fib(n-2).",
        "starter": "# Define fib(n) and print fib(0), fib(1), fib(5), fib(10)\n",
        "tests": [
            {"input": "", "expected_output": "0\n1\n5\n55"}
        ]
    },
    {
        "id": 8,
        "title": "Power Function",
        "category": "functions",
        "difficulty": "easy",
        "description": "Write a function power(base, exp) that computes base^exp using a loop.\nPrint power(2, 10) and power(3, 4).",
        "hint": "Start with result=1, multiply by base in a loop exp times.",
        "starter": "# Define power(base, exp) and print power(2,10), power(3,4)\n",
        "tests": [
            {"input": "", "expected_output": "1024\n81"}
        ]
    },
    {
        "id": 9,
        "title": "GCD",
        "category": "functions",
        "difficulty": "medium",
        "description": "Write a function gcd(a, b) using Euclid's algorithm.\nPrint gcd(48, 18) and gcd(100, 75).",
        "hint": "While b != 0: a, b = b, a % b. Return a.",
        "starter": "# Define gcd(a, b) and print gcd(48,18), gcd(100,75)\n",
        "tests": [
            {"input": "", "expected_output": "6\n25"}
        ]
    },
    {
        "id": 10,
        "title": "Higher-Order Functions",
        "category": "functions",
        "difficulty": "medium",
        "description": "Write a function apply_twice(f, x) that applies function f to x twice.\nDefine add3(n) that returns n + 3.\nPrint apply_twice(add3, 7).",
        "hint": "apply_twice returns f(f(x)).",
        "starter": "# Define add3(n) and apply_twice(f, x)\n# Print apply_twice(add3, 7)\n",
        "tests": [
            {"input": "", "expected_output": "13"}
        ]
    },
    # === LOOPS (11-15) ===
    {
        "id": 11,
        "title": "Sum 1 to N",
        "category": "loops",
        "difficulty": "easy",
        "description": "Use a loop to compute the sum of integers from 1 to 100.\nPrint the result.",
        "hint": "Use a for loop with range or a while loop with an accumulator.",
        "starter": "# Compute and print sum of 1 to 100\n",
        "tests": [
            {"input": "", "expected_output": "5050"}
        ]
    },
    {
        "id": 12,
        "title": "FizzBuzz",
        "category": "loops",
        "difficulty": "easy",
        "description": "Print numbers 1 to 20. For multiples of 3 print \"Fizz\",\nfor multiples of 5 print \"Buzz\", for both print \"FizzBuzz\".",
        "hint": "Check divisibility by 15 first, then 3, then 5.",
        "starter": "# FizzBuzz from 1 to 20\n",
        "tests": [
            {"input": "", "expected_output": "1\n2\nFizz\n4\nBuzz\nFizz\n7\n8\nFizz\nBuzz\n11\nFizz\n13\n14\nFizzBuzz\n16\n17\nFizz\n19\nBuzz"}
        ]
    },
    {
        "id": 13,
        "title": "Multiplication Table",
        "category": "loops",
        "difficulty": "easy",
        "description": "Print the multiplication table for 7 (7x1 through 7x10).\nFormat each line as: \"7 x 1 = 7\"",
        "hint": "Use a for loop and f-strings or string concatenation.",
        "starter": "# Print 7x1 through 7x10\n",
        "tests": [
            {"input": "", "expected_output": "7 x 1 = 7\n7 x 2 = 14\n7 x 3 = 21\n7 x 4 = 28\n7 x 5 = 35\n7 x 6 = 42\n7 x 7 = 49\n7 x 8 = 56\n7 x 9 = 63\n7 x 10 = 70"}
        ]
    },
    {
        "id": 14,
        "title": "Collatz Sequence",
        "category": "loops",
        "difficulty": "medium",
        "description": "Write a function collatz_steps(n) that returns how many steps it takes\nfor n to reach 1 using the Collatz rules:\n  if even: n = n / 2\n  if odd:  n = 3n + 1\nPrint collatz_steps(6) and collatz_steps(27).",
        "hint": "Use a while loop counting steps until n == 1.",
        "starter": "# Define collatz_steps(n) and print for 6 and 27\n",
        "tests": [
            {"input": "", "expected_output": "8\n111"}
        ]
    },
    {
        "id": 15,
        "title": "Prime Checker",
        "category": "loops",
        "difficulty": "medium",
        "description": "Write a function is_prime(n) that returns true if n is prime.\nPrint results for 2, 17, 1, 4, and 97.",
        "hint": "Check divisibility from 2 up to sqrt(n). 1 is not prime.",
        "starter": "# Define is_prime(n) and print for 2, 17, 1, 4, 97\n",
        "tests": [
            {"input": "", "expected_output": "true\ntrue\nfalse\nfalse\ntrue"}
        ]
    },
    # === COLLECTIONS (16-20) ===
    {
        "id": 16,
        "title": "List Sum",
        "category": "collections",
        "difficulty": "easy",
        "description": "Given nums = [3, 7, 1, 9, 4, 6, 2, 8, 5, 10], compute and print the sum.",
        "hint": "Use a for loop to accumulate, or use a built-in if available.",
        "starter": "nums = [3, 7, 1, 9, 4, 6, 2, 8, 5, 10]\n# Compute and print the sum\n",
        "tests": [
            {"input": "", "expected_output": "55"}
        ]
    },
    {
        "id": 17,
        "title": "List Max",
        "category": "collections",
        "difficulty": "easy",
        "description": "Write a function find_max(lst) that returns the maximum element.\nPrint find_max([3, 7, 1, 9, 4]).",
        "hint": "Track the maximum as you iterate through the list.",
        "starter": "# Define find_max(lst) and test it\n",
        "tests": [
            {"input": "", "expected_output": "9"}
        ]
    },
    {
        "id": 18,
        "title": "List Reverse",
        "category": "collections",
        "difficulty": "medium",
        "description": "Write a function reverse_list(lst) that returns a new reversed list.\nPrint reverse_list([1, 2, 3, 4, 5]).",
        "hint": "Build a new list by prepending or iterating backwards.",
        "starter": "# Define reverse_list(lst) and test it\n",
        "tests": [
            {"input": "", "expected_output": "[5, 4, 3, 2, 1]"}
        ]
    },
    {
        "id": 19,
        "title": "Map Builder",
        "category": "collections",
        "difficulty": "medium",
        "description": "Create a map (dictionary) counting occurrences of each word in:\nwords = [\"apple\", \"banana\", \"apple\", \"cherry\", \"banana\", \"apple\"]\nPrint the count for \"apple\".",
        "hint": "Use a map/dictionary. Check if the key exists before incrementing.",
        "starter": 'words = ["apple", "banana", "apple", "cherry", "banana", "apple"]\n# Count occurrences and print count for "apple"\n',
        "tests": [
            {"input": "", "expected_output": "3"}
        ]
    },
    {
        "id": 20,
        "title": "Unique Elements",
        "category": "collections",
        "difficulty": "medium",
        "description": "Write a function unique(lst) that returns a list of unique elements\npreserving first-occurrence order.\nPrint unique([1, 2, 3, 2, 1, 4, 3, 5]).",
        "hint": "Track seen elements with a set; only add unseen ones to result.",
        "starter": "# Define unique(lst) and test it\n",
        "tests": [
            {"input": "", "expected_output": "[1, 2, 3, 4, 5]"}
        ]
    },
    # === STRINGS (21-24) ===
    {
        "id": 21,
        "title": "Palindrome Check",
        "category": "strings",
        "difficulty": "easy",
        "description": "Write a function is_palindrome(s) that returns true if s reads the same forwards and backwards.\nPrint is_palindrome(\"racecar\") and is_palindrome(\"hello\").",
        "hint": "Compare the string to its reverse.",
        "starter": '# Define is_palindrome(s) and test it\n',
        "tests": [
            {"input": "", "expected_output": "true\nfalse"}
        ]
    },
    {
        "id": 22,
        "title": "Character Counter",
        "category": "strings",
        "difficulty": "medium",
        "description": "Write a function count_char(s, c) that returns how many times character c appears in s.\nPrint count_char(\"mississippi\", \"s\").",
        "hint": "Iterate through each character and count matches.",
        "starter": '# Define count_char(s, c) and test it\n',
        "tests": [
            {"input": "", "expected_output": "4"}
        ]
    },
    {
        "id": 23,
        "title": "Caesar Cipher",
        "category": "strings",
        "difficulty": "hard",
        "description": "Write a function caesar(text, shift) that shifts each lowercase letter by shift positions.\nNon-letters stay unchanged. Wrap around z→a.\nPrint caesar(\"hello\", 3).",
        "hint": "Use character codes. For each char: new = (old - 'a' + shift) % 26 + 'a'.",
        "starter": '# Define caesar(text, shift) and print caesar("hello", 3)\n',
        "tests": [
            {"input": "", "expected_output": "khoor"}
        ]
    },
    {
        "id": 24,
        "title": "Word Frequency",
        "category": "strings",
        "difficulty": "hard",
        "description": "Write a function word_count(text) that splits text by spaces and returns\na map of word→count.\nPrint the count of \"the\" in: \"the cat sat on the mat by the door\".",
        "hint": "Split the string, iterate, and count with a map.",
        "starter": '# Define word_count(text) and test it\n',
        "tests": [
            {"input": "", "expected_output": "3"}
        ]
    },
    # === CLASSES (25-27) ===
    {
        "id": 25,
        "title": "Counter Class",
        "category": "classes",
        "difficulty": "medium",
        "description": "Create a class Counter with:\n- init() sets count to 0\n- increment() adds 1\n- get() returns current count\nCreate a counter, increment 3 times, print get().",
        "hint": "Use class with init, define methods that modify self.count.",
        "starter": "# Define class Counter and test it\n",
        "tests": [
            {"input": "", "expected_output": "3"}
        ]
    },
    {
        "id": 26,
        "title": "Stack Class",
        "category": "classes",
        "difficulty": "medium",
        "description": "Implement a Stack class with push(val), pop(), peek(), and is_empty() methods.\nPush 10, 20, 30. Print peek(), pop(), peek().",
        "hint": "Use a list internally. Push appends, pop removes last.",
        "starter": "# Define class Stack and test it\n",
        "tests": [
            {"input": "", "expected_output": "30\n30\n20"}
        ]
    },
    {
        "id": 27,
        "title": "Linked List",
        "category": "classes",
        "difficulty": "hard",
        "description": "Implement a singly linked list with:\n- push(val) — add to front\n- to_list() — return as a sauravcode list\nPush 1, 2, 3 and print to_list().",
        "hint": "Each node has val and next. Push creates a new head.",
        "starter": "# Define Node and LinkedList classes\n",
        "tests": [
            {"input": "", "expected_output": "[3, 2, 1]"}
        ]
    },
    # === PATTERNS (28-30) ===
    {
        "id": 28,
        "title": "Match Expression",
        "category": "patterns",
        "difficulty": "medium",
        "description": "Write a function day_type(day) that uses match/case to return:\n\"weekday\" for \"mon\",\"tue\",\"wed\",\"thu\",\"fri\"\n\"weekend\" for \"sat\",\"sun\"\n\"unknown\" otherwise.\nPrint day_type(\"mon\"), day_type(\"sat\"), day_type(\"xyz\").",
        "hint": "Use match day: case \"mon\" | \"tue\" ... syntax.",
        "starter": "# Define day_type(day) using match/case\n",
        "tests": [
            {"input": "", "expected_output": "weekday\nweekend\nunknown"}
        ]
    },
    {
        "id": 29,
        "title": "Enum Shapes",
        "category": "patterns",
        "difficulty": "hard",
        "description": "Define an enum Shape with variants Circle, Square, Triangle.\nWrite a function describe(s) that uses match to print a description.\nPrint describe for each variant.",
        "hint": "Use enum Shape { Circle, Square, Triangle } and match.",
        "starter": "# Define enum Shape and describe(s) function\n",
        "tests": [
            {"input": "", "expected_output": "A round shape\nA four-sided shape\nA three-sided shape"}
        ]
    },
    {
        "id": 30,
        "title": "List Comprehension",
        "category": "patterns",
        "difficulty": "medium",
        "description": "Use a list comprehension to create a list of squares of even numbers from 1 to 10.\nPrint the result.",
        "hint": "Use [x*x for x in range(1,11) if x%2==0] syntax.",
        "starter": "# Create list of squares of even numbers 1-10\n",
        "tests": [
            {"input": "", "expected_output": "[4, 16, 36, 64, 100]"}
        ]
    },
    # === ALGORITHMS (31-35) ===
    {
        "id": 31,
        "title": "Bubble Sort",
        "category": "algorithms",
        "difficulty": "medium",
        "description": "Write a function bubble_sort(lst) that sorts a list in ascending order.\nPrint bubble_sort([5, 3, 8, 1, 9, 2]).",
        "hint": "Nested loops: compare adjacent elements, swap if out of order.",
        "starter": "# Define bubble_sort(lst) and test it\n",
        "tests": [
            {"input": "", "expected_output": "[1, 2, 3, 5, 8, 9]"}
        ]
    },
    {
        "id": 32,
        "title": "Binary Search",
        "category": "algorithms",
        "difficulty": "medium",
        "description": "Write a function binary_search(lst, target) that returns the index\nof target in a sorted list, or -1 if not found.\nPrint binary_search([1,3,5,7,9,11], 7) and binary_search([1,3,5,7,9,11], 4).",
        "hint": "Use low/high pointers, check mid element each iteration.",
        "starter": "# Define binary_search(lst, target) and test it\n",
        "tests": [
            {"input": "", "expected_output": "3\n-1"}
        ]
    },
    {
        "id": 33,
        "title": "Selection Sort",
        "category": "algorithms",
        "difficulty": "medium",
        "description": "Write selection_sort(lst) that sorts by finding the minimum each pass.\nPrint selection_sort([64, 25, 12, 22, 11]).",
        "hint": "For each position, find the minimum in the remaining unsorted portion.",
        "starter": "# Define selection_sort(lst) and test it\n",
        "tests": [
            {"input": "", "expected_output": "[11, 12, 22, 25, 64]"}
        ]
    },
    {
        "id": 34,
        "title": "Matrix Transpose",
        "category": "algorithms",
        "difficulty": "hard",
        "description": "Write a function transpose(matrix) that transposes a 2D list.\nGiven [[1,2,3],[4,5,6]], print the transposed result.",
        "hint": "Swap rows and columns. Result[j][i] = matrix[i][j].",
        "starter": "# Define transpose(matrix) and test it\n",
        "tests": [
            {"input": "", "expected_output": "[[1, 4], [2, 5], [3, 6]]"}
        ]
    },
    {
        "id": 35,
        "title": "Merge Sort",
        "category": "algorithms",
        "difficulty": "hard",
        "description": "Implement merge_sort(lst) using the divide-and-conquer approach.\nPrint merge_sort([38, 27, 43, 3, 9, 82, 10]).",
        "hint": "Split list in half, sort each half recursively, merge sorted halves.",
        "starter": "# Define merge_sort(lst) and test it\n",
        "tests": [
            {"input": "", "expected_output": "[3, 9, 10, 27, 38, 43, 82]"}
        ]
    },
]

CATEGORIES = sorted(set(c["category"] for c in CHALLENGES))
DIFFICULTIES = ["easy", "medium", "hard"]

# ── Progress tracking ──────────────────────────────────────────────────

def _progress_file():
    """Return path to progress file."""
    return Path.home() / ".sauravchallenge_progress.json"

def _load_progress():
    """Load progress from disk."""
    pf = _progress_file()
    if pf.exists():
        try:
            return json.loads(pf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"solved": [], "attempts": {}}

def _save_progress(progress):
    """Save progress to disk."""
    pf = _progress_file()
    pf.write_text(json.dumps(progress, indent=2), encoding="utf-8")

def _reset_progress():
    """Reset all progress."""
    pf = _progress_file()
    if pf.exists():
        pf.unlink()
    print("Progress reset.")

# ── Challenge execution ────────────────────────────────────────────────

def _run_srv_code(code, timeout=10):
    """Run sauravcode source and capture output."""
    # Find the interpreter
    here = Path(__file__).resolve().parent
    interp = here / "saurav.py"
    if not interp.exists():
        return None, "Cannot find saurav.py interpreter"

    import subprocess
    with tempfile.NamedTemporaryFile(mode="w", suffix=".srv", delete=False,
                                      encoding="utf-8") as f:
        f.write(code)
        tmp = f.name
    try:
        result = subprocess.run(
            [sys.executable, str(interp), tmp],
            capture_output=True, text=True, timeout=timeout
        )
        output = result.stdout.rstrip("\n")
        err = result.stderr.strip()
        if result.returncode != 0 and err:
            return None, err
        return output, None
    except subprocess.TimeoutExpired:
        return None, "Timeout: solution took too long (>10s)"
    except Exception as e:
        return None, str(e)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass

def _get_challenge(cid):
    """Get challenge by ID."""
    for c in CHALLENGES:
        if c["id"] == cid:
            return c
    return None

# ── Display functions ──────────────────────────────────────────────────

_DIFF_COLORS = {"easy": "\033[32m", "medium": "\033[33m", "hard": "\033[31m"}
_RESET = "\033[0m"

def _colorize_diff(diff):
    """Colorize difficulty label."""
    color = _DIFF_COLORS.get(diff, "")
    return f"{color}{diff}{_RESET}"

def list_challenges(difficulty=None, category=None, show_status=True):
    """List all challenges with optional filters."""
    progress = _load_progress() if show_status else {"solved": []}
    filtered = CHALLENGES
    if difficulty:
        filtered = [c for c in filtered if c["difficulty"] == difficulty]
    if category:
        filtered = [c for c in filtered if c["category"] == category]

    if not filtered:
        print("No challenges match the filters.")
        return

    print(f"\n{'ID':>3}  {'Status':^6}  {'Difficulty':<8}  {'Category':<12}  Title")
    print("-" * 65)
    for c in filtered:
        status = "✅" if c["id"] in progress["solved"] else "  "
        diff = _colorize_diff(c["difficulty"])
        print(f"{c['id']:>3}  {status:^6}  {diff:<17}  {c['category']:<12}  {c['title']}")

    solved = sum(1 for c in filtered if c["id"] in progress["solved"])
    print(f"\n{solved}/{len(filtered)} solved")
    print(f"\nCategories: {', '.join(CATEGORIES)}")

def show_challenge(cid):
    """Show detailed challenge info."""
    c = _get_challenge(cid)
    if not c:
        print(f"Challenge {cid} not found. Valid IDs: 1-{len(CHALLENGES)}")
        return

    progress = _load_progress()
    status = "✅ SOLVED" if c["id"] in progress["solved"] else "⬜ Unsolved"

    print(f"\n{'='*50}")
    print(f"  Challenge #{c['id']}: {c['title']}")
    print(f"  Difficulty: {_colorize_diff(c['difficulty'])}  |  Category: {c['category']}  |  {status}")
    print(f"{'='*50}")
    print(f"\n{c['description']}")
    print(f"\n💡 Hint: {c['hint']}")
    print(f"\n📝 Tests: {len(c['tests'])} test case(s)")
    attempts = progress.get("attempts", {}).get(str(cid), 0)
    if attempts:
        print(f"📊 Attempts: {attempts}")
    print(f"\nGet starter code: python sauravchallenge.py --starter {cid}")
    print(f"Submit solution:  python sauravchallenge.py --attempt {cid} your_solution.srv")

def show_starter(cid):
    """Print starter code for a challenge."""
    c = _get_challenge(cid)
    if not c:
        print(f"Challenge {cid} not found.")
        return
    print(f"# Challenge #{c['id']}: {c['title']}")
    print(f"# Difficulty: {c['difficulty']} | Category: {c['category']}")
    print(f"# {c['description'].split(chr(10))[0]}")
    print()
    print(c["starter"])

def attempt_challenge(cid, solution_path=None, from_stdin=False):
    """Test a solution against challenge test cases."""
    c = _get_challenge(cid)
    if not c:
        print(f"Challenge {cid} not found.")
        return False

    # Read solution
    if from_stdin:
        code = sys.stdin.read()
    elif solution_path:
        try:
            code = Path(solution_path).read_text(encoding="utf-8")
        except FileNotFoundError:
            print(f"File not found: {solution_path}")
            return False
    else:
        print("Provide a solution file or --stdin.")
        return False

    # Track attempt
    progress = _load_progress()
    key = str(cid)
    progress.setdefault("attempts", {})
    progress["attempts"][key] = progress["attempts"].get(key, 0) + 1
    _save_progress(progress)

    print(f"\n🧪 Testing Challenge #{cid}: {c['title']}")
    print(f"   Attempt #{progress['attempts'][key]}")
    print("-" * 40)

    all_passed = True
    for i, test in enumerate(c["tests"], 1):
        output, err = _run_srv_code(code)
        if err:
            print(f"  Test {i}: ❌ ERROR")
            print(f"    {err}")
            all_passed = False
            continue

        expected = test["expected_output"]
        if output == expected:
            print(f"  Test {i}: ✅ PASSED")
        else:
            print(f"  Test {i}: ❌ FAILED")
            print(f"    Expected: {expected}")
            print(f"    Got:      {output}")
            all_passed = False

    print("-" * 40)
    if all_passed:
        print(f"🎉 Challenge #{cid} SOLVED!")
        if cid not in progress["solved"]:
            progress["solved"].append(cid)
            _save_progress(progress)
            print("   Progress saved!")
    else:
        print(f"❌ Not all tests passed. Keep trying!")
        print(f"   Hint: {c['hint']}")

    return all_passed

def show_stats():
    """Show progress statistics."""
    progress = _load_progress()
    solved = progress.get("solved", [])
    total = len(CHALLENGES)

    print(f"\n📊 Challenge Progress")
    print("=" * 40)
    print(f"  Total solved: {len(solved)}/{total} ({100*len(solved)//total}%)")

    # By difficulty
    print(f"\n  By Difficulty:")
    for diff in DIFFICULTIES:
        diff_challenges = [c for c in CHALLENGES if c["difficulty"] == diff]
        diff_solved = sum(1 for c in diff_challenges if c["id"] in solved)
        bar_len = 20
        filled = bar_len * diff_solved // len(diff_challenges) if diff_challenges else 0
        bar = "█" * filled + "░" * (bar_len - filled)
        print(f"    {diff:<8} [{bar}] {diff_solved}/{len(diff_challenges)}")

    # By category
    print(f"\n  By Category:")
    for cat in CATEGORIES:
        cat_challenges = [c for c in CHALLENGES if c["category"] == cat]
        cat_solved = sum(1 for c in cat_challenges if c["id"] in solved)
        bar_len = 20
        filled = bar_len * cat_solved // len(cat_challenges) if cat_challenges else 0
        bar = "█" * filled + "░" * (bar_len - filled)
        print(f"    {cat:<12} [{bar}] {cat_solved}/{len(cat_challenges)}")

    # Total attempts
    attempts = progress.get("attempts", {})
    total_attempts = sum(attempts.values())
    if total_attempts:
        print(f"\n  Total attempts: {total_attempts}")
        if solved:
            avg = total_attempts / len(solved)
            print(f"  Avg attempts per solve: {avg:.1f}")

def random_challenge(difficulty=None):
    """Pick a random unsolved challenge."""
    progress = _load_progress()
    candidates = [c for c in CHALLENGES if c["id"] not in progress["solved"]]
    if difficulty:
        candidates = [c for c in candidates if c["difficulty"] == difficulty]
    if not candidates:
        if difficulty:
            print(f"All {difficulty} challenges solved! Try another difficulty.")
        else:
            print("🎉 All challenges solved! You've mastered sauravcode!")
        return
    chosen = _random.choice(candidates)
    show_challenge(chosen["id"])

def export_challenges(fmt):
    """Export challenges as JSON or CSV."""
    if fmt == "json":
        print(json.dumps(CHALLENGES, indent=2))
    elif fmt == "csv":
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["id", "title", "category", "difficulty", "description", "hint", "num_tests"])
        for c in CHALLENGES:
            writer.writerow([c["id"], c["title"], c["category"], c["difficulty"],
                           c["description"], c["hint"], len(c["tests"])])
        print(out.getvalue().rstrip())
    else:
        print(f"Unknown format: {fmt}. Use 'json' or 'csv'.")

# ── CLI ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="sauravchallenge — Coding challenges for learning sauravcode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               "  python sauravchallenge.py --list\n"
               "  python sauravchallenge.py --show 1\n"
               "  python sauravchallenge.py --starter 1 > solution.srv\n"
               "  python sauravchallenge.py --attempt 1 solution.srv\n"
               "  python sauravchallenge.py --random --difficulty easy\n"
    )
    parser.add_argument("--list", action="store_true", help="List all challenges")
    parser.add_argument("--show", type=int, metavar="ID", help="Show challenge details")
    parser.add_argument("--starter", type=int, metavar="ID", help="Print starter code")
    parser.add_argument("--attempt", type=int, metavar="ID", help="Test a solution")
    parser.add_argument("solution", nargs="?", help="Solution .srv file (with --attempt)")
    parser.add_argument("--stdin", action="store_true", help="Read solution from stdin")
    parser.add_argument("--stats", action="store_true", help="Show progress statistics")
    parser.add_argument("--reset", action="store_true", help="Reset all progress")
    parser.add_argument("--random", action="store_true", help="Pick a random unsolved challenge")
    parser.add_argument("--difficulty", choices=DIFFICULTIES, help="Filter by difficulty")
    parser.add_argument("--category", choices=CATEGORIES, help="Filter by category")
    parser.add_argument("--export", choices=["json", "csv"], help="Export challenges")

    args = parser.parse_args()

    if args.reset:
        _reset_progress()
    elif args.export:
        export_challenges(args.export)
    elif args.stats:
        show_stats()
    elif args.show:
        show_challenge(args.show)
    elif args.starter is not None:
        show_starter(args.starter)
    elif args.attempt:
        attempt_challenge(args.attempt, args.solution, args.stdin)
    elif args.random:
        random_challenge(args.difficulty)
    elif args.list or not any(vars(args).values()):
        list_challenges(args.difficulty, args.category)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
