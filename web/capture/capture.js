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
  camDist: 1.15,             // pull-back on the fitted distance (1.0 = corners touch frame)
  fov: 40,                   // a longer lens than the Studio's 55 — less wide-angle wall bulge
  track: false,              // tripod shot: fixed position, camera pans/tilts to follow the drone
  droneFrac: 0.22,           // (track) fraction of the frame height the airframe fills at the top
  camAbove: 0.30,            // (track) metres the camera sits above the flight's highest point,
                             //         so the shot NEVER tilts upward — level or looking down
  trackSmooth: 25,           // (track) symmetric smoothing half-window, frames — bigger = calmer
  trackAmount: 1.0,          // (track) 1 = drone locked centre, <1 = camera stays nearer centre
  frameHeight: null,         // (fixed) metres of world the frame spans vertically — the direct
                             //         "how big is the drone" control (drone = scale/frameHeight)
  aim: null,                 // (fixed) sim [x,y,z] the shot is centred on; null -> flight centre
  aimZ: null,                // (fixed) sim-z only, if `aim` is not given
  roomLabels: true,          // bake the "1 METER" / "PROTOTYPE" text into the greybox tiles
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

const environment = createEnvironment(view, { labels: opts.roomLabels });
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

// --- camera + room ----------------------------------------------------------------------------
const framesList = playback.actors.map((a) => a.frames);
const bounds = courseBounds(view.world, framesList, episode.gates || []);
let roomSize = 6;                  // set once the camera is placed (the room must contain it)

// The camera. Two modes, both with a FIXED position — nothing dollies, and nothing accumulates
// between frames (no OrbitControls, no damping), so frame N stays a pure function of N.
//
//   wide (default) — an exact BOX fit of the whole flight, not cameras.js's bounding-SPHERE fit:
//     this flight is tall and thin (1.6 m of climb inside ~0.7 m of drift) and a sphere fit holds
//     the camera ~25% further back than it needs to be. Fixed lookAt at the flight's centre.
//
//   track (`--track`) — a TRIPOD shot: the position is fixed, but the camera pans/tilts to follow
//     the drone. This is the only way to get genuinely close at true scale. The arithmetic is
//     unforgiving: with the whole 1.56 m flight in a fixed frame, an 82 mm airframe can occupy at
//     most 82/1560 = 5% of the frame height, full stop. Tracking decouples the two — distance is
//     set from how large the DRONE should read (`--drone-frac`), and the flight extent no longer
//     constrains it. The cost is that you no longer see the whole trajectory at once.
view.world.updateMatrixWorld();
const flight = new THREE.Box3();

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
{
  const cam = view.camera;
  const v = new THREE.Vector3();
  for (const frames of framesList) for (const f of frames) flight.expandByPoint(v.set(...f.pos));
  for (const g of episode.gates || []) flight.expandByPoint(v.set(...g.pos));
  if (flight.isEmpty()) flight.setFromCenterAndSize(new THREE.Vector3(), new THREE.Vector3(1, 1, 1));
  const box = flight.clone().expandByScalar(opts.scale);  // don't clip the airframe at the extremes
  const target = box.getCenter(new THREE.Vector3()).applyMatrix4(view.world.matrixWorld);

  cam.fov = opts.fov;
  cam.updateProjectionMatrix();
  const tanV = Math.tan(THREE.MathUtils.degToRad(cam.fov) / 2);
  const tanH = tanV * (cam.aspect || 16 / 9);
  // Camera basis, with `dir` pointing from the subject BACK to the camera.
  const dir = new THREE.Vector3(...opts.camDir).normalize();
  const right = new THREE.Vector3(0, 1, 0).cross(dir).normalize();
  const up = dir.clone().cross(right).normalize();

  let dist;
  if (opts.track) {
    // Distance that makes the airframe fill `droneFrac` of the frame height.
    dist = opts.camDist * opts.scale / (2 * tanV * Math.max(0.001, opts.droneFrac));
    // NEVER TILT UP. The camera is parked `camAbove` metres over the highest point the shot will
    // ever aim at, so every frame looks level-to-downward. That fixes the elevation, so `dist`
    // buys HORIZONTAL offset with whatever is left — the shot is a slightly-high three-quarter
    // when the drone is at hover height and looks progressively further down as it descends.
    // (Apparent size therefore shrinks near the floor; that is what a fixed overhead camera sees,
    // and `--drone-frac` is calibrated at the top of the flight where the flip happens.)
    const topY = flight.max.z + opts.scale;                 // sim z == three y under world's rot
    const camY = Math.max(topY + opts.camAbove, target.y + dir.y * dist);
    const dy = camY - topY;
    const h = Math.max(0.15 * dist, Math.sqrt(Math.max(dist * dist - dy * dy, 0)));
    const dirH = new THREE.Vector3(dir.x, 0, dir.z).normalize();
    cam.position.set(target.x + dirH.x * h, camY, target.z + dirH.z * h);
    cam.lookAt(target);
    cam.updateMatrixWorld();
  } else if (opts.frameHeight) {
    // LOCKED-OFF shot with an explicit framing: `frameHeight` is how many metres of world the
    // frame spans vertically, so the airframe is exactly scale/frameHeight of the picture — the
    // direct "how big is the drone" control, instead of deriving it from the flight extent.
    // `aimZ` (sim z, metres) picks the height the shot is centred on; with a level `camDir` the
    // camera sits AT that height, i.e. dead straight-on, which is also the tightest framing that
    // still never tilts up.
    dist = opts.frameHeight / (2 * tanV);
    // Default aim: the MEDIAN hero position, not the bbox centre. A bbox centre is dragged around
    // by wherever the flight happened to reach its extremes — on this sequence that puts it 0.33 m
    // from where the drone actually spends its time, which at a tight framing throws the subject
    // clean out of frame. The median is where the drone IS.
    const aim = opts.aim
      ? new THREE.Vector3(...opts.aim).applyMatrix4(view.world.matrixWorld)
      : medianHeroPos().applyMatrix4(view.world.matrixWorld);
    if (!opts.aim && opts.aimZ !== null) aim.y = opts.aimZ;   // sim z == three y under world's rot
    cam.position.copy(aim).add(dir.multiplyScalar(dist));
    cam.lookAt(aim);
    cam.updateMatrixWorld();
  } else {
    // For a corner at camera-space (u, v, w) the frustum needs depth >= |u|/tanH and >= |v|/tanV;
    // depth is (d - w), so each corner imposes a minimum d. Take the max over all eight.
    dist = 0;
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
}

// --- the room ----------------------------------------------------------------------------------
// Built AFTER the camera, because the floor has to be big enough that the CAMERA stands inside it:
// the walls are a BackSide box, so a camera outside culls the near wall and you get a hard diagonal
// seam where the room simply stops. That is a hard floor on `--room-size`, not a preference — a
// smaller request is raised to fit, silently, rather than rendering visibly broken. Otherwise the
// room is as small as the shot allows, which is what makes it read as a room instead of a hangar.
{
  const cam = view.camera;
  const camReach = 2 * (Math.hypot(cam.position.x, cam.position.z) + 0.6);
  const wanted = opts.roomSize || Math.max(4, bounds ? bounds.footprint : 4);
  const footprint = Math.max(wanted, camReach);
  environment.setSize({
    footprint,
    height: clamp((bounds ? bounds.zMax : 2) + 1.2, 2.2, 4),
    floorZ: 0,
  });
  roomSize = footprint;
}

// Where the tracking camera aims, per flight frame: the hero's three-world position, box-smoothed
// over a symmetric window so a jittery frame doesn't shake the whole shot. Precomputed (symmetric,
// not a causal EMA) so renderFrame(i) never depends on having rendered i-1.
const aimTrack = (() => {
  if (!opts.track) return null;
  const raw = playback.heroFrames.map((f) =>
    new THREE.Vector3(f.pos[0], f.pos[1], f.pos[2]).applyMatrix4(view.world.matrixWorld));
  if (!raw.length) return null;
  const W = Math.max(0, Math.round(opts.trackSmooth));
  const camY = view.camera.position.y;
  const centre = raw.reduce((a, p) => a.add(p), new THREE.Vector3()).multiplyScalar(1 / raw.length);
  return raw.map((_, i) => {
    const acc = new THREE.Vector3();
    let n = 0;
    for (let k = Math.max(0, i - W); k <= Math.min(raw.length - 1, i + W); k++, n++) acc.add(raw[k]);
    const aim = acc.multiplyScalar(1 / Math.max(1, n));
    // `trackAmount` < 1 keeps the camera partly parked on the flight's centre, so it swings less;
    // 1.0 locks the drone dead centre. Smoothing (above) is the gentler knob — at a close framing
    // the drone leaves frame fast if the aim under-travels.
    aim.lerpVectors(centre, aim, opts.trackAmount);
    // Belt and braces on "never upwards": whatever the smoothing did, the aim stays at or below
    // the camera, so the shot is level or looking down. Always.
    aim.y = Math.min(aim.y, camY);
    return aim;
  });
})();

// Shadows: scene.js sizes the sun's shadow ortho for a ±30 m arena, where an 82 mm drone spans
// ~1.4 texels of the 1024² map — i.e. no contact shadow at all. Refit it and double the map, which
// is what makes the airframe look like it's ON the floor rather than pasted over it. Only the DRONE
// casts (the room is receive-only), so the ortho only has to cover the flight, not the room — which
// at whoop scale is another ~4x of shadow resolution, and it shows in a close shot.
{
  const sun = view.lights.sun;
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
  const cam = view.camera;
  const v = new THREE.Vector3();
  const tanV = Math.tan(THREE.MathUtils.degToRad(cam.fov) / 2);
  const tanH = tanV * (cam.aspect || 1);
  const rad = opts.scale * 0.5;
  let mx = 0, my = 0;
  for (let i = 0; i < nFlight; i++) {
    if (aimTrack && aimTrack.length) {
      cam.lookAt(aimTrack[Math.min(i, aimTrack.length - 1)]);
      cam.updateMatrixWorld();
    }
    const f = playback.heroFrames[Math.min(i, playback.heroFrames.length - 1)];
    if (!f) continue;
    v.set(f.pos[0], f.pos[1], f.pos[2]).applyMatrix4(view.world.matrixWorld);
    const depth = Math.max(1e-3, v.distanceTo(cam.position));
    const pad = rad / depth;                    // angular radius -> NDC (half-frame == tan(fov/2))
    v.project(cam);
    mx = Math.max(mx, Math.abs(v.x) + pad / tanH);
    my = Math.max(my, Math.abs(v.y) + pad / tanV);
  }
  return { x: mx, y: my };
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

  // Tripod pan/tilt. The camera POSITION is still never touched — only where it aims.
  if (aimTrack && aimTrack.length) {
    view.camera.lookAt(aimTrack[Math.min(flightIdx, aimTrack.length - 1)]);
    view.camera.updateMatrixWorld();
  }

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
