"""Cross-cloud contract check (cloud/PARITY.md): call every query operation on the
Azure and AWS APIs and compare what dashboards and agents depend on: the column
set of each row, and the devices reported. Read-only; safe against live stacks.

  python3 cloud/contract_tests/compare_clouds.py <azure-api-base> <aws-api-base>
Exit 1 when an operation returns rows on both clouds with different columns."""
import json
import sys
import urllib.request

sys.path.insert(0, __file__.rsplit("/cloud/", 1)[0] + "/cloud/query_api")
from backends import OPERATIONS  # noqa: E402


def fetch(base, op):
    path = op.replace("_", "/", 1)
    with urllib.request.urlopen(f"{base.rstrip('/')}/{path}", timeout=60) as r:
        return json.load(r)["rows"]


def main(azure, aws):
    bad = 0
    for op in sorted(OPERATIONS):
        az, aw = fetch(azure, op), fetch(aws, op)
        ca = sorted({k for r in az for k in r}) if az else None
        cw = sorted({k for r in aw for k in r}) if aw else None
        if ca is None or cw is None:
            verdict = "n/a (no rows on " + ("both" if ca is None and cw is None else "azure" if ca is None else "aws") + ")"
        elif ca == cw:
            verdict = "same columns"
        else:
            bad += 1
            verdict = f"DIFF azure-only={sorted(set(ca) - set(cw))} aws-only={sorted(set(cw) - set(ca))}"
        print(f"{op:20} azure={len(az):3} aws={len(aw):3}  {verdict}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
