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
token_specification = [
    ('COMMENT',  r'#.*'),  # Comments
    ('NUMBER',   r'\d+(\.\d*)?'),  # Integer or decimal number
    ('STRING',   r'\".*?\"'),  # String literal
    ('ASSIGN',   r'='),  # Assignment operator
    ('EQ',       r'=='),  # Equality operator
    ('OP',       r'[+\-*/]'),  # Arithmetic operators
    ('KEYWORD',  r'\b(?:function|return|class|int|float|bool|string|if|else if|else|for|while|try|catch|list|set|map|stack|queue)\b'),  # All keywords
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

class IdentifierNode(ASTNode):
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"IdentifierNode(name={self.name})"

class FunctionCallNode(ASTNode):
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments

    def __repr__(self):
        return f"FunctionCallNode(name={self.name}, arguments={self.arguments})"

# Parser Class with Block Parsing
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
            # Skip comment lines
            self.advance()
            return None
        elif token_type == 'KEYWORD' and value == 'function':
            return self.parse_function()
        elif token_type == 'KEYWORD' and value == 'return':
            self.expect('KEYWORD', 'return')
            expression = self.parse_expression()
            return ReturnNode(expression)
        elif token_type == 'IDENT':
            name = self.expect('IDENT')[1]
            if self.peek()[0] == 'ASSIGN':
                self.expect('ASSIGN')
                expression = self.parse_expression()
                debug(f"Parsed assignment: {name} = {expression}")
                return AssignmentNode(name, expression)
            else:
                return self.parse_function_call(name)
        elif token_type == 'NEWLINE':
            self.advance()  # Skip extraneous newlines
            return None
        elif token_type in {'INDENT', 'DEDENT'}:
            debug(f"Skipping unexpected {token_type} with value={value}")
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
        while self.peek()[0] in ('NUMBER', 'IDENT'):
            token_type, value, *_ = self.peek()
            if token_type == 'NUMBER':
                self.advance()
                number_node = NumberNode(float(value))
                arguments.append(number_node)
                debug(f"Added NumberNode argument: {number_node}")
            elif token_type == 'IDENT':
                self.advance()
                ident_node = IdentifierNode(value)
                arguments.append(ident_node)
                debug(f"Added IdentifierNode argument: {ident_node}")
            else:
                break  # Break if it's not a number or identifier
        function_call_node = FunctionCallNode(name, arguments)
        debug(f"Created {function_call_node}\n")
        return function_call_node

    def parse_expression(self):
        debug("Parsing expression...")
        left = self.parse_term()
        while self.peek()[0] == 'OP':
            op = self.expect('OP')[1]
            right = self.parse_term()
            left = BinaryOpNode(left, op, right)
        debug(f"Parsed expression: {left}\n")
        return left

    def parse_term(self):
        token_type, value, *_ = self.peek()
        debug(f"Parsing term: token_type={token_type}, value={repr(value)}")
        if token_type == 'NUMBER':
            self.advance()
            number_node = NumberNode(float(value))
            debug(f"parse_term returning NumberNode: {number_node}")
            return number_node
        elif token_type == 'IDENT':
            self.advance()
            if self.peek()[0] in ('NUMBER', 'IDENT'):
                # If the next token is a number or identifier, it's a function call
                func_call_node = self.parse_function_call(value)
                debug(f"parse_term returning FunctionCallNode: {func_call_node}")
                return func_call_node
            else:
                ident_node = IdentifierNode(value)
                debug(f"parse_term returning IdentifierNode: {ident_node}")
                return ident_node
        else:
            raise SyntaxError(f'Unexpected token: {value}')

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
class Interpreter:
    def __init__(self):
        self.functions = {}  # Store function definitions
        self.variables = {}  # Store variable values

    def interpret(self, ast):
        debug("Interpreting AST...")
        if isinstance(ast, FunctionNode):
            # Store the function in the functions dictionary
            debug(f"Storing function: {ast.name}\n")
            self.functions[ast.name] = ast
        elif isinstance(ast, ReturnNode):
            result = self.evaluate(ast.expression)
            debug(f"ReturnNode evaluated with result: {result}\n")
            return result
        elif isinstance(ast, FunctionCallNode):
            debug(f"Interpreting function call: {ast.name}")
            return self.execute_function(ast)
        elif isinstance(ast, AssignmentNode):
            # Handle assignments by storing in the variables dictionary
            value = self.evaluate(ast.expression)
            self.variables[ast.name] = value
            debug(f"Assigned {value} to {ast.name}\n")
        else:
            debug(f"Unknown AST node: {ast}\n")
            raise ValueError(f'Unknown AST node type: {ast}')

    def execute_function(self, call_node):
        # Look up the function in the functions dictionary
        func = self.functions.get(call_node.name)
        if not func:
            raise RuntimeError(f"Function {call_node.name} is not defined.")
        
        debug(f"Executing function: {call_node.name} with arguments {call_node.arguments}")
        saved_env = self.variables.copy()  # Save the current variable environment
        for param, arg in zip(func.params, call_node.arguments):
            evaluated_arg = self.evaluate(arg)
            self.variables[param] = evaluated_arg
            debug(f"Set parameter '{param}' to {evaluated_arg}")

        result = None
        for stmt in func.body:
            result = self.interpret(stmt)
            if result is not None:
                break

        self.variables = saved_env  # Restore the variable environment
        debug(f"Function {call_node.name} returned {result}\n")
        return result

    def evaluate(self, node):
        debug(f"Evaluating node: {node}")
        if isinstance(node, NumberNode):
            return node.value
        elif isinstance(node, IdentifierNode):
            # Check if the identifier is a variable first
            if node.name in self.variables:
                value = self.variables[node.name]
                debug(f"Identifier '{node.name}' is a variable with value {value}")
                return value
            # If not a variable, check if it is a function (without executing it)
            elif node.name in self.functions:
                debug(f"Identifier '{node.name}' is a function name")
                return node.name  # Simply return the function name as a placeholder
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
                return left / right
            else:
                raise ValueError(f'Unknown operator: {node.operator}')
        elif isinstance(node, FunctionCallNode):
            return self.execute_function(node)
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
    
    print("\nFinal result:", result)

if __name__ == '__main__':
    main()
