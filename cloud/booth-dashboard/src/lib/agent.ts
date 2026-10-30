// Agent overwatch client (ADR 0004). Same two routes on every cloud:
// GET agent/brief (cached server-side, safe to poll) and staff-only POST agent/ask.
"use client";
import { useEffect, useState } from "react";

export interface Brief { text: string; at: number; ageS: number }

const BRIEF_POLL_MS = 60_000;          // the server caches the brief for 60 s
const KEY_STORE = "watchdog.staffKey";

export function useBrief(api: string, enabled: boolean): Brief | null {
  const [brief, setBrief] = useState<Brief | null>(null);
  useEffect(() => {
    if (!enabled || !api) return;
    let stop = false;
    const load = async () => {
      try {
        const r = await fetch(`${api.replace(/\/$/, "")}/agent/brief`, { cache: "no-store" });
        if (!r.ok) throw new Error(String(r.status));
        const b = (await r.json()) as { text: string; at: number; age_s: number };
        if (!stop) setBrief({ text: b.text, at: b.at * 1000, ageS: b.age_s });
      } catch {
        if (!stop) setBrief(null);       // no brief beats a stale one presented as current
      }
    };
    load();
    const id = setInterval(load, BRIEF_POLL_MS);
    return () => { stop = true; clearInterval(id); };
  }, [api, enabled]);
  return brief;
}

// The passcode is a per-browser staff convenience, so localStorage is fine;
// it can be unavailable (private window), so every access is guarded.
export function loadStaffKey(): string {
  try { return localStorage.getItem(KEY_STORE) ?? ""; } catch { return ""; }
}
export function saveStaffKey(k: string) {
  try { if (k) localStorage.setItem(KEY_STORE, k); else localStorage.removeItem(KEY_STORE); } catch { /* not persisted */ }
}

export type AskResult = { ok: true; text: string; seconds: number } | { ok: false; status: number; message: string };

export async function askOverwatch(api: string, key: string, question: string): Promise<AskResult> {
  try {
    const r = await fetch(`${api.replace(/\/$/, "")}/agent/ask`, {
      method: "POST", headers: { "content-type": "application/json", "x-staff-key": key },
      body: JSON.stringify({ question }),
    });
    const body = (await r.json().catch(() => ({}))) as { text?: string; seconds?: number; error?: string };
    if (!r.ok) return { ok: false, status: r.status, message: body.error ?? `HTTP ${r.status}` };
    return { ok: true, text: body.text ?? "", seconds: body.seconds ?? 0 };
  } catch (e) {
    return { ok: false, status: 0, message: e instanceof Error ? e.message : String(e) };
  }
}
