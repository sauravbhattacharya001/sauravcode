# FAQ & Common Patterns

Common questions and idiomatic patterns for sauravcode.

---

## Syntax

### How do I call a function with nested calls?

Use parentheses to disambiguate when passing the result of one function to another:

```sauravcode
function double x
    return x * 2

function add x y
    return x + y

# Parentheses tell the parser where each argument ends
print add (double 3) (double 5)    # 16
```

Without parentheses, `add double 3 5` would be parsed as `add(double, 3, 5)`.

### How do I write multi-line expressions?

Sauravcode is line-oriented. Break complex logic into intermediate variables:

```sauravcode
# Instead of one giant expression, use let-bindings
let base = compute_score data
let adjusted = apply_weight base factor
let final = clamp adjusted 0 100
print final
```

### How do strings work?

Double quotes only. Use `+` for concatenation, `str` to convert numbers:

```sauravcode
let name = "World"
print "Hello, " + name + "!"

let count = 42
print "Found " + str count + " items"
```

---

## Functions & Closures

### Can I pass functions as arguments?

Yes — functions are first-class values:

```sauravcode
function apply_twice f x
    return f (f x)

function increment x
    return x + 1

print apply_twice increment 5    # 7
```

### Do lambdas capture variables?

Yes, lambdas form closures over their enclosing scope:

```sauravcode
function make_adder n
    return lambda x -> x + n

let add5 = make_adder 5
print add5 10    # 15
```

---

## Classes & Objects

### How do I create a class with methods?

```sauravcode
class Counter
    function init self start
        self.value = start

    function increment self
        self.value = self.value + 1

    function get self
        return self.value

let c = new Counter 0
c.increment
c.increment
print c.get    # 2
```

### Is there inheritance?

Not currently. Use composition — store objects as fields and delegate:

```sauravcode
class Logger
    function init self prefix
        self.prefix = prefix

    function log self msg
        print self.prefix + ": " + msg

class Service
    function init self name
        self.logger = new Logger name

    function run self
        self.logger.log "starting"
```

---

## Lists & Maps

### How do I iterate with an index?

Use `range` with `len`:

```sauravcode
let items = [10 20 30]
for i in range (len items)
    print str i + " -> " + str items[i]
```

### How do I filter a list?

Use a loop and `append`:

```sauravcode
let numbers = [1 2 3 4 5 6 7 8]
let evens = []
for n in numbers
    if n % 2 == 0
        append evens n
# evens = [2, 4, 6, 8]
```

Or use the built-in `filter` with a lambda:

```sauravcode
let evens = filter numbers lambda n -> n % 2 == 0
```

### How do maps (dictionaries) work?

```sauravcode
let config = {"host": "localhost" "port": 8080}
print config["host"]           # localhost
config["debug"] = true         # add a key
print keys config              # ["host", "port", "debug"]
```

---

## Error Handling

### How do I handle errors gracefully?

Use `try`/`catch` blocks:

```sauravcode
try
    let result = risky_operation data
    print result
catch e
    print "Error: " + str e
```

!!! warning "Compiler Note"
    In compiled mode (`sauravcc.py`), try/catch maps to `setjmp`/`longjmp`. Avoid deeply nested try/catch in performance-critical compiled code.

---

## Interpreter vs Compiler

### When should I interpret vs compile?

| Use Case | Interpreter (`saurav.py`) | Compiler (`sauravcc.py`) |
|----------|:------------------------:|:------------------------:|
| Prototyping & scripting | ✅ Recommended | Overkill |
| Numeric computation | Slower | ✅ ~10-50× faster |
| File I/O, JSON, regex | ✅ Full stdlib | Limited C mapping |
| Deployment | Needs Python | ✅ Standalone binary |
| Debugging | ✅ Better errors | Harder to trace |

### What features differ between interpreter and compiler?

The interpreter supports the full language. The compiler covers core features but some dynamic stdlib functions (HTTP, JSON parsing, advanced regex) require the interpreter. Check the [Compiler Guide](compiler.md) for the exact feature matrix.

---

## Troubleshooting

### `NameError: variable 'x' not defined`

Variables must be assigned before use. Check:

- Spelling (case-sensitive)
- Scope — variables inside `if`/`for`/`function` are block-scoped
- Order — define functions before calling them (no hoisting)

### `ParseError: unexpected indent`

Sauravcode uses 4-space indentation. Tabs are not allowed. Check your editor settings.

### Compiled binary crashes with segfault

Common causes:

1. **Array out of bounds** — the compiler generates bounds checks, but if disabled via flags this can segfault
2. **Deep recursion** — C stack is limited (~1MB default). Add `-O2` or increase stack size
3. **Null/uninitialized variable** — ensure all code paths assign before use

Run with the interpreter first to get readable error messages, then compile once logic is correct.
