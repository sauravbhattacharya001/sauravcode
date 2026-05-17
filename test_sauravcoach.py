"""Tests for sauravcoach."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import sauravcoach
from sauravcoach import Coach, CoachReport, FEATURE_CATALOGUE


REPO_ROOT = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _write(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_empty_user_root_returns_report(tmp_path: Path) -> None:
    coach = Coach(user_root=tmp_path, demos_root=REPO_ROOT)
    report = coach.recommend()
    assert isinstance(report, CoachReport)
    assert report.user_files_scanned == 0
    assert report.skill_score == 0
    assert report.skill_grade == "F"
    # All catalogued features should be untouched
    assert len(report.untouched) == len(FEATURE_CATALOGUE)
    assert report.mastered == []
    # P0 recommendations exist (weight>=4 features)
    p0 = [r for r in report.recommendations if r.priority == "P0"]
    assert len(p0) >= 1


def test_single_hello_file(tmp_path: Path) -> None:
    _write(tmp_path / "hello.srv", 'print("hello, world")\n')
    report = Coach(user_root=tmp_path, demos_root=REPO_ROOT).recommend()
    assert report.user_files_scanned == 1
    # 'print' should be practiced (1 file)
    assert "print" in report.practiced
    assert "print" not in report.mastered
    assert "print" not in report.untouched
    # untouched is large but not full catalogue
    assert len(report.untouched) < len(FEATURE_CATALOGUE)


def test_mastered_classification(tmp_path: Path) -> None:
    body = 'x = 1\nprint(f"value is {x}")\n'
    _write(tmp_path / "a.srv", body)
    _write(tmp_path / "b.srv", body)
    _write(tmp_path / "c.srv", body)
    skills = {s.feature: s for s in Coach(user_root=tmp_path, demos_root=REPO_ROOT).profile()}
    assert skills["fstring"].skill == "mastered"
    assert len(skills["fstring"].user_files) == 3


def test_practiced_classification(tmp_path: Path) -> None:
    _write(tmp_path / "a.srv", 'print(f"hi {1}")\n')
    skills = {s.feature: s for s in Coach(user_root=tmp_path, demos_root=REPO_ROOT).profile()}
    assert skills["fstring"].skill == "practiced"


def test_adjacency_bonus_lifts_score(tmp_path: Path) -> None:
    # Make user master 'higher_order' and 'lambda' (both link to 'pipe')
    body_ho = "func g(x): return map(lambda y: y+1, x)\n"
    for n in ("a.srv", "b.srv", "c.srv"):
        _write(tmp_path / n, body_ho)
    report = Coach(user_root=tmp_path, demos_root=REPO_ROOT).recommend()
    pipe_rec = next((r for r in report.recommendations if r.feature == "pipe"), None)
    assert pipe_rec is not None
    assert pipe_rec.adjacency_bonus > 0
    assert "higher_order" in pipe_rec.adjacent_mastered or "lambda" in pipe_rec.adjacent_mastered


def test_priority_p0_for_high_weight_untouched(tmp_path: Path) -> None:
    report = Coach(user_root=tmp_path, demos_root=REPO_ROOT).recommend()
    # if_else is weight 5 and untouched -> must be P0
    rec = next((r for r in report.recommendations if r.feature == "if_else"), None)
    assert rec is not None
    assert rec.priority == "P0"


def test_snippet_extraction_for_real_demo(tmp_path: Path) -> None:
    # Use the actual repo demos as the demo source.
    coach = Coach(user_root=tmp_path, demos_root=REPO_ROOT)
    name, snippet = coach._find_snippet("fstring")
    assert name == "fstring_demo.srv"
    assert snippet is not None
    assert len(snippet.splitlines()) >= 1
    assert len(snippet) > 10


def test_snippet_missing_demo_returns_none(tmp_path: Path) -> None:
    # demos_root points at empty tmp dir -> no demo files at all
    empty = tmp_path / "no_demos"
    empty.mkdir()
    coach = Coach(user_root=tmp_path, demos_root=empty)
    name, snippet = coach._find_snippet("forecast")
    assert name is None
    assert snippet is None


def test_format_json_is_valid(tmp_path: Path) -> None:
    _write(tmp_path / "a.srv", 'print("x")\n')
    report = Coach(user_root=tmp_path, demos_root=REPO_ROOT).recommend(top=3)
    blob = report.format("json")
    parsed = json.loads(blob)
    assert parsed["skill_grade"] in {"A", "B", "C", "D", "E", "F"}
    assert isinstance(parsed["recommendations"], list)


def test_format_md_contains_section(tmp_path: Path) -> None:
    report = Coach(user_root=tmp_path, demos_root=REPO_ROOT).recommend(top=3)
    md = report.format("md")
    assert "## Recommendations" in md
    assert "## Skill profile" in md


def test_format_text_contains_grade(tmp_path: Path) -> None:
    report = Coach(user_root=tmp_path, demos_root=REPO_ROOT).recommend(top=3)
    txt = report.format("text")
    assert "grade" in txt.lower()
    assert "Recommendations:" in txt


def test_cli_smoke_json(tmp_path: Path) -> None:
    _write(tmp_path / "a.srv", 'print("x")\n')
    proc = subprocess.run(
        [sys.executable, "-m", "sauravcoach",
         "--root", str(tmp_path),
         "--demos", str(REPO_ROOT),
         "--top", "3",
         "--format", "json"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    parsed = json.loads(proc.stdout)
    assert "recommendations" in parsed
