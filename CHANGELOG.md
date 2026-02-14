# Changelog

All notable changes to sauravcode will be documented in this file.

## [Unreleased]

### Added
- `docs/LANGUAGE.md` — Complete language reference with EBNF grammar
- `docs/ARCHITECTURE.md` — Compiler and interpreter architecture documentation
- `docs/EXAMPLES.md` — Annotated example programs
- `CHANGELOG.md` — This file

## [1.0.0] - 2025

### Features
- **Interpreter** (`saurav.py`) — Tree-walk interpreter for `.srv` files
- **Compiler** (`sauravcc.py`) — Compiles `.srv` → C → native executable via gcc
- Functions with recursion (parenthesized disambiguation)
- Variables and assignment (dynamic typing)
- Arithmetic: `+`, `-`, `*`, `/`, `%`
- Comparisons: `==`, `!=`, `<`, `>`, `<=`, `>=`
- Logical operators: `and`, `or`, `not`
- Control flow: `if` / `else if` / `else`, `while`, `for` (range-based)
- Strings with escape support
- Booleans (`true`, `false`)
- Lists with `append`, `len`, `pop`, indexing, and assignment
- Classes with fields and methods (`self`, `new`)
- Error handling (`try` / `catch`)
- Negative numbers and parenthesized expressions
- Compiler flags: `--emit-c`, `-o`, `--keep-c`, `-v`
