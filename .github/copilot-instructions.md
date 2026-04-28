# Copilot Instructions for sauravcode

## Project Overview

sauravcode is a custom programming language with minimal syntax — no parentheses for function calls, no commas in argument lists, no semicolons, no braces. The project has two main execution backends plus a comprehensive toolchain of 80+ Python modules.

## Core Components

### Interpreter (`saurav.py`, ~870 lines)
1. **Tokenizer** — regex-based, emits INDENT/DEDENT tokens for block structure
2. **Parser** — recursive descent, produces AST nodes (AssignmentNode, FunctionDef, IfNode, etc.)
3. **Evaluator** — walks the AST, maintains variable scopes and function definitions

### Compiler (`sauravcc.py`, ~1300 lines)
1. **Tokenizer** — same regex approach as interpreter
2. **Parser** — recursive descent with operator precedence for expressions
3. **C Code Generator** — emits C source with:
   - `SrvList` struct for dynamic arrays with bounds checking
   - `setjmp`/`longjmp` for try/catch
   - C structs for classes
   - Type-detecting `print` via tagged unions or type inference
4. **gcc invocation** — compiles generated C to native binary

## Toolchain Modules

### Analysis & Quality
| Module | Purpose |
|--------|---------|
| `sauravlint.py` | Static analysis linter (E001–E005 errors, W001–W011 warnings) |
| `sauravtype.py` | Type inference engine — detects mismatches without annotations |
| `sauravfmt.py` | Code formatter (indentation, whitespace, alignment) |
| `sauravcomplex.py` | Cyclomatic/cognitive complexity metrics |
| `sauravmetrics.py` | Code quality metrics (LOC, coupling, cohesion) |
| `sauravsec.py` | Security scanner — detects dangerous patterns in AST |
| `sauravguard.py` | Runtime guardian — infinite loops, memory, recursion depth |

### Testing & Coverage
| Module | Purpose |
|--------|---------|
| `sauravtest.py` | Test runner for `.srv` test files (test_ prefix convention) |
| `sauravcov.py` | Code coverage instrumentation |
| `sauravfuzz.py` | Fuzz testing — generates random programs to find crashes |
| `sauravbench.py` | Benchmarking harness |

### Code Intelligence
| Module | Purpose |
|--------|---------|
| `sauravast.py` | AST utilities — parse/dump/transform |
| `sauravflow.py` | Control-flow graph construction |
| `sauravdiff.py` | Semantic diff between `.srv` files |
| `sauravquery.py` | Query AST with pattern matching (grep for code) |
| `sauravrefactor.py` | Automated refactoring (rename, extract, inline) |
| `sauravexplain.py` | Code explanation engine |
| `sauravdiagnose.py` | Error diagnosis with suggestions |
| `sauravdoc.py` | Documentation generator |

### Development Tools
| Module | Purpose |
|--------|---------|
| `sauravdbg.py` | Interactive debugger |
| `sauravrepl.py` | REPL/interactive shell |
| `sauravprof.py` | Profiler (function-level timing) |
| `sauravtrace.py` | Execution tracer |
| `sauravwatch.py` | File watcher — re-runs on change |
| `sauravsnap.py` | Snapshot testing |

### Project Management
| Module | Purpose |
|--------|---------|
| `sauravpkg.py` | Package manager for sauravcode libraries |
| `sauravdeps.py` | Dependency analysis |
| `sauravbundle.py` | Bundler — combines multi-file projects |
| `sauravci.py` | CI config generator |
| `sauravmigrate.py` | Version migration tool |
| `sauravscaffold.py` | Project scaffolding |
| `sauravver.py` | Versioning utilities |

### Language Extensions
| Module | Purpose |
|--------|---------|
| `sauravtranspile.py` | Transpiler to other languages |
| `sauravmin.py` | Minifier |
| `sauravobf.py` | Obfuscator |
| `sauravembed.py` | Embedding engine (embed .srv in other programs) |
| `sauravpipe.py` | Pipe operator implementation |
| `sauravgen.py` | Code generator from templates |

### Educational & Fun
| Module | Purpose |
|--------|---------|
| `sauravlearn.py` | Interactive tutorials |
| `sauravmentor.py` | Code review mentor |
| `sauravchallenge.py` | Programming challenges |
| `sauravkata.py` | Code kata runner |
| `sauravduel.py` | Code golf / dueling |
| `sauravgolf.py` | Shortest solution finder |
| `sauravquest.py` | Gamified learning quests |

## Language Syntax

```srv
function add x y
    return x + y

x = add 3 5          # No parens, no commas
print x               # Prints 8

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

## How to Test

```bash
# Run interpreter tests (comprehensive .srv suite)
python saurav.py test_all.srv

# Run compiler tests
python sauravcc.py test_all.srv

# Run Python test suite (148+ unit/integration tests)
pytest tests/ -v --tb=short

# Run specific test module
pytest tests/test_interpreter.py -v

# Test individual .srv files
python saurav.py hello.srv
python sauravcc.py hello.srv

# Lint a .srv file
python sauravlint.py hello.srv

# Type-check a file
python sauravtype.py hello.srv --verbose

# Format check
python sauravfmt.py hello.srv
```

Both interpreter and compiler should produce identical output for all `.srv` files.

## Key Design Decisions

- **Indentation-based blocks** (Python-style) via INDENT/DEDENT tokens
- **Expression-as-argument ambiguity:** `f n - 1` parses as `f(n) - 1`, use `f (n - 1)` for nested
- **Dynamic typing** in interpreter; compiler infers or defaults to `double` for numbers
- **Lists** are dynamic arrays (realloc-based) in compiled output
- **Both paths must agree** — any language change needs updates to BOTH `saurav.py` and `sauravcc.py`

## Important Files

| File | Purpose |
|------|---------|
| `saurav.py` | Interpreter |
| `sauravcc.py` | Compiler |
| `sauravast.py` | Shared AST utilities |
| `sauravflow.py` | Control-flow graph |
| `test_all.srv` | Full feature test suite (.srv language tests) |
| `tests/` | Python pytest suite (148+ tests) |
| `hello.srv` | Hello world example |
| `a.srv` | Function composition example |
| `docs/LANGUAGE.md` | EBNF grammar and language spec |
| `docs/ARCHITECTURE.md` | Internal architecture docs |
| `pyproject.toml` | Project metadata and pytest config |

## Common Pitfalls

1. **Tokenizer ordering matters** — `==` must be matched before `=`, `<=` before `<`
2. **INDENT/DEDENT generation** — must track indent level stack correctly
3. **Function call ambiguity** — `f a + b` means `f(a) + b`, not `f(a + b)`
4. **Compiler C output** — generated C must compile with standard gcc (C99+)
5. **Both paths must agree** — any language change needs updates to BOTH `saurav.py` and `sauravcc.py`
6. **Test with both backends** — always verify `python saurav.py` AND `python sauravcc.py` produce the same output
7. **Run pytest** — `pytest tests/ -v` catches regressions in the toolchain modules
8. **Module imports** — many tool modules import from `saurav.py` (tokenizer/parser); changes there cascade

## Conventions

- Source files use `.srv` extension
- Keywords: `function`, `return`, `class`, `if`, `else if`, `else`, `for`, `while`, `try`, `catch`, `print`, `true`, `false`, `and`, `or`, `not`, `append`, `len`, `self`, `import`, `assert`, `throw`, `break`, `continue`, `match`, `case`
- Indentation is 4 spaces (tabs normalized to 4 spaces)
- Python modules follow `saurav*.py` naming convention
- Tests in `tests/` follow `test_*.py` naming (pytest discovers automatically)
- Each toolchain module is standalone — runnable via `python saurav<tool>.py [args]`
