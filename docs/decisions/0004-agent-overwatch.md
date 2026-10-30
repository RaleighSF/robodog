# 0004 Agent overwatch: read-only, alerts, staff-only chat
Date: 2026-10-28 · Status: Accepted

## Context
The booth story needs an agent that "observes and interacts with" the robot's data. The
robot's safety model (Orin drive permits, single local controller) forbids cloud control.

## Decision
- The agent's only tool is the query API (ADR 0002), imported as OpenAPI.
- It never commands the robot.
- It posts findings to a visible feed on its own, driven by `Overwatch_Findings`.
- Only demo staff type questions; visitors do not chat freely at a public booth.
- It cites the telemetry it used.
- Ignite: Azure AI Foundry Agent Service, model to be chosen after pricing is confirmed
  (new LLM cost, flagged).

## Consequences
The agent's prompt and tool spec are cloud-neutral files (`cloud/agent/`). Alert
thresholds are placeholders until calibrated on the real dog.

## AWS parity
Amazon Bedrock agent (or AgentCore) with the same instructions file and the same OpenAPI
tool pointed at the AWS query API.
