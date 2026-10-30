"use client";
import { useEffect, useRef, useState } from "react";
import { Telemetry } from "./model";
import { SyntheticSource } from "./synthetic";
import { readLive } from "./live";

const EMPTY: Telemetry = { snapshot: null, series: { soc: [], tempMax: [], tempAvg: [], fps: [], edgeTemp: [], pitch: [], roll: [], joint: {} }, findings: [], postures: [], detections: [], ppeAlerts: 0, commands: [], error: null };

// Source: ?source=synthetic|live. Live needs QUERY_API_URL (build) or ?api=.
// Live never falls back to synthetic on its own: stale stays visibly stale.
export function useTelemetry(): { data: Telemetry; source: "live" | "synthetic" } {
  const [data, setData] = useState<Telemetry>(EMPTY);
  const [source, setSource] = useState<"live" | "synthetic">("synthetic");
  const synth = useRef<SyntheticSource | null>(null);

  useEffect(() => {
    const qs = new URLSearchParams(window.location.search);
    const api = qs.get("api") || process.env.NEXT_PUBLIC_QUERY_API_URL || "";
    const src = qs.get("source") === "live" || (qs.get("source") !== "synthetic" && api) ? "live" : "synthetic";
    setSource(src);
    let stop = false;
    let last: Telemetry = EMPTY;
    const tick = async () => {
      if (src === "synthetic") {
        synth.current ??= new SyntheticSource();
        last = synth.current.read();
      } else {
        try { last = await readLive(api); }
        catch (e) {
          // keep the last snapshot but re-age it so the UI goes invalid; surface the error
          last = { ...last, error: e instanceof Error ? e.message : String(e) };
        }
      }
      if (!stop) setData(last);
    };
    tick();
    const id = setInterval(tick, src === "synthetic" ? 1000 : 2500);
    // Re-age the snapshot every second even between fetches, so staleness is honest.
    const age = setInterval(() => setData((d) => (d.snapshot ? { ...d, snapshot: { ...d.snapshot, ageS: (Date.now() - d.snapshot.t) / 1000 } } : d)), 1000);
    return () => { stop = true; clearInterval(id); clearInterval(age); };
  }, []);
  return { data, source };
}
