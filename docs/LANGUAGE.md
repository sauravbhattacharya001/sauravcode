# Sauravcode Language Reference

> The complete specification of the sauravcode programming language.

## Table of Contents

- [Design Philosophy](#design-philosophy)
- [Source Files](#source-files)
- [Lexical Structure](#lexical-structure)
- [Types](#types)
- [Variables](#variables)
- [Operators](#operators)
- [Control Flow](#control-flow)
- [Functions](#functions)
- [Classes](#classes)
- [Lists](#lists)
- [Error Handling](#error-handling)
- [Built-in Functions](#built-in-functions)
- [Grammar (EBNF)](#grammar-ebnf)

---

## Design Philosophy

Sauravcode strips away syntactic noise to let you focus on logic:

- **No parentheses** for function calls — `add 3 5` instead of `add(3, 5)`
- **No commas** between arguments
- **No semicolons** to end statements
- **No braces** — indentation defines blocks (like Python)
- **No `def`/`func`/`fn`** — just `function`

The result is code that reads almost like pseudocode.

## Source Files

- Extension: `.srv`
- Encoding: UTF-8
- Line endings: LF or CRLF
- Indentation: spaces or tabs (tabs are normalized to 4 spaces)

## Lexical Structure

### Comments

Line comments start with `#`:

```
# This is a comment
x = 10  # inline comment
```

### Identifiers

Identifiers start with a letter or underscore, followed by letters, digits, or underscores:

```
my_var
_private
counter2
```

### Keywords

```
function  return  class  new  self
if  else if  else
for  while
try  catch
print  true  false
and  or  not
int  float  bool  string
list  set  map  stack  queue
append  len  pop  get
```

### Literals

| Type    | Examples                          |
|---------|-----------------------------------|
| Integer | `42`, `0`, `100`                  |
| Float   | `3.14`, `0.5`, `2.`              |
| String  | `"hello"`, `"it's a \"quote\""` |
| Boolean | `true`, `false`                   |
| List    | `[1, 2, 3]`, `["a", "b"]`       |

### Indentation

Blocks are defined by indentation level. An increase in indentation starts a new block; a decrease ends it:

```
function greet name
    print "Hello"      # indented = part of function body
    print name

print "outside"        # back to top level
```

## Types

Sauravcode is dynamically typed. Values carry their type at runtime.

| Type    | Description            | Example Values          |
|---------|------------------------|-------------------------|
| Number  | 64-bit floating point  | `42`, `3.14`, `-7`     |
| String  | Character sequence     | `"hello"`, `""`        |
| Boolean | Logical value          | `true`, `false`         |
| List    | Dynamic array          | `[1, 2, 3]`            |
| Object  | Class instance         | `new Point`             |

Optional type annotations (`int`, `float`, `bool`, `string`) are recognized by the parser but not enforced at runtime.

## Variables

### Declaration & Assignment

Variables are declared on first assignment. No `let`, `var`, or `const` needed:

```
x = 10
name = "sauravcode"
flag = true
pi = 3.14159
```

### Scope

- Variables inside a function are **local** to that call
- Top-level variables are **global**
- Function parameters shadow outer variables

## Operators

### Arithmetic

| Operator | Description    | Example       | Result |
|----------|---------------|---------------|--------|
| `+`      | Addition       | `10 + 3`      | `13`   |
| `-`      | Subtraction    | `10 - 3`      | `7`    |
| `*`      | Multiplication | `10 * 3`      | `30`   |
| `/`      | Division       | `10 / 3`      | `3.33` |
| `%`      | Modulo         | `10 % 3`      | `1`    |

### Comparison

| Operator | Description          |
|----------|----------------------|
| `==`     | Equal                |
| `!=`     | Not equal            |
| `<`      | Less than            |
| `>`      | Greater than         |
| `<=`     | Less than or equal   |
| `>=`     | Greater than or equal|

### Logical

| Operator | Description     | Example            |
|----------|----------------|--------------------|
| `and`    | Logical AND     | `x and y`          |
| `or`     | Logical OR      | `x or y`           |
| `not`    | Logical NOT     | `not x`            |

### Operator Precedence (highest to lowest)

1. `not` (unary)
2. `*`, `/`, `%`
3. `+`, `-`
4. `==`, `!=`, `<`, `>`, `<=`, `>=`
5. `and`
6. `or`

### Grouping

Use parentheses to override precedence:

```
result = (2 + 3) * (4 - 1)    # 15
```

## Control Flow

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
    print "F"
```

### While Loop

```
i = 0
while i < 10
    print i
    i = i + 1
```

### For Loop (Range-Based)

Iterates from `start` to `end - 1`:

```
for i 1 6
    print i    # prints 1, 2, 3, 4, 5
```

Syntax: `for <variable> <start> <end>`

## Functions

### Definition

```
function name param1 param2
    # body (indented)
    return expression
```

### Calling

No parentheses, no commas — just space-separated arguments:

```
function add x y
    return x + y

add 3 5          # returns 8
print add 3 5    # prints 8
```

### Recursion

Use parentheses to disambiguate nested calls in arguments:

```
function factorial n
    if n <= 1
        return 1
    return n * factorial (n - 1)

print factorial 10    # 3628800
```

Without parentheses, `factorial n - 1` would parse as `factorial(n) - 1` rather than `factorial(n - 1)`.

### Nested Calls

```
function square x
    return x * x

function sum_of_squares a b
    return square a + square b

print sum_of_squares 3 4    # 25
```

## Classes

### Definition

```
class Point
    function init x y
        self.x = x
        self.y = y

    function display
        print self.x
        print self.y
```

### Instantiation

```
p = new Point
p.init 10 20
p.display
```

### Field Access

```
print p.x    # dot notation
p.x = 42    # field assignment
```

## Lists

### Creation

```
nums = [10, 20, 30]
empty = []
mixed = [1, "two", true]
```

### Indexing

Zero-based indexing:

```
print nums[0]     # 10
print nums[2]     # 30
nums[1] = 99      # assignment
```

### Operations

| Operation        | Syntax              | Description                |
|-----------------|---------------------|----------------------------|
| Length           | `len list`          | Number of elements         |
| Append           | `append list value` | Add element to end         |
| Index access     | `list[i]`           | Get element at index       |
| Index assignment | `list[i] = val`     | Set element at index       |

### Example

```
nums = [10, 20, 30]
print len nums        # 3
append nums 40
print nums[3]         # 40
print len nums        # 4
```

## Error Handling

### Try / Catch

```
try
    x = risky_operation
catch err
    print "Error occurred"
    print err
```

The catch variable (`err`) receives the error message as a string.

**Compiler note:** Try/catch compiles to `setjmp`/`longjmp` in the generated C code.

## Built-in Functions

| Function          | Syntax                | Description                    |
|------------------|-----------------------|--------------------------------|
| `print`          | `print expr`          | Print value to stdout          |
| `len`            | `len list`            | Return list length             |
| `append`         | `append list value`   | Append value to list           |
| `pop`            | `pop list`            | Remove and return last element |
| `get`            | `get list index`      | Get element at index           |

## Grammar (EBNF)

```ebnf
program        = { statement } ;
statement      = function_def | class_def | if_stmt | while_stmt
               | for_stmt | try_stmt | return_stmt | print_stmt
               | assignment | append_stmt | expression_stmt ;

function_def   = "function" IDENT { IDENT } NEWLINE INDENT block DEDENT ;
class_def      = "class" IDENT NEWLINE INDENT { function_def } DEDENT ;

if_stmt        = "if" expression NEWLINE INDENT block DEDENT
                 { "else if" expression NEWLINE INDENT block DEDENT }
                 [ "else" NEWLINE INDENT block DEDENT ] ;
while_stmt     = "while" expression NEWLINE INDENT block DEDENT ;
for_stmt       = "for" IDENT term term NEWLINE INDENT block DEDENT ;
try_stmt       = "try" NEWLINE INDENT block DEDENT
                 "catch" [ IDENT ] NEWLINE INDENT block DEDENT ;

return_stmt    = "return" expression ;
print_stmt     = "print" expression ;
assignment     = IDENT "=" expression
               | IDENT "[" expression "]" "=" expression
               | IDENT "." IDENT "=" expression ;
append_stmt    = "append" IDENT expression ;

expression     = logical_or ;
logical_or     = logical_and { "or" logical_and } ;
logical_and    = comparison { "and" comparison } ;
comparison     = arith_expr [ comp_op arith_expr ] ;
arith_expr     = mul_expr { ("+" | "-") mul_expr } ;
mul_expr       = unary { ("*" | "/" | "%") unary } ;
unary          = "not" unary | "-" atom | atom ;
atom           = NUMBER | STRING | "true" | "false"
               | IDENT [ "[" expression "]" ]
               | IDENT { arg }
               | "len" atom
               | "new" IDENT
               | "(" expression ")"
               | "[" [ expression { "," expression } ] "]" ;

arg            = NUMBER | STRING | "true" | "false" | IDENT
               | "(" expression ")" | "[" ... "]" ;

comp_op        = "==" | "!=" | "<" | ">" | "<=" | ">=" ;
block          = { statement } ;
```

---

*This document describes sauravcode as implemented in the interpreter (`saurav.py`) and compiler (`sauravcc.py`). For examples, see the `.srv` files in the repository.*
