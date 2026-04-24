"""sauravmutant — Autonomous Mutation Testing Engine for sauravcode.

Measures test suite effectiveness by automatically generating mutant .srv
programs, running the test suite against each, and reporting which mutants
survived (indicating weak test coverage areas).

Mutation operators:
  1. Arithmetic:  + ↔ -,  * ↔ /,  % → +
  2. Comparison:  > ↔ <,  >= ↔ <=,  == ↔ !=
  3. Logical:     and ↔ or,  not removal
  4. Constant:    number ± 1,  0 → 1,  1 → 0
  5. Statement:   delete statement,  swap adjacent statements
  6. Boundary:    off-by-one in ranges/loops

Usage:
    python sauravmutant.py <source.srv> --test <test.srv> [options]
    python sauravmutant.py <source.srv> --test-dir <dir> [options]
    python sauravmutant.py <source.srv> --self-test [options]

Options:
    --timeout N          Per-mutant timeout in seconds (default: 10)
    --max-mutants N      Max mutants to generate (default: 100)
    --operators OPS      Comma-separated operator list (default: all)
    --report             Generate HTML mutation report
    --json               Output results as JSON
    --verbose            Show each mutant and result
    --auto-harden        Suggest test improvements for surviving mutants
    --watch              Re-run on file change (autonomous monitoring mode)
    --sample N           Random sample N mutants (faster for large files)
"""

import sys
import os
import re
import json
import time
import random
import argparse
import subprocess
import hashlib
import tempfile
from datetime import datetime
from collections import defaultdict


# ---------------------------------------------------------------------------
# Mutation Operators
# ---------------------------------------------------------------------------

class Mutation:
    """A single mutation applied to source code."""

    def __init__(self, operator, line_no, original, replacement, description):
        self.operator = operator
        self.line_no = line_no
        self.original = original
        self.replacement = replacement
        self.description = description
        self.status = "pending"  # pending | killed | survived | timeout | error
        self.execution_time = 0.0

    def to_dict(self):
        return {
            "operator": self.operator,
            "line": self.line_no,
            "original": self.original.strip(),
            "replacement": self.replacement.strip(),
            "description": self.description,
            "status": self.status,
            "execution_time": round(self.execution_time, 3),
        }


class MutationEngine:
    """Generates mutations from .srv source lines."""

    # Arithmetic swaps
    ARITH_PAIRS = [
        (r'(?<!=)\+(?!=)', '-', 'arithmetic', 'Replace + with -'),
        (r'(?<![\-<>!=])-(?!>)', '+', 'arithmetic', 'Replace - with +'),
        (r'(?<!\*)\*(?!\*)', '/', 'arithmetic', 'Replace * with /'),
        (r'(?<!/)/', '*', 'arithmetic', 'Replace / with *'),
        (r'%', '+', 'arithmetic', 'Replace % with +'),
    ]

    # Comparison swaps
    CMP_PAIRS = [
        (r'(?<![<>=!])>(?!=)', '<', 'comparison', 'Replace > with <'),
        (r'(?<![<>=!])<(?!=)', '>', 'comparison', 'Replace < with >'),
        (r'>=', '<=', 'comparison', 'Replace >= with <='),
        (r'<=', '>=', 'comparison', 'Replace <= with >='),
        (r'==', '!=', 'comparison', 'Replace == with !='),
        (r'!=', '==', 'comparison', 'Replace != with =='),
    ]

    # Logical swaps
    LOGIC_PAIRS = [
        (r'\band\b', 'or', 'logical', 'Replace and with or'),
        (r'\bor\b', 'and', 'logical', 'Replace or with and'),
        (r'\bnot\s+', '', 'logical', 'Remove not'),
    ]

    ALL_OPERATORS = {
        'arithmetic': ARITH_PAIRS,
        'comparison': CMP_PAIRS,
        'logical': LOGIC_PAIRS,
        'constant': [],  # handled specially
        'statement': [],  # handled specially
        'boundary': [],   # handled specially
    }

    def __init__(self, operators=None):
        self.active_operators = operators or list(self.ALL_OPERATORS.keys())

    def generate(self, lines):
        """Generate all possible mutations for the given source lines."""
        mutations = []

        for line_no, line in enumerate(lines, 1):
            stripped = line.strip()

            # Skip comments and blank lines
            if not stripped or stripped.startswith('#') or stripped.startswith('//'):
                continue

            # Skip string-only lines
            if stripped.startswith('"') or stripped.startswith("'"):
                continue

            # Regex-based operators
            for op_name in ['arithmetic', 'comparison', 'logical']:
                if op_name not in self.active_operators:
                    continue
                pairs = self.ALL_OPERATORS[op_name]
                for pattern, repl, cat, desc in pairs:
                    if re.search(pattern, stripped):
                        new_line = re.sub(pattern, repl, stripped, count=1)
                        if new_line != stripped:
                            mutations.append(Mutation(
                                cat, line_no, line, 
                                line.replace(stripped, new_line, 1),
                                f"L{line_no}: {desc}"
                            ))

            # Constant mutations
            if 'constant' in self.active_operators:
                mutations.extend(self._mutate_constants(line, line_no, stripped))

            # Boundary mutations (off-by-one in range-like constructs)
            if 'boundary' in self.active_operators:
                mutations.extend(self._mutate_boundaries(line, line_no, stripped))

        # Statement-level mutations
        if 'statement' in self.active_operators:
            mutations.extend(self._mutate_statements(lines))

        return mutations

    def _mutate_constants(self, line, line_no, stripped):
        """Mutate numeric constants: n → n+1, n → n-1, 0 ↔ 1."""
        mutations = []
        for m in re.finditer(r'\b(\d+)\b', stripped):
            val = int(m.group(1))
            # 0 → 1
            if val == 0:
                new_stripped = stripped[:m.start()] + '1' + stripped[m.end():]
                mutations.append(Mutation(
                    'constant', line_no, line,
                    line.replace(stripped, new_stripped, 1),
                    f"L{line_no}: Replace 0 with 1"
                ))
            # 1 → 0
            elif val == 1:
                new_stripped = stripped[:m.start()] + '0' + stripped[m.end():]
                mutations.append(Mutation(
                    'constant', line_no, line,
                    line.replace(stripped, new_stripped, 1),
                    f"L{line_no}: Replace 1 with 0"
                ))
            else:
                # n → n+1
                new_stripped = stripped[:m.start()] + str(val + 1) + stripped[m.end():]
                mutations.append(Mutation(
                    'constant', line_no, line,
                    line.replace(stripped, new_stripped, 1),
                    f"L{line_no}: Replace {val} with {val + 1}"
                ))
                # n → n-1
                new_stripped = stripped[:m.start()] + str(val - 1) + stripped[m.end():]
                mutations.append(Mutation(
                    'constant', line_no, line,
                    line.replace(stripped, new_stripped, 1),
                    f"L{line_no}: Replace {val} with {val - 1}"
                ))
            break  # only first constant per line
        return mutations

    def _mutate_boundaries(self, line, line_no, stripped):
        """Off-by-one mutations in range/loop constructs."""
        mutations = []
        # range(n) → range(n-1) and range(n+1)
        m = re.search(r'range\s*\(\s*(\d+)\s*\)', stripped)
        if m:
            val = int(m.group(1))
            if val > 0:
                new1 = stripped[:m.start()] + f'range({val - 1})' + stripped[m.end():]
                mutations.append(Mutation(
                    'boundary', line_no, line,
                    line.replace(stripped, new1, 1),
                    f"L{line_no}: range({val}) → range({val - 1}) [off-by-one]"
                ))
            new2 = stripped[:m.start()] + f'range({val + 1})' + stripped[m.end():]
            mutations.append(Mutation(
                'boundary', line_no, line,
                line.replace(stripped, new2, 1),
                f"L{line_no}: range({val}) → range({val + 1}) [off-by-one]"
            ))
        return mutations

    def _mutate_statements(self, lines):
        """Statement deletion and swap mutations."""
        mutations = []
        code_lines = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped and not stripped.startswith('#') and not stripped.startswith('//'):
                code_lines.append(i)

        # Statement deletion (skip first and last to keep structure)
        for idx in code_lines[1:-1]:
            new_lines = list(lines)
            indent = len(lines[idx]) - len(lines[idx].lstrip())
            new_lines[idx] = ' ' * indent + '# MUTANT: deleted\n'
            mutations.append(Mutation(
                'statement', idx + 1, lines[idx],
                new_lines[idx],
                f"L{idx + 1}: Delete statement"
            ))

        # Adjacent statement swap
        for i in range(len(code_lines) - 1):
            a, b = code_lines[i], code_lines[i + 1]
            if b - a == 1:  # truly adjacent
                new_lines = list(lines)
                new_lines[a], new_lines[b] = new_lines[b], new_lines[a]
                mutations.append(Mutation(
                    'statement', a + 1, lines[a],
                    lines[b],
                    f"L{a + 1}-L{b + 1}: Swap adjacent statements"
                ))

        return mutations


# ---------------------------------------------------------------------------
# Mutant Runner
# ---------------------------------------------------------------------------

class MutantRunner:
    """Runs the test suite against each mutant."""

    def __init__(self, source_path, test_paths, timeout=10, verbose=False):
        self.source_path = os.path.abspath(source_path)
        self.test_paths = [os.path.abspath(t) for t in test_paths]
        self.timeout = timeout
        self.verbose = verbose
        self.interpreter = sys.executable
        self.saurav_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'saurav.py')

    def run_tests_against(self, mutant_source):
        """Run test files against a mutant. Returns (killed, error_msg, elapsed)."""
        # Write mutant to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.srv', delete=False) as f:
            f.write(mutant_source)
            mutant_path = f.name

        try:
            for test_path in self.test_paths:
                start = time.time()
                try:
                    result = subprocess.run(
                        [self.interpreter, self.saurav_py, test_path],
                        capture_output=True, text=True, timeout=self.timeout,
                        env={**os.environ, 'SAURAV_MUTANT_SOURCE': mutant_path}
                    )
                    elapsed = time.time() - start

                    # If test fails (non-zero exit or error output), mutant is killed
                    if result.returncode != 0:
                        return True, result.stderr[:200], elapsed
                    # Check for assertion errors in output
                    if 'error' in result.stderr.lower() or 'assert' in result.stderr.lower():
                        return True, result.stderr[:200], elapsed
                    # Check for FAIL markers
                    if 'FAIL' in result.stdout or 'Error' in result.stdout:
                        return True, result.stdout[:200], elapsed

                except subprocess.TimeoutExpired:
                    return False, "timeout", self.timeout

            return False, "survived", time.time() - start

        finally:
            try:
                os.unlink(mutant_path)
            except OSError:
                pass

    def run_original(self):
        """Verify tests pass on the original source."""
        for test_path in self.test_paths:
            try:
                result = subprocess.run(
                    [self.interpreter, self.saurav_py, test_path],
                    capture_output=True, text=True, timeout=self.timeout
                )
                if result.returncode != 0:
                    return False, f"Test {os.path.basename(test_path)} fails on original: {result.stderr[:200]}"
            except subprocess.TimeoutExpired:
                return False, f"Test {os.path.basename(test_path)} timed out on original"
        return True, "all tests pass"


# ---------------------------------------------------------------------------
# Report Generator
# ---------------------------------------------------------------------------

class MutationReport:
    """Generates HTML and text reports from mutation results."""

    def __init__(self, source_path, mutations, stats):
        self.source_path = source_path
        self.mutations = mutations
        self.stats = stats

    def text_summary(self):
        """Return a text summary of mutation testing results."""
        lines = []
        lines.append("=" * 60)
        lines.append("  MUTATION TESTING REPORT — sauravmutant")
        lines.append("=" * 60)
        lines.append(f"  Source:     {os.path.basename(self.source_path)}")
        lines.append(f"  Timestamp:  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"  Mutants:    {self.stats['total']}")
        lines.append(f"  Killed:     {self.stats['killed']} ✓")
        lines.append(f"  Survived:   {self.stats['survived']} ✗")
        lines.append(f"  Timeout:    {self.stats['timeout']}")
        lines.append(f"  Errors:     {self.stats['errors']}")
        lines.append("-" * 60)
        
        score = self.stats['score']
        if score >= 80:
            grade = "A — Excellent test suite"
            color = "green"
        elif score >= 60:
            grade = "B — Good, some gaps"
            color = "yellow"
        elif score >= 40:
            grade = "C — Moderate coverage"
            color = "orange"
        else:
            grade = "D — Weak test suite"
            color = "red"

        lines.append(f"  MUTATION SCORE: {score:.1f}%  [{grade}]")
        lines.append("=" * 60)

        # Operator breakdown
        lines.append("\n  By Operator:")
        for op, counts in self.stats['by_operator'].items():
            k = counts['killed']
            t = counts['total']
            pct = (k / t * 100) if t > 0 else 0
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            lines.append(f"    {op:12s}  {bar}  {pct:5.1f}% ({k}/{t})")

        # Surviving mutants detail
        survivors = [m for m in self.mutations if m.status == 'survived']
        if survivors:
            lines.append(f"\n  ⚠ Surviving Mutants ({len(survivors)}):")
            for m in survivors[:20]:
                lines.append(f"    L{m.line_no}: {m.description}")
                lines.append(f"      Original:  {m.original.strip()}")
                lines.append(f"      Mutant:    {m.replacement.strip()}")

        return "\n".join(lines)

    def auto_harden_suggestions(self):
        """Generate test improvement suggestions for surviving mutants."""
        survivors = [m for m in self.mutations if m.status == 'survived']
        if not survivors:
            return ["All mutants killed — test suite is strong! 🎉"]

        suggestions = []
        by_op = defaultdict(list)
        for m in survivors:
            by_op[m.operator].append(m)

        if 'arithmetic' in by_op:
            suggestions.append(
                f"🔢 {len(by_op['arithmetic'])} arithmetic mutants survived — "
                "add tests that verify exact numeric results, not just truthiness"
            )
        if 'comparison' in by_op:
            suggestions.append(
                f"⚖️ {len(by_op['comparison'])} comparison mutants survived — "
                "add boundary value tests (test at exact thresholds)"
            )
        if 'logical' in by_op:
            suggestions.append(
                f"🔀 {len(by_op['logical'])} logical mutants survived — "
                "test both branches of every conditional"
            )
        if 'constant' in by_op:
            suggestions.append(
                f"🔢 {len(by_op['constant'])} constant mutants survived — "
                "test with edge-case values (0, 1, negative, boundary)"
            )
        if 'statement' in by_op:
            lines = sorted(set(m.line_no for m in by_op['statement']))
            suggestions.append(
                f"📝 {len(by_op['statement'])} statement mutants survived — "
                f"lines {lines[:5]} may be untested dead code"
            )
        if 'boundary' in by_op:
            suggestions.append(
                f"🎯 {len(by_op['boundary'])} boundary mutants survived — "
                "add off-by-one tests for loops and ranges"
            )

        return suggestions

    def to_json(self):
        """Return mutation results as a JSON-serializable dict."""
        return {
            "source": os.path.basename(self.source_path),
            "timestamp": datetime.now().isoformat(),
            "stats": self.stats,
            "mutations": [m.to_dict() for m in self.mutations],
            "suggestions": self.auto_harden_suggestions(),
        }

    def to_html(self):
        """Generate an interactive HTML mutation report."""
        score = self.stats['score']
        if score >= 80:
            score_color = "#22c55e"
        elif score >= 60:
            score_color = "#eab308"
        elif score >= 40:
            score_color = "#f97316"
        else:
            score_color = "#ef4444"

        survivors = [m for m in self.mutations if m.status == 'survived']
        killed = [m for m in self.mutations if m.status == 'killed']

        op_rows = ""
        for op, counts in self.stats['by_operator'].items():
            k = counts['killed']
            t = counts['total']
            pct = (k / t * 100) if t > 0 else 0
            op_rows += f"""<tr>
                <td style="font-weight:600">{op}</td>
                <td>{k}/{t}</td>
                <td>
                    <div style="background:#1e293b;border-radius:4px;overflow:hidden;height:20px">
                        <div style="background:{'#22c55e' if pct>=70 else '#eab308' if pct>=40 else '#ef4444'};
                             height:100%;width:{pct}%;transition:width 0.5s"></div>
                    </div>
                </td>
                <td style="text-align:right">{pct:.1f}%</td>
            </tr>"""

        survivor_rows = ""
        for m in survivors[:30]:
            survivor_rows += f"""<tr>
                <td>L{m.line_no}</td>
                <td><span class="badge badge-{m.operator}">{m.operator}</span></td>
                <td><code>{_html_escape(m.original.strip())}</code></td>
                <td><code>{_html_escape(m.replacement.strip())}</code></td>
                <td>{_html_escape(m.description)}</td>
            </tr>"""

        suggestions_html = ""
        for s in self.auto_harden_suggestions():
            suggestions_html += f"<li>{_html_escape(s)}</li>"

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mutation Report — {_html_escape(os.path.basename(self.source_path))}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Segoe UI',system-ui,sans-serif; background:#0f172a; color:#e2e8f0; padding:2rem; }}
  .container {{ max-width:1000px; margin:0 auto; }}
  h1 {{ font-size:1.8rem; margin-bottom:0.5rem; }}
  h2 {{ font-size:1.3rem; margin:1.5rem 0 0.8rem; color:#94a3b8; }}
  .subtitle {{ color:#64748b; margin-bottom:2rem; }}
  .score-card {{ background:#1e293b; border-radius:12px; padding:2rem; text-align:center; margin-bottom:2rem; }}
  .score-value {{ font-size:4rem; font-weight:800; color:{score_color}; }}
  .score-label {{ font-size:1rem; color:#94a3b8; }}
  .stats {{ display:grid; grid-template-columns:repeat(4,1fr); gap:1rem; margin-bottom:2rem; }}
  .stat {{ background:#1e293b; border-radius:8px; padding:1rem; text-align:center; }}
  .stat-value {{ font-size:2rem; font-weight:700; }}
  .stat-label {{ font-size:0.8rem; color:#64748b; }}
  table {{ width:100%; border-collapse:collapse; background:#1e293b; border-radius:8px; overflow:hidden; margin-bottom:1.5rem; }}
  th {{ background:#334155; padding:0.6rem 1rem; text-align:left; font-size:0.85rem; color:#94a3b8; }}
  td {{ padding:0.5rem 1rem; border-top:1px solid #334155; font-size:0.85rem; }}
  code {{ background:#334155; padding:2px 6px; border-radius:3px; font-size:0.8rem; }}
  .badge {{ padding:2px 8px; border-radius:10px; font-size:0.75rem; font-weight:600; }}
  .badge-arithmetic {{ background:#3b82f6; color:#fff; }}
  .badge-comparison {{ background:#8b5cf6; color:#fff; }}
  .badge-logical {{ background:#ec4899; color:#fff; }}
  .badge-constant {{ background:#f59e0b; color:#000; }}
  .badge-statement {{ background:#6366f1; color:#fff; }}
  .badge-boundary {{ background:#14b8a6; color:#000; }}
  .suggestions {{ background:#1e293b; border-radius:8px; padding:1.5rem; }}
  .suggestions li {{ margin:0.5rem 0; padding-left:0.5rem; }}
  .footer {{ text-align:center; color:#475569; margin-top:2rem; font-size:0.8rem; }}
</style>
</head>
<body>
<div class="container">
  <h1>🧬 Mutation Testing Report</h1>
  <p class="subtitle">{_html_escape(os.path.basename(self.source_path))} — {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

  <div class="score-card">
    <div class="score-value">{score:.1f}%</div>
    <div class="score-label">Mutation Score</div>
  </div>

  <div class="stats">
    <div class="stat"><div class="stat-value" style="color:#22c55e">{self.stats['killed']}</div><div class="stat-label">Killed</div></div>
    <div class="stat"><div class="stat-value" style="color:#ef4444">{self.stats['survived']}</div><div class="stat-label">Survived</div></div>
    <div class="stat"><div class="stat-value" style="color:#eab308">{self.stats['timeout']}</div><div class="stat-label">Timeout</div></div>
    <div class="stat"><div class="stat-value" style="color:#64748b">{self.stats['total']}</div><div class="stat-label">Total</div></div>
  </div>

  <h2>Operator Breakdown</h2>
  <table>
    <tr><th>Operator</th><th>Killed/Total</th><th>Kill Rate</th><th>%</th></tr>
    {op_rows}
  </table>

  {"<h2>⚠ Surviving Mutants</h2><table><tr><th>Line</th><th>Operator</th><th>Original</th><th>Mutant</th><th>Description</th></tr>" + survivor_rows + "</table>" if survivors else ""}

  <h2>🛡 Auto-Harden Suggestions</h2>
  <div class="suggestions"><ul>{suggestions_html}</ul></div>

  <p class="footer">Generated by sauravmutant — Autonomous Mutation Testing for sauravcode</p>
</div>
</body>
</html>"""


def _html_escape(s):
    """Simple HTML escape."""
    return (s.replace('&', '&amp;').replace('<', '&lt;')
             .replace('>', '&gt;').replace('"', '&quot;'))


# ---------------------------------------------------------------------------
# Watch Mode
# ---------------------------------------------------------------------------

def watch_loop(source_path, test_paths, config):
    """Autonomous file-watching mode: re-run mutation testing on changes."""
    print(f"👁 Watching {source_path} for changes... (Ctrl+C to stop)")
    last_hash = None
    while True:
        try:
            with open(source_path, 'r') as f:
                content = f.read()
            current_hash = hashlib.md5(content.encode()).hexdigest()
            if current_hash != last_hash:
                if last_hash is not None:
                    print(f"\n🔄 Change detected — re-running mutation testing...")
                last_hash = current_hash
                run_mutation_testing(source_path, test_paths, config)
            time.sleep(2)
        except KeyboardInterrupt:
            print("\n👋 Watch mode stopped.")
            break
        except Exception as e:
            print(f"⚠ Watch error: {e}")
            time.sleep(5)


# ---------------------------------------------------------------------------
# Main Logic
# ---------------------------------------------------------------------------

def run_mutation_testing(source_path, test_paths, config):
    """Execute a full mutation testing run."""
    # Read source
    with open(source_path, 'r') as f:
        lines = f.readlines()

    source_text = ''.join(lines)

    # Generate mutations
    engine = MutationEngine(operators=config.get('operators'))
    all_mutations = engine.generate(lines)

    if not all_mutations:
        print("No mutations generated. Source may be too simple.")
        return None

    # Sample if requested
    max_mutants = config.get('max_mutants', 100)
    sample_n = config.get('sample')
    if sample_n and sample_n < len(all_mutations):
        all_mutations = random.sample(all_mutations, sample_n)
    elif len(all_mutations) > max_mutants:
        all_mutations = random.sample(all_mutations, max_mutants)

    # Set up runner
    runner = MutantRunner(
        source_path, test_paths,
        timeout=config.get('timeout', 10),
        verbose=config.get('verbose', False)
    )

    # Verify original passes
    ok, msg = runner.run_original()
    if not ok:
        print(f"❌ Original source fails tests: {msg}")
        print("   Fix your tests first before mutation testing.")
        return None

    print(f"🧬 Running {len(all_mutations)} mutants against {len(test_paths)} test file(s)...")
    print()

    # Run each mutant
    killed = survived = timeouts = errors = 0
    by_operator = defaultdict(lambda: {'killed': 0, 'total': 0})

    for i, mutation in enumerate(all_mutations, 1):
        # Apply mutation
        mutant_lines = list(lines)
        mutant_lines[mutation.line_no - 1] = mutation.replacement
        mutant_source = ''.join(mutant_lines)

        # Run tests
        is_killed, msg, elapsed = runner.run_tests_against(mutant_source)
        mutation.execution_time = elapsed

        by_operator[mutation.operator]['total'] += 1

        if msg == "timeout":
            mutation.status = "timeout"
            timeouts += 1
        elif is_killed:
            mutation.status = "killed"
            killed += 1
            by_operator[mutation.operator]['killed'] += 1
        else:
            mutation.status = "survived"
            survived += 1

        if config.get('verbose'):
            icon = "✓" if mutation.status == "killed" else "✗" if mutation.status == "survived" else "⏱"
            print(f"  [{i}/{len(all_mutations)}] {icon} {mutation.description} ({elapsed:.2f}s)")

        # Progress indicator
        if not config.get('verbose') and i % 10 == 0:
            print(f"  Progress: {i}/{len(all_mutations)} ({killed} killed, {survived} survived)")

    # Calculate score
    testable = killed + survived
    score = (killed / testable * 100) if testable > 0 else 0

    stats = {
        'total': len(all_mutations),
        'killed': killed,
        'survived': survived,
        'timeout': timeouts,
        'errors': errors,
        'score': score,
        'by_operator': dict(by_operator),
    }

    # Generate report
    report = MutationReport(source_path, all_mutations, stats)
    print(report.text_summary())

    # Auto-harden suggestions
    if config.get('auto_harden'):
        print("\n🛡 AUTO-HARDEN SUGGESTIONS:")
        for s in report.auto_harden_suggestions():
            print(f"  {s}")

    # JSON output
    if config.get('json_output'):
        json_path = source_path.replace('.srv', '_mutations.json')
        with open(json_path, 'w') as f:
            json.dump(report.to_json(), f, indent=2)
        print(f"\n📄 JSON report: {json_path}")

    # HTML report
    if config.get('report'):
        html_path = source_path.replace('.srv', '_mutations.html')
        with open(html_path, 'w') as f:
            f.write(report.to_html())
        print(f"\n📊 HTML report: {html_path}")

    return report


# ---------------------------------------------------------------------------
# Self-Test Mode
# ---------------------------------------------------------------------------

def self_test(source_path, config):
    """Run mutation testing using the source's own assertions as tests."""
    # Look for test files that correspond to the source
    base = os.path.basename(source_path).replace('.srv', '')
    directory = os.path.dirname(source_path) or '.'
    
    candidates = [
        os.path.join(directory, f'test_{base}.srv'),
        os.path.join(directory, f'{base}_test.srv'),
        os.path.join(directory, 'tests', f'test_{base}.srv'),
        source_path,  # use the file itself if it contains assertions
    ]

    test_paths = [c for c in candidates if os.path.isfile(c)]
    if not test_paths:
        print(f"❌ No test files found for {source_path}")
        return None

    print(f"🔍 Self-test mode: using {[os.path.basename(t) for t in test_paths]}")
    return run_mutation_testing(source_path, test_paths, config)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='sauravmutant — Autonomous Mutation Testing Engine for sauravcode',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python sauravmutant.py mylib.srv --test test_mylib.srv
    python sauravmutant.py mylib.srv --test-dir tests/ --report --auto-harden
    python sauravmutant.py mylib.srv --self-test --verbose
    python sauravmutant.py mylib.srv --test test.srv --watch
    python sauravmutant.py mylib.srv --test test.srv --operators arithmetic,comparison
    python sauravmutant.py mylib.srv --test test.srv --sample 50 --json
        """
    )

    parser.add_argument('source', help='Source .srv file to mutate')
    parser.add_argument('--test', nargs='+', help='Test file(s) to run against mutants')
    parser.add_argument('--test-dir', help='Directory containing test .srv files')
    parser.add_argument('--self-test', action='store_true', help='Auto-discover tests or use source assertions')
    parser.add_argument('--timeout', type=int, default=10, help='Per-mutant timeout in seconds (default: 10)')
    parser.add_argument('--max-mutants', type=int, default=100, help='Max mutants to generate (default: 100)')
    parser.add_argument('--sample', type=int, help='Random sample N mutants')
    parser.add_argument('--operators', help='Comma-separated operator list (arithmetic,comparison,logical,constant,statement,boundary)')
    parser.add_argument('--report', action='store_true', help='Generate HTML mutation report')
    parser.add_argument('--json', action='store_true', help='Output results as JSON')
    parser.add_argument('--verbose', action='store_true', help='Show each mutant and result')
    parser.add_argument('--auto-harden', action='store_true', help='Suggest test improvements for surviving mutants')
    parser.add_argument('--watch', action='store_true', help='Re-run on file change')

    args = parser.parse_args()

    if not os.path.isfile(args.source):
        print(f"❌ Source file not found: {args.source}")
        sys.exit(1)

    config = {
        'timeout': args.timeout,
        'max_mutants': args.max_mutants,
        'sample': args.sample,
        'report': args.report,
        'json_output': args.json,
        'verbose': args.verbose,
        'auto_harden': args.auto_harden,
    }

    if args.operators:
        config['operators'] = [op.strip() for op in args.operators.split(',')]

    # Collect test files
    test_paths = []
    if args.test:
        test_paths = args.test
    elif args.test_dir:
        if os.path.isdir(args.test_dir):
            test_paths = [
                os.path.join(args.test_dir, f)
                for f in os.listdir(args.test_dir)
                if f.endswith('.srv') and ('test' in f.lower())
            ]
        else:
            print(f"❌ Test directory not found: {args.test_dir}")
            sys.exit(1)

    if args.self_test:
        if args.watch:
            watch_loop(args.source, [], config)
        else:
            self_test(args.source, config)
    elif test_paths:
        if args.watch:
            watch_loop(args.source, test_paths, config)
        else:
            run_mutation_testing(args.source, test_paths, config)
    else:
        print("❌ Specify --test, --test-dir, or --self-test")
        sys.exit(1)


if __name__ == '__main__':
    main()
