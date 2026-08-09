---
node_id: 119c8500-9623-5bf3-98e2-b236b63b5faf
slug: shiny-mountain-6946
title: 'Hypothesis: honest per-channel IMU noise/bias DR + a deploy-matched vz_est channel + a steeper upright well let blind hover survive the REAL sensor floor (the hover_blind_air65_v2 three-way sweep)'
created_at: '2026-07-06T14:44:56.852187+00:00'
parents:
- still-bird-0492
- cold-night-8900
summary: 'Framing + predictions for the 2026-07-06 hover_blind_air65_v2 three-way sweep (flagship / _novz / _noiseonly, all 3.2B steps), forking from the hover_blind_air65_long baseline (cold-night-8900). The real-flight campaign (runs/pilot/flight_*.csv, docs/SIM2REAL.md) exposed three gaps the long baseline never trained against: (1) calm-hover gyro noise floor ~2.5 rad/s SD from frame vibration — a ~250× gap vs the scalar obs_noise_std 0.01 on the policy''s PRIMARY input; attitude ~0.02 rad, vz ~0.15 m/s scatter; (2) residual per-episode bias after floor-cal — ±0.035 rad roll/pitch, vz DC bias −0.6..−1.6 m/s every hover window; (3) altitude was open-loop trim with no velocity feedback, so the external acc-PI damper hit its ceiling fighting the RPM governor over a biased estimate. The sweep tests three levers: honest per-channel noise+bias DR (new randomization.py channels), a 6th obs channel vz_est mirroring pilot.py''s leaky acc-integrated climb-rate estimator exactly (τ 4 s, clamp ±2, freeze past 25° tilt), and a steeper upright well (σ 0.5→0.25) + halved smoothness penalty (0.004→0.002) + obs_stack 3 as the only noise filter. Predicted ablation decode: flagship vs _novz = value of the vz channel; _novz vs _noiseonly = value of the reward steepening; _noiseonly vs the long baseline cross-eval = value of noise-hardening alone. Prediction: the flagship holds attitude AND damps vertical under the measured noise floor where the long baseline (trained on unrealistic scalar noise, no velocity obs) degrades; vz gives the policy a closed-loop path to beat the open-loop ±thrust×±mass altitude limit that capped every constant-trim rescue. Untested prediction — results land after the 5090 runs.'
origin:
  backend: flywheel
  node_id: 119c8500-9623-5bf3-98e2-b236b63b5faf
  slug: shiny-mountain-6946
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 067ab6e5-c0e5-5790-bb03-0e7f51850d89
  slug: damp-salad-1523
  revision: 0
  pushed_at: '2026-08-09T21:27:20+00:00'
  content_sha256: b0e89f53d2a869340fc69e780c58abc4f586388249dbcfd9593d1c749634ab2c
---
# Hypothesis: does honest sensor-noise DR + a velocity channel + a steeper well make blind hover deployable under the REAL noise floor?

## Status: HYPOTHESIS (predictions set before the 5090 runs; results owed as three sibling experiment nodes)

## The gap this tests
The long baseline (**cold-night-8900**) solved the open-loop thrust *trim* (91% pure-hold 30 s survival no-DR) but was trained under a **scalar `obs_noise_std 0.01`** and with **no velocity feedback** — neither matches the real Air65 II first-flight telemetry. The pilot flight campaign (`runs/pilot/flight_*.csv`, tabulated in `docs/SIM2REAL.md`) measured three concrete sim gaps:

1. **Gyro noise floor ~±145 deg/s (~2.5 rad/s) SD** from frame vibration in calm hover — a ~**250×** gap vs the scalar 0.01 on the policy's *primary* input (the ±10–17° wobble it must control). Attitude channels ~0.02 rad; vz ~0.15 m/s per-step scatter.
2. **Residual per-episode bias after floor-cal:** ±2 deg (~0.035 rad) level bias on roll/pitch; a **vz DC bias of −0.6..−1.6 m/s in every hover window** (the estimator reads a persistent phantom sink).
3. **Altitude was open-loop.** The external acc-PI climb damper hit its ceiling fighting the RPM governor over that biased vz — so let the policy own vertical damping and learn what to trust about vz.

## The three levers (and what each sweep arm isolates)
- **Honest per-channel noise + bias DR** — new `randomization.py` channels: `obs_noise_std_channels` (per-channel SDs, overrides the scalar) and `obs_bias_channels` (per-episode uniform ±range constant bias, curriculum-scaled at draw like `thrust_scale`, applied per-frame pre-stacking so a bias is constant across stacked frames).
- **A deploy-matched velocity channel** — obs grows to `[roll, pitch, p, q, r, vz_est]` (`hover_blind_v2`), where `vz_est` mirrors `pilot.py`'s leaky acc-integrated climb-rate estimator **exactly** (τ 4 s, clamp ±2 m/s, freeze past 25° tilt), so what the policy trains on is byte-for-byte what the deployed estimator emits.
- **A steeper upright well + averaging path** — `upright_sigma 0.5→0.25` (the old shallow well commanded rates too small to measure over 2.5 rad/s noise — the real −3..−10° pitch equilibrium = 'drifts backwards'); `smoothness_penalty 0.004→0.002` (the delta-action penalty over honest noise taxes gain a memoryless MLP can't filter); `obs_stack 3` as the policy's only noise filter + latency-inference path (deploy still tiny, [64,64]). Also `action_latency_steps 3→5`, `thrust_scale_frac 0.05→0.12` (measured obs age p50 24 / p99 112 / max 209 ms; same-day hover-anchor spread ±15%).

## Predicted ablation decode (three sibling runs, all 3.2B steps, obs_stack 3)
- **flagship `hover_blind_air65_v2`** = vz channel + noise-hardening + reward steepening.
- **`_novz`** = noise-hardening + reward steepening, obs-5 (no vz).
- **`_noiseonly`** = noise-hardening only (baseline reward, obs-5).
- **flagship − _novz** → value of the **vz channel**; **_novz − _noiseonly** → value of the **reward steepening**; **_noiseonly vs cold-night-8900 cross-eval** → value of **noise-hardening alone**.

## Prediction
Under the measured noise floor + bias, the long baseline should degrade (attitude jitter it never trained to filter; no velocity feedback to catch the phantom-sink bias). The flagship should (a) hold attitude via `obs_stack 3` averaging + the steeper well and (b) **damp vertical closed-loop via vz_est**, giving it a path to beat the open-loop ±thrust×±mass altitude ceiling that capped every constant-trim rescue in still-bird-0492. If vz adds nothing (flagship ≈ _novz), the phantom-sink bias is too adversarial for the leaky estimator and the honest answer is 'IMU-only vertical needs the flow deck'. Testable, and recorded either way.

## Lineage
Forks from **cold-night-8900** (the trim-fixed 3.2B baseline this cross-evals against) and responds to **still-bird-0492** (the trim-discovery node: its 'precise trim by expectation' was refuted as deterministically deployed, and its open-loop-altitude-can't-beat-DR limit is exactly what the vz channel attacks). Executes the branch-B no-flow-deck first-flight thread of the sim2real plan **bitter-fire-0679**. Children: the three sweep experiment nodes (flagship / _novz / _noiseonly), owed after the 5090 runs.