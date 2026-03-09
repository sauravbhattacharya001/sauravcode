"""Tests for sauravgen -- code generator / scaffolder."""

import os
import sys
import shutil
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sauravgen


# ─── Template output tests ───────────────────────────────────────

class TestGenFunction:
    def test_basic(self):
        result = sauravgen.gen_function("add")
        assert "function add" in result
        assert "return 0" in result

    def test_with_args(self):
        result = sauravgen.gen_function("add", args=["x", "y"])
        assert "function add x y" in result
        assert "return x" in result

    def test_with_description(self):
        result = sauravgen.gen_function("calc", description="Calculate stuff")
        assert "Calculate stuff" in result

    def test_example_usage(self):
        result = sauravgen.gen_function("mul", args=["a", "b"])
        assert "result = mul 1 2" in result
        assert 'print f"Result: {result}"' in result

    def test_no_args_example(self):
        result = sauravgen.gen_function("noop")
        assert "result = noop" in result

    def test_header_comment(self):
        result = sauravgen.gen_function("foo")
        assert "# foo.srv" in result
        assert "sauravgen" in result

    def test_three_args(self):
        result = sauravgen.gen_function("f", args=["a", "b", "c"])
        assert "function f a b c" in result
        assert "result = f 1 2 3" in result


class TestGenClass:
    def test_basic(self):
        result = sauravgen.gen_class("Dog")
        assert "class Dog" in result
        assert "function init value" in result

    def test_fields(self):
        result = sauravgen.gen_class("Person", fields=["name", "age"])
        assert "function init name age" in result
        assert "self.name = name" in result
        assert "self.age = age" in result

    def test_tostring(self):
        result = sauravgen.gen_class("Box", fields=["w", "h"])
        assert "function toString" in result
        assert "Box(" in result

    def test_getters(self):
        result = sauravgen.gen_class("Item", fields=["price"])
        assert "function get_price" in result
        assert "return self.price" in result

    def test_setters(self):
        result = sauravgen.gen_class("Item", fields=["price"])
        assert "function set_price price" in result
        assert "self.price = price" in result

    def test_custom_methods(self):
        result = sauravgen.gen_class("Calc", fields=["x"], methods=["compute", "reset"])
        assert "function compute" in result
        assert "function reset" in result

    def test_example_usage_name_field(self):
        result = sauravgen.gen_class("Pet", fields=["name"])
        assert '"example"' in result

    def test_example_usage_age_field(self):
        result = sauravgen.gen_class("Pet", fields=["age"])
        assert "42" in result

    def test_example_usage_other(self):
        result = sauravgen.gen_class("X", fields=["foo"])
        assert '"foo_value"' in result


class TestGenEnum:
    def test_basic(self):
        result = sauravgen.gen_enum("Color")
        assert "enum Color" in result
        assert "A" in result

    def test_variants(self):
        result = sauravgen.gen_enum("Dir", variants=["North", "South", "East", "West"])
        assert "enum Dir" in result
        assert "    North" in result
        assert "    West" in result

    def test_match(self):
        result = sauravgen.gen_enum("Status", variants=["On", "Off"])
        assert "match value" in result
        assert "case Status.On" in result
        assert "case Status.Off" in result

    def test_example(self):
        result = sauravgen.gen_enum("X", variants=["A"])
        assert "value = X.A" in result


class TestGenTest:
    def test_basic(self):
        result = sauravgen.gen_test("math")
        assert "test_math" in result.split("\n")[0] or "Tests for math" in result

    def test_functions(self):
        result = sauravgen.gen_test("util", functions=["parse", "format"])
        assert "function test_parse_basic" in result
        assert "function test_format_basic" in result

    def test_edge_cases(self):
        result = sauravgen.gen_test("x", functions=["foo"])
        assert "test_foo_edge_case" in result

    def test_assertions(self):
        result = sauravgen.gen_test("y")
        assert "assert true" in result

    def test_run_comment(self):
        result = sauravgen.gen_test("abc")
        assert "sauravtest" in result

    def test_pass_message(self):
        result = sauravgen.gen_test("z")
        assert 'All z tests passed!' in result


class TestGenModule:
    def test_basic(self):
        result = sauravgen.gen_module("utils")
        assert "function helper x" in result
        assert "import utils" in result

    def test_functions(self):
        result = sauravgen.gen_module("math", functions=["add", "sub"])
        assert "function add x" in result
        assert "function sub x" in result

    def test_return(self):
        result = sauravgen.gen_module("m")
        assert "return x" in result


class TestGenScript:
    def test_basic(self):
        result = sauravgen.gen_script("deploy")
        assert "=== deploy ===" in result

    def test_args(self):
        result = sauravgen.gen_script("run", args=["env", "target"])
        assert 'env = "env_default"' in result
        assert 'target = "target_default"' in result
        assert "function run env target" in result

    def test_exit_code(self):
        result = sauravgen.gen_script("x")
        assert "exit code" in result


class TestGenProject:
    def test_returns_dict(self):
        result = sauravgen.gen_project("myapp")
        assert isinstance(result, dict)

    def test_has_main(self):
        result = sauravgen.gen_project("myapp")
        assert "myapp/main.srv" in result

    def test_has_lib(self):
        result = sauravgen.gen_project("myapp")
        assert "myapp/lib.srv" in result

    def test_has_tests(self):
        result = sauravgen.gen_project("myapp")
        assert "myapp/tests/test_lib.srv" in result

    def test_has_readme(self):
        result = sauravgen.gen_project("myapp")
        assert "myapp/README.md" in result

    def test_has_gitignore(self):
        result = sauravgen.gen_project("myapp")
        assert "myapp/.gitignore" in result

    def test_main_imports_lib(self):
        result = sauravgen.gen_project("foo")
        assert 'import "foo/lib"' in result["foo/main.srv"]

    def test_readme_has_usage(self):
        result = sauravgen.gen_project("bar")
        assert "python saurav.py bar/main.srv" in result["bar/README.md"]


# ─── Template registry tests ─────────────────────────────────────

class TestTemplateRegistry:
    def test_all_templates_exist(self):
        expected = {"function", "class", "enum", "test", "module", "script", "project"}
        assert set(sauravgen.TEMPLATES.keys()) == expected

    def test_all_have_description(self):
        for name, info in sauravgen.TEMPLATES.items():
            assert "description" in info, f"{name} missing description"

    def test_all_have_generator(self):
        for name, info in sauravgen.TEMPLATES.items():
            assert callable(info["generator"]), f"{name} generator not callable"

    def test_all_have_output_pattern(self):
        for name, info in sauravgen.TEMPLATES.items():
            assert "output_pattern" in info


# ─── File write tests ────────────────────────────────────────────

class TestWriteFile:
    def test_dry_run(self, capsys):
        result = sauravgen.write_file("/fake/path.srv", "content", dry_run=True)
        assert result is True
        captured = capsys.readouterr()
        assert "dry-run" in captured.out

    def test_creates_file(self, tmp_path):
        path = str(tmp_path / "out.srv")
        result = sauravgen.write_file(path, "hello\n")
        assert result is True
        assert os.path.exists(path)
        with open(path) as f:
            assert f.read() == "hello\n"

    def test_no_overwrite(self, tmp_path):
        path = str(tmp_path / "exists.srv")
        with open(path, "w") as f:
            f.write("old")
        result = sauravgen.write_file(path, "new")
        assert result is False
        with open(path) as f:
            assert f.read() == "old"

    def test_creates_dirs(self, tmp_path):
        path = str(tmp_path / "a" / "b" / "out.srv")
        result = sauravgen.write_file(path, "nested\n")
        assert result is True
        assert os.path.exists(path)


# ─── list_templates tests ────────────────────────────────────────

class TestListTemplates:
    def test_prints_all(self, capsys):
        sauravgen.list_templates()
        out = capsys.readouterr().out
        for name in sauravgen.TEMPLATES:
            assert name in out

    def test_shows_version(self, capsys):
        sauravgen.list_templates()
        out = capsys.readouterr().out
        assert sauravgen.__version__ in out


# ─── Integration: generate + write ───────────────────────────────

class TestIntegration:
    def test_function_file(self, tmp_path):
        content = sauravgen.gen_function("greet", args=["name"])
        path = str(tmp_path / "greet.srv")
        sauravgen.write_file(path, content)
        with open(path) as f:
            text = f.read()
        assert "function greet name" in text
        assert text.endswith("\n")

    def test_project_files(self, tmp_path):
        files = sauravgen.gen_project("demo")
        for rel, content in files.items():
            full = str(tmp_path / rel)
            sauravgen.write_file(full, content)
        assert os.path.exists(str(tmp_path / "demo" / "main.srv"))
        assert os.path.exists(str(tmp_path / "demo" / "lib.srv"))
        assert os.path.exists(str(tmp_path / "demo" / "tests" / "test_lib.srv"))
        assert os.path.exists(str(tmp_path / "demo" / "README.md"))

    def test_class_roundtrip(self, tmp_path):
        content = sauravgen.gen_class("Car", fields=["make", "model", "year"])
        path = str(tmp_path / "Car.srv")
        sauravgen.write_file(path, content)
        with open(path) as f:
            text = f.read()
        assert "class Car" in text
        assert "self.make = make" in text
        assert "function get_year" in text

    def test_enum_roundtrip(self, tmp_path):
        content = sauravgen.gen_enum("Light", variants=["Red", "Yellow", "Green"])
        path = str(tmp_path / "Light.srv")
        sauravgen.write_file(path, content)
        with open(path) as f:
            text = f.read()
        assert "enum Light" in text
        assert "case Light.Green" in text
