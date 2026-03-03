# Security & Resource Limits

Sauravcode includes built-in guards to prevent denial-of-service attacks and
accidental resource exhaustion. These limits protect the host process when
running untrusted or user-supplied `.srv` programs.

## Resource Limits

| Guard | Default Limit | Configurable | Purpose |
|---|---|---|---|
| **Recursion depth** | 500 calls | `MAX_RECURSION_DEPTH` | Prevents stack overflow from infinite/deep recursion |
| **Loop iterations** | 10,000,000 | `MAX_LOOP_ITERATIONS` | Prevents infinite `while` and `for` loops |
| **Allocation size** | 10,000,000 elements | `MAX_ALLOC_SIZE` | Prevents memory exhaustion via large allocations |
| **Exponent limit** | 10,000 | `MAX_EXPONENT` | Prevents huge integer computation via `power` |

All limits are defined as constants at the top of `saurav.py` and can be
adjusted before instantiating the interpreter.

## What Each Guard Protects

### Recursion Depth (`MAX_RECURSION_DEPTH = 500`)

Limits the call stack depth for user-defined functions. Without this guard,
a program like:

```
function loop
    loop
loop
```

would exhaust the Python call stack and crash the host process.

**Error message:** `Maximum recursion depth (500) exceeded in function 'loop'`

### Loop Iterations (`MAX_LOOP_ITERATIONS = 10,000,000`)

Caps the number of iterations in any single `while` or `for` loop. Prevents:

```
while true
    x = 1
```

from running forever.

**Error message:** `Maximum loop iterations (10,000,000) exceeded`

### Allocation Size (`MAX_ALLOC_SIZE = 10,000,000`)

Prevents memory exhaustion from three operations:

1. **String repetition:** `"A" * 999999999` would try to allocate ~1 GB
2. **List repetition:** `[1] * 999999999` would allocate ~8 GB
3. **Range creation:** `range 999999999` would create a list with ~1 billion elements

All three are checked before the allocation happens, so the host process
is never at risk.

**Error messages:**
- `String repetition would create N characters, exceeding limit of 10,000,000`
- `List repetition would create N elements, exceeding limit of 10,000,000`
- `range would create N elements, exceeding limit of 10,000,000`

### Exponent Limit (`MAX_EXPONENT = 10,000`)

The `power` built-in guards against exponents that would produce astronomically
large integers. `power 2 1000000` would attempt to compute a number with
~300,000 digits, consuming significant CPU and memory.

**Error message:** `Exponent N exceeds maximum of 10,000`

## File I/O

The built-in file operations (`read_file`, `write_file`, `append_file`,
`file_exists`, `read_lines`) operate with the permissions of the host process.
There is no path sandboxing — a `.srv` program can read or write any file the
host user can access.

**Recommendation:** When running untrusted `.srv` code, consider:
- Running the interpreter in a container or sandbox
- Using OS-level file permissions to restrict access
- Running as a limited user account

## Import System

The `import` statement loads and executes `.srv` files relative to the
importing file's directory. Key safety features:

- **Circular import detection:** Tracks imported module paths and silently
  skips already-imported modules
- **Path normalization:** Uses `os.path.abspath()` for consistent tracking
- **Isolated scope:** Imported modules execute in a clean variable scope;
  only functions merge into the caller's namespace

However, there is no restriction on which `.srv` files can be imported —
any file accessible to the host process can be loaded.

## Adjusting Limits

To change limits for your use case, modify the constants at the top of
`saurav.py`:

```python
MAX_RECURSION_DEPTH = 500       # Increase for deeply recursive algorithms
MAX_LOOP_ITERATIONS = 10_000_000  # Increase for long-running computations
MAX_ALLOC_SIZE = 10_000_000     # Increase if you need large data structures
MAX_EXPONENT = 10_000           # Increase for number theory / crypto work
```

When embedding the interpreter in a server or multi-tenant environment,
consider lowering these limits and adding execution time limits at the
host level.
