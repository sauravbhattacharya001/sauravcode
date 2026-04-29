#!/usr/bin/env python3
"""sauravdebt — Autonomous Technical Debt Tracker for sauravcode.

Scans .srv codebases to identify, classify, prioritise, and track technical
debt over time.  Each finding gets a severity, estimated fix effort, impact
score, and ROI ranking so you know exactly what to tackle first.

Maintains a historical timeline (.debt-history.json) to detect new debt,
resolved debt, and velocity trends across snapshots.

Debt catalogue (12 detectors):
    D001  TODO/FIXME/HACK         Comment markers indicating known debt
    D002  Duplicated Code Blocks  Near-identical blocks across functions
    D003  Magic Numbers           Unexplained numeric literals
    D004  Missing Error Handling  File/network ops without try/catch
    D005  Dead Code               Functions defined but never called
    D006  Long Functions          Functions exceeding 40 lines
    D007  Deep Nesting            Code nested >4 indent levels
    D008  Hardcoded Strings       Repeated string literals → constants
    D009  Missing Documentation   Functions without preceding comments
    D010  Complex Conditionals    If/elif chains with >4 branches
    D011  Inconsistent Style      Mixed naming conventions in a file
    D012  Coupling Hotspots       Functions called by / calling too many

Usage:
    python sauravdebt.py program.srv              # Scan a single file
    python sauravdebt.py .                        # Scan all .srv files in cwd
    python sauravdebt.py . --recursive            # Include subdirectories
    python sauravdebt.py . --html report.html     # Interactive HTML dashboard
    python sauravdebt.py . --json                 # JSON output
    python sauravdebt.py . --plan                 # Prioritised payoff plan
    python sauravdebt.py . --timeline             # Debt trend over time
    python sauravdebt.py . --new                  # Only new debt since last scan
    python sauravdebt.py . --resolved             # Recently resolved debt
    python sauravdebt.py . --severity critical    # Filter by severity
    python sauravdebt.py . --top 10               # Top N highest-ROI items
    python sauravdebt.py . --budget 20            # Alert if total exceeds budget
    python sauravdebt.py . --reset                # Clear timeline history
"""

import sys
import os
import re
import json
import math
import time as _time
import glob
import hashlib
import argparse
from collections import defaultdict, Counter
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Set, Optional, Tuple, Any
from datetime import datetime

__version__ = "1.0.0"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Windows UTF-8 fix ────────────────────────────────────────────────
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    import io as _io
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from _srv_utils import find_srv_files as _find_srv_files
from _termcolors import colors as _make_colors

_C = _make_colors()

# ── Constants ─────────────────────────────────────────────────────────

HISTORY_FILE = ".debt-history.json"

LONG_FUNC_LINES = 40
MAX_NESTING = 4
MAX_ELIF_BRANCHES = 4
MAX_CALLEES = 8
MAX_CALLERS = 8
DUPLICATE_STRING_THRESHOLD = 3
DUPLICATE_BLOCK_MIN_LINES = 3

TODO_RE = re.compile(r"#\s*(TODO|FIXME|HACK|XXX|KLUDGE)\b", re.IGNORECASE)
FUNC_DEF_RE = re.compile(r"^(\s*)(?:function|fn)\s+(\w+)\s*(.*)")
CALL_RE = re.compile(r"\b([a-zA-Z_]\w*)\s*\(")
STRING_LIT_RE = re.compile(r'''(?:"([^"\\]*(?:\\.[^"\\]*)*)"|'([^'\\]*(?:\\.[^'\\]*)*)')''')
MAGIC_NUM_RE = re.compile(r"\b(\d+\.?\d*)\b")
IO_KEYWORDS = {"open", "read", "write", "fetch", "request", "socket", "connect", "download", "upload", "http"}
COMMENT_RE = re.compile(r"^\s*#")

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


# ── Data Structures ──────────────────────────────────────────────────

@dataclass
class DebtItem:
    """A single technical debt finding."""
    id: str                   # D001, D002, …
    name: str
    file: str
    line: int
    severity: str             # critical / high / medium / low
    effort: int               # 1-5 (fix effort)
    impact: int               # 1-10 (health impact if fixed)
    description: str
    suggestion: str
    context: str = ""         # source snippet

    @property
    def roi_score(self) -> float:
        return round(self.impact / max(self.effort, 1), 2)

    @property
    def fingerprint(self) -> str:
        raw = f"{self.id}:{self.file}:{self.line}:{self.description}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]


@dataclass
class ScanResult:
    items: List[DebtItem] = field(default_factory=list)
    files_scanned: int = 0
    total_lines: int = 0
    scan_time: float = 0.0

    @property
    def debt_score(self) -> int:
        """0-100 health score (higher = less debt = healthier)."""
        if self.total_lines == 0:
            return 100
        # Weighted penalty per item
        penalty = 0.0
        for item in self.items:
            w = {"critical": 8, "high": 5, "medium": 3, "low": 1}.get(item.severity, 1)
            penalty += w
        # Normalise: 1 penalty point per 10 lines is 0 health
        raw = max(0, 100 - (penalty / max(self.total_lines / 10, 1)) * 10)
        return int(min(100, max(0, raw)))


@dataclass
class TimelineEntry:
    timestamp: str
    debt_count: int
    debt_score: int
    fingerprints: List[str]
    severity_counts: Dict[str, int]


# ── Helpers ───────────────────────────────────────────────────────────

def _indent_level(line: str) -> int:
    count = 0
    for ch in line:
        if ch == " ":
            count += 1
        elif ch == "\t":
            count += 4
        else:
            break
    return count


def _parse_functions(lines: List[str]) -> List[dict]:
    """Extract function definitions with bodies."""
    funcs = []
    i = 0
    while i < len(lines):
        m = FUNC_DEF_RE.match(lines[i])
        if m:
            indent = _indent_level(lines[i])
            name = m.group(2)
            params_raw = m.group(3).strip()
            # Parse params: could be (a, b) or just a b
            params_raw = params_raw.strip("()")
            params = [p.strip() for p in re.split(r"[,\s]+", params_raw) if p.strip()]
            start = i
            body_start = i + 1
            j = body_start
            while j < len(lines):
                stripped = lines[j].strip()
                if stripped == "":
                    j += 1
                    continue
                if _indent_level(lines[j]) <= indent and stripped != "":
                    break
                j += 1
            funcs.append({
                "name": name,
                "params": params,
                "start": start,
                "end": j - 1,
                "body_lines": lines[body_start:j],
                "all_lines": lines[start:j],
                "indent": indent,
            })
            i = j
        else:
            i += 1
    return funcs


def _tokenise_block(lines: List[str]) -> Tuple[str, ...]:
    """Normalise and tokenise a block for similarity comparison."""
    tokens = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Replace identifiers with placeholders for structural comparison
        normalised = re.sub(r"\b[a-zA-Z_]\w*\b", "ID", stripped)
        normalised = re.sub(r"\b\d+\b", "NUM", normalised)
        tokens.append(normalised)
    return tuple(tokens)


def _jaccard(a: Tuple, b: Tuple) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


# ── Detectors ─────────────────────────────────────────────────────────

def _detect_todo_markers(lines: List[str], filepath: str) -> List[DebtItem]:
    """D001: TODO/FIXME/HACK comment markers."""
    items = []
    for i, line in enumerate(lines, 1):
        m = TODO_RE.search(line)
        if m:
            marker = m.group(1).upper()
            sev = "high" if marker in ("FIXME", "HACK", "XXX") else "medium"
            items.append(DebtItem(
                id="D001", name="TODO/FIXME/HACK Marker",
                file=filepath, line=i, severity=sev, effort=2, impact=4,
                description=f"{marker} marker: {line.strip()}",
                suggestion=f"Address the {marker} or create a tracked issue.",
                context=line.rstrip(),
            ))
    return items


def _detect_duplicated_blocks(funcs: List[dict], filepath: str) -> List[DebtItem]:
    """D002: Near-identical code blocks across functions."""
    items = []
    blocks = []
    for f in funcs:
        body = [l for l in f["body_lines"] if l.strip() and not l.strip().startswith("#")]
        if len(body) >= DUPLICATE_BLOCK_MIN_LINES:
            blocks.append((f["name"], f["start"] + 1, _tokenise_block(body), body))

    seen_pairs: Set[Tuple[str, str]] = set()
    for i in range(len(blocks)):
        for j in range(i + 1, len(blocks)):
            n1, l1, t1, _ = blocks[i]
            n2, l2, t2, _ = blocks[j]
            pair_key = (min(n1, n2), max(n1, n2))
            if pair_key in seen_pairs:
                continue
            if len(t1) >= DUPLICATE_BLOCK_MIN_LINES and _jaccard(t1, t2) > 0.75:
                seen_pairs.add(pair_key)
                items.append(DebtItem(
                    id="D002", name="Duplicated Code Block",
                    file=filepath, line=l1, severity="high", effort=3, impact=7,
                    description=f"Functions '{n1}' and '{n2}' have ~{int(_jaccard(t1, t2)*100)}% structural similarity.",
                    suggestion=f"Extract shared logic into a common helper function.",
                ))
    return items


def _detect_magic_numbers(lines: List[str], filepath: str, funcs: List[dict]) -> List[DebtItem]:
    """D003: Unexplained numeric literals in logic."""
    items = []
    trivial = {"0", "1", "2", "0.0", "1.0", "100", "10"}
    num_occurrences: Dict[str, List[int]] = defaultdict(list)

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        # Skip function defs and simple assignments like x = 42
        for m in MAGIC_NUM_RE.finditer(stripped):
            val = m.group(1)
            if val not in trivial:
                num_occurrences[val].append(i)

    for val, locs in num_occurrences.items():
        if len(locs) >= 2:
            items.append(DebtItem(
                id="D003", name="Magic Number",
                file=filepath, line=locs[0], severity="low", effort=1, impact=3,
                description=f"Magic number {val} appears {len(locs)} times (lines {', '.join(str(l) for l in locs[:5])}).",
                suggestion=f"Extract {val} into a named constant.",
            ))
    return items


def _detect_missing_error_handling(funcs: List[dict], filepath: str) -> List[DebtItem]:
    """D004: Functions with I/O operations but no try/catch."""
    items = []
    for f in funcs:
        body_text = "\n".join(f["body_lines"]).lower()
        has_io = any(kw in body_text for kw in IO_KEYWORDS)
        has_try = "try" in body_text
        if has_io and not has_try:
            items.append(DebtItem(
                id="D004", name="Missing Error Handling",
                file=filepath, line=f["start"] + 1, severity="high", effort=3, impact=8,
                description=f"Function '{f['name']}' performs I/O without error handling.",
                suggestion="Wrap I/O operations in try/catch with appropriate error handling.",
            ))
    return items


def _detect_dead_code(funcs: List[dict], lines: List[str], filepath: str) -> List[DebtItem]:
    """D005: Functions defined but never called."""
    items = []
    all_text = "\n".join(lines)
    defined_names = {f["name"] for f in funcs}
    called_names: Set[str] = set()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for m in CALL_RE.finditer(stripped):
            called_names.add(m.group(1))
    # Also check non-call references
    for name in defined_names:
        # Count occurrences beyond the definition
        pattern = re.compile(r"\b" + re.escape(name) + r"\b")
        matches = pattern.findall(all_text)
        # The definition itself accounts for at least 1 match
        if len(matches) <= 1 and name not in called_names and name != "main":
            items.append(DebtItem(
                id="D005", name="Dead Code",
                file=filepath, line=[f["start"] + 1 for f in funcs if f["name"] == name][0],
                severity="medium", effort=1, impact=4,
                description=f"Function '{name}' is defined but never referenced.",
                suggestion="Remove unused function or add a call site.",
            ))
    return items


def _detect_long_functions(funcs: List[dict], filepath: str) -> List[DebtItem]:
    """D006: Functions exceeding threshold lines."""
    items = []
    for f in funcs:
        loc = len([l for l in f["body_lines"] if l.strip()])
        if loc > LONG_FUNC_LINES:
            sev = "critical" if loc > LONG_FUNC_LINES * 2 else "high"
            items.append(DebtItem(
                id="D006", name="Long Function",
                file=filepath, line=f["start"] + 1, severity=sev,
                effort=4, impact=6,
                description=f"Function '{f['name']}' has {loc} lines (threshold: {LONG_FUNC_LINES}).",
                suggestion="Break into smaller, focused helper functions.",
            ))
    return items


def _detect_deep_nesting(lines: List[str], filepath: str) -> List[DebtItem]:
    """D007: Code nested >4 indent levels."""
    items = []
    reported_lines: Set[int] = set()
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        level = _indent_level(line) // 4
        if level > MAX_NESTING and i not in reported_lines:
            reported_lines.add(i)
            items.append(DebtItem(
                id="D007", name="Deep Nesting",
                file=filepath, line=i, severity="medium", effort=3, impact=5,
                description=f"Code at nesting level {level} (max recommended: {MAX_NESTING}).",
                suggestion="Extract inner logic into helper functions or use early returns.",
                context=line.rstrip(),
            ))
    return items


def _detect_hardcoded_strings(lines: List[str], filepath: str) -> List[DebtItem]:
    """D008: Repeated string literals that should be constants."""
    items = []
    string_locs: Dict[str, List[int]] = defaultdict(list)
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for m in STRING_LIT_RE.finditer(stripped):
            val = m.group(1) or m.group(2)
            if val and len(val) > 3:  # skip short strings
                string_locs[val].append(i)

    for val, locs in string_locs.items():
        if len(locs) >= DUPLICATE_STRING_THRESHOLD:
            items.append(DebtItem(
                id="D008", name="Hardcoded String",
                file=filepath, line=locs[0], severity="low", effort=1, impact=3,
                description=f'String "{val[:40]}" repeated {len(locs)} times.',
                suggestion="Extract into a named constant.",
            ))
    return items


def _detect_missing_docs(funcs: List[dict], lines: List[str], filepath: str) -> List[DebtItem]:
    """D009: Functions without preceding comments."""
    items = []
    for f in funcs:
        start = f["start"]
        has_doc = False
        # Check line before function def for comment
        if start > 0:
            prev = lines[start - 1].strip()
            if prev.startswith("#"):
                has_doc = True
        # Check first line of body for docstring-like comment
        if f["body_lines"]:
            first_body = f["body_lines"][0].strip()
            if first_body.startswith("#"):
                has_doc = True
        if not has_doc:
            items.append(DebtItem(
                id="D009", name="Missing Documentation",
                file=filepath, line=start + 1, severity="low", effort=1, impact=2,
                description=f"Function '{f['name']}' has no documentation.",
                suggestion="Add a comment describing what the function does.",
            ))
    return items


def _detect_complex_conditionals(lines: List[str], filepath: str) -> List[DebtItem]:
    """D010: If/elif chains with too many branches."""
    items = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("if ") or stripped.startswith("if("):
            indent = _indent_level(lines[i])
            branch_count = 1
            chain_start = i
            j = i + 1
            while j < len(lines):
                s = lines[j].strip()
                ind = _indent_level(lines[j])
                if ind == indent and (s.startswith("elif ") or s.startswith("elif(")):
                    branch_count += 1
                    j += 1
                elif ind == indent and s.startswith("else"):
                    branch_count += 1
                    j += 1
                    break
                elif ind <= indent and s and not s.startswith("#"):
                    break
                else:
                    j += 1
            if branch_count > MAX_ELIF_BRANCHES:
                items.append(DebtItem(
                    id="D010", name="Complex Conditional",
                    file=filepath, line=chain_start + 1, severity="medium",
                    effort=3, impact=5,
                    description=f"If/elif chain with {branch_count} branches (max recommended: {MAX_ELIF_BRANCHES}).",
                    suggestion="Consider using match/case, lookup table, or strategy pattern.",
                ))
            i = j
        else:
            i += 1
    return items


def _detect_inconsistent_style(funcs: List[dict], filepath: str) -> List[DebtItem]:
    """D011: Mixed naming conventions within a file."""
    items = []
    snake_names = []
    camel_names = []
    for f in funcs:
        name = f["name"]
        if "_" in name:
            snake_names.append(name)
        elif name != name.lower() and any(c.isupper() for c in name[1:]):
            camel_names.append(name)

    if snake_names and camel_names:
        items.append(DebtItem(
            id="D011", name="Inconsistent Style",
            file=filepath, line=1, severity="low", effort=2, impact=3,
            description=f"Mixed naming: snake_case ({len(snake_names)}) vs camelCase ({len(camel_names)}).",
            suggestion="Pick one naming convention and apply consistently.",
        ))
    return items


def _detect_coupling_hotspots(funcs: List[dict], lines: List[str], filepath: str) -> List[DebtItem]:
    """D012: Functions that call or are called by too many others."""
    items = []
    func_names = {f["name"] for f in funcs}
    # Build call graph
    calls_out: Dict[str, Set[str]] = defaultdict(set)
    calls_in: Dict[str, Set[str]] = defaultdict(set)

    for f in funcs:
        body_text = "\n".join(f["body_lines"])
        for m in CALL_RE.finditer(body_text):
            callee = m.group(1)
            if callee in func_names and callee != f["name"]:
                calls_out[f["name"]].add(callee)
                calls_in[callee].add(f["name"])

    for f in funcs:
        out_count = len(calls_out.get(f["name"], set()))
        in_count = len(calls_in.get(f["name"], set()))
        if out_count > MAX_CALLEES:
            items.append(DebtItem(
                id="D012", name="Coupling Hotspot",
                file=filepath, line=f["start"] + 1, severity="high",
                effort=4, impact=6,
                description=f"Function '{f['name']}' calls {out_count} other functions (max: {MAX_CALLEES}).",
                suggestion="Split into smaller orchestration functions.",
            ))
        if in_count > MAX_CALLERS:
            items.append(DebtItem(
                id="D012", name="Coupling Hotspot",
                file=filepath, line=f["start"] + 1, severity="medium",
                effort=3, impact=5,
                description=f"Function '{f['name']}' is called by {in_count} functions — high change risk.",
                suggestion="Consider adding an abstraction layer.",
            ))
    return items


# ── Scanner ───────────────────────────────────────────────────────────

def scan_file(filepath: str) -> List[DebtItem]:
    """Run all 12 detectors on a single .srv file."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except (IOError, OSError):
        return []

    lines = content.splitlines()
    funcs = _parse_functions(lines)
    items: List[DebtItem] = []

    items.extend(_detect_todo_markers(lines, filepath))
    items.extend(_detect_duplicated_blocks(funcs, filepath))
    items.extend(_detect_magic_numbers(lines, filepath, funcs))
    items.extend(_detect_missing_error_handling(funcs, filepath))
    items.extend(_detect_dead_code(funcs, lines, filepath))
    items.extend(_detect_long_functions(funcs, filepath))
    items.extend(_detect_deep_nesting(lines, filepath))
    items.extend(_detect_hardcoded_strings(lines, filepath))
    items.extend(_detect_missing_docs(funcs, lines, filepath))
    items.extend(_detect_complex_conditionals(lines, filepath))
    items.extend(_detect_inconsistent_style(funcs, filepath))
    items.extend(_detect_coupling_hotspots(funcs, lines, filepath))

    return items


def scan_project(paths: List[str], recursive: bool = False) -> ScanResult:
    """Scan one or more paths for .srv debt."""
    t0 = _time.time()
    files = _find_srv_files(paths, recursive=recursive)
    result = ScanResult()
    result.files_scanned = len(files)

    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                line_count = sum(1 for _ in fh)
            result.total_lines += line_count
        except (IOError, OSError):
            pass
        result.items.extend(scan_file(fp))

    result.scan_time = round(_time.time() - t0, 3)
    return result


# ── Payoff Plan ───────────────────────────────────────────────────────

def generate_payoff_plan(items: List[DebtItem]) -> Dict[str, List[DebtItem]]:
    """Group debt items into prioritised sprints by ROI."""
    sorted_items = sorted(items, key=lambda x: -x.roi_score)
    plan: Dict[str, List[DebtItem]] = {
        "quick_wins": [],
        "medium_effort": [],
        "deep_refactors": [],
    }
    for item in sorted_items:
        if item.effort <= 2:
            plan["quick_wins"].append(item)
        elif item.effort <= 3:
            plan["medium_effort"].append(item)
        else:
            plan["deep_refactors"].append(item)
    return plan


# ── Timeline / History ────────────────────────────────────────────────

def _load_history(history_file: str = HISTORY_FILE) -> List[dict]:
    if os.path.isfile(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, IOError):
            pass
    return []


def _save_history(entries: List[dict], history_file: str = HISTORY_FILE) -> None:
    with open(history_file, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2)


def record_snapshot(result: ScanResult, history_file: str = HISTORY_FILE) -> dict:
    """Record current scan as a timeline entry and return diff info."""
    history = _load_history(history_file)
    current_fps = [item.fingerprint for item in result.items]
    sev_counts = Counter(item.severity for item in result.items)

    entry = {
        "timestamp": datetime.now().isoformat(),
        "debt_count": len(result.items),
        "debt_score": result.debt_score,
        "fingerprints": current_fps,
        "severity_counts": dict(sev_counts),
    }

    # Compute diff with previous snapshot
    diff = {"new": [], "resolved": [], "velocity": 0}
    if history:
        prev_fps = set(history[-1].get("fingerprints", []))
        curr_fps = set(current_fps)
        diff["new"] = list(curr_fps - prev_fps)
        diff["resolved"] = list(prev_fps - curr_fps)
        if len(history) >= 2:
            recent_counts = [h["debt_count"] for h in history[-5:]] + [len(result.items)]
            if len(recent_counts) >= 2:
                diff["velocity"] = recent_counts[-1] - recent_counts[0]

    history.append(entry)
    _save_history(history, history_file)
    return diff


def get_timeline_summary(history_file: str = HISTORY_FILE) -> List[dict]:
    """Return timeline entries for display."""
    return _load_history(history_file)


def reset_history(history_file: str = HISTORY_FILE) -> None:
    if os.path.isfile(history_file):
        os.remove(history_file)


# ── Text Output ───────────────────────────────────────────────────────

def _severity_color(sev: str) -> str:
    colors = {"critical": "31", "high": "33", "medium": "36", "low": "2"}
    return colors.get(sev, "0")


def print_results(result: ScanResult, *, top: int = 0, severity: str = "",
                  show_plan: bool = False, show_new: bool = False,
                  show_resolved: bool = False, budget: int = 0,
                  diff: Optional[dict] = None) -> None:
    """Print scan results to terminal."""
    c = _C
    items = result.items

    if severity:
        items = [i for i in items if i.severity == severity]

    # Sort by ROI
    items = sorted(items, key=lambda x: -x.roi_score)

    if top > 0:
        items = items[:top]

    print()
    print(c.bold(f"  ╔══════════════════════════════════════════════════════╗"))
    print(c.bold(f"  ║         sauravdebt — Technical Debt Tracker         ║"))
    print(c.bold(f"  ╚══════════════════════════════════════════════════════╝"))
    print()

    score = result.debt_score
    score_color = "32" if score >= 80 else "33" if score >= 60 else "31"
    print(f"  Debt Score: \033[{score_color}m{score}/100\033[0m  │  "
          f"Items: {len(result.items)}  │  "
          f"Files: {result.files_scanned}  │  "
          f"Lines: {result.total_lines}  │  "
          f"Time: {result.scan_time}s")
    print()

    if budget > 0 and len(result.items) > budget:
        print(c.red(f"  ⚠ BUDGET EXCEEDED: {len(result.items)} items > {budget} budget"))
        print()

    if diff and show_new and diff.get("new"):
        new_items = [i for i in result.items if i.fingerprint in set(diff["new"])]
        if new_items:
            print(c.yellow(f"  ── New Debt ({len(new_items)} items) ──"))
            for item in new_items:
                print(f"    {c.red('+')} [{item.id}] {item.description}")
            print()

    if diff and show_resolved and diff.get("resolved"):
        print(c.green(f"  ── Resolved Debt ({len(diff['resolved'])} items) ──"))
        for fp in diff["resolved"]:
            print(f"    {c.green('✓')} {fp}")
        print()

    if show_plan:
        plan = generate_payoff_plan(items)
        for sprint_name, sprint_items in plan.items():
            if sprint_items:
                label = sprint_name.replace("_", " ").title()
                print(c.bold(f"  ── {label} ({len(sprint_items)} items) ──"))
                for item in sprint_items:
                    sev_badge = f"\033[{_severity_color(item.severity)}m{item.severity.upper()}\033[0m"
                    print(f"    ROI {item.roi_score:>5.1f} │ {sev_badge:>20s} │ "
                          f"[{item.id}] {item.description[:60]}")
                print()
    else:
        if items:
            print(c.bold("  ── Debt Items ──"))
            for item in items:
                sev_badge = f"\033[{_severity_color(item.severity)}m{item.severity.upper()}\033[0m"
                print(f"    ROI {item.roi_score:>5.1f} │ {sev_badge:>20s} │ "
                      f"[{item.id}] L{item.line} {item.file}")
                print(f"             │ {item.description[:70]}")
                print(f"             │ {c.dim(item.suggestion[:70])}")
                print()
        else:
            print(c.green("  ✨ No debt found — codebase is clean!"))
            print()

    # Severity summary
    sev_counts = Counter(i.severity for i in result.items)
    parts = []
    for sev in ("critical", "high", "medium", "low"):
        cnt = sev_counts.get(sev, 0)
        if cnt:
            parts.append(f"\033[{_severity_color(sev)}m{sev}: {cnt}\033[0m")
    if parts:
        print(f"  Summary: {' │ '.join(parts)}")
        print()


def print_timeline(history_file: str = HISTORY_FILE) -> None:
    """Print debt timeline to terminal."""
    c = _C
    history = _load_history(history_file)
    if not history:
        print(c.yellow("  No timeline data. Run a scan first."))
        return

    print(c.bold("\n  ── Debt Timeline ──\n"))
    print(f"  {'Date':<22} {'Score':>6} {'Items':>6}  Severity")
    print(f"  {'─'*22} {'─'*6} {'─'*6}  {'─'*30}")
    for entry in history[-20:]:
        ts = entry["timestamp"][:19].replace("T", " ")
        score = entry.get("debt_score", "?")
        count = entry.get("debt_count", "?")
        sevs = entry.get("severity_counts", {})
        sev_str = ", ".join(f"{k}:{v}" for k, v in sevs.items())
        print(f"  {ts:<22} {score:>6} {count:>6}  {sev_str}")

    if len(history) >= 2:
        first = history[0]["debt_count"]
        last = history[-1]["debt_count"]
        delta = last - first
        trend = "↑ increasing" if delta > 0 else "↓ decreasing" if delta < 0 else "→ stable"
        color = c.red if delta > 0 else c.green if delta < 0 else c.cyan
        print(f"\n  Trend: {color(trend)} ({delta:+d} items over {len(history)} snapshots)")
    print()


# ── HTML Dashboard ────────────────────────────────────────────────────

def generate_html(result: ScanResult, output_path: str,
                  history_file: str = HISTORY_FILE) -> None:
    """Generate an interactive single-file HTML dashboard."""
    items = sorted(result.items, key=lambda x: -x.roi_score)
    plan = generate_payoff_plan(result.items)
    history = _load_history(history_file)
    sev_counts = Counter(i.severity for i in result.items)
    score = result.debt_score

    # Severity colours
    sev_colors = {"critical": "#e74c3c", "high": "#e67e22", "medium": "#3498db", "low": "#95a5a6"}

    # Build timeline SVG
    timeline_svg = ""
    if len(history) >= 2:
        w, h = 600, 200
        entries = history[-20:]
        max_count = max(e["debt_count"] for e in entries) or 1
        step = w / max(len(entries) - 1, 1)
        points = []
        for idx, e in enumerate(entries):
            x = idx * step
            y = h - (e["debt_count"] / max_count) * (h - 20) - 10
            points.append(f"{x:.0f},{y:.0f}")
        polyline = " ".join(points)
        timeline_svg = f'''
        <svg viewBox="0 0 {w} {h}" style="width:100%;max-width:600px;background:#1a1a2e;border-radius:8px;padding:10px">
          <polyline points="{polyline}" fill="none" stroke="#3498db" stroke-width="2"/>
          {"".join(f'<circle cx="{p.split(",")[0]}" cy="{p.split(",")[1]}" r="3" fill="#3498db"/>' for p in points)}
          <text x="5" y="15" fill="#888" font-size="11">Debt Items Over Time</text>
        </svg>'''

    # Score gauge colour
    gauge_color = "#2ecc71" if score >= 80 else "#f39c12" if score >= 60 else "#e74c3c"

    items_html = ""
    for item in items:
        sc = sev_colors.get(item.severity, "#888")
        items_html += f'''
        <tr>
          <td><span style="background:{sc};color:#fff;padding:2px 8px;border-radius:4px;font-size:12px">{item.severity.upper()}</span></td>
          <td>{item.id}</td>
          <td>{item.roi_score:.1f}</td>
          <td>{item.file}:{item.line}</td>
          <td>{_html_escape(item.description[:80])}</td>
          <td style="color:#888">{_html_escape(item.suggestion[:60])}</td>
        </tr>'''

    plan_html = ""
    for sprint_name, sprint_items in plan.items():
        if sprint_items:
            label = sprint_name.replace("_", " ").title()
            plan_html += f'<h3 style="color:#ccc;margin-top:20px">{label} ({len(sprint_items)} items)</h3>'
            plan_html += '<div style="display:flex;flex-wrap:wrap;gap:8px">'
            for item in sprint_items:
                sc = sev_colors.get(item.severity, "#888")
                plan_html += f'''
                <div style="background:#1a1a2e;border-left:3px solid {sc};padding:8px 12px;border-radius:4px;flex:0 0 auto;max-width:400px">
                  <div style="font-weight:bold;font-size:13px">[{item.id}] ROI {item.roi_score:.1f}</div>
                  <div style="font-size:12px;color:#aaa">{_html_escape(item.description[:70])}</div>
                </div>'''
            plan_html += '</div>'

    html = f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>sauravdebt — Technical Debt Report</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{background:#0d1117;color:#e6e6e6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;padding:20px}}
  .header{{text-align:center;padding:30px 0}}
  .header h1{{font-size:28px;color:#58a6ff}}
  .gauge{{display:inline-block;width:120px;height:120px;border-radius:50%;border:8px solid {gauge_color};position:relative;margin:20px}}
  .gauge-val{{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);font-size:32px;font-weight:bold;color:{gauge_color}}}
  .stats{{display:flex;gap:20px;justify-content:center;flex-wrap:wrap;margin:20px 0}}
  .stat{{background:#161b22;padding:15px 25px;border-radius:8px;text-align:center}}
  .stat-val{{font-size:24px;font-weight:bold;color:#58a6ff}}
  .stat-label{{font-size:12px;color:#888;margin-top:4px}}
  .section{{margin:30px 0}}
  .section h2{{color:#58a6ff;margin-bottom:15px;font-size:20px}}
  table{{width:100%;border-collapse:collapse;background:#161b22;border-radius:8px;overflow:hidden}}
  th{{background:#1a1a2e;color:#888;text-align:left;padding:10px 12px;font-size:12px;cursor:pointer}}
  td{{padding:8px 12px;border-top:1px solid #21262d;font-size:13px}}
  tr:hover{{background:#1c2333}}
  .tabs{{display:flex;gap:0;margin-bottom:20px}}
  .tab{{padding:10px 20px;background:#161b22;color:#888;cursor:pointer;border:none;font-size:14px}}
  .tab.active{{color:#58a6ff;border-bottom:2px solid #58a6ff}}
  .panel{{display:none}} .panel.active{{display:block}}
  .timeline{{text-align:center;margin:20px 0}}
</style></head><body>
<div class="header">
  <h1>🔍 sauravdebt — Technical Debt Report</h1>
  <div class="gauge"><div class="gauge-val">{score}</div></div>
  <div style="color:#888;font-size:14px">Debt Health Score</div>
</div>
<div class="stats">
  <div class="stat"><div class="stat-val">{len(result.items)}</div><div class="stat-label">Debt Items</div></div>
  <div class="stat"><div class="stat-val">{result.files_scanned}</div><div class="stat-label">Files Scanned</div></div>
  <div class="stat"><div class="stat-val">{result.total_lines}</div><div class="stat-label">Total Lines</div></div>
  <div class="stat"><div class="stat-val">{result.scan_time}s</div><div class="stat-label">Scan Time</div></div>
  <div class="stat"><div class="stat-val">{sev_counts.get("critical",0)}</div><div class="stat-label" style="color:#e74c3c">Critical</div></div>
  <div class="stat"><div class="stat-val">{sev_counts.get("high",0)}</div><div class="stat-label" style="color:#e67e22">High</div></div>
  <div class="stat"><div class="stat-val">{sev_counts.get("medium",0)}</div><div class="stat-label" style="color:#3498db">Medium</div></div>
  <div class="stat"><div class="stat-val">{sev_counts.get("low",0)}</div><div class="stat-label" style="color:#95a5a6">Low</div></div>
</div>

<div class="tabs">
  <button class="tab active" onclick="showTab('items')">All Items</button>
  <button class="tab" onclick="showTab('plan')">Payoff Plan</button>
  <button class="tab" onclick="showTab('timeline')">Timeline</button>
</div>

<div id="items" class="panel active">
<div class="section">
  <h2>Debt Items (sorted by ROI)</h2>
  <table id="debtTable">
    <thead><tr>
      <th onclick="sortTable(0)">Severity</th>
      <th onclick="sortTable(1)">ID</th>
      <th onclick="sortTable(2)">ROI</th>
      <th onclick="sortTable(3)">Location</th>
      <th onclick="sortTable(4)">Description</th>
      <th>Suggestion</th>
    </tr></thead>
    <tbody>{items_html}</tbody>
  </table>
</div>
</div>

<div id="plan" class="panel">
<div class="section">
  <h2>Prioritised Payoff Plan</h2>
  {plan_html}
</div>
</div>

<div id="timeline" class="panel">
<div class="section">
  <h2>Debt Timeline</h2>
  <div class="timeline">{timeline_svg if timeline_svg else '<p style="color:#888">Run multiple scans to see trends.</p>'}</div>
</div>
</div>

<script>
function showTab(id) {{
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  event.target.classList.add('active');
}}
function sortTable(col) {{
  const table = document.getElementById('debtTable');
  const rows = Array.from(table.tBodies[0].rows);
  const asc = table.dataset.sortCol == col ? !(table.dataset.sortAsc === 'true') : true;
  table.dataset.sortCol = col;
  table.dataset.sortAsc = asc;
  rows.sort((a, b) => {{
    let va = a.cells[col].textContent.trim();
    let vb = b.cells[col].textContent.trim();
    let na = parseFloat(va), nb = parseFloat(vb);
    if (!isNaN(na) && !isNaN(nb)) return asc ? na - nb : nb - na;
    return asc ? va.localeCompare(vb) : vb.localeCompare(va);
  }});
  rows.forEach(r => table.tBodies[0].appendChild(r));
}}
</script>
<div style="text-align:center;color:#444;margin-top:40px;font-size:12px">
  Generated by sauravdebt v{__version__} • {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
</div>
</body></html>'''

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(html)


def _html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ── JSON Output ───────────────────────────────────────────────────────

def to_json(result: ScanResult) -> dict:
    """Convert scan results to JSON-serialisable dict."""
    return {
        "version": __version__,
        "timestamp": datetime.now().isoformat(),
        "debt_score": result.debt_score,
        "files_scanned": result.files_scanned,
        "total_lines": result.total_lines,
        "scan_time": result.scan_time,
        "total_items": len(result.items),
        "severity_counts": dict(Counter(i.severity for i in result.items)),
        "items": [
            {
                "id": i.id, "name": i.name, "file": i.file, "line": i.line,
                "severity": i.severity, "effort": i.effort, "impact": i.impact,
                "roi_score": i.roi_score, "description": i.description,
                "suggestion": i.suggestion, "fingerprint": i.fingerprint,
            }
            for i in sorted(result.items, key=lambda x: -x.roi_score)
        ],
    }


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="sauravdebt",
        description="Autonomous Technical Debt Tracker for sauravcode",
    )
    parser.add_argument("paths", nargs="*", default=["."],
                        help="Files or directories to scan")
    parser.add_argument("--recursive", "-r", action="store_true",
                        help="Scan subdirectories")
    parser.add_argument("--html", metavar="FILE",
                        help="Generate interactive HTML dashboard")
    parser.add_argument("--json", action="store_true",
                        help="JSON output")
    parser.add_argument("--plan", action="store_true",
                        help="Show prioritised payoff plan")
    parser.add_argument("--timeline", action="store_true",
                        help="Show debt trend over time")
    parser.add_argument("--new", action="store_true",
                        help="Show only new debt since last scan")
    parser.add_argument("--resolved", action="store_true",
                        help="Show recently resolved debt")
    parser.add_argument("--severity", choices=["critical", "high", "medium", "low"],
                        help="Filter by severity level")
    parser.add_argument("--top", type=int, default=0,
                        help="Show top N items by ROI")
    parser.add_argument("--budget", type=int, default=0,
                        help="Alert if total debt exceeds budget")
    parser.add_argument("--reset", action="store_true",
                        help="Clear timeline history")
    parser.add_argument("--version", action="version",
                        version=f"sauravdebt {__version__}")

    args = parser.parse_args()

    if args.reset:
        reset_history()
        print(_C.green("  ✓ Timeline history cleared."))
        return

    if args.timeline:
        print_timeline()
        return

    result = scan_project(args.paths, recursive=args.recursive)
    diff = record_snapshot(result)

    if args.json:
        print(json.dumps(to_json(result), indent=2))
        return

    if args.html:
        generate_html(result, args.html)
        print(_C.green(f"  ✓ HTML dashboard written to {args.html}"))
        return

    print_results(
        result, top=args.top, severity=args.severity or "",
        show_plan=args.plan, show_new=args.new,
        show_resolved=args.resolved, budget=args.budget,
        diff=diff,
    )


if __name__ == "__main__":
    main()
