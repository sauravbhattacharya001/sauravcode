#!/usr/bin/env python3
"""sauravdeps -- Dependency analyzer for SauravCode (.srv) projects.

Scans .srv files for import statements, builds a dependency graph,
detects circular dependencies, computes import statistics, and
can output DOT (Graphviz), JSON, or a human-readable text report.

Usage:
    python sauravdeps.py <path>                     # Analyze file or directory
    python sauravdeps.py <path> --format dot         # Output Graphviz DOT
    python sauravdeps.py <path> --format json        # Output JSON graph
    python sauravdeps.py <path> --cycles             # Only show circular deps
    python sauravdeps.py <path> --stats              # Show import statistics
    python sauravdeps.py <path> --tree               # Show import tree per file
    python sauravdeps.py <path> --roots              # Show root modules (nothing imports them)
    python sauravdeps.py <path> --leaves             # Show leaf modules (import nothing)
    python sauravdeps.py <path> --depth              # Show max dependency depth per module
    python sauravdeps.py <path> --unused <file.srv>  # Find modules not reachable from file
"""

import os
import re
import sys
import json
import argparse
from collections import defaultdict, deque

__version__ = "1.0.0"

# Regex to match import statements in .srv files
# Matches: import "module_name"  or  import module_name
_IMPORT_RE = re.compile(
    r'^\s*import\s+(?:"([^"]+)"|([a-zA-Z_]\w*))\s*(?:#.*)?$',
    re.MULTILINE,
)


def extract_imports(filepath):
    """Extract import module names from a .srv file.

    Returns a list of module path strings (without .srv extension).
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        return []

    imports = []
    for m in _IMPORT_RE.finditer(content):
        # Group 1 = quoted string, group 2 = bare identifier
        module = m.group(1) or m.group(2)
        imports.append(module)
    return imports


def resolve_module(module_name, source_dir, search_dirs):
    """Resolve a module name to an absolute .srv file path.

    Searches source_dir first, then each directory in search_dirs.
    Returns the absolute path if found, else None.
    """
    candidates = [source_dir] + list(search_dirs)
    for d in candidates:
        path = os.path.join(d, module_name + ".srv")
        if os.path.isfile(path):
            return os.path.abspath(path)
        # Also try without adding .srv if module_name already has it
        if module_name.endswith(".srv"):
            path = os.path.join(d, module_name)
            if os.path.isfile(path):
                return os.path.abspath(path)
    return None


def discover_srv_files(path):
    """Discover all .srv files under a path (file or directory)."""
    path = os.path.abspath(path)
    if os.path.isfile(path):
        if path.endswith(".srv"):
            return [path]
        return []
    results = []
    for root, _dirs, files in os.walk(path):
        for f in files:
            if f.endswith(".srv"):
                results.append(os.path.abspath(os.path.join(root, f)))
    results.sort()
    return results


def build_graph(srv_files, search_dirs=None):
    """Build the dependency graph.

    Returns:
        graph: dict mapping absolute filepath -> list of absolute filepaths it imports
        unresolved: dict mapping absolute filepath -> list of unresolved module names
        all_files: set of all known absolute filepaths
    """
    if search_dirs is None:
        search_dirs = []

    # Collect all directories containing .srv files as implicit search dirs
    implicit_dirs = set()
    for f in srv_files:
        implicit_dirs.add(os.path.dirname(f))

    graph = {}
    unresolved = defaultdict(list)
    all_files = set(srv_files)

    for filepath in srv_files:
        imports = extract_imports(filepath)
        source_dir = os.path.dirname(filepath)
        deps = []
        for module in imports:
            resolved = resolve_module(module, source_dir, list(implicit_dirs) + search_dirs)
            if resolved:
                deps.append(resolved)
                all_files.add(resolved)
            else:
                unresolved[filepath].append(module)
        graph[filepath] = deps

    return graph, dict(unresolved), all_files


def find_cycles(graph):
    """Find all cycles in the dependency graph using DFS.

    Returns a list of cycles, where each cycle is a list of filepaths.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color = defaultdict(int)
    cycles = []
    path = []

    def dfs(node):
        color[node] = GRAY
        path.append(node)
        for dep in graph.get(node, []):
            if color[dep] == GRAY:
                # Found a cycle — extract it
                idx = path.index(dep)
                cycles.append(list(path[idx:]))
            elif color[dep] == WHITE:
                dfs(dep)
        path.pop()
        color[node] = BLACK

    for node in graph:
        if color[node] == WHITE:
            dfs(node)

    return cycles


def compute_depth(graph):
    """Compute the maximum dependency depth for each module.

    A module with no imports has depth 0.
    Returns a dict mapping filepath -> depth.
    """
    depths = {}
    visiting = set()

    def _depth(node):
        if node in depths:
            return depths[node]
        if node in visiting:
            return 0  # cycle — break with 0
        visiting.add(node)
        deps = graph.get(node, [])
        if not deps:
            d = 0
        else:
            d = 1 + max(_depth(dep) for dep in deps)
        visiting.discard(node)
        depths[node] = d
        return d

    for node in graph:
        _depth(node)
    return depths


def find_roots(graph, all_files):
    """Find root modules — files that nothing else imports."""
    imported = set()
    for deps in graph.values():
        imported.update(deps)
    return sorted(all_files - imported)


def find_leaves(graph):
    """Find leaf modules — files that import nothing."""
    return sorted(f for f, deps in graph.items() if not deps)


def reachable_from(graph, start):
    """BFS to find all files reachable from start via imports."""
    visited = set()
    queue = deque([start])
    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        for dep in graph.get(node, []):
            if dep not in visited:
                queue.append(dep)
    return visited


def short_name(filepath, base_dir):
    """Get a short display name relative to base_dir."""
    try:
        rel = os.path.relpath(filepath, base_dir)
    except ValueError:
        rel = filepath
    # Remove .srv extension for cleaner display
    if rel.endswith(".srv"):
        rel = rel[:-4]
    return rel.replace("\\", "/")


# ── Output Formatters ──────────────────────────────────────────────


def format_text(graph, unresolved, all_files, base_dir, show_tree=False):
    """Format dependency graph as human-readable text."""
    lines = []
    lines.append("═══ SauravCode Dependency Report ═══")
    lines.append(f"Files analyzed: {len(all_files)}")

    total_edges = sum(len(deps) for deps in graph.values())
    lines.append(f"Import edges:   {total_edges}")
    lines.append("")

    # Per-file summary
    lines.append("── Module Dependencies ──")
    for filepath in sorted(graph.keys()):
        name = short_name(filepath, base_dir)
        deps = graph[filepath]
        dep_names = [short_name(d, base_dir) for d in deps]
        if deps:
            lines.append(f"  {name} → {', '.join(dep_names)}")
        else:
            lines.append(f"  {name} (no imports)")

    # Unresolved
    if unresolved:
        lines.append("")
        lines.append("── Unresolved Imports ──")
        for filepath, modules in sorted(unresolved.items()):
            name = short_name(filepath, base_dir)
            for m in modules:
                lines.append(f"  ⚠ {name} → {m} (not found)")

    # Cycles
    cycles = find_cycles(graph)
    lines.append("")
    if cycles:
        lines.append(f"── Circular Dependencies ({len(cycles)} found) ──")
        for i, cycle in enumerate(cycles, 1):
            cycle_names = [short_name(f, base_dir) for f in cycle]
            lines.append(f"  {i}. {' → '.join(cycle_names)} → {cycle_names[0]}")
    else:
        lines.append("── No Circular Dependencies ✓ ──")

    if show_tree:
        lines.append("")
        lines.append("── Import Trees ──")
        for filepath in sorted(graph.keys()):
            if graph[filepath]:
                name = short_name(filepath, base_dir)
                lines.append(f"  {name}")
                _print_tree(graph, filepath, base_dir, lines, set(), "    ")

    return "\n".join(lines)


def _print_tree(graph, node, base_dir, lines, visited, indent):
    """Recursively print the import tree."""
    deps = graph.get(node, [])
    for i, dep in enumerate(deps):
        is_last = i == len(deps) - 1
        connector = "└── " if is_last else "├── "
        name = short_name(dep, base_dir)
        if dep in visited:
            lines.append(f"{indent}{connector}{name} (circular)")
        else:
            lines.append(f"{indent}{connector}{name}")
            visited.add(dep)
            child_indent = indent + ("    " if is_last else "│   ")
            _print_tree(graph, dep, base_dir, lines, visited, child_indent)
            visited.discard(dep)


def format_dot(graph, base_dir):
    """Format dependency graph as Graphviz DOT."""
    lines = ['digraph dependencies {']
    lines.append('    rankdir=LR;')
    lines.append('    node [shape=box, style="rounded,filled", fillcolor="#e8f4f8", fontname="Consolas"];')
    lines.append('    edge [color="#666666"];')
    lines.append("")

    # Define nodes
    node_ids = {}
    for i, filepath in enumerate(sorted(set(
        list(graph.keys()) + [d for deps in graph.values() for d in deps]
    ))):
        nid = f"n{i}"
        node_ids[filepath] = nid
        name = short_name(filepath, base_dir)
        lines.append(f'    {nid} [label="{name}"];')

    lines.append("")

    # Define edges
    cycles = find_cycles(graph)
    cycle_edges = set()
    for cycle in cycles:
        for j in range(len(cycle)):
            a = cycle[j]
            b = cycle[(j + 1) % len(cycle)]
            cycle_edges.add((a, b))

    for filepath in sorted(graph.keys()):
        src = node_ids[filepath]
        for dep in graph[filepath]:
            dst = node_ids.get(dep, "unknown")
            if (filepath, dep) in cycle_edges:
                lines.append(f'    {src} -> {dst} [color="red", penwidth=2];')
            else:
                lines.append(f'    {src} -> {dst};')

    lines.append("}")
    return "\n".join(lines)


def format_json(graph, unresolved, all_files, base_dir):
    """Format dependency graph as JSON."""
    cycles = find_cycles(graph)
    depths = compute_depth(graph)

    data = {
        "files": len(all_files),
        "edges": sum(len(deps) for deps in graph.values()),
        "modules": {},
        "cycles": [],
        "roots": [short_name(f, base_dir) for f in find_roots(graph, all_files)],
        "leaves": [short_name(f, base_dir) for f in find_leaves(graph)],
    }

    for filepath in sorted(graph.keys()):
        name = short_name(filepath, base_dir)
        data["modules"][name] = {
            "imports": [short_name(d, base_dir) for d in graph[filepath]],
            "depth": depths.get(filepath, 0),
        }
        if filepath in unresolved:
            data["modules"][name]["unresolved"] = unresolved[filepath]

    for cycle in cycles:
        data["cycles"].append([short_name(f, base_dir) for f in cycle])

    return json.dumps(data, indent=2)


# ── CLI ──────────────────────────────────────────────────────────


def _safe_print(text):
    """Print with fallback encoding for Windows consoles."""
    try:
        print(text)
    except UnicodeEncodeError:
        # Replace problematic chars for non-UTF-8 terminals
        safe = text.encode(sys.stdout.encoding or "ascii", errors="replace").decode(
            sys.stdout.encoding or "ascii"
        )
        print(safe)


def main():
    parser = argparse.ArgumentParser(
        prog="sauravdeps",
        description="Dependency analyzer for SauravCode (.srv) projects",
    )
    parser.add_argument("path", help="File or directory to analyze")
    parser.add_argument(
        "--format", "-f",
        choices=["text", "dot", "json"],
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument("--cycles", action="store_true", help="Only show circular dependencies")
    parser.add_argument("--stats", action="store_true", help="Show import statistics")
    parser.add_argument("--tree", action="store_true", help="Show import tree per file")
    parser.add_argument("--roots", action="store_true", help="Show root modules (not imported by anything)")
    parser.add_argument("--leaves", action="store_true", help="Show leaf modules (import nothing)")
    parser.add_argument("--depth", action="store_true", help="Show max dependency depth per module")
    parser.add_argument("--unused", metavar="ENTRY", help="Find modules not reachable from ENTRY file")
    parser.add_argument(
        "-I", "--include",
        action="append", default=[],
        help="Additional directories to search for imports",
    )
    parser.add_argument("-o", "--output", help="Write output to file instead of stdout")
    parser.add_argument("--version", action="version", version=f"sauravdeps {__version__}")

    args = parser.parse_args()

    target = os.path.abspath(args.path)
    if not os.path.exists(target):
        print(f"Error: '{args.path}' does not exist.", file=sys.stderr)
        sys.exit(1)

    base_dir = target if os.path.isdir(target) else os.path.dirname(target)
    srv_files = discover_srv_files(target)

    if not srv_files:
        print(f"No .srv files found in '{args.path}'.", file=sys.stderr)
        sys.exit(1)

    graph, unresolved, all_files = build_graph(srv_files, args.include)

    # Handle specific subcommands
    output = None

    if args.cycles:
        cycles = find_cycles(graph)
        if cycles:
            lines = [f"Found {len(cycles)} circular dependency chain(s):"]
            for i, cycle in enumerate(cycles, 1):
                names = [short_name(f, base_dir) for f in cycle]
                lines.append(f"  {i}. {' → '.join(names)} → {names[0]}")
            output = "\n".join(lines)
        else:
            output = "No circular dependencies found ✓"

    elif args.stats:
        depths = compute_depth(graph)
        total_edges = sum(len(deps) for deps in graph.values())
        roots = find_roots(graph, all_files)
        leaves = find_leaves(graph)

        # Most imported (fan-in)
        fan_in = defaultdict(int)
        for deps in graph.values():
            for d in deps:
                fan_in[d] += 1
        top_imported = sorted(fan_in.items(), key=lambda x: -x[1])[:5]

        # Most dependencies (fan-out)
        top_deps = sorted(graph.items(), key=lambda x: -len(x[1]))[:5]

        lines = [
            "═══ Import Statistics ═══",
            f"Total modules:      {len(all_files)}",
            f"Total import edges: {total_edges}",
            f"Root modules:       {len(roots)}",
            f"Leaf modules:       {len(leaves)}",
            f"Avg imports/module: {total_edges / max(len(graph), 1):.1f}",
            f"Max depth:          {max(depths.values()) if depths else 0}",
            f"Circular deps:      {len(find_cycles(graph))}",
            "",
        ]
        if top_imported:
            lines.append("Most imported (fan-in):")
            for f, count in top_imported:
                lines.append(f"  {short_name(f, base_dir)}: imported by {count} module(s)")
        if top_deps:
            lines.append("Most dependencies (fan-out):")
            for f, deps in top_deps:
                if deps:
                    lines.append(f"  {short_name(f, base_dir)}: {len(deps)} import(s)")
        if unresolved:
            lines.append(f"\nUnresolved imports: {sum(len(v) for v in unresolved.values())}")
        output = "\n".join(lines)

    elif args.roots:
        roots = find_roots(graph, all_files)
        if roots:
            output = "Root modules (not imported by anything):\n" + "\n".join(
                f"  {short_name(f, base_dir)}" for f in roots
            )
        else:
            output = "No root modules found (everything is imported by something)."

    elif args.leaves:
        leaves = find_leaves(graph)
        if leaves:
            output = "Leaf modules (import nothing):\n" + "\n".join(
                f"  {short_name(f, base_dir)}" for f in leaves
            )
        else:
            output = "No leaf modules found (everything imports something)."

    elif args.depth:
        depths = compute_depth(graph)
        sorted_depths = sorted(depths.items(), key=lambda x: (-x[1], x[0]))
        lines = ["Module dependency depths:"]
        for f, d in sorted_depths:
            bar = "█" * d if d > 0 else "·"
            lines.append(f"  {short_name(f, base_dir):30s}  depth {d}  {bar}")
        output = "\n".join(lines)

    elif args.unused:
        entry = os.path.abspath(args.unused)
        if not os.path.isfile(entry):
            print(f"Error: entry file '{args.unused}' not found.", file=sys.stderr)
            sys.exit(1)
        reached = reachable_from(graph, entry)
        unreached = sorted(all_files - reached)
        if unreached:
            output = f"Modules not reachable from {short_name(entry, base_dir)}:\n" + "\n".join(
                f"  {short_name(f, base_dir)}" for f in unreached
            )
        else:
            output = f"All modules are reachable from {short_name(entry, base_dir)} ✓"

    else:
        # Default: full report
        if args.format == "dot":
            output = format_dot(graph, base_dir)
        elif args.format == "json":
            output = format_json(graph, unresolved, all_files, base_dir)
        else:
            output = format_text(graph, unresolved, all_files, base_dir, show_tree=args.tree)

    # Output
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output + "\n")
        print(f"Output written to {args.output}")
    else:
        _safe_print(output)


if __name__ == "__main__":
    main()
