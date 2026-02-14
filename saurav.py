import re
import sys
import os

# Debug flag — enabled with --debug command-line argument
DEBUG = False

def debug(msg):
    """Print debug message only when DEBUG mode is enabled."""
    if DEBUG:
        print(msg)

# Define token specifications with indentation tokens
# NOTE: Order matters! Longer patterns (e.g. '==') must come before shorter
# ones (e.g. '=') so the regex alternation matches the longest token first.
token_specification = [
    ('COMMENT',  r'#.*'),  # Comments
    ('NUMBER',   r'\d+(\.\d*)?'),  # Integer or decimal number
    ('STRING',   r'\".*?\"'),  # String literal
    ('EQ',       r'=='),  # Equality operator (must precede ASSIGN)
    ('NEQ',      r'!='),  # Not-equal operator
    ('LTE',      r'<='),  # Less-than-or-equal
    ('GTE',      r'>='),  # Greater-than-or-equal
    ('LT',       r'<'),   # Less-than
    ('GT',       r'>'),   # Greater-than
    ('ASSIGN',   r'='),  # Assignment operator
    ('OP',       r'[+\-*/%]'),  # Arithmetic operators (includes modulo)
    ('LPAREN',   r'\('),  # Left parenthesis
    ('RPAREN',   r'\)'),  # Right parenthesis
    ('LBRACKET', r'\['),  # Left bracket
    ('RBRACKET', r'\]'),  # Right bracket
    ('COMMA',    r','),   # Comma separator
    ('KEYWORD',  r'\b(?:function|return|class|int|float|bool|string|if|else if|else|for|in|while|try|catch|print|true|false|and|or|not|list|set|map|stack|queue|append|len|pop)\b'),  # All keywords
    ('IDENT',    r'[a-zA-Z_]\w*'),  # Identifiers
    ('NEWLINE',  r'\n'),  # Newlines
    ('SKIP',     r'[ \t]+'),  # Whitespace
    ('MISMATCH', r'.'),  # Any other character
]

tok_regex = '|'.join(f'(?P<{pair[0]}>{pair[1]})' for pair in token_specification)
get_token = re.compile(tok_regex).match

def tokenize(code):
    debug("Tokenizing code...")
    tokens = []
    line_num = 1
    line_start = 0
    indent_levels = [0]  # Track indentation levels
    
    for match in re.finditer(tok_regex, code):
        typ = match.lastgroup
        value = match.group(typ)
        debug(f"Token: {typ}, Value: {repr(value)}")

        if typ == 'NEWLINE':
            line_num += 1
            line_start = match.end()
            tokens.append(('NEWLINE', value, line_num, match.start()))
            
            # Handle indentation on the next line
            indent_match = re.match(r'[ \t]*', code[line_start:])
            if indent_match:
                indent_str = indent_match.group(0)
                indent = len(indent_str.replace('\t', '    '))  # Normalize tabs to spaces
                debug(f"Detected indentation: {indent} spaces")
                if indent > indent_levels[-1]:
                    indent_levels.append(indent)
                    tokens.append(('INDENT', indent, line_num, line_start))
                    debug(f"Added INDENT token: {indent}")
                while indent < indent_levels[-1]:
                    popped_indent = indent_levels.pop()
                    tokens.append(('DEDENT', popped_indent, line_num, line_start))
                    debug(f"Added DEDENT token: {popped_indent}")
    
        elif typ == 'SKIP':
            continue
        elif typ == 'MISMATCH':
            raise RuntimeError(f'Unexpected character {value!r} on line {line_num}')
        else:
            column = match.start() - line_start
            tokens.append((typ, value, line_num, column))
            debug(f"Added token: ({typ}, {value}, {line_num}, {column})")
    
    # Final dedents at end of file
    while len(indent_levels) > 1:
        popped_indent = indent_levels.pop()
        tokens.append(('DEDENT', popped_indent, line_num, line_start))
        debug(f"Added final DEDENT token: {popped_indent}")
    
    debug("Finished tokenizing.\n")
    return tokens

# AST Node Classes with __repr__ for Debugging
class ASTNode:
    pass

class AssignmentNode(ASTNode):
    def __init__(self, name, expression):
        self.name = name
        self.expression = expression

    def __repr__(self):
        return f"AssignmentNode(name={self.name}, expression={self.expression})"

class FunctionNode(ASTNode):
    def __init__(self, name, params, body):
        self.name = name
        self.params = params
        self.body = body

    def __repr__(self):
        return f"FunctionNode(name={self.name}, params={self.params}, body={self.body})"

class ReturnNode(ASTNode):
    def __init__(self, expression):
        self.expression = expression

    def __repr__(self):
        return f"ReturnNode(expression={self.expression})"

class BinaryOpNode(ASTNode):
    def __init__(self, left, operator, right):
        self.left = left
        self.operator = operator
        self.right = right

    def __repr__(self):
        return f"BinaryOpNode(left={self.left}, operator='{self.operator}', right={self.right})"

class NumberNode(ASTNode):
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"NumberNode(value={self.value})"

class StringNode(ASTNode):
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"StringNode(value={self.value!r})"

class IdentifierNode(ASTNode):
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"IdentifierNode(name={self.name})"

class PrintNode(ASTNode):
    def __init__(self, expression):
        self.expression = expression

    def __repr__(self):
        return f"PrintNode(expression={self.expression})"

class FunctionCallNode(ASTNode):
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments

    def __repr__(self):
        return f"FunctionCallNode(name={self.name}, arguments={self.arguments})"

class CompareNode(ASTNode):
    """Comparison: ==, !=, <, >, <=, >="""
    def __init__(self, left, operator, right):
        self.left = left
        self.operator = operator
        self.right = right

    def __repr__(self):
        return f"CompareNode(left={self.left}, operator='{self.operator}', right={self.right})"

class LogicalNode(ASTNode):
    """Logical: and, or"""
    def __init__(self, left, operator, right):
        self.left = left
        self.operator = operator
        self.right = right

    def __repr__(self):
        return f"LogicalNode(left={self.left}, operator='{self.operator}', right={self.right})"

class UnaryOpNode(ASTNode):
    """Unary: not, - (negation)"""
    def __init__(self, operator, operand):
        self.operator = operator
        self.operand = operand

    def __repr__(self):
        return f"UnaryOpNode(operator='{self.operator}', operand={self.operand})"

class BoolNode(ASTNode):
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"BoolNode(value={self.value})"

class IfNode(ASTNode):
    def __init__(self, condition, body, elif_chains=None, else_body=None):
        self.condition = condition
        self.body = body
        self.elif_chains = elif_chains or []
        self.else_body = else_body

    def __repr__(self):
        return f"IfNode(condition={self.condition}, body={self.body})"

class WhileNode(ASTNode):
    def __init__(self, condition, body):
        self.condition = condition
        self.body = body

    def __repr__(self):
        return f"WhileNode(condition={self.condition}, body={self.body})"

class ForNode(ASTNode):
    def __init__(self, var, start, end, body):
        self.var = var
        self.start = start
        self.end = end
        self.body = body

    def __repr__(self):
        return f"ForNode(var={self.var}, start={self.start}, end={self.end})"

class ListNode(ASTNode):
    def __init__(self, elements):
        self.elements = elements

    def __repr__(self):
        return f"ListNode(elements={self.elements})"

class IndexNode(ASTNode):
    def __init__(self, obj, index):
        self.obj = obj
        self.index = index

    def __repr__(self):
        return f"IndexNode(obj={self.obj}, index={self.index})"

class AppendNode(ASTNode):
    def __init__(self, list_name, value):
        self.list_name = list_name
        self.value = value

    def __repr__(self):
        return f"AppendNode(list_name={self.list_name}, value={self.value})"

class LenNode(ASTNode):
    def __init__(self, expression):
        self.expression = expression

    def __repr__(self):
        return f"LenNode(expression={self.expression})"

# Parser Class with Block Parsing and Full Control Flow
class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def parse(self):
        debug("Parsing tokens into AST...")
        statements = []
        while self.pos < len(self.tokens):
            self.skip_newlines()
            if self.pos < len(self.tokens):
                statement = self.parse_statement()
                if statement:  # Only add valid statements
                    statements.append(statement)
        debug("Finished parsing.\n")
        return statements

    def parse_statement(self):
        token_type, value, *_ = self.peek()
        debug(f"Parsing statement: token_type={token_type}, value={repr(value)}")

        if token_type == 'COMMENT':
            self.advance()
            return None
        elif token_type == 'KEYWORD' and value == 'function':
            return self.parse_function()
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
        elif token_type == 'KEYWORD' and value == 'append':
            return self.parse_append()
        elif token_type == 'IDENT':
            name = self.expect('IDENT')[1]
            if self.peek()[0] == 'ASSIGN':
                self.expect('ASSIGN')
                expression = self.parse_full_expression()
                debug(f"Parsed assignment: {name} = {expression}")
                return AssignmentNode(name, expression)
            elif self.peek()[0] == 'LBRACKET':
                # list[index] access — parse as expression starting from name
                self.expect('LBRACKET')
                idx = self.parse_full_expression()
                self.expect('RBRACKET')
                if self.peek()[0] == 'ASSIGN':
                    self.expect('ASSIGN')
                    val = self.parse_full_expression()
                    return AssignmentNode(name, val)  # Simplified indexed assign
                return IndexNode(IdentifierNode(name), idx)
            else:
                return self.parse_function_call(name)
        elif token_type == 'NEWLINE':
            self.advance()
            return None
        elif token_type in {'INDENT', 'DEDENT'}:
            debug(f"Skipping unexpected {token_type} with value={value}")
            self.advance()
            return None
        # Skip type annotations
        elif token_type == 'KEYWORD' and value in ('int', 'float', 'bool', 'string'):
            self.advance()
            return None
        else:
            raise SyntaxError(f"Unknown top-level statement: token_type={token_type}, value={repr(value)}")

    def parse_function(self):
        debug("Parsing function definition...")
        self.expect('KEYWORD', 'function')
        name = self.expect('IDENT')[1]
        params = []

        while self.peek()[0] == 'IDENT':
            params.append(self.expect('IDENT')[1])

        self.expect('NEWLINE')
        self.expect('INDENT')
        body = self.parse_block()
        self.expect('DEDENT')

        function_node = FunctionNode(name, params, body)
        debug(f"Created {function_node}\n")
        return function_node

    def parse_if(self):
        debug("Parsing if statement...")
        self.expect('KEYWORD', 'if')
        condition = self.parse_full_expression()
        self.expect('NEWLINE')
        self.expect('INDENT')
        body = self.parse_block()
        self.expect('DEDENT')

        elif_chains = []
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
        debug("Parsing while statement...")
        self.expect('KEYWORD', 'while')
        condition = self.parse_full_expression()
        self.expect('NEWLINE')
        self.expect('INDENT')
        body = self.parse_block()
        self.expect('DEDENT')
        return WhileNode(condition, body)

    def parse_for(self):
        debug("Parsing for statement...")
        self.expect('KEYWORD', 'for')
        var = self.expect('IDENT')[1]
        start = self.parse_atom()
        end = self.parse_atom()
        self.expect('NEWLINE')
        self.expect('INDENT')
        body = self.parse_block()
        self.expect('DEDENT')
        return ForNode(var, start, end, body)

    def parse_append(self):
        self.expect('KEYWORD', 'append')
        list_name = self.expect('IDENT')[1]
        value = self.parse_full_expression()
        return AppendNode(list_name, value)

    def parse_block(self):
        debug("Parsing block...")
        statements = []
        while self.peek()[0] != 'DEDENT' and self.peek()[0] != 'EOF':
            statement = self.parse_statement()
            if statement:
                statements.append(statement)
            while self.peek()[0] == 'NEWLINE':
                self.advance()
        debug(f"Parsed block: {statements}\n")
        return statements

    def parse_function_call(self, name):
        debug(f"Parsing function call for: {name}")
        arguments = []
        while self.peek()[0] in ('NUMBER', 'IDENT', 'STRING', 'LPAREN', 'LBRACKET', 'KEYWORD'):
            pk = self.peek()
            if pk[0] == 'KEYWORD' and pk[1] in ('true', 'false', 'not', 'len'):
                arguments.append(self.parse_atom())
            elif pk[0] == 'KEYWORD':
                break  # Don't consume control flow keywords as arguments
            else:
                arguments.append(self.parse_atom())
        function_call_node = FunctionCallNode(name, arguments)
        debug(f"Created {function_call_node}\n")
        return function_call_node

    # Expression parsing with proper precedence:
    # full_expression -> logical_or
    # logical_or -> logical_and ('or' logical_and)*
    # logical_and -> comparison ('and' comparison)*
    # comparison -> expression (comp_op expression)?
    # expression -> term (('+' | '-') term)*
    # term_mul -> unary (('*' | '/' | '%') unary)*
    # unary -> 'not' unary | '-' unary | atom
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
            _, op_val, *_ = self.advance()
            right = self.parse_expression()
            return CompareNode(left, op_val, right)
        return left

    def parse_expression(self):
        debug("Parsing expression...")
        left = self.parse_term_mul()
        while self.peek()[0] == 'OP' and self.peek()[1] in ('+', '-'):
            op = self.expect('OP')[1]
            right = self.parse_term_mul()
            left = BinaryOpNode(left, op, right)
        debug(f"Parsed expression: {left}\n")
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
        """Parse atom followed by optional [index] chains."""
        node = self.parse_atom()
        while self.peek()[0] == 'LBRACKET':
            self.expect('LBRACKET')
            idx = self.parse_full_expression()
            self.expect('RBRACKET')
            node = IndexNode(node, idx)
        return node

    def parse_atom(self):
        token_type, value, *_ = self.peek()
        debug(f"Parsing atom: token_type={token_type}, value={repr(value)}")

        if token_type == 'NUMBER':
            self.advance()
            number_node = NumberNode(float(value))
            debug(f"parse_atom returning NumberNode: {number_node}")
            return number_node
        elif token_type == 'STRING':
            self.advance()
            string_node = StringNode(value[1:-1])
            debug(f"parse_atom returning StringNode: {string_node}")
            return string_node
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
            # Don't treat as function call if next is [ (indexing handled in parse_postfix)
            if pk[0] == 'LBRACKET':
                return IdentifierNode(value)
            # Check if next token could be a function argument
            if pk[0] in ('NUMBER', 'STRING', 'LPAREN'):
                func_call = self.parse_function_call(value)
                debug(f"parse_atom returning FunctionCallNode: {func_call}")
                return func_call
            elif pk[0] == 'IDENT':
                func_call = self.parse_function_call(value)
                debug(f"parse_atom returning FunctionCallNode: {func_call}")
                return func_call
            elif pk[0] == 'KEYWORD' and pk[1] in ('true', 'false', 'not', 'len'):
                func_call = self.parse_function_call(value)
                return func_call
            else:
                ident_node = IdentifierNode(value)
                debug(f"parse_atom returning IdentifierNode: {ident_node}")
                return ident_node
        else:
            raise SyntaxError(f'Unexpected token: {value}')

    def parse_list_literal(self):
        self.expect('LBRACKET')
        elements = []
        while self.peek()[0] != 'RBRACKET':
            elements.append(self.parse_full_expression())
            if self.peek()[0] == 'COMMA':
                self.advance()
        self.expect('RBRACKET')
        return ListNode(elements)

    def skip_newlines(self):
        while self.peek()[0] == 'NEWLINE':
            self.advance()

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else ('EOF', None)

    def advance(self):
        token = self.tokens[self.pos]
        self.pos += 1
        debug(f"Advanced to token: {token}")
        return token

    def expect(self, token_type, value=None):
        actual_type, actual_value, *_ = self.advance()
        debug(f"Expecting token: {token_type} {repr(value)}. Got: {actual_type} {repr(actual_value)}")
        if actual_type != token_type or (value and actual_value != value):
            raise SyntaxError(f'Expected {token_type} {repr(value)}, got {actual_type} {repr(actual_value)}')
        return actual_type, actual_value

# Interpreter Class
class ReturnSignal(Exception):
    """Signal to propagate return values through nested calls."""
    def __init__(self, value):
        self.value = value

class Interpreter:
    def __init__(self):
        self.functions = {}  # Store function definitions
        self.variables = {}  # Store variable values

    def interpret(self, ast):
        debug("Interpreting AST...")
        if isinstance(ast, FunctionNode):
            debug(f"Storing function: {ast.name}\n")
            self.functions[ast.name] = ast
        elif isinstance(ast, ReturnNode):
            result = self.evaluate(ast.expression)
            debug(f"ReturnNode evaluated with result: {result}\n")
            raise ReturnSignal(result)
        elif isinstance(ast, PrintNode):
            value = self.evaluate(ast.expression)
            # Format numeric output: show integers without decimal point
            if isinstance(value, float) and value == int(value):
                print(int(value))
            elif isinstance(value, bool):
                print("true" if value else "false")
            elif isinstance(value, list):
                print(value)
            else:
                print(value)
            debug(f"Printed: {value}\n")
        elif isinstance(ast, FunctionCallNode):
            debug(f"Interpreting function call: {ast.name}")
            return self.execute_function(ast)
        elif isinstance(ast, AssignmentNode):
            value = self.evaluate(ast.expression)
            self.variables[ast.name] = value
            debug(f"Assigned {value} to {ast.name}\n")
        elif isinstance(ast, IfNode):
            self.execute_if(ast)
        elif isinstance(ast, WhileNode):
            self.execute_while(ast)
        elif isinstance(ast, ForNode):
            self.execute_for(ast)
        elif isinstance(ast, AppendNode):
            lst = self.variables.get(ast.list_name)
            if not isinstance(lst, list):
                raise RuntimeError(f"'{ast.list_name}' is not a list")
            value = self.evaluate(ast.value)
            lst.append(value)
        else:
            debug(f"Unknown AST node: {ast}\n")
            raise ValueError(f'Unknown AST node type: {ast}')

    def execute_if(self, node):
        """Execute if / else if / else statements."""
        condition = self.evaluate(node.condition)
        if self._is_truthy(condition):
            self.execute_body(node.body)
            return
        for elif_cond, elif_body in node.elif_chains:
            if self._is_truthy(self.evaluate(elif_cond)):
                self.execute_body(elif_body)
                return
        if node.else_body:
            self.execute_body(node.else_body)

    def execute_while(self, node):
        """Execute while loop."""
        while self._is_truthy(self.evaluate(node.condition)):
            self.execute_body(node.body)

    def execute_for(self, node):
        """Execute for loop (range-based)."""
        start = int(self.evaluate(node.start))
        end = int(self.evaluate(node.end))
        for i in range(start, end):
            self.variables[node.var] = float(i)
            self.execute_body(node.body)

    def execute_body(self, body):
        """Execute a list of statements. Propagates ReturnSignal."""
        for stmt in body:
            self.interpret(stmt)

    def _is_truthy(self, value):
        """Determine truthiness of a value."""
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return len(value) > 0
        if value is None:
            return False
        return True

    def execute_function(self, call_node):
        func = self.functions.get(call_node.name)
        if not func:
            raise RuntimeError(f"Function {call_node.name} is not defined.")

        debug(f"Executing function: {call_node.name} with arguments {call_node.arguments}")
        saved_env = self.variables.copy()
        for param, arg in zip(func.params, call_node.arguments):
            evaluated_arg = self.evaluate(arg)
            self.variables[param] = evaluated_arg
            debug(f"Set parameter '{param}' to {evaluated_arg}")

        result = None
        try:
            for stmt in func.body:
                self.interpret(stmt)
        except ReturnSignal as ret:
            result = ret.value

        self.variables = saved_env
        debug(f"Function {call_node.name} returned {result}\n")
        return result

    def evaluate(self, node):
        debug(f"Evaluating node: {node}")
        if isinstance(node, NumberNode):
            return node.value
        elif isinstance(node, StringNode):
            return node.value
        elif isinstance(node, BoolNode):
            return node.value
        elif isinstance(node, IdentifierNode):
            if node.name in self.variables:
                value = self.variables[node.name]
                debug(f"Identifier '{node.name}' is a variable with value {value}")
                return value
            elif node.name in self.functions:
                debug(f"Identifier '{node.name}' is a function name")
                return node.name
            else:
                raise RuntimeError(f"Name '{node.name}' is not defined.")
        elif isinstance(node, BinaryOpNode):
            left = self.evaluate(node.left)
            right = self.evaluate(node.right)
            debug(f"Performing operation: {left} {node.operator} {right}")
            if node.operator == '+':
                return left + right
            elif node.operator == '-':
                return left - right
            elif node.operator == '*':
                return left * right
            elif node.operator == '/':
                if right == 0:
                    raise RuntimeError("Division by zero")
                return left / right
            elif node.operator == '%':
                if right == 0:
                    raise RuntimeError("Modulo by zero")
                return left % right
            else:
                raise ValueError(f'Unknown operator: {node.operator}')
        elif isinstance(node, CompareNode):
            left = self.evaluate(node.left)
            right = self.evaluate(node.right)
            debug(f"Comparing: {left} {node.operator} {right}")
            if node.operator == '==':
                return left == right
            elif node.operator == '!=':
                return left != right
            elif node.operator == '<':
                return left < right
            elif node.operator == '>':
                return left > right
            elif node.operator == '<=':
                return left <= right
            elif node.operator == '>=':
                return left >= right
            else:
                raise ValueError(f'Unknown comparison operator: {node.operator}')
        elif isinstance(node, LogicalNode):
            left = self.evaluate(node.left)
            if node.operator == 'and':
                return self._is_truthy(left) and self._is_truthy(self.evaluate(node.right))
            elif node.operator == 'or':
                return self._is_truthy(left) or self._is_truthy(self.evaluate(node.right))
            else:
                raise ValueError(f'Unknown logical operator: {node.operator}')
        elif isinstance(node, UnaryOpNode):
            operand = self.evaluate(node.operand)
            if node.operator == 'not':
                return not self._is_truthy(operand)
            elif node.operator == '-':
                return -operand
            else:
                raise ValueError(f'Unknown unary operator: {node.operator}')
        elif isinstance(node, FunctionCallNode):
            return self.execute_function(node)
        elif isinstance(node, ListNode):
            return [self.evaluate(e) for e in node.elements]
        elif isinstance(node, IndexNode):
            obj = self.evaluate(node.obj)
            idx = int(self.evaluate(node.index))
            if isinstance(obj, list):
                if idx < 0 or idx >= len(obj):
                    raise RuntimeError(f"Index {idx} out of bounds (size {len(obj)})")
                return obj[idx]
            raise RuntimeError(f"Cannot index into {type(obj).__name__}")
        elif isinstance(node, LenNode):
            obj = self.evaluate(node.expression)
            if isinstance(obj, (list, str)):
                return float(len(obj))
            raise RuntimeError(f"Cannot get length of {type(obj).__name__}")
        else:
            raise ValueError(f'Unknown node type: {node}')

# Main Execution Code
def main():
    global DEBUG

    # Parse --debug flag before filename
    args = sys.argv[1:]
    if '--debug' in args:
        DEBUG = True
        args.remove('--debug')

    if len(args) != 1:
        print("Usage: python saurav.py <filename>.srv [--debug]")
        sys.exit(1)
    
    filename = args[0]
    
    if not filename.endswith('.srv'):
        print("Error: The file must have a .srv extension.")
        sys.exit(1)
    
    if not os.path.isfile(filename):
        print(f"Error: File '{filename}' does not exist.")
        sys.exit(1)
    
    try:
        with open(filename, 'r') as file:
            code = file.read()
            debug(f"Read code from {filename}:\n{code}\n")
    except Exception as e:
        print(f"Error reading file '{filename}': {e}")
        sys.exit(1)
    
    # Tokenize and parse multiple top-level statements
    tokens = list(tokenize(code))
    debug(f"\nTokens: {tokens}\n")

    parser = Parser(tokens)
    ast_nodes = parser.parse()
    debug(f"\nAST: {ast_nodes}\n")

    # Interpret each top-level AST node
    interpreter = Interpreter()
    result = None
    for node in ast_nodes:
        if isinstance(node, FunctionNode):
            interpreter.interpret(node)  # Store the function definitions
        elif isinstance(node, FunctionCallNode):
            result = interpreter.execute_function(node)  # Execute standalone function calls
        elif isinstance(node, (PrintNode, AssignmentNode, IfNode, WhileNode, ForNode, AppendNode)):
            interpreter.interpret(node)  # Execute statements
        else:
            interpreter.interpret(node)
    
    if result is not None:
        print("\nFinal result:", result)

if __name__ == '__main__':
    main()
