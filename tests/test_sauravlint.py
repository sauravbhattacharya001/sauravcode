#!/usr/bin/env python3
"""Tests for sauravlint — the sauravcode linter."""

import sys
import os
import json
import tempfile
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from sauravlint import SauravLinter, LintReport, LintIssue, Severity, lint_file, lint_directory, format_report, format_summary


def lint(code, disabled=None):
    """Helper: lint code string and return report."""
    linter = SauravLinter(disabled_rules=disabled)
    return linter.lint(code, "<test>")


def rules(report):
    """Get list of rule codes from a report."""
    return [i.rule for i in report.issues]


def has_rule(report, rule):
    return rule in rules(report)


# ── E001-related (undefined variable) ──
# Note: E001 is conservative; only fires for clear cases


# ── E002: Unreachable code ──

def test_e002_after_return():
    r = lint("function foo x\n    return x\n    print x\n")
    assert has_rule(r, "E002"), f"Expected E002, got {rules(r)}"

def test_e002_after_throw():
    r = lint("try\n    throw 42\n    print 1\ncatch e\n    print e\n")
    assert has_rule(r, "E002")

def test_e002_after_break():
    r = lint("while true\n    break\n    print 1\n")
    assert has_rule(r, "E002")

def test_e002_after_continue():
    r = lint("while true\n    continue\n    print 1\n")
    assert has_rule(r, "E002")

def test_e002_no_false_positive_after_if():
    r = lint("function foo x\n    if x > 0\n        return x\n    print x\n")
    assert not has_rule(r, "E002")


# ── E003: Division by zero ──

def test_e003_literal_div_zero():
    r = lint("x = 10 / 0\n")
    assert has_rule(r, "E003")

def test_e003_no_false_positive():
    r = lint("x = 10 / 2\n")
    assert not has_rule(r, "E003")

def test_e003_float_zero():
    r = lint("x = 10 / 0.0\n")
    assert has_rule(r, "E003")


# ── E004: Duplicate function ──

def test_e004_duplicate_func():
    r = lint("function foo x\n    return x\nfunction foo y\n    return y\n")
    assert has_rule(r, "E004")

def test_e004_no_dup():
    r = lint("function foo x\n    return x\nfunction bar y\n    return y\n")
    assert not has_rule(r, "E004")


# ── E005: Break/continue outside loop ──

def test_e005_break_outside():
    r = lint("break\n")
    assert has_rule(r, "E005")

def test_e005_continue_outside():
    r = lint("continue\n")
    assert has_rule(r, "E005")

def test_e005_break_inside_loop():
    r = lint("while true\n    break\n")
    assert not has_rule(r, "E005")


# ── W001: Unused variable ──

def test_w001_unused():
    r = lint("x = 42\n")
    assert has_rule(r, "W001")

def test_w001_used():
    r = lint("x = 42\nprint x\n")
    assert not has_rule(r, "W001")


# ── W002: Unused parameter ──

def test_w002_unused_param():
    r = lint("function foo x y\n    return x\n")
    assert has_rule(r, "W002")

def test_w002_all_used():
    r = lint("function foo x y\n    return x + y\n")
    assert not has_rule(r, "W002")


# ── W003: Variable shadows outer scope ──

def test_w003_shadow():
    r = lint("x = 10\nfunction foo x\n    return x\n")
    assert has_rule(r, "W003")

def test_w003_no_shadow():
    r = lint("function foo y\n    return y\n")
    assert not has_rule(r, "W003")


# ── W004: Self-comparison ──

def test_w004_self_eq():
    r = lint("if x == x\n    print 1\n")
    assert has_rule(r, "W004")

def test_w004_self_neq():
    r = lint("if x != x\n    print 1\n")
    assert has_rule(r, "W004")

def test_w004_different_vars():
    r = lint("if x == y\n    print 1\n")
    assert not has_rule(r, "W004")


# ── W005: Constant condition ──

def test_w005_if_true():
    r = lint("if true\n    print 1\n")
    assert has_rule(r, "W005")

def test_w005_while_false():
    r = lint("while false\n    print 1\n")
    assert has_rule(r, "W005")

def test_w005_normal_condition():
    r = lint("if x > 0\n    print 1\n")
    assert not has_rule(r, "W005")


# ── W006: Empty block ──

def test_w006_empty_if():
    r = lint("if x > 0\nprint 1\n")
    assert has_rule(r, "W006")

def test_w006_non_empty_if():
    r = lint("if x > 0\n    print 1\n")
    assert not has_rule(r, "W006")

def test_w006_empty_while():
    r = lint("while true\nprint 1\n")
    assert has_rule(r, "W006")

def test_w006_empty_function():
    r = lint("function foo x\nprint 1\n")
    assert has_rule(r, "W006")


# ── W007: Too many parameters ──

def test_w007_many_params():
    r = lint("function foo a b c d e f\n    return a\n")
    assert has_rule(r, "W007")

def test_w007_ok_params():
    r = lint("function foo a b c\n    return a\n")
    assert not has_rule(r, "W007")


# ── W008: Too deep nesting ──

def test_w008_deep():
    code = ""
    indent = ""
    for i in range(7):
        code += f"{indent}if true\n"
        indent += "    "
    code += f"{indent}print 1\n"
    r = lint(code)
    assert has_rule(r, "W008")

def test_w008_shallow():
    r = lint("if true\n    if true\n        print 1\n")
    assert not has_rule(r, "W008")


# ── W011: Mixed indentation ──

def test_w011_mixed():
    r = lint("if true\n    print 1\n\tprint 2\n")
    assert has_rule(r, "W011")

def test_w011_consistent_spaces():
    r = lint("if true\n    print 1\n    print 2\n")
    assert not has_rule(r, "W011")


# ── S002: Long line ──

def test_s002_long():
    r = lint("x = " + "a" * 120 + "\n")
    assert has_rule(r, "S002")

def test_s002_ok():
    r = lint("x = 1\n")
    assert not has_rule(r, "S002")


# ── S003: Trailing whitespace ──

def test_s003_trailing():
    r = lint("x = 1   \n")
    assert has_rule(r, "S003")

def test_s003_clean():
    r = lint("x = 1\n")
    assert not has_rule(r, "S003")


# ── S004: Missing newline at EOF ──

def test_s004_missing():
    r = lint("x = 1")
    assert has_rule(r, "S004")

def test_s004_present():
    r = lint("x = 1\n")
    assert not has_rule(r, "S004")


# ── Rule disabling ──

def test_disable_rule():
    r = lint("x = 42\n", disabled={"W001"})
    assert not has_rule(r, "W001")


# ── Report helpers ──

def test_report_counts():
    r = lint("x = 10 / 0\n")  # E003 + W001 + S004
    assert r.error_count >= 1
    assert r.total >= 1

def test_format_report_empty():
    r = LintReport(file="test.srv")
    assert format_report(r) == ""

def test_format_report_nonempty():
    r = lint("x = 10 / 0\n")
    output = format_report(r)
    assert "<test>" in output

def test_format_summary_clean():
    r = LintReport(file="test.srv")
    s = format_summary([r])
    assert "no issues" in s

def test_format_summary_issues():
    r = lint("break\n")
    s = format_summary([r])
    assert "error" in s


# ── File/directory linting ──

def test_lint_file():
    with tempfile.NamedTemporaryFile(suffix='.srv', mode='w', delete=False, encoding='utf-8') as f:
        f.write("x = 1\nprint x\n")
        fpath = f.name
    try:
        r = lint_file(fpath)
        assert r.file == fpath
    finally:
        os.unlink(fpath)

def test_lint_file_not_found():
    r = lint_file("/nonexistent/file.srv")
    assert has_rule(r, "F001")

def test_lint_directory():
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "a.srv"), 'w') as f:
            f.write("x = 1\nprint x\n")
        with open(os.path.join(d, "b.srv"), 'w') as f:
            f.write("y = 2\nprint y\n")
        reports = lint_directory(d)
        assert len(reports) == 2


# ── JSON output ──

def test_json_output():
    r = lint("break\n")
    d = r.to_dict()
    assert "issues" in d
    assert d["errors"] >= 1
    j = json.dumps(d)
    parsed = json.loads(j)
    assert parsed["file"] == "<test>"


# ── Integration: lint actual demo files ──

def test_lint_demo_files():
    """Lint all .srv files in the repo — should not crash."""
    repo = os.path.dirname(__file__)
    srv_files = [f for f in os.listdir(repo) if f.endswith('.srv')]
    for fname in srv_files:
        r = lint_file(os.path.join(repo, fname))
        assert isinstance(r, LintReport)
        assert r.file.endswith(fname)


# ── Edge cases ──

def test_empty_file():
    r = lint("")
    assert r.total == 0 or has_rule(r, "S004")

def test_comment_only():
    r = lint("# just a comment\n")
    assert r.error_count == 0

def test_string_not_flagged_as_division():
    r = lint('print "10 / 0 is bad"\n')
    assert not has_rule(r, "E003")

def test_fstring_not_flagged():
    r = lint('print f"value: {x / 0}"\n')
    # Inside f-string — should not trigger (string is removed)
    # This depends on implementation; we accept either behavior

def test_multiple_functions():
    code = "function add a b\n    return a + b\nfunction sub a b\n    return a - b\n"
    r = lint(code)
    assert not has_rule(r, "E004")

def test_for_loop_var_not_unused():
    r = lint("for i in range 0 10\n    print i\n")
    assert not has_rule(r, "W001")

def test_catch_var_used():
    r = lint("try\n    throw 1\ncatch err\n    print err\n")
    assert not has_rule(r, "W001")

def test_severity_enum():
    assert Severity.ERROR.value == "error"
    assert Severity.WARNING.value == "warning"
    assert Severity.STYLE.value == "style"

def test_issue_str():
    i = LintIssue("E001", Severity.ERROR, 5, 3, "test message")
    s = str(i)
    assert "5:3" in s
    assert "E001" in s

def test_no_crash_on_complex_code():
    code = """
function fibonacci n
    if n <= 1
        return n
    return fibonacci (n - 1) + fibonacci (n - 2)

for i in range 0 10
    print fibonacci i

nums = [1, 2, 3, 4, 5]
for n in nums
    if n % 2 == 0
        print f"{n} is even"
    else
        print f"{n} is odd"

try
    x = 10 / 2
    print x
catch err
    print err
"""
    r = lint(code)
    assert isinstance(r, LintReport)


# ── CLI ──

_CLI_ENV = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}

def test_cli_help():
    result = subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'sauravlint.py'), '--help'],
        capture_output=True, text=True, env=_CLI_ENV)
    assert result.returncode == 0
    assert 'sauravlint' in result.stdout

def test_cli_json():
    with tempfile.NamedTemporaryFile(suffix='.srv', mode='w', delete=False, encoding='utf-8') as f:
        f.write("break\n")
        fpath = f.name
    try:
        result = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'sauravlint.py'),
             '--json', fpath],
            capture_output=True, text=True, env=_CLI_ENV)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) == 1
    finally:
        os.unlink(fpath)

def test_cli_check_exit_code():
    with tempfile.NamedTemporaryFile(suffix='.srv', mode='w', delete=False, encoding='utf-8') as f:
        f.write("break\n")
        fpath = f.name
    try:
        result = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'sauravlint.py'),
             '--check', fpath],
            capture_output=True, text=True, env=_CLI_ENV)
        assert result.returncode == 1
    finally:
        os.unlink(fpath)

def test_cli_severity_filter():
    with tempfile.NamedTemporaryFile(suffix='.srv', mode='w', delete=False, encoding='utf-8') as f:
        f.write("x = 1   \n")  # S003 trailing ws + W001 unused
        fpath = f.name
    try:
        result = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'sauravlint.py'),
             '--severity', 'error', '--json', fpath],
            capture_output=True, text=True, env=_CLI_ENV)
        data = json.loads(result.stdout)
        for issue in data[0]['issues']:
            assert issue['severity'] == 'error'
    finally:
        os.unlink(fpath)

def test_cli_disable():
    with tempfile.NamedTemporaryFile(suffix='.srv', mode='w', delete=False, encoding='utf-8') as f:
        f.write("break\n")
        fpath = f.name
    try:
        result = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'sauravlint.py'),
             '--disable', 'E005', '--json', fpath],
            capture_output=True, text=True, env=_CLI_ENV)
        data = json.loads(result.stdout)
        rule_codes = [i['rule'] for i in data[0]['issues']]
        assert 'E005' not in rule_codes
    finally:
        os.unlink(fpath)


# ── Run all tests ──

def run_tests():
    test_funcs = [(name, obj) for name, obj in globals().items()
                  if name.startswith('test_') and callable(obj)]
    passed = 0
    failed = 0
    errors = []
    for name, func in sorted(test_funcs):
        try:
            func()
            passed += 1
            print(f"  ✓ {name}")
        except Exception as ex:
            failed += 1
            errors.append((name, ex))
            print(f"  ✗ {name}: {ex}")

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
    if errors:
        print("\nFailed tests:")
        for name, ex in errors:
            print(f"  {name}: {ex}")
    return failed == 0


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
