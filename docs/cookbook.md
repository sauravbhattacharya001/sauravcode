---
hide:
  - footer
---

# Cookbook & Recipes

> Practical end-to-end workflows that combine sauravcode tools to solve real-world development problems. Each recipe is a complete walkthrough you can follow step by step.

!!! tip "Prerequisites"
    These recipes assume you have sauravcode installed and are familiar with the [core tooling](tooling.md). Each recipe lists the specific tools used.

---

## Quick Index

| Recipe | Tools Used | Time |
|--------|-----------|------|
| [Full CI Pipeline from Scratch](#full-ci-pipeline-from-scratch) | `sauravci` · `sauravtest` · `sauravlint` · `sauravsec` · `sauravcov` | 15 min |
| [Debug a Failing Program](#debug-a-failing-program) | `sauravdiagnose` · `sauravtrace` · `sauravdb` · `sauravexplain` | 10 min |
| [Security Audit a Codebase](#security-audit-a-codebase) | `sauravsec` · `sauravbounty` · `sauravguard` · `sauravcontract` | 15 min |
| [Evolve a Solution Genetically](#evolve-a-solution-genetically) | `sauravevolve` · `sauravtest` · `sauravmutant` | 10 min |
| [Profile and Optimize Hot Paths](#profile-and-optimize-hot-paths) | `sauravprof` · `sauravmetrics` · `sauravoptimize` · `sauravcc` | 15 min |
| [Migrate to a New Version](#migrate-to-a-new-version) | `sauravdiff` · `sauravadapt` · `sauravmigrate` · `sauravtest` | 20 min |
| [Build a Production Release](#build-a-production-release) | `sauravcc` · `sauravmin` · `sauravbundle` · `sauravver` | 10 min |
| [Code Review Workflow](#code-review-workflow) | `sauravlint` · `sauravcomplex` · `sauravdigest` · `sauravdoctor` | 10 min |
| [Interactive Learning Session](#interactive-learning-session) | `sauravlearn` · `sauravtutorial` · `sauravkata` · `sauravchallenge` | 20 min |
| [Monitor Project Health Over Time](#monitor-project-health-over-time) | `sauravsentinel` · `sauravforecast` · `sauravmetrics` | 10 min |

---

## Full CI Pipeline from Scratch

**Goal:** Set up a complete local CI pipeline that lints, type-checks, tests, measures coverage, and runs security scans — all in one command.

**Tools:** `sauravci` · `sauravtest` · `sauravlint` · `sauravsec` · `sauravcov`

### Step 1: Verify your project structure

```bash
# Ensure you have a standard layout
myproject/
├── src/
│   ├── main.srv
│   ├── math_utils.srv
│   └── string_utils.srv
├── tests/
│   ├── test_math.srv
│   └── test_string.srv
└── sauravci.json          # Optional: CI configuration
```

### Step 2: Run the full CI pipeline

```bash
# One command does everything
python sauravci.py

# The pipeline runs these stages in order:
#   1. Lint (sauravlint) — catch code smells and style issues
#   2. Type check (sauravtype) — infer types and find mismatches
#   3. Test (sauravtest) — run all test_* functions
#   4. Coverage (sauravcov) — measure line/branch coverage
#   5. Security (sauravsec) — scan for vulnerable patterns
```

### Step 3: Add a CI configuration file

```json title="sauravci.json"
{
  "stages": ["lint", "type", "test", "coverage", "security"],
  "lint": {
    "paths": ["src/"],
    "strict": true
  },
  "test": {
    "paths": ["tests/"],
    "fail_fast": false
  },
  "coverage": {
    "threshold": 80,
    "fail_below": true
  },
  "security": {
    "paths": ["src/"],
    "min_severity": "medium"
  }
}
```

### Step 4: Integrate with GitHub Actions

```yaml title=".github/workflows/ci.yml"
name: CI
on: [push, pull_request]
jobs:
  ci:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: python sauravci.py --json > ci-report.json
      - run: python sauravtest.py tests/ --fail-fast
```

!!! success "Result"
    A single `python sauravci.py` command catches bugs, enforces style, verifies types, checks coverage thresholds, and flags security issues — locally and in CI.

---

## Debug a Failing Program

**Goal:** Systematically find and fix a runtime error in a `.srv` program using the debugging toolkit.

**Tools:** `sauravdiagnose` · `sauravtrace` · `sauravdb` · `sauravexplain`

### Step 1: Get an automatic diagnosis

```bash
# Point sauravdiagnose at the failing file — it analyzes the error,
# identifies the root cause, and suggests fixes automatically
python sauravdiagnose.py broken.srv
```

Output includes:

- The exact error and line number
- Root cause analysis (why it happened)
- Suggested fix with code diff
- Auto-patch option to apply the fix

### Step 2: Trace execution for deeper insight

```bash
# If the diagnosis isn't enough, trace every statement
python sauravtrace.py broken.srv

# The trace shows:
#   Line 12: x = 0
#   Line 13: y = 100 / x   ← DivisionByZero here
#   Variables at crash: {x: 0, y: undefined}
```

### Step 3: Step through interactively

```bash
# Launch the interactive debugger for fine-grained control
python sauravdb.py broken.srv --debug

# Debugger commands:
#   s/step    — execute next statement
#   p x       — print variable value
#   b 15      — set breakpoint at line 15
#   w         — show call stack
#   c         — continue to next breakpoint
```

### Step 4: Understand the logic

```bash
# Get a plain-English explanation of what the code does
python sauravexplain.py broken.srv

# Shows control flow, data flow, and logic explanation
# for each function — often reveals the conceptual bug
```

!!! tip "Pro Tip"
    Chain diagnosis → trace → debug for increasingly detailed investigation. Most bugs are caught at step 1.

---

## Security Audit a Codebase

**Goal:** Perform a comprehensive security review of a `.srv` project, from automated scanning to manual verification.

**Tools:** `sauravsec` · `sauravbounty` · `sauravguard` · `sauravcontract`

### Step 1: Run the security scanner

```bash
# Scan for known vulnerability patterns
python sauravsec.py src/ --verbose

# Checks for:
#   - Hardcoded secrets (API keys, passwords)
#   - Command injection patterns
#   - Path traversal vulnerabilities
#   - Unsafe deserialization
#   - SSRF patterns
```

### Step 2: Hunt for deeper bugs

```bash
# The bounty hunter finds subtler issues the scanner misses
python sauravbounty.py src/ --auto-triage

# Finds:
#   - Unchecked division (missing zero guards)
#   - Infinite loop risk (while true without break)
#   - Unused variables (potential logic errors)
#   - Magic numbers (unmaintainable constants)
#   - Large functions (complexity hotspots)
```

### Step 3: Verify runtime safety

```bash
# Run programs under the guardian to catch runtime exploits
python sauravguard.py src/server.srv --strict --timeout 10

# Monitors for:
#   - Infinite loops (kills runaway processes)
#   - Memory exhaustion (collection growth limits)
#   - Stack overflow (recursion depth limits)
#   - Resource abuse (file I/O logging)
```

### Step 4: Verify contracts hold

```bash
# Check that preconditions and postconditions are never violated
python sauravcontract.py src/ --verbose

# Example contract violations:
#   FAIL: divide(a, b) — precondition `b != 0` violated
#   FAIL: sort(lst) — postcondition `is_sorted(result)` violated
```

### Step 5: Generate a combined report

```bash
# Combine all findings into a single HTML report
python sauravsec.py src/ --format html -o security-report.html
python sauravbounty.py src/ --format html -o bounty-report.html
```

---

## Evolve a Solution Genetically

**Goal:** Use genetic programming to automatically evolve a `.srv` program that solves a given problem.

**Tools:** `sauravevolve` · `sauravtest` · `sauravmutant`

### Step 1: Define the problem

```bash
# Use a built-in problem
python sauravevolve.py --problem fizzbuzz --pop 200 --gens 100

# Or define custom test cases
cat > cases.json << 'EOF'
{
  "name": "double",
  "description": "Double the input",
  "cases": [
    {"input": "5", "expected": "10"},
    {"input": "0", "expected": "0"},
    {"input": "-3", "expected": "-6"}
  ]
}
EOF
python sauravevolve.py --cases cases.json
```

### Step 2: Watch evolution in action

```
Generation  1: Best fitness 0.30 (3/10 cases) | Pop: 200 | Avg: 0.08
Generation 15: Best fitness 0.70 (7/10 cases) | Pop: 200 | Avg: 0.42
Generation 38: Best fitness 1.00 (10/10 cases) ★ SOLUTION FOUND

Evolved program:
  fn double x is
    return x * 2
  end
```

### Step 3: Verify the evolved solution

```bash
# Write evolved solution to file and run tests
python sauravtest.py evolved_double.srv --verbose

# Mutation test to verify robustness
python sauravmutant.py evolved_double.srv --tests tests/test_double.srv
# Kill rate: 95% — the test suite catches most mutations
```

!!! info "When to Use Genetic Programming"
    Best for exploring solution spaces when you know the **what** (test cases) but not the **how** (algorithm). Not a replacement for human design, but a powerful brainstorming tool.

---

## Profile and Optimize Hot Paths

**Goal:** Find performance bottlenecks, optimize them, and optionally compile to native code for maximum speed.

**Tools:** `sauravprof` · `sauravmetrics` · `sauravoptimize` · `sauravcc`

### Step 1: Profile to find bottlenecks

```bash
# Run the profiler to identify hot functions
python sauravprof.py program.srv

#   Function        Calls    Total ms    Self ms    % Time
#   ──────────────  ─────    ────────    ───────    ──────
#   sort_data       1        1,240       42         62.0%
#   compare         15,422   980         980        49.0%  ← hot path
#   format_output   1        340         340        17.0%
```

### Step 2: Measure complexity

```bash
# Get complexity metrics for the hot functions
python sauravcomplex.py program.srv

#   Function        Cyclomatic  Cognitive  Halstead  Maintainability
#   compare         12          18         42.3      34.2 (low)
```

### Step 3: Auto-optimize

```bash
# Let the optimizer suggest and apply improvements
python sauravoptimize.py program.srv --apply

# Applies:
#   - Loop hoisting (moves invariants out of loops)
#   - Redundant computation elimination
#   - Collection pre-sizing
#   - Algorithm substitution suggestions
```

### Step 4: Compile for native speed

```bash
# For maximum performance, compile to native via C
python sauravcc.py program.srv -o program_fast

# Compare performance
python sauravbench.py program.srv --runs 100
# Interpreted: 1,240ms avg
# Compiled:    18ms avg  (69x faster)
```

---

## Migrate to a New Version

**Goal:** Safely update a codebase when language features change or APIs evolve.

**Tools:** `sauravdiff` · `sauravadapt` · `sauravmigrate` · `sauravtest`

### Step 1: See what changed

```bash
# Semantic diff between old and new versions of a module
python sauravdiff.py old/utils.srv new/utils.srv

# Shows structural changes (not just text):
#   + Added function: validate_input(data, schema)
#   ~ Modified function: parse_data — added parameter `strict`
#   - Removed function: legacy_parse (deprecated in v2)
```

### Step 2: Auto-adapt callers

```bash
# Automatically update call sites for API changes
python sauravadapt.py src/ --from old/utils.srv --to new/utils.srv

# Updates:
#   src/main.srv:12 — parse_data(x) → parse_data(x, strict=false)
#   src/main.srv:28 — legacy_parse(y) → parse_data(y)  [migration]
```

### Step 3: Run migration scripts

```bash
# Apply version-specific migration rules
python sauravmigrate.py src/ --from v1 --to v2
```

### Step 4: Verify nothing broke

```bash
# Run the full test suite
python sauravtest.py tests/ --verbose

# Run mutation testing to verify test quality
python sauravmutant.py src/ --tests tests/ --threshold 75
```

---

## Build a Production Release

**Goal:** Minify, bundle, compile, and version-tag a project for release.

**Tools:** `sauravcc` · `sauravmin` · `sauravbundle` · `sauravver`

### Step 1: Bump the version

```bash
# Semantic versioning with changelog
python sauravver.py bump minor --message "Added sorting algorithms"

# Or specify exact version
python sauravver.py set 2.0.0 --message "Major rewrite"
```

### Step 2: Bundle dependencies

```bash
# Combine all imports into a single file
python sauravbundle.py src/main.srv -o dist/app.srv

# Resolves import chains, deduplicates, preserves order
```

### Step 3: Minify for distribution

```bash
# Remove comments, whitespace, rename locals
python sauravmin.py dist/app.srv -o dist/app.min.srv

# Before: 12,450 bytes
# After:   4,230 bytes (66% reduction)
```

### Step 4: Compile to native

```bash
# Produce a standalone executable
python sauravcc.py dist/app.srv -o dist/app

# The binary has no runtime dependency on Python or sauravcode
```

### Step 5: Generate release notes

```bash
# Auto-generate changelog from commit history
python sauravver.py changelog --from v1.5.0 --to v2.0.0
```

---

## Code Review Workflow

**Goal:** Systematically review code quality before merging changes.

**Tools:** `sauravlint` · `sauravcomplex` · `sauravdigest` · `sauravdoctor`

### Step 1: Lint for obvious issues

```bash
python sauravlint.py src/ --strict
```

### Step 2: Check complexity

```bash
# Flag functions that are too complex
python sauravcomplex.py src/ --threshold 15

# Any function with cyclomatic complexity > 15 needs refactoring
```

### Step 3: Get a health checkup

```bash
# The doctor runs 20 pathology detectors
python sauravdoctor.py src/

# Checks for:
#   - God functions (too many responsibilities)
#   - Deep nesting (arrow code)
#   - Long parameter lists
#   - Feature envy (functions that use other modules more than their own)
#   - Dead code
```

### Step 4: Generate a project digest

```bash
# Full project overview with architecture analysis
python sauravdigest.py src/ --html review.html

# Includes: dependency graph, hotspot map, coupling analysis,
# code health scores, and prioritized recommendations
```

---

## Interactive Learning Session

**Goal:** Learn sauravcode features through guided, interactive practice.

**Tools:** `sauravlearn` · `sauravtutorial` · `sauravkata` · `sauravchallenge`

### Step 1: Start with guided tutorials

```bash
# Interactive tutorial with progressive lessons
python sauravtutorial.py

# Covers: variables, functions, collections, classes,
# error handling, file I/O, and advanced features
```

### Step 2: Practice with katas

```bash
# Short coding exercises with instant feedback
python sauravkata.py

# Categories: strings, math, sorting, recursion,
# data structures, algorithms
```

### Step 3: Take on challenges

```bash
# Harder problems with time tracking and leaderboard
python sauravchallenge.py --difficulty medium
```

### Step 4: Use the AI mentor

```bash
# Get personalized guidance and code review
python sauravmentor.py review src/my_solution.srv

# The mentor analyzes your code and suggests:
#   - Idiomatic improvements
#   - Performance tips
#   - Common pitfalls to avoid
```

---

## Monitor Project Health Over Time

**Goal:** Track code quality trends and predict which files will need maintenance.

**Tools:** `sauravsentinel` · `sauravforecast` · `sauravmetrics`

### Step 1: Record a health snapshot

```bash
# Sentinel records metrics to a local history file
python sauravsentinel.py src/

# Tracks: complexity, test coverage, lint warnings,
# function count, nesting depth, code health score
```

### Step 2: View trends

```bash
# Show health trends over time
python sauravsentinel.py src/ --report

#   Date        Health   Complexity   Coverage   Warnings
#   2026-01-15  82/100   12.3 avg     78%        4
#   2026-02-01  79/100   14.1 avg     75%        7    ← regression
#   2026-03-01  85/100   11.8 avg     82%        2    ← improvement
```

### Step 3: Predict maintenance needs

```bash
# Forecast which files will need attention soon
python sauravforecast.py src/ --top 5

#   Risk   File              Predicted Maintenance
#   HIGH   src/parser.srv    ~48 hours (complexity spike)
#   MED    src/server.srv    ~1 week (growing smell density)
#   LOW    src/utils.srv     ~3 weeks (stable)
```

### Step 4: Set quality gates

```bash
# Fail CI if health drops below threshold
python sauravsentinel.py src/ --fail-on-regression

# Set explicit goals
python sauravsentinel.py --set-goal health 85
python sauravsentinel.py --set-goal coverage 80
```

### Step 5: Generate HTML dashboard

```bash
# Interactive dashboard with charts and drill-downs
python sauravsentinel.py src/ --html dashboard.html
python sauravforecast.py src/ --html forecast.html
```

!!! success "Continuous Monitoring"
    Run sentinel as a post-commit hook or CI step to catch quality regressions early. The forecast tool helps you allocate maintenance time before problems become urgent.

---

*Have a workflow you'd like to see here? [Open an issue](https://github.com/sauravbhattacharya001/sauravcode/issues) with the `documentation` label.*
