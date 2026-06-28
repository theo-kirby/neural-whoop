// Replay playback over a shared scene view — adapted from neural-whoop-lab's single-drone
// Playback to the v2 `episodes[].drones[]` GROUP schema (mirrors ../nw-viz/src/viewer.js): one
// actor (glyph + trail, tinted per drone) per recorded drone, all sharing one course. A HERO
// actor (best by laps -> gates -> length) drives the HUD, the gate recolor, and the on-board
// cameras. UI-agnostic: calls back via `onFrame(heroFrame, i)`.

import * as THREE from "three";
import {
  GATE_COLORS, DRONE_TINTS, COMMAND_TINTS, SCENE_COLORS,
  buildGates, buildTrail, buildMarker, buildSlot, disposeGroup,
} from "./geometry.js";
import { makeDrone } from "./drone-model.js";

// Body(+X fwd, +Y left, +Z up) -> camera(look down -Z, up +Y): forward = body +X, up = body +Z.
const BODY_TO_CAM = new THREE.Quaternion().setFromRotationMatrix(
  new THREE.Matrix4().makeBasis(
    new THREE.Vector3(0, -1, 0),  // cam +X = body -Y (right)
    new THREE.Vector3(0, 0, 1),   // cam +Y = body +Z (up)
    new THREE.Vector3(-1, 0, 0),  // cam +Z = body -X (so -Z = forward)
  )
);
const FPV_OFFSET = new THREE.Vector3(0.1, 0, 0.03);  // nose-cam: slightly forward + up of center
const UP_Y = new THREE.Vector3(0, 1, 0);             // gravity-up in three-world (sim +Z)

// v2 group tracks, or a single synthetic track wrapping a v1 single-drone episode.
function episodeTracks(ep) {
  if (Array.isArray(ep.drones) && ep.drones.length) return ep.drones;
  return [{ drone: ep.drone ?? 0, frames: ep.frames || [], summary: ep.summary || {} }];
}

// Mean distance from a track's drone to whatever it tracks (slot, else target) — the gateless
// hero key (lower = tracking best). Returns Infinity if the track carries no scene reference.
function meanTrackError(track) {
  const frames = track.frames || [];
  let sum = 0, cnt = 0;
  for (const f of frames) {
    const ref = f.scene && (f.scene.slot || f.scene.target);
    if (ref) { sum += Math.hypot(f.pos[0] - ref[0], f.pos[1] - ref[1], f.pos[2] - ref[2]); cnt++; }
  }
  return cnt ? sum / cnt : Infinity;
}

// Most interesting drone. Gate tasks: laps -> gates -> length (matches render.py / nw-viz). Gateless
// follow/formation tasks have no laps, so pick the drone that tracks its target/slot best (lowest
// mean distance), falling back to track 0.
function heroTrackIndex(tracks, hasGates) {
  if (!hasGates) {
    let best = 0, bestErr = Infinity;
    for (let i = 0; i < tracks.length; i++) {
      const err = meanTrackError(tracks[i]);
      if (err < bestErr) { bestErr = err; best = i; }
    }
    return best;
  }
  let best = 0, bestKey = [-1, -1, -1];
  for (let i = 0; i < tracks.length; i++) {
    const s = tracks[i].summary || {};
    const key = [s.laps || 0, s.gates_passed || 0, (tracks[i].frames || []).length];
    if (key[0] > bestKey[0] || (key[0] === bestKey[0] && (key[1] > bestKey[1] ||
        (key[1] === bestKey[1] && key[2] > bestKey[2])))) { best = i; bestKey = key; }
  }
  return best;
}

export class Playback {
  constructor(view) {
    this.view = view;
    this.episode = null;
    this.actors = [];        // [{ glyph, frames, trail, tint }]
    this.heroIdx = 0;
    this.gateLines = [];
    this.dt = 1 / 50;
    this.idx = 0;
    this.playing = false;
    this.speed = 1;
    this.follow = false;
    this.onFrame = null;        // (heroFrame, index) -> void
    this.onStateChange = null;  // () -> void  (play/pause toggled or run ended)
    this._v = new THREE.Vector3();
    this._q = new THREE.Quaternion();
    this._q2 = new THREE.Quaternion();
    this._followPos = new THREE.Vector3();
    this._fpvOff = new THREE.Vector3();
    // Each drone gets its OWN body-mounted FPV camera (built per-episode, one per actor — see
    // setEpisode); the top-down chase cam tracks the hero. fpvCamera aliases the hero's FPV.
    this.topCamera = new THREE.PerspectiveCamera(55, 1, 0.05, 400);
  }

  get fpvCamera() { return this.actors[this.heroIdx]?.fpvCamera; }

  get heroFrames() { return this.actors[this.heroIdx]?.frames || []; }
  get maxFrames() { return this.actors.reduce((m, a) => Math.max(m, a.frames.length), 0); }

  setEpisode(episode, dt) {
    this.episode = episode;
    this.dt = dt > 0 ? dt : 1 / 50;
    this._clear();

    this.gateLines = buildGates(this.view.world, episode.gates || []);
    const tracks = episodeTracks(episode);
    const multi = tracks.length > 1;
    this.actors = tracks.map((t, k) => {
      const tint = multi ? DRONE_TINTS[k % DRONE_TINTS.length] : 0xffe14a;
      const glyph = makeDrone(tint);
      this.view.world.add(glyph);
      const frames = t.frames || [];
      const trail = frames.length ? buildTrail(this.view.world, frames) : null;
      // One onboard camera per drone (wide, rolls with its body) so every FPV inset is independent.
      const fpvCamera = new THREE.PerspectiveCamera(95, 16 / 9, 0.02, 400);
      // Gateless tasks carry per-frame scene markers — build one per key present in this drone's
      // frames (moving target/anchor sphere, slot ring). Updated each frame in applyFrame.
      const sc0 = frames[0] && frames[0].scene;
      const markers = {};
      if (sc0) {
        if (sc0.target !== undefined) markers.target = buildMarker(this.view.world, SCENE_COLORS.target);
        if (sc0.anchor !== undefined) markers.anchor = buildMarker(this.view.world, SCENE_COLORS.anchor, 0.2);
        if (sc0.slot !== undefined) markers.slot = buildSlot(this.view.world);
      }
      return { glyph, frames, trail, tint, fpvCamera, markers };
    });
    this.heroIdx = heroTrackIndex(tracks, (episode.gates || []).length > 0);
    this.idx = 0;
    this.playing = false;
    this.frameToCamera();
    this.applyFrame(0);
  }

  _clear() {
    disposeGroup(this.gateLines, this.view.world);
    this.gateLines = [];
    for (const a of this.actors) {
      disposeGroup([a.glyph], this.view.world);
      if (a.trail) disposeGroup([a.trail.full, a.trail.done], this.view.world);
      if (a.markers) disposeGroup(Object.values(a.markers), this.view.world);
    }
    this.actors = [];
  }

  // Frame the wide cam over the bbox of every drone's path + the gates.
  frameToCamera() {
    const { world, camera, controls } = this.view;
    const box = new THREE.Box3();
    for (const a of this.actors) {
      for (const f of a.frames) box.expandByPoint(this._v.set(f.pos[0], f.pos[1], f.pos[2]));
    }
    for (const g of (this.episode.gates || [])) {
      box.expandByPoint(this._v.set(g.pos[0], g.pos[1], g.pos[2]));
    }
    if (box.isEmpty()) return;
    const center = box.getCenter(new THREE.Vector3()).applyMatrix4(world.matrixWorld);
    const radius = Math.max(box.getSize(new THREE.Vector3()).length() * 0.6, 4);
    controls.target.copy(center);
    camera.position.copy(center).add(new THREE.Vector3(radius * 0.8, radius * 0.7, radius));
    controls.update();
  }

  // Render the frame at floor(idx). Does NOT write this.idx (it's a fractional accumulator).
  applyFrame(idx) {
    if (!this.actors.length) return;
    for (const a of this.actors) {
      if (!a.frames.length) continue;
      const i = Math.max(0, Math.min(a.frames.length - 1, Math.floor(idx)));
      const f = a.frames[i];
      a.glyph.position.set(f.pos[0], f.pos[1], f.pos[2]);
      a.glyph.quaternion.set(f.quat[0], f.quat[1], f.quat[2], f.quat[3]);
      if (a.trail) a.trail.done.geometry.setDrawRange(0, i + 1);
      this._updateFpv(a.glyph, a.fpvCamera);   // each drone's onboard cam follows its own body
      this._updateMarkers(a, f.scene);          // moving target/anchor/slot (gateless tasks)
    }
    const hero = this.actors[this.heroIdx];
    const hi = Math.max(0, Math.min(hero.frames.length - 1, Math.floor(idx)));
    const hf = hero.frames[hi];
    // Only `gate_idx` (hero's next gate) actually counts — make that sphere pop, fade the rest.
    // Gateless tasks have no gate lines (the loop is a no-op there).
    for (let g = 0; g < this.gateLines.length; g++) {
      const state = g < hf.gate_idx ? "passed" : g === hf.gate_idx ? "next" : "upcoming";
      const line = this.gateLines[g];
      line.material.color.setHex(GATE_COLORS[state]);
      line.material.opacity = state === "next" ? 1.0 : 0.18;
      line.scale.setScalar(state === "next" ? 1.08 : 1.0);
    }
    this._updateTop(hero.glyph);
    if (this.follow) this._followCam(hf);
    if (this.onFrame) this.onFrame(hf, hi);
  }

  // Position one drone's onboard FPV camera at its nose, rolling with the body.
  _updateFpv(glyph, cam) {
    glyph.updateWorldMatrix(true, false);
    const dq = glyph.getWorldQuaternion(this._q2);
    const dp = this._v.setFromMatrixPosition(glyph.matrixWorld);
    cam.position.copy(dp).add(this._fpvOff.copy(FPV_OFFSET).applyQuaternion(dq));
    cam.quaternion.copy(dq).multiply(BODY_TO_CAM);
  }

  // Position this actor's scene markers from the frame's `scene` dict (gateless tasks). The target
  // marker recolors by the command channel when present (STOP/GO/NEAR/FAR), so you read the command
  // off the world too, not just the HUD chip.
  _updateMarkers(a, scene) {
    if (!a.markers || !scene) return;
    if (a.markers.target && scene.target) {
      a.markers.target.position.set(scene.target[0], scene.target[1], scene.target[2]);
      if (scene.command !== undefined) {
        a.markers.target.material.color.setHex(COMMAND_TINTS[Math.round(scene.command) % COMMAND_TINTS.length]);
      }
    }
    if (a.markers.anchor && scene.anchor) a.markers.anchor.position.set(scene.anchor[0], scene.anchor[1], scene.anchor[2]);
    if (a.markers.slot && scene.slot) a.markers.slot.position.set(scene.slot[0], scene.slot[1], scene.slot[2]);
  }

  // Top-down chase cam: straight above the hero, looking down, heading-up.
  _updateTop(glyph) {
    glyph.updateWorldMatrix(true, false);
    const dp = this._v.setFromMatrixPosition(glyph.matrixWorld);
    this.topCamera.position.copy(dp).addScaledVector(UP_Y, 8);
    this.topCamera.up.set(0, 0, -1).applyMatrix4(this.view.world.matrixWorld).normalize();
    this.topCamera.lookAt(dp);
  }

  _followCam(f) {
    const { world, camera, controls } = this.view;
    this._q.set(f.quat[0], f.quat[1], f.quat[2], f.quat[3]);
    const back = new THREE.Vector3(-1.8, 0, 0.7).applyQuaternion(this._q).add(this._v.set(...f.pos));
    back.applyMatrix4(world.matrixWorld);
    this._followPos.copy(this._v.set(...f.pos)).applyMatrix4(world.matrixWorld);
    camera.position.lerp(back, 0.12);
    controls.target.lerp(this._followPos, 0.2);
  }

  tick(delta) {
    if (!this.playing || !this.maxFrames) return;
    this.idx += (delta / this.dt) * this.speed;
    if (this.idx >= this.maxFrames - 1) {
      this.idx = this.maxFrames - 1;
      this.playing = false;
      if (this.onStateChange) this.onStateChange();
    }
    this.applyFrame(this.idx);
  }

  setPlaying(on) {
    if (on && this.idx >= this.maxFrames - 1) this.idx = 0; // replay from start
    this.playing = on && this.maxFrames > 1;
    if (this.onStateChange) this.onStateChange();
  }

  seek(idx) {
    this.playing = false;
    this.idx = idx;
    this.applyFrame(idx);
    if (this.onStateChange) this.onStateChange();
  }

  setTrailVisible(v) {
    for (const a of this.actors) if (a.trail) a.trail.full.visible = a.trail.done.visible = v;
  }
}
