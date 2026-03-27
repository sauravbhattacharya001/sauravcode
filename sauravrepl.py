#!/usr/bin/env python3
"""sauravrepl.py — Interactive REPL for sauravcode.

Usage:
    python sauravrepl.py              # Start interactive REPL
    python sauravrepl.py -e "x = 5"  # Evaluate expression(s) and exit
    python sauravrepl.py --no-color   # Disable colored output
    python sauravrepl.py --history    # Show history file path

Features:
    - Persistent state across lines (variables, functions, enums)
    - Multi-line editing for blocks (if, while, for, fn, match, try, enum)
    - Command history with readline (Up/Down arrows)
    - Tab completion for variables, functions, builtins, and keywords
    - Special REPL commands (.help, .vars, .fns, .clear, .load, .save, .ast, .time, .reset)
    - Auto-prints expression results (no explicit 'print' needed)
    - Colored output (errors in red, results in green, prompts in cyan)
    - Graceful error recovery (errors don't kill the session)
    - Session save/load
"""

import sys
import os
import time
import re

# Add the script directory to path so we can import saurav
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

from saurav import (
    tokenize, Parser, Interpreter,
    FunctionCallNode, FunctionNode, AssignmentNode,
    IfNode, WhileNode, ForNode, ForEachNode, TryCatchNode,
    EnumNode, ImportNode, MatchNode, PrintNode,
    ReturnNode, ThrowNode, AssertNode,
    BreakNode, ContinueNode, YieldNode,
    IndexedAssignmentNode, AppendNode, PopNode,
)

try:
    from saurav import ThrowSignal
except ImportError:
    ThrowSignal = None  # Older versions may not have it

# ── Color helpers ─────────────────────────────────────────────────

_NO_COLOR = os.environ.get("NO_COLOR") is not None

def _color(code, text):
    if _NO_COLOR:
        return text
    return "\033[{}m{}\033[0m".format(code, text)

def _green(t):   return _color("32", t)
def _red(t):     return _color("31", t)
def _cyan(t):    return _color("36", t)
def _yellow(t):  return _color("33", t)
def _dim(t):     return _color("2", t)
def _bold(t):    return _color("1", t)

# ── Block detection ───────────────────────────────────────────────

_BLOCK_STARTERS = {
    "fn", "function", "if", "while", "for", "match",
    "try", "enum", "elif", "else", "catch",
}

def _starts_block(line):
    """Check if a line starts a multi-line block."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return False
    first_word = stripped.split()[0] if stripped.split() else ""
    return first_word in _BLOCK_STARTERS

def _is_continuation(line):
    """Check if a line is a block continuation (elif, else, catch)."""
    stripped = line.strip()
    if not stripped:
        return False
    first_word = stripped.split()[0]
    return first_word in {"elif", "else", "catch"}

# ── Completion ────────────────────────────────────────────────────

_KEYWORDS = [
    "fn", "return", "if", "elif", "else", "while", "for", "in",
    "print", "true", "false", "null", "and", "or", "not",
    "try", "catch", "throw", "match", "case", "enum",
    "import", "break", "continue", "yield", "assert",
    "append", "pop", "len", "type", "str", "int", "float",
    "input", "range", "abs", "min", "max", "sum",
    "map", "filter", "reduce", "sort", "reverse",
    "keys", "values", "has_key", "upper", "lower", "trim",
    "replace", "split", "join", "contains", "starts_with", "ends_with",
    "round", "floor", "ceil", "sqrt", "pow", "log",
    "random", "random_int", "time", "sleep",
]

class _Completer:
    """Tab completer for the REPL."""

    def __init__(self, interpreter):
        self._interpreter = interpreter
        self._matches = []

    def complete(self, text, state):
        if state == 0:
            candidates = list(_KEYWORDS)
            candidates.extend(self._interpreter.variables.keys())
            candidates.extend(self._interpreter.functions.keys())
            candidates.extend(self._interpreter.enums.keys())
            # Add REPL commands
            candidates.extend([
                ".help", ".vars", ".fns", ".clear", ".load",
                ".save", ".ast", ".time", ".reset", ".exit",
            ])
            if text:
                self._matches = [c for c in candidates
                                 if c.startswith(text)]
            else:
                self._matches = candidates
        return self._matches[state] if state < len(self._matches) else None

# ── REPL commands ─────────────────────────────────────────────────

_HELP_TEXT = """\
{title}

{commands}
  .help           Show this help message
  .vars           List all defined variables and their values
  .fns            List all defined functions
  .clear          Clear the screen
  .reset          Reset interpreter state (clear all variables/functions)
  .load <file>    Load and execute a .srv file
  .save <file>    Save current session history to a file
  .ast <code>     Show the AST for a line of code
  .time <code>    Time the execution of a line of code
  .exit / .quit   Exit the REPL

{tips}
  - Expressions auto-print their result (no 'print' needed)
  - Multi-line blocks: start with fn/if/while/for/match/try/enum,
    indent continuation lines, press Enter on empty line to execute
  - Use Up/Down arrows for history
  - Tab for completion (variables, functions, keywords)
"""

def _format_value(val, max_len=200):
    """Format a value for display, truncating long strings."""
    s = repr(val)
    if len(s) > max_len:
        s = s[:max_len] + "..."
    return s

# ── Core REPL ─────────────────────────────────────────────────────

class SauravRepl:
    """Interactive REPL for sauravcode."""

    def __init__(self, use_color=True, history_file=None):
        global _NO_COLOR
        if not use_color:
            _NO_COLOR = True

        self.interpreter = Interpreter()
        self.interpreter._source_dir = os.getcwd()
        self.history = []  # Lines entered this session
        self.history_file = history_file or os.path.expanduser(
            "~/.sauravcode_history")
        self._show_timing = False

        self._pending_line = None  # Line consumed during block peek-ahead

        # Set up readline if available
        try:
            import readline
            self._readline = readline
            readline.set_completer(_Completer(self.interpreter).complete)
            readline.parse_and_bind("tab: complete")
            # Load history
            if os.path.exists(self.history_file):
                readline.read_history_file(self.history_file)
        except ImportError:
            self._readline = None

    def run(self):
        """Main REPL loop."""
        self._print_banner()

        while True:
            try:
                # Check for a line consumed during block peek-ahead
                if self._pending_line is not None:
                    line = self._pending_line
                    self._pending_line = None
                else:
                    line = self._read_line()
                    if line is None:
                        # EOF (Ctrl+D)
                        print()
                        break

                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue

                # REPL commands
                if stripped.startswith("."):
                    if self._handle_command(stripped):
                        continue
                    # Not a recognized command — fall through to eval

                # Multi-line block detection
                if _starts_block(stripped):
                    block = self._read_block(line)
                    self._execute(block)
                else:
                    self._execute(line)

            except KeyboardInterrupt:
                print()  # Newline after ^C
                continue
            except EOFError:
                print()
                break

        self._save_history()
        print(_dim("Goodbye!"))

    def _print_banner(self):
        """Print the welcome banner."""
        print(_bold(_cyan("sauravcode")) + _dim(" REPL v1.0"))
        print(_dim('Type .help for commands, .exit to quit'))
        print()

    def _read_line(self):
        """Read a single line with prompt."""
        prompt = _cyan(">>> ") if not _NO_COLOR else ">>> "
        try:
            line = input(prompt)
            self.history.append(line)
            return line
        except EOFError:
            return None

    def _read_block(self, first_line):
        """Read a multi-line block until an empty line."""
        lines = [first_line]
        cont_prompt = _cyan("... ") if not _NO_COLOR else "... "

        while True:
            try:
                line = input(cont_prompt)
                self.history.append(line)

                if line.strip() == "":
                    # Check if the next line could be a continuation
                    # (elif, else, catch) — peek ahead
                    try:
                        peek = input(cont_prompt)
                        self.history.append(peek)
                        if _is_continuation(peek):
                            lines.append("")  # preserve blank line
                            lines.append(peek)
                            continue
                        elif peek.strip() == "":
                            # Double blank line = end of block
                            break
                        else:
                            # Non-continuation, non-blank = end block,
                            # but we already read it — save for next
                            # iteration so it doesn't get dropped
                            self._pending_line = peek
                            break
                    except EOFError:
                        break
                else:
                    lines.append(line)

            except EOFError:
                break
            except KeyboardInterrupt:
                print()
                return ""

        return "\n".join(lines)

    def _execute(self, code):
        """Execute a piece of code and print results."""
        if not code or not code.strip():
            return

        t0 = time.perf_counter()

        # First, try normal parse (statements)
        try:
            tokens = list(tokenize(code))
            parser = Parser(tokens)
            ast_nodes = parser.parse()
        except SyntaxError:
            # If statement parsing fails, try as a bare expression
            # by wrapping in a print-like evaluation
            try:
                tokens = list(tokenize(code))
                parser = Parser(tokens)
                expr = parser.parse_full_expression()
                # Evaluate the expression directly
                try:
                    result = self.interpreter.evaluate(expr)
                    elapsed = time.perf_counter() - t0
                    if result is not None:
                        self._print_result(result)
                    if self._show_timing:
                        print(_dim("  [{:.3f}ms]".format(elapsed * 1000)))
                except Exception as e:
                    self._print_error(e)
                return
            except Exception:
                pass
            # If both fail, report the original error
            print(_red("SyntaxError: could not parse input"))
            return
        except Exception as e:
            print(_red("SyntaxError: {}".format(e)))
            return

        try:
            result = None
            for node in ast_nodes:
                result = self._interpret_node(node)

            elapsed = time.perf_counter() - t0

            # Auto-print expression results
            if result is not None:
                self._print_result(result)

            if self._show_timing:
                print(_dim("  [{:.3f}ms]".format(elapsed * 1000)))

        except Exception as e:
            self._print_error(e)

    def _print_error(self, e):
        """Print an error message."""
        ename = type(e).__name__
        if ThrowSignal and isinstance(e, ThrowSignal):
            msg = e.message
            if isinstance(msg, float) and msg == int(msg):
                msg = int(msg)
            print(_red("Uncaught error: {}".format(msg)))
        elif isinstance(e, RuntimeError):
            print(_red("RuntimeError: {}".format(e)))
        else:
            print(_red("{}: {}".format(ename, e)))

    def _interpret_node(self, node):
        """Interpret a single AST node, returning a value for expressions."""
        # Statement nodes — use interpret()
        statement_types = (
            FunctionNode, AssignmentNode, IndexedAssignmentNode,
            IfNode, WhileNode, ForNode, ForEachNode,
            TryCatchNode, ThrowNode, PrintNode,
            EnumNode, ImportNode, MatchNode,
            AppendNode, PopNode, ReturnNode, YieldNode,
            BreakNode, ContinueNode, AssertNode,
        )

        if isinstance(node, statement_types):
            self.interpreter.interpret(node)
            return None

        # Expression nodes — use evaluate() and return result
        if isinstance(node, FunctionCallNode):
            return self.interpreter.execute_function(node)

        # Everything else is an expression
        try:
            return self.interpreter.evaluate(node)
        except Exception:
            # Fallback: try interpret
            self.interpreter.interpret(node)
            return None

    def _print_result(self, value):
        """Pretty-print a result value."""
        if isinstance(value, str):
            print(_green('"{}"'.format(value)))
        elif isinstance(value, bool):
            print(_green("true" if value else "false"))
        elif isinstance(value, float):
            if value == int(value) and abs(value) < 1e15:
                print(_green(str(int(value))))
            else:
                print(_green(str(value)))
        elif isinstance(value, list):
            formatted = ", ".join(_format_value(v, 50) for v in value)
            print(_green("[{}]".format(formatted)))
        elif isinstance(value, dict):
            pairs = []
            for k, v in value.items():
                pairs.append("{}: {}".format(
                    _format_value(k, 30), _format_value(v, 30)))
            print(_green("{{{}}}".format(", ".join(pairs))))
        elif value is None:
            pass  # Don't print null
        else:
            print(_green(str(value)))

    # ── REPL commands ─────────────────────────────────────────────

    def _handle_command(self, cmd):
        """Handle a dot-command. Returns True if handled."""
        parts = cmd.split(None, 1)
        command = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if command in (".exit", ".quit"):
            self._save_history()
            print(_dim("Goodbye!"))
            sys.exit(0)

        elif command == ".help":
            print(_HELP_TEXT.format(
                title=_bold("sauravcode REPL Commands"),
                commands=_yellow("Commands:"),
                tips=_yellow("Tips:")))
            return True

        elif command == ".vars":
            self._show_vars()
            return True

        elif command == ".fns":
            self._show_fns()
            return True

        elif command == ".clear":
            # Use ANSI escape sequence instead of os.system to avoid shell invocation
            print("\033[2J\033[H", end="", flush=True)
            return True

        elif command == ".reset":
            self.interpreter = Interpreter()
            self.interpreter._source_dir = os.getcwd()
            print(_yellow("State reset."))
            return True

        elif command == ".load":
            self._load_file(arg.strip())
            return True

        elif command == ".save":
            self._save_session(arg.strip())
            return True

        elif command == ".ast":
            self._show_ast(arg.strip())
            return True

        elif command == ".time":
            if arg.strip():
                old = self._show_timing
                self._show_timing = True
                self._execute(arg.strip())
                self._show_timing = old
            else:
                self._show_timing = not self._show_timing
                state = "on" if self._show_timing else "off"
                print(_dim("Timing: {}".format(state)))
            return True

        return False  # Not a known command

    def _show_vars(self):
        """Display all defined variables."""
        if not self.interpreter.variables:
            print(_dim("No variables defined."))
            return
        # Sort and display, skip internal/builtin
        for name in sorted(self.interpreter.variables.keys()):
            val = self.interpreter.variables[name]
            print("  {} = {}".format(
                _cyan(name), _format_value(val, 80)))

    def _show_fns(self):
        """Display all defined functions."""
        user_fns = {}
        for name, fn in self.interpreter.functions.items():
            # Skip builtins (they're Python callables, not FunctionNode)
            if hasattr(fn, 'params'):
                user_fns[name] = fn
        if not user_fns:
            print(_dim("No user-defined functions."))
            return
        for name in sorted(user_fns.keys()):
            fn = user_fns[name]
            params = ", ".join(fn.params) if hasattr(fn, 'params') else "..."
            print("  {} fn {}({})".format(
                _dim("•"), _cyan(name), params))

    def _load_file(self, filename):
        """Load and execute a .srv file."""
        if not filename:
            print(_red("Usage: .load <filename>"))
            return
        if not os.path.exists(filename):
            print(_red("File not found: {}".format(filename)))
            return
        try:
            with open(filename, "r") as f:
                code = f.read()
            print(_dim("Loading {}...".format(filename)))
            self._execute(code)
            print(_dim("Loaded."))
        except Exception as e:
            print(_red("Error loading file: {}".format(e)))

    def _save_session(self, filename):
        """Save session history to a file."""
        if not filename:
            print(_red("Usage: .save <filename>"))
            return
        try:
            with open(filename, "w") as f:
                for line in self.history:
                    f.write(line + "\n")
            print(_dim("Session saved to {}".format(filename)))
        except Exception as e:
            print(_red("Error saving: {}".format(e)))

    def _show_ast(self, code):
        """Show the AST for a line of code."""
        if not code:
            print(_red("Usage: .ast <code>"))
            return
        try:
            tokens = list(tokenize(code))
            parser = Parser(tokens)
            nodes = parser.parse()
            for node in nodes:
                self._print_ast_node(node, indent=0)
        except Exception as e:
            print(_red("Parse error: {}".format(e)))

    def _print_ast_node(self, node, indent=0):
        """Pretty-print an AST node."""
        prefix = "  " * indent
        name = type(node).__name__
        # Show key attributes
        attrs = []
        for attr in ("name", "value", "operator", "params",
                      "expression", "condition"):
            if hasattr(node, attr):
                val = getattr(node, attr)
                if val is not None and not isinstance(val, list):
                    attrs.append("{}={}".format(attr, repr(val)))
        attr_str = " " + " ".join(attrs) if attrs else ""
        print("{}{}{}".format(prefix, _yellow(name), _dim(attr_str)))

        # Recurse into child nodes
        for attr in ("body", "elif_chains", "else_body", "handler",
                      "elements", "cases", "left", "right",
                      "expression", "condition", "operand",
                      "arguments", "start", "end"):
            child = getattr(node, attr, None)
            if child is None:
                continue
            if isinstance(child, list):
                for item in child:
                    if hasattr(item, '__class__') and \
                       item.__class__.__module__ == 'saurav':
                        self._print_ast_node(item, indent + 1)
            elif hasattr(child, '__class__') and \
                 hasattr(child, '__dict__'):
                self._print_ast_node(child, indent + 1)

    def _save_history(self):
        """Save readline history."""
        if self._readline:
            try:
                self._readline.write_history_file(self.history_file)
            except Exception:
                pass  # Silently fail on history write errors

# ── Entry point ───────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="sauravcode interactive REPL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               "  python sauravrepl.py             # Start REPL\n"
               "  python sauravrepl.py -e 'x = 5'  # Evaluate and exit\n"
               "  python sauravrepl.py --no-color   # No ANSI colors\n"
    )
    parser.add_argument("-e", "--eval", metavar="CODE",
                        help="Evaluate code and exit")
    parser.add_argument("--no-color", action="store_true",
                        help="Disable colored output")
    parser.add_argument("--history", action="store_true",
                        help="Show history file path and exit")

    args = parser.parse_args()

    if args.history:
        path = os.path.expanduser("~/.sauravcode_history")
        print(path)
        return

    repl = SauravRepl(use_color=not args.no_color)

    if args.eval:
        repl._execute(args.eval)
        return

    repl.run()


if __name__ == "__main__":
    main()
