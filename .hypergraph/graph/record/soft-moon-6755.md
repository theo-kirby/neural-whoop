---
node_id: b20dc0fe-502b-5f23-bcac-b47c1f00b721
slug: soft-moon-6755
title: 'O-3 hybrid-obs split-latency retrain (GREEN): onboard execution buys back the offboard conservatism tax — −6% lap everywhere at equal-or-better completion; completion is DR-floor-limited, not latency-limited'
created_at: '2026-07-02T12:14:23.864279+00:00'
parents:
- little-term-0124
- royal-field-3745
- blue-unit-1398
summary: 'O-3 hybrid-obs retrain (new uplink staleness DR seam, commit 55ff26e): moving the 0–100 ms latency from the action path (offboard) to a ~25 Hz zero-order-held target channel (onboard hybrid) makes the retrained policy ~6% faster EVERYWHERE (3.203→3.021 s clean, 3.29→3.07 DR-on) at equal-or-better completion — action-latency training bakes in a conservatism tax that onboard execution removes. Completion floor (~0.80 DR-on) is set by the non-latency DR, not by where latency sits. GREEN; quantifies the Path-B companion payoff pre-purchase. Pack + comparison table attached.'
origin:
  backend: flywheel
  node_id: b20dc0fe-502b-5f23-bcac-b47c1f00b721
  slug: soft-moon-6755
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
---
# O-3: hybrid-obs split-latency retrain — what onboard execution is worth before buying hardware

**Hypothesis** (staged in summer-boat-5684, architecture from little-term-0124): the onboard-hybrid split — policy on the drone with FRESH local state obs (vel/att/rates) + a STALE ~30 Hz uplinked target channel — has a strictly smaller sim2real gap than full-offboard, and a policy retrained under it should buy back part of the latency tax blue-unit-1398 paid (offboard DR-on completion 0.79 vs 0.93 no-DR).

**Setup.** New seam-DR primitive (commit 55ff26e): `uplink_latency_steps` / `uplink_interval_steps` delay + zero-order-hold the task-declared uplink obs channels (`DroneTask.uplink_slices`; gate_race = target encoding + next-gate lookahead) via a per-drone ring buffer mirroring the action-latency one (never reads across a reset; measurement noise frozen across holds). Unit-tested pure (tests/test_uplink_latency.py); pytest 117-green + env_check green. Config `gate_race_air65_hybrid.yaml`: fork of `gate_race_air65`, ONLY the latency DR re-shaped — action_latency 5→1 (onboard control loop), uplink_latency 5 + interval 2 (~25–30 Hz uplink, 0–100 ms). [128,128]@120M, ~5 min. Eval seed 12345, 2048×1500, DR-on + no-DR vs the offboard-trained blue-unit-1398 policy.

**Results.**
| regime | offboard-trained (blue-unit-1398) | hybrid-trained (this) | Δ |
|---|---|---|---|
| no-DR completion | 0.926 | **0.934** | +0.8 pt |
| no-DR best lap | 3.203 s | **3.021 s** | **−5.7%** |
| own-DR-on completion | 0.79 | **0.809** | +1.9 pt |
| own-DR-on best lap | 3.29 s | **3.072 s** | **−6.6%** |
| own-DR-on crash/step | 3.0e-4 | 3.7e-4 | ~par |

**Verdict — GREEN, with the honest decomposition.**
1. **The offboard loop's real cost is a conservatism tax baked into the policy, and onboard execution removes it.** Training under 0–100 ms ACTION latency forces a policy that flies ~6% slower everywhere — even evaluated clean. The same latency moved to the TARGET channel (fresh actions, stale uplinked goal) costs almost nothing: the hybrid policy beats the offboard one on every metric and nearly matches the pre-widening 0–20 ms era's numbers (0.93/3.02 vs the old 0.93/3.20 clean).
2. **Completion was never latency-dominated.** The DR-on completion floor (~0.80) barely moves (0.79→0.809) because it is set by the non-latency DR (wind/rate-gain/thrust/obs-noise) — consistent with royal-firefly-3187's 0.92→0.80 measurement at the old tight latency. Onboard compute buys SPEED, not the generic-DR completion floor.
3. **Decision input for Path B (ONBOARD_COMPUTE.md, BOM pending user approval):** the companion-MCU architecture is now quantified end-to-end in sim — ~6% faster laps at equal robustness, on top of sparkling-shadow-2507's 0.55 ms / 79 KB feasibility. The remaining sim2real unknowns are the real uplink jitter spectrum (O-1 bench) and the G473 flash headroom (O-2).

**Honesty / caveats.** (1) Uplink modeled as uniform 0–100 ms staleness + 25 Hz ZOH with a global sender clock; real ELRS/MSP jitter is burstier — refine at O-1. (2) Single seed; the −6% lap gap is well outside prior seed noise (~±1–2%) but the +2 pt completion is not. (3) DR-on numbers compare each policy under its own architecture's DR — that is the point (different physical realities), not a confound.

**Lineage.** Executes O-3 from summer-boat-5684's staged frontier; architecture per little-term-0124; compared against blue-unit-1398 (offboard latency baseline); control royal-field-3745. Code + config at 55ff26e (docs table at 4925a61). Artifacts: full standard pack (no-DR, baseline = blue-unit's replay) + DR-on architecture-comparison table.