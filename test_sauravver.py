#!/usr/bin/env python3
"""Tests for sauravver — version & release management CLI."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sauravver import SemVer, Commit, CONVENTIONAL_RE, main, compare_versions, suggest_next, \
    find_version_file, generate_changelog_md, generate_changelog_json, generate_changelog_text


class TestSemVerParse(unittest.TestCase):
    def test_basic(self):
        v = SemVer.parse("1.2.3")
        self.assertEqual(v.major, 1)
        self.assertEqual(v.minor, 2)
        self.assertEqual(v.patch, 3)
        self.assertIsNone(v.pre)

    def test_with_v_prefix(self):
        v = SemVer.parse("v2.0.0")
        self.assertEqual(v.major, 2)

    def test_prerelease(self):
        v = SemVer.parse("1.0.0-alpha.1")
        self.assertEqual(v.pre, "alpha.1")

    def test_build_meta(self):
        v = SemVer.parse("1.0.0+build.123")
        self.assertEqual(v.build, "build.123")

    def test_full(self):
        v = SemVer.parse("3.2.1-beta.2+sha.abc")
        self.assertEqual(str(v), "3.2.1-beta.2+sha.abc")

    def test_invalid(self):
        with self.assertRaises(ValueError):
            SemVer.parse("not-a-version")

    def test_invalid_partial(self):
        with self.assertRaises(ValueError):
            SemVer.parse("1.2")

    def test_str(self):
        self.assertEqual(str(SemVer(1, 2, 3)), "1.2.3")
        self.assertEqual(str(SemVer(1, 0, 0, "rc.1")), "1.0.0-rc.1")


class TestSemVerBump(unittest.TestCase):
    def test_major(self):
        v = SemVer(1, 2, 3).bump("major")
        self.assertEqual(str(v), "2.0.0")

    def test_minor(self):
        v = SemVer(1, 2, 3).bump("minor")
        self.assertEqual(str(v), "1.3.0")

    def test_patch(self):
        v = SemVer(1, 2, 3).bump("patch")
        self.assertEqual(str(v), "1.2.4")

    def test_prerelease_new(self):
        v = SemVer(1, 2, 3).bump("prerelease")
        self.assertEqual(str(v), "1.2.4-alpha.0")

    def test_prerelease_increment(self):
        v = SemVer(1, 2, 4, "alpha.0").bump("prerelease")
        self.assertEqual(str(v), "1.2.4-alpha.1")

    def test_prerelease_custom_tag(self):
        v = SemVer(1, 0, 0).bump("prerelease", "beta")
        self.assertEqual(str(v), "1.0.1-beta.0")

    def test_unknown_kind(self):
        with self.assertRaises(ValueError):
            SemVer(1, 0, 0).bump("unknown")


class TestSemVerCompare(unittest.TestCase):
    def test_less_than(self):
        self.assertTrue(SemVer(1, 0, 0) < SemVer(2, 0, 0))
        self.assertTrue(SemVer(1, 0, 0) < SemVer(1, 1, 0))
        self.assertTrue(SemVer(1, 0, 0) < SemVer(1, 0, 1))

    def test_equal(self):
        self.assertEqual(SemVer(1, 2, 3), SemVer(1, 2, 3))

    def test_prerelease_lower(self):
        self.assertTrue(SemVer(1, 0, 0, "alpha") < SemVer(1, 0, 0))

    def test_gt(self):
        self.assertTrue(SemVer(2, 0, 0) > SemVer(1, 0, 0))


class TestConventionalCommit(unittest.TestCase):
    def test_feat(self):
        m = CONVENTIONAL_RE.match("feat: add new feature")
        self.assertIsNotNone(m)
        self.assertEqual(m.group('type'), 'feat')

    def test_fix_with_scope(self):
        m = CONVENTIONAL_RE.match("fix(parser): handle edge case")
        self.assertEqual(m.group('scope'), 'parser')

    def test_breaking(self):
        m = CONVENTIONAL_RE.match("feat!: breaking change")
        self.assertTrue(m.group('breaking'))

    def test_non_conventional(self):
        m = CONVENTIONAL_RE.match("random commit message")
        self.assertIsNone(m)


class TestCommitParsing(unittest.TestCase):
    def test_conventional(self):
        c = Commit.from_git_line("abc1234567", "feat(cli): add version command", "Alice", "2026-01-01")
        self.assertEqual(c.type, "feat")
        self.assertEqual(c.scope, "cli")
        self.assertEqual(c.description, "add version command")

    def test_non_conventional(self):
        c = Commit.from_git_line("def7890123", "update readme", "Bob", "2026-01-02")
        self.assertEqual(c.type, "other")
        self.assertEqual(c.description, "update readme")

    def test_breaking_commit(self):
        c = Commit.from_git_line("aaa1111111", "feat!: remove old API", "Eve", "2026-03-01")
        self.assertTrue(c.breaking)


class TestChangelog(unittest.TestCase):
    def _make_commits(self):
        return [
            Commit("a" * 40, "a" * 7, "feat", "cli", "add version cmd", "", False, "A", "2026-01-01", ""),
            Commit("b" * 40, "b" * 7, "fix", None, "fix crash", "", False, "B", "2026-01-02", ""),
            Commit("c" * 40, "c" * 7, "feat", None, "new feature", "", True, "C", "2026-01-03", ""),
        ]

    def test_md(self):
        md = generate_changelog_md(self._make_commits(), "1.0.0", "2026-01-03")
        self.assertIn("[1.0.0]", md)
        self.assertIn("Features", md)
        self.assertIn("Bug Fixes", md)
        self.assertIn("Breaking", md)

    def test_json(self):
        j = generate_changelog_json(self._make_commits(), "1.0.0", "2026-01-03")
        data = json.loads(j)
        self.assertEqual(data["version"], "1.0.0")
        self.assertEqual(data["stats"]["total"], 3)
        self.assertEqual(data["stats"]["breaking"], 1)

    def test_text(self):
        t = generate_changelog_text(self._make_commits(), "1.0.0", "2026-01-03")
        self.assertIn("1.0.0", t)
        self.assertIn("Total: 3", t)

    def test_empty_commits(self):
        md = generate_changelog_md([], "0.0.1")
        self.assertIn("[0.0.1]", md)


class TestCompareVersions(unittest.TestCase):
    def test_older(self):
        r = compare_versions("1.0.0", "2.0.0")
        self.assertIn("older", r["relationship"])
        self.assertFalse(r["compatible"])

    def test_equal(self):
        r = compare_versions("1.2.3", "1.2.3")
        self.assertIn("equal", r["relationship"])

    def test_newer(self):
        r = compare_versions("3.0.0", "1.0.0")
        self.assertIn("newer", r["relationship"])

    def test_compatible(self):
        r = compare_versions("1.0.0", "1.5.0")
        self.assertTrue(r["compatible"])


class TestSuggestNext(unittest.TestCase):
    def test_breaking(self):
        c = [Commit("a" * 40, "a" * 7, "feat", None, "x", "", True, "", "", "")]
        v, reason = suggest_next(SemVer(1, 0, 0), c)
        self.assertEqual(str(v), "2.0.0")
        self.assertIn("major", reason)

    def test_feat(self):
        c = [Commit("a" * 40, "a" * 7, "feat", None, "x", "", False, "", "", "")]
        v, _ = suggest_next(SemVer(1, 0, 0), c)
        self.assertEqual(str(v), "1.1.0")

    def test_fix(self):
        c = [Commit("a" * 40, "a" * 7, "fix", None, "x", "", False, "", "", "")]
        v, _ = suggest_next(SemVer(1, 0, 0), c)
        self.assertEqual(str(v), "1.0.1")

    def test_no_commits(self):
        v, reason = suggest_next(SemVer(1, 0, 0), [])
        self.assertEqual(str(v), "1.0.0")
        self.assertIn("no changes", reason)


class TestFindVersionFile(unittest.TestCase):
    def test_pyproject(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "pyproject.toml"), "w") as f:
                f.write('[project]\nversion = "1.2.3"\n')
            result = find_version_file(d)
            self.assertIsNotNone(result)
            self.assertEqual(result[1], "1.2.3")

    def test_version_file(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "VERSION"), "w") as f:
                f.write("2.0.0\n")
            result = find_version_file(d)
            self.assertIsNotNone(result)
            self.assertEqual(result[1], "2.0.0")

    def test_package_json(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "package.json"), "w") as f:
                f.write('{"name":"test","version":"3.1.0"}')
            result = find_version_file(d)
            self.assertIsNotNone(result)
            self.assertEqual(result[1], "3.1.0")

    def test_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "my_ver.txt"), "w") as f:
                f.write("5.0.0\n")
            result = find_version_file(d, "my_ver.txt")
            self.assertIsNotNone(result)
            self.assertEqual(result[1], "5.0.0")

    def test_not_found(self):
        with tempfile.TemporaryDirectory() as d:
            result = find_version_file(d)
            self.assertIsNone(result)


class TestCLI(unittest.TestCase):
    def test_validate_valid(self):
        rc = main(["validate", "1.2.3"])
        self.assertEqual(rc, 0)

    def test_validate_invalid(self):
        rc = main(["validate", "nope"])
        self.assertEqual(rc, 1)

    def test_compare(self):
        rc = main(["compare", "1.0.0", "2.0.0"])
        self.assertEqual(rc, 0)

    def test_compare_json(self):
        rc = main(["--json", "compare", "1.0.0", "2.0.0"])
        self.assertEqual(rc, 0)

    def test_show_in_project(self):
        rc = main(["--dir", os.path.dirname(os.path.abspath(__file__)), "show"])
        # Should find pyproject.toml
        self.assertEqual(rc, 0)

    def test_no_command(self):
        rc = main([])
        self.assertEqual(rc, 0)

    def test_validate_prerelease(self):
        rc = main(["validate", "1.0.0-beta.3"])
        self.assertEqual(rc, 0)

    def test_validate_build(self):
        rc = main(["validate", "1.0.0+build.42"])
        self.assertEqual(rc, 0)

    def test_bump_dry_run(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "VERSION"), "w") as f:
                f.write("1.0.0\n")
            rc = main(["--dir", d, "bump", "minor", "--dry-run"])
            self.assertEqual(rc, 0)
            # Version unchanged
            self.assertEqual(open(os.path.join(d, "VERSION")).read().strip(), "1.0.0")

    def test_bump_writes(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "VERSION"), "w") as f:
                f.write("1.0.0\n")
            rc = main(["--dir", d, "bump", "patch"])
            self.assertEqual(rc, 0)
            self.assertEqual(open(os.path.join(d, "VERSION")).read().strip(), "1.0.1")

    def test_set_version(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "VERSION"), "w") as f:
                f.write("1.0.0\n")
            rc = main(["--dir", d, "set", "3.0.0"])
            self.assertEqual(rc, 0)
            self.assertEqual(open(os.path.join(d, "VERSION")).read().strip(), "3.0.0")

    def test_set_invalid(self):
        rc = main(["set", "nope"])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
