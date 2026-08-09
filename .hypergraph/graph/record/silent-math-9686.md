---
node_id: bd57f350-09bf-504a-acb6-3798efada409
slug: silent-math-9686
title: 'Honest dynamically-feasible oracle: yardstick re-instated -> ~37% lap-time headroom (GREEN)'
created_at: '2026-06-26T12:41:06.857680+00:00'
parents:
- morning-base-2167
- bitter-meadow-7267
summary: 'RESOLVED GREEN / yardstick re-instated. Built neural_whoop/oracle.py: a pure batched feasible-oracle (top speed + tangential accel/brake trapezoidal profile + junction-deviation cornering cap), calibrated from the tp=0.05 baseline flown telemetry (p95: v_max=7, a_max=25, a_lat=23 m/s^2). On the seed-12345 eval courses it targets mean 2.32s vs the flown 3.185s -> the policy laps at only 73% of the dynamically-feasible pace (speed_factor 0.73), i.e. it does NOT beat the honest yardstick (hypothesis confirmed). The old path-length oracle (3.50s) was ~50% too slow because v_ref=4.0 was the MEAN flown speed, not a feasible cruise. Decisive frontier signal: racing is NOT solved -- ~37% headroom exists (grounded: the oracle uses speeds/accels the policy already hits transiently but fails to SUSTAIN on straights). Wired behind oracle_model flag (default pathlen -> baseline unchanged); 46 pytest green; committed df93a29. Selects next hop = sustain higher cruise speed on straights (algorithm: SHAC/BPTT vs PPO at equal wall-clock, and/or a speed-on-straights reward/curriculum). stop_reason=improved (measurement).'
origin:
  backend: flywheel
  node_id: bd57f350-09bf-504a-acb6-3798efada409
  slug: silent-math-9686
  revision: 26
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 4d5a5512-990c-52b1-90fc-16d7cf9a86d6
  slug: late-bread-4076
  revision: 0
  pushed_at: '2026-08-09T21:26:19+00:00'
  content_sha256: ce6d72e91c53f9272ed7f8a3969a53ea3d2921b8b00958fef20844aae9175d88
---
# Honest dynamically-feasible oracle (empirical / measurement node, RESOLVED — GREEN)

## Lineage (DAG merge)
- **builds-on:** `e4a66478` (tp=0.05 GREEN baseline, best_lap ~3.13–3.19s) — the validated policy this instruments.
- **informed-by:** `5fcc1b12` (hop-3 RED / saturation) — its finding (reward-weight tuning saturated; the old oracle beaten) is *why* this hop re-instates a real yardstick instead of tuning reward weights again.

## What was built
`neural_whoop/oracle.py` — a pure, batched, GPU-resident timing oracle over the closed gate loop `g0->..->g_{n-1}->g0`, with two models behind `GateRaceConfig.oracle_model`:
- **pathlen** (default, baseline-reproducing): closed path length ÷ `v_ref`. Geometry-blind, speed-neutral.
- **feasible** (honest): the classic time-optimal speed profile along the fixed polygonal path — a top speed `v_max`, a tangential accel/brake limit `a_max` (trapezoidal forward+backward passes around the ring), and a **cornering cap** `v_corner = sqrt(a_lat·R)` with `R` from a junction-deviation model `R = corner_dev·cos(θ/2)/(1−cos(θ/2))` (straight-through → no cap; reversal → stop). +7 unit tests (geometry, the >=path-length/v_max invariant, sharper-corners-cost-more, lower-limits-slower); 46 total green; env_check green.

**Calibration (grounded, not invented).** Limits are p95 of the tp=0.05 baseline *flown* replay telemetry (`runs/gate_race_tp005/viz/replay.json.gz`, 4 heroes): speed mean 4.1 / p95 6.9 / max 9.2 m/s; |a_tang| p95 25; |a_lat| p95 23 (~2.5g sustained, ~4g peak). So `FeasibleOracle(v_max=7, a_max=25, a_lat=23, corner_dev=gate_radius=0.45)` — speeds/accels the policy ALREADY hits transiently.

## Result (seed-12345 eval courses, 2048 envs, DR-off — the canonical course set)
| reference | lap time (mean) | vs flown |
|---|---|---|
| path-length oracle (old) | 3.498 s | policy beats it by 8.9% |
| **flown policy (tp=0.05)** | **3.185 s** | — |
| **feasible oracle (honest)** | **2.324 s** | **policy is 37% slower; speed_factor 0.73** |

## Verdict: GREEN — yardstick re-instated, hypothesis confirmed
The honest oracle yields a target the policy does **not** beat: `speed_factor` collapses from ~1.1 (vs the old oracle) to **0.73** (vs feasible). The old path-length oracle was a floor, not a ceiling — it used `v_ref=4.0`, the *mean* flown speed, so any policy that bursts above 4 m/s 'beats' it. The decisive frontier signal: **~37% lap-time headroom remains**. The headroom is grounded — the oracle assumes only speeds/accels the policy already reaches in bursts; the policy simply fails to **sustain** them (it cruises near the 4 m/s mean on straights rather than the 7 m/s it is capable of). Caveat: the feasible oracle is an idealized point-mass flying the polygon vertices, so 2.32s is an optimistic lower bound on lap time; the *achievable* gap is smaller than 37% but clearly non-zero — racing is **not** solved.

## Action taken
Committed `oracle.py` + tests + the `oracle_model` flag at **df93a29** (default `pathlen`, so the baseline config and the lap-bonus `speed_factor` are unchanged; the feasible oracle is opt-in and reported in metrics). This is validated tooling (GREEN), so — unlike the refuted hops 2/3 — the code is kept, not reverted.

## Artifacts
hop4_oracle.json (oracle distributions + headroom math); oracle_yardstick.png (the three references + per-course oracle histograms). No new rollout/replay pack: the policy is unchanged from the builds-on parent `e4a66478`, which already carries the standard visual pack; this hop measures that same policy against a new reference.

## Stop reason: improved (measurement — re-instated the optimality yardstick)

## Next frontier (replan — n=1 from here, bench branch selected)
Flown ≫ honest oracle, so the staged bench selects the **speed/algorithm** branch (not the pivot-to-swarm branch). The policy leaves ~37% on the table by under-cruising straights. Candidate hop-5 directions: (a) **DiffAero SHAC/BPTT vs PPO at equal wall-clock** — a differentiable-dynamics optimizer may find the faster sustained-speed regime PPO's exploration misses; (b) a **sustain-speed lever** — e.g. switch the lap-bonus/eval yardstick to the feasible oracle (now that it is honest, `speed_factor` has real gradient up to 0.73) or add a straight-segment speed target; (c) **curriculum** toward higher v_max. Recommend (a) as the highest-information next hop given reward-weight tuning is already saturated.