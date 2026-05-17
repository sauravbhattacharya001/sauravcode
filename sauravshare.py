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

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, Optional, Tuple

# Reuse the shared HTML-escape helper so every sauravcode tool stays in sync.
try:
    from sauravtext import html_escape as _html_escape
except ImportError:  # pragma: no cover — defensive fallback
    import html as _html

    def _html_escape(s: str) -> str:
        return _html.escape(s, quote=True)


# ───────────────────────── Token spec ──────────────────────────────────
#
# Order matters: multi-character operators must precede their single-char
# fallbacks so the alternation matches them first.

TOKEN_SPEC: list[Tuple[str, str]] = [
    ('COMMENT',  r'#.*'),
    ('NUMBER',   r'\d+(\.\d*)?'),
    ('FSTRING',  r'f"(?:[^"\\]|\\.)*"'),
    ('STRING',   r'"(?:[^"\\]|\\.)*"'),
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

# Token kinds that should be emitted as raw text (no <span> wrapper) when
# rendering to HTML. Centralised so the renderer can't fall out of sync
# with the tokenizer.
_RAW_KINDS = frozenset({'WS', 'NEWLINE', 'OTHER'})


# ───────────────────────── Themes ──────────────────────────────────────

@dataclass(frozen=True)
class Theme:
    """A complete colour palette for a rendered share page.

    Grouped here (instead of being scattered through `build_html` as a
    dozen ternary expressions) so adding a new theme — or tweaking an
    existing one — is a single localised edit.
    """
    token: dict[str, str]
    bg: str
    fg: str
    code_bg: str
    border: str
    btn_bg: str
    meta: str
    out_bg: str
    out_fg: str
    err_fg: str


_LIGHT = Theme(
    token={
        'COMMENT': '#6a737d', 'STRING': '#032f62', 'FSTRING': '#032f62',
        'NUMBER': '#005cc5', 'KEYWORD': '#d73a49', 'IDENT': '#24292e',
        'OP': '#d73a49', 'PUNC': '#24292e',
    },
    bg='#ffffff', fg='#24292e', code_bg='#f6f8fa', border='#e1e4e8',
    btn_bg='#0366d6', meta='#586069',
    out_bg='#f0f4f8', out_fg='#22863a', err_fg='#cb2431',
)

_DARK = Theme(
    token={
        'COMMENT': '#6a9955', 'STRING': '#ce9178', 'FSTRING': '#ce9178',
        'NUMBER': '#b5cea8', 'KEYWORD': '#569cd6', 'IDENT': '#d4d4d4',
        'OP': '#d4d4d4', 'PUNC': '#d4d4d4',
    },
    bg='#1e1e1e', fg='#d4d4d4', code_bg='#282c34', border='#444',
    btn_bg='#0366d6', meta='#888',
    out_bg='#1a1a2e', out_fg='#a9dc76', err_fg='#ff6b6b',
)


# Backwards-compatible aliases — kept because external callers and tests
# index into these dictionaries directly.
_LIGHT_COLORS = _LIGHT.token
_DARK_COLORS = _DARK.token


def _theme(dark: bool) -> Theme:
    return _DARK if dark else _LIGHT


# ───────────────────────── Tokenizer ───────────────────────────────────

def tokenize(source: str) -> Iterator[Tuple[str, str]]:
    """Yield ``(token_type, value)`` pairs covering every char in *source*.

    Concatenating every yielded ``value`` reproduces *source* exactly,
    which is what allows :func:`highlight_html` to stream output without
    losing whitespace.
    """
    for m in _TOKEN_RE.finditer(source):
        yield m.lastgroup, m.group()


# ───────────────────────── Highlight ───────────────────────────────────

def _render_token(kind: str, value: str, palette: dict[str, str]) -> str:
    escaped = _html_escape(value)
    if kind in _RAW_KINDS:
        return escaped
    color = palette.get(kind, palette['IDENT'])
    return f'<span style="color:{color}">{escaped}</span>'


def highlight_html(source: str, dark: bool = False) -> str:
    """Return syntax-highlighted HTML for sauravcode *source*."""
    palette = _theme(dark).token
    return ''.join(_render_token(k, v, palette) for k, v in tokenize(source))


# ───────────────────────── Run & capture ───────────────────────────────

def capture_output(srv_path, timeout: int = 10) -> Tuple[str, str, int]:
    """Run a .srv file and return ``(stdout, stderr, returncode)``."""
    interp = Path(__file__).parent / 'saurav.py'
    try:
        r = subprocess.run(
            [sys.executable, str(interp), str(srv_path)],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(Path(srv_path).parent),
        )
        return r.stdout, r.stderr, r.returncode
    except subprocess.TimeoutExpired:
        return '', f'(timed out after {timeout}s)', 1
    except Exception as e:  # noqa: BLE001 — surfaced to the user as stderr
        return '', str(e), 1


# ───────────────────────── HTML rendering ──────────────────────────────

def _render_output_section(
    theme: Theme,
    output: Optional[str],
    stderr: Optional[str],
    returncode: Optional[int],
) -> str:
    """Render the ``▶ Output`` block (or empty string when there is none)."""
    if output is None:
        return ''

    out_html = _html_escape(output) if output else '<em>(no output)</em>'

    err_html = ''
    if stderr and stderr.strip():
        err_html = (
            f'<pre style="color:{theme.err_fg};margin:4px 0 0 0;font-size:13px">'
            f'{_html_escape(stderr.strip())}</pre>'
        )

    rc_badge = ''
    if returncode and returncode != 0:
        rc_badge = (
            f' <span style="color:{theme.err_fg};font-size:12px">'
            f'(exit code {returncode})</span>'
        )

    return f'''
    <div style="margin-top:16px">
      <div style="font-weight:600;font-size:14px;color:{theme.fg};margin-bottom:6px">
        ▶ Output{rc_badge}
      </div>
      <div style="background:{theme.out_bg};border:1px solid {theme.border};border-radius:6px;padding:12px;overflow-x:auto">
        <pre style="margin:0;font-family:'Fira Code',Consolas,monospace;font-size:13px;color:{theme.out_fg}">{out_html}</pre>
        {err_html}
      </div>
    </div>'''


def _page_styles(theme: Theme) -> str:
    """The ``<style>`` block. Pure function of the theme."""
    t = theme
    return f'''<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
         background:{t.bg}; color:{t.fg}; padding:24px; line-height:1.5; }}
  .container {{ max-width:800px; margin:0 auto; }}
  .header {{ display:flex; align-items:center; justify-content:space-between;
             margin-bottom:16px; flex-wrap:wrap; gap:8px; }}
  .header h1 {{ font-size:20px; font-weight:600; }}
  .badge {{ display:inline-block; background:#6f42c1; color:#fff;
            font-size:11px; padding:2px 8px; border-radius:12px; font-weight:500; }}
  .meta {{ font-size:12px; color:{t.meta}; margin-bottom:12px; }}
  .code-box {{ position:relative; background:{t.code_bg}; border:1px solid {t.border};
               border-radius:6px; overflow:hidden; }}
  .code-box pre {{ margin:0; padding:16px; overflow-x:auto;
                   font-family:'Fira Code',Consolas,monospace; font-size:13px;
                   line-height:1.6; white-space:pre; }}
  .copy-btn {{ position:absolute; top:8px; right:8px; background:{t.btn_bg}; color:#fff;
               border:none; border-radius:4px; padding:4px 12px; font-size:12px;
               cursor:pointer; opacity:0.85; transition:opacity .2s; }}
  .copy-btn:hover {{ opacity:1; }}
  .footer {{ margin-top:20px; font-size:11px; color:{t.meta};
             border-top:1px solid {t.border}; padding-top:12px; text-align:center; }}
  .footer a {{ color:{t.btn_bg}; text-decoration:none; }}
</style>'''


_COPY_SCRIPT = '''<script>
function copyCode() {
  const src = document.getElementById('src').textContent;
  navigator.clipboard.writeText(src).then(() => {
    const btn = document.querySelector('.copy-btn');
    btn.textContent = 'Copied!';
    setTimeout(() => btn.textContent = 'Copy', 1500);
  });
}
</script>'''


def build_html(
    filename: str,
    source: str,
    dark: bool = False,
    title: Optional[str] = None,
    output: Optional[str] = None,
    stderr: Optional[str] = None,
    returncode: Optional[int] = None,
) -> str:
    """Build a complete, self-contained HTML share page.

    The implementation delegates to a small set of pure helpers:

      * :func:`_theme` picks light vs dark colours.
      * :func:`highlight_html` syntax-highlights the source.
      * :func:`_render_output_section` builds the optional output block.
      * :func:`_page_styles` produces the ``<style>`` chunk.

    This makes each piece independently testable and removes the giant
    ternary-soup that used to live inline.
    """
    title = title or filename
    theme = _theme(dark)
    safe_title = _html_escape(title)
    highlighted = highlight_html(source, dark=dark)
    line_count = source.count('\n') + 1
    char_count = len(source)
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    styles = _page_styles(theme)
    output_section = _render_output_section(theme, output, stderr, returncode)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{safe_title} - sauravcode</title>
{styles}
</head>
<body>
<div class="container">
  <div class="header">
    <h1>{safe_title}</h1>
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
{_COPY_SCRIPT}
</body>
</html>'''


# ───────────────────────── CLI ─────────────────────────────────────────

def _collect_paths(args_files: Iterable[str]) -> list[Path]:
    paths: list[Path] = []
    for f in args_files:
        p = Path(f)
        if p.is_dir():
            paths.extend(p.rglob('*.srv'))
        else:
            paths.append(p)
    return paths


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

    paths = _collect_paths(args.files)

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
