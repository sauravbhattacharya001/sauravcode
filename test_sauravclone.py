#!/usr/bin/env python3
"""Tests for sauravclone - Autonomous Code Clone Detector."""

import sys
import os
import json
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sauravclone import (
    node_fingerprint, node_size, extract_fragments, parse_file,
    detect_exact_clones, detect_renamed_clones, detect_gapped_clones,
    detect_clones, compute_dry_score, classify_severity, suggest_refactoring,
    generate_insights, format_text, format_json, generate_html,
    CloneGroup, CodeFragment, CloneReport, collect_files,
    _fingerprint_similarity, _refactoring_confidence,
)

PASS = 0
FAIL = 0


def check(name, condition):
    global PASS, FAIL
    if condition:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {name}")


def make_srv(content, filename="test.srv"):
    """Write a .srv file to a temp directory and return its path."""
    d = tempfile.mkdtemp()
    path = os.path.join(d, filename)
    with open(path, 'w') as f:
        f.write(content)
    return path, d


# ── Test: Basic parsing and fragment extraction ──────────────────────────────

def test_parse_and_extract():
    src = """
function add a b
    return a + b

function subtract a b
    return a - b

function multiply a b
    x = a * b
    return x
"""
    path, d = make_srv(src)
    try:
        ast = parse_file(path)
        check("parse_file returns list", isinstance(ast, list))
        check("parse_file has nodes", len(ast) > 0)
        
        frags = extract_fragments(ast, path, min_size=3)
        check("extract_fragments returns list", isinstance(frags, list))
        check("fragments found", len(frags) > 0)
        
        # Each fragment should have a fingerprint
        for frag in frags:
            check("fragment has fingerprint", len(frag.fingerprint) > 0)
            check("fragment has normalized_fingerprint", len(frag.normalized_fingerprint) > 0)
            check("fragment has file", frag.file == path)
    finally:
        shutil.rmtree(d)


# ── Test: Exact clone detection ──────────────────────────────────────────────

def test_exact_clones():
    # Two identical functions
    src = """
function process_a x
    y = x * 2
    z = y + 1
    return z

function helper
    return 0

function process_b x
    y = x * 2
    z = y + 1
    return z
"""
    path, d = make_srv(src)
    try:
        ast = parse_file(path)
        frags = extract_fragments(ast, path, min_size=3)
        groups = detect_exact_clones(frags)
        # Should find the duplicated function body pattern
        check("exact_clones returns list", isinstance(groups, list))
        # The two identical functions should be detected
        exact_found = len(groups) > 0
        check("exact clones detected", exact_found)
        if exact_found:
            check("clone type is exact", groups[0].clone_type == 'exact')
            check("at least 2 fragments", len(groups[0].fragments) >= 2)
    finally:
        shutil.rmtree(d)


# ── Test: Renamed clone detection ────────────────────────────────────────────

def test_renamed_clones():
    # Same structure, different variable names
    src = """
function calc_area width height
    result = width * height
    return result

function calc_volume length depth
    output = length * depth
    return output
"""
    path, d = make_srv(src)
    try:
        ast = parse_file(path)
        frags = extract_fragments(ast, path, min_size=3)
        
        # Check that normalization makes them match
        func_frags = [f for f in frags if 'FunctionDef' in f.fingerprint]
        if len(func_frags) >= 2:
            check("normalized fps differ from raw",
                  func_frags[0].fingerprint != func_frags[0].normalized_fingerprint)
        
        groups = detect_renamed_clones(frags)
        check("renamed_clones returns list", isinstance(groups, list))
    finally:
        shutil.rmtree(d)


# ── Test: Fingerprint similarity ─────────────────────────────────────────────

def test_fingerprint_similarity():
    fp_a = "(FunctionDef name=foo (Assign x (BinOp + a b)))"
    fp_b = "(FunctionDef name=bar (Assign y (BinOp + c d)))"
    fp_c = "(WhileLoop (BinOp < i n) (Assign i (BinOp + i 1)))"
    
    sim_same = _fingerprint_similarity(fp_a, fp_a)
    check("identical fingerprints = 1.0", sim_same == 1.0)
    
    sim_similar = _fingerprint_similarity(fp_a, fp_b)
    check("similar fingerprints > 0", sim_similar > 0)
    
    sim_different = _fingerprint_similarity(fp_a, fp_c)
    check("different fingerprints < similar", sim_different < sim_similar or sim_different < 0.5)
    
    sim_empty = _fingerprint_similarity("", "")
    check("empty fingerprints = 0", sim_empty == 0.0)


# ── Test: DRY score computation ──────────────────────────────────────────────

def test_dry_score():
    # No clones = perfect score
    report_clean = CloneReport(total_fragments=50, clone_groups=[])
    score_clean = compute_dry_score(report_clean)
    check("no clones = 100", score_clean == 100.0)
    
    # Some clones reduce score
    frag = CodeFragment(file="test.srv", start_line=1, end_line=5, node=None, size=15)
    group = CloneGroup(clone_type='exact', fragments=[frag, frag], size=15)
    report_some = CloneReport(total_fragments=50, clone_groups=[group])
    score_some = compute_dry_score(report_some)
    check("some clones < 100", score_some < 100.0)
    check("some clones > 0", score_some > 0.0)
    
    # Many clones = low score
    groups_many = [CloneGroup(clone_type='exact', fragments=[frag]*4, size=25)
                   for _ in range(10)]
    report_many = CloneReport(total_fragments=50, clone_groups=groups_many)
    score_many = compute_dry_score(report_many)
    check("many clones lower score", score_many < score_some)


# ── Test: Severity classification ────────────────────────────────────────────

def test_severity():
    frag = CodeFragment(file="test.srv", start_line=1, end_line=5, node=None, size=10)
    
    g_critical = CloneGroup(clone_type='exact', fragments=[frag]*4, size=35)
    check("critical severity", classify_severity(g_critical) == "critical")
    
    g_high = CloneGroup(clone_type='exact', fragments=[frag]*2, size=25)
    check("high severity", classify_severity(g_high) == "high")
    
    g_medium = CloneGroup(clone_type='exact', fragments=[frag]*3, size=8)
    check("medium severity", classify_severity(g_medium) == "medium")
    
    g_low = CloneGroup(clone_type='exact', fragments=[frag]*2, size=6)
    check("low severity", classify_severity(g_low) == "low")


# ── Test: Refactoring suggestions ────────────────────────────────────────────

def test_refactoring():
    frag = CodeFragment(file="test.srv", start_line=1, end_line=5, node=None, size=20)
    
    g_exact = CloneGroup(clone_type='exact', fragments=[frag]*2, size=20)
    suggestion = suggest_refactoring(g_exact)
    check("exact suggestion exists", suggestion is not None)
    check("exact suggestion non-empty", len(suggestion) > 0)
    
    g_renamed = CloneGroup(clone_type='renamed', fragments=[frag]*2, size=20)
    suggestion_r = suggest_refactoring(g_renamed)
    check("renamed suggestion exists", suggestion_r is not None)
    check("renamed mentions parameterize", "parameterize" in suggestion_r.lower() or "parameter" in suggestion_r.lower())
    
    g_gapped = CloneGroup(clone_type='gapped', fragments=[frag]*2, size=25)
    suggestion_g = suggest_refactoring(g_gapped)
    check("gapped suggestion exists", suggestion_g is not None)


# ── Test: Insights generation ────────────────────────────────────────────────

def test_insights():
    # Empty report
    report_empty = CloneReport(clone_groups=[])
    insights_empty = generate_insights(report_empty)
    check("empty insights exist", len(insights_empty) > 0)
    check("empty insights mention no duplication", "no" in insights_empty[0].lower() or "No" in insights_empty[0])
    
    # Report with clones
    frag = CodeFragment(file="test.srv", start_line=1, end_line=5, node=None, size=15)
    groups = [CloneGroup(clone_type='exact', fragments=[frag]*3, size=20, severity='high')
              for _ in range(5)]
    report = CloneReport(clone_groups=groups, dry_score=45.0)
    insights = generate_insights(report)
    check("clone insights generated", len(insights) > 1)


# ── Test: Text formatter ─────────────────────────────────────────────────────

def test_format_text():
    report = CloneReport(
        files_scanned=3, total_lines=100, total_fragments=20,
        dry_score=75.5, clone_groups=[], insights=["All good"]
    )
    text = format_text(report)
    check("text has header", "SAURAVCLONE" in text)
    check("text has dry score", "75.5" in text)
    check("text has files scanned", "3" in text)


# ── Test: JSON formatter ─────────────────────────────────────────────────────

def test_format_json():
    frag = CodeFragment(file="test.srv", start_line=5, end_line=10, node=None, size=12)
    group = CloneGroup(clone_type='exact', fragments=[frag], size=12,
                       severity='medium', confidence=0.8, refactoring="Extract function")
    report = CloneReport(
        files_scanned=2, total_lines=80, total_fragments=15,
        dry_score=82.0, clone_groups=[group], insights=["Some duplication"]
    )
    output = format_json(report)
    data = json.loads(output)
    check("json has dry_score", data["dry_score"] == 82.0)
    check("json has clone_groups", len(data["clone_groups"]) == 1)
    check("json group has type", data["clone_groups"][0]["clone_type"] == "exact")
    check("json has insights", len(data["insights"]) == 1)


# ── Test: HTML generation ────────────────────────────────────────────────────

def test_html_generation():
    frag = CodeFragment(file="test.srv", start_line=1, end_line=5, node=None, size=10)
    group = CloneGroup(clone_type='renamed', fragments=[frag]*2, size=10,
                       severity='medium', similarity=0.95, confidence=0.75,
                       refactoring="Parameterize")
    report = CloneReport(
        files_scanned=1, total_lines=50, total_fragments=10,
        dry_score=88.0, clone_groups=[group], insights=["Minor duplication"]
    )
    
    d = tempfile.mkdtemp()
    try:
        html_path = os.path.join(d, "report.html")
        generate_html(report, html_path)
        check("html file created", os.path.exists(html_path))
        with open(html_path, 'r') as f:
            content = f.read()
        check("html has title", "sauravclone" in content)
        check("html has score", "88" in content)
        check("html has clone type", "renamed" in content)
    finally:
        shutil.rmtree(d)


# ── Test: File collection ────────────────────────────────────────────────────

def test_collect_files():
    d = tempfile.mkdtemp()
    try:
        # Create test .srv files
        for name in ["a.srv", "b.srv", "c.txt"]:
            with open(os.path.join(d, name), 'w') as f:
                f.write("x = 1\n")
        
        files = collect_files(d)
        check("collects .srv files", len(files) == 2)
        check("skips non-srv", all(f.endswith('.srv') for f in files))
        
        # Recursive
        sub = os.path.join(d, "sub")
        os.makedirs(sub)
        with open(os.path.join(sub, "d.srv"), 'w') as f:
            f.write("y = 2\n")
        
        files_r = collect_files(d, recursive=True)
        check("recursive finds nested", len(files_r) == 3)
    finally:
        shutil.rmtree(d)


# ── Test: Refactoring confidence ─────────────────────────────────────────────

def test_refactoring_confidence():
    frag = CodeFragment(file="test.srv", start_line=1, end_line=5, node=None, size=10)
    
    g_exact_big = CloneGroup(clone_type='exact', fragments=[frag]*5, size=30)
    conf_high = _refactoring_confidence(g_exact_big)
    check("high confidence > 0.5", conf_high > 0.5)
    
    g_gapped_small = CloneGroup(clone_type='gapped', fragments=[frag]*2, size=5)
    conf_low = _refactoring_confidence(g_gapped_small)
    check("low confidence < high", conf_low < conf_high)


# ── Test: Full pipeline with real .srv ───────────────────────────────────────

def test_full_pipeline():
    src = """
function compute_tax income
    rate = 0.3
    tax = income * rate
    return tax

function compute_bonus salary
    rate = 0.1
    bonus = salary * rate
    return bonus

function compute_discount price
    rate = 0.2
    discount = price * rate
    return discount

x = 10
y = 20
z = x + y
"""
    path, d = make_srv(src)
    try:
        report = detect_clones([path], min_size=3)
        check("pipeline returns report", isinstance(report, CloneReport))
        check("pipeline scans 1 file", report.files_scanned == 1)
        check("pipeline has dry_score", 0 <= report.dry_score <= 100)
        check("pipeline has insights", len(report.insights) > 0)
    finally:
        shutil.rmtree(d)


# ── Test: Multi-file clone detection ─────────────────────────────────────────

def test_multi_file():
    src_a = """
function validate input
    if input == ""
        return false
    if len(input) > 100
        return false
    return true
"""
    src_b = """
function check data
    if data == ""
        return false
    if len(data) > 100
        return false
    return true
"""
    d = tempfile.mkdtemp()
    try:
        path_a = os.path.join(d, "a.srv")
        path_b = os.path.join(d, "b.srv")
        with open(path_a, 'w') as f:
            f.write(src_a)
        with open(path_b, 'w') as f:
            f.write(src_b)
        
        report = detect_clones([d], min_size=3)
        check("multi-file scans 2 files", report.files_scanned == 2)
        check("multi-file has score", report.dry_score is not None)
    finally:
        shutil.rmtree(d)


# ── Test: Edge cases ─────────────────────────────────────────────────────────

def test_edge_cases():
    # Empty file
    path, d = make_srv("")
    try:
        report = detect_clones([path])
        check("empty file no crash", report.files_scanned == 1)
        check("empty file score 100", report.dry_score == 100.0)
    finally:
        shutil.rmtree(d)
    
    # Single statement
    path2, d2 = make_srv("x = 1")
    try:
        report2 = detect_clones([path2])
        check("single stmt no crash", report2.files_scanned == 1)
    finally:
        shutil.rmtree(d2)
    
    # Non-existent path
    report3 = detect_clones(["/nonexistent/path.srv"])
    check("nonexistent path no crash", report3.files_scanned == 0)


# ── Run all tests ────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("Testing sauravclone...")
    print()
    
    test_parse_and_extract()
    test_exact_clones()
    test_renamed_clones()
    test_fingerprint_similarity()
    test_dry_score()
    test_severity()
    test_refactoring()
    test_insights()
    test_format_text()
    test_format_json()
    test_html_generation()
    test_collect_files()
    test_refactoring_confidence()
    test_full_pipeline()
    test_multi_file()
    test_edge_cases()
    
    print()
    print(f"Results: {PASS} passed, {FAIL} failed out of {PASS + FAIL} checks")
    if FAIL:
        sys.exit(1)
    else:
        print("All tests passed!")
