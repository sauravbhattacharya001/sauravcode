"""Tests for denial-of-service prevention guards."""
import pytest
from saurav import Interpreter, tokenize, Parser, MAX_ALLOC_SIZE, MAX_EXPONENT


def run(code):
    tokens = list(tokenize(code))
    parser = Parser(tokens)
    ast_nodes = parser.parse()
    interp = Interpreter()
    result = None
    for node in ast_nodes:
        result = interp.interpret(node)
    return result


class TestStringRepetitionGuard:
    def test_small_repeat_works(self):
        """string * number should work for small values."""
        run('x = "ab" * 5')

    def test_huge_repeat_blocked(self):
        with pytest.raises(RuntimeError, match="String repetition"):
            run(f'x = "A" * {MAX_ALLOC_SIZE + 1}')

    def test_reverse_operand_order(self):
        """number * string should also be guarded."""
        run('x = 3 * "ab"')

    def test_zero_repeat_allowed(self):
        run('x = "hello" * 0')

    def test_negative_repeat_allowed(self):
        run('n = 0 - 1\nx = "hello" * n')


class TestListRepetitionGuard:
    def test_small_list_repeat_works(self):
        run('x = [1, 2, 3] * 3')

    def test_huge_list_repeat_blocked(self):
        with pytest.raises(RuntimeError, match="List repetition"):
            run(f'x = [1] * {MAX_ALLOC_SIZE + 1}')


class TestRangeGuard:
    def test_normal_range_works(self):
        run('x = range 10')

    def test_huge_range_blocked(self):
        with pytest.raises(RuntimeError, match="range would create"):
            run(f'x = range {MAX_ALLOC_SIZE + 1}')

    def test_range_with_step(self):
        run('x = range 0 100 2')

    def test_range_zero_step_blocked(self):
        with pytest.raises(RuntimeError, match="step cannot be zero"):
            run('x = range 0 10 0')

    def test_range_two_args(self):
        run('x = range 5 15')

    def test_huge_range_two_args_blocked(self):
        with pytest.raises(RuntimeError, match="range would create"):
            run(f'x = range 0 {MAX_ALLOC_SIZE + 1}')


class TestPowerGuard:
    def test_small_power_works(self):
        run('x = power 2 10')

    def test_huge_exponent_blocked(self):
        with pytest.raises(RuntimeError, match="Exponent.*exceeds maximum"):
            run(f'x = power 2 {MAX_EXPONENT + 1}')

    def test_negative_huge_exponent_blocked(self):
        with pytest.raises(RuntimeError, match="Exponent.*exceeds maximum"):
            run(f'x = power 2 (0 - {MAX_EXPONENT + 1})')

    def test_boundary_exponent(self):
        """Exponent exactly at MAX_EXPONENT should be allowed (may overflow to inf)."""
        run(f'x = power 1.001 {MAX_EXPONENT}')


class TestExistingLimitsStillWork:
    def test_recursion_depth_limit(self):
        code = "function recurse n\n    recurse (n + 1)\nrecurse 0"
        with pytest.raises((RuntimeError, RecursionError)):
            run(code)

    def test_while_loop_works(self):
        """Small while loop should work fine."""
        code = "x = 0\nwhile x < 100\n    x = x + 1"
        run(code)


class TestGuardConstants:
    def test_max_alloc_size_positive(self):
        assert MAX_ALLOC_SIZE > 0

    def test_max_exponent_positive(self):
        assert MAX_EXPONENT > 0

    def test_max_alloc_size_reasonable(self):
        """Should be large enough for normal use but not unlimited."""
        assert 1_000_000 <= MAX_ALLOC_SIZE <= 100_000_000

    def test_max_exponent_reasonable(self):
        assert 1_000 <= MAX_EXPONENT <= 1_000_000
