#!/usr/bin/env python3
"""sauravintent — Autonomous Intent Inference Engine for sauravcode.

Analyzes .srv source code and infers programmer intent from naming
conventions, code structure, and patterns.  Detects mismatches between
what the code *appears* to want to do and what it *actually* does, then
suggests corrections.

Usage:
    python sauravintent.py <file.srv>                 Analyze intent
    python sauravintent.py <file.srv> --json          JSON output
    python sauravintent.py <file.srv> --report        HTML report
    python sauravintent.py <file.srv> --watch         Auto-analyze on change
    python sauravintent.py <dir>                      Analyze all .srv files
    python sauravintent.py <file.srv> --confidence 0.6  Min confidence threshold
"""

import sys, os, re, json, time, math
from pathlib import Path
from datetime import datetime
from collections import Counter, defaultdict

# Pre-compiled regexes for function/variable extraction
_FUNC_DEF_RE = re.compile(r'^function\s+(\w+)\s*\((.*?)\)')
_BLOCK_OPEN_RE = re.compile(r'^(function|if|for|while|class|match)\b')
_VAR_ASSIGN_RE = re.compile(r'^\s*(\w+)\s*=\s*(.+)')

# ── Intent Categories ──────────────────────────────────────────────

INTENT_CATEGORIES = {
    "accumulation": {
        "desc": "Collecting or summing values",
        "name_patterns": [r"total", r"sum", r"count", r"accum", r"tally", r"running"],
        "body_signals": ["+=", "append", "push"],
    },
    "search": {
        "desc": "Finding a specific element",
        "name_patterns": [r"find", r"search", r"lookup", r"locate", r"index_of", r"contains"],
        "body_signals": ["==", "break", "return"],
    },
    "filter": {
        "desc": "Selecting items matching criteria",
        "name_patterns": [r"filter", r"select", r"keep", r"reject", r"remove", r"exclude"],
        "body_signals": ["if", "append", "push"],
    },
    "transform": {
        "desc": "Converting data from one form to another",
        "name_patterns": [r"map", r"transform", r"convert", r"to_", r"parse", r"format"],
        "body_signals": ["append", "push", "return"],
    },
    "sort": {
        "desc": "Ordering elements",
        "name_patterns": [r"sort", r"order", r"rank", r"arrange"],
        "body_signals": [">", "<", "swap", "sort"],
    },
    "validation": {
        "desc": "Checking correctness of input",
        "name_patterns": [r"valid", r"check", r"verify", r"is_", r"has_", r"can_"],
        "body_signals": ["if", "return", "true", "false"],
    },
    "io": {
        "desc": "Input/output operations",
        "name_patterns": [r"read", r"write", r"load", r"save", r"print", r"log", r"display"],
        "body_signals": ["print", "write", "read", "open"],
    },
    "initialization": {
        "desc": "Setting up initial state",
        "name_patterns": [r"init", r"setup", r"create", r"new", r"reset", r"default"],
        "body_signals": ["=", "[]", "{}"],
    },
    "aggregation": {
        "desc": "Computing summary statistics",
        "name_patterns": [r"avg", r"average", r"mean", r"max", r"min", r"median", r"stats"],
        "body_signals": ["/", "len", "max", "min", "sum"],
    },
    "guard": {
        "desc": "Early exit or precondition checking",
        "name_patterns": [r"guard", r"ensure", r"require", r"assert", r"bail"],
        "body_signals": ["if", "return", "raise", "error"],
    },
}

# ── Mismatch Rules ─────────────────────────────────────────────────

class IntentMismatch:
    """A detected mismatch between inferred intent and actual code."""
    __slots__ = ("kind", "line", "name", "inferred_intent", "issue",
                 "suggestion", "confidence")

    def __init__(self, kind, line, name, inferred_intent, issue, suggestion, confidence):
        self.kind = kind
        self.line = line
        self.name = name
        self.inferred_intent = inferred_intent
        self.issue = issue
        self.suggestion = suggestion
        self.confidence = confidence

    def to_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}


# ── Code Analyzer ──────────────────────────────────────────────────

class IntentAnalyzer:
    """Analyzes sauravcode source for intent-implementation mismatches."""

    def __init__(self, source, filename="<unknown>"):
        self.source = source
        self.filename = filename
        self.lines = source.splitlines()
        self.functions = self._extract_functions()
        self.variables = self._extract_variables()
        self.mismatches = []

    def _extract_functions(self):
        """Extract function definitions with their bodies."""
        funcs = []
        i = 0
        while i < len(self.lines):
            m = _FUNC_DEF_RE.match(self.lines[i])
            if m:
                name, params = m.group(1), m.group(2)
                start = i
                depth = 1
                body_lines = []
                i += 1
                while i < len(self.lines) and depth > 0:
                    s = self.lines[i].strip()
                    if s in ("end",) and depth == 1:
                        depth -= 1
                    else:
                        if _BLOCK_OPEN_RE.match(s):
                            depth += 1
                        if s == "end":
                            depth -= 1
                        body_lines.append(self.lines[i])
                    i += 1
                funcs.append({
                    "name": name,
                    "params": [p.strip() for p in params.split(",") if p.strip()],
                    "body": "\n".join(body_lines),
                    "body_lines": body_lines,
                    "start_line": start + 1,
                    "length": len(body_lines),
                })
            else:
                i += 1
        return funcs

    def _extract_variables(self):
        """Extract variable assignments with context."""
        variables = []
        for i, line in enumerate(self.lines):
            m = _VAR_ASSIGN_RE.match(line)
            if m:
                variables.append({
                    "name": m.group(1),
                    "value_expr": m.group(2).strip(),
                    "line": i + 1,
                })
        return variables

    def _infer_intent(self, name):
        """Infer intent category from a name. Returns (category, confidence)."""
        name_lower = name.lower()
        scores = {}
        for cat, info in INTENT_CATEGORIES.items():
            score = 0
            for pat in info["name_patterns"]:
                if re.search(pat, name_lower):
                    score += 1
            if score > 0:
                scores[cat] = score
        if not scores:
            return None, 0.0
        best = max(scores, key=scores.get)
        confidence = min(1.0, scores[best] * 0.5)
        return best, confidence

    def _check_body_signals(self, body, expected_cat):
        """Check how many expected body signals are present."""
        signals = INTENT_CATEGORIES[expected_cat]["body_signals"]
        found = sum(1 for s in signals if s in body)
        return found / max(len(signals), 1)

    def analyze(self):
        """Run all mismatch detectors."""
        self.mismatches = []
        self._check_function_intents()
        self._check_variable_naming()
        self._check_boolean_functions()
        self._check_unused_accumulation()
        self._check_search_without_return()
        self._check_sort_stability()
        return self.mismatches

    def _check_function_intents(self):
        """Check if function bodies match their name-implied intent."""
        for func in self.functions:
            cat, conf = self._infer_intent(func["name"])
            if cat and conf >= 0.4:
                signal_score = self._check_body_signals(func["body"], cat)
                if signal_score < 0.3:
                    self.mismatches.append(IntentMismatch(
                        kind="intent_body_mismatch",
                        line=func["start_line"],
                        name=func["name"],
                        inferred_intent=cat,
                        issue=f"Function name suggests '{cat}' ({INTENT_CATEGORIES[cat]['desc']}), "
                              f"but body lacks typical signals (score: {signal_score:.0%})",
                        suggestion=f"Review function body — expected patterns like: "
                                   f"{', '.join(INTENT_CATEGORIES[cat]['body_signals'])}",
                        confidence=conf * 0.8,
                    ))

    def _check_variable_naming(self):
        """Check variables whose names imply a collection but aren't."""
        plural_pats = [r"s$", r"list$", r"items$", r"array$", r"set$", r"collection$"]
        for var in self.variables:
            name_lower = var["name"].lower()
            is_plural = any(re.search(p, name_lower) for p in plural_pats)
            if is_plural:
                expr = var["value_expr"]
                looks_scalar = re.match(r'^(\d+|".*"|true|false|none)$', expr, re.I)
                if looks_scalar:
                    self.mismatches.append(IntentMismatch(
                        kind="naming_type_mismatch",
                        line=var["line"],
                        name=var["name"],
                        inferred_intent="collection",
                        issue=f"Variable '{var['name']}' looks plural/collection-like "
                              f"but is assigned a scalar value: {expr}",
                        suggestion=f"Rename to singular form or assign a collection (e.g., [{expr}])",
                        confidence=0.7,
                    ))

    def _check_boolean_functions(self):
        """Functions named is_/has_/can_ should return booleans."""
        for func in self.functions:
            if re.match(r'^(is_|has_|can_|should_)', func["name"]):
                body = func["body"]
                has_bool_return = bool(re.search(r'\breturn\s+(true|false)\b', body, re.I))
                has_any_return = "return" in body
                if has_any_return and not has_bool_return:
                    self.mismatches.append(IntentMismatch(
                        kind="boolean_return_mismatch",
                        line=func["start_line"],
                        name=func["name"],
                        inferred_intent="validation",
                        issue=f"Function '{func['name']}' implies boolean result "
                              f"but doesn't return true/false",
                        suggestion="Return true/false explicitly to match naming convention",
                        confidence=0.85,
                    ))

    def _check_unused_accumulation(self):
        """Variables named total/sum/count that are never used after assignment."""
        accum_pats = [r"total", r"sum", r"count", r"tally"]
        for var in self.variables:
            name_lower = var["name"].lower()
            if any(re.search(p, name_lower) for p in accum_pats):
                # Check if var is used after its line
                used_after = False
                for j in range(var["line"], len(self.lines)):
                    later = self.lines[j]
                    if re.search(r'\b' + re.escape(var["name"]) + r'\b', later):
                        # Exclude the assignment itself
                        if j + 1 != var["line"]:
                            used_after = True
                            break
                if not used_after:
                    self.mismatches.append(IntentMismatch(
                        kind="unused_accumulator",
                        line=var["line"],
                        name=var["name"],
                        inferred_intent="accumulation",
                        issue=f"Accumulator '{var['name']}' is assigned but never used afterward",
                        suggestion="Use the accumulated value (print, return, or pass it on)",
                        confidence=0.75,
                    ))

    def _check_search_without_return(self):
        """Functions named find/search that don't return anything."""
        for func in self.functions:
            if re.match(r'^(find|search|lookup|locate)', func["name"].lower()):
                if "return" not in func["body"]:
                    self.mismatches.append(IntentMismatch(
                        kind="search_no_return",
                        line=func["start_line"],
                        name=func["name"],
                        inferred_intent="search",
                        issue=f"Search function '{func['name']}' doesn't return a result",
                        suggestion="Add a return statement to give back the found element (or none)",
                        confidence=0.8,
                    ))

    def _check_sort_stability(self):
        """Functions named sort that use simple comparison without stable sort."""
        for func in self.functions:
            if "sort" in func["name"].lower():
                body = func["body"]
                if "swap" in body and "==" not in body:
                    self.mismatches.append(IntentMismatch(
                        kind="unstable_sort_hint",
                        line=func["start_line"],
                        name=func["name"],
                        inferred_intent="sort",
                        issue=f"Sort function '{func['name']}' uses swaps without "
                              f"equality checks — may not be stable",
                        suggestion="Consider using <= instead of < for stable sort behavior",
                        confidence=0.5,
                    ))


# ── Output Formatters ──────────────────────────────────────────────

def _severity_label(confidence):
    if confidence >= 0.8:
        return "HIGH"
    if confidence >= 0.6:
        return "MEDIUM"
    return "LOW"

def _severity_color(confidence):
    if confidence >= 0.8:
        return "#e74c3c"
    if confidence >= 0.6:
        return "#f39c12"
    return "#3498db"

def _p(text=""):
    """Print with fallback for non-UTF-8 terminals."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"))


def print_report(filename, mismatches):
    """Print a colorful terminal report."""
    _p(f"\n{'=' * 60}")
    _p(f"  INTENT ANALYSIS -- {filename}")
    _p(f"{'=' * 60}")

    if not mismatches:
        _p("\n  [OK] No intent mismatches detected!")
        _p("     Code appears to do what its names suggest.\n")
        return

    _p(f"\n  Found {len(mismatches)} potential intent mismatch(es):\n")

    for i, m in enumerate(mismatches, 1):
        sev = _severity_label(m.confidence)
        icon = {"HIGH": "[!]", "MEDIUM": "[~]", "LOW": "[.]"}[sev]
        _p(f"  {icon} [{sev}] Line {m.line}: {m.name}")
        _p(f"     Intent: {m.inferred_intent} -- {INTENT_CATEGORIES.get(m.inferred_intent, {}).get('desc', '')}")
        _p(f"     Issue:  {m.issue}")
        _p(f"     Fix:    {m.suggestion}")
        _p(f"     Confidence: {m.confidence:.0%}")
        _p()

    # Summary
    by_sev = Counter(_severity_label(m.confidence) for m in mismatches)
    _p(f"  {'-' * 50}")
    parts = []
    for s in ("HIGH", "MEDIUM", "LOW"):
        if by_sev[s]:
            parts.append(f"{by_sev[s]} {s}")
    _p(f"  Summary: {', '.join(parts)}")
    _p()


def to_json(filename, mismatches):
    """Return JSON-serializable result."""
    return {
        "file": filename,
        "timestamp": datetime.now().isoformat(),
        "mismatches": [m.to_dict() for m in mismatches],
        "stats": {
            "total": len(mismatches),
            "high": sum(1 for m in mismatches if m.confidence >= 0.8),
            "medium": sum(1 for m in mismatches if 0.6 <= m.confidence < 0.8),
            "low": sum(1 for m in mismatches if m.confidence < 0.6),
        },
    }


def generate_html_report(filename, mismatches):
    """Generate an interactive HTML report."""
    items_html = ""
    if not mismatches:
        items_html = '<div class="ok">✅ No intent mismatches detected!</div>'
    else:
        for m in mismatches:
            sev = _severity_label(m.confidence)
            color = _severity_color(m.confidence)
            cat_desc = INTENT_CATEGORIES.get(m.inferred_intent, {}).get("desc", "")
            items_html += f"""
            <div class="card" style="border-left: 4px solid {color};">
                <div class="header">
                    <span class="sev" style="background:{color};">{sev}</span>
                    <span class="name">{m.name}</span>
                    <span class="line">line {m.line}</span>
                    <span class="conf">{m.confidence:.0%}</span>
                </div>
                <div class="intent">🎯 Intent: <strong>{m.inferred_intent}</strong> — {cat_desc}</div>
                <div class="issue">⚠️ {m.issue}</div>
                <div class="fix">💡 {m.suggestion}</div>
            </div>"""

    stats = {"total": len(mismatches),
             "high": sum(1 for m in mismatches if m.confidence >= 0.8),
             "medium": sum(1 for m in mismatches if 0.6 <= m.confidence < 0.8),
             "low": sum(1 for m in mismatches if m.confidence < 0.6)}

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Intent Analysis — {filename}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:system-ui,sans-serif;background:#0d1117;color:#c9d1d9;padding:24px;max-width:800px;margin:0 auto}}
h1{{font-size:1.6rem;margin-bottom:8px}}
.sub{{color:#8b949e;margin-bottom:20px}}
.stats{{display:flex;gap:12px;margin-bottom:24px}}
.stat{{background:#161b22;padding:12px 18px;border-radius:8px;text-align:center}}
.stat .n{{font-size:1.8rem;font-weight:700}} .stat .l{{font-size:.75rem;color:#8b949e}}
.card{{background:#161b22;border-radius:8px;padding:16px;margin-bottom:12px}}
.card .header{{display:flex;align-items:center;gap:10px;margin-bottom:8px}}
.sev{{color:#fff;padding:2px 8px;border-radius:4px;font-size:.75rem;font-weight:700}}
.name{{font-weight:600;font-size:1rem}} .line{{color:#8b949e;font-size:.8rem}} .conf{{margin-left:auto;color:#8b949e;font-size:.8rem}}
.intent,.issue,.fix{{margin:4px 0;font-size:.9rem}}
.fix{{color:#58a6ff}}
.ok{{background:#161b22;border-radius:8px;padding:24px;text-align:center;font-size:1.1rem}}
.filter{{margin-bottom:16px}}
.filter button{{background:#21262d;color:#c9d1d9;border:1px solid #30363d;padding:6px 14px;border-radius:6px;cursor:pointer;margin-right:6px}}
.filter button.active{{background:#388bfd;border-color:#388bfd;color:#fff}}
</style></head><body>
<h1>🧠 Intent Analysis</h1>
<div class="sub">{filename} — {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
<div class="stats">
    <div class="stat"><div class="n">{stats['total']}</div><div class="l">Total</div></div>
    <div class="stat"><div class="n" style="color:#e74c3c">{stats['high']}</div><div class="l">High</div></div>
    <div class="stat"><div class="n" style="color:#f39c12">{stats['medium']}</div><div class="l">Medium</div></div>
    <div class="stat"><div class="n" style="color:#3498db">{stats['low']}</div><div class="l">Low</div></div>
</div>
<div class="filter">
    <button class="active" onclick="filt('all')">All</button>
    <button onclick="filt('HIGH')">🔴 High</button>
    <button onclick="filt('MEDIUM')">🟡 Medium</button>
    <button onclick="filt('LOW')">🔵 Low</button>
</div>
<div id="cards">{items_html}</div>
<script>
function filt(level){{
    document.querySelectorAll('.filter button').forEach(b=>b.classList.remove('active'));
    event.target.classList.add('active');
    document.querySelectorAll('.card').forEach(c=>{{
        if(level==='all'){{c.style.display='';return;}}
        const sev=c.querySelector('.sev').textContent;
        c.style.display=sev===level?'':'none';
    }});
}}
</script>
</body></html>"""


# ── Watch Mode ─────────────────────────────────────────────────────

def watch_file(filepath, min_conf):
    """Watch a file for changes and re-analyze."""
    print(f"👁️  Watching {filepath} (Ctrl+C to stop)...")
    last_mtime = 0
    while True:
        try:
            mtime = os.path.getmtime(filepath)
            if mtime != last_mtime:
                last_mtime = mtime
                with open(filepath, "r", encoding="utf-8") as f:
                    source = f.read()
                analyzer = IntentAnalyzer(source, filepath)
                results = analyzer.analyze()
                filtered = [m for m in results if m.confidence >= min_conf]
                os.system("cls" if os.name == "nt" else "clear")
                print_report(filepath, filtered)
                print(f"  [Watching... last update {datetime.now().strftime('%H:%M:%S')}]")
            time.sleep(1)
        except KeyboardInterrupt:
            print("\n  Stopped watching.")
            break
        except Exception as e:
            print(f"  Error: {e}")
            time.sleep(2)


# ── Multi-file ─────────────────────────────────────────────────────

def analyze_directory(dirpath, min_conf):
    """Analyze all .srv files in a directory."""
    srv_files = sorted(Path(dirpath).rglob("*.srv"))
    if not srv_files:
        print(f"No .srv files found in {dirpath}")
        return

    all_mismatches = {}
    total = 0
    for fp in srv_files:
        with open(fp, "r", encoding="utf-8") as f:
            source = f.read()
        analyzer = IntentAnalyzer(source, str(fp))
        results = analyzer.analyze()
        filtered = [m for m in results if m.confidence >= min_conf]
        if filtered:
            all_mismatches[str(fp)] = filtered
            total += len(filtered)

    _p(f"\n{'=' * 60}")
    _p(f"  INTENT ANALYSIS -- {dirpath} ({len(srv_files)} files)")
    _p(f"{'=' * 60}")
    _p(f"\n  {total} mismatch(es) across {len(all_mismatches)} file(s)\n")

    for fp, mm in all_mismatches.items():
        _p(f"  {fp} ({len(mm)} issues)")
        for m in mm:
            sev = _severity_label(m.confidence)
            icon = {"HIGH": "[!]", "MEDIUM": "[~]", "LOW": "[.]"}[sev]
            _p(f"     {icon} L{m.line} {m.name}: {m.issue}")
        _p()


# ── CLI ────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="🧠 sauravintent — Autonomous intent inference for sauravcode")
    parser.add_argument("target", help="File or directory to analyze")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--report", action="store_true", help="Generate HTML report")
    parser.add_argument("--watch", action="store_true", help="Watch mode")
    parser.add_argument("--confidence", type=float, default=0.4,
                        help="Min confidence threshold (0.0–1.0, default 0.4)")

    args = parser.parse_args()
    target = args.target
    min_conf = args.confidence

    if os.path.isdir(target):
        analyze_directory(target, min_conf)
        return

    if not os.path.isfile(target):
        print(f"Error: {target} not found")
        sys.exit(1)

    if args.watch:
        watch_file(target, min_conf)
        return

    with open(target, "r", encoding="utf-8") as f:
        source = f.read()

    analyzer = IntentAnalyzer(source, target)
    results = analyzer.analyze()
    filtered = [m for m in results if m.confidence >= min_conf]

    if args.json:
        print(json.dumps(to_json(target, filtered), indent=2))
    elif args.report:
        out = target.rsplit(".", 1)[0] + "_intent.html"
        html = generate_html_report(target, filtered)
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Report saved to {out}")
    else:
        print_report(target, filtered)


if __name__ == "__main__":
    main()
