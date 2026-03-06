"""Tests for sauravbench.py -- benchmark runner for sauravcode programs."""

import json
import math
import os
import sys
import tempfile
import unittest

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)

import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("sauravbench", os.path.join(_root, "sauravbench.py"))
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

BenchStats = _mod.BenchStats
BenchmarkResult = _mod.BenchmarkResult
benchmark_file = _mod.benchmark_file
compare_to_baseline = _mod.compare_to_baseline
format_text_report = _mod.format_text_report
format_csv = _mod.format_csv
parse_args = _mod.parse_args
_fmt_time = _mod._fmt_time
_fmt_mem = _mod._fmt_mem
_run_program = _mod._run_program
_resolve_saurav = _mod._resolve_saurav


class TestBenchStats(unittest.TestCase):

    def test_empty(self):
        s = BenchStats([])
        self.assertEqual(s.n, 0)
        self.assertEqual(s.mean, 0.0)
        self.assertEqual(s.median, 0.0)
        self.assertEqual(s.std, 0.0)

    def test_single_value(self):
        s = BenchStats([5.0])
        self.assertEqual(s.mean, 5.0)
        self.assertEqual(s.median, 5.0)
        self.assertEqual(s.std, 0.0)

    def test_mean(self):
        s = BenchStats([1, 2, 3, 4, 5])
        self.assertAlmostEqual(s.mean, 3.0)

    def test_median_odd(self):
        s = BenchStats([3, 1, 2])
        self.assertEqual(s.median, 2.0)

    def test_median_even(self):
        s = BenchStats([1, 2, 3, 4])
        self.assertEqual(s.median, 2.5)

    def test_std(self):
        s = BenchStats([2, 4, 4, 4, 5, 5, 7, 9])
        self.assertAlmostEqual(s.std, 2.14, places=1)

    def test_min_max(self):
        s = BenchStats([10, 3, 7, 1, 5])
        self.assertEqual(s.min, 1)
        self.assertEqual(s.max, 10)

    def test_cv_zero(self):
        s = BenchStats([10, 10, 10])
        self.assertEqual(s.cv, 0.0)

    def test_cv_nonzero(self):
        s = BenchStats([1, 2, 3])
        self.assertGreater(s.cv, 0)

    def test_percentile_0(self):
        s = BenchStats([1, 2, 3, 4, 5])
        self.assertEqual(s.percentile(0), 1)

    def test_percentile_100(self):
        s = BenchStats([1, 2, 3, 4, 5])
        self.assertEqual(s.percentile(100), 5)

    def test_percentile_50(self):
        s = BenchStats([1, 2, 3, 4, 5])
        self.assertEqual(s.percentile(50), 3)

    def test_to_dict(self):
        s = BenchStats([1, 2, 3])
        d = s.to_dict()
        self.assertIn("mean", d)
        self.assertIn("median", d)
        self.assertIn("std", d)
        self.assertIn("min", d)
        self.assertIn("max", d)
        self.assertIn("cv_percent", d)
        self.assertIn("p5", d)
        self.assertIn("p95", d)
        self.assertEqual(d["n"], 3)

    def test_sorted_internally(self):
        s = BenchStats([5, 3, 1, 4, 2])
        self.assertEqual(s.values, [1, 2, 3, 4, 5])

    def test_percentile_empty(self):
        s = BenchStats([])
        self.assertEqual(s.percentile(50), 0.0)

    def test_cv_zero_mean(self):
        s = BenchStats([0, 0, 0])
        self.assertEqual(s.cv, 0.0)

    def test_large_dataset(self):
        vals = list(range(1, 101))
        s = BenchStats(vals)
        self.assertEqual(s.n, 100)
        self.assertAlmostEqual(s.mean, 50.5)
        self.assertEqual(s.min, 1)
        self.assertEqual(s.max, 100)


class TestFormatters(unittest.TestCase):

    def test_fmt_time_microseconds(self):
        self.assertIn("us", _fmt_time(0.0005))

    def test_fmt_time_milliseconds(self):
        self.assertIn("ms", _fmt_time(0.05))

    def test_fmt_time_seconds(self):
        self.assertIn("s", _fmt_time(1.5))

    def test_fmt_mem_bytes(self):
        self.assertIn("B", _fmt_mem(500))

    def test_fmt_mem_kb(self):
        self.assertIn("KB", _fmt_mem(5000))

    def test_fmt_mem_mb(self):
        self.assertIn("MB", _fmt_mem(5_000_000))

    def test_fmt_time_zero(self):
        self.assertIn("us", _fmt_time(0))

    def test_fmt_mem_zero(self):
        self.assertIn("B", _fmt_mem(0))


class TestBenchmarkResult(unittest.TestCase):

    def _make_result(self):
        return BenchmarkResult(
            filename="test.srv",
            iterations=10,
            warmup=2,
            time_stats=BenchStats([0.01, 0.02, 0.015]),
            mem_stats=BenchStats([1000, 2000, 1500]),
            errors=0,
        )

    def test_to_dict_has_keys(self):
        r = self._make_result()
        d = r.to_dict()
        self.assertEqual(d["file"], "test.srv")
        self.assertEqual(d["iterations"], 10)
        self.assertEqual(d["warmup"], 2)
        self.assertIn("time_seconds", d)
        self.assertIn("peak_memory_bytes", d)

    def test_to_dict_errors(self):
        r = BenchmarkResult("x.srv", 5, 1, BenchStats([1]), BenchStats([1]), 3)
        self.assertEqual(r.to_dict()["errors"], 3)

    def test_to_dict_json_serializable(self):
        r = self._make_result()
        json.dumps(r.to_dict())


class TestRunProgram(unittest.TestCase):

    def test_simple_program(self):
        saurav = _resolve_saurav()
        t, m, err = _run_program(saurav, 'x = 1 + 2', quiet=True)
        self.assertIsNone(err)
        self.assertGreater(t, 0)
        self.assertGreater(m, 0)

    def test_print_program(self):
        saurav = _resolve_saurav()
        t, m, err = _run_program(saurav, 'print "hello"', quiet=True)
        self.assertIsNone(err)
        self.assertGreater(t, 0)

    def test_empty_program(self):
        saurav = _resolve_saurav()
        t, m, err = _run_program(saurav, '', quiet=True)
        self.assertIsNone(err)

    def test_math_program(self):
        saurav = _resolve_saurav()
        t, m, err = _run_program(saurav, 'x = 2 * 3 + 4', quiet=True)
        self.assertIsNone(err)

    def test_multiple_statements(self):
        saurav = _resolve_saurav()
        code = 'x = 1\ny = 2\nz = x + y'
        t, m, err = _run_program(saurav, code, quiet=True)
        self.assertIsNone(err)


class TestBenchmarkFile(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.tmpdir, "bench_test.srv")
        with open(self.test_file, "w") as f:
            f.write('x = 1 + 2\ny = x * 3\n')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_basic_benchmark(self):
        r = benchmark_file(self.test_file, iterations=3, warmup=1, quiet=True)
        self.assertEqual(r.iterations, 3)
        self.assertEqual(r.warmup, 1)
        self.assertEqual(r.filename, "bench_test.srv")
        self.assertEqual(r.errors, 0)
        self.assertGreater(r.time_stats.mean, 0)

    def test_progress_callback(self):
        calls = []
        def on_progress(phase, cur, total):
            calls.append((phase, cur, total))
        benchmark_file(self.test_file, iterations=2, warmup=1, quiet=True, on_progress=on_progress)
        warmups = [c for c in calls if c[0] == "warmup"]
        benches = [c for c in calls if c[0] == "bench"]
        self.assertEqual(len(warmups), 1)
        self.assertEqual(len(benches), 2)

    def test_iterations_count(self):
        r = benchmark_file(self.test_file, iterations=5, warmup=0, quiet=True)
        self.assertEqual(r.time_stats.n, 5)

    def test_zero_warmup(self):
        r = benchmark_file(self.test_file, iterations=2, warmup=0, quiet=True)
        self.assertEqual(r.warmup, 0)
        self.assertGreater(r.time_stats.mean, 0)


class TestCompareToBaseline(unittest.TestCase):

    def test_faster(self):
        result = {"file": "a.srv", "time_seconds": {"mean": 0.5}, "peak_memory_bytes": {"mean": 1000}}
        baseline = {"file": "a.srv", "time_seconds": {"mean": 1.0}, "peak_memory_bytes": {"mean": 1000}}
        c = compare_to_baseline(result, baseline)
        self.assertEqual(c["time_assessment"], "FASTER")
        self.assertAlmostEqual(c["time_delta_percent"], -50.0)

    def test_slower(self):
        result = {"file": "a.srv", "time_seconds": {"mean": 1.5}, "peak_memory_bytes": {"mean": 1000}}
        baseline = {"file": "a.srv", "time_seconds": {"mean": 1.0}, "peak_memory_bytes": {"mean": 1000}}
        c = compare_to_baseline(result, baseline)
        self.assertEqual(c["time_assessment"], "SLOWER")

    def test_same(self):
        result = {"file": "a.srv", "time_seconds": {"mean": 1.0}, "peak_memory_bytes": {"mean": 1000}}
        baseline = {"file": "a.srv", "time_seconds": {"mean": 1.0}, "peak_memory_bytes": {"mean": 1000}}
        c = compare_to_baseline(result, baseline)
        self.assertEqual(c["time_assessment"], "SAME")

    def test_more_memory(self):
        result = {"file": "a.srv", "time_seconds": {"mean": 1.0}, "peak_memory_bytes": {"mean": 2000}}
        baseline = {"file": "a.srv", "time_seconds": {"mean": 1.0}, "peak_memory_bytes": {"mean": 1000}}
        c = compare_to_baseline(result, baseline)
        self.assertEqual(c["mem_assessment"], "MORE_MEMORY")

    def test_less_memory(self):
        result = {"file": "a.srv", "time_seconds": {"mean": 1.0}, "peak_memory_bytes": {"mean": 400}}
        baseline = {"file": "a.srv", "time_seconds": {"mean": 1.0}, "peak_memory_bytes": {"mean": 1000}}
        c = compare_to_baseline(result, baseline)
        self.assertEqual(c["mem_assessment"], "LESS_MEMORY")

    def test_zero_baseline(self):
        result = {"file": "a.srv", "time_seconds": {"mean": 1.0}, "peak_memory_bytes": {"mean": 0}}
        baseline = {"file": "a.srv", "time_seconds": {"mean": 0}, "peak_memory_bytes": {"mean": 0}}
        c = compare_to_baseline(result, baseline)
        self.assertEqual(c["time_delta_percent"], 0)

    def test_has_all_keys(self):
        result = {"file": "a.srv", "time_seconds": {"mean": 1.0}, "peak_memory_bytes": {"mean": 1000}}
        baseline = {"file": "a.srv", "time_seconds": {"mean": 1.0}, "peak_memory_bytes": {"mean": 1000}}
        c = compare_to_baseline(result, baseline)
        for key in ["file", "time_delta_percent", "time_assessment", "mem_delta_percent", "mem_assessment",
                     "baseline_time", "current_time", "baseline_mem", "current_mem"]:
            self.assertIn(key, c)


class TestFormatTextReport(unittest.TestCase):

    def _make_results(self, n=1):
        results = []
        for i in range(n):
            results.append(BenchmarkResult(
                filename=f"test{i}.srv",
                iterations=5,
                warmup=1,
                time_stats=BenchStats([0.01 * (i + 1)] * 5),
                mem_stats=BenchStats([1000 * (i + 1)] * 5),
                errors=0,
            ))
        return results

    def test_single_report(self):
        report = format_text_report(self._make_results(1))
        self.assertIn("SAURAVCODE BENCHMARK REPORT", report)
        self.assertIn("test0.srv", report)
        self.assertIn("Mean:", report)

    def test_comparison_table(self):
        report = format_text_report(self._make_results(2))
        self.assertIn("COMPARISON", report)
        self.assertIn("baseline", report)

    def test_baseline_comparison(self):
        results = self._make_results(1)
        comps = [{"file": "test0.srv", "time_delta_percent": -20.0, "time_assessment": "FASTER",
                  "mem_delta_percent": 5.0, "mem_assessment": "SAME",
                  "baseline_time": 0.05, "current_time": 0.04,
                  "baseline_mem": 1000, "current_mem": 1050}]
        report = format_text_report(results, comps)
        self.assertIn("BASELINE COMPARISON", report)
        self.assertIn("FASTER", report)

    def test_sparkline(self):
        r = BenchmarkResult("x.srv", 5, 1, BenchStats([0.01, 0.02, 0.03, 0.04, 0.05]), BenchStats([1000]*5), 0)
        report = format_text_report([r])
        self.assertIn("Time Distribution:", report)

    def test_errors_shown(self):
        r = BenchmarkResult("err.srv", 5, 1, BenchStats([0.01]), BenchStats([1000]), 3)
        report = format_text_report([r])
        self.assertIn("Errors: 3", report)

    def test_report_contains_memory(self):
        report = format_text_report(self._make_results(1))
        self.assertIn("Peak Memory:", report)


class TestFormatCSV(unittest.TestCase):

    def test_csv_header(self):
        r = BenchmarkResult("t.srv", 3, 1, BenchStats([1, 2, 3]), BenchStats([100, 200, 300]), 0)
        csv = format_csv([r])
        lines = csv.strip().split("\n")
        self.assertEqual(len(lines), 2)
        self.assertIn("file", lines[0])
        self.assertIn("t.srv", lines[1])

    def test_csv_multiple(self):
        r1 = BenchmarkResult("a.srv", 3, 1, BenchStats([1]), BenchStats([100]), 0)
        r2 = BenchmarkResult("b.srv", 3, 1, BenchStats([2]), BenchStats([200]), 0)
        csv = format_csv([r1, r2])
        lines = csv.strip().split("\n")
        self.assertEqual(len(lines), 3)

    def test_csv_fields_count(self):
        r = BenchmarkResult("t.srv", 3, 1, BenchStats([1]), BenchStats([100]), 0)
        csv = format_csv([r])
        lines = csv.strip().split("\n")
        self.assertEqual(len(lines[0].split(",")), len(lines[1].split(",")))


class TestParseArgs(unittest.TestCase):

    def test_simple_file(self):
        files, opts = parse_args(["test.srv"])
        self.assertEqual(files, ["test.srv"])
        self.assertEqual(opts["iterations"], 10)

    def test_iterations(self):
        _, opts = parse_args(["t.srv", "-n", "20"])
        self.assertEqual(opts["iterations"], 20)

    def test_warmup(self):
        _, opts = parse_args(["t.srv", "--warmup", "5"])
        self.assertEqual(opts["warmup"], 5)

    def test_json_flag(self):
        _, opts = parse_args(["t.srv", "--json"])
        self.assertTrue(opts["json"])

    def test_csv_flag(self):
        _, opts = parse_args(["t.srv", "--csv"])
        self.assertTrue(opts["csv"])

    def test_quiet_flag(self):
        _, opts = parse_args(["t.srv", "--quiet"])
        self.assertTrue(opts["quiet"])

    def test_baseline(self):
        _, opts = parse_args(["t.srv", "--baseline", "base.json"])
        self.assertEqual(opts["baseline"], "base.json")

    def test_save(self):
        _, opts = parse_args(["t.srv", "--save", "out.json"])
        self.assertEqual(opts["save"], "out.json")

    def test_multiple_files(self):
        files, _ = parse_args(["a.srv", "b.srv", "c.srv"])
        self.assertEqual(len(files), 3)

    def test_all_options(self):
        files, opts = parse_args(["x.srv", "-n", "50", "--warmup", "3", "--json", "--quiet", "--baseline", "b.json", "--save", "s.json"])
        self.assertEqual(files, ["x.srv"])
        self.assertEqual(opts["iterations"], 50)
        self.assertEqual(opts["warmup"], 3)
        self.assertTrue(opts["json"])
        self.assertTrue(opts["quiet"])

    def test_defaults(self):
        _, opts = parse_args(["t.srv"])
        self.assertEqual(opts["iterations"], 10)
        self.assertEqual(opts["warmup"], 2)
        self.assertFalse(opts["json"])
        self.assertFalse(opts["csv"])
        self.assertFalse(opts["quiet"])
        self.assertIsNone(opts["baseline"])
        self.assertIsNone(opts["save"])

    def test_long_iterations(self):
        _, opts = parse_args(["t.srv", "--iterations", "100"])
        self.assertEqual(opts["iterations"], 100)


class TestIntegration(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_benchmark_and_save(self):
        srv = os.path.join(self.tmpdir, "prog.srv")
        with open(srv, "w") as f:
            f.write('x = 1 + 2\n')
        save_path = os.path.join(self.tmpdir, "results.json")
        r = benchmark_file(srv, iterations=3, warmup=1, quiet=True)
        output = {"results": [r.to_dict()]}
        with open(save_path, "w") as f:
            json.dump(output, f)
        with open(save_path) as f:
            data = json.load(f)
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["file"], "prog.srv")

    def test_baseline_roundtrip(self):
        srv = os.path.join(self.tmpdir, "prog.srv")
        with open(srv, "w") as f:
            f.write('x = 1\n')
        r = benchmark_file(srv, iterations=3, warmup=0, quiet=True)
        rd = r.to_dict()
        c = compare_to_baseline(rd, rd)
        self.assertEqual(c["time_assessment"], "SAME")
        self.assertEqual(c["mem_assessment"], "SAME")

    def test_full_json_output(self):
        srv = os.path.join(self.tmpdir, "prog.srv")
        with open(srv, "w") as f:
            f.write('x = 1\n')
        r = benchmark_file(srv, iterations=2, warmup=0, quiet=True)
        output = {"results": [r.to_dict()]}
        j = json.dumps(output)
        parsed = json.loads(j)
        self.assertEqual(parsed["results"][0]["iterations"], 2)

    def test_csv_output(self):
        srv = os.path.join(self.tmpdir, "prog.srv")
        with open(srv, "w") as f:
            f.write('x = 1\n')
        r = benchmark_file(srv, iterations=2, warmup=0, quiet=True)
        csv = format_csv([r])
        self.assertIn("prog.srv", csv)


if __name__ == "__main__":
    unittest.main()
