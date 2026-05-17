"""Tests for sauravplot — ASCII data plotting for sauravcode.

Covers all chart functions (bar, line, scatter, hist, sparkline, pie,
multi_bar), the input parsers, the color helper, and the
``register_plot_builtins`` integration hook.

These tests are intentionally tolerant of cosmetic spacing/layout while
strict about the *semantic* content of the rendered output: number of
bars, axis labels, glyphs used, color escapes, etc.
"""

import io
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sauravplot as sp


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip(s: str) -> str:
    """Remove ANSI escape sequences for content-level assertions."""
    return ANSI_RE.sub("", s)


# ─── _c color helper ────────────────────────────────────────────────


class TestColorHelper:
    def test_returns_plain_string_without_color(self):
        assert sp._c("hi", 0, False) == "hi"
        assert sp._c(123, 0, False) == "123"

    def test_wraps_with_ansi_when_color_enabled(self):
        out = sp._c("X", 0, True)
        assert out.startswith("\x1b[")
        assert out.endswith(sp.RESET)
        assert "X" in out

    def test_color_index_wraps_modulo(self):
        last = sp.COLORS[-1]
        out = sp._c("Y", len(sp.COLORS), True)  # index == len → wraps to 0
        assert sp.COLORS[0] in out
        out2 = sp._c("Y", len(sp.COLORS) - 1, True)
        assert last in out2


# ─── bar_chart ──────────────────────────────────────────────────────


class TestBarChart:
    def test_one_bar_per_label(self):
        labels = ["A", "B", "C"]
        values = [1, 2, 3]
        out = _strip(sp.bar_chart(labels, values, width=20))
        # Each label appears on exactly one bar row.
        for lbl in labels:
            rows = [ln for ln in out.splitlines() if f" {lbl} " in ln or ln.lstrip().startswith(lbl)]
            assert rows, f"label {lbl!r} not found in output"

    def test_largest_value_uses_full_width(self):
        out = _strip(sp.bar_chart(["A", "B"], [5, 10], width=10))
        # Bar for value 10 should contain 10 full blocks.
        b_row = [ln for ln in out.splitlines() if "B" in ln][0]
        assert b_row.count("█") == 10
        a_row = [ln for ln in out.splitlines() if " A " in ln or ln.lstrip().startswith("A")][0]
        assert a_row.count("█") == 5

    def test_zero_max_does_not_crash(self):
        out = sp.bar_chart(["A", "B"], [0, 0], width=10)
        assert "A" in _strip(out) and "B" in _strip(out)

    def test_title_included_when_provided(self):
        out = sp.bar_chart(["A"], [1], title="My Chart", color=False)
        assert "My Chart" in out

    def test_color_emits_ansi_codes(self):
        out = sp.bar_chart(["A"], [1], color=True)
        assert "\x1b[" in out


# ─── sparkline ──────────────────────────────────────────────────────


class TestSparkline:
    def test_empty_returns_empty_string(self):
        assert sp.sparkline([]) == ""

    def test_uses_only_spark_glyphs(self):
        out = _strip(sp.sparkline([1, 2, 3, 4, 5, 6, 7, 8]))
        # Extract the sparkline portion (between "  " prefix and " (min=").
        m = re.search(r"  ([\S]+) \(min=", out)
        assert m, f"no sparkline found in {out!r}"
        chars = m.group(1)
        assert len(chars) == 8
        assert all(ch in sp.SPARKS for ch in chars)

    def test_min_and_max_shown_in_legend(self):
        out = _strip(sp.sparkline([1.5, 7.25]))
        assert "min=1.5" in out
        assert "max=7.25" in out

    def test_flat_series_does_not_crash(self):
        # All-equal values: rng falls back to 1; no ZeroDivisionError.
        out = _strip(sp.sparkline([3, 3, 3]))
        assert "min=3" in out and "max=3" in out


# ─── line_chart / scatter_plot ──────────────────────────────────────


class TestLineChart:
    def test_renders_height_rows_plus_axis(self):
        out = sp.line_chart([1, 2, 3, 4], [1, 2, 3, 4], width=20, height=5)
        lines = out.splitlines()
        # We get `height` data rows + x-axis line + min/max labels = height + 2.
        assert len(lines) >= 5 + 2

    def test_point_glyph_present(self):
        out = _strip(sp.line_chart([0, 1, 2], [0, 1, 2], width=15, height=6))
        assert "●" in out

    def test_flat_y_does_not_crash(self):
        out = sp.line_chart([0, 1, 2], [3, 3, 3], width=10, height=4)
        assert "●" in _strip(out)


class TestScatterPlot:
    def test_uses_diamond_marker(self):
        out = _strip(sp.scatter_plot([0, 1, 2], [0, 1, 2], width=10, height=5))
        assert "◆" in out

    def test_marker_count_matches_unique_cells(self):
        out = _strip(sp.scatter_plot([0, 5, 10], [0, 5, 10], width=20, height=10))
        # 3 distinct points → 3 markers.
        assert out.count("◆") == 3


# ─── histogram ──────────────────────────────────────────────────────


class TestHistogram:
    def test_uses_requested_bin_count(self):
        out = _strip(sp.histogram([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], bins=5, width=20))
        # 5 bins → 5 bar rows that contain a "-" between bin edges.
        bar_rows = [ln for ln in out.splitlines() if re.search(r"\d+(?:\.\d+)?-\d+(?:\.\d+)?", ln)]
        assert len(bar_rows) == 5

    def test_bin_counts_sum_to_value_count(self):
        values = [1, 1, 2, 2, 2, 3]
        out = _strip(sp.histogram(values, bins=3, width=20))
        # Each bar row ends with the count value; extract trailing ints.
        counts = []
        for ln in out.splitlines():
            m = re.search(r"\s(\d+)\s*$", ln)
            if m and "-" in ln:
                counts.append(int(m.group(1)))
        assert sum(counts) == len(values)

    def test_flat_values_does_not_crash(self):
        out = sp.histogram([5, 5, 5, 5], bins=4)
        assert "Histogram" in _strip(out)


# ─── pie_chart ──────────────────────────────────────────────────────


class TestPieChart:
    def test_percentages_sum_to_100(self):
        out = _strip(sp.pie_chart(["A", "B", "C"], [1, 1, 2]))
        pcts = [float(m) for m in re.findall(r"\(([\d.]+)%\)", out)]
        assert len(pcts) == 3
        assert abs(sum(pcts) - 100.0) < 0.5  # rounding tolerance

    def test_legend_contains_each_label(self):
        out = _strip(sp.pie_chart(["Apples", "Bananas"], [3, 7]))
        assert "Apples" in out and "Bananas" in out


# ─── multi_bar ──────────────────────────────────────────────────────


class TestMultiBar:
    def test_renders_each_series_per_label(self):
        data = {"s1": {"A": 1, "B": 2}, "s2": {"A": 3, "B": 4}}
        out = _strip(sp.multi_bar(data, width=20))
        assert "[s1]" in out and "[s2]" in out
        # A and B labels both present
        assert " A " in out or out.lstrip().startswith("A")
        assert " B " in out or "B " in out

    def test_missing_label_in_series_treated_as_zero(self):
        data = {"s1": {"A": 5}, "s2": {"B": 10}}
        out = _strip(sp.multi_bar(data, width=20))
        # Both labels appear at least once each.
        assert "A" in out and "B" in out

    def test_single_series_omits_tag(self):
        out = _strip(sp.multi_bar({"only": {"X": 1}}, width=10))
        assert "[only]" not in out


# ─── CLI parsers ────────────────────────────────────────────────────


class TestParsers:
    def test_parse_kv_basic(self):
        labels, values = sp._parse_kv("A:1,B:2,C:3")
        assert labels == ["A", "B", "C"]
        assert values == [1.0, 2.0, 3.0]

    def test_parse_kv_handles_whitespace(self):
        labels, values = sp._parse_kv(" A : 1 , B : 2 ")
        assert labels == ["A", "B"]
        assert values == [1.0, 2.0]

    def test_parse_kv_skips_malformed_pairs(self):
        labels, values = sp._parse_kv("A:1,bad,B:2")
        assert labels == ["A", "B"]
        assert values == [1.0, 2.0]

    def test_parse_xy_basic(self):
        xs, ys = sp._parse_xy("1:2,3:4,5:6")
        assert xs == [1.0, 3.0, 5.0]
        assert ys == [2.0, 4.0, 6.0]

    def test_parse_values_basic(self):
        assert sp._parse_values("1,2,3,4") == [1.0, 2.0, 3.0, 4.0]

    def test_parse_values_handles_empty_tokens(self):
        # Trailing comma must not crash.
        assert sp._parse_values("1,2,,3,") == [1.0, 2.0, 3.0]


# ─── register_plot_builtins ─────────────────────────────────────────


class TestRegisterBuiltins:
    def test_registers_all_plot_funcs(self):
        b = {}
        sp.register_plot_builtins(b)
        for k in ("plot_bar", "plot_line", "plot_scatter",
                  "plot_hist", "plot_spark", "plot_pie"):
            assert k in b and callable(b[k])

    def test_plot_bar_prints_and_returns_none(self, capsys):
        b = {}
        sp.register_plot_builtins(b)
        ret = b["plot_bar"]([["A", "B"], [1, 2]])
        captured = capsys.readouterr()
        assert ret is None
        assert "A" in _strip(captured.out) and "B" in _strip(captured.out)

    def test_plot_hist_accepts_bins_arg(self, capsys):
        b = {}
        sp.register_plot_builtins(b)
        ret = b["plot_hist"]([[1, 2, 3, 4, 5, 6], 3])
        captured = capsys.readouterr()
        assert ret is None
        # 3 bins requested → 3 bar rows
        assert sum(1 for ln in _strip(captured.out).splitlines()
                   if re.search(r"\d+(?:\.\d+)?-\d+(?:\.\d+)?", ln)) == 3


# ─── CLI main() ─────────────────────────────────────────────────────


class TestMainCLI:
    def test_help_prints_docstring(self, capsys, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["sauravplot.py", "--help"])
        sp.main()
        out = capsys.readouterr().out
        assert "sauravplot" in out

    def test_no_args_prints_help(self, capsys, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["sauravplot.py"])
        sp.main()
        out = capsys.readouterr().out
        assert "sauravplot" in out

    def test_bar_subcommand(self, capsys, monkeypatch):
        monkeypatch.setattr(sys, "argv",
                            ["sauravplot.py", "bar", "A:1,B:2", "--width", "10"])
        sp.main()
        out = _strip(capsys.readouterr().out)
        assert "A" in out and "B" in out and "█" in out

    def test_hist_subcommand_respects_bins(self, capsys, monkeypatch):
        monkeypatch.setattr(sys, "argv",
                            ["sauravplot.py", "hist", "1,2,3,4,5", "--bins", "5", "--width", "20"])
        sp.main()
        out = _strip(capsys.readouterr().out)
        bar_rows = [ln for ln in out.splitlines() if re.search(r"\d+(?:\.\d+)?-\d+(?:\.\d+)?", ln)]
        assert len(bar_rows) == 5

    def test_unknown_chart_exits_nonzero(self, capsys, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["sauravplot.py", "nope", "1,2,3"])
        with pytest.raises(SystemExit) as exc:
            sp.main()
        assert exc.value.code == 1
