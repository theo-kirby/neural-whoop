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
import { TRUE_FOOTPRINT, chassisPrototype, spinProps } from "../studio/drone-model.js";

const DEFAULTS = {
  episode: 0,
  theme: "light",            // the bright "prototype map" look
  scale: TRUE_FOOTPRINT,     // drone tip-to-tip footprint (m)
  roomSize: null,            // greybox room footprint (m); null -> derived from the flight
  camDir: [0.9, 0.35, 1.0],  // lower + more heroic than the Studio's [0.9, 0.65, 1.0]
  camDist: 1.15,             // pull-back on the exact box fit (1.0 = corners touch frame)
  fov: 40,                   // a longer lens than the Studio's 55 — less wide-angle wall bulge
  propRate: 0.8,             // radians per frame at hover thrust (stylized — see spinProps)
  title: "neural-whoop",
  titleFrames: 0,            // opening card; the same count is held as a closing card
};

const $ = (h) => document.querySelector(`[data-h="${h}"]`);
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

const doc = window.__REPLAY_DOC__;
const opts = { ...DEFAULTS, ...(window.__CAPTURE_OPTS__ || {}) };
if (!doc) throw new Error("capture: window.__REPLAY_DOC__ was not injected");

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

const environment = createEnvironment(view);
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

// --- room + camera ----------------------------------------------------------------------------
const framesList = playback.actors.map((a) => a.frames);
const bounds = courseBounds(view.world, framesList, episode.gates || []);
// A real indoor room, not a hangar. The floor is big enough that the CAMERA stands inside it —
// otherwise the near wall culls (it's a BackSide box) and you get a hard diagonal seam across the
// frame where the room simply stops. 6 m covers the default camera pull-back for a whoop-scale
// flight; a bigger course widens it. The ceiling stays low enough to read as a ceiling.
const roomSize = opts.roomSize || Math.max(6, bounds ? bounds.footprint : 6);
const roomHeight = clamp((bounds ? bounds.zMax : 2) + 1.2, 2.5, 4);
environment.setSize({ footprint: roomSize, height: roomHeight, floorZ: 0 });

// A fixed 3/4 shot, written straight onto the camera and never touched again (no OrbitControls,
// so nothing accumulates between frames). The fit is an exact BOX fit, not cameras.js's
// bounding-SPHERE fit: this flight is tall and thin (1.6 m of climb inside ~0.7 m of drift), and a
// sphere fit would hold the camera ~25% further back than it needs to be — which at true scale is
// the difference between reading the airframe and not.
view.world.updateMatrixWorld();
{
  const cam = view.camera;
  const box = new THREE.Box3();
  const v = new THREE.Vector3();
  for (const frames of framesList) for (const f of frames) box.expandByPoint(v.set(...f.pos));
  for (const g of episode.gates || []) box.expandByPoint(v.set(...g.pos));
  if (box.isEmpty()) box.setFromCenterAndSize(new THREE.Vector3(), new THREE.Vector3(1, 1, 1));
  box.expandByScalar(opts.scale);              // don't clip the airframe itself at the extremes
  const target = box.getCenter(new THREE.Vector3()).applyMatrix4(view.world.matrixWorld);

  cam.fov = opts.fov;
  cam.updateProjectionMatrix();
  const tanV = Math.tan(THREE.MathUtils.degToRad(cam.fov) / 2);
  const tanH = tanV * (cam.aspect || 16 / 9);
  // Camera basis, with `dir` pointing from the subject BACK to the camera.
  const dir = new THREE.Vector3(...opts.camDir).normalize();
  const right = new THREE.Vector3(0, 1, 0).cross(dir).normalize();
  const up = dir.clone().cross(right).normalize();
  // For a corner at camera-space (u, v, w) the frustum needs depth >= |u|/tanH and >= |v|/tanV;
  // depth is (d - w), so each corner imposes a minimum d. Take the max over all eight.
  let dist = 0;
  for (const x of [box.min.x, box.max.x]) {
    for (const y of [box.min.y, box.max.y]) {
      for (const z of [box.min.z, box.max.z]) {
        const c = v.set(x, y, z).applyMatrix4(view.world.matrixWorld).sub(target);
        const w = c.dot(dir);
        dist = Math.max(dist, w + Math.abs(c.dot(right)) / tanH, w + Math.abs(c.dot(up)) / tanV);
      }
    }
  }
  cam.position.copy(target).add(dir.multiplyScalar(dist * opts.camDist));
  cam.lookAt(target);
  cam.updateMatrixWorld();
}

// Shadows: scene.js sizes the sun's shadow ortho for a ±30 m arena, where an 82 mm drone spans
// ~1.4 texels of the 1024² map — i.e. no contact shadow at all. Refit it to the room and double
// the map, which is what makes the airframe look like it's ON the floor rather than pasted over it.
{
  const sun = view.lights.sun;
  const h = roomSize * 0.75;
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
window.NW_CAPTURE = { frameCount, renderFrame, meta, dt, nFlight, nCard };
window.NW_CAPTURE_READY = true;
