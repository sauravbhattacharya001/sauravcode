"""_termcolors -- Shared ANSI terminal color helpers for sauravcode tools.

Centralises the color/style escape sequences that were duplicated across
sauravkata, sauravlearn, sauravpipe, sauravrepl, sauravtest, and others.

Usage::

    from _termcolors import colors

    # Get a Colors instance (auto-detects tty by default)
    c = colors()              # auto-detect
    c = colors(enabled=True)  # force on
    c = colors(enabled=False) # force off

    print(c.green("PASS"))
    print(c.bold(c.red("FAIL")))

The module also exposes a low-level ``ansi(code, text, enabled)`` helper for
callers that only need a single wrap without constructing an instance.
"""

from __future__ import annotations

import os
import sys

__all__ = ["Colors", "colors", "ansi"]


def ansi(code: str, text, enabled: bool = True) -> str:
    """Wrap *text* in an ANSI escape sequence if *enabled*."""
    if not enabled:
        return str(text)
    return f"\033[{code}m{text}\033[0m"


class Colors:
    """Convenience wrapper for the standard six ANSI helpers.

    Each method (``green``, ``red``, ``yellow``, ``cyan``, ``bold``, ``dim``,
    ``magenta``) returns *text* wrapped in the appropriate escape when
    ``self.enabled`` is truthy, or plain ``str(text)`` otherwise.
    """

    __slots__ = ("enabled",)

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    # Core helper ---------------------------------------------------------
    def c(self, code: str, text) -> str:          # noqa: D102
        return ansi(code, text, self.enabled)

    # Named colours -------------------------------------------------------
    def green(self, t) -> str:   return self.c("32", t)
    def red(self, t) -> str:     return self.c("31", t)
    def yellow(self, t) -> str:  return self.c("33", t)
    def cyan(self, t) -> str:    return self.c("36", t)
    def magenta(self, t) -> str: return self.c("35", t)
    def bold(self, t) -> str:    return self.c("1", t)
    def dim(self, t) -> str:     return self.c("2", t)


def colors(enabled: bool | None = None) -> Colors:
    """Factory: auto-detect TTY when *enabled* is ``None``."""
    if enabled is None:
        enabled = sys.stdout.isatty() and bool(os.environ.get("TERM", True))
    return Colors(enabled)
