#!/usr/bin/env python3
"""Tests for sauravsnippet — Code snippet manager."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from sauravsnippet import SnippetLibrary, main


class TestSnippetLibrary(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.lib = SnippetLibrary(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_and_get(self):
        self.lib.save("hello", 'print("hello")\n', tags=["demo"], description="A hello snippet")
        code = self.lib.get("hello")
        self.assertEqual(code, 'print("hello")\n')

    def test_save_duplicate_raises(self):
        self.lib.save("x", "code")
        with self.assertRaises(ValueError):
            self.lib.save("x", "code2")

    def test_get_missing_raises(self):
        with self.assertRaises(KeyError):
            self.lib.get("nope")

    def test_info(self):
        self.lib.save("a", "code\nline2", tags=["t1", "t2"], description="desc")
        info = self.lib.info("a")
        self.assertEqual(info["name"], "a")
        self.assertEqual(info["tags"], ["t1", "t2"])
        self.assertEqual(info["description"], "desc")
        self.assertEqual(info["lines"], 2)
        self.assertEqual(info["uses"], 0)

    def test_edit(self):
        self.lib.save("e", "old")
        self.lib.edit("e", "new\ncode\n")
        self.assertEqual(self.lib.get("e"), "new\ncode\n")
        self.assertEqual(self.lib.index["e"]["lines"], 2)

    def test_edit_missing_raises(self):
        with self.assertRaises(KeyError):
            self.lib.edit("nope", "x")

    def test_delete(self):
        self.lib.save("d", "code")
        self.lib.delete("d")
        with self.assertRaises(KeyError):
            self.lib.get("d")
        self.assertNotIn("d", self.lib.index)

    def test_rename(self):
        self.lib.save("old", "code", tags=["t"])
        self.lib.rename("old", "new")
        self.assertEqual(self.lib.get("new"), "code")
        with self.assertRaises(KeyError):
            self.lib.get("old")
        self.assertEqual(self.lib.info("new")["tags"], ["t"])

    def test_rename_conflict(self):
        self.lib.save("a", "1")
        self.lib.save("b", "2")
        with self.assertRaises(ValueError):
            self.lib.rename("a", "b")

    def test_duplicate(self):
        self.lib.save("src", "code", tags=["x"], description="d")
        self.lib.duplicate("src", "cpy")
        self.assertEqual(self.lib.get("cpy"), "code")
        self.assertEqual(self.lib.info("cpy")["tags"], ["x"])

    def test_add_remove_tags(self):
        self.lib.save("t", "c", tags=["a"])
        self.lib.add_tags("t", ["b", "c"])
        self.assertEqual(self.lib.info("t")["tags"], ["a", "b", "c"])
        self.lib.remove_tags("t", ["a", "c"])
        self.assertEqual(self.lib.info("t")["tags"], ["b"])

    def test_use_bumps_count(self):
        self.lib.save("u", "code")
        self.assertEqual(self.lib.info("u")["uses"], 0)
        code = self.lib.use("u")
        self.assertEqual(code, "code")
        self.assertEqual(self.lib.info("u")["uses"], 1)
        self.lib.use("u")
        self.assertEqual(self.lib.info("u")["uses"], 2)

    def test_list_all(self):
        self.lib.save("b", "2")
        self.lib.save("a", "1")
        items = self.lib.list_snippets()
        self.assertEqual([i["name"] for i in items], ["a", "b"])

    def test_list_filter_tag(self):
        self.lib.save("x", "1", tags=["py"])
        self.lib.save("y", "2", tags=["js"])
        items = self.lib.list_snippets(tag="py")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "x")

    def test_list_sort_uses(self):
        self.lib.save("a", "1")
        self.lib.save("b", "2")
        self.lib.use("b")
        self.lib.use("b")
        items = self.lib.list_snippets(sort_by="uses")
        self.assertEqual(items[0]["name"], "b")

    def test_search_by_name(self):
        self.lib.save("fizzbuzz", "code")
        results = self.lib.search("fizz")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "fizzbuzz")

    def test_search_by_tag(self):
        self.lib.save("x", "code", tags=["algorithm"])
        results = self.lib.search("algorithm")
        self.assertTrue(len(results) >= 1)

    def test_search_by_content(self):
        self.lib.save("x", 'function fib(n)\n  return n\n')
        results = self.lib.search("fib")
        self.assertTrue(len(results) >= 1)

    def test_search_no_match(self):
        self.lib.save("x", "code")
        results = self.lib.search("zzzzz")
        self.assertEqual(len(results), 0)

    def test_stats_empty(self):
        s = self.lib.stats()
        self.assertEqual(s["total"], 0)

    def test_stats(self):
        self.lib.save("a", "line1\nline2", tags=["t1"])
        self.lib.save("b", "line1", tags=["t1", "t2"])
        self.lib.use("a")
        s = self.lib.stats()
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["total_lines"], 3)
        self.assertEqual(s["total_uses"], 1)
        self.assertEqual(s["tags"]["t1"], 2)
        self.assertEqual(s["tags"]["t2"], 1)
        self.assertEqual(s["most_used"], "a")

    def test_export_json(self):
        self.lib.save("x", "code", tags=["t"])
        data = json.loads(self.lib.export_all("json"))
        self.assertIn("x", data)
        self.assertEqual(data["x"]["code"], "code")

    def test_export_srv(self):
        self.lib.save("x", "code", tags=["t"], description="desc")
        out = self.lib.export_all("srv")
        self.assertIn("# === Snippet: x ===", out)
        self.assertIn("# Tags: t", out)
        self.assertIn("code", out)

    def test_import_snippets(self):
        self.lib.save("a", "1")
        exported = self.lib.export_all("json")
        lib2 = SnippetLibrary(tempfile.mkdtemp())
        result = lib2.import_snippets(exported)
        self.assertEqual(result["imported"], 1)
        self.assertEqual(lib2.get("a"), "1")

    def test_import_skip_existing(self):
        self.lib.save("a", "1")
        exported = self.lib.export_all("json")
        result = self.lib.import_snippets(exported, overwrite=False)
        self.assertEqual(result["skipped"], 1)

    def test_import_overwrite(self):
        self.lib.save("a", "old")
        data = json.dumps({"a": {"code": "new", "tags": ["x"], "description": ""}})
        result = self.lib.import_snippets(data, overwrite=True)
        self.assertEqual(result["imported"], 1)
        self.assertEqual(self.lib.get("a"), "new")

    def test_persistence(self):
        self.lib.save("p", "code")
        lib2 = SnippetLibrary(self.tmpdir)
        self.assertEqual(lib2.get("p"), "code")


class TestCLI(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.srv_file = os.path.join(self.tmpdir, "test.srv")
        Path(self.srv_file).write_text('print("test")\n', encoding="utf-8")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_cli_save_and_get(self):
        import io
        from contextlib import redirect_stdout

        lib_dir = os.path.join(self.tmpdir, "lib")
        main(["--lib", lib_dir, "save", "t", self.srv_file, "--tags", "demo", "--desc", "test snippet"])

        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["--lib", lib_dir, "get", "t"])
        self.assertEqual(buf.getvalue(), 'print("test")\n')

    def test_cli_list(self):
        import io
        from contextlib import redirect_stdout

        lib_dir = os.path.join(self.tmpdir, "lib")
        main(["--lib", lib_dir, "save", "a", self.srv_file])
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["--lib", lib_dir, "list"])
        self.assertIn("a", buf.getvalue())

    def test_cli_stats_empty(self):
        import io
        from contextlib import redirect_stdout

        lib_dir = os.path.join(self.tmpdir, "lib")
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["--lib", lib_dir, "stats"])
        self.assertIn("Total snippets: 0", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
