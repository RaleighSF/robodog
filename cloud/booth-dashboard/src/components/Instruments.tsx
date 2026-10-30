"use client";
// EICAS instruments drawn from data: joint dials, annunciators, freshness lamp,
// crew-alerting stack, trend tapes. Colour always travels with a label or shape.
import { DIAL, Finding, Joint, jointState, LIMITS, SeriesPoint } from "@/lib/model";

const SWEEP = 210;                         // degrees, EICAS round-dial sweep
const START = 90 + (360 - SWEEP) / 2;      // start angle (SVG: 0 = +x, clockwise)
const STATUS_VAR = { ok: "var(--status-ok)", caution: "var(--status-warn)", warning: "var(--status-danger)", unknown: "var(--status-offline)" } as const;

function polar(cx: number, cy: number, r: number, deg: number) {
  const a = (deg * Math.PI) / 180; return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
}
function arc(cx: number, cy: number, r: number, a0: number, a1: number) {
  const [x0, y0] = polar(cx, cy, r, a0), [x1, y1] = polar(cx, cy, r, a1);
  return `M ${x0} ${y0} A ${r} ${r} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${x1} ${y1}`;
}
const toDeg = (v: number) => START + (Math.min(Math.max(v, DIAL.min), DIAL.max) - DIAL.min) / (DIAL.max - DIAL.min) * SWEEP;

export function JointDial({ joint, stale, size = 100 }: { joint: Joint; stale: boolean; size?: number }) {
  const st = stale ? "unknown" : jointState(joint.temp);
  const c = 50, r = 38;
  const tq = joint.torque == null ? 0 : Math.min(Math.abs(joint.torque) / 20, 1);
  const valid = !stale && joint.temp != null;
  return (
    <figure className="dial" aria-label={`${joint.leg} ${joint.seg} motor ${valid ? `${joint.temp!.toFixed(0)} degrees C, ${st}` : "no valid data"}`} style={{ width: size }}>
      <svg viewBox="0 0 100 92" width={size} height={size * 0.92} role="img" aria-hidden="true">
        <path d={arc(c, c, r, START, toDeg(LIMITS.jointCaution))} stroke="var(--status-ok)" strokeOpacity={0.55} strokeWidth={3} fill="none" />
        <path d={arc(c, c, r, toDeg(LIMITS.jointCaution), toDeg(LIMITS.jointWarning))} stroke="var(--status-warn)" strokeOpacity={0.75} strokeWidth={5} fill="none" />
        <path d={arc(c, c, r, toDeg(LIMITS.jointWarning), START + SWEEP)} stroke="var(--border)" strokeWidth={3} fill="none" />
        {(() => { const [x0, y0] = polar(c, c, r - 7, toDeg(LIMITS.jointWarning)); const [x1, y1] = polar(c, c, r + 5, toDeg(LIMITS.jointWarning));
          return <line x1={x0} y1={y0} x2={x1} y2={y1} stroke="var(--status-danger)" strokeWidth={3} />; })()}
        {/* torque: thin inner arc, proportion of 20 Nm */}
        {valid && tq > 0.01 && <path d={arc(c, c, r - 9, START, START + tq * SWEEP)} stroke="var(--text-tertiary)" strokeWidth={2} fill="none" />}
        {valid && (() => { const [x, y] = polar(c, c, r - 2, toDeg(joint.temp!)); return <line x1={c} y1={c} x2={x} y2={y} stroke={STATUS_VAR[st]} strokeWidth={st === "ok" ? 2.5 : 3.5} strokeLinecap="round" style={{ transition: "all 600ms var(--ease-out)" }} />; })()}
        <circle cx={c} cy={c} r={3.2} fill="var(--surface-3)" stroke="var(--border-strong)" />
      </svg>
      <div className={`readout num ${valid ? st : "invalid"}`}>{valid ? joint.temp!.toFixed(0) : "--"}<span>°C</span></div>
      <figcaption className="title">{joint.seg}</figcaption>
    </figure>
  );
}

export function FreshnessLamp({ ageS, source, error }: { ageS: number | null; source: "live" | "synthetic"; error: string | null }) {
  const stale = ageS == null || ageS > LIMITS.staleS;
  const label = ageS == null ? "NO DATA" : stale ? `STALE ${ageS < 120 ? `${ageS.toFixed(0)} s` : `${Math.round(ageS / 60)} min`}` : `LIVE ${ageS.toFixed(1)} s`;
  return (
    <div className={`fresh ${stale ? "stale" : "ok"}`} role="status" aria-live="polite" title={error ?? undefined}>
      <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">{stale ? <path d="M6 1 L11 11 L1 11 Z" fill="currentColor" /> : <circle cx="6" cy="6" r="5" fill="currentColor" />}</svg>
      <span className="num">{label}</span>
      {source === "synthetic" && <span className="synthetic">SYNTHETIC DATA</span>}
    </div>
  );
}

export function Annunciator({ kind, lit, onAck }: { kind: "warning" | "caution"; lit: boolean; onAck?: () => void }) {
  return (
    <button type="button" className={`annun ${kind} ${lit ? "lit" : ""}`} onClick={onAck} disabled={!lit || !onAck}
      aria-label={`Master ${kind}${lit ? ", lit. Press to acknowledge" : ", off"}`}>
      <span className="title">MASTER</span><span className="big">{kind === "warning" ? "WARNING" : "CAUTION"}</span>
    </button>
  );
}

const SEV_LABEL = { warning: "WARNING", caution: "CAUTION", advisory: "ADVISORY" } as const;
function hhmmss(t: number) { return new Date(t).toLocaleTimeString([], { hour12: false }); }

export function CasStack({ findings, stale }: { findings: Finding[]; stale: boolean }) {
  return (
    <section className="cas panel" aria-label="Agent overwatch crew-alerting messages">
      <header className="cas-head"><h2 className="title">Overwatch · crew alerting</h2><span className="cas-count num">{findings.length}</span></header>
      {stale && <p className="cas-stale">Telemetry is stale. Findings below are not current.</p>}
      <ol className="cas-list">
        {findings.length === 0 && <li className="cas-empty">No findings. All monitored systems inside limits.</li>}
        {findings.map((f) => (
          <li key={f.id} className={`cas-msg ${f.severity}`}>
            <div className="cas-meta">
              <span className={`sev ${f.severity}`}>{SEV_LABEL[f.severity]}</span>
              <span className="num cas-metric">{f.metric}</span>
              <time className="num">{hhmmss(f.t)}</time>
            </div>
            <p>{f.text}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** Strip-chart trend tape: one quantity, its limits, last value. */
export function TrendTape({ label, unit, data, min, max, limits = [], digits = 0, height = 56 }: {
  label: string; unit: string; data: SeriesPoint[]; min: number; max: number;
  limits?: { v: number; kind: "caution" | "warning" }[]; digits?: number; height?: number;
}) {
  const w = 300, h = 60;
  const last = data[data.length - 1];
  const t0 = data[0]?.t ?? 0, t1 = last?.t ?? 1;
  const x = (t: number) => ((t - t0) / Math.max(t1 - t0, 1)) * w;
  const y = (v: number) => h - ((Math.min(Math.max(v, min), max) - min) / (max - min)) * h;
  const d = data.map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
  return (
    <div className="tape">
      <div className="tape-head"><span className="title">{label}</span><span className="num tape-val">{last ? last.v.toFixed(digits) : "--"}<small>{unit}</small></span></div>
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ height }} role="img" aria-label={`${label} trend, last ten minutes`}>
        {[0.25, 0.5, 0.75].map((f) => <line key={f} x1={0} x2={w} y1={h * f} y2={h * f} stroke="var(--border-subtle)" strokeWidth={1} vectorEffect="non-scaling-stroke" />)}
        {limits.map((l) => <line key={l.v} x1={0} x2={w} y1={y(l.v)} y2={y(l.v)} stroke={l.kind === "warning" ? "var(--status-danger)" : "var(--status-warn)"} strokeDasharray="4 4" strokeWidth={1} vectorEffect="non-scaling-stroke" />)}
        <path d={d} fill="none" stroke="var(--text-primary)" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
      </svg>
    </div>
  );
}
