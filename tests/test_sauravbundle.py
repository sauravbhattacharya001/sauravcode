"""Tests for sauravbundle -- SauravCode file bundler."""

import os
import sys
import json
import pytest
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sauravbundle


@pytest.fixture
def tmp_project(tmp_path):
    """Create a temp project with multiple .srv files."""
    # utils.srv
    (tmp_path / "utils.srv").write_text(
        '# Utility functions\n'
        'function square n\n'
        '    return n * n\n'
        '\n'
        'PI = 3.14159\n'
    )
    # math_helpers.srv (imports utils)
    (tmp_path / "math_helpers.srv").write_text(
        'import "utils"\n'
        '\n'
        'function circle_area r\n'
        '    return PI * (square r)\n'
    )
    # main.srv (imports math_helpers)
    (tmp_path / "main.srv").write_text(
        '# Main program\n'
        'import "math_helpers"\n'
        '\n'
        'area = circle_area 5\n'
        'print f"Area: {area}"\n'
    )
    # standalone.srv (no imports)
    (tmp_path / "standalone.srv").write_text(
        '# No dependencies\n'
        'print "hello"\n'
    )
    return tmp_path


class TestResolveModulePath:
    def test_resolves_with_extension(self, tmp_project):
        result = sauravbundle.resolve_module_path("utils", [str(tmp_project)])
        assert result is not None
        assert result.endswith("utils.srv")

    def test_resolves_exact_path(self, tmp_project):
        result = sauravbundle.resolve_module_path("utils.srv", [str(tmp_project)])
        assert result is not None

    def test_returns_none_for_missing(self, tmp_project):
        result = sauravbundle.resolve_module_path("nonexistent", [str(tmp_project)])
        assert result is None

    def test_multiple_search_dirs(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "mod.srv").write_text("x = 1\n")
        result = sauravbundle.resolve_module_path("mod", [str(tmp_path), str(sub)])
        assert result is not None


class TestExtractImports:
    def test_extracts_quoted_import(self, tmp_project):
        imports = sauravbundle.extract_imports(str(tmp_project / "main.srv"))
        assert len(imports) == 1
        assert imports[0] == (2, "math_helpers")

    def test_extracts_no_imports(self, tmp_project):
        imports = sauravbundle.extract_imports(str(tmp_project / "standalone.srv"))
        assert len(imports) == 0

    def test_chained_imports(self, tmp_project):
        imports = sauravbundle.extract_imports(str(tmp_project / "math_helpers.srv"))
        assert len(imports) == 1
        assert imports[0] == (1, "utils")

    def test_missing_file(self):
        imports = sauravbundle.extract_imports("/nonexistent/file.srv")
        assert imports == []


class TestStripImports:
    def test_removes_import_lines(self):
        lines = ['import "foo"\n', 'x = 1\n', 'import bar\n', 'y = 2\n']
        result = sauravbundle.strip_imports(lines)
        assert len(result) == 2
        assert result[0] == 'x = 1\n'
        assert result[1] == 'y = 2\n'

    def test_preserves_non_import_lines(self):
        lines = ['x = 1\n', '# import is not real\n']
        result = sauravbundle.strip_imports(lines)
        assert len(result) == 2


class TestMinifyLines:
    def test_removes_comments(self):
        lines = ['# comment\n', 'x = 1\n', '  # indented comment\n']
        result = sauravbundle.minify_lines(lines)
        assert len(result) == 1
        assert result[0] == 'x = 1\n'

    def test_removes_blank_lines(self):
        lines = ['x = 1\n', '\n', '  \n', 'y = 2\n']
        result = sauravbundle.minify_lines(lines)
        assert len(result) == 2

    def test_preserves_code(self):
        lines = ['function foo\n', '    return 42\n']
        result = sauravbundle.minify_lines(lines)
        assert result == lines


class TestCollectModules:
    def test_collects_all_modules(self, tmp_project):
        modules, unresolved = sauravbundle.collect_modules(
            str(tmp_project / "main.srv"), [str(tmp_project)])
        names = list(modules.values())
        assert "utils" in names
        assert "math_helpers" in names
        assert "main" in names
        assert len(unresolved) == 0

    def test_topological_order(self, tmp_project):
        modules, _ = sauravbundle.collect_modules(
            str(tmp_project / "main.srv"), [str(tmp_project)])
        names = list(modules.values())
        # utils before math_helpers before main
        assert names.index("utils") < names.index("math_helpers")
        assert names.index("math_helpers") < names.index("main")

    def test_exclude_module(self, tmp_project):
        modules, _ = sauravbundle.collect_modules(
            str(tmp_project / "main.srv"), [str(tmp_project)],
            exclude=["utils"])
        names = list(modules.values())
        assert "utils" not in names

    def test_standalone_single_module(self, tmp_project):
        modules, _ = sauravbundle.collect_modules(
            str(tmp_project / "standalone.srv"), [str(tmp_project)])
        assert len(modules) == 1

    def test_unresolved_imports(self, tmp_path):
        (tmp_path / "bad.srv").write_text('import "nonexistent"\nprint 1\n')
        modules, unresolved = sauravbundle.collect_modules(
            str(tmp_path / "bad.srv"), [str(tmp_path)])
        assert len(unresolved) == 1


class TestBundle:
    def test_basic_bundle(self, tmp_project):
        result, stats = sauravbundle.bundle(
            str(tmp_project / "main.srv"), [str(tmp_project)])
        # Should contain code from all modules
        assert "square" in result
        assert "circle_area" in result
        assert "print" in result
        # Should NOT contain import statements
        assert 'import "' not in result
        assert stats['module_count'] == 3

    def test_no_import_lines_in_output(self, tmp_project):
        result, _ = sauravbundle.bundle(
            str(tmp_project / "main.srv"), [str(tmp_project)])
        for line in result.split('\n'):
            stripped = line.strip()
            if stripped and not stripped.startswith('#'):
                assert not sauravbundle.IMPORT_RE.match(line), \
                    f"Import line found in bundle: {line}"

    def test_module_separators(self, tmp_project):
        result, _ = sauravbundle.bundle(
            str(tmp_project / "main.srv"), [str(tmp_project)])
        assert "# ── Module: utils" in result
        assert "# ── Entry: main" in result

    def test_minify(self, tmp_project):
        normal, s1 = sauravbundle.bundle(
            str(tmp_project / "main.srv"), [str(tmp_project)])
        minified, s2 = sauravbundle.bundle(
            str(tmp_project / "main.srv"), [str(tmp_project)],
            do_minify=True)
        assert len(minified) < len(normal)
        assert s2['minified'] is True

    def test_banner(self, tmp_project):
        result, _ = sauravbundle.bundle(
            str(tmp_project / "main.srv"), [str(tmp_project)],
            banner="MyApp v1.0")
        assert result.startswith("# MyApp v1.0\n")
        assert "sauravbundle" in result.split('\n')[1]

    def test_standalone_bundle(self, tmp_project):
        result, stats = sauravbundle.bundle(
            str(tmp_project / "standalone.srv"), [str(tmp_project)])
        assert stats['module_count'] == 1
        assert 'print "hello"' in result

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            sauravbundle.bundle("/nonexistent/file.srv")

    def test_stats_structure(self, tmp_project):
        _, stats = sauravbundle.bundle(
            str(tmp_project / "main.srv"), [str(tmp_project)])
        assert 'entry' in stats
        assert 'module_count' in stats
        assert 'total_lines' in stats
        assert 'imports_removed' in stats
        assert 'modules' in stats
        assert isinstance(stats['modules'], list)

    def test_exclude_in_bundle(self, tmp_project):
        result, stats = sauravbundle.bundle(
            str(tmp_project / "main.srv"), [str(tmp_project)],
            exclude=["utils"])
        # utils module itself is excluded (no PI = 3.14159 definition)
        assert "PI = 3.14159" not in result
        assert stats['module_count'] == 2


class TestFormatStats:
    def test_format_output(self, tmp_project):
        _, stats = sauravbundle.bundle(
            str(tmp_project / "main.srv"), [str(tmp_project)])
        text = sauravbundle.format_stats(stats)
        assert "Bundle Statistics" in text
        assert "Modules bundled:" in text
        assert "3" in text


class TestBuildDependencyTree:
    def test_tree_structure(self, tmp_project):
        lines = sauravbundle.build_dependency_tree(
            str(tmp_project / "main.srv"), [str(tmp_project)])
        tree = '\n'.join(lines)
        assert "main.srv" in tree
        assert "math_helpers.srv" in tree
        assert "utils.srv" in tree

    def test_unresolved_in_tree(self, tmp_path):
        (tmp_path / "bad.srv").write_text('import "missing"\n')
        lines = sauravbundle.build_dependency_tree(
            str(tmp_path / "bad.srv"), [str(tmp_path)])
        tree = '\n'.join(lines)
        assert "unresolved" in tree


class TestCLI:
    def test_dry_run(self, tmp_project, capsys):
        rc = sauravbundle.main([str(tmp_project / "main.srv"), '--dry-run'])
        assert rc == 0
        out = capsys.readouterr().out
        assert "utils" in out
        assert "math_helpers" in out

    def test_tree(self, tmp_project, capsys):
        rc = sauravbundle.main([str(tmp_project / "main.srv"), '--tree'])
        assert rc == 0
        out = capsys.readouterr().out
        assert "main.srv" in out

    def test_stats(self, tmp_project, capsys):
        rc = sauravbundle.main([str(tmp_project / "main.srv"), '--stats'])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Bundle Statistics" in out

    def test_json_output(self, tmp_project, capsys):
        rc = sauravbundle.main([str(tmp_project / "main.srv"), '--json'])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data['module_count'] == 3

    def test_output_file(self, tmp_project, capsys):
        outfile = str(tmp_project / "out.srv")
        rc = sauravbundle.main([str(tmp_project / "main.srv"), '-o', outfile])
        assert rc == 0
        assert os.path.isfile(outfile)
        content = open(outfile).read()
        assert "square" in content

    def test_missing_entry(self, capsys):
        rc = sauravbundle.main(["/nonexistent.srv"])
        assert rc == 1

    def test_minify_flag(self, tmp_project, capsys):
        rc = sauravbundle.main([str(tmp_project / "main.srv"), '--minify'])
        assert rc == 0
        out = capsys.readouterr().out
        # No comment-only lines (except separators)
        for line in out.split('\n'):
            if line.strip() and line.strip().startswith('#'):
                assert "──" in line  # Only separators

    def test_banner_flag(self, tmp_project, capsys):
        rc = sauravbundle.main([
            str(tmp_project / "main.srv"), '--banner', 'Test v2.0'])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Test v2.0" in out

    def test_exclude_flag(self, tmp_project, capsys):
        rc = sauravbundle.main([
            str(tmp_project / "main.srv"), '--exclude', 'utils'])
        assert rc == 0
        out = capsys.readouterr().out
        # utils module code excluded (no PI definition)
        assert "PI = 3.14159" not in out
