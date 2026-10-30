# 0002 Read-only query API with named operations
Date: 2026-10-28 · Status: Accepted

## Context
The dashboard and the agent need the same facts on either cloud. Free-form queries would
tie both to one database dialect and let an agent run arbitrary queries.

## Decision
- `cloud/query_api` exposes fixed GET operations and nothing else:
  - `vitals_latest`, `vitals_series`
  - `motors_latest`, `motors_series`
  - `posture_timeline`
  - `detections_summary`, `alerts_recent`, `commands_recent`
  - `overwatch_findings`
- Each cloud implements them in a backend (`backends/adx.py` now). The ADX backend calls
  only the named KQL functions in `deploy/azure/adx/setup.kql`, so it is read-only by
  construction.
- Timespan parameters are validated (`15m`, `1h`, `7d`).

## Consequences
The dashboard and the agent never change when the cloud changes. New data needs a new
named operation, added to every backend.

## AWS parity
Implement `backends/aws.py` with the same operation names, parameters and row shapes (for
example Athena SQL over the S3/Firehose data, or the chosen AWS store; see ADR 0003).
Serve it from Lambda behind API Gateway or a function URL. It must pass
`cloud/contract_tests`.
