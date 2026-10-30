// Cloud-neutral dashboard model. Both data sources (live query API, synthetic
// simulator) produce exactly these shapes.

export const LEGS = ["FL", "FR", "RL", "RR"] as const;           // display order: front pair, rear pair
export const SEGS = ["hip", "thigh", "calf"] as const;
export type Leg = (typeof LEGS)[number];
export type Seg = (typeof SEGS)[number];
export type Posture = "standing" | "low" | "lying" | "unknown";
export type Severity = "warning" | "caution" | "advisory";

// Go2 sport error_code values that report a posture state, not a fault
// (observed on firmware 1.1.15, 2026-10-30). Mirrored in Overwatch_Findings (setup.kql).
export const STATE_CODES: Record<number, string> = { 100: "STANDING", 1001: "LYING", 1002: "TRANSITION" };

export interface Joint { name: string; leg: Leg; seg: Seg; temp: number | null; torque: number | null; q: number | null; lost: number }

export interface Snapshot {
  source: "live" | "synthetic";
  deviceId: string;
  t: number;                 // ms epoch of the robot sample
  ageS: number;              // freshness at render time
  connected: boolean;
  hasVideo: boolean;
  posture: Posture;
  bodyHeight: number | null;
  roll: number | null; pitch: number | null; yaw: number | null;          // rad
  velocity: [number, number] | null; yawSpeed: number | null;
  gaitType: number | null; sportMode: number | null; errorCode: number | null;
  battery: { soc: number | null; packV: number | null; packA: number | null; cycles: number | null; cellV: number[]; bmsTemps: number[]; boardTemps: number[] };
  imuTemp: number | null;
  footForce: (number | null)[];  // FR FL RR RL as published; null = sensor reports nothing
  obstacles: number[];       // range_obstacle, metres
  joints: Joint[];           // 12
  edge: { cpu: number | null; memAvailGb: number | null; temp: number | null; fps: number | null; videoAgeS: number | null };
  actuator: { moving: boolean; stopConfirmed: boolean };
  // Head lidar: window from the near-field ring check on the robot link; null = not reported.
  lidar: { window: "clear" | "obstructed" | "unknown"; hz: number | null; errorState: number | null; avoidance: boolean | null } | null;
}

export interface Finding { id: string; severity: Severity; t: number; metric: string; text: string; joint?: string }
export interface SeriesPoint { t: number; v: number }
export interface Series { soc: SeriesPoint[]; tempMax: SeriesPoint[]; tempAvg: SeriesPoint[]; fps: SeriesPoint[]; edgeTemp: SeriesPoint[]; pitch: SeriesPoint[]; roll: SeriesPoint[]; joint: Record<string, SeriesPoint[]> }
export interface PostureChange { t: number; posture: Posture }
export interface DetectionClass { className: string; count: number; avgConfidence: number }
export interface CommandRow { t: number; command: string; success: boolean }

export interface Telemetry {
  snapshot: Snapshot | null;
  series: Series;
  findings: Finding[];
  postures: PostureChange[];
  detections: DetectionClass[];
  ppeAlerts: number;
  commands: CommandRow[];
  error: string | null;
}

// Overwatch thresholds - PLACEHOLDERS until calibrated on the real dog (ADR 0004).
// Mirror any change in Overwatch_Findings (deploy/azure/adx/setup.kql) for parity.
export const LIMITS = {
  jointCaution: 55, jointWarning: 70,          // degC
  batteryCaution: 20, batteryWarning: 10,      // %
  tiltWarning: 0.6,                            // rad (~34 deg)
  edgeCaution: 85,                             // degC
  cellImbalanceMv: 50,                         // mV spread before a cell is flagged (placeholder)
  staleS: 15,                                  // telemetry older than this is shown invalid
};

export const DIAL = { min: 20, max: 90 };      // joint temperature dial span, degC

export function jointState(temp: number | null): "ok" | "caution" | "warning" | "unknown" {
  if (temp == null) return "unknown";
  if (temp >= LIMITS.jointWarning) return "warning";
  if (temp >= LIMITS.jointCaution) return "caution";
  return "ok";
}
