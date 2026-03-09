#!/usr/bin/env python3
"""
sauravobf.py - Source code obfuscator for sauravcode programs.

Renames user-defined variables and function names to short, meaningless
identifiers (e.g., _a, _b, _c) to protect source code from casual reading.

Features:
  - AST-aware renaming (doesn't rename builtins, keywords, or strings)
  - Consistent renaming (same identifier always maps to the same obfuscated name)
  - Preserves program semantics (obfuscated code runs identically)
  - Optional comment stripping
  - Configurable prefix for generated names
  - Name map export (JSON) for de-obfuscation
  - Dry-run mode (show map without writing)
  - Directory batch mode

Usage:
    python sauravobf.py program.srv                      # Obfuscate to stdout
    python sauravobf.py program.srv -o out.srv           # Write to file
    python sauravobf.py program.srv --strip-comments     # Also remove comments
    python sauravobf.py program.srv --map map.json       # Export name mapping
    python sauravobf.py program.srv --prefix _v          # Use _v prefix
    python sauravobf.py program.srv --dry-run            # Show plan only
    python sauravobf.py src/ -o obf/ --recursive         # Batch obfuscate
"""

import sys
import os
import re
import json
import argparse
import string

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from saurav import tokenize, Parser, ASTNode

KEYWORDS = {
    'if', 'else', 'while', 'for', 'in', 'function', 'return', 'print',
    'true', 'false', 'and', 'or', 'not', 'import', 'from', 'as',
    'try', 'catch', 'throw', 'break', 'continue', 'yield', 'collect',
    'foreach', 'match', 'case', 'default', 'enum', 'assert',
}

BUILTINS = {
    'len', 'type_of', 'is_number', 'is_string', 'is_list', 'is_map',
    'is_function', 'is_generator', 'is_bool', 'is_none',
    'to_number', 'to_string', 'to_bool',
    'range', 'append', 'pop', 'push', 'keys', 'values', 'has_key',
    'split', 'join', 'strip', 'replace', 'upper', 'lower', 'starts_with',
    'ends_with', 'contains', 'find', 'substring', 'char_at', 'char_code',
    'from_char_code', 'trim', 'reverse', 'sort', 'sorted', 'map', 'filter',
    'reduce', 'zip', 'enumerate', 'sum', 'min', 'max', 'abs', 'round',
    'floor', 'ceil', 'sqrt', 'pow', 'log', 'sin', 'cos', 'tan',
    'random', 'random_int', 'input', 'read_file', 'write_file',
    'file_exists', 'time', 'sleep', 'exit', 'hash', 'format',
    'slice', 'index_of', 'count', 'flat', 'unique', 'insert',
    'remove', 'clear', 'copy', 'deep_copy', 'freeze', 'is_frozen',
    'now', 'today', 'timestamp', 'format_date', 'parse_date',
    'none', 'None',
}

RESERVED = KEYWORDS | BUILTINS


class NameGenerator:
    def __init__(self, prefix='_'):
        self.prefix = prefix
        self._counter = 0
        self._chars = string.ascii_lowercase

    def next(self):
        n = self._counter
        self._counter += 1
        name = ''
        while True:
            name = self._chars[n % 26] + name
            n = n // 26 - 1
            if n < 0:
                break
        return self.prefix + name

    def reset(self):
        self._counter = 0


def collect_identifiers(ast_nodes):
    names = set()
    _walk(ast_nodes, names)
    return names - RESERVED


def _walk(node, names):
    if isinstance(node, list):
        for item in node:
            _walk(item, names)
        return
    if not isinstance(node, ASTNode):
        return
    node_type = type(node).__name__

    if node_type == 'FunctionNode':
        names.add(node.name)
        if isinstance(node.params, list):
            for p in node.params:
                if isinstance(p, str):
                    names.add(p)
                elif isinstance(p, tuple) and len(p) >= 1:
                    names.add(p[0])
        _walk(node.body, names)
        return
    if node_type == 'AssignmentNode':
        if isinstance(node.name, str):
            names.add(node.name)
        _walk(node.expression, names)
        return
    if node_type == 'IndexedAssignmentNode':
        if hasattr(node, 'name') and isinstance(node.name, str):
            names.add(node.name)
        for attr in vars(node):
            if attr.startswith('_') or attr == 'line_num':
                continue
            _walk(getattr(node, attr), names)
        return
    if node_type == 'IdentifierNode':
        names.add(node.name)
        return
    if node_type in ('ForEachNode', 'ForNode'):
        if hasattr(node, 'var_name') and isinstance(node.var_name, str):
            names.add(node.var_name)
        elif hasattr(node, 'variable') and isinstance(node.variable, str):
            names.add(node.variable)
    if node_type == 'LambdaNode':
        if hasattr(node, 'params'):
            for p in (node.params if isinstance(node.params, list) else []):
                if isinstance(p, str):
                    names.add(p)
    if node_type == 'ImportNode':
        return
    for attr in sorted(vars(node)):
        if attr.startswith('_') or attr == 'line_num':
            continue
        val = getattr(node, attr)
        if isinstance(val, (ASTNode, list)):
            _walk(val, names)


def build_rename_map(identifiers, prefix='_'):
    gen = NameGenerator(prefix)
    return {name: gen.next() for name in sorted(identifiers)}


def obfuscate_line(line, rename_map, strip_comments=False):
    if not line.strip():
        return line
    stripped = line.lstrip()
    if stripped.startswith('#'):
        return None if strip_comments else line

    result = []
    i = 0
    text = line
    while i < len(text):
        if text[i] == '"':
            if i > 0 and text[i-1] == 'f' and (i < 2 or not text[i-2].isalnum()):
                j = i + 1
                while j < len(text):
                    if text[j] == '\\': j += 2; continue
                    if text[j] == '"': j += 1; break
                    j += 1
                result.append(text[i:j]); i = j; continue
            else:
                j = i + 1
                while j < len(text):
                    if text[j] == '\\': j += 2; continue
                    if text[j] == '"': j += 1; break
                    j += 1
                result.append(text[i:j]); i = j; continue
        if text[i] == '#':
            if strip_comments: break
            result.append(text[i:]); break
        if text[i].isalpha() or text[i] == '_':
            j = i
            while j < len(text) and (text[j].isalnum() or text[j] == '_'):
                j += 1
            word = text[i:j]
            result.append(rename_map.get(word, word))
            i = j; continue
        result.append(text[i]); i += 1
    return ''.join(result)


def obfuscate_source(source, rename_map, strip_comments=False):
    lines = source.split('\n')
    output = [r for line in lines if (r := obfuscate_line(line, rename_map, strip_comments)) is not None]
    if strip_comments:
        cleaned, prev_blank = [], False
        for line in output:
            is_blank = not line.strip()
            if is_blank and prev_blank: continue
            cleaned.append(line); prev_blank = is_blank
        output = cleaned
    return '\n'.join(output)


def obfuscate_fstring_expressions(source, rename_map):
    def replace_in_braces(match):
        expr = match.group(1)
        result = re.sub(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b',
                        lambda m: rename_map.get(m.group(1), m.group(1)), expr)
        return '{' + result + '}'
    def process_fstring(match):
        return re.sub(r'\{([^}]+)\}', replace_in_braces, match.group(0))
    return re.sub(r'f"(?:[^"\\]|\\.)*"', process_fstring, source)


def obfuscation_stats(source, obfuscated, rename_map):
    orig_lines = len(source.split('\n'))
    obf_lines = len(obfuscated.split('\n'))
    orig_size = len(source)
    obf_size = len(obfuscated)
    return {
        'identifiers_renamed': len(rename_map),
        'original_lines': orig_lines, 'obfuscated_lines': obf_lines,
        'lines_removed': orig_lines - obf_lines,
        'original_bytes': orig_size, 'obfuscated_bytes': obf_size,
        'size_reduction_pct': round((1 - obf_size / orig_size) * 100, 1) if orig_size > 0 else 0,
    }


def obfuscate_file(path, prefix='_', strip_comments=False):
    with open(path, 'r', encoding='utf-8') as f:
        source = f.read()
    try:
        tokens = tokenize(source)
        ast_nodes = Parser(tokens).parse()
        identifiers = collect_identifiers(ast_nodes)
    except Exception as e:
        print(f"Warning: Parse error in {path}: {e}", file=sys.stderr)
        identifiers = set()
        for line in source.split('\n'):
            ls = line.strip()
            if ls.startswith('#'): continue
            cleaned = re.sub(r'"(?:[^"\\]|\\.)*"', '', ls)
            for m in re.finditer(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', cleaned):
                w = m.group(1)
                if w not in RESERVED: identifiers.add(w)
    rename_map = build_rename_map(identifiers, prefix)
    obfuscated = obfuscate_source(source, rename_map, strip_comments)
    obfuscated = obfuscate_fstring_expressions(obfuscated, rename_map)
    stats = obfuscation_stats(source, obfuscated, rename_map)
    return obfuscated, rename_map, stats


def obfuscate_directory(dir_path, output_dir, prefix='_', strip_comments=False, recursive=False):
    results = []
    for root, dirs, files in os.walk(dir_path):
        if not recursive and root != dir_path: break
        for fname in sorted(files):
            if not fname.endswith('.srv'): continue
            src = os.path.join(root, fname)
            rel = os.path.relpath(src, dir_path)
            dst = os.path.join(output_dir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            obfuscated, rename_map, stats = obfuscate_file(src, prefix, strip_comments)
            with open(dst, 'w', encoding='utf-8') as f:
                f.write(obfuscated)
            results.append({'file': rel, 'stats': stats, 'map': rename_map})
    return results


def run_tests():
    passed = failed = 0
    errors = []
    def test(name, cond):
        nonlocal passed, failed
        if cond: passed += 1
        else: failed += 1; errors.append(name)

    # NameGenerator
    gen = NameGenerator('_')
    test('gen_first', gen.next() == '_a')
    test('gen_second', gen.next() == '_b')
    gen2 = NameGenerator('_')
    for _ in range(26): gen2.next()
    test('gen_aa', gen2.next() == '_aa')
    test('gen_ab', gen2.next() == '_ab')
    gen3 = NameGenerator('_v')
    test('gen_prefix', gen3.next() == '_va')
    gen.reset()
    test('gen_reset', gen.next() == '_a')

    test('keywords_reserved', 'if' in RESERVED)
    test('builtins_reserved', 'len' in RESERVED)
    test('user_not_reserved', 'my_var' not in RESERVED)

    # collect_identifiers
    ids1 = collect_identifiers(Parser(tokenize('x = 5\ny = x + 1\nprint y')).parse())
    test('collect_x', 'x' in ids1)
    test('collect_y', 'y' in ids1)
    test('collect_no_print', 'print' not in ids1)

    ids2 = collect_identifiers(Parser(tokenize('function greet name\n    print name\ngreet "world"')).parse())
    test('collect_func', 'greet' in ids2)
    test('collect_param', 'name' in ids2)

    # build_rename_map
    rmap = build_rename_map({'alpha', 'beta', 'gamma'}, '_')
    test('map_size', len(rmap) == 3)
    test('map_deterministic', rmap['alpha'] == '_a')
    test('map_beta', rmap['beta'] == '_b')
    test('map_gamma', rmap['gamma'] == '_c')

    # obfuscate_line
    rm = {'x': '_a', 'y': '_b', 'total': '_c'}
    test('line_simple', obfuscate_line('x = 5', rm) == '_a = 5')
    test('line_expr', obfuscate_line('y = x + 1', rm) == '_b = _a + 1')
    test('line_indent', obfuscate_line('    total = x', rm) == '    _c = _a')
    test('line_string_preserve', obfuscate_line('print "hello x"', rm) == 'print "hello x"')
    test('line_empty', obfuscate_line('', rm) == '')
    test('line_comment', obfuscate_line('# x = 5', rm) == '# x = 5')
    test('line_comment_strip', obfuscate_line('# x = 5', rm, strip_comments=True) is None)

    # obfuscate_source
    rm3 = {'x': '_a', 'y': '_b'}
    obf3 = obfuscate_source('x = 10\ny = x + 5\nprint y', rm3)
    test('source_basic', '_a = 10' in obf3)
    test('source_expr', '_b = _a + 5' in obf3)
    test('source_print', 'print _b' in obf3)

    obf4 = obfuscate_source('# header\nx = 1\n# mid\ny = 2', {'x': '_a', 'y': '_b'}, strip_comments=True)
    test('strip_no_comments', '#' not in obf4)
    test('strip_has_code', '_a = 1' in obf4)

    # Full pipeline
    src5 = 'function add a b\n    result = a + b\n    return result\nprint add 3 4'
    ids5 = collect_identifiers(Parser(tokenize(src5)).parse())
    test('pipeline_ids', all(n in ids5 for n in ['add', 'a', 'b', 'result']))
    obf5 = obfuscate_source(src5, build_rename_map(ids5))
    test('pipeline_has_function', 'function' in obf5)
    test('pipeline_has_return', 'return' in obf5)

    # Stats
    st = obfuscation_stats('x = 1\ny = 2', '_a = 1\n_b = 2', {'x': '_a', 'y': '_b'})
    test('stats_count', st['identifiers_renamed'] == 2)
    test('stats_lines', st['original_lines'] == 2)

    # Edge cases
    test('empty_source', obfuscate_source('', {}) == '')
    test('no_identifiers', obfuscate_source('print 42', {}) == 'print 42')
    test('string_only', obfuscate_source('print "hello"', {}) == 'print "hello"')
    test('string_preserve', obfuscate_line('print "name is name"', {'name': '_a'}) == 'print "name is name"')
    test('multi_id', obfuscate_line('c = a + b', {'a': '_a', 'b': '_b', 'c': '_c'}) == '_c = _a + _b')

    # For loop var
    ids9 = collect_identifiers(Parser(tokenize('for i in range 0 10\n    print i')).parse())
    test('for_var', 'i' in ids9)

    # Generator
    ids10 = collect_identifiers(Parser(tokenize('function gen limit\n    i = 0\n    while i < limit\n        yield i\n        i = i + 1')).parse())
    test('gen_ids', all(n in ids10 for n in ['gen', 'limit', 'i']))

    # File integration
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.srv', delete=False, encoding='utf-8') as f:
        f.write('x = 42\nfunction double n\n    return n * 2\nprint double x\n')
        tp = f.name
    try:
        obf, rm, st = obfuscate_file(tp)
        test('file_works', st['identifiers_renamed'] >= 3)
        test('file_semantic', 'function' in obf)
        test('file_return', 'return' in obf)
    finally:
        os.unlink(tp)

    # f-string
    obf_f = obfuscate_fstring_expressions('print f"Hello {name}, age {age}"', {'name': '_a', 'age': '_b'})
    test('fstring_rename', '{_a}' in obf_f and '{_b}' in obf_f)

    # Directory
    import tempfile as _tf, shutil
    td = _tf.mkdtemp(); od = _tf.mkdtemp()
    try:
        for fn, code in [('a.srv', 'x = 1\nprint x\n'), ('b.srv', 'y = 2\nprint y\n')]:
            with open(os.path.join(td, fn), 'w') as f: f.write(code)
        res = obfuscate_directory(td, od)
        test('dir_count', len(res) == 2)
        test('dir_files_exist', all(os.path.isfile(os.path.join(od, n)) for n in ['a.srv', 'b.srv']))
    finally:
        shutil.rmtree(td); shutil.rmtree(od)

    # Semantic correctness
    src_sem = 'x = 10\ny = x + 5\nprint y'
    ids_sem = collect_identifiers(Parser(tokenize(src_sem)).parse())
    obf_sem = obfuscate_source(src_sem, build_rename_map(ids_sem))
    import subprocess
    saurav_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'saurav.py')
    with tempfile.NamedTemporaryFile(mode='w', suffix='.srv', delete=False, encoding='utf-8') as f1:
        f1.write(src_sem); op = f1.name
    with tempfile.NamedTemporaryFile(mode='w', suffix='.srv', delete=False, encoding='utf-8') as f2:
        f2.write(obf_sem); bp = f2.name
    try:
        r1 = subprocess.run([sys.executable, saurav_path, op], capture_output=True, text=True, timeout=5)
        r2 = subprocess.run([sys.executable, saurav_path, bp], capture_output=True, text=True, timeout=5)
        test('semantic_equiv', r1.stdout.strip() == r2.stdout.strip())
    except: test('semantic_equiv', False)
    finally: os.unlink(op); os.unlink(bp)

    total = passed + failed
    print(f"\nsauravobf tests: {passed}/{total} passed")
    if errors: print(f"  FAILED: {', '.join(errors)}")
    return failed == 0


def main():
    ap = argparse.ArgumentParser(description='sauravobf -- source code obfuscator for sauravcode',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python sauravobf.py hello.srv                     Obfuscate to stdout
  python sauravobf.py hello.srv -o hello_obf.srv    Write to file
  python sauravobf.py hello.srv --strip-comments    Remove all comments
  python sauravobf.py hello.srv --map map.json      Export name mapping
  python sauravobf.py hello.srv --prefix _v         Custom prefix
  python sauravobf.py hello.srv --stats             Show statistics
  python sauravobf.py hello.srv --dry-run           Preview rename map
  python sauravobf.py src/ -o obf/ --recursive      Batch obfuscate
""")
    ap.add_argument('input', nargs='?', help='Input .srv file or directory')
    ap.add_argument('-o', '--output', help='Output file or directory')
    ap.add_argument('--prefix', default='_', help='Prefix for names (default: _)')
    ap.add_argument('--strip-comments', action='store_true', help='Remove all comments')
    ap.add_argument('--map', metavar='FILE', help='Export rename mapping to JSON')
    ap.add_argument('--stats', action='store_true', help='Show statistics')
    ap.add_argument('--dry-run', action='store_true', help='Show rename map only')
    ap.add_argument('--recursive', action='store_true', help='Process dirs recursively')
    ap.add_argument('--json', action='store_true', help='JSON output for stats/map')
    ap.add_argument('--test', action='store_true', help='Run test suite')
    args = ap.parse_args()

    if args.test:
        sys.exit(0 if run_tests() else 1)
    if not args.input:
        ap.print_help(); sys.exit(1)

    if os.path.isdir(args.input):
        if not args.output:
            print("Error: --output required for batch mode", file=sys.stderr); sys.exit(1)
        results = obfuscate_directory(args.input, args.output, args.prefix, args.strip_comments, args.recursive)
        tr = sum(r['stats']['identifiers_renamed'] for r in results)
        print(f"Obfuscated {len(results)} files, {tr} identifiers renamed.")
        for r in results:
            s = r['stats']
            print(f"  {r['file']}: {s['identifiers_renamed']} ids, {s['size_reduction_pct']}% reduction")
        return

    if not os.path.isfile(args.input):
        print(f"Error: {args.input} not found", file=sys.stderr); sys.exit(1)

    obfuscated, rename_map, stats = obfuscate_file(args.input, args.prefix, args.strip_comments)

    if args.dry_run:
        if args.json:
            print(json.dumps({'rename_map': rename_map, 'stats': stats}, indent=2))
        else:
            print(f"Rename plan for {args.input}:")
            print(f"  {stats['identifiers_renamed']} identifiers to rename\n")
            ml = max((len(k) for k in rename_map), default=0)
            for orig, obf in sorted(rename_map.items()):
                print(f"  {orig:<{ml}}  ->  {obf}")
        return

    if args.map:
        with open(args.map, 'w', encoding='utf-8') as f:
            json.dump({'source': args.input, 'prefix': args.prefix,
                       'rename_map': rename_map,
                       'reverse_map': {v: k for k, v in rename_map.items()}}, f, indent=2)
        print(f"Name mapping exported to {args.map}", file=sys.stderr)

    if args.stats:
        if args.json:
            print(json.dumps(stats, indent=2))
        else:
            print(f"Obfuscation stats for {args.input}:", file=sys.stderr)
            print(f"  Identifiers renamed: {stats['identifiers_renamed']}", file=sys.stderr)
            print(f"  Lines: {stats['original_lines']} -> {stats['obfuscated_lines']} ({stats['lines_removed']} removed)", file=sys.stderr)
            print(f"  Size: {stats['original_bytes']} -> {stats['obfuscated_bytes']} bytes ({stats['size_reduction_pct']}% reduction)", file=sys.stderr)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(obfuscated)
        print(f"Obfuscated output written to {args.output}", file=sys.stderr)
    else:
        print(obfuscated)


if __name__ == '__main__':
    main()
