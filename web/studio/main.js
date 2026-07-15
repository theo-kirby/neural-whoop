// Studio app shell: two tabs. SIMULATION (pick policy + course + drone count, fly a fixed-course
// rollout on the GPU, watch the v2 replay in a hero-layout viewport that matches the exported MP4;
// an ✎ Edit-course toggle overlays the gate editor on the same scene) and REAL (the always-on
// bench dashboard flying the actual drone, with a calibration mode). The sim viewport composites a
// wide main shot with three fixed left cells — FPV (top), top-down (middle), stats HUD (bottom) —
// via scissor passes, then exports the byte-identical hero MP4 server-side through nw-viz capture.
// A draggable divider between the scene and the sidebar resizes both (persisted).

import { createScene } from "./scene.js";
import { createEnvironment } from "./environment.js";
import { Playback } from "./playback.js";
import { createEditor } from "./editor.js";
import { createBench } from "./bench.js";
import { courseBounds } from "./cameras.js";
import { layoutInsets, layoutInsetsCss } from "./layout.js";
import { getPolicies, getCourses, getScalars, postRollout, exportVideo, runFileUrl } from "./api.js";
import { loadRunByPath } from "./run-loader.js";

const $ = (h) => document.querySelector(`[data-h="${h}"]`);
const MAX_FPV = 6;                  // cap on FPV sub-cells in the grid (busy swarms get a "+N more")
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

// ---- theme (light / dark) -----------------------------------------------------------
// Single source of truth: documentElement.dataset.theme, persisted in localStorage["nw_theme"].
// Applied to the DOM early (before the first render) so there's no flash; the 3D scenes are synced
// once their environments exist (applyTheme, below). Default = light.
const THEME_KEY = "nw_theme";
let theme = localStorage.getItem(THEME_KEY) === "dark" ? "dark" : "light";
document.documentElement.dataset.theme = theme;

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
// grid:false — the greybox room (sized per course on run/edit) replaces the flat 160 m grid+ground.
const view = createScene(document.querySelector(".view3d"), { grid: false });
const simEnv = createEnvironment(view);
const playback = new Playback(view);
let activeTab = "sim";              // "sim" | "real"
let simMode = "play";               // Simulation sub-mode: "play" (default) | "edit" (course editor)
let fpvOn = true, topOn = true;     // FPV + top-down hero cells shown by default
let sceneInfo = {};                 // meta.scene_info of the loaded run (command labels, standoff…)
let currentRunPath = null;          // run_path of the loaded replay (the export target)
const policiesByPath = new Map();   // path -> policy meta (for the details panel + scalars run name)

const heroFpvEl = document.getElementById("hero-fpv");
const heroTopEl = document.getElementById("hero-top");
const heroStatsEl = document.getElementById("hero-stats");

// ---- hero compositor ----------------------------------------------------------------
// Position a DOM overlay box from a top-origin CSS rect ({left, top, w, h}).
function placeBox(el, r) {
  el.style.left = `${r.left}px`; el.style.top = `${r.top}px`;
  el.style.width = `${r.w}px`; el.style.height = `${r.h}px`;
}

// The actors shown in the FPV cell: hero first, then the rest, capped at MAX_FPV.
function shownActors() {
  const acts = playback.actors;
  if (!acts.length) return [];
  const hero = acts[playback.heroIdx];
  const rest = acts.filter((_, i) => i !== playback.heroIdx);
  return [hero, ...rest].slice(0, MAX_FPV).filter(Boolean);
}

// Render the wide main shot full-canvas, then the FPV + top-down hero cells via scissor passes, and
// track the DOM overlay boxes to the same layout rects.
function compositeHero() {
  view.render();
  const W = view.mount.clientWidth || 1, H = view.mount.clientHeight || 1;
  const insets = layoutInsets(W, H);      // bottom-origin (WebGL viewports)
  const css = layoutInsetsCss(W, H);      // top-origin (DOM boxes)
  placeBox(heroFpvEl, css.fpv);
  placeBox(heroTopEl, css.top);
  placeBox(heroStatsEl, css.stats);

  if (fpvOn) {
    const shown = shownActors();
    if (shown.length === 1) {
      const a = shown[0];
      view.renderInset(a.fpvCamera, insets.fpv, { hide: [a.glyph].filter(Boolean) });
    } else if (shown.length > 1) {
      // Subdivide the FPV cell into a near-square grid (top row first, matching reading order).
      const n = shown.length, cols = Math.ceil(Math.sqrt(n)), rows = Math.ceil(n / cols);
      const cw = insets.fpv.w / cols, ch = insets.fpv.h / rows;
      shown.forEach((a, k) => {
        const col = k % cols, row = Math.floor(k / cols);
        const rect = { x: insets.fpv.x + col * cw, y: insets.fpv.y + (rows - 1 - row) * ch, w: cw, h: ch };
        view.renderInset(a.fpvCamera, rect, { hide: [a.glyph].filter(Boolean) });
      });
    }
    const extra = playback.actors.length - shown.length;
    $("fpvcap").textContent = extra > 0 ? `+${extra} more` : "";
  }
  if (topOn && playback.actors.length) view.renderInset(playback.topCamera, insets.top);
}

// Show/hide the hero boxes per the FPV/top toggles + active tab/mode (play mode only).
function syncHeroBoxes() {
  const player = activeTab === "sim" && simMode === "play";
  heroStatsEl.classList.toggle("hidden", !player);
  heroFpvEl.classList.toggle("hidden", !player || !fpvOn);
  heroTopEl.classList.toggle("hidden", !player || !topOn);
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
  const tsec = (i * playback.dt).toFixed(2);
  $("tcur").textContent = tsec;
  $("htime").textContent = tsec;            // hero stats HUD time
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
$("fpv").addEventListener("change", (e) => { fpvOn = e.target.checked; syncHeroBoxes(); });
$("top").addEventListener("change", (e) => { topOn = e.target.checked; syncHeroBoxes(); });
$("trail").addEventListener("change", (e) => playback.setTrailVisible(e.target.checked));

// ---- hero MP4 export (server-side nw-viz capture) -----------------------------------
$("export").addEventListener("click", async () => {
  if (!currentRunPath) return;
  const btn = $("export");
  btn.disabled = true;
  btn.innerHTML = `<span class="spin">⟳</span> exporting…`;
  try {
    const { video_path } = await exportVideo(currentRunPath, { width: 1280, height: 720 });
    const a = document.createElement("a");
    a.href = runFileUrl(video_path);
    a.download = video_path.split("/").pop();
    document.body.appendChild(a); a.click(); a.remove();
    toast(`hero MP4 ready — downloading ${a.download}`);
  } catch (err) {
    toast(`export failed: ${err.message}`, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "⤓ Export hero MP4";
  }
});

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
  // Baseline + line — strokes read from the CSS theme vars so charts repaint per theme.
  ctx.strokeStyle = cssVar("--line") || "#3a3a3a"; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(pad, h - pad); ctx.lineTo(w - pad, h - pad); ctx.stroke();
  ctx.strokeStyle = cssVar("--fg") || "#e0e0e0"; ctx.lineWidth = 1.5; ctx.lineJoin = "round";
  ctx.beginPath();
  steps.forEach((s, i) => { const X = px(s), Y = py(values[i]); i ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y); });
  ctx.stroke();
  // Endpoint dot.
  ctx.fillStyle = cssVar("--on") || "#f4f4f4";
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

    populateCourses(courses);
  } catch (err) {
    toast(`failed to load lists: ${err.message}`, true);
  }
}

// (Re)build the course dropdown: random presets, then seeded courses, then browser-authored ones.
// `preserve` keeps the current selection if it still exists (used after the editor saves a course).
function populateCourses(courses, preserve) {
  const crs = $("course");
  const optgroup = (label) => { const g = document.createElement("optgroup"); g.label = label; return g; };
  const prev = preserve ? crs.value : null;
  crs.innerHTML = "";
  const gPresets = optgroup("presets (random)");
  for (const c of courses.presets) {
    const o = document.createElement("option");
    o.value = c.name;
    o.textContent = `${c.name}  (r=${c.radius}m, hop ${c.step_min}-${c.step_max}m)`;
    gPresets.appendChild(o);
  }
  crs.appendChild(gPresets);
  const addGroup = (label, list) => {
    if (!list.length) return;
    const g = optgroup(label);
    for (const c of list) {
      const o = document.createElement("option");
      o.value = c.name;
      o.textContent = `${c.name}  (${c.num_gates} gates)`;
      g.appendChild(o);
    }
    crs.appendChild(g);
  };
  addGroup("seeded courses", courses.courses.filter((c) => c.kind !== "web"));
  addGroup("your courses (editor)", courses.courses.filter((c) => c.kind === "web"));
  // Keep the prior selection if it survived the refresh, else default to a seeded course / spread.
  const seeded = courses.courses.find((c) => c.kind !== "web");
  crs.value = (prev && [...crs.options].some((o) => o.value === prev)) ? prev
    : (seeded?.name || courses.courses[0]?.name || "preset:spread");
}

// Refresh just the course dropdown (after the editor saves), preserving the current pick.
async function refreshCourses() {
  try { populateCourses(await getCourses(), true); }
  catch (err) { toast(`couldn't refresh courses: ${err.message}`, true); }
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
  setSimMode("play");                    // a fresh replay always lands in the player view
  const meta = doc.meta || {};
  sceneInfo = meta.scene_info || {};
  $("title").textContent = `${summary.course} · ${meta.policy ?? ""}`;
  $("ndrones").textContent = String(summary.drone_count);
  const dt = Number(meta.dt) > 0 ? Number(meta.dt) : 1 / (Number(meta.control_hz) || 50);
  const ep = doc.episodes[0];
  playback.setEpisode(ep, dt);
  // Size the greybox room to the course (footprint from all gates + flown paths, capped height so
  // big spread courses don't get an absurd ceiling); centred at the origin like the arena.
  const b = courseBounds(view.world, playback.actors.map((a) => a.frames), ep.gates || []);
  if (b) {
    const footprint = b.footprint + 4;   // ~2 m breathing room each side
    simEnv.setSize({ footprint, height: clamp(b.zMax + 1.5, 4, footprint), floorZ: 0 });
  }
  const n = playback.maxFrames;
  $("scrub").max = String(Math.max(0, n - 1));
  $("scrub").value = "0";
  $("fend").textContent = String(n);
  $("tend").textContent = (n * dt).toFixed(2);
  $("fpvcap").textContent = "";
  currentRunPath = summary.run_path;     // the export target
  $("export").disabled = false;
  syncHeroBoxes();
  syncPlayBtn();
}

// ---- course editor (edit mode of the Simulation tab) ---------------------------------
// Shares the player's `view` — its gizmo/gates/ring live in one group that setSimMode toggles.
const editor = createEditor({
  view,
  panel: document.getElementById("sim-controls"),
  toast,
  onSaved: refreshCourses,               // refresh the course picker after a save
  onFly: (stem) => {
    setSimMode("play");
    $("course").value = stem;            // option value == saved stem; refreshCourses ran first
    $("run").click();
  },
  // Size the greybox room to the arena preset while editing (the flat arena ring stays as an
  // in-room floor marker). Guarded to edit mode so the editor's async preset-init can't shrink a
  // course-sized room in play mode.
  onArena: (radius) => {
    if (simMode !== "edit") return;
    const footprint = 2 * radius + 2;
    simEnv.setSize({ footprint, height: clamp(2 * radius, 4, footprint), floorZ: 0 });
  },
});

// ---- real tab (always-on bench drone) -------------------------------------------------
const bench = createBench({
  mount: document.querySelector(".view3d-bench"),
  panel: document.getElementById("bench-controls"),
  toast,
  getPolicies,
});

// ---- theme toggle ---------------------------------------------------------------------
// Themes both 3D scenes (simEnv + benchEnv) and the DOM sidebar (via data-theme) together, and
// repaints the themed canvases (training charts follow the CSS stroke vars; the Real trends repaint
// on their next frame). The button glyph shows the theme you'd switch TO.
function applyTheme(t) {
  theme = t === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = theme;
  localStorage.setItem(THEME_KEY, theme);
  simEnv.setTheme(theme);
  bench.setTheme(theme);
  const btn = $("theme");
  if (btn) btn.textContent = theme === "light" ? "☾" : "☀";
  renderCharts();
}
$("theme").addEventListener("click", () => applyTheme(theme === "light" ? "dark" : "light"));

// ---- Simulation play/edit mode --------------------------------------------------------
function setSimMode(mode) {
  simMode = mode;
  const edit = mode === "edit";
  for (const el of document.querySelectorAll("#sim-controls .edit-only")) el.classList.toggle("hidden", !edit);
  for (const el of document.querySelectorAll("#sim-controls .play-only")) el.classList.toggle("hidden", edit);
  $("editmode").textContent = edit ? "✓ Done editing" : "✎ Edit course";
  editor.setActive(edit);
  syncHeroBoxes();
  // Back to play with a replay loaded: restore the hero framing the edit orbiting disturbed.
  if (!edit && playback.episode) playback.frameToCamera();
}
$("editmode").addEventListener("click", () => setSimMode(simMode === "edit" ? "play" : "edit"));

// ---- tab routing ----------------------------------------------------------------------
const bench_mount = () => document.querySelector(".view3d-bench");
function switchTab(name) {
  activeTab = name;
  for (const b of document.querySelectorAll(".tabbar .tab")) b.classList.toggle("active", b.dataset.tab === name);
  document.getElementById("sim-controls").classList.toggle("hidden", name !== "sim");
  document.getElementById("bench-controls").classList.toggle("hidden", name !== "real");
  view.mount.classList.toggle("hidden", name !== "sim");
  bench_mount().classList.toggle("hidden", name !== "real");
  syncHeroBoxes();
  if (name === "sim") view.resize();
  else bench.onShow();
}
for (const b of document.querySelectorAll(".tabbar .tab")) {
  b.addEventListener("click", () => switchTab(b.dataset.tab));
}

// ---- draggable sidebar divider --------------------------------------------------------
// The sidebar width is a CSS var; dragging the divider resizes both panels and persists the width.
const SIDEBAR_MIN = 280, SIDEBAR_MAX = 640;
const dividerEl = document.getElementById("divider");
function setSidebarWidth(px) {
  document.documentElement.style.setProperty("--sidebar-w", `${px}px`);
}
{
  const saved = Number(localStorage.getItem("nw_sidebar_w"));
  if (saved >= SIDEBAR_MIN && saved <= SIDEBAR_MAX) setSidebarWidth(saved);
}
function onLayoutChange() {
  if (activeTab === "sim") view.resize();
  else bench.resize();
  syncHeroBoxes();
  if ($("chartfold").open) renderCharts();
}
let dividerW = null;                     // px while dragging, else null
dividerEl.addEventListener("pointerdown", (e) => {
  dividerEl.setPointerCapture(e.pointerId);
  dividerEl.classList.add("dragging");
  dividerW = Number(getComputedStyle(document.getElementById("sidebar")).width.replace("px", ""));
});
dividerEl.addEventListener("pointermove", (e) => {
  if (dividerW === null) return;
  dividerW = Math.max(SIDEBAR_MIN, Math.min(SIDEBAR_MAX, Math.round(innerWidth - e.clientX)));
  setSidebarWidth(dividerW);
  onLayoutChange();
});
const endDrag = () => {
  if (dividerW === null) return;
  localStorage.setItem("nw_sidebar_w", String(dividerW));
  dividerW = null;
  dividerEl.classList.remove("dragging");
  onLayoutChange();
};
dividerEl.addEventListener("pointerup", endDrag);
dividerEl.addEventListener("pointercancel", endDrag);

// ---- single animation loop ------------------------------------------------------------
let last = performance.now();
function loop(now) {
  requestAnimationFrame(loop);
  const delta = Math.min(0.1, (now - last) / 1000);
  last = now;
  if (activeTab === "real") { bench.tick(delta); return; }
  if (simMode === "edit") { view.render(); return; }   // edit mode: plain wide render, no insets
  playback.tick(delta);
  compositeHero();
}
requestAnimationFrame(loop);
addEventListener("resize", onLayoutChange);

view.resize();
syncHeroBoxes();
applyTheme(theme);          // sync both 3D scenes + the toggle glyph to the persisted theme
loadSelectors();
