#!/usr/bin/env python3
"""
sauravmin - Source code minifier for the sauravcode language.

Compresses .srv source files for distribution by stripping comments,
collapsing blank lines, removing trailing whitespace, and optionally
shortening user-defined identifiers.

Levels:
  0  Strip comments and trailing whitespace only
  1  Level 0 + collapse consecutive blank lines to one
  2  Level 1 + collapse all blank lines (densest readable form)
  3  Level 2 + shorten user identifiers (smallest output)

Usage:
    python sauravmin.py program.srv                 # minify to stdout (level 2)
    python sauravmin.py program.srv -o out.srv      # write to file
    python sauravmin.py program.srv --level 3       # aggressive: rename ids
    python sauravmin.py program.srv --level 0       # strip comments only
    python sauravmin.py program.srv --stats         # show size reduction stats
    python sauravmin.py program.srv --map map.json  # export identifier map (level 3)
    python sauravmin.py src/ -o dist/ --recursive   # batch minify directory
    python sauravmin.py program.srv --dry-run       # show stats without output
"""

import argparse
import json
import os
import re
import sys
import string
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from saurav import tokenize

__version__ = "1.0.0"

KEYWORDS = {
    'if', 'else', 'while', 'for', 'in', 'function', 'return', 'print',
    'true', 'false', 'and', 'or', 'not', 'import', 'from', 'as',
    'try', 'catch', 'throw', 'break', 'continue', 'yield', 'collect',
    'foreach', 'match', 'case', 'default', 'enum', 'assert',
    'class', 'self', 'none', 'None', 'lambda',
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
    'print_error', 'error',
}

RESERVED = KEYWORDS | BUILTINS


def _id_generator():
    """Generate short identifiers: _a, _b, ..., _z, _aa, _ab, ..."""
    n = 0
    while True:
        name = ""
        val = n
        while True:
            name = string.ascii_lowercase[val % 26] + name
            val = val // 26 - 1
            if val < 0:
                break
        candidate = f"_{name}"
        if candidate not in RESERVED:
            yield candidate
        n += 1


def _collect_identifiers(source):
    """Extract user-defined identifiers from source using the tokenizer."""
    try:
        tokens = tokenize(source)
    except Exception:
        return {}
    counts = {}
    for tok in tokens:
        typ = tok[0]
        val = tok[1]
        if typ == 'IDENT' and val not in RESERVED:
            counts[val] = counts.get(val, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))


def _build_rename_map(identifiers):
    """Build a mapping from original identifiers to short names."""
    gen = _id_generator()
    return {name: next(gen) for name in identifiers}


def _scan_tokens(source):
    """Yield (kind, text, start, end) for each segment of source.

    Kinds: 'string', 'comment', 'ident', 'other'.
    Correctly handles escape sequences inside strings and #-comments.
    """
    _IDENT_RE = re.compile(r'[a-zA-Z_][a-zA-Z0-9_]*')
    i = 0
    n = len(source)
    while i < n:
        ch = source[i]
        if ch == '#':
            start = i
            while i < n and source[i] != '\n':
                i += 1
            yield ('comment', source[start:i], start, i)
            continue
        if ch in ('"', "'"):
            quote = ch
            start = i
            i += 1
            while i < n:
                c = source[i]
                if c == '\\' and i + 1 < n:
                    i += 2
                    continue
                if c == quote:
                    i += 1
                    break
                i += 1
            yield ('string', source[start:i], start, i)
            continue
        if ch.isalpha() or ch == '_':
            m = _IDENT_RE.match(source, i)
            if m:
                yield ('ident', m.group(0), i, m.end())
                i = m.end()
                continue
        yield ('other', ch, i, i + 1)
        i += 1


def _apply_renames(source, rename_map):
    """Replace identifiers in source, preserving strings and comments."""
    if not rename_map:
        return source
    result = []
    for kind, text, _start, _end in _scan_tokens(source):
        if kind == 'ident':
            result.append(rename_map.get(text, text))
        else:
            result.append(text)
    return ''.join(result)


def _strip_comments(line):
    """Remove comments from a line, preserving strings."""
    for kind, _text, start, _end in _scan_tokens(line):
        if kind == 'comment':
            return line[:start].rstrip()
    return line


def minify(source, level=2):
    """Minify sauravcode source at the given compression level.

    Returns (minified_source, stats_dict, rename_map).
    """
    original_size = len(source)
    original_lines = source.count('\n') + (1 if source and not source.endswith('\n') else 0)
    rename_map = {}
    lines = source.split('\n')

    processed = []
    for line in lines:
        stripped = _strip_comments(line)
        stripped = stripped.rstrip()
        processed.append(stripped)

    if level >= 1:
        collapsed = []
        prev_blank = False
        for line in processed:
            is_blank = (line.strip() == '')
            if is_blank and prev_blank:
                continue
            collapsed.append(line)
            prev_blank = is_blank
        processed = collapsed

    if level >= 2:
        processed = [line for line in processed if line.strip() != '']

    result = '\n'.join(processed)
    if result and not result.endswith('\n'):
        result += '\n'

    if level >= 3:
        identifiers = _collect_identifiers(source)
        rename_map = _build_rename_map(identifiers)
        result = _apply_renames(result, rename_map)

    final_size = len(result)
    final_lines = result.count('\n')
    stats = {
        'original_bytes': original_size,
        'minified_bytes': final_size,
        'saved_bytes': original_size - final_size,
        'compression_pct': round((1 - final_size / original_size) * 100, 1) if original_size > 0 else 0,
        'original_lines': original_lines,
        'minified_lines': final_lines,
        'removed_lines': original_lines - final_lines,
        'level': level,
        'identifiers_renamed': len(rename_map),
    }
    return result, stats, rename_map


def minify_file(path, output=None, level=2, show_stats=False,
                dry_run=False, map_path=None):
    with open(path, 'r', encoding='utf-8') as f:
        source = f.read()
    result, stats, rename_map = minify(source, level=level)
    stats['file'] = str(path)
    if show_stats or dry_run:
        _print_stats(stats)
    if dry_run:
        return stats
    if output:
        os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
        with open(output, 'w', encoding='utf-8') as f:
            f.write(result)
    else:
        sys.stdout.write(result)
    if map_path and rename_map:
        with open(map_path, 'w', encoding='utf-8') as f:
            json.dump(rename_map, f, indent=2)
    return stats


def minify_directory(src_dir, out_dir=None, level=2, recursive=False,
                     show_stats=False, dry_run=False):
    src_path = Path(src_dir)
    glob = src_path.rglob('*.srv') if recursive else src_path.glob('*.srv')
    all_stats = []
    for file_path in sorted(glob):
        if out_dir:
            rel = file_path.relative_to(src_path)
            out_path = Path(out_dir) / rel
        else:
            out_path = None
        stats = minify_file(
            str(file_path),
            output=str(out_path) if out_path else None,
            level=level, show_stats=show_stats, dry_run=dry_run,
        )
        all_stats.append(stats)
    if all_stats and (show_stats or dry_run):
        _print_summary(all_stats)
    return all_stats


def _print_stats(stats):
    print(f"  {stats['file']}:", file=sys.stderr)
    print(f"    {stats['original_bytes']} -> {stats['minified_bytes']} bytes "
          f"({stats['compression_pct']}% reduction)", file=sys.stderr)
    print(f"    {stats['original_lines']} -> {stats['minified_lines']} lines "
          f"({stats['removed_lines']} removed)", file=sys.stderr)
    if stats['identifiers_renamed']:
        print(f"    {stats['identifiers_renamed']} identifiers renamed", file=sys.stderr)


def _print_summary(all_stats):
    total_orig = sum(s['original_bytes'] for s in all_stats)
    total_min = sum(s['minified_bytes'] for s in all_stats)
    total_saved = total_orig - total_min
    pct = round((1 - total_min / total_orig) * 100, 1) if total_orig > 0 else 0
    print(f"\n  Summary: {len(all_stats)} files, "
          f"{total_orig} -> {total_min} bytes ({pct}% reduction, "
          f"{total_saved} bytes saved)", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        prog='sauravmin', description='Minify sauravcode (.srv) source files.')
    parser.add_argument('input', help='Source file or directory')
    parser.add_argument('-o', '--output', help='Output file or directory')
    parser.add_argument('--level', type=int, default=2, choices=[0, 1, 2, 3],
                        help='Minification level (0-3, default: 2)')
    parser.add_argument('--stats', action='store_true', help='Show compression statistics')
    parser.add_argument('--dry-run', action='store_true', help='Show stats without output')
    parser.add_argument('--map', help='Export identifier rename map to JSON (level 3)')
    parser.add_argument('--recursive', '-r', action='store_true', help='Process dirs recursively')
    parser.add_argument('--version', action='version', version=f'sauravmin {__version__}')
    args = parser.parse_args()
    if os.path.isdir(args.input):
        minify_directory(args.input, out_dir=args.output, level=args.level,
                         recursive=args.recursive,
                         show_stats=args.stats or args.dry_run, dry_run=args.dry_run)
    elif os.path.isfile(args.input):
        minify_file(args.input, output=args.output, level=args.level,
                    show_stats=args.stats or args.dry_run, dry_run=args.dry_run,
                    map_path=args.map)
    else:
        print(f"Error: '{args.input}' not found", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
