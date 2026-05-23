"""Tests for sauravplay - the sandboxed sauravcode web playground.

Covers the three things a regression here would actually break:

1. ``_run_code`` - the sandboxed interpreter wrapper that the web UI calls
   for every Run click. Correctness of the *sandbox boundary* is the
   whole reason this module exists, so the disabled-builtin set, the
   output truncation cap, and the error-reporting contract are pinned
   down explicitly here.

2. ``PlaygroundHandler`` - the tiny ``http.server`` handler that powers
   the local UI. We spin up a real ``HTTPServer`` on an ephemeral port
   and exercise every branch (``GET /``, ``GET /health``, ``POST /run``
   success + the four documented failure modes, plus 404 fallback).

3. ``EXAMPLES`` - the dropdown sample programs. Each example is shipped
   in the page HTML, so they must all run without error in the sandbox
   (a broken example is a broken landing page).
"""

from __future__ import annotations

import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer

import sauravplay


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _start_server():
    """Start a PlaygroundHandler on an ephemeral port; return (server, port)."""
    server = HTTPServer(('127.0.0.1', 0), sauravplay.PlaygroundHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # Give the accept loop a moment to enter serve_forever.
    time.sleep(0.05)
    return server, port


def _http_post(url, body, content_type='application/json'):
    """POST raw bytes; return (status, body_text). Handles HTTPError."""
    req = urllib.request.Request(
        url, data=body, method='POST',
        headers={'Content-Type': content_type},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=5)
        return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


# ---------------------------------------------------------------------------
# _run_code: happy paths
# ---------------------------------------------------------------------------

class RunCodeBasicsTest(unittest.TestCase):
    """The wrapper must capture stdout, report no error, and time the run."""

    def test_print_number(self):
        result = sauravplay._run_code('print 42')
        self.assertEqual(result['output'], '42\n')
        self.assertIsNone(result['error'])
        self.assertGreaterEqual(result['time_ms'], 0.0)

    def test_print_string(self):
        result = sauravplay._run_code('print "hi"')
        self.assertEqual(result['output'], 'hi\n')
        self.assertIsNone(result['error'])

    def test_multiple_statements_share_state(self):
        result = sauravplay._run_code('a = 5\nprint a + 1')
        self.assertEqual(result['output'], '6\n')
        self.assertIsNone(result['error'])

    def test_empty_source(self):
        result = sauravplay._run_code('')
        self.assertEqual(result['output'], '')
        self.assertIsNone(result['error'])
        self.assertGreaterEqual(result['time_ms'], 0.0)

    def test_result_keys(self):
        result = sauravplay._run_code('print 1')
        self.assertEqual(set(result.keys()), {'output', 'error', 'time_ms'})

    def test_time_ms_is_float(self):
        result = sauravplay._run_code('print 1')
        self.assertIsInstance(result['time_ms'], float)


# ---------------------------------------------------------------------------
# _run_code: error reporting contract
# ---------------------------------------------------------------------------

class RunCodeErrorsTest(unittest.TestCase):
    """All failure modes must surface as ``error`` strings, never raise."""

    def test_syntax_error_is_reported_not_raised(self):
        result = sauravplay._run_code('print (1 +')
        self.assertEqual(result['output'], '')
        self.assertIsNotNone(result['error'])
        self.assertTrue(result['error'].startswith('SyntaxError:'),
                        f"unexpected error: {result['error']!r}")

    def test_uncaught_throw_is_reported(self):
        result = sauravplay._run_code('throw "boom"')
        self.assertIsNotNone(result['error'])
        self.assertIn('boom', result['error'])
        self.assertTrue(result['error'].startswith('Uncaught error:'),
                        f"unexpected error: {result['error']!r}")

    def test_partial_output_before_error_is_preserved(self):
        """A program that prints then throws should keep the printed output."""
        result = sauravplay._run_code('print "before"\nthrow "stop"')
        self.assertEqual(result['output'], 'before\n')
        self.assertIsNotNone(result['error'])
        self.assertIn('stop', result['error'])


# ---------------------------------------------------------------------------
# _run_code: sandbox boundary
# ---------------------------------------------------------------------------

class SandboxDisabledBuiltinsTest(unittest.TestCase):
    """Every name in _DISABLED_BUILTINS must refuse to execute."""

    # Spot-check categories. A single failure here means the playground
    # would let arbitrary visitor code touch the host.
    EXPECTED_DISABLED_SAMPLES = [
        # File I/O
        'read_file', 'write_file', 'delete_file',
        # CSV I/O
        'csv_read', 'csv_write',
        # Directory ops
        'list_dir', 'make_dir', 'path_abs',
        # Environment
        'env_get', 'env_set',
        # System info
        'sys_info',
        # HTTP / SSRF
        'http_get', 'http_post', 'http_put', 'http_delete',
        # Logging to disk
        'log_to_file',
        # Path construction (traversal helper)
        'path_join',
        # Interactive / timing
        'sleep', 'input',
    ]

    def test_all_expected_names_are_in_disabled_set(self):
        missing = [n for n in self.EXPECTED_DISABLED_SAMPLES
                   if n not in sauravplay._DISABLED_BUILTINS]
        self.assertEqual(missing, [],
                         f"sandbox set lost these builtins: {missing}")

    def test_make_disabled_builtin_raises_runtime_error(self):
        fn = sauravplay._make_disabled_builtin('write_file')
        with self.assertRaises(RuntimeError) as cm:
            fn("x.txt", "data")
        self.assertIn('write_file', str(cm.exception))
        self.assertIn('disabled', str(cm.exception).lower())
        self.assertIn('sandbox', str(cm.exception).lower())

    def test_disabled_builtin_in_sauravcode_is_reported(self):
        result = sauravplay._run_code('write_file "x.txt" "hi"')
        self.assertEqual(result['output'], '')
        self.assertIsNotNone(result['error'])
        # Message must mention the offending builtin so the user knows
        # why their snippet was rejected.
        self.assertIn('write_file', result['error'])
        self.assertIn('disabled', result['error'].lower())

    def test_imports_are_disabled(self):
        """``_source_dir`` is set to None so the interpreter can't follow
        ``import`` statements out to disk."""
        # An import attempt should fail with an error rather than succeed.
        result = sauravplay._run_code('import "saurav.py"')
        self.assertIsNotNone(result['error'])


# ---------------------------------------------------------------------------
# _run_code: output truncation
# ---------------------------------------------------------------------------

class OutputTruncationTest(unittest.TestCase):

    def test_output_capped_when_exceeded(self):
        # ~60 KB of output, well past the 50 KB cap.
        big = 'print "x" * 1000\n' * 60
        result = sauravplay._run_code(big)
        # Cap is enforced and the truncation marker is appended.
        self.assertLessEqual(len(result['output']),
                             sauravplay._MAX_OUTPUT_CHARS + 64)
        self.assertIn('truncated', result['output'])
        # When output is truncated the error message also notes the cap.
        self.assertIsNotNone(result['error'])
        self.assertIn('truncated', result['error'].lower())

    def test_short_output_is_not_truncated(self):
        result = sauravplay._run_code('print "hi"')
        self.assertNotIn('truncated', result['output'])
        self.assertIsNone(result['error'])

    def test_max_output_chars_constant(self):
        # Pin the documented limit (the UI tells the user "50,000 chars").
        self.assertEqual(sauravplay._MAX_OUTPUT_CHARS, 50_000)

    def test_max_execution_seconds_constant(self):
        # Pin the documented limit (UI message references this value).
        self.assertEqual(sauravplay._MAX_EXECUTION_SECONDS, 5)


# ---------------------------------------------------------------------------
# Built-in EXAMPLES
# ---------------------------------------------------------------------------

class ExamplesTest(unittest.TestCase):
    """Every dropdown example ships in the HTML; broken ones break the UX."""

    def test_examples_is_nonempty_and_well_formed(self):
        self.assertTrue(len(sauravplay.EXAMPLES) >= 1)
        for ex in sauravplay.EXAMPLES:
            self.assertIn('name', ex)
            self.assertIn('code', ex)
            self.assertIsInstance(ex['name'], str)
            self.assertIsInstance(ex['code'], str)
            self.assertTrue(ex['name'].strip(), 'empty example name')
            self.assertTrue(ex['code'].strip(), 'empty example body')

    def test_every_example_runs_without_error(self):
        for ex in sauravplay.EXAMPLES:
            with self.subTest(example=ex['name']):
                result = sauravplay._run_code(ex['code'])
                self.assertIsNone(
                    result['error'],
                    f"example {ex['name']!r} failed: {result['error']!r}"
                )


# ---------------------------------------------------------------------------
# PlaygroundHandler: HTTP surface
# ---------------------------------------------------------------------------

class PlaygroundHandlerTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.server, cls.port = _start_server()
        cls.base = f'http://127.0.0.1:{cls.port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    # ---- GET ----------------------------------------------------------

    def test_get_root_returns_html_page(self):
        resp = urllib.request.urlopen(self.base + '/', timeout=5)
        self.assertEqual(resp.status, 200)
        self.assertIn('text/html', resp.headers.get('Content-Type', ''))
        body = resp.read().decode()
        # Sentinels from the template.
        self.assertIn('sauravcode', body)
        self.assertIn('<title>sauravcode', body)
        # EXAMPLES are injected as JSON into the page.
        self.assertIn('EXAMPLES = [', body)
        # No unreplaced placeholders should leak through.
        self.assertNotIn('%%EXAMPLE_OPTIONS%%', body)
        self.assertNotIn('%%EXAMPLES_JSON%%', body)

    def test_get_health_returns_ok_json(self):
        resp = urllib.request.urlopen(self.base + '/health', timeout=5)
        self.assertEqual(resp.status, 200)
        self.assertIn('application/json', resp.headers.get('Content-Type', ''))
        self.assertEqual(json.loads(resp.read()), {'status': 'ok'})

    def test_get_unknown_path_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.base + '/does-not-exist', timeout=5)
        self.assertEqual(cm.exception.code, 404)

    # ---- POST /run ----------------------------------------------------

    def test_post_run_executes_code(self):
        status, body = _http_post(
            self.base + '/run',
            json.dumps({'code': 'print 7'}).encode(),
        )
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data['output'], '7\n')
        self.assertIsNone(data['error'])
        self.assertIn('time_ms', data)

    def test_post_run_reports_sandbox_violation(self):
        status, body = _http_post(
            self.base + '/run',
            json.dumps({'code': 'http_get "http://example.com"'}).encode(),
        )
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIsNotNone(data['error'])
        self.assertIn('http_get', data['error'])
        self.assertIn('disabled', data['error'].lower())

    def test_post_run_rejects_invalid_json(self):
        status, body = _http_post(self.base + '/run', b'not-json')
        self.assertEqual(status, 400)
        data = json.loads(body)
        self.assertEqual(data['error'], 'Invalid JSON')
        self.assertEqual(data['output'], '')

    def test_post_run_rejects_oversize_body(self):
        # 100_000 bytes is the documented limit (`>` is strict). We use
        # http.client directly so we can swallow the connection reset that
        # Windows produces when the server replies + closes before we finish
        # streaming the 100 KB body.
        import http.client
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            payload = b'{"code":"' + b'x' * 100_001 + b'"}'
            try:
                conn.request('POST', '/run', body=payload,
                             headers={'Content-Type': 'application/json'})
                resp = conn.getresponse()
                status = resp.status
                body = resp.read().decode()
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                # The server already sent 413 and closed; on some platforms
                # the lingering write of the rejected body raises. We could
                # not read the response. Reconnect and probe with a *small*
                # body to confirm the server is still healthy (i.e. the
                # rejection was orderly, not a crash).
                conn.close()
                status, body = _http_post(
                    self.base + '/run',
                    json.dumps({'code': 'print 1'}).encode(),
                )
                self.assertEqual(status, 200,
                                 'server should still be healthy after a 413')
                self.skipTest('413 response closed connection before client '
                              'finished streaming 100 KB body (Windows); '
                              'server still healthy.')
        finally:
            conn.close()
        self.assertEqual(status, 413)
        data = json.loads(body)
        self.assertIn('too large', data['error'].lower())

    def test_post_run_rejects_non_string_code(self):
        status, body = _http_post(
            self.base + '/run',
            json.dumps({'code': 42}).encode(),
        )
        self.assertEqual(status, 400)
        data = json.loads(body)
        self.assertIn('string', data['error'].lower())

    def test_post_run_missing_code_field_runs_empty(self):
        # ``data.get('code', '')`` defaults to empty string, so the
        # handler must succeed (and return empty output) rather than 500.
        status, body = _http_post(
            self.base + '/run',
            json.dumps({}).encode(),
        )
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data['output'], '')
        self.assertIsNone(data['error'])

    def test_post_unknown_path_is_404(self):
        status, _ = _http_post(self.base + '/anything-else', b'')
        self.assertEqual(status, 404)


if __name__ == '__main__':
    unittest.main()
