#!/usr/bin/env python3
"""sauravalchemy — Code Transmutation Engine for sauravcode (.srv).

Analyzes .srv programs and generates equivalent implementations in different
programming paradigms.  Shows side-by-side comparisons with trade-off analysis.

Transmutations:
  1. Imperative → Functional (loops → comprehensions / map / filter / reduce)
  2. Recursive → Iterative (recursion → stack-based loops)
  3. Iterative → Recursive (for/while → tail-recursive equivalents)
  4. Verbose → Concise (syntactic sugar expansion / collapse)
  5. Inline → Extracted (long expressions → named helper variables)
  6. Eager → Lazy (list builds → generator patterns)

Also includes:
  - Paradigm profile scoring (how functional/imperative/OOP each file is)
  - Transmutation difficulty estimation
  - Trade-off analysis (readability, performance, memory)
  - Proactive style recommendations
  - Interactive HTML lab report

Usage:
    python sauravalchemy.py <file.srv>                # Full analysis + HTML report
    python sauravalchemy.py <file.srv> --transmute     # Apply all transmutations
    python sauravalchemy.py <file.srv> --functional    # Imperative → Functional only
    python sauravalchemy.py <file.srv> --iterative     # Recursive → Iterative only
    python sauravalchemy.py <file.srv> --recursive     # Iterative → Recursive only
    python sauravalchemy.py <file.srv> --concise       # Verbose → Concise only
    python sauravalchemy.py <file.srv> --extract       # Inline → Extracted only
    python sauravalchemy.py <file.srv> --lazy          # Eager → Lazy only
    python sauravalchemy.py <file.srv> --profile       # Paradigm profile only
    python sauravalchemy.py <file.srv> --json          # JSON output
    python sauravalchemy.py <file.srv> --html FILE     # Custom HTML output path
    python sauravalchemy.py <file.srv> --no-html       # Skip HTML, text only
    python sauravalchemy.py <dir>                      # Analyze all .srv in directory
    python sauravalchemy.py <dir> --watch              # Re-analyze on file changes
"""

import sys
import os
import io
import re
import json
import math
import time
import hashlib
import argparse
from collections import defaultdict, Counter
from pathlib import Path
from datetime import datetime

# Fix Windows console encoding
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from _termcolors import colors
    C = colors()
except ImportError:
    class _Stub:
        def __getattr__(self, _):
            return lambda t: str(t)
    C = _Stub()

# ── Regex patterns for sauravcode constructs ──────────────────────────

RE_FUN = re.compile(r'^fun\s+(\w+)\s*\(([^)]*)\)', re.MULTILINE)
RE_CLASS = re.compile(r'^class\s+(\w+)', re.MULTILINE)
RE_FOR = re.compile(r'^(\s*)for\s+(\w+)\s+in\s+(.+?)$', re.MULTILINE)
RE_WHILE = re.compile(r'^(\s*)while\s+(.+?)$', re.MULTILINE)
RE_IF = re.compile(r'^(\s*)if\s+(.+?)$', re.MULTILINE)
RE_ASSIGN = re.compile(r'^(\s*)(\w+)\s*=\s*(.+)$', re.MULTILINE)
RE_RETURN = re.compile(r'^(\s*)return\s+(.+)$', re.MULTILINE)
RE_CALL = re.compile(r'\b(\w+)\s*\(')
RE_LISTCOMP = re.compile(r'\[(.+?)\s+for\s+(\w+)\s+in\s+(.+?)(?:\s+if\s+(.+?))?\]')
RE_PIPE = re.compile(r'\|>')
RE_MATCH = re.compile(r'^(\s*)match\s+', re.MULTILINE)
RE_LAMBDA = re.compile(r'\blambda\b')
RE_YIELD = re.compile(r'\byield\b')
RE_COMMENT = re.compile(r'^\s*#', re.MULTILINE)
RE_APPEND_LOOP = re.compile(
    r'^(\s*)(\w+)\s*=\s*\[\]\s*\n'
    r'(\s*)for\s+(\w+)\s+in\s+(.+?)\s*\n'
    r'\s+\2\.append\((.+?)\)',
    re.MULTILINE
)
RE_ACCUM_LOOP = re.compile(
    r'^(\s*)(\w+)\s*=\s*(\d+(?:\.\d+)?)\s*\n'
    r'(\s*)for\s+(\w+)\s+in\s+(.+?)\s*\n'
    r'\s+\2\s*=\s*\2\s*([+\-*/])\s*(.+)',
    re.MULTILINE
)
RE_FILTER_LOOP = re.compile(
    r'^(\s*)(\w+)\s*=\s*\[\]\s*\n'
    r'(\s*)for\s+(\w+)\s+in\s+(.+?)\s*\n'
    r'\s+if\s+(.+?)\s*\n'
    r'\s+\2\.append\((.+?)\)',
    re.MULTILINE
)
RE_RECURSIVE_CALL = re.compile(r'fun\s+(\w+)\s*\(([^)]*)\)[^}]*?\b\1\s*\(', re.DOTALL)

# ── Paradigm Profile ─────────────────────────────────────────────────

def compute_paradigm_profile(source):
    """Score how functional / imperative / OOP a piece of code is."""
    lines = source.strip().split('\n')
    total = max(len(lines), 1)

    # Functional indicators
    func_score = 0
    func_score += len(RE_LISTCOMP.findall(source)) * 3
    func_score += len(RE_PIPE.findall(source)) * 2
    func_score += len(RE_LAMBDA.findall(source)) * 2
    func_score += len(RE_YIELD.findall(source)) * 2
    func_score += source.count('map(') * 2
    func_score += source.count('filter(') * 2
    func_score += source.count('reduce(') * 3
    # Recursive functions
    for m in RE_FUN.finditer(source):
        fname = m.group(1)
        # Check if function body calls itself
        start = m.end()
        depth = 0
        end = start
        for i in range(start, len(source)):
            if source[i] == '\n' and depth == 0 and i > start + 5:
                # Scan ahead for next top-level definition
                rest = source[i+1:i+20]
                if rest.startswith('fun ') or rest.startswith('class ') or (rest.strip() and not rest[0].isspace()):
                    end = i
                    break
        else:
            end = len(source)
        body = source[start:end]
        if re.search(rf'\b{re.escape(fname)}\s*\(', body):
            func_score += 3

    # Imperative indicators
    imp_score = 0
    imp_score += len(RE_FOR.findall(source)) * 2
    imp_score += len(RE_WHILE.findall(source)) * 3
    imp_score += source.count(' = ') * 0.5  # Mutation
    imp_score += source.count(' += ') * 1
    imp_score += source.count(' -= ') * 1
    imp_score += source.count('.append(') * 1
    imp_score += source.count('.remove(') * 1

    # OOP indicators
    oop_score = 0
    oop_score += len(RE_CLASS.findall(source)) * 5
    oop_score += source.count('self.') * 1
    oop_score += source.count('.init(') * 2
    oop_score += source.count('extends ') * 3

    total_score = max(func_score + imp_score + oop_score, 1)
    return {
        'functional': round(func_score / total_score * 100, 1),
        'imperative': round(imp_score / total_score * 100, 1),
        'oop': round(oop_score / total_score * 100, 1),
        'raw': {'functional': func_score, 'imperative': imp_score, 'oop': oop_score},
        'dominant': max(
            [('functional', func_score), ('imperative', imp_score), ('oop', oop_score)],
            key=lambda x: x[1]
        )[0]
    }


# ── Transmutation: Imperative → Functional ────────────────────────────

def _transmute_to_functional(source):
    """Convert imperative patterns to functional equivalents."""
    transmutations = []

    # 1. Accumulator loops → reduce
    for m in RE_ACCUM_LOOP.finditer(source):
        indent, var, init, _, itervar, collection, op, expr = m.groups()
        original = m.group(0)
        if itervar in expr:
            body_expr = expr.replace(itervar, 'x')
        else:
            body_expr = expr
        functional = f'{indent}{var} = reduce(lambda acc, x: acc {op} {body_expr}, {collection}, {init})'
        transmutations.append({
            'type': 'imperative_to_functional',
            'name': f'Accumulator loop → reduce()',
            'original': original,
            'transmuted': functional,
            'explanation': f'The loop accumulates into `{var}` using `{op}` — this is the classic reduce pattern.',
            'trade_offs': {
                'readability': 'Reduce can be harder to read for beginners, but clearly expresses intent for experienced devs',
                'performance': 'Similar — both are O(n)',
                'memory': 'Reduce avoids the mutable variable'
            },
            'difficulty': 'easy'
        })

    # 2. Filter-append loops → list comprehension with condition
    for m in RE_FILTER_LOOP.finditer(source):
        indent, var, _, itervar, collection, condition, body = m.groups()
        original = m.group(0)
        functional = f'{indent}{var} = [{body} for {itervar} in {collection} if {condition}]'
        transmutations.append({
            'type': 'imperative_to_functional',
            'name': 'Filter loop → list comprehension',
            'original': original,
            'transmuted': functional,
            'explanation': f'The loop builds `{var}` by filtering — a list comprehension with `if` is equivalent.',
            'trade_offs': {
                'readability': 'Comprehension is more concise and idiomatic',
                'performance': 'Comprehension is slightly faster (no method dispatch for .append)',
                'memory': 'Both create the full list'
            },
            'difficulty': 'easy'
        })

    # 3. Append loops → list comprehension
    for m in RE_APPEND_LOOP.finditer(source):
        indent, var, _, itervar, collection, body = m.groups()
        original = m.group(0)
        functional = f'{indent}{var} = [{body} for {itervar} in {collection}]'
        transmutations.append({
            'type': 'imperative_to_functional',
            'name': 'Append loop → list comprehension',
            'original': original,
            'transmuted': functional,
            'explanation': f'The loop builds `{var}` via append — direct comprehension is equivalent.',
            'trade_offs': {
                'readability': 'More concise, clearly expresses mapping intent',
                'performance': 'Slightly faster (no .append overhead)',
                'memory': 'Same — both create full list'
            },
            'difficulty': 'easy'
        })

    return transmutations


# ── Transmutation: Recursive → Iterative ──────────────────────────────

def _transmute_recursive_to_iterative(source):
    """Detect recursive functions and suggest iterative equivalents."""
    transmutations = []
    functions = list(RE_FUN.finditer(source))

    for m in functions:
        fname = m.group(1)
        params = m.group(2).strip()
        start = m.end()

        # Find function body (indented block after fun declaration)
        lines = source[start:].split('\n')
        body_lines = []
        for line in lines:
            if line.strip() == '':
                body_lines.append(line)
                continue
            if body_lines and line and not line[0].isspace():
                break
            body_lines.append(line)

        body = '\n'.join(body_lines)

        # Check if recursive
        if not re.search(rf'\b{re.escape(fname)}\s*\(', body):
            continue

        # Detect tail recursion pattern: return fname(...)
        is_tail = bool(re.search(rf'return\s+{re.escape(fname)}\s*\(', body))

        param_list = [p.strip() for p in params.split(',') if p.strip()]

        if is_tail and param_list:
            # Generate iterative equivalent for tail recursion
            iter_params = ', '.join(param_list)
            original = f'fun {fname}({params})\n{body.rstrip()}'
            iterative = f'fun {fname}({params})\n'
            iterative += f'    while true\n'
            iterative += f'        # base case check goes here\n'
            iterative += f'        # update {iter_params} for next iteration\n'
            iterative += f'        # instead of return {fname}(...)\n'

            transmutations.append({
                'type': 'recursive_to_iterative',
                'name': f'Tail recursion → while loop ({fname})',
                'original': original.strip(),
                'transmuted': iterative.strip(),
                'explanation': f'`{fname}` uses tail recursion — the recursive call is the last operation. '
                               f'This can be mechanically converted to a while loop by updating parameters in-place.',
                'trade_offs': {
                    'readability': 'Iterative may be clearer for simple tail recursion',
                    'performance': 'Iterative avoids call stack overhead — O(1) stack vs O(n)',
                    'memory': 'Iterative uses O(1) memory vs O(n) stack frames'
                },
                'difficulty': 'medium'
            })
        elif param_list:
            # Non-tail recursion → explicit stack
            original = f'fun {fname}({params})\n{body.rstrip()}'
            iterative = f'fun {fname}_iterative({params})\n'
            iterative += f'    stack = [({", ".join(param_list)})]\n'
            iterative += f'    result = none\n'
            iterative += f'    while not stack.is_empty()\n'
            iterative += f'        frame = stack.pop()\n'
            iterative += f'        # process frame, push sub-problems to stack\n'

            transmutations.append({
                'type': 'recursive_to_iterative',
                'name': f'Recursion → explicit stack ({fname})',
                'original': original.strip(),
                'transmuted': iterative.strip(),
                'explanation': f'`{fname}` uses non-tail recursion — it needs an explicit stack to convert. '
                               f'Each recursive call becomes a push; each return becomes a pop.',
                'trade_offs': {
                    'readability': 'Explicit stack is more complex but avoids stack overflow',
                    'performance': 'Slightly faster (no function call overhead)',
                    'memory': 'Heap stack can be larger than call stack limit'
                },
                'difficulty': 'hard'
            })

    return transmutations


# ── Transmutation: Iterative → Recursive ──────────────────────────────

def _transmute_iterative_to_recursive(source):
    """Detect iterative patterns and suggest recursive equivalents."""
    transmutations = []

    for m in RE_FOR.finditer(source):
        indent, itervar, collection = m.groups()
        # Find the loop body
        start_line = source[:m.start()].count('\n')
        lines = source.split('\n')
        body_lines = []
        i = start_line + 1
        while i < len(lines):
            line = lines[i]
            if line.strip() == '':
                body_lines.append(line)
                i += 1
                continue
            if line and not line.startswith(indent + '    ') and not line.startswith(indent + '\t'):
                break
            body_lines.append(line)
            i += 1

        if not body_lines:
            continue

        body = '\n'.join(body_lines).strip()
        if len(body.split('\n')) > 5:
            continue  # Skip complex loops

        original = f'{indent}for {itervar} in {collection}\n' + '\n'.join(body_lines)

        recursive = (
            f'{indent}fun process_{itervar}s(items)\n'
            f'{indent}    if len(items) == 0\n'
            f'{indent}        return\n'
            f'{indent}    {itervar} = items[0]\n'
            f'{indent}    {body.strip()}\n'
            f'{indent}    process_{itervar}s(items[1:])'
        )

        transmutations.append({
            'type': 'iterative_to_recursive',
            'name': f'For loop → recursive function',
            'original': original.strip(),
            'transmuted': recursive.strip(),
            'explanation': f'The for loop over `{collection}` can be expressed as head/tail recursion: '
                           f'process first element, recurse on the rest.',
            'trade_offs': {
                'readability': 'Recursive version is more elegant for list processing',
                'performance': 'Recursion has call overhead; risk of stack overflow on large lists',
                'memory': 'O(n) stack frames vs O(1) for the loop'
            },
            'difficulty': 'medium'
        })

    return transmutations


# ── Transmutation: Verbose → Concise ──────────────────────────────────

def _transmute_verbose_to_concise(source):
    """Detect verbose patterns and suggest concise equivalents."""
    transmutations = []

    # 1. if x == true → if x
    for m in re.finditer(r'^(\s*)if\s+(\w+)\s*==\s*true\b', source, re.MULTILINE):
        indent, var = m.groups()
        transmutations.append({
            'type': 'verbose_to_concise',
            'name': 'Redundant boolean comparison',
            'original': m.group(0),
            'transmuted': f'{indent}if {var}',
            'explanation': f'`{var} == true` is equivalent to just `{var}` — the comparison is redundant.',
            'trade_offs': {
                'readability': 'More concise and idiomatic',
                'performance': 'Saves one comparison operation',
                'memory': 'No difference'
            },
            'difficulty': 'easy'
        })

    # 2. if x == false → if not x
    for m in re.finditer(r'^(\s*)if\s+(\w+)\s*==\s*false\b', source, re.MULTILINE):
        indent, var = m.groups()
        transmutations.append({
            'type': 'verbose_to_concise',
            'name': 'Redundant boolean comparison (false)',
            'original': m.group(0),
            'transmuted': f'{indent}if not {var}',
            'explanation': f'`{var} == false` is equivalent to `not {var}`.',
            'trade_offs': {
                'readability': 'More natural to read',
                'performance': 'Saves one comparison',
                'memory': 'No difference'
            },
            'difficulty': 'easy'
        })

    # 3. Verbose if/else return → ternary
    ternary_pat = re.compile(
        r'^(\s*)if\s+(.+?)\s*\n'
        r'\s+return\s+(.+?)\s*\n'
        r'\s*else\s*\n'
        r'\s+return\s+(.+?)$',
        re.MULTILINE
    )
    for m in ternary_pat.finditer(source):
        indent, cond, true_val, false_val = m.groups()
        transmutations.append({
            'type': 'verbose_to_concise',
            'name': 'If/else return → ternary',
            'original': m.group(0),
            'transmuted': f'{indent}return {true_val} if {cond} else {false_val}',
            'explanation': 'Two-branch if/else that just returns can be a single ternary expression.',
            'trade_offs': {
                'readability': 'Concise for simple cases; avoid for complex conditions',
                'performance': 'Identical',
                'memory': 'No difference'
            },
            'difficulty': 'easy'
        })

    # 4. len(x) == 0 → x is empty
    for m in re.finditer(r'len\((\w+)\)\s*==\s*0', source):
        var = m.group(1)
        transmutations.append({
            'type': 'verbose_to_concise',
            'name': 'Length check → emptiness check',
            'original': m.group(0),
            'transmuted': f'not {var}',
            'explanation': f'`len({var}) == 0` is equivalent to `not {var}` — empty collections are falsy.',
            'trade_offs': {
                'readability': 'More idiomatic',
                'performance': 'Avoids len() call',
                'memory': 'No difference'
            },
            'difficulty': 'easy'
        })

    return transmutations


# ── Transmutation: Inline → Extracted ─────────────────────────────────

def _transmute_inline_to_extracted(source):
    """Detect long inline expressions and suggest extraction."""
    transmutations = []

    for m in RE_ASSIGN.finditer(source):
        indent, var, expr = m.groups()
        if len(expr.strip()) > 80 and expr.count('(') >= 2:
            # Complex expression — suggest extraction
            parts = re.split(r'(?<=\))\s*[+\-*/]?\s*(?=\w+\()', expr.strip())
            if len(parts) >= 2:
                extracted_lines = []
                part_vars = []
                for i, part in enumerate(parts):
                    pvar = f'_part_{i+1}'
                    extracted_lines.append(f'{indent}{pvar} = {part.strip()}')
                    part_vars.append(pvar)
                extracted_lines.append(f'{indent}{var} = {" + ".join(part_vars)}')
                transmutations.append({
                    'type': 'inline_to_extracted',
                    'name': 'Long expression → named parts',
                    'original': m.group(0),
                    'transmuted': '\n'.join(extracted_lines),
                    'explanation': 'Breaking complex expressions into named parts improves readability and debuggability.',
                    'trade_offs': {
                        'readability': 'Much clearer — each part has a descriptive name',
                        'performance': 'Negligible overhead from extra variable bindings',
                        'memory': 'Slightly more variables on the stack'
                    },
                    'difficulty': 'easy'
                })

    return transmutations


# ── Transmutation: Eager → Lazy ───────────────────────────────────────

def _transmute_eager_to_lazy(source):
    """Detect eager list building and suggest lazy/generator alternatives."""
    transmutations = []

    # List comprehension used only in a for loop → generator
    for m in re.finditer(r'for\s+(\w+)\s+in\s+\[(.+?)\s+for\s+(\w+)\s+in\s+(.+?)(?:\s+if\s+(.+?))?\]',
                         source):
        itervar, expr, inner_var, collection, cond = m.groups()
        cond_part = f' if {cond}' if cond else ''
        transmutations.append({
            'type': 'eager_to_lazy',
            'name': 'List comprehension in for → generator',
            'original': m.group(0),
            'transmuted': f'for {itervar} in ({expr} for {inner_var} in {collection}{cond_part})',
            'explanation': 'When iterating over a comprehension, a generator avoids building the full list.',
            'trade_offs': {
                'readability': 'Identical syntax except [ ] → ( )',
                'performance': 'Lazy evaluation — starts yielding immediately',
                'memory': 'O(1) vs O(n) — generator yields one item at a time'
            },
            'difficulty': 'easy'
        })

    return transmutations


# ── Main Analysis Engine ──────────────────────────────────────────────

def analyze_file(filepath):
    """Run all transmutation analyses on a single .srv file."""
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        source = f.read()

    filename = os.path.basename(filepath)
    lines = source.strip().split('\n')
    line_count = len(lines)

    # Paradigm profile
    profile = compute_paradigm_profile(source)

    # Run all transmutations
    all_transmutations = []
    all_transmutations.extend(_transmute_to_functional(source))
    all_transmutations.extend(_transmute_recursive_to_iterative(source))
    all_transmutations.extend(_transmute_iterative_to_recursive(source))
    all_transmutations.extend(_transmute_verbose_to_concise(source))
    all_transmutations.extend(_transmute_inline_to_extracted(source))
    all_transmutations.extend(_transmute_eager_to_lazy(source))

    # Compute transmutability score (how many transformations are possible)
    transmutability = min(100, len(all_transmutations) * 10)

    # Difficulty distribution
    difficulties = Counter(t['difficulty'] for t in all_transmutations)

    # Type distribution
    type_dist = Counter(t['type'] for t in all_transmutations)

    # Proactive recommendations
    recommendations = _generate_recommendations(profile, all_transmutations, line_count)

    return {
        'file': filename,
        'path': str(filepath),
        'lines': line_count,
        'profile': profile,
        'transmutations': all_transmutations,
        'transmutability': transmutability,
        'difficulty_distribution': dict(difficulties),
        'type_distribution': dict(type_dist),
        'recommendations': recommendations,
        'timestamp': datetime.now().isoformat()
    }


def _generate_recommendations(profile, transmutations, line_count):
    """Generate proactive style and paradigm recommendations."""
    recs = []

    # Paradigm balance
    if profile['imperative'] > 70:
        recs.append({
            'icon': '🔄',
            'title': 'Heavy imperative style detected',
            'detail': f'Your code is {profile["imperative"]}% imperative. Consider list comprehensions '
                      f'or map/filter for data transformations — they are more concise and expressive.',
            'priority': 'medium'
        })
    if profile['functional'] > 80:
        recs.append({
            'icon': '📐',
            'title': 'Very functional style',
            'detail': f'Your code is {profile["functional"]}% functional. While elegant, ensure deep recursion '
                      f'has base cases and consider iterative alternatives for performance-critical paths.',
            'priority': 'low'
        })
    if profile['oop'] > 70:
        recs.append({
            'icon': '🏗️',
            'title': 'Heavy OOP style',
            'detail': f'Your code is {profile["oop"]}% OOP. Consider whether simple functions with data '
                      f'could replace some classes — simpler is often better.',
            'priority': 'low'
        })

    # Transmutation opportunities
    func_count = sum(1 for t in transmutations if t['type'] == 'imperative_to_functional')
    if func_count >= 3:
        recs.append({
            'icon': '✨',
            'title': f'{func_count} functional transmutations available',
            'detail': 'Multiple loops could be replaced with comprehensions or reduce. '
                      'This would make the code more declarative and easier to reason about.',
            'priority': 'high'
        })

    rec_to_iter = sum(1 for t in transmutations if t['type'] == 'recursive_to_iterative')
    if rec_to_iter >= 2:
        recs.append({
            'icon': '⚡',
            'title': f'{rec_to_iter} recursive functions could be iterative',
            'detail': 'Consider converting tail-recursive functions to loops for better stack safety.',
            'priority': 'medium'
        })

    verbose_count = sum(1 for t in transmutations if t['type'] == 'verbose_to_concise')
    if verbose_count >= 3:
        recs.append({
            'icon': '✂️',
            'title': f'{verbose_count} verbosity reductions available',
            'detail': 'Several patterns can be simplified. Concise code has fewer bugs.',
            'priority': 'low'
        })

    if not transmutations:
        recs.append({
            'icon': '🎯',
            'title': 'Code is already well-balanced',
            'detail': 'No obvious paradigm transmutations detected. Your code uses appropriate patterns.',
            'priority': 'info'
        })

    if line_count > 200 and not any(t['type'] == 'inline_to_extracted' for t in transmutations):
        recs.append({
            'icon': '📦',
            'title': 'Consider extracting helper functions',
            'detail': f'At {line_count} lines, breaking large functions into smaller pieces improves testability.',
            'priority': 'medium'
        })

    return recs


# ── Multi-file / Directory Analysis ───────────────────────────────────

def analyze_directory(dirpath, max_depth=5):
    """Analyze all .srv files in a directory."""
    results = []
    for root, dirs, files in os.walk(dirpath):
        depth = root.replace(str(dirpath), '').count(os.sep)
        if depth >= max_depth:
            dirs.clear()
            continue
        for fname in sorted(files):
            if fname.endswith('.srv'):
                fpath = os.path.join(root, fname)
                try:
                    results.append(analyze_file(fpath))
                except Exception as e:
                    results.append({
                        'file': fname,
                        'path': fpath,
                        'error': str(e)
                    })
    return results


def aggregate_results(results):
    """Compute project-wide summary from individual file analyses."""
    valid = [r for r in results if 'error' not in r]
    if not valid:
        return {'files': 0, 'error': 'No valid files analyzed'}

    total_trans = sum(len(r['transmutations']) for r in valid)
    avg_transmutability = sum(r['transmutability'] for r in valid) / len(valid)

    # Aggregate paradigm profile
    avg_profile = {
        'functional': round(sum(r['profile']['functional'] for r in valid) / len(valid), 1),
        'imperative': round(sum(r['profile']['imperative'] for r in valid) / len(valid), 1),
        'oop': round(sum(r['profile']['oop'] for r in valid) / len(valid), 1),
    }
    dominant = max(avg_profile, key=avg_profile.get)

    # Type distribution across project
    type_totals = Counter()
    for r in valid:
        type_totals.update(r['type_distribution'])

    # Files with most transmutation opportunities
    hotspots = sorted(valid, key=lambda r: len(r['transmutations']), reverse=True)[:5]

    return {
        'files': len(valid),
        'errors': len(results) - len(valid),
        'total_transmutations': total_trans,
        'avg_transmutability': round(avg_transmutability, 1),
        'project_profile': avg_profile,
        'dominant_paradigm': dominant,
        'type_distribution': dict(type_totals),
        'hotspots': [{'file': h['file'], 'count': len(h['transmutations'])} for h in hotspots],
    }


# ── HTML Report ───────────────────────────────────────────────────────

def generate_html(results, summary=None, output_path='sauravalchemy_report.html'):
    """Generate interactive HTML lab report."""
    is_multi = isinstance(results, list)
    if not is_multi:
        results = [results]

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>⚗️ sauravalchemy — Code Transmutation Lab</title>
<style>
  :root {{
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #c9d1d9; --text-dim: #8b949e; --accent: #58a6ff;
    --green: #3fb950; --yellow: #d29922; --red: #f85149;
    --purple: #bc8cff; --orange: #f0883e; --cyan: #39d2c0;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, 'Segoe UI', sans-serif; background: var(--bg);
         color: var(--text); line-height: 1.6; padding: 2rem; }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
  h1 {{ color: var(--accent); margin-bottom: 0.5rem; font-size: 1.8rem; }}
  h2 {{ color: var(--purple); margin: 1.5rem 0 0.8rem; font-size: 1.3rem; }}
  h3 {{ color: var(--cyan); margin: 1rem 0 0.5rem; }}
  .subtitle {{ color: var(--text-dim); margin-bottom: 2rem; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
           gap: 1rem; margin: 1rem 0; }}
  .card {{ background: var(--surface); border: 1px solid var(--border);
           border-radius: 8px; padding: 1.2rem; }}
  .metric {{ font-size: 2rem; font-weight: 700; }}
  .metric-label {{ color: var(--text-dim); font-size: 0.85rem; text-transform: uppercase; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px;
            font-size: 0.75rem; font-weight: 600; }}
  .badge-easy {{ background: #1a3a2a; color: var(--green); }}
  .badge-medium {{ background: #3a2a1a; color: var(--yellow); }}
  .badge-hard {{ background: #3a1a1a; color: var(--red); }}
  .badge-info {{ background: #1a2a3a; color: var(--accent); }}
  .transmutation {{ background: var(--surface); border: 1px solid var(--border);
                    border-radius: 8px; margin: 0.8rem 0; overflow: hidden; }}
  .trans-header {{ padding: 0.8rem 1rem; display: flex; justify-content: space-between;
                   align-items: center; cursor: pointer; user-select: none; }}
  .trans-header:hover {{ background: rgba(88, 166, 255, 0.05); }}
  .trans-body {{ padding: 0 1rem 1rem; display: none; }}
  .trans-body.open {{ display: block; }}
  .code-block {{ background: #0d1117; border: 1px solid var(--border); border-radius: 6px;
                 padding: 0.8rem; font-family: 'Cascadia Code', 'Fira Code', monospace;
                 font-size: 0.85rem; overflow-x: auto; white-space: pre-wrap; margin: 0.5rem 0; }}
  .arrow {{ color: var(--purple); font-size: 1.5rem; text-align: center; padding: 0.3rem; }}
  .trade-offs {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.8rem; margin: 0.8rem 0; }}
  .trade-off {{ background: rgba(255,255,255,0.03); border-radius: 6px; padding: 0.6rem; }}
  .trade-off-label {{ font-weight: 600; font-size: 0.8rem; color: var(--accent); }}
  .recommendation {{ display: flex; gap: 1rem; padding: 0.8rem; border-left: 3px solid;
                     margin: 0.5rem 0; background: var(--surface); border-radius: 0 6px 6px 0; }}
  .rec-high {{ border-color: var(--red); }}
  .rec-medium {{ border-color: var(--yellow); }}
  .rec-low {{ border-color: var(--green); }}
  .rec-info {{ border-color: var(--accent); }}
  .rec-icon {{ font-size: 1.5rem; }}
  .radar {{ position: relative; width: 200px; height: 200px; margin: 1rem auto; }}
  .radar svg {{ width: 100%; height: 100%; }}
  .tab-bar {{ display: flex; gap: 0; border-bottom: 1px solid var(--border); margin: 1rem 0; }}
  .tab {{ padding: 0.5rem 1rem; cursor: pointer; color: var(--text-dim); border-bottom: 2px solid transparent; }}
  .tab:hover {{ color: var(--text); }}
  .tab.active {{ color: var(--accent); border-bottom-color: var(--accent); }}
  .tab-content {{ display: none; }}
  .tab-content.active {{ display: block; }}
  .progress {{ height: 8px; background: var(--border); border-radius: 4px; overflow: hidden; }}
  .progress-bar {{ height: 100%; border-radius: 4px; transition: width 0.5s; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ text-align: left; padding: 0.5rem; border-bottom: 1px solid var(--border); }}
  th {{ color: var(--text-dim); font-size: 0.8rem; text-transform: uppercase; }}
  footer {{ text-align: center; color: var(--text-dim); margin-top: 3rem; font-size: 0.8rem; }}
</style>
</head>
<body>
<div class="container">
  <h1>⚗️ sauravalchemy — Code Transmutation Lab</h1>
  <p class="subtitle">Autonomous paradigm transmutation engine for sauravcode</p>
"""

    # Summary section
    if summary and summary.get('files', 0) > 1:
        html += f"""
  <div class="grid">
    <div class="card"><div class="metric">{summary['files']}</div>
      <div class="metric-label">Files Analyzed</div></div>
    <div class="card"><div class="metric" style="color:var(--purple)">{summary['total_transmutations']}</div>
      <div class="metric-label">Transmutations Found</div></div>
    <div class="card"><div class="metric" style="color:var(--cyan)">{summary['avg_transmutability']}%</div>
      <div class="metric-label">Avg Transmutability</div></div>
    <div class="card"><div class="metric" style="color:var(--yellow)">{summary['dominant_paradigm'].title()}</div>
      <div class="metric-label">Dominant Paradigm</div></div>
  </div>
"""

    for result in results:
        if 'error' in result:
            html += f'<div class="card"><h3>{result["file"]}</h3><p style="color:var(--red)">{result["error"]}</p></div>'
            continue

        profile = result['profile']
        trans = result['transmutations']

        html += f"""
  <h2>📄 {result['file']} <span style="color:var(--text-dim);font-size:0.9rem">({result['lines']} lines)</span></h2>

  <h3>Paradigm Profile</h3>
  <div class="grid">
    <div class="card">
      <div style="display:flex;justify-content:space-between;margin-bottom:0.3rem">
        <span>Functional</span><span style="color:var(--green)">{profile['functional']}%</span>
      </div>
      <div class="progress"><div class="progress-bar" style="width:{profile['functional']}%;background:var(--green)"></div></div>
    </div>
    <div class="card">
      <div style="display:flex;justify-content:space-between;margin-bottom:0.3rem">
        <span>Imperative</span><span style="color:var(--yellow)">{profile['imperative']}%</span>
      </div>
      <div class="progress"><div class="progress-bar" style="width:{profile['imperative']}%;background:var(--yellow)"></div></div>
    </div>
    <div class="card">
      <div style="display:flex;justify-content:space-between;margin-bottom:0.3rem">
        <span>OOP</span><span style="color:var(--purple)">{profile['oop']}%</span>
      </div>
      <div class="progress"><div class="progress-bar" style="width:{profile['oop']}%;background:var(--purple)"></div></div>
    </div>
  </div>

  <div style="margin:0.5rem 0">
    <span style="color:var(--text-dim)">Dominant:</span>
    <strong style="color:var(--accent)">{profile['dominant'].title()}</strong>
    &nbsp;|&nbsp;
    <span style="color:var(--text-dim)">Transmutability:</span>
    <strong style="color:var(--cyan)">{result['transmutability']}%</strong>
  </div>
"""

        # Transmutations
        if trans:
            html += f'<h3>⚗️ Transmutations ({len(trans)})</h3>'
            for i, t in enumerate(trans):
                diff_class = f'badge-{t["difficulty"]}'
                tid = f'trans-{result["file"]}-{i}'
                html += f"""
  <div class="transmutation">
    <div class="trans-header" onclick="document.getElementById('{tid}').classList.toggle('open')">
      <span><strong>{t['name']}</strong></span>
      <span><span class="badge {diff_class}">{t['difficulty']}</span></span>
    </div>
    <div class="trans-body" id="{tid}">
      <p style="color:var(--text-dim);margin-bottom:0.5rem">{t['explanation']}</p>
      <div class="code-block" style="border-left:3px solid var(--red)">{_html_escape(t['original'])}</div>
      <div class="arrow">⬇️ transmutes to</div>
      <div class="code-block" style="border-left:3px solid var(--green)">{_html_escape(t['transmuted'])}</div>
      <h4 style="margin-top:0.8rem;color:var(--text-dim)">Trade-offs</h4>
      <div class="trade-offs">
        <div class="trade-off"><div class="trade-off-label">📖 Readability</div>{t['trade_offs']['readability']}</div>
        <div class="trade-off"><div class="trade-off-label">⚡ Performance</div>{t['trade_offs']['performance']}</div>
        <div class="trade-off"><div class="trade-off-label">💾 Memory</div>{t['trade_offs']['memory']}</div>
      </div>
    </div>
  </div>
"""
        else:
            html += '<p style="color:var(--text-dim)">No transmutations detected — code is well-optimized! 🎯</p>'

        # Recommendations
        if result['recommendations']:
            html += '<h3>💡 Proactive Recommendations</h3>'
            for rec in result['recommendations']:
                html += f"""
  <div class="recommendation rec-{rec['priority']}">
    <div class="rec-icon">{rec['icon']}</div>
    <div><strong>{rec['title']}</strong><br><span style="color:var(--text-dim)">{rec['detail']}</span></div>
  </div>
"""

    html += f"""
  <footer>
    <p>Generated by sauravalchemy — Code Transmutation Engine for sauravcode</p>
    <p>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
  </footer>
</div>
<script>
  // Auto-open first transmutation
  document.querySelectorAll('.trans-body')[0]?.classList.add('open');
</script>
</body>
</html>"""

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    return output_path


def _html_escape(text):
    """Escape HTML entities."""
    return (text.replace('&', '&amp;').replace('<', '&lt;')
                .replace('>', '&gt;').replace('"', '&quot;'))


# ── Text Output ───────────────────────────────────────────────────────

def print_text_report(result):
    """Print a text-mode analysis report."""
    if 'error' in result:
        print(C.red(f"Error analyzing {result['file']}: {result['error']}"))
        return

    profile = result['profile']
    trans = result['transmutations']

    print(C.bold(f"\n⚗️  sauravalchemy — {result['file']}"))
    print(f"   {result['lines']} lines | {len(trans)} transmutations | "
          f"transmutability: {result['transmutability']}%\n")

    print(C.bold("Paradigm Profile:"))
    bar_len = 30
    for name, val, color_fn in [
        ('Functional', profile['functional'], C.green),
        ('Imperative', profile['imperative'], C.yellow),
        ('OOP',        profile['oop'],        C.magenta),
    ]:
        filled = int(val / 100 * bar_len)
        bar = color_fn('█' * filled) + '░' * (bar_len - filled)
        print(f"  {name:12s} [{bar}] {val}%")
    print(f"  Dominant: {C.cyan(profile['dominant'].title())}\n")

    if trans:
        print(C.bold(f"Transmutations ({len(trans)}):"))
        for i, t in enumerate(trans, 1):
            diff_color = {'easy': C.green, 'medium': C.yellow, 'hard': C.red}.get(
                t['difficulty'], C.dim)
            print(f"\n  {C.bold(f'{i}.')} {t['name']} [{diff_color(t['difficulty'])}]")
            print(f"     {C.dim(t['explanation'])}")
            print(f"     {C.red('BEFORE:')} {t['original'][:80]}{'...' if len(t['original'])>80 else ''}")
            print(f"     {C.green('AFTER:')}  {t['transmuted'][:80]}{'...' if len(t['transmuted'])>80 else ''}")
    else:
        print(C.green("  No transmutations needed — code is already well-balanced! 🎯"))

    if result['recommendations']:
        print(C.bold(f"\nRecommendations:"))
        for rec in result['recommendations']:
            print(f"  {rec['icon']} {C.bold(rec['title'])}")
            print(f"     {C.dim(rec['detail'])}")


# ── Watch Mode ────────────────────────────────────────────────────────

def watch_loop(target, html_path, interval=2.0):
    """Re-analyze on file changes."""
    print(C.cyan(f"👁️  Watching {target} (Ctrl+C to stop)..."))
    last_hash = None

    while True:
        try:
            if os.path.isfile(target):
                with open(target, 'rb') as f:
                    current_hash = hashlib.md5(f.read()).hexdigest()
                if current_hash != last_hash:
                    last_hash = current_hash
                    result = analyze_file(target)
                    generate_html(result, output_path=html_path)
                    print_text_report(result)
                    print(C.dim(f"\n[{datetime.now().strftime('%H:%M:%S')}] HTML report updated → {html_path}"))
            elif os.path.isdir(target):
                results = analyze_directory(target)
                content = ''.join(
                    open(os.path.join(target, f), 'rb').read().hex()
                    for f in os.listdir(target) if f.endswith('.srv')
                )
                current_hash = hashlib.md5(content.encode()).hexdigest()
                if current_hash != last_hash:
                    last_hash = current_hash
                    summary = aggregate_results(results)
                    generate_html(results, summary, html_path)
                    print(C.dim(f"\n[{datetime.now().strftime('%H:%M:%S')}] Re-analyzed {summary['files']} files"))
            time.sleep(interval)
        except KeyboardInterrupt:
            print(C.yellow("\n⏹️  Watch stopped."))
            break
        except Exception as e:
            print(C.red(f"Watch error: {e}"))
            time.sleep(interval)


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='⚗️ sauravalchemy — Code Transmutation Engine for sauravcode',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('target', nargs='?', help='.srv file or directory')
    parser.add_argument('--transmute', action='store_true', help='Show all transmutations')
    parser.add_argument('--functional', action='store_true', help='Imperative → Functional only')
    parser.add_argument('--iterative', action='store_true', help='Recursive → Iterative only')
    parser.add_argument('--recursive', action='store_true', help='Iterative → Recursive only')
    parser.add_argument('--concise', action='store_true', help='Verbose → Concise only')
    parser.add_argument('--extract', action='store_true', help='Inline → Extracted only')
    parser.add_argument('--lazy', action='store_true', help='Eager → Lazy only')
    parser.add_argument('--profile', action='store_true', help='Paradigm profile only')
    parser.add_argument('--json', action='store_true', help='JSON output')
    parser.add_argument('--html', default='sauravalchemy_report.html', help='HTML output path')
    parser.add_argument('--no-html', action='store_true', help='Skip HTML generation')
    parser.add_argument('--watch', action='store_true', help='Watch mode')

    args = parser.parse_args()

    if not args.target:
        parser.print_help()
        print(C.dim('\n  Example: python sauravalchemy.py examples/fibonacci.srv'))
        return

    target = args.target

    if args.watch:
        watch_loop(target, args.html)
        return

    if os.path.isfile(target):
        result = analyze_file(target)

        # Filter by type if requested
        type_filter = None
        if args.functional:
            type_filter = 'imperative_to_functional'
        elif args.iterative:
            type_filter = 'recursive_to_iterative'
        elif args.recursive:
            type_filter = 'iterative_to_recursive'
        elif args.concise:
            type_filter = 'verbose_to_concise'
        elif args.extract:
            type_filter = 'inline_to_extracted'
        elif args.lazy:
            type_filter = 'eager_to_lazy'

        if type_filter:
            result['transmutations'] = [
                t for t in result['transmutations'] if t['type'] == type_filter
            ]

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print_text_report(result)
            if not args.no_html and not args.profile:
                generate_html(result, output_path=args.html)
                print(C.dim(f"\n📄 HTML report → {args.html}"))
    elif os.path.isdir(target):
        results = analyze_directory(target)
        summary = aggregate_results(results)

        if args.json:
            print(json.dumps({'summary': summary, 'files': results}, indent=2))
        else:
            print(C.bold("\n⚗️  sauravalchemy — Project Analysis"))
            print(f"   {summary['files']} files | {summary['total_transmutations']} transmutations\n")
            print(C.bold("Project Paradigm Profile:"))
            pp = summary['project_profile']
            print(f"  Functional: {pp['functional']}% | Imperative: {pp['imperative']}% | OOP: {pp['oop']}%")
            print(f"  Dominant: {C.cyan(summary['dominant_paradigm'].title())}")
            if summary.get('hotspots'):
                print(C.bold("\nTransmutation Hotspots:"))
                for h in summary['hotspots']:
                    if h['count'] > 0:
                        print(f"  {h['file']:30s} {h['count']} transmutations")
            for r in results:
                if 'error' not in r and r['transmutations']:
                    print_text_report(r)
            if not args.no_html:
                generate_html(results, summary, args.html)
                print(C.dim(f"\n📄 HTML report → {args.html}"))
    else:
        print(C.red(f"Not found: {target}"))
        sys.exit(1)


if __name__ == '__main__':
    main()
