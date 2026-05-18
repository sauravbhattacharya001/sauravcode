"""Tests for sauravreview - code-review focus advisor."""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sauravreview as sr


def _fake_repo(srv_files=None, test_files=None, test_text="", target="origin/main"):
    return sr.RepoState(
        is_git=True,
        target_branch=target,
        test_files=list(test_files or []),
        test_corpus_text=test_text,
        srv_files=dict(srv_files or {}),
        recently_rewritten={},
    )


def _advisor(diff_text, state=None, risk="balanced"):
    state = state or _fake_repo()
    return sr.ReviewFocusAdvisor(
        root=".",
        target_branch=state.target_branch,
        risk_appetite=risk,
        diff_provider=lambda root, tb: diff_text,
        repo_provider=lambda root, tb: state,
    )


# ---------------------------------------------------------------------------

def test_not_a_git_repo_returns_clean_report():
    state = sr.RepoState(is_git=False)
    adv = sr.ReviewFocusAdvisor(
        root=".",
        diff_provider=lambda r, t: "",
        repo_provider=lambda r, t: state,
    )
    rep = adv.scan()
    assert rep.items == []
    assert rep.grade == "A"
    assert "not a git repository" in rep.headline
    assert "not_a_git_repository" in rep.insights


def test_clean_repo_no_changes_quiet_pr():
    adv = _advisor(diff_text="")
    rep = adv.scan()
    assert rep.items == []
    assert "QUIET_PR" in rep.insights
    assert rep.grade == "A"


def test_new_function_yields_new_hotspot_p0():
    diff = """diff --git a/foo.srv b/foo.srv
--- a/foo.srv
+++ b/foo.srv
@@ -0,0 +1,8 @@
+def compute_total(items):
+    total = 0
+    for i in items:
+        if i > 0:
+            total = total + i
+        elif i < -10:
+            total = total - i
+    return total
"""
    rep = _advisor(diff).scan()
    assert len(rep.items) == 1
    it = rep.items[0]
    assert it.function == "compute_total"
    assert it.verdict in ("NEW_HOTSPOT", "DEEP_REVIEW", "BLOCK_REVIEW", "SECURITY_REVIEW")
    # New function should be P0 (NEW_HOTSPOT) given the complexity bumps
    assert any(r["code"] == "NEW_FUNCTION" for r in it.reasons)
    assert any(r["code"] == "NO_TEST_COVERAGE" for r in it.reasons)


def test_secret_literal_forces_block_review_p0():
    diff = """diff --git a/secrets.srv b/secrets.srv
--- a/secrets.srv
+++ b/secrets.srv
@@ -1,0 +2,1 @@ def load():
+AWS_KEY = "AKIAABCDEFGHIJKLMNOP"
"""
    rep = _advisor(diff).scan()
    assert any(it.verdict == "BLOCK_REVIEW" for it in rep.items)
    assert any(it.priority == "P0" for it in rep.items)
    assert "SECURITY_HOTSPOT_PRESENT" in rep.insights


def test_eval_introduction_forces_block_review():
    diff = """diff --git a/danger.srv b/danger.srv
--- a/danger.srv
+++ b/danger.srv
@@ -1,0 +2,1 @@ def run_user_code(src):
+    result = eval(src)
"""
    rep = _advisor(diff).scan()
    assert any(it.verdict == "BLOCK_REVIEW" for it in rep.items)
    assert any(any(r["code"] == "EVAL_OR_EXEC" for r in it.reasons) for it in rep.items)
    ids = {a["id"] for a in rep.playbook}
    assert "SECURITY_DEEP_DIVE" in ids
    assert "RESET_BEFORE_MERGE" in ids


def test_auth_keyword_promotes_to_security_review():
    diff = """diff --git a/login.srv b/login.srv
--- a/login.srv
+++ b/login.srv
@@ -1,0 +2,1 @@ def check(user):
+    if user.password == provided:
+        return True
"""
    rep = _advisor(diff).scan()
    assert any(it.verdict in ("SECURITY_REVIEW", "BLOCK_REVIEW") for it in rep.items)


def test_comment_only_change_becomes_rubber_stamp():
    diff = """diff --git a/util.srv b/util.srv
--- a/util.srv
+++ b/util.srv
@@ -1,1 +1,1 @@ def add(a, b):
-# old comment about adding
+# new better comment about adding
"""
    rep = _advisor(diff).scan()
    assert rep.items
    assert all(it.verdict == "RUBBER_STAMP" for it in rep.items)
    assert all(it.priority == "P3" for it in rep.items)


def test_trivial_rename_becomes_skim():
    diff = """diff --git a/util.srv b/util.srv
--- a/util.srv
+++ b/util.srv
@@ -1,1 +1,1 @@ def add(a, b):
-    result = a + b
+    answer = a + b
"""
    rep = _advisor(diff).scan()
    assert rep.items
    # should be SKIM or RUBBER_STAMP, not DEEP_REVIEW
    for it in rep.items:
        assert it.verdict in ("SKIM", "RUBBER_STAMP", "STANDARD_REVIEW")
        assert it.review_priority_score <= 25


def test_risk_appetite_monotonic_scoring():
    diff = """diff --git a/x.srv b/x.srv
--- a/x.srv
+++ b/x.srv
@@ -1,5 +1,12 @@ def big():
+    if a:
+        if b:
+            for c in d:
+                while e:
+                    pass
+    if z:
+        pass
"""
    scores = {}
    for risk in ("cautious", "balanced", "aggressive"):
        rep = _advisor(diff, risk=risk).scan()
        scores[risk] = sum(it.review_priority_score for it in rep.items)
    assert scores["cautious"] >= scores["balanced"] >= scores["aggressive"]


def test_high_blast_radius_uses_corpus():
    diff = """diff --git a/core.srv b/core.srv
--- a/core.srv
+++ b/core.srv
@@ -1,1 +1,2 @@ def utility():
+    return 42
"""
    callers = "\n".join(f"x = utility()" for _ in range(15))
    state = _fake_repo(srv_files={
        "core.srv": "def utility(): pass",
        "caller_a.srv": callers,
    })
    rep = _advisor(diff, state=state).scan()
    found = False
    for it in rep.items:
        for r in it.reasons:
            if r["code"] == "HIGH_BLAST_RADIUS":
                found = True
    assert found


def test_markdown_has_required_sections():
    diff = """diff --git a/foo.srv b/foo.srv
--- a/foo.srv
+++ b/foo.srv
@@ -0,0 +1,3 @@
+def greet(name):
+    return "hi " + name
"""
    rep = _advisor(diff).scan()
    md = rep.to_markdown()
    assert "# Review Focus Report" in md
    assert "## Items" in md
    assert "## Playbook" in md
    assert "## Insights" in md


def test_json_is_byte_stable_and_valid():
    diff = """diff --git a/foo.srv b/foo.srv
--- a/foo.srv
+++ b/foo.srv
@@ -0,0 +1,3 @@
+def greet(name):
+    return "hi " + name
"""
    fixed_now = lambda: __import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc)
    a = sr.ReviewFocusAdvisor(
        root=".", target_branch="origin/main",
        diff_provider=lambda r, t: diff,
        repo_provider=lambda r, t: _fake_repo(),
        now=fixed_now,
    ).scan().to_json()
    b = sr.ReviewFocusAdvisor(
        root=".", target_branch="origin/main",
        diff_provider=lambda r, t: diff,
        repo_provider=lambda r, t: _fake_repo(),
        now=fixed_now,
    ).scan().to_json()
    assert a == b
    parsed = json.loads(a)
    assert "items" in parsed and "playbook" in parsed and "headline" in parsed


def test_no_test_coverage_when_function_not_referenced():
    diff = """diff --git a/foo.srv b/foo.srv
--- a/foo.srv
+++ b/foo.srv
@@ -0,0 +1,2 @@
+def unique_helper_xyz():
+    return 1
"""
    state = _fake_repo(test_files=["test_other.py"], test_text="def test_other(): pass")
    rep = _advisor(diff, state=state).scan()
    assert any(any(r["code"] == "NO_TEST_COVERAGE" for r in it.reasons) for it in rep.items)


def test_invalid_risk_appetite_raises():
    import pytest
    with pytest.raises(ValueError):
        sr.ReviewFocusAdvisor(risk_appetite="paranoid")


def test_format_report_routing():
    rep = _advisor("").scan()
    assert isinstance(sr.format_report(rep, "text"), str)
    assert sr.format_report(rep, "md").startswith("# Review Focus")
    assert json.loads(sr.format_report(rep, "json"))
    import pytest
    with pytest.raises(ValueError):
        sr.format_report(rep, "xml")
