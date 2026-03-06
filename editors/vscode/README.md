# Sauravcode for Visual Studio Code

Syntax highlighting, code snippets, and language support for the [sauravcode](https://github.com/sauravbhattacharya001/sauravcode) programming language.

## Features

### Syntax Highlighting

Full TextMate grammar covering all sauravcode constructs:

- **Keywords** — `function`, `if`/`else if`/`else`, `while`, `for`/`in`, `class`, `enum`, `match`/`case`, `try`/`catch`/`throw`, `import`, `lambda`, `return`, `yield`, `break`/`continue`, `assert`
- **Built-in functions** — `print`, `append`, `len`, `pop`, `map`, `filter`, `reduce`, `sort`, `range`, `type_of`, regex functions, JSON functions, string functions, math functions (40+ builtins)
- **Types** — `int`, `float`, `bool`, `string`, `list`, `set`, `stack`, `queue`, `map`
- **Operators** — arithmetic (`+`, `-`, `*`, `/`, `%`), comparison (`==`, `!=`, `<`, `>`, `<=`, `>=`), logical (`and`, `or`, `not`), pipe (`|>`), arrow (`->`)
- **Strings** — double-quoted with escape sequences (`\n`, `\t`, `\r`, `\\`, `\"`, `\0`)
- **F-strings** — `f"Hello {name}!"` with embedded expression highlighting
- **Comments** — `# line comments`
- **Numbers** — integers and decimals

### Code Snippets

25 snippets for rapid sauravcode development:

| Prefix | Snippet |
|--------|---------|
| `fn` | Function definition |
| `fnr` | Function with return |
| `if` | If statement |
| `ife` | If-else |
| `ifei` | If-else if-else |
| `while` | While loop |
| `for` | For loop with range |
| `foreach` | For-each over list |
| `class` | Class with init and method |
| `try` | Try-catch block |
| `match` | Match-case expression |
| `enum` | Enum definition |
| `lam` | Lambda expression |
| `pr` | Print |
| `prf` | Print with f-string |
| `fs` | F-string literal |
| `pipe` | Pipe operator |
| `map` | Map literal |
| `list` | List literal |
| `imp` | Import module |
| `assert` | Assert with message |
| `gen` | Generator function |

### Language Configuration

- **Comments** — `#` line comments with toggle shortcut
- **Brackets** — auto-closing for `[]`, `()`, `{}`, `""`
- **Indentation** — auto-indent after `function`, `if`, `else`, `while`, `for`, `class`, `try`, `catch`, `match`, `case`, `lambda`
- **Folding** — indentation-based code folding

## Installation

### From Source (Development)

1. Clone the sauravcode repository:
   ```
   git clone https://github.com/sauravbhattacharya001/sauravcode.git
   ```

2. Copy or symlink the `editors/vscode` directory to your VS Code extensions folder:
   ```
   # Windows
   mklink /D "%USERPROFILE%\.vscode\extensions\sauravcode" "path\to\sauravcode\editors\vscode"

   # macOS / Linux
   ln -s path/to/sauravcode/editors/vscode ~/.vscode/extensions/sauravcode
   ```

3. Restart VS Code. Files with `.srv` extension will automatically get syntax highlighting.

### Manual VSIX Install

```bash
cd editors/vscode
npx @vscode/vsce package
code --install-extension sauravcode-1.0.0.vsix
```

## Example

```sauravcode
# Fibonacci sequence
function fib n
  if n <= 1
    return n
  return (fib n - 1) + (fib n - 2)

# Print first 10 Fibonacci numbers
for i in range 10
  print f"fib({i}) = {fib i}"

# List comprehension with pipe
numbers = [1 2 3 4 5]
doubled = numbers |> map (lambda x -> x * 2)
print doubled
```

## File Association

The extension associates with `.srv` files automatically. To manually set the language mode, use `Ctrl+K M` (or `Cmd+K M` on macOS) and select **Sauravcode**.
