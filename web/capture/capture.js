// Headless capture page — the concept-video renderer, built on the STUDIO's own scene modules so
// the look can never drift from what the dashboard shows. It is a second page over the same
// scene.js / environment.js / geometry.js / drone-model.js / playback.js, with the interactive
// parts removed and a cinematic layer added:
//
//   * true scale — the drone is drawn at its real 82 mm footprint (the Studio's glyph is ~7x life
//     size so it reads in a wide course shot), which is the whole point of a concept video: an
//     honest sense of the airframe against the 1 m floor grid;
//   * a FIXED camera computed from the flight's own bounds — no orbit, no damping, nothing
//     time-dependent, so frame N is a pure function of N;
//   * no trail, no axis triad, no centre marker, no gates, no HUD — clean full frame;
//   * spinning props (drone-model.js::spinProps) driven by the recorded collective thrust;
//   * a DOM title/phase caption layer, baked in because the driver screenshots #app, not <canvas>.
//
// Contract with scripts/capture_video.py (mirrors ../nw-viz's page contract — three symbols):
//   in:   window.__REPLAY_DOC__   the parsed replay document (injected before this module runs)
//         window.__CAPTURE_OPTS__ render options (see DEFAULTS)
//   out:  window.NW_CAPTURE_READY === true once the scene AND the chassis GLB are loaded
//         window.NW_CAPTURE = { frameCount, renderFrame(i), meta }
//
// renderFrame(i) is the ONLY clock: the driver calls it for i = 0..frameCount-1 and screenshots
// after each. There is no requestAnimationFrame and no wall-clock anywhere in this file.

import * as THREE from "three";
import { configureKeyLight, createScene, setToneMapping } from "../studio/scene.js";
import { createEnvironment } from "../studio/environment.js";
import { Playback } from "../studio/playback.js";
import { TRUE_FOOTPRINT, chassisPrototype, spinProps } from "../studio/drone-model.js";

// These MUST agree, value for value, with scripts/capture_video.py::render()'s keyword defaults —
// i.e. with src/neural_whoop/video/look.py::VIDEO_LOOK, which is where the reasons behind each
// number are written down. tests/test_capture_opts_contract.py diffs the two on every run; the
// throw below catches the other direction. They are only ever a fallback (the driver sends every
// key), but a fallback that disagrees is exactly how a render silently uses the wrong camera.
const DEFAULTS = {
  episode: 0,
  theme: "dark",
  scale: TRUE_FOOTPRINT,     // drone tip-to-tip footprint (m)
  shot: "follow",            // "fit" | "tripod" | "follow" — see the camera section below
  track: false,              // deprecated spelling of shot:"tripod" (resolved just below)
  roomSize: null,            // stage-floor footprint (m); null -> derived from the fog, which is
                             //   derived from the standoff, so the plane always runs past its fade
  camDir: [0.85, 0.30, 1.0],
  camDist: 1.15,             // pull-back on the fitted/standoff distance (1.0 = the exact fit)
  fov: 40,                   // a longer lens than the Studio's 55; bought for the flatter
                             //   perspective, NOT for framing room (measured: it buys none)
  droneFrac: 0.22,           // (tripod/follow) fraction of the frame height the airframe fills
  camAbove: 0.30,            // (tripod) metres the camera sits above the flight's highest point,
                             //          so the shot NEVER tilts upward — level or looking down
  trackSmooth: 20,           // (tripod/follow) symmetric smoothing half-window, frames
  trackAmount: 1.0,          // (tripod) 1 = drone locked centre, <1 = camera stays nearer centre
  subjectY: -0.06,           // (follow) the subject's resting NDC height: <0 sits it below centre,
                             //          leaving headroom for the climb. 0 = dead centre.
  maxDrift: 0.26,            // (follow) how far, in NDC, the airframe may lag the camera before the
                             //          rig gives up smoothing and pulls it back into frame
  frameHeight: null,         // (fit) metres of world the frame spans vertically — the direct
                             //       "how big is the drone" control (drone = scale/frameHeight)
  aim: null,                 // (fit) sim [x,y,z] the shot is centred on; null -> flight centre
  aimZ: null,                // (fit) sim-z only, if `aim` is not given
  gridPitch: null,           // greybox grid pitch (m); null -> chosen from the shot's own framing
  gridMinor: null,           // finer subdivision (m); null -> pitch/5, 0 -> none
  fog: null,                 // [near, far] in m for the cyclorama; null -> from the standoff
  keyDir: [0.22, 1.0, 0.15], // sun direction [x,y,z] (three-frame). Steep, so the cast shadow sits
                             //   UNDER the airframe; null leaves the base rig's aim alone
  exposure: 0.95,            // ACES tone-mapping exposure; null = no tone mapping at all
  roomLabels: true,          // bake the pitch / "PROTOTYPE" text into the greybox tiles
  propRate: 0.8,             // radians per frame at hover thrust (stylized — see spinProps)
  title: "neural-whoop",
  titleFrames: 0,            // opening card; the same count is held as a closing card
};

const $ = (h) => document.querySelector(`[data-h="${h}"]`);
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

const doc = window.__REPLAY_DOC__;
const opts = { ...DEFAULTS, ...(window.__CAPTURE_OPTS__ || {}) };
// The injected options are a CONTRACT with scripts/capture_video.py::page_options, and the spread
// above silently swallows a violation: a key renamed on the Python side lands here as a new
// property nothing reads, the value falls back to the DEFAULT, and a perfectly plausible video is
// encoded with the wrong camera. Fail loudly instead — the driver forwards page errors to stderr.
{
  const unknown = Object.keys(window.__CAPTURE_OPTS__ || {}).filter((k) => !(k in DEFAULTS));
  if (unknown.length) {
    throw new Error(`capture: injected option(s) not in DEFAULTS: ${unknown.join(", ")} — ` +
      "capture_video.py::page_options and this file have drifted apart");
  }
}
if (!doc) throw new Error("capture: window.__REPLAY_DOC__ was not injected");
if (opts.track && opts.shot === "fit") opts.shot = "tripod";   // legacy `--track` spelling

const meta = doc.meta || {};
const episode = doc.episodes[opts.episode] || doc.episodes[0];
const dt = Number(meta.dt) > 0 ? Number(meta.dt) : 1 / (Number(meta.control_hz) || 50);
// Phase captions: the per-frame `scene.phase` code indexes these labels (see
// docs/VISUAL_CONTRACT.md). Absent -> no caption, which is the right no-op for other replays.
const phaseLabels = (meta.scene_info || {}).phase_labels || null;
const hoverThrust = (meta.action_limits || {}).hover_thrust_normed || 1.0;

// --- scene ------------------------------------------------------------------------------------
// Pixel ratio pinned to 1 so device px == CSS px and the screenshot is exactly --width x --height.
const view = createScene(document.getElementById("scene"), {
  grid: false, preserveDrawingBuffer: true,
});
view.renderer.setPixelRatio(1);
view.controls.enabled = false;     // nothing may move the camera; we render explicitly below
view.resize();

// ACES tone mapping (scene.js::setToneMapping) — `--exposure` is the one grading knob, and `null`
// means no tone mapping at all.
setToneMapping(view.renderer, opts.exposure);

const environment = createEnvironment(view, { labels: opts.roomLabels });
environment.setTheme(opts.theme);
document.documentElement.dataset.theme = opts.theme;   // drives the caption-layer palette

const playback = new Playback(view);
playback.droneOptions = { footprint: opts.scale, axes: false, marker: false };

// The chassis GLB swaps in from a promise inside makeDrone. Await it BEFORE signalling ready or
// frame 0 captures the procedural placeholder glyph instead of the CAD.
await chassisPrototype();
playback.setEpisode(episode, dt, (doc.meta || {}).scene_info || {});
await chassisPrototype();          // flush the swap callback makeDrone queued a moment ago
playback.setTrailVisible(false);   // cinematic: the airframe, not the analysis overlay

// --- camera -------------------------------------------------------------------------------------
// Three shots. Whichever is chosen, the whole camera track is PRECOMPUTED here into `pose[i]`
// ({position, target}) — nothing accumulates between frames (no OrbitControls, no damping, no
// causal filter), so frame N stays a pure function of N and re-rendering any index is identical.
//
//   fit (default) — a locked-off camera with an exact BOX fit of the whole flight, not cameras.js's
//     bounding-SPHERE fit: a tall thin flight (1.6 m of climb inside 0.7 m of drift) would sit ~25%
//     further back under a sphere. `--frame-height` overrides the fit with an explicit framing.
//
//   tripod (`--shot tripod`) — a fixed POSITION that pans/tilts to follow the drone. Gets close at
//     true scale, but the price is steep and it is why this is no longer the hero shot: because the
//     camera stays put while the subject crosses the room, the drone's apparent size swings with
//     range (2x over a 1.6 m climb here) and the whole background — horizon, room corner, ceiling
//     seam — sweeps across the frame. It reads as a security camera, not a product shot.
//
//   follow (`--shot follow`) — the STANDARDIZED hero rig, and the reason this file exists. The
//     camera holds a constant offset from a smoothed subject track, so:
//       * apparent size is fixed BY CONSTRUCTION — `--drone-frac` of the frame height, in every
//         frame of every clip, whatever the flight extent. That is what makes the look portable
//         across a hover, a flip, a gate lap and a real flight log without per-clip tuning.
//       * the camera's ORIENTATION never changes (position and target translate together), so the
//         horizon is nailed to one place in the frame. Only the ground parallaxes past.
//     The subject is not welded to the centre: the camera anchor is the Hann-smoothed track, so the
//     drone leads it through fast transients (a symmetric window is zero-phase — it rounds corners,
//     it does not lag a steady climb) and settles back. `--max-drift` softly caps how far that goes.
//     NOTE (measured): at a fixed `--drone-frac` the standoff scales as 1/tan(fov/2), so
//     `tan(fov/2)·dist` — the metres of world one NDC unit spans at the subject — is CONSTANT. A
//     wider FOV therefore buys exactly ZERO framing room; it very slightly WORSENS it, from the
//     shorter standoff's stronger perspective. Worst |NDC| across 34/40/46°: 0.64 -> 0.68 -> 0.73
//     under the old box+hard-clamp filter, 0.54 -> 0.56 -> 0.58 under this one — same trend, and
//     the sign is what matters. `--drone-frac` is the only lever on room; fov buys perspective.
//     Likewise `--track-smooth` is not free calm: more smoothing means more lead means more
//     excursion. 14 -> 28 (at drone-frac 0.26) cost worst |NDC| 0.64 -> 0.91 with a 19-40% size
//     spread under the box window, and 0.54 -> 0.68 with 20.4-30.7% under Hann — tamed, not free.
view.world.updateMatrixWorld();
const flight = new THREE.Box3();
const cam = view.camera;
cam.fov = opts.fov;
cam.updateProjectionMatrix();
const tanV = Math.tan(THREE.MathUtils.degToRad(cam.fov) / 2);
const tanH = tanV * (cam.aspect || 16 / 9);
// Camera basis, with `dir` pointing from the subject BACK to the camera.
const dir = new THREE.Vector3(...opts.camDir).normalize();
const right = new THREE.Vector3(0, 1, 0).cross(dir).normalize();
const up = dir.clone().cross(right).normalize();

const framesList = playback.actors.map((a) => a.frames);

// Component-wise median of the hero's sim-frame track — a robust "where is the drone, mostly?".
function medianHeroPos() {
  const fr = playback.heroFrames;
  if (!fr.length) return new THREE.Vector3();
  const at = (k) => {
    const col = fr.map((f) => f.pos[k]).sort((a, b) => a - b);
    return col[col.length >> 1];
  };
  return new THREE.Vector3(at(0), at(1), at(2));
}

// The hero's three-world track, and a symmetric smoothing of it. Symmetric (not a causal EMA)
// keeps renderFrame(i) independent of having rendered i-1, and has zero phase lag.
//
// The window is a HANN (raised cosine), not a box. Both are zero-phase; the difference is what the
// camera path's SECOND derivative looks like, which is what the eye reads as "calm". A box filter's
// weights jump from w to 0 at the window edge, so every time a track sample enters or leaves the
// window the smoothed velocity takes a step — over a whip like the flip's roll that is a visible
// tick. Hann's weights taper to zero at the edges, so samples fade in and out and the acceleration
// stays continuous. It buys that at the SAME drift budget: a Hann window of half-width W has an
// effective width ~W/2, so it is if anything gentler on the lead/lag excursion than the box it
// replaces. Measured on the take-off/flip/land replay at the OLD hero settings (fov 34,
// drone-frac 0.26, track-smooth 14), Hann + the soft limiter below moved worst |NDC| 0.64 -> 0.54
// and the apparent-size spread 20.4-28.9% -> 21.3-25.6% — calmer AND better framed, same budget.
const heroTrack = playback.heroFrames.map((f) =>
  new THREE.Vector3(f.pos[0], f.pos[1], f.pos[2]).applyMatrix4(view.world.matrixWorld));
function smoothTrack(track, halfWindow) {
  const W = Math.max(0, Math.round(halfWindow));
  if (W === 0) return track.map((p) => p.clone());
  return track.map((_, i) => {
    const acc = new THREE.Vector3();
    let wsum = 0;
    for (let k = Math.max(0, i - W); k <= Math.min(track.length - 1, i + W); k++) {
      // Hann: 0 at |k-i| == W+1, 1 at the centre. Never exactly zero inside the window, so the
      // support is the full 2W+1 taps and a truncated (near-edge) window still normalizes cleanly.
      const w = 0.5 * (1 + Math.cos((Math.PI * (k - i)) / (W + 1)));
      acc.addScaledVector(track[k], w);
      wsum += w;
    }
    return acc.multiplyScalar(1 / Math.max(1e-9, wsum));
  });
}

// The standoff that makes the airframe fill `droneFrac` of the frame height. Same formula for both
// moving shots — it is the one number that standardizes apparent size across clips.
const standoff = opts.camDist * opts.scale / (2 * tanV * Math.max(0.001, opts.droneFrac));

let pose;                          // pose[i] = {position, target}; length 1 for a locked-off shot
let camDist;                       // the shot's nominal subject distance (drives room/fog/shadows)
{
  const v = new THREE.Vector3();
  for (const frames of framesList) for (const f of frames) flight.expandByPoint(v.set(...f.pos));
  for (const g of episode.gates || []) flight.expandByPoint(v.set(...g.pos));
  if (flight.isEmpty()) flight.setFromCenterAndSize(new THREE.Vector3(), new THREE.Vector3(1, 1, 1));
  const box = flight.clone().expandByScalar(opts.scale);  // don't clip the airframe at the extremes
  const target = box.getCenter(new THREE.Vector3()).applyMatrix4(view.world.matrixWorld);

  if (opts.shot === "follow") {
    camDist = standoff;
    // Fixed rig offset. `subjectY` biases the anchor's screen height: shifting the camera along its
    // own `up` by (-subjectY · tanV · dist) puts the anchor at exactly that NDC height, without
    // touching the orientation. Negative = the drone rests low with headroom above it.
    const rig = dir.clone().multiplyScalar(camDist)
      .addScaledVector(up, -opts.subjectY * tanV * camDist);
    const anchors = smoothTrack(heroTrack, opts.trackSmooth);
    // Never let the rig sink into the floor: clamping the ANCHOR (not the camera) keeps position
    // and target moving together, so the orientation stays exactly constant.
    const minAnchorY = 0.06 - rig.y;
    // Cap the drift: past `maxDrift` NDC the anchor is pulled back toward the true position, so a
    // whip like the flip's 360 deg/s roll can never carry the airframe out of frame.
    //
    // SOFT limiter, not a hard clamp. `min(|d|, lim)` is only C0: its derivative steps from 1 to 0
    // the instant the drift saturates, so the anchor's velocity (and therefore the camera's) has a
    // kink exactly during the fastest part of the shot — the caveat recorded on Flywheel node
    // hidden-field-0837. `lim·tanh(d/lim)` has the same two properties we actually wanted — it is
    // the identity for small drift (tanh(x) = x - x³/3 + …, so ordinary lead/lag is untouched) and
    // it asymptotes to `lim` — while being smooth everywhere, so the camera eases into the limit
    // instead of hitting it. It also never quite reaches `lim`, making the cap a true bound.
    const soft = (d, l) => l * Math.tanh(d / l);
    const lim = opts.maxDrift * tanV * camDist;
    const limX = lim * tanH / tanV;
    pose = anchors.map((a, i) => {
      const anchor = a.clone();
      const off = heroTrack[i].clone().sub(anchor);
      const dy = off.dot(up), dx = off.dot(right);
      // Move the anchor by (actual drift − allowed drift) so the RESIDUAL offset is the soft-limited
      // one; d − lim·tanh(d/lim) is ~0 near the origin and grows to absorb everything beyond it.
      anchor.addScaledVector(up, dy - soft(dy, lim));
      anchor.addScaledVector(right, dx - soft(dx, limX));
      anchor.y = Math.max(anchor.y, minAnchorY);
      return { position: anchor.clone().add(rig), target: anchor };
    });
  } else if (opts.shot === "tripod") {
    camDist = standoff;
    // NEVER TILT UP. The camera is parked `camAbove` metres over the highest point the shot will
    // ever aim at, so every frame looks level-to-downward. That fixes the elevation, so `dist`
    // buys HORIZONTAL offset with whatever is left.
    const topY = flight.max.z + opts.scale;                 // sim z == three y under world's rot
    const camY = Math.max(topY + opts.camAbove, target.y + dir.y * camDist);
    const dy = camY - topY;
    const h = Math.max(0.15 * camDist, Math.sqrt(Math.max(camDist * camDist - dy * dy, 0)));
    const dirH = new THREE.Vector3(dir.x, 0, dir.z).normalize();
    const position = new THREE.Vector3(target.x + dirH.x * h, camY, target.z + dirH.z * h);
    const centre = heroTrack.length
      ? heroTrack.reduce((a, p) => a.add(p.clone()), new THREE.Vector3()).multiplyScalar(1 / heroTrack.length)
      : target;
    const aims = smoothTrack(heroTrack, opts.trackSmooth);
    pose = (aims.length ? aims : [target]).map((aim) => {
      const t = aim.clone().lerpVectors(centre, aim, opts.trackAmount);
      t.y = Math.min(t.y, camY);   // belt and braces on "never upwards"
      return { position, target: t };
    });
  } else if (opts.frameHeight) {
    // LOCKED-OFF shot with an explicit framing: `frameHeight` is how many metres of world the
    // frame spans vertically, so the airframe is exactly scale/frameHeight of the picture.
    // Default aim: the MEDIAN hero position, not the bbox centre — a bbox centre is dragged around
    // by wherever the flight happened to reach its extremes, which at a tight framing throws the
    // subject clean out of frame. The median is where the drone IS.
    camDist = opts.frameHeight / (2 * tanV);
    const aim = opts.aim
      ? new THREE.Vector3(...opts.aim).applyMatrix4(view.world.matrixWorld)
      : medianHeroPos().applyMatrix4(view.world.matrixWorld);
    if (!opts.aim && opts.aimZ !== null) aim.y = opts.aimZ;   // sim z == three y under world's rot
    pose = [{ position: aim.clone().addScaledVector(dir, camDist), target: aim }];
  } else {
    // For a corner at camera-space (u, v, w) the frustum needs depth >= |u|/tanH and >= |v|/tanV;
    // depth is (d - w), so each corner imposes a minimum d. Take the max over all eight.
    let d = 0;
    for (const x of [box.min.x, box.max.x]) {
      for (const y of [box.min.y, box.max.y]) {
        for (const z of [box.min.z, box.max.z]) {
          const c = v.set(x, y, z).applyMatrix4(view.world.matrixWorld).sub(target);
          const w = c.dot(dir);
          d = Math.max(d, w + Math.abs(c.dot(right)) / tanH, w + Math.abs(c.dot(up)) / tanV);
        }
      }
    }
    camDist = d * opts.camDist;
    pose = [{ position: target.clone().addScaledVector(dir, camDist), target }];
  }
}
const poseAt = (i) => pose[Math.min(i, pose.length - 1)];
function applyPose(i) {
  const p = poseAt(i);
  cam.position.copy(p.position);
  cam.lookAt(p.target);
  cam.updateMatrixWorld();
}
applyPose(0);

// --- the stage ------------------------------------------------------------------------------------
// Built AFTER the camera, because the whole thing is derived from where the camera actually stands:
// setStage takes the subject distance and returns the fog, the floor size and the grid it chose.
// See environment.js::STAGE_LOOK for what each constant buys. There is one backdrop — a fogged
// cyclorama — in every view in the repo, so nothing here selects a look.
const stage = environment.setStage({
  camDist,
  camReach: 2 * (Math.hypot(cam.position.x, cam.position.z) + 0.6),
  frameSpan: 2 * tanV * camDist,               // metres of world across the frame height
  fog: opts.fog, gridPitch: opts.gridPitch, gridMinor: opts.gridMinor, roomSize: opts.roomSize,
});
const roomSize = stage.roomSize;

// --- key light + shadow ---------------------------------------------------------------------------
// Aim the key at the flight and refit its shadow ortho to it (scene.js::configureKeyLight). The
// base rig's ±30 m ortho is sized for an arena; a true-scale 82 mm airframe inside it resolves to a
// couple of texels, i.e. no contact shadow, which is the thing that sells the drone as being ON the
// floor rather than pasted over it.
configureKeyLight(view, {
  dir: opts.keyDir,          // null leaves the base rig's aim alone; the shipped look always sets it
  focus: flight.getCenter(new THREE.Vector3()).applyMatrix4(view.world.matrixWorld),
  extent: flight.getSize(new THREE.Vector3()).length() * 0.5 + 0.5,
  roomSize,
});

// --- captions ---------------------------------------------------------------------------------
const cardEl = document.getElementById("card");
const captionEl = document.getElementById("caption");
$("card-title").textContent = opts.title;
const openSub = meta.policy || meta.task || "";
const closeSub = (episode.summary || {}).sequence || meta.config || "";

// Ease a card in and back out across its own window so the cut isn't hard.
function cardAlpha(k, n) {
  const fade = Math.max(1, Math.round(n * 0.25));
  return clamp(Math.min(k / fade, (n - 1 - k) / fade), 0, 1);
}

// --- prop spin ---------------------------------------------------------------------------------
// Integrated ONCE, up front, into an absolute angle per flight frame, so renderFrame(i) stays a
// pure function of i (the driver may render any index, and re-rendering must be identical). The
// rate is stylized: a visible idle floor so a grounded drone still reads as powered, scaling with
// the recorded collective thrust up to a 1.5x ceiling through the climb and the flip.
const propAngles = playback.actors.map((a) => {
  const out = new Float64Array(a.frames.length);
  let phi = 0;
  for (let k = 0; k < a.frames.length; k++) {
    const thrust = (a.frames[k].action_diffaero || [hoverThrust])[0];
    phi += opts.propRate * clamp(0.25 + 0.75 * (thrust / hoverThrust), 0.25, 1.5);
    out[k] = phi;
  }
  return out;
});

// --- frame program ----------------------------------------------------------------------------
// [ title card | flight | end card ] — one flat index space so the driver stays a dumb for-loop.
const nFlight = playback.maxFrames;
const nCard = Math.max(0, Math.round(opts.titleFrames));
const frameCount = nCard + nFlight + nCard;

// Worst-case framing over the WHOLE flight: project each drone (padded by the airframe's angular
// radius) through the camera it will actually be rendered with, and report the largest |NDC| in
// each axis. >= 1 means a drone leaves frame at some point. Reported by the driver so "does it
// stay in frame?" is a measured number, not something you check by scrubbing.
//
// EVERY drone counts, not just the hero. On a single-drone replay that is the same number as
// before. On an OVERLAY (scripts/reference_vs_policy.py: a ghost reference beside the policy
// tracking it) the camera follows the hero, so a hero-only check reports a comfortable framing
// while the drone the clip exists to show has left the picture entirely — the check would pass on
// a video that hides its own subject. Apparent size stays hero-only: it is what `--drone-frac`
// asks for, and a second drone at a different depth would smear a number that is meant to prove
// the follow rig holds the SUBJECT at a constant size.
function framingReport() {
  const v = new THREE.Vector3();
  const rad = opts.scale * 0.5;
  let mx = 0, my = 0, sMin = Infinity, sMax = 0;
  const tracks = playback.actors.map((a) => a.frames).filter((fr) => fr && fr.length);
  for (let i = 0; i < nFlight; i++) {
    applyPose(i);
    for (const frames of tracks) {
      // A track that ended early (crash / early abort) holds at its last frame — the same thing
      // the renderer draws — so the check measures the picture, not the telemetry.
      const f = frames[Math.min(i, frames.length - 1)];
      if (!f) continue;
      v.set(f.pos[0], f.pos[1], f.pos[2]).applyMatrix4(view.world.matrixWorld);
      const depth = Math.max(1e-3, v.distanceTo(cam.position));
      const pad = rad / depth;                  // angular radius -> NDC (half-frame == tan(fov/2))
      v.project(cam);
      mx = Math.max(mx, Math.abs(v.x) + pad / tanH);
      my = Math.max(my, Math.abs(v.y) + pad / tanV);
    }
    const h = playback.heroFrames[Math.min(i, playback.heroFrames.length - 1)];
    if (!h) continue;
    v.set(h.pos[0], h.pos[1], h.pos[2]).applyMatrix4(view.world.matrixWorld);
    // Apparent size as a fraction of the frame HEIGHT — the number `--drone-frac` asks for. A
    // follow rig holds it flat by construction; the spread is what tells you a locked-off or
    // tripod shot is letting the subject balloon and shrink.
    const frac = opts.scale / (Math.max(1e-3, v.distanceTo(cam.position)) * 2 * tanV);
    sMin = Math.min(sMin, frac); sMax = Math.max(sMax, frac);
  }
  return { x: mx, y: my, sizeMin: sMin === Infinity ? 0 : sMin, sizeMax: sMax };
}

function renderFrame(i) {
  let flightIdx;
  if (i < nCard) {
    flightIdx = 0;
    $("card-title").textContent = opts.title;
    $("card-sub").textContent = openSub;
    cardEl.style.opacity = String(cardAlpha(i, nCard));
    captionEl.style.opacity = "0";
  } else if (i < nCard + nFlight) {
    flightIdx = i - nCard;
    cardEl.style.opacity = "0";
    captionEl.style.opacity = "1";
  } else {
    flightIdx = nFlight - 1;
    $("card-title").textContent = opts.title;
    $("card-sub").textContent = closeSub;
    cardEl.style.opacity = String(cardAlpha(i - nCard - nFlight, nCard));
    captionEl.style.opacity = "0";
  }

  playback.applyFrame(flightIdx);   // pure function of the index — it does not write playback.idx

  playback.actors.forEach((a, k) => {
    const angles = propAngles[k];
    if (angles.length) spinProps(a.glyph, angles[Math.min(flightIdx, angles.length - 1)]);
  });

  applyPose(flightIdx);   // precomputed track — a locked-off shot just re-applies pose[0]

  const hero = playback.heroFrames[Math.min(flightIdx, playback.heroFrames.length - 1)];
  if (hero) {
    if (phaseLabels && hero.scene && hero.scene.phase !== undefined) {
      $("phase").textContent = phaseLabels[Math.round(hero.scene.phase)] || "";
    } else {
      $("phase").textContent = "";
    }
    $("clock").textContent = `${Number(hero.t || flightIdx * dt).toFixed(2)} s`;
  }

  // Render explicitly — NOT view.render(), which calls controls.update() (OrbitControls damping is
  // the one time-dependent thing in the Studio's loop and would make frames path-dependent).
  view.renderer.render(view.scene, view.camera);
}

renderFrame(0);
const framing = framingReport();
renderFrame(0);
window.NW_CAPTURE = { frameCount, renderFrame, meta, dt, nFlight, nCard, framing };
window.NW_CAPTURE_READY = true;
