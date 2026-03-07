#!/usr/bin/env python3
"""sauravnb — Notebook runner for sauravcode (.srvnb files).

A lightweight Jupyter-like notebook format for sauravcode. Notebooks contain
markdown cells and code cells separated by cell markers. The runner executes
code cells sequentially with a shared interpreter, captures output, and can
export results to HTML or run headless for CI.

Notebook format (.srvnb):
    --- md ---
    # My Notebook
    This is a **markdown** cell.

    --- code ---
    x = 10
    print(x + 5)

    --- md ---
    The result above should be 15.

    --- code ---
    function square(n)
        return n * n
    print(square(x))

Usage:
    python sauravnb.py notebook.srvnb              Run notebook, show output
    python sauravnb.py notebook.srvnb --html out.html   Export to self-contained HTML
    python sauravnb.py notebook.srvnb --stats       Show execution statistics
    python sauravnb.py notebook.srvnb --cell 2      Run only cell #2 (1-indexed code cells)
    python sauravnb.py notebook.srvnb --dry-run     Parse and validate without executing
    python sauravnb.py --new blank.srvnb            Create a starter notebook
"""

import sys
import os
import re
import time
import io
import contextlib
import html as html_mod
import argparse

# Add parent directory to path for saurav imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from saurav import tokenize, Parser, Interpreter, ThrowSignal, ReturnSignal

# ── Cell types ───────────────────────────────────────────────

class Cell:
    """Base cell in a notebook."""
    def __init__(self, cell_type, content, line_number=0):
        self.cell_type = cell_type
        self.content = content
        self.line_number = line_number

class MarkdownCell(Cell):
    def __init__(self, content, line_number=0):
        super().__init__('md', content, line_number)

class CodeCell(Cell):
    def __init__(self, content, line_number=0):
        super().__init__('code', content, line_number)
        self.output = ''
        self.error = None
        self.elapsed_ms = 0.0
        self.executed = False

# ── Parser ───────────────────────────────────────────────────

_CELL_MARKER = re.compile(r'^---\s*(md|code)\s*---\s*$', re.IGNORECASE)

def parse_notebook(text):
    """Parse a .srvnb file into a list of Cell objects."""
    lines = text.split('\n')
    cells = []
    current_type = None
    current_lines = []
    current_start = 1

    for i, line in enumerate(lines, 1):
        m = _CELL_MARKER.match(line.strip())
        if m:
            # Flush previous cell
            if current_type is not None:
                content = '\n'.join(current_lines).strip()
                if content or current_type == 'code':
                    cls = MarkdownCell if current_type == 'md' else CodeCell
                    cells.append(cls(content, current_start))
            current_type = m.group(1).lower()
            current_lines = []
            current_start = i + 1
        else:
            if current_type is not None:
                current_lines.append(line)
            else:
                # Lines before any marker are treated as markdown
                if not cells and line.strip():
                    current_type = 'md'
                    current_lines.append(line)
                    current_start = i

    # Flush final cell
    if current_type is not None:
        content = '\n'.join(current_lines).strip()
        if content or current_type == 'code':
            cls = MarkdownCell if current_type == 'md' else CodeCell
            cells.append(cls(content, current_start))

    return cells

# ── Executor ─────────────────────────────────────────────────

def execute_notebook(cells, only_cell=None):
    """Execute code cells with a shared interpreter.
    
    Args:
        cells: list of Cell objects
        only_cell: if set, only execute this 1-indexed code cell number
    
    Returns:
        (cells, stats) where stats is a dict with execution metadata
    """
    interpreter = Interpreter()
    interpreter._source_dir = os.getcwd()

    code_index = 0
    total_time = 0.0
    executed_count = 0
    error_count = 0

    for cell in cells:
        if not isinstance(cell, CodeCell):
            continue
        code_index += 1

        if only_cell is not None and code_index != only_cell:
            continue

        if not cell.content.strip():
            cell.output = ''
            cell.executed = True
            continue

        # Capture stdout
        buf = io.StringIO()
        start = time.perf_counter()
        try:
            tokens = list(tokenize(cell.content))
            parser = Parser(tokens)
            ast_nodes = parser.parse()

            with contextlib.redirect_stdout(buf):
                for node in ast_nodes:
                    try:
                        interpreter.interpret(node)
                    except ReturnSignal:
                        pass
            cell.output = buf.getvalue()
            cell.executed = True
        except ThrowSignal as e:
            cell.output = buf.getvalue()
            msg = e.message
            if isinstance(msg, float) and msg == int(msg):
                msg = int(msg)
            cell.error = f"Uncaught error: {msg}"
            error_count += 1
            cell.executed = True
        except Exception as e:
            cell.output = buf.getvalue()
            cell.error = str(e)
            error_count += 1
            cell.executed = True
        finally:
            elapsed = (time.perf_counter() - start) * 1000
            cell.elapsed_ms = elapsed
            total_time += elapsed
            executed_count += 1

    stats = {
        'total_cells': len(cells),
        'code_cells': sum(1 for c in cells if isinstance(c, CodeCell)),
        'md_cells': sum(1 for c in cells if isinstance(c, MarkdownCell)),
        'executed': executed_count,
        'errors': error_count,
        'total_time_ms': total_time,
    }
    return cells, stats

# ── Terminal renderer ────────────────────────────────────────

_BOLD = '\033[1m'
_DIM = '\033[2m'
_GREEN = '\033[32m'
_RED = '\033[31m'
_CYAN = '\033[36m'
_YELLOW = '\033[33m'
_RESET = '\033[0m'
_BLUE = '\033[34m'

def render_terminal(cells, stats, show_stats=False):
    """Render executed notebook to terminal with colors."""
    # Force UTF-8 stdout on Windows
    if sys.platform == 'win32' and hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
    code_idx = 0
    for cell in cells:
        if isinstance(cell, MarkdownCell):
            # Render markdown as dimmed text with bold headers
            for line in cell.content.split('\n'):
                if line.startswith('#'):
                    print(f"{_BOLD}{_CYAN}{line}{_RESET}")
                elif line.startswith('- ') or line.startswith('* '):
                    print(f"  {_DIM}{line}{_RESET}")
                else:
                    print(f"{_DIM}{line}{_RESET}")
            print()
        elif isinstance(cell, CodeCell):
            code_idx += 1
            if not cell.executed:
                print(f"{_DIM}[{code_idx}] (skipped){_RESET}\n")
                continue

            # Cell header
            status = f"{_GREEN}✓{_RESET}" if cell.error is None else f"{_RED}✗{_RESET}"
            time_str = f"{cell.elapsed_ms:.1f}ms"
            print(f"{_BLUE}In [{code_idx}]{_RESET} {status} {_DIM}{time_str}{_RESET}")

            # Code
            for line in cell.content.split('\n'):
                print(f"  {line}")

            # Output
            if cell.output.strip():
                print(f"{_YELLOW}Out[{code_idx}]:{_RESET}")
                for line in cell.output.rstrip('\n').split('\n'):
                    print(f"  {line}")

            # Error
            if cell.error:
                print(f"{_RED}Err[{code_idx}]: {cell.error}{_RESET}")

            print()

    if show_stats:
        print(f"{_BOLD}── Notebook Stats ──{_RESET}")
        print(f"  Cells: {stats['total_cells']} ({stats['code_cells']} code, {stats['md_cells']} markdown)")
        print(f"  Executed: {stats['executed']}, Errors: {stats['errors']}")
        print(f"  Total time: {stats['total_time_ms']:.1f}ms")
        ok = stats['errors'] == 0
        print(f"  Status: {_GREEN}ALL PASSED{_RESET}" if ok else f"  Status: {_RED}{stats['errors']} ERRORS{_RESET}")

# ── HTML exporter ────────────────────────────────────────────

def render_html(cells, stats, title="Sauravcode Notebook"):
    """Generate a self-contained HTML page from executed notebook."""
    parts = []
    parts.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html_mod.escape(title)}</title>
<style>
:root {{ --bg: #1a1b26; --fg: #c0caf5; --code-bg: #24283b; --out-bg: #1f2335;
         --border: #3b4261; --accent: #7aa2f7; --green: #9ece6a; --red: #f7768e;
         --dim: #565f89; --yellow: #e0af68; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg);
        color: var(--fg); line-height: 1.6; padding: 2rem; max-width: 900px; margin: auto; }}
h1, h2, h3, h4 {{ color: var(--accent); margin: 1rem 0 0.5rem; }}
h1 {{ font-size: 1.8rem; border-bottom: 2px solid var(--border); padding-bottom: 0.5rem; }}
.md-cell {{ margin: 1rem 0; padding: 0.5rem 1rem; }}
.md-cell p {{ margin: 0.3rem 0; }}
.code-cell {{ margin: 1rem 0; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }}
.cell-header {{ display: flex; justify-content: space-between; align-items: center;
                padding: 0.3rem 1rem; background: var(--code-bg); border-bottom: 1px solid var(--border);
                font-size: 0.85rem; }}
.cell-label {{ color: var(--accent); font-weight: 600; }}
.cell-time {{ color: var(--dim); }}
.cell-status {{ font-size: 1.1rem; margin-right: 0.5rem; }}
pre {{ margin: 0; padding: 1rem; font-family: 'Cascadia Code', 'Fira Code', monospace;
       font-size: 0.9rem; white-space: pre-wrap; word-wrap: break-word; }}
.code-content {{ background: var(--code-bg); }}
.code-output {{ background: var(--out-bg); border-top: 1px solid var(--border); color: var(--yellow); }}
.code-error {{ background: #2d202a; border-top: 1px solid var(--red); color: var(--red); }}
.stats {{ margin-top: 2rem; padding: 1rem; background: var(--code-bg); border-radius: 8px;
          border: 1px solid var(--border); font-size: 0.9rem; }}
.stats-title {{ color: var(--accent); font-weight: 600; margin-bottom: 0.5rem; }}
.stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 0.5rem; }}
.stat {{ padding: 0.5rem; background: var(--out-bg); border-radius: 4px; text-align: center; }}
.stat-value {{ font-size: 1.3rem; font-weight: 700; color: var(--accent); }}
.stat-label {{ font-size: 0.8rem; color: var(--dim); }}
strong {{ color: var(--accent); }}
em {{ color: var(--yellow); }}
code {{ background: var(--code-bg); padding: 0.15rem 0.4rem; border-radius: 3px; font-family: monospace; }}
ul, ol {{ padding-left: 1.5rem; margin: 0.5rem 0; }}
</style>
</head>
<body>
""")

    code_idx = 0
    for cell in cells:
        if isinstance(cell, MarkdownCell):
            rendered = _simple_md_to_html(cell.content)
            parts.append(f'<div class="md-cell">{rendered}</div>\n')
        elif isinstance(cell, CodeCell):
            code_idx += 1
            if not cell.executed:
                continue
            status_icon = '✓' if cell.error is None else '✗'
            status_color = 'var(--green)' if cell.error is None else 'var(--red)'
            parts.append(f'''<div class="code-cell">
<div class="cell-header">
  <span><span class="cell-status" style="color:{status_color}">{status_icon}</span><span class="cell-label">In [{code_idx}]</span></span>
  <span class="cell-time">{cell.elapsed_ms:.1f}ms</span>
</div>
<pre class="code-content">{html_mod.escape(cell.content)}</pre>
''')
            if cell.output.strip():
                parts.append(f'<pre class="code-output">{html_mod.escape(cell.output.rstrip())}</pre>\n')
            if cell.error:
                parts.append(f'<pre class="code-error">{html_mod.escape(cell.error)}</pre>\n')
            parts.append('</div>\n')

    # Stats footer
    status_text = "ALL PASSED" if stats['errors'] == 0 else f"{stats['errors']} ERRORS"
    status_color = 'var(--green)' if stats['errors'] == 0 else 'var(--red)'
    parts.append(f'''<div class="stats">
<div class="stats-title">Notebook Statistics</div>
<div class="stats-grid">
  <div class="stat"><div class="stat-value">{stats['total_cells']}</div><div class="stat-label">Total Cells</div></div>
  <div class="stat"><div class="stat-value">{stats['code_cells']}</div><div class="stat-label">Code Cells</div></div>
  <div class="stat"><div class="stat-value">{stats['md_cells']}</div><div class="stat-label">Markdown Cells</div></div>
  <div class="stat"><div class="stat-value">{stats['executed']}</div><div class="stat-label">Executed</div></div>
  <div class="stat"><div class="stat-value" style="color:{status_color}">{status_text}</div><div class="stat-label">Status</div></div>
  <div class="stat"><div class="stat-value">{stats['total_time_ms']:.0f}ms</div><div class="stat-label">Total Time</div></div>
</div>
</div>
</body></html>''')

    return ''.join(parts)


def _simple_md_to_html(md):
    """Minimal markdown to HTML (headers, bold, italic, code, lists, paragraphs)."""
    lines = md.split('\n')
    html_lines = []
    in_list = False

    for line in lines:
        stripped = line.strip()

        # Headers
        if stripped.startswith('####'):
            if in_list: html_lines.append('</ul>'); in_list = False
            html_lines.append(f'<h4>{_inline_md(stripped[4:].strip())}</h4>')
        elif stripped.startswith('###'):
            if in_list: html_lines.append('</ul>'); in_list = False
            html_lines.append(f'<h3>{_inline_md(stripped[3:].strip())}</h3>')
        elif stripped.startswith('##'):
            if in_list: html_lines.append('</ul>'); in_list = False
            html_lines.append(f'<h2>{_inline_md(stripped[2:].strip())}</h2>')
        elif stripped.startswith('#'):
            if in_list: html_lines.append('</ul>'); in_list = False
            html_lines.append(f'<h1>{_inline_md(stripped[1:].strip())}</h1>')
        # List items
        elif stripped.startswith('- ') or stripped.startswith('* '):
            if not in_list: html_lines.append('<ul>'); in_list = True
            html_lines.append(f'<li>{_inline_md(stripped[2:])}</li>')
        # Empty line
        elif not stripped:
            if in_list: html_lines.append('</ul>'); in_list = False
            html_lines.append('')
        # Paragraph
        else:
            if in_list: html_lines.append('</ul>'); in_list = False
            html_lines.append(f'<p>{_inline_md(stripped)}</p>')

    if in_list:
        html_lines.append('</ul>')

    return '\n'.join(html_lines)


def _inline_md(text):
    """Handle inline markdown: bold, italic, code."""
    text = html_mod.escape(text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
    return text


# ── Starter notebook ─────────────────────────────────────────

STARTER_NOTEBOOK = """--- md ---
# My Sauravcode Notebook
Welcome! This is a sauravcode notebook. Mix **markdown** and **code** cells freely.

--- code ---
# Variables persist across cells
x = 10
y = 20
print(x + y)

--- md ---
## Functions
Define functions in one cell, use them in the next.

--- code ---
function factorial n
    if n <= 1
        return 1
    return n * factorial(n - 1)

print(factorial(5))
print(factorial(10))

--- md ---
## Collections
Lists, maps, and higher-order functions work great in notebooks.

--- code ---
nums = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
evens = filter("is_even", nums)

function is_even n
    return n % 2 == 0

evens = filter("is_even", nums)
print(evens)

--- md ---
## F-Strings
Use f-strings for clean output formatting.

--- code ---
name = "Sauravcode"
version = 1
print(f"{name} notebook v{version} is running!")
print(f"We computed {factorial(7)} = 7! earlier")

--- md ---
---
*Generated by sauravnb*
"""

# ── CLI ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog='sauravnb',
        description='Notebook runner for sauravcode (.srvnb files)',
        epilog='Example: python sauravnb.py demo.srvnb --html report.html'
    )
    parser.add_argument('notebook', nargs='?', help='Path to .srvnb notebook file')
    parser.add_argument('--html', metavar='FILE', help='Export executed notebook to HTML')
    parser.add_argument('--stats', action='store_true', help='Show execution statistics')
    parser.add_argument('--cell', type=int, metavar='N', help='Run only code cell #N (1-indexed)')
    parser.add_argument('--dry-run', action='store_true', help='Parse and validate without executing')
    parser.add_argument('--new', metavar='FILE', help='Create a starter notebook')
    parser.add_argument('--quiet', action='store_true', help='Suppress terminal output (useful with --html)')

    args = parser.parse_args()

    # Create starter notebook
    if args.new:
        if os.path.exists(args.new):
            print(f"Error: '{args.new}' already exists.", file=sys.stderr)
            sys.exit(1)
        with open(args.new, 'w') as f:
            f.write(STARTER_NOTEBOOK.lstrip())
        print(f"Created starter notebook: {args.new}")
        return

    if not args.notebook:
        parser.print_help()
        sys.exit(1)

    if not os.path.isfile(args.notebook):
        print(f"Error: File '{args.notebook}' not found.", file=sys.stderr)
        sys.exit(1)

    with open(args.notebook, 'r') as f:
        text = f.read()

    cells = parse_notebook(text)

    if not cells:
        print("Notebook is empty — no cells found.", file=sys.stderr)
        sys.exit(1)

    code_count = sum(1 for c in cells if isinstance(c, CodeCell))
    md_count = sum(1 for c in cells if isinstance(c, MarkdownCell))

    if args.dry_run:
        print(f"Notebook parsed successfully: {len(cells)} cells ({code_count} code, {md_count} markdown)")
        for i, cell in enumerate(cells, 1):
            label = 'md' if isinstance(cell, MarkdownCell) else 'code'
            lines = len(cell.content.split('\n'))
            print(f"  [{i}] {label} — {lines} lines (line {cell.line_number})")
        return

    if args.cell and (args.cell < 1 or args.cell > code_count):
        print(f"Error: --cell {args.cell} out of range (notebook has {code_count} code cells).", file=sys.stderr)
        sys.exit(1)

    # Execute
    os.chdir(os.path.dirname(os.path.abspath(args.notebook)) or '.')
    cells, stats = execute_notebook(cells, only_cell=args.cell)

    # Render
    if not args.quiet:
        render_terminal(cells, stats, show_stats=args.stats)

    if args.html:
        title = os.path.splitext(os.path.basename(args.notebook))[0]
        html_content = render_html(cells, stats, title=title)
        with open(args.html, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"\nExported to: {args.html}")

    # Exit with error code if any cells failed
    if stats['errors'] > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
