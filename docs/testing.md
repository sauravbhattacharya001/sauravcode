# Testing & Debugging Guide

> A practical guide to testing, debugging, coverage, snapshot testing, and fuzzing sauravcode programs.

## Overview

Sauravcode ships with a full testing and debugging toolkit:

| Tool | Command | Purpose |
|------|---------|---------|
| **sauravtest** | `python sauravtest.py [paths]` | Test runner — discover and run test suites |
| **sauravdbg** | `python sauravdbg.py file.srv` | Interactive step-through debugger |
| **sauravcov** | `python sauravcov.py file.srv` | Line-level code coverage |
| **sauravsnap** | `python sauravsnap.py test files` | Snapshot testing — regression test output |
| **sauravfuzz** | `python sauravfuzz.py` | Grammar-aware fuzzer — find crashes |

---

## Test Runner (`sauravtest`)

The test runner discovers and executes test files following simple conventions.

### Conventions

- **Test files** match `test_*.srv` or `*_test.srv`
- **Test functions** start with `test_`
- Use `assert` statements for assertions

### Basic Usage

```bash
# Run all tests in the current directory
python sauravtest.py

# Run a specific test file
python sauravtest.py test_basics.srv

# Run tests in a directory
python sauravtest.py tests/

# Verbose output (show captured output and error details)
python sauravtest.py -v

# Only run tests matching a keyword
python sauravtest.py -k "sort"

# Stop on first failure
python sauravtest.py --failfast
```

### Export Results

```bash
# Export to JSON for CI integration
python sauravtest.py --json results.json
```

### Writing Tests

```
fn test_addition()
    assert 2 + 2 == 4
end

fn test_string_concat()
    let greeting = "hello" + " world"
    assert greeting == "hello world"
end

fn test_list_operations()
    let items = [1 2 3]
    assert len(items) == 3
    append(items 4)
    assert len(items) == 4
end
```

!!! tip "Test Isolation"
    Each test function runs in its own scope. Variables from one test don't leak into another.

---

## Interactive Debugger (`sauravdbg`)

A line-by-line step-through debugger with breakpoints, watch expressions, and stack inspection.

### Starting a Debug Session

```bash
# Start debugging
python sauravdbg.py program.srv

# Start with a breakpoint at line 5
python sauravdbg.py program.srv --break 5
```

### Debugger Commands

| Command | Shortcut | Description |
|---------|----------|-------------|
| `step` | `s` | Execute one statement |
| `next` | `n` | Step over function calls |
| `continue` | `c` | Run until next breakpoint |
| `b <line>` | — | Set breakpoint at line number |
| `rb <line>` | — | Remove breakpoint |
| `bl` | — | List all breakpoints |
| `p <expr>` | — | Print variable or expression |
| `vars` | — | Show all variables in scope |
| `stack` | — | Show call stack |
| `where` | — | Show current source location with context |
| `list [n]` | — | Show source code around current line |
| `watch <var>` | — | Add variable to watchlist |
| `unwatch <var>` | — | Remove from watchlist |
| `restart` | — | Restart execution |
| `quit` | `q` | Exit debugger |

### Example Session

```
$ python sauravdbg.py sort_demo.srv
[dbg] Loaded sort_demo.srv (42 lines)
[dbg] → Line 1: let data = [5 3 8 1 9 2]

(sauravdbg) b 15
[dbg] Breakpoint set at line 15

(sauravdbg) c
[dbg] Hit breakpoint at line 15: let pivot = items[0]

(sauravdbg) p data
[5, 3, 8, 1, 9, 2]

(sauravdbg) vars
  data = [5, 3, 8, 1, 9, 2]
  pivot = 5

(sauravdbg) watch pivot
[dbg] Watching: pivot

(sauravdbg) s
[dbg] → Line 16: let left = []
  [watch] pivot = 5
```

!!! tip "Debugging Tests"
    To debug a failing test, copy the test function body into a standalone `.srv` file and run it through `sauravdbg`.

---

## Code Coverage (`sauravcov`)

Measure which lines of your code are actually executed during a test run.

### Usage

```bash
# Run a file and report coverage
python sauravcov.py program.srv

# Run a test file and measure coverage of the code it tests
python sauravcov.py test_basics.srv
```

### Reading Coverage Output

Coverage reports show each line as:

- **✓ (hit)** — line was executed
- **✗ (miss)** — line was never reached
- **- (skip)** — blank line or comment (not counted)

The summary shows:

```
Coverage: 47/52 lines (90.4%)
```

### CI Integration

Pair with the project's [Codecov configuration](../.codecov.yml) to track coverage trends across commits. The CI workflow runs `sauravcov` automatically and uploads results.

---

## Snapshot Testing (`sauravsnap`)

Snapshot testing captures program output (stdout and stderr) and compares it against saved baselines. This catches unintended output regressions.

### Workflow

```bash
# 1. Record snapshots for the first time
python sauravsnap.py update *.srv

# 2. Run tests against saved snapshots
python sauravsnap.py test *.srv

# 3. Review differences when tests fail
python sauravsnap.py review

# 4. See a diff for a specific file
python sauravsnap.py diff program.srv

# 5. List all saved snapshots
python sauravsnap.py list

# 6. Clean up stale snapshots
python sauravsnap.py clean
```

### Options

```bash
# Custom snapshot directory (default: __snapshots__)
python sauravsnap.py test *.srv --snap-dir my_snaps/

# Increase timeout for slow programs
python sauravsnap.py test *.srv --timeout 30

# Auto-update snapshots on failure
python sauravsnap.py test *.srv --update-on-fail

# Verbose output
python sauravsnap.py test *.srv -v
```

### When to Use Snapshots

- Demo programs that should produce consistent output
- Compiler/interpreter output that shouldn't change unexpectedly
- CLI tool output formatting

!!! warning "Non-deterministic Output"
    Snapshots don't work well for programs with random output or timestamps. Use `sauravtest` assertions for those.

---

## Fuzzing (`sauravfuzz`)

The grammar-aware fuzzer generates random but syntactically plausible sauravcode programs and runs them, looking for crashes, hangs, and unexpected errors.

### Basic Usage

```bash
# Run 100 random programs (default)
python sauravfuzz.py

# Run 1000 iterations with a fixed seed for reproducibility
python sauravfuzz.py -n 1000 --seed 42

# Deeper nesting and more statements per program
python sauravfuzz.py --depth 6 --stmts 20

# Export crash report
python sauravfuzz.py --report crashes.json

# Minimize crash-inducing programs
python sauravfuzz.py --min-crash

# Mutate existing programs instead of generating from scratch
python sauravfuzz.py --mutate
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `-n`, `--iterations` | 100 | Number of programs to generate |
| `-s`, `--seed` | random | Seed for reproducibility |
| `-t`, `--timeout` | 2.0s | Per-program timeout |
| `-d`, `--depth` | 4 | Max AST nesting depth |
| `--stmts` | — | Statements per generated program |
| `--report` | — | Export results to JSON |
| `--min-crash` | off | Minimize crash-inducing inputs |
| `--mutate` | off | Mutate existing files instead |
| `--quiet` | off | Suppress per-program output |

### Interpreting Results

The fuzzer reports:

- **Crashes** — programs that caused unhandled exceptions
- **Hangs** — programs that exceeded the timeout
- **Successes** — programs that ran without error

Crash-inducing programs are saved so you can reproduce and fix the bug.

---

## Putting It All Together

A typical testing workflow for a sauravcode project:

```bash
# 1. Write tests alongside your code
#    test_mymodule.srv tests mymodule.srv

# 2. Run the full test suite
python sauravtest.py tests/

# 3. Check coverage to find untested paths
python sauravcov.py tests/test_mymodule.srv

# 4. Snapshot demo programs for regression checking
python sauravsnap.py update demos/*.srv
python sauravsnap.py test demos/*.srv

# 5. Fuzz the interpreter to find edge cases
python sauravfuzz.py -n 500 --seed 42

# 6. Debug any failures interactively
python sauravdbg.py failing_test.srv --break 10
```

### CI Integration

The project's CI workflow (`.github/workflows/ci.yml`) automatically:

1. Runs `sauravtest.py` on the full test suite
2. Generates coverage reports with `sauravcov`
3. Uploads coverage to [Codecov](https://codecov.io/gh/sauravbhattacharya001/sauravcode)

To replicate CI locally, run:

```bash
python sauravtest.py tests/ -v --json results.json
```
