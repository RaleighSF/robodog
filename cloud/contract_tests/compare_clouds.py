"""Cross-cloud contract check (cloud/PARITY.md), live and read-only: call every
query operation on the Azure and AWS APIs while the same robot streams to both
(demo profile "default"), and fail when what dashboards and agents depend on
differs:
  - column sets per operation;
  - core operations (CORE) must return rows on BOTH clouds;
  - device sets must match;
  - latest values must agree (posture, battery, joint temperatures within 2 C).
Deterministic logic (ordering, nulls, late samples) is covered offline by
test_aws_backend.py.

  python3 cloud/contract_tests/compare_clouds.py <azure-api-base> <aws-api-base>"""
import json
import sys
import urllib.request

sys.path.insert(0, __file__.rsplit("/cloud/", 1)[0] + "/cloud/query_api")
from backends import OPERATIONS  # noqa: E402


def fetch(base, op):
    path = op.replace("_", "/", 1)
    with urllib.request.urlopen(f"{base.rstrip('/')}/{path}", timeout=60) as r:
        return json.load(r)["rows"]


CORE = ("vitals_latest", "vitals_snapshot", "vitals_series", "motors_latest", "motors_series", "posture_timeline")


def main(azure, aws):
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
            if op in CORE:
                bad.append(f"{op}: {verdict}")
                verdict = "FAIL " + verdict
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
    for k in set(ma) & set(mw):
        if ma[k] is not None and mw[k] is not None and abs(ma[k] - mw[k]) > 2:
            bad.append(f"motors_latest {k}: azure={ma[k]} aws={mw[k]}")
    print("\n" + ("PASS" if not bad else "FAIL\n  " + "\n  ".join(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
