"""
Comprehensive tests for the sauravcode interpreter (saurav.py).

Tests tokenizer, parser, and interpreter with coverage for all
language features: arithmetic, functions, control flow, lists,
strings, booleans, logical operators, error handling, and edge cases.
"""

import pytest
import sys
import os
import io
from contextlib import redirect_stdout

# Add repo root to path so we can import saurav
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from saurav import (
    tokenize,
    Parser,
    Interpreter,
    ReturnSignal,
    NumberNode,
    StringNode,
    BoolNode,
    IdentifierNode,
    BinaryOpNode,
    UnaryOpNode,
    CompareNode,
    LogicalNode,
    format_value,
    _repl_execute,
    FunctionNode,
    FunctionCallNode,
    AssignmentNode,
    PrintNode,
    ReturnNode,
    IfNode,
    WhileNode,
    ForNode,
    ListNode,
    IndexNode,
    AppendNode,
    LenNode,
    ASTNode,
)


# ============================================================
# Helpers
# ============================================================

def run_code(code: str) -> str:
    """Tokenize, parse, interpret sauravcode and capture stdout."""
    tokens = list(tokenize(code))
    parser = Parser(tokens)
    ast_nodes = parser.parse()
    interpreter = Interpreter()

    buf = io.StringIO()
    with redirect_stdout(buf):
        for node in ast_nodes:
            if isinstance(node, FunctionNode):
                interpreter.interpret(node)
            elif isinstance(node, FunctionCallNode):
                result = interpreter.execute_function(node)
            else:
                interpreter.interpret(node)
    return buf.getvalue()


def run_code_result(code: str):
    """Run code and return the interpreter's last result (for function calls)."""
    tokens = list(tokenize(code))
    parser = Parser(tokens)
    ast_nodes = parser.parse()
    interpreter = Interpreter()

    result = None
    for node in ast_nodes:
        if isinstance(node, FunctionNode):
            interpreter.interpret(node)
        elif isinstance(node, FunctionCallNode):
            result = interpreter.execute_function(node)
        else:
            interpreter.interpret(node)
    return result


# ============================================================
# Tokenizer Tests
# ============================================================

class TestTokenizer:
    def test_number_tokens(self):
        tokens = list(tokenize("42\n"))
        number_tokens = [t for t in tokens if t[0] == "NUMBER"]
        assert len(number_tokens) == 1
        assert number_tokens[0][1] == "42"

    def test_float_tokens(self):
        tokens = list(tokenize("3.14\n"))
        number_tokens = [t for t in tokens if t[0] == "NUMBER"]
        assert number_tokens[0][1] == "3.14"

    def test_string_tokens(self):
        tokens = list(tokenize('"hello"\n'))
        string_tokens = [t for t in tokens if t[0] == "STRING"]
        assert len(string_tokens) == 1
        assert string_tokens[0][1] == '"hello"'

    def test_operator_tokens(self):
        tokens = list(tokenize("+ - * / %\n"))
        op_tokens = [t for t in tokens if t[0] == "OP"]
        assert len(op_tokens) == 5
        assert [t[1] for t in op_tokens] == ["+", "-", "*", "/", "%"]

    def test_comparison_tokens(self):
        tokens = list(tokenize("== != < > <= >=\n"))
        types = [t[0] for t in tokens if t[0] not in ("NEWLINE", "SKIP")]
        assert types == ["EQ", "NEQ", "LT", "GT", "LTE", "GTE"]

    def test_keyword_tokens(self):
        tokens = list(tokenize("if else while for function return print true false and or not\n"))
        kw_tokens = [t for t in tokens if t[0] == "KEYWORD"]
        assert len(kw_tokens) >= 10

    def test_indent_dedent(self):
        code = "if true\n    x = 1\nx = 2\n"
        tokens = list(tokenize(code))
        types = [t[0] for t in tokens]
        assert "INDENT" in types
        assert "DEDENT" in types

    def test_comment_token(self):
        tokens = list(tokenize("# this is a comment\n"))
        comment_tokens = [t for t in tokens if t[0] == "COMMENT"]
        assert len(comment_tokens) == 1

    def test_mismatch_raises(self):
        with pytest.raises(RuntimeError, match="Unexpected character"):
            list(tokenize("@\n"))

    def test_assign_token(self):
        tokens = list(tokenize("x = 5\n"))
        types = [t[0] for t in tokens if t[0] not in ("NEWLINE",)]
        assert "IDENT" in types
        assert "ASSIGN" in types
        assert "NUMBER" in types

    def test_brackets(self):
        tokens = list(tokenize("[1, 2]\n"))
        types = [t[0] for t in tokens if t[0] != "NEWLINE"]
        assert "LBRACKET" in types
        assert "RBRACKET" in types
        assert "COMMA" in types

    def test_parens(self):
        tokens = list(tokenize("(1 + 2)\n"))
        types = [t[0] for t in tokens if t[0] != "NEWLINE"]
        assert "LPAREN" in types
        assert "RPAREN" in types

    def test_multiple_dedents_at_eof(self):
        code = "if true\n    if true\n        x = 1\n"
        tokens = list(tokenize(code))
        dedent_count = sum(1 for t in tokens if t[0] == "DEDENT")
        assert dedent_count >= 2


# ============================================================
# Parser Tests
# ============================================================

class TestParser:
    def test_parse_assignment(self):
        tokens = list(tokenize("x = 42\n"))
        parser = Parser(tokens)
        ast = parser.parse()
        assignments = [n for n in ast if isinstance(n, AssignmentNode)]
        assert len(assignments) == 1
        assert assignments[0].name == "x"

    def test_parse_print(self):
        tokens = list(tokenize('print "hello"\n'))
        parser = Parser(tokens)
        ast = parser.parse()
        prints = [n for n in ast if isinstance(n, PrintNode)]
        assert len(prints) == 1

    def test_parse_function(self):
        code = "function add x y\n    return x + y\n"
        tokens = list(tokenize(code))
        parser = Parser(tokens)
        ast = parser.parse()
        funcs = [n for n in ast if isinstance(n, FunctionNode)]
        assert len(funcs) == 1
        assert funcs[0].name == "add"
        assert funcs[0].params == ["x", "y"]

    def test_parse_if(self):
        code = "if true\n    x = 1\n"
        tokens = list(tokenize(code))
        parser = Parser(tokens)
        ast = parser.parse()
        ifs = [n for n in ast if isinstance(n, IfNode)]
        assert len(ifs) == 1

    def test_parse_while(self):
        code = "while true\n    x = 1\n"
        tokens = list(tokenize(code))
        parser = Parser(tokens)
        ast = parser.parse()
        whiles = [n for n in ast if isinstance(n, WhileNode)]
        assert len(whiles) == 1

    def test_parse_for(self):
        code = "for i 0 10\n    print i\n"
        tokens = list(tokenize(code))
        parser = Parser(tokens)
        ast = parser.parse()
        fors = [n for n in ast if isinstance(n, ForNode)]
        assert len(fors) == 1
        assert fors[0].var == "i"

    def test_parse_list_literal(self):
        tokens = list(tokenize("x = [1, 2, 3]\n"))
        parser = Parser(tokens)
        ast = parser.parse()
        assignments = [n for n in ast if isinstance(n, AssignmentNode)]
        assert len(assignments) == 1
        assert isinstance(assignments[0].expression, ListNode)

    def test_parse_function_call(self):
        code = "function f x\n    return x\nf 5\n"
        tokens = list(tokenize(code))
        parser = Parser(tokens)
        ast = parser.parse()
        calls = [n for n in ast if isinstance(n, FunctionCallNode)]
        assert len(calls) == 1
        assert calls[0].name == "f"

    def test_parse_binary_expression(self):
        tokens = list(tokenize("x = 3 + 4 * 2\n"))
        parser = Parser(tokens)
        ast = parser.parse()
        assign = [n for n in ast if isinstance(n, AssignmentNode)][0]
        # The expression should be a BinaryOpNode
        assert isinstance(assign.expression, BinaryOpNode)

    def test_parse_unexpected_token_raises(self):
        tokens = [("MISMATCH", "@", 1, 0)]
        parser = Parser(tokens)
        with pytest.raises(SyntaxError):
            parser.parse()


# ============================================================
# Interpreter Tests — Arithmetic
# ============================================================

class TestArithmetic:
    def test_addition(self):
        output = run_code("print 3 + 5\n")
        assert output.strip() == "8"

    def test_subtraction(self):
        output = run_code("print 10 - 3\n")
        assert output.strip() == "7"

    def test_multiplication(self):
        output = run_code("print 4 * 6\n")
        assert output.strip() == "24"

    def test_division(self):
        output = run_code("print 10 / 4\n")
        assert output.strip() == "2.5"

    def test_modulo(self):
        output = run_code("print 15 % 4\n")
        assert output.strip() == "3"

    def test_division_by_zero(self):
        with pytest.raises(RuntimeError, match="Division by zero"):
            run_code("print 1 / 0\n")

    def test_modulo_by_zero(self):
        with pytest.raises(RuntimeError, match="Modulo by zero"):
            run_code("print 1 % 0\n")

    def test_negative_numbers(self):
        output = run_code("x = -42\nprint x\n")
        assert output.strip() == "-42"

    def test_parenthesized_expression(self):
        output = run_code("print (2 + 3) * 4\n")
        assert output.strip() == "20"

    def test_nested_arithmetic(self):
        output = run_code("print (2 + 3) * (4 - 1)\n")
        assert output.strip() == "15"

    def test_operator_precedence(self):
        # Multiplication before addition
        output = run_code("print 2 + 3 * 4\n")
        assert output.strip() == "14"


# ============================================================
# Interpreter Tests — Variables
# ============================================================

class TestVariables:
    def test_assignment_and_print(self):
        output = run_code("x = 10\nprint x\n")
        assert output.strip() == "10"

    def test_reassignment(self):
        output = run_code("x = 5\nx = 10\nprint x\n")
        assert output.strip() == "10"

    def test_variable_in_expression(self):
        output = run_code("x = 3\ny = 7\nprint x + y\n")
        assert output.strip() == "10"

    def test_undefined_variable_raises(self):
        with pytest.raises(RuntimeError, match="not defined"):
            run_code("print z\n")


# ============================================================
# Interpreter Tests — Functions
# ============================================================

class TestFunctions:
    def test_simple_function(self):
        code = "function add x y\n    return x + y\nprint add 3 5\n"
        output = run_code(code)
        assert output.strip() == "8"

    def test_nested_function_call(self):
        code = """function square x
    return x * x

function hypotenuse a b
    sa = square a
    sb = square b
    return sa + sb

print hypotenuse 3 4
"""
        output = run_code(code)
        assert output.strip() == "25"

    def test_recursion(self):
        code = """function factorial n
    if n <= 1
        return 1
    return n * factorial (n - 1)

print factorial 5
"""
        output = run_code(code)
        assert output.strip() == "120"

    def test_function_with_print(self):
        code = """function greet name
    print name
    return 0

greet "hello"
"""
        output = run_code(code)
        assert output.strip() == "hello"

    def test_undefined_function_raises(self):
        with pytest.raises(RuntimeError, match="not defined"):
            run_code("nonexistent 5\n")

    def test_fibonacci(self):
        code = """function fib n
    if n <= 1
        return n
    return fib (n - 1) + fib (n - 2)

print fib 10
"""
        output = run_code(code)
        assert output.strip() == "55"

    def test_function_scope_isolation(self):
        """Function vars shouldn't leak to outer scope."""
        code = """x = 100
function f a
    x = 999
    return x

f 0
print x
"""
        output = run_code(code)
        assert output.strip() == "100"


# ============================================================
# Interpreter Tests — Control Flow
# ============================================================

class TestControlFlow:
    def test_if_true(self):
        output = run_code("if true\n    print 1\n")
        assert output.strip() == "1"

    def test_if_false(self):
        output = run_code("if false\n    print 1\n")
        assert output.strip() == ""

    def test_if_else(self):
        code = "if false\n    print 1\nelse\n    print 2\n"
        output = run_code(code)
        assert output.strip() == "2"

    def test_if_elif_else(self):
        code = """score = 85
if score >= 90
    print "A"
else if score >= 80
    print "B"
else
    print "C"
"""
        output = run_code(code)
        assert output.strip() == "B"

    def test_while_loop(self):
        code = """counter = 0
while counter < 3
    print counter
    counter = counter + 1
"""
        output = run_code(code)
        assert output.strip() == "0\n1\n2"

    def test_for_loop(self):
        code = """for i 1 4
    print i
"""
        output = run_code(code)
        assert output.strip() == "1\n2\n3"

    def test_nested_if(self):
        code = """x = 5
if x > 0
    if x < 10
        print "single digit positive"
"""
        output = run_code(code)
        assert output.strip() == "single digit positive"


# ============================================================
# Interpreter Tests — Comparisons
# ============================================================

class TestComparisons:
    def test_equality(self):
        output = run_code("if 5 == 5\n    print 1\n")
        assert output.strip() == "1"

    def test_inequality(self):
        output = run_code("if 5 != 3\n    print 1\n")
        assert output.strip() == "1"

    def test_less_than(self):
        output = run_code("if 3 < 5\n    print 1\n")
        assert output.strip() == "1"

    def test_greater_than(self):
        output = run_code("if 5 > 3\n    print 1\n")
        assert output.strip() == "1"

    def test_less_than_or_equal(self):
        output = run_code("if 5 <= 5\n    print 1\n")
        assert output.strip() == "1"

    def test_greater_than_or_equal(self):
        output = run_code("if 5 >= 5\n    print 1\n")
        assert output.strip() == "1"


# ============================================================
# Interpreter Tests — Logical Operators
# ============================================================

class TestLogicalOperators:
    def test_and_true(self):
        output = run_code("if true and true\n    print 1\n")
        assert output.strip() == "1"

    def test_and_false(self):
        output = run_code("if true and false\n    print 1\n")
        assert output.strip() == ""

    def test_or_true(self):
        output = run_code("if false or true\n    print 1\n")
        assert output.strip() == "1"

    def test_or_false(self):
        output = run_code("if false or false\n    print 1\n")
        assert output.strip() == ""

    def test_not(self):
        output = run_code("if not false\n    print 1\n")
        assert output.strip() == "1"

    def test_combined_logical(self):
        output = run_code("if true and not false\n    print 1\n")
        assert output.strip() == "1"


# ============================================================
# Interpreter Tests — Strings
# ============================================================

class TestStrings:
    def test_string_print(self):
        output = run_code('print "hello world"\n')
        assert output.strip() == "hello world"

    def test_string_variable(self):
        output = run_code('x = "test"\nprint x\n')
        assert output.strip() == "test"

    def test_string_concatenation(self):
        output = run_code('print "hello" + " world"\n')
        assert output.strip() == "hello world"


# ============================================================
# Interpreter Tests — Booleans
# ============================================================

class TestBooleans:
    def test_true_print(self):
        output = run_code("print true\n")
        assert output.strip() == "true"

    def test_false_print(self):
        output = run_code("print false\n")
        assert output.strip() == "false"

    def test_bool_variable(self):
        output = run_code("x = true\nprint x\n")
        assert output.strip() == "true"


# ============================================================
# Interpreter Tests — Lists
# ============================================================

class TestLists:
    def test_list_creation(self):
        output = run_code("nums = [10, 20, 30]\nprint nums[0]\n")
        assert output.strip() == "10"

    def test_list_index(self):
        output = run_code("nums = [10, 20, 30]\nprint nums[2]\n")
        assert output.strip() == "30"

    def test_list_len(self):
        output = run_code("nums = [10, 20, 30]\nprint len nums\n")
        assert output.strip() == "3"

    def test_list_append(self):
        code = """nums = [10, 20]
append nums 30
print len nums
print nums[2]
"""
        output = run_code(code)
        lines = output.strip().split("\n")
        assert lines[0] == "3"
        assert lines[1] == "30"

    def test_list_out_of_bounds(self):
        with pytest.raises(RuntimeError, match="out of bounds"):
            run_code("nums = [1, 2]\nprint nums[5]\n")

    def test_append_to_non_list_raises(self):
        with pytest.raises(RuntimeError, match="not a list"):
            run_code("x = 5\nappend x 10\n")

    def test_empty_list(self):
        output = run_code("nums = []\nprint len nums\n")
        assert output.strip() == "0"

    def test_len_of_string(self):
        output = run_code('print len "hello"\n')
        assert output.strip() == "5"


# ============================================================
# Interpreter Tests — Print Formatting
# ============================================================

class TestPrintFormatting:
    def test_integer_no_decimal(self):
        """Integers should print without .0"""
        output = run_code("print 42\n")
        assert output.strip() == "42"

    def test_float_with_decimal(self):
        output = run_code("print 3.5\n")
        assert output.strip() == "3.5"

    def test_expression_result_integer(self):
        output = run_code("print 6 / 2\n")
        assert output.strip() == "3"


# ============================================================
# Interpreter Tests — Truthiness
# ============================================================

class TestTruthiness:
    def test_zero_is_falsy(self):
        output = run_code("if 0\n    print 1\n")
        assert output.strip() == ""

    def test_nonzero_is_truthy(self):
        output = run_code("if 42\n    print 1\n")
        assert output.strip() == "1"

    def test_empty_string_is_falsy(self):
        output = run_code('if ""\n    print 1\n')
        assert output.strip() == ""

    def test_nonempty_string_is_truthy(self):
        output = run_code('if "x"\n    print 1\n')
        assert output.strip() == "1"


# ============================================================
# Interpreter Tests — Edge Cases & Error Handling
# ============================================================

class TestEdgeCases:
    def test_return_signal(self):
        """ReturnSignal should carry a value."""
        sig = ReturnSignal(42)
        assert sig.value == 42

    def test_ast_node_repr(self):
        """AST nodes should have useful repr."""
        node = NumberNode(42.0)
        assert "42" in repr(node)
        node = StringNode("hello")
        assert "hello" in repr(node)

    def test_comments_ignored(self):
        output = run_code("# this is a comment\nprint 1\n")
        assert output.strip() == "1"

    def test_empty_program(self):
        output = run_code("\n")
        assert output.strip() == ""

    def test_multiple_statements(self):
        code = "print 1\nprint 2\nprint 3\n"
        output = run_code(code)
        assert output.strip() == "1\n2\n3"

    def test_len_non_iterable_raises(self):
        with pytest.raises(RuntimeError, match="Cannot get length"):
            run_code("x = 5\nprint len x\n")

    def test_index_non_list_raises(self):
        with pytest.raises(RuntimeError, match="Cannot index"):
            run_code("x = 5\nprint x[0]\n")

    def test_unknown_node_type_raises(self):
        """Unknown node in interpreter should raise."""
        interp = Interpreter()
        with pytest.raises(ValueError, match="Unknown AST node"):
            interp.interpret("not_a_node")

    def test_unknown_expression_type_raises(self):
        interp = Interpreter()
        with pytest.raises(ValueError, match="Unknown node type"):
            interp.evaluate("not_a_node")


# ============================================================
# Integration: run the .srv test files
# ============================================================

class TestSrvFiles:
    def test_test_srv_runs(self):
        """test.srv should run without errors."""
        test_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "test.srv")
        if not os.path.isfile(test_file):
            pytest.skip("test.srv not found")
        with open(test_file) as f:
            code = f.read()
        # Should not raise
        run_code(code)

    def test_test_all_srv_runs(self):
        """test_all.srv should run and produce expected output."""
        test_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "test_all.srv")
        if not os.path.isfile(test_file):
            pytest.skip("test_all.srv not found")
        with open(test_file) as f:
            code = f.read()
        output = run_code(code)
        assert "=== all tests passed ===" in output


# ============================================================
# REPL Tests
# ============================================================

class TestFormatValue:
    def test_format_integer_float(self):
        assert format_value(5.0) == "5"

    def test_format_float(self):
        assert format_value(3.14) == "3.14"

    def test_format_string(self):
        assert format_value("hello") == '"hello"'

    def test_format_bool_true(self):
        assert format_value(True) == "true"

    def test_format_bool_false(self):
        assert format_value(False) == "false"

    def test_format_list(self):
        assert format_value([1.0, 2.0, 3.0]) == "[1, 2, 3]"

    def test_format_nested_list(self):
        result = format_value([1.0, [2.0, 3.0]])
        assert result == "[1, [2, 3]]"

    def test_format_none(self):
        assert format_value(None) is None

    def test_format_empty_list(self):
        assert format_value([]) == "[]"

    def test_format_mixed_list(self):
        result = format_value([1.0, "hi", True])
        assert '"hi"' in result
        assert "true" in result


class TestReplExecute:
    def test_simple_print(self):
        interp = Interpreter()
        buf = io.StringIO()
        with redirect_stdout(buf):
            _repl_execute("print 42\n", interp)
        assert buf.getvalue().strip() == "42"

    def test_variable_persists(self):
        interp = Interpreter()
        _repl_execute("x = 10\n", interp)
        assert interp.variables.get("x") == 10.0

    def test_function_persists(self):
        interp = Interpreter()
        _repl_execute("function double x\n    return x * 2\n", interp)
        assert "double" in interp.functions

    def test_function_call_after_define(self):
        interp = Interpreter()
        _repl_execute("function add a b\n    return a + b\n", interp)
        buf = io.StringIO()
        with redirect_stdout(buf):
            _repl_execute("print add 3 5\n", interp)
        assert buf.getvalue().strip() == "8"

    def test_if_statement(self):
        interp = Interpreter()
        buf = io.StringIO()
        with redirect_stdout(buf):
            _repl_execute("if true\n    print 1\n", interp)
        assert buf.getvalue().strip() == "1"

    def test_while_loop(self):
        interp = Interpreter()
        buf = io.StringIO()
        with redirect_stdout(buf):
            _repl_execute("x = 0\nwhile x < 3\n    print x\n    x = x + 1\n", interp)
        assert buf.getvalue().strip() == "0\n1\n2"

    def test_for_loop(self):
        interp = Interpreter()
        buf = io.StringIO()
        with redirect_stdout(buf):
            _repl_execute("for i 1 4\n    print i\n", interp)
        assert buf.getvalue().strip() == "1\n2\n3"

    def test_syntax_error_does_not_crash(self):
        """Syntax errors in REPL should raise, not crash."""
        interp = Interpreter()
        with pytest.raises(SyntaxError):
            _repl_execute("if\n", interp)

    def test_list_operations(self):
        interp = Interpreter()
        _repl_execute("nums = [10, 20, 30]\n", interp)
        buf = io.StringIO()
        with redirect_stdout(buf):
            _repl_execute("print nums[1]\n", interp)
        assert buf.getvalue().strip() == "20"

    def test_multiple_sessions(self):
        """State persists across multiple _repl_execute calls."""
        interp = Interpreter()
        _repl_execute("x = 5\n", interp)
        _repl_execute("y = x + 10\n", interp)
        buf = io.StringIO()
        with redirect_stdout(buf):
            _repl_execute("print y\n", interp)
        assert buf.getvalue().strip() == "15"

    def test_function_call_result_printed(self):
        """Standalone function call results should be printed in REPL."""
        interp = Interpreter()
        _repl_execute("function sq x\n    return x * x\n", interp)
        buf = io.StringIO()
        with redirect_stdout(buf):
            _repl_execute("sq 7\n", interp)
        output = buf.getvalue().strip()
        assert output == "49"

    def test_string_expression(self):
        interp = Interpreter()
        buf = io.StringIO()
        with redirect_stdout(buf):
            _repl_execute('print "hello world"\n', interp)
        assert buf.getvalue().strip() == "hello world"
