"""
Tests for file I/O path traversal protection.

Verifies that when the interpreter is running from a file (_source_dir set),
file I/O builtins (read_file, write_file, append_file, file_exists,
read_lines) cannot access files outside the source directory tree.
"""

import pytest
import sys
import os
import io
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from saurav import (
    tokenize,
    Parser,
    Interpreter,
    FunctionNode,
    FunctionCallNode,
)


def run_code_sandboxed(code, source_dir):
    """Run sauravcode with _source_dir set (simulating file execution)."""
    tokens = list(tokenize(code))
    parser = Parser(tokens)
    ast_nodes = parser.parse()
    interpreter = Interpreter()
    interpreter._source_dir = source_dir

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


class TestPathTraversalBlocked:
    """When _source_dir is set, file ops must stay within that directory."""

    def test_read_file_parent_traversal(self, tmp_path):
        """../../etc/passwd style traversal should be blocked."""
        project = tmp_path / "project"
        project.mkdir()
        # Create a file outside the project
        secret = tmp_path / "secret.txt"
        secret.write_text("sensitive data")

        with pytest.raises(RuntimeError, match="path traversal"):
            run_code_sandboxed(
                'read_file "../secret.txt"',
                str(project)
            )

    def test_write_file_parent_traversal(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()

        with pytest.raises(RuntimeError, match="path traversal"):
            run_code_sandboxed(
                'write_file "../evil.txt" "pwned"',
                str(project)
            )

    def test_append_file_parent_traversal(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()

        with pytest.raises(RuntimeError, match="path traversal"):
            run_code_sandboxed(
                'append_file "../evil.txt" "extra"',
                str(project)
            )

    def test_file_exists_parent_traversal(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()

        with pytest.raises(RuntimeError, match="path traversal"):
            run_code_sandboxed(
                'file_exists "../secret.txt"',
                str(project)
            )

    def test_read_lines_parent_traversal(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()

        with pytest.raises(RuntimeError, match="path traversal"):
            run_code_sandboxed(
                'read_lines "../secret.txt"',
                str(project)
            )

    def test_absolute_path_outside_project(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        secret = tmp_path / "secret.txt"
        secret.write_text("nope")

        abs_path = str(secret).replace("\\", "/")
        with pytest.raises(RuntimeError, match="path traversal"):
            run_code_sandboxed(
                f'read_file "{abs_path}"',
                str(project)
            )


class TestPathTraversalAllowed:
    """File ops within the source directory should still work."""

    def test_read_relative_within_project(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        (project / "data.txt").write_text("hello")

        output = run_code_sandboxed(
            'print (read_file "data.txt")',
            str(project)
        )
        assert output.strip() == "hello"

    def test_write_within_project(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()

        run_code_sandboxed(
            'write_file "output.txt" "written"',
            str(project)
        )
        assert (project / "output.txt").read_text() == "written"

    def test_subdirectory_within_project(self, tmp_path):
        project = tmp_path / "project"
        sub = project / "data"
        sub.mkdir(parents=True)
        (sub / "file.txt").write_text("in subdir")

        output = run_code_sandboxed(
            'print (read_file "data/file.txt")',
            str(project)
        )
        assert output.strip() == "in subdir"

    def test_file_exists_within_project(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        (project / "exists.txt").write_text("here")

        output = run_code_sandboxed(
            'print (file_exists "exists.txt")',
            str(project)
        )
        assert output.strip() == "true"

    def test_read_lines_within_project(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        (project / "lines.txt").write_text("a\nb\nc")

        output = run_code_sandboxed(
            'x = read_lines "lines.txt"\nprint (len x)',
            str(project)
        )
        assert output.strip() == "3"

    def test_append_within_project(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        (project / "log.txt").write_text("first\n")

        run_code_sandboxed(
            'append_file "log.txt" "second"',
            str(project)
        )
        assert (project / "log.txt").read_text() == "first\nsecond"


class TestNullByteInjection:
    """Null bytes in paths should always be blocked."""

    def test_read_file_null_byte(self):
        with pytest.raises(RuntimeError, match="null bytes"):
            interp = Interpreter()
            interp._builtin_read_file(["file\x00.txt"])

    def test_write_file_null_byte(self):
        with pytest.raises(RuntimeError, match="null bytes"):
            interp = Interpreter()
            interp._builtin_write_file(["file\x00.txt", "content"])

    def test_file_exists_null_byte(self):
        with pytest.raises(RuntimeError, match="null bytes"):
            interp = Interpreter()
            interp._builtin_file_exists(["file\x00.txt"])


class TestEmptyPath:
    """Empty/whitespace paths should be blocked."""

    def test_read_file_empty(self):
        with pytest.raises(RuntimeError, match="empty file path"):
            interp = Interpreter()
            interp._builtin_read_file([""])

    def test_write_file_whitespace(self):
        with pytest.raises(RuntimeError, match="empty file path"):
            interp = Interpreter()
            interp._builtin_write_file(["   ", "content"])


class TestInteractiveModeNoRestriction:
    """When _source_dir is None (REPL), file ops should work unrestricted."""

    def test_read_absolute_path_in_repl(self, tmp_path):
        target = tmp_path / "data.txt"
        target.write_text("repl data")
        abs_path = str(target).replace("\\", "/")

        # _source_dir is None by default in Interpreter()
        output = run_code_sandboxed(
            f'print (read_file "{abs_path}")',
            None  # triggers interactive mode — won't set _source_dir
        )
        assert output.strip() == "repl data"

    def test_symlink_traversal_blocked(self, tmp_path):
        """Symlinks pointing outside the sandbox must be rejected."""
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "secret.txt"
        secret.write_text("top secret")

        link = sandbox / "escape"
        try:
            link.symlink_to(outside)
        except OSError:
            pytest.skip("symlinks not supported on this platform")

        with pytest.raises(RuntimeError, match="path traversal"):
            run_code_sandboxed(
                'print (read_file "escape/secret.txt")',
                str(sandbox),
            )

    def test_write_absolute_path_in_repl(self, tmp_path):
        target = tmp_path / "output.txt"
        abs_path = str(target).replace("\\", "/")

        interp = Interpreter()
        # _source_dir is None
        interp._builtin_write_file([str(target), "repl write"])
        assert target.read_text() == "repl write"
