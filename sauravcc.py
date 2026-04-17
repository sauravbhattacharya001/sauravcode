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
    ('FSTRING',  r'f\"(?:[^\"\\]|\\.)*\"'),   # f-string: f"..." (must come before STRING)
    ('STRING',   r'\"(?:[^\"\\]|\\.)*\"'),     # String with escape support
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
    ('LBRACE',   r'\{'),
    ('RBRACE',   r'\}'),
    ('COLON',    r':'),
    ('DOT',      r'\.'),
    ('COMMA',    r','),
    ('KEYWORD',  r'\b(?:function|return|class|new|self|int|float|bool|string|if|else if|else|for|in|while|try|catch|throw|print|true|false|and|or|not|list|set|map|stack|queue|append|len|pop|get|break|continue|assert|enum)\b'),
    ('IDENT',    r'[a-zA-Z_]\w*'),
    ('NEWLINE',  r'\n'),
    ('SKIP',     r'[ \t]+'),
    ('MISMATCH', r'.'),
]

tok_regex = re.compile('|'.join(f'(?P<{pair[0]}>{pair[1]})' for pair in token_specification))
_indent_re = re.compile(r'[ \t]*')


def tokenize(code):
    tokens = []
    line_num = 1
    line_start = 0
    indent_levels = [0]

    for match in tok_regex.finditer(code):
        typ = match.lastgroup
        value = match.group(typ)

        if typ == 'NEWLINE':
            line_num += 1
            line_start = match.end()
            tokens.append(('NEWLINE', value, line_num, match.start()))

            indent_match = _indent_re.match(code, line_start)
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
    def children(self):
        """Yield all child ASTNode instances for generic tree walking."""
        for val in self.__dict__.values():
            if isinstance(val, ASTNode):
                yield val
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, ASTNode):
                        yield item
                    elif isinstance(item, tuple):
                        for elem in item:
                            if isinstance(elem, ASTNode):
                                yield elem
                            elif isinstance(elem, list):
                                for sub in elem:
                                    if isinstance(sub, ASTNode):
                                        yield sub

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

class ThrowNode(ASTNode):
    """Throw an error with a message expression."""
    def __init__(self, expression):
        self.expression = expression

class AssertNode(ASTNode):
    """Assert that a condition is true, with optional error message."""
    def __init__(self, condition, message=None):
        self.condition = condition
        self.message = message

class EnumNode(ASTNode):
    """Enum type definition with auto-incrementing integer variants."""
    def __init__(self, name, variants):
        self.name = name
        self.variants = variants

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

class FStringNode(ASTNode):
    """Interpolated string: f"Hello {name}, you are {age} years old"
    parts is a list of ASTNode — StringNode for literal text, others for expressions.
    """
    def __init__(self, parts):
        self.parts = parts  # list of ASTNode

class MapNode(ASTNode):
    """Map literal: { key: value, key2: value2 }"""
    def __init__(self, pairs):
        self.pairs = pairs  # list of (key_expr, value_expr) tuples

class ForEachNode(ASTNode):
    """For-each iteration: for item in collection"""
    def __init__(self, var, iterable, body):
        self.var = var          # variable name
        self.iterable = iterable  # expression (list, map, or string)
        self.body = body        # list of statements


class BreakNode(ASTNode):
    pass

class ContinueNode(ASTNode):
    pass

class TernaryNode(ASTNode):
    def __init__(self, condition, true_expr, false_expr):
        self.condition = condition
        self.true_expr = true_expr
        self.false_expr = false_expr


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
        elif token_type == 'KEYWORD' and value == 'break':
            self.expect('KEYWORD', 'break')
            return BreakNode()
        elif token_type == 'KEYWORD' and value == 'continue':
            self.expect('KEYWORD', 'continue')
            return ContinueNode()
        elif token_type == 'KEYWORD' and value == 'try':
            return self.parse_try()
        elif token_type == 'KEYWORD' and value == 'throw':
            return self.parse_throw()
        elif token_type == 'KEYWORD' and value == 'assert':
            return self.parse_assert()
        elif token_type == 'KEYWORD' and value == 'enum':
            return self.parse_enum()
        elif token_type == 'KEYWORD' and value == 'append':
            return self.parse_append()
        elif token_type == 'KEYWORD' and value == 'pop':
            return self.parse_pop()
        elif token_type == 'KEYWORD' and value == 'self':
            return self.parse_self_statement()
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
        # Check for for-each syntax: for item in collection
        if self.peek()[0] == 'KEYWORD' and self.peek()[1] == 'in':
            self.expect('KEYWORD', 'in')
            iterable = self.parse_full_expression()
            self.expect('NEWLINE')
            self.expect('INDENT')
            body = self.parse_block()
            self.expect('DEDENT')
            return ForEachNode(var, iterable, body)
        # Legacy range-based for loop: for i 0 10
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

    def parse_throw(self):
        """Parse throw statement: throw expression"""
        self.expect('KEYWORD', 'throw')
        expression = self.parse_expression()
        return ThrowNode(expression)

    def parse_assert(self):
        """Parse assert statement: assert condition [message]"""
        self.expect('KEYWORD', 'assert')
        condition = self.parse_full_expression()
        message = None
        if self.pos < len(self.tokens):
            next_tok = self.peek()
            if next_tok[0] == 'STRING':
                message = StringNode(next_tok[1][1:-1])
                self.advance()
            elif next_tok[0] == 'FSTRING':
                message = self.parse_fstring(self.advance()[1])
        return AssertNode(condition, message)

    def parse_enum(self):
        """Parse enum definition: enum Name followed by indented variants."""
        self.expect('KEYWORD', 'enum')
        name = self.expect('IDENT')[1]
        self.expect('NEWLINE')
        self.expect('INDENT')

        variants = []
        while self.pos < len(self.tokens):
            self.skip_newlines()
            if self.pos >= len(self.tokens):
                break
            pk = self.peek()
            if pk[0] == 'DEDENT':
                break
            if pk[0] == 'IDENT':
                variants.append(self.expect('IDENT')[1])
            else:
                break

        if not variants:
            raise SyntaxError(f"Enum '{name}' must have at least one variant")

        self.expect('DEDENT')
        return EnumNode(name, variants)

    def parse_append(self):
        self.expect('KEYWORD', 'append')
        list_name = self.expect('IDENT')[1]
        value = self.parse_full_expression()
        return AppendNode(list_name, value)

    def parse_pop(self):
        self.expect('KEYWORD', 'pop')
        list_name = self.expect('IDENT')[1]
        return PopNode(list_name)

    def parse_self_statement(self):
        """Parse self.field = val as a DotAssignmentNode."""
        self.expect('KEYWORD', 'self')
        self.expect('DOT')
        field = self.expect('IDENT')[1]
        self.expect('ASSIGN')
        val = self.parse_full_expression()
        return DotAssignmentNode(IdentifierNode('self'), field, val)

    def parse_dot_chain(self, obj):
        """Parse obj.field or obj.method args"""
        while self.peek()[0] == 'DOT':
            self.expect('DOT')
            field = self.expect('IDENT')[1]
            # Check if it's a method call (next token is arg-like)
            if self.peek()[0] in ('NUMBER', 'IDENT', 'STRING', 'FSTRING', 'LPAREN', 'KEYWORD'):
                pk = self.peek()
                if pk[0] == 'KEYWORD' and pk[1] in ('true', 'false'):
                    args = [self.parse_term()]
                elif pk[0] in ('NUMBER', 'IDENT', 'STRING', 'FSTRING', 'LPAREN'):
                    args = []
                    while self.peek()[0] in ('NUMBER', 'IDENT', 'STRING', 'FSTRING', 'LPAREN'):
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
        while self.peek()[0] in ('NUMBER', 'IDENT', 'STRING', 'FSTRING', 'LPAREN', 'LBRACKET', 'KEYWORD'):
            pk = self.peek()
            if pk[0] == 'KEYWORD' and pk[1] in ('true', 'false', 'not', 'len', 'new', 'pop', 'self'):
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
        elif token_type == 'KEYWORD' and value == 'pop':
            self.advance()
            list_name = self.expect('IDENT')[1]
            return PopNode(list_name)
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
        return self.parse_ternary()

    def parse_ternary(self):
        true_expr = self.parse_logical_or()
        if self.peek()[0] == 'KEYWORD' and self.peek()[1] == 'if':
            self.advance()
            condition = self.parse_logical_or()
            if self.peek()[0] == 'KEYWORD' and self.peek()[1] == 'else':
                self.advance()
                false_expr = self.parse_ternary()
                return TernaryNode(condition, true_expr, false_expr)
            else:
                raise SyntaxError("Expected 'else' in ternary expression")
        return true_expr

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
        elif token_type == 'FSTRING':
            self.advance()
            return self.parse_fstring(value)
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
            while self.peek()[0] in ('NUMBER', 'IDENT', 'STRING', 'FSTRING', 'LPAREN'):
                args.append(self.parse_atom())
            return NewNode(class_name, args)
        elif token_type == 'KEYWORD' and value == 'pop':
            self.advance()
            list_name = self.expect('IDENT')[1]
            return PopNode(list_name)
        elif token_type == 'KEYWORD' and value == 'self':
            self.advance()
            return IdentifierNode('self')
        elif token_type == 'LPAREN':
            self.expect('LPAREN')
            expr = self.parse_full_expression()
            self.expect('RPAREN')
            return expr
        elif token_type == 'LBRACKET':
            return self.parse_list_literal()
        elif token_type == 'LBRACE':
            return self.parse_map_literal()
        elif token_type == 'IDENT':
            self.advance()
            pk = self.peek()
            # Don't treat as function call if next is [ (that's indexing) or . (dot access)
            if pk[0] in ('LBRACKET', 'DOT'):
                return IdentifierNode(value)
            # Check if function call (next is arg-like)
            if pk[0] in ('NUMBER', 'STRING', 'FSTRING', 'LPAREN'):
                return self.parse_function_call(value)
            elif pk[0] == 'IDENT':
                return self.parse_function_call(value)
            elif pk[0] == 'KEYWORD' and pk[1] in ('true', 'false', 'not', 'len', 'new', 'pop', 'self'):
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

    def parse_map_literal(self):
        """Parse a map literal: { key: value, key2: value2 }"""
        self.expect('LBRACE')
        pairs = []
        while self.peek()[0] != 'RBRACE':
            key = self.parse_full_expression()
            self.expect('COLON')
            val = self.parse_full_expression()
            pairs.append((key, val))
            if self.peek()[0] == 'COMMA':
                self.advance()
        self.expect('RBRACE')
        return MapNode(pairs)

    def parse_fstring(self, raw_value):
        """Parse an f-string token into an FStringNode.

        raw_value is the full token text like: f"Hello {name}, age {age + 1}"
        We strip the f" prefix and " suffix, then split on { } delimiters,
        parsing the expressions inside { } as sauravcode expressions.
        """
        # Strip the f" prefix and " suffix
        content = raw_value[2:-1]

        parts = []
        i = 0
        text_buf = []

        while i < len(content):
            ch = content[i]
            if ch == '\\' and i + 1 < len(content):
                text_buf.append(content[i + 1])
                i += 2
            elif ch == '{':
                if i + 1 < len(content) and content[i + 1] == '{':
                    text_buf.append('{')
                    i += 2
                    continue
                if text_buf:
                    parts.append(StringNode(''.join(text_buf)))
                    text_buf = []
                depth = 1
                j = i + 1
                while j < len(content) and depth > 0:
                    if content[j] == '{':
                        depth += 1
                    elif content[j] == '}':
                        depth -= 1
                    j += 1
                if depth != 0:
                    raise SyntaxError("Unmatched '{' in f-string")
                expr_text = content[i + 1:j - 1].strip()
                if not expr_text:
                    raise SyntaxError("Empty expression in f-string")
                expr_code = expr_text + '\n'
                expr_tokens = list(tokenize(expr_code))
                expr_parser = Parser(expr_tokens)
                expr_node = expr_parser.parse_full_expression()
                parts.append(expr_node)
                i = j
            elif ch == '}':
                if i + 1 < len(content) and content[i + 1] == '}':
                    text_buf.append('}')
                    i += 2
                    continue
                raise SyntaxError("Unmatched '}' in f-string")
            else:
                text_buf.append(ch)
                i += 1

        if text_buf:
            parts.append(StringNode(''.join(text_buf)))

        return FStringNode(parts)

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
        'ceil', 'abs', 'round', 'pow', 'atof', 'toupper', 'tolower',
    ])

    # Valid C identifier pattern
    _IDENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

    def __init__(self):
        self.functions = {}       # name -> FunctionNode
        self.classes = {}         # name -> ClassNode
        self.enums = {}           # name -> {variant: index}
        self.declared_vars = {}   # scope -> set of var names
        self.string_vars = set()  # track which vars hold strings
        self.string_params = {}   # func_name -> set of param indices that receive strings
        self.list_vars = set()    # track which vars hold lists
        self.map_vars = set()     # track which vars hold maps
        self.output_lines = []
        self.indent_level = 0
        self.uses_lists = False
        self.uses_strings = False
        self.uses_try_catch = False
        self.uses_string_helpers = False
        self.uses_fstring = False
        self.uses_maps = False
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

    def _is_string_expr(self, expr):
        """Return True if *expr* is known to produce a string (const char*) in C.

        Used to decide whether comparisons should emit strcmp() instead of
        the default numeric == / < / > operators.
        """
        if isinstance(expr, StringNode):
            return True
        if isinstance(expr, FStringNode):
            return True
        if isinstance(expr, IdentifierNode) and expr.name in self.string_vars:
            return True
        if isinstance(expr, FunctionCallNode) and expr.name in self.STRING_RETURNING_BUILTINS:
            return True
        return False

    def _build_param_list(self, func_name, params):
        """Build a C parameter list string for a function signature.

        Deduplicates the logic previously repeated in compile() for forward
        declarations and in compile_function() for definitions.
        """
        string_indices = self.string_params.get(func_name, set())
        parts = []
        for i, p in enumerate(params):
            c_type = "const char *" if i in string_indices else "double "
            parts.append(c_type + self._safe_ident(p))
        return ", ".join(parts) if parts else "void"

    def _infer_c_type(self, expression):
        """Infer the C type category for a sauravcode expression.

        Returns one of: 'string', 'const_string', 'fstring', 'bool',
        'list', 'map', 'string_func', 'split', 'double'.
        Used to emit correct C declarations for first assignments.
        """
        if isinstance(expression, StringNode):
            return 'const_string'
        if isinstance(expression, FStringNode):
            return 'fstring'
        if isinstance(expression, BoolNode):
            return 'bool'
        if isinstance(expression, ListNode):
            return 'list'
        if isinstance(expression, MapNode):
            return 'map'
        if isinstance(expression, FunctionCallNode):
            if expression.name in self.STRING_RETURNING_BUILTINS:
                return 'string_func'
            if expression.name == 'split':
                return 'split'
        return 'double'

    def _emit_first_declaration(self, name, expression, expr_c, scope):
        """Emit a C variable declaration for the first assignment of *name*.

        Determines the correct C type from *expression*, emits the declaration,
        and updates type-tracking sets (string_vars, list_vars, map_vars).
        """
        safe = self._safe_ident(name)
        ctype = self._infer_c_type(expression)

        if ctype == 'const_string':
            self.emit(f'const char *{safe} = {expr_c};')
            self.string_vars.add(name)
        elif ctype == 'fstring':
            self.emit(f'char *{safe} = {expr_c};')
            self.string_vars.add(name)
        elif ctype == 'bool':
            self.emit(f'int {safe} = {expr_c};')
        elif ctype == 'list':
            self.emit(f'SrvList {safe} = srv_list_new();')
            self.list_vars.add(name)
            for elem in expression.elements:
                self.emit(f'srv_list_append(&{safe}, {self.compile_expression(elem)});')
        elif ctype == 'map':
            self.emit(f'SrvMap {safe} = srv_map_new();')
            self.map_vars.add(name)
            for key_expr, val_expr in expression.pairs:
                self.emit(f'srv_map_set(&{safe}, {self.compile_expression(key_expr)}, {self.compile_expression(val_expr)});')
        elif ctype == 'string_func':
            self.emit(f'char *{safe} = {expr_c};')
            self.string_vars.add(name)
        elif ctype == 'split':
            self.emit(f'SrvList {safe} = {expr_c};')
            self.list_vars.add(name)
        else:
            self.emit(f'double {safe} = {expr_c};')

        self.declared_vars.setdefault(scope, set()).add(name)

    def _emit_reassignment(self, name, expression, expr_c):
        """Emit a C reassignment for an already-declared variable *name*."""
        safe = self._safe_ident(name)
        if isinstance(expression, ListNode):
            self.emit(f'{safe} = srv_list_new();')
            for elem in expression.elements:
                self.emit(f'srv_list_append(&{safe}, {self.compile_expression(elem)});')
        elif isinstance(expression, MapNode):
            self.emit(f'{safe} = srv_map_new();')
            for key_expr, val_expr in expression.pairs:
                self.emit(f'srv_map_set(&{safe}, {self.compile_expression(key_expr)}, {self.compile_expression(val_expr)});')
        else:
            self.emit(f'{safe} = {expr_c};')

    def emit(self, line=""):
        self.output_lines.append("    " * self.indent_level + line)

    def scan_features(self, program):
        """Pre-scan AST to detect which features are used.

        Uses the generic ``ASTNode.children()`` walker instead of
        manually listing every node type, making this automatically
        correct for new AST nodes.
        """
        # Map node types to the feature flags they trigger
        _LIST_NODES = (ListNode, AppendNode, LenNode, PopNode, IndexNode, IndexedAssignmentNode)
        _TRY_NODES = (TryCatchNode, ThrowNode)

        def walk(node):
            if isinstance(node, _LIST_NODES):
                self.uses_lists = True
            if isinstance(node, MapNode):
                self.uses_maps = True
            if isinstance(node, FunctionCallNode) and node.name in ('keys', 'values', 'has_key'):
                self.uses_maps = True
            if isinstance(node, ForEachNode):
                self.uses_lists = True
                self.uses_maps = True
            if isinstance(node, StringNode):
                self.uses_strings = True
            if isinstance(node, _TRY_NODES):
                self.uses_try_catch = True
            if isinstance(node, FunctionCallNode):
                if node.name in self.STRING_RETURNING_BUILTINS or node.name in ('contains', 'index_of', 'split'):
                    self.uses_string_helpers = True
            if isinstance(node, FStringNode):
                self.uses_fstring = True
            # Generic child traversal — no need to enumerate every node type
            for child in node.children():
                walk(child)

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
            elif isinstance(stmt, EnumNode):
                self.enums[stmt.name] = {v: i for i, v in enumerate(stmt.variants)}
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

        # Emit checked-malloc helper (used by list/map runtimes)
        self.emit("/* Checked allocation — aborts on OOM */")
        self.emit("static void* srv_checked_malloc(size_t n) {")
        self.emit("    void* p = malloc(n);")
        self.emit('    if (!p) { fprintf(stderr, "Out of memory (requested %zu bytes)\\n", n); exit(1); }')
        self.emit("    return p;")
        self.emit("}")
        self.emit("static void* srv_checked_realloc(void* ptr, size_t n) {")
        self.emit("    void* p = realloc(ptr, n);")
        self.emit('    if (!p) { fprintf(stderr, "Out of memory (realloc %zu bytes)\\n", n); exit(1); }')
        self.emit("    return p;")
        self.emit("}")
        self.emit("")

        # Emit arena allocator for string memory management
        if self.uses_string_helpers or getattr(self, 'uses_fstring', False):
            self.emit("/* Arena allocator — all string allocations go through here */")
            self.emit("/* and are freed in one shot at program exit.              */")
            self.emit("#define SRV_ARENA_BLOCK_SIZE (64 * 1024)  /* 64 KB blocks */")
            self.emit("typedef struct SrvArenaBlock {")
            self.emit("    struct SrvArenaBlock* next;")
            self.emit("    size_t used;")
            self.emit("    size_t capacity;")
            self.emit("    char data[];  /* flexible array member */")
            self.emit("} SrvArenaBlock;")
            self.emit("")
            self.emit("static SrvArenaBlock* __arena_head = NULL;")
            self.emit("")
            self.emit("static SrvArenaBlock* srv_arena_new_block(size_t min_size) {")
            self.emit("    size_t cap = min_size > SRV_ARENA_BLOCK_SIZE ? min_size : SRV_ARENA_BLOCK_SIZE;")
            self.emit("    SrvArenaBlock* b = (SrvArenaBlock*)malloc(sizeof(SrvArenaBlock) + cap);")
            self.emit('    if (!b) { fprintf(stderr, "Out of memory (arena block %zu bytes)\\n", cap); exit(1); }')
            self.emit("    b->next = __arena_head;")
            self.emit("    b->used = 0;")
            self.emit("    b->capacity = cap;")
            self.emit("    __arena_head = b;")
            self.emit("    return b;")
            self.emit("}")
            self.emit("")
            self.emit("static void* srv_arena_alloc(size_t n) {")
            self.emit("    /* Align to 8 bytes */")
            self.emit("    n = (n + 7) & ~(size_t)7;")
            self.emit("    SrvArenaBlock* b = __arena_head;")
            self.emit("    if (!b || b->used + n > b->capacity)")
            self.emit("        b = srv_arena_new_block(n);")
            self.emit("    void* p = b->data + b->used;")
            self.emit("    b->used += n;")
            self.emit("    return p;")
            self.emit("}")
            self.emit("")
            self.emit("static void srv_arena_free_all(void) {")
            self.emit("    SrvArenaBlock* b = __arena_head;")
            self.emit("    while (b) {")
            self.emit("        SrvArenaBlock* next = b->next;")
            self.emit("        free(b);")
            self.emit("        b = next;")
            self.emit("    }")
            self.emit("    __arena_head = NULL;")
            self.emit("}")
            self.emit("")

        # Emit dynamic list support if needed
        if self.uses_lists:
            self.emit_list_runtime()

        # Emit map (hash map) support if needed
        if self.uses_maps:
            self.emit_map_runtime()

        # Emit string helper functions if needed
        # String helpers (srv_split/srv_join) depend on SrvList, so force list runtime
        if self.uses_string_helpers:
            if not self.uses_lists:
                self.uses_lists = True
                self.emit_list_runtime()
            self.emit_string_helpers()

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

        # Infer which function parameters receive string arguments
        self._infer_string_params(top_level)

        # Emit forward declarations for functions
        for name, func in self.functions.items():
            safe_name = self._safe_ident(name)
            params = self._build_param_list(name, func.params)
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

        # Free arena memory before exit
        if self.uses_string_helpers or getattr(self, 'uses_fstring', False):
            self.emit("srv_arena_free_all();")

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
        self.emit("    l.data = (double*)srv_checked_malloc(sizeof(double) * l.capacity);")
        self.emit("    return l;")
        self.emit("}")
        self.emit("")
        self.emit("void srv_list_append(SrvList *l, double val) {")
        self.emit("    if (l->size >= l->capacity) {")
        self.emit("        l->capacity *= 2;")
        self.emit("        l->data = (double*)srv_checked_realloc(l->data, sizeof(double) * l->capacity);")
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

    def emit_map_runtime(self):
        """Emit a simple string-keyed hash map implementation in C.

        Uses open addressing with linear probing and string keys.
        Values are doubles (matching sauravcode's numeric type).
        """
        self.emit("/* ---- Hash map runtime ---- */")
        self.emit("typedef struct {")
        self.emit("    char *key;")
        self.emit("    double value;")
        self.emit("    int occupied;")
        self.emit("} SrvMapEntry;")
        self.emit("")
        self.emit("typedef struct {")
        self.emit("    SrvMapEntry *entries;")
        self.emit("    int size;")
        self.emit("    int capacity;")
        self.emit("} SrvMap;")
        self.emit("")
        # Hash function (djb2)
        self.emit("static unsigned int srv_map_hash(const char *key, int cap) {")
        self.emit("    unsigned int h = 5381;")
        self.emit("    while (*key) h = ((h << 5) + h) + (unsigned char)*key++;")
        self.emit("    return h % cap;")
        self.emit("}")
        self.emit("")
        # Create
        self.emit("SrvMap srv_map_new(void) {")
        self.emit("    SrvMap m;")
        self.emit("    m.capacity = 16;")
        self.emit("    m.size = 0;")
        self.emit("    m.entries = (SrvMapEntry*)calloc(m.capacity, sizeof(SrvMapEntry));")
        self.emit('    if (!m.entries) { fprintf(stderr, "Out of memory\\n"); exit(1); }')
        self.emit("    return m;")
        self.emit("}")
        self.emit("")
        # Resize
        self.emit("static void srv_map_resize(SrvMap *m) {")
        self.emit("    int old_cap = m->capacity;")
        self.emit("    SrvMapEntry *old = m->entries;")
        self.emit("    m->capacity *= 2;")
        self.emit("    m->entries = (SrvMapEntry*)calloc(m->capacity, sizeof(SrvMapEntry));")
        self.emit('    if (!m->entries) { fprintf(stderr, "Out of memory\\n"); exit(1); }')
        self.emit("    m->size = 0;")
        self.emit("    for (int i = 0; i < old_cap; i++) {")
        self.emit("        if (old[i].occupied) {")
        self.emit("            unsigned int idx = srv_map_hash(old[i].key, m->capacity);")
        self.emit("            while (m->entries[idx].occupied) idx = (idx + 1) % m->capacity;")
        self.emit("            m->entries[idx].key = old[i].key;")
        self.emit("            m->entries[idx].value = old[i].value;")
        self.emit("            m->entries[idx].occupied = 1;")
        self.emit("            m->size++;")
        self.emit("        }")
        self.emit("    }")
        self.emit("    free(old);")
        self.emit("}")
        self.emit("")
        # Set (insert or update)
        self.emit("void srv_map_set(SrvMap *m, const char *key, double value) {")
        self.emit("    if (m->size * 2 >= m->capacity) srv_map_resize(m);")
        self.emit("    unsigned int idx = srv_map_hash(key, m->capacity);")
        self.emit("    while (m->entries[idx].occupied) {")
        self.emit("        if (strcmp(m->entries[idx].key, key) == 0) {")
        self.emit("            m->entries[idx].value = value;")
        self.emit("            return;")
        self.emit("        }")
        self.emit("        idx = (idx + 1) % m->capacity;")
        self.emit("    }")
        self.emit("    m->entries[idx].key = strdup(key);")
        self.emit("    m->entries[idx].value = value;")
        self.emit("    m->entries[idx].occupied = 1;")
        self.emit("    m->size++;")
        self.emit("}")
        self.emit("")
        # Get
        self.emit("double srv_map_get(SrvMap *m, const char *key) {")
        self.emit("    unsigned int idx = srv_map_hash(key, m->capacity);")
        self.emit("    while (m->entries[idx].occupied) {")
        self.emit("        if (strcmp(m->entries[idx].key, key) == 0)")
        self.emit("            return m->entries[idx].value;")
        self.emit("        idx = (idx + 1) % m->capacity;")
        self.emit("    }")
        self.emit('    fprintf(stderr, "Key not found: %s\\n", key);')
        self.emit("    exit(1);")
        self.emit("}")
        self.emit("")
        # Has key
        self.emit("int srv_map_has_key(SrvMap *m, const char *key) {")
        self.emit("    unsigned int idx = srv_map_hash(key, m->capacity);")
        self.emit("    while (m->entries[idx].occupied) {")
        self.emit("        if (strcmp(m->entries[idx].key, key) == 0) return 1;")
        self.emit("        idx = (idx + 1) % m->capacity;")
        self.emit("    }")
        self.emit("    return 0;")
        self.emit("}")
        self.emit("")
        # Keys (returns SrvList of string hashes — not ideal, but we return indices)
        # Actually we need to return a list of key strings. Since our list only holds
        # doubles, we'll return a special "keys list" as a string array printed directly.
        # For now, provide srv_map_keys that fills an output buffer.
        self.emit("int srv_map_size(SrvMap *m) {")
        self.emit("    return m->size;")
        self.emit("}")
        self.emit("")
        # Print map
        self.emit("void srv_map_print(SrvMap *m) {")
        self.emit('    printf("{");')
        self.emit("    int first = 1;")
        self.emit("    for (int i = 0; i < m->capacity; i++) {")
        self.emit("        if (m->entries[i].occupied) {")
        self.emit('            if (!first) printf(", ");')
        self.emit("            double v = m->entries[i].value;")
        self.emit("            if (v == (long long)v)")
        self.emit('                printf("\\"%s\\": %lld", m->entries[i].key, (long long)v);')
        self.emit("            else")
        self.emit('                printf("\\"%s\\": %.10g", m->entries[i].key, v);')
        self.emit("            first = 0;")
        self.emit("        }")
        self.emit("    }")
        self.emit('    printf("}\\n");')
        self.emit("}")
        self.emit("")
        # Iterate keys (callback-based)
        self.emit("typedef void (*SrvMapKeyCallback)(const char *key, double value, void *ctx);")
        self.emit("void srv_map_foreach(SrvMap *m, SrvMapKeyCallback cb, void *ctx) {")
        self.emit("    for (int i = 0; i < m->capacity; i++) {")
        self.emit("        if (m->entries[i].occupied)")
        self.emit("            cb(m->entries[i].key, m->entries[i].value, ctx);")
        self.emit("    }")
        self.emit("}")
        self.emit("")
        # Free
        self.emit("void srv_map_free(SrvMap *m) {")
        self.emit("    for (int i = 0; i < m->capacity; i++) {")
        self.emit("        if (m->entries[i].occupied) free(m->entries[i].key);")
        self.emit("    }")
        self.emit("    free(m->entries);")
        self.emit("    m->entries = NULL;")
        self.emit("    m->size = 0;")
        self.emit("    m->capacity = 0;")
        self.emit("}")
        self.emit("")

    def emit_string_helpers(self):
        """Emit C helper functions for sauravcode string/conversion builtins."""
        self.emit("/* ---- String / conversion helpers ---- */")
        self.emit("#include <ctype.h>")
        self.emit("")
        # srv_upper: returns an arena-allocated uppercase copy
        self.emit("static char* srv_upper(const char* s) {")
        self.emit("    size_t len = strlen(s);")
        self.emit("    char* out = (char*)srv_arena_alloc(len + 1);")
        self.emit("    for (size_t i = 0; i <= len; i++) out[i] = toupper((unsigned char)s[i]);")
        self.emit("    return out;")
        self.emit("}")
        self.emit("")
        # srv_lower: returns an arena-allocated lowercase copy
        self.emit("static char* srv_lower(const char* s) {")
        self.emit("    size_t len = strlen(s);")
        self.emit("    char* out = (char*)srv_arena_alloc(len + 1);")
        self.emit("    for (size_t i = 0; i <= len; i++) out[i] = tolower((unsigned char)s[i]);")
        self.emit("    return out;")
        self.emit("}")
        self.emit("")
        # srv_to_string: converts a double to a string
        self.emit("static char* srv_to_string(double val) {")
        self.emit("    char* buf = (char*)srv_arena_alloc(64);")
        self.emit("    if (val == (long long)val)")
        self.emit('        snprintf(buf, 64, "%lld", (long long)val);')
        self.emit("    else")
        self.emit('        snprintf(buf, 64, "%.10g", val);')
        self.emit("    return buf;")
        self.emit("}")
        self.emit("")
        # srv_type_of: returns the type name (simplified — only works for doubles in compiled mode)
        self.emit('static const char* srv_type_of(double val) {')
        self.emit('    if (val == (long long)val) return "number";')
        self.emit('    return "number";  /* compiled mode only has doubles */')
        self.emit("}")
        self.emit("")
        # srv_trim: returns an arena-allocated trimmed copy (strips leading/trailing whitespace)
        self.emit("static char* srv_trim(const char* s) {")
        self.emit("    while (*s && isspace((unsigned char)*s)) s++;")
        self.emit("    if (*s == '\\0') { char* out = (char*)srv_arena_alloc(1); out[0] = '\\0'; return out; }")
        self.emit("    const char* end = s + strlen(s) - 1;")
        self.emit("    while (end > s && isspace((unsigned char)*end)) end--;")
        self.emit("    size_t len = (size_t)(end - s + 1);")
        self.emit("    char* out = (char*)srv_arena_alloc(len + 1);")
        self.emit("    memcpy(out, s, len);")
        self.emit("    out[len] = '\\0';")
        self.emit("    return out;")
        self.emit("}")
        self.emit("")
        # srv_replace: returns an arena-allocated string with all occurrences of old replaced by new
        self.emit("static char* srv_replace(const char* s, const char* old, const char* neww) {")
        self.emit("    size_t slen = strlen(s), olen = strlen(old), nlen = strlen(neww);")
        self.emit("    if (olen == 0) { char* out = (char*)srv_arena_alloc(slen + 1); memcpy(out, s, slen + 1); return out; }")
        self.emit("    size_t count = 0;")
        self.emit("    const char* p = s;")
        self.emit("    while ((p = strstr(p, old)) != NULL) { count++; p += olen; }")
        self.emit("    size_t rlen = slen + count * (nlen - olen);")
        self.emit("    char* out = (char*)srv_arena_alloc(rlen + 1);")
        self.emit("    char* w = out;")
        self.emit("    p = s;")
        self.emit("    while (*p) {")
        self.emit("        if (strncmp(p, old, olen) == 0) { memcpy(w, neww, nlen); w += nlen; p += olen; }")
        self.emit("        else { *w++ = *p++; }")
        self.emit("    }")
        self.emit("    *w = '\\0';")
        self.emit("    return out;")
        self.emit("}")
        self.emit("")
        # srv_contains: returns 1.0 if substring found, 0.0 otherwise
        self.emit("static double srv_contains(const char* s, const char* sub) {")
        self.emit("    return strstr(s, sub) != NULL ? 1.0 : 0.0;")
        self.emit("}")
        self.emit("")
        # srv_index_of: returns index of first occurrence, or -1
        self.emit("static double srv_index_of(const char* s, const char* sub) {")
        self.emit("    const char* p = strstr(s, sub);")
        self.emit("    if (p == NULL) return -1.0;")
        self.emit("    return (double)(p - s);")
        self.emit("}")
        self.emit("")
        # srv_char_at: returns single-char string at index
        self.emit("static char* srv_char_at(const char* s, double idx) {")
        self.emit("    int i = (int)idx;")
        self.emit("    size_t len = strlen(s);")
        self.emit('    if (i < 0 || (size_t)i >= len) { char* out = (char*)srv_arena_alloc(1); out[0] = \'\\0\'; return out; }')
        self.emit("    char* out = (char*)srv_arena_alloc(2);")
        self.emit("    out[0] = s[i]; out[1] = '\\0';")
        self.emit("    return out;")
        self.emit("}")
        self.emit("")
        # srv_substring: returns substring from start to end (exclusive)
        self.emit("static char* srv_substring(const char* s, double start, double end) {")
        self.emit("    int st = (int)start, en = (int)end;")
        self.emit("    size_t len = strlen(s);")
        self.emit("    if (st < 0) st = 0;")
        self.emit("    if ((size_t)en > len) en = (int)len;")
        self.emit("    if (st >= en) { char* out = (char*)srv_arena_alloc(1); out[0] = '\\0'; return out; }")
        self.emit("    size_t rlen = (size_t)(en - st);")
        self.emit("    char* out = (char*)srv_arena_alloc(rlen + 1);")
        self.emit("    memcpy(out, s + st, rlen);")
        self.emit("    out[rlen] = '\\0';")
        self.emit("    return out;")
        self.emit("}")
        self.emit("")
        # srv_reverse: returns an arena-allocated reversed copy
        self.emit("static char* srv_reverse(const char* s) {")
        self.emit("    size_t len = strlen(s);")
        self.emit("    char* out = (char*)srv_arena_alloc(len + 1);")
        self.emit("    for (size_t i = 0; i < len; i++) out[i] = s[len - 1 - i];")
        self.emit("    out[len] = '\\0';")
        self.emit("    return out;")
        self.emit("}")
        self.emit("")
        # srv_split: splits string by delimiter, returns SrvList of string pointers stored as doubles
        self.emit("static SrvList srv_split(const char* s, const char* delim) {")
        self.emit("    SrvList list = srv_list_new();")
        self.emit("    size_t dlen = strlen(delim);")
        self.emit("    if (dlen == 0) {")
        self.emit("        /* Split into individual characters */")
        self.emit("        size_t slen = strlen(s);")
        self.emit("        for (size_t i = 0; i < slen; i++) {")
        self.emit("            char* ch = (char*)srv_arena_alloc(2); ch[0] = s[i]; ch[1] = '\\0';")
        self.emit("            union { char* p; double d; } u; u.p = ch;")
        self.emit("            srv_list_append(&list, u.d);")
        self.emit("        }")
        self.emit("        return list;")
        self.emit("    }")
        self.emit("    const char* p = s;")
        self.emit("    while (*p) {")
        self.emit("        const char* found = strstr(p, delim);")
        self.emit("        size_t partlen = found ? (size_t)(found - p) : strlen(p);")
        self.emit("        char* part = (char*)srv_arena_alloc(partlen + 1);")
        self.emit("        memcpy(part, p, partlen); part[partlen] = '\\0';")
        self.emit("        union { char* ptr; double d; } u; u.ptr = part;")
        self.emit("        srv_list_append(&list, u.d);")
        self.emit("        if (!found) break;")
        self.emit("        p = found + dlen;")
        self.emit("        if (*p == '\\0') {")
        self.emit("            char* empty = (char*)srv_arena_alloc(1); empty[0] = '\\0';")
        self.emit("            union { char* ptr; double d; } u2; u2.ptr = empty;")
        self.emit("            srv_list_append(&list, u2.d);")
        self.emit("            break;")
        self.emit("        }")
        self.emit("    }")
        self.emit("    return list;")
        self.emit("}")
        self.emit("")
        # srv_join: joins a SrvList of strings with a delimiter
        self.emit("static char* srv_join(const char* delim, SrvList* list) {")
        self.emit("    if (list->size == 0) { char* out = (char*)srv_arena_alloc(1); out[0] = '\\0'; return out; }")
        self.emit("    size_t dlen = strlen(delim);")
        self.emit("    size_t total = 0;")
        self.emit("    for (int i = 0; i < list->size; i++) {")
        self.emit("        union { double d; char* p; } u; u.d = list->data[i];")
        self.emit("        total += strlen(u.p);")
        self.emit("        if (i > 0) total += dlen;")
        self.emit("    }")
        self.emit("    char* out = (char*)srv_arena_alloc(total + 1);")
        self.emit("    char* w = out;")
        self.emit("    for (int i = 0; i < list->size; i++) {")
        self.emit("        if (i > 0) { memcpy(w, delim, dlen); w += dlen; }")
        self.emit("        union { double d; char* p; } u; u.d = list->data[i];")
        self.emit("        size_t slen = strlen(u.p);")
        self.emit("        memcpy(w, u.p, slen); w += slen;")
        self.emit("    }")
        self.emit("    *w = '\\0';")
        self.emit("    return out;")
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
                    # Handle DotAssignmentNode: self.field = val
                    if isinstance(s, DotAssignmentNode) and isinstance(s.obj, IdentifierNode) and s.obj.name == 'self':
                        fields.add(s.field)
                    # Legacy: AssignmentNode with self. prefix (shouldn't happen anymore, but keep for safety)
                    elif isinstance(s, AssignmentNode) and isinstance(s.name, str) and s.name.startswith('self.'):
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

    def _infer_string_params(self, top_level_stmts):
        """Pre-scan all call sites to infer which function parameters receive strings.

        Walks all statements (top-level + function bodies) looking for
        FunctionCallNode where arguments are string-typed. Records the
        parameter index in self.string_params[func_name].
        """
        def is_string_expr(expr):
            """Check if an expression is known to produce a string."""
            if isinstance(expr, StringNode):
                return True
            if isinstance(expr, FStringNode):
                return True
            if isinstance(expr, IdentifierNode) and expr.name in self.string_vars:
                return True
            if isinstance(expr, FunctionCallNode) and expr.name in self.STRING_RETURNING_BUILTINS:
                return True
            return False

        def scan_call(node):
            """If node is a function call to a user-defined function, check args."""
            if isinstance(node, FunctionCallNode) and node.name in self.functions:
                func = self.functions[node.name]
                for i, arg in enumerate(node.arguments):
                    if i < len(func.params) and is_string_expr(arg):
                        if node.name not in self.string_params:
                            self.string_params[node.name] = set()
                        self.string_params[node.name].add(i)

        def walk_expr(expr):
            """Walk an expression tree looking for function calls."""
            if expr is None:
                return
            scan_call(expr)
            if isinstance(expr, BinaryOpNode):
                walk_expr(expr.left)
                walk_expr(expr.right)
            elif isinstance(expr, UnaryOpNode):
                walk_expr(expr.operand)
            elif isinstance(expr, FunctionCallNode):
                for a in expr.arguments:
                    walk_expr(a)
            elif isinstance(expr, FStringNode):
                for p in expr.parts:
                    walk_expr(p)
            elif isinstance(expr, ListNode):
                for e in expr.elements:
                    walk_expr(e)
            elif isinstance(expr, MapNode):
                for k, v in expr.pairs:
                    walk_expr(k)
                    walk_expr(v)
            elif isinstance(expr, IndexNode):
                walk_expr(expr.obj)
                walk_expr(expr.index)
            elif isinstance(expr, LenNode):
                walk_expr(expr.expression)
            elif isinstance(expr, TernaryNode):
                walk_expr(expr.condition)
                walk_expr(expr.true_expr)
                walk_expr(expr.false_expr)

        def walk_stmts(stmts):
            """Walk a list of statements looking for function calls."""
            for stmt in stmts:
                if isinstance(stmt, AssignmentNode):
                    walk_expr(stmt.expression)
                elif isinstance(stmt, FunctionCallNode):
                    scan_call(stmt)
                    for a in stmt.arguments:
                        walk_expr(a)
                elif isinstance(stmt, PrintNode):
                    walk_expr(stmt.expression)
                elif isinstance(stmt, ReturnNode) and stmt.expression:
                    walk_expr(stmt.expression)
                elif isinstance(stmt, IfNode):
                    walk_expr(stmt.condition)
                    walk_stmts(stmt.body)
                    for elif_cond, elif_body in (stmt.elif_chains or []):
                        walk_expr(elif_cond)
                        walk_stmts(elif_body)
                    if stmt.else_body:
                        walk_stmts(stmt.else_body)
                elif isinstance(stmt, WhileNode):
                    walk_expr(stmt.condition)
                    walk_stmts(stmt.body)
                elif isinstance(stmt, ForNode):
                    walk_expr(stmt.start)
                    walk_expr(stmt.end)
                    walk_stmts(stmt.body)
                elif isinstance(stmt, ForEachNode):
                    walk_expr(stmt.iterable)
                    walk_stmts(stmt.body)
                elif isinstance(stmt, TryCatchNode):
                    walk_stmts(stmt.try_body)
                    walk_stmts(stmt.catch_body)
                elif isinstance(stmt, IndexedAssignmentNode):
                    walk_expr(stmt.index)
                    walk_expr(stmt.value)
                elif isinstance(stmt, AppendNode):
                    walk_expr(stmt.value)
                elif isinstance(stmt, AssertNode):
                    walk_expr(stmt.condition)

        # Scan top-level code
        walk_stmts(top_level_stmts)
        # Scan inside function bodies
        for func in self.functions.values():
            walk_stmts(func.body)

    def compile_function(self, func):
        """Emit a C function definition."""
        safe_name = self._safe_ident(func.name)
        params = self._build_param_list(func.name, func.params)
        self.emit(f"double {safe_name}({params}) {{")
        self.indent_level += 1
        self.declared_vars[func.name] = set(func.params)

        # Mark string parameters in string_vars for correct f-string formatting
        saved_string_vars = set(self.string_vars)
        string_indices = self.string_params.get(func.name, set())
        for i, p in enumerate(func.params):
            if i in string_indices:
                self.string_vars.add(p)

        for stmt in func.body:
            self.compile_statement(stmt, scope=func.name)

        # Add implicit return 0 if no return found
        has_return = any(isinstance(s, ReturnNode) for s in func.body)
        if not has_return:
            self.emit("return 0;")

        self.indent_level -= 1
        self.emit("}")

        # Restore string_vars to avoid leaking function-scope info
        self.string_vars = saved_string_vars

    def compile_statement(self, stmt, scope='main', is_top_level=False):
        """Compile a single statement to C."""
        if isinstance(stmt, IndexedAssignmentNode):
            name = self._safe_ident(stmt.name)
            idx_c = self.compile_expression(stmt.index)
            val_c = self.compile_expression(stmt.value)
            if stmt.name in self.map_vars:
                # Map key assignment: m["key"] = value
                self.emit(f"srv_map_set(&{name}, {idx_c}, {val_c});")
            else:
                self.emit(f"srv_list_set(&{name}, (int)({idx_c}), {val_c});")

        elif isinstance(stmt, DotAssignmentNode):
            obj_c = self.compile_expression(stmt.obj)
            field = self._safe_ident(stmt.field)
            val_c = self.compile_expression(stmt.value)
            # Use -> for pointer access (self is a pointer in class methods)
            if isinstance(stmt.obj, IdentifierNode) and stmt.obj.name == 'self':
                self.emit(f"{obj_c}->{field} = {val_c};")
            else:
                self.emit(f"{obj_c}.{field} = {val_c};")

        elif isinstance(stmt, AssignmentNode):
            expr_c = self.compile_expression(stmt.expression)
            if stmt.name not in self.declared_vars.get(scope, set()):
                self._emit_first_declaration(stmt.name, stmt.expression, expr_c, scope)
            else:
                self._emit_reassignment(stmt.name, stmt.expression, expr_c)

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

        elif isinstance(stmt, ForEachNode):
            var = self._safe_ident(stmt.var)
            self.declared_vars.setdefault(scope, set()).add(stmt.var)
            iterable_c = self.compile_expression(stmt.iterable)

            # Determine collection type from context
            is_map_iter = (isinstance(stmt.iterable, IdentifierNode) and
                          stmt.iterable.name in self.map_vars)
            is_list_iter = (isinstance(stmt.iterable, IdentifierNode) and
                           stmt.iterable.name in self.list_vars)

            if is_map_iter:
                # Iterate over map keys
                idx_var = f"__i_{var}"
                self.emit(f"for (int {idx_var} = 0; {idx_var} < {iterable_c}.capacity; {idx_var}++) {{")
                self.indent_level += 1
                self.emit(f"if (!{iterable_c}.entries[{idx_var}].occupied) continue;")
                # Bind loop variable as string key — but our vars are doubles.
                # For map iteration, the var gets the key as a string (const char*).
                # We need to track it as a string var.
                self.string_vars.add(stmt.var)
                self.emit(f"const char *{var} = {iterable_c}.entries[{idx_var}].key;")
                for s in stmt.body:
                    self.compile_statement(s, scope=scope)
                self.indent_level -= 1
                self.emit("}")
            else:
                # Default: iterate over list
                idx_var = f"__i_{var}"
                self.emit(f"for (int {idx_var} = 0; {idx_var} < srv_list_len(&{iterable_c}); {idx_var}++) {{")
                self.indent_level += 1
                self.emit(f"double {var} = srv_list_get(&{iterable_c}, {idx_var});")
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
                self.string_vars.add(stmt.catch_var)
            for s in stmt.catch_body:
                self.compile_statement(s, scope=scope)
            self.indent_level -= 1
            self.emit("}")

        elif isinstance(stmt, ThrowNode):
            msg_c = self.compile_expression(stmt.expression)
            if self._is_string_expr(stmt.expression):
                self.emit(f'snprintf(__error_msg, sizeof(__error_msg), "%s", {msg_c});')
            else:
                self.emit(f'snprintf(__error_msg, sizeof(__error_msg), "%s", srv_to_string({msg_c}));')
            self.emit("__has_error = 1;")
            self.emit("longjmp(__catch_buf, 1);")

        elif isinstance(stmt, AssertNode):
            cond_c = self.compile_expression(stmt.condition)
            if stmt.message:
                msg_c = self.compile_expression(stmt.message)
                if self._is_string_expr(stmt.message):
                    self.emit(f'if (!({cond_c})) {{ fprintf(stderr, "Assertion failed: %s\\n", {msg_c}); exit(1); }}')
                else:
                    self.emit(f'if (!({cond_c})) {{ fprintf(stderr, "Assertion failed: %s\\n", srv_to_string({msg_c})); exit(1); }}')
            else:
                self.emit(f'if (!({cond_c})) {{ fprintf(stderr, "Assertion failed\\n"); exit(1); }}')

        elif isinstance(stmt, AppendNode):
            safe_list = self._safe_ident(stmt.list_name)
            val_c = self.compile_expression(stmt.value)
            self.emit(f"srv_list_append(&{safe_list}, {val_c});")

        elif isinstance(stmt, PopNode):
            safe_list = self._safe_ident(stmt.list_name)
            self.emit(f"srv_list_pop(&{safe_list});")

        elif isinstance(stmt, BreakNode):
            self.emit('break;')

        elif isinstance(stmt, ContinueNode):
            self.emit('continue;')

        elif isinstance(stmt, EnumNode):
            pass  # Already handled in first pass (stored in self.enums)

        elif isinstance(stmt, ClassNode):
            pass  # Already handled in first pass

    def compile_print(self, stmt):
        """Smart print that detects type."""
        expr = stmt.expression
        expr_c = self.compile_expression(expr)

        # Set of builtins that return strings (char*)
        STRING_BUILTINS = self.STRING_RETURNING_BUILTINS

        if isinstance(expr, StringNode):
            self.emit(f'printf("%s\\n", {expr_c});')
        elif isinstance(expr, BoolNode):
            self.emit(f'printf("%s\\n", {expr_c} ? "true" : "false");')
        elif isinstance(expr, IdentifierNode) and expr.name in self.string_vars:
            self.emit(f'printf("%s\\n", {expr_c});')
        elif isinstance(expr, IdentifierNode) and expr.name in self.list_vars:
            self.emit(f'printf("[list: %d items]\\n", srv_list_len(&{expr_c}));')
        elif isinstance(expr, IdentifierNode) and expr.name in self.map_vars:
            self.emit(f'srv_map_print(&{expr_c});')
        elif isinstance(expr, FunctionCallNode) and expr.name in STRING_BUILTINS:
            self.emit(f'printf("%s\\n", {expr_c});')
        elif isinstance(expr, FunctionCallNode) and expr.name == 'split':
            self.emit(f'{{ SrvList __tmp = {expr_c}; printf("[list: %d items]\\n", srv_list_len(&__tmp)); }}')
        elif isinstance(expr, FunctionCallNode) and expr.name == 'contains':
            self.emit(f'printf("%s\\n", {expr_c} ? "true" : "false");')
        elif isinstance(expr, FStringNode):
            self.emit(f'printf("%s\\n", {expr_c});')
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
            # String operands need strcmp(); C's == compares pointers.
            if self._is_string_expr(expr.left) or self._is_string_expr(expr.right):
                self.uses_string_helpers = True
                cmp_expr = f"strcmp({left_c}, {right_c})"
                if expr.operator == '==':
                    return f"({cmp_expr} == 0)"
                elif expr.operator == '!=':
                    return f"({cmp_expr} != 0)"
                elif expr.operator == '<':
                    return f"({cmp_expr} < 0)"
                elif expr.operator == '>':
                    return f"({cmp_expr} > 0)"
                elif expr.operator == '<=':
                    return f"({cmp_expr} <= 0)"
                elif expr.operator == '>=':
                    return f"({cmp_expr} >= 0)"
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

        elif isinstance(expr, MapNode):
            # Map literal in expression context — placeholder
            return "srv_map_new()"  # Actual init in assignment

        elif isinstance(expr, IndexNode):
            obj_c = self.compile_expression(expr.obj)
            idx_c = self.compile_expression(expr.index)
            # Determine if this is map access or list access
            if isinstance(expr.obj, IdentifierNode) and expr.obj.name in self.map_vars:
                return f"srv_map_get(&{obj_c}, {idx_c})"
            return f"srv_list_get(&{obj_c}, (int)({idx_c}))"

        elif isinstance(expr, LenNode):
            inner = self.compile_expression(expr.expression)
            # Check if it's a map
            if isinstance(expr.expression, IdentifierNode) and expr.expression.name in self.map_vars:
                return f"srv_map_size(&{inner})"
            return f"srv_list_len(&{inner})"

        elif isinstance(expr, DotAccessNode):
            # Check for enum access: EnumName.VARIANT -> integer constant
            if isinstance(expr.obj, IdentifierNode) and expr.obj.name in self.enums:
                enum_map = self.enums[expr.obj.name]
                if expr.field not in enum_map:
                    avail = ', '.join(enum_map.keys())
                    raise RuntimeError(
                        f"Enum '{expr.obj.name}' has no variant '{expr.field}'. "
                        f"Available: {avail}"
                    )
                return str(enum_map[expr.field])
            obj_c = self.compile_expression(expr.obj)
            field = self._safe_ident(expr.field)
            # Use -> for pointer access (self is a pointer in class methods)
            if isinstance(expr.obj, IdentifierNode) and expr.obj.name == 'self':
                return f"{obj_c}->{field}"
            return f"{obj_c}.{field}"

        elif isinstance(expr, NewNode):
            # Generate struct initialization — call ClassName_init if it exists
            class_name = expr.class_name
            if class_name in self.classes:
                # Create a zero-initialized struct and call init
                args_c = ", ".join(self.compile_expression(a) for a in expr.arguments)
                if args_c:
                    return f"({{ {class_name} __tmp = {{0}}; {class_name}_init(&__tmp, {args_c}); __tmp; }})"
                else:
                    return f"({{ {class_name} __tmp = {{0}}; {class_name}_init(&__tmp); __tmp; }})"
            else:
                # Unknown class — just zero-init
                return f"(({class_name}){{0}})"

        elif isinstance(expr, PopNode):
            safe_list = self._safe_ident(expr.list_name)
            return f"srv_list_pop(&{safe_list})"

        elif isinstance(expr, FStringNode):
            return self.compile_fstring(expr)

        elif isinstance(expr, TernaryNode):
            cond_c = self.compile_expression(expr.condition)
            true_c = self.compile_expression(expr.true_expr)
            false_c = self.compile_expression(expr.false_expr)
            return f"(({cond_c}) ? ({true_c}) : ({false_c}))"

        elif isinstance(expr, MethodCallNode):
            obj_c = self.compile_expression(expr.obj)
            args_c = ", ".join(self.compile_expression(a) for a in expr.arguments)
            return f"{obj_c}_{expr.method}(&{obj_c}, {args_c})"

        else:
            raise ValueError(f"Unknown expression type: {type(expr).__name__}")

    # Builtin functions: sauravcode name -> C expression template.
    # {0}, {1}, ... are replaced with compiled argument expressions.
    BUILTIN_MAP = {
        # Math builtins (math.h)
        'abs':        ('fabs({0})', 1),
        'sqrt':       ('sqrt({0})', 1),
        'floor':      ('floor({0})', 1),
        'ceil':       ('ceil({0})', 1),
        'round':      ('round({0})', 1),
        'power':      ('pow({0}, {1})', 2),
        # Conversion builtins
        'to_number':  ('atof({0})', 1),
        # String builtins (need runtime helpers emitted once)
        'upper':      ('srv_upper({0})', 1),
        'lower':      ('srv_lower({0})', 1),
        'to_string':  ('srv_to_string({0})', 1),
        'type_of':    ('srv_type_of({0})', 1),
        'trim':       ('srv_trim({0})', 1),
        'replace':    ('srv_replace({0}, {1}, {2})', 3),
        'contains':   ('srv_contains({0}, {1})', 2),
        'index_of':   ('srv_index_of({0}, {1})', 2),
        'char_at':    ('srv_char_at({0}, {1})', 2),
        'substring':  ('srv_substring({0}, {1}, {2})', 3),
        'reverse':    ('srv_reverse({0})', 1),
        'split':      ('srv_split({0}, {1})', 2),
        'join':       ('srv_join({0}, &{1})', 2),
        # Map builtins
        'has_key':    ('srv_map_has_key(&{0}, {1})', 2),
    }

    # Builtins that return char* (used for printf formatting and type tracking)
    STRING_RETURNING_BUILTINS = {
        'upper', 'lower', 'to_string', 'type_of', 'trim', 'replace',
        'char_at', 'substring', 'reverse', 'join',
    }

    def compile_call(self, call):
        """Compile a function call to C, with builtin support."""
        if call.name in self.BUILTIN_MAP:
            template, arity = self.BUILTIN_MAP[call.name]
            if len(call.arguments) < arity:
                raise ValueError(f"Builtin '{call.name}' expects {arity} argument(s), got {len(call.arguments)}")
            args_c = [self.compile_expression(a) for a in call.arguments]
            # Track that we need string helper runtime
            if call.name in self.STRING_RETURNING_BUILTINS or call.name in ('contains', 'index_of', 'split'):
                self.uses_string_helpers = True
            return template.format(*args_c)

        safe_name = self._safe_ident(call.name)
        args_c = ", ".join(self.compile_expression(a) for a in call.arguments)
        return f"{safe_name}({args_c})"

    def compile_fstring(self, node):
        """Compile an f-string to C using snprintf into an arena-allocated buffer.

        Generates a GCC statement-expression ({ ... }) that:
        1. Calculates the required buffer size via snprintf(NULL, 0, ...)
        2. Allocates a buffer from the arena (NULL-safe)
        3. Writes the formatted string into it
        """
        self.uses_fstring = True

        # Build format string and args list
        fmt_parts = []
        args = []
        for part in node.parts:
            if isinstance(part, StringNode):
                # Literal text — escape % for printf
                escaped = part.value.replace('\\', '\\\\').replace('"', '\\"')
                escaped = escaped.replace('%', '%%').replace('\n', '\\n')
                fmt_parts.append(escaped)
            elif isinstance(part, IdentifierNode) and part.name in self.string_vars:
                fmt_parts.append('%s')
                args.append(self.compile_expression(part))
            elif isinstance(part, FunctionCallNode) and part.name in self.STRING_RETURNING_BUILTINS:
                fmt_parts.append('%s')
                args.append(self.compile_expression(part))
            elif isinstance(part, NumberNode):
                # Number literal — format as int if possible
                if part.value == int(part.value):
                    fmt_parts.append('%d')
                    args.append(str(int(part.value)))
                else:
                    fmt_parts.append('%.10g')
                    args.append(str(part.value))
            elif isinstance(part, StringNode):
                # Already handled above
                pass
            else:
                # Expression — assume numeric, use %.10g
                fmt_parts.append('%.10g')
                args.append(f"(double)({self.compile_expression(part)})")

        fmt_str = ''.join(fmt_parts)
        if args:
            args_str = ', ' + ', '.join(args)
        else:
            args_str = ''

        # Use a statement-expression to allocate and format
        return (
            f'({{ int __n = snprintf(NULL, 0, "{fmt_str}"{args_str}); '
            f'char* __s = (char*)srv_arena_alloc(__n + 1); '
            f'snprintf(__s, __n + 1, "{fmt_str}"{args_str}); __s; }})'
        )


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
