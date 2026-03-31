#!/usr/bin/env python3
"""
sauravshare.py — Export sauravcode (.srv) programs as shareable HTML pages.

Creates a self-contained HTML file with syntax-highlighted code,
copy-to-clipboard, optional captured output, and file metadata.
Perfect for sharing code snippets in blogs, emails, or documentation.

Usage:
    python sauravshare.py hello.srv                      # Create hello.html
    python sauravshare.py hello.srv -o share.html        # Custom output name
    python sauravshare.py hello.srv --run                 # Capture & embed output
    python sauravshare.py hello.srv --dark                # Dark theme
    python sauravshare.py hello.srv --title "My Program"  # Custom title
    python sauravshare.py *.srv --outdir shared/          # Batch export
"""

import argparse
import html
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ── Token patterns (from sauravhl.py) ─────────────────────────────────

TOKEN_SPEC = [
    ('COMMENT',  r'#.*'),
    ('NUMBER',   r'\d+(\.\d*)?'),
    ('FSTRING',  r'f\"(?:[^\"\\]|\\.)*\"'),
    ('STRING',   r'\"(?:[^\"\\]|\\.)*\"'),
    ('EQ',       r'=='),
    ('NEQ',      r'!='),
    ('LTE',      r'<='),
    ('GTE',      r'>='),
    ('ARROW',    r'->'),
    ('PIPE',     r'\|>'),
    ('OP',       r'[+\-*/%<>=!]'),
    ('PUNC',     r'[()[\]{},:|]'),
    ('KEYWORD',  r'\b(?:if|else|elif|while|for|in|func|return|class|new|'
                 r'import|from|try|catch|finally|throw|match|case|default|'
                 r'break|continue|and|or|not|true|false|none|enum|yield|'
                 r'foreach|lambda|async|await|print|assert|del)\b'),
    ('IDENT',    r'[A-Za-z_]\w*'),
    ('WS',       r'[ \t]+'),
    ('NEWLINE',  r'\n'),
    ('OTHER',    r'.'),
]

_TOKEN_RE = re.compile('|'.join(f'(?P<{n}>{p})' for n, p in TOKEN_SPEC))

# ── Tokenizer ─────────────────────────────────────────────────────────

def tokenize(source):
    """Yield (token_type, value) pairs."""
    for m in _TOKEN_RE.finditer(source):
        kind = m.lastgroup
        yield kind, m.group()

# ── HTML highlight ────────────────────────────────────────────────────

_LIGHT_COLORS = {
    'COMMENT': '#6a737d', 'STRING': '#032f62', 'FSTRING': '#032f62',
    'NUMBER': '#005cc5', 'KEYWORD': '#d73a49', 'IDENT': '#24292e',
    'OP': '#d73a49', 'PUNC': '#24292e',
}

_DARK_COLORS = {
    'COMMENT': '#6a9955', 'STRING': '#ce9178', 'FSTRING': '#ce9178',
    'NUMBER': '#b5cea8', 'KEYWORD': '#569cd6', 'IDENT': '#d4d4d4',
    'OP': '#d4d4d4', 'PUNC': '#d4d4d4',
}


def highlight_html(source, dark=False):
    """Return syntax-highlighted HTML spans for sauravcode source."""
    colors = _DARK_COLORS if dark else _LIGHT_COLORS
    parts = []
    for kind, val in tokenize(source):
        escaped = html.escape(val)
        if kind in ('WS', 'NEWLINE', 'OTHER'):
            parts.append(escaped)
        else:
            color = colors.get(kind, colors['IDENT'])
            parts.append(f'<span style="color:{color}">{escaped}</span>')
    return ''.join(parts)

# ── Run & capture ─────────────────────────────────────────────────────

def capture_output(srv_path, timeout=10):
    """Run a .srv file and return (stdout, stderr, returncode)."""
    interp = Path(__file__).parent / 'saurav.py'
    try:
        r = subprocess.run(
            [sys.executable, str(interp), str(srv_path)],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(Path(srv_path).parent),
        )
        return r.stdout, r.stderr, r.returncode
    except subprocess.TimeoutExpired:
        return '', '(timed out after {}s)'.format(timeout), 1
    except Exception as e:
        return '', str(e), 1

# ── HTML template ─────────────────────────────────────────────────────

def build_html(filename, source, dark=False, title=None, output=None,
               stderr=None, returncode=None):
    """Build a complete self-contained HTML page."""
    title = title or filename
    highlighted = highlight_html(source, dark=dark)
    bg = '#1e1e1e' if dark else '#ffffff'
    fg = '#d4d4d4' if dark else '#24292e'
    code_bg = '#282c34' if dark else '#f6f8fa'
    border = '#444' if dark else '#e1e4e8'
    btn_bg = '#0366d6' if dark else '#0366d6'
    meta_color = '#888' if dark else '#586069'
    line_count = source.count('\n') + 1
    char_count = len(source)
    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    output_section = ''
    if output is not None:
        out_bg = '#1a1a2e' if dark else '#f0f4f8'
        out_fg = '#a9dc76' if dark else '#22863a'
        err_fg = '#ff6b6b' if dark else '#cb2431'
        out_html = html.escape(output) if output else '<em>(no output)</em>'
        err_html = ''
        if stderr and stderr.strip():
            err_html = f'<pre style="color:{err_fg};margin:4px 0 0 0;font-size:13px">{html.escape(stderr.strip())}</pre>'
        rc_badge = ''
        if returncode and returncode != 0:
            rc_badge = f' <span style="color:{err_fg};font-size:12px">(exit code {returncode})</span>'
        output_section = f'''
    <div style="margin-top:16px">
      <div style="font-weight:600;font-size:14px;color:{fg};margin-bottom:6px">
        ▶ Output{rc_badge}
      </div>
      <div style="background:{out_bg};border:1px solid {border};border-radius:6px;padding:12px;overflow-x:auto">
        <pre style="margin:0;font-family:'Fira Code',Consolas,monospace;font-size:13px;color:{out_fg}">{out_html}</pre>
        {err_html}
      </div>
    </div>'''

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} - sauravcode</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
         background:{bg}; color:{fg}; padding:24px; line-height:1.5; }}
  .container {{ max-width:800px; margin:0 auto; }}
  .header {{ display:flex; align-items:center; justify-content:space-between;
             margin-bottom:16px; flex-wrap:wrap; gap:8px; }}
  .header h1 {{ font-size:20px; font-weight:600; }}
  .badge {{ display:inline-block; background:#6f42c1; color:#fff;
            font-size:11px; padding:2px 8px; border-radius:12px; font-weight:500; }}
  .meta {{ font-size:12px; color:{meta_color}; margin-bottom:12px; }}
  .code-box {{ position:relative; background:{code_bg}; border:1px solid {border};
               border-radius:6px; overflow:hidden; }}
  .code-box pre {{ margin:0; padding:16px; overflow-x:auto;
                   font-family:'Fira Code',Consolas,monospace; font-size:13px;
                   line-height:1.6; white-space:pre; }}
  .copy-btn {{ position:absolute; top:8px; right:8px; background:{btn_bg}; color:#fff;
               border:none; border-radius:4px; padding:4px 12px; font-size:12px;
               cursor:pointer; opacity:0.85; transition:opacity .2s; }}
  .copy-btn:hover {{ opacity:1; }}
  .footer {{ margin-top:20px; font-size:11px; color:{meta_color};
             border-top:1px solid {border}; padding-top:12px; text-align:center; }}
  .footer a {{ color:{btn_bg}; text-decoration:none; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>{html.escape(title)}</h1>
    <span class="badge">.srv</span>
  </div>
  <div class="meta">{line_count} lines · {char_count} chars · exported {now}</div>
  <div class="code-box">
    <button class="copy-btn" onclick="copyCode()">Copy</button>
    <pre><code id="src">{highlighted}</code></pre>
  </div>
  {output_section}
  <div class="footer">
    Generated by <a href="https://github.com/sauravbhattacharya001/sauravcode">sauravcode</a> · sauravshare
  </div>
</div>
<script>
function copyCode() {{
  const src = document.getElementById('src').textContent;
  navigator.clipboard.writeText(src).then(() => {{
    const btn = document.querySelector('.copy-btn');
    btn.textContent = 'Copied!';
    setTimeout(() => btn.textContent = 'Copy', 1500);
  }});
}}
</script>
</body>
</html>'''

# ── CLI ───────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description='Export sauravcode (.srv) files as shareable HTML pages.')
    ap.add_argument('files', nargs='+', help='.srv file(s) to export')
    ap.add_argument('-o', '--output', help='Output HTML file (single-file mode)')
    ap.add_argument('--outdir', help='Output directory (batch mode)')
    ap.add_argument('--run', action='store_true',
                    help='Run the program and embed its output')
    ap.add_argument('--dark', action='store_true', help='Use dark theme')
    ap.add_argument('--title', help='Custom page title')
    ap.add_argument('--timeout', type=int, default=10,
                    help='Run timeout in seconds (default: 10)')
    args = ap.parse_args()

    paths = []
    for f in args.files:
        p = Path(f)
        if p.is_dir():
            paths.extend(p.rglob('*.srv'))
        else:
            paths.append(p)

    if not paths:
        print('No .srv files found.', file=sys.stderr)
        sys.exit(1)

    if args.output and len(paths) > 1:
        print('-o/--output only works with a single file. Use --outdir for batch.',
              file=sys.stderr)
        sys.exit(1)

    outdir = Path(args.outdir) if args.outdir else None
    if outdir:
        outdir.mkdir(parents=True, exist_ok=True)

    for p in paths:
        if not p.exists():
            print(f'File not found: {p}', file=sys.stderr)
            continue
        source = p.read_text(encoding='utf-8', errors='replace')
        output = stderr = returncode = None
        if args.run:
            output, stderr, returncode = capture_output(p, timeout=args.timeout)

        page = build_html(
            filename=p.name, source=source, dark=args.dark,
            title=args.title or p.stem,
            output=output, stderr=stderr, returncode=returncode,
        )

        if args.output:
            dest = Path(args.output)
        elif outdir:
            dest = outdir / (p.stem + '.html')
        else:
            dest = p.with_suffix('.html')

        dest.write_text(page, encoding='utf-8')
        print(f'  {p.name} -> {dest} (done)')


if __name__ == '__main__':
    main()
