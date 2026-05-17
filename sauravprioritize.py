"""
sauravprioritize — Agentic test/demo prioritizer for sauravcode projects.

Given a directory of ``.srv`` test/demo files and a recent git diff (or an
explicit list of changed files), this module produces a ranked execution
plan: which tests to run first, why, and how long the recommended slate is
expected to take.

It is intentionally dependency-free (stdlib only) so it can run in any
sauravcode checkout, CI job, or pre-push hook.

Agentic behavior
----------------
- **Awareness**: reads ``git log`` / ``git diff`` to detect what changed
  recently (or accepts an explicit list).
- **Inference**: scores every candidate ``.srv`` file against changed files
  using token/symbol overlap, path proximity, name affinity, and recency.
- **Recommendation**: ranks tests, emits priority tiers (P0/P1/P2/P3),
  reasoning per pick, and a time-budgeted slate that fits a user-supplied
  wall-clock cap.
- **Explainability**: every recommendation carries a short ``rationale``.

Public API
----------
- ``Prioritizer(root=".", changed=None, lookback=20)``
- ``Prioritizer.scan()`` -> ``list[TestCandidate]``
- ``Prioritizer.recommend(budget_seconds=None, top=None)`` -> ``PrioritizedPlan``
- ``PrioritizedPlan.format(fmt="text"|"md"|"json")``

CLI
---
::

    python -m sauravprioritize --root . --budget 30 --format md
    python -m sauravprioritize --changed sauravcc.py sauravlint.py --format json

This module is *standalone*: importing it does not pull in the rest of the
sauravcode runtime, so it is safe to use as a pre-commit advisor or in
constrained CI containers.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable, Optional

# ---------------------------------------------------------------------------
# Configuration constants (deliberately tunable, not magic)
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_DEFAULT_LOOKBACK = 20
_TEST_GLOBS = ("test_*.srv", "*_test.srv", "*_demo.srv", "demo_*.srv")
_PRIORITY_TIERS = ("P0", "P1", "P2", "P3")

# Heuristic time-cost (seconds) per .srv file when none measured.
_DEFAULT_PER_FILE_SECONDS = 2.0

# Tokens that show up in almost every .srv file and would inflate overlap.
_STOPWORDS = frozenset(
    {
        "let", "set", "fn", "function", "def", "return", "if", "else", "elif",
        "for", "while", "in", "of", "do", "end", "then", "print", "println",
        "true", "false", "null", "none", "and", "or", "not", "is", "as",
        "import", "from", "with", "use", "try", "catch", "raise", "throw",
        "class", "type", "new", "self", "this", "len", "list", "dict", "map",
        "set", "tuple", "str", "int", "float", "bool", "range", "var",
    }
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TestCandidate:
    """A single ``.srv`` file under consideration."""

    path: str
    size_bytes: int
    overlap_score: float = 0.0
    path_score: float = 0.0
    name_score: float = 0.0
    recency_score: float = 0.0
    total_score: float = 0.0
    estimated_seconds: float = _DEFAULT_PER_FILE_SECONDS
    rationale: list[str] = field(default_factory=list)

    @property
    def tier(self) -> str:
        s = self.total_score
        if s >= 0.75:
            return "P0"
        if s >= 0.45:
            return "P1"
        if s >= 0.20:
            return "P2"
        return "P3"


@dataclass
class PrioritizedPlan:
    root: str
    changed_files: list[str]
    candidates: list[TestCandidate]
    slate: list[TestCandidate]
    budget_seconds: Optional[float]
    total_seconds: float
    generated_at: float = field(default_factory=time.time)

    # ----- formatting -----------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "changed_files": list(self.changed_files),
            "budget_seconds": self.budget_seconds,
            "total_seconds": round(self.total_seconds, 2),
            "generated_at": self.generated_at,
            "candidates": [self._cand_dict(c) for c in self.candidates],
            "slate": [self._cand_dict(c) for c in self.slate],
        }

    @staticmethod
    def _cand_dict(c: TestCandidate) -> dict:
        d = asdict(c)
        d["tier"] = c.tier
        # round noisy floats
        for k in ("overlap_score", "path_score", "name_score",
                  "recency_score", "total_score", "estimated_seconds"):
            d[k] = round(d[k], 3)
        return d

    def format(self, fmt: str = "text") -> str:
        fmt = fmt.lower()
        if fmt == "json":
            return json.dumps(self.to_dict(), indent=2, sort_keys=True)
        if fmt == "md":
            return self._format_md()
        if fmt == "text":
            return self._format_text()
        raise ValueError(f"unknown format: {fmt!r}")

    def _format_text(self) -> str:
        out: list[str] = []
        out.append(f"sauravprioritize :: {self.root}")
        out.append(
            f"  changed files : {len(self.changed_files)}"
            f"  | candidates  : {len(self.candidates)}"
            f"  | slate       : {len(self.slate)}"
            f"  | budget      : "
            f"{('%.1fs' % self.budget_seconds) if self.budget_seconds else 'unbounded'}"
            f"  | est total   : {self.total_seconds:.1f}s"
        )
        out.append("")
        out.append("Recommended slate (run in order):")
        if not self.slate:
            out.append("  (none — nothing scored above zero)")
        for i, c in enumerate(self.slate, 1):
            out.append(
                f"  {i:>2}. [{c.tier}] {c.path}  "
                f"(score={c.total_score:.2f}, ~{c.estimated_seconds:.1f}s)"
            )
            if c.rationale:
                out.append(f"        why: {'; '.join(c.rationale)}")
        out.append("")
        skipped = [c for c in self.candidates if c not in self.slate]
        if skipped:
            out.append(f"Deferred ({len(skipped)}):")
            for c in skipped[:10]:
                out.append(
                    f"  - [{c.tier}] {c.path}  (score={c.total_score:.2f})"
                )
            if len(skipped) > 10:
                out.append(f"  … and {len(skipped) - 10} more")
        return "\n".join(out)

    def _format_md(self) -> str:
        out: list[str] = []
        out.append(f"# sauravprioritize — {self.root}")
        out.append("")
        out.append(
            f"- changed files: **{len(self.changed_files)}**"
        )
        out.append(f"- candidates considered: **{len(self.candidates)}**")
        out.append(f"- slate length: **{len(self.slate)}**")
        budget = (
            f"{self.budget_seconds:.1f}s"
            if self.budget_seconds
            else "unbounded"
        )
        out.append(f"- budget: **{budget}**  |  est total: **{self.total_seconds:.1f}s**")
        out.append("")
        out.append("## Recommended slate")
        out.append("")
        if not self.slate:
            out.append("_no candidates scored above zero — nothing to run_")
        else:
            out.append("| # | tier | file | score | est | rationale |")
            out.append("|---|------|------|------:|----:|-----------|")
            for i, c in enumerate(self.slate, 1):
                why = "; ".join(c.rationale) or "—"
                out.append(
                    f"| {i} | {c.tier} | `{c.path}` | "
                    f"{c.total_score:.2f} | {c.estimated_seconds:.1f}s | {why} |"
                )
        deferred = [c for c in self.candidates if c not in self.slate]
        if deferred:
            out.append("")
            out.append("## Deferred")
            out.append("")
            for c in deferred[:25]:
                out.append(f"- `{c.path}` — {c.tier} ({c.total_score:.2f})")
            if len(deferred) > 25:
                out.append(f"- … and {len(deferred) - 25} more")
        return "\n".join(out)


# ---------------------------------------------------------------------------
# Prioritizer
# ---------------------------------------------------------------------------


class Prioritizer:
    """Agentic test/demo prioritizer.

    The prioritizer is deterministic: given the same inputs it produces the
    same ranking. It blends four signals:

    1. **overlap_score** — Jaccard-ish overlap between identifiers in the
       test file and identifiers in changed files.
    2. **path_score**    — proximity of the test path to changed paths
       (shared parent directory, shared stem).
    3. **name_score**    — affinity between the test name and changed
       module names (``test_sauravcc.py`` ↔ ``sauravcc.py``).
    4. **recency_score** — boost for tests that have themselves been
       modified recently (more likely to be unstable).
    """

    def __init__(
        self,
        root: str | os.PathLike = ".",
        changed: Optional[Iterable[str]] = None,
        lookback: int = _DEFAULT_LOOKBACK,
        include_py_tests: bool = False,
        weights: Optional[dict] = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.lookback = max(1, int(lookback))
        self.include_py_tests = bool(include_py_tests)
        self._changed_override = (
            [str(c) for c in changed] if changed is not None else None
        )
        self.weights = {
            "overlap": 0.45,
            "path": 0.20,
            "name": 0.25,
            "recency": 0.10,
        }
        if weights:
            self.weights.update(weights)

    # ----- inputs ---------------------------------------------------------

    def changed_files(self) -> list[str]:
        if self._changed_override is not None:
            return list(self._changed_override)
        return self._git_recent_changes()

    def _git_recent_changes(self) -> list[str]:
        try:
            res = subprocess.run(
                [
                    "git", "-C", str(self.root),
                    "log", f"-{self.lookback}", "--name-only",
                    "--pretty=format:",
                ],
                capture_output=True, text=True, timeout=15, check=False,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            return []
        if res.returncode != 0:
            return []
        seen: dict[str, None] = {}
        for line in res.stdout.splitlines():
            line = line.strip()
            if line and line not in seen:
                seen[line] = None
        return list(seen)

    # ----- scanning -------------------------------------------------------

    def _discover_candidates(self) -> list[Path]:
        found: set[Path] = set()
        for pattern in _TEST_GLOBS:
            for p in self.root.rglob(pattern):
                if self._skip(p):
                    continue
                found.add(p)
        if self.include_py_tests:
            for p in self.root.rglob("test_*.py"):
                if self._skip(p):
                    continue
                found.add(p)
        return sorted(found)

    @staticmethod
    def _skip(p: Path) -> bool:
        parts = set(p.parts)
        return bool(parts & {".git", "node_modules", "__pycache__",
                             "build", "dist", ".venv", "venv"})

    # ----- scoring --------------------------------------------------------

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {t for t in _TOKEN_RE.findall(text) if t not in _STOPWORDS}

    def _read_tokens(self, p: Path) -> set[str]:
        try:
            return self._tokens(p.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            return set()

    def _changed_token_pool(self, changed: list[str]) -> set[str]:
        pool: set[str] = set()
        for rel in changed:
            cand = self.root / rel
            if cand.exists() and cand.is_file():
                pool |= self._read_tokens(cand)
            else:
                # changed file may have been deleted — still use the stem as
                # a weak signal.
                pool.add(Path(rel).stem)
        return pool

    def _recency_map(self) -> dict[str, int]:
        """Map relative path -> index in recent change history (0=newest)."""
        if self._changed_override is not None:
            return {}
        recent = self._git_recent_changes()
        return {rel: i for i, rel in enumerate(recent)}

    def _score(
        self,
        cand: Path,
        changed: list[str],
        changed_tokens: set[str],
        recency: dict[str, int],
    ) -> TestCandidate:
        cand_tokens = self._read_tokens(cand)
        rel = str(cand.relative_to(self.root)).replace("\\", "/")
        rationale: list[str] = []

        # --- overlap ----------------------------------------------------
        overlap = 0.0
        if cand_tokens and changed_tokens:
            inter = cand_tokens & changed_tokens
            union = cand_tokens | changed_tokens
            overlap = len(inter) / max(1, len(union))
            if inter:
                top = sorted(inter)[:3]
                rationale.append(
                    f"shares {len(inter)} identifiers with changes "
                    f"(e.g. {', '.join(top)})"
                )

        # --- path proximity ---------------------------------------------
        path_score = 0.0
        cand_parts = Path(rel).parts
        for ch in changed:
            ch_parts = Path(ch).parts
            common = 0
            for a, b in zip(cand_parts, ch_parts):
                if a == b:
                    common += 1
                else:
                    break
            denom = max(len(cand_parts), len(ch_parts), 1)
            path_score = max(path_score, common / denom)
        if path_score >= 0.5:
            rationale.append("shares parent directory with a change")

        # --- name affinity ----------------------------------------------
        name_score = 0.0
        cand_stem = Path(rel).stem.lower()
        cand_stem_norm = re.sub(r"^(test_|demo_)", "", cand_stem)
        cand_stem_norm = re.sub(r"(_test|_demo)$", "", cand_stem_norm)
        for ch in changed:
            ch_stem = Path(ch).stem.lower()
            if not ch_stem:
                continue
            if cand_stem_norm == ch_stem:
                name_score = 1.0
                rationale.append(f"name matches changed module `{ch_stem}`")
                break
            if cand_stem_norm and ch_stem.endswith(cand_stem_norm):
                name_score = max(name_score, 0.8)
                rationale.append(f"name aligns with `{ch_stem}`")
            elif cand_stem_norm and cand_stem_norm in ch_stem:
                name_score = max(name_score, 0.5)
            elif ch_stem in cand_stem_norm and len(ch_stem) >= 5:
                name_score = max(name_score, 0.5)

        # --- recency ----------------------------------------------------
        recency_score = 0.0
        if rel in recency:
            idx = recency[rel]
            # newest commits dominate
            recency_score = max(0.0, 1.0 - (idx / max(1, self.lookback)))
            if recency_score > 0:
                rationale.append("recently modified itself")

        w = self.weights
        total = (
            w["overlap"] * overlap
            + w["path"] * path_score
            + w["name"] * name_score
            + w["recency"] * recency_score
        )

        size = cand.stat().st_size if cand.exists() else 0
        # Rough estimate: 1s baseline + 1s per 4 KB of source.
        est = 1.0 + (size / 4096.0)

        return TestCandidate(
            path=rel,
            size_bytes=size,
            overlap_score=overlap,
            path_score=path_score,
            name_score=name_score,
            recency_score=recency_score,
            total_score=total,
            estimated_seconds=est,
            rationale=rationale,
        )

    # ----- public API -----------------------------------------------------

    def scan(self) -> list[TestCandidate]:
        changed = self.changed_files()
        changed_tokens = self._changed_token_pool(changed)
        recency = self._recency_map()
        cands = [
            self._score(p, changed, changed_tokens, recency)
            for p in self._discover_candidates()
        ]
        cands.sort(key=lambda c: (-c.total_score, c.path))
        return cands

    def recommend(
        self,
        budget_seconds: Optional[float] = None,
        top: Optional[int] = None,
        min_score: float = 0.05,
    ) -> PrioritizedPlan:
        cands = self.scan()
        changed = self.changed_files()
        slate: list[TestCandidate] = []
        running = 0.0
        for c in cands:
            if c.total_score < min_score:
                break
            if top is not None and len(slate) >= top:
                break
            if (
                budget_seconds is not None
                and running + c.estimated_seconds > budget_seconds
                and slate  # always keep at least one
            ):
                break
            slate.append(c)
            running += c.estimated_seconds
        return PrioritizedPlan(
            root=str(self.root),
            changed_files=changed,
            candidates=cands,
            slate=slate,
            budget_seconds=budget_seconds,
            total_seconds=running,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sauravprioritize",
        description=(
            "Agentic test/demo prioritizer for sauravcode projects. "
            "Ranks .srv (and optionally .py) tests by likely impact of "
            "recent changes and emits a time-budgeted execution slate."
        ),
    )
    p.add_argument("--root", default=".", help="project root (default: cwd)")
    p.add_argument(
        "--changed", nargs="*", default=None,
        help="explicit list of changed files (relative to root). "
             "If omitted, recent git history is used.",
    )
    p.add_argument(
        "--lookback", type=int, default=_DEFAULT_LOOKBACK,
        help="how many recent commits to scan for change signal "
             f"(default: {_DEFAULT_LOOKBACK})",
    )
    p.add_argument(
        "--budget", type=float, default=None,
        help="time budget in seconds for the recommended slate",
    )
    p.add_argument(
        "--top", type=int, default=None,
        help="cap slate length to N entries",
    )
    p.add_argument(
        "--min-score", type=float, default=0.05,
        help="minimum total score required to enter the slate (default: 0.05)",
    )
    p.add_argument(
        "--include-py-tests", action="store_true",
        help="also consider tests/test_*.py files (off by default)",
    )
    p.add_argument(
        "--format", choices=("text", "md", "json"), default="text",
        help="output format (default: text)",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    pr = Prioritizer(
        root=args.root,
        changed=args.changed,
        lookback=args.lookback,
        include_py_tests=args.include_py_tests,
    )
    plan = pr.recommend(
        budget_seconds=args.budget,
        top=args.top,
        min_score=args.min_score,
    )
    print(plan.format(args.format))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
