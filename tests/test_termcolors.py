"""Tests for the shared ``_termcolors`` ANSI helpers.

Focus areas:

* ``ansi`` low-level helper enables/disables based on its flag.
* ``Colors`` named-colour helpers produce the expected escapes when enabled
  and pass text through unchanged when disabled.
* The ``colors()`` factory's auto-detection honours ``NO_COLOR``,
  ``FORCE_COLOR``, ``TERM=dumb`` and ``sys.stdout.isatty()`` with the
  documented precedence.

These tests guard the behaviour relied on by sauravkata, sauravlearn,
sauravpipe, sauravrepl, sauravtest, and other CLIs that share the module.
"""

from __future__ import annotations

import importlib
import io
import os
import sys
from pathlib import Path
from typing import Iterator

import pytest

# Ensure repo root (where _termcolors.py lives) is on sys.path when tests are
# collected from inside ``tests/``.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import _termcolors  # noqa: E402  (sys.path tweak above)
from _termcolors import Colors, ansi, colors  # noqa: E402


# ---------------------------------------------------------------------------
# ansi() low-level helper
# ---------------------------------------------------------------------------

def test_ansi_enabled_wraps_with_escape_and_reset():
    assert ansi("31", "boom", enabled=True) == "\x1b[31mboom\x1b[0m"


def test_ansi_disabled_returns_plain_str():
    assert ansi("31", "boom", enabled=False) == "boom"


def test_ansi_disabled_coerces_non_string():
    # Must call str() so callers can pass ints / objects safely.
    assert ansi("31", 42, enabled=False) == "42"


def test_ansi_enabled_coerces_non_string():
    assert ansi("1", 7, enabled=True) == "\x1b[1m7\x1b[0m"


# ---------------------------------------------------------------------------
# Colors helpers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "method,code",
    [
        ("green",   "32"),
        ("red",     "31"),
        ("yellow",  "33"),
        ("cyan",    "36"),
        ("magenta", "35"),
        ("bold",    "1"),
        ("dim",     "2"),
    ],
)
def test_colors_named_helpers_when_enabled(method, code):
    c = Colors(enabled=True)
    assert getattr(c, method)("x") == f"\x1b[{code}mx\x1b[0m"


@pytest.mark.parametrize(
    "method",
    ["green", "red", "yellow", "cyan", "magenta", "bold", "dim"],
)
def test_colors_named_helpers_when_disabled_are_plain(method):
    c = Colors(enabled=False)
    assert getattr(c, method)("x") == "x"


def test_colors_nested_calls_compose():
    c = Colors(enabled=True)
    # Outer bold wraps the already-wrapped red text.
    assert c.bold(c.red("x")) == "\x1b[1m\x1b[31mx\x1b[0m\x1b[0m"


def test_colors_uses_slots():
    # __slots__ keeps the per-instance footprint tiny; regressing this would
    # silently bloat memory in CLIs that build many Colors instances.
    c = Colors(enabled=True)
    with pytest.raises(AttributeError):
        c.unexpected = "nope"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# colors() factory + env-var detection
# ---------------------------------------------------------------------------

@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Remove every colour-affecting env var before each test."""
    for name in ("NO_COLOR", "FORCE_COLOR", "TERM", "CLICOLOR", "CLICOLOR_FORCE"):
        monkeypatch.delenv(name, raising=False)
    yield


def _patch_stdout_tty(monkeypatch: pytest.MonkeyPatch, is_tty: bool) -> None:
    """Swap ``sys.stdout`` for a stream whose ``isatty()`` returns *is_tty*."""

    class _Stream(io.StringIO):
        def isatty(self) -> bool:  # noqa: D401 - simple override
            return is_tty

    monkeypatch.setattr(sys, "stdout", _Stream())


def test_factory_explicit_true_overrides_detection(monkeypatch, clean_env):
    monkeypatch.setenv("NO_COLOR", "1")
    _patch_stdout_tty(monkeypatch, is_tty=False)
    # Explicit True wins; detection (which would say False) is bypassed.
    assert colors(enabled=True).enabled is True


def test_factory_explicit_false_overrides_detection(monkeypatch, clean_env):
    monkeypatch.setenv("FORCE_COLOR", "1")
    _patch_stdout_tty(monkeypatch, is_tty=True)
    assert colors(enabled=False).enabled is False


def test_factory_auto_enabled_on_tty(monkeypatch, clean_env):
    _patch_stdout_tty(monkeypatch, is_tty=True)
    assert colors().enabled is True


def test_factory_auto_disabled_when_not_tty(monkeypatch, clean_env):
    _patch_stdout_tty(monkeypatch, is_tty=False)
    assert colors().enabled is False


def test_no_color_disables_even_on_tty(monkeypatch, clean_env):
    monkeypatch.setenv("NO_COLOR", "1")
    _patch_stdout_tty(monkeypatch, is_tty=True)
    assert colors().enabled is False


def test_no_color_empty_string_is_ignored(monkeypatch, clean_env):
    # Per https://no-color.org spec: "when present and not an empty string".
    monkeypatch.setenv("NO_COLOR", "")
    _patch_stdout_tty(monkeypatch, is_tty=True)
    assert colors().enabled is True


def test_force_color_enables_without_tty(monkeypatch, clean_env):
    monkeypatch.setenv("FORCE_COLOR", "1")
    _patch_stdout_tty(monkeypatch, is_tty=False)
    assert colors().enabled is True


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "always", "TRUE", "Yes"])
def test_force_color_truthy_values(monkeypatch, clean_env, value):
    monkeypatch.setenv("FORCE_COLOR", value)
    _patch_stdout_tty(monkeypatch, is_tty=False)
    assert colors().enabled is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "garbage"])
def test_force_color_non_truthy_does_not_enable_without_tty(monkeypatch, clean_env, value):
    monkeypatch.setenv("FORCE_COLOR", value)
    _patch_stdout_tty(monkeypatch, is_tty=False)
    assert colors().enabled is False


def test_no_color_beats_force_color(monkeypatch, clean_env):
    # no-color.org is explicit that NO_COLOR is the prevailing signal.
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("FORCE_COLOR", "1")
    _patch_stdout_tty(monkeypatch, is_tty=True)
    assert colors().enabled is False


def test_term_dumb_disables(monkeypatch, clean_env):
    monkeypatch.setenv("TERM", "dumb")
    _patch_stdout_tty(monkeypatch, is_tty=True)
    assert colors().enabled is False


def test_term_dumb_is_overridden_by_force_color(monkeypatch, clean_env):
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv("FORCE_COLOR", "1")
    _patch_stdout_tty(monkeypatch, is_tty=False)
    assert colors().enabled is True


def test_term_xterm_does_not_force_enable_without_tty(monkeypatch, clean_env):
    # Regression: the old implementation used ``bool(os.environ.get("TERM", True))``
    # which made *any* TERM value count as "colour-capable" regardless of the
    # actual stream. Detection must defer to isatty() when TERM is set normally.
    monkeypatch.setenv("TERM", "xterm-256color")
    _patch_stdout_tty(monkeypatch, is_tty=False)
    assert colors().enabled is False


def test_detection_survives_stdout_without_isatty(monkeypatch, clean_env):
    # Some test harnesses replace stdout with a plain object that lacks
    # ``isatty``. Detection must not crash.
    monkeypatch.setattr(sys, "stdout", object())
    assert colors().enabled is False


def test_detection_survives_closed_stdout(monkeypatch, clean_env):
    stream = io.StringIO()
    stream.close()
    monkeypatch.setattr(sys, "stdout", stream)
    # Closed StringIO raises ValueError on isatty(); detection must swallow it.
    assert colors().enabled is False


def test_module_reimport_is_clean():
    # Importing the module a second time should be a no-op (no leftover global
    # state). This protects against future refactors that introduce caches.
    mod = importlib.reload(_termcolors)
    assert hasattr(mod, "colors")
    assert hasattr(mod, "Colors")
    assert hasattr(mod, "ansi")
