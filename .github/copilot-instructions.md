# Copilot Instructions for sauravcode

These notes orient GitHub Copilot coding agents (Claude, Codex, etc.)
and any new human contributors. Keep them short, accurate, and
checked-in. Update when conventions change.

## Project Overview

**sauravcode** is a custom programming language with intentionally
minimal syntax — no parentheses for function calls, no commas, no
semicolons, no braces. The repo ships two independent front ends
plus a large family of tooling scripts:

- **`saurav.py`** — Tree-walk interpreter that evaluates `.srv` files
  directly (and powers the REPL).
- **`sauravcc.py`** — Compiler that translates `.srv` → C → native
  executable via `gcc`.

Both implement the same language but have separate tokenizers /
parsers. **Any language change MUST be applied to both.**

## Repository Layout

```
saurav.py                # Interpreter (canonical reference)
sauravcc.py              # Compiler (.srv → C → native)
sauravapi.py             # REST API server wrapping the interpreter
sauravsnap.py            # Snapshot testing harness
sauravcanvas.py          # Turtle / canvas graphics runtime
sauravcheat.py           # Cheat-sheet generator
sauravpipe.py            # Pipeline runner
sauravcc, sauravarchitect, sauravbench, sauravchange, ...
                         # Senior-tier tools (refactor, bench, audit,
                         # debug, doctor, etc.) — see file headers.
sauravcode/__init__.py   # PyPI package (re-exports version)
sauravcode/cli.py        # Console-script entry points (delegate to
                         # the top-level saurav*.py scripts).
*.srv                    # Demo / regression programs
test_*.srv               # Language-level smoke tests
tests/                   # Pytest suite (Python harnesses)
test_*.py                # Additional pytest modules at repo root
docs/                    # LANGUAGE.md, ARCHITECTURE.md, etc.
demos/                   # Larger example programs
editors/                 # Editor integrations
.github/workflows/       # CI: ci, codeql, docker, pages, publish, ...
.github/copilot-setup-steps.yml
                         # Reproducible bootstrap workflow — mirror of
                         # the CI environment for coding agents.
```

## Architecture

### Interpreter (`saurav.py`)
1. **Tokenizer** — regex-based; emits `INDENT` / `DEDENT` tokens.
2. **Parser** — recursive descent; produces AST nodes
   (`AssignmentNode`, `FunctionDef`, `IfNode`, …).
3. **Evaluator** — walks the AST with scoped environments.

### Compiler (`sauravcc.py`)
1. **Tokenizer** — same regex approach as the interpreter.
2. **Parser** — recursive descent with operator precedence.
3. **C Code Generator** — emits portable C99:
   - `SrvList` struct → dynamic arrays with bounds checking
   - `setjmp` / `longjmp` for try / catch
   - C structs for user-defined classes
   - Tagged unions / type inference for polymorphic `print`
4. **gcc invocation** — links to a native binary next to the `.srv`.

### Key Design Decisions
- Indentation-based blocks via `INDENT` / `DEDENT` tokens (Python-style).
- **Expression-as-argument ambiguity**: `f n - 1` parses as `f(n) - 1`.
  Use `f (n - 1)` for nested calls.
- Dynamic typing in the interpreter; the compiler infers, defaulting
  to `double` for numbers and `SrvList*` for lists.
- Lists are dynamic arrays (`realloc`-based) in compiled output.

## Language Syntax

```
function add x y
    return x + y

x = add 3 5          # No parens, no commas
print x               # 8

nums = [10, 20, 30]   # Lists use commas + brackets
append nums 40
print len nums         # 4

for i 1 6              # Range-based for
    print i

if x > 5
    print "big"
else
    print "small"
```

Keywords: `function`, `return`, `class`, `if`, `else if`, `else`,
`for`, `while`, `try`, `catch`, `print`, `true`, `false`, `and`, `or`,
`not`, `append`, `len`, `self`.

## How to Build & Test

The reproducible bootstrap lives in `.github/copilot-setup-steps.yml`
— run it (or read it) for the canonical recipe. Locally:

```bash
# 1. Install the package and dev tooling
pip install -e .
pip install pytest pytest-cov ruff

# 2. Run the interpreter and compiler smoke tests
python saurav.py hello.srv
python saurav.py a.srv
python sauravcc.py hello.srv          # produces ./hello
python sauravcc.py test_all.srv        # full feature regression

# 3. Run the Python test suite
pytest tests/ -q

# 4. Lint (CI gate)
ruff check .
ruff format --check .
```

Both interpreter and compiler should produce identical output for the
shared `.srv` files. If they diverge, that is a bug — fix the side
that disagrees with the language spec in `docs/LANGUAGE.md`.

## CI Expectations

- **`.github/workflows/ci.yml`** runs `ruff check` + `ruff format`,
  then pytest on Python 3.9, 3.10, 3.11, 3.12, 3.13.
- Coverage is uploaded to Codecov on the 3.13 leg only.
- `[tool.coverage.report]` has `fail_under = 70`; PRs that drop
  coverage below 70 % will fail.
- `[tool.ruff]` targets `py39` with line length 120 and selects
  `E, F, W, I, UP, B, SIM`. Match that style.
- `.github/workflows/codeql.yml` and `scorecard.yml` run security
  checks; do not introduce `eval` / shell-string concatenation in
  fresh code.

## Conventions

- Source files: `.srv` extension.
- 4-space indentation everywhere (tabs are normalized to 4 spaces
  inside the tokenizer; for Python use ruff's formatter).
- New language features need: (a) a `.srv` regression in
  `test_all.srv`, (b) a pytest unit test under `tests/`, and (c)
  identical behaviour from interpreter and compiler.
- Public CLI entry points live in `sauravcode/cli.py` — add a thin
  wrapper there and register it under `[project.scripts]` in
  `pyproject.toml` rather than asking users to invoke
  `python sauravsomething.py` directly.

## Common Pitfalls

1. **Tokenizer ordering matters** — `==` must be matched before `=`,
   `<=` before `<`, etc.
2. **INDENT/DEDENT generation** — track the indent stack correctly;
   off-by-one errors here cascade into the parser.
3. **Function call ambiguity** — `f a + b` means `f(a) + b`, not
   `f(a + b)`. Update both `docs/LANGUAGE.md` and the tests if you
   ever change this rule.
4. **Compiler C output** — must compile with stock `gcc` (C99+).
   Avoid GNU extensions unless guarded.
5. **Both paths must agree** — language changes always touch both
   `saurav.py` and `sauravcc.py`.
6. **No network in tests** — pytest must stay hermetic; the API
   server tests stub out sockets.
