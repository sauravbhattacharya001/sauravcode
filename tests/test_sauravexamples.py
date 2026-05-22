"""Tests for sauravexamples."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sauravexamples import (
    DEFAULT_OPTIONS,
    DemoAuditor,
    DemoFinding,
    DemoMetrics,
    DemoReport,
    PlaybookAction,
    main,
    scan_demos,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


@pytest.fixture
def healthy_root(tmp_path: Path) -> Path:
    _write(
        tmp_path / "hello.srv",
        "# What this demo shows: hello world\n"
        "name = \"world\"\n"
        "greeting = \"Hello, \"\n"
        "message = greeting + name\n"
        "# Greet the user.\n"
        "print message\n",
    )
    _write(
        tmp_path / "math.srv",
        "# What this demo shows: arithmetic\n"
        "x = 1\n"
        "y = 2\n"
        "z = x + y\n"
        "w = z * 2\n"
        "v = w - 1\n"
        "# Print the result so the reader can verify.\n"
        "print v\n",
    )
    return tmp_path


@pytest.fixture
def messy_root(tmp_path: Path) -> Path:
    # Empty.
    _write(tmp_path / "empty.srv", "")
    # Stub.
    _write(tmp_path / "stub.srv", "x = 1\n")
    # Missing header.
    _write(
        tmp_path / "no_header.srv",
        "a = 1\nb = 2\nc = 3\nd = 4\nprint a + b + c + d\n",
    )
    # Missing print.
    _write(
        tmp_path / "no_output.srv",
        "# What this demo shows: silent computation\n"
        "a = 1\nb = 2\nc = 3\nd = 4\ne = a + b + c + d\n",
    )
    # Duplicate pair.
    dup_body = (
        "# What this demo shows: duplicate\n"
        "name = \"world\"\n"
        "greeting = \"hi\"\n"
        "output = greeting + name\n"
        "print output\n"
    )
    _write(tmp_path / "dup_a.srv", dup_body)
    _write(tmp_path / "dup_b.srv", dup_body)
    # Too long.
    long_body = "# Long demo\n" + "\n".join(f"x{i} = {i}" for i in range(200))
    _write(tmp_path / "long_demo.srv", long_body + "\nprint x199\n")
    # Exemplary.
    _write(
        tmp_path / "exemplary.srv",
        "# What this demo shows: a clean, well-commented example.\n"
        "# Step 1: define inputs.\n"
        "a = 1\n"
        "b = 2\n"
        "# Step 2: compute.\n"
        "c = a + b\n"
        "# Step 3: print the result.\n"
        "print c\n",
    )
    return tmp_path


# ---------------------------------------------------------------------------
# scan_demos / metrics
# ---------------------------------------------------------------------------


def test_scan_demos_finds_srv_files(healthy_root: Path) -> None:
    metrics = scan_demos(healthy_root)
    paths = {m.path for m in metrics}
    assert paths == {"hello.srv", "math.srv"}


def test_scan_demos_skips_hidden_dirs(tmp_path: Path) -> None:
    _write(tmp_path / "ok.srv", "# h\nprint 1\n")
    _write(tmp_path / ".cache" / "skip.srv", "print 1\n")
    paths = {m.path for m in scan_demos(tmp_path)}
    assert paths == {"ok.srv"}


def test_metrics_basic_counts(tmp_path: Path) -> None:
    _write(
        tmp_path / "x.srv",
        "# header\n\nfunction greet name\n  print name\nend\n",
    )
    m = scan_demos(tmp_path)[0]
    assert m.total_lines == 5
    assert m.blank_lines == 1
    assert m.comment_lines == 1
    assert m.code_lines == 3
    assert m.has_header_comment is True
    assert m.has_print is True
    assert m.function_count == 1


def test_metrics_empty_file(tmp_path: Path) -> None:
    _write(tmp_path / "e.srv", "")
    m = scan_demos(tmp_path)[0]
    assert m.code_lines == 0
    assert m.signature == ""


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def test_empty_file_yields_empty_verdict(tmp_path: Path) -> None:
    _write(tmp_path / "e.srv", "")
    report = DemoAuditor(tmp_path).report()
    f = next(f for f in report.findings if f.path == "e.srv")
    assert f.verdict == "EMPTY"
    assert f.priority == "P0"
    assert f.quality_score <= 10


def test_stub_yields_too_short_stub(tmp_path: Path) -> None:
    _write(tmp_path / "stub.srv", "x = 1\n")
    report = DemoAuditor(tmp_path).report()
    f = report.findings[0]
    assert f.verdict == "TOO_SHORT_STUB"
    assert "ONLY_1_CODE_LINES" in f.reasons


def test_long_demo_yields_too_long(tmp_path: Path) -> None:
    body = "# long\n" + "\n".join(f"x{i} = {i}" for i in range(200)) + "\nprint x0\n"
    _write(tmp_path / "long.srv", body)
    report = DemoAuditor(tmp_path).report()
    f = next(f for f in report.findings if f.path == "long.srv")
    assert f.verdict == "TOO_LONG"


def test_missing_header_yields_needs_header(tmp_path: Path) -> None:
    _write(
        tmp_path / "x.srv",
        "a = 1\nb = 2\nc = 3\nd = 4\nprint a\n",
    )
    f = DemoAuditor(tmp_path).report().findings[0]
    assert f.verdict == "NEEDS_HEADER"


def test_missing_print_yields_needs_output(tmp_path: Path) -> None:
    _write(
        tmp_path / "x.srv",
        "# header\na = 1\nb = 2\nc = 3\nd = a + b + c\n",
    )
    f = DemoAuditor(tmp_path).report().findings[0]
    assert f.verdict == "NEEDS_OUTPUT"


def test_duplicate_pair_flagged(tmp_path: Path) -> None:
    body = "# h\na = 1\nb = 2\nc = 3\nd = a + b + c\nprint d\n"
    _write(tmp_path / "a.srv", body)
    _write(tmp_path / "b.srv", body)
    findings = DemoAuditor(tmp_path).report().findings
    verdicts = {f.path: f.verdict for f in findings}
    assert verdicts["a.srv"] == "NEAR_DUPLICATE_OF"
    assert verdicts["b.srv"] == "NEAR_DUPLICATE_OF"
    for f in findings:
        assert f.related  # populated with sibling path


def test_exemplary_demo_is_recognised(healthy_root: Path) -> None:
    report = DemoAuditor(healthy_root).report()
    assert all(f.verdict in ("GOOD", "EXEMPLARY") for f in report.findings)
    assert any(f.verdict == "EXEMPLARY" for f in report.findings)
    assert report.grade in ("A", "B")


# ---------------------------------------------------------------------------
# Playbook & insights
# ---------------------------------------------------------------------------


def test_playbook_contains_actions_for_each_issue(messy_root: Path) -> None:
    report = DemoAuditor(messy_root).report()
    ids = {a.id for a in report.playbook}
    assert "DELETE_EMPTY_DEMOS" in ids
    assert "MERGE_DUPLICATE_DEMOS" in ids
    assert "SPLIT_LARGE_DEMOS" in ids
    assert "ADD_HEADER_COMMENTS" in ids
    assert "ADD_PRINT_OUTPUT" in ids
    assert "EXPAND_STUB_DEMOS" in ids
    # P0 first.
    priorities = [a.priority for a in report.playbook]
    assert priorities == sorted(priorities, key=lambda p: int(p[1:]))


def test_playbook_healthy_when_no_findings(healthy_root: Path) -> None:
    report = DemoAuditor(healthy_root).report()
    ids = {a.id for a in report.playbook}
    assert ids == {"HEALTHY_DEMO_FLEET"}


def test_aggressive_trims_p3_fallback_when_others_present(messy_root: Path) -> None:
    report = DemoAuditor(messy_root).report(risk_appetite="aggressive")
    assert all(a.priority != "P3" for a in report.playbook)


def test_cautious_adds_schedule_review(messy_root: Path) -> None:
    report = DemoAuditor(messy_root).report(risk_appetite="cautious")
    ids = {a.id for a in report.playbook}
    assert "SCHEDULE_DEMO_REVIEW" in ids


def test_insights_flag_empty_and_duplicates(messy_root: Path) -> None:
    report = DemoAuditor(messy_root).report()
    assert "EMPTY_DEMO_FILES_PRESENT" in report.insights
    assert "NEAR_DUPLICATE_CLUSTER" in report.insights


def test_no_demos_grade_is_f(tmp_path: Path) -> None:
    report = DemoAuditor(tmp_path).report()
    assert report.grade == "F"
    assert report.summary["total_demos"] == 0
    assert "NO_DEMOS_FOUND" in report.insights


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def test_text_format_contains_headline_and_sections(messy_root: Path) -> None:
    out = DemoAuditor(messy_root).report().format("text")
    assert out.startswith("VERDICT:")
    assert "Findings" in out
    assert "Playbook" in out
    assert "Insights" in out


def test_markdown_format_has_required_sections(messy_root: Path) -> None:
    out = DemoAuditor(messy_root).report().format("md")
    assert "## Summary" in out
    assert "## Findings" in out
    assert "## Playbook" in out
    assert "## Insights" in out


def test_json_format_is_byte_stable(messy_root: Path) -> None:
    a = DemoAuditor(messy_root).report().format("json")
    b = DemoAuditor(messy_root).report().format("json")
    assert a == b
    payload = json.loads(a)
    assert {"headline", "grade", "summary", "findings", "playbook", "insights"} <= payload.keys()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_writes_output_file(messy_root: Path, tmp_path: Path) -> None:
    out_path = tmp_path / "report.md"
    rc = main(["--root", str(messy_root), "--format", "md", "--output", str(out_path)])
    assert rc == 0
    assert out_path.exists()
    assert "## Summary" in out_path.read_text(encoding="utf-8")


def test_cli_prints_to_stdout(healthy_root: Path, capsys) -> None:
    rc = main(["--root", str(healthy_root), "--format", "text"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "VERDICT:" in captured.out
