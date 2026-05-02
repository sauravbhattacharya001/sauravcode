#!/usr/bin/env python3
"""Tests for sauravterrain — autonomous code complexity terrain mapper."""

import json
import math
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from io import StringIO

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sauravterrain import (
    TerrainCell, Ridge, Trail, TerrainReport,
    _analyze_file, _compute_elevations, _detect_peaks, _detect_valleys,
    _trace_ridges, _compute_erosion, _recommend_trails, _compute_health,
    analyze_terrain, _generate_html, main
)


def _write_srv(tmpdir, name, content):
    path = os.path.join(tmpdir, name)
    with open(path, 'w') as f:
        f.write(content)
    return path


SIMPLE_SRV = """\
# A simple program
function greet name
    print "Hello " + name

function add a b
    return a + b
"""

COMPLEX_SRV = """\
function process_data items
    if items
        for item in items
            if item > 0
                while item > 10
                    item = item - 1
                    if item == 5
                        print "midpoint"
                    elif item == 3
                        print "low"
            elif item < 0
                for x in range(10)
                    if x > 5
                        print x
    return items

function simple_helper
    return 42

function validate input
    if input
        if input > 0
            if input < 100
                if input != 50
                    return true
    return false
"""

MIXED_SRV = """\
function easy
    return 1

function medium x
    if x > 0
        for i in range(x)
            print i
    return x

function hard a b c
    if a
        if b
            while c > 0
                for i in range(a)
                    if i > b
                        if c > 10
                            print "complex"
                        elif c > 5
                            print "moderate"
                c = c - 1
    elif b
        for j in range(b)
            if j > 0
                print j
    return a + b + c

function tiny
    print "hi"
"""


class TestTerrainCell(unittest.TestCase):
    def test_fqn(self):
        c = TerrainCell(name="foo", file="test.srv", line=1)
        self.assertEqual(c.fqn, "test.srv::foo")

    def test_default_values(self):
        c = TerrainCell(name="bar", file="x.srv", line=5)
        self.assertEqual(c.elevation, 0.0)
        self.assertEqual(c.risk_tier, "plain")
        self.assertFalse(c.is_peak)
        self.assertFalse(c.is_valley)
        self.assertEqual(c.ridge_id, -1)


class TestAnalyzeFile(unittest.TestCase):
    def test_simple_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_srv(d, "simple.srv", SIMPLE_SRV)
            cells = _analyze_file(path)
            self.assertEqual(len(cells), 2)
            names = [c.name for c in cells]
            self.assertIn("greet", names)
            self.assertIn("add", names)

    def test_complex_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_srv(d, "complex.srv", COMPLEX_SRV)
            cells = _analyze_file(path)
            self.assertEqual(len(cells), 3)
            process = next(c for c in cells if c.name == "process_data")
            self.assertGreater(process.complexity, 1)
            self.assertGreater(process.max_depth, 2)

    def test_empty_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_srv(d, "empty.srv", "# just a comment\n")
            cells = _analyze_file(path)
            self.assertEqual(len(cells), 0)

    def test_nonexistent_file(self):
        cells = _analyze_file("/nonexistent/path.srv")
        self.assertEqual(len(cells), 0)

    def test_call_detection(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_srv(d, "calls.srv",
                "function foo\n    bar()\n    baz(1, 2)\n")
            cells = _analyze_file(path)
            self.assertEqual(len(cells), 1)
            self.assertIn("bar", cells[0].calls)
            self.assertIn("baz", cells[0].calls)

    def test_builtin_calls_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_srv(d, "builtins.srv",
                "function foo\n    print(1)\n    len(x)\n    custom()\n")
            cells = _analyze_file(path)
            self.assertNotIn("print", cells[0].calls)
            self.assertNotIn("len", cells[0].calls)
            self.assertIn("custom", cells[0].calls)


class TestElevationMapper(unittest.TestCase):
    def test_single_cell(self):
        cells = [TerrainCell(name="a", file="t.srv", line=1, complexity=5, max_depth=3, loc=20)]
        _compute_elevations(cells)
        self.assertEqual(cells[0].elevation, 0.0)  # single cell = normalized to 0 (min=max)

    def test_multiple_cells_normalized(self):
        cells = [
            TerrainCell(name="low", file="t.srv", line=1, complexity=1, max_depth=0, loc=2),
            TerrainCell(name="high", file="t.srv", line=10, complexity=10, max_depth=5, loc=50),
        ]
        _compute_elevations(cells)
        self.assertEqual(cells[0].elevation, 0.0)
        self.assertEqual(cells[1].elevation, 100.0)

    def test_risk_tiers(self):
        cells = [
            TerrainCell(name="a", file="t.srv", line=1, complexity=1, max_depth=0, loc=1),
            TerrainCell(name="b", file="t.srv", line=2, complexity=3, max_depth=1, loc=10),
            TerrainCell(name="c", file="t.srv", line=3, complexity=6, max_depth=3, loc=30),
            TerrainCell(name="d", file="t.srv", line=4, complexity=12, max_depth=6, loc=80),
        ]
        _compute_elevations(cells)
        tiers = {c.name: c.risk_tier for c in cells}
        self.assertEqual(tiers["a"], "plain")
        self.assertEqual(tiers["d"], "peak")

    def test_empty_cells(self):
        _compute_elevations([])  # should not crash


class TestPeakDetector(unittest.TestCase):
    def test_isolated_high_cell_is_peak(self):
        cells = [
            TerrainCell(name="high", file="t.srv", line=1, elevation=80.0),
        ]
        peaks = _detect_peaks(cells, {})
        self.assertIn("t.srv::high", peaks)
        self.assertTrue(cells[0].is_peak)

    def test_highest_among_neighbors_is_peak(self):
        cells = [
            TerrainCell(name="center", file="t.srv", line=1, elevation=90.0, calls=["left", "right"]),
            TerrainCell(name="left", file="t.srv", line=5, elevation=30.0),
            TerrainCell(name="right", file="t.srv", line=10, elevation=40.0),
        ]
        peaks = _detect_peaks(cells, {})
        self.assertIn("t.srv::center", peaks)

    def test_low_cell_not_peak(self):
        cells = [
            TerrainCell(name="low", file="t.srv", line=1, elevation=10.0),
        ]
        peaks = _detect_peaks(cells, {})
        self.assertEqual(len(peaks), 0)


class TestValleyFinder(unittest.TestCase):
    def test_valley_detection(self):
        cells = [
            TerrainCell(name="valley", file="t.srv", line=1, elevation=5.0, calls=["h1", "h2"]),
            TerrainCell(name="h1", file="t.srv", line=5, elevation=70.0),
            TerrainCell(name="h2", file="t.srv", line=10, elevation=80.0),
        ]
        valleys = _detect_valleys(cells)
        self.assertIn("t.srv::valley", valleys)

    def test_no_valley_if_neighbors_also_low(self):
        cells = [
            TerrainCell(name="a", file="t.srv", line=1, elevation=10.0, calls=["b"]),
            TerrainCell(name="b", file="t.srv", line=5, elevation=15.0),
            TerrainCell(name="c", file="t.srv", line=10, elevation=12.0),
        ]
        valleys = _detect_valleys(cells)
        self.assertEqual(len(valleys), 0)


class TestRidgeTracer(unittest.TestCase):
    def test_connected_high_cells_form_ridge(self):
        cells = [
            TerrainCell(name="a", file="t.srv", line=1, elevation=70.0, calls=["b"]),
            TerrainCell(name="b", file="t.srv", line=10, elevation=65.0, calls=["c"]),
            TerrainCell(name="c", file="t.srv", line=20, elevation=60.0),
        ]
        ridges = _trace_ridges(cells)
        self.assertGreaterEqual(len(ridges), 1)
        self.assertGreaterEqual(ridges[0].length, 2)

    def test_no_ridge_if_all_low(self):
        cells = [
            TerrainCell(name="a", file="t.srv", line=1, elevation=10.0),
            TerrainCell(name="b", file="t.srv", line=5, elevation=20.0),
        ]
        ridges = _trace_ridges(cells)
        self.assertEqual(len(ridges), 0)

    def test_ridge_severity(self):
        cells = [
            TerrainCell(name="a", file="t.srv", line=1, elevation=85.0, calls=["b"]),
            TerrainCell(name="b", file="t.srv", line=10, elevation=90.0),
        ]
        ridges = _trace_ridges(cells)
        if ridges:
            self.assertEqual(ridges[0].severity, "critical")


class TestErosionRisk(unittest.TestCase):
    def test_high_density_gets_high_erosion(self):
        cells = [
            TerrainCell(name="dense", file="t.srv", line=1, complexity=10, max_depth=5, loc=5),
        ]
        zones = _compute_erosion(cells)
        self.assertGreater(cells[0].erosion_risk, 0.5)

    def test_low_density_low_erosion(self):
        cells = [
            TerrainCell(name="spread", file="t.srv", line=1, complexity=2, max_depth=1, loc=50),
        ]
        _compute_erosion(cells)
        self.assertLess(cells[0].erosion_risk, 0.3)

    def test_tiny_function_skipped(self):
        cells = [
            TerrainCell(name="tiny", file="t.srv", line=1, complexity=5, max_depth=2, loc=2),
        ]
        zones = _compute_erosion(cells)
        self.assertEqual(len(zones), 0)


class TestTrailRecommender(unittest.TestCase):
    def test_gentle_ascent_always_generated(self):
        cells = [
            TerrainCell(name="a", file="t.srv", line=1, elevation=20.0),
            TerrainCell(name="b", file="t.srv", line=5, elevation=60.0),
        ]
        trails = _recommend_trails(cells, [])
        names = [t.name for t in trails]
        self.assertIn("Gentle Ascent", names)

    def test_peak_summit_with_peaks(self):
        cells = [
            TerrainCell(name="p", file="t.srv", line=1, elevation=90.0, is_peak=True),
        ]
        trails = _recommend_trails(cells, [])
        names = [t.name for t in trails]
        self.assertIn("Peak Summit", names)

    def test_empty_cells_no_trails(self):
        trails = _recommend_trails([], [])
        self.assertEqual(len(trails), 0)

    def test_ridge_walk_generated(self):
        cells = [TerrainCell(name="a", file="t.srv", line=1, elevation=70.0)]
        ridge = Ridge(ridge_id=0, cells=["t.srv::a", "t.srv::b"], avg_elevation=65.0, length=2)
        trails = _recommend_trails(cells, [ridge])
        names = [t.name for t in trails]
        self.assertTrue(any("Ridge Walk" in n for n in names))

    def test_erosion_patrol_generated(self):
        cells = [
            TerrainCell(name="e", file="t.srv", line=1, erosion_risk=0.8, elevation=50.0),
        ]
        trails = _recommend_trails(cells, [])
        names = [t.name for t in trails]
        self.assertIn("Erosion Patrol", names)


class TestHealthScorer(unittest.TestCase):
    def test_empty_cells_max_health(self):
        score, insights = _compute_health([], [], [], [])
        self.assertEqual(score, 100.0)

    def test_all_low_elevation_high_health(self):
        cells = [
            TerrainCell(name="a", file="t.srv", line=1, elevation=10.0),
            TerrainCell(name="b", file="t.srv", line=5, elevation=15.0),
        ]
        score, _ = _compute_health(cells, [], [], [])
        self.assertGreater(score, 70)

    def test_many_peaks_lowers_health(self):
        cells = [
            TerrainCell(name=f"p{i}", file="t.srv", line=i, elevation=85.0)
            for i in range(10)
        ]
        peaks = [c.fqn for c in cells]
        score, _ = _compute_health(cells, peaks, [], [])
        self.assertLess(score, 60)

    def test_critical_ridges_lower_health(self):
        cells = [TerrainCell(name="a", file="t.srv", line=1, elevation=50.0)]
        ridges = [Ridge(ridge_id=0, severity="critical", avg_elevation=80.0, length=3)]
        score, _ = _compute_health(cells, [], ridges, [])
        self.assertLess(score, 90)

    def test_insights_generated(self):
        cells = [TerrainCell(name="a", file="t.srv", line=1, elevation=70.0)]
        _, insights = _compute_health(cells, [], [], [])
        self.assertGreater(len(insights), 0)


class TestAnalyzeTerrain(unittest.TestCase):
    def test_full_pipeline(self):
        with tempfile.TemporaryDirectory() as d:
            _write_srv(d, "a.srv", MIXED_SRV)
            report = analyze_terrain([d])
            self.assertEqual(report.files_scanned, 1)
            self.assertEqual(report.total_functions, 4)
            self.assertIsInstance(report.health_score, float)
            self.assertGreater(len(report.insights), 0)

    def test_multiple_files(self):
        with tempfile.TemporaryDirectory() as d:
            _write_srv(d, "a.srv", SIMPLE_SRV)
            _write_srv(d, "b.srv", COMPLEX_SRV)
            report = analyze_terrain([d])
            self.assertEqual(report.files_scanned, 2)
            self.assertEqual(report.total_functions, 5)

    def test_recursive(self):
        with tempfile.TemporaryDirectory() as d:
            sub = os.path.join(d, "sub")
            os.makedirs(sub)
            _write_srv(d, "root.srv", SIMPLE_SRV)
            _write_srv(sub, "child.srv", SIMPLE_SRV)
            report = analyze_terrain([d], recursive=True)
            self.assertEqual(report.files_scanned, 2)

    def test_elevation_histogram(self):
        with tempfile.TemporaryDirectory() as d:
            _write_srv(d, "a.srv", MIXED_SRV)
            report = analyze_terrain([d])
            total = sum(report.elevation_histogram.values())
            self.assertEqual(total, report.total_functions)


class TestHTMLGeneration(unittest.TestCase):
    def test_html_contains_key_elements(self):
        report = TerrainReport(
            timestamp="2026-05-02", files_scanned=1, total_functions=2,
            cells=[
                TerrainCell(name="a", file="t.srv", line=1, elevation=80.0, risk_tier="peak", is_peak=True),
                TerrainCell(name="b", file="t.srv", line=5, elevation=20.0, risk_tier="plain"),
            ],
            peaks=["t.srv::a"], valleys=[], ridges=[], trails=[], erosion_zones=[],
            health_score=75.0, insights=["Test insight"]
        )
        html = _generate_html(report)
        self.assertIn("sauravterrain", html)
        self.assertIn("Terrain Map", html)
        self.assertIn("Test insight", html)
        self.assertIn("PEAK", html)

    def test_html_file_output(self):
        with tempfile.TemporaryDirectory() as d:
            _write_srv(d, "a.srv", MIXED_SRV)
            report = analyze_terrain([d])
            html = _generate_html(report)
            out = os.path.join(d, "report.html")
            with open(out, 'w', encoding='utf-8') as f:
                f.write(html)
            self.assertTrue(os.path.exists(out))
            self.assertGreater(os.path.getsize(out), 1000)


class TestCLI(unittest.TestCase):
    def test_json_output(self):
        with tempfile.TemporaryDirectory() as d:
            _write_srv(d, "a.srv", SIMPLE_SRV)
            out = StringIO()
            with patch('sys.stdout', out):
                main([d, "--json", "--no-color"])
            data = json.loads(out.getvalue())
            self.assertIn("health_score", data)
            self.assertIn("cells", data)

    def test_peaks_filter(self):
        with tempfile.TemporaryDirectory() as d:
            _write_srv(d, "a.srv", COMPLEX_SRV)
            out = StringIO()
            with patch('sys.stdout', out):
                main([d, "--peaks", "--no-color"])
            # Should not crash
            self.assertIsInstance(out.getvalue(), str)

    def test_top_n(self):
        with tempfile.TemporaryDirectory() as d:
            _write_srv(d, "a.srv", MIXED_SRV)
            out = StringIO()
            with patch('sys.stdout', out):
                main([d, "--top", "2", "--no-color"])
            self.assertIn("Top 2", out.getvalue())

    def test_html_flag(self):
        with tempfile.TemporaryDirectory() as d:
            _write_srv(d, "a.srv", SIMPLE_SRV)
            html_path = os.path.join(d, "out.html")
            main([d, "--html", html_path, "--no-color"])
            self.assertTrue(os.path.exists(html_path))

    def test_trails_filter(self):
        with tempfile.TemporaryDirectory() as d:
            _write_srv(d, "a.srv", MIXED_SRV)
            out = StringIO()
            with patch('sys.stdout', out):
                main([d, "--trails", "--no-color"])
            self.assertIn("Gentle Ascent", out.getvalue())

    def test_ridges_filter(self):
        with tempfile.TemporaryDirectory() as d:
            _write_srv(d, "a.srv", COMPLEX_SRV)
            out = StringIO()
            with patch('sys.stdout', out):
                main([d, "--ridges", "--no-color"])
            self.assertIsInstance(out.getvalue(), str)

    def test_erosion_filter(self):
        with tempfile.TemporaryDirectory() as d:
            _write_srv(d, "a.srv", COMPLEX_SRV)
            out = StringIO()
            with patch('sys.stdout', out):
                main([d, "--erosion", "--no-color"])
            self.assertIsInstance(out.getvalue(), str)

    def test_valleys_filter(self):
        with tempfile.TemporaryDirectory() as d:
            _write_srv(d, "a.srv", MIXED_SRV)
            out = StringIO()
            with patch('sys.stdout', out):
                main([d, "--valleys", "--no-color"])
            self.assertIsInstance(out.getvalue(), str)

    def test_full_report(self):
        with tempfile.TemporaryDirectory() as d:
            _write_srv(d, "a.srv", MIXED_SRV)
            out = StringIO()
            with patch('sys.stdout', out):
                main([d, "--no-color"])
            output = out.getvalue()
            self.assertIn("sauravterrain", output)
            self.assertIn("Health", output)


if __name__ == "__main__":
    unittest.main()
