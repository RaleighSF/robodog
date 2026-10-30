"""Usage: python3 deploy/azure/tools/kql_run.py <cluster-uri> <database> <file.kql>
Run a .kql script of management commands against ADX, one command at a time."""
import json, subprocess, sys, urllib.request, urllib.error
cluster, db, path = sys.argv[1], sys.argv[2], sys.argv[3]
tok = subprocess.check_output(["az", "account", "get-access-token", "--resource", cluster, "--query", "accessToken", "-o", "tsv"], text=True).strip()
cmds, cur = [], []
for line in open(path):
    if line.lstrip().startswith("//") or not line.strip():
        continue
    if line.startswith("."):
        if cur: cmds.append("".join(cur).strip())
        cur = [line]
    elif cur:
        cur.append(line)
if cur: cmds.append("".join(cur).strip())
ok = 0
for c in cmds:
    req = urllib.request.Request(f"{cluster}/v1/rest/mgmt", data=json.dumps({"db": db, "csl": c}).encode(),
                                 headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=60).read(); ok += 1
    except urllib.error.HTTPError as e:
        print("FAILED:", c.splitlines()[0][:110], "\n   ", e.read().decode()[:400].replace("\n", " "))
print(f"{ok}/{len(cmds)} commands succeeded")
