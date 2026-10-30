"""Watch Dog telemetry query API (Azure Functions, Python v2 model).

Read-only. One GET route per operation in backends.OPERATIONS; the Foundry
overwatch agent calls these through the OpenAPI tool (openapi.yaml)."""
import hmac
import json
import logging
import os
import threading
import time

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


# ---------------------------------------------------------------------------
# Agent overwatch (ADR 0004). The browser never talks to the model directly.
# ---------------------------------------------------------------------------
from agents import get_agent  # noqa: E402
from ingest_adx import bp as ingest_bp  # noqa: E402

app.register_functions(ingest_bp)       # Event Hubs -> ADX (ADR 0008)


# ---------------------------------------------------------------------------
# Live motion mirror (ADR 0010): hand dashboards a short-lived, receive-only
# client URL for the real-time channel. No access key exists (local auth is
# off); the token is minted with this app's managed identity.
# ---------------------------------------------------------------------------
from realtime import motion_client_url  # noqa: E402


@app.route(route="motion/negotiate", methods=["GET"])
def motion_negotiate(req: func.HttpRequest) -> func.HttpResponse:
    try:
        return func.HttpResponse(json.dumps(motion_client_url()), mimetype="application/json",
                                 headers={"Cache-Control": "no-store"})
    except Exception:
        logging.exception("motion negotiate failed")
        return func.HttpResponse(json.dumps({"error": "live motion unavailable"}), status_code=502, mimetype="application/json")

BRIEF_PROMPT = ("Give the booth's current crew-alerting brief: check overwatch_findings and the latest "
                "vitals, then state the single most important thing in 1-2 sentences, ending with the "
                "recommended action if any.")
BRIEF_TTL_S = 60          # one model call per minute at most, however many screens poll
_agent = None
_brief = {"t": 0.0, "body": None}
_brief_lock = threading.Lock()


def _get_agent():
    global _agent
    if _agent is None:
        _agent = get_agent()
    return _agent


@app.route(route="agent/brief", methods=["GET"])
def agent_brief(req: func.HttpRequest) -> func.HttpResponse:
    with _brief_lock:
        if _brief["body"] is None or time.time() - _brief["t"] > BRIEF_TTL_S:
            try:
                r = _get_agent().ask(BRIEF_PROMPT)
                _brief.update(t=time.time(), body={"text": r["text"], "at": time.time(), "seconds": r["seconds"]})
            except Exception:
                logging.exception("agent brief failed")
                if _brief["body"] is None:
                    return func.HttpResponse(json.dumps({"error": "agent unavailable"}), status_code=502, mimetype="application/json")
        body = dict(_brief["body"], age_s=round(time.time() - _brief["t"], 1))
    return func.HttpResponse(json.dumps(body), mimetype="application/json")


@app.route(route="agent/ask", methods=["POST"])
def agent_ask(req: func.HttpRequest) -> func.HttpResponse:
    # Staff only: visitors never type to the agent at a public booth.
    want = os.environ.get("STAFF_KEY", "")
    got = req.headers.get("x-staff-key", "")
    if not want or not hmac.compare_digest(want.encode(), got.encode()):
        return func.HttpResponse(json.dumps({"error": "staff passcode required"}), status_code=401, mimetype="application/json")
    try:
        q = (req.get_json() or {}).get("question", "")
    except ValueError:
        q = ""
    q = str(q).strip()[:500]
    if not q:
        return func.HttpResponse(json.dumps({"error": "question required"}), status_code=400, mimetype="application/json")
    try:
        r = _get_agent().ask(q)
        return func.HttpResponse(json.dumps(r), mimetype="application/json")
    except Exception:
        logging.exception("agent ask failed")
        return func.HttpResponse(json.dumps({"error": "agent unavailable"}), status_code=502, mimetype="application/json")
