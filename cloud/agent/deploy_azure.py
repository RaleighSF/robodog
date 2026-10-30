"""Create or update the Watch Dog Overwatch agent in Azure AI Foundry Agent Service.
Instructions (cloud/agent/instructions.md) and the tool spec (cloud/query_api/openapi.yaml)
are the cloud-neutral contracts; the AWS build points Amazon Bedrock at the same files.
  python cloud/agent/deploy_azure.py <project-endpoint> <query-api-base-url> [model]
Auth: your `az login` (needs the Foundry User role on the Foundry resource)."""
import json, os, subprocess, sys, urllib.request

EP, API = sys.argv[1].rstrip("/"), sys.argv[2].rstrip("/")
MODEL = sys.argv[3] if len(sys.argv) > 3 else "gpt-4.1-mini"
NAME = "watchdog-overwatch"
HERE = os.path.dirname(os.path.abspath(__file__))
tok = subprocess.check_output(["az", "account", "get-access-token", "--resource", "https://ai.azure.com",
                               "--query", "accessToken", "-o", "tsv"], text=True).strip()

def call(method, path, body=None):
    req = urllib.request.Request(f"{EP}{path}?api-version=v1", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())

spec_text = open(os.path.join(HERE, "..", "query_api", "openapi.yaml")).read().split("\n", 1)[1]
spec = json.loads(spec_text)
spec["servers"] = [{"url": API}]
for p in spec["paths"].values():
    p["get"].pop("security", None)          # read-only routes are keyless (ADR 0007)
spec.pop("components", None)
body = {
    "name": NAME, "model": MODEL,
    "instructions": open(os.path.join(HERE, "instructions.md")).read(),
    "temperature": 0.2,
    "tools": [{"type": "openapi", "openapi": {
        "name": "watchdog_telemetry",
        "description": "Read-only telemetry for the Go2 robot dog (vitals, 12 joints, posture, findings, detections). Cannot command the robot.",
        "spec": spec, "auth": {"type": "anonymous"}}}],
    "metadata": {"source": "watch_dog/cloud/agent", "contract": "ADR 0004"},
}
existing = [a for a in call("GET", "/assistants").get("data", []) if a.get("name") == NAME]
agent = call("POST", f"/assistants/{existing[0]['id']}", body) if existing else call("POST", "/assistants", body)
print(("updated" if existing else "created"), agent["id"], agent["model"])
