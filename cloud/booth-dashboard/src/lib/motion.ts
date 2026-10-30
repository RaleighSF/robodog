// Live motion mirror (ADR 0010): joint frames pushed from the edge over the
// cloud real-time channel. The query API hands out a short-lived receive-only
// URL (GET motion/negotiate); the same {url, protocol} contract on every cloud.
"use client";
import { useEffect, useRef, useState } from "react";

export interface MotionFrame { t: number; q: number[]; rpy: number[] | null; h: number | null }
export interface Maneuver { name: string; t: number; paw?: string; posture_from?: string; posture_to?: string }

const PLAYBACK_DELAY_S = 0.25;      // jitter buffer: render this far behind the newest frame
const FRESH_S = 1.0;                // no frame for this long = mirror off (fall back to vitals)
const RENEW_MS = 45 * 60_000;       // reconnect with a fresh token before the 60 min one lapses
export const MANEUVER_SHOW_MS = 6000;  // a maneuver badge shows for this long after the event

/** Mutable feed read by the 3D render loop (no React re-render per frame). */
export class MotionFeed {
  private frames: MotionFrame[] = [];
  private offset: number | null = null;     // browser clock minus robot clock (min seen, s)
  lastRecv = 0;

  /** Robot-clock time (s) as browser epoch ms, once the clock offset is known. */
  toLocalMs(t: number): number | null { return this.offset == null ? null : (t + this.offset) * 1000; }

  push(frames: MotionFrame[]) {
    const now = Date.now() / 1000;
    for (const f of frames) {
      if (!Array.isArray(f.q) || f.q.length !== 12) continue;
      const off = now - f.t;
      this.offset = this.offset == null ? off : Math.min(this.offset, off);
      this.frames.push(f);
    }
    if (this.frames.length > 120) this.frames.splice(0, this.frames.length - 120);
    this.lastRecv = Date.now();
  }

  live(): boolean { return Date.now() - this.lastRecv < FRESH_S * 1000 && this.frames.length > 1; }

  /** Joint angles interpolated at (now - offset - delay) on the robot's clock. */
  sample(): MotionFrame | null {
    if (!this.live() || this.offset == null) return null;
    const t = Date.now() / 1000 - this.offset - PLAYBACK_DELAY_S;
    const fs = this.frames;
    if (t <= fs[0].t) return fs[0];
    for (let i = fs.length - 1; i > 0; i--) {
      const a = fs[i - 1], b = fs[i];
      if (a.t <= t && t <= b.t) {
        const k = (t - a.t) / Math.max(b.t - a.t, 1e-3);
        return { t, q: a.q.map((v, j) => v + (b.q[j] - v) * k), rpy: b.rpy, h: b.h };
      }
    }
    return fs[fs.length - 1];
  }
}

export function useMotion(api: string, enabled: boolean): { feed: MotionFeed; maneuver: Maneuver | null; live: boolean } {
  const feed = useRef(new MotionFeed()).current;
  const [maneuver, setManeuver] = useState<Maneuver | null>(null);
  const [live, setLive] = useState(false);

  useEffect(() => {
    if (!enabled || !api) return;
    let ws: WebSocket | null = null, stop = false, renew: ReturnType<typeof setTimeout> | undefined, retry: ReturnType<typeof setTimeout> | undefined;
    const connect = async () => {
      try {
        const r = await fetch(`${api.replace(/\/$/, "")}/motion/negotiate`, { cache: "no-store" });
        if (!r.ok) throw new Error(String(r.status));
        const { url, protocol } = (await r.json()) as { url: string; protocol: string };
        if (stop) return;
        const sock = new WebSocket(url, protocol);
        ws = sock;
        sock.onmessage = (ev) => {
          let m: { type?: string; data?: { frames?: MotionFrame[]; maneuvers?: Maneuver[] } };
          try { m = JSON.parse(String(ev.data)); } catch { return; }
          if (m.type !== "message" || !m.data) return;
          feed.push(m.data.frames ?? []);
          // Keep each maneuver's real time (robot clock); ignore any that are already old.
          const mans = m.data.maneuvers ?? [];
          const last = mans[mans.length - 1];
          const at = last ? feed.toLocalMs(last.t) : null;
          if (last && at != null && Date.now() - at < MANEUVER_SHOW_MS) setManeuver({ ...last, t: at });
        };
        sock.onclose = () => { clearTimeout(renew); if (!stop) retry = setTimeout(connect, 3000); };
        renew = setTimeout(() => sock.close(), RENEW_MS);   // renew this socket only
      } catch {
        if (!stop) retry = setTimeout(connect, 5000);
      }
    };
    connect();
    const tick = setInterval(() => setLive(feed.live()), 500);
    return () => { stop = true; clearTimeout(renew); clearTimeout(retry); clearInterval(tick); ws?.close(); };
  }, [api, enabled, feed]);

  return { feed, maneuver, live };
}

export const MANEUVER_LABEL: Record<string, string> = { hello: "HELLO", sit: "SIT", stand_up: "STAND UP", lie_down: "LIE DOWN" };
