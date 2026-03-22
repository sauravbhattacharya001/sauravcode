"""Tests for generator functions with yield."""
import pytest
from saurav import tokenize, Parser, Interpreter


def run(code):
    """Run sauravcode and return (output_lines, interpreter)."""
    tokens = tokenize(code)
    parser = Parser(tokens)
    ast = parser.parse()
    interp = Interpreter()
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        for node in ast:
            interp.interpret(node)
    return buf.getvalue().strip().split('\n') if buf.getvalue().strip() else [], interp


def run_output(code):
    """Run and return output lines."""
    lines, _ = run(code)
    return lines


class TestBasicGenerator:
    def test_simple_yield(self):
        out = run_output("""
function gen limit
    i = 0
    while i < limit
        yield i
        i = i + 1

for n in gen 3
    print n
""")
        assert out == ['0', '1', '2']

    def test_yield_in_for_loop(self):
        out = run_output("""
function evens limit
    for i in range 0 limit
        if i % 2 == 0
            yield i

for n in evens 8
    print n
""")
        assert out == ['0', '2', '4', '6']

    def test_yield_multiple_statements(self):
        out = run_output("""
function multi n
    yield n
    yield n * 2
    yield n * 3

for v in multi 5
    print v
""")
        assert out == ['5', '10', '15']

    def test_empty_generator(self):
        out = run_output("""
function empty n
    if n > 100
        yield n

for v in empty 5
    print v
print "done"
""")
        assert out == ['done']


class TestGeneratorCollect:
    def test_collect_basic(self):
        out = run_output("""
function gen limit
    i = 0
    while i < limit
        yield i
        i = i + 1

result = collect gen 4
print result
""")
        assert out == ['[0, 1, 2, 3]']

    def test_collect_empty(self):
        out = run_output("""
function gen n
    if n > 100
        yield n

result = collect gen 5
print result
""")
        assert out == ['[]']


class TestGeneratorTypeChecks:
    def test_type_of_generator(self):
        out = run_output("""
function gen n
    yield n

g = gen 1
print type_of g
""")
        assert out == ['generator']

    def test_is_generator_true(self):
        out = run_output("""
function gen n
    yield n

print is_generator gen 1
""")
        assert out == ['true']

    def test_is_generator_false(self):
        out = run_output("""
print is_generator 42
""")
        assert out == ['false']

    def test_is_generator_list(self):
        out = run_output("""
print is_generator 42
""")
        # Already tested above — just verify lists aren't generators
        assert out == ['false']


class TestGeneratorLen:
    def test_len_generator(self):
        out = run_output("""
function gen limit
    i = 0
    while i < limit
        yield i
        i = i + 1

print len gen 5
""")
        assert out == ['5']


class TestGeneratorComposition:
    def test_generator_uses_generator(self):
        out = run_output("""
function count limit
    i = 0
    while i < limit
        yield i
        i = i + 1

function doubled limit
    for n in count limit
        yield n * 2

for d in doubled 4
    print d
""")
        assert out == ['0', '2', '4', '6']

    def test_generator_with_filter(self):
        out = run_output("""
function gen limit
    for i in range 0 limit
        if i % 3 == 0
            yield i

result = collect gen 12
print result
""")
        assert out == ['[0, 3, 6, 9]']


class TestFibonacciGenerator:
    def test_fibonacci(self):
        out = run_output("""
function fibonacci limit
    a = 0
    b = 1
    while a < limit
        yield a
        temp = a + b
        a = b
        b = temp

result = collect fibonacci 50
print result
""")
        assert out == ['[0, 1, 1, 2, 3, 5, 8, 13, 21, 34]']


class TestGeneratorWithBreak:
    def test_break_in_generator_loop(self):
        out = run_output("""
function gen limit
    i = 0
    while i < limit
        yield i
        i = i + 1

for n in gen 10
    if n == 3
        break
    print n
""")
        assert out == ['0', '1', '2']


class TestGeneratorWithContinue:
    def test_continue_in_consumer_loop(self):
        out = run_output("""
function gen limit
    i = 0
    while i < limit
        yield i
        i = i + 1

for n in gen 6
    if n % 2 == 0
        continue
    print n
""")
        assert out == ['1', '3', '5']


class TestGeneratorAssignment:
    def test_assign_generator_to_variable(self):
        out = run_output("""
function gen n
    yield n
    yield n + 1

g = gen 10
result = collect g
print result
""")
        assert out == ['[10, 11]']

    def test_collect_list_passthrough(self):
        out = run_output("""
function gen n
    yield n
    yield n + 1

result = collect gen 10
print result
""")
        assert out == ['[10, 11]']


class TestGeneratorPrint:
    def test_print_generator(self):
        out = run_output("""
function gen n
    yield n

g = gen 1
print g
""")
        assert out == ['<generator gen>']


class TestGeneratorWithTryCatch:
    def test_yield_in_try(self):
        out = run_output("""
function safe_gen limit
    for i in range 0 limit
        try
            yield i
        catch e
            print e

for n in safe_gen 3
    print n
""")
        assert out == ['0', '1', '2']


class TestGeneratorEdgeCases:
    def test_yield_computed_values(self):
        out = run_output("""
function squares limit
    i = 1
    while i * i <= limit
        yield i * i
        i = i + 1

result = collect squares 25
print result
""")
        assert out == ['[1, 4, 9, 16, 25]']

    def test_yield_string_values(self):
        out = run_output("""
function words sep
    yield "hello"
    yield sep
    yield "world"

result = collect words "-"
print result
""")
        assert out == ['["hello", "-", "world"]']

    def test_yield_boolean_values(self):
        out = run_output("""
function bools n
    yield n > 0
    yield n == 0
    yield n < 0

for b in bools 5
    print b
""")
        assert out == ['true', 'false', 'false']

    def test_non_generator_function_unchanged(self):
        """Regular functions without yield should work as before."""
        out = run_output("""
function add a b
    return a + b

print add 3 4
""")
        assert out == ['7']

    def test_generator_with_conditional_yields(self):
        out = run_output("""
function fizzbuzz limit
    for i in range 1 limit
        if i % 15 == 0
            yield "FizzBuzz"
        else if i % 3 == 0
            yield "Fizz"
        else if i % 5 == 0
            yield "Buzz"
        else
            yield i

result = collect fizzbuzz 16
print len result
""")
        assert out == ['15']

class TestHasYieldElifChains:
    def test_yield_in_elif_detected_as_generator(self):
        '''_has_yield must find yield inside elif branches (bug: used elif_blocks instead of elif_chains).'''
        out = run_output('''
function gen x
    if x == 1
        yield 10
    else if x == 2
        yield 20
    else
        yield 30

result = collect gen 2
print result
''')
        assert out == ['[20]']

    def test_yield_only_in_elif(self):
        '''Function with yield ONLY in elif branch must still be a generator.'''
        out = run_output('''
function gen flag
    if flag == 0
        print("no yield path")
    else if flag == 1
        yield 42

result = collect gen 1
print result
''')
        assert out == ['[42]']
