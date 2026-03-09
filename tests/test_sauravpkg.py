#!/usr/bin/env python3
"""Tests for sauravpkg -- package manager for sauravcode."""

import json
import os
import shutil
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sauravpkg import (
    parse_semver, semver_matches, find_best_version,
    default_manifest, load_manifest, save_manifest, validate_manifest,
    load_lockfile, save_lockfile,
    collect_files, pack_project, install_package, uninstall_package,
    list_installed, check_outdated, dependency_tree,
    LocalRegistry, sha256_file, sha256_bytes,
    MANIFEST_NAME, LOCK_NAME, PKG_DIR,
    cmd_init, cmd_validate,
    build_parser, main,
)


class TestSemver(unittest.TestCase):
    def test_parse_basic(self):
        self.assertEqual(parse_semver("1.2.3"), (1, 2, 3))

    def test_parse_v_prefix(self):
        self.assertEqual(parse_semver("v2.0.1"), (2, 0, 1))

    def test_parse_partial(self):
        self.assertEqual(parse_semver("1.2"), (1, 2, 0))
        self.assertEqual(parse_semver("3"), (3, 0, 0))

    def test_caret_match(self):
        self.assertTrue(semver_matches("1.2.3", "^1.0.0"))
        self.assertTrue(semver_matches("1.9.9", "^1.0.0"))
        self.assertFalse(semver_matches("2.0.0", "^1.0.0"))
        self.assertFalse(semver_matches("0.9.0", "^1.0.0"))

    def test_tilde_match(self):
        self.assertTrue(semver_matches("1.2.5", "~1.2.3"))
        self.assertTrue(semver_matches("1.2.3", "~1.2.3"))
        self.assertFalse(semver_matches("1.3.0", "~1.2.3"))
        self.assertFalse(semver_matches("1.2.2", "~1.2.3"))

    def test_gte_match(self):
        self.assertTrue(semver_matches("2.0.0", ">=1.0.0"))
        self.assertTrue(semver_matches("1.0.0", ">=1.0.0"))
        self.assertFalse(semver_matches("0.9.9", ">=1.0.0"))

    def test_lt_match(self):
        self.assertTrue(semver_matches("0.9.0", "<1.0.0"))
        self.assertFalse(semver_matches("1.0.0", "<1.0.0"))

    def test_exact_match(self):
        self.assertTrue(semver_matches("1.2.3", "1.2.3"))
        self.assertFalse(semver_matches("1.2.4", "1.2.3"))

    def test_wildcard(self):
        self.assertTrue(semver_matches("9.9.9", "*"))
        self.assertTrue(semver_matches("0.0.1", "latest"))

    def test_find_best(self):
        versions = ["0.1.0", "0.2.0", "1.0.0", "1.1.0", "2.0.0"]
        self.assertEqual(find_best_version(versions, "^1.0.0"), "1.1.0")
        self.assertEqual(find_best_version(versions, "*"), "2.0.0")
        self.assertIsNone(find_best_version(versions, "^3.0.0"))

    def test_lte_match(self):
        self.assertTrue(semver_matches("1.0.0", "<=1.0.0"))
        self.assertTrue(semver_matches("0.5.0", "<=1.0.0"))
        self.assertFalse(semver_matches("1.0.1", "<=1.0.0"))

    def test_gt_match(self):
        self.assertTrue(semver_matches("1.0.1", ">1.0.0"))
        self.assertFalse(semver_matches("1.0.0", ">1.0.0"))


class TestManifest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_default_manifest(self):
        m = default_manifest("test_pkg")
        self.assertEqual(m["name"], "test_pkg")
        self.assertEqual(m["version"], "0.1.0")
        self.assertIn("dependencies", m)

    def test_save_load_roundtrip(self):
        m = default_manifest("roundtrip")
        m["description"] = "A test package"
        save_manifest(m, self.tmpdir)
        loaded = load_manifest(self.tmpdir)
        self.assertEqual(loaded["name"], "roundtrip")
        self.assertEqual(loaded["description"], "A test package")

    def test_load_missing(self):
        self.assertIsNone(load_manifest(self.tmpdir))

    def test_validate_valid(self):
        m = default_manifest("valid_pkg")
        issues = validate_manifest(m)
        self.assertEqual(len(issues), 0)

    def test_validate_missing_name(self):
        m = {"version": "1.0.0"}
        issues = validate_manifest(m)
        self.assertTrue(any("name" in i for i in issues))

    def test_validate_missing_version(self):
        m = {"name": "test"}
        issues = validate_manifest(m)
        self.assertTrue(any("version" in i for i in issues))

    def test_validate_bad_version(self):
        m = {"name": "test", "version": "abc"}
        issues = validate_manifest(m)
        self.assertTrue(any("semver" in i.lower() or "version" in i.lower() for i in issues))

    def test_validate_bad_name(self):
        m = {"name": "123-bad!", "version": "1.0.0"}
        issues = validate_manifest(m)
        self.assertTrue(any("name" in i.lower() for i in issues))

    def test_validate_bad_dependencies(self):
        m = {"name": "test", "version": "1.0.0", "dependencies": "not_a_dict"}
        issues = validate_manifest(m)
        self.assertTrue(any("dependencies" in i for i in issues))

    def test_validate_bad_files(self):
        m = {"name": "test", "version": "1.0.0", "files": "not_a_list"}
        issues = validate_manifest(m)
        self.assertTrue(any("files" in i for i in issues))

    def test_validate_bad_scripts(self):
        m = {"name": "test", "version": "1.0.0", "scripts": []}
        issues = validate_manifest(m)
        self.assertTrue(any("scripts" in i for i in issues))

    def test_validate_empty_name(self):
        m = {"name": "", "version": "1.0.0"}
        issues = validate_manifest(m)
        self.assertTrue(len(issues) > 0)


class TestLockfile(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_load_missing(self):
        lock = load_lockfile(self.tmpdir)
        self.assertEqual(lock, {"packages": {}})

    def test_save_load(self):
        data = {"packages": {"foo": {"version": "1.0.0"}}}
        save_lockfile(data, self.tmpdir)
        loaded = load_lockfile(self.tmpdir)
        self.assertEqual(loaded["packages"]["foo"]["version"], "1.0.0")


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reg_dir = os.path.join(self.tmpdir, "registry")
        self.proj_dir = os.path.join(self.tmpdir, "project")
        os.makedirs(self.proj_dir)
        self.registry = LocalRegistry(self.reg_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _create_package(self, name, version, files=None, deps=None):
        """Helper to create and publish a package."""
        pkg_dir = os.path.join(self.tmpdir, f"_build_{name}_{version}")
        os.makedirs(pkg_dir, exist_ok=True)

        manifest = default_manifest(name)
        manifest["version"] = version
        manifest["description"] = f"Test package {name}"
        manifest["author"] = "test"
        if deps:
            manifest["dependencies"] = deps
        save_manifest(manifest, pkg_dir)

        # Create .srv files
        for fname in (files or ["main.srv"]):
            with open(os.path.join(pkg_dir, fname), "w") as f:
                f.write(f'print "Hello from {name}@{version}"\n')

        result, error = pack_project(pkg_dir)
        self.assertIsNone(error)

        ok, msg = self.registry.publish(result["archive"], load_manifest(pkg_dir))
        self.assertTrue(ok)
        return pkg_dir

    def test_publish_and_search(self):
        self._create_package("math_utils", "1.0.0")
        results = self.registry.search("math")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "math_utils")

    def test_search_all(self):
        self._create_package("pkg_a", "1.0.0")
        self._create_package("pkg_b", "1.0.0")
        results = self.registry.search("")
        self.assertEqual(len(results), 2)

    def test_search_no_match(self):
        self._create_package("foo", "1.0.0")
        results = self.registry.search("zzz_nonexistent")
        self.assertEqual(len(results), 0)

    def test_info(self):
        self._create_package("mylib", "1.0.0")
        self._create_package("mylib", "1.1.0")
        info = self.registry.info("mylib")
        self.assertEqual(info["name"], "mylib")
        self.assertEqual(info["latest"], "1.1.0")
        self.assertIn("1.0.0", info["versions"])
        self.assertIn("1.1.0", info["versions"])

    def test_info_not_found(self):
        self.assertIsNone(self.registry.info("nonexistent"))

    def test_duplicate_publish(self):
        self._create_package("dup", "1.0.0")
        # Try to publish same version again
        pkg_dir = os.path.join(self.tmpdir, "_build_dup_dup")
        os.makedirs(pkg_dir, exist_ok=True)
        manifest = default_manifest("dup")
        manifest["version"] = "1.0.0"
        save_manifest(manifest, pkg_dir)
        with open(os.path.join(pkg_dir, "main.srv"), "w") as f:
            f.write('print "dup"\n')
        result, _ = pack_project(pkg_dir)
        ok, msg = self.registry.publish(result["archive"], load_manifest(pkg_dir))
        self.assertFalse(ok)
        self.assertIn("already published", msg)

    def test_get_versions(self):
        self._create_package("versioned", "1.0.0")
        self._create_package("versioned", "2.0.0")
        self._create_package("versioned", "1.5.0")
        versions = self.registry.get_versions("versioned")
        self.assertEqual(versions[0], "2.0.0")
        self.assertEqual(len(versions), 3)

    def test_get_versions_not_found(self):
        self.assertEqual(self.registry.get_versions("nope"), [])

    def test_get_archive_path(self):
        self._create_package("archtest", "1.0.0")
        path = self.registry.get_archive_path("archtest", "1.0.0")
        self.assertIsNotNone(path)
        self.assertTrue(path.exists())

    def test_get_archive_path_not_found(self):
        self.assertIsNone(self.registry.get_archive_path("nope", "1.0.0"))


class TestInstallUninstall(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reg_dir = os.path.join(self.tmpdir, "registry")
        self.proj_dir = os.path.join(self.tmpdir, "project")
        os.makedirs(self.proj_dir)
        self.registry = LocalRegistry(self.reg_dir)

        # Init project
        manifest = default_manifest("myproject")
        save_manifest(manifest, self.proj_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _publish(self, name, version, deps=None):
        pkg_dir = os.path.join(self.tmpdir, f"_b_{name}_{version}")
        os.makedirs(pkg_dir, exist_ok=True)
        m = default_manifest(name)
        m["version"] = version
        m["description"] = f"{name} lib"
        if deps:
            m["dependencies"] = deps
        save_manifest(m, pkg_dir)
        with open(os.path.join(pkg_dir, "main.srv"), "w") as f:
            f.write(f'print "{name}"\n')
        result, _ = pack_project(pkg_dir)
        self.registry.publish(result["archive"], load_manifest(pkg_dir))

    def test_install(self):
        self._publish("helpers", "1.0.0")
        ok, msg = install_package("helpers", "*", self.proj_dir, self.registry)
        self.assertTrue(ok)
        self.assertIn("1.0.0", msg)

        # Check files exist
        pkg_path = Path(self.proj_dir) / PKG_DIR / "helpers"
        self.assertTrue(pkg_path.exists())

    def test_install_specific_version(self):
        self._publish("lib", "1.0.0")
        self._publish("lib", "2.0.0")
        ok, _ = install_package("lib", "^1.0.0", self.proj_dir, self.registry)
        self.assertTrue(ok)
        lock = load_lockfile(self.proj_dir)
        self.assertEqual(lock["packages"]["lib"]["version"], "1.0.0")

    def test_install_not_found(self):
        ok, msg = install_package("nonexistent", "*", self.proj_dir, self.registry)
        self.assertFalse(ok)

    def test_install_no_matching_version(self):
        self._publish("v_test", "1.0.0")
        ok, msg = install_package("v_test", "^2.0.0", self.proj_dir, self.registry)
        self.assertFalse(ok)

    def test_uninstall(self):
        self._publish("removeme", "1.0.0")
        install_package("removeme", "*", self.proj_dir, self.registry)
        ok, msg = uninstall_package("removeme", self.proj_dir)
        self.assertTrue(ok)
        self.assertFalse((Path(self.proj_dir) / PKG_DIR / "removeme").exists())

    def test_uninstall_not_installed(self):
        ok, msg = uninstall_package("nope", self.proj_dir)
        self.assertFalse(ok)

    def test_list_installed(self):
        self._publish("a", "1.0.0")
        self._publish("b", "2.0.0")
        install_package("a", "*", self.proj_dir, self.registry)
        install_package("b", "*", self.proj_dir, self.registry)
        installed = list_installed(self.proj_dir)
        names = [p["name"] for p in installed]
        self.assertIn("a", names)
        self.assertIn("b", names)

    def test_list_empty(self):
        self.assertEqual(list_installed(self.proj_dir), [])

    def test_install_updates_manifest(self):
        self._publish("auto_dep", "1.0.0")
        install_package("auto_dep", "*", self.proj_dir, self.registry)
        m = load_manifest(self.proj_dir)
        self.assertIn("auto_dep", m["dependencies"])

    def test_transitive_deps(self):
        self._publish("base_lib", "1.0.0")
        self._publish("mid_lib", "1.0.0", deps={"base_lib": "^1.0.0"})
        ok, _ = install_package("mid_lib", "*", self.proj_dir, self.registry)
        self.assertTrue(ok)
        # base_lib should also be installed
        self.assertTrue((Path(self.proj_dir) / PKG_DIR / "base_lib").exists())


class TestPack(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_pack_success(self):
        m = default_manifest("packtest")
        save_manifest(m, self.tmpdir)
        with open(os.path.join(self.tmpdir, "main.srv"), "w") as f:
            f.write('print "hello"\n')
        result, error = pack_project(self.tmpdir)
        self.assertIsNone(error)
        self.assertEqual(result["name"], "packtest")
        self.assertTrue(os.path.exists(result["archive"]))

    def test_pack_no_manifest(self):
        result, error = pack_project(self.tmpdir)
        self.assertIsNone(result)
        self.assertIn("No", error)

    def test_pack_invalid_manifest(self):
        m = {"version": "1.0.0"}  # missing name
        save_manifest(m, self.tmpdir)
        result, error = pack_project(self.tmpdir)
        self.assertIsNone(result)
        self.assertIn("Invalid", error)

    def test_pack_checksum(self):
        m = default_manifest("chk")
        save_manifest(m, self.tmpdir)
        with open(os.path.join(self.tmpdir, "main.srv"), "w") as f:
            f.write('print "chk"\n')
        result, _ = pack_project(self.tmpdir)
        self.assertEqual(len(result["checksum"]), 64)


class TestOutdated(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reg_dir = os.path.join(self.tmpdir, "registry")
        self.proj_dir = os.path.join(self.tmpdir, "project")
        os.makedirs(self.proj_dir)
        self.registry = LocalRegistry(self.reg_dir)
        save_manifest(default_manifest("proj"), self.proj_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _publish(self, name, version):
        d = os.path.join(self.tmpdir, f"_b_{name}_{version}")
        os.makedirs(d, exist_ok=True)
        m = default_manifest(name)
        m["version"] = version
        save_manifest(m, d)
        with open(os.path.join(d, "main.srv"), "w") as f:
            f.write('x = 1\n')
        r, _ = pack_project(d)
        self.registry.publish(r["archive"], load_manifest(d))

    def test_outdated(self):
        self._publish("old", "1.0.0")
        install_package("old", "*", self.proj_dir, self.registry)
        self._publish("old", "2.0.0")
        outdated = check_outdated(self.proj_dir, self.registry)
        self.assertEqual(len(outdated), 1)
        self.assertEqual(outdated[0]["current"], "1.0.0")
        self.assertEqual(outdated[0]["latest"], "2.0.0")

    def test_not_outdated(self):
        self._publish("fresh", "1.0.0")
        install_package("fresh", "*", self.proj_dir, self.registry)
        outdated = check_outdated(self.proj_dir, self.registry)
        self.assertEqual(len(outdated), 0)


class TestDepTree(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proj_dir = os.path.join(self.tmpdir, "project")
        os.makedirs(self.proj_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_empty_tree(self):
        save_manifest(default_manifest("notree"), self.proj_dir)
        tree = dependency_tree(self.proj_dir)
        self.assertEqual(tree, {})

    def test_tree_with_deps(self):
        m = default_manifest("withdeps")
        m["dependencies"] = {"foo": "^1.0.0", "bar": "~2.0.0"}
        save_manifest(m, self.proj_dir)
        tree = dependency_tree(self.proj_dir)
        self.assertIn("foo", tree)
        self.assertIn("bar", tree)

    def test_no_manifest(self):
        tree = dependency_tree(self.proj_dir)
        self.assertEqual(tree, {})


class TestHash(unittest.TestCase):
    def test_sha256_bytes(self):
        h = sha256_bytes(b"hello")
        self.assertEqual(len(h), 64)

    def test_sha256_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"test content")
            f.flush()
            h = sha256_file(f.name)
        os.unlink(f.name)
        self.assertEqual(len(h), 64)


class TestCollectFiles(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_glob_srv(self):
        for name in ["a.srv", "b.srv", "c.txt"]:
            with open(os.path.join(self.tmpdir, name), "w") as f:
                f.write("x\n")
        files = collect_files(self.tmpdir, ["*.srv"])
        names = [str(f) for f in files]
        self.assertIn("a.srv", names)
        self.assertIn("b.srv", names)
        self.assertNotIn("c.txt", names)


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orig_dir = os.getcwd()
        os.chdir(self.tmpdir)

    def tearDown(self):
        os.chdir(self.orig_dir)
        shutil.rmtree(self.tmpdir)

    def test_init(self):
        ret = main(["init", "--name", "cli_test"])
        self.assertEqual(ret, 0)
        self.assertTrue(os.path.exists(MANIFEST_NAME))

    def test_init_force(self):
        main(["init", "--name", "first"])
        ret = main(["init", "--name", "second", "--force"])
        self.assertEqual(ret, 0)
        m = load_manifest(".")
        self.assertEqual(m["name"], "second")

    def test_init_no_overwrite(self):
        main(["init", "--name", "first"])
        ret = main(["init", "--name", "second"])
        self.assertEqual(ret, 1)

    def test_validate_valid(self):
        main(["init", "--name", "valid"])
        ret = main(["validate"])
        self.assertEqual(ret, 0)

    def test_validate_no_manifest(self):
        ret = main(["validate"])
        self.assertEqual(ret, 1)

    def test_list_empty(self):
        main(["init", "--name", "test"])
        ret = main(["list"])
        self.assertEqual(ret, 0)

    def test_deps_no_manifest(self):
        ret = main(["deps"])
        self.assertEqual(ret, 1)

    def test_pack_no_manifest(self):
        ret = main(["pack"])
        self.assertEqual(ret, 1)

    def test_run_no_manifest(self):
        ret = main(["run", "test"])
        self.assertEqual(ret, 1)

    def test_no_command(self):
        ret = main([])
        self.assertEqual(ret, 1)

    def test_search_empty_registry(self):
        reg_dir = os.path.join(self.tmpdir, "_reg")
        ret = main(["search", "foo", "--registry", reg_dir])
        self.assertEqual(ret, 0)

    def test_info_not_found(self):
        reg_dir = os.path.join(self.tmpdir, "_reg")
        ret = main(["info", "nonexistent", "--registry", reg_dir])
        self.assertEqual(ret, 1)

    def test_full_workflow(self):
        """End-to-end: init → pack → publish → search → install."""
        reg_dir = os.path.join(self.tmpdir, "_reg")

        # Create a library
        lib_dir = os.path.join(self.tmpdir, "mylib")
        os.makedirs(lib_dir)
        os.chdir(lib_dir)
        main(["init", "--name", "mylib", "--description", "A library"])
        with open("main.srv", "w") as f:
            f.write('function greet name\n  print f"Hello {name}"\n')
        main(["pack"])
        main(["publish", "--registry", reg_dir])

        # Create a project and install the library
        proj_dir = os.path.join(self.tmpdir, "myproj")
        os.makedirs(proj_dir)
        os.chdir(proj_dir)
        main(["init", "--name", "myproj"])
        ret = main(["install", "mylib", "--registry", reg_dir])
        self.assertEqual(ret, 0)

        # Verify
        installed = list_installed(".")
        self.assertEqual(len(installed), 1)
        self.assertEqual(installed[0]["name"], "mylib")


if __name__ == "__main__":
    unittest.main()
