// Hero-shot camera framing — ported from ../nw-viz/src/cameras.js. The Studio keeps its orbitable
// view camera (so you can inspect the scene), but we INITIALIZE it to nw-viz's fixed wide 3/4 hero
// framing each time a run loads, so the on-screen wide shot matches what the exported MP4 captures
// (the canonical fixed framing is reproduced exactly at export time by nw-viz). The per-drone FPV
// and top-down cameras live in playback.js; this module only frames the main orbit camera.

import * as THREE from "three";

// Sim-frame Box3 over the episode's gates + every flown path, plus its three-world center (mapped
// through the `world` transform, a pure rotation so lengths are preserved). Returns null if empty.
// Also returns the raw sim-frame extent needed to size an origin-centred greybox room around the
// course: `footprint` = 2× the farthest horizontal reach from the origin (so a room centred at
// (0,0) encloses every point), and `zMax` = the highest sim-z touched.
export function courseBounds(world, framesList, gates) {
  const simBox = new THREE.Box3();
  const p = new THREE.Vector3();
  for (const frames of framesList)
    for (const f of frames) simBox.expandByPoint(p.set(f.pos[0], f.pos[1], f.pos[2]));
  for (const g of gates) simBox.expandByPoint(p.set(g.pos[0], g.pos[1], g.pos[2]));
  if (simBox.isEmpty()) return null;
  const centerSim = simBox.getCenter(new THREE.Vector3());
  const radius = Math.max(simBox.getSize(new THREE.Vector3()).length() * 0.5, 2.0);
  const center = centerSim.clone().applyMatrix4(world.matrixWorld);
  const reach = Math.max(
    Math.abs(simBox.min.x), Math.abs(simBox.max.x),
    Math.abs(simBox.min.y), Math.abs(simBox.max.y), 2.0);
  return { center, radius, footprint: 2 * reach, zMax: Math.max(simBox.max.z, 1.5) };
}

// Point the view's orbit camera at the course from nw-viz's fixed 3/4 hero angle, pulled back far
// enough that the whole course fits at the limiting field-of-view dimension. `framesList` is one
// frame array per drone; `gates` the episode gate list. Leaves the camera fully orbitable.
export function frameHeroCamera(view, framesList, gates) {
  const { camera, controls, world } = view;
  world.updateMatrixWorld();
  const bounds = courseBounds(world, framesList, gates);
  if (!bounds) return;
  const aspect = camera.aspect || 16 / 9;
  const halfV = THREE.MathUtils.degToRad(camera.fov) / 2;
  // For aspect<1 (portrait) the horizontal FOV is the tighter one; fit to whichever is smaller.
  const halfFit = Math.atan(Math.tan(halfV) * Math.min(1, aspect));
  const dist = (bounds.radius * 1.25) / Math.sin(halfFit);
  const dir = new THREE.Vector3(0.9, 0.65, 1.0).normalize();
  controls.target.copy(bounds.center);
  camera.position.copy(bounds.center).add(dir.multiplyScalar(dist));
  controls.update();
}

// Close-up on a single drone (calibration mode): target the orbit camera on the drone's SIM-frame
// position and park it a short fixed distance away along the same 3/4 hero direction. Stays fully
// orbitable — this only re-frames.
export function frameDrone(view, simPos, dist = 1.2) {
  const { camera, controls, world } = view;
  world.updateMatrixWorld();
  const center = new THREE.Vector3(simPos[0], simPos[1], simPos[2]).applyMatrix4(world.matrixWorld);
  const dir = new THREE.Vector3(0.9, 0.65, 1.0).normalize();
  controls.target.copy(center);
  camera.position.copy(center).add(dir.multiplyScalar(dist));
  controls.update();
}
