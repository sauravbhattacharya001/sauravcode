# Changelog

All notable changes to sauravcode will be documented in this file.

## [7.9.0] - 2026-04-30

### New Tools
- **sauravclone** — Autonomous code clone detector with AST-based structural comparison, DRY scoring (0–100), Type 1/2/3 clone classification, and refactoring suggestions
- **sauravfossil** — Code fossil record analyzer with 8 detection engines for dead functions, orphaned variables, vestigial branches, unreachable code, and evolutionary layer dating
- **sauravautopatch** — Self-healing engine with 10 bug detectors and 4 autonomy levels (scan → suggest → heal → heal-all) for autonomous patch generation and application

### Documentation
- Added `docs/autonomous-engineering.md` — comprehensive documentation for sauravclone, sauravfossil, and sauravautopatch with usage examples, engine references, and CI integration guide
- Updated site navigation with new Autonomous Engineering section

## [2.0.0] - 2026-02-14

### Compiler (sauravcc v2)
- **Full-featured compiler** (`sauravcc.py`) — Compiles `.srv` → C → native executable via gcc
- All language features supported: functions, recursion, lists, booleans, if/else if/else, while, for, classes, try/catch, strings, logical ops, modulo, parenthesized expressions
- Proper operator precedence with recursive descent parser
- Dynamic list runtime (SrvList) with bounds checking
- Try/catch via setjmp/longjmp in generated C code
- Class compilation to C structs with method dispatch
- CLI: `--emit-c`, `-o`, `--keep-c`, `--cc`, `-v` flags

### Documentation
- `docs/LANGUAGE.md` — Complete language reference with EBNF grammar
- `docs/ARCHITECTURE.md` — Compiler and interpreter architecture documentation
- `docs/EXAMPLES.md` — Annotated example programs
- GitHub Pages site with interactive documentation
- Professional README with badges, feature list, and usage examples
- `CHANGELOG.md` — This file

### DevOps
- CodeQL security scanning workflow
- Auto-labeler and stale bot workflows
- `.gitignore` for build artifacts

### Interpreter Improvements
- Reordered tokenizer: `EQ` before `ASSIGN` (fixes `==` parsing)
- Added `print`, string literals, division-by-zero error handling
- Replaced debug `print()` calls with `--debug` flag
- Refactored parser: proper AST nodes instead of codegen hacks

## [1.0.0] - 2025

### Features
- **Interpreter** (`saurav.py`) — Tree-walk interpreter for `.srv` files
- Functions with recursion
- Variables and assignment (dynamic typing)
- Arithmetic: `+`, `-`, `*`, `/`
- Basic control flow
- Nested function calls
