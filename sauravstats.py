#!/usr/bin/env python3
"""sauravstats -- Codebase metrics analyzer for SauravCode (.srv) projects.

Scans .srv files and computes per-file and project-wide metrics:
lines of code, functions, classes, imports, comments, complexity
indicators, and more.

Usage:
    python sauravstats.py <path>                   # Analyze file or directory
    python sauravstats.py <path> --json            # JSON output
    python sauravstats.py <path> --csv             # CSV output
    python sauravstats.py <path> --sort loc        # Sort files by metric
    python sauravstats.py <path> --top 10          # Show top N files only
    python sauravstats.py <path> --hotspots        # Show complexity hotspots
    python sauravstats.py <path> --summary         # Project summary only
    python sauravstats.py <path> --treemap         # ASCII treemap of LOC
    python sauravstats.py <path> --history         # Compare with previous run
    python sauravstats.py <path> --badge           # Generate health badge text
"""

import os
import re
import sys
import json
import csv as _csv
import argparse
import io
from datetime import datetime

__version__ = "1.0.0"

_COMMENT_RE = re.compile(r'^\s*#')
_BLANK_RE = re.compile(r'^\s*$')
_FUNCTION_RE = re.compile(r'^\s*function\s+(\w+)\s*\(')
_CLASS_RE = re.compile(r'^\s*class\s+(\w+)')
_IMPORT_RE = re.compile(r'^\s*import\s+')
_ENUM_RE = re.compile(r'^\s*enum\s+(\w+)')
_LAMBDA_RE = re.compile(r'\blambda\b')
_TRY_RE = re.compile(r'^\s*try\s*:?\s*$')
_CATCH_RE = re.compile(r'^\s*catch\b')
_LOOP_RE = re.compile(r'^\s*(for|while)\b')
_IF_RE = re.compile(r'^\s*(if|else if)\b')
_MATCH_RE = re.compile(r'^\s*match\b')
_CASE_RE = re.compile(r'^\s*case\b')
_ASSERT_RE = re.compile(r'^\s*assert\b')
_YIELD_RE = re.compile(r'\byield\b')
_RETURN_RE = re.compile(r'^\s*return\b')
_THROW_RE = re.compile(r'^\s*throw\b')
_PRINT_RE = re.compile(r'^\s*print\s*\(')


class FileMetrics:
    __slots__ = (
        'path', 'rel_path', 'total_lines', 'code_lines', 'blank_lines',
        'comment_lines', 'functions', 'classes', 'enums', 'imports',
        'lambdas', 'loops', 'branches', 'match_cases', 'try_catches',
        'asserts', 'yields', 'returns', 'throws', 'prints',
        'max_depth', 'avg_depth', 'max_func_length', 'function_names',
        'class_names', 'enum_names', 'nested_functions', 'complexity_score',
    )

    def __init__(self, path, rel_path=None):
        self.path = path
        self.rel_path = rel_path or path
        for s in self.__slots__:
            if s in ('path', 'rel_path'):
                continue
            if s.endswith('_names'):
                setattr(self, s, [])
            elif s in ('avg_depth', 'complexity_score'):
                setattr(self, s, 0.0)
            else:
                setattr(self, s, 0)

    def to_dict(self):
        """Serialize all slot attributes into a plain dictionary."""
        return {s: getattr(self, s) for s in self.__slots__}

    @property
    def comment_ratio(self):
        """Ratio of comment lines to code lines (0.0–∞, higher = more comments)."""
        return self.comment_lines / max(self.code_lines, 1)

    @property
    def code_ratio(self):
        """Ratio of code lines to total lines (0.0–1.0, higher = less whitespace/comments)."""
        return self.code_lines / max(self.total_lines, 1)


def _indent_level(line):
    """Return the indentation level of *line* in spaces (tabs count as 4)."""
    count = 0
    for ch in line:
        if ch == ' ':
            count += 1
        elif ch == '\t':
            count += 4
        else:
            break
    return count


def analyze_file(filepath, base_dir=None):
    """Parse a single ``.srv`` file and return a populated :class:`FileMetrics`.

    Reads the file line-by-line, categorising each line (code, blank, comment)
    and detecting language constructs (functions, classes, imports, etc.).
    Complexity and nesting metrics are accumulated during the single pass.

    Args:
        filepath: Absolute or relative path to the ``.srv`` source file.
        base_dir: If given, ``FileMetrics.rel_path`` is set relative to this
            directory.  Otherwise the raw *filepath* is used.

    Returns:
        A :class:`FileMetrics` instance (never ``None``).  On read errors the
        counters will all be zero.
    """
    rel = os.path.relpath(filepath, base_dir) if base_dir else filepath
    fm = FileMetrics(filepath, rel)
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except (OSError, UnicodeDecodeError):
        return fm

    fm.total_lines = len(lines)
    depths = []
    func_start_line = None
    func_lengths = []

    for i, raw in enumerate(lines):
        line = raw.rstrip('\n\r')
        if _BLANK_RE.match(line):
            fm.blank_lines += 1
            continue
        if _COMMENT_RE.match(line):
            fm.comment_lines += 1
            continue

        fm.code_lines += 1
        depth = _indent_level(line)
        depths.append(depth)
        fm.max_depth = max(fm.max_depth, depth)

        m = _FUNCTION_RE.match(line)
        if m:
            fm.functions += 1
            fm.function_names.append(m.group(1))
            if depth > 0:
                fm.nested_functions += 1
            if func_start_line is not None:
                func_lengths.append(i - func_start_line)
            func_start_line = i

        m = _CLASS_RE.match(line)
        if m:
            fm.classes += 1
            fm.class_names.append(m.group(1))

        m = _ENUM_RE.match(line)
        if m:
            fm.enums += 1
            fm.enum_names.append(m.group(1))

        if _IMPORT_RE.match(line): fm.imports += 1
        if _LAMBDA_RE.search(line): fm.lambdas += 1
        if _LOOP_RE.match(line): fm.loops += 1
        if _IF_RE.match(line): fm.branches += 1
        if _MATCH_RE.match(line): fm.match_cases += 1
        if _CASE_RE.match(line): fm.match_cases += 1
        if _TRY_RE.match(line): fm.try_catches += 1
        if _CATCH_RE.match(line): fm.try_catches += 1
        if _ASSERT_RE.match(line): fm.asserts += 1
        if _YIELD_RE.search(line): fm.yields += 1
        if _RETURN_RE.match(line): fm.returns += 1
        if _THROW_RE.match(line): fm.throws += 1
        if _PRINT_RE.match(line): fm.prints += 1

    if func_start_line is not None:
        func_lengths.append(len(lines) - func_start_line)

    fm.max_func_length = max(func_lengths) if func_lengths else 0
    fm.avg_depth = sum(depths) / len(depths) if depths else 0.0
    fm.complexity_score = (
        fm.branches * 1.0 + fm.loops * 1.5 + fm.match_cases * 0.5 +
        fm.try_catches * 1.0 + fm.nested_functions * 2.0 +
        fm.lambdas * 0.5 + (fm.max_depth / 4.0) * 1.0
    )
    return fm


def find_srv_files(path):
    """Collect all ``.srv`` file paths under *path*.

    If *path* is a single file it is returned in a one-element list (provided
    it has the ``.srv`` extension).  Directories are walked recursively,
    skipping hidden directories (those starting with ``'.'``).
    """
    if os.path.isfile(path):
        return [path] if path.endswith('.srv') else []
    results = []
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for f in sorted(files):
            if f.endswith('.srv'):
                results.append(os.path.join(root, f))
    return results


def analyze_path(path):
    """Analyse all ``.srv`` files under *path* and return a list of :class:`FileMetrics`."""
    base = path if os.path.isdir(path) else os.path.dirname(path) or '.'
    return [analyze_file(f, base) for f in find_srv_files(path)]


class ProjectSummary:
    def __init__(self, file_metrics):
        self.file_count = len(file_metrics)
        self.total_lines = sum(f.total_lines for f in file_metrics)
        self.code_lines = sum(f.code_lines for f in file_metrics)
        self.blank_lines = sum(f.blank_lines for f in file_metrics)
        self.comment_lines = sum(f.comment_lines for f in file_metrics)
        self.functions = sum(f.functions for f in file_metrics)
        self.classes = sum(f.classes for f in file_metrics)
        self.enums = sum(f.enums for f in file_metrics)
        self.imports = sum(f.imports for f in file_metrics)
        self.lambdas = sum(f.lambdas for f in file_metrics)
        self.loops = sum(f.loops for f in file_metrics)
        self.branches = sum(f.branches for f in file_metrics)
        self.asserts = sum(f.asserts for f in file_metrics)
        self.yields = sum(f.yields for f in file_metrics)
        self.nested_functions = sum(f.nested_functions for f in file_metrics)
        self.avg_complexity = sum(f.complexity_score for f in file_metrics) / max(len(file_metrics), 1)
        self.max_complexity = max((f.complexity_score for f in file_metrics), default=0)
        self.max_depth = max((f.max_depth for f in file_metrics), default=0)
        self.avg_file_size = self.code_lines / max(self.file_count, 1)
        self.comment_ratio = self.comment_lines / max(self.code_lines, 1)
        self.max_func_length = max((f.max_func_length for f in file_metrics), default=0)
        self.health_score = self._compute_health()

    def _compute_health(self):
        """Compute a 0–100 health score from summary metrics.

        Deductions are applied for low comment ratios, excessively long
        functions, high complexity, and deep nesting.  Bonuses are given
        for the presence of assertions and small average file sizes.
        """
        s = 100.0
        if self.comment_ratio < 0.05: s -= 10
        elif self.comment_ratio < 0.1: s -= 5
        if self.max_func_length > 100: s -= 15
        elif self.max_func_length > 50: s -= 5
        if self.avg_complexity > 30: s -= 15
        elif self.avg_complexity > 15: s -= 5
        if self.max_depth > 20: s -= 10
        elif self.max_depth > 12: s -= 5
        if self.asserts > 0: s += 5
        if self.avg_file_size < 200: s += 5
        return max(0, min(100, s))

    def to_dict(self):
        """Return summary metrics as a plain dictionary (JSON-serialisable)."""
        return {k: getattr(self, k) for k in (
            'file_count', 'total_lines', 'code_lines', 'blank_lines',
            'comment_lines', 'functions', 'classes', 'enums', 'imports',
            'lambdas', 'loops', 'branches', 'asserts', 'yields',
            'nested_functions', 'avg_complexity', 'max_complexity',
            'max_depth', 'avg_file_size', 'comment_ratio',
            'max_func_length', 'health_score',
        )}

    @property
    def health_grade(self):
        """Map :attr:`health_score` to a letter grade (A–F)."""
        s = self.health_score
        if s >= 90: return 'A'
        if s >= 80: return 'B'
        if s >= 70: return 'C'
        if s >= 60: return 'D'
        return 'F'


def find_hotspots(metrics, threshold=None):
    """Return files whose complexity exceeds *threshold* (default: 1.5× average).

    Results are sorted by descending complexity score.
    """
    if threshold is None:
        avg = sum(f.complexity_score for f in metrics) / max(len(metrics), 1)
        threshold = max(avg * 1.5, 5.0)
    hotspots = [f for f in metrics if f.complexity_score >= threshold]
    hotspots.sort(key=lambda f: f.complexity_score, reverse=True)
    return hotspots


def render_treemap(metrics, width=60):
    """Render an ASCII bar chart showing relative LOC distribution across files."""
    if not metrics:
        return "No files found."
    sorted_m = sorted(metrics, key=lambda f: f.code_lines, reverse=True)
    max_loc = max(f.code_lines for f in sorted_m)
    if max_loc == 0:
        return "No code lines found."
    lines = ["LOC Distribution:", ""]
    max_name_len = max(len(f.rel_path) for f in sorted_m)
    bar_width = max(width - max_name_len - 10, 10)
    for f in sorted_m:
        if f.code_lines == 0:
            continue
        bar_len = max(int((f.code_lines / max_loc) * bar_width), 1)
        lines.append(f"  {f.rel_path.ljust(max_name_len)}  {'#' * bar_len} {f.code_lines}")
    return '\n'.join(lines)


_HISTORY_FILE = '.sauravstats.json'


def save_snapshot(summary, path):
    """Persist the current :class:`ProjectSummary` to ``.sauravstats.json`` for later comparison."""
    hist_path = os.path.join(path if os.path.isdir(path) else os.path.dirname(path) or '.', _HISTORY_FILE)
    data = summary.to_dict()
    data['timestamp'] = datetime.now().isoformat()
    try:
        with open(hist_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


def load_previous(path):
    """Load a previously saved snapshot from ``.sauravstats.json``, or ``None``."""
    hist_path = os.path.join(path if os.path.isdir(path) else os.path.dirname(path) or '.', _HISTORY_FILE)
    try:
        with open(hist_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def compare_snapshots(current, previous):
    """Diff two snapshot dicts and return a dict of changed metrics, or ``None``."""
    if not previous:
        return None
    diffs = {}
    for k in ('file_count', 'total_lines', 'code_lines', 'functions', 'classes', 'avg_complexity', 'health_score'):
        cur_v, prev_v = current.get(k, 0), previous.get(k, 0)
        if cur_v != prev_v:
            delta = round(cur_v - prev_v, 2) if isinstance(cur_v - prev_v, float) else cur_v - prev_v
            diffs[k] = {'previous': prev_v, 'current': cur_v, 'delta': delta}
    return diffs if diffs else None


def generate_badge(summary):
    """Return a short string suitable for a README badge (e.g. ``Health: A (95/100)``)."""
    return f"SauravCode Health: {summary.health_grade} ({int(summary.health_score)}/100)"


SORT_KEYS = {
    'loc': lambda f: f.code_lines, 'total': lambda f: f.total_lines,
    'functions': lambda f: f.functions, 'complexity': lambda f: f.complexity_score,
    'depth': lambda f: f.max_depth, 'comments': lambda f: f.comment_lines,
    'name': lambda f: f.rel_path, 'classes': lambda f: f.classes,
}


def _delta_str(val):
    """Format a numeric delta with a ``+`` prefix for positive values."""
    return f"+{val}" if val > 0 else str(val)


def format_text(metrics, summary, args):
    """Render a human-readable table of per-file metrics plus a project summary."""
    out = []
    if not args.summary:
        sort_fn = SORT_KEYS.get(args.sort, SORT_KEYS['loc'])
        sorted_m = sorted(metrics, key=sort_fn, reverse=(args.sort != 'name'))
        if args.top and args.top < len(sorted_m):
            sorted_m = sorted_m[:args.top]
        out.append(f"{'File':<40} {'LOC':>6} {'Func':>5} {'Cls':>4} {'Cplx':>6} {'Dep':>4} {'Cmt%':>5}")
        out.append('-' * 72)
        for f in sorted_m:
            out.append(f"{f.rel_path:<40} {f.code_lines:>6} {f.functions:>5} "
                       f"{f.classes:>4} {f.complexity_score:>6.1f} {f.max_depth:>4} {f.comment_ratio*100:>4.0f}%")
        out.append('-' * 72)
        out.append('')
    out.append("Project Summary")
    out.append('-' * 40)
    for label, val in [
        ("Files", summary.file_count), ("Total lines", summary.total_lines),
        ("Code lines", summary.code_lines), ("Blank lines", summary.blank_lines),
        ("Comment lines", summary.comment_lines),
    ]:
        out.append(f"  {label+':':<20}{val}")
    out.append(f"  {'Comment ratio:':<20}{summary.comment_ratio*100:.1f}%")
    for label, val in [
        ("Functions", summary.functions), ("Classes", summary.classes),
        ("Enums", summary.enums), ("Imports", summary.imports),
        ("Lambdas", summary.lambdas), ("Loops", summary.loops),
        ("Branches", summary.branches), ("Asserts", summary.asserts),
        ("Generators", summary.yields), ("Nested funcs", summary.nested_functions),
    ]:
        out.append(f"  {label+':':<20}{val}")
    out.append(f"  {'Avg complexity:':<20}{summary.avg_complexity:.1f}")
    out.append(f"  {'Max complexity:':<20}{summary.max_complexity:.1f}")
    out.append(f"  {'Max nesting:':<20}{summary.max_depth} spaces")
    out.append(f"  {'Avg file size:':<20}{summary.avg_file_size:.0f} LOC")
    out.append(f"  {'Longest function:':<20}{summary.max_func_length} lines")
    out.append(f"  {'Health score:':<20}{summary.health_score:.0f}/100 ({summary.health_grade})")
    return '\n'.join(out)


def format_json(metrics, summary, args):
    """Render metrics as a pretty-printed JSON string."""
    data = {'summary': summary.to_dict(), 'summary_grade': summary.health_grade}
    if not args.summary:
        data['files'] = [f.to_dict() for f in metrics]
    return json.dumps(data, indent=2, default=str)


def format_csv(metrics, summary, args):
    """Render per-file metrics as a CSV string (including header row)."""
    buf = io.StringIO()
    w = _csv.writer(buf)
    w.writerow(['file','total_lines','code_lines','blank_lines','comment_lines',
                'functions','classes','enums','imports','loops','branches',
                'complexity','max_depth','comment_ratio'])
    for f in metrics:
        w.writerow([f.rel_path, f.total_lines, f.code_lines, f.blank_lines,
                     f.comment_lines, f.functions, f.classes, f.enums, f.imports,
                     f.loops, f.branches, f'{f.complexity_score:.1f}', f.max_depth,
                     f'{f.comment_ratio:.2f}'])
    return buf.getvalue()


def format_hotspots(metrics, summary, args):
    """Render a report of complexity hotspot files with per-file explanations."""
    hotspots = find_hotspots(metrics)
    if not hotspots:
        return "No complexity hotspots found. Your code is clean!"
    out = ["Complexity Hotspots", '-' * 50]
    for f in hotspots:
        reasons = []
        if f.branches > 5: reasons.append(f"{f.branches} branches")
        if f.loops > 3: reasons.append(f"{f.loops} loops")
        if f.nested_functions > 0: reasons.append(f"{f.nested_functions} nested funcs")
        if f.max_depth > 12: reasons.append(f"depth {f.max_depth}")
        if f.max_func_length > 50: reasons.append(f"func {f.max_func_length}L")
        reason_str = ', '.join(reasons) if reasons else 'high combined score'
        out.append(f"  ! {f.rel_path:<35} complexity={f.complexity_score:.1f}  ({reason_str})")
    return '\n'.join(out)


def format_history(metrics, summary, args, path):
    """Compare current metrics against the previous snapshot and render a diff report.

    A new snapshot is saved after the comparison so the next invocation
    can diff against this run.
    """
    previous = load_previous(path)
    current = summary.to_dict()
    save_snapshot(summary, path)
    if not previous:
        return "No previous snapshot found. Current metrics saved for next comparison."
    diffs = compare_snapshots(current, previous)
    ts = previous.get('timestamp', 'unknown')
    out = [f"Changes since {ts}:", '-' * 40]
    if not diffs:
        out.append("  No changes detected.")
    else:
        for k, v in diffs.items():
            out.append(f"  {k.replace('_',' ').title():<25} {v['previous']} -> {v['current']}  ({_delta_str(v['delta'])})")
    return '\n'.join(out)


def build_parser():
    """Build and return the :mod:`argparse` parser for the CLI."""
    p = argparse.ArgumentParser(prog='sauravstats',
        description='Codebase metrics analyzer for SauravCode (.srv) projects.')
    p.add_argument('path', help='File or directory to analyze')
    p.add_argument('--json', action='store_true', help='JSON output')
    p.add_argument('--csv', action='store_true', help='CSV output')
    p.add_argument('--sort', choices=list(SORT_KEYS), default='loc', help='Sort by metric')
    p.add_argument('--top', type=int, metavar='N', help='Show only top N files')
    p.add_argument('--hotspots', action='store_true', help='Show complexity hotspots')
    p.add_argument('--summary', action='store_true', help='Project summary only')
    p.add_argument('--treemap', action='store_true', help='ASCII LOC distribution')
    p.add_argument('--history', action='store_true', help='Compare with previous run')
    p.add_argument('--badge', action='store_true', help='Generate health badge text')
    p.add_argument('--version', action='version', version=f'sauravstats {__version__}')
    return p


def main(argv=None):
    """CLI entry point.  Parse arguments, analyse, and print the chosen format.

    Returns 0 on success, 1 on error.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if not os.path.exists(args.path):
        print(f"Error: '{args.path}' not found.", file=sys.stderr)
        return 1
    metrics = analyze_path(args.path)
    if not metrics:
        print(f"No .srv files found in '{args.path}'.", file=sys.stderr)
        return 1
    summary = ProjectSummary(metrics)
    if args.badge:
        print(generate_badge(summary)); return 0
    if args.treemap:
        print(render_treemap(metrics)); return 0
    if args.history:
        print(format_history(metrics, summary, args, args.path)); return 0
    if args.hotspots:
        print(format_hotspots(metrics, summary, args)); return 0
    if args.json:
        print(format_json(metrics, summary, args))
    elif args.csv:
        print(format_csv(metrics, summary, args))
    else:
        print(format_text(metrics, summary, args))
    return 0


if __name__ == '__main__':
    sys.exit(main())
