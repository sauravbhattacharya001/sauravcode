"""Tests for sauravast.py — AST visualizer for sauravcode."""

import sys
import os
import json
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from saurav import tokenize, Parser, ASTNode
from sauravast import (
    node_to_dict,
    collect_stats,
    _node_children,
    _tree_lines,
    _format_leaf,
    _dot_lines,
    print_tree,
    print_dot,
)


# ── Helpers ──────────────────────────────────────────────────────────

def parse(code):
    """Parse sauravcode source and return AST node list."""
    tokens = list(tokenize(code))
    p = Parser(tokens)
    return p.parse()


# ── node_to_dict ─────────────────────────────────────────────────────

class TestNodeToDict:
    def test_simple_assignment(self):
        nodes = parse("x = 5")
        d = node_to_dict(nodes[0])
        assert d["_type"] == "AssignmentNode"
        assert d["name"] == "x"

    def test_returns_json_serializable(self):
        nodes = parse('msg = "hello"')
        d = node_to_dict(nodes[0])
        # Should not raise
        json.dumps(d, default=str)

    def test_function_def(self):
        nodes = parse('function greet name\n    return "hi"')
        d = node_to_dict(nodes[0])
        assert d["_type"] == "FunctionNode"
        assert "params" in d
        assert "body" in d

    def test_depth_truncation(self):
        nodes = parse("x = 1 + 2 + 3")
        d = node_to_dict(nodes[0], depth=1)
        # At depth 1, nested nodes should be truncated
        assert d["_type"] == "AssignmentNode"

    def test_depth_zero_truncates_immediately(self):
        nodes = parse("x = 5")
        d = node_to_dict(nodes[0], depth=0)
        assert d["_truncated"] is True

    def test_list_children(self):
        nodes = parse("x = [1, 2, 3]")
        d = node_to_dict(nodes[0])
        assert isinstance(d["expression"], dict) or isinstance(d["expression"], list)

    def test_nested_expression(self):
        nodes = parse("y = (1 + 2) * 3")
        d = node_to_dict(nodes[0])
        assert d["_type"] == "AssignmentNode"
        # expression should be a BinaryOpNode
        assert "expression" in d

    def test_if_statement(self):
        nodes = parse("if x > 0\n    y = 1")
        d = node_to_dict(nodes[0])
        assert d["_type"] == "IfNode"
        assert "condition" in d
        assert "body" in d

    def test_while_loop(self):
        nodes = parse("while x > 0\n    x = x - 1")
        d = node_to_dict(nodes[0])
        assert d["_type"] == "WhileNode"

    def test_plain_value_passthrough(self):
        assert node_to_dict(42) == 42
        assert node_to_dict("hello") == "hello"
        assert node_to_dict(None) is None

    def test_list_of_non_nodes(self):
        result = node_to_dict([1, 2, 3])
        assert result == [1, 2, 3]

    def test_tuple_handling(self):
        result = node_to_dict((1, 2))
        assert isinstance(result, list)
        assert result == [1, 2]


# ── _node_children ───────────────────────────────────────────────────

class TestNodeChildren:
    def test_skips_private_attrs(self):
        nodes = parse("x = 5")
        children = _node_children(nodes[0])
        labels = [label for label, _ in children]
        assert all(not l.startswith("_") for l in labels)

    def test_skips_line_num(self):
        nodes = parse("x = 5")
        children = _node_children(nodes[0])
        labels = [label for label, _ in children]
        assert "line_num" not in labels

    def test_sorted_attributes(self):
        nodes = parse("x = 5")
        children = _node_children(nodes[0])
        labels = [label for label, _ in children]
        assert labels == sorted(labels)

    def test_returns_pairs(self):
        nodes = parse("x = 5")
        children = _node_children(nodes[0])
        for item in children:
            assert len(item) == 2


# ── _format_leaf ─────────────────────────────────────────────────────

class TestFormatLeaf:
    def test_string_repr(self):
        assert _format_leaf("hello") == "'hello'"

    def test_integer(self):
        assert _format_leaf(42) == "42"

    def test_float(self):
        assert _format_leaf(3.14) == "3.14"

    def test_none(self):
        assert _format_leaf(None) == "None"

    def test_bool(self):
        assert _format_leaf(True) == "True"

    def test_list(self):
        result = _format_leaf([1, 2])
        assert result == "[1, 2]"


# ── collect_stats ────────────────────────────────────────────────────

class TestCollectStats:
    def test_simple_program(self):
        nodes = parse("x = 5")
        stats = collect_stats(nodes)
        assert stats["total_nodes"] >= 1
        assert stats["max_depth"] >= 0
        assert "AssignmentNode" in stats["node_types"]

    def test_empty_program(self):
        stats = collect_stats([])
        assert stats["total_nodes"] == 0
        assert stats["max_depth"] == 0
        assert stats["node_types"] == {}

    def test_nested_increases_depth(self):
        simple = collect_stats(parse("x = 5"))
        nested = collect_stats(parse("if x > 0\n    if y > 0\n        z = 1"))
        assert nested["max_depth"] >= simple["max_depth"]

    def test_multiple_node_types(self):
        nodes = parse("x = 5\ny = x + 1\nif y > 3\n    print y")
        stats = collect_stats(nodes)
        assert len(stats["node_types"]) >= 3

    def test_function_stats(self):
        nodes = parse('function add a b\n    return a + b\nresult = (add 1 2)')
        stats = collect_stats(nodes)
        assert "FunctionNode" in stats["node_types"]
        assert stats["total_nodes"] >= 5

    def test_loop_stats(self):
        nodes = parse("i = 0\nwhile i < 5\n    i = i + 1")
        stats = collect_stats(nodes)
        assert "WhileNode" in stats["node_types"]

    def test_node_count_consistency(self):
        nodes = parse("a = 1\nb = 2\nc = a + b")
        stats = collect_stats(nodes)
        assert stats["total_nodes"] == sum(stats["node_types"].values())


# ── _tree_lines ──────────────────────────────────────────────────────

class TestTreeLines:
    def test_produces_output(self):
        nodes = parse("x = 5")
        lines = list(_tree_lines(nodes[0]))
        assert len(lines) >= 1
        assert "AssignmentNode" in lines[0]

    def test_depth_limit(self):
        nodes = parse("x = 1 + 2")
        full = list(_tree_lines(nodes[0]))
        limited = list(_tree_lines(nodes[0], depth=1))
        assert len(limited) <= len(full)

    def test_contains_attribute_labels(self):
        nodes = parse("x = 5")
        lines = list(_tree_lines(nodes[0]))
        text = "\n".join(lines)
        assert "name" in text
        assert "value" in text

    def test_list_children_formatting(self):
        nodes = parse("x = [1, 2, 3]")
        lines = list(_tree_lines(nodes[0]))
        text = "\n".join(lines)
        assert "items" in text.lower() or "[" in text

    def test_plain_value(self):
        lines = list(_tree_lines(42))
        assert lines == ["42"]

    def test_string_value(self):
        lines = list(_tree_lines("hello"))
        assert lines == ["'hello'"]

    def test_nested_function(self):
        nodes = parse('function f x\n    return x + 1')
        lines = list(_tree_lines(nodes[0]))
        text = "\n".join(lines)
        assert "FunctionNode" in text
        assert "body" in text


# ── _dot_lines (Graphviz DOT output) ────────────────────────────────

class TestDotLines:
    def test_produces_valid_dot(self):
        nodes = parse("x = 5")
        lines = list(_dot_lines(nodes))
        dot = "\n".join(lines)
        assert dot.startswith("digraph AST {")
        assert dot.endswith("}")

    def test_contains_nodes(self):
        nodes = parse("x = 5")
        dot = "\n".join(_dot_lines(nodes))
        assert "Program" in dot
        assert "Assignment" in dot

    def test_contains_edges(self):
        nodes = parse("x = 5")
        dot = "\n".join(_dot_lines(nodes))
        assert "->" in dot

    def test_multiple_statements(self):
        nodes = parse("x = 1\ny = 2")
        dot = "\n".join(_dot_lines(nodes))
        assert dot.count("->") >= 2

    def test_function_in_dot(self):
        nodes = parse('function greet\n    return "hi"')
        dot = "\n".join(_dot_lines(nodes))
        assert "Function" in dot

    def test_empty_program(self):
        dot = "\n".join(_dot_lines([]))
        assert "digraph AST {" in dot
        assert "Program" in dot


# ── print_tree / print_dot (stdout capture) ──────────────────────────

class TestPrintFunctions:
    def test_print_tree_output(self, capsys):
        nodes = parse("x = 5")
        print_tree(nodes)
        captured = capsys.readouterr()
        assert "Program" in captured.out
        assert "Assignment" in captured.out

    def test_print_tree_with_depth(self, capsys):
        nodes = parse("x = 1 + 2 * 3")
        print_tree(nodes, depth=2)
        captured = capsys.readouterr()
        assert "Program" in captured.out
        assert "..." in captured.out  # truncated nodes

    def test_print_tree_multiple_statements(self, capsys):
        nodes = parse("a = 1\nb = 2\nc = 3")
        print_tree(nodes)
        captured = capsys.readouterr()
        assert captured.out.count("AssignmentNode") == 3

    def test_print_dot_output(self, capsys):
        nodes = parse("x = 5")
        print_dot(nodes)
        captured = capsys.readouterr()
        assert "digraph AST" in captured.out
        assert "}" in captured.out

    def test_print_tree_empty(self, capsys):
        print_tree([])
        captured = capsys.readouterr()
        assert "Program" in captured.out


# ── Integration: round-trip dict → JSON ──────────────────────────────

class TestIntegration:
    def test_complex_program_to_json(self):
        code = """
x = 10
y = 20
function add a b
    return a + b
result = (add x y)
if result > 25
    print "big"
"""
        nodes = parse(code.strip())
        data = [node_to_dict(n) for n in nodes]
        # Should be fully JSON-serializable
        text = json.dumps(data, indent=2, default=str)
        parsed_back = json.loads(text)
        assert isinstance(parsed_back, list)
        assert len(parsed_back) >= 4

    def test_for_loop_ast(self):
        nodes = parse("for i in [1, 2, 3]\n    print i")
        d = node_to_dict(nodes[0])
        assert d["_type"] == "ForEachNode"
        stats = collect_stats(nodes)
        assert stats["total_nodes"] >= 3

    def test_try_catch(self):
        code = 'try\n    x = 1 / 0\ncatch e\n    print e'
        nodes = parse(code)
        d = node_to_dict(nodes[0])
        assert "Try" in d["_type"] or "try" in d["_type"].lower()

    def test_match_statement(self):
        code = 'x = 5\nmatch x\n    case 5\n        print "five"'
        nodes = parse(code)
        stats = collect_stats(nodes)
        assert stats["total_nodes"] >= 3

    def test_stats_and_tree_agree_on_types(self):
        nodes = parse("a = 1\nb = a + 2")
        stats = collect_stats(nodes)
        tree_text = "\n".join(
            line for node in nodes for line in _tree_lines(node)
        )
        # Every type in stats should appear in tree output
        for node_type in stats["node_types"]:
            # Node type names show up without "Node" suffix in tree sometimes
            base = node_type.replace("Node", "")
            assert base in tree_text or node_type in tree_text
