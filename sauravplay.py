#!/usr/bin/env python3
"""sauravplay -- Interactive web playground for the sauravcode language.

Launches a local web server with a browser-based code editor where you can
write, run, and experiment with sauravcode in real time.  No external
dependencies beyond the Python standard library and the saurav interpreter.

Usage:
    python sauravplay.py                  # start on http://localhost:8471
    python sauravplay.py --port 9000      # custom port
    python sauravplay.py --no-open        # don't auto-open browser

Features:
    - Syntax-highlighted code editor with line numbers
    - Run code with Ctrl+Enter or the Run button
    - Output panel with stdout capture and error display
    - 8 built-in example programs (dropdown selector)
    - Execution time display
    - Sandboxed: file I/O, sleep, and input are disabled for safety
    - Share button copies a URL-encoded permalink of your code
    - Dark/light theme toggle
    - Persistent editor state via localStorage
"""

import argparse
import html
import io
import json
import os
import sys
import textwrap
import threading
import time
import urllib.parse
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler

# ---------------------------------------------------------------------------
# Import the sauravcode interpreter
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from saurav import tokenize, Parser, Interpreter, ThrowSignal, format_value  # noqa: E402


# ---------------------------------------------------------------------------
# Sandboxed execution
# ---------------------------------------------------------------------------

# Builtins that are unsafe or nonsensical in a web playground.
_DISABLED_BUILTINS = frozenset([
    'read_file', 'write_file', 'append_file', 'read_lines', 'file_exists',
    'sleep', 'input',
])

_MAX_EXECUTION_SECONDS = 5
_MAX_OUTPUT_CHARS = 50_000


def _make_disabled_builtin(name):
    """Return a function that raises RuntimeError when called."""
    def _disabled(*_args, **_kwargs):
        raise RuntimeError(
            f"'{name}' is disabled in the playground (sandbox mode)"
        )
    return _disabled


def _run_code(source):
    """Execute sauravcode *source* in a sandbox and return the result.

    Returns a dict with keys:
        output   - captured stdout (str)
        error    - error message if execution failed (str | None)
        time_ms  - wall-clock execution time in milliseconds (float)
    """
    # Capture stdout
    captured = io.StringIO()
    old_stdout = sys.stdout

    interpreter = Interpreter()

    # Disable dangerous builtins
    for name in _DISABLED_BUILTINS:
        if name in interpreter.builtins:
            interpreter.builtins[name] = _make_disabled_builtin(name)

    # Also disable imports (they read files from disk)
    interpreter._source_dir = None

    error_msg = None
    t0 = time.perf_counter()

    # Run in a thread with a timeout
    result_container = {'done': False}

    def _execute():
        nonlocal error_msg
        sys.stdout = captured
        try:
            tokens = list(tokenize(source))
            parser = Parser(tokens)
            ast_nodes = parser.parse()
            for node in ast_nodes:
                # Respect output limit
                if captured.tell() > _MAX_OUTPUT_CHARS:
                    error_msg = (
                        "Output truncated at {:,} characters".format(
                            _MAX_OUTPUT_CHARS)
                    )
                    break
                from saurav import FunctionCallNode
                if isinstance(node, FunctionCallNode):
                    r = interpreter.execute_function(node)
                    if r is not None:
                        formatted = format_value(r)
                        if formatted is not None:
                            print(formatted)
                else:
                    interpreter.interpret(node)
        except ThrowSignal as e:
            msg = e.message
            if isinstance(msg, float) and msg == int(msg):
                msg = int(msg)
            error_msg = "Uncaught error: {}".format(msg)
        except SyntaxError as e:
            error_msg = "SyntaxError: {}".format(e)
        except RuntimeError as e:
            error_msg = "RuntimeError: {}".format(e)
        except RecursionError:
            error_msg = "RecursionError: maximum recursion depth exceeded"
        except Exception as e:
            error_msg = "Error: {}".format(e)
        finally:
            sys.stdout = old_stdout
            result_container['done'] = True

    thread = threading.Thread(target=_execute, daemon=True)
    thread.start()
    thread.join(timeout=_MAX_EXECUTION_SECONDS)

    elapsed_ms = (time.perf_counter() - t0) * 1000

    if not result_container['done']:
        # Thread is still running -- it timed out
        sys.stdout = old_stdout
        error_msg = (
            "Execution timed out after {}s "
            "(infinite loop?)".format(_MAX_EXECUTION_SECONDS)
        )

    output = captured.getvalue()
    if len(output) > _MAX_OUTPUT_CHARS:
        output = output[:_MAX_OUTPUT_CHARS] + "\n... (truncated)"

    return {
        'output': output,
        'error': error_msg,
        'time_ms': round(elapsed_ms, 2),
    }


# ---------------------------------------------------------------------------
# Example programs
# ---------------------------------------------------------------------------

EXAMPLES = [
    {
        "name": "Hello World",
        "code": textwrap.dedent('''\
            print "Hello, sauravcode!"
            print f"2 + 3 = {2 + 3}"
        '''),
    },
    {
        "name": "Fibonacci",
        "code": textwrap.dedent('''\
            function fib n
                if n <= 1
                    return n
                a = fib (n - 1)
                b = fib (n - 2)
                return a + b

            for i in range 10
                print f"fib({i}) = {fib i}"
        '''),
    },
    {
        "name": "FizzBuzz",
        "code": textwrap.dedent('''\
            for i in range 1 31
                if i % 15 == 0
                    print "FizzBuzz"
                else if i % 3 == 0
                    print "Fizz"
                else if i % 5 == 0
                    print "Buzz"
                else
                    print i
        '''),
    },
    {
        "name": "Higher-Order Functions",
        "code": textwrap.dedent('''\
            numbers = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

            evens = filter (lambda x -> x % 2 == 0) (numbers)
            print f"Evens: {evens}"

            squares = map (lambda x -> x * x) (evens)
            print f"Squares: {squares}"

            total = reduce (lambda a b -> a + b) (numbers) 0
            print f"Sum: {total}"

            print f"Mean: {mean (numbers)}"
            print f"Median: {median (numbers)}"
        '''),
    },
    {
        "name": "String Processing",
        "code": textwrap.dedent('''\
            text = "the quick brown fox jumps over the lazy dog"

            words = split (text) " "
            print f"Word count: {len (words)}"
            print upper (text)

            reversed_words = reverse (words)
            backwards = join " " (reversed_words)
            print f"Reversed: {backwards}"

            has_fox = contains (text) "fox"
            print f"Contains fox: {has_fox}"
            print sha256 (text)
        '''),
    },
    {
        "name": "Maps & Data",
        "code": textwrap.dedent('''\
            person = {"name": "Alice", "age": 30, "city": "Seattle"}
            name = person["name"]
            print f"Name: {name}"
            print f"Keys: {keys (person)}"

            items = [5, 3, 1, 4, 2]
            print f"Sorted: {sort (items)}"
            print f"Sum: {sum (items)}"
            print f"Unique: {unique [1, 2, 2, 3, 3, 3]}"

            data = [23, 45, 12, 67, 34, 89, 56]
            print f"Mean: {round (mean (data)) 2}"
            print f"Stdev: {round (stdev (data)) 2}"
            print f"Median: {median (data)}"
        '''),
    },
    {
        "name": "Pattern Matching",
        "code": textwrap.dedent('''\
            emails = ["alice@example.com", "bob@test", "carol@domain.org"]
            p = "^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+[.][a-zA-Z]{2,}$"

            for email in emails
                if regex_match (p) (email)
                    print f"  Valid:   {email}"
                else
                    print f"  Invalid: {email}"

            text = "Order 42 has 3 items at 19.99 each"
            m = regex_find_all "[0-9.]+" (text)
            print f"Numbers found: {m}"
        '''),
    },
    {
        "name": "Pipes & Statistics",
        "code": textwrap.dedent('''\
            # Pipe operator chains functions
            result = [5, 3, 1, 4, 2] |> sort |> reverse
            print f"Sorted descending: {result}"

            # Error handling with try/catch
            try
                x = 1 / 0
            catch e
                print f"Caught: {e}"

            # Statistics
            data = [23, 45, 12, 67, 34, 89, 56, 11, 78, 43]
            print f"Mean:   {round (mean (data)) 2}"
            print f"Stdev:  {round (stdev (data)) 2}"
            print f"Median: {median (data)}"
            print f"P90:    {percentile (data) 90}"
        '''),
    },
]


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>sauravcode Playground</title>
<style>
:root {
  --bg: #1e1e2e;
  --bg2: #181825;
  --surface: #313244;
  --overlay: #45475a;
  --text: #cdd6f4;
  --subtext: #a6adc8;
  --accent: #89b4fa;
  --accent2: #a6e3a1;
  --error: #f38ba8;
  --warn: #fab387;
  --border: #585b70;
  --font-mono: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', monospace;
}
[data-theme="light"] {
  --bg: #eff1f5;
  --bg2: #e6e9ef;
  --surface: #ccd0da;
  --overlay: #bcc0cc;
  --text: #4c4f69;
  --subtext: #6c6f85;
  --accent: #1e66f5;
  --accent2: #40a02b;
  --error: #d20f39;
  --warn: #fe640b;
  --border: #9ca0b0;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: var(--font-mono);
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}
.header {
  background: var(--bg2);
  border-bottom: 1px solid var(--border);
  padding: 8px 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.header h1 { font-size: 16px; font-weight: 600; color: var(--accent); white-space: nowrap; }
.header h1 span { color: var(--subtext); font-weight: 400; }
.btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 14px; border: 1px solid var(--border); border-radius: 6px;
  background: var(--surface); color: var(--text);
  font-family: var(--font-mono); font-size: 12px;
  cursor: pointer; transition: all 0.15s ease; white-space: nowrap;
}
.btn:hover { background: var(--overlay); border-color: var(--accent); }
.btn-primary {
  background: var(--accent); color: var(--bg);
  border-color: var(--accent); font-weight: 600;
}
.btn-primary:hover { opacity: 0.85; }
select.example-select {
  padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px;
  background: var(--surface); color: var(--text);
  font-family: var(--font-mono); font-size: 12px; cursor: pointer;
}
select.example-select:focus { outline: 2px solid var(--accent); }
.spacer { flex: 1; }
.main { flex: 1; display: flex; min-height: 0; }
.editor-panel {
  flex: 1; display: flex; flex-direction: column;
  border-right: 1px solid var(--border); min-width: 0;
}
.panel-header {
  background: var(--bg2); padding: 6px 12px; font-size: 11px;
  color: var(--subtext); text-transform: uppercase; letter-spacing: 1px;
  border-bottom: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between;
}
.editor-wrap { flex: 1; position: relative; overflow: auto; display: flex; }
.line-numbers {
  padding: 12px 0; text-align: right; user-select: none;
  color: var(--overlay); font-size: 13px; line-height: 1.6;
  min-width: 40px; padding-right: 8px; padding-left: 8px;
  background: var(--bg2); border-right: 1px solid var(--border); flex-shrink: 0;
}
#editor {
  flex: 1; padding: 12px; font-family: var(--font-mono);
  font-size: 13px; line-height: 1.6; background: var(--bg);
  color: var(--text); border: none; outline: none; resize: none;
  white-space: pre; overflow-wrap: normal; tab-size: 4; min-height: 100%;
}
.output-panel { flex: 1; display: flex; flex-direction: column; min-width: 0; }
#output {
  flex: 1; padding: 12px; font-family: var(--font-mono);
  font-size: 13px; line-height: 1.6; background: var(--bg);
  overflow: auto; white-space: pre-wrap; word-break: break-word;
}
.output-error { color: var(--error); }
.status-bar {
  background: var(--bg2); border-top: 1px solid var(--border);
  padding: 4px 12px; font-size: 11px; color: var(--subtext);
  display: flex; justify-content: space-between;
}
@media (max-width: 768px) {
  .main { flex-direction: column; }
  .editor-panel { border-right: none; border-bottom: 1px solid var(--border); min-height: 40vh; }
  .output-panel { min-height: 30vh; }
}
.spinner {
  display: inline-block; width: 14px; height: 14px;
  border: 2px solid var(--bg); border-top-color: transparent;
  border-radius: 50%; animation: spin 0.6s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.toast {
  position: fixed; bottom: 40px; left: 50%; transform: translateX(-50%);
  background: var(--surface); color: var(--accent2);
  padding: 8px 20px; border-radius: 8px; border: 1px solid var(--accent2);
  font-size: 12px; z-index: 100; animation: fadeInOut 2s ease forwards;
}
@keyframes fadeInOut {
  0% { opacity: 0; transform: translateX(-50%) translateY(10px); }
  15% { opacity: 1; transform: translateX(-50%) translateY(0); }
  85% { opacity: 1; } 100% { opacity: 0; }
}
</style>
</head>
<body>
<div class="header">
  <h1>sauravcode <span>playground</span></h1>
  <button class="btn btn-primary" id="runBtn" onclick="runCode()" title="Ctrl+Enter">&#9654; Run</button>
  <select class="example-select" id="examples" onchange="loadExample(this.value)">
    <option value="">&#128218; Examples...</option>
    %%EXAMPLE_OPTIONS%%
  </select>
  <button class="btn" onclick="clearOutput()" title="Clear output">&#128465; Clear</button>
  <button class="btn" onclick="shareCode()" title="Copy shareable link">&#128279; Share</button>
  <div class="spacer"></div>
  <button class="btn" id="themeBtn" onclick="toggleTheme()">&#127769; Theme</button>
</div>
<div class="main">
  <div class="editor-panel">
    <div class="panel-header"><span>editor</span><span id="charCount">0 chars</span></div>
    <div class="editor-wrap">
      <div class="line-numbers" id="lineNums">1</div>
      <textarea id="editor" spellcheck="false" autocapitalize="off" autocomplete="off"
                placeholder="Write sauravcode here..."></textarea>
    </div>
  </div>
  <div class="output-panel">
    <div class="panel-header"><span>output</span><span id="execTime"></span></div>
    <div id="output"><span style="color:var(--subtext)">Press Ctrl+Enter or click Run to execute your code.</span></div>
  </div>
</div>
<div class="status-bar">
  <span>sauravcode playground &middot; sandbox mode (file I/O disabled)</span>
  <span id="statusRight">Ready</span>
</div>
<script>
const EXAMPLES = %%EXAMPLES_JSON%%;
const editor = document.getElementById('editor');
const output = document.getElementById('output');
const lineNums = document.getElementById('lineNums');
const charCount = document.getElementById('charCount');
const execTime = document.getElementById('execTime');
const runBtn = document.getElementById('runBtn');
const statusRight = document.getElementById('statusRight');

function updateLineNumbers() {
  var lines = editor.value.split('\n').length;
  var nums = [];
  for (var i = 1; i <= lines; i++) nums.push(i);
  lineNums.textContent = nums.join('\n');
  charCount.textContent = editor.value.length + ' chars';
}
editor.addEventListener('input', updateLineNumbers);
editor.addEventListener('scroll', function() {
  lineNums.style.transform = 'translateY(-' + editor.scrollTop + 'px)';
});
editor.addEventListener('keydown', function(e) {
  if (e.key === 'Tab') {
    e.preventDefault();
    var start = this.selectionStart, end = this.selectionEnd;
    this.value = this.value.substring(0, start) + '    ' + this.value.substring(end);
    this.selectionStart = this.selectionEnd = start + 4;
    updateLineNumbers();
  }
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); runCode(); }
});

var isRunning = false;
function runCode() {
  if (isRunning) return;
  isRunning = true;
  var code = editor.value;
  if (!code.trim()) { output.innerHTML = '<span class="output-error">No code to run.</span>'; isRunning = false; return; }
  runBtn.innerHTML = '<span class="spinner"></span> Running...';
  runBtn.disabled = true;
  statusRight.textContent = 'Executing...';
  output.innerHTML = '<span style="color:var(--subtext)">Running...</span>';
  execTime.textContent = '';
  localStorage.setItem('sauravplay_code', code);
  fetch('/run', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({code: code}) })
    .then(function(resp) { return resp.json(); })
    .then(function(data) {
      var h = '';
      if (data.output) h += escapeHtml(data.output);
      if (data.error) { if (h) h += '\n'; h += '<span class="output-error">' + escapeHtml(data.error) + '</span>'; }
      if (!data.output && !data.error) h = '<span style="color:var(--subtext)">(no output)</span>';
      output.innerHTML = h;
      execTime.textContent = data.time_ms + ' ms';
      statusRight.textContent = data.error ? 'Error' : 'Done';
    })
    .catch(function(err) { output.innerHTML = '<span class="output-error">Network error: ' + escapeHtml(err.message) + '</span>'; statusRight.textContent = 'Error'; })
    .finally(function() { runBtn.innerHTML = '&#9654; Run'; runBtn.disabled = false; isRunning = false; });
}
function escapeHtml(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function loadExample(idx) {
  if (idx === '') return;
  var ex = EXAMPLES[parseInt(idx)];
  if (ex) { editor.value = ex.code; updateLineNumbers(); output.innerHTML = '<span style="color:var(--subtext)">Loaded: ' + escapeHtml(ex.name) + '</span>'; }
  document.getElementById('examples').value = '';
}
function clearOutput() { output.innerHTML = ''; execTime.textContent = ''; statusRight.textContent = 'Ready'; }
function shareCode() {
  var url = location.origin + '/?code=' + encodeURIComponent(editor.value);
  navigator.clipboard.writeText(url).then(function() { showToast('Link copied to clipboard!'); }).catch(function() { prompt('Copy this URL:', url); });
}
function showToast(msg) {
  var t = document.createElement('div'); t.className = 'toast'; t.textContent = msg;
  document.body.appendChild(t); setTimeout(function() { t.remove(); }, 2200);
}
function toggleTheme() {
  var current = document.documentElement.getAttribute('data-theme');
  var next = current === 'light' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('sauravplay_theme', next);
  document.getElementById('themeBtn').innerHTML = next === 'light' ? '&#127769; Theme' : '&#9728;&#65039; Theme';
}
(function init() {
  var savedTheme = localStorage.getItem('sauravplay_theme');
  if (savedTheme === 'light') { document.documentElement.setAttribute('data-theme', 'light'); document.getElementById('themeBtn').innerHTML = '&#127769; Theme'; }
  var params = new URLSearchParams(location.search);
  var sharedCode = params.get('code');
  if (sharedCode) { editor.value = sharedCode; }
  else { var saved = localStorage.getItem('sauravplay_code'); editor.value = saved || EXAMPLES[0].code; }
  updateLineNumbers(); editor.focus();
})();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

class PlaygroundHandler(BaseHTTPRequestHandler):
    """Serves the playground HTML and handles /run requests."""

    def log_message(self, fmt, *args):
        pass  # suppress noisy default logging

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html_str):
        body = html_str.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ('/', ''):
            example_options = '\n'.join(
                '    <option value="{}">{}</option>'.format(
                    i, html.escape(ex["name"]))
                for i, ex in enumerate(EXAMPLES)
            )
            page = _HTML_TEMPLATE.replace(
                '%%EXAMPLE_OPTIONS%%', example_options
            ).replace(
                '%%EXAMPLES_JSON%%', json.dumps(EXAMPLES)
            )
            self._send_html(page)
        elif parsed.path == '/health':
            self._send_json({'status': 'ok'})
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == '/run':
            length = int(self.headers.get('Content-Length', 0))
            if length > 100_000:
                self._send_json(
                    {'output': '', 'error': 'Code too large (max 100KB)',
                     'time_ms': 0}, status=413)
                return
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self._send_json(
                    {'output': '', 'error': 'Invalid JSON', 'time_ms': 0},
                    status=400)
                return
            code = data.get('code', '')
            if not isinstance(code, str):
                self._send_json(
                    {'output': '', 'error': 'code must be a string',
                     'time_ms': 0}, status=400)
                return
            result = _run_code(code)
            self._send_json(result)
        else:
            self.send_error(404)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='sauravcode interactive web playground')
    parser.add_argument(
        '--port', type=int, default=8471,
        help='Port to listen on (default: 8471)')
    parser.add_argument(
        '--no-open', action='store_true',
        help="Don't auto-open browser")
    args = parser.parse_args()

    server = HTTPServer(('127.0.0.1', args.port), PlaygroundHandler)
    url = 'http://localhost:{}'.format(args.port)

    print("sauravcode playground running at " + url)
    print("Press Ctrl+C to stop.\n")

    if not args.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == '__main__':
    main()
