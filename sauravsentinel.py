#!/usr/bin/env python3
"""
sauravsentinel — Autonomous Project Health Sentinel for sauravcode.

Continuously monitors .srv project health over time, detects regressions,
tracks trends, and generates interactive HTML dashboards with proactive
alerts and improvement recommendations.

Unlike sauravdigest (single snapshot), sentinel maintains a historical
health timeline and autonomously detects when things get worse.

Usage:
    python sauravsentinel.py                        # Scan + record snapshot
    python sauravsentinel.py path/to/project        # Scan specific directory
    python sauravsentinel.py --report               # Show trend report
    python sauravsentinel.py --html dash.html       # Interactive HTML dashboard
    python sauravsentinel.py --alerts               # Show only regressions/alerts
    python sauravsentinel.py --reset                # Clear history
    python sauravsentinel.py --watch                # Continuous monitoring mode
    python sauravsentinel.py --budget 50            # Set complexity budget (alert if exceeded)
    python sauravsentinel.py --goals                # Show/set improvement goals
    python sauravsentinel.py --set-goal health 85   # Set health target
"""

import sys
import os
import re
import json
import math
import time as _time
import glob
import hashlib
from collections import defaultdict, Counter
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Ensure UTF-8 output on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ── Data Structures ───────────────────────────────────────────────────

HISTORY_FILE = ".sentinel-history.json"
GOALS_FILE = ".sentinel-goals.json"

@dataclass
class FileSnapshot:
    path: str
    lines: int = 0
    code_lines: int = 0
    comment_lines: int = 0
    functions: int = 0
    max_nesting: int = 0
    complexity: float = 0.0
    lint_warnings: int = 0
    lint_errors: int = 0
    file_hash: str = ""

@dataclass
class ProjectSnapshot:
    timestamp: str = ""
    directory: str = ""
    total_files: int = 0
    total_lines: int = 0
    total_code_lines: int = 0
    total_functions: int = 0
    avg_complexity: float = 0.0
    max_complexity: float = 0.0
    health_score: float = 0.0
    lint_warnings: int = 0
    lint_errors: int = 0
    comment_ratio: float = 0.0
    files: List[dict] = field(default_factory=list)
    alerts: List[dict] = field(default_factory=list)

# ── Scanning ──────────────────────────────────────────────────────────

def scan_file(path: str) -> FileSnapshot:
    """Analyze a single .srv file."""
    snap = FileSnapshot(path=path)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
            raw_lines = content.splitlines()
    except Exception:
        return snap

    snap.lines = len(raw_lines)
    snap.file_hash = hashlib.md5(content.encode()).hexdigest()[:12]

    nesting = 0
    max_nest = 0
    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("//") or stripped.startswith("#"):
            snap.comment_lines += 1
            continue
        snap.code_lines += 1

        # Function detection
        if re.match(r"^(func|function|def|fn)\s+\w+", stripped):
            snap.functions += 1

        # Nesting tracking
        opens = stripped.count("{") + (1 if re.match(r"^(if|for|while|loop|match)\b", stripped) and "{" not in stripped else 0)
        closes = stripped.count("}")
        nesting += opens - closes
        if nesting > max_nest:
            max_nest = nesting

    snap.max_nesting = max_nest

    # Complexity: weighted combo of lines, nesting, function count
    snap.complexity = round(
        (snap.code_lines * 0.1) +
        (snap.max_nesting * 5.0) +
        (max(0, snap.code_lines - 100) * 0.2),
        2
    )

    # Quick lint check (inline, no external deps)
    snap.lint_warnings = _quick_lint(raw_lines)

    return snap


def _quick_lint(lines: list) -> int:
    """Fast inline lint checks - returns warning count."""
    warnings = 0
    for i, line in enumerate(lines):
        # Trailing whitespace
        if line != line.rstrip():
            warnings += 1
        # Very long lines
        if len(line) > 120:
            warnings += 1
        # TODO/FIXME/HACK markers
        if re.search(r"\b(TODO|FIXME|HACK|XXX)\b", line, re.IGNORECASE):
            warnings += 1
    # Missing final newline
    if lines and lines[-1].strip():
        warnings += 1
    return warnings


def scan_project(directory: str) -> ProjectSnapshot:
    """Scan all .srv files and produce a snapshot."""
    snap = ProjectSnapshot(
        timestamp=datetime.now().isoformat(),
        directory=os.path.abspath(directory),
    )

    srv_files = sorted(glob.glob(os.path.join(directory, "**", "*.srv"), recursive=True))
    if not srv_files:
        # Also check root-level
        srv_files = sorted(glob.glob(os.path.join(directory, "*.srv")))

    total_comment_lines = 0
    for path in srv_files:
        fs = scan_file(path)
        snap.total_files += 1
        snap.total_lines += fs.lines
        snap.total_code_lines += fs.code_lines
        snap.total_functions += fs.functions
        snap.lint_warnings += fs.lint_warnings
        snap.lint_errors += fs.lint_errors
        total_comment_lines += fs.comment_lines
        if fs.complexity > snap.max_complexity:
            snap.max_complexity = fs.complexity
        snap.files.append({
            "path": os.path.relpath(fs.path, directory),
            "lines": fs.lines,
            "code_lines": fs.code_lines,
            "complexity": fs.complexity,
            "functions": fs.functions,
            "max_nesting": fs.max_nesting,
            "lint_warnings": fs.lint_warnings,
            "hash": fs.file_hash,
        })

    if snap.total_files > 0:
        complexities = [f["complexity"] for f in snap.files]
        snap.avg_complexity = round(sum(complexities) / len(complexities), 2)
        snap.comment_ratio = round(total_comment_lines / max(snap.total_lines, 1) * 100, 1)

    # Health score: 0-100
    snap.health_score = _compute_health(snap)

    return snap


def _compute_health(snap: ProjectSnapshot) -> float:
    """Compute project health score (0-100)."""
    if snap.total_files == 0:
        return 0.0

    score = 100.0

    # Penalize high average complexity
    if snap.avg_complexity > 20:
        score -= min(20, (snap.avg_complexity - 20) * 0.5)

    # Penalize high max complexity
    if snap.max_complexity > 50:
        score -= min(15, (snap.max_complexity - 50) * 0.3)

    # Penalize lint warnings per file
    warnings_per_file = snap.lint_warnings / snap.total_files
    if warnings_per_file > 5:
        score -= min(15, (warnings_per_file - 5) * 1.0)

    # Penalize lint errors
    score -= min(20, snap.lint_errors * 5)

    # Reward comment ratio (up to 10 bonus)
    if snap.comment_ratio >= 10:
        score += min(5, snap.comment_ratio * 0.2)

    # Penalize very large files
    large_files = sum(1 for f in snap.files if f["lines"] > 300)
    score -= large_files * 2

    return round(max(0, min(100, score)), 1)


# ── History Management ────────────────────────────────────────────────

def _history_path(directory: str) -> str:
    return os.path.join(directory, HISTORY_FILE)

def load_history(directory: str) -> list:
    path = _history_path(directory)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_history(directory: str, history: list):
    path = _history_path(directory)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(history, f, indent=2)

def snapshot_to_dict(snap: ProjectSnapshot) -> dict:
    return {
        "timestamp": snap.timestamp,
        "total_files": snap.total_files,
        "total_lines": snap.total_lines,
        "total_code_lines": snap.total_code_lines,
        "total_functions": snap.total_functions,
        "avg_complexity": snap.avg_complexity,
        "max_complexity": snap.max_complexity,
        "health_score": snap.health_score,
        "lint_warnings": snap.lint_warnings,
        "lint_errors": snap.lint_errors,
        "comment_ratio": snap.comment_ratio,
        "files": snap.files,
    }


# ── Regression Detection ─────────────────────────────────────────────

def detect_regressions(current: ProjectSnapshot, history: list) -> List[dict]:
    """Compare current snapshot against history to find regressions."""
    alerts = []
    if not history:
        return alerts

    prev = history[-1]

    # Health score drop
    delta_health = current.health_score - prev["health_score"]
    if delta_health < -5:
        alerts.append({
            "severity": "critical" if delta_health < -15 else "warning",
            "type": "health_regression",
            "message": f"Health score dropped {abs(delta_health):.1f} points ({prev['health_score']:.1f} → {current.health_score:.1f})",
            "delta": delta_health,
        })

    # Complexity spike
    if current.avg_complexity > prev.get("avg_complexity", 0) * 1.3 and prev.get("avg_complexity", 0) > 5:
        alerts.append({
            "severity": "warning",
            "type": "complexity_spike",
            "message": f"Average complexity increased 30%+ ({prev['avg_complexity']:.1f} → {current.avg_complexity:.1f})",
        })

    # Lint warning surge
    delta_warnings = current.lint_warnings - prev.get("lint_warnings", 0)
    if delta_warnings > 10:
        alerts.append({
            "severity": "warning",
            "type": "lint_surge",
            "message": f"Lint warnings increased by {delta_warnings} ({prev.get('lint_warnings', 0)} → {current.lint_warnings})",
        })

    # Max complexity blowup
    if current.max_complexity > prev.get("max_complexity", 0) * 1.5 and prev.get("max_complexity", 0) > 10:
        alerts.append({
            "severity": "critical",
            "type": "complexity_blowup",
            "message": f"Max complexity spiked ({prev['max_complexity']:.1f} → {current.max_complexity:.1f})",
        })

    # File-level regressions
    prev_files = {f["path"]: f for f in prev.get("files", [])}
    for f in current.files:
        pf = prev_files.get(f["path"])
        if pf and f["complexity"] > pf["complexity"] * 1.5 and pf["complexity"] > 5:
            alerts.append({
                "severity": "warning",
                "type": "file_regression",
                "message": f"{f['path']}: complexity {pf['complexity']:.1f} → {f['complexity']:.1f}",
            })

    # Trend analysis: 3+ consecutive health drops
    if len(history) >= 3:
        recent = [h["health_score"] for h in history[-3:]] + [current.health_score]
        if all(recent[i] > recent[i+1] for i in range(len(recent)-1)):
            alerts.append({
                "severity": "critical",
                "type": "declining_trend",
                "message": f"Health declining for {len(recent)} consecutive snapshots ({recent[0]:.1f} → {recent[-1]:.1f})",
            })

    return alerts


# ── Goals ─────────────────────────────────────────────────────────────

def load_goals(directory: str) -> dict:
    path = os.path.join(directory, GOALS_FILE)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_goals(directory: str, goals: dict):
    path = os.path.join(directory, GOALS_FILE)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(goals, f, indent=2)

def check_goals(snap: ProjectSnapshot, goals: dict) -> List[dict]:
    """Check if current metrics meet goals."""
    alerts = []
    mapping = {
        "health": snap.health_score,
        "avg_complexity": snap.avg_complexity,
        "max_complexity": snap.max_complexity,
        "lint_warnings": snap.lint_warnings,
    }
    for key, target in goals.items():
        current = mapping.get(key)
        if current is None:
            continue
        if key == "health":
            if current < target:
                alerts.append({
                    "severity": "info",
                    "type": "goal_miss",
                    "message": f"Goal '{key}': target {target}, current {current:.1f} (need +{target - current:.1f})",
                })
        else:
            if current > target:
                alerts.append({
                    "severity": "info",
                    "type": "goal_miss",
                    "message": f"Goal '{key}': target ≤{target}, current {current:.1f} (over by {current - target:.1f})",
                })
    return alerts


# ── Report Formatting ─────────────────────────────────────────────────

def _grade(score: float) -> str:
    if score >= 90: return "A"
    if score >= 80: return "B"
    if score >= 70: return "C"
    if score >= 60: return "D"
    return "F"

def _severity_icon(s: str) -> str:
    return {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(s, "⚪")

def print_report(snap: ProjectSnapshot, history: list, alerts: list, goal_alerts: list):
    """Print a rich terminal report."""
    grade = _grade(snap.health_score)
    bar = "█" * int(snap.health_score / 5) + "░" * (20 - int(snap.health_score / 5))

    print("\n╔══════════════════════════════════════════════════════════════╗")
    print("║           🛡️  SAURAVCODE SENTINEL — PROJECT HEALTH          ║")
    print("╠══════════════════════════════════════════════════════════════╣")
    print(f"║  Directory: {snap.directory[:46]:<46} ║")
    print(f"║  Scanned:   {snap.timestamp[:19]:<46} ║")
    print(f"║  Snapshots: {len(history) + 1:<46} ║")
    print("╠══════════════════════════════════════════════════════════════╣")
    print(f"║  Health: [{bar}] {snap.health_score:5.1f}/100 ({grade})     ║")
    print("╠══════════════════════════════════════════════════════════════╣")
    print(f"║  Files: {snap.total_files:<5}  Lines: {snap.total_lines:<7}  Functions: {snap.total_functions:<5}    ║")
    print(f"║  Avg Complexity: {snap.avg_complexity:<6.1f}  Max: {snap.max_complexity:<6.1f}                ║")
    print(f"║  Lint Warnings: {snap.lint_warnings:<6}  Errors: {snap.lint_errors:<6}                ║")
    print(f"║  Comment Ratio: {snap.comment_ratio:<5.1f}%                                    ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    # Trend
    if history:
        print("\n📈 HEALTH TREND (last 10)")
        recent = history[-9:] + [snapshot_to_dict(snap)]
        for entry in recent:
            ts = entry["timestamp"][:10]
            hs = entry["health_score"]
            bar_len = int(hs / 5)
            print(f"  {ts}  {'█' * bar_len}{'░' * (20 - bar_len)} {hs:5.1f}")

    # Alerts
    if alerts or goal_alerts:
        print("\n🚨 ALERTS")
        for a in alerts + goal_alerts:
            print(f"  {_severity_icon(a['severity'])} [{a['type']}] {a['message']}")
    else:
        print("\n✅ No regressions detected. Project is healthy!")

    # Top complex files
    if snap.files:
        print("\n📊 TOP COMPLEX FILES")
        sorted_files = sorted(snap.files, key=lambda x: x["complexity"], reverse=True)[:5]
        for f in sorted_files:
            print(f"  {f['complexity']:6.1f}  {f['path']} ({f['lines']} lines, depth {f['max_nesting']})")

    # Recommendations
    recs = _generate_recommendations(snap, alerts)
    if recs:
        print("\n💡 RECOMMENDATIONS")
        for i, r in enumerate(recs, 1):
            print(f"  {i}. {r}")

    print()


def _generate_recommendations(snap: ProjectSnapshot, alerts: list) -> List[str]:
    """Generate proactive recommendations based on metrics and alerts."""
    recs = []

    if snap.avg_complexity > 30:
        recs.append("Average complexity is high — consider breaking large functions into smaller helpers")
    if snap.max_complexity > 60:
        top = max(snap.files, key=lambda f: f["complexity"])
        recs.append(f"Refactor {top['path']} — complexity {top['complexity']:.1f} is very high")
    if snap.comment_ratio < 5:
        recs.append("Comment ratio is low — add documentation to key functions")
    if snap.lint_warnings > snap.total_files * 5:
        recs.append(f"High lint warnings ({snap.lint_warnings}) — run sauravfmt to auto-fix style issues")

    has_declining = any(a["type"] == "declining_trend" for a in alerts)
    if has_declining:
        recs.append("⚠️ Health is declining over multiple snapshots — prioritize a cleanup sprint")

    large = [f for f in snap.files if f["lines"] > 300]
    if large:
        recs.append(f"{len(large)} file(s) exceed 300 lines — consider splitting them")

    deep = [f for f in snap.files if f["max_nesting"] > 5]
    if deep:
        recs.append(f"{len(deep)} file(s) have deep nesting (>5) — flatten with early returns or extraction")

    if not recs:
        recs.append("Project looks good! Consider setting stretch goals with --set-goal")

    return recs


# ── HTML Dashboard ────────────────────────────────────────────────────

def generate_html(snap: ProjectSnapshot, history: list, alerts: list, goal_alerts: list) -> str:
    """Generate interactive HTML dashboard."""
    all_entries = history + [snapshot_to_dict(snap)]
    timestamps_js = json.dumps([e["timestamp"][:10] for e in all_entries])
    health_js = json.dumps([e["health_score"] for e in all_entries])
    complexity_js = json.dumps([e["avg_complexity"] for e in all_entries])
    warnings_js = json.dumps([e.get("lint_warnings", 0) for e in all_entries])
    files_js = json.dumps(snap.files)
    alerts_js = json.dumps(alerts + goal_alerts)
    grade = _grade(snap.health_score)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sentinel Dashboard — sauravcode</title>
<style>
  :root {{ --bg: #0d1117; --card: #161b22; --border: #30363d; --text: #e6edf3;
           --green: #3fb950; --yellow: #d29922; --red: #f85149; --blue: #58a6ff; }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          background: var(--bg); color: var(--text); padding: 24px; }}
  .header {{ text-align: center; margin-bottom: 32px; }}
  .header h1 {{ font-size: 28px; margin-bottom: 8px; }}
  .header .subtitle {{ color: #8b949e; font-size: 14px; }}
  .grade {{ font-size: 72px; font-weight: bold; margin: 16px 0;
            color: {'{0}'.format('var(--green)' if grade in ('A','B') else 'var(--yellow)' if grade == 'C' else 'var(--red)')}; }}
  .score-bar {{ width: 300px; height: 12px; background: var(--border); border-radius: 6px;
                margin: 0 auto; overflow: hidden; }}
  .score-fill {{ height: 100%; border-radius: 6px; transition: width 0.5s;
                 background: linear-gradient(90deg, var(--red), var(--yellow), var(--green));
                 width: {snap.health_score}%; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-bottom: 24px; }}
  .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 20px; }}
  .card h3 {{ font-size: 14px; color: #8b949e; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px; }}
  .metric {{ font-size: 32px; font-weight: bold; }}
  .metric-sm {{ font-size: 14px; color: #8b949e; }}
  .chart-container {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px;
                      padding: 20px; margin-bottom: 24px; }}
  .alert {{ padding: 12px 16px; border-radius: 6px; margin-bottom: 8px; font-size: 14px; }}
  .alert-critical {{ background: rgba(248,81,73,0.15); border-left: 3px solid var(--red); }}
  .alert-warning {{ background: rgba(210,153,34,0.15); border-left: 3px solid var(--yellow); }}
  .alert-info {{ background: rgba(88,166,255,0.15); border-left: 3px solid var(--blue); }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); }}
  th {{ color: #8b949e; font-weight: 600; text-transform: uppercase; font-size: 12px; }}
  canvas {{ width: 100% !important; max-height: 300px; }}
  .rec {{ padding: 8px 12px; background: rgba(63,185,80,0.1); border-left: 3px solid var(--green);
          border-radius: 4px; margin-bottom: 6px; font-size: 14px; }}
</style>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
</head>
<body>
<div class="header">
  <h1>🛡️ Sentinel Dashboard</h1>
  <div class="subtitle">sauravcode project health · {snap.timestamp[:19]} · {snap.total_files} files</div>
  <div class="grade">{grade}</div>
  <div class="score-bar"><div class="score-fill"></div></div>
  <div class="metric-sm" style="margin-top:8px">{snap.health_score}/100</div>
</div>

<div class="grid">
  <div class="card"><h3>Files</h3><div class="metric">{snap.total_files}</div><div class="metric-sm">{snap.total_lines} total lines</div></div>
  <div class="card"><h3>Functions</h3><div class="metric">{snap.total_functions}</div><div class="metric-sm">{snap.total_code_lines} code lines</div></div>
  <div class="card"><h3>Avg Complexity</h3><div class="metric">{snap.avg_complexity:.1f}</div><div class="metric-sm">Max: {snap.max_complexity:.1f}</div></div>
  <div class="card"><h3>Lint Issues</h3><div class="metric">{snap.lint_warnings + snap.lint_errors}</div><div class="metric-sm">{snap.lint_warnings} warnings · {snap.lint_errors} errors</div></div>
</div>

<div class="chart-container">
  <h3 style="color:#8b949e;font-size:14px;margin-bottom:16px">HEALTH OVER TIME</h3>
  <canvas id="healthChart"></canvas>
</div>

<div class="chart-container">
  <h3 style="color:#8b949e;font-size:14px;margin-bottom:16px">COMPLEXITY TREND</h3>
  <canvas id="complexityChart"></canvas>
</div>

<div class="card" style="margin-bottom:24px">
  <h3>🚨 Alerts</h3>
  <div id="alerts"></div>
</div>

<div class="card" style="margin-bottom:24px">
  <h3>📊 File Details</h3>
  <table>
    <thead><tr><th>File</th><th>Lines</th><th>Code</th><th>Functions</th><th>Complexity</th><th>Depth</th><th>Warnings</th></tr></thead>
    <tbody id="fileTable"></tbody>
  </table>
</div>

<div class="card" style="margin-bottom:24px">
  <h3>💡 Recommendations</h3>
  <div id="recs"></div>
</div>

<script>
const timestamps = {timestamps_js};
const healthData = {health_js};
const complexityData = {complexity_js};
const warningsData = {warnings_js};
const files = {files_js};
const alerts = {alerts_js};

// Health chart
new Chart(document.getElementById('healthChart'), {{
  type: 'line',
  data: {{
    labels: timestamps,
    datasets: [{{
      label: 'Health Score',
      data: healthData,
      borderColor: '#3fb950',
      backgroundColor: 'rgba(63,185,80,0.1)',
      fill: true, tension: 0.3, pointRadius: 4,
    }}]
  }},
  options: {{
    responsive: true,
    scales: {{ y: {{ min: 0, max: 100, ticks: {{ color: '#8b949e' }}, grid: {{ color: '#21262d' }} }},
               x: {{ ticks: {{ color: '#8b949e' }}, grid: {{ color: '#21262d' }} }} }},
    plugins: {{ legend: {{ labels: {{ color: '#e6edf3' }} }} }}
  }}
}});

// Complexity chart
new Chart(document.getElementById('complexityChart'), {{
  type: 'line',
  data: {{
    labels: timestamps,
    datasets: [
      {{ label: 'Avg Complexity', data: complexityData, borderColor: '#d29922', tension: 0.3, pointRadius: 4 }},
      {{ label: 'Lint Warnings', data: warningsData, borderColor: '#f85149', tension: 0.3, pointRadius: 4 }},
    ]
  }},
  options: {{
    responsive: true,
    scales: {{ y: {{ ticks: {{ color: '#8b949e' }}, grid: {{ color: '#21262d' }} }},
               x: {{ ticks: {{ color: '#8b949e' }}, grid: {{ color: '#21262d' }} }} }},
    plugins: {{ legend: {{ labels: {{ color: '#e6edf3' }} }} }}
  }}
}});

// Alerts
const alertsDiv = document.getElementById('alerts');
if (alerts.length === 0) {{
  alertsDiv.innerHTML = '<div style="color:#3fb950;padding:8px">✅ No regressions detected!</div>';
}} else {{
  alerts.forEach(a => {{
    const cls = a.severity === 'critical' ? 'alert-critical' : a.severity === 'warning' ? 'alert-warning' : 'alert-info';
    alertsDiv.innerHTML += `<div class="alert ${{cls}}"><strong>${{a.type}}</strong>: ${{a.message}}</div>`;
  }});
}}

// File table
const tbody = document.getElementById('fileTable');
files.sort((a,b) => b.complexity - a.complexity).forEach(f => {{
  tbody.innerHTML += `<tr><td>${{f.path}}</td><td>${{f.lines}}</td><td>${{f.code_lines}}</td><td>${{f.functions}}</td><td>${{f.complexity.toFixed(1)}}</td><td>${{f.max_nesting}}</td><td>${{f.lint_warnings}}</td></tr>`;
}});

// Recommendations
const recsDiv = document.getElementById('recs');
const recList = {json.dumps(_generate_recommendations(snap, alerts + goal_alerts))};
recList.forEach(r => {{ recsDiv.innerHTML += `<div class="rec">${{r}}</div>`; }});
</script>
</body>
</html>"""


# ── Watch Mode ────────────────────────────────────────────────────────

def watch_mode(directory: str, interval: int = 10):
    """Continuously monitor and alert on regressions."""
    print(f"👁️ Sentinel watching {directory} (Ctrl+C to stop, interval={interval}s)")
    prev_hashes = {}
    while True:
        srv_files = glob.glob(os.path.join(directory, "**", "*.srv"), recursive=True)
        current_hashes = {}
        for f in srv_files:
            try:
                with open(f, "rb") as fh:
                    current_hashes[f] = hashlib.md5(fh.read()).hexdigest()[:12]
            except Exception:
                pass

        if current_hashes != prev_hashes and prev_hashes:
            changed = set(current_hashes.keys()) ^ set(prev_hashes.keys())
            changed |= {k for k in current_hashes if current_hashes.get(k) != prev_hashes.get(k)}
            print(f"\n⚡ Changes detected in {len(changed)} file(s) — re-scanning...")
            snap = scan_project(directory)
            history = load_history(directory)
            alerts = detect_regressions(snap, history)
            goal_alerts = check_goals(snap, load_goals(directory))
            history.append(snapshot_to_dict(snap))
            save_history(directory, history)
            print_report(snap, history[:-1], alerts, goal_alerts)

        prev_hashes = current_hashes
        try:
            _time.sleep(interval)
        except KeyboardInterrupt:
            print("\n👋 Sentinel stopped.")
            break


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    directory = "."
    html_file = None
    show_report = False
    show_alerts = False
    do_reset = False
    do_watch = False
    budget = None
    show_goals = False
    set_goal_key = None
    set_goal_val = None

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--html" and i + 1 < len(args):
            html_file = args[i + 1]; i += 2; continue
        elif a == "--report":
            show_report = True; i += 1; continue
        elif a == "--alerts":
            show_alerts = True; i += 1; continue
        elif a == "--reset":
            do_reset = True; i += 1; continue
        elif a == "--watch":
            do_watch = True; i += 1; continue
        elif a == "--budget" and i + 1 < len(args):
            budget = float(args[i + 1]); i += 2; continue
        elif a == "--goals":
            show_goals = True; i += 1; continue
        elif a == "--set-goal" and i + 2 < len(args):
            set_goal_key = args[i + 1]; set_goal_val = float(args[i + 2]); i += 3; continue
        elif not a.startswith("-"):
            directory = a; i += 1; continue
        else:
            i += 1

    directory = os.path.abspath(directory)

    if do_reset:
        for f in [HISTORY_FILE, GOALS_FILE]:
            path = os.path.join(directory, f)
            if os.path.exists(path):
                os.remove(path)
                print(f"  Removed {path}")
        print("✅ Sentinel history reset.")
        return 0

    if set_goal_key:
        goals = load_goals(directory)
        goals[set_goal_key] = set_goal_val
        save_goals(directory, goals)
        print(f"✅ Goal set: {set_goal_key} = {set_goal_val}")
        return 0

    if show_goals:
        goals = load_goals(directory)
        if goals:
            print("🎯 GOALS:")
            for k, v in goals.items():
                print(f"  {k}: {v}")
        else:
            print("No goals set. Use --set-goal <metric> <value>")
        return 0

    if do_watch:
        watch_mode(directory)
        return 0

    # Scan
    snap = scan_project(directory)
    history = load_history(directory)

    # Budget check
    budget_alerts = []
    if budget and snap.avg_complexity > budget:
        budget_alerts.append({
            "severity": "warning",
            "type": "budget_exceeded",
            "message": f"Complexity budget {budget} exceeded: current avg is {snap.avg_complexity:.1f}",
        })

    alerts = detect_regressions(snap, history)
    goal_alerts = check_goals(snap, load_goals(directory)) + budget_alerts

    # Save snapshot
    history.append(snapshot_to_dict(snap))
    # Keep last 100 snapshots
    if len(history) > 100:
        history = history[-100:]
    save_history(directory, history)

    if show_alerts:
        all_alerts = alerts + goal_alerts
        if all_alerts:
            for a in all_alerts:
                print(f"{_severity_icon(a['severity'])} [{a['type']}] {a['message']}")
        else:
            print("✅ No alerts.")
        return 0

    # Print report
    print_report(snap, history[:-1], alerts, goal_alerts)

    # HTML
    if html_file:
        html = generate_html(snap, history[:-1], alerts, goal_alerts)
        with open(html_file, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"📄 HTML dashboard saved to {html_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
