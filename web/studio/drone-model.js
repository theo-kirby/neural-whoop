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

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

const CHASSIS_URL = "assets/whoop_chassis.glb";
// The studio's drone glyph has always been drawn ~7x life size so it reads in the wide hero shot;
// the CAD (a true-scale ~82 mm whoop) is blown up to the same XY footprint the procedural glyph
// has. Scale is derived from the model's own bbox, so the source units (mm here) don't matter.
const GLYPH_FOOTPRINT = 0.54;

let chassisPromise = null; // Promise<THREE.Group|null>, one fetch shared by every drone instance

function chassisPrototype() {
  if (!chassisPromise) {
    chassisPromise = new GLTFLoader()
      .loadAsync(CHASSIS_URL)
      .then((gltf) => {
        const cad = gltf.scene;
        // CAD frame (Blender FBX export, Z-up, mm): +Y forward — the front props sit at y=+23 mm.
        // Yaw -90 deg so the nose faces sim body +X, recenter on the bounding box, then scale the
        // XY footprint to the glyph size. Authored materials are kept verbatim (that's the whole
        // point of the FBX); we only flag meshes to cast shadows.
        cad.rotation.z = -Math.PI / 2;
        const proto = new THREE.Group();
        proto.add(cad);
        const box = new THREE.Box3().setFromObject(proto);
        cad.position.sub(box.getCenter(new THREE.Vector3()));
        const size = box.getSize(new THREE.Vector3());
        proto.scale.setScalar(GLYPH_FOOTPRINT / Math.max(size.x, size.y));
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

export function makeDrone(centerColor = 0xf2f2f2) {
  const g = new THREE.Group();
  const placeholder = new THREE.Group(); // procedural glyph, swapped for the CAD chassis on load
  g.add(placeholder);
  const body = new THREE.Mesh(
    new THREE.BoxGeometry(0.18, 0.18, 0.06),
    new THREE.MeshStandardMaterial({ color: 0x2b2b2b, metalness: 0.3, roughness: 0.6 })
  );
  body.castShadow = true;
  placeholder.add(body);

  // Bright center marker at the drone origin — this exact point is what gate detection tests
  // against the gate sphere. Tinted per-drone for identity.
  const center = new THREE.Mesh(
    new THREE.SphereGeometry(0.04, 12, 8),
    new THREE.MeshBasicMaterial({ color: centerColor })
  );
  g.add(center);

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
  const axes = new THREE.AxesHelper(0.34);
  axes.material.depthTest = false;
  axes.material.transparent = true;
  axes.renderOrder = 10;
  g.add(axes);

  chassisPrototype().then((proto) => {
    if (!proto) return;
    g.remove(placeholder);
    g.add(proto.clone(true)); // clones share geometry + materials across drones
  });
  return g;
}
