#!/usr/bin/env python3
"""
sauravdigest — Autonomous Codebase Digest for sauravcode projects.

Scans all .srv files in a directory and generates a comprehensive project
health report with metrics, complexity analysis, dependency mapping,
code pattern detection, and proactive improvement recommendations.

Usage:
    python sauravdigest.py                        # Scan current directory
    python sauravdigest.py path/to/project        # Scan specific directory
    python sauravdigest.py --html report.html     # Generate HTML report
    python sauravdigest.py --json                 # JSON output
    python sauravdigest.py --watch                # Re-scan on file changes
    python sauravdigest.py --compare old.json     # Compare with previous digest
"""

import sys
import os
import re
import json as _json
import math
import time as _time
import glob
from collections import defaultdict, Counter
from typing import TYPE_CHECKING
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Set

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FileMetrics:
    """Metrics for a single .srv file."""
    path: str
    lines: int = 0
    code_lines: int = 0
    comment_lines: int = 0
    blank_lines: int = 0
    functions: List[str] = field(default_factory=list)
    classes: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    max_nesting: int = 0
    avg_line_length: float = 0.0
    max_line_length: int = 0
    complexity_score: float = 0.0
    patterns: List[str] = field(default_factory=list)


@dataclass
class ProjectDigest:
    """Aggregated project digest."""
    directory: str
    scan_time: str = ""
    total_files: int = 0
    total_lines: int = 0
    total_code_lines: int = 0
    total_comment_lines: int = 0
    total_blank_lines: int = 0
    total_functions: int = 0
    total_classes: int = 0
    avg_file_size: float = 0.0
    largest_file: str = ""
    largest_file_lines: int = 0
    most_complex_file: str = ""
    most_complex_score: float = 0.0
    comment_ratio: float = 0.0
    health_score: float = 0.0
    health_grade: str = ""
    files: List[FileMetrics] = field(default_factory=list)
    dependency_graph: Dict[str, List[str]] = field(default_factory=dict)
    pattern_counts: Dict[str, int] = field(default_factory=dict)
    hotspots: List[Dict] = field(default_factory=list)
    recommendations: List[Dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Analysis engine
# ---------------------------------------------------------------------------

# Patterns we detect in .srv code — pre-compiled at module level
# instead of calling re.search(raw_string, ...) on every line.
_PATTERN_DEFS_RAW = {
    "error_handling": r'\b(try|catch|throw)\b',
    "loops": r'\b(for|while|foreach)\b',
    "conditionals": r'\b(if|else|elif|match)\b',
    "list_comprehension": r'\[.+\bfor\b.+\bin\b.+\]',
    "pipe_operator": r'\|>',
    "lambda": r'\blambda\b',
    "class_usage": r'\bclass\b',
    "generator": r'\byield\b',
    "async_patterns": r'\b(async|await)\b',
    "f_strings": r'f"[^"]*\{',
    "assertions": r'\bassert\b',
}
# Compiled patterns — skip empty/special entries (recursion_hint is detected separately)
PATTERN_COMPILED = [
    (name, re.compile(pat))
    for name, pat in _PATTERN_DEFS_RAW.items()
    if pat
]
# Keep original dict for feature-diversity checks in generate_recommendations
PATTERN_NAMES = set(_PATTERN_DEFS_RAW.keys()) | {"recursion_hint"}


def _is_comment(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("//") or stripped.startswith("#")


def _is_blank(line: str) -> bool:
    return line.strip() == ""


def _count_nesting(line: str) -> int:
    """Estimate nesting depth from indentation (4-space or 2-space)."""
    stripped = line.lstrip()
    if not stripped:
        return 0
    indent = len(line) - len(stripped)
    # Try 4-space first, then 2-space
    return indent // 4 if indent >= 4 else indent // 2


# Pre-compiled regexes for structure detection in analyze_file
_FN_RE = re.compile(r'\s*(?:fun|function)\s+(\w+)\s*\(')
_CLS_RE = re.compile(r'\s*class\s+(\w+)')
_IMP_RE = re.compile(r'\s*import\s+"([^"]+)"')


def analyze_file(filepath: str) -> FileMetrics:
    """Analyze a single .srv file and return metrics."""
    metrics = FileMetrics(path=filepath)

    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    except (IOError, OSError):
        return metrics

    raw_lines = content.split('\n')
    metrics.lines = len(raw_lines)

    line_lengths = []
    max_nesting = 0
    pattern_hits = defaultdict(int)
    func_names = []
    class_names = []
    import_names = []

    for line in raw_lines:
        if _is_blank(line):
            metrics.blank_lines += 1
        elif _is_comment(line):
            metrics.comment_lines += 1
        else:
            metrics.code_lines += 1

        stripped = line.strip()
        if stripped:
            line_lengths.append(len(stripped))

        # Track nesting
        depth = _count_nesting(line)
        if depth > max_nesting:
            max_nesting = depth

        # Detect functions
        fn_match = _FN_RE.match(line)
        if fn_match:
            func_names.append(fn_match.group(1))

        # Detect classes
        cls_match = _CLS_RE.match(line)
        if cls_match:
            class_names.append(cls_match.group(1))

        # Detect imports
        imp_match = _IMP_RE.match(line)
        if imp_match:
            import_names.append(imp_match.group(1))

        # Pattern detection — uses pre-compiled regexes
        for pname, compiled in PATTERN_COMPILED:
            if compiled.search(line):
                pattern_hits[pname] += 1

    # Check for recursion (function calls its own name)
    # Single alternation regex scans content once — O(L) instead of O(F×L)
    if func_names:
        alt = '|'.join(re.escape(fn) for fn in func_names)
        call_re = re.compile(r'\b(' + alt + r')\s*\(')
        call_counts: Counter = Counter(call_re.findall(content))
        if any(c > 1 for c in call_counts.values()):
            pattern_hits["recursion_hint"] += 1

    metrics.functions = func_names
    metrics.classes = class_names
    metrics.imports = import_names
    metrics.max_nesting = max_nesting
    metrics.avg_line_length = sum(line_lengths) / len(line_lengths) if line_lengths else 0
    metrics.max_line_length = max(line_lengths) if line_lengths else 0
    metrics.patterns = list(pattern_hits.keys())

    # Complexity score: weighted combination of factors
    metrics.complexity_score = (
        metrics.code_lines * 0.1 +
        len(func_names) * 2.0 +
        len(class_names) * 3.0 +
        max_nesting * 5.0 +
        pattern_hits.get("conditionals", 0) * 1.5 +
        pattern_hits.get("loops", 0) * 2.0 +
        pattern_hits.get("error_handling", 0) * 1.0
    )

    return metrics


def build_dependency_graph(files: List[FileMetrics]) -> Dict[str, List[str]]:
    """Build import dependency graph across files."""
    graph = {}
    for fm in files:
        basename = os.path.basename(fm.path)
        deps = []
        for imp in fm.imports:
            dep_name = imp if imp.endswith('.srv') else imp + '.srv'
            deps.append(dep_name)
        graph[basename] = deps
    return graph


def detect_hotspots(files: List[FileMetrics]) -> List[Dict]:
    """Identify files that need attention."""
    hotspots = []
    for fm in files:
        # Compute per-file comment ratio
        cr = fm.comment_lines / max(fm.code_lines, 1)

        reasons = []
        if fm.code_lines > 200:
            reasons.append(f"Large file ({fm.code_lines} code lines)")
        if fm.max_nesting > 5:
            reasons.append(f"Deep nesting (depth {fm.max_nesting})")
        if fm.complexity_score > 100:
            reasons.append(f"High complexity ({fm.complexity_score:.0f})")
        if cr < 0.05 and fm.code_lines > 30:
            reasons.append("Low documentation")
        if len(fm.functions) > 15:
            reasons.append(f"Many functions ({len(fm.functions)})")

        if reasons:
            hotspots.append({
                "file": os.path.basename(fm.path),
                "reasons": reasons,
                "severity": "high" if len(reasons) >= 3 else "medium" if len(reasons) >= 2 else "low"
            })

    return sorted(hotspots, key=lambda h: len(h["reasons"]), reverse=True)


def generate_recommendations(digest: ProjectDigest) -> List[Dict]:
    """Generate proactive improvement recommendations."""
    recs = []

    if digest.comment_ratio < 0.1:
        recs.append({
            "priority": "high",
            "category": "documentation",
            "title": "Increase code documentation",
            "detail": f"Comment ratio is {digest.comment_ratio:.1%}. Aim for 15-25% for maintainability.",
            "action": "Add comments to complex functions and class definitions."
        })

    if digest.most_complex_score > 150:
        recs.append({
            "priority": "high",
            "category": "complexity",
            "title": f"Refactor {digest.most_complex_file}",
            "detail": f"Complexity score {digest.most_complex_score:.0f} is very high.",
            "action": "Break large functions into smaller ones. Extract helper functions."
        })

    large_files = [f for f in digest.files if f.code_lines > 150]
    if large_files:
        recs.append({
            "priority": "medium",
            "category": "structure",
            "title": f"{len(large_files)} file(s) over 150 lines",
            "detail": "Large files are harder to maintain and test.",
            "action": "Consider splitting into modules using import statements."
        })

    # Check for missing error handling
    has_try = any("error_handling" in f.patterns for f in digest.files)
    if not has_try and digest.total_code_lines > 100:
        recs.append({
            "priority": "medium",
            "category": "robustness",
            "title": "Add error handling",
            "detail": "No try/catch blocks found in the project.",
            "action": "Wrap I/O and risky operations in try/catch blocks."
        })

    # Check for test files
    test_files = [f for f in digest.files if "test" in os.path.basename(f.path).lower()]
    if not test_files and digest.total_functions > 5:
        recs.append({
            "priority": "medium",
            "category": "testing",
            "title": "Add test coverage",
            "detail": f"No test files found for {digest.total_functions} functions.",
            "action": "Create test_*.srv files using assert statements."
        })

    # Circular dependency check
    visited = set()
    def has_cycle(node, path):
        if node in path:
            return True
        if node in visited:
            return False
        visited.add(node)
        path.add(node)
        for dep in digest.dependency_graph.get(node, []):
            if has_cycle(dep, path):
                return True
        path.discard(node)
        return False

    for node in digest.dependency_graph:
        if has_cycle(node, set()):
            recs.append({
                "priority": "high",
                "category": "architecture",
                "title": "Circular dependency detected",
                "detail": f"File '{node}' is part of a circular import chain.",
                "action": "Restructure imports to break the cycle."
            })
            break

    # Pattern diversity recommendation
    all_patterns = set()
    for f in digest.files:
        all_patterns.update(f.patterns)
    unused_features = {"error_handling", "list_comprehension", "pipe_operator", "lambda", "assertions"} - all_patterns
    if unused_features and digest.total_code_lines > 50:
        recs.append({
            "priority": "low",
            "category": "language_features",
            "title": "Explore more language features",
            "detail": f"Not using: {', '.join(sorted(unused_features))}.",
            "action": "These features can make code more concise and robust."
        })

    return recs


def compute_health_score(digest: ProjectDigest) -> Tuple[float, str]:
    """Compute overall project health score (0-100) and letter grade.

    Reuses pre-computed aggregates (_complexity_sum) from scan_project
    instead of re-iterating digest.files for averages.
    """
    score = 100.0
    n_files = max(len(digest.files), 1)

    # Comment ratio penalty
    if digest.comment_ratio < 0.05:
        score -= 15
    elif digest.comment_ratio < 0.1:
        score -= 8

    # Complexity penalty — reuse cached sum when available
    complexity_sum = getattr(digest, '_complexity_sum', None)
    if complexity_sum is None:
        complexity_sum = sum(f.complexity_score for f in digest.files)
    avg_complexity = complexity_sum / n_files
    if avg_complexity > 100:
        score -= 15
    elif avg_complexity > 60:
        score -= 8

    # Hotspot penalty
    high_hotspots = sum(1 for h in digest.hotspots if h["severity"] == "high")
    score -= high_hotspots * 5

    # File size uniformity — single-pass Welford variance avoids
    # building an intermediate list + two iterations
    if digest.files:
        mean_size = digest.total_code_lines / n_files
        var_sum = 0.0
        for f in digest.files:
            d = f.code_lines - mean_size
            var_sum += d * d
        cv = math.sqrt(var_sum / n_files) / max(mean_size, 1)
        if cv > 2.0:
            score -= 8

    # Recommendation penalty
    high_recs = sum(1 for r in digest.recommendations if r["priority"] == "high")
    score -= high_recs * 5

    score = max(0, min(100, score))

    if score >= 90:
        grade = "A"
    elif score >= 80:
        grade = "B"
    elif score >= 70:
        grade = "C"
    elif score >= 60:
        grade = "D"
    else:
        grade = "F"

    return score, grade


def scan_project(directory: str) -> ProjectDigest:
    """Scan all .srv files in a directory and build a project digest."""
    digest = ProjectDigest(directory=os.path.abspath(directory))
    digest.scan_time = _time.strftime("%Y-%m-%d %H:%M:%S")

    # Find all .srv files
    srv_files = sorted(glob.glob(os.path.join(directory, "**", "*.srv"), recursive=True))
    if not srv_files:
        return digest

    digest.total_files = len(srv_files)

    # Single-pass accumulation: track largest file and most complex file
    # inline instead of separate max() scans at the end.
    _complexity_sum = 0.0
    _size_sum_sq = 0.0  # for variance in health score

    for filepath in srv_files:
        fm = analyze_file(filepath)
        digest.files.append(fm)
        digest.total_lines += fm.lines
        digest.total_code_lines += fm.code_lines
        digest.total_comment_lines += fm.comment_lines
        digest.total_blank_lines += fm.blank_lines
        digest.total_functions += len(fm.functions)
        digest.total_classes += len(fm.classes)
        _complexity_sum += fm.complexity_score

        # Track patterns
        for p in fm.patterns:
            digest.pattern_counts[p] = digest.pattern_counts.get(p, 0) + 1

        # Track largest file (by line count)
        if fm.lines > digest.largest_file_lines:
            digest.largest_file = os.path.basename(fm.path)
            digest.largest_file_lines = fm.lines

        # Track most complex file
        if fm.complexity_score > digest.most_complex_score:
            digest.most_complex_file = os.path.basename(fm.path)
            digest.most_complex_score = fm.complexity_score

    # Averages
    digest.avg_file_size = digest.total_lines / max(digest.total_files, 1)
    digest.comment_ratio = digest.total_comment_lines / max(digest.total_code_lines, 1)

    # Cache aggregates on digest for compute_health_score to reuse
    digest._complexity_sum = _complexity_sum

    # Dependencies
    digest.dependency_graph = build_dependency_graph(digest.files)

    # Hotspots
    digest.hotspots = detect_hotspots(digest.files)

    # Recommendations
    digest.recommendations = generate_recommendations(digest)

    # Health score
    digest.health_score, digest.health_grade = compute_health_score(digest)

    return digest


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def _bar(value: float, max_val: float, width: int = 30) -> str:
    if max_val <= 0:
        return ""
    filled = int(value / max_val * width)
    return "█" * filled + "░" * (width - filled)


def format_text(digest: ProjectDigest) -> str:
    """Format digest as a terminal-friendly text report."""
    lines = []
    lines.append("╔══════════════════════════════════════════════════════════════╗")
    lines.append("║           SAURAVCODE PROJECT DIGEST                         ║")
    lines.append("╚══════════════════════════════════════════════════════════════╝")
    lines.append("")
    lines.append(f"  Directory:   {digest.directory}")
    lines.append(f"  Scanned:     {digest.scan_time}")
    lines.append(f"  Health:      {digest.health_grade} ({digest.health_score:.0f}/100)")
    lines.append("")

    # Overview
    lines.append("── Overview ─────────────────────────────────────────────────")
    lines.append(f"  Files:       {digest.total_files}")
    lines.append(f"  Total Lines: {digest.total_lines}  (code: {digest.total_code_lines}, comments: {digest.total_comment_lines}, blank: {digest.total_blank_lines})")
    lines.append(f"  Functions:   {digest.total_functions}")
    lines.append(f"  Classes:     {digest.total_classes}")
    lines.append(f"  Avg File:    {digest.avg_file_size:.0f} lines")
    lines.append(f"  Comments:    {digest.comment_ratio:.1%}")
    lines.append("")

    # Top files by size
    lines.append("── Largest Files ────────────────────────────────────────────")
    max_lines = max((f.lines for f in digest.files), default=1)
    for fm in sorted(digest.files, key=lambda f: f.lines, reverse=True)[:10]:
        name = os.path.basename(fm.path)[:30]
        bar = _bar(fm.lines, max_lines, 20)
        lines.append(f"  {name:<30s} {fm.lines:>5d} lines  {bar}")
    lines.append("")

    # Top files by complexity
    lines.append("── Most Complex ─────────────────────────────────────────────")
    max_cx = max((f.complexity_score for f in digest.files), default=1)
    for fm in sorted(digest.files, key=lambda f: f.complexity_score, reverse=True)[:10]:
        name = os.path.basename(fm.path)[:30]
        bar = _bar(fm.complexity_score, max_cx, 20)
        lines.append(f"  {name:<30s} {fm.complexity_score:>6.0f}       {bar}")
    lines.append("")

    # Language patterns
    if digest.pattern_counts:
        lines.append("── Language Patterns ─────────────────────────────────────────")
        max_p = max(digest.pattern_counts.values())
        for pname, count in sorted(digest.pattern_counts.items(), key=lambda x: -x[1]):
            bar = _bar(count, max_p, 20)
            lines.append(f"  {pname:<25s} {count:>4d} files  {bar}")
        lines.append("")

    # Dependencies
    deps_with_imports = {k: v for k, v in digest.dependency_graph.items() if v}
    if deps_with_imports:
        lines.append("── Dependency Map ───────────────────────────────────────────")
        for src, dsts in sorted(deps_with_imports.items()):
            lines.append(f"  {src} → {', '.join(dsts)}")
        lines.append("")

    # Hotspots
    if digest.hotspots:
        lines.append("── Hotspots ⚠ ──────────────────────────────────────────────")
        severity_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}
        for hs in digest.hotspots[:10]:
            icon = severity_icon.get(hs["severity"], "⚪")
            lines.append(f"  {icon} {hs['file']}")
            for r in hs["reasons"]:
                lines.append(f"      • {r}")
        lines.append("")

    # Recommendations
    if digest.recommendations:
        lines.append("── Recommendations ──────────────────────────────────────────")
        priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}
        for rec in digest.recommendations:
            icon = priority_icon.get(rec["priority"], "⚪")
            lines.append(f"  {icon} [{rec['category']}] {rec['title']}")
            lines.append(f"      {rec['detail']}")
            lines.append(f"      → {rec['action']}")
            lines.append("")

    return "\n".join(lines)


def format_json(digest: ProjectDigest) -> str:
    """Format digest as JSON."""
    data = {
        "directory": digest.directory,
        "scanTime": digest.scan_time,
        "health": {"score": round(digest.health_score, 1), "grade": digest.health_grade},
        "overview": {
            "files": digest.total_files,
            "totalLines": digest.total_lines,
            "codeLines": digest.total_code_lines,
            "commentLines": digest.total_comment_lines,
            "blankLines": digest.total_blank_lines,
            "functions": digest.total_functions,
            "classes": digest.total_classes,
            "avgFileSize": round(digest.avg_file_size, 1),
            "commentRatio": round(digest.comment_ratio, 3),
        },
        "largestFile": {"name": digest.largest_file, "lines": digest.largest_file_lines},
        "mostComplex": {"name": digest.most_complex_file, "score": round(digest.most_complex_score, 1)},
        "patterns": digest.pattern_counts,
        "dependencies": digest.dependency_graph,
        "hotspots": digest.hotspots,
        "recommendations": digest.recommendations,
        "files": [
            {
                "path": os.path.basename(f.path),
                "lines": f.lines,
                "codeLines": f.code_lines,
                "commentLines": f.comment_lines,
                "functions": f.functions,
                "classes": f.classes,
                "complexity": round(f.complexity_score, 1),
                "maxNesting": f.max_nesting,
            }
            for f in digest.files
        ],
    }
    return _json.dumps(data, indent=2)


def format_html(digest: ProjectDigest) -> str:
    """Generate an interactive HTML report."""
    # Build file table rows (list + join avoids O(N²) string concat)
    _file_parts = []
    for fm in sorted(digest.files, key=lambda f: -f.complexity_score):
        name = os.path.basename(fm.path)
        cx_color = "#e74c3c" if fm.complexity_score > 100 else "#f39c12" if fm.complexity_score > 50 else "#27ae60"
        _file_parts.append(f"""<tr>
            <td>{name}</td>
            <td>{fm.lines}</td>
            <td>{fm.code_lines}</td>
            <td>{len(fm.functions)}</td>
            <td style="color:{cx_color};font-weight:bold">{fm.complexity_score:.0f}</td>
            <td>{fm.max_nesting}</td>
        </tr>""")
    file_rows = '\n'.join(_file_parts)

    # Build hotspot cards
    _hs_parts = []
    sev_colors = {"high": "#e74c3c", "medium": "#f39c12", "low": "#27ae60"}
    for hs in digest.hotspots[:10]:
        color = sev_colors.get(hs["severity"], "#95a5a6")
        reasons = "".join(f"<li>{r}</li>" for r in hs["reasons"])
        _hs_parts.append(f"""<div style="border-left:4px solid {color};padding:8px 12px;margin:6px 0;background:#1a1a2e;border-radius:4px">
            <strong>{hs['file']}</strong> <span style="color:{color}">({hs['severity']})</span>
            <ul style="margin:4px 0;padding-left:18px">{reasons}</ul>
        </div>""")
    hotspot_html = '\n'.join(_hs_parts)

    # Build recommendation cards
    _rec_parts = []
    for rec in digest.recommendations:
        color = sev_colors.get(rec["priority"], "#95a5a6")
        _rec_parts.append(f"""<div style="border-left:4px solid {color};padding:8px 12px;margin:6px 0;background:#1a1a2e;border-radius:4px">
            <strong>[{rec['category']}]</strong> {rec['title']}
            <div style="color:#aaa;margin:4px 0">{rec['detail']}</div>
            <div style="color:#7ec8e3">→ {rec['action']}</div>
        </div>""")
    rec_html = '\n'.join(_rec_parts)

    # Pattern bar chart data
    _pat_parts = []
    if digest.pattern_counts:
        max_p = max(digest.pattern_counts.values())
        for pname, count in sorted(digest.pattern_counts.items(), key=lambda x: -x[1]):
            pct = count / max_p * 100
            _pat_parts.append(f"""<div style="display:flex;align-items:center;margin:3px 0">
                <span style="width:160px;font-size:13px">{pname}</span>
                <div style="flex:1;background:#1a1a2e;border-radius:3px;height:18px;overflow:hidden">
                    <div style="width:{pct}%;background:linear-gradient(90deg,#7ec8e3,#3498db);height:100%;border-radius:3px"></div>
                </div>
                <span style="width:40px;text-align:right;font-size:13px;color:#aaa">{count}</span>
            </div>""")
    pattern_bars = '\n'.join(_pat_parts)

    # Health gauge color
    h_color = "#27ae60" if digest.health_score >= 80 else "#f39c12" if digest.health_score >= 60 else "#e74c3c"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sauravcode Project Digest</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#0f0f23;color:#e0e0e0;padding:20px;line-height:1.5}}
h1{{text-align:center;color:#7ec8e3;margin-bottom:4px;font-size:28px}}
.subtitle{{text-align:center;color:#888;margin-bottom:24px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:16px 0}}
.card{{background:#16213e;border-radius:8px;padding:16px;text-align:center}}
.card .value{{font-size:32px;font-weight:bold;color:#7ec8e3}}
.card .label{{color:#888;font-size:13px;margin-top:4px}}
.section{{background:#16213e;border-radius:8px;padding:16px;margin:16px 0}}
.section h2{{color:#7ec8e3;font-size:18px;margin-bottom:12px;border-bottom:1px solid #1a1a2e;padding-bottom:6px}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th{{text-align:left;padding:8px;border-bottom:2px solid #1a1a2e;color:#7ec8e3}}
td{{padding:6px 8px;border-bottom:1px solid #1a1a2e}}
tr:hover{{background:#1a1a2e}}
.health-ring{{width:120px;height:120px;margin:0 auto 12px}}
.health-ring svg{{width:100%;height:100%}}
</style>
</head>
<body>
<h1>📊 Sauravcode Project Digest</h1>
<div class="subtitle">{digest.directory} • {digest.scan_time}</div>

<!-- Health Score -->
<div style="text-align:center;margin:20px 0">
    <div class="health-ring">
        <svg viewBox="0 0 120 120">
            <circle cx="60" cy="60" r="50" fill="none" stroke="#1a1a2e" stroke-width="10"/>
            <circle cx="60" cy="60" r="50" fill="none" stroke="{h_color}" stroke-width="10"
                stroke-dasharray="{digest.health_score * 3.14} 314" stroke-linecap="round"
                transform="rotate(-90 60 60)"/>
            <text x="60" y="55" text-anchor="middle" fill="{h_color}" font-size="28" font-weight="bold">{digest.health_grade}</text>
            <text x="60" y="75" text-anchor="middle" fill="#888" font-size="14">{digest.health_score:.0f}/100</text>
        </svg>
    </div>
</div>

<!-- Overview Cards -->
<div class="grid">
    <div class="card"><div class="value">{digest.total_files}</div><div class="label">Files</div></div>
    <div class="card"><div class="value">{digest.total_code_lines}</div><div class="label">Code Lines</div></div>
    <div class="card"><div class="value">{digest.total_functions}</div><div class="label">Functions</div></div>
    <div class="card"><div class="value">{digest.total_classes}</div><div class="label">Classes</div></div>
    <div class="card"><div class="value">{digest.comment_ratio:.0%}</div><div class="label">Comment Ratio</div></div>
    <div class="card"><div class="value">{digest.avg_file_size:.0f}</div><div class="label">Avg File Size</div></div>
</div>

<!-- File Table -->
<div class="section">
    <h2>📁 Files by Complexity</h2>
    <table>
        <tr><th>File</th><th>Lines</th><th>Code</th><th>Functions</th><th>Complexity</th><th>Max Depth</th></tr>
        {file_rows}
    </table>
</div>

<!-- Language Patterns -->
<div class="section">
    <h2>🔍 Language Pattern Usage</h2>
    {pattern_bars if pattern_bars else "<p style='color:#888'>No patterns detected.</p>"}
</div>

<!-- Hotspots -->
<div class="section">
    <h2>⚠️ Hotspots</h2>
    {hotspot_html if hotspot_html else "<p style='color:#888'>No hotspots detected. Looking good!</p>"}
</div>

<!-- Recommendations -->
<div class="section">
    <h2>💡 Proactive Recommendations</h2>
    {rec_html if rec_html else "<p style='color:#888'>No recommendations. Project is in great shape!</p>"}
</div>

<div style="text-align:center;color:#555;margin-top:24px;font-size:12px">
    Generated by sauravdigest • sauravcode project health analyzer
</div>
</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# Watch mode
# ---------------------------------------------------------------------------

def watch_mode(directory: str, interval: float = 5.0, html_path: Optional[str] = None):
    """Re-scan project on file changes."""
    print(f"👁  Watching {directory} (every {interval}s, Ctrl+C to stop)")
    last_mtime = 0.0
    while True:
        # Check for changes
        current_mtime = 0.0
        for f in glob.glob(os.path.join(directory, "**", "*.srv"), recursive=True):
            try:
                mt = os.path.getmtime(f)
                if mt > current_mtime:
                    current_mtime = mt
            except OSError:
                pass

        if current_mtime > last_mtime:
            last_mtime = current_mtime
            digest = scan_project(directory)
            # Clear screen
            print("\033[2J\033[H", end="")
            print(format_text(digest))
            if html_path:
                with open(html_path, 'w', encoding='utf-8') as f:
                    f.write(format_html(digest))
                print(f"\n  HTML report updated: {html_path}")

        _time.sleep(interval)


# ---------------------------------------------------------------------------
# Compare mode
# ---------------------------------------------------------------------------

def compare_digests(current: ProjectDigest, previous_json_path: str) -> str:
    """Compare current digest with a saved JSON digest."""
    try:
        with open(previous_json_path, 'r') as f:
            prev = _json.load(f)
    except (IOError, _json.JSONDecodeError) as e:
        return f"Error loading previous digest: {e}"

    lines = []
    lines.append("── Digest Comparison ────────────────────────────────────────")
    lines.append(f"  Previous: {prev.get('scanTime', '?')}")
    lines.append(f"  Current:  {current.scan_time}")
    lines.append("")

    # Compare key metrics
    prev_ov = prev.get("overview", {})
    deltas = [
        ("Files", current.total_files, prev_ov.get("files", 0)),
        ("Code Lines", current.total_code_lines, prev_ov.get("codeLines", 0)),
        ("Functions", current.total_functions, prev_ov.get("functions", 0)),
        ("Classes", current.total_classes, prev_ov.get("classes", 0)),
    ]
    for label, cur, prv in deltas:
        diff = cur - prv
        arrow = "↑" if diff > 0 else "↓" if diff < 0 else "="
        color = "" 
        lines.append(f"  {label:<15s}  {prv:>6d} → {cur:>6d}  {arrow} {abs(diff)}")

    # Health comparison
    prev_health = prev.get("health", {})
    prev_score = prev_health.get("score", 0)
    diff = current.health_score - prev_score
    arrow = "↑" if diff > 0 else "↓" if diff < 0 else "="
    lines.append(f"  {'Health':<15s}  {prev_score:>6.0f} → {current.health_score:>6.0f}  {arrow} {abs(diff):.0f}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Autonomous Codebase Digest for sauravcode projects",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("directory", nargs="?", default=".",
                        help="Directory to scan (default: current)")
    parser.add_argument("--html", metavar="FILE",
                        help="Generate interactive HTML report")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON format")
    parser.add_argument("--watch", action="store_true",
                        help="Watch mode — re-scan on file changes")
    parser.add_argument("--compare", metavar="FILE",
                        help="Compare with a previous JSON digest")
    parser.add_argument("--interval", type=float, default=5.0,
                        help="Watch interval in seconds (default: 5)")
    args = parser.parse_args()

    if args.watch:
        watch_mode(args.directory, args.interval, args.html)
        return

    digest = scan_project(args.directory)

    if args.json:
        print(format_json(digest))
    else:
        print(format_text(digest))

    if args.html:
        with open(args.html, 'w', encoding='utf-8') as f:
            f.write(format_html(digest))
        print(f"\n  ✅ HTML report saved to {args.html}")

    if args.compare:
        print(compare_digests(digest, args.compare))


if __name__ == "__main__":
    main()
