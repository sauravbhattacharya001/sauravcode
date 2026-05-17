"""
sauravcoach - Agentic personalized learning coach for sauravcode users.

Given a directory of the user's ``.srv`` files (their own project / scratch
folder), sauravcoach profiles which language and stdlib features they
actually use, builds a skill-adjacency graph, and recommends the next set
of features they should learn -- ranked by *projected utility in their own
code*, not generic difficulty.

For every recommendation it tries to attach a paste-ready snippet pulled
from the matching ``<feature>_demo.srv`` shipped with the repo, so the
user can immediately see the feature in action.

Agentic behavior
----------------
- **Awareness** -- counts how many of the user's files touch each of the
  41 catalogued features (regex catalogue is reused from ``sauravsmoke``).
- **Inference** -- classifies each feature as ``mastered`` (>=3 files),
  ``practiced`` (1-2 files), or ``untouched`` (0 files).
- **Recommendation** -- for every untouched feature, scores
  ``base_weight + adjacency_bonus + utility_bonus`` where:

  * ``base_weight`` comes from the feature catalogue weight (1..5).
  * ``adjacency_bonus`` = 1.5 per mastered + 0.75 per practiced neighbour
    in the hand-curated learning graph.
  * ``utility_bonus`` = up to +3.0 when the user's code shows patterns the
    feature would naturally improve (manual loops -> pipes/higher_order,
    string concat with '+' -> fstring, dict-of-list trees -> graph/trie,
    no try/except -> try_catch, no assert/contract -> assert/validation).

- **Explainability** -- every pick carries reasons + which mastered/
  practiced features link to it, plus a P0/P1/P2/P3 priority tier:

  * **P0** weight>=4 foundational gap (you really should know this)
  * **P1** strong adjacency (>=2 known neighbours)
  * **P2** medium weight enrichment
  * **P3** exotic / niche

Public API
----------
- ``Coach(user_root=".", demos_root=None)``
- ``Coach.profile()`` -> ``list[FeatureSkill]``
- ``Coach.recommend(top=None)`` -> ``CoachReport``
- ``CoachReport.format(fmt="text"|"md"|"json")``

CLI
---
::

    python -m sauravcoach --root my_project/ --format md
    python -m sauravcoach --root . --demos demos/ --top 5 --format json

Standalone (stdlib only); no third-party deps; no side-effecting imports
from the rest of the sauravcode runtime (the regex catalogue is imported
read-only from ``sauravsmoke`` if available, otherwise copied verbatim
below).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

__all__ = [
    "FEATURE_CATALOGUE",
    "ADJACENCY",
    "FeatureSkill",
    "CoachRecommendation",
    "CoachReport",
    "Coach",
    "main",
]


# ---------------------------------------------------------------------------
# Feature catalogue
# ---------------------------------------------------------------------------
#
# Mirrors ``sauravsmoke.FEATURE_CATALOGUE`` so this module stays standalone
# even if sauravsmoke is unavailable. Format: ``name -> (weight, regex)``.
_FALLBACK_CATALOGUE: dict[str, tuple[int, str]] = {
    "if_else":        (5, r"^\s*if\s+|^\s*else\s*$|^\s*else\s+if\b"),
    "while_loop":     (4, r"^\s*while\s+"),
    "for_range":      (4, r"^\s*for\s+\w+\s*=\s*\d+\s+to\s+"),
    "for_each":       (4, r"^\s*for\s+\w+\s+in\s+"),
    "break_continue": (3, r"^\s*(break|continue)\b"),
    "function_def":   (5, r"^\s*func\s+\w+\s*\("),
    "lambda":         (3, r"\blambda\s+[\w,\s]*:"),
    "pipe":           (3, r"\|>"),
    "higher_order":   (3, r"\b(map|filter|reduce|fold)\s*\("),
    "recursion_hint": (2, r"^\s*func\s+(\w+)\s*\([^)]*\)\s*:[\s\S]*\b\1\s*\("),
    "fstring":        (4, r"f\"[^\"\n]*\{"),
    "string_methods": (3, r"\.(upper|lower|split|join|strip|replace|startswith|endswith|find|count)\s*\("),
    "list":           (4, r"^\s*\w+\s*=\s*\["),
    "map_literal":    (3, r"^\s*\w+\s*=\s*\{[^}]*:"),
    "set_literal":    (2, r"^\s*\w+\s*=\s*\{[^:}]+\}\s*$"),
    "matrix":         (2, r"\bmatrix\s*\("),
    "print":          (5, r"\bprint\s*\("),
    "try_catch":      (4, r"\btry\b|\bcatch\b|\bexcept\b"),
    "assert":         (3, r"\bassert\b"),
    "input_read":     (2, r"\binput\s*\("),
    "json":           (3, r"\bjson(_load|_dump|\.parse|\.stringify)?\s*\("),
    "regex":          (3, r"\b(re|regex)\.(match|search|findall|sub)\s*\("),
    "datetime":       (2, r"\b(now|today|datetime|date|time)\s*\("),
    "csv":            (2, r"\bcsv(_read|_write|\.read|\.write)\s*\("),
    "http":           (2, r"\bhttp(_get|_post|\.get|\.post|\.request)\s*\("),
    "logging":        (2, r"\blog\.(info|warn|warning|error|debug)\s*\("),
    "hash":           (2, r"\b(hash|sha\d+|md5|hmac)\s*\("),
    "cipher":         (1, r"\b(encrypt|decrypt|cipher)\s*\("),
    "compression":    (1, r"\b(gzip|zlib|compress|decompress)\s*\("),
    "graph":          (2, r"\bgraph\s*\("),
    "heap":           (2, r"\b(heap|push_heap|pop_heap|heappush|heappop)\s*\("),
    "deque":          (2, r"\bdeque\s*\("),
    "linkedlist":     (1, r"\blinkedlist\s*\("),
    "trie":           (1, r"\btrie\s*\("),
    "ring_buffer":    (1, r"\bring(_buffer)?\s*\("),
    "stats":          (2, r"\b(mean|median|stdev|variance|quantile)\s*\("),
    "plot":           (1, r"\bplot\s*\("),
    "automata":       (1, r"\b(fsm|automaton|dfa|nfa)\s*\("),
    "forecast":       (1, r"\b(forecast|predict|arima|holt)\s*\("),
    "validation":     (2, r"\b(validate|require|ensure|check)\s*\("),
    "bloom":          (1, r"\bbloom(_filter)?\s*\("),
}

try:  # prefer the canonical catalogue if present
    from sauravsmoke import FEATURE_CATALOGUE as _SMOKE_CATALOGUE  # type: ignore
    FEATURE_CATALOGUE: dict[str, tuple[int, str]] = dict(_SMOKE_CATALOGUE)
except Exception:  # pragma: no cover - defensive
    FEATURE_CATALOGUE = dict(_FALLBACK_CATALOGUE)


# ---------------------------------------------------------------------------
# Learning adjacency graph (hand-curated edges)
# ---------------------------------------------------------------------------
ADJACENCY: dict[str, list[str]] = {
    "if_else":        ["while_loop", "for_each", "try_catch", "assert"],
    "while_loop":     ["if_else", "for_range", "break_continue"],
    "for_range":      ["while_loop", "for_each", "break_continue"],
    "for_each":       ["for_range", "list", "higher_order", "pipe"],
    "break_continue": ["while_loop", "for_range"],
    "function_def":   ["lambda", "recursion_hint", "higher_order", "try_catch"],
    "lambda":         ["higher_order", "pipe", "function_def"],
    "pipe":           ["higher_order", "lambda", "for_each"],
    "higher_order":   ["lambda", "pipe", "list", "for_each"],
    "recursion_hint": ["function_def"],
    "fstring":        ["print", "string_methods", "logging"],
    "string_methods": ["fstring", "regex", "list"],
    "list":           ["for_each", "higher_order", "map_literal", "set_literal"],
    "map_literal":    ["list", "set_literal", "json"],
    "set_literal":    ["list", "map_literal"],
    "matrix":         ["list", "stats"],
    "print":          ["fstring", "logging"],
    "try_catch":      ["assert", "validation", "function_def"],
    "assert":         ["try_catch", "validation"],
    "input_read":     ["print", "validation"],
    "json":           ["map_literal", "http", "csv"],
    "regex":          ["string_methods", "fstring", "validation"],
    "datetime":       ["logging", "forecast"],
    "csv":            ["json", "list", "stats"],
    "http":           ["json", "try_catch", "logging"],
    "logging":        ["fstring", "datetime", "try_catch"],
    "hash":           ["cipher", "bloom"],
    "cipher":         ["hash"],
    "compression":    ["hash"],
    "graph":          ["heap", "trie", "linkedlist"],
    "heap":           ["graph", "deque"],
    "deque":          ["heap", "ring_buffer", "linkedlist"],
    "linkedlist":     ["deque", "graph"],
    "trie":           ["graph", "string_methods"],
    "ring_buffer":    ["deque"],
    "stats":          ["matrix", "csv", "forecast", "plot"],
    "plot":           ["stats", "matrix"],
    "automata":       ["graph"],
    "forecast":       ["stats", "datetime"],
    "validation":     ["assert", "try_catch", "regex"],
    "bloom":          ["hash"],
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class FeatureSkill:
    feature: str
    weight: int
    user_files: list[str] = field(default_factory=list)
    skill: str = "untouched"  # mastered | practiced | untouched


@dataclass
class CoachRecommendation:
    feature: str
    priority: str               # P0|P1|P2|P3
    score: float
    weight: int
    adjacency_bonus: float
    utility_bonus: float
    reasons: list[str]
    adjacent_mastered: list[str]
    example_demo: str | None
    example_snippet: str | None


@dataclass
class CoachReport:
    root: str
    user_files_scanned: int
    skill_score: int            # 0-100
    skill_grade: str            # A-F
    mastered: list[str]
    practiced: list[str]
    untouched: list[str]
    recommendations: list[CoachRecommendation]
    summary: str

    # ----- formatters -----
    def format(self, fmt: str = "text") -> str:
        fmt = (fmt or "text").lower()
        if fmt == "json":
            return self._to_json()
        if fmt in ("md", "markdown"):
            return self._to_md()
        return self._to_text()

    def _to_json(self) -> str:
        payload = asdict(self)
        return json.dumps(payload, indent=2, sort_keys=False)

    def _to_text(self) -> str:
        lines: list[str] = []
        lines.append(f"sauravcoach - learning coach for {self.root}")
        lines.append("=" * 60)
        lines.append(
            f"Files scanned: {self.user_files_scanned}    "
            f"Skill: {self.skill_score}/100  (grade {self.skill_grade})"
        )
        lines.append(self.summary)
        lines.append("")
        lines.append(f"Mastered  ({len(self.mastered)}): {', '.join(self.mastered) or '-'}")
        lines.append(f"Practiced ({len(self.practiced)}): {', '.join(self.practiced) or '-'}")
        lines.append(f"Untouched ({len(self.untouched)}): {len(self.untouched)} features")
        lines.append("")
        lines.append("Recommendations:")
        if not self.recommendations:
            lines.append("  (none -- you're covering the catalogue!)")
        for r in self.recommendations:
            lines.append(
                f"  [{r.priority}] {r.feature:<16} score={r.score:5.2f} "
                f"(w={r.weight} adj={r.adjacency_bonus:+.2f} util={r.utility_bonus:+.2f})"
            )
            for reason in r.reasons:
                lines.append(f"      - {reason}")
            if r.adjacent_mastered:
                lines.append(f"      builds on: {', '.join(r.adjacent_mastered)}")
            if r.example_demo:
                lines.append(f"      example: {r.example_demo}")
        return "\n".join(lines)

    def _to_md(self) -> str:
        lines: list[str] = []
        lines.append(f"# sauravcoach report - `{self.root}`")
        lines.append("")
        lines.append(
            f"**Files scanned:** {self.user_files_scanned}  "
            f"**Skill:** {self.skill_score}/100 (grade **{self.skill_grade}**)"
        )
        lines.append("")
        lines.append(f"> {self.summary}")
        lines.append("")
        lines.append("## Skill profile")
        lines.append("")
        lines.append(f"- **Mastered ({len(self.mastered)}):** "
                     f"{', '.join(f'`{x}`' for x in self.mastered) or '_none_'}")
        lines.append(f"- **Practiced ({len(self.practiced)}):** "
                     f"{', '.join(f'`{x}`' for x in self.practiced) or '_none_'}")
        lines.append(f"- **Untouched:** {len(self.untouched)} features")
        lines.append("")
        lines.append("## Recommendations")
        lines.append("")
        if not self.recommendations:
            lines.append("_You're covering the catalogue. Nothing to suggest._")
        for r in self.recommendations:
            lines.append(f"### [{r.priority}] `{r.feature}` -- score {r.score:.2f}")
            lines.append("")
            lines.append(
                f"_weight {r.weight}, adjacency {r.adjacency_bonus:+.2f}, "
                f"utility {r.utility_bonus:+.2f}_"
            )
            lines.append("")
            for reason in r.reasons:
                lines.append(f"- {reason}")
            if r.adjacent_mastered:
                lines.append(f"- builds on: {', '.join(f'`{x}`' for x in r.adjacent_mastered)}")
            if r.example_demo and r.example_snippet:
                lines.append("")
                lines.append(f"Example from `{r.example_demo}`:")
                lines.append("")
                lines.append("```")
                lines.append(r.example_snippet)
                lines.append("```")
            lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Coach
# ---------------------------------------------------------------------------
class Coach:
    """Profile a user's .srv corpus and recommend learning targets."""

    def __init__(
        self,
        user_root: str | Path = ".",
        demos_root: str | Path | None = None,
    ) -> None:
        self.user_root = Path(user_root).resolve()
        self.demos_root = Path(demos_root).resolve() if demos_root else self.user_root
        # Pre-compile catalogue patterns
        self._patterns: dict[str, re.Pattern[str]] = {
            name: re.compile(rx, re.MULTILINE)
            for name, (_, rx) in FEATURE_CATALOGUE.items()
        }
        # State filled by scan_user()
        self._user_files: list[Path] = []
        self._file_features: dict[Path, set[str]] = {}

    # ----------------------- scanning -----------------------
    def _iter_srv(self, root: Path) -> Iterable[Path]:
        if not root.exists():
            return
        for p in sorted(root.rglob("*.srv")):
            # Skip our own demos_root if we're scanning user_root and they differ
            try:
                if (
                    self.demos_root != self.user_root
                    and self.demos_root in p.parents
                ):
                    continue
            except Exception:
                pass
            yield p

    def _scan_user(self) -> None:
        if self._user_files:
            return
        for p in self._iter_srv(self.user_root):
            self._user_files.append(p)
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                text = ""
            feats: set[str] = set()
            for name, pat in self._patterns.items():
                if pat.search(text):
                    feats.add(name)
            self._file_features[p] = feats

    # ----------------------- public API -----------------------
    def profile(self) -> list[FeatureSkill]:
        self._scan_user()
        per_feature_files: dict[str, list[str]] = defaultdict(list)
        for path, feats in self._file_features.items():
            for f in feats:
                per_feature_files[f].append(path.name)

        skills: list[FeatureSkill] = []
        for name, (weight, _rx) in FEATURE_CATALOGUE.items():
            files = sorted(per_feature_files.get(name, []))
            if len(files) >= 3:
                skill = "mastered"
            elif len(files) >= 1:
                skill = "practiced"
            else:
                skill = "untouched"
            skills.append(
                FeatureSkill(feature=name, weight=weight, user_files=files, skill=skill)
            )
        return skills

    # --- utility heuristics ----------------------------------
    def _detect_utility_signals(self) -> dict[str, list[str]]:
        """Return {feature -> list of human-readable reasons}."""
        signals: dict[str, list[str]] = defaultdict(list)
        manual_loop_files = 0
        string_concat_files = 0
        no_try_files = 0
        no_assert_files = 0
        nested_dict_files = 0
        for path, feats in self._file_features.items():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            # manual loops -> pipes / higher_order
            if re.search(r"^\s*for\s+\w+\s+in\s+", text, re.MULTILINE):
                if "pipe" not in feats or "higher_order" not in feats:
                    manual_loop_files += 1
            # '+ ' string concat with quotes -> fstring
            if re.search(r"\"[^\"\n]*\"\s*\+\s*\w+|\w+\s*\+\s*\"[^\"\n]*\"", text):
                if "fstring" not in feats:
                    string_concat_files += 1
            # no try/catch in a file that does IO-ish things
            if "try_catch" not in feats and re.search(
                r"\b(http|input|json|csv|open)\s*\(", text
            ):
                no_try_files += 1
            # no assertions in a file with func defs
            if "assert" not in feats and "function_def" in feats:
                no_assert_files += 1
            # dict-of-dict nesting hints at graph/trie
            if re.search(r"\{[^{}\n]*\{", text):
                nested_dict_files += 1

        if manual_loop_files:
            signals["pipe"].append(
                f"{manual_loop_files} file(s) have manual for-each loops that pipes/higher-order would simplify"
            )
            signals["higher_order"].append(
                f"{manual_loop_files} file(s) have manual for-each loops -- map/filter/reduce would be cleaner"
            )
        if string_concat_files:
            signals["fstring"].append(
                f"{string_concat_files} file(s) use '+' string concatenation -- f-strings are the idiomatic fix"
            )
        if no_try_files:
            signals["try_catch"].append(
                f"{no_try_files} file(s) do IO without error handling"
            )
        if no_assert_files:
            signals["assert"].append(
                f"{no_assert_files} file(s) define functions without any assertions"
            )
            signals["validation"].append(
                f"{no_assert_files} file(s) define functions without input validation"
            )
        if nested_dict_files:
            signals["graph"].append(
                f"{nested_dict_files} file(s) build nested-dict structures -- a graph type would model them better"
            )
            signals["trie"].append(
                f"{nested_dict_files} file(s) build nested-dict structures -- consider a trie for string keys"
            )
        return signals

    # --- snippet extraction ----------------------------------
    def _find_snippet(self, feature: str) -> tuple[str | None, str | None]:
        if not self.demos_root.exists():
            return None, None
        # Primary: exact filename
        candidates = [
            self.demos_root / f"{feature}_demo.srv",
            self.demos_root / f"{feature}.srv",
        ]
        # Aliases for slightly off names
        aliases = {
            "fstring":       ["fstring_demo.srv"],
            "for_each":      ["foreach_demo.srv"],
            "for_range":     ["foreach_demo.srv"],
            "if_else":       ["break_continue_demo.srv"],
            "function_def":  ["foreach_demo.srv"],
            "string_methods": ["fstring_demo.srv"],
            "map_literal":   ["map_demo.srv"],
            "set_literal":   ["collection_demo.srv"],
            "lambda":        ["pipe_demo.srv"],
            "higher_order":  ["pipe_demo.srv"],
            "input_read":    ["env_sys_demo.srv"],
            "logging":       ["logging_demo.srv"],
            "datetime":      ["datetime_demo.srv"],
            "recursion_hint": ["foreach_demo.srv"],
            "ring_buffer":   ["ring_demo.srv"],
            "assert":        ["assert_demo.srv"],
            "validation":    ["validation_demo.srv"],
        }
        for alias in aliases.get(feature, []):
            candidates.append(self.demos_root / alias)
        for c in candidates:
            if c.exists():
                snippet = self._extract_snippet_from(c)
                if snippet:
                    return c.name, snippet
        return None, None

    @staticmethod
    def _extract_snippet_from(path: Path, max_lines: int = 18) -> str | None:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None
        kept: list[str] = []
        for line in raw.splitlines():
            stripped = line.strip()
            # Skip pure header comments / blank lines until we have some code
            if not kept and (not stripped or stripped.startswith("#")):
                continue
            kept.append(line.rstrip())
            if len(kept) >= max_lines:
                break
        snippet = "\n".join(kept).strip()
        return snippet or None

    # ----------------------- recommend -----------------------
    def recommend(self, top: int | None = None) -> CoachReport:
        skills = self.profile()
        by_skill = {s.feature: s for s in skills}
        mastered = [s.feature for s in skills if s.skill == "mastered"]
        practiced = [s.feature for s in skills if s.skill == "practiced"]
        untouched = [s.feature for s in skills if s.skill == "untouched"]

        utility = self._detect_utility_signals()

        recs: list[CoachRecommendation] = []
        for feat in untouched:
            weight = by_skill[feat].weight
            neighbours = ADJACENCY.get(feat, [])
            adj_mastered = [n for n in neighbours if by_skill.get(n, FeatureSkill(n, 0)).skill == "mastered"]
            adj_practiced = [n for n in neighbours if by_skill.get(n, FeatureSkill(n, 0)).skill == "practiced"]
            adj_bonus = 1.5 * len(adj_mastered) + 0.75 * len(adj_practiced)

            util_reasons = utility.get(feat, [])
            util_bonus = min(3.0, 1.0 * len(util_reasons) + (0.5 if util_reasons else 0.0))

            score = float(weight) + adj_bonus + util_bonus

            # Priority bucket
            if weight >= 4:
                priority = "P0"
            elif len(adj_mastered) + len(adj_practiced) >= 2:
                priority = "P1"
            elif weight >= 2:
                priority = "P2"
            else:
                priority = "P3"

            reasons: list[str] = []
            if adj_mastered:
                reasons.append(
                    f"links to {len(adj_mastered)} mastered feature(s): {', '.join(adj_mastered)}"
                )
            if adj_practiced:
                reasons.append(
                    f"links to {len(adj_practiced)} practiced feature(s): {', '.join(adj_practiced)}"
                )
            if weight >= 4 and not adj_mastered and not adj_practiced:
                reasons.append("foundational feature you haven't touched yet")
            reasons.extend(util_reasons)
            if not reasons:
                reasons.append("rounds out catalogue coverage")

            demo, snippet = self._find_snippet(feat)
            recs.append(
                CoachRecommendation(
                    feature=feat,
                    priority=priority,
                    score=round(score, 2),
                    weight=weight,
                    adjacency_bonus=round(adj_bonus, 2),
                    utility_bonus=round(util_bonus, 2),
                    reasons=reasons,
                    adjacent_mastered=adj_mastered,
                    example_demo=demo,
                    example_snippet=snippet,
                )
            )

        # Sort: P0<P1<P2<P3 then by score desc then feature name
        prio_rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        recs.sort(key=lambda r: (prio_rank.get(r.priority, 9), -r.score, r.feature))
        if top is not None and top > 0:
            recs = recs[:top]

        # Skill score = weighted coverage 0..100
        total_weight = sum(w for w, _ in FEATURE_CATALOGUE.values())
        earned = 0.0
        for s in skills:
            if s.skill == "mastered":
                earned += s.weight
            elif s.skill == "practiced":
                earned += 0.5 * s.weight
        skill_score = int(round(100.0 * earned / total_weight)) if total_weight else 0
        skill_grade = _grade(skill_score)

        n_files = len(self._user_files)
        summary = _build_summary(n_files, skill_score, skill_grade, mastered, untouched, recs)

        return CoachReport(
            root=str(self.user_root),
            user_files_scanned=n_files,
            skill_score=skill_score,
            skill_grade=skill_grade,
            mastered=mastered,
            practiced=practiced,
            untouched=untouched,
            recommendations=recs,
            summary=summary,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _grade(score: int) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    if score >= 20:
        return "E"
    return "F"


def _build_summary(
    n_files: int,
    score: int,
    grade: str,
    mastered: list[str],
    untouched: list[str],
    recs: list[CoachRecommendation],
) -> str:
    if n_files == 0:
        return (
            "No .srv files found in the user root. Start with the P0 recommendations "
            "below -- they are the foundational features every sauravcode program leans on."
        )
    top = recs[0].feature if recs else None
    msg = (
        f"Scanned {n_files} file(s); skill {score}/100 (grade {grade}). "
        f"You've mastered {len(mastered)} feature(s), {len(untouched)} still untouched."
    )
    if top:
        msg += f" Next best feature to learn: '{top}' ({recs[0].priority})."
    return msg


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sauravcoach",
        description="Agentic learning coach: profile your sauravcode skills and recommend what to learn next.",
    )
    parser.add_argument("--root", default=".", help="Directory of the user's .srv files (default: .)")
    parser.add_argument("--demos", default=None, help="Directory of *_demo.srv files (default: same as --root)")
    parser.add_argument("--top", type=int, default=None, help="Limit recommendations to N entries")
    parser.add_argument("--format", choices=["text", "md", "json"], default="text")
    args = parser.parse_args(argv)

    coach = Coach(user_root=args.root, demos_root=args.demos)
    report = coach.recommend(top=args.top)
    sys.stdout.write(report.format(args.format))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
