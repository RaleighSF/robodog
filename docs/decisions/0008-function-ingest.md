# 0008 Event Hubs → ADX through a Function, not an ADX data connection
Date: 2026-10-30 · Status: Accepted (amends 0003)

## Context
ADR 0003 planned an ADX Event Hubs data connection. On the free cluster that
connection can only be created in the ADX web UI. The UI needs a tenant-switch
popup: the cluster sits under the personal Microsoft Account directory, while the
subscription is in the "Raleigh" tenant. That made the step manual and brittle.

## Decision
`telemetry_ingest` (`cloud/query_api/ingest_adx.py`), an Event Hubs trigger in the
query API Function App, streams each batch into `RawEvents` with
`RawEventsMapping`. The update policies then fill the typed tables exactly as a
data connection would.
- **Identity:** the Function's managed identity, with *Azure Event Hubs Data
  Receiver* on the hub and *Database Ingestor* on `watchdog`. No secrets.
- **Streaming ingestion:** the policy is enabled on the database and on
  `RawEvents` (`setup.kql`). The SDK always sends gzip, so bodies are gzipped.
- **No new package:** `azure-kusto-data` already provides streaming ingest.
- **Retries:** exponential backoff, at most 5 attempts. Malformed events are skipped
  and logged.

## Consequences
- Fully scripted: no portal or ADX UI steps.
- The query API identity can now write to ADX. Read routes still call only
  named functions (ADR 0002), so this does not widen what HTTP callers can do.
- At-least-once delivery: a restart can replay a batch, so rare duplicate rows
  are possible. That is acceptable for vitals; the queries take latest or binned
  values.
- Reading the Python v2 trigger annotation: use `typing.List[...]`. The worker
  rejects `list[...]` and then indexes no functions at all, which takes the read
  routes down too.

## AWS parity
Kinesis Data Streams → Firehose → S3 (ADR 0003) needs no ingest function. If a
Lambda transform is ever added, give it the same skip-malformed and retry
behaviour, plus an IAM role scoped to that stream and bucket.
