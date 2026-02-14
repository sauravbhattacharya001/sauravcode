<p align="center">
  <h1 align="center">sauravcode</h1>
  <p align="center">
    <strong>A programming language designed for clarity. No noise, just logic.</strong>
  </p>
  <p align="center">
    <a href="https://github.com/sauravbhattacharya001/sauravcode/actions/workflows/ci.yml"><img src="https://github.com/sauravbhattacharya001/sauravcode/actions/workflows/ci.yml/badge.svg" alt="Tests"></a>
    <a href="https://codecov.io/gh/sauravbhattacharya001/sauravcode"><img src="https://codecov.io/gh/sauravbhattacharya001/sauravcode/branch/main/graph/badge.svg" alt="Coverage"></a>
    <a href="https://github.com/sauravbhattacharya001/sauravcode/actions/workflows/codeql.yml"><img src="https://github.com/sauravbhattacharya001/sauravcode/actions/workflows/codeql.yml/badge.svg" alt="CodeQL"></a>
    <a href="https://github.com/sauravbhattacharya001/sauravcode/actions/workflows/pages.yml"><img src="https://github.com/sauravbhattacharya001/sauravcode/actions/workflows/pages.yml/badge.svg" alt="Pages"></a>
    <a href="https://github.com/sauravbhattacharya001/sauravcode/blob/main/LICENSE"><img src="https://img.shields.io/github/license/sauravbhattacharya001/sauravcode" alt="License"></a>
    <a href="https://github.com/sauravbhattacharya001/sauravcode"><img src="https://img.shields.io/github/languages/top/sauravbhattacharya001/sauravcode" alt="Language"></a>
    <a href="https://github.com/sauravbhattacharya001/sauravcode"><img src="https://img.shields.io/github/repo-size/sauravbhattacharya001/sauravcode" alt="Repo Size"></a>
    <a href="https://github.com/sauravbhattacharya001/sauravcode/releases"><img src="https://img.shields.io/github/v/release/sauravbhattacharya001/sauravcode" alt="Release"></a>
  </p>
</p>

---

**sauravcode** is a programming language that strips away the ceremony of traditional syntax. No parentheses for function calls. No commas between arguments. No semicolons. No braces. Just clean, readable code that flows like thought.

It comes with both an **interpreter** for rapid prototyping and a **compiler** that produces native executables via C code generation.

🌐 **[Documentation Site](https://sauravbhattacharya001.github.io/sauravcode/)** · 📖 **[Language Reference](docs/LANGUAGE.md)** · 🏗️ **[Architecture Guide](docs/ARCHITECTURE.md)**

---

## ✨ Features

- **Minimal syntax** — no parentheses, commas, semicolons, or braces
- **Dual execution** — interpreted (`saurav.py`) or compiled to native (`sauravcc.py`)
- **Functions & recursion** — with clean call syntax
- **Dynamic typing** — integers, floats, booleans, strings, lists
- **Control flow** — if/else if/else, while loops, range-based for loops
- **Classes** — with fields, methods, and `self`
- **Error handling** — try/catch blocks
- **Lists** — dynamic arrays with append, len, indexing
- **Logical operators** — `and`, `or`, `not`
- **Compiler generates readable C** — inspect with `--emit-c`

## 🚀 Quick Start

### Prerequisites

- **Python 3.6+**
- **gcc** (for compiler — MinGW on Windows, Xcode CLI on macOS)

### Run with the Interpreter

```bash
python saurav.py hello.srv
```

### Compile to Native Executable

```bash
python sauravcc.py hello.srv     # Compile and run
./hello                          # Run the binary directly
```

## 📝 Language at a Glance

### Hello World

```
print "Hello, World!"
```

### Functions

No parentheses, no commas — just the function name and its arguments:

```
function greet name
    print "Hello,"
    print name

greet "world"
```

### Variables & Arithmetic

```
x = 10
y = 3
print x + y      # 13
print x * y      # 30
print x % y      # 1
```

### Control Flow

```
score = 85
if score >= 90
    print "A"
else if score >= 80
    print "B"
else
    print "below B"
```

### Loops

```
# While
i = 0
while i < 5
    print i
    i = i + 1

# For (range-based)
for i 1 6
    print i        # prints 1 through 5
```

### Recursion

Use parentheses only when you need to disambiguate nested expressions:

```
function factorial n
    if n <= 1
        return 1
    return n * factorial (n - 1)

print factorial 10    # 3628800
```

### Lists

```
nums = [10, 20, 30]
print nums[0]          # 10
print len nums         # 3
append nums 40
print nums[3]          # 40
```

### Classes

```
class Point
    function init x y
        self.x = x
        self.y = y
```

### Error Handling

```
try
    x = risky_operation
catch err
    print "something went wrong"
```

## ⚙️ Compiler

The compiler (`sauravcc.py`) translates sauravcode to C, then uses gcc to produce native executables.

```bash
# Compile and run
python sauravcc.py program.srv

# Emit C code only (inspect the generated code)
python sauravcc.py program.srv --emit-c

# Compile to a specific output name
python sauravcc.py program.srv -o myprogram

# Keep the intermediate .c file
python sauravcc.py program.srv --keep-c

# Verbose output
python sauravcc.py program.srv -v
```

### Compilation Pipeline

```
┌──────────┐    ┌─────────┐    ┌──────────┐    ┌──────────┐    ┌────────────┐
│ .srv     │───▶│ Tokenize │───▶│  Parse   │───▶│ Generate │───▶│   gcc      │
│ source   │    │ (lexer)  │    │  (AST)   │    │  (C code)│    │ (native)   │
└──────────┘    └─────────┘    └──────────┘    └──────────┘    └────────────┘
```

### Supported Features

| Feature | Interpreter | Compiler |
|---------|:-----------:|:--------:|
| Functions & recursion | ✅ | ✅ |
| Variables & assignment | ✅ | ✅ |
| Arithmetic (+, -, *, /, %) | ✅ | ✅ |
| Comparisons (==, !=, <, >, <=, >=) | ✅ | ✅ |
| Booleans & logical ops | ✅ | ✅ |
| If / else if / else | ✅ | ✅ |
| While loops | ✅ | ✅ |
| For loops (range-based) | ✅ | ✅ |
| Strings | ✅ | ✅ |
| Lists (dynamic arrays) | ✅ | ✅ |
| Classes | ✅ | ✅ |
| Try / catch | ✅ | ✅ |
| Parenthesized expressions | ✅ | ✅ |
| Negative numbers | ✅ | ✅ |

## 🏗️ Architecture

The codebase has two execution paths sharing a common tokenizer design:

- **`saurav.py`** — Tree-walk interpreter. Tokenizes, parses to AST, evaluates directly.
- **`sauravcc.py`** — Compiler. Tokenizes, parses to AST, generates C source, invokes gcc.

The compiler generates clean, readable C. Lists become dynamic arrays (`SrvList`) with bounds checking. Try/catch maps to `setjmp`/`longjmp`. Classes compile to C structs with associated functions.

For the full deep-dive, see the [Architecture Guide](docs/ARCHITECTURE.md).

## 📂 Project Structure

```
sauravcode/
├── saurav.py           # Interpreter
├── sauravcc.py         # Compiler (.srv → C → native)
├── hello.srv           # Hello World example
├── a.srv               # Function composition example
├── test.srv            # Basic test
├── test_all.srv        # Comprehensive feature test
├── docs/
│   ├── LANGUAGE.md     # Language reference & EBNF grammar
│   ├── ARCHITECTURE.md # Compiler/interpreter internals
│   └── EXAMPLES.md     # Annotated examples
├── site/
│   └── index.html      # Documentation website
├── .github/
│   └── workflows/      # CI/CD (CodeQL, Pages)
├── CHANGELOG.md        # Version history
└── LICENSE             # MIT License
```

## 🧪 Running Tests

Run the comprehensive test suite:

```bash
# Interpreter
python saurav.py test_all.srv

# Compiler
python sauravcc.py test_all.srv
```

Both should produce identical output, covering all language features.

## 🎯 Design Philosophy

> Code should read like thought. No ceremony, no noise — just logic.

Traditional languages carry decades of syntactic baggage. Sauravcode asks: *what if we kept only what matters?*

- **Function calls without parentheses** — `add 3 5` instead of `add(3, 5)`
- **Indentation-based blocks** — no `{}` or `end` keywords
- **Minimal punctuation** — colons, semicolons, and most commas are gone
- **Disambiguation when needed** — parentheses are available for complex expressions

The result is code that reads almost like pseudocode but actually runs.

## 📖 Documentation

| Document | Description |
|----------|-------------|
| [Language Reference](docs/LANGUAGE.md) | Complete spec with EBNF grammar, types, operators, precedence |
| [Architecture Guide](docs/ARCHITECTURE.md) | How the tokenizer, parser, interpreter, and compiler work |
| [Examples](docs/EXAMPLES.md) | Annotated programs covering all features |
| [Changelog](CHANGELOG.md) | Version history and notable changes |
| [Website](https://sauravbhattacharya001.github.io/sauravcode/) | Interactive documentation |
| [Home Page](https://sites.google.com/view/sauravcode) | Project home |

## 🤝 Contributing

Contributions are welcome! Here's how to get started:

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/my-feature`)
3. **Make** your changes with tests
4. **Test** with both interpreter and compiler
5. **Submit** a pull request

### Ideas for Contributions

- Additional data structures (dictionaries, sets)
- Import/module system
- Standard library functions
- IDE/editor syntax highlighting
- REPL mode
- Optimization passes in the compiler

## 📄 License

This project is licensed under the [MIT License](LICENSE).

## 👤 Author

**Saurav Bhattacharya** — [GitHub](https://github.com/sauravbhattacharya001)
