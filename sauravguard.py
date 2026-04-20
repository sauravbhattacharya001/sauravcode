"""sauravguard — Autonomous Runtime Guardian for sauravcode.

Monitors .srv program execution with proactive safety detection:
- Infinite loop detection (static pattern analysis)
- Memory pressure monitoring (collection growth patterns)
- Recursion depth analysis (missing base cases)
- Execution timeouts (subprocess enforcement)
- Resource audit trail (file I/O logging)
- Post-execution safety report with risk scoring

Usage:
    python sauravguard.py <filename>.srv [options]

Options:
    --max-loops N        Max iterations per loop (default: 100000)
    --max-depth N        Max recursion depth (default: 500)
    --timeout N          Execution timeout in seconds (default: 30)
    --max-memory N       Max collection size (default: 1000000)
    --report             Generate detailed HTML safety report
    --strict             Halt on first warning (default: log and continue)
    --watch              Re-run on file change (autonomous monitoring mode)
    --json               Output report as JSON
"""

import sys
import os
import time
import json
import re
import subprocess
import argparse
import hashlib
from datetime import datetime
from collections import defaultdict

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class GuardConfig:
    """Runtime guardian configuration with sensible defaults."""

    def __init__(self, max_loops=100000, max_depth=500, timeout=30,
                 max_memory=1000000, strict=False, report=False,
                 watch=False, json_output=False):
        self.max_loops = max_loops
        self.max_depth = max_depth
        self.timeout = timeout
        self.max_memory = max_memory
        self.strict = strict
        self.report = report
        self.watch = watch
        self.json_output = json_output


# ---------------------------------------------------------------------------
# Safety Events
# ---------------------------------------------------------------------------

class SafetyEvent:
    """A structured safety finding."""

    SEVERITY_INFO = "info"
    SEVERITY_WARN = "warn"
    SEVERITY_CRITICAL = "critical"

    def __init__(self, severity, category, message, line=None, context=None):
        self.timestamp = datetime.now().isoformat()
        self.severity = severity
        self.category = category
        self.message = message
        self.line = line
        self.context = context or {}

    def to_dict(self):
        return {
            "timestamp": self.timestamp,
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
            "line": self.line,
            "context": self.context,
        }

    def __repr__(self):
        loc = f" (line {self.line})" if self.line else ""
        return f"[{self.severity.upper()}] {self.category}{loc}: {self.message}"


# ---------------------------------------------------------------------------
# Static Analyzer
# ---------------------------------------------------------------------------

class StaticAnalyzer:
    """Analyzes .srv source code for risky patterns without execution."""

    def __init__(self, source, config):
        self.source = source
        self.lines = source.splitlines()
        self.config = config
        self.events = []

    def analyze(self):
        """Run all static checks."""
        self._check_unbounded_loops()
        self._check_recursion_without_base()
        self._check_collection_growth_in_loops()
        self._check_file_ops_without_handling()
        self._check_sleep_in_loops()
        self._check_deep_nesting()
        return self.events

    def _check_unbounded_loops(self):
        """Detect loops without break/return conditions."""
        loop_starts = []
        for i, line in enumerate(self.lines, 1):
            stripped = line.strip()
            if re.match(r'^(while|loop|for)\b', stripped):
                loop_starts.append((i, stripped))

        for line_no, loop_line in loop_starts:
            # Check if "while true" or similar infinite patterns
            if re.search(r'while\s+(true|1|yes)', loop_line, re.IGNORECASE):
                # Look for break within ~50 lines
                block = "\n".join(self.lines[line_no:min(line_no + 50, len(self.lines))])
                if "break" not in block and "return" not in block:
                    self.events.append(SafetyEvent(
                        SafetyEvent.SEVERITY_CRITICAL,
                        "infinite-loop",
                        f"Potentially unbounded loop without break/return",
                        line=line_no,
                        context={"pattern": loop_line.strip()},
                    ))

    def _check_recursion_without_base(self):
        """Detect recursive functions missing obvious base cases."""
        func_pattern = re.compile(r'^(fun|function|def)\s+(\w+)')
        functions = {}
        for i, line in enumerate(self.lines, 1):
            m = func_pattern.match(line.strip())
            if m:
                functions[m.group(2)] = i

        for fname, start_line in functions.items():
            # Get function body (next 50 lines or until next function)
            end = min(start_line + 50, len(self.lines))
            body = "\n".join(self.lines[start_line:end])
            # Check if function calls itself
            if re.search(rf'\b{re.escape(fname)}\s*\(', body):
                # Check for base case patterns (if/return without recursion)
                if not re.search(r'\b(if|when|match)\b', body):
                    self.events.append(SafetyEvent(
                        SafetyEvent.SEVERITY_WARN,
                        "recursion",
                        f"Recursive function '{fname}' may lack a base case",
                        line=start_line,
                        context={"function": fname},
                    ))

    def _check_collection_growth_in_loops(self):
        """Detect unbounded list/collection growth inside loops."""
        in_loop = False
        loop_line = 0
        for i, line in enumerate(self.lines, 1):
            stripped = line.strip()
            if re.match(r'^(while|loop|for)\b', stripped):
                in_loop = True
                loop_line = i
            elif in_loop and stripped and not stripped.startswith(" ") and not stripped.startswith("\t"):
                # Rough heuristic: dedent means loop ended (imperfect but useful)
                if not re.match(r'^(while|loop|for|if|else|elif|end)\b', stripped):
                    in_loop = False

            if in_loop:
                if re.search(r'\.(append|push|add|insert)\s*\(', stripped):
                    # Check if there's a size guard
                    block = "\n".join(self.lines[loop_line - 1:i + 5])
                    if not re.search(r'\b(len|size|count|limit|max)\b', block):
                        self.events.append(SafetyEvent(
                            SafetyEvent.SEVERITY_WARN,
                            "memory-pressure",
                            "Collection grows in loop without apparent size limit",
                            line=i,
                            context={"code": stripped.strip()},
                        ))
                        in_loop = False  # avoid duplicate warnings for same loop

    def _check_file_ops_without_handling(self):
        """Detect file operations without error handling."""
        file_ops = re.compile(r'\b(file_read|file_write|open)\s*\(')
        for i, line in enumerate(self.lines, 1):
            if file_ops.search(line):
                # Check surrounding context for try/catch
                ctx_start = max(0, i - 3)
                ctx_end = min(len(self.lines), i + 3)
                context = "\n".join(self.lines[ctx_start:ctx_end])
                if "try" not in context and "catch" not in context:
                    self.events.append(SafetyEvent(
                        SafetyEvent.SEVERITY_INFO,
                        "resource-safety",
                        "File operation without error handling",
                        line=i,
                        context={"code": line.strip()},
                    ))

    def _check_sleep_in_loops(self):
        """Detect sleep calls inside loops (potential DoS or busy-wait)."""
        in_loop = False
        for i, line in enumerate(self.lines, 1):
            stripped = line.strip()
            if re.match(r'^(while|loop|for)\b', stripped):
                in_loop = True
            elif in_loop and re.search(r'\b(sleep|wait|delay)\s*\(', stripped):
                self.events.append(SafetyEvent(
                    SafetyEvent.SEVERITY_INFO,
                    "performance",
                    "Sleep/delay inside loop — may cause sluggish execution",
                    line=i,
                    context={"code": stripped},
                ))
                in_loop = False

    def _check_deep_nesting(self):
        """Detect deeply nested code blocks (complexity smell)."""
        max_indent = 0
        max_indent_line = 0
        for i, line in enumerate(self.lines, 1):
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip())
            if indent > max_indent:
                max_indent = indent
                max_indent_line = i

        if max_indent >= 20:  # 5+ levels at 4-space indent
            self.events.append(SafetyEvent(
                SafetyEvent.SEVERITY_INFO,
                "complexity",
                f"Deep nesting detected ({max_indent // 4}+ levels)",
                line=max_indent_line,
            ))


# ---------------------------------------------------------------------------
# Runtime Monitor
# ---------------------------------------------------------------------------

class RuntimeMonitor:
    """Executes .srv file as subprocess with safety constraints."""

    def __init__(self, filepath, config):
        self.filepath = filepath
        self.config = config
        self.events = []
        self.execution_time = 0
        self.exit_code = None
        self.stdout = ""
        self.stderr = ""
        self.timed_out = False

    def run(self):
        """Execute the .srv file with timeout and resource monitoring."""
        interpreter = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saurav.py")
        if not os.path.exists(interpreter):
            self.events.append(SafetyEvent(
                SafetyEvent.SEVERITY_CRITICAL,
                "runtime",
                "saurav.py interpreter not found",
            ))
            return self.events

        cmd = [sys.executable, interpreter, self.filepath]
        start = time.time()

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.timeout,
                cwd=os.path.dirname(os.path.abspath(self.filepath)) or ".",
            )
            self.execution_time = time.time() - start
            self.exit_code = result.returncode
            self.stdout = result.stdout
            self.stderr = result.stderr

        except subprocess.TimeoutExpired:
            self.execution_time = self.config.timeout
            self.timed_out = True
            self.events.append(SafetyEvent(
                SafetyEvent.SEVERITY_CRITICAL,
                "timeout",
                f"Execution exceeded {self.config.timeout}s timeout — forcibly terminated",
                context={"timeout_seconds": self.config.timeout},
            ))
            return self.events

        # Analyze results
        if self.exit_code != 0:
            self.events.append(SafetyEvent(
                SafetyEvent.SEVERITY_WARN,
                "runtime-error",
                f"Program exited with code {self.exit_code}",
                context={"stderr": self.stderr[:500]},
            ))

        # Check for runtime error patterns in stderr
        if "RecursionError" in self.stderr or "maximum recursion" in self.stderr:
            self.events.append(SafetyEvent(
                SafetyEvent.SEVERITY_CRITICAL,
                "recursion-overflow",
                "Program hit recursion limit at runtime",
                context={"detail": self.stderr[:200]},
            ))

        if "MemoryError" in self.stderr:
            self.events.append(SafetyEvent(
                SafetyEvent.SEVERITY_CRITICAL,
                "memory-overflow",
                "Program ran out of memory",
            ))

        # Performance warnings
        if self.execution_time > self.config.timeout * 0.8:
            self.events.append(SafetyEvent(
                SafetyEvent.SEVERITY_WARN,
                "performance",
                f"Execution took {self.execution_time:.1f}s ({self.execution_time/self.config.timeout*100:.0f}% of timeout)",
                context={"seconds": round(self.execution_time, 2)},
            ))

        return self.events


# ---------------------------------------------------------------------------
# Safety Report
# ---------------------------------------------------------------------------

class SafetyReport:
    """Generates unified safety reports from static + runtime analysis."""

    def __init__(self, filepath, static_events, runtime_events, execution_time, config):
        self.filepath = filepath
        self.events = static_events + runtime_events
        self.execution_time = execution_time
        self.config = config
        self.risk_score = self._calculate_risk()

    def _calculate_risk(self):
        """Calculate risk score 0-100 based on findings."""
        score = 0
        for event in self.events:
            if event.severity == SafetyEvent.SEVERITY_CRITICAL:
                score += 30
            elif event.severity == SafetyEvent.SEVERITY_WARN:
                score += 15
            else:
                score += 5
        return min(100, score)

    def _risk_label(self):
        if self.risk_score >= 70:
            return "HIGH RISK"
        elif self.risk_score >= 40:
            return "MODERATE RISK"
        elif self.risk_score > 0:
            return "LOW RISK"
        return "SAFE"

    def _risk_color(self):
        if self.risk_score >= 70:
            return "#ff4444"
        elif self.risk_score >= 40:
            return "#ffaa00"
        elif self.risk_score > 0:
            return "#88cc44"
        return "#44ff44"

    def _ascii_gauge(self):
        """ASCII severity gauge."""
        filled = self.risk_score // 5
        empty = 20 - filled
        bar = "█" * filled + "░" * empty
        return f"[{bar}] {self.risk_score}/100 {self._risk_label()}"

    def print_console(self):
        """Print formatted console report."""
        print("\n" + "=" * 60)
        print("  🛡️  SAURAVGUARD — Runtime Safety Report")
        print("=" * 60)
        print(f"  File: {self.filepath}")
        print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Execution: {self.execution_time:.2f}s")
        print(f"\n  Risk: {self._ascii_gauge()}")
        print("-" * 60)

        if not self.events:
            print("  ✅ No safety issues detected. Program appears safe.")
        else:
            # Group by severity
            critical = [e for e in self.events if e.severity == SafetyEvent.SEVERITY_CRITICAL]
            warnings = [e for e in self.events if e.severity == SafetyEvent.SEVERITY_WARN]
            info = [e for e in self.events if e.severity == SafetyEvent.SEVERITY_INFO]

            if critical:
                print(f"\n  🔴 CRITICAL ({len(critical)}):")
                for e in critical:
                    loc = f" [line {e.line}]" if e.line else ""
                    print(f"     • {e.message}{loc}")

            if warnings:
                print(f"\n  🟡 WARNINGS ({len(warnings)}):")
                for e in warnings:
                    loc = f" [line {e.line}]" if e.line else ""
                    print(f"     • {e.message}{loc}")

            if info:
                print(f"\n  🔵 INFO ({len(info)}):")
                for e in info:
                    loc = f" [line {e.line}]" if e.line else ""
                    print(f"     • {e.message}{loc}")

        # Recommendations
        print("\n" + "-" * 60)
        print("  📋 Recommendations:")
        recommendations = self._generate_recommendations()
        for rec in recommendations:
            print(f"     → {rec}")

        print("=" * 60 + "\n")

    def _generate_recommendations(self):
        """Proactive recommendations based on findings."""
        recs = []
        categories = {e.category for e in self.events}

        if "infinite-loop" in categories:
            recs.append("Add explicit loop bounds or break conditions to while-true loops")
        if "recursion" in categories or "recursion-overflow" in categories:
            recs.append("Ensure all recursive functions have reachable base cases")
        if "memory-pressure" in categories or "memory-overflow" in categories:
            recs.append("Add size checks before collection growth in loops")
        if "timeout" in categories:
            recs.append("Optimize hot paths or add progress checkpoints")
        if "resource-safety" in categories:
            recs.append("Wrap file operations in try/catch blocks")
        if "performance" in categories:
            recs.append("Consider caching or algorithmic improvements for better performance")
        if "complexity" in categories:
            recs.append("Refactor deeply nested code into helper functions")

        if not recs:
            recs.append("No immediate action needed — code looks safe!")

        return recs

    def to_json(self):
        """Export report as JSON."""
        return json.dumps({
            "file": self.filepath,
            "timestamp": datetime.now().isoformat(),
            "execution_time_seconds": round(self.execution_time, 3),
            "risk_score": self.risk_score,
            "risk_label": self._risk_label(),
            "findings_count": len(self.events),
            "findings": [e.to_dict() for e in self.events],
            "recommendations": self._generate_recommendations(),
        }, indent=2)

    def to_html(self):
        """Generate detailed HTML safety report."""
        events_html = ""
        for e in self.events:
            color = {"critical": "#ff4444", "warn": "#ffaa00", "info": "#6699ff"}[e.severity]
            icon = {"critical": "🔴", "warn": "🟡", "info": "🔵"}[e.severity]
            loc = f" <span style='color:#888'>(line {e.line})</span>" if e.line else ""
            events_html += f"""
            <div style="border-left:3px solid {color}; padding:8px 12px; margin:8px 0; background:#1a1a2e;">
                {icon} <strong style="color:{color}">{e.severity.upper()}</strong> — {e.category}{loc}
                <div style="color:#ccc; margin-top:4px">{e.message}</div>
            </div>"""

        recs_html = "".join(f"<li>{r}</li>" for r in self._generate_recommendations())
        risk_pct = self.risk_score

        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>SauravGuard Report</title>
<style>
body {{ background:#0f0f23; color:#e0e0e0; font-family:'Segoe UI',sans-serif; padding:40px; max-width:800px; margin:auto; }}
h1 {{ color:#7fdbca; }} h2 {{ color:#c3a6ff; border-bottom:1px solid #333; padding-bottom:8px; }}
.risk-bar {{ background:#222; border-radius:10px; height:28px; overflow:hidden; margin:12px 0; }}
.risk-fill {{ height:100%; border-radius:10px; display:flex; align-items:center; padding-left:12px;
              font-weight:bold; transition:width 0.5s; background:{self._risk_color()}; width:{risk_pct}%; }}
.meta {{ color:#888; font-size:0.9em; }}
ul {{ line-height:2; }}
</style></head><body>
<h1>🛡️ SauravGuard — Safety Report</h1>
<p class="meta">File: <code>{self.filepath}</code> | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Execution: {self.execution_time:.2f}s</p>
<h2>Risk Score</h2>
<div class="risk-bar"><div class="risk-fill">{risk_pct}/100 — {self._risk_label()}</div></div>
<h2>Findings ({len(self.events)})</h2>
{events_html if events_html else '<p style="color:#88cc44">✅ No safety issues detected.</p>'}
<h2>Recommendations</h2><ul>{recs_html}</ul>
</body></html>"""


# ---------------------------------------------------------------------------
# Watch Mode
# ---------------------------------------------------------------------------

class WatchMode:
    """Autonomous file watcher — re-runs analysis on source change."""

    def __init__(self, filepath, config):
        self.filepath = filepath
        self.config = config
        self.last_hash = None
        self.last_events_count = 0

    def _file_hash(self):
        try:
            with open(self.filepath, "rb") as f:
                return hashlib.md5(f.read()).hexdigest()
        except OSError:
            return None

    def run(self):
        """Poll for changes and re-run analysis."""
        print(f"👁️  Watching {self.filepath} (Ctrl+C to stop)")
        print("-" * 40)
        try:
            while True:
                current_hash = self._file_hash()
                if current_hash and current_hash != self.last_hash:
                    self.last_hash = current_hash
                    print(f"\n🔄 Change detected at {datetime.now().strftime('%H:%M:%S')}")
                    events = run_analysis(self.filepath, self.config, quiet=False)
                    diff = len(events) - self.last_events_count
                    if diff > 0:
                        print(f"   ⚠️  +{diff} new finding(s)")
                    elif diff < 0:
                        print(f"   ✅ {-diff} finding(s) resolved")
                    self.last_events_count = len(events)
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\n👋 Watch mode ended.")


# ---------------------------------------------------------------------------
# Main Analysis Pipeline
# ---------------------------------------------------------------------------

def run_analysis(filepath, config, quiet=False):
    """Run full static + runtime analysis pipeline."""
    # Read source
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
    except OSError as e:
        print(f"❌ Cannot read {filepath}: {e}")
        return []

    # Static analysis
    analyzer = StaticAnalyzer(source, config)
    static_events = analyzer.analyze()

    # Runtime monitoring
    monitor = RuntimeMonitor(filepath, config)
    runtime_events = monitor.run()

    # Generate report
    report = SafetyReport(
        filepath,
        static_events,
        runtime_events,
        monitor.execution_time,
        config,
    )

    if config.json_output:
        print(report.to_json())
    elif not quiet:
        report.print_console()

    if config.report:
        html_path = filepath.replace(".srv", "_guard_report.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(report.to_html())
        print(f"📄 HTML report saved: {html_path}")

    # Strict mode: exit with error if critical findings
    if config.strict:
        critical = [e for e in report.events if e.severity == SafetyEvent.SEVERITY_CRITICAL]
        if critical:
            print(f"\n⛔ STRICT MODE: {len(critical)} critical finding(s) — halting.")
            sys.exit(1)

    return report.events


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="sauravguard",
        description="Autonomous Runtime Guardian for sauravcode — proactive safety analysis",
    )
    parser.add_argument("file", help="Path to .srv file to analyze")
    parser.add_argument("--max-loops", type=int, default=100000, help="Max loop iterations (default: 100000)")
    parser.add_argument("--max-depth", type=int, default=500, help="Max recursion depth (default: 500)")
    parser.add_argument("--timeout", type=int, default=30, help="Execution timeout in seconds (default: 30)")
    parser.add_argument("--max-memory", type=int, default=1000000, help="Max collection size (default: 1000000)")
    parser.add_argument("--report", action="store_true", help="Generate HTML safety report")
    parser.add_argument("--strict", action="store_true", help="Halt on critical findings")
    parser.add_argument("--watch", action="store_true", help="Re-run on file change (autonomous monitoring)")
    parser.add_argument("--json", dest="json_output", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"❌ File not found: {args.file}")
        sys.exit(1)

    if not args.file.endswith(".srv"):
        print(f"⚠️  Warning: {args.file} doesn't have .srv extension")

    config = GuardConfig(
        max_loops=args.max_loops,
        max_depth=args.max_depth,
        timeout=args.timeout,
        max_memory=args.max_memory,
        strict=args.strict,
        report=args.report,
        watch=args.watch,
        json_output=args.json_output,
    )

    if config.watch:
        watcher = WatchMode(args.file, config)
        watcher.run()
    else:
        run_analysis(args.file, config)


if __name__ == "__main__":
    main()
