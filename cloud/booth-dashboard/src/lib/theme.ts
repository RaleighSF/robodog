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
