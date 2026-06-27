// Studio app shell: populate the policy/course selectors, run a fixed-course rollout on Fly,
// load the returned v2 replay, and play it back (3D wide + FPV/top-down PiP, play/pause/scrub).
// Single-file app — the Editor/Metrics tabs from the lab are deferred (see the plan).

import { createScene } from "./scene.js";
import { Playback } from "./playback.js";
import { getPolicies, getCourses, postRollout } from "./api.js";
import { loadRunByPath } from "./run-loader.js";

const $ = (h) => document.querySelector(`[data-h="${h}"]`);

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
let fpvOn = true, topOn = true;   // FPV + top-down insets shown by default

function insetRect(frame) {
  const cr = view.renderer.domElement.getBoundingClientRect();
  const br = frame.getBoundingClientRect();
  return { x: br.left - cr.left, y: cr.height - (br.top - cr.top + br.height), w: br.width, h: br.height };
}

// ---- transport wiring ---------------------------------------------------------------
function syncPlayBtn() { $("play").textContent = playback.playing ? "⏸ Pause" : "▶ Play"; }
playback.onStateChange = () => { syncPlayBtn(); $("scrub").value = String(Math.floor(playback.idx)); };
playback.onFrame = (f, i) => {
  const spd = Math.hypot(f.vel[0], f.vel[1], f.vel[2]);
  $("step").textContent = String(f.step);
  $("gate").textContent = `${f.gate_idx}/${(playback.episode?.gates || []).length}`;
  $("spd").textContent = `${spd.toFixed(2)} m/s`;
  $("reward").textContent = f.cum_reward.toFixed(1);
  $("tcur").textContent = (i * playback.dt).toFixed(2);
  $("fcur").textContent = String(i + 1);
  $("scrub").value = String(i);
};

$("play").addEventListener("click", () => playback.setPlaying(!playback.playing));
$("scrub").addEventListener("input", (e) => playback.seek(Number(e.target.value)));
$("speed").addEventListener("change", (e) => { playback.speed = Number(e.target.value); });
$("follow").addEventListener("change", (e) => { playback.follow = e.target.checked; });
$("fpv").addEventListener("change", (e) => { fpvOn = e.target.checked; $("fpvframe").classList.toggle("hidden", !fpvOn); });
$("top").addEventListener("change", (e) => { topOn = e.target.checked; $("topframe").classList.toggle("hidden", !topOn); });
$("trail").addEventListener("change", (e) => playback.setTrailVisible(e.target.checked));

// ---- selectors ----------------------------------------------------------------------
async function loadSelectors() {
  try {
    const [policies, courses] = await Promise.all([getPolicies(), getCourses()]);
    const pol = $("policy");
    pol.innerHTML = "";
    for (const p of policies) {
      const o = document.createElement("option");
      o.value = p.path;
      const lap = p.best_lap != null ? ` · ${p.best_lap.toFixed(2)}s` : "";
      o.textContent = `${p.name} [${p.task}]${lap}`;
      pol.appendChild(o);
    }
    if (!policies.length) toast("No policies found under runs/*/ckpt_final.pt", true);

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
    const lap = m.best_lap_time != null ? `, best lap ${m.best_lap_time.toFixed(2)}s` : "";
    $("status").textContent = `${summary.task} · ${summary.drone_count} drones · ${summary.course}${lap}`;
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
  $("title").textContent = `${summary.course} · ${meta.policy ?? ""}`;
  $("ndrones").textContent = String(summary.drone_count);
  const dt = Number(meta.dt) > 0 ? Number(meta.dt) : 1 / (Number(meta.control_hz) || 50);
  const ep = doc.episodes[0];
  playback.setEpisode(ep, dt);
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
  // FPV hides only the hero's own body (so it doesn't occlude its camera); other drones stay
  // visible so you see them around you in the onboard view.
  if (fpvOn) view.renderInset(playback.fpvCamera, insetRect($("fpvframe")),
    { hide: [playback.actors[playback.heroIdx]?.glyph].filter(Boolean) });
  if (topOn) view.renderInset(playback.topCamera, insetRect($("topframe")));
}
requestAnimationFrame(loop);
addEventListener("resize", () => view.resize());

view.resize();
loadSelectors();
