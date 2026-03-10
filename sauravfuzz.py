#!/usr/bin/env python3
"""sauravfuzz — Grammar-aware fuzzer for finding sauravcode bugs.

Generates random syntactically valid-ish sauravcode programs and runs
them through the interpreter to find crashes, hangs, and unexpected
exceptions.

Two fuzzing strategies:
  - **Generative**: Build programs from a weighted grammar
  - **Mutation**: Mutate known-good programs from a seed corpus

Usage:
    python sauravfuzz.py                     # quick fuzz (100 programs)
    python sauravfuzz.py --iterations 1000   # extended fuzzing
    python sauravfuzz.py --seed 42           # reproducible run
    python sauravfuzz.py --min-crash         # minimize crash cases
    python sauravfuzz.py --mutate            # mutation-based fuzzing
    python sauravfuzz.py --report fuzz.json  # save report as JSON
    python sauravfuzz.py --timeout 2.0       # per-program timeout (sec)
    python sauravfuzz.py --depth 5           # max AST nesting depth
"""

from __future__ import annotations

import argparse
import io
import json
import os
import random
import re
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ── Ensure sauravcode modules are importable ────────────────────────

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import saurav


# ── Outcome classification ──────────────────────────────────────────

class Outcome:
    OK = "ok"                  # ran without error
    RUNTIME_ERROR = "runtime"  # expected RuntimeError / signal
    SYNTAX_ERROR = "syntax"    # expected SyntaxError
    CRASH = "crash"            # unexpected exception (bug!)
    TIMEOUT = "timeout"        # hung / infinite loop
    INTERNAL = "internal"      # interpreter internal error


# Control flow signals that escape when used outside proper context
# (e.g. throw outside try/catch, break outside loop)
_SIGNAL_TYPES = tuple(
    getattr(saurav, name) for name in
    ["ThrowSignal", "BreakSignal", "ContinueSignal",
     "ReturnSignal", "YieldSignal"]
    if hasattr(saurav, name)
)


@dataclass
class FuzzResult:
    """Result of fuzzing a single program."""
    code: str
    outcome: str
    error_type: str = ""
    error_msg: str = ""
    duration_ms: float = 0.0
    minimized: str = ""

    def to_dict(self):
        d = {"outcome": self.outcome, "duration_ms": round(self.duration_ms, 2)}
        if self.error_type:
            d["error_type"] = self.error_type
        if self.error_msg:
            d["error_msg"] = self.error_msg[:200]
        d["code"] = self.code
        if self.minimized:
            d["minimized"] = self.minimized
        return d


@dataclass
class FuzzReport:
    """Summary of a fuzzing run."""
    iterations: int = 0
    seed: int = 0
    duration_sec: float = 0.0
    outcomes: Dict[str, int] = field(default_factory=Counter)
    crashes: List[FuzzResult] = field(default_factory=list)
    timeouts: List[FuzzResult] = field(default_factory=list)
    internals: List[FuzzResult] = field(default_factory=list)

    def to_dict(self):
        return {
            "iterations": self.iterations,
            "seed": self.seed,
            "duration_sec": round(self.duration_sec, 2),
            "outcomes": dict(self.outcomes),
            "crash_count": len(self.crashes),
            "timeout_count": len(self.timeouts),
            "internal_count": len(self.internals),
            "crashes": [c.to_dict() for c in self.crashes[:50]],
            "timeouts": [t.to_dict() for t in self.timeouts[:20]],
            "internals": [i.to_dict() for i in self.internals[:20]],
        }

    def summary(self):
        lines = []
        lines.append("=" * 60)
        lines.append("sauravfuzz Report")
        lines.append("=" * 60)
        lines.append(f"Iterations: {self.iterations}  |  Seed: {self.seed}")
        lines.append(f"Duration:   {self.duration_sec:.1f}s")
        lines.append("")
        lines.append("Outcomes:")
        total = max(self.iterations, 1)
        for k, v in sorted(self.outcomes.items(), key=lambda x: -x[1]):
            pct = v / total * 100
            bar = "#" * int(pct / 2)
            lines.append(f"  {k:15s} {v:5d} ({pct:5.1f}%) {bar}")
        lines.append("")

        if self.crashes:
            lines.append(f"CRASHES ({len(self.crashes)}):")
            for i, c in enumerate(self.crashes[:10]):
                lines.append(f"  [{i+1}] {c.error_type}: {c.error_msg[:80]}")
                for cl in c.code.split("\n")[:3]:
                    lines.append(f"      | {cl}")
                if c.minimized:
                    lines.append(f"      minimized:")
                    for ml in c.minimized.split("\n")[:3]:
                        lines.append(f"      > {ml}")
            lines.append("")

        if self.timeouts:
            lines.append(f"TIMEOUTS ({len(self.timeouts)}):")
            for i, t in enumerate(self.timeouts[:5]):
                first_line = t.code.split("\n")[0]
                lines.append(f"  [{i+1}] {first_line[:80]}...")
            lines.append("")

        if self.internals:
            lines.append(f"INTERNAL ERRORS ({len(self.internals)}):")
            for i, e in enumerate(self.internals[:5]):
                lines.append(f"  [{i+1}] {e.error_type}: {e.error_msg[:80]}")
            lines.append("")

        if not self.crashes and not self.internals:
            lines.append("No crashes or internal errors found.")
        lines.append("=" * 60)
        return "\n".join(lines)


# ── Program generator ───────────────────────────────────────────────

class ProgramGenerator:
    """Generate random syntactically valid sauravcode programs."""

    VARS = ["x", "y", "z", "n", "m", "acc", "tmp", "val", "idx", "res"]
    FN_NAMES = ["foo", "bar", "baz", "helper", "calc", "proc"]

    def __init__(self, rng=None, max_depth=4, max_stmts=15):
        self.rng = rng or random.Random()
        self.max_depth = max_depth
        self.max_stmts = max_stmts
        self._defined_fns = []
        self._defined_vars = []

    def generate(self):
        """Generate a complete program as a string."""
        self._defined_fns = []
        self._defined_vars = []
        lines = []
        n_stmts = self.rng.randint(1, self.max_stmts)
        for _ in range(n_stmts):
            stmt = self._gen_statement(0)
            if stmt:
                lines.append(stmt)
        return "\n".join(lines) + "\n"

    def _gen_statement(self, depth):
        if depth >= self.max_depth:
            return self._gen_simple_statement(depth)

        weights = [
            (30, "assign"), (15, "print"), (10, "if"),
            (8, "while"), (8, "for"), (8, "foreach"),
            (6, "function"), (5, "try_catch"), (4, "list_ops"),
            (3, "map_ops"), (3, "match"), (2, "assert"),
            (2, "enum"), (2, "class"), (2, "fstring"),
        ]
        labels = [w[1] for w in weights]
        ws = [w[0] for w in weights]
        choice = self.rng.choices(labels, weights=ws, k=1)[0]
        gen_fn = getattr(self, f"_gen_{choice}")
        return gen_fn(depth)

    def _gen_simple_statement(self, depth):
        choice = self.rng.choice(["assign", "print"])
        if choice == "assign":
            return self._gen_assign(depth)
        return self._gen_print(depth)

    @staticmethod
    def _indent(code, level=1):
        prefix = "    " * level
        return "\n".join(prefix + line if line.strip() else line
                         for line in code.split("\n"))

    # ── Expressions ─────────────────────────────────────────

    def _gen_expr(self, depth=0):
        if depth >= self.max_depth:
            return self._gen_atom()

        choice = self.rng.choices(
            ["atom", "binary", "compare", "unary", "call", "index",
             "list_lit", "ternary", "lambda"],
            weights=[30, 20, 10, 5, 10, 5, 5, 5, 3],
            k=1,
        )[0]

        dispatch = {
            "atom": lambda: self._gen_atom(),
            "binary": lambda: self._gen_binary(depth),
            "compare": lambda: self._gen_compare(depth),
            "unary": lambda: self._gen_unary(depth),
            "call": lambda: self._gen_call(depth),
            "index": lambda: self._gen_index(depth),
            "list_lit": lambda: self._gen_list_literal(depth),
            "ternary": lambda: self._gen_ternary(depth),
            "lambda": lambda: self._gen_lambda_expr(depth),
        }
        return dispatch.get(choice, self._gen_atom)()

    def _gen_atom(self):
        choice = self.rng.choices(
            ["int", "float", "string", "bool", "var", "neg"],
            weights=[25, 10, 15, 10, 30, 10], k=1,
        )[0]
        if choice == "int":
            return str(self.rng.randint(0, 1000))
        if choice == "float":
            return f"{self.rng.uniform(-100, 100):.2f}"
        if choice == "string":
            words = ["hello", "world", "test", "foo", "", "a b c"]
            return f'"{self.rng.choice(words)}"'
        if choice == "bool":
            return self.rng.choice(["true", "false"])
        if choice == "var":
            if self._defined_vars:
                return self.rng.choice(self._defined_vars)
            return str(self.rng.randint(0, 10))
        return str(-self.rng.randint(1, 100))

    def _gen_binary(self, depth):
        left = self._gen_expr(depth + 1)
        right = self._gen_expr(depth + 1)
        op = self.rng.choice(["+", "-", "*", "/", "%", "**"])
        return f"({left} {op} {right})"

    def _gen_compare(self, depth):
        left = self._gen_expr(depth + 1)
        right = self._gen_expr(depth + 1)
        op = self.rng.choice(["==", "!=", "<", ">", "<=", ">="])
        return f"{left} {op} {right}"

    def _gen_unary(self, depth):
        return f"not {self._gen_expr(depth + 1)}"

    def _gen_call(self, depth):
        if self._defined_fns:
            fn = self.rng.choice(self._defined_fns)
            arg = self._gen_expr(depth + 1)
            return f"{fn}({arg})"
        builtin = self.rng.choice(["len", "abs", "round", "str", "int",
                                    "float", "type"])
        return f"{builtin}({self._gen_expr(depth + 1)})"

    def _gen_index(self, depth):
        if self._defined_vars:
            var = self.rng.choice(self._defined_vars)
            return f"{var}[{self.rng.randint(0, 3)}]"
        return self._gen_atom()

    def _gen_list_literal(self, depth):
        n = self.rng.randint(0, 5)
        return "[" + ", ".join(self._gen_atom() for _ in range(n)) + "]"

    def _gen_ternary(self, depth):
        cond = self._gen_compare(depth + 1)
        t = self._gen_expr(depth + 1)
        f = self._gen_expr(depth + 1)
        return f"{t} if {cond} else {f}"

    def _gen_lambda_expr(self, depth):
        p = self.rng.choice(self.VARS[:5])
        return f"lambda {p}: {self._gen_expr(depth + 1)}"

    # ── Statements ──────────────────────────────────────────

    def _gen_assign(self, depth):
        var = self.rng.choice(self.VARS)
        if var not in self._defined_vars:
            self._defined_vars.append(var)
        return f"{var} = {self._gen_expr(depth)}"

    def _gen_print(self, depth):
        return f"print {self._gen_expr(depth)}"

    def _gen_if(self, depth):
        cond = self._gen_compare(depth + 1)
        body = self._gen_body(depth + 1)
        result = f"if {cond}\n{body}"
        if self.rng.random() < 0.4:
            result += f"\nelse\n{self._gen_body(depth + 1)}"
        return result

    def _gen_while(self, depth):
        var = self.rng.choice(self.VARS[:3])
        limit = self.rng.randint(1, 5)
        if var not in self._defined_vars:
            self._defined_vars.append(var)
        body = self._gen_body(depth + 1)
        incr = self._indent(f"{var} = {var} + 1")
        return f"{var} = 0\nwhile {var} < {limit}\n{body}\n{incr}"

    def _gen_for(self, depth):
        var = self.rng.choice(self.VARS[:5])
        s = self.rng.randint(0, 3)
        e = s + self.rng.randint(1, 5)
        if var not in self._defined_vars:
            self._defined_vars.append(var)
        return f"for {var} {s} {e}\n{self._gen_body(depth + 1)}"

    def _gen_foreach(self, depth):
        var = self.rng.choice(self.VARS[:5])
        if var not in self._defined_vars:
            self._defined_vars.append(var)
        items = self._gen_list_literal(depth + 1)
        return f"for {var} in {items}\n{self._gen_body(depth + 1)}"

    def _gen_function(self, depth):
        name = self.rng.choice(self.FN_NAMES)
        params = self.rng.sample(self.VARS[:5], k=self.rng.randint(0, 3))
        old_vars = self._defined_vars[:]
        self._defined_vars.extend(params)
        body = self._gen_body(depth + 1)
        ret = self._gen_expr(depth + 1)
        self._defined_vars = old_vars
        if name not in self._defined_fns:
            self._defined_fns.append(name)
        return f"function {name} {' '.join(params)}\n{body}\n    return {ret}"

    def _gen_try_catch(self, depth):
        var = self.rng.choice(["e", "err", "ex"])
        return (f"try\n{self._gen_body(depth + 1)}\n"
                f"catch {var}\n{self._indent(f'print {var}')}")

    def _gen_list_ops(self, depth):
        var = self.rng.choice(self.VARS[:5])
        if var not in self._defined_vars:
            self._defined_vars.append(var)
        lines = [f"{var} = {self._gen_list_literal(depth + 1)}"]
        op = self.rng.choice(["append", "len", "pop", "index"])
        if op == "append":
            lines.append(f"append {var} {self._gen_atom()}")
        elif op == "len":
            lines.append(f"print len({var})")
        elif op == "pop":
            lines.append(f"pop {var}")
        elif op == "index":
            lines.append(f"print {var}[0]")
        return "\n".join(lines)

    def _gen_map_ops(self, depth):
        var = self.rng.choice(self.VARS[:5])
        if var not in self._defined_vars:
            self._defined_vars.append(var)
        keys = self.rng.sample(["a", "b", "c", "d"],
                                k=self.rng.randint(1, 3))
        pairs = ", ".join(f'"{k}": {self.rng.randint(1, 99)}' for k in keys)
        return f'{var} = {{{pairs}}}\nprint {var}["{keys[0]}"]'

    def _gen_match(self, depth):
        expr = self._gen_expr(depth + 1)
        cases = []
        for _ in range(self.rng.randint(1, 3)):
            val = self._gen_atom()
            cases.append(f"    case {val}\n        print {val}")
        return f"match {expr}\n" + "\n".join(cases)

    def _gen_assert(self, depth):
        return f"assert {self._gen_compare(depth + 1)}"

    def _gen_enum(self, depth):
        name = f"Color{self.rng.randint(1, 99)}"
        variants = self.rng.sample(["Red", "Green", "Blue", "Yellow"], k=3)
        body = "\n".join(f"    {v}" for v in variants)
        return f"enum {name}\n{body}"

    def _gen_class(self, depth):
        name = f"Thing{self.rng.randint(1, 99)}"
        fields = self.rng.sample(["name", "value", "count"], k=2)
        body = "\n".join(f"    {f} = {self._gen_atom()}" for f in fields)
        return f"class {name}\n{body}"

    def _gen_fstring(self, depth):
        var = self._defined_vars[0] if self._defined_vars else "42"
        return f'print f"value is {{{var}}}"'

    def _gen_body(self, depth, min_s=1, max_s=3):
        n = self.rng.randint(min_s, max_s)
        stmts = [self._gen_simple_statement(depth) for _ in range(n)]
        stmts = [s for s in stmts if s] or [f"print {self.rng.randint(0, 99)}"]
        return "\n".join(self._indent(s) for s in stmts)


# ── Runner ──────────────────────────────────────────────────────────

def _run_code_safe(code, timeout_sec=2.0):
    """Run sauravcode and classify the outcome.

    Returns (outcome, error_type, error_msg, duration_ms).
    """
    result = {"done": False, "outcome": Outcome.OK,
              "error_type": "", "error_msg": ""}
    start = time.perf_counter()

    def target():
        try:
            tokens = list(saurav.tokenize(code))
            parser = saurav.Parser(tokens)
            ast = parser.parse()
            interp = saurav.Interpreter()
            old_stdout = sys.stdout
            sys.stdout = io.StringIO()
            try:
                for node in ast:
                    interp.execute_body([node])
            finally:
                sys.stdout = old_stdout
            result["outcome"] = Outcome.OK
        except SyntaxError as e:
            result["outcome"] = Outcome.SYNTAX_ERROR
            result["error_type"] = "SyntaxError"
            result["error_msg"] = str(e)[:300]
        except (RuntimeError, ValueError, ZeroDivisionError,
                KeyError, IndexError) as e:
            result["outcome"] = Outcome.RUNTIME_ERROR
            result["error_type"] = type(e).__name__
            result["error_msg"] = str(e)[:300]
        except _SIGNAL_TYPES as e:
            # Control flow signals escaping (throw outside try, break outside loop)
            result["outcome"] = Outcome.RUNTIME_ERROR
            result["error_type"] = type(e).__name__
            result["error_msg"] = str(e)[:300]
        except RecursionError:
            result["outcome"] = Outcome.RUNTIME_ERROR
            result["error_type"] = "RecursionError"
            result["error_msg"] = "Maximum recursion depth exceeded"
        except SystemExit:
            result["outcome"] = Outcome.INTERNAL
            result["error_type"] = "SystemExit"
            result["error_msg"] = "Interpreter called sys.exit()"
        except MemoryError:
            result["outcome"] = Outcome.RUNTIME_ERROR
            result["error_type"] = "MemoryError"
            result["error_msg"] = "Out of memory"
        except Exception as e:
            result["outcome"] = Outcome.CRASH
            result["error_type"] = type(e).__name__
            result["error_msg"] = str(e)[:300]
        finally:
            result["done"] = True

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout=timeout_sec)
    elapsed = (time.perf_counter() - start) * 1000

    if not result["done"]:
        return Outcome.TIMEOUT, "Timeout", f"Exceeded {timeout_sec}s", elapsed

    return result["outcome"], result["error_type"], result["error_msg"], elapsed


# ── Minimizer ───────────────────────────────────────────────────────

def minimize_crash(code, timeout_sec=2.0, max_attempts=50):
    """Reduce a crashing program to its minimal form via delta debugging."""
    lines = code.strip().split("\n")
    if len(lines) <= 1:
        return code

    outcome, etype, _, _ = _run_code_safe(code, timeout_sec)
    if outcome not in (Outcome.CRASH, Outcome.INTERNAL):
        return code

    original_etype = etype
    best = lines[:]

    for attempt in range(min(max_attempts, len(lines) * 2)):
        i = attempt % len(best)
        if i >= len(best):
            break
        candidate = best[:i] + best[i + 1:]
        if not candidate:
            continue
        test_code = "\n".join(candidate) + "\n"
        o, et, _, _ = _run_code_safe(test_code, timeout_sec)
        if o in (Outcome.CRASH, Outcome.INTERNAL) and et == original_etype:
            best = candidate

    return "\n".join(best) + "\n"


# ── Mutation fuzzer ─────────────────────────────────────────────────

class MutationFuzzer:
    """Mutate existing programs to find edge cases."""

    def __init__(self, rng=None):
        self.rng = rng or random.Random()

    def mutate(self, code):
        mutations = [
            self._swap_operator, self._duplicate_line,
            self._remove_line, self._change_number,
            self._insert_keyword, self._swap_lines,
            self._break_indent, self._inject_unicode,
        ]
        return self.rng.choice(mutations)(code)

    def _swap_operator(self, code):
        ops = ["+", "-", "*", "/", "%", "**", "==", "!=", "<", ">"]
        return code.replace(self.rng.choice(ops), self.rng.choice(ops), 1)

    def _duplicate_line(self, code):
        lines = code.split("\n")
        if lines:
            i = self.rng.randrange(len(lines))
            lines.insert(i, lines[i])
        return "\n".join(lines)

    def _remove_line(self, code):
        lines = code.split("\n")
        if len(lines) > 1:
            lines.pop(self.rng.randrange(len(lines)))
        return "\n".join(lines)

    def _change_number(self, code):
        nums = list(re.finditer(r'\b\d+\b', code))
        if nums:
            m = self.rng.choice(nums)
            val = self.rng.choice(["0", "-1", "999999", str(2**31)])
            code = code[:m.start()] + val + code[m.end():]
        return code

    def _insert_keyword(self, code):
        lines = code.split("\n")
        kws = ["break", "continue", "return", "throw", "yield", "next"]
        if lines:
            i = self.rng.randrange(len(lines))
            indent = len(lines[i]) - len(lines[i].lstrip())
            lines.insert(i, " " * indent + self.rng.choice(kws))
        return "\n".join(lines)

    def _swap_lines(self, code):
        lines = code.split("\n")
        if len(lines) >= 2:
            i, j = self.rng.sample(range(len(lines)), 2)
            lines[i], lines[j] = lines[j], lines[i]
        return "\n".join(lines)

    def _break_indent(self, code):
        lines = code.split("\n")
        if lines:
            i = self.rng.randrange(len(lines))
            if lines[i].startswith("    "):
                lines[i] = lines[i][4:]
            else:
                lines[i] = "    " + lines[i]
        return "\n".join(lines)

    def _inject_unicode(self, code):
        chars = ["\u0000", "\uffff", "\u200b", "\U0001f600", "\t\t"]
        lines = code.split("\n")
        if lines:
            i = self.rng.randrange(len(lines))
            pos = self.rng.randrange(max(1, len(lines[i])))
            lines[i] = lines[i][:pos] + self.rng.choice(chars) + lines[i][pos:]
        return "\n".join(lines)


# ── Seed corpus ─────────────────────────────────────────────────────

SEED_CORPUS = [
    'x = 42\nprint x\n',
    'print 3 + 5\n',
    'x = "hello"\nprint x\n',
    'if true\n    print 1\nelse\n    print 0\n',
    'for i 0 5\n    print i\n',
    'x = 0\nwhile x < 3\n    print x\n    x = x + 1\n',
    'function add a b\n    return a + b\nprint add(2 3)\n',
    ('function fib n\n    if n <= 1\n        return n\n'
     '    return fib(n - 1) + fib(n - 2)\nprint fib(8)\n'),
    'xs = [1, 2, 3]\nappend xs 4\nprint len(xs)\n',
    'xs = [10, 20, 30]\nfor x in xs\n    print x\n',
    'try\n    throw "oops"\ncatch e\n    print e\n',
    ('x = 2\nmatch x\n    case 1\n        print "one"\n'
     '    case 2\n        print "two"\n'),
    'm = {"a": 1, "b": 2}\nprint m["a"]\n',
    'enum Color\n    Red\n    Green\n    Blue\nprint Color.Red\n',
    'name = "world"\nprint f"hello {name}"\n',
    'double = lambda x: x * 2\nprint double(5)\n',
    'xs = [1, 2, 3, 4, 5]\nprint xs[1:3]\n',
]


# ── Main fuzzer engine ──────────────────────────────────────────────

class Fuzzer:
    """Main fuzzer engine."""

    def __init__(self, seed=None, timeout=2.0, max_depth=4,
                 max_stmts=15, minimize=False):
        self.seed = seed if seed is not None else random.randint(0, 2**32)
        self.rng = random.Random(self.seed)
        self.timeout = timeout
        self.max_depth = max_depth
        self.max_stmts = max_stmts
        self.minimize = minimize
        self.report = FuzzReport(seed=self.seed)
        self._seen = set()

    def run(self, iterations=100, progress=True):
        self.report.iterations = iterations
        start = time.perf_counter()
        gen = ProgramGenerator(rng=self.rng, max_depth=self.max_depth,
                               max_stmts=self.max_stmts)

        for i in range(iterations):
            if progress and (i + 1) % max(1, iterations // 10) == 0:
                pct = (i + 1) / iterations * 100
                print(f"  [{pct:5.1f}%] {i+1}/{iterations} "
                      f"({len(self.report.crashes)} crashes, "
                      f"{len(self.report.timeouts)} timeouts)",
                      file=sys.stderr)

            code = gen.generate()
            outcome, etype, emsg, dur = _run_code_safe(code, self.timeout)
            self.report.outcomes[outcome] += 1

            result = FuzzResult(code=code, outcome=outcome,
                                error_type=etype, error_msg=emsg,
                                duration_ms=dur)

            if outcome == Outcome.CRASH:
                sig = f"{etype}:{emsg[:50]}"
                if sig not in self._seen:
                    self._seen.add(sig)
                    if self.minimize:
                        result.minimized = minimize_crash(code, self.timeout)
                    self.report.crashes.append(result)
            elif outcome == Outcome.TIMEOUT:
                if len(self.report.timeouts) < 20:
                    self.report.timeouts.append(result)
            elif outcome == Outcome.INTERNAL:
                if len(self.report.internals) < 20:
                    self.report.internals.append(result)

        self.report.duration_sec = time.perf_counter() - start
        return self.report


def run_mutation_fuzz(iterations, seed, timeout, quiet):
    """Run mutation-based fuzzing."""
    rng = random.Random(seed)
    mutator = MutationFuzzer(rng)
    report = FuzzReport(iterations=iterations, seed=seed or 0)
    start = time.perf_counter()
    seen = set()

    for i in range(iterations):
        base = rng.choice(SEED_CORPUS)
        code = base
        for _ in range(rng.randint(1, 5)):
            code = mutator.mutate(code)

        outcome, etype, emsg, dur = _run_code_safe(code, timeout)
        report.outcomes[outcome] += 1

        if outcome == Outcome.CRASH:
            sig = f"{etype}:{emsg[:50]}"
            if sig not in seen:
                seen.add(sig)
                report.crashes.append(FuzzResult(
                    code=code, outcome=outcome,
                    error_type=etype, error_msg=emsg, duration_ms=dur))
        elif outcome == Outcome.TIMEOUT and len(report.timeouts) < 20:
            report.timeouts.append(FuzzResult(
                code=code, outcome=outcome,
                error_type=etype, error_msg=emsg, duration_ms=dur))
        elif outcome == Outcome.INTERNAL and len(report.internals) < 20:
            report.internals.append(FuzzResult(
                code=code, outcome=outcome,
                error_type=etype, error_msg=emsg, duration_ms=dur))

        if not quiet and (i + 1) % max(1, iterations // 10) == 0:
            pct = (i + 1) / iterations * 100
            print(f"  [{pct:5.1f}%] {i+1}/{iterations} "
                  f"({len(report.crashes)} crashes)", file=sys.stderr)

    report.duration_sec = time.perf_counter() - start
    return report


# ── CLI ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="sauravfuzz -- Grammar-aware fuzzer for sauravcode",
        epilog="Example: python sauravfuzz.py -n 500 --seed 42",
    )
    parser.add_argument("--iterations", "-n", type=int, default=100,
                        help="Number of programs to generate (default: 100)")
    parser.add_argument("--seed", "-s", type=int, default=None,
                        help="Random seed for reproducibility")
    parser.add_argument("--timeout", "-t", type=float, default=2.0,
                        help="Per-program timeout in seconds (default: 2.0)")
    parser.add_argument("--depth", "-d", type=int, default=4,
                        help="Max AST nesting depth (default: 4)")
    parser.add_argument("--stmts", type=int, default=15,
                        help="Max statements per program (default: 15)")
    parser.add_argument("--report", "-r", metavar="FILE",
                        help="Save report as JSON")
    parser.add_argument("--min-crash", action="store_true",
                        help="Minimize crash cases (slower)")
    parser.add_argument("--mutate", action="store_true",
                        help="Use mutation fuzzing on seed corpus")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="Suppress progress output")

    args = parser.parse_args()
    seed = args.seed if args.seed is not None else random.randint(0, 2**32)

    print(f"sauravfuzz -- fuzzing sauravcode interpreter", file=sys.stderr)
    print(f"  iterations: {args.iterations}  seed: {seed}  "
          f"timeout: {args.timeout}s  depth: {args.depth}", file=sys.stderr)

    if args.mutate:
        report = run_mutation_fuzz(args.iterations, seed,
                                   args.timeout, args.quiet)
    else:
        fuzzer = Fuzzer(seed=seed, timeout=args.timeout,
                        max_depth=args.depth, max_stmts=args.stmts,
                        minimize=args.min_crash)
        report = fuzzer.run(iterations=args.iterations,
                            progress=not args.quiet)

    print(report.summary())

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2)
        print(f"\nReport saved to {args.report}", file=sys.stderr)


if __name__ == "__main__":
    main()
