"""Tests for process_escapes() and escape-related string handling.

The process_escapes function translates backslash sequences in string
literals (\\n, \\t, \\r, \\\\, \\", \\0) and preserves unknown escapes
verbatim. These tests ensure correctness for all mapped escapes, unknown
escapes, edge cases, and integration with the interpreter.
"""

import os
import sys
import io
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from saurav import (
    process_escapes,
    tokenize,
    Parser,
    Interpreter,
    FunctionNode,
    FunctionCallNode,
)


def run(code):
    """Tokenize, parse, interpret sauravcode and capture stdout."""
    tokens = list(tokenize(code))
    parser = Parser(tokens)
    ast_nodes = parser.parse()
    interpreter = Interpreter()
    buf = io.StringIO()
    with redirect_stdout(buf):
        for node in ast_nodes:
            if isinstance(node, FunctionNode):
                interpreter.interpret(node)
            elif isinstance(node, FunctionCallNode):
                interpreter.execute_function(node)
            else:
                interpreter.interpret(node)
    return buf.getvalue()


# ── Unit tests for process_escapes ───────────────────────────────


class TestProcessEscapes:
    def test_newline(self):
        assert process_escapes(r"\n") == "\n"

    def test_tab(self):
        assert process_escapes(r"\t") == "\t"

    def test_carriage_return(self):
        assert process_escapes(r"\r") == "\r"

    def test_backslash(self):
        assert process_escapes("\\\\") == "\\"

    def test_escaped_quote(self):
        assert process_escapes('\\"') == '"'

    def test_null_char(self):
        assert process_escapes(r"\0") == "\0"

    def test_no_escapes(self):
        assert process_escapes("hello world") == "hello world"

    def test_empty_string(self):
        assert process_escapes("") == ""

    def test_unknown_escape_preserved(self):
        # Unknown escape like \d should keep both backslash and char
        assert process_escapes(r"\d") == "\\d"

    def test_unknown_escape_w(self):
        assert process_escapes(r"\w") == "\\w"

    def test_multiple_escapes(self):
        assert process_escapes(r"line1\nline2\ttab") == "line1\nline2\ttab"

    def test_mixed_known_and_unknown(self):
        # \n is known, \d is unknown
        result = process_escapes(r"\n\d")
        assert result == "\n\\d"

    def test_trailing_backslash(self):
        # A trailing single backslash with no following char
        assert process_escapes("abc\\") == "abc\\"

    def test_consecutive_backslashes(self):
        # Four backslashes -> two actual backslashes
        assert process_escapes("\\\\\\\\") == "\\\\"

    def test_escaped_quote_in_middle(self):
        assert process_escapes('say \\"hello\\"') == 'say "hello"'

    def test_all_mapped_escapes(self):
        input_str = r"\n\t\r\\\"\0"
        expected = "\n\t\r\\\"\0"
        assert process_escapes(input_str) == expected


# ── Integration tests: escapes through the interpreter ───────────


class TestEscapeIntegration:
    def test_print_newline_escape(self):
        output = run('print "hello\\nworld"\n')
        assert output == "hello\nworld\n"

    def test_print_tab_escape(self):
        output = run('print "col1\\tcol2"\n')
        assert output == "col1\tcol2\n"

    def test_print_escaped_backslash(self):
        output = run('print "path\\\\file"\n')
        assert output == "path\\file\n"

    def test_print_escaped_quote(self):
        output = run('print "say \\"hi\\""\n')
        assert output == 'say "hi"\n'

    def test_string_with_no_escapes(self):
        output = run('print "plain text"\n')
        assert output == "plain text\n"

    def test_string_length_with_escape(self):
        # \n should count as 1 character
        output = run('x = "a\\nb"\nprint len x\n')
        assert output.strip() == "3"
