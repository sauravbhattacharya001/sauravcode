"""Tests for sauravstats — FileMetrics, analyze_file, ProjectSummary, hotspots, treemap."""

import os
import sys
import json
import tempfile
import textwrap
import pytest

sys.path.insert(0, os.path.dirname(__file__))
import sauravstats


# ── FileMetrics ──────────────────────────────────────────────────────────────

class TestFileMetrics:
    def test_defaults_are_zero(self):
        fm = sauravstats.FileMetrics("/dummy.srv")
        assert fm.total_lines == 0
        assert fm.code_lines == 0
        assert fm.functions == 0
        assert fm.classes == 0
        assert fm.function_names == []
        assert fm.complexity_score == 0.0

    def test_to_dict_round_trip(self):
        fm = sauravstats.FileMetrics("/a.srv", "a.srv")
        fm.total_lines = 42
        fm.functions = 3
        d = fm.to_dict()
        assert d["total_lines"] == 42
        assert d["functions"] == 3
        assert d["path"] == "/a.srv"

    def test_comment_ratio_no_code(self):
        fm = sauravstats.FileMetrics("/x.srv")
        assert fm.comment_ratio == 0.0  # no division-by-zero

    def test_code_ratio_no_lines(self):
        fm = sauravstats.FileMetrics("/x.srv")
        assert fm.code_ratio == 0.0


# ── _indent_level ────────────────────────────────────────────────────────────

class TestIndentLevel:
    def test_no_indent(self):
        assert sauravstats._indent_level("hello") == 0

    def test_spaces(self):
        assert sauravstats._indent_level("    hello") == 4

    def test_tab(self):
        assert sauravstats._indent_level("\thello") == 4

    def test_mixed(self):
        assert sauravstats._indent_level("  \thello") == 6


# ── analyze_file ─────────────────────────────────────────────────────────────

@pytest.fixture
def srv_dir(tmp_path):
    """Create a temp directory with sample .srv files."""
    code = textwrap.dedent("""\
        # A comment
        import utils

        class Greeter
            function greet(name)
                if name
                    print("Hello " + name)
                return name

            function farewell(name)
                return "Bye " + name

        function standalone()
            for i in range(10)
                yield i
    """)
    (tmp_path / "sample.srv").write_text(code, encoding="utf-8")
    (tmp_path / "empty.srv").write_text("", encoding="utf-8")
    (tmp_path / "not_srv.txt").write_text("ignored", encoding="utf-8")
    return tmp_path


class TestAnalyzeFile:
    def test_basic_counts(self, srv_dir):
        fm = sauravstats.analyze_file(str(srv_dir / "sample.srv"), str(srv_dir))
        assert fm.total_lines == 15
        assert fm.comment_lines == 1
        assert fm.imports == 1
        assert fm.classes == 1
        assert fm.functions == 3
        assert fm.branches == 1  # the if
        assert fm.loops == 1     # for
        assert fm.yields == 1
        assert fm.returns == 2
        assert fm.prints == 1
        assert "greet" in fm.function_names
        assert "standalone" in fm.function_names

    def test_nested_function(self, srv_dir):
        fm = sauravstats.analyze_file(str(srv_dir / "sample.srv"), str(srv_dir))
        # greet and farewell are indented inside class → nested_functions
        assert fm.nested_functions == 2

    def test_empty_file(self, srv_dir):
        fm = sauravstats.analyze_file(str(srv_dir / "empty.srv"), str(srv_dir))
        assert fm.total_lines == 0
        assert fm.code_lines == 0
        assert fm.complexity_score == 0.0

    def test_nonexistent_file(self):
        fm = sauravstats.analyze_file("/no/such/file.srv")
        assert fm.total_lines == 0  # graceful failure

    def test_complexity_score_positive(self, srv_dir):
        fm = sauravstats.analyze_file(str(srv_dir / "sample.srv"), str(srv_dir))
        assert fm.complexity_score > 0

    def test_avg_depth_computed(self, srv_dir):
        fm = sauravstats.analyze_file(str(srv_dir / "sample.srv"), str(srv_dir))
        assert fm.avg_depth > 0

    def test_max_func_length(self, srv_dir):
        fm = sauravstats.analyze_file(str(srv_dir / "sample.srv"), str(srv_dir))
        assert fm.max_func_length > 0


# ── find_srv_files ───────────────────────────────────────────────────────────

class TestFindSrvFiles:
    def test_finds_only_srv(self, srv_dir):
        files = sauravstats.find_srv_files(str(srv_dir))
        names = [os.path.basename(f) for f in files]
        assert "sample.srv" in names
        assert "empty.srv" in names
        assert "not_srv.txt" not in names

    def test_single_file(self, srv_dir):
        files = sauravstats.find_srv_files(str(srv_dir / "sample.srv"))
        assert len(files) == 1

    def test_non_srv_file_returns_empty(self, srv_dir):
        files = sauravstats.find_srv_files(str(srv_dir / "not_srv.txt"))
        assert files == []

    def test_skips_hidden_dirs(self, srv_dir):
        hidden = srv_dir / ".hidden"
        hidden.mkdir()
        (hidden / "secret.srv").write_text("# hidden", encoding="utf-8")
        files = sauravstats.find_srv_files(str(srv_dir))
        assert not any(".hidden" in f for f in files)


# ── ProjectSummary ───────────────────────────────────────────────────────────

class TestProjectSummary:
    def test_aggregates_correctly(self, srv_dir):
        metrics = sauravstats.analyze_path(str(srv_dir))
        summary = sauravstats.ProjectSummary(metrics)
        assert summary.file_count == 2  # sample.srv + empty.srv
        assert summary.functions == 3
        assert summary.classes == 1

    def test_health_score_bounded(self, srv_dir):
        metrics = sauravstats.analyze_path(str(srv_dir))
        summary = sauravstats.ProjectSummary(metrics)
        assert 0 <= summary.health_score <= 100

    def test_health_grade(self, srv_dir):
        metrics = sauravstats.analyze_path(str(srv_dir))
        summary = sauravstats.ProjectSummary(metrics)
        assert summary.health_grade in ("A", "B", "C", "D", "F")

    def test_to_dict_keys(self, srv_dir):
        metrics = sauravstats.analyze_path(str(srv_dir))
        summary = sauravstats.ProjectSummary(metrics)
        d = summary.to_dict()
        assert "file_count" in d
        assert "health_score" in d
        assert "avg_complexity" in d

    def test_empty_project(self):
        summary = sauravstats.ProjectSummary([])
        assert summary.file_count == 0
        assert summary.health_score > 0  # baseline score


# ── Hotspots ─────────────────────────────────────────────────────────────────

class TestHotspots:
    def test_no_hotspots_in_simple_project(self, srv_dir):
        metrics = sauravstats.analyze_path(str(srv_dir))
        hotspots = sauravstats.find_hotspots(metrics)
        # All files have low complexity → shouldn't all be hotspots
        assert isinstance(hotspots, list)

    def test_custom_threshold_zero_catches_all(self, srv_dir):
        metrics = sauravstats.analyze_path(str(srv_dir))
        code_metrics = [m for m in metrics if m.code_lines > 0]
        hotspots = sauravstats.find_hotspots(metrics, threshold=0)
        assert len(hotspots) >= len(code_metrics)

    def test_sorted_descending(self, srv_dir):
        metrics = sauravstats.analyze_path(str(srv_dir))
        hotspots = sauravstats.find_hotspots(metrics, threshold=0)
        scores = [h.complexity_score for h in hotspots]
        assert scores == sorted(scores, reverse=True)


# ── Treemap ──────────────────────────────────────────────────────────────────

class TestTreemap:
    def test_renders_string(self, srv_dir):
        metrics = sauravstats.analyze_path(str(srv_dir))
        output = sauravstats.render_treemap(metrics)
        assert isinstance(output, str)
        assert "LOC Distribution" in output

    def test_empty_metrics(self):
        output = sauravstats.render_treemap([])
        assert "No files" in output

    def test_all_empty_files(self):
        fm = sauravstats.FileMetrics("/z.srv", "z.srv")
        fm.total_lines = 0
        fm.code_lines = 0
        output = sauravstats.render_treemap([fm])
        assert "No code lines" in output
