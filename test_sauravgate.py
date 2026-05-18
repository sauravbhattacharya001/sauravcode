"""Tests for sauravgate."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

import sauravgate
from sauravgate import ReleaseGate


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    cp = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    return cp


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)
    _git("config", "user.email", "tester@example.com", cwd=repo)
    _git("config", "user.name", "Tester", cwd=repo)
    (repo / "README.md").write_text("# repo\n", encoding="utf-8")
    _git("add", "README.md", cwd=repo)
    _git("commit", "-q", "-m", "initial", cwd=repo)
    return repo


def _ensure_git_or_skip():
    try:
        cp = subprocess.run(["git", "--version"], capture_output=True, text=True)
        if cp.returncode != 0:
            pytest.skip("git not available")
    except FileNotFoundError:
        pytest.skip("git not available")


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def test_clean_repo_ships(tmp_path):
    _ensure_git_or_skip()
    repo = _init_repo(tmp_path)
    gate = ReleaseGate(root=str(repo))
    report = gate.scan()
    assert report.verdict in ("SHIP", "STAGE")
    assert report.readiness_score >= 70
    assert report.grade in ("A", "B", "C")
    # No P0 in a clean repo.
    assert all(a.priority != "P0" for a in report.actions)


def test_uncommitted_changes_trigger_action(tmp_path):
    _ensure_git_or_skip()
    repo = _init_repo(tmp_path)
    for i in range(10):
        (repo / f"f{i}.txt").write_text(f"hello {i}\n", encoding="utf-8")
    gate = ReleaseGate(root=str(repo))
    report = gate.scan()
    codes = {s.code for s in report.signals}
    assert "UNCOMMITTED_CHANGES" in codes
    sig = next(s for s in report.signals if s.code == "UNCOMMITTED_CHANGES")
    assert sig.severity >= 80
    action_ids = {a.id for a in report.actions}
    assert "COMMIT_OR_STASH_CHANGES" in action_ids


def test_new_python_without_tests_flags(tmp_path):
    _ensure_git_or_skip()
    repo = _init_repo(tmp_path)
    (repo / "newmod.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    _git("add", "newmod.py", cwd=repo)
    _git("commit", "-q", "-m", "add newmod", cwd=repo)
    # Set up a target branch pointing at first commit so newmod appears as added.
    cp = _git("rev-parse", "HEAD~1", cwd=repo)
    initial = cp.stdout.strip()
    _git("branch", "baseline", initial, cwd=repo)
    gate = ReleaseGate(root=str(repo), target_branch="baseline")
    report = gate.scan()
    codes = {s.code for s in report.signals}
    assert "NEW_FILES_NO_TESTS" in codes
    sig = next(s for s in report.signals if s.code == "NEW_FILES_NO_TESTS")
    assert sig.severity > 0
    assert any("newmod.py" in e for e in sig.evidence)
    assert any(a.id == "ADD_TESTS_FOR_NEW_FILES" for a in report.actions)


def test_merge_conflict_markers_block(tmp_path):
    _ensure_git_or_skip()
    repo = _init_repo(tmp_path)
    conflicted = repo / "conflict.txt"
    conflicted.write_text(
        "before\n<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> branch\nafter\n",
        encoding="utf-8",
    )
    _git("add", "conflict.txt", cwd=repo)
    _git("commit", "-q", "-m", "wip", cwd=repo)
    gate = ReleaseGate(root=str(repo))
    report = gate.scan()
    assert report.verdict == "BLOCK"
    assert report.grade == "F"
    assert any(a.id == "RESOLVE_MERGE_CONFLICTS" and a.priority == "P0" for a in report.actions)


def test_risk_appetite_shifts_score(tmp_path):
    _ensure_git_or_skip()
    repo = _init_repo(tmp_path)
    (repo / "dirty.txt").write_text("x\n", encoding="utf-8")
    balanced = ReleaseGate(root=str(repo), risk_appetite="balanced").scan().readiness_score
    cautious = ReleaseGate(root=str(repo), risk_appetite="cautious").scan().readiness_score
    aggressive = ReleaseGate(root=str(repo), risk_appetite="aggressive").scan().readiness_score
    assert cautious <= balanced <= aggressive


def test_json_output_is_deterministic(tmp_path):
    _ensure_git_or_skip()
    repo = _init_repo(tmp_path)
    fixed_now = lambda: datetime(2026, 5, 17, 12, 0, 0, tzinfo=timezone.utc)
    a = ReleaseGate(root=str(repo), now=fixed_now).scan().format("json")
    b = ReleaseGate(root=str(repo), now=fixed_now).scan().format("json")
    assert a == b
    parsed = json.loads(a)
    assert parsed["verdict"] in ("SHIP", "STAGE", "HOLD", "BLOCK")


def test_markdown_contains_sections(tmp_path):
    _ensure_git_or_skip()
    repo = _init_repo(tmp_path)
    (repo / "x.txt").write_text("y\n", encoding="utf-8")
    md = ReleaseGate(root=str(repo)).scan().format("md")
    assert "## Signals" in md
    assert "## Playbook" in md


def test_text_contains_headline(tmp_path):
    _ensure_git_or_skip()
    repo = _init_repo(tmp_path)
    report = ReleaseGate(root=str(repo)).scan()
    txt = report.format("text")
    assert report.summary in txt
    assert "verdict=" in txt


def test_non_git_directory_degrades(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "hello.txt").write_text("hi\n", encoding="utf-8")
    report = ReleaseGate(root=str(plain)).scan()
    # Should not crash; should note degradation.
    assert any("not a git repository" in i for i in report.insights)
    # Verdict should still resolve.
    assert report.verdict in ("SHIP", "STAGE", "HOLD", "BLOCK")


def test_format_unknown_raises(tmp_path):
    _ensure_git_or_skip()
    repo = _init_repo(tmp_path)
    report = ReleaseGate(root=str(repo)).scan()
    with pytest.raises(ValueError):
        report.format("yaml")


def test_priority_for_buckets():
    assert sauravgate._priority_for(95) == "P0"
    assert sauravgate._priority_for(80) == "P0"
    assert sauravgate._priority_for(70) == "P1"
    assert sauravgate._priority_for(45) == "P2"
    assert sauravgate._priority_for(10) == "P3"


def test_cli_runs(tmp_path, capsys):
    _ensure_git_or_skip()
    repo = _init_repo(tmp_path)
    rc = sauravgate.main(["--root", str(repo), "--format", "text"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "verdict=" in captured.out
