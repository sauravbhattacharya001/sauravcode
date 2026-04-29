# Contributing to sauravcode

Thanks for your interest in contributing to sauravcode! Whether you're fixing a bug, adding a language feature, improving docs, or writing tests, every contribution helps.

## Getting Started

### Prerequisites

- **Python 3.9+** (for the interpreter and compiler)
- **gcc** (for the compiler to produce native executables)
- **pytest** and **pytest-cov** (for running tests)

### Setup

```bash
# Clone the repo
git clone https://github.com/sauravbhattacharya001/sauravcode.git
cd sauravcode

# Install test dependencies
pip install pytest pytest-cov

# Verify everything works
python -m pytest tests/ -v
```

### Project Structure

```
sauravcode/
├── saurav.py              # Tree-walk interpreter (core)
├── sauravcc.py            # Compiler (.srv → C → native executable)
├── sauravcode/            # Installable package (CLI entry points)
│   └── cli.py             # Entry points: sauravcode, sauravcode-compile, etc.
├── tests/                 # pytest test suite
│   ├── test_interpreter.py
│   ├── test_compiler.py
│   └── test_saurav*.py    # Tool-specific test files
├── docs/                  # MkDocs documentation source
├── editors/               # Editor integrations
├── demos/                 # Demo programs
├── *.srv                  # Example sauravcode programs
├── pyproject.toml         # Build config, pytest + coverage settings
├── .codecov.yml           # Codecov settings
├── Dockerfile             # Container build
├── CHANGELOG.md           # Release history
└── .github/workflows/     # CI/CD pipelines
```

### The Extended Toolchain

Beyond the interpreter and compiler, sauravcode includes a rich set of developer tools. Each is a standalone Python module:

| Module | Purpose |
|---|---|
| `sauravlint.py` | Linter — static analysis and style checks |
| `sauravfmt.py` | Formatter — auto-format `.srv` files |
| `sauravtest.py` | Test runner for `.srv` test files |
| `sauravdbg.py` | Interactive debugger |
| `sauravprof.py` | Profiler — execution timing |
| `sauravdoc.py` | Documentation generator |
| `sauravsec.py` | Security scanner |
| `sauravfuzz.py` | Fuzzer — random program generation + testing |
| `sauravrepl.py` | Interactive REPL |
| `sauravplay.py` | Playground / sandbox |
| `sauravast.py` | AST visualizer |
| `sauravapi.py` | REST API server |
| `sauravhl.py` | Syntax highlighter |
| `sauravflow.py` | Control flow analyzer |
| `sauravtype.py` | Type checker |
| `sauravrefactor.py` | Automated refactoring |
| `sauravquery.py` | Code search / query tool |
| `sauravwatch.py` | File watcher — auto-run on save |
| `sauravbench.py` | Benchmarking suite |
| `sauravcov.py` | Coverage analysis |
| `sauravmetrics.py` | Code metrics (complexity, etc.) |
| `sauravdeps.py` | Dependency analyzer |
| `sauravdiff.py` | AST-level diff tool |
| `sauravsnap.py` | Snapshot testing |
| `sauravsnippet.py` | Snippet manager |
| `sauravstats.py` | Codebase statistics |
| `sauravtodo.py` | TODO/FIXME tracker |
| `sauravtrace.py` | Execution tracer |
| `sauravmigrate.py` | Version migration tool |
| `sauravmin.py` | Minifier |
| `sauravobf.py` | Obfuscator |
| `sauravver.py` | Version manager |
| `sauravgen.py` | Code generator |
| `sauravexplain.py` | Code explainer (educational) |
| `sauravlearn.py` | Interactive tutorials |
| `sauravci.py` | CI helper utilities |
| `sauravdb.py` | Database integration |
| `sauravembed.py` | Embedding / integration tools |
| `sauravcomplex.py` | Complexity analysis |
| `sauravscaffold.py` | Project scaffolding |
| `sauravpkg.py` | Package manager |
| `sauravbundle.py` | Bundler |
| `sauravchallenge.py` | Coding challenges |
| `sauravnb.py` | Notebook support (`.srvnb`) |
| `sauravtranspile.py` | Transpiler to other languages |

When contributing to any tool module, look at related test files (`test_saurav*.py`) and follow existing patterns.

## Development with Docker

You can develop and test entirely inside Docker without installing anything locally:

```bash
# Build the image (runs tests during build)
docker build -t sauravcode .

# Run a script
docker run --rm sauravcode interpret examples/hello.srv

# Compile a script to native binary
docker run --rm sauravcode compile examples/hello.srv -o hello

# Interactive REPL
docker run --rm -it sauravcode repl

# Mount your local .srv files for testing
docker run --rm -v $(pwd):/work sauravcode interpret /work/my_script.srv
```

For iterative development, mount the source directory:

```bash
docker run --rm -it -v $(pwd):/app -w /app python:3.12-slim bash
pip install pytest pytest-cov
python -m pytest tests/ -v
```

## Editor Setup

### VS Code

The repo includes a VS Code extension for `.srv` file support:

1. Open `editors/vscode/` in VS Code
2. Press `F5` to launch the extension in a development host
3. Open any `.srv` file — you'll get syntax highlighting

Alternatively, symlink the extension into your VS Code extensions directory:

```bash
# Linux/macOS
ln -s $(pwd)/editors/vscode ~/.vscode/extensions/sauravcode

# Windows (PowerShell, run as admin)
New-Item -ItemType SymbolicLink -Path "$env:USERPROFILE\.vscode\extensions\sauravcode" -Target "$(Get-Location)\editors\vscode"
```

If you're adding new language constructs, update the TextMate grammar in `editors/vscode/` so syntax highlighting stays correct.

### GitHub Copilot / AI Coding Agents

The repo includes `.github/copilot-setup-steps.yml` and `.github/copilot-instructions.md` for AI coding agents. If you're using Copilot, Claude, or Codex in a PR workflow, these files help the agent understand the project's conventions and build steps.

## Architecture Deep Dive

The interpreter pipeline has three stages, each with clear boundaries:

```
.srv source → Tokenizer → [Token stream] → Parser → [AST] → Interpreter → output
                                                   ↘
                                              CCodeGenerator → .c source → gcc → binary
```

### AST Node Types

The parser produces these node types (defined in `saurav.py`). Understanding these is essential for any language feature work:

| Category | Nodes | Purpose |
|----------|-------|---------|
| **Literals** | `NumberNode`, `StringNode`, `BooleanNode`, `NullNode`, `ListNode`, `MapNode` | Constant values |
| **Expressions** | `BinaryOpNode`, `UnaryOpNode`, `ComparisonNode`, `LogicalNode` | Operators |
| **Variables** | `AssignNode`, `VarAccessNode`, `IndexAccessNode`, `SliceNode` | Binding and lookup |
| **Control Flow** | `IfNode`, `WhileNode`, `ForNode`, `ForEachNode`, `BreakNode`, `ContinueNode` | Branching and loops |
| **Functions** | `FunctionDefNode`, `ReturnNode`, `CallNode`, `LambdaNode` | Callable definitions |
| **Classes** | `ClassDefNode`, `MethodCallNode`, `PropertyAccessNode` | OOP support |
| **Error Handling** | `TryCatchNode`, `ThrowNode` | Exception flow |
| **I/O** | `PrintNode`, `InputNode`, `ImportNode` | Side effects |

When adding a new node type:
1. Define the dataclass/namedtuple in `saurav.py`
2. Add tokenizer support if new syntax is needed
3. Add parser production rule
4. Add `visit_*` method to `Interpreter`
5. Add `generate_*` method to `CCodeGenerator` in `sauravcc.py`
6. Write tests for both interpreter and compiler paths

### Adding a New Tool Module

If you're adding a new `saurav*.py` tool:

1. Create `sauravXYZ.py` in the project root
2. Use the same CLI pattern as existing tools (argparse with subcommands)
3. Add a test file `test_sauravXYZ.py` in `tests/` (or root, matching existing convention)
4. Register CLI entry points in `pyproject.toml` under `[project.scripts]` if it should be a standalone command
5. Update the toolchain table in this CONTRIBUTING.md
6. Add it to the CI matrix if it has special requirements

## How to Contribute

### 1. Find Something to Work On

- **Issues** — Check [open issues](https://github.com/sauravbhattacharya001/sauravcode/issues) for bugs or feature requests
- **Tests** — Increase coverage (currently ~85%). Look at `Missing` lines in coverage reports
- **Language features** — Propose new syntax via an issue first
- **Docs** — Improve examples, fix typos, or add tutorials

### 2. Create a Branch

```bash
git checkout -b feature/your-feature-name
```

Use descriptive branch names:
- `fix/division-by-zero-message`
- `feature/string-interpolation`
- `docs/add-list-examples`
- `test/compiler-edge-cases`

### 3. Make Your Changes

#### Working on the Interpreter (`saurav.py`)

The interpreter has three stages:
1. **Tokenizer** (`tokenize()`) — converts source code to tokens
2. **Parser** (`Parser` class) — builds an AST from tokens
3. **Interpreter** (`Interpreter` class) — walks the AST and executes

#### Working on the Compiler (`sauravcc.py`)

The compiler shares tokenizer and parser logic but adds:
4. **C Code Generator** (`CCodeGenerator`) — converts AST to C source
5. **Build step** — invokes gcc to produce a native binary

#### Key Design Principles

- **No semicolons, no parentheses, no commas** in sauravcode syntax
- Indentation-based blocks (like Python)
- Function arguments are space-separated: `add 3 5` not `add(3, 5)`
- Keep the language minimal and readable

### 4. Write Tests

Every change should include tests. We use **pytest** with organized test classes:

```python
# In tests/test_interpreter.py or tests/test_compiler.py

class TestYourFeature:
    def test_basic_case(self):
        output = run_code("your sauravcode here\n")
        assert output.strip() == "expected output"

    def test_error_case(self):
        with pytest.raises(RuntimeError, match="expected error"):
            run_code("bad code\n")
```

Run tests with coverage:

```bash
# Run all tests
python -m pytest tests/ -v

# Run with coverage report
python -m pytest tests/ --cov=. --cov-report=term-missing

# Run a specific test file
python -m pytest tests/test_interpreter.py -v

# Run a specific test
python -m pytest tests/test_interpreter.py::TestArithmetic::test_addition -v
```

**Coverage requirement:** Don't decrease the overall coverage percentage. New features should have corresponding tests.

### 5. Test with .srv Files

Create or update `.srv` example files to exercise your changes:

```
# my_feature.srv
function example x
    return x + 1

print example 5
```

Test with both interpreter and compiler:

```bash
# Interpreter
python saurav.py my_feature.srv

# Compiler
python sauravcc.py my_feature.srv
```

### 6. Submit a Pull Request

1. Push your branch: `git push origin feature/your-feature-name`
2. Open a PR against `main`
3. Describe what you changed and why
4. Reference any related issues (`Fixes #123`)
5. CI will run tests automatically — make sure they pass

## Development with the Package

sauravcode is also an installable Python package. For development:

```bash
# Install in editable mode (so changes are picked up immediately)
pip install -e .

# This provides CLI commands:
sauravcode hello.srv           # Run via interpreter
sauravcode-compile hello.srv   # Compile to native binary
sauravcode-snap hello.srv      # Snapshot testing
sauravcode-api                 # Start REST API server
```

When adding new CLI entry points, register them in `pyproject.toml` under `[project.scripts]` and implement in `sauravcode/cli.py`.

### Running the Full CI Locally

Before submitting a PR, replicate what CI does:

```bash
# Lint (if applicable)
python sauravlint.py your_file.srv

# Format check
python sauravfmt.py --check your_file.srv

# Full test suite with coverage
python -m pytest tests/ --cov=. --cov-report=term-missing

# Security scan
python sauravsec.py your_file.srv
```

## Code Style

- **Python**: Follow PEP 8 generally, but match existing patterns in the codebase
- **Naming**: `snake_case` for functions/variables, `PascalCase` for AST node classes
- **Comments**: Add them for non-obvious logic, especially in the parser and code generator
- **Keep it simple**: sauravcode values clarity — the implementation should too
- **Linting**: CI uses [ruff](https://docs.astral.sh/ruff/). Run `ruff check .` and `ruff format --check .` locally before pushing
- **Type hints**: Encouraged for new code, especially public APIs in tool modules

## Performance Contributions

The codebase includes profiling tools — use them when working on performance:

```bash
# Profile a script's execution
python sauravprof.py my_script.srv

# Measure complexity metrics
python sauravcomplex.py saurav.py

# Run benchmarks
python sauravbench.py
```

When submitting performance improvements:
1. Include **before/after** benchmark numbers in the PR description
2. Explain the algorithmic change (e.g., O(n²) → O(n log n))
3. Ensure no behavioral regressions — same inputs, same outputs
4. Test with large inputs where the improvement matters

## Reporting Bugs

Open an issue with:
1. **Sauravcode program** that triggers the bug (minimal reproducible example)
2. **Expected behavior** vs **actual behavior**
3. Whether it affects the interpreter, compiler, or both
4. Python version and OS

## Proposing Language Features

sauravcode is intentionally minimal. Before implementing a new language feature:

1. **Open an issue** describing the proposed syntax and semantics
2. Explain the **motivation** — what problem does it solve?
3. Show **example code** using the new feature
4. Wait for discussion before starting implementation

## License

By contributing, you agree that your contributions will be licensed under the same [MIT License](LICENSE) that covers the project.
