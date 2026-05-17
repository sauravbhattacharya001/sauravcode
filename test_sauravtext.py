"""Tests for sauravtext - shared text-processing utilities.

These cover the canonical string/comment-aware scanner that every
sauravcode tool (sauravfmt, sauravlint, sauravmin, ...) depends on.
A regression here breaks every downstream tool, so the coverage is
deliberately exhaustive on the tricky corners: escapes, f-strings,
mixed quotes, hashes inside strings, embedded newlines, etc.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sauravtext import (
    find_comment_offset,
    strip_comment,
    split_trailing_comment,
    strip_string_literals,
    extract_identifiers,
    scan_segments,
    html_escape,
)


# ---------------------------------------------------------------------------
# find_comment_offset
# ---------------------------------------------------------------------------

class TestFindCommentOffset:
    def test_no_hash_returns_none(self):
        assert find_comment_offset("x = 1") is None

    def test_empty_string_returns_none(self):
        assert find_comment_offset("") is None

    def test_simple_trailing_comment(self):
        assert find_comment_offset("x = 1  # note") == 7

    def test_hash_at_start_of_line(self):
        assert find_comment_offset("# full-line comment") == 0

    def test_hash_inside_double_quoted_string_is_ignored(self):
        line = 's = "has # inside"'
        assert find_comment_offset(line) is None

    def test_hash_inside_single_quoted_string_is_ignored(self):
        line = "s = 'has # inside'"
        assert find_comment_offset(line) is None

    def test_hash_after_string_is_detected(self):
        line = 's = "hello" # trailing'
        assert find_comment_offset(line) == line.index("#")

    def test_escaped_quote_does_not_end_string(self):
        # The middle " is escaped, so the # remains inside the string.
        line = 's = "a\\"b#c"'
        assert find_comment_offset(line) is None

    def test_escaped_backslash_then_quote_ends_string(self):
        # \\ is an escaped backslash, then " actually closes the string,
        # so the # that follows IS a comment.
        line = 's = "a\\\\" # real comment'
        offset = find_comment_offset(line)
        assert offset is not None
        # The '#' that we returned should be the trailing-comment one.
        assert line[offset] == '#'
        assert line[offset:].startswith("# real")

    def test_mixed_quotes_inside_outer_string(self):
        # A single quote inside a double-quoted string must not switch state.
        line = '''s = "it's #1"'''
        assert find_comment_offset(line) is None

    def test_hash_before_any_quote_fast_path(self):
        # Exercises the fast path where # appears before any quote.
        line = '# x = "abc"'
        assert find_comment_offset(line) == 0

    def test_multiple_hashes_returns_first(self):
        line = "x = 1  # one # two"
        assert find_comment_offset(line) == 7


# ---------------------------------------------------------------------------
# strip_comment / split_trailing_comment
# ---------------------------------------------------------------------------

class TestStripComment:
    def test_strip_simple(self):
        assert strip_comment("x = 1  # note") == "x = 1  "

    def test_strip_preserves_string_with_hash(self):
        line = 's = "has # inside"'
        assert strip_comment(line) == line

    def test_strip_no_comment_returns_input(self):
        assert strip_comment("x = 1") == "x = 1"

    def test_strip_only_comment(self):
        assert strip_comment("# all comment") == ""


class TestSplitTrailingComment:
    def test_split_with_comment(self):
        assert split_trailing_comment("x = 1  # note") == ("x = 1  ", "# note")

    def test_split_without_comment(self):
        assert split_trailing_comment("x = 1") == ("x = 1", None)

    def test_split_string_with_hash(self):
        line = 's = "a#b"'
        assert split_trailing_comment(line) == (line, None)

    def test_split_full_line_comment(self):
        assert split_trailing_comment("# only") == ("", "# only")


# ---------------------------------------------------------------------------
# strip_string_literals
# ---------------------------------------------------------------------------

class TestStripStringLiterals:
    def test_removes_plain_string(self):
        assert strip_string_literals('x = "hello"') == "x = "

    def test_removes_fstring(self):
        assert strip_string_literals('x = f"hello {name}"') == "x = "

    def test_keeps_code_around_string(self):
        assert strip_string_literals('a + "b" + c') == "a +  + c"

    def test_handles_escapes_inside_string(self):
        assert strip_string_literals('s = "a\\"b"') == "s = "

    def test_no_strings_returns_unchanged(self):
        assert strip_string_literals("x = 1 + 2") == "x = 1 + 2"

    def test_multiple_strings(self):
        assert strip_string_literals('"a" + "b"') == " + "


# ---------------------------------------------------------------------------
# extract_identifiers
# ---------------------------------------------------------------------------

class TestExtractIdentifiers:
    def test_basic_identifiers(self):
        assert extract_identifiers("x = foo(y)") == {"x", "foo", "y"}

    def test_strips_strings_and_comments(self):
        # "world" must NOT contribute, neither should the comment word.
        assert extract_identifiers('greet = "world"  # bar') == {"greet"}

    def test_ignores_numeric_literals(self):
        # 1 and 42 should not become identifiers (regex excludes leading digit)
        assert extract_identifiers("x = 1 + 42") == {"x"}

    def test_exclude_set(self):
        assert extract_identifiers(
            "if foo then bar", exclude={"if", "then"}
        ) == {"foo", "bar"}

    def test_underscore_identifier_ok(self):
        assert "_internal" in extract_identifiers("_internal = 1")

    def test_empty_input_returns_empty_set(self):
        assert extract_identifiers("") == set()


# ---------------------------------------------------------------------------
# scan_segments
# ---------------------------------------------------------------------------

class TestScanSegments:
    def _kinds(self, source):
        return [k for (k, _t, _s, _e) in scan_segments(source)]

    def _texts(self, source, kind):
        return [t for (k, t, _s, _e) in scan_segments(source) if k == kind]

    def test_empty_source_yields_nothing(self):
        assert list(scan_segments("")) == []

    def test_offsets_cover_input_exactly(self):
        source = 'x = "hi" # bye\n'
        segs = list(scan_segments(source))
        # Concatenating segment texts in order must reproduce the source.
        assert "".join(t for (_k, t, _s, _e) in segs) == source
        # Offsets must be contiguous and monotonic.
        for prev, nxt in zip(segs, segs[1:]):
            assert prev[3] == nxt[2]
        # First starts at 0, last ends at len(source).
        assert segs[0][2] == 0
        assert segs[-1][3] == len(source)

    def test_string_segment_kept_intact(self):
        source = 'x = "hello world"'
        strings = self._texts(source, "string")
        assert strings == ['"hello world"']

    def test_fstring_prefix_included(self):
        source = 'y = f"hi {name}"'
        strings = self._texts(source, "string")
        assert strings == ['f"hi {name}"']

    def test_comment_segment_extends_to_eol(self):
        source = "code # comment text\nnext = 1"
        comments = self._texts(source, "comment")
        assert comments == ["# comment text"]

    def test_escaped_quote_inside_string(self):
        source = 's = "a\\"b"'
        strings = self._texts(source, "string")
        # The whole quoted region (with embedded escaped quote) is one string.
        assert strings == ['"a\\"b"']

    def test_identifier_kind(self):
        source = "foo bar"
        idents = self._texts(source, "ident")
        assert idents == ["foo", "bar"]

    def test_unterminated_string_does_not_crash(self):
        # End-of-input mid-string: scanner should still terminate.
        result = list(scan_segments('x = "unterminated'))
        # Last segment should be a string starting at the quote.
        kinds = [k for (k, *_rest) in result]
        assert "string" in kinds

    def test_single_quoted_string(self):
        source = "x = 'abc'"
        assert self._texts(source, "string") == ["'abc'"]


# ---------------------------------------------------------------------------
# html_escape
# ---------------------------------------------------------------------------

class TestHtmlEscape:
    def test_all_four_chars(self):
        # Ampersand must be escaped FIRST so later replacements don't double-encode.
        assert html_escape("&") == "&amp;"
        assert html_escape("<") == "&lt;"
        assert html_escape(">") == "&gt;"
        assert html_escape('"') == "&quot;"

    def test_combined(self):
        src = '<script>alert("xss & oops")</script>'
        out = html_escape(src)
        assert out == (
            "&lt;script&gt;alert(&quot;xss &amp; oops&quot;)&lt;/script&gt;"
        )

    def test_no_special_chars_unchanged(self):
        assert html_escape("hello world") == "hello world"

    def test_empty_string(self):
        assert html_escape("") == ""

    def test_ampersand_not_double_escaped(self):
        # Critical: must not turn '&' into '&amp;amp;' on the second pass.
        assert html_escape("a & b") == "a &amp; b"

    def test_preserves_unicode(self):
        assert html_escape("café <") == "café &lt;"


# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------

def test_all_exports_resolvable():
    """Every name in __all__ must actually be a callable on the module."""
    import sauravtext

    for name in sauravtext.__all__:
        attr = getattr(sauravtext, name)
        assert callable(attr), f"{name} is exported but not callable"


# ---------------------------------------------------------------------------
# Cross-checks: scan_segments must agree with find_comment_offset
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "line",
    [
        "x = 1",
        "x = 1 # comment",
        '# pure comment',
        's = "a#b"',
        's = "abc" # real comment',
        "s = 'single#quote'",
        's = "a\\"b#c"',
        '',
    ],
)
def test_scan_segments_agrees_with_find_comment_offset(line):
    """If scan_segments reports a comment, find_comment_offset must point
    to the same '#'. Otherwise both must agree there is no comment."""
    segs = list(scan_segments(line))
    comments = [(s, e) for (k, _t, s, e) in segs if k == "comment"]
    offset = find_comment_offset(line)
    if comments:
        # find_comment_offset is "first '#' outside a string", which by
        # definition is the start of the first comment segment.
        assert offset == comments[0][0]
    else:
        assert offset is None
