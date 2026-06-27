// The drone mesh, built in sim body frame (+X forward, +Z up) and parented under the scene's
// `world` group so a run's pose quaternion applies directly. `centerColor` tints the hub sphere
// so multi-drone (swarm / N-racer) episodes are tellable apart; nav lights still encode heading
// (blue front / red rear). Ported from neural-whoop-lab + the nw-viz multi-drone tint.

import * as THREE from "three";

export function makeDrone(centerColor = 0xf2f2f2) {
  const g = new THREE.Group();
  const body = new THREE.Mesh(
    new THREE.BoxGeometry(0.18, 0.18, 0.06),
    new THREE.MeshStandardMaterial({ color: 0x2b2b2b, metalness: 0.3, roughness: 0.6 })
  );
  body.castShadow = true;
  g.add(body);

  // Bright center marker at the drone origin — this exact point is what gate detection tests
  // against the gate sphere. Tinted per-drone for identity.
  const center = new THREE.Mesh(
    new THREE.SphereGeometry(0.04, 12, 8),
    new THREE.MeshBasicMaterial({ color: centerColor })
  );
  g.add(center);

  const armMat = new THREE.MeshStandardMaterial({ color: 0x1c1c1c, roughness: 0.8 });
  const rotorGeo = new THREE.CylinderGeometry(0.11, 0.11, 0.02, 20);
  const offsets = [
    [0.16, 0.16, 0xf0f0f0], [0.16, -0.16, 0xf0f0f0],   // front (+X): white (heading)
    [-0.16, 0.16, 0x4a4a4a], [-0.16, -0.16, 0x4a4a4a],  // rear (-X): dark grey
  ];
  for (const [x, y, color] of offsets) {
    const arm = new THREE.Mesh(new THREE.BoxGeometry(Math.hypot(x, y) * 1.0, 0.025, 0.025), armMat);
    arm.position.set(x / 2, y / 2, 0);
    arm.rotation.z = Math.atan2(y, x);
    g.add(arm);
    const rotor = new THREE.Mesh(
      rotorGeo,
      new THREE.MeshStandardMaterial({ color, transparent: true, opacity: 0.85 })
    );
    rotor.rotation.x = Math.PI / 2; // cylinder axis -> sim +Z
    rotor.position.set(x, y, 0.03);
    rotor.castShadow = true;
    g.add(rotor);
  }
  return g;
}
