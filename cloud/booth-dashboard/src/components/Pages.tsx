"use client";
// Synoptic pages (EICAS): every vital not on the main display.
import { LIMITS, Posture, Telemetry } from "@/lib/model";
import { TrendTape } from "./Instruments";

export const PAGES = ["POWER", "GAIT", "ATTITUDE", "VISION", "EDGE", "LINK"] as const;
export type Page = (typeof PAGES)[number];

const f = (v: number | null | undefined, d = 0, unit = "") => (v == null || !Number.isFinite(v) ? "--" : `${v.toFixed(d)}${unit}`);

function Readout({ label, value, unit, state }: { label: string; value: string; unit?: string; state?: "ok" | "caution" | "warning" | "invalid" }) {
  return (
    <div className="ro">
      <span className="title">{label}</span>
      <span className={`num ro-v ${value === "--" ? "invalid" : state ?? ""}`}>{value}{unit && value !== "--" && <small>{unit}</small>}</span>
    </div>
  );
}

function Power({ d, stale }: { d: Telemetry; stale: boolean }) {
  const s = d.snapshot!;
  const b = s.battery;
  const series = d.series.soc;
  const cells = stale ? [] : b.cellV;
  const cmin = cells.length ? Math.min(...cells) : null, cmax = cells.length ? Math.max(...cells) : null;
  const spreadMv = cmin != null ? (cmax! - cmin) * 1000 : null;
  const imbalanced = spreadMv != null && spreadMv > LIMITS.cellImbalanceMv;
  return (
    <div className="pg pg-power">
      <div className="cells">
        <span className="title">Cells · {cells.length || "--"}S</span>
        <div className="cell-bars" role="img" aria-label="Cell voltages">
          {cells.map((v, i) => (
            <div key={i} className="cell"><i style={{ height: `${Math.max(4, ((v - 3.3) / 0.9) * 100)}%` }} className={imbalanced && v === cmin ? "low" : "ok"} /><span className="num">{v.toFixed(2)}</span></div>
          ))}
        </div>
        <span className={`num cell-delta ${imbalanced ? "caution" : ""}`}>Δ {spreadMv != null ? spreadMv.toFixed(0) : "--"}{"\u00a0"}mV{imbalanced ? " · imbalance" : " · balanced"}</span>
      </div>
      <div className="ro-grid">
        <Readout label="Pack" value={stale ? "--" : f(b.packV, 1)} unit=" V" />
        <Readout label="Current" value={stale ? "--" : f(b.packA, 1)} unit=" A" />
        <Readout label="Cycles" value={stale ? "--" : f(b.cycles)} />
        <Readout label="BMS max" value={stale ? "--" : f(b.bmsTemps.length ? Math.max(...b.bmsTemps) : null, 0)} unit=" °C" />
        <Readout label="Board" value={stale ? "--" : f(b.boardTemps.length ? Math.max(...b.boardTemps) : null, 0)} unit=" °C" />
      </div>
      <TrendTape label="State of charge" unit="%" data={series} min={0} max={100} limits={[{ v: LIMITS.batteryCaution, kind: "caution" }, { v: LIMITS.batteryWarning, kind: "warning" }]} />
    </div>
  );
}

function Gait({ d, stale }: { d: Telemetry; stale: boolean }) {
  const s = d.snapshot!;
  // Go2 publishes foot_force in FR, FL, RR, RL order.
  const feet: Record<string, number> = { FR: s.footForce[0] ?? 0, FL: s.footForce[1] ?? 0, RR: s.footForce[2] ?? 0, RL: s.footForce[3] ?? 0 };
  const pos: Record<string, [number, number]> = { FL: [62, 42], FR: [138, 42], RL: [62, 158], RR: [138, 158] };
  const obs = s.obstacles;
  const sector = (i: number, r: number) => {
    const a0 = [-135, -45, 45, 135][i] - 35, a1 = a0 + 70, R = 40 + Math.min(r, 3) * 22;
    const p = (a: number) => [100 + R * Math.cos((a * Math.PI) / 180), 100 + R * Math.sin((a * Math.PI) / 180)];
    const [x0, y0] = p(a0), [x1, y1] = p(a1);
    return <path key={i} d={`M ${x0} ${y0} A ${R} ${R} 0 0 1 ${x1} ${y1}`} stroke={r < 0.6 ? "var(--status-warn)" : "var(--border-strong)"} strokeWidth={r < 0.6 ? 3 : 1.5} fill="none" />;
  };
  return (
    <div className="pg pg-gait">
      <svg viewBox="0 0 200 200" className="topview" role="img" aria-label="Top view: foot contact forces and obstacle ranges">
        {obs.slice(0, 4).map((r, i) => sector(i, r))}
        <rect x={72} y={46} width={56} height={108} rx={6} fill="var(--surface-2)" stroke="var(--border-strong)" />
        <path d="M100 52 L94 62 L106 62 Z" fill="var(--text-secondary)" />
        {Object.entries(pos).map(([leg, [x, y]]) => {
          const fN = stale ? 0 : feet[leg];
          const h = Math.min(fN / 120, 1) * 30;
          return (
            <g key={leg}>
              <rect x={x - 9} y={y - 15} width={18} height={30} fill="var(--surface-inset)" stroke="var(--border)" />
              <rect x={x - 9} y={y + 15 - h} width={18} height={h} fill={fN > 4 ? "var(--status-ok)" : "transparent"} opacity={0.8} />
              <text x={x} y={y + 28} textAnchor="middle" className="svg-label">{leg}</text>
            </g>
          );
        })}
      </svg>
      <div className="ro-grid">
        <Readout label="Speed" value={stale ? "--" : f(s.velocity ? Math.hypot(...s.velocity) : null, 2)} unit=" m/s" />
        <Readout label="Yaw rate" value={stale ? "--" : f(s.yawSpeed, 2)} unit=" rad/s" />
        <Readout label="Gait" value={s.gaitType == null ? "--" : s.gaitType === 0 ? "IDLE" : `TROT ${s.gaitType}`} />
        <Readout label="Body" value={stale ? "--" : f(s.bodyHeight, 2)} unit=" m" />
        <Readout label="Nearest" value={stale ? "--" : f(obs.length ? Math.min(...obs) : null, 2)} unit=" m" state={obs.length && Math.min(...obs) < 0.6 ? "caution" : undefined} />
        <Readout label="Feet down" value={stale ? "--" : String(Object.values(feet).filter((x) => x > 4).length)} unit="/4" />
      </div>
    </div>
  );
}

function Silhouette({ posture }: { posture: Posture }) {
  // Authored side-view glyphs on one shared baseline (same scale in every cell).
  const paths: Record<Posture, string> = {
    standing: "M6 14 L30 14 L33 10 L37 10 M10 14 L8 24 M12 14 L14 24 M26 14 L24 24 M28 14 L30 24",
    low: "M6 18 L28 12 L31 8 L35 8 M10 18 L6 24 L12 24 M26 14 L24 24 M28 14 L30 24",
    lying: "M4 21 L32 21 L35 18 L38 18 M6 21 L14 24 M24 21 L32 24",
    unknown: "M8 16 L30 16",
  };
  return <svg viewBox="0 0 40 26" className="sil" aria-hidden="true"><line x1="0" y1="25" x2="40" y2="25" stroke="var(--border)" /><path d={paths[posture]} fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

function Attitude({ d, stale }: { d: Telemetry; stale: boolean }) {
  const s = d.snapshot!;
  const roll = stale ? 0 : s.roll ?? 0, pitch = stale ? 0 : s.pitch ?? 0;
  const deg = (r: number) => (r * 180) / Math.PI;
  const recent = d.postures.slice(-8);
  return (
    <div className="pg pg-att">
      <svg viewBox="0 0 160 160" className="adi" role="img" aria-label={`Attitude: roll ${deg(roll).toFixed(1)} degrees, pitch ${deg(pitch).toFixed(1)} degrees`}>
        <defs><clipPath id="adi-clip"><circle cx="80" cy="80" r="70" /></clipPath></defs>
        <g clipPath="url(#adi-clip)">
          <g transform={`rotate(${-deg(roll)} 80 80) translate(0 ${deg(pitch) * 2})`} style={{ transition: "transform 500ms var(--ease-out)" }}>
            <rect x={-80} y={-160} width={320} height={240} fill="#13283F" />
            <rect x={-80} y={80} width={320} height={240} fill="#2A2118" />
            <line x1={-80} x2={240} y1={80} y2={80} stroke="var(--text-primary)" strokeWidth={1.5} />
            {[-20, -10, 10, 20].map((p) => <g key={p}><line x1={66} x2={94} y1={80 - p * 2} y2={80 - p * 2} stroke="var(--text-secondary)" /><text x={98} y={84 - p * 2} className="svg-label">{Math.abs(p)}</text></g>)}
          </g>
        </g>
        <circle cx="80" cy="80" r="70" fill="none" stroke="var(--border-strong)" />
        <path d="M50 80 L70 80 L74 86 M110 80 L90 80 L86 86" stroke="var(--status-warn)" strokeWidth={3} fill="none" />
        <circle cx="80" cy="80" r="2.5" fill="var(--status-warn)" />
        {stale && <text x="80" y="84" textAnchor="middle" className="svg-invalid">ATT FAIL</text>}
      </svg>
      <div className="att-side">
        <div className="ro-grid two">
          <Readout label="Roll" value={stale ? "--" : f(deg(roll), 1)} unit="°" state={Math.abs(roll) > LIMITS.tiltWarning ? "warning" : undefined} />
          <Readout label="Pitch" value={stale ? "--" : f(deg(pitch), 1)} unit="°" state={Math.abs(pitch) > LIMITS.tiltWarning ? "warning" : undefined} />
          <Readout label="IMU temp" value={stale ? "--" : f(s.imuTemp, 0)} unit=" °C" />
          <Readout label="Posture" value={stale ? "--" : s.posture.toUpperCase()} />
        </div>
        <div className="sil-strip" aria-label="Posture history">
          <span className="title">Posture history</span>
          <ol>{recent.map((p) => <li key={p.t}><Silhouette posture={p.posture} /><time className="num">{new Date(p.t).toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit" })}</time></li>)}</ol>
        </div>
      </div>
    </div>
  );
}

function Vision({ d }: { d: Telemetry }) {
  const max = Math.max(1, ...d.detections.map((x) => x.count));
  return (
    <div className="pg pg-vision">
      <div className="det">
        <span className="title">Detections · last hour</span>
        {d.detections.length === 0 && <p className="muted">Nothing detected in the last hour.</p>}
        {d.detections.map((x) => (
          <div key={x.className} className="det-row"><span>{x.className}</span><i style={{ width: `${(x.count / max) * 100}%` }} /><span className="num">{x.count}</span><span className="num muted">{(x.avgConfidence * 100).toFixed(0)}%</span></div>
        ))}
      </div>
      <div className="ro-grid">
        <Readout label="PPE alerts" value={String(d.ppeAlerts)} state={d.ppeAlerts > 0 ? "caution" : undefined} />
        <Readout label="Detector" value={f(d.snapshot!.edge.fps, 1)} unit=" fps" />
      </div>
      <div className="cmds">
        <span className="title">Commands</span>
        <ol>{d.commands.slice(0, 5).map((c) => <li key={c.t}><span className="num">{new Date(c.t).toLocaleTimeString([], { hour12: false })}</span><span>{c.command}</span><span className={c.success ? "ok" : "warning"}>{c.success ? "OK" : "FAIL"}</span></li>)}</ol>
      </div>
    </div>
  );
}

function Edge({ d, stale }: { d: Telemetry; stale: boolean }) {
  const e = d.snapshot!.edge;
  return (
    <div className="pg pg-edge">
      <div className="ro-grid">
        <Readout label="Thor CPU" value={stale ? "--" : f(e.cpu, 0)} unit=" %" />
        <Readout label="Memory free" value={stale ? "--" : f(e.memAvailGb, 1)} unit=" GB" />
        <Readout label="Thor temp" value={stale ? "--" : f(e.temp, 0)} unit=" °C" state={e.temp != null && e.temp > LIMITS.edgeCaution ? "caution" : undefined} />
        <Readout label="Video age" value={stale ? "--" : f(e.videoAgeS, 2)} unit=" s" />
      </div>
      <TrendTape label="Detector rate" unit=" fps" data={d.series.fps} min={0} max={20} digits={1} />
      <TrendTape label="Thor temperature" unit=" °C" data={d.series.edgeTemp} min={30} max={95} limits={[{ v: LIMITS.edgeCaution, kind: "caution" }]} />
    </div>
  );
}

function Link({ d, stale, source }: { d: Telemetry; stale: boolean; source: string }) {
  const s = d.snapshot!;
  const lost = s.joints.reduce((a, j) => a + j.lost, 0);
  return (
    <div className="pg pg-link">
      <div className="ro-grid">
        <Readout label="Robot link" value={stale ? "--" : s.connected ? "DDS UP" : "DOWN"} state={!stale && !s.connected ? "warning" : undefined} />
        <Readout label="Video" value={stale ? "--" : s.hasVideo ? "UP" : "DOWN"} state={!stale && !s.hasVideo ? "caution" : undefined} />
        <Readout label="Telemetry age" value={f(s.ageS, 1)} unit=" s" state={stale ? "warning" : undefined} />
        <Readout label="Source" value={source === "live" ? "LIVE" : "SYNTHETIC"} state={source === "live" ? undefined : "caution"} />
        <Readout label="Lost frames" value={String(lost)} state={lost > 0 ? "caution" : undefined} />
        <Readout label="Error code" value={stale ? "--" : f(s.errorCode)} state={s.errorCode ? "caution" : undefined} />
      </div>
      <p className="note">Joint map: <strong>unconfirmed</strong>. Joint order follows the Unitree convention (FR, FL, RR, RL) until it is verified on the robot; the 3D legs follow posture, not raw angles.</p>
      {d.error && <p className="note warning">Query API: {d.error}</p>}
    </div>
  );
}

export function SynopticPage({ page, d, stale, source }: { page: Page; d: Telemetry; stale: boolean; source: string }) {
  if (!d.snapshot) return <p className="muted">Waiting for the first telemetry sample…</p>;
  switch (page) {
    case "POWER": return <Power d={d} stale={stale} />;
    case "GAIT": return <Gait d={d} stale={stale} />;
    case "ATTITUDE": return <Attitude d={d} stale={stale} />;
    case "VISION": return <Vision d={d} />;
    case "EDGE": return <Edge d={d} stale={stale} />;
    case "LINK": return <Link d={d} stale={stale} source={source} />;
  }
}
