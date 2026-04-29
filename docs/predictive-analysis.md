# Predictive & Analysis Tools

Advanced tools for anticipating problems, understanding change impact, and
tracking technical debt across your sauravcode projects.

---

## Test Case Prophet (`sauravprophet`)

Autonomous test case generator that discovers functions in your `.srv` code,
analyzes their parameters and branching logic, then automatically generates
comprehensive test files.

### Usage

```bash
python sauravprophet.py file.srv                    # Analyze and generate tests
python sauravprophet.py path/to/dir                 # Scan all .srv files
python sauravprophet.py file.srv --run              # Generate AND run tests
python sauravprophet.py file.srv --html report.html # Interactive HTML report
python sauravprophet.py file.srv --json             # JSON output
python sauravprophet.py file.srv --out tests/       # Output test files to dir
python sauravprophet.py file.srv --strategy edge    # Focus on edge cases
python sauravprophet.py file.srv --strategy random  # Random value generation
python sauravprophet.py file.srv --strategy smart   # Smart analysis (default)
python sauravprophet.py file.srv --max-tests 50     # Limit total test cases
python sauravprophet.py file.srv --predict          # Predict expected output
```

### Strategies

| Strategy | Description |
|----------|-------------|
| `smart` | Analyzes comparisons and branches to pick meaningful boundary values (default) |
| `edge` | Focuses on edge cases: zero, negative, empty strings, large numbers |
| `random` | Generates random inputs for broad coverage |

### Features

- **Function discovery** — regex-based `.srv` parsing finds all functions and their parameters
- **Branch analysis** — extracts boundary values from comparisons (`if x > 5` → tests with 4, 5, 6)
- **Output prediction** — predicts expected results for simple arithmetic/logic functions
- **Recursive detection** — identifies recursive functions and generates appropriate depth tests
- **HTML report** — interactive pass/fail matrix with prediction accuracy metrics

### Example

```bash
$ python sauravprophet.py math_utils.srv --run --strategy smart

╔═══════════════════════════════════════════════════╗
║         sauravprophet — Test Case Prophet         ║
╚═══════════════════════════════════════════════════╝

Scanning: math_utils.srv
  Discovered 4 functions: factorial, fibonacci, gcd, is_prime

Generating tests (strategy: smart)...
  factorial: 8 test cases (boundary + edge)
  fibonacci: 6 test cases (sequence verification)
  gcd:       9 test cases (coprime + identity + zero)
  is_prime:  12 test cases (primes + composites + edge)

Running 35 tests...
  ✓ 33 passed  ✗ 2 failed  (94.3%)
```

---

## Change Impact Analyzer (`sauravimpact`)

Analyzes the blast radius of potential changes — which functions and files
depend on a target, cascade depth, risk scoring, and suggested test coverage.

### Usage

```bash
python sauravimpact.py target.srv                    # Analyze all functions
python sauravimpact.py target.srv --function myfunc  # Specific function
python sauravimpact.py . --function myfunc           # Search all .srv files
python sauravimpact.py . --recursive                 # Deep scan
python sauravimpact.py target.srv --html report.html # Interactive HTML dashboard
python sauravimpact.py target.srv --json             # JSON output
python sauravimpact.py target.srv --graph            # ASCII call graph
python sauravimpact.py . --hotspots                  # Highest blast radius functions
python sauravimpact.py . --safe-changes              # Low-impact safe-to-modify functions
```

### Analysis Engines

| Code | Engine | What It Detects |
|------|--------|-----------------|
| I001 | Direct Dependency Scan | Functions that directly call the target |
| I002 | Transitive Dependency Chain | Full reachability via call graph |
| I003 | Variable Flow Analysis | Shared/global variable coupling |
| I004 | Import Ripple Detector | Downstream importers of a file |
| I005 | Structural Coupling Score | Bidirectional coupling measurement |
| I006 | Change Cascade Simulator | Predicted breakage if signature changes |
| I007 | Test Coverage Gap Finder | Affected functions without tests |
| I008 | Risk Scorecard | Composite 0–100 risk score |

### Key Modes

**Hotspot analysis** — `--hotspots` ranks functions by blast radius (most dependents).
Useful for identifying the most dangerous code to modify:

```bash
$ python sauravimpact.py . --hotspots --recursive

Top 5 Hotspots (highest blast radius):
  1. parse_expression (12 dependents, risk: 87/100)
  2. evaluate        (9 dependents, risk: 72/100)
  3. tokenize        (7 dependents, risk: 68/100)
  4. resolve_var     (6 dependents, risk: 55/100)
  5. format_output   (4 dependents, risk: 41/100)
```

**Safe changes** — `--safe-changes` identifies leaf functions with zero or minimal dependents,
ideal candidates for refactoring without risk.

---

## Technical Debt Tracker (`sauravdebt`)

Scans codebases to identify, classify, prioritize, and track technical debt
over time. Maintains a historical timeline (`.debt-history.json`) to detect
new debt, resolved debt, and velocity trends.

### Usage

```bash
python sauravdebt.py program.srv              # Scan a single file
python sauravdebt.py .                        # Scan all .srv files in cwd
python sauravdebt.py . --recursive            # Include subdirectories
python sauravdebt.py . --html report.html     # Interactive HTML dashboard
python sauravdebt.py . --json                 # JSON output
python sauravdebt.py . --plan                 # Prioritised payoff plan
python sauravdebt.py . --timeline             # Debt trend over time
python sauravdebt.py . --new                  # Only new debt since last scan
python sauravdebt.py . --resolved             # Recently resolved debt
python sauravdebt.py . --severity critical    # Filter by severity
python sauravdebt.py . --top 10               # Top N highest-ROI items
python sauravdebt.py . --budget 20            # Alert if total exceeds budget
python sauravdebt.py . --reset                # Clear timeline history
```

### Debt Detectors

| Code | Detector | What It Finds |
|------|----------|---------------|
| D001 | TODO/FIXME/HACK | Comment markers indicating known debt |
| D002 | Duplicated Code Blocks | Near-identical blocks across functions |
| D003 | Magic Numbers | Unexplained numeric literals |
| D004 | Missing Error Handling | File/network ops without try/catch |
| D005 | Dead Code | Functions defined but never called |
| D006 | Long Functions | Functions exceeding 40 lines |
| D007 | Deep Nesting | Code nested >4 indent levels |
| D008 | Hardcoded Strings | Repeated string literals → constants |
| D009 | Missing Documentation | Functions without preceding comments |
| D010 | Complex Conditionals | If/elif chains with >4 branches |
| D011 | Inconsistent Style | Mixed naming conventions in a file |
| D012 | Coupling Hotspots | Functions called by / calling too many |

### Payoff Plan

The `--plan` flag generates a prioritized repayment plan sorted by ROI
(impact ÷ effort). Each item shows severity, estimated fix time, and
expected benefit:

```bash
$ python sauravdebt.py . --plan --top 5

Technical Debt Payoff Plan (Top 5 by ROI):
  #1  D005 Dead Code — remove_legacy_parser (utils.srv)
      Severity: medium | Effort: 5 min | Impact: high
      → Removes 45 unreachable lines, simplifies maintenance

  #2  D003 Magic Numbers — calculate_tax (billing.srv:23)
      Severity: low | Effort: 3 min | Impact: medium
      → Extract 0.0825 → TAX_RATE constant

  #3  D006 Long Function — process_order (orders.srv:112)
      Severity: high | Effort: 30 min | Impact: high
      → 87 lines, extract validation + formatting sub-functions
  ...
```

### Timeline Tracking

Each scan saves a snapshot to `.debt-history.json`. Use `--timeline` to
visualize debt trends:

```bash
$ python sauravdebt.py . --timeline

Debt Timeline (last 10 snapshots):
  2026-03-01: 23 items (score: 145)
  2026-03-15: 21 items (score: 132)  ↓ -2 resolved
  2026-04-01: 19 items (score: 118)  ↓ -2 resolved
  2026-04-15: 22 items (score: 128)  ↑ +3 new
  2026-04-29: 20 items (score: 121)  ↓ -2 resolved

Velocity: -0.6 items/week (improving)
```

---

## Combining These Tools

These three tools form a powerful analysis pipeline:

1. **Before changes:** Run `sauravimpact` to understand blast radius
2. **Generate tests:** Use `sauravprophet` to auto-generate tests for affected code
3. **After changes:** Run `sauravdebt` to verify you didn't introduce new debt

```bash
# Full pre-change analysis workflow
python sauravimpact.py . --function my_func --graph
python sauravprophet.py affected_file.srv --run --strategy edge
python sauravdebt.py . --new
```
