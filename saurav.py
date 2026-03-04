import re
import sys
import os
import math
import random
import time as _time
from datetime import datetime as _datetime, timezone as _timezone

# Debug flag — enabled with --debug command-line argument
DEBUG = False

# Security limits to prevent denial-of-service attacks
MAX_RECURSION_DEPTH = 500      # Maximum nested function call depth
MAX_LOOP_ITERATIONS = 10_000_000  # Maximum iterations per loop
MAX_ALLOC_SIZE = 10_000_000    # Maximum elements in a single allocation (list/string repeat/range)
MAX_EXPONENT = 10_000          # Maximum exponent to prevent memory exhaustion via huge integers

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
    ('ARROW',    r'->'),  # Arrow operator (for lambda expressions)
    ('PIPE',     r'\|>'),  # Pipe operator (must precede any | token)
    ('BAR',      r'\|'),   # Bar (for match case alternatives)
    ('OP',       r'[+\-*/%]'),  # Arithmetic operators (includes modulo)
    ('LPAREN',   r'\('),  # Left parenthesis
    ('RPAREN',   r'\)'),  # Right parenthesis
    ('LBRACKET', r'\['),  # Left bracket
    ('RBRACKET', r'\]'),  # Right bracket
    ('LBRACE',   r'\{'),  # Left brace (for maps)
    ('RBRACE',   r'\}'),  # Right brace (for maps)
    ('COLON',    r':'),   # Colon (for map key-value pairs)
    ('COMMA',    r','),   # Comma separator
    ('DOT',      r'\.'),  # Dot accessor (for enum variants)
    ('KEYWORD',  r'\b(?:function|return|class|int|float|bool|string|if|else if|else|for|in|while|try|catch|throw|print|true|false|and|or|not|list|set|stack|queue|append|len|pop|lambda|import|match|case|enum|break|continue|assert|yield|next)\b'),  # All keywords
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
    line_num = None  # Source line number (optionally set by debugger/tooling)

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

class YieldNode(ASTNode):
    """Yield a value from a generator function."""
    def __init__(self, expression):
        self.expression = expression

    def __repr__(self):
        return f"YieldNode(expression={self.expression})"

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

class ForEachNode(ASTNode):
    """For-each iteration over a collection.
    
    for item in collection
        body...
    
    Iterates over: lists (elements), strings (characters), maps (keys).
    """
    def __init__(self, var, iterable, body):
        self.var = var          # variable name to bind each element
        self.iterable = iterable  # expression that evaluates to a collection
        self.body = body        # list of statements in loop body

    def __repr__(self):
        return f"ForEachNode(var={self.var}, iterable={self.iterable}, body={self.body})"

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

class LambdaNode(ASTNode):
    """Anonymous function expression: lambda x y -> expr.
    
    Creates a callable value that can be passed to higher-order
    functions like map, filter, reduce, each, or stored in variables.
    
    lambda x -> x * 2
    lambda x y -> x + y
    map (lambda x -> x * 2) [1, 2, 3]
    """
    def __init__(self, params, body_expr):
        self.params = params       # list of parameter names
        self.body_expr = body_expr  # single expression (not a block)

    def __repr__(self):
        return f"LambdaNode(params={self.params}, body_expr={self.body_expr})"

class PipeNode(ASTNode):
    """Pipe operator: value |> function.
    
    Evaluates value, then passes it as the last argument to function.
    Enables functional composition: x |> f |> g is equivalent to g(f(x)).
    """
    def __init__(self, value, function):
        self.value = value       # Left side: expression to pipe
        self.function = function # Right side: function/lambda to apply
    
    def __repr__(self):
        return f"PipeNode(value={self.value}, function={self.function})"

class ImportNode(ASTNode):
    """Import another .srv module: import "math_utils"
    
    Loads and executes a .srv file, making all its top-level
    functions and variables available in the current scope.
    The .srv extension is added automatically if not present.
    Circular imports are detected and prevented.
    """
    def __init__(self, module_path):
        self.module_path = module_path  # string path to the module

    def __repr__(self):
        return f"ImportNode(module_path={self.module_path!r})"

class ListComprehensionNode(ASTNode):
    """List comprehension: [expr for var in iterable] or
    [expr for var in iterable if condition]

    Creates a new list by evaluating expr for each element of
    iterable, optionally filtering with a condition.
    """
    def __init__(self, expr, var, iterable, condition=None):
        self.expr = expr       # expression to evaluate per element
        self.var = var         # loop variable name (string)
        self.iterable = iterable  # expression that produces the collection
        self.condition = condition  # optional filter expression (or None)

    def __repr__(self):
        cond = f", condition={self.condition}" if self.condition else ""
        return f"ListComprehensionNode(expr={self.expr}, var={self.var}, iterable={self.iterable}{cond})"

class MatchNode(ASTNode):
    """Pattern matching: match expression with case clauses."""
    def __init__(self, expression, cases):
        self.expression = expression
        self.cases = cases

    def __repr__(self):
        return f"MatchNode(expression={self.expression}, cases={self.cases})"

class CaseNode(ASTNode):
    """A single case in a match expression."""
    def __init__(self, patterns, guard, body, is_wildcard=False, binding_name=None):
        self.patterns = patterns
        self.guard = guard
        self.body = body
        self.is_wildcard = is_wildcard
        self.binding_name = binding_name

    def __repr__(self):
        return f"CaseNode(patterns={self.patterns}, guard={self.guard}, is_wildcard={self.is_wildcard}, binding_name={self.binding_name})"

class EnumNode(ASTNode):
    """Enum type definition: enum Color\n    RED\n    GREEN\n    BLUE
    
    Defines a named enumeration. Each variant gets an auto-incrementing
    integer value starting from 0. Access variants via dot notation:
    Color.RED (== 0), Color.GREEN (== 1), etc.
    """
    def __init__(self, name, variants):
        self.name = name
        self.variants = variants

    def __repr__(self):
        return f"EnumNode(name={self.name}, variants={self.variants})"

class EnumAccessNode(ASTNode):
    """Access an enum variant: Color.RED"""
    def __init__(self, enum_name, variant_name):
        self.enum_name = enum_name
        self.variant_name = variant_name

    def __repr__(self):
        return f"EnumAccessNode(enum_name={self.enum_name}, variant_name={self.variant_name})"

class SliceNode(ASTNode):
    """Slice access: obj[start:end], obj[start:], obj[:end], obj[:]"""
    def __init__(self, obj, start, end):
        self.obj = obj
        self.start = start
        self.end = end
    def __repr__(self):
        return f"SliceNode(obj={self.obj}, start={self.start}, end={self.end})"

class AssertNode(ASTNode):
    """Assert that a condition is true, with optional error message."""
    def __init__(self, condition, message=None):
        self.condition = condition
        self.message = message

    def __repr__(self):
        return f"AssertNode(condition={self.condition}, message={self.message})"

class BreakNode(ASTNode):
    """Break out of the nearest enclosing loop."""
    def __repr__(self):
        return "BreakNode()"

class ContinueNode(ASTNode):
    """Skip to the next iteration of the nearest enclosing loop."""
    def __repr__(self):
        return "ContinueNode()"


class TernaryNode(ASTNode):
    """Ternary conditional expression: true_expr if condition else false_expr"""
    def __init__(self, condition, true_expr, false_expr):
        self.condition = condition
        self.true_expr = true_expr
        self.false_expr = false_expr
    def __repr__(self):
        return f"TernaryNode({self.true_expr} if {self.condition} else {self.false_expr})"

# Parser Class with Block Parsing and Full Control Flow
class Parser:
    # Builtin function names that accept arguments.
    # When one of these is followed by '[', the '[' starts a list literal
    # argument rather than an index operation.  (Fixes #18)
    BUILTIN_FUNCTIONS = frozenset({
        'upper', 'lower', 'trim', 'replace', 'split', 'join',
        'contains', 'starts_with', 'ends_with', 'substring', 'index_of',
        'char_at', 'abs', 'round', 'floor', 'ceil', 'sqrt', 'power',
        'type_of', 'to_string', 'to_number', 'input', 'range', 'reverse',
        'sort', 'keys', 'values', 'has_key', 'map', 'filter', 'reduce',
        'each', 'random', 'random_int', 'random_choice', 'random_shuffle',
        'read_file', 'write_file', 'append_file', 'file_exists', 'read_lines',
        'now', 'timestamp', 'date_format', 'date_part', 'sleep',
        'date_add', 'date_diff', 'date_compare', 'date_range',
        'pi', 'euler', 'sin', 'cos', 'tan', 'log', 'log10', 'min', 'max',
        'zip', 'enumerate', 'flatten', 'unique', 'count', 'sum', 'any', 'all',
        'slice', 'chunk', 'find', 'find_index',
        'regex_match', 'regex_find', 'regex_find_all', 'regex_replace', 'regex_split',
        'json_parse', 'json_stringify', 'json_pretty',
        'pad_left', 'pad_right', 'repeat', 'char_code', 'from_char_code',
        'md5', 'sha256', 'sha1', 'base64_encode', 'base64_decode',
        'hex_encode', 'hex_decode', 'crc32', 'url_encode', 'url_decode',
        'mean', 'median', 'stdev', 'variance', 'mode', 'percentile',
        'clamp', 'lerp', 'remap',
    })

    # Builtins that take zero arguments — auto-called when used standalone
    ZERO_ARG_BUILTINS = frozenset({'now', 'timestamp', 'pi', 'euler'})

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
        elif token_type == 'KEYWORD' and value == 'import':
            return self.parse_import()
        elif token_type == 'KEYWORD' and value == 'return':
            self.expect('KEYWORD', 'return')
            expression = self.parse_full_expression()
            return ReturnNode(expression)
        elif token_type == 'KEYWORD' and value == 'yield':
            self.expect('KEYWORD', 'yield')
            expression = self.parse_full_expression()
            return YieldNode(expression)
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
        elif token_type == 'KEYWORD' and value == 'match':
            return self.parse_match()
        elif token_type == 'KEYWORD' and value == 'enum':
            return self.parse_enum()
        elif token_type == 'KEYWORD' and value == 'break':
            self.advance()
            return BreakNode()
        elif token_type == 'KEYWORD' and value == 'continue':
            self.advance()
            return ContinueNode()
        elif token_type == 'KEYWORD' and value == 'assert':
            return self.parse_assert()
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

    def parse_lambda(self):
        """Parse a lambda expression: lambda param1 param2 ... -> expr.
        
        Lambda syntax:
            lambda x -> x * 2
            lambda x y -> x + y
            lambda -> 42  (no params, returns constant)
        
        Can be used anywhere an expression is expected:
            let double = lambda x -> x * 2
            map (lambda x -> x * 2) [1, 2, 3]
            let result = (lambda x y -> x + y) 3 4  -- not yet supported for direct call
        """
        debug("Parsing lambda expression...")
        self.expect('KEYWORD', 'lambda')
        params = []

        # Collect parameter names until we hit '->'
        while self.peek()[0] == 'IDENT':
            params.append(self.expect('IDENT')[1])
            if self.peek()[0] == 'ARROW':
                break

        # Expect the arrow
        self.expect('ARROW')

        # Parse the body expression (use parse_logical_or so |> is not consumed
        # inside lambda bodies — this allows pipes to chain through lambdas:
        # 5 |> lambda x -> x + 1 |> lambda y -> y * 2  parses as (5 |> λ) |> λ2
        body_expr = self.parse_logical_or()

        lambda_node = LambdaNode(params, body_expr)
        debug(f"Created {lambda_node}\n")
        return lambda_node

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

    def parse_assert(self):
        """Parse assert statement: assert condition [message]
        
        Examples:
            assert x == 5
            assert len(items) > 0 "list must not be empty"
        """
        debug("Parsing assert statement...")
        self.expect('KEYWORD', 'assert')
        condition = self.parse_full_expression()
        # Check for optional string message
        message = None
        if self.pos < len(self.tokens):
            next_tok = self.peek()
            if next_tok[0] == 'STRING':
                message = StringNode(self.advance()[1][1:-1])
            elif next_tok[0] == 'FSTRING':
                message = self.parse_fstring(self.advance()[1])
        return AssertNode(condition, message)

    def parse_match(self):
        """Parse match/case statement:
        match expression
            case pattern1
                body1
            case pattern2 | pattern3
                body2
            case x if x > 10
                body3
            case _
                default_body
        """
        debug("Parsing match statement...")
        self.expect('KEYWORD', 'match')
        expression = self.parse_full_expression()
        self.expect('NEWLINE')
        self.expect('INDENT')

        cases = []
        while self.peek()[0] == 'KEYWORD' and self.peek()[1] == 'case':
            self.expect('KEYWORD', 'case')
            # Parse first pattern
            is_wildcard = False
            binding_name = None
            patterns = []

            pk = self.peek()
            if pk[0] == 'IDENT' and pk[1] == '_':
                # Wildcard
                self.advance()
                is_wildcard = True
            elif pk[0] == 'IDENT':
                # Could be variable binding - check if followed by 'if', NEWLINE, or '|'
                name = pk[1]
                next_pk = self.peek_ahead(1) if hasattr(self, 'peek_ahead') else None
                # We need to determine: is this a binding or a literal?
                # Rule: true/false are bool keywords, numbers/strings are literals, 
                # other identifiers are bindings
                # But identifiers are IDENT tokens, true/false are KEYWORD tokens
                # So any IDENT here is a binding
                self.advance()
                binding_name = name
                patterns.append(IdentifierNode(name))
            else:
                patterns.append(self.parse_atom())

            # Parse additional patterns with |
            if not is_wildcard and not binding_name:
                while self.peek()[0] == 'BAR':
                    self.advance()  # consume |
                    patterns.append(self.parse_atom())

            # Parse optional guard: if condition
            guard = None
            if not is_wildcard and self.peek()[0] == 'KEYWORD' and self.peek()[1] == 'if':
                self.advance()  # consume 'if'
                guard = self.parse_full_expression()

            self.expect('NEWLINE')
            self.expect('INDENT')
            body = self.parse_block()
            self.expect('DEDENT')

            cases.append(CaseNode(patterns, guard, body, is_wildcard, binding_name))

        self.expect('DEDENT')
        return MatchNode(expression, cases)

    def parse_enum(self):
        """Parse enum definition:
        enum Color
            RED
            GREEN
            BLUE
        """
        debug("Parsing enum definition...")
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
        debug(f"Parsed enum: {name} with variants {variants}")
        return EnumNode(name, variants)

    def parse_import(self):
        """Parse import statement: import "module_name" """
        debug("Parsing import statement...")
        self.expect('KEYWORD', 'import')
        # Accept a string literal as the module path
        token_type, value, *_ = self.peek()
        if token_type == 'STRING':
            self.advance()
            # Strip quotes
            module_path = value[1:-1]
        elif token_type == 'IDENT':
            # Allow: import math_utils (bare identifier)
            self.advance()
            module_path = value
        else:
            raise SyntaxError("import expects a module name (string or identifier)")
        return ImportNode(module_path)

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
            if pk[0] == 'KEYWORD' and pk[1] in ('true', 'false', 'not', 'len', 'lambda'):
                arguments.append(self.parse_atom())
            elif pk[0] == 'KEYWORD':
                break  # Don't consume control flow keywords as arguments
            else:
                arguments.append(self.parse_atom())
        function_call_node = FunctionCallNode(name, arguments)
        debug(f"Created {function_call_node}\n")
        return function_call_node

    # Expression parsing with proper precedence:
    # full_expression -> pipe
    # pipe -> logical_or ('|>' logical_or)*
    # logical_or -> logical_and ('or' logical_and)*
    # logical_and -> comparison ('and' comparison)*
    # comparison -> expression (comp_op expression)?
    # expression -> term (('+' | '-') term)*
    # term_mul -> unary (('*' | '/' | '%') unary)*
    # unary -> 'not' unary | '-' unary | atom
    # atom -> NUMBER | STRING | BOOL | IDENT | '(' full_expression ')' | list | func_call

    def parse_full_expression(self):
        return self.parse_pipe()

    def parse_pipe(self):
        """Parse pipe expressions: expr (|> expr)*"""
        left = self.parse_ternary()
        while self.peek()[0] == 'PIPE':
            self.advance()
            right = self.parse_ternary()
            left = PipeNode(left, right)
        return left

    def parse_ternary(self):
        """Parse ternary conditional: true_expr if condition else false_expr"""
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
        """Parse atom followed by optional [index] or [start:end] slice chains."""
        node = self.parse_atom()
        return self._parse_postfix_chain(node)

    def _parse_postfix_chain(self, node):
        """Parse [index] or [start:end] chains on an already-parsed node."""
        while self.peek()[0] == 'LBRACKET':
            self.expect('LBRACKET')
            if self.peek()[0] == 'COLON':
                self.advance()
                end_expr = None
                if self.peek()[0] != 'RBRACKET':
                    end_expr = self.parse_full_expression()
                self.expect('RBRACKET')
                node = SliceNode(node, None, end_expr)
            else:
                start_expr = self.parse_full_expression()
                if self.peek()[0] == 'COLON':
                    self.advance()
                    end_expr = None
                    if self.peek()[0] != 'RBRACKET':
                        end_expr = self.parse_full_expression()
                    self.expect('RBRACKET')
                    node = SliceNode(node, start_expr, end_expr)
                else:
                    self.expect('RBRACKET')
                    node = IndexNode(node, start_expr)
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
        elif token_type == 'KEYWORD' and value == 'lambda':
            return self.parse_lambda()
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
            # Dot notation for enum access: EnumName.VARIANT
            if pk[0] == 'DOT':
                self.advance()  # consume DOT
                variant = self.expect('IDENT')[1]
                return EnumAccessNode(value, variant)
            # Don't treat as function call if next is [ (indexing handled in parse_postfix)
            # UNLESS the identifier is a known builtin function — then [ starts
            # a list argument, not an index operation.  (Fixes #18)
            if pk[0] == 'LBRACKET' and value not in self.BUILTIN_FUNCTIONS:
                return IdentifierNode(value)
            if pk[0] == 'LBRACKET' and value in self.BUILTIN_FUNCTIONS:
                func_call = self.parse_function_call(value)
                return func_call
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
                # Zero-argument builtin function call (only for builtins that take no args)
                if value in self.ZERO_ARG_BUILTINS:
                    return FunctionCallNode(value, [])
                ident_node = IdentifierNode(value)
                debug(f"parse_atom returning IdentifierNode: {ident_node}")
                return ident_node
        else:
            raise SyntaxError(f'Unexpected token: {value}')

    def parse_list_literal(self):
        self.expect('LBRACKET')
        # Empty list
        if self.peek()[0] == 'RBRACKET':
            self.expect('RBRACKET')
            return ListNode([])
        # Parse first expression
        first = self.parse_full_expression()
        # Check for list comprehension: [expr for var in iterable]
        if self.peek()[0] == 'KEYWORD' and self.peek()[1] == 'for':
            return self._parse_list_comprehension(first)
        # Regular list literal
        elements = [first]
        while self.peek()[0] == 'COMMA':
            self.advance()
            if self.peek()[0] == 'RBRACKET':
                break  # trailing comma
            elements.append(self.parse_full_expression())
        self.expect('RBRACKET')
        return ListNode(elements)

    def _parse_list_comprehension(self, expr):
        """Parse the rest of a list comprehension after the initial expression.
        
        Syntax: [expr for var in iterable]
                [expr for var in iterable if condition]
        """
        self.expect('KEYWORD', 'for')
        var = self.expect('IDENT')[1]
        self.expect('KEYWORD', 'in')
        # Use parse_logical_or instead of parse_full_expression so that
        # `if` is not consumed as a ternary operator — it belongs to the
        # comprehension filter clause.
        iterable = self.parse_logical_or()
        condition = None
        if self.peek()[0] == 'KEYWORD' and self.peek()[1] == 'if':
            self.advance()
            condition = self.parse_logical_or()
        self.expect('RBRACKET')
        return ListComprehensionNode(expr, var, iterable, condition)

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

class BreakSignal(Exception):
    """Signal to break out of the nearest enclosing loop."""
    pass

class ContinueSignal(Exception):
    """Signal to skip to the next iteration of the nearest enclosing loop."""
    pass

class YieldSignal(Exception):
    """Signal to yield a value from a generator function."""
    def __init__(self, value):
        self.value = value

class GeneratorValue:
    """Runtime representation of a generator — a lazy iterable.

    Created when a function containing ``yield`` is called.
    Internally runs the function body step-by-step: each call to
    ``__next__`` resumes execution until the next ``yield`` or the
    function body ends.

    Implementation uses a background thread that pauses at every
    ``yield`` via threading events, so the interpreter's existing
    tree-walking execution model works unchanged.
    """
    def __init__(self, interpreter, func_node, args):
        import threading
        self.interpreter = interpreter
        self.func_node = func_node
        self.args = args
        self._values = []       # buffered yielded values
        self._done = False
        self._error = None
        self._started = False
        # Synchronization primitives
        self._yield_ready = threading.Event()
        self._resume = threading.Event()
        self._thread = None

    def _run(self):
        """Run the generator body in a background thread."""
        import threading
        try:
            # Create a fresh interpreter scope snapshot
            saved_vars = self.interpreter.variables.copy()
            saved_funcs = self.interpreter.functions.copy()
            try:
                # Set up parameters
                for param, arg_val in zip(self.func_node.params, self.args):
                    self.interpreter.variables[param] = arg_val

                # Inject closure scope
                if hasattr(self.func_node, 'closure_scope') and self.func_node.closure_scope:
                    for cname, cval in self.func_node.closure_scope.items():
                        if cname not in self.interpreter.variables:
                            self.interpreter.variables[cname] = cval

                for stmt in self.func_node.body:
                    self.interpreter.interpret(stmt)
            except YieldSignal as ys:
                # Should not happen here — handled inside interpret
                pass
            except ReturnSignal:
                pass
            except Exception as e:
                self._error = e
        finally:
            self.interpreter.variables = saved_vars
            self.interpreter.functions = saved_funcs
            self._done = True
            self._yield_ready.set()

    def _ensure_started(self):
        if not self._started:
            self._started = True
            self._collect_all()

    def _collect_all(self):
        """Eagerly collect all yielded values by executing the function body."""
        saved_vars = self.interpreter.variables.copy()
        saved_funcs = self.interpreter.functions.copy()
        try:
            for param, arg_val in zip(self.func_node.params, self.args):
                self.interpreter.variables[param] = arg_val

            if hasattr(self.func_node, 'closure_scope') and self.func_node.closure_scope:
                for cname, cval in self.func_node.closure_scope.items():
                    if cname not in self.interpreter.variables:
                        self.interpreter.variables[cname] = cval

            self._execute_collecting(self.func_node.body)
        except ReturnSignal:
            pass
        except StopIteration:
            pass
        finally:
            self.interpreter.variables = saved_vars
            self.interpreter.functions = saved_funcs
            self._done = True

    def _execute_collecting(self, stmts):
        """Execute statements, collecting yield values instead of raising.
        
        Temporarily patches the interpreter's yield handler to collect values
        instead of raising YieldSignal, so yield works correctly inside loops.
        """
        interp = self.interpreter
        original_interp_yield = interp._interp_yield
        collected = self._values

        def _collecting_yield(ast):
            result = interp.evaluate(ast.expression)
            collected.append(result)

        # Temporarily replace yield handler so loops don't break on yield
        interp._interp_yield = _collecting_yield
        interp._interpret_dispatch[YieldNode] = _collecting_yield
        try:
            for stmt in stmts:
                interp.interpret(stmt)
        finally:
            interp._interp_yield = original_interp_yield
            interp._interpret_dispatch[YieldNode] = original_interp_yield

    def to_list(self):
        """Convert generator to a list of all yielded values."""
        self._ensure_started()
        return list(self._values)

    def __repr__(self):
        return f"<generator {self.func_node.name}>"

    def __str__(self):
        return self.__repr__()

class LambdaValue:
    """Runtime representation of a lambda expression.
    
    Captures the parameter list, body expression, and the defining
    scope (closure) so variables from the enclosing environment are
    accessible inside the lambda body.
    """
    def __init__(self, params, body_expr, closure):
        self.params = params       # parameter names
        self.body_expr = body_expr  # AST expression node
        self.closure = closure     # captured variable scope (dict copy)

    def __repr__(self):
        params_str = " ".join(self.params) if self.params else ""
        return f"<lambda {params_str} -> ...>"

    def __str__(self):
        return self.__repr__()

class Interpreter:
    def __init__(self):
        self.functions = {}  # Store function definitions
        self.variables = {}  # Store variable values
        self.enums = {}      # Store enum definitions: {name: {VARIANT: value, ...}}
        self._call_depth = 0  # Track recursion depth for DoS protection
        self._imported_modules = set()  # Track imported modules (circular import prevention)
        self._source_dir = None  # Directory of the currently executing file (for relative imports)
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
            YieldNode:              self._interp_yield,
            PrintNode:              self._interp_print,
            FunctionCallNode:       self._interp_function_call,
            AssignmentNode:         self._interp_assignment,
            IndexedAssignmentNode:  self._interp_indexed_assignment,
            IfNode:                 self.execute_if,
            WhileNode:              self.execute_while,
            ForNode:                self.execute_for,
            ForEachNode:            self.execute_for_each,
            TryCatchNode:           self.execute_try_catch,
            ThrowNode:              self.execute_throw,
            AppendNode:             self._interp_append,
            ImportNode:             self.execute_import,
            MatchNode:              self.execute_match,
            EnumNode:               self._interp_enum,
            BreakNode:              self._interp_break,
            ContinueNode:           self._interp_continue,
            AssertNode:             self._interp_assert,
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
            ListComprehensionNode: self._eval_list_comprehension,
            IndexNode:        self._eval_index,
            SliceNode:        self._eval_slice,
            LenNode:          self._eval_len,
            MapNode:           self._eval_map,
            FStringNode:      self._eval_fstring,
            LambdaNode:       self._eval_lambda,
            PipeNode:         self._eval_pipe,
            EnumAccessNode:   self._eval_enum_access,
            TernaryNode:      self._eval_ternary,
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
            'round':       self._builtin_round,
            # abs, floor, ceil, sqrt are registered below via _register_math_builtins()
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
            # --- Higher-order functions ---
            'map':         self._builtin_map,
            'filter':      self._builtin_filter,
            'reduce':      self._builtin_reduce,
            'each':        self._builtin_each,
            # --- Random functions ---
            'random':         self._builtin_random,
            'random_int':     self._builtin_random_int,
            'random_choice':  self._builtin_random_choice,
            'random_shuffle': self._builtin_random_shuffle,
            # --- File I/O functions ---
            'read_file':      self._builtin_read_file,
            'write_file':     self._builtin_write_file,
            'append_file':    self._builtin_append_file,
            'file_exists':    self._builtin_file_exists,
            'read_lines':     self._builtin_read_lines,
            # --- Date/Time functions ---
            'now':            self._builtin_now,
            'timestamp':      self._builtin_timestamp,
            'date_format':    self._builtin_date_format,
            'date_part':      self._builtin_date_part,
            'date_add':       self._builtin_date_add,
            'date_diff':      self._builtin_date_diff,
            'date_compare':   self._builtin_date_compare,
            'date_range':     self._builtin_date_range,
            'sleep':          self._builtin_sleep,
            # --- Math constants & trig functions ---
            'pi':             self._builtin_pi,
            'euler':          self._builtin_euler,
            # sin, cos, tan, log10 are registered below via _register_math_builtins()
            'log':            self._builtin_log,
            'min':            self._builtin_min,
            'max':            self._builtin_max,
            # --- Collection functions ---
            'zip':            self._builtin_zip,
            'enumerate':      self._builtin_enumerate,
            'flatten':        self._builtin_flatten,
            'unique':         self._builtin_unique,
            'count':          self._builtin_count,
            'sum':            self._builtin_sum,
            'any':            self._builtin_any,
            'all':            self._builtin_all,
            'slice':          self._builtin_slice,
            'chunk':          self._builtin_chunk,
            'find':           self._builtin_find,
            'find_index':     self._builtin_find_index,
            # --- String padding & char functions ---
            'pad_left':       self._builtin_pad_left,
            'pad_right':      self._builtin_pad_right,
            'repeat':         self._builtin_repeat,
            'char_code':      self._builtin_char_code,
            'from_char_code': self._builtin_from_char_code,
            # --- Regex functions ---
            'regex_match':    self._builtin_regex_match,
            'regex_find':     self._builtin_regex_find,
            'regex_find_all': self._builtin_regex_find_all,
            'regex_replace':  self._builtin_regex_replace,
            'regex_split':    self._builtin_regex_split,
            # --- JSON functions ---
            'json_parse':     self._builtin_json_parse,
            'json_stringify': self._builtin_json_stringify,
            'json_pretty':    self._builtin_json_pretty,
            # --- Hash & encoding functions ---
            'md5':            self._builtin_md5,
            'sha256':         self._builtin_sha256,
            'sha1':           self._builtin_sha1,
            'base64_encode':  self._builtin_base64_encode,
            'base64_decode':  self._builtin_base64_decode,
            'hex_encode':     self._builtin_hex_encode,
            'hex_decode':     self._builtin_hex_decode,
            'crc32':          self._builtin_crc32,
            'url_encode':     self._builtin_url_encode,
            'url_decode':     self._builtin_url_decode,
            # --- Statistics & math functions ---
            'mean':           self._builtin_mean,
            'median':         self._builtin_median,
            'stdev':          self._builtin_stdev,
            'variance':       self._builtin_variance,
            'mode':           self._builtin_mode,
            'percentile':     self._builtin_percentile,
            'clamp':          self._builtin_clamp,
            'lerp':           self._builtin_lerp,
            'remap':          self._builtin_remap,
            # --- Generator functions ---
            'collect':        self._builtin_collect,
            'is_generator':   self._builtin_is_generator,
        }
        self._register_math_builtins()

    # ── Data-driven math builtins ────────────────────────

    @staticmethod
    def _make_math_builtin(name, fn, cast_float=True):
        """Create a single-arg math builtin from a callable."""
        def handler(self, args):
            self._expect_args(name, args, 1)
            result = fn(args[0])
            return float(result) if cast_float else result
        return handler

    def _register_math_builtins(self):
        """Register simple single-arg math builtins via a table.

        Each entry maps a builtin name to its underlying Python callable.
        This eliminates boilerplate for functions that are just thin
        wrappers around ``math.*`` or Python builtins.
        """
        _MATH_TABLE = {
            'abs':   abs,
            'floor': math.floor,
            'ceil':  math.ceil,
            'sin':   math.sin,
            'cos':   math.cos,
            'tan':   math.tan,
        }

        # Builtins with special validation
        def _safe_sqrt(x):
            if x < 0:
                raise RuntimeError("sqrt of negative number")
            return math.sqrt(x)

        def _safe_log10(x):
            if x <= 0:
                raise RuntimeError("log10: argument must be positive")
            return math.log10(x)

        _MATH_TABLE['sqrt'] = _safe_sqrt
        _MATH_TABLE['log10'] = _safe_log10

        # power takes 2 args — register manually
        def _power(self_inner, args):
            self_inner._expect_args('power', args, 2)
            base, exp = args[0], args[1]
            if isinstance(exp, (int, float)) and abs(exp) > MAX_EXPONENT:
                raise RuntimeError(
                    f"Exponent {exp} exceeds maximum of {MAX_EXPONENT:,} "
                    f"(prevent memory exhaustion)")
            return float(base ** exp)
        self.builtins['power'] = lambda args: _power(self, args)

        for name, fn in _MATH_TABLE.items():
            handler = Interpreter._make_math_builtin(name, fn)
            # Bind to this instance
            self.builtins[name] = lambda args, h=handler: h(self, args)

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
    #
    # Simple single-arg math wrappers are registered via
    # _register_math_builtins() below; only builtins needing
    # custom logic (round, sqrt, power, log, min, max) are
    # kept as explicit methods.

    def _builtin_round(self, args):
        if len(args) == 1:
            return float(round(args[0]))
        elif len(args) == 2:
            return float(round(args[0], int(args[1])))
        else:
            raise RuntimeError("round expects 1 or 2 arguments: round value [places]")

    # sqrt, power are registered via _register_math_builtins()

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
        if isinstance(val, LambdaValue):
            return "lambda"
        if isinstance(val, GeneratorValue):
            return "generator"
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
        if isinstance(val, LambdaValue):
            return str(val)
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
            count = int(args[0])
        elif len(args) == 2:
            count = int(args[1]) - int(args[0])
        elif len(args) == 3:
            step = int(args[2])
            if step == 0:
                raise RuntimeError("range step cannot be zero")
            count = max(0, (int(args[1]) - int(args[0]) + (step - (1 if step > 0 else -1))) // step)
        else:
            raise RuntimeError("range expects 1-3 arguments: range end | range start end | range start end step")

        if count > MAX_ALLOC_SIZE:
            raise RuntimeError(
                f"range would create {count:,} elements, "
                f"exceeding limit of {MAX_ALLOC_SIZE:,}")

        if len(args) == 1:
            return [float(i) for i in range(int(args[0]))]
        elif len(args) == 2:
            return [float(i) for i in range(int(args[0]), int(args[1]))]
        else:
            return [float(i) for i in range(int(args[0]), int(args[1]), int(args[2]))]

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
        try:
            return sorted(val)
        except TypeError:
            raise RuntimeError("sort: cannot compare elements of different types")

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

    # --- Higher-order function built-ins ---

    def _call_function_with_args(self, func_ref, evaluated_args):
        """Call a user-defined function, built-in, or lambda with pre-evaluated args.
        
        Used by higher-order functions (map, filter, reduce) to invoke
        callbacks with already-evaluated Python values.
        
        func_ref can be:
        - A string (function name to look up)
        - A LambdaValue (anonymous function)
        """
        # Lambda value — call directly
        if isinstance(func_ref, LambdaValue):
            return self._call_lambda(func_ref, evaluated_args)
        
        # Named function
        func_name = func_ref
        func = self.functions.get(func_name)
        if func:
            self._call_depth += 1
            if self._call_depth > MAX_RECURSION_DEPTH:
                self._call_depth -= 1
                raise RuntimeError(
                    f"Maximum recursion depth ({MAX_RECURSION_DEPTH}) exceeded "
                    f"in function '{func_name}'"
                )
            result = None
            with self._scoped_env():
                for param, val in zip(func.params, evaluated_args):
                    self.variables[param] = val
                try:
                    for stmt in func.body:
                        self.interpret(stmt)
                except ReturnSignal as ret:
                    result = ret.value
                finally:
                    self._call_depth -= 1
            return result
        if func_name in self.builtins:
            return self.builtins[func_name](evaluated_args)
        raise RuntimeError(f"Function '{func_name}' is not defined.")

    def _builtin_map(self, args):
        """map func list → apply function to each element, return new list.
        
        func can be a function name (string) or a lambda expression.
        Example: map double [1, 2, 3] → [2, 4, 6]
        Example: map (lambda x -> x * 2) [1, 2, 3] → [2, 4, 6]
        """
        self._expect_args('map', args, 2)
        func_ref, lst = args
        if not isinstance(func_ref, (str, LambdaValue)):
            raise RuntimeError("map expects a function name or lambda as first argument")
        if not isinstance(lst, list):
            raise RuntimeError("map expects a list as second argument")
        return [self._call_function_with_args(func_ref, [item]) for item in lst]

    def _builtin_filter(self, args):
        """filter func list → keep elements where function returns truthy.
        
        func can be a function name (string) or a lambda expression.
        Example: filter is_positive [3, -1, 4, -5, 2] → [3, 4, 2]
        Example: filter (lambda x -> x > 0) [3, -1, 4] → [3, 4]
        """
        self._expect_args('filter', args, 2)
        func_ref, lst = args
        if not isinstance(func_ref, (str, LambdaValue)):
            raise RuntimeError("filter expects a function name or lambda as first argument")
        if not isinstance(lst, list):
            raise RuntimeError("filter expects a list as second argument")
        return [item for item in lst
                if self._is_truthy(self._call_function_with_args(func_ref, [item]))]

    def _builtin_reduce(self, args):
        """reduce func list initial → fold list with binary function.
        
        func can be a function name (string) or a lambda expression.
        Example: reduce add [1, 2, 3, 4] 0 → 10
        Example: reduce (lambda acc x -> acc + x) [1, 2, 3] 0 → 6
        """
        self._expect_args('reduce', args, 3)
        func_ref, lst, init = args
        if not isinstance(func_ref, (str, LambdaValue)):
            raise RuntimeError("reduce expects a function name or lambda as first argument")
        if not isinstance(lst, list):
            raise RuntimeError("reduce expects a list as second argument")
        acc = init
        for item in lst:
            acc = self._call_function_with_args(func_ref, [acc, item])
        return acc

    def _builtin_each(self, args):
        """each func list → apply function to each element for side effects.
        
        func can be a function name (string) or a lambda expression.
        Like map, but discards return values. Returns the list unchanged.
        Example: each print_item [1, 2, 3]
        Example: each (lambda x -> print x) [1, 2, 3]
        """
        self._expect_args('each', args, 2)
        func_ref, lst = args
        if not isinstance(func_ref, (str, LambdaValue)):
            raise RuntimeError("each expects a function name or lambda as first argument")
        if not isinstance(lst, list):
            raise RuntimeError("each expects a list as second argument")
        for item in lst:
            self._call_function_with_args(func_ref, [item])
        return lst

    # --- Random built-ins ---
    def _builtin_random(self, args):
        """random min max → random float between min and max."""
        self._expect_args('random', args, 2)
        lo, hi = args
        if not isinstance(lo, (int, float)) or not isinstance(hi, (int, float)):
            raise RuntimeError("random expects numeric arguments")
        return random.uniform(float(lo), float(hi))

    def _builtin_random_int(self, args):
        """random_int min max → random integer between min and max (inclusive)."""
        self._expect_args('random_int', args, 2)
        lo, hi = args
        if not isinstance(lo, (int, float)) or not isinstance(hi, (int, float)):
            raise RuntimeError("random_int expects numeric arguments")
        return random.randint(int(lo), int(hi))

    def _builtin_random_choice(self, args):
        """random_choice list → pick a random element from a list."""
        self._expect_args('random_choice', args, 1)
        lst = args[0]
        if not isinstance(lst, list) or len(lst) == 0:
            raise RuntimeError("random_choice expects a non-empty list")
        return random.choice(lst)

    def _builtin_random_shuffle(self, args):
        """random_shuffle list → return a new list with elements in random order."""
        self._expect_args('random_shuffle', args, 1)
        lst = args[0]
        if not isinstance(lst, list):
            raise RuntimeError("random_shuffle expects a list argument")
        result = lst[:]
        random.shuffle(result)
        return result

    # --- File I/O built-ins ---
    def _builtin_read_file(self, args):
        """read_file path → return file contents as a string."""
        self._expect_args('read_file', args, 1)
        path = args[0]
        if not isinstance(path, str):
            raise RuntimeError("read_file expects a string path")
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            raise RuntimeError(f"read_file: file not found: {path}")
        except PermissionError:
            raise RuntimeError(f"read_file: permission denied: {path}")
        except OSError as e:
            raise RuntimeError(f"read_file: error reading file: {e}")

    def _builtin_write_file(self, args):
        """write_file path content → write content to file (creates or overwrites)."""
        self._expect_args('write_file', args, 2)
        path = args[0]
        content = args[1]
        if not isinstance(path, str):
            raise RuntimeError("write_file expects a string path as first argument")
        if not isinstance(content, str):
            content = str(content)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        except PermissionError:
            raise RuntimeError(f"write_file: permission denied: {path}")
        except OSError as e:
            raise RuntimeError(f"write_file: error writing file: {e}")

    def _builtin_append_file(self, args):
        """append_file path content → append content to file (creates if missing)."""
        self._expect_args('append_file', args, 2)
        path = args[0]
        content = args[1]
        if not isinstance(path, str):
            raise RuntimeError("append_file expects a string path as first argument")
        if not isinstance(content, str):
            content = str(content)
        try:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(content)
            return True
        except PermissionError:
            raise RuntimeError(f"append_file: permission denied: {path}")
        except OSError as e:
            raise RuntimeError(f"append_file: error appending to file: {e}")

    def _builtin_file_exists(self, args):
        """file_exists path → return true if file exists, false otherwise."""
        self._expect_args('file_exists', args, 1)
        path = args[0]
        if not isinstance(path, str):
            raise RuntimeError("file_exists expects a string path")
        return os.path.isfile(path)

    def _builtin_read_lines(self, args):
        """read_lines path → return file contents as a list of lines."""
        self._expect_args('read_lines', args, 1)
        path = args[0]
        if not isinstance(path, str):
            raise RuntimeError("read_lines expects a string path")
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return [line.rstrip('\n').rstrip('\r') for line in f.readlines()]
        except FileNotFoundError:
            raise RuntimeError(f"read_lines: file not found: {path}")
        except PermissionError:
            raise RuntimeError(f"read_lines: permission denied: {path}")
        except OSError as e:
            raise RuntimeError(f"read_lines: error reading file: {e}")

    # --- Date/Time built-ins ---
    def _builtin_now(self, args):
        """now() → return current date/time as ISO 8601 string."""
        if len(args) != 0:
            raise RuntimeError("now expects 0 arguments")
        return _datetime.now().isoformat()

    def _builtin_timestamp(self, args):
        """timestamp() → return current Unix timestamp as a float."""
        if len(args) != 0:
            raise RuntimeError("timestamp expects 0 arguments")
        return _time.time()

    def _builtin_date_format(self, args):
        """date_format(iso_string, format) → format a date/time string.
        Uses Python strftime codes: %Y, %m, %d, %H, %M, %S, etc."""
        self._expect_args('date_format', args, 2)
        iso_str, fmt = args
        if not isinstance(iso_str, str):
            raise RuntimeError("date_format expects a string as first argument")
        if not isinstance(fmt, str):
            raise RuntimeError("date_format expects a format string as second argument")
        try:
            dt = _datetime.fromisoformat(iso_str)
            return dt.strftime(fmt)
        except ValueError as e:
            raise RuntimeError(f"date_format: invalid date string: {e}")

    def _builtin_date_part(self, args):
        """date_part(iso_string, part) → extract a component from a date/time.
        Parts: year, month, day, hour, minute, second, weekday, weekday_name."""
        self._expect_args('date_part', args, 2)
        iso_str, part = args
        if not isinstance(iso_str, str):
            raise RuntimeError("date_part expects a string as first argument")
        if not isinstance(part, str):
            raise RuntimeError("date_part expects a string part name as second argument")
        try:
            dt = _datetime.fromisoformat(iso_str)
        except ValueError as e:
            raise RuntimeError(f"date_part: invalid date string: {e}")
        part = part.lower()
        parts = {
            'year': dt.year, 'month': dt.month, 'day': dt.day,
            'hour': dt.hour, 'minute': dt.minute, 'second': dt.second,
            'weekday': dt.weekday(),
            'weekday_name': dt.strftime('%A'),
        }
        if part not in parts:
            raise RuntimeError(f"date_part: unknown part '{part}'. Use: {', '.join(parts.keys())}")
        result = parts[part]
        return float(result) if isinstance(result, int) else result

    # --- Date arithmetic built-ins ---

    _DATE_UNITS = {
        'seconds': 'seconds', 'second': 'seconds', 'sec': 'seconds', 's': 'seconds',
        'minutes': 'minutes', 'minute': 'minutes', 'min': 'minutes',
        'hours': 'hours', 'hour': 'hours', 'h': 'hours',
        'days': 'days', 'day': 'days', 'd': 'days',
        'weeks': 'weeks', 'week': 'weeks', 'w': 'weeks',
    }

    def _resolve_date_unit(self, unit):
        """Resolve a unit alias to a canonical timedelta keyword."""
        if not isinstance(unit, str):
            raise RuntimeError("date unit must be a string")
        key = unit.lower().strip()
        if key not in self._DATE_UNITS:
            valid = sorted(set(self._DATE_UNITS.values()))
            raise RuntimeError(
                f"unknown date unit '{unit}'. Use: {', '.join(valid)}")
        return self._DATE_UNITS[key]

    def _parse_iso(self, value, fn_name):
        """Parse an ISO 8601 string into a datetime object."""
        if not isinstance(value, str):
            raise RuntimeError(f"{fn_name} expects a date string")
        try:
            return _datetime.fromisoformat(value)
        except ValueError as e:
            raise RuntimeError(f"{fn_name}: invalid date string: {e}")

    def _builtin_date_add(self, args):
        """date_add(iso_string, amount, unit) -- add/subtract time from a date.
        Returns a new ISO 8601 string.
        Units: seconds, minutes, hours, days, weeks (and abbreviations).
        Use negative amount to subtract."""
        self._expect_args('date_add', args, 3)
        iso_str, amount, unit = args
        dt = self._parse_iso(iso_str, 'date_add')
        if not isinstance(amount, (int, float)):
            raise RuntimeError("date_add expects a numeric amount")
        canon = self._resolve_date_unit(unit)
        from datetime import timedelta as _td
        delta = _td(**{canon: amount})
        return (dt + delta).isoformat()

    def _builtin_date_diff(self, args):
        """date_diff(iso_a, iso_b, unit) -- difference (a - b) in given unit.
        Returns a float. Positive if a is after b, negative if before.
        Units: seconds, minutes, hours, days, weeks."""
        self._expect_args('date_diff', args, 3)
        iso_a, iso_b, unit = args
        dt_a = self._parse_iso(iso_a, 'date_diff')
        dt_b = self._parse_iso(iso_b, 'date_diff')
        canon = self._resolve_date_unit(unit)
        delta = dt_a - dt_b
        total_seconds = delta.total_seconds()
        divisors = {
            'seconds': 1.0,
            'minutes': 60.0,
            'hours': 3600.0,
            'days': 86400.0,
            'weeks': 604800.0,
        }
        return total_seconds / divisors[canon]

    def _builtin_date_compare(self, args):
        """date_compare(iso_a, iso_b) -- comparison result.
        Returns -1.0 if a < b, 0.0 if equal, 1.0 if a > b."""
        self._expect_args('date_compare', args, 2)
        iso_a, iso_b = args
        dt_a = self._parse_iso(iso_a, 'date_compare')
        dt_b = self._parse_iso(iso_b, 'date_compare')
        if dt_a < dt_b:
            return -1.0
        elif dt_a > dt_b:
            return 1.0
        else:
            return 0.0

    def _builtin_date_range(self, args):
        """date_range(start, end, step, unit) -- list of ISO strings.
        Generates dates from start to end (exclusive) with given step.
        Units: seconds, minutes, hours, days, weeks."""
        self._expect_args('date_range', args, 4)
        start_iso, end_iso, step_amount, step_unit = args
        dt_start = self._parse_iso(start_iso, 'date_range')
        dt_end = self._parse_iso(end_iso, 'date_range')
        if not isinstance(step_amount, (int, float)):
            raise RuntimeError("date_range expects a numeric step amount")
        if step_amount == 0:
            raise RuntimeError("date_range: step amount cannot be zero")
        canon = self._resolve_date_unit(step_unit)
        from datetime import timedelta as _td
        delta = _td(**{canon: step_amount})
        if step_amount > 0 and dt_start >= dt_end:
            return []
        if step_amount < 0 and dt_start <= dt_end:
            return []
        result = []
        current = dt_start
        max_items = 10000
        if step_amount > 0:
            while current < dt_end and len(result) < max_items:
                result.append(current.isoformat())
                current = current + delta
        else:
            while current > dt_end and len(result) < max_items:
                result.append(current.isoformat())
                current = current + delta
        if len(result) >= max_items:
            raise RuntimeError("date_range: too many items (max 10000)")
        return result

    def _builtin_sleep(self, args):
        """sleep(seconds) → pause execution for the given number of seconds."""
        self._expect_args('sleep', args, 1)
        seconds = args[0]
        if not isinstance(seconds, (int, float)):
            raise RuntimeError("sleep expects a numeric argument")
        if seconds < 0:
            raise RuntimeError("sleep: seconds must be non-negative")
        if seconds > 60:
            raise RuntimeError("sleep: maximum sleep is 60 seconds")
        _time.sleep(seconds)
        return 0.0

    # --- Math constants ---
    def _builtin_pi(self, args):
        """pi() → return the mathematical constant π (3.14159...)."""
        if len(args) != 0:
            raise RuntimeError("pi expects 0 arguments")
        return math.pi

    def _builtin_euler(self, args):
        """euler() → return Euler's number e (2.71828...)."""
        if len(args) != 0:
            raise RuntimeError("euler expects 0 arguments")
        return math.e

    # sin, cos, tan, log10 are registered via _register_math_builtins()

    def _builtin_log(self, args):
        """log(value) → natural logarithm (base e). log(value, base) → log with custom base."""
        if len(args) == 1:
            if args[0] <= 0:
                raise RuntimeError("log: argument must be positive")
            return math.log(args[0])
        elif len(args) == 2:
            if args[0] <= 0:
                raise RuntimeError("log: argument must be positive")
            if args[1] <= 0 or args[1] == 1:
                raise RuntimeError("log: base must be positive and not 1")
            return math.log(args[0], args[1])
        else:
            raise RuntimeError("log expects 1 or 2 arguments: log value [base]")

    # log10 is registered via _register_math_builtins()

    def _builtin_min(self, args):
        """min(a, b) → return the smaller value. min(list) → return the smallest element."""
        if len(args) == 1:
            lst = args[0]
            if not isinstance(lst, list) or len(lst) == 0:
                raise RuntimeError("min expects a non-empty list when called with 1 argument")
            try:
                return min(lst)
            except TypeError:
                raise RuntimeError("min: cannot compare elements of different types")
        elif len(args) == 2:
            try:
                return min(args[0], args[1])
            except TypeError:
                raise RuntimeError("min: cannot compare values of different types")
        else:
            raise RuntimeError("min expects 1 or 2 arguments: min list | min a b")

    def _builtin_max(self, args):
        """max(a, b) → return the larger value. max(list) → return the largest element."""
        if len(args) == 1:
            lst = args[0]
            if not isinstance(lst, list) or len(lst) == 0:
                raise RuntimeError("max expects a non-empty list when called with 1 argument")
            try:
                return max(lst)
            except TypeError:
                raise RuntimeError("max: cannot compare elements of different types")
        elif len(args) == 2:
            try:
                return max(args[0], args[1])
            except TypeError:
                raise RuntimeError("max: cannot compare values of different types")
        else:
            raise RuntimeError("max expects 1 or 2 arguments: max list | max a b")

    # --- Collection built-ins ---

    def _builtin_zip(self, args):
        """zip(list1, list2, ...) -> list of lists, pairing elements by index."""
        if len(args) < 2:
            raise RuntimeError("zip expects at least 2 list arguments")
        for i, a in enumerate(args):
            if not isinstance(a, list):
                raise RuntimeError(f"zip argument {i+1} must be a list")
        return [list(t) for t in zip(*args)]

    def _builtin_enumerate(self, args):
        """enumerate(list) -> list of [index, value] pairs."""
        if len(args) < 1 or len(args) > 2:
            raise RuntimeError("enumerate expects 1-2 arguments: enumerate list [start]")
        lst = args[0]
        if not isinstance(lst, list):
            raise RuntimeError("enumerate expects a list argument")
        start = 0
        if len(args) == 2:
            start = int(args[1])
        return [[i + start, v] for i, v in enumerate(lst)]

    def _builtin_flatten(self, args):
        """flatten(list) -> flatten nested lists one level deep."""
        self._expect_args('flatten', args, 1)
        lst = args[0]
        if not isinstance(lst, list):
            raise RuntimeError("flatten expects a list argument")
        result = []
        for item in lst:
            if isinstance(item, list):
                result.extend(item)
            else:
                result.append(item)
        return result

    def _builtin_unique(self, args):
        """unique(list) -> list with duplicates removed, preserving order."""
        self._expect_args('unique', args, 1)
        lst = args[0]
        if not isinstance(lst, list):
            raise RuntimeError("unique expects a list argument")
        seen = []
        result = []
        for item in lst:
            key = repr(item)
            if key not in seen:
                seen.append(key)
                result.append(item)
        return result

    def _builtin_count(self, args):
        """count(list, value) -> number of occurrences of value in list."""
        self._expect_args('count', args, 2)
        lst = args[0]
        if not isinstance(lst, list):
            raise RuntimeError("count expects a list as first argument")
        return lst.count(args[1])

    def _builtin_sum(self, args):
        """sum(list) -> sum of all numeric elements."""
        self._expect_args('sum', args, 1)
        lst = args[0]
        if not isinstance(lst, list):
            raise RuntimeError("sum expects a list argument")
        return sum(lst)

    def _builtin_any(self, args):
        """any(list) -> true if any element is truthy."""
        self._expect_args('any', args, 1)
        lst = args[0]
        if not isinstance(lst, list):
            raise RuntimeError("any expects a list argument")
        return any(lst)

    def _builtin_all(self, args):
        """all(list) -> true if all elements are truthy."""
        self._expect_args('all', args, 1)
        lst = args[0]
        if not isinstance(lst, list):
            raise RuntimeError("all expects a list argument")
        return all(lst)

    def _builtin_slice(self, args):
        """slice(list, start, end) -> sub-list from start to end (exclusive)."""
        if len(args) < 2 or len(args) > 3:
            raise RuntimeError("slice expects 2-3 arguments: slice list start [end]")
        lst = args[0]
        if not isinstance(lst, list):
            raise RuntimeError("slice expects a list as first argument")
        start = int(args[1])
        end = len(lst) if len(args) < 3 else int(args[2])
        return lst[start:end]

    def _builtin_chunk(self, args):
        """chunk(list, size) -> split list into sub-lists of given size."""
        self._expect_args('chunk', args, 2)
        lst = args[0]
        size = int(args[1])
        if not isinstance(lst, list):
            raise RuntimeError("chunk expects a list as first argument")
        if size <= 0:
            raise RuntimeError("chunk size must be positive")
        return [lst[i:i+size] for i in range(0, len(lst), size)]

    def _builtin_find(self, args):
        """find(fn, list) -> first element where fn returns true, or null."""
        self._expect_args('find', args, 2)
        fn, lst = args[0], args[1]
        if not isinstance(fn, (str, LambdaValue)):
            raise RuntimeError("find expects a function name or lambda as first argument")
        if not isinstance(lst, list):
            raise RuntimeError("find expects a list as second argument")
        for item in lst:
            result = self._call_function_with_args(fn, [item])
            if result:
                return item
        return None

    def _builtin_find_index(self, args):
        """find_index(fn, list) -> index of first element where fn returns true, or -1."""
        self._expect_args('find_index', args, 2)
        fn, lst = args[0], args[1]
        if not isinstance(fn, (str, LambdaValue)):
            raise RuntimeError("find_index expects a function name or lambda as first argument")
        if not isinstance(lst, list):
            raise RuntimeError("find_index expects a list as second argument")
        for i, item in enumerate(lst):
            result = self._call_function_with_args(fn, [item])
            if result:
                return i
        return -1

    # — Statistics builtins ————————————————————————

    def _builtin_mean(self, args):
        self._expect_args('mean', args, 1)
        lst = args[0]
        if not isinstance(lst, list):
            raise RuntimeError("mean expects a list argument")
        if len(lst) == 0:
            raise RuntimeError("mean: empty list")
        total = 0.0
        for v in lst:
            if not isinstance(v, (int, float)):
                raise RuntimeError("mean: all elements must be numbers")
            total += v
        return total / len(lst)

    def _builtin_median(self, args):
        self._expect_args('median', args, 1)
        lst = args[0]
        if not isinstance(lst, list):
            raise RuntimeError("median expects a list argument")
        if len(lst) == 0:
            raise RuntimeError("median: empty list")
        for v in lst:
            if not isinstance(v, (int, float)):
                raise RuntimeError("median: all elements must be numbers")
        s = sorted(lst)
        n = len(s)
        mid = n // 2
        if n % 2 == 1:
            return float(s[mid])
        return (s[mid - 1] + s[mid]) / 2.0

    def _builtin_stdev(self, args):
        self._expect_args('stdev', args, 1)
        lst = args[0]
        if not isinstance(lst, list):
            raise RuntimeError("stdev expects a list argument")
        if len(lst) == 0:
            raise RuntimeError("stdev: empty list")
        import math
        m = self._builtin_mean([lst])
        variance = 0.0
        for v in lst:
            if not isinstance(v, (int, float)):
                raise RuntimeError("stdev: all elements must be numbers")
            variance += (v - m) ** 2
        variance /= len(lst)
        return math.sqrt(variance)

    def _builtin_variance(self, args):
        self._expect_args('variance', args, 1)
        lst = args[0]
        if not isinstance(lst, list):
            raise RuntimeError("variance expects a list argument")
        if len(lst) == 0:
            raise RuntimeError("variance: empty list")
        m = self._builtin_mean([lst])
        total = 0.0
        for v in lst:
            if not isinstance(v, (int, float)):
                raise RuntimeError("variance: all elements must be numbers")
            total += (v - m) ** 2
        return total / len(lst)

    def _builtin_mode(self, args):
        self._expect_args('mode', args, 1)
        lst = args[0]
        if not isinstance(lst, list):
            raise RuntimeError("mode expects a list argument")
        if len(lst) == 0:
            raise RuntimeError("mode: empty list")
        counts = {}
        order = []
        for v in lst:
            key = v
            if key not in counts:
                counts[key] = 0
                order.append(key)
            counts[key] += 1
        best = order[0]
        best_count = counts[best]
        for k in order[1:]:
            if counts[k] > best_count:
                best = k
                best_count = counts[k]
        return best

    def _builtin_percentile(self, args):
        self._expect_args('percentile', args, 2)
        lst = args[0]
        p = args[1]
        if not isinstance(lst, list):
            raise RuntimeError("percentile expects a list as first argument")
        if not isinstance(p, (int, float)):
            raise RuntimeError("percentile expects a number as second argument")
        if p < 0 or p > 100:
            raise RuntimeError("percentile: p must be between 0 and 100")
        if len(lst) == 0:
            raise RuntimeError("percentile: empty list")
        for v in lst:
            if not isinstance(v, (int, float)):
                raise RuntimeError("percentile: all elements must be numbers")
        s = sorted(lst)
        if p == 0:
            return float(s[0])
        if p == 100:
            return float(s[-1])
        k = (p / 100.0) * (len(s) - 1)
        f = int(k)
        c = f + 1
        if c >= len(s):
            return float(s[f])
        d = k - f
        return float(s[f]) + d * (float(s[c]) - float(s[f]))

    def _builtin_clamp(self, args):
        self._expect_args('clamp', args, 3)
        val, lo, hi = args[0], args[1], args[2]
        for v in (val, lo, hi):
            if not isinstance(v, (int, float)):
                raise RuntimeError("clamp: all arguments must be numbers")
        if lo > hi:
            raise RuntimeError("clamp: lo must be <= hi")
        if val < lo:
            return float(lo)
        if val > hi:
            return float(hi)
        return float(val)

    def _builtin_lerp(self, args):
        self._expect_args('lerp', args, 3)
        a, b, t = args[0], args[1], args[2]
        for v in (a, b, t):
            if not isinstance(v, (int, float)):
                raise RuntimeError("lerp: all arguments must be numbers")
        return float(a) + (float(b) - float(a)) * float(t)

    def _builtin_remap(self, args):
        self._expect_args('remap', args, 5)
        val, in_lo, in_hi, out_lo, out_hi = args
        for v in args:
            if not isinstance(v, (int, float)):
                raise RuntimeError("remap: all arguments must be numbers")
        if in_lo == in_hi:
            raise RuntimeError("remap: input range must not be zero-width")
        t = (val - in_lo) / (in_hi - in_lo)
        return float(out_lo) + t * (float(out_hi) - float(out_lo))

    # --- Generator built-ins ---

    def _builtin_collect(self, args):
        """collect(generator) -> list of all yielded values."""
        self._expect_args('collect', args, 1)
        gen = args[0]
        if isinstance(gen, GeneratorValue):
            return gen.to_list()
        elif isinstance(gen, list):
            return list(gen)
        raise RuntimeError("collect: argument must be a generator or list")

    def _builtin_is_generator(self, args):
        """is_generator(value) -> true if value is a generator."""
        self._expect_args('is_generator', args, 1)
        return isinstance(args[0], GeneratorValue)

    # --- Regex built-ins ---

    def _builtin_regex_match(self, args):
        """regex_match(pattern, string) -> true if the entire string matches the pattern."""
        self._expect_args('regex_match', args, 2)
        pattern, string = args[0], args[1]
        if not isinstance(pattern, str):
            raise RuntimeError("regex_match expects a string pattern as first argument")
        if not isinstance(string, str):
            raise RuntimeError("regex_match expects a string as second argument")
        try:
            return re.fullmatch(pattern, string) is not None
        except re.error as e:
            raise RuntimeError(f"regex_match: invalid regex pattern: {e}")

    def _builtin_regex_find(self, args):
        """regex_find(pattern, string) -> map with 'match', 'start', 'end', 'groups' or null."""
        self._expect_args('regex_find', args, 2)
        pattern, string = args[0], args[1]
        if not isinstance(pattern, str):
            raise RuntimeError("regex_find expects a string pattern as first argument")
        if not isinstance(string, str):
            raise RuntimeError("regex_find expects a string as second argument")
        try:
            m = re.search(pattern, string)
        except re.error as e:
            raise RuntimeError(f"regex_find: invalid regex pattern: {e}")
        if m is None:
            return None
        groups = list(m.groups()) if m.groups() else []
        return {
            'match': m.group(0),
            'start': m.start(),
            'end': m.end(),
            'groups': groups,
        }

    def _builtin_regex_find_all(self, args):
        """regex_find_all(pattern, string) -> list of all matches (strings or group tuples)."""
        self._expect_args('regex_find_all', args, 2)
        pattern, string = args[0], args[1]
        if not isinstance(pattern, str):
            raise RuntimeError("regex_find_all expects a string pattern as first argument")
        if not isinstance(string, str):
            raise RuntimeError("regex_find_all expects a string as second argument")
        try:
            results = re.findall(pattern, string)
        except re.error as e:
            raise RuntimeError(f"regex_find_all: invalid regex pattern: {e}")
        # re.findall returns strings when no groups, tuples when groups
        # Convert tuples to lists for sauravcode consistency
        return [list(r) if isinstance(r, tuple) else r for r in results]

    def _builtin_regex_replace(self, args):
        """regex_replace(pattern, replacement, string) -> string with matches replaced."""
        self._expect_args('regex_replace', args, 3)
        pattern, replacement, string = args[0], args[1], args[2]
        if not isinstance(pattern, str):
            raise RuntimeError("regex_replace expects a string pattern as first argument")
        if not isinstance(replacement, str):
            raise RuntimeError("regex_replace expects a string replacement as second argument")
        if not isinstance(string, str):
            raise RuntimeError("regex_replace expects a string as third argument")
        try:
            return re.sub(pattern, replacement, string)
        except re.error as e:
            raise RuntimeError(f"regex_replace: invalid regex pattern: {e}")

    def _builtin_regex_split(self, args):
        """regex_split(pattern, string) -> list of substrings split by pattern matches."""
        self._expect_args('regex_split', args, 2)
        pattern, string = args[0], args[1]
        if not isinstance(pattern, str):
            raise RuntimeError("regex_split expects a string pattern as first argument")
        if not isinstance(string, str):
            raise RuntimeError("regex_split expects a string as second argument")
        try:
            return re.split(pattern, string)
        except re.error as e:
            raise RuntimeError(f"regex_split: invalid regex pattern: {e}")

    # --- JSON built-ins ---
    def _builtin_json_parse(self, args):
        """json_parse(string) -> parse JSON string into a map/list/value."""
        self._expect_args('json_parse', args, 1)
        s = args[0]
        if not isinstance(s, str):
            raise RuntimeError("json_parse expects a string argument")
        import json as _json
        try:
            result = _json.loads(s)
            return self._json_to_srv(result)
        except _json.JSONDecodeError as e:
            raise RuntimeError(f"json_parse: invalid JSON: {e}")

    def _builtin_json_stringify(self, args):
        """json_stringify(value) -> convert a value to a compact JSON string."""
        self._expect_args('json_stringify', args, 1)
        import json as _json
        try:
            return _json.dumps(self._srv_to_json(args[0]), separators=(',', ':'))
        except (TypeError, ValueError) as e:
            raise RuntimeError(f"json_stringify: cannot serialize: {e}")

    def _builtin_json_pretty(self, args):
        """json_pretty(value) -> convert a value to a pretty-printed JSON string."""
        self._expect_args('json_pretty', args, 1)
        import json as _json
        try:
            return _json.dumps(self._srv_to_json(args[0]), indent=2)
        except (TypeError, ValueError) as e:
            raise RuntimeError(f"json_pretty: cannot serialize: {e}")

    # — Hash & encoding builtins ————————————————————

    def _builtin_md5(self, args):
        """md5(string) -> MD5 hex digest of the input string."""
        self._expect_args('md5', args, 1)
        s = args[0]
        if not isinstance(s, str):
            s = str(s)
        import hashlib
        return hashlib.md5(s.encode('utf-8')).hexdigest()

    def _builtin_sha256(self, args):
        """sha256(string) -> SHA-256 hex digest of the input string."""
        self._expect_args('sha256', args, 1)
        s = args[0]
        if not isinstance(s, str):
            s = str(s)
        import hashlib
        return hashlib.sha256(s.encode('utf-8')).hexdigest()

    def _builtin_sha1(self, args):
        """sha1(string) -> SHA-1 hex digest of the input string."""
        self._expect_args('sha1', args, 1)
        s = args[0]
        if not isinstance(s, str):
            s = str(s)
        import hashlib
        return hashlib.sha1(s.encode('utf-8')).hexdigest()

    def _builtin_base64_encode(self, args):
        """base64_encode(string) -> Base64 encoded string."""
        self._expect_args('base64_encode', args, 1)
        s = args[0]
        if not isinstance(s, str):
            s = str(s)
        import base64
        return base64.b64encode(s.encode('utf-8')).decode('ascii')

    def _builtin_base64_decode(self, args):
        """base64_decode(string) -> decoded string from Base64."""
        self._expect_args('base64_decode', args, 1)
        s = args[0]
        if not isinstance(s, str):
            raise RuntimeError("base64_decode expects a string argument")
        import base64
        try:
            return base64.b64decode(s).decode('utf-8')
        except Exception as e:
            raise RuntimeError(f"base64_decode: invalid input: {e}")

    def _builtin_hex_encode(self, args):
        """hex_encode(string) -> hex-encoded string."""
        self._expect_args('hex_encode', args, 1)
        s = args[0]
        if not isinstance(s, str):
            s = str(s)
        return s.encode('utf-8').hex()

    def _builtin_hex_decode(self, args):
        """hex_decode(hex_string) -> decoded string from hex."""
        self._expect_args('hex_decode', args, 1)
        s = args[0]
        if not isinstance(s, str):
            raise RuntimeError("hex_decode expects a string argument")
        try:
            return bytes.fromhex(s).decode('utf-8')
        except Exception as e:
            raise RuntimeError(f"hex_decode: invalid hex string: {e}")

    def _builtin_crc32(self, args):
        """crc32(string) -> CRC-32 checksum as unsigned integer."""
        self._expect_args('crc32', args, 1)
        s = args[0]
        if not isinstance(s, str):
            s = str(s)
        import binascii
        return float(binascii.crc32(s.encode('utf-8')) & 0xFFFFFFFF)

    def _builtin_url_encode(self, args):
        """url_encode(string) -> percent-encoded string for URLs."""
        self._expect_args('url_encode', args, 1)
        s = args[0]
        if not isinstance(s, str):
            s = str(s)
        from urllib.parse import quote
        return quote(s, safe='')

    def _builtin_url_decode(self, args):
        """url_decode(string) -> decoded string from percent-encoding."""
        self._expect_args('url_decode', args, 1)
        s = args[0]
        if not isinstance(s, str):
            raise RuntimeError("url_decode expects a string argument")
        from urllib.parse import unquote
        return unquote(s)

    # — String padding & char builtins ———————————————

    def _builtin_pad_left(self, args):
        """pad_left str width [fill] — left-pad string to given width."""
        if len(args) < 2 or len(args) > 3:
            raise RuntimeError("pad_left expects 2-3 arguments: str width [fill]")
        s = args[0]
        if not isinstance(s, str):
            s = str(s)
        width = args[1]
        if not isinstance(width, (int, float)):
            raise RuntimeError("pad_left: width must be a number")
        width = int(width)
        fill = args[2] if len(args) == 3 else ' '
        if not isinstance(fill, str) or len(fill) != 1:
            raise RuntimeError("pad_left: fill must be a single character")
        return s.rjust(width, fill)

    def _builtin_pad_right(self, args):
        """pad_right str width [fill] — right-pad string to given width."""
        if len(args) < 2 or len(args) > 3:
            raise RuntimeError("pad_right expects 2-3 arguments: str width [fill]")
        s = args[0]
        if not isinstance(s, str):
            s = str(s)
        width = args[1]
        if not isinstance(width, (int, float)):
            raise RuntimeError("pad_right: width must be a number")
        width = int(width)
        fill = args[2] if len(args) == 3 else ' '
        if not isinstance(fill, str) or len(fill) != 1:
            raise RuntimeError("pad_right: fill must be a single character")
        return s.ljust(width, fill)

    def _builtin_repeat(self, args):
        """repeat str n — repeat string n times."""
        self._expect_args('repeat', args, 2)
        s = args[0]
        if not isinstance(s, str):
            s = str(s)
        n = args[1]
        if not isinstance(n, (int, float)):
            raise RuntimeError("repeat: count must be a number")
        n = int(n)
        if n < 0:
            raise RuntimeError("repeat: count must be non-negative")
        if n > MAX_ALLOC_SIZE:
            raise RuntimeError(f"repeat: count {n} exceeds safety limit {MAX_ALLOC_SIZE}")
        return s * n

    def _builtin_char_code(self, args):
        """char_code str — get Unicode code point of first character."""
        self._expect_args('char_code', args, 1)
        s = args[0]
        if not isinstance(s, str) or len(s) == 0:
            raise RuntimeError("char_code expects a non-empty string")
        return float(ord(s[0]))

    def _builtin_from_char_code(self, args):
        """from_char_code n — create character from Unicode code point."""
        self._expect_args('from_char_code', args, 1)
        n = args[0]
        if not isinstance(n, (int, float)):
            raise RuntimeError("from_char_code expects a number")
        code = int(n)
        if code < 0 or code > 0x10FFFF:
            raise RuntimeError(f"from_char_code: {code} is not a valid Unicode code point")
        return chr(code)

    def _json_to_srv(self, value):
        """Convert a Python JSON value to sauravcode types."""
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return float(value)
        if isinstance(value, float):
            return value
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return [self._json_to_srv(v) for v in value]
        if isinstance(value, dict):
            return {str(k): self._json_to_srv(v) for k, v in value.items()}
        return str(value)

    def _srv_to_json(self, value):
        """Convert a sauravcode value to JSON-compatible Python types."""
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, float):
            if value == int(value):
                return int(value)
            return value
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return [self._srv_to_json(v) for v in value]
        if isinstance(value, dict):
            return {str(k): self._srv_to_json(v) for k, v in value.items()}
        return str(value)

    def _guarded_repeat(self, seq, count):
        """Guard string/list repetition against memory exhaustion."""
        kind = "String" if isinstance(seq, str) else "List"
        unit = "characters" if isinstance(seq, str) else "elements"
        if count > 0 and len(seq) * count > MAX_ALLOC_SIZE:
            raise RuntimeError(
                f"{kind} repetition would create {len(seq) * count:,} {unit}, "
                f"exceeding limit of {MAX_ALLOC_SIZE:,}")
        return seq * count

    def _scoped_env(self):
        """Context manager: saves self.variables on entry, restores on exit.

        Eliminates the repeated saved_env = self.variables.copy() / restore
        pattern used across execute_function, _call_lambda, _eval_pipe, etc.
        """
        import contextlib

        @contextlib.contextmanager
        def _scope():
            saved = self.variables.copy()
            try:
                yield
            finally:
                self.variables = saved

        return _scope()

    def _expect_args(self, name, args, count):
        if len(args) != count:
            raise RuntimeError(f"{name} expects {count} argument(s), got {len(args)}")

    def _has_yield(self, body):
        """Check if a function body contains any yield statements (recursively)."""
        for stmt in body:
            if isinstance(stmt, YieldNode):
                return True
            # Check nested blocks
            if isinstance(stmt, IfNode):
                if self._has_yield(stmt.body):
                    return True
                for elif_cond, elif_body in (stmt.elif_blocks if hasattr(stmt, 'elif_blocks') else []):
                    if self._has_yield(elif_body):
                        return True
                if hasattr(stmt, 'else_body') and stmt.else_body and self._has_yield(stmt.else_body):
                    return True
            elif isinstance(stmt, (WhileNode, ForNode, ForEachNode)):
                if self._has_yield(stmt.body):
                    return True
            elif isinstance(stmt, TryCatchNode):
                if self._has_yield(stmt.body) or self._has_yield(stmt.handler):
                    return True
        return False

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

    def _interp_yield(self, ast):
        result = self.evaluate(ast.expression)
        debug(f"YieldNode evaluated with result: {result}\n")
        raise YieldSignal(result)

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
        elif isinstance(value, GeneratorValue):
            print(repr(value))
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

    def _interp_enum(self, ast):
        """Register an enum type with auto-incrementing integer values."""
        enum_map = {}
        for i, variant in enumerate(ast.variants):
            enum_map[variant] = float(i)
        self.enums[ast.name] = enum_map
        debug(f"Registered enum: {ast.name} = {enum_map}")

    def _interp_break(self, ast):
        raise BreakSignal()

    def _interp_continue(self, ast):
        raise ContinueSignal()

    def _interp_assert(self, ast):
        """Execute assert statement — raise RuntimeError if condition is falsy."""
        value = self.evaluate(ast.condition)
        if not value:
            if ast.message is not None:
                msg = self.evaluate(ast.message)
            else:
                msg = "Assertion failed"
            raise RuntimeError(f"AssertionError: {msg}")

    def _eval_enum_access(self, node):
        """Evaluate enum variant access: EnumName.VARIANT"""
        enum_map = self.enums.get(node.enum_name)
        if enum_map is None:
            raise RuntimeError(f"Unknown enum '{node.enum_name}'")
        if node.variant_name not in enum_map:
            raise RuntimeError(
                f"Enum '{node.enum_name}' has no variant '{node.variant_name}'. "
                f"Available: {', '.join(enum_map.keys())}"
            )
        return enum_map[node.variant_name]

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
            try:
                self.execute_body(node.body)
            except BreakSignal:
                break
            except ContinueSignal:
                continue

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
            try:
                self.execute_body(node.body)
            except BreakSignal:
                break
            except ContinueSignal:
                continue

    def execute_for_each(self, node):
        """Execute for-each loop: for item in collection.
        
        Iterates over:
        - Lists → elements
        - Strings → individual characters
        - Maps → keys
        - Generators → yielded values
        """
        collection = self.evaluate(node.iterable)
        if isinstance(collection, GeneratorValue):
            items = collection.to_list()
        elif isinstance(collection, list):
            items = collection
        elif isinstance(collection, str):
            items = list(collection)
        elif isinstance(collection, dict):
            items = list(collection.keys())
        else:
            raise RuntimeError(
                f"Cannot iterate over {type(collection).__name__}. "
                f"for-each requires a list, string, map, or generator."
            )
        if len(items) > MAX_LOOP_ITERATIONS:
            raise RuntimeError(
                f"For-each collection size ({len(items):,}) exceeds maximum "
                f"iterations ({MAX_LOOP_ITERATIONS:,})"
            )
        for item in items:
            self.variables[node.var] = item
            try:
                self.execute_body(node.body)
            except BreakSignal:
                break
            except ContinueSignal:
                continue

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

    def execute_match(self, node):
        """Execute match/case pattern matching."""
        value = self.evaluate(node.expression)
        for case in node.cases:
            if case.is_wildcard:
                if case.binding_name:
                    self.variables[case.binding_name] = value
                self.execute_body(case.body)
                return
            for pattern in case.patterns:
                matched = False
                if case.binding_name:
                    # Variable binding - always matches the pattern
                    matched = True
                else:
                    # Literal match
                    pattern_val = self.evaluate(pattern)
                    matched = (value == pattern_val)
                if matched:
                    if case.guard:
                        if case.binding_name:
                            self.variables[case.binding_name] = value
                        if self._is_truthy(self.evaluate(case.guard)):
                            self.execute_body(case.body)
                            return
                        if case.binding_name:
                            if case.binding_name in self.variables:
                                del self.variables[case.binding_name]
                    else:
                        if case.binding_name:
                            self.variables[case.binding_name] = value
                        self.execute_body(case.body)
                        return

    def execute_import(self, node):
        """Execute import statement — load and run a .srv module file.
        
        Resolves the module path relative to the currently executing file
        (or cwd if running from REPL). The imported module is executed in
        an isolated scope; its function definitions are merged into the
        caller's scope, and new variables are added without overwriting
        any existing variables in the caller's scope (fixes issue #13:
        silent variable shadowing). Side-effect statements (print, loops)
        still execute during import but cannot modify the caller's state.
        Circular imports are detected and silently skipped.
        """
        module_path = node.module_path
        
        # Add .srv extension if not present
        if not module_path.endswith('.srv'):
            module_path = module_path + '.srv'
        
        # Resolve relative to source file directory or cwd
        if self._source_dir and not os.path.isabs(module_path):
            full_path = os.path.join(self._source_dir, module_path)
        else:
            full_path = module_path
        
        # Normalize for circular import detection
        full_path = os.path.abspath(full_path)
        
        # Prevent path traversal — imports must resolve within the source
        # directory or current working directory (fixes issue #24)
        allowed_root = os.path.abspath(self._source_dir or os.getcwd())
        if not full_path.startswith(allowed_root + os.sep) and full_path != allowed_root:
            raise RuntimeError(
                f"Cannot import '{node.module_path}': "
                f"path traversal outside project directory is not allowed"
            )
        
        # Circular import guard
        if full_path in self._imported_modules:
            debug(f"Skipping already-imported module: {full_path}")
            return
        
        if not os.path.isfile(full_path):
            raise RuntimeError(f"Cannot import '{node.module_path}': file '{full_path}' not found")
        
        # Mark as imported before executing (handles mutual imports)
        self._imported_modules.add(full_path)
        
        try:
            with open(full_path, 'r') as f:
                code = f.read()
        except Exception as e:
            raise RuntimeError(f"Cannot read module '{node.module_path}': {e}")
        
        # Save current source dir and set to module's directory
        prev_source_dir = self._source_dir
        self._source_dir = os.path.dirname(full_path)
        
        try:
            tokens = list(tokenize(code))
            parser = Parser(tokens)
            ast_nodes = parser.parse()
            
            # Execute module in an isolated scope (issue #13).
            # Save the caller's variables, run the module in a clean
            # environment, then merge back: functions always overwrite
            # (latest definition wins), but variables only merge if
            # they don't already exist in the caller's scope.
            saved_vars = self.variables.copy()
            saved_funcs = self.functions.copy()

            for stmt in ast_nodes:
                self.interpret(stmt)

            # Collect all functions defined/overwritten by the module
            module_functions = dict(self.functions)
            # Collect all variables defined by the module
            module_vars = dict(self.variables)

            # Attach the module scope as a closure on each function defined
            # in this module, so they can reference module-level variables
            # at call time even after the caller's scope is restored (#26).
            for fname, func in module_functions.items():
                if fname not in saved_funcs or func is not saved_funcs[fname]:
                    func.closure_scope = dict(module_vars)

            # Restore caller's state
            self.variables = saved_vars
            self.functions = saved_funcs

            # Merge functions (always: latest definition wins)
            self.functions.update(module_functions)

            # Merge variables (only new ones — never overwrite caller's)
            for name, value in module_vars.items():
                if name not in self.variables:
                    self.variables[name] = value
        finally:
            # Restore source dir
            self._source_dir = prev_source_dir
        
        debug(f"Imported module: {node.module_path}")

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

            # Check if this is a generator function (contains yield)
            if self._has_yield(func.body):
                debug(f"Function {call_node.name} is a generator — returning GeneratorValue")
                evaluated_args = [self.evaluate(arg) for arg in call_node.arguments]
                return GeneratorValue(self, func, evaluated_args)

            # Guard against excessive recursion (DoS protection)
            self._call_depth += 1
            if self._call_depth > MAX_RECURSION_DEPTH:
                self._call_depth -= 1
                raise RuntimeError(
                    f"Maximum recursion depth ({MAX_RECURSION_DEPTH}) exceeded "
                    f"in function '{call_node.name}'"
                )

            result = None
            with self._scoped_env():
                # Inject closure scope from imported modules (#26).
                # Variables from the defining module are available but
                # won't overwrite the caller's existing variables.
                if hasattr(func, 'closure_scope') and func.closure_scope:
                    for cname, cval in func.closure_scope.items():
                        if cname not in self.variables:
                            self.variables[cname] = cval

                for param, arg in zip(func.params, call_node.arguments):
                    evaluated_arg = self.evaluate(arg)
                    self.variables[param] = evaluated_arg
                    debug(f"Set parameter '{param}' to {evaluated_arg}")
                try:
                    for stmt in func.body:
                        self.interpret(stmt)
                except ReturnSignal as ret:
                    result = ret.value
                finally:
                    self._call_depth -= 1
            debug(f"Function {call_node.name} returned {result}\n")
            return result

        # Check built-in functions
        if call_node.name in self.builtins:
            evaluated_args = [self.evaluate(arg) for arg in call_node.arguments]
            # Zero-arg builtin call: if a user variable shadows it, return the variable
            if len(evaluated_args) == 0 and call_node.name in self.variables:
                return self.variables[call_node.name]
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
        try:
            if node.operator == '+':
                return left + right
            elif node.operator == '-':
                return left - right
            elif node.operator == '*':
                # Guard against memory exhaustion via string/list repetition
                if isinstance(left, (str, list)) and isinstance(right, (int, float)):
                    return self._guarded_repeat(left, int(right))
                elif isinstance(right, (str, list)) and isinstance(left, (int, float)):
                    return self._guarded_repeat(right, int(left))
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
        except TypeError:
            left_type = 'string' if isinstance(left, str) else \
                        'list' if isinstance(left, list) else \
                        'bool' if isinstance(left, bool) else \
                        'number' if isinstance(left, (int, float)) else type(left).__name__
            right_type = 'string' if isinstance(right, str) else \
                         'list' if isinstance(right, list) else \
                         'bool' if isinstance(right, bool) else \
                         'number' if isinstance(right, (int, float)) else type(right).__name__
            raise RuntimeError(
                f"Cannot use '{node.operator}' on {left_type} and {right_type}"
            )

    def _eval_compare(self, node):
        left = self.evaluate(node.left)
        right = self.evaluate(node.right)
        debug(f"Comparing: {left} {node.operator} {right}")
        if node.operator == '==':
            return left == right
        elif node.operator == '!=':
            return left != right
        try:
            if node.operator == '<':
                return left < right
            elif node.operator == '>':
                return left > right
            elif node.operator == '<=':
                return left <= right
            elif node.operator == '>=':
                return left >= right
            else:
                raise ValueError(f'Unknown comparison operator: {node.operator}')
        except TypeError:
            left_type = 'string' if isinstance(left, str) else \
                        'list' if isinstance(left, list) else \
                        'bool' if isinstance(left, bool) else \
                        'map' if isinstance(left, dict) else \
                        'number' if isinstance(left, (int, float)) else type(left).__name__
            right_type = 'string' if isinstance(right, str) else \
                         'list' if isinstance(right, list) else \
                         'bool' if isinstance(right, bool) else \
                         'map' if isinstance(right, dict) else \
                         'number' if isinstance(right, (int, float)) else type(right).__name__
            raise RuntimeError(
                f"Cannot compare {left_type} and {right_type} with '{node.operator}'"
            )

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

    def _eval_list_comprehension(self, node):
        """Evaluate list comprehension: [expr for var in iterable if cond]"""
        collection = self.evaluate(node.iterable)
        if isinstance(collection, list):
            items = collection
        elif isinstance(collection, str):
            items = list(collection)
        elif isinstance(collection, dict):
            items = list(collection.keys())
        else:
            raise RuntimeError(
                f"Cannot iterate over {type(collection).__name__} in "
                f"list comprehension. Expected list, string, or map."
            )
        if len(items) > MAX_LOOP_ITERATIONS:
            raise RuntimeError(
                f"List comprehension collection size ({len(items):,}) exceeds "
                f"maximum iterations ({MAX_LOOP_ITERATIONS:,})"
            )
        # Save old variable value to restore after comprehension
        old_val = self.variables.get(node.var, None)
        had_var = node.var in self.variables
        result = []
        for item in items:
            self.variables[node.var] = item
            if node.condition is not None:
                cond = self.evaluate(node.condition)
                if not self._is_truthy(cond):
                    continue
            result.append(self.evaluate(node.expr))
        # Restore variable scope
        if had_var:
            self.variables[node.var] = old_val
        else:
            self.variables.pop(node.var, None)
        return result

    def _eval_index(self, node):
        obj = self.evaluate(node.obj)
        idx = self.evaluate(node.index)
        if isinstance(obj, (list, str)):
            i = int(idx)
            if i < 0:
                i += len(obj)
            if i < 0 or i >= len(obj):
                raise RuntimeError(f"Index {int(idx)} out of bounds (size {len(obj)})")
            return obj[i]
        if isinstance(obj, dict):
            if idx not in obj:
                raise RuntimeError(f"Key {idx!r} not found in map")
            return obj[idx]
        raise RuntimeError(f"Cannot index into {type(obj).__name__}")

    def _eval_slice(self, node):
        obj = self.evaluate(node.obj)
        start = int(self.evaluate(node.start)) if node.start is not None else None
        end = int(self.evaluate(node.end)) if node.end is not None else None
        if isinstance(obj, (list, str)):
            return obj[start:end]
        raise RuntimeError(f"Cannot slice {type(obj).__name__}; expected list or string")

    def _eval_len(self, node):
        obj = self.evaluate(node.expression)
        if isinstance(obj, (list, str)):
            return float(len(obj))
        if isinstance(obj, dict):
            return float(len(obj))
        if isinstance(obj, GeneratorValue):
            return float(len(obj.to_list()))
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

    def _eval_lambda(self, node):
        """Evaluate a lambda expression — captures current scope as closure."""
        return LambdaValue(node.params, node.body_expr, self.variables.copy())

    def _call_lambda(self, lam, args):
        """Call a LambdaValue with the given arguments."""
        if len(args) != len(lam.params):
            raise RuntimeError(
                f"Lambda expects {len(lam.params)} argument(s), "
                f"got {len(args)}"
            )
        # Set up lambda scope: closure + params
        with self._scoped_env():
            self.variables = lam.closure.copy()
            for param, val in zip(lam.params, args):
                self.variables[param] = val
            return self.evaluate(lam.body_expr)

    def _eval_ternary(self, node):
        condition = self.evaluate(node.condition)
        if condition:
            return self.evaluate(node.true_expr)
        else:
            return self.evaluate(node.false_expr)

    def _eval_pipe(self, node):
        """Evaluate a pipe expression: value |> function.
        
        The piped value is passed as the LAST argument to the function.
        - If right side is a function call (e.g., map (lambda x -> x*2)),
          evaluate its explicit args and append the piped value.
        - If right side is a function name (IdentifierNode), call with piped value.
        - If right side is a lambda, call with piped value.
        """
        piped_value = self.evaluate(node.value)
        func_node = node.function
        
        # Case 1: Right side is a function call with explicit arguments
        # e.g., [1,2,3] |> map (lambda x -> x * 2) → map(lambda, [1,2,3])
        if isinstance(func_node, FunctionCallNode):
            evaluated_args = [self.evaluate(arg) for arg in func_node.arguments]
            evaluated_args.append(piped_value)
            func_name = func_node.name
            # Check user-defined functions first
            func = self.functions.get(func_name)
            if func:
                self._call_depth += 1
                if self._call_depth > MAX_RECURSION_DEPTH:
                    self._call_depth -= 1
                    raise RuntimeError(
                        f"Maximum recursion depth ({MAX_RECURSION_DEPTH}) exceeded")
                result = None
                with self._scoped_env():
                    for param, val in zip(func.params, evaluated_args):
                        self.variables[param] = val
                    try:
                        for stmt in func.body:
                            self.interpret(stmt)
                    except ReturnSignal as ret:
                        result = ret.value
                    finally:
                        self._call_depth -= 1
                return result
            if func_name in self.builtins:
                return self.builtins[func_name](evaluated_args)
            raise RuntimeError(f"Function '{func_name}' is not defined.")
        
        # Case 2: Right side is an identifier (function name, no extra args)
        # e.g., "hello" |> upper → upper("hello")
        if isinstance(func_node, IdentifierNode):
            func_name = func_node.name
            # Check if it's a variable holding a lambda
            if func_name in self.variables:
                val = self.variables[func_name]
                if isinstance(val, LambdaValue):
                    return self._call_lambda(val, [piped_value])
            # Check user-defined functions
            func = self.functions.get(func_name)
            if func:
                self._call_depth += 1
                if self._call_depth > MAX_RECURSION_DEPTH:
                    self._call_depth -= 1
                    raise RuntimeError(
                        f"Maximum recursion depth ({MAX_RECURSION_DEPTH}) exceeded")
                result = None
                with self._scoped_env():
                    for param, val in zip(func.params, [piped_value]):
                        self.variables[param] = val
                    try:
                        for stmt in func.body:
                            self.interpret(stmt)
                    except ReturnSignal as ret:
                        result = ret.value
                    finally:
                        self._call_depth -= 1
                return result
            # Check builtins
            if func_name in self.builtins:
                return self.builtins[func_name]([piped_value])
            raise RuntimeError(f"Function '{func_name}' is not defined.")
        
        # Case 3: Right side is a lambda expression
        # e.g., 5 |> lambda x -> x * 2
        if isinstance(func_node, LambdaNode):
            lam = self._eval_lambda(func_node)
            return self._call_lambda(lam, [piped_value])
        
        # Case 4: Right side evaluated to a callable value
        func_val = self.evaluate(func_node)
        if isinstance(func_val, LambdaValue):
            return self._call_lambda(func_val, [piped_value])
        
        raise RuntimeError(
            f"Pipe operator requires a function on the right side, "
            f"got {type(func_val).__name__}"
        )


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
            print("For-each: use 'for item in list' to iterate over collections.")
            print("F-strings: use f\"Hello {name}!\" to embed expressions in strings.")
            print("Higher-order: map, filter, reduce, each work with function names.")
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
                'map':         'map func list       — apply function to each element',
                'filter':      'filter func list    — keep elements where func is truthy',
                'reduce':      'reduce func list init — fold list with binary function',
                'each':        'each func list      — apply func to each element (side effects)',
                'regex_match':    'regex_match pat str    — true if entire string matches regex',
                'regex_find':     'regex_find pat str     — first match as map {match, start, end, groups}',
                'regex_find_all': 'regex_find_all pat str — list of all regex matches',
                'regex_replace':  'regex_replace pat rep str — replace regex matches in string',
                'regex_split':    'regex_split pat str    — split string by regex pattern',
                'json_parse':     'json_parse str         — parse JSON string into value',
                'json_stringify': 'json_stringify val     — convert value to compact JSON string',
                'json_pretty':    'json_pretty val        — convert value to pretty JSON string',
                'pad_left':       'pad_left str w [fill]  — left-pad string to width w',
                'pad_right':      'pad_right str w [fill] — right-pad string to width w',
                'repeat':         'repeat str n           — repeat string n times',
                'char_code':      'char_code str          — Unicode code point of first char',
                'from_char_code': 'from_char_code n       — character from Unicode code point',
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
    abs_filename = os.path.abspath(filename)
    interpreter._source_dir = os.path.dirname(abs_filename)
    interpreter._imported_modules.add(abs_filename)  # Prevent re-importing entry file
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
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    if result is not None:
        print("\nFinal result:", result)

if __name__ == '__main__':
    main()

