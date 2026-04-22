"""sauravheal — Autonomous Self-Healing Runtime for sauravcode.

Runs .srv programs and when they fail, automatically diagnoses the error,
generates a patch, applies it, and retries — building a knowledge base of
fixes over time so the same errors heal faster.

Usage:
    python sauravheal.py <file.srv>                 Run with auto-healing
    python sauravheal.py <file.srv> --max-retries 5 Retry limit (default: 3)
    python sauravheal.py <file.srv> --dry-run       Show patches without applying
    python sauravheal.py <file.srv> --report        Generate HTML healing report
    python sauravheal.py <file.srv> --json          JSON output
    python sauravheal.py --history                  Show healing history
    python sauravheal.py --stats                    Healing success statistics
    python sauravheal.py <file.srv> --watch         Auto-heal on file change
    python sauravheal.py --learn <file.srv>         Run & learn patterns without patching
"""

import sys
import os
import re
import json
import time
import shutil
import hashlib
import argparse
import subprocess
from datetime import datetime

HEAL_HISTORY = ".sauravheal_history.json"
HEAL_KB = ".sauravheal_kb.json"  # Knowledge base of learned fixes

# ─── Pre-compiled diagnostic regexes ────────────────────────────────────────────
# These patterns are used in the diagnostic rules below.  Pre-compiling them
# avoids re-parsing the same regex strings on every healing attempt (there can
# be several per run, each scanning the same set of rules).

_RE_UNDEF_VAR = re.compile(r"(?:Undefined variable|NameError|not defined)[:\s]*['\"]?(\w+)['\"]?")
_RE_UNKNOWN_VAR = re.compile(r"Unknown variable ['\"]?(\w+)['\"]?")
_RE_SET_LET_ASSIGN = re.compile(r'^\s*(?:set|let)?\s*(\w+)\s*=')
_RE_FOR_VAR = re.compile(r'^\s*for\s+(\w+)\s+in')
_RE_FUNC_PARAMS = re.compile(r'^\s*func\s+\w+\((.*?)\)')
_RE_MISSING_END = re.compile(r"(?:expected 'end'|unexpected end|missing end|unterminated)", re.I)
_RE_BLOCK_OPENER = re.compile(r'^(if|for|while|func|class|try)\b')
_RE_TYPE_ERROR = re.compile(r"(?:TypeError|type error|cannot (?:add|subtract|multiply|compare))[:\s]*(.*)", re.I)
_RE_STR_NUM_MIX = re.compile(r"str.*(?:int|float|number)|(?:int|float|number).*str", re.I)
_RE_INDEX_ERROR = re.compile(r"(?:IndexError|index out of (?:range|bounds))[:\s]*(.*)", re.I)
_RE_DIV_ZERO = re.compile(r"(?:division by zero|divide by zero|ZeroDivisionError)", re.I)
_RE_DIVISOR = re.compile(r'/\s*(\w+)')
_RE_IMPORT_ERROR = re.compile(r"(?:ImportError|ModuleNotFoundError|Cannot import|No module)[:\s]*['\"]?(\w+)['\"]?", re.I)
_RE_FILE_NOT_FOUND = re.compile(r"(?:File not found|cannot open)[:\s]*['\"]?([^\s'\"]+)['\"]?", re.I)
_RE_SYNTAX_LINE = re.compile(r"(?:SyntaxError|syntax error|parse error).*?line\s*(\d+)", re.I)
_RE_LINE_SYNTAX = re.compile(r"line\s*(\d+).*?(?:SyntaxError|syntax error|parse error)", re.I)

# ─── Error Diagnosis ────────────────────────────────────────────────────────────

class Diagnosis:
    """A diagnosed error with root cause and suggested fix."""

    def __init__(self, error_type, message, line_num=None, root_cause="",
                 fix_description="", patch=None, confidence=0.0):
        self.error_type = error_type
        self.message = message
        self.line_num = line_num
        self.root_cause = root_cause
        self.fix_description = fix_description
        self.patch = patch  # (line_num, old_text, new_text) or None
        self.confidence = confidence  # 0.0 - 1.0
        self.timestamp = datetime.now().isoformat()

    def to_dict(self):
        return {
            "error_type": self.error_type, "message": self.message,
            "line_num": self.line_num, "root_cause": self.root_cause,
            "fix_description": self.fix_description,
            "patch": list(self.patch) if self.patch else None,
            "confidence": self.confidence, "timestamp": self.timestamp
        }


# ─── Diagnostic Rules ──────────────────────────────────────────────────────────

def _diagnose_undefined_variable(error_msg, source_lines):
    """Detect and fix undefined variable errors."""
    m = _RE_UNDEF_VAR.search(error_msg)
    if not m:
        m = _RE_UNKNOWN_VAR.search(error_msg)
    if not m:
        return None

    var_name = m.group(1)
    # Find where the variable is first used
    use_line = None
    for i, line in enumerate(source_lines):
        stripped = line.strip()
        if re.search(rf'\b{re.escape(var_name)}\b', stripped) and not stripped.startswith('#'):
            use_line = i
            break

    if use_line is None:
        return None

    # Check if it's a typo — find similar variable names
    defined_vars = set()
    for line in source_lines:
        # Match: set x = ..., let x = ..., x = ...
        vm = _RE_SET_LET_ASSIGN.match(line)
        if vm:
            defined_vars.add(vm.group(1))
        # Match: for x in ...
        vm = _RE_FOR_VAR.match(line)
        if vm:
            defined_vars.add(vm.group(1))
        # Match: func params
        vm = _RE_FUNC_PARAMS.match(line)
        if vm:
            for p in vm.group(1).split(','):
                p = p.strip()
                if p:
                    defined_vars.add(p)

    # Levenshtein-like similarity
    best_match = None
    best_dist = 999
    for dv in defined_vars:
        dist = _edit_distance(var_name.lower(), dv.lower())
        if dist < best_dist and dist <= 2:
            best_dist = dist
            best_match = dv

    if best_match and best_match != var_name:
        # Typo fix
        old_line = source_lines[use_line]
        new_line = old_line.replace(var_name, best_match)
        return Diagnosis(
            "undefined_variable", error_msg, use_line + 1,
            f"'{var_name}' is likely a typo of '{best_match}'",
            f"Replace '{var_name}' with '{best_match}'",
            patch=(use_line, old_line, new_line),
            confidence=0.85
        )
    else:
        # Initialize with default
        indent = len(source_lines[use_line]) - len(source_lines[use_line].lstrip())
        init_line = " " * indent + f"set {var_name} = 0\n"
        return Diagnosis(
            "undefined_variable", error_msg, use_line + 1,
            f"Variable '{var_name}' used before definition",
            f"Initialize '{var_name}' before first use",
            patch=(use_line, None, init_line),  # Insert before
            confidence=0.6
        )


def _diagnose_missing_end(error_msg, source_lines):
    """Detect missing 'end' keywords for blocks."""
    if not _RE_MISSING_END.search(error_msg):
        return None

    # Count block openers vs 'end'
    openers = 0
    closers = 0
    last_opener_line = 0
    for i, line in enumerate(source_lines):
        stripped = line.strip()
        if _RE_BLOCK_OPENER.match(stripped):
            openers += 1
            last_opener_line = i
        if stripped == 'end':
            closers += 1

    if openers > closers:
        # Add missing end(s)
        insert_line = len(source_lines)
        # Try to find the right place — after last block opener's content
        return Diagnosis(
            "missing_end", error_msg, last_opener_line + 1,
            f"Found {openers} block openers but only {closers} 'end' keywords",
            f"Add {openers - closers} missing 'end' keyword(s)",
            patch=(insert_line, None, "end\n" * (openers - closers)),
            confidence=0.75
        )
    return None


def _diagnose_type_error(error_msg, source_lines):
    """Detect type mismatch errors."""
    m = _RE_TYPE_ERROR.search(error_msg)
    if not m:
        return None

    detail = m.group(1).strip()

    # Common: string + number
    if _RE_STR_NUM_MIX.search(detail):
        return Diagnosis(
            "type_error", error_msg, None,
            "Mixing string and numeric types in an operation",
            "Wrap numeric values with str() or use f-strings",
            confidence=0.5  # Can't auto-patch without knowing exact line
        )

    return Diagnosis(
        "type_error", error_msg, None,
        f"Type mismatch: {detail}",
        "Check operand types match the operation",
        confidence=0.3
    )


def _diagnose_index_error(error_msg, source_lines):
    """Detect out-of-bounds access."""
    m = _RE_INDEX_ERROR.search(error_msg)
    if not m:
        return None

    return Diagnosis(
        "index_error", error_msg, None,
        "Array/list index exceeds collection size",
        "Add bounds checking before access (e.g., if len(arr) > idx)",
        confidence=0.4
    )


def _diagnose_division_by_zero(error_msg, source_lines):
    """Detect division by zero."""
    if not _RE_DIV_ZERO.search(error_msg):
        return None

    # Find division operations
    for i, line in enumerate(source_lines):
        stripped = line.strip()
        if '/' in stripped and not stripped.startswith('#'):
            # Find the divisor
            dm = _RE_DIVISOR.search(stripped)
            if dm:
                divisor = dm.group(1)
                old_line = source_lines[i]
                indent = " " * (len(old_line) - len(old_line.lstrip()))
                guard = f"{indent}if {divisor} == 0\n{indent}    print \"Warning: division by zero, using 1\"\n{indent}    set {divisor} = 1\n{indent}end\n"
                return Diagnosis(
                    "division_by_zero", error_msg, i + 1,
                    f"Division by '{divisor}' which may be zero",
                    f"Add zero-guard before division",
                    patch=(i, None, guard),
                    confidence=0.8
                )

    return Diagnosis(
        "division_by_zero", error_msg, None,
        "Division by zero encountered",
        "Add guards to check divisor != 0",
        confidence=0.3
    )


def _diagnose_import_error(error_msg, source_lines):
    """Detect missing import/module errors."""
    m = _RE_IMPORT_ERROR.search(error_msg)
    if not m:
        m = _RE_FILE_NOT_FOUND.search(error_msg)
    if not m:
        return None

    module = m.group(1)
    return Diagnosis(
        "import_error", error_msg, 1,
        f"Module or file '{module}' not found",
        f"Check that '{module}' exists and path is correct",
        confidence=0.3
    )


def _diagnose_syntax_error(error_msg, source_lines):
    """Detect common syntax errors."""
    m = _RE_SYNTAX_LINE.search(error_msg)
    if not m:
        m = _RE_LINE_SYNTAX.search(error_msg)
    if not m:
        return None

    line_num = int(m.group(1)) - 1
    if line_num < 0 or line_num >= len(source_lines):
        return Diagnosis("syntax_error", error_msg, line_num + 1,
            "Syntax error at unknown location", "Check syntax", confidence=0.2)

    line_text = source_lines[line_num].rstrip()
    stripped = line_text.strip()

    # Missing quotes
    quote_count = stripped.count('"') + stripped.count("'")
    if quote_count % 2 != 0:
        # Find and close unclosed quote
        for q in ['"', "'"]:
            if stripped.count(q) % 2 != 0:
                new_line = line_text + q + "\n"
                return Diagnosis(
                    "syntax_error", error_msg, line_num + 1,
                    f"Unclosed string literal on line {line_num + 1}",
                    "Close the string quote",
                    patch=(line_num, source_lines[line_num], new_line),
                    confidence=0.8
                )

    # Missing parenthesis
    if stripped.count('(') > stripped.count(')'):
        new_line = line_text + ")" * (stripped.count('(') - stripped.count(')')) + "\n"
        return Diagnosis(
            "syntax_error", error_msg, line_num + 1,
            f"Unclosed parenthesis on line {line_num + 1}",
            "Close parenthesis",
            patch=(line_num, source_lines[line_num], new_line),
            confidence=0.8
        )

    return Diagnosis(
        "syntax_error", error_msg, line_num + 1,
        f"Syntax error on line {line_num + 1}: {stripped[:60]}",
        "Review syntax around this line",
        confidence=0.2
    )


# All diagnostic rules in priority order
DIAGNOSTIC_RULES = [
    _diagnose_undefined_variable,
    _diagnose_missing_end,
    _diagnose_division_by_zero,
    _diagnose_syntax_error,
    _diagnose_type_error,
    _diagnose_index_error,
    _diagnose_import_error,
]


# ─── Knowledge Base ─────────────────────────────────────────────────────────────

class HealingKB:
    """Persistent knowledge base of learned error→fix patterns."""

    def __init__(self, path=HEAL_KB):
        self.path = path
        self.patterns = []  # [{error_sig, fix_type, success_count, fail_count}]
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, 'r') as f:
                    data = json.load(f)
                self.patterns = data.get("patterns", [])
            except (json.JSONDecodeError, IOError):
                self.patterns = []

    def save(self):
        with open(self.path, 'w') as f:
            json.dump({"patterns": self.patterns, "updated": datetime.now().isoformat()}, f, indent=2)

    def record_outcome(self, error_sig, fix_type, success):
        """Record whether a fix worked."""
        for p in self.patterns:
            if p["error_sig"] == error_sig and p["fix_type"] == fix_type:
                if success:
                    p["success_count"] += 1
                else:
                    p["fail_count"] += 1
                p["last_seen"] = datetime.now().isoformat()
                self.save()
                return

        self.patterns.append({
            "error_sig": error_sig,
            "fix_type": fix_type,
            "success_count": 1 if success else 0,
            "fail_count": 0 if success else 1,
            "first_seen": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat()
        })
        self.save()

    def get_confidence_boost(self, error_sig, fix_type):
        """Get confidence boost from past successes."""
        for p in self.patterns:
            if p["error_sig"] == error_sig and p["fix_type"] == fix_type:
                total = p["success_count"] + p["fail_count"]
                if total > 0:
                    return p["success_count"] / total * 0.2  # Up to 0.2 boost
        return 0.0

    def stats(self):
        total = len(self.patterns)
        successes = sum(p["success_count"] for p in self.patterns)
        failures = sum(p["fail_count"] for p in self.patterns)
        return {"total_patterns": total, "total_successes": successes,
                "total_failures": failures,
                "success_rate": successes / max(successes + failures, 1)}


# ─── Healing Engine ─────────────────────────────────────────────────────────────

class HealingEngine:
    """Core self-healing runtime engine."""

    def __init__(self, filename, config):
        self.filename = filename
        self.config = config
        self.kb = HealingKB()
        self.history = []  # List of healing attempts
        self.original_source = None
        self.current_source = None

    def run(self):
        """Run the .srv file with auto-healing."""
        if not os.path.exists(self.filename):
            print(f"Error: File '{self.filename}' not found.")
            return False

        with open(self.filename, 'r') as f:
            self.original_source = f.read()
        self.current_source = self.original_source

        backup_path = self.filename + ".heal_backup"
        shutil.copy2(self.filename, backup_path)

        attempt = 0
        success = False

        while attempt <= self.config.max_retries:
            if attempt > 0:
                print(f"\n{'='*60}")
                print(f"  Healing attempt {attempt}/{self.config.max_retries}")
                print(f"{'='*60}")

            exit_code, stdout, stderr = self._execute()

            if exit_code == 0:
                if attempt > 0:
                    print(f"\n✅ Program healed and ran successfully after {attempt} fix(es)!")
                    # Record successes
                    for h in self.history:
                        if h.get("applied"):
                            self.kb.record_outcome(
                                h["diagnosis"]["error_type"],
                                h["diagnosis"]["fix_description"],
                                True
                            )
                else:
                    print(f"✅ Program ran successfully (no healing needed)")
                success = True
                break

            # Diagnose the error
            error_output = stderr if stderr else stdout
            if not error_output:
                print(f"❌ Program failed with exit code {exit_code} but no error output")
                break

            print(f"\n🔍 Error detected:")
            print(f"   {error_output[:200]}")

            source_lines = self.current_source.splitlines(keepends=True)
            diagnosis = self._diagnose(error_output, source_lines)

            if not diagnosis:
                print(f"❌ Could not diagnose error — no matching patterns")
                break

            # Apply KB confidence boost
            boost = self.kb.get_confidence_boost(diagnosis.error_type, diagnosis.fix_description)
            diagnosis.confidence = min(1.0, diagnosis.confidence + boost)

            print(f"\n🩺 Diagnosis:")
            print(f"   Type:       {diagnosis.error_type}")
            print(f"   Root cause: {diagnosis.root_cause}")
            print(f"   Fix:        {diagnosis.fix_description}")
            print(f"   Confidence: {diagnosis.confidence:.0%}")

            record = {
                "attempt": attempt + 1,
                "error": error_output[:300],
                "diagnosis": diagnosis.to_dict(),
                "applied": False
            }

            if diagnosis.patch is None:
                print(f"⚠️  No auto-patch available — manual fix needed")
                self.history.append(record)
                break

            if diagnosis.confidence < 0.4:
                print(f"⚠️  Confidence too low ({diagnosis.confidence:.0%}) — skipping auto-patch")
                self.history.append(record)
                break

            if self.config.dry_run:
                print(f"\n📝 Dry-run patch (not applied):")
                self._show_patch(diagnosis.patch, source_lines)
                self.history.append(record)
                break

            # Apply the patch
            print(f"\n🔧 Applying patch...")
            patched = self._apply_patch(source_lines, diagnosis.patch)
            if patched is None:
                print(f"❌ Failed to apply patch")
                self.history.append(record)
                break

            self.current_source = patched
            with open(self.filename, 'w') as f:
                f.write(patched)

            record["applied"] = True
            self.history.append(record)
            attempt += 1

        if not success and attempt > self.config.max_retries:
            print(f"\n❌ Max retries ({self.config.max_retries}) exceeded — restoring original")
            # Record failures
            for h in self.history:
                if h.get("applied"):
                    self.kb.record_outcome(
                        h["diagnosis"]["error_type"],
                        h["diagnosis"]["fix_description"],
                        False
                    )

        # Restore original if healing failed or dry run
        if not success or self.config.dry_run:
            if os.path.exists(backup_path):
                shutil.copy2(backup_path, self.filename)

        # Clean up backup on success (source already has patches)
        if success and not self.config.dry_run and os.path.exists(backup_path):
            os.remove(backup_path)

        # Save history
        self._save_history()

        return success

    def _execute(self):
        """Execute the .srv file and capture output."""
        try:
            result = subprocess.run(
                [sys.executable, "saurav.py", self.filename],
                capture_output=True, text=True, timeout=30,
                cwd=os.path.dirname(os.path.abspath(__file__)) or "."
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return 1, "", "Error: Execution timeout (30s)"
        except FileNotFoundError:
            return 1, "", "Error: saurav.py interpreter not found"

    def _diagnose(self, error_output, source_lines):
        """Run diagnostic rules and return best diagnosis."""
        candidates = []
        for rule in DIAGNOSTIC_RULES:
            try:
                d = rule(error_output, source_lines)
                if d:
                    # Check we haven't already tried this exact fix
                    sig = f"{d.error_type}:{d.line_num}:{d.fix_description}"
                    already_tried = any(
                        h["diagnosis"]["error_type"] == d.error_type and
                        h["diagnosis"]["line_num"] == d.line_num and
                        h.get("applied")
                        for h in self.history
                    )
                    if not already_tried:
                        candidates.append(d)
            except Exception:
                continue

        if not candidates:
            return None

        # Pick highest confidence
        candidates.sort(key=lambda d: d.confidence, reverse=True)
        return candidates[0]

    def _apply_patch(self, source_lines, patch):
        """Apply a patch: (line_num, old_text, new_text)."""
        line_num, old_text, new_text = patch
        lines = list(source_lines)

        if old_text is None:
            # Insert before line_num
            if line_num >= len(lines):
                lines.append(new_text)
            else:
                lines.insert(line_num, new_text)
        else:
            # Replace
            if line_num < len(lines):
                lines[line_num] = new_text
            else:
                return None

        return "".join(lines)

    def _show_patch(self, patch, source_lines):
        """Display a patch diff."""
        line_num, old_text, new_text = patch
        if old_text is None:
            print(f"   + Insert at line {line_num + 1}:")
            for l in new_text.splitlines():
                print(f"     + {l}")
        else:
            print(f"   @ line {line_num + 1}:")
            print(f"     - {old_text.rstrip()}")
            print(f"     + {new_text.rstrip()}")

    def _save_history(self):
        """Append run to persistent history."""
        history_data = {"runs": []}
        if os.path.exists(HEAL_HISTORY):
            try:
                with open(HEAL_HISTORY, 'r') as f:
                    history_data = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

        history_data["runs"].append({
            "file": self.filename,
            "timestamp": datetime.now().isoformat(),
            "attempts": len(self.history),
            "healed": any(h.get("applied") for h in self.history),
            "details": self.history
        })

        # Keep last 100 runs
        history_data["runs"] = history_data["runs"][-100:]

        with open(HEAL_HISTORY, 'w') as f:
            json.dump(history_data, f, indent=2)

    def generate_report(self):
        """Generate an HTML healing report."""
        attempts_html = ""
        for h in self.history:
            d = h["diagnosis"]
            status = "✅ Applied" if h.get("applied") else "⚠️ Not applied"
            attempts_html += f"""
            <div class="attempt">
                <div class="attempt-header">Attempt #{h['attempt']} — {status}</div>
                <table>
                    <tr><td><strong>Error Type</strong></td><td>{d['error_type']}</td></tr>
                    <tr><td><strong>Root Cause</strong></td><td>{d['root_cause']}</td></tr>
                    <tr><td><strong>Fix</strong></td><td>{d['fix_description']}</td></tr>
                    <tr><td><strong>Confidence</strong></td><td>{d['confidence']:.0%}</td></tr>
                    <tr><td><strong>Line</strong></td><td>{d.get('line_num', 'N/A')}</td></tr>
                </table>
                <pre class="error">{h.get('error', '')[:200]}</pre>
            </div>"""

        kb_stats = self.kb.stats()

        html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>sauravheal — Healing Report</title>
<style>
  :root {{ --bg: #0d1117; --card: #161b22; --border: #30363d; --text: #e6edf3;
           --green: #3fb950; --red: #f85149; --yellow: #d29922; --blue: #58a6ff; }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:var(--bg); color:var(--text); font-family:'Segoe UI',sans-serif;
          padding:2rem; max-width:900px; margin:0 auto; }}
  h1 {{ color:var(--green); margin-bottom:.5rem; }}
  .subtitle {{ color:#8b949e; margin-bottom:2rem; }}
  .stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
            gap:1rem; margin-bottom:2rem; }}
  .stat {{ background:var(--card); border:1px solid var(--border); border-radius:8px;
           padding:1.2rem; text-align:center; }}
  .stat-value {{ font-size:2rem; font-weight:700; }}
  .stat-label {{ color:#8b949e; font-size:.85rem; margin-top:.3rem; }}
  .attempt {{ background:var(--card); border:1px solid var(--border); border-radius:8px;
              padding:1.2rem; margin-bottom:1rem; }}
  .attempt-header {{ font-weight:600; margin-bottom:.8rem; font-size:1.1rem; }}
  table {{ width:100%; border-collapse:collapse; margin-bottom:.8rem; }}
  td {{ padding:.4rem .8rem; border-bottom:1px solid var(--border); }}
  td:first-child {{ width:130px; color:#8b949e; }}
  .error {{ background:#1a1a2e; color:var(--red); padding:.8rem; border-radius:4px;
            font-size:.85rem; overflow-x:auto; white-space:pre-wrap; }}
  .kb {{ background:var(--card); border:1px solid var(--border); border-radius:8px;
         padding:1.2rem; margin-top:2rem; }}
  .kb h2 {{ color:var(--blue); margin-bottom:1rem; }}
</style></head><body>
<h1>🩺 sauravheal — Healing Report</h1>
<p class="subtitle">{self.filename} — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>

<div class="stats">
  <div class="stat"><div class="stat-value">{len(self.history)}</div><div class="stat-label">Healing Attempts</div></div>
  <div class="stat"><div class="stat-value" style="color:var(--green)">{sum(1 for h in self.history if h.get('applied'))}</div><div class="stat-label">Patches Applied</div></div>
  <div class="stat"><div class="stat-value">{kb_stats['total_patterns']}</div><div class="stat-label">Known Patterns</div></div>
  <div class="stat"><div class="stat-value">{kb_stats['success_rate']:.0%}</div><div class="stat-label">KB Success Rate</div></div>
</div>

{attempts_html if attempts_html else '<p style="color:#8b949e">No healing attempts needed — program ran clean.</p>'}

<div class="kb">
  <h2>🧠 Knowledge Base</h2>
  <p>Total learned patterns: {kb_stats['total_patterns']} | Successes: {kb_stats['total_successes']} | Failures: {kb_stats['total_failures']}</p>
</div>
</body></html>"""
        return html


# ─── Utilities ──────────────────────────────────────────────────────────────────

def _edit_distance(s1, s2):
    """Simple Levenshtein distance."""
    if len(s1) < len(s2):
        return _edit_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1,
                           prev[j] + (0 if c1 == c2 else 1)))
        prev = curr
    return prev[-1]


# ─── CLI ────────────────────────────────────────────────────────────────────────

class HealConfig:
    def __init__(self, max_retries=3, dry_run=False, report=False,
                 json_output=False, watch=False, learn=False):
        self.max_retries = max_retries
        self.dry_run = dry_run
        self.report = report
        self.json_output = json_output
        self.watch = watch
        self.learn = learn


def show_history():
    """Display healing history."""
    if not os.path.exists(HEAL_HISTORY):
        print("No healing history yet.")
        return

    with open(HEAL_HISTORY, 'r') as f:
        data = json.load(f)

    runs = data.get("runs", [])
    if not runs:
        print("No healing history yet.")
        return

    print(f"\n{'='*60}")
    print(f"  sauravheal — Healing History ({len(runs)} runs)")
    print(f"{'='*60}\n")

    for run in runs[-20:]:  # Show last 20
        ts = run["timestamp"][:19]
        healed = "🩺 Healed" if run["healed"] else "✅ Clean" if run["attempts"] == 0 else "❌ Failed"
        print(f"  {ts}  {run['file']:<30}  {healed}  ({run['attempts']} attempts)")


def show_stats():
    """Display KB statistics."""
    kb = HealingKB()
    stats = kb.stats()

    print(f"\n{'='*60}")
    print(f"  sauravheal — Knowledge Base Statistics")
    print(f"{'='*60}\n")
    print(f"  Known patterns:  {stats['total_patterns']}")
    print(f"  Total successes: {stats['total_successes']}")
    print(f"  Total failures:  {stats['total_failures']}")
    print(f"  Success rate:    {stats['success_rate']:.0%}")

    if kb.patterns:
        print(f"\n  Top patterns:")
        sorted_p = sorted(kb.patterns, key=lambda p: p["success_count"], reverse=True)
        for p in sorted_p[:10]:
            rate = p["success_count"] / max(p["success_count"] + p["fail_count"], 1)
            print(f"    {p['error_sig']:<25} {p['fix_type']:<35} {rate:.0%} ({p['success_count']}✓ {p['fail_count']}✗)")


def watch_mode(filename, config):
    """Watch file and auto-heal on change."""
    print(f"👁️  Watching {filename} for changes (Ctrl+C to stop)...")
    last_hash = ""

    while True:
        try:
            with open(filename, 'r') as f:
                content = f.read()
            h = hashlib.md5(content.encode()).hexdigest()
            if h != last_hash:
                last_hash = h
                print(f"\n📝 Change detected at {datetime.now().strftime('%H:%M:%S')}")
                engine = HealingEngine(filename, config)
                engine.run()
                if config.report:
                    report_path = filename.replace('.srv', '_heal_report.html')
                    with open(report_path, 'w') as f:
                        f.write(engine.generate_report())
                    print(f"📊 Report: {report_path}")
            time.sleep(1)
        except KeyboardInterrupt:
            print("\n👋 Watch stopped.")
            break
        except FileNotFoundError:
            print(f"⚠️  File {filename} not found, waiting...")
            time.sleep(2)


def main():
    parser = argparse.ArgumentParser(
        description="sauravheal — Autonomous Self-Healing Runtime for sauravcode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python sauravheal.py program.srv              Run with auto-healing
  python sauravheal.py program.srv --dry-run    Preview fixes without applying
  python sauravheal.py program.srv --report     Generate HTML healing report
  python sauravheal.py program.srv --watch      Auto-heal on file change
  python sauravheal.py --history                Show healing history
  python sauravheal.py --stats                  Knowledge base statistics"""
    )

    parser.add_argument("file", nargs="?", help="The .srv file to run")
    parser.add_argument("--max-retries", type=int, default=3, help="Max healing attempts (default: 3)")
    parser.add_argument("--dry-run", action="store_true", help="Show patches without applying")
    parser.add_argument("--report", action="store_true", help="Generate HTML healing report")
    parser.add_argument("--json", dest="json_output", action="store_true", help="JSON output")
    parser.add_argument("--watch", action="store_true", help="Auto-heal on file change")
    parser.add_argument("--learn", action="store_true", help="Learn patterns without patching")
    parser.add_argument("--history", action="store_true", help="Show healing history")
    parser.add_argument("--stats", action="store_true", help="KB statistics")

    args = parser.parse_args()

    if args.history:
        show_history()
        return
    if args.stats:
        show_stats()
        return

    if not args.file:
        parser.print_help()
        return

    config = HealConfig(
        max_retries=args.max_retries,
        dry_run=args.dry_run or args.learn,
        report=args.report,
        json_output=args.json_output,
        watch=args.watch,
        learn=args.learn
    )

    if args.watch:
        watch_mode(args.file, config)
        return

    engine = HealingEngine(args.file, config)
    success = engine.run()

    if config.json_output:
        output = {
            "file": args.file,
            "success": success,
            "attempts": len(engine.history),
            "history": engine.history,
            "kb_stats": engine.kb.stats()
        }
        print(json.dumps(output, indent=2))

    if config.report:
        report_path = args.file.replace('.srv', '_heal_report.html')
        with open(report_path, 'w') as f:
            f.write(engine.generate_report())
        print(f"\n📊 Report saved: {report_path}")


if __name__ == "__main__":
    main()
