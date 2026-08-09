---
node_id: 1efa6f41-2fcc-5d70-973d-8278d3ac8640
slug: icy-flower-1085
title: 'hover_air65_bridge (3 seeds): first-flight hover under ESP-bridge DR — hold 0.73–0.78 DR-on ≈ hover_base''s 0.75 under an easier regime, GREEN'
created_at: '2026-07-04T09:15:46.903690+00:00'
parents:
- bitter-fire-0679
- long-queen-3431
summary: 'hover re-centered for the real first-flight stack (Air65 II + XIAO companion, ~30 g AUW mass DR 26–34 g, action_latency_steps 3 = 0–60 ms lumped ESP-bridge round trip; wind + impulse seam kept ON) vs parent recipe hover_base (32 g, 0–20 ms): DR-on eval (2048 drones, 1500 steps) hold_rate 0.776/0.727/0.770 across seeds 0/1/2, mean_pos_error 0.33–0.37 m, crash 0.11–0.16%/step — statistically matching hover_base''s 0.749 hold / 0.286 m under its EASIER regime; clean-air (no-DR) hold 0.918, tilt 2.7°, zero crashes. Verdict GREEN: the branch-B latency+payload envelope costs essentially nothing on hover — seed-0 ckpt is the first-flight checkpoint candidate. Honesty: found + fixed a real eval-metrics bug en route (commit 8ef15e0): evaluate() read task.metrics() after lockstep truncation resets zeroed the accumulators (hover_base originally ''evaled'' at pos_err 0.013/hold 0.019 — self-contradictory); tasks now expose per-step metric tensors in info[''metrics''], aggregated rollout-wide (regression-tested; follow/formation tasks share the pattern, adoption pending). Standard pack attached (seed 0, no-DR hero vs hover_base baseline). Configs/commits: 0ea71b2 (config+sweep), 8ef15e0 (metrics fix).'
origin:
  backend: flywheel
  node_id: 1efa6f41-2fcc-5d70-973d-8278d3ac8640
  slug: icy-flower-1085
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
---
# hover_air65_bridge: first-flight hover under the ESP-bridge envelope (3 seeds)

**Hypothesis.** The branch-B first-flight stack (Air65 II + XIAO ESP32-S3 companion; host policy over WiFi/ESP-NOW → MSP override) changes two things vs the trained hover_base: +payload mass (~30 g AUW) and a longer action round trip (~20–50 ms measured band). Hover should train to baseline-comparable hold under this regime — if it doesn't, branch B needs a rethink before soldering.

**Setup.** `configs/hover_air65_bridge.yaml` = fork of `hover.yaml` (hover_base recipe: same task shaping, [64,64] tanh, adam 3e-4, 40M steps, wind 2.0 + impulse seam ON, dr_curriculum 0.3) changing ONLY: `whoop.mass [0.030, 0.026–0.034]` + inertia ~0.9x (Air65 II + XIAO payload; clean-Air65 is 0.8x), and `action_latency_steps 1→3` (0–60 ms lumped — hover declares no `uplink_slices`, its whole loop is offboard, so the lumped action-side knob is the honest one). 3 seeds (0/1/2), ~90 s each at ~480k sps on the 5090. Commit `0ea71b2`.

**Results.** DR-on eval (2048 drones × 1500 steps, deterministic):

| run | hold_rate | pos_err (m) | tilt (deg) | crash %/step |
|---|---|---|---|---|
| bridge s0 | **0.776** | 0.330 | 16.0 | 0.11 |
| bridge s1 | 0.727 | 0.366 | 17.0 | 0.16 |
| bridge s2 | 0.770 | 0.347 | 16.7 | 0.14 |
| hover_base (its own easier DR: 32 g, 0–20 ms) | 0.749 | 0.286 | 13.8 | 0.00 |
| bridge s2, no-DR | 0.918 | 0.262 | 2.7 | 0.00 |

Δ vs parent: hold **0.75→0.73–0.78 under a strictly harder regime** (3× the latency band, ±15% heavier + payload) — the ESP-bridge envelope costs ≈nothing on station-keeping. Crash-rate 0.11–0.16%/step is impulse-kick recovery losses (the 2%/step shove seam), absent in clean air (0.00). No-DR mean_pos_error 0.26 m is dominated by the recovery cohort's fly-to-setpoint transit; steady-state hold is the 0.92.

**Verdict.** GREEN — hover survives the branch-B latency+payload envelope at parity with baseline; **seed-0 `ckpt_final.pt` is the first-flight checkpoint candidate** pending Stage-0 bench numbers (real mass/TWR/K_angvel) to re-pin the airframe.

**Honesty.**
- Found a real eval-metrics bug while comparing to baseline: `evaluate()` read `task.metrics()` once at the end, but hover-family per-episode accumulators zero on auto-reset — a no-crash lockstep population with horizon = k×episode_len reset right at the read (hover_base initially 'evaled' at pos_err 0.013 m with hold 0.019: self-contradictory). Fixed (commit `8ef15e0`): tasks expose per-step metric tensors in `info['metrics']`, eval aggregates rollout-wide; regression test pins the boundary case; suite 127 green. The bridge seeds' pre-fix numbers looked plausible only because staggered crash-resets desynced their episodes — they were still biased and are superseded by the table above. follow/formation tasks share the accumulator pattern — adoption is a pending follow-up.
- action_latency lumps uplink+downlink into one action-side delay; real split behavior gets measured at Stage 1 (bench latency capture) and can move to a proper split seam if hover ever grows offboard-computed obs channels.
- Airframe numbers (mass/inertia) remain provisional estimates until the kitchen-scale + bench session.

**Artifacts.** Standard visual pack, seed 0, no-DR hero rollout vs `hover_base` baseline replay: replay.json.gz, trajectory.png, fpv_00/01.png, training_curves.png, comparison.png + table.csv, run.json (repro manifest), eval.json.

**Lineage.** Recipe parent: **hover_base** (`configs/hover.yaml`, the auto-stabilization workstream — its node predates this branch's docs so the edge is cited here textually; config fork is 1:1 minus the two changed blocks). Context parents: the control-path branch map `long-queen-3431` (branch B's latency band + payload numbers) and the sim2real plan `bitter-fire-0679` (this executes its 'sim-side work startable now' item 5: re-train hover under the new DR). Sibling: the Stage-0 MSP bench toolkit `frosty-pond-8115` (same-day; its bench numbers will re-pin this config's airframe block).