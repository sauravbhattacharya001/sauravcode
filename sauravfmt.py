#!/usr/bin/env python3
"""
sauravfmt — Code formatter for the sauravcode language.

Normalises indentation (spaces vs tabs, consistent width), trailing
whitespace, blank-line runs, operator spacing, and alignment.

Usage:
    python sauravfmt.py FILE.srv              # show diff (dry-run)
    python sauravfmt.py FILE.srv --write      # overwrite in-place
    python sauravfmt.py FILE.srv --check      # exit 1 if changes needed (CI)
    python sauravfmt.py src/                  # format all .srv files in dir
    python sauravfmt.py FILE.srv --indent 2   # use 2-space indent (default 4)
    python sauravfmt.py FILE.srv --diff       # show unified diff
"""

import argparse
import os
import re
import sys

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_INDENT = 4
MAX_CONSECUTIVE_BLANKS = 2      # collapse runs of blank lines to at most this
TRAILING_NEWLINE = True         # ensure file ends with exactly one newline

# Keywords that open a new indented block on the next line
BLOCK_OPENERS = {
    "function", "if", "else", "else if", "while", "for", "try",
    "catch", "match", "case", "enum", "class", "lambda",
}

# Binary operators that should have single spaces around them
SPACED_OPS = {"==", "!=", "<=", ">=", "=", "+", "-", "*", "/", "%", "|>",
              "and", "or", "->"}

# ---------------------------------------------------------------------------
# Core formatting
# ---------------------------------------------------------------------------

def _detect_indent(lines):
    """Detect the most common indentation unit in the file."""
    counts = {}
    for line in lines:
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        leading = len(line) - len(stripped)
        if leading > 0:
            counts[leading] = counts.get(leading, 0) + 1
    if not counts:
        return DEFAULT_INDENT
    # Find the GCD of all indentation widths — that's the indent unit
    from math import gcd
    from functools import reduce
    return reduce(gcd, counts.keys())


def _normalise_indent(line, old_indent, new_indent):
    """Convert leading whitespace to use new_indent spaces per level."""
    if not line or not line[0] in (" ", "\t"):
        return line
    # Count leading spaces (tabs -> old_indent spaces)
    expanded = ""
    for ch in line:
        if ch == "\t":
            expanded += " " * old_indent
        elif ch == " ":
            expanded += " "
        else:
            break
    leading = len(expanded)
    rest = line.lstrip()
    if old_indent == 0:
        return line  # can't determine levels
    level = leading // old_indent
    remainder = leading % old_indent
    return (" " * (level * new_indent + remainder)) + rest


def _fix_operator_spacing(line):
    """Ensure single spaces around binary operators, preserving strings/comments."""
    # Don't touch comment lines
    stripped = line.lstrip()
    if stripped.startswith("#"):
        return line

    leading = line[:len(line) - len(stripped)]
    result = []
    i = 0
    in_string = False
    string_char = None

    while i < len(stripped):
        ch = stripped[i]

        # Handle string boundaries
        if ch == '"' and not in_string:
            in_string = True
            string_char = ch
            result.append(ch)
            i += 1
            continue
        if in_string:
            result.append(ch)
            if ch == '\\' and i + 1 < len(stripped):
                result.append(stripped[i + 1])
                i += 2
                continue
            if ch == string_char:
                in_string = False
            i += 1
            continue

        # Handle f-strings
        if ch == 'f' and i + 1 < len(stripped) and stripped[i + 1] == '"':
            in_string = True
            string_char = '"'
            result.append(ch)
            result.append(stripped[i + 1])
            i += 2
            continue

        # Handle comment — stop processing
        if ch == '#':
            result.append(stripped[i:])
            break

        # Check for two-char operators first
        two = stripped[i:i+2]
        if two in ("==", "!=", "<=", ">=", "|>", "->"):
            # Ensure space before
            if result and result[-1] != " ":
                result.append(" ")
            result.append(two)
            i += 2
            # Ensure space after
            if i < len(stripped) and stripped[i] != " ":
                result.append(" ")
            continue

        # Single-char = (assignment, not == which is handled above)
        if ch == "=" and (i == 0 or stripped[i-1:i+1] not in ("==", "!=", "<=", ">=")):
            if i + 1 < len(stripped) and stripped[i + 1] == "=":
                # Part of ==, skip (shouldn't reach here but safety)
                result.append(ch)
                i += 1
                continue
            if result and result[-1] != " ":
                result.append(" ")
            result.append(ch)
            i += 1
            if i < len(stripped) and stripped[i] != " ":
                result.append(" ")
            continue

        # Single-char arithmetic operators: + - * / %
        # Only space them when they look like binary operators (preceded by
        # a non-space, non-operator character — i.e. an operand just ended).
        if ch in "+-*/%" and not in_string:
            # Heuristic: binary if preceded by alnum, ), ], or "
            prev_non_space = None
            for k in range(len(result) - 1, -1, -1):
                if result[k] != " ":
                    prev_non_space = result[k]
                    break
            is_binary = prev_non_space is not None and (
                prev_non_space.isalnum() or prev_non_space in (')', ']', '"', '_')
            )
            if is_binary:
                if result and result[-1] != " ":
                    result.append(" ")
                result.append(ch)
                i += 1
                if i < len(stripped) and stripped[i] != " ":
                    result.append(" ")
            else:
                # Unary operator — no space before, keep as-is
                result.append(ch)
                i += 1
            continue

        result.append(ch)
        i += 1

    formatted = leading + "".join(result)
    # Collapse multiple spaces (outside strings) into single spaces
    # This is tricky with strings, so only collapse in the non-string parts
    return formatted


def _collapse_blanks(lines, max_blanks):
    """Collapse consecutive blank lines to at most max_blanks."""
    result = []
    blank_count = 0
    for line in lines:
        if line.strip() == "":
            blank_count += 1
            if blank_count <= max_blanks:
                result.append("")
        else:
            blank_count = 0
            result.append(line)
    return result


def _strip_trailing(lines):
    """Remove trailing whitespace from each line."""
    return [line.rstrip() for line in lines]


def _ensure_final_newline(text):
    """Ensure text ends with exactly one newline."""
    text = text.rstrip("\n\r")
    return text + "\n"


def _align_inline_comments(lines):
    """Align trailing comments on consecutive lines to the same column.

    Groups are consecutive non-blank lines that each have a trailing
    ``# comment``.  Within each group the ``#`` is aligned to the
    column of the longest code-part (plus one space).
    """
    result = list(lines)
    i = 0
    while i < len(result):
        # Find a run of consecutive lines with trailing comments
        group_start = None
        group = []
        j = i
        while j < len(result):
            line = result[j]
            stripped = line.lstrip()
            if not stripped or stripped.startswith("#"):
                break
            # Check for trailing comment (not inside string)
            code_part, comment = _split_trailing_comment(line)
            if comment is None:
                break
            if group_start is None:
                group_start = j
            group.append((j, code_part, comment))
            j += 1

        if len(group) >= 2:
            max_code_len = max(len(cp.rstrip()) for _, cp, _ in group)
            for idx, code_part, comment in group:
                padded = code_part.rstrip().ljust(max_code_len)
                result[idx] = padded + "  " + comment
            i = j
        else:
            i += 1

    return result


def _split_trailing_comment(line):
    """Split a line into (code, comment) respecting strings.

    Returns (line, None) if there is no trailing comment.
    """
    in_string = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == '"' and not in_string:
            in_string = True
            i += 1
            continue
        if in_string:
            if ch == '\\' and i + 1 < len(line):
                i += 2  # properly skip escaped character
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '#':
            return line[:i], line[i:]
        i += 1
    return line, None


# ---------------------------------------------------------------------------
# Format entry point
# ---------------------------------------------------------------------------

def format_code(source, indent_width=DEFAULT_INDENT):
    """Format a sauravcode source string and return the formatted version."""
    lines = source.split("\n")

    # Detect existing indent
    old_indent = _detect_indent(lines)

    # 1. Strip trailing whitespace
    lines = _strip_trailing(lines)

    # 2. Normalise indentation
    lines = [_normalise_indent(line, old_indent, indent_width) for line in lines]

    # 3. Fix operator spacing
    lines = [_fix_operator_spacing(line) for line in lines]

    # 4. Collapse excessive blank lines
    lines = _collapse_blanks(lines, MAX_CONSECUTIVE_BLANKS)

    # 5. Align trailing comments in groups
    lines = _align_inline_comments(lines)

    # 6. Strip trailing whitespace again (spacing fixes may add some)
    lines = _strip_trailing(lines)

    result = "\n".join(lines)

    # 7. Ensure final newline
    if TRAILING_NEWLINE:
        result = _ensure_final_newline(result)

    return result


# ---------------------------------------------------------------------------
# Diffing
# ---------------------------------------------------------------------------

def unified_diff(original, formatted, filename="<stdin>"):
    """Return a unified diff string, or empty if no changes."""
    import difflib
    orig_lines = original.splitlines(keepends=True)
    fmt_lines = formatted.splitlines(keepends=True)
    diff = difflib.unified_diff(orig_lines, fmt_lines,
                                fromfile=filename,
                                tofile=filename + " (formatted)")
    return "".join(diff)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _find_srv_files(path):
    """Recursively find all .srv files under a directory."""
    srv_files = []
    for root, _dirs, files in os.walk(path):
        for f in files:
            if f.endswith(".srv"):
                srv_files.append(os.path.join(root, f))
    return sorted(srv_files)


def _format_file(filepath, indent_width, write, check, show_diff):
    """Format a single file.  Returns True if changes were made."""
    with open(filepath, "r", encoding="utf-8") as f:
        original = f.read()

    formatted = format_code(original, indent_width)

    if original == formatted:
        return False  # no changes

    if check:
        print(f"would reformat {filepath}")
        return True

    if write:
        with open(filepath, "w", encoding="utf-8", newline="") as f:
            f.write(formatted)
        print(f"reformatted {filepath}")
        return True

    # Default: show diff
    if show_diff:
        diff = unified_diff(original, formatted, filepath)
        if diff:
            print(diff, end="")
    else:
        # Summary mode
        diff = unified_diff(original, formatted, filepath)
        if diff:
            print(f"would reformat {filepath}")
            print(diff, end="")

    return True


def main():
    parser = argparse.ArgumentParser(
        prog="sauravfmt",
        description="Code formatter for the sauravcode language.",
    )
    parser.add_argument("paths", nargs="+",
                        help="Files or directories to format")
    parser.add_argument("--write", "-w", action="store_true",
                        help="Write changes in-place")
    parser.add_argument("--check", action="store_true",
                        help="Exit with code 1 if any files would be changed (CI mode)")
    parser.add_argument("--diff", "-d", action="store_true",
                        help="Show unified diff")
    parser.add_argument("--indent", type=int, default=DEFAULT_INDENT,
                        help=f"Indent width in spaces (default: {DEFAULT_INDENT})")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")

    args = parser.parse_args()

    # Collect files
    files = []
    for p in args.paths:
        if os.path.isdir(p):
            files.extend(_find_srv_files(p))
        elif os.path.isfile(p):
            files.append(p)
        else:
            print(f"sauravfmt: error: {p} not found", file=sys.stderr)
            sys.exit(1)

    if not files:
        print("sauravfmt: no .srv files found", file=sys.stderr)
        sys.exit(1)

    changed_count = 0
    for filepath in files:
        if _format_file(filepath, args.indent, args.write, args.check,
                        args.diff or (not args.write and not args.check)):
            changed_count += 1

    total = len(files)
    unchanged = total - changed_count

    # Summary
    parts = []
    if changed_count:
        verb = "reformatted" if args.write else "would reformat"
        parts.append(f"{changed_count} file{'s' if changed_count != 1 else ''} {verb}")
    if unchanged:
        parts.append(f"{unchanged} file{'s' if unchanged != 1 else ''} unchanged")
    print(f"\nAll done! {', '.join(parts)}.")

    if args.check and changed_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
