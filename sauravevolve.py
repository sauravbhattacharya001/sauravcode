#!/usr/bin/env python3
"""sauravevolve — Genetic programming engine for sauravcode (.srv).

Autonomously evolves .srv programs toward passing user-defined test cases
using tournament selection, crossover, and mutation. Programs start as
random expressions and evolve over generations toward correct solutions.

Usage:
    python sauravevolve.py                           # Interactive REPL
    python sauravevolve.py --problem sum              # Evolve a sum function
    python sauravevolve.py --problem max              # Evolve a max function
    python sauravevolve.py --problem fizzbuzz         # Evolve fizzbuzz
    python sauravevolve.py --cases cases.json         # Custom test cases
    python sauravevolve.py --problem sum --pop 200    # Population size
    python sauravevolve.py --problem sum --gens 100   # Max generations
    python sauravevolve.py --problem sum --report     # HTML report
    python sauravevolve.py --list                     # List built-in problems
    python sauravevolve.py --autopilot                # Auto-solve all problems

Built-in problems: sum, max, factorial, fibonacci, reverse, fizzbuzz,
    collatz, gcd, isPrime, abs

Custom test cases (JSON):
    {
      "name": "double",
      "description": "Double the input",
      "cases": [
        {"input": "5", "expected": "10"},
        {"input": "0", "expected": "0"},
        {"input": "-3", "expected": "-6"}
      ]
    }
"""

from __future__ import annotations

import argparse
import copy
import io
import json
import math
import os
import random
import re
import sys
import textwrap
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ── Ensure sauravcode importable ────────────────────────────────────

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import saurav

_SIGNAL_TYPES = tuple(
    getattr(saurav, name) for name in
    ["ThrowSignal", "BreakSignal", "ContinueSignal",
     "ReturnSignal", "YieldSignal"]
    if hasattr(saurav, name)
)

# ── Safe program execution ──────────────────────────────────────────

def _run_program(code: str, stdin_text: str = "", timeout: float = 2.0,
                 _precompiled: Any = None) -> Tuple[str, bool]:
    """Run .srv code, return (stdout, success).

    If *_precompiled* is a list of AST nodes (from a previous
    ``saurav.Parser(saurav.tokenize(code)).parse()`` call), the
    tokenize+parse step is skipped — a significant speedup when the
    same program is evaluated against many test inputs.
    """
    result = {"output": "", "ok": False}

    def _exec():
        try:
            old_stdin = sys.stdin
            old_stdout = sys.stdout
            sys.stdin = io.StringIO(stdin_text)
            capture = io.StringIO()
            sys.stdout = capture
            try:
                if _precompiled is not None:
                    program = _precompiled
                else:
                    tokens = saurav.tokenize(code)
                    parser = saurav.Parser(tokens)
                    program = parser.parse()
                interpreter = saurav.Interpreter()
                interpreter.run(program)
                result["ok"] = True
            except _SIGNAL_TYPES:
                result["ok"] = True
            except (SyntaxError, RuntimeError):
                pass
            except Exception:
                pass
            finally:
                result["output"] = capture.getvalue()
                sys.stdin = old_stdin
                sys.stdout = old_stdout
        except Exception:
            pass

    t = threading.Thread(target=_exec, daemon=True)
    t.start()
    t.join(timeout)
    return result["output"].rstrip("\n"), result["ok"]


def _precompile(code: str) -> Optional[Any]:
    """Tokenize + parse *code* once, returning the AST or None on error."""
    try:
        tokens = saurav.tokenize(code)
        parser = saurav.Parser(tokens)
        return parser.parse()
    except Exception:
        return None


# ── Test case definition ────────────────────────────────────────────

@dataclass
class TestCase:
    input: str
    expected: str

@dataclass
class Problem:
    name: str
    description: str
    cases: List[TestCase]
    hint: str = ""


# ── Built-in problems ──────────────────────────────────────────────

BUILTIN_PROBLEMS: Dict[str, Problem] = {}

def _register(name, desc, cases, hint=""):
    BUILTIN_PROBLEMS[name] = Problem(
        name=name, description=desc, hint=hint,
        cases=[TestCase(c[0], c[1]) for c in cases],
    )

_register("sum", "Read two integers and print their sum.", [
    ("3\n5", "8"), ("0\n0", "0"), ("-1\n4", "3"),
    ("100\n200", "300"), ("7\n-7", "0"),
], hint='let a = int(input(""))\nlet b = int(input(""))\nprint(a + b)')

_register("max", "Read two integers and print the larger one.", [
    ("3\n5", "5"), ("10\n2", "10"), ("-1\n-5", "-1"),
    ("7\n7", "7"), ("0\n100", "100"),
], hint='let a = int(input(""))\nlet b = int(input(""))\nif a > b { print(a) } else { print(b) }')

_register("abs", "Read an integer and print its absolute value.", [
    ("5", "5"), ("-3", "3"), ("0", "0"), ("-100", "100"), ("42", "42"),
], hint='let n = int(input(""))\nif n < 0 { print(-n) } else { print(n) }')

_register("factorial", "Read a non-negative integer and print its factorial.", [
    ("0", "1"), ("1", "1"), ("5", "120"), ("3", "6"), ("7", "5040"),
], hint='let n = int(input(""))\nlet r = 1\nfor i in range(1, n + 1) { r = r * i }\nprint(r)')

_register("fibonacci", "Read n and print the nth Fibonacci number (0-indexed).", [
    ("0", "0"), ("1", "1"), ("5", "5"), ("10", "55"), ("7", "13"),
], hint='let n = int(input(""))\nlet a = 0\nlet b = 1\nfor i in range(0, n) { let t = b\nb = a + b\na = t }\nprint(a)')

_register("reverse", "Read a string and print it reversed.", [
    ("hello", "olleh"), ("abc", "cba"), ("a", "a"), ("racecar", "racecar"), ("12345", "54321"),
], hint='let s = input("")\nprint(reverse(s))')

_register("fizzbuzz", "Read n. Print FizzBuzz for numbers 1 to n.", [
    ("3", "1\n2\nFizz"), ("5", "1\n2\nFizz\n4\nBuzz"),
    ("1", "1"), ("15", "1\n2\nFizz\n4\nBuzz\nFizz\n7\n8\nFizz\nBuzz\n11\nFizz\n13\n14\nFizzBuzz"),
], hint='let n = int(input(""))\nfor i in range(1, n + 1) { if i % 15 == 0 { print("FizzBuzz") } else if i % 3 == 0 { print("Fizz") } else if i % 5 == 0 { print("Buzz") } else { print(i) } }')

_register("collatz", "Read n. Print collatz sequence steps until 1.", [
    ("1", "0"), ("2", "1"), ("3", "7"), ("6", "8"), ("27", "111"),
], hint='let n = int(input(""))\nlet s = 0\nwhile n != 1 { if n % 2 == 0 { n = n / 2 } else { n = 3 * n + 1 }\ns = s + 1 }\nprint(s)')

_register("gcd", "Read two positive integers, print their GCD.", [
    ("12\n8", "4"), ("7\n3", "1"), ("100\n25", "25"),
    ("17\n17", "17"), ("48\n18", "6"),
], hint='let a = int(input(""))\nlet b = int(input(""))\nwhile b != 0 { let t = b\nb = a % b\na = t }\nprint(a)')

_register("isPrime", "Read an integer, print true or false.", [
    ("2", "true"), ("7", "true"), ("1", "false"),
    ("4", "false"), ("13", "true"), ("15", "false"),
], hint='let n = int(input(""))\nif n < 2 { print("false") } else { let p = true\nfor i in range(2, n) { if n % i == 0 { p = false } }\nif p { print("true") } else { print("false") } }')


# ── Genome: Program representation ─────────────────────────────────

# We use a template-based approach. Programs are built from code fragments
# that can be combined and mutated. This is more effective than random
# token generation for producing valid .srv programs.

# Code building blocks
ATOMS = [
    'let {v} = int(input(""))',
    'let {v} = input("")',
    'let {v} = 0',
    'let {v} = 1',
    'let {v} = ""',
    'let {v} = true',
    'let {v} = false',
]

EXPRESSIONS = [
    '{v1} + {v2}', '{v1} - {v2}', '{v1} * {v2}', '{v1} / {v2}',
    '{v1} % {v2}', '-{v1}',
    '{v1} == {v2}', '{v1} != {v2}', '{v1} > {v2}', '{v1} < {v2}',
    '{v1} >= {v2}', '{v1} <= {v2}',
    'str({v1})', 'int({v1})', 'len({v1})', 'reverse({v1})',
]

ACTIONS = [
    'print({v1})',
    'print({e})',
    '{v1} = {e}',
    '{v1} = {v2}',
]

CONTROLS = [
    'if {cond} {{ {body1} }} else {{ {body2} }}',
    'while {cond} {{ {body1} }}',
    'for {v} in range({v1}, {v2}) {{ {body1} }}',
]

VAR_NAMES = list("abcdefnrstxyz")


@dataclass
class Individual:
    """A candidate program."""
    code: str
    fitness: float = 0.0
    cases_passed: int = 0
    generation: int = 0

    def copy(self):
        clone = Individual(code=self.code, fitness=self.fitness,
                         cases_passed=self.cases_passed, generation=self.generation)
        clone._evaluated = getattr(self, '_evaluated', False)
        return clone


# ── Random program generation ──────────────────────────────────────

def _rand_var() -> str:
    return random.choice(VAR_NAMES)

def _rand_expr(vars_available: List[str]) -> str:
    if not vars_available:
        vars_available = ["n"]
    tmpl = random.choice(EXPRESSIONS)
    return tmpl.format(
        v1=random.choice(vars_available),
        v2=random.choice(vars_available),
    )

def _rand_cond(vars_available: List[str]) -> str:
    if not vars_available:
        vars_available = ["n"]
    v1 = random.choice(vars_available)
    v2 = random.choice(vars_available + ["0", "1", "2", "3", "5", "15"])
    op = random.choice(["==", "!=", ">", "<", ">=", "<="])
    if random.random() < 0.3:
        return f"{v1} % {random.choice(['2','3','5','15'])} {op} 0"
    return f"{v1} {op} {v2}"


def generate_random_program(max_lines: int = 8) -> str:
    """Generate a random .srv program."""
    lines = []
    declared_vars: List[str] = []
    n_lines = random.randint(2, max_lines)

    # Always start by reading input (most problems need it)
    n_inputs = random.randint(1, 2)
    for _ in range(n_inputs):
        v = _rand_var()
        while v in declared_vars:
            v = _rand_var()
        if random.random() < 0.7:
            lines.append(f'let {v} = int(input(""))')
        else:
            lines.append(f'let {v} = input("")')
        declared_vars.append(v)

    # Add some computation lines
    for _ in range(n_lines - n_inputs - 1):
        choice = random.random()
        if choice < 0.2 and declared_vars:
            # New variable from expression
            v = _rand_var()
            if v not in declared_vars:
                lines.append(f"let {v} = {_rand_expr(declared_vars)}")
                declared_vars.append(v)
            else:
                lines.append(f"{v} = {_rand_expr(declared_vars)}")
        elif choice < 0.4 and declared_vars:
            # If/else
            cond = _rand_cond(declared_vars)
            body1 = f"print({random.choice(declared_vars)})"
            body2 = f"print({random.choice(declared_vars)})"
            lines.append(f"if {cond} {{ {body1} }} else {{ {body2} }}")
        elif choice < 0.55 and declared_vars:
            # While loop
            v = random.choice(declared_vars)
            lines.append(f"while {v} > 0 {{ print({v})\n{v} = {v} - 1 }}")
        elif choice < 0.7 and declared_vars:
            # For loop
            lv = _rand_var()
            v1 = random.choice(declared_vars + ["0", "1"])
            v2 = random.choice(declared_vars)
            body = f"print({random.choice([lv] + declared_vars)})"
            lines.append(f"for {lv} in range({v1}, {v2}) {{ {body} }}")
        else:
            # Assignment
            if declared_vars:
                v = random.choice(declared_vars)
                lines.append(f"{v} = {_rand_expr(declared_vars)}")

    # End with a print
    if declared_vars:
        lines.append(f"print({random.choice(declared_vars)})")

    return "\n".join(lines)


# ── Fitness evaluation ──────────────────────────────────────────────

def evaluate(individual: Individual, problem: Problem) -> float:
    """Evaluate fitness: fraction of test cases passed + partial credit.

    The program is tokenized and parsed *once* via :func:`_precompile`;
    the resulting AST is reused for every test case, avoiding redundant
    O(code-length) tokenize+parse work per case.
    """
    total = len(problem.cases)
    passed = 0
    partial = 0.0

    # Parse once, reuse for all test cases
    ast = _precompile(individual.code)

    # Short-circuit: if program doesn't parse, skip all test-case
    # executions — avoids N thread spawns + redundant re-parse attempts
    if ast is None:
        individual.cases_passed = 0
        individual.fitness = -0.05  # slight penalty vs zero
        return individual.fitness

    for tc in problem.cases:
        output, ok = _run_program(individual.code, tc.input, timeout=2.0,
                                  _precompiled=ast)
        if output.strip() == tc.expected.strip():
            passed += 1
        elif ok and output.strip():
            # Partial credit for producing output
            expected_lines = tc.expected.strip().split("\n")
            output_lines = output.strip().split("\n")
            matching = sum(1 for a, b in zip(expected_lines, output_lines) if a == b)
            if expected_lines:
                partial += 0.3 * (matching / len(expected_lines))

    individual.cases_passed = passed
    # Fitness: passed cases + partial credit, penalize length slightly
    length_penalty = min(0.05, len(individual.code) / 10000)
    individual.fitness = (passed + partial) / total - length_penalty
    return individual.fitness


# ── Genetic operators ───────────────────────────────────────────────

def tournament_select(population: List[Individual], k: int = 3) -> Individual:
    """Tournament selection."""
    competitors = random.sample(population, min(k, len(population)))
    return max(competitors, key=lambda ind: ind.fitness)


def crossover(parent1: Individual, parent2: Individual) -> Individual:
    """Single-point crossover on lines."""
    lines1 = parent1.code.split("\n")
    lines2 = parent2.code.split("\n")
    if len(lines1) < 2 or len(lines2) < 2:
        return parent1.copy()
    pt1 = random.randint(1, len(lines1) - 1)
    pt2 = random.randint(1, len(lines2) - 1)
    child_lines = lines1[:pt1] + lines2[pt2:]
    child = Individual(code="\n".join(child_lines))
    return child


# ── Shared helpers for genetic operators ────────────────────────────

_VAR_NAME_SET = frozenset(VAR_NAMES)

def _extract_declared_vars(lines: List[str]) -> List[str]:
    """Extract unique variable names referenced in *lines* that appear
    in the VAR_NAMES alphabet.  Returns at least ["n"] so callers
    never get an empty list."""
    seen = set()
    result = []
    for line in lines:
        for part in line.split():
            if part in _VAR_NAME_SET and part not in seen:
                seen.add(part)
                result.append(part)
    return result or ["n"]


def mutate(individual: Individual, rate: float = 0.3) -> Individual:
    """Mutate a program by modifying, inserting, or deleting lines."""
    if random.random() > rate:
        return individual.copy()

    lines = individual.code.split("\n")
    if not lines:
        return individual.copy()

    mutation_type = random.choice(["modify", "insert", "delete", "swap", "constant"])

    if mutation_type == "modify" and lines:
        idx = random.randint(0, len(lines) - 1)
        declared = _extract_declared_vars(lines)

        # Replace line with a new random action
        choice = random.random()
        if choice < 0.3:
            lines[idx] = f"print({random.choice(declared)})"
        elif choice < 0.5:
            lines[idx] = f"print({_rand_expr(declared)})"
        elif choice < 0.7:
            v = random.choice(declared)
            lines[idx] = f"{v} = {_rand_expr(declared)}"
        else:
            cond = _rand_cond(declared)
            body = f"print({random.choice(declared)})"
            lines[idx] = f"if {cond} {{ {body} }}"

    elif mutation_type == "insert" and len(lines) < 15:
        declared = _extract_declared_vars(lines)
        idx = random.randint(0, len(lines))
        new_line = random.choice([
            f"print({random.choice(declared)})",
            f"let {_rand_var()} = {_rand_expr(declared)}",
            f"{random.choice(declared)} = {_rand_expr(declared)}",
        ])
        lines.insert(idx, new_line)

    elif mutation_type == "delete" and len(lines) > 2:
        idx = random.randint(0, len(lines) - 1)
        lines.pop(idx)

    elif mutation_type == "swap" and len(lines) > 2:
        i, j = random.sample(range(len(lines)), 2)
        lines[i], lines[j] = lines[j], lines[i]

    elif mutation_type == "constant":
        # Tweak a numeric constant
        code = individual.code
        nums = list(re.finditer(r'\b(\d+)\b', code))
        if nums:
            m = random.choice(nums)
            val = int(m.group())
            new_val = val + random.choice([-1, 1, -2, 2, 0])
            new_val = max(0, new_val)
            code = code[:m.start()] + str(new_val) + code[m.end():]
            return Individual(code=code)

    return Individual(code="\n".join(lines))


# ── Evolution engine ────────────────────────────────────────────────

@dataclass
class EvolutionStats:
    generation: int = 0
    best_fitness: float = 0.0
    avg_fitness: float = 0.0
    best_passed: int = 0
    total_cases: int = 0
    best_code: str = ""
    history: List[Dict] = field(default_factory=list)
    solved: bool = False
    solve_gen: int = -1
    elapsed_sec: float = 0.0


def evolve(problem: Problem, pop_size: int = 100, max_gens: int = 50,
           mutation_rate: float = 0.4, elitism: int = 5,
           verbose: bool = True, seed: Optional[int] = None) -> EvolutionStats:
    """Run genetic programming to evolve a solution."""
    if seed is not None:
        random.seed(seed)

    stats = EvolutionStats(total_cases=len(problem.cases))
    start = time.time()

    # Initialize population
    population = [Individual(code=generate_random_program(), generation=0)
                  for _ in range(pop_size)]

    # If hint exists, seed one individual with it
    if problem.hint:
        population[0] = Individual(code=problem.hint, generation=0)

    for gen in range(max_gens):
        # Evaluate — skip elite carry-overs that already have a valid
        # score.  Using a boolean flag avoids the fragile `fitness == 0.0`
        # check that re-evaluated programs with legitimately zero fitness
        # and failed to skip zero-fitness elites.
        for ind in population:
            if not getattr(ind, '_evaluated', False) or ind.generation == gen:
                evaluate(ind, problem)
                ind._evaluated = True

        # Sort by fitness
        population.sort(key=lambda x: x.fitness, reverse=True)
        best = population[0]

        # Stats
        avg_fit = sum(ind.fitness for ind in population) / len(population)
        stats.generation = gen
        stats.best_fitness = best.fitness
        stats.avg_fitness = avg_fit
        stats.best_passed = best.cases_passed
        stats.best_code = best.code
        stats.history.append({
            "gen": gen,
            "best_fitness": round(best.fitness, 4),
            "avg_fitness": round(avg_fit, 4),
            "best_passed": best.cases_passed,
        })

        if verbose:
            bar = "█" * int(best.fitness * 20) + "░" * (20 - int(best.fitness * 20))
            print(f"  Gen {gen:3d}  [{bar}] {best.cases_passed}/{stats.total_cases}  "
                  f"best={best.fitness:.3f}  avg={avg_fit:.3f}")

        # Check if solved
        if best.cases_passed == stats.total_cases and best.fitness > 0.9:
            stats.solved = True
            stats.solve_gen = gen
            if verbose:
                print(f"\n  ✅ SOLVED in generation {gen}!")
            break

        # Next generation
        new_pop = []

        # Elitism
        for i in range(min(elitism, len(population))):
            new_pop.append(population[i].copy())

        # Fill rest with crossover + mutation
        while len(new_pop) < pop_size:
            if random.random() < 0.7:
                p1 = tournament_select(population)
                p2 = tournament_select(population)
                child = crossover(p1, p2)
            else:
                child = tournament_select(population).copy()

            child = mutate(child, mutation_rate)
            child.generation = gen + 1
            new_pop.append(child)

        population = new_pop

    stats.elapsed_sec = time.time() - start
    return stats


# ── Autopilot mode ──────────────────────────────────────────────────

def run_autopilot(problems: Optional[List[str]] = None, pop_size: int = 100,
                  max_gens: int = 50, verbose: bool = True) -> Dict[str, EvolutionStats]:
    """Autonomously attempt to solve multiple problems."""
    targets = problems or list(BUILTIN_PROBLEMS.keys())
    results = {}

    print("\n╔══════════════════════════════════════════════════╗")
    print("║         🧬  SAURAVEVOLVE AUTOPILOT  🧬          ║")
    print("╠══════════════════════════════════════════════════╣")
    print(f"║  Problems: {len(targets):<37} ║")
    print(f"║  Population: {pop_size:<35} ║")
    print(f"║  Max generations: {max_gens:<30} ║")
    print("╚══════════════════════════════════════════════════╝\n")

    solved = 0
    for i, name in enumerate(targets):
        if name not in BUILTIN_PROBLEMS:
            print(f"  ⚠️  Unknown problem: {name}")
            continue
        prob = BUILTIN_PROBLEMS[name]
        print(f"{'─' * 50}")
        print(f"  [{i+1}/{len(targets)}] 🎯 {prob.name}: {prob.description}")
        print(f"{'─' * 50}")

        stats = evolve(prob, pop_size=pop_size, max_gens=max_gens, verbose=verbose)
        results[name] = stats
        if stats.solved:
            solved += 1

    # Summary
    print(f"\n{'═' * 50}")
    print(f"  AUTOPILOT RESULTS: {solved}/{len(targets)} solved")
    print(f"{'═' * 50}")
    for name, stats in results.items():
        status = "✅" if stats.solved else "❌"
        gen_info = f"gen {stats.solve_gen}" if stats.solved else f"{stats.best_passed}/{stats.total_cases}"
        print(f"  {status} {name:<15} {gen_info:<15} {stats.elapsed_sec:.1f}s")

    return results


# ── HTML report ─────────────────────────────────────────────────────

def generate_report(stats: EvolutionStats, problem: Problem) -> str:
    """Generate an HTML evolution report."""
    history_json = json.dumps(stats.history)
    solved_badge = '<span style="color:#22c55e;font-weight:bold">✅ SOLVED</span>' if stats.solved else '<span style="color:#ef4444;font-weight:bold">❌ Not solved</span>'
    escaped_code = stats.best_code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>sauravevolve — {problem.name}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Segoe UI',system-ui,sans-serif; background:#0f172a; color:#e2e8f0; padding:2rem; }}
  h1 {{ color:#818cf8; margin-bottom:.5rem; }}
  .card {{ background:#1e293b; border-radius:12px; padding:1.5rem; margin:1rem 0; }}
  .stat {{ display:inline-block; margin:0 2rem 1rem 0; }}
  .stat-val {{ font-size:2rem; font-weight:700; color:#818cf8; }}
  .stat-lbl {{ font-size:.8rem; color:#94a3b8; }}
  pre {{ background:#0f172a; padding:1rem; border-radius:8px; overflow-x:auto; font-size:.9rem; color:#a5f3fc; }}
  canvas {{ width:100%; height:250px; }}
  .badge {{ display:inline-block; padding:.25rem .75rem; border-radius:99px; font-size:.85rem; }}
</style></head><body>
<h1>🧬 sauravevolve — {problem.name}</h1>
<p style="color:#94a3b8">{problem.description}</p>

<div class="card">
  <div class="stat"><div class="stat-val">{stats.best_passed}/{stats.total_cases}</div><div class="stat-lbl">Cases Passed</div></div>
  <div class="stat"><div class="stat-val">{stats.generation}</div><div class="stat-lbl">Generations</div></div>
  <div class="stat"><div class="stat-val">{stats.elapsed_sec:.1f}s</div><div class="stat-lbl">Time</div></div>
  <div class="stat">{solved_badge}</div>
</div>

<div class="card">
  <h3 style="margin-bottom:.5rem">📈 Fitness Over Generations</h3>
  <canvas id="chart"></canvas>
</div>

<div class="card">
  <h3 style="margin-bottom:.5rem">🏆 Best Program</h3>
  <pre>{escaped_code}</pre>
</div>

<script>
const history = {history_json};
const canvas = document.getElementById('chart');
const ctx = canvas.getContext('2d');
function draw() {{
  const W = canvas.width = canvas.offsetWidth;
  const H = canvas.height = 250;
  ctx.clearRect(0,0,W,H);
  if (!history.length) return;
  const pad = 40;
  const pw = (W - 2*pad) / Math.max(history.length - 1, 1);

  // Grid
  ctx.strokeStyle = '#334155'; ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {{
    const y = pad + (H - 2*pad) * i / 4;
    ctx.beginPath(); ctx.moveTo(pad, y); ctx.lineTo(W-pad, y); ctx.stroke();
    ctx.fillStyle = '#64748b'; ctx.font = '11px sans-serif';
    ctx.fillText((1 - i/4).toFixed(2), 2, y + 4);
  }}

  // Best fitness line
  ctx.strokeStyle = '#818cf8'; ctx.lineWidth = 2;
  ctx.beginPath();
  history.forEach((h, i) => {{
    const x = pad + i * pw;
    const y = pad + (H - 2*pad) * (1 - h.best_fitness);
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }});
  ctx.stroke();

  // Avg fitness line
  ctx.strokeStyle = '#475569'; ctx.lineWidth = 1;
  ctx.beginPath();
  history.forEach((h, i) => {{
    const x = pad + i * pw;
    const y = pad + (H - 2*pad) * (1 - h.avg_fitness);
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }});
  ctx.stroke();

  ctx.fillStyle = '#94a3b8'; ctx.font = '11px sans-serif';
  ctx.fillText('Generation', W/2 - 30, H - 5);
}}
draw(); window.addEventListener('resize', draw);
</script>
</body></html>"""


# ── Interactive REPL ────────────────────────────────────────────────

def repl():
    """Interactive evolution REPL."""
    print("\n🧬 sauravevolve — Genetic Programming for sauravcode")
    print("=" * 50)
    print("Commands: list, solve <name>, autopilot, custom, help, quit\n")

    while True:
        try:
            cmd = input("evolve> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not cmd:
            continue

        parts = cmd.split()
        verb = parts[0].lower()

        if verb in ("quit", "exit", "q"):
            print("Bye!")
            break
        elif verb == "list":
            print(f"\n  {'Problem':<15} {'Description'}")
            print(f"  {'─'*15} {'─'*35}")
            for name, prob in BUILTIN_PROBLEMS.items():
                print(f"  {name:<15} {prob.description[:35]}")
            print()
        elif verb == "solve" and len(parts) >= 2:
            name = parts[1]
            if name not in BUILTIN_PROBLEMS:
                print(f"  Unknown problem: {name}. Use 'list' to see options.")
                continue
            pop = int(parts[2]) if len(parts) > 2 else 100
            gens = int(parts[3]) if len(parts) > 3 else 50
            prob = BUILTIN_PROBLEMS[name]
            print(f"\n  🎯 Evolving: {prob.description}")
            print(f"  Population: {pop}, Max gens: {gens}\n")
            stats = evolve(prob, pop_size=pop, max_gens=gens)
            print(f"\n  Best program ({stats.best_passed}/{stats.total_cases} cases):")
            print(f"  {'─'*40}")
            for line in stats.best_code.split("\n"):
                print(f"    {line}")
            print()
        elif verb == "autopilot":
            run_autopilot()
        elif verb == "custom":
            print("  Enter JSON test cases (end with blank line):")
            json_lines = []
            while True:
                line = input("  ")
                if not line:
                    break
                json_lines.append(line)
            try:
                data = json.loads("\n".join(json_lines))
                prob = Problem(
                    name=data.get("name", "custom"),
                    description=data.get("description", "Custom problem"),
                    cases=[TestCase(c["input"], c["expected"]) for c in data["cases"]],
                )
                stats = evolve(prob)
                print(f"\n  Best ({stats.best_passed}/{stats.total_cases}):")
                for line in stats.best_code.split("\n"):
                    print(f"    {line}")
            except (json.JSONDecodeError, KeyError) as e:
                print(f"  Invalid JSON: {e}")
        elif verb == "help":
            print("""
  list                    — Show built-in problems
  solve <name> [pop] [gen] — Evolve a solution
  autopilot               — Auto-solve all problems
  custom                  — Define custom test cases (JSON)
  quit                    — Exit
""")
        else:
            print(f"  Unknown command: {verb}. Type 'help'.")


# ── CLI ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="sauravevolve — Genetic programming for sauravcode")
    parser.add_argument("--problem", help="Built-in problem to solve")
    parser.add_argument("--cases", help="JSON file with custom test cases")
    parser.add_argument("--list", action="store_true", help="List problems")
    parser.add_argument("--autopilot", action="store_true", help="Solve all")
    parser.add_argument("--pop", type=int, default=100, help="Population size")
    parser.add_argument("--gens", type=int, default=50, help="Max generations")
    parser.add_argument("--seed", type=int, help="Random seed")
    parser.add_argument("--report", action="store_true", help="HTML report")
    parser.add_argument("--mutation-rate", type=float, default=0.4)

    args = parser.parse_args()

    if args.list:
        print(f"\n  {'Problem':<15} {'Cases':<7} Description")
        print(f"  {'─'*15} {'─'*7} {'─'*35}")
        for name, prob in BUILTIN_PROBLEMS.items():
            print(f"  {name:<15} {len(prob.cases):<7} {prob.description[:40]}")
        return

    if args.autopilot:
        run_autopilot(pop_size=args.pop, max_gens=args.gens)
        return

    if args.cases:
        with open(args.cases) as f:
            data = json.load(f)
        prob = Problem(
            name=data.get("name", "custom"),
            description=data.get("description", "Custom"),
            cases=[TestCase(c["input"], c["expected"]) for c in data["cases"]],
        )
    elif args.problem:
        if args.problem not in BUILTIN_PROBLEMS:
            print(f"Unknown problem: {args.problem}")
            print(f"Available: {', '.join(BUILTIN_PROBLEMS.keys())}")
            return
        prob = BUILTIN_PROBLEMS[args.problem]
    else:
        repl()
        return

    print(f"\n🧬 sauravevolve — Evolving: {prob.name}")
    print(f"   {prob.description}")
    print(f"   Population: {args.pop}, Max generations: {args.gens}\n")

    stats = evolve(prob, pop_size=args.pop, max_gens=args.gens,
                   mutation_rate=args.mutation_rate, seed=args.seed)

    print(f"\n{'═' * 50}")
    if stats.solved:
        print(f"  ✅ SOLVED in generation {stats.solve_gen} ({stats.elapsed_sec:.1f}s)")
    else:
        print(f"  ❌ Best: {stats.best_passed}/{stats.total_cases} after {stats.generation+1} generations")
    print(f"{'═' * 50}")
    print(f"\nBest program:")
    print(f"{'─' * 40}")
    print(stats.best_code)
    print(f"{'─' * 40}")

    if args.report:
        path = f"sauravevolve_report_{prob.name}.html"
        with open(path, "w", encoding="utf-8") as f:
            f.write(generate_report(stats, prob))
        print(f"\n📄 Report saved to {path}")


if __name__ == "__main__":
    main()
