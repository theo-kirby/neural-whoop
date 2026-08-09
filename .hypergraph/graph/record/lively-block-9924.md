---
node_id: eeaa9fca-d883-5e9a-b838-b3d17aa8e711
slug: lively-block-9924
title: 'Method: pilot acro-flip harness — system take-off→flip→land, flown blind (obs-parity + bounded FLIP window + suspended crash detector)'
created_at: '2026-07-12T14:45:26.435000+00:00'
parents:
- cold-leaf-0762
- shiny-violet-1747
- billowing-paper-5404
summary: 'The deploy half of the blind-acro idea (billowing-paper-5404): wires the trained roll+pitch acro policies into the offboard pilot so a real Air65 II does take-off→flip→land, IMU-only. System-level split — the pilot''s 3·2·1→RISE→HOVER→LAND state machine owns takeoff/land; a learned acro policy owns a bounded FLIP window inserted at HOVER. Two make-or-break pieces: (1) obs_from_msp_acro rebuilds gravity_body byte-parity with the sim (<1e-6 over a roll/pitch/yaw grid) so the policy sees its training obs; (2) the crash detector + RPM governor + climb damper are suspended ONLY inside the acro_flip_max_s window (a real flip legitimately passes |roll|>110°) and re-arm the instant it closes. Verified end-to-end on the in-process fake bridge: WAITING→COUNTDOWN→SEEK→RISE→HOVER→FLIP→HOVER→LAND→RELEASED, rotation_remaining 1→0, zero crash-abort through the inversion. 238 pytest green. Real-drone flip is NOT validated (hardware-gated).'
origin:
  backend: flywheel
  node_id: eeaa9fca-d883-5e9a-b838-b3d17aa8e711
  slug: lively-block-9924
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
---
# Method: the pilot acro-flip harness — blind take-off → flip → land

**What & why.** This is the **deploy half** of the blind-acro idea (`billowing-paper-5404`): now that both acro axes are trained GREEN (roll `shiny-violet-1747`, pitch `cold-leaf-0762`), wire them into the offboard pilot so a real Air65 II performs **take-off → flip → land, flown blind** (IMU-only; the only onboard companion is the XIAO ESP32 — no altitude/position/camera). ROADMAP #7, closes it.

**System-level design (the locked choice).** The learned policy owns *only the flip*; the pilot's existing `3·2·1 → RISE → HOVER → LAND` state machine owns take-off and landing. So “take off, flip, land” = pilot(open-loop takeoff/land) + policy(learned flip), for both axes. The base flight keeps flying the **hover** policy; a **second, acro** policy drives a bounded **FLIP** window inserted at HOVER.

**Setup (the harness).**
- **Deploy obs** (`pilot/policy.py::obs_from_msp_acro`, obs-7 `[gravity_body(3), p, q, r, rotation_remaining]`). `gravity_body` = `world_to_body([0,0,-1], R) = -R[2,:]`, a pure-stdlib port of the sim's `euler_to_quaternion` + `quaternion_to_matrix`. `check_policy_family_acro` gates the 7-dim family.
- **FLIP phase + maneuver clock** (`pilot/controller.py`). `request_flip()` (Bench **Flip** button / `fly --flip-at` / auto `flip_at_s`) is gated to HOVER + fresh link + near-level; a maneuver clock integrates the axis gyro toward Φ=2π·n (`rotation_remaining` 1→0, mirrors `tasks/acro_flip.py`); the acro policy drives the rates; FLIP exits → HOVER on rotation-complete + re-level or the hard `acro_flip_max_s` backstop.
- **Safety-critical suspension:** the crash detector (`|roll|>110°` is legitimate mid-flip), the RPM governor, and the climb damper are suspended **only inside the window** and re-arm the instant it closes.
- **Wiring:** `pilot.py fly --acro-weights/--flip-at/--axis/--n-rotations` + a fake-bridge path; Studio `FlightManager` loads an optional acro policy and handles `{type:"flip"}`; `serve.py --flight-acro-weights` (default `runs/acro_flip`); Bench UI **Flip** button + rotation chip. Fake bridge now echoes commanded rate→gyro + integrated attitude so a fake FLIP truly rolls through Φ.

**Results.**
- **obs parity** (`tests/test_pilot_acro_obs.py`): `gravity_body` max |Δ| vs the sim `world_to_body([0,0,-1], R)` **< 1e-6** across a roll/pitch/yaw grid (the yaw sweep also proves yaw-invariance). This is the make-or-break gate.
- **Fake-bridge system integration** (deterministic 50 Hz): phase sequence **WAITING→COUNTDOWN→SEEK→RISE→HOVER→FLIP→HOVER→LAND** (→RELEASED), **rotation_remaining swept 1→0.0**, **crash_aborted = None** — the roll crosses ±110° inside the FLIP band (detector suspended) then re-levels. See the phase-trace artifact.
- **238 pytest green**, incl. new FLIP-sequence + bounded-window-exit + parity tests.

**Verdict / Honesty.** Method shipped + fake-bridge-verified. **The real-drone flip is NOT validated here — hardware-gated.** Only sim training (parents) + fake-bridge integration. Honest risks: (1) **crash-detector suspension is safety-critical** — it must re-arm the instant the window ends; the bounded `acro_flip_max_s` + re-level exit guarantee a *failed* flip that tumbles still cuts (a dedicated test asserts this). (2) **gravity_body parity is make-or-break**; the <1e-6 test is the gate. (3) The blind flip's altitude is **open-loop through the inversion** (vz freezes >25° tilt); sub-second so drift is bounded, but a real flight must keep generous ceiling headroom.

**Lineage.** Parents: **cold-leaf-0762** (pitch acro) + **shiny-violet-1747** (roll acro) — the two policies this harness flies; and **billowing-paper-5404** — the idea whose deploy half this realizes (the training half was the two acro nodes). Commits 50eb052 (obs+parity) → cd258a2 (controller FLIP) → 539f236 (studio+CLI) → bae0ca6 (docs). Stays in **cluster:agility** (the deploy tooling for the acro workstream).