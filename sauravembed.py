#!/usr/bin/env python3
"""sauravembed -- Embed and run sauravcode from Python.

A clean API for running .srv code inside Python programs, passing data
in/out, registering Python callbacks, and capturing output.

Quick start::

    from sauravembed import SauravEmbed

    srv = SauravEmbed()
    srv.set("name", "World")
    result = srv.run('greet = f"Hello {name}"')
    print(srv.get("greet"))       # "Hello World"
    print(result.output)          # captured stdout
    print(result.variables)       # all top-level variables

Features:
  - Run .srv code strings or files from Python
  - Inject Python values as sauravcode variables
  - Retrieve sauravcode values back into Python
  - Register Python functions callable from .srv code
  - Capture stdout/stderr output
  - Persistent interpreter state across multiple run() calls
  - Error handling with structured result objects
  - Context manager support (with statement)
  - Multiple isolated instances

Usage::

    # Basic execution
    srv = SauravEmbed()
    result = srv.run('x = 42')
    assert srv.get("x") == 42

    # Inject values
    srv.set("items", [1, 2, 3])
    srv.run('total = 0\\nfor item in items\\n    total = total + item')
    assert srv.get("total") == 6

    # Register Python functions
    srv.register("double", lambda x: x * 2)
    srv.run('y = double 21')
    assert srv.get("y") == 42

    # Run files
    result = srv.run_file("script.srv")

    # Capture output
    result = srv.run('print "hello"')
    assert result.output.strip() == "hello"

    # Error handling
    result = srv.run('throw "oops"')
    assert result.error is not None

    # Context manager
    with SauravEmbed() as srv:
        srv.run('x = 1')
"""

import io
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable

# Add the script directory to path so we can import saurav
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

from saurav import (
    tokenize,
    Parser,
    Interpreter,
    FunctionCallNode,
    ThrowSignal,
)


@dataclass
class RunResult:
    """Result of a sauravcode execution."""

    success: bool
    """Whether execution completed without errors."""

    output: str = ""
    """Captured stdout output."""

    error: str | None = None
    """Error message if execution failed, else None."""

    error_type: str | None = None
    """Error classification: 'throw', 'runtime', 'syntax', or None."""

    return_value: Any = None
    """Return value from the last top-level function call, if any."""

    elapsed_ms: float = 0.0
    """Wall-clock execution time in milliseconds."""

    variables: dict[str, Any] = field(default_factory=dict)
    """Snapshot of all top-level variables after execution."""

    def __bool__(self) -> bool:
        """Truthy if execution succeeded."""
        return self.success

    def __repr__(self) -> str:
        if self.success:
            return f"RunResult(success=True, vars={len(self.variables)}, elapsed={self.elapsed_ms:.1f}ms)"
        return f"RunResult(success=False, error={self.error!r})"


class SauravEmbed:
    """Embeddable sauravcode interpreter for Python integration.

    Each instance maintains its own interpreter state (variables,
    functions, enums).  Use multiple instances for isolation.

    Parameters
    ----------
    source_dir : str or None
        Directory for resolving ``import`` statements in .srv code.
        Defaults to the current working directory.
    capture_output : bool
        If True (default), stdout from ``print`` statements is captured
        in ``RunResult.output`` instead of going to the console.
    """

    def __init__(
        self,
        source_dir: str | None = None,
        capture_output: bool = True,
    ) -> None:
        self._interp = Interpreter()
        self._interp._source_dir = source_dir or os.getcwd()
        self._capture = capture_output
        self._registered: dict[str, Callable] = {}
        self._run_count = 0

    # ── Context Manager ──────────────────────────────────────────

    def __enter__(self) -> "SauravEmbed":
        return self

    def __exit__(self, *_: Any) -> None:
        self.reset()

    # ── Variable Access ──────────────────────────────────────────

    def set(self, name: str, value: Any) -> "SauravEmbed":
        """Inject a Python value as a sauravcode variable.

        Supported types: int, float, str, bool, None, list, dict.
        Python ints are converted to float (sauravcode's numeric type).
        Python dicts become sauravcode maps.

        Returns self for chaining.
        """
        self._interp.variables[name] = self._to_srv(value)
        return self

    def get(self, name: str, default: Any = None) -> Any:
        """Retrieve a sauravcode variable's value.

        Returns *default* if the variable doesn't exist.
        Values are converted back to natural Python types.
        """
        if name not in self._interp.variables:
            return default
        return self._from_srv(self._interp.variables[name])

    def get_all(self) -> dict[str, Any]:
        """Return a copy of all top-level variables."""
        return {k: self._from_srv(v) for k, v in self._interp.variables.items()}

    def has(self, name: str) -> bool:
        """Check if a variable exists."""
        return name in self._interp.variables

    def delete(self, name: str) -> bool:
        """Remove a variable.  Returns True if it existed."""
        if name in self._interp.variables:
            del self._interp.variables[name]
            return True
        return False

    def variables(self) -> list[str]:
        """List all variable names."""
        return list(self._interp.variables.keys())

    # ── Function Registration ────────────────────────────────────

    def register(self, name: str, fn: Callable) -> "SauravEmbed":
        """Register a Python function callable from sauravcode.

        The function will be available by *name* in .srv code.
        Arguments are passed positionally.

        Example::

            srv.register("add", lambda a, b: a + b)
            srv.run('result = add 3 4')
            assert srv.get("result") == 7

        Returns self for chaining.
        """
        self._registered[name] = fn
        # Register as a builtin — builtins receive a list of evaluated args
        self._interp.builtins[name] = self._wrap_python_fn(fn)
        return self

    def unregister(self, name: str) -> bool:
        """Remove a registered Python function."""
        removed = False
        if name in self._registered:
            del self._registered[name]
            removed = True
        if name in self._interp.builtins:
            del self._interp.builtins[name]
            removed = True
        return removed

    def registered_functions(self) -> list[str]:
        """List names of registered Python functions."""
        return list(self._registered.keys())

    # ── Execution ────────────────────────────────────────────────

    def run(self, code: str) -> RunResult:
        """Parse and execute a sauravcode string.

        Execution is cumulative — variables and functions from previous
        ``run()`` calls persist.  Use ``reset()`` to start fresh.

        Parameters
        ----------
        code : str
            Sauravcode source code to execute.

        Returns
        -------
        RunResult
            Structured result with output, errors, variables, timing.
        """
        self._run_count += 1
        start = time.perf_counter()

        # Parse
        try:
            tokens = tokenize(code)
            parser = Parser(tokens)
            ast_nodes = parser.parse()
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return RunResult(
                success=False,
                error=str(e),
                error_type="syntax",
                elapsed_ms=round(elapsed, 2),
                variables=self.get_all(),
            )

        # Execute with optional output capture
        output_buf = io.StringIO() if self._capture else None
        old_stdout = sys.stdout

        try:
            if output_buf is not None:
                sys.stdout = output_buf

            return_value = None
            for node in ast_nodes:
                if isinstance(node, FunctionCallNode):
                    return_value = self._interp.execute_function(node)
                else:
                    self._interp.interpret(node)

            elapsed = (time.perf_counter() - start) * 1000
            return RunResult(
                success=True,
                output=output_buf.getvalue() if output_buf else "",
                return_value=self._from_srv(return_value),
                elapsed_ms=round(elapsed, 2),
                variables=self.get_all(),
            )

        except ThrowSignal as e:
            elapsed = (time.perf_counter() - start) * 1000
            msg = e.message
            if isinstance(msg, float) and msg == int(msg):
                msg = int(msg)
            return RunResult(
                success=False,
                output=output_buf.getvalue() if output_buf else "",
                error=f"Uncaught error: {msg}",
                error_type="throw",
                elapsed_ms=round(elapsed, 2),
                variables=self.get_all(),
            )

        except RuntimeError as e:
            elapsed = (time.perf_counter() - start) * 1000
            return RunResult(
                success=False,
                output=output_buf.getvalue() if output_buf else "",
                error=str(e),
                error_type="runtime",
                elapsed_ms=round(elapsed, 2),
                variables=self.get_all(),
            )

        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return RunResult(
                success=False,
                output=output_buf.getvalue() if output_buf else "",
                error=f"{type(e).__name__}: {e}",
                error_type="runtime",
                elapsed_ms=round(elapsed, 2),
                variables=self.get_all(),
            )

        finally:
            if output_buf is not None:
                sys.stdout = old_stdout

    def run_file(self, path: str) -> RunResult:
        """Execute a .srv file.

        Sets the interpreter's source directory to the file's parent
        for correct ``import`` resolution.

        Parameters
        ----------
        path : str
            Path to a .srv file.

        Returns
        -------
        RunResult
        """
        abs_path = os.path.abspath(path)
        if not os.path.isfile(abs_path):
            return RunResult(
                success=False,
                error=f"File not found: {path}",
                error_type="runtime",
            )

        old_source_dir = self._interp._source_dir
        self._interp._source_dir = os.path.dirname(abs_path)
        self._interp._imported_modules.add(abs_path)

        try:
            with open(abs_path, encoding="utf-8") as f:
                code = f.read()
            return self.run(code)
        finally:
            self._interp._source_dir = old_source_dir

    def eval(self, expression: str) -> Any:
        """Evaluate a sauravcode expression and return the result.

        Unlike ``run()``, this expects a single expression and returns
        its value directly (not wrapped in RunResult).  Raises on error.

        Parameters
        ----------
        expression : str
            A single sauravcode expression.

        Returns
        -------
        Any
            The evaluated Python value.

        Raises
        ------
        ValueError
            If the expression fails to parse or evaluate.
        """
        temp = "__embed_eval_result__"
        result = self.run(f"{temp} = {expression}")
        if not result.success:
            raise ValueError(result.error)
        value = self.get(temp)
        self.delete(temp)
        return value

    # ── State Management ─────────────────────────────────────────

    def reset(self) -> "SauravEmbed":
        """Reset interpreter state (variables, functions, enums).

        Registered Python functions are preserved.
        Returns self for chaining.
        """
        source_dir = self._interp._source_dir
        self._interp = Interpreter()
        self._interp._source_dir = source_dir
        self._run_count = 0

        # Re-register Python functions
        for name, fn in self._registered.items():
            self._interp.builtins[name] = self._wrap_python_fn(fn)

        return self

    @property
    def run_count(self) -> int:
        """Number of run() calls since creation or last reset()."""
        return self._run_count

    @property
    def function_names(self) -> list[str]:
        """List all defined function names (sauravcode + registered Python)."""
        names = set(self._interp.functions.keys())
        names.update(self._registered.keys())
        return sorted(names)

    @property
    def enum_names(self) -> list[str]:
        """List all defined enum names."""
        return list(self._interp.enums.keys())

    # ── Bulk Operations ──────────────────────────────────────────

    def set_many(self, mapping: dict[str, Any]) -> "SauravEmbed":
        """Inject multiple variables at once.

        Parameters
        ----------
        mapping : dict
            Name -> value pairs.

        Returns self for chaining.
        """
        for name, value in mapping.items():
            self.set(name, value)
        return self

    def run_many(self, codes: list[str]) -> list[RunResult]:
        """Execute multiple code strings sequentially.

        Stops at the first error unless all succeed.

        Parameters
        ----------
        codes : list[str]
            List of sauravcode strings.

        Returns
        -------
        list[RunResult]
            One result per code string executed (may be shorter than
            *codes* if an error stops execution early).
        """
        results = []
        for code in codes:
            result = self.run(code)
            results.append(result)
            if not result.success:
                break
        return results

    # ── Type Conversion ──────────────────────────────────────────

    @staticmethod
    def _to_srv(value: Any) -> Any:
        """Convert a Python value to sauravcode representation."""
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return float(value)  # sauravcode uses float for all numbers
        if isinstance(value, (float, str)):
            return value
        if isinstance(value, (list, tuple)):
            return [SauravEmbed._to_srv(item) for item in value]
        if isinstance(value, dict):
            return {
                SauravEmbed._to_srv(k): SauravEmbed._to_srv(v)
                for k, v in value.items()
            }
        # Fall back — pass through and let the interpreter handle it
        return value

    @staticmethod
    def _from_srv(value: Any) -> Any:
        """Convert a sauravcode value to natural Python type."""
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, float):
            # Convert whole floats to int for cleaner Python values
            if value == int(value) and abs(value) < 2**53:
                return int(value)
            return value
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return [SauravEmbed._from_srv(item) for item in value]
        if isinstance(value, dict):
            return {
                SauravEmbed._from_srv(k): SauravEmbed._from_srv(v)
                for k, v in value.items()
            }
        return value

    @staticmethod
    def _wrap_python_fn(fn: Callable) -> Callable:
        """Wrap a Python callable as a sauravcode builtin.

        Builtins receive a single ``args`` list of already-evaluated
        values.  This wrapper unpacks the list into positional args,
        converts the return value to sauravcode representation, and
        translates Python exceptions to RuntimeError.
        """

        def wrapper(args: list) -> Any:
            try:
                py_args = [SauravEmbed._from_srv(a) for a in args]
                result = fn(*py_args)
                return SauravEmbed._to_srv(result)
            except TypeError as e:
                raise RuntimeError(f"Python function error: {e}") from None
            except Exception as e:
                raise RuntimeError(f"Python function error: {e}") from None

        return wrapper

    # ── Repr ─────────────────────────────────────────────────────

    def __repr__(self) -> str:
        n_vars = len(self._interp.variables)
        n_fns = len(self._interp.functions)
        n_py = len(self._registered)
        return (
            f"SauravEmbed(vars={n_vars}, fns={n_fns}, "
            f"python_fns={n_py}, runs={self._run_count})"
        )


# ── CLI Demo ─────────────────────────────────────────────────────

def main() -> None:
    """Interactive demo of the embedding API."""
    import argparse

    ap = argparse.ArgumentParser(
        description="sauravembed -- run sauravcode from Python",
    )
    ap.add_argument("file", nargs="?", help=".srv file to run")
    ap.add_argument("-e", "--eval", help="evaluate expression and print result")
    ap.add_argument("-c", "--code", help="execute code string")
    ap.add_argument(
        "--set",
        nargs=2,
        action="append",
        metavar=("NAME", "VALUE"),
        help="set a variable (can repeat)",
    )
    ap.add_argument("--no-capture", action="store_true", help="don't capture output")
    ap.add_argument("--json", action="store_true", help="output result as JSON")
    args = ap.parse_args()

    srv = SauravEmbed(capture_output=not args.no_capture)

    # Set variables from CLI
    if args.set:
        for name, val in args.set:
            # Try to parse as number or bool
            if val.lower() == "true":
                srv.set(name, True)
            elif val.lower() == "false":
                srv.set(name, False)
            else:
                try:
                    srv.set(name, int(val))
                except ValueError:
                    try:
                        srv.set(name, float(val))
                    except ValueError:
                        srv.set(name, val)

    if args.eval:
        try:
            value = srv.eval(args.eval)
            print(value)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.code:
        result = srv.run(args.code)
        _print_result(result, as_json=args.json)
        sys.exit(0 if result.success else 1)
    elif args.file:
        result = srv.run_file(args.file)
        _print_result(result, as_json=args.json)
        sys.exit(0 if result.success else 1)
    else:
        # Interactive demo
        _interactive_demo(srv)


def _print_result(result: RunResult, as_json: bool = False) -> None:
    """Print a RunResult."""
    if as_json:
        import json

        data = {
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "error_type": result.error_type,
            "elapsed_ms": result.elapsed_ms,
            "variables": result.variables,
        }
        if result.return_value is not None:
            data["return_value"] = result.return_value
        print(json.dumps(data, indent=2, default=str))
        return

    if result.output:
        print(result.output, end="")
    if not result.success:
        print(f"\nError ({result.error_type}): {result.error}", file=sys.stderr)
    if result.return_value is not None:
        print(f"Return: {result.return_value}")


def _interactive_demo(srv: SauravEmbed) -> None:
    """Run an interactive demo showing the embedding API."""
    print("+" + "=" * 46 + "+")
    print("|  sauravembed -- Python <-> Sauravcode Bridge |")
    print("+" + "=" * 46 + "+")
    print("|  Type sauravcode, or use these commands:     |")
    print("|    .set NAME VALUE   -- inject a variable    |")
    print("|    .get NAME         -- read a variable      |")
    print("|    .vars             -- list all variables    |")
    print("|    .fns              -- list all functions    |")
    print("|    .reset            -- reset state           |")
    print("|    .quit             -- exit                  |")
    print("+" + "=" * 46 + "+")
    print()

    # Register a demo Python function
    srv.register("pylen", lambda x: float(len(x)) if isinstance(x, (str, list)) else 0.0)
    print("  Registered Python function: pylen (returns length)")
    print()

    while True:
        try:
            line = input("embed> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue

        if line == ".quit":
            break
        elif line == ".vars":
            for name in sorted(srv.variables()):
                print(f"  {name} = {srv.get(name)!r}")
        elif line == ".fns":
            for name in sorted(srv.function_names):
                py = " (python)" if name in srv.registered_functions() else ""
                print(f"  {name}{py}")
        elif line == ".reset":
            srv.reset()
            srv.register("pylen", lambda x: float(len(x)) if isinstance(x, (str, list)) else 0.0)
            print("  State reset.")
        elif line.startswith(".set "):
            parts = line[5:].split(None, 1)
            if len(parts) == 2:
                name, val = parts
                try:
                    srv.set(name, int(val))
                except ValueError:
                    try:
                        srv.set(name, float(val))
                    except ValueError:
                        srv.set(name, val)
                print(f"  {name} = {srv.get(name)!r}")
            else:
                print("  Usage: .set NAME VALUE")
        elif line.startswith(".get "):
            name = line[5:].strip()
            if srv.has(name):
                print(f"  {name} = {srv.get(name)!r}")
            else:
                print(f"  Variable '{name}' not found.")
        else:
            result = srv.run(line)
            if result.output:
                print(result.output, end="")
            if not result.success:
                print(f"  Error: {result.error}")


if __name__ == "__main__":
    main()
