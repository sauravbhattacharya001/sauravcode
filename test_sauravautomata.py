"""Tests for sauravautomata — Cellular Automata Simulator & Explorer.

Covers: sparkline, shannon_entropy, rule_to_table, step_1d, render_1d_row,
run_1d, classify_1d_rule, make_life_grid, step_life, render_life, grid_hash,
run_life, recommend_after_1d, recommend_after_life, _get_arg, _has_flag,
and PRESETS integrity.
"""

import math
import pytest
import random
from sauravautomata import (
    sparkline,
    shannon_entropy,
    rule_to_table,
    step_1d,
    render_1d_row,
    run_1d,
    classify_1d_rule,
    make_life_grid,
    step_life,
    render_life,
    grid_hash,
    run_life,
    recommend_after_1d,
    recommend_after_life,
    PRESETS,
    SPARK_CHARS,
    _get_arg,
    _has_flag,
)


# ── sparkline ────────────────────────────────────────────────────────

class TestSparkline:
    def test_empty(self):
        assert sparkline([]) == ""

    def test_constant(self):
        result = sparkline([5, 5, 5])
        assert len(result) == 3
        assert len(set(result)) == 1

    def test_ascending(self):
        result = sparkline([0, 1, 2, 3, 4, 5, 6, 7])
        assert result[0] == SPARK_CHARS[0]
        assert result[-1] == SPARK_CHARS[7]

    def test_two_values(self):
        result = sparkline([0, 100])
        assert result[0] == SPARK_CHARS[0]
        assert result[1] == SPARK_CHARS[7]

    def test_length_matches_input(self):
        assert len(sparkline([1, 2, 3, 4, 5])) == 5

    def test_single_value(self):
        result = sparkline([42])
        assert len(result) == 1


# ── shannon_entropy ──────────────────────────────────────────────────

class TestShannonEntropy:
    def test_empty(self):
        assert shannon_entropy([]) == 0.0

    def test_all_zeros(self):
        assert shannon_entropy([0, 0, 0, 0]) == 0.0

    def test_all_ones(self):
        assert shannon_entropy([1, 1, 1, 1]) == 0.0

    def test_equal_split(self):
        ent = shannon_entropy([0, 1])
        assert abs(ent - 1.0) < 1e-10

    def test_equal_split_larger(self):
        ent = shannon_entropy([0, 0, 1, 1])
        assert abs(ent - 1.0) < 1e-10

    def test_skewed(self):
        ent = shannon_entropy([0, 0, 0, 1])
        expected = -(0.75 * math.log2(0.75) + 0.25 * math.log2(0.25))
        assert abs(ent - expected) < 1e-10

    def test_entropy_range(self):
        for _ in range(10):
            cells = [random.choice([0, 1]) for _ in range(50)]
            ent = shannon_entropy(cells)
            assert 0.0 <= ent <= 1.0


# ── rule_to_table ────────────────────────────────────────────────────

class TestRuleToTable:
    def test_table_size(self):
        table = rule_to_table(30)
        assert len(table) == 8

    def test_all_neighborhoods(self):
        table = rule_to_table(110)
        for i in range(8):
            key = (i >> 2 & 1, i >> 1 & 1, i & 1)
            assert key in table
            assert table[key] in (0, 1)

    def test_rule_0(self):
        table = rule_to_table(0)
        assert all(v == 0 for v in table.values())

    def test_rule_255(self):
        table = rule_to_table(255)
        assert all(v == 1 for v in table.values())

    def test_rule_30_specific(self):
        table = rule_to_table(30)
        assert table[(0, 0, 0)] == 0
        assert table[(0, 0, 1)] == 1
        assert table[(0, 1, 0)] == 1
        assert table[(0, 1, 1)] == 1
        assert table[(1, 0, 0)] == 1
        assert table[(1, 0, 1)] == 0
        assert table[(1, 1, 0)] == 0
        assert table[(1, 1, 1)] == 0


# ── step_1d ──────────────────────────────────────────────────────────

class TestStep1D:
    def test_single_seed_rule_30(self):
        table = rule_to_table(30)
        cells = [0, 0, 1, 0, 0]
        result = step_1d(cells, table)
        assert len(result) == 5
        assert result[2] == 1

    def test_preserves_length(self):
        table = rule_to_table(110)
        cells = [0] * 20
        cells[10] = 1
        result = step_1d(cells, table)
        assert len(result) == 20

    def test_wrapping(self):
        table = rule_to_table(30)
        cells = [1, 0, 0, 0, 0]
        result = step_1d(cells, table)
        assert result[0] == table[(0, 1, 0)]

    def test_rule_0_kills_all(self):
        table = rule_to_table(0)
        cells = [1, 1, 1, 1, 1]
        result = step_1d(cells, table)
        assert all(c == 0 for c in result)

    def test_rule_255_fills_all(self):
        table = rule_to_table(255)
        cells = [0, 0, 0, 0, 0]
        result = step_1d(cells, table)
        assert all(c == 1 for c in result)

    def test_deterministic(self):
        table = rule_to_table(90)
        cells = [0, 0, 0, 1, 0, 0, 0]
        r1 = step_1d(cells, table)
        r2 = step_1d(cells, table)
        assert r1 == r2


# ── render_1d_row ────────────────────────────────────────────────────

class TestRender1DRow:
    def test_plain(self):
        row = render_1d_row([1, 0, 1], color=False)
        assert "█" in row
        assert " " in row
        assert len(row) == 3

    def test_all_dead(self):
        row = render_1d_row([0, 0, 0], color=False)
        assert row == "   "

    def test_all_alive(self):
        row = render_1d_row([1, 1, 1], color=False)
        assert row == "███"


# ── run_1d ───────────────────────────────────────────────────────────

class TestRun1D:
    def test_return_shape(self):
        lines, history, pops, ents = run_1d(30, width=20, generations=10)
        assert len(lines) == 10
        assert len(history) == 10
        assert len(pops) == 10
        assert len(ents) == 10

    def test_initial_population(self):
        _, _, pops, _ = run_1d(30, width=20, generations=5)
        assert pops[0] == 1

    def test_history_width(self):
        _, history, _, _ = run_1d(110, width=30, generations=5)
        assert all(len(row) == 30 for row in history)

    def test_entropy_range(self):
        _, _, _, ents = run_1d(30, width=40, generations=20)
        assert all(0.0 <= e <= 1.0 for e in ents)


# ── classify_1d_rule ─────────────────────────────────────────────────

class TestClassify1DRule:
    def test_rule_0_stable(self):
        cls, desc = classify_1d_rule(0, width=40, generations=60)
        assert cls == "I"

    def test_returns_valid_class(self):
        for rule in [30, 90, 110, 0, 128]:
            cls, desc = classify_1d_rule(rule, width=40, generations=60)
            assert cls in ("I", "II", "III", "IV")
            assert isinstance(desc, str)
            assert len(desc) > 0

    def test_rule_30_chaotic_or_complex(self):
        cls, _ = classify_1d_rule(30, width=60, generations=80)
        assert cls in ("III", "IV")

    def test_rule_110_complex(self):
        cls, _ = classify_1d_rule(110, width=60, generations=80)
        assert cls in ("III", "IV")


# ── Game of Life: make_life_grid ─────────────────────────────────────

class TestMakeLifeGrid:
    def test_dimensions(self):
        grid = make_life_grid(30, 20)
        assert len(grid) == 20
        assert all(len(row) == 30 for row in grid)

    def test_preset_glider(self):
        grid = make_life_grid(40, 20, preset="glider")
        total = sum(sum(row) for row in grid)
        assert total == 5

    def test_preset_blinker(self):
        grid = make_life_grid(40, 20, preset="blinker")
        total = sum(sum(row) for row in grid)
        assert total == 3

    def test_random_density_zero(self):
        random.seed(42)
        grid = make_life_grid(20, 20, density=0.0)
        total = sum(sum(row) for row in grid)
        assert total == 0

    def test_random_density_one(self):
        random.seed(42)
        grid = make_life_grid(20, 20, density=1.0)
        total = sum(sum(row) for row in grid)
        assert total == 400

    def test_unknown_preset_falls_through_to_random(self):
        random.seed(42)
        grid = make_life_grid(10, 10, preset="nonexistent")
        total = sum(sum(row) for row in grid)
        assert total > 0


# ── step_life ────────────────────────────────────────────────────────

class TestStepLife:
    def test_blinker_oscillates(self):
        grid = [[0]*5 for _ in range(5)]
        grid[2][1] = grid[2][2] = grid[2][3] = 1
        new, births, deaths = step_life(grid)
        assert new[1][2] == 1
        assert new[2][2] == 1
        assert new[3][2] == 1
        assert new[2][1] == 0
        assert new[2][3] == 0

    def test_block_stable(self):
        grid = [[0]*6 for _ in range(6)]
        grid[2][2] = grid[2][3] = grid[3][2] = grid[3][3] = 1
        new, births, deaths = step_life(grid)
        assert new[2][2] == 1 and new[2][3] == 1
        assert new[3][2] == 1 and new[3][3] == 1
        assert births == 0 and deaths == 0

    def test_lone_cell_dies(self):
        grid = [[0]*5 for _ in range(5)]
        grid[2][2] = 1
        new, births, deaths = step_life(grid)
        assert new[2][2] == 0
        assert deaths == 1

    def test_birth_and_death_counts(self):
        grid = [[0]*5 for _ in range(5)]
        grid[2][1] = grid[2][2] = grid[2][3] = 1
        _, births, deaths = step_life(grid)
        assert births > 0
        assert deaths > 0


# ── grid_hash ────────────────────────────────────────────────────────

class TestGridHash:
    def test_equal_grids_same_hash(self):
        g1 = [[0, 1], [1, 0]]
        g2 = [[0, 1], [1, 0]]
        assert grid_hash(g1) == grid_hash(g2)

    def test_different_grids_different_hash(self):
        g1 = [[0, 1], [1, 0]]
        g2 = [[1, 0], [0, 1]]
        assert grid_hash(g1) != grid_hash(g2)

    def test_hashable(self):
        g = [[0, 1], [1, 0]]
        h = grid_hash(g)
        s = {h}
        assert h in s


# ── render_life ──────────────────────────────────────────────────────

class TestRenderLife:
    def test_line_count(self):
        grid = [[0]*5 for _ in range(3)]
        lines = render_life(grid, color=False)
        assert len(lines) == 3

    def test_alive_cells_rendered(self):
        grid = [[1, 0], [0, 1]]
        lines = render_life(grid, color=False)
        assert "█" in lines[0]
        assert "·" in lines[0]


# ── run_life ─────────────────────────────────────────────────────────

class TestRunLife:
    def test_blinker_detects_oscillation(self):
        frames, pops, alerts, osc = run_life(
            width=10, height=10, generations=50, preset="blinker"
        )
        assert osc == 2
        assert any("Oscillation" in a for a in alerts)

    def test_populations_tracked(self):
        frames, pops, alerts, osc = run_life(
            width=10, height=10, generations=20, preset="glider"
        )
        assert len(pops) > 1
        assert all(isinstance(p, int) for p in pops)

    def test_empty_grid_extinct(self):
        frames, pops, alerts, osc = run_life(
            width=5, height=5, generations=10, density=0.0
        )
        assert pops[0] == 0


# ── PRESETS integrity ────────────────────────────────────────────────

class TestPresets:
    def test_all_presets_have_cells(self):
        for name, data in PRESETS.items():
            assert "cells" in data
            assert isinstance(data["cells"], list)
            assert "desc" in data

    def test_glider_five_cells(self):
        assert len(PRESETS["glider"]["cells"]) == 5

    def test_blinker_three_cells(self):
        assert len(PRESETS["blinker"]["cells"]) == 3

    def test_pulsar_nonempty(self):
        assert len(PRESETS["pulsar"]["cells"]) > 10

    def test_gun_nonempty(self):
        assert len(PRESETS["gun"]["cells"]) > 20

    def test_rpentomino_five_cells(self):
        assert len(PRESETS["rpentomino"]["cells"]) == 5

    def test_no_duplicate_cells_in_pulsar(self):
        cells = PRESETS["pulsar"]["cells"]
        assert len(cells) == len(set(cells))


# ── recommend_after_1d ───────────────────────────────────────────────

class TestRecommendAfter1D:
    def test_returns_list(self):
        recs = recommend_after_1d(30)
        assert isinstance(recs, list)
        assert len(recs) > 0

    def test_stable_rule_suggests_chaos(self):
        recs = recommend_after_1d(0)
        combined = " ".join(recs)
        assert "30" in combined or "110" in combined

    def test_neighbors_suggested(self):
        recs = recommend_after_1d(100)
        combined = " ".join(recs)
        assert "99" in combined or "101" in combined or "155" in combined


# ── recommend_after_life ─────────────────────────────────────────────

class TestRecommendAfterLife:
    def test_returns_list(self):
        recs = recommend_after_life("glider")
        assert isinstance(recs, list)
        assert len(recs) > 0

    def test_suggests_different_preset(self):
        recs = recommend_after_life("glider")
        assert any(p in " ".join(recs) for p in ["blinker", "pulsar", "rpentomino", "gun"])


# ── CLI helpers ──────────────────────────────────────────────────────

class TestCLIHelpers:
    def test_get_arg_found(self):
        assert _get_arg(["--width", "80"], "--width", 60, int) == 80

    def test_get_arg_default(self):
        assert _get_arg(["--height", "20"], "--width", 60, int) == 60

    def test_get_arg_at_end(self):
        assert _get_arg(["--width"], "--width", 60, int) == 60

    def test_has_flag_true(self):
        assert _has_flag(["--color", "rule", "30"], "--color") is True

    def test_has_flag_false(self):
        assert _has_flag(["rule", "30"], "--color") is False
