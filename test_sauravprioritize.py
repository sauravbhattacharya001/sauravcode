"""Tests for sauravprioritize."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import sauravprioritize as sp


@pytest.fixture
def project(tmp_path: Path) -> Path:
    # Create a fake source module
    (tmp_path / "mymod.py").write_text(
        "def compute_widget_factor(x):\n    return x * 2\n",
        encoding="utf-8",
    )
    (tmp_path / "other.py").write_text("def unrelated():\n    return 1\n",
                                       encoding="utf-8")

    # Create candidate tests/demos in sauravcode style
    (tmp_path / "test_mymod.srv").write_text(
        "let r = compute_widget_factor 21\nprint r\n", encoding="utf-8"
    )
    (tmp_path / "demo_unrelated.srv").write_text(
        "let q = unrelated\nprint q\n", encoding="utf-8"
    )
    (tmp_path / "completely_other_demo.srv").write_text(
        "print \"hello world\"\n", encoding="utf-8"
    )
    return tmp_path


def test_discovers_srv_tests_and_demos(project: Path) -> None:
    pr = sp.Prioritizer(root=project, changed=["mymod.py"])
    plan = pr.recommend()
    paths = {c.path for c in plan.candidates}
    assert "test_mymod.srv" in paths
    assert "demo_unrelated.srv" in paths
    assert "completely_other_demo.srv" in paths


def test_changed_module_ranks_first(project: Path) -> None:
    pr = sp.Prioritizer(root=project, changed=["mymod.py"])
    plan = pr.recommend()
    assert plan.candidates[0].path == "test_mymod.srv"
    assert plan.candidates[0].total_score > 0
    # the related test should be in the slate
    assert plan.slate[0].path == "test_mymod.srv"


def test_unrelated_files_have_low_score(project: Path) -> None:
    pr = sp.Prioritizer(root=project, changed=["mymod.py"])
    plan = pr.recommend(min_score=0.05)
    slate_paths = [c.path for c in plan.slate]
    assert "completely_other_demo.srv" not in slate_paths


def test_budget_caps_slate_length(project: Path) -> None:
    pr = sp.Prioritizer(root=project, changed=["mymod.py", "other.py"])
    # Force every candidate to be considered, then cap to one
    plan = pr.recommend(top=1, min_score=0.0)
    assert len(plan.slate) == 1


def test_tier_buckets() -> None:
    c = sp.TestCandidate(path="x", size_bytes=0, total_score=0.9)
    assert c.tier == "P0"
    c.total_score = 0.5
    assert c.tier == "P1"
    c.total_score = 0.3
    assert c.tier == "P2"
    c.total_score = 0.01
    assert c.tier == "P3"


def test_format_text_and_md_and_json(project: Path) -> None:
    pr = sp.Prioritizer(root=project, changed=["mymod.py"])
    plan = pr.recommend()
    text = plan.format("text")
    assert "sauravprioritize" in text
    assert "Recommended slate" in text

    md = plan.format("md")
    assert md.startswith("# sauravprioritize")
    assert "| # | tier |" in md

    payload = json.loads(plan.format("json"))
    assert payload["root"] == str(project.resolve()) or payload["root"].endswith(
        project.name
    )
    assert isinstance(payload["candidates"], list)
    assert isinstance(payload["slate"], list)


def test_format_rejects_unknown(project: Path) -> None:
    pr = sp.Prioritizer(root=project, changed=[])
    plan = pr.recommend()
    with pytest.raises(ValueError):
        plan.format("xml")


def test_cli_smoke(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = sp.main([
        "--root", str(project),
        "--changed", "mymod.py",
        "--format", "json",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert any(c["path"] == "test_mymod.srv" for c in data["slate"])


def test_no_changes_returns_empty_slate(project: Path) -> None:
    pr = sp.Prioritizer(root=project, changed=[])
    plan = pr.recommend()
    assert plan.slate == []
    assert plan.candidates  # we still scanned them


def test_changed_file_can_be_missing(project: Path) -> None:
    # Deleted-file scenario: still use the stem as a weak signal.
    pr = sp.Prioritizer(root=project, changed=["mymod.py", "ghost.py"])
    plan = pr.recommend()
    paths = [c.path for c in plan.candidates]
    assert "test_mymod.srv" in paths
