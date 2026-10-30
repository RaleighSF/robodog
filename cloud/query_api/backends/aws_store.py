"""DynamoDB layout for the AWS live store (ADR 0011).

One table (env TELEMETRY_TABLE), string keys `pk` / `sk`, the row as a JSON
string in `d`, and a TTL attribute `ttl` (epoch seconds) on time-series rows:

  pk                      sk              d                          ttl
  Devices                 <device>        {last}                     -
  Latest#<device>         vitals          vitals row incl. Raw       -
  Latest#<device>         heartbeat       heartbeat row              -
  JointState#<device>     <joint>         latest motor row + state   -
  Vitals#<device>         <timestamp>     compact vitals row         24 h
  Motors#<device>         <timestamp>     {joint: [temp, torque]}    24 h
  Detections#<device>     <ts>#<n>        detection row              24 h
  Alerts#<device>         <ts>#<id>       alert row                  24 h
  Commands#<device>       <ts>            command row                24 h
  Maneuvers#<device>      <ts>#<name>     maneuver row               24 h

JointState carries what ADX derives from 2 h of Motors history: when the joint's
current run at or above 55 C / 70 C began, and a short temperature trail (one
point per ~20 s for 11 min) for the 10-minute trend."""
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional

ROW_TTL_S = 24 * 3600
TRAIL_STEP_S = 20
TRAIL_KEEP_S = 11 * 60
CAUTION_C, LIMIT_C = 55.0, 70.0          # mirrored from Overwatch_Findings (provisional thresholds)
COMPACT_VITALS = ("Timestamp", "DeviceId", "BatterySoc", "EdgeDetectionFps", "MotorTempMax", "Connected",
                  "BatteryCurrentA", "Posture", "BodyHeight")


def parse_ts(ts: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def key_ts(dt: datetime) -> str:
    """Canonical sort-key timestamp: fixed width, UTC, so string order == time order."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _table():
    import boto3
    return boto3.resource("dynamodb").Table(os.environ["TELEMETRY_TABLE"])


def _dumps(row: Dict) -> str:
    return json.dumps(row, separators=(",", ":"), default=str)


# ---------------------------------------------------------------------------
# Write side (ingest Lambda)
# ---------------------------------------------------------------------------
class Writer:
    def __init__(self, table=None):
        self.table = table or _table()
        self._puts: Dict[tuple, Dict] = {}

    def put(self, pk: str, sk: str, row: Dict, ttl: bool = True):
        item = {"pk": pk, "sk": sk, "d": _dumps(row)}
        if ttl:
            ts = parse_ts(row.get("Timestamp")) or datetime.now(timezone.utc)
            item["ttl"] = int(ts.timestamp()) + ROW_TTL_S
        self._puts[(pk, sk)] = item          # last write per key wins within a batch (dedupes replays)

    def get_many(self, keys: Iterable[tuple]) -> Dict[tuple, Dict]:
        import boto3
        keys = list(dict.fromkeys(keys))
        out: Dict[tuple, Dict] = {}
        client = boto3.client("dynamodb")
        for i in range(0, len(keys), 100):
            req = {self.table.name: {"Keys": [{"pk": {"S": pk}, "sk": {"S": sk}} for pk, sk in keys[i:i + 100]]}}
            while req:
                resp = client.batch_get_item(RequestItems=req)
                for it in resp.get("Responses", {}).get(self.table.name, []):
                    out[(it["pk"]["S"], it["sk"]["S"])] = json.loads(it["d"]["S"])
                req = resp.get("UnprocessedKeys") or None
        return out

    def flush(self):
        with self.table.batch_writer(overwrite_by_pkeys=["pk", "sk"]) as bw:
            for item in self._puts.values():
                bw.put_item(Item=item)
        self._puts.clear()


def update_joint_state(prev: Optional[Dict], m: Dict) -> Optional[Dict]:
    """New JointState from the previous one and a motor row; None to skip a stale
    or duplicate sample (at-least-once delivery can replay)."""
    ts = parse_ts(m.get("Timestamp"))
    if ts is None:
        return None
    prev = prev or {}
    pts = parse_ts(prev.get("Timestamp"))
    if pts is not None and ts <= pts:
        return None
    t = m.get("Temperature")
    state = dict(m)
    hot = t is not None and t >= CAUTION_C
    over = t is not None and t >= LIMIT_C
    state["Since55"] = (prev.get("Since55") or m["Timestamp"]) if hot else None
    state["Since70"] = (prev.get("Since70") or m["Timestamp"]) if over else None
    trail = [p for p in prev.get("Trail") or [] if ts.timestamp() - p[0] <= TRAIL_KEEP_S]
    if t is not None and (not trail or ts.timestamp() - trail[-1][0] >= TRAIL_STEP_S):
        trail.append([round(ts.timestamp(), 1), t])
    state["Trail"] = trail
    return state


# ---------------------------------------------------------------------------
# Read side (query API Lambda)
# ---------------------------------------------------------------------------
class Reader:
    def __init__(self, table=None):
        self.table = table or _table()

    def _query(self, pk: str, sk_from: Optional[str] = None, newest_first=False, limit: Optional[int] = None) -> List[Dict]:
        from boto3.dynamodb.conditions import Key
        cond = Key("pk").eq(pk) & Key("sk").gte(sk_from) if sk_from else Key("pk").eq(pk)
        kw = {"KeyConditionExpression": cond, "ScanIndexForward": not newest_first}
        rows: List[Dict] = []
        while True:
            if limit:
                kw["Limit"] = limit - len(rows)
            resp = self.table.query(**kw)
            rows += [json.loads(it["d"]) for it in resp.get("Items", [])]
            if (limit and len(rows) >= limit) or "LastEvaluatedKey" not in resp:
                return rows
            kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    def devices(self) -> List[str]:
        return [r.get("DeviceId") for r in self._query("Devices") if r.get("DeviceId")]

    def latest(self, device: str) -> Dict[str, Dict]:
        return {r.pop("_kind"): r for r in self._query("Latest#" + device) if "_kind" in r}

    def joint_states(self, device: str) -> List[Dict]:
        return self._query("JointState#" + device)

    def window(self, kind: str, device: str, window: timedelta, newest_first=False, limit=None) -> List[Dict]:
        since = key_ts(datetime.now(timezone.utc) - window)
        return self._query(f"{kind}#{device}", since, newest_first=newest_first, limit=limit)
