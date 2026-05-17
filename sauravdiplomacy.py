#!/usr/bin/env python3
"""sauravdiplomacy — Autonomous Code Diplomacy Engine for sauravcode.

Models inter-module (.srv file) relationships as diplomatic relations
between nation-states.  Each module is a sovereign nation; imports are
treaties; shared patterns are alliances; missing connections are
embargoes; naming collisions are conflicts.

Analysis Engines (7):
    D001  Sovereignty Analyzer     Module independence & self-sufficiency scoring
    D002  Alliance Detector        Mutual-dependency cluster detection (Jaccard)
    D003  Embargo Detector         Missing connections between related modules
    D004  Treaty Analyzer          Interface contract fairness & complexity
    D005  Conflict Detector        Naming collisions & competing implementations
    D006  Diplomatic Health Scorer Composite 0-100 score with 5 tiers
    D007  Insight Generator        Autonomous recommendations & diplomacy advice

Usage:
    python sauravdiplomacy.py                          # Analyze current directory
    python sauravdiplomacy.py path/to/project          # Analyze specific directory
    python sauravdiplomacy.py path --html report.html  # Interactive HTML dashboard
    python sauravdiplomacy.py path --json              # JSON output
    python sauravdiplomacy.py path --recursive         # Deep scan
    python sauravdiplomacy.py path --sovereignty       # Sovereignty rankings only
    python sauravdiplomacy.py path --alliances         # Alliance map only
    python sauravdiplomacy.py path --embargoes         # Embargo list only
    python sauravdiplomacy.py path --treaties          # Treaty analysis only
    python sauravdiplomacy.py path --conflicts         # Conflict report only
"""

import sys
import os
import re
import json
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
CALL_RE = re.compile(r"\b([a-zA-Z_]\w*)\s*\(")
PARAM_RE = re.compile(r"\(([^)]*)\)")
IDENT_RE = re.compile(r"\b([a-zA-Z_]\w*)\b")

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
    calls: Set[str] = field(default_factory=set)
    variables_written: Set[str] = field(default_factory=set)
    variables_read: Set[str] = field(default_factory=set)
    has_return: bool = False


@dataclass
class ModuleNation:
    """A module modeled as a nation-state."""
    name: str
    path: str
    lines: int = 0
    code_lines: int = 0
    functions: List[FunctionInfo] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    exports: Set[str] = field(default_factory=set)  # function names (public API)
    variables_defined: Set[str] = field(default_factory=set)
    all_calls: Set[str] = field(default_factory=set)
    sovereignty_score: float = 0.0
    sovereignty_tier: str = ""


@dataclass
class Alliance:
    """A group of modules with mutual dependencies."""
    members: List[str]
    strength: float = 0.0  # 0-1
    alliance_type: str = ""  # bilateral / multilateral
    shared_imports: int = 0
    shared_calls: int = 0


@dataclass
class Embargo:
    """Missing connection between related modules."""
    module_a: str
    module_b: str
    reason: str
    severity: float = 0.0  # 0-1
    shared_patterns: List[str] = field(default_factory=list)


@dataclass
class Treaty:
    """An interface contract between two modules."""
    exporter: str
    importer: str
    functions_used: List[str] = field(default_factory=list)
    complexity: float = 0.0  # 0-1
    is_one_sided: bool = False


@dataclass
class Conflict:
    """A conflict between modules."""
    modules: List[str]
    conflict_type: str = ""  # naming / implementation / resource
    severity: float = 0.0  # 0-1
    details: str = ""
    items: List[str] = field(default_factory=list)


@dataclass
class SovereigntyReport:
    """D001 results."""
    rankings: List[Dict[str, Any]] = field(default_factory=list)
    avg_sovereignty: float = 0.0
    most_independent: str = ""
    most_dependent: str = ""
    score: float = 0.0


@dataclass
class AllianceReport:
    """D002 results."""
    alliances: List[Dict[str, Any]] = field(default_factory=list)
    total_alliances: int = 0
    largest_alliance: int = 0
    avg_strength: float = 0.0
    score: float = 0.0


@dataclass
class EmbargoReport:
    """D003 results."""
    embargoes: List[Dict[str, Any]] = field(default_factory=list)
    total_embargoes: int = 0
    avg_severity: float = 0.0
    score: float = 0.0


@dataclass
class TreatyReport:
    """D004 results."""
    treaties: List[Dict[str, Any]] = field(default_factory=list)
    total_treaties: int = 0
    one_sided_count: int = 0
    avg_complexity: float = 0.0
    fairness_ratio: float = 0.0
    score: float = 0.0


@dataclass
class ConflictReport:
    """D005 results."""
    conflicts: List[Dict[str, Any]] = field(default_factory=list)
    total_conflicts: int = 0
    avg_severity: float = 0.0
    score: float = 0.0


@dataclass
class DiplomacyReport:
    """Full diplomacy analysis report."""
    timestamp: str = ""
    path: str = ""
    total_modules: int = 0
    total_functions: int = 0
    total_lines: int = 0
    sovereignty: Dict[str, Any] = field(default_factory=dict)
    alliances: Dict[str, Any] = field(default_factory=dict)
    embargoes: Dict[str, Any] = field(default_factory=dict)
    treaties: Dict[str, Any] = field(default_factory=dict)
    conflicts: Dict[str, Any] = field(default_factory=dict)
    health_score: float = 0.0
    health_tier: str = ""
    sub_scores: Dict[str, float] = field(default_factory=dict)
    insights: List[Dict[str, Any]] = field(default_factory=list)
    modules: List[Dict[str, Any]] = field(default_factory=list)


# ── Parsing ──────────────────────────────────────────────────────────


def parse_module(path: str) -> ModuleNation:
    """Parse a .srv file into a ModuleNation."""
    name = os.path.splitext(os.path.basename(path))[0]
    nation = ModuleNation(path=path, name=name)

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            raw_lines = f.readlines()
    except (OSError, IOError):
        return nation

    nation.lines = len(raw_lines)
    current_func: Optional[FunctionInfo] = None
    func_indent = 0

    for i, raw in enumerate(raw_lines, 1):
        line = raw.rstrip()
        stripped = line.strip()

        if stripped and not stripped.startswith("#") and not stripped.startswith("//"):
            nation.code_lines += 1

        # Imports
        m = IMPORT_RE.match(stripped)
        if m:
            imp_path = m.group(1)
            imp_name = os.path.splitext(os.path.basename(imp_path))[0]
            if imp_name not in nation.imports:
                nation.imports.append(imp_name)
            continue

        # Function definition
        m = FUNC_DEF_RE.match(line)
        if m:
            if current_func is not None:
                current_func.end_line = i - 1
                current_func.line_count = current_func.end_line - current_func.start_line + 1
                nation.functions.append(current_func)

            indent = len(m.group(1))
            fname = m.group(2)
            rest = m.group(3)

            pm = PARAM_RE.search(rest)
            pcount = 0
            if pm:
                params = pm.group(1).strip()
                if params:
                    pcount = len([p.strip() for p in params.split(",") if p.strip()])

            current_func = FunctionInfo(
                name=fname, module=name,
                start_line=i, end_line=i, param_count=pcount,
            )
            func_indent = indent
            nation.exports.add(fname)
            continue

        # Inside function body
        if current_func is not None:
            line_indent = len(line) - len(line.lstrip()) if stripped else 0
            if stripped and line_indent <= func_indent and i > current_func.start_line:
                current_func.end_line = i - 1
                current_func.line_count = current_func.end_line - current_func.start_line + 1
                nation.functions.append(current_func)
                current_func = None
            else:
                if stripped:
                    # Track calls
                    for cm in CALL_RE.finditer(stripped):
                        cname = cm.group(1)
                        if cname not in KEYWORDS:
                            current_func.calls.add(cname)
                            nation.all_calls.add(cname)
                    # Track variables
                    am = ASSIGN_RE.match(stripped)
                    if am:
                        vname = am.group(1)
                        if vname not in KEYWORDS:
                            current_func.variables_written.add(vname)
                            nation.variables_defined.add(vname)
                    if "return" in stripped:
                        current_func.has_return = True
        else:
            # Top-level calls and assignments
            if stripped:
                for cm in CALL_RE.finditer(stripped):
                    cname = cm.group(1)
                    if cname not in KEYWORDS:
                        nation.all_calls.add(cname)
                am = ASSIGN_RE.match(stripped)
                if am:
                    vname = am.group(1)
                    if vname not in KEYWORDS:
                        nation.variables_defined.add(vname)

    # Close last function
    if current_func is not None:
        current_func.end_line = nation.lines
        current_func.line_count = current_func.end_line - current_func.start_line + 1
        nation.functions.append(current_func)

    return nation


def parse_codebase(paths: list, recursive: bool = False) -> List[ModuleNation]:
    """Parse all .srv files into ModuleNation objects."""
    srv_files = _find_srv_files(paths, recursive=recursive)
    nations = []
    for f in srv_files:
        nation = parse_module(f)
        if nation.lines > 0:
            nations.append(nation)
    return nations


# ── D001: Sovereignty Analyzer ───────────────────────────────────────


def analyze_sovereignty(nations: List[ModuleNation]) -> SovereigntyReport:
    """Score each module's independence 0-100."""
    report = SovereigntyReport()
    if not nations:
        report.score = 100.0
        return report

    all_func_names: Dict[str, str] = {}
    for n in nations:
        for f in n.functions:
            all_func_names[f.name] = n.name

    rankings = []
    for n in nations:
        # Factor 1: Import dependency ratio (fewer imports = more sovereign)
        import_penalty = min(len(n.imports) * 10, 50)

        # Factor 2: Self-sufficiency — ratio of internal calls to total calls
        internal_calls = 0
        external_calls = 0
        local_func_names = {f.name for f in n.functions}
        for call in n.all_calls:
            if call in local_func_names:
                internal_calls += 1
            elif call in all_func_names and all_func_names[call] != n.name:
                external_calls += 1

        total_calls = internal_calls + external_calls
        self_sufficiency = (internal_calls / total_calls * 100) if total_calls > 0 else 100

        # Factor 3: Function count (having functions = productive nation)
        productivity = min(len(n.functions) * 5, 30)

        raw = max(0, min(100, self_sufficiency - import_penalty + productivity))
        n.sovereignty_score = round(raw, 1)

        if raw >= 80:
            n.sovereignty_tier = "Superpower"
        elif raw >= 60:
            n.sovereignty_tier = "Independent"
        elif raw >= 40:
            n.sovereignty_tier = "Aligned"
        elif raw >= 20:
            n.sovereignty_tier = "Dependent"
        else:
            n.sovereignty_tier = "Vassal"

        rankings.append({
            "module": n.name,
            "sovereignty": n.sovereignty_score,
            "tier": n.sovereignty_tier,
            "imports": len(n.imports),
            "functions": len(n.functions),
            "internal_calls": internal_calls,
            "external_calls": external_calls,
        })

    rankings.sort(key=lambda x: x["sovereignty"], reverse=True)
    report.rankings = rankings

    scores = [r["sovereignty"] for r in rankings]
    report.avg_sovereignty = round(sum(scores) / len(scores), 1) if scores else 0
    report.most_independent = rankings[0]["module"] if rankings else ""
    report.most_dependent = rankings[-1]["module"] if rankings else ""

    # Score: avg sovereignty is the subscore
    report.score = report.avg_sovereignty
    return report


# ── D002: Alliance Detector ──────────────────────────────────────────


def _jaccard(set_a: set, set_b: set) -> float:
    """Jaccard similarity coefficient."""
    if not set_a and not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def detect_alliances(nations: List[ModuleNation]) -> AllianceReport:
    """Find clusters of mutually dependent modules."""
    report = AllianceReport()
    if len(nations) < 2:
        report.score = 100.0
        return report

    name_map = {n.name: n for n in nations}

    # Build pairwise affinity matrix
    pairs: List[Tuple[str, str, float, int, int]] = []
    for i, a in enumerate(nations):
        for j, b in enumerate(nations):
            if j <= i:
                continue
            # Check mutual imports
            a_imports_b = b.name in a.imports
            b_imports_a = a.name in b.imports
            mutual = a_imports_b and b_imports_a

            # Jaccard on call sets
            call_sim = _jaccard(a.all_calls, b.all_calls)

            # Jaccard on import sets
            import_sim = _jaccard(set(a.imports), set(b.imports))

            strength = 0.0
            if mutual:
                strength += 0.5
            elif a_imports_b or b_imports_a:
                strength += 0.2
            strength += call_sim * 0.3
            strength += import_sim * 0.2

            if strength > 0.15:
                shared_i = len(set(a.imports) & set(b.imports))
                shared_c = len(a.all_calls & b.all_calls)
                pairs.append((a.name, b.name, round(strength, 3), shared_i, shared_c))

    # Greedy clustering: merge pairs into alliances
    alliances: List[Alliance] = []
    used = set()
    pairs.sort(key=lambda x: x[2], reverse=True)

    for a_name, b_name, strength, si, sc in pairs:
        # Find existing alliance containing either
        found = None
        for alliance in alliances:
            if a_name in alliance.members or b_name in alliance.members:
                found = alliance
                break
        if found:
            if a_name not in found.members:
                found.members.append(a_name)
            if b_name not in found.members:
                found.members.append(b_name)
            found.strength = round((found.strength + strength) / 2, 3)
            found.shared_imports += si
            found.shared_calls += sc
        else:
            alliances.append(Alliance(
                members=[a_name, b_name],
                strength=strength,
                alliance_type="bilateral",
                shared_imports=si,
                shared_calls=sc,
            ))

    # Update types
    for a in alliances:
        if len(a.members) > 2:
            a.alliance_type = "multilateral"

    report.alliances = [
        {
            "members": a.members,
            "strength": a.strength,
            "type": a.alliance_type,
            "shared_imports": a.shared_imports,
            "shared_calls": a.shared_calls,
        }
        for a in alliances
    ]
    report.total_alliances = len(alliances)
    report.largest_alliance = max((len(a.members) for a in alliances), default=0)
    strengths = [a.strength for a in alliances]
    report.avg_strength = round(sum(strengths) / len(strengths), 3) if strengths else 0

    # Score: alliances are good — more strong alliances = higher score
    if alliances:
        report.score = round(min(100, report.avg_strength * 100 + len(alliances) * 5), 1)
    else:
        # No alliances in small codebase is fine; in large codebase it's a concern
        report.score = 50.0 if len(nations) > 5 else 80.0
    return report


# ── D003: Embargo Detector ───────────────────────────────────────────


def detect_embargoes(nations: List[ModuleNation]) -> EmbargoReport:
    """Find missing connections between related modules."""
    report = EmbargoReport()
    if len(nations) < 2:
        report.score = 100.0
        return report

    name_map = {n.name: n for n in nations}
    embargoes: List[Embargo] = []

    for i, a in enumerate(nations):
        for j, b in enumerate(nations):
            if j <= i:
                continue

            # Already connected?
            connected = (b.name in a.imports) or (a.name in b.imports)
            if connected:
                continue

            shared_patterns: List[str] = []

            # Check naming similarity (shared prefix)
            prefix_len = 0
            for c1, c2 in zip(a.name, b.name):
                if c1 == c2:
                    prefix_len += 1
                else:
                    break
            if prefix_len >= 4:
                shared_patterns.append(f"shared prefix '{a.name[:prefix_len]}'")

            # Check similar function names
            a_funcs = {f.name for f in a.functions}
            b_funcs = {f.name for f in b.functions}
            common_funcs = a_funcs & b_funcs
            if common_funcs:
                shared_patterns.append(f"same function names: {', '.join(sorted(common_funcs)[:3])}")

            # Check if A calls functions that B defines (but doesn't import B)
            b_exports = {f.name for f in b.functions}
            a_calls_b_funcs = a.all_calls & b_exports
            if a_calls_b_funcs:
                shared_patterns.append(f"A calls B's functions: {', '.join(sorted(a_calls_b_funcs)[:3])}")

            # Similar variable names
            common_vars = a.variables_defined & b.variables_defined
            if len(common_vars) >= 3:
                shared_patterns.append(f"shared variables: {', '.join(sorted(common_vars)[:3])}")

            if shared_patterns:
                severity = min(1.0, len(shared_patterns) * 0.3)
                embargoes.append(Embargo(
                    module_a=a.name,
                    module_b=b.name,
                    reason="; ".join(shared_patterns),
                    severity=round(severity, 2),
                    shared_patterns=shared_patterns,
                ))

    report.embargoes = [
        {
            "module_a": e.module_a,
            "module_b": e.module_b,
            "reason": e.reason,
            "severity": e.severity,
            "shared_patterns": e.shared_patterns,
        }
        for e in embargoes
    ]
    report.total_embargoes = len(embargoes)
    sevs = [e.severity for e in embargoes]
    report.avg_severity = round(sum(sevs) / len(sevs), 2) if sevs else 0

    # Score: fewer embargoes is better
    penalty = min(50, len(embargoes) * 5)
    report.score = round(max(0, 100 - penalty - report.avg_severity * 20), 1)
    return report


# ── D004: Treaty Analyzer ────────────────────────────────────────────


def analyze_treaties(nations: List[ModuleNation]) -> TreatyReport:
    """Analyze interface contracts between modules."""
    report = TreatyReport()
    if len(nations) < 2:
        report.score = 100.0
        return report

    name_map = {n.name: n for n in nations}
    treaties: List[Treaty] = []

    for n in nations:
        for imp_name in n.imports:
            if imp_name not in name_map:
                continue
            target = name_map[imp_name]
            target_funcs = {f.name for f in target.functions}

            # Which of target's functions does this module call?
            used_funcs = sorted(n.all_calls & target_funcs)

            if not used_funcs and not target_funcs:
                continue

            complexity = min(1.0, len(used_funcs) / 10) if used_funcs else 0.1

            # Is it one-sided? (n imports target, but target doesn't import n)
            one_sided = n.name not in target.imports

            treaties.append(Treaty(
                exporter=imp_name,
                importer=n.name,
                functions_used=used_funcs,
                complexity=round(complexity, 2),
                is_one_sided=one_sided,
            ))

    report.treaties = [
        {
            "exporter": t.exporter,
            "importer": t.importer,
            "functions_used": t.functions_used,
            "complexity": t.complexity,
            "is_one_sided": t.is_one_sided,
        }
        for t in treaties
    ]
    report.total_treaties = len(treaties)
    report.one_sided_count = sum(1 for t in treaties if t.is_one_sided)
    complexities = [t.complexity for t in treaties]
    report.avg_complexity = round(sum(complexities) / len(complexities), 2) if complexities else 0

    if treaties:
        report.fairness_ratio = round(1 - (report.one_sided_count / len(treaties)), 2)
    else:
        report.fairness_ratio = 1.0

    # Score: balanced treaties are good, one-sided are bad
    report.score = round(report.fairness_ratio * 80 + 20 * (1 - report.avg_complexity), 1)
    return report


# ── D005: Conflict Detector ──────────────────────────────────────────


def detect_conflicts(nations: List[ModuleNation]) -> ConflictReport:
    """Find naming collisions and competing implementations."""
    report = ConflictReport()
    if len(nations) < 2:
        report.score = 100.0
        return report

    conflicts: List[Conflict] = []

    # Naming collisions: same function name in different modules
    func_locations: Dict[str, List[str]] = defaultdict(list)
    for n in nations:
        for f in n.functions:
            func_locations[f.name].append(n.name)

    for fname, modules in func_locations.items():
        if len(modules) > 1:
            severity = min(1.0, len(modules) * 0.25)
            conflicts.append(Conflict(
                modules=sorted(set(modules)),
                conflict_type="naming",
                severity=round(severity, 2),
                details=f"Function '{fname}' defined in {len(modules)} modules",
                items=[fname],
            ))

    # Resource contention: modules writing to same variable names at top level
    var_locations: Dict[str, List[str]] = defaultdict(list)
    for n in nations:
        for v in n.variables_defined:
            var_locations[v].append(n.name)

    common_var_sets: Dict[Tuple[str, ...], List[str]] = defaultdict(list)
    for vname, modules in var_locations.items():
        if len(modules) > 1:
            key = tuple(sorted(set(modules)))
            common_var_sets[key].append(vname)

    for module_key, vars_list in common_var_sets.items():
        if len(vars_list) >= 3:
            severity = min(1.0, len(vars_list) * 0.1)
            conflicts.append(Conflict(
                modules=list(module_key),
                conflict_type="resource",
                severity=round(severity, 2),
                details=f"{len(vars_list)} shared variable names",
                items=sorted(vars_list)[:5],
            ))

    # Implementation conflicts: similar function signatures (same name + similar param count)
    func_sigs: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
    for n in nations:
        for f in n.functions:
            func_sigs[f.name].append((n.name, f.param_count))

    for fname, sigs in func_sigs.items():
        if len(sigs) > 1:
            # Check if param counts differ (competing implementations)
            params = [s[1] for s in sigs]
            if len(set(params)) > 1:
                modules = sorted(set(s[0] for s in sigs))
                # Only add if not already added as naming conflict
                already = any(
                    c.conflict_type == "implementation" and set(c.modules) == set(modules)
                    and fname in c.items
                    for c in conflicts
                )
                if not already:
                    conflicts.append(Conflict(
                        modules=modules,
                        conflict_type="implementation",
                        severity=0.5,
                        details=f"'{fname}' has different signatures: {dict(sigs)}",
                        items=[fname],
                    ))

    report.conflicts = [
        {
            "modules": c.modules,
            "type": c.conflict_type,
            "severity": c.severity,
            "details": c.details,
            "items": c.items,
        }
        for c in conflicts
    ]
    report.total_conflicts = len(conflicts)
    sevs = [c.severity for c in conflicts]
    report.avg_severity = round(sum(sevs) / len(sevs), 2) if sevs else 0

    # Score: fewer conflicts is better
    penalty = min(60, len(conflicts) * 8)
    report.score = round(max(0, 100 - penalty - report.avg_severity * 15), 1)
    return report


# ── D006: Diplomatic Health Scorer ───────────────────────────────────


def score_health(
    sov: SovereigntyReport,
    ali: AllianceReport,
    emb: EmbargoReport,
    tre: TreatyReport,
    con: ConflictReport,
) -> Tuple[float, str, Dict[str, float]]:
    """Compute composite diplomatic health score 0-100."""
    weights = {
        "sovereignty": 0.30,
        "alliances": 0.20,
        "embargoes": 0.15,
        "treaties": 0.20,
        "conflicts": 0.15,
    }
    sub_scores = {
        "sovereignty": sov.score,
        "alliances": ali.score,
        "embargoes": emb.score,
        "treaties": tre.score,
        "conflicts": con.score,
    }

    health = sum(sub_scores[k] * weights[k] for k in weights)
    health = round(max(0, min(100, health)), 1)

    if health >= 80:
        tier = "Utopia"
    elif health >= 60:
        tier = "Stable"
    elif health >= 40:
        tier = "Tense"
    elif health >= 20:
        tier = "Crisis"
    else:
        tier = "Failed State"

    return health, tier, sub_scores


# ── D007: Insight Generator ──────────────────────────────────────────


def generate_insights(
    nations: List[ModuleNation],
    sov: SovereigntyReport,
    ali: AllianceReport,
    emb: EmbargoReport,
    tre: TreatyReport,
    con: ConflictReport,
    health_score: float,
    health_tier: str,
) -> List[Dict[str, Any]]:
    """Generate autonomous diplomatic recommendations."""
    insights: List[Dict[str, Any]] = []

    # Sovereignty insights
    for r in sov.rankings:
        if r["sovereignty"] < 20:
            insights.append({
                "engine": "D001",
                "type": "sovereignty_warning",
                "severity": "high",
                "message": f"Module '{r['module']}' is a vassal state — "
                           f"sovereignty {r['sovereignty']}/100 with {r['imports']} imports. "
                           f"Consider reducing external dependencies.",
            })
        elif r["sovereignty"] >= 90:
            insights.append({
                "engine": "D001",
                "type": "sovereignty_praise",
                "severity": "info",
                "message": f"Module '{r['module']}' is a superpower — "
                           f"sovereignty {r['sovereignty']}/100. Highly self-contained.",
            })

    # Alliance insights
    for a in ali.alliances:
        if a["strength"] >= 0.7:
            insights.append({
                "engine": "D002",
                "type": "strong_alliance",
                "severity": "info",
                "message": f"Strong {a['type']} alliance: {', '.join(a['members'])} "
                           f"(strength {a['strength']}). These modules work well together.",
            })

    # Embargo insights — suggest connections
    for e in emb.embargoes:
        if e["severity"] >= 0.5:
            insights.append({
                "engine": "D003",
                "type": "embargo_resolution",
                "severity": "medium",
                "message": f"'{e['module_a']}' and '{e['module_b']}' are related but disconnected: "
                           f"{e['reason']}. Consider adding an import.",
            })

    # Treaty insights
    for t in tre.treaties:
        if t["is_one_sided"] and t["complexity"] >= 0.3:
            insights.append({
                "engine": "D004",
                "type": "treaty_imbalance",
                "severity": "medium",
                "message": f"One-sided treaty: '{t['importer']}' depends on "
                           f"'{t['exporter']}' ({len(t['functions_used'])} functions) "
                           f"but not vice versa. Consider bidirectional design.",
            })

    # Conflict insights
    for c in con.conflicts:
        if c["type"] == "naming" and c["severity"] >= 0.5:
            insights.append({
                "engine": "D005",
                "type": "naming_conflict",
                "severity": "high",
                "message": f"Naming collision across {', '.join(c['modules'])}: "
                           f"{c['details']}. Consider namespacing.",
            })
        elif c["type"] == "implementation":
            insights.append({
                "engine": "D005",
                "type": "competing_implementation",
                "severity": "medium",
                "message": f"Competing implementations in {', '.join(c['modules'])}: "
                           f"{c['details']}. Consider consolidating.",
            })

    # Overall health insight
    if health_tier == "Failed State":
        insights.append({
            "engine": "D006",
            "type": "critical_warning",
            "severity": "critical",
            "message": f"Diplomatic health is {health_score}/100 (Failed State). "
                       f"Major structural issues need attention.",
        })
    elif health_tier == "Utopia":
        insights.append({
            "engine": "D006",
            "type": "health_praise",
            "severity": "info",
            "message": f"Diplomatic health is {health_score}/100 (Utopia). "
                       f"Module relationships are well-balanced.",
        })

    return insights


# ── Full Analysis ────────────────────────────────────────────────────


def analyze(paths: list, recursive: bool = False) -> DiplomacyReport:
    """Run all 7 diplomacy analysis engines."""
    nations = parse_codebase(paths, recursive=recursive)

    sov = analyze_sovereignty(nations)
    ali = detect_alliances(nations)
    emb = detect_embargoes(nations)
    tre = analyze_treaties(nations)
    con = detect_conflicts(nations)

    health, tier, sub_scores = score_health(sov, ali, emb, tre, con)
    insights = generate_insights(nations, sov, ali, emb, tre, con, health, tier)

    report = DiplomacyReport(
        timestamp=datetime.now().isoformat(),
        path=str(paths),
        total_modules=len(nations),
        total_functions=sum(len(n.functions) for n in nations),
        total_lines=sum(n.lines for n in nations),
        sovereignty=asdict(sov),
        alliances=asdict(ali),
        embargoes=asdict(emb),
        treaties=asdict(tre),
        conflicts=asdict(con),
        health_score=health,
        health_tier=tier,
        sub_scores=sub_scores,
        insights=insights,
        modules=[
            {
                "name": n.name,
                "path": n.path,
                "lines": n.lines,
                "functions": len(n.functions),
                "imports": n.imports,
                "exports": sorted(n.exports),
                "sovereignty": n.sovereignty_score,
                "sovereignty_tier": n.sovereignty_tier,
            }
            for n in nations
        ],
    )
    return report


# ── CLI Output Formatting ────────────────────────────────────────────


def _bar(value: float, width: int = 20) -> str:
    filled = int(value / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _tier_color(tier: str) -> str:
    colors = {
        "Utopia": _C.green, "Stable": _C.cyan,
        "Tense": _C.yellow, "Crisis": _C.red,
        "Failed State": _C.red, "Superpower": _C.green,
        "Independent": _C.cyan, "Aligned": _C.yellow,
        "Dependent": _C.red, "Vassal": _C.red,
    }
    fn = colors.get(tier, _C.dim)
    return fn(tier)


def print_sovereignty(report: DiplomacyReport):
    """Print sovereignty rankings."""
    sov = report["sovereignty"] if isinstance(report, dict) else report.sovereignty
    rankings = sov.get("rankings", []) if isinstance(sov, dict) else sov.rankings
    print(_C.bold("\n═══ D001: Sovereignty Rankings ═══\n"))
    if not rankings:
        print("  No modules to analyze.")
        return
    for r in rankings:
        score = r["sovereignty"]
        tier = r["tier"]
        bar = _bar(score)
        print(f"  {r['module']:<25} {bar} {score:5.1f}  {_tier_color(tier)}")
        print(f"  {'':25} imports={r['imports']}  funcs={r['functions']}  "
              f"internal={r['internal_calls']}  external={r['external_calls']}")


def print_alliances(report: DiplomacyReport):
    """Print alliance map."""
    ali = report["alliances"] if isinstance(report, dict) else report.alliances
    alliances = ali.get("alliances", []) if isinstance(ali, dict) else ali.alliances
    print(_C.bold("\n═══ D002: Alliance Map ═══\n"))
    if not alliances:
        print("  No alliances detected.")
        return
    for i, a in enumerate(alliances, 1):
        strength_bar = _bar(a["strength"] * 100, 10)
        print(f"  Alliance #{i} ({_C.cyan(a['type'])})")
        print(f"    Members:  {', '.join(a['members'])}")
        print(f"    Strength: {strength_bar} {a['strength']:.3f}")


def print_embargoes(report: DiplomacyReport):
    """Print embargo list."""
    emb = report["embargoes"] if isinstance(report, dict) else report.embargoes
    embargoes = emb.get("embargoes", []) if isinstance(emb, dict) else emb.embargoes
    print(_C.bold("\n═══ D003: Embargoes ═══\n"))
    if not embargoes:
        print("  No embargoes detected. All related modules are connected.")
        return
    for e in embargoes:
        sev_color = _C.red if e["severity"] >= 0.7 else (_C.yellow if e["severity"] >= 0.4 else _C.dim)
        print(f"  {e['module_a']} ↔ {e['module_b']}  severity={sev_color(e['severity'])}")
        print(f"    {e['reason']}")


def print_treaties(report: DiplomacyReport):
    """Print treaty analysis."""
    tre = report["treaties"] if isinstance(report, dict) else report.treaties
    treaties = tre.get("treaties", []) if isinstance(tre, dict) else tre.treaties
    print(_C.bold("\n═══ D004: Treaties ═══\n"))
    if not treaties:
        print("  No treaties (imports) detected.")
        return
    for t in treaties:
        direction = "→" if t["is_one_sided"] else "↔"
        status = _C.yellow("one-sided") if t["is_one_sided"] else _C.green("mutual")
        print(f"  {t['importer']} {direction} {t['exporter']}  [{status}]  "
              f"complexity={t['complexity']:.2f}")
        if t["functions_used"]:
            print(f"    uses: {', '.join(t['functions_used'][:5])}")


def print_conflicts(report: DiplomacyReport):
    """Print conflict report."""
    con = report["conflicts"] if isinstance(report, dict) else report.conflicts
    conflicts = con.get("conflicts", []) if isinstance(con, dict) else con.conflicts
    print(_C.bold("\n═══ D005: Conflicts ═══\n"))
    if not conflicts:
        print("  No conflicts detected. Peace reigns.")
        return
    for c in conflicts:
        sev_color = _C.red if c["severity"] >= 0.7 else (_C.yellow if c["severity"] >= 0.4 else _C.dim)
        print(f"  [{c['type'].upper()}] {', '.join(c['modules'])}  "
              f"severity={sev_color(c['severity'])}")
        print(f"    {c['details']}")


def print_health(report: DiplomacyReport):
    """Print overall health."""
    r = report if isinstance(report, dict) else asdict(report)
    score = r["health_score"]
    tier = r["health_tier"]
    sub = r["sub_scores"]

    print(_C.bold("\n═══ D006: Diplomatic Health ═══\n"))
    print(f"  Overall: {_bar(score)} {score:.1f}/100  {_tier_color(tier)}")
    print()
    for name, val in sub.items():
        weight = {"sovereignty": 30, "alliances": 20, "embargoes": 15,
                  "treaties": 20, "conflicts": 15}
        print(f"    {name:<15} {_bar(val, 15)} {val:5.1f}  (weight {weight.get(name, 0)}%)")


def print_insights(report: DiplomacyReport):
    """Print insights."""
    r = report if isinstance(report, dict) else asdict(report)
    insights = r.get("insights", [])
    print(_C.bold("\n═══ D007: Diplomatic Insights ═══\n"))
    if not insights:
        print("  No insights generated.")
        return
    icons = {"critical": "🚨", "high": "⚠️", "medium": "📋", "info": "ℹ️"}
    for ins in insights:
        icon = icons.get(ins["severity"], "•")
        print(f"  {icon} [{ins['engine']}] {ins['message']}")


def print_full_report(report: DiplomacyReport):
    """Print the complete analysis."""
    r = report if isinstance(report, dict) else asdict(report)
    print(_C.bold(f"\n{'═' * 60}"))
    print(_C.bold("  sauravdiplomacy — Code Diplomacy Engine v{__version__}"))
    print(_C.bold(f"{'═' * 60}"))
    print(f"  Modules: {r['total_modules']}  Functions: {r['total_functions']}  "
          f"Lines: {r['total_lines']}")

    print_health(report)
    print_sovereignty(report)
    print_alliances(report)
    print_treaties(report)
    print_embargoes(report)
    print_conflicts(report)
    print_insights(report)
    print()


# ── HTML Dashboard ───────────────────────────────────────────────────


def generate_html(report: DiplomacyReport) -> str:
    """Generate a self-contained interactive HTML dashboard."""
    r = report if isinstance(report, dict) else asdict(report)

    def _set_default(obj):
        if isinstance(obj, set):
            return sorted(obj)
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    report_json = json.dumps(r, indent=2, default=_set_default)

    tier = r["health_tier"]
    tier_colors = {
        "Utopia": "#22c55e", "Stable": "#06b6d4", "Tense": "#eab308",
        "Crisis": "#ef4444", "Failed State": "#991b1b",
    }
    tier_color = tier_colors.get(tier, "#666")

    sov_rankings = r.get("sovereignty", {}).get("rankings", [])
    sov_rows = ""
    for rank in sov_rankings:
        pct = rank["sovereignty"]
        tier_class = rank["tier"].lower().replace(" ", "-")
        sov_rows += f"""<tr>
            <td>{rank['module']}</td>
            <td><div class="bar-bg"><div class="bar-fill" style="width:{pct}%;background:{tier_colors.get(rank['tier'], '#666')}"></div></div></td>
            <td>{pct:.1f}</td>
            <td><span class="badge badge-{tier_class}">{rank['tier']}</span></td>
            <td>{rank['imports']}</td>
            <td>{rank['functions']}</td>
        </tr>"""

    alliances_html = ""
    for i, a in enumerate(r.get("alliances", {}).get("alliances", []), 1):
        members = ", ".join(a["members"])
        alliances_html += f"""<div class="card">
            <h4>Alliance #{i} — {a['type'].title()}</h4>
            <p><strong>Members:</strong> {members}</p>
            <p><strong>Strength:</strong> {a['strength']:.3f}</p>
        </div>"""

    treaties_html = ""
    for t in r.get("treaties", {}).get("treaties", []):
        direction = "→" if t["is_one_sided"] else "↔"
        status_cls = "one-sided" if t["is_one_sided"] else "mutual"
        funcs = ", ".join(t["functions_used"][:5]) if t["functions_used"] else "—"
        treaties_html += f"""<tr>
            <td>{t['importer']}</td>
            <td>{direction}</td>
            <td>{t['exporter']}</td>
            <td><span class="badge badge-{status_cls}">{'One-sided' if t['is_one_sided'] else 'Mutual'}</span></td>
            <td>{t['complexity']:.2f}</td>
            <td>{funcs}</td>
        </tr>"""

    embargoes_html = ""
    for e in r.get("embargoes", {}).get("embargoes", []):
        embargoes_html += f"""<tr>
            <td>{e['module_a']}</td>
            <td>{e['module_b']}</td>
            <td>{e['severity']:.2f}</td>
            <td>{e['reason']}</td>
        </tr>"""

    conflicts_html = ""
    for c in r.get("conflicts", {}).get("conflicts", []):
        conflicts_html += f"""<tr>
            <td>{', '.join(c['modules'])}</td>
            <td><span class="badge badge-{c['type']}">{c['type'].title()}</span></td>
            <td>{c['severity']:.2f}</td>
            <td>{c['details']}</td>
        </tr>"""

    insights_html = ""
    sev_icons = {"critical": "🚨", "high": "⚠️", "medium": "📋", "info": "ℹ️"}
    for ins in r.get("insights", []):
        icon = sev_icons.get(ins["severity"], "•")
        insights_html += f"""<div class="insight insight-{ins['severity']}">
            <span class="insight-icon">{icon}</span>
            <span class="insight-engine">[{ins['engine']}]</span>
            {ins['message']}
        </div>"""

    sub_scores = r.get("sub_scores", {})
    sub_bars = ""
    weights = {"sovereignty": 30, "alliances": 20, "embargoes": 15, "treaties": 20, "conflicts": 15}
    for k, v in sub_scores.items():
        sub_bars += f"""<div class="sub-score">
            <span class="sub-label">{k.title()} ({weights.get(k,0)}%)</span>
            <div class="bar-bg"><div class="bar-fill" style="width:{v}%"></div></div>
            <span class="sub-val">{v:.1f}</span>
        </div>"""

    _tre = r.get('treaties', {})
    _tre_fairness = _tre.get('fairness_ratio', 0)
    _tre_one_sided = _tre.get('one_sided_count', 0)
    _tre_total = _tre.get('total_treaties', 0)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>sauravdiplomacy — Code Diplomacy Dashboard</title>
<style>
:root {{ --bg: #0f172a; --card: #1e293b; --text: #e2e8f0; --dim: #94a3b8;
         --accent: {tier_color}; --border: #334155; }}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg);
        color: var(--text); padding: 2rem; }}
h1 {{ color: var(--accent); margin-bottom: .5rem; }}
h2 {{ color: var(--accent); margin: 2rem 0 1rem; border-bottom: 2px solid var(--border); padding-bottom: .5rem; }}
h3 {{ color: var(--dim); margin-bottom: .5rem; }}
h4 {{ color: var(--text); margin-bottom: .5rem; }}
.header {{ text-align: center; margin-bottom: 2rem; }}
.gauge {{ display: inline-block; width: 150px; height: 150px; border-radius: 50%;
          border: 8px solid var(--accent); display: flex; align-items: center;
          justify-content: center; margin: 1rem auto; }}
.gauge-val {{ font-size: 2rem; font-weight: bold; color: var(--accent); }}
.gauge-tier {{ font-size: 1.2rem; color: var(--accent); }}
.stats {{ display: flex; gap: 2rem; justify-content: center; margin: 1rem 0; color: var(--dim); }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 1.5rem; }}
.card {{ background: var(--card); border-radius: 8px; padding: 1.5rem; border: 1px solid var(--border); }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ padding: .5rem .75rem; text-align: left; border-bottom: 1px solid var(--border); }}
th {{ color: var(--dim); font-weight: 600; font-size: .85rem; text-transform: uppercase; }}
.bar-bg {{ background: var(--border); border-radius: 4px; height: 12px; width: 100%; }}
.bar-fill {{ background: var(--accent); border-radius: 4px; height: 100%; transition: width .3s; }}
.badge {{ padding: 2px 8px; border-radius: 12px; font-size: .8rem; font-weight: 600; }}
.badge-superpower {{ background: #166534; color: #bbf7d0; }}
.badge-independent {{ background: #155e75; color: #a5f3fc; }}
.badge-aligned {{ background: #854d0e; color: #fef08a; }}
.badge-dependent {{ background: #991b1b; color: #fecaca; }}
.badge-vassal {{ background: #7f1d1d; color: #fca5a5; }}
.badge-mutual {{ background: #166534; color: #bbf7d0; }}
.badge-one-sided {{ background: #854d0e; color: #fef08a; }}
.badge-naming {{ background: #991b1b; color: #fecaca; }}
.badge-implementation {{ background: #854d0e; color: #fef08a; }}
.badge-resource {{ background: #155e75; color: #a5f3fc; }}
.sub-score {{ display: flex; align-items: center; gap: .75rem; margin: .5rem 0; }}
.sub-label {{ width: 160px; color: var(--dim); font-size: .9rem; }}
.sub-val {{ width: 50px; text-align: right; font-weight: 600; }}
.insight {{ padding: .75rem 1rem; margin: .5rem 0; border-radius: 6px; border-left: 4px solid var(--border); background: var(--card); }}
.insight-critical {{ border-left-color: #ef4444; }}
.insight-high {{ border-left-color: #f97316; }}
.insight-medium {{ border-left-color: #eab308; }}
.insight-info {{ border-left-color: #06b6d4; }}
.insight-icon {{ margin-right: .5rem; }}
.insight-engine {{ color: var(--dim); font-size: .85rem; margin-right: .5rem; }}
.tab-bar {{ display: flex; gap: 0; margin-bottom: 1rem; border-bottom: 2px solid var(--border); }}
.tab {{ padding: .75rem 1.25rem; cursor: pointer; color: var(--dim); border-bottom: 2px solid transparent; margin-bottom: -2px; }}
.tab.active {{ color: var(--accent); border-bottom-color: var(--accent); }}
.tab-content {{ display: none; }}
.tab-content.active {{ display: block; }}
</style>
</head>
<body>

<div class="header">
    <h1>🏛️ sauravdiplomacy</h1>
    <h3>Autonomous Code Diplomacy Engine v{__version__}</h3>
    <div style="display:flex;align-items:center;justify-content:center;width:150px;height:150px;border-radius:50%;border:8px solid var(--accent);margin:1rem auto;">
        <div>
            <div class="gauge-val">{r['health_score']:.0f}</div>
            <div class="gauge-tier">{tier}</div>
        </div>
    </div>
    <div class="stats">
        <span>📦 {r['total_modules']} modules</span>
        <span>⚙️ {r['total_functions']} functions</span>
        <span>📄 {r['total_lines']} lines</span>
    </div>
</div>

<div class="card" style="max-width:600px;margin:0 auto 2rem;">
    <h3>Sub-Scores</h3>
    {sub_bars}
</div>

<div class="tab-bar">
    <div class="tab active" onclick="switchTab('sovereignty')">🏰 Sovereignty</div>
    <div class="tab" onclick="switchTab('alliances')">🤝 Alliances</div>
    <div class="tab" onclick="switchTab('treaties')">📜 Treaties</div>
    <div class="tab" onclick="switchTab('embargoes')">🚫 Embargoes</div>
    <div class="tab" onclick="switchTab('conflicts')">⚔️ Conflicts</div>
    <div class="tab" onclick="switchTab('insights')">💡 Insights</div>
</div>

<div id="tab-sovereignty" class="tab-content active">
    <div class="card">
        <h3>Sovereignty Rankings</h3>
        <table>
            <tr><th>Module</th><th>Score</th><th></th><th>Tier</th><th>Imports</th><th>Functions</th></tr>
            {sov_rows}
        </table>
    </div>
</div>

<div id="tab-alliances" class="tab-content">
    <div class="grid">{alliances_html if alliances_html else '<div class="card"><p>No alliances detected.</p></div>'}</div>
</div>

<div id="tab-treaties" class="tab-content">
    <div class="card">
        <h3>Treaty Analysis</h3>
        <p style="color:var(--dim);margin-bottom:1rem;">Fairness: {_tre_fairness:.0%} — One-sided: {_tre_one_sided}/{_tre_total}</p>
        <table>
            <tr><th>Importer</th><th></th><th>Exporter</th><th>Status</th><th>Complexity</th><th>Functions Used</th></tr>
            {treaties_html if treaties_html else '<tr><td colspan="6">No treaties detected.</td></tr>'}
        </table>
    </div>
</div>

<div id="tab-embargoes" class="tab-content">
    <div class="card">
        <h3>Embargoes — Missing Connections</h3>
        <table>
            <tr><th>Module A</th><th>Module B</th><th>Severity</th><th>Reason</th></tr>
            {embargoes_html if embargoes_html else '<tr><td colspan="4">No embargoes detected.</td></tr>'}
        </table>
    </div>
</div>

<div id="tab-conflicts" class="tab-content">
    <div class="card">
        <h3>Conflicts</h3>
        <table>
            <tr><th>Modules</th><th>Type</th><th>Severity</th><th>Details</th></tr>
            {conflicts_html if conflicts_html else '<tr><td colspan="4">No conflicts. Peace reigns!</td></tr>'}
        </table>
    </div>
</div>

<div id="tab-insights" class="tab-content">
    <div class="card">
        <h3>Autonomous Insights</h3>
        {insights_html if insights_html else '<p>No insights generated.</p>'}
    </div>
</div>

<script>
function switchTab(name) {{
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
    document.getElementById('tab-' + name).classList.add('active');
    event.target.classList.add('active');
}}
const REPORT = {report_json};
</script>
</body>
</html>"""


# ── Main ─────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        prog="sauravdiplomacy",
        description="Autonomous Code Diplomacy Engine for sauravcode",
    )
    parser.add_argument("path", nargs="?", default=".",
                        help="File or directory to analyze (default: cwd)")
    parser.add_argument("--recursive", "-r", action="store_true",
                        help="Recurse into subdirectories")
    parser.add_argument("--html", metavar="FILE",
                        help="Write interactive HTML dashboard")
    parser.add_argument("--json", action="store_true",
                        help="Print JSON output")
    parser.add_argument("--sovereignty", action="store_true",
                        help="Show sovereignty rankings only")
    parser.add_argument("--alliances", action="store_true",
                        help="Show alliance map only")
    parser.add_argument("--embargoes", action="store_true",
                        help="Show embargo list only")
    parser.add_argument("--treaties", action="store_true",
                        help="Show treaty analysis only")
    parser.add_argument("--conflicts", action="store_true",
                        help="Show conflict report only")

    args = parser.parse_args()
    report = analyze([args.path], recursive=args.recursive)

    if args.html:
        html = generate_html(report)
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Dashboard written to {args.html}")

    if args.json:
        def _set_default(obj):
            if isinstance(obj, set):
                return sorted(obj)
            raise TypeError
        print(json.dumps(asdict(report), indent=2, default=_set_default))
        return

    # Filtered views
    if args.sovereignty:
        print_sovereignty(report)
    elif args.alliances:
        print_alliances(report)
    elif args.embargoes:
        print_embargoes(report)
    elif args.treaties:
        print_treaties(report)
    elif args.conflicts:
        print_conflicts(report)
    else:
        if not args.html:
            print_full_report(report)


if __name__ == "__main__":
    main()
