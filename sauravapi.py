#!/usr/bin/env python3
"""sauravapi -- Serve sauravcode functions as REST API endpoints.

Load a .srv file, and every top-level function becomes a POST endpoint.
Parameters are passed as JSON in the request body.  Results come back
as JSON.  Zero external dependencies.

Usage:
    python sauravapi.py api.srv                    # serve on http://localhost:8480
    python sauravapi.py api.srv --port 9000        # custom port
    python sauravapi.py api.srv --cors              # enable CORS headers
    python sauravapi.py api.srv --list              # list endpoints and exit

Example .srv file (math_api.srv):
    function add x y
        return x + y

    function greet name
        return f"Hello {name}!"

Then:
    curl -X POST http://localhost:8480/add -d '{"x": 3, "y": 5}'
    # => {"result": 8}

    curl -X POST http://localhost:8480/greet -d '{"name": "World"}'
    # => {"result": "Hello World!"}

    curl http://localhost:8480/
    # => {"endpoints": [{"name": "add", "params": ["x", "y"]}, ...]}
"""

import argparse
import copy
import io
import json
import os
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

# ---------------------------------------------------------------------------
# Import the sauravcode interpreter
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from saurav import (  # noqa: E402
    tokenize, Parser, Interpreter, ThrowSignal,
    ReturnSignal,
)


# ---------------------------------------------------------------------------
# Load .srv source and extract functions
# ---------------------------------------------------------------------------

def load_srv(path):
    """Parse a .srv file, interpret it (to register functions/globals),
    and return the interpreter instance."""
    with open(path, "r", encoding="utf-8") as f:
        code = f.read()
    if not code.endswith("\n"):
        code += "\n"
    tokens = list(tokenize(code))
    parser = Parser(tokens)
    ast_nodes = parser.parse()
    interp = Interpreter()
    for node in ast_nodes:
        interp.interpret(node)
    return interp


def _coerce_arg(value):
    """Try to keep JSON values natural for sauravcode (numbers stay numbers)."""
    return value  # sauravcode is dynamically typed; pass through as-is


def _serialise(value):
    """Convert a sauravcode value to something JSON-safe."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        # Return ints without trailing .0
        if isinstance(value, float) and value == int(value):
            return int(value)
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return [_serialise(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _serialise(v) for k, v in value.items()}
    return str(value)


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

# Maximum request body size (1 MB) to prevent denial-of-service via
# oversized payloads.  Configurable via --max-body-size CLI flag.
MAX_BODY_SIZE = 1_048_576  # 1 MB

# Maximum execution time per request (seconds).
MAX_EXEC_TIME = 10

# Maximum concurrent function executions to prevent thread-leak DoS.
# When a request times out the daemon thread keeps running; capping
# concurrency limits the blast radius.
MAX_CONCURRENT_EXECUTIONS = 16
_exec_semaphore = threading.Semaphore(MAX_CONCURRENT_EXECUTIONS)
_active_threads: int = 0
_active_threads_lock = threading.Lock()


class APIHandler(BaseHTTPRequestHandler):
    """Handles GET / (list endpoints) and POST /<fn_name> (call function)."""

    server_version = "sauravapi/1.0"
    interp = None       # set by serve()
    enable_cors = False  # set by serve()
    srv_path = ""        # set by serve()
    max_body_size = MAX_BODY_SIZE  # set by serve()

    def _set_cors(self):
        """Append CORS headers to the current response if CORS is enabled."""
        if self.enable_cors:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json_response(self, code, obj):
        """Send *obj* as a JSON HTTP response with the given status *code*."""
        body = json.dumps(obj, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._set_cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _endpoints_list(self):
        """Return a list of public endpoint descriptors for the index route."""
        endpoints = []
        for name, func in sorted(self.interp.functions.items()):
            if name.startswith("_"):
                continue  # skip private helpers
            params = list(func.params) if func.params else []
            endpoints.append({"name": name, "params": params, "url": f"/{name}"})
        return endpoints

    def do_OPTIONS(self):
        """Handle CORS preflight OPTIONS requests."""
        self.send_response(204)
        self._set_cors()
        self.end_headers()

    def do_GET(self):
        """Serve the endpoint index (``/``) or per-endpoint usage info."""
        path = self.path.rstrip("/")
        if path == "" or path == "/":
            self._json_response(200, {
                "service": "sauravapi",
                "source": os.path.basename(self.srv_path),
                "endpoints": self._endpoints_list(),
            })
            return

        fn_name = path.lstrip("/")
        if fn_name in self.interp.functions and not fn_name.startswith("_"):
            func = self.interp.functions[fn_name]
            params = list(func.params) if func.params else []
            self._json_response(200, {
                "endpoint": fn_name,
                "params": params,
                "method": "POST",
                "hint": f"POST /{fn_name} with JSON body containing: {', '.join(params) if params else '(no params)'}",
            })
            return

        self._json_response(404, {"error": f"Unknown endpoint: /{fn_name}"})

    def do_POST(self):
        """Execute a sauravcode function and return its result as JSON.

        Reads the JSON request body, validates parameters, runs the
        function in an isolated interpreter copy with a timeout guard,
        and returns the result (or an appropriate error).
        """
        fn_name = self.path.lstrip("/").rstrip("/")

        if not fn_name:
            self._json_response(400, {"error": "Specify a function name in the URL path"})
            return

        if fn_name.startswith("_"):
            self._json_response(403, {"error": "Private functions are not exposed"})
            return

        if fn_name not in self.interp.functions:
            self._json_response(404, {"error": f"No function '{fn_name}'. GET / for available endpoints."})
            return

        func = self.interp.functions[fn_name]
        params = list(func.params) if func.params else []

        # Read body — enforce size limit to prevent DoS
        try:
            content_len = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            self._json_response(400, {"error": "Invalid Content-Length header"})
            return
        if content_len < 0:
            self._json_response(400, {"error": "Negative Content-Length is not allowed"})
            return
        if content_len > self.max_body_size:
            self._json_response(413, {
                "error": f"Request body too large ({content_len} bytes). "
                         f"Max allowed: {self.max_body_size} bytes."
            })
            return
        raw = self.rfile.read(content_len) if content_len else b""

        # Parse arguments
        args = {}
        if raw:
            try:
                args = json.loads(raw)
                if not isinstance(args, dict):
                    self._json_response(400, {"error": "Request body must be a JSON object"})
                    return
            except json.JSONDecodeError as e:
                self._json_response(400, {"error": f"Invalid JSON: {e}"})
                return

        # Check required params
        missing = [p for p in params if p not in args]
        if missing:
            self._json_response(400, {
                "error": f"Missing parameters: {', '.join(missing)}",
                "required": params,
            })
            return

        # Build argument list in order
        arg_values = [_coerce_arg(args[p]) for p in params]

        # Execute in an isolated interpreter copy to prevent cross-request
        # state pollution (shared mutable variables are a security risk).
        #
        # Concurrency guard: a semaphore caps the number of in-flight
        # execution threads.  Timed-out threads are daemon threads, so
        # they don't prevent shutdown, but without a cap an attacker
        # could launch many slow requests and exhaust server resources.
        if not _exec_semaphore.acquire(timeout=2):
            self._json_response(503, {
                "error": "Server is at maximum concurrent execution capacity. "
                         "Try again shortly."
            })
            return

        t0 = time.monotonic()
        stdout_capture = io.StringIO()
        try:
            # Deep-copy the interpreter so each request gets clean state
            req_interp = copy.deepcopy(self.interp)
            for p, v in zip(params, arg_values):
                req_interp.variables[p] = v

            # Execute function body with a timeout guard
            result = None
            exc_info = [None]
            timed_out = [False]

            _release_lock = threading.Lock()
            _released = [False]

            def _release_semaphore():
                with _release_lock:
                    if not _released[0]:
                        _released[0] = True
                        _exec_semaphore.release()

            def _execute():
                nonlocal result
                old_stdout = sys.stdout
                sys.stdout = stdout_capture
                try:
                    for stmt in req_interp.functions[fn_name].body:
                        req_interp.interpret(stmt)
                except ReturnSignal as r:
                    result = r.value
                except Exception as e:
                    exc_info[0] = e
                finally:
                    sys.stdout = old_stdout
                    _release_semaphore()

            thread = threading.Thread(target=_execute, daemon=True)
            thread.start()
            thread.join(timeout=MAX_EXEC_TIME)
            if thread.is_alive():
                timed_out[0] = True
                # Release the semaphore immediately on timeout so that
                # stuck daemon threads (e.g. infinite loops) don't
                # permanently consume a concurrency slot, which would
                # lead to a full DoS after MAX_CONCURRENT_EXECUTIONS
                # timed-out requests.
                _release_semaphore()

            if timed_out[0]:
                self._json_response(504, {
                    "error": f"Function '{fn_name}' exceeded {MAX_EXEC_TIME}s execution limit."
                })
                return

            # Re-raise exceptions from the execution thread
            if exc_info[0] is not None:
                raise exc_info[0]

            elapsed = time.monotonic() - t0
            output = stdout_capture.getvalue()

            response = {"result": _serialise(result)}
            if output:
                response["stdout"] = output
            response["elapsed_ms"] = round(elapsed * 1000, 2)

            self._json_response(200, response)

        except ThrowSignal as e:
            msg = e.message
            if isinstance(msg, float) and msg == int(msg):
                msg = int(msg)
            self._json_response(500, {"error": str(msg)})
        except Exception as e:
            self._json_response(500, {"error": str(e)})

    def log_message(self, fmt, *args):
        """Write a compact log line to stderr (overrides default verbose format)."""
        # Cleaner log format
        sys.stderr.write(f"[sauravapi] {args[0]} {args[1]} {args[2]}\n")


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

def serve(srv_path, port=8480, cors=False, host="127.0.0.1", max_body_size=None):
    """Load the .srv file and start the API server."""
    print(f"Loading {srv_path}...")
    interp = load_srv(srv_path)

    # Inject settings into handler class
    APIHandler.interp = interp
    APIHandler.enable_cors = cors
    APIHandler.srv_path = srv_path
    if max_body_size is not None:
        APIHandler.max_body_size = max_body_size

    endpoints = []
    for name, func in sorted(interp.functions.items()):
        if name.startswith("_"):
            continue
        params = list(func.params) if func.params else []
        endpoints.append((name, params))

    if not endpoints:
        print("Warning: No public functions found in the source file.")
        print("Define functions (not starting with _) to expose as endpoints.")
        return

    print(f"\nEndpoints ({len(endpoints)}):")
    for name, params in endpoints:
        param_str = " ".join(params) if params else "(no params)"
        print(f"  POST /{name}  — {param_str}")

    print(f"\nServing on http://{host}:{port}")
    if host == "0.0.0.0":
        print("  ⚠ WARNING: Listening on all interfaces — the API is network-accessible.")
    print("Press Ctrl+C to stop.\n")

    server = HTTPServer((host, port), APIHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


def list_endpoints(srv_path):
    """Load the .srv file and print available endpoints."""
    interp = load_srv(srv_path)
    endpoints = []
    for name, func in sorted(interp.functions.items()):
        if name.startswith("_"):
            continue
        params = list(func.params) if func.params else []
        endpoints.append((name, params))

    if not endpoints:
        print("No public functions found.")
        return

    print(f"Endpoints from {srv_path}:\n")
    for name, params in endpoints:
        param_str = ", ".join(params) if params else "(none)"
        print(f"  /{name}")
        print(f"    params: {param_str}")
        print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    """Parse CLI arguments and launch the API server or list endpoints."""
    parser = argparse.ArgumentParser(
        prog="sauravapi",
        description="Serve sauravcode functions as REST API endpoints.",
    )
    parser.add_argument("source", help="Path to .srv file")
    parser.add_argument("--port", type=int, default=8480, help="Port (default 8480)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Bind address (default 127.0.0.1; use 0.0.0.0 for all interfaces)")
    parser.add_argument("--cors", action="store_true", help="Enable CORS headers")
    parser.add_argument("--max-body-size", type=int, default=None,
                        help=f"Max request body in bytes (default {MAX_BODY_SIZE})")
    parser.add_argument("--list", action="store_true", help="List endpoints and exit")

    args = parser.parse_args()

    if not os.path.isfile(args.source):
        print(f"Error: File '{args.source}' not found.", file=sys.stderr)
        sys.exit(1)

    if args.list:
        list_endpoints(args.source)
    else:
        serve(args.source, port=args.port, cors=args.cors,
              host=args.host, max_body_size=args.max_body_size)


if __name__ == "__main__":
    main()
