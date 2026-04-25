"""sauravbounty — Autonomous Bug Bounty Hunter for sauravcode.

Scans .srv source files for potential bugs using pattern-based static
analysis, assigns severity levels and bounty values, and generates
actionable reports with auto-triage and fix prioritization.

Bug categories detected:
  - Unchecked division (division without zero guards)
  - Unused variables (assigned but never read)
  - Infinite loop risk (while true / loop without break)
  - Empty catch blocks (catch with no meaningful handler)
  - Hardcoded secrets (API keys, passwords, tokens)
  - Unreachable code (statements after return)
  - Large functions (exceeding 50 lines)
  - Magic numbers (raw numeric literals outside set)

Usage:
    python sauravbounty.py <file_or_dir> [options]

Options:
    --min-severity LEVEL  Filter minimum severity (default: info)
    --format FORMAT       Output format: text, json, html (default: text)
    --watch               Re-scan on file changes (autonomous monitoring)
    --leaderboard         Show cumulative bounty stats per category
    --auto-triage         Group related bugs, suggest fix priority
    -o FILE               Write report to file
"""

import sys
import os
import re
import json
import time
import argparse
from datetime import datetime
from collections import defaultdict

# Ensure stdout handles Unicode on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower().replace('-', '') != 'utf8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ---------------------------------------------------------------------------
# Severity & Bounty
# ---------------------------------------------------------------------------

SEVERITIES = ["critical", "high", "medium", "low", "info"]
SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITIES)}
BOUNTY_TABLE = {"critical": 500, "high": 200, "medium": 100, "low": 50, "info": 10}

# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------

class Finding:
    """A single bug bounty finding."""

    def __init__(self, category, severity, line, description, suggestion, snippet=""):
        self.category = category
        self.severity = severity
        self.bounty = BOUNTY_TABLE.get(severity, 0)
        self.line = line
        self.description = description
        self.suggestion = suggestion
        self.snippet = snippet

    def to_dict(self):
        return {
            "category": self.category,
            "severity": self.severity,
            "bounty": self.bounty,
            "line": self.line,
            "description": self.description,
            "suggestion": self.suggestion,
            "snippet": self.snippet,
        }

# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------

def detect_unchecked_division(lines):
    """Find division without zero-check guards."""
    findings = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        if re.search(r'[^/]/[^/=]', stripped) or re.search(r'\s/\s', stripped):
            # Check if previous lines have a zero guard
            context = "\n".join(l.strip() for l in lines[max(0, i - 4):i - 1])
            if not re.search(r'(!=\s*0|== 0|is not 0|zero|divide.*check)', context, re.I):
                findings.append(Finding(
                    "Unchecked Division", "high", i,
                    "Division operation without visible zero-check guard",
                    "Add a zero-check before dividing: if divisor != 0",
                    stripped
                ))
    return findings


def detect_unused_variables(lines):
    """Find variables assigned via 'set' but never referenced afterward."""
    findings = []
    assignments = {}
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*set\s+(\w+)\s*=', line)
        if m:
            varname = m.group(1)
            assignments[varname] = i

    for varname, lineno in assignments.items():
        used = False
        for i, line in enumerate(lines, 1):
            if i == lineno:
                continue
            if re.search(r'\b' + re.escape(varname) + r'\b', line):
                used = True
                break
        if not used:
            findings.append(Finding(
                "Unused Variable", "low", lineno,
                f"Variable '{varname}' is assigned but never used",
                f"Remove unused variable '{varname}' or use it",
                lines[lineno - 1].strip()
            ))
    return findings


def detect_infinite_loops(lines):
    """Find while-true / loop constructs without break."""
    findings = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if re.match(r'(while\s+true|loop)\b', stripped, re.I):
            # Scan forward for break within reasonable range
            indent = len(line) - len(line.lstrip())
            has_break = False
            for j in range(i, min(i + 100, len(lines))):
                jline = lines[j]
                jindent = len(jline) - len(jline.lstrip())
                if jline.strip() and jindent <= indent and j > i:
                    break
                if re.search(r'\bbreak\b', jline):
                    has_break = True
                    break
            if not has_break:
                findings.append(Finding(
                    "Infinite Loop Risk", "critical", i,
                    "Loop without visible break condition — may run forever",
                    "Add a break condition or use a bounded loop",
                    stripped
                ))
    return findings


def detect_empty_catch(lines):
    """Find catch blocks with no meaningful body."""
    findings = []
    for i, line in enumerate(lines, 1):
        if re.match(r'\s*catch\b', line.strip()):
            # Check next few lines for content
            body_lines = []
            for j in range(i, min(i + 5, len(lines))):
                nxt = lines[j].strip()
                if nxt and nxt not in ("end", "pass", "}", ""):
                    body_lines.append(nxt)
            if not body_lines:
                findings.append(Finding(
                    "Empty Catch Block", "medium", i,
                    "Catch block with no error handling — errors silently swallowed",
                    "Add error logging or re-raise the exception",
                    line.strip()
                ))
    return findings


def detect_hardcoded_secrets(lines):
    """Find strings that look like secrets."""
    findings = []
    secret_patterns = [
        (r'(?i)(api[_-]?key|secret|token|password|passwd|pwd)\s*=\s*["\']', "Hardcoded credential"),
        (r'["\'][A-Za-z0-9+/]{32,}={0,2}["\']', "Base64-encoded secret candidate"),
        (r'sk-[a-zA-Z0-9]{20,}', "OpenAI-style API key"),
    ]
    for i, line in enumerate(lines, 1):
        for pat, desc in secret_patterns:
            if re.search(pat, line):
                findings.append(Finding(
                    "Hardcoded Secret", "critical", i,
                    desc,
                    "Move secrets to environment variables or a config file",
                    line.strip()[:80]
                ))
                break
    return findings


def detect_unreachable_code(lines):
    """Find code after return statements in the same block."""
    findings = []
    for i, line in enumerate(lines, 1):
        if re.match(r'\s*return\b', line):
            indent = len(line) - len(line.lstrip())
            if i < len(lines):
                nxt = lines[i]
                nxt_indent = len(nxt) - len(nxt.lstrip())
                if nxt.strip() and nxt_indent >= indent and not re.match(r'\s*(end|else|catch|finally)\b', nxt):
                    findings.append(Finding(
                        "Unreachable Code", "medium", i + 1,
                        "Code after return statement is unreachable",
                        "Remove unreachable code or restructure logic",
                        nxt.strip()
                    ))
    return findings


def detect_large_functions(lines):
    """Find functions exceeding 50 lines."""
    findings = []
    func_start = None
    func_name = None
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*fun\s+(\w+)', line)
        if m:
            if func_start and func_name:
                size = i - func_start
                if size > 50:
                    findings.append(Finding(
                        "Large Function", "low", func_start,
                        f"Function '{func_name}' is {size} lines — consider splitting",
                        "Break into smaller helper functions",
                        f"fun {func_name} (...)"
                    ))
            func_start = i
            func_name = m.group(1)
    # Check last function
    if func_start and func_name:
        size = len(lines) - func_start + 1
        if size > 50:
            findings.append(Finding(
                "Large Function", "low", func_start,
                f"Function '{func_name}' is {size} lines — consider splitting",
                "Break into smaller helper functions",
                f"fun {func_name} (...)"
            ))
    return findings


def detect_magic_numbers(lines):
    """Find raw numeric literals outside set assignments."""
    findings = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        if re.match(r'\s*set\s+', line):
            continue
        # Remove string literals before checking for magic numbers
        no_strings = re.sub(r'"[^"]*"|' + r"'[^']*'", '', stripped)
        nums = re.findall(r'\b(\d+\.?\d*)\b', no_strings)
        for n in nums:
            try:
                val = float(n)
            except ValueError:
                continue
            if val not in (0, 1, -1, 2, 10, 100):
                findings.append(Finding(
                    "Magic Number", "info", i,
                    f"Magic number {n} — consider using a named constant",
                    f"Replace with: set MEANINGFUL_NAME = {n}",
                    stripped
                ))
                break  # One per line
    return findings


ALL_DETECTORS = [
    detect_unchecked_division,
    detect_unused_variables,
    detect_infinite_loops,
    detect_empty_catch,
    detect_hardcoded_secrets,
    detect_unreachable_code,
    detect_large_functions,
    detect_magic_numbers,
]

# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

def scan_file(filepath):
    """Scan a single .srv file and return findings."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except (IOError, OSError) as e:
        return [Finding("Scanner Error", "info", 0, str(e), "Check file permissions")]

    all_findings = []
    for detector in ALL_DETECTORS:
        try:
            all_findings.extend(detector(lines))
        except Exception:
            pass
    return all_findings


def scan_path(path):
    """Scan a file or directory, returning {filepath: [findings]}."""
    results = {}
    if os.path.isfile(path):
        if path.endswith(".srv"):
            results[path] = scan_file(path)
    elif os.path.isdir(path):
        for root, _dirs, files in os.walk(path):
            for fn in sorted(files):
                if fn.endswith(".srv"):
                    fp = os.path.join(root, fn)
                    results[fp] = scan_file(fp)
    return results

# ---------------------------------------------------------------------------
# Auto-Triage
# ---------------------------------------------------------------------------

def auto_triage(results):
    """Group findings by area and suggest fix priority."""
    all_findings = []
    for fp, findings in results.items():
        for f in findings:
            all_findings.append((fp, f))

    if not all_findings:
        return []

    # Sort by severity then by file
    all_findings.sort(key=lambda x: (SEVERITY_RANK.get(x[1].severity, 99), x[0], x[1].line))

    groups = defaultdict(list)
    for fp, f in all_findings:
        groups[f.category].append((fp, f))

    triage = []
    for cat, items in sorted(groups.items(), key=lambda x: sum(i[1].bounty for i in x[1]), reverse=True):
        total_bounty = sum(i[1].bounty for i in items)
        worst = min(items, key=lambda x: SEVERITY_RANK.get(x[1].severity, 99))
        triage.append({
            "category": cat,
            "count": len(items),
            "total_bounty": total_bounty,
            "worst_severity": worst[1].severity,
            "priority": "FIX NOW" if worst[1].severity in ("critical", "high") else "FIX SOON" if worst[1].severity == "medium" else "BACKLOG",
            "files": list(set(fp for fp, _ in items)),
        })
    return triage

# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

def build_leaderboard(results):
    """Build bounty stats per category."""
    stats = defaultdict(lambda: {"count": 0, "bounty": 0, "worst": "info"})
    for _fp, findings in results.items():
        for f in findings:
            s = stats[f.category]
            s["count"] += 1
            s["bounty"] += f.bounty
            if SEVERITY_RANK.get(f.severity, 99) < SEVERITY_RANK.get(s["worst"], 99):
                s["worst"] = f.severity
    rows = sorted(stats.items(), key=lambda x: x[1]["bounty"], reverse=True)
    return rows

# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

SEVERITY_ICONS = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵", "info": "⚪"}


def format_text(results, min_sev, show_leaderboard, show_triage):
    """Plain text report."""
    out = []
    out.append("=" * 60)
    out.append("  🏴‍☠️  SAURAVCODE BUG BOUNTY REPORT")
    out.append(f"  Scanned: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    out.append("=" * 60)

    total_bounty = 0
    total_findings = 0
    min_rank = SEVERITY_RANK.get(min_sev, 4)

    for fp, findings in sorted(results.items()):
        filtered = [f for f in findings if SEVERITY_RANK.get(f.severity, 99) <= min_rank]
        if not filtered:
            continue
        out.append(f"\n📄 {fp}")
        out.append("-" * 50)
        for f in sorted(filtered, key=lambda x: (SEVERITY_RANK.get(x.severity, 99), x.line)):
            icon = SEVERITY_ICONS.get(f.severity, "?")
            out.append(f"  {icon} L{f.line}: [{f.severity.upper()}] {f.category}")
            out.append(f"     {f.description}")
            out.append(f"     💡 {f.suggestion}")
            out.append(f"     💰 ${f.bounty}")
            total_bounty += f.bounty
            total_findings += 1

    out.append("\n" + "=" * 60)
    out.append(f"  TOTAL: {total_findings} findings | 💰 ${total_bounty} bounty")
    out.append("=" * 60)

    if show_leaderboard:
        lb = build_leaderboard(results)
        out.append("\n🏆 BOUNTY LEADERBOARD")
        out.append("-" * 50)
        out.append(f"  {'Category':<25} {'Count':>5} {'Bounty':>8} {'Worst':>10}")
        out.append("  " + "-" * 48)
        for cat, s in lb:
            out.append(f"  {cat:<25} {s['count']:>5} ${s['bounty']:>6} {s['worst']:>10}")

    if show_triage:
        triage = auto_triage(results)
        out.append("\n🎯 AUTO-TRIAGE PRIORITY")
        out.append("-" * 50)
        for t in triage:
            out.append(f"  [{t['priority']}] {t['category']} — {t['count']} issues, ${t['total_bounty']} bounty")
            out.append(f"    Worst: {t['worst_severity']} | Files: {', '.join(os.path.basename(f) for f in t['files'][:5])}")

    return "\n".join(out)


def format_json(results, min_sev, show_leaderboard, show_triage):
    """JSON report."""
    min_rank = SEVERITY_RANK.get(min_sev, 4)
    report = {
        "timestamp": datetime.now().isoformat(),
        "files": {},
        "summary": {"total_findings": 0, "total_bounty": 0},
    }
    for fp, findings in results.items():
        filtered = [f.to_dict() for f in findings if SEVERITY_RANK.get(f.severity, 99) <= min_rank]
        if filtered:
            report["files"][fp] = filtered
            report["summary"]["total_findings"] += len(filtered)
            report["summary"]["total_bounty"] += sum(f["bounty"] for f in filtered)

    if show_leaderboard:
        report["leaderboard"] = [{"category": c, **s} for c, s in build_leaderboard(results)]
    if show_triage:
        report["triage"] = auto_triage(results)

    return json.dumps(report, indent=2)


def format_html(results, min_sev, show_leaderboard, show_triage):
    """Interactive HTML report."""
    min_rank = SEVERITY_RANK.get(min_sev, 4)

    total_bounty = 0
    total_findings = 0
    file_sections = []

    sev_colors = {"critical": "#e74c3c", "high": "#e67e22", "medium": "#f1c40f", "low": "#3498db", "info": "#95a5a6"}

    for fp, findings in sorted(results.items()):
        filtered = [f for f in findings if SEVERITY_RANK.get(f.severity, 99) <= min_rank]
        if not filtered:
            continue
        rows = ""
        for f in sorted(filtered, key=lambda x: (SEVERITY_RANK.get(x.severity, 99), x.line)):
            color = sev_colors.get(f.severity, "#999")
            rows += f"""<tr>
              <td style="color:{color};font-weight:bold">{f.severity.upper()}</td>
              <td>{f.line}</td><td>{f.category}</td>
              <td>{f.description}</td><td>{f.suggestion}</td>
              <td>${f.bounty}</td></tr>"""
            total_bounty += f.bounty
            total_findings += 1
        file_sections.append(f"""<h3>📄 {os.path.basename(fp)}</h3>
        <table><tr><th>Severity</th><th>Line</th><th>Category</th><th>Description</th><th>Fix</th><th>Bounty</th></tr>{rows}</table>""")

    lb_html = ""
    if show_leaderboard:
        lb_rows = ""
        for cat, s in build_leaderboard(results):
            lb_rows += f"<tr><td>{cat}</td><td>{s['count']}</td><td>${s['bounty']}</td><td>{s['worst']}</td></tr>"
        lb_html = f"""<h2>🏆 Bounty Leaderboard</h2>
        <table><tr><th>Category</th><th>Count</th><th>Bounty</th><th>Worst</th></tr>{lb_rows}</table>"""

    triage_html = ""
    if show_triage:
        triage = auto_triage(results)
        t_rows = ""
        for t in triage:
            p_color = "#e74c3c" if t["priority"] == "FIX NOW" else "#e67e22" if t["priority"] == "FIX SOON" else "#3498db"
            t_rows += f"""<tr><td style="color:{p_color};font-weight:bold">{t['priority']}</td>
            <td>{t['category']}</td><td>{t['count']}</td><td>${t['total_bounty']}</td><td>{t['worst_severity']}</td></tr>"""
        triage_html = f"""<h2>🎯 Auto-Triage Priority</h2>
        <table><tr><th>Priority</th><th>Category</th><th>Count</th><th>Bounty</th><th>Worst</th></tr>{t_rows}</table>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Bug Bounty Report</title>
<style>
  body {{ background: #1a1a2e; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; padding: 2rem; margin: 0; }}
  h1 {{ color: #e94560; }} h2 {{ color: #0f3460; background: #e94560; padding: 0.5rem 1rem; border-radius: 4px; }}
  h3 {{ color: #16213e; background: #e94560; padding: 0.3rem 0.8rem; border-radius: 4px; display: inline-block; }}
  table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; }}
  th {{ background: #16213e; padding: 0.6rem; text-align: left; }}
  td {{ padding: 0.5rem; border-bottom: 1px solid #333; }}
  tr:hover {{ background: #16213e; }}
  .summary {{ background: #16213e; padding: 1.5rem; border-radius: 8px; margin: 1rem 0; display: flex; gap: 2rem; }}
  .stat {{ text-align: center; }} .stat .num {{ font-size: 2rem; color: #e94560; font-weight: bold; }}
</style></head><body>
<h1>🏴‍☠️ Sauravcode Bug Bounty Report</h1>
<p>Scanned: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
<div class="summary">
  <div class="stat"><div class="num">{total_findings}</div>Findings</div>
  <div class="stat"><div class="num">${total_bounty}</div>Total Bounty</div>
  <div class="stat"><div class="num">{len(results)}</div>Files Scanned</div>
</div>
{''.join(file_sections)}
{lb_html}
{triage_html}
</body></html>"""

# ---------------------------------------------------------------------------
# Watch Mode
# ---------------------------------------------------------------------------

def watch_mode(path, min_sev, fmt, show_lb, show_triage, output):
    """Re-scan on file changes."""
    print(f"👁️  Watching {path} for changes... (Ctrl+C to stop)")
    mtimes = {}

    def get_mtimes():
        m = {}
        if os.path.isfile(path) and path.endswith(".srv"):
            m[path] = os.stat(path).st_mtime
        elif os.path.isdir(path):
            for root, _, files in os.walk(path):
                for fn in files:
                    if fn.endswith(".srv"):
                        fp = os.path.join(root, fn)
                        m[fp] = os.stat(fp).st_mtime
        return m

    mtimes = get_mtimes()
    while True:
        time.sleep(1)
        new_mtimes = get_mtimes()
        if new_mtimes != mtimes:
            changed = [f for f in new_mtimes if new_mtimes.get(f) != mtimes.get(f)]
            print(f"\n🔄 Changes detected in: {', '.join(os.path.basename(f) for f in changed)}")
            mtimes = new_mtimes
            results = scan_path(path)
            report = format_report(results, min_sev, fmt, show_lb, show_triage)
            if output:
                with open(output, "w", encoding="utf-8") as f:
                    f.write(report)
                print(f"📝 Report written to {output}")
            else:
                print(report)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def format_report(results, min_sev, fmt, show_lb, show_triage):
    if fmt == "json":
        return format_json(results, min_sev, show_lb, show_triage)
    elif fmt == "html":
        return format_html(results, min_sev, show_lb, show_triage)
    else:
        return format_text(results, min_sev, show_lb, show_triage)


def main():
    parser = argparse.ArgumentParser(
        description="🏴‍☠️ sauravbounty — Autonomous Bug Bounty Hunter for sauravcode"
    )
    parser.add_argument("path", help="File or directory to scan")
    parser.add_argument("--min-severity", default="info",
                        choices=SEVERITIES, help="Minimum severity to report")
    parser.add_argument("--format", default="text", choices=["text", "json", "html"],
                        dest="fmt", help="Output format")
    parser.add_argument("--watch", action="store_true",
                        help="Re-scan on file changes (autonomous monitoring)")
    parser.add_argument("--leaderboard", action="store_true",
                        help="Show bounty stats per category")
    parser.add_argument("--auto-triage", action="store_true",
                        help="Auto-triage: group bugs, suggest fix priority")
    parser.add_argument("-o", "--output", help="Write report to file")

    args = parser.parse_args()

    if not os.path.exists(args.path):
        print(f"❌ Path not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    if args.watch:
        watch_mode(args.path, args.min_severity, args.fmt,
                   args.leaderboard, args.auto_triage, args.output)
    else:
        results = scan_path(args.path)
        report = format_report(results, args.min_severity, args.fmt,
                               args.leaderboard, args.auto_triage)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"📝 Report written to {args.output}")
        else:
            print(report)


if __name__ == "__main__":
    main()
