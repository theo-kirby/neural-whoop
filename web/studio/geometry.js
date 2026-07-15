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

// A "prototype map" greybox tile texture: a 2 m x 2 m block (checkerboard of light/dark grey
// squares) with bright white 1 m gridlines, half-meter intersection dots, and "1 METER" /
// "[PROTOTYPE MAP]" labels baked along the lines. Repeats across the room's faces so each square is
// exactly one metre. Returns a THREE.Texture (RepeatWrapping, sRGB).
function greyboxTexture() {
  const S = 512, M = S / 2;                  // 512 px = 2 m  ->  256 px per metre
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = S;
  const ctx = canvas.getContext("2d");
  // Neutral greys, low contrast: a faint checker with soft grey (not white) gridlines.
  const DARK = "#5c5c5c", LIGHT = "#646464", LINE = "#7d7d7d", DOT = "#8a8a8a";

  // Checkerboard: dark on the (0,0)/(M,M) diagonal, light on the off-diagonal.
  ctx.fillStyle = DARK; ctx.fillRect(0, 0, S, S);
  ctx.fillStyle = LIGHT; ctx.fillRect(M, 0, M, M); ctx.fillRect(0, M, M, M);

  // White gridlines at every metre (0/M/S; edge lines straddle the seam and complete on the tile
  // next door, so the repeat is continuous).
  ctx.strokeStyle = LINE; ctx.lineWidth = 5;
  for (const p of [0, M, S]) {
    ctx.beginPath(); ctx.moveTo(p, 0); ctx.lineTo(p, S); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, p); ctx.lineTo(S, p); ctx.stroke();
  }
  // Half-metre dots on the lines (mark x half, half x mark).
  ctx.fillStyle = DOT;
  const marks = [0, M, S], halves = [M / 2, (3 * M) / 2];
  const dot = (x, y) => { ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2); ctx.fill(); };
  for (const a of marks) for (const b of halves) { dot(a, b); dot(b, a); }

  // Labels along the lines (faint grey), repeated every 2 m like the reference.
  ctx.fillStyle = "rgba(200,200,200,0.28)";
  ctx.font = "bold 34px system-ui, -apple-system, sans-serif";
  ctx.textBaseline = "alphabetic";
  ctx.save(); ctx.translate(24, M - 16); ctx.fillText("1 METER", 0, 0); ctx.restore();
  ctx.save(); ctx.translate(M - 16, S - 24); ctx.rotate(-Math.PI / 2); ctx.fillText("[PROTOTYPE MAP]", 0, 0); ctx.restore();

  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  return tex;
}

// A bounded reference room (sim frame, added under `world`): a solid `size` m greybox cube resting
// on z=floorZ, tiled into `cell` m "prototype map" squares (see greyboxTexture). Built with
// THREE.BackSide so the near walls are culled and you always look INTO the room — the drone
// (hovering ~1.2 m up inside) is never occluded as you orbit. Returns the THREE.Mesh.
export function buildRoom(world, { size = 10, cell = 1, floorZ = 0 } = {}) {
  const cz = floorZ + size / 2;              // room centre height (sim z)
  const tex = greyboxTexture();
  const reps = size / 2;                      // texture block is 2 m; repeat to cover the face
  tex.repeat.set(reps, reps);

  const room = new THREE.Mesh(
    new THREE.BoxGeometry(size, size, size),
    new THREE.MeshStandardMaterial({ map: tex, roughness: 1, metalness: 0, side: THREE.BackSide }));
  room.position.set(0, 0, cz);
  room.receiveShadow = true;
  world.add(room);
  return room;
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
