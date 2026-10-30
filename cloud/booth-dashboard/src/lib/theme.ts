// Cloud theme: the ONLY place the cloud brand lives. The chassis and status
// semantics are shared (Azimuth industrial instrument world); the accent and
// partner marks swap per show. THEME is chosen at build (next.config.ts).
export type CloudTheme = "azure" | "aws";

export const THEMES: Record<CloudTheme, { accent: string; accentPress: string; accentInk: string; builtOn: string; cloudName: string; agentHost: string }> = {
  // Azure blue lifted for a dark chassis (passes AA on surface-1); Azure brand is #0078D4.
  azure: { accent: "#3A9BF0", accentPress: "#1F86E0", accentInk: "#06121F", builtOn: "Built on Microsoft Azure", cloudName: "Azure", agentHost: "Azure AI Foundry" },
  // AWS "smile" orange family for re:Invent.
  aws: { accent: "#FF9F1C", accentPress: "#E8890A", accentInk: "#1A0F00", builtOn: "Built on AWS", cloudName: "AWS", agentHost: "Amazon Bedrock" },
};

export const CLOUD: CloudTheme = (process.env.NEXT_PUBLIC_THEME === "aws" ? "aws" : "azure");
export const theme = THEMES[CLOUD];

// Architecture dialog labels: the same data flow, named in each cloud's services
// (cloud/PARITY.md). Text only; no cloud logos until the artwork is approved.
export interface ArchLabels { region: string; ingest: string; compute: string; store: string; agent: string; realtime: string; hosting: string;
  storeNote: string; computeNote: string; identityHead: string; identity: string;
  ingestLink: string; storeLink: string; agentNote: string; agentLink: string; twinLink: string }
export const ARCH: Record<CloudTheme, ArchLabels> = {
  azure: { region: "Microsoft Azure", ingest: "Azure Event Hubs", compute: "Azure Functions", store: "Azure Data Explorer",
    agent: "Azure AI Foundry Agent", realtime: "Azure Web PubSub", hosting: "Azure Static Web Apps",
    storeNote: "KQL tables · update policies · Overwatch rules", computeNote: "stream ingest · read-only query API",
    identityHead: "Keyless by design",
    identity: "Managed identities and Entra ID tokens: no keys in the browser, send-only token at the edge",
    ingestLink: "trigger", storeLink: "streaming ingest · KQL", agentNote: "GPT-4.1 mini · read-only tool",
    agentLink: "OpenAPI tool", twinLink: "joint frames · send-only token" },
  aws: { region: "AWS", ingest: "Amazon Kinesis Data Streams", compute: "AWS Lambda", store: "Amazon DynamoDB",
    agent: "Amazon Bedrock · Claude", realtime: "AWS AppSync Events", hosting: "AWS Amplify Hosting",
    storeNote: "live rows (TTL 24 h) · Overwatch rules", computeNote: "stream ingest · read-only query API",
    identityHead: "Least privilege by design",
    identity: "IAM roles in the cloud and a send-only IAM user at the edge; the browser holds only a subscribe-only key for the live twin",
    ingestLink: "event source mapping", storeLink: "batch writes · queries", agentNote: "Claude Haiku 5.5 · read-only tool",
    agentLink: "read-only tool", twinLink: "joint frames · IAM-signed publish" },
};
export const arch = ARCH[CLOUD];

