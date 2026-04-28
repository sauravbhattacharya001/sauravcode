"""sauravflow -- Control flow diagram generator for sauravcode (.srv) programs.

Parse .srv source into an AST, build a control flow graph (CFG), and
render it as a Mermaid flowchart, Graphviz DOT, or plain-text diagram.
Useful for understanding program structure, documenting algorithms, and
teaching sauravcode control flow.

Supports:
  - Functions (one diagram per function + one for top-level)
  - If / elif / else branching
  - While loops, for loops, for-each loops
  - Try / catch blocks
  - Match / case pattern matching
  - Return, break, continue, throw
  - Import statements
  - Nested control flow (arbitrary depth)

Output formats:
  - mermaid  (default) — Markdown-embeddable Mermaid flowchart
  - dot      — Graphviz DOT language
  - text     — ASCII box diagram

Usage (CLI)::

    python sauravflow.py program.srv
    python sauravflow.py program.srv --format dot
    python sauravflow.py program.srv --format text
    python sauravflow.py program.srv --function factorial
    python sauravflow.py program.srv -o flowchart.md
    python sauravflow.py program.srv --all-functions
    python sauravflow.py *.srv --format dot -o diagrams/

Usage (Python API)::

    from sauravflow import build_cfg, render_mermaid, render_dot, render_text
    from saurav import tokenize, Parser

    tokens = tokenize("if x > 0\\n    print x")
    ast = Parser(tokens).parse()
    cfg = build_cfg(ast, name="example")
    print(render_mermaid(cfg))
"""

import os
import sys

# ---------------------------------------------------------------------------
# CFG data structures
# ---------------------------------------------------------------------------

class CFGNode:
    """A node in the control flow graph."""

    __slots__ = ("id", "label", "shape", "successors", "node_type")

    SHAPES = ("box", "diamond", "stadium", "hexagon", "circle", "trapezoid")

    def __init__(self, node_id, label, shape="box", node_type="statement"):
        self.id = node_id
        self.label = label
        self.shape = shape  # box | diamond | stadium | hexagon | circle
        self.node_type = node_type  # statement | decision | terminal | loop | error
        self.successors = []  # list of (target_id, edge_label_or_None)

    def add_edge(self, target_id, label=None):
        self.successors.append((target_id, label))

    def __repr__(self):
        return f"CFGNode({self.id!r}, {self.label!r})"


class CFG:
    """Control flow graph — ordered collection of CFGNodes."""

    def __init__(self, name="main"):
        self.name = name
        self.nodes = {}       # id -> CFGNode
        self._counter = 0

    def new_node(self, label, shape="box", node_type="statement"):
        nid = f"n{self._counter}"
        self._counter += 1
        node = CFGNode(nid, label, shape, node_type)
        self.nodes[nid] = node
        return node

    def node_count(self):
        return len(self.nodes)

    def edge_count(self):
        return sum(len(n.successors) for n in self.nodes.values())


# ---------------------------------------------------------------------------
# Expression pretty-printer (compact)
# ---------------------------------------------------------------------------

def _expr_str(node):
    """Produce a short human-readable string for an expression AST node."""
    if node is None:
        return "?"

    # Import saurav classes lazily to avoid circular import issues
    import saurav as sv

    name = type(node).__name__

    if isinstance(node, sv.NumberNode):
        return str(node.value)
    if isinstance(node, sv.StringNode):
        return repr(node.value)
    if isinstance(node, sv.BoolNode):
        return str(node.value).lower()
    if isinstance(node, sv.IdentifierNode):
        return node.name
    if isinstance(node, sv.BinaryOpNode):
        return f"{_expr_str(node.left)} {node.operator} {_expr_str(node.right)}"
    if isinstance(node, sv.CompareNode):
        return f"{_expr_str(node.left)} {node.operator} {_expr_str(node.right)}"
    if isinstance(node, sv.LogicalNode):
        return f"{_expr_str(node.left)} {node.operator} {_expr_str(node.right)}"
    if isinstance(node, sv.UnaryOpNode):
        return f"{node.operator} {_expr_str(node.operand)}"
    if isinstance(node, sv.FunctionCallNode):
        args = ", ".join(_expr_str(a) for a in node.arguments)
        return f"{node.name}({args})"
    if isinstance(node, sv.IndexNode):
        return f"{_expr_str(node.obj)}[{_expr_str(node.index)}]"
    if isinstance(node, sv.LenNode):
        return f"len({_expr_str(node.expression)})"
    if isinstance(node, sv.LambdaNode):
        params = " ".join(node.params)
        return f"lambda {params} -> ..."
    if isinstance(node, sv.PipeNode):
        return f"{_expr_str(node.value)} |> {_expr_str(node.function)}"
    if isinstance(node, sv.TernaryNode):
        return f"{_expr_str(node.true_expr)} if {_expr_str(node.condition)} else {_expr_str(node.false_expr)}"
    if isinstance(node, sv.FStringNode):
        return 'f"..."'
    if isinstance(node, sv.ListNode):
        if len(node.elements) <= 3:
            return "[" + ", ".join(_expr_str(e) for e in node.elements) + "]"
        return f"[...{len(node.elements)} items]"
    if isinstance(node, sv.MapNode):
        return "{...}"
    if isinstance(node, sv.SliceNode):
        return f"{_expr_str(node.obj)}[{_expr_str(node.start)}:{_expr_str(node.end)}]"
    if isinstance(node, sv.EnumAccessNode):
        return f"{node.enum_name}.{node.variant}"
    if isinstance(node, sv.ListComprehensionNode):
        return f"[... for {node.var} in ...]"

    # Fallback
    return name.replace("Node", "")


def _truncate(s, maxlen=50):
    """Truncate a label to maxlen characters."""
    if len(s) <= maxlen:
        return s
    return s[:maxlen - 3] + "..."


# ---------------------------------------------------------------------------
# CFG builder
# ---------------------------------------------------------------------------

def build_cfg(ast_nodes, name="main"):
    """Build a CFG from a list of AST nodes.

    Parameters
    ----------
    ast_nodes : list
        List of AST statement nodes (e.g. from ``Parser.parse()``).
    name : str
        Name of this flow (function name or ``"main"``).

    Returns
    -------
    CFG
    """
    cfg = CFG(name)
    _Builder(cfg).build(ast_nodes)
    return cfg


def build_all_cfgs(ast_nodes):
    """Build a CFG for top-level code and each function definition.

    Returns a list of CFG objects: the first is top-level code (name="main"),
    followed by one CFG per FunctionNode found at the top level.
    """
    import saurav as sv

    top_level = []
    functions = []
    for node in ast_nodes:
        if isinstance(node, sv.FunctionNode):
            functions.append(node)
        else:
            top_level.append(node)

    cfgs = []
    if top_level:
        cfgs.append(build_cfg(top_level, name="main"))
    for fn in functions:
        cfgs.append(build_cfg(fn.body, name=fn.name))
    return cfgs


class _Builder:
    """Walks the AST and populates a CFG."""

    def __init__(self, cfg):
        self.cfg = cfg

    # -- helpers --

    def _node(self, label, shape="box", node_type="statement"):
        return self.cfg.new_node(_truncate(label), shape, node_type)

    def _edge(self, src, dst, label=None):
        if src is not None and dst is not None:
            src.add_edge(dst.id, label)

    # -- main entry --

    def build(self, stmts):
        if not stmts:
            n = self._node("(empty)", "stadium", "terminal")
            return

        start = self._node("START", "stadium", "terminal")
        end = self._node("END", "stadium", "terminal")
        tails = self._process_block(stmts, [start])
        for t in tails:
            self._edge(t, end)

    # -- block processor --

    def _process_block(self, stmts, predecessors):
        """Process a list of statements. Returns list of tail nodes."""
        import saurav as sv

        tails = list(predecessors)
        for stmt in stmts:
            if not tails:
                break  # unreachable code after return/throw/break/continue
            tails = self._process_stmt(stmt, tails)
        return tails

    def _link_preds(self, node_id, preds):
        """Connect all predecessor nodes to *node_id*."""
        for p in preds:
            self._edge(p, node_id)

    def _terminal_node(self, label, shape, style, preds):
        """Create a terminal node (no successors) linked from *preds*."""
        n = self._node(label, shape, style)
        self._link_preds(n, preds)
        return []

    def _simple_stmt_node(self, label, preds, shape="box", style="statement"):
        """Create a simple statement node linked from *preds*, returning it as the new tail."""
        n = self._node(label, shape, style)
        self._link_preds(n, preds)
        return [n]

    def _process_stmt(self, stmt, preds):
        """Process a single statement. Returns list of new tail nodes."""
        import saurav as sv

        # -- Control flow (delegated to dedicated processors) --
        _CONTROL_FLOW = {
            sv.IfNode:       self._process_if,
            sv.WhileNode:    self._process_while,
            sv.ForNode:      self._process_for,
            sv.ForEachNode:  self._process_foreach,
            sv.TryCatchNode: self._process_trycatch,
            sv.MatchNode:    self._process_match,
        }
        handler = _CONTROL_FLOW.get(type(stmt))
        if handler:
            return handler(stmt, preds)

        # -- Terminals (no successors) --
        if isinstance(stmt, sv.ReturnNode):
            return self._terminal_node(f"return {_expr_str(stmt.expression)}", "stadium", "terminal", preds)
        if isinstance(stmt, sv.ThrowNode):
            return self._terminal_node(f"throw {_expr_str(stmt.expression)}", "hexagon", "error", preds)
        if isinstance(stmt, sv.BreakNode):
            return self._terminal_node("break", "stadium", "terminal", preds)
        if isinstance(stmt, sv.ContinueNode):
            return self._terminal_node("continue", "stadium", "terminal", preds)

        # -- Function definitions --
        if isinstance(stmt, sv.FunctionNode):
            return self._simple_stmt_node(f"def {stmt.name}({', '.join(stmt.params)})", preds)

        # -- Simple statements (all produce a single "box" node) --
        if isinstance(stmt, sv.AssignmentNode):
            return self._simple_stmt_node(f"{stmt.name} = {_expr_str(stmt.expression)}", preds)
        if isinstance(stmt, sv.IndexedAssignmentNode):
            return self._simple_stmt_node(f"{stmt.name}[{_expr_str(stmt.index)}] = {_expr_str(stmt.value)}", preds)
        if isinstance(stmt, sv.PrintNode):
            return self._simple_stmt_node(f"print {_expr_str(stmt.expression)}", preds)
        if isinstance(stmt, sv.ImportNode):
            return self._simple_stmt_node(f'import "{stmt.module_path}"', preds)
        if isinstance(stmt, sv.AppendNode):
            return self._simple_stmt_node(f"append {_expr_str(stmt.list_name)} {_expr_str(stmt.value)}", preds)
        if isinstance(stmt, sv.PopNode):
            return self._simple_stmt_node(f"pop {_expr_str(stmt.list_name)}", preds)
        if isinstance(stmt, sv.YieldNode):
            return self._simple_stmt_node(f"yield {_expr_str(stmt.expression)}", preds, shape="hexagon")
        if isinstance(stmt, sv.AssertNode):
            return self._simple_stmt_node(f"assert {_expr_str(stmt.condition)}", preds, shape="hexagon")
        if isinstance(stmt, sv.EnumNode):
            variants = ", ".join(stmt.variants[:4])
            if len(stmt.variants) > 4:
                variants += ", ..."
            return self._simple_stmt_node(f"enum {stmt.name} ({variants})", preds)

        # -- Expression statement (function call etc.) --
        return self._simple_stmt_node(_expr_str(stmt), preds)

    # -- Control flow processors --

    def _process_if(self, node, preds):
        import saurav as sv
        cond_str = _expr_str(node.condition)
        cond = self._node(cond_str, "diamond", "decision")
        self._link_preds(cond, preds)

        # True branch
        tails_true = self._process_block(node.body, [cond])
        # Mark true edge
        if tails_true or node.body:
            cond.successors[-len(node.body) if node.body else -1] = (
                cond.successors[-1][0] if cond.successors else cond.id, "yes"
            )
            # Fix: properly label the edge to the first body node
            for i, (tid, lbl) in enumerate(cond.successors):
                if lbl is None:
                    cond.successors[i] = (tid, "yes")
                    break

        all_tails = list(tails_true)

        # Elif branches
        prev_cond = cond
        for elif_cond_ast, elif_body in node.elif_chains:
            elif_cond_str = _expr_str(elif_cond_ast)
            elif_cond = self._node(elif_cond_str, "diamond", "decision")
            self._edge(prev_cond, elif_cond, "no")
            elif_tails = self._process_block(elif_body, [elif_cond])
            # Label yes edge
            for i, (tid, lbl) in enumerate(elif_cond.successors):
                if lbl is None:
                    elif_cond.successors[i] = (tid, "yes")
                    break
            all_tails.extend(elif_tails)
            prev_cond = elif_cond

        # Else branch
        if node.else_body:
            else_tails = self._process_block(node.else_body, [prev_cond])
            # Label else edge
            for i, (tid, lbl) in enumerate(prev_cond.successors):
                if lbl is None:
                    prev_cond.successors[i] = (tid, "no")
                    break
            all_tails.extend(else_tails)
        else:
            all_tails.append(prev_cond)  # no else → condition falls through

        return all_tails

    def _process_while(self, node, preds):
        cond_str = _expr_str(node.condition)
        cond = self._node(f"while {cond_str}", "diamond", "loop")
        self._link_preds(cond, preds)

        body_tails = self._process_block(node.body, [cond])
        # Label the edge to body as "yes"
        for i, (tid, lbl) in enumerate(cond.successors):
            if lbl is None:
                cond.successors[i] = (tid, "yes")
                break

        # Loop back
        for t in body_tails:
            self._edge(t, cond, "loop")

        return [cond]  # exits when condition is false

    def _process_for(self, node, preds):
        start_str = _expr_str(node.start)
        end_str = _expr_str(node.end)
        header = self._node(f"for {node.var} = {start_str} to {end_str}", "diamond", "loop")
        self._link_preds(header, preds)

        body_tails = self._process_block(node.body, [header])
        for i, (tid, lbl) in enumerate(header.successors):
            if lbl is None:
                header.successors[i] = (tid, "yes")
                break

        for t in body_tails:
            self._edge(t, header, "next")

        return [header]

    def _process_foreach(self, node, preds):
        iter_str = _expr_str(node.iterable)
        header = self._node(f"for {node.var} in {iter_str}", "diamond", "loop")
        self._link_preds(header, preds)

        body_tails = self._process_block(node.body, [header])
        for i, (tid, lbl) in enumerate(header.successors):
            if lbl is None:
                header.successors[i] = (tid, "yes")
                break

        for t in body_tails:
            self._edge(t, header, "next")

        return [header]

    def _process_trycatch(self, node, preds):
        try_node = self._node("try", "hexagon", "error")
        self._link_preds(try_node, preds)

        try_tails = self._process_block(node.body, [try_node])

        catch_node = self._node(f"catch {node.error_var}", "hexagon", "error")
        self._edge(try_node, catch_node, "error")

        catch_tails = self._process_block(node.handler, [catch_node])

        all_tails = list(try_tails) + list(catch_tails)
        return all_tails

    def _process_match(self, node, preds):
        expr_str = _expr_str(node.expression)
        match_node = self._node(f"match {expr_str}", "diamond", "decision")
        self._link_preds(match_node, preds)

        all_tails = []
        for case in node.cases:
            if case.is_wildcard:
                case_label = "_"
            else:
                case_label = " | ".join(str(_expr_str(p)) for p in case.patterns)
            case_label = _truncate(case_label, 30)

            case_tails = self._process_block(case.body, [match_node])
            # Label the edge
            for i in range(len(match_node.successors) - 1, -1, -1):
                tid, lbl = match_node.successors[i]
                if lbl is None:
                    match_node.successors[i] = (tid, case_label)
                    break

            all_tails.extend(case_tails)

        return all_tails


# ---------------------------------------------------------------------------
# Mermaid renderer
# ---------------------------------------------------------------------------

def render_mermaid(cfg):
    """Render a CFG as a Mermaid flowchart string."""
    lines = [f"```mermaid", f"flowchart TD"]

    # Escape for mermaid
    def esc(s):
        return s.replace('"', "'").replace("<", "&lt;").replace(">", "&gt;")

    for nid, node in cfg.nodes.items():
        label = esc(node.label)
        if node.shape == "diamond":
            lines.append(f"    {nid}{{{{{label}}}}}")
        elif node.shape == "stadium":
            lines.append(f"    {nid}([{label}])")
        elif node.shape == "hexagon":
            lines.append(f"    {nid}{{{{{{{label}}}}}}}")
        elif node.shape == "circle":
            lines.append(f"    {nid}(({label}))")
        else:
            lines.append(f"    {nid}[{label}]")

    for nid, node in cfg.nodes.items():
        for target_id, edge_label in node.successors:
            if edge_label:
                lines.append(f"    {nid} -->|{esc(edge_label)}| {target_id}")
            else:
                lines.append(f"    {nid} --> {target_id}")

    lines.append("```")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# DOT renderer
# ---------------------------------------------------------------------------

def render_dot(cfg):
    """Render a CFG as a Graphviz DOT string."""
    lines = [f'digraph "{cfg.name}" {{']
    lines.append('    rankdir=TB;')
    lines.append('    node [fontname="Helvetica", fontsize=11];')
    lines.append('    edge [fontname="Helvetica", fontsize=9];')

    shape_map = {
        "box": "box",
        "diamond": "diamond",
        "stadium": "ellipse",
        "hexagon": "hexagon",
        "circle": "circle",
    }

    style_map = {
        "terminal": 'style=filled, fillcolor="#e8f5e9"',
        "decision": 'style=filled, fillcolor="#fff3e0"',
        "loop":     'style=filled, fillcolor="#e3f2fd"',
        "error":    'style=filled, fillcolor="#fce4ec"',
        "statement": "",
    }

    def esc(s):
        return s.replace('"', '\\"').replace("\n", "\\n")

    for nid, node in cfg.nodes.items():
        shape = shape_map.get(node.shape, "box")
        style = style_map.get(node.node_type, "")
        label = esc(node.label)
        attrs = f'label="{label}", shape={shape}'
        if style:
            attrs += f", {style}"
        lines.append(f'    {nid} [{attrs}];')

    for nid, node in cfg.nodes.items():
        for target_id, edge_label in node.successors:
            if edge_label:
                lines.append(f'    {nid} -> {target_id} [label="{esc(edge_label)}"];')
            else:
                lines.append(f'    {nid} -> {target_id};')

    lines.append("}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Text renderer (ASCII boxes)
# ---------------------------------------------------------------------------

def render_text(cfg):
    """Render a CFG as a plain-text box diagram."""
    if not cfg.nodes:
        return f"[{cfg.name}: empty]"

    lines = [f"=== {cfg.name} ===", ""]

    # Topological ordering (best-effort BFS from START)
    visited = set()
    order = []
    queue = []

    # Find start node (first node)
    first_id = next(iter(cfg.nodes))
    queue.append(first_id)
    visited.add(first_id)

    while queue:
        nid = queue.pop(0)
        order.append(nid)
        node = cfg.nodes[nid]
        for target_id, _ in node.successors:
            if target_id not in visited:
                visited.add(target_id)
                queue.append(target_id)

    # Add any unreachable nodes
    for nid in cfg.nodes:
        if nid not in visited:
            order.append(nid)

    for nid in order:
        node = cfg.nodes[nid]
        label = node.label

        if node.shape == "diamond":
            # Decision — diamond-ish
            lines.append(f"    /{label}\\")
            lines.append(f"    \\{'_' * len(label)}/")
        elif node.shape == "stadium":
            # Terminal — rounded
            lines.append(f"    ({label})")
        elif node.shape == "hexagon":
            # Error/special
            lines.append(f"    <{label}>")
        else:
            # Box
            border = "+" + "-" * (len(label) + 2) + "+"
            lines.append(f"    {border}")
            lines.append(f"    | {label} |")
            lines.append(f"    {border}")

        # Show edges
        for target_id, edge_label in node.successors:
            target = cfg.nodes.get(target_id)
            target_name = target.label if target else target_id
            arrow = f"  --> {target_name}"
            if edge_label:
                arrow = f"  --[{edge_label}]--> {target_name}"
            lines.append(f"      {arrow}")

        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------

def cfg_stats(cfg):
    """Return a dict of summary statistics for a CFG."""
    nodes = cfg.nodes
    n_decisions = sum(1 for n in nodes.values() if n.node_type == "decision")
    n_loops = sum(1 for n in nodes.values() if n.node_type == "loop")
    n_errors = sum(1 for n in nodes.values() if n.node_type == "error")
    n_terminals = sum(1 for n in nodes.values() if n.node_type == "terminal")
    n_statements = sum(1 for n in nodes.values() if n.node_type == "statement")

    # Cyclomatic complexity: M = E - N + 2P (P=1 for a single function)
    edges = cfg.edge_count()
    nodes_count = cfg.node_count()
    cyclomatic = edges - nodes_count + 2

    return {
        "name": cfg.name,
        "nodes": nodes_count,
        "edges": edges,
        "decisions": n_decisions,
        "loops": n_loops,
        "error_handlers": n_errors,
        "terminals": n_terminals,
        "statements": n_statements,
        "cyclomatic_complexity": max(cyclomatic, 1),
    }


def summary_text(cfgs):
    """Produce a summary table for a list of CFGs."""
    lines = ["Control Flow Summary", "=" * 70]
    lines.append(f"{'Function':<25} {'Nodes':>6} {'Edges':>6} {'CC':>4} {'Loops':>6} {'Branches':>9}")
    lines.append("-" * 70)
    for cfg in cfgs:
        s = cfg_stats(cfg)
        lines.append(
            f"{s['name']:<25} {s['nodes']:>6} {s['edges']:>6} "
            f"{s['cyclomatic_complexity']:>4} {s['loops']:>6} {s['decisions']:>9}"
        )
    lines.append("-" * 70)
    total_cc = sum(cfg_stats(c)["cyclomatic_complexity"] for c in cfgs)
    lines.append(f"{'Total':<25} {'':>6} {'':>6} {total_cc:>4}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv):
    """Simple argument parser."""
    args = {
        "files": [],
        "format": "mermaid",
        "function": None,
        "all_functions": False,
        "output": None,
        "stats": False,
    }
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--format", "-f"):
            i += 1
            if i < len(argv):
                args["format"] = argv[i]
        elif a in ("--function", "--fn"):
            i += 1
            if i < len(argv):
                args["function"] = argv[i]
        elif a == "--all-functions":
            args["all_functions"] = True
        elif a in ("--output", "-o"):
            i += 1
            if i < len(argv):
                args["output"] = argv[i]
        elif a == "--stats":
            args["stats"] = True
        elif a in ("--help", "-h"):
            _print_help()
            sys.exit(0)
        elif not a.startswith("-"):
            args["files"].append(a)
        else:
            print(f"Unknown option: {a}", file=sys.stderr)
            sys.exit(1)
        i += 1
    return args


def _print_help():
    print("""sauravflow -- Control flow diagram generator for sauravcode

Usage:
    python sauravflow.py FILE [FILE...] [OPTIONS]

Options:
    --format, -f FORMAT    Output format: mermaid (default), dot, text
    --function, --fn NAME  Show only the named function
    --all-functions        Show all functions (default: top-level only)
    --output, -o PATH      Write output to file/directory
    --stats                Print control flow statistics
    --help, -h             Show this help

Examples:
    python sauravflow.py program.srv
    python sauravflow.py program.srv --format dot -o flow.dot
    python sauravflow.py program.srv --all-functions --stats
    python sauravflow.py *.srv --format text""")


def main(argv=None):
    """CLI entry point."""
    if argv is None:
        argv = sys.argv[1:]

    args = _parse_args(argv)

    if not args["files"]:
        print("Error: no input files", file=sys.stderr)
        _print_help()
        sys.exit(1)

    fmt = args["format"]
    if fmt not in ("mermaid", "dot", "text"):
        print(f"Error: unknown format '{fmt}'. Use mermaid, dot, or text.", file=sys.stderr)
        sys.exit(1)

    renderer = {"mermaid": render_mermaid, "dot": render_dot, "text": render_text}[fmt]

    # Add parent dir to path for saurav import
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    import saurav as sv

    all_outputs = []
    all_cfgs = []

    for filepath in args["files"]:
        if not os.path.isfile(filepath):
            print(f"Warning: {filepath} not found, skipping", file=sys.stderr)
            continue

        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()

        try:
            tokens = sv.tokenize(source)
            ast_nodes = sv.Parser(tokens).parse()
        except Exception as e:
            print(f"Error parsing {filepath}: {e}", file=sys.stderr)
            continue

        cfgs = build_all_cfgs(ast_nodes)
        all_cfgs.extend(cfgs)

        # Filter by function name if requested
        if args["function"]:
            cfgs = [c for c in cfgs if c.name == args["function"]]
            if not cfgs:
                print(f"Warning: function '{args['function']}' not found in {filepath}", file=sys.stderr)
                continue
        elif not args["all_functions"]:
            # Default: show only the first CFG (top-level or first function)
            cfgs = cfgs[:1]

        for cfg in cfgs:
            all_outputs.append(f"# {filepath} :: {cfg.name}\n")
            all_outputs.append(renderer(cfg))
            all_outputs.append("")

    result = "\n".join(all_outputs)

    if args["stats"]:
        result += "\n" + summary_text(all_cfgs) + "\n"

    if args["output"]:
        out_path = args["output"]
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(result)
        print(f"Written to {out_path}")
    else:
        print(result)


if __name__ == "__main__":
    main()
