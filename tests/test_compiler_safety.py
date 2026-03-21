"""Tests for compiler edge cases: identifier safety, builtin arity,
feature detection, and generated C structure.

Covers error-handling code paths and security-critical _safe_ident logic
that existing tests don't exercise.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sauravcc import (
    tokenize,
    Parser,
    CCodeGenerator,
    NumberNode,
    StringNode,
    FunctionCallNode,
    ASTNode,
)


# ============================================================
# Helpers
# ============================================================

def compile_to_c(code: str) -> str:
    tokens = tokenize(code)
    parser = Parser(tokens)
    program = parser.parse()
    codegen = CCodeGenerator()
    return codegen.compile(program)

def make_codegen():
    return CCodeGenerator()


# ============================================================
# _safe_ident: C reserved word collision prevention
# ============================================================

class TestSafeIdentReservedWords:
    """Identifiers that collide with C keywords/stdlib get u_ prefix."""

    def test_c_keyword_int(self):
        assert make_codegen()._safe_ident("int") == "u_int"

    def test_c_keyword_float(self):
        assert make_codegen()._safe_ident("float") == "u_float"

    def test_c_keyword_return(self):
        assert make_codegen()._safe_ident("return") == "u_return"

    def test_c_keyword_void(self):
        assert make_codegen()._safe_ident("void") == "u_void"

    def test_c_keyword_char(self):
        assert make_codegen()._safe_ident("char") == "u_char"

    def test_c_keyword_double(self):
        assert make_codegen()._safe_ident("double") == "u_double"

    def test_c_keyword_static(self):
        assert make_codegen()._safe_ident("static") == "u_static"

    def test_c_keyword_const(self):
        assert make_codegen()._safe_ident("const") == "u_const"

    def test_c_keyword_struct(self):
        assert make_codegen()._safe_ident("struct") == "u_struct"

    def test_c_keyword_typedef(self):
        assert make_codegen()._safe_ident("typedef") == "u_typedef"

    def test_c_keyword_enum(self):
        assert make_codegen()._safe_ident("enum") == "u_enum"

    def test_c_keyword_switch(self):
        assert make_codegen()._safe_ident("switch") == "u_switch"

    def test_c_keyword_break(self):
        assert make_codegen()._safe_ident("break") == "u_break"

    def test_c_keyword_continue(self):
        assert make_codegen()._safe_ident("continue") == "u_continue"

    def test_c_keyword_goto(self):
        assert make_codegen()._safe_ident("goto") == "u_goto"

    def test_c_keyword_sizeof(self):
        assert make_codegen()._safe_ident("sizeof") == "u_sizeof"

    def test_c_stdlib_malloc(self):
        assert make_codegen()._safe_ident("malloc") == "u_malloc"

    def test_c_stdlib_printf(self):
        assert make_codegen()._safe_ident("printf") == "u_printf"

    def test_c_stdlib_free(self):
        assert make_codegen()._safe_ident("free") == "u_free"

    def test_c_stdlib_exit(self):
        assert make_codegen()._safe_ident("exit") == "u_exit"

    def test_c_stdlib_NULL(self):
        assert make_codegen()._safe_ident("NULL") == "u_NULL"

    def test_c_setjmp(self):
        assert make_codegen()._safe_ident("setjmp") == "u_setjmp"

    def test_c_longjmp(self):
        assert make_codegen()._safe_ident("longjmp") == "u_longjmp"

    def test_c_jmp_buf(self):
        assert make_codegen()._safe_ident("jmp_buf") == "u_jmp_buf"

    def test_c_memcpy(self):
        assert make_codegen()._safe_ident("memcpy") == "u_memcpy"

    def test_c_strcmp(self):
        assert make_codegen()._safe_ident("strcmp") == "u_strcmp"

    def test_c_strlen(self):
        assert make_codegen()._safe_ident("strlen") == "u_strlen"

    def test_c_fmod(self):
        assert make_codegen()._safe_ident("fmod") == "u_fmod"

    def test_normal_ident_unchanged(self):
        assert make_codegen()._safe_ident("counter") == "counter"

    def test_normal_ident_underscore(self):
        assert make_codegen()._safe_ident("my_var") == "my_var"

    def test_normal_ident_digits(self):
        assert make_codegen()._safe_ident("x2") == "x2"

    def test_single_char_ident(self):
        assert make_codegen()._safe_ident("x") == "x"

    def test_underscore_start_ok(self):
        # Single underscore prefix is fine (not srv_ or __)
        assert make_codegen()._safe_ident("_temp") == "_temp"


class TestSafeIdentPrefixCollision:
    """Names starting with srv_ or __ must be prefixed to avoid
    colliding with compiler-generated runtime code."""

    def test_srv_prefix_gets_u_prefix(self):
        assert make_codegen()._safe_ident("srv_data") == "u_srv_data"

    def test_srv_prefix_single_char(self):
        assert make_codegen()._safe_ident("srv_x") == "u_srv_x"

    def test_srv_list(self):
        assert make_codegen()._safe_ident("srv_list") == "u_srv_list"

    def test_dunder_prefix_gets_u_prefix(self):
        assert make_codegen()._safe_ident("__init") == "u___init"

    def test_dunder_error_msg(self):
        assert make_codegen()._safe_ident("__error_msg") == "u___error_msg"

    def test_dunder_has_error(self):
        assert make_codegen()._safe_ident("__has_error") == "u___has_error"


class TestSafeIdentInvalid:
    """Names with invalid C identifier characters must be rejected."""

    def test_hyphen_raises(self):
        with pytest.raises(ValueError, match="Invalid identifier"):
            make_codegen()._safe_ident("my-var")

    def test_space_raises(self):
        with pytest.raises(ValueError, match="Invalid identifier"):
            make_codegen()._safe_ident("my var")

    def test_starts_with_digit_raises(self):
        with pytest.raises(ValueError, match="Invalid identifier"):
            make_codegen()._safe_ident("3abc")

    def test_at_sign_raises(self):
        with pytest.raises(ValueError, match="Invalid identifier"):
            make_codegen()._safe_ident("a@b")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="Invalid identifier"):
            make_codegen()._safe_ident("")

    def test_dot_raises(self):
        with pytest.raises(ValueError, match="Invalid identifier"):
            make_codegen()._safe_ident("a.b")

    def test_semicolon_injection_raises(self):
        with pytest.raises(ValueError, match="Invalid identifier"):
            make_codegen()._safe_ident("x; system(\"rm -rf /\")")


class TestSafeIdentCaching:
    """Results are cached for consistency within a compilation unit."""

    def test_same_name_cached(self):
        cg = make_codegen()
        r1 = cg._safe_ident("myFunc")
        r2 = cg._safe_ident("myFunc")
        assert r1 is r2

    def test_reserved_word_cached(self):
        cg = make_codegen()
        r1 = cg._safe_ident("int")
        r2 = cg._safe_ident("int")
        assert r1 == "u_int"
        assert r1 is r2

    def test_different_names_not_confused(self):
        cg = make_codegen()
        assert cg._safe_ident("x") == "x"
        assert cg._safe_ident("y") == "y"
        assert cg._safe_ident("int") == "u_int"


# ============================================================
# compile_call: builtin arity validation
# ============================================================

class TestCompileCallBuiltinArity:
    """Builtins with wrong arg counts must raise ValueError."""

    def test_sqrt_no_args(self):
        cg = make_codegen()
        with pytest.raises(ValueError, match="expects 1 argument"):
            cg.compile_call(FunctionCallNode("sqrt", []))

    def test_power_one_arg(self):
        cg = make_codegen()
        with pytest.raises(ValueError, match="expects 2 argument"):
            cg.compile_call(FunctionCallNode("power", [NumberNode(2)]))

    def test_replace_two_args(self):
        cg = make_codegen()
        with pytest.raises(ValueError, match="expects 3 argument"):
            cg.compile_call(FunctionCallNode("replace", [StringNode("a"), StringNode("b")]))

    def test_contains_one_arg(self):
        cg = make_codegen()
        with pytest.raises(ValueError, match="expects 2 argument"):
            cg.compile_call(FunctionCallNode("contains", [StringNode("a")]))

    def test_abs_no_args(self):
        cg = make_codegen()
        with pytest.raises(ValueError, match="expects 1 argument"):
            cg.compile_call(FunctionCallNode("abs", []))

    def test_floor_no_args(self):
        cg = make_codegen()
        with pytest.raises(ValueError, match="expects 1 argument"):
            cg.compile_call(FunctionCallNode("floor", []))

    def test_ceil_no_args(self):
        cg = make_codegen()
        with pytest.raises(ValueError, match="expects 1 argument"):
            cg.compile_call(FunctionCallNode("ceil", []))

    def test_round_no_args(self):
        cg = make_codegen()
        with pytest.raises(ValueError, match="expects 1 argument"):
            cg.compile_call(FunctionCallNode("round", []))

    def test_to_number_no_args(self):
        cg = make_codegen()
        with pytest.raises(ValueError, match="expects 1 argument"):
            cg.compile_call(FunctionCallNode("to_number", []))

    def test_upper_no_args(self):
        cg = make_codegen()
        with pytest.raises(ValueError, match="expects 1 argument"):
            cg.compile_call(FunctionCallNode("upper", []))

    def test_lower_no_args(self):
        cg = make_codegen()
        with pytest.raises(ValueError, match="expects 1 argument"):
            cg.compile_call(FunctionCallNode("lower", []))

    def test_index_of_one_arg(self):
        cg = make_codegen()
        with pytest.raises(ValueError, match="expects 2 argument"):
            cg.compile_call(FunctionCallNode("index_of", [StringNode("a")]))

    def test_char_at_one_arg(self):
        cg = make_codegen()
        with pytest.raises(ValueError, match="expects 2 argument"):
            cg.compile_call(FunctionCallNode("char_at", [StringNode("a")]))

    def test_substring_one_arg(self):
        cg = make_codegen()
        with pytest.raises(ValueError, match="expects 3 argument"):
            cg.compile_call(FunctionCallNode("substring", [StringNode("a")]))

    def test_has_key_one_arg(self):
        cg = make_codegen()
        with pytest.raises(ValueError, match="expects 2 argument"):
            cg.compile_call(FunctionCallNode("has_key", [StringNode("m")]))

    def test_join_one_arg(self):
        cg = make_codegen()
        with pytest.raises(ValueError, match="expects 2 argument"):
            cg.compile_call(FunctionCallNode("join", [StringNode(",")]))

    def test_split_one_arg(self):
        cg = make_codegen()
        with pytest.raises(ValueError, match="expects 2 argument"):
            cg.compile_call(FunctionCallNode("split", [StringNode("a")]))


class TestCompileCallUserFunction:
    """User functions compile to direct C calls with safe names."""

    def test_normal_function(self):
        cg = make_codegen()
        result = cg.compile_call(FunctionCallNode("my_func", [NumberNode(42)]))
        assert result == "my_func(42)"

    def test_no_args(self):
        cg = make_codegen()
        result = cg.compile_call(FunctionCallNode("greet", []))
        assert result == "greet()"

    def test_multiple_args(self):
        cg = make_codegen()
        result = cg.compile_call(FunctionCallNode("add", [NumberNode(1), NumberNode(2)]))
        assert result == "add(1, 2)"

    def test_reserved_name_prefixed(self):
        cg = make_codegen()
        result = cg.compile_call(FunctionCallNode("printf", [NumberNode(1)]))
        assert result == "u_printf(1)"


# ============================================================
# compile_expression: unknown AST node type
# ============================================================

class TestCompileExpressionUnknown:
    def test_unknown_node_raises(self):
        class FakeNode(ASTNode):
            pass

        cg = make_codegen()
        with pytest.raises(ValueError, match="Unknown expression type"):
            cg.compile_expression(FakeNode())


# ============================================================
# Feature detection (scan_features)
# ============================================================

class TestFeatureDetection:
    """scan_features should set flags that control runtime emission."""

    def test_no_lists_no_list_runtime(self):
        output = compile_to_c("x = 5\nprint x")
        assert "srv_list" not in output

    def test_list_triggers_list_runtime(self):
        output = compile_to_c("items = [1 2 3]\nprint items")
        assert "srv_list" in output

    def test_no_try_no_setjmp(self):
        output = compile_to_c("x = 5\nprint x")
        assert "setjmp" not in output

    def test_try_catch_triggers_setjmp(self):
        output = compile_to_c("try\n  x = 1\ncatch e\n  print e")
        assert "setjmp" in output

    def test_fstring_triggers_fstring_flag(self):
        tokens = tokenize('x = 5\nprint f"val={x}"')
        parser = Parser(tokens)
        program = parser.parse()
        cg = CCodeGenerator()
        cg.compile(program)
        assert cg.uses_fstring

    def test_map_triggers_map_runtime(self):
        tokens = tokenize('m = {"a": 1}\nprint m')
        parser = Parser(tokens)
        program = parser.parse()
        cg = CCodeGenerator()
        cg.compile(program)
        assert cg.uses_maps

    def test_append_triggers_list_flag(self):
        tokens = tokenize("items = [1]\nappend items 2\nprint items")
        parser = Parser(tokens)
        program = parser.parse()
        cg = CCodeGenerator()
        cg.compile(program)
        assert cg.uses_lists

    def test_has_key_triggers_map_flag(self):
        tokens = tokenize('m = {"a": 1}\nprint has_key m "a"')
        parser = Parser(tokens)
        program = parser.parse()
        cg = CCodeGenerator()
        cg.compile(program)
        assert cg.uses_maps


# ============================================================
# Generated C structure
# ============================================================

class TestOutputStructure:
    """Structural properties of the generated C code."""

    def test_includes_stdio(self):
        assert "#include <stdio.h>" in compile_to_c("x = 5\nprint x")

    def test_includes_stdlib(self):
        assert "#include <stdlib.h>" in compile_to_c("x = 5\nprint x")

    def test_includes_math(self):
        assert "#include <math.h>" in compile_to_c("x = 5\nprint x")

    def test_has_main(self):
        output = compile_to_c("x = 5\nprint x")
        assert "int main(void)" in output
        assert "return 0;" in output

    def test_function_forward_declared_before_main(self):
        code = "function greet name\n  print name\ngreet \"world\""
        output = compile_to_c(code)
        fwd_idx = output.find("double greet(")
        main_idx = output.find("int main(void)")
        assert fwd_idx < main_idx

    def test_while_generates_while(self):
        output = compile_to_c("x = 10\nwhile x > 0\n  x = x - 1\nprint x")
        assert "while (" in output

    def test_if_else_generates_if_else(self):
        output = compile_to_c("x = 5\nif x > 3\n  print 1\nelse\n  print 0")
        assert "if (" in output
        assert "else" in output

    def test_for_loop_generates_for(self):
        # Compiler's legacy range syntax: for VAR START END
        output = compile_to_c("for i 0 5\n  print i")
        assert "for (" in output

    def test_modulo_uses_fmod(self):
        output = compile_to_c("x = 10 % 3\nprint x")
        assert "fmod(" in output

    def test_power_uses_pow(self):
        # power() is a builtin function in the compiler
        output = compile_to_c("x = power 2 3\nprint x")
        assert "pow(" in output

    def test_not_generates_bang(self):
        output = compile_to_c("x = not true\nprint x")
        assert "!" in output


class TestVarTracking:
    """Verify the compiler tracks variable types for printf formatting."""

    def test_string_var_percent_s(self):
        output = compile_to_c('name = "alice"\nprint name')
        assert "%s" in output

    def test_number_var_percent_g(self):
        output = compile_to_c("x = 42\nprint x")
        # Compiler uses %.10g format
        assert "%.10g" in output

    def test_list_var_tracked(self):
        tokens = tokenize("items = [1 2 3]\nprint items")
        parser = Parser(tokens)
        program = parser.parse()
        cg = CCodeGenerator()
        cg.compile(program)
        assert "items" in cg.list_vars

    def test_map_var_tracked(self):
        tokens = tokenize('m = {"a": 1}\nprint m')
        parser = Parser(tokens)
        program = parser.parse()
        cg = CCodeGenerator()
        cg.compile(program)
        assert "m" in cg.map_vars

    def test_string_var_tracked(self):
        tokens = tokenize('s = "hello"\nprint s')
        parser = Parser(tokens)
        program = parser.parse()
        cg = CCodeGenerator()
        cg.compile(program)
        assert "s" in cg.string_vars


class TestStringBuiltinHelpers:
    """String builtins must trigger helper emission."""

    def test_upper_triggers_helpers(self):
        tokens = tokenize('s = "hello"\nprint upper s')
        parser = Parser(tokens)
        program = parser.parse()
        cg = CCodeGenerator()
        cg.compile(program)
        assert cg.uses_string_helpers

    def test_lower_triggers_helpers(self):
        tokens = tokenize('s = "HELLO"\nprint lower s')
        parser = Parser(tokens)
        program = parser.parse()
        cg = CCodeGenerator()
        cg.compile(program)
        assert cg.uses_string_helpers

    def test_trim_triggers_helpers(self):
        tokens = tokenize('s = " hi "\nprint trim s')
        parser = Parser(tokens)
        program = parser.parse()
        cg = CCodeGenerator()
        cg.compile(program)
        assert cg.uses_string_helpers

    def test_type_of_triggers_helpers(self):
        tokens = tokenize("x = 5\nprint type_of x")
        parser = Parser(tokens)
        program = parser.parse()
        cg = CCodeGenerator()
        cg.compile(program)
        assert cg.uses_string_helpers

    def test_contains_triggers_helpers(self):
        tokens = tokenize('s = "hello world"\nprint contains s "hello"')
        parser = Parser(tokens)
        program = parser.parse()
        cg = CCodeGenerator()
        cg.compile(program)
        assert cg.uses_string_helpers

    def test_reverse_triggers_helpers(self):
        tokens = tokenize('s = "hello"\nprint reverse s')
        parser = Parser(tokens)
        program = parser.parse()
        cg = CCodeGenerator()
        cg.compile(program)
        assert cg.uses_string_helpers


class TestRecursionCompilation:
    """Recursive and mutually recursive functions compile correctly."""

    def test_recursive_fibonacci(self):
        code = "function fib n\n  if n < 2\n    return n\n  return fib n - 1\nprint fib 5"
        output = compile_to_c(code)
        assert "double fib(" in output

    def test_mutual_recursion_both_declared(self):
        code = ("function isEven n\n  if n == 0\n    return 1\n  return isOdd n - 1\n"
                "function isOdd n\n  if n == 0\n    return 0\n  return isEven n - 1\n"
                "print isEven 4")
        output = compile_to_c(code)
        assert "double isEven(" in output
        assert "double isOdd(" in output


class TestNestedTryCatch:
    """Nested try/catch generates multiple setjmp calls."""

    def test_nested_try_compiles(self):
        code = "try\n  try\n    x = 1 / 0\n  catch e\n    print e\ncatch outer\n  print outer"
        output = compile_to_c(code)
        assert output.count("setjmp") >= 2


class TestClassCompilation:
    """Class definitions generate C structs and methods."""

    def test_class_generates_typedef_struct(self):
        code = "class Dog\n  function init name\n    self.name = name\n  function speak\n    print self.name"
        output = compile_to_c(code)
        assert "typedef struct" in output
        assert "Dog" in output

    def test_new_object_compiles(self):
        code = 'class Cat\n  function init n\n    self.n = n\nc = new Cat "Whiskers"\nprint c'
        output = compile_to_c(code)
        assert "Cat" in output
        assert "int main(void)" in output


class TestCompileEndToEnd:
    """Full programs compile without error."""

    def test_fizzbuzz(self):
        code = ("for i 1 16\n"
                "  if i % 15 == 0\n"
                '    print "FizzBuzz"\n'
                "  else if i % 3 == 0\n"
                '    print "Fizz"\n'
                "  else if i % 5 == 0\n"
                '    print "Buzz"\n'
                "  else\n"
                "    print i")
        output = compile_to_c(code)
        assert "int main(void)" in output
        assert "fmod(" in output

    def test_list_manipulation(self):
        code = ("items = [10 20 30]\n"
                "append items 40\n"
                "print len items\n"
                "pop items\n"
                "print items")
        output = compile_to_c(code)
        assert "srv_list" in output

    def test_map_operations(self):
        code = ('m = {"name": "Alice" "age": 30}\n'
                'print has_key m "name"')
        output = compile_to_c(code)
        assert "srv_map" in output

    def test_fstring_program(self):
        code = ('name = "World"\nprint f"Hello {name}!"')
        output = compile_to_c(code)
        assert "snprintf" in output

    def test_try_catch_throw(self):
        code = ('try\n  throw "oops"\ncatch e\n  print e')
        output = compile_to_c(code)
        assert "setjmp" in output
        # throw compiles to longjmp-based error propagation in the generated C
        assert "longjmp" in output
