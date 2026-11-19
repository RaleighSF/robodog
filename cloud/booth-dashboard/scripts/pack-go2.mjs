// Pack the MuJoCo Menagerie Unitree Go2 OBJ meshes (BSD-3-Clause, (c) Unitree
// Robotics) into a compact binary per part for the browser:
//   [Int16 x,y,z per vertex, quantized to the part's bounding box] + [indices]
// Normals are recomputed in the browser. Usage:
//   GO2_ASSETS=<path to mujoco_menagerie/unitree_go2> npm run pack:go2
import { readFileSync, writeFileSync, mkdirSync, copyFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const src = process.env.GO2_ASSETS;
if (!src) throw new Error("set GO2_ASSETS to the mujoco_menagerie/unitree_go2 directory");
const out = "public/models/go2";
mkdirSync(out, { recursive: true });

const manifest = { source: "google-deepmind/mujoco_menagerie unitree_go2 (BSD-3-Clause)", parts: {} };
let total = 0;
for (const file of readdirSync(join(src, "assets")).filter((f) => f.endsWith(".obj")).sort()) {
  const name = file.replace(/\.obj$/, "");
  const verts = [];
  const tris = [];
  for (const line of readFileSync(join(src, "assets", file), "utf8").split("\n")) {
    if (line.startsWith("v ")) {
      const [, x, y, z] = line.trim().split(/\s+/);
      verts.push(+x, +y, +z);
    } else if (line.startsWith("f ")) {
      const idx = line.trim().split(/\s+/).slice(1).map((t) => {
        const i = parseInt(t.split("/")[0], 10);
        return i < 0 ? verts.length / 3 + i : i - 1;
      });
      for (let k = 1; k + 1 < idx.length; k++) tris.push(idx[0], idx[k], idx[k + 1]); // fan-triangulate
    }
  }
  const n = verts.length / 3;
  const min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < n; i++) for (let a = 0; a < 3; a++) {
    min[a] = Math.min(min[a], verts[3 * i + a]); max[a] = Math.max(max[a], verts[3 * i + a]);
  }
  const pos = new Int16Array(n * 3);
  for (let i = 0; i < n; i++) for (let a = 0; a < 3; a++) {
    const span = max[a] - min[a] || 1;
    pos[3 * i + a] = Math.round(((verts[3 * i + a] - min[a]) / span) * 65534 - 32767);
  }
  const index = n <= 65535 ? new Uint16Array(tris) : new Uint32Array(tris);
  const buf = Buffer.concat([Buffer.from(pos.buffer), Buffer.from(index.buffer)]);
  writeFileSync(join(out, `${name}.bin`), buf);
  manifest.parts[name] = { vertices: n, indices: tris.length, index: n <= 65535 ? "u16" : "u32", min, max, bytes: buf.length };
  total += buf.length;
}
writeFileSync(join(out, "manifest.json"), JSON.stringify(manifest, null, 1));
copyFileSync(join(src, "LICENSE"), join(out, "LICENSE.txt"));
console.log(`packed ${Object.keys(manifest.parts).length} parts, ${(total / 1e6).toFixed(2)} MB`);
