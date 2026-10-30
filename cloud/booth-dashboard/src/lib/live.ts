// LIVE data source: the provider-agnostic read-only query API (ADR 0002).
// Same calls on Azure (Ignite) and AWS (re:Invent); only the base URL differs.
import { Finding, Joint, LEGS, Posture, SEGS, Series, SeriesPoint, Snapshot, Telemetry } from "./model";

type Row = Record<string, unknown>;
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : typeof v === "string" && v !== "" && Number.isFinite(+v) ? +v : null);
const arr = (v: unknown): number[] => (Array.isArray(v) ? v.map((x) => num(x) ?? 0) : []);
const ms = (v: unknown) => (typeof v === "string" ? Date.parse(v) : NaN);
const sev = (s: unknown): Finding["severity"] => (s === "high" ? "warning" : s === "medium" ? "caution" : "advisory");
const posture = (p: unknown): Posture => (p === "standing" || p === "low" || p === "lying" ? p : "unknown");

async function op(base: string, name: string, params: Record<string, string> = {}): Promise<Row[]> {
  const route = name.replace("_", "/");
  const qs = new URLSearchParams(params).toString();
  const r = await fetch(`${base.replace(/\/$/, "")}/${route}${qs ? `?${qs}` : ""}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
  return ((await r.json()) as { rows: Row[] }).rows ?? [];
}

export async function readLive(base: string): Promise<Telemetry> {
  const [snapRows, motors, vseries, mseries, findings, postures, detections, alerts, commands] = await Promise.all([
    op(base, "vitals_snapshot"),
    op(base, "motors_latest"),
    op(base, "vitals_series", { window: "10m", bin_size: "15s" }),
    op(base, "motors_series", { window: "10m", bin_size: "30s" }),
    op(base, "overwatch_findings"),
    op(base, "posture_timeline", { window: "1h" }),
    op(base, "detections_summary", { window: "1h" }),
    op(base, "alerts_recent", { window: "1h" }),
    op(base, "commands_recent", { window: "1h" }),
  ]);
  // One row per device; show the freshest (old sample devices can linger in the store).
  const s = [...snapRows].sort((a, b) => ms(b.Timestamp) - ms(a.Timestamp))[0];
  const now = Date.now();
  let snapshot: Snapshot | null = null;
  if (s) {
    const raw = (s.Raw ?? {}) as Row;
    const v = (raw.robot_vitals ?? {}) as Row;
    const power = (v.power ?? {}) as Row, bms = (power.bms ?? {}) as Row;
    const byName = new Map(motors.filter((m) => m.DeviceId === s.DeviceId).map((m) => [String(m.Joint), m]));
    const joints: Joint[] = [];
    for (const leg of LEGS) for (const seg of SEGS) {
      const name = `${leg}_${seg}`; const m = byName.get(name);
      joints.push({ name, leg, seg, temp: num(m?.Temperature), torque: num(m?.TorqueEst), q: num(m?.Position), lost: num(m?.Lost) ?? 0 });
    }
    const t = ms(s.Timestamp);
    snapshot = {
      source: "live", deviceId: String(s.DeviceId), t, ageS: (now - t) / 1000,
      connected: s.Connected === true, hasVideo: s.HasVideo === true, posture: posture(s.Posture),
      bodyHeight: num(s.BodyHeight), roll: num(s.Roll), pitch: num(s.Pitch), yaw: num(s.Yaw),
      velocity: [num(s.VelocityX) ?? 0, num(s.VelocityY) ?? 0], yawSpeed: num(s.YawSpeed),
      // Firmware 1.1.15 leaves sport mode, gait and range_obstacle at 0, so show them as unavailable.
      gaitType: null, sportMode: null, errorCode: num(s.ErrorCode),
      battery: { soc: num(s.BatterySoc), packV: num(s.PackVoltage), packA: num(s.PackCurrentA), cycles: num(s.BmsCycles),
        cellV: arr(bms.cell_vol).filter((mv) => mv > 0).map((mv) => (mv > 100 ? mv / 1000 : mv)),   // the BMS reports 15 slots; unused ones read 0
        bmsTemps: [...arr(bms.bq_ntc), ...arr(bms.mcu_ntc)],
        boardTemps: [num(s.BoardTempMax)].filter((x): x is number => x != null) },
      imuTemp: num(s.ImuTemp), // A raised paw still reads ~10; an exact 0 on every sample is a sensor that
      // reports nothing (FL and RR on the booth dog, 2026-10-30), so show it as n/a.
      footForce: arr(s.FootForce).map((f) => (f === 0 ? null : f)), obstacles: arr(s.RangeObstacle).some((r) => r > 0) ? arr(s.RangeObstacle) : [], joints,
      edge: { cpu: num(s.EdgeCpuPercent), memAvailGb: num(s.EdgeMemAvailableGb), temp: num(s.EdgeTempMax), fps: num(s.EdgeDetectionFps), videoAgeS: null },
      actuator: { moving: false, stopConfirmed: true },
    };
  }
  const series: Series = { soc: [], tempMax: [], tempAvg: [], fps: [], edgeTemp: [], pitch: [], roll: [], joint: {} };
  const pt = (r: Row, k: string): SeriesPoint | null => { const v = num(r[k]); const t = ms(r.Timestamp); return v == null || !Number.isFinite(t) ? null : { t, v }; };
  for (const r of vseries.sort((a, b) => ms(a.Timestamp) - ms(b.Timestamp))) {
    const a = pt(r, "BatterySoc"); if (a) series.soc.push(a);
    const b = pt(r, "MotorTempMax"); if (b) series.tempMax.push(b);
    const c = pt(r, "DetectionFps"); if (c) series.fps.push(c);
  }
  for (const r of mseries.sort((a, b) => ms(a.Timestamp) - ms(b.Timestamp))) {
    const p = pt(r, "Temperature"); if (p) (series.joint[String(r.Joint)] ??= []).push(p);
  }
  return {
    snapshot, series,
    findings: findings.map((f, i) => ({ id: `${f.Finding}-${i}`, severity: sev(f.Severity), t: now, metric: String(f.DeviceId ?? ""), text: String(f.Finding ?? "") })),
    postures: postures.map((p) => ({ t: ms(p.Timestamp), posture: posture(p.Posture) })),
    detections: detections.map((d) => ({ className: String(d.ClassName), count: num(d.Count) ?? 0, avgConfidence: num(d.AvgConfidence) ?? 0 })),
    ppeAlerts: alerts.filter((a) => String(a.AlertType).includes("ppe")).length,
    commands: commands.map((c) => ({ t: ms(c.Timestamp), command: String(c.Command), success: c.Success === true })),
    error: null,
  };
}
