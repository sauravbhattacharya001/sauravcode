#!/usr/bin/env python3
"""sauravmap — Autonomous Codebase Cartographer for sauravcode.

Statically analyzes .srv files to map function definitions, function calls,
class hierarchies, imports, and variable assignments. Generates an interactive
HTML dependency graph with proactive recommendations for code health.

Features:
  - Function/class definition extraction across multi-file projects
  - Call graph construction with cross-file resolution
  - Orphaned function detection (defined but never called)
  - Hot path identification (most-called functions)
  - Circular dependency detection between files
  - Complexity hotspot scoring (lines, branches, nesting)
  - Interactive force-directed HTML visualization
  - Proactive recommendations for refactoring

Usage:
    python sauravmap.py <file_or_dir> [options]

Options:
    --html FILE       Write interactive HTML report (default: sauravmap_report.html)
    --json            Output JSON analysis to stdout
    --no-html         Skip HTML generation, print text summary only
    --depth N         Max directory recursion depth (default: 5)
    --watch           Re-analyze on file changes (auto-monitor mode)
    --recommend       Show proactive recommendations
"""

import os
import re
import sys
import json
import math
import time
import hashlib

# Fix Windows console encoding for Unicode output
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
from collections import defaultdict
from pathlib import Path

# ── regex patterns for sauravcode constructs ──────────────────────────
RE_FUNCTION = re.compile(r'^fun\s+(\w+)\s*\((.*?)\)', re.MULTILINE)
RE_CLASS = re.compile(r'^class\s+(\w+)(?:\s+extends\s+(\w+))?', re.MULTILINE)
RE_IMPORT = re.compile(r'^import\s+"([^"]+)"', re.MULTILINE)
RE_CALL = re.compile(r'\b(\w+)\s*\(')
RE_ASSIGN = re.compile(r'^(\w+)\s*=', re.MULTILINE)
RE_IF = re.compile(r'^\s*if\s+', re.MULTILINE)
RE_FOR = re.compile(r'^\s*for\s+', re.MULTILINE)
RE_WHILE = re.compile(r'^\s*while\s+', re.MULTILINE)
RE_COMMENT = re.compile(r'^\s*#', re.MULTILINE)

# Built-in functions to exclude from call graph
BUILTINS = {
    'print', 'input', 'len', 'type', 'str', 'int', 'float', 'bool',
    'list', 'map', 'filter', 'reduce', 'range', 'append', 'push', 'pop',
    'keys', 'values', 'items', 'split', 'join', 'replace', 'strip',
    'upper', 'lower', 'find', 'contains', 'starts_with', 'ends_with',
    'sort', 'reverse', 'abs', 'min', 'max', 'sum', 'round', 'floor',
    'ceil', 'sqrt', 'pow', 'log', 'sin', 'cos', 'tan', 'random',
    'sleep', 'time', 'assert', 'error', 'try', 'catch',
    'graph_create', 'graph_add_node', 'graph_add_edge', 'graph_nodes',
    'graph_edges', 'graph_neighbors', 'graph_bfs', 'graph_dfs',
    'graph_shortest_path', 'graph_has_node', 'graph_has_edge',
    'graph_remove_node', 'graph_remove_edge', 'graph_degree',
    'stack_new', 'queue_new', 'set_new', 'map_new', 'heap_new',
    'trie_new', 'linkedlist_new', 'ring_new', 'bloom_new',
    'file_read', 'file_write', 'file_exists', 'file_delete',
    'json_parse', 'json_stringify', 'regex_match', 'regex_find',
    'http_get', 'http_post', 'hash_md5', 'hash_sha256',
    'table_new', 'table_add_row', 'table_render',
}


class FileAnalysis:
    """Analysis results for a single .srv file."""
    __slots__ = ('path', 'functions', 'classes', 'imports', 'calls',
                 'assignments', 'lines', 'comment_lines', 'branches',
                 'complexity_score')

    def __init__(self, path):
        self.path = path
        self.functions = {}   # name -> {params, line, end_line}
        self.classes = {}     # name -> {parent, line, methods}
        self.imports = []     # list of imported file paths
        self.calls = []       # list of (caller_func_or_None, callee_name, line)
        self.assignments = [] # list of (name, line)
        self.lines = 0
        self.comment_lines = 0
        self.branches = 0
        self.complexity_score = 0.0


def analyze_file(filepath):
    """Parse a .srv file and extract structural information."""
    analysis = FileAnalysis(filepath)
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    except (IOError, OSError):
        return analysis

    lines = content.split('\n')
    analysis.lines = len(lines)
    analysis.comment_lines = len(RE_COMMENT.findall(content))

    # Extract function definitions
    for m in RE_FUNCTION.finditer(content):
        name = m.group(1)
        params = [p.strip() for p in m.group(2).split(',') if p.strip()]
        line_no = content[:m.start()].count('\n') + 1
        analysis.functions[name] = {
            'params': params,
            'line': line_no,
            'param_count': len(params),
        }

    # Extract class definitions
    for m in RE_CLASS.finditer(content):
        name = m.group(1)
        parent = m.group(2)
        line_no = content[:m.start()].count('\n') + 1
        analysis.classes[name] = {
            'parent': parent,
            'line': line_no,
        }

    # Extract imports
    for m in RE_IMPORT.finditer(content):
        analysis.imports.append(m.group(1))

    # Extract function calls with context
    # Determine which function scope each line belongs to
    func_ranges = []
    sorted_funcs = sorted(analysis.functions.items(), key=lambda x: x[1]['line'])
    for i, (fname, finfo) in enumerate(sorted_funcs):
        start = finfo['line']
        # End is next function start or EOF
        end = sorted_funcs[i + 1][1]['line'] if i + 1 < len(sorted_funcs) else len(lines) + 1
        func_ranges.append((fname, start, end))

    def get_scope(line_no):
        for fname, start, end in func_ranges:
            if start <= line_no < end:
                return fname
        return None

    for m in RE_CALL.finditer(content):
        callee = m.group(1)
        if callee in BUILTINS or callee in ('fun', 'class', 'if', 'for', 'while', 'return', 'import'):
            continue
        line_no = content[:m.start()].count('\n') + 1
        caller = get_scope(line_no)
        analysis.calls.append((caller, callee, line_no))

    # Count branches for complexity
    analysis.branches = (len(RE_IF.findall(content)) +
                         len(RE_FOR.findall(content)) +
                         len(RE_WHILE.findall(content)))

    # Complexity score: lines + 2*branches + 0.5*functions
    analysis.complexity_score = round(
        analysis.lines + 2 * analysis.branches + 0.5 * len(analysis.functions), 1
    )

    # Assignments
    for m in RE_ASSIGN.finditer(content):
        name = m.group(1)
        if name not in ('fun', 'class', 'if', 'for', 'while', 'return', 'import', '#'):
            line_no = content[:m.start()].count('\n') + 1
            analysis.assignments.append((name, line_no))

    return analysis


def discover_files(target, max_depth=5):
    """Find all .srv files in target path."""
    target = Path(target)
    if target.is_file() and target.suffix == '.srv':
        return [str(target)]
    if target.is_dir():
        files = []
        for root, dirs, fnames in os.walk(target):
            depth = str(root).replace(str(target), '').count(os.sep)
            if depth >= max_depth:
                dirs.clear()
                continue
            for fn in fnames:
                if fn.endswith('.srv'):
                    files.append(os.path.join(root, fn))
        return sorted(files)
    return []


def build_project_graph(analyses):
    """Build cross-file dependency graph and call graph."""
    # All defined functions across project
    all_functions = {}  # name -> filepath
    all_classes = {}    # name -> filepath
    for a in analyses:
        for fname in a.functions:
            all_functions[fname] = a.path
        for cname in a.classes:
            all_classes[cname] = a.path

    # Call graph edges: (caller_file, caller_func) -> [(callee_file, callee_func)]
    call_edges = []
    unresolved_calls = []
    for a in analyses:
        for caller_func, callee_name, line_no in a.calls:
            if callee_name in all_functions:
                call_edges.append({
                    'source_file': a.path,
                    'source_func': caller_func,
                    'target_file': all_functions[callee_name],
                    'target_func': callee_name,
                    'line': line_no,
                })
            elif callee_name in all_classes:
                call_edges.append({
                    'source_file': a.path,
                    'source_func': caller_func,
                    'target_file': all_classes[callee_name],
                    'target_func': callee_name,
                    'line': line_no,
                    'type': 'class_instantiation',
                })
            else:
                unresolved_calls.append({
                    'file': a.path,
                    'func': caller_func,
                    'callee': callee_name,
                    'line': line_no,
                })

    # File-level import graph
    file_imports = {}
    for a in analyses:
        file_imports[a.path] = a.imports

    return call_edges, unresolved_calls, file_imports


def detect_orphans(analyses, call_edges):
    """Find functions that are defined but never called."""
    called = set()
    for edge in call_edges:
        called.add(edge['target_func'])

    # Also exclude 'main' and entry-point-like functions
    entry_points = {'main', 'init', 'setup', 'start', 'run', 'test'}

    orphans = []
    for a in analyses:
        for fname, finfo in a.functions.items():
            if fname not in called and fname.lower() not in entry_points:
                orphans.append({
                    'file': a.path,
                    'function': fname,
                    'line': finfo['line'],
                    'params': finfo['param_count'],
                })
    return orphans


def detect_hot_functions(call_edges):
    """Find the most-called functions (hot paths)."""
    call_count = defaultdict(int)
    for edge in call_edges:
        key = (edge['target_file'], edge['target_func'])
        call_count[key] += 1
    ranked = sorted(call_count.items(), key=lambda x: -x[1])
    return [{'file': k[0], 'function': k[1], 'calls': v} for k, v in ranked[:15]]


def detect_circular_imports(file_imports, analyses):
    """Detect circular import chains between files."""
    # Build adjacency from imports
    file_map = {}
    for a in analyses:
        base = os.path.basename(a.path)
        name_no_ext = os.path.splitext(base)[0]
        file_map[name_no_ext] = a.path
        file_map[base] = a.path

    adj = defaultdict(set)
    for a in analyses:
        for imp in a.imports:
            imp_base = os.path.splitext(os.path.basename(imp))[0]
            if imp_base in file_map or imp in file_map:
                target = file_map.get(imp_base, file_map.get(imp, imp))
                adj[a.path].add(target)

    # DFS cycle detection
    cycles = []
    visited = set()
    path = []
    path_set = set()

    def dfs(node):
        if node in path_set:
            idx = path.index(node)
            cycles.append(list(path[idx:]))
            return
        if node in visited:
            return
        visited.add(node)
        path.append(node)
        path_set.add(node)
        for neighbor in adj.get(node, []):
            dfs(neighbor)
        path.pop()
        path_set.discard(node)

    for node in adj:
        dfs(node)

    return cycles


def generate_recommendations(analyses, orphans, hot_funcs, cycles, call_edges):
    """Generate proactive improvement recommendations."""
    recs = []

    # Orphan recommendations
    if orphans:
        recs.append({
            'severity': 'warning',
            'category': 'Dead Code',
            'message': f'{len(orphans)} function(s) defined but never called — consider removing or documenting their intended use.',
            'details': [f"  {o['function']} in {os.path.basename(o['file'])}:{o['line']}" for o in orphans[:5]],
        })

    # Hot path recommendations
    for hf in hot_funcs[:3]:
        if hf['calls'] >= 5:
            recs.append({
                'severity': 'info',
                'category': 'Hot Path',
                'message': f"'{hf['function']}' is called {hf['calls']} times — consider optimizing or caching its results.",
                'details': [],
            })

    # Circular dependency recommendations
    if cycles:
        recs.append({
            'severity': 'error',
            'category': 'Circular Import',
            'message': f'{len(cycles)} circular import chain(s) detected — refactor to break the cycle.',
            'details': [' → '.join(os.path.basename(f) for f in c) for c in cycles[:3]],
        })

    # Large file recommendations
    for a in analyses:
        if a.lines > 500:
            recs.append({
                'severity': 'warning',
                'category': 'Large File',
                'message': f"{os.path.basename(a.path)} has {a.lines} lines — consider splitting into modules.",
                'details': [],
            })
        if len(a.functions) > 20:
            recs.append({
                'severity': 'info',
                'category': 'Many Functions',
                'message': f"{os.path.basename(a.path)} defines {len(a.functions)} functions — consider grouping related functions into separate files.",
                'details': [],
            })

    # Complexity hotspots
    sorted_by_complexity = sorted(analyses, key=lambda a: -a.complexity_score)
    for a in sorted_by_complexity[:2]:
        if a.complexity_score > 100:
            recs.append({
                'severity': 'info',
                'category': 'Complexity Hotspot',
                'message': f"{os.path.basename(a.path)} has complexity score {a.complexity_score} — review for simplification opportunities.",
                'details': [],
            })

    # Low comment ratio
    for a in analyses:
        if a.lines > 50 and a.comment_lines / max(a.lines, 1) < 0.05:
            recs.append({
                'severity': 'info',
                'category': 'Low Documentation',
                'message': f"{os.path.basename(a.path)} has only {a.comment_lines} comment lines in {a.lines} lines ({a.comment_lines*100//max(a.lines,1)}%) — consider adding documentation.",
                'details': [],
            })

    if not recs:
        recs.append({
            'severity': 'success',
            'category': 'Clean',
            'message': 'No issues detected — codebase looks healthy! ✨',
            'details': [],
        })

    return recs


def generate_html(analyses, call_edges, orphans, hot_funcs, cycles, recommendations, output_path):
    """Generate interactive HTML report with force-directed graph."""
    # Build nodes and edges for visualization
    nodes = []
    node_ids = {}
    idx = 0

    for a in analyses:
        # File node
        fid = f"file_{idx}"
        short = os.path.basename(a.path)
        node_ids[a.path] = fid
        nodes.append({
            'id': fid, 'label': short, 'type': 'file',
            'lines': a.lines, 'functions': len(a.functions),
            'classes': len(a.classes), 'complexity': a.complexity_score,
        })
        idx += 1
        # Function nodes
        for fname, finfo in a.functions.items():
            nid = f"func_{idx}"
            node_ids[(a.path, fname)] = nid
            is_orphan = any(o['function'] == fname and o['file'] == a.path for o in orphans)
            call_ct = sum(1 for e in call_edges if e['target_func'] == fname)
            nodes.append({
                'id': nid, 'label': fname, 'type': 'function',
                'file': short, 'line': finfo['line'],
                'params': finfo['param_count'], 'orphan': is_orphan,
                'call_count': call_ct, 'parent': fid,
            })
            idx += 1

    # Edges
    edges = []
    # Function containment
    for a in analyses:
        fid = node_ids[a.path]
        for fname in a.functions:
            nid = node_ids.get((a.path, fname))
            if nid:
                edges.append({'source': fid, 'target': nid, 'type': 'contains'})

    # Call edges
    for ce in call_edges:
        src = node_ids.get((ce['source_file'], ce['source_func'])) if ce['source_func'] else node_ids.get(ce['source_file'])
        tgt = node_ids.get((ce['target_file'], ce['target_func']))
        if src and tgt:
            edges.append({'source': src, 'target': tgt, 'type': 'calls'})

    data = json.dumps({'nodes': nodes, 'edges': edges}, indent=None)
    recs_json = json.dumps(recommendations, indent=None)
    hot_json = json.dumps(hot_funcs, indent=None)
    orphan_json = json.dumps(orphans, indent=None)

    stats = {
        'files': len(analyses),
        'total_lines': sum(a.lines for a in analyses),
        'total_functions': sum(len(a.functions) for a in analyses),
        'total_classes': sum(len(a.classes) for a in analyses),
        'total_calls': len(call_edges),
        'orphans': len(orphans),
        'cycles': len(cycles),
    }

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>sauravmap — Codebase Cartographer</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: 'Segoe UI', system-ui, sans-serif; background:#0d1117; color:#c9d1d9; overflow:hidden; }}
#header {{ background:#161b22; padding:12px 20px; border-bottom:1px solid #30363d; display:flex; align-items:center; gap:16px; }}
#header h1 {{ font-size:18px; color:#58a6ff; }}
#header .stat {{ background:#21262d; padding:4px 10px; border-radius:12px; font-size:13px; }}
#header .stat b {{ color:#58a6ff; }}
#main {{ display:flex; height:calc(100vh - 50px); }}
#canvas-wrap {{ flex:1; position:relative; }}
canvas {{ width:100%; height:100%; }}
#sidebar {{ width:340px; background:#161b22; border-left:1px solid #30363d; overflow-y:auto; padding:12px; }}
.panel {{ margin-bottom:16px; }}
.panel h3 {{ font-size:14px; color:#8b949e; margin-bottom:8px; text-transform:uppercase; letter-spacing:0.5px; }}
.rec {{ padding:8px 10px; border-radius:6px; margin-bottom:6px; font-size:13px; line-height:1.4; }}
.rec.error {{ background:#3d1a1a; border-left:3px solid #f85149; }}
.rec.warning {{ background:#3d2e00; border-left:3px solid #d29922; }}
.rec.info {{ background:#0c2d6b; border-left:3px solid #58a6ff; }}
.rec.success {{ background:#0d2818; border-left:3px solid #3fb950; }}
.rec .cat {{ font-weight:600; font-size:11px; text-transform:uppercase; opacity:0.7; }}
.rec .det {{ font-size:11px; color:#8b949e; margin-top:4px; font-family:monospace; }}
.hot-item {{ display:flex; justify-content:space-between; padding:4px 0; font-size:13px; border-bottom:1px solid #21262d; }}
.hot-item .count {{ color:#f0883e; font-weight:600; }}
.orphan-item {{ font-size:13px; padding:3px 0; color:#d29922; }}
.legend {{ display:flex; flex-wrap:wrap; gap:8px; margin-bottom:12px; }}
.legend span {{ display:flex; align-items:center; gap:4px; font-size:12px; }}
.legend .dot {{ width:10px; height:10px; border-radius:50%; display:inline-block; }}
#tooltip {{ position:absolute; background:#1c2128; border:1px solid #30363d; border-radius:6px; padding:8px 12px; font-size:12px; pointer-events:none; display:none; z-index:10; max-width:250px; }}
</style>
</head>
<body>
<div id="header">
  <h1>🗺️ sauravmap</h1>
  <span class="stat">Files: <b>{stats['files']}</b></span>
  <span class="stat">Lines: <b>{stats['total_lines']}</b></span>
  <span class="stat">Functions: <b>{stats['total_functions']}</b></span>
  <span class="stat">Classes: <b>{stats['total_classes']}</b></span>
  <span class="stat">Calls: <b>{stats['total_calls']}</b></span>
  <span class="stat" style="color:#d29922">Orphans: <b>{stats['orphans']}</b></span>
  <span class="stat" style="color:#f85149">Cycles: <b>{stats['cycles']}</b></span>
</div>
<div id="main">
  <div id="canvas-wrap">
    <canvas id="graph"></canvas>
    <div id="tooltip"></div>
  </div>
  <div id="sidebar">
    <div class="panel">
      <h3>Legend</h3>
      <div class="legend">
        <span><span class="dot" style="background:#58a6ff"></span> File</span>
        <span><span class="dot" style="background:#3fb950"></span> Function</span>
        <span><span class="dot" style="background:#d29922"></span> Orphan</span>
        <span><span class="dot" style="background:#f0883e"></span> Hot Path</span>
      </div>
    </div>
    <div class="panel">
      <h3>🔮 Recommendations</h3>
      <div id="recs"></div>
    </div>
    <div class="panel">
      <h3>🔥 Hot Functions</h3>
      <div id="hot"></div>
    </div>
    <div class="panel">
      <h3>👻 Orphaned Functions</h3>
      <div id="orphans-list"></div>
    </div>
  </div>
</div>
<script>
const DATA = {data};
const RECS = {recs_json};
const HOT = {hot_json};
const ORPHANS = {orphan_json};

// Render sidebar
const recsEl = document.getElementById('recs');
RECS.forEach(r => {{
  const d = document.createElement('div');
  d.className = 'rec ' + r.severity;
  d.innerHTML = '<div class="cat">' + r.category + '</div>' + r.message +
    (r.details.length ? '<div class="det">' + r.details.join('<br>') + '</div>' : '');
  recsEl.appendChild(d);
}});

const hotEl = document.getElementById('hot');
HOT.forEach(h => {{
  const d = document.createElement('div');
  d.className = 'hot-item';
  d.innerHTML = '<span>' + h.function + '</span><span class="count">' + h.calls + ' calls</span>';
  hotEl.appendChild(d);
}});
if (!HOT.length) hotEl.innerHTML = '<div style="font-size:13px;color:#8b949e">No hot paths detected</div>';

const orpEl = document.getElementById('orphans-list');
ORPHANS.slice(0, 15).forEach(o => {{
  const d = document.createElement('div');
  d.className = 'orphan-item';
  d.textContent = o.function + ' (' + o.file.split(/[\\/\\\\]/).pop() + ':' + o.line + ')';
  orpEl.appendChild(d);
}});
if (!ORPHANS.length) orpEl.innerHTML = '<div style="font-size:13px;color:#8b949e">None — all functions are called ✨</div>';

// Force-directed graph
const canvas = document.getElementById('graph');
const ctx = canvas.getContext('2d');
const tooltip = document.getElementById('tooltip');
let W, H;
function resize() {{
  const r = canvas.parentElement.getBoundingClientRect();
  W = canvas.width = r.width * devicePixelRatio;
  H = canvas.height = r.height * devicePixelRatio;
  canvas.style.width = r.width + 'px';
  canvas.style.height = r.height + 'px';
  ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
}}
resize();
window.addEventListener('resize', resize);

const nodes = DATA.nodes.map((n, i) => ({{
  ...n, x: W/devicePixelRatio/2 + (Math.random()-0.5)*300,
  y: H/devicePixelRatio/2 + (Math.random()-0.5)*300,
  vx: 0, vy: 0,
  r: n.type === 'file' ? 14 : (6 + Math.min((n.call_count||0)*2, 12)),
}}));
const nodeMap = {{}};
nodes.forEach(n => nodeMap[n.id] = n);
const edges = DATA.edges.filter(e => nodeMap[e.source] && nodeMap[e.target]);

let dragging = null, mx = 0, my = 0;
canvas.addEventListener('mousedown', e => {{
  const rect = canvas.getBoundingClientRect();
  mx = e.clientX - rect.left; my = e.clientY - rect.top;
  for (const n of nodes) {{
    if (Math.hypot(n.x - mx, n.y - my) < n.r + 4) {{ dragging = n; break; }}
  }}
}});
canvas.addEventListener('mousemove', e => {{
  const rect = canvas.getBoundingClientRect();
  mx = e.clientX - rect.left; my = e.clientY - rect.top;
  if (dragging) {{ dragging.x = mx; dragging.y = my; dragging.vx = 0; dragging.vy = 0; }}
  // Tooltip
  let hit = null;
  for (const n of nodes) {{
    if (Math.hypot(n.x - mx, n.y - my) < n.r + 4) {{ hit = n; break; }}
  }}
  if (hit) {{
    tooltip.style.display = 'block';
    tooltip.style.left = (mx + 15) + 'px';
    tooltip.style.top = (my + 15) + 'px';
    if (hit.type === 'file') {{
      tooltip.innerHTML = '<b>' + hit.label + '</b><br>Lines: ' + hit.lines +
        '<br>Functions: ' + hit.functions + '<br>Complexity: ' + hit.complexity;
    }} else {{
      tooltip.innerHTML = '<b>' + hit.label + '()</b><br>File: ' + hit.file +
        '<br>Line: ' + hit.line + '<br>Params: ' + hit.params +
        '<br>Called: ' + (hit.call_count||0) + 'x' +
        (hit.orphan ? '<br><span style="color:#d29922">⚠ Orphaned</span>' : '');
    }}
  }} else {{ tooltip.style.display = 'none'; }}
}});
canvas.addEventListener('mouseup', () => {{ dragging = null; }});

function tick() {{
  const cw = W/devicePixelRatio, ch = H/devicePixelRatio;
  // Repulsion
  for (let i = 0; i < nodes.length; i++) {{
    for (let j = i+1; j < nodes.length; j++) {{
      let dx = nodes[j].x - nodes[i].x, dy = nodes[j].y - nodes[i].y;
      let d = Math.max(Math.hypot(dx, dy), 1);
      let f = 800 / (d * d);
      nodes[i].vx -= dx/d * f; nodes[i].vy -= dy/d * f;
      nodes[j].vx += dx/d * f; nodes[j].vy += dy/d * f;
    }}
  }}
  // Attraction along edges
  edges.forEach(e => {{
    const a = nodeMap[e.source], b = nodeMap[e.target];
    if (!a || !b) return;
    let dx = b.x - a.x, dy = b.y - a.y;
    let d = Math.max(Math.hypot(dx, dy), 1);
    let ideal = e.type === 'contains' ? 40 : 100;
    let f = (d - ideal) * 0.01;
    a.vx += dx/d * f; a.vy += dy/d * f;
    b.vx -= dx/d * f; b.vy -= dy/d * f;
  }});
  // Center gravity
  nodes.forEach(n => {{
    n.vx += (cw/2 - n.x) * 0.001;
    n.vy += (ch/2 - n.y) * 0.001;
    if (n !== dragging) {{
      n.vx *= 0.9; n.vy *= 0.9;
      n.x += n.vx; n.y += n.vy;
      n.x = Math.max(n.r, Math.min(cw - n.r, n.x));
      n.y = Math.max(n.r, Math.min(ch - n.r, n.y));
    }}
  }});
}}

function draw() {{
  const cw = W/devicePixelRatio, ch = H/devicePixelRatio;
  ctx.clearRect(0, 0, cw, ch);
  // Edges
  edges.forEach(e => {{
    const a = nodeMap[e.source], b = nodeMap[e.target];
    if (!a || !b) return;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
    ctx.strokeStyle = e.type === 'contains' ? 'rgba(48,54,61,0.6)' :
                      e.type === 'calls' ? 'rgba(88,166,255,0.3)' : 'rgba(48,54,61,0.4)';
    ctx.lineWidth = e.type === 'calls' ? 1.5 : 0.8;
    ctx.stroke();
    // Arrow for calls
    if (e.type === 'calls') {{
      const dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.hypot(dx, dy);
      if (d > 0) {{
        const ux = dx/d, uy = dy/d;
        const ax = b.x - ux*(b.r+4), ay = b.y - uy*(b.r+4);
        ctx.beginPath();
        ctx.moveTo(ax, ay);
        ctx.lineTo(ax - ux*6 - uy*3, ay - uy*6 + ux*3);
        ctx.lineTo(ax - ux*6 + uy*3, ay - uy*6 - ux*3);
        ctx.fillStyle = 'rgba(88,166,255,0.5)';
        ctx.fill();
      }}
    }}
  }});
  // Nodes
  nodes.forEach(n => {{
    ctx.beginPath();
    ctx.arc(n.x, n.y, n.r, 0, Math.PI*2);
    if (n.type === 'file') {{ ctx.fillStyle = '#58a6ff'; }}
    else if (n.orphan) {{ ctx.fillStyle = '#d29922'; }}
    else if ((n.call_count||0) >= 3) {{ ctx.fillStyle = '#f0883e'; }}
    else {{ ctx.fillStyle = '#3fb950'; }}
    ctx.fill();
    // Label
    ctx.font = n.type === 'file' ? 'bold 11px sans-serif' : '10px sans-serif';
    ctx.fillStyle = '#c9d1d9';
    ctx.textAlign = 'center';
    ctx.fillText(n.label, n.x, n.y + n.r + 12);
  }});
}}

function animate() {{
  tick(); draw(); requestAnimationFrame(animate);
}}
animate();
</script>
</body>
</html>"""

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)


def print_summary(analyses, call_edges, orphans, hot_funcs, cycles, recommendations):
    """Print text summary to stdout."""
    total_lines = sum(a.lines for a in analyses)
    total_funcs = sum(len(a.functions) for a in analyses)
    total_classes = sum(len(a.classes) for a in analyses)

    print("╔══════════════════════════════════════════════════╗")
    print("║        🗺️  sauravmap — Codebase Cartographer     ║")
    print("╚══════════════════════════════════════════════════╝")
    print()
    print(f"  Files analyzed:  {len(analyses)}")
    print(f"  Total lines:     {total_lines}")
    print(f"  Functions:       {total_funcs}")
    print(f"  Classes:         {total_classes}")
    print(f"  Call edges:      {len(call_edges)}")
    print(f"  Orphans:         {len(orphans)}")
    print(f"  Circular deps:   {len(cycles)}")
    print()

    if hot_funcs:
        print("  🔥 Hot Functions:")
        for hf in hot_funcs[:5]:
            print(f"     {hf['function']:20s}  {hf['calls']} calls")
        print()

    if orphans:
        print("  👻 Orphaned Functions:")
        for o in orphans[:8]:
            print(f"     {o['function']:20s}  {os.path.basename(o['file'])}:{o['line']}")
        if len(orphans) > 8:
            print(f"     ... and {len(orphans)-8} more")
        print()

    if cycles:
        print("  🔄 Circular Imports:")
        for c in cycles[:3]:
            print(f"     {' → '.join(os.path.basename(f) for f in c)}")
        print()

    print("  🔮 Recommendations:")
    for r in recommendations:
        icon = {'error': '❌', 'warning': '⚠️', 'info': 'ℹ️', 'success': '✅'}.get(r['severity'], '•')
        print(f"     {icon} [{r['category']}] {r['message']}")
        for d in r['details'][:3]:
            print(f"       {d}")
    print()


def to_json(analyses, call_edges, orphans, hot_funcs, cycles, recommendations):
    """Return full analysis as JSON dict."""
    return {
        'files': [{
            'path': a.path,
            'lines': a.lines,
            'comment_lines': a.comment_lines,
            'functions': {k: v for k, v in a.functions.items()},
            'classes': {k: v for k, v in a.classes.items()},
            'imports': a.imports,
            'complexity': a.complexity_score,
        } for a in analyses],
        'call_edges': call_edges,
        'orphans': orphans,
        'hot_functions': hot_funcs,
        'circular_imports': [[os.path.basename(f) for f in c] for c in cycles],
        'recommendations': recommendations,
        'summary': {
            'files': len(analyses),
            'total_lines': sum(a.lines for a in analyses),
            'total_functions': sum(len(a.functions) for a in analyses),
            'total_classes': sum(len(a.classes) for a in analyses),
        },
    }


def watch_mode(target, max_depth, html_output):
    """Watch for file changes and re-analyze."""
    print("👁️  Watch mode — monitoring for changes (Ctrl+C to stop)")
    last_hash = None
    while True:
        files = discover_files(target, max_depth)
        h = hashlib.md5(''.join(f + str(os.path.getmtime(f)) for f in files).encode()).hexdigest()
        if h != last_hash:
            last_hash = h
            print(f"\n🔄 Change detected — re-analyzing {len(files)} files...")
            analyses = [analyze_file(f) for f in files]
            call_edges, unresolved, file_imports = build_project_graph(analyses)
            orphans = detect_orphans(analyses, call_edges)
            hot_funcs = detect_hot_functions(call_edges)
            cycles = detect_circular_imports(file_imports, analyses)
            recs = generate_recommendations(analyses, orphans, hot_funcs, cycles, call_edges)
            print_summary(analyses, call_edges, orphans, hot_funcs, cycles, recs)
            generate_html(analyses, call_edges, orphans, hot_funcs, cycles, recs, html_output)
            print(f"  📄 HTML report updated: {html_output}")
        time.sleep(2)


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='sauravmap — Autonomous Codebase Cartographer for sauravcode',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python sauravmap.py .                        # Analyze current directory
  python sauravmap.py myproject/ --html map.html
  python sauravmap.py script.srv --json        # JSON output
  python sauravmap.py . --watch                # Auto-monitor mode
  python sauravmap.py . --recommend            # Show recommendations only
""")
    parser.add_argument('target', help='File or directory to analyze')
    parser.add_argument('--html', default='sauravmap_report.html', help='HTML output path')
    parser.add_argument('--json', action='store_true', help='Output JSON to stdout')
    parser.add_argument('--no-html', action='store_true', help='Skip HTML generation')
    parser.add_argument('--depth', type=int, default=5, help='Max directory depth')
    parser.add_argument('--watch', action='store_true', help='Watch mode — re-analyze on changes')
    parser.add_argument('--recommend', action='store_true', help='Show recommendations only')
    args = parser.parse_args()

    if args.watch:
        watch_mode(args.target, args.depth, args.html)
        return

    files = discover_files(args.target, args.depth)
    if not files:
        print(f"No .srv files found in {args.target}")
        sys.exit(1)

    analyses = [analyze_file(f) for f in files]
    call_edges, unresolved, file_imports = build_project_graph(analyses)
    orphans = detect_orphans(analyses, call_edges)
    hot_funcs = detect_hot_functions(call_edges)
    cycles = detect_circular_imports(file_imports, analyses)
    recs = generate_recommendations(analyses, orphans, hot_funcs, cycles, call_edges)

    if args.json:
        print(json.dumps(to_json(analyses, call_edges, orphans, hot_funcs, cycles, recs), indent=2))
        return

    if args.recommend:
        print("🔮 Recommendations:")
        for r in recs:
            icon = {'error': '❌', 'warning': '⚠️', 'info': 'ℹ️', 'success': '✅'}.get(r['severity'], '•')
            print(f"  {icon} [{r['category']}] {r['message']}")
            for d in r['details']:
                print(f"    {d}")
        return

    print_summary(analyses, call_edges, orphans, hot_funcs, cycles, recs)

    if not args.no_html:
        generate_html(analyses, call_edges, orphans, hot_funcs, cycles, recs, args.html)
        print(f"  📄 Interactive HTML report: {args.html}")


if __name__ == '__main__':
    main()
