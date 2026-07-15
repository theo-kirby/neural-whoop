// Real tab: the always-on real-drone dashboard. Connects to /ws/flight (the FlightManager is
// always running on the bench controller), shows live telemetry + flight metrics, and drives the
// software Start / Abort. createBench returns {onShow,tick,resize,disconnect}; a single real-drone
// glyph is oriented by the telemetry attitude, and a `b_sim` toggle opens a parallel /ws/live sim
// of the same policy in a split of the view. A CALIBRATION mode (Betaflight-setup style) zooms the
// camera onto the glyph so you can tilt the drone by hand and watch the on-screen rotation track,
// with rolling attitude / gyro / battery+throttle / link-age charts in the sidebar.
//
// SAFETY: the Start button is a SOFTWARE clock only, and is enabled ONLY when telemetry shows the
// drone ARMED + MSP-OVERRIDE engaged on the radio. The radio still owns enable + instant kill
// (dropping override / disarming aborts within Betaflight's ~300 ms freshness window). Software
// never writes arm/aux — stopping the RC stream is the only "stop".

import * as THREE from "three";
import { createScene } from "./scene.js";
import { makeDrone } from "./drone-model.js";
import { buildRoom } from "./geometry.js";
import { frameDrone } from "./cameras.js";

const TREND = 180;                     // rolling trend length (frames) for every mini-chart
const FLYING = new Set(["countdown", "seek", "rise", "hover", "flip", "land"]);
const SIM_OFFSET = 2.0;                // the parallel-sim drone sits this far +x of the real one
const SEED_HINTS = ["hover_blind_air65_d50var_s8", "hover_blind", "hover"];  // parallel-sim policy
const RAD2DEG = 180 / Math.PI;
const GREY = "#e0e0e0", CYAN = "#6ff0f0", AMBER = "#ffd23f";

export function createBench({ mount, panel, toast, getPolicies }) {
  // grid:false — the real-drone view uses a bounded 10 m³ reference room instead of the infinite
  // course grid, so the hand-flown / hover drone has a fixed metric backdrop.
  const view = createScene(mount, { grid: false });
  buildRoom(view.world, { size: 10, cell: 1, floorZ: 0 });
  // Extra fill so the greybox room reads bright and even (the shared scene lighting is tuned dark
  // for the course view).
  view.scene.add(new THREE.HemisphereLight(0xffffff, 0x9a9a9a, 1.9));
  const $ = (h) => panel.querySelector(`[data-h="${h}"]`);

  let ws = null;
  let connected = false;
  let lastPhase = "waiting";           // Flip doubles as a starter when pressed while WAITING
  let cal = false;                     // calibration mode (close-up attitude check)?
  const tiltHist = [];
  const vzHist = [];
  // Calibration ring buffers — one per plotted signal (filled only while cal mode is on).
  const calHist = { roll: [], pitch: [], yaw: [], p: [], q: [], r: [], vbat: [], thr: [], age: [] };
  const push = (buf, v) => { buf.push(v); if (buf.length > TREND) buf.shift(); };

  // The real drone: a single glyph hovering at origin, oriented live by the telemetry attitude.
  const drone = makeDrone(0xdcdcdc);
  drone.position.set(0, 0, 1.2);
  view.world.add(drone);

  // Phase 4: the parallel CPU-torch sim of the same policy, shown +x of the real drone.
  let simWs = null;
  let simDrone = null;

  function send(obj) { if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj)); }

  // ---- websocket plumbing -----------------------------------------------------------
  function connect() {
    if (ws) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws/flight`);
    $("b_link").textContent = "connecting…";
    ws.onopen = () => { connected = true; };
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "error") { toast(`bench: ${msg.detail}`, true); $("b_link").textContent = msg.detail; return; }
      if (msg.type === "report") { onReport(msg); return; }
      onFrame(msg);
    };
    ws.onclose = () => { connected = false; $("b_link").textContent = "disconnected"; ws = null; };
    ws.onerror = () => { toast("bench socket error", true); };
  }

  function disconnect() {
    if (ws) { ws.onclose = null; ws.close(); ws = null; }
    connected = false;
    stopSim();
  }

  // ---- frame handling ---------------------------------------------------------------
  function dot(el, on) { el.classList.toggle("cmd-1", on); el.classList.toggle("cmd-0", !on); }

  function onFrame(msg) {
    const st = msg.status || {};
    const phase = msg.phase || "waiting";
    lastPhase = phase;
    const link = msg.link_state || "down";
    $("b_link").textContent = `link: ${link}`;
    $("b_link").className = "status " + (link === "flying" ? "" : "");

    dot($("b_armed"), !!st.armed);
    dot($("b_override"), !!st.override_on);
    $("b_phase").textContent = phase;
    $("b_phase").className = "v cmd bench-phase-" + phase;

    // Start is a software clock, permitted ONLY when the radio already reports armed + override and
    // we're still WAITING. Abort is live during any flying phase. Flip is a learned acro maneuver,
    // permitted in free HOVER (the backend re-gates it: fresh link + near-level) — or while WAITING
    // under the same gate as Start, where it starts the flight and auto-flips once hover settles.
    const startable = st.armed && st.override_on && phase === "waiting";
    $("b_start").disabled = !startable;
    if ($("b_flip")) $("b_flip").disabled = !(phase === "hover" || startable);
    $("b_abort").disabled = !FLYING.has(phase);

    const m = msg.metrics || {};
    const t = msg.telemetry || {};
    const fmt = (v, d = 2, suf = "") => (v === null || v === undefined || Number.isNaN(v)) ? "—" : v.toFixed(d) + suf;
    $("b_hud").innerHTML = [
      row("phase", phase),
      row("t (air)", fmt(msg.t, 2, " s")),
      ...(m.flipping ? [row("flip rot left", fmt(m.rotation_remaining, 2))] : []),
      row("tilt", fmt(m.tilt_deg, 1, "°")),
      row("vz est", fmt(m.vz_est, 2, " m/s")),
      row("thrust", fmt(m.thrust_norm, 2)),
      row("throttle", (msg.cmd && msg.cmd.us_thr != null) ? `${msg.cmd.us_thr} µs` : "—"),
      row("hover eff", (m.hover_eff != null) ? `${m.hover_eff} µs` : "—"),
      row("link age", fmt(m.link_age_ms, 0, " ms")),
      row("battery", fmt(m.battery_v, 2, " V")),
      row("rpm", (t.rpm_rms != null) ? `${Math.round(t.rpm_rms)}` : "—"),
    ].join("");

    // Live attitude: orient the glyph by sim-convention roll/pitch/yaw (radians). "ZYX" applies
    // yaw about sim z first, then pitch, then roll — the aerospace composition, so a hand-yawed
    // drone still rolls about its own (yawed) body axes on screen.
    if (t.roll != null) {
      drone.quaternion.setFromEuler(new THREE.Euler(t.roll, t.pitch || 0, t.yaw || 0, "ZYX"));
    }

    // Rolling tilt / vz trend (dashboard).
    if (m.tilt_deg != null) push(tiltHist, m.tilt_deg);
    if (m.vz_est != null) push(vzHist, m.vz_est);

    if (cal) onCalFrame(msg, t, m, st, link);
    else drawTrend();

    if (msg.events && msg.events.length) $("b_msg").textContent = msg.events[msg.events.length - 1].trim();
  }

  // ---- calibration mode ----------------------------------------------------------------
  // Close-up attitude check: zoom onto the glyph, tilt the drone by hand, watch the rotation +
  // four rolling signal charts track live. Camera restores to the default wide view on exit.
  function setCal(on) {
    cal = on;
    $("b_dash").classList.toggle("hidden", on);
    $("b_calpanel").classList.toggle("hidden", !on);
    if (on) {
      frameDrone(view, [drone.position.x, drone.position.y, drone.position.z], 1.1);
    } else {
      view.camera.position.set(8, 7, 11);          // the scene factory's default wide view
      view.controls.target.set(0, 0, 0);
      view.controls.update();
    }
  }

  function onCalFrame(msg, t, m, st, link) {
    $("c_link").textContent = `link: ${link}`;
    dot($("c_armed"), !!st.armed);
    dot($("c_override"), !!st.override_on);
    const deg = (v) => (v == null || Number.isNaN(v)) ? "—" : (v * RAD2DEG).toFixed(1);
    $("c_roll").textContent = deg(t.roll);
    $("c_pitch").textContent = deg(t.pitch);
    $("c_yaw").textContent = deg(t.yaw);
    if (t.roll != null) { push(calHist.roll, t.roll * RAD2DEG); push(calHist.pitch, (t.pitch || 0) * RAD2DEG); push(calHist.yaw, (t.yaw || 0) * RAD2DEG); }
    if (t.p != null) { push(calHist.p, t.p); push(calHist.q, t.q || 0); push(calHist.r, t.r || 0); }
    if (t.vbat != null) push(calHist.vbat, t.vbat);
    if (msg.cmd && msg.cmd.us_thr != null) push(calHist.thr, msg.cmd.us_thr);
    const age = m.link_age_ms ?? t.obs_age_ms;
    if (age != null) push(calHist.age, age);
    // Symmetric auto-scale for the signed signals so level reads as a centered line.
    const attLim = Math.max(20, ...calHist.roll.map(Math.abs), ...calHist.pitch.map(Math.abs), ...calHist.yaw.map(Math.abs));
    const gyroLim = Math.max(2, ...calHist.p.map(Math.abs), ...calHist.q.map(Math.abs), ...calHist.r.map(Math.abs));
    drawSeries($("c_att"), [
      { data: calHist.roll, color: GREY, lo: -attLim, hi: attLim },
      { data: calHist.pitch, color: CYAN, lo: -attLim, hi: attLim },
      { data: calHist.yaw, color: AMBER, lo: -attLim, hi: attLim },
    ]);
    drawSeries($("c_gyro"), [
      { data: calHist.p, color: GREY, lo: -gyroLim, hi: gyroLim },
      { data: calHist.q, color: CYAN, lo: -gyroLim, hi: gyroLim },
      { data: calHist.r, color: AMBER, lo: -gyroLim, hi: gyroLim },
    ]);
    drawSeries($("c_batt"), [
      { data: calHist.vbat, color: GREY, lo: 3.2, hi: 4.4 },
      { data: calHist.thr, color: CYAN, lo: 1000, hi: 2000 },
    ]);
    drawSeries($("c_linkage"), [
      { data: calHist.age, color: GREY, lo: 0, hi: Math.max(50, ...calHist.age) },
    ]);
  }

  function onReport(msg) {
    // Phase 5: a completed flight's auto-report is ready.
    const m = msg.metrics || {};
    const bits = [];
    if (m.median_tilt_deg != null) bits.push(`tilt ${m.median_tilt_deg.toFixed(1)}°`);
    if (m.vz_rail_frames != null) bits.push(`vz-rail ${m.vz_rail_frames}`);
    if (m.link_p99_ms != null) bits.push(`link p99 ${m.link_p99_ms.toFixed(0)}ms`);
    if (m.battery_sag_v != null) bits.push(`sag ${m.battery_sag_v.toFixed(2)}V`);
    const panelEl = $("b_report");
    panelEl.classList.remove("hidden");
    const link = msg.out_dir ? `<a href="/api/runs/${encodeURIComponent(msg.csv || "")}" target="_blank">flight CSV</a>` : "";
    panelEl.innerHTML = `<div class="title">flight report ready</div><div class="hint">${bits.join(" · ") || "written"}</div>${link}`;
    toast("flight report ready");
  }

  function row(k, v) { return `<div class="row"><span class="k">${k}</span><span class="v">${v}</span></div>`; }

  // ---- rolling mini-charts ------------------------------------------------------------
  // N overlaid series on one canvas, each with its own [lo,hi] scale (so e.g. vbat and throttle
  // share a chart at native units). Rolling x: TREND frames wide.
  function drawSeries(canvas, series) {
    if (!canvas) return;
    const dpr = Math.min(devicePixelRatio || 1, 2);
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    canvas.width = w * dpr; canvas.height = h * dpr;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    for (const { data, color, lo, hi } of series) {
      if (data.length < 2) continue;
      ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.lineJoin = "round"; ctx.beginPath();
      data.forEach((v, i) => {
        const x = (i / (TREND - 1)) * w;
        const y = h - ((v - lo) / (hi - lo || 1)) * h;
        i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      });
      ctx.stroke();
    }
  }

  function drawTrend() {
    drawSeries($("b_trend"), [
      { data: tiltHist, color: GREY, lo: 0, hi: Math.max(10, ...tiltHist) },  // tilt: 0..max°
      { data: vzHist, color: CYAN, lo: -2, hi: 2 },                            // vz: -2..2 m/s
    ]);
  }

  // ---- controls ---------------------------------------------------------------------
  function sendParams() {
    // Level trim (deg), policy's-view obs offset: + pushes right / nose-down-forward, so dial it
    // OPPOSITE the drift (drifts forward -> negative pitch trim). Backend field names are the
    // FlightParams ones (_PARAM_FIELDS).
    send({ type: "params", seconds: Number($("b_seconds").value) || 15,
           hz: Number($("b_hz").value) || 50, hover_us: Number($("b_hover_us").value) || 1410,
           trim_roll_deg: Number($("b_trim_roll").value) || 0,
           trim_pitch_deg: Number($("b_trim_pitch").value) || 0,
           mode: $("b_mode").value });
  }
  $("b_start").addEventListener("click", () => { sendParams(); send({ type: "start" }); });
  if ($("b_flip")) $("b_flip").addEventListener("click", () => {
    // Mid-hover: fire the maneuver. While WAITING: this IS the starter — apply the panel knobs
    // first (like Start), then take off, auto-flip once hover settles, and keep hovering.
    if (lastPhase === "waiting") sendParams();
    send({ type: "flip" });
  });
  $("b_abort").addEventListener("click", () => send({ type: "abort" }));
  if ($("b_sim")) $("b_sim").addEventListener("change", () => toggleSim($("b_sim").checked));
  $("b_cal").addEventListener("click", () => setCal(true));
  $("c_exit").addEventListener("click", () => setCal(false));

  // ---- Phase 4: parallel CPU-torch sim of the same policy --------------------------
  async function toggleSim(on) {
    if (!on) { stopSim(); return; }
    let path = null;
    try {
      const policies = await getPolicies();
      for (const hint of SEED_HINTS) {
        const hit = policies.find((p) => p.name === hint) || policies.find((p) => (p.name || "").includes(hint) || p.task === hint);
        if (hit) { path = hit.path; break; }
      }
    } catch (err) { toast(`sim: couldn't load policies: ${err.message}`, true); }
    if (!path) { toast("no hover policy found for the parallel sim", true); $("b_sim").checked = false; return; }

    simDrone = makeDrone(0x6ff0f0);              // cyan = the sim twin
    view.world.add(simDrone);
    const proto = location.protocol === "https:" ? "wss" : "ws";
    simWs = new WebSocket(`${proto}://${location.host}/ws/live`);
    simWs.onopen = () => simWs.send(JSON.stringify({ policy: path, drone_count: 1, dr: false }));
    simWs.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "error") { toast(`sim: ${msg.detail}`, true); stopSim(); $("b_sim").checked = false; return; }
      if (msg.type === "frame" && msg.drones && msg.drones[0] && simDrone) {
        const d = msg.drones[0];
        simDrone.position.set(d.pos[0] + SIM_OFFSET, d.pos[1], d.pos[2]);
        simDrone.quaternion.set(d.quat[0], d.quat[1], d.quat[2], d.quat[3]);
      }
    };
    simWs.onclose = () => { simWs = null; };
    simWs.onerror = () => { toast("sim socket error", true); };
  }

  function stopSim() {
    if (simWs) { simWs.onclose = null; simWs.close(); simWs = null; }
    if (simDrone) { view.world.remove(simDrone); simDrone = null; }
  }

  return {
    onShow() { view.resize(); if (!ws) connect(); },
    tick() { view.render(); },
    resize() { view.resize(); },
    disconnect,
  };
}
