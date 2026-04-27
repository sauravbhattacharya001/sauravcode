# Advanced Tools Reference

> Beyond the [core developer tooling](tooling.md), sauravcode ships with 40+ specialized tools for code analysis, learning, security, deployment, and creative programming. All tools work on `.srv` files out of the box — no configuration needed.

---

## Quick Reference

| Category | Tools |
|----------|-------|
| **Testing & Quality** | `sauravtest` · `sauravmutant` · `sauravcontract` · `sauravguard` · `sauravsentinel` |
| **Analysis & Metrics** | `sauravdigest` · `sauravmetrics` · `sauravstats` · `sauravmap` · `sauravquery` · `sauravforecast` |
| **Debugging & Tracing** | `sauravtrace` · `sauravdbg` · `sauravchrono` · `sauravexplain` |
| **Refactoring & Migration** | `sauravrefactor` · `sauravadapt` · `sauravmigrate` · `sauravheal` · `sauravagent` |
| **Code Transformation** | `sauravmin` · `sauravobf` · `sauravtranspile` · `sauravalchemy` · `sauravbundle` |
| **CI & Deployment** | `sauravci` · `sauravapi` · `sauravpipe` · `sauravver` · `sauravshare` · `sauravembed` |
| **Learning & Practice** | `sauravlearn` · `sauravtutorial` · `sauravchallenge` · `sauravkata` · `sauravquest` · `sauravgolf` · `sauravduel` · `sauravmentor` |
| **Creative & Fun** | `sauravcanvas` · `sauravplot` · `sauravmatrix` · `sauravcipher` · `sauravevolve` |
| **Utilities** | `sauravcheat` · `sauravhl` · `sauravregex` · `sauravsnippet` · `sauravtodo` · `sauravflow` · `sauravscaffold` · `sauravtext` · `sauravfuzz` · `sauravbounty` · `sauravintent` · `sauravreflex` |

---

## Testing & Quality

### Test Runner (`sauravtest`)

Discovers and runs test functions in `.srv` files with timing, pass/fail reporting, and summary statistics.

**Convention:** Functions named `test_*` are automatically discovered and executed as tests.

```bash
python sauravtest.py tests/                     # Run all tests in directory
python sauravtest.py tests/test_math.srv        # Run specific test file
python sauravtest.py tests/ --verbose           # Show passing tests too
python sauravtest.py tests/ --fail-fast         # Stop on first failure
python sauravtest.py tests/ --json              # JSON output for CI
python sauravtest.py tests/ --filter "test_sort*"  # Filter by name pattern
```

### Mutation Testing (`sauravmutant`)

Measures test suite effectiveness by generating mutant programs (small code changes like `+` → `-`, `<` → `<=`) and checking that tests catch them. A surviving mutant means a gap in your tests.

```bash
python sauravmutant.py src/math.srv --tests tests/test_math.srv
python sauravmutant.py src/ --tests tests/ --json
python sauravmutant.py src/sort.srv --tests tests/ --verbose
python sauravmutant.py src/ --tests tests/ --threshold 80   # Fail if kill rate < 80%
```

### Design-by-Contract (`sauravcontract`)

Verifies preconditions, postconditions, and invariants in `.srv` programs. Autonomously detects contract violations during execution.

```bash
python sauravcontract.py program.srv            # Check contracts
python sauravcontract.py program.srv --verbose  # Show all checked contracts
python sauravcontract.py program.srv --json     # JSON output
```

### Runtime Guardian (`sauravguard`)

Monitors `.srv` program execution with proactive safety detection — catches infinite loops, excessive memory, stack overflows, and other runtime anomalies before they crash.

```bash
python sauravguard.py program.srv               # Run with safety monitoring
python sauravguard.py program.srv --timeout 10  # Custom timeout (seconds)
python sauravguard.py program.srv --memory 50   # Memory limit (MB)
python sauravguard.py program.srv --verbose     # Detailed safety log
```

### Project Health Sentinel (`sauravsentinel`)

Continuously monitors `.srv` project health over time, detects regressions in complexity, test coverage, and code quality. Tracks metrics across runs for trend analysis.

```bash
python sauravsentinel.py src/                   # Run health check
python sauravsentinel.py src/ --history         # Show trend over time
python sauravsentinel.py src/ --json            # JSON output
python sauravsentinel.py src/ --fail-on-regression  # CI: fail if quality dropped
```

---

## Analysis & Metrics

### Codebase Digest (`sauravdigest`)

Scans all `.srv` files in a directory and generates a comprehensive project report: architecture overview, hotspots, dependency chains, code health scores, and recommendations.

```bash
python sauravdigest.py src/                     # Full project digest
python sauravdigest.py src/ --json              # JSON output
python sauravdigest.py src/ --html report.html  # HTML report
python sauravdigest.py src/ --compare old.json  # Compare with baseline
```

### Code Metrics (`sauravmetrics`)

Analyzes `.srv` files for code quality metrics: lines of code, function count, comment density, cyclomatic complexity, and maintainability scores.

```bash
python sauravmetrics.py program.srv             # Single file metrics
python sauravmetrics.py src/                    # Directory-wide metrics
python sauravmetrics.py src/ --json             # JSON output
python sauravmetrics.py src/ --sort complexity  # Sort by metric
```

### Codebase Statistics (`sauravstats`)

Project-wide metrics: total files, LOC, function counts, import patterns, comment ratios, and file-level breakdowns.

```bash
python sauravstats.py src/                      # Full stats report
python sauravstats.py src/ --json               # JSON output
python sauravstats.py src/ --sort loc           # Sort files by lines of code
```

### Codebase Cartographer (`sauravmap`)

Statically analyzes `.srv` files to map function definitions, call sites, variable usage, and cross-file dependencies. Builds a navigable map of your codebase.

```bash
python sauravmap.py src/                        # Full codebase map
python sauravmap.py src/ --callers my_func      # Who calls this function?
python sauravmap.py src/ --callees my_func      # What does this function call?
python sauravmap.py src/ --orphans              # Unreachable functions
python sauravmap.py src/ --dot                  # Graphviz call graph
```

### Structural Code Query (`sauravquery`)

Search `.srv` codebases by AST patterns — find functions by signature, loops by depth, assignments by type, and more. Like `grep` but structure-aware.

```bash
python sauravquery.py "function * x y" src/     # Functions with 2 params named x, y
python sauravquery.py "while true" src/          # Infinite loops
python sauravquery.py "let * = map *" src/       # Map assignments
python sauravquery.py --unused-vars src/         # All unused variables
python sauravquery.py --json "for * in *" src/   # JSON output
```

### Maintenance Forecaster (`sauravforecast`)

Predicts which `.srv` files will need maintenance next by analyzing complexity trends, change frequency, bug density, and code age.

```bash
python sauravforecast.py src/                   # Forecast report
python sauravforecast.py src/ --json            # JSON output
python sauravforecast.py src/ --top 10          # Top 10 at-risk files
```

---

## Debugging & Tracing

### Execution Tracer (`sauravtrace`)

Records every statement execution, function call, and variable change, producing a step-by-step trace log. Invaluable for understanding complex control flow.

```bash
python sauravtrace.py program.srv               # Full trace to stdout
python sauravtrace.py program.srv -o trace.log  # Write to file
python sauravtrace.py program.srv --calls-only  # Only function calls
python sauravtrace.py program.srv --vars        # Include variable snapshots
python sauravtrace.py program.srv --json        # JSON trace
python sauravtrace.py program.srv --max 1000    # Limit trace length
```

### Interactive Debugger (`sauravdbg`)

Step-through debugger with breakpoints, variable inspection, and call stack navigation. Alternative to `sauravdb` with different UI.

```bash
python sauravdbg.py program.srv                 # Start debugging
```

### Time-Travel Debugger (`sauravchrono`)

Records full execution snapshots at every step, enabling forward and backward navigation through program history. Find bugs by rewinding to the exact moment things went wrong.

```bash
python sauravchrono.py program.srv              # Record and replay
python sauravchrono.py program.srv --replay     # Replay saved session
python sauravchrono.py program.srv --json       # JSON timeline
```

### Code Explainer (`sauravexplain`)

Parses a `.srv` file and generates a human-readable, line-by-line explanation of what the code does. Great for code review and learning.

```bash
python sauravexplain.py program.srv             # Explain to stdout
python sauravexplain.py program.srv --verbose   # Detailed explanations
python sauravexplain.py program.srv -o explain.md  # Write markdown
```

---

## Refactoring & Migration

### Automated Refactoring (`sauravrefactor`)

Safe, AST-aware code transformations: rename variables/functions across scopes, extract functions, inline variables, and more.

```bash
python sauravrefactor.py rename old_name new_name file.srv
python sauravrefactor.py extract new_func 10-20 file.srv   # Extract lines 10-20 into function
python sauravrefactor.py inline var_name file.srv           # Inline a variable
python sauravrefactor.py --dry-run rename x y file.srv      # Preview only
```

### Adaptive Optimizer (`sauravadapt`)

Analyzes `.srv` source and applies optimization transformations: constant folding, dead code elimination, loop unrolling, and more.

```bash
python sauravadapt.py program.srv               # Show suggested optimizations
python sauravadapt.py program.srv --apply       # Apply in-place
python sauravadapt.py program.srv --diff        # Show diff
python sauravadapt.py program.srv --json        # JSON output
```

### Python-to-Sauravcode Migrator (`sauravmigrate`)

Converts simple Python scripts into idiomatic sauravcode by parsing Python AST and generating equivalent `.srv` code.

```bash
python sauravmigrate.py script.py               # Convert to stdout
python sauravmigrate.py script.py -o script.srv # Write to file
python sauravmigrate.py src/ -o converted/      # Batch convert directory
```

### Self-Healing Runtime (`sauravheal`)

Runs `.srv` programs and when they fail, automatically diagnoses the error, generates a fix, and retries. Learns from failures to prevent recurrence.

```bash
python sauravheal.py program.srv                # Run with auto-healing
python sauravheal.py program.srv --max-retries 3  # Retry limit
python sauravheal.py program.srv --verbose      # Show diagnosis process
```

### Code Transformation Agent (`sauravagent`)

An intelligent agent that takes a natural-language goal and autonomously transforms `.srv` code to achieve it. Combines analysis, refactoring, and testing.

```bash
python sauravagent.py "optimize for performance" program.srv
python sauravagent.py "add error handling" program.srv
python sauravagent.py "make thread-safe" program.srv --dry-run
```

---

## Code Transformation

### Source Minifier (`sauravmin`)

Compresses `.srv` files for distribution: strips comments, collapses blank lines, removes trailing whitespace, and optionally shortens identifiers.

```bash
python sauravmin.py program.srv                 # Minified output to stdout
python sauravmin.py program.srv -o program.min.srv  # Write to file
python sauravmin.py program.srv --mangle        # Also shorten identifiers
python sauravmin.py program.srv --stats         # Show compression ratio
```

### Source Obfuscator (`sauravobf`)

Renames user-defined variables and functions to short, meaningless identifiers to protect source code from casual inspection.

```bash
python sauravobf.py program.srv                 # Obfuscated output to stdout
python sauravobf.py program.srv -o obfuscated.srv  # Write to file
python sauravobf.py program.srv --preserve "main,init"  # Keep some names
```

### Transpiler to Python (`sauravtranspile`)

Converts `.srv` source files into clean, idiomatic Python 3 code. Enables sauravcode prototypes to be deployed as Python scripts.

```bash
python sauravtranspile.py program.srv           # Python output to stdout
python sauravtranspile.py program.srv -o program.py  # Write to file
python sauravtranspile.py src/ -o python_src/   # Batch convert
```

### Code Alchemy (`sauravalchemy`)

Analyzes `.srv` programs and generates equivalent implementations in different programming paradigms or styles (functional, imperative, recursive, iterative).

```bash
python sauravalchemy.py program.srv --style functional
python sauravalchemy.py program.srv --style imperative
python sauravalchemy.py program.srv --json
```

### Module Bundler (`sauravbundle`)

Bundles multiple `.srv` files into a single distributable file. Resolves all imports recursively, performs topological sorting, and concatenates into one self-contained script.

```bash
python sauravbundle.py main.srv                 # Bundle to stdout
python sauravbundle.py main.srv -o bundle.srv   # Write to file
python sauravbundle.py main.srv --tree          # Show dependency tree
```

---

## CI & Deployment

### Local CI Runner (`sauravci`)

Orchestrates lint, type-check, test, metrics, and security scans in one command — a full CI pipeline locally.

```bash
python sauravci.py                              # Run all checks
python sauravci.py --skip lint                  # Skip linting step
python sauravci.py --only test,lint             # Run specific stages
python sauravci.py --json                       # JSON results
python sauravci.py --fail-fast                  # Stop on first failure
```

### REST API Server (`sauravapi`)

Loads a `.srv` file and exposes every top-level function as a POST endpoint. Instant API from any sauravcode module.

```bash
python sauravapi.py math_utils.srv              # Serve on http://localhost:8472
python sauravapi.py math_utils.srv --port 9000  # Custom port
python sauravapi.py math_utils.srv --docs       # Auto-generate API docs page
```

**Example:** If `math_utils.srv` defines `function add x y`, you get:
```bash
curl -X POST localhost:8472/add -d '{"args": [3, 5]}'
# → {"result": 8}
```

### Pipeline Runner (`sauravpipe`)

Define multi-stage pipelines that pass data between sauravcode scripts, with parallel execution, error handling, and retry logic.

```bash
python sauravpipe.py pipeline.json              # Run pipeline from config
python sauravpipe.py --dry-run pipeline.json    # Preview execution plan
python sauravpipe.py --verbose pipeline.json    # Detailed stage logging
```

### Version Manager (`sauravver`)

Manages semantic versioning, generates changelogs from git commits, and creates release tags.

```bash
python sauravver.py bump patch                  # 1.0.0 → 1.0.1
python sauravver.py bump minor                  # 1.0.0 → 1.1.0
python sauravver.py bump major                  # 1.0.0 → 2.0.0
python sauravver.py changelog                   # Generate changelog
python sauravver.py tag                         # Create git tag
python sauravver.py current                     # Show current version
```

### HTML Exporter (`sauravshare`)

Creates self-contained HTML pages with syntax-highlighted code and output for sharing sauravcode programs.

```bash
python sauravshare.py program.srv               # Generate HTML to stdout
python sauravshare.py program.srv -o share.html # Write to file
python sauravshare.py program.srv --run         # Include execution output
python sauravshare.py program.srv --dark        # Dark theme
```

### Python Embedding (`sauravembed`)

A clean API for running `.srv` code inside Python programs. Pass data in, get results out — use sauravcode as a scripting engine.

```python
from sauravembed import SauravRuntime
rt = SauravRuntime()
result = rt.run_file("math.srv", {"x": 10})
value = rt.call("add", 3, 5)
```

```bash
python sauravembed.py program.srv               # Quick run via CLI
python sauravembed.py program.srv --args '{"x": 5}'  # Pass arguments
```

---

## Learning & Practice

### Interactive Lessons (`sauravlearn`)

Learn sauravcode through progressive lessons with explanations, examples, and exercises. Covers basics through advanced features.

```bash
python sauravlearn.py                           # Start from lesson 1
python sauravlearn.py --list                    # List all lessons
python sauravlearn.py --lesson 5               # Jump to lesson 5
python sauravlearn.py --topic "loops"           # Topic-based search
```

### Step-by-Step Tutorial (`sauravtutorial`)

In-terminal guided tutorial that teaches sauravcode concepts one at a time with interactive prompts and immediate feedback.

```bash
python sauravtutorial.py                        # Start tutorial
python sauravtutorial.py --chapter 3            # Jump to chapter
python sauravtutorial.py --list                 # List chapters
```

### Coding Challenges (`sauravchallenge`)

Built-in set of programming challenges with automated verification. Test your sauravcode skills at various difficulty levels.

```bash
python sauravchallenge.py                       # Random challenge
python sauravchallenge.py --list                # List all challenges
python sauravchallenge.py --difficulty hard      # Filter by difficulty
python sauravchallenge.py --verify solution.srv  # Check your solution
```

### Coding Katas (`sauravkata`)

Progressive practice problems with automated testing and hints. Build muscle memory for common programming patterns.

```bash
python sauravkata.py                            # Next kata in sequence
python sauravkata.py --list                     # List all katas
python sauravkata.py --hint                     # Get a hint
python sauravkata.py --verify solution.srv      # Check your solution
```

### Coding Quests (`sauravquest`)

RPG-style coding adventure: solve progressively harder sauravcode puzzles to level up, unlock new abilities, and defeat coding bosses.

```bash
python sauravquest.py                           # Start adventure
python sauravquest.py --status                  # View progress
python sauravquest.py --leaderboard             # Rankings
```

### Code Golf (`sauravgolf`)

Solve programming puzzles in the fewest characters possible. Compete against built-in par scores.

```bash
python sauravgolf.py                            # Random golf challenge
python sauravgolf.py --list                     # List all holes
python sauravgolf.py --verify solution.srv      # Score your solution
python sauravgolf.py --leaderboard              # Best scores
```

### Code Duels (`sauravduel`)

Head-to-head comparison of two `.srv` solutions: correctness, performance, readability, and code quality scores.

```bash
python sauravduel.py solution_a.srv solution_b.srv
python sauravduel.py a.srv b.srv --challenge "sort"  # Specific challenge
python sauravduel.py a.srv b.srv --json              # JSON results
```

### Code Review Mentor (`sauravmentor`)

Analyzes `.srv` source files for code quality, detects anti-patterns, and provides actionable improvement suggestions like a senior developer would.

```bash
python sauravmentor.py program.srv              # Full review
python sauravmentor.py program.srv --severity high  # Only serious issues
python sauravmentor.py program.srv --json       # JSON output
python sauravmentor.py src/                     # Review entire directory
```

---

## Creative & Fun

### Turtle Graphics (`sauravcanvas`)

Write `.srv` programs using turtle-like drawing commands and generate SVG or PNG output. Great for learning and creative coding.

```bash
python sauravcanvas.py drawing.srv              # Render to terminal
python sauravcanvas.py drawing.srv --svg out.svg   # SVG output
python sauravcanvas.py drawing.srv --png out.png   # PNG output
```

### ASCII Plotting (`sauravplot`)

Create bar charts, line charts, scatter plots, and histograms right in the terminal from `.srv` data.

```bash
python sauravplot.py data.srv                   # Auto-detect chart type
python sauravplot.py data.srv --type bar        # Force bar chart
python sauravplot.py data.srv --type scatter    # Scatter plot
python sauravplot.py data.srv --width 60        # Custom terminal width
```

### Matrix Calculator (`sauravmatrix`)

Full-featured matrix calculator with REPL interface: create, multiply, transpose, invert, and decompose matrices interactively.

```bash
python sauravmatrix.py                          # Interactive REPL
python sauravmatrix.py --eval "[[1,2],[3,4]] * [[5,6],[7,8]]"
python sauravmatrix.py script.srv               # Run matrix script
```

### Cipher Workbench (`sauravcipher`)

Encrypt, decrypt, analyze, and crack classical ciphers interactively. Uses the same cipher builtins available in `.srv` files.

```bash
python sauravcipher.py                          # Interactive mode
python sauravcipher.py --encrypt caesar "hello" 3
python sauravcipher.py --crack "KHOOR"          # Auto-detect and crack
python sauravcipher.py --analyze ciphertext.txt # Frequency analysis
```

### Genetic Programming (`sauravevolve`)

Autonomously evolves `.srv` programs toward passing user-defined test cases using genetic algorithms. Starts with random programs and breeds them toward correctness.

```bash
python sauravevolve.py --target tests/target.srv  # Evolve toward test suite
python sauravevolve.py --generations 100          # Generation limit
python sauravevolve.py --population 50            # Population size
python sauravevolve.py --verbose                  # Show evolution progress
```

---

## Utilities

### Terminal Cheat Sheet (`sauravcheat`)

Quickly look up syntax, built-ins, and idioms without leaving the terminal.

```bash
python sauravcheat.py                           # Full cheat sheet
python sauravcheat.py loops                     # Topic: loops
python sauravcheat.py map filter reduce         # Topic: higher-order functions
python sauravcheat.py --search "sort"           # Search all topics
```

### Syntax Highlighter (`sauravhl`)

Outputs beautifully colored source code in ANSI terminal format or HTML.

```bash
python sauravhl.py program.srv                  # ANSI colored output
python sauravhl.py program.srv --html           # HTML output
python sauravhl.py program.srv --theme dark     # Theme selection
python sauravhl.py program.srv --lines          # Include line numbers
```

### Regex Tester (`sauravregex`)

Interactive regex tester and debugger. Test patterns against input strings with match highlighting and group extraction.

```bash
python sauravregex.py                           # Interactive mode
python sauravregex.py --pattern "\d+" --input "abc123def456"
python sauravregex.py --explain "\d{3}-\d{4}"   # Explain pattern
```

### Snippet Manager (`sauravsnippet`)

Save, search, tag, and reuse `.srv` code snippets from a local library.

```bash
python sauravsnippet.py save "binary search" search.srv
python sauravsnippet.py find "sort"             # Search snippets
python sauravsnippet.py list                    # List all snippets
python sauravsnippet.py tags                    # List all tags
python sauravsnippet.py get "binary search"     # Retrieve snippet
```

### TODO Tracker (`sauravtodo`)

Scans `.srv` source files for tagged comments (TODO, FIXME, HACK, NOTE, XXX) and reports them with file locations and context.

```bash
python sauravtodo.py src/                       # Scan directory
python sauravtodo.py src/ --tag FIXME           # Filter by tag
python sauravtodo.py src/ --json                # JSON output
python sauravtodo.py src/ --sort priority       # Sort by urgency
```

### Control Flow Diagrams (`sauravflow`)

Parse `.srv` source into a control flow graph (CFG) and render as Mermaid flowchart, Graphviz DOT, or plain text.

```bash
python sauravflow.py program.srv                # Text CFG
python sauravflow.py program.srv --mermaid      # Mermaid markdown
python sauravflow.py program.srv --dot          # Graphviz DOT
python sauravflow.py program.srv --function fib # CFG for specific function
```

### Project Scaffolding (`sauravscaffold`)

Quickly create new sauravcode projects from built-in or custom templates.

```bash
python sauravscaffold.py new myproject          # New project from template
python sauravscaffold.py list                   # List available templates
python sauravscaffold.py new myproject --template cli  # Specific template
```

### Grammar-Aware Fuzzer (`sauravfuzz`)

Generates random syntactically valid-ish sauravcode programs and runs them to find crashes, hangs, and unexpected behaviour.

```bash
python sauravfuzz.py                            # Run fuzzer (default 100 programs)
python sauravfuzz.py -n 1000                    # Generate 1000 programs
python sauravfuzz.py --timeout 5                # Per-program timeout
python sauravfuzz.py --seed 42                  # Reproducible fuzzing
python sauravfuzz.py --save-crashes crashes/    # Save crashing inputs
```

### Bug Bounty Hunter (`sauravbounty`)

Autonomous bug finder: scans `.srv` source files for potential bugs using static analysis patterns, type inference, and heuristics.

```bash
python sauravbounty.py src/                     # Hunt for bugs
python sauravbounty.py src/ --json              # JSON output
python sauravbounty.py src/ --severity high     # Critical bugs only
```

### Intent Inference (`sauravintent`)

Analyzes `.srv` source code and infers programmer intent from naming conventions, patterns, and structure. Useful for documentation generation and code review.

```bash
python sauravintent.py program.srv              # Infer intent
python sauravintent.py program.srv --verbose    # Detailed analysis
```

### Reactive Programming Engine (`sauravreflex`)

Analyzes `.srv` programs for reactive patterns and provides an interactive environment for reactive programming experiments.

```bash
python sauravreflex.py program.srv              # Analyze reactive patterns
python sauravreflex.py --interactive            # Interactive mode
```

### Text Utilities (`sauravtext`)

Shared text-processing utilities used by other sauravcode tools. Not typically called directly, but available for custom tooling integration.
