"use client";
// Watch Dog booth dashboard — EICAS cockpit for a Go2's vitals + agent overwatch.
// ?mode=booth (default): unattended, synoptic pages auto-cycle.
// ?mode=staff: page keys, acknowledge, and the Ask Overwatch field.
import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";
import { Annunciator, CasStack, FreshnessLamp, JointDial } from "@/components/Instruments";
import { PAGES, Page, SynopticPage } from "@/components/Pages";
import { LEGS, LIMITS, Leg } from "@/lib/model";
import { theme } from "@/lib/theme";
import { useTelemetry } from "@/lib/useTelemetry";

const Go2View = dynamic(() => import("@/components/Go2View"), { ssr: false });

const LEG_NAME: Record<Leg, string> = { FL: "Front left", FR: "Front right", RL: "Rear left", RR: "Rear right" };
// Screen placement matches the camera: dog faces left, left legs nearest.
const QUADRANT: Record<Leg, string> = { FR: "q-tl", FL: "q-bl", RR: "q-tr", RL: "q-br" };

export default function Home() {
  const { data, source } = useTelemetry();
  const [mode, setMode] = useState<"booth" | "staff">("booth");
  const [page, setPage] = useState<Page>("POWER");
  const [acked, setAcked] = useState<Set<string>>(new Set());

  useEffect(() => { setMode(new URLSearchParams(window.location.search).get("mode") === "staff" ? "staff" : "booth"); }, []);
  useEffect(() => {
    if (mode !== "booth") return;
    const id = setInterval(() => setPage((p) => PAGES[(PAGES.indexOf(p) + 1) % PAGES.length]), 12000);
    return () => clearInterval(id);
  }, [mode]);

  const s = data.snapshot;
  const stale = !s || s.ageS > LIMITS.staleS || !!(data.error && source === "live");
  const unacked = useMemo(() => data.findings.filter((f) => !acked.has(`${f.id}:${f.severity}`)), [data.findings, acked]);
  const warnLit = !stale && unacked.some((f) => f.severity === "warning");
  const cautionLit = !stale && unacked.some((f) => f.severity === "caution");
  const ack = (sev: "warning" | "caution") => setAcked((a) => new Set([...a, ...data.findings.filter((f) => f.severity === sev).map((f) => `${f.id}:${f.severity}`)]));
  const hot = s?.joints.reduce((m, j) => (j.temp != null && (m == null || j.temp > (m.temp ?? -1)) ? j : m), s?.joints[0]);

  return (
    <main className={`cockpit ${mode}`}>
      <header className="strip">
        <img src="/brand/nttdata.svg" alt="NTT DATA" className="ntt" />
        <div className="ident">
          <h1>Watch Dog <span>Overwatch</span></h1>
          <span className="num ident-sub">UNITREE GO2 · {s?.deviceId ?? "—"}</span>
        </div>
        <div className="annuns">
          <Annunciator kind="warning" lit={warnLit} onAck={mode === "staff" ? () => ack("warning") : undefined} />
          <Annunciator kind="caution" lit={cautionLit} onAck={mode === "staff" ? () => ack("caution") : undefined} />
        </div>
        <FreshnessLamp ageS={s?.ageS ?? null} source={source} error={data.error} />
        <div className="marks"><span>{theme.builtOn}</span><span className="nv">Powered by <b>NVIDIA</b></span></div>
      </header>

      <section className="body panel" aria-label="Robot body and joint motors">
        <div className="horizon" aria-hidden="true" style={{ transform: `rotate(${-(s?.roll ?? 0) * 57.3}deg) translateY(${(s?.pitch ?? 0) * 57.3 * 1.2}px)` }} />
        <Go2View posture={s?.posture ?? "unknown"} walking={!stale && !!s && Math.hypot(...(s.velocity ?? [0, 0])) > 0.05}
          joints={s?.joints ?? []} roll={s?.roll ?? 0} stale={stale} orbit={mode === "booth"} />
        {LEGS.map((leg) => (
          <div key={leg} className={`leg ${QUADRANT[leg]}`}>
            <h3 className="title">{LEG_NAME[leg]}</h3>
            <div className="dials">{(s?.joints ?? []).filter((j) => j.leg === leg).map((j) => <JointDial key={j.name} joint={j} stale={stale} />)}</div>
          </div>
        ))}
        <div className="body-foot">
          <span className="title">Posture</span><b className="num">{stale ? "--" : (s?.posture === "low" ? "sitting" : s?.posture ?? "--").toUpperCase()}</b>
          <span className="title">Hottest</span><b className="num">{stale || !hot?.temp ? "--" : `${hot.name.replace("_", " ")} ${hot.temp.toFixed(0)}°C`}</b>
          <span className="title">Battery</span><b className="num">{stale || s?.battery.soc == null ? "--" : `${s.battery.soc.toFixed(0)}%`}</b>
        </div>
      </section>

      <CasStack findings={data.findings} stale={stale} />

      <section className="synoptic panel" aria-label={`Synoptic page ${page}`}>
        <nav className="keys" aria-label="Synoptic pages">
          {PAGES.map((p) => (
            <button key={p} type="button" className={p === page ? "on" : ""} aria-pressed={p === page}
              onClick={() => setPage(p)} disabled={mode === "booth"}>{p}</button>
          ))}
          {mode === "booth" && <span className="cycle num" key={page} aria-hidden="true" />}
        </nav>
        <div className="page"><SynopticPage page={page} d={data} stale={stale} source={source} /></div>
      </section>

      {mode === "staff" && (
        <form className="ask panel" onSubmit={(e) => e.preventDefault()}>
          <label htmlFor="ask" className="title">Ask overwatch</label>
          <input id="ask" placeholder="e.g. Which joint is running hottest, and why?" disabled aria-describedby="ask-note" />
          <span id="ask-note" className="muted">The agent is not connected yet. It arrives with the Azure AI Foundry deployment.</span>
        </form>
      )}
      <footer className="legal">Go2 model: MuJoCo Menagerie, BSD-3-Clause, © Unitree Robotics. Read-only view; this screen cannot command the robot.</footer>
    </main>
  );
}
