// Shared gate/trail geometry helpers (sim frame), ported from neural-whoop-lab and trimmed to
// what the Studio replay needs (gates + per-drone trails). Per-drone identity tints come from
// DRONE_TINTS so swarm/multi-drone racers are tellable apart.

import * as THREE from "three";

export const GATE_COLORS = { passed: 0x39d98a, next: 0xffd23f, upcoming: 0x6b7888 };

// Per-drone identity tints for group episodes (matches ../nw-viz/src/palette.js).
export const DRONE_TINTS = [
  0x4ea1ff, // blue
  0xff5d5d, // red
  0xffe14a, // yellow
  0x53e0a0, // green
  0xc77dff, // violet
  0xff9d3c, // orange
];

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

// Dim full path + a bright "traveled" overlay revealed via drawRange. `color` tints both (a
// drone's identity hue for multi-drone, or the default blue). Returns {full, done}.
export function buildTrail(world, frames, color = 0x4ea1ff) {
  const pathPts = frames.map((f) => new THREE.Vector3(f.pos[0], f.pos[1], f.pos[2]));
  const geo = new THREE.BufferGeometry().setFromPoints(pathPts);
  const full = new THREE.Line(geo, new THREE.LineBasicMaterial({ color: 0x33425a }));
  const done = new THREE.Line(geo.clone(), new THREE.LineBasicMaterial({ color }));
  world.add(full);
  world.add(done);
  return { full, done };
}
