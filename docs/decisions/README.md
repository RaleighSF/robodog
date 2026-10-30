# Design decision log (ADRs)

Each decision gets one short record: context, decision, consequences, and **AWS
parity** (what the re:Invent build must do to match). The Azure build for Microsoft
Ignite is the reference implementation. The AWS build for re:Invent is generated from
these records plus `cloud/PARITY.md`, and it must pass the same contract tests.

| # | Decision | Status |
|---|---|---|
| [0001](0001-cloud-portable-telemetry.md) | One telemetry schema; pluggable edge sinks | Accepted |
| [0002](0002-read-only-query-api.md) | Read-only query API with named operations and per-cloud backends | Accepted |
| [0003](0003-azure-ingest-and-store.md) | Ignite stack: Event Hubs Basic + ADX free cluster | Accepted |
| [0004](0004-agent-overwatch.md) | Agent overwatch: read-only, alerts, staff-only chat | Accepted |
| [0005](0005-booth-dashboard.md) | Booth dashboard: Next.js + TS, EICAS direction, themeable per cloud | Accepted |
| [0006](0006-telemetry-schema-1-1.md) | Schema 1.1: full robot superset (joints, IMU, BMS, feet, gait, edge) | Accepted |

New decisions: copy the template below, take the next number, and add a row.

```markdown
# NNNN Title
Date: YYYY-MM-DD · Status: Proposed | Accepted | Superseded by NNNN
## Context
## Decision
## Consequences
## AWS parity
```
