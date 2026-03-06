# Developer Tooling

> Sauravcode ships with a complete development toolkit: linter, formatter, profiler, code coverage, debugger, and documentation generator. All tools work on `.srv` files out of the box.

## Overview

| Tool | Command | Purpose |
|------|---------|---------|
| **sauravlint** | `python sauravlint.py file.srv` | Static analysis — find bugs and code smells |
| **sauravfmt** | `python sauravfmt.py file.srv` | Code formatting — consistent style |
| **sauravprof** | `python sauravprof.py file.srv` | Profiling — find performance bottlenecks |
| **sauravcov** | `python sauravcov.py file.srv` | Code coverage — measure test completeness |
| **sauravdb** | `python sauravdb.py file.srv` | Interactive debugger — step through code |
| **sauravdoc** | `python sauravdoc.py file.srv` | Doc generator — extract API documentation |

---

## Linter (`sauravlint`)

Static analysis tool that catches bugs, style issues, and code smells before you run your program.

### Usage

```bash
# Lint a single file
python sauravlint.py file.srv

# Lint with non-zero exit code on warnings (for CI)
python sauravlint.py --check file.srv

# Output as JSON (for editor integrations)
python sauravlint.py --json file.srv

# Filter by severity
python sauravlint.py --severity error file.srv

# Disable specific rules
python sauravlint.py --disable W003,W005 file.srv

# Lint an entire directory
python sauravlint.py --check src/
```

### Rules

#### Errors (E-codes) — likely bugs

| Code | Rule | Description |
|------|------|-------------|
| E001 | Undefined variable | Variable used but never assigned |
| E002 | Unreachable code | Code after `return`, `throw`, `break`, or `continue` |
| E003 | Division by zero | Literal division by zero (e.g., `x / 0`) |
| E004 | Duplicate function | Two functions with the same name and arity |
| E005 | Break/continue outside loop | `break` or `continue` in non-loop context |

#### Warnings (W-codes) — code smells

| Code | Rule | Description |
|------|------|-------------|
| W001 | Unused variable | Assigned but never read |
| W002 | Unused parameter | Function parameter never used in body |
| W003 | Variable shadowing | Inner variable shadows an outer scope variable |
| W004 | Self-comparison | Comparing a variable to itself (`x == x`) |
| W005 | Constant condition | Condition always true or false (`if true`, `while false`) |
| W006 | Empty block | `if`, `while`, `for`, `try`, or `catch` with no body |
| W007 | Too many parameters | Function with more than 5 parameters |
| W008 | Deep nesting | Code nested more than 5 levels deep |
| W009 | Unused import | Import statement for a module never referenced |
| W010 | Reassignment before use | Variable assigned twice without being read between |
| W011 | Inconsistent indentation | Mixed tabs and spaces |

### Example output

```
file.srv:12: W001 Unused variable 'temp' (assigned but never read)
file.srv:25: E002 Unreachable code after return
file.srv:41: W003 Variable 'x' shadows outer scope
```

---

## Formatter (`sauravfmt`)

Automatically formats `.srv` files with consistent indentation, spacing, and style.

### Usage

```bash
# Preview changes (dry-run, no file modification)
python sauravfmt.py file.srv

# Format in-place
python sauravfmt.py file.srv --write

# Check if file needs formatting (exit 1 if yes, for CI)
python sauravfmt.py --check file.srv

# Show unified diff
python sauravfmt.py --diff file.srv

# Custom indent width (default: 4 spaces)
python sauravfmt.py file.srv --indent 2

# Format all .srv files in a directory
python sauravfmt.py src/ --write
```

### What it does

- Normalises indentation to consistent spaces (configurable width)
- Removes trailing whitespace
- Collapses excessive blank lines
- Standardises operator spacing
- Fixes mixed tabs/spaces

### CI integration

Add to your GitHub Actions workflow:

```yaml
- name: Check formatting
  run: python sauravfmt.py --check *.srv
```

---

## Profiler (`sauravprof`)

Instruments the interpreter to measure function timing, call counts, and call graphs. Use it to find performance bottlenecks.

### Usage

```bash
# Run with default report (top 10 functions by time)
python sauravprof.py program.srv

# Show top 20 functions
python sauravprof.py program.srv --top 20

# Sort by call count instead of time
python sauravprof.py program.srv --sort calls

# Only show functions that took >= 1ms
python sauravprof.py program.srv --threshold 1.0

# Output as JSON
python sauravprof.py program.srv --json

# Include call graph (who calls whom)
python sauravprof.py program.srv --callgraph

# Suppress program output (show only profile)
python sauravprof.py program.srv --quiet
```

### Example report

```
=== sauravprof — Performance Report ===

  Function         Calls   Total (ms)   Self (ms)   Avg (ms)
  ─────────────────────────────────────────────────────────────
  fibonacci           89       12.45        8.32       0.14
  compute_sum         10        3.21        3.21       0.32
  validate             5        0.89        0.89       0.18

Total program time: 16.55 ms
```

### Tips

- **`--sort calls`** reveals functions called most often (hot paths)
- **`--callgraph`** helps understand execution flow
- **`--threshold`** filters noise from micro-functions
- Compare profiles before/after optimisation with `--json` output

---

## Code Coverage (`sauravcov`)

Tracks which source lines execute during a program run and generates coverage reports. Supports line and branch coverage.

### Usage

```bash
# Terminal report
python sauravcov.py program.srv

# JSON output (for CI integration)
python sauravcov.py program.srv --json

# HTML report (visual, with source highlighting)
python sauravcov.py program.srv --html report.html

# Annotated source (inline hit/miss markers)
python sauravcov.py program.srv --annotate

# Include branch coverage
python sauravcov.py program.srv --branch

# Fail CI if coverage drops below threshold
python sauravcov.py program.srv --fail-under 80

# Suppress program output
python sauravcov.py program.srv --quiet
```

### Example report

```
=== sauravcov — Coverage Report ===

  File             Stmts   Exec   Miss   Cover
  ────────────────────────────────────────────────
  program.srv         45     38      7    84.4%

  Uncovered lines: 22-24, 31, 40-42
```

### CI integration

```yaml
- name: Check coverage
  run: python sauravcov.py tests/test_all.srv --fail-under 80 --quiet
```

---

## Debugger (`sauravdb`)

Interactive step debugger for `.srv` programs. Set breakpoints, inspect variables, and step through execution.

### Usage

```bash
python sauravdb.py program.srv
```

### Commands

| Command | Shortcut | Description |
|---------|----------|-------------|
| `step` | `s` | Execute the next statement |
| `next` | `n` | Execute the next statement (step over) |
| `continue` | `c` | Run until next breakpoint or end |
| `break <line>` | `b <line>` | Set breakpoint at line number |
| `delete <line>` | `d <line>` | Remove breakpoint at line |
| `breaklist` | `bl` | List all breakpoints |
| `print <expr>` | `p <expr>` | Print a variable's value |
| `vars` | | Show all variables in current scope |
| `funcs` | | Show all defined functions |
| `stack` | | Show call stack |
| `where` | | Show current position in source |
| `list [n]` | | Show source around current line (n = context lines) |
| `restart` | | Restart from beginning |
| `quit` | `q` | Exit debugger |
| `help` | `h` | Show help |

### Example session

```
$ python sauravdb.py fib.srv
sauravdb> b 5
Breakpoint set at line 5
sauravdb> c
→ 5: let result = fibonacci n - 1
sauravdb> p n
n = 10
sauravdb> vars
  n = 10
  result = <undefined>
sauravdb> s
→ 6: return result
sauravdb> p result
result = 55
```

---

## Documentation Generator (`sauravdoc`)

Extracts functions, enums, variables, and their comments from `.srv` files to generate API documentation in Markdown or HTML.

### Usage

```bash
# Print docs to stdout
python sauravdoc.py file.srv

# Write to file
python sauravdoc.py file.srv -o docs.md

# Document an entire directory
python sauravdoc.py src/ -o docs/

# HTML output
python sauravdoc.py file.srv --format html

# Include table of contents
python sauravdoc.py file.srv --toc

# Include private items (names starting with _)
python sauravdoc.py file.srv --private

# Show code statistics (function count, LOC, etc.)
python sauravdoc.py file.srv --stats

# Include source code in documentation
python sauravdoc.py file.srv --source
```

### Comment conventions

The doc generator extracts comments directly above function definitions:

```sauravcode
# Compute the nth Fibonacci number.
# Uses iterative approach for O(n) performance.
function fibonacci n
    let a = 0
    let b = 1
    for i in range 0 n
        let temp = b
        b = a + b
        a = temp
    return a
```

This produces:

> **`fibonacci(n)`**
>
> Compute the nth Fibonacci number.
> Uses iterative approach for O(n) performance.

---

## Putting It All Together

A typical development workflow:

```bash
# 1. Write code
vim calculator.srv

# 2. Format
python sauravfmt.py calculator.srv --write

# 3. Lint
python sauravlint.py calculator.srv

# 4. Run tests with coverage
python sauravcov.py tests/test_calculator.srv --fail-under 80

# 5. Profile if slow
python sauravprof.py calculator.srv --top 5

# 6. Debug if broken
python sauravdb.py calculator.srv

# 7. Generate docs
python sauravdoc.py calculator.srv -o docs/calculator.md --toc
```

### CI pipeline example

```yaml
name: CI
on: [push, pull_request]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Format check
        run: python sauravfmt.py --check *.srv demos/*.srv

      - name: Lint
        run: python sauravlint.py --check *.srv demos/*.srv

      - name: Tests with coverage
        run: python sauravcov.py test_all.srv --fail-under 70 --quiet

      - name: Generate docs
        run: python sauravdoc.py *.srv -o docs/api/ --toc
```
