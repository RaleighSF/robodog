"""AWS ingest Lambda (ADR 0011): Kinesis -> DynamoDB live store.

The AWS counterpart of ingest_adx.py + the ADX update policies. Each Kinesis
record is one schema-1.2 telemetry event (the same JSON the Thor sends to Event
Hubs); rows are derived with backends/rows.py, which mirrors the KQL Expand*
functions. Delivery is at-least-once and batches can arrive late: time-series rows are
keyed by event time (a replay overwrites), Latest#* items are replaced only by
newer rows, and joint state folds late samples in under a version check."""
import base64
import json
import logging

from backends import aws_store as st
from backends import rows

log = logging.getLogger()
log.setLevel(logging.INFO)


def _events(records):
    for r in records:
        try:
            ev = json.loads(base64.b64decode(r["kinesis"]["data"]))
        except (KeyError, ValueError):
            log.warning("skipping undecodable record")
            continue
        if isinstance(ev, dict) and st.parse_ts(ev.get("timestamp")):
            yield ev


def handler(event, _context):
    evs = sorted(_events(event.get("Records", [])), key=lambda e: st.parse_ts(e["timestamp"]))
    w = st.Writer()
    motor_updates, devices = [], {}
    for ev in evs:
        et = str(ev.get("event_type", ""))
        dev = str((ev.get("device") or {}).get("device_id") or "unknown")
        ts = st.parse_ts(ev["timestamp"])
        k = st.key_ts(ts)
        devices[dev] = max(devices.get(dev, k), k)
        if et == "vitals":
            v = rows.vitals_row(ev)
            w.put_if_newer("Latest#" + dev, "vitals", dict(v, _kind="vitals"))
            w.put("Vitals#" + dev, k, {c: v.get(c) for c in st.COMPACT_VITALS})
            ms = rows.motor_rows(ev)
            w.put("Motors#" + dev, k, {"Timestamp": ev["timestamp"],
                                       "J": {m["Joint"]: [m["Temperature"], m["TorqueEst"]] for m in ms}})
            motor_updates += [(dev, m) for m in ms]
        elif et == "heartbeat":
            h = rows.heartbeat_row(ev)
            w.put_if_newer("Latest#" + dev, "heartbeat", dict(h, _kind="heartbeat"))
        elif et == "command":
            w.put("Commands#" + dev, k, rows.command_row(ev))
        elif et == "maneuver":
            m = rows.maneuver_row(ev)
            w.put("Maneuvers#" + dev, k + "#" + m["Name"], m)
        if et == "detection" or et.startswith("alert"):
            for i, d in enumerate(rows.detection_rows(ev)):
                w.put("Detections#" + dev, f"{k}#{d['EventId']}#{i}", d)
        if et.startswith("alert"):
            a = rows.alert_row(ev)
            w.put("Alerts#" + dev, f"{k}#{a['EventId']}", a)

    # Joint state: group this batch's samples per joint, then fold them into the
    # stored state with a consistent read and a versioned write (retry on conflict).
    by_joint: dict = {}
    for dev, m in motor_updates:
        by_joint.setdefault(("JointState#" + dev, m["Joint"]), []).append(m)
    for (pk, sk), ms in by_joint.items():
        for _attempt in range(5):
            cur = w.get_consistent(pk, sk)
            prev = json.loads(cur["d"]) if cur else None
            new = st.fold_joint_state(prev, ms)
            if new is None or w.put_versioned(pk, sk, new, int(cur["v"]) if cur and "v" in cur else (0 if cur else None)):
                break
        else:
            log.warning("joint state %s/%s: gave up after repeated write conflicts", pk, sk)
    for dev, k in devices.items():
        w.put("Devices", dev, {"DeviceId": dev, "Last": k}, ttl=False)
    w.flush()
    log.info("ingested %d events (%d motor samples)", len(evs), len(motor_updates))
    return {"events": len(evs)}
