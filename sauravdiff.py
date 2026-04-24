#!/usr/bin/env python3
"""
sauravdiff.py - Semantic diff tool for sauravcode programs.

Compares two .srv files by their AST structure rather than raw text,
so formatting changes (whitespace, comments, blank lines) are ignored
and only meaningful code changes are reported.

Usage:
    python sauravdiff.py old.srv new.srv             # Colored diff
    python sauravdiff.py old.srv new.srv --json       # JSON output
    python sauravdiff.py old.srv new.srv --summary    # Counts only
    python sauravdiff.py old.srv new.srv --context 5  # More context
    python sauravdiff.py old.srv new.srv --no-color   # Plain text
"""

import sys
import os
import json as _json
import argparse
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from saurav import tokenize, Parser, ASTNode


# ── AST fingerprinting ──────────────────────────────────────────────

def _node_type(node):
    """Return the type name of an AST node."""
    return type(node).__name__


def _node_signature(node):
    """
    Create a short human-readable signature for a node.
    E.g. 'FunctionNode(fibonacci)', 'AssignmentNode(x)', etc.
    """
    name = _node_type(node)
    if hasattr(node, 'name'):
        return f"{name}({node.name})"
    if hasattr(node, 'var_name'):
        return f"{name}({node.var_name})"
    if hasattr(node, 'value') and not isinstance(node.value, (list, dict)):
        val = repr(node.value)
        if len(val) > 30:
            val = val[:27] + "..."
        return f"{name}({val})"
    if hasattr(node, 'op'):
        return f"{name}({node.op})"
    return name


def _node_hash(node):
    """
    Compute a structural hash of an AST node and its children.
    Two nodes with the same hash are structurally identical.
    Ignores line_num so position changes don't affect equality.
    """
    if not isinstance(node, ASTNode):
        return hash(repr(node))

    parts = [_node_type(node)]

    # Collect scalar attributes (skip line_num — it's positional, not structural)
    for attr in sorted(vars(node)):
        if attr.startswith('_') or attr == 'line_num':
            continue
        val = getattr(node, attr)
        if isinstance(val, ASTNode):
            parts.append(f"{attr}={_node_hash(val)}")
        elif isinstance(val, list):
            items = tuple(_node_hash(v) for v in val)
            parts.append(f"{attr}={hash(items)}")
        else:
            parts.append(f"{attr}={hash(repr(val))}")

    return hash(tuple(parts))


def _node_to_dict(node, depth=0, max_depth=20):
    """Convert an AST node to a comparable dictionary."""
    if depth > max_depth:
        return {"type": _node_type(node), "...": "truncated"}

    if not isinstance(node, ASTNode):
        return repr(node)

    d = {"type": _node_type(node)}
    for attr in sorted(vars(node)):
        if attr.startswith('_') or attr == 'line_num':
            continue
        val = getattr(node, attr)
        if isinstance(val, ASTNode):
            d[attr] = _node_to_dict(val, depth + 1, max_depth)
        elif isinstance(val, list):
            d[attr] = [_node_to_dict(v, depth + 1, max_depth) if isinstance(v, ASTNode) else repr(v) for v in val]
        else:
            d[attr] = repr(val)
    return d


# ── Top-level statement matching ────────────────────────────────────

def _statement_key(node):
    """
    Generate a matching key for a top-level statement.
    Functions and enums match by name; others by position + type.
    """
    ntype = _node_type(node)
    if ntype == 'FunctionNode' and hasattr(node, 'name'):
        return ('function', node.name)
    if ntype == 'EnumNode' and hasattr(node, 'name'):
        return ('enum', node.name)
    if ntype == 'ImportNode' and hasattr(node, 'module_name'):
        return ('import', node.module_name)
    if ntype == 'AssignmentNode' and hasattr(node, 'name'):
        return ('assign', node.name)
    return None  # positional matching only


def _match_statements(old_stmts, new_stmts):
    """
    Match old and new top-level statements by key (name-based) first,
    then fall back to positional matching for unkeyed statements.

    Returns a list of (old_node_or_None, new_node_or_None) pairs.
    """
    old_by_key = {}
    old_positional = []
    for i, node in enumerate(old_stmts):
        key = _statement_key(node)
        if key:
            old_by_key[key] = (i, node)
        else:
            old_positional.append((i, node))

    new_by_key = {}
    new_positional = []
    for i, node in enumerate(new_stmts):
        key = _statement_key(node)
        if key:
            new_by_key[key] = (i, node)
        else:
            new_positional.append((i, node))

    pairs = []
    matched_old = set()
    matched_new = set()

    # Match by key
    all_keys = set(old_by_key.keys()) | set(new_by_key.keys())
    for key in sorted(all_keys, key=lambda k: old_by_key.get(k, (999,))[0]):
        old_entry = old_by_key.get(key)
        new_entry = new_by_key.get(key)
        old_node = old_entry[1] if old_entry else None
        new_node = new_entry[1] if new_entry else None
        pairs.append((old_node, new_node, key))
        if old_entry:
            matched_old.add(old_entry[0])
        if new_entry:
            matched_new.add(new_entry[0])

    # Positional matching for remaining
    old_remaining = [(i, n) for i, n in old_positional if i not in matched_old]
    new_remaining = [(i, n) for i, n in new_positional if i not in matched_new]

    max_len = max(len(old_remaining), len(new_remaining))
    for j in range(max_len):
        old_node = old_remaining[j][1] if j < len(old_remaining) else None
        new_node = new_remaining[j][1] if j < len(new_remaining) else None
        pairs.append((old_node, new_node, None))

    return pairs


# ── Diff computation ────────────────────────────────────────────────

class DiffEntry:
    """A single change between old and new AST."""
    ADDED = 'added'
    REMOVED = 'removed'
    MODIFIED = 'modified'
    UNCHANGED = 'unchanged'

    def __init__(self, kind, signature, old_node=None, new_node=None, details=None):
        self.kind = kind
        self.signature = signature
        self.old_node = old_node
        self.new_node = new_node
        self.details = details or []

    def to_dict(self):
        d = {
            "kind": self.kind,
            "signature": self.signature,
        }
        if self.details:
            d["details"] = self.details
        if self.old_node:
            d["old"] = _node_to_dict(self.old_node)
        if self.new_node:
            d["new"] = _node_to_dict(self.new_node)
        return d


def _diff_attrs(old_node, new_node):
    """Compare attributes of two same-type nodes, return list of change descriptions."""
    changes = []
    old_attrs = set(vars(old_node).keys())
    new_attrs = set(vars(new_node).keys())

    for attr in sorted(old_attrs | new_attrs):
        if attr.startswith('_') or attr == 'line_num':
            continue
        old_val = getattr(old_node, attr, None)
        new_val = getattr(new_node, attr, None)

        if isinstance(old_val, ASTNode) and isinstance(new_val, ASTNode):
            if _node_hash(old_val) != _node_hash(new_val):
                changes.append(f"  {attr}: {_node_signature(old_val)} -> {_node_signature(new_val)}")
        elif isinstance(old_val, list) and isinstance(new_val, list):
            old_len = len(old_val)
            new_len = len(new_val)
            if old_len != new_len:
                changes.append(f"  {attr}: {old_len} items -> {new_len} items")
            else:
                modified_count = 0
                for a, b in zip(old_val, new_val):
                    if isinstance(a, ASTNode) and isinstance(b, ASTNode):
                        if _node_hash(a) != _node_hash(b):
                            modified_count += 1
                    elif repr(a) != repr(b):
                        modified_count += 1
                if modified_count > 0:
                    changes.append(f"  {attr}: {modified_count}/{old_len} items changed")
        else:
            if repr(old_val) != repr(new_val):
                old_repr = repr(old_val)
                new_repr = repr(new_val)
                if len(old_repr) > 40:
                    old_repr = old_repr[:37] + "..."
                if len(new_repr) > 40:
                    new_repr = new_repr[:37] + "..."
                changes.append(f"  {attr}: {old_repr} -> {new_repr}")

    return changes


def _is_noise_node(node):
    """Check if a node is parser noise (stray 'end' tokens, etc.)."""
    if _node_type(node) == 'FunctionCallNode' and hasattr(node, 'name'):
        if node.name == 'end' and hasattr(node, 'arguments') and not node.arguments:
            return True
    return False


def compute_diff(old_ast, new_ast):
    """
    Compute semantic diff between two AST lists (top-level statements).
    Returns a list of DiffEntry objects.
    """
    # Filter out parser noise (stray 'end' tokens)
    old_ast = [n for n in old_ast if not _is_noise_node(n)]
    new_ast = [n for n in new_ast if not _is_noise_node(n)]

    pairs = _match_statements(old_ast, new_ast)
    entries = []

    for old_node, new_node, key in pairs:
        if old_node is None and new_node is not None:
            entries.append(DiffEntry(
                DiffEntry.ADDED,
                _node_signature(new_node),
                new_node=new_node
            ))
        elif old_node is not None and new_node is None:
            entries.append(DiffEntry(
                DiffEntry.REMOVED,
                _node_signature(old_node),
                old_node=old_node
            ))
        elif _node_hash(old_node) == _node_hash(new_node):
            entries.append(DiffEntry(
                DiffEntry.UNCHANGED,
                _node_signature(old_node),
                old_node=old_node,
                new_node=new_node
            ))
        else:
            details = _diff_attrs(old_node, new_node)
            entries.append(DiffEntry(
                DiffEntry.MODIFIED,
                _node_signature(old_node),
                old_node=old_node,
                new_node=new_node,
                details=details
            ))

    return entries


# ── Output formatting ───────────────────────────────────────────────

# ANSI colors
_RED = '\033[31m'
_GREEN = '\033[32m'
_YELLOW = '\033[33m'
_CYAN = '\033[36m'
_DIM = '\033[2m'
_BOLD = '\033[1m'
_RESET = '\033[0m'


def _color(text, code, use_color=True):
    if not use_color:
        return text
    return f"{code}{text}{_RESET}"


def format_diff(entries, use_color=True, show_unchanged=False, show_details=True):
    """Format diff entries as human-readable output."""
    lines = []

    added = sum(1 for e in entries if e.kind == DiffEntry.ADDED)
    removed = sum(1 for e in entries if e.kind == DiffEntry.REMOVED)
    modified = sum(1 for e in entries if e.kind == DiffEntry.MODIFIED)
    unchanged = sum(1 for e in entries if e.kind == DiffEntry.UNCHANGED)

    for entry in entries:
        if entry.kind == DiffEntry.ADDED:
            lines.append(_color(f"+ {entry.signature}", _GREEN, use_color))
        elif entry.kind == DiffEntry.REMOVED:
            lines.append(_color(f"- {entry.signature}", _RED, use_color))
        elif entry.kind == DiffEntry.MODIFIED:
            lines.append(_color(f"~ {entry.signature}", _YELLOW, use_color))
            if show_details and entry.details:
                for detail in entry.details:
                    lines.append(_color(detail, _DIM, use_color))
        elif entry.kind == DiffEntry.UNCHANGED and show_unchanged:
            lines.append(_color(f"  {entry.signature}", _DIM, use_color))

    # Summary
    lines.append("")
    parts = []
    if added:
        parts.append(_color(f"+{added} added", _GREEN, use_color))
    if removed:
        parts.append(_color(f"-{removed} removed", _RED, use_color))
    if modified:
        parts.append(_color(f"~{modified} modified", _YELLOW, use_color))
    parts.append(f"{unchanged} unchanged")

    lines.append(", ".join(parts))

    return "\n".join(lines)


def format_summary(entries):
    """Return a brief one-line summary."""
    counts = Counter(e.kind for e in entries)
    parts = []
    if counts.get(DiffEntry.ADDED, 0):
        parts.append(f"+{counts[DiffEntry.ADDED]}")
    if counts.get(DiffEntry.REMOVED, 0):
        parts.append(f"-{counts[DiffEntry.REMOVED]}")
    if counts.get(DiffEntry.MODIFIED, 0):
        parts.append(f"~{counts[DiffEntry.MODIFIED]}")
    total = sum(counts.values())
    unchanged = counts.get(DiffEntry.UNCHANGED, 0)
    if not parts:
        return f"No semantic changes ({unchanged} statements identical)"
    return f"{', '.join(parts)} ({unchanged}/{total} unchanged)"


def format_json(entries):
    """Return JSON representation of the diff."""
    result = {
        "summary": {
            "added": sum(1 for e in entries if e.kind == DiffEntry.ADDED),
            "removed": sum(1 for e in entries if e.kind == DiffEntry.REMOVED),
            "modified": sum(1 for e in entries if e.kind == DiffEntry.MODIFIED),
            "unchanged": sum(1 for e in entries if e.kind == DiffEntry.UNCHANGED),
        },
        "changes": [e.to_dict() for e in entries if e.kind != DiffEntry.UNCHANGED],
    }
    return _json.dumps(result, indent=2)


# ── Parsing helper ──────────────────────────────────────────────────

def parse_file(filepath):
    """Parse a .srv file and return its AST (list of top-level nodes)."""
    if not os.path.isfile(filepath):
        print(f"Error: File '{filepath}' not found.", file=sys.stderr)
        sys.exit(1)

    with open(filepath, 'r', encoding='utf-8') as f:
        code = f.read()

    try:
        tokens = tokenize(code)
        parser = Parser(tokens)
        return parser.parse()
    except Exception as e:
        print(f"Error parsing '{filepath}': {e}", file=sys.stderr)
        sys.exit(1)


# ── CLI ─────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Semantic diff for sauravcode (.srv) files. "
                    "Compares AST structure, ignoring formatting changes.",
        epilog="Examples:\n"
               "  sauravdiff old.srv new.srv           # Colored diff\n"
               "  sauravdiff old.srv new.srv --json     # JSON output\n"
               "  sauravdiff old.srv new.srv --summary  # Counts only\n"
               "  sauravdiff old.srv new.srv --all      # Show unchanged too\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument('old', help='Original .srv file')
    ap.add_argument('new', help='Modified .srv file')
    ap.add_argument('--json', action='store_true', help='Output as JSON')
    ap.add_argument('--summary', action='store_true', help='One-line summary only')
    ap.add_argument('--all', action='store_true', help='Show unchanged statements too')
    ap.add_argument('--no-color', action='store_true', help='Disable ANSI colors')
    ap.add_argument('--no-details', action='store_true', help='Hide attribute-level changes')

    args = ap.parse_args()

    for f in [args.old, args.new]:
        if not f.endswith('.srv'):
            print(f"Error: '{f}' does not have a .srv extension.", file=sys.stderr)
            sys.exit(1)

    old_ast = parse_file(args.old)
    new_ast = parse_file(args.new)

    entries = compute_diff(old_ast, new_ast)

    if args.json:
        print(format_json(entries))
    elif args.summary:
        print(format_summary(entries))
    else:
        use_color = not args.no_color and sys.stdout.isatty()
        print(format_diff(entries, use_color=use_color,
                          show_unchanged=args.all,
                          show_details=not args.no_details))

    # Exit code: 0 = identical, 1 = differences found
    has_changes = any(e.kind != DiffEntry.UNCHANGED for e in entries)
    sys.exit(1 if has_changes else 0)


if __name__ == '__main__':
    main()
