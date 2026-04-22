"""Shared utilities for sauravcode analysis tools.

Provides common helpers used by sauravmetrics, sauravstats, sauravlint,
and sauravhl — avoiding duplicated implementations across modules.
"""

import os


def get_indent(line: str) -> int:
    """Return the indentation level of *line* in spaces (tabs count as 4).

    Identical to the previously-duplicated ``_get_indent`` / ``_indent_level``
    helpers in sauravmetrics.py, sauravstats.py, and sauravlint.py.
    """
    count = 0
    for ch in line:
        if ch == ' ':
            count += 1
        elif ch == '\t':
            count += 4
        else:
            break
    return count


def find_srv_files(paths, *, recursive=False):
    """Find .srv files from one or more paths.

    Consolidates the ``find_srv_files`` implementations that were
    duplicated across sauravmetrics.py, sauravstats.py, and sauravhl.py.

    Args:
        paths: A single path string or an iterable of path strings.
            Each may be a file or a directory.
        recursive: When *True*, descend into subdirectories.

    Returns:
        A list of .srv file paths (strings), sorted within each directory.
    """
    if isinstance(paths, str):
        paths = [paths]

    files: list[str] = []
    for p in paths:
        if os.path.isfile(p):
            if p.endswith('.srv'):
                files.append(p)
        elif os.path.isdir(p):
            if recursive:
                for root, dirs, fnames in os.walk(p):
                    dirs[:] = [d for d in dirs if not d.startswith('.')
                               and d != '__pycache__'
                               and d != '__snapshots__'
                               and d != 'node_modules']
                    for fn in sorted(fnames):
                        if fn.endswith('.srv'):
                            files.append(os.path.join(root, fn))
            else:
                for fn in sorted(os.listdir(p)):
                    if fn.endswith('.srv'):
                        files.append(os.path.join(p, fn))
    return files
