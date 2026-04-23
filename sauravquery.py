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
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from saurav import tokenize, Parser, ASTNode


# ── AST Walking ─────────────────────────────────────────────────────

# Cache which attributes of each ASTNode subclass are child-bearing.
# Avoids calling sorted(vars(node)) on every node during tree walks,
# which allocates a dict + sorted list per node.  Instead we compute
# the attribute list once per type and reuse it for all instances.
_NODE_CHILD_ATTRS: dict[type, tuple[str, ...]] = {}


def _child_attrs(node):
    """Return the cached tuple of child-bearing attribute names for *node*'s type."""
    cls = type(node)
    attrs = _NODE_CHILD_ATTRS.get(cls)
    if attrs is not None:
        return attrs
    attrs = tuple(
        a for a in sorted(vars(node))
        if not a.startswith('_') and a != 'line_num'
    )
    _NODE_CHILD_ATTRS[cls] = attrs
    return attrs


def walk_ast(nodes, depth=0):
    """Yield (node, depth) for every ASTNode in the tree.

    Uses a cached per-type attribute list (via ``_child_attrs``) so we
    avoid the ``sorted(vars(node))`` overhead on every node.  For a
    1 000-node AST this eliminates ~1 000 dict + sorted-list allocations.
    """
    if isinstance(nodes, list):
        for node in nodes:
            yield from walk_ast(node, depth)
    elif isinstance(nodes, ASTNode):
        yield (nodes, depth)
        for attr in _child_attrs(nodes):
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
    for attr in _child_attrs(node):
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


def contains_any_node_types(node, type_names):
    """Check for multiple node types in a single AST walk.

    Returns a dict mapping each type_name to a bool.  This is
    significantly faster than calling ``contains_node_type`` N times,
    since it walks the tree only once instead of N times.
    """
    remaining = set(type_names)
    found = {tn: False for tn in type_names}
    for child, _ in walk_ast(node):
        if child is node:
            continue
        cname = type(child).__name__
        if cname in remaining:
            found[cname] = True
            remaining.discard(cname)
            if not remaining:
                break
    return found


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
            # Single-pass check for both ReturnNode and YieldNode
            _found = contains_any_node_types(node, ('ReturnNode', 'YieldNode'))
            has_return = _found['ReturnNode']
            has_yield = _found['YieldNode']
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
            # Single-pass check for both BreakNode and ContinueNode
            # instead of two separate tree walks.
            _found = contains_any_node_types(node, ('BreakNode', 'ContinueNode'))
            has_break = _found['BreakNode']
            has_continue = _found['ContinueNode']
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
    """Find all if/else chains.

    Uses DFS pre-order with depth tracking to count nested IfNodes in
    O(N) total — no per-node subtree walks.  Each IfNode that appears
    after another at a greater depth (before the depth drops back) is
    counted as nested under all shallower IfNode ancestors.
    """
    # Single pass: collect IfNodes in DFS order with depths
    if_entries = []  # (index, node, depth)
    for node, depth in walk_ast(ast):
        if type(node).__name__ == 'IfNode':
            if_entries.append((len(if_entries), node, depth))

    # Count nested ifs per IfNode using DFS order + depth.
    # In pre-order DFS, a node B at index j is a descendant of node A
    # at index i (i < j) iff B.depth > A.depth and no node between
    # i and j has depth <= A.depth.
    # We use a stack of (index, depth) to track active ancestors.
    nested_counts = [0] * len(if_entries)
    ancestor_stack = []  # stack of (entry_index, depth)
    for idx, _node, depth in if_entries:
        # Pop ancestors that this node is NOT nested under
        while ancestor_stack and depth <= ancestor_stack[-1][1]:
            ancestor_stack.pop()
        # This node is nested under all remaining ancestors
        for anc_idx, _anc_depth in ancestor_stack:
            nested_counts[anc_idx] += 1
        ancestor_stack.append((idx, depth))

    results = []
    for idx, node, depth in if_entries:
        if min_depth is not None and depth < min_depth:
            continue
        has_else = getattr(node, 'else_body', None) is not None
        elif_count = 0
        elifs = getattr(node, 'elif_chains', getattr(node, 'elifs', []))
        if isinstance(elifs, list):
            elif_count = len(elifs)
        line = getattr(node, 'line_num', '?')
        results.append({
            'file': filename,
            'line': line,
            'depth': depth,
            'has_else': has_else,
            'elif_count': elif_count,
            'nested_ifs': nested_counts[idx],
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
    """Compute complexity metrics per function.

    Uses a single AST walk per function to count branches, calls, and
    loops simultaneously — previously three separate ``walk_ast`` passes
    (O(3·N) → O(N) per function).
    """
    _BRANCH_TYPES = frozenset(('IfNode', 'MatchNode', 'TryCatchNode'))
    _LOOP_TYPES = frozenset(('ForNode', 'ForEachNode', 'WhileNode'))

    results = []
    for node, _ in walk_ast(ast):
        if type(node).__name__ == 'FunctionNode':
            fname = getattr(node, 'name', '?')
            body = getattr(node, 'body', [])
            stmt_count = len(body) if isinstance(body, list) else 1
            max_nest = _max_nesting(node)

            # Single-pass counting of branches, calls, and loops
            branches = 0
            calls = 0
            loops = 0
            for n, _ in walk_ast(node):
                if n is node:
                    continue
                ntype = type(n).__name__
                if ntype in _BRANCH_TYPES:
                    branches += 1
                elif ntype == 'FunctionCallNode':
                    calls += 1
                if ntype in _LOOP_TYPES:
                    loops += 1

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
    """Full structural summary.

    Collects all data in a single AST walk instead of six separate
    passes (type counting, functions, calls, loops, imports, variables).
    For a 1 000-node AST this eliminates ~5 000 redundant node visits.
    """
    type_counts = Counter()
    max_depth = 0
    func_names = []
    generators = 0
    call_targets = Counter()
    total_calls = 0
    loop_count = 0
    assigned = {}   # name -> True
    used = set()
    import_modules = []

    _LOOP_TYPES = frozenset(('ForNode', 'ForEachNode', 'WhileNode'))

    for node, depth in walk_ast(ast):
        ntype = type(node).__name__
        type_counts[ntype] += 1
        if depth > max_depth:
            max_depth = depth

        if ntype == 'FunctionNode':
            fname = getattr(node, 'name', '?')
            func_names.append(fname)
            if contains_node_type(node, 'YieldNode'):
                generators += 1
        elif ntype == 'FunctionCallNode':
            total_calls += 1
            call_targets[getattr(node, 'name', '?')] += 1
        elif ntype in _LOOP_TYPES:
            loop_count += 1
        elif ntype == 'ImportNode':
            module = getattr(node, 'module_path',
                             getattr(node, 'module',
                                     getattr(node, 'name', '?')))
            import_modules.append(module)
        elif ntype == 'AssignmentNode':
            name = getattr(node, 'name', None)
            if name:
                assigned[name] = True
        elif ntype == 'IdentifierNode':
            name = getattr(node, 'name', None)
            if name:
                used.add(name)

    unused_names = [n for n in sorted(assigned) if n not in used]

    return {
        'file': filename,
        'total_nodes': sum(type_counts.values()),
        'node_types': len(type_counts),
        'max_depth': max_depth,
        'functions': len(func_names),
        'function_names': func_names,
        'generators': generators,
        'total_calls': total_calls,
        'top_called': dict(call_targets.most_common(10)),
        'loops': loop_count,
        'variables': len(assigned),
        'unused_variables': len(unused_names),
        'unused_names': unused_names[:5],
        'imports': len(import_modules),
        'import_modules': import_modules,
        'type_breakdown': dict(type_counts.most_common(15)),
    }


# ── Formatting ───────────────────────────────────────────────────────

# Use shared terminal color helpers instead of duplicating ANSI codes.
from _termcolors import colors as _make_colors, ansi as _ansi

_colors = _make_colors()  # auto-detect TTY


def _c(text, *styles):
    """Apply ANSI styles to text via _termcolors."""
    _STYLE_MAP = {
        'bold': '1', 'dim': '2', 'red': '31', 'green': '32',
        'yellow': '33', 'blue': '34', 'magenta': '35', 'cyan': '36',
    }
    for s in styles:
        code = _STYLE_MAP.get(s)
        if code:
            text = _ansi(code, text, _colors.enabled)
    return str(text)


def _disable_colors():
    """Turn off color output."""
    _colors.enabled = False


# ── Table-driven result formatting ───────────────────────────────────
#
# Each tabular query type is described by a compact spec: column
# definitions (header, width, key-or-callable, optional color), plus
# an optional sort key and separator width.  ``_format_table`` renders
# any spec, eliminating the repetitive header/separator/loop pattern
# that was previously copy-pasted 10× in ``format_results``.

def _loc(r):
    return f"{r['file']}:{r['line']}"


def _bool_mark(val):
    return '✓' if val else '·'


# Column spec tuples: (header, width, extractor, color)
# *extractor* is a dict key string or a callable(row) → str.
# width=0 means no padding (last column).
_TABLE_SPECS = {
    'functions': {
        'cols': [
            ('Name',   25, 'name',       'cyan'),
            ('Params', 20, lambda r: ', '.join(r['params']) if r['params'] else '(none)', None),
            ('Body',    6, 'body_size',  None),
            ('Ret',     5, lambda r: _bool_mark(r['has_return']),    None),
            ('Gen',     5, lambda r: '⚡' if r['is_generator'] else '·', None),
            ('Line',    0, _loc, 'dim'),
        ],
        'sep': 80,
    },
    'calls': {
        'cols': [
            ('Function', 25, 'name',      'yellow'),
            ('Args',      6, 'arg_count', None),
            ('Location',  0, _loc,        'dim'),
        ],
        'sep': 50,
    },
    'variables': {
        'cols': [
            ('Name',    20, 'name',         'cyan'),
            ('Assigns',  9, 'assign_count', None),
            ('Unused',   8, lambda r: _c('⚠ YES', 'red') if r['unused'] else _c('no', 'dim'), None),
            ('Lines',    0, lambda r: ', '.join(str(l) for l in r['lines'][:5]), 'dim'),
        ],
        'sep': 55,
    },
    'loops': {
        'cols': [
            ('Type',  12, 'type',  'green'),
            ('Var',   12, lambda r: r.get('var') or '·', None),
            ('Depth',  7, 'depth', None),
            ('Break',  7, lambda r: _bool_mark(r['has_break']),    None),
            ('Cont',   7, lambda r: _bool_mark(r['has_continue']), None),
            ('Line',   0, _loc, 'dim'),
        ],
        'sep': 60,
    },
    'assignments': {
        'cols': [
            ('Name',      20, 'name',      'cyan'),
            ('Idx',        5, lambda r: '[]' if r['indexed'] else '·', None),
            ('Expr Type', 20, 'expr_type', None),
            ('Location',   0, _loc,        'dim'),
        ],
        'sep': 60,
    },
    'imports': {
        'cols': [
            ('Module',   30, 'module', 'magenta'),
            ('Location',  0, _loc,     'dim'),
        ],
        'sep': 45,
    },
    'conditions': {
        'cols': [
            ('Depth',    7, 'depth',      None),
            ('Else',     6, lambda r: _bool_mark(r['has_else']), None),
            ('Elifs',    7, 'elif_count', None),
            ('Nested',   8, 'nested_ifs', None),
            ('Location', 0, _loc,         'dim'),
        ],
        'sep': 50,
    },
    'complexity': {
        'cols': [
            ('Function', 25, 'name',        'cyan'),
            ('Stmts',     7, 'statements',  None),
            ('Nest',      6, 'max_nesting', None),
            ('Brnch',     7, 'branches',    None),
            ('Loops',     7, 'loops',       None),
            ('Cplx',      6, 'complexity',  None),
            ('Rating',    0, lambda r: _c(r['rating'],
                'green' if r['rating'] == 'simple'
                else 'yellow' if r['rating'] == 'moderate'
                else 'red'), None),
        ],
        'sep': 75,
        'sort': lambda x: -x['complexity'],
    },
    'strings': {
        'cols': [
            ('Type',     8, 'type', None),
            ('Value',   50, lambda r: r['value'][:48] + '..' if len(r['value']) > 50 else r['value'], 'green'),
            ('Location', 0, _loc,   'dim'),
        ],
        'sep': 70,
    },
    'patterns': {
        'cols': [
            ('Node Type', 25, 'node_type', 'magenta'),
            ('Depth',      7, 'depth',     None),
            ('Children',  10, 'children',  None),
            ('Location',   0, _loc,        'dim'),
        ],
        'sep': 55,
    },
}


def _format_table(results, spec):
    """Render *results* as a table described by *spec*."""
    cols = spec['cols']
    sort_key = spec.get('sort')
    if sort_key:
        results = sorted(results, key=sort_key)

    # Header
    hdr_parts = []
    for header, width, _ext, _clr in cols:
        hdr_parts.append(f"{header:<{width}}" if width else header)
    lines = [_c('  ' + ' '.join(hdr_parts), 'bold'),
             '  ' + '─' * spec.get('sep', 60)]

    # Rows
    for r in results:
        parts = []
        for _header, width, extractor, color in cols:
            val = extractor(r) if callable(extractor) else str(r.get(extractor, '?'))
            val_padded = f"{val:<{width}}" if width else val
            parts.append(_c(val_padded, color) if color else val_padded)
        lines.append('  ' + ' '.join(parts))

    return '\n'.join(lines)


def _format_summary(r):
    """Render the summary query type."""
    lines = [_c(f"\n  ═══ {r['file']} ═══", 'bold')]
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


def format_results(results, query_type, use_json=False):
    """Format query results for display."""
    if use_json:
        return _json.dumps(results, indent=2, default=str)

    if not results:
        return _c("No results found.", 'dim')

    if query_type == 'summary':
        return _format_summary(results)

    spec = _TABLE_SPECS.get(query_type)
    if spec:
        return _format_table(results, spec)

    # Fallback — shouldn't happen with known query types
    return _json.dumps(results, indent=2, default=str)


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
        _disable_colors()

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
