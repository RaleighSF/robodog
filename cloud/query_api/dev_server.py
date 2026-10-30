"""Local dev host for the query API (same backends + operations as the Azure
Function). Auth to ADX via your `az login` (ADX_USE_AZ_CLI=1). Dev only.
  ADX_CLUSTER_URI=https://<cluster>.kusto.windows.net python dev_server.py
"""
import json, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("ADX_USE_AZ_CLI", "1")
from backends import OPERATIONS, get_backend

ROUTES = {"/api/" + op.replace("_", "/", 1): op for op in OPERATIONS}
ALLOW_ORIGIN = os.environ.get("DEV_ALLOW_ORIGIN", "http://localhost:3100")
backend = get_backend()


class H(BaseHTTPRequestHandler):
    def _send(self, code, body):
        data = json.dumps(body, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", ALLOW_ORIGIN)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        op = ROUTES.get(u.path)
        if not op:
            return self._send(404, {"error": "unknown operation"})
        fn, defaults = OPERATIONS[op]
        q = parse_qs(u.query)
        params = {k: q.get(k, [d])[0] for k, d in defaults.items()}
        try:
            self._send(200, {"operation": op, "rows": backend.run(fn, params)})
        except ValueError as e:
            self._send(400, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            print("query failed:", op, e)
            self._send(502, {"error": "query failed"})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "7071"))
    print(f"query API dev server on http://localhost:{port}/api ({len(ROUTES)} operations)")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
