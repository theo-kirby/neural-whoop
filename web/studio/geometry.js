// Shared gate/trail geometry helpers (sim frame), ported from neural-whoop-lab and trimmed to
// what the Studio replay needs (gates + per-drone trails). Per-drone identity tints come from
// DRONE_TINTS so swarm/multi-drone racers are tellable apart.

import * as THREE from "three";

// Greyscale gate states: the active "next" gate is bright white; passed/upcoming fade to grey
// (pass state is also conveyed by opacity/scale in playback, so it stays legible without colour).
export const GATE_COLORS = { passed: 0x6e6e6e, next: 0xffffff, upcoming: 0x454545 };

// Per-drone identity tints for group episodes — greyscale tones (white -> dark grey) so multiple
// racers are tellable apart without any colour.
export const DRONE_TINTS = [
  0xf2f2f2, // white
  0x9a9a9a, // mid grey
  0x6a6a6a, // dark grey
  0xcccccc, // light grey
  0x808080, // grey
  0x565656, // charcoal
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
export function buildTrail(world, frames, color = 0xbfbfbf) {
  const pathPts = frames.map((f) => new THREE.Vector3(f.pos[0], f.pos[1], f.pos[2]));
  const geo = new THREE.BufferGeometry().setFromPoints(pathPts);
  const full = new THREE.Line(geo, new THREE.LineBasicMaterial({ color: 0x3a3a3a }));
  const done = new THREE.Line(geo.clone(), new THREE.LineBasicMaterial({ color }));
  world.add(full);
  world.add(done);
  return { full, done };
}
