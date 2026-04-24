#!/usr/bin/env python3
"""sauravduel — Competitive code duel arena for sauravcode (.srv).

Two solutions enter. One champion emerges. Head-to-head battles
scored on correctness, speed, and elegance by an autonomous judge.

Usage:
    python sauravduel.py                              # Arena dashboard
    python sauravduel.py --list                       # List all duel problems
    python sauravduel.py --show 1                     # Show problem details
    python sauravduel.py --duel 1 a.srv b.srv         # Duel two solutions
    python sauravduel.py --duel 1 a.srv --vs-ref      # Duel against reference
    python sauravduel.py --tournament dir/             # Round-robin tournament
    python sauravduel.py --history                    # Duel history
    python sauravduel.py --rankings                   # ELO rankings
    python sauravduel.py --export json                # Export data as JSON
    python sauravduel.py --reset                      # Reset all history

Scoring:
    Correctness (60%): % of test cases passed
    Speed (20%):       Relative execution time (faster = higher)
    Elegance (20%):    Code brevity comparison (shorter = higher)

    Overall = correctness * 0.6 + speed * 0.2 + elegance * 0.2
"""

import sys
import os
import io
import json
import argparse
import time
import threading
import glob
import itertools
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime

# Fix Windows console encoding
if sys.stdout.encoding and sys.stdout.encoding.lower().startswith('cp'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from saurav import tokenize, Parser, Interpreter

# ── Terminal colors ────────────────────────────────────────────────────

try:
    from _termcolors import RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, BOLD, DIM, RESET
except ImportError:
    RED = GREEN = YELLOW = BLUE = MAGENTA = CYAN = BOLD = DIM = RESET = ""

# ── Duel problems ─────────────────────────────────────────────────────

PROBLEMS = [
    {
        "id": 1,
        "title": "Hello World",
        "difficulty": "easy",
        "description": "Print exactly: Hello, World!",
        "time_limit": 5,
        "test_cases": [
            {"input": "", "expected": "Hello, World!"}
        ],
        "reference": 'print "Hello, World!"',
    },
    {
        "id": 2,
        "title": "Sum 1 to N",
        "difficulty": "easy",
        "description": "Read N from input, print the sum of integers 1 to N.",
        "time_limit": 5,
        "test_cases": [
            {"input": "5", "expected": "15"},
            {"input": "10", "expected": "55"},
            {"input": "1", "expected": "1"},
            {"input": "100", "expected": "5050"},
        ],
        "reference": 'set n to input\nset n to number n\nset s to 0\nset i to 1\nwhile i <= n\n  set s to s + i\n  set i to i + 1\nend\nprint s',
    },
    {
        "id": 3,
        "title": "Reverse String",
        "difficulty": "easy",
        "description": "Read a string and print it reversed.",
        "time_limit": 5,
        "test_cases": [
            {"input": "hello", "expected": "olleh"},
            {"input": "abcdef", "expected": "fedcba"},
            {"input": "a", "expected": "a"},
        ],
        "reference": 'set s to input\nset r to ""\nset i to length s\nwhile i > 0\n  set i to i - 1\n  set r to r + char_at s i\nend\nprint r',
    },
    {
        "id": 4,
        "title": "Count Vowels",
        "difficulty": "easy",
        "description": "Read a string and print the number of vowels (a, e, i, o, u, case-insensitive).",
        "time_limit": 5,
        "test_cases": [
            {"input": "hello", "expected": "2"},
            {"input": "AEIOU", "expected": "5"},
            {"input": "xyz", "expected": "0"},
            {"input": "Programming", "expected": "3"},
        ],
        "reference": 'set s to input\nset s to lowercase s\nset c to 0\nset i to 0\nwhile i < length s\n  set ch to char_at s i\n  if ch == "a" or ch == "e" or ch == "i" or ch == "o" or ch == "u"\n    set c to c + 1\n  end\n  set i to i + 1\nend\nprint c',
    },
    {
        "id": 5,
        "title": "Max of Three",
        "difficulty": "easy",
        "description": "Read three numbers (one per line) and print the largest.",
        "time_limit": 5,
        "test_cases": [
            {"input": "3\n7\n2", "expected": "7"},
            {"input": "10\n10\n5", "expected": "10"},
            {"input": "-1\n-5\n-3", "expected": "-1"},
        ],
        "reference": 'set a to number input\nset b to number input\nset c to number input\nset m to a\nif b > m\n  set m to b\nend\nif c > m\n  set m to c\nend\nprint m',
    },
    {
        "id": 6,
        "title": "Fibonacci N",
        "difficulty": "medium",
        "description": "Read N and print the Nth Fibonacci number (0-indexed: fib(0)=0, fib(1)=1).",
        "time_limit": 5,
        "test_cases": [
            {"input": "0", "expected": "0"},
            {"input": "1", "expected": "1"},
            {"input": "6", "expected": "8"},
            {"input": "10", "expected": "55"},
        ],
        "reference": 'set n to number input\nif n == 0\n  print 0\nelse\n  set a to 0\n  set b to 1\n  set i to 1\n  while i < n\n    set t to a + b\n    set a to b\n    set b to t\n    set i to i + 1\n  end\n  print b\nend',
    },
    {
        "id": 7,
        "title": "Palindrome Check",
        "difficulty": "medium",
        "description": "Read a string and print 'yes' if it's a palindrome, 'no' otherwise (case-insensitive).",
        "time_limit": 5,
        "test_cases": [
            {"input": "racecar", "expected": "yes"},
            {"input": "hello", "expected": "no"},
            {"input": "Madam", "expected": "yes"},
            {"input": "a", "expected": "yes"},
        ],
        "reference": 'set s to lowercase input\nset r to ""\nset i to length s\nwhile i > 0\n  set i to i - 1\n  set r to r + char_at s i\nend\nif s == r\n  print "yes"\nelse\n  print "no"\nend',
    },
    {
        "id": 8,
        "title": "Count Words",
        "difficulty": "medium",
        "description": "Read a line of text and print the number of words (space-separated).",
        "time_limit": 5,
        "test_cases": [
            {"input": "hello world", "expected": "2"},
            {"input": "one", "expected": "1"},
            {"input": "the quick brown fox", "expected": "4"},
        ],
        "reference": 'set s to input\nset c to 1\nset i to 0\nwhile i < length s\n  if char_at s i == " "\n    set c to c + 1\n  end\n  set i to i + 1\nend\nprint c',
    },
    {
        "id": 9,
        "title": "Triangle Numbers",
        "difficulty": "medium",
        "description": "Read N and print the first N triangle numbers, one per line. Triangle(k) = k*(k+1)/2.",
        "time_limit": 5,
        "test_cases": [
            {"input": "4", "expected": "1\n3\n6\n10"},
            {"input": "1", "expected": "1"},
            {"input": "6", "expected": "1\n3\n6\n10\n15\n21"},
        ],
        "reference": 'set n to number input\nset i to 1\nwhile i <= n\n  set t to i * (i + 1) / 2\n  print t\n  set i to i + 1\nend',
    },
    {
        "id": 10,
        "title": "Star Pyramid",
        "difficulty": "hard",
        "description": "Read N and print a centered pyramid of stars with N rows.",
        "time_limit": 5,
        "test_cases": [
            {"input": "3", "expected": "  *\n ***\n*****"},
            {"input": "1", "expected": "*"},
            {"input": "4", "expected": "   *\n  ***\n *****\n*******"},
        ],
        "reference": 'set n to number input\nset i to 1\nwhile i <= n\n  set spaces to n - i\n  set stars to 2 * i - 1\n  set line to ""\n  set j to 0\n  while j < spaces\n    set line to line + " "\n    set j to j + 1\n  end\n  set j to 0\n  while j < stars\n    set line to line + "*"\n    set j to j + 1\n  end\n  print line\n  set i to i + 1\nend',
    },
]

# ── Data paths ─────────────────────────────────────────────────────────

DATA_DIR = os.path.join(os.path.expanduser("~"), ".sauravcode")
HISTORY_FILE = os.path.join(DATA_DIR, "duel_history.json")


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _load_history():
    _ensure_data_dir()
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"duels": [], "elo": {}}


def _save_history(hist):
    _ensure_data_dir()
    with open(HISTORY_FILE, "w") as f:
        json.dump(hist, f, indent=2)


# ── Solution runner ────────────────────────────────────────────────────

def _run_solution(code, input_text="", timeout=5):
    """Run .srv code and return (output, elapsed_seconds, error)."""
    result = {"output": "", "time": 0.0, "error": None}

    def _execute():
        try:
            tokens = tokenize(code)
            parser = Parser(tokens)
            ast_nodes = parser.parse()
            interp = Interpreter()

            old_stdin = sys.stdin
            sys.stdin = io.StringIO(input_text)
            buf = io.StringIO()
            try:
                with redirect_stdout(buf), redirect_stderr(io.StringIO()):
                    interp.execute_body(ast_nodes)
            finally:
                sys.stdin = old_stdin

            result["output"] = buf.getvalue().rstrip("\n")
        except Exception as e:
            result["error"] = str(e)

    start = time.perf_counter()
    t = threading.Thread(target=_execute)
    t.start()
    t.join(timeout)
    elapsed = time.perf_counter() - start

    if t.is_alive():
        result["error"] = "TIMEOUT"
        result["time"] = timeout
    else:
        result["time"] = elapsed

    return result


# ── Judge ──────────────────────────────────────────────────────────────

def _judge(problem, code_a, code_b, name_a="Player A", name_b="Player B"):
    """Run both solutions on all test cases and produce a scored verdict."""
    tests = problem["test_cases"]
    tl = problem.get("time_limit", 5)

    results_a = []
    results_b = []
    for tc in tests:
        ra = _run_solution(code_a, tc.get("input", ""), tl)
        rb = _run_solution(code_b, tc.get("input", ""), tl)
        expected = tc["expected"]
        ra["passed"] = (ra["error"] is None and ra["output"].strip() == expected.strip())
        rb["passed"] = (rb["error"] is None and rb["output"].strip() == expected.strip())
        results_a.append(ra)
        results_b.append(rb)

    # Correctness (0-100)
    pass_a = sum(1 for r in results_a if r["passed"])
    pass_b = sum(1 for r in results_b if r["passed"])
    correct_a = (pass_a / len(tests)) * 100 if tests else 0
    correct_b = (pass_b / len(tests)) * 100 if tests else 0

    # Speed (0-100) - relative comparison
    time_a = sum(r["time"] for r in results_a)
    time_b = sum(r["time"] for r in results_b)
    total_time = time_a + time_b
    if total_time > 0:
        speed_a = (1 - time_a / total_time) * 100
        speed_b = (1 - time_b / total_time) * 100
    else:
        speed_a = speed_b = 50.0

    # Elegance (0-100) - brevity comparison
    len_a = len(code_a.strip())
    len_b = len(code_b.strip())
    total_len = len_a + len_b
    if total_len > 0:
        eleg_a = (1 - len_a / total_len) * 100
        eleg_b = (1 - len_b / total_len) * 100
    else:
        eleg_a = eleg_b = 50.0

    # Overall
    score_a = correct_a * 0.6 + speed_a * 0.2 + eleg_a * 0.2
    score_b = correct_b * 0.6 + speed_b * 0.2 + eleg_b * 0.2

    # Determine winner
    diff = abs(score_a - score_b)
    if diff < 2:
        outcome = "draw"
        verdict_text = "DRAW"
    elif score_a > score_b:
        outcome = "a"
        verdict_text = f"{name_a} WINS"
    else:
        outcome = "b"
        verdict_text = f"{name_b} WINS"

    if diff < 2:
        intensity = "Dead heat!"
    elif diff < 10:
        intensity = "Razor-thin margin!"
    elif diff < 25:
        intensity = "Clear victory."
    else:
        intensity = "Decisive domination!"

    # Commentary
    commentary = []
    if correct_a != correct_b:
        better = name_a if correct_a > correct_b else name_b
        commentary.append(f"{better} dominated in correctness ({max(correct_a,correct_b):.0f}% vs {min(correct_a,correct_b):.0f}%)")
    if abs(speed_a - speed_b) > 10:
        faster = name_a if speed_a > speed_b else name_b
        commentary.append(f"{faster} was significantly faster")
    if abs(eleg_a - eleg_b) > 10:
        shorter = name_a if eleg_a > eleg_b else name_b
        commentary.append(f"{shorter} wrote more elegant (shorter) code")

    # Test case callouts
    callouts = []
    for i, (ra, rb) in enumerate(zip(results_a, results_b)):
        if ra["passed"] != rb["passed"]:
            winner = name_a if ra["passed"] else name_b
            callouts.append(f"Test {i+1}: Only {winner} passed")

    return {
        "name_a": name_a,
        "name_b": name_b,
        "scores": {
            "a": {"correctness": correct_a, "speed": speed_a, "elegance": eleg_a, "overall": score_a,
                   "passed": pass_a, "total": len(tests), "time": time_a, "chars": len_a},
            "b": {"correctness": correct_b, "speed": speed_b, "elegance": eleg_b, "overall": score_b,
                   "passed": pass_b, "total": len(tests), "time": time_b, "chars": len_b},
        },
        "outcome": outcome,
        "verdict": verdict_text,
        "intensity": intensity,
        "commentary": commentary,
        "callouts": callouts,
        "problem_id": problem["id"],
        "problem_title": problem["title"],
        "timestamp": datetime.now().isoformat(),
    }


# ── ELO calculation ───────────────────────────────────────────────────

def _update_elo(elo, name_a, name_b, outcome, k=32):
    """Update ELO ratings. outcome: 'a', 'b', or 'draw'."""
    ra = elo.get(name_a, 1200)
    rb = elo.get(name_b, 1200)
    ea = 1 / (1 + 10 ** ((rb - ra) / 400))
    eb = 1 - ea
    if outcome == "a":
        sa, sb = 1, 0
    elif outcome == "b":
        sa, sb = 0, 1
    else:
        sa, sb = 0.5, 0.5
    elo[name_a] = round(ra + k * (sa - ea))
    elo[name_b] = round(rb + k * (sb - eb))


# ── Display helpers ────────────────────────────────────────────────────

def _bar(label, val_a, val_b, width=30):
    """Render a comparison bar."""
    total = val_a + val_b if (val_a + val_b) > 0 else 1
    len_a = int((val_a / total) * width)
    len_b = width - len_a
    bar_a = f"{CYAN}{'█' * len_a}{RESET}"
    bar_b = f"{MAGENTA}{'█' * len_b}{RESET}"
    return f"  {label:>13s}  {val_a:6.1f} {bar_a}{bar_b} {val_b:6.1f}"


def _print_verdict(result):
    """Print the full duel verdict."""
    sa = result["scores"]["a"]
    sb = result["scores"]["b"]
    na = result["name_a"]
    nb = result["name_b"]

    print()
    print(f"{BOLD}{'=' * 60}{RESET}")
    print(f"{BOLD}  ⚔️  DUEL ARENA — {result['problem_title']}{RESET}")
    print(f"{'=' * 60}")
    print()
    print(f"  {CYAN}{na}{RESET}  vs  {MAGENTA}{nb}{RESET}")
    print()
    print(_bar("Correctness", sa["correctness"], sb["correctness"]))
    print(_bar("Speed", sa["speed"], sb["speed"]))
    print(_bar("Elegance", sa["elegance"], sb["elegance"]))
    print(f"  {'─' * 56}")
    print(_bar("OVERALL", sa["overall"], sb["overall"]))
    print()
    print(f"  Tests: {CYAN}{na}{RESET} {sa['passed']}/{sa['total']}  |  {MAGENTA}{nb}{RESET} {sb['passed']}/{sb['total']}")
    print(f"  Time:  {CYAN}{na}{RESET} {sa['time']:.4f}s  |  {MAGENTA}{nb}{RESET} {sb['time']:.4f}s")
    print(f"  Chars: {CYAN}{na}{RESET} {sa['chars']}  |  {MAGENTA}{nb}{RESET} {sb['chars']}")
    print()

    # Verdict
    if result["outcome"] == "draw":
        color = YELLOW
    elif result["outcome"] == "a":
        color = CYAN
    else:
        color = MAGENTA
    print(f"  {BOLD}{color}🏆 {result['verdict']}{RESET}  — {result['intensity']}")
    print()

    # Commentary
    if result["commentary"]:
        print(f"  {BOLD}Judge's Notes:{RESET}")
        for note in result["commentary"]:
            print(f"    • {note}")
    if result["callouts"]:
        for callout in result["callouts"]:
            print(f"    ⚡ {callout}")

    # Recommendations
    if result["outcome"] != "draw":
        loser = na if result["outcome"] == "b" else nb
        loser_s = sa if result["outcome"] == "b" else sb
        tips = []
        if loser_s["correctness"] < 100:
            tips.append("Fix failing test cases first — correctness is 60% of the score")
        if loser_s["speed"] < 40:
            tips.append("Optimize execution time — avoid redundant loops")
        if loser_s["elegance"] < 40:
            tips.append("Shorten your code — every character counts")
        if tips:
            print(f"\n  {BOLD}Tips for {loser}:{RESET}")
            for tip in tips:
                print(f"    💡 {tip}")

    print()
    print(f"{'=' * 60}")


# ── Commands ───────────────────────────────────────────────────────────

def cmd_dashboard():
    """Show arena dashboard."""
    hist = _load_history()
    total = len(hist["duels"])
    print(f"\n{BOLD}  ⚔️  SAURAVCODE DUEL ARENA{RESET}")
    print(f"  {'─' * 40}")
    print(f"  Problems:  {len(PROBLEMS)}")
    print(f"  Duels:     {total}")
    print(f"  Fighters:  {len(hist.get('elo', {}))}")
    if hist.get("elo"):
        top = sorted(hist["elo"].items(), key=lambda x: -x[1])[:3]
        print(f"\n  {BOLD}Top Fighters:{RESET}")
        medals = ["🥇", "🥈", "🥉"]
        for i, (name, elo) in enumerate(top):
            print(f"    {medals[i]} {name} — ELO {elo}")
    print(f"\n  Use --list to see problems, --duel to fight!\n")


def cmd_list():
    """List all problems."""
    print(f"\n{BOLD}  ⚔️  Duel Problems{RESET}\n")
    for p in PROBLEMS:
        diff_color = {"easy": GREEN, "medium": YELLOW, "hard": RED}.get(p["difficulty"], "")
        print(f"  {BOLD}#{p['id']:>2}{RESET}  {p['title']:<25s} {diff_color}[{p['difficulty']}]{RESET}  ({len(p['test_cases'])} tests)")
    print()


def cmd_show(pid):
    """Show problem details."""
    prob = next((p for p in PROBLEMS if p["id"] == pid), None)
    if not prob:
        print(f"{RED}Problem #{pid} not found.{RESET}")
        return
    diff_color = {"easy": GREEN, "medium": YELLOW, "hard": RED}.get(prob["difficulty"], "")
    print(f"\n{BOLD}  Problem #{prob['id']}: {prob['title']}{RESET}")
    print(f"  Difficulty: {diff_color}{prob['difficulty']}{RESET}")
    print(f"  Time Limit: {prob['time_limit']}s")
    print(f"\n  {prob['description']}\n")
    print(f"  {BOLD}Sample Tests:{RESET}")
    for i, tc in enumerate(prob["test_cases"][:2]):
        inp = tc.get("input", "(none)")
        print(f"    Test {i+1}: input={repr(inp)}  →  {repr(tc['expected'])}")
    if len(prob["test_cases"]) > 2:
        print(f"    ... and {len(prob['test_cases'])-2} more hidden tests")
    print()


def cmd_duel(pid, file_a, file_b=None, vs_ref=False):
    """Run a duel between two solutions."""
    prob = next((p for p in PROBLEMS if p["id"] == pid), None)
    if not prob:
        print(f"{RED}Problem #{pid} not found.{RESET}")
        return

    # Load solution A
    if not os.path.exists(file_a):
        print(f"{RED}File not found: {file_a}{RESET}")
        return
    with open(file_a, "r") as f:
        code_a = f.read()
    name_a = os.path.basename(file_a)

    # Load solution B
    if vs_ref:
        code_b = prob["reference"]
        name_b = "Reference"
    elif file_b:
        if not os.path.exists(file_b):
            print(f"{RED}File not found: {file_b}{RESET}")
            return
        with open(file_b, "r") as f:
            code_b = f.read()
        name_b = os.path.basename(file_b)
    else:
        print(f"{RED}Provide a second .srv file or use --vs-ref{RESET}")
        return

    print(f"\n  ⚔️  Preparing duel on '{prob['title']}'...")
    result = _judge(prob, code_a, code_b, name_a, name_b)
    _print_verdict(result)

    # Save to history
    hist = _load_history()
    hist["duels"].append(result)
    _update_elo(hist.setdefault("elo", {}), name_a, name_b, result["outcome"])
    _save_history(hist)
    print(f"  {DIM}Duel recorded. ELO updated.{RESET}\n")


def cmd_tournament(directory):
    """Round-robin tournament of all .srv files in a directory."""
    files = sorted(glob.glob(os.path.join(directory, "*.srv")))
    if len(files) < 2:
        print(f"{RED}Need at least 2 .srv files in {directory}{RESET}")
        return

    names = [os.path.basename(f) for f in files]
    codes = []
    for fpath in files:
        with open(fpath, "r") as f:
            codes.append(f.read())

    print(f"\n{BOLD}  ⚔️  TOURNAMENT — {len(files)} fighters, {len(PROBLEMS)} problems{RESET}")
    print(f"  {'─' * 50}")

    # Track wins/losses/draws and points
    stats = {n: {"w": 0, "l": 0, "d": 0, "pts": 0.0} for n in names}
    hist = _load_history()

    for prob in PROBLEMS:
        print(f"\n  {BOLD}Round: {prob['title']}{RESET}")
        for i, j in itertools.combinations(range(len(files)), 2):
            result = _judge(prob, codes[i], codes[j], names[i], names[j])
            sa = result["scores"]["a"]["overall"]
            sb = result["scores"]["b"]["overall"]
            if result["outcome"] == "a":
                stats[names[i]]["w"] += 1
                stats[names[j]]["l"] += 1
                stats[names[i]]["pts"] += 3
                marker = f"{CYAN}{names[i]} wins{RESET}"
            elif result["outcome"] == "b":
                stats[names[j]]["w"] += 1
                stats[names[i]]["l"] += 1
                stats[names[j]]["pts"] += 3
                marker = f"{MAGENTA}{names[j]} wins{RESET}"
            else:
                stats[names[i]]["d"] += 1
                stats[names[j]]["d"] += 1
                stats[names[i]]["pts"] += 1
                stats[names[j]]["pts"] += 1
                marker = f"{YELLOW}Draw{RESET}"
            print(f"    {names[i]} vs {names[j]}: {marker}  ({sa:.1f} - {sb:.1f})")

            hist["duels"].append(result)
            _update_elo(hist.setdefault("elo", {}), names[i], names[j], result["outcome"])

    _save_history(hist)

    # Leaderboard
    ranked = sorted(stats.items(), key=lambda x: (-x[1]["pts"], -x[1]["w"]))
    print(f"\n{BOLD}  🏆 TOURNAMENT LEADERBOARD{RESET}")
    print(f"  {'─' * 50}")
    print(f"  {'#':>3}  {'Fighter':<25s} {'W':>3} {'L':>3} {'D':>3} {'Pts':>6}")
    for rank, (name, s) in enumerate(ranked, 1):
        print(f"  {rank:>3}  {name:<25s} {s['w']:>3} {s['l']:>3} {s['d']:>3} {s['pts']:>6.0f}")
    print()


def cmd_history():
    """Show duel history."""
    hist = _load_history()
    if not hist["duels"]:
        print(f"\n  No duels recorded yet. Use --duel to start!\n")
        return
    print(f"\n{BOLD}  ⚔️  Duel History ({len(hist['duels'])} duels){RESET}\n")
    for d in hist["duels"][-20:]:
        sa = d["scores"]["a"]["overall"]
        sb = d["scores"]["b"]["overall"]
        ts = d.get("timestamp", "")[:16]
        print(f"  {ts}  {d['problem_title']:<20s}  {d['name_a']} ({sa:.1f}) vs {d['name_b']} ({sb:.1f})  →  {d['verdict']}")
    if len(hist["duels"]) > 20:
        print(f"\n  ... showing last 20 of {len(hist['duels'])}")
    print()


def cmd_rankings():
    """Show ELO rankings."""
    hist = _load_history()
    elo = hist.get("elo", {})
    if not elo:
        print(f"\n  No rankings yet. Duel first!\n")
        return
    ranked = sorted(elo.items(), key=lambda x: -x[1])
    print(f"\n{BOLD}  ⚔️  ELO Rankings{RESET}\n")
    print(f"  {'#':>3}  {'Fighter':<30s} {'ELO':>6}")
    print(f"  {'─' * 45}")
    for i, (name, rating) in enumerate(ranked, 1):
        medal = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else "  "
        print(f"  {i:>3}  {medal} {name:<27s} {rating:>6}")
    print()


def cmd_export(fmt):
    """Export history and rankings."""
    hist = _load_history()
    if fmt == "json":
        print(json.dumps(hist, indent=2))
    else:
        print(f"{RED}Unsupported format: {fmt}. Use 'json'.{RESET}")


def cmd_reset():
    """Reset all history."""
    _ensure_data_dir()
    if os.path.exists(HISTORY_FILE):
        os.remove(HISTORY_FILE)
    print(f"  {GREEN}Duel history reset.{RESET}")


# ── CLI ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="sauravduel — Competitive code duel arena for sauravcode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--list", action="store_true", help="List all duel problems")
    parser.add_argument("--show", type=int, metavar="ID", help="Show problem details")
    parser.add_argument("--duel", nargs="+", metavar="ARG",
                        help="Duel: PROBLEM_ID file_a.srv [file_b.srv]")
    parser.add_argument("--vs-ref", action="store_true", help="Duel against reference solution")
    parser.add_argument("--tournament", metavar="DIR", help="Round-robin tournament")
    parser.add_argument("--history", action="store_true", help="Show duel history")
    parser.add_argument("--rankings", action="store_true", help="Show ELO rankings")
    parser.add_argument("--export", metavar="FMT", help="Export data (json)")
    parser.add_argument("--reset", action="store_true", help="Reset history")

    args = parser.parse_args()

    if args.list:
        cmd_list()
    elif args.show is not None:
        cmd_show(args.show)
    elif args.duel:
        if len(args.duel) < 2:
            print(f"{RED}Usage: --duel PROBLEM_ID file_a.srv [file_b.srv]{RESET}")
            return
        pid = int(args.duel[0])
        file_a = args.duel[1]
        file_b = args.duel[2] if len(args.duel) > 2 else None
        cmd_duel(pid, file_a, file_b, args.vs_ref)
    elif args.tournament:
        cmd_tournament(args.tournament)
    elif args.history:
        cmd_history()
    elif args.rankings:
        cmd_rankings()
    elif args.export:
        cmd_export(args.export)
    elif args.reset:
        cmd_reset()
    else:
        cmd_dashboard()


if __name__ == "__main__":
    main()
