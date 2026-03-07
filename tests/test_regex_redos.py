"""Tests for ReDoS protection in regex builtins."""
import pytest
import sys
import os
import io
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from saurav import Interpreter, tokenize, Parser


def run_code(code):
    """Parse and interpret a sauravcode snippet, returning stdout output."""
    tokens = list(tokenize(code))
    parser = Parser(tokens)
    ast_nodes = parser.parse()
    interp = Interpreter()
    buf = io.StringIO()
    with redirect_stdout(buf):
        for node in ast_nodes:
            interp.interpret(node)
    return buf.getvalue()


class TestRegexReDoSProtection:
    """Test that regex builtins are protected against ReDoS attacks."""

    # -- Normal operation still works --

    def test_regex_match_normal(self):
        out = run_code('print regex_match "^hello$" "hello"\n')
        assert out.strip() == "true"

    def test_regex_match_no_match(self):
        out = run_code('print regex_match "^hello$" "world"\n')
        assert out.strip() == "false"

    def test_regex_find_normal(self):
        out = run_code('m = regex_find "\\\\d+" "abc123def"\nprint m["match"]\n')
        assert out.strip() == "123"

    def test_regex_find_all_normal(self):
        out = run_code('r = regex_find_all "\\\\d+" "a1b2c3"\nprint len r\n')
        assert out.strip() == "3"

    def test_regex_replace_normal(self):
        out = run_code('print regex_replace "\\\\d" "X" "a1b2"\n')
        assert out.strip() == "aXbX"

    def test_regex_split_normal(self):
        out = run_code('r = regex_split "[,;]" "a,b;c"\nprint len r\n')
        assert out.strip() == "3"

    def test_regex_find_groups(self):
        out = run_code('m = regex_find "(\\\\d+)-(\\\\d+)" "abc123-456def"\nprint m["groups"]\n')
        assert "123" in out
        assert "456" in out

    def test_regex_find_all_groups(self):
        out = run_code('r = regex_find_all "(\\\\w)(\\\\d)" "a1b2c3"\nprint len r\n')
        assert out.strip() == "3"

    # -- Safe quantified groups (NOT nested quantifiers) --

    def test_quantified_group_no_inner_quantifier(self):
        """(abc)+ is safe — no inner quantifier."""
        out = run_code('print regex_match "(abc)+" "abcabc"\n')
        assert out.strip() == "true"

    def test_alternation_with_quantifier(self):
        """(a|b)+ is safe — alternation, not nested quantifier."""
        out = run_code('print regex_match "(a|b)+" "abba"\n')
        assert out.strip() == "true"

    def test_character_class_quantifier(self):
        """[abc]+ is safe."""
        out = run_code('print regex_match "[abc]+" "abcabc"\n')
        assert out.strip() == "true"

    # -- Pattern length limits --

    def test_pattern_too_long_match(self):
        long_pat = "a" * 1001
        code = f'print regex_match "{long_pat}" "test"\n'
        with pytest.raises(RuntimeError, match="regex pattern too long"):
            run_code(code)

    def test_pattern_too_long_find(self):
        long_pat = "a" * 1001
        code = f'print regex_find "{long_pat}" "test"\n'
        with pytest.raises(RuntimeError, match="regex pattern too long"):
            run_code(code)

    def test_pattern_too_long_find_all(self):
        long_pat = "a" * 1001
        code = f'print regex_find_all "{long_pat}" "test"\n'
        with pytest.raises(RuntimeError, match="regex pattern too long"):
            run_code(code)

    def test_pattern_too_long_replace(self):
        long_pat = "a" * 1001
        code = f'print regex_replace "{long_pat}" "y" "test"\n'
        with pytest.raises(RuntimeError, match="regex pattern too long"):
            run_code(code)

    def test_pattern_too_long_split(self):
        long_pat = "a" * 1001
        code = f'print regex_split "{long_pat}" "test"\n'
        with pytest.raises(RuntimeError, match="regex pattern too long"):
            run_code(code)

    def test_pattern_at_max_length(self):
        """Pattern exactly at 1000 chars is allowed."""
        pat = "a" * 1000
        inp = "a" * 1000
        code = f'print regex_match "{pat}" "{inp}"\n'
        out = run_code(code)
        assert out.strip() == "true"

    # -- Invalid pattern syntax --

    def test_invalid_pattern_match(self):
        with pytest.raises(RuntimeError, match="invalid regex pattern"):
            run_code('print regex_match "[invalid" "test"\n')

    def test_invalid_pattern_find(self):
        with pytest.raises(RuntimeError, match="invalid regex pattern"):
            run_code('print regex_find "[bad" "test"\n')

    def test_invalid_pattern_find_all(self):
        with pytest.raises(RuntimeError, match="invalid regex pattern"):
            run_code('print regex_find_all "(unclosed" "test"\n')

    # -- Nested quantifier rejection (ReDoS prevention) --

    def test_redos_nested_plus_plus_match(self):
        """(a+)+ is a classic ReDoS pattern — rejected."""
        with pytest.raises(RuntimeError, match="nested quantifiers"):
            run_code('print regex_match "(a+)+" "aaa"\n')

    def test_redos_nested_star_plus_match(self):
        """(a*)+ is dangerous — rejected."""
        with pytest.raises(RuntimeError, match="nested quantifiers"):
            run_code('print regex_match "(a*)+" "aaa"\n')

    def test_redos_nested_plus_star_match(self):
        """(a+)* is dangerous — rejected."""
        with pytest.raises(RuntimeError, match="nested quantifiers"):
            run_code('print regex_match "(a+)*" "aaa"\n')

    def test_redos_nested_star_star_match(self):
        """(a*)* is dangerous — rejected."""
        with pytest.raises(RuntimeError, match="nested quantifiers"):
            run_code('print regex_match "(a*)*" "aaa"\n')

    def test_redos_nested_quantifier_brace(self):
        """(a?){N} is dangerous — rejected."""
        with pytest.raises(RuntimeError, match="nested quantifiers"):
            run_code('print regex_match "(a?){5}" "aaa"\n')

    def test_redos_nested_plus_brace(self):
        """(a+){N} is dangerous — rejected."""
        with pytest.raises(RuntimeError, match="nested quantifiers"):
            run_code('print regex_match "(a+){5}" "aaa"\n')

    def test_redos_nested_brace_plus(self):
        """(a{2})+ is dangerous — rejected."""
        with pytest.raises(RuntimeError, match="nested quantifiers"):
            run_code('print regex_match "(a{2})+" "aaa"\n')

    def test_redos_find_rejects_nested(self):
        """regex_find also rejects nested quantifiers."""
        with pytest.raises(RuntimeError, match="nested quantifiers"):
            run_code('print regex_find "(a+)+" "aaa"\n')

    def test_redos_find_all_rejects_nested(self):
        """regex_find_all also rejects nested quantifiers."""
        with pytest.raises(RuntimeError, match="nested quantifiers"):
            run_code('print regex_find_all "(a+)+" "aaa"\n')

    def test_redos_replace_rejects_nested(self):
        """regex_replace also rejects nested quantifiers."""
        with pytest.raises(RuntimeError, match="nested quantifiers"):
            run_code('print regex_replace "(a+)+" "X" "aaa"\n')

    def test_redos_split_rejects_nested(self):
        """regex_split also rejects nested quantifiers."""
        with pytest.raises(RuntimeError, match="nested quantifiers"):
            run_code('print regex_split "(a+)+" "aaa"\n')

    def test_redos_complex_nested(self):
        """More complex nested quantifier pattern."""
        with pytest.raises(RuntimeError, match="nested quantifiers"):
            run_code('print regex_match "([a-z]+)+" "abc"\n')

    def test_redos_dot_star_plus(self):
        """(.*)+  is dangerous — rejected."""
        with pytest.raises(RuntimeError, match="nested quantifiers"):
            run_code('print regex_match "(.*)+" "abc"\n')
