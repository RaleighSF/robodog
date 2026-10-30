// SYNTHETIC data source: a physically plausible Go2 booth loop for design work
// and as the clearly-labelled fallback when the booth has no live data.
// Never presented as the real robot: every snapshot carries source "synthetic".
import { Finding, Joint, LEGS, LIMITS, Posture, SEGS, Snapshot, Telemetry, SeriesPoint, Series } from "./model";

const LOOP_S = 180;
type Phase = { until: number; posture: Posture; walking?: boolean; label: string };
const PHASES: Phase[] = [
  { until: 20, posture: "lying", label: "lying, cooling" },
  { until: 26, posture: "standing", label: "standing up" },
  { until: 60, posture: "standing", walking: true, label: "patrol" },
  { until: 80, posture: "standing", label: "holding position" },
  { until: 110, posture: "standing", walking: true, label: "patrol" },
  { until: 150, posture: "low", label: "sitting, cooling" },
  { until: LOOP_S, posture: "lying", label: "lying, cooling" },
];
// Per-joint heating under load (degC/s) - calves and thighs carry the stance
// load; RL calf runs hottest, the story seen on the real dog on 2026-09-29.
const HEAT: Record<string, number> = {};
for (const l of LEGS) for (const s of SEGS) HEAT[`${l}_${s}`] = s === "calf" ? 0.23 : s === "thigh" ? 0.16 : 0.07;
HEAT["RL_calf"] = 0.41;
HEAT["RR_calf"] = 0.29;

const AMBIENT = 33;
const WINDOW_MS = 10 * 60 * 1000;

function rnd(seed: number) { const x = Math.sin(seed * 12.9898) * 43758.5453; return x - Math.floor(x); }
function push(arr: SeriesPoint[], t: number, v: number) { arr.push({ t, v }); while (arr.length && arr[0].t < t - WINDOW_MS) arr.shift(); }

export class SyntheticSource {
  private t0 = Date.now();
  private temps: Record<string, number> = {};
  private soc = 81.4;
  private last = Date.now();
  private series: Series = { soc: [], tempMax: [], tempAvg: [], fps: [], edgeTemp: [], pitch: [], roll: [], joint: {} };
  private postures: { t: number; posture: Posture }[] = [];
  private findings = new Map<string, Finding>();
  private detections = { person: 0, confSum: 0 };
  private ppe = 0;
  private commands: { t: number; command: string; success: boolean }[] = [];
  private prevPosture: Posture | null = null;

  constructor() {
    for (const k of Object.keys(HEAT)) this.temps[k] = AMBIENT + 2 + rnd(k.length) * 3;
    // Pre-roll 10 minutes so the trend tapes are populated on first paint.
    const now = Date.now();
    for (let s = 600; s > 0; s -= 2) this.step(now - s * 1000, 2);
    this.last = now;
  }

  private phaseAt(t: number): Phase {
    const s = ((t - this.t0) / 1000) % LOOP_S;
    const p = (s + LOOP_S) % LOOP_S;
    return PHASES.find((ph) => p < ph.until) ?? PHASES[PHASES.length - 1];
  }

  private step(t: number, dt: number) {
    const ph = this.phaseAt(t);
    const load = ph.posture === "standing" ? (ph.walking ? 1.35 : 1) : ph.posture === "low" ? 0.25 : 0;
    for (const k of Object.keys(this.temps)) {
      const heat = HEAT[k] * load;
      const cool = (this.temps[k] - AMBIENT) * 0.012;      // Newtonian cooling
      this.temps[k] += (heat - cool) * dt;
    }
    this.soc -= (load > 0 ? 0.012 + 0.006 * load : 0.004) * dt;
    if (this.soc < 12) this.soc = 81.4;                    // demo loop "battery swap"

    const vals = Object.values(this.temps);
    const max = Math.max(...vals), avg = vals.reduce((a, b) => a + b, 0) / vals.length;
    const sway = ph.walking ? 0.05 : 0.012;
    push(this.series.soc, t, this.soc);
    push(this.series.tempMax, t, max);
    push(this.series.tempAvg, t, avg);
    push(this.series.fps, t, 14 + Math.sin(t / 7000) * 0.4);
    push(this.series.edgeTemp, t, 53 + Math.sin(t / 30000) * 2.5 + load);
    push(this.series.pitch, t, Math.sin(t / 900) * sway);
    push(this.series.roll, t, Math.sin(t / 1300 + 1) * sway * 0.7);
    for (const [k, v] of Object.entries(this.temps)) push((this.series.joint[k] ??= []), t, v);

    if (ph.posture !== this.prevPosture) {
      this.postures.push({ t, posture: ph.posture });
      if (this.postures.length > 40) this.postures.shift();
      if (this.prevPosture) this.commands.unshift({ t, command: ph.posture === "standing" ? "stand" : ph.posture === "low" ? "sit" : "crouch", success: true });
      this.commands = this.commands.slice(0, 12);
      this.prevPosture = ph.posture;
    }
    if (ph.posture === "standing" && rnd(t / 997) > 0.93) { this.detections.person += 1; this.detections.confSum += 0.78 + rnd(t) * 0.18; if (rnd(t / 3) > 0.7) this.ppe += 1; }
  }

  private trend(key: string): number {        // degC per minute over the last 60 s
    const s = this.series.joint[key];
    if (!s || s.length < 2) return 0;
    const end = s[s.length - 1];
    const start = s.find((p) => p.t >= end.t - 60000) ?? s[0];
    const dtMin = (end.t - start.t) / 60000;
    return dtMin > 0 ? (end.v - start.v) / dtMin : 0;
  }

  private updateFindings(snap: Snapshot) {
    const now = snap.t;
    const live = new Set<string>();
    const label = (j: Joint) => `${j.leg} ${j.seg}`;
    for (const j of snap.joints) {
      if (j.temp == null) continue;
      const rate = this.trend(j.name);
      if (j.temp >= LIMITS.jointWarning) {
        live.add(j.name);
        this.upsert(`joint:${j.name}`, "warning", now, `${j.name} ${j.temp.toFixed(0)} °C`,
          `${label(j)} motor reached ${j.temp.toFixed(0)}\u00a0°C, over the ${LIMITS.jointWarning}\u00a0°C limit. Sit or lie the dog down now.`, j.name);
      } else if (j.temp >= LIMITS.jointCaution) {
        live.add(j.name);
        const eta = rate > 0.2 ? Math.max(1, Math.round((LIMITS.jointWarning - j.temp) / rate)) : null;
        const toLimit = eta != null ? ` It reaches ${LIMITS.jointWarning}\u00a0°C in about ${eta}\u00a0min at this rate.` : "";
        this.upsert(`joint:${j.name}`, "caution", now, `${j.name} ${j.temp.toFixed(0)}\u00a0°C ${rate >= 0 ? "+" : ""}${rate.toFixed(1)}\u00a0°C/min`,
          `${label(j)} motor is at ${j.temp.toFixed(0)}\u00a0°C and ${rate > 0.2 ? "climbing" : "steady"} while ${snap.posture}.${toLimit} Sit the dog to cool it.`, j.name);
      }
    }
    // A joint that cooled back below caution clears its message (EICAS: messages leave when the condition clears).
    for (const key of [...this.findings.keys()]) if (key.startsWith("joint:") && !live.has(key.slice(6))) this.findings.delete(key);

    const soc = snap.battery.soc ?? 0;
    const drainPerMin = this.series.soc.length > 30 ? (this.series.soc[this.series.soc.length - 31].v - soc) / ((snap.t - this.series.soc[this.series.soc.length - 31].t) / 60000) : 0;
    const mins = drainPerMin > 0.01 ? Math.round((soc - 10) / drainPerMin) : null;
    this.upsert("battery", soc < LIMITS.batteryWarning ? "warning" : soc < LIMITS.batteryCaution ? "caution" : "advisory", now,
      `SOC ${soc.toFixed(0)}\u00a0%`, mins != null ? `Battery ${soc.toFixed(0)}\u00a0%, about ${mins}\u00a0min of demo left at the current draw.` : `Battery ${soc.toFixed(0)}\u00a0%, draw is light while ${snap.posture}.`);

    const pc = this.postures[this.postures.length - 1];
    if (pc && now - pc.t < 20000) {
      const why = pc.posture === "standing" ? "Joint load is up; I am watching the calves." : pc.posture === "low" ? "Sitting takes the load off the rear calves so they can cool." : "Lying down, every motor is unloaded and cooling.";
      this.upsert("posture", "advisory", pc.t, `POSTURE ${pc.posture.toUpperCase()}`, `Dog is now ${pc.posture === "low" ? "sitting" : pc.posture}. ${why}`);
    } else this.findings.delete("posture");
  }

  private upsert(id: string, severity: Finding["severity"], t: number, metric: string, text: string, joint?: string) {
    const prev = this.findings.get(id);
    this.findings.set(id, { id, severity, t: prev && prev.severity === severity ? prev.t : t, metric, text, joint });
  }

  read(): Telemetry {
    const now = Date.now();
    const dt = (now - this.last) / 1000;
    if (dt > 0.2) { this.step(now, Math.min(dt, 5)); this.last = now; }
    const ph = this.phaseAt(now);
    const standing = ph.posture === "standing";
    const joints: Joint[] = [];
    for (const leg of LEGS) for (const seg of SEGS) {
      const name = `${leg}_${seg}`;
      const temp = this.temps[name];
      const torque = standing ? (seg === "calf" ? 7.5 : seg === "thigh" ? 4.2 : 1.1) * (ph.walking ? 1.25 + Math.sin(now / 180 + name.length) * 0.35 : 1) : ph.posture === "low" && leg.startsWith("F") ? 2.4 : 0.2;
      joints.push({ name, leg, seg, temp, torque, q: null, lost: 0 });
    }
    const p = this.series.pitch[this.series.pitch.length - 1]?.v ?? 0;
    const r = this.series.roll[this.series.roll.length - 1]?.v ?? 0;
    const tempVals = joints.map((j) => j.temp as number);
    const snap: Snapshot = {
      source: "synthetic", deviceId: "watchdog-sample", t: now - 900, ageS: 0.9,   // realistic edge-to-cloud latency
      connected: true, hasVideo: true, posture: ph.posture,
      bodyHeight: standing ? 0.32 : ph.posture === "low" ? 0.2 : 0.08,
      roll: r, pitch: ph.posture === "low" ? p + 0.42 : p, yaw: 1.57,
      velocity: ph.walking ? [0.24 + Math.sin(now / 2000) * 0.03, 0] : [0, 0], yawSpeed: ph.walking ? Math.sin(now / 3000) * 0.2 : 0,
      gaitType: ph.walking ? 1 : 0, sportMode: standing ? 1 : 0, errorCode: 0,
      battery: { soc: this.soc, packV: 25.2 + this.soc * 0.058, packA: standing ? -(4.8 + (ph.walking ? 3 : 0)) : -1.1, cycles: 42,
        cellV: Array.from({ length: 8 }, (_, i) => 3.62 + this.soc * 0.0072 + (i === 5 ? -0.012 : 0) + rnd(i) * 0.004), bmsTemps: [31 + this.soc * 0.02, 32.5, 34.1, 35.0], boardTemps: [38.2, 39.6] },
      imuTemp: 41,
      footForce: standing ? [64, 61, 72, 70].map((f, i) => f + Math.sin(now / 160 + i * 1.6) * (ph.walking ? 26 : 2)) : ph.posture === "low" ? [55, 53, 0, 0] : [0, 0, 0, 0],
      obstacles: [1.9 + Math.sin(now / 5000) * 0.4, 2.6, 0.85 + Math.sin(now / 4100) * 0.2, 2.2],
      joints,
      edge: { cpu: 21 + Math.sin(now / 9000) * 6, memAvailGb: 10.1, temp: this.series.edgeTemp[this.series.edgeTemp.length - 1]?.v ?? 54, fps: 14 + Math.sin(now / 7000) * 0.4, videoAgeS: 0.07 },
      actuator: { moving: !!ph.walking, stopConfirmed: !ph.walking },
      lidar: { window: standing ? "clear" : "unknown", hz: 15.4, errorState: 0, avoidance: true },
    };
    void tempVals;
    this.updateFindings(snap);
    const order = { warning: 0, caution: 1, advisory: 2 } as const;
    return {
      snapshot: snap,
      series: this.series,
      findings: [...this.findings.values()].sort((a, b) => order[a.severity] - order[b.severity] || b.t - a.t),
      postures: this.postures,
      detections: this.detections.person ? [{ className: "person", count: this.detections.person, avgConfidence: this.detections.confSum / this.detections.person }] : [],
      ppeAlerts: this.ppe,
      commands: this.commands,
      error: null,
    };
  }
}
