"""Tests for sauravcohort."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Sequence

import pytest

import sauravcohort
from sauravcohort import CohortAdvisor, CohortReport, ModuleCoverage


# ---------------------------------------------------------------------------
# Fake repo builder
# ---------------------------------------------------------------------------


def _now():
    return datetime(2026, 5, 21, 17, 30, 0, tzinfo=timezone.utc)


def _write_module(
    tmp_path: Path,
    name: str,
    *,
    docstring: str = '"""A reasonably long module docstring written for the sauravcohort tests; it must be at least eighty characters long to count as documented."""',
    argparse: bool = True,
    main_block: bool = True,
) -> Path:
    body_parts = [docstring, "", "from __future__ import annotations", ""]
    if argparse:
        body_parts += [
            "import argparse",
            "",
            "def _build_parser():",
            "    return argparse.ArgumentParser()",
            "",
        ]
    if main_block:
        body_parts += [
            'if __name__ == "__main__":',
            "    pass",
        ]
    src = "\n".join(body_parts) + "\n"
    p = tmp_path / f"{name}.py"
    p.write_text(src, encoding="utf-8")
    return p


def _write_demo(tmp_path: Path, topic: str) -> Path:
    p = tmp_path / f"{topic}_demo.srv"
    p.write_text(f"# {topic} demo\n", encoding="utf-8")
    return p


def _write_test(tmp_path: Path, module_name: str, subdir: str = "tests") -> Path:
    if subdir:
        d = tmp_path / subdir
        d.mkdir(exist_ok=True)
    else:
        d = tmp_path
    p = d / f"test_{module_name}.py"
    p.write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    return p


def _write_doc(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def _make_complete_module(tmp_path: Path, name: str, topic: str | None = None) -> None:
    topic = topic if topic is not None else (name[len("saurav"):] if name.startswith("saurav") else name)
    _write_module(tmp_path, name)
    _write_demo(tmp_path, topic)
    _write_test(tmp_path, name)
    # ensure docs mention it
    p = tmp_path / "README.md"
    prev = p.read_text(encoding="utf-8") if p.is_file() else ""
    p.write_text(prev + f"\n- `{name}` is great\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_empty_repo_grades_F(tmp_path: Path):
    report = CohortAdvisor(root=tmp_path, now_fn=_now).scan()
    assert report.summary["total"] == 0
    assert report.grade == "F"
    assert report.portfolio_verdict == "UNHEALTHY"
    assert "EMPTY_COHORT" in report.insights


def test_complete_module_classifies_as_complete(tmp_path: Path):
    _make_complete_module(tmp_path, "sauravalpha", topic="alpha")
    report = CohortAdvisor(root=tmp_path, now_fn=_now).scan()
    assert len(report.modules) == 1
    m = report.modules[0]
    assert m.name == "sauravalpha"
    assert m.verdict == "COMPLETE"
    assert m.priority == "P3"
    assert m.has_demo and m.has_tests and m.has_cli and m.doc_mentions
    assert m.health_score == 100
    assert "FULL_COVERAGE" in report.insights


def test_orphan_module_flagged_P0(tmp_path: Path):
    _write_module(tmp_path, "sauravlonely", argparse=False, main_block=False)
    report = CohortAdvisor(root=tmp_path, now_fn=_now).scan()
    m = report.modules[0]
    assert m.verdict == "ORPHAN"
    assert m.priority == "P0"
    assert not m.has_demo
    assert not m.has_tests
    assert not m.has_cli
    assert not m.doc_mentions
    ids = [a.id for a in report.playbook]
    assert "audit_orphan_modules" in ids


def test_hidden_module_flagged_P1(tmp_path: Path):
    # Has demo + tests + cli but is not mentioned in any doc.
    _write_module(tmp_path, "sauravhidden")
    _write_demo(tmp_path, "hidden")
    _write_test(tmp_path, "sauravhidden")
    report = CohortAdvisor(root=tmp_path, now_fn=_now).scan()
    m = report.modules[0]
    assert m.verdict == "HIDDEN"
    assert m.priority == "P1"
    assert m.has_tests and m.has_demo
    assert not m.doc_mentions
    assert any(a.id == "mention_hidden_in_docs" for a in report.playbook)


def test_untested_module_priority_depends_on_cli(tmp_path: Path):
    # CLI present but tests missing -> P0 (regression risk on a user-facing entry).
    _write_module(tmp_path, "sauravbeta")
    _write_demo(tmp_path, "beta")
    _write_doc(tmp_path, "README.md", "see sauravbeta for details")
    report = CohortAdvisor(root=tmp_path, now_fn=_now).scan()
    m = report.modules[0]
    assert m.verdict == "UNTESTED"
    assert m.priority == "P0"


def test_thin_docstring_flagged_under_documented(tmp_path: Path):
    _make_complete_module(tmp_path, "sauravgamma", topic="gamma")
    # Re-write the module with a very short docstring (<80 chars).
    p = tmp_path / "sauravgamma.py"
    src = (
        '"""tiny."""\n'
        "from __future__ import annotations\n"
        "import argparse\n"
        "def _p(): return argparse.ArgumentParser()\n"
        'if __name__ == "__main__":\n'
        "    pass\n"
    )
    p.write_text(src, encoding="utf-8")
    report = CohortAdvisor(root=tmp_path, now_fn=_now).scan()
    m = report.modules[0]
    assert m.verdict == "UNDER_DOCUMENTED"
    assert m.priority == "P2"
    assert not (m.has_docstring and m.docstring_chars >= 80)


def test_demo_lookup_strips_saurav_prefix(tmp_path: Path):
    _write_module(tmp_path, "sauravchange")
    _write_demo(tmp_path, "change")
    _write_test(tmp_path, "sauravchange")
    _write_doc(tmp_path, "README.md", "sauravchange notes")
    report = CohortAdvisor(root=tmp_path, now_fn=_now).scan()
    m = report.modules[0]
    assert m.has_demo
    assert m.demo_path is not None and m.demo_path.endswith("change_demo.srv")


def test_tests_in_repo_root_are_detected(tmp_path: Path):
    _write_module(tmp_path, "sauravdelta")
    _write_demo(tmp_path, "delta")
    _write_test(tmp_path, "sauravdelta", subdir="")  # root level
    _write_doc(tmp_path, "STDLIB.md", "sauravdelta is documented")
    report = CohortAdvisor(root=tmp_path, now_fn=_now).scan()
    m = report.modules[0]
    assert m.has_tests
    assert m.tests_path is not None and m.tests_path.endswith("test_sauravdelta.py")


def test_cli_requires_both_argparse_and_main(tmp_path: Path):
    # argparse but no __main__ block
    _write_module(tmp_path, "sauravnomain", argparse=True, main_block=False)
    # __main__ but no argparse
    _write_module(tmp_path, "sauravnoarg", argparse=False, main_block=True)
    _write_doc(tmp_path, "README.md", "sauravnomain sauravnoarg")
    report = CohortAdvisor(root=tmp_path, now_fn=_now).scan()
    cli = {m.name: m.has_cli for m in report.modules}
    assert cli["sauravnomain"] is False
    assert cli["sauravnoarg"] is False


def test_portfolio_scores_average_with_appetite(tmp_path: Path):
    # 3 modules: one complete (100), one missing-tests (~70), one orphan (~0)
    _make_complete_module(tmp_path, "sauravone", topic="one")
    # missing-tests + docs
    _write_module(tmp_path, "sauravtwo")
    _write_demo(tmp_path, "two")
    _write_doc(tmp_path, "STDLIB.md", "sauravtwo here")
    # orphan
    _write_module(tmp_path, "sauravthree", argparse=False, main_block=False)

    rb = CohortAdvisor(root=tmp_path, risk_appetite="balanced", now_fn=_now).scan()
    rc = CohortAdvisor(root=tmp_path, risk_appetite="cautious", now_fn=_now).scan()
    ra = CohortAdvisor(root=tmp_path, risk_appetite="aggressive", now_fn=_now).scan()
    assert rb.summary["total"] == 3
    assert rc.portfolio_score <= rb.portfolio_score <= ra.portfolio_score
    # Orphan present -> grade F regardless of appetite.
    assert rb.grade == "F"
    assert "ORPHANED_MODULES_PRESENT" in rb.insights


def test_aggressive_trims_p3_when_higher_priority_present(tmp_path: Path):
    _write_module(tmp_path, "sauravlonely", argparse=False, main_block=False)
    ra = CohortAdvisor(root=tmp_path, risk_appetite="aggressive", now_fn=_now).scan()
    # P0 exists; P3 fallback should not.
    prios = {a.priority for a in ra.playbook}
    assert "P0" in prios
    assert "P3" not in prios


def test_cautious_adds_schedule_audit_on_low_grade(tmp_path: Path):
    _write_module(tmp_path, "sauravlonely", argparse=False, main_block=False)
    rc = CohortAdvisor(root=tmp_path, risk_appetite="cautious", now_fn=_now).scan()
    ids = [a.id for a in rc.playbook]
    assert "schedule_cohort_audit" in ids


def test_playbook_when_only_complete_modules_present_emits_fallback(tmp_path: Path):
    _make_complete_module(tmp_path, "sauravalpha", topic="alpha")
    _make_complete_module(tmp_path, "sauravbravo", topic="bravo")
    report = CohortAdvisor(root=tmp_path, now_fn=_now).scan()
    # Both complete -> no orphans/untested/hidden/under_doc/partial; demo_thresh
    # at balanced=2 not crossed by 0 missing-demo modules.
    ids = {a.id for a in report.playbook}
    assert ids == {"maintain_cohort_discipline"}
    assert report.grade in ("A", "B")
    assert report.portfolio_verdict == "HEALTHY"


def test_json_is_byte_stable(tmp_path: Path):
    _make_complete_module(tmp_path, "sauravalpha", topic="alpha")
    _write_module(tmp_path, "sauravlonely", argparse=False, main_block=False)
    advisor = CohortAdvisor(root=tmp_path, now_fn=_now)
    a = advisor.scan().to_json()
    b = advisor.scan().to_json()
    assert a == b
    data = json.loads(a)
    assert set(["headline", "grade", "modules", "playbook", "insights"]).issubset(data.keys())
    # sort_keys = True -> top-level keys sorted
    keys = list(data.keys())
    assert keys == sorted(keys)


def test_markdown_and_text_renderers_run(tmp_path: Path):
    _make_complete_module(tmp_path, "sauravalpha", topic="alpha")
    _write_module(tmp_path, "sauravlonely", argparse=False, main_block=False)
    report = CohortAdvisor(root=tmp_path, now_fn=_now).scan()
    md = report.to_markdown()
    txt = report.to_text()
    assert "# Module Cohort Coverage" in md
    assert "## Modules" in md
    assert "Cohort:" in txt
    assert "## Playbook" in txt


def test_invalid_risk_appetite_raises(tmp_path: Path):
    with pytest.raises(ValueError):
        CohortAdvisor(root=tmp_path, risk_appetite="reckless")


def test_only_filter_in_cli(tmp_path: Path):
    _make_complete_module(tmp_path, "sauravalpha", topic="alpha")
    _make_complete_module(tmp_path, "sauravbravo", topic="bravo")
    out_path = tmp_path / "cohort.json"
    rc = sauravcohort.main([
        "--root", str(tmp_path),
        "--format", "json",
        "--only", "sauravalpha",
        "--output", str(out_path),
    ])
    assert rc == 0
    data = json.loads(out_path.read_text(encoding="utf-8"))
    names = [m["name"] for m in data["modules"]]
    assert names == ["sauravalpha"]


def test_only_filter_supports_globs(tmp_path: Path):
    _make_complete_module(tmp_path, "sauravalpha", topic="alpha")
    _make_complete_module(tmp_path, "sauravbravo", topic="bravo")
    _make_complete_module(tmp_path, "otherthing", topic="otherthing")
    out_path = tmp_path / "cohort.json"
    rc = sauravcohort.main([
        "--root", str(tmp_path),
        "--format", "json",
        "--only", "saurav*",
        "--output", str(out_path),
    ])
    assert rc == 0
    data = json.loads(out_path.read_text(encoding="utf-8"))
    names = sorted(m["name"] for m in data["modules"])
    assert names == ["sauravalpha", "sauravbravo"]


def test_output_file_written(tmp_path: Path):
    _make_complete_module(tmp_path, "sauravalpha", topic="alpha")
    out = tmp_path / "cohort.md"
    rc = sauravcohort.main([
        "--root", str(tmp_path),
        "--format", "md",
        "--output", str(out),
    ])
    assert rc == 0
    body = out.read_text(encoding="utf-8")
    assert "Module Cohort Coverage" in body


def test_no_demo_threshold_scales_with_appetite(tmp_path: Path):
    # 1 module missing demo + everything else fine
    _write_module(tmp_path, "sauravonly")
    _write_test(tmp_path, "sauravonly")
    _write_doc(tmp_path, "README.md", "sauravonly stuff")
    # cautious threshold is 1, aggressive is 3
    rc = CohortAdvisor(root=tmp_path, risk_appetite="cautious", now_fn=_now).scan()
    ra = CohortAdvisor(root=tmp_path, risk_appetite="aggressive", now_fn=_now).scan()
    cautious_ids = {a.id for a in rc.playbook}
    aggressive_ids = {a.id for a in ra.playbook}
    assert "add_demo_for_no_demo" in cautious_ids
    assert "add_demo_for_no_demo" not in aggressive_ids


def test_deterministic_with_injected_now(tmp_path: Path):
    _make_complete_module(tmp_path, "sauravalpha", topic="alpha")
    r1 = CohortAdvisor(root=tmp_path, now_fn=_now).scan()
    r2 = CohortAdvisor(root=tmp_path, now_fn=_now).scan()
    assert r1.generated_at == r2.generated_at
    assert r1.to_json() == r2.to_json()
