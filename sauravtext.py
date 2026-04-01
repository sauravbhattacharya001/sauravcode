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
