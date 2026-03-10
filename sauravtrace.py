#!/usr/bin/env python3
"""sauravtrace — Execution tracer for sauravcode (.srv) programs.

Records every statement execution, function call, and variable change,
producing a step-by-step trace log.  Useful for debugging, education,
and understanding program flow without breakpoints.

Usage:
    python sauravtrace.py FILE.srv                 # human-readable trace
    python sauravtrace.py FILE.srv --json           # JSON trace output
    python sauravtrace.py FILE.srv --limit 100      # stop after 100 steps
    python sauravtrace.py FILE.srv --vars            # show variables at each step
    python sauravtrace.py FILE.srv --calls-only      # only trace function calls
    python sauravtrace.py FILE.srv --no-builtins     # hide builtin function calls
    python sauravtrace.py FILE.srv --summary         # show execution summary only
    python sauravtrace.py FILE.srv -o trace.json     # write trace to file
"""

import argparse
import json
import os
import sys
import time
from io import StringIO

__version__ = "1.0.0"

# ── Import interpreter machinery ──────────────────────────────────
# Add the directory containing saurav.py to the path
_script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _script_dir)

from saurav import (
    tokenize, Parser, Interpreter,
    FunctionNode, FunctionCallNode, AssignmentNode, PrintNode,
    ReturnNode, IfNode, WhileNode, ForNode, ForEachNode,
    TryCatchNode, ThrowNode, MatchNode, ImportNode, BreakNode,
    ContinueNode, YieldNode, IndexedAssignmentNode, AppendNode,
    PopNode, EnumNode, AssertNode, ReturnSignal, ThrowSignal,
)


# ── Trace Event ──────────────────────────────────────────────────

class TraceEvent:
    """A single trace event recording one interpreter step."""

    __slots__ = ('step', 'kind', 'line', 'detail', 'depth', 'variables',
                 'timestamp_ns')

    def __init__(self, step, kind, line, detail, depth, variables=None):
        self.step = step
        self.kind = kind          # 'statement' | 'call' | 'return' | 'assign' | 'print' | 'error'
        self.line = line          # source line number (or None)
        self.detail = detail      # human-readable description
        self.depth = depth        # call stack depth
        self.variables = variables  # snapshot of variables (if --vars)
        self.timestamp_ns = time.monotonic_ns()

    def to_dict(self):
        d = {
            'step': self.step,
            'kind': self.kind,
            'line': self.line,
            'detail': self.detail,
            'depth': self.depth,
        }
        if self.variables is not None:
            d['variables'] = self.variables
        return d


# ── Step Limit ───────────────────────────────────────────────────

class StepLimitReached(Exception):
    """Raised when the trace step limit is exceeded."""
    pass


# ── Tracing Interpreter ─────────────────────────────────────────

class TracingInterpreter(Interpreter):
    """Subclass of Interpreter that records execution trace events."""

    # Map AST node types to human-readable names
    _NODE_NAMES = {
        AssignmentNode: 'assign',
        IndexedAssignmentNode: 'index_assign',
        PrintNode: 'print',
        FunctionNode: 'function_def',
        ReturnNode: 'return',
        YieldNode: 'yield',
        IfNode: 'if',
        WhileNode: 'while',
        ForNode: 'for',
        ForEachNode: 'foreach',
        TryCatchNode: 'try_catch',
        ThrowNode: 'throw',
        MatchNode: 'match',
        ImportNode: 'import',
        BreakNode: 'break',
        ContinueNode: 'continue',
        AppendNode: 'append',
        PopNode: 'pop',
        EnumNode: 'enum',
        AssertNode: 'assert',
        FunctionCallNode: 'call',
    }

    def __init__(self, *, track_vars=False, calls_only=False,
                 no_builtins=False, limit=None):
        super().__init__()
        self.trace = []
        self._step = 0
        self._depth = 0
        self._track_vars = track_vars
        self._calls_only = calls_only
        self._no_builtins = no_builtins
        self._limit = limit
        self._call_count = 0
        self._assign_count = 0
        self._print_count = 0
        self._source_lines = []

    def set_source(self, source_code):
        """Store source lines for line-level annotation."""
        self._source_lines = source_code.splitlines()

    def _get_line(self, node):
        """Extract line number from an AST node."""
        return getattr(node, 'line_num', None)

    def _snap_vars(self):
        """Take a snapshot of current variables for the trace."""
        if not self._track_vars:
            return None
        snap = {}
        for k, v in self.variables.items():
            snap[k] = _safe_repr(v)
        return snap

    def _record(self, kind, line, detail):
        """Record a trace event."""
        if self._calls_only and kind not in ('call', 'return', 'error'):
            return
        self._step += 1
        if self._limit and self._step > self._limit:
            raise StepLimitReached()
        event = TraceEvent(
            step=self._step,
            kind=kind,
            line=line,
            detail=detail,
            depth=self._depth,
            variables=self._snap_vars(),
        )
        self.trace.append(event)

    # ── Override interpret() to trace statements ─────────────────

    def interpret(self, ast):
        node_name = self._NODE_NAMES.get(type(ast), type(ast).__name__)
        line = self._get_line(ast)

        if isinstance(ast, AssignmentNode):
            self._record('assign', line, f'{ast.name} = ...')
            self._assign_count += 1
        elif isinstance(ast, PrintNode):
            self._record('print', line, 'print ...')
            self._print_count += 1
        elif isinstance(ast, FunctionNode):
            self._record('statement', line, f'def {ast.name}({", ".join(ast.params)})')
        elif isinstance(ast, ReturnNode):
            self._record('return', line, 'return ...')
        elif isinstance(ast, IfNode):
            self._record('statement', line, 'if ...')
        elif isinstance(ast, WhileNode):
            self._record('statement', line, 'while ...')
        elif isinstance(ast, (ForNode, ForEachNode)):
            self._record('statement', line, 'for ...')
        elif isinstance(ast, ImportNode):
            self._record('statement', line, f'import {getattr(ast, "module_name", "?")}')
        elif not isinstance(ast, FunctionCallNode):
            self._record('statement', line, node_name)

        return super().interpret(ast)

    # ── Override execute_function to trace calls ─────────────────

    def execute_function(self, call_node):
        func_name = call_node.name
        is_builtin = func_name in self.builtins

        if is_builtin and self._no_builtins:
            return super().execute_function(call_node)

        line = self._get_line(call_node)
        arg_count = len(call_node.args) if hasattr(call_node, 'args') else 0
        self._record('call', line, f'{func_name}({arg_count} args)')
        self._call_count += 1

        self._depth += 1
        try:
            result = super().execute_function(call_node)
        except Exception:
            self._depth -= 1
            raise
        self._depth -= 1

        self._record('return', line, f'{func_name} -> {_safe_repr(result)}')
        return result

    # ── Summary ──────────────────────────────────────────────────

    def summary(self):
        """Return execution summary statistics."""
        return {
            'total_steps': self._step,
            'function_calls': self._call_count,
            'assignments': self._assign_count,
            'prints': self._print_count,
            'max_depth': max((e.depth for e in self.trace), default=0),
            'unique_variables': len(set(
                e.detail.split(' = ')[0]
                for e in self.trace
                if e.kind == 'assign'
            )),
            'trace_events': len(self.trace),
        }


# ── Helpers ──────────────────────────────────────────────────────

def _safe_repr(value, max_len=80):
    """Safe string representation of a value, truncated."""
    try:
        if isinstance(value, str):
            r = repr(value)
        elif isinstance(value, float) and value == int(value):
            r = str(int(value))
        elif isinstance(value, bool):
            r = 'true' if value else 'false'
        elif isinstance(value, list):
            if len(value) > 10:
                items = ', '.join(_safe_repr(x, 20) for x in value[:10])
                r = f'[{items}, ... ({len(value)} items)]'
            else:
                items = ', '.join(_safe_repr(x, 20) for x in value)
                r = f'[{items}]'
        elif isinstance(value, dict):
            if len(value) > 5:
                r = f'{{{len(value)} entries}}'
            else:
                pairs = ', '.join(f'{k}: {_safe_repr(v, 20)}' for k, v in value.items())
                r = f'{{{pairs}}}'
        elif callable(value):
            r = '<function>'
        elif value is None:
            r = 'null'
        else:
            r = str(value)
    except Exception:
        r = '<error>'
    if len(r) > max_len:
        r = r[:max_len - 3] + '...'
    return r


# ── Formatters ───────────────────────────────────────────────────

_KIND_ICONS = {
    'statement': '  ',
    'assign':    '<- ',
    'call':      '-> ',
    'return':    '<= ',
    'print':     '|  ',
    'error':     'X  ',
}

_KIND_COLORS = {
    'statement': '\033[37m',     # white
    'assign':    '\033[36m',     # cyan
    'call':      '\033[33m',     # yellow
    'return':    '\033[32m',     # green
    'print':     '\033[35m',     # magenta
    'error':     '\033[31m',     # red
}

_RESET = '\033[0m'


def format_trace_human(trace, source_lines=None, color=True):
    """Format trace events as human-readable text."""
    lines = []
    for event in trace:
        indent = '  ' * event.depth
        icon = _KIND_ICONS.get(event.kind, '  ')
        line_str = f'L{event.line}' if event.line else '   '

        if color:
            c = _KIND_COLORS.get(event.kind, '')
            line = f'{c}{event.step:5d} {line_str:>5s} {indent}{icon}{event.detail}{_RESET}'
        else:
            line = f'{event.step:5d} {line_str:>5s} {indent}{icon}{event.detail}'

        lines.append(line)

        if event.variables:
            var_str = ', '.join(f'{k}={v}' for k, v in sorted(event.variables.items()))
            pad = ' ' * 12
            if color:
                lines.append(f'\033[90m{pad}{indent}   vars: {var_str}{_RESET}')
            else:
                lines.append(f'{pad}{indent}   vars: {var_str}')

    return '\n'.join(lines)


def format_trace_json(trace):
    """Format trace events as JSON."""
    return json.dumps([e.to_dict() for e in trace], indent=2)


def format_summary(summary, color=True):
    """Format execution summary."""
    lines = []
    if color:
        lines.append(f'\033[1m-- Execution Summary --\033[0m')
    else:
        lines.append('-- Execution Summary --')
    lines.append(f'  Total steps:      {summary["total_steps"]}')
    lines.append(f'  Function calls:   {summary["function_calls"]}')
    lines.append(f'  Assignments:      {summary["assignments"]}')
    lines.append(f'  Print statements: {summary["prints"]}')
    lines.append(f'  Max call depth:   {summary["max_depth"]}')
    lines.append(f'  Unique variables: {summary["unique_variables"]}')
    lines.append(f'  Trace events:     {summary["trace_events"]}')
    return '\n'.join(lines)


# ── Main ─────────────────────────────────────────────────────────

def run_trace(source_code, filename='<stdin>', **kwargs):
    """Run a sauravcode program with tracing enabled.

    Returns (interpreter, captured_output) tuple.
    """
    tokens = list(tokenize(source_code))
    parser = Parser(tokens)
    ast_nodes = parser.parse()

    interp = TracingInterpreter(**kwargs)
    interp.set_source(source_code)
    abs_filename = os.path.abspath(filename)
    interp._source_dir = os.path.dirname(abs_filename)
    interp._imported_modules.add(abs_filename)

    # Capture stdout
    old_stdout = sys.stdout
    captured = StringIO()
    sys.stdout = captured

    try:
        for node in ast_nodes:
            if isinstance(node, FunctionCallNode):
                interp.execute_function(node)
            else:
                interp.interpret(node)
    except StepLimitReached:
        pass
    except ThrowSignal as e:
        msg = e.message
        if isinstance(msg, float) and msg == int(msg):
            msg = int(msg)
        interp._record('error', None, f'Uncaught error: {msg}')
    except (RuntimeError, RecursionError) as e:
        interp._record('error', None, f'Error: {e}')
    finally:
        sys.stdout = old_stdout

    return interp, captured.getvalue()


def main():
    ap = argparse.ArgumentParser(
        description='Execution tracer for sauravcode programs',
        prog='sauravtrace',
    )
    ap.add_argument('file', help='Path to .srv file to trace')
    ap.add_argument('--json', action='store_true',
                    help='Output trace as JSON')
    ap.add_argument('--limit', type=int, default=None,
                    help='Maximum number of trace steps')
    ap.add_argument('--vars', action='store_true',
                    help='Show variable snapshots at each step')
    ap.add_argument('--calls-only', action='store_true',
                    help='Only trace function calls and returns')
    ap.add_argument('--no-builtins', action='store_true',
                    help='Hide builtin function calls')
    ap.add_argument('--summary', action='store_true',
                    help='Show execution summary only')
    ap.add_argument('--no-color', action='store_true',
                    help='Disable colored output')
    ap.add_argument('-o', '--output', metavar='FILE',
                    help='Write trace to file instead of stdout')
    ap.add_argument('--version', action='version',
                    version=f'sauravtrace {__version__}')

    args = ap.parse_args()

    if not os.path.isfile(args.file):
        print(f'Error: file not found: {args.file}', file=sys.stderr)
        sys.exit(1)

    with open(args.file, encoding='utf-8') as f:
        source = f.read()

    color = not args.no_color and not args.json and not args.output

    interp, output = run_trace(
        source, args.file,
        track_vars=args.vars,
        calls_only=args.calls_only,
        no_builtins=args.no_builtins,
        limit=args.limit,
    )

    # Format output
    if args.json:
        result = json.dumps({
            'file': args.file,
            'trace': [e.to_dict() for e in interp.trace],
            'summary': interp.summary(),
            'output': output,
        }, indent=2)
    elif args.summary:
        result = format_summary(interp.summary(), color=color)
    else:
        parts = []
        parts.append(format_trace_human(interp.trace, color=color))
        if output.strip():
            parts.append('')
            if color:
                parts.append(f'\033[1m-- Program Output --\033[0m')
            else:
                parts.append('-- Program Output --')
            parts.append(output.rstrip())
        parts.append('')
        parts.append(format_summary(interp.summary(), color=color))
        result = '\n'.join(parts)

    # Write output
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(result)
        print(f'Trace written to {args.output}')
    else:
        print(result)


if __name__ == '__main__':
    main()
