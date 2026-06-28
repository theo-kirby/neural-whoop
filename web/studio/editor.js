// Course editor — author a gate course in a unified 3D scene (click the ground to drop a gate, drag
// a translate gizmo to move it incl. height, edit a numeric list), with live flyability validation
// against the backend. Reuses the shared createScene + gate geometry so placement matches the
// player/replay exactly. Adapted from neural-whoop-lab's editor-tab.js to one 3D view (no 2D map).

import * as THREE from "three";
import { TransformControls } from "three/addons/controls/TransformControls.js";
import { createScene } from "./scene.js";
import { makeDrone } from "./drone-model.js";
import { buildGates, disposeGroup, GATE_COLORS } from "./geometry.js";
import * as api from "./api.js";

// A short flyable starter course (fits the tight arena: all within r=4.5, ~1.5 m hops).
const DEFAULT_GATES = [
  { pos: [2.0, 0.0, 1.0], radius: 0.35 },
  { pos: [3.4, 0.7, 1.1], radius: 0.35 },
  { pos: [4.2, -0.6, 1.0], radius: 0.30 },
];

// Sim-frame Z-up <-> three-world Y-up: the `world` group is rotated -90° about X, mapping
// sim (x,y,z) -> three (x, z, -y). So a three-world ground hit (X, 0, Z) is sim (X, -Z, ·).
const simXYFromGround = (p) => [p.x, -p.z];

export function createEditor({ mount, panel, toast, onSaved, onFly }) {
  const $ = (h) => panel.querySelector(`[data-h="${h}"]`);
  const view = createScene(mount);
  const drone = makeDrone();
  view.world.add(drone);            // a static drone glyph at origin as a scale/start reference

  let gates = DEFAULT_GATES.map((g) => ({ pos: [...g.pos], radius: g.radius }));
  let selected = 0;
  let preset = "tight";
  let arenaRadius = 4.5;
  let issuesByGate = new Map();     // gate index -> worst level ("error"|"warning")

  let gateLines = [];               // wireframe spheres (recolored by issue/selection)
  let pickMeshes = [];              // invisible raycast targets for click-select
  let arenaRing = null;             // dashed ground circle at the arena radius (hint)

  // ---- gizmo: drag the selected gate in space (incl. height) -------------------------
  // Attached to a proxy parented under `world`, so the proxy's LOCAL position is the gate's sim
  // (x,y,z). setSpace("local") aligns the handles to the sim axes despite the world group's tilt.
  const gizmoProxy = new THREE.Object3D();
  view.world.add(gizmoProxy);
  const gizmo = new TransformControls(view.camera, view.renderer.domElement);
  gizmo.setMode("translate");
  gizmo.setSpace("local");
  gizmo.setSize(0.8);
  gizmo.attach(gizmoProxy);
  view.scene.add(gizmo);
  gizmo.addEventListener("dragging-changed", (e) => { view.controls.enabled = !e.value; });
  gizmo.addEventListener("objectChange", onGizmoMove);

  const raycaster = new THREE.Raycaster();
  const groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0); // three-world ground (y=0)

  // ---- arena hint ring ---------------------------------------------------------------
  function rebuildArenaRing() {
    if (arenaRing) disposeGroup([arenaRing], view.world);
    const geo = new THREE.RingGeometry(arenaRadius - 0.03, arenaRadius, 96);
    arenaRing = new THREE.Mesh(geo, new THREE.MeshBasicMaterial(
      { color: 0x4a4a4a, transparent: true, opacity: 0.5, side: THREE.DoubleSide }));
    arenaRing.position.z = 0.01;     // lie flat on the sim ground (world group tilts it to three XZ)
    view.world.add(arenaRing);
  }

  // ---- gate meshes -------------------------------------------------------------------
  function rebuildGates() {
    disposeGroup(gateLines, view.world);
    disposeGroup(pickMeshes, view.world);
    gateLines = buildGates(view.world, gates);
    pickMeshes = gates.map((g, i) => {
      const mesh = new THREE.Mesh(
        new THREE.SphereGeometry(Math.max(0.4, g.radius), 12, 8),
        new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false }));
      mesh.position.set(g.pos[0], g.pos[1], g.pos[2]);
      mesh.userData.gateIndex = i;
      view.world.add(mesh);
      return mesh;
    });
    recolorGates();
  }
  // Tint each gate by its worst issue (red error / amber warning), the selected one blue, else green.
  function recolorGates() {
    gateLines.forEach((line, i) => {
      const lvl = issuesByGate.get(i);
      const color = lvl === "error" ? 0xff5d5d : lvl === "warning" ? 0xffd23f
        : i === selected ? 0x4ea1ff : GATE_COLORS.passed;
      line.material.color.setHex(color);
      line.material.opacity = i === selected ? 0.95 : 0.6;
    });
  }

  // ---- selection / inputs ------------------------------------------------------------
  function selectGate(i) {
    selected = Math.max(0, Math.min(gates.length - 1, i));
    const g = gates[selected];
    if (g) {
      $("e_gx").value = g.pos[0].toFixed(2);
      $("e_gy").value = g.pos[1].toFixed(2);
      $("e_gz").value = g.pos[2].toFixed(2);
      $("e_grad").value = String(g.radius);
    }
    syncGizmo();
    renderGateList();
    recolorGates();
  }
  function syncGizmo() {
    const g = gates[selected];
    gizmo.visible = gizmo.enabled = !!g;
    if (g) gizmoProxy.position.set(g.pos[0], g.pos[1], g.pos[2]);
  }
  function renderGateList() {
    const el = $("e_gatelist");
    el.innerHTML = "";
    gates.forEach((g, i) => {
      const row = document.createElement("div");
      row.className = "gate-row" + (i === selected ? " sel" : "");
      row.innerHTML = `<span class="idx">${i}</span><span class="pos">` +
        `(${g.pos[0].toFixed(1)}, ${g.pos[1].toFixed(1)}, ${g.pos[2].toFixed(1)}) · r ${g.radius.toFixed(2)}m</span>`;
      row.addEventListener("click", () => selectGate(i));
      el.appendChild(row);
    });
  }

  function onGizmoMove() {
    const g = gates[selected];
    if (!g) return;
    g.pos[0] = Math.round(gizmoProxy.position.x * 100) / 100;
    g.pos[1] = Math.round(gizmoProxy.position.y * 100) / 100;
    g.pos[2] = Math.round(gizmoProxy.position.z * 100) / 100;
    if (g.pos[2] < 0.05) { g.pos[2] = 0.05; gizmoProxy.position.z = 0.05; }  // keep above ground
    gateLines[selected]?.position.set(g.pos[0], g.pos[1], g.pos[2]);
    pickMeshes[selected]?.position.set(g.pos[0], g.pos[1], g.pos[2]);
    $("e_gx").value = g.pos[0].toFixed(2);
    $("e_gy").value = g.pos[1].toFixed(2);
    $("e_gz").value = g.pos[2].toFixed(2);
    renderGateList();
    scheduleValidate();
  }

  // Click a gate sphere to select; click empty ground to ADD a gate there.
  view.renderer.domElement.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || gizmo.dragging || gizmo.axis) return;
    const r = view.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(
      ((e.clientX - r.left) / r.width) * 2 - 1,
      -((e.clientY - r.top) / r.height) * 2 + 1);
    raycaster.setFromCamera(ndc, view.camera);
    const hit = raycaster.intersectObjects(pickMeshes, false)[0];
    if (hit) { selectGate(hit.object.userData.gateIndex); return; }
    // Missed every gate -> drop a new one where the ray meets the ground plane.
    const p = new THREE.Vector3();
    if (!raycaster.ray.intersectPlane(groundPlane, p)) return;
    const [sx, sy] = simXYFromGround(p);
    const z = gates.length ? gates[gates.length - 1].pos[2] : 1.0;
    gates.push({ pos: [Math.round(sx * 100) / 100, Math.round(sy * 100) / 100, z], radius: 0.35 });
    selected = gates.length - 1;
    onGatesChanged(); selectGate(selected);
  });

  function bindNum(h, apply) {
    $(h).addEventListener("input", () => {
      const g = gates[selected];
      if (!g) return;
      apply(g, Number($(h).value));
      gateLines[selected]?.position.set(g.pos[0], g.pos[1], g.pos[2]);
      pickMeshes[selected]?.position.set(g.pos[0], g.pos[1], g.pos[2]);
      syncGizmo(); renderGateList(); scheduleValidate();
    });
  }
  bindNum("e_gx", (g, v) => { g.pos[0] = v; });
  bindNum("e_gy", (g, v) => { g.pos[1] = v; });
  bindNum("e_gz", (g, v) => { g.pos[2] = Math.max(0.05, v); });
  bindNum("e_grad", (g, v) => { g.radius = Math.max(0.1, v); rebuildGates(); });

  $("e_add").addEventListener("click", () => {
    const last = gates[gates.length - 1] || { pos: [1.5, 0, 1.0], radius: 0.35 };
    gates.push({ pos: [last.pos[0] + 1.5, last.pos[1], last.pos[2]], radius: last.radius });
    selected = gates.length - 1;
    onGatesChanged(); selectGate(selected);
  });
  $("e_del").addEventListener("click", () => {
    if (gates.length <= 1) return toast("a course needs at least one gate", true);
    gates.splice(selected, 1);
    selected = Math.max(0, selected - 1);
    onGatesChanged(); selectGate(selected);
  });
  $("e_up").addEventListener("click", () => reorder(-1));
  $("e_down").addEventListener("click", () => reorder(1));
  function reorder(d) {
    const j = selected + d;
    if (j < 0 || j >= gates.length) return;
    [gates[selected], gates[j]] = [gates[j], gates[selected]];
    selected = j; onGatesChanged(); selectGate(selected);
  }

  function onGatesChanged() {
    rebuildGates(); renderGateList(); syncGizmo(); scheduleValidate();
  }

  // ---- validation (debounced) --------------------------------------------------------
  let validateTimer = null;
  function scheduleValidate() { clearTimeout(validateTimer); validateTimer = setTimeout(validate, 250); }
  async function validate() {
    try {
      const rep = await api.validateCourse({ name: $("e_name").value || "course", gates }, preset);
      issuesByGate = new Map();
      for (const iss of rep.issues) {
        if (iss.gate_index < 0) continue;
        const cur = issuesByGate.get(iss.gate_index);
        if (iss.level === "error" || cur !== "error") issuesByGate.set(iss.gate_index, iss.level);
      }
      renderIssues(rep);
      recolorGates();
    } catch (err) { toast(`validate failed: ${err.message}`, true); }
  }
  function renderIssues(rep) {
    const el = $("e_issues");
    if (rep.ok && !rep.issues.length) { el.innerHTML = `<div class="issue ok">✓ course is flyable</div>`; return; }
    el.innerHTML = (rep.ok ? `<div class="issue ok">✓ flyable (warnings below)</div>` : "") +
      rep.issues.map((i) => `<div class="issue ${i.level}">${i.level === "error" ? "✕" : "⚠"} ` +
        `${i.gate_index >= 0 ? `gate ${i.gate_index}: ` : ""}${i.message}</div>`).join("");
  }

  // ---- arena preset ------------------------------------------------------------------
  async function loadPresets() {
    const sel = $("e_preset");
    try {
      const { presets } = await api.getCourses();
      sel.innerHTML = "";
      for (const p of presets) {
        const o = document.createElement("option");
        o.value = p.preset;
        o.textContent = `${p.preset}  (r=${p.radius}m)`;
        sel.appendChild(o);
      }
      sel.value = "tight";
    } catch { /* leave empty; validation falls back to tight server-side */ }
    applyPreset(sel.value || "tight", presetRadius(sel));
    sel.addEventListener("change", () => applyPreset(sel.value, presetRadius(sel)));
  }
  const presetRadius = (sel) => {
    const m = /r=([\d.]+)m/.exec(sel.selectedOptions[0]?.textContent || "");
    return m ? Number(m[1]) : 4.5;
  };
  function applyPreset(key, radius) {
    preset = key || "tight";
    arenaRadius = radius || 4.5;
    rebuildArenaRing();
    scheduleValidate();
  }

  // ---- save / fly --------------------------------------------------------------------
  $("e_save").addEventListener("click", () => doSave().then((stem) => stem && toast(`saved course "${$("e_name").value}"`)));
  $("e_fly").addEventListener("click", async () => {
    const stem = await doSave();
    if (stem) onFly?.(stem);
  });
  async function doSave() {
    try {
      const res = await api.saveCourse({ name: $("e_name").value || "course", gates }, preset);
      await onSaved?.();                             // refresh the Player's course picker first
      return res.path.split("/").pop().replace(/\.yaml$/, "");   // the saved stem (option value)
    } catch (err) { toast(`save rejected: ${err.message}`, true); return null; }
  }

  // ---- lifecycle ---------------------------------------------------------------------
  loadPresets();
  onGatesChanged(); selectGate(0);

  return {
    onShow() { view.resize(); syncGizmo(); },
    resize() { view.resize(); },
    tick() { view.render(); },
  };
}
