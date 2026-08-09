---
node_id: 0b9fd006-ea48-55c7-a2c0-03965dac0b62
slug: little-term-0124
title: 'Onboard-compute paths for the Air65 II: hybrid-obs architecture, ranked A/B/C, Path-B companion first — docs/ONBOARD_COMPUTE.md'
created_at: '2026-07-02T10:13:37.975193+00:00'
parents:
- summer-boat-5684
- sparkling-shadow-2507
summary: 'Decision doc for onboard compute (docs/ONBOARD_COMPUTE.md @ f618b12): hybrid-obs architecture (fresh local state + ~30 Hz uplinked target) as the right onboard shape; paths ranked — A: G473-in-Betaflight end-state (0 g, flash headroom unmeasured → O-2), B: gram-class MSP companion RECOMMENDED first (also retires the flow-deck risk), C: camera deck deferred. BOM ~$40–55 awaiting approval; O-3 hybrid-obs retrain is the next no-hardware experiment.'
origin:
  backend: flywheel
  node_id: 0b9fd006-ea48-55c7-a2c0-03965dac0b62
  slug: little-term-0124
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: e15a4715-c6ae-5769-b4f0-566111efe7f0
  slug: orange-king-5423
  revision: 0
  pushed_at: '2026-08-09T21:26:51+00:00'
  content_sha256: f69998f753aee6ce4400e1b1e1f8b9abbe821160f892757e6a97ceb739e86734
---
## Hypothesis
Framing/decision node: given the O-0 measurement (parent sparkling-shadow-2507: policy = 79 KB flash / 1 KB RAM / ≥0.5% CPU headroom everywhere), which chip-on-the-whoop path should the project take, and how does it compose with the locked offboard-first plan?

## Setup
Analysis in docs/ONBOARD_COMPUTE.md @ f618b12 (attached), built on: the O-0 numbers; the tensaur/Crazyflie onboard existence proof (long-fog-2207); SIM2REAL.md's constraints (Air65 II ≈25 g AUW, G473 FC, flow-deck integration risk, 40–100 ms offboard latency as the dominant sim2real gap per blue-unit-1398); web-verified hardware facts (Crazyflie AI-deck: 4.4 g, GAP8 + Himax 320×320, ≤300 mA; Betaflight manages 512 KB targets via cloud-build feature trimming; XIAO/Teensy bare boards are gram-class — exact weights to be verified on a scale).

## Results — the analysis in brief
**Key insight: the obs vector, not compute, is the real fork.** Onboard execution pays because attitude/rates/velocity become fresh (vs 40–100 ms stale); `target_rel` stays camera-derived. The natural architecture is **hybrid-obs**: state obs sampled locally at control rate + a ~30 Hz uplinked target channel — the same staleness structure our DetectorNoise + action_latency DR already trains, but with delay confined to the target channel. Strictly smaller sim2real gap than full offboard.

Paths ranked:
- **A — the G473 the drone already carries** (+0 g, $0): policy as a Betaflight-fork task with a tensaur-style RL/PID param toggle. End-state for racing (zero mass, minimum latency); blocked on unmeasured flash headroom (O-2) and BF-fork risk. Not first.
- **B — gram-class companion MCU** (+1–3 g, ~$15–25): Teensy 4.0 / XIAO class running policy + flow→velocity estimation, reading the PMW3901 directly, commanding stock Betaflight via MSP on a spare UART. No firmware fork; ALSO retires the flow-deck integration risk SIM2REAL.md already flagged ("may need a tiny companion MCU"). **Recommended first step (O-1).**
- **C — camera+NN deck** (+3–5 g, $30–100): AI-deck/GAP8 class or XIAO ESP32-S3 Sense for onboard perception → full autonomy. Defer until B flies; the Sense board doubles as the cheap probe.

Staged plan O-0..O-4 (O-0 done this session); BOM (~$40–55, companion + PMW3901 + regulator) awaiting user approval — nothing ordered.

## Verdict / Honesty
Recommendation node — no outcome tag. The ranking rests on two unmeasured quantities, both staged: Air65 II Betaflight target flash size (O-2, buildable locally with zig/arm-gcc) and real board weights/current. The hybrid-obs retrain (O-3: split latency DR — fresh state, stale target) is the sim-side experiment this analysis makes testable NOW without any hardware, and is the natural next empirical node in this cluster.

## Lineage
Child of the onboard control (summer-boat-5684) + the O-0 measurement (sparkling-shadow-2507). Composes with the sim2real plan (bitter-fire-0679 / blue-unit-1398 latency-DR result) and imports the tensaur onboard pattern (long-fog-2207). Doc: docs/ONBOARD_COMPUTE.md @ f618b12 (attached).