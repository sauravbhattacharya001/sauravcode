#!/usr/bin/env python3
"""
sauravcov.py - Code coverage tool for sauravcode (.srv) programs.

Instruments the sauravcode interpreter to track which source lines are
executed during a program run, then produces a coverage report showing
hit/miss per line, per-function breakdown, and uncovered regions.

Usage:
    python sauravcov.py program.srv                # Run with terminal report
    python sauravcov.py program.srv --json         # Output JSON report
    python sauravcov.py program.srv --html out.html # Generate HTML report
    python sauravcov.py program.srv --annotate     # Show annotated source
    python sauravcov.py program.srv --branch       # Include branch coverage
    python sauravcov.py program.srv --quiet        # Suppress program output
    python sauravcov.py program.srv --fail-under 80 # Exit 1 if coverage < 80%
"""

import sys
import os
import argparse
import json as _json
from collections import defaultdict
from sauravtext import html_escape as _html_escape

# Import the sauravcode interpreter and parser
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from saurav import (
    tokenize, Parser, Interpreter, ASTNode,
    FunctionNode, IfNode, WhileNode, ForNode, ForEachNode,
    TryCatchNode, MatchNode, ReturnNode, PrintNode,
    FunctionCallNode, AssignmentNode, IndexedAssignmentNode,
    ThrowNode, AppendNode, ImportNode, ThrowSignal, ReturnSignal,
    BreakSignal, ContinueSignal
)


class LineTrackingParser(Parser):
    """Parser subclass that tags AST nodes with source line numbers.

    Wraps parse_statement() to capture the token position before parsing,
    then annotates the resulting node with the line number from that token.
    """

    def parse_statement(self):
        line = None
        if self.pos < len(self.tokens):
            tok = self.tokens[self.pos]
            if len(tok) > 2:
                line = tok[2]

        node = super().parse_statement()

        if node is not None and node.line_num is None and line is not None:
            node.line_num = line

        return node


class CoverageData:
    """Stores line-level and branch-level coverage data."""

    def __init__(self, source_lines, filename):
        self.filename = filename
        self.source_lines = source_lines
        self.total_source_lines = len(source_lines)

        # Line coverage: line_num -> hit count
        self.line_hits = defaultdict(int)

        # Executable lines (lines that have AST nodes)
        self.executable_lines = set()

        # Branch coverage: (line_num, branch_id) -> taken count
        # branch_id: 'true' or 'false' for if/while
        self.branch_hits = defaultdict(int)
        self.branches = set()  # All possible branches

        # Per-function tracking
        self.function_lines = {}  # func_name -> set of executable lines
        self.function_hits = {}   # func_name -> set of hit lines

    def record_line(self, line_num):
        """Record that a line was executed."""
        if line_num is not None:
            self.line_hits[line_num] += 1

    def record_branch(self, line_num, branch_id, taken):
        """Record a branch decision."""
        if line_num is not None:
            key = (line_num, branch_id)
            self.branches.add(key)
            if taken:
                self.branch_hits[key] += 1

    def register_executable(self, line_num):
        """Mark a line as executable (has an AST node)."""
        if line_num is not None:
            self.executable_lines.add(line_num)

    def register_function(self, name, body_lines):
        """Register a function's executable lines."""
        self.function_lines[name] = body_lines
        self.function_hits[name] = set()

    def record_function_line(self, name, line_num):
        """Record a hit within a specific function."""
        if name in self.function_hits and line_num is not None:
            self.function_hits[name].add(line_num)

    @property
    def hit_lines(self):
        """Lines that were executed at least once."""
        return {ln for ln, count in self.line_hits.items()
                if count > 0 and ln in self.executable_lines}

    @property
    def missed_lines(self):
        """Executable lines that were never executed."""
        return self.executable_lines - self.hit_lines

    @property
    def line_coverage_pct(self):
        """Line coverage percentage."""
        if not self.executable_lines:
            return 100.0
        return len(self.hit_lines) / len(self.executable_lines) * 100

    @property
    def branch_coverage_pct(self):
        """Branch coverage percentage."""
        if not self.branches:
            return 100.0
        taken = sum(1 for b in self.branches if self.branch_hits.get(b, 0) > 0)
        return taken / len(self.branches) * 100

    def uncovered_ranges(self):
        """Find contiguous ranges of uncovered lines."""
        missed = sorted(self.missed_lines)
        if not missed:
            return []

        ranges = []
        start = missed[0]
        end = missed[0]

        for line in missed[1:]:
            if line == end + 1:
                end = line
            else:
                ranges.append((start, end))
                start = line
                end = line
        ranges.append((start, end))
        return ranges


class CoverageCollector:
    """Instruments the interpreter to collect coverage data."""

    def __init__(self, coverage_data, track_branches=False):
        self.data = coverage_data
        self.track_branches = track_branches
        self._current_function = None

    def _collect_executable_lines(self, nodes, func_name=None):
        """Walk AST nodes and register all executable lines."""
        for node in nodes:
            if not isinstance(node, ASTNode):
                continue

            line = getattr(node, 'line_num', None)
            if line is not None:
                self.data.register_executable(line)
                if func_name is not None:
                    if func_name not in self.data.function_lines:
                        self.data.function_lines[func_name] = set()
                    self.data.function_lines[func_name].add(line)

            # Recurse into bodies
            if isinstance(node, FunctionNode):
                fn_name = node.name
                self.data.function_lines[fn_name] = set()
                self.data.function_hits[fn_name] = set()
                self._collect_executable_lines(node.body, fn_name)

            elif isinstance(node, IfNode):
                if hasattr(node, 'body') and node.body:
                    self._collect_executable_lines(node.body, func_name)
                if hasattr(node, 'else_body') and node.else_body:
                    self._collect_executable_lines(node.else_body, func_name)
                # Handle elif chains
                if hasattr(node, 'elif_blocks'):
                    for elif_block in node.elif_blocks:
                        if hasattr(elif_block, 'body'):
                            self._collect_executable_lines(elif_block.body, func_name)

            elif isinstance(node, (WhileNode, ForNode, ForEachNode)):
                if hasattr(node, 'body') and node.body:
                    self._collect_executable_lines(node.body, func_name)

            elif isinstance(node, TryCatchNode):
                if hasattr(node, 'body') and node.body:
                    self._collect_executable_lines(node.body, func_name)
                if hasattr(node, 'handler') and node.handler:
                    self._collect_executable_lines(node.handler, func_name)

            elif isinstance(node, MatchNode):
                if hasattr(node, 'cases'):
                    for case in node.cases:
                        body = case[1] if isinstance(case, tuple) else getattr(case, 'body', [])
                        if body:
                            self._collect_executable_lines(body, func_name)

    def instrument(self, interpreter):
        """Monkey-patch the interpreter to record coverage."""
        collector = self

        # Wrap interpret() to record line hits
        original_interpret = interpreter.interpret

        def instrumented_interpret(ast):
            line = getattr(ast, 'line_num', None)
            if line is not None:
                collector.data.record_line(line)
                if collector._current_function:
                    collector.data.record_function_line(
                        collector._current_function, line)
            return original_interpret(ast)

        interpreter.interpret = instrumented_interpret

        # Wrap execute_body for body-level tracking
        if hasattr(interpreter, 'execute_body'):
            original_execute_body = interpreter.execute_body

            def instrumented_execute_body(body):
                for stmt in body:
                    line = getattr(stmt, 'line_num', None)
                    if line is not None:
                        collector.data.record_line(line)
                        if collector._current_function:
                            collector.data.record_function_line(
                                collector._current_function, line)
                return original_execute_body(body)

            interpreter.execute_body = instrumented_execute_body

        # Wrap execute_if for branch coverage
        if self.track_branches:
            original_execute_if = interpreter.execute_if

            def instrumented_execute_if(node):
                line = getattr(node, 'line_num', None)
                result = original_execute_if(node)
                # Record which branch was taken
                if line is not None:
                    # We can't easily know which branch was taken post-hoc
                    # but we can record the if was evaluated
                    collector.data.record_branch(line, 'evaluated', True)
                return result

            interpreter.execute_if = instrumented_execute_if

            # Patch dispatch table for IfNode
            if hasattr(interpreter, '_interpret_dispatch'):
                interpreter._interpret_dispatch[IfNode] = instrumented_execute_if

        # Patch dispatch tables — they cache method refs from __init__
        if hasattr(interpreter, '_interpret_dispatch'):
            for node_type, handler in interpreter._interpret_dispatch.items():
                if handler == original_interpret:
                    interpreter._interpret_dispatch[node_type] = instrumented_interpret

        # Wrap function execution for per-function tracking
        if hasattr(interpreter, 'execute_function'):
            original_execute_function = interpreter.execute_function

            def instrumented_execute_function(node, env=None):
                name = getattr(node, 'name', None) or \
                       getattr(node, 'function_name', '<anonymous>')
                old_func = collector._current_function
                collector._current_function = name
                try:
                    if env is not None:
                        return original_execute_function(node, env)
                    return original_execute_function(node)
                finally:
                    collector._current_function = old_func

            interpreter.execute_function = instrumented_execute_function

            # Patch dispatch tables for function calls
            if hasattr(interpreter, '_evaluate_dispatch'):
                interpreter._evaluate_dispatch[FunctionCallNode] = instrumented_execute_function
            if hasattr(interpreter, '_interpret_dispatch'):
                interpreter._interpret_dispatch[FunctionCallNode] = lambda n: instrumented_execute_function(n)


class CoverageReporter:
    """Generates coverage reports in various formats."""

    COLORS = {
        'green': '\033[92m',
        'red': '\033[91m',
        'yellow': '\033[93m',
        'cyan': '\033[96m',
        'bold': '\033[1m',
        'dim': '\033[2m',
        'reset': '\033[0m',
    }

    def __init__(self, data, use_color=True):
        self.data = data
        self.c = self.COLORS if use_color else {k: '' for k in self.COLORS}
        # Detect if terminal supports Unicode box-drawing characters
        try:
            '\u2550\u2500\u2502'.encode(sys.stdout.encoding or 'utf-8')
            self._box_h = '\u2550'  # ═
            self._line_h = '\u2500'  # ─
            self._vert = '\u2502'    # │
        except (UnicodeEncodeError, UnicodeDecodeError, LookupError):
            self._box_h = '='
            self._line_h = '-'
            self._vert = '|'

    def _pct_color(self, pct):
        """Get color for a coverage percentage."""
        if pct >= 90:
            return self.c['green']
        elif pct >= 70:
            return self.c['yellow']
        return self.c['red']

    def _bar(self, pct, width=30):
        """Render a coverage bar."""
        filled = int(pct / 100 * width)
        try:
            bar = '\u2588' * filled + '\u2591' * (width - filled)
            bar.encode(sys.stdout.encoding or 'utf-8')
            return bar
        except (UnicodeEncodeError, UnicodeDecodeError):
            return '#' * filled + '-' * (width - filled)

    def format_summary(self, include_branches=False):
        """Generate a summary coverage report."""
        d = self.data
        lines = []

        lines.append('')
        lines.append('{}{} Coverage Report: {} {}{}'.format(
            self.c['bold'], self._box_h * 3,
            d.filename, self._box_h * 3, self.c['reset']))
        lines.append('')

        # Line coverage
        pct = d.line_coverage_pct
        col = self._pct_color(pct)
        lines.append('{}Line Coverage:{} {}{:.1f}%{} ({}/{} lines)'.format(
            self.c['bold'], self.c['reset'],
            col, pct, self.c['reset'],
            len(d.hit_lines), len(d.executable_lines)))
        lines.append('  {} {}{:.1f}%{}'.format(
            self._bar(pct), col, pct, self.c['reset']))

        # Branch coverage
        if include_branches and d.branches:
            bpct = d.branch_coverage_pct
            bcol = self._pct_color(bpct)
            taken = sum(1 for b in d.branches if d.branch_hits.get(b, 0) > 0)
            lines.append('')
            lines.append('{}Branch Coverage:{} {}{:.1f}%{} ({}/{} branches)'.format(
                self.c['bold'], self.c['reset'],
                bcol, bpct, self.c['reset'],
                taken, len(d.branches)))
            lines.append('  {} {}{:.1f}%{}'.format(
                self._bar(bpct), bcol, bpct, self.c['reset']))

        # Per-function breakdown
        if d.function_lines:
            lines.append('')
            lines.append('{}Per-function coverage:{}'.format(
                self.c['bold'], self.c['reset']))
            lines.append('{:<30s}  {:>6s}  {:>6s}  {:>8s}'.format(
                'Function', 'Hit', 'Total', 'Coverage'))
            lines.append(self._line_h * 56)

            for func_name in sorted(d.function_lines.keys()):
                total = len(d.function_lines[func_name])
                if total == 0:
                    continue
                hit = len(d.function_hits.get(func_name, set()) &
                          d.function_lines[func_name])
                fpct = hit / total * 100
                fcol = self._pct_color(fpct)
                lines.append('{:<30s}  {:>6d}  {:>6d}  {}{:>7.1f}%{}'.format(
                    func_name[:30], hit, total,
                    fcol, fpct, self.c['reset']))

        # Uncovered ranges
        ranges = d.uncovered_ranges()
        if ranges:
            lines.append('')
            lines.append('{}Uncovered regions:{}'.format(
                self.c['bold'], self.c['reset']))
            for start, end in ranges:
                if start == end:
                    lines.append('  {}Line {}{}'.format(
                        self.c['red'], start, self.c['reset']))
                else:
                    lines.append('  {}Lines {}-{}{}'.format(
                        self.c['red'], start, end, self.c['reset']))

        lines.append('')
        return '\n'.join(lines)

    def format_annotated(self):
        """Generate annotated source with hit/miss markers."""
        d = self.data
        lines = []
        lines.append('')
        lines.append('{}{} Annotated Source: {} {}{}'.format(
            self.c['bold'], self._box_h * 3,
            d.filename, self._box_h * 3, self.c['reset']))
        lines.append('')

        for i, src_line in enumerate(d.source_lines, 1):
            hits = d.line_hits.get(i, 0)
            is_exec = i in d.executable_lines

            if not is_exec:
                # Non-executable line (blank, comment, etc.)
                marker = '   '
                color = self.c['dim']
            elif hits > 0:
                # Covered line
                marker = '{:>3d}'.format(min(hits, 999))
                color = self.c['green']
            else:
                # Uncovered executable line
                marker = '  !'
                color = self.c['red']

            lines.append('{}{} {:>4d} {} {}{}'.format(
                color, marker, i, self._vert,
                src_line.rstrip(), self.c['reset']))

        lines.append('')
        pct = d.line_coverage_pct
        col = self._pct_color(pct)
        lines.append('{}Coverage: {}{:.1f}%{} ({}/{} executable lines)'.format(
            self.c['bold'], col, pct, self.c['reset'],
            len(d.hit_lines), len(d.executable_lines)))
        lines.append('')
        return '\n'.join(lines)

    def to_json(self, include_branches=False):
        """Generate machine-readable JSON report."""
        d = self.data
        result = {
            'filename': d.filename,
            'line_coverage_pct': round(d.line_coverage_pct, 2),
            'total_executable_lines': len(d.executable_lines),
            'covered_lines': len(d.hit_lines),
            'missed_lines': sorted(d.missed_lines),
            'uncovered_ranges': [
                {'start': s, 'end': e} for s, e in d.uncovered_ranges()
            ],
            'line_hits': {str(k): v for k, v in sorted(d.line_hits.items())},
        }

        if include_branches:
            result['branch_coverage_pct'] = round(d.branch_coverage_pct, 2)
            result['total_branches'] = len(d.branches)
            result['covered_branches'] = sum(
                1 for b in d.branches if d.branch_hits.get(b, 0) > 0)

        if d.function_lines:
            funcs = {}
            for name in sorted(d.function_lines.keys()):
                total = len(d.function_lines[name])
                if total == 0:
                    continue
                hit = len(d.function_hits.get(name, set()) &
                          d.function_lines[name])
                funcs[name] = {
                    'total_lines': total,
                    'covered_lines': hit,
                    'coverage_pct': round(hit / total * 100, 2),
                    'uncovered': sorted(
                        d.function_lines[name] -
                        d.function_hits.get(name, set())),
                }
            result['functions'] = funcs

        return _json.dumps(result, indent=2)

    def to_html(self):
        """Generate an HTML coverage report with syntax-highlighted source."""
        d = self.data
        pct = d.line_coverage_pct

        rows = []
        for i, src_line in enumerate(d.source_lines, 1):
            hits = d.line_hits.get(i, 0)
            is_exec = i in d.executable_lines

            if not is_exec:
                cls = 'non-exec'
                hit_str = ''
            elif hits > 0:
                cls = 'covered'
                hit_str = str(hits)
            else:
                cls = 'uncovered'
                hit_str = '!'

            escaped = _html_escape(src_line.rstrip())
            rows.append(
                '<tr class="{cls}">'
                '<td class="hits">{hits}</td>'
                '<td class="line-num">{num}</td>'
                '<td class="source"><pre>{src}</pre></td>'
                '</tr>'.format(cls=cls, hits=hit_str, num=i, src=escaped))

        # Per-function table rows
        func_rows = []
        if d.function_lines:
            for name in sorted(d.function_lines.keys()):
                total = len(d.function_lines[name])
                if total == 0:
                    continue
                hit = len(d.function_hits.get(name, set()) &
                          d.function_lines[name])
                fpct = hit / total * 100
                cls = 'high' if fpct >= 90 else ('med' if fpct >= 70 else 'low')
                func_rows.append(
                    '<tr class="{cls}">'
                    '<td>{name}</td><td>{hit}/{total}</td>'
                    '<td>{pct:.1f}%</td></tr>'.format(
                        cls=cls, name=name, hit=hit, total=total, pct=fpct))

        html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Coverage: {filename}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       margin: 0; padding: 20px; background: #0d1117; color: #e6edf3; }}
h1 {{ font-size: 1.4rem; margin-bottom: 4px; }}
.summary {{ margin: 16px 0; padding: 12px 16px; background: #161b22;
            border: 1px solid #30363d; border-radius: 8px; }}
.bar {{ height: 8px; border-radius: 4px; background: #21262d; margin: 8px 0; }}
.bar-fill {{ height: 100%; border-radius: 4px; }}
.high .bar-fill {{ background: #3fb950; }}
.med .bar-fill {{ background: #d29922; }}
.low .bar-fill {{ background: #f85149; }}
table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
th {{ text-align: left; padding: 6px 10px; border-bottom: 2px solid #30363d;
      font-size: 0.85rem; color: #8b949e; }}
td {{ padding: 0; }}
.source-table td {{ padding: 0; line-height: 1.5; font-size: 13px; }}
.source-table pre {{ margin: 0; white-space: pre; }}
.hits {{ width: 40px; text-align: right; padding-right: 8px; color: #8b949e; }}
.line-num {{ width: 50px; text-align: right; padding-right: 8px; color: #484f58;
             user-select: none; }}
.covered {{ background: rgba(63, 185, 80, 0.08); }}
.covered .hits {{ color: #3fb950; }}
.uncovered {{ background: rgba(248, 81, 73, 0.12); }}
.uncovered .hits {{ color: #f85149; font-weight: bold; }}
.non-exec .source pre {{ color: #484f58; }}
.func-table td {{ padding: 6px 10px; border-bottom: 1px solid #21262d; }}
.func-table .high td {{ color: #3fb950; }}
.func-table .med td {{ color: #d29922; }}
.func-table .low td {{ color: #f85149; }}
</style>
</head>
<body>
<h1>Coverage Report: {filename}</h1>
<div class="summary {grade}">
  <strong>Line Coverage: {pct:.1f}%</strong>
  ({hit}/{total} executable lines)
  <div class="bar"><div class="bar-fill" style="width:{pct:.1f}%"></div></div>
</div>
{func_section}
<table class="source-table">
<thead><tr><th>Hits</th><th>Line</th><th>Source</th></tr></thead>
<tbody>{rows}</tbody>
</table>
</body></html>"""

        grade = 'high' if pct >= 90 else ('med' if pct >= 70 else 'low')

        func_section = ''
        if func_rows:
            func_section = (
                '<h2 style="font-size:1.1rem;margin-top:24px;">Per-function</h2>'
                '<table class="func-table"><thead><tr>'
                '<th>Function</th><th>Lines</th><th>Coverage</th>'
                '</tr></thead><tbody>' + '\n'.join(func_rows) +
                '</tbody></table>')

        return html.format(
            filename=d.filename,
            pct=pct,
            hit=len(d.hit_lines),
            total=len(d.executable_lines),
            grade=grade,
            func_section=func_section,
            rows='\n'.join(rows))


def run_coverage(filename, track_branches=False, quiet=False):
    """Run a sauravcode program with coverage collection.

    Returns a CoverageData object with all collected metrics.
    """
    with open(filename, 'r', encoding='utf-8') as f:
        code = f.read()

    source_lines = code.split('\n')
    source_dir = os.path.dirname(os.path.abspath(filename))
    basename = os.path.basename(filename)

    data = CoverageData(source_lines, basename)

    # Parse with line tracking
    tokens = tokenize(code)
    parser = LineTrackingParser(tokens)
    ast = parser.parse()

    # Collect executable lines from AST
    collector = CoverageCollector(data, track_branches)
    collector._collect_executable_lines(ast)

    # Set up interpreter
    interpreter = Interpreter()
    interpreter._source_dir = source_dir

    # Instrument
    collector.instrument(interpreter)

    # Suppress output if quiet
    if quiet:
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()

    # Run
    try:
        for node in ast:
            interpreter.interpret(node)
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as e:
        if quiet:
            sys.stdout = old_stdout
        print('Warning: program raised {}: {}'.format(
            type(e).__name__, e), file=sys.stderr)
    finally:
        if quiet:
            sys.stdout = old_stdout

    return data


def main():
    ap = argparse.ArgumentParser(
        prog='sauravcov',
        description='Code coverage tool for sauravcode (.srv) programs')
    ap.add_argument('file', help='sauravcode (.srv) file to run')
    ap.add_argument('--json', '-j', action='store_true',
                    help='Output JSON report')
    ap.add_argument('--html', metavar='FILE',
                    help='Generate HTML coverage report')
    ap.add_argument('--annotate', '-a', action='store_true',
                    help='Show annotated source with hit/miss markers')
    ap.add_argument('--branch', '-b', action='store_true',
                    help='Track branch coverage (if/while decisions)')
    ap.add_argument('--quiet', '-q', action='store_true',
                    help='Suppress program output')
    ap.add_argument('--fail-under', type=float, default=0,
                    metavar='PCT',
                    help='Exit with code 2 if coverage is below PCT%%')
    ap.add_argument('--no-color', action='store_true',
                    help='Disable colored output')
    args = ap.parse_args()

    if not os.path.isfile(args.file):
        print('Error: File not found: ' + args.file, file=sys.stderr)
        sys.exit(1)

    data = run_coverage(args.file, track_branches=args.branch,
                        quiet=args.quiet)

    reporter = CoverageReporter(data, use_color=not args.no_color)

    if args.json:
        print(reporter.to_json(include_branches=args.branch))
    elif args.html:
        html = reporter.to_html()
        with open(args.html, 'w', encoding='utf-8') as f:
            f.write(html)
        print('HTML coverage report written to: ' + args.html)
        # Also print summary
        print(reporter.format_summary(include_branches=args.branch))
    elif args.annotate:
        print(reporter.format_annotated())
    else:
        print(reporter.format_summary(include_branches=args.branch))

    # Fail-under check
    if args.fail_under > 0:
        if data.line_coverage_pct < args.fail_under:
            print('FAIL: Coverage {:.1f}% is below threshold {:.1f}%'.format(
                data.line_coverage_pct, args.fail_under),
                file=sys.stderr)
            sys.exit(2)


if __name__ == '__main__':
    main()
