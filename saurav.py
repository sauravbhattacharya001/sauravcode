"""saurav — The sauravcode language interpreter.

A complete interpreter for the sauravcode (.srv) programming language,
including tokenizer, parser, and tree-walking interpreter. Supports
functions, classes, closures, pattern matching, enums, list comprehensions,
generators, f-strings, pipe operator, imports, and comprehensive built-in
functions for strings, math, collections, file I/O, dates, and regex.

Usage:
    python saurav.py <filename>.srv [--debug]
"""

import copy
import operator
import re
import sys
import os
import math
import random
import time as _time
import contextlib
from collections import ChainMap, deque
from datetime import datetime as _datetime


class _SrvStack:
    """Stack data structure for sauravcode (LIFO)."""
    __slots__ = ('_data',)
    def __init__(self, items=None):
        self._data = list(items) if items else []
    def push(self, val):
        self._data.append(val)
    def pop(self):
        if not self._data:
            raise RuntimeError("stack_pop: stack is empty")
        return self._data.pop()
    def peek(self):
        if not self._data:
            raise RuntimeError("stack_peek: stack is empty")
        return self._data[-1]
    def size(self):
        return len(self._data)
    def is_empty(self):
        return len(self._data) == 0
    def to_list(self):
        return list(self._data)
    def clear(self):
        self._data.clear()
    def __repr__(self):
        return f"Stack({self._data})"


class _SrvQueue:
    """Queue data structure for sauravcode (FIFO)."""
    __slots__ = ('_data',)
    def __init__(self, items=None):
        self._data = deque(items) if items else deque()
    def enqueue(self, val):
        self._data.append(val)
    def dequeue(self):
        if not self._data:
            raise RuntimeError("queue_dequeue: queue is empty")
        return self._data.popleft()
    def peek(self):
        if not self._data:
            raise RuntimeError("queue_peek: queue is empty")
        return self._data[0]
    def size(self):
        return len(self._data)
    def is_empty(self):
        return len(self._data) == 0
    def to_list(self):
        return list(self._data)
    def clear(self):
        self._data.clear()
    def __repr__(self):
        return f"Queue({list(self._data)})"


class _SrvGraph:
    """Graph data structure for sauravcode (adjacency list, undirected by default)."""
    __slots__ = ('_adj', '_directed')
    def __init__(self, directed=False):
        self._adj = {}  # node -> set of (neighbor, weight)
        self._directed = directed
    def add_node(self, node):
        if node not in self._adj:
            self._adj[node] = set()
    def add_edge(self, u, v, weight=1):
        self.add_node(u)
        self.add_node(v)
        self._adj[u].add((v, weight))
        if not self._directed:
            self._adj[v].add((u, weight))
    def remove_node(self, node):
        if node not in self._adj:
            raise RuntimeError(f"graph_remove_node: node {node!r} not found")
        del self._adj[node]
        for n in self._adj:
            self._adj[n] = {(nb, w) for nb, w in self._adj[n] if nb != node}
    def remove_edge(self, u, v):
        if u not in self._adj:
            raise RuntimeError(f"graph_remove_edge: node {u!r} not found")
        self._adj[u] = {(nb, w) for nb, w in self._adj[u] if nb != v}
        if not self._directed:
            if v in self._adj:
                self._adj[v] = {(nb, w) for nb, w in self._adj[v] if nb != u}
    def has_node(self, node):
        return node in self._adj
    def has_edge(self, u, v):
        if u not in self._adj:
            return False
        return any(nb == v for nb, _ in self._adj[u])
    def neighbors(self, node):
        if node not in self._adj:
            raise RuntimeError(f"graph_neighbors: node {node!r} not found")
        return sorted([nb for nb, _ in self._adj[node]], key=lambda x: str(x))
    def nodes(self):
        return sorted(self._adj.keys(), key=lambda x: str(x))
    def edges(self):
        seen = set()
        result = []
        for u in sorted(self._adj.keys(), key=lambda x: str(x)):
            for v, w in sorted(self._adj[u], key=lambda x: str(x[0])):
                key = (u, v) if self._directed else tuple(sorted([str(u), str(v)]))
                if key not in seen:
                    seen.add(key)
                    result.append([u, v, w])
        return result
    def degree(self, node):
        if node not in self._adj:
            raise RuntimeError(f"graph_degree: node {node!r} not found")
        return len(self._adj[node])
    def bfs(self, start):
        if start not in self._adj:
            raise RuntimeError(f"graph_bfs: node {start!r} not found")
        visited = []
        seen = {start}
        queue = deque([start])
        while queue:
            node = queue.popleft()
            visited.append(node)
            for nb, _ in sorted(self._adj.get(node, set()), key=lambda x: str(x[0])):
                if nb not in seen:
                    seen.add(nb)
                    queue.append(nb)
        return visited
    def dfs(self, start):
        if start not in self._adj:
            raise RuntimeError(f"graph_dfs: node {start!r} not found")
        visited = []
        seen = set()
        stack = [start]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            visited.append(node)
            for nb, _ in sorted(self._adj.get(node, set()), key=lambda x: str(x[0]), reverse=True):
                if nb not in seen:
                    stack.append(nb)
        return visited
    def shortest_path(self, start, end):
        if start not in self._adj:
            raise RuntimeError(f"graph_shortest_path: node {start!r} not found")
        if end not in self._adj:
            raise RuntimeError(f"graph_shortest_path: node {end!r} not found")
        import heapq
        dist = {start: 0}
        prev = {start: None}
        pq = [(0, str(start), start)]
        while pq:
            d, _, node = heapq.heappop(pq)
            if node == end:
                path = []
                while node is not None:
                    path.append(node)
                    node = prev[node]
                return list(reversed(path))
            if d > dist.get(node, float('inf')):
                continue
            for nb, w in self._adj.get(node, set()):
                nd = d + w
                if nd < dist.get(nb, float('inf')):
                    dist[nb] = nd
                    prev[nb] = node
                    heapq.heappush(pq, (nd, str(nb), nb))
        return []  # no path
    def connected(self, u, v):
        if u not in self._adj or v not in self._adj:
            return False
        return v in self.bfs(u)
    def __repr__(self):
        n = len(self._adj)
        e = len(self.edges())
        kind = "Directed" if self._directed else "Undirected"
        return f"Graph({kind}, {n} nodes, {e} edges)"


class _SrvLLNode:
    """Internal node for the sauravcode doubly-linked list."""
    __slots__ = ('value', 'prev', 'next')
    def __init__(self, value, prev=None, nxt=None):
        self.value = value
        self.prev = prev
        self.next = nxt


class _SrvLinkedList:
    """Doubly-linked list data structure for sauravcode."""
    __slots__ = ('_head', '_tail', '_size')
    def __init__(self, items=None):
        self._head = None
        self._tail = None
        self._size = 0
        if items:
            for item in items:
                self.push_back(item)
    def push_front(self, val):
        node = _SrvLLNode(val, nxt=self._head)
        if self._head:
            self._head.prev = node
        self._head = node
        if self._tail is None:
            self._tail = node
        self._size += 1
    def push_back(self, val):
        node = _SrvLLNode(val, prev=self._tail)
        if self._tail:
            self._tail.next = node
        self._tail = node
        if self._head is None:
            self._head = node
        self._size += 1
    def pop_front(self):
        if not self._head:
            raise RuntimeError("ll_pop_front: list is empty")
        val = self._head.value
        self._head = self._head.next
        if self._head:
            self._head.prev = None
        else:
            self._tail = None
        self._size -= 1
        return val
    def pop_back(self):
        if not self._tail:
            raise RuntimeError("ll_pop_back: list is empty")
        val = self._tail.value
        self._tail = self._tail.prev
        if self._tail:
            self._tail.next = None
        else:
            self._head = None
        self._size -= 1
        return val
    def get(self, index):
        if index < 0 or index >= self._size:
            raise RuntimeError(f"ll_get: index {index} out of range (size {self._size})")
        node = self._head
        for _ in range(int(index)):
            node = node.next
        return node.value
    def insert_at(self, index, val):
        if index < 0 or index > self._size:
            raise RuntimeError(f"ll_insert_at: index {index} out of range (size {self._size})")
        if index == 0:
            self.push_front(val)
            return
        if index == self._size:
            self.push_back(val)
            return
        node = self._head
        for _ in range(int(index)):
            node = node.next
        new_node = _SrvLLNode(val, prev=node.prev, nxt=node)
        node.prev.next = new_node
        node.prev = new_node
        self._size += 1
    def remove_at(self, index):
        if index < 0 or index >= self._size:
            raise RuntimeError(f"ll_remove_at: index {index} out of range (size {self._size})")
        if index == 0:
            return self.pop_front()
        if index == self._size - 1:
            return self.pop_back()
        node = self._head
        for _ in range(int(index)):
            node = node.next
        val = node.value
        node.prev.next = node.next
        node.next.prev = node.prev
        self._size -= 1
        return val
    def reverse(self):
        node = self._head
        while node:
            node.prev, node.next = node.next, node.prev
            node = node.prev
        self._head, self._tail = self._tail, self._head
    def to_list(self):
        result = []
        node = self._head
        while node:
            result.append(node.value)
            node = node.next
        return result
    def size(self):
        return float(self._size)
    def is_empty(self):
        return self._size == 0
    def clear(self):
        self._head = None
        self._tail = None
        self._size = 0
    def peek_front(self):
        if not self._head:
            raise RuntimeError("ll_peek_front: list is empty")
        return self._head.value
    def peek_back(self):
        if not self._tail:
            raise RuntimeError("ll_peek_back: list is empty")
        return self._tail.value
    def __repr__(self):
        return f"LinkedList({self.to_list()})"


# Debug flag — enabled with --debug command-line argument
DEBUG = False

# Security limits to prevent denial-of-service attacks
MAX_RECURSION_DEPTH = 500      # Maximum nested function call depth
MAX_EVAL_DEPTH = 500           # Maximum expression nesting depth
MAX_LOOP_ITERATIONS = 10_000_000  # Maximum iterations per loop
MAX_ALLOC_SIZE = 10_000_000    # Maximum elements in a single allocation (list/string repeat/range)
MAX_EXPONENT = 10_000          # Maximum exponent to prevent memory exhaustion via huge integers

# ── Parser hot-path lookup sets (frozenset for O(1) membership) ──────
_FUNC_CALL_ARG_TOKENS = frozenset({
    'NUMBER', 'IDENT', 'STRING', 'FSTRING', 'LPAREN', 'LBRACKET', 'LBRACE', 'KEYWORD'
})
_ATOM_KEYWORDS = frozenset({'true', 'false', 'not', 'len', 'lambda', 'pop'})
_COMPARISON_OPS = frozenset({'EQ', 'NEQ', 'LT', 'GT', 'LTE', 'GTE'})
_PRIMARY_TOKENS = frozenset({'NUMBER', 'STRING', 'FSTRING', 'LPAREN'})
_TYPE_KEYWORDS = frozenset({'int', 'float', 'bool', 'string'})

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
    ('IDENT',    r'[a-zA-Z_]\w*'),  # Identifiers (keywords resolved via _KEYWORDS post-match)
    ('NEWLINE',  r'\n'),  # Newlines
    ('SKIP',     r'[ \t]+'),  # Whitespace
    ('MISMATCH', r'.'),  # Any other character
]

tok_regex = re.compile('|'.join(f'(?P<{pair[0]}>{pair[1]})' for pair in token_specification))
_indent_re = re.compile(r'[ \t]*')

# Keyword set for O(1) post-match reclassification.
# Replacing the 30+ alternation KEYWORD regex pattern with a frozenset lookup
# eliminates the regex engine trying every keyword branch before falling through
# to IDENT on each word token — a significant tokenizer speedup.
_KEYWORDS = frozenset({
    'function', 'return', 'class', 'int', 'float', 'bool', 'string',
    'if', 'else', 'for', 'in', 'while', 'try', 'catch', 'throw',
    'print', 'true', 'false', 'and', 'or', 'not', 'list', 'set',
    'stack', 'queue', 'append', 'len', 'pop', 'lambda', 'import',
    'match', 'case', 'enum', 'break', 'continue', 'assert', 'yield', 'next',
})

# Escape sequence mapping for string literals
_ESCAPE_MAP = {
    'n': '\n',
    't': '\t',
    'r': '\r',
    '\\': '\\',
    '"': '"',
    '0': '\0',
}

def _is_hex(c):
    """Return True if *c* is a valid hexadecimal digit."""
    return c in '0123456789abcdefABCDEF'


def process_escapes(s):
    """Process backslash escape sequences in a string literal.

    Translates \\n → newline, \\t → tab, \\r → carriage return,
    \\\\ → backslash, \\" → quote, \\0 → null,
    \\xHH → hex byte, \\uXXXX → Unicode (BMP),
    \\UXXXXXXXX → Unicode (full range).
    Unknown escape sequences (e.g. \\d) are kept verbatim
    (backslash + character), which preserves regex patterns
    and other backslash-heavy content.
    """
    if '\\' not in s:
        return s
    result = []
    i = 0
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt in _ESCAPE_MAP:
                result.append(_ESCAPE_MAP[nxt])
                i += 2
            elif nxt == 'x' and i + 3 < len(s) and all(_is_hex(s[i + j]) for j in range(2, 4)):
                result.append(chr(int(s[i + 2:i + 4], 16)))
                i += 4
            elif nxt == 'u' and i + 5 < len(s) and all(_is_hex(s[i + j]) for j in range(2, 6)):
                result.append(chr(int(s[i + 2:i + 6], 16)))
                i += 6
            elif nxt == 'U' and i + 9 < len(s) and all(_is_hex(s[i + j]) for j in range(2, 10)):
                code_point = int(s[i + 2:i + 10], 16)
                if code_point > 0x10FFFF:
                    result.append('\\')
                    result.append(nxt)
                    i += 2
                else:
                    result.append(chr(code_point))
                    i += 10
            else:
                # Unknown escape — keep both backslash and character
                result.append('\\')
                result.append(nxt)
                i += 2
        else:
            result.append(s[i])
            i += 1
    return ''.join(result)

def tokenize(code):
    """Tokenize sauravcode source into a list of (type, value, line) tuples.

    Handles indentation-based block structure by emitting INDENT/DEDENT
    tokens, similar to Python's tokenizer. Comments and whitespace are
    consumed but not emitted. Returns a flat token list ready for parsing.

    Args:
        code: Source code string to tokenize.

    Returns:
        List of (token_type, token_value, line_number) tuples.
    """
    if DEBUG:
        debug("Tokenizing code...")
    tokens = []
    line_num = 1
    line_start = 0
    indent_levels = [0]  # Track indentation levels
    
    for match in tok_regex.finditer(code):
        typ = match.lastgroup
        value = match.group(typ)
        if DEBUG:
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
                if DEBUG:
                    debug(f"Detected indentation: {indent} spaces")
                if indent > indent_levels[-1]:
                    indent_levels.append(indent)
                    tokens.append(('INDENT', indent, line_num, line_start))
                    if DEBUG:
                        debug(f"Added INDENT token: {indent}")
                while indent < indent_levels[-1]:
                    popped_indent = indent_levels.pop()
                    tokens.append(('DEDENT', popped_indent, line_num, line_start))
                    if DEBUG:
                        debug(f"Added DEDENT token: {popped_indent}")
    
        elif typ in ('SKIP', 'COMMENT'):
            continue
        elif typ == 'MISMATCH':
            raise RuntimeError(f'Unexpected character {value!r} on line {line_num}')
        else:
            # Reclassify identifiers that are keywords via O(1) set lookup.
            # This replaces the expensive 30+ alternation KEYWORD regex.
            if value in _KEYWORDS:
                typ = 'KEYWORD'
            column = match.start() - line_start
            tokens.append((typ, value, line_num, column))
            if DEBUG:
                debug(f"Added token: ({typ}, {value}, {line_num}, {column})")
    
    # Final dedents at end of file
    while len(indent_levels) > 1:
        popped_indent = indent_levels.pop()
        tokens.append(('DEDENT', popped_indent, line_num, line_start))
        if DEBUG:
            debug(f"Added final DEDENT token: {popped_indent}")

    # Merge adjacent KEYWORD('else') + KEYWORD('if') into KEYWORD('else if')
    # to preserve parser compatibility.  This is a single linear pass.
    merged = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if (tok[0] == 'KEYWORD' and tok[1] == 'else' and
                i + 1 < n and tokens[i + 1][0] == 'KEYWORD' and tokens[i + 1][1] == 'if'):
            merged.append(('KEYWORD', 'else if', tok[2], tok[3]))
            i += 2
        else:
            merged.append(tok)
            i += 1
    tokens = merged
    
    if DEBUG:
        debug("Finished tokenizing.\n")
    return tokens

# AST Node Classes with __repr__ for Debugging
class ASTNode:
    """Base class for all Abstract Syntax Tree nodes.

    Every node in the parsed AST inherits from this class. The optional
    ``line_num`` attribute tracks the source line for error reporting
    and debugger integration.
    """
    line_num = None  # Source line number (optionally set by debugger/tooling)

class AssignmentNode(ASTNode):
    """Variable assignment: ``name = expression``."""
    def __init__(self, name, expression):
        self.name = name
        self.expression = expression

    def __repr__(self):
        return f"AssignmentNode(name={self.name}, expression={self.expression})"

class FunctionNode(ASTNode):
    """Function definition: ``function name(params) body``."""
    def __init__(self, name, params, body):
        self.name = name
        self.params = params
        self.body = body

    def __repr__(self):
        return f"FunctionNode(name={self.name}, params={self.params}, body={self.body})"


class _BoundFunction(FunctionNode):
    """Lightweight wrapper binding a FunctionNode to a closure scope.

    Replaces the ``copy.copy(func_node)`` + attribute-set pattern in
    ``_eval_identifier``.  Using ``__slots__`` and direct attribute
    delegation avoids the overhead of shallow-copying the entire
    FunctionNode (which triggers ``__init__`` introspection, copies
    all attributes, and allocates a new dict).  On CPython 3.11+
    this is ~3x faster per function-as-value reference.
    """
    __slots__ = ('_func', 'closure_scope', '_is_generator')

    def __init__(self, func_node, closure_scope):
        # Skip FunctionNode.__init__ — copy attributes directly
        self.name = func_node.name
        self.params = func_node.params
        self.body = func_node.body
        self._func = func_node
        self.closure_scope = closure_scope
        self._is_generator = getattr(func_node, '_is_generator', False)
        self.line_num = getattr(func_node, 'line_num', None)

class ReturnNode(ASTNode):
    """Return statement: ``return expression``."""
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
    """Binary arithmetic operation: ``left operator right`` (+, -, *, /, %)."""
    def __init__(self, left, operator, right):
        self.left = left
        self.operator = operator
        self.right = right

    def __repr__(self):
        return f"BinaryOpNode(left={self.left}, operator='{self.operator}', right={self.right})"

class NumberNode(ASTNode):
    """Numeric literal (integer or float)."""
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"NumberNode(value={self.value})"

class StringNode(ASTNode):
    """String literal with escape sequence support."""
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"StringNode(value={self.value!r})"

class IdentifierNode(ASTNode):
    """Variable or function name reference."""
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"IdentifierNode(name={self.name})"

class PrintNode(ASTNode):
    """Print statement: ``print expression``."""
    def __init__(self, expression):
        self.expression = expression

    def __repr__(self):
        return f"PrintNode(expression={self.expression})"

class FunctionCallNode(ASTNode):
    """Function call: ``name(arguments)`` or built-in call."""
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
    """Boolean literal: ``true`` or ``false``."""
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"BoolNode(value={self.value})"

class IfNode(ASTNode):
    """Conditional: ``if condition body [else if ... else ...]``."""
    def __init__(self, condition, body, elif_chains=None, else_body=None):
        self.condition = condition
        self.body = body
        self.elif_chains = elif_chains or []
        self.else_body = else_body

    def __repr__(self):
        return f"IfNode(condition={self.condition}, body={self.body})"

class WhileNode(ASTNode):
    """While loop: ``while condition body``."""
    def __init__(self, condition, body):
        self.condition = condition
        self.body = body

    def __repr__(self):
        return f"WhileNode(condition={self.condition}, body={self.body})"

class ForNode(ASTNode):
    """Range-based for loop: ``for var in start to end body``."""
    def __init__(self, var, start, end, body):
        self.var = var
        self.start = start
        self.end = end
        self.body = body

    def __repr__(self):
        return f"ForNode(var={self.var}, start={self.start}, end={self.end})"

class ListNode(ASTNode):
    """List literal: ``[elem1, elem2, ...]``."""
    def __init__(self, elements):
        self.elements = elements

    def __repr__(self):
        return f"ListNode(elements={self.elements})"

class IndexNode(ASTNode):
    """Index access: ``obj[index]``."""
    def __init__(self, obj, index):
        self.obj = obj
        self.index = index

    def __repr__(self):
        return f"IndexNode(obj={self.obj}, index={self.index})"

class AppendNode(ASTNode):
    """Append to a list: ``append(list_name, value)``."""
    def __init__(self, list_name, value):
        self.list_name = list_name
        self.value = value

    def __repr__(self):
        return f"AppendNode(list_name={self.list_name}, value={self.value})"

class PopNode(ASTNode):
    """Pop from a list: ``pop(list_name)``."""
    def __init__(self, list_name):
        self.list_name = list_name

    def __repr__(self):
        return f"PopNode(list_name={self.list_name})"

class LenNode(ASTNode):
    """Length of a collection or string: ``len(expression)``."""
    def __init__(self, expression):
        self.expression = expression

    def __repr__(self):
        return f"LenNode(expression={self.expression})"

class MapNode(ASTNode):
    """Map (dictionary) literal: ``{key: value, ...}``."""
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
    """Recursive-descent parser for sauravcode.

    Converts a flat token list from ``tokenize()`` into an Abstract Syntax
    Tree (AST). Handles indentation-based blocks (INDENT/DEDENT tokens),
    operator precedence, and all language constructs including functions,
    classes, control flow, pattern matching, enums, and comprehensions.

    Args:
        tokens: List of (type, value, line) tuples from the tokenizer.
    """
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
        'factorial', 'gcd', 'lcm', 'is_prime', 'prime_factors',
        'fibonacci', 'modpow', 'divisors',
        'http_get', 'http_post', 'http_put', 'http_delete',
        'bit_and', 'bit_or', 'bit_xor', 'bit_not', 'bit_lshift', 'bit_rshift',
        'group_by', 'take_while', 'drop_while', 'scan', 'zip_with',
        'str_reverse', 'str_chars', 'str_title', 'str_is_digit', 'str_is_alpha',
        'str_is_alnum', 'str_words', 'str_slug', 'str_count', 'str_wrap', 'str_center',
        'sets_create', 'sets_add', 'sets_remove', 'sets_contains',
        'sets_union', 'sets_intersection', 'sets_difference', 'sets_symmetric_diff',
        'sets_size', 'sets_to_list', 'sets_is_subset', 'sets_is_superset',
        'stack_create', 'stack_push', 'stack_pop', 'stack_peek',
        'stack_size', 'stack_is_empty', 'stack_to_list', 'stack_clear',
        'queue_create', 'queue_enqueue', 'queue_dequeue', 'queue_peek',
        'queue_size', 'queue_is_empty', 'queue_to_list', 'queue_clear',
        'deque_create', 'deque_push_front', 'deque_push_back',
        'deque_pop_front', 'deque_pop_back', 'deque_peek_front', 'deque_peek_back',
        'deque_size', 'deque_is_empty', 'deque_to_list', 'deque_rotate', 'deque_clear',
        'interval_create', 'interval_contains', 'interval_overlaps',
        'interval_merge', 'interval_intersection', 'interval_gap',
        'interval_span', 'interval_width', 'interval_to_list',
        'interval_merge_all',
        'path_join', 'path_dir', 'path_base', 'path_ext', 'path_stem',
        'path_abs', 'path_exists', 'list_dir', 'make_dir', 'is_dir', 'is_file',
        'sort_by', 'min_by', 'max_by', 'partition', 'rotate',
        'interleave', 'frequencies', 'combinations', 'permutations',
        'env_get', 'env_set', 'env_unset', 'env_list', 'env_has',
        'sys_exit', 'sys_args', 'sys_platform', 'sys_cwd', 'sys_pid',
        'sys_uptime', 'sys_hostname',
        'color', 'bg_color', 'bold', 'dim', 'italic', 'underline',
        'strikethrough', 'style', 'rainbow', 'strip_ansi',
        'uuid_v4', 'random_bytes', 'random_hex', 'random_string', 'random_float',
        'csv_parse', 'csv_stringify', 'csv_headers', 'csv_select', 'csv_filter',
        'csv_sort', 'csv_read', 'csv_write',
        'is_email', 'is_url', 'is_ipv4', 'is_ipv6', 'is_ip',
        'is_date', 'is_uuid', 'is_hex_color', 'is_phone',
        'is_credit_card', 'is_json', 'validate',
        'cache_create', 'cache_get', 'cache_set', 'cache_clear',
        'cache_has', 'cache_keys', 'cache_size', 'cache_delete',
        'cache_values', 'cache_entries',
        'color_rgb', 'color_hex', 'color_hsl', 'color_blend',
        'color_lighten', 'color_darken', 'color_invert', 'color_contrast',
        'color_to_rgb', 'color_to_hex', 'color_to_hsl',
        're_test', 're_match', 're_search', 're_find_all',
        're_replace', 're_split', 're_escape',
        'graph_create', 'graph_add_node', 'graph_add_edge', 'graph_neighbors',
        'graph_nodes', 'graph_edges', 'graph_has_node', 'graph_has_edge',
        'graph_degree', 'graph_remove_node', 'graph_remove_edge',
        'graph_bfs', 'graph_dfs', 'graph_shortest_path', 'graph_connected',
        'json_encode', 'json_decode', 'json_pretty', 'json_get',
        'json_set', 'json_delete', 'json_keys', 'json_values',
        'json_has', 'json_merge', 'json_flatten', 'json_query',
        'heap_create', 'heap_push', 'heap_pop', 'heap_peek',
        'heap_size', 'heap_is_empty', 'heap_to_list', 'heap_clear',
        'heap_merge', 'heap_push_pop', 'heap_replace',
        'trie_create', 'trie_insert', 'trie_search', 'trie_starts_with',
        'trie_delete', 'trie_autocomplete', 'trie_size', 'trie_words',
        'trie_longest_prefix', 'trie_count_prefix',
        'll_create', 'll_push_front', 'll_push_back', 'll_pop_front', 'll_pop_back',
        'll_get', 'll_insert_at', 'll_remove_at', 'll_size', 'll_is_empty',
        'll_to_list', 'll_reverse', 'll_clear', 'll_peek_front', 'll_peek_back',
        'll_from_list',
        'bloom_create', 'bloom_add', 'bloom_contains', 'bloom_size',
        'bloom_clear', 'bloom_false_positive_rate', 'bloom_merge',
        'bloom_info',
        'http_get', 'http_post', 'url_parse', 'url_encode', 'url_decode',
        'base64_encode', 'base64_decode',
        'compress', 'decompress', 'gzip_compress', 'gzip_decompress',
        'compress_ratio',
        'log_info', 'log_warn', 'log_error', 'log_debug',
        'log_to_file', 'log_clear', 'log_history',
        'perf_start', 'perf_stop', 'perf_elapsed',
        'table_create', 'table_add_row', 'table_headers', 'table_print',
        'table_sort', 'table_filter', 'table_to_csv', 'table_to_json',
        'table_column', 'table_size', 'table_row', 'table_reverse',
        'omap_create', 'omap_set', 'omap_get', 'omap_delete',
        'omap_has', 'omap_size', 'omap_keys', 'omap_values',
        'omap_entries', 'omap_min', 'omap_max', 'omap_range',
        'omap_floor', 'omap_ceil', 'omap_to_map', 'omap_clear',
        'fsm_create', 'fsm_add_state', 'fsm_add_transition', 'fsm_set_start',
        'fsm_transition', 'fsm_current', 'fsm_is_accepting', 'fsm_reset',
        'fsm_states', 'fsm_transitions', 'fsm_run', 'fsm_accepts',
        'ring_create', 'ring_push', 'ring_peek', 'ring_pop',
        'ring_size', 'ring_capacity', 'ring_is_empty', 'ring_is_full',
        'ring_to_list', 'ring_clear', 'ring_get',
        'caesar_encrypt', 'caesar_decrypt', 'rot13',
        'vigenere_encrypt', 'vigenere_decrypt',
        'xor_cipher', 'atbash', 'morse_encode', 'morse_decode',
        'md5', 'sha1', 'sha256', 'sha512', 'crc32', 'hmac_sha256',
        # Binary pack/unpack
        'pack', 'unpack', 'pack_size', 'pack_formats',
        # Event emitter (pub/sub)
        'emitter_create', 'emitter_on', 'emitter_once', 'emitter_emit',
        'emitter_off', 'emitter_listeners', 'emitter_clear', 'emitter_count',
    })

    # Builtins that take zero arguments — auto-called when used standalone
    ZERO_ARG_BUILTINS = frozenset({'now', 'timestamp', 'pi', 'euler',
        'sys_args', 'sys_platform', 'sys_cwd', 'sys_pid', 'sys_uptime', 'sys_hostname',
        'env_list', 'uuid_v4', 'random_float',
        'stack_create', 'queue_create', 'cache_create', 'graph_create', 'heap_create', 'trie_create',
        'll_create', 'bloom_create', 'deque_create',
        'log_clear', 'table_create', 'omap_create', 'fsm_create',
        'pack_formats', 'emitter_create'})

    # ── Keyword dispatch table for _parse_statement_inner ──────────
    # Maps keyword values to method names. Methods that need special
    # inline logic (return, yield, print, break, continue) use small
    # wrapper lambdas defined in _parse_statement_inner; the rest are
    # direct method references initialised once in __init__.

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0
        self._keyword_dispatch = {
            'function': self.parse_function,
            'import':   self.parse_import,
            'if':       self.parse_if,
            'while':    self.parse_while,
            'for':      self.parse_for,
            'try':      self.parse_try_catch,
            'throw':    self.parse_throw,
            'match':    self.parse_match,
            'enum':     self.parse_enum,
            'assert':   self.parse_assert,
            'append':   self.parse_append,
            'pop':      self.parse_pop,
            'return':   self._parse_return,
            'yield':    self._parse_yield,
            'print':    self._parse_print,
            'break':    self._parse_break,
            'continue': self._parse_continue,
        }

    def _current_line(self):
        """Return the line number of the current token, or None."""
        if self.pos < len(self.tokens) and len(self.tokens[self.pos]) >= 3:
            return self.tokens[self.pos][2]
        return None

    def _tag(self, node):
        """Attach the current source line number to an AST node and return it."""
        line = self._current_line()
        if line is not None:
            node.line_num = line
        return node

    def parse(self):
        if DEBUG:
            debug("Parsing tokens into AST...")
        statements = []
        while self.pos < len(self.tokens):
            self.skip_newlines()
            if self.pos < len(self.tokens):
                statement = self.parse_statement()
                if statement:  # Only add valid statements
                    statements.append(statement)
        if DEBUG:
            debug("Finished parsing.\n")
        return statements

    def parse_statement(self):
        line = self._current_line()
        node = self._parse_statement_inner()
        if isinstance(node, ASTNode) and node.line_num is None and line is not None:
            node.line_num = line
        return node

    def _parse_return(self):
        """Parse ``return <expression>``."""
        self.expect('KEYWORD', 'return')
        return ReturnNode(self.parse_full_expression())

    def _parse_yield(self):
        """Parse ``yield <expression>``."""
        self.expect('KEYWORD', 'yield')
        return YieldNode(self.parse_full_expression())

    def _parse_print(self):
        """Parse ``print <expression>``."""
        self.expect('KEYWORD', 'print')
        return PrintNode(self.parse_full_expression())

    def _parse_break(self):
        """Parse ``break``."""
        self.advance()
        return BreakNode()

    def _parse_continue(self):
        """Parse ``continue``."""
        self.advance()
        return ContinueNode()

    def _parse_statement_inner(self):
        token_type, value, *_ = self.peek()
        if DEBUG:
            debug(f"Parsing statement: token_type={token_type}, value={repr(value)}")

        # O(1) keyword dispatch — replaces long if/elif chain
        if token_type == 'KEYWORD':
            handler = self._keyword_dispatch.get(value)
            if handler is not None:
                return handler()
            # Skip type annotation keywords (int, float, bool, string)
            if value in _TYPE_KEYWORDS:
                self.advance()
                return None

        if token_type == 'IDENT':
            name = self.expect('IDENT')[1]
            if self.peek()[0] == 'ASSIGN':
                self.expect('ASSIGN')
                expression = self.parse_full_expression()
                if DEBUG:
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
            if DEBUG:
                debug(f"Skipping unexpected {token_type} with value={value}")
            self.advance()
            return None
        else:
            raise SyntaxError(f"Unknown top-level statement: token_type={token_type}, value={repr(value)}")

    def parse_function(self):
        if DEBUG:
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
        if DEBUG:
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
        if DEBUG:
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
        if DEBUG:
            debug(f"Created {lambda_node}\n")
        return lambda_node

    def parse_if(self):
        if DEBUG:
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
        if DEBUG:
            debug("Parsing while statement...")
        self.expect('KEYWORD', 'while')
        condition = self.parse_full_expression()
        self.expect('NEWLINE')
        self.expect('INDENT')
        body = self.parse_block()
        self.expect('DEDENT')
        return WhileNode(condition, body)

    def parse_for(self):
        if DEBUG:
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
        if DEBUG:
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
        if DEBUG:
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
        if DEBUG:
            debug("Parsing assert statement...")
        self.expect('KEYWORD', 'assert')
        condition = self.parse_full_expression()
        # Check for optional string message
        message = None
        if self.pos < len(self.tokens):
            next_tok = self.peek()
            if next_tok[0] == 'STRING':
                message = StringNode(process_escapes(self.advance()[1][1:-1]))
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
        if DEBUG:
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
        if DEBUG:
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
        if DEBUG:
            debug(f"Parsed enum: {name} with variants {variants}")
        return EnumNode(name, variants)

    def parse_import(self):
        """Parse import statement: import "module_name" """
        if DEBUG:
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

    def parse_pop(self):
        self.expect('KEYWORD', 'pop')
        list_name = self.expect('IDENT')[1]
        return PopNode(list_name)

    def parse_block(self):
        if DEBUG:
            debug("Parsing block...")
        statements = []
        while self.peek()[0] != 'DEDENT' and self.peek()[0] != 'EOF':
            statement = self.parse_statement()
            if statement:
                statements.append(statement)
            while self.peek()[0] == 'NEWLINE':
                self.advance()
        if DEBUG:
            debug(f"Parsed block: {statements}\n")
        return statements

    def parse_function_call(self, name):
        if DEBUG:
            debug(f"Parsing function call for: {name}")
        arguments = []
        while self.peek()[0] in _FUNC_CALL_ARG_TOKENS:
            pk = self.peek()
            if pk[0] == 'KEYWORD' and pk[1] in _ATOM_KEYWORDS:
                arguments.append(self.parse_atom())
            elif pk[0] == 'KEYWORD':
                break  # Don't consume control flow keywords as arguments
            else:
                arguments.append(self.parse_atom())
        function_call_node = FunctionCallNode(name, arguments)
        if DEBUG:
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
        if self.peek()[0] in _COMPARISON_OPS:
            _, op_val, *_ = self.advance()
            right = self.parse_expression()
            return CompareNode(left, op_val, right)
        return left

    def parse_expression(self):
        line = self._current_line()
        if DEBUG:
            debug("Parsing expression...")
        left = self.parse_term_mul()
        while self.peek()[0] == 'OP' and self.peek()[1] in ('+', '-'):
            op = self.expect('OP')[1]
            right = self.parse_term_mul()
            left = BinaryOpNode(left, op, right)
        if DEBUG:
            debug(f"Parsed expression: {left}\n")
        if isinstance(left, ASTNode) and left.line_num is None and line is not None:
            left.line_num = line
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
        if DEBUG:
            debug(f"Parsing atom: token_type={token_type}, value={repr(value)}")

        if token_type == 'NUMBER':
            self.advance()
            number_node = NumberNode(float(value))
            if DEBUG:
                debug(f"parse_atom returning NumberNode: {number_node}")
            return number_node
        elif token_type == 'STRING':
            self.advance()
            string_node = StringNode(process_escapes(value[1:-1]))
            if DEBUG:
                debug(f"parse_atom returning StringNode: {string_node}")
            return string_node
        elif token_type == 'FSTRING':
            self.advance()
            fstring_node = self.parse_fstring(value)
            if DEBUG:
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
        elif token_type == 'KEYWORD' and value == 'pop':
            self.advance()
            list_name = self.expect('IDENT')[1]
            return PopNode(list_name)
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
            if pk[0] in _PRIMARY_TOKENS:
                func_call = self.parse_function_call(value)
                if DEBUG:
                    debug(f"parse_atom returning FunctionCallNode: {func_call}")
                return func_call
            elif pk[0] == 'IDENT':
                func_call = self.parse_function_call(value)
                if DEBUG:
                    debug(f"parse_atom returning FunctionCallNode: {func_call}")
                return func_call
            elif pk[0] == 'KEYWORD' and pk[1] in _ATOM_KEYWORDS:
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
                if DEBUG:
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
                # Handle escape sequences (same mapping as regular strings)
                nxt = content[i + 1]
                if nxt in _ESCAPE_MAP:
                    text_buf.append(_ESCAPE_MAP[nxt])
                    i += 2
                elif nxt == 'x' and i + 3 < len(content) and all(_is_hex(content[i + j]) for j in range(2, 4)):
                    text_buf.append(chr(int(content[i + 2:i + 4], 16)))
                    i += 4
                elif nxt == 'u' and i + 5 < len(content) and all(_is_hex(content[i + j]) for j in range(2, 6)):
                    text_buf.append(chr(int(content[i + 2:i + 6], 16)))
                    i += 6
                elif nxt == 'U' and i + 9 < len(content) and all(_is_hex(content[i + j]) for j in range(2, 10)):
                    code_point = int(content[i + 2:i + 10], 16)
                    if code_point > 0x10FFFF:
                        text_buf.append('\\')
                        text_buf.append(nxt)
                        i += 2
                    else:
                        text_buf.append(chr(code_point))
                        i += 10
                else:
                    # Unknown escape — keep both backslash and character
                    text_buf.append('\\')
                    text_buf.append(nxt)
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
                # Find matching closing brace, skipping over string literals
                depth = 1
                j = i + 1
                while j < len(content) and depth > 0:
                    c = content[j]
                    if c in ('"', "'"):
                        # Skip over quoted string inside expression
                        quote = c
                        j += 1
                        while j < len(content):
                            if content[j] == '\\' and j + 1 < len(content):
                                j += 2
                                continue
                            if content[j] == quote:
                                j += 1
                                break
                            j += 1
                        continue
                    if c == '{':
                        depth += 1
                    elif c == '}':
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
        if DEBUG:
            debug(f"Advanced to token: {token}")
        return token

    def expect(self, token_type, value=None):
        actual_type, actual_value, *_ = self.advance()
        if DEBUG:
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

class SauravRuntimeError(RuntimeError):
    """Runtime error with source location info for better diagnostics.

    Wraps standard RuntimeError to include the .srv source line number
    and optional filename so users can quickly locate the error.
    """
    def __init__(self, message, line=None, filename=None):
        self.line = line
        self.filename = filename
        if line is not None:
            loc = f"line {line}"
            if filename:
                loc += f" in {filename}"
            super().__init__(f"{loc}: {message}")
        else:
            super().__init__(str(message))
        self.original_message = str(message)

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
    """Tree-walking interpreter for sauravcode ASTs.

    Evaluates an AST produced by the Parser. Maintains a scope chain
    (via ``ChainMap``) for variables and functions, supports closures,
    classes with methods, generators, and 80+ built-in functions for
    strings, math, collections, file I/O, dates, regex, and more.

    Includes DoS guards (recursion depth, loop iteration, and allocation
    limits) to prevent runaway programs.
    """

    # ── Class-level operator dispatch tables (static mappings, no per-instance alloc) ──
    _BINARY_OP_DISPATCH = {
        '+': operator.add,
        '-': operator.sub,
        '*': operator.mul,
        '/': operator.truediv,
        '%': operator.mod,
    }
    # Numeric-only dispatch with inline zero-checks for / and %.
    # +, -, * go straight to the C-level operator with no branch overhead.
    @staticmethod
    def _safe_div(a, b):
        if b == 0:
            raise RuntimeError("Division by zero")
        return a / b

    @staticmethod
    def _safe_mod(a, b):
        if b == 0:
            raise RuntimeError("Modulo by zero")
        return a % b

    _NUMERIC_OP_DISPATCH = {
        '+': operator.add,
        '-': operator.sub,
        '*': operator.mul,
        '/': _safe_div.__func__,
        '%': _safe_mod.__func__,
    }
    _COMPARE_OP_DISPATCH = {
        '==': operator.eq,
        '!=': operator.ne,
        '<':  operator.lt,
        '>':  operator.gt,
        '<=': operator.le,
        '>=': operator.ge,
    }

    def __init__(self):
        self.functions = {}  # Store function definitions
        self.variables = {}  # Store variable values
        self.enums = {}      # Store enum definitions: {name: {VARIANT: value, ...}}
        self._call_depth = 0  # Track recursion depth for DoS protection
        self._eval_depth = 0  # Track expression nesting depth for DoS protection
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
            PopNode:                self._interp_pop,
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
            PopNode:          self._eval_pop,
            MapNode:           self._eval_map,
            FStringNode:      self._eval_fstring,
            LambdaNode:       self._eval_lambda,
            PipeNode:         self._eval_pipe,
            EnumAccessNode:   self._eval_enum_access,
            TernaryNode:      self._eval_ternary,
        }

        # Operator dispatch tables are class-level constants
        # (_BINARY_OP_DISPATCH and _COMPARE_OP_DISPATCH) — no per-instance
        # allocation needed since they only reference pure operator functions.

    @staticmethod
    def _type_name(value):
        """Return a human-friendly type name for error messages.

        Centralizes the isinstance-chain type naming that was previously
        duplicated in _eval_binary_op and _eval_compare.
        """
        if isinstance(value, str):
            return 'string'
        if isinstance(value, list):
            return 'list'
        if isinstance(value, bool):
            return 'bool'
        if isinstance(value, dict):
            return 'map'
        if isinstance(value, set):
            return 'set'
        if isinstance(value, (int, float)):
            return 'number'
        return type(value).__name__

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
            'date_format':    self._builtin_date_format,
            'date_part':      self._builtin_date_part,
            'date_add':       self._builtin_date_add,
            'date_diff':      self._builtin_date_diff,
            'date_compare':   self._builtin_date_compare,
            'date_range':     self._builtin_date_range,
            'sleep':          self._builtin_sleep,
            # --- Math constants (trig via _register_math_builtins) ---
            # pi, euler registered via _register_zero_arg_builtins()
            # sin, cos, tan, log10 are registered via _register_math_builtins()
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
            'group_by':       self._builtin_group_by,
            'take_while':     self._builtin_take_while,
            'drop_while':     self._builtin_drop_while,
            'scan':           self._builtin_scan,
            'zip_with':       self._builtin_zip_with,
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
            # --- Hash & encoding (md5/sha256/sha1/crc32/url_encode/hex_encode/url_decode
            #     registered via _register_hash_builtins; these 3 have special error handling) ---
            'base64_encode':  self._builtin_base64_encode,
            'base64_decode':  self._builtin_base64_decode,
            'hex_decode':     self._builtin_hex_decode,
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
            # --- Number theory ---
            'factorial':      self._builtin_factorial,
            'gcd':            self._builtin_gcd,
            'lcm':            self._builtin_lcm,
            'is_prime':       self._builtin_is_prime,
            'prime_factors':  self._builtin_prime_factors,
            'fibonacci':      self._builtin_fibonacci,
            'modpow':         self._builtin_modpow,
            'divisors':       self._builtin_divisors,
            # --- Generator functions ---
            'collect':        self._builtin_collect,
            'is_generator':   self._builtin_is_generator,
            # --- HTTP functions ---
            'http_get':       self._builtin_http_get,
            'http_post':      self._builtin_http_post,
            'http_put':       self._builtin_http_put,
            'http_delete':    self._builtin_http_delete,
        }
        self._register_math_builtins()
        self._register_zero_arg_builtins()
        self._register_hash_builtins()
        self._register_bitwise_builtins()
        self._register_string_builtins()
        self._register_env_sys_builtins()
        self._register_ansi_builtins()
        self._register_random_data_builtins()
        self._register_csv_builtins()
        self._register_validation_builtins()
        self._register_cache_builtins()
        self._register_color_builtins()
        self._register_regex_builtins()
        self._register_heap_builtins()
        self._register_linkedlist_builtins()
        self._register_bloom_builtins()
        self._register_deque_builtins()
        self._register_interval_builtins()
        self._register_compression_builtins()
        self._register_logging_builtins()
        self._register_omap_builtins()
        self._register_fsm_builtins()
        self._register_cipher_builtins()
        # NOTE: _register_hash_builtins already called above; removed duplicate call
        self._register_pack_builtins()
        self._register_emitter_builtins()
        self._register_plot_builtins()

    def _register_plot_builtins(self):
        """Register ASCII plotting builtins (plot_bar, plot_line, etc.)."""
        try:
            from sauravplot import register_plot_builtins
            register_plot_builtins(self.builtins)
        except ImportError:
            pass  # sauravplot not available

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

    # ── Data-driven zero-arg builtins ────────────────────

    def _register_zero_arg_builtins(self):
        """Register builtins that take no arguments and return a value.

        Eliminates boilerplate for functions like ``now()``, ``pi()``,
        ``timestamp()``, and ``euler()`` that all share the same
        pattern: reject any arguments, return a constant or call.
        """
        _ZERO_ARG_TABLE = {
            'now':       lambda: _datetime.now().isoformat(),
            'timestamp': lambda: _time.time(),
            'pi':        lambda: math.pi,
            'euler':     lambda: math.e,
        }
        for name, fn in _ZERO_ARG_TABLE.items():
            def make_handler(n, f):
                def handler(self_inner, args):
                    if len(args) != 0:
                        raise RuntimeError(f"{n} expects 0 arguments")
                    return f()
                return handler
            h = make_handler(name, fn)
            self.builtins[name] = lambda args, h=h: h(self, args)

    # ── Data-driven hash & encoding builtins ──────────

    def _register_hash_builtins(self):
        """Register hash/encoding builtins via a data-driven table.

        All these functions take a single string argument (auto-coercing
        non-strings via ``str()``), encode to UTF-8, and apply a
        transform.  This eliminates ~70 lines of near-identical methods.
        """
        import hashlib, binascii
        from urllib.parse import quote, unquote

        # Simple transforms: coerce to str, encode, apply fn
        _HASH_TABLE = {
            'md5':           lambda s: hashlib.md5(s.encode('utf-8')).hexdigest(),
            'sha256':        lambda s: hashlib.sha256(s.encode('utf-8')).hexdigest(),
            'sha1':          lambda s: hashlib.sha1(s.encode('utf-8')).hexdigest(),
            'crc32':         lambda s: float(binascii.crc32(s.encode('utf-8')) & 0xFFFFFFFF),
            'url_encode':    lambda s: quote(s, safe=''),
            'hex_encode':    lambda s: s.encode('utf-8').hex(),
        }
        for name, fn in _HASH_TABLE.items():
            def make_handler(n, f):
                def handler(self_inner, args):
                    self_inner._expect_args(n, args, 1)
                    s = args[0]
                    if not isinstance(s, str):
                        s = str(s)
                    return f(s)
                return handler
            h = make_handler(name, fn)
            self.builtins[name] = lambda args, h=h: h(self, args)

        # url_decode: coerce to str (no auto-str), just unquote
        def _url_decode(self_inner, args):
            self_inner._expect_args('url_decode', args, 1)
            s = args[0]
            if not isinstance(s, str):
                raise RuntimeError("url_decode expects a string argument")
            return unquote(s)
        self.builtins['url_decode'] = lambda args: _url_decode(self, args)

    # ── Data-driven bitwise builtins ─────────────────

    def _register_bitwise_builtins(self):
        """Register bitwise operation builtins.

        Provides bit_and, bit_or, bit_xor (2-arg), bit_not (1-arg),
        bit_lshift, bit_rshift (2-arg) for integer bitwise operations.
        """
        def _require_int(name, val):
            if not isinstance(val, (int, float)):
                raise RuntimeError(f"{name} expects integer arguments")
            if isinstance(val, float) and val != int(val):
                raise RuntimeError(f"{name} expects integer arguments, got float {val}")
            return int(val)

        _TWO_ARG_TABLE = {
            'bit_and':    lambda a, b: a & b,
            'bit_or':     lambda a, b: a | b,
            'bit_xor':    lambda a, b: a ^ b,
            'bit_lshift': lambda a, b: a << b,
            'bit_rshift': lambda a, b: a >> b,
        }
        for name, fn in _TWO_ARG_TABLE.items():
            def make_handler(n, f):
                def handler(self_inner, args):
                    self_inner._expect_args(n, args, 2)
                    a = _require_int(n, args[0])
                    b = _require_int(n, args[1])
                    if n in ('bit_lshift', 'bit_rshift') and (b < 0 or b > 64):
                        raise RuntimeError(f"{n}: shift amount must be 0-64, got {b}")
                    return float(f(a, b))
                return handler
            h = make_handler(name, fn)
            self.builtins[name] = lambda args, h=h: h(self, args)

        # bit_not: 1-arg
        def _bit_not(self_inner, args):
            self_inner._expect_args('bit_not', args, 1)
            a = _require_int('bit_not', args[0])
            return float(~a)
        self.builtins['bit_not'] = lambda args: _bit_not(self, args)

    # ── Data-driven advanced string builtins ─────────────────

    def _register_string_builtins(self):
        """Register advanced string manipulation builtins.

        Extends the existing string library with:
        - str_reverse: reverse a string
        - str_chars: split into character list
        - str_count: count substring occurrences
        - str_title: title-case a string
        - str_center: center-pad a string
        - str_is_digit: check if all digits
        - str_is_alpha: check if all alphabetic
        - str_is_alnum: check if all alphanumeric
        - str_words: split by whitespace into word list
        - str_slug: convert to URL-friendly slug
        - str_wrap: word-wrap at a given column width
        """
        import re as _re
        import textwrap as _textwrap

        # -- 1-arg string builtins --
        _ONE_ARG_TABLE = {
            'str_reverse':  lambda s: s[::-1],
            'str_chars':    lambda s: list(s),
            'str_title':    lambda s: s.title(),
            'str_is_digit': lambda s: len(s) > 0 and s.isdigit(),
            'str_is_alpha': lambda s: len(s) > 0 and s.isalpha(),
            'str_is_alnum': lambda s: len(s) > 0 and s.isalnum(),
            'str_words':    lambda s: s.split(),
            'str_slug':     lambda s: _re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-'),
        }
        for name, fn in _ONE_ARG_TABLE.items():
            def make_handler(n, f):
                def handler(self_inner, args):
                    self_inner._expect_args(n, args, 1)
                    s = args[0]
                    if not isinstance(s, str):
                        raise RuntimeError(f"{n} expects a string argument, got {type(s).__name__}")
                    return f(s)
                return handler
            h = make_handler(name, fn)
            self.builtins[name] = lambda args, h=h: h(self, args)

        # -- 2-arg string builtins --
        def _str_count(self_inner, args):
            self_inner._expect_args('str_count', args, 2)
            s, sub = args
            if not isinstance(s, str) or not isinstance(sub, str):
                raise RuntimeError("str_count expects two string arguments")
            return float(s.count(sub))

        def _str_wrap(self_inner, args):
            self_inner._expect_args('str_wrap', args, 2)
            s, width = args
            if not isinstance(s, str):
                raise RuntimeError("str_wrap expects a string as first argument")
            width = int(width)
            if width < 1 or width > 10000:
                raise RuntimeError(f"str_wrap: width must be 1-10000, got {width}")
            return _textwrap.fill(s, width=width)

        _TWO_ARG_BUILTINS = {
            'str_count': _str_count,
            'str_wrap':  _str_wrap,
        }
        for name, fn in _TWO_ARG_BUILTINS.items():
            self.builtins[name] = lambda args, f=fn: f(self, args)

        # -- 3-arg: str_center(s, width, fill) --
        def _str_center(self_inner, args):
            self_inner._expect_args('str_center', args, 3)
            s, width, fill = args
            if not isinstance(s, str):
                raise RuntimeError("str_center expects a string as first argument")
            width = int(width)
            if not isinstance(fill, str) or len(fill) != 1:
                raise RuntimeError("str_center expects a single fill character as third argument")
            return s.center(width, fill)

        self.builtins['str_center'] = lambda args: _str_center(self, args)

        # ── Set data structure builtins ──────────────────

        # Sets are represented as Python frozensets internally.
        # Users create them from lists and get lists back.

        # ── Data-driven set builtins ─────────────────────────
        # sets_create and sets_add/sets_remove have special logic, but
        # the 7 two-set-arg operators and 2 one-set-arg helpers collapse
        # into compact tables.

        def _sets_create(self_inner, args):
            """sets_create([1, 2, 3]) → set from list (or empty set)"""
            if len(args) == 0:
                return set()
            self_inner._expect_args('sets_create', args, 1)
            lst = args[0]
            if not isinstance(lst, list):
                raise RuntimeError("sets_create expects a list argument")
            for item in lst:
                if isinstance(item, (list, dict, set)):
                    raise RuntimeError("sets_create: set elements must be hashable (numbers, strings, booleans)")
            return set(lst)

        def _sets_add(self_inner, args):
            """sets_add(s, value) → new set with value added"""
            self_inner._expect_args('sets_add', args, 2)
            s, val = args
            if not isinstance(s, set):
                raise RuntimeError("sets_add expects a set as first argument")
            if isinstance(val, (list, dict, set)):
                raise RuntimeError("sets_add: value must be hashable (number, string, boolean)")
            result = set(s)
            result.add(val)
            return result

        def _sets_remove(self_inner, args):
            """sets_remove(s, value) → new set with value removed"""
            self_inner._expect_args('sets_remove', args, 2)
            s, val = args
            if not isinstance(s, set):
                raise RuntimeError("sets_remove expects a set as first argument")
            result = set(s)
            result.discard(val)
            return result

        def _sets_contains(self_inner, args):
            """sets_contains(s, value) → true/false"""
            self_inner._expect_args('sets_contains', args, 2)
            s, val = args
            if not isinstance(s, set):
                raise RuntimeError("sets_contains expects a set as first argument")
            return val in s

        self.builtins['sets_create'] = lambda args: _sets_create(self, args)
        self.builtins['sets_add'] = lambda args: _sets_add(self, args)
        self.builtins['sets_remove'] = lambda args: _sets_remove(self, args)
        self.builtins['sets_contains'] = lambda args: _sets_contains(self, args)

        # Two-set-arg operators: all share validate-two-sets + apply pattern
        _SETS_TWO_ARG_TABLE = {
            'sets_union':          lambda a, b: a | b,
            'sets_intersection':   lambda a, b: a & b,
            'sets_difference':     lambda a, b: a - b,
            'sets_symmetric_diff': lambda a, b: a ^ b,
            'sets_is_subset':      lambda a, b: a <= b,
            'sets_is_superset':    lambda a, b: a >= b,
        }
        for _name, _op in _SETS_TWO_ARG_TABLE.items():
            def _make_two_set(n, op):
                def handler(self_inner, args):
                    self_inner._expect_args(n, args, 2)
                    a, b = args
                    if not isinstance(a, set) or not isinstance(b, set):
                        raise RuntimeError(f"{n} expects two sets")
                    return op(a, b)
                return handler
            h = _make_two_set(_name, _op)
            self.builtins[_name] = lambda args, h=h: h(self, args)

        # One-set-arg helpers
        def _sets_size(self_inner, args):
            self_inner._expect_args('sets_size', args, 1)
            s = args[0]
            if not isinstance(s, set):
                raise RuntimeError("sets_size expects a set argument")
            return len(s)

        def _sets_to_list(self_inner, args):
            self_inner._expect_args('sets_to_list', args, 1)
            s = args[0]
            if not isinstance(s, set):
                raise RuntimeError("sets_to_list expects a set argument")
            try:
                return sorted(s)
            except TypeError:
                return list(s)

        self.builtins['sets_size'] = lambda args: _sets_size(self, args)
        self.builtins['sets_to_list'] = lambda args: _sets_to_list(self, args)

        # ── Stack & Queue builtins ────────────────────────────
        # Data-driven registration for stack (LIFO) and queue (FIFO) builtins.
        # Each entry maps a builtin name to (arg_count, method_name, returns_container).
        # For 2-arg methods the second arg is passed to the method; for 1-arg methods
        # the method is called on the container directly.

        def _make_container_create(prefix, cls):
            """Build a create handler for a container type."""
            name = f'{prefix}_create'
            def handler(args):
                if len(args) == 0:
                    return cls()
                self._expect_args(name, args, 1)
                if not isinstance(args[0], list):
                    raise RuntimeError(f"{name} expects a list argument")
                return cls(args[0])
            return handler

        def _make_container_method(prefix, cls, method, nargs, returns_self):
            """Build a handler that delegates to a method on the container."""
            builtin_name = f'{prefix}_{method}'
            type_label = prefix
            def handler(args):
                self._expect_args(builtin_name, args, nargs)
                obj = args[0]
                if not isinstance(obj, cls):
                    raise RuntimeError(
                        f"{builtin_name} expects a {type_label} as first argument")
                result = getattr(obj, method)(*args[1:])
                return obj if returns_self else result
            return handler

        # (method_name, arg_count, returns_container)
        _CONTAINER_METHODS = [
            ('push',     2, True),   # stack only — mapped to enqueue for queue
            ('pop',      1, False),
            ('peek',     1, False),
            ('size',     1, False),
            ('is_empty', 1, False),
            ('to_list',  1, False),
            ('clear',    1, True),
        ]

        # Stack builtins
        self.builtins['stack_create'] = _make_container_create('stack', _SrvStack)
        for _method, _nargs, _ret_self in _CONTAINER_METHODS:
            self.builtins[f'stack_{_method}'] = _make_container_method(
                'stack', _SrvStack, _method, _nargs, _ret_self)

        # Queue builtins — same shape but 'push' becomes 'enqueue' and 'pop' becomes 'dequeue'
        _QUEUE_METHOD_MAP = {
            'push': 'enqueue',
            'pop':  'dequeue',
        }
        self.builtins['queue_create'] = _make_container_create('queue', _SrvQueue)
        for _method, _nargs, _ret_self in _CONTAINER_METHODS:
            _q_method = _QUEUE_METHOD_MAP.get(_method, _method)
            _q_builtin = f'queue_{_q_method}'
            self.builtins[_q_builtin] = _make_container_method(
                'queue', _SrvQueue, _q_method, _nargs, _ret_self)

        # ── Data-driven path builtins ─────────────────────────
        # Pure path builtins (no filesystem access, just string transforms)
        # share: 1-arg, require string, apply os.path function.
        _PATH_PURE_TABLE = {
            'path_dir':  os.path.dirname,
            'path_base': os.path.basename,
            'path_ext':  lambda p: os.path.splitext(p)[1],
            'path_stem': lambda p: os.path.splitext(os.path.basename(p))[0],
        }
        for _name, _fn in _PATH_PURE_TABLE.items():
            def _make_path_pure(n, fn):
                def handler(self_inner, args):
                    self_inner._expect_args(n, args, 1)
                    if not isinstance(args[0], str):
                        raise RuntimeError(f"{n} expects a string argument")
                    return fn(args[0])
                return handler
            h = _make_path_pure(_name, _fn)
            self.builtins[_name] = lambda args, h=h: h(self, args)

        # Validated path builtins (need _validate_file_path before filesystem access)
        _PATH_VALIDATED_TABLE = {
            'path_abs':    os.path.abspath,
            'path_exists': os.path.exists,
            'is_dir':      os.path.isdir,
            'is_file':     os.path.isfile,
        }
        for _name, _fn in _PATH_VALIDATED_TABLE.items():
            def _make_path_validated(n, fn):
                def handler(self_inner, args):
                    self_inner._expect_args(n, args, 1)
                    if not isinstance(args[0], str):
                        raise RuntimeError(f"{n} expects a string argument")
                    self_inner._validate_file_path(n, args[0])
                    return fn(args[0])
                return handler
            h = _make_path_validated(_name, _fn)
            self.builtins[_name] = lambda args, h=h: h(self, args)

        # Special path builtins with unique logic
        def _path_join(self_inner, args):
            """path_join(parts...) → join path components using OS separator"""
            if len(args) < 1:
                raise RuntimeError("path_join expects at least 1 argument")
            for a in args:
                if not isinstance(a, str):
                    raise RuntimeError("path_join: all arguments must be strings")
            return os.path.join(*args)

        def _list_dir(self_inner, args):
            """list_dir(path) → list of filenames in directory"""
            self_inner._expect_args('list_dir', args, 1)
            if not isinstance(args[0], str):
                raise RuntimeError("list_dir expects a string argument")
            self_inner._validate_file_path('list_dir', args[0])
            if not os.path.isdir(args[0]):
                raise RuntimeError(f"list_dir: '{args[0]}' is not a directory")
            return sorted(os.listdir(args[0]))

        def _make_dir(self_inner, args):
            """make_dir(path) → creates directory (and parents), returns path"""
            self_inner._expect_args('make_dir', args, 1)
            if not isinstance(args[0], str):
                raise RuntimeError("make_dir expects a string argument")
            self_inner._validate_file_path('make_dir', args[0])
            os.makedirs(args[0], exist_ok=True)
            return args[0]

        self.builtins['path_join'] = lambda args: _path_join(self, args)
        self.builtins['list_dir'] = lambda args: _list_dir(self, args)
        self.builtins['make_dir'] = lambda args: _make_dir(self, args)

        # --- Combinatorics & advanced collection builtins ---
        self.builtins['sort_by'] = lambda args: self._builtin_sort_by(args)
        self.builtins['min_by'] = lambda args: self._builtin_min_by(args)
        self.builtins['max_by'] = lambda args: self._builtin_max_by(args)
        self.builtins['partition'] = lambda args: self._builtin_partition(args)
        self.builtins['rotate'] = lambda args: self._builtin_rotate(args)
        self.builtins['interleave'] = lambda args: self._builtin_interleave(args)
        self.builtins['frequencies'] = lambda args: self._builtin_frequencies(args)
        self.builtins['combinations'] = lambda args: self._builtin_combinations(args)
        self.builtins['permutations'] = lambda args: self._builtin_permutations(args)

    # ── Environment variable & system info builtins ──────────────────

    def _register_env_sys_builtins(self):
        """Register environment variable and system info builtins.

        Environment:
        - env_get(name[, default]) → get env var (optional default)
        - env_set(name, value) → set env var
        - env_unset(name) → remove env var
        - env_list() → map of all env vars
        - env_has(name) → true/false

        System:
        - sys_exit([code]) → exit with code (default 0)
        - sys_args() → list of command-line arguments
        - sys_platform() → platform string (linux/win32/darwin)
        - sys_cwd() → current working directory
        - sys_pid() → current process ID
        - sys_uptime() → interpreter uptime in seconds
        - sys_hostname() → machine hostname
        """
        import platform as _platform
        import socket as _socket

        _start_time = _time.perf_counter()

        def _env_get(args):
            if len(args) < 1 or len(args) > 2:
                raise RuntimeError("env_get expects 1-2 arguments: env_get(name[, default])")
            name = args[0]
            if not isinstance(name, str):
                raise RuntimeError("env_get: name must be a string")
            if len(args) == 2:
                return os.environ.get(name, args[1])
            val = os.environ.get(name)
            if val is None:
                return None
            return val

        def _env_set(args):
            self._expect_args('env_set', args, 2)
            name, value = args
            if not isinstance(name, str):
                raise RuntimeError("env_set: name must be a string")
            os.environ[name] = str(value)
            return None

        def _env_unset(args):
            self._expect_args('env_unset', args, 1)
            name = args[0]
            if not isinstance(name, str):
                raise RuntimeError("env_unset: name must be a string")
            os.environ.pop(name, None)
            return None

        def _env_list(args):
            if len(args) != 0:
                raise RuntimeError("env_list takes no arguments")
            return dict(os.environ)

        def _env_has(args):
            self._expect_args('env_has', args, 1)
            name = args[0]
            if not isinstance(name, str):
                raise RuntimeError("env_has: name must be a string")
            return name in os.environ

        def _sys_exit(args):
            code = 0
            if len(args) == 1:
                code = int(args[0])
            elif len(args) > 1:
                raise RuntimeError("sys_exit expects 0-1 arguments: sys_exit([code])")
            sys.exit(code)

        def _sys_args(args):
            if len(args) != 0:
                raise RuntimeError("sys_args takes no arguments")
            return list(sys.argv)

        def _sys_platform(args):
            if len(args) != 0:
                raise RuntimeError("sys_platform takes no arguments")
            return sys.platform

        def _sys_cwd(args):
            if len(args) != 0:
                raise RuntimeError("sys_cwd takes no arguments")
            return os.getcwd()

        def _sys_pid(args):
            if len(args) != 0:
                raise RuntimeError("sys_pid takes no arguments")
            return float(os.getpid())

        def _sys_uptime(args):
            if len(args) != 0:
                raise RuntimeError("sys_uptime takes no arguments")
            return round(_time.perf_counter() - _start_time, 3)

        def _sys_hostname(args):
            if len(args) != 0:
                raise RuntimeError("sys_hostname takes no arguments")
            return _socket.gethostname()

        _table = {
            'env_get': _env_get,
            'env_set': _env_set,
            'env_unset': _env_unset,
            'env_list': _env_list,
            'env_has': _env_has,
            'sys_exit': _sys_exit,
            'sys_args': _sys_args,
            'sys_platform': _sys_platform,
            'sys_cwd': _sys_cwd,
            'sys_pid': _sys_pid,
            'sys_uptime': _sys_uptime,
            'sys_hostname': _sys_hostname,
        }
        for name, fn in _table.items():
            self.builtins[name] = fn

    # ── ANSI terminal color & styling builtins ────────────────────────

    def _register_ansi_builtins(self):
        """Register ANSI terminal color and styling builtins.

        Styling:
        - bold(text) → bold text
        - dim(text) → dim/faint text
        - italic(text) → italic text
        - underline(text) → underlined text
        - strikethrough(text) → strikethrough text

        Colors:
        - color(text, name) → foreground color (black/red/green/yellow/blue/magenta/cyan/white
          + bright variants like bright_red, bright_green, etc.)
        - bg_color(text, name) → background color (same names)

        Combo:
        - style(text, style1, style2, ...) → apply multiple styles/colors
        - rainbow(text) → cycle rainbow colors across characters
        - strip_ansi(text) → remove all ANSI escape sequences
        """
        _RESET = '\033[0m'

        _FG_COLORS = {
            'black': '\033[30m', 'red': '\033[31m', 'green': '\033[32m',
            'yellow': '\033[33m', 'blue': '\033[34m', 'magenta': '\033[35m',
            'cyan': '\033[36m', 'white': '\033[37m',
            'bright_black': '\033[90m', 'bright_red': '\033[91m',
            'bright_green': '\033[92m', 'bright_yellow': '\033[93m',
            'bright_blue': '\033[94m', 'bright_magenta': '\033[95m',
            'bright_cyan': '\033[96m', 'bright_white': '\033[97m',
        }

        _BG_COLORS = {
            'black': '\033[40m', 'red': '\033[41m', 'green': '\033[42m',
            'yellow': '\033[43m', 'blue': '\033[44m', 'magenta': '\033[45m',
            'cyan': '\033[46m', 'white': '\033[47m',
            'bright_black': '\033[100m', 'bright_red': '\033[101m',
            'bright_green': '\033[102m', 'bright_yellow': '\033[103m',
            'bright_blue': '\033[104m', 'bright_magenta': '\033[105m',
            'bright_cyan': '\033[106m', 'bright_white': '\033[107m',
        }

        _STYLES = {
            'bold': '\033[1m', 'dim': '\033[2m', 'italic': '\033[3m',
            'underline': '\033[4m', 'strikethrough': '\033[9m',
        }

        _RAINBOW = ['\033[31m', '\033[33m', '\033[32m', '\033[36m', '\033[34m', '\033[35m']

        _ANSI_RE = re.compile(r'\033\[[0-9;]*m')

        def _bold(args):
            self._expect_args('bold', args, 1)
            return f"{_STYLES['bold']}{args[0]}{_RESET}"

        def _dim(args):
            self._expect_args('dim', args, 1)
            return f"{_STYLES['dim']}{args[0]}{_RESET}"

        def _italic(args):
            self._expect_args('italic', args, 1)
            return f"{_STYLES['italic']}{args[0]}{_RESET}"

        def _underline(args):
            self._expect_args('underline', args, 1)
            return f"{_STYLES['underline']}{args[0]}{_RESET}"

        def _strikethrough(args):
            self._expect_args('strikethrough', args, 1)
            return f"{_STYLES['strikethrough']}{args[0]}{_RESET}"

        def _color(args):
            self._expect_args('color', args, 2)
            text, name = args
            if not isinstance(name, str):
                raise RuntimeError("color: color name must be a string")
            code = _FG_COLORS.get(name)
            if code is None:
                raise RuntimeError(
                    f"color: unknown color '{name}'. Available: "
                    + ', '.join(sorted(_FG_COLORS.keys()))
                )
            return f"{code}{text}{_RESET}"

        def _bg_color(args):
            self._expect_args('bg_color', args, 2)
            text, name = args
            if not isinstance(name, str):
                raise RuntimeError("bg_color: color name must be a string")
            code = _BG_COLORS.get(name)
            if code is None:
                raise RuntimeError(
                    f"bg_color: unknown color '{name}'. Available: "
                    + ', '.join(sorted(_BG_COLORS.keys()))
                )
            return f"{code}{text}{_RESET}"

        def _style(args):
            if len(args) < 2:
                raise RuntimeError(
                    "style expects at least 2 arguments: style(text, style1, ...)"
                )
            text = args[0]
            codes = []
            for s in args[1:]:
                if not isinstance(s, str):
                    raise RuntimeError(f"style: each style must be a string, got {type(s).__name__}")
                if s in _STYLES:
                    codes.append(_STYLES[s])
                elif s in _FG_COLORS:
                    codes.append(_FG_COLORS[s])
                elif s.startswith('bg_') and s[3:] in _BG_COLORS:
                    codes.append(_BG_COLORS[s[3:]])
                else:
                    available = sorted(set(list(_STYLES.keys()) + list(_FG_COLORS.keys())
                                       + [f'bg_{c}' for c in _BG_COLORS.keys()]))
                    raise RuntimeError(
                        f"style: unknown style '{s}'. Available: " + ', '.join(available)
                    )
            return ''.join(codes) + str(text) + _RESET

        def _rainbow(args):
            self._expect_args('rainbow', args, 1)
            text = str(args[0])
            result = []
            ci = 0
            for ch in text:
                if ch == ' ':
                    result.append(ch)
                else:
                    result.append(f"{_RAINBOW[ci % len(_RAINBOW)]}{ch}")
                    ci += 1
            result.append(_RESET)
            return ''.join(result)

        def _strip_ansi(args):
            self._expect_args('strip_ansi', args, 1)
            if not isinstance(args[0], str):
                raise RuntimeError("strip_ansi: argument must be a string")
            return _ANSI_RE.sub('', args[0])

        _table = {
            'bold': _bold,
            'dim': _dim,
            'italic': _italic,
            'underline': _underline,
            'strikethrough': _strikethrough,
            'color': _color,
            'bg_color': _bg_color,
            'style': _style,
            'rainbow': _rainbow,
            'strip_ansi': _strip_ansi,
        }
        for name, fn in _table.items():
            self.builtins[name] = fn

    # ── UUID & random data generation builtins ────────────────────────

    def _register_random_data_builtins(self):
        """Register UUID and random data generation builtins.

        Builtins:
        - uuid_v4()  generate a random UUID v4 string
        - random_bytes(n)  list of n random integers 0-255
        - random_hex(n)  random hex string of n bytes (2n hex chars)
        - random_string(n)  random alphanumeric string of length n
        - random_float()  random float in [0, 1), or random_float(min, max)
        """
        import uuid as _uuid_mod
        import os as _os_mod
        import string as _string_mod

        def _uuid_v4(args):
            if args:
                raise RuntimeError("uuid_v4 takes no arguments")
            return str(_uuid_mod.uuid4())

        def _random_bytes(args):
            self._expect_args('random_bytes', args, 1)
            n = args[0]
            if not isinstance(n, (int, float)) or int(n) != n or n < 0:
                raise RuntimeError("random_bytes: argument must be a non-negative integer")
            n = int(n)
            if n > 65536:
                raise RuntimeError("random_bytes: maximum 65536 bytes")
            return list(_os_mod.urandom(n))

        def _random_hex(args):
            self._expect_args('random_hex', args, 1)
            n = args[0]
            if not isinstance(n, (int, float)) or int(n) != n or n < 0:
                raise RuntimeError("random_hex: argument must be a non-negative integer")
            n = int(n)
            if n > 65536:
                raise RuntimeError("random_hex: maximum 65536 bytes")
            return _os_mod.urandom(n).hex()

        def _random_string(args):
            self._expect_args('random_string', args, 1)
            n = args[0]
            if not isinstance(n, (int, float)) or int(n) != n or n < 0:
                raise RuntimeError("random_string: argument must be a non-negative integer")
            n = int(n)
            if n > 65536:
                raise RuntimeError("random_string: maximum 65536 characters")
            import random as _rng
            chars = _string_mod.ascii_letters + _string_mod.digits
            return ''.join(_rng.choice(chars) for _ in range(n))

        def _random_float(args):
            import random as _rng
            if len(args) == 0:
                return _rng.random()
            elif len(args) == 2:
                lo, hi = args
                if not isinstance(lo, (int, float)) or not isinstance(hi, (int, float)):
                    raise RuntimeError("random_float: arguments must be numbers")
                return _rng.uniform(float(lo), float(hi))
            else:
                raise RuntimeError("random_float expects 0 or 2 arguments: random_float() or random_float(min, max)")

        _table = {
            'uuid_v4': _uuid_v4,
            'random_bytes': _random_bytes,
            'random_hex': _random_hex,
            'random_string': _random_string,
            'random_float': _random_float,
        }
        for name, fn in _table.items():
            self.builtins[name] = fn

    def _register_csv_builtins(self):
        """Register CSV parsing and generation builtins.

        Builtins:
        - csv_parse(text)  parse CSV text into list of maps (first row = headers)
        - csv_parse(text, delimiter)  parse with custom delimiter
        - csv_stringify(rows)  convert list of maps to CSV text
        - csv_stringify(rows, delimiter)  with custom delimiter
        - csv_headers(rows)  extract column headers from parsed CSV data
        - csv_select(rows, columns)  select specific columns from CSV data
        - csv_filter(rows, column, value)  filter rows where column == value
        - csv_sort(rows, column)  sort rows by column value
        - csv_sort(rows, column, "desc")  sort descending
        - csv_read(path)  read and parse a CSV file
        - csv_read(path, delimiter)  read with custom delimiter
        - csv_write(path, rows)  write CSV data to a file
        - csv_write(path, rows, delimiter)  write with custom delimiter
        """
        import csv as _csv_mod
        import io as _io_mod

        interpreter = self

        def _csv_parse(args):
            if len(args) < 1 or len(args) > 2:
                raise RuntimeError("csv_parse expects 1-2 arguments: csv_parse(text) or csv_parse(text, delimiter)")
            text = args[0]
            if not isinstance(text, str):
                raise RuntimeError("csv_parse: first argument must be a string")
            delimiter = ','
            if len(args) == 2:
                if not isinstance(args[1], str) or len(args[1]) != 1:
                    raise RuntimeError("csv_parse: delimiter must be a single character")
                delimiter = args[1]
            reader = _csv_mod.DictReader(_io_mod.StringIO(text), delimiter=delimiter)
            rows = []
            for row in reader:
                converted = {}
                for k, v in row.items():
                    if v is None:
                        converted[k] = ''
                    else:
                        # Try numeric conversion
                        try:
                            converted[k] = float(v) if '.' in v else int(v)
                        except (ValueError, TypeError):
                            converted[k] = v
                rows.append(converted)
            return rows

        def _csv_stringify(args):
            if len(args) < 1 or len(args) > 2:
                raise RuntimeError("csv_stringify expects 1-2 arguments: csv_stringify(rows) or csv_stringify(rows, delimiter)")
            rows = args[0]
            if not isinstance(rows, list):
                raise RuntimeError("csv_stringify: first argument must be a list of maps")
            if not rows:
                return ''
            delimiter = ','
            if len(args) == 2:
                if not isinstance(args[1], str) or len(args[1]) != 1:
                    raise RuntimeError("csv_stringify: delimiter must be a single character")
                delimiter = args[1]
            if not isinstance(rows[0], dict):
                raise RuntimeError("csv_stringify: each row must be a map")
            headers = list(rows[0].keys())
            output = _io_mod.StringIO()
            writer = _csv_mod.writer(output, delimiter=delimiter, lineterminator='\n')
            writer.writerow(headers)
            for row in rows:
                if not isinstance(row, dict):
                    raise RuntimeError("csv_stringify: each row must be a map")
                writer.writerow([row.get(h, '') for h in headers])
            return output.getvalue()

        def _csv_headers(args):
            interpreter._expect_args('csv_headers', args, 1)
            rows = args[0]
            if not isinstance(rows, list):
                raise RuntimeError("csv_headers: argument must be a list of maps")
            if not rows:
                return []
            if not isinstance(rows[0], dict):
                raise RuntimeError("csv_headers: rows must contain maps")
            return list(rows[0].keys())

        def _csv_select(args):
            interpreter._expect_args('csv_select', args, 2)
            rows, columns = args
            if not isinstance(rows, list):
                raise RuntimeError("csv_select: first argument must be a list of maps")
            if not isinstance(columns, list):
                raise RuntimeError("csv_select: second argument must be a list of column names")
            result = []
            for row in rows:
                if not isinstance(row, dict):
                    raise RuntimeError("csv_select: each row must be a map")
                result.append({c: row.get(c, '') for c in columns})
            return result

        def _csv_filter(args):
            interpreter._expect_args('csv_filter', args, 3)
            rows, column, value = args
            if not isinstance(rows, list):
                raise RuntimeError("csv_filter: first argument must be a list of maps")
            if not isinstance(column, str):
                raise RuntimeError("csv_filter: second argument must be a column name string")
            result = []
            for row in rows:
                if not isinstance(row, dict):
                    raise RuntimeError("csv_filter: each row must be a map")
                if row.get(column) == value:
                    result.append(row)
            return result

        def _csv_sort(args):
            if len(args) < 2 or len(args) > 3:
                raise RuntimeError("csv_sort expects 2-3 arguments: csv_sort(rows, column) or csv_sort(rows, column, \"desc\")")
            rows = args[0]
            column = args[1]
            descending = False
            if len(args) == 3:
                if args[2] == "desc":
                    descending = True
                elif args[2] != "asc":
                    raise RuntimeError("csv_sort: third argument must be \"asc\" or \"desc\"")
            if not isinstance(rows, list):
                raise RuntimeError("csv_sort: first argument must be a list of maps")
            if not isinstance(column, str):
                raise RuntimeError("csv_sort: second argument must be a column name string")
            def sort_key(row):
                v = row.get(column, '')
                if isinstance(v, (int, float)):
                    return (0, v, '')
                return (1, 0, str(v))
            return sorted(rows, key=sort_key, reverse=descending)

        def _csv_read(args):
            if len(args) < 1 or len(args) > 2:
                raise RuntimeError("csv_read expects 1-2 arguments: csv_read(path) or csv_read(path, delimiter)")
            path = args[0]
            if not isinstance(path, str):
                raise RuntimeError("csv_read: first argument must be a file path string")
            full_path = interpreter._validate_file_path('csv_read', path)
            try:
                with open(full_path, 'r', encoding='utf-8', newline='') as f:
                    text = f.read()
            except FileNotFoundError:
                raise RuntimeError(f"csv_read: file not found: {path}")
            except PermissionError:
                raise RuntimeError(f"csv_read: permission denied: {path}")
            read_args = [text]
            if len(args) == 2:
                read_args.append(args[1])
            return _csv_parse(read_args)

        def _csv_write(args):
            if len(args) < 2 or len(args) > 3:
                raise RuntimeError("csv_write expects 2-3 arguments: csv_write(path, rows) or csv_write(path, rows, delimiter)")
            path = args[0]
            rows = args[1]
            if not isinstance(path, str):
                raise RuntimeError("csv_write: first argument must be a file path string")
            full_path = interpreter._validate_file_path('csv_write', path)
            stringify_args = [rows]
            if len(args) == 3:
                stringify_args.append(args[2])
            text = _csv_stringify(stringify_args)
            try:
                with open(full_path, 'w', encoding='utf-8', newline='') as f:
                    f.write(text)
            except PermissionError:
                raise RuntimeError(f"csv_write: permission denied: {path}")
            return True

        _table = {
            'csv_parse': _csv_parse,
            'csv_stringify': _csv_stringify,
            'csv_headers': _csv_headers,
            'csv_select': _csv_select,
            'csv_filter': _csv_filter,
            'csv_sort': _csv_sort,
            'csv_read': _csv_read,
            'csv_write': _csv_write,
        }
        for name, fn in _table.items():
            self.builtins[name] = fn

    def _register_validation_builtins(self):
        """Register data validation builtins."""
        import re as _re
        import json as _json

        _email_re = _re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')
        _url_re = _re.compile(r'^https?://[^\s/$.?#].[^\s]*$', _re.IGNORECASE)
        _ipv4_re = _re.compile(r'^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$')
        _ipv6_re = _re.compile(r'^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}$')
        _uuid_re = _re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
        _hex_color_re = _re.compile(r'^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$')
        _phone_re = _re.compile(r'^\+?[1-9]\d{6,14}$')
        _credit_card_re = _re.compile(r'^\d{13,19}$')

        self_inner = self

        def _is_email(args):
            self_inner._expect_args('is_email', args, 1)
            if not isinstance(args[0], str):
                return False
            return bool(_email_re.match(args[0]))

        def _is_url(args):
            self_inner._expect_args('is_url', args, 1)
            if not isinstance(args[0], str):
                return False
            return bool(_url_re.match(args[0]))

        def _is_ipv4(args):
            self_inner._expect_args('is_ipv4', args, 1)
            if not isinstance(args[0], str):
                return False
            m = _ipv4_re.match(args[0])
            if not m:
                return False
            return all(0 <= int(g) <= 255 for g in m.groups())

        def _is_ipv6(args):
            self_inner._expect_args('is_ipv6', args, 1)
            if not isinstance(args[0], str):
                return False
            return bool(_ipv6_re.match(args[0]))

        def _is_ip(args):
            self_inner._expect_args('is_ip', args, 1)
            return _is_ipv4(args) or _is_ipv6(args)

        def _is_date(args):
            self_inner._expect_args('is_date', args, 1)
            if not isinstance(args[0], str):
                return False
            from datetime import datetime as _dt
            for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%d-%m-%Y', '%Y/%m/%d',
                        '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S'):
                try:
                    _dt.strptime(args[0], fmt)
                    return True
                except ValueError:
                    continue
            return False

        def _is_uuid(args):
            self_inner._expect_args('is_uuid', args, 1)
            if not isinstance(args[0], str):
                return False
            return bool(_uuid_re.match(args[0]))

        def _is_hex_color(args):
            self_inner._expect_args('is_hex_color', args, 1)
            if not isinstance(args[0], str):
                return False
            return bool(_hex_color_re.match(args[0]))

        def _is_phone(args):
            self_inner._expect_args('is_phone', args, 1)
            if not isinstance(args[0], str):
                return False
            cleaned = args[0].replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
            return bool(_phone_re.match(cleaned))

        def _is_credit_card(args):
            self_inner._expect_args('is_credit_card', args, 1)
            if not isinstance(args[0], str):
                return False
            digits = args[0].replace(' ', '').replace('-', '')
            if not _credit_card_re.match(digits):
                return False
            # Luhn algorithm
            total = 0
            for i, d in enumerate(reversed(digits)):
                n = int(d)
                if i % 2 == 1:
                    n *= 2
                    if n > 9:
                        n -= 9
                total += n
            return total % 10 == 0

        def _is_json(args):
            self_inner._expect_args('is_json', args, 1)
            if not isinstance(args[0], str):
                return False
            try:
                _json.loads(args[0])
                return True
            except (ValueError, TypeError):
                return False

        def _validate(args):
            """validate(value, rules) - returns map with valid, errors. rules is a list of rule strings."""
            if len(args) < 2:
                raise RuntimeError("validate: requires 2 arguments (value, rules_list)")
            value = args[0]
            rules_arg = args[1] if len(args) == 2 else args[1:]
            if isinstance(rules_arg, list):
                rules = rules_arg
            else:
                rules = [rules_arg]
            errors = []
            for rule in rules:
                if not isinstance(rule, str):
                    raise RuntimeError(f"validate: rules must be strings, got {type(rule).__name__}")
                r = rule.lower().strip()
                if r == 'required':
                    if value is None or (isinstance(value, str) and value.strip() == ''):
                        errors.append('Value is required')
                elif r == 'email':
                    if not _is_email([value]):
                        errors.append('Invalid email address')
                elif r == 'url':
                    if not _is_url([value]):
                        errors.append('Invalid URL')
                elif r == 'ipv4':
                    if not _is_ipv4([value]):
                        errors.append('Invalid IPv4 address')
                elif r == 'ipv6':
                    if not _is_ipv6([value]):
                        errors.append('Invalid IPv6 address')
                elif r == 'ip':
                    if not _is_ip([value]):
                        errors.append('Invalid IP address')
                elif r == 'uuid':
                    if not _is_uuid([value]):
                        errors.append('Invalid UUID')
                elif r == 'date':
                    if not _is_date([value]):
                        errors.append('Invalid date')
                elif r == 'hex_color':
                    if not _is_hex_color([value]):
                        errors.append('Invalid hex color')
                elif r == 'phone':
                    if not _is_phone([value]):
                        errors.append('Invalid phone number')
                elif r == 'credit_card':
                    if not _is_credit_card([value]):
                        errors.append('Invalid credit card number')
                elif r == 'json':
                    if not _is_json([value]):
                        errors.append('Invalid JSON')
                elif r == 'numeric':
                    if not isinstance(value, (int, float)):
                        try:
                            float(value)
                        except (ValueError, TypeError):
                            errors.append('Value must be numeric')
                elif r == 'alpha':
                    if not isinstance(value, str) or not value.isalpha():
                        errors.append('Value must contain only letters')
                elif r == 'alphanumeric':
                    if not isinstance(value, str) or not value.isalnum():
                        errors.append('Value must be alphanumeric')
                elif r.startswith('min_len:'):
                    min_l = int(r.split(':')[1])
                    if not isinstance(value, str) or len(value) < min_l:
                        errors.append(f'Minimum length is {min_l}')
                elif r.startswith('max_len:'):
                    max_l = int(r.split(':')[1])
                    if not isinstance(value, str) or len(value) > max_l:
                        errors.append(f'Maximum length is {max_l}')
                elif r.startswith('min:'):
                    min_v = float(r.split(':')[1])
                    try:
                        if float(value) < min_v:
                            errors.append(f'Value must be at least {min_v}')
                    except (ValueError, TypeError):
                        errors.append(f'Value must be at least {min_v}')
                elif r.startswith('max:'):
                    max_v = float(r.split(':')[1])
                    try:
                        if float(value) > max_v:
                            errors.append(f'Value must be at most {max_v}')
                    except (ValueError, TypeError):
                        errors.append(f'Value must be at most {max_v}')
                else:
                    errors.append(f'Unknown rule: {rule}')
            return {'valid': len(errors) == 0, 'errors': errors}

        _table = {
            'is_email': _is_email,
            'is_url': _is_url,
            'is_ipv4': _is_ipv4,
            'is_ipv6': _is_ipv6,
            'is_ip': _is_ip,
            'is_date': _is_date,
            'is_uuid': _is_uuid,
            'is_hex_color': _is_hex_color,
            'is_phone': _is_phone,
            'is_credit_card': _is_credit_card,
            'is_json': _is_json,
            'validate': _validate,
        }
        for name, fn in _table.items():
            self.builtins[name] = fn

    # ── Memoization & Cache builtins ─────────────────────

    def _register_cache_builtins(self):
        """Register memoization and key-value cache builtins.

        Provides a simple key-value cache with
           ``cache_create``, ``cache_get``, ``cache_set``, ``cache_has``,
           ``cache_delete``, ``cache_keys``, ``cache_values``,
           ``cache_entries``, ``cache_size``, ``cache_clear``.
        """

        # --- cache_create() -> new empty cache (dict wrapper) ---
        def _cache_create(args):
            return {'__sauravcode_cache__': True, '_data': {}}
        self.builtins['cache_create'] = _cache_create

        # --- cache_set(cache, key, value) ---
        def _cache_set(args):
            self._expect_args('cache_set', args, 3)
            cache, key, value = args[0], args[1], args[2]
            if not isinstance(cache, dict) or not cache.get('__sauravcode_cache__'):
                raise RuntimeError("cache_set: first argument must be a cache (from cache_create)")
            if not isinstance(key, str):
                raise RuntimeError("cache_set: key must be a string")
            cache['_data'][key] = value
            return value
        self.builtins['cache_set'] = _cache_set

        # --- cache_get(cache, key) -> value or "" ---
        def _cache_get(args):
            self._expect_args('cache_get', args, 2)
            cache, key = args[0], args[1]
            if not isinstance(cache, dict) or not cache.get('__sauravcode_cache__'):
                raise RuntimeError("cache_get: first argument must be a cache (from cache_create)")
            if not isinstance(key, str):
                raise RuntimeError("cache_get: key must be a string")
            return cache['_data'].get(key, "")
        self.builtins['cache_get'] = _cache_get

        # --- cache_has(cache, key) -> bool ---
        def _cache_has(args):
            self._expect_args('cache_has', args, 2)
            cache, key = args[0], args[1]
            if not isinstance(cache, dict) or not cache.get('__sauravcode_cache__'):
                raise RuntimeError("cache_has: first argument must be a cache (from cache_create)")
            return 1.0 if key in cache['_data'] else 0.0
        self.builtins['cache_has'] = _cache_has

        # --- cache_delete(cache, key) -> deleted value or "" ---
        def _cache_delete(args):
            self._expect_args('cache_delete', args, 2)
            cache, key = args[0], args[1]
            if not isinstance(cache, dict) or not cache.get('__sauravcode_cache__'):
                raise RuntimeError("cache_delete: first argument must be a cache (from cache_create)")
            return cache['_data'].pop(key, "")
        self.builtins['cache_delete'] = _cache_delete

        # --- cache_keys(cache) -> list of keys ---
        def _cache_keys(args):
            self._expect_args('cache_keys', args, 1)
            cache = args[0]
            if not isinstance(cache, dict) or not cache.get('__sauravcode_cache__'):
                raise RuntimeError("cache_keys: argument must be a cache (from cache_create)")
            return list(cache['_data'].keys())
        self.builtins['cache_keys'] = _cache_keys

        # --- cache_size(cache) -> number of entries ---
        def _cache_size(args):
            self._expect_args('cache_size', args, 1)
            cache = args[0]
            if not isinstance(cache, dict) or not cache.get('__sauravcode_cache__'):
                raise RuntimeError("cache_size: argument must be a cache (from cache_create)")
            return float(len(cache['_data']))
        self.builtins['cache_size'] = _cache_size

        # --- cache_clear(cache) -> 0.0 ---
        def _cache_clear(args):
            self._expect_args('cache_clear', args, 1)
            cache = args[0]
            if not isinstance(cache, dict) or not cache.get('__sauravcode_cache__'):
                raise RuntimeError("cache_clear: argument must be a cache (from cache_create)")
            cache['_data'].clear()
            return 0.0
        self.builtins['cache_clear'] = _cache_clear

        # --- cache_values(cache) -> list of values ---
        def _cache_values(args):
            self._expect_args('cache_values', args, 1)
            cache = args[0]
            if not isinstance(cache, dict) or not cache.get('__sauravcode_cache__'):
                raise RuntimeError("cache_values: argument must be a cache (from cache_create)")
            return list(cache['_data'].values())
        self.builtins['cache_values'] = _cache_values

        # --- cache_entries(cache) -> list of [key, value] pairs ---
        def _cache_entries(args):
            self._expect_args('cache_entries', args, 1)
            cache = args[0]
            if not isinstance(cache, dict) or not cache.get('__sauravcode_cache__'):
                raise RuntimeError("cache_entries: argument must be a cache (from cache_create)")
            return [list(pair) for pair in cache['_data'].items()]
        self.builtins['cache_entries'] = _cache_entries

    def _register_color_builtins(self):
        """Register color manipulation builtins.

        Provides ``color_rgb``, ``color_hex``, ``color_hsl``, ``color_blend``,
        ``color_lighten``, ``color_darken``, ``color_invert``, ``color_contrast``,
        ``color_to_rgb``, ``color_to_hex``, ``color_to_hsl``.
        """
        interpreter = self

        def _parse_hex_color(s):
            """Parse '#RRGGBB' or '#RGB' to (r, g, b) ints."""
            if not isinstance(s, str):
                raise RuntimeError("color: expected a hex color string like '#FF0000'")
            s = s.strip().lstrip('#')
            if len(s) == 3:
                s = s[0]*2 + s[1]*2 + s[2]*2
            if len(s) != 6:
                raise RuntimeError(f"color: invalid hex color '#{s}'")
            try:
                r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
            except ValueError:
                raise RuntimeError(f"color: invalid hex color '#{s}'")
            return (r, g, b)

        def _rgb_to_hsl(r, g, b):
            """Convert RGB (0-255) to HSL (h: 0-360, s: 0-100, l: 0-100)."""
            r1, g1, b1 = r / 255.0, g / 255.0, b / 255.0
            mx, mn = max(r1, g1, b1), min(r1, g1, b1)
            l = (mx + mn) / 2.0
            if mx == mn:
                h = s = 0.0
            else:
                d = mx - mn
                s = d / (2.0 - mx - mn) if l > 0.5 else d / (mx + mn)
                if mx == r1:
                    h = (g1 - b1) / d + (6.0 if g1 < b1 else 0.0)
                elif mx == g1:
                    h = (b1 - r1) / d + 2.0
                else:
                    h = (r1 - g1) / d + 4.0
                h /= 6.0
            return (round(h * 360, 1), round(s * 100, 1), round(l * 100, 1))

        def _hsl_to_rgb(h, s, l):
            """Convert HSL (h: 0-360, s: 0-100, l: 0-100) to RGB (0-255)."""
            h1, s1, l1 = h / 360.0, s / 100.0, l / 100.0
            if s1 == 0:
                v = int(round(l1 * 255))
                return (v, v, v)
            def hue2rgb(p, q, t):
                if t < 0: t += 1
                if t > 1: t -= 1
                if t < 1/6: return p + (q - p) * 6 * t
                if t < 1/2: return q
                if t < 2/3: return p + (q - p) * (2/3 - t) * 6
                return p
            q = l1 * (1 + s1) if l1 < 0.5 else l1 + s1 - l1 * s1
            p = 2 * l1 - q
            r = int(round(hue2rgb(p, q, h1 + 1/3) * 255))
            g = int(round(hue2rgb(p, q, h1) * 255))
            b = int(round(hue2rgb(p, q, h1 - 1/3) * 255))
            return (r, g, b)

        def _clamp(v, lo=0, hi=255):
            return max(lo, min(hi, int(round(v))))

        # color_rgb(r, g, b) -> map {r, g, b, hex}
        def _color_rgb(args):
            interpreter._expect_args('color_rgb', args, 3)
            r, g, b = [_clamp(a) for a in args]
            return {'r': float(r), 'g': float(g), 'b': float(b),
                    'hex': f'#{r:02X}{g:02X}{b:02X}'}

        # color_hex(str) -> map {r, g, b, hex}
        def _color_hex(args):
            interpreter._expect_args('color_hex', args, 1)
            r, g, b = _parse_hex_color(args[0])
            return {'r': float(r), 'g': float(g), 'b': float(b),
                    'hex': f'#{r:02X}{g:02X}{b:02X}'}

        # color_hsl(h, s, l) -> map {h, s, l, r, g, b, hex}
        def _color_hsl(args):
            interpreter._expect_args('color_hsl', args, 3)
            h, s, l = float(args[0]), float(args[1]), float(args[2])
            r, g, b = _hsl_to_rgb(h, s, l)
            return {'h': h, 's': s, 'l': l,
                    'r': float(r), 'g': float(g), 'b': float(b),
                    'hex': f'#{r:02X}{g:02X}{b:02X}'}

        # color_blend(hex1, hex2, ratio) -> blended hex
        def _color_blend(args):
            interpreter._expect_args('color_blend', args, 3)
            r1, g1, b1 = _parse_hex_color(args[0])
            r2, g2, b2 = _parse_hex_color(args[1])
            t = float(args[2])
            r = _clamp(r1 + (r2 - r1) * t)
            g = _clamp(g1 + (g2 - g1) * t)
            b = _clamp(b1 + (b2 - b1) * t)
            return f'#{r:02X}{g:02X}{b:02X}'

        # color_lighten(hex, amount) -> hex  (amount 0-100)
        def _color_lighten(args):
            interpreter._expect_args('color_lighten', args, 2)
            r, g, b = _parse_hex_color(args[0])
            h, s, l = _rgb_to_hsl(r, g, b)
            l = min(100, l + float(args[1]))
            r, g, b = _hsl_to_rgb(h, s, l)
            return f'#{r:02X}{g:02X}{b:02X}'

        # color_darken(hex, amount) -> hex  (amount 0-100)
        def _color_darken(args):
            interpreter._expect_args('color_darken', args, 2)
            r, g, b = _parse_hex_color(args[0])
            h, s, l = _rgb_to_hsl(r, g, b)
            l = max(0, l - float(args[1]))
            r, g, b = _hsl_to_rgb(h, s, l)
            return f'#{r:02X}{g:02X}{b:02X}'

        # color_invert(hex) -> hex
        def _color_invert(args):
            interpreter._expect_args('color_invert', args, 1)
            r, g, b = _parse_hex_color(args[0])
            return f'#{255-r:02X}{255-g:02X}{255-b:02X}'

        # color_contrast(hex) -> "#000000" or "#FFFFFF"
        def _color_contrast(args):
            interpreter._expect_args('color_contrast', args, 1)
            r, g, b = _parse_hex_color(args[0])
            # W3C relative luminance
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            return '#000000' if lum > 128 else '#FFFFFF'

        # color_to_rgb(hex) -> map {r, g, b}
        def _color_to_rgb(args):
            interpreter._expect_args('color_to_rgb', args, 1)
            r, g, b = _parse_hex_color(args[0])
            return {'r': float(r), 'g': float(g), 'b': float(b)}

        # color_to_hex(r, g, b) -> hex string
        def _color_to_hex(args):
            interpreter._expect_args('color_to_hex', args, 3)
            r, g, b = [_clamp(a) for a in args]
            return f'#{r:02X}{g:02X}{b:02X}'

        # color_to_hsl(hex) -> map {h, s, l}
        def _color_to_hsl(args):
            interpreter._expect_args('color_to_hsl', args, 1)
            r, g, b = _parse_hex_color(args[0])
            h, s, l = _rgb_to_hsl(r, g, b)
            return {'h': h, 's': s, 'l': l}

        self.builtins['color_rgb'] = _color_rgb
        self.builtins['color_hex'] = _color_hex
        self.builtins['color_hsl'] = _color_hsl
        self.builtins['color_blend'] = _color_blend
        self.builtins['color_lighten'] = _color_lighten
        self.builtins['color_darken'] = _color_darken
        self.builtins['color_invert'] = _color_invert
        self.builtins['color_contrast'] = _color_contrast
        self.builtins['color_to_rgb'] = _color_to_rgb
        self.builtins['color_to_hex'] = _color_to_hex
        self.builtins['color_to_hsl'] = _color_to_hsl

    # ── Regex builtins ───────────────────────────────────

    def _register_regex_builtins(self):
        """Register regular expression builtins.

        Provides ``re_test``, ``re_match``, ``re_search``, ``re_find_all``,
        ``re_replace``, ``re_split``, ``re_escape``.
        """
        import re as _re
        interpreter = self

        # re_test(pattern, text) -> bool
        def _re_test(args):
            interpreter._expect_args('re_test', args, 2)
            if not isinstance(args[0], str) or not isinstance(args[1], str):
                raise RuntimeError("re_test: both arguments must be strings")
            return bool(_re.search(args[0], args[1]))

        # re_match(pattern, text) -> map {matched, groups, start, end} or nil
        def _re_match(args):
            interpreter._expect_args('re_match', args, 2)
            if not isinstance(args[0], str) or not isinstance(args[1], str):
                raise RuntimeError("re_match: both arguments must be strings")
            m = _re.match(args[0], args[1])
            if m is None:
                return None
            return {
                'matched': m.group(0),
                'groups': list(m.groups()),
                'start': float(m.start()),
                'end': float(m.end()),
            }

        # re_search(pattern, text) -> map {matched, groups, start, end} or nil
        def _re_search(args):
            interpreter._expect_args('re_search', args, 2)
            if not isinstance(args[0], str) or not isinstance(args[1], str):
                raise RuntimeError("re_search: both arguments must be strings")
            m = _re.search(args[0], args[1])
            if m is None:
                return None
            return {
                'matched': m.group(0),
                'groups': list(m.groups()),
                'start': float(m.start()),
                'end': float(m.end()),
            }

        # re_find_all(pattern, text) -> list of strings (or list of lists for groups)
        def _re_find_all(args):
            interpreter._expect_args('re_find_all', args, 2)
            if not isinstance(args[0], str) or not isinstance(args[1], str):
                raise RuntimeError("re_find_all: both arguments must be strings")
            results = _re.findall(args[0], args[1])
            # findall returns list of tuples when groups exist; convert to lists
            return [list(r) if isinstance(r, tuple) else r for r in results]

        # re_replace(pattern, replacement, text) -> string
        def _re_replace(args):
            if len(args) < 3 or len(args) > 4:
                raise RuntimeError("re_replace expects 3-4 arguments: re_replace(pattern, replacement, text) or re_replace(pattern, replacement, text, count)")
            if not isinstance(args[0], str) or not isinstance(args[1], str) or not isinstance(args[2], str):
                raise RuntimeError("re_replace: pattern, replacement, and text must be strings")
            count = 0  # 0 means replace all
            if len(args) == 4:
                count = int(args[3])
            return _re.sub(args[0], args[1], args[2], count=count)

        # re_split(pattern, text) -> list of strings
        def _re_split(args):
            if len(args) < 2 or len(args) > 3:
                raise RuntimeError("re_split expects 2-3 arguments: re_split(pattern, text) or re_split(pattern, text, maxsplit)")
            if not isinstance(args[0], str) or not isinstance(args[1], str):
                raise RuntimeError("re_split: pattern and text must be strings")
            maxsplit = 0
            if len(args) == 3:
                maxsplit = int(args[2])
            return _re.split(args[0], args[1], maxsplit=maxsplit)

        # re_escape(text) -> escaped string safe for use in regex
        def _re_escape(args):
            interpreter._expect_args('re_escape', args, 1)
            if not isinstance(args[0], str):
                raise RuntimeError("re_escape: argument must be a string")
            return _re.escape(args[0])

        self.builtins['re_test'] = _re_test
        self.builtins['re_match'] = _re_match
        self.builtins['re_search'] = _re_search
        self.builtins['re_find_all'] = _re_find_all
        self.builtins['re_replace'] = _re_replace
        self.builtins['re_split'] = _re_split
        self.builtins['re_escape'] = _re_escape

        # Graph and JSON builtins extracted to their own registration methods
        self._register_graph_builtins()
        self._register_json_builtins()

    def _register_graph_builtins(self):
        """Register graph data-structure builtins.

        Provides ``graph_create``, ``graph_add_node``, ``graph_add_edge``,
        ``graph_neighbors``, ``graph_nodes``, ``graph_edges``,
        ``graph_has_node``, ``graph_has_edge``, ``graph_remove_node``,
        ``graph_remove_edge``, ``graph_degree``, ``graph_bfs``,
        ``graph_dfs``, ``graph_shortest_path``, ``graph_connected``.
        """
        interpreter = self

        # ── Graph builtins ──
        def _graph_create(args):
            if len(args) == 0:
                return _SrvGraph()
            interpreter._expect_args('graph_create', args, 1)
            directed = args[0]
            if not isinstance(directed, bool):
                raise RuntimeError("graph_create expects a boolean (true for directed)")
            return _SrvGraph(directed)

        def _graph_add_node(args):
            interpreter._expect_args('graph_add_node', args, 2)
            g, node = args
            if not isinstance(g, _SrvGraph):
                raise RuntimeError("graph_add_node: first argument must be a graph")
            g.add_node(node)
            return g

        def _graph_add_edge(args):
            if len(args) == 3:
                g, u, v = args
                w = 1
            elif len(args) == 4:
                g, u, v, w = args
            else:
                raise RuntimeError("graph_add_edge expects 3 or 4 arguments: (graph, u, v[, weight])")
            if not isinstance(g, _SrvGraph):
                raise RuntimeError("graph_add_edge: first argument must be a graph")
            g.add_edge(u, v, w)
            return g

        def _graph_neighbors(args):
            interpreter._expect_args('graph_neighbors', args, 2)
            g, node = args
            if not isinstance(g, _SrvGraph):
                raise RuntimeError("graph_neighbors: first argument must be a graph")
            return g.neighbors(node)

        def _graph_nodes(args):
            interpreter._expect_args('graph_nodes', args, 1)
            g = args[0]
            if not isinstance(g, _SrvGraph):
                raise RuntimeError("graph_nodes: argument must be a graph")
            return g.nodes()

        def _graph_edges(args):
            interpreter._expect_args('graph_edges', args, 1)
            g = args[0]
            if not isinstance(g, _SrvGraph):
                raise RuntimeError("graph_edges: argument must be a graph")
            return g.edges()

        def _graph_has_node(args):
            interpreter._expect_args('graph_has_node', args, 2)
            g, node = args
            if not isinstance(g, _SrvGraph):
                raise RuntimeError("graph_has_node: first argument must be a graph")
            return g.has_node(node)

        def _graph_has_edge(args):
            interpreter._expect_args('graph_has_edge', args, 3)
            g, u, v = args
            if not isinstance(g, _SrvGraph):
                raise RuntimeError("graph_has_edge: first argument must be a graph")
            return g.has_edge(u, v)

        def _graph_degree(args):
            interpreter._expect_args('graph_degree', args, 2)
            g, node = args
            if not isinstance(g, _SrvGraph):
                raise RuntimeError("graph_degree: first argument must be a graph")
            return g.degree(node)

        def _graph_remove_node(args):
            interpreter._expect_args('graph_remove_node', args, 2)
            g, node = args
            if not isinstance(g, _SrvGraph):
                raise RuntimeError("graph_remove_node: first argument must be a graph")
            g.remove_node(node)
            return g

        def _graph_remove_edge(args):
            interpreter._expect_args('graph_remove_edge', args, 3)
            g, u, v = args
            if not isinstance(g, _SrvGraph):
                raise RuntimeError("graph_remove_edge: first argument must be a graph")
            g.remove_edge(u, v)
            return g

        def _graph_bfs(args):
            interpreter._expect_args('graph_bfs', args, 2)
            g, start = args
            if not isinstance(g, _SrvGraph):
                raise RuntimeError("graph_bfs: first argument must be a graph")
            return g.bfs(start)

        def _graph_dfs(args):
            interpreter._expect_args('graph_dfs', args, 2)
            g, start = args
            if not isinstance(g, _SrvGraph):
                raise RuntimeError("graph_dfs: first argument must be a graph")
            return g.dfs(start)

        def _graph_shortest_path(args):
            interpreter._expect_args('graph_shortest_path', args, 3)
            g, start, end = args
            if not isinstance(g, _SrvGraph):
                raise RuntimeError("graph_shortest_path: first argument must be a graph")
            return g.shortest_path(start, end)

        def _graph_connected(args):
            interpreter._expect_args('graph_connected', args, 3)
            g, u, v = args
            if not isinstance(g, _SrvGraph):
                raise RuntimeError("graph_connected: first argument must be a graph")
            return g.connected(u, v)

        self.builtins['graph_create'] = _graph_create
        self.builtins['graph_add_node'] = _graph_add_node
        self.builtins['graph_add_edge'] = _graph_add_edge
        self.builtins['graph_neighbors'] = _graph_neighbors
        self.builtins['graph_nodes'] = _graph_nodes
        self.builtins['graph_edges'] = _graph_edges
        self.builtins['graph_has_node'] = _graph_has_node
        self.builtins['graph_has_edge'] = _graph_has_edge
        self.builtins['graph_degree'] = _graph_degree
        self.builtins['graph_remove_node'] = _graph_remove_node
        self.builtins['graph_remove_edge'] = _graph_remove_edge
        self.builtins['graph_bfs'] = _graph_bfs
        self.builtins['graph_dfs'] = _graph_dfs
        self.builtins['graph_shortest_path'] = _graph_shortest_path
        self.builtins['graph_connected'] = _graph_connected

    def _register_json_builtins(self):
        """Register JSON manipulation builtins.

        Provides ``json_encode``, ``json_decode``, ``json_pretty``,
        ``json_get``, ``json_set``, ``json_delete``, ``json_keys``,
        ``json_values``, ``json_has``, ``json_merge``, ``json_flatten``,
        ``json_query``.
        """
        interpreter = self

        # ── JSON builtins ──────────────────────────────────────────
        import json as _json

        def _json_encode(args):
            interpreter._expect_args('json_encode', args, 1)
            try:
                return _json.dumps(args[0])
            except (TypeError, ValueError) as e:
                raise RuntimeError(f"json_encode: {e}")

        def _json_decode(args):
            interpreter._expect_args('json_decode', args, 1)
            if not isinstance(args[0], str):
                raise RuntimeError("json_decode: argument must be a string")
            try:
                return _json.loads(args[0])
            except _json.JSONDecodeError as e:
                raise RuntimeError(f"json_decode: {e}")

        def _json_pretty(args):
            if len(args) == 1:
                indent = 2
            elif len(args) == 2:
                indent = int(args[1])
            else:
                raise RuntimeError("json_pretty: expected 1-2 arguments")
            try:
                return _json.dumps(args[0], indent=indent, sort_keys=True)
            except (TypeError, ValueError) as e:
                raise RuntimeError(f"json_pretty: {e}")

        def _json_get(args):
            interpreter._expect_args('json_get', args, 2)
            obj, path = args
            if not isinstance(path, str):
                raise RuntimeError("json_get: path must be a string")
            keys = path.split('.')
            current = obj
            for key in keys:
                if isinstance(current, dict):
                    if key not in current:
                        return None
                    current = current[key]
                elif isinstance(current, list):
                    try:
                        current = current[int(key)]
                    except (ValueError, IndexError):
                        return None
                else:
                    return None
            return current

        def _json_set(args):
            interpreter._expect_args('json_set', args, 3)
            obj, path, value = args
            if not isinstance(path, str):
                raise RuntimeError("json_set: path must be a string")
            import copy
            result = copy.deepcopy(obj) if isinstance(obj, (dict, list)) else obj
            keys = path.split('.')
            current = result
            for key in keys[:-1]:
                if isinstance(current, dict):
                    if key not in current:
                        current[key] = {}
                    current = current[key]
                elif isinstance(current, list):
                    current = current[int(key)]
                else:
                    raise RuntimeError(f"json_set: cannot traverse into {type(current)}")
            last_key = keys[-1]
            if isinstance(current, dict):
                current[last_key] = value
            elif isinstance(current, list):
                current[int(last_key)] = value
            return result

        def _json_delete(args):
            interpreter._expect_args('json_delete', args, 2)
            obj, path = args
            if not isinstance(path, str):
                raise RuntimeError("json_delete: path must be a string")
            import copy
            result = copy.deepcopy(obj) if isinstance(obj, (dict, list)) else obj
            keys = path.split('.')
            current = result
            for key in keys[:-1]:
                if isinstance(current, dict):
                    if key not in current:
                        return result
                    current = current[key]
                elif isinstance(current, list):
                    try:
                        current = current[int(key)]
                    except (ValueError, IndexError):
                        return result
                else:
                    return result
            last_key = keys[-1]
            if isinstance(current, dict) and last_key in current:
                del current[last_key]
            elif isinstance(current, list):
                try:
                    del current[int(last_key)]
                except (ValueError, IndexError):
                    pass
            return result

        def _json_keys(args):
            interpreter._expect_args('json_keys', args, 1)
            if not isinstance(args[0], dict):
                raise RuntimeError("json_keys: argument must be a map/dict")
            return list(args[0].keys())

        def _json_values(args):
            interpreter._expect_args('json_values', args, 1)
            if not isinstance(args[0], dict):
                raise RuntimeError("json_values: argument must be a map/dict")
            return list(args[0].values())

        def _json_has(args):
            interpreter._expect_args('json_has', args, 2)
            obj, path = args
            if not isinstance(path, str):
                raise RuntimeError("json_has: path must be a string")
            keys = path.split('.')
            current = obj
            for key in keys:
                if isinstance(current, dict):
                    if key not in current:
                        return False
                    current = current[key]
                elif isinstance(current, list):
                    try:
                        current = current[int(key)]
                    except (ValueError, IndexError):
                        return False
                else:
                    return False
            return True

        def _json_merge(args):
            interpreter._expect_args('json_merge', args, 2)
            a, b = args
            if not isinstance(a, dict) or not isinstance(b, dict):
                raise RuntimeError("json_merge: both arguments must be maps/dicts")
            import copy
            result = copy.deepcopy(a)
            result.update(copy.deepcopy(b))
            return result

        def _json_flatten(args):
            interpreter._expect_args('json_flatten', args, 1)
            obj = args[0]
            if not isinstance(obj, dict):
                raise RuntimeError("json_flatten: argument must be a map/dict")
            result = {}
            def _flatten(current, prefix):
                if isinstance(current, dict):
                    for k, v in current.items():
                        new_key = f"{prefix}.{k}" if prefix else k
                        _flatten(v, new_key)
                elif isinstance(current, list):
                    for i, v in enumerate(current):
                        new_key = f"{prefix}.{i}" if prefix else str(i)
                        _flatten(v, new_key)
                else:
                    result[prefix] = current
            _flatten(obj, "")
            return result

        def _json_query(args):
            """json_query(obj, key, value) - find all objects in nested structure where key==value"""
            interpreter._expect_args('json_query', args, 3)
            obj, key, value = args
            if not isinstance(key, str):
                raise RuntimeError("json_query: key must be a string")
            results = []
            def _search(current):
                if isinstance(current, dict):
                    if key in current and current[key] == value:
                        results.append(current)
                    for v in current.values():
                        _search(v)
                elif isinstance(current, list):
                    for item in current:
                        _search(item)
            _search(obj)
            return results

        self.builtins['json_encode'] = _json_encode
        self.builtins['json_decode'] = _json_decode
        self.builtins['json_pretty'] = _json_pretty
        self.builtins['json_get'] = _json_get
        self.builtins['json_set'] = _json_set
        self.builtins['json_delete'] = _json_delete
        self.builtins['json_keys'] = _json_keys
        self.builtins['json_values'] = _json_values
        self.builtins['json_has'] = _json_has
        self.builtins['json_merge'] = _json_merge
        self.builtins['json_flatten'] = _json_flatten
        self.builtins['json_query'] = _json_query

    # ── Heap / Priority Queue builtins ───────────────────

    def _register_heap_builtins(self):
        """Register min-heap (priority queue) builtins.

        Provides ``heap_create``, ``heap_push``, ``heap_pop``, ``heap_peek``,
        ``heap_size``, ``heap_is_empty``, ``heap_to_list``, ``heap_clear``,
        ``heap_merge``, ``heap_push_pop``, ``heap_replace``.

        A heap is represented as a plain list managed by Python's heapq module.
        Items are stored as [priority, value] pairs so any value type works.
        """
        import heapq
        interpreter = self

        _HEAP_TAG = '__srvheap__'

        def _is_heap(h):
            return isinstance(h, dict) and h.get('__type__') == _HEAP_TAG

        def _assert_heap(name, h):
            if not _is_heap(h):
                raise RuntimeError(f"{name}: first argument must be a heap (created with heap_create)")

        # heap_create() -> new empty heap
        def _heap_create(args):
            return {'__type__': _HEAP_TAG, 'data': [], '_counter': 0.0}

        # heap_push(heap, priority, value) -> nil  (mutates heap)
        def _heap_push(args):
            interpreter._expect_args('heap_push', args, 3)
            _assert_heap('heap_push', args[0])
            h = args[0]
            priority = args[1]
            if not isinstance(priority, (int, float)):
                raise RuntimeError("heap_push: priority must be a number")
            cnt = h['_counter']
            h['_counter'] = cnt + 1.0
            heapq.heappush(h['data'], [float(priority), cnt, args[2]])
            return None

        # heap_pop(heap) -> value with lowest priority (removes it)
        def _heap_pop(args):
            interpreter._expect_args('heap_pop', args, 1)
            _assert_heap('heap_pop', args[0])
            if len(args[0]['data']) == 0:
                raise RuntimeError("heap_pop: heap is empty")
            entry = heapq.heappop(args[0]['data'])
            return entry[2]

        # heap_peek(heap) -> value with lowest priority (does not remove)
        def _heap_peek(args):
            interpreter._expect_args('heap_peek', args, 1)
            _assert_heap('heap_peek', args[0])
            if len(args[0]['data']) == 0:
                raise RuntimeError("heap_peek: heap is empty")
            return args[0]['data'][0][2]

        # heap_size(heap) -> number of items
        def _heap_size(args):
            interpreter._expect_args('heap_size', args, 1)
            _assert_heap('heap_size', args[0])
            return float(len(args[0]['data']))

        # heap_is_empty(heap) -> bool
        def _heap_is_empty(args):
            interpreter._expect_args('heap_is_empty', args, 1)
            _assert_heap('heap_is_empty', args[0])
            return len(args[0]['data']) == 0

        # heap_to_list(heap) -> list of [priority, value] pairs sorted by priority
        def _heap_to_list(args):
            interpreter._expect_args('heap_to_list', args, 1)
            _assert_heap('heap_to_list', args[0])
            sorted_entries = sorted(args[0]['data'])
            return [[e[0], e[2]] for e in sorted_entries]

        # heap_clear(heap) -> nil (removes all items)
        def _heap_clear(args):
            interpreter._expect_args('heap_clear', args, 1)
            _assert_heap('heap_clear', args[0])
            args[0]['data'] = []
            args[0]['_counter'] = 0.0
            return None

        # heap_merge(heap1, heap2) -> new heap containing all items from both
        def _heap_merge(args):
            interpreter._expect_args('heap_merge', args, 2)
            _assert_heap('heap_merge', args[0])
            _assert_heap('heap_merge', args[1])
            merged = {'__type__': _HEAP_TAG, 'data': [], '_counter': 0.0}
            combined = list(args[0]['data']) + list(args[1]['data'])
            # Re-index counters for stable ordering
            cnt = 0.0
            for entry in sorted(combined):
                heapq.heappush(merged['data'], [entry[0], cnt, entry[2]])
                cnt += 1.0
            merged['_counter'] = cnt
            return merged

        # heap_push_pop(heap, priority, value) -> pops and returns smallest after pushing
        def _heap_push_pop(args):
            interpreter._expect_args('heap_push_pop', args, 3)
            _assert_heap('heap_push_pop', args[0])
            h = args[0]
            priority = args[1]
            if not isinstance(priority, (int, float)):
                raise RuntimeError("heap_push_pop: priority must be a number")
            cnt = h['_counter']
            h['_counter'] = cnt + 1.0
            entry = heapq.heappushpop(h['data'], [float(priority), cnt, args[2]])
            return entry[2]

        # heap_replace(heap, priority, value) -> pops smallest, then pushes new item
        def _heap_replace(args):
            interpreter._expect_args('heap_replace', args, 3)
            _assert_heap('heap_replace', args[0])
            h = args[0]
            if len(h['data']) == 0:
                raise RuntimeError("heap_replace: heap is empty")
            priority = args[1]
            if not isinstance(priority, (int, float)):
                raise RuntimeError("heap_replace: priority must be a number")
            cnt = h['_counter']
            h['_counter'] = cnt + 1.0
            entry = heapq.heapreplace(h['data'], [float(priority), cnt, args[2]])
            return entry[2]

        self.builtins['heap_create'] = _heap_create
        self.builtins['heap_push'] = _heap_push
        self.builtins['heap_pop'] = _heap_pop
        self.builtins['heap_peek'] = _heap_peek
        self.builtins['heap_size'] = _heap_size
        self.builtins['heap_is_empty'] = _heap_is_empty
        self.builtins['heap_to_list'] = _heap_to_list
        self.builtins['heap_clear'] = _heap_clear
        self.builtins['heap_merge'] = _heap_merge
        self.builtins['heap_push_pop'] = _heap_push_pop
        self.builtins['heap_replace'] = _heap_replace

        # ── Trie (Prefix Tree) builtins ──────────────────────────────
        class _TrieNode:
            __slots__ = ('children', 'is_end')
            def __init__(self):
                self.children = {}
                self.is_end = False

        def _trie_create(args):
            return {'_type': 'trie', 'root': _TrieNode(), 'size': 0}

        def _trie_insert(args):
            if len(args) != 2:
                raise RuntimeError("trie_insert: expected 2 arguments (trie, word)")
            t, word = args
            if not isinstance(t, dict) or t.get('_type') != 'trie':
                raise RuntimeError("trie_insert: first argument must be a trie")
            if not isinstance(word, str):
                raise RuntimeError("trie_insert: word must be a string")
            node = t['root']
            for ch in word:
                if ch not in node.children:
                    node.children[ch] = _TrieNode()
                node = node.children[ch]
            if not node.is_end:
                node.is_end = True
                t['size'] += 1
            return t

        def _trie_search(args):
            if len(args) != 2:
                raise RuntimeError("trie_search: expected 2 arguments (trie, word)")
            t, word = args
            if not isinstance(t, dict) or t.get('_type') != 'trie':
                raise RuntimeError("trie_search: first argument must be a trie")
            if not isinstance(word, str):
                raise RuntimeError("trie_search: word must be a string")
            node = t['root']
            for ch in word:
                if ch not in node.children:
                    return False
                node = node.children[ch]
            return node.is_end

        def _trie_starts_with(args):
            if len(args) != 2:
                raise RuntimeError("trie_starts_with: expected 2 arguments (trie, prefix)")
            t, prefix = args
            if not isinstance(t, dict) or t.get('_type') != 'trie':
                raise RuntimeError("trie_starts_with: first argument must be a trie")
            if not isinstance(prefix, str):
                raise RuntimeError("trie_starts_with: prefix must be a string")
            node = t['root']
            for ch in prefix:
                if ch not in node.children:
                    return False
                node = node.children[ch]
            return True

        def _trie_delete(args):
            if len(args) != 2:
                raise RuntimeError("trie_delete: expected 2 arguments (trie, word)")
            t, word = args
            if not isinstance(t, dict) or t.get('_type') != 'trie':
                raise RuntimeError("trie_delete: first argument must be a trie")
            if not isinstance(word, str):
                raise RuntimeError("trie_delete: word must be a string")
            def _delete(node, word, depth):
                if depth == len(word):
                    if not node.is_end:
                        return False
                    node.is_end = False
                    return len(node.children) == 0
                ch = word[depth]
                if ch not in node.children:
                    return False
                should_remove = _delete(node.children[ch], word, depth + 1)
                if should_remove:
                    del node.children[ch]
                    return not node.is_end and len(node.children) == 0
                return False
            existed = _trie_search([t, word])
            _delete(t['root'], word, 0)
            if existed and not _trie_search([t, word]):
                t['size'] = max(0, t['size'] - 1)
            return t

        def _trie_collect_words(node, prefix, limit=None):
            """Collect words from a trie node, optionally up to *limit*."""
            results = []
            def _walk(n, current):
                if limit is not None and len(results) >= limit:
                    return
                if n.is_end:
                    results.append(current)
                for ch in sorted(n.children.keys()):
                    if limit is not None and len(results) >= limit:
                        return
                    _walk(n.children[ch], current + ch)
            _walk(node, prefix)
            return results

        def _trie_autocomplete(args):
            if len(args) < 2 or len(args) > 3:
                raise RuntimeError("trie_autocomplete: expected 2-3 arguments (trie, prefix, [limit])")
            t = args[0]
            prefix = args[1]
            limit = int(args[2]) if len(args) == 3 else 10
            if not isinstance(t, dict) or t.get('_type') != 'trie':
                raise RuntimeError("trie_autocomplete: first argument must be a trie")
            if not isinstance(prefix, str):
                raise RuntimeError("trie_autocomplete: prefix must be a string")
            node = t['root']
            for ch in prefix:
                if ch not in node.children:
                    return []
                node = node.children[ch]
            return _trie_collect_words(node, prefix, limit)

        def _trie_size(args):
            if len(args) != 1:
                raise RuntimeError("trie_size: expected 1 argument (trie)")
            t = args[0]
            if not isinstance(t, dict) or t.get('_type') != 'trie':
                raise RuntimeError("trie_size: argument must be a trie")
            return float(t['size'])

        def _trie_words(args):
            if len(args) != 1:
                raise RuntimeError("trie_words: expected 1 argument (trie)")
            t = args[0]
            if not isinstance(t, dict) or t.get('_type') != 'trie':
                raise RuntimeError("trie_words: argument must be a trie")
            return _trie_collect_words(t['root'], "")

        def _trie_longest_prefix(args):
            if len(args) != 2:
                raise RuntimeError("trie_longest_prefix: expected 2 arguments (trie, word)")
            t, word = args
            if not isinstance(t, dict) or t.get('_type') != 'trie':
                raise RuntimeError("trie_longest_prefix: first argument must be a trie")
            if not isinstance(word, str):
                raise RuntimeError("trie_longest_prefix: word must be a string")
            node = t['root']
            longest = ""
            current = ""
            for ch in word:
                if ch not in node.children:
                    break
                node = node.children[ch]
                current += ch
                if node.is_end:
                    longest = current
            return longest

        def _trie_count_prefix(args):
            if len(args) != 2:
                raise RuntimeError("trie_count_prefix: expected 2 arguments (trie, prefix)")
            t, prefix = args
            if not isinstance(t, dict) or t.get('_type') != 'trie':
                raise RuntimeError("trie_count_prefix: first argument must be a trie")
            if not isinstance(prefix, str):
                raise RuntimeError("trie_count_prefix: prefix must be a string")
            node = t['root']
            for ch in prefix:
                if ch not in node.children:
                    return 0.0
                node = node.children[ch]
            count = [0]
            def _count(node):
                if node.is_end:
                    count[0] += 1
                for child in node.children.values():
                    _count(child)
            _count(node)
            return float(count[0])

        self.builtins['trie_create'] = _trie_create
        self.builtins['trie_insert'] = _trie_insert
        self.builtins['trie_search'] = _trie_search
        self.builtins['trie_starts_with'] = _trie_starts_with
        self.builtins['trie_delete'] = _trie_delete
        self.builtins['trie_autocomplete'] = _trie_autocomplete
        self.builtins['trie_size'] = _trie_size
        self.builtins['trie_words'] = _trie_words
        self.builtins['trie_longest_prefix'] = _trie_longest_prefix
        self.builtins['trie_count_prefix'] = _trie_count_prefix

    def _register_linkedlist_builtins(self):
        """Register linked-list builtins."""
        def _ll_create(args):
            if len(args) == 0:
                return _SrvLinkedList()
            if len(args) == 1 and isinstance(args[0], list):
                return _SrvLinkedList(args[0])
            raise RuntimeError("ll_create: expects 0 args or 1 list argument")

        def _ll_push_front(args):
            self._expect_args('ll_push_front', args, 2)
            ll, val = args
            if not isinstance(ll, _SrvLinkedList):
                raise RuntimeError("ll_push_front: first argument must be a linked list")
            ll.push_front(val)
            return val

        def _ll_push_back(args):
            self._expect_args('ll_push_back', args, 2)
            ll, val = args
            if not isinstance(ll, _SrvLinkedList):
                raise RuntimeError("ll_push_back: first argument must be a linked list")
            ll.push_back(val)
            return val

        def _ll_pop_front(args):
            self._expect_args('ll_pop_front', args, 1)
            ll = args[0]
            if not isinstance(ll, _SrvLinkedList):
                raise RuntimeError("ll_pop_front: argument must be a linked list")
            return ll.pop_front()

        def _ll_pop_back(args):
            self._expect_args('ll_pop_back', args, 1)
            ll = args[0]
            if not isinstance(ll, _SrvLinkedList):
                raise RuntimeError("ll_pop_back: argument must be a linked list")
            return ll.pop_back()

        def _ll_get(args):
            self._expect_args('ll_get', args, 2)
            ll, idx = args
            if not isinstance(ll, _SrvLinkedList):
                raise RuntimeError("ll_get: first argument must be a linked list")
            return ll.get(int(idx))

        def _ll_insert_at(args):
            self._expect_args('ll_insert_at', args, 3)
            ll, idx, val = args
            if not isinstance(ll, _SrvLinkedList):
                raise RuntimeError("ll_insert_at: first argument must be a linked list")
            ll.insert_at(int(idx), val)
            return val

        def _ll_remove_at(args):
            self._expect_args('ll_remove_at', args, 2)
            ll, idx = args
            if not isinstance(ll, _SrvLinkedList):
                raise RuntimeError("ll_remove_at: first argument must be a linked list")
            return ll.remove_at(int(idx))

        def _ll_size(args):
            self._expect_args('ll_size', args, 1)
            ll = args[0]
            if not isinstance(ll, _SrvLinkedList):
                raise RuntimeError("ll_size: argument must be a linked list")
            return ll.size()

        def _ll_is_empty(args):
            self._expect_args('ll_is_empty', args, 1)
            ll = args[0]
            if not isinstance(ll, _SrvLinkedList):
                raise RuntimeError("ll_is_empty: argument must be a linked list")
            return ll.is_empty()

        def _ll_to_list(args):
            self._expect_args('ll_to_list', args, 1)
            ll = args[0]
            if not isinstance(ll, _SrvLinkedList):
                raise RuntimeError("ll_to_list: argument must be a linked list")
            return ll.to_list()

        def _ll_reverse(args):
            self._expect_args('ll_reverse', args, 1)
            ll = args[0]
            if not isinstance(ll, _SrvLinkedList):
                raise RuntimeError("ll_reverse: argument must be a linked list")
            ll.reverse()
            return ll

        def _ll_clear(args):
            self._expect_args('ll_clear', args, 1)
            ll = args[0]
            if not isinstance(ll, _SrvLinkedList):
                raise RuntimeError("ll_clear: argument must be a linked list")
            ll.clear()
            return ll

        def _ll_peek_front(args):
            self._expect_args('ll_peek_front', args, 1)
            ll = args[0]
            if not isinstance(ll, _SrvLinkedList):
                raise RuntimeError("ll_peek_front: argument must be a linked list")
            return ll.peek_front()

        def _ll_peek_back(args):
            self._expect_args('ll_peek_back', args, 1)
            ll = args[0]
            if not isinstance(ll, _SrvLinkedList):
                raise RuntimeError("ll_peek_back: argument must be a linked list")
            return ll.peek_back()

        def _ll_from_list(args):
            self._expect_args('ll_from_list', args, 1)
            lst = args[0]
            if not isinstance(lst, list):
                raise RuntimeError("ll_from_list: argument must be a list")
            return _SrvLinkedList(lst)

        self.builtins['ll_create'] = _ll_create
        self.builtins['ll_push_front'] = _ll_push_front
        self.builtins['ll_push_back'] = _ll_push_back
        self.builtins['ll_pop_front'] = _ll_pop_front
        self.builtins['ll_pop_back'] = _ll_pop_back
        self.builtins['ll_get'] = _ll_get
        self.builtins['ll_insert_at'] = _ll_insert_at
        self.builtins['ll_remove_at'] = _ll_remove_at
        self.builtins['ll_size'] = _ll_size
        self.builtins['ll_is_empty'] = _ll_is_empty
        self.builtins['ll_to_list'] = _ll_to_list
        self.builtins['ll_reverse'] = _ll_reverse
        self.builtins['ll_clear'] = _ll_clear
        self.builtins['ll_peek_front'] = _ll_peek_front
        self.builtins['ll_peek_back'] = _ll_peek_back
        self.builtins['ll_from_list'] = _ll_from_list

    def _register_bloom_builtins(self):
        """Register Bloom filter builtins."""
        import hashlib as _hashlib
        import struct as _struct

        class _BloomFilter:
            """Simple Bloom filter backed by a Python bytearray."""
            __slots__ = ('_bits', '_size', '_num_hashes', '_count')

            def __init__(self, size=1024, num_hashes=3):
                self._size = max(8, int(size))
                self._num_hashes = max(1, int(num_hashes))
                self._bits = bytearray(self._size)
                self._count = 0

            def _hashes(self, item):
                raw = str(item).encode('utf-8')
                h1 = int.from_bytes(_hashlib.md5(raw).digest()[:8], 'little')
                h2 = int.from_bytes(_hashlib.md5(raw).digest()[8:], 'little')
                for i in range(self._num_hashes):
                    yield (h1 + i * h2) % self._size

            def add(self, item):
                for idx in self._hashes(item):
                    self._bits[idx] = 1
                self._count += 1

            def contains(self, item):
                return all(self._bits[idx] for idx in self._hashes(item))

            def clear(self):
                self._bits = bytearray(self._size)
                self._count = 0

            def false_positive_rate(self):
                if self._count == 0:
                    return 0.0
                bits_set = sum(self._bits)
                return (bits_set / self._size) ** self._num_hashes

            def info(self):
                bits_set = sum(self._bits)
                return {
                    'size': self._size,
                    'num_hashes': self._num_hashes,
                    'items_added': self._count,
                    'bits_set': bits_set,
                    'fill_ratio': round(bits_set / self._size, 4),
                    'est_fpr': round(self.false_positive_rate(), 6),
                }

            def __repr__(self):
                return f"BloomFilter(size={self._size}, hashes={self._num_hashes}, items={self._count})"

        def _bloom_create(args):
            size = 1024
            num_hashes = 3
            if len(args) >= 1:
                size = int(args[0])
            if len(args) >= 2:
                num_hashes = int(args[1])
            if len(args) > 2:
                raise RuntimeError("bloom_create: expected 0-2 arguments (size, num_hashes)")
            return _BloomFilter(size, num_hashes)

        def _bloom_add(args):
            if len(args) != 2:
                raise RuntimeError("bloom_add: expected 2 arguments (bloom, item)")
            bf, item = args
            if not isinstance(bf, _BloomFilter):
                raise RuntimeError("bloom_add: first argument must be a bloom filter")
            bf.add(item)
            return None

        def _bloom_contains(args):
            if len(args) != 2:
                raise RuntimeError("bloom_contains: expected 2 arguments (bloom, item)")
            bf, item = args
            if not isinstance(bf, _BloomFilter):
                raise RuntimeError("bloom_contains: first argument must be a bloom filter")
            return bf.contains(item)

        def _bloom_size(args):
            if len(args) != 1:
                raise RuntimeError("bloom_size: expected 1 argument (bloom)")
            bf = args[0]
            if not isinstance(bf, _BloomFilter):
                raise RuntimeError("bloom_size: argument must be a bloom filter")
            return bf._count

        def _bloom_clear(args):
            if len(args) != 1:
                raise RuntimeError("bloom_clear: expected 1 argument (bloom)")
            bf = args[0]
            if not isinstance(bf, _BloomFilter):
                raise RuntimeError("bloom_clear: argument must be a bloom filter")
            bf.clear()
            return None

        def _bloom_false_positive_rate(args):
            if len(args) != 1:
                raise RuntimeError("bloom_false_positive_rate: expected 1 argument (bloom)")
            bf = args[0]
            if not isinstance(bf, _BloomFilter):
                raise RuntimeError("bloom_false_positive_rate: argument must be a bloom filter")
            return bf.false_positive_rate()

        def _bloom_merge(args):
            if len(args) != 2:
                raise RuntimeError("bloom_merge: expected 2 arguments (bloom1, bloom2)")
            bf1, bf2 = args
            if not isinstance(bf1, _BloomFilter) or not isinstance(bf2, _BloomFilter):
                raise RuntimeError("bloom_merge: both arguments must be bloom filters")
            if bf1._size != bf2._size or bf1._num_hashes != bf2._num_hashes:
                raise RuntimeError("bloom_merge: filters must have same size and num_hashes")
            merged = _BloomFilter(bf1._size, bf1._num_hashes)
            for i in range(bf1._size):
                merged._bits[i] = bf1._bits[i] | bf2._bits[i]
            merged._count = bf1._count + bf2._count
            return merged

        def _bloom_info(args):
            if len(args) != 1:
                raise RuntimeError("bloom_info: expected 1 argument (bloom)")
            bf = args[0]
            if not isinstance(bf, _BloomFilter):
                raise RuntimeError("bloom_info: argument must be a bloom filter")
            return bf.info()

        self.builtins['bloom_create'] = _bloom_create
        self.builtins['bloom_add'] = _bloom_add
        self.builtins['bloom_contains'] = _bloom_contains
        self.builtins['bloom_size'] = _bloom_size
        self.builtins['bloom_clear'] = _bloom_clear
        self.builtins['bloom_false_positive_rate'] = _bloom_false_positive_rate
        self.builtins['bloom_merge'] = _bloom_merge
        self.builtins['bloom_info'] = _bloom_info

    def _register_deque_builtins(self):
        """Register double-ended queue (deque) builtins."""
        from collections import deque as _deque

        class _SrvDeque:
            """Double-ended queue for sauravcode."""
            __slots__ = ('_data',)
            def __init__(self, items=None):
                self._data = _deque(items) if items else _deque()
            def __repr__(self):
                return f"Deque({list(self._data)})"

        def _deque_create(args):
            if len(args) == 0:
                return _SrvDeque()
            if len(args) == 1:
                if isinstance(args[0], list):
                    return _SrvDeque(args[0])
                raise RuntimeError("deque_create: argument must be a list")
            raise RuntimeError("deque_create: expected 0-1 arguments")

        def _check_deque(fn, dq):
            if not isinstance(dq, _SrvDeque):
                raise RuntimeError(f"{fn}: first argument must be a deque")

        def _deque_push_front(args):
            if len(args) != 2:
                raise RuntimeError("deque_push_front: expected 2 arguments (deque, item)")
            _check_deque('deque_push_front', args[0])
            args[0]._data.appendleft(args[1])
            return None

        def _deque_push_back(args):
            if len(args) != 2:
                raise RuntimeError("deque_push_back: expected 2 arguments (deque, item)")
            _check_deque('deque_push_back', args[0])
            args[0]._data.append(args[1])
            return None

        def _deque_pop_front(args):
            if len(args) != 1:
                raise RuntimeError("deque_pop_front: expected 1 argument (deque)")
            _check_deque('deque_pop_front', args[0])
            if not args[0]._data:
                raise RuntimeError("deque_pop_front: deque is empty")
            return args[0]._data.popleft()

        def _deque_pop_back(args):
            if len(args) != 1:
                raise RuntimeError("deque_pop_back: expected 1 argument (deque)")
            _check_deque('deque_pop_back', args[0])
            if not args[0]._data:
                raise RuntimeError("deque_pop_back: deque is empty")
            return args[0]._data.pop()

        def _deque_peek_front(args):
            if len(args) != 1:
                raise RuntimeError("deque_peek_front: expected 1 argument (deque)")
            _check_deque('deque_peek_front', args[0])
            if not args[0]._data:
                raise RuntimeError("deque_peek_front: deque is empty")
            return args[0]._data[0]

        def _deque_peek_back(args):
            if len(args) != 1:
                raise RuntimeError("deque_peek_back: expected 1 argument (deque)")
            _check_deque('deque_peek_back', args[0])
            if not args[0]._data:
                raise RuntimeError("deque_peek_back: deque is empty")
            return args[0]._data[-1]

        def _deque_size(args):
            if len(args) != 1:
                raise RuntimeError("deque_size: expected 1 argument (deque)")
            _check_deque('deque_size', args[0])
            return float(len(args[0]._data))

        def _deque_is_empty(args):
            if len(args) != 1:
                raise RuntimeError("deque_is_empty: expected 1 argument (deque)")
            _check_deque('deque_is_empty', args[0])
            return len(args[0]._data) == 0

        def _deque_to_list(args):
            if len(args) != 1:
                raise RuntimeError("deque_to_list: expected 1 argument (deque)")
            _check_deque('deque_to_list', args[0])
            return list(args[0]._data)

        def _deque_rotate(args):
            if len(args) != 2:
                raise RuntimeError("deque_rotate: expected 2 arguments (deque, n)")
            _check_deque('deque_rotate', args[0])
            n = args[1]
            if not isinstance(n, (int, float)):
                raise RuntimeError("deque_rotate: n must be a number")
            args[0]._data.rotate(int(n))
            return None

        def _deque_clear(args):
            if len(args) != 1:
                raise RuntimeError("deque_clear: expected 1 argument (deque)")
            _check_deque('deque_clear', args[0])
            args[0]._data.clear()
            return None

        self.builtins['deque_create'] = _deque_create
        self.builtins['deque_push_front'] = _deque_push_front
        self.builtins['deque_push_back'] = _deque_push_back
        self.builtins['deque_pop_front'] = _deque_pop_front
        self.builtins['deque_pop_back'] = _deque_pop_back
        self.builtins['deque_peek_front'] = _deque_peek_front
        self.builtins['deque_peek_back'] = _deque_peek_back
        self.builtins['deque_size'] = _deque_size
        self.builtins['deque_is_empty'] = _deque_is_empty
        self.builtins['deque_to_list'] = _deque_to_list
        self.builtins['deque_rotate'] = _deque_rotate
        self.builtins['deque_clear'] = _deque_clear

        # ── HTTP / Network builtins ──────────────────────────────
        import urllib.request, urllib.parse, urllib.error, base64 as _b64, json as _json_mod

        # NOTE: http_get / http_post are registered via _builtin_http_get /
        # _builtin_http_post (see _init_dispatch_tables) which route through
        # the SSRF-safe _http_request path.  No closure-based fallbacks are
        # defined here to avoid accidentally bypassing SSRF protection.

        def _url_parse(args):
            if len(args) != 1:
                raise RuntimeError("url_parse: expected 1 argument (url)")
            url = args[0]
            if not isinstance(url, str):
                raise RuntimeError("url_parse: argument must be a string")
            p = urllib.parse.urlparse(url)
            query_params = {}
            for k, v in urllib.parse.parse_qs(p.query).items():
                query_params[k] = v[0] if len(v) == 1 else v
            return {
                "scheme": p.scheme, "host": p.hostname or "",
                "port": p.port if p.port else 0,
                "path": p.path, "query": p.query,
                "fragment": p.fragment, "params": query_params
            }

        def _url_encode(args):
            if len(args) != 1:
                raise RuntimeError("url_encode: expected 1 argument (string or map)")
            val = args[0]
            if isinstance(val, dict):
                return urllib.parse.urlencode({str(k): str(v) for k, v in val.items()})
            if isinstance(val, str):
                return urllib.parse.quote(val, safe='')
            raise RuntimeError("url_encode: argument must be a string or map")

        def _url_decode(args):
            if len(args) != 1:
                raise RuntimeError("url_decode: expected 1 argument (string)")
            if not isinstance(args[0], str):
                raise RuntimeError("url_decode: argument must be a string")
            return urllib.parse.unquote(args[0])

        def _base64_encode(args):
            if len(args) != 1:
                raise RuntimeError("base64_encode: expected 1 argument (string)")
            if not isinstance(args[0], str):
                raise RuntimeError("base64_encode: argument must be a string")
            return _b64.b64encode(args[0].encode('utf-8')).decode('ascii')

        def _base64_decode(args):
            if len(args) != 1:
                raise RuntimeError("base64_decode: expected 1 argument (string)")
            if not isinstance(args[0], str):
                raise RuntimeError("base64_decode: argument must be a string")
            try:
                return _b64.b64decode(args[0]).decode('utf-8')
            except Exception as e:
                raise RuntimeError(f"base64_decode: {e}")

        self.builtins['url_parse'] = _url_parse
        self.builtins['url_encode'] = _url_encode
        self.builtins['url_decode'] = _url_decode
        self.builtins['base64_encode'] = _base64_encode
        self.builtins['base64_decode'] = _base64_decode

    def _register_interval_builtins(self):
        """Register numeric interval/range builtins."""

        class _SrvInterval:
            """Closed numeric interval [low, high] for sauravcode."""
            __slots__ = ('low', 'high')
            def __init__(self, low, high):
                self.low = float(min(low, high))
                self.high = float(max(low, high))
            def __repr__(self):
                return f"Interval({self.low}, {self.high})"

        def _check_num(fn, v, name='argument'):
            if not isinstance(v, (int, float)):
                raise RuntimeError(f"{fn}: {name} must be a number")

        def _check_interval(fn, v):
            if not isinstance(v, _SrvInterval):
                raise RuntimeError(f"{fn}: argument must be an interval")

        def _interval_create(args):
            if len(args) != 2:
                raise RuntimeError("interval_create: expected 2 arguments (low, high)")
            _check_num('interval_create', args[0], 'low')
            _check_num('interval_create', args[1], 'high')
            return _SrvInterval(args[0], args[1])

        def _interval_contains(args):
            if len(args) != 2:
                raise RuntimeError("interval_contains: expected 2 arguments (interval, value)")
            _check_interval('interval_contains', args[0])
            _check_num('interval_contains', args[1], 'value')
            return args[0].low <= args[1] <= args[0].high

        def _interval_overlaps(args):
            if len(args) != 2:
                raise RuntimeError("interval_overlaps: expected 2 arguments (interval, interval)")
            _check_interval('interval_overlaps', args[0])
            _check_interval('interval_overlaps', args[1])
            return args[0].low <= args[1].high and args[1].low <= args[0].high

        def _interval_merge(args):
            if len(args) != 2:
                raise RuntimeError("interval_merge: expected 2 arguments (interval, interval)")
            _check_interval('interval_merge', args[0])
            _check_interval('interval_merge', args[1])
            a, b = args[0], args[1]
            if a.low > b.high or b.low > a.high:
                raise RuntimeError("interval_merge: intervals do not overlap or touch")
            return _SrvInterval(min(a.low, b.low), max(a.high, b.high))

        def _interval_intersection(args):
            if len(args) != 2:
                raise RuntimeError("interval_intersection: expected 2 arguments (interval, interval)")
            _check_interval('interval_intersection', args[0])
            _check_interval('interval_intersection', args[1])
            a, b = args[0], args[1]
            lo = max(a.low, b.low)
            hi = min(a.high, b.high)
            if lo > hi:
                return None
            return _SrvInterval(lo, hi)

        def _interval_gap(args):
            if len(args) != 2:
                raise RuntimeError("interval_gap: expected 2 arguments (interval, interval)")
            _check_interval('interval_gap', args[0])
            _check_interval('interval_gap', args[1])
            a, b = args[0], args[1]
            if a.low <= b.high and b.low <= a.high:
                return None  # overlapping, no gap
            if a.high < b.low:
                return _SrvInterval(a.high, b.low)
            return _SrvInterval(b.high, a.low)

        def _interval_span(args):
            if len(args) != 2:
                raise RuntimeError("interval_span: expected 2 arguments (interval, interval)")
            _check_interval('interval_span', args[0])
            _check_interval('interval_span', args[1])
            return _SrvInterval(min(args[0].low, args[1].low), max(args[0].high, args[1].high))

        def _interval_width(args):
            if len(args) != 1:
                raise RuntimeError("interval_width: expected 1 argument (interval)")
            _check_interval('interval_width', args[0])
            return args[0].high - args[0].low

        def _interval_to_list(args):
            if len(args) != 1:
                raise RuntimeError("interval_to_list: expected 1 argument (interval)")
            _check_interval('interval_to_list', args[0])
            return [args[0].low, args[0].high]

        def _interval_merge_all(args):
            if len(args) != 1:
                raise RuntimeError("interval_merge_all: expected 1 argument (list of intervals)")
            lst = args[0]
            if not isinstance(lst, list):
                raise RuntimeError("interval_merge_all: argument must be a list of intervals")
            if len(lst) == 0:
                return []
            for item in lst:
                _check_interval('interval_merge_all', item)
            sorted_ivs = sorted(lst, key=lambda iv: iv.low)
            merged = [_SrvInterval(sorted_ivs[0].low, sorted_ivs[0].high)]
            for iv in sorted_ivs[1:]:
                top = merged[-1]
                if iv.low <= top.high:
                    merged[-1] = _SrvInterval(top.low, max(top.high, iv.high))
                else:
                    merged.append(_SrvInterval(iv.low, iv.high))
            return merged

        self.builtins['interval_create'] = _interval_create
        self.builtins['interval_contains'] = _interval_contains
        self.builtins['interval_overlaps'] = _interval_overlaps
        self.builtins['interval_merge'] = _interval_merge
        self.builtins['interval_intersection'] = _interval_intersection
        self.builtins['interval_gap'] = _interval_gap
        self.builtins['interval_span'] = _interval_span
        self.builtins['interval_width'] = _interval_width
        self.builtins['interval_to_list'] = _interval_to_list
        self.builtins['interval_merge_all'] = _interval_merge_all

    def _register_compression_builtins(self):
        """Register data compression builtins (zlib & gzip)."""
        import zlib as _zlib
        import gzip as _gzip
        import base64 as _b64

        def _compress(args):
            """compress(string [, level]) → base64-encoded zlib-compressed data."""
            if len(args) < 1 or len(args) > 2:
                raise RuntimeError("compress: expected 1-2 arguments (data, level)")
            data = str(args[0]).encode('utf-8')
            level = int(args[1]) if len(args) == 2 else 6
            level = max(-1, min(9, level))
            compressed = _zlib.compress(data, level)
            return _b64.b64encode(compressed).decode('ascii')

        def _decompress(args):
            """decompress(base64_string) → original string."""
            if len(args) != 1:
                raise RuntimeError("decompress: expected 1 argument (compressed_data)")
            raw = _b64.b64decode(str(args[0]))
            return _zlib.decompress(raw).decode('utf-8')

        def _gzip_compress(args):
            """gzip_compress(string [, level]) → base64-encoded gzip data."""
            if len(args) < 1 or len(args) > 2:
                raise RuntimeError("gzip_compress: expected 1-2 arguments (data, level)")
            data = str(args[0]).encode('utf-8')
            level = int(args[1]) if len(args) == 2 else 9
            level = max(0, min(9, level))
            compressed = _gzip.compress(data, compresslevel=level)
            return _b64.b64encode(compressed).decode('ascii')

        def _gzip_decompress(args):
            """gzip_decompress(base64_string) → original string."""
            if len(args) != 1:
                raise RuntimeError("gzip_decompress: expected 1 argument (compressed_data)")
            raw = _b64.b64decode(str(args[0]))
            return _gzip.decompress(raw).decode('utf-8')

        def _compress_ratio(args):
            """compress_ratio(string) → compression ratio as float (original/compressed)."""
            if len(args) != 1:
                raise RuntimeError("compress_ratio: expected 1 argument (data)")
            data = str(args[0]).encode('utf-8')
            if len(data) == 0:
                return 1.0
            compressed = _zlib.compress(data)
            return round(len(data) / len(compressed), 4)

        self.builtins['compress'] = _compress
        self.builtins['decompress'] = _decompress
        self.builtins['gzip_compress'] = _gzip_compress
        self.builtins['gzip_decompress'] = _gzip_decompress
        self.builtins['compress_ratio'] = _compress_ratio

    def _register_logging_builtins(self):
        """Register logging & diagnostics builtins."""
        import sys as _sys

        # Internal log storage
        _log_buffer = []
        _perf_timers = {}

        _LEVEL_NAMES = {'INFO': 'INFO', 'WARN': 'WARN', 'ERROR': 'ERROR', 'DEBUG': 'DEBUG'}
        _LEVEL_COLORS = {
            'INFO':  '\033[36m',   # cyan
            'WARN':  '\033[33m',   # yellow
            'ERROR': '\033[31m',   # red
            'DEBUG': '\033[90m',   # grey
        }
        _RESET = '\033[0m'

        def _log_at_level(level, args):
            if len(args) < 1:
                raise RuntimeError(f"log_{level.lower()}: expected at least 1 argument")
            msg = ' '.join(str(a) for a in args)
            timestamp = _datetime.now().strftime('%H:%M:%S.%f')[:-3]
            entry = {'level': level, 'message': msg, 'timestamp': timestamp}
            _log_buffer.append(entry)
            color = _LEVEL_COLORS.get(level, '')
            print(f"{color}[{level}] {timestamp} | {msg}{_RESET}")
            return msg

        def _log_info(args):
            return _log_at_level('INFO', args)

        def _log_warn(args):
            return _log_at_level('WARN', args)

        def _log_error(args):
            return _log_at_level('ERROR', args)

        def _log_debug(args):
            return _log_at_level('DEBUG', args)

        def _log_to_file(args):
            """log_to_file(filename [, clear]) → write log buffer to file. Pass true as 2nd arg to clear buffer."""
            if len(args) < 1 or len(args) > 2:
                raise RuntimeError("log_to_file: expected 1-2 arguments (filename [, clear])")
            filename = str(args[0])
            clear_after = bool(args[1]) if len(args) == 2 else False
            with open(filename, 'w', encoding='utf-8') as f:
                for entry in _log_buffer:
                    f.write(f"[{entry['level']}] {entry['timestamp']} | {entry['message']}\n")
            count = len(_log_buffer)
            if clear_after:
                _log_buffer.clear()
            return float(count)

        def _log_clear(args):
            """log_clear() → clear the in-memory log buffer. Returns count of cleared entries."""
            count = len(_log_buffer)
            _log_buffer.clear()
            return float(count)

        def _log_history(args):
            """log_history([level]) → return list of log entries, optionally filtered by level."""
            if len(args) > 1:
                raise RuntimeError("log_history: expected 0-1 arguments ([level])")
            level_filter = str(args[0]).upper() if len(args) == 1 else None
            results = []
            for entry in _log_buffer:
                if level_filter is None or entry['level'] == level_filter:
                    results.append(f"[{entry['level']}] {entry['timestamp']} | {entry['message']}")
            return results

        def _perf_start(args):
            """perf_start(label) → start a performance timer with the given label."""
            if len(args) != 1:
                raise RuntimeError("perf_start: expected 1 argument (label)")
            label = str(args[0])
            _perf_timers[label] = _time.perf_counter()
            return label

        def _perf_stop(args):
            """perf_stop(label) → stop timer and return elapsed seconds."""
            if len(args) != 1:
                raise RuntimeError("perf_stop: expected 1 argument (label)")
            label = str(args[0])
            if label not in _perf_timers:
                raise RuntimeError(f"perf_stop: no timer named '{label}'")
            elapsed = _time.perf_counter() - _perf_timers[label]
            del _perf_timers[label]
            return round(elapsed, 6)

        def _perf_elapsed(args):
            """perf_elapsed(label) → return elapsed seconds without stopping the timer."""
            if len(args) != 1:
                raise RuntimeError("perf_elapsed: expected 1 argument (label)")
            label = str(args[0])
            if label not in _perf_timers:
                raise RuntimeError(f"perf_elapsed: no timer named '{label}'")
            elapsed = _time.perf_counter() - _perf_timers[label]
            return round(elapsed, 6)

        self.builtins['log_info'] = _log_info
        self.builtins['log_warn'] = _log_warn
        self.builtins['log_error'] = _log_error
        self.builtins['log_debug'] = _log_debug
        self.builtins['log_to_file'] = _log_to_file
        self.builtins['log_clear'] = _log_clear
        self.builtins['log_history'] = _log_history
        self.builtins['perf_start'] = _perf_start
        self.builtins['perf_stop'] = _perf_stop
        self.builtins['perf_elapsed'] = _perf_elapsed

        # ── Table builtins ──────────────────────────────────────────
        def _table_create(args):
            """table_create() or table_create(headers_list) — create a new table."""
            if len(args) == 0:
                return {'__table__': True, 'headers': [], 'rows': []}
            if len(args) == 1:
                hdrs = args[0]
                if not isinstance(hdrs, list):
                    raise RuntimeError("table_create: argument must be a list of header strings")
                return {'__table__': True, 'headers': [str(h) for h in hdrs], 'rows': []}
            raise RuntimeError("table_create: expected 0 or 1 argument")

        def _ensure_table(name, val):
            if not isinstance(val, dict) or not val.get('__table__'):
                raise RuntimeError(f"{name}: first argument must be a table")
            return val

        def _table_add_row(args):
            """table_add_row(table, row_list) — add a row to the table; returns the table."""
            if len(args) != 2:
                raise RuntimeError("table_add_row: expected 2 arguments (table, row)")
            tbl = _ensure_table('table_add_row', args[0])
            row = args[1]
            if not isinstance(row, list):
                raise RuntimeError("table_add_row: second argument must be a list")
            # Auto-set headers from first row if empty
            if not tbl['headers']:
                tbl['headers'] = [f"col{i}" for i in range(len(row))]
            tbl['rows'].append(row)
            return tbl

        def _table_headers(args):
            """table_headers(table) — return list of header names."""
            if len(args) != 1:
                raise RuntimeError("table_headers: expected 1 argument")
            tbl = _ensure_table('table_headers', args[0])
            return list(tbl['headers'])

        def _table_size(args):
            """table_size(table) — return number of rows."""
            if len(args) != 1:
                raise RuntimeError("table_size: expected 1 argument")
            tbl = _ensure_table('table_size', args[0])
            return float(len(tbl['rows']))

        def _table_row(args):
            """table_row(table, index) — return a specific row as a list."""
            if len(args) != 2:
                raise RuntimeError("table_row: expected 2 arguments (table, index)")
            tbl = _ensure_table('table_row', args[0])
            idx = int(args[1])
            if idx < 0 or idx >= len(tbl['rows']):
                raise RuntimeError(f"table_row: index {idx} out of range (0..{len(tbl['rows'])-1})")
            return list(tbl['rows'][idx])

        def _table_column(args):
            """table_column(table, header_or_index) — return all values in a column."""
            if len(args) != 2:
                raise RuntimeError("table_column: expected 2 arguments (table, column)")
            tbl = _ensure_table('table_column', args[0])
            col = args[1]
            if isinstance(col, str):
                if col not in tbl['headers']:
                    raise RuntimeError(f"table_column: no column named '{col}'")
                idx = tbl['headers'].index(col)
            else:
                idx = int(col)
            return [r[idx] if idx < len(r) else None for r in tbl['rows']]

        def _table_print(args):
            """table_print(table) — pretty-print the table and return it."""
            if len(args) != 1:
                raise RuntimeError("table_print: expected 1 argument")
            tbl = _ensure_table('table_print', args[0])
            hdrs = tbl['headers']
            rows = tbl['rows']
            if not hdrs and not rows:
                print("(empty table)")
                return tbl
            # Calculate column widths
            all_rows = [hdrs] + [[str(c) for c in r] for r in rows]
            ncols = max(len(r) for r in all_rows)
            widths = [0] * ncols
            for r in all_rows:
                for i, c in enumerate(r):
                    widths[i] = max(widths[i], len(str(c)))
            # Print header
            hdr_line = " | ".join(str(hdrs[i] if i < len(hdrs) else "").ljust(widths[i]) for i in range(ncols))
            sep_line = "-+-".join("-" * widths[i] for i in range(ncols))
            print(hdr_line)
            print(sep_line)
            for r in rows:
                cells = [str(r[i] if i < len(r) else "").ljust(widths[i]) for i in range(ncols)]
                print(" | ".join(cells))
            return tbl

        def _table_sort(args):
            """table_sort(table, column) — sort rows by column; returns a new table."""
            if len(args) < 2 or len(args) > 3:
                raise RuntimeError("table_sort: expected 2-3 arguments (table, column, [reverse])")
            tbl = _ensure_table('table_sort', args[0])
            col = args[1]
            rev = bool(args[2]) if len(args) == 3 else False
            if isinstance(col, str):
                if col not in tbl['headers']:
                    raise RuntimeError(f"table_sort: no column named '{col}'")
                idx = tbl['headers'].index(col)
            else:
                idx = int(col)
            sorted_rows = sorted(tbl['rows'], key=lambda r: r[idx] if idx < len(r) else "", reverse=rev)
            return {'__table__': True, 'headers': list(tbl['headers']), 'rows': sorted_rows}

        def _table_filter(args):
            """table_filter(table, column, value) — keep only rows where column == value."""
            if len(args) != 3:
                raise RuntimeError("table_filter: expected 3 arguments (table, column, value)")
            tbl = _ensure_table('table_filter', args[0])
            col = args[1]
            val = args[2]
            if isinstance(col, str):
                if col not in tbl['headers']:
                    raise RuntimeError(f"table_filter: no column named '{col}'")
                idx = tbl['headers'].index(col)
            else:
                idx = int(col)
            filtered = [r for r in tbl['rows'] if (r[idx] if idx < len(r) else None) == val]
            return {'__table__': True, 'headers': list(tbl['headers']), 'rows': filtered}

        def _table_reverse(args):
            """table_reverse(table) — reverse row order; returns a new table."""
            if len(args) != 1:
                raise RuntimeError("table_reverse: expected 1 argument")
            tbl = _ensure_table('table_reverse', args[0])
            return {'__table__': True, 'headers': list(tbl['headers']), 'rows': list(reversed(tbl['rows']))}

        def _table_to_csv(args):
            """table_to_csv(table) — return CSV string of the table."""
            if len(args) != 1:
                raise RuntimeError("table_to_csv: expected 1 argument")
            tbl = _ensure_table('table_to_csv', args[0])
            lines = [",".join(str(h) for h in tbl['headers'])]
            for r in tbl['rows']:
                lines.append(",".join(str(c) for c in r))
            return "\n".join(lines)

        def _table_to_json(args):
            """table_to_json(table) — return JSON array of row objects."""
            import json as _json_mod
            if len(args) != 1:
                raise RuntimeError("table_to_json: expected 1 argument")
            tbl = _ensure_table('table_to_json', args[0])
            result = []
            for r in tbl['rows']:
                obj = {}
                for i, h in enumerate(tbl['headers']):
                    obj[h] = r[i] if i < len(r) else None
                result.append(obj)
            return _json_mod.dumps(result, indent=2)

        self.builtins['table_create'] = _table_create
        self.builtins['table_add_row'] = _table_add_row
        self.builtins['table_headers'] = _table_headers
        self.builtins['table_size'] = _table_size
        self.builtins['table_row'] = _table_row
        self.builtins['table_column'] = _table_column
        self.builtins['table_print'] = _table_print
        self.builtins['table_sort'] = _table_sort
        self.builtins['table_filter'] = _table_filter
        self.builtins['table_reverse'] = _table_reverse
        self.builtins['table_to_csv'] = _table_to_csv
        self.builtins['table_to_json'] = _table_to_json

    def _register_omap_builtins(self):
        """Register ordered map (sorted dictionary) builtins using bisect."""
        import bisect as _bisect

        class _SrvOMap:
            """Ordered map that keeps keys in sorted order."""
            __slots__ = ('_keys', '_vals')
            def __init__(self):
                self._keys = []
                self._vals = []
            def __repr__(self):
                pairs = ', '.join(f'{k}: {v}' for k, v in zip(self._keys, self._vals))
                return f"OMap({{{pairs}}})"

        def _check_omap(fn, m):
            if not isinstance(m, _SrvOMap):
                raise RuntimeError(f"{fn}: first argument must be an ordered map")

        def _omap_create(args):
            if len(args) > 1:
                raise RuntimeError("omap_create: expected 0-1 arguments ([map])")
            om = _SrvOMap()
            if len(args) == 1:
                if isinstance(args[0], dict):
                    for k in sorted(args[0].keys(), key=str):
                        om._keys.append(str(k))
                        om._vals.append(args[0][k])
                else:
                    raise RuntimeError("omap_create: argument must be a map")
            return om

        def _omap_set(args):
            if len(args) != 3:
                raise RuntimeError("omap_set: expected 3 arguments (omap, key, value)")
            _check_omap('omap_set', args[0])
            om, key, val = args[0], str(args[1]), args[2]
            idx = _bisect.bisect_left(om._keys, key)
            if idx < len(om._keys) and om._keys[idx] == key:
                om._vals[idx] = val
            else:
                om._keys.insert(idx, key)
                om._vals.insert(idx, val)
            return None

        def _omap_get(args):
            if len(args) < 2 or len(args) > 3:
                raise RuntimeError("omap_get: expected 2-3 arguments (omap, key, [default])")
            _check_omap('omap_get', args[0])
            om, key = args[0], str(args[1])
            idx = _bisect.bisect_left(om._keys, key)
            if idx < len(om._keys) and om._keys[idx] == key:
                return om._vals[idx]
            if len(args) == 3:
                return args[2]
            raise RuntimeError(f"omap_get: key '{key}' not found")

        def _omap_delete(args):
            if len(args) != 2:
                raise RuntimeError("omap_delete: expected 2 arguments (omap, key)")
            _check_omap('omap_delete', args[0])
            om, key = args[0], str(args[1])
            idx = _bisect.bisect_left(om._keys, key)
            if idx < len(om._keys) and om._keys[idx] == key:
                om._keys.pop(idx)
                return om._vals.pop(idx)
            raise RuntimeError(f"omap_delete: key '{key}' not found")

        def _omap_has(args):
            if len(args) != 2:
                raise RuntimeError("omap_has: expected 2 arguments (omap, key)")
            _check_omap('omap_has', args[0])
            om, key = args[0], str(args[1])
            idx = _bisect.bisect_left(om._keys, key)
            return idx < len(om._keys) and om._keys[idx] == key

        def _omap_size(args):
            if len(args) != 1:
                raise RuntimeError("omap_size: expected 1 argument (omap)")
            _check_omap('omap_size', args[0])
            return float(len(args[0]._keys))

        def _omap_keys(args):
            if len(args) != 1:
                raise RuntimeError("omap_keys: expected 1 argument (omap)")
            _check_omap('omap_keys', args[0])
            return list(args[0]._keys)

        def _omap_values(args):
            if len(args) != 1:
                raise RuntimeError("omap_values: expected 1 argument (omap)")
            _check_omap('omap_values', args[0])
            return list(args[0]._vals)

        def _omap_entries(args):
            if len(args) != 1:
                raise RuntimeError("omap_entries: expected 1 argument (omap)")
            _check_omap('omap_entries', args[0])
            return [[k, v] for k, v in zip(args[0]._keys, args[0]._vals)]

        def _omap_min(args):
            if len(args) != 1:
                raise RuntimeError("omap_min: expected 1 argument (omap)")
            _check_omap('omap_min', args[0])
            if not args[0]._keys:
                raise RuntimeError("omap_min: ordered map is empty")
            return [args[0]._keys[0], args[0]._vals[0]]

        def _omap_max(args):
            if len(args) != 1:
                raise RuntimeError("omap_max: expected 1 argument (omap)")
            _check_omap('omap_max', args[0])
            if not args[0]._keys:
                raise RuntimeError("omap_max: ordered map is empty")
            return [args[0]._keys[-1], args[0]._vals[-1]]

        def _omap_range(args):
            if len(args) != 3:
                raise RuntimeError("omap_range: expected 3 arguments (omap, low_key, high_key)")
            _check_omap('omap_range', args[0])
            om, lo, hi = args[0], str(args[1]), str(args[2])
            lo_idx = _bisect.bisect_left(om._keys, lo)
            hi_idx = _bisect.bisect_right(om._keys, hi)
            return [[om._keys[i], om._vals[i]] for i in range(lo_idx, hi_idx)]

        def _omap_floor(args):
            if len(args) != 2:
                raise RuntimeError("omap_floor: expected 2 arguments (omap, key)")
            _check_omap('omap_floor', args[0])
            om, key = args[0], str(args[1])
            idx = _bisect.bisect_right(om._keys, key) - 1
            if idx < 0:
                return None
            return [om._keys[idx], om._vals[idx]]

        def _omap_ceil(args):
            if len(args) != 2:
                raise RuntimeError("omap_ceil: expected 2 arguments (omap, key)")
            _check_omap('omap_ceil', args[0])
            om, key = args[0], str(args[1])
            idx = _bisect.bisect_left(om._keys, key)
            if idx >= len(om._keys):
                return None
            return [om._keys[idx], om._vals[idx]]

        def _omap_to_map(args):
            if len(args) != 1:
                raise RuntimeError("omap_to_map: expected 1 argument (omap)")
            _check_omap('omap_to_map', args[0])
            return dict(zip(args[0]._keys, args[0]._vals))

        def _omap_clear(args):
            if len(args) != 1:
                raise RuntimeError("omap_clear: expected 1 argument (omap)")
            _check_omap('omap_clear', args[0])
            args[0]._keys.clear()
            args[0]._vals.clear()
            return None

        self.builtins['omap_create'] = _omap_create
        self.builtins['omap_set'] = _omap_set
        self.builtins['omap_get'] = _omap_get
        self.builtins['omap_delete'] = _omap_delete
        self.builtins['omap_has'] = _omap_has
        self.builtins['omap_size'] = _omap_size
        self.builtins['omap_keys'] = _omap_keys
        self.builtins['omap_values'] = _omap_values
        self.builtins['omap_entries'] = _omap_entries
        self.builtins['omap_min'] = _omap_min
        self.builtins['omap_max'] = _omap_max
        self.builtins['omap_range'] = _omap_range
        self.builtins['omap_floor'] = _omap_floor
        self.builtins['omap_ceil'] = _omap_ceil
        self.builtins['omap_to_map'] = _omap_to_map
        self.builtins['omap_clear'] = _omap_clear

    def _register_fsm_builtins(self):
        """Register Finite State Machine builtins."""

        class _SrvFSM:
            """Finite State Machine for sauravcode."""
            __slots__ = ('_states', '_accepting', '_transitions', '_start', '_current')
            def __init__(self):
                self._states = set()
                self._accepting = set()
                self._transitions = {}  # {(state, symbol): next_state}
                self._start = None
                self._current = None
            def __repr__(self):
                cur = self._current if self._current else '(none)'
                return f"FSM(current={cur}, states={len(self._states)})"

        def _check_fsm(fn, obj):
            if not isinstance(obj, _SrvFSM):
                raise RuntimeError(f"{fn}: first argument must be an FSM")

        def _fsm_create(args):
            if len(args) != 0:
                raise RuntimeError("fsm_create: expected 0 arguments")
            return _SrvFSM()

        def _fsm_add_state(args):
            if len(args) < 2 or len(args) > 3:
                raise RuntimeError("fsm_add_state: expected 2-3 arguments (fsm, name, accepting?)")
            _check_fsm('fsm_add_state', args[0])
            name = args[1]
            if not isinstance(name, str):
                raise RuntimeError("fsm_add_state: state name must be a string")
            args[0]._states.add(name)
            if len(args) == 3 and args[2]:
                args[0]._accepting.add(name)
            return None

        def _fsm_add_transition(args):
            if len(args) != 4:
                raise RuntimeError("fsm_add_transition: expected 4 arguments (fsm, from_state, symbol, to_state)")
            _check_fsm('fsm_add_transition', args[0])
            from_s, symbol, to_s = args[1], args[2], args[3]
            for v in (from_s, symbol, to_s):
                if not isinstance(v, str):
                    raise RuntimeError("fsm_add_transition: from_state, symbol, and to_state must be strings")
            if from_s not in args[0]._states:
                raise RuntimeError(f"fsm_add_transition: state '{from_s}' not found")
            if to_s not in args[0]._states:
                raise RuntimeError(f"fsm_add_transition: state '{to_s}' not found")
            args[0]._transitions[(from_s, symbol)] = to_s
            return None

        def _fsm_set_start(args):
            if len(args) != 2:
                raise RuntimeError("fsm_set_start: expected 2 arguments (fsm, state)")
            _check_fsm('fsm_set_start', args[0])
            state = args[1]
            if not isinstance(state, str):
                raise RuntimeError("fsm_set_start: state must be a string")
            if state not in args[0]._states:
                raise RuntimeError(f"fsm_set_start: state '{state}' not found")
            args[0]._start = state
            args[0]._current = state
            return None

        def _fsm_transition(args):
            if len(args) != 2:
                raise RuntimeError("fsm_transition: expected 2 arguments (fsm, symbol)")
            _check_fsm('fsm_transition', args[0])
            fsm = args[0]
            symbol = args[1]
            if not isinstance(symbol, str):
                raise RuntimeError("fsm_transition: symbol must be a string")
            if fsm._current is None:
                raise RuntimeError("fsm_transition: no current state (set start state first)")
            key = (fsm._current, symbol)
            if key not in fsm._transitions:
                raise RuntimeError(f"fsm_transition: no transition from '{fsm._current}' on '{symbol}'")
            fsm._current = fsm._transitions[key]
            return fsm._current

        def _fsm_current(args):
            if len(args) != 1:
                raise RuntimeError("fsm_current: expected 1 argument (fsm)")
            _check_fsm('fsm_current', args[0])
            return args[0]._current if args[0]._current else ""

        def _fsm_is_accepting(args):
            if len(args) != 1:
                raise RuntimeError("fsm_is_accepting: expected 1 argument (fsm)")
            _check_fsm('fsm_is_accepting', args[0])
            return args[0]._current in args[0]._accepting if args[0]._current else False

        def _fsm_reset(args):
            if len(args) != 1:
                raise RuntimeError("fsm_reset: expected 1 argument (fsm)")
            _check_fsm('fsm_reset', args[0])
            args[0]._current = args[0]._start
            return None

        def _fsm_states(args):
            if len(args) != 1:
                raise RuntimeError("fsm_states: expected 1 argument (fsm)")
            _check_fsm('fsm_states', args[0])
            return sorted(list(args[0]._states))

        def _fsm_transitions(args):
            if len(args) != 1:
                raise RuntimeError("fsm_transitions: expected 1 argument (fsm)")
            _check_fsm('fsm_transitions', args[0])
            result = []
            for (from_s, symbol), to_s in sorted(args[0]._transitions.items()):
                result = result + [{"from": from_s, "symbol": symbol, "to": to_s}]
            return result

        def _fsm_run(args):
            if len(args) != 2:
                raise RuntimeError("fsm_run: expected 2 arguments (fsm, symbols_list)")
            _check_fsm('fsm_run', args[0])
            fsm = args[0]
            symbols = args[1]
            if not isinstance(symbols, list):
                raise RuntimeError("fsm_run: second argument must be a list of symbols")
            if fsm._start is None:
                raise RuntimeError("fsm_run: no start state set")
            fsm._current = fsm._start
            path = [fsm._current]
            for sym in symbols:
                if not isinstance(sym, str):
                    raise RuntimeError("fsm_run: each symbol must be a string")
                key = (fsm._current, sym)
                if key not in fsm._transitions:
                    return {"accepted": False, "path": path, "stuck_on": sym}
                fsm._current = fsm._transitions[key]
                path = path + [fsm._current]
            return {"accepted": fsm._current in fsm._accepting, "path": path, "final": fsm._current}

        def _fsm_accepts(args):
            if len(args) != 2:
                raise RuntimeError("fsm_accepts: expected 2 arguments (fsm, symbols_list)")
            result = _fsm_run(args)
            return result.get("accepted", False)

        self.builtins['fsm_create'] = _fsm_create
        self.builtins['fsm_add_state'] = _fsm_add_state
        self.builtins['fsm_add_transition'] = _fsm_add_transition
        self.builtins['fsm_set_start'] = _fsm_set_start
        self.builtins['fsm_transition'] = _fsm_transition
        self.builtins['fsm_current'] = _fsm_current
        self.builtins['fsm_is_accepting'] = _fsm_is_accepting
        self.builtins['fsm_reset'] = _fsm_reset
        self.builtins['fsm_states'] = _fsm_states
        self.builtins['fsm_transitions'] = _fsm_transitions
        self.builtins['fsm_run'] = _fsm_run
        self.builtins['fsm_accepts'] = _fsm_accepts

        # ── Ring Buffer builtins ──────────────────────────────────────
        class _SrvRingBuffer:
            """Fixed-size circular buffer for sauravcode."""
            __slots__ = ('_buf', '_capacity', '_head', '_count')
            def __init__(self, capacity):
                self._capacity = capacity
                self._buf = [None] * capacity
                self._head = 0   # index of oldest element
                self._count = 0
            def __repr__(self):
                return f"RingBuffer(size={self._count}, capacity={self._capacity})"

        def _check_ring(fn, obj):
            if not isinstance(obj, _SrvRingBuffer):
                raise RuntimeError(f"{fn}: first argument must be a RingBuffer")

        def _ring_create(args):
            if len(args) != 1:
                raise RuntimeError("ring_create: expected 1 argument (capacity)")
            cap = args[0]
            if not isinstance(cap, (int, float)) or int(cap) < 1:
                raise RuntimeError("ring_create: capacity must be a positive integer")
            return _SrvRingBuffer(int(cap))

        def _ring_push(args):
            if len(args) != 2:
                raise RuntimeError("ring_push: expected 2 arguments (ring, value)")
            _check_ring('ring_push', args[0])
            rb = args[0]
            idx = (rb._head + rb._count) % rb._capacity
            overwritten = None
            if rb._count == rb._capacity:
                overwritten = rb._buf[rb._head]
                rb._head = (rb._head + 1) % rb._capacity
            else:
                rb._count += 1
            rb._buf[idx] = args[1]
            return overwritten

        def _ring_peek(args):
            if len(args) != 1:
                raise RuntimeError("ring_peek: expected 1 argument (ring)")
            _check_ring('ring_peek', args[0])
            rb = args[0]
            if rb._count == 0:
                raise RuntimeError("ring_peek: buffer is empty")
            return rb._buf[rb._head]

        def _ring_pop(args):
            if len(args) != 1:
                raise RuntimeError("ring_pop: expected 1 argument (ring)")
            _check_ring('ring_pop', args[0])
            rb = args[0]
            if rb._count == 0:
                raise RuntimeError("ring_pop: buffer is empty")
            val = rb._buf[rb._head]
            rb._buf[rb._head] = None
            rb._head = (rb._head + 1) % rb._capacity
            rb._count -= 1
            return val

        def _ring_size(args):
            if len(args) != 1:
                raise RuntimeError("ring_size: expected 1 argument (ring)")
            _check_ring('ring_size', args[0])
            return float(args[0]._count)

        def _ring_capacity(args):
            if len(args) != 1:
                raise RuntimeError("ring_capacity: expected 1 argument (ring)")
            _check_ring('ring_capacity', args[0])
            return float(args[0]._capacity)

        def _ring_is_empty(args):
            if len(args) != 1:
                raise RuntimeError("ring_is_empty: expected 1 argument (ring)")
            _check_ring('ring_is_empty', args[0])
            return args[0]._count == 0

        def _ring_is_full(args):
            if len(args) != 1:
                raise RuntimeError("ring_is_full: expected 1 argument (ring)")
            _check_ring('ring_is_full', args[0])
            return args[0]._count == args[0]._capacity

        def _ring_to_list(args):
            if len(args) != 1:
                raise RuntimeError("ring_to_list: expected 1 argument (ring)")
            _check_ring('ring_to_list', args[0])
            rb = args[0]
            result = []
            for i in range(rb._count):
                result.append(rb._buf[(rb._head + i) % rb._capacity])
            return result

        def _ring_clear(args):
            if len(args) != 1:
                raise RuntimeError("ring_clear: expected 1 argument (ring)")
            _check_ring('ring_clear', args[0])
            rb = args[0]
            rb._buf = [None] * rb._capacity
            rb._head = 0
            rb._count = 0
            return None

        def _ring_get(args):
            if len(args) != 2:
                raise RuntimeError("ring_get: expected 2 arguments (ring, index)")
            _check_ring('ring_get', args[0])
            rb = args[0]
            idx = int(args[1])
            if idx < 0 or idx >= rb._count:
                raise RuntimeError(f"ring_get: index {idx} out of range (size={rb._count})")
            return rb._buf[(rb._head + idx) % rb._capacity]

        self.builtins['ring_create'] = _ring_create
        self.builtins['ring_push'] = _ring_push
        self.builtins['ring_peek'] = _ring_peek
        self.builtins['ring_pop'] = _ring_pop
        self.builtins['ring_size'] = _ring_size
        self.builtins['ring_capacity'] = _ring_capacity
        self.builtins['ring_is_empty'] = _ring_is_empty
        self.builtins['ring_is_full'] = _ring_is_full
        self.builtins['ring_to_list'] = _ring_to_list
        self.builtins['ring_clear'] = _ring_clear
        self.builtins['ring_get'] = _ring_get

    # ── Data-driven cipher builtins ──────────────────────

    def _register_cipher_builtins(self):
        """Register classical cipher builtins: Caesar, ROT13, Vigenère, XOR, Atbash, Morse."""

        def _require_str(fn, val):
            if not isinstance(val, str):
                raise RuntimeError(f"{fn}: expected string argument, got {type(val).__name__}")
            return val

        def _require_int_shift(fn, val):
            if isinstance(val, float) and val == int(val):
                return int(val)
            if isinstance(val, (int, float)):
                return int(val)
            raise RuntimeError(f"{fn}: shift must be an integer")

        # ── Caesar cipher ──
        def _caesar(text, shift):
            result = []
            for ch in text:
                if ch.isalpha():
                    base = ord('A') if ch.isupper() else ord('a')
                    result.append(chr((ord(ch) - base + shift) % 26 + base))
                else:
                    result.append(ch)
            return ''.join(result)

        def _caesar_encrypt(args):
            if len(args) != 2:
                raise RuntimeError("caesar_encrypt: expected 2 arguments (text, shift)")
            text = _require_str('caesar_encrypt', args[0])
            shift = _require_int_shift('caesar_encrypt', args[1])
            return _caesar(text, shift)

        def _caesar_decrypt(args):
            if len(args) != 2:
                raise RuntimeError("caesar_decrypt: expected 2 arguments (text, shift)")
            text = _require_str('caesar_decrypt', args[0])
            shift = _require_int_shift('caesar_decrypt', args[1])
            return _caesar(text, -shift)

        # ── ROT13 ──
        def _rot13(args):
            if len(args) != 1:
                raise RuntimeError("rot13: expected 1 argument (text)")
            text = _require_str('rot13', args[0])
            return _caesar(text, 13)

        # ── Vigenère cipher ──
        def _vigenere_encrypt(args):
            if len(args) != 2:
                raise RuntimeError("vigenere_encrypt: expected 2 arguments (text, key)")
            text = _require_str('vigenere_encrypt', args[0])
            key = _require_str('vigenere_encrypt', args[1])
            if len(key) == 0:
                raise RuntimeError("vigenere_encrypt: key must not be empty")
            key_upper = key.upper()
            result = []
            ki = 0
            for ch in text:
                if ch.isalpha():
                    base = ord('A') if ch.isupper() else ord('a')
                    shift = ord(key_upper[ki % len(key_upper)]) - ord('A')
                    result.append(chr((ord(ch) - base + shift) % 26 + base))
                    ki += 1
                else:
                    result.append(ch)
            return ''.join(result)

        def _vigenere_decrypt(args):
            if len(args) != 2:
                raise RuntimeError("vigenere_decrypt: expected 2 arguments (text, key)")
            text = _require_str('vigenere_decrypt', args[0])
            key = _require_str('vigenere_decrypt', args[1])
            if len(key) == 0:
                raise RuntimeError("vigenere_decrypt: key must not be empty")
            key_upper = key.upper()
            result = []
            ki = 0
            for ch in text:
                if ch.isalpha():
                    base = ord('A') if ch.isupper() else ord('a')
                    shift = ord(key_upper[ki % len(key_upper)]) - ord('A')
                    result.append(chr((ord(ch) - base - shift) % 26 + base))
                    ki += 1
                else:
                    result.append(ch)
            return ''.join(result)

        # ── XOR cipher ──
        def _xor_cipher(args):
            if len(args) != 2:
                raise RuntimeError("xor_cipher: expected 2 arguments (text, key)")
            text = _require_str('xor_cipher', args[0])
            key = _require_str('xor_cipher', args[1])
            if len(key) == 0:
                raise RuntimeError("xor_cipher: key must not be empty")
            result = []
            for i, ch in enumerate(text):
                result.append(chr(ord(ch) ^ ord(key[i % len(key)])))
            # Return hex-encoded to avoid non-printable chars
            return ''.join(result).encode('utf-8', errors='replace').hex()

        # ── Atbash cipher ──
        def _atbash(args):
            if len(args) != 1:
                raise RuntimeError("atbash: expected 1 argument (text)")
            text = _require_str('atbash', args[0])
            result = []
            for ch in text:
                if ch.isalpha():
                    if ch.isupper():
                        result.append(chr(ord('Z') - (ord(ch) - ord('A'))))
                    else:
                        result.append(chr(ord('z') - (ord(ch) - ord('a'))))
                else:
                    result.append(ch)
            return ''.join(result)

        # ── Morse code ──
        _MORSE = {
            'A': '.-', 'B': '-...', 'C': '-.-.', 'D': '-..', 'E': '.',
            'F': '..-.', 'G': '--.', 'H': '....', 'I': '..', 'J': '.---',
            'K': '-.-', 'L': '.-..', 'M': '--', 'N': '-.', 'O': '---',
            'P': '.--.', 'Q': '--.-', 'R': '.-.', 'S': '...', 'T': '-',
            'U': '..-', 'V': '...-', 'W': '.--', 'X': '-..-', 'Y': '-.--',
            'Z': '--..', '0': '-----', '1': '.----', '2': '..---',
            '3': '...--', '4': '....-', '5': '.....', '6': '-....',
            '7': '--...', '8': '---..', '9': '----.', ' ': '/',
            '.': '.-.-.-', ',': '--..--', '?': '..--..', '!': '-.-.--',
            "'": '.----.', '"': '.-..-.', '(': '-.--.', ')': '-.--.-',
            '&': '.-...', ':': '---...', ';': '-.-.-.', '/': '-..-.',
            '=': '-...-', '+': '.-.-.', '-': '-....-', '_': '..--.-',
            '@': '.--.-.', '$': '...-..-',
        }
        _MORSE_REV = {v: k for k, v in _MORSE.items()}

        def _morse_encode(args):
            if len(args) != 1:
                raise RuntimeError("morse_encode: expected 1 argument (text)")
            text = _require_str('morse_encode', args[0]).upper()
            result = []
            for ch in text:
                if ch in _MORSE:
                    result.append(_MORSE[ch])
                else:
                    result.append(ch)  # pass through unknown chars
            return ' '.join(result)

        def _morse_decode(args):
            if len(args) != 1:
                raise RuntimeError("morse_decode: expected 1 argument (morse_string)")
            text = _require_str('morse_decode', args[0])
            words = text.strip().split(' / ')
            decoded = []
            for word in words:
                chars = word.strip().split(' ')
                for c in chars:
                    c = c.strip()
                    if c in _MORSE_REV:
                        decoded.append(_MORSE_REV[c])
                    elif c == '':
                        pass
                    else:
                        decoded.append(c)  # pass through unknown
                decoded.append(' ')
            return ''.join(decoded).strip()

        self.builtins['caesar_encrypt'] = _caesar_encrypt
        self.builtins['caesar_decrypt'] = _caesar_decrypt
        self.builtins['rot13'] = _rot13
        self.builtins['vigenere_encrypt'] = _vigenere_encrypt
        self.builtins['vigenere_decrypt'] = _vigenere_decrypt
        self.builtins['xor_cipher'] = _xor_cipher
        self.builtins['atbash'] = _atbash
        self.builtins['morse_encode'] = _morse_encode
        self.builtins['morse_decode'] = _morse_decode

    # ── Data-driven hash/digest builtins ──────────────────

    def _register_hash_builtins(self):
        """Register hashing builtins: md5, sha1, sha256, sha512, crc32, hmac_sha256."""
        import hashlib as _hashlib
        import hmac as _hmac
        import binascii as _binascii

        def _require_str(fn, val):
            if not isinstance(val, str):
                raise RuntimeError(f"{fn}: expected string argument, got {type(val).__name__}")
            return val

        def _hash_fn(name, algo):
            def _impl(args):
                if len(args) != 1:
                    raise RuntimeError(f"{name}: expected 1 argument (text)")
                text = _require_str(name, args[0])
                h = _hashlib.new(algo)
                h.update(text.encode('utf-8'))
                return h.hexdigest()
            return _impl

        def _crc32(args):
            if len(args) != 1:
                raise RuntimeError("crc32: expected 1 argument (text)")
            text = _require_str('crc32', args[0])
            val = _binascii.crc32(text.encode('utf-8')) & 0xFFFFFFFF
            return format(val, '08x')

        def _hmac_sha256(args):
            if len(args) != 2:
                raise RuntimeError("hmac_sha256: expected 2 arguments (key, message)")
            key = _require_str('hmac_sha256', args[0])
            msg = _require_str('hmac_sha256', args[1])
            h = _hmac.new(key.encode('utf-8'), msg.encode('utf-8'), _hashlib.sha256)
            return h.hexdigest()

        self.builtins['md5'] = _hash_fn('md5', 'md5')
        self.builtins['sha1'] = _hash_fn('sha1', 'sha1')
        self.builtins['sha256'] = _hash_fn('sha256', 'sha256')
        self.builtins['sha512'] = _hash_fn('sha512', 'sha512')
        self.builtins['crc32'] = _crc32
        self.builtins['hmac_sha256'] = _hmac_sha256

    # ── Binary pack/unpack builtins ──────────────────────

    def _register_pack_builtins(self):
        """Register binary pack/unpack builtins (struct-like)."""
        import struct as _struct

        _FORMAT_MAP = {
            'byte': 'b', 'ubyte': 'B',
            'short': 'h', 'ushort': 'H',
            'int': 'i', 'uint': 'I',
            'long': 'q', 'ulong': 'Q',
            'float': 'f', 'double': 'd',
            'bool': '?', 'char': 'c',
        }

        _ENDIAN_MAP = {
            'little': '<', 'big': '>', 'native': '=', 'network': '!',
        }

        def _build_fmt(type_names, endian='little'):
            prefix = _ENDIAN_MAP.get(endian)
            if prefix is None:
                raise RuntimeError(f"pack: unknown endian '{endian}', use little/big/native/network")
            if isinstance(type_names, str):
                type_names = [type_names]
            if not isinstance(type_names, list):
                raise RuntimeError("pack: types must be a string or list of strings")
            codes = []
            for tn in type_names:
                if not isinstance(tn, str):
                    raise RuntimeError(f"pack: type name must be a string, got {type(tn).__name__}")
                code = _FORMAT_MAP.get(tn)
                if code is None:
                    raise RuntimeError(f"pack: unknown type '{tn}', use: {', '.join(sorted(_FORMAT_MAP))}")
                codes.append(code)
            return prefix + ''.join(codes)

        _INT_CODES = frozenset('bBhHiIqQ')

        def _coerce_values(type_names, values):
            """Coerce sauravcode values (floats) to proper Python types for struct."""
            if isinstance(type_names, str):
                type_names = [type_names]
            coerced = []
            for i, v in enumerate(values):
                tn = type_names[i] if i < len(type_names) else type_names[-1]
                code = _FORMAT_MAP.get(tn, '')
                if code in _INT_CODES and isinstance(v, float):
                    coerced.append(int(v))
                elif code == '?' and isinstance(v, (int, float)):
                    coerced.append(bool(v))
                elif code == 'c' and isinstance(v, str):
                    coerced.append(v.encode('utf-8')[0:1])
                else:
                    coerced.append(v)
            return coerced

        def _pack(args):
            if len(args) < 2 or len(args) > 3:
                raise RuntimeError("pack: expected 2-3 arguments (types, values [, endian])")
            type_names = args[0]
            values = args[1]
            endian = args[2] if len(args) == 3 else 'little'
            if not isinstance(values, list):
                values = [values]
            fmt = _build_fmt(type_names, endian)
            coerced = _coerce_values(type_names if isinstance(type_names, list) else [type_names], values)
            try:
                packed = _struct.pack(fmt, *coerced)
            except _struct.error as e:
                raise RuntimeError(f"pack: {e}")
            # Return as list of integers (bytes)
            return list(packed)

        def _unpack(args):
            if len(args) < 2 or len(args) > 3:
                raise RuntimeError("unpack: expected 2-3 arguments (types, bytes_list [, endian])")
            type_names = args[0]
            byte_list = args[1]
            endian = args[2] if len(args) == 3 else 'little'
            if not isinstance(byte_list, list):
                raise RuntimeError("unpack: second argument must be a list of byte values")
            fmt = _build_fmt(type_names, endian)
            raw = bytes(int(b) if isinstance(b, float) else b for b in byte_list)
            try:
                result = list(_struct.unpack(fmt, raw))
            except _struct.error as e:
                raise RuntimeError(f"unpack: {e}")
            # Convert to sauravcode types: ints->floats, bytes->strings
            return [v.decode('utf-8') if isinstance(v, bytes) else
                    float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
                    for v in result]

        def _pack_size(args):
            if len(args) < 1 or len(args) > 2:
                raise RuntimeError("pack_size: expected 1-2 arguments (types [, endian])")
            type_names = args[0]
            endian = args[1] if len(args) == 2 else 'little'
            fmt = _build_fmt(type_names, endian)
            return float(_struct.calcsize(fmt))

        def _pack_formats(args):
            if len(args) != 0:
                raise RuntimeError("pack_formats: expected 0 arguments")
            return sorted(_FORMAT_MAP.keys())

        self.builtins['pack'] = _pack
        self.builtins['unpack'] = _unpack
        self.builtins['pack_size'] = _pack_size
        self.builtins['pack_formats'] = _pack_formats

    def _register_emitter_builtins(self):
        """Event emitter (pub/sub) builtins for inter-component communication."""
        interpreter = self

        class EventEmitter:
            def __init__(self):
                self._listeners = {}   # event_name -> [(callback, once)]
            def on(self, event, callback, once=False):
                if event not in self._listeners:
                    self._listeners[event] = []
                self._listeners[event].append((callback, once))
            def off(self, event, callback=None):
                if event not in self._listeners:
                    return
                if callback is None:
                    del self._listeners[event]
                else:
                    self._listeners[event] = [
                        (cb, o) for cb, o in self._listeners[event] if cb != callback
                    ]
            def emit(self, event, args):
                if event not in self._listeners:
                    return 0.0
                to_remove = []
                count = 0
                for cb, once in self._listeners[event]:
                    kind, obj = interpreter._resolve_callable(cb)
                    interpreter._call_resolved(kind, obj, args)
                    count += 1
                    if once:
                        to_remove.append(cb)
                for cb in to_remove:
                    self._listeners[event] = [
                        (c, o) for c, o in self._listeners[event] if c is not cb
                    ]
                return float(count)
            def listeners(self, event=None):
                if event is not None:
                    return [cb for cb, _ in self._listeners.get(event, [])]
                return list(self._listeners.keys())
            def clear(self):
                self._listeners.clear()
            def count(self, event=None):
                if event is not None:
                    return float(len(self._listeners.get(event, [])))
                return float(sum(len(v) for v in self._listeners.values()))

        def _emitter_create(args):
            if len(args) != 0:
                raise RuntimeError("emitter_create: expected 0 arguments")
            return EventEmitter()

        def _emitter_on(args):
            if len(args) != 3:
                raise RuntimeError("emitter_on: expected 3 arguments (emitter, event, callback)")
            em, event, cb = args
            if not isinstance(em, EventEmitter):
                raise RuntimeError("emitter_on: first argument must be an emitter")
            if not isinstance(event, str):
                raise RuntimeError("emitter_on: event name must be a string")
            em.on(event, cb)
            return em

        def _emitter_once(args):
            if len(args) != 3:
                raise RuntimeError("emitter_once: expected 3 arguments (emitter, event, callback)")
            em, event, cb = args
            if not isinstance(em, EventEmitter):
                raise RuntimeError("emitter_once: first argument must be an emitter")
            if not isinstance(event, str):
                raise RuntimeError("emitter_once: event name must be a string")
            em.on(event, cb, once=True)
            return em

        def _emitter_emit(args):
            if len(args) < 2:
                raise RuntimeError("emitter_emit: expected at least 2 arguments (emitter, event, ...data)")
            em = args[0]
            event = args[1]
            data = args[2:]
            if not isinstance(em, EventEmitter):
                raise RuntimeError("emitter_emit: first argument must be an emitter")
            if not isinstance(event, str):
                raise RuntimeError("emitter_emit: event name must be a string")
            return em.emit(event, data)

        def _emitter_off(args):
            if len(args) < 2 or len(args) > 3:
                raise RuntimeError("emitter_off: expected 2-3 arguments (emitter, event [, callback])")
            em = args[0]
            event = args[1]
            cb = args[2] if len(args) == 3 else None
            if not isinstance(em, EventEmitter):
                raise RuntimeError("emitter_off: first argument must be an emitter")
            if not isinstance(event, str):
                raise RuntimeError("emitter_off: event name must be a string")
            em.off(event, cb)
            return em

        def _emitter_listeners(args):
            if len(args) < 1 or len(args) > 2:
                raise RuntimeError("emitter_listeners: expected 1-2 arguments (emitter [, event])")
            em = args[0]
            event = args[1] if len(args) == 2 else None
            if not isinstance(em, EventEmitter):
                raise RuntimeError("emitter_listeners: first argument must be an emitter")
            return em.listeners(event)

        def _emitter_clear(args):
            if len(args) != 1:
                raise RuntimeError("emitter_clear: expected 1 argument (emitter)")
            em = args[0]
            if not isinstance(em, EventEmitter):
                raise RuntimeError("emitter_clear: first argument must be an emitter")
            em.clear()
            return em

        def _emitter_count(args):
            if len(args) < 1 or len(args) > 2:
                raise RuntimeError("emitter_count: expected 1-2 arguments (emitter [, event])")
            em = args[0]
            event = args[1] if len(args) == 2 else None
            if not isinstance(em, EventEmitter):
                raise RuntimeError("emitter_count: first argument must be an emitter")
            return em.count(event)

        self.builtins['emitter_create'] = _emitter_create
        self.builtins['emitter_on'] = _emitter_on
        self.builtins['emitter_once'] = _emitter_once
        self.builtins['emitter_emit'] = _emitter_emit
        self.builtins['emitter_off'] = _emitter_off
        self.builtins['emitter_listeners'] = _emitter_listeners
        self.builtins['emitter_clear'] = _emitter_clear
        self.builtins['emitter_count'] = _emitter_count

    def _builtin_sort_by(self, args):
        """sort_by(func, list) - sort list by key function result"""
        self._expect_args('sort_by', args, 2)
        func, lst = args
        if not isinstance(func, (str, LambdaValue)):
            raise RuntimeError("sort_by: first argument must be a function or lambda")
        if not isinstance(lst, list):
            raise RuntimeError("sort_by: second argument must be a list")
        kind, obj = self._resolve_callable(func)
        call = self._call_resolved
        return sorted(lst, key=lambda x: call(kind, obj, [x]))

    def _builtin_min_by(self, args):
        """min_by(func, list) - element with minimum key function result"""
        self._expect_args('min_by', args, 2)
        func, lst = args
        if not isinstance(func, (str, LambdaValue)):
            raise RuntimeError("min_by: first argument must be a function or lambda")
        if not isinstance(lst, list):
            raise RuntimeError("min_by: second argument must be a list")
        if len(lst) == 0:
            raise RuntimeError("min_by: empty list")
        kind, obj = self._resolve_callable(func)
        call = self._call_resolved
        return min(lst, key=lambda x: call(kind, obj, [x]))

    def _builtin_max_by(self, args):
        """max_by(func, list) - element with maximum key function result"""
        self._expect_args('max_by', args, 2)
        func, lst = args
        if not isinstance(func, (str, LambdaValue)):
            raise RuntimeError("max_by: first argument must be a function or lambda")
        if not isinstance(lst, list):
            raise RuntimeError("max_by: second argument must be a list")
        if len(lst) == 0:
            raise RuntimeError("max_by: empty list")
        kind, obj = self._resolve_callable(func)
        call = self._call_resolved
        return max(lst, key=lambda x: call(kind, obj, [x]))

    def _builtin_partition(self, args):
        """partition(func, list) - split list into [truthy, falsy] by predicate"""
        self._expect_args('partition', args, 2)
        func, lst = args
        if not isinstance(func, (str, LambdaValue)):
            raise RuntimeError("partition: first argument must be a function or lambda")
        if not isinstance(lst, list):
            raise RuntimeError("partition: second argument must be a list")
        kind, obj = self._resolve_callable(func)
        call = self._call_resolved
        truthy, falsy = [], []
        for item in lst:
            if call(kind, obj, [item]):
                truthy.append(item)
            else:
                falsy.append(item)
        return [truthy, falsy]

    def _builtin_rotate(self, args):
        """rotate(list, n) - rotate list by n positions (positive = left)"""
        self._expect_args('rotate', args, 2)
        lst, n = args
        if not isinstance(lst, list):
            raise RuntimeError("rotate: first argument must be a list")
        if not isinstance(n, (int, float)):
            raise RuntimeError("rotate: second argument must be a number")
        n = int(n)
        if len(lst) == 0:
            return []
        n = n % len(lst)
        return lst[n:] + lst[:n]

    def _builtin_interleave(self, args):
        """interleave(list1, list2) - interleave two lists element by element"""
        self._expect_args('interleave', args, 2)
        a, b = args
        if not isinstance(a, list) or not isinstance(b, list):
            raise RuntimeError("interleave: both arguments must be lists")
        result = []
        for i in range(max(len(a), len(b))):
            if i < len(a):
                result.append(a[i])
            if i < len(b):
                result.append(b[i])
        return result

    def _builtin_frequencies(self, args):
        """frequencies(list) - count occurrences of each element, returns dict"""
        self._expect_args('frequencies', args, 1)
        lst = args[0]
        if not isinstance(lst, list):
            raise RuntimeError("frequencies: argument must be a list")
        freq = {}
        for item in lst:
            key = str(item) if isinstance(item, list) else item
            if isinstance(key, float) and key == int(key):
                key = int(key)
            k = str(key)
            freq[k] = freq.get(k, 0) + 1
        return freq

    def _builtin_combinations(self, args):
        """combinations(list, k) - all k-element combinations"""
        self._expect_args('combinations', args, 2)
        from itertools import combinations as _combinations
        lst, k = args
        if not isinstance(lst, list):
            raise RuntimeError("combinations: first argument must be a list")
        if not isinstance(k, (int, float)):
            raise RuntimeError("combinations: second argument must be a number")
        k = int(k)
        if k < 0 or k > len(lst):
            raise RuntimeError(f"combinations: k={k} out of range for list of length {len(lst)}")
        return [list(c) for c in _combinations(lst, k)]

    def _builtin_permutations(self, args):
        """permutations(list, k?) - all k-element permutations (default k=len)"""
        if len(args) < 1 or len(args) > 2:
            raise RuntimeError("permutations expects 1-2 arguments")
        from itertools import permutations as _permutations
        lst = args[0]
        if not isinstance(lst, list):
            raise RuntimeError("permutations: first argument must be a list")
        k = int(args[1]) if len(args) == 2 else len(lst)
        if k < 0 or k > len(lst):
            raise RuntimeError(f"permutations: k={k} out of range for list of length {len(lst)}")
        return [list(p) for p in _permutations(lst, k)]

    # ── Shared statistics validation ──────────────────

    def _validate_number_list(self, name, args):
        """Validate and return a non-empty list of numbers.

        Shared by mean, median, stdev, variance, mode, and percentile
        to eliminate duplicated validation code.
        """
        self._expect_args(name, args, 1)
        lst = args[0]
        if not isinstance(lst, list):
            raise RuntimeError(f"{name} expects a list argument")
        if len(lst) == 0:
            raise RuntimeError(f"{name}: empty list")
        for v in lst:
            if not isinstance(v, (int, float)):
                raise RuntimeError(f"{name}: all elements must be numbers")
        return lst

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
        if isinstance(val, _SrvLinkedList):
            return "linkedlist"
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

    def _invoke_func_node(self, func_node, evaluated_args):
        """Invoke a FunctionNode with recursion depth tracking and scoped environment.
        
        Handles closure scope restoration, parameter binding, body interpretation,
        and ReturnSignal handling — the common logic for all FunctionNode invocations.
        """
        self._call_depth += 1
        if self._call_depth > MAX_RECURSION_DEPTH:
            self._call_depth -= 1
            raise RuntimeError(
                f"Maximum recursion depth ({MAX_RECURSION_DEPTH}) exceeded "
                f"in function '{func_node.name}'"
            )
        result = None
        with self._scoped_env():
            # Inject closure scope via ChainMap splicing — O(1) instead
            # of iterating all closure variables.  Matches the approach
            # used by _invoke_function(); previously this path did an
            # O(k) loop per call which was a bottleneck for map/filter/
            # reduce over large lists with closures.
            if hasattr(func_node, 'closure_scope') and func_node.closure_scope:
                cs = func_node.closure_scope
                closure_maps = cs.maps if isinstance(cs, ChainMap) else [cs] if isinstance(cs, dict) else []
                if closure_maps:
                    local = self.variables.maps[0]
                    self.variables = ChainMap(local, *closure_maps, *self.variables.maps[1:])
            for param, val in zip(func_node.params, evaluated_args):
                self.variables[param] = val
            try:
                for stmt in func_node.body:
                    self.interpret(stmt)
            except ReturnSignal as ret:
                result = ret.value
            finally:
                self._call_depth -= 1
        return result

    def _resolve_callable(self, func_ref):
        """Resolve a callable reference to a direct (kind, obj) pair.

        Returns a tuple ``(kind, obj)`` where *kind* is one of
        ``'lambda'``, ``'func'``, or ``'builtin'``, and *obj* is the
        resolved callable (``LambdaValue``, ``FunctionNode``, or the
        built-in function itself).

        This allows higher-order functions (map, filter, reduce, each)
        to resolve the callable *once* outside the hot loop, then use
        the appropriate fast path on every iteration — eliminating N
        repeated ``isinstance`` checks and dict lookups for an
        N-element list.
        """
        if isinstance(func_ref, LambdaValue):
            return ('lambda', func_ref)
        if isinstance(func_ref, FunctionNode):
            return ('func', func_ref)
        # String name — resolve to concrete callable
        func_name = func_ref
        func = self.functions.get(func_name)
        if func:
            return ('func', func)
        if func_name in self.builtins:
            return ('builtin', self.builtins[func_name])
        if func_name in self.variables:
            var_val = self.variables[func_name]
            if isinstance(var_val, FunctionNode):
                return ('func', var_val)
            elif isinstance(var_val, LambdaValue):
                return ('lambda', var_val)
        raise RuntimeError(f"Function '{func_name}' is not defined.")

    def _call_resolved(self, kind, obj, evaluated_args):
        """Invoke a pre-resolved callable. See ``_resolve_callable``."""
        if kind == 'lambda':
            return self._call_lambda(obj, evaluated_args)
        if kind == 'func':
            return self._invoke_func_node(obj, evaluated_args)
        # builtin
        return obj(evaluated_args)

    def _call_function_with_args(self, func_ref, evaluated_args):
        """Call a user-defined function, built-in, or lambda with pre-evaluated args.
        
        Used by higher-order functions (map, filter, reduce) to invoke
        callbacks with already-evaluated Python values.
        
        func_ref can be:
        - A string (function name to look up)
        - A LambdaValue (anonymous function)
        - A FunctionNode (closure / first-class function value)
        """
        kind, obj = self._resolve_callable(func_ref)
        return self._call_resolved(kind, obj, evaluated_args)

    def _builtin_map(self, args):
        """map func list → apply function to each element, return new list.
        
        func can be a function name (string) or a lambda expression.
        Example: map double [1, 2, 3] → [2, 4, 6]
        Example: map (lambda x -> x * 2) [1, 2, 3] → [2, 4, 6]
        """
        self._expect_args('map', args, 2)
        func_ref, lst = args
        if not isinstance(func_ref, (str, LambdaValue, FunctionNode)):
            raise RuntimeError("map expects a function name or lambda as first argument")
        if not isinstance(lst, list):
            raise RuntimeError("map expects a list as second argument")
        # Fast path: lambda callbacks get a reusable scope to avoid
        # per-element ChainMap + dict allocation overhead.
        kind, obj = self._resolve_callable(func_ref)
        if kind == 'lambda':
            call = self._make_lambda_caller(obj)
            return [call([item]) for item in lst]
        call = self._call_resolved
        return [call(kind, obj, [item]) for item in lst]

    def _builtin_filter(self, args):
        """filter func list → keep elements where function returns truthy.
        
        func can be a function name (string) or a lambda expression.
        Example: filter is_positive [3, -1, 4, -5, 2] → [3, 4, 2]
        Example: filter (lambda x -> x > 0) [3, -1, 4] → [3, 4]
        """
        self._expect_args('filter', args, 2)
        func_ref, lst = args
        if not isinstance(func_ref, (str, LambdaValue, FunctionNode)):
            raise RuntimeError("filter expects a function name or lambda as first argument")
        if not isinstance(lst, list):
            raise RuntimeError("filter expects a list as second argument")
        kind, obj = self._resolve_callable(func_ref)
        truthy = self._is_truthy
        if kind == 'lambda':
            call = self._make_lambda_caller(obj)
            return [item for item in lst if truthy(call([item]))]
        call = self._call_resolved
        return [item for item in lst
                if truthy(call(kind, obj, [item]))]

    def _builtin_reduce(self, args):
        """reduce func list initial → fold list with binary function.
        
        func can be a function name (string) or a lambda expression.
        Example: reduce add [1, 2, 3, 4] 0 → 10
        Example: reduce (lambda acc x -> acc + x) [1, 2, 3] 0 → 6
        """
        self._expect_args('reduce', args, 3)
        func_ref, lst, init = args
        if not isinstance(func_ref, (str, LambdaValue, FunctionNode)):
            raise RuntimeError("reduce expects a function name or lambda as first argument")
        if not isinstance(lst, list):
            raise RuntimeError("reduce expects a list as second argument")
        kind, obj = self._resolve_callable(func_ref)
        if kind == 'lambda':
            call = self._make_lambda_caller(obj)
            acc = init
            for item in lst:
                acc = call([acc, item])
            return acc
        call = self._call_resolved
        acc = init
        for item in lst:
            acc = call(kind, obj, [acc, item])
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
        if not isinstance(func_ref, (str, LambdaValue, FunctionNode)):
            raise RuntimeError("each expects a function name or lambda as first argument")
        if not isinstance(lst, list):
            raise RuntimeError("each expects a list as second argument")
        kind, obj = self._resolve_callable(func_ref)
        if kind == 'lambda':
            call = self._make_lambda_caller(obj)
            for item in lst:
                call([item])
            return lst
        call = self._call_resolved
        for item in lst:
            call(kind, obj, [item])
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

    def _validate_file_path(self, func_name, path):
        """Validate a file path against the interpreter's sandbox root.

        When the interpreter has a _source_dir (i.e. running from a file),
        file I/O is restricted to the source directory tree — consistent
        with the import path traversal guard. This prevents sauravcode
        programs from reading/writing arbitrary files outside their project.

        When _source_dir is None (REPL/interactive), no restriction is
        applied — the user is directly controlling the interpreter.

        Null bytes are always blocked regardless of mode.
        """
        # Block null bytes (path injection)
        if '\x00' in path:
            raise RuntimeError(f"{func_name}: null bytes are not allowed in file paths")

        # Block empty paths
        if not path.strip():
            raise RuntimeError(f"{func_name}: empty file path")

        # When running from a file, enforce path traversal protection
        if self._source_dir is not None:
            # Use realpath to resolve symlinks — abspath alone can be
            # bypassed via symlink chains that point outside the sandbox.
            allowed_root = os.path.realpath(self._source_dir)

            if os.path.isabs(path):
                full_path = os.path.realpath(path)
            else:
                full_path = os.path.realpath(os.path.join(allowed_root, path))

            # Path traversal check — must resolve within allowed root.
            # Use os.path.normcase for case-insensitive comparison on Windows.
            norm_root = os.path.normcase(allowed_root)
            norm_full = os.path.normcase(full_path)
            if not norm_full.startswith(norm_root + os.sep) and norm_full != norm_root:
                raise RuntimeError(
                    f"{func_name}: path traversal outside project directory "
                    f"is not allowed ('{path}' resolves outside '{allowed_root}')"
                )
            return full_path

        # Interactive/REPL mode: resolve but don't restrict
        return os.path.abspath(path)

    def _builtin_read_file(self, args):
        """read_file path → return file contents as a string."""
        self._expect_args('read_file', args, 1)
        path = args[0]
        if not isinstance(path, str):
            raise RuntimeError("read_file expects a string path")
        full_path = self._validate_file_path('read_file', path)
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            raise RuntimeError(f"read_file: file not found: {path}")
        except PermissionError:
            raise RuntimeError(f"read_file: permission denied: {path}")
        except OSError as e:
            raise RuntimeError(f"read_file: error reading file: {e}")

    def _write_file_impl(self, func_name, args, mode):
        """Shared implementation for write_file and append_file.

        Validates arguments, coerces content to string, resolves the path
        through the sandbox validator, and writes with the given mode.
        """
        self._expect_args(func_name, args, 2)
        path = args[0]
        content = args[1]
        if not isinstance(path, str):
            raise RuntimeError(f"{func_name} expects a string path as first argument")
        if not isinstance(content, str):
            content = str(content)
        full_path = self._validate_file_path(func_name, path)
        action = "writing" if mode == "w" else "appending to"
        try:
            with open(full_path, mode, encoding='utf-8') as f:
                f.write(content)
            return True
        except PermissionError:
            raise RuntimeError(f"{func_name}: permission denied: {path}")
        except OSError as e:
            raise RuntimeError(f"{func_name}: error {action} file: {e}")

    def _builtin_write_file(self, args):
        """write_file path content → write content to file (creates or overwrites)."""
        return self._write_file_impl('write_file', args, 'w')

    def _builtin_append_file(self, args):
        """append_file path content → append content to file (creates if missing)."""
        return self._write_file_impl('append_file', args, 'a')

    def _builtin_file_exists(self, args):
        """file_exists path → return true if file exists, false otherwise."""
        self._expect_args('file_exists', args, 1)
        path = args[0]
        if not isinstance(path, str):
            raise RuntimeError("file_exists expects a string path")
        full_path = self._validate_file_path('file_exists', path)
        return os.path.isfile(full_path)

    def _builtin_read_lines(self, args):
        """read_lines path → return file contents as a list of lines."""
        self._expect_args('read_lines', args, 1)
        path = args[0]
        if not isinstance(path, str):
            raise RuntimeError("read_lines expects a string path")
        full_path = self._validate_file_path('read_lines', path)
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                return [line.rstrip('\n').rstrip('\r') for line in f.readlines()]
        except FileNotFoundError:
            raise RuntimeError(f"read_lines: file not found: {path}")
        except PermissionError:
            raise RuntimeError(f"read_lines: permission denied: {path}")
        except OSError as e:
            raise RuntimeError(f"read_lines: error reading file: {e}")

    # --- HTTP built-ins ---

    @staticmethod
    def _is_private_address(ip_str):
        """Check if an IP address string is private/reserved."""
        import ipaddress
        try:
            ip = ipaddress.ip_address(ip_str)
            return ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local
        except ValueError:
            return True  # unparseable → block

    @staticmethod
    def _is_private_ip(hostname):
        """Check if a hostname resolves to a private/reserved IP (SSRF protection)."""
        import ipaddress
        import socket
        try:
            # Resolve hostname to IP(s) — check ALL resolved addresses
            for info in socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM):
                addr = info[4][0]
                ip = ipaddress.ip_address(addr)
                if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
                    return True
        except (socket.gaierror, ValueError):
            # Can't resolve → block by default (could be a crafted hostname)
            return True
        return False

    @staticmethod
    def _make_ssrf_safe_opener():
        """Create a urllib opener that validates resolved IPs at connection time.

        This prevents DNS rebinding attacks where a hostname resolves to a
        public IP during the initial check but a private IP when the actual
        connection is made.  The custom handler intercepts the socket connect
        call and rejects private/reserved IPs.
        """
        import urllib.request
        import http.client
        import socket
        import ipaddress

        class _SSRFGuardMixin:
            """Mixin that validates resolved IPs to block SSRF via DNS rebinding."""
            def connect(self):
                for info in socket.getaddrinfo(self.host, self.port, socket.AF_UNSPEC, socket.SOCK_STREAM):
                    af, socktype, proto, canonname, sa = info
                    addr = sa[0]
                    ip = ipaddress.ip_address(addr)
                    if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
                        raise RuntimeError(
                            f"SSRF protection: connection blocked — "
                            f"'{self.host}' resolved to private IP {addr} at connect time "
                            f"(possible DNS rebinding attack)."
                        )
                super().connect()

        class SSRFSafeHTTPConnection(_SSRFGuardMixin, http.client.HTTPConnection):
            pass

        class SSRFSafeHTTPSConnection(_SSRFGuardMixin, http.client.HTTPSConnection):
            pass

        class SSRFSafeHTTPHandler(urllib.request.HTTPHandler):
            def http_open(self, req):
                return self.do_open(SSRFSafeHTTPConnection, req)

        class SSRFSafeHTTPSHandler(urllib.request.HTTPSHandler):
            def https_open(self, req):
                return self.do_open(SSRFSafeHTTPSConnection, req)

        return urllib.request.build_opener(SSRFSafeHTTPHandler, SSRFSafeHTTPSHandler)

    def _http_request(self, method, url, body=None, headers=None):
        """Perform an HTTP request and return a map with status, body, and headers."""
        import urllib.request
        import urllib.error
        from urllib.parse import urlparse

        if not isinstance(url, str):
            raise RuntimeError(f"http_{method.lower()} expects a string URL")
        if not url.startswith(('http://', 'https://')):
            raise RuntimeError(f"http_{method.lower()}: URL must start with http:// or https://")

        # Pre-flight SSRF check (fast-fail for obviously private hosts)
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            raise RuntimeError(f"http_{method.lower()}: could not parse hostname from URL")
        if self._is_private_ip(hostname):
            raise RuntimeError(
                f"http_{method.lower()}: requests to private/internal networks are blocked "
                f"(SSRF protection). Host '{hostname}' resolves to a private IP."
            )

        req_headers = {'User-Agent': 'sauravcode/1.0'}
        if headers and isinstance(headers, dict):
            for k, v in headers.items():
                req_headers[str(k)] = str(v)

        data = None
        if body is not None:
            if isinstance(body, str):
                data = body.encode('utf-8')
            elif isinstance(body, dict) or isinstance(body, list):
                import json as _json
                data = _json.dumps(body).encode('utf-8')
                if 'Content-Type' not in req_headers:
                    req_headers['Content-Type'] = 'application/json'
            else:
                data = str(body).encode('utf-8')

        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)

        # Use SSRF-safe opener that validates IPs at connect time,
        # preventing DNS rebinding attacks (TOCTOU between resolve and connect)
        opener = self._make_ssrf_safe_opener()

        try:
            with opener.open(req, timeout=30) as resp:
                resp_body = resp.read().decode('utf-8', errors='replace')
                resp_headers = {k: v for k, v in resp.getheaders()}
                # Try to auto-parse JSON responses
                content_type = resp.getheader('Content-Type', '')
                if 'application/json' in content_type:
                    try:
                        import json as _json
                        resp_body = _json.loads(resp_body)
                    except Exception:
                        pass
                return {
                    'status': float(resp.status),
                    'body': resp_body,
                    'headers': resp_headers,
                }
        except urllib.error.HTTPError as e:
            resp_body = e.read().decode('utf-8', errors='replace') if e.fp else ''
            return {
                'status': float(e.code),
                'body': resp_body,
                'headers': {k: v for k, v in e.headers.items()} if e.headers else {},
            }
        except urllib.error.URLError as e:
            raise RuntimeError(f"http_{method.lower()}: connection error: {e.reason}")
        except Exception as e:
            raise RuntimeError(f"http_{method.lower()}: request failed: {e}")

    def _builtin_http_get(self, args):
        """http_get url [headers_map] — perform an HTTP GET request."""
        if len(args) < 1 or len(args) > 2:
            raise RuntimeError("http_get expects 1-2 arguments: url [headers]")
        url = args[0]
        headers = args[1] if len(args) > 1 else None
        return self._http_request('GET', url, headers=headers)

    def _builtin_http_post(self, args):
        """http_post url body [headers_map] — perform an HTTP POST request."""
        if len(args) < 2 or len(args) > 3:
            raise RuntimeError("http_post expects 2-3 arguments: url body [headers]")
        url, body = args[0], args[1]
        headers = args[2] if len(args) > 2 else None
        return self._http_request('POST', url, body, headers)

    def _builtin_http_put(self, args):
        """http_put url body [headers_map] — perform an HTTP PUT request."""
        if len(args) < 2 or len(args) > 3:
            raise RuntimeError("http_put expects 2-3 arguments: url body [headers]")
        url, body = args[0], args[1]
        headers = args[2] if len(args) > 2 else None
        return self._http_request('PUT', url, body, headers)

    def _builtin_http_delete(self, args):
        """http_delete url [headers_map] — perform an HTTP DELETE request."""
        if len(args) < 1 or len(args) > 2:
            raise RuntimeError("http_delete expects 1-2 arguments: url [headers]")
        url = args[0]
        headers = args[1] if len(args) > 1 else None
        return self._http_request('DELETE', url, headers=headers)

    # --- Date/Time built-ins ---
    # now() and timestamp() are registered via _register_zero_arg_builtins()

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
    # pi() and euler() are registered via _register_zero_arg_builtins()
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

    # — Functional collection builtins ————————————————

    def _builtin_group_by(self, args):
        """group_by(fn, list) -> map of key -> [elements] grouped by fn result."""
        self._expect_args('group_by', args, 2)
        fn, lst = args[0], args[1]
        if not isinstance(fn, (str, LambdaValue)):
            raise RuntimeError("group_by expects a function name or lambda as first argument")
        if not isinstance(lst, list):
            raise RuntimeError("group_by expects a list as second argument")
        result = {}
        for item in lst:
            key = self._call_function_with_args(fn, [item])
            str_key = str(key) if not isinstance(key, str) else key
            if str_key not in result:
                result[str_key] = []
            result[str_key].append(item)
        return result

    def _builtin_take_while(self, args):
        """take_while(fn, list) -> elements from start while fn returns true."""
        self._expect_args('take_while', args, 2)
        fn, lst = args[0], args[1]
        if not isinstance(fn, (str, LambdaValue)):
            raise RuntimeError("take_while expects a function name or lambda as first argument")
        if not isinstance(lst, list):
            raise RuntimeError("take_while expects a list as second argument")
        result = []
        for item in lst:
            if self._call_function_with_args(fn, [item]):
                result.append(item)
            else:
                break
        return result

    def _builtin_drop_while(self, args):
        """drop_while(fn, list) -> elements after first element where fn returns false."""
        self._expect_args('drop_while', args, 2)
        fn, lst = args[0], args[1]
        if not isinstance(fn, (str, LambdaValue)):
            raise RuntimeError("drop_while expects a function name or lambda as first argument")
        if not isinstance(lst, list):
            raise RuntimeError("drop_while expects a list as second argument")
        dropping = True
        result = []
        for item in lst:
            if dropping and self._call_function_with_args(fn, [item]):
                continue
            dropping = False
            result.append(item)
        return result

    def _builtin_scan(self, args):
        """scan(fn, initial, list) -> list of intermediate reduce results."""
        self._expect_args('scan', args, 3)
        fn, init, lst = args[0], args[1], args[2]
        if not isinstance(fn, (str, LambdaValue)):
            raise RuntimeError("scan expects a function name or lambda as first argument")
        if not isinstance(lst, list):
            raise RuntimeError("scan expects a list as third argument")
        acc = init
        result = [acc]
        for item in lst:
            acc = self._call_function_with_args(fn, [acc, item])
            result.append(acc)
        return result

    def _builtin_zip_with(self, args):
        """zip_with(fn, list1, list2) -> list of fn(a, b) for each pair."""
        self._expect_args('zip_with', args, 3)
        fn, lst1, lst2 = args[0], args[1], args[2]
        if not isinstance(fn, (str, LambdaValue)):
            raise RuntimeError("zip_with expects a function name or lambda as first argument")
        if not isinstance(lst1, list) or not isinstance(lst2, list):
            raise RuntimeError("zip_with expects lists as second and third arguments")
        return [self._call_function_with_args(fn, [a, b])
                for a, b in zip(lst1, lst2)]

    # — Statistics builtins ————————————————————————

    def _builtin_mean(self, args):
        lst = self._validate_number_list('mean', args)
        return sum(lst) / len(lst)

    def _builtin_median(self, args):
        lst = self._validate_number_list('median', args)
        s = sorted(lst)
        n = len(s)
        mid = n // 2
        if n % 2 == 1:
            return float(s[mid])
        return (s[mid - 1] + s[mid]) / 2.0

    def _builtin_stdev(self, args):
        lst = self._validate_number_list('stdev', args)
        m = sum(lst) / len(lst)
        variance = sum((v - m) ** 2 for v in lst) / len(lst)
        return math.sqrt(variance)

    def _builtin_variance(self, args):
        lst = self._validate_number_list('variance', args)
        m = sum(lst) / len(lst)
        return sum((v - m) ** 2 for v in lst) / len(lst)

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

    # --- Number theory built-ins ---

    def _builtin_factorial(self, args):
        """factorial(n) -> n! for non-negative integer n."""
        self._expect_args('factorial', args, 1)
        n = args[0]
        if not isinstance(n, (int, float)) or n != int(n) or n < 0:
            raise RuntimeError("factorial: argument must be a non-negative integer")
        n = int(n)
        if n > 170:
            raise RuntimeError("factorial: argument too large (max 170)")
        result = 1
        for i in range(2, n + 1):
            result *= i
        return float(result)

    def _builtin_gcd(self, args):
        """gcd(a, b) -> greatest common divisor."""
        self._expect_args('gcd', args, 2)
        import math as _math
        a, b = int(args[0]), int(args[1])
        return float(_math.gcd(a, b))

    def _builtin_lcm(self, args):
        """lcm(a, b) -> least common multiple."""
        self._expect_args('lcm', args, 2)
        import math as _math
        a, b = int(args[0]), int(args[1])
        g = _math.gcd(a, b)
        return float(abs(a * b) // g) if g else 0.0

    def _builtin_is_prime(self, args):
        """is_prime(n) -> true if n is a prime number."""
        self._expect_args('is_prime', args, 1)
        n = int(args[0])
        if n < 2:
            return False
        if n < 4:
            return True
        if n % 2 == 0 or n % 3 == 0:
            return False
        i = 5
        while i * i <= n:
            if n % i == 0 or n % (i + 2) == 0:
                return False
            i += 6
        return True

    def _builtin_prime_factors(self, args):
        """prime_factors(n) -> list of prime factors."""
        self._expect_args('prime_factors', args, 1)
        n = int(args[0])
        if n < 2:
            return []
        factors = []
        d = 2
        while d * d <= n:
            while n % d == 0:
                factors.append(float(d))
                n //= d
            d += 1
        if n > 1:
            factors.append(float(n))
        return factors

    def _builtin_fibonacci(self, args):
        """fibonacci(n) -> nth Fibonacci number (0-indexed)."""
        self._expect_args('fibonacci', args, 1)
        n = int(args[0])
        if n < 0:
            raise RuntimeError("fibonacci: argument must be non-negative")
        if n > 1000:
            raise RuntimeError("fibonacci: argument too large (max 1000)")
        if n <= 1:
            return float(n)
        a, b = 0, 1
        for _ in range(2, n + 1):
            a, b = b, a + b
        return float(b)

    def _builtin_modpow(self, args):
        """modpow(base, exp, mod) -> (base^exp) % mod."""
        self._expect_args('modpow', args, 3)
        base, exp, mod = int(args[0]), int(args[1]), int(args[2])
        if mod == 0:
            raise RuntimeError("modpow: modulus must not be zero")
        return float(pow(base, exp, mod))

    def _builtin_divisors(self, args):
        """divisors(n) -> sorted list of all positive divisors of n."""
        self._expect_args('divisors', args, 1)
        n = int(args[0])
        if n <= 0:
            raise RuntimeError("divisors: argument must be a positive integer")
        divs = []
        i = 1
        while i * i <= n:
            if n % i == 0:
                divs.append(float(i))
                if i != n // i:
                    divs.append(float(n // i))
            i += 1
        divs.sort()
        return divs

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

    # --- Regex built-ins (with ReDoS protection) ---

    # Maximum allowed regex pattern length.  Excessively long patterns
    # can be used to craft exponential-backtracking attacks even before
    # the match is attempted.
    _REGEX_MAX_PATTERN_LEN = 1000

    # Patterns that indicate potential ReDoS (nested quantifiers).
    # These catch constructs like (a+)+, (a*)+, (a+)*, (a?){N}, etc.
    _REGEX_DANGEROUS_PATTERNS = re.compile(
        r'(\([^)]*[+*][^)]*\))[+*]'   # (X+)+ or (X*)+ or (X+)* etc.
        r'|(\([^)]*[+*?][^)]*\))\{'    # (X+){N} or (X?){N}
        r'|(\([^)]*\{[^)]*\))[+*]'    # (X{N})+ etc.
    )

    def _regex_validate(self, func_name, pattern):
        """Validate a regex pattern for length and dangerous constructs.

        Checks:
        1. Pattern length <= _REGEX_MAX_PATTERN_LEN
        2. Pattern compiles (valid syntax)
        3. No nested quantifiers that cause exponential backtracking

        Args:
            func_name: Name of the calling builtin (for error messages).
            pattern:   The regex pattern string.

        Raises:
            RuntimeError: On invalid, oversized, or dangerous pattern.
        """
        if len(pattern) > self._REGEX_MAX_PATTERN_LEN:
            raise RuntimeError(
                f"{func_name}: regex pattern too long "
                f"({len(pattern)} chars, max {self._REGEX_MAX_PATTERN_LEN})"
            )

        try:
            re.compile(pattern)
        except re.error as e:
            raise RuntimeError(f"{func_name}: invalid regex pattern: {e}")

        if self._REGEX_DANGEROUS_PATTERNS.search(pattern):
            raise RuntimeError(
                f"{func_name}: regex pattern rejected — nested quantifiers "
                f"detected (potential ReDoS). Simplify the pattern to avoid "
                f"exponential backtracking."
            )

    def _builtin_regex_match(self, args):
        """regex_match(pattern, string) -> true if the entire string matches the pattern."""
        self._expect_args('regex_match', args, 2)
        pattern, string = args[0], args[1]
        if not isinstance(pattern, str):
            raise RuntimeError("regex_match expects a string pattern as first argument")
        if not isinstance(string, str):
            raise RuntimeError("regex_match expects a string as second argument")
        self._regex_validate('regex_match', pattern)
        return re.fullmatch(pattern, string) is not None

    def _builtin_regex_find(self, args):
        """regex_find(pattern, string) -> map with 'match', 'start', 'end', 'groups' or null."""
        self._expect_args('regex_find', args, 2)
        pattern, string = args[0], args[1]
        if not isinstance(pattern, str):
            raise RuntimeError("regex_find expects a string pattern as first argument")
        if not isinstance(string, str):
            raise RuntimeError("regex_find expects a string as second argument")
        self._regex_validate('regex_find', pattern)
        m = re.search(pattern, string)
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
        self._regex_validate('regex_find_all', pattern)
        results = re.findall(pattern, string)
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
        self._regex_validate('regex_replace', pattern)
        return re.sub(pattern, replacement, string)

    def _builtin_regex_split(self, args):
        """regex_split(pattern, string) -> list of substrings split by pattern matches."""
        self._expect_args('regex_split', args, 2)
        pattern, string = args[0], args[1]
        if not isinstance(pattern, str):
            raise RuntimeError("regex_split expects a string pattern as first argument")
        if not isinstance(string, str):
            raise RuntimeError("regex_split expects a string as second argument")
        self._regex_validate('regex_split', pattern)
        return re.split(pattern, string)

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

    # md5, sha256, sha1, crc32, url_encode, hex_encode, url_decode
    # are registered via _register_hash_builtins()

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

    # hex_encode, crc32, url_encode, url_decode are registered via
    # _register_hash_builtins()

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

    @contextlib.contextmanager
    def _scoped_env(self):
        """Context manager: pushes a new scope on entry, pops on exit.

        Uses ``collections.ChainMap`` for O(1) scope push/pop instead of
        copying the entire variable dict on every function call.  Reads
        fall through to the parent scope, writes stay local — identical
        semantics to the old ``dict.copy()`` / restore pattern, but
        much faster for programs with deep recursion or many calls.
        """
        parent = self.variables
        self.variables = ChainMap({}, parent)
        try:
            yield
        finally:
            self.variables = parent

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
                for elif_cond, elif_body in stmt.elif_chains:
                    if self._has_yield(elif_body):
                        return True
                if stmt.else_body and self._has_yield(stmt.else_body):
                    return True
            elif isinstance(stmt, (WhileNode, ForNode, ForEachNode)):
                if self._has_yield(stmt.body):
                    return True
            elif isinstance(stmt, TryCatchNode):
                if self._has_yield(stmt.body) or self._has_yield(stmt.handler):
                    return True
        return False

    def interpret(self, ast):
        if DEBUG:
            debug("Interpreting AST...")
        handler = self._interpret_dispatch.get(type(ast))
        if handler is not None:
            try:
                return handler(ast)
            except SauravRuntimeError:
                raise  # already enriched
            except (ReturnSignal, ThrowSignal, BreakSignal, ContinueSignal, YieldSignal):
                raise  # control flow signals, not errors
            except RuntimeError as e:
                line = getattr(ast, 'line_num', None)
                raise SauravRuntimeError(str(e), line=line) from None
        else:
            raise ValueError(f'Unknown AST node type: {type(ast).__name__}')

    # ── interpret dispatch handlers ──────────────────────────

    def _interp_function(self, ast):
        if DEBUG:
            debug(f"Storing function: {ast.name}\n")
        # Cache generator status on the FunctionNode to avoid O(n)
        # AST walk on every call (was a major bottleneck for recursion).
        if not hasattr(ast, '_is_generator'):
            ast._is_generator = self._has_yield(ast.body)
        self.functions[ast.name] = ast

    def _interp_return(self, ast):
        result = self.evaluate(ast.expression)
        if DEBUG:
            debug(f"ReturnNode evaluated with result: {result}\n")
        raise ReturnSignal(result)

    def _interp_yield(self, ast):
        result = self.evaluate(ast.expression)
        debug(f"YieldNode evaluated with result: {result}\n")
        raise YieldSignal(result)

    # ── Value → string formatting dispatch (shared by print + f-strings) ──
    # O(1) type-based lookup; avoids isinstance chains on the hot path.
    _PRINT_FORMATTERS = {
        bool:  lambda v: "true" if v else "false",
        list:  lambda v: _format_list(v),
        dict:  lambda v: _format_map(v),
        set:   lambda v: _format_set(v),
    }

    # String-coercion dispatch used by f-strings and any future
    # value-to-string conversion.  Separated from _PRINT_FORMATTERS
    # because print has special cases (Stack, Queue, Generator) that
    # f-strings handle via the generic str() fallback.
    _STR_FORMATTERS = {
        bool:  lambda v: "true" if v else "false",
        list:  lambda v: _format_list(v),
        dict:  lambda v: _format_map(v),
        set:   lambda v: _format_set(v),
        int:   str,
        str:   lambda v: v,      # identity — skip str() call overhead
    }

    @staticmethod
    def _value_to_str(val):
        """Convert a sauravcode value to its string representation.

        Uses O(1) type dispatch for common types (bool, list, dict, set,
        int, str).  Falls back to the float-integer check and generic
        str() for uncommon types.  This is the single source of truth
        for value → string formatting, used by both f-string evaluation
        and print statements.
        """
        formatter = Interpreter._STR_FORMATTERS.get(type(val))
        if formatter is not None:
            return formatter(val)
        if isinstance(val, float):
            return str(int(val)) if val == int(val) else str(val)
        return str(val)

    def _interp_print(self, ast):
        value = self.evaluate(ast.expression)
        # O(1) type dispatch for the common collection/bool types
        formatter = self._PRINT_FORMATTERS.get(type(value))
        if formatter is not None:
            print(formatter(value))
        elif isinstance(value, float) and value == int(value):
            print(int(value))
        elif isinstance(value, _SrvStack):
            print(f"Stack({_format_list(value.to_list())})")
        elif isinstance(value, _SrvQueue):
            print(f"Queue({_format_list(value.to_list())})")
        elif isinstance(value, GeneratorValue):
            print(repr(value))
        else:
            print(value)
        if DEBUG:
            debug(f"Printed: {value}\n")

    def _interp_function_call(self, ast):
        if DEBUG:
            debug(f"Interpreting function call: {ast.name}")
        return self.execute_function(ast)

    def _interp_assignment(self, ast):
        value = self.evaluate(ast.expression)
        self.variables[ast.name] = value
        if DEBUG:
            debug(f"Assigned {value} to {ast.name}\n")

    def _interp_indexed_assignment(self, ast):
        collection = self.variables.get(ast.name)
        idx_or_key = self.evaluate(ast.index)
        value = self.evaluate(ast.value)
        if isinstance(collection, list):
            idx = int(idx_or_key)
            if idx < 0:
                idx += len(collection)
            if idx < 0 or idx >= len(collection):
                raise RuntimeError(f"Index {int(idx_or_key)} out of bounds (size {len(collection)})")
            collection[idx] = value
        elif isinstance(collection, dict):
            collection[idx_or_key] = value
        else:
            raise RuntimeError(f"'{ast.name}' is not a list or map")
        if DEBUG:
            debug(f"Indexed assignment: {ast.name}[{idx_or_key}] = {value}\n")

    def _interp_append(self, ast):
        lst = self.variables.get(ast.list_name)
        if not isinstance(lst, list):
            raise RuntimeError(f"'{ast.list_name}' is not a list")
        value = self.evaluate(ast.value)
        lst.append(value)

    def _interp_pop(self, ast):
        lst = self.variables.get(ast.list_name)
        if not isinstance(lst, list):
            raise RuntimeError(f"'{ast.list_name}' is not a list")
        if len(lst) == 0:
            raise RuntimeError(f"Pop from empty list '{ast.list_name}'")
        lst.pop()

    def _interp_enum(self, ast):
        """Register an enum type with auto-incrementing integer values."""
        enum_map = {}
        for i, variant in enumerate(ast.variants):
            enum_map[variant] = float(i)
        self.enums[ast.name] = enum_map
        if DEBUG:
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
        """Execute while loop with iteration limit for DoS protection.

        Hoists method references (evaluate, _is_truthy, execute_body) to
        locals so the per-iteration attribute lookups go through LOAD_FAST
        instead of LOAD_ATTR.  On CPython this saves ~30-50 ns per
        iteration — meaningful for tight loops with millions of cycles.
        """
        iterations = 0
        _evaluate = self.evaluate
        _is_truthy = self._is_truthy
        _execute_body = self.execute_body
        _condition = node.condition
        _body = node.body
        _max = MAX_LOOP_ITERATIONS
        while _is_truthy(_evaluate(_condition)):
            iterations += 1
            if iterations > _max:
                raise RuntimeError(
                    f"Maximum loop iterations ({_max:,}) exceeded "
                    f"in while loop"
                )
            try:
                _execute_body(_body)
            except BreakSignal:
                break
            except ContinueSignal:
                continue

    def execute_for(self, node):
        """Execute for loop (range-based) with iteration limit for DoS protection.

        Hoists ``self.variables`` dict and ``node.var`` to locals so the
        loop variable assignment uses LOAD_FAST + STORE_SUBSCR instead of
        LOAD_ATTR + LOAD_ATTR + STORE_SUBSCR on each iteration.
        """
        start = int(self.evaluate(node.start))
        end = int(self.evaluate(node.end))
        if abs(end - start) > MAX_LOOP_ITERATIONS:
            raise RuntimeError(
                f"For loop range ({abs(end - start):,}) exceeds maximum "
                f"iterations ({MAX_LOOP_ITERATIONS:,})"
            )
        _variables = self.variables
        _var = node.var
        _execute_body = self.execute_body
        _body = node.body
        for i in range(start, end):
            _variables[_var] = i
            try:
                _execute_body(_body)
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

        Avoids materializing intermediate lists for strings, dicts, and
        sets by checking ``len()`` directly and iterating in-place.
        For a 10k-character string this saves ~80 KB of allocation and
        the O(n) copy cost.
        """
        collection = self.evaluate(node.iterable)
        if isinstance(collection, GeneratorValue):
            items = collection.to_list()
            size = len(items)
        elif isinstance(collection, (list, str, dict, set)):
            items = collection  # iterate directly — no copy needed
            size = len(collection)
        else:
            raise RuntimeError(
                f"Cannot iterate over {type(collection).__name__}. "
                f"for-each requires a list, string, map, or generator."
            )
        if size > MAX_LOOP_ITERATIONS:
            raise RuntimeError(
                f"For-each collection size ({size:,}) exceeds maximum "
                f"iterations ({MAX_LOOP_ITERATIONS:,})"
            )
        _variables = self.variables
        _var = node.var
        _execute_body = self.execute_body
        _body = node.body
        for item in items:
            _variables[_var] = item
            try:
                _execute_body(_body)
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
                            # Save previous value so we can restore it if guard fails
                            _had_prev = case.binding_name in self.variables
                            _prev_val = self.variables.get(case.binding_name)
                            self.variables[case.binding_name] = value
                        if self._is_truthy(self.evaluate(case.guard)):
                            self.execute_body(case.body)
                            return
                        if case.binding_name:
                            # Guard failed — restore previous variable state
                            if _had_prev:
                                self.variables[case.binding_name] = _prev_val
                            elif case.binding_name in self.variables:
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
        
        # Normalize for circular import detection — use realpath to
        # resolve symlinks (abspath alone can be bypassed via symlink
        # chains that point outside the sandbox).
        full_path = os.path.realpath(full_path)
        
        # Prevent path traversal — imports must resolve within the source
        # directory or current working directory (fixes issue #24).
        # Use realpath + normcase for parity with _validate_file_path
        # (symlink-safe and case-insensitive on Windows).
        allowed_root = os.path.realpath(self._source_dir or os.getcwd())
        norm_root = os.path.normcase(allowed_root)
        norm_full = os.path.normcase(full_path)
        if not norm_full.startswith(norm_root + os.sep) and norm_full != norm_root:
            raise RuntimeError(
                f"Cannot import '{node.module_path}': "
                f"path traversal outside project directory is not allowed"
            )
        
        # Circular import guard
        if full_path in self._imported_modules:
            if DEBUG:
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
        
        if DEBUG:
            debug(f"Imported module: {node.module_path}")

    def execute_body(self, body):
        """Execute a list of statements. Propagates ReturnSignal.

        Fast-paths single-statement bodies (common for simple loops and
        if-branches) to skip the for-loop iteration overhead.
        """
        if len(body) == 1:
            self.interpret(body[0])
            return
        _interpret = self.interpret
        for stmt in body:
            _interpret(stmt)

    def _is_truthy(self, value):
        """Determine truthiness of a value.

        Falsy values: ``false``, ``0``, ``""``, ``[]``, ``{}``, ``None``.
        Everything else (non-zero numbers, non-empty strings/lists/maps,
        generators, etc.) is truthy.

        Uses Python's native ``bool()`` for the common types (bool, int,
        float, str, list, dict, None) which is implemented in C and
        avoids the overhead of multiple isinstance checks on every call.
        This is a hot-path function — called on every while-loop
        iteration and every if/elif condition evaluation.
        """
        # Python's bool() matches sauravcode truthiness for all built-in
        # types: bool, int, float, str, list, dict, None.  Only custom
        # objects (GeneratorValue, _SrvStack, _SrvQueue, class instances)
        # need special handling — and they're always truthy.
        try:
            return bool(value)
        except (TypeError, ValueError):
            return True

    def _invoke_function(self, func_node, evaluated_args, name='<anonymous>'):
        """Invoke a FunctionNode with pre-evaluated arguments.

        Centralises the recursion guard, scope management, closure injection,
        parameter binding, body execution, and ReturnSignal handling that was
        previously duplicated between the named-function and variable-callable
        code paths in execute_function().

        Inlines the scope push/pop rather than using ``_scoped_env()`` to
        avoid the ``@contextlib.contextmanager`` generator protocol overhead
        (~500 ns/call on CPython). Since function invocation is the hottest
        path after evaluate(), this matters for recursive and loop-heavy
        programs.
        """
        self._call_depth += 1
        if self._call_depth > MAX_RECURSION_DEPTH:
            self._call_depth -= 1
            raise RuntimeError(
                f"Maximum recursion depth ({MAX_RECURSION_DEPTH}) exceeded "
                f"in function '{name}'"
            )

        result = None
        # Inline scope push (replaces ``with self._scoped_env():``)
        parent_vars = self.variables
        self.variables = ChainMap({}, parent_vars)
        try:
            # Inject closure scope by splicing its maps into the ChainMap
            # chain — O(1) instead of iterating all closure variables.
            # The local scope (maps[0]) stays on top so params and local
            # writes shadow closure variables correctly.
            cs = getattr(func_node, 'closure_scope', None)
            if cs:
                # Extract the underlying maps from the closure ChainMap and
                # insert them between the local scope and the parent scope.
                # Using getattr+None avoids the hasattr double-lookup, and
                # pre-building the maps list avoids repeated tuple unpacking.
                if isinstance(cs, ChainMap):
                    closure_maps = cs.maps
                elif isinstance(cs, dict):
                    closure_maps = [cs]
                else:
                    closure_maps = []
                if closure_maps:
                    maps = self.variables.maps
                    self.variables = ChainMap(maps[0], *closure_maps, *maps[1:])

            for param, arg_val in zip(func_node.params, evaluated_args):
                self.variables[param] = arg_val
                if DEBUG:
                    debug(f"Set parameter '{param}' to {arg_val}")
            try:
                for stmt in func_node.body:
                    self.interpret(stmt)
            except ReturnSignal as ret:
                result = ret.value
            finally:
                self._call_depth -= 1
        finally:
            # Inline scope pop (replaces _scoped_env finally block)
            self.variables = parent_vars
        if DEBUG:
            debug(f"Function {name} returned {result}\n")
        return result

    def execute_function(self, call_node):
        name = call_node.name

        # Evaluate arguments once — all code paths need the same values
        # and sauravcode has no lazy-evaluation semantics.
        evaluated_args = [self.evaluate(arg) for arg in call_node.arguments]

        # Check user-defined functions first (allows overriding builtins)
        func = self.functions.get(name)
        if func:
            if DEBUG:
                debug(f"Executing function: {name} with arguments {call_node.arguments}")

            # Check if this is a generator function.
            # Use getattr with default to avoid the slower hasattr
            # double-lookup (hasattr calls getattr internally then
            # catches AttributeError).
            is_gen = getattr(func, '_is_generator', None)
            if is_gen is None:
                is_gen = self._has_yield(func.body)
                func._is_generator = is_gen
            if is_gen:
                debug(f"Function {name} is a generator — returning GeneratorValue")
                return GeneratorValue(self, func, evaluated_args)

            return self._invoke_function(func, evaluated_args, name)

        # Check built-in functions — single dict lookup instead of
        # ``name in self.builtins`` followed by ``self.builtins[name]``.
        builtin_fn = self.builtins.get(name)
        if builtin_fn is not None:
            # Zero-arg builtin call: if a user variable shadows it, return the variable
            if len(evaluated_args) == 0 and name in self.variables:
                return self.variables[name]
            return builtin_fn(evaluated_args)

        # Check if the name refers to a variable holding a callable value
        # (e.g. a closure returned from a higher-order function)
        var_val = self.variables.get(name, self._SENTINEL)
        if var_val is not self._SENTINEL:
            if isinstance(var_val, FunctionNode):
                return self._invoke_function(var_val, evaluated_args, name)
            elif isinstance(var_val, LambdaValue):
                return self._call_lambda(var_val, evaluated_args)

        raise SauravRuntimeError(
            f"Function {name} is not defined.",
            line=getattr(call_node, 'line_num', None)
        )

    # ── Leaf-node types that return a value directly (no recursion possible).
    # Evaluating these via the full evaluate() path wastes ~200ns per call
    # on depth tracking, try/finally, and dispatch overhead.  By checking
    # the type *before* touching _eval_depth we skip all of that for the
    # most common nodes in any program (literals and identifiers).
    _LEAF_TYPES = (NumberNode, StringNode, BoolNode)

    def evaluate(self, node):
        # Fast path for leaf nodes — no depth tracking needed since they
        # cannot recurse.  NumberNode/StringNode/BoolNode just return a
        # stored value; IdentifierNode does a single dict lookup.
        # This is the single highest-frequency code path in the interpreter.
        node_type = type(node)
        if node_type is NumberNode:
            return node.value
        if node_type is StringNode:
            return node.value
        if node_type is BoolNode:
            return node.value
        if node_type is IdentifierNode:
            value = self.variables.get(node.name, self._SENTINEL)
            if value is not self._SENTINEL:
                return value
            # Fall through to full path for function/builtin lookups
            return self._eval_identifier(node)

        self._eval_depth += 1
        if self._eval_depth > MAX_EVAL_DEPTH:
            self._eval_depth -= 1
            line = getattr(node, 'line_num', None)
            raise SauravRuntimeError(
                f"Maximum expression nesting depth ({MAX_EVAL_DEPTH}) exceeded",
                line=line
            )
        try:
            if DEBUG:
                debug(f"Evaluating node: {node}")
            handler = self._evaluate_dispatch.get(node_type)
            if handler is not None:
                try:
                    return handler(node)
                except SauravRuntimeError:
                    raise  # already enriched
                except (ReturnSignal, ThrowSignal, BreakSignal, ContinueSignal, YieldSignal):
                    raise  # control flow signals, not errors
                except RuntimeError as e:
                    line = getattr(node, 'line_num', None)
                    raise SauravRuntimeError(str(e), line=line) from None
            else:
                raise ValueError(f'Unknown node type: {node}')
        finally:
            self._eval_depth -= 1

    # ── evaluate dispatch handlers ───────────────────────────

    def _eval_number(self, node):
        return node.value

    def _eval_string(self, node):
        return node.value

    def _eval_bool(self, node):
        return node.value

    _SENTINEL = object()  # unique sentinel for single-lookup variable access

    def _eval_identifier(self, node):
        # Single lookup via sentinel avoids the double ChainMap traversal
        # of ``name in self.variables`` followed by ``self.variables[name]``.
        # For programs with deeply nested scopes this cuts identifier
        # resolution cost roughly in half on the hot path.
        value = self.variables.get(node.name, self._SENTINEL)
        if value is not self._SENTINEL:
            if DEBUG:
                debug(f"Identifier '{node.name}' is a variable with value {value}")
            return value
        elif node.name in self.functions:
            if DEBUG:
                debug(f"Identifier '{node.name}' is a function name")
            # Return a lightweight _BoundFunction wrapping the original
            # FunctionNode with a lazy ChainMap scope snapshot.  This
            # avoids the cost of copy.copy() on every function-as-value
            # reference — significant in programs that pass functions to
            # map/filter/reduce in tight loops.
            return _BoundFunction(
                self.functions[node.name], ChainMap({}, self.variables)
            )
        elif node.name in self.builtins:
            if DEBUG:
                debug(f"Identifier '{node.name}' is a built-in function")
            return node.name
        else:
            raise RuntimeError(f"Name '{node.name}' is not defined.")

    def _eval_binary_op(self, node):
        left = self.evaluate(node.left)
        right = self.evaluate(node.right)
        if DEBUG:
            debug(f"Performing operation: {left} {node.operator} {right}")
        op = node.operator
        try:
            # Fast path: both operands are numbers — pure dispatch, no guards needed.
            # This avoids isinstance checks on the hot path for arithmetic-heavy code.
            # Division/modulo zero-checks are embedded in the dispatch lambdas
            # (_NUMERIC_OP_DISPATCH) so +, -, * avoid the branch entirely.
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                return self._NUMERIC_OP_DISPATCH[op](left, right)

            # Repetition guard for string/list * int
            if op == '*':
                if isinstance(left, (str, list)) and isinstance(right, (int, float)):
                    return self._guarded_repeat(left, int(right))
                elif isinstance(right, (str, list)) and isinstance(left, (int, float)):
                    return self._guarded_repeat(right, int(left))
                return left * right

            # Division / modulo zero-checks for non-numeric types that support them
            if op == '/':
                if right == 0:
                    raise RuntimeError("Division by zero")
                return left / right
            if op == '%':
                if right == 0:
                    raise RuntimeError("Modulo by zero")
                return left % right

            # O(1) dispatch for +, - (handles string concat, list concat, etc.)
            op_fn = self._BINARY_OP_DISPATCH.get(op)
            if op_fn is not None:
                return op_fn(left, right)
            raise ValueError(f'Unknown operator: {op}')
        except TypeError:
            raise RuntimeError(
                f"Cannot use '{op}' on "
                f"{self._type_name(left)} and {self._type_name(right)}"
            )

    def _eval_compare(self, node):
        left = self.evaluate(node.left)
        right = self.evaluate(node.right)
        if DEBUG:
            debug(f"Comparing: {left} {node.operator} {right}")
        try:
            cmp_fn = self._COMPARE_OP_DISPATCH.get(node.operator)
            if cmp_fn is not None:
                return cmp_fn(left, right)
            raise ValueError(f'Unknown comparison operator: {node.operator}')
        except TypeError:
            raise RuntimeError(
                f"Cannot compare {self._type_name(left)} and "
                f"{self._type_name(right)} with '{node.operator}'"
            )

    def _eval_logical(self, node):
        """Evaluate logical and/or with short-circuit semantics.

        Hoists _is_truthy to a local to avoid repeated LOAD_ATTR on the
        hot path.  For deeply nested boolean expressions this saves one
        attribute lookup per node.
        """
        _truthy = self._is_truthy
        left = self.evaluate(node.left)
        op = node.operator
        if op == 'and':
            return _truthy(left) and _truthy(self.evaluate(node.right))
        elif op == 'or':
            return _truthy(left) or _truthy(self.evaluate(node.right))
        else:
            raise ValueError(f'Unknown logical operator: {op}')

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
        """Evaluate list comprehension: [expr for var in iterable if cond]

        Iterates strings, dicts, and sets in-place without materializing
        an intermediate list.  For a 10k-character string this saves the
        O(n) ``list()`` copy and ~80 KB of allocation.
        """
        collection = self.evaluate(node.iterable)
        if isinstance(collection, (list, str)):
            items = collection          # iterate directly — no copy
        elif isinstance(collection, dict):
            items = collection           # iterating a dict yields its keys
        elif isinstance(collection, set):
            items = collection           # iterate directly
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
        _variables = self.variables
        _var = node.var
        _evaluate = self.evaluate
        try:
            # Split into two loops to avoid checking node.condition on
            # every iteration when there is no filter.  For unfiltered
            # comprehensions over large collections this eliminates one
            # branch + attribute load per element.
            if node.condition is not None:
                _is_truthy = self._is_truthy
                _cond = node.condition
                result = []
                for item in items:
                    _variables[_var] = item
                    if not _is_truthy(_evaluate(_cond)):
                        continue
                    result.append(_evaluate(node.expr))
            else:
                _expr = node.expr
                result = []
                for item in items:
                    _variables[_var] = item
                    result.append(_evaluate(_expr))
        finally:
            # Restore variable scope (in finally to be exception-safe)
            if had_var:
                _variables[_var] = old_val
            else:
                _variables.pop(_var, None)
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
        if isinstance(obj, (list, str, dict)):
            return float(len(obj))
        if isinstance(obj, GeneratorValue):
            return float(len(obj.to_list()))
        raise RuntimeError(f"Cannot get length of {type(obj).__name__}")

    def _eval_pop(self, node):
        lst = self.variables.get(node.list_name)
        if not isinstance(lst, list):
            raise RuntimeError(f"'{node.list_name}' is not a list")
        if len(lst) == 0:
            raise RuntimeError(f"Pop from empty list '{node.list_name}'")
        return lst.pop()

    def _eval_map(self, node):
        result = {}
        for key_expr, val_expr in node.pairs:
            key = self.evaluate(key_expr)
            val = self.evaluate(val_expr)
            result[key] = val
        return result

    def _eval_fstring(self, node):
        parts = []
        _to_str = self._value_to_str  # local ref avoids repeated attr lookup
        for part in node.parts:
            parts.append(_to_str(self.evaluate(part)))
        return ''.join(parts)

    def _eval_lambda(self, node):
        """Evaluate a lambda expression — captures current scope snapshot.

        Lambdas must capture a *snapshot* of the enclosing scope at
        definition time (not a live reference), so that later mutations
        to the outer scope don't affect the lambda's closed-over values.

        Uses ``dict(self.variables)`` instead of ``self.variables.copy()``
        because when ``self.variables`` is a ``ChainMap`` (common during
        nested function calls), ``dict()`` flattens it in one C-level
        pass while ``.copy()`` returns another ``ChainMap`` whose
        ``__iter__`` must walk the full chain.  For a 3-deep ChainMap
        with ~50 variables, ``dict()`` is ~2x faster.
        """
        return LambdaValue(node.params, node.body_expr, dict(self.variables))

    def _call_lambda(self, lam, args):
        """Call a LambdaValue with the given arguments.

        Uses ``ChainMap`` over the captured closure instead of copying
        the closure dict.  This avoids an O(n) ``dict.copy()`` on every
        lambda invocation — a significant win when higher-order
        functions (map, filter, reduce, each) invoke a lambda once per
        element.  Parameters are written into the child map so they
        shadow any same-named closure variables without mutating the
        original closure.
        """
        if len(args) != len(lam.params):
            raise RuntimeError(
                f"Lambda expects {len(lam.params)} argument(s), "
                f"got {len(args)}"
            )
        # Save and restore variables manually (skip _scoped_env which
        # would create an unused intermediate ChainMap).
        saved = self.variables
        self.variables = ChainMap({}, lam.closure)
        for param, val in zip(lam.params, args):
            self.variables[param] = val
        try:
            return self.evaluate(lam.body_expr)
        finally:
            self.variables = saved

    def _make_lambda_caller(self, lam):
        """Create a reusable fast-path caller for a lambda in HOF loops.

        Returns a function ``call(args) -> result`` that reuses a single
        pre-allocated locals dict and ChainMap across all invocations.
        This eliminates per-call ``ChainMap({}, closure)`` construction
        and ``zip(params, args)`` overhead — significant when map/filter/
        reduce/each invoke the same lambda thousands of times.

        The caller is **not** reentrant: it must only be used in a
        single-threaded, non-recursive HOF loop (which is the case for
        all sauravcode HOFs).
        """
        params = lam.params
        body_expr = lam.body_expr
        nparams = len(params)
        # Pre-allocate the locals dict and ChainMap once.
        local = {}
        scope = ChainMap(local, lam.closure)
        _evaluate = self.evaluate

        def call(args):
            if len(args) != nparams:
                raise RuntimeError(
                    f"Lambda expects {nparams} argument(s), "
                    f"got {len(args)}"
                )
            saved = self.variables
            # Reuse the pre-allocated local dict: clear and refill.
            # For 1-2 params (the common case), direct assignment is
            # faster than local.clear() + zip().
            if nparams == 1:
                local.clear()
                local[params[0]] = args[0]
            elif nparams == 2:
                local.clear()
                local[params[0]] = args[0]
                local[params[1]] = args[1]
            else:
                local.clear()
                for p, v in zip(params, args):
                    local[p] = v
            self.variables = scope
            try:
                return _evaluate(body_expr)
            finally:
                self.variables = saved

        return call

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
            return self._call_function_with_args(func_node.name, evaluated_args)
        
        # Case 2: Right side is an identifier (function name, no extra args)
        # e.g., "hello" |> upper → upper("hello")
        if isinstance(func_node, IdentifierNode):
            func_name = func_node.name
            # Check if it's a variable holding a lambda
            if func_name in self.variables:
                val = self.variables[func_name]
                if isinstance(val, LambdaValue):
                    return self._call_lambda(val, [piped_value])
            return self._call_function_with_args(func_name, [piped_value])
        
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


def _format_value(v):
    """Format a single sauravcode value for display."""
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    if isinstance(v, dict):
        return _format_map(v)
    if isinstance(v, list):
        return _format_list(v)
    if isinstance(v, set):
        return _format_set(v)
    return str(v)


def _format_list(lst):
    """Format a list for display."""
    return "[" + ", ".join(_format_value(v) for v in lst) + "]"


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
        pairs.append(f"{key_str}: {_format_value(v)}")
    return "{" + ", ".join(pairs) + "}"

def _format_set(s):
    """Format a set for display."""
    try:
        items = sorted(s)
    except TypeError:
        items = list(s)
    return "set(" + ", ".join(_format_value(v) for v in items) + ")"


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
    if isinstance(value, set):
        return _format_set(value)
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
                'http_get':       'http_get url [headers] — HTTP GET, returns {status, body, headers}',
                'http_post':      'http_post url body [h] — HTTP POST, returns {status, body, headers}',
                'http_put':       'http_put url body [h]  — HTTP PUT, returns {status, body, headers}',
                'http_delete':    'http_delete url [h]    — HTTP DELETE, returns {status, body, headers}',
                'color':          'color text name        — wrap text in foreground ANSI color',
                'bg_color':       'bg_color text name     — wrap text in background ANSI color',
                'bold':           'bold text              — bold text',
                'dim':            'dim text               — dim/faint text',
                'italic':         'italic text            — italic text',
                'underline':      'underline text         — underlined text',
                'strikethrough':  'strikethrough text     — strikethrough text',
                'style':          'style text s1 s2 ...   — apply multiple styles/colors at once',
                'rainbow':        'rainbow text           — rainbow-colored text',
                'strip_ansi':     'strip_ansi text        — remove all ANSI escape codes',
                'uuid_v4':        'uuid_v4               — generate random UUID v4 string',
                'random_bytes':   'random_bytes n         — list of n random bytes (0-255)',
                'random_hex':     'random_hex n           — random hex string of n bytes',
                'random_string':  'random_string n        — random alphanumeric string of length n',
                'random_float':   'random_float [min max] — random float in [0,1) or [min,max)',
                'csv_parse':      'csv_parse text [delim] — parse CSV text into list of maps',
                'csv_stringify':  'csv_stringify rows [delim] — convert list of maps to CSV text',
                'csv_headers':   'csv_headers rows       — extract column names from CSV data',
                'csv_select':    'csv_select rows cols   — select specific columns',
                'csv_filter':    'csv_filter rows col val — filter rows where col == val',
                'csv_sort':      'csv_sort rows col [dir] — sort rows by column (asc/desc)',
                'csv_read':      'csv_read path [delim]  — read and parse a CSV file',
                'csv_write':     'csv_write path rows [d] — write CSV data to a file',
                'is_email':      'is_email str          — true if valid email address',
                'is_url':        'is_url str            — true if valid HTTP/HTTPS URL',
                'is_ipv4':       'is_ipv4 str           — true if valid IPv4 address',
                'is_ipv6':       'is_ipv6 str           — true if valid IPv6 address',
                'is_ip':         'is_ip str             — true if valid IPv4 or IPv6',
                'is_date':       'is_date str           — true if parseable date string',
                'is_uuid':       'is_uuid str           — true if valid UUID format',
                'is_hex_color':  'is_hex_color str      — true if valid hex color (#RGB/#RRGGBB)',
                'is_phone':      'is_phone str          — true if valid phone number format',
                'is_credit_card':'is_credit_card str    — true if valid card number (Luhn)',
                'is_json':       'is_json str           — true if valid JSON string',
                'validate':      'validate val rules... — multi-rule validation → {valid, errors}',
                'deque_create':     'deque_create [list]     — create a double-ended queue',
                'deque_push_front': 'deque_push_front dq val — push item to front',
                'deque_push_back':  'deque_push_back dq val  — push item to back',
                'deque_pop_front':  'deque_pop_front dq      — remove & return front item',
                'deque_pop_back':   'deque_pop_back dq       — remove & return back item',
                'deque_peek_front': 'deque_peek_front dq     — view front item without removing',
                'deque_peek_back':  'deque_peek_back dq      — view back item without removing',
                'deque_size':       'deque_size dq           — number of items in deque',
                'deque_is_empty':   'deque_is_empty dq       — true if deque has no items',
                'deque_to_list':    'deque_to_list dq        — convert deque to list',
                'deque_rotate':     'deque_rotate dq n       — rotate deque n steps (positive=right)',
                'deque_clear':      'deque_clear dq          — remove all items from deque',
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
    """Entry point for the sauravcode interpreter CLI.

    Parses command-line arguments and either starts the interactive REPL
    (no arguments) or executes the specified .srv file. Supports ``--debug``
    flag for verbose tokenizer/parser output.
    """
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
            if DEBUG:
                debug(f"Read code from {filename}:\n{code}\n")
    except Exception as e:
        print(f"Error reading file '{filename}': {e}")
        sys.exit(1)
    
    # Tokenize and parse multiple top-level statements
    tokens = list(tokenize(code))
    if DEBUG:
        debug(f"\nTokens: {tokens}\n")

    parser = Parser(tokens)
    ast_nodes = parser.parse()
    if DEBUG:
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
    except SauravRuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    if result is not None:
        print("\nFinal result:", result)

if __name__ == '__main__':
    main()

