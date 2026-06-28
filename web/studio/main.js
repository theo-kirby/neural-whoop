// Studio app shell: populate the policy/course selectors, show a picked policy's metadata +
// training curves, run a fixed-course rollout on the GPU, load the returned v2 replay, and play it
// back. The replay view carries movable/resizable PiP frames: one onboard-FPV box PER drone plus a
// top-down chase box. Single-file app — the Editor/Metrics tabs from the lab are deferred.

import { createScene } from "./scene.js";
import { Playback } from "./playback.js";
import { getPolicies, getCourses, getScalars, postRollout } from "./api.js";
import { loadRunByPath } from "./run-loader.js";

const $ = (h) => document.querySelector(`[data-h="${h}"]`);
const hex = (n) => "#" + (n >>> 0).toString(16).padStart(6, "0").slice(-6);

// ---- toast --------------------------------------------------------------------------
const toastEl = document.getElementById("toast");
let toastTimer = null;
function toast(msg, isErr = false) {
  toastEl.textContent = msg;
  toastEl.className = "toast" + (isErr ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.add("hidden"), isErr ? 7000 : 3500);
}

// ---- scene + playback ---------------------------------------------------------------
const view = createScene(document.querySelector(".view3d"));
const playback = new Playback(view);
let fpvOn = true, topOn = true;     // FPV-per-drone + top-down insets shown by default
let fpvFrames = [];                 // [{ frame, body, idx }] — one per drone, built per run
let sceneInfo = {};                 // meta.scene_info of the loaded run (command labels, standoff…)
const policiesByPath = new Map();   // path -> policy meta (for the details panel + scalars run name)

// Screen-space rect of an element in the WebGL convention (origin = canvas BOTTOM-left).
function insetRect(el) {
  const cr = view.renderer.domElement.getBoundingClientRect();
  const br = el.getBoundingClientRect();
  return { x: br.left - cr.left, y: cr.height - (br.top - cr.top + br.height), w: br.width, h: br.height };
}

// ---- movable + resizable PiP frames -------------------------------------------------
// Drag by a handle (the header); resizing is the element's native CSS `resize: both` corner. We
// just clamp the drag so a frame can't be flung off the view.
function makeDraggable(frame, handle) {
  let sx = 0, sy = 0, ox = 0, oy = 0, id = null;
  handle.addEventListener("pointerdown", (e) => {
    id = e.pointerId;
    handle.setPointerCapture(id);
    sx = e.clientX; sy = e.clientY;
    ox = frame.offsetLeft; oy = frame.offsetTop;
    frame.classList.add("dragging");
  });
  handle.addEventListener("pointermove", (e) => {
    if (id === null) return;
    const host = frame.parentElement.getBoundingClientRect();
    const nx = Math.max(0, Math.min(host.width - frame.offsetWidth, ox + e.clientX - sx));
    const ny = Math.max(0, Math.min(host.height - frame.offsetHeight, oy + e.clientY - sy));
    frame.style.left = `${nx}px`; frame.style.top = `${ny}px`;
  });
  const end = () => { if (id !== null) { handle.releasePointerCapture(id); id = null; frame.classList.remove("dragging"); } };
  handle.addEventListener("pointerup", end);
  handle.addEventListener("pointercancel", end);
}

// Build one FPV frame per drone, tiled top-left, each tinted to match its drone glyph.
function buildFpvFrames() {
  const host = $("fpvframes");
  host.innerHTML = "";
  fpvFrames = [];
  const W = 232, H = 162, gap = 10, x0 = 12, y0 = 12;
  const vw = view.mount.clientWidth || 800;
  const cols = Math.max(1, Math.floor((vw * 0.62) / (W + gap)));
  playback.actors.forEach((actor, i) => {
    const col = i % cols, row = Math.floor(i / cols);
    const frame = document.createElement("div");
    frame.className = "cam-frame";
    frame.style.cssText = `left:${x0 + col * (W + gap)}px;top:${y0 + row * (H + gap)}px;width:${W}px;height:${H}px;`;
    const head = document.createElement("div");
    head.className = "cam-head";
    head.dataset.drag = "";
    const single = playback.actors.length === 1;
    head.innerHTML = `<span class="dot" style="background:${hex(actor.tint)}"></span>` +
      `<span class="name">FPV · ${single ? "onboard" : "drone " + i}</span>`;
    const body = document.createElement("div");
    body.className = "cam-body";
    frame.append(head, body);
    host.appendChild(frame);
    makeDraggable(frame, head);
    fpvFrames.push({ frame, body, idx: i });
  });
  host.classList.toggle("hidden", !fpvOn);
}

// ---- transport wiring ---------------------------------------------------------------
function syncPlayBtn() { $("play").textContent = playback.playing ? "⏸ Pause" : "▶ Play"; }
playback.onStateChange = () => { syncPlayBtn(); $("scrub").value = String(Math.floor(playback.idx)); };
playback.onFrame = (f, i) => {
  const spd = Math.hypot(f.vel[0], f.vel[1], f.vel[2]);
  $("step").textContent = String(f.step);
  // Gate row carries gate progress for gate tasks; for gateless follow/formation it shows the
  // distance to whatever the hero tracks (slot, else target) read off the scene channel.
  const nGates = (playback.episode?.gates || []).length;
  if (nGates) {
    $("gaterow").classList.remove("hidden");
    $("gate").textContent = `${f.gate_idx}/${nGates}`;
  } else {
    $("gaterow").classList.add("hidden");
  }
  $("spd").textContent = `${spd.toFixed(2)} m/s`;
  $("reward").textContent = f.cum_reward.toFixed(1);
  $("tcur").textContent = (i * playback.dt).toFixed(2);
  $("fcur").textContent = String(i + 1);
  $("scrub").value = String(i);
  // Command chip (gesture/command_follow): label the raw command via meta.scene_info.command_labels.
  const labels = sceneInfo.command_labels;
  const sc = f.scene || {};
  if (labels && sc.command !== undefined) {
    const cmd = labels[Math.round(sc.command)] ?? String(sc.command);
    const chip = $("cmd");
    chip.textContent = cmd;
    chip.className = "v cmd cmd-" + Math.round(sc.command);
    $("cmdrow").classList.remove("hidden");
  } else {
    $("cmdrow").classList.add("hidden");
  }
};

$("play").addEventListener("click", () => playback.setPlaying(!playback.playing));
$("scrub").addEventListener("input", (e) => playback.seek(Number(e.target.value)));
$("speed").addEventListener("change", (e) => { playback.speed = Number(e.target.value); });
$("follow").addEventListener("change", (e) => { playback.follow = e.target.checked; });
$("fpv").addEventListener("change", (e) => { fpvOn = e.target.checked; $("fpvframes").classList.toggle("hidden", !fpvOn); });
$("top").addEventListener("change", (e) => { topOn = e.target.checked; $("topframe").classList.toggle("hidden", !topOn); });
$("trail").addEventListener("change", (e) => playback.setTrailVisible(e.target.checked));

// The top-down frame is movable from the start; FPV frames get wired in buildFpvFrames().
makeDraggable($("topframe"), $("topframe").querySelector("[data-drag]"));

// ---- policy metadata + training charts ----------------------------------------------
function fmtDate(epoch) {
  if (!epoch) return "—";
  const d = new Date(epoch * 1000);
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) +
    " " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}
function fmtSteps(n) {
  if (n == null) return "—";
  if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(0) + "k";
  return String(n);
}
function kvRow(k, v) { return `<div class="kv"><span class="k">${k}</span><span class="v">${v}</span></div>`; }

function renderMeta(p) {
  const box = $("meta");
  if (!p) { box.innerHTML = `<div class="charts-empty">pick a policy to see its details.</div>`; return; }
  const ev = p.eval || {};
  const rows = [
    kvRow("name", `${p.recommended ? "★ " : ""}${p.name}`),
    kvRow("task", `${p.task || "—"}${p.family_label ? ` · ${p.family_label}` : ""}`),
    kvRow("created", fmtDate(p.created)),
    kvRow("trained", `${fmtSteps(p.step)} steps`),
    kvRow("obs / act", `${p.obs_dim ?? "—"} / ${p.act_dim ?? "—"}`),
  ];
  if (ev.best_lap_time != null) rows.push(kvRow("best lap", `${ev.best_lap_time.toFixed(2)} s`));
  if (ev.oracle_lap_time != null) rows.push(kvRow("oracle lap", `${ev.oracle_lap_time.toFixed(2)} s`));
  if (ev.lap_completion_rate != null) rows.push(kvRow("lap completion", `${(ev.lap_completion_rate * 100).toFixed(0)}%`));
  if (ev.mean_reward != null) rows.push(kvRow("mean reward", ev.mean_reward.toFixed(3)));
  if (ev.crash_rate_per_step != null) rows.push(kvRow("crash / step", ev.crash_rate_per_step.toExponential(1)));
  box.innerHTML = rows.join("");
}

// Curated training curves (label, formatter for the last value). Only those present are drawn.
const CHART_SPECS = [
  ["charts/episodic_return", "episodic return", (v) => v.toFixed(1)],
  ["metrics/best_lap_time", "best lap (s)", (v) => v.toFixed(2)],
  ["metrics/lap_completion_rate", "lap completion", (v) => `${(v * 100).toFixed(0)}%`],
  ["losses/entropy", "policy entropy", (v) => v.toFixed(2)],
  ["losses/value", "value loss", (v) => v.toFixed(2)],
  ["charts/learning_rate", "learning rate", (v) => v.toExponential(1)],
];
let lastScalars = null;   // cache so we can redraw on fold-open / resize without refetching

function drawChart(canvas, steps, values) {
  const dpr = Math.min(devicePixelRatio || 1, 2);
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (!w || !h) return;                         // collapsed/hidden — redrawn when revealed
  canvas.width = w * dpr; canvas.height = h * dpr;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  if (values.length < 2) return;
  const pad = 6;
  let lo = Math.min(...values), hi = Math.max(...values);
  if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
  const x0 = steps[0], x1 = steps[steps.length - 1] || 1;
  const px = (s) => pad + ((s - x0) / (x1 - x0 || 1)) * (w - 2 * pad);
  const py = (v) => h - pad - ((v - lo) / (hi - lo)) * (h - 2 * pad);
  // Baseline + line.
  ctx.strokeStyle = "#3a3a3a"; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(pad, h - pad); ctx.lineTo(w - pad, h - pad); ctx.stroke();
  ctx.strokeStyle = "#e0e0e0"; ctx.lineWidth = 1.5; ctx.lineJoin = "round";
  ctx.beginPath();
  steps.forEach((s, i) => { const X = px(s), Y = py(values[i]); i ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y); });
  ctx.stroke();
  // Endpoint dot.
  ctx.fillStyle = "#f4f4f4";
  ctx.beginPath(); ctx.arc(px(x1), py(values[values.length - 1]), 2.2, 0, Math.PI * 2); ctx.fill();
}

function renderCharts() {
  const host = $("charts");
  const tags = lastScalars?.tags || {};
  const present = CHART_SPECS.filter(([tag]) => (tags[tag]?.values || []).length > 1);
  if (!present.length) {
    host.innerHTML = `<div class="charts-empty">${lastScalars ? "no training curves recorded for this run." : "pick a policy to load its training curves."}</div>`;
    return;
  }
  host.innerHTML = present.map(([tag, label, fmt]) => {
    const s = tags[tag];
    const last = fmt(s.values[s.values.length - 1]);
    return `<div class="chart"><div class="clabel"><span>${label}</span><b>${last}</b></div><canvas></canvas></div>`;
  }).join("");
  // Canvases exist in the DOM now — draw into each.
  host.querySelectorAll(".chart").forEach((el, k) => {
    const [tag] = present[k];
    const s = tags[tag];
    drawChart(el.querySelector("canvas"), s.steps, s.values);
  });
}

async function loadScalarsFor(p) {
  lastScalars = null;
  if (!p || !p.has_scalars) { renderCharts(); return; }
  try {
    lastScalars = await getScalars(p.run || p.name);
  } catch (err) {
    lastScalars = null;
    toast(`couldn't load training curves: ${err.message}`, true);
  }
  renderCharts();
}

function onPolicyPicked() {
  const p = policiesByPath.get($("policy").value);
  renderMeta(p);
  loadScalarsFor(p);
  // Gateless follow/formation policies fly their own arena — hide the course + preset-gates fields
  // (no course to pick). The drone-count input stays (it maps to envs / n_agents per family).
  const needsCourse = !p || p.needs_course !== false;
  $("coursefield").classList.toggle("hidden", !needsCourse);
  $("gatesfield").classList.toggle("hidden", !needsCourse);
}
$("policy").addEventListener("change", onPolicyPicked);
// Charts only have a measurable size once their fold is open — (re)draw on reveal + on resize.
$("chartfold").addEventListener("toggle", () => { if ($("chartfold").open) renderCharts(); });

// ---- selectors ----------------------------------------------------------------------
async function loadSelectors() {
  try {
    const [policies, courses] = await Promise.all([getPolicies(), getCourses()]);
    const pol = $("policy");
    pol.innerHTML = "";
    policiesByPath.clear();
    for (const p of policies) policiesByPath.set(p.path, p);

    // Group the picker so it isn't a flat wall of experiment runs: a "★ recommended" group first
    // (the curated known-good policy per family), then one group per family. Within a group, sort
    // best-lap first (gate tasks) then by name.
    const FAM_ORDER = ["gate", "gate_swarm", "follow", "formation"];
    const optgroup = (label) => { const g = document.createElement("optgroup"); g.label = label; return g; };
    const optionFor = (p, star) => {
      const o = document.createElement("option");
      o.value = p.path;
      const lap = p.best_lap != null ? ` · ${p.best_lap.toFixed(2)}s` : "";
      o.textContent = `${star ? "★ " : ""}${p.name}${lap}`;
      return o;
    };
    const sortKey = (p) => [p.best_lap == null ? 1 : 0, p.best_lap ?? 0, p.name];
    const byKey = (a, b) => { const ka = sortKey(a), kb = sortKey(b);
      for (let i = 0; i < ka.length; i++) { if (ka[i] < kb[i]) return -1; if (ka[i] > kb[i]) return 1; } return 0; };

    const recommended = policies.filter((p) => p.recommended)
      .sort((a, b) => FAM_ORDER.indexOf(a.family) - FAM_ORDER.indexOf(b.family) || byKey(a, b));
    if (recommended.length) {
      const g = optgroup("★ recommended (start here)");
      for (const p of recommended) g.appendChild(optionFor(p, true));
      pol.appendChild(g);
    }
    const byFamily = new Map();
    for (const p of policies) (byFamily.get(p.family) ?? byFamily.set(p.family, []).get(p.family)).push(p);
    const fams = [...byFamily.keys()].sort((a, b) => FAM_ORDER.indexOf(a) - FAM_ORDER.indexOf(b));
    for (const fam of fams) {
      const g = optgroup(byFamily.get(fam)[0]?.family_label || fam);
      for (const p of byFamily.get(fam).sort(byKey)) g.appendChild(optionFor(p, p.recommended));
      pol.appendChild(g);
    }
    if (!policies.length) toast("No policies found under runs/*/ckpt_final.pt", true);
    else {
      pol.value = (recommended[0] || policies[0]).path;   // land on a known-good policy
      onPolicyPicked();             // populate meta + charts for the default selection
    }

    const crs = $("course");
    crs.innerHTML = "";
    const optgroup = (label) => { const g = document.createElement("optgroup"); g.label = label; return g; };
    const gPresets = optgroup("presets (random)");
    for (const c of courses.presets) {
      const o = document.createElement("option");
      o.value = c.name;
      o.textContent = `${c.name}  (r=${c.radius}m, hop ${c.step_min}-${c.step_max}m)`;
      gPresets.appendChild(o);
    }
    crs.appendChild(gPresets);
    if (courses.courses.length) {
      const gFiles = optgroup("seeded courses");
      for (const c of courses.courses) {
        const o = document.createElement("option");
        o.value = c.name;
        o.textContent = `${c.name}  (${c.num_gates} gates)`;
        gFiles.appendChild(o);
      }
      crs.appendChild(gFiles);
    }
    // Default to a seeded spread course if present, else the spread preset.
    crs.value = courses.courses[0]?.name || "preset:spread";
  } catch (err) {
    toast(`failed to load lists: ${err.message}`, true);
  }
}

// ---- run (rollout) ------------------------------------------------------------------
let running = false;
$("run").addEventListener("click", async () => {
  if (running) return;
  running = true;
  const btn = $("run");
  btn.disabled = true;
  $("status").innerHTML = `<span class="spin">⟳</span> running…`;
  try {
    const req = {
      policy: $("policy").value,
      course: $("course").value,
      drone_count: Number($("drones").value),
      n_gates: Number($("gates").value),
      dr: $("dr").checked,
    };
    if (!req.policy) throw new Error("pick a policy");
    const summary = await postRollout(req);
    const doc = await loadRunByPath(summary.run_path);
    showRun(doc, summary);
    const m = summary.metrics || {};
    const lap = m.best_lap_time != null ? `, best ${m.best_lap_time.toFixed(2)}s` : "";
    const laps = m.laps_per_drone != null ? `, ${m.laps_per_drone.toFixed(1)} laps/drone` : "";
    $("status").textContent = `${summary.task} · ${summary.drone_count} drones · ${summary.course}${lap}${laps}`;
  } catch (err) {
    $("status").textContent = "";
    toast(`rollout failed: ${err.message}`, true);
  } finally {
    running = false;
    btn.disabled = false;
  }
});

function showRun(doc, summary) {
  const meta = doc.meta || {};
  sceneInfo = meta.scene_info || {};
  $("title").textContent = `${summary.course} · ${meta.policy ?? ""}`;
  $("ndrones").textContent = String(summary.drone_count);
  const dt = Number(meta.dt) > 0 ? Number(meta.dt) : 1 / (Number(meta.control_hz) || 50);
  const ep = doc.episodes[0];
  playback.setEpisode(ep, dt);
  buildFpvFrames();              // one onboard box per drone in the freshly-loaded episode
  const n = playback.maxFrames;
  $("scrub").max = String(Math.max(0, n - 1));
  $("scrub").value = "0";
  $("fend").textContent = String(n);
  $("tend").textContent = (n * dt).toFixed(2);
  syncPlayBtn();
}

// ---- single animation loop ----------------------------------------------------------
let last = performance.now();
function loop(now) {
  requestAnimationFrame(loop);
  const delta = Math.min(0.1, (now - last) / 1000);
  last = now;
  playback.tick(delta);
  view.render();
  // Each FPV inset shows that drone's onboard view, hiding only its OWN body so it doesn't occlude
  // its camera; other drones stay visible so you see them around you.
  if (fpvOn) {
    for (const fr of fpvFrames) {
      const actor = playback.actors[fr.idx];
      if (!actor) continue;
      view.renderInset(actor.fpvCamera, insetRect(fr.body), { hide: [actor.glyph].filter(Boolean) });
    }
  }
  if (topOn && playback.actors.length) view.renderInset(playback.topCamera, insetRect($("topbody")));
}
requestAnimationFrame(loop);
addEventListener("resize", () => { view.resize(); if ($("chartfold").open) renderCharts(); });

view.resize();
loadSelectors();
