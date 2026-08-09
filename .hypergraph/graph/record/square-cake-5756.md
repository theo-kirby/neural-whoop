---
node_id: 08c0c825-47ea-5e2f-a9c0-eb0c353b10e7
slug: square-cake-5756
title: 'PPO exploration (ent_coef) sweep: RED / no-effect — headroom is a control limit, not exploration'
created_at: '2026-06-26T13:09:13.721856+00:00'
parents:
- morning-base-2167
- silent-math-9686
summary: 'RESOLVED RED / no-effect. Hop-4 showed ~37% lap-time headroom (policy under-cruises straights); hypothesis was that PPO is stuck in a conservative-cruise local optimum that more exploration could escape. Swept ent_coef {0 (control), 0.001, 0.005, 0.01} on tp=0.05, 40M steps, DR-off eval. Result is MONOTONIC and opposite to the hope: more entropy -> SLOWER laps + HIGHER completion (ent001 3.252s/0.843 ~= control; ent005 3.595s/0.876; ent01 3.811s/0.900). Entropy regularization just slides the policy further down the completion side of the speed/completion Pareto frontier; it does not unlock speed. Conclusion: the headroom is a CONTROL-QUALITY / algorithm limit -- the policy already flies as fast as it safely can with PPO + this action rep. Closing it needs differentiable-dynamics control (SHAC/BPTT), a finer action representation, or a curriculum, NOT more exploration or reward-weight tuning (saturated, hop-3). Pure config; no code; baseline unchanged at df93a29. stop_reason=no-effect.'
origin:
  backend: flywheel
  node_id: 08c0c825-47ea-5e2f-a9c0-eb0c353b10e7
  slug: square-cake-5756
  revision: 25
  exported_at: '2026-08-09T18:23:28+00:00'
---
# PPO exploration (ent_coef) sweep (empirical node, RESOLVED — RED / no-effect)

## Lineage (DAG merge)
- **builds-on:** `e4a66478` (tp=0.05 GREEN baseline, ~3.13–3.19s) — the validated state swept on top of.
- **informed-by:** `bd57f350` (hop-4 GREEN / honest oracle) — its ~37% headroom + 'under-cruises straights' finding is *why* this hop tries exploration to escape the conservative-cruise basin.

## Hypothesis (refuted)
Hop-4 found the policy laps at 0.73 of the dynamically-feasible pace, sustaining ~4 m/s of its ~7 m/s capability on straights. Hypothesis: PPO has converged to a conservative-cruise **local optimum**, and more exploration (action-distribution entropy) could escape it toward a faster-but-still-completing regime.

## What was run (40M steps each, seed 0; eval DR-off 2048x1500 seed 12345)
Sweep `ppo.ent_coef` (pure config on `gate_race.yaml`); control is the baseline (ent_coef=0; seed0 3.185, multi-seed mean 3.289 / completion 0.847).

| ent_coef | best_lap (s) | completion | crash/step | laps_mean |
|---|---|---|---|---|
| 0 (control) | 3.185 (ms 3.289) | 0.847–0.866 | 2.3e-4 | 1.23 |
| 0.001 | 3.252 | 0.843 | 1.8e-4 | 1.07 |
| 0.005 | 3.595 | 0.876 | 1.6e-4 | 0.99 |
| 0.010 | 3.811 | 0.900 | 0.9e-4 | 0.93 |

## Verdict: RED / no-effect (and regresses with more entropy)
**Monotonic and opposite to the hypothesis:** more entropy makes the policy **slower and safer**, not faster. ent_coef=0.001 lands inside the control's own multi-seed band (3.12–3.56s) — no win; 0.005 and 0.010 clearly regress best_lap while raising completion. Entropy regularization keeps the action distribution wide, which yields smoother, more conservative flying — it slides the policy *further down the completion side* of the speed/completion Pareto frontier rather than unlocking the speed headroom. The conservative-cruise behavior is therefore **not** an exploration failure.

## Interpretation (frontier-relevant)
Three levers have now been exhausted on the racing speed metric: reward-weight tuning (hop-3, saturated), and exploration (hop-5, moves the wrong way) — with the dense time_penalty (hop-1) already at its completion knee. The ~37% headroom (hop-4) is a **control-quality / algorithm limit**: PPO with the current CTBR action representation flies as fast as it safely can; pushing speed costs completion/crashes because control is the binding constraint. Closing the headroom needs a different *kind* of lever, not another knob on the same optimizer/reward.

## Action taken
Pure config sweep (no code); scratch configs removed; baseline unchanged at **df93a29**. The ent_coef knob already exists in `configs/gate_race.yaml` (`ppo.ent_coef`), so the sweep is reproducible by setting it to {0.001, 0.005, 0.01}.

## Artifacts
hop5_summary.json (the sweep + interpretation); ent_sweep.png (best_lap & completion vs ent_coef — the monotonic trade); standard visual pack on the ent_coef=0.001 representative variant vs the tp=0.05 baseline parent (trajectory / comparison / fpv; leaderboard table; eval json; portable replay). No training_curves (these runs trained render-free without TB).

## Stop reason: no-effect

## Next frontier (replan — n=1 from here)
The speed headroom is a control/algorithm limit, so the next hop must change the optimizer or the control problem, not tune PPO/reward. Candidates: (a) **implement DiffAero SHAC/BPTT** (the reserved `--algo shac`) — differentiable short-horizon RL can exploit analytic dynamics gradients for finer control PPO's score-function estimator misses (highest-information, but a real implementation chunk); (b) **course-difficulty / speed curriculum** — anneal toward harder/faster courses so the policy learns the high-speed control regime gradually; (c) **pivot off the (now well-characterized) speed metric** to the hop-3 DR-on reliability gap (completion 0.68 under DR) or the first n_agents>1 swarm task. Recommend (a) if a SHAC implementation fits the local budget, else (b) as the cheaper config/curriculum lever.