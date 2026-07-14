// Shared Three.js scene factory for the Studio replay view (ported from neural-whoop-lab).
//
// Coordinate frames: data is raw SIMULATOR frame — right-handed, Z-up, meters, quaternion
// [x,y,z,w]. Three.js is Y-up. Instead of converting every vector we drop all sim-frame objects
// into a `world` group rotated -90 deg about X (maps sim (x,y,z) -> three (x,z,-y), preserving
// handedness), so a drone's pose quaternion applies verbatim. The ground is large so giant
// courses still sit on a floor.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

export function createScene(mount, { grid = true } = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  mount.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x141414);
  scene.fog = new THREE.Fog(0x141414, 40, 130);

  const camera = new THREE.PerspectiveCamera(55, 1, 0.05, 800);
  camera.position.set(8, 7, 11);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;

  scene.add(new THREE.HemisphereLight(0xffffff, 0x383838, 1.75));
  const sun = new THREE.DirectionalLight(0xffffff, 2.7);
  sun.position.set(10, 18, 7);
  sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024);
  sun.shadow.camera.near = 1; sun.shadow.camera.far = 90;
  sun.shadow.camera.left = -30; sun.shadow.camera.right = 30;
  sun.shadow.camera.top = 30; sun.shadow.camera.bottom = -30;
  scene.add(sun);
  // Soft fill from the opposite side so the CAD chassis's near-black plastics don't crush to
  // silhouette; no shadow (the sun owns shadows).
  const fill = new THREE.DirectionalLight(0xdfe6ff, 1.0);
  fill.position.set(-12, 6, -9);
  scene.add(fill);

  // Ground (three-frame XZ plane = sim XY ground) + grid, sized for the giant arena.
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
  return { scene, camera, renderer, controls, world, resize, render, renderInset, mount, THREE };
}
