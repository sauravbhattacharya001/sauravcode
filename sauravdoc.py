#!/usr/bin/env python3
"""
sauravdoc — Documentation generator for sauravcode (.srv) files.

Parses .srv source files and extracts functions, enums, variables,
and their associated comments to generate Markdown documentation.

Usage:
    python sauravdoc.py file.srv                  # Print docs to stdout
    python sauravdoc.py file.srv -o docs.md       # Write to file
    python sauravdoc.py src/ -o docs/             # Document entire directory
    python sauravdoc.py file.srv --format html    # HTML output
    python sauravdoc.py file.srv --toc            # Include table of contents
    python sauravdoc.py file.srv --private        # Include private (_prefixed) items
    python sauravdoc.py file.srv --stats          # Show code statistics
"""

import re
import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime


# ─── Source Parsing ──────────────────────────────────────────────────────────

class DocItem:
    """Represents a documentable item extracted from source code."""

    def __init__(self, kind, name, line_number, params=None, comment=None,
                 body_lines=None, decorators=None, return_comment=None):
        self.kind = kind              # 'function', 'enum', 'variable', 'import', 'section'
        self.name = name
        self.line_number = line_number
        self.params = params or []
        self.comment = comment or ''  # Leading comment block
        self.body_lines = body_lines or []
        self.decorators = decorators or []
        self.return_comment = return_comment or ''

    def is_private(self):
        return self.name.startswith('_')

    def __repr__(self):
        return f"DocItem({self.kind}, {self.name}, line={self.line_number})"


class SourceParser:
    """Parse a .srv file and extract documentable items."""

    def __init__(self, source, filename='<unknown>'):
        self.source = source
        self.filename = filename
        self.lines = source.split('\n')
        self.items = []
        self.module_comment = ''
        self._parse()

    def _parse(self):
        """Extract all documentable items from source."""
        self._extract_module_comment()
        self._extract_functions()
        self._extract_enums()
        self._extract_variables()
        self._extract_imports()
        self._extract_sections()
        # Sort by line number
        self.items.sort(key=lambda item: item.line_number)

    def _extract_module_comment(self):
        """Extract leading comment block as module docstring."""
        lines = []
        for line in self.lines:
            stripped = line.strip()
            if stripped.startswith('#'):
                # Strip the # and optional space
                text = stripped[1:].strip() if len(stripped) > 1 else ''
                # Skip decorative lines like "# ===="
                if text and all(c in '=-~*' for c in text):
                    continue
                lines.append(text)
            elif stripped == '':
                if lines:
                    break  # End of leading comment block
            else:
                break
        self.module_comment = '\n'.join(lines).strip()

    def _get_leading_comment(self, line_idx):
        """Get the comment block immediately preceding a line."""
        comments = []
        i = line_idx - 1
        while i >= 0:
            stripped = self.lines[i].strip()
            if stripped.startswith('#'):
                text = stripped[1:].strip() if len(stripped) > 1 else ''
                # Skip decorative lines
                if text and all(c in '=-~*' for c in text):
                    i -= 1
                    continue
                comments.insert(0, text)
            elif stripped == '':
                if comments:
                    break
                # Allow one blank line gap
                i -= 1
                continue
            else:
                break
            i -= 1
        return '\n'.join(comments).strip()

    def _extract_functions(self):
        """Extract function definitions with parameters and comments."""
        func_re = re.compile(r'^function\s+(\w+)(.*)')
        decorator_re = re.compile(r'^@(\w+)(?:\s+(.*))?$')

        pending_decorators = []
        for i, line in enumerate(self.lines):
            stripped = line.strip()

            # Collect decorators
            dec_match = decorator_re.match(stripped)
            if dec_match:
                pending_decorators.append(dec_match.group(1))
                continue

            match = func_re.match(stripped)
            if match:
                name = match.group(1)
                param_str = match.group(2).strip()
                params = param_str.split() if param_str else []
                comment = self._get_leading_comment(i - len(pending_decorators))

                # Extract body lines
                body_lines = self._extract_body(i + 1)

                # Look for return comment in body
                return_comment = ''
                for bline in body_lines:
                    bstripped = bline.strip()
                    if bstripped.startswith('return') and '#' in bstripped:
                        return_comment = bstripped.split('#', 1)[1].strip()
                        break

                item = DocItem(
                    kind='function',
                    name=name,
                    line_number=i + 1,
                    params=params,
                    comment=comment,
                    body_lines=body_lines,
                    decorators=pending_decorators[:],
                    return_comment=return_comment,
                )
                self.items.append(item)
                pending_decorators.clear()
            elif not dec_match and stripped and not stripped.startswith('#'):
                pending_decorators.clear()

    def _extract_body(self, start_idx):
        """Extract indented body lines starting from start_idx."""
        body = []
        if start_idx >= len(self.lines):
            return body
        # Determine the indentation level of the first body line
        first_line = self.lines[start_idx] if start_idx < len(self.lines) else ''
        indent = len(first_line) - len(first_line.lstrip())
        if indent == 0 and first_line.strip():
            return body

        for i in range(start_idx, len(self.lines)):
            line = self.lines[i]
            if line.strip() == '':
                body.append(line)
                continue
            current_indent = len(line) - len(line.lstrip())
            if current_indent >= indent and indent > 0:
                body.append(line)
            else:
                break
        # Trim trailing empty lines
        while body and body[-1].strip() == '':
            body.pop()
        return body

    def _extract_enums(self):
        """Extract enum definitions."""
        enum_re = re.compile(r'^enum\s+(\w+)')
        for i, line in enumerate(self.lines):
            match = enum_re.match(line.strip())
            if match:
                name = match.group(1)
                comment = self._get_leading_comment(i)
                body_lines = self._extract_body(i + 1)

                # Extract variants from body
                variants = []
                for bline in body_lines:
                    bstripped = bline.strip()
                    if bstripped and not bstripped.startswith('#'):
                        variants.append(bstripped)

                item = DocItem(
                    kind='enum',
                    name=name,
                    line_number=i + 1,
                    params=variants,  # Reuse params for variants
                    comment=comment,
                    body_lines=body_lines,
                )
                self.items.append(item)

    def _extract_variables(self):
        """Extract top-level variable assignments."""
        assign_re = re.compile(r'^(\w+)\s*=\s*(.+)')
        # Skip variables inside functions/enums (indented)
        for i, line in enumerate(self.lines):
            if line and not line[0].isspace():
                match = assign_re.match(line.strip())
                if match:
                    name = match.group(1)
                    value = match.group(2).strip()
                    # Skip if it's a keyword line
                    if name in ('function', 'enum', 'if', 'else', 'for', 'while',
                                'try', 'catch', 'import', 'match', 'class', 'return'):
                        continue
                    comment = self._get_leading_comment(i)
                    item = DocItem(
                        kind='variable',
                        name=name,
                        line_number=i + 1,
                        params=[value],  # Store value in params
                        comment=comment,
                    )
                    self.items.append(item)

    def _extract_imports(self):
        """Extract import statements."""
        import_re = re.compile(r'^import\s+(.+)')
        for i, line in enumerate(self.lines):
            match = import_re.match(line.strip())
            if match:
                module_name = match.group(1).strip()
                comment = self._get_leading_comment(i)
                item = DocItem(
                    kind='import',
                    name=module_name,
                    line_number=i + 1,
                    comment=comment,
                )
                self.items.append(item)

    def _extract_sections(self):
        """Extract section markers from decorative comments like # --- Title ---."""
        section_re = re.compile(r'^#\s*[-=~]{3,}\s*(.+?)\s*[-=~]*\s*$')
        for i, line in enumerate(self.lines):
            match = section_re.match(line.strip())
            if match:
                title = match.group(1).strip()
                if title and not all(c in '=-~*' for c in title):
                    item = DocItem(
                        kind='section',
                        name=title,
                        line_number=i + 1,
                    )
                    self.items.append(item)

    def get_stats(self):
        """Return code statistics."""
        total_lines = len(self.lines)
        blank_lines = sum(1 for l in self.lines if l.strip() == '')
        comment_lines = sum(1 for l in self.lines if l.strip().startswith('#'))
        code_lines = total_lines - blank_lines - comment_lines
        functions = [i for i in self.items if i.kind == 'function']
        enums = [i for i in self.items if i.kind == 'enum']
        variables = [i for i in self.items if i.kind == 'variable']
        imports = [i for i in self.items if i.kind == 'import']

        # Average function length
        avg_func_len = 0
        if functions:
            avg_func_len = sum(len(f.body_lines) for f in functions) / len(functions)

        # Documented ratio
        documentable = functions + enums
        documented = [i for i in documentable if i.comment]
        doc_ratio = len(documented) / len(documentable) if documentable else 1.0

        return {
            'total_lines': total_lines,
            'code_lines': code_lines,
            'blank_lines': blank_lines,
            'comment_lines': comment_lines,
            'functions': len(functions),
            'enums': len(enums),
            'variables': len(variables),
            'imports': len(imports),
            'avg_function_length': round(avg_func_len, 1),
            'documentation_ratio': round(doc_ratio * 100, 1),
            'comment_ratio': round(comment_lines / total_lines * 100, 1) if total_lines else 0,
        }


# ─── Markdown Generator ─────────────────────────────────────────────────────

class MarkdownGenerator:
    """Generate Markdown documentation from parsed source."""

    def __init__(self, parser, include_private=False, include_toc=True,
                 include_stats=False, include_source=False):
        self.parser = parser
        self.include_private = include_private
        self.include_toc = include_toc
        self.include_stats = include_stats
        self.include_source = include_source

    def generate(self):
        """Generate complete Markdown documentation."""
        parts = []

        # Title
        filename = Path(self.parser.filename).stem
        parts.append(f'# {filename}\n')

        # Module description
        if self.parser.module_comment:
            parts.append(f'{self.parser.module_comment}\n')

        # File info
        parts.append(f'> Source: `{self.parser.filename}`\n')

        # Stats
        if self.include_stats:
            parts.append(self._render_stats())

        # Filter items
        items = self.parser.items
        if not self.include_private:
            items = [i for i in items if not i.is_private()]

        # Collect by kind
        functions = [i for i in items if i.kind == 'function']
        enums = [i for i in items if i.kind == 'enum']
        variables = [i for i in items if i.kind == 'variable']
        imports = [i for i in items if i.kind == 'import']

        # Table of contents
        if self.include_toc and (functions or enums):
            parts.append(self._render_toc(functions, enums, variables))

        # Imports
        if imports:
            parts.append('## Imports\n')
            for item in imports:
                parts.append(f'- `import {item.name}`')
                if item.comment:
                    parts.append(f'  — {item.comment}')
                parts.append('')
            parts.append('')

        # Enums
        if enums:
            parts.append('## Enums\n')
            for item in enums:
                parts.append(self._render_enum(item))

        # Functions
        if functions:
            parts.append('## Functions\n')
            for item in functions:
                parts.append(self._render_function(item))

        # Variables
        if variables:
            parts.append('## Variables\n')
            for item in variables:
                parts.append(self._render_variable(item))

        # Footer
        parts.append('---')
        parts.append(f'*Generated by sauravdoc on {datetime.now().strftime("%Y-%m-%d %H:%M")}*\n')

        return '\n'.join(parts)

    def _render_toc(self, functions, enums, variables):
        """Render table of contents."""
        lines = ['## Table of Contents\n']

        if enums:
            lines.append('### Enums')
            for item in enums:
                anchor = item.name.lower().replace(' ', '-')
                lines.append(f'- [`{item.name}`](#{anchor})')
            lines.append('')

        if functions:
            lines.append('### Functions')
            for item in functions:
                anchor = item.name.lower().replace(' ', '-')
                params = ' '.join(item.params)
                sig = f'{item.name} {params}'.strip()
                lines.append(f'- [`{sig}`](#{anchor})')
            lines.append('')

        return '\n'.join(lines)

    def _render_function(self, item):
        """Render a single function's documentation."""
        lines = []
        # Heading
        params = ' '.join(item.params)
        signature = f'{item.name} {params}'.strip()
        lines.append(f'### `{signature}`\n')

        # Decorators
        if item.decorators:
            dec_str = ' '.join(f'@{d}' for d in item.decorators)
            lines.append(f'**Decorators:** {dec_str}\n')

        # Line reference
        lines.append(f'*Defined at line {item.line_number}*\n')

        # Description
        if item.comment:
            lines.append(f'{item.comment}\n')

        # Parameters
        if item.params:
            lines.append('**Parameters:**\n')
            for p in item.params:
                # Check if the comment mentions the parameter
                param_desc = self._find_param_desc(p, item.comment)
                if param_desc:
                    lines.append(f'- `{p}` — {param_desc}')
                else:
                    lines.append(f'- `{p}`')
            lines.append('')

        # Return info
        if item.return_comment:
            lines.append(f'**Returns:** {item.return_comment}\n')

        # Source code
        if self.include_source and item.body_lines:
            lines.append('<details>')
            lines.append('<summary>Source</summary>\n')
            lines.append('```')
            lines.append(f'function {signature}')
            for bline in item.body_lines:
                lines.append(bline)
            lines.append('```\n')
            lines.append('</details>\n')

        return '\n'.join(lines)

    def _render_enum(self, item):
        """Render an enum's documentation."""
        lines = []
        lines.append(f'### `{item.name}`\n')
        lines.append(f'*Defined at line {item.line_number}*\n')

        if item.comment:
            lines.append(f'{item.comment}\n')

        if item.params:  # variants
            lines.append('**Variants:**\n')
            for v in item.params:
                lines.append(f'- `{v}`')
            lines.append('')

        return '\n'.join(lines)

    def _render_variable(self, item):
        """Render a variable's documentation."""
        lines = []
        value = item.params[0] if item.params else '?'
        lines.append(f'- **`{item.name}`** = `{value}` *(line {item.line_number})*')
        if item.comment:
            lines.append(f'  {item.comment}')
        lines.append('')
        return '\n'.join(lines)

    def _render_stats(self):
        """Render code statistics."""
        stats = self.parser.get_stats()
        lines = ['## Statistics\n']
        lines.append(f'| Metric | Value |')
        lines.append(f'| ------ | ----- |')
        lines.append(f'| Total lines | {stats["total_lines"]} |')
        lines.append(f'| Code lines | {stats["code_lines"]} |')
        lines.append(f'| Comment lines | {stats["comment_lines"]} ({stats["comment_ratio"]}%) |')
        lines.append(f'| Blank lines | {stats["blank_lines"]} |')
        lines.append(f'| Functions | {stats["functions"]} |')
        lines.append(f'| Enums | {stats["enums"]} |')
        lines.append(f'| Variables | {stats["variables"]} |')
        lines.append(f'| Imports | {stats["imports"]} |')
        lines.append(f'| Avg function length | {stats["avg_function_length"]} lines |')
        lines.append(f'| Documentation coverage | {stats["documentation_ratio"]}% |')
        lines.append('')
        return '\n'.join(lines)

    def _find_param_desc(self, param_name, comment):
        """Try to find a parameter description in the comment text."""
        if not comment:
            return ''
        # Look for patterns like "param_name: description" or "param_name - description"
        patterns = [
            rf'\b{re.escape(param_name)}\s*[:\-—]\s*(.+)',
            rf'\b{re.escape(param_name)}\s+is\s+(.+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, comment, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return ''


# ─── HTML Generator ──────────────────────────────────────────────────────────

class HtmlGenerator:
    """Generate HTML documentation from parsed source."""

    def __init__(self, parser, include_private=False, include_stats=False):
        self.parser = parser
        self.include_private = include_private
        self.include_stats = include_stats

    def generate(self):
        """Generate complete HTML documentation."""
        filename = Path(self.parser.filename).stem
        md_gen = MarkdownGenerator(
            self.parser,
            include_private=self.include_private,
            include_toc=True,
            include_stats=self.include_stats,
        )
        # Simple HTML wrapper with styling
        md_content = md_gen.generate()

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{_html_escape(filename)} — sauravdoc</title>
    <style>
        :root {{
            --bg: #0d1117; --fg: #c9d1d9; --accent: #58a6ff;
            --code-bg: #161b22; --border: #30363d; --muted: #8b949e;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            max-width: 900px; margin: 0 auto; padding: 2rem;
            background: var(--bg); color: var(--fg); line-height: 1.6;
        }}
        h1 {{ color: var(--accent); border-bottom: 1px solid var(--border); padding-bottom: 0.3em; }}
        h2 {{ color: var(--accent); margin-top: 2em; }}
        h3 {{ color: var(--fg); }}
        code, pre {{
            background: var(--code-bg); border-radius: 6px;
            font-family: 'JetBrains Mono', 'Fira Code', monospace;
        }}
        code {{ padding: 0.2em 0.4em; font-size: 0.9em; }}
        pre {{ padding: 1em; overflow-x: auto; border: 1px solid var(--border); }}
        blockquote {{
            border-left: 3px solid var(--accent); padding-left: 1em;
            color: var(--muted); margin: 1em 0;
        }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid var(--border); padding: 0.5em 1em; text-align: left; }}
        th {{ background: var(--code-bg); }}
        a {{ color: var(--accent); text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        em {{ color: var(--muted); }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 1em; }}
        .stat-card {{ background: var(--code-bg); border: 1px solid var(--border); border-radius: 8px; padding: 1em; }}
        .stat-value {{ font-size: 1.5em; font-weight: bold; color: var(--accent); }}
        .stat-label {{ color: var(--muted); font-size: 0.9em; }}
    </style>
</head>
<body>
<pre>{_html_escape(md_content)}</pre>
</body>
</html>"""
        return html


def _html_escape(text):
    """Basic HTML escaping."""
    return (text
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;'))


# ─── JSON Generator ──────────────────────────────────────────────────────────

class JsonGenerator:
    """Generate JSON documentation from parsed source."""

    def __init__(self, parser, include_private=False):
        self.parser = parser
        self.include_private = include_private

    def generate(self):
        """Generate JSON documentation."""
        items = self.parser.items
        if not self.include_private:
            items = [i for i in items if not i.is_private()]

        data = {
            'file': self.parser.filename,
            'module_comment': self.parser.module_comment,
            'stats': self.parser.get_stats(),
            'items': [],
        }

        for item in items:
            entry = {
                'kind': item.kind,
                'name': item.name,
                'line': item.line_number,
                'comment': item.comment,
            }
            if item.kind == 'function':
                entry['params'] = item.params
                entry['decorators'] = item.decorators
                entry['return_comment'] = item.return_comment
            elif item.kind == 'enum':
                entry['variants'] = item.params
            elif item.kind == 'variable':
                entry['value'] = item.params[0] if item.params else None
            data['items'].append(entry)

        return json.dumps(data, indent=2)


# ─── Multi-File Documentation ───────────────────────────────────────────────

def document_directory(dir_path, output_dir=None, format='markdown', **kwargs):
    """Generate documentation for all .srv files in a directory."""
    dir_path = Path(dir_path)
    srv_files = sorted(dir_path.rglob('*.srv'))

    if not srv_files:
        print(f"No .srv files found in {dir_path}", file=sys.stderr)
        return

    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for srv_file in srv_files:
        rel_path = srv_file.relative_to(dir_path)
        source = srv_file.read_text(encoding='utf-8', errors='replace')
        parser = SourceParser(source, str(rel_path))

        if format == 'json':
            gen = JsonGenerator(parser, **kwargs)
            ext = '.json'
        elif format == 'html':
            gen = HtmlGenerator(parser, **kwargs)
            ext = '.html'
        else:
            gen = MarkdownGenerator(parser, include_toc=True,
                                     include_stats=kwargs.get('include_stats', False),
                                     include_private=kwargs.get('include_private', False),
                                     include_source=kwargs.get('include_source', False))
            ext = '.md'

        doc = gen.generate()

        if output_dir:
            out_file = output_dir / (rel_path.stem + ext)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(doc, encoding='utf-8')
            print(f"  ✓ {rel_path} → {out_file}")
        else:
            results.append(doc)

    if not output_dir and results:
        print('\n\n---\n\n'.join(results))

    # Generate index if output_dir
    if output_dir and format == 'markdown':
        _generate_index(srv_files, dir_path, output_dir)


def _generate_index(srv_files, src_dir, output_dir):
    """Generate an index.md linking all documented files."""
    lines = ['# Documentation Index\n']
    lines.append(f'Generated from `{src_dir}`\n')

    total_functions = 0
    total_enums = 0

    for srv_file in srv_files:
        rel_path = srv_file.relative_to(src_dir)
        source = srv_file.read_text(encoding='utf-8', errors='replace')
        parser = SourceParser(source, str(rel_path))
        stats = parser.get_stats()

        doc_link = rel_path.stem + '.md'
        lines.append(f'- [{rel_path}]({doc_link})')
        lines.append(f'  — {stats["functions"]} functions, {stats["enums"]} enums, '
                      f'{stats["code_lines"]} code lines')
        total_functions += stats['functions']
        total_enums += stats['enums']

    lines.append(f'\n**Total:** {len(srv_files)} files, '
                  f'{total_functions} functions, {total_enums} enums\n')
    lines.append('---')
    lines.append(f'*Generated by sauravdoc on {datetime.now().strftime("%Y-%m-%d %H:%M")}*\n')

    index_path = output_dir / 'index.md'
    index_path.write_text('\n'.join(lines), encoding='utf-8')
    print(f"  ✓ Index → {index_path}")


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    argparser = argparse.ArgumentParser(
        prog='sauravdoc',
        description='Documentation generator for sauravcode (.srv) files.',
        epilog='Examples:\n'
               '  sauravdoc hello.srv\n'
               '  sauravdoc hello.srv -o docs.md\n'
               '  sauravdoc src/ -o docs/ --stats\n'
               '  sauravdoc hello.srv --format json\n',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    argparser.add_argument('input', help='Input .srv file or directory')
    argparser.add_argument('-o', '--output', help='Output file or directory')
    argparser.add_argument('--format', choices=['markdown', 'html', 'json'],
                           default='markdown', help='Output format (default: markdown)')
    argparser.add_argument('--toc', action='store_true', default=True,
                           help='Include table of contents (default)')
    argparser.add_argument('--no-toc', action='store_true',
                           help='Exclude table of contents')
    argparser.add_argument('--private', action='store_true',
                           help='Include private (_prefixed) items')
    argparser.add_argument('--stats', action='store_true',
                           help='Include code statistics')
    argparser.add_argument('--source', action='store_true',
                           help='Include source code in docs')

    args = argparser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: '{args.input}' not found", file=sys.stderr)
        sys.exit(1)

    include_toc = not args.no_toc

    if input_path.is_dir():
        document_directory(
            input_path,
            output_dir=args.output,
            format=args.format,
            include_private=args.private,
            include_stats=args.stats,
            include_source=args.source,
        )
    else:
        # Single file
        source = input_path.read_text(encoding='utf-8', errors='replace')
        parser = SourceParser(source, str(input_path))

        if args.format == 'json':
            gen = JsonGenerator(parser, include_private=args.private)
        elif args.format == 'html':
            gen = HtmlGenerator(parser, include_private=args.private,
                                include_stats=args.stats)
        else:
            gen = MarkdownGenerator(parser, include_private=args.private,
                                     include_toc=include_toc,
                                     include_stats=args.stats,
                                     include_source=args.source)

        doc = gen.generate()

        if args.output:
            out_path = Path(args.output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(doc, encoding='utf-8')
            print(f"Documentation written to {out_path}")
        else:
            print(doc)


if __name__ == '__main__':
    main()
