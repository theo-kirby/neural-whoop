// Themed greybox environment manager — the single owner of a scene's greybox reference room plus
// its theme-driven scene chrome (background, fog, light intensities). Both Studio tabs (the
// Simulation player/editor and the Real bench) build one over their `view` so the light/dark toggle
// and the per-course room sizing go through one seam.
//
// `createEnvironment(view)` -> { setTheme(theme), setSize({footprint,height,floorZ}), dispose() }:
//   - setTheme repaints the room texture from the active palette and swaps scene.background / fog /
//     ground tint / light intensities (a cheap rebuild — new CanvasTextures);
//   - setSize disposes the old room mesh and builds a new one at a new footprint/height (call on
//     course load / arena-preset change);
//   - dispose tears the whole thing down (room geometry + per-face textures + the extra fill light).

import * as THREE from "three";
import { buildRoom } from "./geometry.js";

// Two environment palettes (tile texture + scene chrome). `light` reads bright — soft grey scene
// background/fog, mid-grey tiles, soft light gridlines, dark-on-light labels — matching the
// prototype-map reference image. `dark` is the near-black void (the original course look).
export const THEME_PALETTES = {
  light: {
    tile: { tileA: "#9aa0a9", tileB: "#a3a9b2", line: "#d7dbe1", dot: "#e0e4ea", label: "rgba(60,64,72,0.40)" },
    scene: {
      bg: 0xc4c8cf, fogNear: 40, fogFar: 150,
      hemiIntensity: 2.2, hemiGround: 0xbfc4cc, sunIntensity: 2.2, fillIntensity: 1.1,
      roomFillIntensity: 1.4, roomFillGround: 0xcfd3da,
    },
  },
  dark: {
    tile: { tileA: "#1c1c1c", tileB: "#232323", line: "#3a3a3a", dot: "#444444", label: "rgba(150,150,150,0.22)" },
    scene: {
      bg: 0x141414, fogNear: 40, fogFar: 130,
      hemiIntensity: 1.6, hemiGround: 0x2a2a2a, sunIntensity: 2.7, fillIntensity: 1.0,
      roomFillIntensity: 1.2, roomFillGround: 0x9a9a9a,
    },
  },
};

function paletteFor(theme) { return THEME_PALETTES[theme] || THEME_PALETTES.light; }

export function createEnvironment(view) {
  let theme = "light";
  let size = { footprint: 10, height: 10, floorZ: 0 };
  let room = null;

  // An extra hemisphere fill so the greybox room reads bright and even (replacing bench.js's old
  // ad-hoc light); its intensity/ground colour are themed too.
  const roomFill = new THREE.HemisphereLight(0xffffff, 0xbfc4cc, 1.4);
  view.scene.add(roomFill);

  function disposeObj(root) {
    if (!root) return;
    root.traverse((o) => {
      o.geometry?.dispose?.();
      const m = o.material;
      if (Array.isArray(m)) m.forEach((mm) => { mm?.map?.dispose?.(); mm?.dispose?.(); });
      else if (m) { m.map?.dispose?.(); m.dispose?.(); }
    });
    view.world.remove(root);
  }

  function rebuildRoom() {
    disposeObj(room);
    room = buildRoom(view.world, {
      size: size.footprint, height: size.height, floorZ: size.floorZ, palette: paletteFor(theme).tile,
    });
  }

  function applyChrome() {
    const s = paletteFor(theme).scene;
    view.scene.background = new THREE.Color(s.bg);
    view.scene.fog = new THREE.Fog(s.bg, s.fogNear, s.fogFar);
    if (view.ground) view.ground.material.color.setHex(s.bg);
    const L = view.lights || {};
    if (L.hemi) { L.hemi.intensity = s.hemiIntensity; L.hemi.groundColor.setHex(s.hemiGround); }
    if (L.sun) L.sun.intensity = s.sunIntensity;
    if (L.fill) L.fill.intensity = s.fillIntensity;
    roomFill.intensity = s.roomFillIntensity;
    roomFill.groundColor.setHex(s.roomFillGround);
  }

  function setTheme(t) {
    theme = t === "dark" ? "dark" : "light";
    applyChrome();
    rebuildRoom();
  }

  function setSize(sz = {}) {
    size = {
      footprint: sz.footprint ?? size.footprint,
      height: sz.height ?? size.height,
      floorZ: sz.floorZ ?? size.floorZ,
    };
    rebuildRoom();
  }

  function dispose() {
    disposeObj(room);
    room = null;
    view.scene.remove(roomFill);
  }

  setTheme(theme);
  return { setTheme, setSize, dispose, get theme() { return theme; } };
}
