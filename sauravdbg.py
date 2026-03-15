#!/usr/bin/env python3
"""
sauravdbg — Interactive step-through debugger for Sauravcode.

Usage:
    python sauravdbg.py <file.srv>             # Start debugging
    python sauravdbg.py <file.srv> --break 5   # Start with breakpoint at line 5
    python sauravdbg.py --help                 # Show help

Debugger Commands:
    s, step        Execute one statement and stop
    n, next        Execute until next line (step over function calls)
    c, continue    Run until next breakpoint
    b <line>       Set breakpoint at line number
    rb <line>      Remove breakpoint at line number
    bl             List all breakpoints
    p <expr>       Print variable or expression value
    vars           Show all variables in current scope
    stack          Show call stack
    where          Show current source location with context
    list [n]       Show source code around current line (default ±5 lines)
    watch <var>    Add variable to watchlist (printed after each step)
    unwatch <var>  Remove variable from watchlist
    restart        Restart execution from beginning
    q, quit        Exit debugger
    h, help        Show this help

Breakpoint Conditions:
    b 10 if x > 5  Set conditional breakpoint at line 10
"""

import sys
import os
import re
import traceback

# Add parent directory to path so we can import saurav
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from saurav import (
    tokenize, Parser, Interpreter, ASTNode,
    AssignmentNode, FunctionNode, ReturnNode, PrintNode,
    FunctionCallNode, IfNode, WhileNode, ForNode, ForEachNode,
    TryCatchNode, ThrowNode, MatchNode, ImportNode,
    BreakSignal, ContinueSignal, ReturnSignal, YieldSignal,
)


class Breakpoint:
    """A debugger breakpoint with optional condition."""

    def __init__(self, line, condition=None):
        self.line = line
        self.condition = condition  # String expression to evaluate
        self.hit_count = 0
        self.enabled = True

    def __repr__(self):
        s = f"Breakpoint(line={self.line}"
        if self.condition:
            s += f", if {self.condition}"
        if self.hit_count > 0:
            s += f", hits={self.hit_count}"
        return s + ")"


class DebugInterpreter(Interpreter):
    """Interpreter subclass with debugging support.

    Hooks into interpret() to provide breakpoints, stepping,
    variable inspection, and call stack tracking.
    """

    def __init__(self, source_lines):
        super().__init__()
        self.source_lines = source_lines
        self.breakpoints = {}       # line_num -> Breakpoint
        self.stepping = True        # Start in step mode
        self.step_over = False      # Step over function calls
        self.step_depth = 0         # Call depth when step-over started
        self.current_line = 0       # Current source line
        self.call_stack = []        # List of (function_name, line_num)
        self.watchlist = set()      # Variables to print after each step
        self._stopped = False       # Set to True to quit
        self._last_command = 's'    # Repeat last command on empty input

    def interpret(self, ast):
        """Override interpret to inject debug hooks before each statement."""
        if self._stopped:
            raise KeyboardInterrupt("Debugger quit")

        line = getattr(ast, 'line_num', None)
        if line is not None:
            self.current_line = line

        # Check if we should stop here
        should_stop = False

        if self.stepping:
            should_stop = True
        elif self.step_over and self._call_depth <= self.step_depth:
            should_stop = True
            self.step_over = False
            self.stepping = True

        # Check breakpoints
        if line is not None and line in self.breakpoints:
            bp = self.breakpoints[line]
            if bp.enabled:
                if bp.condition:
                    try:
                        # Evaluate condition in current scope
                        if self._eval_condition(bp.condition):
                            bp.hit_count += 1
                            should_stop = True
                    except Exception:
                        pass  # Skip broken conditions silently
                else:
                    bp.hit_count += 1
                    should_stop = True

        if should_stop and line is not None:
            self._show_watches()
            self._debug_prompt(line, ast)

        return super().interpret(ast)

    def execute_function(self, ast):
        """Track function calls on the debug call stack."""
        name = ast.name if hasattr(ast, 'name') else str(ast.function)
        line = getattr(ast, 'line_num', self.current_line)
        self.call_stack.append((name, line))
        try:
            result = super().execute_function(ast)
            return result
        finally:
            if self.call_stack:
                self.call_stack.pop()

    def _eval_condition(self, condition_str):
        """Evaluate a breakpoint condition string."""
        # Simple variable lookup and comparison
        try:
            return eval(condition_str, {"__builtins__": {}}, self.variables)
        except Exception:
            return False

    def _show_watches(self):
        """Print watched variables if they exist in scope."""
        for var in sorted(self.watchlist):
            if var in self.variables:
                val = self.variables[var]
                print(f"  {_CYAN}{var}{_RESET} = {_format_value(val)}")

    def _debug_prompt(self, line, ast):
        """Show the interactive debug prompt."""
        # Show current line
        node_type = type(ast).__name__.replace('Node', '')
        print(f"\n{_YELLOW}→ Line {line}{_RESET}  [{_DIM}{node_type}{_RESET}]")
        self._show_source_line(line)

        while True:
            try:
                cmd = input(f"{_GREEN}(sauravdbg){_RESET} ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                self._stopped = True
                raise KeyboardInterrupt("Debugger quit")

            if not cmd:
                cmd = self._last_command

            self._last_command = cmd
            parts = cmd.split(None, 1)
            command = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ''

            if command in ('s', 'step'):
                self.stepping = True
                self.step_over = False
                return

            elif command in ('n', 'next'):
                self.stepping = False
                self.step_over = True
                self.step_depth = self._call_depth
                return

            elif command in ('c', 'continue'):
                self.stepping = False
                self.step_over = False
                return

            elif command in ('b', 'break'):
                self._cmd_breakpoint(args)

            elif command in ('rb', 'remove'):
                self._cmd_remove_breakpoint(args)

            elif command in ('bl', 'breakpoints'):
                self._cmd_list_breakpoints()

            elif command in ('p', 'print'):
                self._cmd_print(args)

            elif command == 'vars':
                self._cmd_vars()

            elif command == 'stack':
                self._cmd_stack()

            elif command in ('where', 'w'):
                self._show_context(line, 5)

            elif command in ('list', 'l'):
                n = int(args) if args.isdigit() else 5
                self._show_context(line, n)

            elif command == 'watch':
                if args:
                    self.watchlist.add(args.strip())
                    print(f"  Watching: {args.strip()}")
                else:
                    print(f"  Watched: {', '.join(sorted(self.watchlist)) or '(none)'}")

            elif command == 'unwatch':
                self.watchlist.discard(args.strip())
                print(f"  Unwatched: {args.strip()}")

            elif command == 'restart':
                raise RestartSignal()

            elif command in ('q', 'quit', 'exit'):
                self._stopped = True
                raise KeyboardInterrupt("Debugger quit")

            elif command in ('h', 'help'):
                self._cmd_help()

            else:
                # Try evaluating as an expression
                try:
                    result = eval(cmd, {"__builtins__": {}}, self.variables)
                    print(f"  {_format_value(result)}")
                except Exception:
                    print(f"  {_RED}Unknown command: {command}. Type 'h' for help.{_RESET}")

    def _cmd_breakpoint(self, args):
        """Set a breakpoint: b <line> [if <condition>]"""
        if not args:
            print(f"  {_RED}Usage: b <line> [if <condition>]{_RESET}")
            return
        match = re.match(r'(\d+)(?:\s+if\s+(.+))?', args)
        if not match:
            print(f"  {_RED}Invalid breakpoint syntax{_RESET}")
            return
        line = int(match.group(1))
        condition = match.group(2)
        if line < 1 or line > len(self.source_lines):
            print(f"  {_RED}Line {line} out of range (1-{len(self.source_lines)}){_RESET}")
            return
        self.breakpoints[line] = Breakpoint(line, condition)
        msg = f"  Breakpoint set at line {line}"
        if condition:
            msg += f" (if {condition})"
        print(msg)

    def _cmd_remove_breakpoint(self, args):
        """Remove a breakpoint: rb <line>"""
        if not args or not args.strip().isdigit():
            print(f"  {_RED}Usage: rb <line>{_RESET}")
            return
        line = int(args.strip())
        if line in self.breakpoints:
            del self.breakpoints[line]
            print(f"  Breakpoint at line {line} removed")
        else:
            print(f"  No breakpoint at line {line}")

    def _cmd_list_breakpoints(self):
        """List all breakpoints."""
        if not self.breakpoints:
            print("  No breakpoints set")
            return
        for line in sorted(self.breakpoints):
            bp = self.breakpoints[line]
            status = "enabled" if bp.enabled else "disabled"
            cond = f" if {bp.condition}" if bp.condition else ""
            print(f"  Line {line}: {status}{cond} (hits: {bp.hit_count})")

    def _cmd_print(self, args):
        """Print a variable or expression value."""
        if not args:
            print(f"  {_RED}Usage: p <variable or expression>{_RESET}")
            return
        name = args.strip()
        # Check variables first
        if name in self.variables:
            print(f"  {name} = {_format_value(self.variables[name])}")
        elif name in self.functions:
            fn = self.functions[name]
            params = ', '.join(fn.params) if hasattr(fn, 'params') else '?'
            print(f"  {name}({params}) [function, {len(fn.body)} statements]")
        else:
            # Try evaluating as expression
            try:
                result = eval(name, {"__builtins__": {}}, self.variables)
                print(f"  {_format_value(result)}")
            except Exception as e:
                print(f"  {_RED}Cannot evaluate '{name}': {e}{_RESET}")

    def _cmd_vars(self):
        """Show all variables in current scope."""
        if not self.variables:
            print("  (no variables)")
            return
        for name in sorted(self.variables):
            val = self.variables[name]
            print(f"  {_CYAN}{name}{_RESET} = {_format_value(val)}")

    def _cmd_stack(self):
        """Show the call stack."""
        if not self.call_stack:
            print("  (top-level)")
            return
        for i, (name, line) in enumerate(reversed(self.call_stack)):
            prefix = "→ " if i == 0 else "  "
            print(f"  {prefix}{name}() at line {line}")
        print(f"  <module>")

    def _cmd_help(self):
        """Show help."""
        print(f"""
{_YELLOW}sauravdbg — Debugger Commands{_RESET}
  {_GREEN}s{_RESET}, step        Step into (execute one statement)
  {_GREEN}n{_RESET}, next        Step over (skip into function calls)
  {_GREEN}c{_RESET}, continue    Run until next breakpoint
  {_GREEN}b{_RESET} <line>       Set breakpoint (optionally: b 10 if x > 5)
  {_GREEN}rb{_RESET} <line>      Remove breakpoint
  {_GREEN}bl{_RESET}             List breakpoints
  {_GREEN}p{_RESET} <expr>       Print variable or expression
  {_GREEN}vars{_RESET}           Show all variables
  {_GREEN}stack{_RESET}          Show call stack
  {_GREEN}where{_RESET}          Show current position in source
  {_GREEN}list{_RESET} [n]       Show source (±n lines around current)
  {_GREEN}watch{_RESET} <var>    Watch a variable
  {_GREEN}unwatch{_RESET} <var>  Stop watching
  {_GREEN}restart{_RESET}        Restart execution
  {_GREEN}q{_RESET}, quit        Exit debugger
  Or type any expression to evaluate it.
""")

    def _show_source_line(self, line):
        """Show a single source line with arrow."""
        if 1 <= line <= len(self.source_lines):
            src = self.source_lines[line - 1].rstrip()
            bp_marker = f"{_RED}●{_RESET}" if line in self.breakpoints else " "
            print(f"  {bp_marker} {_DIM}{line:4d}{_RESET} │ {src}")

    def _show_context(self, line, radius=5):
        """Show source code around the current line."""
        start = max(1, line - radius)
        end = min(len(self.source_lines), line + radius)
        for i in range(start, end + 1):
            src = self.source_lines[i - 1].rstrip()
            bp_marker = f"{_RED}●{_RESET}" if i in self.breakpoints else " "
            arrow = f"{_YELLOW}→{_RESET}" if i == line else " "
            print(f"  {bp_marker}{arrow} {_DIM}{i:4d}{_RESET} │ {src}")


class RestartSignal(Exception):
    """Signal to restart debugging from the beginning."""
    pass


# ── ANSI colors ──

def _supports_color():
    """Check if terminal supports ANSI colors."""
    if os.environ.get('NO_COLOR'):
        return False
    if sys.platform == 'win32':
        return os.environ.get('TERM') or os.environ.get('WT_SESSION')
    return hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()

if _supports_color():
    _RED = '\033[31m'
    _GREEN = '\033[32m'
    _YELLOW = '\033[33m'
    _CYAN = '\033[36m'
    _DIM = '\033[2m'
    _RESET = '\033[0m'
else:
    _RED = _GREEN = _YELLOW = _CYAN = _DIM = _RESET = ''


def _format_value(val, max_len=80):
    """Format a value for display, truncating long collections."""
    if isinstance(val, str):
        s = repr(val)
    elif isinstance(val, list):
        if len(val) > 10:
            items = ', '.join(repr(v) for v in val[:8])
            s = f"[{items}, ... ({len(val)} items)]"
        else:
            s = repr(val)
    elif isinstance(val, dict):
        if len(val) > 5:
            items = ', '.join(f"{k}: {repr(v)}" for k, v in list(val.items())[:4])
            s = f"{{{items}, ... ({len(val)} keys)}}"
        else:
            s = repr(val)
    else:
        s = repr(val)
    if len(s) > max_len:
        s = s[:max_len - 3] + '...'
    return s


def annotate_line_numbers(ast_list, source_lines):
    """Walk the AST and set line_num on nodes where possible.

    The parser doesn't always set line_num, so we infer it from
    the node's position in the statement list (1-indexed).
    We also walk into block bodies for compound statements.
    """
    if not isinstance(ast_list, list):
        return

    # Map each source line to its first non-empty content for matching
    for i, node in enumerate(ast_list):
        if not isinstance(node, ASTNode):
            continue
        if node.line_num is None:
            # Estimate: distribute nodes across source lines
            # This is rough but better than no line info
            node.line_num = _infer_line(node, source_lines, i, len(ast_list))

        # Recurse into compound statement bodies
        if hasattr(node, 'body') and isinstance(node.body, list):
            annotate_line_numbers(node.body, source_lines)
        if hasattr(node, 'else_body') and isinstance(node.else_body, list):
            annotate_line_numbers(node.else_body, source_lines)
        if hasattr(node, 'elif_blocks'):
            for _, elif_body in (node.elif_blocks or []):
                if isinstance(elif_body, list):
                    annotate_line_numbers(elif_body, source_lines)
        if hasattr(node, 'catch_body') and isinstance(node.catch_body, list):
            annotate_line_numbers(node.catch_body, source_lines)
        if hasattr(node, 'cases'):
            for case in (node.cases or []):
                if hasattr(case, 'body') and isinstance(case.body, list):
                    annotate_line_numbers(case.body, source_lines)


def _infer_line(node, source_lines, index, total):
    """Infer a node's source line from its type and position."""
    # If we have a name or value, try to find it in source
    search_terms = []
    if hasattr(node, 'name') and isinstance(node.name, str):
        search_terms.append(node.name)
    if hasattr(node, 'function') and isinstance(node.function, str):
        search_terms.append(node.function)

    for term in search_terms:
        for i, line in enumerate(source_lines):
            stripped = line.strip()
            if stripped and not stripped.startswith('#') and term in stripped:
                return i + 1

    # Fallback: proportional distribution
    if total > 0:
        ratio = index / total
        return max(1, min(len(source_lines), int(ratio * len(source_lines)) + 1))
    return 1


def run_debugger(filepath, initial_breakpoints=None):
    """Run the debugger on a .srv file."""
    if not os.path.exists(filepath):
        print(f"{_RED}Error: File not found: {filepath}{_RESET}")
        sys.exit(1)

    with open(filepath, 'r') as f:
        source = f.read()

    source_lines = source.split('\n')

    print(f"{_YELLOW}sauravdbg{_RESET} — Sauravcode Debugger")
    print(f"Loaded: {filepath} ({len(source_lines)} lines)")
    print(f"Type {_GREEN}h{_RESET} for help, {_GREEN}s{_RESET} to step, {_GREEN}c{_RESET} to continue\n")

    while True:
        try:
            tokens = tokenize(source)
            parser = Parser(tokens)
            ast = parser.parse()

            # Annotate AST nodes with line numbers
            annotate_line_numbers(ast, source_lines)

            interp = DebugInterpreter(source_lines)

            # Set initial breakpoints
            if initial_breakpoints:
                for line in initial_breakpoints:
                    interp.breakpoints[line] = Breakpoint(line)
                    print(f"  Breakpoint set at line {line}")

            # Execute each top-level statement
            for node in ast:
                interp.interpret(node)

            print(f"\n{_GREEN}Program finished.{_RESET}")
            break

        except RestartSignal:
            print(f"\n{_YELLOW}Restarting...{_RESET}\n")
            continue

        except KeyboardInterrupt:
            print(f"\n{_YELLOW}Debugger exited.{_RESET}")
            break

        except ReturnSignal as e:
            print(f"\n{_GREEN}Program returned: {_format_value(e.value)}{_RESET}")
            break

        except Exception as e:
            print(f"\n{_RED}Runtime error: {e}{_RESET}")
            if hasattr(e, '__traceback__'):
                # Show a simplified traceback
                print(f"{_DIM}", end="")
                traceback.print_exc()
                print(f"{_RESET}", end="")
            break


def main():
    """CLI entry point."""
    args = sys.argv[1:]

    if not args or '--help' in args or '-h' in args:
        print(__doc__)
        sys.exit(0)

    filepath = None
    breakpoints = []

    i = 0
    while i < len(args):
        if args[i] == '--break' and i + 1 < len(args):
            breakpoints.append(int(args[i + 1]))
            i += 2
        elif not args[i].startswith('-'):
            filepath = args[i]
            i += 1
        else:
            print(f"Unknown option: {args[i]}")
            sys.exit(1)

    if not filepath:
        print("Error: No .srv file specified")
        print("Usage: python sauravdbg.py <file.srv>")
        sys.exit(1)

    run_debugger(filepath, breakpoints or None)


if __name__ == '__main__':
    main()
