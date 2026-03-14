#!/usr/bin/env python3
"""sauravlearn -- Interactive tutorial system for the sauravcode language.

Learn sauravcode through progressive lessons with explanations, examples,
and exercises that are automatically validated by running your code.

Usage:
    python sauravlearn.py                   # Start from first incomplete lesson
    python sauravlearn.py --list            # List all lessons and progress
    python sauravlearn.py --lesson 3        # Jump to lesson 3
    python sauravlearn.py --reset           # Reset all progress
    python sauravlearn.py --progress        # Show progress summary
    python sauravlearn.py --no-color        # Disable colored output

Features:
    - 12 progressive lessons covering core sauravcode concepts
    - Each lesson has explanation, live examples, and exercises
    - Exercises are auto-validated by running your code
    - Progress is saved between sessions (~/.sauravlearn_progress.json)
    - Hints available when stuck
    - Examples run live so you see real output
"""

import argparse
import io
import json
import os
import sys
import textwrap
import contextlib

# ---------------------------------------------------------------------------
# Import the sauravcode interpreter
# ---------------------------------------------------------------------------
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

try:
    from saurav import Interpreter, tokenize, Parser
except ImportError:
    print("Error: Cannot import saurav.py. Make sure it's in the same directory.")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------
_use_color = True

def _c(code, text):
    if not _use_color:
        return text
    return f"\033[{code}m{text}\033[0m"

def _green(t):   return _c("32", t)
def _red(t):     return _c("31", t)
def _cyan(t):    return _c("36", t)
def _yellow(t):  return _c("33", t)
def _bold(t):    return _c("1", t)
def _dim(t):     return _c("2", t)
def _magenta(t): return _c("35", t)

# ---------------------------------------------------------------------------
# Code runner
# ---------------------------------------------------------------------------
def run_code(source, capture=True):
    """Run sauravcode source and return (stdout_output, error_or_None)."""
    buf = io.StringIO()
    err = None
    try:
        tokens = tokenize(source)
        parser = Parser(tokens)
        ast_nodes = parser.parse()
        interp = Interpreter()
        if capture:
            with contextlib.redirect_stdout(buf):
                for node in ast_nodes:
                    interp.interpret(node)
        else:
            for node in ast_nodes:
                interp.interpret(node)
    except SystemExit:
        pass
    except Exception as e:
        err = str(e)
    return buf.getvalue(), err

# ---------------------------------------------------------------------------
# Lessons
# ---------------------------------------------------------------------------
def _lessons():
    """Return ordered list of lesson dicts."""
    return [
        {
            "title": "Hello, sauravcode!",
            "explanation": """\
Welcome to sauravcode! This language strips away ceremony — no parentheses
for function calls, no semicolons, no braces. Just clean, readable code.

The most basic statement is `print`. Unlike most languages, you don't
need parentheses:

    print "Hello, world!"

You can print numbers, strings, and expressions:

    print 42
    print 3 + 7""",
            "examples": [
                ('print "Hello, world!"', None),
                ('print 10 + 25', None),
            ],
            "exercises": [
                {
                    "prompt": 'Use `print` to output the text: Learning sauravcode!',
                    "hint": 'print "Learning sauravcode!"',
                    "check": lambda out, err: "Learning sauravcode!" in out and err is None,
                },
            ],
        },
        {
            "title": "Variables & Arithmetic",
            "explanation": """\
Assign variables with `=`. No `let`, `var`, or type declarations needed:

    x = 10
    name = "Alice"

Arithmetic works as expected: +, -, *, /, % (modulo).

    result = (5 + 3) * 2
    print result""",
            "examples": [
                ('x = 7\ny = 3\nprint x + y', None),
                ('price = 19\ntax = price * 15 / 100\nprint tax', None),
            ],
            "exercises": [
                {
                    "prompt": "Create two variables `a` and `b` with values 12 and 8.\nPrint their product (a * b).",
                    "hint": "a = 12\nb = 8\nprint a * b",
                    "check": lambda out, err: "96" in out and err is None,
                },
            ],
        },
        {
            "title": "Strings & F-strings",
            "explanation": """\
Strings are enclosed in double quotes. sauravcode supports f-strings
for interpolation — embed expressions inside curly braces:

    name = "World"
    print f"Hello {name}!"

Built-in string functions include `upper`, `lower`, `reverse`, `len`:

    print upper "hello"
    print len "sauravcode\"""",
            "examples": [
                ('name = "sauravcode"\nprint f"Learning {name} is fun!"', None),
                ('print reverse "hello"', None),
            ],
            "exercises": [
                {
                    "prompt": 'Create a variable `lang` set to "sauravcode".\nPrint its length using `len`.',
                    "hint": 'lang = "sauravcode"\nprint len lang',
                    "check": lambda out, err: "10" in out and err is None,
                },
            ],
        },
        {
            "title": "Lists",
            "explanation": """\
Lists are created with square brackets and commas:

    nums = [1, 2, 3, 4, 5]

Access elements by index (0-based):

    print nums[0]

Use `append`, `pop`, `len` to manipulate lists:

    append nums 6
    print len nums""",
            "examples": [
                ('fruits = ["apple", "banana", "cherry"]\nprint fruits[1]', None),
                ('nums = [10, 20, 30]\nappend nums 40\nprint nums', None),
            ],
            "exercises": [
                {
                    "prompt": "Create a list `colors` with 3 colors.\nAppend a 4th color and print the list length.",
                    "hint": 'colors = ["red", "green", "blue"]\nappend colors "yellow"\nprint len colors',
                    "check": lambda out, err: "4" in out and err is None,
                },
            ],
        },
        {
            "title": "Control Flow — if/else",
            "explanation": """\
Conditionals use `if`, `else if`, `else` with indentation:

    x = 15
    if x > 10
        print "big"
    else if x > 5
        print "medium"
    else
        print "small"

Comparison operators: ==, !=, <, >, <=, >=
Logical operators: and, or, not""",
            "examples": [
                ('age = 20\nif age >= 18\n    print "adult"\nelse\n    print "minor"', None),
            ],
            "exercises": [
                {
                    "prompt": 'Create a variable `score` set to 85.\nIf score >= 90 print "A", else if >= 80 print "B", else print "C".',
                    "hint": 'score = 85\nif score >= 90\n    print "A"\nelse if score >= 80\n    print "B"\nelse\n    print "C"',
                    "check": lambda out, err: out.strip() == "B" and err is None,
                },
            ],
        },
        {
            "title": "Loops — while & for",
            "explanation": """\
`while` loops repeat while a condition is true:

    i = 0
    while i < 5
        print i
        i = i + 1

`for` loops iterate over ranges or lists:

    for i in range 1 6
        print i

    for fruit in ["apple", "banana"]
        print fruit""",
            "examples": [
                ('total = 0\nfor i in range 1 6\n    total = total + i\nprint total', None),
            ],
            "exercises": [
                {
                    "prompt": "Use a for loop to compute the sum of numbers 1 through 10.\nPrint the result. (Hint: range 1 11 gives 1..10)",
                    "hint": "total = 0\nfor i in range 1 11\n    total = total + i\nprint total",
                    "check": lambda out, err: "55" in out and err is None,
                },
            ],
        },
        {
            "title": "Functions",
            "explanation": """\
Define functions with `function` (or `fn`). No parentheses needed:

    function greet name
        print f"Hello {name}!"

    greet "Alice"

Functions can return values:

    function square x
        return x * x

    print square 5""",
            "examples": [
                ('function double x\n    return x * 2\n\nprint double 7', None),
            ],
            "exercises": [
                {
                    "prompt": "Write a function `add` that takes two parameters and returns their sum.\nPrint the result of calling `add 15 27`.",
                    "hint": "function add a b\n    return a + b\n\nprint add 15 27",
                    "check": lambda out, err: "42" in out and err is None,
                },
            ],
        },
        {
            "title": "Lambda & Pipes",
            "explanation": """\
Lambdas are inline functions:

    double = lambda x -> x * 2
    print double 5

The pipe operator `|>` chains transformations:

    "hello" |> upper |> reverse

This passes "hello" to `upper`, then the result to `reverse`.""",
            "examples": [
                                ('x = "sauravcode" |> upper |> reverse\nprint x', None),
                ('triple = lambda x -> x * 3\nprint triple 4', None),
            ],
            "exercises": [
                {
                    "prompt": 'Create a lambda `square` that returns x * x.\nPrint square 9.',
                    "hint": "square = lambda x -> x * x\nprint square 9",
                    "check": lambda out, err: "81" in out and err is None,
                },
            ],
        },
        {
            "title": "Maps (Dictionaries)",
            "explanation": """\
Maps store key-value pairs with `{}` syntax:

    person = {"name": "Alice", "age": 30}
    print person["name"]

Modify values with bracket assignment:

    person["age"] = 31""",
            "examples": [
                ('scores = {"math": 95, "english": 87}\nprint scores["math"]', None),
            ],
            "exercises": [
                {
                    "prompt": 'Create a map `pet` with keys "name" and "species".\nPrint the "name" value.',
                    "hint": 'pet = {"name": "Rex", "species": "dog"}\nprint pet["name"]',
                    "check": lambda out, err: err is None and len(out.strip()) > 0,
                },
            ],
        },
        {
            "title": "Pattern Matching",
            "explanation": """\
`match` expressions test a value against patterns:

    x = 2
    match x
        case 1
            print "one"
        case 2
            print "two"
        case _
            print "other"

The `_` wildcard matches anything.""",
            "examples": [
                ('day = "Mon"\nmatch day\n    case "Mon"\n        print "Start of week"\n    case "Fri"\n        print "Almost weekend"\n    case _\n        print "Regular day"', None),
            ],
            "exercises": [
                {
                    "prompt": 'Create a variable `color` set to "green".\nUse match to print "go" for green, "stop" for red, "caution" for yellow, "unknown" for anything else.',
                    "hint": 'color = "green"\nmatch color\n    case "green"\n        print "go"\n    case "red"\n        print "stop"\n    case "yellow"\n        print "caution"\n    case _\n        print "unknown"',
                    "check": lambda out, err: out.strip() == "go" and err is None,
                },
            ],
        },
        {
            "title": "Error Handling",
            "explanation": """\
Use `try`/`catch` to handle errors gracefully:

    try
        x = 1 / 0
    catch e
        print f"Error: {e}"

Throw custom errors with `throw`:

    throw "Something went wrong\"""",
            "examples": [
                ('try\n    throw "oops"\ncatch e\n    print f"Caught: {e}"', None),
            ],
            "exercises": [
                {
                    "prompt": 'Write a try/catch that catches a division by zero.\nPrint "caught" in the catch block.',
                    "hint": 'try\n    x = 1 / 0\ncatch e\n    print "caught"',
                    "check": lambda out, err: "caught" in out.lower(),
                },
            ],
        },
        {
            "title": "Enums",
            "explanation": """\
Enums define named constant groups:

    enum Color
        RED
        GREEN
        BLUE

    print Color.RED

Access values with dot notation. Values are numbered from 0.""",
            "examples": [
                ('enum Direction\n    NORTH\n    SOUTH\n    EAST\n    WEST\n\nprint Direction.NORTH', None),
            ],
            "exercises": [
                {
                    "prompt": 'Create an enum `Season` with SPRING, SUMMER, FALL, WINTER.\nPrint Season.SUMMER.',
                    "hint": 'enum Season\n    SPRING\n    SUMMER\n    FALL\n    WINTER\n\nprint Season.SUMMER',
                    "check": lambda out, err: out.strip() != "" and err is None,
                },
            ],
        },
    ]

# ---------------------------------------------------------------------------
# Progress persistence
# ---------------------------------------------------------------------------
PROGRESS_FILE = os.path.expanduser("~/.sauravlearn_progress.json")

def _load_progress():
    try:
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"completed": []}

def _save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)

# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------
def _hr():
    print(_dim("─" * 60))

def _show_example(code, idx):
    print(_dim(f"  Example {idx}:"))
    for line in code.split("\n"):
        print(f"    {_cyan('»')} {line}")
    out, err = run_code(code)
    if out.strip():
        for line in out.strip().split("\n"):
            print(f"    {_green('→')} {line}")
    if err:
        print(f"    {_red('✗')} {err}")
    print()

# ---------------------------------------------------------------------------
# Interactive lesson runner
# ---------------------------------------------------------------------------
def _run_lesson(lesson_idx, lessons, progress):
    lesson = lessons[lesson_idx]
    print()
    _hr()
    print(_bold(f"  Lesson {lesson_idx + 1}/{len(lessons)}: {lesson['title']}"))
    _hr()
    print()

    # Explanation
    for line in lesson["explanation"].split("\n"):
        print(f"  {line}")
    print()

    # Examples
    if lesson["examples"]:
        print(_bold("  📝 Examples:"))
        print()
        for i, (code, _) in enumerate(lesson["examples"], 1):
            _show_example(code, i)

    # Exercises
    for ex_idx, exercise in enumerate(lesson["exercises"]):
        print(_bold(f"  🏋️ Exercise {ex_idx + 1}:"))
        print()
        for line in exercise["prompt"].split("\n"):
            print(f"    {line}")
        print()
        print(_dim("    Type your code (blank line to submit, 'hint' for help, 'skip' to skip):"))
        print()

        while True:
            lines = []
            try:
                while True:
                    prompt = f"    {_cyan('>')} " if _use_color else "    > "
                    line = input(prompt)
                    if line.strip() == "":
                        break
                    if line.strip().lower() == "hint":
                        print(f"\n    {_yellow('💡 Hint:')} {exercise['hint']}\n")
                        continue
                    if line.strip().lower() == "skip":
                        print(f"    {_yellow('⏭  Skipped')}")
                        print()
                        break
                    lines.append(line)
                else:
                    # Submitted code
                    if not lines:
                        continue
                    code = "\n".join(lines)
                    out, err = run_code(code)

                    if exercise["check"](out, err):
                        print(f"\n    {_green('✓ Correct!')}")
                        if out.strip():
                            for ol in out.strip().split("\n"):
                                print(f"    {_green('→')} {ol}")
                        print()
                        break
                    else:
                        print(f"\n    {_red('✗ Not quite.')} Try again or type 'hint'.")
                        if err:
                            print(f"    {_red('Error:')} {err}")
                        if out.strip():
                            print(f"    {_dim('Output:')} {out.strip()}")
                        print()
                        continue

                # skip was called
                break

            except (EOFError, KeyboardInterrupt):
                print(f"\n    {_yellow('Exiting lesson.')}")
                return False

    # Mark completed
    if lesson_idx not in progress["completed"]:
        progress["completed"].append(lesson_idx)
        _save_progress(progress)

    pct = int(len(progress["completed"]) / len(lessons) * 100)
    print(_green(f"  ✓ Lesson {lesson_idx + 1} complete! Progress: {pct}%"))
    print()
    return True

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    global _use_color

    parser = argparse.ArgumentParser(
        description="sauravlearn — Interactive tutorial for sauravcode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--list", action="store_true", help="List all lessons")
    parser.add_argument("--lesson", type=int, metavar="N", help="Jump to lesson N")
    parser.add_argument("--reset", action="store_true", help="Reset progress")
    parser.add_argument("--progress", action="store_true", help="Show progress summary")
    parser.add_argument("--no-color", action="store_true", help="Disable colors")
    args = parser.parse_args()

    if args.no_color or not sys.stdout.isatty():
        _use_color = False

    lessons = _lessons()
    progress = _load_progress()

    if args.reset:
        _save_progress({"completed": []})
        print(_green("Progress reset."))
        return

    if args.list:
        print()
        print(_bold("  sauravlearn — Lessons"))
        _hr()
        for i, lesson in enumerate(lessons):
            mark = _green("✓") if i in progress.get("completed", []) else _dim("○")
            print(f"  {mark} {i + 1:2d}. {lesson['title']}")
        print()
        pct = int(len(progress.get("completed", [])) / len(lessons) * 100)
        print(f"  Progress: {pct}% ({len(progress.get('completed', []))}/{len(lessons)})")
        print()
        return

    if args.progress:
        done = len(progress.get("completed", []))
        total = len(lessons)
        pct = int(done / total * 100)
        bar_w = 30
        filled = int(bar_w * done / total)
        bar = _green("█" * filled) + _dim("░" * (bar_w - filled))
        print()
        print(f"  {bar} {pct}%  ({done}/{total} lessons)")
        if done < total:
            # Find first incomplete
            for i in range(total):
                if i not in progress.get("completed", []):
                    print(f"  Next: Lesson {i + 1} — {lessons[i]['title']}")
                    break
        else:
            print(_green("  🎉 All lessons complete! You've mastered sauravcode!"))
        print()
        return

    # Determine starting lesson
    if args.lesson is not None:
        start = args.lesson - 1
        if start < 0 or start >= len(lessons):
            print(_red(f"Lesson {args.lesson} doesn't exist. Use --list to see available lessons."))
            return
    else:
        # First incomplete lesson
        start = 0
        for i in range(len(lessons)):
            if i not in progress.get("completed", []):
                start = i
                break
        else:
            start = 0  # All done, restart from beginning

    # Welcome
    print()
    print(_bold("  🎓 sauravlearn — Interactive sauravcode Tutorial"))
    print(_dim(f"  Starting from Lesson {start + 1}. Press Ctrl+C to quit anytime."))
    print()

    # Run lessons sequentially
    for i in range(start, len(lessons)):
        ok = _run_lesson(i, lessons, progress)
        if not ok:
            break

        if i < len(lessons) - 1:
            try:
                ans = input(_dim("  Press Enter for next lesson (q to quit): "))
                if ans.strip().lower() == "q":
                    break
            except (EOFError, KeyboardInterrupt):
                print()
                break
    else:
        # Completed all lessons
        print()
        print(_green(_bold("  🎉 Congratulations! You've completed all lessons!")))
        print(_dim("  Run `python sauravlearn.py --progress` to see your stats."))
        print()


if __name__ == "__main__":
    main()
