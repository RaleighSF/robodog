# Cloud parity: Ignite (Azure) → re:Invent (AWS)

The Azure build is the **reference implementation**. The AWS build is produced from this
file, the decision log (`docs/decisions/`) and the shared contracts below. It must pass
the same contract tests. Nothing in the dashboard, agent instructions or telemetry schema
may be cloud-specific.

## Shared contracts (cloud-neutral, used by both builds unchanged)

| Contract | Source of truth |
|---|---|
| Telemetry events (schema 1.1) | `TELEMETRY_SCHEMA.md`, `telemetry_exporter.py` |
| Query API operations, parameters and row shapes | `cloud/query_api/backends/__init__.py` (`OPERATIONS`) + `cloud/query_api/openapi.yaml` |
| Derived-table semantics (Heartbeats, Vitals, Motors, Detections, Commands, Alerts) | `deploy/azure/adx/setup.kql`. The AWS views must produce the same columns. |
| Overwatch findings rules and thresholds | `Overwatch_Findings` in `setup.kql` (thresholds are placeholders, ADR 0004) |
| Agent instructions + tool | `cloud/agent/` (instructions + OpenAPI tool; one copy for both clouds) |
| Booth dashboard | `cloud/booth-dashboard/` (one app; `THEME` + `QUERY_API_URL` at build) |
| Sample data | `deploy/azure/tools/sample_events.py` (device `watchdog-sample`) |
| Contract tests | `cloud/contract_tests/`: same sample in, same expected rows out, per cloud |

## Component map

| Role | Azure (Ignite), built | AWS (re:Invent), planned; verify availability at build time |
|---|---|---|
| Edge sink | `azure_eventhub` (`EventHubExporter`) | `aws_kinesis` sink, same JSON |
| Ingest | Event Hubs Basic `watchdog-ignite-28628191/watchdog-telemetry` → `telemetry_ingest` Function (ADR 0008) | Kinesis Data Streams (on-demand) |
| Store and analytics | ADX free cluster, KQL update policies + functions | Firehose → S3 (Parquet) + Athena views mirroring the tables/functions |
| Query API host | Azure Functions (Python), `cloud/query_api` | Lambda (Python) behind a function URL or API Gateway, same handler |
| Agent | Azure AI Foundry agent + OpenAPI tool | Amazon Bedrock agent / AgentCore + the same OpenAPI tool |
| Live motion channel | Web PubSub `wd-motion-28628191` (hub `motion`, keys off) + `motion/negotiate` | API Gateway WebSockets or IoT Core + same negotiate contract |
| Agent knowledge | `cloud/agent/knowledge/go2_health.md` appended to instructions | Same file in the Bedrock agent instructions |
| Dashboard hosting | Azure Static Web Apps | Amplify Hosting or S3 + CloudFront |
| Infrastructure as code | `deploy/azure/main.bicep` + `deploy.sh` | `deploy/aws/` (CDK or CloudFormation), same parameters |
| Secrets on the Thor | `/state/eventhub.conn` (send-only SAS) | `/state/aws-telemetry.env` (IAM user/role limited to `kinesis:PutRecord*`) |
| Theme | `THEME=azure`: Azure-blue accent, "Built on Microsoft Azure" | `THEME=aws`: AWS orange accent, AWS marks per approval |

## How the AWS build is produced

1. Read this file and ADRs 0001–0006 (and later ones). Each ADR's **AWS parity** section
   lists that decision's AWS obligations.
2. Implement `aws_kinesis` (edge), `deploy/aws/` (infrastructure) and
   `backends/aws.py` (queries) against the shared contracts. Do not edit the
   contracts to fit AWS. If a contract cannot be met, record a new ADR first.
3. Load `sample_events.py` output and run `cloud/contract_tests` against the AWS query
   API. AWS is done when the results match Azure's.
4. Build the dashboard with `THEME=aws` and the AWS API URL. Point the Bedrock agent at
   the same instructions and OpenAPI file.

## Log

- 2026-10-28: Edge sinks, ADX schema, query API (ADX backend), schema 1.1.
- 2026-10-30: Azure subscription live; Event Hubs deployed (rg-watchdog-ignite,
  southcentralus); EICAS dashboard direction chosen.
- 2026-10-30: Live path working end to end: Thor → Event Hubs → Function ingest → ADX →
  query API → dashboard and Foundry agent (ADR 0008).
- 2026-10-30: Lidar window check (ADR 0009); live motion mirror + maneuvers (ADR 0010);
  agent grounded on a cited Go2 health knowledge base.
