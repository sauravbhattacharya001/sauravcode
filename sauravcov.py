#!/usr/bin/env python3
"""
sauravcov.py - Code coverage tool for sauravcode programs.

Tracks which lines of .srv source files are executed and generates
coverage reports in text, JSON, or HTML format.

Uses the LineTrackingParser from sauravdb to annotate AST nodes with
source line numbers, then wraps the interpreter to record execution.

Usage:
    python sauravcov.py program.srv                 # Text coverage report
    python sauravcov.py program.srv --html report.html  # HTML report
    python sauravcov.py program.srv --json           # JSON output
    python sauravcov.py program.srv --show-missing   # Show uncovered lines
    python sauravcov.py program.srv --min-coverage 80  # Fail if < 80%
    python sauravcov.py program.srv --branch         # Include branch coverage
"""

import sys
import os
import json as _json
import argparse
import html as _html
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from saurav import (
    tokenize, Parser, Interpreter, ASTNode,
    IfNode, WhileNode, ForNode, ForEachNode, TryCatchNode,
    MatchNode, FunctionNode, ReturnSignal, BreakSignal, ContinueSignal,
    MAX_LOOP_ITERATIONS,
)
from sauravdb import LineTrackingParser


class CoverageData:
    """Stores coverage information for a single source file."""

    def __init__(self, filename, source_lines):
        self.filename = filename
        self.source_lines = source_lines
        self.executable_lines = set()
        self.executed_lines = set()
        self.branches = defaultdict(lambda: defaultdict(int))
        self.branch_total = 0
        self.branch_taken = 0

    @property
    def total_executable(self):
        return len(self.executable_lines)

    @property
    def total_executed(self):
        return len(self.executed_lines & self.executable_lines)

    @property
    def coverage_percent(self):
        if self.total_executable == 0:
            return 100.0
        return (self.total_executed / self.total_executable) * 100.0

    @property
    def missing_lines(self):
        return sorted(self.executable_lines - self.executed_lines)

    def missing_ranges(self):
        """Return missing lines as compact ranges like '5-8, 12, 15-20'."""
        missing = self.missing_lines
        if not missing:
            return ""
        ranges = []
        start = missing[0]
        end = missing[0]
        for line in missing[1:]:
            if line == end + 1:
                end = line
            else:
                ranges.append(f"{start}" if start == end else f"{start}-{end}")
                start = end = line
        ranges.append(f"{start}" if start == end else f"{start}-{end}")
        return ", ".join(ranges)

    def branch_coverage_percent(self):
        if self.branch_total == 0:
            return 100.0
        return (self.branch_taken / self.branch_total) * 100.0


def _find_executable_lines(source_code):
    """Determine which lines contain executable code (not blank/comment-only)."""
    executable = set()
    for i, line in enumerate(source_code.splitlines(), 1):
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            executable.add(i)
    return executable


def _collect_node_lines(nodes, lines=None):
    """Recursively collect all line numbers from AST nodes."""
    if lines is None:
        lines = set()
    for node in nodes:
        if not isinstance(node, ASTNode):
            continue
        if node.line_num is not None:
            lines.add(node.line_num)
        if isinstance(node, IfNode):
            _collect_node_lines(node.body, lines)
            for _, elif_body in node.elif_chains:
                _collect_node_lines(elif_body, lines)
            if node.else_body:
                _collect_node_lines(node.else_body, lines)
        elif isinstance(node, (WhileNode, ForNode, ForEachNode)):
            _collect_node_lines(node.body, lines)
        elif isinstance(node, TryCatchNode):
            _collect_node_lines(node.body, lines)
            _collect_node_lines(node.handler, lines)
            if hasattr(node, 'finally_body') and node.finally_body:
                _collect_node_lines(node.finally_body, lines)
        elif isinstance(node, FunctionNode):
            _collect_node_lines(node.body, lines)
        elif isinstance(node, MatchNode):
            for _, case_body in node.cases:
                _collect_node_lines(case_body, lines)
    return lines


class CoverageInterpreter(Interpreter):
    """Interpreter subclass that tracks line-level and branch coverage."""

    def __init__(self, coverage_data, track_branches=False):
        super().__init__()
        self.coverage = coverage_data
        self.track_branches = track_branches

    def _record_line(self, node):
        if isinstance(node, ASTNode) and node.line_num is not None:
            self.coverage.executed_lines.add(node.line_num)

    def interpret(self, ast):
        self._record_line(ast)
        return super().interpret(ast)

    def execute_if(self, node):
        self._record_line(node)
        condition = self.evaluate(node.condition)
        if self.track_branches and node.line_num:
            line = node.line_num
            self.coverage.branch_total += 2  # true + false branches
            if self._is_truthy(condition):
                self.coverage.branches[line]["true"] += 1
                self.coverage.branch_taken += 1
            else:
                self.coverage.branches[line]["false"] += 1
                self.coverage.branch_taken += 1

        if self._is_truthy(condition):
            self.execute_body(node.body)
            return
        for i, (elif_cond, elif_body) in enumerate(node.elif_chains):
            if self._is_truthy(self.evaluate(elif_cond)):
                self.execute_body(elif_body)
                return
        if node.else_body:
            self.execute_body(node.else_body)

    def execute_while(self, node):
        self._record_line(node)
        iterations = 0
        entered = False
        while self._is_truthy(self.evaluate(node.condition)):
            if not entered and self.track_branches and node.line_num:
                self.coverage.branches[node.line_num]["enter"] += 1
                self.coverage.branch_total += 1
                self.coverage.branch_taken += 1
                entered = True
            iterations += 1
            if iterations > MAX_LOOP_ITERATIONS:
                raise RuntimeError(
                    f"Maximum loop iterations ({MAX_LOOP_ITERATIONS:,}) exceeded"
                )
            try:
                self.execute_body(node.body)
            except BreakSignal:
                break
            except ContinueSignal:
                continue
        if not entered and self.track_branches and node.line_num:
            self.coverage.branches[node.line_num]["skip"] += 1
            self.coverage.branch_total += 1

    def execute_body(self, body):
        for stmt in body:
            self._record_line(stmt)
            self.interpret(stmt)


def run_with_coverage(filename, source_code, track_branches=False):
    """Run a .srv file and collect coverage data."""
    source_lines = source_code.splitlines()
    coverage = CoverageData(filename, source_lines)
    coverage.executable_lines = _find_executable_lines(source_code)

    tokens = tokenize(source_code)
    parser = LineTrackingParser(tokens)
    ast_nodes = parser.parse()

    interp = CoverageInterpreter(coverage, track_branches=track_branches)
    interp._source_dir = os.path.dirname(os.path.abspath(filename))

    try:
        for node in ast_nodes:
            interp.interpret(node)
    except SystemExit:
        pass
    except ReturnSignal:
        pass
    except Exception as e:
        coverage.runtime_error = str(e)

    return coverage


def format_text_report(coverages, show_missing=False):
    """Format coverage results as a text table."""
    lines = []
    if show_missing:
        sep = "-" * 90
        header = f"{'File':<30} {'Stmts':>6} {'Miss':>6} {'Cover':>7}   {'Missing'}"
    else:
        sep = "-" * 70
        header = f"{'File':<30} {'Stmts':>6} {'Miss':>6} {'Cover':>7}"
    lines.append(sep)
    lines.append(header)
    lines.append(sep)

    total_stmts = 0
    total_miss = 0

    for cov in coverages:
        stmts = cov.total_executable
        miss = stmts - cov.total_executed
        pct = cov.coverage_percent
        name = os.path.basename(cov.filename)
        total_stmts += stmts
        total_miss += miss

        if show_missing:
            missing = cov.missing_ranges()
            lines.append(f"{name:<30} {stmts:>6} {miss:>6} {pct:>6.1f}%   {missing}")
        else:
            lines.append(f"{name:<30} {stmts:>6} {miss:>6} {pct:>6.1f}%")

    lines.append(sep)
    total_pct = (((total_stmts - total_miss) / total_stmts) * 100.0) if total_stmts > 0 else 100.0
    if show_missing:
        lines.append(f"{'TOTAL':<30} {total_stmts:>6} {total_miss:>6} {total_pct:>6.1f}%")
    else:
        lines.append(f"{'TOTAL':<30} {total_stmts:>6} {total_miss:>6} {total_pct:>6.1f}%")
    lines.append(sep)
    return "\n".join(lines)


def format_json_report(coverages):
    """Format coverage results as JSON."""
    result = {"files": {}, "totals": {}}
    total_stmts = 0
    total_executed = 0

    for cov in coverages:
        name = cov.filename
        stmts = cov.total_executable
        executed = cov.total_executed
        total_stmts += stmts
        total_executed += executed

        file_data = {
            "executable_lines": sorted(cov.executable_lines),
            "executed_lines": sorted(cov.executed_lines & cov.executable_lines),
            "missing_lines": cov.missing_lines,
            "num_statements": stmts,
            "num_executed": executed,
            "num_missing": stmts - executed,
            "coverage_percent": round(cov.coverage_percent, 2),
        }
        if hasattr(cov, 'runtime_error'):
            file_data["runtime_error"] = cov.runtime_error
        if cov.branch_total > 0:
            file_data["branch_coverage_percent"] = round(cov.branch_coverage_percent(), 2)
            file_data["branches_total"] = cov.branch_total
            file_data["branches_taken"] = cov.branch_taken
        result["files"][name] = file_data

    total_pct = ((total_executed / total_stmts) * 100.0) if total_stmts > 0 else 100.0
    result["totals"] = {
        "num_statements": total_stmts,
        "num_executed": total_executed,
        "num_missing": total_stmts - total_executed,
        "coverage_percent": round(total_pct, 2),
    }
    return _json.dumps(result, indent=2)


def format_html_report(coverages):
    """Generate an HTML coverage report with annotated source."""
    parts = []
    parts.append("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>sauravcode Coverage Report</title>
<style>
body { font-family: 'Segoe UI', Tahoma, sans-serif; margin: 0; padding: 20px; background: #1a1a2e; color: #e0e0e0; }
h1 { color: #e94560; }
h2 { color: #0f3460; background: #16213e; padding: 8px 12px; border-radius: 4px; }
table { border-collapse: collapse; width: 100%; margin-bottom: 24px; }
th, td { padding: 6px 12px; text-align: left; border-bottom: 1px solid #16213e; }
th { background: #16213e; color: #e94560; }
.pct-high { color: #4ecca3; font-weight: bold; }
.pct-mid { color: #f0a500; font-weight: bold; }
.pct-low { color: #e94560; font-weight: bold; }
.source { margin: 16px 0; }
.source pre { margin: 0; padding: 0; }
.line { display: block; padding: 1px 8px; font-family: 'Consolas', 'Courier New', monospace; font-size: 13px; white-space: pre; }
.line-num { display: inline-block; width: 40px; text-align: right; margin-right: 12px; color: #555; user-select: none; }
.hit { background: rgba(78, 204, 163, 0.15); }
.miss { background: rgba(233, 69, 96, 0.2); }
.no-code { }
.summary-bar { height: 8px; border-radius: 4px; background: #333; margin: 4px 0; overflow: hidden; }
.summary-fill { height: 100%; border-radius: 4px; }
</style>
</head>
<body>
<h1>&#x1F4CA; sauravcode Coverage Report</h1>
""")

    parts.append("<table><tr><th>File</th><th>Stmts</th><th>Miss</th><th>Cover</th><th></th></tr>")
    total_stmts = 0
    total_miss = 0
    for cov in coverages:
        stmts = cov.total_executable
        miss = stmts - cov.total_executed
        pct = cov.coverage_percent
        total_stmts += stmts
        total_miss += miss
        pct_class = "pct-high" if pct >= 80 else ("pct-mid" if pct >= 50 else "pct-low")
        bar_color = "#4ecca3" if pct >= 80 else ("#f0a500" if pct >= 50 else "#e94560")
        name = _html.escape(os.path.basename(cov.filename))
        parts.append(f'<tr><td><a href="#{name}" style="color:#e0e0e0">{name}</a></td>'
                      f'<td>{stmts}</td><td>{miss}</td>'
                      f'<td class="{pct_class}">{pct:.1f}%</td>'
                      f'<td style="width:100px"><div class="summary-bar">'
                      f'<div class="summary-fill" style="width:{pct:.0f}%;background:{bar_color}"></div>'
                      f'</div></td></tr>')
    total_pct = (((total_stmts - total_miss) / total_stmts) * 100.0) if total_stmts > 0 else 100.0
    pct_class = "pct-high" if total_pct >= 80 else ("pct-mid" if total_pct >= 50 else "pct-low")
    parts.append(f'<tr style="font-weight:bold"><td>TOTAL</td><td>{total_stmts}</td>'
                  f'<td>{total_miss}</td><td class="{pct_class}">{total_pct:.1f}%</td><td></td></tr>')
    parts.append("</table>")

    for cov in coverages:
        name = _html.escape(os.path.basename(cov.filename))
        pct = cov.coverage_percent
        parts.append(f'<h2 id="{name}">{name} ({pct:.1f}%)</h2>')
        parts.append('<div class="source"><pre>')
        for i, line in enumerate(cov.source_lines, 1):
            escaped = _html.escape(line)
            if i in cov.executable_lines:
                if i in cov.executed_lines:
                    cls = "hit"
                    marker = "&#x2713;"
                else:
                    cls = "miss"
                    marker = "&#x2717;"
            else:
                cls = "no-code"
                marker = " "
            parts.append(f'<span class="line {cls}">'
                          f'<span class="line-num">{i}</span>{marker} {escaped}</span>')
        parts.append('</pre></div>')

    parts.append("</body></html>")
    return "\n".join(parts)


def merge_coverage(existing_json, new_coverages):
    """Merge new coverage data into existing JSON coverage data."""
    if existing_json is None:
        existing_json = {"files": {}, "totals": {}}

    for cov in new_coverages:
        name = cov.filename
        if name in existing_json["files"]:
            prev = existing_json["files"][name]
            prev_executed = set(prev.get("executed_lines", []))
            prev_executed |= (cov.executed_lines & cov.executable_lines)
            all_exec = set(prev.get("executable_lines", []))
            all_exec |= cov.executable_lines
            stmts = len(all_exec)
            executed = len(prev_executed & all_exec)
            existing_json["files"][name] = {
                "executable_lines": sorted(all_exec),
                "executed_lines": sorted(prev_executed & all_exec),
                "missing_lines": sorted(all_exec - prev_executed),
                "num_statements": stmts,
                "num_executed": executed,
                "num_missing": stmts - executed,
                "coverage_percent": round((executed / stmts * 100) if stmts > 0 else 100, 2),
            }
        else:
            stmts = cov.total_executable
            executed = cov.total_executed
            existing_json["files"][name] = {
                "executable_lines": sorted(cov.executable_lines),
                "executed_lines": sorted(cov.executed_lines & cov.executable_lines),
                "missing_lines": cov.missing_lines,
                "num_statements": stmts,
                "num_executed": executed,
                "num_missing": stmts - executed,
                "coverage_percent": round(cov.coverage_percent, 2),
            }

    ts = te = 0
    for f in existing_json["files"].values():
        ts += f["num_statements"]
        te += f["num_executed"]
    existing_json["totals"] = {
        "num_statements": ts,
        "num_executed": te,
        "num_missing": ts - te,
        "coverage_percent": round((te / ts * 100) if ts > 0 else 100, 2),
    }
    return existing_json


def collect_srv_files(paths):
    """Collect .srv files from a list of paths (files or directories)."""
    result = []
    for p in paths:
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                for f in files:
                    if f.endswith('.srv'):
                        result.append(os.path.join(root, f))
        elif p.endswith('.srv'):
            result.append(p)
    return sorted(set(result))


def main():
    """CLI entry point for sauravcov."""
    ap = argparse.ArgumentParser(
        description="Code coverage tool for sauravcode programs.",
        epilog="Examples:\n"
               "  python sauravcov.py tests/test.srv\n"
               "  python sauravcov.py tests/ --show-missing\n"
               "  python sauravcov.py prog.srv --html coverage.html\n"
               "  python sauravcov.py prog.srv --json\n"
               "  python sauravcov.py prog.srv --min-coverage 80\n"
               "  python sauravcov.py a.srv b.srv --merge coverage.json\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("files", nargs="+", help=".srv files or directories to run")
    ap.add_argument("--show-missing", "-m", action="store_true",
                     help="Show missing line ranges in text report")
    ap.add_argument("--json", "-j", action="store_true",
                     help="Output JSON report instead of text")
    ap.add_argument("--html", metavar="FILE",
                     help="Generate HTML coverage report")
    ap.add_argument("--branch", "-b", action="store_true",
                     help="Track branch coverage (if/while)")
    ap.add_argument("--min-coverage", type=float, default=None,
                     metavar="PCT", help="Fail if total coverage below PCT%%")
    ap.add_argument("--merge", metavar="FILE",
                     help="Merge results into existing JSON coverage file")
    ap.add_argument("--quiet", "-q", action="store_true",
                     help="Suppress program stdout during execution")

    args = ap.parse_args()

    srv_files = collect_srv_files(args.files)
    if not srv_files:
        print("No .srv files found.", file=sys.stderr)
        sys.exit(1)

    coverages = []
    errors = []

    for filepath in srv_files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                source = f.read()
        except (IOError, OSError) as e:
            errors.append(f"Error reading {filepath}: {e}")
            continue

        if args.quiet:
            old_stdout = sys.stdout
            sys.stdout = open(os.devnull, 'w')

        try:
            cov = run_with_coverage(filepath, source, track_branches=args.branch)
            coverages.append(cov)
            if hasattr(cov, 'runtime_error'):
                errors.append(f"Runtime error in {filepath}: {cov.runtime_error}")
        except Exception as e:
            errors.append(f"Error running {filepath}: {e}")
        finally:
            if args.quiet:
                sys.stdout.close()
                sys.stdout = old_stdout

    if not coverages:
        for err in errors:
            print(err, file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(format_json_report(coverages))
    elif args.html:
        html_content = format_html_report(coverages)
        with open(args.html, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"HTML coverage report written to {args.html}")
        print(format_text_report(coverages, show_missing=args.show_missing))
    else:
        print(format_text_report(coverages, show_missing=args.show_missing))

    if args.merge:
        existing = None
        if os.path.exists(args.merge):
            try:
                with open(args.merge, 'r') as f:
                    existing = _json.load(f)
            except Exception:
                existing = None
        merged = merge_coverage(existing, coverages)
        with open(args.merge, 'w') as f:
            _json.dump(merged, f, indent=2)
        print(f"Merged coverage data saved to {args.merge}")

    for err in errors:
        print(f"WARNING: {err}", file=sys.stderr)

    total_stmts = sum(c.total_executable for c in coverages)
    total_exec = sum(c.total_executed for c in coverages)
    total_pct = ((total_exec / total_stmts) * 100.0) if total_stmts > 0 else 100.0

    if args.min_coverage is not None and total_pct < args.min_coverage:
        print(f"\nFAIL: Total coverage {total_pct:.1f}% is below minimum {args.min_coverage}%",
              file=sys.stderr)
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
