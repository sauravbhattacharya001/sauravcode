"""Tests for slice operations, assert statements, and expression edge cases in SauravCode.

Covers:
- List slicing: [start:end], [:end], [start:], [:]
- String slicing
- Negative indices in slices
- Slice in expressions (assignment, len, nested)
- Assert statement (pass and fail)
- Edge cases: empty slices, out-of-range, type errors
"""
import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from saurav import tokenize, Parser, Interpreter


def run(code):
    """Helper to run SauravCode and capture output."""
    import io
    from contextlib import redirect_stdout
    tokens = tokenize(code)
    parser = Parser(tokens)
    ast = parser.parse()
    interp = Interpreter()
    buf = io.StringIO()
    with redirect_stdout(buf):
        for node in ast:
            interp.interpret(node)
    return buf.getvalue().strip()


def eval_expr(code):
    """Run code that ends with a print and return the printed value."""
    return run(code)


# ══════════════════════════════════════════════════════════════
# List Slicing
# ══════════════════════════════════════════════════════════════

class TestListSlicing:
    def test_slice_start_end(self):
        assert eval_expr('nums = [10, 20, 30, 40, 50]\nprint nums[1:3]') == '[20, 30]'

    def test_slice_from_start(self):
        assert eval_expr('nums = [10, 20, 30, 40, 50]\nprint nums[:2]') == '[10, 20]'

    def test_slice_to_end(self):
        assert eval_expr('nums = [10, 20, 30, 40, 50]\nprint nums[3:]') == '[40, 50]'

    def test_slice_full_copy(self):
        assert eval_expr('nums = [10, 20, 30, 40, 50]\nprint nums[:]') == '[10, 20, 30, 40, 50]'

    def test_slice_single_element_range(self):
        assert eval_expr('nums = [10, 20, 30]\nprint nums[1:2]') == '[20]'

    def test_slice_empty_range(self):
        assert eval_expr('nums = [10, 20, 30]\nprint nums[2:2]') == '[]'

    def test_slice_negative_start(self):
        assert eval_expr('nums = [10, 20, 30, 40, 50]\nprint nums[-2:]') == '[40, 50]'

    def test_slice_negative_end(self):
        assert eval_expr('nums = [10, 20, 30, 40, 50]\nprint nums[:-1]') == '[10, 20, 30, 40]'

    def test_slice_both_negative(self):
        assert eval_expr('nums = [10, 20, 30, 40, 50]\nprint nums[-3:-1]') == '[30, 40]'

    def test_slice_beyond_length(self):
        # Python-style: slicing beyond bounds doesn't error
        assert eval_expr('nums = [10, 20, 30]\nprint nums[0:100]') == '[10, 20, 30]'

    def test_slice_empty_list(self):
        assert eval_expr('nums = []\nprint nums[:]') == '[]'

    def test_slice_in_assignment(self):
        out = eval_expr('nums = [10, 20, 30, 40, 50]\nfirst = nums[:3]\nprint first')
        assert out == '[10, 20, 30]'

    def test_slice_with_len(self):
        out = eval_expr('nums = [10, 20, 30, 40, 50]\nprint len (nums[1:4])')
        assert out == '3'

    def test_slice_preserves_original(self):
        """Slicing should not modify the original list."""
        out = eval_expr('''nums = [10, 20, 30]
part = nums[:2]
append part 99
print nums
print part''')
        lines = out.split('\n')
        assert lines[0] == '[10, 20, 30]'
        assert lines[1] == '[10, 20, 99]'

    def test_slice_of_slice(self):
        out = eval_expr('nums = [10, 20, 30, 40, 50]\nprint nums[1:4][0:2]')
        assert out == '[20, 30]'


# ══════════════════════════════════════════════════════════════
# String Slicing
# ══════════════════════════════════════════════════════════════

class TestStringSlicing:
    def test_string_slice_start_end(self):
        assert eval_expr('text = "Hello World"\nprint text[0:5]') == 'Hello'

    def test_string_slice_from_start(self):
        assert eval_expr('text = "Hello World"\nprint text[:5]') == 'Hello'

    def test_string_slice_to_end(self):
        assert eval_expr('text = "Hello World"\nprint text[6:]') == 'World'

    def test_string_slice_full_copy(self):
        assert eval_expr('text = "Hello"\nprint text[:]') == 'Hello'

    def test_string_slice_negative(self):
        assert eval_expr('text = "Hello World"\nprint text[-5:]') == 'World'

    def test_string_slice_single_char(self):
        assert eval_expr('text = "abc"\nprint text[1:2]') == 'b'

    def test_string_slice_empty(self):
        assert eval_expr('text = "abc"\nprint text[1:1]') == ''

    def test_string_slice_in_assignment(self):
        out = eval_expr('text = "Hello World"\nfirst = text[:5]\nprint first')
        assert out == 'Hello'


# ══════════════════════════════════════════════════════════════
# Slice Error Cases
# ══════════════════════════════════════════════════════════════

class TestSliceErrors:
    def test_slice_on_number_raises(self):
        with pytest.raises(RuntimeError, match="Cannot slice"):
            run('x = 42\nprint x[0:1]')

    def test_slice_on_bool_raises(self):
        with pytest.raises(RuntimeError, match="Cannot slice"):
            run('x = true\nprint x[0:1]')


# ══════════════════════════════════════════════════════════════
# Assert Statement
# ══════════════════════════════════════════════════════════════

class TestAssertStatement:
    def test_assert_true_passes(self):
        # Should not raise
        run('assert true')

    def test_assert_truthy_number(self):
        run('assert 1')

    def test_assert_expression(self):
        run('x = 10\nassert x > 5')

    def test_assert_equality(self):
        run('assert 2 + 3 == 5')

    def test_assert_false_raises(self):
        with pytest.raises((AssertionError, RuntimeError)):
            run('assert false')

    def test_assert_zero_raises(self):
        with pytest.raises((AssertionError, RuntimeError)):
            run('assert 0')

    def test_assert_failed_comparison(self):
        with pytest.raises((AssertionError, RuntimeError)):
            run('assert 3 > 5')

    def test_assert_with_message(self):
        """Assert with a descriptive message (if supported)."""
        run('assert 1 == 1')

    def test_assert_after_computation(self):
        run('''x = 10
y = 20
z = x + y
assert z == 30''')


# ══════════════════════════════════════════════════════════════
# Break and Continue
# ══════════════════════════════════════════════════════════════

class TestBreakContinue:
    def test_break_in_while(self):
        out = eval_expr('''i = 0
while i < 10
    if i == 3
        break
    print i
    i = i + 1''')
        assert out == '0\n1\n2'

    def test_continue_in_while(self):
        out = eval_expr('''i = 0
while i < 5
    i = i + 1
    if i == 3
        continue
    print i''')
        lines = out.split('\n')
        assert '3' not in lines
        assert '1' in lines
        assert '2' in lines

    def test_break_in_for(self):
        out = eval_expr('''for i 0 10
    if i == 4
        break
    print i''')
        assert out == '0\n1\n2\n3'

    def test_continue_in_for(self):
        out = eval_expr('''for i 0 5
    if i == 2
        continue
    print i''')
        lines = out.split('\n')
        assert '2' not in lines

    def test_break_in_foreach(self):
        out = eval_expr('''items = [10, 20, 30, 40, 50]
for item in items
    if item == 30
        break
    print item''')
        assert out == '10\n20'

    def test_continue_in_foreach(self):
        out = eval_expr('''items = [10, 20, 30, 40, 50]
for item in items
    if item == 30
        continue
    print item''')
        assert out == '10\n20\n40\n50'


# ══════════════════════════════════════════════════════════════
# Ternary Expressions
# ══════════════════════════════════════════════════════════════

class TestTernaryExpressions:
    def test_basic_ternary(self):
        assert eval_expr('x = 10\nresult = "big" if x > 5 else "small"\nprint result') == 'big'

    def test_ternary_false_branch(self):
        assert eval_expr('x = 3\nresult = "big" if x > 5 else "small"\nprint result') == 'small'

    def test_ternary_in_print(self):
        assert eval_expr('x = 10\nprint "yes" if x > 5 else "no"') == 'yes'

    def test_ternary_with_numbers(self):
        assert eval_expr('x = 7\nresult = x * 2 if x > 5 else x + 1\nprint result') == '14'

    def test_nested_ternary(self):
        out = eval_expr('''x = 5
result = "high" if x > 10 else "mid" if x > 3 else "low"
print result''')
        assert out == 'mid'


# ══════════════════════════════════════════════════════════════
# Lambda Functions
# ══════════════════════════════════════════════════════════════

class TestLambdaFunctions:
    def test_lambda_with_map(self):
        out = eval_expr('''nums = [1, 2, 3]
doubled = map (lambda x -> x * 2) nums
print doubled''')
        assert out == '[2, 4, 6]'

    def test_lambda_with_filter(self):
        out = eval_expr('''nums = [1, 2, 3, 4, 5, 6]
evens = filter (lambda x -> x % 2 == 0) nums
print evens''')
        assert out == '[2, 4, 6]'

    def test_lambda_pipe(self):
        out = eval_expr('''result = 5 |> lambda x -> x * 2
print result''')
        assert out == '10'

    def test_lambda_no_params(self):
        out = eval_expr('''f = lambda -> 42
print f''')
        # Lambda with no params should be stored as a value
        # This tests the parser doesn't crash


# ══════════════════════════════════════════════════════════════
# Try/Catch Edge Cases
# ══════════════════════════════════════════════════════════════

class TestTryCatchEdgeCases:
    def test_try_no_error(self):
        out = eval_expr('''try
    x = 10
    print x
catch e
    print "error"''')
        assert out == '10'

    def test_try_catches_runtime_error(self):
        out = eval_expr('''try
    x = 1 / 0
catch e
    print "caught"''')
        assert out == 'caught'

    def test_throw_custom_message(self):
        out = eval_expr('''try
    throw "custom error"
catch e
    print e''')
        assert out == 'custom error'

    def test_nested_try_catch(self):
        out = eval_expr('''try
    try
        throw "inner"
    catch e
        print e
    print "outer ok"
catch e
    print "outer caught"''')
        lines = out.split('\n')
        assert lines[0] == 'inner'
        assert lines[1] == 'outer ok'

    def test_throw_number(self):
        out = eval_expr('''try
    throw 42
catch e
    print e''')
        assert out == '42'


# ══════════════════════════════════════════════════════════════
# Comprehension Filters (regression for fixed bug)
# ══════════════════════════════════════════════════════════════

class TestComprehensionFilterRegression:
    """Regression tests for the fix where 'if' in comprehension
    filter was incorrectly consumed by the ternary parser."""

    def test_filter_with_comparison(self):
        out = eval_expr('''nums = [1, 2, 3, 4, 5, 6]
evens = [x for x in nums if x % 2 == 0]
print evens''')
        assert out == '[2, 4, 6]'

    def test_filter_with_simple_variable(self):
        """Iterable is a simple identifier, filter follows."""
        out = eval_expr('''items = [1, 2, 3, 4, 5]
big = [x for x in items if x > 3]
print big''')
        assert out == '[4, 5]'

    def test_filter_with_transform_and_filter(self):
        out = eval_expr('''nums = [1, 2, 3, 4, 5]
doubled = [x * 2 for x in nums if x > 2]
print doubled''')
        assert out == '[6, 8, 10]'

    def test_no_filter_still_works(self):
        out = eval_expr('''nums = [1, 2, 3]
squares = [x * x for x in nums]
print squares''')
        assert out == '[1, 4, 9]'

    def test_filter_none_pass(self):
        out = eval_expr('''nums = [1, 2, 3]
empty = [x for x in nums if x > 100]
print empty''')
        assert out == '[]'

    def test_filter_all_pass(self):
        out = eval_expr('''nums = [10, 20, 30]
all = [x for x in nums if x > 0]
print all''')
        assert out == '[10, 20, 30]'


# ══════════════════════════════════════════════════════════════
# Map Operations
# ══════════════════════════════════════════════════════════════

class TestMapOperations:
    def test_map_literal(self):
        out = eval_expr('''m = {"a": 1, "b": 2}
print m["a"]''')
        assert out == '1'

    def test_map_assignment(self):
        out = eval_expr('''m = {"x": 10}
m["y"] = 20
print m["y"]''')
        assert out == '20'

    def test_map_len(self):
        out = eval_expr('''m = {"a": 1, "b": 2, "c": 3}
print len m''')
        assert out == '3'

    def test_map_overwrite(self):
        out = eval_expr('''m = {"key": "old"}
m["key"] = "new"
print m["key"]''')
        assert out == 'new'

    def test_empty_map(self):
        out = eval_expr('''m = {}
print len m''')
        assert out == '0'

    def test_map_numeric_values(self):
        out = eval_expr('''m = {"x": 3.14}
print m["x"]''')
        assert out == '3.14'


# ══════════════════════════════════════════════════════════════
# F-String Expressions
# ══════════════════════════════════════════════════════════════

class TestFStrings:
    def test_basic_fstring(self):
        out = eval_expr('''name = "world"
print f"hello {name}"''')
        assert out == 'hello world'

    def test_fstring_with_expression(self):
        out = eval_expr('''x = 5
print f"result is {x + 3}"''')
        assert out == 'result is 8'

    def test_fstring_multiple_interpolations(self):
        out = eval_expr('''a = 1
b = 2
print f"{a} + {b} = {a + b}"''')
        assert out == '1 + 2 = 3'

    def test_fstring_no_interpolation(self):
        out = eval_expr('print f"plain text"')
        assert out == 'plain text'

    def test_fstring_with_string_var(self):
        out = eval_expr('''name = "Alice"
greeting = f"Hi {name}!"
print greeting''')
        assert out == 'Hi Alice!'
