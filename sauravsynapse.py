#!/usr/bin/env python3
"""sauravsynapse — Autonomous Code Neural Network Analyzer for sauravcode.

Models a .srv codebase as a neural network: functions are neurons,
calls are synapses, data flow is signal propagation.  Detects bottlenecks,
measures plasticity, classifies neuron types, and generates autonomous
rewiring recommendations.

Analysis engines (7):
    S001  Neuron Classifier         Sensory / Interneuron / Motor classification
    S002  Synapse Mapper            Call relationships with weights & directionality
    S003  Signal Propagation        Path tracing from inputs to outputs
    S004  Plasticity Analyzer       Codebase adaptability scoring
    S005  Bottleneck Detector       Information flow chokepoints
    S006  Network Health Scorer     Composite 0-100 weighted score
    S007  Insight Generator         Autonomous rewiring recommendations

Neuron types:
    Sensory     Functions that read external data (files, input, HTTP)
    Interneuron Pure computation / transformation functions
    Motor       Functions that produce output / side-effects (print, write)
    Hub         In+out degree > 2× average connectivity
    Isolated    No incoming or outgoing connections

Health tiers (0-100):
    Genius   85-100
    Healthy  70-84
    Functional 55-69
    Degraded 40-54
    Damaged  0-39

Usage:
    python sauravsynapse.py .                        # Analyze .srv files in cwd
    python sauravsynapse.py . --recursive            # Include subdirectories
    python sauravsynapse.py . --html report.html     # Interactive HTML dashboard
    python sauravsynapse.py . --json                 # JSON output
    python sauravsynapse.py . --neurons              # Show neuron classification
    python sauravsynapse.py . --synapses             # Show synapse map
    python sauravsynapse.py . --propagation          # Show signal paths
    python sauravsynapse.py . --bottlenecks          # Show bottleneck analysis
    python sauravsynapse.py . --plasticity           # Show plasticity scores
    python sauravsynapse.py . --top N                # Top N most connected neurons
    python sauravsynapse.py . --no-color             # Disable colors
"""

import sys
import os
import re
import json
import math
import argparse
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Set, Tuple, Any, Optional
from datetime import datetime

__version__ = "1.0.0"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Windows UTF-8 fix ────────────────────────────────────────────────
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    import io as _io
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from _srv_utils import find_srv_files as _find_srv_files, get_indent as _get_indent

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
CALL_PATTERN = re.compile(r'\b([a-zA-Z_]\w*)\s*\(')
BRANCH_KEYWORDS = {'if', 'elif', 'while', 'for', 'foreach', 'catch', 'and', 'or'}

SENSORY_CALLS = {'read_file', 'input', 'http_get', 'fetch', 'parse_json',
                 'parse_xml', 'parse_csv', 'load', 'open', 'import_module',
                 'download', 'recv', 'accept', 'listen', 'read', 'readline',
                 'get_env', 'get_config', 'from_file', 'deserialize'}

MOTOR_CALLS = {'print', 'println', 'write_file', 'http_post', 'send',
               'display', 'emit', 'log', 'write', 'render', 'output',
               'publish', 'broadcast', 'notify', 'alert', 'flush',
               'export', 'save', 'serialize', 'put', 'post'}

GUARD_CONTEXT = re.compile(
    r'\b(assert|throw|raise|return\s+null|return\s+false|return\s+err)\b'
    r'|!=\s*null|==\s*null|is\s+null|is\s+not\s+null'
)


# ── Data Classes ─────────────────────────────────────────────────────

@dataclass
class Neuron:
    """A function modeled as a neuron."""
    name: str
    file: str
    line: int
    neuron_type: str = "Interneuron"  # Sensory, Interneuron, Motor
    is_hub: bool = False
    is_isolated: bool = False
    loc: int = 0
    params: int = 0
    calls_out: List[str] = field(default_factory=list)
    called_by: List[str] = field(default_factory=list)
    sensory_signals: int = 0
    motor_signals: int = 0
    guard_context_calls: int = 0
    complexity: int = 1

    @property
    def fqn(self):
        return f"{self.file}::{self.name}"

    @property
    def in_degree(self):
        return len(self.called_by)

    @property
    def out_degree(self):
        return len(self.calls_out)

    @property
    def total_degree(self):
        return self.in_degree + self.out_degree


@dataclass
class Synapse:
    """A call relationship modeled as a synapse."""
    source: str  # caller function name
    target: str  # callee function name
    weight: int = 1  # call count
    synapse_type: str = "excitatory"  # excitatory or inhibitory
    file: str = ""


@dataclass
class SignalPath:
    """A traced path from sensory input to motor output."""
    path: List[str]
    length: int = 0
    source_type: str = "Sensory"
    sink_type: str = "Motor"


@dataclass
class Bottleneck:
    """An identified information flow bottleneck."""
    neuron: str
    category: str  # chokepoint, overloaded_hub, starved
    severity: str  # critical, warning, info
    in_degree: int = 0
    out_degree: int = 0
    description: str = ""


@dataclass
class NetworkReport:
    """Full neural network analysis report."""
    timestamp: str = ""
    files_scanned: int = 0
    total_neurons: int = 0
    neurons: List[Dict[str, Any]] = field(default_factory=list)
    synapses: List[Dict[str, Any]] = field(default_factory=list)
    signal_paths: List[Dict[str, Any]] = field(default_factory=list)
    bottlenecks: List[Dict[str, Any]] = field(default_factory=list)
    plasticity_score: float = 0.0
    health_score: float = 0.0
    health_tier: str = ""
    neuron_distribution: Dict[str, int] = field(default_factory=dict)
    insights: List[str] = field(default_factory=list)
    avg_path_length: float = 0.0
    max_path_length: int = 0
    connectivity_density: float = 0.0


# ── File Parser ──────────────────────────────────────────────────────

def parse_file(filepath: str) -> List[Neuron]:
    """Parse a .srv file and extract neurons (functions)."""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
    except OSError:
        return []

    neurons: List[Neuron] = []
    current: Optional[Neuron] = None
    base_indent = 0
    fname = os.path.basename(filepath)
    in_guard_context = False

    for i, raw in enumerate(lines):
        line = raw.rstrip()
        stripped = line.lstrip()

        if not stripped or stripped.startswith('#'):
            continue

        indent = _get_indent(raw)
        m = FUNCTION_DEF.match(line)

        if m:
            current = Neuron(name=m.group(3), file=fname, line=i + 1)
            base_indent = indent
            after = line[m.end():].strip()
            if after:
                current.params = len(after.split())
            neurons.append(current)
            continue

        if current is not None and indent > base_indent:
            current.loc += 1

            first_word = stripped.split()[0] if stripped else ""
            if first_word in BRANCH_KEYWORDS:
                current.complexity += 1

            # Check if in guard context
            in_guard_context = bool(GUARD_CONTEXT.search(stripped))

            for cm in CALL_PATTERN.finditer(stripped):
                cname = cm.group(1)
                if cname in BRANCH_KEYWORDS or cname in ('end', 'return'):
                    continue
                current.calls_out.append(cname)

                if cname in SENSORY_CALLS:
                    current.sensory_signals += 1
                elif cname in MOTOR_CALLS:
                    current.motor_signals += 1

                if in_guard_context:
                    current.guard_context_calls += 1

    return neurons


# ── S001: Neuron Classifier ──────────────────────────────────────────

def classify_neurons(neurons: List[Neuron]) -> List[Neuron]:
    """Classify neurons as Sensory, Interneuron, or Motor."""
    if not neurons:
        return neurons

    # Build call graph for in-degree
    all_names = {n.name for n in neurons}
    call_counts = defaultdict(list)
    for n in neurons:
        for c in n.calls_out:
            if c in all_names:
                call_counts[c].append(n.name)

    # Set called_by
    for n in neurons:
        n.called_by = call_counts.get(n.name, [])

    # Classify type
    for n in neurons:
        if n.sensory_signals > 0 and n.sensory_signals >= n.motor_signals:
            n.neuron_type = "Sensory"
        elif n.motor_signals > 0 and n.motor_signals > n.sensory_signals:
            n.neuron_type = "Motor"
        else:
            n.neuron_type = "Interneuron"

    # Detect hubs and isolated
    if neurons:
        avg_degree = sum(n.total_degree for n in neurons) / len(neurons)
        threshold = max(4, avg_degree * 2)
        for n in neurons:
            if n.total_degree > threshold:
                n.is_hub = True
            if n.in_degree == 0 and n.out_degree == 0:
                n.is_isolated = True

    return neurons


# ── S002: Synapse Mapper ─────────────────────────────────────────────

def map_synapses(neurons: List[Neuron]) -> List[Synapse]:
    """Map call relationships as synapses with weights."""
    all_names = {n.name for n in neurons}
    synapse_map: Dict[Tuple[str, str], Synapse] = {}

    for n in neurons:
        call_freq = defaultdict(int)
        guard_calls = set()

        # Count call frequencies
        for c in n.calls_out:
            if c in all_names and c != n.name:
                call_freq[c] += 1

        # Determine inhibitory calls (those in guard contexts)
        if n.guard_context_calls > 0:
            # Heuristic: if a function's calls are mostly in guard context, mark as inhibitory
            guard_ratio = n.guard_context_calls / max(1, len(n.calls_out))
            if guard_ratio > 0.5:
                guard_calls = set(call_freq.keys())

        for target, count in call_freq.items():
            key = (n.name, target)
            stype = "inhibitory" if target in guard_calls else "excitatory"
            if key in synapse_map:
                synapse_map[key].weight += count
            else:
                synapse_map[key] = Synapse(
                    source=n.name, target=target,
                    weight=count, synapse_type=stype, file=n.file
                )

    return list(synapse_map.values())


# ── S003: Signal Propagation Analyzer ────────────────────────────────

def analyze_propagation(neurons: List[Neuron], synapses: List[Synapse]) -> List[SignalPath]:
    """Trace signal paths from Sensory neurons to Motor neurons."""
    if not neurons or not synapses:
        return []

    # Build adjacency
    adj: Dict[str, List[str]] = defaultdict(list)
    for s in synapses:
        adj[s.source].append(s.target)

    sensory = [n.name for n in neurons if n.neuron_type == "Sensory"]
    motor = set(n.name for n in neurons if n.neuron_type == "Motor")
    all_names = {n.name for n in neurons}

    paths: List[SignalPath] = []

    # BFS from each sensory neuron to find motor neurons
    for start in sensory:
        visited: Set[str] = set()
        queue: deque = deque()
        queue.append((start, [start]))
        visited.add(start)

        while queue:
            current, path = queue.popleft()

            if current in motor and current != start:
                paths.append(SignalPath(
                    path=path, length=len(path) - 1,
                    source_type="Sensory", sink_type="Motor"
                ))
                continue  # Don't continue past motor neurons

            if len(path) > 20:  # prevent infinite loops
                continue

            for neighbor in adj.get(current, []):
                if neighbor not in visited and neighbor in all_names:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

    return paths


# ── S004: Plasticity Analyzer ────────────────────────────────────────

def compute_plasticity(neurons: List[Neuron], synapses: List[Synapse]) -> float:
    """Score codebase plasticity (adaptability) 0-100."""
    if not neurons:
        return 50.0

    scores = []

    # 1. Coupling looseness (fewer direct dependencies = more plastic)
    avg_out = sum(n.out_degree for n in neurons) / len(neurons) if neurons else 0
    coupling_score = max(0, min(100, 100 - avg_out * 10))
    scores.append(coupling_score)

    # 2. Parameter flexibility (functions with moderate params = good interfaces)
    param_scores = []
    for n in neurons:
        if n.params == 0:
            param_scores.append(60)  # no params = somewhat rigid
        elif n.params <= 3:
            param_scores.append(90)  # sweet spot
        elif n.params <= 6:
            param_scores.append(70)  # acceptable
        else:
            param_scores.append(40)  # too many = rigid
    flex_score = sum(param_scores) / len(param_scores) if param_scores else 50
    scores.append(flex_score)

    # 3. Function size (smaller = more plastic)
    avg_loc = sum(n.loc for n in neurons) / len(neurons) if neurons else 0
    if avg_loc <= 10:
        size_score = 95
    elif avg_loc <= 20:
        size_score = 80
    elif avg_loc <= 40:
        size_score = 60
    else:
        size_score = max(20, 60 - (avg_loc - 40))
    scores.append(size_score)

    # 4. Isolation ratio (some isolated neurons = modular, too many = disconnected)
    isolated = sum(1 for n in neurons if n.is_isolated)
    iso_ratio = isolated / len(neurons) if neurons else 0
    if iso_ratio < 0.1:
        iso_score = 80
    elif iso_ratio < 0.3:
        iso_score = 90  # good modularity
    elif iso_ratio < 0.5:
        iso_score = 60
    else:
        iso_score = 40  # too disconnected
    scores.append(iso_score)

    # 5. Complexity (lower complexity = easier to rewire)
    avg_cx = sum(n.complexity for n in neurons) / len(neurons) if neurons else 1
    cx_score = max(0, min(100, 100 - (avg_cx - 1) * 15))
    scores.append(cx_score)

    return sum(scores) / len(scores) if scores else 50.0


# ── S005: Bottleneck Detector ────────────────────────────────────────

def detect_bottlenecks(neurons: List[Neuron]) -> List[Bottleneck]:
    """Identify information flow bottlenecks."""
    if not neurons:
        return []

    bottlenecks: List[Bottleneck] = []
    avg_in = sum(n.in_degree for n in neurons) / len(neurons) if neurons else 0
    avg_out = sum(n.out_degree for n in neurons) / len(neurons) if neurons else 0

    for n in neurons:
        # Chokepoint: high in-degree AND high out-degree (everything flows through)
        if n.in_degree > max(3, avg_in * 2) and n.out_degree > max(2, avg_out * 1.5):
            bottlenecks.append(Bottleneck(
                neuron=n.fqn, category="chokepoint",
                severity="critical" if n.in_degree > avg_in * 3 else "warning",
                in_degree=n.in_degree, out_degree=n.out_degree,
                description=f"Signal chokepoint: {n.in_degree} inputs, {n.out_degree} outputs"
            ))
        # Overloaded hub: very high total degree
        elif n.is_hub:
            bottlenecks.append(Bottleneck(
                neuron=n.fqn, category="overloaded_hub",
                severity="warning",
                in_degree=n.in_degree, out_degree=n.out_degree,
                description=f"Overloaded hub: {n.total_degree} total connections"
            ))
        # Starved neuron: defined but never called and calls nothing useful
        elif n.in_degree == 0 and n.out_degree > 0 and n.neuron_type == "Interneuron":
            bottlenecks.append(Bottleneck(
                neuron=n.fqn, category="starved",
                severity="info",
                in_degree=0, out_degree=n.out_degree,
                description=f"Never called but has {n.out_degree} outgoing connections"
            ))

    return bottlenecks


# ── S006: Network Health Scorer ──────────────────────────────────────

def compute_health_score(neurons: List[Neuron], synapses: List[Synapse],
                         paths: List[SignalPath], plasticity: float,
                         bottlenecks: List[Bottleneck]) -> Tuple[float, str]:
    """Compute composite health score 0-100 and tier."""
    if not neurons:
        return 50.0, "Functional"

    scores = []

    # 1. Neuron diversity (good mix of types) - weight 0.15
    types = defaultdict(int)
    for n in neurons:
        types[n.neuron_type] += 1
    n_types = len(types)
    if n_types >= 3:
        diversity = 90
    elif n_types == 2:
        diversity = 70
    else:
        diversity = 40
    # Penalize extreme imbalance
    if types:
        max_ratio = max(types.values()) / len(neurons)
        if max_ratio > 0.8:
            diversity -= 20
    scores.append(diversity * 0.15)

    # 2. Connectivity balance (not too sparse/dense) - weight 0.20
    n_possible = len(neurons) * (len(neurons) - 1) if len(neurons) > 1 else 1
    density = len(synapses) / n_possible if n_possible > 0 else 0
    if 0.05 <= density <= 0.3:
        conn_score = 90
    elif 0.01 <= density <= 0.5:
        conn_score = 70
    elif density == 0:
        conn_score = 30
    else:
        conn_score = 50
    scores.append(conn_score * 0.20)

    # 3. Path efficiency (shorter average paths = better) - weight 0.20
    if paths:
        avg_len = sum(p.length for p in paths) / len(paths)
        if avg_len <= 3:
            path_score = 95
        elif avg_len <= 5:
            path_score = 80
        elif avg_len <= 8:
            path_score = 60
        else:
            path_score = max(30, 60 - (avg_len - 8) * 5)
    else:
        path_score = 50  # no paths found = neutral
    scores.append(path_score * 0.20)

    # 4. Plasticity - weight 0.25
    scores.append(plasticity * 0.25)

    # 5. Bottleneck absence - weight 0.20
    critical = sum(1 for b in bottlenecks if b.severity == "critical")
    warnings = sum(1 for b in bottlenecks if b.severity == "warning")
    bn_score = max(0, 100 - critical * 25 - warnings * 10)
    scores.append(bn_score * 0.20)

    total = sum(scores)

    # Classify tier
    if total >= 85:
        tier = "Genius"
    elif total >= 70:
        tier = "Healthy"
    elif total >= 55:
        tier = "Functional"
    elif total >= 40:
        tier = "Degraded"
    else:
        tier = "Damaged"

    return round(total, 1), tier


# ── S007: Insight Generator ──────────────────────────────────────────

def generate_insights(neurons: List[Neuron], synapses: List[Synapse],
                      paths: List[SignalPath], bottlenecks: List[Bottleneck],
                      plasticity: float, health_score: float) -> List[str]:
    """Generate autonomous rewiring recommendations."""
    insights: List[str] = []

    if not neurons:
        insights.append("No neurons found — add functions to build a neural network")
        return insights

    # Type distribution insights
    types = defaultdict(int)
    for n in neurons:
        types[n.neuron_type] += 1

    if types.get("Motor", 0) == 0:
        insights.append("No motor neurons detected — consider adding output/display functions")
    if types.get("Sensory", 0) == 0:
        insights.append("No sensory neurons detected — consider adding input/data-loading functions")

    motor_ratio = types.get("Motor", 0) / len(neurons) if neurons else 0
    if motor_ratio > 0.5:
        insights.append("Over 50% of neurons are Motor type — extract computation into Interneurons for better signal processing")

    # Bottleneck insights
    chokepoints = [b for b in bottlenecks if b.category == "chokepoint"]
    if chokepoints:
        for cp in chokepoints[:3]:
            insights.append(f"Chokepoint '{cp.neuron}' — consider splitting into specialized sub-functions to distribute signal load")

    hubs = [b for b in bottlenecks if b.category == "overloaded_hub"]
    if hubs:
        for h in hubs[:3]:
            insights.append(f"Overloaded hub '{h.neuron}' ({h.in_degree}in/{h.out_degree}out) — consider introducing mediator functions")

    # Path insights
    if paths:
        max_path = max(paths, key=lambda p: p.length)
        if max_path.length > 8:
            insights.append(f"Longest signal path is {max_path.length} hops ({' -> '.join(max_path.path[:5])}...) — consider shortcutting with direct connections")
    elif types.get("Sensory", 0) > 0 and types.get("Motor", 0) > 0:
        insights.append("No complete signal paths from Sensory to Motor neurons — network may be fragmented")

    # Plasticity insights
    if plasticity < 40:
        insights.append("Low plasticity — functions are tightly coupled; consider reducing dependencies and function sizes")
    elif plasticity > 85:
        insights.append("High plasticity — network is very flexible, good for rapid evolution")

    # Isolated neuron insights
    isolated = [n for n in neurons if n.is_isolated]
    if len(isolated) > len(neurons) * 0.3:
        insights.append(f"{len(isolated)} isolated neurons ({len(isolated)*100//len(neurons)}%) — consider connecting them or removing dead code")

    # Hub distribution
    hub_count = sum(1 for n in neurons if n.is_hub)
    if hub_count == 0 and len(neurons) > 5:
        insights.append("No hub neurons — network may lack coordination centers")

    # Health-based insights
    if health_score < 40:
        insights.append("Network health is Damaged — prioritize reducing bottlenecks and improving connectivity")
    elif health_score >= 85:
        insights.append("Network architecture is excellent — well-balanced neuron types and signal flow")

    return insights


# ── Full Analysis Pipeline ───────────────────────────────────────────

def analyze(paths_arg: List[str], recursive: bool = False) -> NetworkReport:
    """Run full neural network analysis on .srv files."""
    files = _find_srv_files(paths_arg, recursive=recursive)
    report = NetworkReport(timestamp=datetime.now().isoformat())
    report.files_scanned = len(files)

    if not files:
        report.insights = ["No .srv files found"]
        report.health_tier = "Damaged"
        return report

    # Parse all files
    all_neurons: List[Neuron] = []
    for fpath in files:
        neurons = parse_file(fpath)
        all_neurons.extend(neurons)

    # S001: Classify neurons
    all_neurons = classify_neurons(all_neurons)
    report.total_neurons = len(all_neurons)

    # S002: Map synapses
    synapses = map_synapses(all_neurons)

    # S003: Signal propagation
    signal_paths = analyze_propagation(all_neurons, synapses)

    # S004: Plasticity
    plasticity = compute_plasticity(all_neurons, synapses)
    report.plasticity_score = round(plasticity, 1)

    # S005: Bottlenecks
    bottlenecks = detect_bottlenecks(all_neurons)

    # S006: Health score
    health, tier = compute_health_score(all_neurons, synapses, signal_paths, plasticity, bottlenecks)
    report.health_score = health
    report.health_tier = tier

    # S007: Insights
    insights = generate_insights(all_neurons, synapses, signal_paths, bottlenecks, plasticity, health)
    report.insights = insights

    # Populate report data
    report.neuron_distribution = defaultdict(int)
    for n in all_neurons:
        report.neuron_distribution[n.neuron_type] += 1
        report.neurons.append({
            'name': n.name, 'file': n.file, 'line': n.line,
            'type': n.neuron_type, 'is_hub': n.is_hub,
            'is_isolated': n.is_isolated, 'in_degree': n.in_degree,
            'out_degree': n.out_degree, 'loc': n.loc,
            'complexity': n.complexity,
        })

    for s in synapses:
        report.synapses.append({
            'source': s.source, 'target': s.target,
            'weight': s.weight, 'type': s.synapse_type,
        })

    for p in signal_paths:
        report.signal_paths.append({
            'path': p.path, 'length': p.length,
        })

    for b in bottlenecks:
        report.bottlenecks.append({
            'neuron': b.neuron, 'category': b.category,
            'severity': b.severity, 'description': b.description,
            'in_degree': b.in_degree, 'out_degree': b.out_degree,
        })

    if signal_paths:
        report.avg_path_length = round(sum(p.length for p in signal_paths) / len(signal_paths), 2)
        report.max_path_length = max(p.length for p in signal_paths)

    n_possible = len(all_neurons) * (len(all_neurons) - 1) if len(all_neurons) > 1 else 1
    report.connectivity_density = round(len(synapses) / n_possible, 4) if n_possible > 0 else 0

    return report


# ── HTML Dashboard ───────────────────────────────────────────────────

def _html_esc(s: str) -> str:
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def generate_html_report(report: NetworkReport) -> str:
    """Generate an interactive HTML dashboard."""
    # Neuron type colors
    type_colors = {
        'Sensory': '#4CAF50',
        'Interneuron': '#2196F3',
        'Motor': '#FF9800',
    }

    # Build neuron rows
    neuron_rows = ""
    for n in sorted(report.neurons, key=lambda x: x['in_degree'] + x['out_degree'], reverse=True):
        badges = ""
        if n['is_hub']:
            badges += ' <span class="badge hub">HUB</span>'
        if n['is_isolated']:
            badges += ' <span class="badge isolated">ISOLATED</span>'
        color = type_colors.get(n['type'], '#666')
        neuron_rows += f"""<tr>
            <td><span class="type-dot" style="background:{color}"></span> {_html_esc(n['name'])}{badges}</td>
            <td>{_html_esc(n['file'])}</td>
            <td>{n['type']}</td>
            <td>{n['in_degree']}</td>
            <td>{n['out_degree']}</td>
            <td>{n['complexity']}</td>
        </tr>\n"""

    # Synapse rows
    synapse_rows = ""
    for s in sorted(report.synapses, key=lambda x: x['weight'], reverse=True)[:50]:
        sclass = "inhibitory" if s['type'] == 'inhibitory' else "excitatory"
        synapse_rows += f"""<tr class="{sclass}">
            <td>{_html_esc(s['source'])}</td>
            <td>{_html_esc(s['target'])}</td>
            <td>{s['weight']}</td>
            <td>{s['type']}</td>
        </tr>\n"""

    # Bottleneck rows
    bn_rows = ""
    for b in report.bottlenecks:
        sev_class = b['severity']
        bn_rows += f"""<tr class="{sev_class}">
            <td>{_html_esc(b['neuron'])}</td>
            <td>{b['category']}</td>
            <td>{b['severity']}</td>
            <td>{_html_esc(b['description'])}</td>
        </tr>\n"""

    # Insights list
    insight_items = "\n".join(f"<li>{_html_esc(i)}</li>" for i in report.insights)

    # Distribution data for chart
    dist_data = dict(report.neuron_distribution)

    # Path lengths for histogram
    path_lengths = [p['length'] for p in report.signal_paths]
    path_hist = defaultdict(int)
    for pl in path_lengths:
        path_hist[pl] += 1

    # Health gauge color
    if report.health_score >= 85:
        gauge_color = '#4CAF50'
    elif report.health_score >= 70:
        gauge_color = '#8BC34A'
    elif report.health_score >= 55:
        gauge_color = '#FFC107'
    elif report.health_score >= 40:
        gauge_color = '#FF9800'
    else:
        gauge_color = '#F44336'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>sauravsynapse Neural Network Report</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       background: #0d1117; color: #c9d1d9; padding: 2rem; line-height: 1.6; }}
.header {{ text-align: center; margin-bottom: 2rem; }}
.header h1 {{ color: #58a6ff; font-size: 2rem; }}
.header .subtitle {{ color: #8b949e; margin-top: 0.5rem; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.5rem; margin-bottom: 2rem; }}
.card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 1.5rem; }}
.card h2 {{ color: #58a6ff; font-size: 1.1rem; margin-bottom: 1rem; border-bottom: 1px solid #30363d; padding-bottom: 0.5rem; }}
.gauge {{ text-align: center; }}
.gauge-value {{ font-size: 3rem; font-weight: bold; color: {gauge_color}; }}
.gauge-tier {{ font-size: 1.2rem; color: #8b949e; }}
.stat {{ display: flex; justify-content: space-between; padding: 0.3rem 0; border-bottom: 1px solid #21262d; }}
.stat-label {{ color: #8b949e; }}
.stat-value {{ color: #f0f6fc; font-weight: 600; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 0.5rem; font-size: 0.85rem; }}
th, td {{ padding: 0.5rem; text-align: left; border-bottom: 1px solid #21262d; }}
th {{ color: #58a6ff; font-weight: 600; }}
.badge {{ font-size: 0.7rem; padding: 2px 6px; border-radius: 10px; font-weight: 600; }}
.badge.hub {{ background: #f97316; color: #fff; }}
.badge.isolated {{ background: #6b7280; color: #fff; }}
.type-dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; }}
.critical {{ background: rgba(244, 67, 54, 0.1); }}
.warning {{ background: rgba(255, 152, 0, 0.1); }}
.info {{ background: rgba(33, 150, 243, 0.1); }}
.inhibitory {{ background: rgba(156, 39, 176, 0.05); }}
.insight-list {{ list-style: none; }}
.insight-list li {{ padding: 0.5rem 0; border-bottom: 1px solid #21262d; }}
.insight-list li::before {{ content: "\\1F4A1 "; }}
.dist-bar {{ display: flex; height: 30px; border-radius: 4px; overflow: hidden; margin-top: 0.5rem; }}
.dist-segment {{ display: flex; align-items: center; justify-content: center; color: #fff; font-size: 0.75rem; font-weight: 600; }}
.path-bar {{ display: inline-block; background: #58a6ff; height: 20px; border-radius: 3px; margin-right: 4px; min-width: 2px; }}
</style>
</head>
<body>
<div class="header">
    <h1>&#x1F9E0; sauravsynapse — Neural Network Report</h1>
    <div class="subtitle">Generated {_html_esc(report.timestamp)} | {report.files_scanned} files | {report.total_neurons} neurons</div>
</div>

<div class="grid">
    <div class="card gauge">
        <h2>Network Health</h2>
        <div class="gauge-value">{report.health_score}</div>
        <div class="gauge-tier">{report.health_tier}</div>
        <div style="margin-top:1rem">
            <div class="stat"><span class="stat-label">Plasticity</span><span class="stat-value">{report.plasticity_score}</span></div>
            <div class="stat"><span class="stat-label">Density</span><span class="stat-value">{report.connectivity_density}</span></div>
            <div class="stat"><span class="stat-label">Avg Path</span><span class="stat-value">{report.avg_path_length}</span></div>
            <div class="stat"><span class="stat-label">Max Path</span><span class="stat-value">{report.max_path_length}</span></div>
        </div>
    </div>

    <div class="card">
        <h2>Neuron Distribution</h2>
        <div class="dist-bar">
            {"".join(f'<div class="dist-segment" style="flex:{dist_data.get(t,0)};background:{c}">{t} ({dist_data.get(t,0)})</div>' for t, c in type_colors.items() if dist_data.get(t, 0) > 0)}
        </div>
        <div style="margin-top:1rem">
            <div class="stat"><span class="stat-label">Hubs</span><span class="stat-value">{sum(1 for n in report.neurons if n['is_hub'])}</span></div>
            <div class="stat"><span class="stat-label">Isolated</span><span class="stat-value">{sum(1 for n in report.neurons if n['is_isolated'])}</span></div>
            <div class="stat"><span class="stat-label">Bottlenecks</span><span class="stat-value">{len(report.bottlenecks)}</span></div>
        </div>
    </div>

    <div class="card">
        <h2>Signal Path Lengths</h2>
        {"".join(f'<div style="margin:3px 0"><span style="color:#8b949e;width:30px;display:inline-block">{l}</span><span class="path-bar" style="width:{c*30}px"></span> {c}</div>' for l, c in sorted(path_hist.items())) if path_hist else '<p style="color:#8b949e">No signal paths found</p>'}
    </div>
</div>

<div class="card" style="margin-bottom:1.5rem">
    <h2>&#x1F4A1; Insights</h2>
    <ul class="insight-list">{insight_items}</ul>
</div>

<div class="card" style="margin-bottom:1.5rem">
    <h2>Neurons ({report.total_neurons})</h2>
    <table>
        <thead><tr><th>Name</th><th>File</th><th>Type</th><th>In</th><th>Out</th><th>Complexity</th></tr></thead>
        <tbody>{neuron_rows}</tbody>
    </table>
</div>

<div class="grid">
    <div class="card">
        <h2>Synapses (top 50)</h2>
        <table>
            <thead><tr><th>Source</th><th>Target</th><th>Weight</th><th>Type</th></tr></thead>
            <tbody>{synapse_rows}</tbody>
        </table>
    </div>

    <div class="card">
        <h2>Bottlenecks ({len(report.bottlenecks)})</h2>
        <table>
            <thead><tr><th>Neuron</th><th>Category</th><th>Severity</th><th>Description</th></tr></thead>
            <tbody>{bn_rows if bn_rows else '<tr><td colspan="4" style="color:#8b949e">No bottlenecks detected</td></tr>'}</tbody>
        </table>
    </div>
</div>

<div style="text-align:center;margin-top:2rem;color:#8b949e;font-size:0.85rem">
    sauravsynapse v{__version__} — Autonomous Code Neural Network Analyzer
</div>
</body>
</html>"""
    return html


# ── CLI Output ───────────────────────────────────────────────────────

def print_neuron_table(report: NetworkReport):
    """Print neuron classification table."""
    print(f"\n{bold('NEURON CLASSIFICATION')} ({report.total_neurons} neurons)")
    print(f"{'─' * 80}")
    print(f"  {'Name':<25} {'File':<20} {'Type':<12} {'In':<4} {'Out':<4} {'Cx':<4}")
    print(f"  {'─' * 75}")
    for n in sorted(report.neurons, key=lambda x: x['in_degree'] + x['out_degree'], reverse=True):
        badges = ""
        if n['is_hub']:
            badges = f" {yellow('[HUB]')}"
        elif n['is_isolated']:
            badges = f" {dim('[ISO]')}"
        type_color = green if n['type'] == 'Sensory' else (magenta if n['type'] == 'Motor' else cyan)
        print(f"  {n['name']:<25} {n['file']:<20} {type_color(n['type']):<20} {n['in_degree']:<4} {n['out_degree']:<4} {n['complexity']:<4}{badges}")


def print_synapse_table(report: NetworkReport):
    """Print synapse map."""
    print(f"\n{bold('SYNAPSE MAP')} ({len(report.synapses)} connections)")
    print(f"{'─' * 70}")
    print(f"  {'Source':<20} {'→ Target':<20} {'Weight':<8} {'Type':<12}")
    print(f"  {'─' * 65}")
    for s in sorted(report.synapses, key=lambda x: x['weight'], reverse=True)[:30]:
        stype_f = red(s['type']) if s['type'] == 'inhibitory' else green(s['type'])
        print(f"  {s['source']:<20} → {s['target']:<18} {s['weight']:<8} {stype_f}")


def print_propagation(report: NetworkReport):
    """Print signal propagation paths."""
    print(f"\n{bold('SIGNAL PROPAGATION')} ({len(report.signal_paths)} paths)")
    print(f"{'─' * 70}")
    if not report.signal_paths:
        print(f"  {dim('No complete signal paths found')}")
        return
    print(f"  Avg path length: {cyan(str(report.avg_path_length))}")
    print(f"  Max path length: {cyan(str(report.max_path_length))}")
    print(f"\n  {'Path':<60} {'Len':<5}")
    print(f"  {'─' * 65}")
    for p in sorted(report.signal_paths, key=lambda x: x['length'], reverse=True)[:15]:
        path_str = " → ".join(p['path'][:8])
        if len(p['path']) > 8:
            path_str += " → ..."
        print(f"  {path_str:<60} {p['length']:<5}")


def print_bottlenecks(report: NetworkReport):
    """Print bottleneck analysis."""
    print(f"\n{bold('BOTTLENECKS')} ({len(report.bottlenecks)} detected)")
    print(f"{'─' * 70}")
    if not report.bottlenecks:
        print(f"  {green('No bottlenecks detected — signal flow is smooth')}")
        return
    for b in report.bottlenecks:
        sev_f = red if b['severity'] == 'critical' else (yellow if b['severity'] == 'warning' else dim)
        sev_label = sev_f('[' + b['severity'].upper() + ']')
        print(f"  {sev_label:<18} {b['neuron']}")
        print(f"  {'':18} {dim(b['description'])}")


def print_summary(report: NetworkReport):
    """Print overall summary."""
    # Health tier color
    tier_color = green if report.health_score >= 70 else (yellow if report.health_score >= 55 else red)

    print(f"\n{'═' * 70}")
    print(f"  {bold('NEURAL NETWORK HEALTH REPORT')}")
    print(f"{'═' * 70}")
    print(f"\n  Health Score: {tier_color(f'{report.health_score}/100')} [{tier_color(report.health_tier)}]")
    print(f"  Plasticity:   {report.plasticity_score}/100")
    print(f"  Density:      {report.connectivity_density}")
    print(f"  Neurons:      {report.total_neurons} ({report.files_scanned} files)")

    # Distribution
    dist_parts = []
    for t, count in sorted(report.neuron_distribution.items()):
        dist_parts.append(f"{t}: {count}")
    print(f"  Types:        {', '.join(dist_parts)}")
    print(f"  Synapses:     {len(report.synapses)}")
    print(f"  Signal Paths: {len(report.signal_paths)} (avg {report.avg_path_length}, max {report.max_path_length})")
    print(f"  Bottlenecks:  {len(report.bottlenecks)}")

    if report.insights:
        print(f"\n  {bold('Insights:')}")
        for i in report.insights[:8]:
            print(f"    • {i}")
    print()


# ── Main ─────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point."""
    global USE_COLOR

    parser = argparse.ArgumentParser(
        prog='sauravsynapse',
        description='Autonomous Code Neural Network Analyzer for sauravcode'
    )
    parser.add_argument('paths', nargs='*', default=['.'],
                        help='Files or directories to analyze')
    parser.add_argument('--recursive', '-r', action='store_true',
                        help='Scan subdirectories')
    parser.add_argument('--html', metavar='FILE',
                        help='Generate HTML dashboard')
    parser.add_argument('--json', action='store_true',
                        help='JSON output')
    parser.add_argument('--neurons', action='store_true',
                        help='Show neuron classification table')
    parser.add_argument('--synapses', action='store_true',
                        help='Show synapse map')
    parser.add_argument('--propagation', action='store_true',
                        help='Show signal propagation paths')
    parser.add_argument('--bottlenecks', action='store_true',
                        help='Show bottleneck analysis')
    parser.add_argument('--plasticity', action='store_true',
                        help='Show plasticity details')
    parser.add_argument('--top', type=int, metavar='N',
                        help='Show top N most connected neurons')
    parser.add_argument('--no-color', action='store_true',
                        help='Disable ANSI colors')

    args = parser.parse_args(argv)

    if args.no_color:
        USE_COLOR = False

    report = analyze(args.paths, recursive=args.recursive)

    if args.json:
        out = {
            'timestamp': report.timestamp,
            'files_scanned': report.files_scanned,
            'total_neurons': report.total_neurons,
            'health_score': report.health_score,
            'health_tier': report.health_tier,
            'plasticity_score': report.plasticity_score,
            'connectivity_density': report.connectivity_density,
            'avg_path_length': report.avg_path_length,
            'max_path_length': report.max_path_length,
            'neuron_distribution': dict(report.neuron_distribution),
            'neurons': report.neurons,
            'synapses': report.synapses,
            'signal_paths': report.signal_paths,
            'bottlenecks': report.bottlenecks,
            'insights': report.insights,
        }
        print(json.dumps(out, indent=2))
        return 0

    if args.html:
        html = generate_html_report(report)
        with open(args.html, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"HTML dashboard written to {args.html}")
        return 0

    # Specific views
    show_specific = args.neurons or args.synapses or args.propagation or args.bottlenecks or args.plasticity or args.top

    if args.neurons:
        print_neuron_table(report)
    if args.synapses:
        print_synapse_table(report)
    if args.propagation:
        print_propagation(report)
    if args.bottlenecks:
        print_bottlenecks(report)
    if args.plasticity:
        print(f"\n{bold('PLASTICITY SCORE')}: {report.plasticity_score}/100")
        if report.plasticity_score >= 80:
            print(f"  {green('Highly adaptable — easy to rewire and refactor')}")
        elif report.plasticity_score >= 60:
            print(f"  {cyan('Moderately plastic — some refactoring flexibility')}")
        elif report.plasticity_score >= 40:
            print(f"  {yellow('Low plasticity — tightly coupled, hard to change')}")
        else:
            print(f"  {red('Rigid — major restructuring needed for adaptability')}")
    if args.top:
        print(f"\n{bold(f'TOP {args.top} MOST CONNECTED NEURONS')}")
        print(f"{'─' * 60}")
        for n in sorted(report.neurons, key=lambda x: x['in_degree'] + x['out_degree'], reverse=True)[:args.top]:
            total = n['in_degree'] + n['out_degree']
            print(f"  {n['name']:<25} {n['type']:<12} degree={total} (in={n['in_degree']}, out={n['out_degree']})")

    if not show_specific:
        print_summary(report)

    return 0


if __name__ == '__main__':
    sys.exit(main())
