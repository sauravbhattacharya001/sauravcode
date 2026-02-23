"""
Tests for the sauravcode compiler (sauravcc.py).

Tests the tokenizer, parser, AST nodes, and C code generator.
Does NOT require gcc — tests the compilation pipeline up to C output.
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sauravcc import (
    tokenize,
    Parser,
    CCodeGenerator,
    ProgramNode,
    NumberNode,
    StringNode,
    BoolNode,
    IdentifierNode,
    BinaryOpNode,
    UnaryOpNode,
    CompareNode,
    LogicalNode,
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
    IndexedAssignmentNode,
    AppendNode,
    LenNode,
    ClassNode,
    NewNode,
    DotAccessNode,
    MethodCallNode,
    DotAssignmentNode,
    TryCatchNode,
    PopNode,
    ASTNode,
)


# ============================================================
# Helpers
# ============================================================

def compile_to_c(code: str) -> str:
    """Tokenize, parse, and compile sauravcode to C source."""
    tokens = tokenize(code)
    parser = Parser(tokens)
    program = parser.parse()
    codegen = CCodeGenerator()
    return codegen.compile(program)


# ============================================================
# Tokenizer Tests (compiler version)
# ============================================================

class TestCompilerTokenizer:
    def test_basic_tokens(self):
        tokens = tokenize("x = 42\n")
        types = [t[0] for t in tokens]
        assert "IDENT" in types
        assert "ASSIGN" in types
        assert "NUMBER" in types

    def test_comments_skipped(self):
        tokens = tokenize("# comment\nx = 1\n")
        types = [t[0] for t in tokens]
        assert "COMMENT" not in types  # compiler skips comments

    def test_string_with_escapes(self):
        tokens = tokenize('"hello\\"world"\n')
        string_tokens = [t for t in tokens if t[0] == "STRING"]
        assert len(string_tokens) == 1

    def test_dot_token(self):
        tokens = tokenize("obj.field\n")
        types = [t[0] for t in tokens]
        assert "DOT" in types

    def test_class_keyword(self):
        tokens = tokenize("class Foo\n")
        kw_tokens = [t for t in tokens if t[0] == "KEYWORD"]
        assert any(t[1] == "class" for t in kw_tokens)

    def test_new_keyword(self):
        tokens = tokenize("new Foo\n")
        kw_tokens = [t for t in tokens if t[0] == "KEYWORD"]
        assert any(t[1] == "new" for t in kw_tokens)

    def test_try_catch_keywords(self):
        tokens = tokenize("try\n    x = 1\ncatch e\n    print e\n")
        kw_tokens = [t for t in tokens if t[0] == "KEYWORD"]
        kw_values = [t[1] for t in kw_tokens]
        assert "try" in kw_values
        assert "catch" in kw_values


# ============================================================
# Parser Tests (compiler version)
# ============================================================

class TestCompilerParser:
    def test_parse_program(self):
        tokens = tokenize("x = 5\n")
        parser = Parser(tokens)
        program = parser.parse()
        assert isinstance(program, ProgramNode)
        assert len(program.statements) > 0

    def test_parse_function(self):
        code = "function add x y\n    return x + y\n"
        tokens = tokenize(code)
        parser = Parser(tokens)
        program = parser.parse()
        funcs = [s for s in program.statements if isinstance(s, FunctionNode)]
        assert len(funcs) == 1
        assert funcs[0].name == "add"

    def test_parse_class(self):
        code = "class Foo\n    function init\n        return 0\n"
        tokens = tokenize(code)
        parser = Parser(tokens)
        program = parser.parse()
        classes = [s for s in program.statements if isinstance(s, ClassNode)]
        assert len(classes) == 1
        assert classes[0].name == "Foo"

    def test_parse_if_elif_else(self):
        code = """if x > 0
    print 1
else if x == 0
    print 0
else
    print -1
"""
        tokens = tokenize(code)
        parser = Parser(tokens)
        program = parser.parse()
        ifs = [s for s in program.statements if isinstance(s, IfNode)]
        assert len(ifs) == 1
        assert len(ifs[0].elif_chains) == 1
        assert ifs[0].else_body is not None

    def test_parse_for(self):
        code = "for i 0 10\n    print i\n"
        tokens = tokenize(code)
        parser = Parser(tokens)
        program = parser.parse()
        fors = [s for s in program.statements if isinstance(s, ForNode)]
        assert len(fors) == 1

    def test_parse_try_catch(self):
        code = "try\n    x = 1\ncatch e\n    print e\n"
        tokens = tokenize(code)
        parser = Parser(tokens)
        program = parser.parse()
        trys = [s for s in program.statements if isinstance(s, TryCatchNode)]
        assert len(trys) == 1
        assert trys[0].catch_var == "e"

    def test_parse_indexed_assignment(self):
        code = "nums[0] = 42\n"
        tokens = tokenize(code)
        parser = Parser(tokens)
        program = parser.parse()
        indexed = [s for s in program.statements if isinstance(s, IndexedAssignmentNode)]
        assert len(indexed) == 1

    def test_parse_append(self):
        code = "append nums 10\n"
        tokens = tokenize(code)
        parser = Parser(tokens)
        program = parser.parse()
        appends = [s for s in program.statements if isinstance(s, AppendNode)]
        assert len(appends) == 1

    def test_parse_list_literal(self):
        code = "x = [1, 2, 3]\n"
        tokens = tokenize(code)
        parser = Parser(tokens)
        program = parser.parse()
        assigns = [s for s in program.statements if isinstance(s, AssignmentNode)]
        assert len(assigns) == 1
        assert isinstance(assigns[0].expression, ListNode)

    def test_parse_dot_access(self):
        code = "function f x\n    return x\nprint f 1\n"
        # Just test parsing doesn't crash
        tokens = tokenize(code)
        parser = Parser(tokens)
        program = parser.parse()
        assert isinstance(program, ProgramNode)


# ============================================================
# C Code Generator Tests
# ============================================================

class TestCCodeGenerator:
    def test_arithmetic_generates_c(self):
        c_code = compile_to_c("print 3 + 5\n")
        assert "#include <stdio.h>" in c_code
        assert "int main" in c_code
        assert "printf" in c_code

    def test_function_generates_forward_decl(self):
        c_code = compile_to_c("function add x y\n    return x + y\n")
        assert "double add(double x, double y)" in c_code

    def test_variable_generates_double(self):
        c_code = compile_to_c("x = 42\n")
        assert "double x = 42" in c_code

    def test_string_generates_const_char(self):
        c_code = compile_to_c('name = "hello"\n')
        assert 'const char *name = "hello"' in c_code

    def test_bool_generates_int(self):
        c_code = compile_to_c("x = true\n")
        assert "int x = 1" in c_code

    def test_if_generates_c_if(self):
        c_code = compile_to_c("if true\n    print 1\n")
        assert "if (1)" in c_code

    def test_while_generates_c_while(self):
        c_code = compile_to_c("x = 0\nwhile x < 5\n    x = x + 1\n")
        assert "while" in c_code

    def test_for_generates_c_for(self):
        c_code = compile_to_c("for i 0 10\n    print i\n")
        assert "for (double i = 0" in c_code

    def test_list_generates_runtime(self):
        c_code = compile_to_c("nums = [1, 2, 3]\n")
        assert "SrvList" in c_code
        assert "srv_list_new" in c_code
        assert "srv_list_append" in c_code

    def test_modulo_uses_fmod(self):
        c_code = compile_to_c("print 10 % 3\n")
        assert "fmod" in c_code

    def test_logical_and_generates_ampersand(self):
        c_code = compile_to_c("if true and false\n    print 1\n")
        assert "&&" in c_code

    def test_logical_or_generates_pipe(self):
        c_code = compile_to_c("if true or false\n    print 1\n")
        assert "||" in c_code

    def test_not_generates_bang(self):
        c_code = compile_to_c("if not true\n    print 1\n")
        assert "!" in c_code

    def test_try_catch_generates_setjmp(self):
        c_code = compile_to_c("try\n    x = 1\ncatch e\n    print e\n")
        assert "#include <setjmp.h>" in c_code
        assert "setjmp" in c_code

    def test_return_zero_implicit(self):
        """Functions without return should get implicit return 0."""
        c_code = compile_to_c("function f x\n    print x\n")
        assert "return 0;" in c_code

    def test_indexed_assignment_generates_set(self):
        c_code = compile_to_c("nums = [1, 2]\nnums[0] = 42\n")
        assert "srv_list_set" in c_code

    def test_comparison_operators(self):
        c_code = compile_to_c("if 5 == 5\n    print 1\n")
        assert "==" in c_code

    def test_negation_generates_minus(self):
        c_code = compile_to_c("x = -5\n")
        assert "-(5)" in c_code or "-5" in c_code

    def test_len_generates_srv_list_len(self):
        c_code = compile_to_c("nums = [1]\nprint len nums\n")
        assert "srv_list_len" in c_code

    def test_elif_generates_else_if(self):
        code = """x = 5
if x > 10
    print 1
else if x > 3
    print 2
else
    print 3
"""
        c_code = compile_to_c(code)
        assert "} else if" in c_code

    def test_class_generates_struct(self):
        code = "class Foo\n    function init\n        return 0\n"
        c_code = compile_to_c(code)
        assert "typedef struct" in c_code
        assert "Foo" in c_code

    def test_reassignment_no_redeclare(self):
        c_code = compile_to_c("x = 1\nx = 2\n")
        # First assignment declares, second does not
        lines = [l.strip() for l in c_code.split("\n") if "x =" in l or "x=" in l]
        decl_lines = [l for l in lines if l.startswith("double x")]
        assert len(decl_lines) == 1

    def test_no_list_runtime_when_unused(self):
        c_code = compile_to_c("x = 5\nprint x\n")
        assert "SrvList" not in c_code

    def test_no_setjmp_when_no_try(self):
        c_code = compile_to_c("x = 5\n")
        assert "setjmp" not in c_code

    def test_string_print_uses_percent_s(self):
        c_code = compile_to_c('print "hello"\n')
        assert '%s' in c_code

    def test_bool_print_uses_ternary(self):
        c_code = compile_to_c("print true\n")
        assert "true" in c_code
        assert "false" in c_code


# ============================================================
# Integration: compile .srv test files to C
# ============================================================

class TestSrvFilesCompiler:
    def test_test_all_compiles_to_c(self):
        """test_all.srv should compile to valid C without errors."""
        test_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "test_all.srv")
        if not os.path.isfile(test_file):
            pytest.skip("test_all.srv not found")
        with open(test_file) as f:
            code = f.read()
        c_code = compile_to_c(code)
        assert "#include <stdio.h>" in c_code
        assert "int main" in c_code
        # Should have multiple printf calls
        assert c_code.count("printf") > 10

    def test_test_srv_compiles_to_c(self):
        test_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "test.srv")
        if not os.path.isfile(test_file):
            pytest.skip("test.srv not found")
        with open(test_file) as f:
            code = f.read()
        c_code = compile_to_c(code)
        assert "#include <stdio.h>" in c_code


# ============================================================
# Builtin functions: math, string, conversion
# ============================================================

class TestBuiltinCodeGen:
    """Tests for compiler-supported builtin functions."""

    # --- Math builtins ---

    def test_abs_compiles_to_fabs(self):
        c_code = compile_to_c("x = -5\nprint abs x\n")
        assert "fabs" in c_code

    def test_sqrt_compiles(self):
        c_code = compile_to_c("print sqrt 144\n")
        assert "sqrt(144)" in c_code

    def test_floor_compiles(self):
        c_code = compile_to_c("print floor 3.7\n")
        assert "floor(3.7)" in c_code

    def test_ceil_compiles(self):
        c_code = compile_to_c("print ceil 3.2\n")
        assert "ceil(3.2)" in c_code

    def test_round_compiles(self):
        c_code = compile_to_c("print round 3.5\n")
        assert "round(3.5)" in c_code

    def test_power_compiles_to_pow(self):
        c_code = compile_to_c("print power 2 10\n")
        assert "pow(2, 10)" in c_code

    # --- String builtins ---

    def test_upper_compiles(self):
        c_code = compile_to_c('print upper "hello"\n')
        assert "srv_upper" in c_code
        assert "%s" in c_code  # should print as string

    def test_lower_compiles(self):
        c_code = compile_to_c('print lower "HELLO"\n')
        assert "srv_lower" in c_code
        assert "%s" in c_code

    def test_upper_emits_string_helpers(self):
        c_code = compile_to_c('print upper "test"\n')
        assert "static char* srv_upper" in c_code
        assert "#include <ctype.h>" in c_code

    def test_lower_emits_string_helpers(self):
        c_code = compile_to_c('print lower "test"\n')
        assert "static char* srv_lower" in c_code

    # --- Conversion builtins ---

    def test_to_string_compiles(self):
        c_code = compile_to_c("n = 42\nprint to_string n\n")
        assert "srv_to_string" in c_code
        assert "%s" in c_code  # should print as string

    def test_to_number_compiles(self):
        c_code = compile_to_c('s = "42"\nprint to_number s\n')
        assert "atof" in c_code

    def test_type_of_compiles(self):
        c_code = compile_to_c("x = 5\nprint type_of x\n")
        assert "srv_type_of" in c_code
        assert "%s" in c_code

    # --- No helper emission when not needed ---

    def test_no_string_helpers_when_unused(self):
        c_code = compile_to_c("x = 5\nprint x\n")
        assert "srv_upper" not in c_code
        assert "ctype.h" not in c_code

    def test_math_builtins_no_string_helpers(self):
        c_code = compile_to_c("print abs -5\nprint sqrt 9\n")
        assert "srv_upper" not in c_code
        assert "ctype.h" not in c_code

    # --- In expressions ---

    def test_abs_in_expression(self):
        c_code = compile_to_c("x = -5\ny = abs x + 1\n")
        assert "fabs" in c_code

    def test_power_in_expression(self):
        c_code = compile_to_c("result = power 2 10\nprint result\n")
        assert "pow(2, 10)" in c_code

    # --- Builtin test file compiles ---

    def test_builtins_srv_compiles(self):
        test_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "test_builtins.srv")
        if not os.path.isfile(test_file):
            pytest.skip("test_builtins.srv not found")
        with open(test_file) as f:
            code = f.read()
        c_code = compile_to_c(code)
        assert "fabs" in c_code
        assert "floor" in c_code
        assert "ceil" in c_code
        assert "sqrt" in c_code
        assert "pow" in c_code
        assert "round" in c_code
        assert "srv_to_string" in c_code
        assert "srv_upper" in c_code
        assert "srv_lower" in c_code