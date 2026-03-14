#!/usr/bin/env python3
"""
sauravsnap — Snapshot testing for sauravcode programs.

Runs .srv files, captures their stdout/stderr output, and compares against
saved snapshots. Perfect for regression testing — ensures your programs
produce the same output after code changes.

Usage:
    python sauravsnap.py update [FILES...]    Capture and save snapshots
    python sauravsnap.py test [FILES...]      Test files against saved snapshots
    python sauravsnap.py review               Interactively review changed snapshots
    python sauravsnap.py list                 List all saved snapshots
    python sauravsnap.py clean                Remove snapshots for deleted files
    python sauravsnap.py diff FILE            Show diff between current and snapshot

Options:
    --snap-dir DIR     Snapshot directory (default: __snapshots__)
    --timeout SECS     Per-file timeout in seconds (default: 10)
    --verbose          Show passing tests too
    --json             Output results as JSON
    --pattern GLOB     Only process files matching pattern
    --update-on-fail   Auto-update snapshots that fail (use with caution)

Snapshot files are stored as .snap files alongside your code (or in a
configurable directory), making them easy to commit to version control.

Example workflow:
    # First time: capture snapshots
    python sauravsnap.py update tests/*.srv

    # After changes: verify nothing broke
    python sauravsnap.py test tests/*.srv

    # Something changed intentionally? Review and accept
    python sauravsnap.py review
"""

import os
import sys
import json
import glob
import hashlib
import subprocess
import time
import difflib
import argparse
from datetime import datetime

# Fix Windows console encoding for emoji output
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


# ─── Snapshot Store ────────────────────────────────────────────────

class SnapshotStore:
    """Manages reading/writing snapshot files."""

    def __init__(self, snap_dir="__snapshots__"):
        self.snap_dir = snap_dir

    def snap_path(self, srv_file):
        """Get the snapshot path for a given .srv file."""
        base = os.path.basename(srv_file)
        name = os.path.splitext(base)[0]
        return os.path.join(self.snap_dir, f"{name}.snap")

    def meta_path(self, srv_file):
        """Get the metadata path for a given .srv file."""
        base = os.path.basename(srv_file)
        name = os.path.splitext(base)[0]
        return os.path.join(self.snap_dir, f"{name}.snap.meta")

    def save(self, srv_file, stdout, stderr, exit_code, duration):
        """Save a snapshot for a .srv file."""
        os.makedirs(self.snap_dir, exist_ok=True)

        snap = self.snap_path(srv_file)
        meta = self.meta_path(srv_file)

        # The snapshot file contains the captured output
        with open(snap, 'w', encoding='utf-8') as f:
            f.write(stdout)

        # Metadata includes stderr, exit code, timing, source hash
        source_hash = self._hash_file(srv_file)
        metadata = {
            "file": os.path.abspath(srv_file),
            "source_hash": source_hash,
            "exit_code": exit_code,
            "stderr": stderr,
            "duration_ms": round(duration * 1000, 1),
            "captured_at": datetime.now().isoformat(),
            "sauravsnap_version": "1.0.0"
        }
        with open(meta, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2)

        return snap

    def load(self, srv_file):
        """Load a saved snapshot. Returns (stdout, metadata) or (None, None)."""
        snap = self.snap_path(srv_file)
        meta = self.meta_path(srv_file)

        if not os.path.exists(snap):
            return None, None

        with open(snap, 'r', encoding='utf-8') as f:
            stdout = f.read()

        metadata = {}
        if os.path.exists(meta):
            with open(meta, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

        return stdout, metadata

    def exists(self, srv_file):
        """Check if a snapshot exists for a file."""
        return os.path.exists(self.snap_path(srv_file))

    def list_all(self):
        """List all snapshot files."""
        if not os.path.exists(self.snap_dir):
            return []
        snaps = []
        for f in sorted(os.listdir(self.snap_dir)):
            if f.endswith('.snap') and not f.endswith('.snap.meta'):
                snaps.append(f)
        return snaps

    def remove(self, srv_file):
        """Remove snapshot for a file."""
        snap = self.snap_path(srv_file)
        meta = self.meta_path(srv_file)
        removed = False
        if os.path.exists(snap):
            os.remove(snap)
            removed = True
        if os.path.exists(meta):
            os.remove(meta)
        return removed

    def _hash_file(self, filepath):
        """SHA-256 hash of a file's contents."""
        h = hashlib.sha256()
        with open(filepath, 'rb') as f:
            h.update(f.read())
        return h.hexdigest()[:16]


# ─── Runner ────────────────────────────────────────────────────────

class SrvRunner:
    """Runs .srv files and captures output."""

    def __init__(self, timeout=10):
        self.timeout = timeout
        self._interpreter = self._find_interpreter()

    def _find_interpreter(self):
        """Find the sauravcode interpreter."""
        # Try relative paths first (development), then installed
        candidates = [
            os.path.join(os.path.dirname(__file__), 'saurav.py'),
            'saurav.py',
        ]
        for c in candidates:
            if os.path.exists(c):
                return [sys.executable, c]
        # Try installed command
        return ['sauravcode']

    def run(self, srv_file):
        """Run a .srv file and capture output. Returns (stdout, stderr, exit_code, duration)."""
        cmd = self._interpreter + [srv_file]
        start = time.time()
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=os.path.dirname(os.path.abspath(srv_file)) or '.'
            )
            duration = time.time() - start
            return result.stdout, result.stderr, result.returncode, duration
        except subprocess.TimeoutExpired:
            duration = time.time() - start
            return "", f"TIMEOUT after {self.timeout}s", -1, duration
        except FileNotFoundError:
            duration = time.time() - start
            return "", "sauravcode interpreter not found", -2, duration


# ─── Comparator ────────────────────────────────────────────────────

class SnapshotComparator:
    """Compares current output against saved snapshots."""

    @staticmethod
    def compare(actual, expected):
        """Compare two strings. Returns (match, diff_lines)."""
        if actual == expected:
            return True, []

        diff = list(difflib.unified_diff(
            expected.splitlines(keepends=True),
            actual.splitlines(keepends=True),
            fromfile='snapshot',
            tofile='actual',
            lineterm=''
        ))
        return False, diff

    @staticmethod
    def format_diff(diff_lines, color=True):
        """Format diff lines with optional ANSI colors."""
        if not color:
            return '\n'.join(diff_lines)

        colored = []
        for line in diff_lines:
            if line.startswith('+++') or line.startswith('---'):
                colored.append(f"\033[1m{line}\033[0m")
            elif line.startswith('+'):
                colored.append(f"\033[32m{line}\033[0m")
            elif line.startswith('-'):
                colored.append(f"\033[31m{line}\033[0m")
            elif line.startswith('@@'):
                colored.append(f"\033[36m{line}\033[0m")
            else:
                colored.append(line)
        return '\n'.join(colored)


# ─── Commands ──────────────────────────────────────────────────────

def resolve_files(file_args, pattern=None):
    """Resolve file arguments and glob patterns into .srv file paths."""
    files = []
    for arg in file_args:
        expanded = glob.glob(arg, recursive=True)
        if expanded:
            files.extend(expanded)
        elif os.path.exists(arg):
            files.append(arg)

    # Filter to .srv files only
    files = [f for f in files if f.endswith('.srv')]

    # Apply pattern filter if specified
    if pattern:
        import fnmatch
        files = [f for f in files if fnmatch.fnmatch(os.path.basename(f), pattern)]

    return sorted(set(files))


def cmd_update(files, store, runner, verbose=False):
    """Capture and save snapshots for given files."""
    if not files:
        print("No .srv files specified.")
        return 1

    results = {"updated": 0, "failed": 0, "files": []}

    for f in files:
        print(f"  📸 {os.path.basename(f)} ", end="", flush=True)
        stdout, stderr, exit_code, duration = runner.run(f)

        if exit_code == -2:
            print("✗ interpreter not found")
            results["failed"] += 1
            continue

        snap_path = store.save(f, stdout, stderr, exit_code, duration)
        lines = len(stdout.splitlines())
        print(f"✓ ({lines} lines, {duration*1000:.0f}ms)")
        results["updated"] += 1
        results["files"].append({
            "file": f,
            "lines": lines,
            "duration_ms": round(duration * 1000, 1),
            "exit_code": exit_code
        })

    print(f"\n  Updated {results['updated']} snapshot(s)")
    if results["failed"]:
        print(f"  Failed: {results['failed']}")
    return 0 if results["failed"] == 0 else 1


def cmd_test(files, store, runner, verbose=False, update_on_fail=False, as_json=False):
    """Test files against saved snapshots."""
    if not files:
        print("No .srv files specified.")
        return 1

    passed = 0
    failed = 0
    missing = 0
    errors = 0
    results = []

    for f in files:
        basename = os.path.basename(f)

        # Check if snapshot exists
        if not store.exists(f):
            print(f"  ⚠ {basename} — no snapshot (run 'update' first)")
            missing += 1
            results.append({"file": f, "status": "missing"})
            continue

        # Load saved snapshot
        expected_stdout, metadata = store.load(f)

        # Run the file
        stdout, stderr, exit_code, duration = runner.run(f)

        if exit_code == -2:
            print(f"  ✗ {basename} — interpreter not found")
            errors += 1
            results.append({"file": f, "status": "error", "error": "interpreter not found"})
            continue

        # Compare
        match, diff = SnapshotComparator.compare(stdout, expected_stdout)

        # Also compare exit codes
        expected_exit = metadata.get("exit_code", 0) if metadata else 0
        exit_match = exit_code == expected_exit

        if match and exit_match:
            passed += 1
            results.append({"file": f, "status": "pass", "duration_ms": round(duration * 1000, 1)})
            if verbose:
                print(f"  ✓ {basename} ({duration*1000:.0f}ms)")
        else:
            failed += 1
            result_entry = {"file": f, "status": "fail", "duration_ms": round(duration * 1000, 1)}

            print(f"  ✗ {basename}")
            if not match:
                print(SnapshotComparator.format_diff(diff))
                result_entry["diff"] = diff
            if not exit_match:
                print(f"    Exit code: expected {expected_exit}, got {exit_code}")
                result_entry["exit_expected"] = expected_exit
                result_entry["exit_actual"] = exit_code

            results.append(result_entry)

            if update_on_fail:
                store.save(f, stdout, stderr, exit_code, duration)
                print(f"    → snapshot updated")

    # Summary
    total = passed + failed + missing + errors
    print()
    if failed == 0 and missing == 0 and errors == 0:
        print(f"  ✅ All {passed} snapshot(s) match!")
    else:
        parts = []
        if passed: parts.append(f"{passed} passed")
        if failed: parts.append(f"{failed} failed")
        if missing: parts.append(f"{missing} missing")
        if errors: parts.append(f"{errors} errors")
        print(f"  {' | '.join(parts)} ({total} total)")

    if as_json:
        print(json.dumps({"passed": passed, "failed": failed, "missing": missing,
                          "errors": errors, "results": results}, indent=2))

    return 0 if (failed == 0 and errors == 0) else 1


def cmd_review(store, runner):
    """Interactively review snapshots whose source files have changed."""
    snaps = store.list_all()
    if not snaps:
        print("  No snapshots found.")
        return 0

    pending = []
    for snap_name in snaps:
        name = snap_name.replace('.snap', '')
        meta_path = os.path.join(store.snap_dir, f"{name}.snap.meta")
        if not os.path.exists(meta_path):
            continue
        with open(meta_path, 'r') as f:
            meta = json.load(f)

        src_file = meta.get("file", "")
        if not os.path.exists(src_file):
            continue

        current_hash = store._hash_file(src_file)
        if current_hash != meta.get("source_hash", ""):
            pending.append((src_file, meta))

    if not pending:
        print("  All snapshots are up to date with their source files.")
        return 0

    print(f"  {len(pending)} snapshot(s) have source changes:\n")

    for src_file, meta in pending:
        basename = os.path.basename(src_file)
        expected, _ = store.load(src_file)

        # Run current version
        stdout, stderr, exit_code, duration = runner.run(src_file)
        match, diff = SnapshotComparator.compare(stdout, expected)

        if match:
            print(f"  {basename} — source changed but output is identical")
            # Auto-update metadata hash
            store.save(src_file, stdout, stderr, exit_code, duration)
            print(f"    → metadata updated")
            continue

        print(f"  {basename} — output changed:")
        print(SnapshotComparator.format_diff(diff))
        print()

        try:
            answer = input(f"  Accept new snapshot for {basename}? [y/n/q] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Review cancelled.")
            return 0

        if answer == 'y':
            store.save(src_file, stdout, stderr, exit_code, duration)
            print(f"    → snapshot updated\n")
        elif answer == 'q':
            print("  Review cancelled.")
            return 0
        else:
            print(f"    → kept existing snapshot\n")

    return 0


def cmd_list(store):
    """List all saved snapshots."""
    snaps = store.list_all()
    if not snaps:
        print("  No snapshots found.")
        return 0

    print(f"  {len(snaps)} snapshot(s) in {store.snap_dir}/:\n")
    for snap_name in snaps:
        name = snap_name.replace('.snap', '')
        snap_path = os.path.join(store.snap_dir, snap_name)
        meta_path = os.path.join(store.snap_dir, f"{name}.snap.meta")

        size = os.path.getsize(snap_path)
        lines = 0
        with open(snap_path, 'r', encoding='utf-8') as f:
            lines = len(f.readlines())

        meta_info = ""
        if os.path.exists(meta_path):
            with open(meta_path, 'r') as f:
                meta = json.load(f)
            captured = meta.get("captured_at", "?")[:10]
            dur = meta.get("duration_ms", 0)
            meta_info = f"  ({captured}, {dur:.0f}ms)"

        print(f"    {name}.srv  →  {lines} lines, {size} bytes{meta_info}")

    return 0


def cmd_clean(store):
    """Remove snapshots for source files that no longer exist."""
    snaps = store.list_all()
    if not snaps:
        print("  No snapshots found.")
        return 0

    removed = 0
    for snap_name in snaps:
        name = snap_name.replace('.snap', '')
        meta_path = os.path.join(store.snap_dir, f"{name}.snap.meta")

        src_file = None
        if os.path.exists(meta_path):
            with open(meta_path, 'r') as f:
                meta = json.load(f)
            src_file = meta.get("file")

        if src_file and not os.path.exists(src_file):
            os.remove(os.path.join(store.snap_dir, snap_name))
            if os.path.exists(meta_path):
                os.remove(meta_path)
            print(f"  🗑 Removed {name}.snap (source file gone)")
            removed += 1

    if removed == 0:
        print("  All snapshots have existing source files.")
    else:
        print(f"\n  Removed {removed} orphaned snapshot(s).")
    return 0


def cmd_diff(srv_file, store, runner):
    """Show diff between current output and saved snapshot."""
    if not store.exists(srv_file):
        print(f"  No snapshot found for {os.path.basename(srv_file)}")
        print(f"  Run: python sauravsnap.py update {srv_file}")
        return 1

    expected, metadata = store.load(srv_file)
    stdout, stderr, exit_code, duration = runner.run(srv_file)

    match, diff = SnapshotComparator.compare(stdout, expected)

    if match:
        print(f"  ✓ Output matches snapshot for {os.path.basename(srv_file)}")
        # Check source hash
        current_hash = store._hash_file(srv_file)
        saved_hash = metadata.get("source_hash", "") if metadata else ""
        if current_hash != saved_hash:
            print(f"  ℹ Source file has changed (but output is identical)")
        return 0

    print(f"  Diff for {os.path.basename(srv_file)}:\n")
    print(SnapshotComparator.format_diff(diff))

    expected_exit = metadata.get("exit_code", 0) if metadata else 0
    if exit_code != expected_exit:
        print(f"\n  Exit code: expected {expected_exit}, got {exit_code}")

    return 1


# ─── Main ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog='sauravsnap',
        description='Snapshot testing for sauravcode programs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s update *.srv           Capture snapshots for all .srv files
  %(prog)s test *.srv             Test all files against snapshots
  %(prog)s test tests/*.srv -v    Verbose test output
  %(prog)s diff hello.srv         Show diff for a specific file
  %(prog)s review                 Interactively accept/reject changes
  %(prog)s list                   List all saved snapshots
  %(prog)s clean                  Remove orphaned snapshots
        """
    )

    parser.add_argument('command', choices=['update', 'test', 'review', 'list', 'clean', 'diff'],
                        help='Command to run')
    parser.add_argument('files', nargs='*', help='.srv files or glob patterns')
    parser.add_argument('--snap-dir', default='__snapshots__',
                        help='Snapshot directory (default: __snapshots__)')
    parser.add_argument('--timeout', type=int, default=10,
                        help='Per-file timeout in seconds (default: 10)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Show passing tests too')
    parser.add_argument('--json', action='store_true', dest='as_json',
                        help='Output results as JSON')
    parser.add_argument('--pattern', help='Only process files matching glob pattern')
    parser.add_argument('--update-on-fail', action='store_true',
                        help='Auto-update failing snapshots')

    args = parser.parse_args()

    store = SnapshotStore(args.snap_dir)
    runner = SrvRunner(timeout=args.timeout)

    print(f"\n  sauravsnap — snapshot testing for sauravcode\n")

    if args.command == 'update':
        files = resolve_files(args.files, args.pattern)
        return cmd_update(files, store, runner, args.verbose)

    elif args.command == 'test':
        files = resolve_files(args.files, args.pattern)
        return cmd_test(files, store, runner, args.verbose, args.update_on_fail, args.as_json)

    elif args.command == 'review':
        return cmd_review(store, runner)

    elif args.command == 'list':
        return cmd_list(store)

    elif args.command == 'clean':
        return cmd_clean(store)

    elif args.command == 'diff':
        if not args.files:
            print("  Usage: sauravsnap diff FILE.srv")
            return 1
        return cmd_diff(args.files[0], store, runner)


if __name__ == '__main__':
    sys.exit(main() or 0)
