#!/usr/bin/env python3
"""
sauravoracle.py — Autonomous Test Oracle for sauravcode programs.

Analyzes .srv functions, infers expected properties from naming conventions
and code patterns, generates property-based tests, and detects specification
violations. The oracle acts autonomously — it reads your code and tells you
what's likely wrong, without you writing a single test.

Usage:
    python sauravoracle.py program.srv                # Full oracle analysis
    python sauravoracle.py program.srv --infer        # Show inferred properties only
    python sauravoracle.py program.srv --test         # Run generated tests
    python sauravoracle.py program.srv --watch        # Continuous monitoring
    python sauravoracle.py program.srv --html report  # HTML report
    python sauravoracle.py program.srv --json         # JSON output
"""

import sys
import os
import re
import json
import time
import random
import argparse
import traceback
from collections import defaultdict
from io import StringIO

# Fix Windows console encoding
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from saurav import tokenize, Parser, Interpreter, ASTNode, FunctionNode


# ── Property Types ────────────────────────────────────────────────────

class Property:
    """A property the oracle inferred about a function."""
    def __init__(self, kind, description, confidence, test_fn=None):
        self.kind = kind           # e.g., 'pure', 'idempotent', 'monotonic'
        self.description = description
        self.confidence = confidence  # 0.0–1.0
        self.test_fn = test_fn     # callable(interpreter, func_name) -> (passed, detail)

    def to_dict(self):
        return {
            "kind": self.kind,
            "description": self.description,
            "confidence": round(self.confidence, 2),
        }


class Violation:
    """A specification violation detected during testing."""
    def __init__(self, func_name, property_kind, description, inputs=None, expected=None, actual=None):
        self.func_name = func_name
        self.property_kind = property_kind
        self.description = description
        self.inputs = inputs
        self.expected = expected
        self.actual = actual

    def to_dict(self):
        d = {
            "function": self.func_name,
            "property": self.property_kind,
            "description": self.description,
        }
        if self.inputs is not None:
            d["inputs"] = str(self.inputs)
        if self.expected is not None:
            d["expected"] = str(self.expected)
        if self.actual is not None:
            d["actual"] = str(self.actual)
        return d


# ── AST Analysis ──────────────────────────────────────────────────────

def _collect_functions(ast_nodes):
    """Extract all FunctionNode objects from the AST."""
    funcs = {}
    for node in ast_nodes:
        if isinstance(node, FunctionNode):
            funcs[node.name] = node
    return funcs


def _body_contains(body, node_type_name):
    """Check if function body contains a specific node type (by class name)."""
    if not isinstance(body, list):
        body = [body]
    for node in body:
        if type(node).__name__ == node_type_name:
            return True
        for attr in vars(node).values() if isinstance(node, ASTNode) else []:
            if isinstance(attr, list):
                if _body_contains(attr, node_type_name):
                    return True
            elif isinstance(attr, ASTNode):
                if _body_contains([attr], node_type_name):
                    return True
    return False


def _body_references_global(body):
    """Heuristic: check if body might reference/mutate global state."""
    source_hints = str(body)
    for keyword in ['global', 'file_write', 'file_append', 'print']:
        if keyword in source_hints:
            return True
    return False


def _count_params(func_node):
    """Return the number of parameters."""
    return len(func_node.params) if func_node.params else 0


# ── Property Inference Engine ─────────────────────────────────────────

# Name patterns that suggest properties
NAME_PATTERNS = {
    r'^(is_|has_|can_|should_|check_|valid)': ('boolean_return', 'Function name suggests boolean return value'),
    r'^(get_|fetch_|find_|lookup_|retrieve)': ('getter', 'Function name suggests it retrieves/returns a value'),
    r'^(set_|update_|modify_|change_)': ('setter', 'Function name suggests it modifies state'),
    r'^(calc_|compute_|count_|sum_|avg_|total_|measure)': ('numeric_return', 'Function name suggests numeric return value'),
    r'^(sort|order|rank|arrange)': ('ordering', 'Function name suggests ordering operation'),
    r'^(filter|select|where|reject)': ('filter', 'Function name suggests filtering operation'),
    r'^(map|transform|convert|to_)': ('transform', 'Function name suggests transformation'),
    r'^(max|min|largest|smallest|best|worst)': ('extremum', 'Function name suggests finding extreme values'),
    r'^(reverse|flip|invert|negate|toggle)': ('involution_candidate', 'Function may be its own inverse'),
    r'^(add|append|push|insert|enqueue)': ('accumulator', 'Function name suggests adding to a collection'),
    r'^(remove|delete|pop|dequeue|drop)': ('remover', 'Function name suggests removing from a collection'),
    r'^(merge|combine|join|concat|zip)': ('combiner', 'Function name suggests combining inputs'),
    r'^(split|divide|partition|chunk)': ('splitter', 'Function name suggests splitting input'),
    r'^(format|render|display|stringify|to_str)': ('formatter', 'Function name suggests formatting/string output'),
}


def infer_properties(func_name, func_node):
    """Infer testable properties for a function based on patterns."""
    props = []
    n_params = _count_params(func_node)

    # Name-based inference
    for pattern, (kind, desc) in NAME_PATTERNS.items():
        if re.search(pattern, func_name, re.IGNORECASE):
            props.append(Property(kind, desc, 0.7))

    # Structural inference
    body_str = repr(func_node.body)

    # If function has no side-effect indicators, likely pure
    if not _body_references_global(func_node.body):
        props.append(Property('likely_pure', 'No obvious side effects detected — likely a pure function', 0.6))

    # Functions with 1+ params that return values are testable with random inputs
    if n_params >= 1:
        props.append(Property('callable', f'Function accepts {n_params} parameter(s) — can be tested with generated inputs', 0.9))

    # Idempotency candidate: single param, returns same type
    if n_params == 1 and any(p.kind in ('formatter', 'ordering', 'filter') for p in props):
        props.append(Property('idempotent_candidate', 'Applying function twice may equal applying once (f(f(x)) == f(x))', 0.5))

    # Involution candidate: reverse/flip applied twice = identity
    if any(p.kind == 'involution_candidate' for p in props) and n_params == 1:
        props.append(Property('involution', 'Applying function twice may return original input (f(f(x)) == x)', 0.5))

    # Numeric functions: check consistency
    if any(p.kind == 'numeric_return' for p in props):
        props.append(Property('deterministic', 'Same inputs should always produce same numeric output', 0.8))

    # Boolean functions: should return true or false
    if any(p.kind == 'boolean_return' for p in props):
        props.append(Property('boolean_output', 'Function should return true or false for all inputs', 0.8))

    # Zero-param functions: can test for no-crash
    if n_params == 0:
        props.append(Property('no_crash', 'Function with no parameters should not crash on invocation', 0.9))

    return props


# ── Test Generation & Execution ───────────────────────────────────────

def _generate_test_values():
    """Generate diverse test input values for property testing."""
    return [
        # Integers
        0, 1, -1, 2, 42, -100, 999,
        # Floats
        0.0, 1.5, -3.14, 0.001,
        # Strings
        "", "hello", "a", "Hello World", "123", "  spaces  ",
        # Lists
        [], [1], [1, 2, 3], [3, 1, 2], [-5, 0, 5], ["a", "b", "c"],
        # Booleans
        True, False,
        # None
        None,
    ]


def _safe_call(interpreter, func_name, args):
    """Call a function in the interpreter, capturing output and exceptions."""
    old_stdout = sys.stdout
    sys.stdout = StringIO()
    try:
        # Build a call expression string
        arg_strs = []
        for a in args:
            if a is None:
                arg_strs.append("none")
            elif isinstance(a, bool):
                arg_strs.append("true" if a else "false")
            elif isinstance(a, str):
                arg_strs.append(json.dumps(a))
            elif isinstance(a, list):
                inner = ", ".join(
                    json.dumps(x) if isinstance(x, str) else
                    ("true" if x is True else "false" if x is False else
                     "none" if x is None else str(x))
                    for x in a
                )
                arg_strs.append(f"[{inner}]")
            else:
                arg_strs.append(str(a))

        call_code = f"{func_name}({', '.join(arg_strs)})"
        tokens = tokenize(call_code)
        parser = Parser(tokens)
        call_ast = parser.parse()
        result = None
        for node in call_ast:
            result = interpreter.evaluate(node)
        output = sys.stdout.getvalue()
        return True, result, output
    except Exception as e:
        return False, str(e), sys.stdout.getvalue()
    finally:
        sys.stdout = old_stdout


def run_property_tests(interpreter, func_name, func_node, properties, max_trials=20):
    """Run property-based tests and return violations."""
    violations = []
    test_values = _generate_test_values()
    n_params = _count_params(func_node)

    for prop in properties:
        if prop.kind == 'no_crash' and n_params == 0:
            ok, result, _ = _safe_call(interpreter, func_name, [])
            if not ok:
                violations.append(Violation(
                    func_name, 'no_crash',
                    f"Function crashed with no arguments: {result}",
                ))

        elif prop.kind == 'boolean_output' and n_params >= 1:
            trials = 0
            for val in test_values:
                if trials >= max_trials:
                    break
                ok, result, _ = _safe_call(interpreter, func_name, [val])
                if ok and result not in (True, False, None):
                    # Only flag if it returned something clearly non-boolean
                    if result is not None:
                        violations.append(Violation(
                            func_name, 'boolean_output',
                            f"Expected boolean return, got {type(result).__name__}",
                            inputs=[val], expected="true/false", actual=result,
                        ))
                        break
                trials += 1

        elif prop.kind == 'deterministic' and n_params >= 1:
            for val in test_values[:10]:
                ok1, r1, _ = _safe_call(interpreter, func_name, [val])
                ok2, r2, _ = _safe_call(interpreter, func_name, [val])
                if ok1 and ok2 and r1 != r2:
                    violations.append(Violation(
                        func_name, 'deterministic',
                        f"Same input produced different outputs",
                        inputs=[val], expected=r1, actual=r2,
                    ))
                    break

        elif prop.kind == 'idempotent_candidate' and n_params == 1:
            for val in test_values[:10]:
                ok1, r1, _ = _safe_call(interpreter, func_name, [val])
                if ok1 and r1 is not None:
                    ok2, r2, _ = _safe_call(interpreter, func_name, [r1])
                    if ok2 and r2 is not None and r1 != r2:
                        violations.append(Violation(
                            func_name, 'idempotent_candidate',
                            f"f(f(x)) != f(x) — not idempotent",
                            inputs=[val], expected=r1, actual=r2,
                        ))
                        break

        elif prop.kind == 'involution' and n_params == 1:
            for val in test_values[:10]:
                ok1, r1, _ = _safe_call(interpreter, func_name, [val])
                if ok1 and r1 is not None:
                    ok2, r2, _ = _safe_call(interpreter, func_name, [r1])
                    if ok2 and r2 != val:
                        violations.append(Violation(
                            func_name, 'involution',
                            f"f(f(x)) != x — not an involution",
                            inputs=[val], expected=val, actual=r2,
                        ))
                        break

        elif prop.kind == 'callable' and n_params >= 1:
            # Smoke test: just try a few calls, report crashes
            crash_count = 0
            tried = 0
            for val in test_values[:15]:
                args = [val] * n_params  # Simple: repeat same value for all params
                ok, result, _ = _safe_call(interpreter, func_name, args)
                tried += 1
                if not ok:
                    crash_count += 1
            if crash_count > 0 and crash_count == tried:
                violations.append(Violation(
                    func_name, 'callable',
                    f"Function crashed on ALL {tried} test inputs",
                ))

    return violations


# ── Oracle Report ─────────────────────────────────────────────────────

def _severity_label(violations):
    if not violations:
        return "✅ PASS"
    severe = sum(1 for v in violations if v.property_kind in ('no_crash', 'callable'))
    if severe > 0:
        return "🔴 CRITICAL"
    return "🟡 WARNING"


def _confidence_bar(conf, width=10):
    filled = int(conf * width)
    return "█" * filled + "░" * (width - filled)


def print_report(func_results, show_infer=False, show_test=True):
    """Print a human-readable oracle report."""
    total_funcs = len(func_results)
    total_props = sum(len(fr['properties']) for fr in func_results.values())
    total_violations = sum(len(fr['violations']) for fr in func_results.values())

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║             🔮 SAURAVORACLE — Test Oracle Report            ║")
    print("╠══════════════════════════════════════════════════════════════╣")
    print(f"║  Functions analyzed:  {total_funcs:<38}║")
    print(f"║  Properties inferred: {total_props:<38}║")
    print(f"║  Violations found:    {total_violations:<38}║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()

    for func_name, data in sorted(func_results.items()):
        props = data['properties']
        viols = data['violations']
        severity = _severity_label(viols)
        n_params = data['n_params']

        print(f"  ┌─ {func_name}({', '.join(data.get('param_names', []))}) {severity}")

        if show_infer and props:
            print(f"  │  Inferred Properties:")
            for p in props:
                bar = _confidence_bar(p.confidence)
                print(f"  │    {bar} [{p.confidence:.0%}] {p.kind}: {p.description}")

        if show_test and viols:
            print(f"  │  ⚠ Violations:")
            for v in viols:
                print(f"  │    🔸 [{v.property_kind}] {v.description}")
                if v.inputs is not None:
                    print(f"  │      Input:    {v.inputs}")
                if v.expected is not None:
                    print(f"  │      Expected: {v.expected}")
                if v.actual is not None:
                    print(f"  │      Actual:   {v.actual}")

        if not viols and not (show_infer and props):
            print(f"  │  No violations detected ({len(props)} properties checked)")

        print(f"  └{'─' * 60}")
        print()

    # Proactive recommendations
    if total_violations > 0:
        print("  💡 Proactive Recommendations:")
        crash_funcs = [fn for fn, d in func_results.items()
                       if any(v.property_kind in ('no_crash', 'callable') for v in d['violations'])]
        if crash_funcs:
            print(f"     • {len(crash_funcs)} function(s) crash on common inputs — add input validation:")
            for fn in crash_funcs[:5]:
                print(f"       → {fn}")
        det_funcs = [fn for fn, d in func_results.items()
                     if any(v.property_kind == 'deterministic' for v in d['violations'])]
        if det_funcs:
            print(f"     • {len(det_funcs)} function(s) are non-deterministic — verify this is intentional")
        bool_funcs = [fn for fn, d in func_results.items()
                      if any(v.property_kind == 'boolean_output' for v in d['violations'])]
        if bool_funcs:
            print(f"     • {len(bool_funcs)} predicate function(s) return non-boolean values — fix return types")
        print()


def generate_html_report(func_results, output_path):
    """Generate an interactive HTML report."""
    total_funcs = len(func_results)
    total_props = sum(len(fr['properties']) for fr in func_results.values())
    total_violations = sum(len(fr['violations']) for fr in func_results.values())
    pass_count = sum(1 for fr in func_results.values() if not fr['violations'])
    fail_count = total_funcs - pass_count

    rows_html = []
    for func_name, data in sorted(func_results.items()):
        props = data['properties']
        viols = data['violations']
        status = "pass" if not viols else "fail"
        status_icon = "✅" if not viols else "🔴"

        props_html = "".join(
            f'<div class="prop"><span class="conf">{p.confidence:.0%}</span> '
            f'<strong>{p.kind}</strong>: {p.description}</div>'
            for p in props
        )

        viols_html = ""
        if viols:
            viols_html = "".join(
                f'<div class="viol"><strong>[{v.property_kind}]</strong> {v.description}'
                + (f'<br><small>Input: {v.inputs}</small>' if v.inputs else '')
                + (f'<br><small>Expected: {v.expected} | Actual: {v.actual}</small>' if v.expected else '')
                + '</div>'
                for v in viols
            )

        rows_html.append(f'''
        <div class="func-card {status}" onclick="this.classList.toggle('expanded')">
            <div class="func-header">
                <span class="status-icon">{status_icon}</span>
                <span class="func-name">{func_name}</span>
                <span class="param-count">{data['n_params']} params</span>
                <span class="prop-count">{len(props)} props</span>
                <span class="viol-count">{len(viols)} violations</span>
            </div>
            <div class="func-details">
                <h4>Inferred Properties</h4>
                {props_html or '<div class="none">None inferred</div>'}
                <h4>Violations</h4>
                {viols_html or '<div class="none">None detected ✅</div>'}
            </div>
        </div>''')

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🔮 SauravOracle Report</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #0d1117; color: #c9d1d9; padding: 24px; }}
.header {{ text-align: center; padding: 32px 0; }}
.header h1 {{ font-size: 2rem; color: #f0f6fc; }}
.header p {{ color: #8b949e; margin-top: 8px; }}
.stats {{ display: flex; gap: 16px; justify-content: center; margin: 24px 0; flex-wrap: wrap; }}
.stat {{ background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 16px 24px; text-align: center; min-width: 140px; }}
.stat .num {{ font-size: 2rem; font-weight: bold; }}
.stat .label {{ color: #8b949e; font-size: 0.85rem; margin-top: 4px; }}
.stat.pass .num {{ color: #3fb950; }}
.stat.fail .num {{ color: #f85149; }}
.stat.props .num {{ color: #d2a8ff; }}
.filter-bar {{ text-align: center; margin: 16px 0; }}
.filter-bar button {{ background: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 8px 16px; border-radius: 8px; cursor: pointer; margin: 4px; }}
.filter-bar button.active {{ background: #388bfd; border-color: #388bfd; color: #fff; }}
.func-card {{ background: #161b22; border: 1px solid #30363d; border-radius: 12px; margin: 8px 0; overflow: hidden; cursor: pointer; transition: all 0.2s; }}
.func-card:hover {{ border-color: #58a6ff; }}
.func-card.fail {{ border-left: 4px solid #f85149; }}
.func-card.pass {{ border-left: 4px solid #3fb950; }}
.func-header {{ display: flex; align-items: center; gap: 12px; padding: 14px 18px; flex-wrap: wrap; }}
.func-name {{ font-weight: 600; font-size: 1.05rem; color: #f0f6fc; }}
.param-count, .prop-count, .viol-count {{ font-size: 0.8rem; color: #8b949e; background: #21262d; padding: 2px 8px; border-radius: 10px; }}
.func-details {{ display: none; padding: 0 18px 14px; }}
.func-card.expanded .func-details {{ display: block; }}
.func-details h4 {{ color: #8b949e; margin: 12px 0 6px; font-size: 0.85rem; text-transform: uppercase; }}
.prop {{ padding: 4px 0; font-size: 0.9rem; }}
.conf {{ display: inline-block; width: 36px; color: #d2a8ff; font-weight: 600; }}
.viol {{ padding: 6px 10px; margin: 4px 0; background: #2d1b1b; border-radius: 6px; font-size: 0.9rem; }}
.none {{ color: #484f58; font-style: italic; font-size: 0.85rem; }}
</style>
</head>
<body>
<div class="header">
    <h1>🔮 SauravOracle — Test Oracle Report</h1>
    <p>Autonomous property inference & specification violation detection</p>
</div>
<div class="stats">
    <div class="stat"><div class="num">{total_funcs}</div><div class="label">Functions</div></div>
    <div class="stat props"><div class="num">{total_props}</div><div class="label">Properties</div></div>
    <div class="stat pass"><div class="num">{pass_count}</div><div class="label">Passing</div></div>
    <div class="stat fail"><div class="num">{fail_count}</div><div class="label">Violations</div></div>
</div>
<div class="filter-bar">
    <button class="active" onclick="filterCards('all', this)">All</button>
    <button onclick="filterCards('fail', this)">Violations Only</button>
    <button onclick="filterCards('pass', this)">Passing Only</button>
</div>
<div id="cards">
{"".join(rows_html)}
</div>
<script>
function filterCards(mode, btn) {{
    document.querySelectorAll('.filter-bar button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.func-card').forEach(c => {{
        if (mode === 'all') c.style.display = '';
        else if (mode === 'fail') c.style.display = c.classList.contains('fail') ? '' : 'none';
        else c.style.display = c.classList.contains('pass') ? '' : 'none';
    }});
}}
</script>
</body>
</html>'''

    with open(output_path + ".html", 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"  📄 HTML report: {output_path}.html")


# ── Main Oracle Pipeline ─────────────────────────────────────────────

def run_oracle(source_path, show_infer=False, run_tests=True, html_path=None, json_output=False, watch=False):
    """Main oracle pipeline: parse → infer → test → report."""

    while True:
        with open(source_path, 'r', encoding='utf-8') as f:
            source = f.read()

        # Parse
        try:
            tokens = tokenize(source)
            parser = Parser(tokens)
            ast_nodes = parser.parse()
        except Exception as e:
            print(f"  ❌ Parse error: {e}")
            if not watch:
                return {}
            time.sleep(2)
            continue

        # Collect functions
        funcs = _collect_functions(ast_nodes)
        if not funcs:
            print("  ℹ No functions found in source file.")
            if not watch:
                return {}
            time.sleep(2)
            continue

        # Set up interpreter (run the full file to define functions)
        interpreter = Interpreter()
        old_stdout = sys.stdout
        sys.stdout = StringIO()
        try:
            for node in ast_nodes:
                interpreter.evaluate(node)
        except Exception:
            pass  # Some top-level code might fail; that's okay
        finally:
            sys.stdout = old_stdout

        # Infer properties and run tests
        func_results = {}
        for func_name, func_node in sorted(funcs.items()):
            props = infer_properties(func_name, func_node)
            viols = []
            if run_tests:
                viols = run_property_tests(interpreter, func_name, func_node, props)

            func_results[func_name] = {
                'properties': props,
                'violations': viols,
                'n_params': _count_params(func_node),
                'param_names': func_node.params if func_node.params else [],
            }

        # Output
        if json_output:
            out = {
                "file": source_path,
                "functions": {
                    fn: {
                        "params": d['param_names'],
                        "properties": [p.to_dict() for p in d['properties']],
                        "violations": [v.to_dict() for v in d['violations']],
                    }
                    for fn, d in func_results.items()
                }
            }
            print(json.dumps(out, indent=2))
        else:
            print_report(func_results, show_infer=show_infer, show_test=run_tests)

        if html_path:
            generate_html_report(func_results, html_path)

        if not watch:
            return func_results

        # Watch mode: poll for changes
        mtime = os.path.getmtime(source_path)
        print(f"\n  👁 Watching {source_path} for changes... (Ctrl+C to stop)")
        while os.path.getmtime(source_path) == mtime:
            time.sleep(1)
        print(f"\n  🔄 File changed — re-analyzing...\n")


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="sauravoracle",
        description="🔮 Autonomous Test Oracle for sauravcode programs",
    )
    parser.add_argument("file", help="Path to .srv source file")
    parser.add_argument("--infer", action="store_true", help="Show inferred properties")
    parser.add_argument("--test", action="store_true", help="Run property-based tests (default: on)")
    parser.add_argument("--watch", action="store_true", help="Continuous file monitoring")
    parser.add_argument("--html", metavar="PATH", help="Generate HTML report")
    parser.add_argument("--json", action="store_true", help="JSON output")

    args = parser.parse_args()

    if not os.path.isfile(args.file):
        print(f"Error: file not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    run_oracle(
        args.file,
        show_infer=args.infer,
        run_tests=True,
        html_path=args.html,
        json_output=args.json,
        watch=args.watch,
    )


if __name__ == "__main__":
    main()
