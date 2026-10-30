"use client";
// "How it works": the live data path from the dog to this screen, named in the
// show's cloud services (theme.ts ARCH). A native <dialog>: focus is trapped,
// Esc closes, and the page behind is inert.
import { useRef } from "react";
import { arch, theme } from "@/lib/theme";

type Node = { id: string; x: number; y: number; title: string; note: string; cloud?: boolean };
const W = 236, H = 74;
const NODES: Node[] = [
  { id: "dog", x: 40, y: 92, title: "Unitree Go2", note: "12 joints · IMU · battery · L1 lidar" },
  { id: "orin", x: 40, y: 232, title: "Robot link · Jetson Orin", note: "DDS → HTTPS · safety deadman" },
  { id: "thor", x: 40, y: 372, title: "NVIDIA Jetson AGX Thor", note: "vision · telemetry · maneuvers" },
  { id: "hub", x: 382, y: 92, title: arch.ingest, note: "telemetry stream", cloud: true },
  { id: "fn", x: 382, y: 232, title: arch.compute, note: arch.computeNote, cloud: true },
  { id: "store", x: 382, y: 372, title: arch.store, note: arch.storeNote, cloud: true },
  { id: "agent", x: 700, y: 92, title: arch.agent, note: arch.agentNote, cloud: true },
  { id: "web", x: 700, y: 232, title: arch.hosting, note: "this dashboard", cloud: true },
  { id: "rt", x: 700, y: 372, title: arch.realtime, note: "live twin · ~15 frames/s", cloud: true },
];
const cx = (id: string) => NODES.find((n) => n.id === id)!.x + W / 2;

// Flows routed through the corridors between columns, so no line crosses a box.
// [path, label, x, y, anchor, rotate?, twin?]
type Flow = { d: string; label: string; lx: number; ly: number; anchor?: "start" | "middle" | "end"; rot?: boolean; twin?: boolean };
const FLOWS: Flow[] = [
  { d: `M${cx("dog")},166 V232`, label: "DDS · 20 Hz", lx: cx("dog") + 10, ly: 203, anchor: "start" },
  { d: `M${cx("orin")},306 V372`, label: "/vitals · /joints", lx: cx("orin") + 10, ly: 343, anchor: "start" },
  { d: "M276,400 H322 V129 H382", label: "telemetry events · every 2 s", lx: 312, ly: 265, rot: true },
  { d: `M${cx("hub")},166 V232`, label: arch.ingestLink, lx: cx("hub") + 10, ly: 203, anchor: "start" },
  { d: `M${cx("fn")},306 V372`, label: arch.storeLink, lx: cx("fn") + 10, ly: 343, anchor: "start" },
  { d: "M700,129 H659 V252 H618", label: arch.agentLink, lx: 650, ly: 190, rot: true },
  { d: "M618,286 H700", label: "read API", lx: 659, ly: 279 },
  { d: `M276,428 H340 V476 H${cx("rt")} V446`, label: arch.twinLink, lx: 560, ly: 470, twin: true },
  { d: `M${cx("rt")},372 V306`, label: "receive-only", lx: cx("rt") + 10, ly: 343, anchor: "start", twin: true },
];

export function ArchitectureButton() {
  const dlg = useRef<HTMLDialogElement>(null);
  return (
    <>
      <button type="button" className="arch-btn" onClick={() => dlg.current?.showModal()} aria-haspopup="dialog">How it works</button>
      <dialog ref={dlg} className="arch-dlg" aria-labelledby="arch-title" onClick={(e) => { if (e.target === dlg.current) dlg.current?.close(); }}>
        <header className="arch-head">
          <h2 id="arch-title">From the dog to this screen</h2>
          <button type="button" className="arch-close" onClick={() => dlg.current?.close()} aria-label="Close">
            <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M2 2 L12 12 M12 2 L2 12" stroke="currentColor" strokeWidth="1.8" /></svg>
          </button>
        </header>
        <svg className="arch-svg" viewBox="0 0 980 500" role="img" aria-label={`Data flow: Unitree Go2 to Jetson Orin robot link to NVIDIA Jetson AGX Thor at the booth, then ${arch.ingest}, ${arch.compute} and ${arch.store}; ${arch.agent} reads through the query API; ${arch.realtime} carries the live twin to ${arch.hosting}.`}>
          <defs>
            <marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L8 4 L0 8 Z" className="arch-arrowhead" /></marker>
          </defs>
          <rect x="18" y="28" width="282" height="456" rx="8" className="arch-zone" />
          <text x="34" y="54" className="arch-zone-label">Booth edge</text>
          <rect x="356" y="28" width="606" height="456" rx="8" className="arch-zone cloud" />
          <text x="372" y="54" className="arch-zone-label cloud">{arch.region}</text>
          {FLOWS.map((f, i) => (
            <g key={i} className={`arch-flow ${f.twin ? "twin" : ""}`}>
              <path d={f.d} markerEnd="url(#arrow)" />
              <text x={f.lx} y={f.ly} textAnchor={f.anchor ?? "middle"} className="arch-flow-label"
                transform={f.rot ? `rotate(-90 ${f.lx} ${f.ly})` : undefined}>{f.label}</text>
            </g>
          ))}
          {NODES.map((n) => (
            <g key={n.id} className={`arch-node ${n.cloud ? "cloud" : ""}`}>
              <rect x={n.x} y={n.y} width={W} height={H} rx="6" />
              <text x={n.x + 16} y={n.y + 31} className="arch-node-title">{n.title}</text>
              <text x={n.x + 16} y={n.y + 54} className="arch-node-note">{n.note}</text>
            </g>
          ))}
        </svg>
        <ul className="arch-notes">
          <li><b>{arch.identityHead}.</b> {arch.identity}.</li>
          <li><b>Read-only overwatch.</b> The {theme.agentHost} agent queries telemetry through a fixed API and can never command the robot.</li>
          <li><b>Live or clearly not.</b> Every value shows its age; the twin falls back to 5 s vitals when the stream pauses.</li>
        </ul>
      </dialog>
    </>
  );
}
