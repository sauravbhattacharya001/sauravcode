#!/usr/bin/env python3
"""
sauravprof.py - Performance profiler for sauravcode programs.

Instruments the sauravcode interpreter to collect per-function timing,
call counts, call graphs, and hot-line analysis. Generates human-readable
reports and machine-parseable JSON output.

Usage:
    python sauravprof.py program.srv              # Run with default report
    python sauravprof.py program.srv --top 20     # Show top 20 functions
    python sauravprof.py program.srv --json       # Output JSON report
    python sauravprof.py program.srv --callgraph  # Include call graph
    python sauravprof.py program.srv --threshold 1.0  # Only show funcs >= 1ms
"""

import time
import json as _json
import sys
import os
import argparse
from collections import defaultdict

# Import the sauravcode interpreter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from saurav import tokenize, Parser, Interpreter


class ProfileStats:
    """Accumulated profiling statistics for a single function."""

    __slots__ = ('name', 'call_count', 'total_time', 'self_time',
                 'min_time', 'max_time', 'callers', 'callees')

    def __init__(self, name):
        self.name = name
        self.call_count = 0
        self.total_time = 0.0
        self.self_time = 0.0
        self.min_time = float('inf')
        self.max_time = 0.0
        self.callers = defaultdict(int)
        self.callees = defaultdict(int)

    @property
    def avg_time(self):
        return self.total_time / self.call_count if self.call_count else 0

    def to_dict(self):
        return {
            'name': self.name,
            'call_count': self.call_count,
            'total_time_ms': round(self.total_time * 1000, 4),
            'self_time_ms': round(self.self_time * 1000, 4),
            'avg_time_ms': round(self.avg_time * 1000, 4),
            'min_time_ms': round(self.min_time * 1000, 4) if self.min_time != float('inf') else 0,
            'max_time_ms': round(self.max_time * 1000, 4),
            'callers': dict(self.callers),
            'callees': dict(self.callees),
        }


class CallFrame:
    """A single frame on the profiler's shadow call stack."""

    __slots__ = ('name', 'start_time', 'child_time')

    def __init__(self, name, start_time):
        self.name = name
        self.start_time = start_time
        self.child_time = 0.0


class Profiler:
    """Instruments the sauravcode Interpreter to collect profiling data."""

    def __init__(self):
        self.stats = {}
        self.call_stack = []
        self.total_calls = 0
        self.start_time = 0.0
        self.end_time = 0.0

    def _get_stats(self, name):
        if name not in self.stats:
            self.stats[name] = ProfileStats(name)
        return self.stats[name]

    def on_call_enter(self, name):
        self.total_calls += 1
        caller = self.call_stack[-1].name if self.call_stack else '<top-level>'

        stats = self._get_stats(name)
        stats.call_count += 1
        stats.callers[caller] += 1

        caller_stats = self._get_stats(caller)
        caller_stats.callees[name] += 1

        self.call_stack.append(CallFrame(name, time.perf_counter()))

    def on_call_exit(self, name):
        end = time.perf_counter()
        if not self.call_stack:
            return

        frame = self.call_stack.pop()
        elapsed = end - frame.start_time

        stats = self._get_stats(name)
        stats.total_time += elapsed
        stats.self_time += elapsed - frame.child_time
        stats.min_time = min(stats.min_time, elapsed)
        stats.max_time = max(stats.max_time, elapsed)

        if self.call_stack:
            self.call_stack[-1].child_time += elapsed

    def instrument(self, interpreter):
        """Monkey-patch the interpreter to capture profiling events.

        Must also update the interpreter's dispatch tables since they
        capture method references at __init__ time — a simple attribute
        override would be bypassed by the cached dispatch entries.
        """
        profiler = self
        original_execute = interpreter.execute_function

        def profiled_execute(node, env=None):
            if hasattr(node, 'name'):
                name = node.name
            elif hasattr(node, 'function_name'):
                name = node.function_name
            else:
                name = '<anonymous>'

            profiler.on_call_enter(name)
            try:
                if env is not None:
                    return original_execute(node, env)
                return original_execute(node)
            finally:
                profiler.on_call_exit(name)

        interpreter.execute_function = profiled_execute

        # Patch dispatch tables — they cache method refs from __init__
        from saurav import FunctionCallNode
        if hasattr(interpreter, '_evaluate_dispatch'):
            interpreter._evaluate_dispatch[FunctionCallNode] = profiled_execute
        if hasattr(interpreter, '_interpret_dispatch'):
            interpreter._interpret_dispatch[FunctionCallNode] = lambda node: profiled_execute(node)

        # Also wrap builtin calls if the method exists
        if hasattr(interpreter, '_call_builtin'):
            original_builtin = interpreter._call_builtin

            def profiled_builtin(name, args):
                profiler.on_call_enter('builtin:' + name)
                try:
                    return original_builtin(name, args)
                finally:
                    profiler.on_call_exit('builtin:' + name)

            interpreter._call_builtin = profiled_builtin

    def run_program(self, code, source_dir=None):
        """Parse and run a sauravcode program with profiling."""
        self.start_time = time.perf_counter()

        tokens = tokenize(code)
        parser = Parser(tokens)
        ast = parser.parse()

        interpreter = Interpreter()
        if source_dir:
            interpreter._source_dir = source_dir
        self.instrument(interpreter)

        try:
            for node in ast:
                interpreter.interpret(node)
        finally:
            self.end_time = time.perf_counter()

    @property
    def wall_time(self):
        return self.end_time - self.start_time

    def get_sorted_stats(self, sort_by='total_time', top_n=None, threshold_ms=0):
        entries = list(self.stats.values())
        entries = [
            e for e in entries
            if e.name != '<top-level>'
            and e.total_time * 1000 >= threshold_ms
        ]

        key_map = {
            'total_time': lambda s: s.total_time,
            'self_time': lambda s: s.self_time,
            'call_count': lambda s: s.call_count,
            'avg_time': lambda s: s.avg_time,
            'max_time': lambda s: s.max_time,
        }
        key_fn = key_map.get(sort_by, key_map['total_time'])
        entries.sort(key=key_fn, reverse=True)

        if top_n:
            entries = entries[:top_n]
        return entries

    def format_report(self, sort_by='total_time', top_n=30, threshold_ms=0,
                      show_callgraph=False):
        """Generate a human-readable profiling report.

        Delegates each report section to a dedicated helper method for
        clarity and testability.
        """
        lines = []
        sep = '=' * 78
        lines.append(sep)
        lines.append('  SAURAVCODE PROFILER REPORT')
        lines.append(sep)
        lines.append('')
        lines.append('  Wall time:    {:.2f} ms'.format(self.wall_time * 1000))
        lines.append('  Total calls:  {}'.format(self.total_calls))
        lines.append('  Functions:    {}'.format(len(self.stats) - 1))
        lines.append('')

        entries = self.get_sorted_stats(sort_by, top_n, threshold_ms)
        if not entries:
            lines.append('  No functions matched the filter criteria.')
            return '\n'.join(lines)

        self._format_function_table(entries, lines)
        self._format_time_distribution(entries, lines)
        if show_callgraph:
            self._format_call_graph(entries, lines)
        self._format_hot_spots(entries, lines)
        self._format_recommendations(entries, lines)

        lines.append(sep)
        return '\n'.join(lines)

    def _format_function_table(self, entries, lines):
        """Append the per-function timing table to *lines*."""
        hdr = '  {:<30} {:>7} {:>10} {:>10} {:>10} {:>10}'.format(
            'Function', 'Calls', 'Total(ms)', 'Self(ms)', 'Avg(ms)', 'Max(ms)')
        lines.append(hdr)
        lines.append('  ' + '-' * 78)

        for stats in entries:
            name = stats.name
            if len(name) > 29:
                name = name[:26] + '...'
            row = '  {:<30} {:>7} {:>10.3f} {:>10.3f} {:>10.3f} {:>10.3f}'.format(
                name, stats.call_count,
                stats.total_time * 1000,
                stats.self_time * 1000,
                stats.avg_time * 1000,
                stats.max_time * 1000)
            lines.append(row)
        lines.append('')

    def _format_time_distribution(self, entries, lines):
        """Append the percentage-bar time distribution to *lines*."""
        if self.wall_time <= 0:
            return
        lines.append('  Time Distribution:')
        for stats in entries[:10]:
            pct = (stats.total_time / self.wall_time) * 100
            bar_len = int(pct / 2)
            bar = '#' * bar_len
            name = stats.name[:25]
            lines.append('    {:<25} {:5.1f}% |{}'.format(name, pct, bar))
        lines.append('')

    def _format_call_graph(self, entries, lines):
        """Append the caller→callee graph section to *lines*."""
        if not entries:
            return
        lines.append('  Call Graph:')
        lines.append('  ' + '-' * 40)
        shown = set()
        for stats in entries[:15]:
            if stats.name in shown:
                continue
            shown.add(stats.name)
            if stats.callees:
                pairs = sorted(stats.callees.items(),
                               key=lambda x: x[1], reverse=True)[:5]
                callees_str = ', '.join(
                    '{}({})'.format(c, n) for c, n in pairs)
                lines.append('    {} -> {}'.format(stats.name, callees_str))
        lines.append('')

    def _format_hot_spots(self, entries, lines):
        """Append the top-5 hot-spot list (by self time) to *lines*."""
        self_sorted = sorted(
            [e for e in entries if e.self_time > 0],
            key=lambda s: s.self_time, reverse=True
        )
        if not self_sorted:
            return
        lines.append('  Hot Spots (by self time):')
        for i, stats in enumerate(self_sorted[:5], 1):
            pct = (stats.self_time / self.wall_time * 100) if self.wall_time > 0 else 0
            lines.append('    {}. {} -- {:.3f} ms ({:.1f}%)'.format(
                i, stats.name, stats.self_time * 1000, pct))
        lines.append('')

    def _format_recommendations(self, entries, lines):
        """Append auto-generated optimisation recommendations to *lines*."""
        recommendations = self._generate_recommendations(entries)
        if not recommendations:
            return
        lines.append('  Recommendations:')
        for rec in recommendations:
            lines.append('    * ' + rec)
        lines.append('')

    def _generate_recommendations(self, entries):
        recs = []
        for stats in entries:
            if (stats.call_count >= 100 and
                    stats.avg_time * 1000 > 0.01 and
                    not stats.name.startswith('builtin:')):
                recs.append(
                    '{} called {} times (avg {:.3f} ms). '
                    'Consider memoization or caching.'.format(
                        stats.name, stats.call_count,
                        stats.avg_time * 1000))

            if (stats.call_count > 5 and stats.avg_time > 0 and
                    stats.max_time / stats.avg_time > 10):
                recs.append(
                    '{} has high variance: max {:.3f} ms vs avg {:.3f} ms. '
                    'Check for worst-case input patterns.'.format(
                        stats.name, stats.max_time * 1000,
                        stats.avg_time * 1000))

            if stats.name in stats.callees:
                depth = stats.callees[stats.name]
                recs.append(
                    '{} is recursive ({} self-calls). '
                    'Consider iterative rewrite if stack depth is a concern.'.format(
                        stats.name, depth))

        return recs[:8]

    def to_json(self, sort_by='total_time', top_n=None, threshold_ms=0):
        entries = self.get_sorted_stats(sort_by, top_n, threshold_ms)
        return _json.dumps({
            'wall_time_ms': round(self.wall_time * 1000, 4),
            'total_calls': self.total_calls,
            'function_count': len(self.stats) - 1,
            'functions': [e.to_dict() for e in entries],
        }, indent=2)


def main():
    ap = argparse.ArgumentParser(
        description='Profile a sauravcode program')
    ap.add_argument('file', help='sauravcode (.srv) file to profile')
    ap.add_argument('--top', '-n', type=int, default=30,
                    help='Show top N functions (default: 30)')
    ap.add_argument('--sort', '-s', default='total_time',
                    choices=['total_time', 'self_time', 'call_count',
                             'avg_time', 'max_time'],
                    help='Sort by (default: total_time)')
    ap.add_argument('--threshold', '-t', type=float, default=0,
                    help='Only show functions >= threshold ms')
    ap.add_argument('--json', '-j', action='store_true',
                    help='Output JSON instead of text report')
    ap.add_argument('--callgraph', '-g', action='store_true',
                    help='Include call graph in report')
    ap.add_argument('--quiet', '-q', action='store_true',
                    help='Suppress program output')
    args = ap.parse_args()

    if not os.path.isfile(args.file):
        print('Error: File not found: ' + args.file, file=sys.stderr)
        sys.exit(1)

    with open(args.file, 'r', encoding='utf-8') as f:
        code = f.read()

    source_dir = os.path.dirname(os.path.abspath(args.file))

    if args.quiet:
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()

    profiler = Profiler()
    try:
        profiler.run_program(code, source_dir)
    except Exception as e:
        if args.quiet:
            sys.stdout = old_stdout
        print('Error during execution: ' + str(e), file=sys.stderr)
        sys.exit(1)

    if args.quiet:
        sys.stdout = old_stdout

    if args.json:
        print(profiler.to_json(args.sort, args.top, args.threshold))
    else:
        print()
        print(profiler.format_report(args.sort, args.top, args.threshold,
                                      args.callgraph))


if __name__ == '__main__':
    main()
