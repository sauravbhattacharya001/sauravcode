"""Tests for sauravpipe — pipeline runner for chaining .srv scripts.

Covers the Stage/Pipeline model (DAG validation, topo-order, ready-set
scheduling), the runner's stage-execution (success / failure / retry /
timeout / cascade-skip), CLI builders (chain / parallel / template /
dot / dry-run), Graphviz output, and the JSON template.

The runner is exercised by injecting fake Python scripts that exit 0/1,
sleep, or write known output — no .srv interpreter is required.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import sauravpipe


# ─── Model: Stage / Pipeline ───────────────────────────────────────────


class TestStage:
    def test_minimal_fields(self):
        s = sauravpipe.Stage({"id": "a", "script": "a.srv"})
        assert s.id == "a"
        assert s.script == "a.srv"
        assert s.args == []
        assert s.depends == []
        assert s.retry == 0
        assert s.timeout is None
        assert s.env == {}
        assert s.status == "pending"
        assert s.duration == 0.0
        assert s.error is None
        assert s.output_file is None

    def test_all_fields(self):
        s = sauravpipe.Stage({
            "id": "b",
            "script": "b.srv",
            "args": ["x", 1],
            "depends": ["a"],
            "retry": 2,
            "timeout": 30,
            "env": {"FOO": "bar"},
        })
        assert s.args == ["x", 1]
        assert s.depends == ["a"]
        assert s.retry == 2
        assert s.timeout == 30
        assert s.env == {"FOO": "bar"}

    def test_missing_id_raises(self):
        with pytest.raises(KeyError):
            sauravpipe.Stage({"script": "a.srv"})

    def test_uses_slots(self):
        s = sauravpipe.Stage({"id": "a", "script": "a.srv"})
        with pytest.raises(AttributeError):
            s.extra = 1  # __slots__ should forbid this


class TestPipelineValidation:
    def _mk(self, stages):
        return sauravpipe.Pipeline("p", [sauravpipe.Stage(s) for s in stages])

    def test_unknown_dependency_raises(self):
        with pytest.raises(ValueError, match="depends on unknown"):
            self._mk([{"id": "a", "script": "a.srv", "depends": ["ghost"]}])

    def test_self_cycle_raises(self):
        with pytest.raises(ValueError, match="Cycle"):
            self._mk([{"id": "a", "script": "a.srv", "depends": ["a"]}])

    def test_two_node_cycle_raises(self):
        with pytest.raises(ValueError, match="Cycle"):
            self._mk([
                {"id": "a", "script": "a.srv", "depends": ["b"]},
                {"id": "b", "script": "b.srv", "depends": ["a"]},
            ])

    def test_three_node_cycle_raises(self):
        with pytest.raises(ValueError, match="Cycle"):
            self._mk([
                {"id": "a", "script": "a.srv", "depends": ["c"]},
                {"id": "b", "script": "b.srv", "depends": ["a"]},
                {"id": "c", "script": "c.srv", "depends": ["b"]},
            ])

    def test_valid_dag_accepted(self):
        p = self._mk([
            {"id": "a", "script": "a.srv"},
            {"id": "b", "script": "b.srv", "depends": ["a"]},
            {"id": "c", "script": "c.srv", "depends": ["a"]},
            {"id": "d", "script": "d.srv", "depends": ["b", "c"]},
        ])
        assert set(p.stages) == {"a", "b", "c", "d"}


class TestTopoOrder:
    def test_linear(self):
        p = sauravpipe.Pipeline("p", [
            sauravpipe.Stage({"id": "a", "script": "a.srv"}),
            sauravpipe.Stage({"id": "b", "script": "b.srv", "depends": ["a"]}),
            sauravpipe.Stage({"id": "c", "script": "c.srv", "depends": ["b"]}),
        ])
        assert p.topo_order() == ["a", "b", "c"]

    def test_diamond(self):
        p = sauravpipe.Pipeline("p", [
            sauravpipe.Stage({"id": "a", "script": "a.srv"}),
            sauravpipe.Stage({"id": "b", "script": "b.srv", "depends": ["a"]}),
            sauravpipe.Stage({"id": "c", "script": "c.srv", "depends": ["a"]}),
            sauravpipe.Stage({"id": "d", "script": "d.srv", "depends": ["b", "c"]}),
        ])
        order = p.topo_order()
        # 'a' before 'b' and 'c'; 'b' and 'c' before 'd'
        assert order.index("a") < order.index("b")
        assert order.index("a") < order.index("c")
        assert order.index("b") < order.index("d")
        assert order.index("c") < order.index("d")


class TestReadyStages:
    def test_initial_ready_set(self):
        p = sauravpipe.Pipeline("p", [
            sauravpipe.Stage({"id": "a", "script": "a.srv"}),
            sauravpipe.Stage({"id": "b", "script": "b.srv"}),
            sauravpipe.Stage({"id": "c", "script": "c.srv", "depends": ["a"]}),
        ])
        ready = {s.id for s in p.ready_stages(completed=set())}
        assert ready == {"a", "b"}

    def test_unlocks_after_completion(self):
        p = sauravpipe.Pipeline("p", [
            sauravpipe.Stage({"id": "a", "script": "a.srv"}),
            sauravpipe.Stage({"id": "b", "script": "b.srv", "depends": ["a"]}),
        ])
        # 'b' depends on 'a' — not ready yet
        ready = {s.id for s in p.ready_stages(set())}
        assert ready == {"a"}
        # After 'a' is marked success and added to completed, 'b' becomes ready
        p.stages["a"].status = "success"
        ready = {s.id for s in p.ready_stages({"a"})}
        assert ready == {"b"}

    def test_skips_non_pending(self):
        p = sauravpipe.Pipeline("p", [
            sauravpipe.Stage({"id": "a", "script": "a.srv"}),
            sauravpipe.Stage({"id": "b", "script": "b.srv"}),
        ])
        p.stages["a"].status = "running"
        ready = {s.id for s in p.ready_stages(set())}
        assert ready == {"b"}


# ─── Runner: _run_stage and run_pipeline ───────────────────────────────


def _make_fake_interp(tmp_path: Path) -> Path:
    """A tiny Python interpreter that mimics saurav.py for tests.

    It treats the first script argument as a Python file and exec()s
    it, so test fixtures can write trivial Python programs that
    exit 0, exit 1, sleep, or read env vars.
    """
    interp = tmp_path / "fake_saurav.py"
    interp.write_text(textwrap.dedent("""
        import os, sys, runpy
        # script path is sys.argv[1]; remaining are passed through
        script = sys.argv[1]
        sys.argv = [script] + sys.argv[2:]
        runpy.run_path(script, run_name="__main__")
    """).strip(), encoding="utf-8")
    return interp


def _write_script(dir_: Path, name: str, body: str) -> Path:
    p = dir_ / name
    p.write_text(textwrap.dedent(body).strip() + "\n", encoding="utf-8")
    return p


class TestRunStage:
    def test_success(self, tmp_path):
        interp = _make_fake_interp(tmp_path)
        _write_script(tmp_path, "ok.srv", "import sys; sys.exit(0)")
        stage = sauravpipe.Stage({"id": "ok", "script": "ok.srv"})
        ok = sauravpipe._run_stage(stage, str(interp), str(tmp_path))
        assert ok is True
        assert stage.status == "success"
        assert stage.duration >= 0
        assert stage.error is None
        # Output file path was assigned and the file is on disk
        assert stage.output_file and os.path.isfile(stage.output_file)
        os.remove(stage.output_file)

    def test_failure_nonzero_exit(self, tmp_path):
        interp = _make_fake_interp(tmp_path)
        _write_script(tmp_path, "bad.srv",
                      'import sys; sys.stderr.write("boom\\n"); sys.exit(2)')
        stage = sauravpipe.Stage({"id": "bad", "script": "bad.srv"})
        ok = sauravpipe._run_stage(stage, str(interp), str(tmp_path))
        assert ok is False
        assert stage.status == "failed"
        assert stage.error and ("boom" in stage.error or "2" in stage.error)
        if stage.output_file and os.path.isfile(stage.output_file):
            os.remove(stage.output_file)

    def test_missing_script(self, tmp_path):
        interp = _make_fake_interp(tmp_path)
        stage = sauravpipe.Stage({"id": "x", "script": "nope.srv"})
        ok = sauravpipe._run_stage(stage, str(interp), str(tmp_path))
        assert ok is False
        assert stage.status == "failed"
        assert "not found" in (stage.error or "").lower()

    def test_retry_then_succeed(self, tmp_path, monkeypatch):
        """A flaky script that succeeds on the 2nd attempt."""
        interp = _make_fake_interp(tmp_path)
        marker = tmp_path / "marker.txt"
        _write_script(tmp_path, "flaky.srv", f"""
            import os, sys
            p = {marker.as_posix()!r}
            if os.path.exists(p):
                sys.exit(0)
            else:
                open(p, 'w').write('seen')
                sys.exit(1)
        """)
        stage = sauravpipe.Stage({
            "id": "flaky", "script": "flaky.srv", "retry": 2,
        })
        # Skip the backoff sleep to keep the test fast
        monkeypatch.setattr(sauravpipe.time, "sleep", lambda *_: None)
        ok = sauravpipe._run_stage(stage, str(interp), str(tmp_path))
        assert ok is True
        assert stage.status == "success"
        if stage.output_file and os.path.isfile(stage.output_file):
            os.remove(stage.output_file)

    def test_retry_exhausted(self, tmp_path, monkeypatch):
        interp = _make_fake_interp(tmp_path)
        _write_script(tmp_path, "always.srv", "import sys; sys.exit(1)")
        stage = sauravpipe.Stage({
            "id": "always", "script": "always.srv", "retry": 2,
        })
        monkeypatch.setattr(sauravpipe.time, "sleep", lambda *_: None)
        ok = sauravpipe._run_stage(stage, str(interp), str(tmp_path))
        assert ok is False
        assert stage.status == "failed"

    def test_timeout(self, tmp_path, monkeypatch):
        interp = _make_fake_interp(tmp_path)
        _write_script(tmp_path, "slow.srv", "import time; time.sleep(5)")
        stage = sauravpipe.Stage({
            "id": "slow", "script": "slow.srv", "timeout": 0.2,
        })
        monkeypatch.setattr(sauravpipe.time, "sleep", lambda *_: None)
        ok = sauravpipe._run_stage(stage, str(interp), str(tmp_path))
        assert ok is False
        assert stage.status == "failed"
        assert "Timeout" in (stage.error or "")

    def test_env_passed_to_subprocess(self, tmp_path):
        interp = _make_fake_interp(tmp_path)
        # Script asserts a specific env var is set
        _write_script(tmp_path, "envcheck.srv", """
            import os, sys
            assert os.environ.get('PIPE_TEST_VAR') == 'present', 'missing var'
            sys.exit(0)
        """)
        stage = sauravpipe.Stage({
            "id": "e", "script": "envcheck.srv",
            "env": {"PIPE_TEST_VAR": "present"},
        })
        ok = sauravpipe._run_stage(stage, str(interp), str(tmp_path))
        assert ok is True
        if stage.output_file and os.path.isfile(stage.output_file):
            os.remove(stage.output_file)

    def test_unexpected_exception_breaks_loop(self, tmp_path, monkeypatch):
        """If subprocess.run itself raises an unexpected error, fail fast."""
        interp = _make_fake_interp(tmp_path)
        _write_script(tmp_path, "x.srv", "import sys; sys.exit(0)")
        stage = sauravpipe.Stage({"id": "x", "script": "x.srv", "retry": 5})
        call_count = {"n": 0}

        def boom(*a, **kw):
            call_count["n"] += 1
            raise RuntimeError("subprocess exploded")

        monkeypatch.setattr(sauravpipe.subprocess, "run", boom)
        ok = sauravpipe._run_stage(stage, str(interp), str(tmp_path))
        assert ok is False
        assert stage.status == "failed"
        # Should not retry after unexpected exception
        assert call_count["n"] == 1


# ─── _collect_input ────────────────────────────────────────────────────


class TestCollectInput:
    def test_no_deps_returns_none(self):
        p = sauravpipe.Pipeline("p", [sauravpipe.Stage({"id": "a", "script": "a.srv"})])
        assert sauravpipe._collect_input(p.stages["a"], p) is None

    def test_returns_last_dep_output(self, tmp_path):
        p = sauravpipe.Pipeline("p", [
            sauravpipe.Stage({"id": "a", "script": "a.srv"}),
            sauravpipe.Stage({"id": "b", "script": "b.srv"}),
            sauravpipe.Stage({"id": "c", "script": "c.srv", "depends": ["a", "b"]}),
        ])
        f = tmp_path / "out.json"
        f.write_text("{}")
        p.stages["b"].output_file = str(f)
        assert sauravpipe._collect_input(p.stages["c"], p) == str(f)

    def test_missing_file_returns_none(self):
        p = sauravpipe.Pipeline("p", [
            sauravpipe.Stage({"id": "a", "script": "a.srv"}),
            sauravpipe.Stage({"id": "b", "script": "b.srv", "depends": ["a"]}),
        ])
        p.stages["a"].output_file = "/path/does/not/exist.json"
        assert sauravpipe._collect_input(p.stages["b"], p) is None


# ─── run_pipeline end-to-end (with fake interp) ────────────────────────


class TestRunPipeline:
    def test_all_succeed_linear(self, tmp_path, monkeypatch):
        interp = _make_fake_interp(tmp_path)
        for name in ("a.srv", "b.srv", "c.srv"):
            _write_script(tmp_path, name, "import sys; sys.exit(0)")
        stages = [
            sauravpipe.Stage({"id": "a", "script": "a.srv"}),
            sauravpipe.Stage({"id": "b", "script": "b.srv", "depends": ["a"]}),
            sauravpipe.Stage({"id": "c", "script": "c.srv", "depends": ["b"]}),
        ]
        p = sauravpipe.Pipeline("test", stages)
        monkeypatch.setattr(sauravpipe, "_find_interpreter", lambda: str(interp))
        failed = sauravpipe.run_pipeline(p, str(tmp_path), max_parallel=2)
        assert failed == set()
        assert all(s.status == "success" for s in p.stages.values())

    def test_cascade_skip_on_dep_failure(self, tmp_path, monkeypatch):
        interp = _make_fake_interp(tmp_path)
        _write_script(tmp_path, "a.srv", "import sys; sys.exit(1)")
        _write_script(tmp_path, "b.srv", "import sys; sys.exit(0)")
        _write_script(tmp_path, "c.srv", "import sys; sys.exit(0)")
        stages = [
            sauravpipe.Stage({"id": "a", "script": "a.srv"}),
            sauravpipe.Stage({"id": "b", "script": "b.srv", "depends": ["a"]}),
            sauravpipe.Stage({"id": "c", "script": "c.srv", "depends": ["b"]}),
        ]
        p = sauravpipe.Pipeline("cascade", stages)
        monkeypatch.setattr(sauravpipe, "_find_interpreter", lambda: str(interp))
        failed = sauravpipe.run_pipeline(p, str(tmp_path), max_parallel=2)
        assert "a" in failed and "b" in failed and "c" in failed
        assert p.stages["a"].status == "failed"
        assert p.stages["b"].status == "skipped"
        assert p.stages["c"].status == "skipped"
        assert "dependency failed" in (p.stages["b"].error or "").lower()

    def test_parallel_independent_stages(self, tmp_path, monkeypatch):
        interp = _make_fake_interp(tmp_path)
        for n in ("a.srv", "b.srv", "c.srv"):
            _write_script(tmp_path, n, "import sys; sys.exit(0)")
        stages = [
            sauravpipe.Stage({"id": "a", "script": "a.srv"}),
            sauravpipe.Stage({"id": "b", "script": "b.srv"}),
            sauravpipe.Stage({"id": "c", "script": "c.srv"}),
        ]
        p = sauravpipe.Pipeline("par", stages)
        monkeypatch.setattr(sauravpipe, "_find_interpreter", lambda: str(interp))
        failed = sauravpipe.run_pipeline(p, str(tmp_path), max_parallel=3)
        assert failed == set()


# ─── print_summary ─────────────────────────────────────────────────────


class TestPrintSummary:
    def test_returns_zero_on_success(self, capsys):
        p = sauravpipe.Pipeline("p", [sauravpipe.Stage({"id": "a", "script": "a.srv"})])
        p.stages["a"].status = "success"
        p.stages["a"].duration = 0.5
        rc = sauravpipe.print_summary(p, failed=set())
        assert rc == 0
        out = capsys.readouterr().out
        assert "a" in out
        assert "passed" in out

    def test_returns_one_on_failure(self, capsys):
        p = sauravpipe.Pipeline("p", [sauravpipe.Stage({"id": "a", "script": "a.srv"})])
        p.stages["a"].status = "failed"
        p.stages["a"].error = "exit 1"
        rc = sauravpipe.print_summary(p, failed={"a"})
        assert rc == 1


# ─── to_dot ────────────────────────────────────────────────────────────


class TestToDot:
    def test_basic(self):
        p = sauravpipe.Pipeline("hello", [
            sauravpipe.Stage({"id": "a", "script": "a.srv"}),
            sauravpipe.Stage({"id": "b", "script": "b.srv", "depends": ["a"]}),
        ])
        dot = sauravpipe.to_dot(p)
        assert 'digraph "hello"' in dot
        assert '"a" -> "b"' in dot
        assert "a.srv" in dot and "b.srv" in dot
        assert dot.rstrip().endswith("}")


# ─── Template ──────────────────────────────────────────────────────────


class TestTemplate:
    def test_template_is_valid_pipeline(self):
        """The shipped TEMPLATE must parse and validate as a real pipeline."""
        stages = [sauravpipe.Stage(s) for s in sauravpipe.TEMPLATE["stages"]]
        p = sauravpipe.Pipeline(sauravpipe.TEMPLATE["name"], stages)
        # No cycles, all deps resolved, topo order returns all ids
        assert set(p.topo_order()) == set(p.stages.keys())

    def test_template_json_serialisable(self):
        # Should round-trip through JSON without loss
        s = json.dumps(sauravpipe.TEMPLATE)
        back = json.loads(s)
        assert back == sauravpipe.TEMPLATE


# ─── CLI: main() entry-point ───────────────────────────────────────────


def _run_cli(monkeypatch, capsys, *args, expect_exit=None):
    monkeypatch.setattr(sys, "argv", ["sauravpipe", *args])
    if expect_exit is not None:
        with pytest.raises(SystemExit) as ei:
            sauravpipe.main()
        assert ei.value.code == expect_exit
    else:
        sauravpipe.main()
    return capsys.readouterr()


class TestCLI:
    def test_template_prints_valid_json(self, monkeypatch, capsys):
        out = _run_cli(monkeypatch, capsys, "--template")
        data = json.loads(out.out)
        assert data["name"] == "example-pipeline"
        assert len(data["stages"]) >= 1

    def test_no_args_prints_help_and_exits_1(self, monkeypatch, capsys):
        _run_cli(monkeypatch, capsys, expect_exit=1)

    def test_dot_from_chain(self, monkeypatch, capsys, tmp_path):
        # Build a chain pipeline and write it as JSON, then ask for --dot
        pjson = tmp_path / "p.json"
        pjson.write_text(json.dumps({
            "name": "chainy",
            "stages": [
                {"id": "a", "script": "a.srv"},
                {"id": "b", "script": "b.srv", "depends": ["a"]},
            ],
        }))
        out = _run_cli(monkeypatch, capsys, str(pjson), "--dot")
        assert 'digraph "chainy"' in out.out
        assert '"a" -> "b"' in out.out

    def test_dry_run(self, monkeypatch, capsys, tmp_path):
        pjson = tmp_path / "p.json"
        pjson.write_text(json.dumps({
            "name": "dry",
            "stages": [
                {"id": "a", "script": "a.srv"},
                {"id": "b", "script": "b.srv", "depends": ["a"]},
            ],
        }))
        out = _run_cli(monkeypatch, capsys, str(pjson), "--dry-run")
        assert "valid" in out.out
        assert "a -> b" in out.out

    def test_chain_builder(self, monkeypatch, capsys, tmp_path):
        # Build a chain whose every script just exits 0 via fake interp
        interp = _make_fake_interp(tmp_path)
        a = _write_script(tmp_path, "a.srv", "import sys; sys.exit(0)")
        b = _write_script(tmp_path, "b.srv", "import sys; sys.exit(0)")
        monkeypatch.setattr(sauravpipe, "_find_interpreter", lambda: str(interp))
        monkeypatch.chdir(tmp_path)
        _run_cli(monkeypatch, capsys, "--chain", str(a), str(b),
                 "--work-dir", str(tmp_path), expect_exit=0)

    def test_parallel_builder(self, monkeypatch, capsys, tmp_path):
        interp = _make_fake_interp(tmp_path)
        a = _write_script(tmp_path, "a.srv", "import sys; sys.exit(0)")
        b = _write_script(tmp_path, "b.srv", "import sys; sys.exit(0)")
        monkeypatch.setattr(sauravpipe, "_find_interpreter", lambda: str(interp))
        monkeypatch.chdir(tmp_path)
        _run_cli(monkeypatch, capsys, "--parallel", str(a), str(b),
                 "--work-dir", str(tmp_path), expect_exit=0)

    def test_invalid_pipeline_exits_1(self, monkeypatch, capsys, tmp_path):
        pjson = tmp_path / "bad.json"
        pjson.write_text(json.dumps({
            "name": "bad",
            "stages": [
                {"id": "a", "script": "a.srv", "depends": ["ghost"]},
            ],
        }))
        _run_cli(monkeypatch, capsys, str(pjson), expect_exit=1)

    def test_failed_pipeline_exits_1(self, monkeypatch, capsys, tmp_path):
        interp = _make_fake_interp(tmp_path)
        _write_script(tmp_path, "fail.srv", "import sys; sys.exit(1)")
        pjson = tmp_path / "p.json"
        pjson.write_text(json.dumps({
            "name": "failpipe",
            "stages": [{"id": "f", "script": "fail.srv"}],
        }))
        monkeypatch.setattr(sauravpipe, "_find_interpreter", lambda: str(interp))
        _run_cli(monkeypatch, capsys, str(pjson),
                 "--work-dir", str(tmp_path), expect_exit=1)
