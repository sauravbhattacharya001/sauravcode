#!/usr/bin/env python3
"""sauravcheat -- Terminal cheat sheet for the sauravcode language.

Quickly look up syntax, built-ins, and idioms without leaving the terminal.

Usage:
    python sauravcheat.py                 # show full cheat sheet
    python sauravcheat.py variables       # show section on variables
    python sauravcheat.py functions       # show section on functions
    python sauravcheat.py --list          # list available sections
    python sauravcheat.py --no-color      # disable colored output
    python sauravcheat.py --compact       # shorter one-liner style
"""

import sys
import os

# ── Color helpers ─────────────────────────────────────────────────

_NO_COLOR = os.environ.get("NO_COLOR") is not None or "--no-color" in sys.argv

def _c(code, text):
    if _NO_COLOR:
        return text
    return "\033[{}m{}\033[0m".format(code, text)

def _h(t):    return _c("1;36", t)   # heading: bold cyan
def _k(t):    return _c("33", t)     # keyword: yellow
def _s(t):    return _c("32", t)     # string/value: green
def _d(t):    return _c("2", t)      # dim
def _b(t):    return _c("1", t)      # bold

# ── Cheat sheet content ──────────────────────────────────────────

SECTIONS = [
    ("variables", "Variables & Types", [
        ("Assign a variable",        'x = 42'),
        ("String",                   'name = "Alice"'),
        ("Boolean",                  'flag = true'),
        ("List",                     'nums = [1 2 3]'),
        ("Map",                      'person = {"name": "Alice" "age": 30}'),
        ("Nil",                      'empty = nil'),
        ("Type check",               'print type 42        # => int'),
    ]),
    ("print", "Printing", [
        ("Basic print",              'print "hello"'),
        ("F-string",                 'print f"Hi {name}, age {age}"'),
        ("Multiple values",          'print x'),
    ]),
    ("math", "Math & Operators", [
        ("Arithmetic",               'x = 10 + 3 * 2 - 1   # => 15'),
        ("Integer division",         'x = 7 / 2             # => 3'),
        ("Float division",           'x = 7.0 / 2           # => 3.5'),
        ("Modulo",                   'x = 10 % 3            # => 1'),
        ("Power",                    'x = 2 ** 10           # => 1024'),
        ("Comparison",               'x == y   x != y   x > y   x <= y'),
        ("Logical",                  'x and y   x or y   not x'),
    ]),
    ("control", "Control Flow", [
        ("If / else if / else",
         'if x > 0\n    print "positive"\nelse if x == 0\n    print "zero"\nelse\n    print "negative"\nend'),
        ("While loop",
         'while x > 0\n    print x\n    x = x - 1\nend'),
        ("For range",
         'for i in range 1 5\n    print i\nend'),
        ("For-each",
         'for item in items\n    print item\nend'),
        ("Break / Continue",
         'for i in range 1 100\n    if i == 5\n        break\n    end\nend'),
    ]),
    ("functions", "Functions", [
        ("Define",
         'fn greet name\n    print f"Hello {name}"\nend'),
        ("Call (no parens!)",
         'greet "world"'),
        ("Return value",
         'fn add a b\n    return a + b\nend\nresult = add 3 4'),
        ("Lambda",
         'double = lambda x -> x * 2\nprint double 5   # => 10'),
        ("Recursion",
         'fn fib n\n    if n <= 1\n        return n\n    end\n    return (fib n - 1) + (fib n - 2)\nend'),
    ]),
    ("strings", "String Operations", [
        ("Length",                    'len "hello"           # => 5'),
        ("Upper / lower",            'upper "hi"   lower "HI"'),
        ("Contains",                 'contains "hello" "ell" # => true'),
        ("Replace",                  'replace "hi world" "hi" "hello"'),
        ("Split / join",             'split "a,b,c" ","     # => ["a" "b" "c"]'),
        ("Trim",                     'trim "  hi  "         # => "hi"'),
        ("Substring",                'substr "hello" 1 3    # => "ell"'),
        ("Starts/ends with",         'startswith "hello" "he"'),
    ]),
    ("lists", "Lists", [
        ("Create",                   'xs = [1 2 3]'),
        ("Access",                   'xs[0]                 # => 1'),
        ("Append",                   'append xs 4'),
        ("Pop",                      'pop xs'),
        ("Length",                    'len xs'),
        ("Slice",                    'xs[1:3]'),
        ("Comprehension",            '[x * 2 for x in range 1 5]'),
        ("Sort / reverse",           'sort xs   reverse xs'),
        ("Map / filter",             'map xs double   filter xs is_even'),
    ]),
    ("maps", "Maps (Dictionaries)", [
        ("Create",                   'data = {"key": "value" "n": 42}'),
        ("Access",                   'data["key"]'),
        ("Set",                      'data["new"] = true'),
        ("Keys / values",            'keys data   values data'),
        ("Has key",                  'has data "key"        # => true'),
        ("Delete",                   'delete data "key"'),
    ]),
    ("match", "Pattern Matching", [
        ("Match expression",
         'match x\n    1 -> print "one"\n    2 -> print "two"\n    _ -> print "other"\nend'),
    ]),
    ("errors", "Error Handling", [
        ("Try / catch",
         'try\n    x = 1 / 0\ncatch e\n    print f"Error: {e}"\nend'),
        ("Throw",                    'throw "something went wrong"'),
    ]),
    ("classes", "Classes", [
        ("Define",
         'class Dog\n    fn init self name\n        self.name = name\n    end\n    fn bark self\n        print f"{self.name} says woof!"\n    end\nend'),
        ("Instantiate",              'rex = Dog "Rex"\nrex.bark'),
    ]),
    ("generators", "Generators", [
        ("Define",
         'fn counter start stop\n    i = start\n    while i <= stop\n        yield i\n        i = i + 1\n    end\nend'),
        ("Iterate",
         'for n in counter 1 5\n    print n\nend'),
    ]),
    ("pipes", "Pipe Operator", [
        ("Chain functions",          '"hello" |> upper |> reverse   # => OLLEH'),
    ]),
    ("enums", "Enums", [
        ("Define",
         'enum Color\n    RED\n    GREEN\n    BLUE\nend'),
        ("Use",                      'c = Color.RED'),
    ]),
    ("imports", "Imports", [
        ("Import a module",          'import "utils.srv"'),
    ]),
    ("io", "File I/O", [
        ("Read file",                'content = read_file "data.txt"'),
        ("Write file",               'write_file "out.txt" "hello"'),
        ("Append",                   'append_file "log.txt" "entry"'),
    ]),
    ("tooling", "Tooling Commands", [
        ("Run a program",            'sauravcode hello.srv'),
        ("Compile to native",        'sauravcode-compile hello.srv'),
        ("Interactive REPL",         'sauravcode'),
        ("Format code",              'python sauravfmt.py code.srv'),
        ("Lint",                     'python sauravlint.py code.srv'),
        ("Run tests",                'python sauravtest.py tests/'),
        ("Playground",               'python sauravplay.py'),
        ("Cheat sheet (this!)",      'python sauravcheat.py'),
    ]),
]


def _format_code_block(code):
    """Format a code example with indentation and syntax hints."""
    lines = code.split("\n")
    result = []
    for line in lines:
        # Highlight keywords
        highlighted = line
        for kw in ["fn ", "if ", "else if ", "else", "end", "for ", "while ",
                    "return ", "match ", "try", "catch ", "throw ", "class ",
                    "import ", "enum ", "yield ", "break", "continue",
                    "in ", "not ", "and ", "or ", "lambda "]:
            if highlighted.lstrip().startswith(kw) or highlighted.strip() == kw.strip():
                idx = highlighted.find(kw.rstrip())
                if idx >= 0:
                    highlighted = (highlighted[:idx] +
                                   _k(kw.rstrip()) +
                                   highlighted[idx + len(kw.rstrip()):])
                    break
        result.append("      " + highlighted)
    return "\n".join(result)


def _print_section(key, title, entries, compact=False):
    """Print one cheat sheet section."""
    print()
    print("  " + _h("-- " + title + " --"))
    print()
    for label, code in entries:
        if compact:
            # One-liner style
            print("    " + _b(label + ":") + "  " + _s(code.split("\n")[0]))
        else:
            print("    " + _d("# " + label))
            print(_format_code_block(code))
            print()


def _print_header():
    print()
    print("  " + _h("+==========================================+"))
    print("  " + _h("|") + _b("    sauravcode -- Language Cheat Sheet    ") + _h("|"))
    print("  " + _h("|") + _d("    No parens. No commas. No noise.      ") + _h("|"))
    print("  " + _h("+==========================================+"))


def _print_footer():
    print()
    print("  " + _d("Docs: https://sauravbhattacharya001.github.io/sauravcode/"))
    print("  " + _d("Source: https://github.com/sauravbhattacharya001/sauravcode"))
    print()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    compact = "--compact" in sys.argv

    if "--list" in sys.argv:
        print()
        print("  " + _h("Available sections:"))
        for key, title, _ in SECTIONS:
            print("    " + _b(key.ljust(14)) + _d(title))
        print()
        print("  " + _d("Usage: python sauravcheat.py <section>"))
        print()
        return

    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        return

    if args:
        # Show specific section(s)
        found = False
        for query in args:
            for key, title, entries in SECTIONS:
                if key.startswith(query.lower()):
                    _print_section(key, title, entries, compact)
                    found = True
                    break
        if not found:
            print(_c("31", "  Unknown section: " + " ".join(args)))
            print(_d("  Run with --list to see available sections"))
        return

    # Full cheat sheet
    _print_header()
    for key, title, entries in SECTIONS:
        _print_section(key, title, entries, compact)
    _print_footer()


if __name__ == "__main__":
    main()
