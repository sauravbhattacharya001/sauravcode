"""Tests for the sauravtext shared text-processing utilities."""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sauravtext import (
    find_comment_offset,
    strip_comment,
    split_trailing_comment,
    strip_string_literals,
    extract_identifiers,
)


def test_find_comment_offset_simple():
    assert find_comment_offset('x = 1  # note') == 7


def test_find_comment_offset_in_string():
    assert find_comment_offset('s = "has # inside"') is None


def test_find_comment_offset_after_string():
    assert find_comment_offset('s = "ok"  # comment') == 10


def test_find_comment_offset_no_comment():
    assert find_comment_offset('x = 1') is None


def test_find_comment_offset_escaped_quote():
    assert find_comment_offset(r's = "esc\"d"  # yes') is not None


def test_strip_comment():
    assert strip_comment('x = 1  # note') == 'x = 1  '
    assert strip_comment('s = "has # inside"') == 's = "has # inside"'
    assert strip_comment('no comment') == 'no comment'


def test_split_trailing_comment():
    code, comment = split_trailing_comment('x = 1  # note')
    assert code == 'x = 1  '
    assert comment == '# note'

    code, comment = split_trailing_comment('s = "has # inside"')
    assert code == 's = "has # inside"'
    assert comment is None


def test_strip_string_literals():
    assert strip_string_literals('x = "hello"') == 'x = '
    assert strip_string_literals('x = f"hello {name}"') == 'x = '
    assert strip_string_literals('no strings') == 'no strings'


def test_extract_identifiers():
    ids = extract_identifiers('x = foo(y)  # bar')
    assert ids == {'x', 'foo', 'y'}


def test_extract_identifiers_with_exclude():
    ids = extract_identifiers('if x and y', exclude={'if', 'and'})
    assert ids == {'x', 'y'}


def test_extract_identifiers_ignores_strings():
    ids = extract_identifiers('x = "hello world"')
    assert 'hello' not in ids
    assert 'world' not in ids
    assert 'x' in ids


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print(f'  PASS {name}')
    print('All tests passed.')
