"""
sauravsmoke - Agentic smoke-test slate builder for sauravcode projects.

Given a directory of ``.srv`` demos / tests, this module assembles a *minimal*
slate of files that, together, exercise the broadest possible slice of the
sauravcode language and stdlib surface. The classic use case is "I have 60
seconds in CI, pick the smallest set of demos that touches the most features".

Agentic behavior
----------------
- **Awareness**: scans every ``.srv`` file and extracts the set of language /
  stdlib features it touches (control flow, f-strings, lambdas, pipes,
  higher-order functions, maps, sets, classes, try/catch, regex, json, http,
  forecasting, automata, ...).
- **Inference**: assigns each feature an importance weight and each candidate
  file a runtime cost estimate (from line count + structural complexity).
- **Recommendation**: solves a greedy weighted max-coverage problem to build a
  ranked slate that fits a wall-clock budget, plus a "long tail" of features
  no demo covers (gap report).
- **Explainability**: every pick carries a short ``rationale`` listing the
  *new* features it brings to the slate, plus a P0/P1/P2/P3 priority tier:

  * **P0** - existing pytest-style ``test_*.srv`` (must run)
  * **P1** - first demo that unlocks 3+ uncovered high-weight features
  * **P2** - smaller incremental coverage gains
  * **P3** - duplicate-coverage demos (run only if budget remains)

Public API
----------
- ``Smoker(root=".")``
- ``Smoker.scan()`` -> ``list[SmokeCandidate]``
- ``Smoker.recommend(budget_seconds=None, top=None)`` -> ``SmokeSlate``
- ``SmokeSlate.format(fmt="text"|"md"|"json")``

CLI
---
::

    python -m sauravsmoke --root . --budget 30 --format md
    python -m sauravsmoke --root demos --format json --top 8

Standalone (stdlib only) so it can run in pre-commit, CI, or a constrained
container without importing the rest of the sauravcode runtime.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable

__all__ = [
    "FEATURE_CATALOGUE",
    "SmokeCandidate",
    "SmokePick",
    "SmokeSlate",
    "Smoker",
    "detect_features",
    "estimate_cost_seconds",
]

# ---------------------------------------------------------------------------
# Feature catalogue
# ---------------------------------------------------------------------------
# Each entry maps a feature id -> (weight, regex). A higher weight means we
# care more about including at least one demo that touches this feature in
# the smoke slate. Weights are deliberately small integers (1..5) so the
# greedy coverage scoring stays interpretable.

FEATURE_CATALOGUE: dict[str, tuple[int, str]] = {
    # Core control flow (high weight - everything depends on these)
    "if_else":          (5, r"^\s*if\s+|^\s*else\s*$|^\s*else\s+if\b"),
    "while_loop":       (4, r"^\s*while\s+"),
    "for_range":        (4, r"^\s*for\s+\w+\s*=\s*\d+\s+to\s+"),
    "for_each":         (4, r"^\s*for\s+\w+\s+in\s+"),
    "break_continue":   (3, r"\bbreak\b|\bcontinue\b"),
    # Functions / abstractions
    "function_def":     (5, r"^\s*function\s+\w+"),
    "lambda":           (4, r"\blambda\b"),
    "pipe":             (4, r"\|>"),
    "higher_order":     (3, r"\bmap\b|\bfilter\b|\breduce\b"),
    "recursion_hint":   (2, r"return\s+\w+\s*\("),
    # Strings & formatting
    "fstring":          (3, r'f"[^"]*\{'),
    "string_methods":   (2, r"\.(upper|lower|reverse|split|replace|trim)\b"),
    # Data structures
    "list":             (3, r"\[\s*[^]]*?\s*\]"),
    "map_literal":      (3, r"\{\s*\".+\"\s*:"),
    "set_literal":      (2, r"\bset\s*\{"),
    "matrix":           (1, r"\[\s*\[\s*\d"),
    # IO & errors
    "print":            (2, r"^\s*print\b"),
    "try_catch":        (3, r"\btry\b|\bcatch\b"),
    "assert":           (3, r"^\s*assert\b"),
    "input_read":       (1, r"\binput\b"),
    # Stdlib touches (light heuristics on demo filenames + content)
    "json":             (2, r"\bjson_(loads|dumps|parse|stringify)\b|\bto_json\b"),
    "regex":            (2, r"\bregex_(match|search|findall|sub)\b|\bre_match\b"),
    "datetime":         (2, r"\bnow\b|\btimestamp\b|\bdate_\w+\b"),
    "csv":              (2, r"\bcsv_(read|write|parse)\b"),
    "http":             (2, r"\bhttp_(get|post)\b"),
    "logging":          (1, r"\blog_(info|warn|error|debug)\b"),
    "hash":             (1, r"\bhash_(md5|sha1|sha256)\b"),
    "cipher":           (1, r"\b(encrypt|decrypt|caesar|xor_cipher)\b"),
    "compression":      (1, r"\b(compress|decompress|gzip_|zlib_)\b"),
    "graph":            (2, r"\bgraph_(add|neighbors|bfs|dfs)\b"),
    "heap":             (1, r"\bheap_(push|pop|peek)\b"),
    "deque":            (1, r"\bdeque_(push|pop|front|back)\b"),
    "linkedlist":       (1, r"\blinked_?list\b"),
    "trie":             (1, r"\btrie_(insert|search|prefix)\b"),
    "ring_buffer":      (1, r"\bring_(push|pop|buffer)\b"),
    "stats":            (1, r"\b(mean|median|stddev|variance)\b"),
    "plot":             (1, r"\bplot_(line|bar|hist|scatter)\b"),
    "automata":         (1, r"\bautomaton\b|\bfsm\b|\bstate_machine\b"),
    "forecast":         (1, r"\bforecast\b|\bpredict\b"),
    "validation":       (2, r"\b(validate_|require_|ensure_)\w+"),
    "bloom":            (1, r"\bbloom_(add|contains|filter)\b"),
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SmokeCandidate:
    """A single ``.srv`` file considered for the smoke slate."""

    path: str
    is_test: bool
    line_count: int
    feature_ids: list[str]
    cost_seconds: float
    feature_weight: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class SmokePick:
    """A candidate that made it into the slate, with its rationale."""

    path: str
    tier: str                # "P0" | "P1" | "P2" | "P3"
    new_features: list[str]
    cumulative_features: int
    cost_seconds: float
    rationale: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class SmokeSlate:
    """The final recommendation."""

    root: str
    total_candidates: int
    total_features_available: int
    picks: list[SmokePick] = field(default_factory=list)
    covered_features: list[str] = field(default_factory=list)
    uncovered_features: list[str] = field(default_factory=list)
    estimated_seconds: float = 0.0
    budget_seconds: float | None = None
    coverage_score: float = 0.0     # 0..1 weighted

    # ---- formatters --------------------------------------------------

    def as_dict(self) -> dict:
        return {
            "root": self.root,
            "total_candidates": self.total_candidates,
            "total_features_available": self.total_features_available,
            "picks": [p.as_dict() for p in self.picks],
            "covered_features": list(self.covered_features),
            "uncovered_features": list(self.uncovered_features),
            "estimated_seconds": round(self.estimated_seconds, 2),
            "budget_seconds": self.budget_seconds,
            "coverage_score": round(self.coverage_score, 4),
        }

    def format(self, fmt: str = "text") -> str:
        fmt = (fmt or "text").lower()
        if fmt == "json":
            return json.dumps(self.as_dict(), indent=2, sort_keys=True)
        if fmt in {"md", "markdown"}:
            return self._format_md()
        if fmt == "text":
            return self._format_text()
        raise ValueError(f"unknown format: {fmt!r}")

    def _format_text(self) -> str:
        lines = []
        lines.append(f"sauravsmoke - slate for {self.root}")
        lines.append(
            f"  candidates: {self.total_candidates}   "
            f"picks: {len(self.picks)}   "
            f"~{self.estimated_seconds:.1f}s"
            + (f" / budget {self.budget_seconds:.0f}s"
               if self.budget_seconds is not None else "")
        )
        lines.append(
            f"  coverage: {len(self.covered_features)}/"
            f"{self.total_features_available} features  "
            f"(weighted {self.coverage_score:.0%})"
        )
        lines.append("")
        for i, p in enumerate(self.picks, 1):
            lines.append(
                f"  {i:>2}. [{p.tier}] {p.path}  (~{p.cost_seconds:.1f}s)"
            )
            lines.append(f"        {p.rationale}")
        if self.uncovered_features:
            lines.append("")
            lines.append(
                f"  gap: {len(self.uncovered_features)} feature(s) untouched: "
                + ", ".join(self.uncovered_features[:10])
                + (" ..." if len(self.uncovered_features) > 10 else "")
            )
        return "\n".join(lines)

    def _format_md(self) -> str:
        lines = []
        lines.append(f"# sauravsmoke slate - `{self.root}`")
        lines.append("")
        lines.append(
            f"- candidates: **{self.total_candidates}**, "
            f"picks: **{len(self.picks)}**"
        )
        lines.append(
            f"- estimated runtime: **~{self.estimated_seconds:.1f}s**"
            + (f" (budget {self.budget_seconds:.0f}s)"
               if self.budget_seconds is not None else "")
        )
        lines.append(
            f"- feature coverage: **{len(self.covered_features)}/"
            f"{self.total_features_available}** "
            f"(weighted **{self.coverage_score:.0%}**)"
        )
        lines.append("")
        lines.append("## Slate")
        lines.append("")
        lines.append("| # | Tier | File | Cost | New features | Rationale |")
        lines.append("|--:|:---:|------|-----:|--------------|-----------|")
        for i, p in enumerate(self.picks, 1):
            nf = ", ".join(p.new_features[:6]) or "-"
            lines.append(
                f"| {i} | {p.tier} | `{p.path}` | {p.cost_seconds:.1f}s | "
                f"{nf} | {p.rationale} |"
            )
        if self.uncovered_features:
            lines.append("")
            lines.append("## Coverage gaps")
            lines.append("")
            lines.append(
                "Features no demo in this set touches (consider adding one):"
            )
            lines.append("")
            for f in self.uncovered_features:
                lines.append(f"- `{f}`")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Feature detection
# ---------------------------------------------------------------------------


_COMPILED: dict[str, re.Pattern[str]] = {
    fid: re.compile(pattern, re.MULTILINE)
    for fid, (_, pattern) in FEATURE_CATALOGUE.items()
}


def detect_features(source: str) -> list[str]:
    """Return the sorted list of feature ids touched by ``source``."""
    hits: list[str] = []
    for fid, pat in _COMPILED.items():
        if pat.search(source):
            hits.append(fid)
    hits.sort()
    return hits


def estimate_cost_seconds(source: str) -> float:
    """Cheap runtime estimate for a sauravcode demo.

    Uses line count + simple complexity signals (loop / function density)
    rather than real timing. Returns seconds in a small, capped range so
    a single very long demo can't dominate the budget.
    """
    lines = source.splitlines() or [""]
    line_count = sum(1 for ln in lines if ln.strip() and not ln.lstrip().startswith("#"))
    # Base: 0.05s per non-empty non-comment line
    base = 0.05 * line_count
    # Loop / nesting weight
    loops = sum(1 for ln in lines if re.match(r"\s*(for|while)\b", ln))
    base += 0.10 * loops
    # Cap so one giant file doesn't eat the entire budget
    return round(max(0.2, min(base, 8.0)), 2)


# ---------------------------------------------------------------------------
# Smoker
# ---------------------------------------------------------------------------


@dataclass
class Smoker:
    """Agentic smoke-test slate builder."""

    root: Path | str = "."
    feature_weights: dict[str, int] = field(default_factory=dict)
    include_subdirs: bool = True
    _candidates_cache: list[SmokeCandidate] | None = field(
        default=None, init=False, repr=False
    )

    # ---- discovery ---------------------------------------------------

    def _iter_srv_files(self) -> Iterable[Path]:
        root = Path(self.root)
        if not root.exists():
            return
        pattern = "**/*.srv" if self.include_subdirs else "*.srv"
        # Sort for deterministic output
        for p in sorted(root.glob(pattern)):
            if p.is_file():
                yield p

    # ---- weight resolution (shared by scan & recommend) ------------

    def _resolved_weights(self) -> dict[str, int]:
        """Catalogue defaults overlaid with any per-instance overrides."""
        return {
            **{fid: w for fid, (w, _) in FEATURE_CATALOGUE.items()},
            **self.feature_weights,
        }

    # ---- scan --------------------------------------------------------

    def scan(self) -> list[SmokeCandidate]:
        """Discover and score every ``.srv`` file under ``root``."""
        cands: list[SmokeCandidate] = []
        weights = self._resolved_weights()
        root = Path(self.root)
        for path in self._iter_srv_files():
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            features = detect_features(source)
            rel = path.relative_to(root).as_posix() if path.is_relative_to(root) \
                else path.as_posix()
            cands.append(SmokeCandidate(
                path=rel,
                is_test=path.name.lower().startswith("test_"),
                line_count=sum(1 for _ in source.splitlines()),
                feature_ids=features,
                cost_seconds=estimate_cost_seconds(source),
                feature_weight=sum(weights.get(f, 1) for f in features),
            ))
        self._candidates_cache = cands
        return cands

    # ---- recommendation ---------------------------------------------

    def recommend(
        self,
        budget_seconds: float | None = None,
        top: int | None = None,
    ) -> SmokeSlate:
        """Build the smoke slate.

        Algorithm
        ---------
        1. Always include every ``test_*.srv`` first (P0).
        2. Greedily pick the file that contributes the highest *weighted new
           coverage per second* until coverage saturates or budget is hit.
        3. Tag the rest as P3 "duplicate coverage" - they're still listed if
           ``top`` allows, but only run if budget remains.

        The three phases are factored out into ``_seed_p0_tests``,
        ``_greedy_pick`` and ``_fill_p3_tail`` so each phase is
        individually testable and the overall flow stays readable.
        """
        cands = self.scan()
        weights = self._resolved_weights()
        total_weight = sum(weights.get(f, 1) for f in FEATURE_CATALOGUE)

        state = _SlateState()

        self._seed_p0_tests(cands, state)
        self._greedy_pick(cands, state, weights, budget_seconds, top)
        self._fill_p3_tail(cands, state, budget_seconds, top)

        covered_weight = sum(weights.get(f, 1) for f in state.covered)
        return SmokeSlate(
            root=str(self.root),
            total_candidates=len(cands),
            total_features_available=len(FEATURE_CATALOGUE),
            picks=state.picks,
            covered_features=sorted(state.covered),
            uncovered_features=sorted(set(FEATURE_CATALOGUE) - state.covered),
            estimated_seconds=round(state.spent, 2),
            budget_seconds=budget_seconds,
            coverage_score=(covered_weight / total_weight) if total_weight else 0.0,
        )

    # ---- recommend phases -------------------------------------------

    @staticmethod
    def _seed_p0_tests(
        cands: list[SmokeCandidate], state: "_SlateState"
    ) -> None:
        """Phase 1: include every ``test_*.srv`` candidate as a P0 pick."""
        for c in sorted((c for c in cands if c.is_test), key=lambda c: c.path):
            new = sorted(set(c.feature_ids) - state.covered)
            state.add(c, SmokePick(
                path=c.path,
                tier="P0",
                new_features=new,
                cumulative_features=len(state.covered) + len(new),
                cost_seconds=c.cost_seconds,
                rationale=(
                    f"test file ({c.line_count} lines); "
                    + (f"adds {len(new)} new feature(s)" if new
                       else "no new features but tests must run")
                ),
            ))

    @staticmethod
    def _greedy_pick(
        cands: list[SmokeCandidate],
        state: "_SlateState",
        weights: dict[str, int],
        budget_seconds: float | None,
        top: int | None,
    ) -> None:
        """Phase 2: greedily add the highest value-per-second pick.

        Value is *weighted new coverage* divided by cost (clamped so a
        zero-cost file can't divide by zero). On the very first greedy
        pick we accept a budget overshoot so an empty slate isn't left
        with zero coverage; subsequent picks must fit the budget or look
        for a cheaper alternative.
        """
        remaining = [c for c in cands if c.path not in state.used]
        first_greedy_pick = True

        while remaining:
            if budget_seconds is not None and state.spent >= budget_seconds:
                break
            remaining.sort(
                key=lambda c: (-_value(c, state.covered, weights),
                               c.cost_seconds, c.path)
            )
            best = remaining[0]
            if _value(best, state.covered, weights) <= 0:
                break  # no remaining candidate adds new coverage

            if (budget_seconds is not None
                    and state.spent + best.cost_seconds > budget_seconds
                    and not first_greedy_pick):
                cheaper = [
                    c for c in remaining
                    if _value(c, state.covered, weights) > 0
                    and state.spent + c.cost_seconds <= budget_seconds
                ]
                if not cheaper:
                    break
                cheaper.sort(
                    key=lambda c: (-_value(c, state.covered, weights),
                                   c.cost_seconds, c.path)
                )
                best = cheaper[0]

            new = sorted(set(best.feature_ids) - state.covered)
            tier = "P1" if len(new) >= 3 else "P2"
            state.add(best, SmokePick(
                path=best.path,
                tier=tier,
                new_features=new,
                cumulative_features=len(state.covered) + len(new),
                cost_seconds=best.cost_seconds,
                rationale=(
                    f"adds {len(new)} new feature(s): "
                    + ", ".join(new[:5])
                    + (" ..." if len(new) > 5 else "")
                ),
            ))
            remaining.remove(best)
            first_greedy_pick = False

            if top is not None and len(state.picks) >= top:
                break

    @staticmethod
    def _fill_p3_tail(
        cands: list[SmokeCandidate],
        state: "_SlateState",
        budget_seconds: float | None,
        top: int | None,
    ) -> None:
        """Phase 3: pad the slate with duplicate-coverage P3 picks.

        Only triggered when the caller asked for a specific ``top`` count
        and the useful coverage greedy phase didn't fill it.
        """
        if top is None or len(state.picks) >= top:
            return
        tail = sorted(
            (c for c in cands if c.path not in state.used),
            key=lambda c: (c.cost_seconds, c.path),
        )
        for c in tail:
            if len(state.picks) >= top:
                break
            if (budget_seconds is not None
                    and state.spent + c.cost_seconds > budget_seconds):
                continue
            state.add(c, SmokePick(
                path=c.path,
                tier="P3",
                new_features=[],
                cumulative_features=len(state.covered),
                cost_seconds=c.cost_seconds,
                rationale="duplicate coverage; runs only if budget allows",
            ))


# ---------------------------------------------------------------------------
# Internal helpers for the recommend() algorithm
# ---------------------------------------------------------------------------


@dataclass
class _SlateState:
    """Mutable bookkeeping shared across recommend()'s three phases."""

    covered: set[str] = field(default_factory=set)
    used: set[str] = field(default_factory=set)
    picks: list[SmokePick] = field(default_factory=list)
    spent: float = 0.0

    def add(self, candidate: SmokeCandidate, pick: SmokePick) -> None:
        self.covered.update(candidate.feature_ids)
        self.used.add(candidate.path)
        self.spent += candidate.cost_seconds
        self.picks.append(pick)


def _value(
    candidate: SmokeCandidate,
    covered: set[str],
    weights: dict[str, int],
) -> float:
    """Weighted new-coverage density (per second) for the greedy phase."""
    new = set(candidate.feature_ids) - covered
    if not new:
        return 0.0
    w = sum(weights.get(f, 1) for f in new)
    return w / max(candidate.cost_seconds, 0.1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sauravsmoke",
        description=(
            "Agentic smoke-test slate builder for sauravcode: greedily picks "
            "a minimal set of .srv demos / tests that together exercise the "
            "broadest language + stdlib surface inside a time budget."
        ),
    )
    p.add_argument("--root", default=".", help="Project root (default: .)")
    p.add_argument("--budget", type=float, default=None,
                   help="Time budget in seconds (default: unlimited)")
    p.add_argument("--top", type=int, default=None,
                   help="Cap total picks at N (default: all useful)")
    p.add_argument("--format", choices=("text", "md", "json"), default="text",
                   help="Output format")
    p.add_argument("--no-subdirs", action="store_true",
                   help="Don't recurse into subdirectories")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    smoker = Smoker(root=args.root, include_subdirs=not args.no_subdirs)
    slate = smoker.recommend(budget_seconds=args.budget, top=args.top)
    print(slate.format(args.format))
    return 0


if __name__ == "__main__":
    sys.exit(main())
