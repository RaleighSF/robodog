import type { NextConfig } from "next";

// Static export: the same build hosts on Azure Static Web Apps (Ignite) or
// S3 + CloudFront / Amplify (re:Invent). Cloud is chosen at build time.
const config: NextConfig = {
  output: "export",
  images: { unoptimized: true },
  devIndicators: false,
  env: {
    NEXT_PUBLIC_THEME: process.env.THEME ?? "azure",
    NEXT_PUBLIC_QUERY_API_URL: process.env.QUERY_API_URL ?? "",
  },
};
export default config;
