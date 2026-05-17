"""Tests for sauravmetrics — code metrics & complexity analyzer.

Exercises the pure-logic surface of sauravmetrics:
- analyze_file (LOC categorisation, function detection, complexity,
  nesting, imports, globals)
- FileMetrics / FunctionMetrics accessors
- Maintainability index
- JSON / CSV / human output paths
- find_srv_files
- CLI main()

Test inputs are written to ``tmp_path`` as .srv files so the analyzer
runs against real on-disk sources rather than mocked strings.
"""

import json
import os
import sys
import textwrap

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sauravmetrics as sm


def _write(tmp_path, name, source):
    """Write ``source`` to ``tmp_path/name`` and return the path."""
    source = textwrap.dedent(source).lstrip("\n")
    p = tmp_path / name
    p.write_text(source, encoding="utf-8")
    return str(p)


# ─── analyze_file: line categorisation ──────────────────────────────


class TestLineCategorisation:
    def test_blank_comment_code_counts(self, tmp_path):
        src = """\
            # comment one
            # comment two

            x = 1
            y = 2

            # another comment
            z = 3
        """
        path = _write(tmp_path, "a.srv", src)
        m = sm.analyze_file(path)
        assert m is not None
        assert m.total_lines == 8
        assert m.comment_lines == 3
        assert m.blank_lines == 2
        assert m.code_lines == 3

    def test_missing_file_returns_none(self, tmp_path, capsys):
        result = sm.analyze_file(str(tmp_path / "does_not_exist.srv"))
        assert result is None
        # An error should be reported on stderr.
        assert "Error reading" in capsys.readouterr().err


# ─── analyze_file: functions, complexity, nesting ───────────────────


class TestFunctionAnalysis:
    def test_function_count_and_names(self, tmp_path):
        src = """\
            function foo a b
                return a + b

            function bar x
                return x * 2
        """
        m = sm.analyze_file(_write(tmp_path, "f.srv", src))
        names = [f.name for f in m.functions]
        assert names == ["foo", "bar"]

    def test_param_counts(self, tmp_path):
        src = """\
            function add a b c
                return a + b + c

            function noargs
                return 0
        """
        m = sm.analyze_file(_write(tmp_path, "p.srv", src))
        params = {f.name: f.params for f in m.functions}
        assert params == {"add": 3, "noargs": 0}

    def test_cyclomatic_complexity_counts_leading_branch_keywords(self, tmp_path):
        # sauravmetrics counts a branch only when the *leading* token of a
        # line is a BRANCH_KEYWORD (if/elif/while/for/foreach/catch/and/or).
        # That gives 1 (base) + len(leading branches) for the function below.
        src = """\
            function complex x y
                if x > 0
                    while y > 0
                        for i in range(10)
                            y = y - 1
                elif x < 0
                    return -1
                if x
                    return 1
                return 0
        """
        m = sm.analyze_file(_write(tmp_path, "cx.srv", src))
        assert len(m.functions) == 1
        fn = m.functions[0]
        # Leading branch tokens: if, while, for, elif, if → 5 over base 1 = 6
        assert fn.complexity == 6

    def test_cyclomatic_complexity_simple_baseline(self, tmp_path):
        # A function with no branches has the base complexity of 1.
        src = """\
            function f a
                x = a + 1
                return x
        """
        m = sm.analyze_file(_write(tmp_path, "cx2.srv", src))
        assert m.functions[0].complexity == 1

    def test_function_loc_counts_body_only(self, tmp_path):
        src = """\
            function f a
                x = 1
                y = 2
                return x + y
        """
        m = sm.analyze_file(_write(tmp_path, "loc.srv", src))
        assert m.functions[0].loc == 3

    def test_function_max_depth(self, tmp_path):
        # body line indented N more than the def → max_depth = N - 1
        src = """\
            function deep
                if a
                    if b
                        if c
                            return 1
                return 0
        """
        m = sm.analyze_file(_write(tmp_path, "d.srv", src))
        # deepest body line (`return 1`) is 4 levels in (4 indents); function
        # base_indent is 0, fn_depth = indent - base_indent - 1 = 3.
        assert m.functions[0].max_depth >= 3

    def test_function_local_variables_captured(self, tmp_path):
        src = """\
            function vars
                a = 1
                b = 2
                a = 3
                return a + b
        """
        m = sm.analyze_file(_write(tmp_path, "v.srv", src))
        assert m.functions[0].variables == {"a", "b"}


# ─── analyze_file: globals, imports, depth ──────────────────────────


class TestGlobalScope:
    def test_imports_counted(self, tmp_path):
        src = """\
            import foo
            import bar
            import baz
            x = 1
        """
        m = sm.analyze_file(_write(tmp_path, "i.srv", src))
        assert m.imports == 3

    def test_global_variables_unique(self, tmp_path):
        src = """\
            a = 1
            b = 2
            a = 3
            c = 4
        """
        m = sm.analyze_file(_write(tmp_path, "g.srv", src))
        assert m.global_variables == {"a", "b", "c"}

    def test_max_depth_tracked(self, tmp_path):
        src = """\
            if x
                if y
                    if z
                        a = 1
        """
        m = sm.analyze_file(_write(tmp_path, "n.srv", src))
        # Deepest indent = 4 levels (4 leading 4-space groups → 16 chars).
        assert m.max_depth > 0

    def test_global_complexity_when_no_functions(self, tmp_path):
        # No functions ⇒ counts global branch keywords (+1 base).
        src = """\
            if a
                pass
            while b
                pass
            for c in d
                pass
        """
        m = sm.analyze_file(_write(tmp_path, "gc.srv", src))
        assert m.functions == []
        # 1 (base) + 3 branch keywords = 4
        assert m.total_complexity == 4


# ─── FileMetrics derived properties ─────────────────────────────────


class TestFileMetricsProps:
    def test_avg_complexity_zero_when_no_functions(self, tmp_path):
        m = sm.analyze_file(_write(tmp_path, "e.srv", "x = 1\n"))
        assert m.avg_complexity == 0
        assert m.avg_function_loc == 0

    def test_avg_function_loc(self, tmp_path):
        src = """\
            function a
                x = 1
                y = 2
            function b
                z = 3
                z = 4
                z = 5
                z = 6
        """
        m = sm.analyze_file(_write(tmp_path, "avg.srv", src))
        # loc: a=2, b=4 → avg 3
        assert m.avg_function_loc == 3

    def test_maintainability_index_in_range(self, tmp_path):
        m = sm.analyze_file(_write(tmp_path, "mi.srv", "x = 1\ny = 2\n"))
        mi = m.maintainability_index
        assert 0 <= mi <= 100


# ─── Output formatters ──────────────────────────────────────────────


class TestOutputFormatters:
    def test_json_output_is_valid(self, tmp_path, capsys):
        sm.USE_COLOR = False
        m = sm.analyze_file(_write(tmp_path, "x.srv", "function f a\n    return a\n"))
        sm.output_json([m])
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, list) and len(data) == 1
        entry = data[0]
        assert entry["functions"] == 1
        assert entry["function_details"][0]["name"] == "f"
        assert "maintainability_index" in entry

    def test_csv_output_header_and_row(self, tmp_path, capsys):
        sm.USE_COLOR = False
        m = sm.analyze_file(_write(tmp_path, "x.srv", "x = 1\n"))
        sm.output_csv([m])
        out = capsys.readouterr().out.strip().splitlines()
        assert out[0].startswith("file,")
        assert len(out) == 2
        # Row must have same comma count as header.
        assert out[0].count(",") == out[1].count(",")

    def test_print_file_metrics_runs(self, tmp_path, capsys):
        sm.USE_COLOR = False
        m = sm.analyze_file(_write(tmp_path, "x.srv",
                                   "function f a\n    if a\n        return 1\n"))
        sm.print_file_metrics(m, threshold=10, show_details=True)
        out = capsys.readouterr().out
        assert "Lines:" in out
        assert "Complexity:" in out
        assert "Function Details:" in out

    def test_print_summary_runs(self, tmp_path, capsys):
        sm.USE_COLOR = False
        m = sm.analyze_file(_write(tmp_path, "x.srv", "x = 1\n"))
        sm.print_summary([m], threshold=10)
        out = capsys.readouterr().out
        assert "Project Summary" in out
        assert "Files:" in out


# ─── find_srv_files ─────────────────────────────────────────────────


class TestFindFiles:
    def test_explicit_files(self, tmp_path):
        a = _write(tmp_path, "a.srv", "x = 1\n")
        b = _write(tmp_path, "b.srv", "y = 2\n")
        found = sm.find_srv_files([a, b])
        assert sorted(found) == sorted([a, b])

    def test_directory_non_recursive(self, tmp_path):
        _write(tmp_path, "a.srv", "x = 1\n")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.srv").write_text("y = 2\n", encoding="utf-8")
        found = sm.find_srv_files([str(tmp_path)], recursive=False)
        assert any(f.endswith("a.srv") for f in found)
        assert not any("nested.srv" in f for f in found)

    def test_directory_recursive(self, tmp_path):
        _write(tmp_path, "a.srv", "x = 1\n")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.srv").write_text("y = 2\n", encoding="utf-8")
        found = sm.find_srv_files([str(tmp_path)], recursive=True)
        assert any("nested.srv" in f for f in found)


# ─── CLI ────────────────────────────────────────────────────────────


class TestCLI:
    def test_main_json_output(self, tmp_path, capsys, monkeypatch):
        path = _write(tmp_path, "a.srv", "function f a\n    return a\n")
        monkeypatch.setattr(sys, "argv", ["sauravmetrics.py", path, "--json", "--no-color"])
        sm.main()
        data = json.loads(capsys.readouterr().out)
        assert data[0]["functions"] == 1

    def test_main_csv_output(self, tmp_path, capsys, monkeypatch):
        path = _write(tmp_path, "a.srv", "x = 1\n")
        monkeypatch.setattr(sys, "argv", ["sauravmetrics.py", path, "--csv", "--no-color"])
        sm.main()
        out = capsys.readouterr().out.strip().splitlines()
        assert out[0].startswith("file,")
        assert len(out) >= 2

    def test_main_summary_only(self, tmp_path, capsys, monkeypatch):
        path = _write(tmp_path, "a.srv", "x = 1\n")
        monkeypatch.setattr(sys, "argv",
                            ["sauravmetrics.py", path, "--summary", "--no-color"])
        sm.main()
        out = capsys.readouterr().out
        assert "Project Summary" in out

    def test_main_no_files_exits(self, tmp_path, capsys, monkeypatch):
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setattr(sys, "argv",
                            ["sauravmetrics.py", str(empty), "--no-color"])
        with pytest.raises(SystemExit) as exc:
            sm.main()
        assert exc.value.code == 1

    def test_main_sort_by_complexity(self, tmp_path, capsys, monkeypatch):
        # Two files; sorted output should place the more complex first.
        simple = _write(tmp_path, "simple.srv", "x = 1\n")
        complex_src = """\
            function f a
                if a
                    if a
                        return 1
                while a
                    return 2
        """
        complicated = _write(tmp_path, "complicated.srv", complex_src)
        monkeypatch.setattr(
            sys, "argv",
            ["sauravmetrics.py", simple, complicated,
             "--sort", "complexity", "--no-color"],
        )
        sm.main()
        out = capsys.readouterr().out
        # The complicated file's name should appear before the simple one
        # in the per-file sections.
        assert out.index("complicated.srv") < out.index("simple.srv")
