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


def _run_module(filename, label):
    """Load and execute a top-level script by filename.

    Locates *filename* relative to the project root, ensures the root
    is on ``sys.path`` so sibling imports resolve, then calls the
    module's ``main()`` function.

    Parameters
    ----------
    filename : str
        Script filename (e.g. ``"saurav.py"``).
    label : str
        Human-readable label for error messages (e.g. ``"interpreter"``).
    """
    import importlib.util

    root = _project_root()
    script = os.path.join(root, filename)

    if os.path.isfile(script) and root not in sys.path:
        sys.path.insert(0, root)

    module_name = os.path.splitext(filename)[0]
    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        print("Error: Cannot locate %s %s" % (filename, label), file=sys.stderr)
        sys.exit(1)

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main()


def main_interpret():
    """Entry point for the ``sauravcode`` console script (interpreter + REPL)."""
    _run_module("saurav.py", "interpreter")


def main_compile():
    """Entry point for the ``sauravcode-compile`` console script (compiler)."""
    _run_module("sauravcc.py", "compiler")


def main_snap():
    """Entry point for the ``sauravcode-snap`` console script (snapshot testing)."""
    _run_module("sauravsnap.py", "snapshot tester")


def main_api():
    """Entry point for the ``sauravcode-api`` console script (REST API server)."""
    _run_module("sauravapi.py", "API server")


def main_cheat():
    """Entry point for the ``sauravcode-cheat`` console script (cheat sheet)."""
    _run_module("sauravcheat.py", "cheat sheet")


def main_canvas():
    """Entry point for the ``sauravcode-canvas`` console script (turtle graphics)."""
    _run_module("sauravcanvas.py", "canvas")


def main_pipe():
    """Entry point for the ``sauravcode-pipe`` console script (pipeline runner)."""
    _run_module("sauravpipe.py", "pipeline runner")
