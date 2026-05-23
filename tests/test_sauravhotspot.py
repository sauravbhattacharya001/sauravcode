"""Tests for sauravhotspot."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import sauravhotspot as sh


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(cwd: Path, *args: str, env: dict | None = None) -> None:
    e = os.environ.copy()
    if env:
        e.update(env)
    subprocess.run(args, cwd=str(cwd), check=True, capture_output=True, env=e)


def _git_env(name: str = "Tester", email: str = "t@example.com") -> dict:
    return {
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
    }


def _commit(
    repo: Path,
    files: dict[str, str],
    msg: str,
    when: datetime,
    author: str = "Alice",
) -> None:
    for rel, content in files.items():
        full = repo / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
    _run(repo, "git", "add", "-A")
    env = _git_env(name=author, email=f"{author.lower()}@example.com")
    iso = when.strftime("%Y-%m-%dT%H:%M:%S")
    env["GIT_AUTHOR_DATE"] = iso
    env["GIT_COMMITTER_DATE"] = iso
    _run(repo, "git", "commit", "-m", msg, env=env)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _run(r, "git", "init", "-q", "-b", "main")
    _run(r, "git", "config", "user.email", "t@example.com")
    _run(r, "git", "config", "user.name", "Tester")
    return r


def _fixed_now() -> datetime:
    return datetime(2026, 5, 23, 5, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_analyze_handles_empty_repo(repo: Path) -> None:
    advisor = sh.HotspotAdvisor(root=repo, now_fn=_fixed_now)
    report = advisor.analyze()
    assert report.findings == []
    assert report.grade == "A"
    assert report.portfolio_risk_score == 0.0
    assert any("EMPTY_HISTORY" in i or "HEALTHY" in i for i in report.insights)
    # No P0/P1 actions, just the healthy fallback
    assert all(a.priority >= sh.P3 for a in report.playbook)


def test_high_churn_bug_prone_file_becomes_hotspot(repo: Path) -> None:
    base = _fixed_now() - timedelta(days=30)
    # Big file -> high complexity
    big = "line\n" * 2200
    _commit(repo, {"core.py": big}, "feat: initial", base)
    # 20 follow-up commits, mostly fix commits, recent, multi-author
    authors = ["Alice", "Bob", "Carol", "Dan"]
    for i in range(20):
        big = big + f"# tweak {i}\n"
        msg = "fix: regression in core" if i % 4 != 3 else "chore: tidy"
        author = authors[i % len(authors)]
        when = base + timedelta(days=3 + i)
        _commit(repo, {"core.py": big}, msg, when, author=author)

    advisor = sh.HotspotAdvisor(root=repo, lookback_days=90, now_fn=_fixed_now)
    report = advisor.analyze()
    paths = [f.path for f in report.findings]
    assert "core.py" in paths
    core = next(f for f in report.findings if f.path == "core.py")
    assert core.verdict == sh.V_HOTSPOT
    assert core.priority == sh.P0
    assert core.risk_score >= 60
    assert "HIGH_CHURN" in core.reasons or "MODERATE_CHURN" in core.reasons
    assert any(r in core.reasons for r in ("BUG_PRONE", "FIX_HEAVY"))
    assert "LARGE_MODULE" in core.reasons or "MEDIUM_MODULE" in core.reasons


def test_stable_file_is_not_a_hotspot(repo: Path) -> None:
    base = _fixed_now() - timedelta(days=60)
    _commit(repo, {"util.py": "def add(a, b):\n    return a + b\n"}, "feat", base)
    advisor = sh.HotspotAdvisor(root=repo, now_fn=_fixed_now)
    report = advisor.analyze()
    util = next(f for f in report.findings if f.path == "util.py")
    assert util.verdict in (sh.V_STABLE, sh.V_COOL)
    assert util.priority >= sh.P2
    assert report.grade in ("A", "B")


def test_excludes_binary_and_lockfiles(repo: Path) -> None:
    base = _fixed_now() - timedelta(days=5)
    _commit(repo, {
        "src.py": "x = 1\n",
        "package-lock.json": "{}\n",
        "vendor.min.js": "var a=1;\n",
    }, "feat", base)
    advisor = sh.HotspotAdvisor(root=repo, now_fn=_fixed_now)
    report = advisor.analyze()
    paths = {f.path for f in report.findings}
    assert "src.py" in paths
    assert "package-lock.json" not in paths
    assert "vendor.min.js" not in paths


def test_risk_appetite_changes_scoring(repo: Path) -> None:
    base = _fixed_now() - timedelta(days=20)
    src = "line\n" * 600
    _commit(repo, {"m.py": src}, "feat", base)
    for i in range(5):
        src += f"# {i}\n"
        msg = "fix: bug " + str(i) if i < 3 else "chore"
        _commit(repo, {"m.py": src}, msg, base + timedelta(days=i + 1))

    cautious = sh.HotspotAdvisor(root=repo, risk_appetite="cautious", now_fn=_fixed_now).analyze()
    aggressive = sh.HotspotAdvisor(root=repo, risk_appetite="aggressive", now_fn=_fixed_now).analyze()
    c_score = next(f for f in cautious.findings if f.path == "m.py").risk_score
    a_score = next(f for f in aggressive.findings if f.path == "m.py").risk_score
    assert c_score > a_score


def test_playbook_contains_refactor_when_hotspot_exists(repo: Path) -> None:
    base = _fixed_now() - timedelta(days=15)
    big = "line\n" * 2200
    _commit(repo, {"hot.py": big}, "feat", base)
    for i in range(10):
        big += f"# {i}\n"
        _commit(repo, {"hot.py": big}, "fix: thing " + str(i),
                base + timedelta(days=i + 1))
    advisor = sh.HotspotAdvisor(root=repo, now_fn=_fixed_now)
    report = advisor.analyze()
    ids = {a.id for a in report.playbook}
    assert "REFACTOR_HOTSPOT" in ids
    assert "ADD_REGRESSION_TESTS" in ids
    # Playbook ordered by priority asc
    pris = [a.priority for a in report.playbook]
    assert pris == sorted(pris)


def test_format_outputs_all_three_shapes(repo: Path) -> None:
    base = _fixed_now() - timedelta(days=5)
    _commit(repo, {"a.py": "x=1\n"}, "feat", base)
    report = sh.HotspotAdvisor(root=repo, now_fn=_fixed_now).analyze()
    text = report.format("text")
    md = report.format("md")
    js = report.format("json")
    assert "Hotspot grade" in text
    assert md.startswith("# Hotspot report")
    payload = json.loads(js)
    assert payload["grade"] in ("A", "B", "C", "D", "F")
    assert "findings" in payload and isinstance(payload["findings"], list)
    # Byte-stable JSON (sorted keys)
    assert js == report.format("json")


def test_include_glob_filters_paths(repo: Path) -> None:
    base = _fixed_now() - timedelta(days=4)
    _commit(repo, {
        "src/a.py": "x=1\n",
        "tests/test_a.py": "x=1\n",
    }, "feat", base)
    advisor = sh.HotspotAdvisor(
        root=repo, include_globs=["src/*"], now_fn=_fixed_now,
    )
    report = advisor.analyze()
    paths = {f.path for f in report.findings}
    assert "src/a.py" in paths
    assert "tests/test_a.py" not in paths


def test_invalid_risk_appetite_raises() -> None:
    with pytest.raises(ValueError):
        sh.HotspotAdvisor(risk_appetite="reckless")


def test_invalid_lookback_raises() -> None:
    with pytest.raises(ValueError):
        sh.HotspotAdvisor(lookback_days=0)
    with pytest.raises(ValueError):
        sh.HotspotAdvisor(top=0)


def test_cli_main_runs(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = _fixed_now() - timedelta(days=3)
    _commit(repo, {"x.py": "x=1\n"}, "feat", base)
    rc = sh.main(["--root", str(repo), "--format", "json"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert "findings" in payload
    assert payload["risk_appetite"] == "balanced"


def test_grade_escalates_with_multiple_hotspots(repo: Path) -> None:
    base = _fixed_now() - timedelta(days=20)
    for name in ("a.py", "b.py", "c.py"):
        body = "line\n" * 2100
        _commit(repo, {name: body}, "feat: " + name, base)
        for i in range(8):
            body += f"# {i}\n"
            _commit(repo, {name: body}, f"fix: bug {i} in " + name,
                    base + timedelta(days=i + 1))
    report = sh.HotspotAdvisor(root=repo, now_fn=_fixed_now).analyze()
    assert report.grade == "F"
    assert report.portfolio_risk_score >= 60
