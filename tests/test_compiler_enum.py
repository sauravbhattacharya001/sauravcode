"""Tests for enum support in the compiler (sauravcc.py)."""
import subprocess
import sys
import os
import pytest

COMPILER = os.path.join(os.path.dirname(__file__), '..', 'sauravcc.py')
INTERPRETER = os.path.join(os.path.dirname(__file__), '..', 'saurav.py')


def run_emit_c(code):
    """Run compiler with --emit-c and return the generated C code."""
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.srv', delete=False) as f:
        f.write(code)
        f.flush()
        result = subprocess.run(
            [sys.executable, COMPILER, f.name, '--emit-c'],
            capture_output=True, text=True
        )
    os.unlink(f.name)
    if result.returncode != 0:
        raise RuntimeError(f"Compiler failed: {result.stderr}")
    return result.stdout


def run_interpreter(code):
    """Run interpreter and return output."""
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.srv', delete=False) as f:
        f.write(code)
        f.flush()
        result = subprocess.run(
            [sys.executable, INTERPRETER, f.name],
            capture_output=True, text=True
        )
    os.unlink(f.name)
    return result.stdout.strip()


class TestEnumCompiler:
    """Test enum compilation support."""

    def test_basic_enum_emits_c(self):
        """Enum variants should compile to integer constants."""
        code = "enum Color\n    RED\n    GREEN\n    BLUE\n\nprint Color.RED\nprint Color.GREEN\nprint Color.BLUE\n"
        c_code = run_emit_c(code)
        # Should contain the integer constants 0, 1, 2
        assert '(double)(0)' in c_code
        assert '(double)(1)' in c_code
        assert '(double)(2)' in c_code

    def test_enum_assignment(self):
        """Enum values should be assignable to variables."""
        code = "enum Direction\n    UP\n    DOWN\n    LEFT\n    RIGHT\n\nx = Direction.RIGHT\nprint x\n"
        c_code = run_emit_c(code)
        assert '3' in c_code  # RIGHT is index 3

    def test_enum_comparison(self):
        """Enum values should be comparable."""
        code = "enum Status\n    OK\n    ERROR\n\nx = Status.OK\nif x == Status.OK\n    print \"is OK\"\n"
        c_code = run_emit_c(code)
        assert '"is OK"' in c_code

    def test_enum_parity_with_interpreter(self):
        """Compiler and interpreter should produce the same enum values."""
        code = "enum Animal\n    CAT\n    DOG\n    BIRD\n\nprint Animal.CAT\nprint Animal.DOG\nprint Animal.BIRD\n"
        interp_output = run_interpreter(code)
        assert interp_output == "0\n1\n2"  # Should match

    def test_multiple_enums(self):
        """Multiple enum definitions should coexist."""
        code = "enum Color\n    RED\n    GREEN\n\nenum Size\n    SMALL\n    LARGE\n\nprint Color.GREEN\nprint Size.LARGE\n"
        c_code = run_emit_c(code)
        # Color.GREEN=1, Size.LARGE=1
        assert c_code.count('(double)(1)') >= 2

    def test_enum_in_arithmetic(self):
        """Enum values (integers) should work in arithmetic."""
        code = "enum Rank\n    BRONZE\n    SILVER\n    GOLD\n\nx = Rank.GOLD + 10\nprint x\n"
        c_code = run_emit_c(code)
        assert '2' in c_code  # GOLD = 2
