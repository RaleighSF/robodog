"use client";
// "How it works": the data path from the dog to this screen, named in the show's
// cloud services (theme.ts arch). A build with an edge plane (theme.ts edgePlane)
// draws it in and marks it as roadmap, because the live path does not use it yet. A native <dialog>: focus is trapped,
// Esc closes, and the page behind is inert.
import { useRef } from "react";
import { arch, edgePlane, theme, type EdgePlane } from "@/lib/theme";

type Node = { id: string; x: number; y: number; title: string; note: string; cloud?: boolean; roadmap?: boolean };
type Flow = { d: string; label: string; lx: number; ly: number; anchor?: "start" | "middle" | "end"; rot?: boolean; twin?: boolean };
type Legend = { x: number; y: number; head: string; lines: string[] };
type Layout = { height: number; nodes: Node[]; flows: Flow[]; tag?: string; legend?: Legend };
const W = 236, H = 74;
const [X0, X1, X2] = [40, 382, 700];
const mid = (x: number) => x + W / 2;

// Three rows: the path as it runs today. Flows are routed through the corridors
// between columns, so no line crosses a box.
function directLayout(): Layout {
  const nodes: Node[] = [
    { id: "dog", x: X0, y: 92, title: "Unitree Go2", note: "12 joints · IMU · battery · L1 lidar" },
    { id: "orin", x: X0, y: 232, title: "Robot link · Jetson Orin", note: "DDS → HTTPS · safety deadman" },
    { id: "thor", x: X0, y: 372, title: "NVIDIA Jetson AGX Thor", note: "vision · telemetry · maneuvers" },
    { id: "hub", x: X1, y: 92, title: arch.ingest, note: "telemetry stream", cloud: true },
    { id: "fn", x: X1, y: 232, title: arch.compute, note: arch.computeNote, cloud: true },
    { id: "store", x: X1, y: 372, title: arch.store, note: arch.storeNote, cloud: true },
    { id: "agent", x: X2, y: 92, title: arch.agent, note: arch.agentNote, cloud: true },
    { id: "web", x: X2, y: 232, title: arch.hosting, note: "this dashboard", cloud: true },
    { id: "rt", x: X2, y: 372, title: arch.realtime, note: "live twin · ~15 frames/s", cloud: true },
  ];
  const flows: Flow[] = [
    { d: `M${mid(X0)},166 V232`, label: "DDS · 20 Hz", lx: mid(X0) + 10, ly: 203, anchor: "start" },
    { d: `M${mid(X0)},306 V372`, label: "/vitals · /joints", lx: mid(X0) + 10, ly: 343, anchor: "start" },
    { d: "M276,400 H322 V129 H382", label: "telemetry events · every 2 s", lx: 312, ly: 265, rot: true },
    { d: `M${mid(X1)},166 V232`, label: arch.ingestLink, lx: mid(X1) + 10, ly: 203, anchor: "start" },
    { d: `M${mid(X1)},306 V372`, label: arch.storeLink, lx: mid(X1) + 10, ly: 343, anchor: "start" },
    { d: "M700,129 H659 V252 H618", label: arch.agentLink, lx: 650, ly: 190, rot: true },
    { d: "M618,286 H700", label: "read API", lx: 659, ly: 279 },
    { d: `M276,428 H340 V476 H${mid(X2)} V446`, label: arch.twinLink, lx: 560, ly: 470, twin: true },
    { d: `M${mid(X2)},372 V306`, label: "receive-only", lx: mid(X2) + 10, ly: 343, anchor: "start", twin: true },
  ];
  return { height: 500, nodes, flows };
}

// Four rows: the same path with the edge plane blended in. The edge runtime sits
// under the Thor and the broker heads the cloud column, so everything leaves the
// booth on one uplink and the broker's rules fan it out to the stream and the twin.
function edgeLayout(e: EdgePlane): Layout {
  const R = [84, 208, 332, 456];
  const down = (x: number, row: number, label: string, twin = false): Flow =>
    ({ d: `M${mid(x)},${R[row] + H} V${R[row + 1]}`, label, lx: mid(x) + 10, ly: R[row] + H + 29, anchor: "start", twin });
  const nodes: Node[] = [
    { id: "dog", x: X0, y: R[0], title: "Unitree Go2", note: "12 joints · IMU · battery · L1 lidar" },
    { id: "orin", x: X0, y: R[1], title: "Robot link · Jetson Orin", note: "DDS → HTTPS · safety deadman" },
    { id: "thor", x: X0, y: R[2], title: "NVIDIA Jetson AGX Thor", note: "vision · telemetry · maneuvers" },
    { id: "edge", x: X0, y: R[3], title: e.runtime, note: e.runtimeNote, roadmap: true },
    { id: "broker", x: X1, y: R[0], title: e.broker, note: e.brokerNote, cloud: true, roadmap: true },
    { id: "hub", x: X1, y: R[1], title: arch.ingest, note: "telemetry stream", cloud: true },
    { id: "fn", x: X1, y: R[2], title: arch.compute, note: arch.computeNote, cloud: true },
    { id: "store", x: X1, y: R[3], title: arch.store, note: arch.storeNote, cloud: true },
    { id: "rt", x: X2, y: R[0], title: arch.realtime, note: "live twin · ~15 frames/s", cloud: true },
    { id: "web", x: X2, y: R[1], title: arch.hosting, note: "this dashboard", cloud: true },
    { id: "agent", x: X2, y: R[2], title: arch.agent, note: arch.agentNote, cloud: true },
  ];
  const flows: Flow[] = [
    down(X0, 0, "DDS · 20 Hz"),
    down(X0, 1, "/vitals · /joints"),
    down(X0, 2, e.localLink),
    { d: `M276,${R[3] + 37} H322 V${R[0] + 37} H382`, label: e.uplink, lx: 312, ly: (R[0] + R[3]) / 2 + 37, rot: true },
    down(X1, 0, e.streamRule),
    down(X1, 1, arch.ingestLink),
    down(X1, 2, arch.storeLink),
    { d: `M618,${R[0] + 37} H700`, label: e.twinRule, lx: 659, ly: R[0] + 30, twin: true },
    down(X2, 0, "receive-only", true),
    { d: `M618,${R[2] + 20} H659 V${R[1] + 37} H700`, label: "read API", lx: 675, ly: (R[1] + R[2]) / 2 + 28, rot: true },
    { d: `M700,${R[2] + 54} H618`, label: e.agentLink, lx: 659, ly: R[2] + 47 },
  ];
  return { height: 566, nodes, flows, tag: e.tag, legend: { x: X2, y: R[3], head: e.legendHead, lines: e.legend } };
}

const LAYOUT = edgePlane ? edgeLayout(edgePlane) : directLayout();

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
        <svg className="arch-svg" viewBox={`0 0 980 ${LAYOUT.height}`} role="img" aria-label={`Data flow: Unitree Go2 to Jetson Orin robot link to NVIDIA Jetson AGX Thor at the booth, then ${arch.ingest}, ${arch.compute} and ${arch.store}; ${arch.agent} reads through the query API; ${arch.realtime} carries the live twin to ${arch.hosting}.${edgePlane ? ` ${edgePlane.aria}` : ""}`}>
          <defs>
            <marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L8 4 L0 8 Z" className="arch-arrowhead" /></marker>
          </defs>
          <rect x="18" y="28" width="282" height={LAYOUT.height - 44} rx="8" className="arch-zone" />
          <text x="34" y="54" className="arch-zone-label">Booth edge</text>
          <rect x="356" y="28" width="606" height={LAYOUT.height - 44} rx="8" className="arch-zone cloud" />
          <text x="372" y="54" className="arch-zone-label cloud">{arch.region}</text>
          {LAYOUT.flows.map((f, i) => (
            <g key={i} className={`arch-flow ${f.twin ? "twin" : ""}`}>
              <path d={f.d} markerEnd="url(#arrow)" />
              <text x={f.lx} y={f.ly} textAnchor={f.anchor ?? "middle"} className="arch-flow-label"
                transform={f.rot ? `rotate(-90 ${f.lx} ${f.ly})` : undefined}>{f.label}</text>
            </g>
          ))}
          {LAYOUT.nodes.map((n) => (
            <g key={n.id} className={`arch-node ${n.cloud ? "cloud" : ""} ${n.roadmap ? "roadmap" : ""}`}>
              <rect x={n.x} y={n.y} width={W} height={H} rx="6" />
              <text x={n.x + 16} y={n.y + 31} className="arch-node-title">{n.title}</text>
              <text x={n.x + 16} y={n.y + 54} className="arch-node-note">{n.note}</text>
              {n.roadmap && <text x={n.x + W - 12} y={n.y + 15} textAnchor="end" className="arch-node-tag">{LAYOUT.tag}</text>}
            </g>
          ))}
          {LAYOUT.legend && (
            <g className="arch-legend">
              <rect x={LAYOUT.legend.x} y={LAYOUT.legend.y + 6} width="26" height="14" rx="3" />
              <text x={LAYOUT.legend.x + 36} y={LAYOUT.legend.y + 18} className="arch-node-tag">{LAYOUT.legend.head}</text>
              {LAYOUT.legend.lines.map((l, i) => <text key={i} x={LAYOUT.legend!.x} y={LAYOUT.legend!.y + 40 + i * 15} className="arch-legend-line">{l}</text>)}
            </g>
          )}
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
