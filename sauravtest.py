#!/usr/bin/env python3
"""sauravtest — built-in test runner for sauravcode (.srv) files.

Discovers and runs test functions in .srv files, reporting pass/fail
with colors, timing, and summary statistics.

Usage:
    python sauravtest.py                        # run all test_*.srv in current dir
    python sauravtest.py tests/                 # run all test_*.srv in directory
    python sauravtest.py test_math.srv          # run specific file
    python sauravtest.py -p "test_*" dir/       # custom file pattern
    python sauravtest.py -v                     # verbose output
    python sauravtest.py --fail-fast            # stop on first failure
    python sauravtest.py --filter "test_add"    # only run matching test functions

Test Convention:
    - Test files: any .srv file (or matching -p pattern)
    - Test functions: functions whose name starts with "test_"
    - Assertions: use the built-in 'assert' keyword
    - Setup: a function named "setup" runs before each test
    - Teardown: a function named "teardown" runs after each test

Example test file (test_math.srv):

    function test_add
        assert add(2, 3) == 5 "2+3 should be 5"

    function test_negative
        assert add(-1, 1) == 0

    function add x y
        return x + y
"""

import argparse
import glob
import io
import os
import sys
import time
import re
import contextlib

# Add the directory containing saurav.py to the path
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

from saurav import (
    tokenize, Parser, Interpreter, FunctionCallNode, FunctionNode,
    ThrowSignal, format_value,
)


# ── Colors ───────────────────────────────────────────────────────────────

class _Colors:
    """ANSI color codes (disabled when not a TTY)."""
    def __init__(self):
        use_color = hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()
        if os.environ.get('NO_COLOR'):
            use_color = False
        if os.environ.get('FORCE_COLOR'):
            use_color = True
        self.GREEN = '\033[32m' if use_color else ''
        self.RED = '\033[31m' if use_color else ''
        self.YELLOW = '\033[33m' if use_color else ''
        self.CYAN = '\033[36m' if use_color else ''
        self.BOLD = '\033[1m' if use_color else ''
        self.DIM = '\033[2m' if use_color else ''
        self.RESET = '\033[0m' if use_color else ''

C = _Colors()


# ── Test Result ──────────────────────────────────────────────────────────

class TestResult:
    """Result of a single test function execution."""
    __slots__ = ('name', 'file', 'passed', 'error', 'duration_ms', 'output')

    def __init__(self, name: str, file: str):
        self.name = name
        self.file = file
        self.passed = True
        self.error = None
        self.duration_ms = 0.0
        self.output = ''


# ── Test Runner ──────────────────────────────────────────────────────────

class TestRunner:
    """Discovers and runs sauravcode test functions."""

    def __init__(self, verbose=False, fail_fast=False, filter_pattern=None):
        self.verbose = verbose
        self.fail_fast = fail_fast
        self.filter_re = re.compile(filter_pattern) if filter_pattern else None
        self.results: list[TestResult] = []

    def discover(self, paths: list[str], pattern='test_*.srv') -> list[str]:
        """Find test files matching the pattern."""
        files = []
        for path in paths:
            if os.path.isfile(path) and path.endswith('.srv'):
                files.append(os.path.abspath(path))
            elif os.path.isdir(path):
                for f in sorted(glob.glob(os.path.join(path, pattern))):
                    files.append(os.path.abspath(f))
                # Also search recursively
                for f in sorted(glob.glob(os.path.join(path, '**', pattern), recursive=True)):
                    abspath = os.path.abspath(f)
                    if abspath not in files:
                        files.append(abspath)
        return files

    def run_file(self, filepath: str) -> list[TestResult]:
        """Parse a .srv file and run all test_ functions in it."""
        rel_path = os.path.relpath(filepath)

        try:
            with open(filepath, 'r') as f:
                code = f.read()
        except Exception as e:
            result = TestResult('(file)', rel_path)
            result.passed = False
            result.error = f"Cannot read file: {e}"
            self.results.append(result)
            return [result]

        # Parse the file
        try:
            tokens = list(tokenize(code))
            parser = Parser(tokens)
            ast_nodes = parser.parse()
        except Exception as e:
            result = TestResult('(parse)', rel_path)
            result.passed = False
            result.error = f"Parse error: {e}"
            self.results.append(result)
            return [result]

        # Create interpreter and load all definitions first
        interpreter = Interpreter()
        interpreter._source_dir = os.path.dirname(os.path.abspath(filepath))

        # Execute top-level code (defines functions, classes, variables)
        try:
            for node in ast_nodes:
                if isinstance(node, FunctionCallNode):
                    # Skip top-level function calls that aren't test-related
                    # (e.g., print statements in the test file)
                    interpreter.execute_function(node)
                else:
                    interpreter.interpret(node)
        except (ThrowSignal, RuntimeError) as e:
            result = TestResult('(setup)', rel_path)
            result.passed = False
            result.error = f"Top-level error: {e}"
            self.results.append(result)
            return [result]

        # Find test functions
        test_funcs = []
        for name, func in interpreter.functions.items():
            if name.startswith('test_'):
                if self.filter_re and not self.filter_re.search(name):
                    continue
                test_funcs.append(name)

        if not test_funcs:
            # Also run files that have asserts at top-level (assertion-only tests)
            # Count the file as a single test if it has assert statements
            has_asserts = 'assert ' in code or 'assert(' in code
            if has_asserts:
                result = TestResult('(assertions)', rel_path)
                result.passed = True  # If we got here without error, assertions passed
                result.duration_ms = 0
                self.results.append(result)
                return [result]
            return []

        test_funcs.sort()
        has_setup = 'setup' in interpreter.functions
        has_teardown = 'teardown' in interpreter.functions
        file_results = []

        for test_name in test_funcs:
            result = TestResult(test_name, rel_path)

            # Run setup
            if has_setup:
                try:
                    setup_call = FunctionCallNode('setup', [])
                    interpreter.execute_function(setup_call)
                except Exception as e:
                    result.passed = False
                    result.error = f"setup() failed: {e}"
                    self.results.append(result)
                    file_results.append(result)
                    self._print_result(result)
                    if self.fail_fast:
                        return file_results
                    continue

            # Capture stdout and run test
            captured = io.StringIO()
            t0 = time.perf_counter()
            try:
                with contextlib.redirect_stdout(captured):
                    call_node = FunctionCallNode(test_name, [])
                    interpreter.execute_function(call_node)
                result.passed = True
            except ThrowSignal as e:
                result.passed = False
                msg = e.message
                if isinstance(msg, float) and msg == int(msg):
                    msg = int(msg)
                result.error = f"Uncaught error: {msg}"
            except RuntimeError as e:
                result.passed = False
                result.error = str(e)
            except Exception as e:
                result.passed = False
                result.error = f"{type(e).__name__}: {e}"
            finally:
                result.duration_ms = (time.perf_counter() - t0) * 1000
                result.output = captured.getvalue()

            # Run teardown
            if has_teardown:
                try:
                    teardown_call = FunctionCallNode('teardown', [])
                    interpreter.execute_function(teardown_call)
                except Exception:
                    pass  # Don't let teardown errors mask test errors

            self.results.append(result)
            file_results.append(result)
            self._print_result(result)

            if self.fail_fast and not result.passed:
                return file_results

        return file_results

    def _print_result(self, result: TestResult):
        """Print a single test result."""
        if result.passed:
            status = f"{C.GREEN}PASS{C.RESET}"
        else:
            status = f"{C.RED}FAIL{C.RESET}"

        timing = f"{C.DIM}{result.duration_ms:.1f}ms{C.RESET}"
        print(f"  {status}  {result.name} {timing}")

        if not result.passed and result.error:
            # Indent error message
            for line in result.error.split('\n'):
                print(f"         {C.RED}{line}{C.RESET}")

        if self.verbose and result.output:
            for line in result.output.rstrip().split('\n'):
                print(f"         {C.DIM}│ {line}{C.RESET}")

    def run_all(self, files: list[str]) -> bool:
        """Run all test files and print summary. Returns True if all passed."""
        if not files:
            print(f"{C.YELLOW}No test files found.{C.RESET}")
            return True

        total_start = time.perf_counter()

        for filepath in files:
            rel = os.path.relpath(filepath)
            print(f"\n{C.BOLD}{C.CYAN}{rel}{C.RESET}")
            self.run_file(filepath)
            if self.fail_fast and any(not r.passed for r in self.results):
                break

        total_ms = (time.perf_counter() - total_start) * 1000

        # Summary
        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed)
        total = len(self.results)

        print()
        print("-" * 50)

        if failed == 0:
            print(f"{C.GREEN}{C.BOLD}All {total} tests passed{C.RESET} {C.DIM}({total_ms:.0f}ms){C.RESET}")
        else:
            print(f"{C.RED}{C.BOLD}{failed} failed{C.RESET}, "
                  f"{C.GREEN}{passed} passed{C.RESET}, "
                  f"{total} total {C.DIM}({total_ms:.0f}ms){C.RESET}")

            # List failures
            print(f"\n{C.RED}Failures:{C.RESET}")
            for r in self.results:
                if not r.passed:
                    print(f"  {C.RED}x{C.RESET} {r.file} :: {r.name}")
                    if r.error:
                        print(f"    {C.DIM}{r.error}{C.RESET}")

        return failed == 0


# ── CLI ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog='sauravtest',
        description='sauravcode test runner — discover and run test functions in .srv files',
    )
    parser.add_argument('paths', nargs='*', default=['.'],
                        help='Files or directories to search (default: current dir)')
    parser.add_argument('-p', '--pattern', default='test_*.srv',
                        help='File glob pattern (default: test_*.srv)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Show captured stdout from tests')
    parser.add_argument('--fail-fast', '-x', action='store_true',
                        help='Stop on first failure')
    parser.add_argument('--filter', '-k', metavar='PATTERN',
                        help='Only run tests matching regex pattern')
    parser.add_argument('--list', '-l', action='store_true',
                        help='List discovered tests without running them')
    parser.add_argument('--all', '-a', action='store_true',
                        help='Run ALL .srv files, not just test_*.srv')

    args = parser.parse_args()

    if args.all:
        args.pattern = '*.srv'

    runner = TestRunner(
        verbose=args.verbose,
        fail_fast=args.fail_fast,
        filter_pattern=args.filter,
    )

    files = runner.discover(args.paths, pattern=args.pattern)

    if args.list:
        print(f"Discovered {len(files)} test file(s):")
        for f in files:
            print(f"  {os.path.relpath(f)}")
        return 0

    print(f"{C.BOLD}sauravtest{C.RESET} — sauravcode test runner")
    print(f"Discovered {len(files)} test file(s)")

    success = runner.run_all(files)
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
