"""Tests for sauravshare — the .srv-to-HTML exporter.

Covers:
  * Tokenizer: each TOKEN_SPEC kind, ordering, edge cases (escapes, f-strings).
  * highlight_html: HTML escaping, light/dark theme color application,
    pass-through of whitespace/newlines/unknown chars.
  * build_html: structural assertions (title, badge, line/char counts,
    copy button, output section gating, exit-code badge, stderr block,
    dark vs light backgrounds).
  * capture_output: timeout path, non-existent file path.
  * CLI main(): single-file mode, --outdir batch mode, --output rejection
    when multiple files given, missing files.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sauravshare as ss  # noqa: E402


# ───────────────────────── tokenize ─────────────────────────

def _kinds(src: str) -> list[str]:
    return [k for k, _ in ss.tokenize(src)]


def _toks(src: str) -> list[tuple[str, str]]:
    return list(ss.tokenize(src))


def test_tokenize_keyword_and_ident():
    toks = _toks('if x: print(x)')
    assert ('KEYWORD', 'if') in toks
    assert ('IDENT', 'x') in toks
    assert ('KEYWORD', 'print') in toks
    assert ('PUNC', '(') in toks
    assert ('PUNC', ')') in toks


def test_tokenize_number_int_and_float():
    toks = _toks('42 3.14')
    assert ('NUMBER', '42') in toks
    assert ('NUMBER', '3.14') in toks


def test_tokenize_string_with_escape():
    toks = _toks(r'"hello \"world\""')
    strings = [v for k, v in toks if k == 'STRING']
    assert strings == [r'"hello \"world\""']


def test_tokenize_fstring_distinguished_from_string():
    toks = _toks('f"hi {name}" "plain"')
    kinds_values = [(k, v) for k, v in toks if k in ('STRING', 'FSTRING')]
    # f"..." matches FSTRING; "plain" matches STRING.
    assert ('FSTRING', 'f"hi {name}"') in kinds_values
    assert ('STRING', '"plain"') in kinds_values


def test_tokenize_comment_runs_to_eol_only():
    toks = _toks('x = 1  # a comment\ny = 2')
    comments = [v for k, v in toks if k == 'COMMENT']
    assert comments == ['# a comment']
    # newline is preserved as NEWLINE, and second line still tokenises.
    assert ('NEWLINE', '\n') in toks
    assert ('NUMBER', '2') in toks


def test_tokenize_multi_char_operators_have_priority():
    # ==, !=, <=, >=, ->, |> must beat the single-char OP/PUNC fallbacks.
    toks = _toks('a == b != c <= d >= e -> f |> g')
    kinds = [k for k, _ in toks if k not in ('WS', 'IDENT')]
    assert kinds == ['EQ', 'NEQ', 'LTE', 'GTE', 'ARROW', 'PIPE']


def test_tokenize_unknown_char_falls_through_to_other():
    toks = _toks('§')
    assert ('OTHER', '§') in toks


def test_tokenize_yields_every_character():
    # Total length yielded must equal source length (round-trip property).
    src = 'func add(a, b) -> int { return a + b } # ok\n'
    assert ''.join(v for _, v in ss.tokenize(src)) == src


# ──────────────────────── highlight_html ────────────────────────

def test_highlight_html_escapes_special_chars():
    html_out = ss.highlight_html('x = "<script>" # &')
    # The literal angle brackets and ampersand must be escaped.
    assert '&lt;script&gt;' in html_out
    assert '&amp;' in html_out
    # And no raw "<script>" leaks through.
    assert '<script>' not in html_out


def test_highlight_html_light_vs_dark_use_different_keyword_color():
    light = ss.highlight_html('if x:', dark=False)
    dark = ss.highlight_html('if x:', dark=True)
    assert ss._LIGHT_COLORS['KEYWORD'] in light
    assert ss._DARK_COLORS['KEYWORD'] in dark
    # The two themes must not be identical for any keyword/ident source.
    assert light != dark


def test_highlight_html_whitespace_passthrough():
    out = ss.highlight_html('a b')
    # Whitespace between idents is rendered literally (not wrapped in span).
    assert re.search(r'>a</span> <span', out)


def test_highlight_html_newline_passes_through():
    out = ss.highlight_html('a\nb')
    assert '\n' in out


# ──────────────────────── build_html ────────────────────────

def _has_section(page: str, marker: str) -> bool:
    return marker in page


def test_build_html_no_output_section_when_output_is_none():
    page = ss.build_html('hello.srv', 'print(1)')
    assert '<!DOCTYPE html>' in page
    assert '▶ Output' not in page


def test_build_html_includes_title_and_badge_and_meta():
    page = ss.build_html('hi.srv', 'x = 1\ny = 2\n', title='My Title')
    assert '<title>My Title - sauravcode</title>' in page
    assert '>My Title<' in page
    assert '.srv</span>' in page
    # 3 lines, 12 chars
    assert '3 lines' in page
    assert '12 chars' in page


def test_build_html_title_falls_back_to_filename():
    page = ss.build_html('foo.srv', 'x = 1')
    assert '<title>foo.srv - sauravcode</title>' in page


def test_build_html_escapes_title_with_html_specials():
    page = ss.build_html('<x>.srv', 'a', title='<x>')
    assert '<title>&lt;x&gt; - sauravcode</title>' in page
    # Raw "<x>" must not appear as an element.
    assert '<h1>&lt;x&gt;</h1>' in page or '>&lt;x&gt;<' in page


def test_build_html_dark_theme_uses_dark_background():
    light = ss.build_html('a.srv', 'x', dark=False)
    dark = ss.build_html('a.srv', 'x', dark=True)
    assert 'background:#ffffff' in light
    assert 'background:#1e1e1e' in dark


def test_build_html_output_section_renders_with_empty_output():
    page = ss.build_html('a.srv', 'print(1)', output='', stderr=None, returncode=0)
    assert '▶ Output' in page
    assert '(no output)' in page


def test_build_html_output_section_with_text():
    page = ss.build_html('a.srv', 'print(1)', output='hello world\n', returncode=0)
    assert '▶ Output' in page
    assert 'hello world' in page
    # returncode 0 → no exit code badge
    assert 'exit code' not in page


def test_build_html_nonzero_returncode_shows_exit_code_badge():
    page = ss.build_html('a.srv', 'x', output='oops', stderr='boom', returncode=2)
    assert 'exit code 2' in page
    assert 'boom' in page


def test_build_html_stderr_is_html_escaped():
    page = ss.build_html('a.srv', 'x', output='', stderr='<script>evil</script>', returncode=1)
    assert '&lt;script&gt;evil&lt;/script&gt;' in page
    assert '<script>evil</script>' not in page


def test_build_html_output_is_html_escaped():
    page = ss.build_html('a.srv', 'x', output='<b>&hi</b>', returncode=0)
    assert '&lt;b&gt;&amp;hi&lt;/b&gt;' in page


def test_build_html_contains_copy_button_script():
    page = ss.build_html('a.srv', 'x')
    assert 'copyCode()' in page
    assert 'navigator.clipboard' in page
    assert 'id="src"' in page


# ─────────────────────── capture_output ───────────────────────

def test_capture_output_timeout(tmp_path, monkeypatch):
    # Force subprocess.run to raise TimeoutExpired and check we handle it.
    def _raise_timeout(*a, **kw):
        raise subprocess.TimeoutExpired(cmd='x', timeout=kw.get('timeout', 0))

    monkeypatch.setattr(ss.subprocess, 'run', _raise_timeout)
    srv = tmp_path / 'loop.srv'
    srv.write_text('while true: print(1)', encoding='utf-8')
    out, err, rc = ss.capture_output(srv, timeout=1)
    assert out == ''
    assert 'timed out' in err
    assert rc == 1


def test_capture_output_generic_exception(tmp_path, monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError('nope')

    monkeypatch.setattr(ss.subprocess, 'run', _boom)
    srv = tmp_path / 'x.srv'
    srv.write_text('x', encoding='utf-8')
    out, err, rc = ss.capture_output(srv)
    assert out == ''
    assert 'nope' in err
    assert rc == 1


def test_capture_output_happy_path(tmp_path, monkeypatch):
    class _R:
        stdout = 'hi\n'
        stderr = ''
        returncode = 0

    captured = {}

    def _fake_run(cmd, **kw):
        captured['cmd'] = cmd
        captured['kw'] = kw
        return _R()

    monkeypatch.setattr(ss.subprocess, 'run', _fake_run)
    srv = tmp_path / 'ok.srv'
    srv.write_text('print(1)', encoding='utf-8')
    out, err, rc = ss.capture_output(srv, timeout=5)
    assert (out, err, rc) == ('hi\n', '', 0)
    # Must invoke the saurav.py interpreter with the given file.
    assert any('saurav.py' in str(c) for c in captured['cmd'])
    assert captured['kw']['timeout'] == 5


# ────────────────────────── CLI: main ──────────────────────────

def _run_main(tmp_path, argv, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['sauravshare.py', *argv])
    return ss.main()


def test_main_single_file_writes_sibling_html(tmp_path, monkeypatch, capsys):
    src = tmp_path / 'hello.srv'
    src.write_text('print(1)', encoding='utf-8')
    _run_main(tmp_path, [str(src)], monkeypatch)
    out_file = tmp_path / 'hello.html'
    assert out_file.exists()
    page = out_file.read_text(encoding='utf-8')
    assert '<!DOCTYPE html>' in page
    assert 'print' in page
    assert '-> ' in capsys.readouterr().out


def test_main_custom_output_path(tmp_path, monkeypatch):
    src = tmp_path / 'a.srv'
    src.write_text('x = 1', encoding='utf-8')
    dest = tmp_path / 'custom.html'
    _run_main(tmp_path, [str(src), '-o', str(dest)], monkeypatch)
    assert dest.exists()


def test_main_batch_outdir(tmp_path, monkeypatch):
    (tmp_path / 'a.srv').write_text('x = 1', encoding='utf-8')
    (tmp_path / 'b.srv').write_text('y = 2', encoding='utf-8')
    outdir = tmp_path / 'shared'
    _run_main(
        tmp_path,
        [str(tmp_path / 'a.srv'), str(tmp_path / 'b.srv'), '--outdir', str(outdir)],
        monkeypatch,
    )
    assert (outdir / 'a.html').exists()
    assert (outdir / 'b.html').exists()


def test_main_rejects_output_with_multiple_files(tmp_path, monkeypatch, capsys):
    (tmp_path / 'a.srv').write_text('x', encoding='utf-8')
    (tmp_path / 'b.srv').write_text('y', encoding='utf-8')
    with pytest.raises(SystemExit) as exc:
        _run_main(
            tmp_path,
            [str(tmp_path / 'a.srv'), str(tmp_path / 'b.srv'), '-o', 'out.html'],
            monkeypatch,
        )
    assert exc.value.code == 1
    assert '--outdir' in capsys.readouterr().err


def test_main_missing_file_is_warned_not_fatal(tmp_path, monkeypatch, capsys):
    ok = tmp_path / 'ok.srv'
    ok.write_text('x = 1', encoding='utf-8')
    missing = tmp_path / 'nope.srv'
    _run_main(tmp_path, [str(ok), str(missing)], monkeypatch)
    err = capsys.readouterr().err
    assert 'File not found' in err
    # The valid file still produced output.
    assert (tmp_path / 'ok.html').exists()


def test_main_no_srv_in_directory_exits_1(tmp_path, monkeypatch, capsys):
    empty = tmp_path / 'empty'
    empty.mkdir()
    with pytest.raises(SystemExit) as exc:
        _run_main(tmp_path, [str(empty)], monkeypatch)
    assert exc.value.code == 1
    assert 'No .srv files found' in capsys.readouterr().err


def test_main_directory_arg_globs_srv(tmp_path, monkeypatch):
    sub = tmp_path / 'pkg'
    sub.mkdir()
    (sub / 'a.srv').write_text('x', encoding='utf-8')
    (sub / 'nested').mkdir()
    (sub / 'nested' / 'b.srv').write_text('y', encoding='utf-8')
    outdir = tmp_path / 'out'
    _run_main(tmp_path, [str(sub), '--outdir', str(outdir)], monkeypatch)
    assert (outdir / 'a.html').exists()
    assert (outdir / 'b.html').exists()


def test_main_with_run_invokes_capture_output(tmp_path, monkeypatch):
    src = tmp_path / 'r.srv'
    src.write_text('print(1)', encoding='utf-8')

    calls = []

    def _fake_capture(p, timeout=10):
        calls.append((p, timeout))
        return 'captured-stdout', '', 0

    monkeypatch.setattr(ss, 'capture_output', _fake_capture)
    _run_main(tmp_path, [str(src), '--run', '--timeout', '7'], monkeypatch)
    assert len(calls) == 1
    assert calls[0][1] == 7
    page = (tmp_path / 'r.html').read_text(encoding='utf-8')
    assert 'captured-stdout' in page
    assert '▶ Output' in page
