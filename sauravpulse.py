#!/usr/bin/env python3
"""sauravpulse — Autonomous Codebase Vital Signs Monitor for sauravcode.

Models a .srv codebase as a living organism and tracks 8 vital signs
simultaneously.  Unlike single-dimension tools, sauravpulse detects
correlations *between* vital signs to surface systemic risks, produces
a unified Pulse Score 0-100, and maintains a historical timeline for
trend analysis.

Vital-Sign Engines (8):
    P001  Heart Rate         Code activity — file count × avg function density
    P002  Blood Pressure     Complexity-to-documentation ratio (hypertension = complex + undocumented)
    P003  Temperature        Hotspot density — proportion of extreme-metric functions
    P004  Respiratory Rate   Code rhythm regularity — CV of function sizes + naming consistency
    P005  Oxygen Saturation  Test-coverage proxy — functions with apparent test references
    P006  Reflexes           Error-handling responsiveness — try/catch around risky ops
    P007  Immune Response    Defensive coding density — assertions, guards, boundary checks
    P008  Neural Activity    Cognitive complexity — weighted nesting + branching + fan-out

Each vital sign is scored 0-100 and classified:
    Optimal    80-100   Healthy
    Normal     60-79    Acceptable
    Concerning 40-59    Needs attention
    Critical   0-39     Immediate action required

Composite Pulse Score (weighted mean) → 0-100:
    Thriving  85-100
    Healthy   70-84
    Stable    55-69
    Stressed  40-54
    Critical  0-39

Cross-vital correlation analysis surfaces systemic issues like
"untested hotspots" or "complex unguarded code."

Usage:
    python sauravpulse.py program.srv              # Check pulse of a single file
    python sauravpulse.py .                        # Scan all .srv files in cwd
    python sauravpulse.py . --recursive            # Include subdirectories
    python sauravpulse.py . --html report.html     # Interactive HTML dashboard
    python sauravpulse.py . --json                 # JSON output
    python sauravpulse.py . --vital heart-rate     # Show specific vital sign
    python sauravpulse.py . --correlations         # Show cross-vital correlations
    python sauravpulse.py . --timeline             # Show pulse trend over time
    python sauravpulse.py . --critical             # Show only critical vital signs
    python sauravpulse.py . --top 10               # Top N worst-scoring functions
    python sauravpulse.py . --no-color             # Disable ANSI colors
    python sauravpulse.py . --reset                # Clear timeline history
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


def red(t):     return _c("31", t)
def green(t):   return _c("32", t)
def yellow(t):  return _c("33", t)
def cyan(t):    return _c("36", t)
def bold(t):    return _c("1", t)
def dim(t):     return _c("2", t)
def magenta(t): return _c("35", t)


# ── Regex / Constants ────────────────────────────────────────────────

FUNCTION_DEF = re.compile(r'^(\s*)(function|fn)\s+(\w+)')
BRANCH_KEYWORDS = {'if', 'elif', 'while', 'for', 'foreach', 'catch', 'and', 'or'}
CALL_PATTERN = re.compile(r'\b([a-zA-Z_]\w*)\s*\(')
RISKY_CALLS = {'read_file', 'write_file', 'open', 'http_get', 'http_post',
               'fetch', 'connect', 'parse_json', 'parse_xml', 'parse_csv',
               'execute', 'eval', 'load', 'import_module', 'download'}
GUARD_PATTERNS = re.compile(
    r'\b(assert|throw|raise|return\s+null|return\s+false|return\s+err)\b'
    r'|!=\s*null|==\s*null|!=\s*none|is\s+null|is\s+not\s+null'
    r'|\blen\s*\(.*\)\s*[<>=!]+\s*\d'
)
NAMING_SNAKE = re.compile(r'^[a-z][a-z0-9_]*$')
NAMING_CAMEL = re.compile(r'^[a-z][a-zA-Z0-9]*$')
COMMENT_LINE = re.compile(r'^\s*#')

VITAL_NAMES = {
    'heart-rate': 'P001', 'blood-pressure': 'P002', 'temperature': 'P003',
    'respiratory-rate': 'P004', 'oxygen-saturation': 'P005', 'reflexes': 'P006',
    'immune-response': 'P007', 'neural-activity': 'P008',
}

VITAL_WEIGHTS = {
    'P001': 0.08, 'P002': 0.15, 'P003': 0.12, 'P004': 0.08,
    'P005': 0.15, 'P006': 0.12, 'P007': 0.12, 'P008': 0.18,
}

HISTORY_FILE = ".pulse-history.json"


# ── Data Classes ─────────────────────────────────────────────────────

@dataclass
class FunctionInfo:
    """Parsed function-level data from a .srv file."""
    name: str
    file: str
    line: int
    loc: int = 0
    complexity: int = 1
    max_depth: int = 0
    params: int = 0
    calls: List[str] = field(default_factory=list)
    has_doc_comment: bool = False
    risky_calls: int = 0
    try_catch_blocks: int = 0
    guard_count: int = 0
    nesting_sum: int = 0

    @property
    def fqn(self):
        return f"{self.file}::{self.name}"


@dataclass
class VitalSign:
    """A single vital sign measurement."""
    code: str           # P001..P008
    name: str
    score: float = 0.0  # 0-100
    status: str = ""    # Optimal/Normal/Concerning/Critical
    details: str = ""
    per_file: Dict[str, float] = field(default_factory=dict)

    def classify(self):
        if self.score >= 80:
            self.status = "Optimal"
        elif self.score >= 60:
            self.status = "Normal"
        elif self.score >= 40:
            self.status = "Concerning"
        else:
            self.status = "Critical"


@dataclass
class Correlation:
    """A detected cross-vital correlation."""
    vital_a: str
    vital_b: str
    description: str
    severity: str  # info/warning/critical


@dataclass
class PulseReport:
    """Full pulse analysis report."""
    timestamp: str = ""
    files_scanned: int = 0
    total_functions: int = 0
    vitals: List[VitalSign] = field(default_factory=list)
    pulse_score: float = 0.0
    pulse_class: str = ""
    correlations: List[Correlation] = field(default_factory=list)
    insights: List[str] = field(default_factory=list)
    worst_functions: List[Dict[str, Any]] = field(default_factory=list)
    timeline: List[Dict[str, Any]] = field(default_factory=list)


# ── File Parser ──────────────────────────────────────────────────────

def _parse_file(filepath: str) -> Tuple[List[FunctionInfo], int, int]:
    """Parse a .srv file → (functions, total_lines, comment_lines)."""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
    except OSError:
        return [], 0, 0

    functions: List[FunctionInfo] = []
    current: Optional[FunctionInfo] = None
    base_indent = 0
    total_lines = len(lines)
    comment_lines = 0
    prev_was_comment = False
    fname = os.path.basename(filepath)

    for i, raw in enumerate(lines):
        line = raw.rstrip()
        stripped = line.lstrip()

        if not stripped:
            prev_was_comment = False
            continue

        if stripped.startswith('#'):
            comment_lines += 1
            prev_was_comment = True
            continue

        indent = _get_indent(raw)
        m = FUNCTION_DEF.match(line)

        if m:
            current = FunctionInfo(
                name=m.group(3), file=fname, line=i + 1,
                has_doc_comment=prev_was_comment,
            )
            base_indent = indent
            after = line[m.end():].strip()
            if after:
                current.params = len(after.split())
            functions.append(current)
            prev_was_comment = False
            continue

        prev_was_comment = False

        if current is not None and indent > base_indent:
            current.loc += 1
            depth = indent - base_indent
            current.nesting_sum += depth
            if depth > current.max_depth:
                current.max_depth = depth

            first_word = stripped.split()[0] if stripped else ""
            if first_word in BRANCH_KEYWORDS:
                current.complexity += 1

            if first_word in ('try',):
                current.try_catch_blocks += 1

            for cm in CALL_PATTERN.finditer(stripped):
                cname = cm.group(1)
                if cname not in BRANCH_KEYWORDS and cname not in ('end', 'return', 'print', 'println'):
                    current.calls.append(cname)
                    if cname in RISKY_CALLS:
                        current.risky_calls += 1

            if GUARD_PATTERNS.search(stripped):
                current.guard_count += 1

    return functions, total_lines, comment_lines


# ── P001: Heart Rate — Code Activity ────────────────────────────────

def compute_heart_rate(file_data: Dict[str, List[FunctionInfo]]) -> VitalSign:
    """Code activity: file count × avg function density."""
    vs = VitalSign(code="P001", name="Heart Rate")
    if not file_data:
        vs.score = 0.0
        vs.classify()
        vs.details = "No files found"
        return vs

    n_files = len(file_data)
    total_fns = sum(len(fns) for fns in file_data.values())
    avg_density = total_fns / n_files if n_files else 0

    # Score: 0-100.  Sweet spot ~3-8 functions per file.
    if avg_density < 1:
        density_score = avg_density * 40  # 0-40
    elif avg_density <= 3:
        density_score = 40 + (avg_density - 1) * 15  # 40-70
    elif avg_density <= 8:
        density_score = 70 + (avg_density - 3) * 6  # 70-100
    elif avg_density <= 15:
        density_score = 100 - (avg_density - 8) * 3  # 100→79
    else:
        density_score = max(20, 79 - (avg_density - 15) * 2)

    # File count factor — more files = more organized
    file_factor = min(1.0, n_files / 5) * 0.3 + 0.7

    vs.score = max(0, min(100, density_score * file_factor))
    for fname, fns in file_data.items():
        d = len(fns)
        vs.per_file[fname] = max(0, min(100, d * 12.5))  # simple per-file
    vs.details = f"{total_fns} functions across {n_files} files (avg {avg_density:.1f}/file)"
    vs.classify()
    return vs


# ── P002: Blood Pressure — Complexity / Documentation Ratio ─────────

def compute_blood_pressure(file_data: Dict[str, List[FunctionInfo]],
                           comment_counts: Dict[str, int],
                           line_counts: Dict[str, int]) -> VitalSign:
    """High complexity + low docs = hypertension."""
    vs = VitalSign(code="P002", name="Blood Pressure")
    all_fns = [fn for fns in file_data.values() for fn in fns]
    if not all_fns:
        vs.score = 50.0
        vs.classify()
        vs.details = "No functions to assess"
        return vs

    avg_complexity = sum(fn.complexity for fn in all_fns) / len(all_fns)
    doc_ratio = sum(1 for fn in all_fns if fn.has_doc_comment) / len(all_fns)

    total_lines = sum(line_counts.values()) or 1
    total_comments = sum(comment_counts.values())
    comment_ratio = total_comments / total_lines

    # Higher doc coverage → lower pressure → better score
    complexity_penalty = min(1.0, avg_complexity / 8)  # normalized 0-1
    doc_benefit = doc_ratio * 0.6 + comment_ratio * 0.4

    raw = (1 - complexity_penalty * 0.6) * 50 + doc_benefit * 50
    vs.score = max(0, min(100, raw))

    for fname, fns in file_data.items():
        if not fns:
            continue
        fc = sum(fn.complexity for fn in fns) / len(fns)
        fd = sum(1 for fn in fns if fn.has_doc_comment) / len(fns)
        vs.per_file[fname] = max(0, min(100, (1 - fc / 8) * 50 + fd * 50))

    high_c = sum(1 for fn in all_fns if fn.complexity > 5)
    undoc = sum(1 for fn in all_fns if not fn.has_doc_comment)
    vs.details = (f"Avg complexity {avg_complexity:.1f}, "
                  f"{doc_ratio:.0%} documented, "
                  f"{high_c} high-complexity, {undoc} undocumented")
    vs.classify()
    return vs


# ── P003: Temperature — Hotspot Density ─────────────────────────────

def compute_temperature(file_data: Dict[str, List[FunctionInfo]]) -> VitalSign:
    """Proportion of extreme-metric functions (hotspots)."""
    vs = VitalSign(code="P003", name="Temperature")
    all_fns = [fn for fns in file_data.values() for fn in fns]
    if not all_fns:
        vs.score = 80.0
        vs.classify()
        vs.details = "No functions — cool baseline"
        return vs

    hotspots = 0
    for fn in all_fns:
        hot = 0
        if fn.loc > 40:
            hot += 1
        if fn.complexity > 6:
            hot += 1
        if fn.max_depth > 4:
            hot += 1
        if len(fn.calls) > 10:
            hot += 1
        if hot >= 2:
            hotspots += 1

    ratio = hotspots / len(all_fns)
    # Less hotspots = better (higher score = healthier)
    vs.score = max(0, min(100, 100 - ratio * 200))

    for fname, fns in file_data.items():
        if not fns:
            continue
        fh = sum(1 for fn in fns if (fn.loc > 40) + (fn.complexity > 6) + (fn.max_depth > 4) >= 2)
        vs.per_file[fname] = max(0, min(100, 100 - (fh / len(fns)) * 200))

    vs.details = f"{hotspots}/{len(all_fns)} functions are hotspots ({ratio:.0%})"
    vs.classify()
    return vs


# ── P004: Respiratory Rate — Code Rhythm Regularity ─────────────────

def compute_respiratory_rate(file_data: Dict[str, List[FunctionInfo]]) -> VitalSign:
    """Measures consistency: CV of function sizes + naming uniformity."""
    vs = VitalSign(code="P004", name="Respiratory Rate")
    all_fns = [fn for fns in file_data.values() for fn in fns]
    if len(all_fns) < 2:
        vs.score = 70.0
        vs.classify()
        vs.details = "Too few functions to measure rhythm"
        return vs

    # CV of function LOC
    locs = [fn.loc for fn in all_fns]
    mean_loc = sum(locs) / len(locs) if locs else 1
    if mean_loc > 0:
        std_loc = math.sqrt(sum((x - mean_loc) ** 2 for x in locs) / len(locs))
        cv = std_loc / mean_loc
    else:
        cv = 0

    # Naming consistency
    names = [fn.name for fn in all_fns]
    snake_count = sum(1 for n in names if NAMING_SNAKE.match(n))
    camel_count = sum(1 for n in names if NAMING_CAMEL.match(n) and not NAMING_SNAKE.match(n))
    dominant = max(snake_count, camel_count)
    naming_consistency = dominant / len(names) if names else 1.0

    # CV score: lower CV = more consistent = better
    cv_score = max(0, 100 - cv * 60)
    naming_score = naming_consistency * 100
    vs.score = max(0, min(100, cv_score * 0.6 + naming_score * 0.4))

    for fname, fns in file_data.items():
        if len(fns) < 2:
            vs.per_file[fname] = 70.0
            continue
        fl = [fn.loc for fn in fns]
        fm = sum(fl) / len(fl) if fl else 1
        if fm > 0:
            fs = math.sqrt(sum((x - fm) ** 2 for x in fl) / len(fl))
            fcv = fs / fm
        else:
            fcv = 0
        vs.per_file[fname] = max(0, min(100, 100 - fcv * 60))

    vs.details = f"Size CV={cv:.2f}, naming consistency {naming_consistency:.0%}"
    vs.classify()
    return vs


# ── P005: Oxygen Saturation — Test Coverage Proxy ───────────────────

def compute_oxygen_saturation(file_data: Dict[str, List[FunctionInfo]],
                              all_file_contents: Dict[str, str]) -> VitalSign:
    """Functions with apparent test references vs total."""
    vs = VitalSign(code="P005", name="Oxygen Saturation")
    all_fns = [fn for fns in file_data.values() for fn in fns]
    if not all_fns:
        vs.score = 50.0
        vs.classify()
        vs.details = "No functions to assess"
        return vs

    # Collect all test-file contents
    test_blob = ""
    for fname, content in all_file_contents.items():
        if 'test' in fname.lower():
            test_blob += " " + content

    tested = 0
    for fn in all_fns:
        # Check if function name appears in any test file
        if fn.name in test_blob:
            tested += 1

    ratio = tested / len(all_fns)
    vs.score = max(0, min(100, ratio * 120))  # slight bonus — 83% coverage → 100

    for fname, fns in file_data.items():
        if not fns:
            continue
        ft = sum(1 for fn in fns if fn.name in test_blob)
        vs.per_file[fname] = max(0, min(100, (ft / len(fns)) * 120))

    vs.details = f"{tested}/{len(all_fns)} functions appear tested ({ratio:.0%})"
    vs.classify()
    return vs


# ── P006: Reflexes — Error-Handling Responsiveness ──────────────────

def compute_reflexes(file_data: Dict[str, List[FunctionInfo]]) -> VitalSign:
    """Try/catch coverage around risky operations."""
    vs = VitalSign(code="P006", name="Reflexes")
    all_fns = [fn for fns in file_data.values() for fn in fns]
    risky_fns = [fn for fn in all_fns if fn.risky_calls > 0]

    if not risky_fns:
        vs.score = 90.0  # no risky calls = good reflexes by default
        vs.classify()
        vs.details = "No risky operations detected"
        return vs

    covered = sum(1 for fn in risky_fns if fn.try_catch_blocks > 0)
    ratio = covered / len(risky_fns)
    vs.score = max(0, min(100, ratio * 100))

    for fname, fns in file_data.items():
        rf = [fn for fn in fns if fn.risky_calls > 0]
        if not rf:
            vs.per_file[fname] = 90.0
            continue
        rc = sum(1 for fn in rf if fn.try_catch_blocks > 0)
        vs.per_file[fname] = max(0, min(100, (rc / len(rf)) * 100))

    vs.details = f"{covered}/{len(risky_fns)} risky functions have error handling ({ratio:.0%})"
    vs.classify()
    return vs


# ── P007: Immune Response — Defensive Coding Density ────────────────

def compute_immune_response(file_data: Dict[str, List[FunctionInfo]]) -> VitalSign:
    """Assertions, guards, input validation per function."""
    vs = VitalSign(code="P007", name="Immune Response")
    all_fns = [fn for fns in file_data.values() for fn in fns]
    if not all_fns:
        vs.score = 50.0
        vs.classify()
        vs.details = "No functions to assess"
        return vs

    guarded = sum(1 for fn in all_fns if fn.guard_count > 0)
    ratio = guarded / len(all_fns)
    avg_guards = sum(fn.guard_count for fn in all_fns) / len(all_fns)

    # Score: ratio-based with density bonus
    vs.score = max(0, min(100, ratio * 80 + min(20, avg_guards * 10)))

    for fname, fns in file_data.items():
        if not fns:
            continue
        fg = sum(1 for fn in fns if fn.guard_count > 0)
        vs.per_file[fname] = max(0, min(100, (fg / len(fns)) * 80 + 10))

    vs.details = f"{guarded}/{len(all_fns)} functions have guards ({ratio:.0%}), avg {avg_guards:.1f}/fn"
    vs.classify()
    return vs


# ── P008: Neural Activity — Cognitive Complexity ────────────────────

def compute_neural_activity(file_data: Dict[str, List[FunctionInfo]]) -> VitalSign:
    """Weighted nesting + branching + call fan-out."""
    vs = VitalSign(code="P008", name="Neural Activity")
    all_fns = [fn for fns in file_data.values() for fn in fns]
    if not all_fns:
        vs.score = 80.0
        vs.classify()
        vs.details = "No functions to assess"
        return vs

    cognitive_scores = []
    for fn in all_fns:
        avg_nest = fn.nesting_sum / fn.loc if fn.loc > 0 else 0
        cog = (fn.complexity * 2 + avg_nest * 3 + len(fn.calls) * 0.5
               + fn.max_depth * 1.5)
        cognitive_scores.append(cog)

    avg_cog = sum(cognitive_scores) / len(cognitive_scores)
    # Lower cognitive load = better. Score inversely.
    # Sweet spot ≤ 10; catastrophic at 40+
    vs.score = max(0, min(100, 100 - (avg_cog - 3) * 3.5))

    for fname, fns in file_data.items():
        if not fns:
            continue
        cs = []
        for fn in fns:
            avg_n = fn.nesting_sum / fn.loc if fn.loc > 0 else 0
            cs.append(fn.complexity * 2 + avg_n * 3 + len(fn.calls) * 0.5 + fn.max_depth * 1.5)
        ac = sum(cs) / len(cs) if cs else 0
        vs.per_file[fname] = max(0, min(100, 100 - (ac - 3) * 3.5))

    high_cog = sum(1 for c in cognitive_scores if c > 20)
    vs.details = f"Avg cognitive load {avg_cog:.1f}, {high_cog} high-load functions"
    vs.classify()
    return vs


# ── Correlation Detection ────────────────────────────────────────────

def detect_correlations(vitals: Dict[str, VitalSign]) -> List[Correlation]:
    """Cross-vital correlation analysis to surface systemic issues."""
    corrs: List[Correlation] = []

    def _v(code):
        return vitals.get(code, VitalSign(code=code, name="?", score=50))

    # Low O2 + High Temperature = untested hotspots
    o2 = _v('P005').score
    temp = _v('P003').score
    if o2 < 50 and temp < 50:
        corrs.append(Correlation(
            vital_a="P005", vital_b="P003",
            description="Untested hotspots — ticking time bombs. "
                        "Low test coverage meets high hotspot density.",
            severity="critical"
        ))
    elif o2 < 60 and temp < 60:
        corrs.append(Correlation(
            vital_a="P005", vital_b="P003",
            description="Moderate untested hotspot risk — some complex code lacks tests.",
            severity="warning"
        ))

    # Low Immune + High Blood Pressure = fragile complex code
    immune = _v('P007').score
    bp = _v('P002').score
    if immune < 50 and bp < 50:
        corrs.append(Correlation(
            vital_a="P007", vital_b="P002",
            description="Complex unguarded code — fragile core. "
                        "High complexity with few defensive guards.",
            severity="critical"
        ))
    elif immune < 60 and bp < 60:
        corrs.append(Correlation(
            vital_a="P007", vital_b="P002",
            description="Some complex code lacks defensive guards.",
            severity="warning"
        ))

    # Low Respiratory + High Neural = cognitive chaos
    resp = _v('P004').score
    neural = _v('P008').score
    if resp < 50 and neural < 50:
        corrs.append(Correlation(
            vital_a="P004", vital_b="P008",
            description="Inconsistent complex code — cognitive chaos. "
                        "Irregular patterns plus high cognitive load.",
            severity="critical"
        ))
    elif resp < 60 and neural < 60:
        corrs.append(Correlation(
            vital_a="P004", vital_b="P008",
            description="Code rhythm inconsistencies compound cognitive load.",
            severity="warning"
        ))

    # Low Reflexes + Low Immune = no safety net
    reflexes = _v('P006').score
    if reflexes < 50 and immune < 50:
        corrs.append(Correlation(
            vital_a="P006", vital_b="P007",
            description="No safety net — risky ops unhandled AND no guards.",
            severity="critical"
        ))

    # Low Heart Rate + Low O2 = stagnant untested code
    hr = _v('P001').score
    if hr < 40 and o2 < 40:
        corrs.append(Correlation(
            vital_a="P001", vital_b="P005",
            description="Stagnant untested code — low activity with no tests.",
            severity="warning"
        ))

    # High neural + low respiratory + low BP = perfect storm
    if neural < 40 and resp < 40 and bp < 40:
        corrs.append(Correlation(
            vital_a="P008", vital_b="P004",
            description="Perfect storm — high cognitive load, irregular style, and poor documentation.",
            severity="critical"
        ))

    return corrs


# ── Composite Pulse Score ────────────────────────────────────────────

def compute_pulse_score(vitals: List[VitalSign]) -> Tuple[float, str]:
    """Weighted mean of all vital signs → (score, classification)."""
    if not vitals:
        return 0.0, "Critical"

    total_w = 0.0
    weighted = 0.0
    for v in vitals:
        w = VITAL_WEIGHTS.get(v.code, 0.1)
        weighted += v.score * w
        total_w += w

    score = weighted / total_w if total_w else 0.0
    score = max(0, min(100, score))

    if score >= 85:
        cls = "Thriving"
    elif score >= 70:
        cls = "Healthy"
    elif score >= 55:
        cls = "Stable"
    elif score >= 40:
        cls = "Stressed"
    else:
        cls = "Critical"

    return round(score, 1), cls


# ── Autonomous Insights ─────────────────────────────────────────────

def generate_insights(vitals: List[VitalSign], correlations: List[Correlation],
                      pulse_score: float) -> List[str]:
    """Generate actionable recommendations."""
    insights: List[str] = []
    vmap = {v.code: v for v in vitals}

    critical = [v for v in vitals if v.status == "Critical"]
    concerning = [v for v in vitals if v.status == "Concerning"]

    if not critical and not concerning:
        insights.append("All vital signs are healthy — keep up the good work!")
    else:
        if critical:
            names = ", ".join(v.name for v in critical)
            insights.append(f"URGENT: {len(critical)} critical vital sign(s): {names}")

    # Specific recommendations
    if vmap.get('P002') and vmap['P002'].score < 50:
        insights.append("Add documentation comments before functions to reduce blood pressure.")
    if vmap.get('P003') and vmap['P003'].score < 50:
        insights.append("Refactor hotspot functions — break large complex functions into smaller ones.")
    if vmap.get('P005') and vmap['P005'].score < 60:
        insights.append("Increase test coverage — untested functions are blind spots.")
    if vmap.get('P006') and vmap['P006'].score < 60:
        insights.append("Add try/catch blocks around file I/O and network calls.")
    if vmap.get('P007') and vmap['P007'].score < 50:
        insights.append("Add input validation and assertions to strengthen immune response.")
    if vmap.get('P008') and vmap['P008'].score < 50:
        insights.append("Reduce cognitive load — simplify deeply nested or heavily branching functions.")
    if vmap.get('P004') and vmap['P004'].score < 50:
        insights.append("Standardize function sizes and naming conventions for better rhythm.")

    crit_corrs = [c for c in correlations if c.severity == "critical"]
    if crit_corrs:
        insights.append(f"Found {len(crit_corrs)} critical cross-vital correlation(s) — systemic risk detected.")

    if pulse_score >= 85:
        insights.append("Codebase is thriving — consider adding more ambitious features.")
    elif pulse_score < 40:
        insights.append("Codebase needs immediate attention — prioritize the critical vitals.")

    return insights


# ── Worst Functions ──────────────────────────────────────────────────

def rank_worst_functions(file_data: Dict[str, List[FunctionInfo]], top_n: int = 10) -> List[Dict[str, Any]]:
    """Rank functions by overall health (worst first)."""
    all_fns = [fn for fns in file_data.values() for fn in fns]
    scored = []
    for fn in all_fns:
        # Composite per-function score (lower = worse)
        avg_nest = fn.nesting_sum / fn.loc if fn.loc > 0 else 0
        cog = fn.complexity * 2 + avg_nest * 3 + len(fn.calls) * 0.5 + fn.max_depth * 1.5
        doc_bonus = 10 if fn.has_doc_comment else 0
        guard_bonus = min(15, fn.guard_count * 5)
        reflex_bonus = 10 if fn.try_catch_blocks > 0 and fn.risky_calls > 0 else 0
        size_penalty = max(0, (fn.loc - 30) * 0.5)

        health = max(0, min(100, 80 - cog * 2 + doc_bonus + guard_bonus + reflex_bonus - size_penalty))
        scored.append({
            "fqn": fn.fqn,
            "health": round(health, 1),
            "loc": fn.loc,
            "complexity": fn.complexity,
            "max_depth": fn.max_depth,
            "calls": len(fn.calls),
            "guarded": fn.guard_count > 0,
            "documented": fn.has_doc_comment,
        })

    scored.sort(key=lambda x: x["health"])
    return scored[:top_n]


# ── Timeline / History ───────────────────────────────────────────────

def _history_path(scan_dir: str) -> str:
    return os.path.join(scan_dir, HISTORY_FILE)


def load_history(scan_dir: str) -> List[Dict[str, Any]]:
    hp = _history_path(scan_dir)
    if os.path.isfile(hp):
        try:
            with open(hp, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_history(scan_dir: str, report: PulseReport):
    hp = _history_path(scan_dir)
    history = load_history(scan_dir)
    entry = {
        "timestamp": report.timestamp,
        "pulse_score": report.pulse_score,
        "pulse_class": report.pulse_class,
        "files": report.files_scanned,
        "functions": report.total_functions,
        "vitals": {v.code: {"score": round(v.score, 1), "status": v.status} for v in report.vitals},
    }
    history.append(entry)
    # Keep last 100 snapshots
    if len(history) > 100:
        history = history[-100:]
    try:
        with open(hp, 'w') as f:
            json.dump(history, f, indent=2)
    except OSError:
        pass


def clear_history(scan_dir: str):
    hp = _history_path(scan_dir)
    if os.path.isfile(hp):
        os.remove(hp)


# ── Main Analyzer ────────────────────────────────────────────────────

def analyze_pulse(paths, *, recursive=False, top_n=10) -> PulseReport:
    """Orchestrate all 8 vital-sign engines and produce a PulseReport."""
    report = PulseReport(timestamp=datetime.now().isoformat())
    srv_files = _find_srv_files(paths, recursive=recursive)

    if not srv_files:
        report.pulse_score = 0.0
        report.pulse_class = "Critical"
        report.insights = ["No .srv files found"]
        return report

    file_data: Dict[str, List[FunctionInfo]] = {}
    comment_counts: Dict[str, int] = {}
    line_counts: Dict[str, int] = {}
    all_contents: Dict[str, str] = {}

    for fp in srv_files:
        fname = os.path.basename(fp)
        fns, total, comments = _parse_file(fp)
        file_data[fname] = fns
        comment_counts[fname] = comments
        line_counts[fname] = total
        try:
            with open(fp, 'r', encoding='utf-8', errors='replace') as f:
                all_contents[fname] = f.read()
        except OSError:
            all_contents[fname] = ""

    report.files_scanned = len(file_data)
    report.total_functions = sum(len(fns) for fns in file_data.values())

    # Run all 8 engines
    vitals = [
        compute_heart_rate(file_data),
        compute_blood_pressure(file_data, comment_counts, line_counts),
        compute_temperature(file_data),
        compute_respiratory_rate(file_data),
        compute_oxygen_saturation(file_data, all_contents),
        compute_reflexes(file_data),
        compute_immune_response(file_data),
        compute_neural_activity(file_data),
    ]
    report.vitals = vitals

    # Pulse score
    report.pulse_score, report.pulse_class = compute_pulse_score(vitals)

    # Correlations
    vmap = {v.code: v for v in vitals}
    report.correlations = detect_correlations(vmap)

    # Insights
    report.insights = generate_insights(vitals, report.correlations, report.pulse_score)

    # Worst functions
    report.worst_functions = rank_worst_functions(file_data, top_n)

    return report


# ── HTML Dashboard ───────────────────────────────────────────────────

def _generate_html(report: PulseReport) -> str:
    """Generate a self-contained interactive HTML dashboard."""

    def _status_color(status):
        return {"Optimal": "#22c55e", "Normal": "#3b82f6",
                "Concerning": "#f59e0b", "Critical": "#ef4444"}.get(status, "#888")

    def _pulse_color(cls):
        return {"Thriving": "#22c55e", "Healthy": "#3b82f6",
                "Stable": "#f59e0b", "Stressed": "#f97316",
                "Critical": "#ef4444"}.get(cls, "#888")

    def _sev_color(sev):
        return {"critical": "#ef4444", "warning": "#f59e0b", "info": "#3b82f6"}.get(sev, "#888")

    vitals_html = ""
    for v in report.vitals:
        color = _status_color(v.status)
        vitals_html += f"""
        <div class="vital-card">
          <div class="vital-code">{v.code}</div>
          <div class="vital-name">{v.name}</div>
          <div class="vital-score" style="color:{color}">{v.score:.0f}</div>
          <div class="vital-status" style="background:{color}20;color:{color}">{v.status}</div>
          <div class="vital-details">{v.details}</div>
        </div>"""

    corr_html = ""
    for c in report.correlations:
        color = _sev_color(c.severity)
        corr_html += f"""
        <div class="corr-card" style="border-left:4px solid {color}">
          <span class="corr-pair">{c.vital_a} × {c.vital_b}</span>
          <span class="corr-sev" style="color:{color}">{c.severity.upper()}</span>
          <div class="corr-desc">{c.description}</div>
        </div>"""

    if not corr_html:
        corr_html = '<div class="empty">No cross-vital correlations detected — healthy!</div>'

    insights_html = "".join(f"<li>{i}</li>" for i in report.insights)

    worst_html = ""
    for fn in report.worst_functions:
        hc = "#22c55e" if fn["health"] >= 70 else "#f59e0b" if fn["health"] >= 40 else "#ef4444"
        worst_html += f"""
        <tr>
          <td>{fn['fqn']}</td>
          <td style="color:{hc}">{fn['health']}</td>
          <td>{fn['loc']}</td>
          <td>{fn['complexity']}</td>
          <td>{fn['max_depth']}</td>
          <td>{'Yes' if fn['documented'] else 'No'}</td>
          <td>{'Yes' if fn['guarded'] else 'No'}</td>
        </tr>"""

    timeline_html = ""
    if report.timeline:
        points = []
        for i, entry in enumerate(report.timeline[-20:]):
            ts = entry.get("timestamp", "")[:10]
            score = entry.get("pulse_score", 0)
            points.append(f'{{x:{i},y:{score},label:"{ts}"}}')
        timeline_html = f"""
        <h2>Pulse Timeline</h2>
        <div class="timeline-chart" id="timeline">
          <canvas id="timelineCanvas" width="800" height="200"></canvas>
        </div>
        <script>
        (function(){{
          var pts = [{",".join(points)}];
          var c = document.getElementById('timelineCanvas');
          var ctx = c.getContext('2d');
          var w = c.width, h = c.height, pad = 40;
          ctx.fillStyle = '#1a1a2e';
          ctx.fillRect(0,0,w,h);
          if(pts.length < 2) return;
          var xStep = (w - 2*pad) / (pts.length - 1);
          ctx.strokeStyle = '#3b82f6';
          ctx.lineWidth = 2;
          ctx.beginPath();
          for(var i=0; i<pts.length; i++){{
            var px = pad + i * xStep;
            var py = h - pad - (pts[i].y / 100) * (h - 2*pad);
            if(i===0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
          }}
          ctx.stroke();
          ctx.fillStyle = '#888';
          ctx.font = '10px monospace';
          for(var i=0; i<pts.length; i++){{
            var px = pad + i * xStep;
            var py = h - pad - (pts[i].y / 100) * (h - 2*pad);
            ctx.beginPath();
            ctx.arc(px, py, 3, 0, 2*Math.PI);
            ctx.fillStyle = '#3b82f6';
            ctx.fill();
            ctx.fillStyle = '#888';
            ctx.fillText(pts[i].y.toFixed(0), px - 8, py - 8);
          }}
        }})();
        </script>"""

    pulse_color = _pulse_color(report.pulse_class)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>sauravpulse — Codebase Vital Signs</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#0f0f23;color:#e0e0e0;padding:2rem}}
h1{{text-align:center;font-size:2rem;margin-bottom:.5rem}}
h2{{margin:2rem 0 1rem;font-size:1.3rem;border-bottom:1px solid #333;padding-bottom:.5rem}}
.subtitle{{text-align:center;color:#888;margin-bottom:2rem}}
.pulse-hero{{text-align:center;margin:2rem 0}}
.pulse-score{{font-size:5rem;font-weight:bold}}
.pulse-class{{font-size:1.5rem;margin-top:.5rem}}
.vital-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:1rem}}
.vital-card{{background:#1a1a2e;border-radius:12px;padding:1.2rem;border:1px solid #333}}
.vital-code{{color:#888;font-size:.8rem;font-family:monospace}}
.vital-name{{font-size:1.1rem;font-weight:600;margin:.3rem 0}}
.vital-score{{font-size:2.2rem;font-weight:bold}}
.vital-status{{display:inline-block;padding:.2rem .8rem;border-radius:999px;font-size:.8rem;margin:.5rem 0}}
.vital-details{{color:#aaa;font-size:.85rem;margin-top:.5rem}}
.corr-card{{background:#1a1a2e;border-radius:8px;padding:1rem;margin:.5rem 0}}
.corr-pair{{font-family:monospace;font-weight:600;margin-right:1rem}}
.corr-sev{{font-weight:600;text-transform:uppercase;font-size:.85rem}}
.corr-desc{{color:#ccc;margin-top:.5rem;font-size:.9rem}}
.insights ul{{list-style:none;padding:0}}
.insights li{{background:#1a1a2e;border-radius:8px;padding:.8rem 1rem;margin:.4rem 0;border-left:3px solid #3b82f6}}
.empty{{color:#666;font-style:italic}}
table{{width:100%;border-collapse:collapse;margin:1rem 0}}
th,td{{padding:.6rem .8rem;text-align:left;border-bottom:1px solid #222}}
th{{background:#1a1a2e;color:#aaa;font-size:.85rem}}
td{{font-family:monospace;font-size:.85rem}}
.meta{{text-align:center;color:#555;font-size:.8rem;margin-top:3rem}}
.timeline-chart{{background:#1a1a2e;border-radius:12px;padding:1rem;text-align:center}}
</style>
</head>
<body>
<h1>sauravpulse</h1>
<div class="subtitle">Autonomous Codebase Vital Signs Monitor — {report.timestamp[:19]}</div>

<div class="pulse-hero">
  <div class="pulse-score" style="color:{pulse_color}">{report.pulse_score:.0f}</div>
  <div class="pulse-class" style="color:{pulse_color}">{report.pulse_class}</div>
  <div style="color:#888;margin-top:.5rem">{report.files_scanned} files, {report.total_functions} functions</div>
</div>

<h2>Vital Signs</h2>
<div class="vital-grid">{vitals_html}</div>

<h2>Cross-Vital Correlations</h2>
{corr_html}

<h2>Autonomous Insights</h2>
<div class="insights"><ul>{insights_html}</ul></div>

<h2>Worst-Health Functions</h2>
<table>
<tr><th>Function</th><th>Health</th><th>LOC</th><th>Complexity</th><th>Depth</th><th>Documented</th><th>Guarded</th></tr>
{worst_html}
</table>

{timeline_html}

<div class="meta">Generated by sauravpulse v{__version__}</div>
</body>
</html>"""


# ── CLI Formatters ───────────────────────────────────────────────────

def _print_vital(v: VitalSign):
    color_fn = {"Optimal": green, "Normal": cyan, "Concerning": yellow, "Critical": red}.get(v.status, str)
    print(f"  {bold(v.code)}  {v.name:<22} {color_fn(f'{v.score:5.1f}'):>14}  {color_fn(v.status)}")
    print(f"         {dim(v.details)}")


def _print_report(report: PulseReport, *, show_vital=None, show_correlations=False,
                  show_critical=False, top_n=0):
    # Header
    pulse_fn = {"Thriving": green, "Healthy": cyan, "Stable": yellow,
                "Stressed": yellow, "Critical": red}.get(report.pulse_class, str)
    print()
    print(bold(f"  PULSE SCORE: {pulse_fn(f'{report.pulse_score:.0f}')} — {pulse_fn(report.pulse_class)}"))
    print(dim(f"  {report.files_scanned} files, {report.total_functions} functions"))
    print()

    # Vitals
    if show_vital:
        code = VITAL_NAMES.get(show_vital)
        matching = [v for v in report.vitals if v.code == code] if code else []
        if matching:
            print(bold("  Vital Sign:"))
            _print_vital(matching[0])
        else:
            print(red(f"  Unknown vital: {show_vital}"))
    elif show_critical:
        critical = [v for v in report.vitals if v.status in ("Critical", "Concerning")]
        if critical:
            print(bold("  Critical / Concerning Vital Signs:"))
            for v in critical:
                _print_vital(v)
        else:
            print(green("  All vital signs are healthy!"))
    else:
        print(bold("  Vital Signs:"))
        for v in report.vitals:
            _print_vital(v)

    print()

    # Correlations
    if show_correlations or (not show_vital and not show_critical):
        if report.correlations:
            print(bold("  Cross-Vital Correlations:"))
            for c in report.correlations:
                sev_fn = {"critical": red, "warning": yellow, "info": cyan}.get(c.severity, str)
                print(f"    {sev_fn(c.severity.upper())}  {c.vital_a} x {c.vital_b}")
                print(f"         {dim(c.description)}")
            print()

    # Worst functions
    if top_n > 0 and report.worst_functions:
        print(bold(f"  Bottom {min(top_n, len(report.worst_functions))} Functions:"))
        for fn in report.worst_functions[:top_n]:
            hfn = green if fn["health"] >= 70 else yellow if fn["health"] >= 40 else red
            h = fn['health']
            fqn = fn['fqn']
            loc = fn['loc']
            cplx = fn['complexity']
            dep = fn['max_depth']
            print(f"    {hfn(f'{h:5.1f}')}  {fqn}  (LOC={loc}, C={cplx}, D={dep})")
        print()

    # Insights
    if report.insights:
        print(bold("  Insights:"))
        for i in report.insights:
            print(f"    {cyan('>')} {i}")
        print()


# ── CLI Entry Point ──────────────────────────────────────────────────

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="sauravpulse",
        description="Autonomous codebase vital signs monitor for sauravcode"
    )
    parser.add_argument("paths", nargs="*", default=["."],
                        help=".srv files or directories to scan")
    parser.add_argument("--recursive", "-r", action="store_true",
                        help="Recurse into subdirectories")
    parser.add_argument("--html", metavar="FILE",
                        help="Generate interactive HTML dashboard")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON report")
    parser.add_argument("--vital", metavar="NAME",
                        help="Show specific vital sign (e.g. heart-rate, blood-pressure)")
    parser.add_argument("--correlations", action="store_true",
                        help="Show cross-vital correlations")
    parser.add_argument("--timeline", action="store_true",
                        help="Show pulse trend over time")
    parser.add_argument("--critical", action="store_true",
                        help="Show only critical vital signs")
    parser.add_argument("--top", type=int, default=0,
                        help="Show top N worst-scoring functions")
    parser.add_argument("--no-color", action="store_true",
                        help="Disable colored output")
    parser.add_argument("--reset", action="store_true",
                        help="Clear timeline history")

    args = parser.parse_args(argv)

    global USE_COLOR
    if args.no_color or os.environ.get("NO_COLOR"):
        USE_COLOR = False

    # Determine scan directory for history
    scan_dir = args.paths[0] if args.paths else "."
    if os.path.isfile(scan_dir):
        scan_dir = os.path.dirname(scan_dir) or "."

    if args.reset:
        clear_history(scan_dir)
        print("Timeline history cleared.")
        return 0

    report = analyze_pulse(args.paths, recursive=args.recursive,
                           top_n=max(args.top, 10))

    # Save history
    save_history(scan_dir, report)

    # Load timeline
    report.timeline = load_history(scan_dir)

    if args.json:
        out = {
            "timestamp": report.timestamp,
            "files_scanned": report.files_scanned,
            "total_functions": report.total_functions,
            "pulse_score": report.pulse_score,
            "pulse_class": report.pulse_class,
            "vitals": [{
                "code": v.code, "name": v.name,
                "score": round(v.score, 1), "status": v.status,
                "details": v.details
            } for v in report.vitals],
            "correlations": [{
                "vital_a": c.vital_a, "vital_b": c.vital_b,
                "description": c.description, "severity": c.severity
            } for c in report.correlations],
            "insights": report.insights,
            "worst_functions": report.worst_functions[:args.top] if args.top else report.worst_functions,
        }
        print(json.dumps(out, indent=2))
        return 0

    if args.html:
        html = _generate_html(report)
        with open(args.html, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"Dashboard written to {args.html}")
        return 0

    if args.timeline:
        history = report.timeline
        if not history:
            print("No timeline history yet. Run sauravpulse a few times to build history.")
            return 0
        print(bold("\n  Pulse Timeline:"))
        for entry in history[-15:]:
            ts = entry.get("timestamp", "?")[:16]
            score = entry.get("pulse_score", 0)
            cls = entry.get("pulse_class", "?")
            bar_len = int(score / 2)
            bar = "=" * bar_len
            pfn = {"Thriving": green, "Healthy": cyan, "Stable": yellow,
                   "Stressed": yellow, "Critical": red}.get(cls, str)
            print(f"    {dim(ts)}  {pfn(f'{score:5.1f}')}  {pfn(bar)}  {pfn(cls)}")
        print()
        return 0

    _print_report(report, show_vital=args.vital, show_correlations=args.correlations,
                  show_critical=args.critical, top_n=args.top)
    return 0


if __name__ == "__main__":
    sys.exit(main())
