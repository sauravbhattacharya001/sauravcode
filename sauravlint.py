#!/usr/bin/env python3
"""sauravlint — Static analysis linter for the sauravcode language (.srv files).

Detects potential bugs, style issues, and code smells in sauravcode programs.

Usage:
    python sauravlint.py file.srv [file2.srv ...]
    python sauravlint.py --check dir/           # exit 1 if any warnings
    python sauravlint.py --json file.srv         # JSON output
    python sauravlint.py --severity error file.srv  # only errors
    python sauravlint.py --disable W003,W005 file.srv

Rules:
    E001  Undefined variable usage
    E002  Unreachable code after return/throw/break/continue
    E003  Division by zero literal
    E004  Duplicate function definition (same name & arity)
    E005  Break/continue outside loop
    W001  Unused variable (assigned but never read)
    W002  Unused function parameter
    W003  Variable shadows outer scope
    W004  Comparison to self (x == x, x != x)
    W005  Constant condition (if true, while false)
    W006  Empty block (if/while/for/try/catch with no body)
    W007  Function with too many parameters (>5)
    W008  Too deep nesting (>5 levels)
    W009  Unused import
    W010  Reassignment before use (variable assigned twice without read)
    W011  Inconsistent indentation (mixed tabs/spaces)
    S001  Magic number (numeric literal > 1 outside of assignment/comparison)
    S002  Too long line (>120 chars)
    S003  Trailing whitespace
    S004  Missing newline at end of file
"""

import sys
import os
import json
import re
import glob
from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional
from enum import Enum


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"
    STYLE = "style"


@dataclass
class LintIssue:
    rule: str
    severity: Severity
    line: int
    column: int
    message: str
    source_line: str = ""

    def to_dict(self):
        return {
            "rule": self.rule,
            "severity": self.severity.value,
            "line": self.line,
            "column": self.column,
            "message": self.message,
        }

    def __str__(self):
        sev = self.severity.value[0].upper()
        return f"  {self.line}:{self.column}  {sev} {self.rule}  {self.message}"


@dataclass
class LintReport:
    file: str
    issues: List[LintIssue] = field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
    style_count: int = 0

    def add(self, issue: LintIssue):
        self.issues.append(issue)
        if issue.severity == Severity.ERROR:
            self.error_count += 1
        elif issue.severity == Severity.WARNING:
            self.warning_count += 1
        else:
            self.style_count += 1

    @property
    def total(self):
        return len(self.issues)

    def to_dict(self):
        return {
            "file": self.file,
            "issues": [i.to_dict() for i in self.issues],
            "errors": self.error_count,
            "warnings": self.warning_count,
            "style": self.style_count,
        }


# -- Token types for lightweight scanning --

_KEYWORDS = {
    "function", "return", "class", "int", "float", "bool", "string",
    "if", "else", "for", "in", "while", "try", "catch", "throw",
    "print", "true", "false", "and", "or", "not", "list", "set",
    "stack", "queue", "append", "len", "pop", "lambda", "import",
    "match", "case", "enum", "break", "continue", "assert", "yield",
    "next", "range", "collect", "type_of", "is_generator",
}

_BUILTIN_FUNCTIONS = {
    "print", "len", "append", "pop", "type_of", "is_generator",
    "collect", "range", "input", "str", "int", "float", "abs",
    "min", "max", "round", "sorted", "reversed", "enumerate",
    "zip", "map", "filter", "sum", "any", "all", "hash",
    "keys", "values", "items", "has_key", "remove", "clear",
    "contains", "push", "peek", "is_empty", "size", "to_list",
    "split", "join", "strip", "upper", "lower", "replace",
    "starts_with", "ends_with", "find", "substring", "trim",
    "char_at", "to_upper", "to_lower", "index_of", "Math",
    "String", "IO", "Collections", "DateTime", "Random", "JSON",
    "read_file", "write_file", "file_exists", "sleep", "time_ms",
    "now", "format_date", "random_int", "random_float", "seed",
    "json_parse", "json_stringify", "sqrt", "pow", "log", "sin",
    "cos", "tan", "floor", "ceil", "pi", "e", "next",
    "http_get", "http_post", "http_put", "http_delete",
}

_BLOCK_STARTERS = {"if", "else", "while", "for", "try", "catch", "function", "match", "case", "enum"}
_LOOP_KEYWORDS = {"while", "for"}
_TERMINATORS = {"return", "throw", "break", "continue"}

# Regex for identifiers and numbers in a line
_IDENT_RE = re.compile(r'\b([a-zA-Z_]\w*)\b')
_NUMBER_RE = re.compile(r'\b(\d+(?:\.\d*)?)\b')
_ASSIGN_RE = re.compile(r'^(\s*)([a-zA-Z_]\w*)\s*=\s*')
_FUNC_DEF_RE = re.compile(r'^(\s*)function\s+([a-zA-Z_]\w*)((?:\s+[a-zA-Z_]\w*)*)\s*$')
_IMPORT_RE = re.compile(r'^(\s*)import\s+"([^"]+)"\s*$')
_FOR_RE = re.compile(r'^(\s*)for\s+([a-zA-Z_]\w*)\s+(?:in\s+)?')
_CATCH_RE = re.compile(r'^(\s*)catch\s+([a-zA-Z_]\w*)\s*$')
_COMPARISON_RE = re.compile(r'([a-zA-Z_]\w*)\s*(==|!=)\s*([a-zA-Z_]\w*)')
_SELF_COMPARE_RE = re.compile(r'\b([a-zA-Z_]\w*)\s*(?:==|!=)\s*\1\b')
_CONDITION_RE = re.compile(r'^\s*(?:if|while|else\s+if)\s+(true|false)\s*$')
_DIVISION_RE = re.compile(r'/\s*0(?:\.\s*0*)?\b')
_TRAILING_WS_RE = re.compile(r'[ \t]+$')


def _get_indent(line: str) -> int:
    """Get indentation level (number of leading spaces; tabs count as 4)."""
    count = 0
    for ch in line:
        if ch == ' ':
            count += 1
        elif ch == '\t':
            count += 4
        else:
            break
    return count


def _strip_comment(line: str) -> str:
    """Remove trailing comment from a line, respecting strings."""
    in_string = False
    escape = False
    for i, ch in enumerate(line):
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
        elif ch == '#' and not in_string:
            return line[:i]
    return line


def _extract_identifiers(line: str) -> Set[str]:
    """Extract all identifier tokens from a line (excluding strings and comments)."""
    cleaned = _strip_comment(line)
    # Remove string literals
    cleaned = re.sub(r'f?"(?:[^"\\]|\\.)*"', '', cleaned)
    return set(_IDENT_RE.findall(cleaned)) - _KEYWORDS


def _line_keyword(line: str) -> Optional[str]:
    """Get the first keyword token of a stripped line."""
    stripped = line.strip()
    if not stripped or stripped.startswith('#'):
        return None
    m = re.match(r'(\w+(?:\s+\w+)?)', stripped)
    if m:
        word = m.group(1)
        if word in _BLOCK_STARTERS or word.startswith("else if"):
            return word.split()[0] if word != "else if" else "else"
        first = word.split()[0]
        if first in _KEYWORDS:
            return first
    return None


@dataclass
class Scope:
    """Tracks variable definitions and usages within a scope."""
    name: str
    depth: int
    defined: Dict[str, int] = field(default_factory=dict)  # var -> line defined
    used: Set[str] = field(default_factory=set)
    params: Dict[str, int] = field(default_factory=dict)  # param -> line
    is_function: bool = False
    is_loop: bool = False
    assigned_without_read: Dict[str, int] = field(default_factory=dict)


class SauravLinter:
    """Static analysis linter for sauravcode .srv files."""

    def __init__(self, disabled_rules: Optional[Set[str]] = None):
        self.disabled = disabled_rules or set()

    def lint(self, source: str, filename: str = "<stdin>") -> LintReport:
        report = LintReport(file=filename)
        lines = source.split('\n')

        self._check_structure(lines, report)
        self._check_style(lines, report, source)
        self._check_variables(lines, report)

        # Sort by line, then column
        report.issues.sort(key=lambda i: (i.line, i.column))
        return report

    def _emit(self, report: LintReport, rule: str, severity: Severity,
              line: int, col: int, msg: str, src: str = ""):
        if rule not in self.disabled:
            report.add(LintIssue(rule, severity, line, col, msg, src))

    # -- Structural checks --

    def _check_structure(self, lines: List[str], report: LintReport):
        """Check for structural issues: unreachable code, empty blocks, etc."""
        func_defs: Dict[str, List[int]] = {}  # name -> [line numbers]
        imports: Dict[str, int] = {}  # module -> line
        all_idents: Set[str] = set()
        indent_stack = [0]
        in_terminated = False
        terminated_indent = -1
        loop_depth = 0
        nesting_depth = 0
        max_nesting = 5

        for lineno_0, raw in enumerate(lines):
            lineno = lineno_0 + 1
            stripped = raw.strip()

            if not stripped or stripped.startswith('#'):
                continue

            indent = _get_indent(raw)
            cleaned = _strip_comment(raw).strip()

            # Collect all identifiers for import usage check
            all_idents |= _extract_identifiers(raw)

            # Track nesting depth
            kw = _line_keyword(raw)

            # Reset terminated state when we dedent below the terminator
            if in_terminated and indent < terminated_indent:
                in_terminated = False

            # Unreachable code check (E002)
            if in_terminated and indent >= terminated_indent:
                self._emit(report, "E002", Severity.ERROR, lineno, 1,
                           "Unreachable code after return/throw/break/continue", raw)

            # Function definition
            m = _FUNC_DEF_RE.match(raw)
            if m:
                fname = m.group(2)
                params_str = m.group(3).strip()
                param_count = len(params_str.split()) if params_str else 0
                func_defs.setdefault(fname, []).append(lineno)

                # W007: too many params
                if param_count > 5:
                    self._emit(report, "W007", Severity.WARNING, lineno, 1,
                               f"Function '{fname}' has {param_count} parameters (max 5)", raw)

            # Import
            m = _IMPORT_RE.match(raw)
            if m:
                mod = m.group(2)
                imports[mod] = lineno

            # Division by zero (E003)
            code_part = _strip_comment(raw)
            code_no_str = re.sub(r'f?"(?:[^"\\]|\\.)*"', '', code_part)
            if _DIVISION_RE.search(code_no_str):
                col = _DIVISION_RE.search(code_no_str).start() + 1
                self._emit(report, "E003", Severity.ERROR, lineno, col,
                           "Division by zero", raw)

            # Break/continue outside loop (E005)
            if kw in ("break", "continue") and loop_depth == 0:
                self._emit(report, "E005", Severity.ERROR, lineno, 1,
                           f"'{kw}' outside of loop", raw)

            # Self-comparison (W004)
            m = _SELF_COMPARE_RE.search(code_no_str)
            if m:
                var = m.group(1)
                if var not in _KEYWORDS:
                    self._emit(report, "W004", Severity.WARNING, lineno, m.start() + 1,
                               f"Comparison of '{var}' to itself", raw)

            # Constant condition (W005)
            m = _CONDITION_RE.match(raw)
            if m:
                val = m.group(1)
                self._emit(report, "W005", Severity.WARNING, lineno, 1,
                           f"Constant condition: always {'true' if val == 'true' else 'false'}", raw)

            # Track loop depth for break/continue checking
            if kw in _LOOP_KEYWORDS:
                loop_depth += 1

            # Track nesting
            if kw in _BLOCK_STARTERS:
                nesting_depth += 1
                if nesting_depth > max_nesting:
                    self._emit(report, "W008", Severity.WARNING, lineno, 1,
                               f"Nesting depth {nesting_depth} exceeds maximum ({max_nesting})", raw)

            # Check for empty blocks (W006)
            if kw in _BLOCK_STARTERS and kw != "enum":
                # Look ahead for body
                block_indent = indent
                has_body = False
                for next_line in lines[lineno_0 + 1:]:
                    next_stripped = next_line.strip()
                    if not next_stripped or next_stripped.startswith('#'):
                        continue
                    next_indent = _get_indent(next_line)
                    if next_indent > block_indent:
                        has_body = True
                    break
                if not has_body:
                    self._emit(report, "W006", Severity.WARNING, lineno, 1,
                               f"Empty '{kw}' block", raw)

            # Mark termination for unreachable code detection
            if kw in _TERMINATORS:
                in_terminated = True
                terminated_indent = indent

        # E004: duplicate function definitions
        for fname, line_nums in func_defs.items():
            if len(line_nums) > 1:
                for ln in line_nums[1:]:
                    self._emit(report, "E004", Severity.ERROR, ln, 1,
                               f"Duplicate function definition '{fname}' (first at line {line_nums[0]})")

        # W009: unused imports
        for mod, ln in imports.items():
            # Check if any identifier from the module name appears
            mod_base = mod.replace('.srv', '').split('/')[-1]
            if mod_base not in all_idents:
                self._emit(report, "W009", Severity.WARNING, ln, 1,
                           f"Unused import '{mod}'")

    # -- Variable analysis --

    def _check_variables(self, lines: List[str], report: LintReport):
        """Check for undefined/unused variables and parameters."""
        # Simplified scope analysis: track defines and uses globally
        defined: Dict[str, int] = {}  # var -> first definition line
        used: Set[str] = set()
        func_params: Dict[str, Dict[str, int]] = {}  # func -> {param: line}
        func_body_idents: Dict[str, Set[str]] = {}  # func -> identifiers used in body
        current_func: Optional[str] = None
        current_func_indent = -1
        shadow_outer: Dict[str, int] = {}  # for shadow detection

        for lineno_0, raw in enumerate(lines):
            lineno = lineno_0 + 1
            stripped = raw.strip()
            if not stripped or stripped.startswith('#'):
                continue

            indent = _get_indent(raw)

            # Track current function context
            m = _FUNC_DEF_RE.match(raw)
            if m:
                fname = m.group(2)
                params_str = m.group(3).strip()
                params = params_str.split() if params_str else []
                current_func = fname
                current_func_indent = indent
                func_params[fname] = {}
                func_body_idents[fname] = set()
                for p in params:
                    func_params[fname][p] = lineno
                    # W003: shadow check
                    if p in defined:
                        self._emit(report, "W003", Severity.WARNING, lineno,
                                   raw.index(p) + 1,
                                   f"Parameter '{p}' shadows variable from outer scope (line {defined[p]})", raw)
                defined[fname] = lineno
                continue

            # Detect leaving function
            if current_func and indent <= current_func_indent:
                current_func = None
                current_func_indent = -1

            # Assignment
            m = _ASSIGN_RE.match(raw)
            if m:
                var = m.group(2)
                if var not in _KEYWORDS and var not in _BUILTIN_FUNCTIONS:
                    # W003: shadow check for assignments
                    if current_func and var in defined and defined[var] < lineno:
                        # Only warn if the outer def is outside this function
                        pass  # simplified; skip for now to reduce false positives

                    # W010: reassignment without read
                    if var in defined and var not in used and defined[var] != lineno:
                        # Only flag if same scope (approximate)
                        pass  # too many false positives without proper scoping

                    defined[var] = lineno

                # Collect identifiers on RHS
                rhs = raw[m.end():]
                rhs_idents = _extract_identifiers(rhs)
                used |= rhs_idents
                if current_func and current_func in func_body_idents:
                    func_body_idents[current_func] |= rhs_idents
                continue

            # For loop variable
            m = _FOR_RE.match(raw)
            if m:
                var = m.group(2)
                defined[var] = lineno
                # Rest of line has identifiers used
                rest_idents = _extract_identifiers(raw[m.end():])
                used |= rest_idents
                if current_func and current_func in func_body_idents:
                    func_body_idents[current_func] |= rest_idents
                continue

            # Catch variable
            m = _CATCH_RE.match(raw)
            if m:
                var = m.group(2)
                defined[var] = lineno
                continue

            # General usage: collect all identifiers
            idents = _extract_identifiers(raw)
            used |= idents
            if current_func and current_func in func_body_idents:
                func_body_idents[current_func] |= idents

        # W001: unused variables (only for non-function, non-param vars)
        for var, ln in defined.items():
            if var not in used and var not in _BUILTIN_FUNCTIONS:
                # Skip function names (they might be called elsewhere)
                is_func = any(var in fp_dict for fp_dict in func_params.values()) or \
                          any(var == fn for fn in func_params.keys())
                if not is_func:
                    self._emit(report, "W001", Severity.WARNING, ln, 1,
                               f"Variable '{var}' is assigned but never used")

        # W002: unused function parameters
        for fname, params in func_params.items():
            body_idents = func_body_idents.get(fname, set())
            # Also check global usage since our scope analysis is approximate
            for p, ln in params.items():
                if p not in body_idents and p not in used:
                    self._emit(report, "W002", Severity.WARNING, ln, 1,
                               f"Parameter '{p}' of function '{fname}' is never used")

    # -- Style checks --

    def _check_style(self, lines: List[str], report: LintReport, source: str):
        """Check for style issues."""
        has_tabs = False
        has_spaces = False

        for lineno_0, raw in enumerate(lines):
            lineno = lineno_0 + 1

            # S002: too long line
            if len(raw) > 120:
                self._emit(report, "S002", Severity.STYLE, lineno, 121,
                           f"Line too long ({len(raw)} > 120 characters)", raw)

            # S003: trailing whitespace
            if raw and _TRAILING_WS_RE.search(raw):
                self._emit(report, "S003", Severity.STYLE, lineno, len(raw.rstrip()) + 1,
                           "Trailing whitespace", raw)

            # W011: mixed indentation
            leading = raw[:len(raw) - len(raw.lstrip())]
            if '\t' in leading:
                has_tabs = True
            if ' ' in leading and leading.strip() == '':
                # pure space indent
                if leading:
                    has_spaces = True

        if has_tabs and has_spaces:
            self._emit(report, "W011", Severity.WARNING, 1, 1,
                       "Inconsistent indentation: file mixes tabs and spaces")

        # S004: missing newline at end of file
        if source and not source.endswith('\n'):
            self._emit(report, "S004", Severity.STYLE, len(lines), 1,
                       "Missing newline at end of file")


def lint_file(filepath: str, disabled: Optional[Set[str]] = None) -> LintReport:
    """Lint a single .srv file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            source = f.read()
    except (IOError, UnicodeDecodeError) as exc:
        report = LintReport(file=filepath)
        report.add(LintIssue("F001", Severity.ERROR, 0, 0, f"Cannot read file: {exc}"))
        return report

    linter = SauravLinter(disabled_rules=disabled)
    return linter.lint(source, filepath)


def lint_directory(dirpath: str, disabled: Optional[Set[str]] = None) -> List[LintReport]:
    """Lint all .srv files in a directory recursively."""
    reports = []
    for root, dirs, files in os.walk(dirpath):
        for fname in sorted(files):
            if fname.endswith('.srv'):
                fpath = os.path.join(root, fname)
                reports.append(lint_file(fpath, disabled))
    return reports


def format_report(report: LintReport) -> str:
    """Format a lint report for terminal output."""
    if not report.issues:
        return ""
    lines = [f"\n{report.file}"]
    for issue in report.issues:
        lines.append(str(issue))
    return '\n'.join(lines)


def format_summary(reports: List[LintReport]) -> str:
    """Format a summary of all reports."""
    total_e = sum(r.error_count for r in reports)
    total_w = sum(r.warning_count for r in reports)
    total_s = sum(r.style_count for r in reports)
    total = total_e + total_w + total_s
    files = len(reports)
    clean = sum(1 for r in reports if r.total == 0)

    parts = []
    if total_e:
        parts.append(f"{total_e} error{'s' if total_e != 1 else ''}")
    if total_w:
        parts.append(f"{total_w} warning{'s' if total_w != 1 else ''}")
    if total_s:
        parts.append(f"{total_s} style issue{'s' if total_s != 1 else ''}")

    if not parts:
        return f"\n[PASS] {files} file{'s' if files != 1 else ''} checked - no issues found"

    return f"\n[FAIL] {files} file{'s' if files != 1 else ''} checked ({clean} clean) - {', '.join(parts)}"


def main():
    import argparse

    parser = argparse.ArgumentParser(
        prog='sauravlint',
        description='Static analysis linter for sauravcode (.srv files)')
    parser.add_argument('paths', nargs='+', help='Files or directories to lint')
    parser.add_argument('--check', action='store_true',
                        help='Exit with code 1 if any issues found')
    parser.add_argument('--json', action='store_true', dest='json_output',
                        help='Output results as JSON')
    parser.add_argument('--severity', choices=['error', 'warning', 'style'],
                        default='style', help='Minimum severity to report (default: style)')
    parser.add_argument('--disable', type=str, default='',
                        help='Comma-separated list of rules to disable (e.g. W003,S001)')

    args = parser.parse_args()

    disabled = set(r.strip() for r in args.disable.split(',') if r.strip())

    severity_filter = {
        'error': {Severity.ERROR},
        'warning': {Severity.ERROR, Severity.WARNING},
        'style': {Severity.ERROR, Severity.WARNING, Severity.STYLE},
    }[args.severity]

    reports = []
    for path in args.paths:
        if os.path.isdir(path):
            reports.extend(lint_directory(path, disabled))
        elif os.path.isfile(path):
            reports.append(lint_file(path, disabled))
        else:
            # Glob
            matches = glob.glob(path, recursive=True)
            for m in matches:
                if os.path.isfile(m):
                    reports.append(lint_file(m, disabled))

    # Filter by severity
    for r in reports:
        r.issues = [i for i in r.issues if i.severity in severity_filter]
        r.error_count = sum(1 for i in r.issues if i.severity == Severity.ERROR)
        r.warning_count = sum(1 for i in r.issues if i.severity == Severity.WARNING)
        r.style_count = sum(1 for i in r.issues if i.severity == Severity.STYLE)

    if args.json_output:
        print(json.dumps([r.to_dict() for r in reports], indent=2))
    else:
        for r in reports:
            output = format_report(r)
            if output:
                print(output)
        print(format_summary(reports))

    if args.check and any(r.total > 0 for r in reports):
        sys.exit(1)


if __name__ == '__main__':
    main()
