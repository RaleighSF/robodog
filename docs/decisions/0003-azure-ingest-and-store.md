# 0003 Ignite stack: Event Hubs Basic + Azure Data Explorer free cluster
Date: 2026-10-30 · Status: Accepted

## Context
The booth needs live data (booth internet required; user decision 2026-10-28), low cost,
and fast time-series queries.

## Decision
- **Ingest:** Azure Event Hubs Basic, namespace `watchdog-ignite-28628191`, hub
  `watchdog-telemetry`, in resource group `rg-watchdog-ignite`, region `southcentralus`.
  Defined in `deploy/azure/main.bicep`.
- **Keys:** `edge-send` (Send only) is used by the Thor; `adx-listen` (Listen only) is
  used by ADX.
- **Store:** ADX free cluster `kvc-n5g99ncbrcxpzed6md.southcentralus`, database
  `watchdog`. Data lands in `RawEvents`, then update policies fill the typed tables
  `Heartbeats`, `Vitals`, `Motors`, `Detections`, `Commands` and `Alerts`.
- **Retention:** 30 days on `RawEvents`; the hub retains 1 day.

## Consequences
- The free cluster has no ARM template, so it is created in the ADX web UI, as is its
  Event Hubs data connection.
- The free cluster has no SLA, which is acceptable for a booth demo.
- The CLI identity was granted database admin explicitly, because the web UI identity
  differs from the CLI identity.

## AWS parity
Candidate stack, to be verified against current AWS service availability before the
build:
- Kinesis Data Streams (on-demand), then Firehose to S3 (Parquet), then Athena views
  mirroring the ADX tables and functions;
- or an equivalent real-time store.

Keep the table names and the derived columns identical.
