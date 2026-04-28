#!/usr/bin/env python3
"""
sauravcomplex.py - Code complexity analyzer for sauravcode programs.

Computes cyclomatic complexity, cognitive complexity, Halstead metrics,
and maintainability index for .srv files. Helps identify overly complex
functions that may need refactoring.

Usage:
    python sauravcomplex.py program.srv              # Analyze single file
    python sauravcomplex.py src/                     # Analyze directory
    python sauravcomplex.py program.srv --json       # JSON output
    python sauravcomplex.py program.srv --threshold 10  # Flag complex funcs
    python sauravcomplex.py program.srv --sort complexity  # Sort by metric
    python sauravcomplex.py a.srv b.srv --compare    # Compare two files
    python sauravcomplex.py program.srv --details    # Show per-function breakdown
"""

import sys
import os
import math
import json as _json
import argparse
from collections import defaultdict

# Import the sauravcode tokenizer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from saurav import tokenize


def _is_code_line(line: str) -> bool:
    """Return True if *line* is non-blank and not a comment.

    Strips once to avoid the redundant double-strip() that was inlined
    in every SLOC counting expression.
    """
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith('#')


def _count_sloc(lines) -> int:
    """Count source lines of code (non-blank, non-comment) in *lines*."""
    return sum(1 for line in lines if _is_code_line(line))


# ─── Data Classes ───────────────────────────────────────────────────────────

class HalsteadMetrics:
    """Halstead software science metrics."""

    __slots__ = ('unique_operators', 'unique_operands', 'total_operators',
                 'total_operands', 'vocabulary', 'length', 'estimated_length',
                 'volume', 'difficulty', 'effort', 'time_to_implement',
                 'delivered_bugs')

    def __init__(self, unique_operators=0, unique_operands=0,
                 total_operators=0, total_operands=0):
        self.unique_operators = unique_operators
        self.unique_operands = unique_operands
        self.total_operators = total_operators
        self.total_operands = total_operands

        n1 = max(unique_operators, 1)
        n2 = max(unique_operands, 1)
        N1 = total_operators
        N2 = total_operands

        self.vocabulary = n1 + n2
        self.length = N1 + N2
        self.estimated_length = (n1 * _safe_log2(n1) + n2 * _safe_log2(n2)
                                 if n1 > 0 and n2 > 0 else 0)
        self.volume = self.length * _safe_log2(self.vocabulary) if self.vocabulary > 0 else 0
        self.difficulty = (n1 / 2.0) * (N2 / n2) if n2 > 0 else 0
        self.effort = self.volume * self.difficulty
        self.time_to_implement = self.effort / 18.0  # seconds (Stroud number)
        self.delivered_bugs = self.volume / 3000.0

    def to_dict(self):
        return {
            'unique_operators': self.unique_operators,
            'unique_operands': self.unique_operands,
            'total_operators': self.total_operators,
            'total_operands': self.total_operands,
            'vocabulary': self.vocabulary,
            'length': self.length,
            'estimated_length': round(self.estimated_length, 2),
            'volume': round(self.volume, 2),
            'difficulty': round(self.difficulty, 2),
            'effort': round(self.effort, 2),
            'time_to_implement_sec': round(self.time_to_implement, 2),
            'delivered_bugs': round(self.delivered_bugs, 4),
        }


class FunctionComplexity:
    """Complexity metrics for a single function."""

    __slots__ = ('name', 'line', 'end_line', 'params', 'loc', 'sloc',
                 'cyclomatic', 'cognitive', 'halstead', 'maintainability',
                 'max_nesting', 'grade')

    def __init__(self, name, line=0):
        self.name = name
        self.line = line
        self.end_line = 0
        self.params = 0
        self.loc = 0
        self.sloc = 0
        self.cyclomatic = 1  # Base complexity
        self.cognitive = 0
        self.halstead = HalsteadMetrics()
        self.maintainability = 100.0
        self.max_nesting = 0
        self.grade = 'A'

    def compute_maintainability(self):
        """Compute maintainability index (0-100 scale, Microsoft variant)."""
        vol = max(self.halstead.volume, 1)
        sloc = max(self.sloc, 1)
        cc = self.cyclomatic
        mi = max(0, (171 - 5.2 * math.log(vol) - 0.23 * cc - 16.2 * math.log(sloc)) * 100 / 171)
        self.maintainability = round(mi, 2)
        if mi >= 80:
            self.grade = 'A'
        elif mi >= 60:
            self.grade = 'B'
        elif mi >= 40:
            self.grade = 'C'
        elif mi >= 20:
            self.grade = 'D'
        else:
            self.grade = 'F'

    def to_dict(self):
        return {
            'name': self.name,
            'line': self.line,
            'end_line': self.end_line,
            'params': self.params,
            'loc': self.loc,
            'sloc': self.sloc,
            'cyclomatic': self.cyclomatic,
            'cognitive': self.cognitive,
            'max_nesting': self.max_nesting,
            'maintainability': self.maintainability,
            'grade': self.grade,
            'halstead': self.halstead.to_dict(),
        }


class FileComplexity:
    """Aggregate complexity metrics for a file."""

    __slots__ = ('path', 'total_loc', 'total_sloc', 'functions',
                 'avg_cyclomatic', 'max_cyclomatic', 'avg_cognitive',
                 'max_cognitive', 'avg_maintainability', 'halstead',
                 'grade', 'risk_functions')

    def __init__(self, path):
        self.path = path
        self.total_loc = 0
        self.total_sloc = 0
        self.functions = []
        self.avg_cyclomatic = 0
        self.max_cyclomatic = 0
        self.avg_cognitive = 0
        self.max_cognitive = 0
        self.avg_maintainability = 100.0
        self.halstead = HalsteadMetrics()
        self.grade = 'A'
        self.risk_functions = []

    def compute_aggregates(self):
        if self.functions:
            cycs = [f.cyclomatic for f in self.functions]
            cogs = [f.cognitive for f in self.functions]
            mis = [f.maintainability for f in self.functions]
            self.avg_cyclomatic = round(sum(cycs) / len(cycs), 2)
            self.max_cyclomatic = max(cycs)
            self.avg_cognitive = round(sum(cogs) / len(cogs), 2)
            self.max_cognitive = max(cogs)
            self.avg_maintainability = round(sum(mis) / len(mis), 2)
        mi = self.avg_maintainability
        if mi >= 80:
            self.grade = 'A'
        elif mi >= 60:
            self.grade = 'B'
        elif mi >= 40:
            self.grade = 'C'
        elif mi >= 20:
            self.grade = 'D'
        else:
            self.grade = 'F'

    def to_dict(self):
        return {
            'path': self.path,
            'total_loc': self.total_loc,
            'total_sloc': self.total_sloc,
            'function_count': len(self.functions),
            'avg_cyclomatic': self.avg_cyclomatic,
            'max_cyclomatic': self.max_cyclomatic,
            'avg_cognitive': self.avg_cognitive,
            'max_cognitive': self.max_cognitive,
            'avg_maintainability': self.avg_maintainability,
            'grade': self.grade,
            'halstead': self.halstead.to_dict(),
            'risk_functions': [f.name for f in self.risk_functions],
            'functions': [f.to_dict() for f in self.functions],
        }


# ─── Helpers ────────────────────────────────────────────────────────────────

def _safe_log2(n):
    return math.log2(n) if n > 0 else 0


# Operators in sauravcode for Halstead classification
OPERATORS = {
    '+', '-', '*', '/', '%', '=', '==', '!=', '<', '>', '<=', '>=',
    'and', 'or', 'not', '|>', '->', '(', ')', '[', ']', '{', '}',
    ',', ':', '.', '|',
}

KEYWORD_OPERATORS = {
    'if', 'else', 'else if', 'for', 'while', 'return', 'print',
    'function', 'class', 'try', 'catch', 'throw', 'import', 'match',
    'case', 'break', 'continue', 'assert', 'yield', 'lambda', 'in',
    'enum', 'next', 'append', 'len', 'pop',
}

# Decision keywords that increment cyclomatic complexity
CYCLOMATIC_KEYWORDS = {'if', 'else if', 'for', 'while', 'catch', 'and', 'or', 'case'}

# Keywords that increment cognitive complexity (nesting-sensitive)
COGNITIVE_NESTING_KEYWORDS = {'if', 'else if', 'for', 'while', 'try', 'catch', 'match'}
COGNITIVE_INCREMENT_KEYWORDS = {'and', 'or', 'break', 'continue'}


# ─── Analyzer ───────────────────────────────────────────────────────────────

class ComplexityAnalyzer:
    """Analyzes sauravcode source for complexity metrics."""

    def __init__(self, threshold=10, sort_by='cyclomatic'):
        self.threshold = threshold
        self.sort_by = sort_by

    def analyze_source(self, source, path='<source>'):
        """Analyze a sauravcode source string.

        Returns a FileComplexity with per-function and aggregate metrics.
        """
        lines = source.split('\n')
        fc = FileComplexity(path)
        fc.total_loc = len(lines)
        fc.total_sloc = _count_sloc(lines)

        # Tokenize
        tokens = list(tokenize(source))

        # Pre-group tokens by line number once — avoids O(functions × tokens)
        # re-scanning in _parse_function_header and _compute_cognitive.
        tokens_by_line = defaultdict(list)
        for tok in tokens:
            tokens_by_line[tok[2]].append(tok)

        # Extract functions and their token ranges
        functions = self._extract_functions(tokens, lines, tokens_by_line)

        # Analyze each function
        for func_info in functions:
            func_cx = self._analyze_function(func_info, lines, tokens_by_line)
            fc.functions.append(func_cx)

        # Analyze module-level code as <module>
        module_cx = self._analyze_module_level(tokens, lines, functions, tokens_by_line)
        if module_cx.sloc > 0:
            fc.functions.insert(0, module_cx)

        # Compute file-level Halstead
        fc.halstead = self._compute_halstead(tokens)

        # Find risk functions
        for f in fc.functions:
            if f.cyclomatic > self.threshold:
                fc.risk_functions.append(f)

        fc.compute_aggregates()
        return fc

    def analyze_file(self, path):
        """Analyze a .srv file."""
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            source = fh.read()
        return self.analyze_source(source, path)

    def analyze_directory(self, dirpath):
        """Analyze all .srv files in a directory recursively."""
        results = []
        for root, dirs, files in os.walk(dirpath):
            for f in sorted(files):
                if f.endswith('.srv'):
                    fp = os.path.join(root, f)
                    results.append(self.analyze_file(fp))
        return results

    def compare(self, fc1, fc2):
        """Compare two FileComplexity results."""
        return {
            'file_a': fc1.path,
            'file_b': fc2.path,
            'loc_delta': fc2.total_sloc - fc1.total_sloc,
            'function_count_delta': len(fc2.functions) - len(fc1.functions),
            'avg_cyclomatic_delta': round(fc2.avg_cyclomatic - fc1.avg_cyclomatic, 2),
            'avg_cognitive_delta': round(fc2.avg_cognitive - fc1.avg_cognitive, 2),
            'avg_maintainability_delta': round(fc2.avg_maintainability - fc1.avg_maintainability, 2),
            'grade_a': fc1.grade,
            'grade_b': fc2.grade,
            'improved': fc2.avg_maintainability > fc1.avg_maintainability,
        }

    def _extract_functions(self, tokens, lines, tokens_by_line):
        """Find function definitions and their token/line ranges."""
        functions = []
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok[0] == 'KEYWORD' and tok[1] == 'function':
                func_info = self._parse_function_header(tokens, i, lines, tokens_by_line)
                if func_info:
                    functions.append(func_info)
            i += 1
        return functions

    def _parse_function_header(self, tokens, start_idx, lines, tokens_by_line):
        """Parse function name, params, and find body range by indentation."""
        i = start_idx + 1
        # skip optional type annotation
        while i < len(tokens) and tokens[i][0] in ('KEYWORD', 'SKIP', 'NEWLINE'):
            if tokens[i][0] == 'KEYWORD' and tokens[i][1] in ('int', 'float', 'string', 'bool', 'list'):
                i += 1
                break
            elif tokens[i][0] in ('SKIP', 'NEWLINE'):
                i += 1
            else:
                break

        # function name
        if i >= len(tokens) or tokens[i][0] != 'IDENT':
            return None
        name = tokens[i][1]
        func_line = tokens[i][2]
        i += 1

        # params
        params = 0
        if i < len(tokens) and tokens[i][0] == 'LPAREN':
            depth = 1
            i += 1
            has_param = False
            while i < len(tokens) and depth > 0:
                if tokens[i][0] == 'LPAREN':
                    depth += 1
                elif tokens[i][0] == 'RPAREN':
                    depth -= 1
                elif tokens[i][0] == 'IDENT' and depth == 1:
                    has_param = True
                elif tokens[i][0] == 'COMMA' and depth == 1:
                    if has_param:
                        params += 1
                i += 1
            if has_param:
                params += 1

        # Find body: lines after function line with greater indentation
        func_line_idx = func_line - 1  # 0-based
        if func_line_idx < 0 or func_line_idx >= len(lines):
            return None
        base_indent = len(lines[func_line_idx]) - len(lines[func_line_idx].lstrip())
        end_line = func_line
        for li in range(func_line_idx + 1, len(lines)):
            line = lines[li]
            stripped = line.strip()
            if stripped == '' or stripped.startswith('#'):
                end_line = li + 1
                continue
            line_indent = len(line) - len(line.lstrip())
            if line_indent > base_indent:
                end_line = li + 1
            else:
                break

        # Collect tokens in range using pre-built line index — O(body_lines)
        # instead of O(total_tokens) per function.
        body_tokens = []
        for ln in range(func_line, end_line + 1):
            body_tokens.extend(tokens_by_line.get(ln, ()))

        return {
            'name': name,
            'line': func_line,
            'end_line': end_line,
            'params': params,
            'tokens': body_tokens,
        }

    def _analyze_module_level(self, all_tokens, lines, functions, tokens_by_line):
        """Analyze tokens that don't belong to any function."""
        func_ranges = set()
        for f in functions:
            for ln in range(f['line'], f['end_line'] + 1):
                func_ranges.add(ln)

        # Use pre-built line index to collect module tokens — avoids
        # O(total_tokens) scan with a per-token set lookup.
        module_tokens = []
        for ln in sorted(tokens_by_line):
            if ln not in func_ranges:
                module_tokens.extend(tokens_by_line[ln])
        module_lines = [i for i in range(len(lines))
                        if (i + 1) not in func_ranges]
        sloc = sum(1 for i in module_lines if _is_code_line(lines[i]))

        fc = FunctionComplexity('<module>', line=1)
        fc.end_line = len(lines)
        fc.loc = len(module_lines)
        fc.sloc = sloc
        fc.cyclomatic = self._compute_cyclomatic(module_tokens)

        # Build module-scoped line→tokens index for fast cognitive/nesting
        module_line_tokens = {ln: tokens_by_line[ln]
                              for ln in tokens_by_line
                              if ln not in func_ranges}
        fc.cognitive = self._compute_cognitive_fast(module_line_tokens, lines)
        fc.max_nesting = self._compute_max_nesting_fast(module_line_tokens, lines)
        fc.halstead = self._compute_halstead(module_tokens)
        fc.compute_maintainability()
        return fc

    def _analyze_function(self, func_info, lines, tokens_by_line=None):
        """Compute all metrics for a function.

        Args:
            func_info: Dict with 'name', 'line', 'end_line', 'params', 'tokens'.
            lines: Full source lines for indentation-based nesting analysis.
            tokens_by_line: Pre-built {line_no: [tokens]} index from the
                caller.  When provided, ``_compute_cognitive`` and
                ``_compute_max_nesting`` skip their internal O(n)
                re-grouping passes, avoiding redundant work on large files.
        """
        fc = FunctionComplexity(func_info['name'], func_info['line'])
        fc.end_line = func_info['end_line']
        fc.params = func_info['params']

        body_lines = lines[func_info['line'] - 1:func_info['end_line']]
        fc.loc = len(body_lines)
        fc.sloc = _count_sloc(body_lines)

        tokens = func_info['tokens']

        # Build a function-scoped line→tokens index once and reuse it
        # across cognitive and nesting analysis — avoids two redundant
        # O(tokens) grouping passes per function.
        if tokens_by_line is not None:
            func_line_tokens = {ln: tokens_by_line[ln]
                                for ln in range(func_info['line'],
                                                func_info['end_line'] + 1)
                                if ln in tokens_by_line}
        else:
            func_line_tokens = defaultdict(list)
            for tok in tokens:
                func_line_tokens[tok[2]].append(tok)

        fc.cyclomatic = self._compute_cyclomatic(tokens)
        fc.cognitive = self._compute_cognitive_fast(func_line_tokens, lines)
        fc.max_nesting = self._compute_max_nesting_fast(func_line_tokens, lines)
        fc.halstead = self._compute_halstead(tokens)
        fc.compute_maintainability()
        return fc

    def _compute_cyclomatic(self, tokens):
        """McCabe cyclomatic complexity: 1 + number of decision points."""
        cc = 1
        for tok in tokens:
            if tok[0] == 'KEYWORD' and tok[1] in CYCLOMATIC_KEYWORDS:
                cc += 1
        return cc

    def _compute_cognitive(self, tokens, lines):
        """Cognitive complexity (Sonar-style): nesting-aware complexity.

        Legacy entry point that builds a line→tokens index internally.
        Prefer ``_compute_cognitive_fast`` when an index is available.
        """
        line_tokens = defaultdict(list)
        for tok in tokens:
            line_tokens[tok[2]].append(tok)
        return self._compute_cognitive_fast(line_tokens, lines)

    def _compute_cognitive_fast(self, line_tokens, lines):
        """Cognitive complexity using a pre-built line→tokens index.

        Eliminates the O(n) token-grouping pass that ``_compute_cognitive``
        performs internally, saving one full scan of the token list per
        function on large files.
        """
        cog = 0
        nesting = 0

        for line_no in sorted(line_tokens):
            toks = line_tokens[line_no]
            for tok in toks:
                if tok[0] == 'KEYWORD':
                    kw = tok[1]
                    if kw in COGNITIVE_NESTING_KEYWORDS:
                        cog += 1 + nesting
                    elif kw in COGNITIVE_INCREMENT_KEYWORDS:
                        cog += 1

            # Estimate nesting from indentation
            if 0 < line_no <= len(lines):
                line = lines[line_no - 1]
                if line.strip():
                    indent = len(line) - len(line.lstrip())
                    nesting = indent // 4

        return cog

    def _compute_max_nesting(self, tokens, lines):
        """Maximum nesting depth based on indentation.

        Legacy entry point — builds a line set internally.
        Prefer ``_compute_max_nesting_fast`` when a line index exists.
        """
        line_set = set(t[2] for t in tokens)
        return self._compute_max_nesting_from_lines(line_set, lines)

    def _compute_max_nesting_fast(self, line_tokens, lines):
        """Maximum nesting depth using a pre-built line→tokens index.

        Avoids the O(n) ``set(t[2] for t in tokens)`` comprehension that
        ``_compute_max_nesting`` performs per function.
        """
        return self._compute_max_nesting_from_lines(line_tokens.keys(), lines)

    @staticmethod
    def _compute_max_nesting_from_lines(line_numbers, lines):
        """Shared implementation: find deepest indentation among given lines."""
        max_nest = 0
        for ln in line_numbers:
            if 0 < ln <= len(lines):
                line = lines[ln - 1]
                if line.strip():
                    indent = len(line) - len(line.lstrip())
                    nest = indent // 4
                    if nest > max_nest:
                        max_nest = nest
        return max_nest

    def _compute_halstead(self, tokens):
        """Compute Halstead metrics from tokens."""
        operators = set()
        operands = set()
        total_ops = 0
        total_opnds = 0

        for tok in tokens:
            typ, val = tok[0], tok[1]
            if typ in ('NEWLINE', 'SKIP', 'COMMENT'):
                continue
            if typ == 'OP' or val in OPERATORS or (typ == 'KEYWORD' and val in KEYWORD_OPERATORS):
                operators.add(val)
                total_ops += 1
            elif typ in ('NUMBER', 'STRING', 'FSTRING', 'IDENT'):
                operands.add(val)
                total_opnds += 1

        return HalsteadMetrics(len(operators), len(operands), total_ops, total_opnds)

    def get_recommendations(self, fc):
        """Generate refactoring recommendations."""
        recs = []
        for func in fc.functions:
            if func.cyclomatic > 20:
                recs.append(f"CRITICAL: {func.name} (line {func.line}) — cyclomatic complexity {func.cyclomatic}. "
                            f"Split into smaller functions.")
            elif func.cyclomatic > self.threshold:
                recs.append(f"WARNING: {func.name} (line {func.line}) — cyclomatic complexity {func.cyclomatic}. "
                            f"Consider simplifying.")
            if func.cognitive > 15:
                recs.append(f"WARNING: {func.name} (line {func.line}) — cognitive complexity {func.cognitive}. "
                            f"Hard to understand; reduce nesting or extract helpers.")
            if func.max_nesting > 4:
                recs.append(f"INFO: {func.name} (line {func.line}) — nesting depth {func.max_nesting}. "
                            f"Consider early returns or guard clauses.")
            if func.params > 5:
                recs.append(f"INFO: {func.name} (line {func.line}) — {func.params} parameters. "
                            f"Consider using a configuration map.")
            if func.maintainability < 20:
                recs.append(f"CRITICAL: {func.name} (line {func.line}) — maintainability index "
                            f"{func.maintainability} (grade {func.grade}). Needs urgent refactoring.")
            elif func.maintainability < 40:
                recs.append(f"WARNING: {func.name} (line {func.line}) — maintainability index "
                            f"{func.maintainability} (grade {func.grade}). Consider refactoring.")
        return recs


# ─── Report Generators ──────────────────────────────────────────────────────

def format_text_report(fc, details=False, recommendations=True):
    """Format a human-readable complexity report."""
    lines = []
    lines.append(f"╔══════════════════════════════════════════════════════════════╗")
    lines.append(f"║  Code Complexity Report: {os.path.basename(fc.path):<35} ║")
    lines.append(f"╚══════════════════════════════════════════════════════════════╝")
    lines.append("")
    lines.append(f"  File:               {fc.path}")
    lines.append(f"  Lines of Code:      {fc.total_loc} ({fc.total_sloc} source)")
    lines.append(f"  Functions:          {len(fc.functions)}")
    lines.append(f"  Overall Grade:      {fc.grade}")
    lines.append("")
    lines.append(f"  ── Complexity Summary ───────────────────────────────────────")
    lines.append(f"  Avg Cyclomatic:     {fc.avg_cyclomatic}")
    lines.append(f"  Max Cyclomatic:     {fc.max_cyclomatic}")
    lines.append(f"  Avg Cognitive:      {fc.avg_cognitive}")
    lines.append(f"  Max Cognitive:      {fc.max_cognitive}")
    lines.append(f"  Avg Maintainability:{fc.avg_maintainability}")
    lines.append("")

    # Halstead summary
    h = fc.halstead
    lines.append(f"  ── Halstead Metrics ─────────────────────────────────────────")
    lines.append(f"  Vocabulary:         {h.vocabulary}")
    lines.append(f"  Length:             {h.length}")
    lines.append(f"  Volume:             {h.volume:.1f}")
    lines.append(f"  Difficulty:         {h.difficulty:.1f}")
    lines.append(f"  Effort:             {h.effort:.1f}")
    lines.append(f"  Est. Time:          {h.time_to_implement:.1f}s ({h.time_to_implement/60:.1f}m)")
    lines.append(f"  Est. Bugs:          {h.delivered_bugs:.3f}")
    lines.append("")

    if fc.risk_functions:
        lines.append(f"  ── Risk Functions (complexity > {10}) ────────────────────────")
        for f in fc.risk_functions:
            lines.append(f"  ⚠ {f.name} (line {f.line}): CC={f.cyclomatic}, "
                         f"Cog={f.cognitive}, MI={f.maintainability} [{f.grade}]")
        lines.append("")

    if details or len(fc.functions) <= 20:
        lines.append(f"  ── Per-Function Breakdown ───────────────────────────────────")
        lines.append(f"  {'Function':<25} {'CC':>4} {'Cog':>4} {'MI':>6} {'Gr':>2} {'SLOC':>5} {'Nest':>4}")
        lines.append(f"  {'─'*25} {'─'*4} {'─'*4} {'─'*6} {'─'*2} {'─'*5} {'─'*4}")
        sorted_funcs = sorted(fc.functions, key=lambda f: f.cyclomatic, reverse=True)
        for f in sorted_funcs:
            name = f.name[:25]
            lines.append(f"  {name:<25} {f.cyclomatic:>4} {f.cognitive:>4} "
                         f"{f.maintainability:>6.1f} {f.grade:>2} {f.sloc:>5} {f.max_nesting:>4}")
        lines.append("")

    if recommendations:
        analyzer = ComplexityAnalyzer()
        recs = analyzer.get_recommendations(fc)
        if recs:
            lines.append(f"  ── Recommendations ─────────────────────────────────────────")
            for r in recs:
                lines.append(f"  • {r}")
            lines.append("")

    return '\n'.join(lines)


def format_comparison_report(cmp):
    """Format a comparison between two files."""
    lines = []
    lines.append(f"╔══════════════════════════════════════════════════════════════╗")
    lines.append(f"║  Complexity Comparison                                      ║")
    lines.append(f"╚══════════════════════════════════════════════════════════════╝")
    lines.append("")
    lines.append(f"  File A: {cmp['file_a']} (Grade: {cmp['grade_a']})")
    lines.append(f"  File B: {cmp['file_b']} (Grade: {cmp['grade_b']})")
    lines.append("")

    def delta_str(val):
        if val > 0:
            return f"+{val}"
        return str(val)

    lines.append(f"  SLOC Delta:              {delta_str(cmp['loc_delta'])}")
    lines.append(f"  Function Count Delta:    {delta_str(cmp['function_count_delta'])}")
    lines.append(f"  Avg Cyclomatic Delta:    {delta_str(cmp['avg_cyclomatic_delta'])}")
    lines.append(f"  Avg Cognitive Delta:     {delta_str(cmp['avg_cognitive_delta'])}")
    lines.append(f"  Avg Maintainability:     {delta_str(cmp['avg_maintainability_delta'])}")
    lines.append("")
    verdict = "✅ Improved" if cmp['improved'] else "⚠ Degraded"
    lines.append(f"  Verdict: {verdict}")
    lines.append("")
    return '\n'.join(lines)


# ─── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='sauravcomplex — Code complexity analyzer for sauravcode (.srv)')
    parser.add_argument('files', nargs='+', help='.srv files or directories to analyze')
    parser.add_argument('--json', action='store_true', help='Output JSON')
    parser.add_argument('--threshold', type=int, default=10,
                        help='Cyclomatic complexity threshold for risk flagging (default: 10)')
    parser.add_argument('--sort', choices=['cyclomatic', 'cognitive', 'maintainability', 'sloc'],
                        default='cyclomatic', help='Sort functions by metric')
    parser.add_argument('--compare', action='store_true',
                        help='Compare two files (requires exactly 2 arguments)')
    parser.add_argument('--details', action='store_true',
                        help='Show detailed per-function breakdown')
    parser.add_argument('--no-recommendations', action='store_true',
                        help='Suppress recommendations')

    args = parser.parse_args()
    analyzer = ComplexityAnalyzer(threshold=args.threshold, sort_by=args.sort)

    results = []
    for f in args.files:
        if os.path.isdir(f):
            results.extend(analyzer.analyze_directory(f))
        elif os.path.isfile(f):
            results.append(analyzer.analyze_file(f))
        else:
            print(f"Warning: {f} not found, skipping.", file=sys.stderr)

    if not results:
        print("No .srv files found.", file=sys.stderr)
        sys.exit(1)

    if args.compare:
        if len(results) != 2:
            print("--compare requires exactly 2 files.", file=sys.stderr)
            sys.exit(1)
        cmp = analyzer.compare(results[0], results[1])
        if args.json:
            print(_json.dumps(cmp, indent=2))
        else:
            print(format_comparison_report(cmp))
        return

    if args.json:
        out = [r.to_dict() for r in results]
        print(_json.dumps(out if len(out) > 1 else out[0], indent=2))
    else:
        for fc in results:
            print(format_text_report(fc, details=args.details,
                                     recommendations=not args.no_recommendations))


if __name__ == '__main__':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    main()
