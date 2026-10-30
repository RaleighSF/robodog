"""Cross-cloud contract check (cloud/PARITY.md), live and read-only: call every
query operation on the Azure and AWS APIs while the same robot streams to both
(demo profile "default"), and fail when what dashboards and agents depend on
differs:
  - column sets per operation;
  - an operation with rows on one cloud only fails, unless explained with
    --explain op="reason" (for example history from before a stack existed);
  - device sets per operation, and the (device, joint) set of motors_latest;
  - latest values must agree (posture, charging, battery within 1 %,
    joint temperatures within 2 C);
  - overwatch findings must agree as (device, severity, finding head), with
    the numbers in the head masked (the clouds read a moment apart).
Deterministic logic (ordering, nulls, late samples) is covered offline by
test_aws_backend.py.

  python3 cloud/contract_tests/compare_clouds.py <azure-api-base> <aws-api-base>"""
import argparse
import json
import re
import sys
import urllib.request

sys.path.insert(0, __file__.rsplit("/cloud/", 1)[0] + "/cloud/query_api")
from backends import OPERATIONS  # noqa: E402


def fetch(base, op):
    path = op.replace("_", "/", 1)
    with urllib.request.urlopen(f"{base.rstrip('/')}/{path}", timeout=60) as r:
        return json.load(r)["rows"]


CORE = ("vitals_latest", "vitals_snapshot", "vitals_series", "motors_latest", "motors_series", "posture_timeline")


def finding_key(r):
    head = str(r.get("Finding", "")).split(" · ")[0]
    return (r.get("DeviceId"), r.get("Severity"), re.sub(r"-?\d+(\.\d+)?", "#", head))


def main(azure, aws, explained=None):
    explained = explained or {}
    bad = []
    got = {}
    for op in sorted(OPERATIONS):
        az, aw = fetch(azure, op), fetch(aws, op)
        got[op] = (az, aw)
        ca = sorted({k for r in az for k in r}) if az else None
        cw = sorted({k for r in aw for k in r}) if aw else None
        if ca is None or cw is None:
            side = "both" if ca is None and cw is None else "azure" if ca is None else "aws"
            verdict = f"no rows on {side}"
            if op in CORE or (side != "both" and op not in explained):
                bad.append(f"{op}: {verdict}")
                verdict = "FAIL " + verdict
            elif op in explained:
                verdict += f" (explained: {explained[op]})"
        elif ca != cw:
            bad.append(f"{op}: columns differ")
            verdict = f"FAIL columns azure-only={sorted(set(ca) - set(cw))} aws-only={sorted(set(cw) - set(ca))}"
        else:
            da = {r.get("DeviceId") for r in az if "DeviceId" in r}
            dw = {r.get("DeviceId") for r in aw if "DeviceId" in r}
            if da != dw:
                bad.append(f"{op}: devices differ")
                verdict = f"FAIL devices azure={sorted(map(str, da))} aws={sorted(map(str, dw))}"
            else:
                verdict = "ok"
        print(f"{op:20} azure={len(az):3} aws={len(aw):3}  {verdict}")
    # Latest values: both clouds see the same robot at (nearly) the same moment.
    va = {r["DeviceId"]: r for r in got["vitals_latest"][0]}
    vw = {r["DeviceId"]: r for r in got["vitals_latest"][1]}
    for dev in set(va) & set(vw):
        for c in ("Posture", "Charging"):
            if va[dev].get(c) != vw[dev].get(c):
                bad.append(f"vitals_latest {dev}.{c}: azure={va[dev].get(c)!r} aws={vw[dev].get(c)!r}")
        a, w = va[dev].get("BatterySoc"), vw[dev].get("BatterySoc")
        if a is not None and w is not None and abs(a - w) > 1:
            bad.append(f"vitals_latest {dev}.BatterySoc: azure={a} aws={w}")
    ma = {(r["DeviceId"], r["Joint"]): r.get("Temperature") for r in got["motors_latest"][0]}
    mw = {(r["DeviceId"], r["Joint"]): r.get("Temperature") for r in got["motors_latest"][1]}
    if set(ma) != set(mw):
        bad.append(f"motors_latest joints differ: azure-only={sorted(set(ma) - set(mw))} aws-only={sorted(set(mw) - set(ma))}")
    for k in set(ma) & set(mw):
        if ma[k] is not None and mw[k] is not None and abs(ma[k] - mw[k]) > 2:
            bad.append(f"motors_latest {k}: azure={ma[k]} aws={mw[k]}")
    fa = {finding_key(r) for r in got["overwatch_findings"][0]}
    fw = {finding_key(r) for r in got["overwatch_findings"][1]}
    if fa != fw and not ((not fa or not fw) and "overwatch_findings" in explained):
        bad.append(f"overwatch_findings differ: azure-only={sorted(map(str, fa - fw))} aws-only={sorted(map(str, fw - fa))}")
    print("\n" + ("PASS" if not bad else "FAIL\n  " + "\n  ".join(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("azure")
    ap.add_argument("aws")
    ap.add_argument("--explain", action="append", default=[], metavar='OP="reason"',
                    help="accept rows on one cloud only for OP, printing the reason")
    a = ap.parse_args()
    sys.exit(main(a.azure, a.aws, dict(e.split("=", 1) for e in a.explain)))
