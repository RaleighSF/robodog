"""Watch Dog telemetry query API (Azure Functions, Python v2 model).

Read-only. One GET route per operation in backends.OPERATIONS; the Foundry
overwatch agent calls these through the OpenAPI tool (openapi.yaml)."""
import json
import logging

import azure.functions as func

from backends import OPERATIONS, get_backend

# Keyless (ANONYMOUS) on purpose: every route is a read-only GET over robot
# telemetry, and the caller is a public booth web page that cannot hold a
# secret. Browsers are limited by CORS to the dashboard's origin (ADR 0007).
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
_backend = None


def _get():
    global _backend
    if _backend is None:
        _backend = get_backend()
    return _backend


def _handle(op: str, req: func.HttpRequest) -> func.HttpResponse:
    fn, defaults = OPERATIONS[op]
    params = {k: req.params.get(k, d) for k, d in defaults.items()}
    try:
        rows = _get().run(fn, params)
        return func.HttpResponse(json.dumps({"operation": op, "rows": rows}, default=str),
                                 mimetype="application/json")
    except ValueError as e:
        return func.HttpResponse(json.dumps({"error": str(e)}), status_code=400, mimetype="application/json")
    except Exception:
        logging.exception("query %s failed", op)
        return func.HttpResponse(json.dumps({"error": "query failed"}), status_code=502, mimetype="application/json")


def _register(op: str):
    route = op.replace("_", "/", 1)                 # vitals_latest -> vitals/latest
    def handler(req: func.HttpRequest) -> func.HttpResponse:
        return _handle(op, req)
    handler.__name__ = op
    app.route(route=route, methods=["GET"])(handler)


for _op in OPERATIONS:
    _register(_op)
