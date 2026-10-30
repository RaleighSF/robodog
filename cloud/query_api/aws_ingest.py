"""AWS ingest Lambda (ADR 0011): Kinesis -> DynamoDB live store.

The AWS counterpart of ingest_adx.py + the ADX update policies. Each Kinesis
record is one schema-1.2 telemetry event (the same JSON the Thor sends to Event
Hubs); rows are derived with backends/rows.py, which mirrors the KQL Expand*
functions. Delivery is at-least-once: rows are keyed by event time, so a replay
overwrites instead of duplicating, and joint state ignores samples it has seen."""
import base64
import json
import logging
from datetime import datetime, timezone

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
            w.put("Latest#" + dev, "vitals", dict(v, _kind="vitals"), ttl=False)
            w.put("Vitals#" + dev, k, {c: v.get(c) for c in st.COMPACT_VITALS})
            ms = rows.motor_rows(ev)
            w.put("Motors#" + dev, k, {"Timestamp": ev["timestamp"],
                                       "J": {m["Joint"]: [m["Temperature"], m["TorqueEst"]] for m in ms}})
            motor_updates += [(dev, m) for m in ms]
        elif et == "heartbeat":
            h = rows.heartbeat_row(ev)
            w.put("Latest#" + dev, "heartbeat", dict(h, _kind="heartbeat"), ttl=False)
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

    # Joint state: read once per batch, fold every sample in order, write once.
    if motor_updates:
        keys = [("JointState#" + dev, m["Joint"]) for dev, m in motor_updates]
        states = w.get_many(keys)
        for dev, m in motor_updates:
            key = ("JointState#" + dev, m["Joint"])
            new = st.update_joint_state(states.get(key), m)
            if new is not None:
                states[key] = new
                w.put(key[0], key[1], new, ttl=False)
    for dev, k in devices.items():
        w.put("Devices", dev, {"DeviceId": dev, "Last": k}, ttl=False)
    w.flush()
    log.info("ingested %d events (%d motor samples)", len(evs), len(motor_updates))
    return {"events": len(evs)}
