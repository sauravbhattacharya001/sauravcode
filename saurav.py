import re
import sys
import os
import math

# Debug flag — enabled with --debug command-line argument
DEBUG = False

# Security limits to prevent denial-of-service attacks
MAX_RECURSION_DEPTH = 500      # Maximum nested function call depth
MAX_LOOP_ITERATIONS = 10_000_000  # Maximum iterations per loop

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
    ('FSTRING',  r'f\"(?:[^\"\\]|\\.)*\"'),  # F-string literal (interpolated string)
    ('STRING',   r'\"(?:[^\"\\]|\\.)*\"'),  # String literal (with escape support)
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
    ('LBRACE',   r'\{'),  # Left brace (for maps)
    ('RBRACE',   r'\}'),  # Right brace (for maps)
    ('COLON',    r':'),   # Colon (for map key-value pairs)
    ('COMMA',    r','),   # Comma separator
    ('KEYWORD',  r'\b(?:function|return|class|int|float|bool|string|if|else if|else|for|in|while|try|catch|throw|print|true|false|and|or|not|list|set|map|stack|queue|append|len|pop)\b'),  # All keywords
    ('IDENT',    r'[a-zA-Z_]\w*'),  # Identifiers
    ('NEWLINE',  r'\n'),  # Newlines
    ('SKIP',     r'[ \t]+'),  # Whitespace
    ('MISMATCH', r'.'),  # Any other character
]

tok_regex = re.compile('|'.join(f'(?P<{pair[0]}>{pair[1]})' for pair in token_specification))
_indent_re = re.compile(r'[ \t]*')

def tokenize(code):
    debug("Tokenizing code...")
    tokens = []
    line_num = 1
    line_start = 0
    indent_levels = [0]  # Track indentation levels
    
    for match in tok_regex.finditer(code):
        typ = match.lastgroup
        value = match.group(typ)
        debug(f"Token: {typ}, Value: {repr(value)}")

        if typ == 'NEWLINE':
            line_num += 1
            line_start = match.end()
            tokens.append(('NEWLINE', value, line_num, match.start()))
            
            # Handle indentation on the next line
            indent_match = _indent_re.match(code, line_start)
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
    
        elif typ in ('SKIP', 'COMMENT'):
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

class MapNode(ASTNode):
    def __init__(self, pairs):
        self.pairs = pairs  # list of (key_expr, value_expr) tuples

    def __repr__(self):
        return f"MapNode(pairs={self.pairs})"

class FStringNode(ASTNode):
    """Interpolated string: f"Hello {name}, you are {age} years old"
    
    Parts is a list of items — each is either a StringNode (literal text)
    or an expression node (to be evaluated and converted to string).
    """
    def __init__(self, parts):
        self.parts = parts  # list of ASTNode (StringNode for literals, others for expressions)

    def __repr__(self):
        return f"FStringNode(parts={self.parts})"

class IndexedAssignmentNode(ASTNode):
    """Assignment to a collection element: list[index] = value, map[key] = value"""
    def __init__(self, name, index, value):
        self.name = name
        self.index = index
        self.value = value

    def __repr__(self):
        return f"IndexedAssignmentNode(name={self.name}, index={self.index}, value={self.value})"

class TryCatchNode(ASTNode):
    """Try/catch error handling block.
    
    try
        body...
    catch error_var
        handler...
    """
    def __init__(self, body, error_var, handler):
        self.body = body         # list of statements in try block
        self.error_var = error_var  # variable name to bind error message (string)
        self.handler = handler   # list of statements in catch block

    def __repr__(self):
        return f"TryCatchNode(body={self.body}, error_var={self.error_var}, handler={self.handler})"

class ThrowNode(ASTNode):
    """Throw an error with a message expression.
    
    throw "something went wrong"
    throw f"invalid value: {x}"
    """
    def __init__(self, expression):
        self.expression = expression  # expression that evaluates to the error message

    def __repr__(self):
        return f"ThrowNode(expression={self.expression})"

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

        if token_type == 'KEYWORD' and value == 'function':
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
        elif token_type == 'KEYWORD' and value == 'try':
            return self.parse_try_catch()
        elif token_type == 'KEYWORD' and value == 'throw':
            return self.parse_throw()
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
                # list[index] or map[key] access — parse index
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

    def parse_try_catch(self):
        """Parse try/catch block:
        
        try
            ... body ...
        catch error_var
            ... handler ...
        """
        debug("Parsing try/catch statement...")
        self.expect('KEYWORD', 'try')
        self.expect('NEWLINE')
        self.expect('INDENT')
        body = self.parse_block()
        self.expect('DEDENT')

        self.expect('KEYWORD', 'catch')
        error_var = self.expect('IDENT')[1]
        self.expect('NEWLINE')
        self.expect('INDENT')
        handler = self.parse_block()
        self.expect('DEDENT')

        return TryCatchNode(body, error_var, handler)

    def parse_throw(self):
        """Parse throw statement: throw expression"""
        debug("Parsing throw statement...")
        self.expect('KEYWORD', 'throw')
        expression = self.parse_full_expression()
        return ThrowNode(expression)

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
        while self.peek()[0] in ('NUMBER', 'IDENT', 'STRING', 'FSTRING', 'LPAREN', 'LBRACKET', 'LBRACE', 'KEYWORD'):
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
        elif token_type == 'FSTRING':
            self.advance()
            fstring_node = self.parse_fstring(value)
            debug(f"parse_atom returning FStringNode: {fstring_node}")
            return fstring_node
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
        elif token_type == 'LBRACE':
            return self.parse_map_literal()
        elif token_type == 'IDENT':
            self.advance()
            pk = self.peek()
            # Don't treat as function call if next is [ (indexing handled in parse_postfix)
            if pk[0] == 'LBRACKET':
                return IdentifierNode(value)
            # Check if next token could be a function argument
            if pk[0] in ('NUMBER', 'STRING', 'FSTRING', 'LPAREN'):
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
            elif pk[0] == 'LBRACE':
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
                # Handle escape sequences
                text_buf.append(content[i + 1])
                i += 2
            elif ch == '{':
                # Check for escaped brace {{ → literal {
                if i + 1 < len(content) and content[i + 1] == '{':
                    text_buf.append('{')
                    i += 2
                    continue
                # Flush accumulated text
                if text_buf:
                    parts.append(StringNode(''.join(text_buf)))
                    text_buf = []
                # Find matching closing brace
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
                # Extract the expression text and parse it
                expr_text = content[i + 1:j - 1].strip()
                if not expr_text:
                    raise SyntaxError("Empty expression in f-string")
                # Tokenize and parse the expression
                expr_code = expr_text + '\n'
                expr_tokens = list(tokenize(expr_code))
                expr_parser = Parser(expr_tokens)
                expr_node = expr_parser.parse_full_expression()
                parts.append(expr_node)
                i = j
            elif ch == '}':
                # Check for escaped brace }} → literal }
                if i + 1 < len(content) and content[i + 1] == '}':
                    text_buf.append('}')
                    i += 2
                    continue
                raise SyntaxError("Unmatched '}' in f-string")
            else:
                text_buf.append(ch)
                i += 1
        
        # Flush remaining text
        if text_buf:
            parts.append(StringNode(''.join(text_buf)))
        
        return FStringNode(parts)

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

class ThrowSignal(Exception):
    """Signal to propagate thrown errors through execution.
    
    Caught by try/catch blocks. If uncaught, becomes a RuntimeError.
    """
    def __init__(self, message):
        self.message = message

class Interpreter:
    def __init__(self):
        self.functions = {}  # Store function definitions
        self.variables = {}  # Store variable values
        self._call_depth = 0  # Track recursion depth for DoS protection
        self._init_builtins()
        self._init_dispatch_tables()

    def _init_dispatch_tables(self):
        """Initialize dispatch tables for O(1) node-type lookup.

        Replaces long isinstance chains in interpret() and evaluate()
        with dict-based dispatch. This is the hottest code path in the
        interpreter, so the speedup is meaningful for loops and recursion.
        """
        # Dispatch table for interpret() — statement-level nodes
        self._interpret_dispatch = {
            FunctionNode:           self._interp_function,
            ReturnNode:             self._interp_return,
            PrintNode:              self._interp_print,
            FunctionCallNode:       self._interp_function_call,
            AssignmentNode:         self._interp_assignment,
            IndexedAssignmentNode:  self._interp_indexed_assignment,
            IfNode:                 self.execute_if,
            WhileNode:              self.execute_while,
            ForNode:                self.execute_for,
            TryCatchNode:           self.execute_try_catch,
            ThrowNode:              self.execute_throw,
            AppendNode:             self._interp_append,
        }

        # Dispatch table for evaluate() — expression-level nodes
        self._evaluate_dispatch = {
            NumberNode:       self._eval_number,
            StringNode:       self._eval_string,
            BoolNode:         self._eval_bool,
            IdentifierNode:   self._eval_identifier,
            BinaryOpNode:     self._eval_binary_op,
            CompareNode:      self._eval_compare,
            LogicalNode:      self._eval_logical,
            UnaryOpNode:      self._eval_unary,
            FunctionCallNode: self.execute_function,
            ListNode:         self._eval_list,
            IndexNode:        self._eval_index,
            LenNode:          self._eval_len,
            MapNode:           self._eval_map,
            FStringNode:      self._eval_fstring,
        }

    def _init_builtins(self):
        """Register built-in standard library functions."""
        self.builtins = {
            # --- String functions ---
            'upper':       self._builtin_upper,
            'lower':       self._builtin_lower,
            'trim':        self._builtin_trim,
            'replace':     self._builtin_replace,
            'split':       self._builtin_split,
            'join':        self._builtin_join,
            'contains':    self._builtin_contains,
            'starts_with': self._builtin_starts_with,
            'ends_with':   self._builtin_ends_with,
            'substring':   self._builtin_substring,
            'index_of':    self._builtin_index_of,
            'char_at':     self._builtin_char_at,
            # --- Math functions ---
            'abs':         self._builtin_abs,
            'round':       self._builtin_round,
            'floor':       self._builtin_floor,
            'ceil':        self._builtin_ceil,
            'sqrt':        self._builtin_sqrt,
            'power':       self._builtin_power,
            # --- Utility functions ---
            'type_of':     self._builtin_type_of,
            'to_string':   self._builtin_to_string,
            'to_number':   self._builtin_to_number,
            'input':       self._builtin_input,
            'range':       self._builtin_range,
            'reverse':     self._builtin_reverse,
            'sort':        self._builtin_sort,
            # --- Map functions ---
            'keys':        self._builtin_keys,
            'values':      self._builtin_values,
            'has_key':     self._builtin_has_key,
        }

    # --- String built-ins ---
    def _builtin_upper(self, args):
        self._expect_args('upper', args, 1)
        s = args[0]
        if not isinstance(s, str):
            raise RuntimeError("upper expects a string argument")
        return s.upper()

    def _builtin_lower(self, args):
        self._expect_args('lower', args, 1)
        s = args[0]
        if not isinstance(s, str):
            raise RuntimeError("lower expects a string argument")
        return s.lower()

    def _builtin_trim(self, args):
        self._expect_args('trim', args, 1)
        s = args[0]
        if not isinstance(s, str):
            raise RuntimeError("trim expects a string argument")
        return s.strip()

    def _builtin_replace(self, args):
        self._expect_args('replace', args, 3)
        s, old, new = args
        if not isinstance(s, str):
            raise RuntimeError("replace expects a string as first argument")
        return s.replace(str(old), str(new))

    def _builtin_split(self, args):
        self._expect_args('split', args, 2)
        s, delim = args
        if not isinstance(s, str):
            raise RuntimeError("split expects a string as first argument")
        return s.split(str(delim))

    def _builtin_join(self, args):
        self._expect_args('join', args, 2)
        delim, lst = args
        if not isinstance(lst, list):
            raise RuntimeError("join expects a list as second argument")
        items = []
        for item in lst:
            if isinstance(item, float) and item == int(item):
                items.append(str(int(item)))
            else:
                items.append(str(item))
        return str(delim).join(items)

    def _builtin_contains(self, args):
        self._expect_args('contains', args, 2)
        s, sub = args
        if isinstance(s, str):
            return str(sub) in s
        if isinstance(s, list):
            return sub in s
        if isinstance(s, dict):
            return sub in s
        raise RuntimeError("contains expects a string, list, or map as first argument")

    def _builtin_starts_with(self, args):
        self._expect_args('starts_with', args, 2)
        s, prefix = args
        if not isinstance(s, str):
            raise RuntimeError("starts_with expects a string as first argument")
        return s.startswith(str(prefix))

    def _builtin_ends_with(self, args):
        self._expect_args('ends_with', args, 2)
        s, suffix = args
        if not isinstance(s, str):
            raise RuntimeError("ends_with expects a string as first argument")
        return s.endswith(str(suffix))

    def _builtin_substring(self, args):
        self._expect_args('substring', args, 3)
        s, start, end = args
        if not isinstance(s, str):
            raise RuntimeError("substring expects a string as first argument")
        return s[int(start):int(end)]

    def _builtin_index_of(self, args):
        self._expect_args('index_of', args, 2)
        s, sub = args
        if not isinstance(s, str):
            raise RuntimeError("index_of expects a string as first argument")
        idx = s.find(str(sub))
        return float(idx)

    def _builtin_char_at(self, args):
        self._expect_args('char_at', args, 2)
        s, idx = args
        if not isinstance(s, str):
            raise RuntimeError("char_at expects a string as first argument")
        i = int(idx)
        if i < 0 or i >= len(s):
            raise RuntimeError(f"char_at index {i} out of bounds (length {len(s)})")
        return s[i]

    # --- Math built-ins ---
    def _builtin_abs(self, args):
        self._expect_args('abs', args, 1)
        return float(abs(args[0]))

    def _builtin_round(self, args):
        if len(args) == 1:
            return float(round(args[0]))
        elif len(args) == 2:
            return float(round(args[0], int(args[1])))
        else:
            raise RuntimeError("round expects 1 or 2 arguments: round value [places]")

    def _builtin_floor(self, args):
        self._expect_args('floor', args, 1)
        return float(math.floor(args[0]))

    def _builtin_ceil(self, args):
        self._expect_args('ceil', args, 1)
        return float(math.ceil(args[0]))

    def _builtin_sqrt(self, args):
        self._expect_args('sqrt', args, 1)
        if args[0] < 0:
            raise RuntimeError("sqrt of negative number")
        return float(math.sqrt(args[0]))

    def _builtin_power(self, args):
        self._expect_args('power', args, 2)
        return float(args[0] ** args[1])

    # --- Utility built-ins ---
    def _builtin_type_of(self, args):
        self._expect_args('type_of', args, 1)
        val = args[0]
        if isinstance(val, bool):
            return "bool"
        if isinstance(val, float):
            return "number"
        if isinstance(val, str):
            return "string"
        if isinstance(val, list):
            return "list"
        if isinstance(val, dict):
            return "map"
        return "unknown"

    def _builtin_to_string(self, args):
        self._expect_args('to_string', args, 1)
        val = args[0]
        if isinstance(val, float) and val == int(val):
            return str(int(val))
        if isinstance(val, bool):
            return "true" if val else "false"
        if isinstance(val, dict):
            return _format_map(val)
        return str(val)

    def _builtin_to_number(self, args):
        self._expect_args('to_number', args, 1)
        val = args[0]
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            try:
                return float(val)
            except ValueError:
                raise RuntimeError(f"Cannot convert '{val}' to number")
        if isinstance(val, bool):
            return 1.0 if val else 0.0
        raise RuntimeError(f"Cannot convert {type(val).__name__} to number")

    def _builtin_input(self, args):
        if len(args) == 0:
            return input()
        elif len(args) == 1:
            return input(str(args[0]))
        else:
            raise RuntimeError("input expects 0 or 1 arguments: input [prompt]")

    def _builtin_range(self, args):
        if len(args) == 1:
            return [float(i) for i in range(int(args[0]))]
        elif len(args) == 2:
            return [float(i) for i in range(int(args[0]), int(args[1]))]
        elif len(args) == 3:
            return [float(i) for i in range(int(args[0]), int(args[1]), int(args[2]))]
        else:
            raise RuntimeError("range expects 1-3 arguments: range end | range start end | range start end step")

    def _builtin_reverse(self, args):
        self._expect_args('reverse', args, 1)
        val = args[0]
        if isinstance(val, list):
            return val[::-1]
        if isinstance(val, str):
            return val[::-1]
        raise RuntimeError("reverse expects a list or string argument")

    def _builtin_sort(self, args):
        self._expect_args('sort', args, 1)
        val = args[0]
        if not isinstance(val, list):
            raise RuntimeError("sort expects a list argument")
        return sorted(val)

    # --- Map built-ins ---
    def _builtin_keys(self, args):
        self._expect_args('keys', args, 1)
        val = args[0]
        if not isinstance(val, dict):
            raise RuntimeError("keys expects a map argument")
        return list(val.keys())

    def _builtin_values(self, args):
        self._expect_args('values', args, 1)
        val = args[0]
        if not isinstance(val, dict):
            raise RuntimeError("values expects a map argument")
        return list(val.values())

    def _builtin_has_key(self, args):
        self._expect_args('has_key', args, 2)
        m, key = args
        if not isinstance(m, dict):
            raise RuntimeError("has_key expects a map as first argument")
        return key in m

    def _expect_args(self, name, args, count):
        if len(args) != count:
            raise RuntimeError(f"{name} expects {count} argument(s), got {len(args)}")

    def interpret(self, ast):
        debug("Interpreting AST...")
        handler = self._interpret_dispatch.get(type(ast))
        if handler is not None:
            return handler(ast)
        else:
            raise ValueError(f'Unknown AST node type: {type(ast).__name__}')

    # ── interpret dispatch handlers ──────────────────────────

    def _interp_function(self, ast):
        debug(f"Storing function: {ast.name}\n")
        self.functions[ast.name] = ast

    def _interp_return(self, ast):
        result = self.evaluate(ast.expression)
        debug(f"ReturnNode evaluated with result: {result}\n")
        raise ReturnSignal(result)

    def _interp_print(self, ast):
        value = self.evaluate(ast.expression)
        # Format numeric output: show integers without decimal point
        if isinstance(value, float) and value == int(value):
            print(int(value))
        elif isinstance(value, bool):
            print("true" if value else "false")
        elif isinstance(value, list):
            print(_format_list(value))
        elif isinstance(value, dict):
            print(_format_map(value))
        else:
            print(value)
        debug(f"Printed: {value}\n")

    def _interp_function_call(self, ast):
        debug(f"Interpreting function call: {ast.name}")
        return self.execute_function(ast)

    def _interp_assignment(self, ast):
        value = self.evaluate(ast.expression)
        self.variables[ast.name] = value
        debug(f"Assigned {value} to {ast.name}\n")

    def _interp_indexed_assignment(self, ast):
        collection = self.variables.get(ast.name)
        idx_or_key = self.evaluate(ast.index)
        value = self.evaluate(ast.value)
        if isinstance(collection, list):
            idx = int(idx_or_key)
            if idx < 0 or idx >= len(collection):
                raise RuntimeError(f"Index {idx} out of bounds (size {len(collection)})")
            collection[idx] = value
        elif isinstance(collection, dict):
            collection[idx_or_key] = value
        else:
            raise RuntimeError(f"'{ast.name}' is not a list or map")
        debug(f"Indexed assignment: {ast.name}[{idx_or_key}] = {value}\n")

    def _interp_append(self, ast):
        lst = self.variables.get(ast.list_name)
        if not isinstance(lst, list):
            raise RuntimeError(f"'{ast.list_name}' is not a list")
        value = self.evaluate(ast.value)
        lst.append(value)

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
        """Execute while loop with iteration limit for DoS protection."""
        iterations = 0
        while self._is_truthy(self.evaluate(node.condition)):
            iterations += 1
            if iterations > MAX_LOOP_ITERATIONS:
                raise RuntimeError(
                    f"Maximum loop iterations ({MAX_LOOP_ITERATIONS:,}) exceeded "
                    f"in while loop"
                )
            self.execute_body(node.body)

    def execute_for(self, node):
        """Execute for loop (range-based) with iteration limit for DoS protection."""
        start = int(self.evaluate(node.start))
        end = int(self.evaluate(node.end))
        if abs(end - start) > MAX_LOOP_ITERATIONS:
            raise RuntimeError(
                f"For loop range ({abs(end - start):,}) exceeds maximum "
                f"iterations ({MAX_LOOP_ITERATIONS:,})"
            )
        for i in range(start, end):
            self.variables[node.var] = float(i)
            self.execute_body(node.body)

    def execute_try_catch(self, node):
        """Execute try/catch block.
        
        Catches ThrowSignal (user-thrown errors) and RuntimeError
        (built-in errors like division by zero, index out of bounds).
        Binds the error message string to the catch variable.
        """
        try:
            self.execute_body(node.body)
        except ThrowSignal as e:
            # User-thrown error — bind message to catch variable
            msg = e.message
            if isinstance(msg, float) and msg == int(msg):
                self.variables[node.error_var] = str(int(msg))
            else:
                self.variables[node.error_var] = str(msg)
            self.execute_body(node.handler)
        except RuntimeError as e:
            # Built-in runtime error — bind message to catch variable
            self.variables[node.error_var] = str(e)
            self.execute_body(node.handler)

    def execute_throw(self, node):
        """Execute throw statement — raises ThrowSignal with the evaluated message."""
        message = self.evaluate(node.expression)
        raise ThrowSignal(message)

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
        # Check user-defined functions first (allows overriding builtins)
        func = self.functions.get(call_node.name)
        if func:
            debug(f"Executing function: {call_node.name} with arguments {call_node.arguments}")

            # Guard against excessive recursion (DoS protection)
            self._call_depth += 1
            if self._call_depth > MAX_RECURSION_DEPTH:
                self._call_depth -= 1
                raise RuntimeError(
                    f"Maximum recursion depth ({MAX_RECURSION_DEPTH}) exceeded "
                    f"in function '{call_node.name}'"
                )

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
            finally:
                self._call_depth -= 1
                self.variables = saved_env
            debug(f"Function {call_node.name} returned {result}\n")
            return result

        # Check built-in functions
        if call_node.name in self.builtins:
            evaluated_args = [self.evaluate(arg) for arg in call_node.arguments]
            return self.builtins[call_node.name](evaluated_args)

        raise RuntimeError(f"Function {call_node.name} is not defined.")

    def evaluate(self, node):
        debug(f"Evaluating node: {node}")
        handler = self._evaluate_dispatch.get(type(node))
        if handler is not None:
            return handler(node)
        else:
            raise ValueError(f'Unknown node type: {node}')

    # ── evaluate dispatch handlers ───────────────────────────

    def _eval_number(self, node):
        return node.value

    def _eval_string(self, node):
        return node.value

    def _eval_bool(self, node):
        return node.value

    def _eval_identifier(self, node):
        if node.name in self.variables:
            value = self.variables[node.name]
            debug(f"Identifier '{node.name}' is a variable with value {value}")
            return value
        elif node.name in self.functions:
            debug(f"Identifier '{node.name}' is a function name")
            return node.name
        elif node.name in self.builtins:
            debug(f"Identifier '{node.name}' is a built-in function")
            return node.name
        else:
            raise RuntimeError(f"Name '{node.name}' is not defined.")

    def _eval_binary_op(self, node):
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

    def _eval_compare(self, node):
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

    def _eval_logical(self, node):
        left = self.evaluate(node.left)
        if node.operator == 'and':
            return self._is_truthy(left) and self._is_truthy(self.evaluate(node.right))
        elif node.operator == 'or':
            return self._is_truthy(left) or self._is_truthy(self.evaluate(node.right))
        else:
            raise ValueError(f'Unknown logical operator: {node.operator}')

    def _eval_unary(self, node):
        operand = self.evaluate(node.operand)
        if node.operator == 'not':
            return not self._is_truthy(operand)
        elif node.operator == '-':
            return -operand
        else:
            raise ValueError(f'Unknown unary operator: {node.operator}')

    def _eval_list(self, node):
        return [self.evaluate(e) for e in node.elements]

    def _eval_index(self, node):
        obj = self.evaluate(node.obj)
        idx = self.evaluate(node.index)
        if isinstance(obj, list):
            i = int(idx)
            if i < 0 or i >= len(obj):
                raise RuntimeError(f"Index {i} out of bounds (size {len(obj)})")
            return obj[i]
        if isinstance(obj, dict):
            if idx not in obj:
                raise RuntimeError(f"Key {idx!r} not found in map")
            return obj[idx]
        raise RuntimeError(f"Cannot index into {type(obj).__name__}")

    def _eval_len(self, node):
        obj = self.evaluate(node.expression)
        if isinstance(obj, (list, str)):
            return float(len(obj))
        if isinstance(obj, dict):
            return float(len(obj))
        raise RuntimeError(f"Cannot get length of {type(obj).__name__}")

    def _eval_map(self, node):
        result = {}
        for key_expr, val_expr in node.pairs:
            key = self.evaluate(key_expr)
            val = self.evaluate(val_expr)
            result[key] = val
        return result

    def _eval_fstring(self, node):
        parts = []
        for part in node.parts:
            val = self.evaluate(part)
            if isinstance(val, float) and val == int(val):
                parts.append(str(int(val)))
            elif isinstance(val, bool):
                parts.append("true" if val else "false")
            elif isinstance(val, list):
                parts.append(_format_list(val))
            elif isinstance(val, dict):
                parts.append(_format_map(val))
            else:
                parts.append(str(val))
        return ''.join(parts)


def _format_list(lst):
    """Format a list for display."""
    items = []
    for v in lst:
        if isinstance(v, str):
            items.append(f'"{v}"')
        elif isinstance(v, float) and v == int(v):
            items.append(str(int(v)))
        elif isinstance(v, bool):
            items.append("true" if v else "false")
        elif isinstance(v, dict):
            items.append(_format_map(v))
        elif isinstance(v, list):
            items.append(_format_list(v))
        else:
            items.append(str(v))
    return "[" + ", ".join(items) + "]"


def _format_map(m):
    """Format a map/dict for display."""
    pairs = []
    for k, v in m.items():
        if isinstance(k, str):
            key_str = f'"{k}"'
        elif isinstance(k, float) and k == int(k):
            key_str = str(int(k))
        else:
            key_str = str(k)
        if isinstance(v, str):
            val_str = f'"{v}"'
        elif isinstance(v, float) and v == int(v):
            val_str = str(int(v))
        elif isinstance(v, bool):
            val_str = "true" if v else "false"
        elif isinstance(v, dict):
            val_str = _format_map(v)
        elif isinstance(v, list):
            val_str = _format_list(v)
        else:
            val_str = str(v)
        pairs.append(f"{key_str}: {val_str}")
    return "{" + ", ".join(pairs) + "}"


# REPL (Read-Eval-Print Loop)
def format_value(value):
    """Format a value for REPL display."""
    if value is None:
        return None
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, list):
        items = ", ".join(format_value(v) for v in value)
        return f"[{items}]"
    if isinstance(value, dict):
        return _format_map(value)
    return str(value)


def repl():
    """Interactive sauravcode REPL."""
    print("sauravcode REPL v1.0")
    print('Type "help" for commands, "quit" to exit.\n')

    interpreter = Interpreter()
    history = []

    while True:
        try:
            line = input(">>> ")
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        stripped = line.strip()

        # REPL commands
        if stripped == "quit" or stripped == "exit":
            print("Bye!")
            break
        if stripped == "help":
            print("sauravcode REPL commands:")
            print("  help      — show this help message")
            print("  vars      — list all defined variables")
            print("  funcs     — list all defined functions")
            print("  builtins  — list all built-in functions")
            print("  clear     — clear all variables and functions")
            print("  history   — show input history")
            print("  load FILE — load and run a .srv file")
            print("  quit/exit — exit the REPL")
            print()
            print("Write sauravcode directly at the prompt.")
            print("For multi-line blocks (functions, if, while, for),")
            print("indent with spaces and enter a blank line to execute.")
            print()
            print("F-strings: use f\"Hello {name}!\" to embed expressions in strings.")
            print()
            continue
        if stripped == "builtins":
            builtin_info = {
                'upper':       'upper str           — convert string to uppercase',
                'lower':       'lower str           — convert string to lowercase',
                'trim':        'trim str            — remove leading/trailing whitespace',
                'replace':     'replace str old new — replace occurrences in string',
                'split':       'split str delim     — split string into list',
                'join':        'join delim list     — join list into string',
                'contains':    'contains str sub    — check if string/list/map contains value',
                'starts_with': 'starts_with str pre — check if string starts with prefix',
                'ends_with':   'ends_with str suf   — check if string ends with suffix',
                'substring':   'substring str s e   — extract substring [start:end]',
                'index_of':    'index_of str sub    — find index of substring (-1 if not found)',
                'char_at':     'char_at str idx     — get character at index',
                'abs':         'abs n               — absolute value',
                'round':       'round n [places]    — round number',
                'floor':       'floor n             — round down to integer',
                'ceil':        'ceil n              — round up to integer',
                'sqrt':        'sqrt n              — square root',
                'power':       'power base exp      — exponentiation',
                'type_of':     'type_of val         — get type name (number/string/bool/list/map)',
                'to_string':   'to_string val       — convert value to string',
                'to_number':   'to_number val       — convert value to number',
                'input':       'input [prompt]      — read line from stdin',
                'range':       'range [start] end [step] — generate list of numbers',
                'reverse':     'reverse val         — reverse a list or string',
                'sort':        'sort list           — sort a list',
                'keys':        'keys map            — get list of map keys',
                'values':      'values map          — get list of map values',
                'has_key':     'has_key map key     — check if map contains key',
            }
            print("Built-in functions:")
            for name in sorted(builtin_info.keys()):
                print(f"  {builtin_info[name]}")
            continue
        if stripped == "vars":
            if not interpreter.variables:
                print("(no variables defined)")
            else:
                for name, val in sorted(interpreter.variables.items()):
                    print(f"  {name} = {format_value(val)}")
            continue
        if stripped == "funcs":
            if not interpreter.functions:
                print("(no functions defined)")
            else:
                for name, func in sorted(interpreter.functions.items()):
                    params = " ".join(func.params) if func.params else ""
                    print(f"  function {name} {params}".rstrip())
            continue
        if stripped == "clear":
            interpreter.variables.clear()
            interpreter.functions.clear()
            print("Cleared all variables and functions.")
            continue
        if stripped == "history":
            if not history:
                print("(no history)")
            else:
                for i, entry in enumerate(history, 1):
                    # Show multi-line entries compactly
                    lines = entry.split('\n')
                    print(f"  [{i}] {lines[0]}")
                    for extra in lines[1:]:
                        print(f"       {extra}")
            continue
        if stripped.startswith("load "):
            filepath = stripped[5:].strip()
            if not filepath.endswith('.srv'):
                filepath += '.srv'
            if not os.path.isfile(filepath):
                print(f"Error: File '{filepath}' not found.")
                continue
            try:
                with open(filepath, 'r') as f:
                    code = f.read()
                _repl_execute(code, interpreter)
                print(f"Loaded {filepath}")
            except Exception as e:
                print(f"Error: {e}")
            continue

        if not stripped:
            continue

        # Multi-line block detection: if the line starts a block construct,
        # keep reading indented lines until a blank line is entered
        block_starters = ('function ', 'if ', 'while ', 'for ', 'class ', 'try')
        needs_block = any(stripped.startswith(s) for s in block_starters)

        code = line
        if needs_block:
            while True:
                try:
                    continuation = input("... ")
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                if continuation.strip() == "":
                    break
                code += "\n" + continuation

        history.append(code)

        # Ensure code ends with newline for tokenizer
        if not code.endswith('\n'):
            code += '\n'

        try:
            _repl_execute(code, interpreter)
        except ThrowSignal as e:
            msg = e.message
            if isinstance(msg, float) and msg == int(msg):
                msg = int(msg)
            print(f"Uncaught error: {msg}")
        except SyntaxError as e:
            print(f"SyntaxError: {e}")
        except RuntimeError as e:
            print(f"RuntimeError: {e}")
        except Exception as e:
            print(f"Error: {e}")


def _repl_execute(code, interpreter):
    """Parse and execute code in the REPL context."""
    tokens = list(tokenize(code))
    parser = Parser(tokens)
    ast_nodes = parser.parse()

    for node in ast_nodes:
        if isinstance(node, FunctionCallNode):
            result = interpreter.execute_function(node)
            if result is not None:
                formatted = format_value(result)
                if formatted is not None:
                    print(formatted)
        else:
            interpreter.interpret(node)


# Main Execution Code
def main():
    global DEBUG

    # Parse --debug flag before filename
    args = sys.argv[1:]
    if '--debug' in args:
        DEBUG = True
        args.remove('--debug')

    # No arguments or --repl flag: start interactive REPL
    if len(args) == 0 or (len(args) == 1 and args[0] == '--repl'):
        repl()
        return

    if len(args) != 1:
        print("Usage: python saurav.py [<filename>.srv] [--debug] [--repl]")
        print()
        print("  <filename>.srv  Run a sauravcode source file")
        print("  --repl          Start interactive REPL (default if no file given)")
        print("  --debug         Enable debug output")
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
    try:
        for node in ast_nodes:
            if isinstance(node, FunctionCallNode):
                result = interpreter.execute_function(node)
            else:
                interpreter.interpret(node)
    except ThrowSignal as e:
        msg = e.message
        if isinstance(msg, float) and msg == int(msg):
            msg = int(msg)
        print(f"Uncaught error: {msg}")
        sys.exit(1)
    
    if result is not None:
        print("\nFinal result:", result)

if __name__ == '__main__':
    main()
