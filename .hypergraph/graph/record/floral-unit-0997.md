---
node_id: 238a7aa4-b0ad-54e7-b279-6d96479afe8e
slug: floral-unit-0997
title: 'Method: hover_tof — the measured ToF height enters the obs; the policy owns the altitude loop (task + deploy path + tests, commit d167886)'
created_at: '2026-07-13T13:02:55.164000+00:00'
parents:
- aged-firefly-8064
- broken-wildflower-8398
summary: 'hover_tof implemented (commit d167886): obs-6 [roll,pitch,p,q,r,height_err] x stack 8 puts the bridge VL53L1X''s measured height in the obs — sensor modeled deploy-exactly in-task (40 Hz ZOH, 1.3 m saturation hold, 45-deg tilt hold; noise sd 0.02 m / bias 0.03 m via per-channel DR, datasheet placeholders), config = flight-proven d50var_s8 + ONE factor. Deploy: task-keyed family, pilot feeds --target-height - tof*cosr*cosp last-valid-held, refuses takeoff without live ToF, tof_lost abort, external damper OFF; exact channel logged as CSV col 26 h_err for byte-exact sim_vs_real replay. 262 tests green (17 new) + fake-bridge system flight. Training run next.'
origin:
  backend: flywheel
  node_id: 238a7aa4-b0ad-54e7-b279-6d96479afe8e
  slug: floral-unit-0997
  revision: 1
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: bcff971b-b3da-5766-ae20-5880d00e924f
  slug: square-term-2705
  revision: 0
  pushed_at: '2026-08-09T21:28:03+00:00'
  content_sha256: 04a91b5572910e592833877bd90bbc329e628899c65bc5935ad58cbd8e3fa7c4
---
# hover_tof: closing the altitude loop with the first measured state channel

**Why (the lineage's open wound).** Every blind-hover flight's residual ceiling is open-loop altitude: the v2/R-ladder record refuted IMU-integrated vz (DC bias -0.6..-1.6 m/s), the RPM anchor only *damps*. The VL53L1X on the bridge (aged-firefly-8064, same day) finally measures height — this node wires it into the obs so PPO can own the vertical loop, exactly the "obs channel for a height-aware hover retrain" step queued in docs/SIM2REAL.md.

**What was built (commit `d167886`).**
- **Task `hover_tof`** (`tasks/hover_tof.py`): obs-6 `[roll, pitch, p, q, r, height_err]`, `height_err = setpoint_z − h_meas` (obs-v4 "target minus measurement" sign, + = climb). The sensor is modeled deploy-exactly *in-task*: true z when fresh+valid (~40 Hz ranging vs the 50 Hz loop → per-step Bernoulli 0.8 refresh), zero-order-held on staleness / >1.3 m slant saturation / >45° tilt; state advances once per step in `reward_and_done` (observe is a pure read — the hover_blind_v2 discipline). Ranging noise (sd 0.02 m) + mount bias (±0.03 m) ride the per-channel DR → `--no-dr` eval is the noise-free ablation for free. **Datasheet placeholders until a ToF-equipped flight calibrates them.**
- **Config `hover_tof_air65.yaml`** = the flight-proven ★ d50var_s8 recipe + ONE factor (the channel; setpoint band lowered into the sensor's 0.5–1.1 m valid band; spawns still overshoot 1.3 m for saturation-recovery exposure). Frame 6 × stack 8 = input 48.
- **New metric `mean_z_error`** across the whole hover family — the vertical-only story these obs ablations are about.
- **Deploy path** (`neural_whoop.pilot`): family is task-keyed off the export meta (`task: hover_tof`; a 6-dim file without it stays the vz family — no dim ambiguity). The pilot feeds `--target-height − tof·cosr·cosp` (flat-floor tilt correction: the ray leaves along body −z, so slant·cosθ IS z), last-valid-held; setup **refuses takeoff without a live ToF**; >1 s in-flight silence aborts (`tof_lost`); the external climb damper turns OFF (the policy owns altitude; RPM governor stays as the absolute thrust anchor). The exact fed channel is CSV col 26 `h_err` → `sim_vs_real.py` replays it byte-exactly (24/25-col logs still load).

**Verification.** 262 tests green (17 new: sensor ZOH/saturation/tilt-hold semantics, purity, family keying, setup gate, `tof_lost` abort, damper handoff, 26-col log). Fake-bridge system flight (`NW_FLIGHT_FAKE=1 pilot.py fly --takeoff --target-height 0.7`) walks WAITING→SEEK→RISE→HOVER→LAND→RELEASED with live `tof_m`/`h_err` in the log and `flight_metrics().height` present.

**Honesty.** (1) Height noise/bias DR magnitudes are datasheet-plausible, not measured — no ToF-equipped flight CSV exists yet; recalibrate from the first one. (2) The DR draws fresh noise on held steps where the real sensor freezes reading+noise together — hold windows are 1–2 steps at 40 vs 50 Hz, spectrum error small. (3) The sim seeds each episode's hold state with clamped spawn z ("last valid on the way here"); real flights track continuously from takeoff, where the sensor always ranges.

**Lineage.** Parents: aged-firefly-8064 (the MSP_BRIDGE_TOF seam this consumes), broken-wildflower-8398 (★ d50var_s8 — the recipe + deploy family it extends by one factor). Child: the `hover_tof_air65` 3.2B training run (launched).