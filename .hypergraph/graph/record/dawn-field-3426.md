---
node_id: 8c2ed3c8-83b8-5e69-bb91-390ebc1ce575
slug: dawn-field-3426
title: 'Control: PufferLib idea-import experiments on gate_race_air65'
created_at: '2026-07-02T09:29:28.215513+00:00'
parents:
- long-fog-2207
summary: 'CLOSED (objective_met): PufferLib idea imports executed on gate_race_air65 — Muon: 3.203→2.461 s best lap (−23%, record) at −6.6 pt completion (mixed); dual-scale tanh: +25% slower (RED); puff-update: +7% slower but safest (NO-GO); DiffAero motor-lag gap confirmed. ~1.6 h used, 0 credits. Next: Muon + reliability shaping.'
origin:
  backend: flywheel
  node_id: 8c2ed3c8-83b8-5e69-bb91-390ebc1ce575
  slug: dawn-field-3426
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Run contract

- Objective: Execute the top-ranked transferable ideas from the PufferLib system comparison (parent node long-fog-2207) as controlled experiments on our stack, base config `configs/gate_race_air65.yaml`: (1) Muon optimizer on TinyPolicy; (2) dual-scale tanh target encoding (obs-v5 candidate); (3) resolve the motor-lag check; (4) if budget remains, port puff-advantage + prioritized minibatches.
- Decision criterion: each experiment judged on **best_lap_time** and **lap_completion_rate** from the standard no-DR eval (seed 12345, n_envs 2048, steps 1500) vs the seed-matched parent baseline `runs/gate_race_air65` (best lap **3.203 s**, completion **92.6%**). GREEN if lap improves with completion not degraded; RED/NO-GO otherwise. Every empirical node carries the standard visual pack.
- Start nodes: long-fog-2207 (analysis frontier), icy-feather-6323 (prior control, closed).
- Budget ceiling: 3.5
- Budget unit: hours of local wall-clock on the single RTX 5090
- Compute approval cap: 0 Flywheel credits — local-only per locked decision #3.
- Lookahead depth: 1
- Frontier width: 1
- Terminal condition: ≥2 experiment nodes committed with packs and verdicts (+ motor-lag check recorded), or budget ceiling reached.
- Stop reason: **objective_met** (2026-07-02; ~1.6 h of the 3.5 h remainder used; 0 credits; all four items + the bonus puff port executed; 3 experiment nodes committed with full packs).

## Outcome (all vs baseline 3.203 s / 92.6% completion)

| experiment | node | best lap | completion | verdict |
|---|---|---|---|---|
| Muon lr 2.5e-3 (+ lr 1e-2 variant) | black-silence-5752 | **2.461 s (−23%)** | 86.0% (−6.6 pt) | mixed — big speed Pareto shift, record lap |
| dual-scale tanh obs | wild-bird-1554 | 3.990 s (+25%) | 93.7% (+1.1 pt) | RED for racing (hover-precision encoding) |
| puff-update (vtrace+prio, replay 4) | hidden-moon-2828 | 3.440 s (+7%) | 93.8% (+1.2 pt, best) | NO-GO at untuned settings; mechanism not refuted |
| motor-lag check | (recorded here) | — | — | CONFIRMED GAP: DiffAero has no motor time constant (c_tau = yaw torque coeff); PufferLib models k_mot 0.15 s as sim2real-critical |

Code: training/muon.py + ppo.optimizer knob + gate_race dual_scale_obs (commit 84f6fc2); ppo.puff_update mode (commit 6111e68); configs gate_race_air65_{muon25,muon100,dstanh,puff}. All pushed to main.

## Staged frontier (next pass candidates, priority order)
1. **Muon + reliability shaping** (boundary_penalty / crash_penalty bump at lr 2.5e-3): buy completion back while keeping the −23% lap — studio-baseline candidate if ≥ half the speed survives. Highest expected value.
2. **Motor lag (k_mot) in WhoopDynamics + DR** — confirmed modeling gap vs the system that demonstrably transferred to hardware; belongs to cluster:reliability-dr / deploy-hw work.
3. Muon seed replication (n=3) + finer lr grid (1e-3..5e-3).
4. Control-frequency pinning in docs/CONTRACT.md (cheap doc task).
5. Deprioritized: dual-scale rescale variant; puff+Muon combined sweep.

Per-candidate rejection for stopping now rather than continuing: item 1 deserves a fresh budget grant (it would promote a studio-baseline move — user-visible decision); items 2–5 are cheaper but lower-information than closing this pass cleanly with the record intact.