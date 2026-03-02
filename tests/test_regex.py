"""Tests for regex builtins: regex_match, regex_find, regex_find_all, regex_replace, regex_split.

Note on escaping: sauravcode does NOT process escape sequences in regular strings
(only f-strings). So a backslash-d in sauravcode source becomes the literal regex
pattern. In Python test code, use r'...' raw strings for readability.
"""
import pytest
import sys
import os
import io
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from saurav import tokenize, Parser, Interpreter


def run(code):
    """Run sauravcode and return captured output lines."""
    tokens = tokenize(code)
    ast = Parser(tokens).parse()
    interp = Interpreter()
    f = io.StringIO()
    with redirect_stdout(f):
        for node in ast:
            interp.interpret(node)
    return f.getvalue().strip().split('\n') if f.getvalue().strip() else []


def run_val(code):
    """Run sauravcode and return last expression value."""
    tokens = tokenize(code)
    ast = Parser(tokens).parse()
    interp = Interpreter()
    result = None
    for node in ast:
        result = interp.interpret(node)
    return result


# --- regex_match ---

class TestRegexMatch:
    def test_full_match(self):
        assert run_val('regex_match "^hello$" "hello"') is True

    def test_no_match(self):
        assert run_val('regex_match "^hello$" "hello world"') is False

    def test_digit_pattern(self):
        assert run_val(r'regex_match "\d+" "12345"') is True

    def test_digit_pattern_no_match(self):
        assert run_val(r'regex_match "\d+" "abc"') is False

    def test_email_pattern(self):
        assert run_val(r'regex_match "[a-z]+@[a-z]+\.[a-z]+" "test@example.com"') is True

    def test_empty_string_empty_pattern(self):
        assert run_val('regex_match "" ""') is True

    def test_dot_star(self):
        assert run_val('regex_match ".*" "anything goes"') is True

    def test_fullmatch_not_search(self):
        assert run_val('regex_match "abc" "abcdef"') is False

    def test_character_class(self):
        assert run_val('regex_match "[A-Z][a-z]+" "Hello"') is True
        assert run_val('regex_match "[A-Z][a-z]+" "hello"') is False

    def test_result_in_if(self):
        out = run(r'''if regex_match "\d+" "42"
  print "yes"
else
  print "no"''')
        assert out == ['yes']

    def test_invalid_regex_raises(self):
        with pytest.raises(RuntimeError, match="invalid regex"):
            run_val('regex_match "[invalid" "test"')


# --- regex_find ---

class TestRegexFind:
    def test_find_match(self):
        result = run_val(r'regex_find "\d+" "abc 123 def"')
        assert result['match'] == '123'
        assert result['start'] == 4
        assert result['end'] == 7

    def test_no_match_returns_null(self):
        out = run(r'''x = regex_find "\d+" "no digits"
print x''')
        assert out == ['None']

    def test_groups(self):
        result = run_val(r'regex_find "(\w+)@(\w+)" "user@host"')
        assert result['match'] == 'user@host'
        assert result['groups'] == ['user', 'host']

    def test_no_groups(self):
        result = run_val(r'regex_find "\d+" "abc 42"')
        assert result['groups'] == []

    def test_map_access(self):
        out = run(r'''m = regex_find "\d+" "abc 99 xyz"
print m["match"]''')
        assert out == ['99']

    def test_start_end_access(self):
        out = run('''m = regex_find "world" "hello world"
print m["start"]
print m["end"]''')
        assert out == ['6', '11']

    def test_invalid_regex_raises(self):
        with pytest.raises(RuntimeError, match="invalid regex"):
            run_val('regex_find "[bad" "test"')


# --- regex_find_all ---

class TestRegexFindAll:
    def test_find_all_simple(self):
        result = run_val(r'regex_find_all "\d+" "a1 b22 c333"')
        assert result == ['1', '22', '333']

    def test_find_all_no_match(self):
        result = run_val(r'regex_find_all "\d+" "no digits here"')
        assert result == []

    def test_find_all_with_groups(self):
        result = run_val(r'regex_find_all "(\w+)=(\w+)" "a=1 b=2 c=3"')
        assert result == [['a', '1'], ['b', '2'], ['c', '3']]

    def test_find_all_words(self):
        result = run_val('regex_find_all "[A-Z][a-z]+" "Hello World Foo"')
        assert result == ['Hello', 'World', 'Foo']

    def test_find_all_len(self):
        out = run(r'''matches = regex_find_all "\d+" "1 22 333 4444"
print len matches''')
        assert out == ['4']

    def test_iteration_over_results(self):
        out = run('''words = regex_find_all "[a-z]+" "abc 123 def 456"
for w in words
  print w''')
        assert out == ['abc', 'def']

    def test_invalid_regex_raises(self):
        with pytest.raises(RuntimeError, match="invalid regex"):
            run_val('regex_find_all "[bad" "test"')


# --- regex_replace ---

class TestRegexReplace:
    def test_simple_replace(self):
        result = run_val(r'regex_replace "\d+" "NUM" "abc 123 def 456"')
        assert result == 'abc NUM def NUM'

    def test_no_match_unchanged(self):
        result = run_val(r'regex_replace "\d+" "X" "no digits"')
        assert result == 'no digits'

    def test_replace_whitespace(self):
        result = run_val(r'regex_replace "\s+" "-" "a b  c   d"')
        assert result == 'a-b-c-d'

    def test_remove_non_alpha(self):
        result = run_val('regex_replace "[^a-zA-Z ]" "" "hello! world? 123"')
        assert result == 'hello world '

    def test_replace_with_empty(self):
        result = run_val(r'regex_replace "\d" "" "a1b2c3"')
        assert result == 'abc'

    def test_literal_replacement(self):
        out = run('''result = regex_replace "cat" "dog" "I have a cat and a cat"
print result''')
        assert out == ['I have a dog and a dog']

    def test_invalid_regex_raises(self):
        with pytest.raises(RuntimeError, match="invalid regex"):
            run_val('regex_replace "[bad" "x" "test"')


# --- regex_split ---

class TestRegexSplit:
    def test_split_by_whitespace(self):
        result = run_val(r'regex_split "\s+" "hello   world   foo"')
        assert result == ['hello', 'world', 'foo']

    def test_split_by_comma_space(self):
        result = run_val(r'regex_split ",\s*" "a, b,c,  d"')
        assert result == ['a', 'b', 'c', 'd']

    def test_split_no_match(self):
        result = run_val(r'regex_split "\d+" "no digits"')
        assert result == ['no digits']

    def test_split_by_multiple_delims(self):
        result = run_val('regex_split "[;|]" "a;b|c;d"')
        assert result == ['a', 'b', 'c', 'd']

    def test_split_len(self):
        out = run(r'''parts = regex_split "\s+" "one two three"
print len parts''')
        assert out == ['3']

    def test_split_empty_between(self):
        result = run_val('regex_split "x" "xax"')
        assert result == ['', 'a', '']

    def test_invalid_regex_raises(self):
        with pytest.raises(RuntimeError, match="invalid regex"):
            run_val('regex_split "[bad" "test"')


# --- Type errors ---

class TestRegexTypeErrors:
    def test_match_non_string_pattern(self):
        with pytest.raises(RuntimeError, match="string pattern"):
            run_val('regex_match 42 "test"')

    def test_match_non_string_input(self):
        with pytest.raises(RuntimeError, match="string as second"):
            run_val('regex_match "abc" 42')

    def test_find_non_string_pattern(self):
        with pytest.raises(RuntimeError, match="string pattern"):
            run_val('regex_find 42 "test"')

    def test_find_non_string_input(self):
        with pytest.raises(RuntimeError, match="string as second"):
            run_val('regex_find "abc" 42')

    def test_find_all_non_string_pattern(self):
        with pytest.raises(RuntimeError, match="string pattern"):
            run_val('regex_find_all 42 "test"')

    def test_find_all_non_string_input(self):
        with pytest.raises(RuntimeError, match="string as second"):
            run_val('regex_find_all "abc" 42')

    def test_replace_non_string_pattern(self):
        with pytest.raises(RuntimeError, match="string pattern"):
            run_val('regex_replace 42 "x" "test"')

    def test_replace_non_string_replacement(self):
        with pytest.raises(RuntimeError, match="string replacement"):
            run_val('regex_replace "abc" 42 "test"')

    def test_replace_non_string_input(self):
        with pytest.raises(RuntimeError, match="string as third"):
            run_val('regex_replace "abc" "x" 42')

    def test_split_non_string_pattern(self):
        with pytest.raises(RuntimeError, match="string pattern"):
            run_val('regex_split 42 "test"')

    def test_split_non_string_input(self):
        with pytest.raises(RuntimeError, match="string as second"):
            run_val('regex_split "abc" 42')


# --- Integration / practical patterns ---

class TestRegexIntegration:
    def test_email_validation_with_filter(self):
        code = r'''emails = ["test@example.com", "bad-email", "user@domain.org", "nope"]
valid = filter (lambda e -> regex_match "[^@]+@[^@]+\.[^@]+" e) emails
print len valid'''
        out = run(code)
        assert out == ['2']

    def test_extract_numbers(self):
        code = r'''text = "Price: $42.99, Qty: 5, Total: $214.95"
nums = regex_find_all "\d+\.?\d*" text
print len nums
print nums[0]'''
        out = run(code)
        assert out == ['3', '42.99']

    def test_clean_whitespace(self):
        result = run_val(r'regex_replace "\s+" " " "  too   many    spaces  "')
        assert result == ' too many spaces '

    def test_parse_key_value_pairs(self):
        code = r'''pairs = regex_find_all "(\w+)=(\w+)" "name=Alice age=30 city=NYC"
print len pairs
print pairs[0][0]
print pairs[0][1]'''
        out = run(code)
        assert out == ['3', 'name', 'Alice']

    def test_csv_split(self):
        result = run_val(r'regex_split ",\s*" "apple, banana, cherry,  date"')
        assert result == ['apple', 'banana', 'cherry', 'date']

    def test_find_and_use_groups(self):
        code = r'''m = regex_find "(\d{4})-(\d{2})-(\d{2})" "Date: 2026-03-02"
print m["match"]
print m["groups"][0]
print m["groups"][1]
print m["groups"][2]'''
        out = run(code)
        assert out == ['2026-03-02', '2026', '03', '02']

    def test_word_count_with_regex(self):
        code = r'''words = regex_find_all "\b\w+\b" "Hello, world! How are you?"
print len words'''
        out = run(code)
        assert out == ['5']

    def test_chained_operations(self):
        code = r'''text = "Hello, World! 123"
cleaned = regex_replace "[^a-zA-Z\s]" "" text
words = regex_split "\s+" cleaned
print join " " words'''
        out = run(code)
        assert out == ['Hello World']

    def test_phone_number_formatting(self):
        code = r'''phone = "5551234567"
formatted = regex_replace "(\d{3})(\d{3})(\d{4})" "(\1) \2-\3" phone
print formatted'''
        out = run(code)
        assert out == ['(555) 123-4567']

    def test_simple_word_match(self):
        assert run_val('regex_match "[a-z]+" "hello"') is True
        assert run_val('regex_match "[a-z]+" "HELLO"') is False

    def test_find_returns_none_on_miss(self):
        result = run_val('regex_find "xyz" "no match here"')
        assert result is None


# --- Arity errors ---

class TestRegexArity:
    def test_match_too_few(self):
        with pytest.raises(RuntimeError, match="expects 2"):
            run_val('regex_match "abc"')

    def test_find_too_few(self):
        with pytest.raises(RuntimeError, match="expects 2"):
            run_val('regex_find "abc"')

    def test_find_all_too_few(self):
        with pytest.raises(RuntimeError, match="expects 2"):
            run_val('regex_find_all "abc"')

    def test_replace_too_few(self):
        with pytest.raises(RuntimeError, match="expects 3"):
            run_val('regex_replace "abc" "def"')

    def test_split_too_few(self):
        with pytest.raises(RuntimeError, match="expects 2"):
            run_val('regex_split "abc"')
