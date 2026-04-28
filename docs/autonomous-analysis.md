---
hide:
  - footer
---

# Autonomous Analysis & Simulation

> Five tools for autonomous code intelligence and interactive simulation — zero-configuration analysis, diagnosis, optimization, property inference, and cellular automata exploration.

!!! info "New in the Toolchain"
    These tools complement the [core tooling](tooling.md) and [advanced tools](advanced-tools.md).
    They emphasize **autonomous operation**: point them at your code and they figure out what's wrong,
    how to fix it, and how to verify it — without you writing tests or specifications.

---

## Quick Reference

| Tool | Command | Purpose |
|------|---------|---------|
| **sauravdiagnose** | `python sauravdiagnose.py file.srv` | Runtime error diagnosis with auto-patching |
| **sauravdoctor** | `python sauravdoctor.py file.srv` | Code health checkup (20 pathology detectors) |
| **sauravoptimize** | `python sauravoptimize.py file.srv` | Performance optimizer with auto-rewrite |
| **sauravoracle** | `python sauravoracle.py file.srv` | Property-based test oracle (zero-test inference) |
| **sauravautomata** | `python sauravautomata.py rule 30` | Cellular automata simulator & explorer |

---

## Runtime Diagnosis (`sauravdiagnose`)

Runs `.srv` programs, catches runtime failures, classifies errors into known patterns, analyzes source context, suggests fixes with confidence scores, and can auto-patch simple issues. Maintains a knowledge base of past errors to improve diagnosis over time.

### Usage

```bash
# Diagnose a single file
python sauravdiagnose.py program.srv

# Scan all .srv files in a directory
python sauravdiagnose.py path/to/project

# Auto-patch simple issues
python sauravdiagnose.py program.srv --fix

# Preview patches without applying
python sauravdiagnose.py program.srv --fix --dry-run

# Deep analysis with execution trace
python sauravdiagnose.py program.srv --deep

# Output formats
python sauravdiagnose.py program.srv --json
python sauravdiagnose.py program.srv --html report.html
```

### Knowledge Base

The diagnosis engine learns from past errors. Each time it diagnoses a file, it records the error pattern, context, and outcome in a local knowledge base (`.diagnose-kb.json`).

```bash
# View knowledge base statistics
python sauravdiagnose.py --kb

# Reset the knowledge base
python sauravdiagnose.py --kb-reset

# Show top N most common error patterns
python sauravdiagnose.py --top 5
```

### How It Works

1. **Execute** — runs the `.srv` program and captures any runtime error
2. **Classify** — matches the error against known patterns (undefined variable, type mismatch, index out of bounds, division by zero, infinite recursion, etc.)
3. **Analyze** — inspects surrounding source code for context
4. **Suggest** — generates fix suggestions with confidence scores
5. **Patch** (with `--fix`) — auto-applies high-confidence fixes
6. **Learn** — stores the diagnosis in the knowledge base for future reference

---

## Code Health (`sauravdoctor`)

A comprehensive health checkup for `.srv` programs that goes beyond simple linting. Each finding is classified as a **diagnosis** with severity, affected location, prescription (fix suggestion), and prognosis (impact if left untreated). Generates an interactive HTML report with a health score gauge.

### Usage

```bash
# Diagnose a single file
python sauravdoctor.py program.srv

# Scan all .srv files in current directory
python sauravdoctor.py .

# Include subdirectories
python sauravdoctor.py . --recursive

# Generate interactive HTML report
python sauravdoctor.py program.srv --html

# Filter by severity
python sauravdoctor.py . --severity critical

# Show only top findings
python sauravdoctor.py . --top 10

# Project health summary
python sauravdoctor.py . --summary

# JSON output
python sauravdoctor.py program.srv --json
```

### Pathology Catalogue (20 Detectors)

| ID | Pathology | What It Detects |
|----|-----------|-----------------|
| P001 | God Function | Function >50 LOC with high complexity — too many responsibilities |
| P002 | Shotgun Surgery | Variable used across many distant functions |
| P003 | Dead Parameter | Function parameter never used in the body |
| P004 | Magic Number | Unexplained numeric literal in logic |
| P005 | Long Parameter List | Function with more than 4 parameters |
| P006 | Deep Nesting | Code nested more than 4 levels deep |
| P007 | Duplicate Strings | Same string literal repeated more than 2 times |
| P008 | Feature Envy | Function referencing more external vars than local |
| P009 | Primitive Obsession | Function returning raw numbers that could be named constants |
| P010 | Speculative Generality | Empty function or unreachable branches |
| P011 | Inconsistent Naming | Mixed naming conventions (camelCase vs snake\_case) |
| P012 | Comment-to-Code Ratio | Too few or too many comments |
| P013 | Function Coupling | Function calling more than 8 other functions |
| P014 | Orphan Function | Defined function that's never called anywhere |
| P015 | Copy-Paste Suspect | Near-duplicate code blocks across functions |
| P016 | Boolean Blindness | Function returning boolean without a descriptive name |
| P017 | Long Line | Lines exceeding 120 characters |
| P018 | Hardcoded Path | Literal file paths in code |
| P019 | Empty Catch | Catch block with no meaningful handling |
| P020 | Recursive Risk | Recursive function without obvious base-case guard |

### Health Score

The doctor computes an overall health score (0–100) based on finding count, severity distribution, and code size. The HTML report includes a gauge visualization:

- **90–100** — Excellent health
- **70–89** — Good, minor issues
- **50–69** — Needs attention
- **0–49** — Critical, significant problems

---

## Code Optimizer (`sauravoptimize`)

Analyzes `.srv` programs for performance anti-patterns, suggests optimizations with estimated impact, and can auto-rewrite optimized versions. Optionally benchmarks before and after to verify improvements.

### Usage

```bash
# Analyze and report performance issues
python sauravoptimize.py program.srv

# Auto-rewrite optimized version (creates program_optimized.srv)
python sauravoptimize.py program.srv --fix

# Overwrite the original file in-place
python sauravoptimize.py program.srv --fix --inplace

# Benchmark before and after
python sauravoptimize.py program.srv --verify

# Filter by severity
python sauravoptimize.py program.srv --severity high

# Output formats
python sauravoptimize.py program.srv --json
python sauravoptimize.py program.srv --html report.html

# Explain a specific rule
python sauravoptimize.py --explain P006

# Batch analysis
python sauravoptimize.py *.srv
```

### Optimization Rules

| ID | Pattern | Optimization |
|----|---------|-------------|
| P001 | Redundant re-computation in loop | Hoist loop-invariant expressions |
| P002 | Repeated identical function calls | Memoize or cache result |
| P003 | String concatenation in loop | Use list accumulation + join |
| P004 | Unnecessary list copy | Append instead of concatenate |
| P005 | Linear search in collection | Replace with set/map lookup (O(n) → O(1)) |
| P006 | Recursive function without memoization | Add memoization (exponential → polynomial) |
| P007 | Unused computation | Remove dead assignments |
| P008 | Nested loop with constant inner bound | Flatten or precompute |
| P009 | Repeated map/list key access | Cache in local variable |
| P010 | Inefficient range iteration | Use for-each when index is unused |

### Verification Mode

With `--verify`, the optimizer:

1. Benchmarks the original program (multiple runs, statistical timing)
2. Applies optimizations
3. Benchmarks the optimized version
4. Reports speedup percentage and verifies output equivalence

---

## Test Oracle (`sauravoracle`)

An autonomous property-based test oracle that analyzes `.srv` functions, infers expected properties from naming conventions and code patterns, generates tests, and detects specification violations — **without you writing a single test**.

### Usage

```bash
# Full oracle analysis
python sauravoracle.py program.srv

# Show inferred properties only (no test execution)
python sauravoracle.py program.srv --infer

# Run all generated tests
python sauravoracle.py program.srv --test

# Continuous monitoring (re-analyze on file change)
python sauravoracle.py program.srv --watch

# Output formats
python sauravoracle.py program.srv --json
python sauravoracle.py program.srv --html report
```

### Inferred Properties

The oracle infers properties based on function names, parameter names, and code structure:

| Property | What It Means | Example Trigger |
|----------|--------------|----------------|
| **Pure** | Same input always gives same output | No external variable references |
| **Idempotent** | `f(f(x)) == f(x)` | Functions named `normalize`, `clamp`, `abs` |
| **Monotonic** | Output preserves input ordering | Functions named `sort`, `rank` |
| **Commutative** | `f(a, b) == f(b, a)` | Functions named `add`, `multiply`, `gcd` |
| **Associative** | `f(f(a, b), c) == f(a, f(b, c))` | Functions named `concat`, `merge` |
| **Bounded** | Output stays within a known range | Functions returning percentages or scores |
| **Total** | Function handles all inputs without error | Functions with guard clauses |

Each inferred property has a **confidence score** (0.0–1.0). Only properties above the confidence threshold are tested.

### How It Works

1. **Parse** — tokenizes and parses the `.srv` file into an AST
2. **Infer** — walks each function, analyzes naming and structure to hypothesize properties
3. **Generate** — creates test inputs (random values, edge cases, boundary values)
4. **Execute** — runs the function with generated inputs via the interpreter
5. **Verify** — checks whether the inferred properties hold
6. **Report** — property violations become test failures with counterexamples

---

## Cellular Automata (`sauravautomata`)

Interactive simulator and explorer for cellular automata in the terminal. Supports all 256 elementary 1D rules (Wolfram classification) and Conway's Game of Life with preset patterns.

### Usage

```bash
# 1D Elementary Cellular Automata
python sauravautomata.py rule 30 --generations 40 --width 80
python sauravautomata.py rule 110 --generations 60 --color

# Conway's Game of Life
python sauravautomata.py life --preset glider --generations 50
python sauravautomata.py life --random --density 0.3 --generations 100
python sauravautomata.py life --width 40 --height 20 --generations 80

# Interactive REPL
python sauravautomata.py repl

# Classify rules 0-255
python sauravautomata.py classify 0 255
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--width N` | 60 | Grid width in columns |
| `--height N` | 20 | Grid height in rows (Game of Life only) |
| `--generations N` | 40 | Number of generations to simulate |
| `--density F` | 0.3 | Random fill density (0.0–1.0) |
| `--color` | off | Enable ANSI color output |
| `--preset NAME` | — | Life preset: `glider`, `blinker`, `pulsar`, `gun`, `rpentomino` |

### Features

- **1D Rules (0–255):** Renders each generation as a row of cells. Includes Shannon entropy computation and sparkline visualization of entropy over time.
- **Game of Life:** Toroidal grid (edges wrap), preset patterns, random initialization, population tracking per generation.
- **Auto-Classification:** The `classify` command runs all rules in a range and groups them by Wolfram class (I: uniform, II: periodic, III: chaotic, IV: complex).
- **Interactive REPL:** Step through generations manually, toggle cells, switch rules, and explore patterns interactively.

### Example Output (Rule 30)

```
                             *
                            ***
                           **  *
                          ** ****
                         **  *   *
                        ** **** ***
                       **  *    *  *
                      ** ****  ******
                     **  *   ***     *
                    ** **** **  *   ***
```

!!! tip "Exploring Wolfram Rules"
    Rule 110 is proven Turing-complete. Rule 30 generates pseudorandom patterns used in
    Mathematica's random number generator. Try `classify 0 255` to see the full spectrum
    of behaviors from trivial (Class I) to complex (Class IV).

---

## Comparison: When to Use Which Tool

| I want to... | Use |
|--------------|-----|
| Find and fix runtime errors automatically | `sauravdiagnose --fix` |
| Get a code health checkup with prescriptions | `sauravdoctor` |
| Identify and fix performance bottlenecks | `sauravoptimize` |
| Verify function behavior without writing tests | `sauravoracle` |
| Visualize cellular automata and explore rules | `sauravautomata` |

These tools work well in combination:

```bash
# Full autonomous code review pipeline
python sauravdoctor.py src/ --summary        # Health overview
python sauravoptimize.py src/main.srv        # Performance analysis
python sauravoracle.py src/main.srv --test   # Property verification
python sauravdiagnose.py src/main.srv --fix  # Auto-fix runtime errors
```
