// Shared gate/trail geometry helpers (sim frame), ported from neural-whoop-lab and trimmed to
// what the Studio replay needs (gates + per-drone trails). Per-drone identity tints come from
// DRONE_TINTS so swarm/multi-drone racers are tellable apart.

import * as THREE from "three";

// Gate states carry real meaning, so they keep colour: the active "next" gate lights up yellow,
// passed gates go green, upcoming stay grey.
export const GATE_COLORS = { passed: 0x39d98a, next: 0xffd23f, upcoming: 0x5a5a5a };

// Per-drone identity tints for group episodes (the glyph centre marker), so multiple racers are
// tellable apart at a glance.
export const DRONE_TINTS = [
  0x4ea1ff, // blue
  0xff5d5d, // red
  0xffe14a, // yellow
  0x53e0a0, // green
  0xc77dff, // violet
  0xff9d3c, // orange
];

// Scene-marker colours for gateless follow/formation tasks: the moving target is cyan, the
// formation anchor amber, slots faint grey. (Gates keep their own GATE_COLORS above.)
export const SCENE_COLORS = { target: 0x35e0e0, anchor: 0xffb13a, slot: 0x8a8a8a };

// Per-command tint for the target marker when a command channel is present, indexed by the raw
// command value: 0=STOP (red), 1=GO/NEAR (cyan), 2=FAR (amber). Mirrors nw-viz/src/palette.js.
export const COMMAND_TINTS = [0xff5d5d, 0x35e0e0, 0xffd23f];

// Turbo colormap (x in [0,1] -> [r,g,b] in [0,1]) for heat-coloured speed trails. Ported from
// ../nw-viz/src/palette.js so the Studio trail matches the MP4 renderer.
export function turbo(x) {
  x = Math.min(1, Math.max(0, x));
  const v1 = x, v2 = x * x, v3 = x * x * x, v4 = v2 * v2, v5 = v2 * v3;
  const r = 0.13572138 + 4.6153926 * v1 - 42.66032258 * v2 + 132.13108234 * v3
    - 152.94239396 * v4 + 59.28637943 * v5;
  const g = 0.09140261 + 2.19418839 * v1 + 4.84296658 * v2 - 14.18503333 * v3
    + 4.27729857 * v4 + 2.82956604 * v5;
  const b = 0.1066733 + 12.64194608 * v1 - 60.58204836 * v2 + 110.36276771 * v3
    - 89.90310912 * v4 + 27.34824973 * v5;
  return [Math.min(1, Math.max(0, r)), Math.min(1, Math.max(0, g)), Math.min(1, Math.max(0, b))];
}

function p95(values, floor = 1.0) {
  if (!values.length) return floor;
  const sorted = [...values].sort((a, b) => a - b);
  const idx = Math.min(sorted.length - 1, Math.floor(0.95 * (sorted.length - 1)));
  return Math.max(floor, sorted[idx]);
}

export function disposeGroup(arr, parent) {
  for (const o of arr) {
    o.geometry?.dispose();
    o.material?.dispose?.();
    parent.remove(o);
  }
}

// Build a wireframe sphere per omnidirectional gate (`{pos, radius}`), added under `world`.
// Returns the LineSegments array so a caller can recolor them by pass state.
export function buildGates(world, gates) {
  const lines = [];
  for (const gate of gates) {
    const r = gate.radius ?? 0.45;
    const sphere = new THREE.SphereGeometry(r, 16, 12);
    const geo = new THREE.WireframeGeometry(sphere);
    sphere.dispose();
    const line = new THREE.LineSegments(
      geo,
      new THREE.LineBasicMaterial({ color: GATE_COLORS.upcoming, transparent: true, opacity: 0.55 })
    );
    line.position.set(gate.pos[0], gate.pos[1], gate.pos[2]);
    world.add(line);
    lines.push(line);
  }
  return lines;
}

// A solid emissive marker sphere for a moving target/anchor (sim frame, added under `world`). The
// caller positions it per frame from `frame.scene.{target,anchor}` and may recolor it by command.
export function buildMarker(world, color, radius = 0.16) {
  const geo = new THREE.SphereGeometry(radius, 16, 12);
  const mesh = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.85 }));
  world.add(mesh);
  return mesh;
}

// A faint wire ring marking a formation slot (sim frame). Lies flat in the world xy-plane (the
// slots ring the anchor horizontally), so it reads as a target pad from the wide + top views.
export function buildSlot(world, radius = 0.18) {
  const geo = new THREE.TorusGeometry(radius, 0.012, 8, 24);
  const mesh = new THREE.Mesh(geo, new THREE.MeshBasicMaterial(
    { color: SCENE_COLORS.slot, transparent: true, opacity: 0.55 }));
  world.add(mesh);
  return mesh;
}

// Fallback tile palette if a caller doesn't pass one (near-black "dark" greybox). Callers
// (environment.js) pass a theme-specific palette so light/dark share this one primitive.
const FALLBACK_TILE = {
  tileA: "#1c1c1c", tileB: "#232323", line: "#3a3a3a", dot: "#444444",
  label: "rgba(150,150,150,0.22)",
};

// Human label for a grid pitch in metres ("1 METER" / "50 CM" / "10 CM"). Baked into the tile, so
// the grid states its own scale — which is the whole point of drawing the airframe at true size.
export function pitchLabel(pitch) {
  if (pitch >= 1) return pitch === 1 ? "1 METER" : `${+pitch.toFixed(2)} METERS`;
  return `${Math.round(pitch * 100)} CM`;
}

// The set of grid pitches we snap to. A hero shot frames ~0.4 m of world, an arena shot ~30 m, and
// the grid has to stay legible across both: pick the coarsest pitch that still puts a handful of
// lines across the frame (see `chooseGridPitch`).
const PITCH_LADDER = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10];

// Grid pitch (m) for a shot that spans `span` metres of world: the coarsest ladder step that still
// draws at least `want` divisions across the frame. This is what makes the room self-scaling —
// the same code gives a 82 mm product shot a 5 cm grid and a giant arena a 5 m grid, so "how big
// is the drone" reads the same way at every framing.
export function chooseGridPitch(span, want = 5) {
  const target = Math.max(1e-4, span) / Math.max(1, want);
  let best = PITCH_LADDER[0];
  for (const p of PITCH_LADDER) if (p <= target) best = p;
  return best;
}

// A "prototype map" greybox tile texture: a 2·pitch square block (checkerboard of two greys) with
// gridlines every `pitch` metres, optional finer `minor` lines inside them, intersection dots at
// the half-pitch, and "<pitch>" / "PROTOTYPE" labels baked along the lines. `palette`
// (tileA/tileB/line/dot/label, optional minorLine) themes it; `repeatX`/`repeatY` tile it to cover
// the surface (per-axis, though the only surface left is the square floor). All feature sizes are fractions
// of the block, so a 5 cm grid looks exactly like a 1 m grid, just smaller. Returns a
// THREE.CanvasTexture (RepeatWrapping, sRGB).
function greyboxTexture(palette = FALLBACK_TILE, repeatX = 1, repeatY = 1, labels = true,
                        { pitch = 1, minor = 0 } = {}) {
  // Sub-divided grids need the extra texel budget; a plain 2-line block does not. A hero shot is
  // close enough to the floor to magnify a block several times, so this is the difference between
  // a crisp mesh and mush.
  const S = minor > 0 ? 2048 : 512, M = S / 2;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = S;
  const ctx = canvas.getContext("2d");
  const { tileA, tileB, line, dot, label } = palette;

  // Checkerboard: tileA on the (0,0)/(M,M) diagonal, tileB on the off-diagonal.
  ctx.fillStyle = tileA; ctx.fillRect(0, 0, S, S);
  ctx.fillStyle = tileB; ctx.fillRect(M, 0, M, M); ctx.fillRect(0, M, M, M);

  const px = S / (2 * pitch);                 // px per metre in this block
  const drawLines = (step, width, style) => {
    ctx.strokeStyle = style; ctx.lineWidth = width;
    for (let p = 0; p <= S + 0.5; p += step) {
      ctx.beginPath(); ctx.moveTo(p, 0); ctx.lineTo(p, S); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(0, p); ctx.lineTo(S, p); ctx.stroke();
    }
  };
  // Minor subdivisions first (thinner + fainter), then the pitch lines over the top. Two densities
  // is what reads as a measured surface rather than a checkerboard: the fine mesh gives the eye a
  // texture right under the airframe while the pitch lines still carry the number.
  if (minor > 0 && minor < pitch) {
    drawLines(minor * px, Math.max(1, S / 512), palette.minorLine || dot);
  }
  // Gridlines every `pitch` (0/M/S; edge lines straddle the seam and complete on the tile next
  // door, so the repeat is continuous).
  drawLines(M, (5 * S) / 512, line);
  // Half-pitch dots on the lines (mark x half, half x mark) — dropped when minor lines already
  // subdivide the block, where they'd just be noise on top of the mesh.
  if (!(minor > 0 && minor < pitch)) {
    ctx.fillStyle = dot;
    const marks = [0, M, S], halves = [M / 2, (3 * M) / 2], r = (5 * S) / 512;
    const dotAt = (x, y) => { ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill(); };
    for (const a of marks) for (const b of halves) { dotAt(a, b); dotAt(b, a); }
  }

  // Labels along the lines (faint), repeated every block like the reference. Read correctly (not
  // mirrored) on the floor, which is built as a front-facing plane below. `labels: false` drops
  // them for a clean product shot — the grid still carries the scale.
  if (labels) {
    const k = S / 512;
    ctx.fillStyle = label;
    ctx.font = `bold ${34 * k}px system-ui, -apple-system, sans-serif`;
    ctx.textBaseline = "alphabetic";
    ctx.save(); ctx.translate(24 * k, M - 16 * k); ctx.fillText(pitchLabel(pitch), 0, 0); ctx.restore();
    ctx.save(); ctx.translate(M - 16 * k, S - 24 * k); ctx.rotate(-Math.PI / 2);
    ctx.fillText("PROTOTYPE", 0, 0); ctx.restore();
  }

  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  tex.repeat.set(repeatX, repeatY);
  return tex;
}

// The stage floor (sim frame): a single `size`×`size` greybox plane resting on z=floorZ, tiled into
// "prototype map" squares at `pitch` metres (see greyboxTexture). Returns a THREE.Group (added
// under `world`) holding one FRONT-facing (DoubleSide) plane a hair above z=floorZ — the surface
// people read, so its baked "PROTOTYPE" / pitch text reads correctly rather than mirrored. Dispose
// the group (geometry + texture) to tear it down.
//
// There are no walls and no ceiling, anywhere, in any view. This used to be a bounded room with a
// BackSide box over it and a `walls: false` escape hatch for the concept renders; the box is gone
// because a corner or a ceiling seam sweeping through a moving frame was the single biggest thing
// that made a travelling shot read as wrong, and keeping two backdrops meant the Studio and the
// video could drift apart. The floor alone, run out past the scene fog (environment.js::setStage
// sizes it from the fade), is a cyclorama: the ground and its contact shadow are still there, so
// the drone is visibly IN a place, and nothing bounds the frame.
export function buildStageFloor(world, { size = 10, floorZ = 0, palette = FALLBACK_TILE,
                                         labels = true, pitch = 1, minor = 0 } = {}) {
  const group = new THREE.Group();
  const repeat = size / (2 * pitch);          // block is 2·pitch -> repeat = metres / block

  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(size, size),
    new THREE.MeshStandardMaterial({
      map: greyboxTexture(palette, repeat, repeat, labels, { pitch, minor }),
      roughness: 1, metalness: 0, side: THREE.DoubleSide,
    }));
  floor.position.set(0, 0, floorZ + 0.003);
  floor.receiveShadow = true;
  group.add(floor);

  world.add(group);
  return group;
}

// Dim grey full path + a heat-coloured "traveled" overlay revealed via drawRange. The traveled
// trail is turbo-mapped by speed (normalized to a fixed p95 so colours don't flicker frame to
// frame), so you read where the drone was fast vs. slow. Returns {full, done}.
export function buildTrail(world, frames, opts = {}) {
  const pathPts = frames.map((f) => new THREE.Vector3(f.pos[0], f.pos[1], f.pos[2]));
  const geo = new THREE.BufferGeometry().setFromPoints(pathPts);
  const full = new THREE.Line(geo, new THREE.LineBasicMaterial({ color: 0x3a3a3a }));

  // `plain` draws the flown trail as one muted colour instead of the turbo speed ramp. Two turbo
  // trails in one scene read as one confusing gradient, so an overlay's ghost takes this path.
  if (opts.plain !== undefined) {
    const doneGeoPlain = geo.clone();
    const donePlain = new THREE.Line(
      doneGeoPlain,
      new THREE.LineBasicMaterial({ color: opts.plain, transparent: true, opacity: 0.55 })
    );
    world.add(full);
    world.add(donePlain);
    return { full, done: donePlain };
  }

  const doneGeo = geo.clone();
  const speeds = frames.map((f) => Math.hypot(f.vel[0], f.vel[1], f.vel[2]));
  const vmax = p95(speeds, 1.0);
  const colors = new Float32Array(frames.length * 3);
  for (let k = 0; k < frames.length; k++) {
    const [r, g, b] = turbo(speeds[k] / vmax);
    colors[k * 3] = r; colors[k * 3 + 1] = g; colors[k * 3 + 2] = b;
  }
  doneGeo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  const done = new THREE.Line(doneGeo, new THREE.LineBasicMaterial({ vertexColors: true }));
  world.add(full);
  world.add(done);
  return { full, done };
}
