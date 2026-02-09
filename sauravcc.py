"""
sauravcc - The Sauravcode Compiler
Compiles .srv files to C, then to native executables via gcc.

Usage:
    python sauravcc.py <filename>.srv           # Compile and run
    python sauravcc.py <filename>.srv --emit-c  # Just emit C code
    python sauravcc.py <filename>.srv -o out    # Compile to specific output name
"""

import re
import sys
import os
import subprocess
import argparse

# ============================================================
# TOKENIZER (from saurav.py, cleaned up - no debug prints)
# ============================================================

token_specification = [
    ('COMMENT',  r'#.*'),
    ('NUMBER',   r'\d+(\.\d*)?'),
    ('STRING',   r'\".*?\"'),
    ('EQ',       r'=='),
    ('NEQ',      r'!='),
    ('LTE',      r'<='),
    ('GTE',      r'>='),
    ('LT',       r'<'),
    ('GT',       r'>'),
    ('ASSIGN',   r'='),
    ('OP',       r'[+\-*/]'),
    ('KEYWORD',  r'\b(?:function|return|class|int|float|bool|string|if|else if|else|for|while|try|catch|print|list|set|map|stack|queue)\b'),
    ('IDENT',    r'[a-zA-Z_]\w*'),
    ('NEWLINE',  r'\n'),
    ('SKIP',     r'[ \t]+'),
    ('MISMATCH', r'.'),
]

tok_regex = '|'.join(f'(?P<{pair[0]}>{pair[1]})' for pair in token_specification)


def tokenize(code):
    tokens = []
    line_num = 1
    line_start = 0
    indent_levels = [0]

    for match in re.finditer(tok_regex, code):
        typ = match.lastgroup
        value = match.group(typ)

        if typ == 'NEWLINE':
            line_num += 1
            line_start = match.end()
            tokens.append(('NEWLINE', value, line_num, match.start()))

            indent_match = re.match(r'[ \t]*', code[line_start:])
            if indent_match:
                indent_str = indent_match.group(0)
                indent = len(indent_str.replace('\t', '    '))
                if indent > indent_levels[-1]:
                    indent_levels.append(indent)
                    tokens.append(('INDENT', indent, line_num, line_start))
                while indent < indent_levels[-1]:
                    indent_levels.pop()
                    tokens.append(('DEDENT', indent, line_num, line_start))

        elif typ == 'SKIP':
            continue
        elif typ == 'COMMENT':
            continue  # Skip comments entirely
        elif typ == 'MISMATCH':
            raise RuntimeError(f'Unexpected character {value!r} on line {line_num}')
        else:
            column = match.start() - line_start
            tokens.append((typ, value, line_num, column))

    while len(indent_levels) > 1:
        indent_levels.pop()
        tokens.append(('DEDENT', 0, line_num, line_start))

    return tokens


# ============================================================
# AST NODES
# ============================================================

class ASTNode:
    pass

class ProgramNode(ASTNode):
    def __init__(self, statements):
        self.statements = statements
    def __repr__(self):
        return f"Program({self.statements})"

class AssignmentNode(ASTNode):
    def __init__(self, name, expression):
        self.name = name
        self.expression = expression
    def __repr__(self):
        return f"Assign({self.name} = {self.expression})"

class FunctionNode(ASTNode):
    def __init__(self, name, params, body):
        self.name = name
        self.params = params
        self.body = body
    def __repr__(self):
        return f"Function({self.name}({self.params}))"

class ReturnNode(ASTNode):
    def __init__(self, expression):
        self.expression = expression
    def __repr__(self):
        return f"Return({self.expression})"

class PrintNode(ASTNode):
    def __init__(self, expression):
        self.expression = expression
    def __repr__(self):
        return f"Print({self.expression})"

class IfNode(ASTNode):
    def __init__(self, condition, body, else_body=None):
        self.condition = condition
        self.body = body
        self.else_body = else_body
    def __repr__(self):
        return f"If({self.condition})"

class WhileNode(ASTNode):
    def __init__(self, condition, body):
        self.condition = condition
        self.body = body
    def __repr__(self):
        return f"While({self.condition})"

class ForNode(ASTNode):
    def __init__(self, var, start, end, body):
        self.var = var
        self.start = start
        self.end = end
        self.body = body
    def __repr__(self):
        return f"For({self.var} in {self.start}..{self.end})"

class BinaryOpNode(ASTNode):
    def __init__(self, left, operator, right):
        self.left = left
        self.operator = operator
        self.right = right
    def __repr__(self):
        return f"BinOp({self.left} {self.operator} {self.right})"

class CompareNode(ASTNode):
    def __init__(self, left, operator, right):
        self.left = left
        self.operator = operator
        self.right = right
    def __repr__(self):
        return f"Compare({self.left} {self.operator} {self.right})"

class NumberNode(ASTNode):
    def __init__(self, value):
        self.value = value
    def __repr__(self):
        return f"Num({self.value})"

class StringNode(ASTNode):
    def __init__(self, value):
        self.value = value
    def __repr__(self):
        return f"Str({self.value})"

class IdentifierNode(ASTNode):
    def __init__(self, name):
        self.name = name
    def __repr__(self):
        return f"Id({self.name})"

class FunctionCallNode(ASTNode):
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments
    def __repr__(self):
        return f"Call({self.name}({self.arguments}))"


# ============================================================
# PARSER (enhanced from saurav.py)
# ============================================================

class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def parse(self):
        statements = []
        while self.pos < len(self.tokens):
            self.skip_newlines()
            if self.pos < len(self.tokens) and self.peek()[0] != 'EOF':
                statement = self.parse_statement()
                if statement:
                    statements.append(statement)
        return ProgramNode(statements)

    def parse_statement(self):
        token_type, value, *_ = self.peek()

        if token_type == 'COMMENT':
            self.advance()
            return None
        elif token_type == 'KEYWORD' and value == 'function':
            return self.parse_function()
        elif token_type == 'KEYWORD' and value == 'return':
            self.expect('KEYWORD', 'return')
            expression = self.parse_expression()
            return ReturnNode(expression)
        elif token_type == 'KEYWORD' and value == 'print':
            self.expect('KEYWORD', 'print')
            expression = self.parse_expression()
            return PrintNode(expression)
        elif token_type == 'KEYWORD' and value == 'if':
            return self.parse_if()
        elif token_type == 'KEYWORD' and value == 'while':
            return self.parse_while()
        elif token_type == 'KEYWORD' and value == 'for':
            return self.parse_for()
        elif token_type == 'IDENT':
            name = self.expect('IDENT')[1]
            if self.peek()[0] == 'ASSIGN':
                self.expect('ASSIGN')
                expression = self.parse_expression()
                return AssignmentNode(name, expression)
            else:
                return self.parse_function_call(name)
        elif token_type == 'NEWLINE':
            self.advance()
            return None
        elif token_type in {'INDENT', 'DEDENT'}:
            self.advance()
            return None
        else:
            raise SyntaxError(f"Unknown statement: {token_type} {repr(value)} on line {self.peek()[2] if len(self.peek()) > 2 else '?'}")

    def parse_function(self):
        self.expect('KEYWORD', 'function')
        name = self.expect('IDENT')[1]
        params = []

        while self.peek()[0] == 'IDENT':
            params.append(self.expect('IDENT')[1])

        self.expect('NEWLINE')
        self.expect('INDENT')
        body = self.parse_block()
        self.expect('DEDENT')

        return FunctionNode(name, params, body)

    def parse_if(self):
        self.expect('KEYWORD', 'if')
        condition = self.parse_comparison()
        self.expect('NEWLINE')
        self.expect('INDENT')
        body = self.parse_block()
        self.expect('DEDENT')

        else_body = None
        if self.peek()[0] == 'KEYWORD' and self.peek()[1] == 'else':
            self.expect('KEYWORD', 'else')
            self.expect('NEWLINE')
            self.expect('INDENT')
            else_body = self.parse_block()
            self.expect('DEDENT')

        return IfNode(condition, body, else_body)

    def parse_while(self):
        self.expect('KEYWORD', 'while')
        condition = self.parse_comparison()
        self.expect('NEWLINE')
        self.expect('INDENT')
        body = self.parse_block()
        self.expect('DEDENT')
        return WhileNode(condition, body)

    def parse_for(self):
        self.expect('KEYWORD', 'for')
        var = self.expect('IDENT')[1]
        start = self.parse_term()
        end = self.parse_term()
        self.expect('NEWLINE')
        self.expect('INDENT')
        body = self.parse_block()
        self.expect('DEDENT')
        return ForNode(var, start, end, body)

    def parse_block(self):
        statements = []
        while self.peek()[0] not in ('DEDENT', 'EOF'):
            statement = self.parse_statement()
            if statement:
                statements.append(statement)
            while self.peek()[0] == 'NEWLINE':
                self.advance()
        return statements

    def parse_function_call(self, name):
        arguments = []
        while self.peek()[0] in ('NUMBER', 'IDENT', 'STRING'):
            token_type, value, *_ = self.peek()
            if token_type == 'NUMBER':
                self.advance()
                arguments.append(NumberNode(float(value)))
            elif token_type == 'IDENT':
                self.advance()
                arguments.append(IdentifierNode(value))
            elif token_type == 'STRING':
                self.advance()
                arguments.append(StringNode(value[1:-1]))  # Strip quotes
            else:
                break
        return FunctionCallNode(name, arguments)

    def parse_expression(self):
        left = self.parse_term()
        while self.peek()[0] == 'OP':
            op = self.expect('OP')[1]
            right = self.parse_term()
            left = BinaryOpNode(left, op, right)
        return left

    def parse_comparison(self):
        left = self.parse_expression()
        if self.peek()[0] in ('EQ', 'NEQ', 'LT', 'GT', 'LTE', 'GTE'):
            op_type, op_val, *_ = self.advance()
            right = self.parse_expression()
            return CompareNode(left, op_val, right)
        return left

    def parse_term(self):
        token_type, value, *_ = self.peek()
        if token_type == 'NUMBER':
            self.advance()
            return NumberNode(float(value))
        elif token_type == 'STRING':
            self.advance()
            return StringNode(value[1:-1])
        elif token_type == 'IDENT':
            self.advance()
            if self.peek()[0] in ('NUMBER', 'IDENT', 'STRING'):
                return self.parse_function_call(value)
            else:
                return IdentifierNode(value)
        else:
            raise SyntaxError(f'Unexpected token: {token_type} {repr(value)}')

    def skip_newlines(self):
        while self.peek()[0] == 'NEWLINE':
            self.advance()

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else ('EOF', None)

    def advance(self):
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def expect(self, token_type, value=None):
        actual_type, actual_value, *_ = self.advance()
        if actual_type != token_type or (value and actual_value != value):
            raise SyntaxError(f'Expected {token_type} {repr(value)}, got {actual_type} {repr(actual_value)}')
        return actual_type, actual_value


# ============================================================
# C CODE GENERATOR
# ============================================================

class CCodeGenerator:
    """Compiles sauravcode AST to C source code."""

    def __init__(self):
        self.functions = {}       # name -> FunctionNode (for forward declarations)
        self.declared_vars = {}   # scope -> set of var names
        self.output_lines = []
        self.indent_level = 0

    def emit(self, line=""):
        self.output_lines.append("    " * self.indent_level + line)

    def compile(self, program):
        """Generate complete C source from a ProgramNode."""
        # First pass: collect all function definitions
        top_level_calls = []
        for stmt in program.statements:
            if isinstance(stmt, FunctionNode):
                self.functions[stmt.name] = stmt
            else:
                top_level_calls.append(stmt)

        # Emit C header
        self.emit("#include <stdio.h>")
        self.emit("#include <stdlib.h>")
        self.emit("")

        # Emit forward declarations
        for name, func in self.functions.items():
            params = ", ".join(f"double {p}" for p in func.params)
            self.emit(f"double {name}({params});")
        self.emit("")

        # Emit function definitions
        for name, func in self.functions.items():
            self.compile_function(func)
            self.emit("")

        # Emit main()
        self.emit("int main(void) {")
        self.indent_level += 1
        self.declared_vars['main'] = set()

        for stmt in top_level_calls:
            self.compile_statement(stmt, scope='main', is_top_level=True)

        self.emit("return 0;")
        self.indent_level -= 1
        self.emit("}")
        self.emit("")

        return "\n".join(self.output_lines)

    def compile_function(self, func):
        """Emit a C function definition."""
        params = ", ".join(f"double {p}" for p in func.params)
        self.emit(f"double {func.name}({params}) {{")
        self.indent_level += 1
        self.declared_vars[func.name] = set(func.params)

        for stmt in func.body:
            self.compile_statement(stmt, scope=func.name)

        self.indent_level -= 1
        self.emit("}")

    def compile_statement(self, stmt, scope='main', is_top_level=False):
        """Compile a single statement to C."""
        if isinstance(stmt, AssignmentNode):
            expr_c = self.compile_expression(stmt.expression)
            if stmt.name not in self.declared_vars.get(scope, set()):
                self.emit(f"double {stmt.name} = {expr_c};")
                self.declared_vars.setdefault(scope, set()).add(stmt.name)
            else:
                self.emit(f"{stmt.name} = {expr_c};")

        elif isinstance(stmt, ReturnNode):
            expr_c = self.compile_expression(stmt.expression)
            self.emit(f"return {expr_c};")

        elif isinstance(stmt, PrintNode):
            expr_c = self.compile_expression(stmt.expression)
            if isinstance(stmt.expression, StringNode):
                self.emit(f'printf("%s\\n", {expr_c});')
            else:
                self.emit(f'printf("%.10g\\n", {expr_c});')

        elif isinstance(stmt, FunctionCallNode):
            call_c = self.compile_call(stmt)
            if is_top_level:
                # Top-level calls: print the result
                self.emit(f'printf("%.10g\\n", {call_c});')
            else:
                self.emit(f"{call_c};")

        elif isinstance(stmt, IfNode):
            cond_c = self.compile_expression(stmt.condition)
            self.emit(f"if ({cond_c}) {{")
            self.indent_level += 1
            for s in stmt.body:
                self.compile_statement(s, scope=scope)
            self.indent_level -= 1
            if stmt.else_body:
                self.emit("} else {")
                self.indent_level += 1
                for s in stmt.else_body:
                    self.compile_statement(s, scope=scope)
                self.indent_level -= 1
            self.emit("}")

        elif isinstance(stmt, WhileNode):
            cond_c = self.compile_expression(stmt.condition)
            self.emit(f"while ({cond_c}) {{")
            self.indent_level += 1
            for s in stmt.body:
                self.compile_statement(s, scope=scope)
            self.indent_level -= 1
            self.emit("}")

        elif isinstance(stmt, ForNode):
            start_c = self.compile_expression(stmt.start)
            end_c = self.compile_expression(stmt.end)
            var = stmt.var
            if var not in self.declared_vars.get(scope, set()):
                self.declared_vars.setdefault(scope, set()).add(var)
            self.emit(f"for (double {var} = {start_c}; {var} < {end_c}; {var}++) {{")
            self.indent_level += 1
            for s in stmt.body:
                self.compile_statement(s, scope=scope)
            self.indent_level -= 1
            self.emit("}")

    def compile_expression(self, expr):
        """Compile an expression to a C expression string."""
        if isinstance(expr, NumberNode):
            # Emit integers as integers, floats as floats
            if expr.value == int(expr.value):
                return str(int(expr.value))
            return str(expr.value)

        elif isinstance(expr, StringNode):
            return f'"{expr.value}"'

        elif isinstance(expr, IdentifierNode):
            return expr.name

        elif isinstance(expr, BinaryOpNode):
            left_c = self.compile_expression(expr.left)
            right_c = self.compile_expression(expr.right)
            return f"({left_c} {expr.operator} {right_c})"

        elif isinstance(expr, CompareNode):
            left_c = self.compile_expression(expr.left)
            right_c = self.compile_expression(expr.right)
            return f"({left_c} {expr.operator} {right_c})"

        elif isinstance(expr, FunctionCallNode):
            return self.compile_call(expr)

        else:
            raise ValueError(f"Unknown expression type: {type(expr)}")

    def compile_call(self, call):
        """Compile a function call to C."""
        args_c = ", ".join(self.compile_expression(a) for a in call.arguments)
        return f"{call.name}({args_c})"


# ============================================================
# MAIN - CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="sauravcc - The Sauravcode Compiler (compiles .srv to C to native)",
        prog="sauravcc"
    )
    parser.add_argument("file", help="Source file (.srv)")
    parser.add_argument("--emit-c", action="store_true", help="Print generated C code and exit")
    parser.add_argument("-o", "--output", help="Output executable name (default: <filename> without extension)")
    parser.add_argument("--keep-c", action="store_true", help="Keep the generated .c file")
    parser.add_argument("--cc", default="gcc", help="C compiler to use (default: gcc)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    if not args.file.endswith('.srv'):
        print("Error: Source file must have .srv extension")
        sys.exit(1)

    if not os.path.isfile(args.file):
        print(f"Error: File '{args.file}' not found")
        sys.exit(1)

    # Read source
    with open(args.file, 'r') as f:
        code = f.read()

    if args.verbose:
        print(f"[sauravcc] Compiling {args.file}...")

    # Tokenize
    tokens = tokenize(code)
    if args.verbose:
        print(f"[sauravcc] {len(tokens)} tokens")

    # Parse
    ast_parser = Parser(tokens)
    program = ast_parser.parse()
    if args.verbose:
        print(f"[sauravcc] {len(program.statements)} top-level statements")

    # Generate C
    codegen = CCodeGenerator()
    c_code = codegen.compile(program)

    if args.emit_c:
        print(c_code)
        return

    # Write C file
    base = os.path.splitext(args.file)[0]
    c_file = base + ".c"
    with open(c_file, 'w') as f:
        f.write(c_code)

    if args.verbose:
        print(f"[sauravcc] Generated {c_file}")

    # Compile with gcc
    out_name = args.output or base
    if sys.platform == 'win32' and not out_name.endswith('.exe'):
        out_name += '.exe'

    compile_cmd = [args.cc, c_file, "-o", out_name, "-lm"]
    if args.verbose:
        print(f"[sauravcc] Running: {' '.join(compile_cmd)}")

    result = subprocess.run(compile_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Compilation failed:\n{result.stderr}")
        sys.exit(1)

    if args.verbose:
        print(f"[sauravcc] Built {out_name}")

    # Clean up .c file unless --keep-c
    if not args.keep_c:
        os.remove(c_file)

    # Run the executable
    if args.verbose:
        print(f"[sauravcc] Running {out_name}...\n")

    run_result = subprocess.run([os.path.abspath(out_name)], capture_output=False)
    sys.exit(run_result.returncode)


if __name__ == '__main__':
    main()
