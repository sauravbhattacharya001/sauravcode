#!/usr/bin/env python3
from __future__ import annotations
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

from sauravtext import strip_comment, extract_identifiers as _text_extract_identifiers


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


# _strip_comment is now provided by sauravtext.strip_comment (imported above)
_strip_comment = strip_comment


def _extract_identifiers(line: str) -> Set[str]:
    """Extract all identifier tokens from a line (excluding strings and comments)."""
    return _text_extract_identifiers(line, exclude=_KEYWORDS)


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


@dataclass
class _ParsedLine:
    """Pre-parsed information for a single source line.

    Computed once by ``_scan_lines`` and shared across all checkers so
    that regex matching and identifier extraction happen only once per
    line instead of once per checker.
    """
    lineno: int            # 1-based
    raw: str               # original text
    stripped: str           # raw.strip()
    indent: int            # leading whitespace depth
    keyword: Optional[str] # first keyword token (via _line_keyword)
    code_no_str: str       # code with strings and comments removed
    identifiers: Set[str]  # identifiers (minus keywords)
    func_match: Optional[re.Match] = None   # _FUNC_DEF_RE result
    assign_match: Optional[re.Match] = None # _ASSIGN_RE result
    import_match: Optional[re.Match] = None # _IMPORT_RE result
    for_match: Optional[re.Match] = None    # _FOR_RE result
    catch_match: Optional[re.Match] = None  # _CATCH_RE result
    is_blank: bool = False  # blank or comment-only


@dataclass
class _StructState:
    """Mutable state threaded through the structural check pass."""
    func_defs: Dict[str, List[int]] = field(default_factory=dict)
    imports: Dict[str, int] = field(default_factory=dict)
    all_idents: Set[str] = field(default_factory=set)
    in_terminated: bool = False
    terminated_indent: int = -1
    loop_depth: int = 0
    loop_indents: List[int] = field(default_factory=list)
    nesting_depth: int = 0
    block_indents: List[int] = field(default_factory=list)


class SauravLinter:
    """Static analysis linter for sauravcode .srv files."""

    def __init__(self, disabled_rules: Optional[Set[str]] = None):
        self.disabled = disabled_rules or set()

    def lint(self, source: str, filename: str = "<stdin>") -> LintReport:
        report = LintReport(file=filename)
        lines = source.split('\n')
        parsed = self._scan_lines(lines)

        self._check_structure(lines, report, parsed)
        self._check_style(lines, report, source)
        self._check_variables(lines, report, parsed)

        # Sort by line, then column
        report.issues.sort(key=lambda i: (i.line, i.column))
        return report

    @staticmethod
    def _scan_lines(lines: List[str]) -> List[_ParsedLine]:
        """Single-pass line scanner that pre-computes regex matches and
        identifier sets used by both structural and variable checkers."""
        result = []
        for lineno_0, raw in enumerate(lines):
            lineno = lineno_0 + 1
            stripped = raw.strip()
            is_blank = not stripped or stripped.startswith('#')

            indent = _get_indent(raw) if not is_blank else 0
            keyword = _line_keyword(raw) if not is_blank else None

            # Strip comments/strings for code analysis
            code_part = _strip_comment(raw)
            code_no_str = re.sub(r'f?"(?:[^"\\]|\\.)*"', '', code_part)

            identifiers = _extract_identifiers(raw) if not is_blank else set()

            pl = _ParsedLine(
                lineno=lineno, raw=raw, stripped=stripped, indent=indent,
                keyword=keyword, code_no_str=code_no_str,
                identifiers=identifiers, is_blank=is_blank,
            )

            if not is_blank:
                pl.func_match = _FUNC_DEF_RE.match(raw)
                pl.assign_match = _ASSIGN_RE.match(raw)
                pl.import_match = _IMPORT_RE.match(raw)
                pl.for_match = _FOR_RE.match(raw)
                pl.catch_match = _CATCH_RE.match(raw)

            result.append(pl)
        return result

    def _emit(self, report: LintReport, rule: str, severity: Severity,
              line: int, col: int, msg: str, src: str = ""):
        if rule not in self.disabled:
            report.add(LintIssue(rule, severity, line, col, msg, src))

    _MAX_NESTING = 5

    # -- Structural checks --

    def _check_structure(self, lines: List[str], report: LintReport,
                         parsed: List[_ParsedLine]):
        """Check for structural issues: unreachable code, empty blocks, etc."""
        st = self._StructState()

        # Precompute next-non-blank index for O(1) empty-block checks
        n_parsed = len(parsed)
        _next_non_blank: List[int] = [n_parsed] * n_parsed
        for _i in range(n_parsed - 2, -1, -1):
            _next_non_blank[_i] = (_i + 1) if not parsed[_i + 1].is_blank else _next_non_blank[_i + 1]

        for pl in parsed:
            if pl.is_blank:
                continue

            st.all_idents |= pl.identifiers

            # Pop closed loops/blocks when we dedent
            self._pop_closed_scopes(st, pl.indent)

            self._check_unreachable_code(report, st, pl)
            self._check_func_definition(report, st, pl)
            self._check_import(st, pl)
            self._check_division_by_zero(report, pl)
            self._check_break_continue(report, st, pl)
            self._check_self_comparison(report, pl)
            self._check_constant_condition(report, pl)
            self._check_loop_entry(st, pl)
            self._check_nesting(report, st, pl)
            self._check_empty_block(report, pl, parsed, _next_non_blank, n_parsed)
            self._check_terminator(st, pl)

        # Post-pass: cross-file checks
        self._check_duplicate_functions(report, st)
        self._check_unused_imports(report, st)

    @staticmethod
    def _pop_closed_scopes(st: '_StructState', indent: int):
        """Pop loops and blocks from tracking stacks when indentation decreases."""
        while st.loop_indents and indent <= st.loop_indents[-1]:
            st.loop_indents.pop()
            st.loop_depth -= 1
        while st.block_indents and indent <= st.block_indents[-1]:
            st.block_indents.pop()
            st.nesting_depth -= 1

    def _check_unreachable_code(self, report: LintReport,
                                st: '_StructState', pl: _ParsedLine):
        """E002: Code after return/throw/break/continue at same or deeper indent."""
        if st.in_terminated and pl.indent < st.terminated_indent:
            st.in_terminated = False
        if st.in_terminated and pl.indent >= st.terminated_indent:
            self._emit(report, "E002", Severity.ERROR, pl.lineno, 1,
                       "Unreachable code after return/throw/break/continue", pl.raw)

    def _check_func_definition(self, report: LintReport,
                               st: '_StructState', pl: _ParsedLine):
        """Collect function definitions; W007: too many parameters."""
        m = pl.func_match
        if not m:
            return
        fname = m.group(2)
        params_str = m.group(3).strip()
        param_count = len(params_str.split()) if params_str else 0
        st.func_defs.setdefault(fname, []).append(pl.lineno)
        if param_count > 5:
            self._emit(report, "W007", Severity.WARNING, pl.lineno, 1,
                       f"Function '{fname}' has {param_count} parameters (max 5)", pl.raw)

    @staticmethod
    def _check_import(st: '_StructState', pl: _ParsedLine):
        """Collect imports for later unused-import analysis."""
        m = pl.import_match
        if m:
            st.imports[m.group(2)] = pl.lineno

    def _check_division_by_zero(self, report: LintReport, pl: _ParsedLine):
        """E003: Division by literal zero."""
        m = _DIVISION_RE.search(pl.code_no_str)
        if m:
            self._emit(report, "E003", Severity.ERROR, pl.lineno, m.start() + 1,
                       "Division by zero", pl.raw)

    def _check_break_continue(self, report: LintReport,
                              st: '_StructState', pl: _ParsedLine):
        """E005: Break/continue outside any loop."""
        if pl.keyword in ("break", "continue") and st.loop_depth == 0:
            self._emit(report, "E005", Severity.ERROR, pl.lineno, 1,
                       f"'{pl.keyword}' outside of loop", pl.raw)

    def _check_self_comparison(self, report: LintReport, pl: _ParsedLine):
        """W004: Comparison of a variable to itself (x == x)."""
        m = _SELF_COMPARE_RE.search(pl.code_no_str)
        if m and m.group(1) not in _KEYWORDS:
            self._emit(report, "W004", Severity.WARNING, pl.lineno, m.start() + 1,
                       f"Comparison of '{m.group(1)}' to itself", pl.raw)

    def _check_constant_condition(self, report: LintReport, pl: _ParsedLine):
        """W005: Condition that is always true or always false."""
        m = _CONDITION_RE.match(pl.raw)
        if m:
            val = m.group(1)
            self._emit(report, "W005", Severity.WARNING, pl.lineno, 1,
                       f"Constant condition: always {'true' if val == 'true' else 'false'}", pl.raw)

    @staticmethod
    def _check_loop_entry(st: '_StructState', pl: _ParsedLine):
        """Track entry into loops for break/continue validation."""
        if pl.keyword in _LOOP_KEYWORDS:
            st.loop_depth += 1
            st.loop_indents.append(pl.indent)

    def _check_nesting(self, report: LintReport,
                       st: '_StructState', pl: _ParsedLine):
        """W008: Block nesting exceeds maximum depth."""
        if pl.keyword not in _BLOCK_STARTERS:
            return
        st.nesting_depth += 1
        st.block_indents.append(pl.indent)
        if st.nesting_depth > self._MAX_NESTING:
            self._emit(report, "W008", Severity.WARNING, pl.lineno, 1,
                       f"Nesting depth {st.nesting_depth} exceeds maximum ({self._MAX_NESTING})", pl.raw)

    def _check_empty_block(self, report: LintReport, pl: _ParsedLine,
                           parsed: List[_ParsedLine],
                           next_non_blank: List[int], n_parsed: int):
        """W006: Block keyword with no body statements."""
        kw = pl.keyword
        if kw not in _BLOCK_STARTERS or kw == "enum":
            return
        idx = pl.lineno - 1
        nxt = next_non_blank[idx] if idx < n_parsed - 1 else n_parsed
        if nxt >= n_parsed or parsed[nxt].indent <= pl.indent:
            self._emit(report, "W006", Severity.WARNING, pl.lineno, 1,
                       f"Empty '{kw}' block", pl.raw)

    @staticmethod
    def _check_terminator(st: '_StructState', pl: _ParsedLine):
        """Mark position of return/throw/break/continue for unreachable-code detection."""
        if pl.keyword in _TERMINATORS:
            st.in_terminated = True
            st.terminated_indent = pl.indent

    def _check_duplicate_functions(self, report: LintReport, st: '_StructState'):
        """E004: Same function name defined more than once."""
        for fname, line_nums in st.func_defs.items():
            if len(line_nums) > 1:
                for ln in line_nums[1:]:
                    self._emit(report, "E004", Severity.ERROR, ln, 1,
                               f"Duplicate function definition '{fname}' (first at line {line_nums[0]})")

    def _check_unused_imports(self, report: LintReport, st: '_StructState'):
        """W009: Imported module never referenced."""
        for mod, ln in st.imports.items():
            mod_base = mod.replace('.srv', '').split('/')[-1]
            if mod_base not in st.all_idents:
                self._emit(report, "W009", Severity.WARNING, ln, 1,
                           f"Unused import '{mod}'")

    # -- Variable analysis --

    def _check_variables(self, lines: List[str], report: LintReport,
                         parsed: List[_ParsedLine]):
        """Check for undefined/unused variables and parameters."""
        defined: Dict[str, int] = {}
        used: Set[str] = set()
        func_params: Dict[str, Dict[str, int]] = {}
        func_body_idents: Dict[str, Set[str]] = {}
        current_func: Optional[str] = None
        current_func_indent = -1

        for pl in parsed:
            if pl.is_blank:
                continue

            lineno = pl.lineno
            raw = pl.raw
            indent = pl.indent

            # Track current function context
            m = pl.func_match
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
            m = pl.assign_match
            if m:
                var = m.group(2)
                if var not in _KEYWORDS and var not in _BUILTIN_FUNCTIONS:
                    defined[var] = lineno

                # Collect identifiers on RHS
                rhs = raw[m.end():]
                rhs_idents = _extract_identifiers(rhs)
                used |= rhs_idents
                if current_func and current_func in func_body_idents:
                    func_body_idents[current_func] |= rhs_idents
                continue

            # For loop variable
            m = pl.for_match
            if m:
                var = m.group(2)
                defined[var] = lineno
                rest_idents = _extract_identifiers(raw[m.end():])
                used |= rest_idents
                if current_func and current_func in func_body_idents:
                    func_body_idents[current_func] |= rest_idents
                continue

            # Catch variable
            m = pl.catch_match
            if m:
                var = m.group(2)
                defined[var] = lineno
                continue

            # General usage
            used |= pl.identifiers
            if current_func and current_func in func_body_idents:
                func_body_idents[current_func] |= pl.identifiers

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
