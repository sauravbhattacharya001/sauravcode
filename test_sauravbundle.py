"""Comprehensive tests for sauravbundle — the .srv module bundler.

Covers: import resolution, recursive collection, topological order, minify,
banner, exclude, dependency tree, dry-run, stats output, JSON output,
unresolved imports, circular dependencies, CLI exit codes.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import sauravbundle as sb  # noqa: E402


class _TmpTree:
    """Helper to build a temporary tree of .srv files."""

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="srvbundle_")

    def write(self, name, content):
        path = os.path.join(self.tmp, name)
        os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(name) else None
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def cleanup(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestImportRegex(unittest.TestCase):
    def test_quoted_import(self):
        m = sb.IMPORT_RE.match('import "math_utils"\n')
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "math_utils")

    def test_bare_import(self):
        m = sb.IMPORT_RE.match("import math_utils\n")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(2), "math_utils")

    def test_leading_whitespace(self):
        m = sb.IMPORT_RE.match("   import foo\n")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(2), "foo")

    def test_non_import_line(self):
        self.assertIsNone(sb.IMPORT_RE.match("print hello\n"))
        self.assertIsNone(sb.IMPORT_RE.match("# import foo\n"))
        self.assertIsNone(sb.IMPORT_RE.match("importx foo\n"))


class TestResolveModulePath(unittest.TestCase):
    def setUp(self):
        self.t = _TmpTree()
        self.t.write("foo.srv", "x = 1\n")
        self.t.write("sub_dir/bar.srv", "y = 2\n") if False else None
        os.makedirs(os.path.join(self.t.tmp, "sub_dir"), exist_ok=True)
        self.t.write("sub_dir/bar.srv", "y = 2\n")

    def tearDown(self):
        self.t.cleanup()

    def test_resolves_with_srv_extension(self):
        path = sb.resolve_module_path("foo", [self.t.tmp])
        self.assertIsNotNone(path)
        self.assertTrue(path.endswith("foo.srv"))

    def test_resolves_with_explicit_extension(self):
        path = sb.resolve_module_path("foo.srv", [self.t.tmp])
        self.assertIsNotNone(path)

    def test_strips_quotes(self):
        path = sb.resolve_module_path('"foo"', [self.t.tmp])
        self.assertIsNotNone(path)

    def test_returns_none_when_missing(self):
        self.assertIsNone(sb.resolve_module_path("does_not_exist", [self.t.tmp]))

    def test_searches_multiple_dirs(self):
        other = tempfile.mkdtemp(prefix="srvbundle_alt_")
        try:
            path = sb.resolve_module_path("bar", [other, os.path.join(self.t.tmp, "sub_dir")])
            self.assertIsNotNone(path)
            self.assertTrue(path.endswith("bar.srv"))
        finally:
            import shutil
            shutil.rmtree(other, ignore_errors=True)


class TestExtractImports(unittest.TestCase):
    def setUp(self):
        self.t = _TmpTree()

    def tearDown(self):
        self.t.cleanup()

    def test_extracts_multiple(self):
        p = self.t.write("a.srv", 'import "b"\nimport c\nx = 1\nimport d\n')
        imps = sb.extract_imports(p)
        names = [n for _, n in imps]
        self.assertEqual(names, ["b", "c", "d"])

    def test_empty_file(self):
        p = self.t.write("e.srv", "")
        self.assertEqual(sb.extract_imports(p), [])

    def test_missing_file_returns_empty(self):
        self.assertEqual(sb.extract_imports("/no/such/file.srv"), [])

    def test_tracks_line_numbers(self):
        p = self.t.write("a.srv", "x = 1\nimport b\ny = 2\nimport c\n")
        imps = sb.extract_imports(p)
        self.assertEqual(imps, [(2, "b"), (4, "c")])


class TestStripAndMinify(unittest.TestCase):
    def test_strip_imports(self):
        lines = ['import "a"\n', "x = 1\n", "import b\n", "y = 2\n"]
        out = sb.strip_imports(lines)
        self.assertEqual(out, ["x = 1\n", "y = 2\n"])

    def test_minify_drops_comments_and_blanks(self):
        lines = ["# comment\n", "\n", "x = 1\n", "  # indented comment\n", "y = 2\n"]
        out = sb.minify_lines(lines)
        self.assertEqual(out, ["x = 1\n", "y = 2\n"])

    def test_minify_preserves_code_with_inline_hash_in_string(self):
        # COMMENT_RE only matches lines that *start* (with optional whitespace) with #
        lines = ['print "#not a comment"\n']
        self.assertEqual(sb.minify_lines(lines), ['print "#not a comment"\n'])


class TestCollectModules(unittest.TestCase):
    def setUp(self):
        self.t = _TmpTree()

    def tearDown(self):
        self.t.cleanup()

    def test_topological_order(self):
        # entry -> a -> b ; entry -> b
        self.t.write("b.srv", "x = 1\n")
        self.t.write("a.srv", 'import "b"\ny = 2\n')
        entry = self.t.write("entry.srv", 'import "a"\nimport "b"\nz = 3\n')
        mods, unresolved = sb.collect_modules(entry, [self.t.tmp])
        names = list(mods.values())
        # b must come before a, and entry must be last
        self.assertEqual(names[-1], "entry")
        self.assertLess(names.index("b"), names.index("a"))
        self.assertEqual(unresolved, {})

    def test_unresolved_imports(self):
        entry = self.t.write("entry.srv", 'import "ghost"\nx = 1\n')
        mods, unresolved = sb.collect_modules(entry, [self.t.tmp])
        self.assertEqual(len(mods), 1)
        self.assertEqual(list(unresolved.values()), ["ghost"])

    def test_exclude_skips_module(self):
        self.t.write("skip.srv", "x = 1\n")
        entry = self.t.write("entry.srv", 'import "skip"\ny = 2\n')
        mods, unresolved = sb.collect_modules(entry, [self.t.tmp], exclude=["skip"])
        self.assertEqual(list(mods.values()), ["entry"])
        self.assertEqual(unresolved, {})

    def test_circular_dependency_does_not_loop(self):
        # a imports b; b imports a -- both should appear once
        self.t.write("a.srv", 'import "b"\nx = 1\n')
        self.t.write("b.srv", 'import "a"\ny = 2\n')
        mods, _ = sb.collect_modules(os.path.join(self.t.tmp, "a.srv"), [self.t.tmp])
        # Both modules collected exactly once
        names = sorted(mods.values())
        self.assertEqual(names, ["a", "b"])

    def test_diamond_visits_shared_dep_once(self):
        self.t.write("d.srv", "x = 1\n")
        self.t.write("b.srv", 'import "d"\n')
        self.t.write("c.srv", 'import "d"\n')
        entry = self.t.write("a.srv", 'import "b"\nimport "c"\n')
        mods, _ = sb.collect_modules(entry, [self.t.tmp])
        names = list(mods.values())
        self.assertEqual(names.count("d"), 1)
        # d before b and c
        self.assertLess(names.index("d"), names.index("b"))
        self.assertLess(names.index("d"), names.index("c"))


class TestBundle(unittest.TestCase):
    def setUp(self):
        self.t = _TmpTree()

    def tearDown(self):
        self.t.cleanup()

    def test_bundle_single_file(self):
        entry = self.t.write("entry.srv", "x = 1\nprint x\n")
        result, stats = sb.bundle(entry)
        self.assertIn("x = 1", result)
        self.assertIn("print x", result)
        self.assertEqual(stats["module_count"], 1)
        self.assertEqual(stats["imports_removed"], 0)

    def test_bundle_strips_imports(self):
        self.t.write("dep.srv", "helper = 1\n")
        entry = self.t.write("entry.srv", 'import "dep"\nuse helper\n')
        result, stats = sb.bundle(entry)
        self.assertNotIn('import "dep"', result)
        self.assertIn("helper = 1", result)
        self.assertIn("use helper", result)
        self.assertEqual(stats["imports_removed"], 1)
        self.assertEqual(stats["module_count"], 2)

    def test_bundle_minify(self):
        entry = self.t.write("entry.srv", "# top\n\nx = 1\n# inline\n\n")
        result, stats = sb.bundle(entry, do_minify=True)
        self.assertNotIn("# top", result)
        self.assertNotIn("# inline", result)
        self.assertIn("x = 1", result)
        self.assertTrue(stats["minified"])

    def test_bundle_banner(self):
        entry = self.t.write("entry.srv", "x = 1\n")
        result, _ = sb.bundle(entry, banner="My App v2")
        self.assertTrue(result.startswith("# My App v2\n"))
        self.assertIn(f"sauravbundle v{sb.__version__}", result)

    def test_bundle_includes_module_separator(self):
        self.t.write("dep.srv", "y = 2\n")
        entry = self.t.write("entry.srv", 'import "dep"\nx = 1\n')
        result, _ = sb.bundle(entry)
        self.assertIn("# ── Module: dep", result)
        self.assertIn("# ── Entry: entry", result)

    def test_bundle_missing_entry_raises(self):
        with self.assertRaises(FileNotFoundError):
            sb.bundle("/no/such.srv")

    def test_bundle_order_dep_before_entry(self):
        self.t.write("dep.srv", "DEP_MARKER = 1\n")
        entry = self.t.write("entry.srv", 'import "dep"\nENTRY_MARKER = 1\n')
        result, _ = sb.bundle(entry)
        self.assertLess(result.index("DEP_MARKER"), result.index("ENTRY_MARKER"))

    def test_bundle_module_stats_marks_entry(self):
        self.t.write("dep.srv", "y = 2\n")
        entry = self.t.write("entry.srv", 'import "dep"\nx = 1\n')
        _, stats = sb.bundle(entry)
        entries = [m for m in stats["modules"] if m["is_entry"]]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["module"], "entry")


class TestDependencyTree(unittest.TestCase):
    def setUp(self):
        self.t = _TmpTree()

    def tearDown(self):
        self.t.cleanup()

    def test_tree_shows_children(self):
        self.t.write("a.srv", "x = 1\n")
        self.t.write("b.srv", "y = 2\n")
        entry = self.t.write("e.srv", 'import "a"\nimport "b"\n')
        tree = sb.build_dependency_tree(entry, [self.t.tmp])
        joined = "\n".join(tree)
        self.assertIn("e.srv", joined)
        self.assertIn("a.srv", joined)
        self.assertIn("b.srv", joined)
        self.assertIn("└──", joined)

    def test_tree_marks_unresolved(self):
        entry = self.t.write("e.srv", 'import "ghost"\n')
        tree = sb.build_dependency_tree(entry, [self.t.tmp])
        self.assertTrue(any("(unresolved)" in ln for ln in tree))

    def test_tree_marks_circular(self):
        self.t.write("a.srv", 'import "b"\n')
        self.t.write("b.srv", 'import "a"\n')
        tree = sb.build_dependency_tree(os.path.join(self.t.tmp, "a.srv"), [self.t.tmp])
        self.assertTrue(any("(circular)" in ln for ln in tree))


class TestFormatStats(unittest.TestCase):
    def test_format_stats_renders_all_sections(self):
        stats = {
            "entry": "/path/to/entry.srv",
            "module_count": 2,
            "total_lines": 10,
            "imports_removed": 1,
            "unresolved": {"foo.srv:3": "ghost"},
            "modules": [
                {"module": "dep", "path": "/p/dep.srv", "original_lines": 5,
                 "bundled_lines": 5, "imports_removed": 0, "is_entry": False},
                {"module": "entry", "path": "/p/entry.srv", "original_lines": 6,
                 "bundled_lines": 5, "imports_removed": 1, "is_entry": True},
            ],
            "minified": False,
            "banner": "X",
        }
        out = sb.format_stats(stats)
        self.assertIn("Bundle Statistics", out)
        self.assertIn("Modules bundled:  2", out)
        self.assertIn("dep:", out)
        self.assertIn("entry (entry)", out)
        self.assertIn("Unresolved imports", out)
        self.assertIn("ghost", out)
        self.assertIn("Banner:", out)


class TestMainCli(unittest.TestCase):
    def setUp(self):
        self.t = _TmpTree()

    def tearDown(self):
        self.t.cleanup()

    def _run(self, argv):
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            rc = sb.main(argv)
        return rc, buf_out.getvalue(), buf_err.getvalue()

    def test_missing_entry_exits_1(self):
        rc, _, err = self._run(["/no/such/file.srv"])
        self.assertEqual(rc, 1)
        self.assertIn("not found", err)

    def test_basic_bundle_to_stdout(self):
        entry = self.t.write("e.srv", "x = 1\n")
        rc, out, _ = self._run([entry])
        self.assertEqual(rc, 0)
        self.assertIn("x = 1", out)

    def test_output_file(self):
        entry = self.t.write("e.srv", "x = 1\n")
        out_path = os.path.join(self.t.tmp, "bundle.srv")
        rc, out, _ = self._run([entry, "-o", out_path])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(out_path))
        with open(out_path) as f:
            self.assertIn("x = 1", f.read())
        self.assertIn("Bundled", out)

    def test_tree_flag(self):
        entry = self.t.write("e.srv", "x = 1\n")
        rc, out, _ = self._run([entry, "--tree"])
        self.assertEqual(rc, 0)
        self.assertIn("e.srv", out)

    def test_dry_run(self):
        self.t.write("dep.srv", "y = 2\n")
        entry = self.t.write("e.srv", 'import "dep"\nx = 1\n')
        rc, out, _ = self._run([entry, "--dry-run"])
        self.assertEqual(rc, 0)
        self.assertIn("Would bundle", out)
        self.assertIn("dep", out)

    def test_stats_flag(self):
        entry = self.t.write("e.srv", "x = 1\n")
        rc, out, _ = self._run([entry, "--stats"])
        self.assertEqual(rc, 0)
        self.assertIn("Bundle Statistics", out)
        # When --stats only, bundled source not printed
        self.assertNotIn("x = 1\n\n# ", out)

    def test_json_flag_is_valid_json(self):
        entry = self.t.write("e.srv", "x = 1\n")
        rc, out, _ = self._run([entry, "--json"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(data["module_count"], 1)
        self.assertIn("modules", data)

    def test_exclude_flag(self):
        self.t.write("skip.srv", "SKIPME = 1\n")
        entry = self.t.write("e.srv", 'import "skip"\nx = 1\n')
        out_path = os.path.join(self.t.tmp, "bundle.srv")
        rc, _, _ = self._run([entry, "--exclude", "skip", "-o", out_path])
        self.assertEqual(rc, 0)
        with open(out_path) as f:
            content = f.read()
        self.assertNotIn("SKIPME", content)

    def test_include_dir(self):
        # Place dep in a separate dir; resolve via -I
        other = tempfile.mkdtemp(prefix="srvbundle_extra_")
        try:
            with open(os.path.join(other, "ext.srv"), "w") as f:
                f.write("EXT = 1\n")
            entry = self.t.write("e.srv", 'import "ext"\nx = 1\n')
            out_path = os.path.join(self.t.tmp, "bundle.srv")
            rc, _, _ = self._run([entry, "-I", other, "-o", out_path])
            self.assertEqual(rc, 0)
            with open(out_path) as f:
                self.assertIn("EXT = 1", f.read())
        finally:
            import shutil
            shutil.rmtree(other, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
