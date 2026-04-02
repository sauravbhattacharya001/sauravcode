"""sauravtext — Shared text-processing utilities for sauravcode tooling.

Centralises string-aware line scanning so that sauravfmt, sauravlint,
and future tools don't re-implement the same escape/quote/comment logic.
"""

from typing import Optional, Set, Tuple
import re

__all__ = [
    "find_comment_offset",
    "strip_comment",
    "split_trailing_comment",
    "strip_string_literals",
    "extract_identifiers",
    "scan_segments",
]

# Matches identifiers (excludes leading digits)
_IDENT_RE = re.compile(r'\b([a-zA-Z_]\w*)\b')

# String literal pattern (double-quoted, with optional f-prefix)
_STRING_LITERAL_RE = re.compile(r'f?"(?:[^"\\]|\\.)*"')


def find_comment_offset(line: str) -> Optional[int]:
    """Return the index of the first ``#`` that is outside a string literal.

    Returns ``None`` if the line has no trailing comment.

    This is the single source of truth for "where does the comment start?"
    used by both :func:`strip_comment` and :func:`split_trailing_comment`.
    """
    in_string = False
    quote_char = None
    i = 0
    while i < len(line):
        ch = line[i]
        if ch in ('"', "'") and not in_string:
            in_string = True
            quote_char = ch
            i += 1
            continue
        if in_string:
            if ch == '\\' and i + 1 < len(line):
                i += 2          # skip escaped character
                continue
            if ch == quote_char:
                in_string = False
            i += 1
            continue
        if ch == '#':
            return i
        i += 1
    return None


def strip_comment(line: str) -> str:
    """Remove the trailing comment (if any) from *line*, respecting strings.

    >>> strip_comment('x = 1  # note')
    'x = 1  '
    >>> strip_comment('s = "has # inside"')
    's = "has # inside"'
    """
    offset = find_comment_offset(line)
    if offset is None:
        return line
    return line[:offset]


def split_trailing_comment(line: str) -> Tuple[str, Optional[str]]:
    """Split *line* into ``(code_part, comment)`` respecting strings.

    *comment* includes the leading ``#``.  Returns ``(line, None)`` when
    there is no trailing comment.

    >>> split_trailing_comment('x = 1  # note')
    ('x = 1  ', '# note')
    """
    offset = find_comment_offset(line)
    if offset is None:
        return line, None
    return line[:offset], line[offset:]


def strip_string_literals(line: str) -> str:
    """Replace all double-quoted string literals (including f-strings) with empty strings.

    Useful for analysing code tokens without being confused by string
    contents.

    >>> strip_string_literals('x = f"hello {name}"')
    'x = '
    """
    return _STRING_LITERAL_RE.sub('', line)


def extract_identifiers(line: str, *, exclude: Optional[Set[str]] = None) -> Set[str]:
    """Extract identifier tokens from *line* after removing strings and comments.

    Parameters
    ----------
    exclude : set[str], optional
        A set of keywords or builtins to subtract from the result.

    >>> sorted(extract_identifiers('x = foo(y)  # bar'))
    ['foo', 'x', 'y']
    """
    cleaned = strip_string_literals(strip_comment(line))
    ids = set(_IDENT_RE.findall(cleaned))
    if exclude:
        ids -= exclude
    return ids


def scan_segments(source: str):
    """Yield ``(kind, text, start, end)`` for each segment of *source*.

    Kinds: ``'string'``, ``'comment'``, ``'ident'``, ``'other'``.

    Correctly handles escape sequences inside strings and ``#``-comments.
    This is the canonical string/comment-aware scanner shared across
    sauravcode tooling (sauravmin, sauravfmt, sauravlint, etc.).

    >>> list(scan_segments('x = 1 # hi'))  # doctest: +NORMALIZE_WHITESPACE
    [('ident', 'x', 0, 1), ('other', ' ', 1, 2), ('other', '=', 2, 3),
     ('other', ' ', 3, 4), ('other', '1', 4, 5), ('other', ' ', 5, 6),
     ('comment', '# hi', 6, 10)]
    """
    i = 0
    n = len(source)
    while i < n:
        ch = source[i]

        # Comment — consumes until end of line
        if ch == '#':
            start = i
            while i < n and source[i] != '\n':
                i += 1
            yield ('comment', source[start:i], start, i)
            continue

        # String literal (single or double quote, with optional f-prefix)
        if ch in ('"', "'") or (ch == 'f' and i + 1 < n and source[i + 1] in ('"', "'")):
            start = i
            if ch == 'f':
                i += 1  # skip the 'f' prefix
            quote = source[i]
            i += 1
            while i < n:
                c = source[i]
                if c == '\\' and i + 1 < n:
                    i += 2
                    continue
                if c == quote:
                    i += 1
                    break
                i += 1
            yield ('string', source[start:i], start, i)
            continue

        # Identifier
        if ch.isalpha() or ch == '_':
            m = _IDENT_RE.match(source, i)
            if m:
                yield ('ident', m.group(0), i, m.end())
                i = m.end()
                continue

        # Everything else (one character at a time)
        yield ('other', ch, i, i + 1)
        i += 1
