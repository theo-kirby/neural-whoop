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
import { createScene } from "../studio/scene.js";
import { createEnvironment } from "../studio/environment.js";
import { Playback } from "../studio/playback.js";
import { courseBounds } from "../studio/cameras.js";
import { chooseGridPitch } from "../studio/geometry.js";
import { TRUE_FOOTPRINT, chassisPrototype, spinProps } from "../studio/drone-model.js";

const DEFAULTS = {
  episode: 0,
  theme: "light",            // the bright "prototype map" look
  scale: TRUE_FOOTPRINT,     // drone tip-to-tip footprint (m)
  shot: "fit",               // "fit" | "tripod" | "follow" — see the camera section below
  roomSize: null,            // greybox room footprint (m); null -> derived from the flight
  camDir: [0.9, 0.35, 1.0],  // lower + more heroic than the Studio's [0.9, 0.65, 1.0]
  camDist: 1.15,             // pull-back on the fitted/standoff distance (1.0 = the exact fit)
  fov: 40,                   // a longer lens than the Studio's 55 — less wide-angle wall bulge
  droneFrac: 0.22,           // (tripod/follow) fraction of the frame height the airframe fills
  camAbove: 0.30,            // (tripod) metres the camera sits above the flight's highest point,
                             //          so the shot NEVER tilts upward — level or looking down
  trackSmooth: 25,           // (tripod/follow) symmetric smoothing half-window, frames
  trackAmount: 1.0,          // (tripod) 1 = drone locked centre, <1 = camera stays nearer centre
  subjectY: -0.08,           // (follow) the subject's resting NDC height: <0 sits it below centre,
                             //          leaving headroom for the climb. 0 = dead centre.
  maxDrift: 0.30,            // (follow) how far, in NDC, the airframe may lag the camera before the
                             //          rig gives up smoothing and pulls it back into frame
  frameHeight: null,         // (fit) metres of world the frame spans vertically — the direct
                             //       "how big is the drone" control (drone = scale/frameHeight)
  aim: null,                 // (fit) sim [x,y,z] the shot is centred on; null -> flight centre
  aimZ: null,                // (fit) sim-z only, if `aim` is not given
  backdrop: "room",          // "room" (walled greybox) | "floor" (cyclorama: floor + fog, no walls)
  gridPitch: null,           // greybox grid pitch (m); null -> chosen from the shot's own framing
  gridMinor: null,           // finer subdivision (m); null -> pitch/5, 0 -> none
  fog: null,                 // [near, far] in m for the floor backdrop; null -> from the standoff
  keyDir: null,              // sun direction [x,y,z] (three-frame); null -> the Studio's rig
  exposure: null,            // ACES tone-mapping exposure; null = no tone mapping at all
  roomLabels: true,          // bake the pitch / "PROTOTYPE" text into the greybox tiles
  propRate: 0.8,             // radians per frame at hover thrust (stylized — see spinProps)
  title: "neural-whoop",
  titleFrames: 0,            // opening card; the same count is held as a closing card
};

const $ = (h) => document.querySelector(`[data-h="${h}"]`);
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

const doc = window.__REPLAY_DOC__;
const opts = { ...DEFAULTS, ...(window.__CAPTURE_OPTS__ || {}) };
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

// ACES tone mapping, because a close product shot lights very differently from the wide Studio
// view it inherits: the light theme's near-white gridlines sit at the top of the range and clip to
// flat white a metre from the lens. Rolling the highlights off keeps the grid readable and gives
// the chassis's plastics some shape. `--exposure` is the one grading knob — and leaving it unset
// means NO tone mapping at all, so an existing render (the standard viz pack's video) is untouched.
if (opts.exposure !== null) {
  view.renderer.toneMapping = THREE.ACESFilmicToneMapping;
  view.renderer.toneMappingExposure = opts.exposure;
}

// The sky gradient belongs to the cyclorama: a walled room has a ceiling above the horizon, the
// floor backdrop has nothing, and flat fill up there reads as an unfinished render.
const environment = createEnvironment(view, {
  labels: opts.roomLabels, sky: opts.backdrop === "floor",
});
environment.setTheme(opts.theme);
document.documentElement.dataset.theme = opts.theme;   // drives the caption-layer palette

const playback = new Playback(view);
playback.droneOptions = { footprint: opts.scale, axes: false, marker: false };

// The chassis GLB swaps in from a promise inside makeDrone. Await it BEFORE signalling ready or
// frame 0 captures the procedural placeholder glyph instead of the CAD.
await chassisPrototype();
playback.setEpisode(episode, dt);
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
//     The subject is not welded to the centre: the camera anchor is the box-smoothed track, so the
//     drone leads it through fast transients (a box filter is zero-phase — it rounds corners, it
//     does not lag a steady climb) and settles back. `--max-drift` caps how far that goes.
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
const bounds = courseBounds(view.world, framesList, episode.gates || []);

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

// The hero's three-world track, and a symmetric box smoothing of it. Symmetric (not a causal EMA)
// keeps renderFrame(i) independent of having rendered i-1, and has zero phase lag.
const heroTrack = playback.heroFrames.map((f) =>
  new THREE.Vector3(f.pos[0], f.pos[1], f.pos[2]).applyMatrix4(view.world.matrixWorld));
function boxSmooth(track, halfWindow) {
  const W = Math.max(0, Math.round(halfWindow));
  return track.map((_, i) => {
    const acc = new THREE.Vector3();
    let n = 0;
    for (let k = Math.max(0, i - W); k <= Math.min(track.length - 1, i + W); k++, n++) acc.add(track[k]);
    return acc.multiplyScalar(1 / Math.max(1, n));
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
    const anchors = boxSmooth(heroTrack, opts.trackSmooth);
    // Never let the rig sink into the floor: clamping the ANCHOR (not the camera) keeps position
    // and target moving together, so the orientation stays exactly constant.
    const minAnchorY = 0.06 - rig.y;
    // Cap the drift: past `maxDrift` NDC the anchor is pulled back toward the true position, so a
    // whip like the flip's 360 deg/s roll can never carry the airframe out of frame.
    const lim = opts.maxDrift * tanV * camDist;
    pose = anchors.map((a, i) => {
      const anchor = a.clone();
      const off = heroTrack[i].clone().sub(anchor);
      const dy = off.dot(up), dx = off.dot(right);
      if (Math.abs(dy) > lim) anchor.addScaledVector(up, dy - Math.sign(dy) * lim);
      if (Math.abs(dx) > lim * tanH / tanV) {
        anchor.addScaledVector(right, dx - Math.sign(dx) * lim * tanH / tanV);
      }
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
    const aims = boxSmooth(heroTrack, opts.trackSmooth);
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

// --- the backdrop --------------------------------------------------------------------------------
// Built AFTER the camera, because both variants are sized from where the camera actually stands.
//
//   room — the walled greybox. The floor has to be big enough that the CAMERA stands inside it: the
//     walls are a BackSide box, so a camera outside culls the near wall and you get a hard diagonal
//     seam where the room simply stops. That is a hard floor on `--room-size`, not a preference.
//
//   floor (`--backdrop floor`) — a cyclorama: the floor alone, run out far past the shot, with the
//     scene fog fading it into the background. No walls and no ceiling means no corner and no seam
//     can ever sweep through a moving frame, which is the single biggest thing that made the tripod
//     shot read as "weird" — and the ground (and its shadow) is still there, so the drone is still
//     visibly IN a place rather than floating on a gradient.
//
// The grid keeps its honest METRE pitch — that label is the scale reference, and shrinking it to
// "10 CM" just moves the problem — but gains a finer mesh matched to the shot. An 82 mm airframe on
// a bare 1 m grid is 1/12 of a tile with nothing nearby to measure it against; subdivided at the
// framing's own scale, the drone sits on a mesh it can be read against while the metre lines still
// say how big a metre is. A wide arena shot resolves the subdivision to "coarser than the tile",
// i.e. none, and is left exactly as it was.
const frameSpan = 2 * tanV * camDist;            // metres of world across the frame height
const gridPitch = opts.gridPitch ?? 1;
const autoMinor = chooseGridPitch(frameSpan * 2.5, 5);
const gridMinor = opts.gridMinor ?? (autoMinor <= gridPitch / 2 ? autoMinor : 0);
let roomSize;
{
  const camReach = 2 * (Math.hypot(cam.position.x, cam.position.z) + 0.6);
  if (opts.backdrop === "floor") {
    // Big enough to run past the fog, so the plane's own edge is never in shot.
    const [fogNear, fogFar] = opts.fog || [Math.max(1.0, 1.5 * camDist), Math.max(6.0, 14 * camDist)];
    roomSize = Math.max(4 * fogFar, camReach);
    environment.setFog({ near: fogNear, far: fogFar });
    environment.setSize({ footprint: roomSize, height: 1, floorZ: 0, walls: false,
                          pitch: gridPitch, minor: gridMinor });
  } else {
    const wanted = opts.roomSize || Math.max(4, bounds ? bounds.footprint : 4);
    roomSize = Math.max(wanted, camReach);
    environment.setSize({
      footprint: roomSize,
      height: clamp((bounds ? bounds.zMax : 2) + 1.2, 2.2, 4),
      floorZ: 0, walls: true, pitch: gridPitch, minor: gridMinor,
    });
  }
}

// --- key light + shadow ---------------------------------------------------------------------------
// scene.js sizes the sun's shadow ortho for a ±30 m arena, where an 82 mm drone spans ~1.4 texels of
// the 1024² map — i.e. no contact shadow at all. Refit it to the flight and double the map, which is
// what makes the airframe look like it's ON the floor rather than pasted over it. Only the DRONE
// casts (the room is receive-only), so the ortho only has to cover the flight, not the room.
//
// `--key-dir` also re-aims the sun. The Studio's rig sits at (10,18,7), i.e. 0.68 of the altitude
// sideways — at 1.5 m up that throws the shadow 1.0 m clear of the drone, so it reads as a second
// object rather than as ground contact. A steeper key keeps the shadow under the airframe.
{
  const sun = view.lights.sun;
  const centre = flight.getCenter(new THREE.Vector3()).applyMatrix4(view.world.matrixWorld);
  if (opts.keyDir) {
    const k = new THREE.Vector3(...opts.keyDir).normalize().multiplyScalar(20);
    sun.target.position.copy(centre);
    view.scene.add(sun.target);              // an unparented target is never updated by three.js
    sun.position.copy(centre).add(k);
  }
  const reach = flight.getSize(new THREE.Vector3()).length() * 0.5 + 0.5;
  const h = clamp(reach, 1.0, roomSize * 0.75);
  sun.shadow.mapSize.set(2048, 2048);
  sun.shadow.camera.left = -h; sun.shadow.camera.right = h;
  sun.shadow.camera.top = h; sun.shadow.camera.bottom = -h;
  sun.shadow.camera.near = 0.5; sun.shadow.camera.far = 120;
  sun.shadow.camera.updateProjectionMatrix();
  sun.shadow.normalBias = 0.002;   // ~2 mm, scaled to a true-size airframe (kills acne, not contact)
  sun.shadow.map?.dispose();
  sun.shadow.map = null;           // force a rebuild at the new mapSize
}

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

// Worst-case framing over the WHOLE flight: project the hero (padded by the airframe's angular
// radius) through the camera it will actually be rendered with, and report the largest |NDC| in
// each axis. >= 1 means the drone leaves frame at some point. Reported by the driver so "does it
// stay in frame?" is a measured number, not something you check by scrubbing.
function framingReport() {
  const v = new THREE.Vector3();
  const rad = opts.scale * 0.5;
  let mx = 0, my = 0, sMin = Infinity, sMax = 0;
  for (let i = 0; i < nFlight; i++) {
    applyPose(i);
    const f = playback.heroFrames[Math.min(i, playback.heroFrames.length - 1)];
    if (!f) continue;
    v.set(f.pos[0], f.pos[1], f.pos[2]).applyMatrix4(view.world.matrixWorld);
    const depth = Math.max(1e-3, v.distanceTo(cam.position));
    const pad = rad / depth;                    // angular radius -> NDC (half-frame == tan(fov/2))
    // Apparent size as a fraction of the frame HEIGHT — the number `--drone-frac` asks for. A
    // follow rig holds it flat by construction; the spread is what tells you a locked-off or
    // tripod shot is letting the subject balloon and shrink.
    const frac = opts.scale / (depth * 2 * tanV);
    sMin = Math.min(sMin, frac); sMax = Math.max(sMax, frac);
    v.project(cam);
    mx = Math.max(mx, Math.abs(v.x) + pad / tanH);
    my = Math.max(my, Math.abs(v.y) + pad / tanV);
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
