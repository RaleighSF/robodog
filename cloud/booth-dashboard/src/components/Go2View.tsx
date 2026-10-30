"use client";
// 3D Unitree Go2 from the MuJoCo Menagerie model (BSD-3-Clause, (c) Unitree
// Robotics; notice in public/models/go2/LICENSE.txt). Rig mirrors go2.xml.
// Legs are posed from the POSTURE CLASS, not raw joint angles, until the
// LowState joint order is confirmed on the real dog (PRODUCT.md).
import type { MotionFeed } from "@/lib/motion";
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { Joint, jointState, Leg, Posture } from "@/lib/model";

type PartMeta = { vertices: number; indices: number; index: "u16" | "u32"; min: number[]; max: number[] };
const BASE = "/models/go2";
const L = 0.213;                 // thigh and calf length (go2.xml)
const FOOT_R = 0.022;
const HIP_X = 0.1934;

const COLORS = { black: 0x1b2128, white: 0xc9d3dd, gray: 0x5f6d7b, metal: 0x9aa7b4 };
const STATUS = { ok: 0x3fd68c, caution: 0xffb224, warning: 0xff5c5c, unknown: 0x8494a3 };

// [mesh, material] per body; right-side legs use mirror meshes (go2.xml).
const LEG_DEF: Record<Leg, { pos: [number, number, number]; hipQuat: [number, number, number, number] | null; thighY: number; mirror: boolean }> = {
  FL: { pos: [HIP_X, 0.0465, 0], hipQuat: null, thighY: 0.0955, mirror: false },
  FR: { pos: [HIP_X, -0.0465, 0], hipQuat: [4.63268e-5, 1, 0, 0], thighY: -0.0955, mirror: true },
  RL: { pos: [-HIP_X, 0.0465, 0], hipQuat: [4.63268e-5, 0, 1, 0], thighY: 0.0955, mirror: false },
  RR: { pos: [-HIP_X, -0.0465, 0], hipQuat: [2.14617e-9, 4.63268e-5, 4.63268e-5, -1], thighY: -0.0955, mirror: true },
};

// Joint targets per posture (hip abduction, thigh, calf), radians. "home" is
// go2.xml's keyframe; the others are within go2.xml's joint ranges.
const POSES: Record<Posture, Record<"front" | "rear", [number, number, number]>> = {
  standing: { front: [0, 0.9, -1.8], rear: [0, 0.9, -1.8] },
  low: { front: [0, 0.75, -1.55], rear: [0, 2.05, -2.6] },
  lying: { front: [0, 1.12, -2.7], rear: [0, 1.12, -2.7] },
  unknown: { front: [0, 0.9, -1.8], rear: [0, 0.9, -1.8] },
};

async function loadPart(name: string, meta: PartMeta): Promise<THREE.BufferGeometry> {
  const buf = await (await fetch(`${BASE}/${name}.bin`)).arrayBuffer();
  const q = new Int16Array(buf, 0, meta.vertices * 3);
  const pos = new Float32Array(meta.vertices * 3);
  for (let i = 0; i < meta.vertices; i++) for (let a = 0; a < 3; a++) {
    pos[3 * i + a] = meta.min[a] + ((q[3 * i + a] + 32767) / 65534) * (meta.max[a] - meta.min[a]);
  }
  const off = meta.vertices * 6;
  // u32 indices may start at an offset that is not 4-byte aligned: copy them out.
  const idx = meta.index === "u16" ? new Uint16Array(buf, off, meta.indices) : new Uint32Array(buf.slice(off, off + meta.indices * 4));
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setIndex(new THREE.BufferAttribute(idx, 1));
  g.computeVertexNormals();
  return g;
}

export interface Go2Props { posture: Posture; walking: boolean; joints: Joint[]; roll: number; pitch: number; stale: boolean; orbit: boolean; motion?: MotionFeed }

// Live stream joint order: FR, FL, RR, RL legs x hip/thigh/calf (confirmed on the robot).
const STREAM_LEG: Record<Leg, number> = { FR: 0, FL: 1, RR: 2, RL: 3 };

export default function Go2View(props: Go2Props) {
  const host = useRef<HTMLDivElement>(null);
  const live = useRef(props);
  live.current = props;

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    el.appendChild(renderer.domElement);
    renderer.domElement.setAttribute("aria-hidden", "true");

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(30, 1, 0.05, 20);
    scene.add(new THREE.HemisphereLight(0xe8eef4, 0x0b0e12, 1.0));
    const key = new THREE.DirectionalLight(0xffffff, 2.2); key.position.set(1.5, 2.5, 1.8); scene.add(key);
    const rim = new THREE.DirectionalLight(0xd6e2ee, 1.1); rim.position.set(-2, 1.2, -1.5); scene.add(rim);

    // Floor: one hairline disc + crosshair on the ground plane (instrument, not a stage).
    const floor = new THREE.Group();
    const ring = new THREE.Mesh(new THREE.RingGeometry(0.62, 0.624, 128), new THREE.MeshBasicMaterial({ color: 0x2c363f, side: THREE.DoubleSide }));
    ring.rotation.x = -Math.PI / 2; floor.add(ring);
    const tick = new THREE.LineBasicMaterial({ color: 0x1e262e });
    for (const [a, b] of [[[-0.62, 0], [0.62, 0]], [[0, -0.62], [0, 0.62]]] as const) {
      floor.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(a[0], 0.001, a[1]), new THREE.Vector3(b[0], 0.001, b[1])]), tick));
    }
    void floor;   // floor hairlines removed: they competed with the attitude ring (finish review)

    // MuJoCo is Z-up; three is Y-up.
    const world = new THREE.Group(); world.rotation.x = -Math.PI / 2; scene.add(world);
    const base = new THREE.Group(); world.add(base);
    const mat = (c: number, metal = 0.35, rough = 0.55) => new THREE.MeshStandardMaterial({ color: c, metalness: metal, roughness: rough });
    const legs: Record<string, { hip: THREE.Group; thigh: THREE.Group; calf: THREE.Group; foot: THREE.Mesh; housings: Record<string, THREE.MeshStandardMaterial>; markers: Record<string, THREE.Mesh> }> = {};
    const markerMat: Record<string, THREE.MeshBasicMaterial> = {};

    let disposed = false;
    let raf = 0;
    (async () => {
      const manifest = (await (await fetch(`${BASE}/manifest.json`)).json()) as { parts: Record<string, PartMeta> };
      const geo: Record<string, THREE.BufferGeometry> = {};
      await Promise.all(Object.entries(manifest.parts).map(async ([n, m]) => { geo[n] = await loadPart(n, m); }));
      if (disposed) return;
      for (const [m, c] of [["base_0", COLORS.black], ["base_1", COLORS.black], ["base_2", COLORS.black], ["base_3", COLORS.white], ["base_4", COLORS.gray]] as const) {
        base.add(new THREE.Mesh(geo[m], mat(c, c === COLORS.white ? 0.1 : 0.3, c === COLORS.white ? 0.35 : 0.6)));
      }
      for (const leg of Object.keys(LEG_DEF) as Leg[]) {
        const d = LEG_DEF[leg];
        const hip = new THREE.Group(); hip.position.set(...d.pos); base.add(hip);
        const housings: Record<string, THREE.MeshStandardMaterial> = { hip: mat(COLORS.metal, 0.6, 0.35), thigh: mat(COLORS.metal, 0.6, 0.35), calf: mat(COLORS.gray) };
        const hipMeshes = [new THREE.Mesh(geo.hip_0, housings.hip), new THREE.Mesh(geo.hip_1, mat(COLORS.gray))];
        if (d.hipQuat) { const [w, x, y, z] = d.hipQuat; hipMeshes.forEach((m) => m.quaternion.set(x, y, z, w)); }
        hipMeshes.forEach((m) => hip.add(m));
        const thigh = new THREE.Group(); thigh.position.set(0, d.thighY, 0); hip.add(thigh);
        thigh.add(new THREE.Mesh(geo[d.mirror ? "thigh_mirror_0" : "thigh_0"], housings.thigh));
        thigh.add(new THREE.Mesh(geo[d.mirror ? "thigh_mirror_1" : "thigh_1"], mat(COLORS.gray)));
        const calf = new THREE.Group(); calf.position.set(0, 0, -L); thigh.add(calf);
        calf.add(new THREE.Mesh(geo[d.mirror ? "calf_mirror_0" : "calf_0"], housings.calf));
        calf.add(new THREE.Mesh(geo[d.mirror ? "calf_mirror_1" : "calf_1"], mat(COLORS.black)));
        const foot = new THREE.Mesh(geo.foot, mat(COLORS.black)); foot.position.set(0, 0, -L); calf.add(foot);
        // Severity markers (size ramp, not colour alone) at each joint centre.
        const markers: Record<string, THREE.Mesh> = {};
        for (const [seg, parent, z] of [["hip", hip, 0], ["thigh", thigh, 0], ["calf", calf, 0]] as const) {
          const mm = (markerMat[`${leg}_${seg}`] = new THREE.MeshBasicMaterial({ color: STATUS.ok, transparent: true, opacity: 0, depthTest: false }));
          const mk = new THREE.Mesh(new THREE.RingGeometry(0.03, 0.036, 48), mm);
          mk.position.set(0, seg === "thigh" ? d.thighY * 0.35 : 0, z); mk.renderOrder = 10;
          parent.add(mk); markers[seg] = mk;
        }
        legs[leg] = { hip, thigh, calf, foot, housings, markers };
      }
      const angles: Record<string, [number, number, number]> = {};
      const att = { r: 0, p: 0 };
      const footPos = new THREE.Vector3();
      const start = performance.now();
      const resize = () => {
        const w = el.clientWidth, h = el.clientHeight;
        renderer.setSize(w, h, false); camera.aspect = w / Math.max(h, 1); camera.updateProjectionMatrix();
      };
      resize();
      const ro = new ResizeObserver(resize); ro.observe(el);
      const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      const baseCol = { hip: new THREE.Color(COLORS.metal), thigh: new THREE.Color(COLORS.metal), calf: new THREE.Color(COLORS.gray) };
      const loop = () => {
        const p = live.current;
        const t = (performance.now() - start) / 1000;
        const pose = POSES[p.posture];
        // Live joint angles when every joint reports (order confirmed on the robot
        // 2026-10-30); otherwise the posture pose. Same sign convention as go2.xml.
        const q = (name: string) => p.joints.find((x) => x.name === name)?.q ?? null;
        const liveQ = !p.stale && p.joints.length === 12 && p.joints.every((j) => j.q != null);
        const mirror = p.motion?.sample() ?? null;          // ~20 Hz live mirror, when streaming
        for (const leg of Object.keys(LEG_DEF) as Leg[]) {
          const si = STREAM_LEG[leg] * 3;
          const target: [number, number, number] = mirror ? [mirror.q[si], mirror.q[si + 1], mirror.q[si + 2]]
            : liveQ ? [q(`${leg}_hip`)!, q(`${leg}_thigh`)!, q(`${leg}_calf`)!] : pose[leg.startsWith("F") ? "front" : "rear"];
          const cur = (angles[leg] ??= [...target] as [number, number, number]);
          const phase = leg === "FL" || leg === "RR" ? 0 : Math.PI;
          const gait = p.walking && !reduced && !mirror ? [0, 0.22 * Math.sin(t * 9 + phase), -0.32 * Math.max(0, Math.sin(t * 9 + phase))] : [0, 0, 0];
          const ease = mirror ? 0.45 : 0.08;                // follow the mirror closely; ease into postures
          for (let k = 0; k < 3; k++) cur[k] += (target[k] + gait[k] - cur[k]) * ease;
          const lg = legs[leg];
          lg.hip.rotation.x = cur[0]; lg.thigh.rotation.y = cur[1]; lg.calf.rotation.y = cur[2];
          // Joint health: housing tint + severity marker ramp.
          for (const seg of ["hip", "thigh", "calf"] as const) {
            const j = p.joints.find((x) => x.name === `${leg}_${seg}`);
            const st = p.stale ? "unknown" : jointState(j?.temp ?? null);
            const col = lg.housings[seg].color;
            col.copy(baseCol[seg]);
            if (st === "caution" || st === "warning") col.lerp(new THREE.Color(STATUS[st]), st === "warning" ? 0.75 : 0.55);
            const mk = lg.markers[seg];
            (mk.material as THREE.MeshBasicMaterial).color.setHex(STATUS[st]);
            (mk.material as THREE.MeshBasicMaterial).opacity = st === "caution" || st === "warning" ? 0.95 : 0;
            const scale = st === "warning" ? 2.2 + (reduced ? 0 : 0.25 * Math.sin(t * 6)) : st === "caution" ? 1.5 : 1;
            mk.scale.setScalar(scale);
            mk.quaternion.copy(camera.quaternion);                                  // billboard
            mk.parent?.updateMatrixWorld();
            const parentQ = new THREE.Quaternion(); mk.parent?.getWorldQuaternion(parentQ);
            mk.quaternion.premultiply(parentQ.invert());
          }
        }
        // Attitude from the IMU (live mirror when streaming, else vitals), then
        // lower the body until the lowest foot meets the floor (forward
        // kinematics), so a raised paw can never tip the body.
        const k = mirror ? 0.45 : 0.08;
        att.r += ((mirror?.rpy ? mirror.rpy[0] : p.roll) - att.r) * k;
        att.p += ((mirror?.rpy ? mirror.rpy[1] : p.pitch) - att.p) * k;
        base.rotation.set(att.r, att.p, 0, "ZYX");
        base.position.z = 0;
        world.updateMatrixWorld(true);
        let lowest = Infinity;
        for (const lg of Object.values(legs)) lowest = Math.min(lowest, world.worldToLocal(lg.foot.getWorldPosition(footPos)).z);
        base.position.z = FOOT_R - lowest;
        // Dog faces screen-left with its left legs nearest; a gentle sway (not an
        // orbit) keeps every leg inside its dial quadrant.
        const ang = -1.22 + (p.orbit && !reduced ? 0.3 * Math.sin(t * 0.21) : 0);
        camera.position.set(Math.cos(ang) * 1.6, 0.66, Math.sin(ang) * 1.6);   // framed for the centre gap between dial quadrants
        camera.lookAt(0, base.position.z * 0.55 + 0.06, 0);
        renderer.render(scene, camera);
        raf = requestAnimationFrame(loop);
      };
      loop();
      (el as HTMLDivElement & { _ro?: ResizeObserver })._ro = ro;
    })();
    return () => {
      disposed = true; cancelAnimationFrame(raf);
      (el as HTMLDivElement & { _ro?: ResizeObserver })._ro?.disconnect();
      renderer.dispose(); el.removeChild(renderer.domElement);
    };
  }, []);

  return <div ref={host} style={{ position: "absolute", inset: 0 }} />;
}
