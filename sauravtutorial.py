#!/usr/bin/env python3
"""sauravtutorial — Interactive step-by-step tutorial for sauravcode.

An in-terminal guided tutorial that teaches sauravcode concepts one
lesson at a time. Each lesson explains a concept, shows examples, then
gives the user an exercise to solve in a live mini-REPL. The tutorial
tracks progress so users can resume where they left off.

Usage:
    python sauravtutorial.py              # Start / resume tutorial
    python sauravtutorial.py --list       # List all lessons
    python sauravtutorial.py --lesson 5   # Jump to lesson 5
    python sauravtutorial.py --reset      # Reset progress
    python sauravtutorial.py --no-color   # Disable ANSI colors

Lessons cover:
    1.  Hello World & print
    2.  Variables & types
    3.  Arithmetic & expressions
    4.  Strings & f-strings
    5.  If/else conditionals
    6.  While loops
    7.  For loops & ranges
    8.  Lists & indexing
    9.  Maps (dictionaries)
    10. Functions
    11. Pattern matching (match/case)
    12. Try/catch error handling
    13. Higher-order functions (map, filter, reduce)
    14. Pipe operator (|>)
    15. Lambdas
    16. Imports & modules
    17. Putting it all together
"""

import sys
import os
import json
import io
import re
import textwrap

# Add script dir so we can import the interpreter
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

from saurav import Interpreter, Parser, tokenize

# ── Colors ──────────────────────────────────────────────────────────────

_use_color = True

def _c(code, text):
    if not _use_color:
        return text
    return f"\033[{code}m{text}\033[0m"

def _title(t):   return _c("1;36", t)   # bold cyan
def _code(t):    return _c("33", t)      # yellow
def _ok(t):      return _c("1;32", t)    # bold green
def _err(t):     return _c("1;31", t)    # bold red
def _dim(t):     return _c("2", t)       # dim
def _bold(t):    return _c("1", t)       # bold
def _hint(t):    return _c("35", t)      # magenta

# ── Progress file ───────────────────────────────────────────────────────

_PROGRESS_FILE = os.path.join(
    os.environ.get("XDG_DATA_HOME", os.path.expanduser("~")),
    ".sauravtutorial_progress.json"
)

def _load_progress():
    try:
        with open(_PROGRESS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"completed": [], "current": 0}

def _save_progress(prog):
    os.makedirs(os.path.dirname(_PROGRESS_FILE) or ".", exist_ok=True)
    with open(_PROGRESS_FILE, "w") as f:
        json.dump(prog, f, indent=2)

# ── Mini-REPL runner ───────────────────────────────────────────────────

def _run_code(code):
    """Run sauravcode and return (output_str, error_str)."""
    interp = Interpreter()
    old_stdout = sys.stdout
    sys.stdout = buf = io.StringIO()
    err = None
    try:
        tokens = tokenize(code)
        parser = Parser(tokens)
        tree = parser.parse()
        interp.execute_body(tree)
    except Exception as e:
        err = str(e)
    finally:
        sys.stdout = old_stdout
    return buf.getvalue(), err

# ── Lessons ─────────────────────────────────────────────────────────────

LESSONS = []

def _lesson(title, explanation, examples, exercise_prompt, validator):
    """Register a lesson."""
    LESSONS.append({
        "title": title,
        "explanation": explanation,
        "examples": examples,
        "exercise_prompt": exercise_prompt,
        "validator": validator,
    })

# Helper validators
def _output_contains(expected):
    """Validator: output must contain expected string."""
    def check(code, output, error):
        if error:
            return False, f"Your code had an error: {error}"
        if expected in output:
            return True, ""
        return False, f"Expected output to contain '{expected}', got: {output.strip()!r}"
    return check

def _code_and_output(code_check, output_check):
    """Validator: checks both code content and output."""
    def check(code, output, error):
        if error:
            return False, f"Your code had an error: {error}"
        if code_check and not code_check(code):
            return False, "Your code doesn't use the required construct."
        if output_check and not output_check(output):
            return False, f"Output wasn't quite right. Got: {output.strip()!r}"
        return True, ""
    return check

# ── Lesson 1: Hello World ──────────────────────────────────────────────

_lesson(
    "Hello World & print",
    """\
Every programming journey starts with "Hello, World!"

In sauravcode, you print to the screen with the `print` keyword:

    print "Hello, World!"

That's it — no imports, no boilerplate, no parentheses needed.
Just write and run!

You can print numbers too:

    print 42
    print 3.14
""",
    [('print "Hello, World!"', "Hello, World!\n")],
    'Write code that prints: Hello, sauravcode!',
    _output_contains("Hello, sauravcode!"),
)

# ── Lesson 2: Variables & types ─────────────────────────────────────────

_lesson(
    "Variables & types",
    """\
Variables store values. Just use `=` to assign:

    name = "Alice"
    age = 30
    pi = 3.14
    is_cool = true

sauravcode has these types:
  - Strings:  "hello"
  - Integers: 42
  - Floats:   3.14
  - Booleans: true, false
  - null

Print variables like this:

    x = 10
    print x
""",
    [('name = "Alice"\nprint name', "Alice\n")],
    'Create a variable called `greeting` set to "Hi there" and print it.',
    _code_and_output(
        lambda c: "greeting" in c,
        lambda o: "Hi there" in o,
    ),
)

# ── Lesson 3: Arithmetic ───────────────────────────────────────────────

_lesson(
    "Arithmetic & expressions",
    """\
sauravcode supports standard arithmetic:

    +   addition
    -   subtraction
    *   multiplication
    /   division
    %   modulo (remainder)

Examples:

    print 2 + 3        # 5
    print 10 / 3       # 3.333...
    print 10 % 3       # 1

You can use parentheses for grouping:

    print (2 + 3) * 4  # 20
""",
    [("print 2 + 3", "5\n")],
    "Print the result of (7 + 3) * (10 - 4). (Should be 60)",
    _output_contains("60"),
)

# ── Lesson 4: Strings & f-strings ──────────────────────────────────────

_lesson(
    "Strings & f-strings",
    """\
Strings are created with double quotes:

    msg = "hello"

F-strings let you embed expressions inside strings:

    name = "World"
    print f"Hello, {name}!"

You can put any expression inside the braces:

    x = 5
    print f"x squared is {x * x}"

Useful string builtins: len(), upper(), lower()

    print len("hello")       # 5
    print upper("hello")     # HELLO
""",
    [('name = "World"\nprint f"Hello, {name}!"', "Hello, World!\n")],
    'Create a variable `lang` set to "sauravcode" and print "I am learning sauravcode" using an f-string.',
    _code_and_output(
        lambda c: 'f"' in c or "f'" in c,
        lambda o: "I am learning sauravcode" in o,
    ),
)

# ── Lesson 5: If/else ──────────────────────────────────────────────────

_lesson(
    "If/else conditionals",
    """\
Conditionals use `if` and `else` with indentation (no braces!):

    x = 15
    if x > 10
        print "big"
    else
        print "small"

Comparison operators: ==, !=, <, >, <=, >=
Logical operators: and, or, not

Note: elif is not supported — nest if/else instead.
""",
    [('x = 15\nif x > 10\n    print "big"\nelse\n    print "small"', "big\n")],
    'Set a variable `score` to 85. Print "pass" if score >= 60, otherwise "fail".',
    _code_and_output(
        lambda c: "if" in c and "score" in c,
        lambda o: "pass" in o,
    ),
)

# ── Lesson 6: While loops ──────────────────────────────────────────────

_lesson(
    "While loops",
    """\
`while` loops repeat as long as a condition is true:

    i = 0
    while i < 5
        print i
        i = i + 1

This prints 0, 1, 2, 3, 4 — each on its own line.

Use `break` to exit early and `continue` to skip an iteration.
""",
    [("i = 0\nwhile i < 3\n    print i\n    i = i + 1", "0\n1\n2\n")],
    "Use a while loop to print the numbers 1 through 5 (one per line).",
    _code_and_output(
        lambda c: "while" in c,
        lambda o: all(str(n) in o for n in range(1, 6)),
    ),
)

# ── Lesson 7: For loops & ranges ───────────────────────────────────────

_lesson(
    "For loops & ranges",
    """\
`for` loops iterate over a range of numbers:

    for i 1 5
        print i

This prints 1 through 4 (the end value is exclusive).

For-each loops iterate over collections:

    colors = ["red", "green", "blue"]
    for c in colors
        print c
""",
    [("for i 1 4\n    print i", "1\n2\n3\n")],
    "Use a for loop to print the numbers 1 through 5.",
    _code_and_output(
        lambda c: "for" in c,
        lambda o: all(str(n) in o for n in range(1, 6)),
    ),
)

# ── Lesson 8: Lists ────────────────────────────────────────────────────

_lesson(
    "Lists & indexing",
    """\
Lists hold ordered collections of values:

    fruits = ["apple", "banana", "cherry"]
    print fruits[0]      # apple
    print len(fruits)    # 3

Add items with `append`:

    append fruits "date"
    print fruits

Lists can hold mixed types:

    mixed = [1, "hello", true, 3.14]
""",
    [('fruits = ["apple", "banana"]\nprint fruits[0]', "apple\n")],
    'Create a list of 3 animals and print the second one (index 1).',
    _code_and_output(
        lambda c: "[" in c,
        lambda o: len(o.strip()) > 0,
    ),
)

# ── Lesson 9: Maps ─────────────────────────────────────────────────────

_lesson(
    "Maps (dictionaries)",
    """\
Maps store key-value pairs:

    person = {"name": "Alice", "age": 30}
    print person["name"]     # Alice

Add or update entries:

    person["city"] = "Seattle"

Get all keys:

    print keys(person)
""",
    [('m = {"x": 1, "y": 2}\nprint m["x"]', "1\n")],
    'Create a map with keys "lang" and "version". Print the "lang" value.',
    _code_and_output(
        lambda c: "{" in c and "lang" in c,
        lambda o: len(o.strip()) > 0,
    ),
)

# ── Lesson 10: Functions ───────────────────────────────────────────────

_lesson(
    "Functions",
    """\
Define functions with the `function` keyword:

    function greet name
        print f"Hello, {name}!"

    greet "World"

Functions can return values:

    function add a b
        return a + b

    print add 3 4    # 7

Functions are first-class — you can pass them around.
""",
    [("function double x\n    return x * 2\n\nprint double 5", "10\n")],
    "Write a function `square` that takes `n` and returns n * n. Print square 7.",
    _code_and_output(
        lambda c: "function" in c and "square" in c,
        lambda o: "49" in o,
    ),
)

# ── Lesson 11: Match/case ──────────────────────────────────────────────

_lesson(
    "Pattern matching (match/case)",
    """\
`match` provides powerful pattern matching:

    x = "hello"
    match x
        case "hello"
            print "greeting!"
        case "bye"
            print "farewell!"
        case _
            print "unknown"

The `_` is a wildcard that matches anything (like a default).
""",
    [('x = "hi"\nmatch x\n    case "hi"\n        print "found it"\n    case _\n        print "nope"', "found it\n")],
    'Use match on a variable set to "cat" to print "meow" for "cat" and "???" for anything else.',
    _code_and_output(
        lambda c: "match" in c,
        lambda o: "meow" in o,
    ),
)

# ── Lesson 12: Try/catch ───────────────────────────────────────────────

_lesson(
    "Try/catch error handling",
    """\
Handle runtime errors with try/catch:

    try
        x = 10 / 0
    catch e
        print f"Error: {e}"

Throw your own errors:

    function check_age age
        if age < 0
            throw "Age cannot be negative"
        print f"Age is {age}"
""",
    [('try\n    throw "oops"\ncatch e\n    print "caught it"', "caught it\n")],
    'Write a try/catch that catches a thrown error and prints "safe".',
    _code_and_output(
        lambda c: "try" in c and "catch" in c,
        lambda o: "safe" in o,
    ),
)

# ── Lesson 13: Higher-order functions ───────────────────────────────────

_lesson(
    "Higher-order functions (map, filter, reduce)",
    """\
sauravcode has built-in higher-order functions:

    function double x
        return x * 2

    nums = [1, 2, 3, 4, 5]
    result = map (double) nums
    print result       # [2, 4, 6, 8, 10]

Filter keeps elements matching a condition:

    function is_even x
        return x % 2 == 0

    evens = filter (is_even) nums
    print evens        # [2, 4]

Reduce folds a list into a single value:

    function add a b
        return a + b

    total = reduce (add) (nums) 0
    print total        # 15

Note: wrap function names in parens to avoid greedy parsing.
""",
    [("function double x\n    return x * 2\n\nprint map (double) [1, 2, 3]", "[2, 4, 6]\n")],
    "Write a function `triple` that multiplies by 3. Use `map` to apply it to [1, 2, 3, 4] and print the result.",
    _code_and_output(
        lambda c: "function" in c and "map" in c,
        lambda o: "3" in o and "12" in o,
    ),
)

# ── Lesson 14: Pipe operator ───────────────────────────────────────────

_lesson(
    "Pipe operator (|>)",
    """\
The pipe operator passes a value to the next function.
It works inside expressions and assignments:

    result = "hello" |> upper
    print result                    # HELLO

Chain operations left-to-right for cleaner code:

    function double x
        return x * 2

    function add_one x
        return x + 1

    result = 5 |> double |> add_one
    print result                    # 11
""",
    [('result = "hello" |> upper\nprint result', "HELLO\n")],
    'Use the pipe operator to take "sauravcode", uppercase it, store it in a variable, and print it.',
    _code_and_output(
        lambda c: "|>" in c,
        lambda o: "SAURAVCODE" in o,
    ),
)

# ── Lesson 15: Lambdas ─────────────────────────────────────────────────

_lesson(
    "Lambdas",
    """\
Lambdas are anonymous inline functions:

    square = lambda x -> x * x
    print square(5)      # 25

They work great with map and filter:

    doubled = map (lambda x -> x * 2) [1, 2, 3]
    print doubled        # [2, 4, 6]
""",
    [("square = lambda x -> x * x\nprint square(5)", "25\n")],
    "Create a lambda `cube` that computes x * x * x. Print cube(3).",
    _code_and_output(
        lambda c: "lambda" in c,
        lambda o: "27" in o,
    ),
)

# ── Lesson 16: Imports ─────────────────────────────────────────────────

_lesson(
    "Imports & modules",
    """\
Split code across files with `import`:

    # utils.srv
    function helper
        return 42

    # main.srv
    import "utils.srv"
    print helper

Import brings all top-level functions and variables into scope.

Note: In this tutorial, imports aren't runnable (single-file REPL).
Just understand the syntax!
""",
    [],
    'Just type: print "I understand imports!" — we\'ll move on.',
    _output_contains("I understand imports!"),
)

# ── Lesson 17: Putting it all together ─────────────────────────────────

_lesson(
    "Putting it all together",
    """\
Congratulations — you've learned the core of sauravcode! 🎉

Let's combine what you know. Here's a mini FizzBuzz:

    function fizzbuzz n
        for i 1 n + 1
            if i % 15 == 0
                print "FizzBuzz"
            else
                if i % 3 == 0
                    print "Fizz"
                else
                    if i % 5 == 0
                        print "Buzz"
                    else
                        print i

Now it's your turn!
""",
    [],
    'Write a function `countdown` that takes `n` and prints from n down to 1, then prints "Go!". Call it with: countdown 3',
    _code_and_output(
        lambda c: "function" in c and "countdown" in c,
        lambda o: "3" in o and "2" in o and "1" in o and "Go!" in o,
    ),
)

# ── Main tutorial flow ──────────────────────────────────────────────────

def _print_banner():
    print()
    print(_title("╔══════════════════════════════════════════════════╗"))
    print(_title("║") + _bold("   🎓 sauravcode Interactive Tutorial            ") + _title("║"))
    print(_title("║") + _dim("   Learn sauravcode step by step                 ") + _title("║"))
    print(_title("╚══════════════════════════════════════════════════╝"))
    print()

def _print_lesson(idx, lesson):
    total = len(LESSONS)
    print()
    print(_title(f"━━━ Lesson {idx + 1}/{total}: {lesson['title']} ━━━"))
    print()
    for line in lesson["explanation"].split("\n"):
        if line.startswith("    "):
            print("  " + _code(line))
        else:
            print("  " + line)
    print()

    if lesson["examples"]:
        print(_dim("  Example:"))
        for code, expected in lesson["examples"]:
            for cl in code.split("\n"):
                print("    " + _code(cl))
            print("    " + _dim(f"→ {expected.strip()}"))
        print()

def _exercise_repl(lesson):
    """Run the exercise mini-REPL. Returns True on success."""
    print(_bold("  📝 Exercise: ") + lesson["exercise_prompt"])
    print(_dim("  Type your code (empty line to run, 'skip' to skip, 'hint' for help):"))
    print()

    while True:
        lines = []
        try:
            while True:
                prompt = _c("36", "  >>> ") if not lines else _c("36", "  ... ")
                line = input(prompt)
                if line.strip() == "":
                    break
                if line.strip().lower() == "skip":
                    print(_dim("  Skipped."))
                    return False
                if line.strip().lower() == "hint":
                    print(_hint("  💡 Re-read the examples above and try something similar!"))
                    continue
                if line.strip().lower() in ("quit", "exit"):
                    print(_dim("  Leaving tutorial."))
                    sys.exit(0)
                lines.append(line)
        except (EOFError, KeyboardInterrupt):
            print()
            print(_dim("  Leaving tutorial."))
            sys.exit(0)

        if not lines:
            print(_dim("  (empty — type some code!)"))
            continue

        code = "\n".join(lines)
        output, error = _run_code(code)

        if output:
            for ol in output.rstrip("\n").split("\n"):
                print("  " + _dim(ol))

        passed, msg = lesson["validator"](code, output, error)
        if passed:
            print()
            print(_ok("  ✅ Correct! Well done!"))
            return True
        else:
            print(_err(f"  ❌ {msg}"))
            print(_dim("  Try again! (or type 'skip')"))
            print()

def _list_lessons():
    print()
    print(_title("  sauravcode Tutorial — All Lessons"))
    print()
    for i, l in enumerate(LESSONS):
        print(f"  {_bold(str(i + 1).rjust(3))}. {l['title']}")
    print()
    print(f"  {_dim(f'{len(LESSONS)} lessons total')}")
    print()

def main():
    global _use_color

    args = sys.argv[1:]

    if "--no-color" in args:
        _use_color = False
        args.remove("--no-color")

    if "--list" in args:
        _list_lessons()
        return

    if "--reset" in args:
        _save_progress({"completed": [], "current": 0})
        print(_ok("Progress reset!"))
        return

    start_lesson = None
    if "--lesson" in args:
        idx = args.index("--lesson")
        if idx + 1 < len(args):
            try:
                start_lesson = int(args[idx + 1]) - 1
            except ValueError:
                print(_err("--lesson requires a number"))
                return
        else:
            print(_err("--lesson requires a number"))
            return

    progress = _load_progress()

    if start_lesson is not None:
        if start_lesson < 0 or start_lesson >= len(LESSONS):
            print(_err(f"Lesson must be 1-{len(LESSONS)}"))
            return
        current = start_lesson
    else:
        current = progress.get("current", 0)
        if current >= len(LESSONS):
            print(_ok("🎓 You've completed all lessons! Use --reset to start over or --lesson N to revisit."))
            return

    _print_banner()

    if current > 0 and start_lesson is None:
        print(_dim(f"  Resuming from lesson {current + 1}..."))

    while current < len(LESSONS):
        lesson = LESSONS[current]
        _print_lesson(current, lesson)
        passed = _exercise_repl(lesson)

        if passed:
            if current not in progress.get("completed", []):
                progress.setdefault("completed", []).append(current)
            progress["current"] = current + 1
            _save_progress(progress)

        current += 1

        if current < len(LESSONS):
            print()
            try:
                answer = input(_dim("  Press Enter for next lesson (or 'quit' to exit): "))
                if answer.strip().lower() in ("quit", "exit", "q"):
                    print(_dim("  See you next time! Your progress is saved. 👋"))
                    return
            except (EOFError, KeyboardInterrupt):
                print()
                print(_dim("  See you next time! Your progress is saved. 👋"))
                return

    print()
    print(_ok("  ╔══════════════════════════════════════════════════╗"))
    print(_ok("  ║   🎓 Congratulations! Tutorial complete!        ║"))
    print(_ok("  ╚══════════════════════════════════════════════════╝"))
    print()
    print(f"  {_dim('You completed all')} {_bold(str(len(LESSONS)))} {_dim('lessons!')}")
    print(f"  {_dim('Next steps:')}")
    print(f"    • Try the playground: {_code('python sauravplay.py')}")
    print(f"    • Read the stdlib:    {_code('python sauravcheat.py')}")
    print(f"    • Start a project:    {_code('python sauravscaffold.py new myapp')}")
    print()

if __name__ == "__main__":
    main()
