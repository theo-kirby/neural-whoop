// Bench tab: the always-on real-drone dashboard. Connects to /ws/flight (the FlightManager is
// always running on the bench controller), shows live telemetry + flight metrics, and drives the
// software Start / Abort. Mirrors live.js's shape (createBench returns {onShow,tick,resize,
// disconnect}); a single real-drone glyph is oriented by the telemetry attitude, and (Phase 4) a
// `b_sim` toggle opens a parallel /ws/live sim of the same policy in a split of the view.
//
// SAFETY: the Start button is a SOFTWARE clock only, and is enabled ONLY when telemetry shows the
// drone ARMED + MSP-OVERRIDE engaged on the radio. The radio still owns enable + instant kill
// (dropping override / disarming aborts within Betaflight's ~300 ms freshness window). Software
// never writes arm/aux — stopping the RC stream is the only "stop".

import * as THREE from "three";
import { createScene } from "./scene.js";
import { makeDrone } from "./drone-model.js";

const TREND = 180;                     // rolling trend length (frames) for the tilt/vz mini-chart
const FLYING = new Set(["countdown", "seek", "rise", "hover", "land"]);

export function createBench({ mount, panel, toast }) {
  const view = createScene(mount);
  const $ = (h) => panel.querySelector(`[data-h="${h}"]`);

  let ws = null;
  let connected = false;
  let sim = null;                      // Phase 4: the parallel /ws/live session
  const tiltHist = [];
  const vzHist = [];

  // The real drone: a single glyph hovering at origin, oriented live by the telemetry attitude.
  const drone = makeDrone(0xdcdcdc);
  drone.position.set(0, 0, 1.2);
  view.world.add(drone);

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
    if (sim) { sim.close(); sim = null; }
  }

  // ---- frame handling ---------------------------------------------------------------
  function dot(el, on) { el.classList.toggle("cmd-1", on); el.classList.toggle("cmd-0", !on); }

  function onFrame(msg) {
    const st = msg.status || {};
    const phase = msg.phase || "waiting";
    const link = msg.link_state || "down";
    $("b_link").textContent = `link: ${link}`;
    $("b_link").className = "status " + (link === "flying" ? "" : "");

    dot($("b_armed"), !!st.armed);
    dot($("b_override"), !!st.override_on);
    $("b_phase").textContent = phase;
    $("b_phase").className = "v cmd bench-phase-" + phase;

    // Start is a software clock, permitted ONLY when the radio already reports armed + override and
    // we're still WAITING. Abort is live during any flying phase.
    $("b_start").disabled = !(st.armed && st.override_on && phase === "waiting");
    $("b_abort").disabled = !FLYING.has(phase);

    const m = msg.metrics || {};
    const t = msg.telemetry || {};
    const fmt = (v, d = 2, suf = "") => (v === null || v === undefined || Number.isNaN(v)) ? "—" : v.toFixed(d) + suf;
    $("b_hud").innerHTML = [
      row("phase", phase),
      row("t (air)", fmt(msg.t, 2, " s")),
      row("tilt", fmt(m.tilt_deg, 1, "°")),
      row("vz est", fmt(m.vz_est, 2, " m/s")),
      row("thrust", fmt(m.thrust_norm, 2)),
      row("throttle", (msg.cmd && msg.cmd.us_thr != null) ? `${msg.cmd.us_thr} µs` : "—"),
      row("hover eff", (m.hover_eff != null) ? `${m.hover_eff} µs` : "—"),
      row("link age", fmt(m.link_age_ms, 0, " ms")),
      row("battery", fmt(m.battery_v, 2, " V")),
      row("rpm", (t.rpm_rms != null) ? `${Math.round(t.rpm_rms)}` : "—"),
    ].join("");

    // Live attitude: orient the glyph by sim-convention roll/pitch (radians).
    if (t.roll != null) drone.quaternion.setFromEuler(new THREE.Euler(t.roll, t.pitch || 0, 0, "XYZ"));

    // Rolling tilt / vz trend.
    if (m.tilt_deg != null) { tiltHist.push(m.tilt_deg); if (tiltHist.length > TREND) tiltHist.shift(); }
    if (m.vz_est != null) { vzHist.push(m.vz_est); if (vzHist.length > TREND) vzHist.shift(); }
    drawTrend();

    if (msg.events && msg.events.length) $("b_msg").textContent = msg.events[msg.events.length - 1].trim();
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

  // ---- tilt/vz trend chart ----------------------------------------------------------
  function drawTrend() {
    const canvas = $("b_trend");
    if (!canvas) return;
    const dpr = Math.min(devicePixelRatio || 1, 2);
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    canvas.width = w * dpr; canvas.height = h * dpr;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const line = (data, color, lo, hi) => {
      if (data.length < 2) return;
      ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.lineJoin = "round"; ctx.beginPath();
      data.forEach((v, i) => {
        const x = (i / (TREND - 1)) * w;
        const y = h - ((v - lo) / (hi - lo || 1)) * h;
        i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      });
      ctx.stroke();
    };
    line(tiltHist, "#e0e0e0", 0, Math.max(10, ...tiltHist));           // tilt: 0..max° (grey)
    line(vzHist, "#6ff0f0", -2, 2);                                     // vz: -2..2 m/s (cyan)
  }

  // ---- controls ---------------------------------------------------------------------
  $("b_start").addEventListener("click", () => {
    send({ type: "params", seconds: Number($("b_seconds").value) || 15,
           hz: Number($("b_hz").value) || 50, hover_us: Number($("b_hover_us").value) || 1410,
           mode: $("b_mode").value });
    send({ type: "start" });
  });
  $("b_abort").addEventListener("click", () => send({ type: "abort" }));
  if ($("b_sim")) $("b_sim").addEventListener("change", () => toggleSim($("b_sim").checked));

  // ---- Phase 4: parallel CPU-torch sim (wired in bench.js's sim companion) ----------
  function toggleSim(on) { /* Phase 4 fills this in */ }

  return {
    onShow() { view.resize(); if (!ws) connect(); },
    tick() { view.render(); if (sim) sim.tick(); },
    resize() { view.resize(); if (sim) sim.resize(); },
    disconnect,
  };
}
