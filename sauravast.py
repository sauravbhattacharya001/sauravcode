#!/usr/bin/env python3
"""
sauravast.py - AST visualizer for sauravcode programs.

Parses a .srv file and displays the abstract syntax tree as either a
pretty-printed tree diagram or machine-readable JSON.

Usage:
    python sauravast.py program.srv              # Pretty tree view
    python sauravast.py program.srv --json       # JSON output
    python sauravast.py program.srv --depth 3    # Limit tree depth
    python sauravast.py program.srv --stats      # Show AST statistics
    python sauravast.py program.srv --dot        # Graphviz DOT output
"""

import sys
import os
import json as _json
import argparse
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from saurav import tokenize, Parser, ASTNode


# ── Node → dict conversion ──────────────────────────────────────────

def _node_children(node):
    """Return a list of (label, child_or_value) pairs for an AST node."""
    pairs = []
    for attr in sorted(vars(node)):
        if attr.startswith('_') or attr == 'line_num':
            continue
        val = getattr(node, attr)
        pairs.append((attr, val))
    return pairs


def node_to_dict(node, depth=None, _cur=0):
    """Recursively convert an ASTNode to a JSON-serialisable dict."""
    if depth is not None and _cur >= depth:
        return {"_type": type(node).__name__, "_truncated": True}

    if isinstance(node, ASTNode):
        d = {"_type": type(node).__name__}
        for label, val in _node_children(node):
            d[label] = node_to_dict(val, depth, _cur + 1)
        return d
    elif isinstance(node, list):
        return [node_to_dict(item, depth, _cur) for item in node]
    elif isinstance(node, tuple):
        return [node_to_dict(item, depth, _cur) for item in node]
    else:
        return node


# ── Pretty tree printer ─────────────────────────────────────────────

def _box_chars():
    """Return tree-drawing characters, falling back to ASCII if the
    console encoding cannot handle Unicode box-drawing glyphs."""
    try:
        "│├└".encode(sys.stdout.encoding or "utf-8")
        return ("│   ", "├── ", "└── ", "    ")
    except (UnicodeEncodeError, LookupError):
        return ("|   ", "|-- ", "`-- ", "    ")

_PIPE, _TEE, _BEND, _BLANK = _box_chars()


def _format_leaf(val):
    """Format a non-node value as a compact string."""
    if isinstance(val, str):
        return repr(val)
    return str(val)


def _tree_lines(node, depth=None, _cur=0):
    """Yield indented tree lines for an AST node."""
    if depth is not None and _cur >= depth:
        yield f"{type(node).__name__} ..."
        return

    if isinstance(node, ASTNode):
        children = _node_children(node)
        yield type(node).__name__
        for i, (label, val) in enumerate(children):
            is_last = i == len(children) - 1
            connector = _BEND if is_last else _TEE
            continuation = _BLANK if is_last else _PIPE

            if isinstance(val, ASTNode):
                sub = list(_tree_lines(val, depth, _cur + 1))
                yield f"{connector}{label}: {sub[0]}"
                for line in sub[1:]:
                    yield f"{continuation}{line}"
            elif isinstance(val, list) and val and any(isinstance(v, ASTNode) for v in val):
                yield f"{connector}{label}: [{len(val)} items]"
                for j, item in enumerate(val):
                    item_last = j == len(val) - 1
                    ic = _BEND if item_last else _TEE
                    ic2 = _BLANK if item_last else _PIPE
                    if isinstance(item, ASTNode):
                        sub = list(_tree_lines(item, depth, _cur + 1))
                        yield f"{continuation}{ic}[{j}]: {sub[0]}"
                        for line in sub[1:]:
                            yield f"{continuation}{ic2}{line}"
                    else:
                        yield f"{continuation}{ic}[{j}]: {_format_leaf(item)}"
            else:
                yield f"{connector}{label}: {_format_leaf(val)}"
    else:
        yield _format_leaf(node)


def print_tree(nodes, depth=None):
    """Print a list of top-level AST nodes as a tree."""
    print("Program")
    for i, node in enumerate(nodes):
        is_last = i == len(nodes) - 1
        connector = _BEND if is_last else _TEE
        continuation = _BLANK if is_last else _PIPE
        lines = list(_tree_lines(node, depth))
        print(f"{connector}{lines[0]}")
        for line in lines[1:]:
            print(f"{continuation}{line}")


# ── Statistics ───────────────────────────────────────────────────────

def collect_stats(nodes):
    """Walk the AST and return node type counts and max depth."""
    counts = Counter()
    max_depth = [0]

    def walk(node, d):
        if d > max_depth[0]:
            max_depth[0] = d
        if isinstance(node, ASTNode):
            counts[type(node).__name__] += 1
            for _, val in _node_children(node):
                walk(val, d + 1)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item, d)

    for n in nodes:
        walk(n, 0)

    return {
        "total_nodes": sum(counts.values()),
        "max_depth": max_depth[0],
        "node_types": dict(counts.most_common()),
    }


# ── Graphviz DOT output ─────────────────────────────────────────────

def _dot_lines(nodes):
    """Yield lines for a Graphviz DOT digraph."""
    yield "digraph AST {"
    yield '  node [shape=box, fontname="Courier", fontsize=10];'
    yield '  edge [fontname="Courier", fontsize=9];'

    counter = [0]

    def _id():
        counter[0] += 1
        return f"n{counter[0]}"

    def walk(node, parent_id=None, edge_label=None):
        if isinstance(node, ASTNode):
            nid = _id()
            name = type(node).__name__.replace("Node", "")
            # Add leaf values inline
            leaf_parts = []
            children = _node_children(node)
            child_items = []
            for label, val in children:
                if isinstance(val, ASTNode) or (isinstance(val, list) and any(isinstance(v, ASTNode) for v in val)):
                    child_items.append((label, val))
                else:
                    disp = repr(val) if isinstance(val, str) else str(val)
                    if len(disp) > 30:
                        disp = disp[:27] + "..."
                    leaf_parts.append(f"{label}={disp}")

            lbl = name
            if leaf_parts:
                lbl += "\\n" + "\\n".join(leaf_parts)
            yield f'  {nid} [label="{lbl}"];'
            if parent_id:
                elbl = f' [label="{edge_label}"]' if edge_label else ""
                yield f"  {parent_id} -> {nid}{elbl};"
            for clabel, cval in child_items:
                yield from walk(cval, nid, clabel)
        elif isinstance(node, (list, tuple)):
            for i, item in enumerate(node):
                yield from walk(item, parent_id, f"{edge_label}[{i}]" if edge_label else f"[{i}]")

    root = _id()
    yield f'  {root} [label="Program", shape=ellipse];'
    for i, n in enumerate(nodes):
        yield from walk(n, root, f"stmt[{i}]" if len(nodes) > 1 else None)
    yield "}"


def print_dot(nodes):
    """Print Graphviz DOT representation of the AST."""
    for line in _dot_lines(nodes):
        print(line)


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="sauravast",
        description="Visualize the AST of a sauravcode (.srv) program",
    )
    parser.add_argument("file", help="Path to a .srv source file")
    parser.add_argument("--json", action="store_true", help="Output AST as JSON")
    parser.add_argument("--dot", action="store_true", help="Output Graphviz DOT digraph")
    parser.add_argument("--stats", action="store_true", help="Show AST statistics")
    parser.add_argument("--depth", type=int, default=None, help="Limit tree display depth")
    args = parser.parse_args()

    filename = args.file
    if not filename.endswith(".srv"):
        print("Error: File must have a .srv extension.", file=sys.stderr)
        sys.exit(1)
    if not os.path.isfile(filename):
        print(f"Error: File '{filename}' not found.", file=sys.stderr)
        sys.exit(1)

    with open(filename, "r") as f:
        code = f.read()

    tokens = list(tokenize(code))
    p = Parser(tokens)
    ast_nodes = p.parse()

    if args.json:
        data = [node_to_dict(n, args.depth) for n in ast_nodes]
        print(_json.dumps(data, indent=2, default=str))
    elif args.dot:
        print_dot(ast_nodes)
    elif args.stats:
        stats = collect_stats(ast_nodes)
        print(f"Total AST nodes : {stats['total_nodes']}")
        print(f"Max tree depth  : {stats['max_depth']}")
        print(f"\nNode type breakdown:")
        for name, count in stats["node_types"].items():
            try:
                "█".encode(sys.stdout.encoding or "utf-8")
                ch = "█"
            except (UnicodeEncodeError, LookupError):
                ch = "#"
            bar = ch * min(count, 40)
            print(f"  {name:<30} {count:>4}  {bar}")
    else:
        print_tree(ast_nodes, args.depth)


if __name__ == "__main__":
    main()
