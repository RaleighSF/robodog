"use client";
// Watch Dog booth dashboard — EICAS cockpit for a Go2's vitals + agent overwatch.
// ?mode=booth (default): unattended, synoptic pages auto-cycle.
// ?mode=staff: page keys, acknowledge, and the Ask Overwatch field.
import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";
import { AskOverwatch } from "@/components/Ask";
import { Annunciator, CasStack, FreshnessLamp, JointDial } from "@/components/Instruments";
import { PAGES, Page, SynopticPage } from "@/components/Pages";
import { useBrief } from "@/lib/agent";
import { MANEUVER_LABEL, useMotion } from "@/lib/motion";
import { LEGS, LIMITS, Leg, Snapshot, jointState } from "@/lib/model";
import { theme } from "@/lib/theme";
import { useTelemetry } from "@/lib/useTelemetry";

const Go2View = dynamic(() => import("@/components/Go2View"), { ssr: false });

/** Bank scale (fixed) + roll pointer and horizon (move with the IMU), behind the dog. */
function AttitudeRing({ roll, pitch, invalid }: { roll: number; pitch: number; invalid: boolean }) {
  const deg = roll * 57.3, R = 100;
  const tick = (a: number, len: number) => { const t = ((a - 90) * Math.PI) / 180; return <line key={a} x1={100 + R * Math.cos(t)} y1={100 + R * Math.sin(t)} x2={100 + (R - len) * Math.cos(t)} y2={100 + (R - len) * Math.sin(t)} />; };
  return (
    <svg className="att-ring" viewBox="-4 -4 208 208" aria-hidden="true">
      <defs><clipPath id="ring-clip"><circle cx="100" cy="100" r={R} /></clipPath></defs>
      <circle cx="100" cy="100" r={R} className="ring" />
      <g className="bank">{[-30, -20, -10, 10, 20, 30].map((a) => tick(a, Math.abs(a) === 30 ? 9 : 6))}{tick(0, 11)}</g>
      <g clipPath="url(#ring-clip)" style={{ transform: `rotate(${-deg}deg)`, transformOrigin: "100px 100px", transition: "transform 600ms var(--ease-out)" }}>
        <line x1="-20" x2="220" y1={100 + pitch * 57.3 * 1.4} y2={100 + pitch * 57.3 * 1.4} className={`hz ${invalid ? "invalid" : ""}`} />
        <path d="M100 4 L95 13 L105 13 Z" className={`ptr ${invalid ? "invalid" : ""}`} />
      </g>
    </svg>
  );
}

const LEG_NAME: Record<Leg, string> = { FL: "Front left", FR: "Front right", RL: "Rear left", RR: "Rear right" };
// Screen placement matches the camera: dog faces left, left legs nearest.
const QUADRANT: Record<"left" | "right", Record<Leg, string>> = {
  left: { FR: "q-tl", FL: "q-bl", RR: "q-tr", RL: "q-br" },     // nose left, left legs nearest
  right: { FR: "q-br", FL: "q-tr", RR: "q-bl", RL: "q-tl" },    // turned: nose right, right legs nearest
};
const SEV_RANK = { warning: 2, caution: 1, ok: 0, unknown: 0 } as const;

/** Show the side of the most severe flagged joint (left by default), so a hot
 *  joint is never hidden behind the body. */
function viewSide(s: Snapshot | null | undefined, stale: boolean): "left" | "right" {
  if (!s || stale) return "left";
  let best: { rank: number; side: "left" | "right" } = { rank: 0, side: "left" };
  for (const j of s.joints) {
    const rank = SEV_RANK[jointState(j.temp)];
    if (rank > best.rank) best = { rank, side: j.leg.endsWith("R") ? "right" : "left" };
  }
  return best.side;
}

export default function Home() {
  const { data, source, api } = useTelemetry();
  const brief = useBrief(api, source === "live");
  const motion = useMotion(api, source === "live");
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(id); }, []);
  const recent = motion.maneuver && now - motion.maneuver.t < 6000 ? motion.maneuver : null;
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
  const side = viewSide(s, stale);
  const unacked = useMemo(() => data.findings.filter((f) => !acked.has(`${f.id}:${f.severity}`)), [data.findings, acked]);
  const warnLit = !stale && unacked.some((f) => f.severity === "warning");
  const cautionLit = !stale && unacked.some((f) => f.severity === "caution");
  const ack = (sev: "warning" | "caution") => setAcked((a) => new Set([...a, ...data.findings.filter((f) => f.severity === sev).map((f) => `${f.id}:${f.severity}`)]));

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
        <div className="stage">
          <AttitudeRing roll={stale ? 0 : s?.roll ?? 0} pitch={stale ? 0 : s?.pitch ?? 0} invalid={stale} />
          <Go2View posture={s?.posture ?? "unknown"} walking={!stale && !!s && Math.hypot(...(s.velocity ?? [0, 0])) > 0.05}
            joints={s?.joints ?? []} roll={s?.roll ?? 0} pitch={s?.pitch ?? 0} side={side} stale={stale} orbit={mode === "booth"} motion={motion.feed} />
        </div>
        {source === "live" && (
          <div className={`mirror ${motion.live ? "on" : ""}`} aria-live="polite">
            <span className="mirror-lamp" aria-hidden="true" />
            <span className="title">{motion.live ? "Live twin" : "Twin · posture only"}</span>
            {recent && <b className="maneuver" key={recent.t}>{MANEUVER_LABEL[recent.name] ?? recent.name.toUpperCase()}{recent.paw ? <small> · {recent.paw} paw</small> : null}</b>}
          </div>
        )}
        {LEGS.map((leg) => (
          <div key={`${leg}-${side}`} className={`leg ${QUADRANT[side][leg]}`}>
            <h3 className="title">{LEG_NAME[leg]}</h3>
            <div className="dials">{(s?.joints ?? []).filter((j) => j.leg === leg).map((j) => <JointDial key={j.name} joint={j} stale={stale} />)}</div>
          </div>
        ))}
      </section>

      <CasStack findings={data.findings} stale={stale} snapshot={s ?? null} socSeries={data.series.soc} brief={brief} detail={mode === "staff"} />

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

      {mode === "staff" && <AskOverwatch api={api} live={source === "live"} />}
      <footer className="legal">Go2 model: MuJoCo Menagerie, BSD-3-Clause, © Unitree Robotics. Read-only view; this screen cannot command the robot.</footer>
    </main>
  );
}
