#!/usr/bin/env python3
"""
sauravhl.py - Syntax highlighter for sauravcode (.srv) programs.

Outputs beautifully colored source code in ANSI terminal format or HTML.
Supports customizable color themes, line numbers, and word-wrapping.

Usage:
    python sauravhl.py program.srv                     # ANSI terminal output
    python sauravhl.py program.srv --html              # HTML output
    python sauravhl.py program.srv --html -o out.html  # Save HTML to file
    python sauravhl.py program.srv --theme monokai     # Use monokai theme
    python sauravhl.py program.srv --lines             # Show line numbers
    python sauravhl.py program.srv --list-themes       # List available themes
    python sauravhl.py src/ --recursive --html         # Highlight directory

Themes: default, monokai, solarized, dracula, github, nord
"""

import re
import sys
import os
import argparse
from pathlib import Path

# ── Token patterns (mirrors saurav.py lexer) ──────────────────────────

TOKEN_SPEC = [
    ('COMMENT',  r'#.*'),
    ('NUMBER',   r'\d+(\.\d*)?'),
    ('FSTRING',  r'f\"(?:[^\"\\]|\\.)*\"'),
    ('STRING',   r'\"(?:[^\"\\]|\\.)*\"'),
    ('EQ',       r'=='),
    ('NEQ',      r'!='),
    ('LTE',      r'<='),
    ('GTE',      r'>='),
    ('LT',       r'<'),
    ('GT',       r'>'),
    ('ASSIGN',   r'='),
    ('ARROW',    r'->'),
    ('PIPE',     r'\|>'),
    ('BAR',      r'\|'),
    ('OP',       r'[+\-*/%]'),
    ('LPAREN',   r'\('),
    ('RPAREN',   r'\)'),
    ('LBRACKET', r'\['),
    ('RBRACKET', r'\]'),
    ('LBRACE',   r'\{'),
    ('RBRACE',   r'\}'),
    ('COLON',    r':'),
    ('COMMA',    r','),
    ('DOT',      r'\.'),
    ('KEYWORD',  r'\b(?:function|return|class|int|float|bool|string|if|else if|else|for|in|while|try|catch|throw|print|true|false|and|or|not|list|set|stack|queue|append|len|pop|lambda|import|match|case|enum|break|continue|assert|yield|next)\b'),
    ('IDENT',    r'[a-zA-Z_]\w*'),
    ('NEWLINE',  r'\n'),
    ('SPACE',    r'[ \t]+'),
    ('MISMATCH', r'.'),
]

_tok_regex = re.compile('|'.join(f'(?P<{name}>{pat})' for name, pat in TOKEN_SPEC))

# Built-in function names for special highlighting
BUILTINS = {
    'print', 'len', 'append', 'pop', 'push', 'peek', 'enqueue', 'dequeue',
    'range', 'abs', 'max', 'min', 'sum', 'sorted', 'reversed', 'enumerate',
    'zip', 'map', 'filter', 'reduce', 'any', 'all', 'type', 'str', 'int',
    'float', 'bool', 'input', 'round', 'floor', 'ceil', 'sqrt', 'log',
    'sin', 'cos', 'tan', 'random', 'randint', 'choice', 'shuffle',
    'upper', 'lower', 'strip', 'split', 'join', 'replace', 'find',
    'startswith', 'endswith', 'contains', 'keys', 'values', 'items',
    'has_key', 'remove', 'clear', 'copy', 'count', 'index', 'insert',
    'extend', 'slice', 'chars', 'to_int', 'to_float', 'to_str',
    'read_file', 'write_file', 'file_exists', 'sleep', 'time', 'now',
    'format_date', 'timestamp',
}

# Type keywords for special color
TYPE_KEYWORDS = {'int', 'float', 'bool', 'string', 'list', 'set', 'stack', 'queue'}

# Control flow keywords
CONTROL_KEYWORDS = {'if', 'else', 'else if', 'for', 'while', 'match', 'case',
                    'break', 'continue', 'return', 'try', 'catch', 'throw', 'yield', 'next'}

# Declaration keywords
DECL_KEYWORDS = {'function', 'class', 'enum', 'import', 'lambda'}

# Literal keywords
LITERAL_KEYWORDS = {'true', 'false'}

# ── Color Themes ──────────────────────────────────────────────────────

# ANSI 256-color / truecolor escape helpers
def _ansi(code):
    return f'\033[{code}m'

RESET = _ansi(0)

# Theme = dict mapping token category → ANSI escape
THEMES_ANSI = {
    'default': {
        'keyword_control': _ansi('1;35'),      # bold magenta
        'keyword_decl':    _ansi('1;34'),       # bold blue
        'keyword_type':    _ansi('36'),         # cyan
        'keyword_literal': _ansi('33'),         # yellow
        'keyword_other':   _ansi('35'),         # magenta
        'builtin':         _ansi('1;36'),       # bold cyan
        'string':          _ansi('32'),         # green
        'fstring':         _ansi('1;32'),       # bold green
        'number':          _ansi('33'),         # yellow
        'comment':         _ansi('2;37'),       # dim gray
        'operator':        _ansi('37'),         # white
        'punctuation':     _ansi('37'),         # white
        'identifier':      _ansi('0'),          # default
        'lineno':          _ansi('2;36'),       # dim cyan
    },
    'monokai': {
        'keyword_control': _ansi('38;5;197'),   # pink
        'keyword_decl':    _ansi('38;5;81'),    # light blue
        'keyword_type':    _ansi('38;5;81'),    # light blue
        'keyword_literal': _ansi('38;5;141'),   # purple
        'keyword_other':   _ansi('38;5;197'),   # pink
        'builtin':         _ansi('38;5;148'),   # green-yellow
        'string':          _ansi('38;5;186'),   # light yellow
        'fstring':         _ansi('1;38;5;186'), # bold light yellow
        'number':          _ansi('38;5;141'),   # purple
        'comment':         _ansi('38;5;242'),   # gray
        'operator':        _ansi('38;5;197'),   # pink
        'punctuation':     _ansi('38;5;248'),   # light gray
        'identifier':      _ansi('38;5;231'),   # white
        'lineno':          _ansi('38;5;239'),   # dark gray
    },
    'solarized': {
        'keyword_control': _ansi('38;5;166'),   # orange
        'keyword_decl':    _ansi('38;5;33'),    # blue
        'keyword_type':    _ansi('38;5;37'),    # cyan
        'keyword_literal': _ansi('38;5;136'),   # yellow
        'keyword_other':   _ansi('38;5;125'),   # magenta
        'builtin':         _ansi('38;5;64'),    # green
        'string':          _ansi('38;5;37'),    # cyan
        'fstring':         _ansi('1;38;5;37'),  # bold cyan
        'number':          _ansi('38;5;136'),   # yellow
        'comment':         _ansi('38;5;245'),   # base1
        'operator':        _ansi('38;5;166'),   # orange
        'punctuation':     _ansi('38;5;244'),   # base0
        'identifier':      _ansi('38;5;246'),   # base0
        'lineno':          _ansi('38;5;240'),   # base01
    },
    'dracula': {
        'keyword_control': _ansi('38;5;212'),   # pink
        'keyword_decl':    _ansi('38;5;141'),   # purple
        'keyword_type':    _ansi('38;5;117'),   # cyan
        'keyword_literal': _ansi('38;5;141'),   # purple
        'keyword_other':   _ansi('38;5;212'),   # pink
        'builtin':         _ansi('38;5;84'),    # green
        'string':          _ansi('38;5;228'),   # yellow
        'fstring':         _ansi('1;38;5;228'), # bold yellow
        'number':          _ansi('38;5;141'),   # purple
        'comment':         _ansi('38;5;61'),    # comment blue
        'operator':        _ansi('38;5;212'),   # pink
        'punctuation':     _ansi('38;5;248'),   # foreground
        'identifier':      _ansi('38;5;231'),   # white
        'lineno':          _ansi('38;5;239'),   # line number
    },
    'github': {
        'keyword_control': _ansi('38;5;167'),   # red
        'keyword_decl':    _ansi('38;5;167'),   # red
        'keyword_type':    _ansi('38;5;30'),    # teal
        'keyword_literal': _ansi('38;5;30'),    # teal
        'keyword_other':   _ansi('38;5;167'),   # red
        'builtin':         _ansi('38;5;99'),    # purple
        'string':          _ansi('38;5;24'),    # dark blue
        'fstring':         _ansi('1;38;5;24'),  # bold dark blue
        'number':          _ansi('38;5;30'),    # teal
        'comment':         _ansi('38;5;245'),   # gray
        'operator':        _ansi('38;5;236'),   # dark
        'punctuation':     _ansi('38;5;236'),   # dark
        'identifier':      _ansi('38;5;236'),   # dark
        'lineno':          _ansi('38;5;250'),   # light gray
    },
    'nord': {
        'keyword_control': _ansi('38;5;176'),   # purple
        'keyword_decl':    _ansi('38;5;110'),   # frost blue
        'keyword_type':    _ansi('38;5;110'),   # frost blue
        'keyword_literal': _ansi('38;5;176'),   # purple
        'keyword_other':   _ansi('38;5;176'),   # purple
        'builtin':         _ansi('38;5;138'),   # aurora
        'string':          _ansi('38;5;150'),   # green
        'fstring':         _ansi('1;38;5;150'), # bold green
        'number':          _ansi('38;5;208'),   # orange
        'comment':         _ansi('38;5;60'),    # polar night
        'operator':        _ansi('38;5;110'),   # frost
        'punctuation':     _ansi('38;5;67'),    # frost dim
        'identifier':      _ansi('38;5;188'),   # snow
        'lineno':          _ansi('38;5;60'),    # polar night
    },
}

# HTML color themes (CSS color values)
THEMES_HTML = {
    'default': {
        'keyword_control': '#c678dd',
        'keyword_decl':    '#61afef',
        'keyword_type':    '#56b6c2',
        'keyword_literal': '#d19a66',
        'keyword_other':   '#c678dd',
        'builtin':         '#56b6c2; font-weight: bold',
        'string':          '#98c379',
        'fstring':         '#98c379; font-weight: bold',
        'number':          '#d19a66',
        'comment':         '#5c6370; font-style: italic',
        'operator':        '#abb2bf',
        'punctuation':     '#abb2bf',
        'identifier':      '#abb2bf',
        'background':      '#282c34',
        'lineno':          '#4b5263',
    },
    'monokai': {
        'keyword_control': '#f92672',
        'keyword_decl':    '#66d9ef',
        'keyword_type':    '#66d9ef',
        'keyword_literal': '#ae81ff',
        'keyword_other':   '#f92672',
        'builtin':         '#a6e22e; font-weight: bold',
        'string':          '#e6db74',
        'fstring':         '#e6db74; font-weight: bold',
        'number':          '#ae81ff',
        'comment':         '#75715e; font-style: italic',
        'operator':        '#f92672',
        'punctuation':     '#f8f8f2',
        'identifier':      '#f8f8f2',
        'background':      '#272822',
        'lineno':          '#49483e',
    },
    'solarized': {
        'keyword_control': '#cb4b16',
        'keyword_decl':    '#268bd2',
        'keyword_type':    '#2aa198',
        'keyword_literal': '#b58900',
        'keyword_other':   '#d33682',
        'builtin':         '#859900; font-weight: bold',
        'string':          '#2aa198',
        'fstring':         '#2aa198; font-weight: bold',
        'number':          '#b58900',
        'comment':         '#93a1a1; font-style: italic',
        'operator':        '#cb4b16',
        'punctuation':     '#839496',
        'identifier':      '#839496',
        'background':      '#002b36',
        'lineno':          '#586e75',
    },
    'dracula': {
        'keyword_control': '#ff79c6',
        'keyword_decl':    '#bd93f9',
        'keyword_type':    '#8be9fd',
        'keyword_literal': '#bd93f9',
        'keyword_other':   '#ff79c6',
        'builtin':         '#50fa7b; font-weight: bold',
        'string':          '#f1fa8c',
        'fstring':         '#f1fa8c; font-weight: bold',
        'number':          '#bd93f9',
        'comment':         '#6272a4; font-style: italic',
        'operator':        '#ff79c6',
        'punctuation':     '#f8f8f2',
        'identifier':      '#f8f8f2',
        'background':      '#282a36',
        'lineno':          '#44475a',
    },
    'github': {
        'keyword_control': '#d73a49',
        'keyword_decl':    '#d73a49',
        'keyword_type':    '#005cc5',
        'keyword_literal': '#005cc5',
        'keyword_other':   '#d73a49',
        'builtin':         '#6f42c1; font-weight: bold',
        'string':          '#032f62',
        'fstring':         '#032f62; font-weight: bold',
        'number':          '#005cc5',
        'comment':         '#6a737d; font-style: italic',
        'operator':        '#24292e',
        'punctuation':     '#24292e',
        'identifier':      '#24292e',
        'background':      '#ffffff',
        'lineno':          '#babbbd',
    },
    'nord': {
        'keyword_control': '#b48ead',
        'keyword_decl':    '#81a1c1',
        'keyword_type':    '#81a1c1',
        'keyword_literal': '#b48ead',
        'keyword_other':   '#b48ead',
        'builtin':         '#88c0d0; font-weight: bold',
        'string':          '#a3be8c',
        'fstring':         '#a3be8c; font-weight: bold',
        'number':          '#d08770',
        'comment':         '#4c566a; font-style: italic',
        'operator':        '#81a1c1',
        'punctuation':     '#d8dee9',
        'identifier':      '#d8dee9',
        'background':      '#2e3440',
        'lineno':          '#4c566a',
    },
}


def _classify_token(tok_type, tok_value):
    """Return the highlight category for a token."""
    if tok_type == 'COMMENT':
        return 'comment'
    if tok_type == 'FSTRING':
        return 'fstring'
    if tok_type == 'STRING':
        return 'string'
    if tok_type == 'NUMBER':
        return 'number'
    if tok_type == 'KEYWORD':
        if tok_value in CONTROL_KEYWORDS:
            return 'keyword_control'
        if tok_value in DECL_KEYWORDS:
            return 'keyword_decl'
        if tok_value in TYPE_KEYWORDS:
            return 'keyword_type'
        if tok_value in LITERAL_KEYWORDS:
            return 'keyword_literal'
        return 'keyword_other'
    if tok_type == 'IDENT':
        if tok_value in BUILTINS:
            return 'builtin'
        return 'identifier'
    if tok_type in ('OP', 'ASSIGN', 'EQ', 'NEQ', 'LTE', 'GTE', 'LT', 'GT',
                    'ARROW', 'PIPE', 'BAR'):
        return 'operator'
    if tok_type in ('LPAREN', 'RPAREN', 'LBRACKET', 'RBRACKET',
                    'LBRACE', 'RBRACE', 'COLON', 'COMMA', 'DOT'):
        return 'punctuation'
    return None  # SPACE, NEWLINE, MISMATCH


def tokenize(source):
    """Tokenize source into (type, value, category) tuples."""
    tokens = []
    for m in _tok_regex.finditer(source):
        tok_type = m.lastgroup
        tok_value = m.group()
        category = _classify_token(tok_type, tok_value)
        tokens.append((tok_type, tok_value, category))
    return tokens


# ── ANSI Output ───────────────────────────────────────────────────────

def highlight_ansi(source, theme_name='default', line_numbers=False):
    """Return ANSI-colored string of the source code."""
    theme = THEMES_ANSI.get(theme_name, THEMES_ANSI['default'])
    tokens = tokenize(source)
    parts = []
    line_num = 1

    if line_numbers:
        total_lines = source.count('\n') + 1
        width = len(str(total_lines))
        parts.append(f"{theme['lineno']}{str(line_num).rjust(width)} {RESET}")

    for tok_type, tok_value, category in tokens:
        if tok_type == 'NEWLINE':
            parts.append('\n')
            line_num += 1
            if line_numbers:
                total_lines = source.count('\n') + 1
                width = len(str(total_lines))
                parts.append(f"{theme['lineno']}{str(line_num).rjust(width)} {RESET}")
        elif category:
            color = theme.get(category, '')
            parts.append(f"{color}{tok_value}{RESET}")
        else:
            parts.append(tok_value)

    return ''.join(parts)


# ── HTML Output ───────────────────────────────────────────────────────

def _html_escape(text):
    """Escape HTML special characters."""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def highlight_html(source, theme_name='default', line_numbers=False, standalone=True, title=None):
    """Return HTML-formatted highlighted source code."""
    theme = THEMES_HTML.get(theme_name, THEMES_HTML['default'])
    tokens = tokenize(source)

    # Build CSS
    css_rules = []
    for cat in ('keyword_control', 'keyword_decl', 'keyword_type', 'keyword_literal',
                'keyword_other', 'builtin', 'string', 'fstring', 'number',
                'comment', 'operator', 'punctuation', 'identifier'):
        style_val = theme[cat]
        css_rules.append(f'.srv-{cat} {{ color: {style_val}; }}')

    css = f"""
.srv-highlight {{
    background: {theme['background']};
    color: {theme.get('identifier', '#abb2bf')};
    font-family: 'Fira Code', 'JetBrains Mono', 'Cascadia Code', 'Consolas', monospace;
    font-size: 14px;
    line-height: 1.5;
    padding: 16px 20px;
    border-radius: 8px;
    overflow-x: auto;
    tab-size: 4;
    white-space: pre;
}}
.srv-lineno {{
    color: {theme.get('lineno', '#4b5263')};
    user-select: none;
    margin-right: 16px;
    display: inline-block;
    text-align: right;
    min-width: 2em;
}}
{chr(10).join(css_rules)}
"""

    # Build code HTML
    code_parts = []
    line_num = 1

    if line_numbers:
        total_lines = source.count('\n') + 1
        width = len(str(total_lines))
        code_parts.append(f'<span class="srv-lineno">{str(line_num).rjust(width)}</span>')

    for tok_type, tok_value, category in tokens:
        if tok_type == 'NEWLINE':
            code_parts.append('\n')
            line_num += 1
            if line_numbers:
                total_lines = source.count('\n') + 1
                width = len(str(total_lines))
                code_parts.append(f'<span class="srv-lineno">{str(line_num).rjust(width)}</span>')
        elif category:
            escaped = _html_escape(tok_value)
            code_parts.append(f'<span class="srv-{category}">{escaped}</span>')
        else:
            code_parts.append(_html_escape(tok_value))

    code_html = ''.join(code_parts)
    inner = f'<pre class="srv-highlight"><code>{code_html}</code></pre>'

    if not standalone:
        return f'<style>{css}</style>\n{inner}'

    page_title = _html_escape(title or 'sauravcode — highlighted source')
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{page_title}</title>
<style>
body {{
    margin: 0;
    padding: 24px;
    background: {theme['background']};
    min-height: 100vh;
}}
h1 {{
    color: {theme.get('identifier', '#abb2bf')};
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    font-size: 18px;
    font-weight: 400;
    margin: 0 0 16px 0;
    opacity: 0.7;
}}
{css}
</style>
</head>
<body>
<h1>{page_title}</h1>
{inner}
</body>
</html>"""


# ── Directory Processing ──────────────────────────────────────────────

def find_srv_files(path, recursive=False):
    """Find all .srv files in a directory."""
    p = Path(path)
    if p.is_file():
        return [p]
    if recursive:
        return sorted(p.rglob('*.srv'))
    return sorted(p.glob('*.srv'))


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog='sauravhl',
        description='Syntax highlighter for sauravcode (.srv) programs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python sauravhl.py hello.srv                       # ANSI terminal output
  python sauravhl.py hello.srv --html -o hello.html  # HTML file
  python sauravhl.py hello.srv --theme monokai       # Monokai colors
  python sauravhl.py hello.srv --lines               # With line numbers
  python sauravhl.py src/ --recursive --html          # All .srv files
  python sauravhl.py --list-themes                    # Show themes
""")

    parser.add_argument('path', nargs='?', help='Source file or directory')
    parser.add_argument('--html', action='store_true', help='Output HTML instead of ANSI')
    parser.add_argument('--theme', '-t', default='default',
                        choices=list(THEMES_ANSI.keys()),
                        help='Color theme (default: default)')
    parser.add_argument('--lines', '-n', action='store_true', help='Show line numbers')
    parser.add_argument('--output', '-o', help='Output file (default: stdout)')
    parser.add_argument('--recursive', '-r', action='store_true',
                        help='Process directory recursively')
    parser.add_argument('--list-themes', action='store_true', help='List available themes')
    parser.add_argument('--fragment', action='store_true',
                        help='HTML: output fragment (no full page wrapper)')
    parser.add_argument('--title', help='HTML page title')

    args = parser.parse_args()

    if args.list_themes:
        print('Available themes:')
        for name in THEMES_ANSI:
            print(f'  {name}')
        return

    if not args.path:
        parser.error('path is required (unless --list-themes)')

    files = find_srv_files(args.path, args.recursive)
    if not files:
        print(f'Error: No .srv files found in {args.path}', file=sys.stderr)
        sys.exit(1)

    outputs = []
    for filepath in files:
        source = filepath.read_text(encoding='utf-8')

        if args.html:
            title = args.title or filepath.name
            result = highlight_html(source, args.theme, args.lines,
                                    standalone=not args.fragment, title=title)
        else:
            result = highlight_ansi(source, args.theme, args.lines)

        if len(files) > 1 and not args.html:
            outputs.append(f'\n{"─" * 60}\n  {filepath}\n{"─" * 60}\n')
        outputs.append(result)

    output = '\n'.join(outputs)

    if args.output:
        Path(args.output).write_text(output, encoding='utf-8')
        print(f'Written to {args.output}')
    else:
        print(output)


if __name__ == '__main__':
    main()
