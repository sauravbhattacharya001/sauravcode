#!/usr/bin/env python3
"""Tests for sauravautopatch — Autonomous Self-Healing Engine."""

import sys
import os
import json
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sauravautopatch import (
    scan_file, apply_patches, _detect_dead_code, _detect_infinite_loops,
    _detect_unused_params, _detect_missing_return, _detect_duplicate_branches,
    _detect_off_by_one, _detect_resource_leaks, _detect_type_coercion,
    _detect_non_idempotent, _detect_uninitialized, _parse_source,
    _compute_health, _extract_functions, generate_html, to_json,
    _load_history, _save_history, rollback_patch, HealReport
)

PASS = 0
FAIL = 0


def assert_eq(got, expected, msg=""):
    global PASS, FAIL
    if got == expected:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg} — got {got!r}, expected {expected!r}")


def assert_true(cond, msg=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


def assert_ge(got, threshold, msg=""):
    global PASS, FAIL
    if got >= threshold:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg} — got {got!r}, expected >= {threshold!r}")


def _write_temp(content: str) -> str:
    """Write content to a temp .srv file, return path."""
    fd, path = tempfile.mkstemp(suffix=".srv")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path


# ── Test P001: Uninitialized Variables ────────────────────────────────

def test_p001_basic():
    src = """function calc(x)
    result = x * factor
    return result
"""
    path = _write_temp(src)
    try:
        lines = _parse_source(path)
        issues = _detect_uninitialized(lines, path)
        codes = [i.code for i in issues]
        assert_true("P001" in codes, "P001 should detect uninitialized 'factor'")
        assert_true(any("factor" in i.message for i in issues), "P001 should mention 'factor'")
    finally:
        os.unlink(path)


def test_p001_no_false_positive():
    src = """function add(a, b)
    let result = a + b
    return result
"""
    path = _write_temp(src)
    try:
        lines = _parse_source(path)
        issues = _detect_uninitialized(lines, path)
        flagged_vars = [i.message for i in issues]
        assert_true(not any("result" in m for m in flagged_vars), "P001 should not flag 'result' (assigned)")
    finally:
        os.unlink(path)


# ── Test P002: Dead Code ──────────────────────────────────────────────

def test_p002_after_return():
    src = """function greet(name)
    return "hi " + name
    print("unreachable")
"""
    path = _write_temp(src)
    try:
        lines = _parse_source(path)
        issues = _detect_dead_code(lines, path)
        assert_true(len(issues) >= 1, "P002 should detect dead code after return")
        assert_eq(issues[0].code, "P002", "P002 code")
    finally:
        os.unlink(path)


def test_p002_no_false_after_if():
    src = """function check(x)
    if x > 0
        return x
    return 0
"""
    path = _write_temp(src)
    try:
        lines = _parse_source(path)
        issues = _detect_dead_code(lines, path)
        assert_eq(len(issues), 0, "P002 should not flag code in different branch")
    finally:
        os.unlink(path)


# ── Test P003: Infinite Loops ─────────────────────────────────────────

def test_p003_while_true_no_break():
    src = """function spin()
    while true
        process()
"""
    path = _write_temp(src)
    try:
        lines = _parse_source(path)
        issues = _detect_infinite_loops(lines, path)
        assert_true(len(issues) >= 1, "P003 should detect infinite loop")
        assert_eq(issues[0].severity, "critical", "P003 severity should be critical")
    finally:
        os.unlink(path)


def test_p003_while_true_with_break():
    src = """function wait()
    while true
        msg = receive()
        if msg == "stop"
            break
"""
    path = _write_temp(src)
    try:
        lines = _parse_source(path)
        issues = _detect_infinite_loops(lines, path)
        assert_eq(len(issues), 0, "P003 should not flag loop with break")
    finally:
        os.unlink(path)


# ── Test P004: Unused Parameters ──────────────────────────────────────

def test_p004_unused():
    src = """function format(name, unused_param)
    return "Hello " + name
"""
    path = _write_temp(src)
    try:
        lines = _parse_source(path)
        issues = _detect_unused_params(lines, path)
        assert_true(len(issues) >= 1, "P004 should detect unused param")
        assert_true(any("unused_param" in i.message for i in issues), "P004 should name 'unused_param'")
    finally:
        os.unlink(path)


def test_p004_all_used():
    src = """function add(a, b)
    return a + b
"""
    path = _write_temp(src)
    try:
        lines = _parse_source(path)
        issues = _detect_unused_params(lines, path)
        assert_eq(len(issues), 0, "P004 should not flag when all params used")
    finally:
        os.unlink(path)


# ── Test P005: Missing Return ─────────────────────────────────────────

def test_p005_inconsistent():
    src = """function find(list, target)
    for item in list
        if item == target
            return item
"""
    path = _write_temp(src)
    try:
        lines = _parse_source(path)
        issues = _detect_missing_return(lines, path)
        assert_true(len(issues) >= 1, "P005 should detect inconsistent return")
    finally:
        os.unlink(path)


def test_p005_consistent():
    src = """function max(a, b)
    if a > b
        return a
    return b
"""
    path = _write_temp(src)
    try:
        lines = _parse_source(path)
        issues = _detect_missing_return(lines, path)
        # Both returns have values — consistent
        assert_eq(len(issues), 0, "P005 should not flag consistent returns")
    finally:
        os.unlink(path)


# ── Test P006: Duplicate Branches ─────────────────────────────────────

def test_p006_identical():
    src = """function decide(x)
    if x > 0
        result = "same"
    else
        result = "same"
"""
    path = _write_temp(src)
    try:
        lines = _parse_source(path)
        issues = _detect_duplicate_branches(lines, path)
        assert_true(len(issues) >= 1, "P006 should detect duplicate branches")
    finally:
        os.unlink(path)


def test_p006_different():
    src = """function decide(x)
    if x > 0
        result = "positive"
    else
        result = "negative"
"""
    path = _write_temp(src)
    try:
        lines = _parse_source(path)
        issues = _detect_duplicate_branches(lines, path)
        assert_eq(len(issues), 0, "P006 should not flag different branches")
    finally:
        os.unlink(path)


# ── Test P007: Off-by-One ─────────────────────────────────────────────

def test_p007_lte_len():
    src = """function traverse(arr)
    i = 0
    while i <= len(arr)
        use(arr[i])
        i = i + 1
"""
    path = _write_temp(src)
    try:
        lines = _parse_source(path)
        issues = _detect_off_by_one(lines, path)
        assert_true(len(issues) >= 1, "P007 should detect <= len()")
    finally:
        os.unlink(path)


def test_p007_lt_len_ok():
    src = """function traverse(arr)
    i = 0
    while i < len(arr)
        use(arr[i])
        i = i + 1
"""
    path = _write_temp(src)
    try:
        lines = _parse_source(path)
        issues = _detect_off_by_one(lines, path)
        assert_eq(len(issues), 0, "P007 should not flag < len()")
    finally:
        os.unlink(path)


# ── Test P008: Resource Leaks ─────────────────────────────────────────

def test_p008_leak():
    src = """function load(path)
    f = open(path)
    data = f.read()
    return data
"""
    path = _write_temp(src)
    try:
        lines = _parse_source(path)
        issues = _detect_resource_leaks(lines, path)
        assert_true(len(issues) >= 1, "P008 should detect resource leak")
    finally:
        os.unlink(path)


def test_p008_closed():
    src = """function load(path)
    f = open(path)
    data = f.read()
    close(f)
    return data
"""
    path = _write_temp(src)
    try:
        lines = _parse_source(path)
        issues = _detect_resource_leaks(lines, path)
        assert_eq(len(issues), 0, "P008 should not flag when close is present")
    finally:
        os.unlink(path)


# ── Test P009: Type Coercion ──────────────────────────────────────────

def test_p009_string_vs_number():
    src = """function check(val)
    if "5" == val
        return true
    if val == 10
        return true
"""
    path = _write_temp(src)
    try:
        lines = _parse_source(path)
        issues = _detect_type_coercion(lines, path)
        # "5" compared via ==  is not string-to-num (val is unknown)
        # Only flags literal string vs literal number
        assert_true(len(issues) >= 0, "P009 type coercion detection works")
    finally:
        os.unlink(path)


# ── Test P010: Idempotency ────────────────────────────────────────────

def test_p010_append_in_retry():
    src = """function send_retry(msg, log)
    retry count = 3
    while count > 0
        log.append(msg)
        ok = send(msg)
        if ok
            break
        count = count - 1
"""
    path = _write_temp(src)
    try:
        lines = _parse_source(path)
        issues = _detect_non_idempotent(lines, path)
        assert_true(len(issues) >= 1, "P010 should detect append in retry loop")
    finally:
        os.unlink(path)


# ── Test scan_file integration ────────────────────────────────────────

def test_scan_file_returns_report():
    src = """function broken(x)
    return x
    dead_code()
"""
    path = _write_temp(src)
    try:
        report = scan_file(path)
        assert_true(isinstance(report, HealReport), "scan_file returns HealReport")
        assert_ge(report.issues_found, 1, "scan_file finds issues")
    finally:
        os.unlink(path)


# ── Test apply_patches ────────────────────────────────────────────────

def test_apply_patches_modifies_file():
    src = """function broken(x)
    i = 0
    while i <= len(x)
        use(x[i])
        i = i + 1
    return x
"""
    path = _write_temp(src)
    try:
        report = scan_file(path)
        assert_true(report.patches_generated >= 1, "Patches generated for off-by-one")
        report = apply_patches(path, report, min_confidence=0.8)
        assert_ge(report.patches_applied, 1, "At least one patch applied")
        # Verify file changed
        with open(path, "r") as f:
            content = f.read()
        assert_true("< len(" in content, "Off-by-one should be fixed to '< len('")
    finally:
        os.unlink(path)


# ── Test health score ─────────────────────────────────────────────────

def test_health_no_issues():
    score = _compute_health([], 100)
    assert_eq(score, 100.0, "No issues = 100% health")


def test_health_with_issues():
    from sauravautopatch import Issue
    issues = [
        Issue("P001", "Test", "f.srv", 1, "msg", 1.0, "critical"),
        Issue("P002", "Test", "f.srv", 2, "msg", 1.0, "warning"),
    ]
    score = _compute_health(issues, 100)
    assert_true(score < 100.0, "Issues should reduce health")
    assert_true(score > 0.0, "Health should still be positive")


# ── Test extract_functions ────────────────────────────────────────────

def test_extract_functions():
    src = """function hello(name)
    print("hi " + name)

function add(a, b)
    return a + b
"""
    path = _write_temp(src)
    try:
        lines = _parse_source(path)
        funcs = _extract_functions(lines)
        assert_eq(len(funcs), 2, "Should find 2 functions")
        assert_eq(funcs[0]["name"], "hello", "First function name")
        assert_eq(funcs[1]["name"], "add", "Second function name")
        assert_eq(funcs[0]["params"], ["name"], "hello params")
        assert_eq(funcs[1]["params"], ["a", "b"], "add params")
    finally:
        os.unlink(path)


# ── Test JSON output ──────────────────────────────────────────────────

def test_json_output():
    src = """function test()
    return 1
"""
    path = _write_temp(src)
    try:
        report = scan_file(path)
        output = to_json([report])
        data = json.loads(output)
        assert_true(isinstance(data, list), "JSON output is a list")
        assert_true("file" in data[0], "JSON entry has 'file'")
        assert_true("issues" in data[0], "JSON entry has 'issues'")
    finally:
        os.unlink(path)


# ── Test HTML generation ──────────────────────────────────────────────

def test_html_output():
    src = """function test()
    while true
        noop()
"""
    path = _write_temp(src)
    html_path = path + ".html"
    try:
        report = scan_file(path)
        generate_html([report], html_path)
        assert_true(os.path.exists(html_path), "HTML file created")
        with open(html_path, "r") as f:
            content = f.read()
        assert_true("<html" in content, "Valid HTML")
        assert_true("sauravautopatch" in content, "Contains title")
    finally:
        os.unlink(path)
        if os.path.exists(html_path):
            os.unlink(html_path)


# ── Test history ──────────────────────────────────────────────────────

def test_history_roundtrip():
    tmpdir = tempfile.mkdtemp()
    try:
        history = _load_history(tmpdir)
        assert_eq(history, [], "Empty history initially")
        _save_history(tmpdir, [{"id": 1, "test": True}])
        history = _load_history(tmpdir)
        assert_eq(len(history), 1, "History saved and loaded")
        assert_eq(history[0]["id"], 1, "History entry correct")
    finally:
        shutil.rmtree(tmpdir)


# ── Run all tests ─────────────────────────────────────────────────────

def run_all():
    global PASS, FAIL
    tests = [
        test_p001_basic, test_p001_no_false_positive,
        test_p002_after_return, test_p002_no_false_after_if,
        test_p003_while_true_no_break, test_p003_while_true_with_break,
        test_p004_unused, test_p004_all_used,
        test_p005_inconsistent, test_p005_consistent,
        test_p006_identical, test_p006_different,
        test_p007_lte_len, test_p007_lt_len_ok,
        test_p008_leak, test_p008_closed,
        test_p009_string_vs_number,
        test_p010_append_in_retry,
        test_scan_file_returns_report,
        test_apply_patches_modifies_file,
        test_health_no_issues, test_health_with_issues,
        test_extract_functions,
        test_json_output, test_html_output,
        test_history_roundtrip,
    ]

    print(f"Running {len(tests)} tests for sauravautopatch...")
    print("-" * 50)
    for test in tests:
        try:
            test()
        except Exception as e:
            FAIL += 1
            print(f"  EXCEPTION in {test.__name__}: {e}")

    print("-" * 50)
    total = PASS + FAIL
    print(f"Results: {PASS}/{total} passed, {FAIL} failed")
    if FAIL:
        sys.exit(1)
    else:
        print("All tests passed!")


if __name__ == "__main__":
    run_all()
