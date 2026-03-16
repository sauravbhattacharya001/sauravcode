#!/usr/bin/env python3
"""sauravci — Local CI runner for sauravcode projects.

Orchestrates lint, type-check, test, metrics, and security scans in one
command.  Produces a unified pass/fail summary with optional HTML dashboard.

Usage:
    python sauravci.py                        # Run all checks in current dir
    python sauravci.py src/                   # Run on specific directory
    python sauravci.py --skip lint,security   # Skip specific stages
    python sauravci.py --only test,lint       # Run only specific stages
    python sauravci.py --html report.html     # Generate HTML dashboard
    python sauravci.py --json                 # JSON summary output
    python sauravci.py --strict               # Fail on warnings too
    python sauravci.py --parallel             # Run independent stages concurrently
    python sauravci.py --config ci.json       # Load config from file

Stages (in order):
    1. lint      — Static analysis via sauravlint
    2. typecheck — Type inference via sauravtype
    3. security  — Vulnerability scan via sauravsec
    4. metrics   — Code complexity via sauravmetrics
    5. test      — Test runner via sauravtest

Exit codes:
    0 — All stages passed
    1 — One or more stages failed
    2 — Configuration or runtime error
"""

import argparse
import json
import os
import subprocess
import sys
import time
import html as html_mod
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# ── Stage definitions ─────────────────────────────────────────────────

STAGES = [
    {
        'name': 'lint',
        'label': 'Lint',
        'description': 'Static analysis',
        'command': [sys.executable, 'sauravlint.py', '--check', '--json'],
        'tool': 'sauravlint.py',
    },
    {
        'name': 'typecheck',
        'label': 'Type Check',
        'description': 'Type inference & mismatch detection',
        'command': [sys.executable, 'sauravtype.py', '--json'],
        'tool': 'sauravtype.py',
    },
    {
        'name': 'security',
        'label': 'Security',
        'description': 'Vulnerability scanning',
        'command': [sys.executable, 'sauravsec.py', '--json'],
        'tool': 'sauravsec.py',
    },
    {
        'name': 'metrics',
        'label': 'Metrics',
        'description': 'Code complexity analysis',
        'command': [sys.executable, 'sauravmetrics.py', '--json', '--summary'],
        'tool': 'sauravmetrics.py',
    },
    {
        'name': 'test',
        'label': 'Tests',
        'description': 'Test suite execution',
        'command': [sys.executable, 'sauravtest.py', '--json', '_ci_test_results.json'],
        'tool': 'sauravtest.py',
    },
]

STAGE_NAMES = [s['name'] for s in STAGES]

# ── Colors ────────────────────────────────────────────────────────────

COLORS = {
    'green': '\033[32m',
    'red': '\033[31m',
    'yellow': '\033[33m',
    'cyan': '\033[36m',
    'bold': '\033[1m',
    'dim': '\033[2m',
    'reset': '\033[0m',
}

def _c(text, color, use_color=True):
    if not use_color:
        return str(text)
    return f"{COLORS.get(color, '')}{text}{COLORS['reset']}"


# ── Stage runner ──────────────────────────────────────────────────────

def _find_tool(tool_name, target_dir):
    """Locate tool script relative to this file or target directory."""
    here = Path(__file__).resolve().parent
    for base in [here, Path(target_dir).resolve()]:
        p = base / tool_name
        if p.exists():
            return str(p)
    return None


def run_stage(stage, targets, strict=False, use_color=True, tool_dir=None):
    """Run a single CI stage and return a result dict."""
    result = {
        'name': stage['name'],
        'label': stage['label'],
        'description': stage['description'],
        'status': 'skip',
        'duration': 0.0,
        'output': '',
        'errors': 0,
        'warnings': 0,
        'details': {},
    }

    tool_path = _find_tool(stage['tool'], tool_dir or '.')
    if not tool_path:
        result['status'] = 'skip'
        result['output'] = f"Tool {stage['tool']} not found — skipped"
        return result

    # Build command with resolved tool path
    cmd = list(stage['command'])
    cmd[1] = tool_path

    # For test stage, the json output goes to a file
    if stage['name'] == 'test':
        cmd_with_targets = cmd + targets
    else:
        cmd_with_targets = cmd + targets

    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd_with_targets,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=tool_dir,
        )
        result['duration'] = time.time() - t0
        result['output'] = proc.stdout + proc.stderr

        # Parse stage-specific results
        if stage['name'] == 'lint':
            result = _parse_lint(result, proc)
        elif stage['name'] == 'typecheck':
            result = _parse_typecheck(result, proc)
        elif stage['name'] == 'security':
            result = _parse_security(result, proc)
        elif stage['name'] == 'metrics':
            result = _parse_metrics(result, proc)
        elif stage['name'] == 'test':
            result = _parse_test(result, proc, tool_dir)

        # Determine pass/fail
        if result['status'] == 'skip':
            if proc.returncode != 0 or result['errors'] > 0:
                result['status'] = 'fail'
            elif strict and result['warnings'] > 0:
                result['status'] = 'fail'
            else:
                result['status'] = 'pass'

    except subprocess.TimeoutExpired:
        result['duration'] = time.time() - t0
        result['status'] = 'fail'
        result['output'] = 'Stage timed out after 300s'
    except Exception as e:
        result['duration'] = time.time() - t0
        result['status'] = 'error'
        result['output'] = str(e)

    return result


# ── Stage output parsers ──────────────────────────────────────────────

def _try_parse_json(text):
    """Try to extract JSON from output (may have non-JSON lines mixed in)."""
    # Try full text first
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    # Try each line
    for line in text.strip().splitlines():
        line = line.strip()
        if line.startswith('{') or line.startswith('['):
            try:
                return json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
    return None


def _parse_lint(result, proc):
    data = _try_parse_json(proc.stdout)
    if isinstance(data, list):
        errors = sum(1 for d in data if d.get('severity') == 'error')
        warnings = sum(1 for d in data if d.get('severity') == 'warning')
        result['errors'] = errors
        result['warnings'] = warnings
        result['details'] = {'issues': len(data), 'breakdown': {}}
        for d in data:
            sev = d.get('severity', 'unknown')
            result['details']['breakdown'][sev] = result['details']['breakdown'].get(sev, 0) + 1
    elif proc.returncode != 0:
        result['errors'] = 1
    return result


def _parse_typecheck(result, proc):
    data = _try_parse_json(proc.stdout)
    if isinstance(data, dict):
        issues = data.get('issues', data.get('errors', []))
        if isinstance(issues, list):
            result['errors'] = len([i for i in issues if i.get('severity') == 'error'])
            result['warnings'] = len([i for i in issues if i.get('severity') != 'error'])
            result['details'] = {'total_issues': len(issues)}
        elif isinstance(issues, int):
            result['errors'] = issues
    elif isinstance(data, list):
        result['errors'] = len(data)
        result['details'] = {'issues': data}
    elif proc.returncode != 0:
        result['errors'] = 1
    return result


def _parse_security(result, proc):
    data = _try_parse_json(proc.stdout)
    if isinstance(data, list):
        high = sum(1 for d in data if d.get('severity', '').lower() in ('high', 'critical'))
        medium = sum(1 for d in data if d.get('severity', '').lower() == 'medium')
        low = sum(1 for d in data if d.get('severity', '').lower() == 'low')
        result['errors'] = high
        result['warnings'] = medium + low
        result['details'] = {'findings': len(data), 'high': high, 'medium': medium, 'low': low}
    elif isinstance(data, dict):
        findings = data.get('findings', data.get('issues', []))
        if isinstance(findings, list):
            result['errors'] = len([f for f in findings if f.get('severity', '').lower() in ('high', 'critical')])
            result['warnings'] = len(findings) - result['errors']
            result['details'] = {'findings': len(findings)}
    elif proc.returncode != 0:
        result['errors'] = 1
    return result


def _parse_metrics(result, proc):
    data = _try_parse_json(proc.stdout)
    if isinstance(data, dict):
        result['details'] = data
        # Metrics doesn't really fail, just reports
        score = data.get('average_maintainability', data.get('score', 100))
        if isinstance(score, (int, float)) and score < 20:
            result['warnings'] = 1
    elif isinstance(data, list) and data:
        result['details'] = {'files': len(data)}
    result['status'] = 'pass'  # Metrics is informational
    return result


def _parse_test(result, proc, tool_dir):
    # Try reading test results from JSON file first
    json_file = Path(tool_dir or '.') / '_ci_test_results.json'
    data = None
    if json_file.exists():
        try:
            data = json.loads(json_file.read_text(encoding='utf-8'))
            json_file.unlink()
        except Exception:
            pass

    if data is None:
        data = _try_parse_json(proc.stdout)

    if isinstance(data, dict):
        passed = data.get('passed', 0)
        failed = data.get('failed', 0)
        skipped = data.get('skipped', 0)
        total = data.get('total', passed + failed + skipped)
        result['errors'] = failed
        result['details'] = {'total': total, 'passed': passed, 'failed': failed, 'skipped': skipped}
    elif proc.returncode != 0:
        result['errors'] = 1
    return result


# ── Console output ────────────────────────────────────────────────────

STATUS_ICONS = {
    'pass': '✓',
    'fail': '✗',
    'skip': '⊘',
    'error': '!',
}

STATUS_COLORS = {
    'pass': 'green',
    'fail': 'red',
    'skip': 'dim',
    'error': 'yellow',
}


def print_header(use_color=True):
    print()
    print(_c('━' * 60, 'cyan', use_color))
    print(_c('  sauravci — Local CI Runner', 'bold', use_color))
    print(_c('━' * 60, 'cyan', use_color))
    print()


def print_stage_start(stage, use_color=True):
    print(f"  {_c('▶', 'cyan', use_color)} {stage['label']}: {stage['description']}...", end='', flush=True)


def print_stage_result(result, use_color=True):
    icon = STATUS_ICONS.get(result['status'], '?')
    color = STATUS_COLORS.get(result['status'], 'dim')
    duration = f"{result['duration']:.1f}s"

    info_parts = []
    if result['errors'] > 0:
        info_parts.append(f"{result['errors']} errors")
    if result['warnings'] > 0:
        info_parts.append(f"{result['warnings']} warnings")
    if result['name'] == 'test' and 'total' in result.get('details', {}):
        d = result['details']
        info_parts.append(f"{d['passed']}/{d['total']} passed")
    if result['name'] == 'metrics' and result['details']:
        score = result['details'].get('average_maintainability')
        if score is not None:
            info_parts.append(f"maintainability: {score:.0f}")

    info = f" ({', '.join(info_parts)})" if info_parts else ''
    print(f" {_c(icon, color, use_color)} {_c(result['status'].upper(), color, use_color)} [{duration}]{info}")


def print_summary(results, total_time, use_color=True):
    passed = sum(1 for r in results if r['status'] == 'pass')
    failed = sum(1 for r in results if r['status'] == 'fail')
    skipped = sum(1 for r in results if r['status'] == 'skip')
    errored = sum(1 for r in results if r['status'] == 'error')

    print()
    print(_c('━' * 60, 'cyan', use_color))

    if failed == 0 and errored == 0:
        print(f"  {_c('✓ ALL CHECKS PASSED', 'green', use_color)}  "
              f"({passed} passed, {skipped} skipped) [{total_time:.1f}s]")
    else:
        print(f"  {_c('✗ CHECKS FAILED', 'red', use_color)}  "
              f"({passed} passed, {failed} failed, {errored} errors, {skipped} skipped) [{total_time:.1f}s]")

    print(_c('━' * 60, 'cyan', use_color))
    print()


# ── HTML Dashboard ────────────────────────────────────────────────────

def generate_html(results, total_time, targets):
    """Generate a self-contained HTML dashboard."""
    passed = sum(1 for r in results if r['status'] == 'pass')
    failed = sum(1 for r in results if r['status'] == 'fail')
    total = len(results)
    overall = 'PASSED' if failed == 0 else 'FAILED'
    overall_color = '#22c55e' if failed == 0 else '#ef4444'
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    stage_cards = ''
    for r in results:
        status_color = {'pass': '#22c55e', 'fail': '#ef4444', 'skip': '#9ca3af', 'error': '#f59e0b'}.get(r['status'], '#9ca3af')
        status_icon = STATUS_ICONS.get(r['status'], '?')

        details_html = ''
        if r['details']:
            details_html = '<div class="details"><pre>' + html_mod.escape(json.dumps(r['details'], indent=2)) + '</pre></div>'

        output_preview = ''
        if r['output'] and r['status'] in ('fail', 'error'):
            lines = r['output'].strip().splitlines()[-20:]
            output_preview = '<div class="output"><pre>' + html_mod.escape('\n'.join(lines)) + '</pre></div>'

        stage_cards += f"""
        <div class="card">
            <div class="card-header">
                <span class="status-badge" style="background:{status_color}">{status_icon} {r['status'].upper()}</span>
                <span class="stage-name">{html_mod.escape(r['label'])}</span>
                <span class="duration">{r['duration']:.1f}s</span>
            </div>
            <div class="card-desc">{html_mod.escape(r['description'])}</div>
            <div class="card-stats">
                {f'<span class="stat err">{r["errors"]} errors</span>' if r['errors'] else ''}
                {f'<span class="stat warn">{r["warnings"]} warnings</span>' if r['warnings'] else ''}
            </div>
            {details_html}
            {output_preview}
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>sauravci Report</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;padding:2rem}}
.container{{max-width:800px;margin:0 auto}}
h1{{font-size:1.5rem;margin-bottom:.25rem}}
.subtitle{{color:#94a3b8;font-size:.875rem;margin-bottom:1.5rem}}
.overall{{display:flex;align-items:center;gap:1rem;padding:1rem;border-radius:.75rem;margin-bottom:1.5rem;background:#1e293b}}
.overall-badge{{font-size:1.25rem;font-weight:700;padding:.5rem 1rem;border-radius:.5rem;color:#fff}}
.overall-stats{{color:#94a3b8;font-size:.875rem}}
.card{{background:#1e293b;border-radius:.75rem;padding:1rem;margin-bottom:.75rem;border-left:4px solid #334155}}
.card-header{{display:flex;align-items:center;gap:.75rem}}
.status-badge{{font-size:.75rem;font-weight:600;padding:.25rem .5rem;border-radius:.25rem;color:#fff}}
.stage-name{{font-weight:600;flex:1}}
.duration{{color:#64748b;font-size:.8rem}}
.card-desc{{color:#94a3b8;font-size:.8rem;margin-top:.25rem}}
.card-stats{{display:flex;gap:.5rem;margin-top:.5rem;flex-wrap:wrap}}
.stat{{font-size:.75rem;padding:.125rem .375rem;border-radius:.25rem}}
.stat.err{{background:#7f1d1d;color:#fca5a5}}
.stat.warn{{background:#78350f;color:#fde68a}}
.details,.output{{margin-top:.5rem}}
.details pre,.output pre{{background:#0f172a;padding:.75rem;border-radius:.5rem;font-size:.75rem;overflow-x:auto;max-height:200px;overflow-y:auto}}
</style>
</head>
<body>
<div class="container">
    <h1>sauravci Report</h1>
    <div class="subtitle">{html_mod.escape(timestamp)} · {html_mod.escape(', '.join(targets))}</div>
    <div class="overall">
        <div class="overall-badge" style="background:{overall_color}">{overall}</div>
        <div class="overall-stats">{passed}/{total} stages passed · {total_time:.1f}s total</div>
    </div>
    {stage_cards}
</div>
</body>
</html>"""


# ── Config loading ────────────────────────────────────────────────────

def load_config(config_path):
    """Load CI config from JSON file."""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Warning: Could not load config {config_path}: {e}", file=sys.stderr)
        return {}


# ── Main ──────────────────────────────────────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='sauravci',
        description='Local CI runner for sauravcode projects',
    )
    parser.add_argument('targets', nargs='*', default=['.'],
                        help='Files or directories to check (default: .)')
    parser.add_argument('--skip', type=str, default='',
                        help='Comma-separated stages to skip')
    parser.add_argument('--only', type=str, default='',
                        help='Comma-separated stages to run (exclusive)')
    parser.add_argument('--html', type=str, metavar='FILE',
                        help='Generate HTML dashboard report')
    parser.add_argument('--json', action='store_true',
                        help='Output JSON summary')
    parser.add_argument('--strict', action='store_true',
                        help='Treat warnings as failures')
    parser.add_argument('--parallel', action='store_true',
                        help='Run independent stages concurrently')
    parser.add_argument('--config', type=str,
                        help='Load configuration from JSON file')
    parser.add_argument('--no-color', action='store_true',
                        help='Disable colored output')
    parser.add_argument('--list-stages', action='store_true',
                        help='List available stages and exit')

    args = parser.parse_args(argv)
    use_color = not args.no_color and sys.stdout.isatty()

    if args.list_stages:
        for s in STAGES:
            print(f"  {s['name']:12s}  {s['description']}  ({s['tool']})")
        return 0

    # Load config overrides
    config = {}
    if args.config:
        config = load_config(args.config)

    # Determine which stages to run
    skip_set = set(args.skip.split(',')) if args.skip else set(config.get('skip', []))
    only_set = set(args.only.split(',')) if args.only else set(config.get('only', []))

    stages_to_run = []
    for s in STAGES:
        if only_set and s['name'] not in only_set:
            continue
        if s['name'] in skip_set:
            continue
        stages_to_run.append(s)

    if not stages_to_run:
        print("No stages to run.", file=sys.stderr)
        return 2

    # Resolve tool directory
    tool_dir = str(Path(__file__).resolve().parent)

    # Resolve targets
    targets = args.targets
    strict = args.strict or config.get('strict', False)

    if not args.json:
        print_header(use_color)

    # Run stages
    results = []
    t_total = time.time()

    if args.parallel and len(stages_to_run) > 1:
        if not args.json:
            print(f"  {_c('⚡', 'yellow', use_color)} Running {len(stages_to_run)} stages in parallel...\n")
        with ThreadPoolExecutor(max_workers=len(stages_to_run)) as executor:
            futures = {
                executor.submit(run_stage, s, targets, strict, use_color, tool_dir): s
                for s in stages_to_run
            }
            # Collect in submission order
            future_map = {id(futures_key): futures_key for futures_key in futures}
            done_results = {}
            for future in as_completed(futures):
                stage = futures[future]
                done_results[stage['name']] = future.result()

            for s in stages_to_run:
                r = done_results[s['name']]
                results.append(r)
                if not args.json:
                    print_stage_start(s, use_color)
                    print_stage_result(r, use_color)
    else:
        for stage in stages_to_run:
            if not args.json:
                print_stage_start(stage, use_color)
            r = run_stage(stage, targets, strict, use_color, tool_dir)
            results.append(r)
            if not args.json:
                print_stage_result(r, use_color)

    total_time = time.time() - t_total

    # Summary
    if not args.json:
        print_summary(results, total_time, use_color)

    # JSON output
    if args.json:
        summary = {
            'timestamp': datetime.now().isoformat(),
            'targets': targets,
            'total_time': round(total_time, 2),
            'stages': [{
                'name': r['name'],
                'status': r['status'],
                'duration': round(r['duration'], 2),
                'errors': r['errors'],
                'warnings': r['warnings'],
                'details': r['details'],
            } for r in results],
            'overall': 'pass' if all(r['status'] in ('pass', 'skip') for r in results) else 'fail',
        }
        print(json.dumps(summary, indent=2))

    # HTML report
    if args.html:
        html_content = generate_html(results, total_time, targets)
        Path(args.html).write_text(html_content, encoding='utf-8')
        if not args.json:
            print(f"  HTML report: {args.html}")

    # Exit code
    has_failures = any(r['status'] in ('fail', 'error') for r in results)
    return 1 if has_failures else 0


if __name__ == '__main__':
    sys.exit(main())
