"""sauravcontract — Design-by-Contract Verifier for sauravcode.

Autonomous contract verification with proactive violation detection:
- Parse @requires, @ensures, @invariant annotations from .srv comments
- Static contract coverage analysis (% of functions with contracts)
- Potential violation detection via code-flow analysis
- Auto-suggest contracts for unannotated functions
- Contract inheritance checking across function calls
- Blame analysis (caller vs callee fault)
- Proactive recommendations for tighter/missing contracts

Usage:
    python sauravcontract.py <filename>.srv [options]

Options:
    --report        Generate detailed HTML contract report
    --json          Output findings as JSON
    --watch         Re-analyze on file change
    --strict        Fail on any violation
    --suggest       Auto-suggest contracts for unannotated functions
    --coverage      Show contract coverage summary only
    --blame         Enable blame analysis for violations
"""

import sys
import os
import re
import json
import time
import argparse
import hashlib
from datetime import datetime

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class ContractConfig:
    """Contract verifier configuration."""

    def __init__(self, report=False, json_output=False, watch=False,
                 strict=False, suggest=False, coverage_only=False,
                 blame=False):
        self.report = report
        self.json_output = json_output
        self.watch = watch
        self.strict = strict
        self.suggest = suggest
        self.coverage_only = coverage_only
        self.blame = blame


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

class ContractFinding:
    """A structured contract analysis finding."""

    SEV_INFO = "info"
    SEV_WARN = "warn"
    SEV_CRITICAL = "critical"

    def __init__(self, severity, category, message, func_name=None,
                 line=None, context=None):
        self.timestamp = datetime.now().isoformat()
        self.severity = severity
        self.category = category
        self.message = message
        self.func_name = func_name
        self.line = line
        self.context = context or {}

    def to_dict(self):
        return {
            "timestamp": self.timestamp,
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
            "func_name": self.func_name,
            "line": self.line,
            "context": self.context,
        }


# ---------------------------------------------------------------------------
# Contract Model
# ---------------------------------------------------------------------------

class Contract:
    """A single contract annotation."""

    def __init__(self, kind, expression, line_no):
        self.kind = kind          # "requires", "ensures", "invariant"
        self.expression = expression
        self.line_no = line_no

    def to_dict(self):
        return {"kind": self.kind, "expression": self.expression, "line": self.line_no}


class FunctionInfo:
    """Parsed function with its contracts and body."""

    def __init__(self, name, params, start_line, end_line, body_lines,
                 contracts):
        self.name = name
        self.params = params
        self.start_line = start_line
        self.end_line = end_line
        self.body_lines = body_lines
        self.contracts = contracts  # list of Contract
        self.calls = []             # function names called in body

    @property
    def requires(self):
        return [c for c in self.contracts if c.kind == "requires"]

    @property
    def ensures(self):
        return [c for c in self.contracts if c.kind == "ensures"]

    @property
    def invariants(self):
        return [c for c in self.contracts if c.kind == "invariant"]

    @property
    def has_contracts(self):
        return len(self.contracts) > 0

    def to_dict(self):
        return {
            "name": self.name,
            "params": self.params,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "contracts": [c.to_dict() for c in self.contracts],
            "calls": self.calls,
            "has_contracts": self.has_contracts,
        }


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_CONTRACT_RE = re.compile(
    r"^\s*#\s*@(requires|ensures|invariant)\s+(.+)$", re.IGNORECASE
)
_FUN_RE = re.compile(r"^\s*fun\s+(\w+)\s*\(([^)]*)\)")
_CALL_RE = re.compile(r"\b(\w+)\s*\(")
_RETURN_RE = re.compile(r"^\s*return\s+(.*)")
_ASSIGN_RE = re.compile(r"^\s*(?:let\s+)?(\w+)\s*=\s*(.*)")


def parse_srv(source):
    """Parse .srv source into list of FunctionInfo."""
    lines = source.splitlines()
    functions = []
    pending_contracts = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Collect contract annotations
        m = _CONTRACT_RE.match(line)
        if m:
            pending_contracts.append(
                Contract(m.group(1).lower(), m.group(2).strip(), i + 1)
            )
            i += 1
            continue
        # Match function definition
        fm = _FUN_RE.match(line)
        if fm:
            fname = fm.group(1)
            params = [p.strip() for p in fm.group(2).split(",") if p.strip()]
            start = i + 1
            # Find matching end
            depth = 1
            j = i + 1
            body = []
            while j < len(lines) and depth > 0:
                bl = lines[j].strip()
                if bl in ("end",):
                    depth -= 1
                    if depth == 0:
                        break
                elif re.match(r"^(fun|if|while|for)\b", bl):
                    depth += 1
                body.append(lines[j])
                j += 1
            end = j + 1
            # Extract calls from body
            calls = set()
            for bl in body:
                for cm in _CALL_RE.finditer(bl):
                    cname = cm.group(1)
                    if cname not in ("print", "say", "len", "range", "str",
                                     "int", "float", "type", "input",
                                     "append", "push", "pop"):
                        calls.add(cname)
            fi = FunctionInfo(fname, params, start, end, body,
                              pending_contracts)
            fi.calls = sorted(calls)
            functions.append(fi)
            pending_contracts = []
            i = j + 1
            continue
        # Non-contract comment or code — reset pending contracts
        if line.strip() and not line.strip().startswith("#"):
            pending_contracts = []
        i += 1
    return functions


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class ContractAnalyzer:
    """Analyze contracts for violations and coverage."""

    def __init__(self, functions, config):
        self.functions = functions
        self.config = config
        self.findings = []
        self.func_map = {f.name: f for f in functions}

    def analyze(self):
        """Run all analysis passes."""
        self._check_coverage()
        self._check_violations()
        self._check_inheritance()
        if self.config.blame:
            self._blame_analysis()
        if self.config.suggest:
            self._suggest_contracts()
        self._proactive_recommendations()
        return self.findings

    def _add(self, sev, cat, msg, func_name=None, line=None, ctx=None):
        self.findings.append(
            ContractFinding(sev, cat, msg, func_name, line, ctx)
        )

    # -- Coverage ----------------------------------------------------------

    def _check_coverage(self):
        total = len(self.functions)
        if total == 0:
            self._add(ContractFinding.SEV_INFO, "coverage",
                       "No functions found in source.")
            return
        covered = sum(1 for f in self.functions if f.has_contracts)
        pct = (covered / total) * 100
        self._add(ContractFinding.SEV_INFO, "coverage",
                   f"Contract coverage: {covered}/{total} functions "
                   f"({pct:.0f}%)",
                   ctx={"covered": covered, "total": total, "percent": pct})
        for f in self.functions:
            if not f.has_contracts:
                self._add(ContractFinding.SEV_WARN, "missing-contract",
                           f"Function '{f.name}' has no contracts.",
                           func_name=f.name, line=f.start_line)

    # -- Violation Detection -----------------------------------------------

    def _check_violations(self):
        for f in self.functions:
            self._check_return_violations(f)
            self._check_param_violations(f)
            self._check_invariant_violations(f)

    def _check_return_violations(self, func):
        """Check @ensures against return statements."""
        for ens in func.ensures:
            expr = ens.expression
            # Simple pattern: "result > 0", "result >= 1", "result != None"
            m = re.match(r"result\s*([><=!]+)\s*(.+)", expr)
            if not m:
                continue
            op, val_str = m.group(1), m.group(2).strip()
            # Scan returns for potential violations
            for bl in func.body_lines:
                rm = _RETURN_RE.match(bl)
                if rm:
                    ret_expr = rm.group(1).strip()
                    violation = self._check_value_against(ret_expr, op,
                                                          val_str)
                    if violation:
                        self._add(ContractFinding.SEV_CRITICAL, "violation",
                                   f"Function '{func.name}' may violate "
                                   f"@ensures {expr}: returns {ret_expr}",
                                   func_name=func.name, line=ens.line_no,
                                   ctx={"contract": expr,
                                        "return_expr": ret_expr})

    def _check_value_against(self, ret_expr, op, val_str):
        """Heuristic check if a return value could violate a condition."""
        try:
            val = float(val_str)
        except ValueError:
            return False
        try:
            ret_val = float(ret_expr)
        except ValueError:
            return False
        checks = {
            ">": ret_val <= val,
            ">=": ret_val < val,
            "<": ret_val >= val,
            "<=": ret_val > val,
            "==": ret_val != val,
            "!=": ret_val == val,
        }
        return checks.get(op, False)

    def _check_param_violations(self, func):
        """Check if @requires conditions could be violated by callers."""
        for req in func.requires:
            # Check if any parameter referenced in requires has no
            # obvious guard in the body
            for param in func.params:
                if param in req.expression:
                    self._add(ContractFinding.SEV_INFO, "precondition",
                               f"Function '{func.name}' requires: "
                               f"{req.expression}",
                               func_name=func.name, line=req.line_no)
                    break

    def _check_invariant_violations(self, func):
        """Check if loop invariants could be violated."""
        for inv in func.invariants:
            # Look for assignments that modify invariant variables
            inv_vars = re.findall(r"\b(\w+)\b", inv.expression)
            inv_vars = [v for v in inv_vars if v in func.params or
                        any(re.search(rf"\blet\s+{v}\b", bl)
                            for bl in func.body_lines)]
            for bl in func.body_lines:
                am = _ASSIGN_RE.match(bl)
                if am and am.group(1) in inv_vars:
                    self._add(ContractFinding.SEV_WARN, "invariant-risk",
                               f"Variable '{am.group(1)}' modified in "
                               f"'{func.name}'; may violate @invariant "
                               f"{inv.expression}",
                               func_name=func.name, line=inv.line_no,
                               ctx={"variable": am.group(1),
                                    "invariant": inv.expression})

    # -- Contract Inheritance ----------------------------------------------

    def _check_inheritance(self):
        """Verify contract compatibility across function calls."""
        for f in self.functions:
            for callee_name in f.calls:
                callee = self.func_map.get(callee_name)
                if not callee:
                    continue
                if callee.requires and not f.has_contracts:
                    self._add(ContractFinding.SEV_WARN, "inheritance",
                               f"'{f.name}' calls '{callee_name}' which has "
                               f"preconditions, but '{f.name}' has no "
                               f"contracts ensuring they're met.",
                               func_name=f.name, line=f.start_line)
                if callee.ensures and f.requires:
                    self._add(ContractFinding.SEV_INFO, "inheritance",
                               f"'{f.name}' calls '{callee_name}' with "
                               f"postconditions — chain verified.",
                               func_name=f.name)

    # -- Blame Analysis ----------------------------------------------------

    def _blame_analysis(self):
        """For each violation, determine caller vs callee fault."""
        for f in self.functions:
            for callee_name in f.calls:
                callee = self.func_map.get(callee_name)
                if not callee or not callee.requires:
                    continue
                # Check if caller has guards matching callee's requires
                body_text = "\n".join(f.body_lines)
                for req in callee.requires:
                    # Simple heuristic: check if an if-guard exists
                    has_guard = False
                    for var in re.findall(r"\b(\w+)\b", req.expression):
                        if re.search(rf"if\s+.*\b{var}\b", body_text):
                            has_guard = True
                            break
                    if not has_guard:
                        self._add(ContractFinding.SEV_WARN, "blame-caller",
                                   f"'{f.name}' calls '{callee_name}' "
                                   f"without guarding @requires "
                                   f"{req.expression} — caller at fault.",
                                   func_name=f.name, line=f.start_line,
                                   ctx={"callee": callee_name,
                                        "requires": req.expression})

    # -- Auto-Suggest ------------------------------------------------------

    def _suggest_contracts(self):
        """Infer likely contracts for unannotated functions."""
        for f in self.functions:
            if f.has_contracts:
                continue
            suggestions = []
            body_text = "\n".join(f.body_lines)
            # Suggest @requires for division (denominator != 0)
            for param in f.params:
                if re.search(rf"/\s*{param}\b", body_text):
                    suggestions.append(f"@requires {param} != 0")
                if re.search(rf"\blen\s*\(\s*{param}\s*\)", body_text):
                    suggestions.append(f"@requires {param} != []")
                if re.search(rf"\brange\s*\(\s*{param}\s*\)", body_text):
                    suggestions.append(f"@requires {param} >= 0")
            # Suggest @ensures for return patterns
            returns = [_RETURN_RE.match(bl) for bl in f.body_lines]
            returns = [r.group(1).strip() for r in returns if r]
            if returns:
                try:
                    vals = [float(r) for r in returns]
                    if all(v >= 0 for v in vals):
                        suggestions.append("@ensures result >= 0")
                except ValueError:
                    pass
                if all(r.startswith('"') or r.startswith("'") for r in returns):
                    suggestions.append("@ensures result != None")
            if len(returns) == 0 and body_text.strip():
                suggestions.append("@ensures result != None  # (no explicit return)")
            # Check for subtraction pattern (absolute value)
            if re.search(r"\w+\s*-\s*\w+", body_text) and len(f.params) >= 2:
                suggestions.append("@ensures result >= 0  # (subtraction pattern)")
            if suggestions:
                self._add(ContractFinding.SEV_INFO, "suggestion",
                           f"Suggested contracts for '{f.name}': "
                           f"{'; '.join(suggestions)}",
                           func_name=f.name, line=f.start_line,
                           ctx={"suggestions": suggestions})

    # -- Proactive Recommendations -----------------------------------------

    def _proactive_recommendations(self):
        total = len(self.functions)
        if total == 0:
            return
        covered = sum(1 for f in self.functions if f.has_contracts)
        pct = (covered / total) * 100
        crits = sum(1 for f in self.findings
                    if f.severity == ContractFinding.SEV_CRITICAL)
        if pct < 50:
            self._add(ContractFinding.SEV_WARN, "recommendation",
                       f"Contract coverage is low ({pct:.0f}%). "
                       f"Consider adding @requires/@ensures to critical "
                       f"functions first. Run with --suggest for ideas.")
        if crits > 0:
            self._add(ContractFinding.SEV_CRITICAL, "recommendation",
                       f"{crits} critical violation(s) detected. "
                       f"Review immediately — these indicate functions "
                       f"that may not satisfy their guarantees.")
        # Suggest invariants for loops
        for f in self.functions:
            if not f.invariants:
                for bl in f.body_lines:
                    if re.match(r"\s*(while|for)\b", bl):
                        self._add(ContractFinding.SEV_INFO, "recommendation",
                                   f"'{f.name}' has loops but no "
                                   f"@invariant annotations. Consider "
                                   f"adding loop invariants.",
                                   func_name=f.name)
                        break


# ---------------------------------------------------------------------------
# Reporter — Terminal
# ---------------------------------------------------------------------------

from _termcolors import colors as _make_colors, ansi as _ansi

# Severity → ANSI code mapping (replaces inline _COLORS dict)
_SEV_CODES = {"info": "36", "warn": "33", "critical": "31"}


def _sev_color(text, severity):
    """Wrap text in severity-appropriate ANSI color."""
    return _ansi(_SEV_CODES.get(severity, ""), text)


def print_findings(findings, functions):
    """Pretty-print findings to terminal."""
    total_f = len(functions)
    covered = sum(1 for f in functions if f.has_contracts)
    tc = _make_colors()

    print(f"\n{tc.bold('╔══════════════════════════════════════════╗')}")
    print(f"{tc.bold('║     sauravcontract — Contract Verifier    ║')}")
    print(f"{tc.bold('╚══════════════════════════════════════════╝')}\n")

    if total_f > 0:
        pct = (covered / total_f) * 100
        bar_len = 30
        filled = int(bar_len * pct / 100)
        bar = "█" * filled + "░" * (bar_len - filled)
        sev = "info" if pct >= 75 else ("warn" if pct >= 50 else "critical")
        print(f"  Coverage: {_sev_color(f'{bar} {pct:.0f}%', sev)}  "
              f"({covered}/{total_f} functions)\n")

    sev_counts = {"info": 0, "warn": 0, "critical": 0}
    for f in findings:
        sev_counts[f.severity] = sev_counts.get(f.severity, 0) + 1

    for f in findings:
        sev = f.severity.upper()
        loc = f"  [line {f.line}]" if f.line else ""
        fn = f"  ({f.func_name})" if f.func_name else ""
        print(f"  {_sev_color(f'{sev:8s}', f.severity)}  [{f.category}]{fn}{loc}")
        print(f"           {f.message}")
        if f.context.get("suggestions"):
            for s in f.context["suggestions"]:
                print(f"           {tc.dim(f'  → # {s}')}")
        print()

    crit = sev_counts['critical']
    warn = sev_counts['warn']
    info = sev_counts['info']
    print(f"  {tc.dim('Summary:')} "
          f"{_sev_color(f'{crit} critical', 'critical')}  "
          f"{_sev_color(f'{warn} warnings', 'warn')}  "
          f"{_sev_color(f'{info} info', 'info')}\n")


# ---------------------------------------------------------------------------
# Reporter — HTML
# ---------------------------------------------------------------------------

def generate_html_report(findings, functions, filename):
    """Generate an interactive HTML contract report."""
    total = len(functions)
    covered = sum(1 for f in functions if f.has_contracts)
    pct = (covered / total * 100) if total > 0 else 0
    crits = sum(1 for f in findings if f.severity == "critical")
    warns = sum(1 for f in findings if f.severity == "warn")
    infos = sum(1 for f in findings if f.severity == "info")

    func_cards = ""
    for f in functions:
        contracts_html = ""
        for c in f.contracts:
            badge = {"requires": "🔒", "ensures": "✅", "invariant": "🔄"}.get(c.kind, "")
            contracts_html += (f'<div class="contract-badge {c.kind}">'
                              f'{badge} @{c.kind} {c.expression}</div>')
        if not f.contracts:
            contracts_html = '<div class="no-contracts">No contracts</div>'
        status_class = "has-contracts" if f.has_contracts else "no-contracts-card"
        func_cards += f'''
        <div class="func-card {status_class}">
            <h3>{f.name}({", ".join(f.params)})</h3>
            <div class="meta">Lines {f.start_line}–{f.end_line}
            {' | Calls: ' + ', '.join(f.calls) if f.calls else ''}</div>
            {contracts_html}
        </div>'''

    findings_html = ""
    for f in findings:
        fn = f" — {f.func_name}" if f.func_name else ""
        loc = f" [line {f.line}]" if f.line else ""
        findings_html += (f'<div class="finding {f.severity}">'
                         f'<span class="sev">{f.severity.upper()}</span> '
                         f'<span class="cat">[{f.category}]{fn}{loc}</span>'
                         f'<p>{f.message}</p></div>')

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Contract Report — {filename}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:system-ui,-apple-system,sans-serif;background:#0a0a0a;color:#e0e0e0;padding:2rem}}
h1{{text-align:center;margin-bottom:.5rem;color:#7dd3fc}}
.subtitle{{text-align:center;color:#888;margin-bottom:2rem}}
.gauge{{text-align:center;margin:1.5rem 0}}
.gauge-bar{{display:inline-block;width:400px;height:24px;background:#222;border-radius:12px;overflow:hidden}}
.gauge-fill{{height:100%;border-radius:12px;transition:width .5s}}
.gauge-label{{margin-top:.5rem;font-size:1.2rem;font-weight:bold}}
.stats{{display:flex;justify-content:center;gap:2rem;margin:1.5rem 0}}
.stat{{text-align:center;padding:1rem;background:#111;border-radius:8px;min-width:120px}}
.stat .num{{font-size:2rem;font-weight:bold}}
.stat.critical .num{{color:#f87171}}
.stat.warn .num{{color:#fbbf24}}
.stat.info .num{{color:#7dd3fc}}
.func-cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:1rem;margin:2rem 0}}
.func-card{{background:#111;border:1px solid #333;border-radius:8px;padding:1rem}}
.func-card.has-contracts{{border-color:#22c55e44}}
.func-card.no-contracts-card{{border-color:#f8717144}}
.func-card h3{{color:#93c5fd;margin-bottom:.5rem}}
.func-card .meta{{font-size:.8rem;color:#666;margin-bottom:.5rem}}
.contract-badge{{display:inline-block;padding:2px 8px;margin:2px;border-radius:4px;font-size:.85rem}}
.contract-badge.requires{{background:#7c3aed22;color:#a78bfa}}
.contract-badge.ensures{{background:#22c55e22;color:#86efac}}
.contract-badge.invariant{{background:#0ea5e922;color:#7dd3fc}}
.no-contracts{{color:#f87171;font-size:.85rem}}
.findings{{margin:2rem 0}}
.finding{{padding:.75rem 1rem;margin:.5rem 0;border-radius:6px;border-left:4px solid}}
.finding.critical{{background:#f8717111;border-color:#f87171}}
.finding.warn{{background:#fbbf2411;border-color:#fbbf24}}
.finding.info{{background:#7dd3fc11;border-color:#7dd3fc}}
.finding .sev{{font-weight:bold;font-size:.8rem;text-transform:uppercase}}
.finding.critical .sev{{color:#f87171}}
.finding.warn .sev{{color:#fbbf24}}
.finding.info .sev{{color:#7dd3fc}}
.finding .cat{{color:#888;font-size:.85rem;margin-left:.5rem}}
.finding p{{margin-top:.3rem}}
h2{{margin:2rem 0 1rem;color:#93c5fd}}
</style></head><body>
<h1>📜 Contract Verification Report</h1>
<div class="subtitle">{filename} — {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
<div class="gauge">
<div class="gauge-bar"><div class="gauge-fill" style="width:{pct}%;background:{'#22c55e' if pct >= 75 else '#fbbf24' if pct >= 50 else '#f87171'}"></div></div>
<div class="gauge-label" style="color:{'#22c55e' if pct >= 75 else '#fbbf24' if pct >= 50 else '#f87171'}">{pct:.0f}% Contract Coverage</div>
</div>
<div class="stats">
<div class="stat critical"><div class="num">{crits}</div><div>Critical</div></div>
<div class="stat warn"><div class="num">{warns}</div><div>Warnings</div></div>
<div class="stat info"><div class="num">{infos}</div><div>Info</div></div>
</div>
<h2>Functions</h2>
<div class="func-cards">{func_cards}</div>
<h2>Findings</h2>
<div class="findings">{findings_html}</div>
</body></html>"""

    report_path = filename.rsplit(".", 1)[0] + "_contracts.html"
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return report_path


# ---------------------------------------------------------------------------
# Watch Mode
# ---------------------------------------------------------------------------

def file_hash(path):
    """Get SHA-256 of file for change detection."""
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def watch_loop(filepath, config):
    """Re-analyze on file change."""
    print(f"  👁  Watching {filepath} for changes (Ctrl+C to stop)\n")
    last_hash = None
    try:
        while True:
            h = file_hash(filepath)
            if h != last_hash:
                last_hash = h
                run_analysis(filepath, config)
                print(f"\n  👁  Watching... (last change: "
                      f"{datetime.now().strftime('%H:%M:%S')})\n")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n  Stopped watching.")


# ---------------------------------------------------------------------------
# Main Analysis
# ---------------------------------------------------------------------------

def run_analysis(filepath, config):
    """Run contract analysis on a single file."""
    with open(filepath, "r", encoding="utf-8") as f:
        source = f.read()

    functions = parse_srv(source)
    analyzer = ContractAnalyzer(functions, config)
    findings = analyzer.analyze()

    if config.json_output:
        output = {
            "file": filepath,
            "timestamp": datetime.now().isoformat(),
            "functions": [f.to_dict() for f in functions],
            "findings": [f.to_dict() for f in findings],
        }
        print(json.dumps(output, indent=2))
    elif config.coverage_only:
        total = len(functions)
        covered = sum(1 for f in functions if f.has_contracts)
        pct = (covered / total * 100) if total > 0 else 0
        print(f"Contract coverage: {covered}/{total} ({pct:.0f}%)")
        for f in functions:
            status = "✅" if f.has_contracts else "❌"
            nc = len(f.contracts)
            print(f"  {status} {f.name}  ({nc} contract{'s' if nc != 1 else ''})")
    else:
        print_findings(findings, functions)

    if config.report:
        rpath = generate_html_report(findings, functions, filepath)
        print(f"  📄 HTML report: {rpath}")

    # Strict mode exit
    if config.strict:
        crits = sum(1 for f in findings
                    if f.severity == ContractFinding.SEV_CRITICAL)
        if crits > 0:
            sys.exit(1)

    return findings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="sauravcontract — Design-by-Contract verifier for "
                    "sauravcode (.srv files)")
    parser.add_argument("file", help="Path to .srv file")
    parser.add_argument("--report", action="store_true",
                        help="Generate HTML contract report")
    parser.add_argument("--json", dest="json_output", action="store_true",
                        help="Output findings as JSON")
    parser.add_argument("--watch", action="store_true",
                        help="Re-analyze on file change")
    parser.add_argument("--strict", action="store_true",
                        help="Exit with code 1 on any critical violation")
    parser.add_argument("--suggest", action="store_true",
                        help="Auto-suggest contracts for unannotated functions")
    parser.add_argument("--coverage", dest="coverage_only",
                        action="store_true",
                        help="Show contract coverage summary only")
    parser.add_argument("--blame", action="store_true",
                        help="Enable blame analysis for violations")
    args = parser.parse_args()

    if not os.path.isfile(args.file):
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    config = ContractConfig(
        report=args.report,
        json_output=args.json_output,
        watch=args.watch,
        strict=args.strict,
        suggest=args.suggest,
        coverage_only=args.coverage_only,
        blame=args.blame,
    )

    if config.watch:
        watch_loop(args.file, config)
    else:
        run_analysis(args.file, config)


if __name__ == "__main__":
    main()
