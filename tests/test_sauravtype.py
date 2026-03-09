"""Tests for sauravtype — static type inference and checking."""

import os
import sys
import json
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Insert parent so we can import from repo root
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from sauravtype import (
    TypeChecker, TypeEnv, SrvType, Severity,
    TypeDiagnostic, FunctionSig,
    check_file, format_report, format_summary,
    BUILTIN_SIGS, NUMERIC_TYPES, ITERABLE_TYPES,
)
from saurav import tokenize, Parser


def _check(code: str) -> TypeChecker:
    """Parse code and run the type checker, return the checker."""
    tokens = tokenize(code)
    parser = Parser(tokens)
    ast = parser.parse()
    checker = TypeChecker()
    checker.check(ast)
    return checker


def _diags(code: str):
    """Return diagnostics for code."""
    return _check(code).diagnostics


# ── Type Environment ─────────────────────────────────────────────────


class TestTypeEnv(unittest.TestCase):
    def test_bind_and_lookup(self):
        env = TypeEnv()
        env.bind("x", SrvType.INT)
        self.assertEqual(env.lookup("x"), {SrvType.INT})

    def test_multiple_types(self):
        env = TypeEnv()
        env.bind("x", SrvType.INT)
        env.bind("x", SrvType.STRING)
        self.assertEqual(env.lookup("x"), {SrvType.INT, SrvType.STRING})

    def test_parent_lookup(self):
        parent = TypeEnv()
        parent.bind("x", SrvType.INT)
        child = parent.child()
        self.assertEqual(child.lookup("x"), {SrvType.INT})

    def test_child_shadows_parent(self):
        parent = TypeEnv()
        parent.bind("x", SrvType.INT)
        child = parent.child()
        child.bind("x", SrvType.STRING)
        self.assertEqual(child.lookup("x"), {SrvType.STRING})
        self.assertEqual(parent.lookup("x"), {SrvType.INT})

    def test_unknown_variable(self):
        env = TypeEnv()
        self.assertEqual(env.lookup("nope"), set())

    def test_define_function(self):
        env = TypeEnv()
        env.define_function("foo", 2)
        sig = env.lookup_function("foo")
        self.assertIsNotNone(sig)
        self.assertEqual(sig.param_count, 2)

    def test_all_bindings(self):
        parent = TypeEnv()
        parent.bind("a", SrvType.INT)
        child = parent.child()
        child.bind("b", SrvType.STRING)
        all_b = child.all_bindings()
        self.assertIn("a", all_b)
        self.assertIn("b", all_b)


# ── Type Inference ───────────────────────────────────────────────────


class TestTypeInference(unittest.TestCase):
    def test_number_int(self):
        c = _check('x = 42')
        types = c.get_inferred_types()
        self.assertIn("int", types["x"])

    def test_string(self):
        c = _check('x = "hello"')
        types = c.get_inferred_types()
        self.assertIn("string", types["x"])

    def test_bool(self):
        c = _check('x = true')
        types = c.get_inferred_types()
        self.assertIn("bool", types["x"])

    def test_list(self):
        c = _check('x = [1, 2, 3]')
        types = c.get_inferred_types()
        self.assertIn("list", types["x"])

    def test_map(self):
        c = _check('x = {"a": 1}')
        types = c.get_inferred_types()
        self.assertIn("map", types["x"])

    def test_fstring(self):
        c = _check('name = "world"\nx = f"hello {name}"')
        types = c.get_inferred_types()
        self.assertIn("string", types["x"])

    def test_arithmetic_result(self):
        c = _check('a = 10\nb = 3\nc = a + b')
        types = c.get_inferred_types()
        self.assertIn("int", types.get("c", []))

    def test_division_is_float(self):
        c = _check('x = 10 / 3')
        types = c.get_inferred_types()
        self.assertIn("float", types.get("x", []))

    def test_comparison_is_bool(self):
        c = _check('x = 5\ny = x > 3')
        types = c.get_inferred_types()
        self.assertIn("bool", types.get("y", []))

    def test_lambda(self):
        c = _check('f = lambda x -> x * 2')
        types = c.get_inferred_types()
        self.assertIn("lambda", types.get("f", []))


# ── Function Signatures ──────────────────────────────────────────────


class TestFunctionSigs(unittest.TestCase):
    def test_function_registered(self):
        c = _check('function add a b\n    return a + b')
        sigs = c.get_function_sigs()
        self.assertIn("add", sigs)
        self.assertEqual(sigs["add"]["params"], 2)

    def test_generator_detected(self):
        c = _check('function gen n\n    i = 0\n    while i < n\n        yield i\n        i = i + 1')
        sigs = c.get_function_sigs()
        self.assertTrue(sigs["gen"]["is_generator"])

    def test_return_type_inferred(self):
        c = _check('function greet name\n    return f"Hi {name}"')
        sigs = c.get_function_sigs()
        self.assertIn("string", sigs["greet"]["returns"])


# ── Type Error Detection ─────────────────────────────────────────────


class TestTypeErrors(unittest.TestCase):
    def test_wrong_arg_count_builtin(self):
        diags = _diags('x = sqrt 1 2')
        codes = [d.code for d in diags]
        # sqrt expects 1 arg, got 2
        self.assertIn("T003", codes)

    def test_wrong_arg_count_user_function(self):
        diags = _diags('function add a b\n    return a + b\nx = add 1')
        codes = [d.code for d in diags]
        self.assertIn("T003", codes)

    def test_string_plus_number(self):
        diags = _diags('x = "hello"\ny = 5\nz = x + y')
        codes = [d.code for d in diags]
        self.assertIn("T001", codes)

    def test_for_each_over_number(self):
        diags = _diags('x = 42\nfor item in x\n    print item')
        codes = [d.code for d in diags]
        self.assertIn("T007", codes)

    def test_index_on_bool(self):
        diags = _diags('x = true\ny = x[0]')
        codes = [d.code for d in diags]
        self.assertIn("T004", codes)

    def test_no_false_positive_list_index(self):
        diags = _diags('x = [1, 2, 3]\ny = x[0]')
        codes = [d.code for d in diags]
        self.assertNotIn("T004", codes)

    def test_no_false_positive_map_index(self):
        diags = _diags('x = {"a": 1}\ny = x["a"]')
        codes = [d.code for d in diags]
        self.assertNotIn("T004", codes)

    def test_no_false_positive_string_index(self):
        diags = _diags('x = "hello"\ny = x[0]')
        codes = [d.code for d in diags]
        self.assertNotIn("T004", codes)


# ── No False Positives ───────────────────────────────────────────────


class TestNoFalsePositives(unittest.TestCase):
    def test_clean_code(self):
        code = '''
x = 10
y = 20
z = x + y
print z
name = "world"
print f"Hello {name}"
nums = [1, 2, 3]
append nums 4
'''
        diags = _diags(code)
        errors = [d for d in diags if d.severity == Severity.ERROR]
        self.assertEqual(len(errors), 0)

    def test_if_else(self):
        code = '''
x = 10
if x > 5
    print "big"
else
    print "small"
'''
        diags = _diags(code)
        errors = [d for d in diags if d.severity == Severity.ERROR]
        self.assertEqual(len(errors), 0)

    def test_while_loop(self):
        code = '''
i = 0
while i < 10
    print i
    i = i + 1
'''
        diags = _diags(code)
        errors = [d for d in diags if d.severity == Severity.ERROR]
        self.assertEqual(len(errors), 0)

    def test_for_loop(self):
        diags = _diags('for i 0 10\n    print i')
        errors = [d for d in diags if d.severity == Severity.ERROR]
        self.assertEqual(len(errors), 0)

    def test_for_each_list(self):
        diags = _diags('nums = [1, 2, 3]\nfor n in nums\n    print n')
        self.assertEqual(len([d for d in diags if d.code == "T007"]), 0)

    def test_for_each_string(self):
        diags = _diags('word = "hello"\nfor c in word\n    print c')
        self.assertEqual(len([d for d in diags if d.code == "T007"]), 0)

    def test_for_each_generator(self):
        code = '''
function gen n
    i = 0
    while i < n
        yield i
        i = i + 1
g = gen 5
for x in g
    print x
'''
        diags = _diags(code)
        self.assertEqual(len([d for d in diags if d.code == "T007"]), 0)

    def test_try_catch(self):
        code = '''
try
    x = 1 / 0
catch err
    print err
'''
        diags = _diags(code)
        errors = [d for d in diags if d.severity == Severity.ERROR]
        self.assertEqual(len(errors), 0)

    def test_match(self):
        code = 'x = 2\nmatch x\n    case 1\n        print "one"\n    case 2\n        print "two"\n    case _\n        print "other"\n'
        diags = _diags(code)
        errors = [d for d in diags if d.severity == Severity.ERROR]
        self.assertEqual(len(errors), 0)

    def test_enum(self):
        code = '''
enum Color
    RED
    GREEN
    BLUE
c = Color.RED
'''
        diags = _diags(code)
        errors = [d for d in diags if d.severity == Severity.ERROR]
        self.assertEqual(len(errors), 0)

    def test_map_operations(self):
        code = '''
m = {"a": 1, "b": 2}
k = keys m
v = values m
m["c"] = 3
'''
        diags = _diags(code)
        self.assertEqual(len([d for d in diags if d.code == "T004"]), 0)


# ── Report Formatting ────────────────────────────────────────────────


class TestReportFormatting(unittest.TestCase):
    def test_format_report_no_issues(self):
        c = _check('x = 42')
        report = format_report("test.srv", c.diagnostics, c)
        self.assertIn("No type issues found", report)

    def test_format_report_with_issues(self):
        c = _check('x = sqrt 1 2')
        report = format_report("test.srv", c.diagnostics, c)
        self.assertIn("T003", report)

    def test_format_report_verbose(self):
        c = _check('x = 42\ny = "hello"')
        report = format_report("test.srv", c.diagnostics, c, verbose=True)
        self.assertIn("Inferred Variable Types", report)
        self.assertIn("x: int", report)
        self.assertIn("y: string", report)

    def test_format_summary(self):
        c = _check('x = 42')
        summary = format_summary("test.srv", c)
        self.assertIn("Type Summary", summary)


# ── CLI / File Processing ────────────────────────────────────────────


class TestFileProcessing(unittest.TestCase):
    def test_check_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".srv", delete=False, encoding="utf-8") as f:
            f.write('x = 42\nprint x\n')
            path = f.name
        try:
            diags, checker = check_file(path)
            self.assertIsInstance(diags, list)
            types = checker.get_inferred_types()
            self.assertIn("x", types)
        finally:
            os.unlink(path)

    def test_check_file_with_errors(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".srv", delete=False, encoding="utf-8") as f:
            f.write('x = sqrt 1 2 3\n')
            path = f.name
        try:
            diags, checker = check_file(path)
            self.assertTrue(any(d.code == "T003" for d in diags))
        finally:
            os.unlink(path)

    def test_json_output(self):
        c = _check('x = 42')
        # Test diagnostic serialization
        for d in c.diagnostics:
            as_dict = d.to_dict()
            self.assertIn("code", as_dict)


# ── Builtin Signatures ──────────────────────────────────────────────


class TestBuiltinSigs(unittest.TestCase):
    def test_common_builtins_exist(self):
        for name in ["upper", "lower", "len", "sqrt", "abs", "type_of", "print"]:
            self.assertIn(name, BUILTIN_SIGS, f"Missing builtin: {name}")

    def test_builtin_return_types(self):
        self.assertEqual(BUILTIN_SIGS["upper"][1], SrvType.STRING)
        self.assertEqual(BUILTIN_SIGS["len"][1], SrvType.INT)
        self.assertEqual(BUILTIN_SIGS["sqrt"][1], SrvType.FLOAT)
        self.assertEqual(BUILTIN_SIGS["sort"][1], SrvType.LIST)
        self.assertEqual(BUILTIN_SIGS["keys"][1], SrvType.LIST)

    def test_print_is_variadic(self):
        count, _ = BUILTIN_SIGS["print"]
        self.assertEqual(count, -1)


# ── Edge Cases ────────────────────────────────────────────────────────


class TestEdgeCases(unittest.TestCase):
    def test_empty_program(self):
        c = _check("")
        self.assertEqual(len(c.diagnostics), 0)

    def test_reassignment_changes_type(self):
        c = _check('x = 42\nx = "hello"')
        types = c.get_inferred_types()
        self.assertIn("int", types["x"])
        self.assertIn("string", types["x"])

    def test_nested_function(self):
        code = '''
function outer a
    function inner b
        return b * 2
    return inner a
'''
        c = _check(code)
        sigs = c.get_function_sigs()
        self.assertIn("outer", sigs)

    def test_list_append_on_non_list(self):
        code = 'x = 42\nappend x 5'
        diags = _diags(code)
        codes = [d.code for d in diags]
        self.assertIn("T010", codes)


class TestDiagnosticSeverity(unittest.TestCase):
    def test_wrong_arg_count_is_error(self):
        diags = _diags('x = sqrt 1 2')
        t003 = [d for d in diags if d.code == "T003"]
        self.assertTrue(len(t003) > 0)
        self.assertEqual(t003[0].severity, Severity.ERROR)

    def test_type_mismatch_is_warning(self):
        diags = _diags('x = "hello"\ny = 5\nz = x + y')
        t001 = [d for d in diags if d.code == "T001"]
        self.assertTrue(len(t001) > 0)
        self.assertEqual(t001[0].severity, Severity.WARNING)


if __name__ == "__main__":
    unittest.main()
