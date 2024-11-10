import re
import sys
import os

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
    print("Tokenizing code...")
    tokens = []
    line_num = 1
    line_start = 0
    indent_levels = [0]  # Track indentation levels
    
    for match in re.finditer(tok_regex, code):
        typ = match.lastgroup
        value = match.group(typ)
        print(f"Token: {typ}, Value: {repr(value)}")  # Debug statement

        if typ == 'NEWLINE':
            line_num += 1
            line_start = match.end()
            tokens.append(('NEWLINE', value, line_num, match.start()))
            
            # Handle indentation on the next line
            indent_match = re.match(r'[ \t]*', code[line_start:])
            if indent_match:
                indent_str = indent_match.group(0)
                indent = len(indent_str.replace('\t', '    '))  # Normalize tabs to spaces
                print(f"Detected indentation: {indent} spaces")
                if indent > indent_levels[-1]:
                    indent_levels.append(indent)
                    tokens.append(('INDENT', indent, line_num, line_start))
                    print(f"Added INDENT token: {indent}")
                while indent < indent_levels[-1]:
                    popped_indent = indent_levels.pop()
                    tokens.append(('DEDENT', popped_indent, line_num, line_start))
                    print(f"Added DEDENT token: {popped_indent}")
    
        elif typ == 'SKIP':
            continue
        elif typ == 'MISMATCH':
            raise RuntimeError(f'Unexpected character {value!r} on line {line_num}')
        else:
            column = match.start() - line_start
            tokens.append((typ, value, line_num, column))
            print(f"Added token: ({typ}, {value}, {line_num}, {column})")
    
    # Final dedents at end of file
    while len(indent_levels) > 1:
        popped_indent = indent_levels.pop()
        tokens.append(('DEDENT', popped_indent, line_num, line_start))
        print(f"Added final DEDENT token: {popped_indent}")
    
    print("Finished tokenizing.\n")  # Debug statement
    return tokens

# AST Node Classes with __repr__ for Debugging
class ASTNode:
    pass

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
        print("Parsing tokens into AST...")
        statements = []
        while self.pos < len(self.tokens):
            self.skip_newlines()
            if self.pos < len(self.tokens):
                statement = self.parse_statement()
                if statement:  # Only add valid statements
                    statements.append(statement)
        print("Finished parsing.\n")  # Debug statement
        return statements

    def parse_statement(self):
        token_type, value, *_ = self.peek()
        print(f"Parsing statement: token_type={token_type}, value={repr(value)}")  # Debug statement

        if token_type == 'KEYWORD' and value == 'function':
            return self.parse_function()
        elif token_type == 'KEYWORD' and value == 'return':
            self.expect('KEYWORD', 'return')
            expression = self.parse_expression()
            return ReturnNode(expression)
        elif token_type == 'IDENT':
            func_name = self.expect('IDENT')[1]
            return self.parse_function_call(func_name)
        elif token_type == 'NEWLINE':
            self.advance()  # Skip extraneous newlines
            return None
        elif token_type in {'INDENT', 'DEDENT'}:
            # Skip unexpected INDENT and DEDENT tokens outside blocks
            print(f"Skipping unexpected {token_type} with value={value}")  # Debug statement
            self.advance()
            return None
        else:
            raise SyntaxError(f"Unknown top-level statement: token_type={token_type}, value={repr(value)}")

    def parse_function(self):
        print("Parsing function definition...")  # Debug statement
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
        print(f"Created {function_node}\n")  # Debug statement
        return function_node

    def parse_block(self):
        print("Parsing block...")  # Debug statement
        statements = []
        while self.peek()[0] != 'DEDENT' and self.peek()[0] != 'EOF':
            statement = self.parse_statement()
            if statement:
                statements.append(statement)
            if self.peek()[0] == 'NEWLINE':
                self.advance()
        print(f"Parsed block: {statements}\n")  # Debug statement
        return statements

    def parse_function_call(self, name):
        print(f"Parsing function call for: {name}")  # Debug statement
        arguments = []
        while self.peek()[0] in ('NUMBER', 'IDENT'):
            arguments.append(self.parse_expression())
        function_call_node = FunctionCallNode(name, arguments)
        print(f"Created {function_call_node}\n")  # Debug statement
        return function_call_node

    def parse_expression(self):
        print("Parsing expression...")  # Debug statement
        left = self.parse_term()
        while self.peek()[0] == 'OP':
            op = self.expect('OP')[1]
            right = self.parse_term()
            left = BinaryOpNode(left, op, right)
        print(f"Parsed expression: {left}\n")  # Debug statement
        return left

    def parse_term(self):
        token_type, value, *_ = self.peek()
        print(f"Parsing term: token_type={token_type}, value={repr(value)}")  # Debug statement
        if token_type == 'NUMBER':
            self.advance()
            return NumberNode(float(value))
        elif token_type == 'IDENT':
            self.advance()
            return IdentifierNode(value)
        raise SyntaxError(f'Unexpected token: {value}')

    def skip_newlines(self):
        while self.peek()[0] == 'NEWLINE':
            self.advance()

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else ('EOF', None)

    def advance(self):
        token = self.tokens[self.pos]
        self.pos += 1
        print(f"Advanced to token: {token}")  # Debug statement
        return token

    def expect(self, token_type, value=None):
        actual_type, actual_value, *_ = self.advance()
        print(f"Expecting token: {token_type} {repr(value)}. Got: {actual_type} {repr(actual_value)}")  # Debug statement
        if actual_type != token_type or (value and actual_value != value):
            raise SyntaxError(f'Expected {token_type} {repr(value)}, got {actual_type} {repr(actual_value)}')
        return actual_type, actual_value

# Interpreter Class
class Interpreter:
    def __init__(self):
        self.environment = {}

    def interpret(self, ast):
        print("Interpreting AST...")  # Debug statement
        if isinstance(ast, FunctionNode):
            print(f"Storing function: {ast.name}\n")
            self.environment[ast.name] = ast
        elif isinstance(ast, ReturnNode):
            result = self.evaluate(ast.expression)
            print(f"ReturnNode evaluated with result: {result}\n")
            return result
        elif isinstance(ast, FunctionCallNode):
            print(f"Interpreting function call: {ast.name}")
            return self.execute_function(ast)
        else:
            print(f"Unknown AST node: {ast}\n")
            raise ValueError(f'Unknown AST node type: {ast}')

    def execute_function(self, call_node):
        func = self.environment.get(call_node.name)
        if not func:
            raise RuntimeError(f"Function {call_node.name} is not defined.")
        
        print(f"Executing function: {call_node.name} with arguments {call_node.arguments}")  # Debug statement
        saved_env = self.environment.copy()
        for param, arg in zip(func.params, call_node.arguments):
            evaluated_arg = self.evaluate(arg)
            self.environment[param] = evaluated_arg
            print(f"Set parameter '{param}' to {evaluated_arg}")  # Debug statement

        result = None
        for stmt in func.body:
            result = self.interpret(stmt)
            if result is not None:
                break

        self.environment = saved_env
        print(f"Function {call_node.name} returned {result}\n")  # Debug statement
        return result

    def evaluate(self, node):
        print(f"Evaluating node: {node}")  # Debug statement
        if isinstance(node, NumberNode):
            return node.value
        elif isinstance(node, IdentifierNode):
            value = self.environment.get(node.name, 0)
            print(f"Identifier '{node.name}' has value {value}")  # Debug statement
            return value
        elif isinstance(node, BinaryOpNode):
            left = self.evaluate(node.left)
            right = self.evaluate(node.right)
            print(f"Performing operation: {left} {node.operator} {right}")  # Debug statement
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
    if len(sys.argv) != 2:
        print("Usage: python interpreter.py <filename>.srv")
        sys.exit(1)
    
    filename = sys.argv[1]
    
    if not filename.endswith('.srv'):
        print("Error: The file must have a .srv extension.")
        sys.exit(1)
    
    if not os.path.isfile(filename):
        print(f"Error: File '{filename}' does not exist.")
        sys.exit(1)
    
    try:
        with open(filename, 'r') as file:
            code = file.read()
            print(f"Read code from {filename}:\n{code}\n")
    except Exception as e:
        print(f"Error reading file '{filename}': {e}")
        sys.exit(1)
    
    # Tokenize and parse multiple top-level statements
    tokens = list(tokenize(code))
    print("\nTokens:", tokens, "\n")  # Debug statement

    parser = Parser(tokens)
    ast_nodes = parser.parse()
    print("\nAST:", ast_nodes, "\n")  # Debug statement

    # Interpret each top-level AST node
    interpreter = Interpreter()
    result = None
    for node in ast_nodes:
        result = interpreter.interpret(node)
    
    print("\nFinal result:", result)

if __name__ == '__main__':
    main()
