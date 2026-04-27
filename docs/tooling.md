# Developer Tooling

> Sauravcode ships with a complete development toolkit: linter, formatter, profiler, code coverage, debugger, and documentation generator. All tools work on `.srv` files out of the box.

## Overview

| Tool | Command | Purpose |
|------|---------|---------|
| **saurav** | `python saurav.py file.srv` | Interpreter — run programs |
| **sauravcc** | `python sauravcc.py file.srv` | Compiler — compile to native executables via C |
| **sauravlint** | `python sauravlint.py file.srv` | Static analysis — find bugs and code smells |
| **sauravfmt** | `python sauravfmt.py file.srv` | Code formatting — consistent style |
| **sauravprof** | `python sauravprof.py file.srv` | Profiling — find performance bottlenecks |
| **sauravcov** | `python sauravcov.py file.srv` | Code coverage — measure test completeness |
| **sauravdb** | `python sauravdb.py file.srv` | Interactive debugger — step through code |
| **sauravdoc** | `python sauravdoc.py file.srv` | Doc generator — extract API documentation |
| **sauravast** | `python sauravast.py file.srv` | AST visualizer — inspect parse trees |
| **sauravbench** | `python sauravbench.py file.srv` | Benchmarking — statistical timing analysis |
| **sauravcomplex** | `python sauravcomplex.py file.srv` | Complexity analyzer — cyclomatic, cognitive, Halstead |
| **sauravdeps** | `python sauravdeps.py path/` | Dependency analyzer — import graphs, cycle detection |
| **sauravdiff** | `python sauravdiff.py a.srv b.srv` | Semantic diff — AST-based structural comparison |
| **sauravgen** | `python sauravgen.py function name` | Code generator — scaffolding from templates |
| **sauravnb** | `python sauravnb.py notebook.srvnb` | Notebook runner — Jupyter-like literate programming |
| **sauravpkg** | `python sauravpkg.py install name` | Package manager — install, publish, manage deps |
| **sauravplay** | `python sauravplay.py` | Web playground — browser-based code editor |
| **sauravrepl** | `python sauravrepl.py` | Interactive REPL — explore and experiment |
| **sauravsec** | `python sauravsec.py file.srv` | Security scanner — detect vulnerable patterns |
| **sauravsnap** | `python sauravsnap.py test files/` | Snapshot testing — regression test stdout/stderr |
| **sauravtype** | `python sauravtype.py file.srv` | Type checker — infer types and catch mismatches |
| **sauravwatch** | `python sauravwatch.py file.srv` | File watcher — auto-run on save |

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

---

## AST Visualizer (`sauravast`)

Parses `.srv` files and displays the abstract syntax tree as a pretty-printed diagram, JSON, or Graphviz DOT output.

### Usage

```bash
python sauravast.py program.srv              # Pretty tree view
python sauravast.py program.srv --json       # JSON output
python sauravast.py program.srv --depth 3    # Limit tree depth
python sauravast.py program.srv --stats      # Show AST statistics
python sauravast.py program.srv --dot        # Graphviz DOT output
```

### Example output

```
Program
├── FunctionDef: fibonacci
│   ├── Param: n
│   └── Body
│       ├── LetDecl: a = 0
│       ├── LetDecl: b = 1
│       ├── ForLoop: i in range(0, n)
│       │   └── Body
│       │       ├── LetDecl: temp = b
│       │       ├── Assignment: b = a + b
│       │       └── Assignment: a = temp
│       └── Return: a
└── Call: print(fibonacci(10))
```

### Tips

- Use `--dot` to pipe into Graphviz: `python sauravast.py prog.srv --dot | dot -Tpng -o ast.png`
- Use `--stats` to see node type counts, tree depth, and total node count
- Use `--depth` to focus on high-level structure of large programs

---

## Benchmarking (`sauravbench`)

Runs programs multiple times and reports statistical timing analysis with warmup, comparison mode, baseline tracking, and percentile reporting.

### Usage

```bash
python sauravbench.py fib.srv                       # Basic benchmark (10 runs)
python sauravbench.py fib.srv -n 50                 # 50 iterations
python sauravbench.py fib.srv --warmup 3            # 3 warmup rounds
python sauravbench.py fib.srv --json                # JSON output
python sauravbench.py fib.srv --save                # Save baseline
python sauravbench.py fib.srv --check               # Compare against baseline
python sauravbench.py fib.srv sort.srv --compare    # Compare two programs
python sauravbench.py fib.srv -n 30 --percentiles   # Show p50/p90/p95/p99
```

### Example report

```
=== sauravbench — Benchmark Report ===

  File: fib.srv  |  Runs: 50  |  Warmup: 3

  Mean:     12.45 ms
  Median:   12.12 ms
  Std Dev:   1.23 ms
  Min:      10.80 ms
  Max:      15.67 ms

  p50:  12.12 ms  |  p90:  14.01 ms  |  p95:  14.89 ms  |  p99:  15.67 ms
```

### Tips

- Always use `--warmup` for accurate results (eliminates JIT and cache effects)
- Use `--save` / `--check` in CI to catch performance regressions
- Use `--compare` to benchmark before/after an optimisation

---

## Complexity Analyzer (`sauravcomplex`)

Computes cyclomatic complexity, cognitive complexity, Halstead metrics, and maintainability index. Helps identify functions that need refactoring.

### Usage

```bash
python sauravcomplex.py program.srv              # Analyze single file
python sauravcomplex.py src/                     # Analyze directory
python sauravcomplex.py program.srv --json       # JSON output
python sauravcomplex.py program.srv --threshold 10  # Flag complex functions
python sauravcomplex.py program.srv --sort complexity  # Sort by metric
python sauravcomplex.py a.srv b.srv --compare    # Compare two files
python sauravcomplex.py program.srv --details    # Per-function breakdown
```

### Metrics

| Metric | What it measures | Good | Bad |
|--------|-----------------|------|-----|
| **Cyclomatic** | Number of linearly independent paths | 1–10 | >15 |
| **Cognitive** | How hard humans find the code to understand | 1–15 | >25 |
| **Halstead Volume** | Algorithmic information content | < 500 | > 1000 |
| **Maintainability** | Composite score (0–100) | > 65 | < 40 |

### Example output

```
=== sauravcomplex — Complexity Report ===

  Function         Cyclo  Cognitive  Halstead  Maintain
  ──────────────────────────────────────────────────────
  solve_maze         12        18     782.3      38.1  ⚠️
  parse_config        8        11     445.6      52.4
  fibonacci           3         2     120.1      78.9  ✓

  File averages: Cyclomatic=7.7  Cognitive=10.3  Maintainability=56.5
```

---

## Dependency Analyzer (`sauravdeps`)

Scans `.srv` files for import statements, builds a dependency graph, and detects circular dependencies.

### Usage

```bash
python sauravdeps.py src/                       # Analyze directory
python sauravdeps.py src/ --format dot           # Graphviz DOT output
python sauravdeps.py src/ --format json          # JSON graph
python sauravdeps.py src/ --cycles               # Only show circular deps
python sauravdeps.py src/ --stats                # Import statistics
python sauravdeps.py src/ --tree                 # Import tree per file
python sauravdeps.py src/ --roots                # Root modules (nothing imports them)
python sauravdeps.py src/ --leaves               # Leaf modules (import nothing)
python sauravdeps.py src/ --depth                # Max dependency depth per module
python sauravdeps.py src/ --unused main.srv      # Modules not reachable from file
```

### Example output

```
=== sauravdeps — Dependency Report ===

  Modules: 12  |  Edges: 18  |  Cycles: 1

  Circular dependency detected:
    parser.srv → validator.srv → parser.srv

  Deepest chain (depth 4):
    main.srv → engine.srv → parser.srv → lexer.srv

  Root modules: main.srv, cli.srv
  Leaf modules: lexer.srv, utils.srv, constants.srv
```

### Tips

- Use `--format dot | dot -Tsvg -o deps.svg` to visualise the full graph
- Use `--cycles` in CI to prevent circular dependencies from being merged

---

## Semantic Diff (`sauravdiff`)

Compares two `.srv` files by their AST structure rather than raw text. Formatting changes (whitespace, comments, blank lines) are ignored — only meaningful code changes are reported.

### Usage

```bash
python sauravdiff.py old.srv new.srv             # Colored diff
python sauravdiff.py old.srv new.srv --json       # JSON output
python sauravdiff.py old.srv new.srv --summary    # Counts only
python sauravdiff.py old.srv new.srv --context 5  # More context lines
python sauravdiff.py old.srv new.srv --no-color   # Plain text
```

### Change types

- **Added** — new function, variable, or statement
- **Removed** — deleted function, variable, or statement
- **Modified** — function body, parameter list, or expression changed
- **Moved** — function or block reordered (same content, different position)

### Example output

```
=== sauravdiff — Semantic Diff ===

  Modified: function fibonacci
    - let temp = b      → let t = b      (renamed variable)
    + let sum = a + b                     (new variable)

  Added: function memoize (lines 25-35)
  Removed: function slow_fib (was lines 40-50)

  Summary: 1 modified, 1 added, 1 removed
```

---

## Code Generator (`sauravgen`)

Generates boilerplate `.srv` files from built-in templates. Scaffolds functions, classes, enums, tests, modules, scripts, and entire projects.

### Usage

```bash
python sauravgen.py function my_func --args "x y z"
python sauravgen.py class Animal --fields "name species age"
python sauravgen.py enum Color --variants "Red Green Blue"
python sauravgen.py test my_module --functions "add subtract"
python sauravgen.py module utils --functions "helper1 helper2"
python sauravgen.py project myapp
python sauravgen.py script greet --args "name greeting"
```

### Templates

| Template | Description | Generated file |
|----------|-------------|----------------|
| `function` | Standalone function with docstring | `<name>.srv` |
| `class` | Class with constructor, methods, toString | `<name>.srv` |
| `enum` | Enum with variants and match example | `<name>.srv` |
| `test` | Test file with test functions | `test_<name>.srv` |
| `module` | Module with imports/exports pattern | `<name>.srv` |
| `project` | Full directory: `src/`, `tests/`, README, `.gitignore` | `<name>/` |
| `script` | CLI script with argument parsing | `<name>.srv` |

### Tips

- Use `project` to bootstrap new repos with a standard structure
- Generated test files include one test per function with TODO markers
- All templates include doc comments as starting points

---

## Notebook Runner (`sauravnb`)

Jupyter-like literate programming for sauravcode. Notebooks (`.srvnb` files) contain markdown and code cells separated by markers. The runner executes cells sequentially with a shared interpreter.

### File format

```
--- md ---
# My Notebook
This is a **markdown** cell.

--- code ---
let x = 10
print x + 5

--- md ---
The result above should be 15.

--- code ---
print x * 2
```

### Usage

```bash
python sauravnb.py notebook.srvnb              # Run and display output
python sauravnb.py notebook.srvnb --html out.html   # Export to HTML
python sauravnb.py notebook.srvnb --quiet       # Suppress markdown, show code output only
python sauravnb.py notebook.srvnb --fail-fast   # Stop on first error
python sauravnb.py notebook.srvnb --json         # JSON output (cell results)
```

### Tips

- Cells share state — variables and functions defined in earlier cells are available later
- Use `--html` to generate shareable reports with rendered markdown and code output
- Use `--fail-fast --quiet` in CI to validate notebooks

---

## Package Manager (`sauravpkg`)

Manages sauravcode dependencies with a `saurav.pkg.json` manifest. Supports install, publish, search, and a local registry.

### Commands

```bash
python sauravpkg.py init                       # Create saurav.pkg.json
python sauravpkg.py install <name>             # Install a package
python sauravpkg.py uninstall <name>           # Remove a package
python sauravpkg.py list                       # List installed packages
python sauravpkg.py search <query>             # Search registry
python sauravpkg.py info <name>                # Package details
python sauravpkg.py pack                       # Bundle as .srvpkg archive
python sauravpkg.py publish                    # Publish to local registry
python sauravpkg.py update                     # Update all to latest
python sauravpkg.py outdated                   # Check for updates
python sauravpkg.py deps                       # Show dependency tree
python sauravpkg.py validate                   # Validate manifest
python sauravpkg.py run <script>               # Run named script
```

### Manifest (`saurav.pkg.json`)

```json
{
  "name": "my-project",
  "version": "1.0.0",
  "description": "A sauravcode project",
  "main": "src/main.srv",
  "scripts": {
    "test": "python saurav.py tests/test_all.srv",
    "build": "python sauravcc.py src/main.srv -o build/main"
  },
  "dependencies": {}
}
```

---

## Web Playground (`sauravplay`)

Launches a local web server with a browser-based code editor for experimenting with sauravcode in real time.

### Usage

```bash
python sauravplay.py                  # Start on http://localhost:8471
python sauravplay.py --port 9000      # Custom port
python sauravplay.py --no-open        # Don't auto-open browser
```

### Features

- Syntax-highlighted code editor with line numbers
- Run code with `Ctrl+Enter` or the Run button
- Output panel with stdout capture and error display
- 8 built-in example programs (dropdown selector)
- Execution time display
- Share button — copies a URL-encoded permalink of your code
- Sandboxed: file I/O, sleep, and input are disabled for safety

---

## REPL (`sauravrepl`)

Interactive read-eval-print loop with persistent state, multi-line editing, tab completion, and session save/load.

### Usage

```bash
python sauravrepl.py              # Start interactive REPL
python sauravrepl.py -e "x = 5"  # Evaluate and exit
python sauravrepl.py --no-color   # Disable colors
python sauravrepl.py --history    # Show history file path
```

### REPL Commands

| Command | Description |
|---------|-------------|
| `.help` | Show help |
| `.vars` | List all variables in scope |
| `.fns` | List all defined functions |
| `.clear` | Clear the screen |
| `.load file.srv` | Load and execute a file |
| `.save file.srv` | Save session to file |
| `.ast` | Show AST of last expression |
| `.time` | Toggle execution timing |
| `.reset` | Reset interpreter state |

### Features

- Multi-line blocks auto-detected (if, while, for, fn, match, try, enum)
- Tab completion for variables, functions, builtins, and keywords
- Expression results auto-printed (no explicit `print` needed)
- Errors don't kill the session — just shows the error and continues

---

## Security Scanner (`sauravsec`)

Detects dangerous patterns, unsafe operations, and potential vulnerabilities by analysing the AST.

### Usage

```bash
python sauravsec.py file.srv                        # Scan file
python sauravsec.py src/                            # Scan directory
python sauravsec.py --json file.srv                 # JSON output
python sauravsec.py --severity high file.srv        # Filter by severity
python sauravsec.py --disable SEC003,SEC007 file.srv  # Disable rules
python sauravsec.py --summary dir/                  # Summary only
python sauravsec.py --sarif file.srv                # SARIF output (CI integration)
```

### Rules

| Code | Severity | Description |
|------|----------|-------------|
| SEC001 | High | Path traversal — file path built from user input |
| SEC002 | Medium | Unbounded loop — `while true` with no break |
| SEC003 | High | Hardcoded credential — password/secret/token/key as string literal |
| SEC004 | Medium | Unchecked file operation — file read/write without try/catch |
| SEC005 | High | Command injection — shell command with variable interpolation |
| SEC006 | Medium | Information disclosure — printing sensitive variable names |
| SEC007 | Low | Weak comparison — using `==` on security-sensitive values |

### Tips

- Use `--sarif` to integrate with GitHub Advanced Security code scanning
- Combine with `sauravlint` for comprehensive static analysis
- Use `--disable` for known false positives

---

## Snapshot Testing (`sauravsnap`)

Regression testing by comparing program stdout/stderr against saved snapshots.

### Commands

```bash
python sauravsnap.py update [FILES...]    # Capture and save snapshots
python sauravsnap.py test [FILES...]      # Test against saved snapshots
python sauravsnap.py review               # Interactively review changes
python sauravsnap.py list                 # List all saved snapshots
python sauravsnap.py clean                # Remove snapshots for deleted files
python sauravsnap.py diff FILE            # Show diff between current and snapshot
```

### Options

```bash
--snap-dir DIR     # Snapshot directory (default: __snapshots__)
--timeout SECS     # Per-file timeout (default: 10)
--verbose          # Show passing tests too
```

### Workflow

```bash
# 1. Create initial snapshots
python sauravsnap.py update demos/*.srv

# 2. Make code changes, then test
python sauravsnap.py test demos/*.srv

# 3. If output changed intentionally, review and accept
python sauravsnap.py review

# 4. Add to CI
python sauravsnap.py test demos/*.srv --timeout 5
```

---

## Type Checker (`sauravtype`)

Static type inference and checking. Analyses sauravcode programs to infer types from usage patterns and detect potential type mismatches — no type annotations required.

### Usage

```bash
python sauravtype.py file.srv              # Check a file
python sauravtype.py file.srv --verbose    # Show all inferred types
python sauravtype.py file.srv --json       # JSON output
python sauravtype.py file.srv --summary    # Type summary only
python sauravtype.py dir/                  # Check all .srv files
```

### Type Warnings

| Code | Description |
|------|-------------|
| T001 | Type mismatch in binary operation (e.g., `string + int`) |
| T002 | Type mismatch in comparison (incompatible types) |
| T003 | Function called with wrong argument count |
| T004 | Index operation on non-list/non-map type |
| T005 | Arithmetic operation on non-numeric type |
| T006 | Return type inconsistency (different branches return different types) |
| T007 | Nullable access without check (variable might be `nil`) |

### Example output

```
=== sauravtype — Type Report ===

  calculator.srv:15: T001 Type mismatch: "hello" + 5
    Left operand inferred as String, right as Number

  calculator.srv:23: T003 Function 'add' expects 2 args, got 3

  2 warnings in 1 file
```

---

## File Watcher (`sauravwatch`)

Monitors `.srv` files and automatically re-runs them on save. Uses polling for cross-platform support (no external dependencies).

### Usage

```bash
python sauravwatch.py file.srv                      # Watch a single file
python sauravwatch.py file.srv --interval 0.5        # Custom poll interval (seconds)
python sauravwatch.py dir/                           # Watch all .srv files in directory
python sauravwatch.py dir/ --recursive               # Watch recursively
python sauravwatch.py file.srv --clear               # Clear terminal before each run
python sauravwatch.py file.srv --quiet               # Only show output
python sauravwatch.py file.srv --test                # Run with sauravtest instead
python sauravwatch.py file.srv --compile             # Compile with sauravcc instead
python sauravwatch.py file.srv --stats               # Show run statistics
python sauravwatch.py file.srv --notify              # Desktop notification on errors
python sauravwatch.py file.srv --on-success "echo done"   # Run command on success
python sauravwatch.py file.srv --on-failure "echo fail"   # Run command on failure
```

### Tips

- Use `--test` during TDD to auto-run tests on save
- Use `--compile` to catch compilation errors immediately
- Combine with `--clear --stats` for a clean development experience
- `--on-success` / `--on-failure` hooks enable custom workflows (e.g., notifications, deployment)

---

## More Tools

Sauravcode ships with 40+ additional specialized tools for testing, analysis, refactoring, learning, and creative coding. See the **[Advanced Tools Reference](advanced-tools.md)** for the full catalog including:

- **`sauravtest`** — test runner, **`sauravmutant`** — mutation testing, **`sauravcontract`** — design-by-contract
- **`sauravtrace`** — execution tracing, **`sauravchrono`** — time-travel debugging
- **`sauravrefactor`** — automated refactoring, **`sauravmigrate`** — Python-to-sauravcode conversion
- **`sauravtranspile`** — transpile to Python, **`sauravapi`** — instant REST API from `.srv` files
- **`sauravlearn`** / **`sauravquest`** / **`sauravkata`** — interactive learning and practice
- **`sauravfuzz`** — grammar-aware fuzzing, **`sauravevolve`** — genetic programming
- And many more…
