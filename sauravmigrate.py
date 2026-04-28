#!/usr/bin/env python3
"""sauravmigrate.py — Migrate Python scripts to sauravcode (.srv).

Converts simple Python code into idiomatic sauravcode by parsing
the Python AST and emitting equivalent .srv syntax.

Usage:
    python sauravmigrate.py script.py                # Print .srv to stdout
    python sauravmigrate.py script.py -o output.srv  # Write to file
    python sauravmigrate.py script.py --preview       # Side-by-side diff
    python sauravmigrate.py src/ --recursive          # Convert directory

Supported Python constructs:
    - Variables and assignments
    - Arithmetic, comparison, logical operators
    - print() calls
    - if/elif/else
    - while loops
    - for loops (range-based and iterable)
    - Function definitions and calls
    - Return, break, continue
    - Try/except → try/catch
    - Raise → throw
    - Lists, dicts, indexing
    - F-strings
    - Comments (preserved where possible)
    - Lambda expressions
    - List comprehensions (simple cases)

Unsupported (skipped with warnings):
    - Classes (partial — no inheritance)
    - Decorators
    - With statements
    - Async/await
    - Star args, kwargs
    - Multiple assignment / unpacking
    - Complex comprehensions (nested)
"""

import ast
import sys
import os
import argparse
from pathlib import Path


class MigrationWarning:
    """Tracks constructs that couldn't be migrated."""
    def __init__(self):
        self.warnings = []

    def add(self, lineno, msg):
        self.warnings.append((lineno, msg))

    def report(self):
        if not self.warnings:
            return ""
        lines = ["# -- Migration Warnings --"]
        for lineno, msg in sorted(self.warnings):
            lines.append(f"# Line {lineno}: {msg}")
        return "\n".join(lines) + "\n\n"


class PythonToSrv(ast.NodeVisitor):
    """AST visitor that emits sauravcode (.srv) source."""

    def __init__(self, source_lines=None):
        self.indent = 0
        self.output = []
        self.warnings = MigrationWarning()
        self.source_lines = source_lines or []

    def emit(self, line=""):
        prefix = "    " * self.indent
        self.output.append(prefix + line if line else "")

    def result(self):
        warning_header = self.warnings.report()
        body = "\n".join(self.output)
        # Clean up excessive blank lines
        while "\n\n\n" in body:
            body = body.replace("\n\n\n", "\n\n")
        return warning_header + body.strip() + "\n"

    # ── Module ──

    def visit_Module(self, node):
        self._emit_body(node.body)

    def _emit_body(self, stmts):
        for stmt in stmts:
            self.visit(stmt)

    # ── Comments (via source lines) ──

    def _emit_leading_comments(self, node):
        """Emit comment lines that appear before this node."""
        # This is best-effort since AST drops comments
        pass

    # ── Assignments ──

    def visit_Assign(self, node):
        if len(node.targets) != 1:
            self.warnings.add(node.lineno, "Multiple assignment targets not supported")
            return
        target = self._expr(node.targets[0])
        value = self._expr(node.value)
        self.emit(f"{target} = {value}")

    def visit_AugAssign(self, node):
        target = self._expr(node.target)
        value = self._expr(node.value)
        # sauravcode doesn't have +=, expand it
        op = self._binop_symbol(node.op)
        self.emit(f"{target} = {target} {op} {value}")

    def visit_AnnAssign(self, node):
        # Type annotations — ignore annotation, keep assignment
        if node.value is not None:
            target = self._expr(node.target)
            value = self._expr(node.value)
            self.emit(f"{target} = {value}")

    # ── Expressions as statements ──

    def visit_Expr(self, node):
        # Check for standalone string (docstring) — emit as comment
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for line in node.value.value.strip().split("\n"):
                self.emit(f"# {line}")
            return
        expr = self._expr(node.value)
        self.emit(expr)

    # ── Print ──

    def _is_print_call(self, node):
        return (isinstance(node, ast.Call) and
                isinstance(node.func, ast.Name) and
                node.func.id == "print")

    # ── Function definitions ──

    def visit_FunctionDef(self, node):
        params = []
        for arg in node.args.args:
            if arg.arg == "self":
                continue
            params.append(arg.arg)

        if node.args.vararg or node.args.kwarg or node.args.kwonlyargs:
            self.warnings.add(node.lineno, f"*args/**kwargs in '{node.name}' not supported")

        if node.decorator_list:
            self.warnings.add(node.lineno, f"Decorators on '{node.name}' skipped")

        param_str = " ".join(params)
        if param_str:
            self.emit(f"function {node.name} {param_str}")
        else:
            self.emit(f"function {node.name}")
        self.indent += 1
        self._emit_body(node.body)
        self.indent -= 1
        self.emit("")

    visit_AsyncFunctionDef = None  # Will trigger generic_visit warning

    # ── Return ──

    def visit_Return(self, node):
        if node.value is None:
            self.emit("return 0")
        else:
            self.emit(f"return {self._expr(node.value)}")

    # ── If/elif/else ──

    def visit_If(self, node):
        cond = self._expr(node.test)
        self.emit(f"if {cond}")
        self.indent += 1
        self._emit_body(node.body)
        self.indent -= 1

        orelse = node.orelse
        while orelse:
            if len(orelse) == 1 and isinstance(orelse[0], ast.If):
                elif_node = orelse[0]
                cond = self._expr(elif_node.test)
                self.emit(f"else if {cond}")
                self.indent += 1
                self._emit_body(elif_node.body)
                self.indent -= 1
                orelse = elif_node.orelse
            else:
                self.emit("else")
                self.indent += 1
                self._emit_body(orelse)
                self.indent -= 1
                break

    # ── While ──

    def visit_While(self, node):
        cond = self._expr(node.test)
        self.emit(f"while {cond}")
        self.indent += 1
        self._emit_body(node.body)
        self.indent -= 1
        if node.orelse:
            self.warnings.add(node.lineno, "while/else not supported, else branch skipped")

    # ── For ──

    @staticmethod
    def _literal_int_value(node):
        """Return the int value of a literal AST expression, or None.

        Handles plain `ast.Constant` integer literals and `ast.UnaryOp(USub, ...)`
        wrapping a constant (i.e. negative literals like ``-1``), which is how
        the AST represents them.
        """
        if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
            return node.value
        if (isinstance(node, ast.UnaryOp)
                and isinstance(node.op, ast.USub)
                and isinstance(node.operand, ast.Constant)
                and isinstance(node.operand.value, int)
                and not isinstance(node.operand.value, bool)):
            return -node.operand.value
        return None

    def _emit_range_with_step(self, node, target, args):
        """Migrate ``for target in range(start, stop, step):`` as a while-loop.

        sauravcode's native ``for`` loop only takes start/stop, so a literal
        step is emitted as the equivalent ``target = start; while ...``
        sequence with a trailing ``target = target + step`` to advance the
        induction variable. A non-literal step would need a runtime sign
        decision sauravcode can't express cleanly, so it gets a hard TODO
        comment and the body is dropped — failing loudly is safer than the
        previous behaviour, which silently emitted a 2-arg ``for`` that ran
        the wrong number of iterations or in the wrong direction.
        """
        step_value = self._literal_int_value(args[2])
        start_expr = self._expr(args[0])
        stop_expr = self._expr(args[1])
        step_expr = self._expr(args[2])

        if step_value is None:
            self.warnings.add(
                node.lineno,
                "range() with non-literal step requires manual migration",
            )
            self.emit(
                f"# TODO MANUAL MIGRATION: range({start_expr}, {stop_expr}, {step_expr}) "
                f"— rewrite as a while-loop matching the runtime sign of step"
            )
            return

        if step_value == 0:
            self.warnings.add(
                node.lineno,
                "range() with step=0 is a ValueError in Python; skipping body",
            )
            self.emit(
                f"# TODO MANUAL MIGRATION: range({start_expr}, {stop_expr}, 0) "
                f"would raise ValueError in Python"
            )
            return

        comparator = "<" if step_value > 0 else ">"
        self.emit(f"{target} = {start_expr}")
        self.emit(f"while {target} {comparator} {stop_expr}")
        self.indent += 1
        self._emit_body(node.body)
        self.emit(f"{target} = {target} + {step_expr}")
        self.indent -= 1
        if node.orelse:
            self.warnings.add(
                node.lineno, "for/else not supported, else branch skipped",
            )

    def visit_For(self, node):
        target = self._expr(node.target)

        # range-based for
        if (isinstance(node.iter, ast.Call) and
                isinstance(node.iter.func, ast.Name) and
                node.iter.func.id == "range"):
            args = node.iter.args
            if len(args) == 1:
                self.emit(f"for {target} 0 {self._expr(args[0])}")
            elif len(args) == 2:
                self.emit(f"for {target} {self._expr(args[0])} {self._expr(args[1])}")
            elif len(args) == 3:
                # The 3-arg form needs a fully custom emission path because the
                # sauravcode for-loop has no step argument. _emit_range_with_step
                # owns the entire block (header, body, induction step) and
                # returns without falling through to the shared body-emission
                # block below.
                self._emit_range_with_step(node, target, args)
                return
            else:
                self.emit(f"for {target} in {self._expr(node.iter)}")
        else:
            # for-each
            self.emit(f"for {target} in {self._expr(node.iter)}")

        self.indent += 1
        self._emit_body(node.body)
        self.indent -= 1
        if node.orelse:
            self.warnings.add(node.lineno, "for/else not supported, else branch skipped")

    # ── Try/except → try/catch ──

    def visit_Try(self, node):
        self.emit("try")
        self.indent += 1
        self._emit_body(node.body)
        self.indent -= 1

        if node.handlers:
            handler = node.handlers[0]
            err_name = handler.name or "err"
            self.emit(f"catch {err_name}")
            self.indent += 1
            self._emit_body(handler.body)
            self.indent -= 1

            if len(node.handlers) > 1:
                self.warnings.add(node.lineno, "Multiple except clauses not supported, only first used")

        if node.finalbody:
            self.warnings.add(node.lineno, "finally block not supported, skipped")

    visit_TryStar = None

    # ── Raise → throw ──

    def visit_Raise(self, node):
        if node.exc is None:
            self.emit('throw "error"')
        elif (isinstance(node.exc, ast.Call) and
              isinstance(node.exc.func, ast.Name) and
              node.exc.func.id in ("Exception", "ValueError", "RuntimeError", "TypeError") and
              node.exc.args):
            # raise Exception("msg") → throw "msg"
            self.emit(f"throw {self._expr(node.exc.args[0])}")
        else:
            self.emit(f"throw {self._expr(node.exc)}")

    # ── Break / Continue ──

    def visit_Break(self, node):
        self.emit("break")

    def visit_Continue(self, node):
        self.emit("continue")

    # ── Pass ──

    def visit_Pass(self, node):
        # sauravcode doesn't need pass; emit a comment
        self.emit("# pass")

    # ── Assert ──

    def visit_Assert(self, node):
        expr = self._expr(node.test)
        if node.msg:
            self.emit(f'assert {expr} "{self._expr(node.msg)}"')
        else:
            self.emit(f"assert {expr}")

    # ── Import (warning) ──

    def visit_Import(self, node):
        names = ", ".join(a.name for a in node.names)
        self.warnings.add(node.lineno, f"import {names} — no equivalent, skipped")

    def visit_ImportFrom(self, node):
        names = ", ".join(a.name for a in node.names)
        self.warnings.add(node.lineno, f"from {node.module} import {names} — skipped")

    # ── Class (partial) ──

    def visit_ClassDef(self, node):
        self.warnings.add(node.lineno, f"class '{node.name}' — classes have limited support")
        self.emit(f"class {node.name}")
        self.indent += 1
        self._emit_body(node.body)
        self.indent -= 1
        self.emit("")

    # ── Delete ──

    def visit_Delete(self, node):
        self.warnings.add(node.lineno, "del statement not supported, skipped")

    # ── Global / Nonlocal ──

    def visit_Global(self, node):
        self.warnings.add(node.lineno, "global declaration skipped")

    def visit_Nonlocal(self, node):
        self.warnings.add(node.lineno, "nonlocal declaration skipped")

    # ── With ──

    def visit_With(self, node):
        self.warnings.add(node.lineno, "with statement not supported, skipped")

    # ── Fallback ──

    def generic_visit(self, node):
        if isinstance(node, ast.stmt):
            self.warnings.add(getattr(node, 'lineno', 0),
                              f"Unsupported statement: {type(node).__name__}")

    # ════════════════════════════════════════════════
    # Expression rendering
    # ════════════════════════════════════════════════

    def _expr(self, node):
        if isinstance(node, ast.Constant):
            return self._const(node)
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.BinOp):
            left = self._expr(node.left)
            right = self._expr(node.right)
            op = self._binop_symbol(node.op)
            # Wrap function calls with args in parens to avoid ambiguity
            if isinstance(node.left, ast.Call) and node.left.args:
                left = f"({left})"
            if isinstance(node.right, ast.Call) and node.right.args:
                right = f"({right})"
            return f"{left} {op} {right}"
        if isinstance(node, ast.UnaryOp):
            operand = self._expr(node.operand)
            if isinstance(node.op, ast.USub):
                return f"0 - {operand}"
            if isinstance(node.op, ast.Not):
                return f"not {operand}"
            return operand
        if isinstance(node, ast.BoolOp):
            op = "and" if isinstance(node.op, ast.And) else "or"
            parts = [self._expr(v) for v in node.values]
            return f" {op} ".join(parts)
        if isinstance(node, ast.Compare):
            return self._compare(node)
        if isinstance(node, ast.Call):
            return self._call(node)
        if isinstance(node, ast.List):
            elts = ", ".join(self._expr(e) for e in node.elts)
            return f"[{elts}]"
        if isinstance(node, ast.Dict):
            pairs = []
            for k, v in zip(node.keys, node.values):
                pairs.append(f"{self._expr(k)}: {self._expr(v)}")
            return "{" + ", ".join(pairs) + "}"
        if isinstance(node, ast.Subscript):
            return self._subscript(node)
        if isinstance(node, ast.Attribute):
            return f"{self._expr(node.value)}.{node.attr}"
        if isinstance(node, ast.JoinedStr):
            return self._fstring(node)
        if isinstance(node, ast.IfExp):
            # Ternary — sauravcode doesn't have ternary, use inline
            # We'll emit it as a comment with a warning
            body = self._expr(node.body)
            test = self._expr(node.test)
            orelse = self._expr(node.orelse)
            return f"ternary {test} {body} {orelse}"
        if isinstance(node, ast.Lambda):
            params = " ".join(a.arg for a in node.args.args)
            body = self._expr(node.body)
            if params:
                return f"lambda {params} -> {body}"
            return f"lambda -> {body}"
        if isinstance(node, ast.ListComp):
            return self._list_comp(node)
        if isinstance(node, ast.Tuple):
            elts = ", ".join(self._expr(e) for e in node.elts)
            return f"[{elts}]"
        if isinstance(node, ast.FormattedValue):
            return self._expr(node.value)
        return f"/* unsupported: {type(node).__name__} */"

    def _const(self, node):
        v = node.value
        if v is True:
            return "true"
        if v is False:
            return "false"
        if v is None:
            return "0"
        if isinstance(v, str):
            escaped = v.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        return repr(v)

    def _binop_symbol(self, op):
        ops = {
            ast.Add: "+", ast.Sub: "-", ast.Mult: "*",
            ast.Div: "/", ast.Mod: "%", ast.FloorDiv: "/",
            ast.Pow: "**",
        }
        return ops.get(type(op), "+")

    def _compare(self, node):
        parts = [self._expr(node.left)]
        for op, comp in zip(node.ops, node.comparators):
            symbol = {
                ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<",
                ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=",
            }.get(type(op), "==")
            parts.append(symbol)
            parts.append(self._expr(comp))
        return " ".join(parts)

    def _call(self, node):
        func = self._expr(node.func)

        # print() → print <args>
        if func == "print":
            if not node.args:
                return 'print ""'
            parts = []
            for arg in node.args:
                parts.append(self._expr(arg))
            if len(parts) == 1:
                return f"print {parts[0]}"
            # Multiple args: join with space in an f-string
            joined = " ".join(f"{{{self._expr(a)}}}" for a in node.args)
            return f'print f"{joined}"'

        # len() → len <arg>
        if func == "len" and len(node.args) == 1:
            return f"len {self._expr(node.args[0])}"

        # input() → input <prompt>
        if func == "input":
            if node.args:
                return f"input {self._expr(node.args[0])}"
            return 'input ""'

        # str(), int(), float() → to_string, to_int, to_float
        type_map = {"str": "to_string", "int": "to_int", "float": "to_float"}
        if func in type_map and len(node.args) == 1:
            return f"{type_map[func]} {self._expr(node.args[0])}"

        # append → list append syntax
        if (isinstance(node.func, ast.Attribute) and
                node.func.attr == "append" and len(node.args) == 1):
            obj = self._expr(node.func.value)
            val = self._expr(node.args[0])
            return f"append {obj} {val}"

        # General function call: func arg1 arg2 ...
        # sauravcode uses space-separated args (no parens, no commas)
        # Wrap complex args in parens to avoid ambiguity
        args = []
        for a in node.args:
            a_str = self._expr(a)
            # Wrap in parens if the arg contains spaces (it's an expression)
            if " " in a_str and not (a_str.startswith("(") and a_str.endswith(")")):
                a_str = f"({a_str})"
            args.append(a_str)

        # For keyword args, emit a warning
        if node.keywords:
            kw_names = [kw.arg for kw in node.keywords if kw.arg]
            self.warnings.add(getattr(node, 'lineno', 0),
                              f"Keyword arguments ({', '.join(kw_names)}) not supported")

        if args:
            arg_str = " ".join(args)
            return f"{func} {arg_str}"
        return f"{func}"

    def _subscript(self, node):
        value = self._expr(node.value)
        if isinstance(node.slice, ast.Slice):
            lower = self._expr(node.slice.lower) if node.slice.lower else "0"
            upper = self._expr(node.slice.upper) if node.slice.upper else ""
            if upper:
                return f"{value}[{lower}:{upper}]"
            return f"{value}[{lower}:]"
        idx = self._expr(node.slice)
        return f"{value}[{idx}]"

    def _fstring(self, node):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            elif isinstance(value, ast.FormattedValue):
                expr = self._expr(value.value)
                parts.append(f"{{{expr}}}")
            else:
                parts.append(self._expr(value))
        return 'f"' + "".join(parts) + '"'

    def _list_comp(self, node):
        if len(node.generators) == 1:
            gen = node.generators[0]
            target = self._expr(gen.target)
            iter_expr = self._expr(gen.iter)
            elt = self._expr(node.elt)
            if not gen.ifs:
                return f"[{elt} for {target} in {iter_expr}]"
            cond = self._expr(gen.ifs[0])
            return f"[{elt} for {target} in {iter_expr} if {cond}]"
        # Nested — warn and do best effort
        return f"/* complex comprehension */"


def migrate_source(source, filename="<stdin>"):
    """Convert Python source string to sauravcode."""
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as e:
        return f"# Migration failed: {e}\n"

    source_lines = source.split("\n")

    # Extract comments from source (AST drops them)
    comment_lines = {}
    for i, line in enumerate(source_lines, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            comment_lines[i] = stripped

    visitor = PythonToSrv(source_lines)
    visitor.visit(tree)

    result = visitor.result()

    # Prepend standalone comments that appear before any code
    header_comments = []
    for i in sorted(comment_lines):
        # Only prepend comments that are at the very top
        if i <= (tree.body[0].lineno if tree.body else 999):
            header_comments.append(comment_lines[i])
        else:
            break

    if header_comments:
        header = "\n".join(header_comments) + "\n\n"
        result = header + result

    return result


def migrate_file(path, output=None, preview=False):
    """Migrate a single Python file."""
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()

    result = migrate_source(source, filename=str(path))

    if preview:
        print(f"-- {path} --")
        print(result)
        print()
        return

    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(result)
        print(f"Migrated {path} → {output}")
    else:
        print(result, end="")


def main():
    parser = argparse.ArgumentParser(
        description="Migrate Python scripts to sauravcode (.srv)")
    parser.add_argument("path", help="Python file or directory to migrate")
    parser.add_argument("-o", "--output", help="Output file path")
    parser.add_argument("--preview", action="store_true",
                        help="Preview conversion without writing")
    parser.add_argument("--recursive", action="store_true",
                        help="Convert all .py files in directory")

    args = parser.parse_args()
    path = Path(args.path)

    if path.is_dir():
        if not args.recursive:
            print("Error: use --recursive to convert directories", file=sys.stderr)
            sys.exit(1)
        py_files = sorted(path.rglob("*.py"))
        if not py_files:
            print("No .py files found", file=sys.stderr)
            sys.exit(1)
        for py_file in py_files:
            srv_path = py_file.with_suffix(".srv")
            if args.preview:
                migrate_file(py_file, preview=True)
            else:
                migrate_file(py_file, output=str(srv_path))
    elif path.is_file():
        migrate_file(path, output=args.output, preview=args.preview)
    else:
        print(f"Error: {path} not found", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
