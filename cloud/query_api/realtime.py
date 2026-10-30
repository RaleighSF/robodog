"""Real-time channel for the live twin (ADR 0010, ADR 0011).

MOTION_PROVIDER picks the cloud:
  azure: Web PubSub, hub `motion`. Dashboards get a receive-only token that joins
         group `motion` at connect; only the Thor holds a send-to-group token.
         Returns {url, protocol, group, expires_in_s}.
  aws:   AppSync Events, namespace `motion`. Publishing needs IAM (only the
         Thor's edge user has it); subscribing uses the API key handed out here,
         which can only subscribe. Returns {provider: "aws-appsync-events",
         httpDomain, realtimeDomain, apiKey, channel}."""
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
    if os.environ.get("MOTION_PROVIDER", "azure").lower() == "aws":
        return {"provider": "aws-appsync-events", "httpDomain": os.environ["MOTION_HTTP_DOMAIN"],
                "realtimeDomain": os.environ["MOTION_REALTIME_DOMAIN"], "apiKey": os.environ["MOTION_API_KEY"],
                "channel": os.environ.get("MOTION_CHANNEL", "/motion/booth")}
    return _webpubsub_url()


def _webpubsub_url() -> dict:
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
