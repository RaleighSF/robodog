# 0011 AWS (re:Invent) stack, and the demo profile picks the cloud path
Date: 2026-10-30 · Status: Accepted (amends 0003's AWS column)

## Context
The AWS build has to mirror the Azure one (ADRs 0001–0010) so that the same
dashboard, agent instructions and telemetry run on either cloud. ADR 0003
planned Kinesis → Firehose → S3 + Athena. Athena can't serve a live dashboard:
- each query takes seconds;
- each query bills at least 10 MB scanned;
- the dashboard polls 9 operations every 2.5 s per screen.

## Decision
**Each Azure piece and its AWS counterpart** (`deploy/aws/template.yaml`, one
CloudFormation stack, deployed by `deploy/aws/deploy.sh`):

| Role | Azure | AWS |
|---|---|---|
| Edge sink | Event Hubs | Kinesis Data Streams, 1 provisioned shard, 24 h |
| Ingest | Functions trigger (ADR 0008) | Lambda event source mapping (`cloud/query_api/aws_ingest.py`) |
| Live store and rules | ADX + KQL | DynamoDB (one table, TTL 24 h) + `backends/aws.py` |
| Query API | Functions, keyless GETs | Lambda function URL (`aws_handler.py`), same routes, CORS to the dashboard |
| Agent | Foundry, GPT-4.1 mini | Bedrock, Claude Haiku 5.5 (`global.` profile), same instructions, knowledge and tool |
| Live twin | Web PubSub | AppSync Events: Thor publishes with IAM, browsers subscribe with an API key |
| Hosting | Static Web Apps | Amplify Hosting (manual zip deploys) |
| IaC | Bicep | CloudFormation (no extra tooling) |

**Shared, cloud-neutral code:**
- `backends/rows.py` ports the KQL `Expand*` functions column for column.
- `backends/aws.py` ports every `api` function, `Overwatch_Findings` included.
  A per-joint state item carries the 10-minute trail and the start of the
  current caution or over-limit run, instead of 2 h of history.
- `api_core.py` holds the brief cache, the staff-key check and question limits,
  for both hosts.
- `cloud/contract_tests/compare_clouds.py` checks live column parity.

**The demo profile picks the cloud path.** The Thor's telemetry sinks and
live-twin channels follow the conference UI's demo profile:
- `azure` sends to Azure only;
- `aws` sends to AWS only;
- `default` sends to both.

This is configurable as `telemetry.cloud_routing` and read at most once per
second. Sinks outside the selected path are skipped, not counted as failures.

**Edge identity:** IAM user `watchdog-reinvent-thor-edge` may only call
`kinesis:PutRecord(s)` on the stream and `appsync:EventPublish` on namespace
`motion`. Its key lives in `/state/aws-edge.json`, written from the gitignored
`deploy/aws/secrets/`.

## Consequences
- **Measured on the real dog** (Default profile, both clouds at once):
  - AWS vitals 3 s old against Azure's 4 s;
  - all 11 operations that return data on both clouds have identical columns;
  - the AWS agent's first brief took about 15 s (cold start), then it is cached.
- **Cost (rough):** about $11/month for the Kinesis shard, plus pennies for
  Lambda, DynamoDB and AppSync, plus Bedrock Haiku at a few cents per booth day.
- **Archive:** there is no S3/Athena history yet. Add Firehose from the same
  stream if analytics are needed.
- **AppSync API key:** it can only subscribe, and it is handed to browsers like
  the Azure receive-only token. It expires 180 days after each deploy.
- **Minor parity gap:** ADX's "minutes in caution" is bounded by a 2 h window,
  while AWS counts from the true start of the run.

## AWS parity
This ADR is the AWS build. A later Azure change must update `backends/aws.py`
and `rows.py` in the same commit, and `compare_clouds.py` must still pass.
