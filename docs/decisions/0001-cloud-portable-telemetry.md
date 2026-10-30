# 0001 One telemetry schema, pluggable edge sinks
Date: 2026-10-28 · Status: Accepted

## Context
Watch Dog demos at Microsoft Ignite (Azure) and AWS re:Invent. The edge (Jetson Thor)
already wrote JSON events to S3.

## Decision
- The Thor emits one JSON event schema (`TELEMETRY_SCHEMA.md`) to any combination of
  sinks: `telemetry.sinks: [local, s3, azure_eventhub, ...]` (`telemetry_exporter.py`).
- Every sink receives byte-identical event JSON.
- Secrets (connection strings and keys) live only on the device, for example
  `/state/eventhub.conn`, never in config or git.

## Consequences
Switching clouds is a config change on the Thor. Images go only to object-storage sinks;
the Event Hubs sink sends JSON only.

## AWS parity
Add an `aws_kinesis` (or `aws_iot`) sink implementing `put_json` / `put_image` with the
same JSON. Keep `s3` for snapshots. For re:Invent, the Thor config becomes
`sinks: [aws_kinesis, s3]`.
