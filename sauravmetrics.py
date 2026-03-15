#!/usr/bin/env python3
"""sauravmetrics — Code metrics and complexity analyzer for sauravcode.

Analyzes .srv files and reports code quality metrics including:
  - Lines of code (total, blank, comment, code)
  - Function count and sizes
  - Cyclomatic complexity (branches per function)
  - Maximum nesting depth
  - Variable count
  - Import count
  - Maintainability index (composite score)

Usage:
    python sauravmetrics.py FILE...              Analyze specific files
    python sauravmetrics.py .                    Analyze all .srv files in current directory
    python sauravmetrics.py . --recursive        Include subdirectories
    python sauravmetrics.py FILE --json          Output as JSON
    python sauravmetrics.py FILE --csv           Output as CSV
    python sauravmetrics.py . --sort complexity  Sort by metric (complexity|loc|functions|depth)
    python sauravmetrics.py . --threshold 10     Flag functions with complexity >= threshold
    python sauravmetrics.py . --summary          Show only project-level summary
    python sauravmetrics.py FILE --details       Show per-function breakdown

Options:
    --recursive, -r    Recurse into subdirectories
    --json             Output results as JSON
    --csv              Output results as CSV
    --sort METRIC      Sort files by metric (loc, complexity, functions, depth, score)
    --threshold N      Complexity threshold for warnings (default: 10)
    --summary          Show only aggregate summary, skip per-file details
    --details          Show per-function metrics breakdown
    --no-color         Disable colored output
"""

import sys
import os
import re
import json
import math
import argparse
from collections import defaultdict

# ── ANSI Colors ──────────────────────────────────────────────────────

USE_COLOR = True

def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else str(text)


# Ensure UTF-8 stdout on Windows
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

def red(t):    return _c("31", t)
def green(t):  return _c("32", t)
def yellow(t): return _c("33", t)
def cyan(t):   return _c("36", t)
def bold(t):   return _c("1", t)
def dim(t):    return _c("2", t)

# ── Language Patterns ────────────────────────────────────────────────

# Keywords that introduce branches (increase cyclomatic complexity)
BRANCH_KEYWORDS = {'if', 'elif', 'while', 'for', 'foreach', 'catch', 'and', 'or'}

# Keywords that introduce blocks (increase nesting)
BLOCK_KEYWORDS = {'if', 'elif', 'else', 'while', 'for', 'foreach', 'function',
                  'fn', 'try', 'catch', 'match', 'enum', 'class'}

# Built-in function pattern
FUNCTION_DEF = re.compile(r'^(\s*)(function|fn)\s+(\w+)')

# Import pattern
IMPORT_PATTERN = re.compile(r'^\s*import\s+')

# Variable assignment pattern (simple)
ASSIGN_PATTERN = re.compile(r'^\s*(\w+)\s*=\s*')

# ── Metrics Computation ─────────────────────────────────────────────

class FunctionMetrics:
    """Metrics for a single function."""
    __slots__ = ('name', 'line', 'loc', 'complexity', 'max_depth', 'params', 'variables')

    def __init__(self, name, line):
        self.name = name
        self.line = line
        self.loc = 0
        self.complexity = 1  # Base complexity
        self.max_depth = 0
        self.params = 0
        self.variables = set()


class FileMetrics:
    """Metrics for a single .srv file."""

    def __init__(self, filepath):
        self.filepath = filepath
        self.total_lines = 0
        self.blank_lines = 0
        self.comment_lines = 0
        self.code_lines = 0
        self.functions = []
        self.global_variables = set()
        self.imports = 0
        self.max_depth = 0
        self.total_complexity = 0

    @property
    def avg_complexity(self):
        if not self.functions:
            return 0
        return sum(f.complexity for f in self.functions) / len(self.functions)

    @property
    def avg_function_loc(self):
        if not self.functions:
            return 0
        return sum(f.loc for f in self.functions) / len(self.functions)

    @property
    def maintainability_index(self):
        """Compute a maintainability index (0-100 scale).

        Based on a simplified version of the Visual Studio maintainability index:
        MI = max(0, 171 - 5.2*ln(HV) - 0.23*CC - 16.2*ln(LOC)) * 100/171

        We approximate Halstead Volume with code_lines * log2(unique operators+operands).
        """
        loc = max(self.code_lines, 1)
        cc = max(self.total_complexity, 1)
        # Approximate Halstead volume
        hv = loc * math.log2(max(len(self.global_variables) + len(self.functions) + 10, 2))
        mi = max(0, 171 - 5.2 * math.log(hv) - 0.23 * cc - 16.2 * math.log(loc))
        return round(mi * 100 / 171, 1)


def _get_indent(line):
    """Return the indentation level (number of leading spaces / 4)."""
    stripped = line.rstrip()
    if not stripped:
        return 0
    spaces = len(stripped) - len(stripped.lstrip())
    return spaces // 4


def analyze_file(filepath):
    """Analyze a single .srv file and return FileMetrics."""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
    except OSError as e:
        print(f"Error reading {filepath}: {e}", file=sys.stderr)
        return None

    metrics = FileMetrics(filepath)
    metrics.total_lines = len(lines)

    current_function = None
    base_indent = 0

    for i, raw_line in enumerate(lines):
        line = raw_line.rstrip()

        # Line classification
        stripped = line.lstrip()
        if not stripped:
            metrics.blank_lines += 1
            continue
        if stripped.startswith('#'):
            metrics.comment_lines += 1
            continue

        metrics.code_lines += 1

        # Track nesting depth
        indent = _get_indent(raw_line)
        if indent > metrics.max_depth:
            metrics.max_depth = indent

        # Function detection
        m = FUNCTION_DEF.match(line)
        if m:
            name = m.group(3)
            fn = FunctionMetrics(name, i + 1)
            # Count params (words after function name on same line)
            after_name = line[m.end():].strip()
            if after_name:
                fn.params = len(after_name.split())
            base_indent = indent
            current_function = fn
            metrics.functions.append(fn)
            continue

        # If inside a function
        if current_function is not None:
            if indent > base_indent:
                current_function.loc += 1
                fn_depth = indent - base_indent - 1
                if fn_depth > current_function.max_depth:
                    current_function.max_depth = fn_depth

                # Check for branch keywords
                first_word = stripped.split()[0] if stripped else ''
                if first_word in BRANCH_KEYWORDS:
                    current_function.complexity += 1

                # Check for variables in function
                vm = ASSIGN_PATTERN.match(stripped)
                if vm:
                    current_function.variables.add(vm.group(1))
            else:
                # Exited function
                current_function = None

        # Global scope checks
        if current_function is None:
            # Check for branch keywords at global scope
            first_word = stripped.split()[0] if stripped else ''

            # Imports
            if IMPORT_PATTERN.match(line):
                metrics.imports += 1

            # Global variables
            vm = ASSIGN_PATTERN.match(stripped)
            if vm:
                metrics.global_variables.add(vm.group(1))

    # Compute total complexity
    if metrics.functions:
        metrics.total_complexity = sum(f.complexity for f in metrics.functions)
    else:
        # For files without functions, count branches at global scope
        metrics.total_complexity = 1
        for raw_line in lines:
            stripped = raw_line.strip()
            if stripped and not stripped.startswith('#'):
                first_word = stripped.split()[0]
                if first_word in BRANCH_KEYWORDS:
                    metrics.total_complexity += 1

    return metrics


# ── Output Formatting ────────────────────────────────────────────────

def _score_color(score):
    """Color a maintainability score."""
    if score >= 70:
        return green(f"{score}")
    elif score >= 40:
        return yellow(f"{score}")
    else:
        return red(f"{score}")


def _complexity_color(cc, threshold):
    """Color a complexity value."""
    if cc <= threshold // 2:
        return green(str(cc))
    elif cc <= threshold:
        return yellow(str(cc))
    else:
        return red(str(cc))


def _grade(score):
    """Letter grade from maintainability score."""
    if score >= 80: return green("A")
    if score >= 60: return green("B")
    if score >= 40: return yellow("C")
    if score >= 20: return red("D")
    return red("F")


def print_file_metrics(fm, threshold=10, show_details=False):
    """Print metrics for one file."""
    name = os.path.basename(fm.filepath)
    print(f"\n{bold(cyan(f'── {name} '))}{dim('─' * max(1, 50 - len(name)))}")

    # Line counts
    print(f"  Lines:       {fm.total_lines:>5}  "
          f"({fm.code_lines} code, {fm.comment_lines} comment, {fm.blank_lines} blank)")

    # Comment ratio
    if fm.code_lines > 0:
        ratio = fm.comment_lines / fm.code_lines * 100
        print(f"  Comment %:   {ratio:>5.1f}%")

    # Functions
    print(f"  Functions:   {len(fm.functions):>5}")
    if fm.functions:
        print(f"  Avg fn LOC:  {fm.avg_function_loc:>5.1f}")

    # Complexity
    cc_str = _complexity_color(fm.total_complexity, threshold)
    print(f"  Complexity:  {cc_str:>5}  (avg {fm.avg_complexity:.1f}/fn)")

    # Nesting
    print(f"  Max depth:   {fm.max_depth:>5}")

    # Imports and variables
    print(f"  Imports:     {fm.imports:>5}")
    print(f"  Variables:   {len(fm.global_variables):>5}  (global)")

    # Maintainability
    score = fm.maintainability_index
    print(f"  Maint. idx:  {_score_color(score):>5}  [{_grade(score)}]")

    # Warnings
    for fn in fm.functions:
        if fn.complexity >= threshold:
            print(f"  {yellow('⚠')} {fn.name}() at line {fn.line}: "
                  f"complexity {red(str(fn.complexity))} >= {threshold}")

    # Per-function details
    if show_details and fm.functions:
        print(f"\n  {bold('Function Details:')}")
        print(f"  {'Name':<25} {'LOC':>5} {'CC':>5} {'Depth':>6} {'Params':>7} {'Vars':>5}")
        print(f"  {'─'*25} {'─'*5} {'─'*5} {'─'*6} {'─'*7} {'─'*5}")
        for fn in sorted(fm.functions, key=lambda f: -f.complexity):
            cc_s = _complexity_color(fn.complexity, threshold)
            print(f"  {fn.name:<25} {fn.loc:>5} {cc_s:>5} {fn.max_depth:>6} "
                  f"{fn.params:>7} {len(fn.variables):>5}")


def print_summary(all_metrics, threshold=10):
    """Print aggregate project summary."""
    total_loc = sum(m.code_lines for m in all_metrics)
    total_lines = sum(m.total_lines for m in all_metrics)
    total_comments = sum(m.comment_lines for m in all_metrics)
    total_blank = sum(m.blank_lines for m in all_metrics)
    total_fns = sum(len(m.functions) for m in all_metrics)
    total_cc = sum(m.total_complexity for m in all_metrics)
    max_depth = max((m.max_depth for m in all_metrics), default=0)
    avg_score = sum(m.maintainability_index for m in all_metrics) / len(all_metrics) if all_metrics else 0

    # Count warnings
    warnings = sum(1 for m in all_metrics for f in m.functions if f.complexity >= threshold)

    print(f"\n{bold(cyan('═══ Project Summary ═══'))}")
    print(f"  Files:          {len(all_metrics):>6}")
    print(f"  Total lines:    {total_lines:>6}  ({total_loc} code, {total_comments} comment, {total_blank} blank)")
    if total_loc > 0:
        print(f"  Comment ratio:  {total_comments/total_loc*100:>5.1f}%")
    print(f"  Functions:      {total_fns:>6}")
    print(f"  Avg complexity: {(total_cc/max(total_fns,1)):>6.1f}  per function")
    print(f"  Max depth:      {max_depth:>6}")
    print(f"  Maint. index:   {_score_color(round(avg_score,1)):>6}  (avg) [{_grade(avg_score)}]")
    if warnings:
        print(f"  {yellow('⚠')} Warnings:     {red(str(warnings)):>6}  (complexity >= {threshold})")
    else:
        print(f"  {green('✓')} No complexity warnings")
    print()


def output_json(all_metrics):
    """Output all metrics as JSON."""
    result = []
    for m in all_metrics:
        entry = {
            'file': m.filepath,
            'lines': {'total': m.total_lines, 'code': m.code_lines,
                       'comment': m.comment_lines, 'blank': m.blank_lines},
            'functions': len(m.functions),
            'complexity': m.total_complexity,
            'avg_complexity': round(m.avg_complexity, 2),
            'max_depth': m.max_depth,
            'imports': m.imports,
            'global_variables': len(m.global_variables),
            'maintainability_index': m.maintainability_index,
            'function_details': [
                {'name': f.name, 'line': f.line, 'loc': f.loc,
                 'complexity': f.complexity, 'max_depth': f.max_depth,
                 'params': f.params, 'variables': len(f.variables)}
                for f in m.functions
            ]
        }
        result.append(entry)
    print(json.dumps(result, indent=2))


def output_csv(all_metrics):
    """Output metrics as CSV."""
    print("file,total_lines,code_lines,comment_lines,blank_lines,functions,"
          "complexity,avg_complexity,max_depth,imports,variables,maintainability")
    for m in all_metrics:
        print(f"{m.filepath},{m.total_lines},{m.code_lines},{m.comment_lines},"
              f"{m.blank_lines},{len(m.functions)},{m.total_complexity},"
              f"{m.avg_complexity:.2f},{m.max_depth},{m.imports},"
              f"{len(m.global_variables)},{m.maintainability_index}")


# ── File Discovery ───────────────────────────────────────────────────

def find_srv_files(paths, recursive=False):
    """Find .srv files from given paths."""
    files = []
    for p in paths:
        if os.path.isfile(p):
            if p.endswith('.srv'):
                files.append(p)
            else:
                print(f"Skipping non-.srv file: {p}", file=sys.stderr)
        elif os.path.isdir(p):
            if recursive:
                for root, dirs, fnames in os.walk(p):
                    # Skip hidden dirs and common non-source dirs
                    dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__'
                               and d != '__snapshots__' and d != 'node_modules']
                    for fn in sorted(fnames):
                        if fn.endswith('.srv'):
                            files.append(os.path.join(root, fn))
            else:
                for fn in sorted(os.listdir(p)):
                    if fn.endswith('.srv'):
                        files.append(os.path.join(p, fn))
        else:
            print(f"Path not found: {p}", file=sys.stderr)
    return files


# ── Main ─────────────────────────────────────────────────────────────

SORT_KEYS = {
    'loc': lambda m: m.code_lines,
    'complexity': lambda m: m.total_complexity,
    'functions': lambda m: len(m.functions),
    'depth': lambda m: m.max_depth,
    'score': lambda m: m.maintainability_index,
}


def main():
    global USE_COLOR

    parser = argparse.ArgumentParser(
        description='Code metrics and complexity analyzer for sauravcode (.srv files)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python sauravmetrics.py hello.srv              # Analyze one file
  python sauravmetrics.py . --recursive           # Analyze all .srv files recursively
  python sauravmetrics.py . --json               # JSON output for CI integration
  python sauravmetrics.py . --sort complexity    # Sort by complexity (highest first)
  python sauravmetrics.py . --threshold 5        # Stricter complexity warnings
  python sauravmetrics.py test.srv --details     # Show per-function breakdown
        """)
    parser.add_argument('paths', nargs='+', help='.srv files or directories to analyze')
    parser.add_argument('-r', '--recursive', action='store_true',
                        help='Recurse into subdirectories')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--csv', action='store_true', help='Output as CSV')
    parser.add_argument('--sort', choices=list(SORT_KEYS.keys()),
                        help='Sort files by metric (descending)')
    parser.add_argument('--threshold', type=int, default=10,
                        help='Complexity threshold for warnings (default: 10)')
    parser.add_argument('--summary', action='store_true',
                        help='Show only project-level summary')
    parser.add_argument('--details', action='store_true',
                        help='Show per-function metrics breakdown')
    parser.add_argument('--no-color', action='store_true',
                        help='Disable colored output')

    args = parser.parse_args()

    if args.no_color or not sys.stdout.isatty():
        USE_COLOR = False

    # Find files
    files = find_srv_files(args.paths, recursive=args.recursive)
    if not files:
        print("No .srv files found.", file=sys.stderr)
        sys.exit(1)

    # Analyze
    all_metrics = []
    for fp in files:
        m = analyze_file(fp)
        if m is not None:
            all_metrics.append(m)

    if not all_metrics:
        print("No files could be analyzed.", file=sys.stderr)
        sys.exit(1)

    # Sort
    if args.sort:
        all_metrics.sort(key=SORT_KEYS[args.sort], reverse=True)

    # Output
    if args.json:
        output_json(all_metrics)
    elif args.csv:
        output_csv(all_metrics)
    else:
        print(bold(cyan("sauravmetrics")) + dim(" — code complexity analyzer for sauravcode"))
        if not args.summary:
            for m in all_metrics:
                print_file_metrics(m, threshold=args.threshold, show_details=args.details)
        print_summary(all_metrics, threshold=args.threshold)


if __name__ == '__main__':
    main()
