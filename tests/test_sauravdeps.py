#!/usr/bin/env python3
"""Tests for sauravdeps -- dependency analyzer."""

import json
import os
import sys
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sauravdeps


class TestExtractImports(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _write(self, name, content):
        path = os.path.join(self.tmpdir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_quoted_import(self):
        p = self._write("a.srv", 'import "utils"\nprint "hi"')
        self.assertEqual(sauravdeps.extract_imports(p), ["utils"])

    def test_bare_import(self):
        p = self._write("a.srv", "import utils\nprint 42")
        self.assertEqual(sauravdeps.extract_imports(p), ["utils"])

    def test_multiple_imports(self):
        p = self._write("a.srv", 'import "x"\nimport y\nimport "z"')
        self.assertEqual(sauravdeps.extract_imports(p), ["x", "y", "z"])

    def test_no_imports(self):
        p = self._write("a.srv", "print 42\nx = 1")
        self.assertEqual(sauravdeps.extract_imports(p), [])

    def test_import_with_comment(self):
        p = self._write("a.srv", 'import "utils"  # load utils')
        self.assertEqual(sauravdeps.extract_imports(p), ["utils"])

    def test_comment_only_line(self):
        p = self._write("a.srv", '# import "fake"\nprint 1')
        self.assertEqual(sauravdeps.extract_imports(p), [])


class TestBuildGraph(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _write(self, name, content):
        path = os.path.join(self.tmpdir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_simple_dep(self):
        a = self._write("a.srv", 'import "b"')
        b = self._write("b.srv", "print 1")
        graph, unresolved, all_files = sauravdeps.build_graph([a, b])
        self.assertIn(b, graph[a])
        self.assertEqual(graph[b], [])
        self.assertFalse(unresolved)

    def test_unresolved(self):
        a = self._write("a.srv", 'import "nonexistent"')
        graph, unresolved, _ = sauravdeps.build_graph([a])
        self.assertIn(a, unresolved)
        self.assertEqual(unresolved[a], ["nonexistent"])

    def test_chain(self):
        a = self._write("a.srv", 'import "b"')
        b = self._write("b.srv", 'import "c"')
        c = self._write("c.srv", "print 1")
        graph, _, _ = sauravdeps.build_graph([a, b, c])
        self.assertIn(b, graph[a])
        self.assertIn(c, graph[b])


class TestCycles(unittest.TestCase):
    def test_no_cycle(self):
        graph = {"a": ["b"], "b": ["c"], "c": []}
        self.assertEqual(sauravdeps.find_cycles(graph), [])

    def test_simple_cycle(self):
        graph = {"a": ["b"], "b": ["a"]}
        cycles = sauravdeps.find_cycles(graph)
        self.assertTrue(len(cycles) > 0)

    def test_self_cycle(self):
        graph = {"a": ["a"]}
        cycles = sauravdeps.find_cycles(graph)
        self.assertTrue(len(cycles) > 0)

    def test_triangle(self):
        graph = {"a": ["b"], "b": ["c"], "c": ["a"]}
        cycles = sauravdeps.find_cycles(graph)
        self.assertTrue(len(cycles) > 0)


class TestDepth(unittest.TestCase):
    def test_flat(self):
        graph = {"a": [], "b": [], "c": []}
        depths = sauravdeps.compute_depth(graph)
        self.assertEqual(depths["a"], 0)

    def test_chain_depth(self):
        graph = {"a": ["b"], "b": ["c"], "c": []}
        depths = sauravdeps.compute_depth(graph)
        self.assertEqual(depths["a"], 2)
        self.assertEqual(depths["b"], 1)
        self.assertEqual(depths["c"], 0)

    def test_diamond(self):
        graph = {"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []}
        depths = sauravdeps.compute_depth(graph)
        self.assertEqual(depths["a"], 2)


class TestRootsAndLeaves(unittest.TestCase):
    def test_roots(self):
        graph = {"a": ["b"], "b": ["c"], "c": []}
        roots = sauravdeps.find_roots(graph, {"a", "b", "c"})
        self.assertEqual(roots, ["a"])

    def test_leaves(self):
        graph = {"a": ["b"], "b": ["c"], "c": []}
        leaves = sauravdeps.find_leaves(graph)
        self.assertEqual(leaves, ["c"])


class TestReachable(unittest.TestCase):
    def test_reachable(self):
        graph = {"a": ["b"], "b": ["c"], "c": [], "d": []}
        reached = sauravdeps.reachable_from(graph, "a")
        self.assertEqual(reached, {"a", "b", "c"})
        self.assertNotIn("d", reached)


class TestFormatters(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _write(self, name, content):
        path = os.path.join(self.tmpdir, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_text_output(self):
        a = self._write("a.srv", 'import "b"')
        b = self._write("b.srv", "print 1")
        graph, unresolved, all_files = sauravdeps.build_graph([a, b])
        text = sauravdeps.format_text(graph, unresolved, all_files, self.tmpdir)
        self.assertIn("Dependency Report", text)
        self.assertIn("a", text)

    def test_dot_output(self):
        a = self._write("a.srv", 'import "b"')
        b = self._write("b.srv", "print 1")
        graph, _, _ = sauravdeps.build_graph([a, b])
        dot = sauravdeps.format_dot(graph, self.tmpdir)
        self.assertIn("digraph", dot)
        self.assertIn("->", dot)

    def test_json_output(self):
        a = self._write("a.srv", 'import "b"')
        b = self._write("b.srv", "print 1")
        graph, unresolved, all_files = sauravdeps.build_graph([a, b])
        j = sauravdeps.format_json(graph, unresolved, all_files, self.tmpdir)
        data = json.loads(j)
        self.assertIn("modules", data)
        self.assertIn("cycles", data)
        self.assertEqual(data["edges"], 1)


class TestDiscover(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_discover(self):
        for name in ["a.srv", "b.srv", "c.txt"]:
            with open(os.path.join(self.tmpdir, name), "w") as f:
                f.write("x = 1")
        files = sauravdeps.discover_srv_files(self.tmpdir)
        self.assertEqual(len(files), 2)
        self.assertTrue(all(f.endswith(".srv") for f in files))

    def test_discover_single(self):
        p = os.path.join(self.tmpdir, "x.srv")
        with open(p, "w") as f:
            f.write("x = 1")
        files = sauravdeps.discover_srv_files(p)
        self.assertEqual(len(files), 1)


if __name__ == "__main__":
    unittest.main()
