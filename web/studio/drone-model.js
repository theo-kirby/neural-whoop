// The drone mesh, built in sim body frame (+X forward, +Z up) and parented under the scene's
// `world` group so a run's pose quaternion applies directly. `centerColor` tints the hub sphere
// so multi-drone (swarm / N-racer) episodes are tellable apart; an RGB axis triad on each drone
// shows its body frame / heading (red +X forward, green +Y left, blue +Z up). Ported from
// neural-whoop-lab + the nw-viz multi-drone tint.
//
// When the real chassis CAD is present (assets/whoop_chassis.glb — the whoop-assembly.fbx converted
// by scripts/chassis_fbx_to_glb.py, with its authored per-part materials baked in), it replaces the
// procedural body/arms/rotors once loaded; the procedural glyph stays as the instant placeholder
// and the no-asset fallback. The center marker and nav lights survive the swap — they carry
// identity and heading either way.
//
// The glyph's XY footprint is a per-drone option: the Studio draws it ~7x life size (GLYPH_FOOTPRINT)
// so it reads in the wide hero shot, while the headless capture page (web/capture/) asks for the
// TRUE 82 mm airframe so the concept video is honest against the 1 m floor grid.

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

// Resolved against THIS MODULE, not the document, so a second page (web/capture/) can import the
// Studio's scene modules verbatim without its own copy of the asset.
const CHASSIS_URL = new URL("assets/whoop_chassis.glb", import.meta.url).href;
// The studio's drone glyph has always been drawn ~7x life size so it reads in the wide hero shot;
// the CAD (a true-scale ~82 mm whoop) is blown up to the same XY footprint the procedural glyph
// has. Scale is derived from the model's own bbox, so the source units (mm here) don't matter.
export const GLYPH_FOOTPRINT = 0.54;
//: The real airframe, tip to tip (m) — the chassis CAD's own bbox measures 82.0 x 83.4 mm.
export const TRUE_FOOTPRINT = 0.082;

// The CAD's four prop nodes. Real quad-X convention: the two diagonals counter-rotate, so a
// stopped-frame render still reads as a quadcopter rather than four props chasing each other.
const PROP_NAMES = ["front-left-prop", "front-right-prop", "rear-left-prop", "rear-right-prop"];
const PROP_DIR = {
  "front-left-prop": 1, "rear-right-prop": 1,
  "front-right-prop": -1, "rear-left-prop": -1,
};

let chassisPromise = null; // Promise<THREE.Group|null>, one fetch shared by every drone instance

// The shared CAD prototype, normalized to a UNIT XY footprint — callers scale it to the footprint
// they want (see `makeDrone`'s `footprint` option). Exported so a headless renderer can await the
// asset before its first frame: without that, frame 0 captures the procedural placeholder.
export function chassisPrototype() {
  if (!chassisPromise) {
    chassisPromise = new GLTFLoader()
      .loadAsync(CHASSIS_URL)
      .then((gltf) => {
        const cad = gltf.scene;
        // CAD frame (Blender FBX export, Z-up, mm): +Y forward — the front props sit at y=+23 mm.
        // Yaw -90 deg so the nose faces sim body +X, recenter on the bounding box, then normalize
        // the XY footprint to 1. Authored materials are kept verbatim (that's the whole point of
        // the FBX); we only flag meshes to cast shadows.
        cad.rotation.z = -Math.PI / 2;
        const proto = new THREE.Group();
        proto.add(cad);
        const box = new THREE.Box3().setFromObject(proto);
        cad.position.sub(box.getCenter(new THREE.Vector3()));
        const size = box.getSize(new THREE.Vector3());
        proto.scale.setScalar(1 / Math.max(size.x, size.y));
        proto.traverse((o) => {
          if (o.isMesh) o.castShadow = true;
        });
        return proto;
      })
      .catch((err) => {
        console.warn("whoop_chassis.glb unavailable — keeping the procedural drone glyph", err);
        return null;
      });
  }
  return chassisPromise;
}

// Give each prop node its own rotation pivot at the motor hub, returning the four pivot groups.
// The blade geometry is baked in CAD space and every prop node's transform is identity, so a
// node's bbox centroid is NOT its spin axis — it carries the same blade-shape offset on all four.
// The hubs are symmetric about the airframe centre, so subtracting the mean of the four centroids
// cancels that shared offset and recovers the hub positions exactly. Returns null if the CAD (and
// therefore the named nodes) isn't in this drone yet.
function pivotProps(drone) {
  const nodes = PROP_NAMES.map((n) => drone.getObjectByName(n)).filter(Boolean);
  if (nodes.length !== PROP_NAMES.length) return null;
  drone.updateWorldMatrix(true, true);
  const centers = nodes.map((n) =>
    n.parent.worldToLocal(new THREE.Box3().setFromObject(n).getCenter(new THREE.Vector3())));
  const mean = centers
    .reduce((a, c) => a.add(c), new THREE.Vector3())
    .multiplyScalar(1 / centers.length);
  return nodes.map((n, k) => {
    const hub = centers[k].clone().sub(mean);
    const parent = n.parent;
    const pivot = new THREE.Group();
    pivot.position.copy(hub);
    n.position.sub(hub);
    parent.add(pivot);
    pivot.add(n);
    pivot.userData.dir = PROP_DIR[n.name] || 1;
    return pivot;
  });
}

// Set this drone's prop angle to `radians` about the body +Z axis (counter-rotating diagonals).
// ABSOLUTE, not a delta: a headless renderer must be able to draw frame N without having drawn
// N-1, so the caller integrates the spin itself and passes the accumulated angle. The pivots are
// built lazily on the first call and cached on the drone group, so this is safe to call before the
// CAD has loaded (it just no-ops until the named nodes exist) and returns whether it applied.
//
// NOTE this is deliberately NOT physical. A real whoop turns ~30 000 rpm — at 50 fps that aliases
// to a stroboscopic mess, so the caller picks a rate that simply READS as spin and scales with the
// recorded collective thrust. It is the one non-literal element in the render.
export function spinProps(drone, radians) {
  let pivots = drone.userData.propPivots;
  if (!pivots) {
    pivots = pivotProps(drone);
    if (!pivots) return false;
    drone.userData.propPivots = pivots;
  }
  for (const p of pivots) p.rotation.z = radians * p.userData.dir;
  return true;
}

// `opts`: { footprint } XY tip-to-tip size in metres; { axes } the RGB body-frame triad;
// { marker } the tinted centre sphere. The defaults are the Studio's look — a headless/cinematic
// renderer turns the two gizmos off and asks for the true-scale footprint.
export function makeDrone(centerColor = 0xf2f2f2, opts = {}) {
  const { footprint = GLYPH_FOOTPRINT, axes = true, marker = true } = opts;
  const glyphScale = footprint / GLYPH_FOOTPRINT;
  const g = new THREE.Group();
  const placeholder = new THREE.Group(); // procedural glyph, swapped for the CAD chassis on load
  placeholder.scale.setScalar(glyphScale);
  g.add(placeholder);
  const body = new THREE.Mesh(
    new THREE.BoxGeometry(0.18, 0.18, 0.06),
    new THREE.MeshStandardMaterial({ color: 0x2b2b2b, metalness: 0.3, roughness: 0.6 })
  );
  body.castShadow = true;
  placeholder.add(body);

  // Bright center marker at the drone origin — this exact point is what gate detection tests
  // against the gate sphere. Tinted per-drone for identity.
  if (marker) {
    const center = new THREE.Mesh(
      new THREE.SphereGeometry(0.04 * glyphScale, 12, 8),
      new THREE.MeshBasicMaterial({ color: centerColor })
    );
    g.add(center);
  }

  const armMat = new THREE.MeshStandardMaterial({ color: 0x1c1c1c, roughness: 0.8 });
  const rotorMat = new THREE.MeshStandardMaterial({ color: 0x303030, transparent: true, opacity: 0.85 });
  const rotorGeo = new THREE.CylinderGeometry(0.11, 0.11, 0.02, 20);
  const offsets = [
    [0.16, 0.16], [0.16, -0.16],     // front (+X)
    [-0.16, 0.16], [-0.16, -0.16],    // rear (-X)
  ];
  for (const [x, y] of offsets) {
    const arm = new THREE.Mesh(new THREE.BoxGeometry(Math.hypot(x, y) * 1.0, 0.025, 0.025), armMat);
    arm.position.set(x / 2, y / 2, 0);
    arm.rotation.z = Math.atan2(y, x);
    placeholder.add(arm);
    const rotor = new THREE.Mesh(rotorGeo, rotorMat);
    rotor.rotation.x = Math.PI / 2; // cylinder axis -> sim +Z
    rotor.position.set(x, y, 0.03);
    rotor.castShadow = true;
    placeholder.add(rotor);
  }

  // Body-frame axis triad (red +X forward, green +Y left, blue +Z up) — the direction gizmo that
  // replaced the nav-light dots. Drawn always-on-top so it stays readable through the chassis, and
  // added to `g` (not the placeholder) so it survives the CAD swap.
  if (axes) {
    const triad = new THREE.AxesHelper(0.34 * glyphScale);
    triad.material.depthTest = false;
    triad.material.transparent = true;
    triad.renderOrder = 10;
    g.add(triad);
  }

  chassisPrototype().then((proto) => {
    if (!proto) return;
    g.remove(placeholder);
    const chassis = proto.clone(true); // clones share geometry + materials across drones
    chassis.scale.multiplyScalar(footprint);
    g.add(chassis);
  });
  return g;
}
