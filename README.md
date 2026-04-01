<p align="center">
  <h1 align="center">sauravcode</h1>
  <p align="center">
    <strong>A programming language designed for clarity. No noise, just logic.</strong>
  </p>
  <!-- CI & Quality -->
  <p align="center">
    <a href="https://github.com/sauravbhattacharya001/sauravcode/actions/workflows/ci.yml"><img src="https://github.com/sauravbhattacharya001/sauravcode/actions/workflows/ci.yml/badge.svg" alt="Tests"></a>
    <a href="https://codecov.io/gh/sauravbhattacharya001/sauravcode"><img src="https://codecov.io/gh/sauravbhattacharya001/sauravcode/branch/main/graph/badge.svg" alt="Coverage"></a>
    <a href="https://github.com/sauravbhattacharya001/sauravcode/actions/workflows/codeql.yml"><img src="https://github.com/sauravbhattacharya001/sauravcode/actions/workflows/codeql.yml/badge.svg" alt="CodeQL"></a>
    <a href="https://github.com/sauravbhattacharya001/sauravcode/actions/workflows/pages.yml"><img src="https://github.com/sauravbhattacharya001/sauravcode/actions/workflows/pages.yml/badge.svg" alt="Pages"></a>
  </p>
  <!-- Package & Version -->
  <p align="center">
    <a href="https://pypi.org/project/sauravcode/"><img src="https://img.shields.io/pypi/v/sauravcode?color=blue" alt="PyPI"></a>
    <a href="https://pypi.org/project/sauravcode/"><img src="https://img.shields.io/pypi/dm/sauravcode" alt="Downloads"></a>
    <a href="https://pypi.org/project/sauravcode/"><img src="https://img.shields.io/pypi/pyversions/sauravcode" alt="Python"></a>
    <a href="https://github.com/sauravbhattacharya001/sauravcode/releases"><img src="https://img.shields.io/github/v/release/sauravbhattacharya001/sauravcode" alt="Release"></a>
  </p>
  <!-- Repo Info -->
  <p align="center">
    <a href="https://github.com/sauravbhattacharya001/sauravcode/blob/main/LICENSE"><img src="https://img.shields.io/github/license/sauravbhattacharya001/sauravcode" alt="License"></a>
    <a href="https://github.com/sauravbhattacharya001/sauravcode"><img src="https://img.shields.io/github/languages/top/sauravbhattacharya001/sauravcode" alt="Language"></a>
    <a href="https://github.com/sauravbhattacharya001/sauravcode"><img src="https://img.shields.io/github/repo-size/sauravbhattacharya001/sauravcode" alt="Repo Size"></a>
    <a href="https://github.com/sauravbhattacharya001/sauravcode/commits/main"><img src="https://img.shields.io/github/last-commit/sauravbhattacharya001/sauravcode" alt="Last Commit"></a>
  </p>
  <!-- Community -->
  <p align="center">
    <a href="https://github.com/sauravbhattacharya001/sauravcode/stargazers"><img src="https://img.shields.io/github/stars/sauravbhattacharya001/sauravcode?style=social" alt="Stars"></a>
    <a href="https://github.com/sauravbhattacharya001/sauravcode/issues"><img src="https://img.shields.io/github/issues/sauravbhattacharya001/sauravcode" alt="Issues"></a>
    <a href="https://github.com/sauravbhattacharya001/sauravcode/pulls"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen" alt="PRs Welcome"></a>
  </p>
</p>

---

**sauravcode** is a programming language that strips away the ceremony of traditional syntax. No parentheses for function calls. No commas between arguments. No semicolons. No braces. Just clean, readable code that flows like thought.

It comes with both an **interpreter** for rapid prototyping and a **compiler** that produces native executables via C code generation.

🌐 **[Documentation Site](https://sauravbhattacharya001.github.io/sauravcode/)** · 📖 **[Language Reference](docs/LANGUAGE.md)** · 🏗️ **[Architecture Guide](docs/ARCHITECTURE.md)**

---

## ✨ Features

- **Minimal syntax** — no parentheses, commas, semicolons, or braces
- **Dual execution** — interpreted (`saurav.py`) or compiled to native (`sauravcc.py`)
- **Interactive REPL** — experiment with sauravcode in real-time
- **Functions & recursion** — with clean call syntax
- **Lambda expressions** — `lambda x -> x * 2` for inline functions
- **Pipe operator** — `"hello" |> upper |> reverse` for chaining
- **Dynamic typing** — integers, floats, booleans, strings, lists, maps
- **Control flow** — if/else if/else, while, range-based for, for-each, break/continue
- **Pattern matching** — `match` expressions with wildcard and literal patterns
- **Generators** — functions with `yield` for lazy sequences
- **Enums** — named constant groups with dot access
- **Classes** — with fields, methods, and `self`
- **Error handling** — try/catch/throw blocks
- **Import system** — `import "module.srv"` with closure scoping
- **Lists** — dynamic arrays with append, pop, len, indexing, slicing, comprehensions
- **Maps** — key-value dictionaries with `{}` syntax, bracket access, and built-in functions
- **105 built-in functions** — strings, math, stats, regex, date/time, JSON, encoding, hashing, HTTP, I/O, bitwise
- **String interpolation** — `f"Hello {name}, you are {age} years old"` f-strings
- **Logical operators** — `and`, `or`, `not`
- **Compiler generates readable C** — inspect with `--emit-c`
- **Developer tooling** — formatter, linter, profiler, debugger, coverage, benchmarks, AST visualizer, playground, dependency graph, complexity analyzer, notebook runner, watch mode, snapshot testing
- **VS Code extension** — syntax highlighting, 25 snippets, and language configuration

## 🚀 Quick Start

### Install from PyPI

```bash
pip install sauravcode
```

After installation, two commands are available globally:
- `sauravcode` — interpreter + interactive REPL
- `sauravcode-compile` — compiler (.srv → C → native executable)

### Prerequisites

- **Python 3.8+**
- **gcc** (for compiler — MinGW on Windows, Xcode CLI on macOS)

### Interactive REPL

Start the REPL with no arguments for instant experimentation:

```bash
python saurav.py
```

```
sauravcode REPL v1.0
Type "help" for commands, "quit" to exit.

>>> x = 10
>>> print x + 5
15
>>> function double n
...     return n * 2
...
>>> print double x
20
>>> vars
  x = 10
>>> quit
Bye!
```

REPL commands: `help`, `vars`, `funcs`, `clear`, `history`, `load FILE`, `quit`

### Run a File

```bash
python saurav.py hello.srv
```

### Compile to Native Executable

```bash
python sauravcc.py hello.srv     # Compile and run
./hello                          # Run the binary directly
```

## 📝 Language at a Glance

### Hello World

```
print "Hello, World!"
```

### Functions

No parentheses, no commas — just the function name and its arguments:

```
function greet name
    print "Hello,"
    print name

greet "world"
```

### Variables & Arithmetic

```
x = 10
y = 3
print x + y      # 13
print x * y      # 30
print x % y      # 1
```

### Control Flow

```
score = 85
if score >= 90
    print "A"
else if score >= 80
    print "B"
else
    print "below B"
```

### Loops

```
# While
i = 0
while i < 5
    print i
    i = i + 1

# For (range-based)
for i 1 6
    print i        # prints 1 through 5

# Break and Continue
for i 0 10
    if i == 5
        break          # exit loop early
    if i % 2 == 0
        continue       # skip even numbers
    print i            # prints 1, 3
```

### Recursion

Use parentheses only when you need to disambiguate nested expressions:

```
function factorial n
    if n <= 1
        return 1
    return n * factorial (n - 1)

print factorial 10    # 3628800
```

### Lists

```
nums = [10, 20, 30]
print nums[0]          # 10
print len nums         # 3
append nums 40
print nums[3]          # 40
```

### Maps (Dictionaries)

```
# Create a map with { key: value } syntax
person = {"name": "Alice", "age": 30, "active": true}
print person["name"]    # Alice

# Add/update keys
person["email"] = "alice@example.com"
person["age"] = 31

# Built-in map functions
k = keys person          # list of keys
v = values person        # list of values
print has_key (person) "name"    # true
print contains (person) "email"  # true
print len person                 # 4
print type_of person             # map

# Word frequency counter
words = split "hello world hello" " "
freq = {}
for i 0 len words
    word = words[i]
    if contains (freq) word
        freq[word] = freq[word] + 1
    else
        freq[word] = 1
print freq["hello"]     # 2
```

### String Interpolation (F-Strings)

Embed expressions directly in strings with the `f"..."` syntax:

```
name = "Alice"
age = 30
print f"Hello, {name}!"           # Hello, Alice!
print f"{name} is {age} years old" # Alice is 30 years old
print f"2 + 3 = {2 + 3}"          # 2 + 3 = 5

# Works with any expression
items = [1, 2, 3]
print f"count: {len items}"       # count: 3
print f"upper: {upper name}"      # upper: ALICE

# Escaped braces: {{ and }} produce literal { and }
x = 42
print f"value: {{x}} = {x}"       # value: {x} = 42
```

### Classes

```
class Point
    function init x y
        self.x = x
        self.y = y
```

### Error Handling

```
try
    x = risky_operation
catch err
    print "something went wrong"
```

### Standard Library

Sauravcode includes **95 built-in functions** — no imports needed. See the full [Standard Library Reference](STDLIB.md).

```
# String functions
print upper "hello"              # HELLO
print lower "HELLO"              # hello
print trim "  spaces  "         # spaces
print replace "hi world" "world" "sauravcode"
words = split "a-b-c" "-"       # ["a", "b", "c"]
print join ", " words            # a, b, c
print contains "hello" "ell"    # true
print starts_with "hello" "he"  # true
print substring "hello" 0 3     # hel
print char_at "hello" 0         # h

# Math functions
print sqrt 16                    # 4
print power 2 10                 # 1024
print round 3.14159 2           # 3.14
print floor 3.7                  # 3
print ceil 3.2                   # 4
print abs (-42)                  # 42

# Statistics
print mean [1, 2, 3, 4, 5]      # 3.0
print median [1, 3, 5, 7]       # 4.0
print stdev [2, 4, 4, 4, 5]     # 0.894...

# Regex
print regex_match "^\d+$" "42"   # true
print regex_replace "\s+" "-" "a b c"  # a-b-c

# Date/Time
print now                        # 2026-03-07T15:...
d = date_add (now) 7 "days"     # one week from now

# JSON
data = json_parse "{\"x\": 1}"   # {"x": 1}
print json_pretty data           # formatted

# Hashing & Encoding
print sha256 "hello"             # 2cf24dba...
print base64_encode "hello"      # aGVsbG8=

# Map functions
m = {"a": 1, "b": 2}
k = keys m                      # ["a", "b"]
v = values m                    # [1, 2]
print has_key (m) "a"           # true
print contains (m) "c"          # false
```

Type `builtins` in the REPL to see all available functions with usage.

## ⚙️ Compiler

The compiler (`sauravcc.py`) translates sauravcode to C, then uses gcc to produce native executables.

```bash
# Compile and run
python sauravcc.py program.srv

# Emit C code only (inspect the generated code)
python sauravcc.py program.srv --emit-c

# Compile to a specific output name
python sauravcc.py program.srv -o myprogram

# Keep the intermediate .c file
python sauravcc.py program.srv --keep-c

# Verbose output
python sauravcc.py program.srv -v
```

### Compilation Pipeline

```
┌──────────┐    ┌─────────┐    ┌──────────┐    ┌──────────┐    ┌────────────┐
│ .srv     │───▶│ Tokenize │───▶│  Parse   │───▶│ Generate │───▶│   gcc      │
│ source   │    │ (lexer)  │    │  (AST)   │    │  (C code)│    │ (native)   │
└──────────┘    └─────────┘    └──────────┘    └──────────┘    └────────────┘
```

### Supported Features

| Feature | Interpreter | Compiler |
|---------|:-----------:|:--------:|
| Interactive REPL | ✅ | — |
| Functions & recursion | ✅ | ✅ |
| Variables & assignment | ✅ | ✅ |
| Arithmetic (+, -, *, /, %) | ✅ | ✅ |
| Comparisons (==, !=, <, >, <=, >=) | ✅ | ✅ |
| Booleans & logical ops | ✅ | ✅ |
| If / else if / else | ✅ | ✅ |
| While loops | ✅ | ✅ |
| For loops (range-based) | ✅ | ✅ |
| Break & continue | ✅ | ✅ |
| Strings | ✅ | ✅ |
| Lists (dynamic arrays) | ✅ | ✅ |
| Maps (dictionaries) | ✅ | — |
| String interpolation (f-strings) | ✅ | — |
| Lambda expressions | ✅ | — |
| Pipe operator | ✅ | — |
| Pattern matching | ✅ | — |
| Generators (yield) | ✅ | — |
| Enums | ✅ | — |
| Import system | ✅ | — |
| Classes | ✅ | ✅ |
| Try / catch | ✅ | ✅ |
| Parenthesized expressions | ✅ | ✅ |
| Negative numbers | ✅ | ✅ |

## 🌳 AST Visualizer

Explore how sauravcode parses your programs with the AST visualizer (`sauravast.py`):

```bash
# Pretty tree view
python sauravast.py hello.srv

# Limit depth for large programs
python sauravast.py program.srv --depth 3

# Machine-readable JSON
python sauravast.py program.srv --json

# Node statistics
python sauravast.py program.srv --stats

# Graphviz DOT graph (pipe to dot -Tpng for images)
python sauravast.py program.srv --dot | dot -Tpng -o ast.png
```

Example output:
```
Program
├── AssignmentNode
│   ├── expression: NumberNode
│   │   └── value: 42.0
│   └── name: 'x'
├── FunctionNode
│   ├── body: [2 items]
│   │   ├── [0]: PrintNode ...
│   │   └── [1]: ReturnNode ...
│   ├── name: 'greet'
│   └── params: ['name']
└── FunctionCallNode
    ├── arguments: [1 items]
    │   └── [0]: StringNode
    │       └── value: 'World'
    └── name: 'greet'
```

## 🔥 Advanced Features

### Lambda Expressions

Inline anonymous functions for quick transformations:

```
double = lambda x -> x * 2
print double 5                # 10

# With higher-order functions
nums = [1, 2, 3, 4, 5]
doubled = map (lambda x -> x * 2) nums
print doubled                 # [2, 4, 6, 8, 10]

filtered = filter (lambda x -> x > 3) nums
print filtered                # [4, 5]
```

### Pipe Operator

Chain transformations left-to-right for readable data pipelines:

```
result = "hello world" |> upper |> reverse
print result                  # DLROW OLLEH

# Multi-step pipelines
"  Hello, World!  " |> trim |> lower |> print
# hello, world!
```

### Pattern Matching

Declarative branching with `match` expressions:

```
function describe x
    match x
        1 -> print "one"
        2 -> print "two"
        3 -> print "three"
        _ -> print "something else"

describe 2                    # two
describe 99                   # something else
```

### Generators

Lazy sequences with `yield` for memory-efficient iteration:

```
function countdown n
    while n > 0
        yield n
        n = n - 1

gen = countdown 5
print next gen                # 5
print next gen                # 4
print next gen                # 3
```

### Enums

Named constant groups with dot-notation access:

```
enum Color
    RED
    GREEN
    BLUE

c = Color.RED
print c                       # Color.RED

match c
    Color.RED -> print "red!"
    Color.GREEN -> print "green!"
    _ -> print "other"
```

### Imports

Modular code with file-based imports:

```
# math_utils.srv
function square x
    return x * x

function cube x
    return x * x * x

# main.srv
import "math_utils.srv"
print square 5                # 25
print cube 3                  # 27
```

## 🛠️ Developer Tooling

Sauravcode ships with a comprehensive suite of developer tools:

| Tool | Command | Description |
|------|---------|-------------|
| **Formatter** | `python sauravfmt.py file.srv` | Auto-format code with consistent indentation and spacing |
| **Linter** | `python sauravlint.py file.srv` | Static analysis for style, complexity, and potential bugs |
| **Profiler** | `python sauravprof.py file.srv` | Execution profiling with call counts and timing |
| **Debugger** | `python sauravdb.py file.srv` | Interactive debugger with breakpoints and step-through |
| **Coverage** | `python sauravcov.py file.srv` | Code coverage analysis (line-level hit/miss) |
| **Benchmarks** | `python sauravbench.py` | Performance benchmarks (fibonacci, sort, recursion, etc.) |
| **AST Viewer** | `python sauravast.py file.srv` | Parse tree visualization (text, JSON, Graphviz DOT) |
| **Playground** | `python sauravplay.py` | Interactive sandbox for experimenting |
| **Semantic Diff** | `python sauravdiff.py a.srv b.srv` | Structural diff between sauravcode files |
| **Doc Generator** | `python sauravdoc.py file.srv` | Extract documentation from source files |
| **Dependency Graph** | `python sauravdeps.py file.srv` | Visualize import dependencies between modules |
| **Complexity** | `python sauravcomplex.py file.srv` | Cyclomatic complexity analysis per function |
| **Notebook** | `python sauravnb.py file.srvnb` | Jupyter-style notebook for literate sauravcode |
| **Watch Mode** | `python sauravwatch.py file.srv` | Auto-rerun on file changes (live reload) |
| **Snapshot Test** | `python sauravsnap.py file.srv` | Snapshot testing for output verification |
| **Enhanced REPL** | `python sauravrepl.py` | REPL with history, multi-line editing, and syntax hints |
| **Canvas** | `python sauravcanvas.py file.srv` | Turtle graphics — generate SVG/HTML from drawing commands |

## 🏗️ Architecture

The codebase has two execution paths sharing a common tokenizer design:

- **`saurav.py`** — Tree-walk interpreter. Tokenizes, parses to AST, evaluates directly.
- **`sauravcc.py`** — Compiler. Tokenizes, parses to AST, generates C source, invokes gcc.

The compiler generates clean, readable C. Lists become dynamic arrays (`SrvList`) with bounds checking. Try/catch maps to `setjmp`/`longjmp`. Classes compile to C structs with associated functions.

For the full deep-dive, see the [Architecture Guide](docs/ARCHITECTURE.md).

## 📂 Project Structure

```
sauravcode/
├── saurav.py           # Interpreter + interactive REPL
├── sauravcc.py         # Compiler (.srv → C → native)
├── sauravast.py        # AST visualizer (tree, JSON, DOT, stats)
├── sauravbench.py      # Benchmark runner (fib, sort, recursion, etc.)
├── sauravcov.py        # Code coverage analysis
├── sauravdb.py         # Interactive debugger
├── sauravdiff.py       # Semantic diff between .srv files
├── sauravdoc.py        # Documentation generator
├── sauravfmt.py        # Code formatter
├── sauravlint.py       # Linter (style, complexity, bugs)
├── sauravplay.py       # Interactive playground
├── sauravprof.py       # Execution profiler
├── sauravcomplex.py    # Cyclomatic complexity analyzer
├── sauravdeps.py       # Import dependency graph
├── sauravnb.py         # Jupyter-style notebook runner
├── sauravrepl.py       # Enhanced REPL with history
├── sauravsnap.py       # Snapshot testing
├── sauravwatch.py      # File watcher (live reload)
├── sauravcanvas.py     # Turtle graphics (SVG/HTML output)
├── tests/              # 2,300+ pytest tests (40 test modules)
├── editors/
│   └── vscode/         # VS Code extension (syntax, snippets)
├── docs/
│   ├── LANGUAGE.md     # Language reference & EBNF grammar
│   ├── ARCHITECTURE.md # Compiler/interpreter internals
│   └── EXAMPLES.md     # Annotated examples
├── site/
│   └── index.html      # Documentation website
├── .github/
│   └── workflows/      # CI/CD (CodeQL, Pages)
├── STDLIB.md           # Standard library reference (95 functions)
├── CHANGELOG.md        # Version history
├── CONTRIBUTING.md     # Contribution guidelines
└── LICENSE             # MIT License
```

## 🧪 Running Tests

Run the comprehensive test suite:

```bash
# Full test suite (interpreter + compiler + REPL)
python -m pytest tests/ -v

# Run .srv test files directly
python saurav.py test_all.srv

# Compiler
python sauravcc.py test_all.srv
```

## 🔄 Language Comparison

See how sauravcode compares to other languages for common tasks:

| Task | sauravcode | Python | JavaScript |
|------|-----------|--------|------------|
| Print | `print "hello"` | `print("hello")` | `console.log("hello")` |
| Function | `function add a b`<br>`    return a + b` | `def add(a, b):`<br>`    return a + b` | `function add(a, b) {`<br>`    return a + b; }` |
| Call | `add 3 5` | `add(3, 5)` | `add(3, 5)` |
| For loop | `for i 1 6`<br>`    print i` | `for i in range(1, 6):`<br>`    print(i)` | `for (let i=1; i<6; i++)`<br>`    console.log(i)` |
| Lambda | `lambda x -> x * 2` | `lambda x: x * 2` | `x => x * 2` |
| Pipe | `"hi" \|> upper \|> reverse` | N/A (nested calls) | N/A (method chaining) |
| F-string | `f"Hi {name}"` | `f"Hi {name}"` | `` `Hi ${name}` `` |
| List comp | `[x * 2 for x in range 1 6]` | `[x*2 for x in range(1,6)]` | `[...Array(5)].map((_,i)=>(i+1)*2)` |

**Key differences:** No parentheses for calls, no commas between arguments, no semicolons, no braces. Indentation defines blocks (like Python), but function calls are cleaner.

## 🎯 Design Philosophy

> Code should read like thought. No ceremony, no noise — just logic.

Traditional languages carry decades of syntactic baggage. Sauravcode asks: *what if we kept only what matters?*

- **Function calls without parentheses** — `add 3 5` instead of `add(3, 5)`
- **Indentation-based blocks** — no `{}` or `end` keywords
- **Minimal punctuation** — colons, semicolons, and most commas are gone
- **Disambiguation when needed** — parentheses are available for complex expressions

The result is code that reads almost like pseudocode but actually runs.

## 📖 Documentation

| Document | Description |
|----------|-------------|
| [Standard Library](STDLIB.md) | All 95 built-in functions with signatures and examples |
| [Language Reference](docs/LANGUAGE.md) | Complete spec with EBNF grammar, types, operators, precedence |
| [Architecture Guide](docs/ARCHITECTURE.md) | How the tokenizer, parser, interpreter, and compiler work |
| [Examples](docs/EXAMPLES.md) | Annotated programs covering all features |
| [Changelog](CHANGELOG.md) | Version history and notable changes |
| [Website](https://sauravbhattacharya001.github.io/sauravcode/) | Interactive documentation |
| [Home Page](https://sites.google.com/view/sauravcode) | Project home |

## ✏️ Editor Support

### Visual Studio Code

Full syntax highlighting, 25 code snippets, and language configuration for VS Code.

**Quick install:**
```bash
# Symlink the extension (Windows)
mklink /D "%USERPROFILE%\.vscode\extensions\sauravcode" "path\to\sauravcode\editors\vscode"

# Symlink the extension (macOS / Linux)
ln -s path/to/sauravcode/editors/vscode ~/.vscode/extensions/sauravcode
```

See [`editors/vscode/README.md`](editors/vscode/README.md) for full details.

## 🤝 Contributing

Contributions are welcome! Here's how to get started:

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/my-feature`)
3. **Make** your changes with tests
4. **Test** with both interpreter and compiler
5. **Submit** a pull request

### Ideas for Contributions

- Additional data structures (sets, tuples)
- Compiler support for maps, f-strings, generators, and pattern matching
- Editor support for more editors (Sublime Text, Vim, Emacs, JetBrains)
- Optimization passes in the compiler
- Async/concurrent execution
- Package manager for .srv modules

## 📄 License

This project is licensed under the [MIT License](LICENSE).

## 👤 Author

**Saurav Bhattacharya** — [GitHub](https://github.com/sauravbhattacharya001)
