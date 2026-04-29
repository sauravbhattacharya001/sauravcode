"""Tests for sauravdebt — Autonomous Technical Debt Tracker."""

import sys
import os
import json
import tempfile
import shutil
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sauravdebt as sd


# ── Helpers ───────────────────────────────────────────────────────────

@pytest.fixture
def tmpdir():
    d = tempfile.mkdtemp(prefix="sauravdebt_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _write_srv(directory, name, content):
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


# ── D001: TODO/FIXME/HACK Markers ────────────────────────────────────

class TestD001TodoMarkers:
    def test_todo_detected(self, tmpdir):
        path = _write_srv(tmpdir, "a.srv", "# TODO: fix this\nx = 1\n")
        items = sd.scan_file(path)
        assert any(i.id == "D001" for i in items)

    def test_fixme_is_high(self, tmpdir):
        path = _write_srv(tmpdir, "a.srv", "# FIXME: broken\n")
        items = sd.scan_file(path)
        fixmes = [i for i in items if i.id == "D001"]
        assert fixmes and fixmes[0].severity == "high"

    def test_hack_detected(self, tmpdir):
        path = _write_srv(tmpdir, "a.srv", "# HACK: workaround\n")
        items = sd.scan_file(path)
        assert any(i.id == "D001" for i in items)

    def test_no_markers_clean(self, tmpdir):
        path = _write_srv(tmpdir, "a.srv", "# This is fine\nx = 1\n")
        items = sd.scan_file(path)
        assert not any(i.id == "D001" for i in items)

    def test_case_insensitive(self, tmpdir):
        path = _write_srv(tmpdir, "a.srv", "# todo: lowercase\n")
        items = sd.scan_file(path)
        assert any(i.id == "D001" for i in items)


# ── D002: Duplicated Code Blocks ─────────────────────────────────────

class TestD002DuplicatedBlocks:
    def test_similar_funcs_detected(self, tmpdir):
        code = """function foo a b
    x = a + b
    y = x * 2
    z = y - 1
    return z

function bar a b
    x = a + b
    y = x * 2
    z = y - 1
    return z
"""
        path = _write_srv(tmpdir, "a.srv", code)
        items = sd.scan_file(path)
        assert any(i.id == "D002" for i in items)

    def test_different_funcs_no_flag(self, tmpdir):
        code = """function foo a
    return a + 1

function bar a b c
    print a
    print b
    print c
    return a * b * c
"""
        path = _write_srv(tmpdir, "a.srv", code)
        items = sd.scan_file(path)
        assert not any(i.id == "D002" for i in items)


# ── D003: Magic Numbers ──────────────────────────────────────────────

class TestD003MagicNumbers:
    def test_repeated_magic_number(self, tmpdir):
        code = "x = 42\ny = 42\nz = 42\n"
        path = _write_srv(tmpdir, "a.srv", code)
        items = sd.scan_file(path)
        assert any(i.id == "D003" for i in items)

    def test_trivial_numbers_ignored(self, tmpdir):
        code = "x = 0\ny = 1\nz = 0\n"
        path = _write_srv(tmpdir, "a.srv", code)
        items = sd.scan_file(path)
        assert not any(i.id == "D003" for i in items)


# ── D004: Missing Error Handling ─────────────────────────────────────

class TestD004MissingErrorHandling:
    def test_io_without_try(self, tmpdir):
        code = """function load_data path
    data = open(path)
    return data
"""
        path = _write_srv(tmpdir, "a.srv", code)
        items = sd.scan_file(path)
        assert any(i.id == "D004" for i in items)

    def test_io_with_try_clean(self, tmpdir):
        code = """function load_data path
    try
        data = open(path)
    catch e
        print e
    return data
"""
        path = _write_srv(tmpdir, "a.srv", code)
        items = sd.scan_file(path)
        assert not any(i.id == "D004" for i in items)


# ── D005: Dead Code ──────────────────────────────────────────────────

class TestD005DeadCode:
    def test_unused_function(self, tmpdir):
        code = """function helper
    return 1

function main
    print "hello"
"""
        path = _write_srv(tmpdir, "a.srv", code)
        items = sd.scan_file(path)
        dead = [i for i in items if i.id == "D005"]
        assert any("helper" in i.description for i in dead)

    def test_called_function_not_dead(self, tmpdir):
        code = """function helper
    return 1

function main
    x = helper()
    print x
"""
        path = _write_srv(tmpdir, "a.srv", code)
        items = sd.scan_file(path)
        dead = [i for i in items if i.id == "D005"]
        assert not any("helper" in i.description for i in dead)


# ── D006: Long Functions ─────────────────────────────────────────────

class TestD006LongFunctions:
    def test_long_function_detected(self, tmpdir):
        body = "\n".join(f"    print {i}" for i in range(50))
        code = f"function big_func\n{body}\n"
        path = _write_srv(tmpdir, "a.srv", code)
        items = sd.scan_file(path)
        assert any(i.id == "D006" for i in items)

    def test_short_function_clean(self, tmpdir):
        code = "function small a\n    return a + 1\n"
        path = _write_srv(tmpdir, "a.srv", code)
        items = sd.scan_file(path)
        assert not any(i.id == "D006" for i in items)


# ── D007: Deep Nesting ───────────────────────────────────────────────

class TestD007DeepNesting:
    def test_deep_nesting_detected(self, tmpdir):
        code = "if a\n    if b\n        if c\n            if d\n                if e\n                    print \"deep\"\n"
        path = _write_srv(tmpdir, "a.srv", code)
        items = sd.scan_file(path)
        assert any(i.id == "D007" for i in items)

    def test_shallow_nesting_clean(self, tmpdir):
        code = "if a\n    print \"shallow\"\n"
        path = _write_srv(tmpdir, "a.srv", code)
        items = sd.scan_file(path)
        assert not any(i.id == "D007" for i in items)


# ── D008: Hardcoded Strings ──────────────────────────────────────────

class TestD008HardcodedStrings:
    def test_repeated_strings(self, tmpdir):
        code = 'x = "important_path"\ny = "important_path"\nz = "important_path"\n'
        path = _write_srv(tmpdir, "a.srv", code)
        items = sd.scan_file(path)
        assert any(i.id == "D008" for i in items)

    def test_unique_strings_clean(self, tmpdir):
        code = 'x = "alpha"\ny = "beta"\nz = "gamma"\n'
        path = _write_srv(tmpdir, "a.srv", code)
        items = sd.scan_file(path)
        assert not any(i.id == "D008" for i in items)


# ── D009: Missing Documentation ──────────────────────────────────────

class TestD009MissingDocs:
    def test_undocumented_func(self, tmpdir):
        code = "function foo x\n    return x\n"
        path = _write_srv(tmpdir, "a.srv", code)
        items = sd.scan_file(path)
        assert any(i.id == "D009" for i in items)

    def test_documented_func_clean(self, tmpdir):
        code = "# Does something useful\nfunction foo x\n    return x\n"
        path = _write_srv(tmpdir, "a.srv", code)
        items = sd.scan_file(path)
        assert not any(i.id == "D009" for i in items)

    def test_inline_doc_clean(self, tmpdir):
        code = "function foo x\n    # Computes stuff\n    return x\n"
        path = _write_srv(tmpdir, "a.srv", code)
        items = sd.scan_file(path)
        assert not any(i.id == "D009" for i in items)


# ── D010: Complex Conditionals ───────────────────────────────────────

class TestD010ComplexConditionals:
    def test_many_elif_branches(self, tmpdir):
        code = "if x == 1\n    print 1\nelif x == 2\n    print 2\nelif x == 3\n    print 3\nelif x == 4\n    print 4\nelif x == 5\n    print 5\n"
        path = _write_srv(tmpdir, "a.srv", code)
        items = sd.scan_file(path)
        assert any(i.id == "D010" for i in items)

    def test_simple_if_clean(self, tmpdir):
        code = "if x == 1\n    print 1\nelse\n    print 2\n"
        path = _write_srv(tmpdir, "a.srv", code)
        items = sd.scan_file(path)
        assert not any(i.id == "D010" for i in items)


# ── D011: Inconsistent Style ─────────────────────────────────────────

class TestD011InconsistentStyle:
    def test_mixed_naming(self, tmpdir):
        code = "function my_func a\n    return a\n\nfunction myFunc b\n    return b\n"
        path = _write_srv(tmpdir, "a.srv", code)
        items = sd.scan_file(path)
        assert any(i.id == "D011" for i in items)

    def test_consistent_naming_clean(self, tmpdir):
        code = "function my_func a\n    return a\n\nfunction other_func b\n    return b\n"
        path = _write_srv(tmpdir, "a.srv", code)
        items = sd.scan_file(path)
        assert not any(i.id == "D011" for i in items)


# ── D012: Coupling Hotspots ──────────────────────────────────────────

class TestD012CouplingHotspots:
    def test_high_fanout(self, tmpdir):
        callees = "\n".join(f"function f{i}\n    return {i}\n" for i in range(10))
        calls = "\n".join(f"    f{i}()" for i in range(10))
        code = f"{callees}\nfunction hub\n{calls}\n    return 0\n"
        path = _write_srv(tmpdir, "a.srv", code)
        items = sd.scan_file(path)
        coupling = [i for i in items if i.id == "D012"]
        assert any("hub" in i.description for i in coupling)


# ── ScanResult ────────────────────────────────────────────────────────

class TestScanResult:
    def test_debt_score_clean(self):
        r = sd.ScanResult(items=[], total_lines=100)
        assert r.debt_score == 100

    def test_debt_score_with_items(self):
        items = [sd.DebtItem("D001", "test", "f.srv", 1, "high", 2, 4, "d", "s")]
        r = sd.ScanResult(items=items, total_lines=100)
        assert 0 <= r.debt_score <= 100

    def test_empty_file_score(self):
        r = sd.ScanResult(items=[], total_lines=0)
        assert r.debt_score == 100


# ── Payoff Plan ───────────────────────────────────────────────────────

class TestPayoffPlan:
    def test_plan_groups_by_effort(self):
        items = [
            sd.DebtItem("D001", "n", "f", 1, "low", 1, 3, "d", "s"),
            sd.DebtItem("D006", "n", "f", 1, "high", 4, 6, "d", "s"),
            sd.DebtItem("D007", "n", "f", 1, "medium", 3, 5, "d", "s"),
        ]
        plan = sd.generate_payoff_plan(items)
        assert len(plan["quick_wins"]) == 1
        assert len(plan["medium_effort"]) == 1
        assert len(plan["deep_refactors"]) == 1

    def test_plan_sorted_by_roi(self):
        items = [
            sd.DebtItem("D001", "n", "f", 1, "low", 1, 10, "d", "s"),
            sd.DebtItem("D006", "n", "f", 1, "high", 1, 2, "d", "s"),
        ]
        plan = sd.generate_payoff_plan(items)
        assert plan["quick_wins"][0].roi_score >= plan["quick_wins"][1].roi_score


# ── ROI Score ─────────────────────────────────────────────────────────

class TestROIScore:
    def test_roi_calculation(self):
        item = sd.DebtItem("D001", "n", "f", 1, "low", 2, 8, "d", "s")
        assert item.roi_score == 4.0

    def test_roi_zero_effort(self):
        item = sd.DebtItem("D001", "n", "f", 1, "low", 0, 5, "d", "s")
        assert item.roi_score == 5.0  # effort clamped to 1


# ── Fingerprint ───────────────────────────────────────────────────────

class TestFingerprint:
    def test_deterministic(self):
        item = sd.DebtItem("D001", "n", "f.srv", 10, "low", 1, 3, "test", "s")
        assert item.fingerprint == item.fingerprint

    def test_different_items_different_fingerprints(self):
        a = sd.DebtItem("D001", "n", "f.srv", 10, "low", 1, 3, "test a", "s")
        b = sd.DebtItem("D001", "n", "f.srv", 20, "low", 1, 3, "test b", "s")
        assert a.fingerprint != b.fingerprint


# ── Timeline / History ────────────────────────────────────────────────

class TestTimeline:
    def test_record_snapshot(self, tmpdir):
        hf = os.path.join(tmpdir, "h.json")
        result = sd.ScanResult(items=[], total_lines=10)
        diff = sd.record_snapshot(result, history_file=hf)
        assert os.path.isfile(hf)
        assert "new" in diff

    def test_new_debt_detected(self, tmpdir):
        hf = os.path.join(tmpdir, "h.json")
        item1 = sd.DebtItem("D001", "n", "f.srv", 1, "low", 1, 3, "first", "s")
        item2 = sd.DebtItem("D002", "n", "f.srv", 5, "high", 3, 7, "second", "s")

        r1 = sd.ScanResult(items=[item1], total_lines=10)
        sd.record_snapshot(r1, history_file=hf)

        r2 = sd.ScanResult(items=[item1, item2], total_lines=20)
        diff = sd.record_snapshot(r2, history_file=hf)
        assert len(diff["new"]) == 1

    def test_resolved_debt_detected(self, tmpdir):
        hf = os.path.join(tmpdir, "h.json")
        item1 = sd.DebtItem("D001", "n", "f.srv", 1, "low", 1, 3, "first", "s")
        item2 = sd.DebtItem("D002", "n", "f.srv", 5, "high", 3, 7, "second", "s")

        r1 = sd.ScanResult(items=[item1, item2], total_lines=20)
        sd.record_snapshot(r1, history_file=hf)

        r2 = sd.ScanResult(items=[item1], total_lines=10)
        diff = sd.record_snapshot(r2, history_file=hf)
        assert len(diff["resolved"]) == 1

    def test_reset_history(self, tmpdir):
        hf = os.path.join(tmpdir, "h.json")
        r = sd.ScanResult(items=[], total_lines=10)
        sd.record_snapshot(r, history_file=hf)
        assert os.path.isfile(hf)
        sd.reset_history(history_file=hf)
        assert not os.path.isfile(hf)


# ── HTML Generation ──────────────────────────────────────────────────

class TestHTMLGeneration:
    def test_html_generated(self, tmpdir):
        items = [sd.DebtItem("D001", "n", "f.srv", 1, "high", 2, 5, "desc", "sug")]
        result = sd.ScanResult(items=items, files_scanned=1, total_lines=50)
        out = os.path.join(tmpdir, "report.html")
        sd.generate_html(result, out, history_file=os.path.join(tmpdir, "h.json"))
        assert os.path.isfile(out)
        content = open(out, encoding="utf-8").read()
        assert "sauravdebt" in content
        assert "D001" in content

    def test_html_escape(self):
        assert sd._html_escape('<script>') == '&lt;script&gt;'


# ── JSON Output ──────────────────────────────────────────────────────

class TestJSONOutput:
    def test_json_structure(self):
        items = [sd.DebtItem("D001", "n", "f.srv", 1, "low", 1, 3, "d", "s")]
        result = sd.ScanResult(items=items, files_scanned=1, total_lines=10)
        data = sd.to_json(result)
        assert data["debt_score"] >= 0
        assert len(data["items"]) == 1
        assert data["items"][0]["roi_score"] > 0

    def test_json_serialisable(self):
        result = sd.ScanResult(items=[], files_scanned=0, total_lines=0)
        data = sd.to_json(result)
        json.dumps(data)  # Should not raise


# ── Project Scan ─────────────────────────────────────────────────────

class TestProjectScan:
    def test_scan_project(self, tmpdir):
        _write_srv(tmpdir, "a.srv", "# TODO: fix\nfunction foo\n    return 1\n")
        _write_srv(tmpdir, "b.srv", "x = 1\n")
        result = sd.scan_project([tmpdir])
        assert result.files_scanned == 2
        assert result.total_lines > 0

    def test_scan_empty_dir(self, tmpdir):
        result = sd.scan_project([tmpdir])
        assert result.files_scanned == 0
        assert result.debt_score == 100


# ── Edge Cases ────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_file(self, tmpdir):
        path = _write_srv(tmpdir, "empty.srv", "")
        items = sd.scan_file(path)
        assert items == []

    def test_comments_only(self, tmpdir):
        path = _write_srv(tmpdir, "comments.srv", "# Just a comment\n# Another one\n")
        items = sd.scan_file(path)
        # No functions, no code → minimal debt
        assert not any(i.id == "D006" for i in items)

    def test_nonexistent_file(self):
        items = sd.scan_file("/nonexistent/path.srv")
        assert items == []


# ── Demo file integration ────────────────────────────────────────────

class TestDemoFile:
    def test_demo_file_has_debt(self):
        demo_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "debt_demo.srv")
        if not os.path.isfile(demo_path):
            pytest.skip("debt_demo.srv not found")
        items = sd.scan_file(demo_path)
        assert len(items) >= 5  # Should catch many patterns
        ids_found = {i.id for i in items}
        # Should detect at least TODO, long func, deep nesting, and inconsistent style
        assert "D001" in ids_found
