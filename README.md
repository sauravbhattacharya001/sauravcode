# sauravcode

Frustrated by syntax-heavy languages, I designed *sauravcode* for simplicity and clarity. It removes unnecessary punctuation and rigid conventions, focusing purely on logic. No parentheses for function calls, no commas between arguments, no semicolons, no braces — just clean, readable code.

**Home page:** https://sites.google.com/view/sauravcode

## Quick Start

```
# Interpreter
python saurav.py hello.srv

# Compiler (compiles to C, then to native executable via gcc)
python sauravcc.py hello.srv
```

## Language Features

### Functions
No parentheses, no commas — just the function name and arguments:
```
function add x y
    return x + y

function greet name
    print "hello"
    print name

add 3 5          # prints 8
greet "world"    # prints hello, then world
```

### Variables & Assignment
```
x = 10
name = "sauravcode"
flag = true
```

### Arithmetic
All standard operators including modulo:
```
a = 10 + 3       # 13
b = 10 - 3       # 7
c = 10 * 3       # 30
d = 10 / 3       # 3.333...
e = 10 % 3       # 1
```

### Comparisons
```
==  !=  <  >  <=  >=
```

### Booleans & Logical Operators
```
x = true
y = false

if x and not y
    print "works"

if x or y
    print "at least one"
```

### If / Else If / Else
```
score = 85
if score >= 90
    print "A"
else if score >= 80
    print "B"
else if score >= 70
    print "C"
else
    print "below C"
```

### While Loops
```
i = 0
while i < 5
    print i
    i = i + 1
```

### For Loops (range-based)
```
for i 1 6
    print i    # prints 1 through 5
```

### Recursion
Use parentheses to disambiguate nested expressions in arguments:
```
function factorial n
    if n <= 1
        return 1
    return n * factorial (n - 1)

print factorial 10    # 3628800
```

```
function fib n
    if n <= 1
        return n
    return fib (n - 1) + fib (n - 2)

print fib 10    # 55
```

### Strings
```
name = "sauravcode"
print name
print "Hello from sauravcode!"
```

### Lists
```
nums = [10, 20, 30]
print nums[0]         # 10
print nums[2]         # 30
print len nums        # 3

append nums 40
print nums[3]         # 40
print len nums        # 4
```

### Parenthesized Expressions
Use parentheses for grouping and disambiguation:
```
result = (2 + 3) * (4 - 1)    # 15
```

### Negative Numbers
```
x = -42
print x    # -42
```

### Classes (basic)
```
class Point
    function init x y
        self.x = x
        self.y = y
```

### Try / Catch
```
try
    x = risky_operation
catch err
    print "something went wrong"
```

## Compiler

The compiler (`sauravcc.py`) compiles `.srv` files to C, then uses `gcc` to produce native executables.

```
# Compile and run
python sauravcc.py program.srv

# Emit C code only (inspect what's generated)
python sauravcc.py program.srv --emit-c

# Compile to a specific output name
python sauravcc.py program.srv -o myprogram

# Keep the intermediate .c file
python sauravcc.py program.srv --keep-c

# Verbose output
python sauravcc.py program.srv -v
```

### Compiler Features

| Feature | Status |
|---------|--------|
| Functions & recursion | ✅ |
| Variables & assignment | ✅ |
| Arithmetic (+, -, *, /, %) | ✅ |
| Comparisons (==, !=, <, >, <=, >=) | ✅ |
| Booleans (true, false) | ✅ |
| Logical operators (and, or, not) | ✅ |
| If / else if / else | ✅ |
| While loops | ✅ |
| For loops (range-based) | ✅ |
| Strings | ✅ |
| Lists (dynamic arrays) | ✅ |
| List operations (append, len, indexing) | ✅ |
| Parenthesized expressions | ✅ |
| Negative numbers | ✅ |
| Classes (struct generation) | ✅ |
| Try/catch (setjmp/longjmp) | ✅ |
| Print (auto-detects type) | ✅ |

### How It Works

1. **Tokenize** — source → tokens (indent-based blocks)
2. **Parse** — tokens → AST (abstract syntax tree)
3. **Generate** — AST → C source code
4. **Compile** — C → native executable via gcc

The compiler generates clean, readable C code. Lists are implemented as dynamic arrays with bounds checking. Try/catch maps to `setjmp`/`longjmp`.

## Requirements

- **Interpreter:** Python 3
- **Compiler:** Python 3 + gcc (MinGW on Windows)

## Example

`a.srv`:
```
function add x y
    return x + y

function sub x y
    return x - y

function fun f g
    ret = add f g
    res = sub g f
    return ret * res

fun 4 6      # (4+6) * (6-4) = 20
fun2 2.3 4.6
```

```
$ python sauravcc.py a.srv
20
15.87
```

## Documentation

- **[Language Reference](docs/LANGUAGE.md)** — Complete specification with EBNF grammar, all types, operators, and precedence rules
- **[Architecture Guide](docs/ARCHITECTURE.md)** — How the tokenizer, parser, interpreter, and compiler work under the hood
- **[Examples](docs/EXAMPLES.md)** — Annotated example programs covering all features
- **[Changelog](CHANGELOG.md)** — Version history and notable changes

## Philosophy

Code should read like thought. No ceremony, no noise — just logic.
