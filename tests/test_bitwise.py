"""Tests for bitwise operation builtins."""
import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import saurav


def _run(code):
    """Parse and interpret sauravcode, return captured output."""
    import io, contextlib
    tokens = saurav.tokenize(code)
    parser = saurav.Parser(tokens)
    ast = parser.parse()
    interp = saurav.Interpreter()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        for node in ast:
            interp.interpret(node)
    return buf.getvalue().strip()


class TestBitwiseBuiltins:
    def test_bit_and(self):
        assert _run("print bit_and 12 10") == "8"

    def test_bit_or(self):
        assert _run("print bit_or 12 10") == "14"

    def test_bit_xor(self):
        assert _run("print bit_xor 12 10") == "6"

    def test_bit_not(self):
        assert _run("print bit_not 12") == "-13"

    def test_bit_lshift(self):
        assert _run("print bit_lshift 1 4") == "16"

    def test_bit_rshift(self):
        assert _run("print bit_rshift 16 2") == "4"

    def test_bit_and_zero(self):
        assert _run("print bit_and 255 0") == "0"

    def test_bit_or_zero(self):
        assert _run("print bit_or 0 0") == "0"

    def test_bit_xor_self(self):
        assert _run("print bit_xor 42 42") == "0"

    def test_bit_not_zero(self):
        assert _run("print bit_not 0") == "-1"

    def test_shift_bounds(self):
        with pytest.raises(RuntimeError, match="shift amount must be 0-64"):
            _run("print bit_lshift 1 65")

    def test_float_rejection(self):
        with pytest.raises(RuntimeError, match="expects integer arguments"):
            _run("print bit_and 3.5 2")
