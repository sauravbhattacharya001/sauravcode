#!/usr/bin/env python3
"""sauravprophet — Autonomous Test Case Generator for sauravcode.

Reads .srv source files, discovers functions, analyzes their parameters,
branches, and edge cases, then automatically generates test .srv files.
Optionally runs generated tests and produces an interactive HTML report.

Features:
    • Function discovery via regex-based .srv parsing
    • Branch analysis — extracts boundary values from comparisons
    • Three generation strategies: smart (default), edge, random
    • Output prediction for simple arithmetic/logic functions
    • Interactive HTML report with pass/fail matrix and prediction accuracy

Usage:
    python sauravprophet.py file.srv                    # Analyze and generate tests
    python sauravprophet.py path/to/dir                 # Scan all .srv files
    python sauravprophet.py file.srv --run              # Generate AND run tests
    python sauravprophet.py file.srv --html report.html # Interactive HTML report
    python sauravprophet.py file.srv --json             # JSON output
    python sauravprophet.py file.srv --out tests/       # Output test files to dir
    python sauravprophet.py file.srv --strategy edge    # Focus on edge cases
    python sauravprophet.py file.srv --strategy random  # Random value generation
    python sauravprophet.py file.srv --strategy smart   # Smart analysis (default)
    python sauravprophet.py file.srv --max-tests 50     # Limit total test cases
    python sauravprophet.py file.srv --predict          # Predict expected output
"""

import sys
import os
import re
import json as _json
import math
import argparse
import subprocess
import random as _random
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple, Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _srv_utils import find_srv_files as _find_srv_files
from _termcolors import colors as _colors

# ── Ensure UTF-8 stdout on Windows ──────────────────────────────────
if sys.platform == "win32":
    import io
    for _s in ("stdout", "stderr"):
        _cur = getattr(sys, _s)
        if hasattr(_cur, "buffer"):
            setattr(sys, _s, io.TextIOWrapper(_cur.buffer, encoding="utf-8",
                                              errors="replace", line_buffering=True))


# ═══════════════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class FuncInfo:
    """Discovered function information."""
    name: str
    params: List[str]
    body_lines: List[str]
    line_number: int
    file_path: str
    is_recursive: bool = False
    comparisons: List[Dict] = field(default_factory=list)
    uses_strings: bool = False
    uses_lists: bool = False
    uses_math: bool = False
    has_conditionals: bool = False
    return_count: int = 0


@dataclass
class TestCase:
    """A generated test case for a function."""
    func_name: str
    args: List[Any]
    arg_descriptions: List[str]
    strategy: str
    predicted_output: Optional[Any] = None
    prediction_confidence: str = "low"
    actual_output: Optional[str] = None
    passed: Optional[bool] = None
    error: Optional[str] = None


@dataclass
class ProphetReport:
    """Full analysis report."""
    file_path: str
    functions: List[FuncInfo]
    test_cases: List[TestCase]
    total_functions: int = 0
    total_tests: int = 0
    tests_run: int = 0
    tests_passed: int = 0
    prediction_accuracy: float = 0.0


# ═══════════════════════════════════════════════════════════════════════
# Function discovery
# ═══════════════════════════════════════════════════════════════════════

_FUNC_RE = re.compile(r'^function\s+([a-zA-Z_]\w*)(?:\s+(.*))?$')
_IF_RE = re.compile(r'^\s*if\s+(.+)$')
_CMP_RE = re.compile(r'(\w+)\s*(==|!=|<=|>=|<|>)\s*(\S+)')
_RETURN_RE = re.compile(r'^\s*return\b', re.MULTILINE)
_CALL_RE = re.compile(r'\b([a-zA-Z_]\w*)\s')
_STRING_LITERAL_RE = re.compile(r'"[^"]*"')
_LIST_LITERAL_RE = re.compile(r'\[.*?\]')
_MATH_OPS_RE = re.compile(r'[\+\-\*/%]')
_FOR_RE = re.compile(r'^\s*for\b')
_WHILE_RE = re.compile(r'^\s*while\b')


def _get_indent(line: str) -> int:
    """Return indentation level in spaces."""
    count = 0
    for ch in line:
        if ch == ' ':
            count += 1
        elif ch == '\t':
            count += 4
        else:
            break
    return count


def discover_functions(source: str, file_path: str = "<stdin>") -> List[FuncInfo]:
    """Parse .srv source and discover all function definitions."""
    functions = []
    lines = source.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        m = _FUNC_RE.match(stripped)
        if m:
            name = m.group(1)
            params_str = m.group(2) or ""
            params = params_str.split() if params_str.strip() else []
            func_indent = _get_indent(line)
            body_lines = []
            j = i + 1
            while j < len(lines):
                if lines[j].strip() == '':
                    body_lines.append(lines[j])
                    j += 1
                    continue
                if _get_indent(lines[j]) > func_indent:
                    body_lines.append(lines[j])
                    j += 1
                else:
                    break
            # Analyze function body
            body_text = '\n'.join(body_lines)
            func = FuncInfo(
                name=name,
                params=params,
                body_lines=body_lines,
                line_number=i + 1,
                file_path=file_path,
            )
            # Check recursion
            func.is_recursive = bool(re.search(r'\b' + re.escape(name) + r'\b', body_text))
            # Check conditionals
            func.has_conditionals = any(_IF_RE.match(bl) for bl in body_lines)
            # Extract comparisons
            for bl in body_lines:
                if_m = _IF_RE.match(bl)
                if if_m:
                    cond = if_m.group(1)
                    for cm in _CMP_RE.finditer(cond):
                        func.comparisons.append({
                            'var': cm.group(1),
                            'op': cm.group(2),
                            'value': cm.group(3),
                        })
            # Check usage patterns
            func.uses_strings = bool(_STRING_LITERAL_RE.search(body_text))
            func.uses_lists = bool(_LIST_LITERAL_RE.search(body_text))
            func.uses_math = bool(_MATH_OPS_RE.search(body_text))
            func.return_count = len(_RETURN_RE.findall(body_text))
            functions.append(func)
            i = j
        else:
            i += 1
    return functions


# ═══════════════════════════════════════════════════════════════════════
# Test value generation
# ═══════════════════════════════════════════════════════════════════════

def _parse_num(s: str) -> Optional[float]:
    """Try to parse a numeric value from a string."""
    try:
        v = float(s)
        return int(v) if v == int(v) else v
    except (ValueError, OverflowError):
        return None


def _boundary_values(comparisons: List[Dict], param_name: str) -> List[Any]:
    """Extract boundary test values from comparisons involving param."""
    values = []
    for cmp in comparisons:
        if cmp['var'] == param_name:
            num = _parse_num(cmp['value'])
            if num is not None:
                op = cmp['op']
                values.append(num)
                if op in ('<', '>='):
                    values.extend([num - 1, num + 1])
                elif op in ('>', '<='):
                    values.extend([num - 1, num + 1])
                elif op == '==':
                    values.extend([num - 1, num + 1])
                elif op == '!=':
                    pass  # value itself is the interesting case
    return list(set(values))


_DEFAULT_NUMERIC = [0, 1, -1, 5, 10, 100]
_DEFAULT_STRING = ['""', '"hello"', '"a"', '"test string with spaces"']
_DEFAULT_LIST = ['[]', '[1]', '[1, 2, 3]', '[0, -1, 99]']
_DEFAULT_BOOL = ['true', 'false']


def _infer_param_type(func: FuncInfo, param: str) -> str:
    """Heuristically infer parameter type from function body usage."""
    body = '\n'.join(func.body_lines)
    # Check if compared with string
    if re.search(r'\b' + re.escape(param) + r'\s*==\s*"', body):
        return 'string'
    # Check if used with list ops
    if re.search(r'\b' + re.escape(param) + r'\s*\[', body) or \
       re.search(r'len\s+' + re.escape(param), body) or \
       re.search(r'append\s+' + re.escape(param), body):
        return 'list'
    # Check if compared with bool
    if re.search(r'\b' + re.escape(param) + r'\s*==\s*(true|false)', body):
        return 'bool'
    # Default to numeric
    return 'numeric'


def generate_test_values(func: FuncInfo, strategy: str = "smart") -> List[List[Any]]:
    """Generate test value combinations for a function's parameters."""
    if not func.params:
        return [[]]  # One test with no args

    param_values: Dict[str, List[Any]] = {}
    for param in func.params:
        ptype = _infer_param_type(func, param)

        if strategy == "random":
            if ptype == 'string':
                vals = [f'"rand_{_random.randint(0,999)}"']
            elif ptype == 'list':
                vals = [f'[{_random.randint(-10,10)}, {_random.randint(-10,10)}]']
            elif ptype == 'bool':
                vals = [_random.choice(['true', 'false'])]
            else:
                vals = [_random.randint(-100, 100) for _ in range(3)]
        elif strategy == "edge":
            if ptype == 'string':
                vals = ['""', '"a"', '"' + 'x' * 50 + '"']
            elif ptype == 'list':
                vals = ['[]', '[0]', '[' + ','.join(str(i) for i in range(20)) + ']']
            elif ptype == 'bool':
                vals = ['true', 'false']
            else:
                vals = [0, -1, 1, -999, 999]
                boundary = _boundary_values(func.comparisons, param)
                vals.extend(boundary)
                vals = list(set(vals))
        else:  # smart
            if ptype == 'string':
                vals = _DEFAULT_STRING[:2]
            elif ptype == 'list':
                vals = _DEFAULT_LIST[:2]
            elif ptype == 'bool':
                vals = _DEFAULT_BOOL
            else:
                vals = [0, 1, -1]
                boundary = _boundary_values(func.comparisons, param)
                if boundary:
                    vals.extend(boundary)
                    vals = list(set(vals))
                else:
                    vals.extend([5, 10])
                vals = sorted(set(vals))

        param_values[param] = vals

    # Generate combinations (capped to avoid explosion)
    combos = _cartesian_product(
        [param_values[p] for p in func.params],
        max_combos=30
    )
    return combos


def _cartesian_product(lists: List[List], max_combos: int = 30) -> List[List]:
    """Compute cartesian product, capped at max_combos."""
    if not lists:
        return [[]]
    result = [[]]
    for lst in lists:
        new_result = []
        for combo in result:
            for val in lst:
                new_result.append(combo + [val])
                if len(new_result) >= max_combos:
                    return new_result
        result = new_result
    return result


# ═══════════════════════════════════════════════════════════════════════
# Output prediction
# ═══════════════════════════════════════════════════════════════════════

def _predict_simple_arithmetic(func: FuncInfo, args: List[Any]) -> Tuple[Optional[Any], str]:
    """Try to predict output for simple single-return arithmetic functions."""
    body = [l.strip() for l in func.body_lines if l.strip() and not l.strip().startswith('#')]
    # Only predict for simple functions: single return, no conditionals, no recursion
    if func.is_recursive or func.has_conditionals:
        return None, "low"
    returns = [l for l in body if l.startswith('return ')]
    if len(returns) != 1:
        return None, "low"
    expr = returns[0][7:].strip()  # After 'return '
    # Build a mapping of param name -> arg value
    env = {}
    for p, a in zip(func.params, args):
        try:
            env[p] = float(a) if isinstance(a, (int, float)) else a
        except (ValueError, TypeError):
            return None, "low"
    # Try to evaluate simple arithmetic
    # Replace param names with values in expression
    eval_expr = expr
    # Sort by length descending to avoid partial replacement
    for p in sorted(func.params, key=len, reverse=True):
        if p in env and isinstance(env[p], (int, float)):
            eval_expr = re.sub(r'\b' + re.escape(p) + r'\b', str(env[p]), eval_expr)
    # Check if expression is pure arithmetic
    if re.match(r'^[\d\.\s\+\-\*/%\(\)]+$', eval_expr):
        try:
            result = eval(eval_expr)  # Safe: only numbers and operators
            if isinstance(result, float) and result == int(result):
                result = int(result)
            return result, "high"
        except Exception:
            return None, "low"
    return None, "low"


def predict_output(func: FuncInfo, args: List[Any]) -> Tuple[Optional[Any], str]:
    """Predict expected output for a function call. Returns (value, confidence)."""
    # Only predict for numeric args for now
    numeric_args = all(isinstance(a, (int, float)) for a in args)
    if numeric_args:
        return _predict_simple_arithmetic(func, args)
    return None, "low"


# ═══════════════════════════════════════════════════════════════════════
# Test .srv generation
# ═══════════════════════════════════════════════════════════════════════

def _format_arg(val: Any) -> str:
    """Format an argument value for .srv source code."""
    if isinstance(val, str):
        return val  # Already formatted (e.g., '"hello"' or 'true')
    if isinstance(val, float):
        return str(val)
    return str(val)


def generate_test_srv(func: FuncInfo, test_cases: List[TestCase],
                      source_lines: List[str]) -> str:
    """Generate a .srv test file for a function."""
    parts = ['# Auto-generated test file by sauravprophet']
    parts.append(f'# Testing function: {func.name}')
    parts.append(f'# Parameters: {", ".join(func.params) if func.params else "none"}')
    parts.append(f'# Generated {len(test_cases)} test cases')
    parts.append('')

    # Include the function definition
    start = func.line_number - 1
    end = start + 1 + len(func.body_lines)
    func_source = '\n'.join(source_lines[start:end])
    parts.append(func_source)
    parts.append('')

    # Also include any helper functions referenced in the body
    body_text = '\n'.join(func.body_lines)
    # Simple heuristic: include functions called in body (won't handle all cases)

    parts.append('# ── Test Cases ──')
    for i, tc in enumerate(test_cases):
        args_str = ' '.join(_format_arg(a) for a in tc.args)
        call = f'{func.name} {args_str}'.strip()
        parts.append(f'# Test {i+1}: {", ".join(tc.arg_descriptions)}')
        parts.append(f'_result_{i} = {call}')
        parts.append(f'print _result_{i}')
        if tc.predicted_output is not None:
            parts.append(f'# Expected: {tc.predicted_output} (confidence: {tc.prediction_confidence})')
        parts.append('')
    return '\n'.join(parts)


# ═══════════════════════════════════════════════════════════════════════
# Test runner
# ═══════════════════════════════════════════════════════════════════════

def run_test_file(test_srv_path: str, interpreter: str = None) -> Tuple[str, bool]:
    """Run a generated .srv test file and capture output."""
    if interpreter is None:
        interpreter = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'saurav.py')
    try:
        result = subprocess.run(
            [sys.executable, interpreter, test_srv_path],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout.strip()
        success = result.returncode == 0
        if not success and result.stderr:
            output += '\n' + result.stderr.strip()
        return output, success
    except subprocess.TimeoutExpired:
        return "TIMEOUT: execution exceeded 10s", False
    except Exception as e:
        return f"ERROR: {e}", False


# ═══════════════════════════════════════════════════════════════════════
# HTML report
# ═══════════════════════════════════════════════════════════════════════

def generate_html_report(reports: List[ProphetReport]) -> str:
    """Generate an interactive HTML report."""
    total_funcs = sum(r.total_functions for r in reports)
    total_tests = sum(r.total_tests for r in reports)
    total_run = sum(r.tests_run for r in reports)
    total_pass = sum(r.tests_passed for r in reports)
    pass_rate = (total_pass / total_run * 100) if total_run > 0 else 0

    # Count prediction accuracy
    pred_total = 0
    pred_correct = 0
    for r in reports:
        for tc in r.test_cases:
            if tc.predicted_output is not None and tc.actual_output is not None:
                pred_total += 1
                actual_clean = tc.actual_output.strip().split('\n')[-1] if tc.actual_output else ""
                if str(tc.predicted_output) == actual_clean:
                    pred_correct += 1
    pred_acc = (pred_correct / pred_total * 100) if pred_total > 0 else 0

    func_rows = []
    for r in reports:
        for f in r.functions:
            ftests = [tc for tc in r.test_cases if tc.func_name == f.name]
            passed = sum(1 for tc in ftests if tc.passed is True)
            failed = sum(1 for tc in ftests if tc.passed is False)
            untested = sum(1 for tc in ftests if tc.passed is None)
            func_rows.append(f"""
            <tr>
                <td><strong>{_html_esc(f.name)}</strong></td>
                <td>{_html_esc(os.path.basename(f.file_path))}</td>
                <td>{len(f.params)}</td>
                <td>{"✓" if f.has_conditionals else ""}</td>
                <td>{"✓" if f.is_recursive else ""}</td>
                <td>{len(ftests)}</td>
                <td class="pass">{passed}</td>
                <td class="fail">{failed}</td>
                <td class="untested">{untested}</td>
            </tr>""")

    test_rows = []
    for r in reports:
        for tc in r.test_cases:
            args_str = ', '.join(_format_arg(a) for a in tc.args)
            status_cls = "pass" if tc.passed else ("fail" if tc.passed is False else "untested")
            status_txt = "PASS" if tc.passed else ("FAIL" if tc.passed is False else "—")
            pred_str = str(tc.predicted_output) if tc.predicted_output is not None else "—"
            actual_str = _html_esc(tc.actual_output or "—")
            test_rows.append(f"""
            <tr class="{status_cls}-row">
                <td>{_html_esc(tc.func_name)}</td>
                <td><code>{_html_esc(args_str)}</code></td>
                <td>{_html_esc(tc.strategy)}</td>
                <td>{_html_esc(pred_str)}</td>
                <td>{actual_str}</td>
                <td class="{status_cls}">{status_txt}</td>
            </tr>""")

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>sauravprophet — Test Generation Report</title>
<style>
  :root {{ --bg:#0d1117; --card:#161b22; --border:#30363d; --text:#e6edf3;
           --green:#3fb950; --red:#f85149; --yellow:#d29922; --blue:#58a6ff;
           --cyan:#39d2c0; }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Segoe UI',system-ui,sans-serif; background:var(--bg); color:var(--text); padding:2rem; }}
  h1 {{ color:var(--cyan); margin-bottom:0.5rem; }}
  .subtitle {{ color:#8b949e; margin-bottom:2rem; }}
  .stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:1rem; margin-bottom:2rem; }}
  .stat {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:1.5rem; text-align:center; }}
  .stat .num {{ font-size:2.5rem; font-weight:bold; }}
  .stat .label {{ color:#8b949e; font-size:0.9rem; }}
  .stat.green .num {{ color:var(--green); }}
  .stat.blue .num {{ color:var(--blue); }}
  .stat.yellow .num {{ color:var(--yellow); }}
  .stat.cyan .num {{ color:var(--cyan); }}
  table {{ width:100%; border-collapse:collapse; margin-bottom:2rem; background:var(--card); border-radius:12px; overflow:hidden; }}
  th {{ background:#21262d; padding:0.8rem; text-align:left; font-size:0.85rem; color:#8b949e; text-transform:uppercase; }}
  td {{ padding:0.7rem 0.8rem; border-top:1px solid var(--border); font-size:0.9rem; }}
  tr:hover {{ background:#1c2128; }}
  .pass {{ color:var(--green); font-weight:bold; }}
  .fail {{ color:var(--red); font-weight:bold; }}
  .untested {{ color:#8b949e; }}
  .pass-row td:first-child {{ border-left:3px solid var(--green); }}
  .fail-row td:first-child {{ border-left:3px solid var(--red); }}
  code {{ background:#21262d; padding:2px 6px; border-radius:4px; font-size:0.85rem; }}
  .gauge {{ width:200px; height:200px; margin:0 auto; }}
  section {{ margin-bottom:2rem; }}
  h2 {{ color:var(--blue); margin-bottom:1rem; }}
  .filter {{ margin-bottom:1rem; }}
  .filter input {{ background:var(--card); border:1px solid var(--border); color:var(--text);
                   padding:0.5rem 1rem; border-radius:8px; width:300px; }}
</style></head><body>
<h1>🔮 sauravprophet — Test Generation Report</h1>
<p class="subtitle">Autonomous test case generation for sauravcode</p>

<div class="stats">
  <div class="stat blue"><div class="num">{total_funcs}</div><div class="label">Functions Found</div></div>
  <div class="stat cyan"><div class="num">{total_tests}</div><div class="label">Tests Generated</div></div>
  <div class="stat green"><div class="num">{pass_rate:.0f}%</div><div class="label">Pass Rate</div></div>
  <div class="stat yellow"><div class="num">{pred_acc:.0f}%</div><div class="label">Prediction Accuracy</div></div>
</div>

<section>
<h2>📋 Function Summary</h2>
<table>
<tr><th>Function</th><th>File</th><th>Params</th><th>Branches</th><th>Recursive</th><th>Tests</th><th>Pass</th><th>Fail</th><th>Untested</th></tr>
{''.join(func_rows)}
</table>
</section>

<section>
<h2>🧪 Test Cases</h2>
<div class="filter"><input type="text" id="filter" placeholder="Filter by function name..." oninput="filterTests()"></div>
<table id="testTable">
<tr><th>Function</th><th>Arguments</th><th>Strategy</th><th>Predicted</th><th>Actual</th><th>Status</th></tr>
{''.join(test_rows)}
</table>
</section>

<script>
function filterTests() {{
  const q = document.getElementById('filter').value.toLowerCase();
  document.querySelectorAll('#testTable tr:not(:first-child)').forEach(r => {{
    r.style.display = r.cells[0].textContent.toLowerCase().includes(q) ? '' : 'none';
  }});
}}
</script>
</body></html>"""
    return html


def _html_esc(s: str) -> str:
    """Escape HTML special characters."""
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


# ═══════════════════════════════════════════════════════════════════════
# Orchestrator
# ═══════════════════════════════════════════════════════════════════════

def analyze_file(file_path: str, strategy: str = "smart",
                 max_tests: int = 100, do_predict: bool = False,
                 do_run: bool = False, out_dir: Optional[str] = None) -> ProphetReport:
    """Analyze a single .srv file and generate test cases."""
    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
        source = f.read()
    source_lines = source.split('\n')
    functions = discover_functions(source, file_path)

    all_tests: List[TestCase] = []
    tests_remaining = max_tests

    for func in functions:
        if tests_remaining <= 0:
            break
        combos = generate_test_values(func, strategy)
        for args in combos[:tests_remaining]:
            descs = []
            for p, a in zip(func.params, args):
                descs.append(f"{p}={a}")
            if not func.params:
                descs.append("no args")
            tc = TestCase(
                func_name=func.name,
                args=args,
                arg_descriptions=descs,
                strategy=strategy,
            )
            if do_predict:
                pred, conf = predict_output(func, args)
                tc.predicted_output = pred
                tc.prediction_confidence = conf
            all_tests.append(tc)
            tests_remaining -= 1

    # Run tests if requested
    if do_run and all_tests:
        _run_generated_tests(functions, all_tests, source_lines, out_dir, file_path)

    # Write test files if out_dir specified (even without --run)
    if out_dir and not do_run:
        _write_test_files(functions, all_tests, source_lines, out_dir, file_path)

    report = ProphetReport(
        file_path=file_path,
        functions=functions,
        test_cases=all_tests,
        total_functions=len(functions),
        total_tests=len(all_tests),
        tests_run=sum(1 for tc in all_tests if tc.passed is not None),
        tests_passed=sum(1 for tc in all_tests if tc.passed is True),
    )
    return report


def _write_test_files(functions, all_tests, source_lines, out_dir, file_path):
    """Write .srv test files to the output directory."""
    os.makedirs(out_dir, exist_ok=True)
    for func in functions:
        ftests = [tc for tc in all_tests if tc.func_name == func.name]
        if not ftests:
            continue
        srv_code = generate_test_srv(func, ftests, source_lines)
        base = os.path.splitext(os.path.basename(file_path))[0]
        out_path = os.path.join(out_dir, f"test_{base}_{func.name}.srv")
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(srv_code)


def _run_generated_tests(functions, all_tests, source_lines, out_dir, file_path):
    """Generate and run test .srv files, capturing results."""
    tmp_dir = out_dir or tempfile.mkdtemp(prefix='sauravprophet_')
    os.makedirs(tmp_dir, exist_ok=True)

    for func in functions:
        ftests = [tc for tc in all_tests if tc.func_name == func.name]
        if not ftests:
            continue
        srv_code = generate_test_srv(func, ftests, source_lines)
        base = os.path.splitext(os.path.basename(file_path))[0]
        test_path = os.path.join(tmp_dir, f"test_{base}_{func.name}.srv")
        with open(test_path, 'w', encoding='utf-8') as f:
            f.write(srv_code)

        output, success = run_test_file(test_path)
        output_lines = output.strip().split('\n') if output.strip() else []

        # Map output lines back to test cases
        for i, tc in enumerate(ftests):
            if i < len(output_lines):
                tc.actual_output = output_lines[i]
                tc.passed = success  # All pass if interpreter succeeds
                if not success:
                    tc.error = output_lines[i] if i < len(output_lines) else "unknown"
            else:
                tc.actual_output = None
                tc.passed = False if not success else None


# ═══════════════════════════════════════════════════════════════════════
# CLI output
# ═══════════════════════════════════════════════════════════════════════

def print_report(reports: List[ProphetReport], c):
    """Print a summary report to the terminal."""
    total_funcs = sum(r.total_functions for r in reports)
    total_tests = sum(r.total_tests for r in reports)
    total_run = sum(r.tests_run for r in reports)
    total_pass = sum(r.tests_passed for r in reports)

    print(c.bold(c.cyan("\n🔮 sauravprophet — Test Generation Report\n")))

    for r in reports:
        print(c.bold(f"  📄 {r.file_path}"))
        for func in r.functions:
            ftests = [tc for tc in r.test_cases if tc.func_name == func.name]
            passed = sum(1 for tc in ftests if tc.passed is True)
            failed = sum(1 for tc in ftests if tc.passed is False)
            untested = sum(1 for tc in ftests if tc.passed is None)
            flags = []
            if func.has_conditionals:
                flags.append("branches")
            if func.is_recursive:
                flags.append("recursive")
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            params_str = ', '.join(func.params) if func.params else 'none'

            status_parts = []
            if passed:
                status_parts.append(c.green(f"{passed} pass"))
            if failed:
                status_parts.append(c.red(f"{failed} fail"))
            if untested:
                status_parts.append(c.dim(f"{untested} untested"))
            status = ' / '.join(status_parts) if status_parts else c.dim("no tests")

            print(f"    {c.bold(func.name)}({params_str}){flag_str} → "
                  f"{len(ftests)} tests: {status}")

            # Show predictions
            for tc in ftests:
                if tc.predicted_output is not None:
                    args_str = ', '.join(str(a) for a in tc.args)
                    pred = str(tc.predicted_output)
                    conf = tc.prediction_confidence
                    if tc.actual_output is not None:
                        match = "✓" if str(tc.predicted_output) == tc.actual_output.strip() else "✗"
                        print(f"      {c.dim(f'predict({args_str})')} → {pred} "
                              f"({conf}) {c.green(match) if match == '✓' else c.red(match)}")
                    else:
                        print(f"      {c.dim(f'predict({args_str})')} → {pred} ({conf})")
        print()

    # Summary
    print(c.bold("  ── Summary ──"))
    print(f"    Functions: {c.cyan(str(total_funcs))}")
    print(f"    Tests:     {c.cyan(str(total_tests))}")
    if total_run > 0:
        rate = total_pass / total_run * 100
        print(f"    Passed:    {c.green(str(total_pass))}/{total_run} ({rate:.0f}%)")
    print()


def main():
    parser = argparse.ArgumentParser(
        prog='sauravprophet',
        description='Autonomous test case generator for sauravcode (.srv programs).')
    parser.add_argument('paths', nargs='*', default=['.'],
                        help='.srv files or directories to analyze')
    parser.add_argument('--run', action='store_true',
                        help='Generate AND run test files')
    parser.add_argument('--html', metavar='FILE',
                        help='Generate interactive HTML report')
    parser.add_argument('--json', action='store_true',
                        help='JSON output')
    parser.add_argument('--out', metavar='DIR',
                        help='Output directory for generated test .srv files')
    parser.add_argument('--strategy', choices=['smart', 'edge', 'random'],
                        default='smart', help='Test generation strategy (default: smart)')
    parser.add_argument('--max-tests', type=int, default=100,
                        help='Maximum total test cases (default: 100)')
    parser.add_argument('--predict', action='store_true',
                        help='Predict expected output for each test')
    parser.add_argument('--recursive', action='store_true',
                        help='Recurse into subdirectories')
    args = parser.parse_args()

    c = _colors()
    files = _find_srv_files(args.paths, recursive=args.recursive)
    if not files:
        print(c.yellow("No .srv files found."))
        sys.exit(1)

    reports = []
    for fp in files:
        report = analyze_file(
            fp,
            strategy=args.strategy,
            max_tests=args.max_tests,
            do_predict=args.predict,
            do_run=args.run,
            out_dir=args.out,
        )
        reports.append(report)

    if args.json:
        out = []
        for r in reports:
            out.append({
                'file': r.file_path,
                'functions': [asdict(f) for f in r.functions],
                'test_cases': [asdict(tc) for tc in r.test_cases],
                'total_functions': r.total_functions,
                'total_tests': r.total_tests,
                'tests_run': r.tests_run,
                'tests_passed': r.tests_passed,
            })
        print(_json.dumps(out, indent=2, default=str))
    elif args.html:
        html = generate_html_report(reports)
        with open(args.html, 'w', encoding='utf-8') as f:
            f.write(html)
        print(c.green(f"✓ HTML report written to {args.html}"))
    else:
        print_report(reports, c)


if __name__ == '__main__':
    main()
