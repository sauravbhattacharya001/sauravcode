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
import io
import json
import os
import sys
import time
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler

# ---------------------------------------------------------------------------
# Import the sauravcode interpreter
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from saurav import tokenize, Parser, Interpreter, FunctionNode, ThrowSignal, format_value  # noqa: E402


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

class APIHandler(BaseHTTPRequestHandler):
    """Handles GET / (list endpoints) and POST /<fn_name> (call function)."""

    server_version = "sauravapi/1.0"
    interp = None       # set by serve()
    enable_cors = False  # set by serve()
    srv_path = ""        # set by serve()

    def _set_cors(self):
        if self.enable_cors:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json_response(self, code, obj):
        body = json.dumps(obj, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._set_cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _endpoints_list(self):
        endpoints = []
        for name, func in sorted(self.interp.functions.items()):
            if name.startswith("_"):
                continue  # skip private helpers
            params = list(func.params) if func.params else []
            endpoints.append({"name": name, "params": params, "url": f"/{name}"})
        return endpoints

    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors()
        self.end_headers()

    def do_GET(self):
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

        # Read body
        content_len = int(self.headers.get("Content-Length", 0))
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

        # Execute
        t0 = time.monotonic()
        stdout_capture = io.StringIO()
        try:
            from saurav import FunctionCallNode, NumberNode, StringNode, ListNode

            # Build a synthetic function call — simpler to just call directly
            old_vars = dict(self.interp.variables)
            for p, v in zip(params, arg_values):
                self.interp.variables[p] = v

            # Execute function body
            result = None
            from saurav import ReturnSignal
            try:
                for stmt in func.body:
                    self.interp.interpret(stmt)
            except ReturnSignal as r:
                result = r.value

            # Restore variables
            self.interp.variables = old_vars

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
        # Cleaner log format
        sys.stderr.write(f"[sauravapi] {args[0]} {args[1]} {args[2]}\n")


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

def serve(srv_path, port=8480, cors=False):
    """Load the .srv file and start the API server."""
    print(f"Loading {srv_path}...")
    interp = load_srv(srv_path)

    # Inject settings into handler class
    APIHandler.interp = interp
    APIHandler.enable_cors = cors
    APIHandler.srv_path = srv_path

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

    print(f"\nServing on http://localhost:{port}")
    print("Press Ctrl+C to stop.\n")

    server = HTTPServer(("", port), APIHandler)
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
    parser = argparse.ArgumentParser(
        prog="sauravapi",
        description="Serve sauravcode functions as REST API endpoints.",
    )
    parser.add_argument("source", help="Path to .srv file")
    parser.add_argument("--port", type=int, default=8480, help="Port (default 8480)")
    parser.add_argument("--cors", action="store_true", help="Enable CORS headers")
    parser.add_argument("--list", action="store_true", help="List endpoints and exit")

    args = parser.parse_args()

    if not os.path.isfile(args.source):
        print(f"Error: File '{args.source}' not found.", file=sys.stderr)
        sys.exit(1)

    if args.list:
        list_endpoints(args.source)
    else:
        serve(args.source, port=args.port, cors=args.cors)


if __name__ == "__main__":
    main()
