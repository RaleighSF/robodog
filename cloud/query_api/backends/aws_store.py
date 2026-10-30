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

JointState carries what ADX derives from 2 h of Motors history: the joint's
samples for the last 11 min (late samples fold in, so runs and trends match
KQL) and when the current run at or above 55 C / 70 C began. Latest#* items
carry `tsms` and are written only if newer (Writer.put_if_newer)."""
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

ROW_TTL_S = 24 * 3600
SAMPLE_KEEP_S = 11 * 60          # per-joint sample history: enough for the 10-minute trend
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
    """Time-series rows go through batch_writer (keyed by event time, so a replay
    overwrites instead of duplicating). "Newest wins" items (Latest#*) use a
    conditional put so an older or replayed batch can never replace newer state.
    Joint state is read consistently and written with a version check."""

    def __init__(self, table=None):
        self.table = table or _table()
        self._puts: Dict[tuple, Dict] = {}
        self._newest: Dict[tuple, Dict] = {}

    def put(self, pk: str, sk: str, row: Dict, ttl: bool = True):
        item = {"pk": pk, "sk": sk, "d": _dumps(row)}
        if ttl:
            ts = parse_ts(row.get("Timestamp")) or datetime.now(timezone.utc)
            item["ttl"] = int(ts.timestamp()) + ROW_TTL_S
        self._puts[(pk, sk)] = item

    def put_if_newer(self, pk: str, sk: str, row: Dict):
        """Keep only the newest row per key across batches and invocations."""
        ts = parse_ts(row.get("Timestamp"))
        if ts is None:
            return
        ms = int(ts.timestamp() * 1000)
        cur = self._newest.get((pk, sk))
        if cur is None or ms > cur["tsms"]:
            self._newest[(pk, sk)] = {"pk": pk, "sk": sk, "d": _dumps(row), "tsms": ms}

    def get_consistent(self, pk: str, sk: str) -> Optional[Dict]:
        it = self.table.get_item(Key={"pk": pk, "sk": sk}, ConsistentRead=True).get("Item")
        return it

    def put_versioned(self, pk: str, sk: str, row: Dict, prev_version: Optional[int]) -> bool:
        """Write row as version prev+1 only if the stored version is still prev.
        False on a conflict (the caller re-reads and refolds)."""
        from botocore.exceptions import ClientError
        item = {"pk": pk, "sk": sk, "d": _dumps(row), "v": (prev_version or 0) + 1}
        try:
            if prev_version is None:            # item did not exist
                self.table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
            elif prev_version == 0:             # item written before versioning
                self.table.put_item(Item=item, ConditionExpression="attribute_exists(pk) AND attribute_not_exists(v)")
            else:
                self.table.put_item(Item=item, ConditionExpression="v = :v", ExpressionAttributeValues={":v": prev_version})
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise

    def flush(self):
        from botocore.exceptions import ClientError
        with self.table.batch_writer(overwrite_by_pkeys=["pk", "sk"]) as bw:
            for item in self._puts.values():
                bw.put_item(Item=item)
        self._puts.clear()
        for item in self._newest.values():
            try:
                self.table.put_item(Item=item, ConditionExpression="attribute_not_exists(tsms) OR tsms < :t",
                                    ExpressionAttributeValues={":t": item["tsms"]})
            except ClientError as e:
                if e.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                    raise                        # an older row lost to newer stored state: expected
        self._newest.clear()


def _since(samples: List[list], threshold: float, carried: Optional[str]) -> Optional[str]:
    """Start of the current run at or above threshold, from the sample window.
    If every sample in the window is at or above it, the run began earlier: keep
    the carried start (KQL counts it from its 2 h history)."""
    start = None
    for e, t in samples:
        if t is not None and t >= threshold:
            start = start if start is not None else e
        else:
            start = None
    if start is None:
        return None
    if start == samples[0][0] and carried:
        c = parse_ts(carried)
        if c is not None and c.timestamp() <= start:
            return carried
    return iso(datetime.fromtimestamp(start, tz=timezone.utc))


def fold_joint_state(prev: Optional[Dict], motors: List[Dict]) -> Optional[Dict]:
    """New JointState from the previous one and this batch's motor rows for one
    joint, in any order. Late samples within the window are folded into the
    sample history, so runs and trends are recomputed as KQL would; the newest
    sample supplies the latest motor reading. None if nothing changed."""
    prev = prev or {}
    samples = {round(e, 3): t for e, t in prev.get("Samples") or []}
    latest = {k: prev.get(k) for k in prev if k not in ("Samples", "Since55", "Since70")} if prev else {}
    latest_ts = parse_ts(latest.get("Timestamp"))
    changed = False
    for m in motors:
        ts = parse_ts(m.get("Timestamp"))
        if ts is None:
            continue
        e = round(ts.timestamp(), 3)
        if e not in samples:
            samples[e] = m.get("Temperature")
            changed = True
        if latest_ts is None or ts > latest_ts:
            latest, latest_ts, changed = dict(m), ts, True
    if not changed or latest_ts is None:
        return None
    newest = latest_ts.timestamp()
    window = sorted([e, t] for e, t in samples.items() if newest - e <= SAMPLE_KEEP_S)
    state = dict(latest, Samples=window)
    t = latest.get("Temperature")
    state["Since55"] = _since(window, CAUTION_C, prev.get("Since55")) if t is not None and t >= CAUTION_C else None
    state["Since70"] = _since(window, LIMIT_C, prev.get("Since70")) if t is not None and t >= LIMIT_C else None
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
