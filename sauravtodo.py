#!/usr/bin/env python3
"""sauravtodo — TODO/FIXME comment tracker for sauravcode (.srv) projects.

Scans .srv source files for tagged comments (TODO, FIXME, HACK, NOTE, XXX,
OPTIMIZE, REVIEW, DEPRECATED) and produces structured reports with filtering,
sorting, and multiple output formats.

Usage:
    python sauravtodo.py file.srv [file2.srv ...]
    python sauravtodo.py src/                        # scan directory recursively
    python sauravtodo.py --tag TODO,FIXME src/       # filter by tag
    python sauravtodo.py --priority high src/        # filter by priority
    python sauravtodo.py --author alice src/          # filter by author
    python sauravtodo.py --json src/                  # JSON output
    python sauravtodo.py --csv src/                   # CSV output
    python sauravtodo.py --summary src/               # summary stats only
    python sauravtodo.py --sort priority src/         # sort by priority
    python sauravtodo.py --sort file src/             # sort by file
    python sauravtodo.py --sort tag src/              # sort by tag
    python sauravtodo.py --group tag src/             # group by tag
    python sauravtodo.py --group file src/            # group by file
    python sauravtodo.py --group priority src/        # group by priority
    python sauravtodo.py --check src/                 # exit 1 if any found
    python sauravtodo.py --check --tag FIXME src/     # exit 1 if FIXMEs found
    python sauravtodo.py --stats src/                 # detailed statistics
    python sauravtodo.py --blame src/                 # show git blame info
    python sauravtodo.py --age src/                   # show age from git log
"""

import argparse
import csv
import glob
import io
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Dict, Optional, Set, Tuple

__version__ = "1.0.0"

# ─── Tag definitions ──────────────────────────────────────────────

KNOWN_TAGS = {
    "TODO":       {"priority": "medium", "description": "Work to be done"},
    "FIXME":      {"priority": "high",   "description": "Known bug or broken code"},
    "HACK":       {"priority": "medium", "description": "Workaround, needs proper fix"},
    "NOTE":       {"priority": "low",    "description": "Important note for developers"},
    "XXX":        {"priority": "high",   "description": "Dangerous or fragile code"},
    "OPTIMIZE":   {"priority": "low",    "description": "Performance improvement opportunity"},
    "REVIEW":     {"priority": "medium", "description": "Needs code review or discussion"},
    "DEPRECATED": {"priority": "medium", "description": "Scheduled for removal"},
}

PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

# ─── Data model ───────────────────────────────────────────────────

@dataclass
class TodoItem:
    """A single tagged comment found in source code."""
    file: str
    line: int
    tag: str
    text: str
    priority: str = "medium"
    author: Optional[str] = None
    source_line: str = ""
    # Git blame fields (populated when --blame or --age is used)
    blame_author: Optional[str] = None
    blame_date: Optional[str] = None

    def to_dict(self) -> dict:
        d = {
            "file": self.file,
            "line": self.line,
            "tag": self.tag,
            "text": self.text,
            "priority": self.priority,
        }
        if self.author:
            d["author"] = self.author
        if self.blame_author:
            d["blame_author"] = self.blame_author
        if self.blame_date:
            d["blame_date"] = self.blame_date
        return d


# ─── Tag pattern ──────────────────────────────────────────────────

# Matches: # TODO: do something
#          # TODO(alice): do something
#          # FIXME do something
#          // TODO: do something  (for any future syntax variants)
TAG_NAMES = "|".join(KNOWN_TAGS.keys())
TAG_PATTERN = re.compile(
    rf'#\s*\b({TAG_NAMES})\b'       # comment hash + tag
    rf'(?:\(([^)]*)\))?'            # optional (author)
    rf'[\s:—-]*'                    # separator (colon, dash, space)
    rf'(.+?)$',                     # description text
    re.IGNORECASE
)


# ─── Scanner ──────────────────────────────────────────────────────

def scan_file(filepath: str) -> List[TodoItem]:
    """Scan a single .srv file for tagged comments."""
    items = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except (OSError, IOError):
        return items

    for i, line in enumerate(lines, 1):
        m = TAG_PATTERN.search(line)
        if m:
            tag = m.group(1).upper()
            author = m.group(2).strip() if m.group(2) else None
            text = m.group(3).strip()
            priority = KNOWN_TAGS.get(tag, {}).get("priority", "medium")
            items.append(TodoItem(
                file=filepath,
                line=i,
                tag=tag,
                text=text,
                priority=priority,
                author=author,
                source_line=line.rstrip(),
            ))
    return items


def scan_paths(paths: List[str], recursive: bool = True) -> List[TodoItem]:
    """Scan files/directories for tagged comments."""
    all_items = []
    files_seen: Set[str] = set()

    for path in paths:
        if os.path.isfile(path):
            norm = os.path.normpath(path)
            if norm not in files_seen:
                files_seen.add(norm)
                all_items.extend(scan_file(path))
        elif os.path.isdir(path):
            pattern = os.path.join(path, "**", "*.srv") if recursive else os.path.join(path, "*.srv")
            for fp in glob.glob(pattern, recursive=recursive):
                norm = os.path.normpath(fp)
                if norm not in files_seen:
                    files_seen.add(norm)
                    all_items.extend(scan_file(fp))
    return all_items


# ─── Git integration ─────────────────────────────────────────────

def git_blame_line(filepath: str, line_no: int) -> Tuple[Optional[str], Optional[str]]:
    """Get git blame info for a specific line."""
    try:
        result = subprocess.run(
            ["git", "blame", "-L", f"{line_no},{line_no}", "--porcelain", filepath],
            capture_output=True, text=True, timeout=10, cwd=os.path.dirname(filepath) or "."
        )
        if result.returncode != 0:
            return None, None
        author = None
        date = None
        for bl in result.stdout.splitlines():
            if bl.startswith("author "):
                author = bl[7:]
            elif bl.startswith("author-time "):
                ts = int(bl[12:])
                date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        return author, date
    except (subprocess.SubprocessError, OSError, ValueError):
        return None, None


def enrich_blame(items: List[TodoItem]) -> None:
    """Add git blame info to all items."""
    for item in items:
        author, date = git_blame_line(item.file, item.line)
        item.blame_author = author
        item.blame_date = date


# ─── Filtering & sorting ─────────────────────────────────────────

def filter_items(items: List[TodoItem], tags: Optional[Set[str]] = None,
                 priority: Optional[str] = None, author: Optional[str] = None) -> List[TodoItem]:
    """Filter items by tag, priority, or author."""
    result = items
    if tags:
        tags_upper = {t.upper() for t in tags}
        result = [i for i in result if i.tag in tags_upper]
    if priority:
        result = [i for i in result if i.priority == priority.lower()]
    if author:
        author_lower = author.lower()
        result = [i for i in result if
                  (i.author and i.author.lower() == author_lower) or
                  (i.blame_author and i.blame_author.lower() == author_lower)]
    return result


def sort_items(items: List[TodoItem], key: str = "file") -> List[TodoItem]:
    """Sort items by the given key."""
    if key == "priority":
        return sorted(items, key=lambda i: (PRIORITY_ORDER.get(i.priority, 9), i.file, i.line))
    elif key == "tag":
        return sorted(items, key=lambda i: (i.tag, i.file, i.line))
    elif key == "line":
        return sorted(items, key=lambda i: (i.file, i.line))
    elif key == "date" and any(i.blame_date for i in items):
        return sorted(items, key=lambda i: (i.blame_date or "9999", i.file, i.line))
    else:  # default: file
        return sorted(items, key=lambda i: (i.file, i.line))


def group_items(items: List[TodoItem], key: str) -> Dict[str, List[TodoItem]]:
    """Group items by the given key."""
    groups: Dict[str, List[TodoItem]] = defaultdict(list)
    for item in items:
        if key == "tag":
            groups[item.tag].append(item)
        elif key == "file":
            groups[item.file].append(item)
        elif key == "priority":
            groups[item.priority].append(item)
        elif key == "author":
            a = item.author or item.blame_author or "(unknown)"
            groups[a].append(item)
    return dict(groups)


# ─── Output formatters ───────────────────────────────────────────

TAG_COLORS = {
    "TODO":       "\033[33m",       # yellow
    "FIXME":      "\033[31m",       # red
    "HACK":       "\033[35m",       # magenta
    "NOTE":       "\033[36m",       # cyan
    "XXX":        "\033[31;1m",     # bold red
    "OPTIMIZE":   "\033[32m",       # green
    "REVIEW":     "\033[34m",       # blue
    "DEPRECATED": "\033[90m",       # gray
}
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

PRIORITY_SYMBOLS = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}


def format_text(items: List[TodoItem], grouped: Optional[Dict[str, List[TodoItem]]] = None,
                color: bool = True) -> str:
    """Format items as colored terminal text."""
    lines = []
    if grouped:
        for group_name, group_items in sorted(grouped.items()):
            lines.append("")
            if color:
                lines.append(f"{BOLD}── {group_name} ({len(group_items)}) ──{RESET}")
            else:
                lines.append(f"── {group_name} ({len(group_items)}) ──")
            for item in group_items:
                lines.append(_format_item_line(item, color))
    else:
        for item in items:
            lines.append(_format_item_line(item, color))

    return "\n".join(lines)


def _format_item_line(item: TodoItem, color: bool) -> str:
    """Format a single item as a text line."""
    tag_c = TAG_COLORS.get(item.tag, "") if color else ""
    rst = RESET if color else ""
    dim = DIM if color else ""
    sym = PRIORITY_SYMBOLS.get(item.priority, "  ")

    loc = f"{item.file}:{item.line}"
    author_str = f" ({item.author})" if item.author else ""
    blame_str = ""
    if item.blame_author or item.blame_date:
        parts = []
        if item.blame_date:
            parts.append(item.blame_date)
        if item.blame_author:
            parts.append(item.blame_author)
        blame_str = f" {dim}[{', '.join(parts)}]{rst}" if color else f" [{', '.join(parts)}]"

    return f"  {sym} {tag_c}{item.tag}{rst}{author_str}: {item.text}  {dim}{loc}{rst}{blame_str}"


def format_json(items: List[TodoItem]) -> str:
    """Format items as JSON."""
    return json.dumps([i.to_dict() for i in items], indent=2)


def format_csv(items: List[TodoItem]) -> str:
    """Format items as CSV."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["file", "line", "tag", "priority", "text", "author", "blame_author", "blame_date"])
    for item in items:
        writer.writerow([
            item.file, item.line, item.tag, item.priority, item.text,
            item.author or "", item.blame_author or "", item.blame_date or ""
        ])
    return out.getvalue()


def format_summary(items: List[TodoItem], files_scanned: int) -> str:
    """Format a summary of findings."""
    lines = []
    lines.append(f"  Files scanned: {files_scanned}")
    lines.append(f"  Total items:   {len(items)}")
    lines.append("")

    by_tag = Counter(i.tag for i in items)
    if by_tag:
        lines.append("  By tag:")
        for tag in sorted(by_tag, key=lambda t: -by_tag[t]):
            desc = KNOWN_TAGS.get(tag, {}).get("description", "")
            lines.append(f"    {tag:12s} {by_tag[tag]:4d}  {desc}")

    by_priority = Counter(i.priority for i in items)
    if by_priority:
        lines.append("")
        lines.append("  By priority:")
        for p in ["critical", "high", "medium", "low"]:
            if p in by_priority:
                sym = PRIORITY_SYMBOLS.get(p, "  ")
                lines.append(f"    {sym} {p:10s} {by_priority[p]:4d}")

    by_file = Counter(i.file for i in items)
    if by_file:
        lines.append("")
        lines.append("  Top files:")
        for f, count in by_file.most_common(10):
            lines.append(f"    {count:4d}  {f}")

    return "\n".join(lines)


def format_stats(items: List[TodoItem], files_scanned: int) -> str:
    """Format detailed statistics."""
    lines = [format_summary(items, files_scanned)]

    # Author breakdown
    authors = Counter()
    for item in items:
        a = item.author or item.blame_author or "(unknown)"
        authors[a] += 1
    if authors and not all(a == "(unknown)" for a in authors):
        lines.append("")
        lines.append("  By author:")
        for author, count in authors.most_common():
            if author != "(unknown)":
                lines.append(f"    {count:4d}  {author}")

    # Age breakdown
    dated = [i for i in items if i.blame_date]
    if dated:
        lines.append("")
        lines.append("  Age distribution:")
        now = datetime.now(tz=timezone.utc)
        age_buckets = {"< 1 week": 0, "1-4 weeks": 0, "1-3 months": 0, "3-6 months": 0, "> 6 months": 0}
        for item in dated:
            try:
                d = datetime.strptime(item.blame_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                days = (now - d).days
                if days < 7:
                    age_buckets["< 1 week"] += 1
                elif days < 28:
                    age_buckets["1-4 weeks"] += 1
                elif days < 90:
                    age_buckets["1-3 months"] += 1
                elif days < 180:
                    age_buckets["3-6 months"] += 1
                else:
                    age_buckets["> 6 months"] += 1
            except ValueError:
                pass
        for bucket, count in age_buckets.items():
            if count:
                lines.append(f"    {count:4d}  {bucket}")

    return "\n".join(lines)


# ─── CLI ──────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sauravtodo",
        description="Track TODO/FIXME/HACK/NOTE comments in sauravcode (.srv) files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Tags tracked:
  TODO       Work to be done (medium priority)
  FIXME      Known bug or broken code (high priority)
  HACK       Workaround, needs proper fix (medium priority)
  NOTE       Important note for developers (low priority)
  XXX        Dangerous or fragile code (high priority)
  OPTIMIZE   Performance improvement opportunity (low priority)
  REVIEW     Needs code review or discussion (medium priority)
  DEPRECATED Scheduled for removal (medium priority)

Examples:
  sauravtodo src/                        Scan all .srv files in src/
  sauravtodo --tag FIXME,TODO src/       Show only FIXMEs and TODOs
  sauravtodo --priority high .           Show high-priority items
  sauravtodo --json --sort priority .    JSON output sorted by priority
  sauravtodo --group tag .               Group results by tag type
  sauravtodo --blame --age src/          Show git blame and age info
  sauravtodo --check --tag FIXME src/    Exit 1 if any FIXMEs found
"""
    )
    p.add_argument("paths", nargs="+", help="Files or directories to scan")
    p.add_argument("--version", action="version", version=f"sauravtodo {__version__}")

    fmt = p.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true", help="Output as JSON")
    fmt.add_argument("--csv", action="store_true", help="Output as CSV")
    fmt.add_argument("--summary", action="store_true", help="Summary stats only")
    fmt.add_argument("--stats", action="store_true", help="Detailed statistics")

    p.add_argument("--tag", type=str, default=None,
                   help="Filter by tag (comma-separated, e.g. TODO,FIXME)")
    p.add_argument("--priority", type=str, choices=["critical", "high", "medium", "low"],
                   help="Filter by priority level")
    p.add_argument("--author", type=str, default=None,
                   help="Filter by author name")
    p.add_argument("--sort", type=str, choices=["file", "priority", "tag", "line", "date"],
                   default="file", help="Sort order (default: file)")
    p.add_argument("--group", type=str, choices=["tag", "file", "priority", "author"],
                   default=None, help="Group results by field")
    p.add_argument("--check", action="store_true",
                   help="Exit with code 1 if any items found (CI mode)")
    p.add_argument("--blame", action="store_true",
                   help="Include git blame info (author, date)")
    p.add_argument("--age", action="store_true",
                   help="Include commit age info from git")
    p.add_argument("--no-color", action="store_true",
                   help="Disable colored output")
    p.add_argument("--no-recursive", action="store_true",
                   help="Don't recurse into subdirectories")
    return p


def count_srv_files(paths: List[str], recursive: bool = True) -> int:
    """Count .srv files in the given paths."""
    files: Set[str] = set()
    for path in paths:
        if os.path.isfile(path) and path.endswith(".srv"):
            files.add(os.path.normpath(path))
        elif os.path.isdir(path):
            pattern = os.path.join(path, "**", "*.srv") if recursive else os.path.join(path, "*.srv")
            for fp in glob.glob(pattern, recursive=recursive):
                files.add(os.path.normpath(fp))
    return len(files)


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    recursive = not args.no_recursive
    use_color = not args.no_color and sys.stdout.isatty() and not args.json and not args.csv

    # Scan
    items = scan_paths(args.paths, recursive=recursive)
    files_scanned = count_srv_files(args.paths, recursive=recursive)

    # Git enrichment
    if args.blame or args.age:
        enrich_blame(items)

    # Filter
    tags = set(args.tag.upper().split(",")) if args.tag else None
    items = filter_items(items, tags=tags, priority=args.priority, author=args.author)

    # Sort
    items = sort_items(items, key=args.sort)

    # Output
    if args.json:
        print(format_json(items))
    elif args.csv:
        print(format_csv(items), end="")
    elif args.stats:
        header = f"\n  sauravtodo v{__version__} — Comment Tracker\n"
        print(header)
        print(format_stats(items, files_scanned))
        print()
    elif args.summary:
        header = f"\n  sauravtodo v{__version__} — Comment Tracker\n"
        print(header)
        print(format_summary(items, files_scanned))
        print()
    else:
        # Full listing
        header = f"\n  sauravtodo v{__version__} — Comment Tracker"
        if use_color:
            print(f"{BOLD}{header}{RESET}\n")
        else:
            print(f"{header}\n")

        if not items:
            print("  No tagged comments found. ✨")
        else:
            grouped = group_items(items, args.group) if args.group else None
            print(format_text(items, grouped=grouped, color=use_color))

        print()
        print(format_summary(items, files_scanned))
        print()

    # Check mode
    if args.check and items:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
