"""Real-time channel for the live motion mirror (ADR 0010).

Azure: Web PubSub, hub `motion`. Dashboards get a receive-only token that joins
group `motion` at connect; only the Thor holds a send-to-group token. AWS
(re:Invent) swaps this module for API Gateway WebSockets or IoT Core and keeps
the same {url, protocol, expires_in_s} contract."""
import json
import os
import threading
import time
import urllib.parse
import urllib.request

TOKEN_MINUTES = 60
_cache = {"exp": 0.0, "body": None}
_lock = threading.Lock()
_cred = None


def _bearer() -> str:
    global _cred
    if _cred is None:
        from azure.identity import DefaultAzureCredential
        _cred = DefaultAzureCredential()
    return _cred.get_token("https://webpubsub.azure.com/.default").token


def motion_client_url() -> dict:
    """One shared receive-only URL, re-minted 10 minutes before it expires."""
    with _lock:
        if _cache["body"] and time.time() < _cache["exp"] - 600:
            return dict(_cache["body"], expires_in_s=int(_cache["exp"] - time.time()))
        host = os.environ["MOTION_PUBSUB_HOST"]            # <name>.webpubsub.azure.com
        hub = os.environ.get("MOTION_HUB", "motion")
        group = os.environ.get("MOTION_GROUP", "motion")
        qs = urllib.parse.urlencode({"api-version": "2024-01-01", "minutesToExpire": TOKEN_MINUTES, "group": group})
        req = urllib.request.Request("https://%s/api/hubs/%s/:generateToken?%s" % (host, hub, qs), method="POST",
                                     headers={"Authorization": "Bearer " + _bearer(), "Content-Length": "0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            token = json.load(r)["token"]
        _cache["exp"] = time.time() + TOKEN_MINUTES * 60
        _cache["body"] = {"url": "wss://%s/client/hubs/%s?access_token=%s" % (host, hub, token),
                          "protocol": "json.webpubsub.azure.v1", "group": group}
        return dict(_cache["body"], expires_in_s=TOKEN_MINUTES * 60)
