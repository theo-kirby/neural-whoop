// Shared Three.js scene factory for the Studio replay view (ported from neural-whoop-lab).
//
// Coordinate frames: data is raw SIMULATOR frame — right-handed, Z-up, meters, quaternion
// [x,y,z,w]. Three.js is Y-up. Instead of converting every vector we drop all sim-frame objects
// into a `world` group rotated -90 deg about X (maps sim (x,y,z) -> three (x,z,-y), preserving
// handedness), so a drone's pose quaternion applies verbatim. The ground is large so giant
// courses still sit on a floor.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

// The key light's direction, as a three-frame (Y up) vector. STEEP on purpose: the old rig sat at
// (10, 18, 7), i.e. 0.68 of its altitude sideways, which at 1.5 m up throws an 82 mm drone's shadow
// a full metre clear of it — so the shadow reads as a second object instead of as ground contact.
// 0.22/0.15 of the altitude puts it under the airframe. environment.js re-exports this as
// STAGE_LOOK.keyDir so the video look and the Studio cannot pick different suns.
export const KEY_DIR = [0.22, 1.0, 0.15];
//: How far along KEY_DIR the sun is parked (m). Only the direction matters to a DirectionalLight;
//: the distance just has to clear the scene so the shadow frustum's `near` doesn't cut into it.
export const KEY_DISTANCE = 20;

// `preserveDrawingBuffer` keeps the colour buffer readable after a render — needed only by the
// headless capture page (web/capture/), which screenshots the page between explicit render() calls
// instead of inside a rAF; the Studio leaves it off (the default) so the driver can discard.
export function createScene(mount, { grid = true, preserveDrawingBuffer = false } = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  mount.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  // Background + fog are theme-neutral defaults here; environment.js (createEnvironment) owns the
  // per-theme background/fog/light intensities and overrides these before the first render.
  scene.background = new THREE.Color(0x141414);
  scene.fog = new THREE.Fog(0x141414, 40, 130);

  const camera = new THREE.PerspectiveCamera(55, 1, 0.05, 800);
  camera.position.set(8, 7, 11);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;

  // Light rig — intensities/ground colour are retuned per theme by environment.js (via the returned
  // `lights` handles), so hold references.
  const hemi = new THREE.HemisphereLight(0xffffff, 0x383838, 1.75);
  scene.add(hemi);
  // The key. Steep (KEY_DIR) and 2048² shadowed in the BASE rig, not just on the capture page:
  // both were cinematic-only refinements, and the reason to hoist them is that the Studio and the
  // video are meant to be the same picture. A 1024² map stretched over a ±30 m ortho gives an
  // 82 mm drone ~1.4 texels — i.e. no contact shadow at all — which is exactly what made the
  // dashboard's airframe look pasted over the floor rather than standing on it.
  const sun = new THREE.DirectionalLight(0xffffff, 2.7);
  sun.position.set(...KEY_DIR).setLength(KEY_DISTANCE);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  sun.shadow.camera.near = 1; sun.shadow.camera.far = 90;
  sun.shadow.camera.left = -30; sun.shadow.camera.right = 30;
  sun.shadow.camera.top = 30; sun.shadow.camera.bottom = -30;
  scene.add(sun);
  // Soft fill from the opposite side so the CAD chassis's near-black plastics don't crush to
  // silhouette; no shadow (the sun owns shadows).
  const fill = new THREE.DirectionalLight(0xdfe6ff, 1.0);
  fill.position.set(-12, 6, -9);
  scene.add(fill);

  // Ground (three-frame XZ plane = sim XY ground), sized for the giant arena — retinted to the scene
  // background per theme by environment.js so beyond the greybox room it fades into the fog. The
  // greybox room's own floor plane covers it within the course footprint.
  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(160, 160),
    new THREE.MeshStandardMaterial({ color: 0x191919, roughness: 1 })
  );
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = -0.001;
  ground.receiveShadow = true;
  scene.add(ground);
  if (grid) scene.add(new THREE.GridHelper(160, 160, 0x3a3a3a, 0x262626));

  // `world` holds every sim-frame object; rotating it maps sim Z-up -> three Y-up.
  const world = new THREE.Group();
  world.rotation.x = -Math.PI / 2;
  scene.add(world);

  function resize() {
    const w = mount.clientWidth || 1, h = mount.clientHeight || 1;
    // updateStyle MUST stay on: it sets canvas.style = w/h CSS px so the displayed size is
    // DPR-independent. With it off the canvas renders at its buffer size (w*devicePixelRatio),
    // so on a retina display (DPR 2) it doubles and overflows #view, painting over the sidebar.
    renderer.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }

  function render() {
    controls.update();
    renderer.render(scene, camera);
  }

  // Render a second camera into a small scissored corner viewport (picture-in-picture), e.g. a
  // drone-mounted FPV or a top-down cam. `rect` is in CSS px with origin at the canvas's
  // BOTTOM-left (WebGL convention). `hide` makes objects invisible just for this pass. Call
  // AFTER render().
  const _sz = new THREE.Vector2();
  function renderInset(cam, rect, { hide = [] } = {}) {
    const prevVis = hide.map((o) => o.visible);
    hide.forEach((o) => { o.visible = false; });
    renderer.getSize(_sz);
    renderer.setScissorTest(true);
    renderer.setViewport(rect.x, rect.y, rect.w, rect.h);
    renderer.setScissor(rect.x, rect.y, rect.w, rect.h);
    if (cam.isPerspectiveCamera) { cam.aspect = rect.w / rect.h; cam.updateProjectionMatrix(); }
    renderer.render(scene, cam);
    renderer.setScissorTest(false);
    renderer.setViewport(0, 0, _sz.x, _sz.y);
    hide.forEach((o, i) => { o.visible = prevVis[i]; });
  }

  resize();
  return {
    scene, camera, renderer, controls, world, resize, render, renderInset, mount, THREE,
    ground, lights: { hemi, sun, fill },
  };
}

// Aim the key at `focus` and refit its shadow ortho to `extent` metres around it.
//
// The default ±30 m ortho is sized for an arena; a true-scale 82 mm airframe inside it is a couple
// of texels, so the contact shadow — the thing that sells the drone as being ON the floor — simply
// isn't resolved. Refitting the frustum to the flight is what buys it back. Only the drone casts
// (the floor is receive-only), so the ortho only ever has to cover the subject, not the stage.
//
// `roomSize` caps the extent: a frustum wider than the floor is spending texels on nothing.
export function configureKeyLight(view, { dir = KEY_DIR, focus, extent = 1.0, roomSize = 40 } = {}) {
  const sun = view.lights.sun;
  if (dir && focus) {
    sun.target.position.copy(focus);
    view.scene.add(sun.target);          // an unparented target is never updated by three.js
    sun.position.copy(focus).add(
      new THREE.Vector3(...dir).normalize().multiplyScalar(KEY_DISTANCE));
  }
  const h = Math.min(Math.max(extent, 1.0), roomSize * 0.75);
  sun.shadow.camera.left = -h; sun.shadow.camera.right = h;
  sun.shadow.camera.top = h; sun.shadow.camera.bottom = -h;
  sun.shadow.camera.near = 0.5; sun.shadow.camera.far = 120;
  sun.shadow.camera.updateProjectionMatrix();
  sun.shadow.normalBias = 0.002;   // ~2 mm, scaled to a true-size airframe (kills acne, not contact)
  sun.shadow.map?.dispose();
  sun.shadow.map = null;           // force a rebuild at the current mapSize
  return sun;
}

// ACES tone mapping at `exposure`. The light rig is tuned for a wide view; close up, the light
// theme's near-white gridlines already sit at the top of the range and clip to flat white a metre
// from the lens. Rolling the highlights off keeps the grid readable and gives the chassis's
// plastics some shape. `null` disables tone mapping entirely (the legacy, ungraded look).
export function setToneMapping(renderer, exposure) {
  renderer.toneMapping = exposure === null || exposure === undefined
    ? THREE.NoToneMapping : THREE.ACESFilmicToneMapping;
  if (exposure !== null && exposure !== undefined) renderer.toneMappingExposure = exposure;
}
