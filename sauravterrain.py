#!/usr/bin/env python3
"""sauravterrain — Autonomous Code Complexity Terrain Mapper for sauravcode.

Models an entire .srv codebase as a topographic landscape where every
function/file is a cell on a 2-D grid.  Elevation = complexity, color =
risk tier.  Then runs 7 autonomous analysis engines to surface
actionable insights about the structural shape of the code.

Analysis Engines (7):
    T001  Elevation Mapper       Assign elevation (0-100) per function from complexity metrics
    T002  Peak Detector          Find local maxima — the hardest functions surrounded by simpler ones
    T003  Valley Finder          Find local minima — unexpectedly simple zones that may be under-implemented
    T004  Ridge Tracer           Chains of connected high-complexity functions forming complexity corridors
    T005  Erosion Risk Scorer    Functions whose complexity is unsustainably high relative to size
    T006  Trail Recommender      Suggest optimal review traversal order to build understanding incrementally
    T007  Terrain Health Scorer  Composite landscape health score 0-100 with autonomous insights

Usage:
    python sauravterrain.py program.srv              # Map a single file
    python sauravterrain.py .                        # Map all .srv files in cwd
    python sauravterrain.py . --recursive            # Include subdirectories
    python sauravterrain.py . --html report.html     # Interactive HTML dashboard
    python sauravterrain.py . --json                 # JSON output
    python sauravterrain.py . --peaks                # Show only peaks (most complex)
    python sauravterrain.py . --valleys              # Show only valleys
    python sauravterrain.py . --ridges               # Show complexity ridges
    python sauravterrain.py . --trails               # Recommend review trails
    python sauravterrain.py . --erosion              # Show erosion risk zones
    python sauravterrain.py . --top 10               # Top N highest elevation cells
"""

import sys
import os
import re
import json
import math
import argparse
from collections import defaultdict, Counter
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Set, Optional, Tuple, Any
from datetime import datetime

__version__ = "1.0.0"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Windows UTF-8 fix ────────────────────────────────────────────────
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    import io as _io
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from _srv_utils import get_indent as _get_indent, find_srv_files as _find_srv_files

# ── ANSI Colors ──────────────────────────────────────────────────────

USE_COLOR = True

def _c(code, t):
    return f"\033[{code}m{t}\033[0m" if USE_COLOR else str(t)

def red(t):    return _c("31", t)
def green(t):  return _c("32", t)
def yellow(t): return _c("33", t)
def cyan(t):   return _c("36", t)
def bold(t):   return _c("1", t)
def dim(t):    return _c("2", t)
def magenta(t): return _c("35", t)

FUNCTION_DEF = re.compile(r'^(\s*)(function|fn)\s+(\w+)')
BRANCH_KEYWORDS = {'if', 'elif', 'while', 'for', 'foreach', 'catch', 'and', 'or'}
CALL_PATTERN = re.compile(r'\b([a-zA-Z_]\w*)\s*\(')

# ── Data Classes ─────────────────────────────────────────────────────

@dataclass
class TerrainCell:
    """A single cell on the complexity terrain — one function."""
    name: str
    file: str
    line: int
    loc: int = 0
    complexity: int = 1
    max_depth: int = 0
    params: int = 0
    calls: List[str] = field(default_factory=list)
    called_by: List[str] = field(default_factory=list)
    elevation: float = 0.0       # 0-100 normalized complexity
    risk_tier: str = "plain"     # plain/hill/mountain/peak
    erosion_risk: float = 0.0    # 0-1
    is_peak: bool = False
    is_valley: bool = False
    ridge_id: int = -1

    @property
    def fqn(self):
        return f"{self.file}::{self.name}"

@dataclass
class Ridge:
    """A chain of connected high-complexity functions."""
    ridge_id: int
    cells: List[str] = field(default_factory=list)  # fqn list
    avg_elevation: float = 0.0
    length: int = 0
    severity: str = "moderate"

@dataclass
class Trail:
    """A recommended review traversal order."""
    name: str
    description: str
    steps: List[str] = field(default_factory=list)  # fqn list
    difficulty: str = "moderate"
    estimated_minutes: int = 0

@dataclass
class TerrainReport:
    """Full terrain analysis report."""
    timestamp: str = ""
    files_scanned: int = 0
    total_functions: int = 0
    cells: List[TerrainCell] = field(default_factory=list)
    peaks: List[str] = field(default_factory=list)
    valleys: List[str] = field(default_factory=list)
    ridges: List[Ridge] = field(default_factory=list)
    trails: List[Trail] = field(default_factory=list)
    erosion_zones: List[str] = field(default_factory=list)
    health_score: float = 0.0
    insights: List[str] = field(default_factory=list)
    elevation_histogram: Dict[str, int] = field(default_factory=dict)

# ── T001: Elevation Mapper ───────────────────────────────────────────

def _analyze_file(filepath: str) -> List[TerrainCell]:
    """Parse a .srv file and extract function-level terrain cells."""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
    except OSError:
        return []

    cells = []
    current = None
    base_indent = 0
    all_lines_text = "".join(lines)

    for i, raw in enumerate(lines):
        line = raw.rstrip()
        stripped = line.lstrip()
        if not stripped or stripped.startswith('#'):
            if current:
                current.loc += 0  # blank/comment inside fn doesn't count
            continue

        indent = _get_indent(raw)
        m = FUNCTION_DEF.match(line)
        if m:
            # Close previous function
            current = TerrainCell(
                name=m.group(3), file=os.path.basename(filepath), line=i + 1
            )
            base_indent = indent
            after = line[m.end():].strip()
            if after:
                current.params = len(after.split())
            cells.append(current)
            continue

        if current is not None:
            if indent > base_indent:
                current.loc += 1
                fn_depth = indent - base_indent
                if fn_depth > current.max_depth:
                    current.max_depth = fn_depth
                # Branch complexity
                first_word = stripped.split()[0] if stripped else ""
                if first_word in BRANCH_KEYWORDS:
                    current.complexity += 1
                # Track calls
                for cm in CALL_PATTERN.finditer(stripped):
                    callee = cm.group(1)
                    if callee not in ('print', 'len', 'str', 'int', 'float',
                                      'input', 'range', 'type', 'list', 'dict',
                                      'set', 'abs', 'min', 'max', 'sum',
                                      'if', 'while', 'for', 'elif'):
                        if callee not in current.calls:
                            current.calls.append(callee)
            else:
                current = None

    return cells


def _compute_elevations(cells: List[TerrainCell]) -> None:
    """Normalize complexity into elevation 0-100 across all cells."""
    if not cells:
        return
    # Composite raw score: complexity * 3 + depth * 2 + log(loc+1) * 2
    for c in cells:
        c.elevation = c.complexity * 3.0 + c.max_depth * 2.0 + math.log(c.loc + 1) * 2.0

    max_elev = max(c.elevation for c in cells)
    min_elev = min(c.elevation for c in cells)
    span = max_elev - min_elev if max_elev > min_elev else 1.0

    for c in cells:
        c.elevation = round(((c.elevation - min_elev) / span) * 100, 1)
        # Assign risk tier
        if c.elevation >= 80:
            c.risk_tier = "peak"
        elif c.elevation >= 55:
            c.risk_tier = "mountain"
        elif c.elevation >= 30:
            c.risk_tier = "hill"
        else:
            c.risk_tier = "plain"


# ── T002: Peak Detector ─────────────────────────────────────────────

def _detect_peaks(cells: List[TerrainCell], call_graph: Dict[str, Set[str]]) -> List[str]:
    """Find local maxima — functions higher than all their neighbors."""
    peaks = []
    cell_map = {c.fqn: c for c in cells}

    for c in cells:
        if c.elevation < 40:
            continue
        neighbors = []
        # Neighbors = functions it calls + functions that call it
        for callee_name in c.calls:
            for other in cells:
                if other.name == callee_name and other.fqn != c.fqn:
                    neighbors.append(other)
        for other in cells:
            if c.name in other.calls and other.fqn != c.fqn:
                neighbors.append(other)

        if not neighbors:
            # Isolated high-complexity function is always a peak
            if c.elevation >= 60:
                c.is_peak = True
                peaks.append(c.fqn)
        elif all(c.elevation > n.elevation for n in neighbors):
            c.is_peak = True
            peaks.append(c.fqn)

    return peaks


# ── T003: Valley Finder ─────────────────────────────────────────────

def _detect_valleys(cells: List[TerrainCell]) -> List[str]:
    """Find local minima — unexpectedly simple among complex neighbors."""
    valleys = []

    for c in cells:
        if c.elevation > 30:
            continue
        neighbors = []
        for other in cells:
            if other.fqn == c.fqn:
                continue
            if c.name in other.calls or other.name in c.calls:
                neighbors.append(other)

        if neighbors and len(neighbors) >= 2:
            avg_neighbor = sum(n.elevation for n in neighbors) / len(neighbors)
            if avg_neighbor > 50 and c.elevation < avg_neighbor * 0.4:
                c.is_valley = True
                valleys.append(c.fqn)

    return valleys


# ── T004: Ridge Tracer ───────────────────────────────────────────────

def _trace_ridges(cells: List[TerrainCell]) -> List[Ridge]:
    """Find chains of connected high-complexity functions."""
    high_cells = [c for c in cells if c.elevation >= 50]
    if not high_cells:
        return []

    # Build adjacency among high cells
    adj: Dict[str, Set[str]] = defaultdict(set)
    for c in high_cells:
        for other in high_cells:
            if c.fqn == other.fqn:
                continue
            if c.name in other.calls or other.name in c.calls or c.file == other.file:
                # Same file adjacency counts too (within same file + high complexity)
                if c.file == other.file and abs(c.line - other.line) > 100:
                    continue
                adj[c.fqn].add(other.fqn)

    # BFS to find connected components
    visited: Set[str] = set()
    ridges: List[Ridge] = []
    ridge_id = 0
    cell_map = {c.fqn: c for c in cells}

    for c in high_cells:
        if c.fqn in visited:
            continue
        # BFS
        component = []
        queue = [c.fqn]
        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            component.append(node)
            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    queue.append(neighbor)

        if len(component) >= 2:
            r = Ridge(ridge_id=ridge_id, cells=component, length=len(component))
            r.avg_elevation = sum(cell_map[fqn].elevation for fqn in component) / len(component)
            if r.avg_elevation >= 75:
                r.severity = "critical"
            elif r.avg_elevation >= 60:
                r.severity = "high"
            else:
                r.severity = "moderate"
            for fqn in component:
                cell_map[fqn].ridge_id = ridge_id
            ridges.append(r)
            ridge_id += 1

    ridges.sort(key=lambda r: r.avg_elevation, reverse=True)
    return ridges


# ── T005: Erosion Risk Scorer ────────────────────────────────────────

def _compute_erosion(cells: List[TerrainCell]) -> List[str]:
    """Identify functions whose complexity is unsustainable relative to size."""
    erosion_zones = []
    for c in cells:
        if c.loc < 3:
            continue
        # Erosion = complexity density (complexity per LOC) + depth factor
        density = c.complexity / max(c.loc, 1)
        depth_factor = c.max_depth / 10.0
        c.erosion_risk = min(1.0, round(density * 2 + depth_factor, 3))

        if c.erosion_risk >= 0.6:
            erosion_zones.append(c.fqn)

    return erosion_zones


# ── T006: Trail Recommender ──────────────────────────────────────────

def _recommend_trails(cells: List[TerrainCell], ridges: List[Ridge]) -> List[Trail]:
    """Suggest optimal code review traversal orders."""
    trails = []
    if not cells:
        return trails

    cell_map = {c.fqn: c for c in cells}

    # Trail 1: Gentle Ascent — start from lowest, climb to highest
    sorted_by_elev = sorted(cells, key=lambda c: c.elevation)
    gentle = Trail(
        name="Gentle Ascent",
        description="Start from simplest functions, gradually climbing to most complex. "
                    "Builds context before tackling hard areas.",
        steps=[c.fqn for c in sorted_by_elev[:min(15, len(sorted_by_elev))]],
        difficulty="easy",
        estimated_minutes=max(5, len(sorted_by_elev[:15]) * 3)
    )
    trails.append(gentle)

    # Trail 2: Peak Summit — tackle the hardest functions directly
    peaks = [c for c in cells if c.is_peak]
    if peaks:
        summit = Trail(
            name="Peak Summit",
            description="Direct path to the highest complexity peaks. "
                        "For experienced reviewers who want to tackle risk first.",
            steps=[c.fqn for c in sorted(peaks, key=lambda c: -c.elevation)[:10]],
            difficulty="hard",
            estimated_minutes=max(10, len(peaks[:10]) * 5)
        )
        trails.append(summit)

    # Trail 3: Ridge Walk — follow a complexity ridge end-to-end
    if ridges:
        longest = max(ridges, key=lambda r: r.length)
        ridge_trail = Trail(
            name=f"Ridge Walk (Ridge #{longest.ridge_id})",
            description=f"Follow the longest complexity ridge ({longest.length} functions, "
                        f"avg elevation {longest.avg_elevation:.0f}). "
                        "Reveals tightly coupled complex clusters.",
            steps=longest.cells[:15],
            difficulty="hard" if longest.avg_elevation >= 70 else "moderate",
            estimated_minutes=max(10, longest.length * 4)
        )
        trails.append(ridge_trail)

    # Trail 4: Erosion Patrol — check functions at risk of degradation
    eroding = [c for c in cells if c.erosion_risk >= 0.5]
    if eroding:
        patrol = Trail(
            name="Erosion Patrol",
            description="Inspect functions with unsustainable complexity-to-size ratios. "
                        "These are most likely to degrade further without intervention.",
            steps=[c.fqn for c in sorted(eroding, key=lambda c: -c.erosion_risk)[:10]],
            difficulty="moderate",
            estimated_minutes=max(8, len(eroding[:10]) * 3)
        )
        trails.append(patrol)

    # Trail 5: Valley Expedition — investigate suspiciously simple functions
    valley_cells = [c for c in cells if c.is_valley]
    if valley_cells:
        expedition = Trail(
            name="Valley Expedition",
            description="Visit unexpectedly simple functions surrounded by complex neighbors. "
                        "May indicate under-implemented stubs or missing error handling.",
            steps=[c.fqn for c in valley_cells[:10]],
            difficulty="easy",
            estimated_minutes=max(5, len(valley_cells[:10]) * 2)
        )
        trails.append(expedition)

    return trails


# ── T007: Terrain Health Scorer ──────────────────────────────────────

def _compute_health(cells: List[TerrainCell], peaks: List[str],
                    ridges: List[Ridge], erosion_zones: List[str]) -> Tuple[float, List[str]]:
    """Compute composite terrain health 0-100 and generate insights."""
    if not cells:
        return 100.0, ["No functions found — empty terrain."]

    insights = []
    score = 100.0

    # Factor 1: Elevation distribution (prefer mostly low)
    avg_elev = sum(c.elevation for c in cells) / len(cells)
    if avg_elev > 60:
        score -= 25
        insights.append(f"⛰️ High average elevation ({avg_elev:.0f}/100) — codebase is broadly complex.")
    elif avg_elev > 40:
        score -= 10
        insights.append(f"🏔️ Moderate average elevation ({avg_elev:.0f}/100) — some areas need simplification.")
    else:
        insights.append(f"🌿 Low average elevation ({avg_elev:.0f}/100) — terrain is mostly accessible.")

    # Factor 2: Peak concentration
    peak_ratio = len(peaks) / max(len(cells), 1)
    if peak_ratio > 0.3:
        score -= 20
        insights.append(f"🔴 {len(peaks)} peaks ({peak_ratio:.0%} of functions) — too many complexity hotspots.")
    elif peak_ratio > 0.15:
        score -= 10
        insights.append(f"🟡 {len(peaks)} peaks ({peak_ratio:.0%}) — moderate number of hotspots.")
    elif peaks:
        insights.append(f"🟢 Only {len(peaks)} peak(s) — complexity is well-contained.")

    # Factor 3: Ridge severity
    critical_ridges = [r for r in ridges if r.severity == "critical"]
    if critical_ridges:
        score -= 15
        insights.append(f"🔥 {len(critical_ridges)} critical ridge(s) — connected clusters of extreme complexity.")
    elif ridges:
        score -= 5
        insights.append(f"⚡ {len(ridges)} ridge(s) detected — some complexity corridors exist.")

    # Factor 4: Erosion risk
    high_erosion = [c for c in cells if c.erosion_risk >= 0.7]
    if len(high_erosion) > 3:
        score -= 15
        insights.append(f"🌊 {len(high_erosion)} functions at high erosion risk — unsustainable complexity density.")
    elif high_erosion:
        score -= 5
        insights.append(f"💧 {len(high_erosion)} function(s) with elevated erosion risk.")

    # Factor 5: Terrain uniformity (std dev)
    if len(cells) > 1:
        mean = sum(c.elevation for c in cells) / len(cells)
        variance = sum((c.elevation - mean) ** 2 for c in cells) / len(cells)
        std_dev = math.sqrt(variance)
        if std_dev > 35:
            score -= 10
            insights.append(f"📊 High terrain variance (σ={std_dev:.1f}) — extreme differences between functions.")
        elif std_dev < 10 and avg_elev < 30:
            score += 5
            insights.append(f"✅ Very uniform low terrain (σ={std_dev:.1f}) — consistently simple code.")

    # Autonomous recommendations
    if score < 50:
        insights.append("🚨 TERRAIN ALERT: Codebase landscape is rugged — prioritize refactoring peaks and ridges.")
    elif score < 70:
        insights.append("⚠️ Terrain is moderately rough — consider smoothing the highest peaks.")

    return max(0, min(100, round(score, 1))), insights


# ── CLI Output ───────────────────────────────────────────────────────

def _tier_icon(tier: str) -> str:
    return {"peak": "🏔️", "mountain": "⛰️", "hill": "🌄", "plain": "🌿"}.get(tier, "·")


def _print_terrain_map(report: TerrainReport) -> None:
    """Print ASCII terrain visualization."""
    if not report.cells:
        print("  (no functions found)")
        return

    # Group by file
    by_file: Dict[str, List[TerrainCell]] = defaultdict(list)
    for c in report.cells:
        by_file[c.file].append(c)

    for fname, cells in sorted(by_file.items()):
        print(f"\n  {bold(fname)}")
        cells.sort(key=lambda c: c.line)
        for c in cells:
            bar_len = int(c.elevation / 2)
            bar_char = "█" if c.elevation >= 60 else "▓" if c.elevation >= 30 else "░"
            bar = bar_char * bar_len
            markers = ""
            if c.is_peak:
                markers += " △PEAK"
            if c.is_valley:
                markers += " ▽VALLEY"
            if c.erosion_risk >= 0.6:
                markers += " ⚠EROSION"
            if c.ridge_id >= 0:
                markers += f" ~R{c.ridge_id}"

            tier_str = _tier_icon(c.risk_tier)
            elev_str = f"{c.elevation:5.1f}"
            if c.elevation >= 80:
                elev_str = red(elev_str)
            elif c.elevation >= 55:
                elev_str = yellow(elev_str)
            elif c.elevation >= 30:
                elev_str = cyan(elev_str)
            else:
                elev_str = green(elev_str)

            print(f"    {tier_str} {c.name:<30s} {elev_str} {bar}{markers}")


def _print_report(report: TerrainReport) -> None:
    """Print full terrain analysis to terminal."""
    print(bold("\n╔══════════════════════════════════════════════════════════╗"))
    print(bold("║        sauravterrain — Code Complexity Terrain Map      ║"))
    print(bold("╚══════════════════════════════════════════════════════════╝"))

    print(f"\n  Files: {report.files_scanned}  |  Functions: {report.total_functions}  |  "
          f"Health: {_health_badge(report.health_score)}")

    # Elevation histogram
    print(bold("\n  ── Elevation Distribution ──"))
    tiers = Counter(c.risk_tier for c in report.cells)
    total = max(len(report.cells), 1)
    for tier_name, icon in [("plain", "🌿"), ("hill", "🌄"), ("mountain", "⛰️"), ("peak", "🏔️")]:
        count = tiers.get(tier_name, 0)
        pct = count / total * 100
        bar = "█" * int(pct / 2)
        print(f"    {icon} {tier_name:<10s} {count:3d} ({pct:4.1f}%) {bar}")

    # Terrain map
    print(bold("\n  ── Terrain Map ──"))
    _print_terrain_map(report)

    # Peaks
    if report.peaks:
        print(bold(f"\n  ── Peaks ({len(report.peaks)}) ──"))
        cell_map = {c.fqn: c for c in report.cells}
        for fqn in report.peaks[:10]:
            c = cell_map[fqn]
            print(f"    △ {red(f'{c.elevation:5.1f}')}  {c.fqn}  (CC={c.complexity}, depth={c.max_depth}, LOC={c.loc})")

    # Valleys
    if report.valleys:
        print(bold(f"\n  ── Valleys ({len(report.valleys)}) ──"))
        cell_map = {c.fqn: c for c in report.cells}
        for fqn in report.valleys[:10]:
            c = cell_map[fqn]
            print(f"    ▽ {green(f'{c.elevation:5.1f}')}  {c.fqn}  (CC={c.complexity}, LOC={c.loc})")

    # Ridges
    if report.ridges:
        print(bold(f"\n  ── Ridges ({len(report.ridges)}) ──"))
        for r in report.ridges[:5]:
            sev_color = red if r.severity == "critical" else yellow if r.severity == "high" else cyan
            print(f"    ~R{r.ridge_id}  {sev_color(r.severity):<10s}  "
                  f"len={r.length}  avg_elev={r.avg_elevation:.0f}  {', '.join(r.cells[:5])}"
                  f"{'...' if len(r.cells) > 5 else ''}")

    # Erosion zones
    if report.erosion_zones:
        print(bold(f"\n  ── Erosion Risk Zones ({len(report.erosion_zones)}) ──"))
        cell_map = {c.fqn: c for c in report.cells}
        for fqn in report.erosion_zones[:10]:
            c = cell_map[fqn]
            risk_bar = "█" * int(c.erosion_risk * 10)
            print(f"    ⚠ {yellow(f'{c.erosion_risk:.2f}')}  {risk_bar}  {c.fqn}")

    # Trails
    if report.trails:
        print(bold(f"\n  ── Recommended Trails ({len(report.trails)}) ──"))
        for t in report.trails:
            diff_color = red if t.difficulty == "hard" else yellow if t.difficulty == "moderate" else green
            print(f"    🥾 {bold(t.name)} ({diff_color(t.difficulty)}, ~{t.estimated_minutes}min)")
            print(f"       {dim(t.description)}")
            for i, step in enumerate(t.steps[:5], 1):
                print(f"       {i}. {step}")
            if len(t.steps) > 5:
                print(f"       ... +{len(t.steps) - 5} more")

    # Insights
    print(bold("\n  ── Terrain Insights ──"))
    for insight in report.insights:
        print(f"    {insight}")

    print()


def _health_badge(score: float) -> str:
    if score >= 80:
        return green(f"{score:.0f}/100 ✅")
    elif score >= 60:
        return yellow(f"{score:.0f}/100 ⚠️")
    elif score >= 40:
        return yellow(f"{score:.0f}/100 🟡")
    else:
        return red(f"{score:.0f}/100 🔴")


# ── HTML Dashboard ───────────────────────────────────────────────────

def _generate_html(report: TerrainReport) -> str:
    """Generate interactive HTML terrain dashboard."""
    import html as _html

    def esc(s):
        return _html.escape(str(s))

    cells_json = json.dumps([{
        "name": c.name, "file": c.file, "line": c.line, "loc": c.loc,
        "complexity": c.complexity, "max_depth": c.max_depth,
        "elevation": c.elevation, "risk_tier": c.risk_tier,
        "erosion_risk": c.erosion_risk, "is_peak": c.is_peak,
        "is_valley": c.is_valley, "ridge_id": c.ridge_id, "fqn": c.fqn
    } for c in report.cells])

    ridges_json = json.dumps([{
        "ridge_id": r.ridge_id, "cells": r.cells, "avg_elevation": r.avg_elevation,
        "length": r.length, "severity": r.severity
    } for r in report.ridges])

    trails_json = json.dumps([{
        "name": t.name, "description": t.description, "steps": t.steps,
        "difficulty": t.difficulty, "estimated_minutes": t.estimated_minutes
    } for t in report.trails])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>sauravterrain — Code Complexity Terrain Map</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#0a0e17;color:#c9d1d9;line-height:1.6}}
.header{{background:linear-gradient(135deg,#1a1e2e,#0d1117);padding:24px 32px;border-bottom:1px solid #30363d}}
.header h1{{font-size:1.6em;color:#58a6ff}}
.header .sub{{color:#8b949e;font-size:0.9em;margin-top:4px}}
.stats{{display:flex;gap:16px;flex-wrap:wrap;padding:16px 32px;background:#161b22;border-bottom:1px solid #21262d}}
.stat{{background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:12px 20px;min-width:130px}}
.stat .val{{font-size:1.8em;font-weight:700}}
.stat .lbl{{font-size:0.75em;color:#8b949e;text-transform:uppercase}}
.health-good .val{{color:#3fb950}} .health-warn .val{{color:#d29922}} .health-bad .val{{color:#f85149}}
.tabs{{display:flex;gap:0;padding:0 32px;background:#161b22;border-bottom:1px solid #21262d}}
.tab{{padding:10px 20px;cursor:pointer;color:#8b949e;border-bottom:2px solid transparent;transition:all .2s}}
.tab:hover{{color:#c9d1d9}} .tab.active{{color:#58a6ff;border-bottom-color:#58a6ff}}
.panels{{padding:20px 32px}}
.panel{{display:none}} .panel.active{{display:block}}
table{{width:100%;border-collapse:collapse;font-size:0.85em}}
th{{text-align:left;padding:8px 12px;background:#161b22;color:#8b949e;border-bottom:1px solid #30363d;position:sticky;top:0}}
td{{padding:8px 12px;border-bottom:1px solid #21262d}}
tr:hover td{{background:#161b22}}
.bar{{height:14px;border-radius:3px;display:inline-block;vertical-align:middle}}
.bar-peak{{background:linear-gradient(90deg,#f85149,#da3633)}}
.bar-mountain{{background:linear-gradient(90deg,#d29922,#e3b341)}}
.bar-hill{{background:linear-gradient(90deg,#58a6ff,#388bfd)}}
.bar-plain{{background:linear-gradient(90deg,#3fb950,#2ea043)}}
.badge{{padding:2px 8px;border-radius:12px;font-size:0.75em;font-weight:600}}
.badge-peak{{background:#f8514922;color:#f85149}} .badge-mountain{{background:#d2992222;color:#d29922}}
.badge-hill{{background:#58a6ff22;color:#58a6ff}} .badge-plain{{background:#3fb95022;color:#3fb950}}
.badge-critical{{background:#f8514933;color:#f85149}} .badge-high{{background:#d2992233;color:#d29922}}
.badge-moderate{{background:#58a6ff33;color:#58a6ff}}
.badge-hard{{background:#f8514922;color:#f85149}} .badge-easy{{background:#3fb95022;color:#3fb950}}
.insight{{padding:8px 14px;margin:6px 0;background:#161b22;border-left:3px solid #58a6ff;border-radius:4px}}
.marker{{font-size:0.7em;padding:1px 6px;border-radius:4px;margin-left:6px}}
.marker-peak{{background:#f8514933;color:#f85149}} .marker-valley{{background:#3fb95033;color:#3fb950}}
.marker-erosion{{background:#d2992233;color:#d29922}}
.trail-card{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin:10px 0}}
.trail-card h3{{color:#58a6ff;font-size:1em}} .trail-card .desc{{color:#8b949e;font-size:0.85em;margin:6px 0}}
.trail-step{{padding:4px 0;font-size:0.85em;color:#c9d1d9}}
.search{{padding:6px 14px;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;width:260px;margin-bottom:12px}}
.histo-row{{display:flex;align-items:center;gap:8px;margin:4px 0}}
.histo-label{{width:80px;text-align:right;font-size:0.85em;color:#8b949e}}
.histo-bar{{height:20px;border-radius:3px;min-width:2px}}
.histo-count{{font-size:0.8em;color:#8b949e}}
</style>
</head>
<body>
<div class="header">
  <h1>⛰️ sauravterrain — Code Complexity Terrain Map</h1>
  <div class="sub">Generated {esc(report.timestamp)} · {report.files_scanned} files · {report.total_functions} functions</div>
</div>
<div class="stats">
  <div class="stat {'health-good' if report.health_score >= 70 else 'health-warn' if report.health_score >= 40 else 'health-bad'}">
    <div class="val">{report.health_score:.0f}</div><div class="lbl">Health Score</div></div>
  <div class="stat"><div class="val">{report.total_functions}</div><div class="lbl">Functions</div></div>
  <div class="stat"><div class="val">{len(report.peaks)}</div><div class="lbl">Peaks</div></div>
  <div class="stat"><div class="val">{len(report.ridges)}</div><div class="lbl">Ridges</div></div>
  <div class="stat"><div class="val">{len(report.erosion_zones)}</div><div class="lbl">Erosion Zones</div></div>
  <div class="stat"><div class="val">{len(report.trails)}</div><div class="lbl">Trails</div></div>
</div>
<div class="tabs">
  <div class="tab active" onclick="showTab('terrain')">Terrain Map</div>
  <div class="tab" onclick="showTab('peaks')">Peaks & Valleys</div>
  <div class="tab" onclick="showTab('ridges')">Ridges</div>
  <div class="tab" onclick="showTab('trails')">Trails</div>
  <div class="tab" onclick="showTab('insights')">Insights</div>
</div>
<div class="panels">
  <div class="panel active" id="panel-terrain"></div>
  <div class="panel" id="panel-peaks"></div>
  <div class="panel" id="panel-ridges"></div>
  <div class="panel" id="panel-trails"></div>
  <div class="panel" id="panel-insights"></div>
</div>
<script>
const cells={cells_json};
const ridges={ridges_json};
const trails={trails_json};
const insights={json.dumps(report.insights)};

function showTab(id){{
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById('panel-'+id).classList.add('active');
}}

function tierBadge(tier){{return '<span class="badge badge-'+tier+'">'+tier+'</span>';}}
function elevBar(e,tier){{return '<span class="bar bar-'+tier+'" style="width:'+Math.max(2,e*2)+'px"></span> '+e.toFixed(1);}}
function markers(c){{
  let m='';
  if(c.is_peak) m+='<span class="marker marker-peak">PEAK</span>';
  if(c.is_valley) m+='<span class="marker marker-valley">VALLEY</span>';
  if(c.erosion_risk>=0.6) m+='<span class="marker marker-erosion">EROSION</span>';
  if(c.ridge_id>=0) m+='<span class="marker" style="background:#58a6ff33;color:#58a6ff">R'+c.ridge_id+'</span>';
  return m;
}}

// Terrain tab
(function(){{
  let h='<input class="search" id="terrainSearch" placeholder="Filter functions..." oninput="filterTerrain()"><br>';
  // Elevation histogram
  const buckets=[0,0,0,0,0];
  const labels=['0-20','20-40','40-60','60-80','80-100'];
  const colors=['#3fb950','#58a6ff','#d29922','#e3b341','#f85149'];
  cells.forEach(c=>{{const i=Math.min(4,Math.floor(c.elevation/20));buckets[i]++;}});
  const mx=Math.max(...buckets,1);
  h+='<h3 style="margin:10px 0">Elevation Distribution</h3>';
  for(let i=0;i<5;i++){{
    h+='<div class="histo-row"><span class="histo-label">'+labels[i]+'</span>'
      +'<span class="histo-bar" style="width:'+Math.max(2,buckets[i]/mx*300)+'px;background:'+colors[i]+'"></span>'
      +'<span class="histo-count">'+buckets[i]+'</span></div>';
  }}
  h+='<table id="terrainTable"><thead><tr><th>Function</th><th>File</th><th>Line</th><th>Elevation</th><th>CC</th><th>Depth</th><th>LOC</th><th>Erosion</th><th>Markers</th></tr></thead><tbody>';
  const sorted=[...cells].sort((a,b)=>b.elevation-a.elevation);
  sorted.forEach(c=>{{
    h+='<tr><td>'+c.name+'</td><td>'+c.file+'</td><td>'+c.line+'</td>'
      +'<td>'+elevBar(c.elevation,c.risk_tier)+'</td>'
      +'<td>'+c.complexity+'</td><td>'+c.max_depth+'</td><td>'+c.loc+'</td>'
      +'<td>'+(c.erosion_risk>=0.6?'<span style="color:#d29922">'+c.erosion_risk.toFixed(2)+'</span>':c.erosion_risk.toFixed(2))+'</td>'
      +'<td>'+markers(c)+'</td></tr>';
  }});
  h+='</tbody></table>';
  document.getElementById('panel-terrain').innerHTML=h;
}})();

window.filterTerrain=function(){{
  const q=document.getElementById('terrainSearch').value.toLowerCase();
  document.querySelectorAll('#terrainTable tbody tr').forEach(r=>{{
    r.style.display=r.textContent.toLowerCase().includes(q)?'':'none';
  }});
}};

// Peaks & Valleys tab
(function(){{
  const peaks=cells.filter(c=>c.is_peak).sort((a,b)=>b.elevation-a.elevation);
  const valleys=cells.filter(c=>c.is_valley).sort((a,b)=>a.elevation-b.elevation);
  let h='<h3 style="margin:10px 0">△ Peaks ('+peaks.length+')</h3>';
  if(peaks.length){{
    h+='<table><thead><tr><th>Function</th><th>File</th><th>Elevation</th><th>CC</th><th>Depth</th><th>LOC</th></tr></thead><tbody>';
    peaks.forEach(c=>{{h+='<tr><td>'+c.name+'</td><td>'+c.file+'</td><td>'+elevBar(c.elevation,c.risk_tier)+'</td><td>'+c.complexity+'</td><td>'+c.max_depth+'</td><td>'+c.loc+'</td></tr>';}});
    h+='</tbody></table>';
  }} else h+='<p style="color:#8b949e">No peaks detected.</p>';
  h+='<h3 style="margin:20px 0 10px">▽ Valleys ('+valleys.length+')</h3>';
  if(valleys.length){{
    h+='<table><thead><tr><th>Function</th><th>File</th><th>Elevation</th><th>CC</th><th>LOC</th></tr></thead><tbody>';
    valleys.forEach(c=>{{h+='<tr><td>'+c.name+'</td><td>'+c.file+'</td><td>'+elevBar(c.elevation,c.risk_tier)+'</td><td>'+c.complexity+'</td><td>'+c.loc+'</td></tr>';}});
    h+='</tbody></table>';
  }} else h+='<p style="color:#8b949e">No valleys detected.</p>';
  document.getElementById('panel-peaks').innerHTML=h;
}})();

// Ridges tab
(function(){{
  let h='<h3 style="margin:10px 0">Complexity Ridges ('+ridges.length+')</h3>';
  if(!ridges.length){{h+='<p style="color:#8b949e">No ridges detected.</p>';}}
  ridges.forEach(r=>{{
    h+='<div class="trail-card"><h3>Ridge #'+r.ridge_id+' <span class="badge badge-'+r.severity+'">'+r.severity+'</span></h3>'
      +'<div class="desc">Length: '+r.length+' functions · Avg elevation: '+r.avg_elevation.toFixed(1)+'</div>';
    r.cells.forEach((fqn,i)=>{{h+='<div class="trail-step">'+(i+1)+'. '+fqn+'</div>';}});
    h+='</div>';
  }});
  document.getElementById('panel-ridges').innerHTML=h;
}})();

// Trails tab
(function(){{
  let h='<h3 style="margin:10px 0">Recommended Review Trails ('+trails.length+')</h3>';
  trails.forEach(t=>{{
    h+='<div class="trail-card"><h3>🥾 '+t.name+' <span class="badge badge-'+t.difficulty+'">'+t.difficulty+'</span> · ~'+t.estimated_minutes+'min</h3>'
      +'<div class="desc">'+t.description+'</div>';
    t.steps.forEach((s,i)=>{{h+='<div class="trail-step">'+(i+1)+'. '+s+'</div>';}});
    h+='</div>';
  }});
  document.getElementById('panel-trails').innerHTML=h;
}})();

// Insights tab
(function(){{
  let h='<h3 style="margin:10px 0">Autonomous Terrain Insights</h3>';
  insights.forEach(i=>{{h+='<div class="insight">'+i+'</div>';}});
  document.getElementById('panel-insights').innerHTML=h;
}})();
</script>
</body></html>"""


# ── Main Analysis Pipeline ───────────────────────────────────────────

def analyze_terrain(paths: List[str], recursive: bool = False) -> TerrainReport:
    """Run full terrain analysis pipeline."""
    srv_files = _find_srv_files(paths, recursive=recursive)
    report = TerrainReport(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        files_scanned=len(srv_files)
    )

    # T001: Collect cells from all files
    all_cells: List[TerrainCell] = []
    for fp in srv_files:
        all_cells.extend(_analyze_file(fp))

    report.total_functions = len(all_cells)
    report.cells = all_cells

    # Compute elevations
    _compute_elevations(all_cells)

    # Build call graph for neighbor lookups
    call_graph: Dict[str, Set[str]] = defaultdict(set)
    for c in all_cells:
        for callee in c.calls:
            call_graph[c.fqn].add(callee)

    # T002: Peaks
    report.peaks = _detect_peaks(all_cells, call_graph)

    # T003: Valleys
    report.valleys = _detect_valleys(all_cells)

    # T004: Ridges
    report.ridges = _trace_ridges(all_cells)

    # T005: Erosion
    report.erosion_zones = _compute_erosion(all_cells)

    # T006: Trails
    report.trails = _recommend_trails(all_cells, report.ridges)

    # T007: Health
    report.health_score, report.insights = _compute_health(
        all_cells, report.peaks, report.ridges, report.erosion_zones
    )

    # Elevation histogram
    buckets = {"0-20": 0, "20-40": 0, "40-60": 0, "60-80": 0, "80-100": 0}
    for c in all_cells:
        idx = min(4, int(c.elevation / 20))
        key = list(buckets.keys())[idx]
        buckets[key] += 1
    report.elevation_histogram = buckets

    return report


# ── CLI ──────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sauravterrain",
        description="Autonomous code complexity terrain mapper for sauravcode"
    )
    parser.add_argument("paths", nargs="*", default=["."],
                        help=".srv files or directories to scan")
    parser.add_argument("--recursive", "-r", action="store_true",
                        help="Recurse into subdirectories")
    parser.add_argument("--html", metavar="FILE",
                        help="Generate interactive HTML dashboard")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON report")
    parser.add_argument("--peaks", action="store_true",
                        help="Show only peaks")
    parser.add_argument("--valleys", action="store_true",
                        help="Show only valleys")
    parser.add_argument("--ridges", action="store_true",
                        help="Show only ridges")
    parser.add_argument("--trails", action="store_true",
                        help="Show recommended review trails")
    parser.add_argument("--erosion", action="store_true",
                        help="Show erosion risk zones")
    parser.add_argument("--top", type=int, default=0,
                        help="Show top N highest elevation cells")
    parser.add_argument("--no-color", action="store_true",
                        help="Disable colored output")

    args = parser.parse_args(argv)

    global USE_COLOR
    if args.no_color:
        USE_COLOR = False

    report = analyze_terrain(args.paths, recursive=args.recursive)

    # JSON output
    if args.json:
        out = {
            "timestamp": report.timestamp,
            "files_scanned": report.files_scanned,
            "total_functions": report.total_functions,
            "health_score": report.health_score,
            "elevation_histogram": report.elevation_histogram,
            "cells": [{
                "name": c.name, "file": c.file, "line": c.line,
                "loc": c.loc, "complexity": c.complexity,
                "max_depth": c.max_depth, "elevation": c.elevation,
                "risk_tier": c.risk_tier, "erosion_risk": c.erosion_risk,
                "is_peak": c.is_peak, "is_valley": c.is_valley,
                "ridge_id": c.ridge_id
            } for c in report.cells],
            "peaks": report.peaks,
            "valleys": report.valleys,
            "ridges": [{"id": r.ridge_id, "cells": r.cells,
                        "avg_elevation": r.avg_elevation, "severity": r.severity}
                       for r in report.ridges],
            "erosion_zones": report.erosion_zones,
            "trails": [{"name": t.name, "description": t.description,
                        "steps": t.steps, "difficulty": t.difficulty,
                        "estimated_minutes": t.estimated_minutes}
                       for t in report.trails],
            "insights": report.insights
        }
        print(json.dumps(out, indent=2))
        return 0

    # HTML output
    if args.html:
        html_content = _generate_html(report)
        with open(args.html, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"  HTML terrain dashboard → {args.html}")
        return 0

    # Filtered views
    if args.peaks:
        cell_map = {c.fqn: c for c in report.cells}
        print(bold(f"\n  △ Peaks ({len(report.peaks)})"))
        for fqn in report.peaks:
            c = cell_map[fqn]
            print(f"    {red(f'{c.elevation:5.1f}')}  {c.fqn}  (CC={c.complexity}, depth={c.max_depth})")
        return 0

    if args.valleys:
        cell_map = {c.fqn: c for c in report.cells}
        print(bold(f"\n  ▽ Valleys ({len(report.valleys)})"))
        for fqn in report.valleys:
            c = cell_map[fqn]
            print(f"    {green(f'{c.elevation:5.1f}')}  {c.fqn}  (CC={c.complexity})")
        return 0

    if args.ridges:
        print(bold(f"\n  ~ Ridges ({len(report.ridges)})"))
        for r in report.ridges:
            print(f"    R{r.ridge_id} [{r.severity}] len={r.length} avg={r.avg_elevation:.0f}  "
                  f"{', '.join(r.cells)}")
        return 0

    if args.trails:
        print(bold(f"\n  🥾 Trails ({len(report.trails)})"))
        for t in report.trails:
            print(f"\n    {bold(t.name)} ({t.difficulty}, ~{t.estimated_minutes}min)")
            print(f"    {t.description}")
            for i, s in enumerate(t.steps, 1):
                print(f"      {i}. {s}")
        return 0

    if args.erosion:
        cell_map = {c.fqn: c for c in report.cells}
        print(bold(f"\n  ⚠ Erosion Zones ({len(report.erosion_zones)})"))
        for fqn in report.erosion_zones:
            c = cell_map[fqn]
            print(f"    {c.erosion_risk:.2f}  {c.fqn}  (CC={c.complexity}, LOC={c.loc})")
        return 0

    if args.top > 0:
        sorted_cells = sorted(report.cells, key=lambda c: -c.elevation)[:args.top]
        print(bold(f"\n  Top {args.top} Highest Elevation Functions"))
        for i, c in enumerate(sorted_cells, 1):
            print(f"    {i:2d}. {_tier_icon(c.risk_tier)} {c.elevation:5.1f}  {c.fqn}  "
                  f"(CC={c.complexity}, depth={c.max_depth}, LOC={c.loc})")
        return 0

    # Full report
    _print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
