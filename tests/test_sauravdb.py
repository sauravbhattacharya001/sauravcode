"""Tests for sauravdb — the interactive debugger for sauravcode.

Tests cover the non-interactive components: LineTrackingParser, _format_value,
_node_line, SauravDebugger state management, and DebugInterpreter hooks.
"""

import os
import sys
import pytest

# Ensure sauravcode root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from saurav import tokenize, ASTNode, FunctionNode
from sauravdb import (
    LineTrackingParser, _format_value, _node_line, SauravDebugger,
    DebugInterpreter, DebuggerQuit, DebuggerRestart
)


# ── _format_value tests ─────────────────────────────────────

class TestFormatValue:
    def test_integer_float(self):
        """Floats that are whole numbers display as integers."""
        assert _format_value(5.0) == "5"

    def test_non_integer_float(self):
        assert _format_value(3.14) == "3.14"

    def test_bool_true(self):
        assert _format_value(True) == "true"

    def test_bool_false(self):
        assert _format_value(False) == "false"

    def test_string(self):
        result = _format_value("hello")
        assert result == "'hello'"

    def test_list(self):
        result = _format_value([1.0, 2.0])
        assert "[" in result

    def test_dict(self):
        result = _format_value({"a": 1})
        assert "a" in result

    def test_truncation(self):
        long_str = "x" * 200
        result = _format_value(long_str, max_len=50)
        assert len(result) <= 50
        assert result.endswith("...")

    def test_none(self):
        assert _format_value(None) == "None"

    def test_zero_float(self):
        assert _format_value(0.0) == "0"

    def test_negative_float(self):
        assert _format_value(-3.0) == "-3"


# ── _node_line tests ────────────────────────────────────────

class TestNodeLine:
    def test_with_line_num(self):
        node = ASTNode()
        node.line_num = 42
        assert _node_line(node) == 42

    def test_without_line_num(self):
        node = ASTNode()
        node.line_num = None
        assert _node_line(node) is None

    def test_missing_attribute(self):
        """Objects without line_num return None."""
        class Bare:
            pass
        assert _node_line(Bare()) is None


# ── LineTrackingParser tests ─────────────────────────────────

class TestLineTrackingParser:
    def test_assigns_line_numbers(self):
        """Parser tags AST nodes with source line numbers."""
        source = 'x = 10\nprint x\n'
        tokens = list(tokenize(source))
        parser = LineTrackingParser(tokens)
        nodes = parser.parse()
        lines = [n.line_num for n in nodes if n.line_num is not None]
        assert len(lines) > 0

    def test_empty_source(self):
        tokens = list(tokenize(""))
        parser = LineTrackingParser(tokens)
        nodes = parser.parse()
        assert nodes == []

    def test_function_def(self):
        source = 'function add x y\n    return x + y\n'
        tokens = list(tokenize(source))
        parser = LineTrackingParser(tokens)
        nodes = parser.parse()
        assert len(nodes) >= 1

    def test_multiline_program(self):
        source = 'x = 1\ny = 2\nz = x + y\nprint z\n'
        tokens = list(tokenize(source))
        parser = LineTrackingParser(tokens)
        nodes = parser.parse()
        assert len(nodes) == 4


# ── SauravDebugger state tests ──────────────────────────────

class TestSauravDebuggerState:
    @pytest.fixture
    def debugger(self, tmp_path):
        """Create a debugger instance with a simple program."""
        src = 'x = 1\ny = 2\nprint x + y\n'
        f = tmp_path / "test.srv"
        f.write_text(src)
        tokens = list(tokenize(src))
        parser = LineTrackingParser(tokens)
        nodes = parser.parse()
        return SauravDebugger(str(f), src, nodes)

    def test_initial_state(self, debugger):
        assert debugger.stepping is True
        assert debugger.current_line == 1
        assert debugger.statements_executed == 0
        assert len(debugger.breakpoints) == 0
        assert len(debugger.call_stack) == 0

    def test_breakpoint_management(self, debugger):
        debugger.breakpoints.add(2)
        assert 2 in debugger.breakpoints
        debugger.breakpoints.discard(2)
        assert 2 not in debugger.breakpoints

    def test_source_lines(self, debugger):
        assert debugger.source_lines[0] == "x = 1"
        assert len(debugger.source_lines) == 3

    def test_interpreter_created(self, debugger):
        assert debugger.interpreter is not None
        assert isinstance(debugger.interpreter, DebugInterpreter)

    def test_multiple_breakpoints(self, debugger):
        debugger.breakpoints.add(1)
        debugger.breakpoints.add(3)
        assert len(debugger.breakpoints) == 2
        debugger.breakpoints.clear()
        assert len(debugger.breakpoints) == 0


# ── DebugInterpreter hooks ──────────────────────────────────

class TestDebugInterpreter:
    def test_on_statement_increments_count(self, tmp_path):
        """on_statement is called and increments statement counter."""
        src = 'x = 42\n'
        f = tmp_path / "test.srv"
        f.write_text(src)
        tokens = list(tokenize(src))
        parser = LineTrackingParser(tokens)
        nodes = parser.parse()
        dbg = SauravDebugger(str(f), src, nodes)
        dbg.stepping = False

        node = nodes[0]
        dbg.on_statement(node)
        assert dbg.statements_executed == 1

    def test_variables_accessible(self, tmp_path):
        """After interpreting, variables are in the interpreter's scope."""
        src = 'x = 42\n'
        f = tmp_path / "test.srv"
        f.write_text(src)
        tokens = list(tokenize(src))
        parser = LineTrackingParser(tokens)
        nodes = parser.parse()
        dbg = SauravDebugger(str(f), src, nodes)
        dbg.stepping = False

        dbg.interpreter.interpret(nodes[0])
        assert dbg.interpreter.variables.get("x") == 42.0

    def test_on_statement_updates_line(self, tmp_path):
        """on_statement updates current_line from node."""
        src = 'x = 1\ny = 2\n'
        f = tmp_path / "test.srv"
        f.write_text(src)
        tokens = list(tokenize(src))
        parser = LineTrackingParser(tokens)
        nodes = parser.parse()
        dbg = SauravDebugger(str(f), src, nodes)
        dbg.stepping = False

        for node in nodes:
            dbg.on_statement(node)

        assert dbg.statements_executed == 2
        # current_line should have been updated
        assert dbg.current_line >= 1


# ── Exception classes ───────────────────────────────────────

class TestExceptions:
    def test_debugger_quit_is_exception(self):
        with pytest.raises(DebuggerQuit):
            raise DebuggerQuit()

    def test_debugger_restart_is_exception(self):
        with pytest.raises(DebuggerRestart):
            raise DebuggerRestart()

    def test_quit_inherits_from_exception(self):
        assert issubclass(DebuggerQuit, Exception)

    def test_restart_inherits_from_exception(self):
        assert issubclass(DebuggerRestart, Exception)
