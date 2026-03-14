"""Tests for sauravflow -- control flow diagram generator."""

import os
import sys
import unittest
import tempfile

# Ensure saurav and sauravflow are importable
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import saurav as sv
from sauravflow import (
    CFG, CFGNode, build_cfg, build_all_cfgs,
    render_mermaid, render_dot, render_text,
    cfg_stats, summary_text, _expr_str, main,
)


def _parse(source):
    """Parse sauravcode source into AST nodes."""
    tokens = sv.tokenize(source)
    return sv.Parser(tokens).parse()


# ── CFG Data Structures ────────────────────────────────────────────

class TestCFGNode(unittest.TestCase):

    def test_create_node(self):
        n = CFGNode("n0", "test", "box", "statement")
        self.assertEqual(n.id, "n0")
        self.assertEqual(n.label, "test")
        self.assertEqual(n.shape, "box")
        self.assertEqual(n.node_type, "statement")
        self.assertEqual(n.successors, [])

    def test_add_edge(self):
        n = CFGNode("n0", "test")
        n.add_edge("n1", "yes")
        n.add_edge("n2")
        self.assertEqual(len(n.successors), 2)
        self.assertEqual(n.successors[0], ("n1", "yes"))
        self.assertEqual(n.successors[1], ("n2", None))

    def test_repr(self):
        n = CFGNode("n0", "hello")
        self.assertIn("hello", repr(n))


class TestCFG(unittest.TestCase):

    def test_empty_cfg(self):
        cfg = CFG("test")
        self.assertEqual(cfg.name, "test")
        self.assertEqual(cfg.node_count(), 0)
        self.assertEqual(cfg.edge_count(), 0)

    def test_new_node(self):
        cfg = CFG()
        n1 = cfg.new_node("a")
        n2 = cfg.new_node("b")
        self.assertEqual(cfg.node_count(), 2)
        self.assertNotEqual(n1.id, n2.id)

    def test_edge_count(self):
        cfg = CFG()
        n1 = cfg.new_node("a")
        n2 = cfg.new_node("b")
        n1.add_edge(n2.id)
        self.assertEqual(cfg.edge_count(), 1)


# ── Expression Pretty-Printer ──────────────────────────────────────

class TestExprStr(unittest.TestCase):

    def test_number(self):
        self.assertEqual(_expr_str(sv.NumberNode(42)), "42")

    def test_string(self):
        result = _expr_str(sv.StringNode("hello"))
        self.assertIn("hello", result)

    def test_bool(self):
        self.assertEqual(_expr_str(sv.BoolNode(True)), "true")

    def test_identifier(self):
        self.assertEqual(_expr_str(sv.IdentifierNode("x")), "x")

    def test_binary_op(self):
        node = sv.BinaryOpNode(sv.NumberNode(1), "+", sv.NumberNode(2))
        self.assertEqual(_expr_str(node), "1 + 2")

    def test_compare(self):
        node = sv.CompareNode(sv.IdentifierNode("x"), ">", sv.NumberNode(0))
        self.assertEqual(_expr_str(node), "x > 0")

    def test_function_call(self):
        node = sv.FunctionCallNode("foo", [sv.NumberNode(1), sv.NumberNode(2)])
        self.assertEqual(_expr_str(node), "foo(1, 2)")

    def test_unary(self):
        node = sv.UnaryOpNode("not", sv.BoolNode(True))
        self.assertEqual(_expr_str(node), "not true")

    def test_lambda(self):
        node = sv.LambdaNode(["x"], sv.BinaryOpNode(sv.IdentifierNode("x"), "*", sv.NumberNode(2)))
        result = _expr_str(node)
        self.assertIn("lambda", result)

    def test_none(self):
        self.assertEqual(_expr_str(None), "?")

    def test_list_short(self):
        node = sv.ListNode([sv.NumberNode(1), sv.NumberNode(2)])
        self.assertEqual(_expr_str(node), "[1, 2]")

    def test_list_long(self):
        node = sv.ListNode([sv.NumberNode(i) for i in range(5)])
        result = _expr_str(node)
        self.assertIn("5 items", result)

    def test_fstring(self):
        node = sv.FStringNode([sv.StringNode("hi")])
        self.assertEqual(_expr_str(node), 'f"..."')

    def test_index(self):
        node = sv.IndexNode(sv.IdentifierNode("arr"), sv.NumberNode(0))
        self.assertEqual(_expr_str(node), "arr[0]")

    def test_len(self):
        node = sv.LenNode(sv.IdentifierNode("xs"))
        self.assertEqual(_expr_str(node), "len(xs)")

    def test_pipe(self):
        node = sv.PipeNode(sv.IdentifierNode("x"), sv.IdentifierNode("f"))
        self.assertEqual(_expr_str(node), "x |> f")

    def test_map_node(self):
        node = sv.MapNode([])
        self.assertEqual(_expr_str(node), "{...}")

    def test_logical(self):
        node = sv.LogicalNode(sv.BoolNode(True), "and", sv.BoolNode(False))
        self.assertEqual(_expr_str(node), "true and false")


# ── CFG Building ───────────────────────────────────────────────────

class TestBuildCFG(unittest.TestCase):

    def test_empty(self):
        cfg = build_cfg([], name="empty")
        self.assertEqual(cfg.name, "empty")
        self.assertEqual(cfg.node_count(), 1)  # just (empty)

    def test_single_assignment(self):
        ast = _parse("x = 5")
        cfg = build_cfg(ast)
        self.assertGreaterEqual(cfg.node_count(), 3)  # START, assign, END
        self.assertGreater(cfg.edge_count(), 0)

    def test_sequential_statements(self):
        ast = _parse("x = 1\ny = 2\nprint x")
        cfg = build_cfg(ast)
        self.assertGreaterEqual(cfg.node_count(), 5)  # START + 3 stmts + END

    def test_if_branch(self):
        ast = _parse("if x > 0\n    print x")
        cfg = build_cfg(ast)
        shapes = [n.shape for n in cfg.nodes.values()]
        self.assertIn("diamond", shapes)

    def test_if_else(self):
        ast = _parse("if x > 0\n    print x\nelse\n    print 0")
        cfg = build_cfg(ast)
        stats = cfg_stats(cfg)
        self.assertEqual(stats["decisions"], 1)

    def test_if_elseif_else(self):
        src = "if x > 10\n    print 10\nelse if x > 5\n    print 5\nelse\n    print 0"
        ast = _parse(src)
        cfg = build_cfg(ast)
        stats = cfg_stats(cfg)
        self.assertEqual(stats["decisions"], 2)  # main if + else if

    def test_while_loop(self):
        ast = _parse("while x > 0\n    x = x - 1")
        cfg = build_cfg(ast)
        stats = cfg_stats(cfg)
        self.assertEqual(stats["loops"], 1)

    def test_for_loop(self):
        ast = _parse("for i 0 10\n    print i")
        cfg = build_cfg(ast)
        stats = cfg_stats(cfg)
        self.assertEqual(stats["loops"], 1)

    def test_foreach_loop(self):
        ast = _parse('for item in [1, 2, 3]\n    print item')
        cfg = build_cfg(ast)
        stats = cfg_stats(cfg)
        self.assertEqual(stats["loops"], 1)

    def test_try_catch(self):
        src = "try\n    x = 1\ncatch e\n    print e"
        ast = _parse(src)
        cfg = build_cfg(ast)
        shapes = [n.shape for n in cfg.nodes.values()]
        self.assertIn("hexagon", shapes)

    def test_function_def(self):
        src = "function double x\n    return x * 2"
        ast = _parse(src)
        cfg = build_cfg(ast)
        # Function definition should create a node
        labels = [n.label for n in cfg.nodes.values()]
        found = any("double" in l for l in labels)
        self.assertTrue(found)

    def test_throw_node(self):
        src = 'throw "error"'
        ast = _parse(src)
        cfg = build_cfg(ast)
        throw_nodes = [n for n in cfg.nodes.values() if "throw" in n.label]
        self.assertEqual(len(throw_nodes), 1)
        self.assertEqual(throw_nodes[0].node_type, "error")

    def test_import_node(self):
        src = 'import "utils"'
        ast = _parse(src)
        cfg = build_cfg(ast)
        import_nodes = [n for n in cfg.nodes.values() if "import" in n.label]
        self.assertEqual(len(import_nodes), 1)

    def test_print_node(self):
        ast = _parse('print "hello"')
        cfg = build_cfg(ast)
        print_nodes = [n for n in cfg.nodes.values() if "print" in n.label]
        self.assertEqual(len(print_nodes), 1)

    def test_nested_if_while(self):
        src = "while x > 0\n    if x > 5\n        print x\n    x = x - 1"
        ast = _parse(src)
        cfg = build_cfg(ast)
        stats = cfg_stats(cfg)
        self.assertEqual(stats["loops"], 1)
        self.assertEqual(stats["decisions"], 1)

    def test_match_case(self):
        src = "match x\n    case 1\n        print 1\n    case 2\n        print 2\n    case _\n        print 0"
        ast = _parse(src)
        cfg = build_cfg(ast)
        stats = cfg_stats(cfg)
        self.assertGreaterEqual(stats["decisions"], 1)

    def test_enum_node(self):
        src = "enum Color\n    RED\n    GREEN\n    BLUE"
        ast = _parse(src)
        cfg = build_cfg(ast)
        enum_nodes = [n for n in cfg.nodes.values() if "enum" in n.label]
        self.assertEqual(len(enum_nodes), 1)
        self.assertIn("Color", enum_nodes[0].label)

    def test_yield_node(self):
        src = "function gen x\n    yield x"
        ast = _parse(src)
        fn_node = [n for n in ast if isinstance(n, sv.FunctionNode)][0]
        cfg = build_cfg(fn_node.body, "gen")
        yield_nodes = [n for n in cfg.nodes.values() if "yield" in n.label]
        self.assertEqual(len(yield_nodes), 1)

    def test_assert_node(self):
        src = "assert x > 0"
        ast = _parse(src)
        cfg = build_cfg(ast)
        assert_nodes = [n for n in cfg.nodes.values() if "assert" in n.label]
        self.assertEqual(len(assert_nodes), 1)

    def test_append_node(self):
        src = "xs = []\nappend xs 1"
        ast = _parse(src)
        cfg = build_cfg(ast)
        append_nodes = [n for n in cfg.nodes.values() if "append" in n.label]
        self.assertEqual(len(append_nodes), 1)

    def test_pop_node(self):
        src = "xs = [1, 2]\npop xs"
        ast = _parse(src)
        cfg = build_cfg(ast)
        pop_nodes = [n for n in cfg.nodes.values() if "pop" in n.label]
        self.assertEqual(len(pop_nodes), 1)

    def test_indexed_assignment(self):
        src = "xs = [0, 1]\nxs[0] = 5"
        ast = _parse(src)
        cfg = build_cfg(ast)
        # Should have at least one node with indexed assignment
        labels = [n.label for n in cfg.nodes.values()]
        found = any("[" in l and "=" in l for l in labels)
        self.assertTrue(found)


# ── build_all_cfgs ─────────────────────────────────────────────────

class TestBuildAllCFGs(unittest.TestCase):

    def test_toplevel_only(self):
        ast = _parse("x = 1\nprint x")
        cfgs = build_all_cfgs(ast)
        self.assertEqual(len(cfgs), 1)
        self.assertEqual(cfgs[0].name, "main")

    def test_functions(self):
        src = "function add a b\n    return a + b\nfunction sub a b\n    return a - b\nprint 1"
        ast = _parse(src)
        cfgs = build_all_cfgs(ast)
        self.assertEqual(len(cfgs), 3)  # main + add + sub
        names = [c.name for c in cfgs]
        self.assertIn("main", names)
        self.assertIn("add", names)
        self.assertIn("sub", names)

    def test_no_toplevel(self):
        src = "function foo x\n    return x"
        ast = _parse(src)
        cfgs = build_all_cfgs(ast)
        self.assertEqual(len(cfgs), 1)
        self.assertEqual(cfgs[0].name, "foo")


# ── Mermaid Renderer ───────────────────────────────────────────────

class TestRenderMermaid(unittest.TestCase):

    def test_basic_output(self):
        ast = _parse("x = 5")
        cfg = build_cfg(ast)
        result = render_mermaid(cfg)
        self.assertIn("```mermaid", result)
        self.assertIn("flowchart TD", result)
        self.assertIn("```", result)

    def test_contains_nodes(self):
        ast = _parse("x = 5")
        cfg = build_cfg(ast)
        result = render_mermaid(cfg)
        self.assertIn("START", result)
        self.assertIn("END", result)
        self.assertIn("x = 5", result)

    def test_diamond_for_if(self):
        ast = _parse("if x > 0\n    print x")
        cfg = build_cfg(ast)
        result = render_mermaid(cfg)
        self.assertIn("{", result)

    def test_edge_labels(self):
        ast = _parse("if x > 0\n    print x\nelse\n    print 0")
        cfg = build_cfg(ast)
        result = render_mermaid(cfg)
        self.assertIn("yes", result)

    def test_html_escaping(self):
        ast = _parse("if x > 0\n    print x")
        cfg = build_cfg(ast)
        result = render_mermaid(cfg)
        self.assertIn("&gt;", result)


# ── DOT Renderer ───────────────────────────────────────────────────

class TestRenderDot(unittest.TestCase):

    def test_basic_output(self):
        ast = _parse("x = 5")
        cfg = build_cfg(ast)
        result = render_dot(cfg)
        self.assertIn("digraph", result)
        self.assertIn("rankdir=TB", result)

    def test_node_shapes(self):
        ast = _parse("if x > 0\n    print x")
        cfg = build_cfg(ast)
        result = render_dot(cfg)
        self.assertIn("diamond", result)
        self.assertIn("ellipse", result)  # START/END

    def test_color_coding(self):
        ast = _parse("while x > 0\n    x = x - 1")
        cfg = build_cfg(ast)
        result = render_dot(cfg)
        self.assertIn("fillcolor", result)

    def test_edge_labels(self):
        ast = _parse("if x > 0\n    print x\nelse\n    print 0")
        cfg = build_cfg(ast)
        result = render_dot(cfg)
        self.assertIn("yes", result)


# ── Text Renderer ──────────────────────────────────────────────────

class TestRenderText(unittest.TestCase):

    def test_empty_cfg(self):
        cfg = CFG("empty")
        result = render_text(cfg)
        self.assertIn("empty", result)

    def test_basic_output(self):
        ast = _parse("x = 5")
        cfg = build_cfg(ast)
        result = render_text(cfg)
        self.assertIn("main", result)
        self.assertIn("START", result)
        self.assertIn("END", result)

    def test_decision_formatting(self):
        ast = _parse("if x > 0\n    print x")
        cfg = build_cfg(ast)
        result = render_text(cfg)
        self.assertIn("/", result)

    def test_arrows(self):
        ast = _parse("x = 5")
        cfg = build_cfg(ast)
        result = render_text(cfg)
        self.assertIn("-->", result)


# ── Statistics ─────────────────────────────────────────────────────

class TestCFGStats(unittest.TestCase):

    def test_simple_stats(self):
        ast = _parse("x = 5")
        cfg = build_cfg(ast)
        s = cfg_stats(cfg)
        self.assertEqual(s["name"], "main")
        self.assertGreater(s["nodes"], 0)
        self.assertGreater(s["edges"], 0)
        self.assertGreaterEqual(s["cyclomatic_complexity"], 1)

    def test_branching_increases_complexity(self):
        simple = _parse("x = 5")
        cfg_simple = build_cfg(simple)
        s1 = cfg_stats(cfg_simple)

        branching = _parse("if x > 0\n    print 1\nelse\n    print 0")
        cfg_branch = build_cfg(branching)
        s2 = cfg_stats(cfg_branch)

        self.assertGreater(s2["cyclomatic_complexity"], s1["cyclomatic_complexity"])

    def test_loop_counted(self):
        ast = _parse("while x > 0\n    x = x - 1")
        cfg = build_cfg(ast)
        s = cfg_stats(cfg)
        self.assertEqual(s["loops"], 1)

    def test_decision_counted(self):
        ast = _parse("if x > 0\n    print x\nelse if x > 5\n    print 0")
        cfg = build_cfg(ast)
        s = cfg_stats(cfg)
        self.assertEqual(s["decisions"], 2)


class TestSummaryText(unittest.TestCase):

    def test_basic_summary(self):
        ast = _parse("function foo x\n    return x\nprint 1")
        cfgs = build_all_cfgs(ast)
        result = summary_text(cfgs)
        self.assertIn("Control Flow Summary", result)
        self.assertIn("foo", result)
        self.assertIn("main", result)

    def test_columns(self):
        ast = _parse("x = 1")
        cfgs = build_all_cfgs(ast)
        result = summary_text(cfgs)
        self.assertIn("Nodes", result)
        self.assertIn("Edges", result)
        self.assertIn("CC", result)


# ── CLI ────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.tmpdir, "test.srv")
        with open(self.test_file, "w") as f:
            f.write("x = 5\nif x > 0\n    print x\nelse\n    print 0\n")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_mermaid_output(self):
        out_path = os.path.join(self.tmpdir, "out.md")
        main([self.test_file, "-o", out_path])
        with open(out_path) as f:
            content = f.read()
        self.assertIn("mermaid", content)

    def test_dot_output(self):
        out_path = os.path.join(self.tmpdir, "out.dot")
        main([self.test_file, "--format", "dot", "-o", out_path])
        with open(out_path) as f:
            content = f.read()
        self.assertIn("digraph", content)

    def test_text_output(self):
        out_path = os.path.join(self.tmpdir, "out.txt")
        main([self.test_file, "--format", "text", "-o", out_path])
        with open(out_path) as f:
            content = f.read()
        self.assertIn("START", content)

    def test_all_functions(self):
        fn_file = os.path.join(self.tmpdir, "fns.srv")
        with open(fn_file, "w") as f:
            f.write("function add a b\n    return a + b\nfunction mul a b\n    return a * b\n")
        out_path = os.path.join(self.tmpdir, "out.md")
        main([fn_file, "--all-functions", "-o", out_path])
        with open(out_path) as f:
            content = f.read()
        self.assertIn("add", content)
        self.assertIn("mul", content)

    def test_specific_function(self):
        fn_file = os.path.join(self.tmpdir, "fns.srv")
        with open(fn_file, "w") as f:
            f.write("function add a b\n    return a + b\nfunction mul a b\n    return a * b\n")
        out_path = os.path.join(self.tmpdir, "out.md")
        main([fn_file, "--function", "mul", "-o", out_path])
        with open(out_path) as f:
            content = f.read()
        self.assertIn("mul", content)

    def test_stats_flag(self):
        out_path = os.path.join(self.tmpdir, "out.md")
        main([self.test_file, "--stats", "-o", out_path])
        with open(out_path) as f:
            content = f.read()
        self.assertIn("Control Flow Summary", content)

    def test_missing_file(self):
        out_path = os.path.join(self.tmpdir, "out.md")
        main(["nonexistent.srv", "-o", out_path])
        # Should not crash


# ── Complex Programs ───────────────────────────────────────────────

class TestComplexPrograms(unittest.TestCase):

    def test_fibonacci(self):
        src = """function fib n
    if n < 2
        return n
    return fib(n - 1) + fib(n - 2)

print fib(10)"""
        ast = _parse(src)
        cfgs = build_all_cfgs(ast)
        self.assertEqual(len(cfgs), 2)
        fib_cfg = [c for c in cfgs if c.name == "fib"][0]
        s = cfg_stats(fib_cfg)
        self.assertEqual(s["decisions"], 1)

    def test_nested_loops(self):
        src = """for i 0 5
    for j 0 5
        print i
"""
        ast = _parse(src)
        cfg = build_cfg(ast)
        s = cfg_stats(cfg)
        self.assertEqual(s["loops"], 2)

    def test_complex_control_flow(self):
        src = """function process items
    result = []
    for item in items
        try
            if item > 10
                append result item
            else
                throw "too small"
        catch e
            print e
    return result"""
        ast = _parse(src)
        fn = [n for n in ast if isinstance(n, sv.FunctionNode)][0]
        cfg = build_cfg(fn.body, "process")
        s = cfg_stats(cfg)
        self.assertGreaterEqual(s["loops"], 1)
        self.assertGreaterEqual(s["decisions"], 1)
        self.assertGreaterEqual(s["error_handlers"], 1)

    def test_all_three_formats_consistent(self):
        src = "if x > 0\n    print x\nelse\n    print 0"
        ast = _parse(src)
        cfg = build_cfg(ast)
        mermaid = render_mermaid(cfg)
        dot = render_dot(cfg)
        text = render_text(cfg)
        for fmt in [mermaid, text]:
            self.assertTrue("x" in fmt)
        self.assertTrue("x" in dot)

    def test_while_with_break(self):
        src = "while true\n    if x > 10\n        break\n    x = x + 1"
        ast = _parse(src)
        cfg = build_cfg(ast)
        labels = [n.label for n in cfg.nodes.values()]
        self.assertTrue(any("break" in l for l in labels))

    def test_for_with_continue(self):
        src = "for i 0 10\n    if i == 5\n        continue\n    print i"
        ast = _parse(src)
        cfg = build_cfg(ast)
        labels = [n.label for n in cfg.nodes.values()]
        self.assertTrue(any("continue" in l for l in labels))


if __name__ == "__main__":
    unittest.main()
