"""Tests for sauravrefactor — automated refactoring tool."""

import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sauravrefactor import (
    refactor_rename,
    refactor_extract,
    refactor_inline,
    refactor_deadcode,
    refactor_unused,
    _replace_outside_strings,
    show_diff,
    format_json,
    get_color,
)


# ── Rename ───────────────────────────────────────────────────────

class TestRename:
    def test_basic_rename(self):
        src = 'x = 10\ny = x + 5\nprint(x)\n'
        result, count, _ = refactor_rename(src, 'x', 'counter')
        assert count == 3
        assert 'counter = 10' in result
        assert 'counter + 5' in result
        assert 'print(counter)' in result

    def test_rename_function(self):
        src = 'function greet(name)\n    print(name)\ngreet("hi")\n'
        result, count, _ = refactor_rename(src, 'greet', 'say_hello')
        assert count >= 2
        assert 'function say_hello' in result
        assert 'say_hello("hi")' in result

    def test_skip_strings(self):
        src = 'x = "hello x world"\ny = x\n'
        result, count, _ = refactor_rename(src, 'x', 'z')
        assert '"hello x world"' in result
        assert 'z = "hello x world"' in result

    def test_reject_reserved_word(self):
        src = 'x = 1\n'
        _, count, _ = refactor_rename(src, 'x', 'for')
        assert count == 0

    def test_reject_invalid_identifier(self):
        src = 'x = 1\n'
        _, count, _ = refactor_rename(src, 'x', '123bad')
        assert count == 0

    def test_word_boundary(self):
        src = 'fox = 1\nx = 2\n'
        result, count, _ = refactor_rename(src, 'x', 'y')
        assert 'fox = 1' in result
        assert 'y = 2' in result

    def test_skip_comments(self):
        src = 'x = 1 # x is important\n'
        result, count, _ = refactor_rename(src, 'x', 'val')
        assert 'val = 1' in result
        assert '# x is important' in result

    def test_no_partial_match(self):
        src = 'ab = 1\nabc = 2\na = ab + abc\n'
        result, count, _ = refactor_rename(src, 'ab', 'xy')
        assert 'xy = 1' in result
        assert 'abc = 2' in result

    def test_empty_source(self):
        result, count, _ = refactor_rename('', 'x', 'y')
        assert result == ''
        assert count == 0

    def test_no_occurrences(self):
        src = 'a = 1\nb = 2\n'
        result, count, _ = refactor_rename(src, 'z', 'w')
        assert count == 0
        assert result == src


# ── Extract ──────────────────────────────────────────────────────

class TestExtract:
    def test_basic_extract(self):
        src = 'a = 10\nb = 20\nc = a + b\nprint(c)\n'
        result, changes = refactor_extract(src, 2, 3, 'compute')
        assert 'function compute' in result
        assert 'compute(' in result

    def test_invalid_range(self):
        src = 'x = 5\ny = x * 2\n'
        result, changes = refactor_extract(src, 5, 3, 'bad')
        assert 'Invalid line range' in changes[0]

    def test_invalid_func_name(self):
        src = 'x = 5\ny = x * 2\n'
        result, changes = refactor_extract(src, 1, 2, '123func')
        assert 'Invalid function name' in changes[0]

    def test_single_line_extract(self):
        src = 'a = 1\nb = a + 1\nprint(b)\n'
        result, changes = refactor_extract(src, 2, 2, 'inc')
        assert 'function inc' in result


# ── Inline ───────────────────────────────────────────────────────

class TestInline:
    def test_basic_inline(self):
        src = 'temp = 42\nresult = temp + 1\nprint(result)\n'
        result, changes = refactor_inline(src, 'temp')
        assert 'result = 42 + 1' in result

    def test_inline_with_parens(self):
        src = 'a = 1 + 2\nb = a * 3\n'
        result, changes = refactor_inline(src, 'a')
        assert '(1 + 2)' in result

    def test_inline_unused_removes(self):
        src = 'x = 10\ny = 20\nz = y\n'
        result, changes = refactor_inline(src, 'x')
        assert 'x' not in result.split('\n')[0] or 'Removed unused' in changes[0]

    def test_reject_multi_assign(self):
        src = 'x = 1\nx = 2\ny = x\n'
        _, changes = refactor_inline(src, 'x')
        assert 'assigned 2 times' in changes[0]

    def test_reject_missing_var(self):
        src = 'a = 1\nb = 2\n'
        _, changes = refactor_inline(src, 'z')
        assert 'No assignment' in changes[0]

    def test_multiple_usages(self):
        src = 'c = 100\na = c\nb = c\nprint(a + b)\n'
        result, changes = refactor_inline(src, 'c')
        assert 'a = 100' in result
        assert 'b = 100' in result


# ── Dead Code ────────────────────────────────────────────────────

class TestDeadCode:
    def test_remove_after_return(self):
        src = 'function foo()\n    return 1\n    x = 2\n    print(x)\n'
        result, changes = refactor_deadcode(src)
        assert len(changes) > 0

    def test_no_false_positives(self):
        src = 'x = 1\ny = 2\nprint(x + y)\n'
        result, changes = refactor_deadcode(src)
        assert len(changes) == 0
        assert result == src

    def test_empty_source(self):
        result, changes = refactor_deadcode('')
        assert result == ''
        assert len(changes) == 0


# ── Unused ───────────────────────────────────────────────────────

class TestUnused:
    def test_remove_unused_variable(self):
        src = 'x = 10\ny = 20\nprint(y)\n'
        result, changes = refactor_unused(src)
        assert len(changes) > 0

    def test_keep_used_variables(self):
        src = 'a = 1\nb = a + 1\nprint(b)\n'
        result, changes = refactor_unused(src)
        assert len(changes) == 0

    def test_empty_source(self):
        result, changes = refactor_unused('')
        assert len(changes) == 0


# ── Helpers ──────────────────────────────────────────────────────

class TestHelpers:
    def test_replace_outside_strings(self):
        r = _replace_outside_strings('x = "hello x" + x', 'x', 'y')
        assert r == 'y = "hello x" + y'

    def test_diff_generation(self):
        diff = show_diff("a = 1\n", "b = 1\n", "test.srv", get_color(False))
        assert '---' in diff or 'a/' in diff

    def test_json_output(self):
        import json
        js = format_json("rename", "test.srv", ["renamed x"], "old", "new")
        parsed = json.loads(js)
        assert parsed["command"] == "rename"
        assert parsed["modified"] is True

    def test_json_no_change(self):
        import json
        js = format_json("rename", "test.srv", [], "same", "same")
        parsed = json.loads(js)
        assert parsed["modified"] is False

    def test_color_enabled(self):
        c = get_color(True)
        assert c.RED != ''

    def test_color_disabled(self):
        c = get_color(False)
        assert c.RED == ''
