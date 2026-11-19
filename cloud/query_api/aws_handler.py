"""AWS query API (ADR 0011): Lambda function URL with the same routes, row shapes
and rules as the Azure Function App (function_app.py). Read routes are keyless
(CORS limits browsers to the booth dashboard's origin); agent/ask is staff-only.

  GET  /api/<operation>      e.g. /api/vitals/latest, /api/motors/series?window=10m
  GET  /api/agent/brief      cached 60 s
  POST /api/agent/ask        header x-staff-key
  GET  /api/motion/negotiate receive-only live-twin channel details"""
import base64
import json
import logging
import threading
import time
import uuid

from api_core import BRIEF_PROMPT, clean_question, staff_ok
from backends import OPERATIONS, get_backend
from realtime import motion_client_url

log = logging.getLogger()
log.setLevel(logging.INFO)

ROUTES = {"/api/" + op.replace("_", "/", 1): op for op in OPERATIONS}   # vitals_latest -> /api/vitals/latest
CACHE_S = 2.0      # several screens polling every 2.5 s share one read of the store
CACHE_MAX = 64     # bounded: expired entries are evicted, and at most this many are kept
_backend, _agent = None, None
_cache: dict = {}
_cache_lock = threading.Lock()


def _get_backend():
    global _backend
    if _backend is None:
        _backend = get_backend()
    return _backend


def _get_agent():
    global _agent
    if _agent is None:
        from agents import get_agent
        _agent = get_agent()
    return _agent


class SharedBrief:
    """One agent brief per minute across every Lambda instance (ADR 0011): the
    brief lives in the store (pk "Brief"); whoever wins a short conditional lease
    refreshes it, everyone else serves the stored copy.

    The lease is taken only if the stored brief is still stale (`atms`, epoch ms,
    checked in the same condition) and carries an owner token, so a slow instance
    whose lease expired can neither publish over nor release a newer owner's work."""
    TTL_S, LEASE_S, ASK_S = 60, 50, 40

    def __init__(self):
        from backends.aws_store import _table
        self.table = _table()
        self.key = {"pk": "Brief", "sk": "current"}

    @staticmethod
    def _conflict(e) -> bool:
        return e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"

    def _served(self, body):
        return dict(body, age_s=round(time.time() - body["at"], 1)), None

    def get(self):
        from botocore.exceptions import ClientError
        now = time.time()
        item = self.table.get_item(Key=self.key, ConsistentRead=True).get("Item") or {}
        body = json.loads(item["d"]) if "d" in item else None
        if body and now - body["at"] < self.TTL_S:
            return self._served(body)
        me = uuid.uuid4().hex
        try:
            self.table.update_item(
                Key=self.key, UpdateExpression="SET lease_until = :until, lease_owner = :me",
                ConditionExpression=("(attribute_not_exists(lease_until) OR lease_until < :now) "
                                     "AND (attribute_not_exists(atms) OR atms < :stale)"),
                ExpressionAttributeValues={":until": int(now + self.LEASE_S), ":now": int(now), ":me": me,
                                           ":stale": int((now - self.TTL_S) * 1000)})
        except ClientError as e:
            if not self._conflict(e):
                raise
            # Another instance is refreshing, or just did: serve the freshest copy.
            item = self.table.get_item(Key=self.key, ConsistentRead=True).get("Item") or {}
            body = json.loads(item["d"]) if "d" in item else body
            return self._served(body) if body else (None, "brief is being prepared")
        try:
            r = _get_agent().ask(BRIEF_PROMPT, timeout_s=self.ASK_S)
        except Exception:
            log.exception("agent brief failed")
            self._release(me)
            return self._served(body) if body else (None, "agent unavailable")
        at = time.time()
        fresh = {"text": r["text"], "at": at, "seconds": r["seconds"]}
        try:
            self.table.update_item(
                Key=self.key, UpdateExpression="SET d = :d, atms = :at REMOVE lease_until, lease_owner",
                ConditionExpression="lease_owner = :me",
                ExpressionAttributeValues={":d": json.dumps(fresh), ":at": int(at * 1000), ":me": me})
        except ClientError as e:
            if not self._conflict(e):
                raise
            # Another owner took over: serve what it stored, never our discarded answer.
            log.warning("brief lease lost before publish; serving the stored brief")
            item = self.table.get_item(Key=self.key, ConsistentRead=True).get("Item") or {}
            stored = json.loads(item["d"]) if "d" in item else body
            return self._served(stored) if stored else (None, "brief is being prepared")
        return dict(fresh, age_s=0.0), None

    def _release(self, me: str):
        from botocore.exceptions import ClientError
        try:
            self.table.update_item(Key=self.key, UpdateExpression="REMOVE lease_until, lease_owner",
                                   ConditionExpression="lease_owner = :me", ExpressionAttributeValues={":me": me})
        except ClientError as e:
            if not self._conflict(e):
                raise


_brief = None


def _get_brief():
    global _brief
    if _brief is None:
        _brief = SharedBrief()
    return _brief


def _resp(status, body, cache="no-store"):
    return {"statusCode": status, "headers": {"content-type": "application/json", "cache-control": cache},
            "body": json.dumps(body, default=str)}


def _operation(op, query):
    fn, defaults = OPERATIONS[op]
    params = {k: (query or {}).get(k, d) for k, d in defaults.items()}
    key = (op, tuple(sorted(params.items())))
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_S:
            return _resp(200, hit[1])
    try:
        body = {"operation": op, "rows": _get_backend().run(fn, params)}
    except ValueError as e:
        return _resp(400, {"error": str(e)})
    except Exception:
        log.exception("query %s failed", op)
        return _resp(502, {"error": "query failed"})
    with _cache_lock:
        now = time.time()
        for k in [k for k, (t, _) in _cache.items() if now - t >= CACHE_S]:
            del _cache[k]                                   # evict expired entries
        while len(_cache) >= CACHE_MAX:
            del _cache[min(_cache, key=lambda k: _cache[k][0])]
        _cache[key] = (now, body)
    return _resp(200, body)


def handler(event, _context):
    method = (event.get("requestContext", {}).get("http", {}) or {}).get("method", "GET")
    path = (event.get("rawPath") or "/").rstrip("/") or "/"
    query = event.get("queryStringParameters") or {}
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}

    if method == "GET" and path in ROUTES:
        return _operation(ROUTES[path], query)
    if method == "GET" and path == "/api/agent/brief":
        try:
            body, err = _get_brief().get()
        except Exception:
            log.exception("brief store failed")
            body, err = None, "agent unavailable"
        return _resp(502, {"error": err}) if err else _resp(200, body)
    if method == "POST" and path == "/api/agent/ask":
        if not staff_ok(headers.get("x-staff-key", "")):
            return _resp(401, {"error": "staff passcode required"})
        raw = event.get("body") or ""
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode("utf-8", "replace")
        try:
            q = clean_question((json.loads(raw) if raw else {}).get("question", ""))
        except (ValueError, AttributeError):
            q = ""
        if not q:
            return _resp(400, {"error": "question required"})
        try:
            return _resp(200, _get_agent().ask(q))
        except Exception:
            log.exception("agent ask failed")
            return _resp(502, {"error": "agent unavailable"})
    if method == "GET" and path == "/api/motion/negotiate":
        try:
            return _resp(200, motion_client_url())
        except Exception:
            log.exception("motion negotiate failed")
            return _resp(502, {"error": "live motion unavailable"})
    return _resp(404, {"error": "not found"})
