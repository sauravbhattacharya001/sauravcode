#!/usr/bin/env python3
"""sauravbundle -- Bundle multiple .srv files into a single distributable file.

Resolves all import statements recursively, performs topological sorting,
and concatenates modules into one self-contained .srv file with no imports.

Usage:
    python sauravbundle.py <entry.srv>                       # Bundle to stdout
    python sauravbundle.py <entry.srv> -o bundle.srv         # Bundle to file
    python sauravbundle.py <entry.srv> --minify              # Strip comments/blanks
    python sauravbundle.py <entry.srv> --tree                # Show dependency tree
    python sauravbundle.py <entry.srv> --dry-run             # Show what would be bundled
    python sauravbundle.py <entry.srv> --exclude utils       # Exclude a module
    python sauravbundle.py <entry.srv> --banner "v1.0"       # Add header banner
    python sauravbundle.py <entry.srv> --stats               # Show bundle statistics
"""

import os
import re
import sys
import json
import argparse
from collections import OrderedDict

__version__ = "1.0.0"

# Matches: import "module_name" or import module_name
IMPORT_RE = re.compile(r'^\s*import\s+(?:"([^"]+)"|(\S+))\s*$')

# Matches comment lines
COMMENT_RE = re.compile(r'^\s*#')


def resolve_module_path(module_name, search_dirs):
    """Resolve a module name to a file path.

    Searches in order: exact path, with .srv extension, in search directories.
    Returns the resolved path or None.
    """
    candidates = []
    name = module_name.strip('"').strip("'")

    # Try exact and with .srv extension
    for base_dir in search_dirs:
        for suffix in ['', '.srv']:
            candidate = os.path.join(base_dir, name + suffix)
            candidates.append(candidate)

    for c in candidates:
        if os.path.isfile(c):
            return os.path.normpath(c)
    return None


def extract_imports(filepath):
    """Extract import statements from a .srv file.

    Returns list of (line_number, module_name) tuples.
    """
    imports = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f, 1):
                m = IMPORT_RE.match(line)
                if m:
                    module_name = m.group(1) or m.group(2)
                    imports.append((i, module_name))
    except (IOError, OSError):
        pass
    return imports


def read_file_lines(filepath):
    """Read file and return lines."""
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.readlines()


def strip_imports(lines):
    """Remove import lines from source, return filtered lines."""
    result = []
    for line in lines:
        if not IMPORT_RE.match(line):
            result.append(line)
    return result


def minify_lines(lines):
    """Remove comments and blank lines."""
    result = []
    for line in lines:
        stripped = line.rstrip()
        if stripped and not COMMENT_RE.match(stripped):
            result.append(line)
    return result


def collect_modules(entry_path, search_dirs, exclude=None):
    """Recursively collect all modules starting from entry file.

    Returns OrderedDict of {normalized_path: module_name} in topological order
    (dependencies before dependents), and a dict of unresolved imports.
    """
    exclude = set(exclude or [])
    visited = set()
    order = []
    unresolved = {}

    def visit(filepath, from_file=None):
        norm = os.path.normpath(filepath)
        if norm in visited:
            return
        visited.add(norm)

        imports = extract_imports(filepath)
        file_dir = os.path.dirname(os.path.abspath(filepath))
        dirs = [file_dir] + search_dirs

        for line_no, mod_name in imports:
            if mod_name in exclude:
                continue
            resolved = resolve_module_path(mod_name, dirs)
            if resolved is None:
                key = f"{filepath}:{line_no}"
                unresolved[key] = mod_name
                continue
            visit(resolved, filepath)

        order.append(norm)

    visit(entry_path)

    result = OrderedDict()
    for path in order:
        basename = os.path.splitext(os.path.basename(path))[0]
        result[path] = basename
    return result, unresolved


def build_dependency_tree(entry_path, search_dirs, exclude=None, prefix="", visited=None):
    """Build a text-based dependency tree string."""
    exclude = set(exclude or [])
    if visited is None:
        visited = set()

    norm = os.path.normpath(entry_path)
    basename = os.path.basename(norm)
    circular = norm in visited

    lines = [f"{prefix}{basename}" + (" (circular)" if circular else "")]
    if circular:
        return lines

    visited.add(norm)
    imports = extract_imports(entry_path)
    file_dir = os.path.dirname(os.path.abspath(entry_path))
    dirs = [file_dir] + search_dirs

    children = []
    for _, mod_name in imports:
        if mod_name in exclude:
            continue
        resolved = resolve_module_path(mod_name, dirs)
        if resolved:
            children.append(resolved)
        else:
            children.append(None)

    for i, (imp, child_path) in enumerate(zip(
            [m for _, m in imports if m not in exclude], children)):
        is_last = (i == len(children) - 1)
        connector = "└── " if is_last else "├── "
        extension = "    " if is_last else "│   "

        if child_path is None:
            lines.append(f"{prefix}{connector}{imp} (unresolved)")
        else:
            subtree = build_dependency_tree(
                child_path, search_dirs, exclude,
                prefix + extension, visited.copy())
            # Replace first line's prefix
            subtree[0] = f"{prefix}{connector}" + os.path.basename(child_path)
            lines.extend(subtree)

    return lines


def bundle(entry_path, search_dirs=None, exclude=None, do_minify=False,
           banner=None):
    """Bundle entry file and all its dependencies into a single string.

    Returns (bundled_source, stats_dict).
    """
    search_dirs = search_dirs or []
    exclude = exclude or []

    entry_path = os.path.normpath(entry_path)
    if not os.path.isfile(entry_path):
        raise FileNotFoundError(f"Entry file not found: {entry_path}")

    modules, unresolved = collect_modules(entry_path, search_dirs, exclude)

    parts = []
    total_lines = 0
    total_imports_removed = 0
    module_stats = []

    for filepath, mod_name in modules.items():
        lines = read_file_lines(filepath)
        original_count = len(lines)

        # Strip import lines
        filtered = strip_imports(lines)
        imports_removed = original_count - len(filtered)
        total_imports_removed += imports_removed

        if do_minify:
            filtered = minify_lines(filtered)

        # Add module separator (except for minified output with single module)
        is_entry = (filepath == entry_path)
        if len(modules) > 1:
            separator = f"# ── Module: {mod_name} " + "─" * max(0, 50 - len(mod_name))
            if is_entry:
                separator = f"# ── Entry: {mod_name} " + "─" * max(0, 50 - len(mod_name))
            parts.append(separator + "\n")

        content = ''.join(filtered)
        # Ensure trailing newline
        if content and not content.endswith('\n'):
            content += '\n'
        parts.append(content)
        parts.append('\n')

        total_lines += len(filtered)
        module_stats.append({
            'module': mod_name,
            'path': filepath,
            'original_lines': original_count,
            'bundled_lines': len(filtered),
            'imports_removed': imports_removed,
            'is_entry': is_entry
        })

    result = ''.join(parts).rstrip('\n') + '\n'

    # Prepend banner if specified
    if banner:
        banner_text = f"# {banner}\n# Bundled by sauravbundle v{__version__}\n\n"
        result = banner_text + result

    stats = {
        'entry': entry_path,
        'module_count': len(modules),
        'total_lines': total_lines,
        'imports_removed': total_imports_removed,
        'unresolved': unresolved,
        'modules': module_stats,
        'minified': do_minify,
        'banner': banner
    }

    return result, stats


def format_stats(stats):
    """Format bundle statistics as human-readable text."""
    lines = []
    lines.append("Bundle Statistics")
    lines.append("=" * 40)
    lines.append(f"Entry:            {stats['entry']}")
    lines.append(f"Modules bundled:  {stats['module_count']}")
    lines.append(f"Total lines:      {stats['total_lines']}")
    lines.append(f"Imports removed:  {stats['imports_removed']}")
    lines.append(f"Minified:         {'yes' if stats['minified'] else 'no'}")
    if stats['banner']:
        lines.append(f"Banner:           {stats['banner']}")
    lines.append("")

    if stats['modules']:
        lines.append("Modules:")
        lines.append("-" * 40)
        for m in stats['modules']:
            marker = " (entry)" if m['is_entry'] else ""
            lines.append(f"  {m['module']}{marker}: {m['bundled_lines']} lines"
                         f" ({m['imports_removed']} imports removed)")

    if stats['unresolved']:
        lines.append("")
        lines.append("Unresolved imports:")
        lines.append("-" * 40)
        for loc, name in stats['unresolved'].items():
            lines.append(f"  {loc}: {name}")

    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Bundle SauravCode .srv files into a single file.')
    parser.add_argument('entry', help='Entry .srv file')
    parser.add_argument('-o', '--output', help='Output file (default: stdout)')
    parser.add_argument('-I', '--include-dir', action='append', default=[],
                        help='Additional search directories for imports')
    parser.add_argument('--exclude', action='append', default=[],
                        help='Module names to exclude from bundling')
    parser.add_argument('--minify', action='store_true',
                        help='Strip comments and blank lines')
    parser.add_argument('--tree', action='store_true',
                        help='Show dependency tree and exit')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be bundled without bundling')
    parser.add_argument('--banner', type=str, default=None,
                        help='Add a header banner to the bundle')
    parser.add_argument('--stats', action='store_true',
                        help='Show bundle statistics')
    parser.add_argument('--json', action='store_true',
                        help='Output statistics as JSON')
    parser.add_argument('--version', action='version',
                        version=f'sauravbundle {__version__}')

    args = parser.parse_args(argv)

    entry = args.entry
    if not os.path.isfile(entry):
        print(f"Error: file not found: {entry}", file=sys.stderr)
        return 1

    search_dirs = [os.path.dirname(os.path.abspath(entry))] + args.include_dir

    # Tree mode
    if args.tree:
        tree_lines = build_dependency_tree(entry, search_dirs, args.exclude)
        print('\n'.join(tree_lines))
        return 0

    # Dry-run mode
    if args.dry_run:
        modules, unresolved = collect_modules(entry, search_dirs, args.exclude)
        print("Would bundle the following modules:")
        for path, name in modules.items():
            lines = read_file_lines(path)
            print(f"  {name}: {path} ({len(lines)} lines)")
        if unresolved:
            print("\nUnresolved imports:")
            for loc, name in unresolved.items():
                print(f"  {loc}: {name}")
        return 0

    # Bundle
    try:
        result, stats = bundle(entry, search_dirs, args.exclude,
                               args.minify, args.banner)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Output
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(result)
        print(f"Bundled {stats['module_count']} module(s) → {args.output}"
              f" ({stats['total_lines']} lines)")
    else:
        if not args.stats and not args.json:
            sys.stdout.write(result)

    # Stats
    if args.stats:
        print(format_stats(stats))
    elif args.json:
        print(json.dumps(stats, indent=2))

    return 0


if __name__ == '__main__':
    sys.exit(main())
