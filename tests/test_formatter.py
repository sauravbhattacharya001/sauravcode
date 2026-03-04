"""Tests for sauravfmt — the sauravcode formatter."""

import os
import sys
import tempfile
import pytest

# Add parent dir to path so we can import sauravfmt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sauravfmt import (
    format_code,
    unified_diff,
    _detect_indent,
    _normalise_indent,
    _fix_operator_spacing,
    _collapse_blanks,
    _strip_trailing,
    _ensure_final_newline,
    _align_inline_comments,
    _split_trailing_comment,
    _find_srv_files,
)


# ---------------------------------------------------------------
# Indentation detection
# ---------------------------------------------------------------

class TestDetectIndent:
    def test_four_spaces(self):
        lines = ["function foo x", "    return x"]
        assert _detect_indent(lines) == 4

    def test_two_spaces(self):
        lines = ["if x", "  print x", "  print y"]
        assert _detect_indent(lines) == 2

    def test_mixed_depths(self):
        lines = ["if x", "    print x", "        print y"]
        # GCD of 4 and 8 = 4
        assert _detect_indent(lines) == 4

    def test_no_indentation(self):
        lines = ["x = 1", "y = 2", "print x"]
        # Falls back to default
        assert _detect_indent(lines) == 4

    def test_skips_comments(self):
        lines = ["# this is a comment", "  # indented comment", "function foo x", "    return x"]
        assert _detect_indent(lines) == 4

    def test_skips_blank_lines(self):
        lines = ["", "function foo x", "", "    return x", ""]
        assert _detect_indent(lines) == 4


# ---------------------------------------------------------------
# Indent normalisation
# ---------------------------------------------------------------

class TestNormaliseIndent:
    def test_no_change(self):
        assert _normalise_indent("    return x", 4, 4) == "    return x"

    def test_tabs_to_spaces(self):
        assert _normalise_indent("\treturn x", 4, 4) == "    return x"

    def test_two_to_four(self):
        assert _normalise_indent("  return x", 2, 4) == "    return x"

    def test_four_to_two(self):
        assert _normalise_indent("    return x", 4, 2) == "  return x"

    def test_nested(self):
        assert _normalise_indent("        print y", 4, 4) == "        print y"

    def test_nested_conversion(self):
        assert _normalise_indent("      print y", 2, 4) == "            print y"

    def test_empty_line(self):
        assert _normalise_indent("", 4, 4) == ""

    def test_no_indent(self):
        assert _normalise_indent("x = 1", 4, 4) == "x = 1"

    def test_zero_old_indent(self):
        # Can't determine levels, return unchanged
        assert _normalise_indent("  x = 1", 0, 4) == "  x = 1"


# ---------------------------------------------------------------
# Operator spacing
# ---------------------------------------------------------------

class TestOperatorSpacing:
    def test_assignment_no_spaces(self):
        assert _fix_operator_spacing("x=1").strip() == "x = 1"

    def test_assignment_already_spaced(self):
        assert _fix_operator_spacing("x = 1").strip() == "x = 1"

    def test_equality(self):
        assert _fix_operator_spacing("if x==y").strip() == "if x == y"

    def test_not_equal(self):
        assert _fix_operator_spacing("if x!=y").strip() == "if x != y"

    def test_lte(self):
        assert _fix_operator_spacing("if x<=y").strip() == "if x <= y"

    def test_gte(self):
        assert _fix_operator_spacing("if x>=y").strip() == "if x >= y"

    def test_pipe(self):
        assert _fix_operator_spacing("x|>foo").strip() == "x |> foo"

    def test_arrow(self):
        assert _fix_operator_spacing("x->y").strip() == "x -> y"

    def test_preserves_strings(self):
        result = _fix_operator_spacing('x = "a==b"')
        assert '==b"' in result  # The == inside string should not be spaced

    def test_comment_line_unchanged(self):
        line = "# x=1 y==2"
        assert _fix_operator_spacing(line) == line

    def test_preserves_indentation(self):
        result = _fix_operator_spacing("    x=1")
        assert result.startswith("    ")
        assert "x = 1" in result

    def test_trailing_comment_preserved(self):
        result = _fix_operator_spacing("x=1 # assign")
        assert "x = 1" in result
        assert "# assign" in result

    def test_fstring_preserved(self):
        result = _fix_operator_spacing('y = f"value={x}"')
        assert 'f"value={x}"' in result

    def test_addition(self):
        assert _fix_operator_spacing("return x+y").strip() == "return x + y"

    def test_multiplication(self):
        assert _fix_operator_spacing("return x*y").strip() == "return x * y"

    def test_subtraction_binary(self):
        assert _fix_operator_spacing("return x-y").strip() == "return x - y"

    def test_division(self):
        assert _fix_operator_spacing("return x/y").strip() == "return x / y"

    def test_modulo(self):
        assert _fix_operator_spacing("return x%y").strip() == "return x % y"

    def test_unary_minus_preserved(self):
        result = _fix_operator_spacing("x = -1")
        assert "-1" in result  # unary minus stays tight


# ---------------------------------------------------------------
# Blank line collapsing
# ---------------------------------------------------------------

class TestCollapseBlankLines:
    def test_no_blanks(self):
        lines = ["x = 1", "y = 2"]
        assert _collapse_blanks(lines, 2) == lines

    def test_single_blank(self):
        lines = ["x = 1", "", "y = 2"]
        assert _collapse_blanks(lines, 2) == lines

    def test_triple_blank_to_double(self):
        lines = ["x = 1", "", "", "", "y = 2"]
        assert _collapse_blanks(lines, 2) == ["x = 1", "", "", "y = 2"]

    def test_five_blanks(self):
        lines = ["a", "", "", "", "", "", "b"]
        result = _collapse_blanks(lines, 2)
        assert result == ["a", "", "", "b"]

    def test_max_one(self):
        lines = ["a", "", "", "b"]
        result = _collapse_blanks(lines, 1)
        assert result == ["a", "", "b"]


# ---------------------------------------------------------------
# Trailing whitespace
# ---------------------------------------------------------------

class TestStripTrailing:
    def test_strips_spaces(self):
        assert _strip_trailing(["x = 1   ", "y = 2  "]) == ["x = 1", "y = 2"]

    def test_strips_tabs(self):
        assert _strip_trailing(["x = 1\t"]) == ["x = 1"]

    def test_preserves_leading(self):
        assert _strip_trailing(["    x = 1   "]) == ["    x = 1"]


# ---------------------------------------------------------------
# Final newline
# ---------------------------------------------------------------

class TestFinalNewline:
    def test_adds_newline(self):
        assert _ensure_final_newline("x = 1") == "x = 1\n"

    def test_keeps_single(self):
        assert _ensure_final_newline("x = 1\n") == "x = 1\n"

    def test_collapses_multiple(self):
        assert _ensure_final_newline("x = 1\n\n\n") == "x = 1\n"


# ---------------------------------------------------------------
# Trailing comment splitting
# ---------------------------------------------------------------

class TestSplitTrailingComment:
    def test_no_comment(self):
        code, comment = _split_trailing_comment("x = 1")
        assert code == "x = 1"
        assert comment is None

    def test_trailing_comment(self):
        code, comment = _split_trailing_comment("x = 1 # value")
        assert code == "x = 1 "
        assert comment == "# value"

    def test_hash_in_string(self):
        code, comment = _split_trailing_comment('x = "#not a comment"')
        assert comment is None

    def test_comment_after_string(self):
        code, comment = _split_trailing_comment('x = "hello" # greeting')
        assert comment == "# greeting"


# ---------------------------------------------------------------
# Inline comment alignment
# ---------------------------------------------------------------

class TestAlignComments:
    def test_aligns_two_lines(self):
        lines = [
            "x = 1 # first",
            "longvar = 2 # second",
        ]
        result = _align_inline_comments(lines)
        # Both # should be at the same column
        idx0 = result[0].index("#")
        idx1 = result[1].index("#")
        assert idx0 == idx1

    def test_single_line_unchanged(self):
        lines = ["x = 1 # comment", "y = 2"]
        result = _align_inline_comments(lines)
        # Only one line in group, no alignment
        assert result == lines

    def test_no_comments(self):
        lines = ["x = 1", "y = 2"]
        result = _align_inline_comments(lines)
        assert result == lines


# ---------------------------------------------------------------
# Full format_code integration
# ---------------------------------------------------------------

class TestFormatCode:
    def test_basic_function(self):
        source = "function add x y\n    return x+y\n"
        result = format_code(source)
        assert "return x + y" in result
        assert result.endswith("\n")

    def test_trailing_whitespace_removed(self):
        source = "x = 1   \ny = 2  \n"
        result = format_code(source)
        for line in result.split("\n"):
            assert line == line.rstrip()

    def test_excessive_blanks_collapsed(self):
        source = "x = 1\n\n\n\n\ny = 2\n"
        result = format_code(source)
        # Should not have more than 2 consecutive blank lines
        assert "\n\n\n\n" not in result

    def test_final_newline_added(self):
        source = "x = 1"
        result = format_code(source)
        assert result.endswith("\n")

    def test_indent_normalisation(self):
        source = "function foo x\n  return x\n"
        result = format_code(source, indent_width=4)
        assert "    return x" in result

    def test_preserves_comments(self):
        source = "# This is a comment\nx = 1\n"
        result = format_code(source)
        assert "# This is a comment" in result

    def test_preserves_strings(self):
        source = 'print "hello world"\n'
        result = format_code(source)
        assert '"hello world"' in result

    def test_idempotent(self):
        source = "function square x\n    return x * x\n\nprint square 5\n"
        result1 = format_code(source)
        result2 = format_code(result1)
        assert result1 == result2

    def test_custom_indent_width(self):
        source = "function foo x\n    return x\n"
        result = format_code(source, indent_width=2)
        assert "  return x" in result

    def test_complex_program(self):
        source = (
            "# Test program\n"
            "function factorial n\n"
            "    if n<=1\n"
            "        return 1\n"
            "    return n*factorial (n-1)\n"
            "\n"
            "print factorial 10\n"
        )
        result = format_code(source)
        assert "n <= 1" in result
        assert "n * factorial" in result
        assert result.endswith("\n")

    def test_empty_file(self):
        result = format_code("")
        assert result == "\n"

    def test_only_comments(self):
        source = "# comment 1\n# comment 2\n"
        result = format_code(source)
        assert "# comment 1" in result
        assert "# comment 2" in result


# ---------------------------------------------------------------
# Unified diff
# ---------------------------------------------------------------

class TestDiff:
    def test_no_diff(self):
        text = "x = 1\n"
        assert unified_diff(text, text) == ""

    def test_has_diff(self):
        original = "x=1\n"
        formatted = "x = 1\n"
        diff = unified_diff(original, formatted, "test.srv")
        assert "---" in diff
        assert "+++" in diff
        assert "-x=1" in diff
        assert "+x = 1" in diff


# ---------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------

class TestFindFiles:
    def test_finds_srv_files(self, tmp_path):
        (tmp_path / "a.srv").write_text("x = 1\n")
        (tmp_path / "b.py").write_text("x = 1\n")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "c.srv").write_text("y = 2\n")
        files = _find_srv_files(str(tmp_path))
        assert len(files) == 2
        assert all(f.endswith(".srv") for f in files)

    def test_empty_dir(self, tmp_path):
        assert _find_srv_files(str(tmp_path)) == []


# ---------------------------------------------------------------
# CLI integration (write mode)
# ---------------------------------------------------------------

class TestCLIWrite:
    def test_write_mode(self, tmp_path):
        srv = tmp_path / "test.srv"
        srv.write_text("x=1\ny=2  \n", encoding="utf-8")
        # Import main and simulate args
        from sauravfmt import _format_file
        changed = _format_file(str(srv), 4, write=True, check=False,
                               show_diff=False)
        assert changed is True
        content = srv.read_text(encoding="utf-8")
        assert "x = 1" in content
        assert content == content.rstrip() + "\n"  # final newline

    def test_check_mode_no_changes(self, tmp_path):
        srv = tmp_path / "clean.srv"
        srv.write_text("x = 1\n", encoding="utf-8")
        from sauravfmt import _format_file
        changed = _format_file(str(srv), 4, write=False, check=True,
                               show_diff=False)
        assert changed is False

    def test_check_mode_with_changes(self, tmp_path):
        srv = tmp_path / "dirty.srv"
        srv.write_text("x=1  \n", encoding="utf-8")
        from sauravfmt import _format_file
        changed = _format_file(str(srv), 4, write=False, check=True,
                               show_diff=False)
        assert changed is True


# ---------------------------------------------------------------
# Formatting on actual .srv demo files
# ---------------------------------------------------------------

class TestRealFiles:
    """Run formatter on the repo's .srv files and verify idempotency."""

    @pytest.fixture
    def repo_root(self):
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_hello_srv_idempotent(self, repo_root):
        path = os.path.join(repo_root, "hello.srv")
        if not os.path.exists(path):
            pytest.skip("hello.srv not found")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        result = format_code(source)
        result2 = format_code(result)
        assert result == result2, "Formatter is not idempotent on hello.srv"
