"""Tests for matrix / 2D-array builtins."""
import pytest
import sys, os, io
from contextlib import redirect_stdout
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from saurav import Interpreter, Parser, tokenize, FunctionNode, FunctionCallNode


def run_code(code):
    tokens = list(tokenize(code))
    ast_nodes = Parser(tokens).parse()
    interp = Interpreter()
    buf = io.StringIO()
    with redirect_stdout(buf):
        for node in ast_nodes:
            if isinstance(node, FunctionNode):
                interp.interpret(node)
            elif isinstance(node, FunctionCallNode):
                interp.execute_function(node)
            else:
                interp.interpret(node)
    return buf.getvalue().strip()


def run_raising(code):
    tokens = list(tokenize(code))
    ast_nodes = Parser(tokens).parse()
    interp = Interpreter()
    for node in ast_nodes:
        if isinstance(node, FunctionNode):
            interp.interpret(node)
        elif isinstance(node, FunctionCallNode):
            interp.execute_function(node)
        else:
            interp.interpret(node)


class TestMatrixCreate:
    def test_basic(self):
        out = run_code('m = matrix_create (2) (3) (0)\nprint m')
        assert out == '[[0, 0, 0], [0, 0, 0]]'

    def test_fill_value(self):
        out = run_code('print matrix_create (2) (2) (7)')
        assert out == '[[7, 7], [7, 7]]'

    def test_default_fill(self):
        out = run_code('print matrix_create (1) (3)')
        assert out == '[[0, 0, 0]]'


class TestMatrixIdentity:
    def test_2x2(self):
        out = run_code('print matrix_identity 2')
        assert out == '[[1, 0], [0, 1]]'

    def test_1x1(self):
        out = run_code('print matrix_identity 1')
        assert out == '[[1]]'


class TestMatrixTranspose:
    def test_square(self):
        out = run_code('print matrix_transpose [[1, 2], [3, 4]]')
        assert out == '[[1, 3], [2, 4]]'

    def test_rectangular(self):
        out = run_code('print matrix_transpose [[1, 2, 3], [4, 5, 6]]')
        assert out == '[[1, 4], [2, 5], [3, 6]]'


class TestMatrixAdd:
    def test_basic(self):
        out = run_code('print matrix_add ([[1, 2], [3, 4]]) ([[10, 20], [30, 40]])')
        assert out == '[[11, 22], [33, 44]]'


class TestMatrixMultiply:
    def test_2x2(self):
        out = run_code('print matrix_multiply ([[1, 2], [3, 4]]) ([[5, 6], [7, 8]])')
        assert out == '[[19, 22], [43, 50]]'

    def test_identity(self):
        out = run_code('a = [[1, 2], [3, 4]]\nid2 = matrix_identity 2\nprint matrix_multiply (a) (id2)')
        assert out == '[[1, 2], [3, 4]]'


class TestMatrixScalar:
    def test_basic(self):
        out = run_code('print matrix_scalar ([[1, 2], [3, 4]]) (3)')
        assert out == '[[3, 6], [9, 12]]'


class TestMatrixDeterminant:
    def test_2x2(self):
        out = run_code('print matrix_determinant [[1, 2], [3, 4]]')
        assert out == '-2'

    def test_3x3(self):
        out = run_code('print matrix_determinant [[1, 2, 3], [0, 1, 4], [5, 6, 0]]')
        assert out == '1'

    def test_1x1(self):
        out = run_code('print matrix_determinant [[42]]')
        assert out == '42'


class TestMatrixDimensions:
    def test_rows(self):
        out = run_code('print matrix_rows [[1, 2, 3], [4, 5, 6]]')
        assert out == '2'

    def test_cols(self):
        out = run_code('print matrix_cols [[1, 2, 3], [4, 5, 6]]')
        assert out == '3'


class TestMatrixGetSet:
    def test_get(self):
        out = run_code('print matrix_get ([[10, 20], [30, 40]]) (1) (0)')
        assert out == '30'

    def test_set_immutable(self):
        out = run_code('a = [[1, 2], [3, 4]]\nb = matrix_set (a) (0) (0) (99)\nprint a\nprint b')
        lines = out.split('\n')
        assert lines[0] == '[[1, 2], [3, 4]]'
        assert lines[1] == '[[99, 2], [3, 4]]'


class TestMatrixErrors:
    def test_add_mismatch(self):
        with pytest.raises(RuntimeError, match="dimension mismatch"):
            run_raising('matrix_add ([[1, 2]]) ([[1], [2]])')

    def test_multiply_mismatch(self):
        with pytest.raises(RuntimeError, match="inner dimensions"):
            run_raising('matrix_multiply ([[1, 2]]) ([[1, 2]])')

    def test_determinant_non_square(self):
        with pytest.raises(RuntimeError, match="square"):
            run_raising('m = [[1, 2, 3], [4, 5, 6]]\nmatrix_determinant m')

    def test_get_out_of_bounds(self):
        with pytest.raises(RuntimeError, match="out of bounds"):
            run_raising('matrix_get ([[1]]) (5) (0)')
