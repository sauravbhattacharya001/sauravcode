#!/usr/bin/env python3
"""sauravtest -- Test runner for sauravcode (.srv) programs.

Discovers and runs test functions in sauravcode source files,
reporting pass/fail results with timing and summary statistics.

Convention:
    - Test files match ``test_*.srv`` or ``*_test.srv``
    - Test functions start with ``test_``
    - Use ``assert`` statements to check results
    - Optional ``setup`` function runs before each test
    - Optional ``teardown`` function runs after each test

Example test file (``test_math.srv``)::

    function test_addition
        assert 1 + 1 == 2
        assert 10 + 20 == 30

    function test_string_len
        name = "sauravcode"
        assert len(name) == 10

    function test_list_ops
        items = [1, 2, 3]
        append items 4
        assert len(items) == 4

Run::

    python sauravtest.py                     # discover & run all tests
    python sauravtest.py test_math.srv       # run specific file
    python sauravtest.py tests/              # run tests in directory
    python sauravtest.py -v                  # verbose output
    python sauravtest.py -k "string"         # filter by name
    python sauravtest.py --failfast          # stop on first failure
    python sauravtest.py --json results.json # export results to JSON
"""

import argparse
import glob
import io
import json
import os
import sys
import time

# ---------------------------------------------------------------------------
# Import interpreter components from saurav.py
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import saurav as sv


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

class TestResult:
    """Result of a single test function execution."""

    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    SKIP = "SKIP"

    __slots__ = ("name", "file", "status", "duration", "message", "output")

    def __init__(self, name, file, status, duration=0.0, message="",
                 output=""):
        self.name = name
        self.file = file
        self.status = status
        self.duration = duration
        self.message = message
        self.output = output


class SuiteResult:
    """Aggregate results for a full test run."""

    __slots__ = ("results", "total_duration")

    def __init__(self):
        self.results = []
        self.total_duration = 0.0

    @property
    def passed(self):
        return sum(1 for r in self.results if r.status == TestResult.PASS)

    @property
    def failed(self):
        return sum(1 for r in self.results if r.status == TestResult.FAIL)

    @property
    def errors(self):
        return sum(1 for r in self.results if r.status == TestResult.ERROR)

    @property
    def skipped(self):
        return sum(1 for r in self.results if r.status == TestResult.SKIP)

    @property
    def total(self):
        return len(self.results)

    @property
    def ok(self):
        return self.failed == 0 and self.errors == 0


# ---------------------------------------------------------------------------
# ANSI helpers (shared via _termcolors)
# ---------------------------------------------------------------------------

from _termcolors import Colors as _Colors

_USE_COLOR = sys.stdout.isatty()
_TC = _Colors(_USE_COLOR)
_green = _TC.green
_red = _TC.red
_yellow = _TC.yellow
_cyan = _TC.cyan
_bold = _TC.bold
_dim = _TC.dim


# ---------------------------------------------------------------------------
# Test discovery
# ---------------------------------------------------------------------------

def discover_test_files(paths):
    """Find test files matching ``test_*.srv`` or ``*_test.srv``.

    Parameters
    ----------
    paths : list[str]
        Files or directories to search.  If empty, searches the current
        directory recursively.

    Returns
    -------
    list[str]
        Sorted list of absolute paths to test files.
    """
    if not paths:
        paths = ["."]

    files = set()
    for p in paths:
        if os.path.isfile(p):
            files.add(os.path.abspath(p))
        elif os.path.isdir(p):
            for pattern in ("test_*.srv", "*_test.srv"):
                for match in glob.glob(os.path.join(p, "**", pattern),
                                       recursive=True):
                    files.add(os.path.abspath(match))
        else:
            # Treat as glob pattern
            for match in glob.glob(p, recursive=True):
                if match.endswith(".srv"):
                    files.add(os.path.abspath(match))

    return sorted(files)


def discover_test_functions(interpreter):
    """Return names of functions starting with ``test_``.

    Parameters
    ----------
    interpreter : sv.Interpreter
        Interpreter with functions already loaded from parsing a file.

    Returns
    -------
    list[str]
        Sorted list of test function names.
    """
    return sorted(
        name for name in interpreter.functions if name.startswith("test_")
    )


# ---------------------------------------------------------------------------
# Test execution
# ---------------------------------------------------------------------------

def _load_file(filepath):
    """Parse a ``.srv`` file and return (interpreter, ast_nodes)."""
    with open(filepath, "r", encoding="utf-8") as f:
        source = f.read()

    tokens = list(sv.tokenize(source))
    parser = sv.Parser(tokens)
    ast_nodes = parser.parse()

    interpreter = sv.Interpreter()
    interpreter._source_dir = os.path.dirname(os.path.abspath(filepath))
    abs_path = os.path.abspath(filepath)
    interpreter._imported_modules.add(abs_path)

    # Execute top-level statements (defines functions, globals, etc.)
    for node in ast_nodes:
        if isinstance(node, sv.FunctionCallNode):
            interpreter.execute_function(node)
        else:
            interpreter.interpret(node)

    return interpreter


def _run_single_test(interpreter, func_name):
    """Execute a single test function, capturing output and timing.

    Returns a TestResult.
    """
    # Create a fresh interpreter copy so tests don't pollute each other
    test_interp = sv.Interpreter()
    test_interp.functions = dict(interpreter.functions)
    test_interp.variables = dict(interpreter.variables)
    test_interp.enums = dict(interpreter.enums)
    test_interp._source_dir = interpreter._source_dir
    test_interp._imported_modules = set(interpreter._imported_modules)

    # Run setup if it exists
    has_setup = "setup" in test_interp.functions
    has_teardown = "teardown" in test_interp.functions

    captured = io.StringIO()
    start = time.perf_counter()
    status = TestResult.PASS
    message = ""

    try:
        # Capture stdout
        old_stdout = sys.stdout
        sys.stdout = captured

        # Run setup body directly (not as a function call) so its
        # variables persist into the test scope.
        if has_setup:
            setup_func = test_interp.functions["setup"]
            for stmt in setup_func.body:
                test_interp.interpret(stmt)

        # Run the test function body directly so it sees setup variables
        test_func = test_interp.functions[func_name]
        for stmt in test_func.body:
            test_interp.interpret(stmt)

    except RuntimeError as e:
        err_msg = str(e)
        if "AssertionError" in err_msg or "AssertionError" in err_msg:
            status = TestResult.FAIL
            # Extract just the assertion message
            message = err_msg.replace("AssertionError: ", "")
        else:
            status = TestResult.ERROR
            message = err_msg
    except sv.ThrowSignal as e:
        status = TestResult.ERROR
        message = f"Uncaught throw: {e.message}"
    except Exception as e:
        status = TestResult.ERROR
        message = f"{type(e).__name__}: {e}"
    finally:
        elapsed = time.perf_counter() - start
        sys.stdout = old_stdout

        # Run teardown even if test failed
        if has_teardown:
            try:
                old_stdout2 = sys.stdout
                sys.stdout = io.StringIO()
                teardown_func = test_interp.functions["teardown"]
                for stmt in teardown_func.body:
                    test_interp.interpret(stmt)
            except Exception:
                pass
            finally:
                sys.stdout = old_stdout2

    output = captured.getvalue()
    return TestResult(func_name, "", status, elapsed, message, output)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_tests(paths, *, keyword=None, verbose=False, failfast=False,
              quiet=False):
    """Discover and run tests, returning a SuiteResult.

    Parameters
    ----------
    paths : list[str]
        Files or directories to search for tests.
    keyword : str or None
        Only run tests whose names contain this substring.
    verbose : bool
        Print each test's output and full error messages.
    failfast : bool
        Stop after the first failure or error.
    quiet : bool
        Suppress per-test output (only print summary).

    Returns
    -------
    SuiteResult
    """
    suite = SuiteResult()
    test_files = discover_test_files(paths)

    if not test_files:
        if not quiet:
            print(_yellow("No test files found."))
            print(_dim("  Test files should match test_*.srv or *_test.srv"))
        return suite

    if not quiet:
        print(_bold(f"sauravtest: discovered {len(test_files)} test file(s)"))
        print()

    suite_start = time.perf_counter()
    aborted = False

    for filepath in test_files:
        rel_path = os.path.relpath(filepath)
        if not quiet:
            print(_cyan(f"  {rel_path}"))

        # Load and parse the file
        try:
            interpreter = _load_file(filepath)
        except Exception as e:
            result = TestResult(
                name="<load>", file=rel_path,
                status=TestResult.ERROR, message=str(e),
            )
            suite.results.append(result)
            if not quiet:
                print(f"    {_red('ERROR')} loading file: {e}")
            if failfast:
                aborted = True
                break
            continue

        test_names = discover_test_functions(interpreter)

        if keyword:
            test_names = [n for n in test_names if keyword in n]

        if not test_names:
            if not quiet and verbose:
                print(_dim("    (no test functions found)"))
            continue

        for name in test_names:
            result = _run_single_test(interpreter, name)
            result.file = rel_path
            suite.results.append(result)

            if not quiet:
                _print_result(result, verbose)

            if failfast and result.status in (TestResult.FAIL,
                                               TestResult.ERROR):
                aborted = True
                break

        if aborted:
            break

    suite.total_duration = time.perf_counter() - suite_start

    if not quiet:
        print()
        _print_summary(suite, aborted)

    return suite


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def _print_result(result, verbose=False):
    """Print a single test result line."""
    ms = result.duration * 1000
    time_str = _dim(f"({ms:.0f}ms)")

    if result.status == TestResult.PASS:
        icon = _green("PASS")
    elif result.status == TestResult.FAIL:
        icon = _red("FAIL")
    elif result.status == TestResult.ERROR:
        icon = _red("ERROR")
    else:
        icon = _yellow("SKIP")

    print(f"    {icon}  {result.name} {time_str}")

    if result.status in (TestResult.FAIL, TestResult.ERROR) and result.message:
        print(f"          {_dim(result.message)}")

    if verbose and result.output.strip():
        for line in result.output.strip().splitlines():
            print(f"          {_dim('> ' + line)}")


def _print_summary(suite, aborted=False):
    """Print the final summary line."""
    parts = []
    if suite.passed:
        parts.append(_green(f"{suite.passed} passed"))
    if suite.failed:
        parts.append(_red(f"{suite.failed} failed"))
    if suite.errors:
        parts.append(_red(f"{suite.errors} errors"))
    if suite.skipped:
        parts.append(_yellow(f"{suite.skipped} skipped"))

    status_str = ", ".join(parts) if parts else "0 tests"
    total_ms = suite.total_duration * 1000

    if aborted:
        status_str += _yellow(" (stopped early --failfast)")

    bar = _green("=" * 50) if suite.ok else _red("=" * 50)
    label = _bold(_green("ALL PASSED")) if suite.ok else _bold(_red("FAILURES"))

    print(bar)
    print(f"  {label}  {status_str}  {_dim(f'in {total_ms:.0f}ms')}")
    print(bar)


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------

def export_json(suite, output_path):
    """Export test results to a JSON file.

    Parameters
    ----------
    suite : SuiteResult
    output_path : str
    """
    data = {
        "summary": {
            "total": suite.total,
            "passed": suite.passed,
            "failed": suite.failed,
            "errors": suite.errors,
            "skipped": suite.skipped,
            "duration_ms": round(suite.total_duration * 1000, 1),
            "ok": suite.ok,
        },
        "results": [
            {
                "name": r.name,
                "file": r.file,
                "status": r.status,
                "duration_ms": round(r.duration * 1000, 2),
                "message": r.message,
                "output": r.output,
            }
            for r in suite.results
        ],
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\nResults exported to {output_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="sauravtest",
        description="Test runner for sauravcode (.srv) programs.",
        epilog="Convention: test files match test_*.srv or *_test.srv; "
               "test functions start with test_.",
    )
    parser.add_argument(
        "paths", nargs="*", default=[],
        help="Files or directories to test (default: current directory)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Show captured output and full error details",
    )
    parser.add_argument(
        "-k", "--keyword", type=str, default=None,
        help="Only run tests whose name contains KEYWORD",
    )
    parser.add_argument(
        "--failfast", action="store_true",
        help="Stop on first failure or error",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="Only print final summary",
    )
    parser.add_argument(
        "--json", type=str, default=None, metavar="FILE",
        help="Export results to JSON file",
    )
    parser.add_argument(
        "--no-color", action="store_true",
        help="Disable colored output",
    )

    args = parser.parse_args(argv)

    if args.no_color:
        global _USE_COLOR, _TC, _green, _red, _yellow, _cyan, _bold, _dim
        _USE_COLOR = False
        _TC = _Colors(False)
        _green = _TC.green
        _red = _TC.red
        _yellow = _TC.yellow
        _cyan = _TC.cyan
        _bold = _TC.bold
        _dim = _TC.dim

    suite = run_tests(
        args.paths,
        keyword=args.keyword,
        verbose=args.verbose,
        failfast=args.failfast,
        quiet=args.quiet,
    )

    if args.json:
        export_json(suite, args.json)

    sys.exit(0 if suite.ok else 1)


if __name__ == "__main__":
    main()
