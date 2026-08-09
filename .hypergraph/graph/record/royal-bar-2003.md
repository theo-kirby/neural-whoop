---
node_id: 7daf0c16-837f-5483-8c7f-493221f98b86
slug: royal-bar-2003
title: 'd50var_s8 first flight: ~9 s near-perfect hover + POLICY EXONERATED — ceiling crash was a vz-estimator harness bug (Air65 II, 2026-07-07)'
created_at: '2026-07-07T11:09:07.030041+00:00'
parents:
- broken-wildflower-8398
- fancy-smoke-0094
summary: 'First real flight of d50var_s8 (the ★ studio-baseline, cleared by the parent bench check fancy-smoke-0094): ~9 s of near-perfect hover — stable-window median tilt 1.28° (p90 1.67°), policy a_thr pinned at −0.50 = textbook hover — then a ceiling contact and tumble at ~10 s. Root-caused from the one surviving log: the policy is EXONERATED (offline sim-vs-real action MAE 2.7e-5, at the log''s 1e-4 rounding floor); the crash was a deploy-harness bug — the pilot''s accel-integrated vz_est drifted and railed at its −2.0 m/s clamp by t=8.24 s while the drone sat at ~1° tilt, so the pilot''s own altitude damper piled on thrust (us_thr +203 µs while a_thr IQR 0.015) → climb → ceiling → tumble. Ships the flight-log measurement infra (analysis/flight_log + flight_report.py + sim_vs_real.py + real-flight replay) so no flight is lost again (a fixed --log stem was overwriting: the multi-battery flights were clobbered). Byproduct — props-on gyro sd 0.84/0.70/0.03 rad/s, lag-1 ρ ~0.70 (corroborates the colored-noise seam). Link p99 122 ms, 32% past the 40 ms cliff (pilot single-poll coupling, not the bridge). Verdict: GREEN — hover solved, policy faithful; deferred immediate follow-on is the RPM-anchor vz fix. Commit 636ad9b.'
origin:
  backend: flywheel
  node_id: 7daf0c16-837f-5483-8c7f-493221f98b86
  slug: royal-bar-2003
  revision: 4
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 34cf6085-9735-5e5d-a644-29ca7ef63163
  slug: rough-sound-3134
  revision: 0
  pushed_at: '2026-08-09T21:27:48+00:00'
  content_sha256: 1c163def9d9e24e2b9342ac1234fd01b82d576586a53d5207963403e68ec5961
---
# d50var_s8 first flight — hover solved, policy exonerated, crash was the harness

**Hypothesis.** The bench check (parent `fancy-smoke-0094`) cleared `d50var_s8` (`broken-wildflower-8398`, ★ studio-baseline) for a calm-air first flight. Test: does the amplitude-DR + obs_stack-8 blind-hover policy actually hold a stable hover on the real Air65 II, and if it departs, is the cause the policy or the deploy harness?

## Setup
- Hardware: Air65 II (BTFL 26.6.0) + XIAO ESP32-S3 WiFi bridge; offboard `scripts/pilot.py fly --takeoff --yaw center`, ~42 Hz effective control, calm indoor air, throttle ceiling + thumb on the override.
- Policy: `runs/hover_blind_air65_d50var_s8/policy_weights.json` (obs-5 × stack 8 → 40, [64,64], act-v2; no vz channel).
- Data: one surviving flight `runs/pilot/d50var_s8_f1.csv` (772 frames, 15.7 s, pack 4.07→3.92 V). **The other multi-battery flights were clobbered** by `pilot.py` opening a fixed `--log` in `"w"` mode — fixed this block (unique-path rollover + printed path).
- Analysis: the new pure `neural_whoop.analysis.flight_log` + `scripts/flight_report.py` pack, and the pure-`python3` `scripts/sim_vs_real.py` offline action diff.

## Results (vs the parent bench clearance)
- **~9 s of near-perfect hover.** Longest contiguous stable window 5.18 s at **median tilt 1.28°** (p90 1.67°); the policy's `a_thr` sat pinned at **−0.50** (textbook hover) throughout. Best real result yet — the bench-confirmed trim held in the air.
- **Policy EXONERATED (the headline).** `sim_vs_real.py` re-ran the exported policy on the logged obs: per-channel action **MAE ~2.7e-5** (worst 2.2e-4, at the log's 1e-4 rounding floor). The in-flight commands are exactly what the policy outputs — no harness corruption between `policy()` and the wire.
- **The crash was a deploy-harness bug — the vz estimator, not the policy.** The pilot's accel-integrated `vz_est` drifted and **railed at its −2.0 m/s clamp by t=8.24 s while the drone was level at ~1° tilt** (pure estimator drift, 48 railed frames). Because this 5-dim policy doesn't consume `vz`, the pilot's own altitude damper responded to the phantom sink by piling on thrust: **`us_thr` climbed +203 µs across the hover window while `a_thr` never moved (IQR 0.015)** → climb → ceiling contact ~10.2 s → tumble. `flight_telemetry.png` shows the divergence and the rail line landing exactly at the hover’s end.
- **Link tail is the pilot, not the bridge.** obs_age p50 24 / p99 **122 ms**, **32% past the 40 ms cliff** — but the bench-measured bridge RTT p99 is ~24 ms, so the tail is the pilot's 50 Hz single-poll-per-tick coupling (deferred: decouple obs polling from the command tick).
- **Open honesty item CLOSED — props-on gyro amplitude/ρ** (over the 5.18 s stable-hover window, filtered obs-level): **sd(p)=0.84, sd(q)=0.70, sd(r)=0.03 rad/s** (48/40/1.7 °/s), **lag-1 ρ ≈ 0.70/0.70/0.64**. The loaded, level in-hover amplitude at the policy input is ~3× below the raw 2.5 rad/s vibration floor the DR band was built around, and ρ≈0.70 empirically corroborates the colored-noise (AR(1)) seam — the parent bench node only had the *motors-off* floor (sd~0.007).
- **Battery:** 4.07 V → 3.92 V (0.15 V sag), hover-window mean 4.00 V — no sag-driven quality drop over the stable window.

## Verdict / honesty
**GREEN — the hover is solved and the policy is faithful in-flight.** This overturns the residual worry from the campaign close: at the calm-air operating point the blind policy hovers to ~1.3°. The departure was NOT a policy or noise-robustness failure — it was a single, cleanly-attributed, fixable deploy-harness bug (the accel-integrated vz rail). Honesty: (1) only one flight survived (the overwrite bug ate the rest — now fixed); (2) it *did* end in a ceiling crash, so this is not a clean 30 s hold — the win is the 9 s hover + the exoneration, not a completed flight; (3) props-on gyro is one level-hover window, not a sweep; (4) the vz fix is designed but unbuilt — the vz-rail + thrust-divergence metrics here are exactly how the next flight will prove it.

## Lineage
Parents: **fancy-smoke-0094** (the props-off bench check that cleared this flight) and **broken-wildflower-8398** (the d50var_s8 policy under test, ★ studio-baseline). Decision this block: build the measurement infra before more flying (flight-log analyzer + sim-vs-real + Flywheel-per-flight). Deferred immediate follow-on: the **RPM-anchor vz fix** (replace accel-integrated vz_est with an rpm_rms hover anchor — rpm_rms is healthy here ~26k rms, bidir-DShot working). Commit `636ad9b`.