"""
CLI entry points for sauravcode.

These thin wrappers allow ``pip install sauravcode`` to create
console scripts (``sauravcode`` and ``sauravcode-compile``) that
delegate to the original interpreter and compiler modules.
"""

import os
import sys


def _project_root():
    """Return the directory containing the top-level saurav.py / sauravcc.py."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_module(filename: str, module_name: str) -> None:
    """Load and execute the ``main()`` function from a top-level module.

    Locates *filename* relative to the project root, ensures the root
    is on ``sys.path`` so sibling imports resolve, then calls
    ``module.main()``.

    Parameters
    ----------
    filename:
        Basename of the script (e.g. ``"saurav.py"``).
    module_name:
        Module name used by ``spec_from_file_location`` (e.g. ``"saurav"``).
    """
    root = _project_root()
    script = os.path.join(root, filename)

    if os.path.isfile(script) and root not in sys.path:
        sys.path.insert(0, root)

    import importlib.util

    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        print(f"Error: Cannot locate {filename}", file=sys.stderr)
        sys.exit(1)

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main()


def main_interpret():
    """Entry point for the ``sauravcode`` console script (interpreter + REPL)."""
    _run_module("saurav.py", "saurav")


def main_compile():
    """Entry point for the ``sauravcode-compile`` console script (compiler)."""
    _run_module("sauravcc.py", "sauravcc")


def main_snap():
    """Entry point for the ``sauravcode-snap`` console script (snapshot testing)."""
    _run_module("sauravsnap.py", "sauravsnap")


def main_api():
    """Entry point for the ``sauravcode-api`` console script (REST API server)."""
    _run_module("sauravapi.py", "sauravapi")
