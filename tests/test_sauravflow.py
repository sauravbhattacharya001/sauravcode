"""Tests for sauravflow -- CFG builder and renderers."""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import saurav as sv
from sauravflow import (
    CFG,
    CFGNode,
    _Builder,
    _expr_str,
    _truncate,
    build_all_cfgs,
    build_cfg,
    cfg_stats,
    render_dot,
    render_mermaid,
    render_text,
    summary_text,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse(source):
    """Tokenize + parse sauravcode source into AST nodes."""
    tokens = sv.tokenize(source)
    return sv.Parser(tokens).parse()


def _cfg_from(source, name="main"):
    """Build a CFG from sauravcode source."""
    return build_cfg(_parse(source), name=name)


# ---------------------------------------------------------------------------
# CFGNode
# ---------------------------------------------------------------------------

class TestCFGNode:
    def test_basic_creation(self):
        n = CFGNode("n0", "hello", "box", "statement")
        assert n.id == "n0"
        assert n.label == "hello"
        assert n.shape == "box"
        assert n.node_type == "statement"
        assert n.successors == []

    def test_add_edge(self):
        n = CFGNode("n0", "a")
        n.add_edge("n1", "yes")
        n.add_edge("n2")
        assert len(n.successors) == 2
        assert n.successors[0] == ("n1", "yes")
        assert n.successors[1] == ("n2", None)

    def test_repr(self):
        n = CFGNode("n0", "test")
        assert "n0" in repr(n)
        assert "test" in repr(n)


# ---------------------------------------------------------------------------
# CFG
# ---------------------------------------------------------------------------

class TestCFG:
    def test_empty(self):
        cfg = CFG("test")
        assert cfg.name == "test"
        assert cfg.node_count() == 0
        assert cfg.edge_count() == 0

    def test_new_node(self):
        cfg = CFG()
        n1 = cfg.new_node("first")
        n2 = cfg.new_node("second", "diamond", "decision")
        assert cfg.node_count() == 2
        assert n1.id == "n0"
        assert n2.id == "n1"
        assert n2.shape == "diamond"

    def test_edge_count(self):
        cfg = CFG()
        n1 = cfg.new_node("a")
        n2 = cfg.new_node("b")
        n1.add_edge(n2.id)
        assert cfg.edge_count() == 1


# ---------------------------------------------------------------------------
# _truncate and _expr_str helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_truncate_short(self):
        assert _truncate("hello", 50) == "hello"

    def test_truncate_long(self):
        s = "a" * 100
        result = _truncate(s, 20)
        assert len(result) == 20
        assert result.endswith("...")

    def test_expr_str_number(self):
        node = sv.NumberNode(42)
        assert _expr_str(node) == "42"

    def test_expr_str_string(self):
        node = sv.StringNode("hello")
        assert _expr_str(node) == "'hello'"

    def test_expr_str_bool(self):
        node = sv.BoolNode(True)
        assert _expr_str(node) == "true"

    def test_expr_str_identifier(self):
        node = sv.IdentifierNode("x")
        assert _expr_str(node) == "x"

    def test_expr_str_binary(self):
        node = sv.BinaryOpNode(sv.NumberNode(1), "+", sv.NumberNode(2))
        assert _expr_str(node) == "1 + 2"

    def test_expr_str_none(self):
        assert _expr_str(None) == "?"

    def test_expr_str_function_call(self):
        node = sv.FunctionCallNode("foo", [sv.NumberNode(1), sv.IdentifierNode("x")])
        assert _expr_str(node) == "foo(1, x)"

    def test_expr_str_unary(self):
        node = sv.UnaryOpNode("-", sv.NumberNode(5))
        assert _expr_str(node) == "- 5"

    def test_expr_str_list_short(self):
        node = sv.ListNode([sv.NumberNode(1), sv.NumberNode(2)])
        result = _expr_str(node)
        assert "[1, 2]" == result

    def test_expr_str_list_long(self):
        node = sv.ListNode([sv.NumberNode(i) for i in range(10)])
        result = _expr_str(node)
        assert "10 items" in result

    def test_expr_str_map(self):
        node = sv.MapNode([])
        assert _expr_str(node) == "{...}"

    def test_expr_str_fstring(self):
        node = sv.FStringNode([])
        assert _expr_str(node) == 'f"..."'


# ---------------------------------------------------------------------------
# build_cfg — basic programs
# ---------------------------------------------------------------------------

class TestBuildCFG:
    def test_empty_program(self):
        cfg = build_cfg([], "empty")
        assert cfg.name == "empty"
        # Should have at least the "(empty)" node
        assert cfg.node_count() >= 1

    def test_single_print(self):
        cfg = _cfg_from('print "hello"')
        # START, print, END
        assert cfg.node_count() == 3
        assert cfg.edge_count() == 2

    def test_assignment_and_print(self):
        cfg = _cfg_from('x = 5\nprint x')
        assert cfg.node_count() == 4  # START, assign, print, END
        assert cfg.edge_count() == 3

    def test_if_statement(self):
        source = 'x = 10\nif x > 5\n    print "big"'
        cfg = _cfg_from(source)
        # Should have decision node
        decision_nodes = [n for n in cfg.nodes.values() if n.node_type == "decision"]
        assert len(decision_nodes) >= 1

    def test_if_else(self):
        source = 'if x > 0\n    print "pos"\nelse\n    print "neg"'
        cfg = _cfg_from(source)
        decision_nodes = [n for n in cfg.nodes.values() if n.node_type == "decision"]
        assert len(decision_nodes) >= 1
        # Both branches should exist
        assert cfg.node_count() >= 5  # START, condition, print_pos, print_neg, END

    def test_while_loop(self):
        source = 'i = 0\nwhile i < 10\n    i = i + 1'
        cfg = _cfg_from(source)
        loop_nodes = [n for n in cfg.nodes.values() if n.node_type == "loop"]
        assert len(loop_nodes) >= 1
        # Loop node should have a back edge
        loop_node = loop_nodes[0]
        back_edges = [tid for tid, lbl in loop_node.successors if lbl == "yes"]
        assert len(back_edges) >= 1

    def test_for_loop(self):
        source = 'for i 0 10\n    print i'
        cfg = _cfg_from(source)
        loop_nodes = [n for n in cfg.nodes.values() if n.node_type == "loop"]
        assert len(loop_nodes) >= 1

    def test_foreach_loop(self):
        source = 'items = [1, 2, 3]\nfor item in items\n    print item'
        cfg = _cfg_from(source)
        loop_nodes = [n for n in cfg.nodes.values() if n.node_type == "loop"]
        assert len(loop_nodes) >= 1

    def test_return_terminates(self):
        source = 'function test x\n    return 42\n    print "unreachable"'
        ast = _parse(source)
        cfgs = build_all_cfgs(ast)
        fn_cfg = [c for c in cfgs if c.name == "test"][0]
        terminal_nodes = [n for n in fn_cfg.nodes.values() if "return" in n.label]
        assert len(terminal_nodes) >= 1

    def test_try_catch(self):
        source = 'try\n    x = 1 / 0\ncatch e\n    print e'
        cfg = _cfg_from(source)
        error_nodes = [n for n in cfg.nodes.values() if n.node_type == "error"]
        assert len(error_nodes) >= 2  # try + catch

    def test_throw(self):
        source = 'throw "error!"'
        cfg = _cfg_from(source)
        error_nodes = [n for n in cfg.nodes.values() if n.node_type == "error"]
        assert len(error_nodes) >= 1

    def test_break_and_continue(self):
        source = 'while true\n    if x > 5\n        break\n    continue'
        cfg = _cfg_from(source)
        labels = [n.label for n in cfg.nodes.values()]
        assert "break" in labels
        assert "continue" in labels

    def test_function_definition(self):
        source = 'function add a b\n    return a + b'
        ast = _parse(source)
        cfgs = build_all_cfgs(ast)
        fn_cfg = [c for c in cfgs if c.name == "add"][0]
        assert fn_cfg.node_count() >= 3  # START, return, END

    def test_match(self):
        source = 'x = 1\nmatch x\n    case 1\n        print "one"\n    case 2\n        print "two"'
        cfg = _cfg_from(source)
        decision_nodes = [n for n in cfg.nodes.values() if n.node_type == "decision"]
        assert len(decision_nodes) >= 1

    def test_import(self):
        cfg = _cfg_from('import "utils"')
        labels = [n.label for n in cfg.nodes.values()]
        assert any("import" in l for l in labels)

    def test_assert(self):
        cfg = _cfg_from('assert x > 0')
        labels = [n.label for n in cfg.nodes.values()]
        assert any("assert" in l for l in labels)

    def test_yield(self):
        cfg = _cfg_from('yield 42')
        labels = [n.label for n in cfg.nodes.values()]
        assert any("yield" in l for l in labels)

    def test_enum(self):
        source = 'enum Color\n    RED\n    GREEN\n    BLUE'
        cfg = _cfg_from(source)
        labels = [n.label for n in cfg.nodes.values()]
        assert any("enum" in l.lower() for l in labels)

    def test_append_and_pop(self):
        source = 'items = []\nappend items 1\npop items'
        cfg = _cfg_from(source)
        labels = [n.label for n in cfg.nodes.values()]
        assert any("append" in l for l in labels)
        assert any("pop" in l for l in labels)


# ---------------------------------------------------------------------------
# build_all_cfgs
# ---------------------------------------------------------------------------

class TestBuildAllCFGs:
    def test_multiple_functions(self):
        source = 'x = 1\nfunction foo a\n    return 1\nfunction bar b\n    return 2'
        cfgs = build_all_cfgs(_parse(source))
        names = [c.name for c in cfgs]
        assert "main" in names
        assert "foo" in names
        assert "bar" in names

    def test_no_top_level(self):
        source = 'function only x\n    return 0'
        cfgs = build_all_cfgs(_parse(source))
        names = [c.name for c in cfgs]
        assert "main" not in names
        assert "only" in names


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

class TestRenderMermaid:
    def test_basic_output(self):
        cfg = _cfg_from('print "hi"')
        result = render_mermaid(cfg)
        assert "```mermaid" in result
        assert "flowchart TD" in result
        assert "```" in result
        assert "print" in result

    def test_decision_shape(self):
        cfg = _cfg_from('if x > 0\n    print "yes"')
        result = render_mermaid(cfg)
        # Diamond nodes use {label} syntax
        assert "{" in result

    def test_edge_labels(self):
        cfg = _cfg_from('if x > 0\n    print "yes"\nelse\n    print "no"')
        result = render_mermaid(cfg)
        assert "yes" in result  # edge label


class TestRenderDot:
    def test_basic_output(self):
        cfg = _cfg_from('print "hi"')
        result = render_dot(cfg)
        assert "digraph" in result
        assert "rankdir=TB" in result
        assert "print" in result

    def test_colored_nodes(self):
        cfg = _cfg_from('if x > 0\n    print "yes"')
        result = render_dot(cfg)
        assert "fillcolor" in result

    def test_edge_labels_dot(self):
        cfg = _cfg_from('while x > 0\n    x = x - 1')
        result = render_dot(cfg)
        assert "label=" in result


class TestRenderText:
    def test_basic_output(self):
        cfg = _cfg_from('print "hi"')
        result = render_text(cfg)
        assert "===" in result
        assert "print" in result

    def test_empty_cfg(self):
        cfg = CFG("empty")
        result = render_text(cfg)
        assert "empty" in result.lower()

    def test_decision_display(self):
        cfg = _cfg_from('if x > 0\n    print "yes"')
        result = render_text(cfg)
        # Decision nodes display as /label\
        assert "/" in result or "\\" in result


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

class TestCFGStats:
    def test_simple_stats(self):
        cfg = _cfg_from('x = 1\nprint x')
        stats = cfg_stats(cfg)
        assert stats["name"] == "main"
        assert stats["nodes"] == 4
        assert stats["edges"] == 3
        assert stats["cyclomatic_complexity"] >= 1

    def test_branching_increases_complexity(self):
        simple_cfg = _cfg_from('x = 1')
        branch_cfg = _cfg_from('if x > 0\n    print "a"\nelse\n    print "b"')
        simple_cc = cfg_stats(simple_cfg)["cyclomatic_complexity"]
        branch_cc = cfg_stats(branch_cfg)["cyclomatic_complexity"]
        assert branch_cc > simple_cc

    def test_summary_text(self):
        cfgs = build_all_cfgs(_parse('function f x\n    return 1\nfunction g x\n    if x > 0\n        return 1\n    return 0'))
        result = summary_text(cfgs)
        assert "Function" in result
        assert "Nodes" in result
        assert "CC" in result


# ---------------------------------------------------------------------------
# CLI (_parse_args + main)
# ---------------------------------------------------------------------------

class TestCLI:
    def test_parse_args_defaults(self):
        from sauravflow import _parse_args
        args = _parse_args(["test.srv"])
        assert args["files"] == ["test.srv"]
        assert args["format"] == "mermaid"
        assert args["function"] is None
        assert args["all_functions"] is False
        assert args["output"] is None

    def test_parse_args_format(self):
        from sauravflow import _parse_args
        args = _parse_args(["test.srv", "--format", "dot"])
        assert args["format"] == "dot"

    def test_parse_args_function(self):
        from sauravflow import _parse_args
        args = _parse_args(["test.srv", "--function", "foo"])
        assert args["function"] == "foo"

    def test_parse_args_all_functions(self):
        from sauravflow import _parse_args
        args = _parse_args(["test.srv", "--all-functions"])
        assert args["all_functions"] is True

    def test_parse_args_stats(self):
        from sauravflow import _parse_args
        args = _parse_args(["test.srv", "--stats"])
        assert args["stats"] is True

    def test_main_with_file(self):
        from sauravflow import main
        with tempfile.NamedTemporaryFile(mode="w", suffix=".srv", delete=False, encoding="utf-8") as f:
            f.write('x = 10\nprint x')
            f.flush()
            tmpname = f.name
        try:
            # Should not raise
            main([tmpname])
        finally:
            os.unlink(tmpname)

    def test_main_with_output(self):
        from sauravflow import main
        with tempfile.NamedTemporaryFile(mode="w", suffix=".srv", delete=False, encoding="utf-8") as f:
            f.write('print "hello"')
            f.flush()
            tmpname = f.name
        outfile = tmpname + ".md"
        try:
            main([tmpname, "-o", outfile])
            assert os.path.exists(outfile)
            content = open(outfile, encoding="utf-8").read()
            assert "mermaid" in content
        finally:
            os.unlink(tmpname)
            if os.path.exists(outfile):
                os.unlink(outfile)

    def test_main_dot_format(self):
        from sauravflow import main
        with tempfile.NamedTemporaryFile(mode="w", suffix=".srv", delete=False, encoding="utf-8") as f:
            f.write('if x > 0\n    print "yes"')
            f.flush()
            tmpname = f.name
        outfile = tmpname + ".dot"
        try:
            main([tmpname, "--format", "dot", "-o", outfile])
            content = open(outfile, encoding="utf-8").read()
            assert "digraph" in content
        finally:
            os.unlink(tmpname)
            if os.path.exists(outfile):
                os.unlink(outfile)

    def test_main_no_files_exits(self):
        from sauravflow import main
        with pytest.raises(SystemExit):
            main([])

    def test_main_bad_format_exits(self):
        from sauravflow import main
        with tempfile.NamedTemporaryFile(mode="w", suffix=".srv", delete=False, encoding="utf-8") as f:
            f.write('print 1')
            f.flush()
            tmpname = f.name
        try:
            with pytest.raises(SystemExit):
                main([tmpname, "--format", "invalid"])
        finally:
            os.unlink(tmpname)


# ---------------------------------------------------------------------------
# Edge cases & complex programs
# ---------------------------------------------------------------------------

class TestComplexPrograms:
    def test_nested_if_while(self):
        source = '''i = 0
while i < 10
    if i > 5
        print "big"
    else
        print "small"
    i = i + 1'''
        cfg = _cfg_from(source)
        assert cfg.node_count() >= 6
        assert cfg.edge_count() >= 6

    def test_elif_chain(self):
        source = '''if x > 10
    print "big"
else if x > 5
    print "medium"
else if x > 0
    print "small"
else
    print "negative"'''
        cfg = _cfg_from(source)
        decision_nodes = [n for n in cfg.nodes.values() if n.node_type == "decision"]
        assert len(decision_nodes) == 3  # 3 conditions

    def test_cyclomatic_complexity_grows(self):
        """More branches = higher complexity."""
        src1 = 'print 1'
        src2 = 'if a > 0\n    print 1\nif b > 0\n    print 2'
        src3 = 'if a > 0\n    print 1\nif b > 0\n    print 2\nif c > 0\n    print 3'
        cc1 = cfg_stats(_cfg_from(src1))["cyclomatic_complexity"]
        cc2 = cfg_stats(_cfg_from(src2))["cyclomatic_complexity"]
        cc3 = cfg_stats(_cfg_from(src3))["cyclomatic_complexity"]
        assert cc1 <= cc2 <= cc3

    def test_all_formats_produce_output(self):
        source = 'x = 1\nif x > 0\n    print x\nwhile x < 10\n    x = x + 1'
        cfg = _cfg_from(source)
        mermaid = render_mermaid(cfg)
        dot = render_dot(cfg)
        text = render_text(cfg)
        assert len(mermaid) > 50
        assert len(dot) > 50
        assert len(text) > 20
