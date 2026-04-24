#!/usr/bin/env python3
"""sauravreflex — Autonomous Reactive Programming Engine for sauravcode.

Analyzes .srv programs for reactive patterns and provides an interactive
reactive programming playground with dependency graph visualization.

Features:
- Reactive variable detection (reassignment pattern analysis)
- Computed value inference (repeated computations after changes)
- Dependency graph construction with topological propagation
- Cycle detection and reactivity potential scoring
- Interactive HTML playground with live reactive graphs
- Auto-monitor mode (--watch)

Usage:
    python sauravreflex.py program.srv              # Analyze reactivity potential
    python sauravreflex.py program.srv --demo       # Run built-in reactive demo
    python sauravreflex.py program.srv --report     # Generate HTML dependency graph
    python sauravreflex.py program.srv --json       # JSON output
    python sauravreflex.py program.srv --watch      # Auto-monitor mode
    python sauravreflex.py --playground             # Interactive reactive playground
"""

import sys
import os
import re
import json
import time
import argparse
import hashlib
from datetime import datetime
from collections import defaultdict, deque

# Fix Windows console encoding
import io
if sys.stdout and hasattr(sys.stdout, 'buffer'):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Reactive Primitives
# ---------------------------------------------------------------------------

class ReactiveVar:
    """Observable variable that tracks dependents and notifies on change."""

    def __init__(self, name, value=None):
        self.name = name
        self._value = value
        self.dependents = set()
        self.history = [(datetime.now().isoformat(), value)]

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, new_val):
        old = self._value
        self._value = new_val
        self.history.append((datetime.now().isoformat(), new_val))
        if old != new_val:
            for dep in self.dependents:
                dep.notify(self)

    def to_dict(self):
        return {
            "type": "ReactiveVar",
            "name": self.name,
            "value": repr(self._value),
            "dependents": [d.name for d in self.dependents],
            "changes": len(self.history),
        }


class Computed:
    """Derived reactive value that auto-recomputes when dependencies change."""

    def __init__(self, name, deps, compute_fn):
        self.name = name
        self.deps = deps
        self.compute_fn = compute_fn
        self.dependents = set()
        self._value = None
        self._dirty = True
        self.recompute_count = 0
        for d in deps:
            d.dependents.add(self)

    def notify(self, source):
        self._dirty = True
        self.recompute_count += 1
        self._value = self.compute_fn(*[d.value if hasattr(d, 'value') else d._value for d in self.deps])
        for dep in self.dependents:
            dep.notify(self)

    @property
    def value(self):
        if self._dirty:
            self._value = self.compute_fn(*[d.value if hasattr(d, 'value') else d._value for d in self.deps])
            self._dirty = False
        return self._value

    def to_dict(self):
        return {
            "type": "Computed",
            "name": self.name,
            "value": repr(self._value),
            "deps": [d.name for d in self.deps],
            "dependents": [d.name for d in self.dependents],
            "recomputes": self.recompute_count,
        }


class Effect:
    """Side effect that triggers when dependencies change."""

    def __init__(self, name, deps, effect_fn):
        self.name = name
        self.deps = deps
        self.effect_fn = effect_fn
        self.trigger_count = 0
        self.dependents = set()
        for d in deps:
            d.dependents.add(self)

    def notify(self, source):
        self.trigger_count += 1
        vals = {d.name: (d.value if hasattr(d, 'value') else d._value) for d in self.deps}
        self.effect_fn(source.name, vals)

    def to_dict(self):
        return {
            "type": "Effect",
            "name": self.name,
            "deps": [d.name for d in self.deps],
            "triggers": self.trigger_count,
        }


class Stream:
    """Event stream with functional operators."""

    def __init__(self, name):
        self.name = name
        self.subscribers = []
        self.history = []
        self.dependents = set()

    def emit(self, value):
        self.history.append((datetime.now().isoformat(), value))
        for sub in self.subscribers:
            sub(value)

    def map(self, fn, name=None):
        s = Stream(name or f"{self.name}.map")
        self.subscribers.append(lambda v: s.emit(fn(v)))
        return s

    def filter(self, fn, name=None):
        s = Stream(name or f"{self.name}.filter")
        self.subscribers.append(lambda v: s.emit(v) if fn(v) else None)
        return s

    def merge(self, other, name=None):
        s = Stream(name or f"{self.name}+{other.name}")
        self.subscribers.append(lambda v: s.emit(v))
        other.subscribers.append(lambda v: s.emit(v))
        return s

    def subscribe(self, callback):
        self.subscribers.append(callback)
        return self

    def to_dict(self):
        return {
            "type": "Stream",
            "name": self.name,
            "events": len(self.history),
            "subscribers": len(self.subscribers),
        }


# ---------------------------------------------------------------------------
# Reactive Graph
# ---------------------------------------------------------------------------

class ReactiveGraph:
    """Manages reactive nodes and their dependency relationships."""

    def __init__(self):
        self.nodes = {}
        self.edges = []
        self.propagation_log = []

    def add(self, node):
        self.nodes[node.name] = node
        if hasattr(node, 'deps'):
            for d in node.deps:
                self.edges.append((d.name, node.name))
        return node

    def detect_cycles(self):
        """Detect cycles using DFS coloring."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {n: WHITE for n in self.nodes}
        cycles = []

        def dfs(u, path):
            color[u] = GRAY
            path.append(u)
            adj = [e[1] for e in self.edges if e[0] == u]
            for v in adj:
                if v not in color:
                    continue
                if color[v] == GRAY:
                    idx = path.index(v)
                    cycles.append(path[idx:] + [v])
                elif color[v] == WHITE:
                    dfs(v, path)
            path.pop()
            color[u] = BLACK

        for n in self.nodes:
            if color[n] == WHITE:
                dfs(n, [])
        return cycles

    def topological_order(self):
        """Return nodes in topological order for propagation."""
        in_deg = defaultdict(int)
        for _, t in self.edges:
            in_deg[t] += 1
        q = deque([n for n in self.nodes if in_deg[n] == 0])
        order = []
        while q:
            n = q.popleft()
            order.append(n)
            for s, t in self.edges:
                if s == n:
                    in_deg[t] -= 1
                    if in_deg[t] == 0:
                        q.append(t)
        return order

    def to_dict(self):
        return {
            "nodes": {n: nd.to_dict() for n, nd in self.nodes.items()},
            "edges": self.edges,
            "cycles": self.detect_cycles(),
            "topologicalOrder": self.topological_order(),
        }


# ---------------------------------------------------------------------------
# .srv Analyzer — Detect Reactive Patterns
# ---------------------------------------------------------------------------

class ReflexAnalyzer:
    """Analyzes .srv source code for reactive programming patterns."""

    def __init__(self, source, filename="<input>"):
        self.source = source
        self.filename = filename
        self.lines = source.splitlines()
        self.assignments = defaultdict(list)  # var -> [(line_no, value)]
        self.computations = []  # (line_no, target, deps)
        self.loops = []  # (line_no, body_vars)
        self.callbacks = []  # (line_no, pattern)
        self.suggestions = []
        self.score = 0

    def analyze(self):
        """Run all analysis passes."""
        self._find_assignments()
        self._find_computations()
        self._find_loops()
        self._find_callbacks()
        self._score()
        self._generate_suggestions()
        return self

    def _find_assignments(self):
        """Find variable assignments and track reassignment frequency."""
        assign_re = re.compile(r'^\s*(?:set\s+)?(\w+)\s*=\s*(.+)$')
        for i, line in enumerate(self.lines, 1):
            m = assign_re.match(line)
            if m:
                var, val = m.group(1), m.group(2).strip()
                self.assignments[var].append((i, val))

    def _find_computations(self):
        """Find computations that depend on other variables."""
        comp_re = re.compile(r'^\s*(?:set\s+)?(\w+)\s*=\s*(.+)$')
        for i, line in enumerate(self.lines, 1):
            m = comp_re.match(line)
            if m:
                target = m.group(1)
                expr = m.group(2)
                # Find variable references in the expression
                refs = set(re.findall(r'\b([a-zA-Z_]\w*)\b', expr))
                refs -= {target, 'true', 'false', 'null', 'none', 'and', 'or', 'not',
                         'if', 'else', 'while', 'for', 'return', 'print', 'input',
                         'len', 'str', 'int', 'float', 'list', 'map', 'filter',
                         'set', 'get', 'push', 'pop', 'append'}
                if refs:
                    self.computations.append((i, target, refs))

    def _find_loops(self):
        """Find loops that modify variables (potential reactive streams)."""
        loop_re = re.compile(r'^\s*(while|for|repeat|loop)\b')
        for i, line in enumerate(self.lines, 1):
            if loop_re.match(line):
                # Scan body for variable modifications
                body_vars = set()
                for j in range(i, min(i + 20, len(self.lines))):
                    m = re.match(r'^\s+(?:set\s+)?(\w+)\s*=', self.lines[j - 1] if j > 0 else '')
                    if m:
                        body_vars.add(m.group(1))
                if body_vars:
                    self.loops.append((i, body_vars))

    def _find_callbacks(self):
        """Find callback-like patterns."""
        cb_re = re.compile(r'(on_\w+|callback|handler|listener|subscribe|observe|watch|emit|trigger)', re.I)
        for i, line in enumerate(self.lines, 1):
            m = cb_re.search(line)
            if m:
                self.callbacks.append((i, m.group(1)))

    def _score(self):
        """Calculate reactivity potential score (0-100)."""
        s = 0
        # Reassigned variables (strong signal)
        reassigned = sum(1 for v, assigns in self.assignments.items() if len(assigns) > 1)
        s += min(reassigned * 10, 30)
        # Computed dependencies
        s += min(len(self.computations) * 5, 25)
        # Loops modifying state
        s += min(len(self.loops) * 8, 20)
        # Callback patterns
        s += min(len(self.callbacks) * 7, 15)
        # Multi-dependency computations
        multi_dep = sum(1 for _, _, deps in self.computations if len(deps) >= 2)
        s += min(multi_dep * 5, 10)
        self.score = min(s, 100)

    def _generate_suggestions(self):
        """Generate proactive refactoring suggestions."""
        for var, assigns in self.assignments.items():
            if len(assigns) >= 3:
                lines = [a[0] for a in assigns]
                self.suggestions.append({
                    "type": "reactive_var",
                    "severity": "high" if len(assigns) >= 5 else "medium",
                    "variable": var,
                    "lines": lines,
                    "message": f"'{var}' is reassigned {len(assigns)} times — consider making it a ReactiveVar for automatic propagation",
                })
            elif len(assigns) == 2:
                self.suggestions.append({
                    "type": "reactive_var",
                    "severity": "low",
                    "variable": var,
                    "lines": [a[0] for a in assigns],
                    "message": f"'{var}' is reassigned — could benefit from reactive binding",
                })

        for line, target, deps in self.computations:
            if len(deps) >= 2:
                self.suggestions.append({
                    "type": "computed",
                    "severity": "medium",
                    "variable": target,
                    "deps": sorted(deps),
                    "line": line,
                    "message": f"'{target}' depends on {sorted(deps)} — a Computed reactive would auto-update when inputs change",
                })

        for line, body_vars in self.loops:
            self.suggestions.append({
                "type": "stream",
                "severity": "medium",
                "line": line,
                "variables": sorted(body_vars),
                "message": f"Loop at line {line} modifies {sorted(body_vars)} — consider a reactive Stream for event-driven processing",
            })

        for line, pattern in self.callbacks:
            self.suggestions.append({
                "type": "effect",
                "severity": "low",
                "line": line,
                "pattern": pattern,
                "message": f"Callback pattern '{pattern}' at line {line} — Effect reactive would auto-trigger on dependency changes",
            })

    def build_graph(self):
        """Build a ReactiveGraph from detected patterns."""
        graph = ReactiveGraph()
        # Create reactive vars for reassigned variables
        created = {}
        for var, assigns in self.assignments.items():
            if len(assigns) >= 2:
                rv = ReactiveVar(var, assigns[-1][1])
                graph.add(rv)
                created[var] = rv

        # Create computed nodes
        for line, target, deps in self.computations:
            dep_nodes = [created[d] for d in deps if d in created]
            if dep_nodes and target not in created:
                c = Computed(target, dep_nodes, lambda *args: None)
                graph.add(c)
                created[target] = c

        return graph

    def to_dict(self):
        return {
            "filename": self.filename,
            "score": self.score,
            "scoreLabel": self._score_label(),
            "stats": {
                "totalVariables": len(self.assignments),
                "reassignedVariables": sum(1 for v in self.assignments.values() if len(v) > 1),
                "computations": len(self.computations),
                "loops": len(self.loops),
                "callbackPatterns": len(self.callbacks),
            },
            "suggestions": self.suggestions,
            "graph": self.build_graph().to_dict(),
        }

    def _score_label(self):
        if self.score >= 70: return "High — strong candidate for reactive refactoring"
        if self.score >= 40: return "Medium — some patterns would benefit from reactivity"
        if self.score >= 15: return "Low — minor reactive opportunities"
        return "Minimal — mostly imperative, reactive may not add value"


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def run_demo():
    """Run an interactive reactive programming demo."""
    print("╔═══════════════════════════════════════════════╗")
    print("║     sauravreflex — Reactive Programming Demo  ║")
    print("╚═══════════════════════════════════════════════╝")
    print()

    graph = ReactiveGraph()

    # Create reactive variables
    price = ReactiveVar("price", 100)
    quantity = ReactiveVar("quantity", 5)
    tax_rate = ReactiveVar("tax_rate", 0.08)

    graph.add(price)
    graph.add(quantity)
    graph.add(tax_rate)

    # Computed values
    subtotal = Computed("subtotal", [price, quantity], lambda p, q: p * q)
    tax = Computed("tax", [subtotal, tax_rate], lambda s, t: round(s * t, 2))
    total = Computed("total", [subtotal, tax], lambda s, t: round(s + t, 2))

    graph.add(subtotal)
    graph.add(tax)
    graph.add(total)

    # Effect
    log = []
    effect = Effect("logger", [total], lambda src, vals: log.append(
        f"  [Effect] Total changed via '{src}' → ${vals['total']}"
    ))
    graph.add(effect)

    print("  Dependency Graph:")
    print("    price ──┐")
    print("    quantity ┤→ subtotal ──┐")
    print("    tax_rate ─────────────┤→ tax ──┐")
    print("                          └→ total ←┘")
    print()
    print(f"  Initial: price=${price.value}, qty={quantity.value}, tax={tax_rate.value*100}%")
    print(f"  Subtotal: ${subtotal.value}")
    print(f"  Tax: ${tax.value}")
    print(f"  Total: ${total.value}")
    print()

    # Change price — everything propagates
    print("  ► Setting price = 150...")
    price.value = 150
    for msg in log:
        print(msg)
    log.clear()
    print(f"  Subtotal: ${subtotal.value}, Tax: ${tax.value}, Total: ${total.value}")
    print()

    # Change quantity
    print("  ► Setting quantity = 10...")
    quantity.value = 10
    for msg in log:
        print(msg)
    log.clear()
    print(f"  Subtotal: ${subtotal.value}, Tax: ${tax.value}, Total: ${total.value}")
    print()

    # Stream demo
    print("  ── Stream Demo ──")
    clicks = Stream("clicks")
    filtered = clicks.filter(lambda x: x > 0, "positive_clicks")
    doubled = filtered.map(lambda x: x * 2, "doubled")
    results = []
    doubled.subscribe(lambda v: results.append(v))

    for v in [3, -1, 7, 0, 5]:
        clicks.emit(v)
    print(f"  Input events: [3, -1, 7, 0, 5]")
    print(f"  After filter(>0).map(*2): {results}")
    print()

    # Cycle detection
    cycles = graph.detect_cycles()
    print(f"  Cycles detected: {len(cycles)}")
    print(f"  Topological order: {graph.topological_order()}")
    print()
    print("  ✓ Demo complete!")


# ---------------------------------------------------------------------------
# Terminal Report
# ---------------------------------------------------------------------------

def print_report(analysis):
    """Print a colorful terminal report."""
    d = analysis.to_dict()
    print()
    print("╔═══════════════════════════════════════════════════════╗")
    print("║         sauravreflex — Reactivity Analysis            ║")
    print("╚═══════════════════════════════════════════════════════╝")
    print()
    print(f"  File: {d['filename']}")
    print(f"  Score: {d['score']}/100 — {d['scoreLabel']}")
    print()

    stats = d['stats']
    print("  ── Statistics ──")
    print(f"  Variables:       {stats['totalVariables']}")
    print(f"  Reassigned:      {stats['reassignedVariables']}")
    print(f"  Computations:    {stats['computations']}")
    print(f"  Loops:           {stats['loops']}")
    print(f"  Callback Patterns: {stats['callbackPatterns']}")
    print()

    if d['suggestions']:
        print("  ── Suggestions ──")
        icons = {"high": "🔴", "medium": "🟡", "low": "🔵"}
        for i, s in enumerate(d['suggestions'], 1):
            icon = icons.get(s.get('severity', 'low'), '•')
            print(f"  {icon} [{s['type'].upper()}] {s['message']}")
            if 'lines' in s:
                print(f"     Lines: {s['lines']}")
            elif 'line' in s:
                print(f"     Line: {s['line']}")
        print()

    graph = d['graph']
    if graph['edges']:
        print("  ── Dependency Graph ──")
        for src, tgt in graph['edges']:
            print(f"    {src} → {tgt}")
        print()
        if graph['cycles']:
            print("  ⚠ Cycles detected:")
            for c in graph['cycles']:
                print(f"    {' → '.join(c)}")
            print()
        print(f"  Propagation order: {graph['topologicalOrder']}")
        print()

    print("  ✓ Analysis complete.")
    print()


# ---------------------------------------------------------------------------
# HTML Report
# ---------------------------------------------------------------------------

def generate_html_report(analysis):
    """Generate an interactive HTML dependency graph report."""
    d = analysis.to_dict()
    nodes_js = json.dumps([
        {"id": n, "type": info["type"], "label": n,
         **{k: v for k, v in info.items() if k not in ("type", "name")}}
        for n, info in d["graph"]["nodes"].items()
    ])
    edges_js = json.dumps([{"from": s, "to": t} for s, t in d["graph"]["edges"]])
    suggestions_js = json.dumps(d["suggestions"])

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>sauravreflex — {d['filename']}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh}}
.header{{background:linear-gradient(135deg,#1a1b2e,#16213e);padding:24px 32px;border-bottom:1px solid #30363d}}
.header h1{{font-size:1.6em;color:#58a6ff}}.header .score{{font-size:2.4em;font-weight:700;margin:8px 0}}
.score-high{{color:#f97583}}.score-med{{color:#d29922}}.score-low{{color:#3fb950}}.score-min{{color:#8b949e}}
.container{{display:grid;grid-template-columns:1fr 1fr;gap:20px;padding:20px;max-width:1400px;margin:0 auto}}
.card{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:20px}}
.card h2{{color:#58a6ff;margin-bottom:12px;font-size:1.1em}}
canvas{{width:100%;height:400px;background:#0d1117;border-radius:6px}}
.stat{{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #21262d}}
.stat-val{{color:#58a6ff;font-weight:600}}
.suggestion{{padding:10px;margin:6px 0;border-radius:6px;border-left:3px solid}}
.sug-high{{border-color:#f97583;background:#f9758310}}.sug-medium{{border-color:#d29922;background:#d2992210}}
.sug-low{{border-color:#3fb950;background:#3fb95010}}
.sug-type{{font-size:.75em;text-transform:uppercase;opacity:.7;margin-bottom:4px}}
.full-width{{grid-column:1/-1}}
</style>
</head>
<body>
<div class="header">
<h1>⚡ sauravreflex — Reactivity Analysis</h1>
<div>File: <strong>{d['filename']}</strong></div>
<div class="score {'score-high' if d['score']>=70 else 'score-med' if d['score']>=40 else 'score-low' if d['score']>=15 else 'score-min'}">{d['score']}/100</div>
<div>{d['scoreLabel']}</div>
</div>
<div class="container">
<div class="card">
<h2>📊 Statistics</h2>
<div class="stat"><span>Total Variables</span><span class="stat-val">{d['stats']['totalVariables']}</span></div>
<div class="stat"><span>Reassigned Variables</span><span class="stat-val">{d['stats']['reassignedVariables']}</span></div>
<div class="stat"><span>Computations</span><span class="stat-val">{d['stats']['computations']}</span></div>
<div class="stat"><span>Loops</span><span class="stat-val">{d['stats']['loops']}</span></div>
<div class="stat"><span>Callback Patterns</span><span class="stat-val">{d['stats']['callbackPatterns']}</span></div>
</div>
<div class="card">
<h2>🔗 Dependency Graph</h2>
<canvas id="graphCanvas"></canvas>
</div>
<div class="card full-width">
<h2>💡 Suggestions</h2>
<div id="suggestions"></div>
</div>
</div>
<script>
const nodes={nodes_js};
const edges={edges_js};
const suggestions={suggestions_js};

// Render suggestions
const sugDiv=document.getElementById('suggestions');
suggestions.forEach(s=>{{
const el=document.createElement('div');
el.className='suggestion sug-'+(s.severity||'low');
el.innerHTML='<div class="sug-type">'+s.type+'</div><div>'+s.message+'</div>';
sugDiv.appendChild(el);
}});

// Render graph on canvas
const canvas=document.getElementById('graphCanvas');
const ctx=canvas.getContext('2d');
canvas.width=canvas.offsetWidth*2;canvas.height=800;
ctx.scale(2,2);
const W=canvas.offsetWidth,H=400;

// Position nodes in a force-directed-ish layout
const pos={{}};
const typeColors={{ReactiveVar:'#58a6ff',Computed:'#d29922',Effect:'#f97583',Stream:'#3fb950'}};
nodes.forEach((n,i)=>{{
const angle=(2*Math.PI*i)/nodes.length;
const r=Math.min(W,H)*0.3;
pos[n.id]={{x:W/2+r*Math.cos(angle),y:H/2+r*Math.sin(angle)}};
}});

// Simple force simulation
for(let iter=0;iter<100;iter++){{
nodes.forEach(n=>{{
nodes.forEach(m=>{{
if(n.id===m.id)return;
const dx=pos[n.id].x-pos[m.id].x;
const dy=pos[n.id].y-pos[m.id].y;
const d=Math.sqrt(dx*dx+dy*dy)||1;
const f=800/(d*d);
pos[n.id].x+=dx/d*f;pos[n.id].y+=dy/d*f;
}});
edges.forEach(e=>{{
if(e.from===n.id||e.to===n.id){{
const other=e.from===n.id?e.to:e.from;
if(!pos[other])return;
const dx=pos[other].x-pos[n.id].x;
const dy=pos[other].y-pos[n.id].y;
const d=Math.sqrt(dx*dx+dy*dy)||1;
const f=(d-120)*0.01;
pos[n.id].x+=dx/d*f;pos[n.id].y+=dy/d*f;
}});
}});
// Center gravity
pos[n.id].x+=(W/2-pos[n.id].x)*0.01;
pos[n.id].y+=(H/2-pos[n.id].y)*0.01;
}});
}}

// Draw edges
ctx.strokeStyle='#30363d';ctx.lineWidth=1.5;
edges.forEach(e=>{{
if(!pos[e.from]||!pos[e.to])return;
const f=pos[e.from],t=pos[e.to];
ctx.beginPath();ctx.moveTo(f.x,f.y);ctx.lineTo(t.x,t.y);ctx.stroke();
// Arrow
const angle=Math.atan2(t.y-f.y,t.x-f.x);
const ax=t.x-20*Math.cos(angle),ay=t.y-20*Math.sin(angle);
ctx.beginPath();ctx.moveTo(ax,ay);
ctx.lineTo(ax-8*Math.cos(angle-0.4),ay-8*Math.sin(angle-0.4));
ctx.lineTo(ax-8*Math.cos(angle+0.4),ay-8*Math.sin(angle+0.4));
ctx.fillStyle='#30363d';ctx.fill();
}});

// Draw nodes
nodes.forEach(n=>{{
if(!pos[n.id])return;
const p=pos[n.id];
const col=typeColors[n.type]||'#8b949e';
ctx.beginPath();ctx.arc(p.x,p.y,16,0,Math.PI*2);
ctx.fillStyle=col+'30';ctx.fill();
ctx.strokeStyle=col;ctx.lineWidth=2;ctx.stroke();
ctx.fillStyle='#c9d1d9';ctx.font='11px system-ui';ctx.textAlign='center';
ctx.fillText(n.id,p.x,p.y+30);
ctx.fillStyle=col;ctx.font='bold 9px system-ui';
ctx.fillText(n.type,p.x,p.y+4);
}});
</script>
</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# Playground
# ---------------------------------------------------------------------------

def generate_playground():
    """Generate interactive reactive playground HTML."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>sauravreflex — Reactive Playground</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh;display:flex;flex-direction:column}
.toolbar{background:#161b22;padding:12px 20px;display:flex;gap:10px;border-bottom:1px solid #30363d;flex-wrap:wrap;align-items:center}
.toolbar button{background:#21262d;color:#c9d1d9;border:1px solid #30363d;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:.85em}
.toolbar button:hover{background:#30363d}.toolbar button.primary{background:#238636;border-color:#2ea043}
.toolbar button.primary:hover{background:#2ea043}
.toolbar h1{color:#58a6ff;font-size:1.1em;margin-right:auto}
.main{display:flex;flex:1;overflow:hidden}
.panel{flex:1;padding:16px;overflow-y:auto}
.panel-left{border-right:1px solid #30363d;max-width:400px}
.node-card{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:12px;margin:8px 0}
.node-card h3{font-size:.9em;color:#58a6ff;margin-bottom:6px}
.node-card input{background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:4px 8px;border-radius:4px;width:100%}
.node-card .type{font-size:.7em;text-transform:uppercase;opacity:.6}
canvas{width:100%;height:100%;background:#0d1117}
.log{background:#161b22;border-top:1px solid #30363d;padding:10px 20px;max-height:150px;overflow-y:auto;font-family:monospace;font-size:.8em}
.log-entry{padding:2px 0;border-bottom:1px solid #21262d}
.log-entry .time{color:#8b949e}.log-entry .event{color:#3fb950}
</style>
</head>
<body>
<div class="toolbar">
<h1>⚡ Reactive Playground</h1>
<button class="primary" onclick="addVar()">+ Variable</button>
<button onclick="addComputed()">+ Computed</button>
<button onclick="resetAll()">Reset</button>
<button onclick="runDemo()">Load Demo</button>
</div>
<div class="main">
<div class="panel panel-left" id="nodePanel"></div>
<div class="panel"><canvas id="canvas"></canvas></div>
</div>
<div class="log" id="log"></div>
<script>
let vars={},computeds={},edges=[],logEntries=[];
let nextId=1;

function log(msg){
const t=new Date().toLocaleTimeString();
logEntries.unshift({time:t,msg});
if(logEntries.length>50)logEntries.pop();
renderLog();
}

function renderLog(){
const el=document.getElementById('log');
el.innerHTML=logEntries.map(e=>'<div class="log-entry"><span class="time">'+e.time+'</span> <span class="event">'+e.msg+'</span></div>').join('');
}

function addVar(name,val){
const id='v'+(nextId++);
name=name||prompt('Variable name:','var'+id);
if(!name)return;
val=val!==undefined?val:0;
vars[id]={name,value:val,dependents:[]};
log('Created ReactiveVar: '+name+' = '+val);
render();return id;
}

function addComputed(){
const name=prompt('Computed name:');if(!name)return;
const depNames=prompt('Dependencies (comma-separated var names):');if(!depNames)return;
const deps=depNames.split(',').map(s=>s.trim());
const expr=prompt('Expression (use dep names):','');if(expr===null)return;
const id='c'+(nextId++);
computeds[id]={name,deps,expr,value:null};
deps.forEach(dn=>{
const vid=Object.keys(vars).find(k=>vars[k].name===dn);
if(vid){vars[vid].dependents.push(id);edges.push({from:vid,to:id});}
});
recompute(id);
log('Created Computed: '+name+' = '+expr);
render();
}

function recompute(cid){
const c=computeds[cid];
try{
const scope={};
Object.values(vars).forEach(v=>scope[v.name]=v.value);
Object.values(computeds).forEach(v=>scope[v.name]=v.value);
c.value=new Function(...Object.keys(scope),'return '+c.expr)(...Object.values(scope));
}catch(e){c.value='ERROR';}
}

function setVar(vid,val){
vars[vid].value=Number(val)||0;
log(vars[vid].name+' → '+vars[vid].value);
// Propagate
vars[vid].dependents.forEach(cid=>{recompute(cid);log('  ↳ '+computeds[cid].name+' recomputed → '+computeds[cid].value);});
render();
}

function resetAll(){vars={};computeds={};edges=[];nextId=1;logEntries=[];render();renderLog();}

function runDemo(){
resetAll();
const p=addVar('price',100);const q=addVar('quantity',5);const t=addVar('taxRate',0.08);
const sid='c'+(nextId++);
computeds[sid]={name:'subtotal',deps:['price','quantity'],expr:'price*quantity',value:500};
vars[p].dependents.push(sid);vars[q].dependents.push(sid);
edges.push({from:p,to:sid},{from:q,to:sid});
const tid='c'+(nextId++);
computeds[tid]={name:'total',deps:['subtotal','taxRate'],expr:'subtotal*(1+taxRate)',value:540};
edges.push({from:sid,to:tid});
vars[t].dependents.push(tid);edges.push({from:t,to:tid});
recompute(sid);recompute(tid);
log('Demo loaded: price/quantity → subtotal → total');
render();
}

function render(){
const panel=document.getElementById('nodePanel');
let h='';
Object.entries(vars).forEach(([id,v])=>{
h+='<div class="node-card"><div class="type">ReactiveVar</div><h3>'+v.name+'</h3>';
h+='<input type="number" value="'+v.value+'" onchange="setVar(\\''+id+'\\',this.value)"></div>';
});
Object.entries(computeds).forEach(([id,c])=>{
h+='<div class="node-card"><div class="type">Computed</div><h3>'+c.name+'</h3>';
h+='<div>= '+c.expr+'</div><div style="color:#58a6ff;font-size:1.2em;margin-top:4px">'+c.value+'</div></div>';
});
panel.innerHTML=h;
drawGraph();
}

function drawGraph(){
const canvas=document.getElementById('canvas');
const ctx=canvas.getContext('2d');
canvas.width=canvas.offsetWidth*2;canvas.height=canvas.offsetHeight*2;
ctx.scale(2,2);
const W=canvas.offsetWidth,H=canvas.offsetHeight;
const allNodes=[...Object.entries(vars).map(([id,v])=>({id,label:v.name,type:'var',val:v.value})),
...Object.entries(computeds).map(([id,c])=>({id,label:c.name,type:'computed',val:c.value}))];
const pos={};
allNodes.forEach((n,i)=>{
const angle=(2*Math.PI*i)/allNodes.length;
const r=Math.min(W,H)*0.3;
pos[n.id]={x:W/2+r*Math.cos(angle-Math.PI/2),y:H/2+r*Math.sin(angle-Math.PI/2)};
});
// Edges
ctx.strokeStyle='#30363d';ctx.lineWidth=1.5;
edges.forEach(e=>{
if(!pos[e.from]||!pos[e.to])return;
ctx.beginPath();ctx.moveTo(pos[e.from].x,pos[e.from].y);ctx.lineTo(pos[e.to].x,pos[e.to].y);ctx.stroke();
});
// Nodes
allNodes.forEach(n=>{
if(!pos[n.id])return;
const p=pos[n.id],col=n.type==='var'?'#58a6ff':'#d29922';
ctx.beginPath();ctx.arc(p.x,p.y,22,0,Math.PI*2);ctx.fillStyle=col+'20';ctx.fill();
ctx.strokeStyle=col;ctx.lineWidth=2;ctx.stroke();
ctx.fillStyle='#c9d1d9';ctx.font='bold 11px system-ui';ctx.textAlign='center';
ctx.fillText(n.label,p.x,p.y-2);
ctx.font='10px system-ui';ctx.fillStyle=col;ctx.fillText(String(n.val),p.x,p.y+12);
});
}

render();
</script>
</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# Watch Mode
# ---------------------------------------------------------------------------

def watch_mode(filepath):
    """Watch a file and re-analyze on change."""
    print(f"  👁 Watching {filepath} for changes... (Ctrl+C to stop)")
    last_hash = None
    while True:
        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            h = hashlib.md5(content.encode()).hexdigest()
            if h != last_hash:
                last_hash = h
                if last_hash is not None:
                    os.system('cls' if os.name == 'nt' else 'clear')
                analysis = ReflexAnalyzer(content, filepath).analyze()
                print_report(analysis)
                print(f"  👁 Watching for changes... (last: {datetime.now().strftime('%H:%M:%S')})")
            time.sleep(1)
        except KeyboardInterrupt:
            print("\n  ✓ Watch stopped.")
            break
        except Exception as e:
            print(f"  ✗ Error: {e}")
            time.sleep(2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog='sauravreflex',
        description='Autonomous Reactive Programming Engine for sauravcode',
    )
    parser.add_argument('file', nargs='?', help='Input .srv file to analyze')
    parser.add_argument('--demo', action='store_true', help='Run built-in reactive demo')
    parser.add_argument('--report', action='store_true', help='Generate HTML dependency graph report')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--watch', action='store_true', help='Auto-monitor mode')
    parser.add_argument('--playground', action='store_true', help='Generate interactive playground HTML')

    args = parser.parse_args()

    if args.playground:
        out = "reflex_playground.html"
        with open(out, 'w', encoding='utf-8') as f:
            f.write(generate_playground())
        print(f"  ✓ Playground saved to {out}")
        return

    if args.demo:
        run_demo()
        return

    if not args.file:
        parser.print_help()
        sys.exit(1)

    if not os.path.exists(args.file):
        print(f"  ✗ File not found: {args.file}")
        sys.exit(1)

    with open(args.file, 'r', encoding='utf-8', errors='replace') as f:
        source = f.read()

    analysis = ReflexAnalyzer(source, args.file).analyze()

    if args.watch:
        watch_mode(args.file)
        return

    if args.json:
        print(json.dumps(analysis.to_dict(), indent=2))
        return

    if args.report:
        out = os.path.splitext(args.file)[0] + "_reflex.html"
        with open(out, 'w', encoding='utf-8') as f:
            f.write(generate_html_report(analysis))
        print(f"  ✓ Report saved to {out}")
        return

    print_report(analysis)


if __name__ == '__main__':
    main()
