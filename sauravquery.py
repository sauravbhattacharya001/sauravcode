#!/usr/bin/env python3
"""
sauravquery.py - Structural code query tool for sauravcode programs.

Search .srv codebases by AST patterns rather than text — find functions
that call X, loops without break, unused variables, deeply nested code,
and more.

Usage:
    python sauravquery.py program.srv functions              # List all functions
    python sauravquery.py program.srv calls                  # List all function calls
    python sauravquery.py program.srv calls --name add       # Calls to 'add'
    python sauravquery.py program.srv variables --unused     # Unused variables
    python sauravquery.py program.srv loops                  # All loops
    python sauravquery.py program.srv loops --no-break       # Loops without break
    python sauravquery.py program.srv complexity             # Nesting/complexity report
    python sauravquery.py program.srv assignments            # All assignments
    python sauravquery.py program.srv imports                # Import statements
    python sauravquery.py program.srv summary                # Full codebase summary
    python sauravquery.py src/ functions --recursive         # Search directory
    python sauravquery.py program.srv functions --json       # JSON output

Queries:
    functions     List function definitions (name, params, line)
    calls         List function call sites
    variables     List variable assignments (--unused for dead code)
    loops         List for/foreach/while loops (--no-break, --depth N)
    assignments   List all assignment statements
    imports       List import statements
    conditions    List if/else chains (--depth N for nesting)
    complexity    Nesting depth and complexity report per function
    strings       List all string literals
    patterns      Find specific AST patterns (--node-type, --has-child)
    summary       Full codebase structural summary
"""

import sys
import os
import argparse
import json as _json
from collections import defaultdict, Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from saurav import tokenize, Parser, ASTNode


# ── AST Walking ─────────────────────────────────────────────────────

def walk_ast(nodes, depth=0):
    """Yield (node, depth) for every ASTNode in the tree."""
    if isinstance(nodes, list):
        for node in nodes:
            yield from walk_ast(node, depth)
    elif isinstance(nodes, ASTNode):
        yield (nodes, depth)
        for attr in sorted(vars(nodes)):
            if attr.startswith('_') or attr == 'line_num':
                continue
            val = getattr(nodes, attr)
            if isinstance(val, ASTNode):
                yield from walk_ast(val, depth + 1)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, ASTNode):
                        yield from walk_ast(item, depth + 1)


def children_of(node):
    """Return direct ASTNode children of a node."""
    kids = []
    for attr in sorted(vars(node)):
        if attr.startswith('_') or attr == 'line_num':
            continue
        val = getattr(node, attr)
        if isinstance(val, ASTNode):
            kids.append(val)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, ASTNode):
                    kids.append(item)
    return kids


def contains_node_type(node, type_name):
    """Check if any descendant has the given type name."""
    for child, _ in walk_ast(node):
        if type(child).__name__ == type_name and child is not node:
            return True
    return False


# ── File Parsing ─────────────────────────────────────────────────────

def parse_file(path):
    """Parse a .srv file and return (ast_nodes, filename)."""
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        source = f.read()
    tokens = tokenize(source)
    parser = Parser(tokens)
    return parser.parse(), os.path.basename(path)


def collect_files(path, recursive=False):
    """Collect .srv files from a path (file or directory)."""
    if os.path.isfile(path):
        if path.endswith('.srv'):
            return [path]
        return []
    if os.path.isdir(path):
        files = []
        if recursive:
            for root, dirs, fnames in os.walk(path):
                for fn in sorted(fnames):
                    if fn.endswith('.srv'):
                        files.append(os.path.join(root, fn))
        else:
            for fn in sorted(os.listdir(path)):
                if fn.endswith('.srv'):
                    files.append(os.path.join(path, fn))
        return files
    return []


# ── Query: functions ─────────────────────────────────────────────────

def query_functions(ast, filename, name_filter=None):
    """Find all function definitions."""
    results = []
    for node, depth in walk_ast(ast):
        if type(node).__name__ == 'FunctionNode':
            fname = getattr(node, 'name', '?')
            params = getattr(node, 'params', [])
            if name_filter and name_filter.lower() not in fname.lower():
                continue
            # Count body statements
            body = getattr(node, 'body', [])
            body_size = len(body) if isinstance(body, list) else 1
            # Check for return
            has_return = contains_node_type(node, 'ReturnNode')
            has_yield = contains_node_type(node, 'YieldNode')
            line = getattr(node, 'line_num', '?')
            results.append({
                'file': filename,
                'name': fname,
                'params': params if isinstance(params, list) else [],
                'line': line,
                'body_size': body_size,
                'has_return': has_return,
                'is_generator': has_yield,
                'depth': depth,
            })
    return results


# ── Query: calls ─────────────────────────────────────────────────────

def query_calls(ast, filename, name_filter=None):
    """Find all function call sites."""
    results = []
    for node, depth in walk_ast(ast):
        if type(node).__name__ == 'FunctionCallNode':
            fname = getattr(node, 'name', '?')
            args = getattr(node, 'args', [])
            if name_filter and name_filter.lower() not in fname.lower():
                continue
            line = getattr(node, 'line_num', '?')
            results.append({
                'file': filename,
                'name': fname,
                'arg_count': len(args) if isinstance(args, list) else 0,
                'line': line,
                'depth': depth,
            })
    return results


# ── Query: variables ─────────────────────────────────────────────────

def query_variables(ast, filename, unused_only=False):
    """Find variable assignments, optionally filtering to unused ones."""
    assigned = {}  # name -> list of lines
    used = set()

    for node, _ in walk_ast(ast):
        ntype = type(node).__name__
        if ntype == 'AssignmentNode':
            name = getattr(node, 'name', None)
            if name:
                assigned.setdefault(name, []).append(getattr(node, 'line_num', '?'))
        elif ntype == 'IdentifierNode':
            name = getattr(node, 'name', None)
            if name:
                used.add(name)

    results = []
    for name, lines in sorted(assigned.items()):
        is_unused = name not in used
        if unused_only and not is_unused:
            continue
        results.append({
            'file': filename,
            'name': name,
            'lines': lines,
            'assign_count': len(lines),
            'unused': is_unused,
        })
    return results


# ── Query: loops ─────────────────────────────────────────────────────

def query_loops(ast, filename, no_break=False, max_depth=None):
    """Find all loop constructs."""
    results = []
    loop_types = ('ForNode', 'ForEachNode', 'WhileNode')
    for node, depth in walk_ast(ast):
        ntype = type(node).__name__
        if ntype in loop_types:
            if max_depth is not None and depth > max_depth:
                continue
            has_break = contains_node_type(node, 'BreakNode')
            has_continue = contains_node_type(node, 'ContinueNode')
            if no_break and has_break:
                continue
            line = getattr(node, 'line_num', '?')
            info = {
                'file': filename,
                'type': ntype.replace('Node', ''),
                'line': line,
                'depth': depth,
                'has_break': has_break,
                'has_continue': has_continue,
            }
            # Add loop variable info
            if ntype == 'ForNode':
                info['var'] = getattr(node, 'var', getattr(node, 'var_name', getattr(node, 'variable', '?')))
            elif ntype == 'ForEachNode':
                info['var'] = getattr(node, 'var', getattr(node, 'var_name', getattr(node, 'variable', '?')))
            elif ntype == 'WhileNode':
                info['var'] = None
            results.append(info)
    return results


# ── Query: assignments ───────────────────────────────────────────────

def query_assignments(ast, filename, name_filter=None):
    """Find all assignment statements."""
    results = []
    for node, depth in walk_ast(ast):
        ntype = type(node).__name__
        if ntype in ('AssignmentNode', 'IndexedAssignmentNode'):
            name = getattr(node, 'name', getattr(node, 'target', '?'))
            if name_filter and name_filter.lower() not in str(name).lower():
                continue
            line = getattr(node, 'line_num', '?')
            expr = getattr(node, 'expression', getattr(node, 'value', None))
            expr_type = type(expr).__name__ if isinstance(expr, ASTNode) else type(expr).__name__
            results.append({
                'file': filename,
                'name': str(name),
                'line': line,
                'indexed': ntype == 'IndexedAssignmentNode',
                'expr_type': expr_type,
                'depth': depth,
            })
    return results


# ── Query: imports ───────────────────────────────────────────────────

def query_imports(ast, filename):
    """Find all import statements."""
    results = []
    for node, depth in walk_ast(ast):
        if type(node).__name__ == 'ImportNode':
            module = getattr(node, 'module_path', getattr(node, 'module', getattr(node, 'name', '?')))
            line = getattr(node, 'line_num', '?')
            results.append({
                'file': filename,
                'module': module,
                'line': line,
            })
    return results


# ── Query: conditions ────────────────────────────────────────────────

def query_conditions(ast, filename, min_depth=None):
    """Find all if/else chains."""
    results = []
    for node, depth in walk_ast(ast):
        if type(node).__name__ == 'IfNode':
            if min_depth is not None and depth < min_depth:
                continue
            has_else = getattr(node, 'else_body', None) is not None
            elif_count = 0
            # Count elif branches
            elifs = getattr(node, 'elif_branches', getattr(node, 'elifs', []))
            if isinstance(elifs, list):
                elif_count = len(elifs)
            line = getattr(node, 'line_num', '?')
            results.append({
                'file': filename,
                'line': line,
                'depth': depth,
                'has_else': has_else,
                'elif_count': elif_count,
                'nested_ifs': sum(1 for c, _ in walk_ast(node)
                                 if type(c).__name__ == 'IfNode' and c is not node),
            })
    return results


# ── Query: complexity ────────────────────────────────────────────────

def _max_nesting(node, cur=0):
    """Compute maximum nesting depth under a node."""
    nesting_types = ('IfNode', 'ForNode', 'ForEachNode', 'WhileNode',
                     'TryCatchNode', 'MatchNode')
    best = cur
    for child in children_of(node):
        child_depth = cur + 1 if type(child).__name__ in nesting_types else cur
        best = max(best, _max_nesting(child, child_depth))
    return best


def _count_branches(node):
    """Count branching constructs under a node."""
    branch_types = ('IfNode', 'MatchNode', 'TryCatchNode')
    return sum(1 for n, _ in walk_ast(node)
               if type(n).__name__ in branch_types and n is not node)


def query_complexity(ast, filename):
    """Compute complexity metrics per function."""
    results = []
    for node, _ in walk_ast(ast):
        if type(node).__name__ == 'FunctionNode':
            fname = getattr(node, 'name', '?')
            body = getattr(node, 'body', [])
            stmt_count = len(body) if isinstance(body, list) else 1
            max_nest = _max_nesting(node)
            branches = _count_branches(node)
            calls = sum(1 for n, _ in walk_ast(node)
                        if type(n).__name__ == 'FunctionCallNode')
            loops = sum(1 for n, _ in walk_ast(node)
                        if type(n).__name__ in ('ForNode', 'ForEachNode', 'WhileNode'))
            line = getattr(node, 'line_num', '?')

            # Simple cyclomatic-ish complexity
            complexity = 1 + branches + loops
            if complexity <= 5:
                rating = 'simple'
            elif complexity <= 10:
                rating = 'moderate'
            elif complexity <= 20:
                rating = 'complex'
            else:
                rating = 'very complex'

            results.append({
                'file': filename,
                'name': fname,
                'line': line,
                'statements': stmt_count,
                'max_nesting': max_nest,
                'branches': branches,
                'loops': loops,
                'calls': calls,
                'complexity': complexity,
                'rating': rating,
            })
    return results


# ── Query: strings ───────────────────────────────────────────────────

def query_strings(ast, filename, pattern=None):
    """Find all string literals."""
    results = []
    for node, depth in walk_ast(ast):
        ntype = type(node).__name__
        if ntype in ('StringNode', 'FStringNode'):
            val = getattr(node, 'value', getattr(node, 'parts', '?'))
            line = getattr(node, 'line_num', '?')
            val_str = str(val)
            if pattern and pattern.lower() not in val_str.lower():
                continue
            results.append({
                'file': filename,
                'type': 'fstring' if ntype == 'FStringNode' else 'string',
                'value': val_str[:80],
                'line': line,
                'depth': depth,
            })
    return results


# ── Query: patterns ──────────────────────────────────────────────────

def query_patterns(ast, filename, node_type=None, has_child=None):
    """Generic AST pattern finder."""
    results = []
    for node, depth in walk_ast(ast):
        ntype = type(node).__name__
        if node_type and node_type.lower() not in ntype.lower():
            continue
        if has_child:
            if not contains_node_type(node, has_child):
                continue
        line = getattr(node, 'line_num', '?')
        results.append({
            'file': filename,
            'node_type': ntype,
            'line': line,
            'depth': depth,
            'children': len(children_of(node)),
        })
    return results


# ── Query: summary ───────────────────────────────────────────────────

def query_summary(ast, filename):
    """Full structural summary."""
    type_counts = Counter()
    max_depth = 0
    for node, depth in walk_ast(ast):
        type_counts[type(node).__name__] += 1
        max_depth = max(max_depth, depth)

    funcs = query_functions(ast, filename)
    calls = query_calls(ast, filename)
    loops = query_loops(ast, filename)
    imports = query_imports(ast, filename)
    variables = query_variables(ast, filename)
    unused = [v for v in variables if v['unused']]

    call_targets = Counter(c['name'] for c in calls)

    return {
        'file': filename,
        'total_nodes': sum(type_counts.values()),
        'node_types': len(type_counts),
        'max_depth': max_depth,
        'functions': len(funcs),
        'function_names': [f['name'] for f in funcs],
        'generators': sum(1 for f in funcs if f['is_generator']),
        'total_calls': len(calls),
        'top_called': dict(call_targets.most_common(10)),
        'loops': len(loops),
        'variables': len(variables),
        'unused_variables': len(unused),
        'unused_names': [v['name'] for v in unused],
        'imports': len(imports),
        'import_modules': [i['module'] for i in imports],
        'type_breakdown': dict(type_counts.most_common(15)),
    }


# ── Formatting ───────────────────────────────────────────────────────

# ANSI colors
_C = {
    'bold': '\033[1m', 'dim': '\033[2m', 'reset': '\033[0m',
    'cyan': '\033[36m', 'yellow': '\033[33m', 'green': '\033[32m',
    'red': '\033[31m', 'magenta': '\033[35m', 'blue': '\033[34m',
}

def _c(text, *styles):
    """Apply ANSI styles to text."""
    prefix = ''.join(_C.get(s, '') for s in styles)
    return f"{prefix}{text}{_C['reset']}" if prefix else text


def format_results(results, query_type, use_json=False):
    """Format query results for display."""
    if use_json:
        return _json.dumps(results, indent=2, default=str)

    if not results:
        return _c("No results found.", 'dim')

    lines = []

    if query_type == 'functions':
        lines.append(_c(f"  {'Name':<25} {'Params':<20} {'Body':<6} {'Ret':<5} {'Gen':<5} {'Line'}", 'bold'))
        lines.append("  " + "─" * 80)
        for r in results:
            params = ', '.join(r['params']) if r['params'] else '(none)'
            ret = '✓' if r['has_return'] else '·'
            gen = '⚡' if r['is_generator'] else '·'
            loc = f"{r['file']}:{r['line']}"
            lines.append(f"  {_c(r['name'], 'cyan'):<34} {params:<20} {r['body_size']:<6} {ret:<5} {gen:<5} {_c(loc, 'dim')}")

    elif query_type == 'calls':
        lines.append(_c(f"  {'Function':<25} {'Args':<6} {'Location'}", 'bold'))
        lines.append("  " + "─" * 50)
        for r in results:
            loc = f"{r['file']}:{r['line']}"
            lines.append(f"  {_c(r['name'], 'yellow'):<34} {r['arg_count']:<6} {_c(loc, 'dim')}")

    elif query_type == 'variables':
        lines.append(_c(f"  {'Name':<20} {'Assigns':<9} {'Unused':<8} {'Lines'}", 'bold'))
        lines.append("  " + "─" * 55)
        for r in results:
            unused = _c('⚠ YES', 'red') if r['unused'] else _c('no', 'dim')
            line_str = ', '.join(str(l) for l in r['lines'][:5])
            lines.append(f"  {_c(r['name'], 'cyan'):<29} {r['assign_count']:<9} {unused:<17} {_c(line_str, 'dim')}")

    elif query_type == 'loops':
        lines.append(_c(f"  {'Type':<12} {'Var':<12} {'Depth':<7} {'Break':<7} {'Cont':<7} {'Line'}", 'bold'))
        lines.append("  " + "─" * 60)
        for r in results:
            brk = '✓' if r['has_break'] else '·'
            cont = '✓' if r['has_continue'] else '·'
            var = r.get('var') or '·'
            loc = f"{r['file']}:{r['line']}"
            lines.append(f"  {_c(r['type'], 'green'):<21} {var:<12} {r['depth']:<7} {brk:<7} {cont:<7} {_c(loc, 'dim')}")

    elif query_type == 'assignments':
        lines.append(_c(f"  {'Name':<20} {'Idx':<5} {'Expr Type':<20} {'Location'}", 'bold'))
        lines.append("  " + "─" * 60)
        for r in results:
            idx = '[]' if r['indexed'] else '·'
            loc = f"{r['file']}:{r['line']}"
            lines.append(f"  {_c(r['name'], 'cyan'):<29} {idx:<5} {r['expr_type']:<20} {_c(loc, 'dim')}")

    elif query_type == 'imports':
        lines.append(_c(f"  {'Module':<30} {'Location'}", 'bold'))
        lines.append("  " + "─" * 45)
        for r in results:
            loc = f"{r['file']}:{r['line']}"
            lines.append(f"  {_c(r['module'], 'magenta'):<39} {_c(loc, 'dim')}")

    elif query_type == 'conditions':
        lines.append(_c(f"  {'Depth':<7} {'Else':<6} {'Elifs':<7} {'Nested':<8} {'Location'}", 'bold'))
        lines.append("  " + "─" * 50)
        for r in results:
            els = '✓' if r['has_else'] else '·'
            loc = f"{r['file']}:{r['line']}"
            lines.append(f"  {r['depth']:<7} {els:<6} {r['elif_count']:<7} {r['nested_ifs']:<8} {_c(loc, 'dim')}")

    elif query_type == 'complexity':
        lines.append(_c(f"  {'Function':<25} {'Stmts':<7} {'Nest':<6} {'Brnch':<7} {'Loops':<7} {'Cplx':<6} {'Rating'}", 'bold'))
        lines.append("  " + "─" * 75)
        for r in sorted(results, key=lambda x: x['complexity'], reverse=True):
            color = 'green' if r['rating'] == 'simple' else 'yellow' if r['rating'] == 'moderate' else 'red'
            loc = f"{r['file']}:{r['line']}"
            lines.append(f"  {_c(r['name'], 'cyan'):<34} {r['statements']:<7} {r['max_nesting']:<6} {r['branches']:<7} {r['loops']:<7} {r['complexity']:<6} {_c(r['rating'], color)}")

    elif query_type == 'strings':
        lines.append(_c(f"  {'Type':<8} {'Value':<50} {'Location'}", 'bold'))
        lines.append("  " + "─" * 70)
        for r in results:
            loc = f"{r['file']}:{r['line']}"
            val = r['value'][:48] + '..' if len(r['value']) > 50 else r['value']
            lines.append(f"  {r['type']:<8} {_c(val, 'green'):<50} {_c(loc, 'dim')}")

    elif query_type == 'patterns':
        lines.append(_c(f"  {'Node Type':<25} {'Depth':<7} {'Children':<10} {'Location'}", 'bold'))
        lines.append("  " + "─" * 55)
        for r in results:
            loc = f"{r['file']}:{r['line']}"
            lines.append(f"  {_c(r['node_type'], 'magenta'):<34} {r['depth']:<7} {r['children']:<10} {_c(loc, 'dim')}")

    elif query_type == 'summary':
        r = results
        lines.append(_c(f"\n  ═══ {r['file']} ═══", 'bold'))
        lines.append(f"  Nodes: {_c(r['total_nodes'], 'cyan')}  Types: {r['node_types']}  Max depth: {r['max_depth']}")
        lines.append(f"  Functions: {_c(r['functions'], 'green')}  Generators: {r['generators']}")
        if r['function_names']:
            lines.append(f"    → {', '.join(_c(n, 'cyan') for n in r['function_names'][:10])}")
        lines.append(f"  Calls: {_c(r['total_calls'], 'yellow')}  Loops: {r['loops']}  Variables: {r['variables']}")
        if r['unused_variables'] > 0:
            lines.append(f"  ⚠ Unused variables: {_c(r['unused_variables'], 'red')} ({', '.join(r['unused_names'][:5])})")
        if r['top_called']:
            top = ', '.join(f"{_c(k, 'yellow')}({v})" for k, v in list(r['top_called'].items())[:5])
            lines.append(f"  Top called: {top}")
        if r['import_modules']:
            lines.append(f"  Imports: {', '.join(_c(m, 'magenta') for m in r['import_modules'])}")
        lines.append(f"  Type breakdown: {', '.join(f'{k}={v}' for k, v in list(r['type_breakdown'].items())[:8])}")

    return '\n'.join(lines)


# ── Main ─────────────────────────────────────────────────────────────

def main():
    # Fix Windows console encoding
    if sys.platform == 'win32':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

    parser = argparse.ArgumentParser(
        prog='sauravquery',
        description='Structural code query tool for sauravcode (.srv) programs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python sauravquery.py app.srv functions              # List functions
  python sauravquery.py app.srv calls --name print     # Find print calls
  python sauravquery.py app.srv variables --unused     # Dead code detection
  python sauravquery.py app.srv loops --no-break       # Infinite loop candidates
  python sauravquery.py app.srv complexity             # Complexity report
  python sauravquery.py src/ summary --recursive       # Directory scan
  python sauravquery.py app.srv patterns --node-type Lambda  # Find lambdas
        """
    )
    parser.add_argument('path', help='Path to .srv file or directory')
    parser.add_argument('query', choices=[
        'functions', 'calls', 'variables', 'loops', 'assignments',
        'imports', 'conditions', 'complexity', 'strings', 'patterns', 'summary'
    ], help='Query type')
    parser.add_argument('--name', help='Filter by name (functions, calls, assignments)')
    parser.add_argument('--unused', action='store_true', help='Show only unused (variables)')
    parser.add_argument('--no-break', action='store_true', help='Loops without break statements')
    parser.add_argument('--depth', type=int, help='Filter by nesting depth')
    parser.add_argument('--node-type', help='AST node type filter (patterns query)')
    parser.add_argument('--has-child', help='Require child node type (patterns query)')
    parser.add_argument('--pattern', help='String content filter (strings query)')
    parser.add_argument('--recursive', '-r', action='store_true', help='Recurse into directories')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--no-color', action='store_true', help='Disable colored output')
    parser.add_argument('--count', action='store_true', help='Show only count of results')

    args = parser.parse_args()

    # Disable colors if requested
    if args.no_color or not sys.stdout.isatty():
        for k in _C:
            _C[k] = ''

    files = collect_files(args.path, args.recursive)
    if not files:
        print(f"No .srv files found at: {args.path}", file=sys.stderr)
        sys.exit(1)

    all_results = []
    errors = []

    for fpath in files:
        try:
            ast, fname = parse_file(fpath)
        except Exception as e:
            errors.append(f"{fpath}: {e}")
            continue

        if args.query == 'functions':
            all_results.extend(query_functions(ast, fname, args.name))
        elif args.query == 'calls':
            all_results.extend(query_calls(ast, fname, args.name))
        elif args.query == 'variables':
            all_results.extend(query_variables(ast, fname, args.unused))
        elif args.query == 'loops':
            all_results.extend(query_loops(ast, fname, args.no_break, args.depth))
        elif args.query == 'assignments':
            all_results.extend(query_assignments(ast, fname, args.name))
        elif args.query == 'imports':
            all_results.extend(query_imports(ast, fname))
        elif args.query == 'conditions':
            all_results.extend(query_conditions(ast, fname, args.depth))
        elif args.query == 'complexity':
            all_results.extend(query_complexity(ast, fname))
        elif args.query == 'strings':
            all_results.extend(query_strings(ast, fname, args.pattern))
        elif args.query == 'patterns':
            all_results.extend(query_patterns(ast, fname, args.node_type, args.has_child))
        elif args.query == 'summary':
            summary = query_summary(ast, fname)
            if args.json:
                all_results.append(summary)
            else:
                print(format_results(summary, 'summary'))
                continue

    if args.query != 'summary' or args.json:
        if args.count:
            count = len(all_results) if isinstance(all_results, list) else 1
            print(count)
        else:
            header = f"\n  {_c(args.query.upper(), 'bold')} — {len(all_results)} result(s) across {len(files)} file(s)\n"
            if not args.json:
                print(header)
            print(format_results(all_results, args.query, args.json))

    if errors:
        print(f"\n  ⚠ {len(errors)} file(s) had parse errors:", file=sys.stderr)
        for e in errors:
            print(f"    {e}", file=sys.stderr)


if __name__ == '__main__':
    main()
