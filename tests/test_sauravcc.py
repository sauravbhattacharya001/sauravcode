"""Tests for sauravcc — the Sauravcode-to-C compiler."""

import os
import sys
import tempfile
import subprocess

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sauravcc import tokenize, Parser, CCodeGenerator


# ── Tokenizer tests ──────────────────────────────────────────

class TestTokenizer:
    def test_simple_assignment(self):
        tokens = tokenize("x = 42\n")
        types = [t[0] for t in tokens if t[0] not in ("NEWLINE", "INDENT", "DEDENT")]
        assert types == ["IDENT", "ASSIGN", "NUMBER"]

    def test_string_literal(self):
        tokens = tokenize('name = "hello"\n')
        vals = [(t[0], t[1]) for t in tokens if t[0] not in ("NEWLINE", "INDENT", "DEDENT")]
        assert ("STRING", '"hello"') in vals

    def test_fstring_token(self):
        tokens = tokenize('x = f"val={y}"\n')
        types = [t[0] for t in tokens if t[0] not in ("NEWLINE", "INDENT", "DEDENT")]
        assert "FSTRING" in types

    def test_comparison_operators(self):
        tokens = tokenize("a == b != c <= d >= e < f > g\n")
        types = [t[0] for t in tokens if t[0] not in ("NEWLINE", "INDENT", "DEDENT", "IDENT")]
        assert types == ["EQ", "NEQ", "LTE", "GTE", "LT", "GT"]

    def test_keywords(self):
        tokens = tokenize("if true\n    print 1\n")
        types = [t[0] for t in tokens if t[0] not in ("NEWLINE", "INDENT", "DEDENT")]
        assert types[0:2] == ["KEYWORD", "KEYWORD"]

    def test_indent_dedent(self):
        code = "if true\n    x = 1\ny = 2\n"
        tokens = tokenize(code)
        types = [t[0] for t in tokens]
        assert "INDENT" in types
        assert "DEDENT" in types

    def test_comment_ignored(self):
        tokens = tokenize("# this is a comment\nx = 1\n")
        types = [t[0] for t in tokens if t[0] not in ("NEWLINE", "INDENT", "DEDENT")]
        assert types == ["IDENT", "ASSIGN", "NUMBER"]

    def test_modulo_operator(self):
        tokens = tokenize("a % b\n")
        ops = [(t[0], t[1]) for t in tokens if t[0] == "OP"]
        assert ("OP", "%") in ops

    def test_unexpected_char_raises(self):
        with pytest.raises(RuntimeError, match="Unexpected character"):
            tokenize("x = $\n")

    def test_list_brackets(self):
        tokens = tokenize("xs = [1, 2, 3]\n")
        types = [t[0] for t in tokens if t[0] not in ("NEWLINE", "INDENT", "DEDENT")]
        assert "LBRACKET" in types
        assert "RBRACKET" in types

    def test_empty_input(self):
        tokens = tokenize("")
        assert isinstance(tokens, list)

    def test_multiline_indentation(self):
        code = "function foo\n    x = 1\n    y = 2\n"
        tokens = tokenize(code)
        indent_count = sum(1 for t in tokens if t[0] == "INDENT")
        dedent_count = sum(1 for t in tokens if t[0] == "DEDENT")
        assert indent_count == dedent_count

    def test_dot_operator(self):
        tokens = tokenize("self.x = 1\n")
        types = [t[0] for t in tokens if t[0] not in ("NEWLINE", "INDENT", "DEDENT")]
        assert "DOT" in types

    def test_multiple_string_escapes(self):
        tokens = tokenize(r'"hello \"world\""' + "\n")
        strings = [t for t in tokens if t[0] == "STRING"]
        assert len(strings) == 1


# ── Parser tests ─────────────────────────────────────────────

class TestParser:
    def _parse(self, code):
        tokens = tokenize(code + "\n")
        parser = Parser(tokens)
        return parser.parse()

    def test_parse_variable_assignment(self):
        ast = self._parse("x = 10")
        assert len(ast.statements) >= 1

    def test_parse_function_def(self):
        # sauravcode functions: "function name\n    body"
        ast = self._parse("function add\n    return 1")
        assert len(ast.statements) >= 1

    def test_parse_if_else(self):
        ast = self._parse("if x == 1\n    print 1\nelse\n    print 2")
        assert len(ast.statements) >= 1

    def test_parse_while_loop(self):
        ast = self._parse("while x > 0\n    x = x - 1")
        assert len(ast.statements) >= 1

    def test_parse_for_loop(self):
        ast = self._parse("for i in range(10)\n    print i")
        assert len(ast.statements) >= 1

    def test_parse_print_string(self):
        ast = self._parse('print "hello world"')
        assert len(ast.statements) >= 1

    def test_parse_try_catch(self):
        ast = self._parse("try\n    x = 1\ncatch e\n    print e")
        assert len(ast.statements) >= 1

    def test_parse_boolean_literals(self):
        ast = self._parse("x = true\ny = false")
        assert len(ast.statements) >= 2

    def test_parse_list_literal(self):
        ast = self._parse("xs = [1, 2, 3]")
        assert len(ast.statements) >= 1

    def test_parse_nested_if(self):
        code = "if true\n    if false\n        print 1\n    print 2"
        ast = self._parse(code)
        assert len(ast.statements) >= 1

    def test_parse_assert(self):
        ast = self._parse("assert 1 == 1")
        assert len(ast.statements) >= 1

    def test_parse_break_continue(self):
        code = "while true\n    break"
        ast = self._parse(code)
        assert len(ast.statements) >= 1


# ── Code Generator tests ────────────────────────────────────

class TestCodeGenerator:
    def _generate(self, code):
        tokens = tokenize(code + "\n")
        parser = Parser(tokens)
        ast = parser.parse()
        gen = CCodeGenerator()
        return gen.compile(ast)

    def test_generates_c_code(self):
        c_code = self._generate("print 42")
        assert "#include" in c_code
        assert "printf" in c_code

    def test_variable_in_c(self):
        c_code = self._generate("x = 10\nprint x")
        assert "10" in c_code

    def test_arithmetic_in_c(self):
        c_code = self._generate("x = 3 + 4")
        assert "3" in c_code
        assert "4" in c_code

    def test_string_in_c(self):
        c_code = self._generate('print "hello"')
        assert "hello" in c_code

    def test_if_generates_if(self):
        c_code = self._generate("if true\n    print 1")
        assert "if" in c_code

    def test_while_generates_while(self):
        c_code = self._generate("x = 5\nwhile x > 0\n    x = x - 1")
        assert "while" in c_code

    def test_function_generates_c_function(self):
        c_code = self._generate("function greet\n    print 42")
        assert "greet" in c_code

    def test_for_loop(self):
        c_code = self._generate("for i in range(5)\n    print i")
        assert "for" in c_code or "while" in c_code

    def test_boolean_true(self):
        c_code = self._generate("x = true")
        assert "1" in c_code  # true -> 1 in C

    def test_boolean_false(self):
        c_code = self._generate("x = false")
        assert "0" in c_code

    def test_comparison_operators(self):
        c_code = self._generate("if x == 1\n    print 1")
        assert "==" in c_code

    def test_logical_and(self):
        c_code = self._generate("if true and false\n    print 1")
        assert "&&" in c_code

    def test_logical_or(self):
        c_code = self._generate("if true or false\n    print 1")
        assert "||" in c_code
