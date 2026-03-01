"""Tests for enum type support in SauravCode."""
import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from saurav import tokenize, Parser, Interpreter


def run(code):
    """Helper to run SauravCode and capture output."""
    import io
    from contextlib import redirect_stdout
    tokens = tokenize(code)
    parser = Parser(tokens)
    ast = parser.parse()
    interp = Interpreter()
    buf = io.StringIO()
    with redirect_stdout(buf):
        for node in ast:
            interp.interpret(node)
    return buf.getvalue().strip()


class TestEnum:
    def test_basic_enum(self):
        code = "enum Color\n    RED\n    GREEN\n    BLUE\nprint Color.RED\nprint Color.GREEN\nprint Color.BLUE"
        assert run(code) == "0\n1\n2"

    def test_enum_assignment(self):
        code = "enum Color\n    RED\n    GREEN\n    BLUE\nx = Color.GREEN\nprint x"
        assert run(code) == "1"

    def test_enum_comparison(self):
        code = 'enum Color\n    RED\n    GREEN\n    BLUE\nx = Color.RED\nif x == Color.RED\n    print "yes"'
        assert run(code) == "yes"

    def test_enum_in_expression(self):
        code = "enum Dir\n    N\n    S\n    E\n    W\nprint Dir.E + 10"
        assert run(code) == "12"

    def test_unknown_enum_error(self):
        code = "print Foo.BAR"
        with pytest.raises(RuntimeError, match="Unknown enum 'Foo'"):
            run(code)

    def test_unknown_variant_error(self):
        code = "enum Color\n    RED\n    GREEN\nprint Color.BLUE"
        with pytest.raises(RuntimeError, match="has no variant 'BLUE'"):
            run(code)

    def test_multiple_enums(self):
        code = "enum A\n    X\n    Y\nenum B\n    P\n    Q\n    R\nprint A.Y\nprint B.R"
        assert run(code) == "1\n2"

    def test_enum_with_match(self):
        code = "enum Color\n    RED\n    GREEN\n    BLUE\nx = Color.GREEN\nmatch x\n    case 1\n        print \"green\"\n    case _\n        print \"other\""
        assert run(code) == "green"

    def test_single_variant_enum(self):
        code = "enum Solo\n    ONLY\nprint Solo.ONLY"
        assert run(code) == "0"
