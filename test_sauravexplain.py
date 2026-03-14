#!/usr/bin/env python3
"""Tests for sauravexplain -- Code-to-English narrator."""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sauravexplain import (
    describe_expr, explain_node, explain, generate_summary, generate_toc,
    format_explanation, to_json, parse_line_range, filter_by_lines,
)
from saurav import (
    tokenize, Parser, ASTNode,
    NumberNode, StringNode, BoolNode, IdentifierNode,
    BinaryOpNode, CompareNode, LogicalNode, UnaryOpNode,
    FunctionCallNode, ListNode, MapNode, IndexNode, SliceNode,
    LenNode, FStringNode, LambdaNode, TernaryNode,
    EnumAccessNode, ListComprehensionNode,
    AssignmentNode, FunctionNode, ReturnNode, YieldNode,
    PrintNode, IfNode, WhileNode, ForNode, ForEachNode,
    TryCatchNode, ThrowNode, ImportNode, AppendNode,
    IndexedAssignmentNode, EnumNode, MatchNode, CaseNode,
    AssertNode, BreakNode, ContinueNode,
)

_pass = 0
_fail = 0


def check(label, got, expected):
    global _pass, _fail
    if got == expected:
        _pass += 1
    else:
        _fail += 1
        print(f"FAIL: {label}")
        print(f"  expected: {expected!r}")
        print(f"  got:      {got!r}")


def parse_one(code):
    """Parse code and return the first AST node."""
    tokens = tokenize(code)
    return Parser(tokens).parse()[0]


def parse_expr(code):
    """Parse 'x = <expr>' and return the expression node."""
    node = parse_one(f"x = {code}")
    return node.expression


# ── Expression descriptions ─────────────────────────────────────

def test_describe_number():
    check("integer", describe_expr(parse_expr("42")), "42")
    check("float", describe_expr(parse_expr("3.14")), "3.14")
    check("zero", describe_expr(parse_expr("0")), "0")

def test_describe_string():
    check("string", describe_expr(parse_expr('"hello"')), '"hello"')

def test_describe_bool():
    check("true", describe_expr(parse_expr("true")), "true")
    check("false", describe_expr(parse_expr("false")), "false")

def test_describe_identifier():
    check("ident", describe_expr(parse_expr("foo")), "foo")

def test_describe_binary_op():
    check("add", describe_expr(parse_expr("a + b")), "a plus b")
    check("sub", describe_expr(parse_expr("a - b")), "a minus b")
    check("mul", describe_expr(parse_expr("a * b")), "a times b")
    check("div", describe_expr(parse_expr("a / b")), "a divided by b")
    check("mod", describe_expr(parse_expr("a % b")), "a modulo b")

def test_describe_compare():
    check("eq", describe_expr(parse_expr("a == b")), "a equals b")
    check("neq", describe_expr(parse_expr("a != b")), "a does not equal b")
    check("lt", describe_expr(parse_expr("a < b")), "a is less than b")
    check("gt", describe_expr(parse_expr("a > b")), "a is greater than b")
    check("lte", describe_expr(parse_expr("a <= b")), "a is at most b")
    check("gte", describe_expr(parse_expr("a >= b")), "a is at least b")

def test_describe_logical():
    check("and", describe_expr(parse_expr("a and b")), "a and b")
    check("or", describe_expr(parse_expr("a or b")), "a or b")

def test_describe_unary():
    check("not", describe_expr(parse_expr("not x")), "not x")
    check("neg", describe_expr(parse_expr("0 - x")), "0 minus x")

def test_describe_function_call():
    node = parse_one("function t\n    x = f 1 2")
    fc = node.body[0].expression
    desc = describe_expr(fc)
    check("call", desc, "call f with 1, 2")

def test_describe_function_call_no_args():
    node = parse_one("function t\n    x = f")
    # f is an IdentifierNode, not FunctionCallNode
    expr = node.body[0].expression
    check("ident-as-func", describe_expr(expr), "f")

def test_describe_list_empty():
    check("empty list", describe_expr(parse_expr("[]")), "an empty list")

def test_describe_list_small():
    desc = describe_expr(parse_expr("[1, 2, 3]"))
    check("small list", desc, "[1, 2, 3]")

def test_describe_map_small():
    desc = describe_expr(parse_expr('{"a": 1}'))
    check("small map", desc, '{"a": 1}')

def test_describe_map_empty():
    desc = describe_expr(parse_expr("{}"))
    check("empty map", desc, "an empty map")

def test_describe_index():
    node = parse_one("function t\n    x = nums[0]")
    expr = node.body[0].expression
    check("index", describe_expr(expr), "nums[0]")

def test_describe_slice():
    node = parse_one("function t\n    x = nums[1:3]")
    expr = node.body[0].expression
    check("slice", describe_expr(expr), "slice of nums from 1 to 3")

def test_describe_fstring_simple():
    node = parse_one('function t\n    x = f"hi {name}"')
    expr = node.body[0].expression
    desc = describe_expr(expr)
    check("fstring simple", desc, "a formatted string with name")

def test_describe_fstring_multi():
    node = parse_one('function t\n    x = f"{a} and {b}"')
    expr = node.body[0].expression
    desc = describe_expr(expr)
    check("fstring multi", desc, "a formatted string with a, b")

def test_describe_ternary():
    node = parse_one("function t\n    x = 1 if true else 0")
    expr = node.body[0].expression
    desc = describe_expr(expr)
    check("ternary", desc, "1 if true, otherwise 0")

def test_describe_list_comp():
    node = parse_one("function t\n    x = [i * 2 for i in nums]")
    expr = node.body[0].expression
    desc = describe_expr(expr)
    check("list comp", desc, "[(i times 2) for each i in nums]")

def test_describe_enum_access():
    code = "enum Color\n    Red\nfunction t\n    x = Color.Red"
    nodes = Parser(tokenize(code)).parse()
    fn = nodes[1]
    expr = fn.body[0].expression
    check("enum access", describe_expr(expr), "Color.Red")


# ── Statement explanations ──────────────────────────────────────

def test_explain_assignment():
    node = parse_one("x = 42")
    entries = explain_node(node)
    check("assign text", entries[0][1], "Set x to 42")

def test_explain_print():
    node = parse_one('print "hello"')
    entries = explain_node(node)
    check("print text", entries[0][1], 'Print "hello"')

def test_explain_function():
    node = parse_one("function greet name\n    return name")
    entries = explain_node(node)
    check("func def", entries[0][1], "Define function 'greet' (name)")
    check("func return", entries[1][1], "Return name")
    check("func indent", entries[1][0], 1)

def test_explain_if_else():
    code = "if x == 1\n    print x\nelse\n    print 0"
    node = parse_one(code)
    entries = explain_node(node)
    check("if cond", entries[0][1], "If x equals 1:")
    check("if body", entries[1][1], "Print x")
    check("else label", entries[2][1], "Otherwise:")
    check("else body", entries[3][1], "Print 0")

def test_explain_elif():
    code = "if x == 1\n    print 1\nelse if x == 2\n    print 2\nelse\n    print 0"
    node = parse_one(code)
    entries = explain_node(node)
    check("elif", entries[2][1], "Otherwise, if x equals 2:")

def test_explain_while():
    code = "while x > 0\n    x = x - 1"
    node = parse_one(code)
    entries = explain_node(node)
    check("while", entries[0][1], "Repeat while x is greater than 0:")

def test_explain_for():
    code = "for i 1 10\n    print i"
    node = parse_one(code)
    entries = explain_node(node)
    check("for", entries[0][1], "Count i from 1 to 10:")

def test_explain_foreach():
    code = "for item in items\n    print item"
    node = parse_one(code)
    entries = explain_node(node)
    check("foreach", entries[0][1], "For each item in items:")

def test_explain_try_catch():
    code = "try\n    x = 1 / 0\ncatch err\n    print err"
    node = parse_one(code)
    entries = explain_node(node)
    check("try", entries[0][1], "Try:")
    check("try body", entries[1][1], "Set x to 1 divided by 0")
    check("catch", entries[2][1], "If an error occurs (caught as 'err'):")
    check("catch body", entries[3][1], "Print err")

def test_explain_throw():
    code = 'throw "error"'
    node = parse_one(code)
    entries = explain_node(node)
    check("throw", entries[0][1], 'Throw error: "error"')

def test_explain_return():
    code = "function f\n    return 42"
    node = parse_one(code)
    entries = explain_node(node)
    check("return", entries[1][1], "Return 42")

def test_explain_yield():
    code = "function f\n    yield 10"
    node = parse_one(code)
    entries = explain_node(node)
    check("yield", entries[1][1], "Yield 10")

def test_explain_import():
    code = 'import "utils"'
    node = parse_one(code)
    entries = explain_node(node)
    check("import", entries[0][1], "Import module 'utils'")

def test_explain_append():
    code = "function f\n    append nums 1"
    node = parse_one(code)
    entries = explain_node(node)
    check("append", entries[1][1], "Append 1 to nums")

def test_explain_indexed_assign():
    code = "function f\n    x[0] = 99"
    node = parse_one(code)
    entries = explain_node(node)
    check("idx assign", entries[1][1], "Set x[0] to 99")

def test_explain_enum():
    code = "enum Color\n    Red\n    Green\n    Blue"
    node = parse_one(code)
    entries = explain_node(node)
    check("enum", entries[0][1], "Define enum 'Color' with variants: Red, Green, Blue")

def test_explain_match():
    code = "match x\n    case 1\n        print 1\n    case 2\n        print 2"
    node = parse_one(code)
    entries = explain_node(node)
    check("match", entries[0][1], "Match x against:")
    check("case1", entries[1][1], "Case 1:")
    check("case1 body", entries[2][1], "Print 1")

def test_explain_assert():
    code = 'assert true "should be true"'
    node = parse_one(code)
    entries = explain_node(node)
    check("assert", entries[0][1], 'Assert that true, or fail with "should be true"')

def test_explain_break():
    code = "while true\n    break"
    node = parse_one(code)
    entries = explain_node(node)
    check("break", entries[1][1], "Break out of the loop")

def test_explain_continue():
    code = "while true\n    continue"
    node = parse_one(code)
    entries = explain_node(node)
    check("continue", entries[1][1], "Skip to the next iteration")

def test_explain_verbose():
    node = parse_one("x = 5")
    entries = explain_node(node, verbose=True)
    check("verbose tag", "AssignmentNode" in entries[0][1], True)

def test_explain_depth_limit():
    code = "if true\n    if true\n        print 1"
    node = parse_one(code)
    entries = explain_node(node, max_depth=0)
    check("depth 0", "deeper code omitted" in entries[1][1], True)


# ── Summary ─────────────────────────────────────────────────────

def test_summary_functions():
    code = "function add a b\n    return a + b\nfunction sub a b\n    return a - b"
    nodes = Parser(tokenize(code)).parse()
    summary = generate_summary(nodes)
    check("summary has add", "add" in summary, True)
    check("summary has sub", "sub" in summary, True)
    check("summary count", "Functions (2)" in summary, True)

def test_summary_features():
    code = "try\n    print 1\ncatch e\n    print e\nfor i 1 5\n    print i"
    nodes = Parser(tokenize(code)).parse()
    summary = generate_summary(nodes)
    check("summary error", "error handling" in summary, True)
    check("summary loops", "loops" in summary, True)

def test_summary_enum():
    code = "enum Color\n    Red"
    nodes = Parser(tokenize(code)).parse()
    summary = generate_summary(nodes)
    check("summary enum", "Color" in summary, True)

def test_summary_import():
    code = 'import "utils"'
    nodes = Parser(tokenize(code)).parse()
    summary = generate_summary(nodes)
    check("summary import", "utils" in summary, True)


# ── Table of contents ───────────────────────────────────────────

def test_toc_functions():
    code = "function greet name\n    return name\nfunction add a b\n    return a + b"
    nodes = Parser(tokenize(code)).parse()
    toc = generate_toc(nodes)
    check("toc greet", "greet" in toc, True)
    check("toc add", "add" in toc, True)

def test_toc_enum():
    code = "enum Status\n    Active\n    Inactive"
    nodes = Parser(tokenize(code)).parse()
    toc = generate_toc(nodes)
    check("toc enum", "Status" in toc, True)

def test_toc_empty():
    code = "x = 5"
    nodes = Parser(tokenize(code)).parse()
    toc = generate_toc(nodes)
    check("toc empty", "no named definitions" in toc, True)


# ── Formatting ──────────────────────────────────────────────────

def test_format_numbered():
    entries = [(0, "First", None), (1, "Nested", None), (0, "Third", None)]
    text = format_explanation(entries)
    check("numbered 1", "1." in text, True)
    check("numbered 3", "3." in text, True)

def test_format_no_lines():
    entries = [(0, "Hello", None)]
    text = format_explanation(entries, show_lines=False)
    check("no line nums", "1." not in text, True)

def test_to_json():
    entries = [(0, "Test", 5), (1, "Nested", None)]
    result = to_json(entries)
    check("json len", len(result), 2)
    check("json text", result[0]["text"], "Test")
    check("json indent", result[1]["indent"], 1)


# ── Line range ──────────────────────────────────────────────────

def test_parse_range_single():
    check("range single", parse_line_range("5"), (5, 5))

def test_parse_range_span():
    check("range span", parse_line_range("10-20"), (10, 20))


# ── Full pipeline ──────────────────────────────────────────────

def test_explain_full():
    code = 'print "hello"\nx = 5\nprint x'
    nodes, entries = explain(code)
    check("pipeline count", len(entries), 3)
    check("pipeline first", entries[0][1], 'Print "hello"')

def test_explain_with_depth():
    code = "if true\n    if true\n        print 1"
    nodes, entries = explain(code, max_depth=0)
    check("depth limit", any("omitted" in e[1] for e in entries), True)

def test_explain_verbose_pipeline():
    code = "x = 5"
    nodes, entries = explain(code, verbose=True)
    check("verbose pipeline", "AssignmentNode" in entries[0][1], True)


# ── Demo files ──────────────────────────────────────────────────

def test_all_demo_files():
    """Verify sauravexplain parses every .srv file without crashing."""
    project_dir = os.path.dirname(os.path.abspath(__file__))
    srv_files = [f for f in os.listdir(project_dir) if f.endswith('.srv')]
    for fname in sorted(srv_files):
        path = os.path.join(project_dir, fname)
        with open(path, 'r', encoding='utf-8') as fh:
            source = fh.read()
        try:
            nodes, entries = explain(source)
            check(f"demo {fname}", len(entries) > 0, True)
        except Exception as e:
            check(f"demo {fname} no crash", False, True)


# ── Run all ─────────────────────────────────────────────────────

if __name__ == '__main__':
    test_describe_number()
    test_describe_string()
    test_describe_bool()
    test_describe_identifier()
    test_describe_binary_op()
    test_describe_compare()
    test_describe_logical()
    test_describe_unary()
    test_describe_function_call()
    test_describe_function_call_no_args()
    test_describe_list_empty()
    test_describe_list_small()
    test_describe_map_small()
    test_describe_map_empty()
    test_describe_index()
    test_describe_slice()
    test_describe_fstring_simple()
    test_describe_fstring_multi()
    test_describe_ternary()
    test_describe_list_comp()
    test_describe_enum_access()
    test_explain_assignment()
    test_explain_print()
    test_explain_function()
    test_explain_if_else()
    test_explain_elif()
    test_explain_while()
    test_explain_for()
    test_explain_foreach()
    test_explain_try_catch()
    test_explain_throw()
    test_explain_return()
    test_explain_yield()
    test_explain_import()
    test_explain_append()
    test_explain_indexed_assign()
    test_explain_enum()
    test_explain_match()
    test_explain_assert()
    test_explain_break()
    test_explain_continue()
    test_explain_verbose()
    test_explain_depth_limit()
    test_summary_functions()
    test_summary_features()
    test_summary_enum()
    test_summary_import()
    test_toc_functions()
    test_toc_enum()
    test_toc_empty()
    test_format_numbered()
    test_format_no_lines()
    test_to_json()
    test_parse_range_single()
    test_parse_range_span()
    test_explain_full()
    test_explain_with_depth()
    test_explain_verbose_pipeline()
    test_all_demo_files()

    total = _pass + _fail
    print(f"\n{'='*50}")
    print(f"Results: {_pass}/{total} passed, {_fail} failed")
    if _fail == 0:
        print("All tests passed!")
    else:
        sys.exit(1)
