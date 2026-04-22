#!/usr/bin/env python3
"""sauravpipe — Pipeline runner for chaining .srv scripts.

Define multi-stage pipelines that pass data between sauravcode scripts,
with parallel execution, error handling, retries, and live progress.

Usage:
    python sauravpipe.py pipeline.json              # run a pipeline from JSON
    python sauravpipe.py --chain a.srv b.srv c.srv   # simple linear chain
    python sauravpipe.py --parallel a.srv b.srv       # run stages in parallel
    python sauravpipe.py --dry-run pipeline.json      # validate without running
    python sauravpipe.py --template                   # print example pipeline JSON
    python sauravpipe.py --dot pipeline.json           # output Graphviz DOT

Pipeline JSON format:
    {
      "name": "my-pipeline",
      "stages": [
        {"id": "load", "script": "load.srv", "args": ["data.csv"]},
        {"id": "transform", "script": "transform.srv", "depends": ["load"]},
        {"id": "report", "script": "report.srv", "depends": ["transform"],
         "retry": 2, "timeout": 30}
      ]
    }

Features:
    - DAG-based execution: stages run as soon as dependencies are met
    - Data passing via _PIPE_INPUT / _PIPE_OUTPUT env vars (JSON files)
    - Retry with backoff on failure
    - Timeout per stage
    - Dry-run validation (cycle detection, missing scripts)
    - DOT graph export for visualization
    - Live progress with durations
    - Exit code aggregation
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import threading
from pathlib import Path


# ─── Colors (shared via _termcolors) ───────────────────────────────────

from _termcolors import Colors as _Colors

_TC = _Colors(sys.stdout.isatty() and bool(os.environ.get("TERM")))
_c = _TC.c

def _safe(text):
    """Replace Unicode symbols with ASCII fallbacks on non-UTF8 terminals."""
    try:
        text.encode(sys.stdout.encoding or "utf-8")
        return text
    except (UnicodeEncodeError, LookupError):
        return text.replace("✓", "OK").replace("✗", "X").replace("▶", ">").replace("⊘", "-").replace("○", "o").replace("─", "-").replace("╭", "+").replace("│", "|").replace("╰", "+")

_green = _TC.green
_red = _TC.red
_yellow = _TC.yellow
_cyan = _TC.cyan
_bold = _TC.bold
_dim = _TC.dim


# ─── Pipeline model ──────────────────────────────────────────────────────────

class Stage:
    """One stage in a pipeline."""
    __slots__ = ("id", "script", "args", "depends", "retry", "timeout",
                 "env", "status", "duration", "error", "output_file")

    def __init__(self, data):
        self.id = data["id"]
        self.script = data["script"]
        self.args = data.get("args", [])
        self.depends = data.get("depends", [])
        self.retry = data.get("retry", 0)
        self.timeout = data.get("timeout", None)
        self.env = data.get("env", {})
        self.status = "pending"  # pending | running | success | failed | skipped
        self.duration = 0.0
        self.error = None
        self.output_file = None


class Pipeline:
    """A DAG of stages."""

    def __init__(self, name, stages):
        self.name = name
        self.stages = {s.id: s for s in stages}
        self._validate()

    def _validate(self):
        ids = set(self.stages.keys())
        for s in self.stages.values():
            for dep in s.depends:
                if dep not in ids:
                    raise ValueError(f"Stage '{s.id}' depends on unknown stage '{dep}'")
        # Cycle detection via topological sort
        visited = set()
        temp = set()

        def visit(sid):
            if sid in temp:
                raise ValueError(f"Cycle detected involving stage '{sid}'")
            if sid in visited:
                return
            temp.add(sid)
            for dep in self.stages[sid].depends:
                visit(dep)
            temp.remove(sid)
            visited.add(sid)

        for sid in self.stages:
            visit(sid)

    def topo_order(self):
        """Return stage IDs in topological order."""
        order = []
        visited = set()

        def visit(sid):
            if sid in visited:
                return
            visited.add(sid)
            for dep in self.stages[sid].depends:
                visit(dep)
            order.append(sid)

        for sid in self.stages:
            visit(sid)
        return order

    def ready_stages(self, completed):
        """Return stages whose dependencies are all in completed set."""
        ready = []
        for s in self.stages.values():
            if s.status == "pending" and all(d in completed for d in s.depends):
                ready.append(s)
        return ready


# ─── Runner ───────────────────────────────────────────────────────────────────

def _find_interpreter():
    """Locate saurav.py interpreter."""
    here = Path(__file__).resolve().parent
    interp = here / "saurav.py"
    if interp.exists():
        return str(interp)
    return "saurav.py"


def _run_stage(stage, interp, work_dir, input_file=None):
    """Execute a single stage, returning True on success."""
    stage.status = "running"
    # tempfile.mktemp is deprecated due to race conditions; use NamedTemporaryFile
    tmp = tempfile.NamedTemporaryFile(
        suffix=".json", prefix=f"pipe_{stage.id}_", delete=False
    )
    stage.output_file = tmp.name
    tmp.close()

    env = os.environ.copy()
    env.update(stage.env)
    if input_file and os.path.isfile(input_file):
        env["_PIPE_INPUT"] = input_file
    env["_PIPE_OUTPUT"] = stage.output_file

    script_path = stage.script
    if not os.path.isabs(script_path):
        script_path = os.path.join(work_dir, script_path)

    if not os.path.isfile(script_path):
        stage.error = f"Script not found: {script_path}"
        stage.status = "failed"
        return False

    cmd = [sys.executable, interp, script_path] + [str(a) for a in stage.args]

    attempts = 1 + stage.retry
    for attempt in range(attempts):
        t0 = time.time()
        try:
            result = subprocess.run(
                cmd, env=env, capture_output=True, text=True,
                timeout=stage.timeout, cwd=work_dir
            )
            stage.duration = time.time() - t0
            if result.returncode == 0:
                stage.status = "success"
                return True
            else:
                stage.error = result.stderr.strip() or f"exit code {result.returncode}"
                if attempt < attempts - 1:
                    backoff = 2 ** attempt
                    time.sleep(backoff)
        except subprocess.TimeoutExpired:
            stage.duration = time.time() - t0
            stage.error = f"Timeout after {stage.timeout}s"
            if attempt < attempts - 1:
                time.sleep(1)
        except Exception as e:
            stage.duration = time.time() - t0
            stage.error = str(e)
            break

    stage.status = "failed"
    return False


def _collect_input(stage, pipeline):
    """Find the output file from the last dependency (simple linear passing)."""
    if not stage.depends:
        return None
    # Use the last dependency's output
    last_dep = stage.depends[-1]
    dep_stage = pipeline.stages[last_dep]
    if dep_stage.output_file and os.path.isfile(dep_stage.output_file):
        return dep_stage.output_file
    return None


def run_pipeline(pipeline, work_dir, max_parallel=4):
    """Execute a pipeline with DAG-aware streaming scheduling.

    Uses a ThreadPoolExecutor so new stages are dispatched as soon as
    their dependencies complete — not after an entire batch finishes.
    A Condition variable replaces the old Event to properly synchronise
    the ready-check loop without busy-polling or batch stalls.
    """
    from concurrent.futures import ThreadPoolExecutor

    interp = _find_interpreter()
    completed = set()   # stage ids that succeeded
    failed = set()      # stage ids that failed or were skipped
    in_flight = set()   # stage ids currently executing
    cond = threading.Condition()  # protects all mutable sets above

    print(_bold(f"+-- Pipeline: {pipeline.name} ({len(pipeline.stages)} stages)"))
    print(f"|  Interpreter: {interp}")
    print(f"|  Work dir: {work_dir}")
    print("+" + "-" * 51)
    print()

    def _cascade_skips():
        """Mark pending stages whose dependencies have failed as skipped."""
        changed = True
        while changed:
            changed = False
            for s in pipeline.stages.values():
                if s.status == "pending" and any(d in failed for d in s.depends):
                    s.status = "skipped"
                    s.error = "Skipped (dependency failed)"
                    failed.add(s.id)
                    print(f"  [{s.id}] {_yellow('SKIP')} Skipped (dependency failed)")
                    changed = True

    def run_one(stage):
        input_file = _collect_input(stage, pipeline)
        prefix = f"  [{stage.id}]"
        print(f"{prefix} {_cyan('>')} Starting {_bold(stage.script)}...")
        ok = _run_stage(stage, interp, work_dir, input_file)
        dur = f"{stage.duration:.1f}s"
        with cond:
            in_flight.discard(stage.id)
            if ok:
                stage.status = "success"
                completed.add(stage.id)
                print(f"{prefix} {_green('OK')} Completed in {dur}")
            else:
                failed.add(stage.id)
                print(f"{prefix} {_red('FAIL')} Failed in {dur}: {stage.error}")
            _cascade_skips()
            cond.notify_all()  # wake scheduler to dispatch newly-ready stages

    with ThreadPoolExecutor(max_workers=max_parallel) as pool:
        while True:
            with cond:
                _cascade_skips()

                all_done = all(
                    s.status in ("success", "failed", "skipped")
                    for s in pipeline.stages.values()
                )
                if all_done:
                    break

                # Find stages that are ready and not already dispatched
                ready = [
                    s for s in pipeline.ready_stages(completed)
                    if s.id not in in_flight
                ]

                if not ready:
                    # Wait until a running stage finishes
                    cond.wait(timeout=5.0)
                    continue

                for stage in ready:
                    stage.status = "running"
                    in_flight.add(stage.id)
                    pool.submit(run_one, stage)

    return failed


def print_summary(pipeline, failed):
    """Print final pipeline summary."""
    print()
    print(_bold("--- Pipeline Summary ---"))
    total_time = sum(s.duration for s in pipeline.stages.values())

    for sid in pipeline.topo_order():
        s = pipeline.stages[sid]
        icon = {"success": _green("OK"), "failed": _red("FAIL"),
                "skipped": _yellow("SKIP"), "pending": _dim("--")}.get(s.status, "?")
        dur = f" ({s.duration:.1f}s)" if s.duration else ""
        err = f" — {s.error}" if s.error else ""
        print(f"  {icon} {s.id}{dur}{err}")

    ok = sum(1 for s in pipeline.stages.values() if s.status == "success")
    fail = sum(1 for s in pipeline.stages.values() if s.status in ("failed", "skipped"))
    print()
    print(f"  {_green(ok)} passed, {_red(fail) if fail else '0'} failed/skipped"
          f"  |  Total: {total_time:.1f}s")
    print()

    return 1 if failed else 0


# ─── Graph output ─────────────────────────────────────────────────────────────

def to_dot(pipeline):
    """Generate Graphviz DOT representation."""
    lines = [f'digraph "{pipeline.name}" {{', '  rankdir=LR;',
             '  node [shape=box, style=rounded, fontname="monospace"];']
    for s in pipeline.stages.values():
        label = f"{s.id}\\n{s.script}"
        lines.append(f'  "{s.id}" [label="{label}"];')
        for dep in s.depends:
            lines.append(f'  "{dep}" -> "{s.id}";')
    lines.append("}")
    return "\n".join(lines)


# ─── Template ─────────────────────────────────────────────────────────────────

TEMPLATE = {
    "name": "example-pipeline",
    "stages": [
        {"id": "load", "script": "load.srv", "args": ["input.csv"]},
        {"id": "clean", "script": "clean.srv", "depends": ["load"]},
        {"id": "analyze", "script": "analyze.srv", "depends": ["clean"], "retry": 1},
        {"id": "report", "script": "report.srv", "depends": ["analyze"], "timeout": 60},
        {"id": "notify", "script": "notify.srv", "depends": ["report"],
         "env": {"NOTIFY_EMAIL": "user@example.com"}}
    ]
}


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="sauravpipe",
        description="Pipeline runner for chaining sauravcode (.srv) scripts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  sauravpipe pipeline.json              Run a pipeline
  sauravpipe --chain a.srv b.srv c.srv  Linear chain
  sauravpipe --parallel a.srv b.srv     Parallel execution
  sauravpipe --dry-run pipeline.json    Validate only
  sauravpipe --dot pipeline.json        Graphviz DOT output
  sauravpipe --template                 Print example JSON"""
    )
    parser.add_argument("file", nargs="?", help="Pipeline JSON file")
    parser.add_argument("--chain", nargs="+", metavar="SCRIPT",
                        help="Chain scripts linearly (output of each feeds next)")
    parser.add_argument("--parallel", nargs="+", metavar="SCRIPT",
                        help="Run scripts in parallel (no dependencies)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate pipeline without executing")
    parser.add_argument("--dot", action="store_true",
                        help="Output Graphviz DOT graph")
    parser.add_argument("--template", action="store_true",
                        help="Print example pipeline JSON")
    parser.add_argument("--max-parallel", type=int, default=4,
                        help="Max concurrent stages (default: 4)")
    parser.add_argument("--work-dir", default=".",
                        help="Working directory for scripts")

    args = parser.parse_args()

    if args.template:
        print(json.dumps(TEMPLATE, indent=2))
        return

    # Build pipeline
    if args.chain:
        stages = []
        for i, script in enumerate(args.chain):
            sid = Path(script).stem
            dep = [stages[i - 1]["id"]] if i > 0 else []
            stages.append({"id": sid, "script": script, "depends": dep})
        data = {"name": "chain", "stages": stages}
    elif args.parallel:
        stages = [{"id": Path(s).stem, "script": s} for s in args.parallel]
        data = {"name": "parallel", "stages": stages}
    elif args.file:
        with open(args.file) as f:
            data = json.load(f)
    else:
        parser.print_help()
        sys.exit(1)

    try:
        pipe_stages = [Stage(s) for s in data["stages"]]
        pipeline = Pipeline(data.get("name", "unnamed"), pipe_stages)
    except (ValueError, KeyError) as e:
        print(_red(f"Pipeline error: {e}"), file=sys.stderr)
        sys.exit(1)

    if args.dot:
        print(to_dot(pipeline))
        return

    if args.dry_run:
        print(_green("OK") + f" Pipeline '{pipeline.name}' is valid"
              f" ({len(pipeline.stages)} stages)")
        order = pipeline.topo_order()
        print(f"  Execution order: {' -> '.join(order)}")
        for sid in order:
            s = pipeline.stages[sid]
            deps = f" (after {', '.join(s.depends)})" if s.depends else ""
            retry = f" [retry={s.retry}]" if s.retry else ""
            timeout = f" [timeout={s.timeout}s]" if s.timeout else ""
            print(f"    {sid}: {s.script}{deps}{retry}{timeout}")
        return

    work_dir = os.path.abspath(args.work_dir)
    failed = run_pipeline(pipeline, work_dir, args.max_parallel)
    code = print_summary(pipeline, failed)

    # Cleanup temp files
    for s in pipeline.stages.values():
        if s.output_file and os.path.isfile(s.output_file):
            try:
                os.remove(s.output_file)
            except OSError:
                pass

    sys.exit(code)


if __name__ == "__main__":
    main()
