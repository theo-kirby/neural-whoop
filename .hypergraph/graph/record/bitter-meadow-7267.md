---
node_id: 5fcc1b12-f5a2-5446-91f3-4dc774e0fe56
slug: bitter-meadow-7267
title: 'Strengthen pass-gated speed-scaled lap bonus: RED / no-effect (reward-weight tuning saturated)'
created_at: '2026-06-26T09:57:46.414197+00:00'
parents:
- morning-base-2167
- aged-darkness-9566
summary: 'RESOLVED RED / no-effect. Tested both ways to strengthen the pass-gated lap-completion bonus on tp=0.05. MAGNITUDE (lap_bonus 20/40/80, DR-off): 40 flat vs control, 80 destabilized value learning (best_lap 3.62s, completion 0.62). Multi-seed n=3: control best_lap mean 3.289s vs lb40 3.275s -- Delta 0.014s, far inside seed sigma ~0.25s (runs span 3.02-3.68). SHAPE (speed_factor**p): p=2 flat; p=3 multi-seed mean 3.217s vs control 3.289s (0.072s, inside noise) bought with a CONSISTENT -9pt completion (0.758 vs 0.847) and 2.6x crash rate. Conclusion: strengthening the sparse once-per-lap bonus does NOT lower converged lap time; the dense time_penalty is the only effective lever and already sits at its completion knee (tp=0.05). Reward-weight tuning of existing terms is SATURATED. Bonus finding: DR-ON transfer-honest baseline is 3.229s but completion only 0.677 -- the real gap is reliability under DR, not speed. Code: speed_factor_exp prototype REVERTED; baseline unchanged at 28f896b. stop_reason=no-effect.'
origin:
  backend: flywheel
  node_id: 5fcc1b12-f5a2-5446-91f3-4dc774e0fe56
  slug: bitter-meadow-7267
  revision: 27
  exported_at: '2026-08-09T18:23:28+00:00'
---
# Strengthen the pass-gated speed-scaled lap bonus (empirical node, RESOLVED — RED / no-effect)

## Lineage (DAG merge, not a chain)
- **builds-on:** `e4a66478` (tp=0.05 GREEN baseline) — ran on top of that validated reward/config state; it is the baseline this had to beat.
- **informed-by:** `0238f7d7` (racing-line RED / reward-hacking) — its refutation is *why* this hop chose a pass-gated lever instead of another dense per-step speed bonus.

## Hypothesis (refuted)
Hop 2 showed ungated dense speed bonuses reward-hack, so a valid lap-time lever must be **pass-gated**. The task already has one — `reward += lap_bonus * clamp(oracle_lap/lap_time, 0.25, 4.0)`, collected **only** on `lap_done` (non-hackable by construction). Prediction: strengthening it makes faster complete laps materially more rewarding → lower `best_lap` **while protecting completion** (the bonus requires completion). **This was refuted on the primary metric.**

## What was run (canonical eval: deterministic, DR-off, 2048 envs × 1500 steps, seed 12345; 40M training steps/run, DR on)

### (1) Magnitude — `lap_bonus` ∈ {20 (control), 40, 80}, pure config, seed 0
| lap_bonus | best_lap (s) | completion | crash/step | laps_mean |
|---|---|---|---|---|
| 20 (control) | 3.185 | 0.866 | 2.3e-4 | 1.23 |
| 40 | 3.126 | 0.804 | 3.1e-4 | 1.17 |
| 80 | **3.617** | **0.616** | 7.4e-4 | 0.83 |

lb40's 3.126 is a 0.059 s nominal gain — right at the ~0.06 s run-to-run noise margin, and it lands at the low end of the baseline's *own* known reseed range (3.126–3.185), while completion drops 6 pts. lb80 clearly **regressed**: the large sparse return destabilizes value learning (training best_lap drifted to ~3.87 s, completion 0.48).

### (2) Magnitude multi-seed (n=3, DR-off) — to separate signal from seed noise
| | s0 | s1 | s2 | **mean** | completion mean | crash mean |
|---|---|---|---|---|---|---|
| control (lb=20) | 3.185 | 3.120 | 3.562 | **3.289** | 0.847 | 1.8e-4 |
| lb=40 | 3.126 | 3.018 | 3.681 | **3.275** | 0.802 | 3.1e-4 |

**Δmean = 0.014 s** — utterly negligible against seed σ≈0.25 s (the per-seed runs span 3.02–3.68 s; the s2 seed was bad for *both* conditions). The `lap_bonus` magnitude has **no measurable effect** on lap time.

### (3) Shape — `speed_factor**p`, p ∈ {1 (control), 2, 3}
Motivation distinct from magnitude: raising `lap_bonus` scales the *whole* factor (so it also makes merely-completing a slow lap, factor∈[0.25,1], more attractive), whereas the exponent **suppresses** slow-lap reward (factor<1 → smaller) and **amplifies** fast-lap reward — a purer speed lever. Required a tiny code change: `speed_factor_exp` added to `GateRaceConfig` (default 1.0 = current behaviour) applied in `reward_and_done`.

| variant | best_lap (s) | completion | crash/step | laps_mean |
|---|---|---|---|---|
| p=2 (seed 0) | 3.239 | 0.877 | 1.3e-4 | 1.25 |
| p=3 (seed 0) | 3.009 | 0.775 | 4.8e-4 | 1.25 |

p=2 is flat vs control. p=3 multi-seed (n=3): best_lap [3.009, 3.355, 3.286] → **mean 3.217 s** vs control 3.289 s (Δ 0.072 s ≈ 0.3σ, inside noise), but completion [0.775, 0.814, 0.685] → **0.758 mean (−9 pts, consistent every seed)** and crash mean **4.7e-4 (~2.6×)**. So p=3 just re-walks the same speed/completion frontier that raising `time_penalty` already maps — it spends completion + safety for a lap-time change indistinguishable from noise.

### (4) Transfer-honest DR-ON baseline (bonus, off the staged bench list)
tp=0.05 baseline ckpt eval'd **with DR on**: best_lap **3.229 s** (vs 3.185 DR-off — speed barely degrades) but completion **0.677** (vs 0.866) and crash **6.3e-4** (vs 2.3e-4). Under the real-whoop perturbations (wind / rate-gain / thrust / latency / obs-noise) the gap is **reliability, not speed**.

## Verdict: RED / no-effect
Strengthening the pass-gated lap bonus — by **magnitude** (lb40 flat; lb80 destabilizes) or by **shape exponent** (p=2 flat; p=3 trades guardrails for a noise-level lap-time delta) — does **not** lower converged `best_lap`. The deeper, decision-relevant lesson: the sparse once-per-lap pass-gated bonus is too weak a gradient signal to reshape the converged trajectory; the **dense per-step `time_penalty`** is the only effective minimum-time lever and it already sits at its completion-knee optimum (tp=0.05, hop-1). **Reward-weight tuning of the existing reward terms is saturated.**

## Action taken
Code prototype `speed_factor_exp` **REVERTED** (default-preserving and pytest-green, but the lever is refuted — keeping the repo at the validated baseline, matching the hop-2 discipline). Baseline unchanged at **28f896b**. env_check + 39 pytest tests green. The magnitude sweep needed no code (pure `lap_bonus` config override).

## Reproduce
- Magnitude: fork `configs/gate_race.yaml`, set `task.lap_bonus` ∈ {40,80} + `run.name`; `scripts/train.py --config <cfg> --name gate_race_lbXX [--seed S]`; `scripts/eval.py --config <cfg> --from runs/gate_race_lbXX/ckpt_final.pt --no-dr --json`.
- Shape: re-add `speed_factor_exp: float = 1.0` to `GateRaceConfig` and `if c.speed_factor_exp != 1.0: speed_factor = speed_factor ** c.speed_factor_exp` after the clamp in `reward_and_done`; set `task.speed_factor_exp` ∈ {2,3}.
- DR-ON baseline: `scripts/eval.py --config configs/gate_race.yaml --from runs/gate_race_tp005/ckpt_final.pt --json` (omit `--no-dr`).

## Artifacts
hop3_summary.json (consolidated sweep + multi-seed + DR-on); the standard visual pack recorded on the lb40 representative variant vs the tp=0.05 baseline parent (trajectory / comparison / training_curves / fpv; leaderboard table; eval json; portable replay).

## Stop reason: no-effect

## Next frontier (replan — n=1 from here)
Reward-weight tuning is saturated and the point-mass oracle is already beaten, so 'time-optimal' is no longer measurable AND the DR-ON result shows the live gap is reliability. Recommended next hop: **establish an honest, dynamically-feasible oracle (accel + turn-rate limited) to re-instate a real optimality yardstick**, then decide between (a) closing the DR-ON reliability gap (completion 0.68 → speed-honest robustness) and (b) pivoting axes entirely (PPO/SHAC at equal wall-clock, curriculum, course difficulty, or the first n_agents>1 swarm task). See the staged successor node.