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

// A bounded reference room (sim frame, added under `world`): a `size` m cube resting on z=floorZ,
// tiled into `cell` m squares. Dark-grey surfaces with lighter-grey gridlines on all six faces, a
// brighter edge outline, and a floating "1 m³" label calling out the cell scale — a fixed metric
// backdrop for the real-drone view (the drone hovers ~1.2 m up inside it). Returns the THREE.Group.
export function buildRoom(world, { size = 10, cell = 1, floorZ = 0 } = {}) {
  const half = size / 2;
  const cz = floorZ + half;                 // room centre height (sim z)
  const room = new THREE.Group();
  const DARK = 0x2a2a2a, LINE = 0x565656, EDGE = 0x7a7a7a;

  // One square face's gridlines in the local XY plane, centred at origin (spans ±half each axis).
  function faceGrid() {
    const pts = [];
    for (let i = -half; i <= half + 1e-6; i += cell) {
      pts.push(-half, i, 0, half, i, 0);    // lines parallel to local x
      pts.push(i, -half, 0, i, half, 0);    // lines parallel to local y
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    return new THREE.LineSegments(
      geo, new THREE.LineBasicMaterial({ color: LINE, transparent: true, opacity: 0.55 }));
  }
  // Place a face grid at `pos` with Euler `rot` (radians, XYZ) so its plane normal aims outward.
  function addFace(pos, rot = [0, 0, 0]) {
    const g = faceGrid();
    g.position.set(pos[0], pos[1], pos[2]);
    g.rotation.set(rot[0], rot[1], rot[2]);
    room.add(g);
  }
  addFace([0, 0, floorZ]);                   // floor
  addFace([0, 0, floorZ + size]);            // ceiling
  addFace([half, 0, cz], [0, Math.PI / 2, 0]);   // +x wall (YZ plane)
  addFace([-half, 0, cz], [0, Math.PI / 2, 0]);  // -x wall
  addFace([0, half, cz], [Math.PI / 2, 0, 0]);   // +y wall (XZ plane)
  addFace([0, -half, cz], [Math.PI / 2, 0, 0]);  // -y wall

  // Solid dark floor panel so the room reads as grey (walls/ceiling stay wireframe to see through).
  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(size, size),
    new THREE.MeshStandardMaterial({ color: DARK, roughness: 1, side: THREE.DoubleSide }));
  floor.position.set(0, 0, floorZ - 0.002);  // just under the grid so lines sit on top
  floor.receiveShadow = true;
  room.add(floor);

  // Brighter cube outline so the 10 m bounds read crisply from any angle.
  const box = new THREE.BoxGeometry(size, size, size);
  const edges = new THREE.LineSegments(
    new THREE.EdgesGeometry(box), new THREE.LineBasicMaterial({ color: EDGE }));
  box.dispose();
  edges.position.set(0, 0, cz);
  room.add(edges);

  // Floating "1 m³" label (a camera-facing sprite) tucked into a floor corner to call out one cell.
  const canvas = document.createElement("canvas");
  canvas.width = 256; canvas.height = 128;
  const ctx = canvas.getContext("2d");
  ctx.font = "bold 76px system-ui, -apple-system, sans-serif";
  ctx.fillStyle = "#9a9a9a";
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText("1 m³", 128, 68);
  const tex = new THREE.CanvasTexture(canvas);
  tex.anisotropy = 4;
  const label = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }));
  label.scale.set(1.5, 0.75, 1);             // ~1.5 m wide
  label.position.set(half - 0.9, -half + 0.9, floorZ + 0.9);
  room.add(label);

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
