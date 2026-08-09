---
node_id: e4a66478-ac1a-5499-b643-06725f4e48bf
slug: morning-base-2167
title: 'Reward shaping: time_penalty sweep -> 0.05 beats the oracle (GREEN)'
created_at: '2026-06-26T09:27:25.593897+00:00'
parents:
- winter-sun-1382
summary: 'RESOLVED / GREEN. Confirmed hypothesis: time_penalty was the only real minimum-time pressure (progress reward telescopes; lap-bonus speed scaling weak). time_penalty sweep {0.02,0.05,0.10,0.20}, 40M steps each on the 5090, DR-off eval. Winner tp=0.05: best_lap 3.185s (-15% vs 0.02 control 3.760s; -18% vs baseline node 3.868s), now BELOW the v_ref=4.0 oracle (3.49s); completion 0.922->0.866, crash still ~2e-4/step, laps_mean 0.96->1.23. tp=0.10 regresses completion (0.715); tp=0.20 collapses into the predicted suicide mode (0 laps). gate_race.yaml updated to time_penalty=0.05 (commit 4381bd7). stop_reason=improved.'
origin:
  backend: flywheel
  node_id: e4a66478-ac1a-5499-b643-06725f4e48bf
  slug: morning-base-2167
  revision: 27
  exported_at: '2026-08-09T18:23:28+00:00'
---
# Reward shaping: time_penalty sweep (empirical node, RESOLVED — GREEN)

## Hypothesis
The GREEN gate_race baseline reaches best_lap 3.868s vs oracle 3.475s — **~11% off time-optimal**. Reading the reward (`tasks/gate_race.py:reward_and_done`):

```
reward = progress_scale*(prev_dist - curr_dist) + alive_bonus - time_penalty
       + gate_bonus*passed - smoothness_penalty
       + lap_bonus * clamp(oracle_lap/lap_time, 0.25, 4.0)   # only on lap completion
       - crash_penalty*crashed
```

The **progress term telescopes over a lap** (sum of prev_dist-curr_dist = fixed path geometry) -> it is *speed-neutral* across an episode. The speed-scaled lap bonus only swings ~2 reward between baseline pace (factor 0.90) and oracle pace (factor 1.0). So the dominant — nearly the only — minimum-time pressure is the constant `time_penalty` (0.02/step), the textbook minimum-time shaping. At 0.02 it is ~7% of per-lap reward, plausibly too weak.

**Prediction:** raising time_penalty pushes best_lap down toward the oracle, until it gets large enough to trade completion/crash (the 'suicide' failure mode, bounded by crash_penalty=10) — revealing the speed/completion frontier.

## Design (single clean variable)
Sweep `task.time_penalty` in {0.02 (control / baseline-repro), 0.05, 0.10, 0.20}. All else identical to `configs/gate_race.yaml` (4096 envs, 40M steps, PPO unchanged, DR on in training). Metric = best_lap_time (DOWN); guardrails = lap_completion_rate + crash_rate_per_step. Eval deterministic, **DR off**, 2048 envs x 1500 steps, seed 12345 — same protocol as the baseline node.

## Results (DR-off eval)

| time_penalty | best_lap (s) | completion | crash/step | laps_mean | note |
|---|---|---|---|---|---|
| (baseline node ff881809) | 3.868 | 0.908 | 8.6e-5 | 0.93 | prior frontier |
| 0.02 (control repro) | 3.760 | 0.922 | 8.1e-5 | 0.96 | reproduces baseline |
| **0.05 (WINNER)** | **3.185** | 0.866 | 2.3e-4 | 1.23 | **beats oracle 3.49s** |
| 0.10 | 3.265 | 0.715 | 6.2e-4 | 1.05 | completion regresses |
| 0.20 | NaN | 0.000 | 2.2e-2 | 0.00 | suicide collapse |

Oracle lap (v_ref=4.0) ≈ 3.48–3.50s across runs. Training throughput ~444–450k env-steps/s (~90s/run).

## Verdict: GREEN / improved
**tp=0.05** is the clear optimum: best_lap **3.185s**, a **15% gain over the 0.02 control** (3.760s) and **18% over the original baseline node** (3.868s) — the policy now flies the course **faster than the v_ref=4.0 speed oracle** (speed_factor ~1.10). The guardrails hold: completion stays high (0.866; and laps_completed_mean actually *rose* 0.96 -> 1.23 because faster laps fit the eval window) and crash rate stays tiny (2.3e-4/step). The hypothesis is confirmed end-to-end, including the predicted **suicide failure mode** materializing exactly at tp=0.20 (ep_ret pinned at -12.5, zero laps, crash 2.2e-2/step), which bounds the useful range; tp=0.10 already over-presses (completion 0.715). The frontier is cleanly unimodal with the optimum at ~0.05.

## Action taken
`configs/gate_race.yaml`: `time_penalty 0.02 -> 0.05` (the new baseline), committed at **4381bd7** with this node id. env_check + 25 pytest tests green before commit. Winner checkpoint `runs/gate_race_tp005/ckpt_final.pt`; deploy policy exported (ONNX round-trips at 2.38e-7) — attached.

## Artifacts
tp_sweep_summary.json (consolidated frontier), eval_tp005_winner.json, eval_tp002_control.json, eval_tp010.json, eval_tp020.json, policy_tp005.onnx (deployable winner).

## Reproduce
Fork gate_race.yaml per tp (edit time_penalty + run.name); `scripts/train.py --config <cfg> --name gate_race_tpXXX` then `scripts/eval.py --config <cfg> --from runs/gate_race_tpXXX/ckpt_final.pt --no-dr --json`.

## Stop reason: improved

## Next frontier (n=1 from here)
The oracle (point-mass path-length / v_ref) is now beaten, so it is a weak yardstick. Candidate next hops: (a) **raise the oracle / refine it** to an accel+turn-limited reference so 'time-optimal' is honest again; (b) **fine-grid time_penalty in [0.04,0.07]** to squeeze the optimum and characterize the completion knee; (c) **racing-line / speed-projection reward** (reward velocity projected on the gate-to-gate chord) to attack the line, not just the clock; (d) **curriculum on course difficulty** now that laps are fast. Recommend (a)+(c) together as the next direction since the current oracle no longer bounds optimality.