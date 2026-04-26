#!/usr/bin/env python3
"""sauravchrono — Time-travel execution recorder & anomaly detector for sauravcode.

Records full execution snapshots at every step, enabling forward/backward
navigation through program history.  Proactively detects anomalies:
mutation storms, type instability, infinite-loop risk, dead variables,
and suspiciously hot lines.

Usage:
    python sauravchrono.py FILE.srv                    # record & interactive replay
    python sauravchrono.py FILE.srv --report           # run & print anomaly report
    python sauravchrono.py FILE.srv --report --html    # HTML anomaly dashboard
    python sauravchrono.py FILE.srv --json             # dump full timeline as JSON
    python sauravchrono.py FILE.srv --limit 5000       # cap recorded steps
    python sauravchrono.py FILE.srv -o timeline.json   # save timeline to file
"""

import argparse
import copy
import json
import os
import sys
import time
import html as _html
from collections import Counter, defaultdict
from io import StringIO

__version__ = "1.0.0"

# ── Import interpreter machinery ──────────────────────────────────
_script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _script_dir)

from saurav import (
    tokenize, Parser, Interpreter,
    FunctionNode, FunctionCallNode, AssignmentNode, PrintNode,
    ReturnNode, IfNode, WhileNode, ForNode, ForEachNode,
    TryCatchNode, ThrowNode, MatchNode, ImportNode, BreakNode,
    ContinueNode, YieldNode, IndexedAssignmentNode, AppendNode,
    PopNode, EnumNode, AssertNode, ThrowSignal,
)


# ── Snapshot ──────────────────────────────────────────────────────

def _safe_copy(env):
    """Shallow-copy env dict, converting non-serializable values to repr."""
    out = {}
    for k, v in env.items():
        if callable(v) or isinstance(v, type):
            continue
        try:
            json.dumps(v)
            out[k] = v
        except (TypeError, ValueError):
            out[k] = repr(v)
    return out


class Snapshot:
    """One moment in execution time."""
    __slots__ = ('step', 'line', 'kind', 'detail', 'variables', 'depth', 'ts')

    def __init__(self, step, line, kind, detail, variables, depth):
        self.step = step
        self.line = line
        self.kind = kind
        self.detail = detail
        self.variables = variables  # dict snapshot
        self.depth = depth
        self.ts = time.monotonic_ns()

    def to_dict(self):
        return {
            'step': self.step,
            'line': self.line,
            'kind': self.kind,
            'detail': self.detail,
            'variables': self.variables,
            'depth': self.depth,
        }


# ── Chrono Recorder ──────────────────────────────────────────────

class ChronoRecorder:
    """Wraps the sauravcode interpreter, recording every execution step."""

    def __init__(self, source, *, limit=10000, capture_vars=True):
        self.source = source
        self.lines = source.splitlines()
        self.limit = limit
        self.capture_vars = capture_vars
        self.timeline = []       # list[Snapshot]
        self._step = 0
        self._depth = 0
        self._line_hits = Counter()
        self._var_types = defaultdict(list)   # var -> list of type names
        self._var_mutations = Counter()       # var -> mutation count

    def _record(self, line, kind, detail, env):
        if self._step >= self.limit:
            return
        variables = _safe_copy(env) if self.capture_vars else {}
        snap = Snapshot(self._step, line, kind, detail, variables, self._depth)
        self.timeline.append(snap)
        if line is not None:
            self._line_hits[line] += 1
        # Track variable types & mutations
        for k, v in variables.items():
            tname = type(v).__name__
            hist = self._var_types[k]
            if not hist or hist[-1] != tname:
                self._var_types[k].append(tname)
            self._var_mutations[k] += 1
        self._step += 1

    def _get_line(self, node):
        return getattr(node, 'line', None)

    def run(self):
        """Execute the program while recording via monkey-patched interpreter."""
        tokens = tokenize(self.source)
        parser = Parser(tokens)
        ast_nodes = parser.parse()
        interp = Interpreter()
        recorder = self

        # Monkey-patch interpret to record every node execution
        _orig_interpret = interp.interpret

        def _hooked_interpret(ast):
            if recorder._step < recorder.limit:
                line = getattr(ast, 'line', None) or getattr(ast, 'line_num', None)
                kind = type(ast).__name__
                detail = _describe(ast, recorder.lines)
                # Gather variables snapshot
                env = dict(interp.variables)
                recorder._record(line, kind, detail, env)
                if isinstance(ast, FunctionCallNode):
                    recorder._depth += 1
            try:
                return _orig_interpret(ast)
            finally:
                if isinstance(ast, FunctionCallNode):
                    recorder._depth = max(0, recorder._depth - 1)

        interp.interpret = _hooked_interpret

        # Capture print output
        buf = StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            for node in ast_nodes:
                interp.interpret(node)
        except (ThrowSignal, Exception):
            pass
        finally:
            sys.stdout = old_stdout

        self.output = buf.getvalue()
        return self


def _describe(node, lines):
    """Human-readable one-liner for a node."""
    line = getattr(node, 'line', None)
    if line is not None and 0 < line <= len(lines):
        return lines[line - 1].strip()[:80]
    return type(node).__name__


# ── Anomaly Detection ────────────────────────────────────────────

class AnomalyDetector:
    """Proactively scans a ChronoRecorder's timeline for anomalies."""

    def __init__(self, recorder):
        self.rec = recorder

    def detect(self):
        anomalies = []
        anomalies.extend(self._hot_lines())
        anomalies.extend(self._mutation_storms())
        anomalies.extend(self._type_instability())
        anomalies.extend(self._loop_risk())
        anomalies.extend(self._dead_variables())
        return anomalies

    def _hot_lines(self, threshold=50):
        """Lines executed suspiciously many times."""
        out = []
        for line, count in self.rec._line_hits.most_common(5):
            if count >= threshold:
                src = self.rec.lines[line - 1].strip() if line <= len(self.rec.lines) else '?'
                out.append({
                    'type': 'hot_line',
                    'severity': 'warning' if count < 200 else 'critical',
                    'line': line,
                    'hits': count,
                    'source': src,
                    'message': f'Line {line} executed {count} times — possible infinite loop',
                })
        return out

    def _mutation_storms(self, threshold=30):
        """Variables mutated an unusual number of times."""
        out = []
        for var, count in self.rec._var_mutations.most_common(5):
            if count >= threshold:
                out.append({
                    'type': 'mutation_storm',
                    'severity': 'warning',
                    'variable': var,
                    'mutations': count,
                    'message': f'Variable "{var}" mutated {count} times — consider refactoring',
                })
        return out

    def _type_instability(self):
        """Variables that changed type during execution."""
        out = []
        for var, types in self.rec._var_types.items():
            unique = list(dict.fromkeys(types))
            if len(unique) >= 3:
                out.append({
                    'type': 'type_instability',
                    'severity': 'warning',
                    'variable': var,
                    'types': unique,
                    'message': f'Variable "{var}" changed type {len(unique)} times: {" → ".join(unique)}',
                })
        return out

    def _loop_risk(self):
        """Detect potential infinite loops via line repetition patterns."""
        out = []
        if not self.rec.timeline:
            return out
        # Look for repeating line patterns in last 200 steps
        recent = [s.line for s in self.rec.timeline[-200:] if s.line is not None]
        if len(recent) < 20:
            return out
        # Check for short cycles
        for cycle_len in range(2, 8):
            segment = recent[-cycle_len * 3:]
            if len(segment) >= cycle_len * 3:
                pattern = segment[:cycle_len]
                repeats = 0
                for i in range(0, len(segment) - cycle_len + 1, cycle_len):
                    if segment[i:i + cycle_len] == pattern:
                        repeats += 1
                if repeats >= 3:
                    out.append({
                        'type': 'loop_risk',
                        'severity': 'critical',
                        'cycle_length': cycle_len,
                        'pattern_lines': pattern,
                        'message': f'Repeating {cycle_len}-line cycle detected (lines {pattern}) — infinite loop likely',
                    })
                    break
        return out

    def _dead_variables(self):
        """Variables assigned but never read (heuristic: assigned in early steps, absent later)."""
        out = []
        if len(self.rec.timeline) < 10:
            return out
        early_vars = set()
        for s in self.rec.timeline[:len(self.rec.timeline) // 3]:
            early_vars.update(s.variables.keys())
        late_vars = set()
        for s in self.rec.timeline[-len(self.rec.timeline) // 3:]:
            late_vars.update(s.variables.keys())
        dead = early_vars - late_vars
        for var in sorted(dead):
            if var.startswith('_'):
                continue
            out.append({
                'type': 'dead_variable',
                'severity': 'info',
                'variable': var,
                'message': f'Variable "{var}" appears early but disappears — possibly unused',
            })
        return out


# ── Interactive Replay ───────────────────────────────────────────

def interactive_replay(recorder):
    """REPL for navigating the recorded timeline."""
    timeline = recorder.timeline
    if not timeline:
        print("No execution steps recorded.")
        return

    pos = 0
    total = len(timeline)

    def _show(idx):
        s = timeline[idx]
        line_info = f"L{s.line}" if s.line else "?"
        indent = "  " * s.depth
        print(f"\n[Step {s.step}/{total - 1}] {line_info} {indent}{s.kind}: {s.detail}")
        if s.variables:
            for k, v in sorted(s.variables.items()):
                vstr = repr(v) if not isinstance(v, str) else v
                if len(vstr) > 60:
                    vstr = vstr[:57] + "..."
                print(f"  {k} = {vstr}")

    print(f"\n  sauravchrono -- Time-Travel Debugger ({total} snapshots)")
    print("Commands: n/next  p/prev  g <N>/goto  f/first  l/last  find <var>  anomalies  q/quit\n")
    _show(pos)

    while True:
        try:
            cmd = input("\nchrono> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not cmd:
            continue
        parts = cmd.split(None, 1)
        verb = parts[0].lower()

        if verb in ('q', 'quit', 'exit'):
            break
        elif verb in ('n', 'next'):
            if pos < total - 1:
                pos += 1
            else:
                print("(end of timeline)")
            _show(pos)
        elif verb in ('p', 'prev', 'b', 'back'):
            if pos > 0:
                pos -= 1
            else:
                print("(start of timeline)")
            _show(pos)
        elif verb in ('f', 'first'):
            pos = 0
            _show(pos)
        elif verb in ('l', 'last'):
            pos = total - 1
            _show(pos)
        elif verb in ('g', 'goto') and len(parts) > 1:
            try:
                target = int(parts[1])
                if 0 <= target < total:
                    pos = target
                    _show(pos)
                else:
                    print(f"Step must be 0-{total - 1}")
            except ValueError:
                print("Usage: g <step_number>")
        elif verb == 'find' and len(parts) > 1:
            var_name = parts[1]
            found = False
            for i in range(pos + 1, total):
                if var_name in timeline[i].variables:
                    pos = i
                    _show(pos)
                    found = True
                    break
            if not found:
                print(f'Variable "{var_name}" not found after step {pos}')
        elif verb == 'diff':
            if pos > 0:
                prev_vars = timeline[pos - 1].variables
                curr_vars = timeline[pos].variables
                changed = []
                for k in set(prev_vars) | set(curr_vars):
                    old = prev_vars.get(k)
                    new = curr_vars.get(k)
                    if old != new:
                        changed.append((k, old, new))
                if changed:
                    print("Changes from previous step:")
                    for k, old, new in sorted(changed):
                        print(f"  {k}: {repr(old)} → {repr(new)}")
                else:
                    print("No variable changes.")
            else:
                print("No previous step to diff against.")
        elif verb == 'anomalies':
            anomalies = AnomalyDetector(recorder).detect()
            if not anomalies:
                print("[OK] No anomalies detected!")
            else:
                for a in anomalies:
                    icon = {'critical': '[!!]', 'warning': '[!]', 'info': '[i]'}.get(a['severity'], '?')
                    print(f"  {icon} [{a['type']}] {a['message']}")
        elif verb == 'help':
            print("Commands: n/next  p/prev  g <N>/goto  f/first  l/last  find <var>  diff  anomalies  q/quit")
        else:
            print(f"Unknown command: {verb}  (type 'help')")


# ── Report Generators ────────────────────────────────────────────

def text_report(recorder, anomalies):
    """Print a text anomaly report."""
    total = len(recorder.timeline)
    print(f"\n{'='*60}")
    print("  sauravchrono -- Execution Report")
    print(f"{'='*60}")
    print(f"Total steps recorded: {total}")
    print(f"Unique lines hit: {len(recorder._line_hits)}")
    print(f"Variables tracked: {len(recorder._var_types)}")

    if recorder._line_hits:
        top = recorder._line_hits.most_common(5)
        print(f"\nHottest lines:")
        for line, count in top:
            src = recorder.lines[line - 1].strip() if line <= len(recorder.lines) else '?'
            print(f"  L{line} ({count}x): {src[:60]}")

    print(f"\nAnomalies: {len(anomalies)}")
    if not anomalies:
        print("  [OK] No anomalies detected -- program looks healthy!")
    else:
        for a in anomalies:
            icon = {'critical': '[!!]', 'warning': '[!]', 'info': '[i]'}.get(a['severity'], '?')
            print(f"  {icon} [{a['type']}] {a['message']}")
    print()


def html_report(recorder, anomalies, filepath=None):
    """Generate an interactive HTML anomaly dashboard."""
    total = len(recorder.timeline)
    top_lines = recorder._line_hits.most_common(10)
    e = _html.escape

    anomaly_rows = ""
    for a in anomalies:
        color = {'critical': '#e74c3c', 'warning': '#f39c12', 'info': '#3498db'}.get(a['severity'], '#999')
        anomaly_rows += f'<tr><td style="color:{color};font-weight:bold">{e(a["severity"].upper())}</td><td>{e(a["type"])}</td><td>{e(a["message"])}</td></tr>\n'

    hotline_rows = ""
    for line, count in top_lines:
        src = recorder.lines[line - 1].strip() if line <= len(recorder.lines) else '?'
        pct = (count / total * 100) if total else 0
        hotline_rows += f'<tr><td>{line}</td><td>{count}</td><td>{pct:.1f}%</td><td><code>{e(src[:80])}</code></td></tr>\n'

    # Timeline chart data (line numbers over time, sampled)
    sample_step = max(1, total // 200)
    chart_data = []
    for i in range(0, total, sample_step):
        s = recorder.timeline[i]
        if s.line is not None:
            chart_data.append({'x': s.step, 'y': s.line})

    content = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>sauravchrono — Execution Report</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0d1117; color: #c9d1d9; padding: 2rem; }}
  h1 {{ color: #58a6ff; margin-bottom: 0.5rem; }}
  .subtitle {{ color: #8b949e; margin-bottom: 2rem; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 2rem; }}
  .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 1.5rem; }}
  .card .num {{ font-size: 2rem; font-weight: bold; color: #58a6ff; }}
  .card .label {{ color: #8b949e; font-size: 0.85rem; margin-top: 0.3rem; }}
  table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; }}
  th, td {{ text-align: left; padding: 0.6rem 0.8rem; border-bottom: 1px solid #21262d; }}
  th {{ color: #8b949e; font-size: 0.8rem; text-transform: uppercase; }}
  canvas {{ width: 100%; height: 200px; background: #161b22; border-radius: 8px; border: 1px solid #30363d; }}
  .section {{ margin: 2rem 0; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: bold; }}
  .ok {{ background: #238636; color: #fff; }}
  .warn {{ background: #9e6a03; color: #fff; }}
  .crit {{ background: #da3633; color: #fff; }}
</style></head><body>
<h1>⏱ sauravchrono</h1>
<p class="subtitle">Time-Travel Execution Report</p>
<div class="grid">
  <div class="card"><div class="num">{total}</div><div class="label">Execution Steps</div></div>
  <div class="card"><div class="num">{len(recorder._line_hits)}</div><div class="label">Unique Lines Hit</div></div>
  <div class="card"><div class="num">{len(recorder._var_types)}</div><div class="label">Variables Tracked</div></div>
  <div class="card"><div class="num">{len(anomalies)}</div><div class="label">Anomalies</div></div>
</div>

<div class="section">
<h2>🔍 Anomalies</h2>
{"<p style='color:#3fb950;margin:1rem 0'>✅ No anomalies — program looks healthy!</p>" if not anomalies else f"<table><tr><th>Severity</th><th>Type</th><th>Details</th></tr>{anomaly_rows}</table>"}
</div>

<div class="section">
<h2>🔥 Hottest Lines</h2>
<table><tr><th>Line</th><th>Hits</th><th>% of Total</th><th>Source</th></tr>
{hotline_rows}</table>
</div>

<div class="section">
<h2>📈 Execution Timeline</h2>
<canvas id="chart"></canvas>
</div>

<script>
const data = {json.dumps(chart_data)};
const canvas = document.getElementById('chart');
const ctx = canvas.getContext('2d');
function draw() {{
  canvas.width = canvas.offsetWidth; canvas.height = 200;
  if (!data.length) return;
  const maxX = Math.max(...data.map(d=>d.x));
  const maxY = Math.max(...data.map(d=>d.y));
  ctx.strokeStyle = '#58a6ff'; ctx.lineWidth = 1.5; ctx.beginPath();
  data.forEach((d,i) => {{
    const x = (d.x/maxX) * (canvas.width-40) + 20;
    const y = canvas.height - 20 - (d.y/maxY) * (canvas.height-40);
    i===0 ? ctx.moveTo(x,y) : ctx.lineTo(x,y);
  }});
  ctx.stroke();
  ctx.fillStyle='#8b949e'; ctx.font='11px sans-serif';
  ctx.fillText('Step →', canvas.width-50, canvas.height-4);
  ctx.fillText('Line ↑', 2, 14);
}}
draw(); window.onresize=draw;
</script>
</body></html>"""

    if filepath:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"HTML report saved to {filepath}")
    return content


# ── CLI ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog='sauravchrono',
        description='Time-travel execution recorder & anomaly detector for sauravcode',
    )
    parser.add_argument('file', help='.srv file to execute and record')
    parser.add_argument('--report', action='store_true', help='Print anomaly report instead of interactive replay')
    parser.add_argument('--html', action='store_true', help='Generate HTML dashboard (use with --report)')
    parser.add_argument('--json', action='store_true', help='Dump full timeline as JSON')
    parser.add_argument('--limit', type=int, default=10000, help='Max steps to record (default: 10000)')
    parser.add_argument('-o', '--output', help='Write output to file')
    parser.add_argument('--version', action='version', version=f'sauravchrono {__version__}')
    args = parser.parse_args()

    if not os.path.isfile(args.file):
        print(f"Error: file not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    with open(args.file, 'r', encoding='utf-8') as f:
        source = f.read()

    recorder = ChronoRecorder(source, limit=args.limit)
    recorder.run()

    if args.json:
        data = {
            'file': args.file,
            'steps': len(recorder.timeline),
            'anomalies': AnomalyDetector(recorder).detect(),
            'timeline': [s.to_dict() for s in recorder.timeline],
        }
        out = json.dumps(data, indent=2)
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(out)
            print(f"Timeline saved to {args.output}")
        else:
            print(out)
    elif args.report:
        anomalies = AnomalyDetector(recorder).detect()
        text_report(recorder, anomalies)
        if args.html:
            outpath = args.output or args.file.replace('.srv', '') + '-chrono-report.html'
            html_report(recorder, anomalies, outpath)
    else:
        interactive_replay(recorder)


if __name__ == '__main__':
    main()
