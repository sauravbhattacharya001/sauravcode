"""Tests for sauravchange."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List, Optional

import pytest

import sauravchange
from sauravchange import ChangelogAdvisor, CommitInfo


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _fake_now():
    return datetime(2026, 5, 18, 14, 35, 0, tzinfo=timezone.utc)


def _make_advisor(commits: List[CommitInfo], risk: str = "balanced",
                  from_ref: Optional[str] = "v1.0.0", to_ref: str = "HEAD"):
    def log_provider(root, frm, to):
        return list(commits)

    def repo_provider(root):
        return {"is_repo": True, "last_tag": "v1.0.0"}

    return ChangelogAdvisor(
        root=".",
        from_ref=from_ref,
        to_ref=to_ref,
        risk_appetite=risk,
        now=_fake_now,
        log_provider=log_provider,
        repo_provider=repo_provider,
    )


def _c(sha, subj, body="", files=None, ins=10, dels=2, author="alice"):
    return CommitInfo(
        sha=sha,
        subject=subj,
        body=body,
        author=author,
        timestamp=1700000000,
        files=files or ["src/foo.py"],
        insertions=ins,
        deletions=dels,
    )


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def test_not_a_git_repo_is_graceful():
    adv = ChangelogAdvisor(
        root=".",
        log_provider=lambda r, f, t: [],
        repo_provider=lambda r: {"is_repo": False, "last_tag": None},
        now=_fake_now,
    )
    rep = adv.scan()
    assert rep.entries == []
    assert rep.release_verdict == "READY"
    assert "not_a_git_repository" in rep.insights


def test_empty_range_returns_ready():
    adv = _make_advisor([])
    rep = adv.scan()
    assert rep.release_verdict == "READY"
    assert rep.grade == "A"
    assert rep.suggested_bump == "none"
    assert "empty_range" in rep.insights


def test_classifies_conventional_commits():
    commits = [
        _c("a" * 40, "feat(api): add new endpoint", files=["src/api.py", "tests/test_api.py"]),
        _c("b" * 40, "fix(parser): handle EOF", files=["src/parser.py", "tests/test_parser.py"]),
        _c("c" * 40, "docs: update README", files=["README.md"]),
    ]
    rep = _make_advisor(commits).scan()
    verdicts = {e.short_sha: e.verdict for e in rep.entries}
    assert verdicts["a" * 7] == "FEATURE"
    assert verdicts["b" * 7] == "FIX"
    assert verdicts["c" * 7] == "DOCS"


def test_breaking_change_trailer_detected():
    commits = [_c(
        "1" * 40,
        "feat: rewrite config",
        body="BREAKING CHANGE: removed legacy fields",
        files=["src/config.py"],
    )]
    rep = _make_advisor(commits).scan()
    e = rep.entries[0]
    assert e.breaking is True
    assert e.verdict == "BREAKING"
    assert e.priority == "P0"
    assert rep.suggested_bump == "major"
    assert any(a["id"] == "ADD_MIGRATION_GUIDE" for a in rep.playbook)


def test_bang_marker_breaking():
    commits = [_c("2" * 40, "feat(api)!: drop v1 endpoints", files=["src/api.py"])]
    rep = _make_advisor(commits).scan()
    assert rep.entries[0].breaking is True
    assert rep.suggested_bump == "major"


def test_security_keyword_promotes_verdict():
    commits = [_c("3" * 40, "fix: patch SSRF in fetch helper", files=["src/net.py", "tests/test_net.py"])]
    rep = _make_advisor(commits).scan()
    e = rep.entries[0]
    assert e.verdict == "SECURITY"
    assert e.priority == "P0"
    assert any(a["id"] == "HIGHLIGHT_SECURITY_FIXES" for a in rep.playbook)


def test_suggest_bump_minor_for_features():
    commits = [_c("4" * 40, "feat: add cache", files=["src/cache.py", "tests/test_cache.py"])]
    rep = _make_advisor(commits).scan()
    assert rep.suggested_bump == "minor"


def test_suggest_bump_patch_for_fix_only():
    commits = [_c("5" * 40, "fix: off-by-one", files=["src/x.py", "tests/test_x.py"])]
    rep = _make_advisor(commits).scan()
    assert rep.suggested_bump == "patch"


def test_no_test_coverage_signal():
    commits = [
        _c("6" * 40, "feat: add module", files=["src/new.py"]),
        _c("7" * 40, "feat: another", files=["src/new2.py"]),
        _c("8" * 40, "feat: third", files=["src/new3.py"]),
    ]
    rep = _make_advisor(commits).scan()
    assert rep.summary["no_test_files_touched"] == 3
    assert any(a["id"] == "VERIFY_TEST_COVERAGE" for a in rep.playbook)


def test_large_diff_flag():
    commits = [
        _c("9" * 40, "refactor: huge", ins=900, dels=200, files=["src/a.py", "tests/test_a.py"]),
        _c("a" * 40 if False else "f" * 40, "refactor: also huge",
           ins=1500, dels=400, files=["src/b.py", "tests/test_b.py"]),
    ]
    rep = _make_advisor(commits).scan()
    assert rep.summary["large_diff"] >= 2
    assert any(a["id"] == "SOLICIT_EXTRA_REVIEW" for a in rep.playbook)


def test_risk_appetite_monotonicity():
    commits = [
        _c("1" * 40, "feat: x", files=["src/x.py"]),
        _c("2" * 40, "feat: y", files=["src/y.py"]),
        _c("3" * 40, "BREAKING: remove v1", body="BREAKING CHANGE: gone", files=["src/api.py"]),
    ]
    cautious = _make_advisor(commits, risk="cautious").scan()
    balanced = _make_advisor(commits, risk="balanced").scan()
    aggressive = _make_advisor(commits, risk="aggressive").scan()
    # Cautious should have at least as many playbook items as aggressive
    assert len(cautious.playbook) >= len(aggressive.playbook)
    # Grade ordering: cautious never better than aggressive
    grade_rank = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4}
    assert grade_rank[cautious.grade] >= grade_rank[aggressive.grade]


def test_revert_classified():
    commits = [_c("1" * 40, "Revert \"feat: experimental cache\"", files=["src/cache.py"])]
    rep = _make_advisor(commits).scan()
    assert rep.entries[0].verdict == "REVERT"
    assert any(a["id"] == "DOCUMENT_REVERTS" for a in rep.playbook)


def test_deprecation_classified():
    commits = [_c("1" * 40, "deprecate: old config keys", files=["src/config.py"])]
    rep = _make_advisor(commits).scan()
    assert rep.entries[0].verdict == "DEPRECATION"
    assert any(a["id"] == "ANNOUNCE_DEPRECATIONS" for a in rep.playbook)


def test_json_is_deterministic():
    commits = [
        _c("1" * 40, "feat: a", files=["src/a.py", "tests/test_a.py"]),
        _c("2" * 40, "fix: b", files=["src/b.py", "tests/test_b.py"]),
    ]
    rep1 = _make_advisor(commits).scan()
    rep2 = _make_advisor(commits).scan()
    assert rep1.to_json() == rep2.to_json()
    # JSON is parseable and has expected keys
    payload = json.loads(rep1.to_json())
    for key in ("entries", "sections", "playbook", "summary", "grade",
                "release_verdict", "suggested_bump", "headline"):
        assert key in payload


def test_markdown_contains_sections():
    commits = [
        _c("1" * 40, "feat: add thing", files=["src/x.py", "tests/test_x.py"]),
        _c("2" * 40, "fix: bug", files=["src/y.py", "tests/test_y.py"]),
        _c("3" * 40, "docs: improve readme", files=["README.md"]),
    ]
    md = _make_advisor(commits).scan().to_markdown()
    assert "# Release Notes Draft" in md
    assert "✨ Features" in md
    assert "🐛 Bug fixes" in md
    assert "📝 Documentation" in md
    assert "## Pre-release playbook" in md
    assert "## Insights" in md


def test_text_headline_present():
    commits = [_c("1" * 40, "feat: add", files=["src/x.py"])]
    txt = _make_advisor(commits).scan().to_text()
    assert "Release draft:" in txt
    assert "Grade:" in txt
    assert "Suggested bump:" in txt


def test_priority_sort_p0_first():
    commits = [
        _c("a" * 40, "chore: format", files=["src/x.py"]),
        _c("b" * 40, "feat!: big rewrite", body="BREAKING CHANGE: yes", files=["src/big.py"]),
        _c("c" * 40, "fix: small", files=["src/s.py", "tests/test_s.py"]),
    ]
    rep = _make_advisor(commits).scan()
    assert rep.entries[0].priority == "P0"


def test_unknown_risk_appetite_raises():
    with pytest.raises(ValueError):
        ChangelogAdvisor(risk_appetite="reckless")


def test_unknown_format_raises_in_cli(tmp_path, monkeypatch, capsys):
    # argparse rejects bad --format
    with pytest.raises(SystemExit):
        sauravchange.main(["--format", "bogus"])


def test_cli_runs_with_empty_repo(tmp_path, monkeypatch, capsys):
    # Point CLI at a non-git tmp dir; should print gracefully and exit 0.
    rc = sauravchange.main(["--root", str(tmp_path), "--format", "text"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Not a git repository" in out or "Grade:" in out
