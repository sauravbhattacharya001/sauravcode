#!/usr/bin/env python3
"""
sauravadapt.py - Autonomous Adaptive Optimizer for sauravcode programs.

Analyzes .srv source code and applies optimization transformations including
dead code elimination, constant folding, redundant assignment detection,
loop invariant identification, complexity analysis, and duplicate code
detection. Generates optimized output with before/after analysis.

Usage:
    python sauravadapt.py program.srv                # Analyze and show report
    python sauravadapt.py program.srv --apply         # Write optimized version
    python sauravadapt.py program.srv --html          # Generate HTML report
    python sauravadapt.py program.srv --diff          # Show before/after diff
    python sauravadapt.py program.srv --aggressive    # Enable all passes
    python sauravadapt.py program.srv --auto          # Auto-apply safe optimizations
    python sauravadapt.py program.srv --watch         # Watch mode
"""

import re
import os
import sys
import math
import time
import argparse
import hashlib
import difflib
from collections import defaultdict, Counter

# ---------------------------------------------------------------------------
# Optimization finding
# ---------------------------------------------------------------------------

class OptFinding:
    """A single optimization opportunity."""
    __slots__ = ('pass_name', 'line', 'message', 'impact', 'category',
                 'original', 'optimized', 'auto_fixable')

    def __init__(self, pass_name, line, message, impact='low',
                 category='style', original=None, optimized=None,
                 auto_fixable=False):
        self.pass_name = pass_name
        self.line = line
        self.message = message
        self.impact = impact          # low / medium / high
        self.category = category      # dead-code / constant / redundant / complexity / duplicate / style
        self.original = original
        self.optimized = optimized
        self.auto_fixable = auto_fixable

    def __repr__(self):
        return f"[{self.impact.upper()}] L{self.line}: {self.message}"


# ---------------------------------------------------------------------------
# Optimization passes
# ---------------------------------------------------------------------------

class DeadCodePass:
    """Detect unreachable code after return/break/continue statements."""
    NAME = "dead-code-elimination"

    def run(self, lines):
        findings = []
        in_block = False
        brace_depth = 0
        dead_start = None

        for i, raw in enumerate(lines, 1):
            stripped = raw.strip()
            brace_depth += stripped.count('{') - stripped.count('}')

            if in_block:
                if brace_depth < dead_depth:
                    in_block = False
                    dead_start = None
                else:
                    if stripped and not stripped.startswith('//') and stripped != '}':
                        findings.append(OptFinding(
                            self.NAME, i,
                            f"Unreachable code after {dead_keyword} statement",
                            impact='high', category='dead-code',
                            original=stripped, optimized='// (removed)',
                            auto_fixable=True))
                continue

            if re.match(r'^(return|break|continue)\b', stripped):
                dead_keyword = stripped.split()[0]
                dead_depth = brace_depth
                in_block = True
                dead_start = i

        return findings


class ConstantFoldPass:
    """Detect constant expressions that can be evaluated at compile time."""
    NAME = "constant-folding"

    _CONST_EXPR = re.compile(
        r'\blet\s+(\w+)\s*=\s*(-?\d+(?:\.\d+)?)\s*([+\-*/])\s*(-?\d+(?:\.\d+)?)\s*$')
    _CONST_CHAIN = re.compile(
        r'\blet\s+(\w+)\s*=\s*(-?\d+(?:\.\d+)?(?:\s*[+\-*/]\s*-?\d+(?:\.\d+)?)+)\s*$')

    def _safe_eval(self, expr):
        """Evaluate a simple arithmetic expression safely."""
        try:
            # Only allow digits, operators, dots, spaces, parens
            if re.match(r'^[\d\s+\-*/.()]+$', expr):
                result = eval(expr)  # safe: validated input
                if isinstance(result, float) and result == int(result):
                    return str(int(result))
                return str(result)
        except Exception:
            pass
        return None

    def run(self, lines):
        findings = []
        for i, raw in enumerate(lines, 1):
            stripped = raw.strip()
            m = self._CONST_CHAIN.match(stripped)
            if m:
                var_name = m.group(1)
                expr = m.group(2)
                result = self._safe_eval(expr)
                if result is not None:
                    optimized = stripped.replace(expr, result)
                    findings.append(OptFinding(
                        self.NAME, i,
                        f"Constant expression '{expr}' => {result}",
                        impact='medium', category='constant',
                        original=stripped, optimized=optimized,
                        auto_fixable=True))
        return findings


class RedundantAssignmentPass:
    """Detect variables that are assigned but never used."""
    NAME = "redundant-assignment"

    _ASSIGN = re.compile(r'^\s*let\s+(\w+)\s*=')

    def run(self, lines):
        findings = []
        assignments = {}  # var_name -> line_number
        full_text = '\n'.join(lines)

        for i, raw in enumerate(lines, 1):
            m = self._ASSIGN.match(raw)
            if m:
                var_name = m.group(1)
                assignments[var_name] = (i, raw.strip())

        # Single-pass word frequency count — O(N) instead of O(V×N)
        word_counts = Counter(re.findall(r'\b\w+\b', full_text))

        for var_name, (line_no, orig) in assignments.items():
            # O(1) lookup instead of per-variable regex scan
            if word_counts.get(var_name, 0) <= 1:
                findings.append(OptFinding(
                    self.NAME, line_no,
                    f"Variable '{var_name}' is assigned but never used",
                    impact='medium', category='redundant',
                    original=orig,
                    optimized=f'// removed unused: {orig}',
                    auto_fixable=True))

        return findings


class LoopInvariantPass:
    """Detect computations inside loops that don't depend on loop variables."""
    NAME = "loop-invariant-detection"

    _LOOP_START = re.compile(r'^\s*(for|while|loop)\b')
    _ASSIGN_IN = re.compile(r'^\s*let\s+(\w+)\s*=\s*(.+)')

    def run(self, lines):
        findings = []
        i = 0
        while i < len(lines):
            stripped = lines[i].strip()
            m = self._LOOP_START.match(stripped)
            if m:
                loop_line = i + 1
                # Extract loop variable if for-loop
                loop_var_m = re.search(r'for\s+(\w+)\s+in', stripped)
                loop_var = loop_var_m.group(1) if loop_var_m else None

                # Scan loop body
                brace_depth = stripped.count('{') - stripped.count('}')
                j = i + 1
                while j < len(lines) and brace_depth > 0:
                    inner = lines[j].strip()
                    brace_depth += inner.count('{') - inner.count('}')
                    am = self._ASSIGN_IN.match(inner)
                    if am:
                        var = am.group(1)
                        expr = am.group(2)
                        # If expression doesn't reference loop var or loop counter
                        if loop_var and loop_var not in expr and var != loop_var:
                            # Check if expr uses only constants/globals
                            if re.match(r'^[\d\s+\-*/.\"\']+$', expr.strip()):
                                findings.append(OptFinding(
                                    self.NAME, j + 1,
                                    f"Loop-invariant assignment '{var} = {expr.strip()}' can be hoisted",
                                    impact='medium', category='performance'))
                    j += 1
            i += 1
        return findings


class ComplexityPass:
    """Flag deeply nested conditionals and loops."""
    NAME = "complexity-reduction"

    MAX_DEPTH = 3

    def run(self, lines):
        findings = []
        nesting = 0
        nesting_stack = []

        for i, raw in enumerate(lines, 1):
            stripped = raw.strip()
            # Track nesting via braces
            opens = stripped.count('{')
            closes = stripped.count('}')

            if re.match(r'^(if|for|while|loop|match)\b', stripped):
                nesting += 1
                nesting_stack.append(i)
                if nesting > self.MAX_DEPTH:
                    findings.append(OptFinding(
                        self.NAME, i,
                        f"Nesting depth {nesting} exceeds threshold ({self.MAX_DEPTH}). "
                        f"Consider extracting into helper function.",
                        impact='medium', category='complexity'))

            nesting += opens - (1 if opens > 0 and re.match(r'^(if|for|while|loop|match)\b', stripped) else 0)
            nesting -= closes
            if nesting < 0:
                nesting = 0

        return findings


class StringConcatPass:
    """Detect string concatenation that could use f-strings."""
    NAME = "string-concat-optimization"

    _CONCAT = re.compile(r'"[^"]*"\s*\+\s*\w+')

    def run(self, lines):
        findings = []
        for i, raw in enumerate(lines, 1):
            stripped = raw.strip()
            # Count string + var patterns
            concats = self._CONCAT.findall(stripped)
            if len(concats) >= 2:
                findings.append(OptFinding(
                    self.NAME, i,
                    "Multiple string concatenations could use f-string interpolation",
                    impact='low', category='style',
                    original=stripped))
        return findings


class DuplicateCodePass:
    """Find similar function bodies that could be refactored."""
    NAME = "duplicate-code-detection"

    _FN_DEF = re.compile(r'^\s*fn\s+(\w+)\s*\(([^)]*)\)\s*\{?\s*$')

    def _extract_functions(self, lines):
        """Extract function name -> normalized body."""
        functions = {}
        i = 0
        while i < len(lines):
            m = self._FN_DEF.match(lines[i])
            if m:
                fn_name = m.group(1)
                fn_line = i + 1
                params = [p.strip() for p in m.group(2).split(',') if p.strip()]
                body_lines = []
                brace_depth = lines[i].count('{') - lines[i].count('}')
                j = i + 1
                while j < len(lines) and brace_depth > 0:
                    brace_depth += lines[j].count('{') - lines[j].count('}')
                    body_lines.append(lines[j].strip())
                    j += 1
                # Normalize: replace param names with positional placeholders
                body_text = '\n'.join(body_lines)
                if params:
                    # Single combined regex for all params — one pass instead of N passes
                    param_map = {p: f'__P{idx}__' for idx, p in enumerate(params)}
                    combined = re.compile(r'\b(' + '|'.join(re.escape(p) for p in params) + r')\b')
                    body_text = combined.sub(lambda m: param_map[m.group(1)], body_text)
                functions[fn_name] = (fn_line, body_text, len(body_lines))
                i = j
            else:
                i += 1
        return functions

    def run(self, lines):
        findings = []
        functions = self._extract_functions(lines)
        names = list(functions.keys())

        for a in range(len(names)):
            for b in range(a + 1, len(names)):
                na, nb = names[a], names[b]
                _, body_a, size_a = functions[na]
                line_b, body_b, size_b = functions[nb]
                if size_a < 2 or size_b < 2:
                    continue
                # Compare normalized bodies
                ratio = difflib.SequenceMatcher(None, body_a, body_b).ratio()
                if ratio > 0.75:
                    findings.append(OptFinding(
                        self.NAME, line_b,
                        f"Functions '{na}' and '{nb}' have {ratio:.0%} similar bodies - "
                        f"consider refactoring into a shared helper",
                        impact='medium' if ratio > 0.9 else 'low',
                        category='duplicate'))

        return findings


# ---------------------------------------------------------------------------
# Main optimizer
# ---------------------------------------------------------------------------

ALL_PASSES = [
    DeadCodePass,
    ConstantFoldPass,
    RedundantAssignmentPass,
    LoopInvariantPass,
    ComplexityPass,
    StringConcatPass,
    DuplicateCodePass,
]

class AdaptiveOptimizer:
    """Orchestrates optimization passes on sauravcode source."""

    def __init__(self, source, filename='<input>'):
        self.source = source
        self.filename = filename
        self.lines = source.splitlines()
        self.findings = []

    def analyze(self, aggressive=False):
        """Run all optimization passes."""
        self.findings = []
        for PassClass in ALL_PASSES:
            p = PassClass()
            try:
                self.findings.extend(p.run(self.lines))
            except Exception as exc:
                self.findings.append(OptFinding(
                    PassClass.NAME, 0,
                    f"Pass error: {exc}", impact='low', category='internal'))
        # Sort by line number
        self.findings.sort(key=lambda f: f.line)
        return self.findings

    def health_score(self):
        """Compute optimization health score (0-100). Higher = more optimized."""
        if not self.lines:
            return 100
        penalty = 0
        for f in self.findings:
            if f.impact == 'high':
                penalty += 15
            elif f.impact == 'medium':
                penalty += 8
            else:
                penalty += 3
        # Scale by code size
        size_factor = max(1, len(self.lines) / 50)
        score = max(0, 100 - penalty / size_factor)
        return round(score, 1)

    def apply_safe_optimizations(self):
        """Apply auto-fixable optimizations and return new source."""
        new_lines = list(self.lines)
        # Collect auto-fixable findings, process from bottom to top
        fixable = [f for f in self.findings if f.auto_fixable and f.original]
        fixable.sort(key=lambda f: f.line, reverse=True)

        applied = []
        for f in fixable:
            idx = f.line - 1
            if 0 <= idx < len(new_lines):
                old = new_lines[idx].strip()
                if old == f.original and f.optimized:
                    indent = len(new_lines[idx]) - len(new_lines[idx].lstrip())
                    if f.optimized.startswith('// (removed)') or f.optimized.startswith('// removed'):
                        new_lines[idx] = ' ' * indent + f.optimized
                    else:
                        new_lines[idx] = ' ' * indent + f.optimized
                    applied.append(f)

        return '\n'.join(new_lines), applied

    def generate_diff(self):
        """Generate unified diff between original and optimized source."""
        optimized, _ = self.apply_safe_optimizations()
        orig_lines = self.source.splitlines(keepends=True)
        opt_lines = optimized.splitlines(keepends=True)
        diff = difflib.unified_diff(
            orig_lines, opt_lines,
            fromfile=f'{self.filename} (original)',
            tofile=f'{self.filename} (optimized)')
        return ''.join(diff)

    # -- Terminal report ---------------------------------------------------

    def print_report(self):
        """Print a human-readable optimization report."""
        score = self.health_score()
        total = len(self.findings)
        high = sum(1 for f in self.findings if f.impact == 'high')
        med = sum(1 for f in self.findings if f.impact == 'medium')
        low = sum(1 for f in self.findings if f.impact == 'low')

        print(f"\n{'='*60}")
        print(f"  sauravadapt - Adaptive Optimizer Report")
        print(f"  File: {self.filename}")
        print(f"  Lines: {len(self.lines)}  |  Findings: {total}")
        print(f"{'='*60}\n")

        # Health score bar
        bar_len = 30
        filled = round(score / 100 * bar_len)
        bar = '#' * filled + '.' * (bar_len - filled)
        if score >= 80:
            grade = 'A'
        elif score >= 60:
            grade = 'B'
        elif score >= 40:
            grade = 'C'
        elif score >= 20:
            grade = 'D'
        else:
            grade = 'F'
        print(f"  Optimization Health: [{bar}] {score}/100 ({grade})")
        print(f"  High: {high}  Medium: {med}  Low: {low}\n")

        if not self.findings:
            print("  [OK] No optimization opportunities found -- code looks great!\n")
            return

        # Group by pass
        by_pass = defaultdict(list)
        for f in self.findings:
            by_pass[f.pass_name].append(f)

        for pass_name, items in by_pass.items():
            print(f"  -- {pass_name} ({len(items)} finding{'s' if len(items)!=1 else ''}) --")
            for f in items:
                icon = {'high': '[!]', 'medium': '[~]', 'low': '[.]'}.get(f.impact, '[ ]')
                fix = ' [auto-fixable]' if f.auto_fixable else ''
                print(f"    {icon} L{f.line}: {f.message}{fix}")
                if f.original and f.optimized and f.original != f.optimized:
                    print(f"       - {f.original}")
                    print(f"       + {f.optimized}")
            print()

        auto_count = sum(1 for f in self.findings if f.auto_fixable)
        if auto_count:
            print(f"  [*] {auto_count} finding(s) can be auto-fixed with --auto\n")

    # -- HTML report -------------------------------------------------------

    def generate_html(self):
        """Generate a self-contained interactive HTML report."""
        score = self.health_score()
        total = len(self.findings)
        high = sum(1 for f in self.findings if f.impact == 'high')
        med = sum(1 for f in self.findings if f.impact == 'medium')
        low = sum(1 for f in self.findings if f.impact == 'low')

        by_pass = defaultdict(list)
        for f in self.findings:
            by_pass[f.pass_name].append(f)

        grade = 'A' if score >= 80 else 'B' if score >= 60 else 'C' if score >= 40 else 'D' if score >= 20 else 'F'
        grade_color = {'A': '#22c55e', 'B': '#84cc16', 'C': '#eab308',
                       'D': '#f97316', 'F': '#ef4444'}.get(grade, '#888')

        findings_html = []
        for pass_name, items in by_pass.items():
            rows = ''
            for f in items:
                badge = {'high': '<span class="badge high">HIGH</span>',
                         'medium': '<span class="badge med">MED</span>',
                         'low': '<span class="badge low">LOW</span>'}.get(f.impact, '')
                fix_tag = ' <span class="autotag">auto-fix</span>' if f.auto_fixable else ''
                diff_html = ''
                if f.original and f.optimized and f.original != f.optimized:
                    diff_html = (f'<div class="diff"><div class="del">- {_html_esc(f.original)}</div>'
                                 f'<div class="add">+ {_html_esc(f.optimized)}</div></div>')
                rows += f'<tr><td>L{f.line}</td><td>{badge}{fix_tag}</td><td>{_html_esc(f.message)}{diff_html}</td></tr>\n'
            findings_html.append(f'''
            <div class="pass-section">
                <h3>{_html_esc(pass_name)} <span class="count">({len(items)})</span></h3>
                <table><thead><tr><th>Line</th><th>Impact</th><th>Details</th></tr></thead>
                <tbody>{rows}</tbody></table>
            </div>''')

        source_lines = ''
        finding_lines = {f.line for f in self.findings}
        for i, line in enumerate(self.lines, 1):
            cls = ' class="flagged"' if i in finding_lines else ''
            source_lines += f'<tr{cls}><td class="ln">{i}</td><td class="code"><pre>{_html_esc(line)}</pre></td></tr>\n'

        return f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>sauravadapt Report — {_html_esc(self.filename)}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#0d1117;color:#c9d1d9;padding:2rem}}
h1{{color:#58a6ff;margin-bottom:.5rem}} h2{{color:#8b949e;margin:1.5rem 0 .5rem}}
h3{{color:#58a6ff;margin-bottom:.5rem}}
.header{{display:flex;align-items:center;gap:2rem;margin-bottom:2rem}}
.score-ring{{width:120px;height:120px;border-radius:50%;border:8px solid {grade_color};
  display:flex;align-items:center;justify-content:center;flex-direction:column}}
.score-ring .val{{font-size:2rem;font-weight:700;color:{grade_color}}}
.score-ring .grade{{font-size:.9rem;color:#8b949e}}
.stats{{display:flex;gap:1rem}} .stat{{background:#161b22;padding:.5rem 1rem;border-radius:8px}}
.stat .n{{font-size:1.4rem;font-weight:700}} .stat .l{{font-size:.75rem;color:#8b949e}}
.badge{{padding:2px 6px;border-radius:4px;font-size:.7rem;font-weight:700;margin-right:4px}}
.badge.high{{background:#f8514940;color:#f85149}} .badge.med{{background:#d2992240;color:#d29922}}
.badge.low{{background:#388bfd40;color:#388bfd}}
.autotag{{background:#23893840;color:#238938;padding:2px 6px;border-radius:4px;font-size:.7rem}}
.pass-section{{background:#161b22;border-radius:8px;padding:1rem;margin-bottom:1rem}}
table{{width:100%;border-collapse:collapse}} th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid #21262d}}
th{{color:#8b949e;font-size:.8rem}} .diff{{margin-top:4px;font-family:monospace;font-size:.85rem}}
.del{{color:#f85149}} .add{{color:#3fb950}}
.source{{background:#161b22;border-radius:8px;overflow-x:auto;margin-top:1rem}}
.source table{{margin:0}} .ln{{color:#484f58;text-align:right;padding-right:1rem;user-select:none;width:3rem}}
.code pre{{margin:0;white-space:pre;color:#c9d1d9;font-size:.85rem}}
tr.flagged{{background:#f8514915}} .count{{color:#8b949e;font-weight:400;font-size:.85rem}}
.filter-bar{{margin:1rem 0;display:flex;gap:.5rem}}
.filter-btn{{background:#21262d;color:#c9d1d9;border:1px solid #30363d;padding:4px 12px;border-radius:6px;cursor:pointer}}
.filter-btn.active{{background:#388bfd40;border-color:#388bfd}}
</style></head><body>
<div class="header">
  <div class="score-ring"><span class="val">{score}</span><span class="grade">Grade {grade}</span></div>
  <div>
    <h1>sauravadapt Report</h1>
    <p style="color:#8b949e">{_html_esc(self.filename)} &mdash; {len(self.lines)} lines, {total} findings</p>
    <div class="stats">
      <div class="stat"><div class="n" style="color:#f85149">{high}</div><div class="l">High</div></div>
      <div class="stat"><div class="n" style="color:#d29922">{med}</div><div class="l">Medium</div></div>
      <div class="stat"><div class="n" style="color:#388bfd">{low}</div><div class="l">Low</div></div>
    </div>
  </div>
</div>
<h2>Optimization Passes</h2>
{''.join(findings_html) if findings_html else '<p style="color:#3fb950">✅ No findings — code is well optimized!</p>'}
<h2>Source (flagged lines highlighted)</h2>
<div class="source"><table>{source_lines}</table></div>
<script>
// Simple filter
document.querySelectorAll('.filter-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    btn.classList.toggle('active');
  }});
}});
</script>
</body></html>'''


def _html_esc(text):
    """Escape HTML entities."""
    return (str(text).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        prog='sauravadapt',
        description='Autonomous Adaptive Optimizer for sauravcode (.srv) programs')
    ap.add_argument('file', help='.srv file to analyze')
    ap.add_argument('--apply', action='store_true',
                    help='Write optimized version to <file>_optimized.srv')
    ap.add_argument('--html', nargs='?', const='auto', default=None,
                    help='Generate HTML report (optional: output path)')
    ap.add_argument('--diff', action='store_true',
                    help='Show unified diff of optimizations')
    ap.add_argument('--aggressive', action='store_true',
                    help='Enable all optimization passes (default)')
    ap.add_argument('--auto', action='store_true',
                    help='Automatically apply safe optimizations')
    ap.add_argument('--watch', action='store_true',
                    help='Watch mode - re-analyze on file changes')
    ap.add_argument('--json', action='store_true',
                    help='Output findings as JSON')

    args = ap.parse_args()

    if not os.path.isfile(args.file):
        print(f"Error: file not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    def run_once():
        with open(args.file, 'r', encoding='utf-8') as fh:
            source = fh.read()

        opt = AdaptiveOptimizer(source, args.file)
        opt.analyze(aggressive=args.aggressive)

        if args.json:
            import json
            data = {
                'file': args.file,
                'lines': len(opt.lines),
                'health_score': opt.health_score(),
                'findings': [
                    {'pass': f.pass_name, 'line': f.line, 'message': f.message,
                     'impact': f.impact, 'category': f.category,
                     'auto_fixable': f.auto_fixable}
                    for f in opt.findings
                ]
            }
            print(json.dumps(data, indent=2))
            return

        opt.print_report()

        if args.diff:
            d = opt.generate_diff()
            if d:
                print("  -- Diff --")
                print(d)
            else:
                print("  No diff - no auto-fixable changes.\n")

        if args.auto:
            new_source, applied = opt.apply_safe_optimizations()
            if applied:
                with open(args.file, 'w', encoding='utf-8') as fh:
                    fh.write(new_source)
                print(f"  [OK] Applied {len(applied)} safe optimization(s) to {args.file}")
            else:
                print("  No auto-fixable optimizations to apply.")

        if args.apply and not args.auto:
            new_source, applied = opt.apply_safe_optimizations()
            base, ext = os.path.splitext(args.file)
            out_path = f"{base}_optimized{ext}"
            with open(out_path, 'w', encoding='utf-8') as fh:
                fh.write(new_source)
            print(f"  [OK] Optimized version written to {out_path}")

        if args.html is not None:
            if args.html == 'auto':
                base, _ = os.path.splitext(args.file)
                html_path = f"{base}_adapt_report.html"
            else:
                html_path = args.html
            html = opt.generate_html()
            with open(html_path, 'w', encoding='utf-8') as fh:
                fh.write(html)
            print(f"  [OK] HTML report: {html_path}")

    if args.watch:
        print(f"  [W] Watching {args.file} for changes (Ctrl+C to stop)\n")
        last_hash = None
        try:
            while True:
                with open(args.file, 'rb') as fh:
                    h = hashlib.md5(fh.read()).hexdigest()
                if h != last_hash:
                    last_hash = h
                    os.system('cls' if os.name == 'nt' else 'clear')
                    run_once()
                    print(f"\n  (watching... last check {time.strftime('%H:%M:%S')})")
                time.sleep(2)
        except KeyboardInterrupt:
            print("\n  Watch stopped.")
    else:
        run_once()


if __name__ == '__main__':
    main()
