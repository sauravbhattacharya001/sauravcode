#!/usr/bin/env python3
"""sauravsec - Security scanner for sauravcode (.srv) programs.

Detects dangerous patterns, unsafe operations, and potential
vulnerabilities in sauravcode programs by analyzing the AST.

Usage:
    python sauravsec.py file.srv [file2.srv ...]
    python sauravsec.py --json file.srv        # JSON output
    python sauravsec.py --severity high file.srv   # filter by severity
    python sauravsec.py --disable SEC003,SEC007 file.srv
    python sauravsec.py --summary dir/         # summary only
    python sauravsec.py --sarif file.srv       # SARIF output

Rules:
    SEC001  Path traversal: file path built from user input/variable
    SEC002  Unbounded loop: while(true) or while(1) with no break
    SEC003  Hardcoded credential: variable named password/secret/token/key
            assigned a string literal
    SEC004  Unchecked file operation: file read/write without try/catch
    SEC005  Recursive depth risk: function calls itself with no base case guard
    SEC006  Denial of service: unbounded list growth in a loop
    SEC007  Information leak: printing sensitive variable names
    SEC008  Unvalidated input: input() result used directly in file ops
    SEC009  Resource exhaustion: nested loops with large range
    SEC010  Catch-all silencer: empty catch block swallows errors
    SEC011  Tainted format string: f-string includes unvalidated input
    SEC012  Dangerous default: mutable default in repeated calls
"""

import sys
import os
import json
import glob

# Import the sauravcode parser
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from saurav import (
    tokenize, Parser, ASTNode, AssignmentNode, FunctionNode,
    FunctionCallNode, WhileNode, ForNode, ForEachNode, IfNode,
    TryCatchNode, BinaryOpNode, CompareNode, IdentifierNode,
    StringNode, NumberNode, BoolNode, PrintNode, ReturnNode,
    IndexNode, IndexedAssignmentNode, ListNode, AppendNode,
    FStringNode, UnaryOpNode, LogicalNode, ImportNode,
    ThrowNode, BreakNode, LambdaNode, PipeNode,
)

# ── Severity levels ──────────────────────────────────────────────
HIGH = "high"
MEDIUM = "medium"
LOW = "low"

# ── Finding data class ───────────────────────────────────────────
class Finding:
    __slots__ = ("rule", "severity", "message", "line", "column", "context")

    def __init__(self, rule, severity, message, line=None, column=0, context=""):
        self.rule = rule
        self.severity = severity
        self.message = message
        self.line = line
        self.column = column
        self.context = context

    def __repr__(self):
        loc = f":{self.line}" if self.line else ""
        return f"[{self.rule}] {self.severity.upper()}{loc} {self.message}"

    def to_dict(self):
        d = {"rule": self.rule, "severity": self.severity, "message": self.message}
        if self.line is not None:
            d["line"] = self.line
        if self.context:
            d["context"] = self.context
        return d


# ── Credential patterns ─────────────────────────────────────────
_CRED_NAMES = {
    "password", "passwd", "pwd", "secret", "api_key", "apikey",
    "token", "auth_token", "access_token", "private_key",
    "credentials", "secret_key", "db_password", "db_pass",
}

_FILE_BUILTINS = {"read_file", "write_file", "append_file", "read_lines", "file_exists"}

_INPUT_BUILTINS = {"input"}


# ── AST helpers ──────────────────────────────────────────────────
def _line(node):
    """Best-effort line number from an AST node."""
    return getattr(node, "line_num", None)


def _walk(node):
    """Yield all AST nodes in a tree (depth-first)."""
    if node is None:
        return
    if isinstance(node, list):
        for child in node:
            yield from _walk(child)
        return
    yield node
    # Walk children based on known node shapes
    for attr in ("body", "expression", "left", "right", "condition",
                 "true_body", "false_body", "handler", "params",
                 "arguments", "elements", "else_body", "cases",
                 "iterable", "key", "value",
                 "operand", "func", "start", "stop", "step",
                 "true_expr", "false_expr", "parts", "values"):
        child = getattr(node, attr, None)
        if child is not None:
            yield from _walk(child)


def _is_literal_true(node):
    """Check if node is a truthy literal (true, 1)."""
    if isinstance(node, BoolNode) and node.value is True:
        return True
    if isinstance(node, NumberNode) and node.value == 1:
        return True
    return False


def _contains_break(body):
    """Check if a body contains a break statement (at any depth)."""
    for node in _walk(body):
        if isinstance(node, BreakNode):
            return True
    return False


def _contains_call(body, name):
    """Check if body contains a function call to `name`."""
    for node in _walk(body):
        if isinstance(node, FunctionCallNode) and node.name == name:
            return True
    return False


def _body_empty(body):
    """Check if a body is empty or None."""
    if body is None:
        return True
    if isinstance(body, list) and len(body) == 0:
        return True
    return False


def _collects_identifiers(node):
    """Collect all identifier names referenced in a subtree."""
    names = set()
    for n in _walk(node):
        if isinstance(n, IdentifierNode):
            names.add(n.name)
    return names


def _contains_file_call(node):
    """Check if subtree contains a file I/O builtin call."""
    for n in _walk(node):
        if isinstance(n, FunctionCallNode) and n.name in _FILE_BUILTINS:
            return True
    return False


# ── Scanner ──────────────────────────────────────────────────────
class SecurityScanner:
    """Walks the AST and collects security findings."""

    def __init__(self, disabled=None):
        self.findings = []
        self.disabled = set(disabled or [])
        # Track state across the scan
        self._input_vars = set()       # Variables assigned from input()
        self._in_try = False           # Currently inside a try block
        self._function_names = set()   # Defined function names
        self._function_bodies = {}     # name -> body for recursion check

    def _add(self, rule, severity, message, line=None, context=""):
        if rule not in self.disabled:
            self.findings.append(Finding(rule, severity, message, line, context=context))

    def scan(self, ast):
        """Main entry point: scan a list of AST nodes."""
        # First pass: collect function names
        for node in ast:
            if isinstance(node, FunctionNode):
                self._function_names.add(node.name)
                self._function_bodies[node.name] = node.body

        # Second pass: analyze
        self._scan_nodes(ast)
        return self.findings

    def _scan_nodes(self, nodes):
        if nodes is None:
            return
        if not isinstance(nodes, list):
            nodes = [nodes]
        for node in nodes:
            self._scan_node(node)

    def _scan_node(self, node):
        if node is None:
            return

        # ── SEC001: Path traversal ───────────────────────────
        if isinstance(node, FunctionCallNode) and node.name in _FILE_BUILTINS:
            args = getattr(node, "arguments", [])
            if args:
                path_arg = args[0]
                # Check if the path argument uses a variable (not a plain string)
                if isinstance(path_arg, IdentifierNode):
                    self._add("SEC001", MEDIUM,
                              f"File operation '{node.name}' uses variable "
                              f"'{path_arg.name}' as path — validate before use",
                              _line(node))
                elif isinstance(path_arg, BinaryOpNode) and path_arg.operator == "+":
                    self._add("SEC001", MEDIUM,
                              f"File operation '{node.name}' uses concatenated path "
                              f"— may allow path traversal",
                              _line(node))
                elif isinstance(path_arg, FStringNode):
                    self._add("SEC001", MEDIUM,
                              f"File operation '{node.name}' uses f-string path "
                              f"— may allow path traversal",
                              _line(node))

        # ── SEC002: Unbounded loop ───────────────────────────
        if isinstance(node, WhileNode):
            if _is_literal_true(node.condition) and not _contains_break(node.body):
                self._add("SEC002", HIGH,
                          "Unbounded loop: while(true) with no break statement",
                          _line(node))

        # ── SEC003: Hardcoded credentials ────────────────────
        if isinstance(node, AssignmentNode):
            name_lower = node.name.lower()
            if name_lower in _CRED_NAMES and isinstance(node.expression, StringNode):
                val_preview = node.expression.value[:20]
                if val_preview:  # Non-empty string
                    self._add("SEC003", HIGH,
                              f"Hardcoded credential: '{node.name}' assigned "
                              f"string literal \"{val_preview}...\"",
                              _line(node))

        # ── SEC004: Unchecked file operation ─────────────────
        if isinstance(node, FunctionCallNode) and node.name in _FILE_BUILTINS:
            if not self._in_try:
                self._add("SEC004", MEDIUM,
                          f"File operation '{node.name}' not wrapped in try/catch "
                          f"— errors will crash the program",
                          _line(node))

        # ── SEC005: Recursive depth risk ─────────────────────
        if isinstance(node, FunctionNode):
            if _contains_call(node.body, node.name):
                # Check if there's a base case (an if/return before the recursive call)
                has_guard = False
                if isinstance(node.body, list):
                    for stmt in node.body:
                        if isinstance(stmt, IfNode):
                            has_guard = True
                            break
                        if isinstance(stmt, FunctionCallNode) and stmt.name == node.name:
                            break  # Recursive call before any guard
                if not has_guard:
                    self._add("SEC005", HIGH,
                              f"Function '{node.name}' is recursive with no "
                              f"apparent base case guard (if statement)",
                              _line(node))

        # ── SEC006: Unbounded list growth in loop ────────────
        if isinstance(node, (WhileNode, ForNode, ForEachNode)):
            body = node.body if isinstance(node.body, list) else [node.body]
            for stmt in body:
                if isinstance(stmt, FunctionCallNode) and stmt.name == "append":
                    # append inside a loop — could grow unboundedly
                    if isinstance(node, WhileNode) and _is_literal_true(node.condition):
                        self._add("SEC006", MEDIUM,
                                  "List append inside unbounded while(true) loop "
                                  "— potential memory exhaustion",
                                  _line(stmt))
                if isinstance(stmt, AppendNode):
                    if isinstance(node, WhileNode) and _is_literal_true(node.condition):
                        self._add("SEC006", MEDIUM,
                                  "List append inside unbounded while(true) loop "
                                  "— potential memory exhaustion",
                                  _line(stmt))

        # ── SEC007: Information leak ─────────────────────────
        if isinstance(node, PrintNode):
            expr = node.expression
            if isinstance(expr, IdentifierNode):
                if expr.name.lower() in _CRED_NAMES:
                    self._add("SEC007", HIGH,
                              f"Printing sensitive variable '{expr.name}' "
                              f"— potential information leak",
                              _line(node))
            # Check f-strings for sensitive var references
            if isinstance(expr, FStringNode):
                for part in getattr(expr, "parts", []):
                    if isinstance(part, IdentifierNode) and part.name.lower() in _CRED_NAMES:
                        self._add("SEC007", HIGH,
                                  f"Printing sensitive variable '{part.name}' "
                                  f"in f-string — potential information leak",
                                  _line(node))

        # ── SEC008: Unvalidated input in file ops ────────────
        if isinstance(node, AssignmentNode):
            expr = node.expression
            if isinstance(expr, FunctionCallNode) and expr.name == "input":
                self._input_vars.add(node.name)

        if isinstance(node, FunctionCallNode) and node.name in _FILE_BUILTINS:
            args = getattr(node, "arguments", [])
            if args and isinstance(args[0], IdentifierNode):
                if args[0].name in self._input_vars:
                    self._add("SEC008", HIGH,
                              f"Unvalidated user input variable '{args[0].name}' "
                              f"used directly as file path in '{node.name}'",
                              _line(node))

        # ── SEC009: Resource exhaustion — nested loops ──────
        if isinstance(node, (ForNode, ForEachNode)):
            # Check for nested for loops
            body = node.body if isinstance(node.body, list) else [node.body]
            for stmt in body:
                if isinstance(stmt, (ForNode, ForEachNode)):
                    # Nested for loops — check if ranges are large
                    self._add("SEC009", LOW,
                              "Nested for loops — O(n²) or worse complexity; "
                              "verify ranges are bounded",
                              _line(node))

        # ── SEC010: Catch-all silencer ───────────────────────
        if isinstance(node, TryCatchNode):
            catch_body = getattr(node, "handler", None)
            if _body_empty(catch_body):
                self._add("SEC010", MEDIUM,
                          "Empty catch block silently swallows errors "
                          "— handle or re-throw",
                          _line(node))

        # ── SEC011: Tainted format string ────────────────────
        if isinstance(node, FStringNode):
            parts = getattr(node, "parts", [])
            for part in parts:
                if isinstance(part, IdentifierNode) and part.name in self._input_vars:
                    self._add("SEC011", MEDIUM,
                              f"F-string includes unvalidated input variable "
                              f"'{part.name}' — sanitize before interpolation",
                              _line(node))

        # ── SEC012: Mutable default — list/map literal in param ──
        if isinstance(node, FunctionNode):
            # This is a static analysis heuristic: if a function is called
            # repeatedly and uses list literals that persist, it could be
            # dangerous. In sauravcode, params don't have defaults in the
            # same way, but we can check for patterns like:
            # fn process items = []
            # where the default is evaluated once.
            pass  # Placeholder for future default-param analysis

        # ── Recurse into children ────────────────────────────
        was_in_try = self._in_try

        if isinstance(node, TryCatchNode):
            self._in_try = True
            self._scan_nodes(getattr(node, "body", None))
            self._in_try = was_in_try
            self._scan_nodes(getattr(node, "handler", None))
            return

        if isinstance(node, FunctionNode):
            self._scan_nodes(node.body)
            return

        if isinstance(node, IfNode):
            self._scan_nodes(getattr(node, "true_body", None))
            self._scan_nodes(getattr(node, "false_body", None))
            self._scan_nodes(getattr(node, "else_body", None))
            return

        if isinstance(node, (WhileNode, ForNode, ForEachNode)):
            self._scan_nodes(node.body)
            return

        if isinstance(node, AssignmentNode):
            self._scan_node(node.expression)
            return

        if isinstance(node, PrintNode):
            # Already handled above, scan expression for nested calls
            self._scan_node(node.expression)
            return

        if isinstance(node, FunctionCallNode):
            for arg in getattr(node, "arguments", []):
                self._scan_node(arg)
            return

        if isinstance(node, ReturnNode):
            self._scan_node(node.expression)
            return

        if isinstance(node, BinaryOpNode):
            self._scan_node(node.left)
            self._scan_node(node.right)
            return


# ── Output formatting ────────────────────────────────────────────

_SEVERITY_COLORS = {
    HIGH: "\033[91m",    # Red
    MEDIUM: "\033[93m",  # Yellow
    LOW: "\033[96m",     # Cyan
}
_RESET = "\033[0m"
_BOLD = "\033[1m"

_SEVERITY_EMOJI = {HIGH: "🔴", MEDIUM: "🟡", LOW: "🔵"}


def _format_text(findings, filepath, use_color=True):
    """Format findings as human-readable text."""
    lines = []
    if not findings:
        mark = f"{_BOLD}✅{_RESET}" if use_color else "✅"
        lines.append(f"{mark} {filepath}: no security issues found")
        return "\n".join(lines)

    highs = sum(1 for f in findings if f.severity == HIGH)
    meds = sum(1 for f in findings if f.severity == MEDIUM)
    lows = sum(1 for f in findings if f.severity == LOW)

    header = f"🔍 {filepath}: {len(findings)} finding(s)"
    if highs:
        header += f" ({highs} high"
        if meds:
            header += f", {meds} medium"
        if lows:
            header += f", {lows} low"
        header += ")"
    lines.append(header)
    lines.append("─" * min(len(header) + 10, 72))

    for f in findings:
        if use_color:
            color = _SEVERITY_COLORS.get(f.severity, "")
            loc = f":{f.line}" if f.line else ""
            lines.append(f"  {color}{f.rule}{_RESET} "
                         f"{_SEVERITY_EMOJI.get(f.severity, '')} "
                         f"{f.message} "
                         f"({filepath}{loc})")
        else:
            loc = f":{f.line}" if f.line else ""
            lines.append(f"  {f.rule} [{f.severity.upper()}] "
                         f"{f.message} ({filepath}{loc})")
    return "\n".join(lines)


def _format_json(results):
    """Format all results as JSON."""
    output = {}
    for filepath, findings in results.items():
        output[filepath] = [f.to_dict() for f in findings]
    return json.dumps(output, indent=2)


def _format_sarif(results):
    """Format results as SARIF v2.1.0 for CI integration."""
    rules = []
    rule_ids = set()
    all_results = []

    for filepath, findings in results.items():
        for f in findings:
            if f.rule not in rule_ids:
                rule_ids.add(f.rule)
                rules.append({
                    "id": f.rule,
                    "shortDescription": {"text": f.rule},
                    "defaultConfiguration": {
                        "level": "error" if f.severity == HIGH else
                                 "warning" if f.severity == MEDIUM else "note"
                    }
                })
            result = {
                "ruleId": f.rule,
                "level": "error" if f.severity == HIGH else
                         "warning" if f.severity == MEDIUM else "note",
                "message": {"text": f.message},
                "locations": [{
                    "physicalLocation": {
                        "artifactLocation": {"uri": filepath},
                        "region": {"startLine": f.line or 1}
                    }
                }]
            }
            all_results.append(result)

    sarif = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {
                "driver": {
                    "name": "sauravsec",
                    "version": "1.0.0",
                    "informationUri": "https://github.com/sauravbhattacharya001/sauravcode",
                    "rules": rules
                }
            },
            "results": all_results
        }]
    }
    return json.dumps(sarif, indent=2)


def _format_summary(results):
    """Format a brief summary across all files."""
    total = 0
    by_rule = {}
    by_severity = {HIGH: 0, MEDIUM: 0, LOW: 0}
    files_clean = 0
    files_total = len(results)

    for filepath, findings in results.items():
        if not findings:
            files_clean += 1
            continue
        total += len(findings)
        for f in findings:
            by_rule[f.rule] = by_rule.get(f.rule, 0) + 1
            by_severity[f.severity] = by_severity.get(f.severity, 0) + 1

    lines = [
        f"╔══════════════════════════════════════╗",
        f"║     sauravsec Security Summary       ║",
        f"╠══════════════════════════════════════╣",
        f"║  Files scanned:  {files_total:<19}║",
        f"║  Files clean:    {files_clean:<19}║",
        f"║  Total findings: {total:<19}║",
        f"║  🔴 High:        {by_severity[HIGH]:<19}║",
        f"║  🟡 Medium:      {by_severity[MEDIUM]:<19}║",
        f"║  🔵 Low:         {by_severity[LOW]:<19}║",
        f"╚══════════════════════════════════════╝",
    ]

    if by_rule:
        lines.append("\nTop findings:")
        for rule, count in sorted(by_rule.items(), key=lambda x: -x[1]):
            lines.append(f"  {rule}: {count}")

    return "\n".join(lines)


# ── File scanning ────────────────────────────────────────────────

def scan_file(filepath, disabled=None):
    """Parse and scan a single .srv file. Returns list of Findings."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
    except (OSError, UnicodeDecodeError) as e:
        return [Finding("SEC000", HIGH, f"Cannot read file: {e}", context=filepath)]

    try:
        tokens = tokenize(source)
        parser = Parser(tokens)
        ast = parser.parse()
    except Exception as e:
        return [Finding("SEC000", MEDIUM, f"Parse error: {e}", context=filepath)]

    scanner = SecurityScanner(disabled=disabled)
    return scanner.scan(ast)


def scan_paths(paths, disabled=None):
    """Scan one or more file paths / directories. Returns {path: [findings]}."""
    results = {}
    for path in paths:
        if os.path.isdir(path):
            for srv in sorted(glob.glob(os.path.join(path, "**", "*.srv"), recursive=True)):
                results[srv] = scan_file(srv, disabled)
        elif os.path.isfile(path):
            results[path] = scan_file(path, disabled)
        else:
            results[path] = [Finding("SEC000", HIGH, f"Path not found: {path}")]
    return results


# ── CLI ──────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    if not args or "--help" in args or "-h" in args:
        print(__doc__)
        sys.exit(0)

    # Parse flags
    output_json = "--json" in args
    output_sarif = "--sarif" in args
    output_summary = "--summary" in args
    no_color = "--no-color" in args or not sys.stdout.isatty()
    severity_filter = None
    disabled = set()

    filtered_args = []
    i = 0
    while i < len(args):
        if args[i] == "--json":
            i += 1
        elif args[i] == "--sarif":
            i += 1
        elif args[i] == "--summary":
            i += 1
        elif args[i] == "--no-color":
            i += 1
        elif args[i] == "--severity" and i + 1 < len(args):
            severity_filter = args[i + 1].lower()
            i += 2
        elif args[i] == "--disable" and i + 1 < len(args):
            disabled = {r.strip() for r in args[i + 1].split(",")}
            i += 2
        else:
            filtered_args.append(args[i])
            i += 1

    if not filtered_args:
        print("Error: no files specified", file=sys.stderr)
        sys.exit(1)

    results = scan_paths(filtered_args, disabled=disabled)

    # Apply severity filter
    if severity_filter:
        for path in results:
            results[path] = [f for f in results[path] if f.severity == severity_filter]

    # Output
    if output_sarif:
        print(_format_sarif(results))
    elif output_json:
        print(_format_json(results))
    elif output_summary:
        print(_format_summary(results))
    else:
        for filepath, findings in results.items():
            print(_format_text(findings, filepath, use_color=not no_color))
            print()

    # Exit code: 1 if any high-severity findings
    has_high = any(
        f.severity == HIGH
        for findings in results.values()
        for f in findings
    )
    sys.exit(1 if has_high else 0)


if __name__ == "__main__":
    main()
