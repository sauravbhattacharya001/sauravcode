#!/usr/bin/env python3
"""sauravtype - Static type inference and checking for sauravcode (.srv files).

Analyzes sauravcode programs to infer types from usage patterns and detect
potential type mismatches without requiring type annotations. Useful for
catching bugs early in dynamically typed code.

Usage:
    python sauravtype.py file.srv              # Check a file
    python sauravtype.py file.srv --verbose    # Show all inferred types
    python sauravtype.py file.srv --json       # JSON output
    python sauravtype.py file.srv --summary    # Type summary only
    python sauravtype.py dir/                  # Check all .srv files

Type Warnings:
    T001  Type mismatch in binary operation (e.g. string + int)
    T002  Type mismatch in comparison (incompatible types)
    T003  Function called with wrong argument count
    T004  Index operation on non-list/non-map type
    T005  Arithmetic operation on non-numeric type
    T006  Boolean operation on non-boolean type
    T007  Iteration over non-iterable type
    T008  Return type inconsistency (function returns different types)
    T009  Condition is not boolean-compatible
    T010  Append to non-list type
    T011  String operation on non-string type
    T012  Map key access on non-map type
"""

import sys
import os
import json
import glob
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from enum import Enum

# Import the parser from the interpreter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from saurav import (
    tokenize, Parser,
    AssignmentNode, BinaryOpNode, BoolNode, CompareNode,
    ForNode, ForEachNode, FStringNode, FunctionCallNode,
    FunctionNode, IdentifierNode, IfNode, IndexNode,
    LambdaNode, ListNode, ListComprehensionNode, LogicalNode,
    MapNode, MatchNode, NumberNode, PipeNode, PrintNode,
    ReturnNode, SliceNode, StringNode, TernaryNode, UnaryOpNode,
    WhileNode, AppendNode, PopNode, LenNode, IndexedAssignmentNode,
    TryCatchNode, ThrowNode, YieldNode, ImportNode, EnumNode,
    EnumAccessNode, CaseNode, BreakNode, ContinueNode, ASTNode,
)


# ── Type Representation ──────────────────────────────────────────────


class SrvType(Enum):
    INT = "int"
    FLOAT = "float"
    NUMBER = "number"       # int or float (unresolved)
    STRING = "string"
    BOOL = "bool"
    LIST = "list"
    MAP = "map"
    FUNCTION = "function"
    LAMBDA = "lambda"
    GENERATOR = "generator"
    ENUM = "enum"
    NONE = "none"
    ANY = "any"             # unknown / mixed
    ERROR = "error"         # type error detected


NUMERIC_TYPES = {SrvType.INT, SrvType.FLOAT, SrvType.NUMBER}
ITERABLE_TYPES = {SrvType.LIST, SrvType.STRING, SrvType.MAP, SrvType.GENERATOR}
BOOLEAN_COMPATIBLE = {SrvType.BOOL, SrvType.INT, SrvType.NUMBER, SrvType.ANY}


# ── Diagnostic ────────────────────────────────────────────────────────


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class TypeDiagnostic:
    code: str               # T001, T002, etc.
    message: str
    severity: Severity
    line: int = 0
    column: int = 0
    inferred_type: str = ""
    expected_type: str = ""

    def __str__(self):
        loc = f":{self.line}" if self.line else ""
        return f"[{self.code}] {self.severity.value}{loc}: {self.message}"

    def to_dict(self):
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
            "line": self.line,
            "inferred_type": self.inferred_type,
            "expected_type": self.expected_type,
        }


# ── Type Environment ─────────────────────────────────────────────────


@dataclass
class FunctionSig:
    name: str
    param_count: int
    return_types: Set[SrvType] = field(default_factory=set)
    is_generator: bool = False


class TypeEnv:
    """Scoped type environment for tracking variable and function types."""

    def __init__(self, parent: Optional["TypeEnv"] = None):
        self.parent = parent
        self.bindings: Dict[str, Set[SrvType]] = {}
        self.functions: Dict[str, FunctionSig] = {}

    def bind(self, name: str, typ: SrvType):
        if name not in self.bindings:
            self.bindings[name] = set()
        self.bindings[name].add(typ)

    def lookup(self, name: str) -> Set[SrvType]:
        if name in self.bindings:
            return self.bindings[name]
        if self.parent:
            return self.parent.lookup(name)
        return set()

    def define_function(self, name: str, param_count: int):
        self.functions[name] = FunctionSig(name=name, param_count=param_count)

    def lookup_function(self, name: str) -> Optional[FunctionSig]:
        if name in self.functions:
            return self.functions[name]
        if self.parent:
            return self.parent.lookup_function(name)
        return None

    def child(self) -> "TypeEnv":
        return TypeEnv(parent=self)

    def all_bindings(self) -> Dict[str, Set[SrvType]]:
        result = {}
        if self.parent:
            result.update(self.parent.all_bindings())
        result.update(self.bindings)
        return result


# ── Built-in Function Signatures ─────────────────────────────────────


# Returns: (param_count or -1 for variadic, return_type)
BUILTIN_SIGS: Dict[str, Tuple[int, SrvType]] = {
    # String functions
    "upper": (1, SrvType.STRING),
    "lower": (1, SrvType.STRING),
    "trim": (1, SrvType.STRING),
    "ltrim": (1, SrvType.STRING),
    "rtrim": (1, SrvType.STRING),
    "replace": (3, SrvType.STRING),
    "split": (2, SrvType.LIST),
    "join": (2, SrvType.STRING),
    "contains": (2, SrvType.BOOL),
    "starts_with": (2, SrvType.BOOL),
    "ends_with": (2, SrvType.BOOL),
    "substring": (3, SrvType.STRING),
    "char_at": (2, SrvType.STRING),
    "index_of": (2, SrvType.INT),
    "reverse": (1, SrvType.ANY),
    "repeat": (2, SrvType.STRING),
    "pad_left": (3, SrvType.STRING),
    "pad_right": (3, SrvType.STRING),
    # Math functions
    "sqrt": (1, SrvType.FLOAT),
    "abs": (1, SrvType.NUMBER),
    "floor": (1, SrvType.INT),
    "ceil": (1, SrvType.INT),
    "round": (2, SrvType.FLOAT),
    "power": (2, SrvType.NUMBER),
    "min": (2, SrvType.NUMBER),
    "max": (2, SrvType.NUMBER),
    "random": (0, SrvType.FLOAT),
    "random_int": (2, SrvType.INT),
    # Type functions
    "type_of": (1, SrvType.STRING),
    "str": (1, SrvType.STRING),
    "int": (1, SrvType.INT),
    "float": (1, SrvType.FLOAT),
    "bool": (1, SrvType.BOOL),
    "is_number": (1, SrvType.BOOL),
    "is_string": (1, SrvType.BOOL),
    "is_bool": (1, SrvType.BOOL),
    "is_list": (1, SrvType.BOOL),
    "is_map": (1, SrvType.BOOL),
    # List functions
    "len": (1, SrvType.INT),
    "sort": (1, SrvType.LIST),
    "range": (2, SrvType.LIST),
    "map": (2, SrvType.LIST),
    "filter": (2, SrvType.LIST),
    "reduce": (3, SrvType.ANY),
    "zip": (2, SrvType.LIST),
    "enumerate": (1, SrvType.LIST),
    "flatten": (1, SrvType.LIST),
    "sum": (1, SrvType.NUMBER),
    # Map functions
    "keys": (1, SrvType.LIST),
    "values": (1, SrvType.LIST),
    "has_key": (2, SrvType.BOOL),
    "merge": (2, SrvType.MAP),
    # Stats
    "mean": (1, SrvType.FLOAT),
    "median": (1, SrvType.FLOAT),
    "stdev": (1, SrvType.FLOAT),
    "variance": (1, SrvType.FLOAT),
    # I/O
    "print": (-1, SrvType.NONE),
    "input": (1, SrvType.STRING),
    "read_file": (1, SrvType.STRING),
    "write_file": (2, SrvType.NONE),
    # Regex
    "regex_match": (2, SrvType.BOOL),
    "regex_replace": (3, SrvType.STRING),
    "regex_find": (2, SrvType.LIST),
    # JSON
    "json_parse": (1, SrvType.ANY),
    "json_stringify": (1, SrvType.STRING),
    "json_pretty": (1, SrvType.STRING),
    # Date/Time
    "now": (0, SrvType.STRING),
    "date_add": (3, SrvType.STRING),
    "date_diff": (3, SrvType.NUMBER),
    "date_format": (2, SrvType.STRING),
    # Hashing/Encoding
    "sha256": (1, SrvType.STRING),
    "md5": (1, SrvType.STRING),
    "base64_encode": (1, SrvType.STRING),
    "base64_decode": (1, SrvType.STRING),
    # Generator
    "next": (1, SrvType.ANY),
}


# ── Type Checker ─────────────────────────────────────────────────────


class TypeChecker:
    """Walk the AST and infer/check types."""

    def __init__(self):
        self.diagnostics: List[TypeDiagnostic] = []
        self.env = TypeEnv()

    def _warn(self, code: str, message: str, severity: Severity = Severity.WARNING,
              line: int = 0, inferred: str = "", expected: str = ""):
        self.diagnostics.append(TypeDiagnostic(
            code=code, message=message, severity=severity,
            line=line, inferred_type=inferred, expected_type=expected,
        ))

    def _get_line(self, node) -> int:
        if hasattr(node, "line"):
            return getattr(node, "line", 0)
        return 0

    def check(self, ast: list) -> List[TypeDiagnostic]:
        """Run type checking on a parsed AST."""
        self.diagnostics = []
        self.env = TypeEnv()

        # First pass: register all function definitions
        for node in ast:
            if isinstance(node, FunctionNode):
                self.env.define_function(node.name, len(node.params))
            elif isinstance(node, EnumNode):
                self.env.bind(node.name, SrvType.ENUM)

        # Second pass: infer and check types
        for node in ast:
            self._check_node(node, self.env)

        return self.diagnostics

    def _infer(self, node, env: TypeEnv) -> SrvType:
        """Infer the type of an expression node."""
        if node is None:
            return SrvType.NONE

        if isinstance(node, NumberNode):
            val = node.value
            if isinstance(val, float) and val == int(val) and not str(val).startswith("0."):
                return SrvType.INT
            return SrvType.FLOAT if isinstance(val, float) and val != int(val) else SrvType.INT

        if isinstance(node, StringNode):
            return SrvType.STRING

        if isinstance(node, FStringNode):
            return SrvType.STRING

        if isinstance(node, BoolNode):
            return SrvType.BOOL

        if isinstance(node, ListNode):
            return SrvType.LIST

        if isinstance(node, ListComprehensionNode):
            return SrvType.LIST

        if isinstance(node, MapNode):
            return SrvType.MAP

        if isinstance(node, LambdaNode):
            return SrvType.LAMBDA

        if isinstance(node, IdentifierNode):
            types = env.lookup(node.name)
            if types:
                if len(types) == 1:
                    return next(iter(types))
                return SrvType.ANY  # Multiple possible types
            # Check if it's a function name
            if env.lookup_function(node.name):
                return SrvType.FUNCTION
            return SrvType.ANY

        if isinstance(node, BinaryOpNode):
            left_t = self._infer(node.left, env)
            right_t = self._infer(node.right, env)
            return self._check_binary_op(node.operator, left_t, right_t, self._get_line(node))

        if isinstance(node, CompareNode):
            left_t = self._infer(node.left, env)
            right_t = self._infer(node.right, env)
            self._check_comparison(node.operator, left_t, right_t, self._get_line(node))
            return SrvType.BOOL

        if isinstance(node, LogicalNode):
            self._infer(node.left, env)
            self._infer(node.right, env)
            return SrvType.BOOL

        if isinstance(node, UnaryOpNode):
            operand_t = self._infer(node.operatorerand, env)
            if node.operator == "-" and operand_t not in NUMERIC_TYPES and operand_t != SrvType.ANY:
                self._warn("T005", f"Negation on non-numeric type '{operand_t.value}'",
                           line=self._get_line(node), inferred=operand_t.value, expected="number")
            if node.operator == "not":
                return SrvType.BOOL
            return operand_t

        if isinstance(node, TernaryNode):
            cond_t = self._infer(node.condition, env)
            if cond_t not in BOOLEAN_COMPATIBLE and cond_t != SrvType.ANY:
                self._warn("T009", f"Ternary condition has type '{cond_t.value}', expected boolean",
                           Severity.WARNING, self._get_line(node), cond_t.value, "bool")
            true_t = self._infer(node.true_expr, env)
            false_t = self._infer(node.false_expr, env)
            if true_t == false_t:
                return true_t
            return SrvType.ANY

        if isinstance(node, IndexNode):
            base_t = self._infer(node.obj, env)
            if base_t not in {SrvType.LIST, SrvType.STRING, SrvType.MAP, SrvType.ANY}:
                self._warn("T004", f"Index operation on type '{base_t.value}' (expected list, string, or map)",
                           line=self._get_line(node), inferred=base_t.value, expected="list|string|map")
            return SrvType.ANY

        if isinstance(node, SliceNode):
            return SrvType.LIST

        if isinstance(node, FunctionCallNode):
            return self._check_call(node, env)

        if isinstance(node, PipeNode):
            # Pipe result type depends on the last function in the chain
            self._infer(node.left, env)
            right_t = self._infer(node.right, env)
            if isinstance(node.right, IdentifierNode):
                sig = BUILTIN_SIGS.get(node.right.name)
                if sig:
                    return sig[1]
            return SrvType.ANY

        if isinstance(node, LenNode):
            return SrvType.INT

        if isinstance(node, EnumAccessNode):
            return SrvType.ENUM

        return SrvType.ANY

    def _check_binary_op(self, op: str, left: SrvType, right: SrvType, line: int) -> SrvType:
        """Check and infer type for binary operations."""
        if left == SrvType.ANY or right == SrvType.ANY:
            return SrvType.ANY

        # String concatenation
        if op == "+":
            if left == SrvType.STRING or right == SrvType.STRING:
                if left == SrvType.STRING and right == SrvType.STRING:
                    return SrvType.STRING
                # Mixing string + number is a type error in many contexts
                if left in NUMERIC_TYPES or right in NUMERIC_TYPES:
                    self._warn("T001",
                               f"String + number concatenation: '{left.value}' + '{right.value}' "
                               "(use str() to convert explicitly)",
                               Severity.WARNING, line, f"{left.value} + {right.value}", "string + string")
                    return SrvType.STRING
            if left == SrvType.LIST and right == SrvType.LIST:
                return SrvType.LIST

        # Arithmetic
        if op in {"+", "-", "*", "/", "%", "**"}:
            if left in NUMERIC_TYPES and right in NUMERIC_TYPES:
                if op == "/" or left == SrvType.FLOAT or right == SrvType.FLOAT:
                    return SrvType.FLOAT
                return SrvType.INT
            if left not in NUMERIC_TYPES and left != SrvType.STRING:
                self._warn("T005", f"Arithmetic '{op}' on non-numeric type '{left.value}'",
                           line=line, inferred=left.value, expected="number")
            if right not in NUMERIC_TYPES and right != SrvType.STRING:
                self._warn("T005", f"Arithmetic '{op}' on non-numeric type '{right.value}'",
                           line=line, inferred=right.value, expected="number")
            return SrvType.ANY

        # String repetition
        if op == "*":
            if left == SrvType.STRING and right in NUMERIC_TYPES:
                return SrvType.STRING
            if right == SrvType.STRING and left in NUMERIC_TYPES:
                return SrvType.STRING

        return SrvType.ANY

    def _check_comparison(self, op: str, left: SrvType, right: SrvType, line: int):
        """Check comparison operations for type compatibility."""
        if left == SrvType.ANY or right == SrvType.ANY:
            return

        # Ordering comparisons between incompatible types
        if op in {"<", ">", "<=", ">="}:
            if (left in NUMERIC_TYPES and right not in NUMERIC_TYPES) or \
               (right in NUMERIC_TYPES and left not in NUMERIC_TYPES):
                if left != SrvType.STRING and right != SrvType.STRING:
                    self._warn("T002",
                               f"Comparison '{op}' between '{left.value}' and '{right.value}'",
                               Severity.WARNING, line, f"{left.value} {op} {right.value}",
                               "comparable types")

    def _check_call(self, node: FunctionCallNode, env: TypeEnv) -> SrvType:
        """Check function call argument count and return type."""
        name = node.name
        arg_count = len(node.arguments)

        # Check built-in
        if name in BUILTIN_SIGS:
            expected_count, return_type = BUILTIN_SIGS[name]
            if expected_count >= 0 and arg_count != expected_count:
                self._warn("T003",
                           f"Built-in '{name}' expects {expected_count} argument(s), got {arg_count}",
                           Severity.ERROR, self._get_line(node),
                           str(arg_count), str(expected_count))
            # Infer arg types
            for arg in node.arguments:
                self._infer(arg, env)
            return return_type

        # Check user-defined function
        sig = env.lookup_function(name)
        if sig:
            if arg_count != sig.param_count:
                self._warn("T003",
                           f"Function '{name}' expects {sig.param_count} argument(s), got {arg_count}",
                           Severity.ERROR, self._get_line(node),
                           str(arg_count), str(sig.param_count))
            for arg in node.arguments:
                self._infer(arg, env)
            if sig.is_generator:
                return SrvType.GENERATOR
            if sig.return_types:
                if len(sig.return_types) == 1:
                    return next(iter(sig.return_types))
                return SrvType.ANY
            return SrvType.ANY

        # Unknown function — infer args anyway
        for arg in node.arguments:
            self._infer(arg, env)
        return SrvType.ANY

    def _check_node(self, node, env: TypeEnv):
        """Check a statement node and update the type environment."""
        if node is None:
            return

        if isinstance(node, AssignmentNode):
            val_type = self._infer(node.expression, env)
            env.bind(node.name, val_type)
            return

        if isinstance(node, IndexedAssignmentNode):
            base_types = env.lookup(node.name)
            if base_types and SrvType.LIST not in base_types and SrvType.MAP not in base_types and SrvType.ANY not in base_types:
                self._warn("T004",
                           f"Indexed assignment on '{node.name}' (expected list or map)",
                           line=self._get_line(node), expected="list|map")
            self._infer(node.index, env)
            self._infer(node.value, env)
            return

        if isinstance(node, PrintNode):
            self._infer(node.expression, env)
            return

        if isinstance(node, FunctionNode):
            child_env = env.child()
            for param in node.params:
                child_env.bind(param, SrvType.ANY)
            sig = env.lookup_function(node.name)

            has_yield = self._has_yield(node.body)
            if sig and has_yield:
                sig.is_generator = True

            for stmt in node.body:
                self._check_node(stmt, child_env)

            # Collect return types
            if sig:
                ret_types = self._collect_return_types(node.body, child_env)
                sig.return_types.update(ret_types)
                if len(ret_types) > 1 and SrvType.NONE in ret_types:
                    non_none = ret_types - {SrvType.NONE, SrvType.ANY}
                    if non_none:
                        self._warn("T008",
                                   f"Function '{node.name}' sometimes returns "
                                   f"{', '.join(t.value for t in non_none)} and sometimes returns nothing",
                                   Severity.INFO, self._get_line(node))
            return

        if isinstance(node, IfNode):
            cond_t = self._infer(node.condition, env)
            if cond_t not in BOOLEAN_COMPATIBLE and cond_t != SrvType.ANY:
                self._warn("T009", f"If condition has type '{cond_t.value}', expected boolean",
                           Severity.WARNING, self._get_line(node), cond_t.value, "bool")
            for stmt in node.body:
                self._check_node(stmt, env)
            for elif_cond, elif_body in (node.elif_chains or []):
                self._infer(elif_cond, env)
                for stmt in elif_body:
                    self._check_node(stmt, env)
            if node.else_body:
                for stmt in node.else_body:
                    self._check_node(stmt, env)
            return

        if isinstance(node, WhileNode):
            cond_t = self._infer(node.condition, env)
            if cond_t not in BOOLEAN_COMPATIBLE and cond_t != SrvType.ANY:
                self._warn("T009", f"While condition has type '{cond_t.value}', expected boolean",
                           Severity.WARNING, self._get_line(node), cond_t.value, "bool")
            for stmt in node.body:
                self._check_node(stmt, env)
            return

        if isinstance(node, ForNode):
            env.bind(node.var, SrvType.INT)
            self._infer(node.start, env)
            self._infer(node.end, env)
            for stmt in node.body:
                self._check_node(stmt, env)
            return

        if isinstance(node, ForEachNode):
            iter_t = self._infer(node.iterable, env)
            if iter_t not in ITERABLE_TYPES and iter_t != SrvType.ANY:
                self._warn("T007", f"For-each over non-iterable type '{iter_t.value}'",
                           line=self._get_line(node), inferred=iter_t.value, expected="list|string|map")
            env.bind(node.var, SrvType.ANY)
            for stmt in node.body:
                self._check_node(stmt, env)
            return

        if isinstance(node, ReturnNode):
            if node.expression:
                self._infer(node.expression, env)
            return

        if isinstance(node, AppendNode):
            list_types = env.lookup(node.list_name)
            if list_types and SrvType.LIST not in list_types and SrvType.ANY not in list_types:
                self._warn("T010", f"Append to non-list '{node.list_name}'",
                           line=self._get_line(node), expected="list")
            self._infer(node.value, env)
            return

        if isinstance(node, TryCatchNode):
            for stmt in node.body:
                self._check_node(stmt, env)
            if node.error_var:
                env.bind(node.error_var, SrvType.STRING)
            for stmt in node.handler:
                self._check_node(stmt, env)
            return

        if isinstance(node, ThrowNode):
            self._infer(node.expression, env)
            return

        if isinstance(node, MatchNode):
            self._infer(node.expression, env)
            for case in node.cases:
                if isinstance(case, CaseNode):
                    for stmt in case.body:
                        self._check_node(stmt, env)
            return

        if isinstance(node, EnumNode):
            env.bind(node.name, SrvType.ENUM)
            return

        if isinstance(node, ImportNode):
            return

        if isinstance(node, (BreakNode, ContinueNode)):
            return

        # Expression statements
        if isinstance(node, FunctionCallNode):
            self._check_call(node, env)
            return

        # Fallback: try to infer
        self._infer(node, env)

    def _has_yield(self, body: list) -> bool:
        """Check if a function body contains yield statements."""
        for node in body:
            if isinstance(node, YieldNode):
                return True
            if hasattr(node, "body") and isinstance(getattr(node, "body"), list):
                if self._has_yield(getattr(node, "body")):
                    return True
            if hasattr(node, "true_body"):
                if self._has_yield(node.body):
                    return True
            if hasattr(node, "false_body") and node.else_body:
                if self._has_yield(node.else_body):
                    return True
        return False

    def _collect_return_types(self, body: list, env: TypeEnv) -> Set[SrvType]:
        """Collect all return types from a function body."""
        types = set()
        has_return = False
        for node in body:
            if isinstance(node, ReturnNode):
                has_return = True
                if node.expression:
                    types.add(self._infer(node.expression, env))
                else:
                    types.add(SrvType.NONE)
            # Recurse into if/else
            if isinstance(node, IfNode):
                types.update(self._collect_return_types(node.body, env))
                if node.else_body:
                    types.update(self._collect_return_types(node.else_body, env))
                for _, elif_body in (node.elif_chains or []):
                    types.update(self._collect_return_types(elif_body, env))
            if isinstance(node, WhileNode):
                types.update(self._collect_return_types(node.body, env))
        if not has_return and not types:
            types.add(SrvType.NONE)
        return types

    def get_inferred_types(self) -> Dict[str, List[str]]:
        """Get all inferred variable types after checking."""
        result = {}
        for name, types in self.env.all_bindings().items():
            result[name] = sorted(t.value for t in types)
        return result

    def get_function_sigs(self) -> Dict[str, dict]:
        """Get function signatures with inferred return types."""
        result = {}
        for name, sig in self.env.functions.items():
            result[name] = {
                "params": sig.param_count,
                "returns": sorted(t.value for t in sig.return_types) if sig.return_types else ["any"],
                "is_generator": sig.is_generator,
            }
        return result


# ── Report Generation ────────────────────────────────────────────────


def format_report(filepath: str, diagnostics: List[TypeDiagnostic],
                  checker: TypeChecker, verbose: bool = False) -> str:
    """Format a human-readable type checking report."""
    lines = []
    lines.append(f"\n{'='*60}")
    lines.append(f"  Type Check: {os.path.basename(filepath)}")
    lines.append(f"{'='*60}")

    errors = [d for d in diagnostics if d.severity == Severity.ERROR]
    warnings = [d for d in diagnostics if d.severity == Severity.WARNING]
    infos = [d for d in diagnostics if d.severity == Severity.INFO]

    if not diagnostics:
        lines.append("  ✓ No type issues found")
    else:
        lines.append(f"  Found: {len(errors)} error(s), {len(warnings)} warning(s), {len(infos)} info(s)")
        lines.append("")

        for d in diagnostics:
            icon = "✗" if d.severity == Severity.ERROR else "⚠" if d.severity == Severity.WARNING else "ℹ"
            loc = f" (line {d.line})" if d.line else ""
            lines.append(f"  {icon} [{d.code}]{loc}: {d.message}")

    if verbose:
        lines.append("")
        lines.append("  Inferred Variable Types:")
        lines.append("  " + "-" * 40)
        for name, types in sorted(checker.get_inferred_types().items()):
            lines.append(f"    {name}: {' | '.join(types)}")

        sigs = checker.get_function_sigs()
        if sigs:
            lines.append("")
            lines.append("  Function Signatures:")
            lines.append("  " + "-" * 40)
            for name, sig in sorted(sigs.items()):
                gen = " (generator)" if sig["is_generator"] else ""
                lines.append(f"    {name}({sig['params']} params) -> {' | '.join(sig['returns'])}{gen}")

    lines.append(f"{'='*60}")
    return "\n".join(lines)


def format_summary(filepath: str, checker: TypeChecker) -> str:
    """Format a brief type summary."""
    lines = [f"\nType Summary: {os.path.basename(filepath)}"]
    lines.append("-" * 40)
    types = checker.get_inferred_types()
    lines.append(f"Variables: {len(types)}")
    lines.append(f"Functions: {len(checker.get_function_sigs())}")
    for name, tlist in sorted(types.items()):
        lines.append(f"  {name}: {' | '.join(tlist)}")
    return "\n".join(lines)


# ── File Processing ──────────────────────────────────────────────────


def check_file(filepath: str) -> Tuple[List[TypeDiagnostic], TypeChecker]:
    """Parse and type-check a .srv file."""
    with open(filepath, "r", encoding="utf-8") as f:
        source = f.read()

    tokens = tokenize(source)
    parser = Parser(tokens)
    ast = parser.parse()

    checker = TypeChecker()
    diagnostics = checker.check(ast)
    return diagnostics, checker


# ── CLI Entry Point ──────────────────────────────────────────────────


def main():
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    args = sys.argv[1:]

    if not args or "--help" in args or "-h" in args:
        print(__doc__)
        sys.exit(0)

    verbose = "--verbose" in args or "-v" in args
    json_output = "--json" in args
    summary_only = "--summary" in args

    # Filter out flags
    files = [a for a in args if not a.startswith("-")]

    # Expand directories
    expanded = []
    for f in files:
        if os.path.isdir(f):
            expanded.extend(glob.glob(os.path.join(f, "**", "*.srv"), recursive=True))
        else:
            expanded.append(f)

    if not expanded:
        print("No .srv files found.")
        sys.exit(1)

    all_diagnostics = {}
    all_checkers = {}
    total_errors = 0

    for filepath in expanded:
        if not os.path.exists(filepath):
            print(f"File not found: {filepath}", file=sys.stderr)
            continue

        try:
            diagnostics, checker = check_file(filepath)
            all_diagnostics[filepath] = diagnostics
            all_checkers[filepath] = checker
            total_errors += sum(1 for d in diagnostics if d.severity == Severity.ERROR)
        except Exception as e:
            print(f"Parse error in {filepath}: {e}", file=sys.stderr)

    if json_output:
        output = {}
        for filepath, diags in all_diagnostics.items():
            checker = all_checkers[filepath]
            output[filepath] = {
                "diagnostics": [d.to_dict() for d in diags],
                "variables": checker.get_inferred_types(),
                "functions": checker.get_function_sigs(),
            }
        print(json.dumps(output, indent=2))
    elif summary_only:
        for filepath, checker in all_checkers.items():
            print(format_summary(filepath, checker))
    else:
        for filepath, diags in all_diagnostics.items():
            checker = all_checkers[filepath]
            print(format_report(filepath, diags, checker, verbose=verbose))

    if total_errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
