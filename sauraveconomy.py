#!/usr/bin/env python3
"""sauraveconomy — Autonomous Code Economy Analyzer for sauravcode.

Models a codebase as an economic system: functions are workers, modules
are economies, imports are trade, complexity is inflation, variable
flows are supply chains.  Generates an interactive HTML dashboard with
economic indicators and policy recommendations.

Analysis engines (7):
    E001  GDP Calculator             Gross productive output of the codebase
    E002  Labor Market Analyzer      Workload distribution and employment metrics
    E003  Trade Balance Analyzer     Inter-module import/export dynamics
    E004  Inflation Tracker          Code complexity bloat signals
    E005  Supply Chain Analyzer      Variable flow bottlenecks and dependency risk
    E006  Market Efficiency Scorer   Resource utilization and waste detection
    E007  Insight Generator          Autonomous policy recommendations

Usage:
    python sauraveconomy.py                          # Analyze current directory
    python sauraveconomy.py path/to/project          # Analyze specific directory
    python sauraveconomy.py path --html report.html  # Interactive HTML dashboard
    python sauraveconomy.py path --json              # JSON output
    python sauraveconomy.py path --recursive         # Deep scan
    python sauraveconomy.py path --gdp               # GDP summary only
    python sauraveconomy.py path --labor             # Labor market only
    python sauraveconomy.py path --trade             # Trade balance only
    python sauraveconomy.py path --inflation         # Inflation metrics only
    python sauraveconomy.py path --supply-chain      # Supply chain view
"""

import sys
import os
import re
import json
import math
import argparse
from collections import defaultdict
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

from _srv_utils import find_srv_files as _find_srv_files
from _termcolors import colors as _make_colors

_C = _make_colors()

# ── Regex ─────────────────────────────────────────────────────────────

FUNC_DEF_RE = re.compile(r"^(\s*)(?:function|fn)\s+(\w+)\s*(.*)")
IMPORT_RE = re.compile(r'^import\s+"([^"]+)"')
ASSIGN_RE = re.compile(r"^\s*(\w+)\s*=\s*")
IDENT_RE = re.compile(r"\b([a-zA-Z_]\w*)\b")
RETURN_RE = re.compile(r"\breturn\b")
CALL_RE = re.compile(r"\b([a-zA-Z_]\w*)\s*\(")
PARAM_RE = re.compile(r"\(([^)]*)\)")

# ── Keywords to exclude from identifier analysis ─────────────────────
KEYWORDS = {
    "if", "else", "while", "for", "return", "function", "fn", "import",
    "true", "false", "null", "and", "or", "not", "in", "break", "continue",
    "try", "catch", "throw", "class", "new", "print", "println", "let",
    "var", "const", "do", "end", "then", "elif", "switch", "case",
    "default", "match", "with", "lambda", "assert", "yield", "from",
}

# ── Data Structures ──────────────────────────────────────────────────


@dataclass
class FunctionInfo:
    """Parsed function metadata."""
    name: str
    module: str
    start_line: int
    end_line: int
    line_count: int = 0
    param_count: int = 0
    max_nesting: int = 0
    variables_written: Set[str] = field(default_factory=set)
    variables_read: Set[str] = field(default_factory=set)
    calls: Set[str] = field(default_factory=set)
    has_return: bool = False


@dataclass
class ModuleInfo:
    """Parsed module (file) metadata."""
    path: str
    name: str
    imports: List[str] = field(default_factory=list)
    functions: List[FunctionInfo] = field(default_factory=list)
    lines: int = 0
    code_lines: int = 0
    variables_defined: Set[str] = field(default_factory=set)


@dataclass
class GDPReport:
    """E001: GDP Calculator results."""
    total_functions: int = 0
    total_code_lines: int = 0
    total_modules: int = 0
    gdp_per_capita: float = 0.0
    productive_functions: int = 0
    consumption_functions: int = 0
    output_input_ratio: float = 0.0
    score: float = 0.0


@dataclass
class LaborReport:
    """E002: Labor Market Analyzer results."""
    total_workers: int = 0
    employed: int = 0
    unemployed: int = 0
    unemployment_rate: float = 0.0
    participation_rate: float = 0.0
    overworked: List[Dict[str, Any]] = field(default_factory=list)
    underemployed: List[str] = field(default_factory=list)
    gini_coefficient: float = 0.0
    score: float = 0.0


@dataclass
class TradeReport:
    """E003: Trade Balance Analyzer results."""
    total_trades: int = 0
    surplus_modules: List[Dict[str, Any]] = field(default_factory=list)
    deficit_modules: List[Dict[str, Any]] = field(default_factory=list)
    autarkic_modules: List[str] = field(default_factory=list)
    balances: List[Dict[str, Any]] = field(default_factory=list)
    score: float = 0.0


@dataclass
class InflationReport:
    """E004: Inflation Tracker results."""
    function_length_index: float = 0.0
    parameter_index: float = 0.0
    nesting_index: float = 0.0
    import_index: float = 0.0
    cpi: float = 0.0
    score: float = 0.0


@dataclass
class SupplyChainReport:
    """E005: Supply Chain Analyzer results."""
    total_variables: int = 0
    bottlenecks: List[Dict[str, Any]] = field(default_factory=list)
    single_source_risks: List[Dict[str, Any]] = field(default_factory=list)
    max_chain_depth: int = 0
    avg_chain_depth: float = 0.0
    score: float = 0.0


@dataclass
class EfficiencyReport:
    """E006: Market Efficiency Scorer results."""
    dead_code_count: int = 0
    unused_import_count: int = 0
    duplicate_indicators: int = 0
    total_waste: int = 0
    efficiency_ratio: float = 0.0
    score: float = 0.0


@dataclass
class EconomyReport:
    """Full economy analysis report."""
    timestamp: str = ""
    path: str = ""
    total_modules: int = 0
    total_functions: int = 0
    total_lines: int = 0
    total_code_lines: int = 0
    gdp: Dict[str, Any] = field(default_factory=dict)
    labor: Dict[str, Any] = field(default_factory=dict)
    trade: Dict[str, Any] = field(default_factory=dict)
    inflation: Dict[str, Any] = field(default_factory=dict)
    supply_chain: Dict[str, Any] = field(default_factory=dict)
    efficiency: Dict[str, Any] = field(default_factory=dict)
    health_score: float = 0.0
    health_tier: str = ""
    sub_scores: Dict[str, float] = field(default_factory=dict)
    insights: List[Dict[str, Any]] = field(default_factory=list)
    modules: List[Dict[str, Any]] = field(default_factory=list)


# ── Parsing ──────────────────────────────────────────────────────────

def parse_module(path: str) -> ModuleInfo:
    """Parse a .srv file into a ModuleInfo structure."""
    name = os.path.splitext(os.path.basename(path))[0]
    mod = ModuleInfo(path=path, name=name)

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            raw_lines = f.readlines()
    except (OSError, IOError):
        return mod

    mod.lines = len(raw_lines)

    current_func: Optional[FunctionInfo] = None
    func_indent = 0

    for i, raw in enumerate(raw_lines, 1):
        line = raw.rstrip()
        stripped = line.strip()

        # Count code lines (non-empty, non-comment)
        if stripped and not stripped.startswith("#") and not stripped.startswith("//"):
            mod.code_lines += 1

        # Imports
        m = IMPORT_RE.match(stripped)
        if m:
            imp_path = m.group(1)
            imp_name = os.path.splitext(os.path.basename(imp_path))[0]
            mod.imports.append(imp_name)
            continue

        # Function definition
        m = FUNC_DEF_RE.match(line)
        if m:
            # Close previous function
            if current_func is not None:
                current_func.end_line = i - 1
                current_func.line_count = current_func.end_line - current_func.start_line + 1
                mod.functions.append(current_func)

            indent = len(m.group(1))
            fname = m.group(2)
            rest = m.group(3)

            # Count parameters
            pm = PARAM_RE.search(rest)
            pcount = 0
            if pm:
                params = pm.group(1).strip()
                if params:
                    pcount = len([p.strip() for p in params.split(",") if p.strip()])

            current_func = FunctionInfo(
                name=fname,
                module=name,
                start_line=i,
                end_line=i,
                param_count=pcount,
            )
            func_indent = indent
            continue

        # Inside a function
        if current_func is not None:
            line_indent = len(line) - len(line.lstrip()) if stripped else 0

            # Detect function end: non-empty line at same or lesser indent
            if stripped and line_indent <= func_indent and i > current_func.start_line:
                current_func.end_line = i - 1
                current_func.line_count = current_func.end_line - current_func.start_line + 1
                mod.functions.append(current_func)
                current_func = None
            else:
                # Track nesting depth
                if stripped:
                    depth = max(0, line_indent - func_indent)
                    if depth > current_func.max_nesting:
                        current_func.max_nesting = depth

                # Track returns
                if RETURN_RE.search(stripped):
                    current_func.has_return = True

                # Track variable assignments
                am = ASSIGN_RE.match(line)
                if am:
                    vname = am.group(1)
                    if vname not in KEYWORDS:
                        current_func.variables_written.add(vname)
                        mod.variables_defined.add(vname)

                # Track calls and variable reads
                for cm in CALL_RE.finditer(stripped):
                    cname = cm.group(1)
                    if cname not in KEYWORDS:
                        current_func.calls.add(cname)

                for im in IDENT_RE.finditer(stripped):
                    iname = im.group(1)
                    if iname not in KEYWORDS and iname not in current_func.variables_written:
                        current_func.variables_read.add(iname)

        # Top-level assignments
        elif stripped:
            am = ASSIGN_RE.match(line)
            if am:
                vname = am.group(1)
                if vname not in KEYWORDS:
                    mod.variables_defined.add(vname)

    # Close last function
    if current_func is not None:
        current_func.end_line = mod.lines
        current_func.line_count = current_func.end_line - current_func.start_line + 1
        mod.functions.append(current_func)

    return mod


# ── E001: GDP Calculator ─────────────────────────────────────────────

def calculate_gdp(modules: List[ModuleInfo]) -> GDPReport:
    """Calculate the Gross Domestic Product of the codebase.

    GDP measures total productive output: functions defined, code lines
    produced, and the ratio of output-producing to input-consuming functions.
    """
    report = GDPReport()
    report.total_modules = len(modules)
    report.total_functions = sum(len(m.functions) for m in modules)
    report.total_code_lines = sum(m.code_lines for m in modules)

    # Productive functions = those with return statements (produce output)
    # Consumption functions = those without returns (consume/side-effect)
    for m in modules:
        for f in m.functions:
            if f.has_return:
                report.productive_functions += 1
            else:
                report.consumption_functions += 1

    # GDP per capita = functions per module
    if report.total_modules > 0:
        report.gdp_per_capita = report.total_functions / report.total_modules

    # Output/Input ratio
    total = report.productive_functions + report.consumption_functions
    if total > 0:
        report.output_input_ratio = report.productive_functions / total

    # Score: balanced economy with good output ratio
    ratio_score = min(100, report.output_input_ratio * 100 * 1.5)
    capita_score = min(100, report.gdp_per_capita * 15) if report.gdp_per_capita > 0 else 0
    volume_score = min(100, report.total_functions * 2) if report.total_functions > 0 else 0
    report.score = min(100, (ratio_score * 0.4 + capita_score * 0.3 + volume_score * 0.3))

    return report


# ── E002: Labor Market Analyzer ──────────────────────────────────────

def analyze_labor_market(modules: List[ModuleInfo]) -> LaborReport:
    """Analyze the labor market: functions as workers, calls as employment.

    Identifies overworked functions (called too many times), unemployed
    functions (never called), and computes Gini coefficient for workload.
    """
    report = LaborReport()

    # Build call counts across all modules
    all_functions: Dict[str, FunctionInfo] = {}
    call_counts: Dict[str, int] = defaultdict(int)

    for m in modules:
        for f in m.functions:
            all_functions[f"{m.name}.{f.name}"] = f
            all_functions[f.name] = f  # also index by short name

    for m in modules:
        for f in m.functions:
            for c in f.calls:
                call_counts[c] += 1

    report.total_workers = len(set(f.name for m in modules for f in m.functions))

    # Determine employed/unemployed
    func_names = set()
    for m in modules:
        for f in m.functions:
            func_names.add(f.name)

    employed_names = set()
    for fname in func_names:
        if call_counts.get(fname, 0) > 0:
            employed_names.add(fname)

    report.employed = len(employed_names)
    report.unemployed = report.total_workers - report.employed

    if report.total_workers > 0:
        report.unemployment_rate = report.unemployed / report.total_workers
        report.participation_rate = report.employed / report.total_workers
    else:
        report.unemployment_rate = 0.0
        report.participation_rate = 0.0

    # Overworked: called more than mean + 2*stddev
    if call_counts:
        counts = [call_counts.get(fn, 0) for fn in func_names]
        mean_calls = sum(counts) / len(counts) if counts else 0
        variance = sum((c - mean_calls) ** 2 for c in counts) / len(counts) if counts else 0
        stddev = math.sqrt(variance)
        threshold = mean_calls + 2 * stddev if stddev > 0 else mean_calls + 1

        for fname in func_names:
            c = call_counts.get(fname, 0)
            if c > threshold and c > 2:
                report.overworked.append({"name": fname, "call_count": c})

        # Underemployed: called exactly once
        for fname in func_names:
            c = call_counts.get(fname, 0)
            if c == 0:
                report.underemployed.append(fname)

    # Gini coefficient for workload inequality
    counts = sorted(call_counts.get(fn, 0) for fn in func_names)
    n = len(counts)
    if n > 0 and sum(counts) > 0:
        numerator = sum((2 * (i + 1) - n - 1) * counts[i] for i in range(n))
        denominator = n * sum(counts)
        report.gini_coefficient = numerator / denominator if denominator else 0.0
    else:
        report.gini_coefficient = 0.0

    # Score: low unemployment, low inequality
    unemp_score = max(0, 100 - report.unemployment_rate * 200)
    gini_score = max(0, 100 - report.gini_coefficient * 100)
    report.score = unemp_score * 0.6 + gini_score * 0.4

    return report


# ── E003: Trade Balance Analyzer ─────────────────────────────────────

def analyze_trade(modules: List[ModuleInfo]) -> TradeReport:
    """Analyze inter-module trade: imports as trade flows.

    Exports = functions defined that other modules call.
    Imports = modules imported.  Balance = exports - imports.
    """
    report = TradeReport()

    # Build export counts: how many other modules import this module
    module_names = {m.name for m in modules}
    export_counts: Dict[str, int] = defaultdict(int)
    import_counts: Dict[str, int] = defaultdict(int)

    for m in modules:
        for imp in m.imports:
            if imp in module_names:
                export_counts[imp] += 1
                import_counts[m.name] += 1
                report.total_trades += 1

    for m in modules:
        exports = export_counts.get(m.name, 0)
        imports = import_counts.get(m.name, 0)
        balance = exports - imports

        entry = {
            "module": m.name,
            "exports": exports,
            "imports": imports,
            "balance": balance,
            "functions_defined": len(m.functions),
        }
        report.balances.append(entry)

        if balance > 0:
            report.surplus_modules.append(entry)
        elif balance < 0:
            report.deficit_modules.append(entry)

        if exports == 0 and imports == 0:
            report.autarkic_modules.append(m.name)

    # Score: balanced trade, not too many autarkic modules
    if modules:
        autarky_ratio = len(report.autarkic_modules) / len(modules)
        # Some autarky is fine (standalone files); penalize if >70%
        autarky_score = max(0, 100 - max(0, autarky_ratio - 0.3) * 200)
        # Trade volume score
        trade_score = min(100, report.total_trades * 10) if report.total_trades > 0 else 30
        report.score = autarky_score * 0.5 + trade_score * 0.5
    else:
        report.score = 0.0

    return report


# ── E004: Inflation Tracker ──────────────────────────────────────────

def track_inflation(modules: List[ModuleInfo]) -> InflationReport:
    """Track complexity inflation: code bloat signals across the codebase.

    Measures function length, parameter count, nesting depth, and import
    count inflation, composing into a Code Price Index (CPI).
    """
    report = InflationReport()

    all_funcs = [f for m in modules for f in m.functions]
    if not all_funcs:
        report.score = 100.0  # no functions = no inflation
        return report

    # Function length inflation (ideal: 5-20 lines)
    avg_length = sum(f.line_count for f in all_funcs) / len(all_funcs)
    # 10 lines = ideal (index 0), 50+ = very inflated (index 100)
    report.function_length_index = min(100, max(0, (avg_length - 10) * 2.5))

    # Parameter inflation (ideal: 0-3 params)
    avg_params = sum(f.param_count for f in all_funcs) / len(all_funcs)
    report.parameter_index = min(100, max(0, (avg_params - 2) * 30))

    # Nesting depth inflation (ideal: 1-2 levels)
    avg_nesting = sum(f.max_nesting for f in all_funcs) / len(all_funcs)
    report.nesting_index = min(100, max(0, (avg_nesting - 4) * 10))

    # Import inflation (ideal: 0-5 imports per module)
    if modules:
        avg_imports = sum(len(m.imports) for m in modules) / len(modules)
        report.import_index = min(100, max(0, (avg_imports - 3) * 15))

    # Composite CPI (0 = no inflation, 100 = hyperinflation)
    report.cpi = (
        report.function_length_index * 0.35
        + report.parameter_index * 0.2
        + report.nesting_index * 0.25
        + report.import_index * 0.2
    )

    # Score: inverse of inflation (low inflation = high score)
    report.score = max(0, 100 - report.cpi)

    return report


# ── E005: Supply Chain Analyzer ──────────────────────────────────────

def analyze_supply_chain(modules: List[ModuleInfo]) -> SupplyChainReport:
    """Analyze variable supply chains: definitions → usage flows.

    Identifies bottleneck variables (defined once, used everywhere),
    single-source risks, and chain depth.
    """
    report = SupplyChainReport()

    # Build variable definition and usage maps
    var_defs: Dict[str, List[str]] = defaultdict(list)  # var -> [defining modules]
    var_uses: Dict[str, List[str]] = defaultdict(list)  # var -> [using modules]

    for m in modules:
        for v in m.variables_defined:
            var_defs[v].append(m.name)
        for f in m.functions:
            for v in f.variables_written:
                if v not in var_defs:
                    var_defs[v] = []
                if m.name not in var_defs[v]:
                    var_defs[v].append(m.name)
            for v in f.variables_read:
                var_uses[v].append(m.name)

    all_vars = set(list(var_defs.keys()) + list(var_uses.keys()))
    report.total_variables = len(all_vars)

    # Bottlenecks: defined in 1 module, used by 3+ modules
    for v in all_vars:
        defs = var_defs.get(v, [])
        uses = var_uses.get(v, [])
        unique_users = set(uses)
        if len(defs) == 1 and len(unique_users) >= 3:
            report.bottlenecks.append({
                "variable": v,
                "source": defs[0],
                "consumers": len(unique_users),
            })

    # Single-source risks: important variables with only one definition
    for v in all_vars:
        defs = var_defs.get(v, [])
        uses = var_uses.get(v, [])
        if len(defs) == 1 and len(uses) >= 2:
            report.single_source_risks.append({
                "variable": v,
                "source": defs[0],
                "dependents": len(uses),
            })

    # Chain depth: approximate by counting how many functions read variables
    # that were written by other functions
    depths: List[int] = []
    for m in modules:
        for f in m.functions:
            chain = 0
            for v in f.variables_read:
                if v in var_defs and var_defs[v]:
                    chain += 1
            depths.append(chain)

    report.max_chain_depth = max(depths) if depths else 0
    report.avg_chain_depth = sum(depths) / len(depths) if depths else 0.0

    # Score: few bottlenecks, low single-source risk
    if report.total_variables > 0:
        bottleneck_ratio = len(report.bottlenecks) / max(1, report.total_variables)
        risk_ratio = len(report.single_source_risks) / max(1, report.total_variables)
        report.score = max(0, 100 - bottleneck_ratio * 200 - risk_ratio * 100)
    else:
        report.score = 50.0  # neutral

    return report


# ── E006: Market Efficiency Scorer ───────────────────────────────────

def score_efficiency(modules: List[ModuleInfo]) -> EfficiencyReport:
    """Score market efficiency: dead code, unused imports, duplicates.

    Dead code = functions never called from anywhere.
    Unused imports = imports whose names aren't referenced.
    Duplicates = functions with identical names across modules.
    """
    report = EfficiencyReport()

    # Build call graph
    all_func_names: Set[str] = set()
    called_names: Set[str] = set()

    for m in modules:
        for f in m.functions:
            all_func_names.add(f.name)
            for c in f.calls:
                called_names.add(c)

    # Dead code: defined but never called
    dead = all_func_names - called_names
    report.dead_code_count = len(dead)

    # Unused imports: imported module not referenced in any function call
    module_names = {m.name for m in modules}
    for m in modules:
        all_idents = set()
        for f in m.functions:
            all_idents.update(f.calls)
            all_idents.update(f.variables_read)
        for imp in m.imports:
            # Simple heuristic: if import name not in any identifier
            if imp not in all_idents:
                report.unused_import_count += 1

    # Duplicate function names across modules
    func_modules: Dict[str, List[str]] = defaultdict(list)
    for m in modules:
        for f in m.functions:
            func_modules[f.name].append(m.name)

    for fname, mods in func_modules.items():
        if len(mods) > 1:
            report.duplicate_indicators += 1

    report.total_waste = (
        report.dead_code_count
        + report.unused_import_count
        + report.duplicate_indicators
    )

    total_assets = len(all_func_names) + sum(len(m.imports) for m in modules)
    if total_assets > 0:
        report.efficiency_ratio = max(0, 1.0 - report.total_waste / total_assets)
    else:
        report.efficiency_ratio = 1.0

    report.score = report.efficiency_ratio * 100

    return report


# ── E007: Insight Generator ──────────────────────────────────────────

def generate_insights(
    gdp: GDPReport,
    labor: LaborReport,
    trade: TradeReport,
    inflation: InflationReport,
    supply_chain: SupplyChainReport,
    efficiency: EfficiencyReport,
    modules: List[ModuleInfo],
) -> List[Dict[str, Any]]:
    """Generate autonomous policy recommendations based on all engines.

    Produces stimulus packages, austerity measures, trade agreements,
    labor reform, and supply chain hardening recommendations.
    """
    insights: List[Dict[str, Any]] = []

    # GDP insights
    if gdp.output_input_ratio < 0.3:
        insights.append({
            "type": "warning",
            "engine": "E001",
            "title": "Low Productive Output",
            "description": (
                f"Only {gdp.output_input_ratio:.0%} of functions produce return values. "
                "Consider refactoring side-effect-heavy functions into pure, "
                "composable units for better code reuse."
            ),
            "policy": "Stimulus Package",
        })

    if gdp.gdp_per_capita < 2.0 and gdp.total_modules > 1:
        insights.append({
            "type": "recommendation",
            "engine": "E001",
            "title": "Low GDP Per Capita",
            "description": (
                f"Average {gdp.gdp_per_capita:.1f} functions per module — "
                "modules may be too granular.  Consider consolidating "
                "related modules to boost per-module productivity."
            ),
            "policy": "Economic Consolidation",
        })

    if gdp.score >= 80:
        insights.append({
            "type": "positive",
            "engine": "E001",
            "title": "Strong Productive Economy",
            "description": (
                f"GDP score {gdp.score:.0f}/100 — the codebase has healthy "
                "productive output with good function density."
            ),
            "policy": "Maintain Course",
        })

    # Labor insights
    if labor.unemployment_rate > 0.3:
        insights.append({
            "type": "critical",
            "engine": "E002",
            "title": "High Unemployment",
            "description": (
                f"{labor.unemployment_rate:.0%} of functions are never called. "
                f"{labor.unemployed} unemployed workers represent dead weight. "
                "Remove or integrate these functions."
            ),
            "policy": "Labor Reform",
        })

    if labor.gini_coefficient > 0.6:
        insights.append({
            "type": "warning",
            "engine": "E002",
            "title": "Severe Workload Inequality",
            "description": (
                f"Gini coefficient {labor.gini_coefficient:.2f} — a few functions "
                "handle most of the work while others sit idle.  Redistribute "
                "responsibilities for better maintainability."
            ),
            "policy": "Wealth Redistribution",
        })

    if labor.overworked:
        top = sorted(labor.overworked, key=lambda x: x["call_count"], reverse=True)[:3]
        names = ", ".join(f"{o['name']} ({o['call_count']} calls)" for o in top)
        insights.append({
            "type": "warning",
            "engine": "E002",
            "title": "Overworked Functions Detected",
            "description": (
                f"These functions are called excessively: {names}. "
                "Consider caching results or splitting responsibilities."
            ),
            "policy": "Worker Protection",
        })

    # Trade insights
    if trade.autarkic_modules and len(trade.autarkic_modules) > len(modules) * 0.7:
        insights.append({
            "type": "warning",
            "engine": "E003",
            "title": "Excessive Economic Isolation",
            "description": (
                f"{len(trade.autarkic_modules)} of {len(modules)} modules have "
                "zero trade (no imports or exports). This suggests missed "
                "opportunities for code reuse."
            ),
            "policy": "Trade Agreement",
        })

    if trade.deficit_modules:
        worst = sorted(trade.deficit_modules, key=lambda x: x["balance"])[:2]
        names = ", ".join(f"{w['module']} (balance: {w['balance']:+d})" for w in worst)
        insights.append({
            "type": "info",
            "engine": "E003",
            "title": "Trade Deficit Modules",
            "description": (
                f"Modules with import deficit: {names}. "
                "These consume more than they produce — consider "
                "extracting reusable utilities."
            ),
            "policy": "Export Incentive",
        })

    # Inflation insights
    if inflation.cpi > 60:
        insights.append({
            "type": "critical",
            "engine": "E004",
            "title": "Hyperinflation Warning",
            "description": (
                f"Code Price Index at {inflation.cpi:.0f}/100 — complexity is "
                "spiraling. Function lengths, parameter counts, and nesting "
                "depth are all above healthy thresholds."
            ),
            "policy": "Austerity Measures",
        })
    elif inflation.cpi > 30:
        insights.append({
            "type": "warning",
            "engine": "E004",
            "title": "Rising Inflation",
            "description": (
                f"CPI at {inflation.cpi:.0f}/100 — moderate complexity creep. "
                "Watch function lengths and nesting depth."
            ),
            "policy": "Inflation Monitoring",
        })
    else:
        insights.append({
            "type": "positive",
            "engine": "E004",
            "title": "Stable Prices",
            "description": (
                f"CPI at {inflation.cpi:.0f}/100 — complexity is well-controlled. "
                "Functions are lean and parameters are minimal."
            ),
            "policy": "Price Stability",
        })

    # Supply chain insights
    if supply_chain.bottlenecks:
        top = supply_chain.bottlenecks[:3]
        names = ", ".join(f"{b['variable']} ({b['consumers']} consumers)" for b in top)
        insights.append({
            "type": "warning",
            "engine": "E005",
            "title": "Supply Chain Bottlenecks",
            "description": (
                f"Critical bottleneck variables: {names}. "
                "If these definitions break, many modules are affected. "
                "Consider redundant sources or dependency injection."
            ),
            "policy": "Supply Chain Hardening",
        })

    # Efficiency insights
    if efficiency.dead_code_count > 5:
        insights.append({
            "type": "warning",
            "engine": "E006",
            "title": "Market Waste: Dead Code",
            "description": (
                f"{efficiency.dead_code_count} unused functions detected — "
                "stranded assets consuming maintenance attention. "
                "Remove or archive them."
            ),
            "policy": "Waste Reduction",
        })

    if efficiency.score >= 85:
        insights.append({
            "type": "positive",
            "engine": "E006",
            "title": "Efficient Market",
            "description": (
                f"Efficiency score {efficiency.score:.0f}/100 — "
                "minimal waste, good resource utilization."
            ),
            "policy": "Market Confidence",
        })

    # Cross-engine insights
    if labor.unemployment_rate > 0.2 and efficiency.dead_code_count > 3:
        insights.append({
            "type": "recommendation",
            "engine": "CROSS",
            "title": "Structural Unemployment + Market Waste",
            "description": (
                "Both high unemployment and dead code suggest the codebase "
                "has accumulated unused infrastructure. A targeted cleanup "
                "sprint would improve both labor metrics and efficiency."
            ),
            "policy": "Economic Restructuring",
        })

    if inflation.cpi > 40 and labor.overworked:
        insights.append({
            "type": "recommendation",
            "engine": "CROSS",
            "title": "Stagflation Risk",
            "description": (
                "Rising complexity (inflation) combined with overworked functions "
                "signals stagflation — the codebase grows heavier while key "
                "workers burn out.  Prioritize decomposition and delegation."
            ),
            "policy": "Anti-Stagflation Program",
        })

    return insights


# ── Composite Analysis ───────────────────────────────────────────────

def compute_health_score(
    gdp: GDPReport,
    labor: LaborReport,
    trade: TradeReport,
    inflation: InflationReport,
    supply_chain: SupplyChainReport,
    efficiency: EfficiencyReport,
) -> Tuple[float, str, Dict[str, float]]:
    """Compute weighted composite economy health score.

    Returns (score, tier, sub_scores).
    """
    sub_scores = {
        "gdp": gdp.score,
        "labor_market": labor.score,
        "trade_balance": trade.score,
        "inflation_control": inflation.score,
        "supply_chain": supply_chain.score,
        "market_efficiency": efficiency.score,
    }

    score = (
        gdp.score * 0.15
        + labor.score * 0.20
        + trade.score * 0.15
        + inflation.score * 0.20
        + supply_chain.score * 0.15
        + efficiency.score * 0.15
    )
    score = min(100, max(0, score))

    if score >= 80:
        tier = "Thriving"
    elif score >= 60:
        tier = "Stable"
    elif score >= 40:
        tier = "Stagnant"
    elif score >= 20:
        tier = "Recession"
    else:
        tier = "Depression"

    return score, tier, sub_scores


def analyze(path: str, recursive: bool = False) -> EconomyReport:
    """Run all 7 analysis engines on the given path."""
    files = _find_srv_files(path, recursive=recursive)
    modules = [parse_module(f) for f in files]

    gdp = calculate_gdp(modules)
    labor = analyze_labor_market(modules)
    trade = analyze_trade(modules)
    inflation = track_inflation(modules)
    supply = analyze_supply_chain(modules)
    efficiency = score_efficiency(modules)

    health, tier, sub_scores = compute_health_score(
        gdp, labor, trade, inflation, supply, efficiency
    )

    insights = generate_insights(
        gdp, labor, trade, inflation, supply, efficiency, modules
    )

    # Module summaries
    mod_summaries = []
    for m in modules:
        mod_summaries.append({
            "name": m.name,
            "functions": len(m.functions),
            "lines": m.lines,
            "code_lines": m.code_lines,
            "imports": len(m.imports),
            "variables": len(m.variables_defined),
        })

    report = EconomyReport(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        path=path,
        total_modules=len(modules),
        total_functions=sum(len(m.functions) for m in modules),
        total_lines=sum(m.lines for m in modules),
        total_code_lines=sum(m.code_lines for m in modules),
        gdp=asdict(gdp),
        labor=_labor_to_dict(labor),
        trade=_trade_to_dict(trade),
        inflation=asdict(inflation),
        supply_chain=_supply_to_dict(supply),
        efficiency=asdict(efficiency),
        health_score=health,
        health_tier=tier,
        sub_scores=sub_scores,
        insights=insights,
        modules=mod_summaries,
    )

    return report


def _labor_to_dict(labor: LaborReport) -> Dict[str, Any]:
    """Convert LaborReport to serializable dict (sets → lists)."""
    d = asdict(labor)
    d["underemployed"] = list(labor.underemployed)
    return d


def _trade_to_dict(trade: TradeReport) -> Dict[str, Any]:
    """Convert TradeReport to serializable dict."""
    return asdict(trade)


def _supply_to_dict(supply: SupplyChainReport) -> Dict[str, Any]:
    """Convert SupplyChainReport to serializable dict."""
    return asdict(supply)


# ── Output Formatters ────────────────────────────────────────────────

def format_text(report: EconomyReport) -> str:
    """Format economy report as colored terminal text."""
    lines: List[str] = []

    lines.append("")
    lines.append(_C.bold(_C.cyan("═══ sauraveconomy — Code Economy Analyzer ═══")))
    lines.append(f"  Path: {report.path}")
    lines.append(f"  {report.total_modules} modules, {report.total_functions} functions, "
                 f"{report.total_code_lines} code lines")
    lines.append(f"  {report.timestamp}")
    lines.append("")

    # E001: GDP
    gdp = report.gdp
    lines.append(_C.bold(_C.cyan("E001 — GDP (Gross Domestic Product)")))
    lines.append(f"  Total Functions:      {gdp['total_functions']}")
    lines.append(f"  Total Code Lines:     {gdp['total_code_lines']}")
    lines.append(f"  GDP Per Capita:       {gdp['gdp_per_capita']:.1f} functions/module")
    lines.append(f"  Productive (return):  {gdp['productive_functions']}")
    lines.append(f"  Consumption (void):   {gdp['consumption_functions']}")
    lines.append(f"  Output/Input Ratio:   {gdp['output_input_ratio']:.2f}")
    _add_score_line(lines, "GDP Score", gdp['score'])
    lines.append("")

    # E002: Labor Market
    lab = report.labor
    lines.append(_C.bold(_C.cyan("E002 — Labor Market")))
    lines.append(f"  Total Workers:        {lab['total_workers']}")
    lines.append(f"  Employed:             {lab['employed']}")
    lines.append(f"  Unemployed:           {lab['unemployed']}")
    lines.append(f"  Unemployment Rate:    {lab['unemployment_rate']:.1%}")
    lines.append(f"  Participation Rate:   {lab['participation_rate']:.1%}")
    lines.append(f"  Gini Coefficient:     {lab['gini_coefficient']:.3f}")
    if lab['overworked']:
        lines.append(f"  Overworked ({len(lab['overworked'])}):")
        for o in lab['overworked'][:5]:
            lines.append(f"    {o['name']:30s} {o['call_count']} calls")
    _add_score_line(lines, "Labor Score", lab['score'])
    lines.append("")

    # E003: Trade Balance
    trd = report.trade
    lines.append(_C.bold(_C.cyan("E003 — Trade Balance")))
    lines.append(f"  Total Trades:         {trd['total_trades']}")
    lines.append(f"  Surplus Modules:      {len(trd['surplus_modules'])}")
    lines.append(f"  Deficit Modules:      {len(trd['deficit_modules'])}")
    lines.append(f"  Autarkic Modules:     {len(trd['autarkic_modules'])}")
    if trd['balances']:
        lines.append("  Top Balances:")
        sorted_bal = sorted(trd['balances'], key=lambda x: abs(x['balance']), reverse=True)
        for b in sorted_bal[:5]:
            sign = "+" if b['balance'] >= 0 else ""
            lines.append(f"    {b['module']:30s} {sign}{b['balance']} "
                         f"(exp={b['exports']}, imp={b['imports']})")
    _add_score_line(lines, "Trade Score", trd['score'])
    lines.append("")

    # E004: Inflation
    inf = report.inflation
    lines.append(_C.bold(_C.cyan("E004 — Inflation Tracker")))
    lines.append(f"  Function Length Index: {inf['function_length_index']:.1f}")
    lines.append(f"  Parameter Index:      {inf['parameter_index']:.1f}")
    lines.append(f"  Nesting Index:        {inf['nesting_index']:.1f}")
    lines.append(f"  Import Index:         {inf['import_index']:.1f}")
    cpi_val = inf['cpi']
    cpi_color = _C.green if cpi_val < 30 else (_C.yellow if cpi_val < 60 else _C.red)
    lines.append(f"  Code Price Index:     {cpi_color(f'{cpi_val:.1f}/100')}")
    _add_score_line(lines, "Inflation Score", inf['score'])
    lines.append("")

    # E005: Supply Chain
    sc = report.supply_chain
    lines.append(_C.bold(_C.cyan("E005 — Supply Chain")))
    lines.append(f"  Total Variables:      {sc['total_variables']}")
    lines.append(f"  Bottlenecks:          {len(sc['bottlenecks'])}")
    lines.append(f"  Single-Source Risks:  {len(sc['single_source_risks'])}")
    lines.append(f"  Max Chain Depth:      {sc['max_chain_depth']}")
    lines.append(f"  Avg Chain Depth:      {sc['avg_chain_depth']:.1f}")
    _add_score_line(lines, "Supply Chain Score", sc['score'])
    lines.append("")

    # E006: Market Efficiency
    eff = report.efficiency
    lines.append(_C.bold(_C.cyan("E006 — Market Efficiency")))
    lines.append(f"  Dead Code:            {eff['dead_code_count']}")
    lines.append(f"  Unused Imports:       {eff['unused_import_count']}")
    lines.append(f"  Duplicate Indicators: {eff['duplicate_indicators']}")
    lines.append(f"  Efficiency Ratio:     {eff['efficiency_ratio']:.2f}")
    _add_score_line(lines, "Efficiency Score", eff['score'])
    lines.append("")

    # Health Score
    lines.append(_C.bold(_C.cyan("═══ Economy Health Score ═══")))
    score = report.health_score
    if score >= 80:
        gauge = _C.green(f"█████████ {score:.0f}/100 — {report.health_tier}")
    elif score >= 60:
        gauge = _C.yellow(f"██████░░░ {score:.0f}/100 — {report.health_tier}")
    elif score >= 40:
        gauge = _C.yellow(f"████░░░░░ {score:.0f}/100 — {report.health_tier}")
    else:
        gauge = _C.red(f"██░░░░░░░ {score:.0f}/100 — {report.health_tier}")
    lines.append(f"  {gauge}")
    lines.append("")

    for k, v in report.sub_scores.items():
        label = k.replace("_", " ").title()
        sc_color = _C.green if v >= 70 else (_C.yellow if v >= 40 else _C.red)
        lines.append(f"    {label:25s} {sc_color(f'{v:.0f}')}")
    lines.append("")

    # E007: Insights
    lines.append(_C.bold(_C.cyan("E007 — Policy Recommendations")))
    for ins in report.insights:
        tp = ins["type"]
        if tp == "critical":
            icon = _C.red("🔴")
        elif tp == "warning":
            icon = _C.yellow("🟡")
        elif tp == "positive":
            icon = _C.green("🟢")
        elif tp == "recommendation":
            icon = _C.cyan("💡")
        else:
            icon = "ℹ️"
        policy = ins.get("policy", "")
        lines.append(f"  {icon} [{ins['engine']}] {_C.bold(ins['title'])} — {policy}")
        lines.append(f"     {ins['description']}")
    lines.append("")

    return "\n".join(lines)


def _add_score_line(lines: List[str], label: str, score: float) -> None:
    """Add a colored score line to the output."""
    if score >= 70:
        color = _C.green
    elif score >= 40:
        color = _C.yellow
    else:
        color = _C.red
    lines.append(f"  {label:25s} {color(f'{score:.0f}/100')}")


def format_json(report: EconomyReport) -> str:
    """Format report as JSON."""
    return json.dumps(asdict(report), indent=2, default=str)


def generate_html(report: EconomyReport) -> str:
    """Generate self-contained interactive HTML dashboard."""
    data_json = json.dumps(asdict(report), indent=2, default=str)
    score = report.health_score
    tier = report.health_tier
    sc = "#d4af37" if score >= 80 else ("#c0c0c0" if score >= 60 else ("#cd7f32" if score >= 40 else "#e74c3c"))

    tier_emoji = {
        "Thriving": "🏆", "Stable": "📊", "Stagnant": "⚠️",
        "Recession": "📉", "Depression": "🆘",
    }

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>sauraveconomy — Code Economy Report</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #0a0e1a; color: #c9d1d9; padding: 20px; }}
  .header {{ text-align: center; padding: 30px 0; }}
  .header h1 {{ font-size: 2em; color: #d4af37; }}
  .header .subtitle {{ color: #8b949e; margin-top: 8px; }}
  .tabs {{ display: flex; gap: 4px; margin: 20px 0 0; flex-wrap: wrap; }}
  .tab {{ padding: 10px 18px; background: #161b22; border: 1px solid #30363d;
          border-bottom: none; border-radius: 8px 8px 0 0; cursor: pointer;
          color: #8b949e; font-size: 0.9em; }}
  .tab.active {{ background: #1c2333; color: #d4af37; border-color: #d4af37; }}
  .tab-content {{ display: none; background: #1c2333; border: 1px solid #30363d;
                  border-radius: 0 8px 8px 8px; padding: 20px; margin-bottom: 20px; }}
  .tab-content.active {{ display: block; }}
  .score-gauge {{ text-align: center; margin: 30px 0; }}
  .score-circle {{ width: 160px; height: 160px; border-radius: 50%; margin: 0 auto;
                   display: flex; align-items: center; justify-content: center;
                   font-size: 2.5em; font-weight: bold; color: white;
                   background: conic-gradient({sc} {score * 3.6}deg, #21262d {score * 3.6}deg); }}
  .score-inner {{ width: 130px; height: 130px; border-radius: 50%; background: #0a0e1a;
                  display: flex; align-items: center; justify-content: center;
                  flex-direction: column; }}
  .score-inner .value {{ font-size: 1em; }}
  .score-inner .tier {{ font-size: 0.4em; color: {sc}; margin-top: 4px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 15px; margin: 15px 0; }}
  .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }}
  .card h3 {{ color: #d4af37; font-size: 1em; margin-bottom: 10px; }}
  .metric {{ display: flex; justify-content: space-between; padding: 6px 0;
             border-bottom: 1px solid #21262d; font-size: 0.9em; }}
  .metric .label {{ color: #8b949e; }}
  .metric .value {{ font-weight: 600; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.85em; }}
  th {{ text-align: left; color: #8b949e; padding: 8px 6px; border-bottom: 1px solid #30363d; }}
  td {{ padding: 8px 6px; border-bottom: 1px solid #21262d; }}
  .bar {{ height: 8px; border-radius: 4px; background: #21262d; margin-top: 4px; }}
  .bar-fill {{ height: 100%; border-radius: 4px; }}
  .sub-scores {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }}
  .sub-score {{ text-align: center; padding: 12px; background: #161b22; border-radius: 8px;
                border: 1px solid #30363d; }}
  .sub-score .val {{ font-size: 1.6em; font-weight: bold; }}
  .sub-score .lbl {{ color: #8b949e; font-size: 0.8em; margin-top: 4px; }}
  .insight {{ padding: 12px; margin: 8px 0; border-radius: 6px; border-left: 4px solid; }}
  .insight-critical {{ border-color: #da3633; background: rgba(218,54,51,0.1); }}
  .insight-warning {{ border-color: #d29922; background: rgba(210,153,34,0.1); }}
  .insight-positive {{ border-color: #238636; background: rgba(35,134,54,0.1); }}
  .insight-recommendation {{ border-color: #388bfd; background: rgba(56,139,253,0.1); }}
  .insight-info {{ border-color: #388bfd; background: rgba(56,139,253,0.1); }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px;
            font-size: 0.75em; font-weight: 600; }}
  .badge-surplus {{ background: #238636; color: white; }}
  .badge-deficit {{ background: #da3633; color: white; }}
  .badge-autarky {{ background: #8b949e; color: white; }}
  .cpi-gauge {{ width: 100%; height: 24px; background: linear-gradient(to right, #238636, #f39c12, #da3633);
                border-radius: 12px; position: relative; margin: 10px 0; }}
  .cpi-needle {{ position: absolute; top: -4px; width: 4px; height: 32px; background: white;
                 border-radius: 2px; }}
</style>
</head>
<body>

<div class="header">
  <h1>💰 sauraveconomy</h1>
  <div class="subtitle">Code Economy Analysis — {report.total_modules} modules, {report.total_functions} functions, {report.total_code_lines} code lines</div>
  <div class="subtitle">{report.timestamp}</div>
</div>

<div class="score-gauge">
  <div class="score-circle">
    <div class="score-inner">
      <div class="value">{score:.0f}</div>
      <div class="tier">{tier_emoji.get(tier, '')} {tier}</div>
    </div>
  </div>
  <div style="margin-top:10px;color:{sc};font-weight:bold;font-size:1.1em">Economy Health Score</div>
</div>

<div class="sub-scores">"""

    for k, v in report.sub_scores.items():
        vc = "#238636" if v >= 70 else ("#f39c12" if v >= 40 else "#da3633")
        label = k.replace("_", " ").title()
        html += f"""
  <div class="sub-score">
    <div class="val" style="color:{vc}">{v:.0f}</div>
    <div class="lbl">{label}</div>
    <div class="bar"><div class="bar-fill" style="width:{v}%;background:{vc}"></div></div>
  </div>"""

    html += """
</div>

<div class="tabs">
  <div class="tab active" onclick="showTab('overview')">Overview</div>
  <div class="tab" onclick="showTab('gdp')">GDP</div>
  <div class="tab" onclick="showTab('labor')">Labor</div>
  <div class="tab" onclick="showTab('trade')">Trade</div>
  <div class="tab" onclick="showTab('inflation')">Inflation</div>
  <div class="tab" onclick="showTab('supply')">Supply Chain</div>
  <div class="tab" onclick="showTab('insights')">Insights</div>
</div>
"""

    # Overview tab
    gdp = report.gdp
    lab = report.labor
    trd = report.trade
    inf = report.inflation
    sc_data = report.supply_chain
    eff = report.efficiency

    html += """<div id="tab-overview" class="tab-content active">
<div class="grid">"""

    # Module table
    html += """<div class="card" style="grid-column:1/-1"><h3>📋 Module Overview</h3>
<table><tr><th>Module</th><th>Functions</th><th>Lines</th><th>Code Lines</th><th>Imports</th><th>Variables</th></tr>"""
    for m in sorted(report.modules, key=lambda x: x["code_lines"], reverse=True)[:20]:
        html += f"<tr><td>{m['name']}</td><td>{m['functions']}</td><td>{m['lines']}</td>"
        html += f"<td>{m['code_lines']}</td><td>{m['imports']}</td><td>{m['variables']}</td></tr>"
    html += "</table></div>"
    html += "</div></div>\n"

    # GDP tab
    html += f"""<div id="tab-gdp" class="tab-content">
<div class="grid">
  <div class="card"><h3>📈 Production Metrics</h3>
    <div class="metric"><span class="label">Total Functions</span><span class="value">{gdp['total_functions']}</span></div>
    <div class="metric"><span class="label">Total Code Lines</span><span class="value">{gdp['total_code_lines']}</span></div>
    <div class="metric"><span class="label">GDP Per Capita</span><span class="value">{gdp['gdp_per_capita']:.1f} fn/module</span></div>
    <div class="metric"><span class="label">Productive (return)</span><span class="value">{gdp['productive_functions']}</span></div>
    <div class="metric"><span class="label">Consumption (void)</span><span class="value">{gdp['consumption_functions']}</span></div>
    <div class="metric"><span class="label">Output/Input Ratio</span><span class="value">{gdp['output_input_ratio']:.2f}</span></div>
  </div>
  <div class="card"><h3>🎯 GDP Score</h3>
    <div style="text-align:center;font-size:3em;font-weight:bold;color:{'#238636' if gdp['score'] >= 70 else '#f39c12' if gdp['score'] >= 40 else '#da3633'}">{gdp['score']:.0f}</div>
    <div class="bar"><div class="bar-fill" style="width:{gdp['score']}%;background:{'#238636' if gdp['score'] >= 70 else '#f39c12' if gdp['score'] >= 40 else '#da3633'}"></div></div>
  </div>
</div></div>\n"""

    # Labor tab
    html += f"""<div id="tab-labor" class="tab-content">
<div class="grid">
  <div class="card"><h3>👷 Employment Metrics</h3>
    <div class="metric"><span class="label">Total Workers</span><span class="value">{lab['total_workers']}</span></div>
    <div class="metric"><span class="label">Employed</span><span class="value" style="color:#238636">{lab['employed']}</span></div>
    <div class="metric"><span class="label">Unemployed</span><span class="value" style="color:#da3633">{lab['unemployed']}</span></div>
    <div class="metric"><span class="label">Unemployment Rate</span><span class="value">{lab['unemployment_rate']:.1%}</span></div>
    <div class="metric"><span class="label">Participation Rate</span><span class="value">{lab['participation_rate']:.1%}</span></div>
    <div class="metric"><span class="label">Gini Coefficient</span><span class="value">{lab['gini_coefficient']:.3f}</span></div>
  </div>
  <div class="card"><h3>🔥 Overworked Functions</h3>"""

    if lab['overworked']:
        html += "<table><tr><th>Function</th><th>Calls</th></tr>"
        for o in sorted(lab['overworked'], key=lambda x: x['call_count'], reverse=True)[:10]:
            html += f"<tr><td>{o['name']}</td><td>{o['call_count']}</td></tr>"
        html += "</table>"
    else:
        html += '<div style="color:#238636;padding:20px;text-align:center">✓ No overworked functions</div>'

    html += """</div></div></div>\n"""

    # Trade tab
    html += """<div id="tab-trade" class="tab-content">
<div class="grid">
  <div class="card" style="grid-column:1/-1"><h3>🚢 Trade Balances</h3>
<table><tr><th>Module</th><th>Exports</th><th>Imports</th><th>Balance</th><th>Status</th></tr>"""

    for b in sorted(trd['balances'], key=lambda x: abs(x['balance']), reverse=True)[:20]:
        if b['balance'] > 0:
            badge = '<span class="badge badge-surplus">SURPLUS</span>'
        elif b['balance'] < 0:
            badge = '<span class="badge badge-deficit">DEFICIT</span>'
        else:
            if b['exports'] == 0 and b['imports'] == 0:
                badge = '<span class="badge badge-autarky">AUTARKY</span>'
            else:
                badge = '<span class="badge" style="background:#d4af37;color:black">BALANCED</span>'
        bc = "#238636" if b['balance'] > 0 else ("#da3633" if b['balance'] < 0 else "#8b949e")
        html += f"<tr><td>{b['module']}</td><td>{b['exports']}</td><td>{b['imports']}</td>"
        html += f'<td style="color:{bc}">{b["balance"]:+d}</td><td>{badge}</td></tr>'

    html += "</table></div></div></div>\n"

    # Inflation tab
    cpi_pos = min(96, max(2, inf['cpi']))
    html += f"""<div id="tab-inflation" class="tab-content">
<div class="grid">
  <div class="card" style="grid-column:1/-1"><h3>📊 Code Price Index (CPI)</h3>
    <div class="cpi-gauge"><div class="cpi-needle" style="left:{cpi_pos}%"></div></div>
    <div style="display:flex;justify-content:space-between;color:#8b949e;font-size:0.8em">
      <span>0 — Deflation</span><span>50 — Moderate</span><span>100 — Hyperinflation</span>
    </div>
    <div style="text-align:center;margin-top:15px;font-size:2em;font-weight:bold;color:{'#238636' if inf['cpi'] < 30 else '#f39c12' if inf['cpi'] < 60 else '#da3633'}">{inf['cpi']:.1f}</div>
  </div>
  <div class="card"><h3>Function Length Index</h3>
    <div style="font-size:2em;font-weight:bold;text-align:center">{inf['function_length_index']:.1f}</div>
    <div class="bar"><div class="bar-fill" style="width:{min(100, inf['function_length_index'])}%;background:#f39c12"></div></div>
  </div>
  <div class="card"><h3>Parameter Index</h3>
    <div style="font-size:2em;font-weight:bold;text-align:center">{inf['parameter_index']:.1f}</div>
    <div class="bar"><div class="bar-fill" style="width:{min(100, inf['parameter_index'])}%;background:#f39c12"></div></div>
  </div>
  <div class="card"><h3>Nesting Index</h3>
    <div style="font-size:2em;font-weight:bold;text-align:center">{inf['nesting_index']:.1f}</div>
    <div class="bar"><div class="bar-fill" style="width:{min(100, inf['nesting_index'])}%;background:#f39c12"></div></div>
  </div>
  <div class="card"><h3>Import Index</h3>
    <div style="font-size:2em;font-weight:bold;text-align:center">{inf['import_index']:.1f}</div>
    <div class="bar"><div class="bar-fill" style="width:{min(100, inf['import_index'])}%;background:#f39c12"></div></div>
  </div>
</div></div>\n"""

    # Supply Chain tab
    html += f"""<div id="tab-supply" class="tab-content">
<div class="grid">
  <div class="card"><h3>📦 Supply Chain Metrics</h3>
    <div class="metric"><span class="label">Total Variables</span><span class="value">{sc_data['total_variables']}</span></div>
    <div class="metric"><span class="label">Bottlenecks</span><span class="value" style="color:#f39c12">{len(sc_data['bottlenecks'])}</span></div>
    <div class="metric"><span class="label">Single-Source Risks</span><span class="value" style="color:#da3633">{len(sc_data['single_source_risks'])}</span></div>
    <div class="metric"><span class="label">Max Chain Depth</span><span class="value">{sc_data['max_chain_depth']}</span></div>
    <div class="metric"><span class="label">Avg Chain Depth</span><span class="value">{sc_data['avg_chain_depth']:.1f}</span></div>
  </div>"""

    if sc_data['bottlenecks']:
        html += """<div class="card"><h3>🚧 Bottleneck Variables</h3>
<table><tr><th>Variable</th><th>Source</th><th>Consumers</th></tr>"""
        for b in sc_data['bottlenecks'][:10]:
            html += f"<tr><td>{b['variable']}</td><td>{b['source']}</td><td>{b['consumers']}</td></tr>"
        html += "</table></div>"

    html += "</div></div>\n"

    # Insights tab
    html += """<div id="tab-insights" class="tab-content">
<h3 style="color:#d4af37;margin-bottom:15px">🏛️ Policy Recommendations</h3>"""

    for ins in report.insights:
        itype = ins["type"]
        policy = ins.get("policy", "")
        html += f"""<div class="insight insight-{itype}">
  <strong>[{ins['engine']}] {ins['title']}</strong>
  <span class="badge" style="background:#30363d;color:#d4af37;margin-left:8px">{policy}</span>
  <div style="margin-top:6px;color:#c9d1d9">{ins['description']}</div>
</div>"""

    html += "</div>\n"

    # JavaScript for tabs
    html += f"""
<script>
const REPORT_DATA = {data_json};

function showTab(name) {{
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  event.target.classList.add('active');
}}
</script>
</body>
</html>"""

    return html


# ── CLI ──────────────────────────────────────────────────────────────

def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="sauraveconomy",
        description="Autonomous code economy analyzer for sauravcode projects",
    )
    parser.add_argument("path", nargs="?", default=".", help="Directory or file to analyze")
    parser.add_argument("--recursive", "-r", action="store_true", help="Recurse into subdirectories")
    parser.add_argument("--html", metavar="FILE", help="Generate interactive HTML dashboard")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--gdp", action="store_true", help="GDP summary only")
    parser.add_argument("--labor", action="store_true", help="Labor market only")
    parser.add_argument("--trade", action="store_true", help="Trade balance only")
    parser.add_argument("--inflation", action="store_true", help="Inflation metrics only")
    parser.add_argument("--supply-chain", action="store_true", help="Supply chain view")
    parser.add_argument("--version", action="version", version=f"sauraveconomy {__version__}")
    args = parser.parse_args()

    report = analyze(args.path, recursive=args.recursive)

    if args.json:
        print(format_json(report))
    else:
        print(format_text(report))

    if args.html:
        html = generate_html(report)
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\n  HTML dashboard saved to {args.html}")

    # Exit code based on health
    if report.health_score < 30:
        sys.exit(2)
    elif report.health_score < 60:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
