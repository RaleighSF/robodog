"""Azure AI Foundry Agent Service client (managed identity; no keys).
Env: FOUNDRY_PROJECT_ENDPOINT, FOUNDRY_AGENT_ID."""
import json
import os
import time
import urllib.request


class FoundryAgent:
    API = "v1"

    def __init__(self):
        from azure.identity import DefaultAzureCredential
        self.ep = os.environ["FOUNDRY_PROJECT_ENDPOINT"].rstrip("/")
        self.agent_id = os.environ["FOUNDRY_AGENT_ID"]
        self.cred = DefaultAzureCredential()

    def _call(self, method, path, body=None):
        tok = self.cred.get_token("https://ai.azure.com/.default").token
        sep = "&" if "?" in path else "?"
        req = urllib.request.Request(f"{self.ep}{path}{sep}api-version={self.API}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=60).read())

    def ask(self, question: str, timeout_s: float = 45) -> dict:
        t0 = time.time()
        run = self._call("POST", "/threads/runs", {"assistant_id": self.agent_id,
                                                   "thread": {"messages": [{"role": "user", "content": question}]}})
        while run["status"] in ("queued", "in_progress", "requires_action"):
            if time.time() - t0 > timeout_s:
                raise TimeoutError("agent run timed out")
            time.sleep(1.0)
            run = self._call("GET", f"/threads/{run['thread_id']}/runs/{run['id']}")
        if run["status"] != "completed":
            raise RuntimeError(f"agent run {run['status']}")
        msgs = self._call("GET", f"/threads/{run['thread_id']}/messages?order=desc&limit=1")
        text = msgs["data"][0]["content"][0]["text"]["value"] if msgs.get("data") else ""
        try:   # threads are per question; do not keep them around
            self._call("DELETE", f"/threads/{run['thread_id']}")
        except Exception:  # noqa: BLE001
            pass
        usage = run.get("usage") or {}
        return {"text": text, "seconds": round(time.time() - t0, 1), "tokens": usage.get("total_tokens")}
