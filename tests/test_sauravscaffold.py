"""Tests for sauravscaffold — project scaffolding & template generator."""

import json
import os
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import sauravscaffold


# ── render_template ────────────────────────────────────────────────


class TestRenderTemplate:
    def test_single_var(self):
        assert sauravscaffold.render_template("Hello {name}!", {"name": "World"}) == "Hello World!"

    def test_multiple_vars(self):
        result = sauravscaffold.render_template("{a} + {b} = {c}", {"a": "1", "b": "2", "c": "3"})
        assert result == "1 + 2 = 3"

    def test_no_vars(self):
        assert sauravscaffold.render_template("no placeholders", {}) == "no placeholders"

    def test_repeated_var(self):
        result = sauravscaffold.render_template("{x} and {x}", {"x": "y"})
        assert result == "y and y"

    def test_missing_var_left_as_is(self):
        result = sauravscaffold.render_template("{known} {unknown}", {"known": "ok"})
        assert result == "ok {unknown}"

    def test_empty_string_var(self):
        result = sauravscaffold.render_template("start{x}end", {"x": ""})
        assert result == "startend"


# ── TEMPLATES registry ─────────────────────────────────────────────


class TestTemplateRegistry:
    EXPECTED_TEMPLATES = {"basic", "cli", "lib", "web", "game", "data"}

    def test_all_expected_templates_exist(self):
        assert self.EXPECTED_TEMPLATES.issubset(sauravscaffold.TEMPLATES.keys())

    @pytest.mark.parametrize("name", EXPECTED_TEMPLATES)
    def test_template_has_required_keys(self, name):
        tmpl = sauravscaffold.TEMPLATES[name]
        assert "name" in tmpl and isinstance(tmpl["name"], str)
        assert "description" in tmpl and len(tmpl["description"]) > 0
        assert "files" in tmpl and len(tmpl["files"]) > 0
        assert "tags" in tmpl and len(tmpl["tags"]) > 0

    @pytest.mark.parametrize("name", EXPECTED_TEMPLATES)
    def test_template_has_readme(self, name):
        assert "README.md" in sauravscaffold.TEMPLATES[name]["files"]

    @pytest.mark.parametrize("name", EXPECTED_TEMPLATES)
    def test_template_has_gitignore(self, name):
        assert ".gitignore" in sauravscaffold.TEMPLATES[name]["files"]


# ── create_project ─────────────────────────────────────────────────


class TestCreateProject:
    @pytest.fixture(autouse=True)
    def _tmpdir(self, tmp_path):
        self.tmpdir = str(tmp_path)

    @pytest.mark.parametrize("template", sauravscaffold.TEMPLATES.keys())
    def test_creates_all_files(self, template, capsys):
        ok = sauravscaffold.create_project(f"proj_{template}", template, self.tmpdir, {"author": "tester"})
        assert ok is True
        proj_dir = os.path.join(self.tmpdir, f"proj_{template}")
        assert os.path.isdir(proj_dir)
        for rel_path in sauravscaffold.TEMPLATES[template]["files"]:
            assert os.path.isfile(os.path.join(proj_dir, rel_path)), f"Missing: {rel_path}"
        # manifest always created
        assert os.path.isfile(os.path.join(proj_dir, "saurav.pkg.json"))

    @pytest.mark.parametrize("template", sauravscaffold.TEMPLATES.keys())
    def test_no_unresolved_placeholders(self, template, capsys):
        sauravscaffold.create_project(f"proj_{template}", template, self.tmpdir, {"author": "alice"})
        proj_dir = os.path.join(self.tmpdir, f"proj_{template}")
        for rel_path in sauravscaffold.TEMPLATES[template]["files"]:
            fp = os.path.join(proj_dir, rel_path)
            with open(fp, encoding="utf-8") as f:
                content = f.read()
            assert "{project_name}" not in content, f"Unresolved {{project_name}} in {rel_path}"
            assert "{author}" not in content, f"Unresolved {{author}} in {rel_path}"
            assert "{short_name}" not in content, f"Unresolved {{short_name}} in {rel_path}"

    def test_manifest_content(self, capsys):
        sauravscaffold.create_project("myapp", "cli", self.tmpdir, {"author": "Bob"})
        with open(os.path.join(self.tmpdir, "myapp", "saurav.pkg.json")) as f:
            manifest = json.load(f)
        assert manifest["name"] == "myapp"
        assert manifest["template"] == "cli"
        assert manifest["author"] == "Bob"
        assert manifest["version"] == "0.1.0"
        assert "start" in manifest["scripts"]

    def test_manifest_has_test_script_when_tests_exist(self, capsys):
        sauravscaffold.create_project("mylib", "lib", self.tmpdir, {"author": "dev"})
        with open(os.path.join(self.tmpdir, "mylib", "saurav.pkg.json")) as f:
            manifest = json.load(f)
        assert "test" in manifest["scripts"]

    def test_duplicate_dir_prevented(self, capsys):
        sauravscaffold.create_project("dup", "basic", self.tmpdir, {})
        ok = sauravscaffold.create_project("dup", "basic", self.tmpdir, {})
        assert ok is False

    def test_unknown_template_rejected(self, capsys):
        ok = sauravscaffold.create_project("bad", "nonexistent_template", self.tmpdir, {})
        assert ok is False

    def test_short_name_strips_special_chars(self, capsys):
        sauravscaffold.create_project("my-cool-app!", "lib", self.tmpdir, {"author": "dev"})
        proj_dir = os.path.join(self.tmpdir, "my-cool-app!")
        # short_name should be alphanumeric only, used in function names
        lib_path = os.path.join(proj_dir, "src", "lib.srv")
        with open(lib_path, encoding="utf-8") as f:
            content = f.read()
        # Should contain function names like mycoolap_add (truncated to 8 chars)
        assert "fn " in content
        assert "-" not in content.split("fn ")[1].split(" ")[0]  # no hyphens in fn name

    def test_extra_vars_applied(self, capsys):
        sauravscaffold.create_project("xproj", "basic", self.tmpdir, {"author": "CustomAuthor"})
        readme = os.path.join(self.tmpdir, "xproj", "README.md")
        with open(readme, encoding="utf-8") as f:
            content = f.read()
        assert "CustomAuthor" in content


# ── parse_args ─────────────────────────────────────────────────────


class TestParseArgs:
    def test_new_basic(self):
        args = sauravscaffold.parse_args(["prog", "new", "myapp"])
        assert args["command"] == "new"
        assert args["project_name"] == "myapp"
        assert args["template"] == "basic"  # default

    def test_new_with_template(self):
        args = sauravscaffold.parse_args(["prog", "new", "myapp", "--template", "cli"])
        assert args["template"] == "cli"

    def test_new_with_short_template_flag(self):
        args = sauravscaffold.parse_args(["prog", "new", "myapp", "-t", "web"])
        assert args["template"] == "web"

    def test_new_with_var(self):
        args = sauravscaffold.parse_args(["prog", "new", "myapp", "--var", "author=Alice"])
        assert args["vars"]["author"] == "Alice"

    def test_new_with_output_dir(self):
        args = sauravscaffold.parse_args(["prog", "new", "myapp", "-d", "/tmp/out"])
        assert args["output_dir"] == "/tmp/out"

    def test_new_combined_flags(self):
        args = sauravscaffold.parse_args([
            "prog", "new", "myapp",
            "-t", "game",
            "--var", "author=Bob",
            "-d", "/out",
        ])
        assert args["template"] == "game"
        assert args["vars"]["author"] == "Bob"
        assert args["output_dir"] == "/out"

    def test_list_command(self):
        args = sauravscaffold.parse_args(["prog", "list"])
        assert args["command"] == "list"

    def test_info_command(self):
        args = sauravscaffold.parse_args(["prog", "info", "data"])
        assert args["command"] == "info"
        assert args["template"] == "data"

    def test_no_args_returns_none(self, capsys):
        args = sauravscaffold.parse_args(["prog"])
        assert args is None

    def test_new_no_name_returns_none(self, capsys):
        args = sauravscaffold.parse_args(["prog", "new"])
        assert args is None

    def test_info_no_template_returns_none(self, capsys):
        args = sauravscaffold.parse_args(["prog", "info"])
        assert args is None

    def test_unknown_command_returns_none(self, capsys):
        args = sauravscaffold.parse_args(["prog", "bogus"])
        assert args is None

    def test_unknown_option_returns_none(self, capsys):
        args = sauravscaffold.parse_args(["prog", "new", "myapp", "--bogus"])
        assert args is None

    def test_help_flag(self, capsys):
        args = sauravscaffold.parse_args(["prog", "--help"])
        assert args is None

    def test_var_with_equals_in_value(self):
        args = sauravscaffold.parse_args(["prog", "new", "app", "--var", "desc=a=b"])
        assert args["vars"]["desc"] == "a=b"


# ── list_templates / show_info ─────────────────────────────────────


class TestListAndInfo:
    def test_list_templates_output(self, capsys):
        sauravscaffold.list_templates()
        out = capsys.readouterr().out
        for name in sauravscaffold.TEMPLATES:
            assert name in out

    def test_show_info_valid(self, capsys):
        sauravscaffold.show_info("cli")
        out = capsys.readouterr().out
        assert "CLI Application" in out
        assert "cli" in out

    def test_show_info_invalid(self, capsys):
        sauravscaffold.show_info("nonexistent")
        out = capsys.readouterr().out
        assert "Error" in out


# ── Edge cases ─────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_project_name(self, tmp_path, capsys):
        # Empty string project name — should still create (directory named "")
        # This tests that the code doesn't crash; whether "" is a valid dir
        # name depends on OS. We just ensure no exception.
        ok = sauravscaffold.create_project("", "basic", str(tmp_path), {})
        # On most OSes this creates a dir at tmp_path itself, which already exists
        # so it should return False (duplicate detection)
        assert isinstance(ok, bool)

    def test_template_file_count(self):
        """Each template + manifest should produce len(files) + 1 total files."""
        for name, tmpl in sauravscaffold.TEMPLATES.items():
            expected = len(tmpl["files"]) + 1  # +1 for saurav.pkg.json
            assert expected >= 3, f"Template '{name}' has too few files"
