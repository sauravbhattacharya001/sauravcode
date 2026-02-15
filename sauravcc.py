"""
sauravcc - The Sauravcode Compiler (v2)
Compiles .srv files to C, then to native executables via gcc.

Supports all sauravcode language features:
  - Functions (with recursion)
  - Variables & assignment
  - Arithmetic (+, -, *, /, %)
  - Comparisons (==, !=, <, >, <=, >=)
  - Logical operators (and, or, not)
  - If / else if / else
  - While loops
  - For loops (range-based)
  - Print statement
  - Strings
  - Booleans (true, false)
  - Lists (dynamic arrays)
  - Type annotations (int, float, bool, string) — optional
  - Classes (with fields and methods)
  - Try / catch (basic error handling)
  - Parenthesized expressions for disambiguation

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
# TOKENIZER
# ============================================================

token_specification = [
    ('COMMENT',  r'#.*'),
    ('NUMBER',   r'\d+(\.\d*)?'),
    ('STRING',   r'\"(?:[^\"\\]|\\.)*\"'),    # String with escape support
    ('EQ',       r'=='),
    ('NEQ',      r'!='),
    ('LTE',      r'<='),
    ('GTE',      r'>='),
    ('LT',       r'<'),
    ('GT',       r'>'),
    ('ASSIGN',   r'='),
    ('OP',       r'[+\-*/%]'),                # Added modulo
    ('LPAREN',   r'\('),
    ('RPAREN',   r'\)'),
    ('LBRACKET', r'\['),
    ('RBRACKET', r'\]'),
    ('DOT',      r'\.'),
    ('COMMA',    r','),
    ('KEYWORD',  r'\b(?:function|return|class|new|self|int|float|bool|string|if|else if|else|for|in|while|try|catch|print|true|false|and|or|not|list|set|map|stack|queue|append|len|pop|get)\b'),
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
            continue
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

class AssignmentNode(ASTNode):
    def __init__(self, name, expression):
        self.name = name
        self.expression = expression

class FunctionNode(ASTNode):
    def __init__(self, name, params, body):
        self.name = name
        self.params = params
        self.body = body

class ReturnNode(ASTNode):
    def __init__(self, expression):
        self.expression = expression

class PrintNode(ASTNode):
    def __init__(self, expression):
        self.expression = expression

class IfNode(ASTNode):
    def __init__(self, condition, body, elif_chains=None, else_body=None):
        self.condition = condition
        self.body = body
        self.elif_chains = elif_chains or []  # list of (condition, body)
        self.else_body = else_body

class WhileNode(ASTNode):
    def __init__(self, condition, body):
        self.condition = condition
        self.body = body

class ForNode(ASTNode):
    def __init__(self, var, start, end, body):
        self.var = var
        self.start = start
        self.end = end
        self.body = body

class BinaryOpNode(ASTNode):
    def __init__(self, left, operator, right):
        self.left = left
        self.operator = operator
        self.right = right

class UnaryOpNode(ASTNode):
    def __init__(self, operator, operand):
        self.operator = operator
        self.operand = operand

class CompareNode(ASTNode):
    def __init__(self, left, operator, right):
        self.left = left
        self.operator = operator
        self.right = right

class LogicalNode(ASTNode):
    def __init__(self, left, operator, right):
        self.left = left
        self.operator = operator  # 'and' or 'or'
        self.right = right

class NumberNode(ASTNode):
    def __init__(self, value):
        self.value = value

class StringNode(ASTNode):
    def __init__(self, value):
        self.value = value

class BoolNode(ASTNode):
    def __init__(self, value):
        self.value = value  # True or False

class IdentifierNode(ASTNode):
    def __init__(self, name):
        self.name = name

class FunctionCallNode(ASTNode):
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments

class ListNode(ASTNode):
    def __init__(self, elements):
        self.elements = elements

class IndexNode(ASTNode):
    def __init__(self, obj, index):
        self.obj = obj
        self.index = index

class DotAccessNode(ASTNode):
    def __init__(self, obj, field):
        self.obj = obj
        self.field = field

class MethodCallNode(ASTNode):
    def __init__(self, obj, method, arguments):
        self.obj = obj
        self.method = method
        self.arguments = arguments

class ClassNode(ASTNode):
    def __init__(self, name, body):
        self.name = name
        self.body = body  # list of FunctionNode (methods)

class NewNode(ASTNode):
    def __init__(self, class_name, arguments):
        self.class_name = class_name
        self.arguments = arguments

class TryCatchNode(ASTNode):
    def __init__(self, try_body, catch_var, catch_body):
        self.try_body = try_body
        self.catch_var = catch_var
        self.catch_body = catch_body

class IndexedAssignmentNode(ASTNode):
    """Assignment to a list element: list[index] = value"""
    def __init__(self, name, index, value):
        self.name = name
        self.index = index
        self.value = value

class DotAssignmentNode(ASTNode):
    """Assignment via dot access: obj.field = value"""
    def __init__(self, obj, field, value):
        self.obj = obj
        self.field = field
        self.value = value

class AppendNode(ASTNode):
    def __init__(self, list_name, value):
        self.list_name = list_name
        self.value = value

class LenNode(ASTNode):
    def __init__(self, expression):
        self.expression = expression

class PopNode(ASTNode):
    def __init__(self, list_name):
        self.list_name = list_name


# ============================================================
# PARSER
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
        elif token_type == 'KEYWORD' and value == 'class':
            return self.parse_class()
        elif token_type == 'KEYWORD' and value == 'return':
            self.expect('KEYWORD', 'return')
            expression = self.parse_full_expression()
            return ReturnNode(expression)
        elif token_type == 'KEYWORD' and value == 'print':
            self.expect('KEYWORD', 'print')
            expression = self.parse_full_expression()
            return PrintNode(expression)
        elif token_type == 'KEYWORD' and value == 'if':
            return self.parse_if()
        elif token_type == 'KEYWORD' and value == 'while':
            return self.parse_while()
        elif token_type == 'KEYWORD' and value == 'for':
            return self.parse_for()
        elif token_type == 'KEYWORD' and value == 'try':
            return self.parse_try()
        elif token_type == 'KEYWORD' and value == 'append':
            return self.parse_append()
        elif token_type == 'IDENT':
            name = self.expect('IDENT')[1]
            # Check for dot access / method call
            if self.peek()[0] == 'DOT':
                return self.parse_dot_chain(IdentifierNode(name))
            if self.peek()[0] == 'ASSIGN':
                self.expect('ASSIGN')
                expression = self.parse_full_expression()
                return AssignmentNode(name, expression)
            elif self.peek()[0] == 'LBRACKET':
                # list[index] = value (indexed assignment)
                self.expect('LBRACKET')
                idx = self.parse_full_expression()
                self.expect('RBRACKET')
                if self.peek()[0] == 'ASSIGN':
                    self.expect('ASSIGN')
                    val = self.parse_full_expression()
                    return IndexedAssignmentNode(name, idx, val)
                return IndexNode(IdentifierNode(name), idx)
            else:
                return self.parse_function_call(name)
        elif token_type == 'NEWLINE':
            self.advance()
            return None
        elif token_type in {'INDENT', 'DEDENT'}:
            self.advance()
            return None
        # Skip type annotations used as statements
        elif token_type == 'KEYWORD' and value in ('int', 'float', 'bool', 'string'):
            self.advance()
            return None
        else:
            raise SyntaxError(f"Unknown statement: {token_type} {repr(value)}")

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

    def parse_class(self):
        self.expect('KEYWORD', 'class')
        name = self.expect('IDENT')[1]
        self.expect('NEWLINE')
        self.expect('INDENT')
        body = []
        while self.peek()[0] not in ('DEDENT', 'EOF'):
            self.skip_newlines()
            if self.peek()[0] == 'DEDENT':
                break
            stmt = self.parse_statement()
            if stmt:
                body.append(stmt)
        self.expect('DEDENT')
        return ClassNode(name, body)

    def parse_if(self):
        self.expect('KEYWORD', 'if')
        condition = self.parse_full_expression()
        self.expect('NEWLINE')
        self.expect('INDENT')
        body = self.parse_block()
        self.expect('DEDENT')

        elif_chains = []
        # Handle 'else if' chains
        while self.peek()[0] == 'KEYWORD' and self.peek()[1] == 'else if':
            self.expect('KEYWORD', 'else if')
            elif_cond = self.parse_full_expression()
            self.expect('NEWLINE')
            self.expect('INDENT')
            elif_body = self.parse_block()
            self.expect('DEDENT')
            elif_chains.append((elif_cond, elif_body))

        else_body = None
        if self.peek()[0] == 'KEYWORD' and self.peek()[1] == 'else':
            self.expect('KEYWORD', 'else')
            self.expect('NEWLINE')
            self.expect('INDENT')
            else_body = self.parse_block()
            self.expect('DEDENT')

        return IfNode(condition, body, elif_chains, else_body)

    def parse_while(self):
        self.expect('KEYWORD', 'while')
        condition = self.parse_full_expression()
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

    def parse_try(self):
        self.expect('KEYWORD', 'try')
        self.expect('NEWLINE')
        self.expect('INDENT')
        try_body = self.parse_block()
        self.expect('DEDENT')

        self.expect('KEYWORD', 'catch')
        catch_var = None
        if self.peek()[0] == 'IDENT':
            catch_var = self.expect('IDENT')[1]
        self.expect('NEWLINE')
        self.expect('INDENT')
        catch_body = self.parse_block()
        self.expect('DEDENT')

        return TryCatchNode(try_body, catch_var, catch_body)

    def parse_append(self):
        self.expect('KEYWORD', 'append')
        list_name = self.expect('IDENT')[1]
        value = self.parse_full_expression()
        return AppendNode(list_name, value)

    def parse_dot_chain(self, obj):
        """Parse obj.field or obj.method args"""
        while self.peek()[0] == 'DOT':
            self.expect('DOT')
            field = self.expect('IDENT')[1]
            # Check if it's a method call (next token is arg-like)
            if self.peek()[0] in ('NUMBER', 'IDENT', 'STRING', 'LPAREN', 'KEYWORD'):
                pk = self.peek()
                if pk[0] == 'KEYWORD' and pk[1] in ('true', 'false'):
                    args = [self.parse_term()]
                elif pk[0] in ('NUMBER', 'IDENT', 'STRING', 'LPAREN'):
                    args = []
                    while self.peek()[0] in ('NUMBER', 'IDENT', 'STRING', 'LPAREN'):
                        args.append(self.parse_term())
                else:
                    args = []
                if args:
                    obj = MethodCallNode(obj, field, args)
                else:
                    obj = DotAccessNode(obj, field)
            else:
                obj = DotAccessNode(obj, field)
        # After dot chain, check for assignment
        if isinstance(obj, DotAccessNode) and self.peek()[0] == 'ASSIGN':
            self.expect('ASSIGN')
            val = self.parse_full_expression()
            return DotAssignmentNode(obj.obj, obj.field, val)
        return obj

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
        while self.peek()[0] in ('NUMBER', 'IDENT', 'STRING', 'LPAREN', 'LBRACKET', 'KEYWORD'):
            pk = self.peek()
            if pk[0] == 'KEYWORD' and pk[1] in ('true', 'false', 'not', 'len', 'new'):
                arguments.append(self.parse_simple_arg())
            elif pk[0] == 'KEYWORD':
                break
            else:
                arguments.append(self.parse_simple_arg())
        return FunctionCallNode(name, arguments)

    def parse_simple_arg(self):
        """Parse a single function argument — no nested function calls from bare idents."""
        token_type, value, *_ = self.peek()
        if token_type == 'NUMBER':
            self.advance()
            return NumberNode(float(value))
        elif token_type == 'STRING':
            self.advance()
            return StringNode(value[1:-1])
        elif token_type == 'KEYWORD' and value == 'true':
            self.advance()
            return BoolNode(True)
        elif token_type == 'KEYWORD' and value == 'false':
            self.advance()
            return BoolNode(False)
        elif token_type == 'KEYWORD' and value == 'not':
            self.advance()
            operand = self.parse_simple_arg()
            return UnaryOpNode('not', operand)
        elif token_type == 'KEYWORD' and value == 'len':
            self.advance()
            arg = self.parse_simple_arg()
            return LenNode(arg)
        elif token_type == 'KEYWORD' and value == 'new':
            self.advance()
            class_name = self.expect('IDENT')[1]
            return NewNode(class_name, [])
        elif token_type == 'LPAREN':
            # Parenthesized expression — full expression inside
            self.expect('LPAREN')
            expr = self.parse_full_expression()
            self.expect('RPAREN')
            return expr
        elif token_type == 'LBRACKET':
            return self.parse_list_literal()
        elif token_type == 'IDENT':
            self.advance()
            # Check for indexing
            if self.peek()[0] == 'LBRACKET':
                self.expect('LBRACKET')
                idx = self.parse_full_expression()
                self.expect('RBRACKET')
                return IndexNode(IdentifierNode(value), idx)
            return IdentifierNode(value)
        else:
            raise SyntaxError(f'Unexpected arg token: {token_type} {repr(value)}')

    # Expression parsing with proper precedence:
    # full_expression -> logical_or
    # logical_or -> logical_and ('or' logical_and)*
    # logical_and -> comparison ('and' comparison)*
    # comparison -> expression (comp_op expression)?
    # expression -> term (('+' | '-') term)*
    # term_mul -> unary (('*' | '/' | '%') unary)*
    # unary -> 'not' unary | atom
    # atom -> NUMBER | STRING | BOOL | IDENT | '(' full_expression ')' | list | func_call

    def parse_full_expression(self):
        return self.parse_logical_or()

    def parse_logical_or(self):
        left = self.parse_logical_and()
        while self.peek()[0] == 'KEYWORD' and self.peek()[1] == 'or':
            self.advance()
            right = self.parse_logical_and()
            left = LogicalNode(left, 'or', right)
        return left

    def parse_logical_and(self):
        left = self.parse_comparison()
        while self.peek()[0] == 'KEYWORD' and self.peek()[1] == 'and':
            self.advance()
            right = self.parse_comparison()
            left = LogicalNode(left, 'and', right)
        return left

    def parse_comparison(self):
        left = self.parse_expression()
        if self.peek()[0] in ('EQ', 'NEQ', 'LT', 'GT', 'LTE', 'GTE'):
            op_type, op_val, *_ = self.advance()
            right = self.parse_expression()
            return CompareNode(left, op_val, right)
        return left

    def parse_expression(self):
        left = self.parse_term_mul()
        while self.peek()[0] == 'OP' and self.peek()[1] in ('+', '-'):
            op = self.expect('OP')[1]
            right = self.parse_term_mul()
            left = BinaryOpNode(left, op, right)
        return left

    def parse_term_mul(self):
        left = self.parse_unary()
        while self.peek()[0] == 'OP' and self.peek()[1] in ('*', '/', '%'):
            op = self.expect('OP')[1]
            right = self.parse_unary()
            left = BinaryOpNode(left, op, right)
        return left

    def parse_unary(self):
        if self.peek()[0] == 'KEYWORD' and self.peek()[1] == 'not':
            self.advance()
            operand = self.parse_unary()
            return UnaryOpNode('not', operand)
        if self.peek()[0] == 'OP' and self.peek()[1] == '-':
            self.advance()
            operand = self.parse_unary()
            return UnaryOpNode('-', operand)
        return self.parse_postfix()

    def parse_postfix(self):
        """Parse atom followed by optional [index] or .field chains."""
        node = self.parse_atom()
        while True:
            if self.peek()[0] == 'LBRACKET':
                self.expect('LBRACKET')
                idx = self.parse_full_expression()
                self.expect('RBRACKET')
                node = IndexNode(node, idx)
            elif self.peek()[0] == 'DOT':
                self.expect('DOT')
                field = self.expect('IDENT')[1]
                node = DotAccessNode(node, field)
            else:
                break
        return node

    def parse_atom(self):
        token_type, value, *_ = self.peek()

        if token_type == 'NUMBER':
            self.advance()
            return NumberNode(float(value))
        elif token_type == 'STRING':
            self.advance()
            return StringNode(value[1:-1])
        elif token_type == 'KEYWORD' and value == 'true':
            self.advance()
            return BoolNode(True)
        elif token_type == 'KEYWORD' and value == 'false':
            self.advance()
            return BoolNode(False)
        elif token_type == 'KEYWORD' and value == 'len':
            self.advance()
            arg = self.parse_atom()
            return LenNode(arg)
        elif token_type == 'KEYWORD' and value == 'new':
            self.advance()
            class_name = self.expect('IDENT')[1]
            args = []
            while self.peek()[0] in ('NUMBER', 'IDENT', 'STRING', 'LPAREN'):
                args.append(self.parse_atom())
            return NewNode(class_name, args)
        elif token_type == 'LPAREN':
            self.expect('LPAREN')
            expr = self.parse_full_expression()
            self.expect('RPAREN')
            return expr
        elif token_type == 'LBRACKET':
            return self.parse_list_literal()
        elif token_type == 'IDENT':
            self.advance()
            pk = self.peek()
            # Don't treat as function call if next is [ (that's indexing) or . (dot access)
            if pk[0] in ('LBRACKET', 'DOT'):
                return IdentifierNode(value)
            # Check if function call (next is arg-like)
            if pk[0] in ('NUMBER', 'STRING', 'LPAREN'):
                return self.parse_function_call(value)
            elif pk[0] == 'IDENT':
                return self.parse_function_call(value)
            elif pk[0] == 'KEYWORD' and pk[1] in ('true', 'false', 'not', 'len', 'new'):
                return self.parse_function_call(value)
            else:
                return IdentifierNode(value)
        else:
            raise SyntaxError(f'Unexpected token: {token_type} {repr(value)}')

    def parse_list_literal(self):
        self.expect('LBRACKET')
        elements = []
        while self.peek()[0] != 'RBRACKET':
            elements.append(self.parse_full_expression())
            if self.peek()[0] == 'COMMA':
                self.advance()
        self.expect('RBRACKET')
        return ListNode(elements)

    def parse_term(self):
        """Legacy parse_term for function args — delegates to atom."""
        return self.parse_atom()

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

    # C reserved words that cannot be used as identifiers
    C_RESERVED = frozenset([
        'auto', 'break', 'case', 'char', 'const', 'continue', 'default',
        'do', 'double', 'else', 'enum', 'extern', 'float', 'for', 'goto',
        'if', 'inline', 'int', 'long', 'register', 'restrict', 'return',
        'short', 'signed', 'sizeof', 'static', 'struct', 'switch',
        'typedef', 'union', 'unsigned', 'void', 'volatile', 'while',
        '_Bool', '_Complex', '_Imaginary', 'main', 'printf', 'malloc',
        'free', 'realloc', 'exit', 'fprintf', 'stderr', 'stdout', 'stdin',
        'NULL', 'sizeof', 'memcpy', 'memset', 'strlen', 'strcmp', 'strcat',
        'strcpy', 'setjmp', 'longjmp', 'jmp_buf', 'fmod', 'sqrt', 'floor',
        'ceil', 'abs',
    ])

    # Valid C identifier pattern
    _IDENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

    def __init__(self):
        self.functions = {}       # name -> FunctionNode
        self.classes = {}         # name -> ClassNode
        self.declared_vars = {}   # scope -> set of var names
        self.string_vars = set()  # track which vars hold strings
        self.list_vars = set()    # track which vars hold lists
        self.output_lines = []
        self.indent_level = 0
        self.uses_lists = False
        self.uses_strings = False
        self.uses_try_catch = False
        self._ident_map = {}      # sauravcode name -> safe C name

    def _safe_ident(self, name):
        """Sanitize a sauravcode identifier for safe use in generated C code.

        Prevents C code injection by:
        - Rejecting names that aren't valid identifiers
        - Prefixing names that collide with C reserved words
        - Caching results for consistency
        """
        if name in self._ident_map:
            return self._ident_map[name]

        if not self._IDENT_RE.match(name):
            raise ValueError(
                f"Invalid identifier '{name}': contains characters not "
                f"allowed in C identifiers"
            )

        safe = name
        if safe in self.C_RESERVED or safe.startswith('srv_') or safe.startswith('__'):
            safe = 'u_' + safe

        self._ident_map[name] = safe
        return safe

    def emit(self, line=""):
        self.output_lines.append("    " * self.indent_level + line)

    def scan_features(self, program):
        """Pre-scan AST to detect which features are used."""
        def walk(node):
            if isinstance(node, ListNode) or isinstance(node, AppendNode) or isinstance(node, LenNode) or isinstance(node, PopNode) or isinstance(node, IndexNode) or isinstance(node, IndexedAssignmentNode):
                self.uses_lists = True
            if isinstance(node, StringNode):
                self.uses_strings = True
            if isinstance(node, TryCatchNode):
                self.uses_try_catch = True
            # Walk children
            if isinstance(node, ProgramNode):
                for s in node.statements: walk(s)
            elif isinstance(node, FunctionNode):
                for s in node.body: walk(s)
            elif isinstance(node, ClassNode):
                for s in node.body: walk(s)
            elif isinstance(node, IfNode):
                walk(node.condition)
                for s in node.body: walk(s)
                for cond, body in node.elif_chains:
                    walk(cond)
                    for s in body: walk(s)
                if node.else_body:
                    for s in node.else_body: walk(s)
            elif isinstance(node, WhileNode):
                walk(node.condition)
                for s in node.body: walk(s)
            elif isinstance(node, ForNode):
                walk(node.start); walk(node.end)
                for s in node.body: walk(s)
            elif isinstance(node, TryCatchNode):
                for s in node.try_body: walk(s)
                for s in node.catch_body: walk(s)
            elif isinstance(node, ReturnNode):
                walk(node.expression)
            elif isinstance(node, PrintNode):
                walk(node.expression)
            elif isinstance(node, AssignmentNode):
                walk(node.expression)
            elif isinstance(node, IndexedAssignmentNode):
                walk(node.index); walk(node.value)
            elif isinstance(node, DotAssignmentNode):
                walk(node.obj); walk(node.value)
            elif isinstance(node, BinaryOpNode):
                walk(node.left); walk(node.right)
            elif isinstance(node, UnaryOpNode):
                walk(node.operand)
            elif isinstance(node, CompareNode):
                walk(node.left); walk(node.right)
            elif isinstance(node, LogicalNode):
                walk(node.left); walk(node.right)
            elif isinstance(node, FunctionCallNode):
                for a in node.arguments: walk(a)
            elif isinstance(node, AppendNode):
                walk(node.value)
            elif isinstance(node, LenNode):
                walk(node.expression)
            elif isinstance(node, ListNode):
                for e in node.elements: walk(e)
            elif isinstance(node, IndexNode):
                walk(node.obj); walk(node.index)
        walk(program)

    def compile(self, program):
        """Generate complete C source from a ProgramNode."""
        # Pre-scan for features
        self.scan_features(program)

        # First pass: collect all function/class definitions
        top_level = []
        for stmt in program.statements:
            if isinstance(stmt, FunctionNode):
                self.functions[stmt.name] = stmt
            elif isinstance(stmt, ClassNode):
                self.classes[stmt.name] = stmt
            else:
                top_level.append(stmt)

        # Emit C headers
        self.emit("#include <stdio.h>")
        self.emit("#include <stdlib.h>")
        self.emit("#include <string.h>")
        self.emit("#include <math.h>")
        if self.uses_try_catch:
            self.emit("#include <setjmp.h>")
        self.emit("")

        # Emit dynamic list support if needed
        if self.uses_lists:
            self.emit_list_runtime()

        # Emit try/catch support if needed
        if self.uses_try_catch:
            self.emit("/* Try/catch support */")
            self.emit("static jmp_buf __catch_buf;")
            self.emit("static int __has_error = 0;")
            self.emit("static char __error_msg[256] = \"\";")
            self.emit("")

        # Emit class structs
        for name, cls in self.classes.items():
            self.emit_class_struct(cls)

        # Emit forward declarations for functions
        for name, func in self.functions.items():
            safe_name = self._safe_ident(name)
            params = ", ".join("double " + self._safe_ident(p) for p in func.params)
            if not params:
                params = "void"
            self.emit(f"double {safe_name}({params});")
        self.emit("")

        # Emit function definitions
        for name, func in self.functions.items():
            self.compile_function(func)
            self.emit("")

        # Emit class method implementations
        for name, cls in self.classes.items():
            self.emit_class_methods(cls)

        # Emit main()
        self.emit("int main(void) {")
        self.indent_level += 1
        self.declared_vars['main'] = set()

        for stmt in top_level:
            self.compile_statement(stmt, scope='main', is_top_level=True)

        self.emit("return 0;")
        self.indent_level -= 1
        self.emit("}")
        self.emit("")

        return "\n".join(self.output_lines)

    def emit_list_runtime(self):
        """Emit a simple dynamic array (list) implementation in C."""
        self.emit("/* Dynamic list runtime */")
        self.emit("typedef struct {")
        self.emit("    double *data;")
        self.emit("    int size;")
        self.emit("    int capacity;")
        self.emit("} SrvList;")
        self.emit("")
        self.emit("SrvList srv_list_new(void) {")
        self.emit("    SrvList l;")
        self.emit("    l.capacity = 8;")
        self.emit("    l.size = 0;")
        self.emit("    l.data = (double*)malloc(sizeof(double) * l.capacity);")
        self.emit("    return l;")
        self.emit("}")
        self.emit("")
        self.emit("void srv_list_append(SrvList *l, double val) {")
        self.emit("    if (l->size >= l->capacity) {")
        self.emit("        l->capacity *= 2;")
        self.emit("        l->data = (double*)realloc(l->data, sizeof(double) * l->capacity);")
        self.emit("    }")
        self.emit("    l->data[l->size++] = val;")
        self.emit("}")
        self.emit("")
        self.emit("double srv_list_get(SrvList *l, int idx) {")
        self.emit("    if (idx < 0 || idx >= l->size) {")
        self.emit('        fprintf(stderr, "Index %d out of bounds (size %d)\\n", idx, l->size);')
        self.emit("        exit(1);")
        self.emit("    }")
        self.emit("    return l->data[idx];")
        self.emit("}")
        self.emit("")
        self.emit("void srv_list_set(SrvList *l, int idx, double val) {")
        self.emit("    if (idx < 0 || idx >= l->size) {")
        self.emit('        fprintf(stderr, "Index %d out of bounds (size %d)\\n", idx, l->size);')
        self.emit("        exit(1);")
        self.emit("    }")
        self.emit("    l->data[idx] = val;")
        self.emit("}")
        self.emit("")
        self.emit("double srv_list_pop(SrvList *l) {")
        self.emit("    if (l->size == 0) {")
        self.emit('        fprintf(stderr, "Pop from empty list\\n");')
        self.emit("        exit(1);")
        self.emit("    }")
        self.emit("    return l->data[--l->size];")
        self.emit("}")
        self.emit("")
        self.emit("int srv_list_len(SrvList *l) {")
        self.emit("    return l->size;")
        self.emit("}")
        self.emit("")
        self.emit("void srv_list_free(SrvList *l) {")
        self.emit("    free(l->data);")
        self.emit("    l->data = NULL;")
        self.emit("    l->size = 0;")
        self.emit("    l->capacity = 0;")
        self.emit("}")
        self.emit("")

    def emit_class_struct(self, cls):
        """Emit a C struct for a sauravcode class."""
        self.emit(f"typedef struct {{")
        self.indent_level += 1
        # Collect field names from init method or all methods
        fields = set()
        for stmt in cls.body:
            if isinstance(stmt, FunctionNode):
                for s in stmt.body:
                    if isinstance(s, AssignmentNode) and isinstance(s.name, str) and s.name.startswith('self.'):
                        fields.add(s.name[5:])
        if not fields:
            self.emit("double __placeholder;")
        for f in sorted(fields):
            self.emit(f"double {f};")
        self.indent_level -= 1
        self.emit(f"}} {cls.name};")
        self.emit("")

    def emit_class_methods(self, cls):
        """Emit C functions for class methods."""
        for stmt in cls.body:
            if isinstance(stmt, FunctionNode):
                method_name = f"{cls.name}_{stmt.name}"
                params = [f"{cls.name} *self"]
                for p in stmt.params:
                    if p != 'self':
                        params.append(f"double {p}")
                params_str = ", ".join(params)
                self.emit(f"double {method_name}({params_str}) {{")
                self.indent_level += 1
                scope = method_name
                self.declared_vars[scope] = set(stmt.params)
                for s in stmt.body:
                    self.compile_statement(s, scope=scope)
                self.indent_level -= 1
                self.emit("}")
                self.emit("")

    def compile_function(self, func):
        """Emit a C function definition."""
        safe_name = self._safe_ident(func.name)
        params = ", ".join(f"double {self._safe_ident(p)}" for p in func.params)
        if not params:
            params = "void"
        self.emit(f"double {safe_name}({params}) {{")
        self.indent_level += 1
        self.declared_vars[func.name] = set(func.params)

        for stmt in func.body:
            self.compile_statement(stmt, scope=func.name)

        # Add implicit return 0 if no return found
        has_return = any(isinstance(s, ReturnNode) for s in func.body)
        if not has_return:
            self.emit("return 0;")

        self.indent_level -= 1
        self.emit("}")

    def compile_statement(self, stmt, scope='main', is_top_level=False):
        """Compile a single statement to C."""
        if isinstance(stmt, IndexedAssignmentNode):
            name = self._safe_ident(stmt.name)
            idx_c = self.compile_expression(stmt.index)
            val_c = self.compile_expression(stmt.value)
            self.emit(f"srv_list_set(&{name}, (int)({idx_c}), {val_c});")

        elif isinstance(stmt, DotAssignmentNode):
            obj_c = self.compile_expression(stmt.obj)
            field = self._safe_ident(stmt.field)
            val_c = self.compile_expression(stmt.value)
            self.emit(f"{obj_c}.{field} = {val_c};")

        elif isinstance(stmt, AssignmentNode):
            expr_c = self.compile_expression(stmt.expression)
            name = self._safe_ident(stmt.name)
            if stmt.name not in self.declared_vars.get(scope, set()):
                # Detect type from expression
                if isinstance(stmt.expression, StringNode):
                    self.emit(f'const char *{name} = {expr_c};')
                    self.string_vars.add(stmt.name)
                elif isinstance(stmt.expression, BoolNode):
                    self.emit(f'int {name} = {expr_c};')
                elif isinstance(stmt.expression, ListNode):
                    self.emit(f'SrvList {name} = srv_list_new();')
                    self.list_vars.add(stmt.name)
                    for elem in stmt.expression.elements:
                        elem_c = self.compile_expression(elem)
                        self.emit(f'srv_list_append(&{name}, {elem_c});')
                else:
                    self.emit(f"double {name} = {expr_c};")
                self.declared_vars.setdefault(scope, set()).add(stmt.name)
            else:
                if isinstance(stmt.expression, ListNode):
                    # Reassigning a list
                    self.emit(f'{name} = srv_list_new();')
                    for elem in stmt.expression.elements:
                        elem_c = self.compile_expression(elem)
                        self.emit(f'srv_list_append(&{name}, {elem_c});')
                else:
                    self.emit(f"{name} = {expr_c};")

        elif isinstance(stmt, ReturnNode):
            expr_c = self.compile_expression(stmt.expression)
            self.emit(f"return {expr_c};")

        elif isinstance(stmt, PrintNode):
            self.compile_print(stmt)

        elif isinstance(stmt, FunctionCallNode):
            call_c = self.compile_call(stmt)
            if is_top_level:
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

            for elif_cond, elif_body in stmt.elif_chains:
                elif_c = self.compile_expression(elif_cond)
                self.emit(f"}} else if ({elif_c}) {{")
                self.indent_level += 1
                for s in elif_body:
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
            var = self._safe_ident(stmt.var)
            self.declared_vars.setdefault(scope, set()).add(stmt.var)
            self.emit(f"for (double {var} = {start_c}; {var} < {end_c}; {var}++) {{")
            self.indent_level += 1
            for s in stmt.body:
                self.compile_statement(s, scope=scope)
            self.indent_level -= 1
            self.emit("}")

        elif isinstance(stmt, TryCatchNode):
            self.emit("__has_error = 0;")
            self.emit("if (setjmp(__catch_buf) == 0) {")
            self.indent_level += 1
            for s in stmt.try_body:
                self.compile_statement(s, scope=scope)
            self.indent_level -= 1
            self.emit("} else {")
            self.indent_level += 1
            if stmt.catch_var:
                safe_catch = self._safe_ident(stmt.catch_var)
                if stmt.catch_var not in self.declared_vars.get(scope, set()):
                    self.emit(f'const char *{safe_catch} = __error_msg;')
                    self.declared_vars.setdefault(scope, set()).add(stmt.catch_var)
                else:
                    self.emit(f'{safe_catch} = __error_msg;')
            for s in stmt.catch_body:
                self.compile_statement(s, scope=scope)
            self.indent_level -= 1
            self.emit("}")

        elif isinstance(stmt, AppendNode):
            safe_list = self._safe_ident(stmt.list_name)
            val_c = self.compile_expression(stmt.value)
            self.emit(f"srv_list_append(&{safe_list}, {val_c});")

        elif isinstance(stmt, ClassNode):
            pass  # Already handled in first pass

    def compile_print(self, stmt):
        """Smart print that detects type."""
        expr = stmt.expression
        expr_c = self.compile_expression(expr)

        if isinstance(expr, StringNode):
            self.emit(f'printf("%s\\n", {expr_c});')
        elif isinstance(expr, BoolNode):
            self.emit(f'printf("%s\\n", {expr_c} ? "true" : "false");')
        elif isinstance(expr, IdentifierNode) and expr.name in self.string_vars:
            self.emit(f'printf("%s\\n", {expr_c});')
        elif isinstance(expr, IdentifierNode) and expr.name in self.list_vars:
            self.emit(f'printf("[list: %d items]\\n", srv_list_len(&{expr_c}));')
        else:
            self.emit(f'printf("%.10g\\n", (double)({expr_c}));')

    def compile_expression(self, expr):
        """Compile an expression to a C expression string."""
        if isinstance(expr, NumberNode):
            if expr.value == int(expr.value):
                return str(int(expr.value))
            return str(expr.value)

        elif isinstance(expr, StringNode):
            # Escape the string for C
            escaped = expr.value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
            return f'"{escaped}"'

        elif isinstance(expr, BoolNode):
            return "1" if expr.value else "0"

        elif isinstance(expr, IdentifierNode):
            return self._safe_ident(expr.name)

        elif isinstance(expr, BinaryOpNode):
            left_c = self.compile_expression(expr.left)
            right_c = self.compile_expression(expr.right)
            if expr.operator == '%':
                return f"fmod({left_c}, {right_c})"
            return f"({left_c} {expr.operator} {right_c})"

        elif isinstance(expr, UnaryOpNode):
            operand_c = self.compile_expression(expr.operand)
            if expr.operator == 'not':
                return f"(!({operand_c}))"
            elif expr.operator == '-':
                return f"(-({operand_c}))"
            return operand_c

        elif isinstance(expr, CompareNode):
            left_c = self.compile_expression(expr.left)
            right_c = self.compile_expression(expr.right)
            return f"({left_c} {expr.operator} {right_c})"

        elif isinstance(expr, LogicalNode):
            left_c = self.compile_expression(expr.left)
            right_c = self.compile_expression(expr.right)
            op = '&&' if expr.operator == 'and' else '||'
            return f"({left_c} {op} {right_c})"

        elif isinstance(expr, FunctionCallNode):
            return self.compile_call(expr)

        elif isinstance(expr, ListNode):
            # List literal in expression context — handled differently
            return "srv_list_new()"  # Placeholder; actual init in assignment

        elif isinstance(expr, IndexNode):
            obj_c = self.compile_expression(expr.obj)
            idx_c = self.compile_expression(expr.index)
            return f"srv_list_get(&{obj_c}, (int)({idx_c}))"

        elif isinstance(expr, LenNode):
            inner = self.compile_expression(expr.expression)
            return f"srv_list_len(&{inner})"

        elif isinstance(expr, DotAccessNode):
            obj_c = self.compile_expression(expr.obj)
            field = self._safe_ident(expr.field)
            return f"{obj_c}.{field}"

        elif isinstance(expr, MethodCallNode):
            obj_c = self.compile_expression(expr.obj)
            args_c = ", ".join(self.compile_expression(a) for a in expr.arguments)
            return f"{obj_c}_{expr.method}(&{obj_c}, {args_c})"

        else:
            raise ValueError(f"Unknown expression type: {type(expr).__name__}")

    def compile_call(self, call):
        """Compile a function call to C."""
        safe_name = self._safe_ident(call.name)
        args_c = ", ".join(self.compile_expression(a) for a in call.arguments)
        return f"{safe_name}({args_c})"


# ============================================================
# MAIN - CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="sauravcc - The Sauravcode Compiler v2 (compiles .srv to C to native)",
        prog="sauravcc"
    )
    parser.add_argument("file", help="Source file (.srv)")
    parser.add_argument("--emit-c", action="store_true", help="Print generated C code and exit")
    parser.add_argument("-o", "--output", help="Output executable name")
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

    with open(args.file, 'r') as f:
        code = f.read()

    if args.verbose:
        print(f"[sauravcc] Compiling {args.file}...")

    tokens = tokenize(code)
    if args.verbose:
        print(f"[sauravcc] {len(tokens)} tokens")

    ast_parser = Parser(tokens)
    program = ast_parser.parse()
    if args.verbose:
        print(f"[sauravcc] {len(program.statements)} top-level statements")

    codegen = CCodeGenerator()
    c_code = codegen.compile(program)

    if args.emit_c:
        print(c_code)
        return

    base = os.path.splitext(args.file)[0]
    c_file = base + ".c"
    with open(c_file, 'w') as f:
        f.write(c_code)

    if args.verbose:
        print(f"[sauravcc] Generated {c_file}")

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

    if not args.keep_c:
        os.remove(c_file)

    if args.verbose:
        print(f"[sauravcc] Running {out_name}...\n")

    run_result = subprocess.run([os.path.abspath(out_name)], capture_output=False)
    sys.exit(run_result.returncode)


if __name__ == '__main__':
    main()
