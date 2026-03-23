#!/usr/bin/env python3
"""sauravwatch -- File watcher for sauravcode development.

Monitors .srv files and automatically re-runs them on save.
Uses polling (no external dependencies) for cross-platform support.

Usage:
    python sauravwatch.py <file.srv>               # Watch a single file
    python sauravwatch.py <file.srv> --interval 0.5 # Custom poll interval (seconds)
    python sauravwatch.py <dir>                     # Watch all .srv files in directory
    python sauravwatch.py <dir> --recursive         # Watch recursively
    python sauravwatch.py <file.srv> --clear        # Clear terminal before each run
    python sauravwatch.py <file.srv> --quiet        # Only show output, suppress banner
    python sauravwatch.py <file.srv> --test         # Run with sauravtest instead
    python sauravwatch.py <file.srv> --compile      # Compile with sauravcc instead
    python sauravwatch.py <file.srv> --stats        # Show run statistics
    python sauravwatch.py <file.srv> --notify       # Desktop notification on errors (if available)
    python sauravwatch.py <file.srv> --on-success "echo done"  # Run shell command on success
    python sauravwatch.py <file.srv> --on-failure "echo fail"  # Run shell command on failure
"""

import argparse
import os
import subprocess
import sys
import time
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


# ── ANSI colors ─────────────────────────────────────────────────────────
class Color:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    RED     = "\033[31m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    BLUE    = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN    = "\033[36m"
    GRAY    = "\033[90m"

    @staticmethod
    def supports_color():
        """Check if terminal supports color."""
        if os.environ.get("NO_COLOR"):
            return False
        if os.environ.get("FORCE_COLOR"):
            return True
        return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    @classmethod
    def disable(cls):
        for attr in ["RESET", "BOLD", "DIM", "RED", "GREEN", "YELLOW",
                      "BLUE", "MAGENTA", "CYAN", "GRAY"]:
            setattr(cls, attr, "")


if not Color.supports_color():
    Color.disable()


# ── File tracking ───────────────────────────────────────────────────────
class FileTracker:
    """Track file changes using content hashing + mtime."""

    def __init__(self):
        self._state = {}  # path -> (mtime, content_hash)

    def snapshot(self, paths):
        """Take a snapshot of current file states."""
        state = {}
        for p in paths:
            try:
                stat = os.stat(p)
                mtime = stat.st_mtime
                # Only re-hash if mtime changed (optimization)
                old = self._state.get(p)
                if old and old[0] == mtime:
                    state[p] = old
                else:
                    with open(p, "rb") as f:
                        h = hashlib.md5(f.read()).hexdigest()
                    state[p] = (mtime, h)
            except (OSError, IOError):
                pass  # File disappeared
        return state

    def detect_changes(self, paths):
        """Returns list of changed file paths since last check."""
        new_state = self.snapshot(paths)
        changed = []

        for p, (mtime, h) in new_state.items():
            old = self._state.get(p)
            if old is None:
                changed.append(("new", p))
            elif old[1] != h:
                changed.append(("modified", p))

        for p in self._state:
            if p not in new_state:
                changed.append(("deleted", p))

        self._state = new_state
        return changed


# ── File discovery ──────────────────────────────────────────────────────
def discover_srv_files(target, recursive=False):
    """Find all .srv files in target path."""
    target = Path(target)
    if target.is_file():
        if target.suffix == ".srv":
            return [str(target)]
        return []
    if target.is_dir():
        pattern = "**/*.srv" if recursive else "*.srv"
        return sorted(str(p) for p in target.glob(pattern))
    return []


# ── Run statistics ──────────────────────────────────────────────────────
class RunStats:
    """Track run statistics across watch session."""

    def __init__(self):
        self.total_runs = 0
        self.successes = 0
        self.failures = 0
        self.total_time_ms = 0
        self.run_history = []  # (timestamp, duration_ms, success, file)

    def record(self, duration_ms, success, file_path):
        self.total_runs += 1
        self.total_time_ms += duration_ms
        if success:
            self.successes += 1
        else:
            self.failures += 1
        self.run_history.append((
            datetime.now().isoformat(),
            duration_ms,
            success,
            file_path,
        ))

    @property
    def avg_time_ms(self):
        return self.total_time_ms / self.total_runs if self.total_runs else 0

    @property
    def success_rate(self):
        return (self.successes / self.total_runs * 100) if self.total_runs else 0

    def summary(self):
        lines = [
            f"\n{Color.BOLD}{'─' * 50}{Color.RESET}",
            f"{Color.BOLD}📊 Watch Session Statistics{Color.RESET}",
            f"{'─' * 50}",
            f"  Total runs:    {self.total_runs}",
            f"  Successes:     {Color.GREEN}{self.successes}{Color.RESET}",
            f"  Failures:      {Color.RED}{self.failures}{Color.RESET}",
            f"  Success rate:  {self.success_rate:.1f}%",
            f"  Avg duration:  {self.avg_time_ms:.0f}ms",
            f"  Total time:    {self.total_time_ms:.0f}ms",
            f"{'─' * 50}",
        ]
        return "\n".join(lines)

    def export_json(self):
        return json.dumps({
            "totalRuns": self.total_runs,
            "successes": self.successes,
            "failures": self.failures,
            "avgTimeMs": round(self.avg_time_ms, 1),
            "totalTimeMs": round(self.total_time_ms, 1),
            "successRate": round(self.success_rate, 1),
            "history": [
                {"time": t, "durationMs": d, "success": s, "file": f}
                for t, d, s, f in self.run_history
            ],
        }, indent=2)


# ── Desktop notification ────────────────────────────────────────────────
def send_notification(title, message):
    """Best-effort desktop notification (no external deps)."""
    try:
        if sys.platform == "darwin":
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{message}" with title "{title}"'],
                capture_output=True, timeout=5,
            )
        elif sys.platform == "win32":
            # PowerShell toast (Windows 10+)
            ps = (
                f'[Windows.UI.Notifications.ToastNotificationManager, '
                f'Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null; '
                f'$xml = [Windows.UI.Notifications.ToastNotificationManager]'
                f'::GetTemplateContent(0); '
                f'$text = $xml.GetElementsByTagName("text"); '
                f'$text.Item(0).AppendChild($xml.CreateTextNode("{title}: {message}")) | Out-Null; '
                f'[Windows.UI.Notifications.ToastNotificationManager]'
                f'::CreateToastNotifier("sauravwatch").Show('
                f'[Windows.UI.Notifications.ToastNotification]::new($xml))'
            )
            subprocess.run(["powershell", "-Command", ps],
                           capture_output=True, timeout=5)
        else:
            # Linux: try notify-send
            subprocess.run(
                ["notify-send", title, message],
                capture_output=True, timeout=5,
            )
    except Exception:
        pass  # Notifications are best-effort


# ── Runner ──────────────────────────────────────────────────────────────
def run_file(file_path, mode="run", debug=False):
    """Run a .srv file and return (success, output, duration_ms)."""
    start = time.time()

    # Determine the command
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if mode == "test":
        cmd = [sys.executable, os.path.join(script_dir, "sauravtest.py"), file_path]
    elif mode == "compile":
        cmd = [sys.executable, os.path.join(script_dir, "sauravcc.py"), file_path]
    else:
        cmd = [sys.executable, os.path.join(script_dir, "saurav.py"), file_path]

    if debug:
        cmd.append("--debug")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=os.path.dirname(os.path.abspath(file_path)) or ".",
        )
        duration_ms = (time.time() - start) * 1000
        output = result.stdout
        if result.stderr:
            output += result.stderr
        return result.returncode == 0, output.rstrip(), duration_ms
    except subprocess.TimeoutExpired:
        duration_ms = (time.time() - start) * 1000
        return False, "⏱️  Execution timed out (30s limit)", duration_ms
    except Exception as e:
        duration_ms = (time.time() - start) * 1000
        return False, f"Error: {e}", duration_ms


# ── Watch configuration ─────────────────────────────────────────────────
@dataclass
class WatchConfig:
    """Consolidated configuration for the watch loop, replacing loose params."""
    target: str
    mode: str = "run"           # "run" | "test" | "compile"
    interval: float = 1.0
    recursive: bool = False
    clear: bool = False
    quiet: bool = False
    debug: bool = False
    show_stats: bool = False
    notify: bool = False
    on_success: str | None = None
    on_failure: str | None = None

    @classmethod
    def from_args(cls, args) -> "WatchConfig":
        """Build config from argparse namespace."""
        mode = "run"
        if args.test:
            mode = "test"
        elif args.compile:
            mode = "compile"
        return cls(
            target=args.target,
            mode=mode,
            interval=args.interval,
            recursive=args.recursive,
            clear=args.clear,
            quiet=args.quiet,
            debug=args.debug,
            show_stats=args.stats,
            notify=args.notify,
            on_success=args.on_success,
            on_failure=args.on_failure,
        )


# ── Watcher ─────────────────────────────────────────────────────────────
def watch(args):
    """Main watch loop."""
    cfg = WatchConfig.from_args(args) if not isinstance(args, WatchConfig) else args

    # Resolve target
    target_path = Path(cfg.target)
    if not target_path.exists():
        print(f"{Color.RED}Error: '{cfg.target}' does not exist.{Color.RESET}")
        sys.exit(1)

    single_file = target_path.is_file()
    if single_file and target_path.suffix != ".srv":
        print(f"{Color.RED}Error: '{cfg.target}' is not a .srv file.{Color.RESET}")
        sys.exit(1)

    tracker = FileTracker()
    stats = RunStats()

    # Initial file list
    files = discover_srv_files(cfg.target, cfg.recursive)
    if not files:
        print(f"{Color.RED}Error: No .srv files found in '{cfg.target}'.{Color.RESET}")
        sys.exit(1)

    # Take initial snapshot
    tracker.snapshot(files)

    # Banner
    if not cfg.quiet:
        mode_label = {"run": "interpret", "test": "test", "compile": "compile"}[cfg.mode]
        print(f"{Color.BOLD}{Color.CYAN}🔭 sauravwatch{Color.RESET}")
        print(f"{Color.GRAY}   Mode:     {mode_label}{Color.RESET}")
        if single_file:
            print(f"{Color.GRAY}   Watching: {cfg.target}{Color.RESET}")
        else:
            print(f"{Color.GRAY}   Watching: {len(files)} .srv files in {cfg.target}"
                  f"{'(recursive)' if cfg.recursive else ''}{Color.RESET}")
        print(f"{Color.GRAY}   Interval: {cfg.interval}s{Color.RESET}")
        print(f"{Color.GRAY}   Press Ctrl+C to stop{Color.RESET}")
        print()

    # Do an initial run for single file mode
    if single_file:
        _execute_and_report(cfg.target, cfg, stats, initial=True)

    # Watch loop
    try:
        while True:
            time.sleep(cfg.interval)

            # Re-discover files (new files may appear)
            if not single_file:
                files = discover_srv_files(cfg.target, cfg.recursive)

            changes = tracker.detect_changes(files)
            if not changes:
                continue

            # Report changes
            for change_type, changed_path in changes:
                rel = os.path.relpath(changed_path)
                if change_type == "new":
                    if not cfg.quiet:
                        print(f"{Color.GREEN}+ New: {rel}{Color.RESET}")
                elif change_type == "modified":
                    if not cfg.quiet:
                        print(f"{Color.YELLOW}~ Modified: {rel}{Color.RESET}")
                elif change_type == "deleted":
                    if not cfg.quiet:
                        print(f"{Color.RED}- Deleted: {rel}{Color.RESET}")

            # Determine which files to run
            modified_files = [p for ct, p in changes
                              if ct in ("new", "modified") and p.endswith(".srv")]

            if single_file and modified_files:
                _execute_and_report(cfg.target, cfg, stats)
            elif modified_files:
                for f in modified_files:
                    _execute_and_report(f, cfg, stats)

    except KeyboardInterrupt:
        if not cfg.quiet:
            print(f"\n{Color.CYAN}👋 Stopped watching.{Color.RESET}")
        if cfg.show_stats and stats.total_runs > 0:
            print(stats.summary())


def _execute_and_report(file_path, cfg, stats, initial=False):
    """Execute a file and print results."""
    if cfg.clear:
        os.system("cls" if os.name == "nt" else "clear")

    now = datetime.now().strftime("%H:%M:%S")
    rel = os.path.relpath(file_path)

    if not cfg.quiet:
        label = "Initial run" if initial else "Re-running"
        print(f"\n{Color.BOLD}{'─' * 50}{Color.RESET}")
        print(f"{Color.GRAY}[{now}]{Color.RESET} {label}: "
              f"{Color.BOLD}{rel}{Color.RESET}")
        print(f"{'─' * 50}")

    success, output, duration_ms = run_file(file_path, cfg.mode, cfg.debug)
    stats.record(duration_ms, success, file_path)

    if output:
        print(output)

    if not cfg.quiet:
        if success:
            print(f"\n{Color.GREEN}✓ OK{Color.RESET} "
                  f"{Color.GRAY}({duration_ms:.0f}ms){Color.RESET}")
        else:
            print(f"\n{Color.RED}✗ FAILED{Color.RESET} "
                  f"{Color.GRAY}({duration_ms:.0f}ms){Color.RESET}")

    # Notifications
    if cfg.notify and not success:
        send_notification("sauravwatch", f"❌ {rel} failed")

    # Hooks
    if success and cfg.on_success:
        try:
            subprocess.run(cfg.on_success, shell=True, timeout=10)
        except Exception:
            pass
    elif not success and cfg.on_failure:
        try:
            subprocess.run(cfg.on_failure, shell=True, timeout=10)
        except Exception:
            pass


# ── Tests ───────────────────────────────────────────────────────────────
def _run_tests():
    """Built-in test suite for sauravwatch."""
    import tempfile
    import shutil

    passed = 0
    failed = 0
    errors = []

    def test(name, fn):
        nonlocal passed, failed
        try:
            fn()
            passed += 1
            print(f"  {Color.GREEN}✓{Color.RESET} {name}")
        except AssertionError as e:
            failed += 1
            errors.append((name, str(e)))
            print(f"  {Color.RED}✗{Color.RESET} {name}: {e}")
        except Exception as e:
            failed += 1
            errors.append((name, str(e)))
            print(f"  {Color.RED}✗{Color.RESET} {name}: {e}")

    print(f"\n{Color.BOLD}sauravwatch tests{Color.RESET}\n")

    # ── FileTracker tests ───────────────────────────────────────────
    def test_tracker_empty():
        t = FileTracker()
        changes = t.detect_changes([])
        assert changes == [], f"Expected no changes, got {changes}"

    def test_tracker_new_file():
        t = FileTracker()
        with tempfile.NamedTemporaryFile(suffix=".srv", delete=False, mode="w") as f:
            f.write('print "hello"\n')
            path = f.name
        try:
            changes = t.detect_changes([path])
            assert len(changes) == 1, f"Expected 1 change, got {len(changes)}"
            assert changes[0][0] == "new", f"Expected 'new', got {changes[0][0]}"
        finally:
            os.unlink(path)

    def test_tracker_no_change():
        t = FileTracker()
        with tempfile.NamedTemporaryFile(suffix=".srv", delete=False, mode="w") as f:
            f.write('print "hello"\n')
            path = f.name
        try:
            t.detect_changes([path])
            changes = t.detect_changes([path])
            assert changes == [], f"Expected no changes, got {changes}"
        finally:
            os.unlink(path)

    def test_tracker_modified():
        t = FileTracker()
        with tempfile.NamedTemporaryFile(suffix=".srv", delete=False, mode="w") as f:
            f.write('print "hello"\n')
            path = f.name
        try:
            t.detect_changes([path])
            time.sleep(0.1)
            with open(path, "w") as f:
                f.write('print "world"\n')
            # Force mtime difference
            os.utime(path, (time.time() + 1, time.time() + 1))
            changes = t.detect_changes([path])
            assert len(changes) == 1, f"Expected 1 change, got {len(changes)}"
            assert changes[0][0] == "modified"
        finally:
            os.unlink(path)

    def test_tracker_deleted():
        t = FileTracker()
        with tempfile.NamedTemporaryFile(suffix=".srv", delete=False, mode="w") as f:
            f.write('print "hello"\n')
            path = f.name
        t.detect_changes([path])
        os.unlink(path)
        changes = t.detect_changes([])
        assert any(ct == "deleted" for ct, _ in changes)

    test("FileTracker: empty", test_tracker_empty)
    test("FileTracker: new file", test_tracker_new_file)
    test("FileTracker: no change", test_tracker_no_change)
    test("FileTracker: modified", test_tracker_modified)
    test("FileTracker: deleted", test_tracker_deleted)

    # ── File discovery tests ────────────────────────────────────────
    def test_discover_single_file():
        with tempfile.NamedTemporaryFile(suffix=".srv", delete=False, mode="w") as f:
            f.write('x = 1\n')
            path = f.name
        try:
            result = discover_srv_files(path)
            assert result == [path]
        finally:
            os.unlink(path)

    def test_discover_non_srv():
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as f:
            f.write('hello\n')
            path = f.name
        try:
            result = discover_srv_files(path)
            assert result == []
        finally:
            os.unlink(path)

    def test_discover_directory():
        d = tempfile.mkdtemp()
        try:
            Path(d, "a.srv").write_text('x = 1\n')
            Path(d, "b.srv").write_text('y = 2\n')
            Path(d, "c.txt").write_text('ignore\n')
            result = discover_srv_files(d)
            assert len(result) == 2
            assert all(p.endswith(".srv") for p in result)
        finally:
            shutil.rmtree(d)

    def test_discover_recursive():
        d = tempfile.mkdtemp()
        try:
            Path(d, "top.srv").write_text('x = 1\n')
            sub = Path(d, "sub")
            sub.mkdir()
            Path(sub, "nested.srv").write_text('y = 2\n')
            non_recursive = discover_srv_files(d, recursive=False)
            recursive = discover_srv_files(d, recursive=True)
            assert len(non_recursive) == 1
            assert len(recursive) == 2
        finally:
            shutil.rmtree(d)

    def test_discover_nonexistent():
        result = discover_srv_files("/nonexistent/path")
        assert result == []

    test("discover: single .srv file", test_discover_single_file)
    test("discover: non-.srv file", test_discover_non_srv)
    test("discover: directory", test_discover_directory)
    test("discover: recursive", test_discover_recursive)
    test("discover: nonexistent path", test_discover_nonexistent)

    # ── RunStats tests ──────────────────────────────────────────────
    def test_stats_empty():
        s = RunStats()
        assert s.total_runs == 0
        assert s.avg_time_ms == 0
        assert s.success_rate == 0

    def test_stats_record():
        s = RunStats()
        s.record(100, True, "a.srv")
        s.record(200, False, "b.srv")
        assert s.total_runs == 2
        assert s.successes == 1
        assert s.failures == 1
        assert s.avg_time_ms == 150
        assert s.success_rate == 50.0

    def test_stats_summary():
        s = RunStats()
        s.record(50, True, "test.srv")
        text = s.summary()
        assert "Total runs" in text
        assert "1" in text

    def test_stats_json():
        s = RunStats()
        s.record(100, True, "test.srv")
        data = json.loads(s.export_json())
        assert data["totalRuns"] == 1
        assert data["successes"] == 1
        assert len(data["history"]) == 1

    test("RunStats: empty", test_stats_empty)
    test("RunStats: record", test_stats_record)
    test("RunStats: summary", test_stats_summary)
    test("RunStats: JSON export", test_stats_json)

    # ── Color tests ─────────────────────────────────────────────────
    def test_color_disable():
        # Save originals
        orig = Color.RED
        Color.disable()
        assert Color.RED == ""
        assert Color.GREEN == ""
        # Restore
        Color.RED = orig
        Color.GREEN = "\033[32m"

    test("Color: disable", test_color_disable)

    # ── run_file tests ──────────────────────────────────────────────
    def test_run_valid_file():
        with tempfile.NamedTemporaryFile(suffix=".srv", delete=False, mode="w",
                                         dir=".") as f:
            f.write('print "hello from watch"\n')
            path = f.name
        try:
            success, output, duration = run_file(path)
            assert success, f"Expected success, got output: {output}"
            assert "hello from watch" in output
            assert duration > 0
        finally:
            os.unlink(path)

    def test_run_syntax_error():
        with tempfile.NamedTemporaryFile(suffix=".srv", delete=False, mode="w",
                                         dir=".") as f:
            f.write('this is not valid sauravcode @@@ !!!\n')
            path = f.name
        try:
            success, output, duration = run_file(path)
            assert not success or "Error" in output or "error" in output.lower()
        finally:
            os.unlink(path)

    def test_run_nonexistent():
        success, output, duration = run_file("nonexistent_file_xyz.srv")
        assert not success

    test("run_file: valid .srv", test_run_valid_file)
    test("run_file: syntax error", test_run_syntax_error)
    test("run_file: nonexistent file", test_run_nonexistent)

    # ── Summary ─────────────────────────────────────────────────────
    total = passed + failed
    print(f"\n{'─' * 40}")
    if failed == 0:
        print(f"{Color.GREEN}{Color.BOLD}All {total} tests passed ✓{Color.RESET}")
    else:
        print(f"{Color.RED}{Color.BOLD}{failed}/{total} tests failed{Color.RESET}")
    print(f"{'─' * 40}")
    return failed == 0


# ── CLI ─────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        prog="sauravwatch",
        description="File watcher for sauravcode — auto-runs .srv files on save",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  sauravwatch hello.srv              Watch and run hello.srv on changes
  sauravwatch . --recursive          Watch all .srv files recursively
  sauravwatch demo.srv --clear       Clear screen before each run
  sauravwatch demo.srv --test        Run tests instead of interpreting
  sauravwatch demo.srv --stats       Show statistics on exit
  sauravwatch demo.srv --interval 2  Poll every 2 seconds
""",
    )
    parser.add_argument("target", nargs="?", default=None,
                        help="File or directory to watch")
    parser.add_argument("--interval", "-i", type=float, default=1.0,
                        help="Poll interval in seconds (default: 1.0)")
    parser.add_argument("--recursive", "-r", action="store_true",
                        help="Watch directories recursively")
    parser.add_argument("--clear", "-c", action="store_true",
                        help="Clear terminal before each run")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="Suppress banner and status messages")
    parser.add_argument("--test", "-t", action="store_true",
                        help="Run with sauravtest instead of interpreter")
    parser.add_argument("--compile", action="store_true",
                        help="Compile with sauravcc instead of interpreter")
    parser.add_argument("--debug", "-d", action="store_true",
                        help="Pass --debug flag to interpreter")
    parser.add_argument("--stats", "-s", action="store_true",
                        help="Show run statistics on exit")
    parser.add_argument("--notify", "-n", action="store_true",
                        help="Desktop notification on errors")
    parser.add_argument("--on-success", metavar="CMD",
                        help="Shell command to run on success")
    parser.add_argument("--on-failure", metavar="CMD",
                        help="Shell command to run on failure")
    parser.add_argument("--self-test", action="store_true",
                        help="Run built-in test suite")

    args = parser.parse_args()

    if args.self_test:
        success = _run_tests()
        sys.exit(0 if success else 1)

    if args.target is None:
        parser.print_help()
        sys.exit(1)

    watch(args)


if __name__ == "__main__":
    main()
