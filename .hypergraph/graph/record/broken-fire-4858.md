---
node_id: 6740ae66-48b9-5c67-ac31-97258e7e0035
slug: broken-fire-4858
title: 'First real-ToF flights (3 × hover_tof @ 0.7 m over ESP-NOW): 3.3 s clean hovers at ~2.8° median tilt and the h-noise calibration data captured — but vertical control oscillates into the 1.3 m ceiling, and flight 3 ended in a tumbling crash'
created_at: '2026-08-08T13:02:26.498056+00:00'
parents:
- young-tree-5511
- white-rice-3299
summary: 'hover_tof_air65_w128u15 (★ studio-baseline) flown for real for the first time with the ToF in the loop — 3 flights at --target-height 0.7 over the repaired ESP-NOW link, Studio Real tab, guards on (min_thrust_frac 0.25, tof-blind grace/fade, max_us 1600). GOT: every flight shows a clean stable-hover window (3.31/3.32/3.33 s at median tilt 2.83/2.75/2.96°, p90 ≤3.7°), thrust telemetry faithful (thrust_divergence not detected, all 3), and the long-awaited calibration data — real ToF height logged at 71–93% airborne coverage plus props-on gyro noise from the fully-stable flight 2: sd p/q/r = 0.091/0.108/0.082 rad/s, lag1 ρ = 0.60/0.62/0.82 (the placeholder h-noise DR can now be fit). NOT GOT: a settled 0.7 m hover — all 3 flights oscillate vertically (vz railed at the ±2 m/s clamp for 13.9/6.8/11.6% of airborne frames; height mean 0.16–0.33 m, sd 0.27–0.44 m; peaks 1.29/1.34/1.20 m kiss the 1.3 m ToF ceiling even from a 0.7 m setpoint), and flight 3 departed at t≈6.4 into a tumbling crash (roll →138°, |gyro| ≈35 rad/s) with visibly stale attitude frames during the departure (same roll/pitch repeated across 3–4 frames, obs_age 24–95 ms). In-flight link: median 22–23 ms but p99 123–226 ms with up to 9.3% of frames >100 ms — the bench air-tail regression (young-tree-5511) is real in flight; no better than the old WiFi baseline (122–232 ms). Aftermath: airframe needs rewiring (crash damage); bench down. Mixed verdict, no outcome tag. Artifacts: telemetry PNG + summary JSON + run.json for all 3 flights.'
origin:
  backend: flywheel
  node_id: 6740ae66-48b9-5c67-ac31-97258e7e0035
  slug: broken-fire-4858
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 7d2ea46c-1e03-53e5-b145-1be580388814
  slug: flat-dew-2459
  revision: 0
  pushed_at: '2026-08-09T21:28:18+00:00'
  content_sha256: 4b75856b4a7f3c7fbe3c371ddf7dd707891189e2592889d9fc4cfde96d2606b4
---
## Hypothesis

`white-rice-3299` shipped hover_tof_air65_w128u15 with a bench handoff: the first real ToF flight
would (a) demonstrate the deploy stack end to end and (b) capture the data to calibrate the
placeholder h-noise DR. The 2026-07-31 ToF-ceiling finding corrected the setpoint to 0.7 m; the
guards (min_thrust_frac 0.25, tof-blind grace 0.2 / fade 0.3, max_us 1600) default on.

## Setup

3 flights, Studio Real tab over the freshly-repaired ESP-NOW link (`young-tree-5511`), Air65 II,
`--flight-target-height 0.7`, radio owning arm/kill. CSVs `flight_1786192970/88/... 93002`,
packed with `flight_report.py` (all three packs attached).

## Results

**What worked, per flight:** a clean stable-hover window in all three — 3.31 / 3.32 / 3.33 s at
median tilt 2.83° / 2.75° / 2.96° (p90 ≤ 3.72°). Thrust telemetry faithful: `thrust_divergence`
not detected in any flight (us_thr ramp 1162→1575 tracks a_thr). Battery healthy (v0 3.88–3.97,
sag ≤ 0.24 V).

**The calibration data — the point of the handoff — captured:**
- Real ToF height in the log at 71–93% airborne coverage (`z` = measured bridge-ToF height).
- Props-on gyro noise from flight 2 (the only one whose entire airborne phase stayed stable, so its
  window is uncontaminated): **sd p/q/r = 0.091 / 0.108 / 0.082 rad/s, lag1 ρ = 0.60 / 0.62 /
  0.82**. These are the numbers the placeholder h-noise/gyro DR should be refit from (flight 1's
  p-sd of 1.13 rad/s is departure-contaminated — use flight 2).

**What did not work — vertical control oscillates in all three flights:** vz pinned at the ±2 m/s
clamp for 13.9% / 6.8% / 11.6% of airborne frames (first rail at t≈5.2–6.0 s, i.e. after the clean
window); height mean 0.16–0.33 m with sd 0.27–0.44 m against a 0.7 m setpoint; peaks 1.291 /
1.341 / 1.197 m — **the flights kiss the 1.3 m ToF ceiling even from 0.7 m**, so the 0.37 m
overshoot number from SIM2REAL.md undersells the oscillation once it builds. The blind-grace fade
prevents the old held-error deploy failure, but it does not damp the oscillation itself.

**Flight 3 crash:** departure at t≈6.4 s → tumbling crash by 8.16 s — roll reaches 2.41 rad
(138°), |gyro| ≈ 35 rad/s. During the departure the attitude channel is visibly stale: the same
roll/pitch value repeats across 3–4 consecutive control frames while gyro keeps changing, obs_age
oscillating 24–95 ms. Recorded as measured; whether staleness caused or merely accompanied the
departure is not established.

**In-flight link:** median 22–23 ms but p99 123 / 123 / 226 ms, frac>100 ms up to 9.3% (flight 1).
The bench air-tail regression measured in `young-tree-5511` (air p99 62.76 ms at the desk) is real
and worse in flight — the new board pair currently flies no better than the old WiFi baseline
(122–232 ms p99 obs_age), erasing ESP-NOW's measured advantage (`black-firefly-9000` had full-trip
p99 39 ms on the old pair).

## Verdict / Honesty

Mixed — deliberately no outcome tag. The deploy stack is real: policy + ToF + ESP-NOW + guards fly,
hover quality inside the stable window is good (≤3° median tilt), and the calibration data the
whole handoff was for is in hand. But the vertical axis is not controlled to spec (railing,
ceiling touches, 0.16–0.33 m means vs 0.7 target), flight 3 ended in a hard crash that takes the
airframe down for a rewire, and the link tail regression is confirmed in flight. The next
sim-side session should (a) refit the h-noise DR from flight 2's numbers and (b) attack the
vertical oscillation — see the child idea node on a 0.1 m ultra-still hover task, which sidesteps
the ceiling entirely and makes crashes nearly free.

## Lineage

- Parent `white-rice-3299` — the deployed policy + the bench handoff these flights execute.
- Parent `young-tree-5511` — the same-day bring-up that unblocked the flights; its unexplained
  air-latency tail is confirmed in flight here.
- Sibling context: `tiny-glitter-0842` characterized the ToF sensor itself (23.9 ± 2.4 mm floor);
  today adds the in-flight h-noise numbers it lacked.