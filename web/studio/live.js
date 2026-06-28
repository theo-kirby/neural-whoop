// Live interactive Studio tab: connect to the /ws/live websocket, stream a policy stepping in real
// time, and poke it — blow wind, shove it (push), drop a (modeled) block on it, and click in the
// scene to relocate the hover setpoint, watching it re-stabilize. Self-contained like editor.js:
// owns its own three.js scene (the .view3d-live mount), reusing the shared glyph/marker builders
// (drone-model.js / geometry.js) so the live drones look identical to the playback ones. The frame
// wire-format is the same per-frame replay schema (pos/quat/vel/scene) — see docs/VISUAL_CONTRACT.

import * as THREE from "three";
import { createScene } from "./scene.js";
import { makeDrone } from "./drone-model.js";
import { buildMarker, DRONE_TINTS, SCENE_COLORS, disposeGroup } from "./geometry.js";

const TRAIL_LEN = 140;            // rolling trail length (frames) per drone
const WIND_MAX = 6.0;             // max horizontal wind accel the pad maps to (m/s^2)

// A live actor: a drone glyph + its setpoint marker + a rolling position trail.
function makeActor(world, tint) {
  const glyph = makeDrone(tint);
  world.add(glyph);
  const marker = buildMarker(world, SCENE_COLORS.target, 0.13);
  const positions = new Float32Array(TRAIL_LEN * 3);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geo.setDrawRange(0, 0);
  const trail = new THREE.Line(geo, new THREE.LineBasicMaterial({ color: tint, transparent: true, opacity: 0.6 }));
  world.add(trail);
  return { glyph, marker, trail, positions, count: 0 };
}

function pushTrail(actor, p) {
  // Ring-ish rolling buffer: shift when full (cheap at a handful of drones / 50 Hz).
  const a = actor.positions;
  if (actor.count < TRAIL_LEN) {
    a.set(p, actor.count * 3);
    actor.count++;
  } else {
    a.copyWithin(0, 3);
    a.set(p, (TRAIL_LEN - 1) * 3);
  }
  actor.trail.geometry.setDrawRange(0, actor.count);
  actor.trail.geometry.attributes.position.needsUpdate = true;
}

export function createLive({ mount, panel, toast, getPolicies }) {
  const view = createScene(mount);
  const $ = (h) => panel.querySelector(`[data-h="${h}"]`);

  let actors = [];
  let ws = null;
  let connected = false;
  let isHover = false;
  let droneCount = 1;
  let setpointAlt = 1.3;          // altitude (sim z) the click-to-move plane sits at
  const policiesByPath = new Map();

  // ---- websocket plumbing -----------------------------------------------------------
  function send(obj) { if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj)); }

  function setConnected(on) {
    connected = on;
    $("l_connect").textContent = on ? "Disconnect" : "Connect";
    $("l_connect").classList.toggle("primary", !on);
    for (const h of ["l_push", "l_drop", "l_pause", "l_reset", "l_speed", "l_drone"]) {
      const el = $(h); if (el) el.disabled = !on;
    }
    $("l_policy").disabled = on;
    $("l_drones").disabled = on;
  }

  function clearActors() {
    for (const a of actors) {
      disposeGroup([a.glyph, a.marker, a.trail], view.world);
    }
    actors = [];
  }

  function buildActors(n) {
    clearActors();
    for (let i = 0; i < n; i++) actors.push(makeActor(view.world, DRONE_TINTS[i % DRONE_TINTS.length]));
  }

  function onFrame(msg) {
    const drones = msg.drones || [];
    for (let i = 0; i < drones.length && i < actors.length; i++) {
      const d = drones[i], a = actors[i];
      a.glyph.position.set(d.pos[0], d.pos[1], d.pos[2]);
      a.glyph.quaternion.set(d.quat[0], d.quat[1], d.quat[2], d.quat[3]);
      pushTrail(a, d.pos);
      const tgt = d.scene && d.scene.target;
      if (tgt) { a.marker.visible = true; a.marker.position.set(tgt[0], tgt[1], tgt[2]); }
      else a.marker.visible = false;
    }
    // HUD: hero (drone 0) speed + tilt.
    const d0 = drones[0];
    if (d0) {
      const spd = Math.hypot(d0.vel[0], d0.vel[1], d0.vel[2]);
      const tilt = Math.hypot(d0.rpy[0], d0.rpy[1]) * 180 / Math.PI;
      $("l_hud").textContent = `t ${msg.t.toFixed(1)}s · speed ${spd.toFixed(2)} m/s · tilt ${tilt.toFixed(0)}°`;
    }
  }

  function connect() {
    const policy = $("l_policy").value;
    if (!policy) { toast("pick a policy", true); return; }
    droneCount = Math.max(1, Math.min(8, Number($("l_drones").value) || 1));
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws/live`);
    $("l_status").textContent = "connecting…";
    ws.onopen = () => send({ policy, drone_count: droneCount, dr: false });
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "ready") {
        isHover = !!msg.info.is_hover;
        droneCount = msg.info.drone_count;
        setpointAlt = (msg.info.scene_info && msg.info.scene_info.z_default) || setpointAlt;
        buildActors(droneCount);
        populateDroneSelector(droneCount);
        setConnected(true);
        $("l_status").textContent = isHover
          ? `live · ${droneCount} drone(s) · click the floor to move the hover point`
          : `live · ${droneCount} drone(s) · ${msg.info.task} (setpoint move is hover-only)`;
        $("l_hint").classList.toggle("hidden", isHover);
      } else if (msg.type === "frame") {
        onFrame(msg);
      } else if (msg.type === "error") {
        toast(`live: ${msg.detail}`, true);
        $("l_status").textContent = "";
      }
    };
    ws.onclose = () => { setConnected(false); $("l_status").textContent = "disconnected"; };
    ws.onerror = () => { toast("live socket error", true); };
  }

  function disconnect() { if (ws) { ws.close(); ws = null; } setConnected(false); }

  // ---- controls ---------------------------------------------------------------------
  function populateDroneSelector(n) {
    const sel = $("l_drone");
    sel.innerHTML = "";
    const all = document.createElement("option"); all.value = "-1"; all.textContent = "all drones";
    sel.appendChild(all);
    for (let i = 0; i < n; i++) {
      const o = document.createElement("option"); o.value = String(i); o.textContent = `drone ${i}`;
      sel.appendChild(o);
    }
  }
  const selectedDrone = () => Number($("l_drone").value);

  // Wind pad: pointer position within the square maps to a horizontal wind vector (sim x,y). The
  // vertical slider adds a z component. Center = calm.
  const pad = () => panel.querySelector("[data-h=l_windpad]");
  let windXY = [0, 0];
  function applyWind() {
    const z = Number($("l_windz").value) || 0;
    send({ type: "wind", vec: [windXY[0], windXY[1], z] });
    $("l_windread").textContent = `wind (${windXY[0].toFixed(1)}, ${windXY[1].toFixed(1)}, ${z.toFixed(1)}) m/s²`;
  }
  function padTo(ev) {
    const el = pad(), r = el.getBoundingClientRect();
    const nx = ((ev.clientX - r.left) / r.width) * 2 - 1;   // [-1,1] right
    const ny = ((ev.clientY - r.top) / r.height) * 2 - 1;   // [-1,1] down
    // Screen right -> +x sim; screen up -> +y sim (so the pad reads like a top-down map).
    windXY = [
      Math.max(-1, Math.min(1, nx)) * WIND_MAX,
      Math.max(-1, Math.min(1, -ny)) * WIND_MAX,
    ];
    const dot = panel.querySelector("[data-h=l_winddot]");
    dot.style.left = `${(windXY[0] / WIND_MAX * 0.5 + 0.5) * 100}%`;
    dot.style.top = `${(-windXY[1] / WIND_MAX * 0.5 + 0.5) * 100}%`;
    applyWind();
  }

  // Click-to-move the hover setpoint: raycast the pointer onto a horizontal plane at setpointAlt
  // (sim z). The `world` group's local frame IS the sim frame, so worldToLocal gives sim coords.
  const raycaster = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);  // three-world y = setpointAlt
  const hit = new THREE.Vector3();
  function onSceneClick(ev) {
    if (!connected || !isHover) return;
    const r = view.renderer.domElement.getBoundingClientRect();
    ndc.x = ((ev.clientX - r.left) / r.width) * 2 - 1;
    ndc.y = -((ev.clientY - r.top) / r.height) * 2 + 1;
    raycaster.setFromCamera(ndc, view.camera);
    plane.constant = -setpointAlt;                 // y = setpointAlt in three-world (sim z)
    if (!raycaster.ray.intersectPlane(plane, hit)) return;
    const sim = view.world.worldToLocal(hit.clone());  // -> sim (x, y, z)
    send({ type: "setpoint", drone: selectedDrone(), pos: [sim.x, sim.y, setpointAlt] });
  }

  // ---- wiring -----------------------------------------------------------------------
  $("l_connect").addEventListener("click", () => (connected ? disconnect() : connect()));
  $("l_push").addEventListener("click", () => send({ type: "push", drone: selectedDrone() }));
  $("l_drop").addEventListener("click", () => send({ type: "drop", drone: selectedDrone() }));
  $("l_reset").addEventListener("click", () => { for (const a of actors) { a.count = 0; a.trail.geometry.setDrawRange(0, 0); } send({ type: "reset" }); });
  let paused = false;
  $("l_pause").addEventListener("click", () => {
    paused = !paused;
    send({ type: paused ? "pause" : "resume" });
    $("l_pause").textContent = paused ? "▶ Resume" : "⏸ Pause";
  });
  $("l_speed").addEventListener("change", (e) => send({ type: "speed", value: Number(e.target.value) }));
  $("l_windz").addEventListener("input", applyWind);
  panel.querySelector("[data-h=l_windcalm]").addEventListener("click", () => {
    windXY = [0, 0]; $("l_windz").value = "0";
    const dot = panel.querySelector("[data-h=l_winddot]"); dot.style.left = "50%"; dot.style.top = "50%";
    applyWind();
  });
  // Wind pad pointer drag.
  let padding = false;
  pad().addEventListener("pointerdown", (e) => { padding = true; pad().setPointerCapture(e.pointerId); padTo(e); });
  pad().addEventListener("pointermove", (e) => { if (padding) padTo(e); });
  pad().addEventListener("pointerup", (e) => { padding = false; });
  // Scene click for setpoint move (only when not orbiting — use a quick click heuristic).
  let downAt = null;
  view.renderer.domElement.addEventListener("pointerdown", (e) => { downAt = { x: e.clientX, y: e.clientY, t: performance.now() }; });
  view.renderer.domElement.addEventListener("pointerup", (e) => {
    if (!downAt) return;
    const moved = Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y);
    if (moved < 5 && performance.now() - downAt.t < 400) onSceneClick(e);
    downAt = null;
  });

  // ---- policy list ------------------------------------------------------------------
  async function loadPolicies() {
    try {
      const policies = await getPolicies();
      const sel = $("l_policy");
      sel.innerHTML = "";
      policiesByPath.clear();
      // Hover policies first (the family the editor is built for), then the rest.
      const hover = policies.filter((p) => p.task === "hover");
      const rest = policies.filter((p) => p.task !== "hover");
      const addOpts = (label, list) => {
        if (!list.length) return;
        const g = document.createElement("optgroup"); g.label = label;
        for (const p of list) {
          policiesByPath.set(p.path, p);
          const o = document.createElement("option"); o.value = p.path; o.textContent = p.name;
          g.appendChild(o);
        }
        sel.appendChild(g);
      };
      addOpts("hover / auto-stabilize", hover);
      addOpts("other policies", rest);
      if (hover.length) sel.value = hover[0].path;
    } catch (err) { toast(`live: couldn't load policies: ${err.message}`, true); }
  }

  return {
    onShow() { view.resize(); if (!policiesByPath.size) loadPolicies(); },
    tick() { view.render(); },
    resize() { view.resize(); },
    disconnect,
  };
}
