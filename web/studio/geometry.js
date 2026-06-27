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
