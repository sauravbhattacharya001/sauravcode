#!/usr/bin/env python3
"""sauravexplain -- Code-to-English narrator for sauravcode programs.

Parses a .srv file and generates a human-readable, line-by-line explanation
of what the code does.  Ideal for learning, code review, and documentation.

Usage:
    python sauravexplain.py program.srv               # Explain entire file
    python sauravexplain.py program.srv --verbose      # Include AST node types
    python sauravexplain.py program.srv --summary      # High-level summary only
    python sauravexplain.py program.srv --json         # JSON output
    python sauravexplain.py program.srv --lines 10-20  # Explain specific lines
    python sauravexplain.py program.srv --depth 2      # Limit nesting depth
    python sauravexplain.py program.srv --toc          # Table of contents
    python sauravexplain.py -c 'x = 5'                 # Explain a snippet
"""

import sys
import os
import json as _json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from saurav import tokenize, Parser, ASTNode

__version__ = "1.0.0"

# ── AST node imports ────────────────────────────────────────────────
from saurav import (
    AssignmentNode, FunctionNode, ReturnNode, YieldNode,
    BinaryOpNode, NumberNode, StringNode, IdentifierNode,
    PrintNode, FunctionCallNode, CompareNode, LogicalNode,
    UnaryOpNode, BoolNode, IfNode, WhileNode, ForNode,
    ListNode, IndexNode, AppendNode, PopNode, LenNode,
    MapNode, FStringNode, IndexedAssignmentNode, ForEachNode,
    TryCatchNode, ThrowNode, LambdaNode, PipeNode, ImportNode,
    ListComprehensionNode, MatchNode, CaseNode, EnumNode,
    EnumAccessNode, SliceNode, AssertNode, BreakNode,
    ContinueNode, TernaryNode,
)

# ── Operator descriptions ──────────────────────────────────────────

_OP_WORDS = {
    '+': 'plus', '-': 'minus', '*': 'times', '/': 'divided by', '%': 'modulo',
}

_CMP_WORDS = {
    '==': 'equals', '!=': 'does not equal',
    '<': 'is less than', '>': 'is greater than',
    '<=': 'is at most', '>=': 'is at least',
}

_LOGIC_WORDS = {
    'and': 'and', 'or': 'or',
}


# ── Expression describer ───────────────────────────────────────────

def describe_expr(node, depth=0):
    """Return a natural-language description of an expression AST node."""
    if isinstance(node, NumberNode):
        v = node.value
        if isinstance(v, float) and v == int(v) and abs(v) < 1e15:
            return str(int(v))
        return str(v)

    if isinstance(node, StringNode):
        return f'"{node.value}"'

    if isinstance(node, BoolNode):
        return "true" if node.value else "false"

    if isinstance(node, IdentifierNode):
        return node.name

    if isinstance(node, BinaryOpNode):
        left = describe_expr(node.left, depth + 1)
        right = describe_expr(node.right, depth + 1)
        op = _OP_WORDS.get(node.operator, node.operator)
        if depth == 0:
            return f"{left} {op} {right}"
        return f"({left} {op} {right})"

    if isinstance(node, CompareNode):
        left = describe_expr(node.left, depth + 1)
        right = describe_expr(node.right, depth + 1)
        op = _CMP_WORDS.get(node.operator, node.operator)
        return f"{left} {op} {right}"

    if isinstance(node, LogicalNode):
        left = describe_expr(node.left, depth + 1)
        right = describe_expr(node.right, depth + 1)
        op = _LOGIC_WORDS.get(node.operator, node.operator)
        return f"{left} {op} {right}"

    if isinstance(node, UnaryOpNode):
        operand = describe_expr(node.operand, depth + 1)
        if node.operator == 'not':
            return f"not {operand}"
        return f"{node.operator}{operand}"

    if isinstance(node, FunctionCallNode):
        name = node.name
        args = [describe_expr(a, depth + 1) for a in node.arguments]
        if args:
            return f"call {name} with {', '.join(args)}"
        return f"call {name}"

    if isinstance(node, LambdaNode):
        params = ', '.join(node.params)
        body = describe_expr(node.body_expr, depth + 1)
        return f"an anonymous function({params}) returning {body}"

    if isinstance(node, ListNode):
        if not node.elements:
            return "an empty list"
        items = [describe_expr(e, depth + 1) for e in node.elements]
        if len(items) <= 5:
            return f"[{', '.join(items)}]"
        return f"a list of {len(items)} items"

    if isinstance(node, MapNode):
        if not node.pairs:
            return "an empty map"
        count = len(node.pairs)
        if count <= 3:
            pairs = []
            for k, v in node.pairs:
                pairs.append(f"{describe_expr(k, depth+1)}: {describe_expr(v, depth+1)}")
            return "{" + ', '.join(pairs) + "}"
        return f"a map with {count} entries"

    if isinstance(node, IndexNode):
        obj = describe_expr(node.obj, depth + 1)
        idx = describe_expr(node.index, depth + 1)
        return f"{obj}[{idx}]"

    if isinstance(node, SliceNode):
        obj = describe_expr(node.obj, depth + 1)
        parts = []
        if node.start is not None:
            parts.append(f"from {describe_expr(node.start, depth+1)}")
        if node.end is not None:
            parts.append(f"to {describe_expr(node.end, depth+1)}")
        return f"slice of {obj} {' '.join(parts)}" if parts else f"full copy of {obj}"

    if isinstance(node, LenNode):
        return f"the length of {describe_expr(node.expression, depth + 1)}"

    if isinstance(node, PopNode):
        return f"pop from {node.list_name}"

    if isinstance(node, FStringNode):
        # Build a readable description from the parts
        expr_parts = [p for p in node.parts if not isinstance(p, StringNode)]
        if not expr_parts:
            # All literal parts
            text = ''.join(p.value for p in node.parts)
            return f'f-string "{text}"'
        if len(expr_parts) == 1:
            return f"a formatted string with {describe_expr(expr_parts[0], depth+1)}"
        names = [describe_expr(p, depth+1) for p in expr_parts[:3]]
        suffix = f" and {len(expr_parts)-3} more" if len(expr_parts) > 3 else ""
        return f"a formatted string with {', '.join(names)}{suffix}"

    if isinstance(node, PipeNode):
        val = describe_expr(node.value, depth + 1)
        func = describe_expr(node.function, depth + 1)
        return f"pipe {val} into {func}"

    if isinstance(node, TernaryNode):
        cond = describe_expr(node.condition, depth + 1)
        true_val = describe_expr(node.true_expr, depth + 1)
        false_val = describe_expr(node.false_expr, depth + 1)
        return f"{true_val} if {cond}, otherwise {false_val}"

    if isinstance(node, EnumAccessNode):
        return f"{node.enum_name}.{node.variant_name}"

    if isinstance(node, ListComprehensionNode):
        expr = describe_expr(node.expr, depth + 1)
        var = node.var
        iter_expr = describe_expr(node.iterable, depth + 1)
        if node.condition is not None:
            cond = describe_expr(node.condition, depth + 1)
            return f"[{expr} for each {var} in {iter_expr} where {cond}]"
        return f"[{expr} for each {var} in {iter_expr}]"

    # Fallback
    return f"<{type(node).__name__}>"


# ── Statement explainer ────────────────────────────────────────────

def explain_node(node, indent=0, verbose=False, max_depth=None, _depth=0):
    """Return a list of (indent_level, explanation_text, line_num) tuples."""
    if max_depth is not None and _depth > max_depth:
        return [(indent, "... (deeper code omitted)", getattr(node, 'line_num', None))]

    results = []
    line = getattr(node, 'line_num', None)
    tag = f"  [{type(node).__name__}]" if verbose else ""

    if isinstance(node, AssignmentNode):
        val = describe_expr(node.expression)
        results.append((indent, f"Set {node.name} to {val}{tag}", line))

    elif isinstance(node, FunctionNode):
        params = ', '.join(node.params) if node.params else 'no parameters'
        results.append((indent, f"Define function '{node.name}' ({params}){tag}", line))
        for stmt in node.body:
            results.extend(explain_node(stmt, indent + 1, verbose, max_depth, _depth + 1))

    elif isinstance(node, ReturnNode):
        val = describe_expr(node.expression) if node.expression else "nothing"
        results.append((indent, f"Return {val}{tag}", line))

    elif isinstance(node, YieldNode):
        val = describe_expr(node.expression) if node.expression else "nothing"
        results.append((indent, f"Yield {val}{tag}", line))

    elif isinstance(node, PrintNode):
        val = describe_expr(node.expression)
        results.append((indent, f"Print {val}{tag}", line))

    elif isinstance(node, IfNode):
        cond = describe_expr(node.condition)
        results.append((indent, f"If {cond}:{tag}", line))
        for stmt in node.body:
            results.extend(explain_node(stmt, indent + 1, verbose, max_depth, _depth + 1))
        # elif_chains is a list of (condition, body) tuples
        if hasattr(node, 'elif_chains') and node.elif_chains:
            for elif_cond, elif_body in node.elif_chains:
                ec = describe_expr(elif_cond)
                results.append((indent, f"Otherwise, if {ec}:", None))
                for stmt in elif_body:
                    results.extend(explain_node(stmt, indent + 1, verbose, max_depth, _depth + 1))
        if node.else_body:
            results.append((indent, "Otherwise:", None))
            for stmt in node.else_body:
                results.extend(explain_node(stmt, indent + 1, verbose, max_depth, _depth + 1))

    elif isinstance(node, WhileNode):
        cond = describe_expr(node.condition)
        results.append((indent, f"Repeat while {cond}:{tag}", line))
        for stmt in node.body:
            results.extend(explain_node(stmt, indent + 1, verbose, max_depth, _depth + 1))

    elif isinstance(node, ForNode):
        var = node.var
        start = describe_expr(node.start)
        end = describe_expr(node.end)
        results.append((indent, f"Count {var} from {start} to {end}:{tag}", line))
        for stmt in node.body:
            results.extend(explain_node(stmt, indent + 1, verbose, max_depth, _depth + 1))

    elif isinstance(node, ForEachNode):
        var = node.var
        iterable = describe_expr(node.iterable)
        results.append((indent, f"For each {var} in {iterable}:{tag}", line))
        for stmt in node.body:
            results.extend(explain_node(stmt, indent + 1, verbose, max_depth, _depth + 1))

    elif isinstance(node, TryCatchNode):
        results.append((indent, f"Try:{tag}", line))
        for stmt in node.body:
            results.extend(explain_node(stmt, indent + 1, verbose, max_depth, _depth + 1))
        err_var = node.error_var if hasattr(node, 'error_var') else 'error'
        results.append((indent, f"If an error occurs (caught as '{err_var}'):", None))
        # handler is the catch body
        handler = node.handler if hasattr(node, 'handler') else []
        for stmt in handler:
            results.extend(explain_node(stmt, indent + 1, verbose, max_depth, _depth + 1))

    elif isinstance(node, ThrowNode):
        val = describe_expr(node.expression)
        results.append((indent, f"Throw error: {val}{tag}", line))

    elif isinstance(node, ImportNode):
        mod = node.module_path if hasattr(node, 'module_path') else '?'
        results.append((indent, f"Import module '{mod}'{tag}", line))

    elif isinstance(node, AppendNode):
        val = describe_expr(node.value)
        results.append((indent, f"Append {val} to {node.list_name}{tag}", line))

    elif isinstance(node, IndexedAssignmentNode):
        idx = describe_expr(node.index)
        val = describe_expr(node.value)
        results.append((indent, f"Set {node.name}[{idx}] to {val}{tag}", line))

    elif isinstance(node, EnumNode):
        variants = ', '.join(node.variants)
        results.append((indent, f"Define enum '{node.name}' with variants: {variants}{tag}", line))

    elif isinstance(node, MatchNode):
        subject = describe_expr(node.expression)
        results.append((indent, f"Match {subject} against:{tag}", line))
        for case in node.cases:
            results.extend(explain_node(case, indent + 1, verbose, max_depth, _depth + 1))

    elif isinstance(node, CaseNode):
        if node.is_wildcard:
            label = f"_ (wildcard)"
            if node.binding_name:
                label = f"_ as {node.binding_name}"
        else:
            pats = ' | '.join(describe_expr(p) for p in node.patterns)
            label = pats
        results.append((indent, f"Case {label}:", line))
        for stmt in node.body:
            results.extend(explain_node(stmt, indent + 1, verbose, max_depth, _depth + 1))

    elif isinstance(node, AssertNode):
        cond = describe_expr(node.condition)
        if node.message:
            msg = describe_expr(node.message)
            results.append((indent, f"Assert that {cond}, or fail with {msg}{tag}", line))
        else:
            results.append((indent, f"Assert that {cond}{tag}", line))

    elif isinstance(node, BreakNode):
        results.append((indent, f"Break out of the loop{tag}", line))

    elif isinstance(node, ContinueNode):
        results.append((indent, f"Skip to the next iteration{tag}", line))

    elif isinstance(node, FunctionCallNode):
        desc = describe_expr(node)
        results.append((indent, f"{desc}{tag}", line))

    else:
        # Fallback — treat as expression statement
        desc = describe_expr(node)
        results.append((indent, f"{desc}{tag}", line))

    return results


# ── Summary generator ──────────────────────────────────────────────

def generate_summary(ast_nodes):
    """Generate a high-level summary of the program."""
    functions = []
    enums = []
    imports = []
    top_level_count = 0
    has_try = False
    has_loops = False
    has_match = False
    has_assertions = False

    for node in ast_nodes:
        if isinstance(node, FunctionNode):
            functions.append((node.name, node.params))
        elif isinstance(node, EnumNode):
            enums.append(node.name)
        elif isinstance(node, ImportNode):
            mod = node.module_path if hasattr(node, 'module_path') else '?'
            imports.append(mod)
        elif isinstance(node, TryCatchNode):
            has_try = True
            top_level_count += 1
        elif isinstance(node, (WhileNode, ForNode, ForEachNode)):
            has_loops = True
            top_level_count += 1
        elif isinstance(node, MatchNode):
            has_match = True
            top_level_count += 1
        elif isinstance(node, AssertNode):
            has_assertions = True
            top_level_count += 1
        else:
            top_level_count += 1

    lines = []
    lines.append("Program Summary")
    lines.append("=" * 50)

    if imports:
        lines.append(f"  Imports: {', '.join(imports)}")

    if enums:
        lines.append(f"  Enums: {', '.join(enums)}")

    if functions:
        lines.append(f"  Functions ({len(functions)}):")
        for name, params in functions:
            p = ', '.join(params) if params else ''
            lines.append(f"    - {name}({p})")

    lines.append(f"  Top-level statements: {top_level_count}")

    features = []
    if has_try:
        features.append("error handling")
    if has_loops:
        features.append("loops")
    if functions:
        features.append("functions")
    if enums:
        features.append("enums")
    if imports:
        features.append("imports")
    if has_match:
        features.append("pattern matching")
    if has_assertions:
        features.append("assertions")
    if features:
        lines.append(f"  Features used: {', '.join(features)}")

    lines.append("")
    return '\n'.join(lines)


# ── Table of contents ──────────────────────────────────────────────

def generate_toc(ast_nodes):
    """Generate a table of contents listing functions, enums, etc."""
    lines = []
    lines.append("Table of Contents")
    lines.append("=" * 50)

    section = 1
    for node in ast_nodes:
        ln = getattr(node, 'line_num', '?')
        if isinstance(node, FunctionNode):
            params = ', '.join(node.params) if node.params else ''
            lines.append(f"  {section}. function {node.name}({params})  [line {ln}]")
            section += 1
        elif isinstance(node, EnumNode):
            lines.append(f"  {section}. enum {node.name}  [line {ln}]")
            section += 1

    if section == 1:
        lines.append("  (no named definitions found)")

    lines.append("")
    return '\n'.join(lines)


# ── Formatting ─────────────────────────────────────────────────────

def format_explanation(entries, show_lines=True):
    """Format explanation entries into readable text."""
    lines = []
    step = 0
    for indent_level, text, _line_num in entries:
        prefix = "    " * indent_level
        step += 1
        if show_lines:
            lines.append(f"  {step:>3}. {prefix}{text}")
        else:
            lines.append(f"  {prefix}{text}")
    return '\n'.join(lines)


def to_json(entries):
    """Convert explanation entries to JSON-serialisable list."""
    return [
        {"indent": indent, "text": text, "line": line_num}
        for indent, text, line_num in entries
    ]


# ── Line range filter ──────────────────────────────────────────────

def parse_line_range(spec):
    """Parse a line range spec like '10-20' or '5' into (start, end)."""
    if '-' in spec:
        parts = spec.split('-', 1)
        return int(parts[0]), int(parts[1])
    n = int(spec)
    return n, n


def filter_by_lines(ast_nodes, start, end):
    """Filter AST nodes to only those within the given line range."""
    filtered = []
    for node in ast_nodes:
        ln = getattr(node, 'line_num', None)
        if ln is not None and start <= ln <= end:
            filtered.append(node)
    return filtered


# ── Main ───────────────────────────────────────────────────────────

def explain(source, verbose=False, max_depth=None, line_range=None):
    """Parse source code and return explanation entries."""
    tokens = tokenize(source)
    parser = Parser(tokens)
    ast_nodes = parser.parse()

    if line_range is not None:
        start, end = line_range
        ast_nodes = filter_by_lines(ast_nodes, start, end)

    entries = []
    for node in ast_nodes:
        entries.extend(explain_node(node, indent=0, verbose=verbose,
                                    max_depth=max_depth))
    return ast_nodes, entries


def main():
    p = argparse.ArgumentParser(
        prog='sauravexplain',
        description='Code-to-English narrator for sauravcode programs.',
    )
    p.add_argument('file', nargs='?', help='.srv file to explain')
    p.add_argument('-c', '--code', help='explain a code snippet')
    p.add_argument('--verbose', '-v', action='store_true',
                   help='include AST node types in output')
    p.add_argument('--summary', '-s', action='store_true',
                   help='high-level summary only')
    p.add_argument('--toc', action='store_true',
                   help='table of contents (functions, enums)')
    p.add_argument('--json', action='store_true',
                   help='JSON output')
    p.add_argument('--lines', help='explain specific lines (e.g. 10-20)')
    p.add_argument('--depth', type=int, default=None,
                   help='maximum nesting depth to show')
    p.add_argument('--no-lines', action='store_true',
                   help='hide line numbers')
    p.add_argument('--version', action='version',
                   version=f'%(prog)s {__version__}')
    args = p.parse_args()

    if args.code:
        source = args.code
        filename = '<snippet>'
    elif args.file:
        if not os.path.isfile(args.file):
            print(f"Error: file not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        with open(args.file, 'r', encoding='utf-8') as f:
            source = f.read()
        filename = args.file
    else:
        p.print_help()
        sys.exit(0)

    line_range = None
    if args.lines:
        try:
            line_range = parse_line_range(args.lines)
        except ValueError:
            print(f"Error: invalid line range '{args.lines}' (use N or N-M)",
                  file=sys.stderr)
            sys.exit(1)

    ast_nodes, entries = explain(source, verbose=args.verbose,
                                 max_depth=args.depth,
                                 line_range=line_range)

    if args.summary:
        print(generate_summary(ast_nodes))
        return

    if args.toc:
        print(generate_toc(ast_nodes))
        return

    if args.json:
        data = {
            'file': filename,
            'explanations': to_json(entries),
            'summary': {
                'total_statements': len(entries),
                'functions': [n.name for n in ast_nodes if isinstance(n, FunctionNode)],
            },
        }
        print(_json.dumps(data, indent=2))
        return

    # Default: full explanation
    print(f"\nExplanation of {filename}")
    print("=" * 50)
    print(format_explanation(entries, show_lines=not args.no_lines))
    print()


if __name__ == '__main__':
    main()
