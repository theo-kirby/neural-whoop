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
  const rotorMat = new THREE.MeshStandardMaterial({ color: 0x303030, transparent: true, opacity: 0.85 });
  const rotorGeo = new THREE.CylinderGeometry(0.11, 0.11, 0.02, 20);
  const navGeo = new THREE.SphereGeometry(0.022, 10, 8);
  const offsets = [
    [0.16, 0.16, true], [0.16, -0.16, true],     // front (+X): white nav light
    [-0.16, 0.16, false], [-0.16, -0.16, false],  // rear (-X): red nav light
  ];
  for (const [x, y, front] of offsets) {
    const arm = new THREE.Mesh(new THREE.BoxGeometry(Math.hypot(x, y) * 1.0, 0.025, 0.025), armMat);
    arm.position.set(x / 2, y / 2, 0);
    arm.rotation.z = Math.atan2(y, x);
    g.add(arm);
    const rotor = new THREE.Mesh(rotorGeo, rotorMat);
    rotor.rotation.x = Math.PI / 2; // cylinder axis -> sim +Z
    rotor.position.set(x, y, 0.03);
    rotor.castShadow = true;
    g.add(rotor);
    // Heading nav light: a small unlit (glowing) dot above each rotor — white front, red rear.
    const nav = new THREE.Mesh(navGeo, new THREE.MeshBasicMaterial({ color: front ? 0xffffff : 0xff2a2a }));
    nav.position.set(x, y, 0.055);
    g.add(nav);
  }
  return g;
}
