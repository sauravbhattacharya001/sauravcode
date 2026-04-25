#!/usr/bin/env python3
"""
sauravforecast — Autonomous Code Maintenance Forecaster for sauravcode.

Predicts which .srv files will need maintenance next by analyzing complexity
trends, code smell density, structural fragility, and coupling. Generates
risk scores, maintenance windows, and proactive recommendations.

Usage:
    python sauravforecast.py                          # Forecast all .srv files in cwd
    python sauravforecast.py path/to/project          # Forecast specific directory
    python sauravforecast.py --html report.html       # Interactive HTML report
    python sauravforecast.py --json                   # JSON output
    python sauravforecast.py --top 5                  # Show top N riskiest files
    python sauravforecast.py --watch                  # Continuous monitoring mode
    python sauravforecast.py --budget 72              # Alert if any file needs maintenance within N hours
    python sauravforecast.py file.srv                 # Deep forecast for single file
"""

import sys
import os
import re
import json
import math
import time as _time
import glob
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

# ── ANSI Colors ───────────────────────────────────────────────────────

def _c(code):
    return lambda t: f"\033[{code}m{t}\033[0m" if sys.stdout.isatty() else t

try:
    from _termcolors import *
except ImportError:
    pass

# Ensure color functions always exist
for _name, _code in [('RED',31),('GREEN',32),('YELLOW',33),('BLUE',34),('CYAN',36),('MAGENTA',35),('BOLD',1),('DIM',2),('WHITE',37)]:
    if _name not in dir() or not callable(globals().get(_name)):
        globals()[_name] = _c(_code)

# ── Data Structures ───────────────────────────────────────────────────

HISTORY_FILE = ".forecast-history.json"

@dataclass
class SmellReport:
    """Individual code smell detected."""
    name: str
    severity: float  # 0-1
    location: str = ""
    description: str = ""

@dataclass
class FileForecast:
    """Maintenance forecast for a single .srv file."""
    path: str
    lines: int = 0
    code_lines: int = 0
    functions: int = 0
    max_nesting: int = 0
    cyclomatic_complexity: float = 0.0
    smell_count: int = 0
    smell_density: float = 0.0
    coupling_score: float = 0.0
    fragility_score: float = 0.0
    risk_score: float = 0.0  # 0-100
    maintenance_urgency: str = "low"  # low/medium/high/critical
    predicted_hours: float = 0.0  # estimated hours until maintenance needed
    smells: List[dict] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

@dataclass
class ProjectForecast:
    """Aggregate forecast for entire project."""
    timestamp: str = ""
    directory: str = ""
    total_files: int = 0
    total_risk: float = 0.0
    avg_risk: float = 0.0
    critical_count: int = 0
    high_count: int = 0
    files: List[dict] = field(default_factory=list)
    hotspots: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

# ── Code Analysis Engine ──────────────────────────────────────────────

def read_file(path: str) -> str:
    for enc in ('utf-8', 'latin-1'):
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, OSError):
            continue
    return ""

def analyze_complexity(source: str) -> Tuple[int, int, int, int, float]:
    """Analyze .srv source: returns (lines, code_lines, functions, max_nesting, complexity)."""
    lines = source.split('\n')
    total = len(lines)
    code_lines = 0
    functions = 0
    max_nesting = 0
    current_nesting = 0
    branch_count = 0

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('//') or stripped.startswith('#'):
            continue
        code_lines += 1

        # Count functions
        if re.match(r'^(func|function|fn)\s+\w+', stripped):
            functions += 1

        # Track nesting
        if re.match(r'^(if|for|while|foreach|try|switch)\b', stripped):
            current_nesting += 1
            branch_count += 1
            max_nesting = max(max_nesting, current_nesting)
        if stripped in ('}', 'end', 'endif', 'endfor', 'endwhile'):
            current_nesting = max(0, current_nesting - 1)

    # Cyclomatic complexity approximation
    complexity = 1.0 + branch_count + (max_nesting * 0.5)
    return total, code_lines, functions, max_nesting, complexity

def detect_smells(source: str, path: str) -> List[SmellReport]:
    """Detect code smells in .srv source."""
    smells = []
    lines = source.split('\n')

    # Long file
    if len(lines) > 300:
        smells.append(SmellReport("long-file", min(1.0, len(lines) / 600),
                                  path, f"File has {len(lines)} lines (>300)"))

    # Long functions
    in_func = False
    func_start = 0
    func_name = ""
    func_lines = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        m = re.match(r'^(?:func|function|fn)\s+(\w+)', stripped)
        if m:
            if in_func and func_lines > 50:
                smells.append(SmellReport("long-function", min(1.0, func_lines / 100),
                                          f"{path}:{func_start+1}", f"Function '{func_name}' is {func_lines} lines"))
            in_func = True
            func_start = i
            func_name = m.group(1)
            func_lines = 0
        elif in_func:
            func_lines += 1
    if in_func and func_lines > 50:
        smells.append(SmellReport("long-function", min(1.0, func_lines / 100),
                                  f"{path}:{func_start+1}", f"Function '{func_name}' is {func_lines} lines"))

    # Deep nesting
    for i, line in enumerate(lines):
        indent = len(line) - len(line.lstrip())
        if indent > 24:  # ~6 levels
            smells.append(SmellReport("deep-nesting", min(1.0, indent / 40),
                                      f"{path}:{i+1}", f"Nesting depth {indent//4} levels"))
            break  # report once

    # Duplicate patterns (repeated blocks)
    block_hashes = Counter()
    for i in range(len(lines) - 3):
        block = '\n'.join(l.strip() for l in lines[i:i+4] if l.strip())
        if len(block) > 20:
            block_hashes[block] += 1
    dupes = sum(1 for c in block_hashes.values() if c > 2)
    if dupes > 3:
        smells.append(SmellReport("duplication", min(1.0, dupes / 10),
                                  path, f"{dupes} repeated code blocks detected"))

    # Magic numbers
    magic = set()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('//') or stripped.startswith('#'):
            continue
        for m in re.finditer(r'(?<!["\w])(\d{2,})(?!["\w])', stripped):
            val = m.group(1)
            if val not in ('100', '10', '0', '00', '1000'):
                magic.add(val)
    if len(magic) > 5:
        smells.append(SmellReport("magic-numbers", min(1.0, len(magic) / 15),
                                  path, f"{len(magic)} magic numbers found"))

    # Missing error handling
    has_try = any('try' in l for l in lines)
    has_risky = any(kw in source for kw in ['open(', 'read(', 'write(', 'http', 'fetch(', 'parse('])
    if has_risky and not has_try:
        smells.append(SmellReport("no-error-handling", 0.6,
                                  path, "Risky operations without try/catch"))

    # God function (single function dominates)
    if func_lines > 0 and len(lines) > 20:
        ratio = func_lines / len(lines)
        if ratio > 0.6:
            smells.append(SmellReport("god-function", ratio,
                                      path, f"One function contains {ratio:.0%} of all code"))

    # Commented-out code
    commented = sum(1 for l in lines if l.strip().startswith('//') and
                    any(kw in l for kw in ['=', '(', 'if ', 'for ', 'func ', 'var ', 'let ']))
    if commented > 5:
        smells.append(SmellReport("commented-code", min(1.0, commented / 15),
                                  path, f"{commented} lines of commented-out code"))

    return smells

def analyze_coupling(source: str, all_files: List[str]) -> float:
    """Measure how coupled a file is to others (import/reference analysis)."""
    imports = re.findall(r'import\s+["\']([^"\']+)["\']', source)
    refs = 0
    for f in all_files:
        basename = os.path.splitext(os.path.basename(f))[0]
        if basename in source:
            refs += 1
    return min(1.0, (len(imports) * 0.3 + refs * 0.1))

def compute_fragility(complexity: float, max_nesting: int, smell_density: float, coupling: float) -> float:
    """Compute structural fragility score (0-1). Higher = more fragile."""
    c = min(1.0, complexity / 30)
    n = min(1.0, max_nesting / 8)
    return 0.3 * c + 0.2 * n + 0.3 * smell_density + 0.2 * coupling

def compute_risk(fragility: float, smell_density: float, code_lines: int, complexity: float) -> float:
    """Compute maintenance risk score (0-100)."""
    size_factor = min(1.0, code_lines / 400)
    raw = (fragility * 40 + smell_density * 30 + size_factor * 15 + min(1.0, complexity / 25) * 15)
    return min(100.0, raw)

def predict_hours(risk: float) -> float:
    """Predict hours until maintenance is needed based on risk score."""
    if risk >= 80:
        return 24.0  # needs attention within a day
    elif risk >= 60:
        return 72.0
    elif risk >= 40:
        return 168.0  # a week
    elif risk >= 20:
        return 720.0  # a month
    else:
        return 2160.0  # ~3 months

def urgency_label(risk: float) -> str:
    if risk >= 80: return "critical"
    if risk >= 60: return "high"
    if risk >= 40: return "medium"
    return "low"

# ── Forecast Engine ───────────────────────────────────────────────────

def forecast_file(path: str, all_files: List[str]) -> FileForecast:
    """Generate maintenance forecast for a single file."""
    source = read_file(path)
    if not source:
        return FileForecast(path=path)

    total, code_lines, functions, max_nesting, complexity = analyze_complexity(source)
    smells = detect_smells(source, path)
    coupling = analyze_coupling(source, all_files)
    smell_density = len(smells) / max(1, code_lines) * 100
    fragility = compute_fragility(complexity, max_nesting, smell_density, coupling)
    risk = compute_risk(fragility, smell_density, code_lines, complexity)
    hours = predict_hours(risk)
    urgency = urgency_label(risk)

    # Generate recommendations
    recs = []
    for s in sorted(smells, key=lambda x: x.severity, reverse=True)[:3]:
        if s.name == "long-file":
            recs.append(f"Split into smaller modules (currently {total} lines)")
        elif s.name == "long-function":
            recs.append(f"Refactor {s.description}")
        elif s.name == "deep-nesting":
            recs.append("Reduce nesting with early returns or extraction")
        elif s.name == "duplication":
            recs.append("Extract repeated code into shared functions")
        elif s.name == "magic-numbers":
            recs.append("Replace magic numbers with named constants")
        elif s.name == "no-error-handling":
            recs.append("Add error handling for risky operations")
        elif s.name == "god-function":
            recs.append("Break up dominant function into smaller pieces")
        elif s.name == "commented-code":
            recs.append("Remove commented-out code (use version control)")

    if coupling > 0.6:
        recs.append("High coupling — consider reducing inter-file dependencies")
    if complexity > 20 and not any("nesting" in r for r in recs):
        recs.append("High cyclomatic complexity — simplify control flow")

    return FileForecast(
        path=os.path.basename(path),
        lines=total,
        code_lines=code_lines,
        functions=functions,
        max_nesting=max_nesting,
        cyclomatic_complexity=round(complexity, 1),
        smell_count=len(smells),
        smell_density=round(smell_density, 2),
        coupling_score=round(coupling, 2),
        fragility_score=round(fragility, 3),
        risk_score=round(risk, 1),
        maintenance_urgency=urgency,
        predicted_hours=round(hours, 1),
        smells=[asdict(s) for s in smells],
        recommendations=recs
    )

def forecast_project(directory: str) -> ProjectForecast:
    """Generate maintenance forecast for entire project."""
    srv_files = glob.glob(os.path.join(directory, '**', '*.srv'), recursive=True)
    if not srv_files:
        srv_files = glob.glob(os.path.join(directory, '*.srv'))

    forecasts = []
    for f in sorted(srv_files):
        fc = forecast_file(f, srv_files)
        if fc.lines > 0:
            forecasts.append(fc)

    if not forecasts:
        return ProjectForecast(timestamp=datetime.now().isoformat(), directory=directory)

    total_risk = sum(f.risk_score for f in forecasts)
    avg_risk = total_risk / len(forecasts)
    critical = sum(1 for f in forecasts if f.maintenance_urgency == "critical")
    high = sum(1 for f in forecasts if f.maintenance_urgency == "high")

    # Sort by risk descending
    forecasts.sort(key=lambda x: x.risk_score, reverse=True)

    # Identify hotspots (top 20% by risk)
    cutoff = max(1, len(forecasts) // 5)
    hotspots = [f.path for f in forecasts[:cutoff]]

    # Project-level recommendations
    recs = []
    if critical > 0:
        recs.append(f"🚨 {critical} file(s) need immediate maintenance attention")
    if high > 0:
        recs.append(f"⚠️ {high} file(s) at high risk — schedule maintenance this week")
    if avg_risk > 50:
        recs.append("📊 Overall project risk is elevated — consider a refactoring sprint")

    # Smell distribution
    all_smells = Counter()
    for f in forecasts:
        for s in f.smells:
            all_smells[s['name']] += 1
    if all_smells:
        top_smell = all_smells.most_common(1)[0]
        recs.append(f"🔍 Most common issue: '{top_smell[0]}' ({top_smell[1]} occurrences)")

    # Coupling analysis
    high_coupling = [f for f in forecasts if f.coupling_score > 0.5]
    if len(high_coupling) > 2:
        recs.append(f"🔗 {len(high_coupling)} files have high coupling — risk of cascade failures")

    return ProjectForecast(
        timestamp=datetime.now().isoformat(),
        directory=directory,
        total_files=len(forecasts),
        total_risk=round(total_risk, 1),
        avg_risk=round(avg_risk, 1),
        critical_count=critical,
        high_count=high,
        files=[asdict(f) for f in forecasts],
        hotspots=hotspots,
        recommendations=recs
    )

# ── History Management ────────────────────────────────────────────────

def load_history(directory: str) -> List[dict]:
    path = os.path.join(directory, HISTORY_FILE)
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return []

def save_history(directory: str, history: List[dict]):
    path = os.path.join(directory, HISTORY_FILE)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(history[-50:], f, indent=2)  # Keep last 50 snapshots

def record_snapshot(forecast: ProjectForecast, directory: str):
    history = load_history(directory)
    snapshot = {
        "timestamp": forecast.timestamp,
        "total_files": forecast.total_files,
        "avg_risk": forecast.avg_risk,
        "critical_count": forecast.critical_count,
        "high_count": forecast.high_count,
        "hotspots": forecast.hotspots[:5]
    }
    history.append(snapshot)
    save_history(directory, history)

# ── Display Functions ─────────────────────────────────────────────────

def risk_bar(score: float, width: int = 20) -> str:
    filled = int(score / 100 * width)
    if score >= 80:
        color = RED
    elif score >= 60:
        color = YELLOW
    elif score >= 40:
        color = CYAN
    else:
        color = GREEN
    return color('█' * filled) + DIM('░' * (width - filled))

def urgency_icon(u: str) -> str:
    return {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(u, "⚪")

def print_forecast(forecast: ProjectForecast, top_n: int = 0):
    print()
    print(BOLD("╔══════════════════════════════════════════════════════════════╗"))
    print(BOLD("║         🔮 SAURAVCODE MAINTENANCE FORECASTER 🔮            ║"))
    print(BOLD("╚══════════════════════════════════════════════════════════════╝"))
    print()
    print(f"  📁 Directory:  {forecast.directory}")
    print(f"  📅 Timestamp:  {forecast.timestamp[:19]}")
    print(f"  📊 Files:      {forecast.total_files}")
    print(f"  ⚡ Avg Risk:   {forecast.avg_risk:.1f}/100  {risk_bar(forecast.avg_risk)}")
    print()

    if forecast.critical_count or forecast.high_count:
        print(BOLD("  ⚠️  ALERTS:"))
        if forecast.critical_count:
            print(RED(f"    🔴 {forecast.critical_count} CRITICAL - maintenance needed within 24h"))
        if forecast.high_count:
            print(YELLOW(f"    🟠 {forecast.high_count} HIGH - maintenance needed this week"))
        print()

    files = forecast.files
    if top_n > 0:
        files = files[:top_n]

    print(BOLD("  📋 FILE FORECAST TABLE"))
    print(f"  {'File':<30} {'Risk':>6} {'Urgency':<10} {'ETA':>8} {'Smells':>7} {'Bar'}")
    print(f"  {'─'*30} {'─'*6} {'─'*10} {'─'*8} {'─'*7} {'─'*22}")

    for fd in files:
        name = fd['path'][:28]
        risk = fd['risk_score']
        urg = fd['maintenance_urgency']
        hours = fd['predicted_hours']
        sc = fd['smell_count']
        if hours < 48:
            eta = f"{hours:.0f}h"
        elif hours < 720:
            eta = f"{hours/24:.0f}d"
        else:
            eta = f"{hours/720:.0f}mo"
        print(f"  {name:<30} {risk:>5.1f} {urgency_icon(urg)} {urg:<8} {eta:>7} {sc:>6}  {risk_bar(risk, 15)}")

    print()

    # Hotspots
    if forecast.hotspots:
        print(BOLD("  🔥 HOTSPOTS (top 20% by risk):"))
        for h in forecast.hotspots[:8]:
            print(f"    • {h}")
        print()

    # Recommendations
    if forecast.recommendations:
        print(BOLD("  💡 PROACTIVE RECOMMENDATIONS:"))
        for r in forecast.recommendations:
            print(f"    {r}")
        print()

    # Detail for top 3 critical/high files
    critical_files = [f for f in forecast.files if f['maintenance_urgency'] in ('critical', 'high')][:3]
    if critical_files:
        print(BOLD("  🔬 DETAILED ANALYSIS (top risk files):"))
        print()
        for fd in critical_files:
            print(f"    {BOLD(fd['path'])}")
            print(f"      Lines: {fd['lines']} | Code: {fd['code_lines']} | Functions: {fd['functions']}")
            print(f"      Complexity: {fd['cyclomatic_complexity']} | Nesting: {fd['max_nesting']} | Coupling: {fd['coupling_score']}")
            print(f"      Fragility: {fd['fragility_score']:.3f} | Smells: {fd['smell_count']}")
            if fd['smells']:
                for s in fd['smells'][:3]:
                    sev_bar = '█' * int(s['severity'] * 5)
                    print(f"        ⚡ {s['name']} [{sev_bar}] {s['description']}")
            if fd['recommendations']:
                for r in fd['recommendations'][:2]:
                    print(f"        → {r}")
            print()

def print_single_file(fc: FileForecast):
    print()
    print(BOLD(f"  🔮 FORECAST: {fc.path}"))
    print(f"  {'─'*50}")
    print(f"  Lines:        {fc.lines} ({fc.code_lines} code)")
    print(f"  Functions:    {fc.functions}")
    print(f"  Complexity:   {fc.cyclomatic_complexity}")
    print(f"  Max Nesting:  {fc.max_nesting}")
    print(f"  Coupling:     {fc.coupling_score}")
    print(f"  Fragility:    {fc.fragility_score:.3f}")
    print(f"  Risk Score:   {fc.risk_score:.1f}/100  {risk_bar(fc.risk_score)}")
    print(f"  Urgency:      {urgency_icon(fc.maintenance_urgency)} {fc.maintenance_urgency.upper()}")
    print(f"  Predicted:    Maintenance in ~{fc.predicted_hours:.0f} hours")
    print()
    if fc.smells:
        print(BOLD("  🦨 Code Smells:"))
        for s in fc.smells:
            sev = '█' * int(s['severity'] * 10)
            print(f"    [{sev:<10}] {s['name']}: {s['description']}")
        print()
    if fc.recommendations:
        print(BOLD("  💡 Recommendations:"))
        for r in fc.recommendations:
            print(f"    → {r}")
        print()

# ── HTML Report Generator ────────────────────────────────────────────

def generate_html(forecast: ProjectForecast, output: str):
    files_json = json.dumps(forecast.files)
    history = load_history(forecast.directory)
    history_json = json.dumps(history)
    recs_html = ''.join(f'<li>{r}</li>' for r in forecast.recommendations)
    hotspots_html = ''.join(f'<span class="tag hot">{h}</span>' for h in forecast.hotspots[:10])

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🔮 Sauravcode Maintenance Forecast</title>
<style>
  :root {{ --bg: #0d1117; --card: #161b22; --border: #30363d; --text: #c9d1d9;
           --green: #3fb950; --yellow: #d29922; --orange: #db6d28; --red: #f85149;
           --blue: #58a6ff; --purple: #bc8cff; }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; padding: 20px; }}
  .header {{ text-align: center; padding: 30px 0; }}
  .header h1 {{ font-size: 2em; margin-bottom: 8px; }}
  .header .sub {{ color: #8b949e; }}
  .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 20px 0; }}
  .stat {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; text-align: center; }}
  .stat .val {{ font-size: 2em; font-weight: bold; }}
  .stat .label {{ color: #8b949e; font-size: 0.85em; margin-top: 4px; }}
  .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 20px; margin: 16px 0; }}
  .card h2 {{ margin-bottom: 12px; font-size: 1.3em; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); }}
  th {{ color: #8b949e; font-weight: 600; font-size: 0.85em; text-transform: uppercase; }}
  .risk-bar {{ display: inline-block; height: 8px; border-radius: 4px; }}
  .risk-bg {{ background: #21262d; width: 100px; display: inline-block; height: 8px; border-radius: 4px; position: relative; }}
  .urgency {{ padding: 2px 8px; border-radius: 12px; font-size: 0.8em; font-weight: 600; }}
  .urgency.critical {{ background: rgba(248,81,73,0.2); color: var(--red); }}
  .urgency.high {{ background: rgba(219,109,40,0.2); color: var(--orange); }}
  .urgency.medium {{ background: rgba(210,153,34,0.2); color: var(--yellow); }}
  .urgency.low {{ background: rgba(63,185,80,0.2); color: var(--green); }}
  .tag {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.8em; margin: 2px; }}
  .tag.hot {{ background: rgba(248,81,73,0.15); color: var(--red); border: 1px solid rgba(248,81,73,0.3); }}
  .smell-badge {{ display: inline-block; padding: 1px 6px; border-radius: 6px; font-size: 0.75em; margin: 1px;
                  background: rgba(188,140,255,0.15); color: var(--purple); }}
  ul {{ list-style: none; }}
  ul li {{ padding: 6px 0; padding-left: 20px; position: relative; }}
  ul li::before {{ content: '→'; position: absolute; left: 0; color: var(--blue); }}
  canvas {{ width: 100%; max-height: 200px; }}
  .chart-container {{ position: relative; height: 200px; }}
  .filter {{ margin: 10px 0; }}
  .filter button {{ background: var(--card); border: 1px solid var(--border); color: var(--text); padding: 6px 14px;
                    border-radius: 6px; cursor: pointer; margin-right: 6px; }}
  .filter button.active {{ border-color: var(--blue); color: var(--blue); }}
  .detail {{ display: none; background: #0d1117; border: 1px solid var(--border); border-radius: 6px; padding: 12px; margin-top: 8px; }}
  .expandable {{ cursor: pointer; }}
  .expandable:hover {{ background: rgba(88,166,255,0.05); }}
  .trend-up {{ color: var(--red); }}
  .trend-down {{ color: var(--green); }}
  .trend-flat {{ color: #8b949e; }}
</style>
</head>
<body>
<div class="header">
  <h1>🔮 Maintenance Forecast</h1>
  <div class="sub">sauravcode · {forecast.timestamp[:19]} · {forecast.total_files} files analyzed</div>
</div>

<div class="stats">
  <div class="stat"><div class="val" style="color:var(--blue)">{forecast.total_files}</div><div class="label">Files Analyzed</div></div>
  <div class="stat"><div class="val" style="color:{'var(--red)' if forecast.avg_risk > 50 else 'var(--green)'}">{forecast.avg_risk:.1f}</div><div class="label">Avg Risk Score</div></div>
  <div class="stat"><div class="val" style="color:var(--red)">{forecast.critical_count}</div><div class="label">Critical</div></div>
  <div class="stat"><div class="val" style="color:var(--orange)">{forecast.high_count}</div><div class="label">High Risk</div></div>
</div>

<div class="card">
  <h2>🔥 Hotspots</h2>
  <div>{hotspots_html if hotspots_html else '<span style="color:#8b949e">No hotspots detected</span>'}</div>
</div>

<div class="card">
  <h2>📈 Risk Trend</h2>
  <div class="chart-container"><canvas id="trendChart"></canvas></div>
</div>

<div class="card">
  <h2>💡 Proactive Recommendations</h2>
  <ul>{recs_html if recs_html else '<li style="color:#8b949e">No recommendations — project looks healthy!</li>'}</ul>
</div>

<div class="card">
  <h2>📋 File Forecast Table</h2>
  <div class="filter">
    <button class="active" onclick="filterFiles('all')">All</button>
    <button onclick="filterFiles('critical')">🔴 Critical</button>
    <button onclick="filterFiles('high')">🟠 High</button>
    <button onclick="filterFiles('medium')">🟡 Medium</button>
    <button onclick="filterFiles('low')">🟢 Low</button>
  </div>
  <table>
    <thead><tr><th>File</th><th>Risk</th><th>Urgency</th><th>ETA</th><th>Smells</th><th>Complexity</th><th>Bar</th></tr></thead>
    <tbody id="fileTable"></tbody>
  </table>
</div>

<div class="card" id="detailPanel" style="display:none">
  <h2>🔬 File Detail</h2>
  <div id="detailContent"></div>
</div>

<script>
const files = {files_json};
const history = {history_json};

function riskColor(r) {{ return r >= 80 ? 'var(--red)' : r >= 60 ? 'var(--orange)' : r >= 40 ? 'var(--yellow)' : 'var(--green)'; }}
function etaStr(h) {{ return h < 48 ? h.toFixed(0)+'h' : h < 720 ? (h/24).toFixed(0)+'d' : (h/720).toFixed(0)+'mo'; }}

function renderTable(filter) {{
  const tbody = document.getElementById('fileTable');
  tbody.innerHTML = '';
  const filtered = filter === 'all' ? files : files.filter(f => f.maintenance_urgency === filter);
  filtered.forEach((f, i) => {{
    const pct = Math.min(100, f.risk_score);
    const row = document.createElement('tr');
    row.className = 'expandable';
    row.onclick = () => showDetail(f);
    row.innerHTML = `<td>${{f.path}}</td><td style="color:${{riskColor(f.risk_score)}};font-weight:bold">${{f.risk_score.toFixed(1)}}</td>` +
      `<td><span class="urgency ${{f.maintenance_urgency}}">${{f.maintenance_urgency}}</span></td>` +
      `<td>${{etaStr(f.predicted_hours)}}</td><td>${{f.smell_count}}</td><td>${{f.cyclomatic_complexity}}</td>` +
      `<td><div class="risk-bg"><div class="risk-bar" style="width:${{pct}}%;background:${{riskColor(f.risk_score)}}"></div></div></td>`;
    tbody.appendChild(row);
  }});
}}

function filterFiles(f) {{
  document.querySelectorAll('.filter button').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  renderTable(f);
}}

function showDetail(f) {{
  const panel = document.getElementById('detailPanel');
  const content = document.getElementById('detailContent');
  let html = `<p><strong>${{f.path}}</strong> — ${{f.lines}} lines, ${{f.functions}} functions</p>`;
  html += `<p>Complexity: ${{f.cyclomatic_complexity}} | Nesting: ${{f.max_nesting}} | Coupling: ${{f.coupling_score}} | Fragility: ${{f.fragility_score.toFixed(3)}}</p>`;
  if (f.smells.length) {{
    html += '<h3 style="margin:10px 0 6px">🦨 Smells</h3>';
    f.smells.forEach(s => {{
      const bar = '█'.repeat(Math.round(s.severity * 10));
      html += `<div><span class="smell-badge">${{s.name}}</span> [${{bar}}] ${{s.description}}</div>`;
    }});
  }}
  if (f.recommendations.length) {{
    html += '<h3 style="margin:10px 0 6px">💡 Recommendations</h3><ul>';
    f.recommendations.forEach(r => html += `<li>${{r}}</li>`);
    html += '</ul>';
  }}
  content.innerHTML = html;
  panel.style.display = 'block';
  panel.scrollIntoView({{ behavior: 'smooth' }});
}}

// Trend chart
function drawTrend() {{
  const canvas = document.getElementById('trendChart');
  if (!history.length) return;
  const ctx = canvas.getContext('2d');
  const W = canvas.width = canvas.parentElement.clientWidth;
  const H = canvas.height = 200;
  const pad = 40;
  const data = history.slice(-20);
  const maxR = Math.max(100, ...data.map(d => d.avg_risk));
  ctx.fillStyle = '#0d1117'; ctx.fillRect(0, 0, W, H);
  // Grid
  ctx.strokeStyle = '#21262d'; ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {{
    const y = pad + (H - 2*pad) * i / 4;
    ctx.beginPath(); ctx.moveTo(pad, y); ctx.lineTo(W-pad, y); ctx.stroke();
    ctx.fillStyle = '#8b949e'; ctx.font = '11px sans-serif';
    ctx.fillText((maxR * (1 - i/4)).toFixed(0), 5, y + 4);
  }}
  if (data.length < 2) return;
  // Line
  ctx.beginPath(); ctx.strokeStyle = '#58a6ff'; ctx.lineWidth = 2;
  data.forEach((d, i) => {{
    const x = pad + (W - 2*pad) * i / (data.length - 1);
    const y = pad + (H - 2*pad) * (1 - d.avg_risk / maxR);
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }});
  ctx.stroke();
  // Points
  data.forEach((d, i) => {{
    const x = pad + (W - 2*pad) * i / (data.length - 1);
    const y = pad + (H - 2*pad) * (1 - d.avg_risk / maxR);
    ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI*2);
    ctx.fillStyle = riskColor(d.avg_risk); ctx.fill();
  }});
}}

renderTable('all');
drawTrend();
window.addEventListener('resize', drawTrend);
</script>
</body>
</html>"""

    with open(output, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"  📄 HTML report saved to {GREEN(output)}")

# ── Watch Mode ────────────────────────────────────────────────────────

def watch_mode(directory: str, interval: int = 60, budget: float = 0):
    """Continuous monitoring mode with autonomous alerts."""
    print(BOLD("  👁️  WATCH MODE — monitoring for maintenance risks"))
    print(f"  Interval: {interval}s | Budget: {budget}h" if budget else f"  Interval: {interval}s")
    print(f"  Press Ctrl+C to stop\n")

    prev_risks = {}
    cycle = 0

    try:
        while True:
            cycle += 1
            forecast = forecast_project(directory)
            record_snapshot(forecast, directory)

            # Check for risk changes
            alerts = []
            for fd in forecast.files:
                prev = prev_risks.get(fd['path'], fd['risk_score'])
                delta = fd['risk_score'] - prev
                if delta > 10:
                    alerts.append(f"  ⬆️  {fd['path']}: risk {prev:.0f} → {fd['risk_score']:.0f} (+{delta:.0f})")
                elif delta < -10:
                    alerts.append(f"  ⬇️  {fd['path']}: risk {prev:.0f} → {fd['risk_score']:.0f} ({delta:.0f})")
                prev_risks[fd['path']] = fd['risk_score']

            # Budget alerts
            if budget > 0:
                urgent = [f for f in forecast.files if f['predicted_hours'] <= budget]
                if urgent:
                    alerts.append(f"  🚨 {len(urgent)} file(s) predicted to need maintenance within {budget}h budget!")

            ts = datetime.now().strftime("%H:%M:%S")
            status = f"avg_risk={forecast.avg_risk:.1f} critical={forecast.critical_count} high={forecast.high_count}"
            if alerts:
                print(f"  [{ts}] Cycle {cycle} — {status}")
                for a in alerts:
                    print(a)
            else:
                print(f"  [{ts}] Cycle {cycle} — {status} — stable ✓")

            _time.sleep(interval)

    except KeyboardInterrupt:
        print(f"\n  Watch stopped after {cycle} cycles.")

# ── Main ──────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    directory = '.'
    html_output = None
    json_output = False
    top_n = 0
    watch = False
    budget = 0
    single_file = None

    i = 0
    while i < len(args):
        a = args[i]
        if a == '--html' and i + 1 < len(args):
            html_output = args[i+1]; i += 2; continue
        elif a == '--json':
            json_output = True; i += 1; continue
        elif a == '--top' and i + 1 < len(args):
            top_n = int(args[i+1]); i += 2; continue
        elif a == '--watch':
            watch = True; i += 1; continue
        elif a == '--budget' and i + 1 < len(args):
            budget = float(args[i+1]); i += 2; continue
        elif a.endswith('.srv'):
            single_file = a; i += 1; continue
        elif not a.startswith('-'):
            directory = a; i += 1; continue
        else:
            i += 1

    if single_file:
        all_files = glob.glob(os.path.join(directory, '*.srv'))
        fc = forecast_file(single_file, all_files)
        if json_output:
            print(json.dumps(asdict(fc), indent=2))
        else:
            print_single_file(fc)
        return

    if watch:
        watch_mode(directory, budget=budget)
        return

    forecast = forecast_project(directory)
    record_snapshot(forecast, directory)

    if json_output:
        print(json.dumps(asdict(forecast), indent=2))
    elif html_output:
        generate_html(forecast, html_output)
        if not top_n:
            print_forecast(forecast, top_n=5)
    else:
        print_forecast(forecast, top_n=top_n)

    # Budget check
    if budget > 0:
        urgent = [f for f in forecast.files if f['predicted_hours'] <= budget]
        if urgent:
            print(RED(f"  🚨 BUDGET ALERT: {len(urgent)} file(s) need maintenance within {budget}h!"))
            for fd in urgent:
                print(f"    • {fd['path']} (risk {fd['risk_score']:.1f}, ~{fd['predicted_hours']:.0f}h)")
            print()

if __name__ == '__main__':
    main()
