// Thin fetch wrappers around the Studio FastAPI backend (src/neural_whoop/studio/server.py).
// All return parsed JSON; throw on non-2xx with the server's detail message when present.

async function jsonOrThrow(res) {
  if (res.ok) return res.json();
  let detail = `${res.status} ${res.statusText}`;
  try {
    const body = await res.json();
    if (body && body.detail) detail = typeof body.detail === "string"
      ? body.detail : JSON.stringify(body.detail);
  } catch { /* non-JSON error body */ }
  throw new Error(detail);
}

export const getPolicies = () => fetch("/api/policies").then(jsonOrThrow);
export const getCourses = () => fetch("/api/courses").then(jsonOrThrow);

// Training scalars (TensorBoard curves) for a run dir name -> { run, tags: {tag: {steps, values}} }.
export const getScalars = (run) =>
  fetch(`/api/policies/${encodeURIComponent(run)}/scalars`).then(jsonOrThrow);

export const postRollout = (req) =>
  fetch("/api/rollout", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  }).then(jsonOrThrow);

// ---- course editor -----------------------------------------------------------------
// Load one saved course (curated or authored _web/) as { name, gates } for editing.
export const getCourse = (name) =>
  fetch(`/api/courses/${encodeURIComponent(name)}`).then(jsonOrThrow);

// `preset` (optional) selects the arena bounds to validate against — the same arena the editor
// draws — so a gate inside the drawn circle isn't flagged against the default tight radius.
export const validateCourse = (course, preset) =>
  fetch(`/api/courses/validate${preset ? `?preset=${encodeURIComponent(preset)}` : ""}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(course),
  }).then(jsonOrThrow);

export const saveCourse = (course, preset) =>
  fetch(`/api/courses${preset ? `?preset=${encodeURIComponent(preset)}` : ""}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(course),
  }).then(jsonOrThrow);

// ---- hero MP4 export (server-side nw-viz capture) ----------------------------------
// Render a loaded replay to a hero MP4; resolves to { video_path } (a runs-relative mp4 path).
export const exportVideo = (run_path, opts = {}) =>
  fetch("/api/export", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_path, ...opts }),
  }).then(jsonOrThrow);

// The raw replay file path is served under /api/runs/{path} (gzip raw).
export const runFileUrl = (path) => `/api/runs/${path}`;
