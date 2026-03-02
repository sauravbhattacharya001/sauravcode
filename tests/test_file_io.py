"""
Tests for file I/O built-in functions in sauravcode.

Covers: read_file, write_file, append_file, file_exists, read_lines
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


def run_code(code: str) -> str:
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


@pytest.fixture
def tmp_file(tmp_path):
    """Return a temporary file path for testing."""
    return str(tmp_path / "test_file.txt").replace("\\", "/")


@pytest.fixture
def tmp_dir(tmp_path):
    """Return the temp directory path."""
    return str(tmp_path).replace("\\", "/")


# ── write_file ────────────────────────────────────────────

class TestWriteFile:
    def test_write_creates_file(self, tmp_file):
        run_code(f'write_file "{tmp_file}" "hello"')
        assert os.path.isfile(tmp_file)

    def test_write_correct_content(self, tmp_file):
        run_code(f'write_file "{tmp_file}" "hello world"')
        with open(tmp_file) as f:
            assert f.read() == "hello world"

    def test_write_overwrites_existing(self, tmp_file):
        run_code(f'write_file "{tmp_file}" "first"')
        run_code(f'write_file "{tmp_file}" "second"')
        with open(tmp_file) as f:
            assert f.read() == "second"

    def test_write_empty_string(self, tmp_file):
        run_code(f'write_file "{tmp_file}" "content"')
        run_code(f'write_file "{tmp_file}" ""')
        with open(tmp_file) as f:
            assert f.read() == ""

    def test_write_special_chars(self, tmp_file):
        run_code(f'write_file "{tmp_file}" "hello world 123!@#"')
        with open(tmp_file) as f:
            content = f.read()
        assert content == "hello world 123!@#"

    def test_write_returns_truthy(self, tmp_file):
        output = run_code(f'''
result = write_file "{tmp_file}" "data"
print result
''')
        assert "true" in output.lower() or "True" in output


# ── read_file ─────────────────────────────────────────────

class TestReadFile:
    def test_read_returns_content(self, tmp_file):
        with open(tmp_file, 'w') as f:
            f.write("test content")
        output = run_code(f'''
content = read_file "{tmp_file}"
print content
''')
        assert "test content" in output

    def test_read_empty_file(self, tmp_file):
        with open(tmp_file, 'w') as f:
            f.write("")
        output = run_code(f'''
content = read_file "{tmp_file}"
print len content
''')
        assert "0" in output

    def test_read_nonexistent_raises(self, tmp_dir):
        bad_path = tmp_dir + "/nonexistent.txt"
        with pytest.raises(RuntimeError, match="file not found"):
            run_code(f'read_file "{bad_path}"')

    def test_read_roundtrip(self, tmp_file):
        run_code(f'write_file "{tmp_file}" "roundtrip data"')
        output = run_code(f'''
content = read_file "{tmp_file}"
print content
''')
        assert "roundtrip data" in output

    def test_read_multiline_content(self, tmp_file):
        with open(tmp_file, 'w') as f:
            f.write("line1\nline2\nline3")
        output = run_code(f'''
content = read_file "{tmp_file}"
print content
''')
        assert "line1" in output
        assert "line3" in output


# ── append_file ───────────────────────────────────────────

class TestAppendFile:
    def test_append_to_existing(self, tmp_file):
        with open(tmp_file, 'w') as f:
            f.write("start")
        run_code(f'append_file "{tmp_file}" " end"')
        with open(tmp_file) as f:
            assert f.read() == "start end"

    def test_append_creates_file(self, tmp_dir):
        new_file = tmp_dir + "/new_append.txt"
        run_code(f'append_file "{new_file}" "created"')
        assert os.path.isfile(new_file)
        with open(new_file) as f:
            assert f.read() == "created"

    def test_append_multiple_times(self, tmp_file):
        run_code(f'write_file "{tmp_file}" "a"')
        run_code(f'append_file "{tmp_file}" "b"')
        run_code(f'append_file "{tmp_file}" "c"')
        with open(tmp_file) as f:
            assert f.read() == "abc"

    def test_append_returns_truthy(self, tmp_file):
        output = run_code(f'''
result = append_file "{tmp_file}" "data"
print result
''')
        assert "true" in output.lower() or "True" in output

    def test_append_in_loop(self, tmp_file):
        run_code(f'''
write_file "{tmp_file}" ""
for i 0 5
    append_file "{tmp_file}" "x"
''')
        with open(tmp_file) as f:
            assert f.read() == "xxxxx"


# ── file_exists ───────────────────────────────────────────

class TestFileExists:
    def test_exists_true(self, tmp_file):
        with open(tmp_file, 'w') as f:
            f.write("content")
        output = run_code(f'''
result = file_exists "{tmp_file}"
print result
''')
        assert "true" in output.lower()

    def test_exists_false(self, tmp_dir):
        bad_path = tmp_dir + "/nope.txt"
        output = run_code(f'''
result = file_exists "{bad_path}"
print result
''')
        assert "false" in output.lower()

    def test_exists_after_write(self, tmp_dir):
        new_file = tmp_dir + "/will_exist.txt"
        output = run_code(f'''
before = file_exists "{new_file}"
print before
write_file "{new_file}" "now"
after = file_exists "{new_file}"
print after
''')
        lines = output.strip().split('\n')
        assert "false" in lines[0].lower()
        assert "true" in lines[1].lower()


# ── read_lines ────────────────────────────────────────────

class TestReadLines:
    def test_read_lines_count(self, tmp_file):
        with open(tmp_file, 'w') as f:
            f.write("alpha\nbeta\ngamma")
        output = run_code(f'''
lines = read_lines "{tmp_file}"
print len lines
''')
        assert "3" in output

    def test_read_lines_single_line(self, tmp_file):
        with open(tmp_file, 'w') as f:
            f.write("only one line")
        output = run_code(f'''
lines = read_lines "{tmp_file}"
print len lines
''')
        assert "1" in output

    def test_read_lines_iteration(self, tmp_file):
        with open(tmp_file, 'w') as f:
            f.write("x\ny\nz")
        output = run_code(f'''
lines = read_lines "{tmp_file}"
for line in lines
    print line
''')
        lines = output.strip().split('\n')
        assert [l.strip() for l in lines] == ["x", "y", "z"]

    def test_read_lines_nonexistent_raises(self, tmp_dir):
        bad_path = tmp_dir + "/nope.txt"
        with pytest.raises(RuntimeError, match="file not found"):
            run_code(f'read_lines "{bad_path}"')

    def test_read_lines_five_lines(self, tmp_file):
        with open(tmp_file, 'w') as f:
            f.write("a\nb\nc\nd\ne")
        output = run_code(f'''
lines = read_lines "{tmp_file}"
print len lines
''')
        assert "5" in output

    def test_read_lines_content_matches(self, tmp_file):
        with open(tmp_file, 'w') as f:
            f.write("hello\nworld")
        output = run_code(f'''
lines = read_lines "{tmp_file}"
print lines
''')
        assert "hello" in output
        assert "world" in output


# ── Integration ───────────────────────────────────────────

class TestFileIOIntegration:
    def test_conditional_file_ops(self, tmp_dir):
        """Use file_exists in conditional logic."""
        path = tmp_dir + "/conditional.txt"
        output = run_code(f'''
if file_exists "{path}"
    print "exists"
else
    print "missing"
    write_file "{path}" "created"

if file_exists "{path}"
    print "now exists"
''')
        assert "missing" in output
        assert "now exists" in output

    def test_read_modify_write(self, tmp_file):
        """Read a file, modify content, write back."""
        with open(tmp_file, 'w') as f:
            f.write("hello")
        run_code(f'''
content = read_file "{tmp_file}"
new_content = content + " world"
write_file "{tmp_file}" new_content
''')
        with open(tmp_file) as f:
            assert f.read() == "hello world"

    def test_line_processing(self, tmp_file):
        """Read lines and process each one."""
        with open(tmp_file, 'w') as f:
            f.write("10\n20\n30")
        output = run_code(f'''
lines = read_lines "{tmp_file}"
total = 0
for line in lines
    total = total + to_number line
print total
''')
        assert "60" in output

    def test_error_handling(self, tmp_dir):
        """try/catch around file errors."""
        bad_path = tmp_dir + "/nope.txt"
        output = run_code(f'''
try
    read_file "{bad_path}"
catch e
    print "caught error"
''')
        assert "caught error" in output

    def test_write_and_count_lines(self, tmp_file):
        """Write multi-line content via append, count lines."""
        run_code(f'''
write_file "{tmp_file}" "line1"
append_file "{tmp_file}" "
line2"
append_file "{tmp_file}" "
line3"
lines = read_lines "{tmp_file}"
print len lines
''')
        # The newlines are actual newlines in the sauravcode source
        # (not \n escape sequences)
