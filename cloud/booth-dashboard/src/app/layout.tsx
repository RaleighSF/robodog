import type { Metadata } from "next";
import { Chakra_Petch, IBM_Plex_Sans, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { theme } from "@/lib/theme";

// Faces pinned by the Azimuth design system (brief-pinned): Chakra Petch for
// panel titles, IBM Plex Sans for interface text, JetBrains Mono for numbers.
// next/font self-hosts them at build time, so the booth needs no font CDN.
const chakra = Chakra_Petch({ subsets: ["latin"], weight: ["500", "600", "700"], variable: "--font-chakra" });
const plex = IBM_Plex_Sans({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-plex" });
const mono = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "500", "700"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: `Watch Dog · Overwatch · ${theme.cloudName}`,
  description: "Live vitals and agent overwatch for a Unitree Go2 robot dog.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${chakra.variable} ${plex.variable} ${mono.variable}`}
      style={{ ["--accent" as string]: theme.accent, ["--accent-press" as string]: theme.accentPress, ["--accent-ink" as string]: theme.accentInk }}>
      <body>{children}</body>
    </html>
  );
}
