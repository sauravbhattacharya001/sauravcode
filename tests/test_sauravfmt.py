"""Tests for sauravfmt — the sauravcode formatter."""

import pytest
import sauravfmt


# ── _detect_indent ────────────────────────────────────────────────────

class TestDetectIndent:
    def test_default_when_no_indentation(self):
        lines = ["x = 1", "y = 2", "z = 3"]
        assert sauravfmt._detect_indent(lines) == sauravfmt.DEFAULT_INDENT

    def test_detects_two_space(self):
        lines = ["function foo", "  x = 1", "  y = 2"]
        assert sauravfmt._detect_indent(lines) == 2

    def test_detects_four_space(self):
        lines = ["if x", "    y = 1", "    z = 2"]
        assert sauravfmt._detect_indent(lines) == 4

    def test_skips_blank_lines(self):
        lines = ["x = 1", "", "  y = 2", "", "  z = 3"]
        assert sauravfmt._detect_indent(lines) == 2

    def test_skips_comments(self):
        lines = ["# comment", "  x = 1", "  y = 2"]
        assert sauravfmt._detect_indent(lines) == 2

    def test_gcd_of_mixed_indents(self):
        # 2 and 4 -> gcd = 2
        lines = ["a", "  b", "    c"]
        assert sauravfmt._detect_indent(lines) == 2


# ── _normalise_indent ────────────────────────────────────────────────

class TestNormaliseIndent:
    def test_no_indent_unchanged(self):
        assert sauravfmt._normalise_indent("x = 1", 4, 4) == "x = 1"

    def test_empty_line(self):
        assert sauravfmt._normalise_indent("", 4, 2) == ""

    def test_convert_4_to_2(self):
        result = sauravfmt._normalise_indent("    x = 1", 4, 2)
        assert result == "  x = 1"

    def test_convert_2_to_4(self):
        result = sauravfmt._normalise_indent("  x = 1", 2, 4)
        assert result == "    x = 1"

    def test_tab_to_spaces(self):
        result = sauravfmt._normalise_indent("\tx = 1", 4, 4)
        assert result == "    x = 1"

    def test_zero_old_indent_unchanged(self):
        result = sauravfmt._normalise_indent("  x = 1", 0, 4)
        assert result == "  x = 1"

    def test_nested_levels(self):
        result = sauravfmt._normalise_indent("        x = 1", 4, 2)
        assert result == "    x = 1"


# ── _strip_trailing ──────────────────────────────────────────────────

class TestStripTrailing:
    def test_removes_trailing_spaces(self):
        lines = ["x = 1   ", "y = 2  "]
        assert sauravfmt._strip_trailing(lines) == ["x = 1", "y = 2"]

    def test_removes_trailing_tabs(self):
        lines = ["x = 1\t"]
        assert sauravfmt._strip_trailing(lines) == ["x = 1"]

    def test_preserves_leading_whitespace(self):
        lines = ["    x = 1  "]
        assert sauravfmt._strip_trailing(lines) == ["    x = 1"]

    def test_empty_line_stays_empty(self):
        assert sauravfmt._strip_trailing([""]) == [""]


# ── _collapse_blanks ─────────────────────────────────────────────────

class TestCollapseBlanks:
    def test_no_blanks_unchanged(self):
        lines = ["a", "b", "c"]
        assert sauravfmt._collapse_blanks(lines, 2) == ["a", "b", "c"]

    def test_collapse_three_to_two(self):
        lines = ["a", "", "", "", "b"]
        result = sauravfmt._collapse_blanks(lines, 2)
        assert result == ["a", "", "", "b"]

    def test_collapse_five_to_one(self):
        lines = ["a", "", "", "", "", "", "b"]
        result = sauravfmt._collapse_blanks(lines, 1)
        assert result == ["a", "", "b"]

    def test_keeps_blanks_under_limit(self):
        lines = ["a", "", "b"]
        assert sauravfmt._collapse_blanks(lines, 2) == ["a", "", "b"]


# ── _ensure_final_newline ─────────────────────────────────────────────

class TestEnsureFinalNewline:
    def test_adds_newline(self):
        assert sauravfmt._ensure_final_newline("hello") == "hello\n"

    def test_no_double_newline(self):
        assert sauravfmt._ensure_final_newline("hello\n") == "hello\n"

    def test_strips_multiple_trailing(self):
        assert sauravfmt._ensure_final_newline("hello\n\n\n") == "hello\n"

    def test_handles_crlf(self):
        result = sauravfmt._ensure_final_newline("hello\r\n")
        assert result == "hello\n"


# ── _split_trailing_comment ──────────────────────────────────────────

class TestSplitTrailingComment:
    def test_no_comment(self):
        code, comment = sauravfmt._split_trailing_comment("x = 1")
        assert code == "x = 1"
        assert comment is None

    def test_trailing_comment(self):
        code, comment = sauravfmt._split_trailing_comment("x = 1  # set x")
        assert code == "x = 1  "
        assert comment == "# set x"

    def test_hash_inside_string(self):
        code, comment = sauravfmt._split_trailing_comment('x = "a#b"')
        assert code == 'x = "a#b"'
        assert comment is None

    def test_comment_after_string(self):
        code, comment = sauravfmt._split_trailing_comment('x = "hello" # assign')
        assert code == 'x = "hello" '
        assert comment == "# assign"

    def test_full_line_comment(self):
        code, comment = sauravfmt._split_trailing_comment("# this is a comment")
        assert code == ""
        assert comment == "# this is a comment"


# ── _fix_operator_spacing ────────────────────────────────────────────

class TestFixOperatorSpacing:
    def test_comment_line_unchanged(self):
        assert sauravfmt._fix_operator_spacing("  # x=1+2").strip() == "# x=1+2"

    def test_spaces_around_equals(self):
        result = sauravfmt._fix_operator_spacing("x=1")
        assert "x = 1" in result

    def test_spaces_around_comparison(self):
        result = sauravfmt._fix_operator_spacing("if x==1")
        assert "x == 1" in result

    def test_pipe_operator(self):
        result = sauravfmt._fix_operator_spacing("x|>f")
        assert "|>" in result

    def test_preserves_string_content(self):
        result = sauravfmt._fix_operator_spacing('x = "a==b"')
        assert '"a==b"' in result

    def test_preserves_fstring(self):
        result = sauravfmt._fix_operator_spacing('x = f"a+b"')
        assert 'f"a+b"' in result

    def test_already_spaced_unchanged(self):
        line = "x = 1 + 2"
        result = sauravfmt._fix_operator_spacing(line)
        assert result.strip() == "x = 1 + 2"

    def test_preserves_leading_indent(self):
        result = sauravfmt._fix_operator_spacing("    x=1")
        assert result.startswith("    ")

    def test_unary_minus_not_spaced(self):
        result = sauravfmt._fix_operator_spacing("x = -1")
        assert "-1" in result

    def test_not_equal(self):
        result = sauravfmt._fix_operator_spacing("if x!=y")
        assert "!=" in result


# ── _align_inline_comments ───────────────────────────────────────────

class TestAlignInlineComments:
    def test_aligns_two_consecutive(self):
        lines = [
            "x = 1  # short",
            "long_var = 2  # also short",
        ]
        result = sauravfmt._align_inline_comments(lines)
        # Both # should be at the same column
        idx0 = result[0].index("#")
        idx1 = result[1].index("#")
        assert idx0 == idx1

    def test_single_comment_no_alignment(self):
        lines = ["x = 1  # comment", "y = 2"]
        result = sauravfmt._align_inline_comments(lines)
        assert result[0] == "x = 1  # comment"

    def test_no_comments_unchanged(self):
        lines = ["x = 1", "y = 2"]
        result = sauravfmt._align_inline_comments(lines)
        assert result == lines


# ── format_code (integration) ────────────────────────────────────────

class TestFormatCode:
    def test_empty_input(self):
        result = sauravfmt.format_code("")
        assert result == "\n"

    def test_basic_formatting(self):
        source = "x=1\ny=2\n"
        result = sauravfmt.format_code(source)
        assert "x = 1" in result
        assert "y = 2" in result

    def test_trailing_whitespace_removed(self):
        source = "x = 1   \ny = 2  \n"
        result = sauravfmt.format_code(source)
        assert "   \n" not in result

    def test_excessive_blanks_collapsed(self):
        source = "x = 1\n\n\n\n\ny = 2\n"
        result = sauravfmt.format_code(source)
        # Should have at most MAX_CONSECUTIVE_BLANKS blank lines
        max_consecutive = 0
        current = 0
        for line in result.split("\n"):
            if line.strip() == "":
                current += 1
                max_consecutive = max(max_consecutive, current)
            else:
                current = 0
        assert max_consecutive <= sauravfmt.MAX_CONSECUTIVE_BLANKS

    def test_ends_with_newline(self):
        result = sauravfmt.format_code("x = 1")
        assert result.endswith("\n")

    def test_no_double_trailing_newlines(self):
        result = sauravfmt.format_code("x = 1\n\n\n")
        assert not result.endswith("\n\n")

    def test_indent_normalization(self):
        source = "if x\n  y = 1\n  z = 2\n"
        result = sauravfmt.format_code(source, indent_width=4)
        lines = result.split("\n")
        # y and z should be indented with 4 spaces (1 level)
        assert lines[1].startswith("    ")

    def test_custom_indent_width(self):
        source = "if x\n    y = 1\n"
        result = sauravfmt.format_code(source, indent_width=2)
        lines = result.split("\n")
        assert lines[1].startswith("  ")

    def test_idempotent(self):
        source = "x = 1 + 2\ny = 3\n"
        first = sauravfmt.format_code(source)
        second = sauravfmt.format_code(first)
        assert first == second, "Formatting should be idempotent"


# ── unified_diff ──────────────────────────────────────────────────────

class TestUnifiedDiff:
    def test_no_changes_empty_diff(self):
        text = "x = 1\n"
        assert sauravfmt.unified_diff(text, text) == ""

    def test_changes_produce_diff(self):
        original = "x=1\n"
        formatted = "x = 1\n"
        diff = sauravfmt.unified_diff(original, formatted)
        assert len(diff) > 0
        assert "-x=1" in diff
        assert "+x = 1" in diff

    def test_custom_filename(self):
        diff = sauravfmt.unified_diff("a\n", "b\n", filename="test.srv")
        assert "test.srv" in diff
