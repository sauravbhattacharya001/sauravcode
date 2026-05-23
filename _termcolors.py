"""_termcolors -- Shared ANSI terminal color helpers for sauravcode tools.

Centralises the color/style escape sequences that were duplicated across
sauravkata, sauravlearn, sauravpipe, sauravrepl, sauravtest, and others.

Usage::

    from _termcolors import colors

    # Get a Colors instance (auto-detects tty by default)
    c = colors()              # auto-detect, honours NO_COLOR / FORCE_COLOR
    c = colors(enabled=True)  # force on
    c = colors(enabled=False) # force off

    print(c.green("PASS"))
    print(c.bold(c.red("FAIL")))

The module also exposes a low-level ``ansi(code, text, enabled)`` helper for
callers that only need a single wrap without constructing an instance.

Environment detection (when ``enabled`` is ``None``):

* ``NO_COLOR``     -- if set to any non-empty value, colour is disabled
                      (https://no-color.org).
* ``FORCE_COLOR``  -- if set to a truthy value (``1``/``true``/``yes``/``on``),
                      colour is enabled even when stdout is not a TTY. This
                      mirrors the convention used by Node.js, npm, pytest,
                      ripgrep, and most modern CLI tooling.
* ``TERM=dumb``    -- explicit "no capabilities" terminal, colour disabled.
* Fallback         -- enabled iff ``sys.stdout.isatty()``.

``NO_COLOR`` takes precedence over ``FORCE_COLOR`` to match the documented
behaviour at no-color.org ("when present and not an empty string ... prevent
the addition of ANSI color").
"""

from __future__ import annotations

import os
import sys

__all__ = ["Colors", "colors", "ansi"]


def ansi(code: str, text, enabled: bool = True) -> str:
    """Wrap *text* in an ANSI escape sequence if *enabled*.

    When *enabled* is falsy the original text is returned unchanged
    (coerced with ``str()``), so callers can unconditionally wrap output
    without branching on the colour-enabled flag.
    """
    if not enabled:
        return str(text)
    return f"\033[{code}m{text}\033[0m"


# Values that count as "truthy" for FORCE_COLOR. Matches the de-facto
# convention used by Node's supports-color, click, and pytest.
_TRUTHY = frozenset({"1", "true", "yes", "on", "always"})


def _env_truthy(name: str) -> bool:
    """Return True if the named env var is set to a recognised truthy value."""
    val = os.environ.get(name)
    if val is None:
        return False
    return val.strip().lower() in _TRUTHY


def _detect_enabled() -> bool:
    """Determine whether colour output should be enabled in the current env.

    Precedence (highest first):
      1. ``NO_COLOR``  (any non-empty value disables, per no-color.org)
      2. ``FORCE_COLOR`` truthy (enables even without a TTY)
      3. ``TERM=dumb`` (disables)
      4. ``sys.stdout.isatty()``
    """
    # 1. NO_COLOR — presence and non-empty disables, regardless of TTY.
    no_color = os.environ.get("NO_COLOR")
    if no_color is not None and no_color != "":
        return False

    # 2. FORCE_COLOR — explicit opt-in, bypasses TTY check.
    if _env_truthy("FORCE_COLOR"):
        return True

    # 3. TERM=dumb — terminal advertises no capabilities.
    if os.environ.get("TERM", "").strip().lower() == "dumb":
        return False

    # 4. Default: only colour when writing to a real terminal. ``isatty`` may
    #    be missing (e.g. patched stdout in tests) — treat absence as no-tty.
    isatty = getattr(sys.stdout, "isatty", None)
    try:
        return bool(isatty()) if callable(isatty) else False
    except (ValueError, OSError):
        # Closed stdout or unusual stream object.
        return False


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
    """Factory: build a ``Colors`` instance.

    If *enabled* is ``None`` (the default), detection follows the precedence
    documented at the module level: ``NO_COLOR`` > ``FORCE_COLOR`` >
    ``TERM=dumb`` > ``sys.stdout.isatty()``. Pass an explicit ``True`` or
    ``False`` to bypass detection entirely.
    """
    if enabled is None:
        enabled = _detect_enabled()
    return Colors(enabled)
