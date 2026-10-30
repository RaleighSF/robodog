"use client";
// EICAS instruments drawn from data: joint dials, annunciators, freshness lamp,
// crew-alerting stack, trend tapes. Colour always travels with a label or shape.
import type { Brief } from "@/lib/agent";
import { DIAL, Finding, Joint, jointState, LIMITS, SeriesPoint, Snapshot } from "@/lib/model";
import { theme } from "@/lib/theme";

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
        {[30, 40, 50, 60, 70, 80].map((v) => { const [x0, y0] = polar(c, c, r + 2, toDeg(v)); const [x1, y1] = polar(c, c, r + 5, toDeg(v));
          return <line key={v} x1={x0} y1={y0} x2={x1} y2={y1} stroke="var(--border-strong)" strokeWidth={1} />; })}
        {/* torque: inner arc, proportion of 20 Nm */}
        <path d={arc(c, c, r - 9, START, START + SWEEP)} stroke="var(--border-subtle)" strokeWidth={3} fill="none" />
        {valid && tq > 0.01 && <path d={arc(c, c, r - 9, START, START + tq * SWEEP)} stroke="var(--text-secondary)" strokeWidth={3} fill="none" style={{ transition: "d 400ms var(--ease-out)" }} />}
        {valid && (() => { const [x, y] = polar(c, c, r - 2, toDeg(joint.temp!)); return <line x1={c} y1={c} x2={x} y2={y} stroke={STATUS_VAR[st]} strokeWidth={st === "ok" ? 2.5 : 3.5} strokeLinecap="round" />; })()}
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

type St = "ok" | "caution" | "warning" | "unknown";
function systems(s: Snapshot | null, stale: boolean): { name: string; state: St; text: string; always?: boolean }[] {
  if (!s || stale) return ["Joint motors", "Battery", "Attitude", "Robot link", "Video", "Head lidar", "Edge compute"].map((name) => ({ name, state: "unknown" as St, text: "NO DATA" }));
  const temps = s.joints.map((j) => j.temp).filter((t): t is number => t != null);
  const tmax = temps.length ? Math.max(...temps) : null;
  const soc = s.battery.soc;
  const tilt = Math.max(Math.abs(s.roll ?? 0), Math.abs(s.pitch ?? 0));
  return [
    { name: "Joint motors", state: jointState(tmax), text: tmax == null ? "NO DATA" : `12 · max ${tmax.toFixed(0)} °C` },
    { name: "Battery", state: soc == null ? "unknown" : soc < LIMITS.batteryWarning ? "warning" : soc < LIMITS.batteryCaution ? "caution" : "ok",
      text: soc == null ? "NO DATA" : s.battery.charging ? `charging +${(s.battery.batteryA ?? 0).toFixed(1)} A` : `${soc.toFixed(0)} %`, always: s.battery.charging },
    { name: "Attitude", state: tilt > LIMITS.tiltWarning ? "warning" : "ok", text: `${s.posture === "low" ? "sitting" : s.posture} · tilt ${(tilt * 57.3).toFixed(0)}°` },
    { name: "Robot link", state: s.connected ? "ok" : "warning", text: s.connected ? "DDS up" : "down" },
    { name: "Video", state: s.hasVideo ? "ok" : "caution", text: s.hasVideo ? "streaming" : "no video" },
    lidarSystem(s.lidar),
    { name: "Edge compute", state: s.edge.temp != null && s.edge.temp > LIMITS.edgeCaution ? "caution" : s.edge.temp == null ? "unknown" : "ok", text: s.edge.temp == null ? "NO DATA" : `Thor ${s.edge.temp.toFixed(0)} °C` },
  ];
}
function lidarSystem(l: Snapshot["lidar"]): { name: string; state: St; text: string } {
  const name = "Head lidar";
  if (!l) return { name, state: "unknown", text: "NO DATA" };
  if ((l.errorState ?? 0) > 0 || (l.hz != null && l.hz < 10)) return { name, state: "caution", text: "degraded" };
  if (l.window === "obstructed") return { name, state: "caution", text: "window obstructed" };
  return { name, state: l.window === "clear" ? "ok" : "unknown", text: `${l.window === "clear" ? "clear" : "standby"} · avoid ${l.avoidance == null ? "?" : l.avoidance ? "on" : "off"}` };
}
const SHAPE: Record<St, string> = { ok: "M6 1 A5 5 0 1 1 5.99 1 Z", caution: "M6 1 L11 11 L1 11 Z", warning: "M2 2 L10 10 M10 2 L2 10", unknown: "M2 6 L10 6" };

/** Mean battery current (A) over the last ~10 min of the trend, or null. */
function meanAmps(amps: SeriesPoint[]): number | null {
  const recent = amps.filter((p) => p.t > (amps[amps.length - 1]?.t ?? 0) - 10 * 60_000);
  return recent.length >= 3 ? recent.reduce((a, p) => a + p.v, 0) / recent.length : null;
}
function hm(mins: number) { return mins >= 60 ? `${Math.floor(mins / 60)}\u00a0h ${String(Math.round(mins % 60)).padStart(2, "0")}\u00a0min` : `${Math.round(mins)}\u00a0min`; }

/** Time left at the current draw: usable charge above the reserve (pack Ah) divided
 *  by the measured 10 min mean battery current. Idle standing draws ~2.7 A; walking
 *  draws more, so this drops as soon as the dog works. Falls back to the SoC slope. */
export function RuntimeBudget({ soc, series, amps, posture, stale, charging = false }: { soc: number | null; series: SeriesPoint[]; amps: SeriesPoint[]; posture: string; stale: boolean; charging?: boolean }) {
  if (charging && !stale) return <ChargeBudget soc={soc} series={series} amps={amps} posture={posture} />;
  let mins: number | null = null;
  const draw = meanAmps(amps);
  if (soc != null && draw != null && draw < -0.3) {
    mins = Math.max(0, ((soc - LIMITS.batteryWarning) / 100) * LIMITS.packAh / -draw * 60);
  } else if (series.length > 8 && soc != null) {
    const a = series[Math.max(0, series.length - 60)], z = series[series.length - 1];
    const rate = (a.v - z.v) / Math.max((z.t - a.t) / 60000, 0.01);
    if (rate > 0.01) mins = Math.max(0, (soc - LIMITS.batteryWarning) / rate);
  }
  const budget = stale || mins == null ? 0 : Math.min(mins / 240, 1);
  return (
    <div className="pinned">
      <div className="pin-posture"><span className="title">Posture</span><b className="num">{stale ? "--" : (posture === "low" ? "sitting" : posture).toUpperCase()}</b></div>
      <div className="budget">
        <div className="budget-head"><span className="title">Battery · at current draw{draw != null && draw < 0 ? ` ${(-draw).toFixed(1)}\u00a0A` : ""}</span>
          <span className="num"><b>{stale || soc == null ? "--" : `${soc.toFixed(0)}\u00a0%`}</b> · {stale || mins == null ? "--" : `~${hm(mins)}`}</span></div>
        <div className="budget-tape" role="img" aria-label={`About ${mins == null ? "unknown" : Math.round(mins)} minutes left at the current draw`}>
          {Array.from({ length: 18 }, (_, i) => <i key={i} className={i / 18 < budget ? (mins != null && mins < 30 ? "warn" : "on") : ""} />)}
        </div>
        <div className="budget-scale num"><span>0</span><span>1 h</span><span>2 h</span><span>3 h</span><span>4 h</span></div>
      </div>
    </div>
  );
}

const SEV_ORDER = { warning: 0, caution: 1, advisory: 2 } as const;

/** Right column, EICAS order: one agent line, terse messages by severity, then
 *  system lamps. Values show only when a system is off-nominal, or in the
 *  staff view (detail), so nothing on the booth screen repeats a dial. */
/** On the charger: the same strip shows charge level and an estimated time to full
 *  from the observed SoC rise (shown only once the trend is measurable). */
function ChargeBudget({ soc, series, amps, posture }: { soc: number | null; series: SeriesPoint[]; amps: SeriesPoint[]; posture: string }) {
  let full: number | null = null;
  const charge = meanAmps(amps);
  if (soc != null && charge != null && charge > LIMITS.chargingA) {
    full = Math.max(0, ((100 - soc) / 100) * LIMITS.packAh / charge * 60);   // constant-current estimate; the last few % taper
  } else if (series.length > 8 && soc != null) {
    const a = series[Math.max(0, series.length - 40)], z = series[series.length - 1];
    const rate = (z.v - a.v) / Math.max((z.t - a.t) / 60000, 0.01);
    if (rate > 0.05) full = Math.max(0, (100 - soc) / rate);
  }
  const level = soc == null ? 0 : soc / 100;
  return (
    <div className="pinned">
      <div className="pin-posture"><span className="title">Posture</span><b className="num">{(posture === "low" ? "sitting" : posture).toUpperCase()}</b></div>
      <div className="budget charging">
        <div className="budget-head"><span className="title">Battery · charging{charge != null ? ` +${charge.toFixed(1)}\u00a0A` : ""}</span>
          <span className="num"><b>{soc == null ? "--" : `${soc.toFixed(0)}\u00a0%`}</b> · {full == null ? "estimating" : `full in ~${hm(full)}`}</span></div>
        <div className="budget-tape" role="img" aria-label={`Charging, ${soc == null ? "unknown" : soc.toFixed(0)} percent`}>
          {Array.from({ length: 18 }, (_, i) => <i key={i} className={i / 18 < level ? (i === Math.ceil(level * 18) - 1 ? "on edge" : "on") : ""} />)}
        </div>
        <div className="budget-scale num"><span>0</span><span>50</span><span>100 %</span></div>
      </div>
    </div>
  );
}

export function CasStack({ findings, stale, snapshot, socSeries, ampSeries = [], brief, detail = false }: {
  findings: Finding[]; stale: boolean; snapshot: Snapshot | null; socSeries: SeriesPoint[]; ampSeries?: SeriesPoint[]; brief?: Brief | null; detail?: boolean;
}) {
  // Level floor: the booth screen shows warnings and cautions only; staff also see advisories.
  const shown = detail ? findings : findings.filter((f) => f.severity !== "advisory");
  const sorted = [...shown].sort((a, b) => SEV_ORDER[a.severity] - SEV_ORDER[b.severity] || b.t - a.t);
  const tally = (["warning", "caution", "advisory"] as const).map((k) => [k, shown.filter((f) => f.severity === k).length] as const).filter(([, n]) => n > 0);
  const briefAge = brief ? Math.max(0, Math.round((Date.now() - brief.at) / 1000)) : 0;
  return (
    <section className="cas panel" aria-label="Agent overwatch crew-alerting messages">
      <header className="cas-head">
        <h2 className="title">Overwatch</h2>
        <span className="cas-tally">{tally.length ? tally.map(([k, n]) => <span key={k} className={`tally ${k}`}><b className="num">{n}</b> {SEV_LABEL[k].toLowerCase()}</span>) : <span className="tally ok">all clear</span>}</span>
      </header>
      {stale && <p className="cas-stale">Telemetry is stale. Messages below are not current.</p>}
      {brief && (
        <figure className="cas-agent" aria-live="polite">
          <blockquote>{brief.text}</blockquote>
          <figcaption>Agent · {theme.agentHost} · <span className="num">{briefAge < 90 ? `${briefAge} s` : `${Math.round(briefAge / 60)} min`} ago</span></figcaption>
        </figure>
      )}
      <ol className="cas-list">
        {sorted.length === 0 && <li className="cas-empty">All monitored systems inside limits.</li>}
        {sorted.map((f) => (
          <li key={f.id} className={`cas-msg ${f.severity}`}>
            <span className={`sev ${f.severity}`}>{SEV_LABEL[f.severity]}</span>
            <p>{f.text}</p>
          </li>
        ))}
      </ol>
      <div className="status">
        <h3 className="title">Systems</h3>
        <ul>
          {systems(snapshot, stale).map((x) => (
            <li key={x.name} className={x.state}>
              <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d={SHAPE[x.state]} fill={x.state === "warning" || x.state === "unknown" ? "none" : "currentColor"} stroke="currentColor" strokeWidth={2} /></svg>
              <span>{x.name}</span>{(detail || x.always || x.state !== "ok") && <span className="num">{x.text}</span>}
            </li>
          ))}
        </ul>
      </div>
      <RuntimeBudget soc={snapshot?.battery.soc ?? null} series={socSeries} amps={ampSeries} posture={snapshot?.posture ?? "unknown"} stale={stale} charging={snapshot?.battery.charging ?? false} />
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
