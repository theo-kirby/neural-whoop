// Shared gate/trail geometry helpers (sim frame), ported from neural-whoop-lab and trimmed to
// what the Studio replay needs (gates + per-drone trails). Per-drone identity tints come from
// DRONE_TINTS so swarm/multi-drone racers are tellable apart.

import * as THREE from "three";

// Gate states carry real meaning, so they keep colour: the active "next" gate lights up yellow,
// passed gates go green, upcoming stay grey.
export const GATE_COLORS = { passed: 0x39d98a, next: 0xffd23f, upcoming: 0x5a5a5a };

// Per-drone identity tints for group episodes (the glyph centre marker), so multiple racers are
// tellable apart at a glance.
export const DRONE_TINTS = [
  0x4ea1ff, // blue
  0xff5d5d, // red
  0xffe14a, // yellow
  0x53e0a0, // green
  0xc77dff, // violet
  0xff9d3c, // orange
];

// Scene-marker colours for gateless follow/formation tasks: the moving target is cyan, the
// formation anchor amber, slots faint grey. (Gates keep their own GATE_COLORS above.)
export const SCENE_COLORS = { target: 0x35e0e0, anchor: 0xffb13a, slot: 0x8a8a8a };

// Per-command tint for the target marker when a command channel is present, indexed by the raw
// command value: 0=STOP (red), 1=GO/NEAR (cyan), 2=FAR (amber). Mirrors nw-viz/src/palette.js.
export const COMMAND_TINTS = [0xff5d5d, 0x35e0e0, 0xffd23f];

// Turbo colormap (x in [0,1] -> [r,g,b] in [0,1]) for heat-coloured speed trails. Ported from
// ../nw-viz/src/palette.js so the Studio trail matches the MP4 renderer.
export function turbo(x) {
  x = Math.min(1, Math.max(0, x));
  const v1 = x, v2 = x * x, v3 = x * x * x, v4 = v2 * v2, v5 = v2 * v3;
  const r = 0.13572138 + 4.6153926 * v1 - 42.66032258 * v2 + 132.13108234 * v3
    - 152.94239396 * v4 + 59.28637943 * v5;
  const g = 0.09140261 + 2.19418839 * v1 + 4.84296658 * v2 - 14.18503333 * v3
    + 4.27729857 * v4 + 2.82956604 * v5;
  const b = 0.1066733 + 12.64194608 * v1 - 60.58204836 * v2 + 110.36276771 * v3
    - 89.90310912 * v4 + 27.34824973 * v5;
  return [Math.min(1, Math.max(0, r)), Math.min(1, Math.max(0, g)), Math.min(1, Math.max(0, b))];
}

function p95(values, floor = 1.0) {
  if (!values.length) return floor;
  const sorted = [...values].sort((a, b) => a - b);
  const idx = Math.min(sorted.length - 1, Math.floor(0.95 * (sorted.length - 1)));
  return Math.max(floor, sorted[idx]);
}

export function disposeGroup(arr, parent) {
  for (const o of arr) {
    o.geometry?.dispose();
    o.material?.dispose?.();
    parent.remove(o);
  }
}

// Build a wireframe sphere per omnidirectional gate (`{pos, radius}`), added under `world`.
// Returns the LineSegments array so a caller can recolor them by pass state.
export function buildGates(world, gates) {
  const lines = [];
  for (const gate of gates) {
    const r = gate.radius ?? 0.45;
    const sphere = new THREE.SphereGeometry(r, 16, 12);
    const geo = new THREE.WireframeGeometry(sphere);
    sphere.dispose();
    const line = new THREE.LineSegments(
      geo,
      new THREE.LineBasicMaterial({ color: GATE_COLORS.upcoming, transparent: true, opacity: 0.55 })
    );
    line.position.set(gate.pos[0], gate.pos[1], gate.pos[2]);
    world.add(line);
    lines.push(line);
  }
  return lines;
}

// A solid emissive marker sphere for a moving target/anchor (sim frame, added under `world`). The
// caller positions it per frame from `frame.scene.{target,anchor}` and may recolor it by command.
export function buildMarker(world, color, radius = 0.16) {
  const geo = new THREE.SphereGeometry(radius, 16, 12);
  const mesh = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.85 }));
  world.add(mesh);
  return mesh;
}

// A faint wire ring marking a formation slot (sim frame). Lies flat in the world xy-plane (the
// slots ring the anchor horizontally), so it reads as a target pad from the wide + top views.
export function buildSlot(world, radius = 0.18) {
  const geo = new THREE.TorusGeometry(radius, 0.012, 8, 24);
  const mesh = new THREE.Mesh(geo, new THREE.MeshBasicMaterial(
    { color: SCENE_COLORS.slot, transparent: true, opacity: 0.55 }));
  world.add(mesh);
  return mesh;
}

// Fallback tile palette if a caller doesn't pass one (near-black "dark" greybox). Callers
// (environment.js) pass a theme-specific palette so light/dark share this one primitive.
const FALLBACK_TILE = {
  tileA: "#1c1c1c", tileB: "#232323", line: "#3a3a3a", dot: "#444444",
  label: "rgba(150,150,150,0.22)",
};

// A "prototype map" greybox tile texture: a 2 m x 2 m block (checkerboard of two grey squares) with
// 1 m gridlines, half-meter intersection dots, and "1 METER" / "PROTOTYPE" labels baked along the
// lines. `palette` (tileA/tileB/line/dot/label) themes it; `repeatX`/`repeatY` tile it to cover a
// face at 1 m/square (per-axis so walls stay square when height != footprint). Returns a
// THREE.CanvasTexture (RepeatWrapping, sRGB).
function greyboxTexture(palette = FALLBACK_TILE, repeatX = 1, repeatY = 1) {
  const S = 512, M = S / 2;                  // 512 px = 2 m  ->  256 px per metre
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = S;
  const ctx = canvas.getContext("2d");
  const { tileA, tileB, line, dot, label } = palette;

  // Checkerboard: tileA on the (0,0)/(M,M) diagonal, tileB on the off-diagonal.
  ctx.fillStyle = tileA; ctx.fillRect(0, 0, S, S);
  ctx.fillStyle = tileB; ctx.fillRect(M, 0, M, M); ctx.fillRect(0, M, M, M);

  // Gridlines at every metre (0/M/S; edge lines straddle the seam and complete on the tile next
  // door, so the repeat is continuous).
  ctx.strokeStyle = line; ctx.lineWidth = 5;
  for (const p of [0, M, S]) {
    ctx.beginPath(); ctx.moveTo(p, 0); ctx.lineTo(p, S); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, p); ctx.lineTo(S, p); ctx.stroke();
  }
  // Half-metre dots on the lines (mark x half, half x mark).
  ctx.fillStyle = dot;
  const marks = [0, M, S], halves = [M / 2, (3 * M) / 2];
  const dotAt = (x, y) => { ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2); ctx.fill(); };
  for (const a of marks) for (const b of halves) { dotAt(a, b); dotAt(b, a); }

  // Labels along the lines (faint), repeated every 2 m like the reference. Read correctly (not
  // mirrored) on the floor, which is built as a front-facing plane below.
  ctx.fillStyle = label;
  ctx.font = "bold 34px system-ui, -apple-system, sans-serif";
  ctx.textBaseline = "alphabetic";
  ctx.save(); ctx.translate(24, M - 16); ctx.fillText("1 METER", 0, 0); ctx.restore();
  ctx.save(); ctx.translate(M - 16, S - 24); ctx.rotate(-Math.PI / 2); ctx.fillText("PROTOTYPE", 0, 0); ctx.restore();

  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  tex.repeat.set(repeatX, repeatY);
  return tex;
}

// A bounded reference room (sim frame): a `size`×`size` footprint × `height` tall greybox resting on
// z=floorZ, tiled into 1 m "prototype map" squares (see greyboxTexture). Returns a THREE.Group
// (added under `world`) holding:
//   - a FRONT-facing (DoubleSide) floor plane just above z=floorZ — the surface people read, so its
//     baked "PROTOTYPE" / "1 METER" text reads correctly (not mirrored);
//   - the four walls + ceiling as a BackSide box, so near walls cull and never occlude the drone
//     (hovering inside) as you orbit. Per-face texture repeats keep every square 1 m even when the
//     height differs from the footprint. Dispose the whole group (geometry + per-face textures) to
//     tear it down.
export function buildRoom(world, { size = 10, height = size, floorZ = 0, palette = FALLBACK_TILE } = {}) {
  const group = new THREE.Group();
  const rH = size / 2, rV = height / 2;      // texture block is 2 m -> repeat = metres / 2

  // Floor: its own DoubleSide plane (sim XY, normal +Z), sitting a hair above the box bottom face
  // so there's no z-fight and the readable text isn't on a mirrored BackSide.
  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(size, size),
    new THREE.MeshStandardMaterial(
      { map: greyboxTexture(palette, rH, rH), roughness: 1, metalness: 0, side: THREE.DoubleSide }));
  floor.position.set(0, 0, floorZ + 0.003);
  floor.receiveShadow = true;
  group.add(floor);

  // Walls + ceiling: a BackSide box. BoxGeometry(size,size,height) face order is
  // [+X,-X,+Y,-Y,+Z,-Z]; ±X/±Y are walls (repeat height×footprint / footprint×height), ±Z the
  // ceiling/floor faces (footprint×footprint). The -Z face is hidden under the floor plane above.
  const wall = (rx, ry) => new THREE.MeshStandardMaterial(
    { map: greyboxTexture(palette, rx, ry), roughness: 1, metalness: 0, side: THREE.BackSide });
  const mats = [wall(rV, rH), wall(rV, rH), wall(rH, rV), wall(rH, rV), wall(rH, rH), wall(rH, rH)];
  const box = new THREE.Mesh(new THREE.BoxGeometry(size, size, height), mats);
  box.position.set(0, 0, floorZ + height / 2);
  box.receiveShadow = true;
  group.add(box);

  world.add(group);
  return group;
}

// Dim grey full path + a heat-coloured "traveled" overlay revealed via drawRange. The traveled
// trail is turbo-mapped by speed (normalized to a fixed p95 so colours don't flicker frame to
// frame), so you read where the drone was fast vs. slow. Returns {full, done}.
export function buildTrail(world, frames) {
  const pathPts = frames.map((f) => new THREE.Vector3(f.pos[0], f.pos[1], f.pos[2]));
  const geo = new THREE.BufferGeometry().setFromPoints(pathPts);
  const full = new THREE.Line(geo, new THREE.LineBasicMaterial({ color: 0x3a3a3a }));

  const doneGeo = geo.clone();
  const speeds = frames.map((f) => Math.hypot(f.vel[0], f.vel[1], f.vel[2]));
  const vmax = p95(speeds, 1.0);
  const colors = new Float32Array(frames.length * 3);
  for (let k = 0; k < frames.length; k++) {
    const [r, g, b] = turbo(speeds[k] / vmax);
    colors[k * 3] = r; colors[k * 3 + 1] = g; colors[k * 3 + 2] = b;
  }
  doneGeo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  const done = new THREE.Line(doneGeo, new THREE.LineBasicMaterial({ vertexColors: true }));
  world.add(full);
  world.add(done);
  return { full, done };
}
