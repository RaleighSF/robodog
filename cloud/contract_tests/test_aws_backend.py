"""Deterministic tests for the AWS live store and query backend (ADR 0011), run
against an in-memory DynamoDB (moto). Covers the cases Astra reproduced:
out-of-order batches, late samples in hot-joint runs, alert-only devices, null
aggregates, timestamp ordering, parameter bounds.

  pip install "moto[dynamodb]" boto3 pytest && python3 -m pytest cloud/contract_tests/test_aws_backend.py -q"""
import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "query_api"))
os.environ.update(AWS_DEFAULT_REGION="us-east-1", AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x",
                  TELEMETRY_TABLE="t", TELEMETRY_BACKEND="aws")
moto = pytest.importorskip("moto")


@pytest.fixture()
def store():
    with moto.mock_aws():
        import boto3
        boto3.client("dynamodb").create_table(
            TableName="t", BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}])
        import aws_ingest
        from backends.aws import AWSBackend
        yield aws_ingest, AWSBackend()


NOW = datetime.now(timezone.utc).replace(microsecond=0)


def ts(sec_ago: float) -> str:
    return (NOW - timedelta(seconds=sec_ago)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def vitals(sec_ago, temp=40.0, soc=80.0, posture="standing", dev="dog"):
    motors = [{"joint": j, "temperature": temp if j == "FR_hip" else 35, "q": 0.1, "dq": 0, "tau_est": 1.0, "lost": 0, "mode": 1}
              for j in [f"{l}_{s}" for l in ("FR", "FL", "RR", "RL") for s in ("hip", "thigh", "calf")]]
    return {"event_type": "vitals", "timestamp": ts(sec_ago), "device": {"device_id": dev}, "session_id": "s",
            "robot_vitals": {"connected": True, "posture": posture, "power": {"bms": {"soc": soc, "current": -2600}},
                             "motors": motors, "motor_summary": {"temp_max": temp}}, "edge": {}}


def push(ingest, *events):
    ingest.handler({"Records": [{"kinesis": {"data": base64.b64encode(json.dumps(e).encode()).decode()}} for e in events]}, None)


def test_older_batch_never_replaces_latest(store):
    ingest, b = store
    push(ingest, vitals(5, soc=70))
    push(ingest, vitals(10, soc=90))                 # an older batch arrives later
    assert b.run("Vitals_Latest", {})[0]["BatterySoc"] == 70


def test_late_cool_sample_restarts_hot_run(store):
    ingest, b = store
    push(ingest, vitals(120, temp=60), vitals(0, temp=60))
    push(ingest, vitals(60, temp=40))                # late cool sample between the two hot ones
    s = next(r for r in b.r.joint_states("dog") if r["Joint"] == "FR_hip")
    assert s["Since55"].startswith((NOW).isoformat()[:16])      # the run restarts at the newest hot sample


def test_late_hot_sample_keeps_latest_reading(store):
    ingest, b = store
    push(ingest, vitals(0, temp=75))
    push(ingest, vitals(30, temp=40))                # older sample must not replace the latest reading
    rows = {r["Joint"]: r for r in b.run("Motors_Latest", {})}
    assert rows["FR_hip"]["Temperature"] == 75
    assert any("FR hip 75 °C" in f["Finding"] for f in b.run("Overwatch_Findings", {}))


def test_ppe_alerts_for_alert_only_device(store):
    ingest, b = store
    push(ingest, {"event_type": "alert:PPE_violation", "timestamp": ts(10), "device": {"device_id": "cam"},
                  "event_id": "e1", "vision": {"detection_count": 1, "detections": []}})
    assert any(f["DeviceId"] == "cam" and "PPE" in f["Finding"] for f in b.run("Overwatch_Findings", {}))


def test_missing_confidence_stays_null(store):
    ingest, b = store
    push(ingest, {"event_type": "detection", "timestamp": ts(5), "device": {"device_id": "dog"}, "event_id": "d1",
                  "vision": {"detections": [{"class_name": "person"}]}})
    assert b.run("Detections_Summary", {"window": "1h"})[0]["AvgConfidence"] is None


def test_recent_events_sorted_by_real_time(store):
    ingest, b = store
    a = {"event_type": "command", "device": {"device_id": "dog"}, "robot": {"last_command": {"command": "a"}}}
    push(ingest, dict(a, timestamp=NOW.strftime("%Y-%m-%dT%H:%M:%SZ")),
         dict(a, timestamp=(NOW + timedelta(milliseconds=500)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
              robot={"last_command": {"command": "b"}}))
    assert [r["Command"] for r in b.run("Commands_Recent", {"window": "1h"})] == ["b", "a"]


def test_parameter_bounds(store):
    _, b = store
    for bad in ({"window": "7d"}, {"window": "1h", "bin_size": "1s"}, {"window": "1d", "bin_size": "10s"}, {"window": "x"}):
        with pytest.raises(ValueError):
            b.run("Vitals_Series", dict({"window": "1h", "bin_size": "1m"}, **bad))


def _fr_hip(b):
    return next(r for r in b.r.joint_states("dog") if r["Joint"] == "FR_hip")


def test_long_run_survives_sample_pruning(store):
    ingest, b = store
    push(ingest, vitals(1500, temp=60))              # run starts 25 min ago, outside the 11-min sample window
    for ago in range(1440, -1, -60):
        push(ingest, vitals(ago, temp=60))
    assert _fr_hip(b)["Since55"].startswith(ts(1500)[:16])
    push(ingest, vitals(1200, temp=40))              # a late cool sample older than the sample window
    since = datetime.fromisoformat(_fr_hip(b)["Since55"])
    # Bound (aws_store._run): the run restarts no earlier than the true restart
    # (19 min ago), at the oldest retained hot sample: shorter, never longer.
    assert NOW - timedelta(seconds=1140) <= since <= NOW - timedelta(seconds=540)


def test_null_temperature_is_neither_hot_nor_cool(store):
    ingest, b = store
    push(ingest, vitals(120, temp=60))
    push(ingest, vitals(60, temp=None))
    push(ingest, vitals(0, temp=60))
    assert _fr_hip(b)["Since55"].startswith(ts(120)[:16])


def test_legacy_latest_row_without_tsms(store):
    ingest, b = store
    from backends.aws_store import _dumps
    from backends.rows import vitals_row
    row = dict(vitals_row(vitals(5, soc=70)), _kind="vitals")
    b.r.table.put_item(Item={"pk": "Latest#dog", "sk": "vitals", "d": _dumps(row)})   # pre-tsms item
    push(ingest, vitals(10, soc=90))                 # older: must not replace it
    assert b.run("Vitals_Latest", {})[0]["BatterySoc"] == 70
    push(ingest, vitals(1, soc=60))                  # newer: replaces it and gains tsms
    assert b.run("Vitals_Latest", {})[0]["BatterySoc"] == 60


def test_findings_are_deterministic(store):
    ingest, b = store
    push(ingest, vitals(300, temp=60), vitals(0, temp=62))
    f = [(x["DeviceId"], x["Severity"], x["Finding"].split(" · ")[0]) for x in b.run("Overwatch_Findings", {})]
    assert f == [(x["DeviceId"], x["Severity"], x["Finding"].split(" · ")[0]) for x in b.run("Overwatch_Findings", {})]
    assert any(d == "dog" and "FR hip 62 °C" in t for d, _, t in f)


def test_brief_lease_is_owned_and_stale_checked(store, monkeypatch):
    import aws_handler
    calls = []

    class FakeAgent:
        def ask(self, q, timeout_s=0):
            calls.append(q)
            return {"text": f"brief {len(calls)}", "seconds": 0.1}
    monkeypatch.setattr(aws_handler, "_get_agent", lambda: FakeAgent())
    sb = aws_handler.SharedBrief()
    body, err = sb.get()
    assert err is None and body["text"] == "brief 1"
    assert sb.get()[0]["text"] == "brief 1" and len(calls) == 1          # fresh: served, not regenerated
    # A stale instance that lost its lease cannot publish or release over a newer owner.
    sb.table.update_item(Key=sb.key, UpdateExpression="SET lease_owner = :o, lease_until = :u",
                         ExpressionAttributeValues={":o": "other", ":u": 2**31})
    sb._release("me")
    assert sb.table.get_item(Key=sb.key)["Item"]["lease_owner"] == "other"


def test_null_interval_longer_than_window_keeps_run(store):
    ingest, b = store
    push(ingest, vitals(900, temp=60))
    push(ingest, vitals(140, temp=None), vitals(120, temp=None))   # 60 C sample now pruned, only nulls kept
    push(ingest, vitals(0, temp=60))
    assert _fr_hip(b)["Since55"].startswith(ts(900)[:16])


def test_brief_lost_lease_serves_stored_copy(store, monkeypatch):
    import aws_handler
    sb = aws_handler.SharedBrief()

    class Thief:
        def ask(self, q, timeout_s=0):     # while we ask, another owner takes the lease and publishes
            import json as _j, time as _t
            sb.table.put_item(Item=dict(sb.key, d=_j.dumps({"text": "new owner brief", "at": _t.time(), "seconds": 1}),
                                        atms=int(_t.time() * 1000), lease_owner="other"))
            return {"text": "lost owner brief", "seconds": 0.1}
    monkeypatch.setattr(aws_handler, "_get_agent", lambda: Thief())
    assert sb.get()[0]["text"] == "new owner brief"
