"""Tests for statistics & math utility built-in functions."""
import pytest
import subprocess
import sys
import os
import tempfile

INTERPRETER = os.path.join(os.path.dirname(__file__), '..', 'saurav.py')


def run_srv(code):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.srv', delete=False) as f:
        f.write(code)
        f.flush()
        result = subprocess.run(
            [sys.executable, INTERPRETER, f.name],
            capture_output=True, text=True, timeout=10
        )
    os.unlink(f.name)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def run_srv_error(code):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.srv', delete=False) as f:
        f.write(code)
        f.flush()
        result = subprocess.run(
            [sys.executable, INTERPRETER, f.name],
            capture_output=True, text=True, timeout=10
        )
    os.unlink(f.name)
    return result


class TestMean:
    def test_basic(self):
        assert float(run_srv('print mean [1, 2, 3, 4, 5]')) == 3.0

    def test_single(self):
        assert float(run_srv('print mean [42]')) == 42.0

    def test_floats(self):
        assert float(run_srv('print mean [1.5, 2.5, 3.5]')) == 2.5

    def test_negative(self):
        assert float(run_srv('print mean [-10, 10]')) == 0.0

    def test_empty_error(self):
        assert run_srv_error('print mean []').returncode != 0

    def test_non_list_error(self):
        assert run_srv_error('print mean 5').returncode != 0

    def test_with_variable(self):
        assert float(run_srv("nums = [10, 20, 30]\nprint mean nums\n")) == 20.0


class TestMedian:
    def test_odd(self):
        assert float(run_srv('print median [3, 1, 2]')) == 2.0

    def test_even(self):
        assert float(run_srv('print median [1, 2, 3, 4]')) == 2.5

    def test_single(self):
        assert float(run_srv('print median [7]')) == 7.0

    def test_sorted(self):
        assert float(run_srv('print median [1, 2, 3, 4, 5]')) == 3.0

    def test_reverse(self):
        assert float(run_srv('print median [5, 4, 3, 2, 1]')) == 3.0

    def test_dupes(self):
        assert float(run_srv('print median [1, 1, 1, 1]')) == 1.0

    def test_empty_error(self):
        assert run_srv_error('print median []').returncode != 0

    def test_two(self):
        assert float(run_srv('print median [3, 7]')) == 5.0


class TestStdev:
    def test_uniform(self):
        assert float(run_srv('print stdev [5, 5, 5, 5]')) == 0.0

    def test_known(self):
        assert abs(float(run_srv('print stdev [2, 4, 4, 4, 5, 5, 7, 9]')) - 2.0) < 0.001

    def test_two(self):
        assert float(run_srv('print stdev [0, 10]')) == 5.0

    def test_single(self):
        assert float(run_srv('print stdev [42]')) == 0.0

    def test_empty_error(self):
        assert run_srv_error('print stdev []').returncode != 0

    def test_small_spread(self):
        assert float(run_srv('print stdev [10, 10, 10, 11]')) < 1.0


class TestVariance:
    def test_uniform(self):
        assert float(run_srv('print variance [3, 3, 3]')) == 0.0

    def test_known(self):
        assert abs(float(run_srv('print variance [2, 4, 4, 4, 5, 5, 7, 9]')) - 4.0) < 0.001

    def test_single(self):
        assert float(run_srv('print variance [10]')) == 0.0

    def test_stdev_squared(self):
        code = "data = [1, 3, 5, 7, 9]\nv = variance data\ns = stdev data\nprint v\nprint s\n"
        out = run_srv(code)
        lines = out.split('\n')
        v, s = float(lines[0]), float(lines[1])
        assert abs(v - s * s) < 0.0001

    def test_positive(self):
        assert float(run_srv('print variance [1, 100]')) > 0


class TestMode:
    def test_basic(self):
        assert float(run_srv('print mode [1, 2, 2, 3]')) == 2.0

    def test_tie(self):
        assert float(run_srv('print mode [1, 2, 1, 2, 3]')) == 1.0

    def test_single(self):
        assert float(run_srv('print mode [99]')) == 99.0

    def test_all_same(self):
        assert float(run_srv('print mode [5, 5, 5]')) == 5.0

    def test_string(self):
        assert run_srv('print mode ["a", "b", "a", "c"]') == 'a'

    def test_empty_error(self):
        assert run_srv_error('print mode []').returncode != 0

    def test_triple_tie(self):
        assert float(run_srv('print mode [7, 8, 9]')) == 7.0


class TestPercentile:
    def test_50th(self):
        assert float(run_srv('print percentile [1, 2, 3, 4, 5] 50')) == 3.0

    def test_0th(self):
        assert float(run_srv('print percentile [10, 20, 30] 0')) == 10.0

    def test_100th(self):
        assert float(run_srv('print percentile [10, 20, 30] 100')) == 30.0

    def test_25th(self):
        assert float(run_srv('print percentile [1, 2, 3, 4] 25')) == 1.75

    def test_75th(self):
        assert float(run_srv('print percentile [1, 2, 3, 4] 75')) == 3.25

    def test_single(self):
        assert float(run_srv('print percentile [42] 50')) == 42.0

    def test_over_error(self):
        assert run_srv_error('print percentile [1, 2] 101').returncode != 0

    def test_neg_error(self):
        assert run_srv_error('print percentile [1, 2] (0 - 1)').returncode != 0

    def test_empty_error(self):
        assert run_srv_error('print percentile [] 50').returncode != 0

    def test_90th(self):
        assert float(run_srv('print percentile [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] 90')) == 9.1


class TestClamp:
    def test_within(self):
        assert float(run_srv('print clamp 5 0 10')) == 5.0

    def test_below(self):
        assert float(run_srv('print clamp (0 - 5) 0 10')) == 0.0

    def test_above(self):
        assert float(run_srv('print clamp 15 0 10')) == 10.0

    def test_at_min(self):
        assert float(run_srv('print clamp 0 0 10')) == 0.0

    def test_at_max(self):
        assert float(run_srv('print clamp 10 0 10')) == 10.0

    def test_neg_range(self):
        assert float(run_srv('print clamp 0 (0 - 10) (0 - 5)')) == -5.0

    def test_bad_range(self):
        assert run_srv_error('print clamp 5 10 0').returncode != 0

    def test_float(self):
        assert float(run_srv('print clamp 0.5 0 1')) == 0.5

    def test_exact(self):
        assert float(run_srv('print clamp 3.14 3.14 3.14')) == 3.14


class TestLerp:
    def test_zero(self):
        assert float(run_srv('print lerp 0 10 0')) == 0.0

    def test_one(self):
        assert float(run_srv('print lerp 0 10 1')) == 10.0

    def test_half(self):
        assert float(run_srv('print lerp 0 10 0.5')) == 5.0

    def test_quarter(self):
        assert float(run_srv('print lerp 100 200 0.25')) == 125.0

    def test_negative(self):
        assert float(run_srv('print lerp (0 - 10) 10 0.5')) == 0.0

    def test_extrapolate(self):
        assert float(run_srv('print lerp 0 10 2')) == 20.0

    def test_reverse(self):
        assert float(run_srv('print lerp 10 0 0.5')) == 5.0

    def test_same(self):
        assert float(run_srv('print lerp 7 7 0.5')) == 7.0


class TestRemap:
    def test_basic(self):
        assert float(run_srv('print remap 5 0 10 0 100')) == 50.0

    def test_min(self):
        assert float(run_srv('print remap 0 0 10 0 100')) == 0.0

    def test_max(self):
        assert float(run_srv('print remap 10 0 10 0 100')) == 100.0

    def test_inverse(self):
        assert float(run_srv('print remap 0 0 10 100 0')) == 100.0

    def test_neg_output(self):
        assert float(run_srv('print remap 5 0 10 (0 - 100) 100')) == 0.0

    def test_zero_width(self):
        assert run_srv_error('print remap 5 5 5 0 10').returncode != 0

    def test_quarter(self):
        assert float(run_srv('print remap 25 0 100 0 1')) == 0.25


class TestStatsComposition:
    def test_mean_manual(self):
        code = "data = [10, 20, 30]\nm = mean data\nmanual = (sum data) / (len data)\nprint m == manual\n"
        assert run_srv(code) == 'true'

    def test_remap_normalize(self):
        assert float(run_srv('print remap 30 10 50 0 1')) == 0.5

    def test_clamp_lerp(self):
        code = "t = clamp 1.5 0 1\nresult = lerp 0 100 t\nprint result\n"
        assert float(run_srv(code)) == 100.0

    def test_p50_median(self):
        assert float(run_srv('print percentile [1, 3, 5, 7, 9] 50')) == 5.0
        assert float(run_srv('print median [1, 3, 5, 7, 9]')) == 5.0

    def test_pipeline(self):
        code = "scores = [85, 90, 78, 92, 88]\nprint mean scores\nprint median scores\nprint mode scores\n"
        lines = run_srv(code).split('\n')
        assert float(lines[0]) == 86.6
        assert float(lines[1]) == 88.0
        assert float(lines[2]) == 85.0

    def test_var_pos(self):
        assert float(run_srv('print variance [1, 100]')) > 0

    def test_stdev_known(self):
        assert abs(float(run_srv('print stdev [10, 20, 30, 40, 50]')) - 14.142) < 0.01
