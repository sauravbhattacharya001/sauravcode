#!/usr/bin/env python3
"""Tests for sauravquery.py -- structural code query tool."""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from saurav import tokenize, Parser
from sauravquery import (
    walk_ast, children_of, contains_node_type, parse_file, collect_files,
    query_functions, query_calls, query_variables, query_loops,
    query_assignments, query_imports, query_conditions, query_complexity,
    query_strings, query_patterns, query_summary, format_results,
)

passed = 0
failed = 0

def test(name, condition):
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")

def parse(code):
    tokens = tokenize(code)
    p = Parser(tokens)
    return p.parse()



if __name__ == "__main__":
    # ── walk_ast ─────────────────────────────────────────────────────────

    ast1 = parse('x = 1\ny = 2\nprint x')
    nodes1 = list(walk_ast(ast1))
    test("walk_ast returns nodes", len(nodes1) > 0)
    test("walk_ast includes depth", all(isinstance(d, int) for _, d in nodes1))
    test("walk_ast top-level depth 0", nodes1[0][1] == 0)

    # ── children_of ──────────────────────────────────────────────────────

    ast2 = parse('x = 1 + 2')
    assign_node = ast2[0]
    kids = children_of(assign_node)
    test("children_of returns list", isinstance(kids, list))
    test("children_of finds expression child", len(kids) >= 1)

    # ── contains_node_type ───────────────────────────────────────────────

    ast3 = parse('x = 1 + 2')
    test("contains BinaryOpNode", contains_node_type(ast3[0], 'BinaryOpNode'))
    test("does not contain ForNode", not contains_node_type(ast3[0], 'ForNode'))

    # ── query_functions ──────────────────────────────────────────────────

    code_fn = '''function add a b
        return a + b

    function greet name
        print name
    '''
    ast_fn = parse(code_fn)
    fns = query_functions(ast_fn, 'test.srv')
    test("finds 2 functions", len(fns) == 2)
    test("function name is add", fns[0]['name'] == 'add')
    test("function params", fns[0]['params'] == ['a', 'b'])
    test("add has return", fns[0]['has_return'] is True)
    test("greet no return", fns[1]['has_return'] is False)

    fns_filtered = query_functions(ast_fn, 'test.srv', name_filter='add')
    test("name filter works", len(fns_filtered) == 1)
    test("name filter correct", fns_filtered[0]['name'] == 'add')

    # ── query_calls ──────────────────────────────────────────────────────

    code_calls = '''print "hello"
    print "world"
    '''
    ast_calls = parse(code_calls)
    calls = query_calls(ast_calls, 'test.srv')
    # print is a PrintNode, not FunctionCallNode
    test("calls returns list", isinstance(calls, list))

    # Test with actual function calls in expression context
    code_calls2 = '''function foo x
        return x

    y = foo(5)
    z = foo(10)
    '''
    ast_calls2 = parse(code_calls2)
    calls2 = query_calls(ast_calls2, 'test.srv')
    test("finds function calls", len(calls2) >= 2)
    calls_filtered = query_calls(ast_calls2, 'test.srv', name_filter='foo')
    test("call name filter works", all(c['name'] == 'foo' for c in calls_filtered))

    # ── query_variables ──────────────────────────────────────────────────

    code_vars = '''x = 1
    y = 2
    z = 3
    print x
    print y
    '''
    ast_vars = parse(code_vars)
    vars_all = query_variables(ast_vars, 'test.srv')
    test("finds all variables", len(vars_all) == 3)
    test("variable names correct", set(v['name'] for v in vars_all) == {'x', 'y', 'z'})

    vars_unused = query_variables(ast_vars, 'test.srv', unused_only=True)
    test("finds unused variable z", len(vars_unused) == 1)
    test("unused is z", vars_unused[0]['name'] == 'z')
    test("unused flag set", vars_unused[0]['unused'] is True)

    # ── query_loops ──────────────────────────────────────────────────────

    code_loops = '''for i in range(10)
        print i

    x = 0
    while x < 5
        x = x + 1
    '''
    ast_loops = parse(code_loops)
    loops = query_loops(ast_loops, 'test.srv')
    test("finds 2 loops", len(loops) == 2)
    test("first is ForEach", loops[0]['type'] == 'ForEach')
    test("second is While", loops[1]['type'] == 'While')
    test("no break in for", loops[0]['has_break'] is False)

    loops_nobreak = query_loops(ast_loops, 'test.srv', no_break=True)
    test("no-break filter keeps all (none have break)", len(loops_nobreak) == 2)

    # ── query_assignments ───────────────────────────────────────────────

    code_assign = '''x = 1
    y = "hello"
    z = 1 + 2
    '''
    ast_assign = parse(code_assign)
    assigns = query_assignments(ast_assign, 'test.srv')
    test("finds 3 assignments", len(assigns) == 3)
    test("assignment name", assigns[0]['name'] == 'x')
    test("not indexed", assigns[0]['indexed'] is False)

    assigns_filtered = query_assignments(ast_assign, 'test.srv', name_filter='y')
    test("assignment name filter", len(assigns_filtered) == 1)

    # ── query_imports ────────────────────────────────────────────────────

    code_import = '''import "import_utils"
    '''
    ast_import = parse(code_import)
    imports = query_imports(ast_import, 'test.srv')
    test("finds import", len(imports) == 1)
    test("import module name", imports[0]['module'] == 'import_utils')

    # ── query_conditions ─────────────────────────────────────────────────

    code_cond = '''x = 5
    if x > 3
        print "big"
    else
        print "small"
    '''
    ast_cond = parse(code_cond)
    conds = query_conditions(ast_cond, 'test.srv')
    test("finds 1 condition", len(conds) == 1)
    test("condition has else", conds[0]['has_else'] is True)

    # ── query_complexity ─────────────────────────────────────────────────

    code_complex = '''function simple x
        return x

    function complex_fn x
        if x > 0
            for i in range(10)
                if i > 2
                    print i
        return x
    '''
    ast_complex = parse(code_complex)
    complexity = query_complexity(ast_complex, 'test.srv')
    test("finds 2 functions for complexity", len(complexity) == 2)
    test("simple function is simple", any(c['rating'] == 'simple' and c['name'] == 'simple' for c in complexity))
    test("complex has higher complexity", 
         next(c for c in complexity if c['name'] == 'complex_fn')['complexity'] > 
         next(c for c in complexity if c['name'] == 'simple')['complexity'])

    # ── query_strings ────────────────────────────────────────────────────

    code_str = '''print "hello world"
    print "goodbye"
    x = "test string"
    '''
    ast_str = parse(code_str)
    strings = query_strings(ast_str, 'test.srv')
    test("finds strings", len(strings) >= 3)

    strings_filtered = query_strings(ast_str, 'test.srv', pattern='hello')
    test("string pattern filter", len(strings_filtered) >= 1)
    test("filtered string contains hello", any('hello' in s['value'] for s in strings_filtered))

    # ── query_patterns ───────────────────────────────────────────────────

    code_pat = '''x = 1 + 2
    y = 3 * 4
    '''
    ast_pat = parse(code_pat)
    patterns = query_patterns(ast_pat, 'test.srv', node_type='BinaryOp')
    test("finds BinaryOp nodes", len(patterns) >= 2)
    test("node type matches", all('BinaryOp' in p['node_type'] for p in patterns))

    patterns_with_child = query_patterns(ast_pat, 'test.srv', node_type='Assignment', has_child='BinaryOpNode')
    test("pattern with has_child filter", len(patterns_with_child) >= 1)

    # ── query_summary ────────────────────────────────────────────────────

    summary = query_summary(ast_fn, 'test.srv')
    test("summary has file", summary['file'] == 'test.srv')
    test("summary has total_nodes", summary['total_nodes'] > 0)
    test("summary has functions count", summary['functions'] == 2)
    test("summary has function_names", 'add' in summary['function_names'])
    test("summary has variables", isinstance(summary['variables'], int))
    test("summary has type_breakdown", isinstance(summary['type_breakdown'], dict))

    # ── format_results ───────────────────────────────────────────────────

    out_json = format_results(fns, 'functions', use_json=True)
    test("JSON output is valid", isinstance(json.loads(out_json), list))

    out_text = format_results(fns, 'functions', use_json=False)
    test("text output has content", len(out_text) > 0)
    test("text output contains function name", 'add' in out_text)

    out_empty = format_results([], 'functions', use_json=False)
    test("empty results handled", 'No results' in out_empty)

    # Test summary format
    out_summary = format_results(summary, 'summary')
    test("summary format has content", len(out_summary) > 0)

    # Test all format types produce output
    for qtype in ['calls', 'variables', 'loops', 'assignments', 'imports', 'conditions', 'complexity', 'strings', 'patterns']:
        out = format_results([{'file': 'x.srv', 'name': 'test', 'line': 1, 'depth': 0,
                               'params': [], 'body_size': 1, 'has_return': False, 'is_generator': False,
                               'arg_count': 0, 'assign_count': 1, 'unused': False, 'lines': [1],
                               'type': 'For', 'var': 'i', 'has_break': False, 'has_continue': False,
                               'indexed': False, 'expr_type': 'NumberNode', 'module': 'test',
                               'has_else': True, 'elif_count': 0, 'nested_ifs': 0,
                               'statements': 5, 'max_nesting': 2, 'branches': 1, 'loops': 1,
                               'calls': 2, 'complexity': 3, 'rating': 'simple',
                               'value': 'hello', 'node_type': 'TestNode', 'children': 2}],
                              qtype, use_json=False)
        test(f"format_{qtype} produces output", len(out) > 0)

    # ── collect_files ────────────────────────────────────────────────────

    # Test with current directory
    test_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    files = collect_files(test_dir)
    test("collect_files finds .srv files", len(files) > 0)
    test("collect_files returns .srv only", all(f.endswith('.srv') for f in files))

    # Test with single file
    single = collect_files(os.path.join(test_dir, 'hello.srv'))
    test("collect_files single file", len(single) == 1)

    # Test with non-existent
    none_files = collect_files('/nonexistent_path_xyz')
    test("collect_files non-existent returns empty", len(none_files) == 0)

    # ── Edge cases ───────────────────────────────────────────────────────

    empty_ast = parse('')
    test("empty program functions", query_functions(empty_ast, 'e.srv') == [])
    test("empty program calls", query_calls(empty_ast, 'e.srv') == [])
    test("empty program variables", query_variables(empty_ast, 'e.srv') == [])
    test("empty program loops", query_loops(empty_ast, 'e.srv') == [])
    test("empty program summary nodes", query_summary(empty_ast, 'e.srv')['total_nodes'] == 0)

    # ── Results ──────────────────────────────────────────────────────────

    print(f"\n{'='*50}")
    print(f"  sauravquery tests: {passed} passed, {failed} failed")
    print(f"{'='*50}")
    sys.exit(1 if failed else 0)
