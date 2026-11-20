// Cloud theme: the ONLY place the cloud brand lives. The chassis and status
// semantics are shared (Azimuth industrial instrument world); the accent and
// partner marks swap per show. THEME is chosen at build (next.config.ts).
export type CloudTheme = "azure" | "aws";

// Each build ships ONE cloud. NEXT_PUBLIC_THEME is inlined as a literal, so
// every `IS_AWS ? aws : azure` below folds at minify time and the other cloud's
// names and code never reach the bundle (no tell that the demo runs on both).
// Keep cloud-specific values behind these ternaries, never in a lookup table.
export const IS_AWS = process.env.NEXT_PUBLIC_THEME === "aws";
export const CLOUD: CloudTheme = IS_AWS ? "aws" : "azure";

type Theme = { accent: string; accentPress: string; accentInk: string; builtOn: string; cloudName: string; agentHost: string; nttLogo: string };
export const theme: Theme = IS_AWS
  // AWS "smile" orange family for re:Invent.
  ? { accent: "#FF9F1C", accentPress: "#E8890A", accentInk: "#1A0F00", builtOn: "Built on AWS", cloudName: "AWS", agentHost: "Amazon Bedrock",
    // Updated NTT DATA mark (emblem + wordmark), AWS build only for now.
    nttLogo: "/brand/nttdata-emblem.svg" }
  // Azure blue lifted for a dark chassis (passes AA on surface-1); Azure brand is #0078D4.
  : { accent: "#3A9BF0", accentPress: "#1F86E0", accentInk: "#06121F", builtOn: "Built on Microsoft Azure", cloudName: "Azure", agentHost: "Azure AI Foundry", nttLogo: "/brand/nttdata.svg" };

// Architecture dialog labels: the same data flow, named in each cloud's services
// (cloud/PARITY.md). Text only; no cloud logos until the artwork is approved.
export interface ArchLabels { region: string; ingest: string; compute: string; store: string; agent: string; realtime: string; hosting: string;
  storeNote: string; computeNote: string; identityHead: string; identity: string;
  ingestLink: string; storeLink: string; agentNote: string; agentLink: string; twinLink: string }
export const arch: ArchLabels = IS_AWS ? { region: "AWS", ingest: "Amazon Kinesis Data Streams", compute: "AWS Lambda", store: "Amazon DynamoDB",
    agent: "Amazon Bedrock · Claude", realtime: "AWS AppSync Events", hosting: "AWS Amplify Hosting",
    storeNote: "live rows (TTL 24 h) · Overwatch rules", computeNote: "stream ingest · read-only query API",
    identityHead: "Least privilege by design",
    identity: "IAM roles in the cloud and a send-only IAM user at the edge; the browser holds only a subscribe-only key for the live twin",
    ingestLink: "event source mapping", storeLink: "batch writes · queries", agentNote: "Claude Haiku 5.5 · read-only tool",
    agentLink: "read-only tool", twinLink: "joint frames · IAM-signed publish" }
  : { region: "Microsoft Azure", ingest: "Azure Event Hubs", compute: "Azure Functions", store: "Azure Data Explorer",
    agent: "Azure AI Foundry Agent", realtime: "Azure Web PubSub", hosting: "Azure Static Web Apps",
    storeNote: "KQL tables · update policies · Overwatch rules", computeNote: "stream ingest · read-only query API",
    identityHead: "Keyless by design",
    identity: "Managed identities and Entra ID tokens: no keys in the browser, send-only token at the edge",
    ingestLink: "trigger", storeLink: "streaming ingest · KQL", agentNote: "GPT-4.1 mini · read-only tool",
    agentLink: "OpenAPI tool", twinLink: "joint frames · send-only token" };


// Edge plane (AWS build only): AWS IoT Greengrass on the Thor publishing over MQTT
// to AWS IoT Core, whose rules feed the same stream and live-twin channel. This is
// the edge ROADMAP, not today's path (today the Thor publishes straight to the
// stream and the realtime channel), so the dialog marks both nodes and says so.
// null on other builds: the names fold out of the bundle with the ternary.
export interface EdgePlane { runtime: string; runtimeNote: string; broker: string; brokerNote: string; tag: string;
  localLink: string; uplink: string; streamRule: string; twinRule: string; agentLink: string;
  legendHead: string; legend: string[]; aria: string }
export const edgePlane: EdgePlane | null = IS_AWS ? { runtime: "AWS IoT Greengrass", runtimeNote: "edge runtime · store and forward",
    broker: "AWS IoT Core", brokerNote: "MQTT broker · rules engine", tag: "Roadmap",
    localLink: "local IPC", uplink: "MQTT · X.509 device certificate", streamRule: "IoT rule · telemetry", twinRule: "IoT rule",
    agentLink: "read-only",
    legendHead: "Edge roadmap",
    legend: ["Greengrass and IoT Core are the", "managed edge plane we are building", "toward. Today the Thor publishes", "direct to Kinesis and AppSync."],
    aria: "On the edge roadmap, AWS IoT Greengrass on the Thor publishes over MQTT to AWS IoT Core, whose rules feed the stream and the live twin; today the Thor publishes to them directly." }
  : null;
