---
node_id: 7a7e6be5-4094-557f-a26e-a04f4cfc7c7d
slug: aged-term-6809
title: 'Reliability-weighted reward (near-miss penalty): SAFER but SLOWER, DR-on completion FLAT — NO-GO'
created_at: '2026-06-26T18:05:52.574016+00:00'
parents:
- shrill-limit-5398
- noisy-disk-9080
summary: 'RESOLVED no-go (stop_reason=no-effect on the primary metric + speed regression). Added a near-miss reward (boundary_proximity_penalty: per-step penalty ramping 0->weight in the last 0.4m before any crash bound) to close the hop-9 DR-on reliability gap. It made the policy SAFER -- DR-off crash 1.7e-4->6.4e-5 (~2.6x fewer), DR-off completion 0.919->0.959, DR-on crash 4.6e-4->3.9e-4 -- but did NOT lift the PRIMARY metric (DR-on completion 0.804->0.808, flat) and cost ~8.5% DR-off / ~10% DR-on speed (best_lap 2.60->2.82 / 2.67->2.93s), violating the <=5% guardrail. Fails the GREEN bar -> not promoted. KEY INSIGHT: DR-on non-completion is NOT simply crash-limited; cutting crashes trades speed and nets flat completion, so the residual gap is as much timeouts/missed-gates under latency+wind as crashes. Baseline unchanged; the penalty kept as a default-off tested reward primitive (committed 3ed796b).'
origin:
  backend: flywheel
  node_id: 7a7e6be5-4094-557f-a26e-a04f4cfc7c7d
  slug: aged-term-6809
  revision: 24
  exported_at: '2026-08-09T18:23:28+00:00'
---
# Hop-11 — reliability-weighted reward (near-miss boundary penalty) (RESOLVED, NO-GO)

## Lineage
- **builds-on:** `8db85abb` (hop-8, [128,128]@120M baseline, full DR from step 0).
- **informed-by:** `fe78365c` (hop-10) — the DR-**curriculum** reliability lever was refuted; this hop tries a mechanistically *different* lever (reward shaping, not schedule) against the same binding constraint (DR-on completion ~0.80).

## Hypothesis
Under DR, wind/latency push the drone toward the walls/floor/ceiling and those excursions become crashes. A **near-miss penalty** that taxes the approach to a crash bound should teach the policy to keep margin and survive DR — lifting DR-on completion toward the DR-off 0.92, trading a little speed.

## Mechanism (committed 3ed796b, default-off)
`reward.boundary_proximity_penalty(pos, bounds, margin, weight)`: a per-step penalty that ramps `0 -> weight` per axis as the drone enters the last `margin` meters before any crash bound (summed over x/y/z). The 0.4 m band sits **below the lowest gate** (z 0.7), so normal flight is untouched — only genuine danger-zone excursions are taxed. Wired into `gate_race` via `boundary_penalty`/`boundary_margin` (default **0.0** = baseline unchanged); experiment used `boundary_penalty=1.0`. 5 new unit tests (no-op at weight 0, untaxed normal flight, monotone in the band, sums at a corner).

## What was run (boundary_penalty=1.0; [128,128]@120M full-DR, 3 seeds; eval 2048x1500 seed 12345)
| metric | reliability reward (n=3) | baseline (hop-8/9) | Δ |
|---|---|---|---|
| **DR-on completion** (primary) | **0.808** | **0.804** | **flat** |
| DR-on crash/step | 3.9e-4 | 4.6e-4 | slightly fewer |
| **DR-on best_lap** | 2.926 s | 2.665 s | **~10% slower** |
| DR-off completion | **0.959** | 0.919 | **+4 pp (safer)** |
| DR-off crash/step | 6.4e-5 | 1.7e-4 | **~2.6x fewer** |
| **DR-off best_lap** | 2.822 s | 2.600 s | **~8.5% slower** |

## Verdict: NO-GO — safer, but the primary metric didn't move and the speed guardrail broke
The penalty does exactly what it should *mechanically*: the policy flies with more margin and **crashes much less** (DR-off crash ~2.6x fewer; DR-off completion up to 0.96). But it **fails the GREEN bar on both counts**: (1) the **primary** metric, **DR-on completion, is flat (0.804 -> 0.808)**; (2) it costs **~8.5–10% speed**, well past the ≤ 5% guardrail.

**Key insight (reframes the reliability gap):** DR-on non-completion is **not simply crash-limited**. Reducing crashes trades speed (the margin-keeping policy flies slower) and under full DR the two effects roughly cancel, leaving completion flat. So the residual DR-on gap (0.92 DR-off -> 0.80 DR-on) is **as much timeouts / missed-gates under latency+wind as it is crashes** — a safety-shaping reward cannot close it. Two reliability levers (curriculum hop-10, reward hop-11) have now failed to lift DR-on completion; the remaining untried lever is one that adds *information* (latency-aware / obs-history), not one that reshapes incentives.

## Action taken
**Do NOT promote** (fails the GREEN bar). Baseline `configs/gate_race.yaml` unchanged (`boundary_penalty` stays 0.0). The **`boundary_proximity_penalty` primitive is kept** — small, default-off, tested, a reusable reward building block (reward.py composes such primitives; env_check + 55 pytest green). `configs/gate_race_relreward.yaml` retained as the reproducible recipe (header marked NO-GO). Committed **3ed796b**.

## Artifacts
`hop11_summary.json` (reliability-reward vs baseline, per-seed DR-on/DR-off); DR-on trajectory of the best seed (s0, 2.75s/0.832); comparison vs the baseline DR-on replay; DR-on s0 eval json; per-run leaderboard table.json; portable DR-on replay. No training_curves (runs trained render-free).

## Stop reason: no-effect (primary DR-on completion flat; speed regressed)

## Next frontier (replan — n=1)
Two reliability levers have now failed to lift DR-on completion (curriculum RED hop-10, reward no-go hop-11), and hop-11 shows the gap is **not** crash-limited. Continuations: (a) **latency-aware / obs-history policy** — the one remaining lever that adds *information* rather than reshaping reward: stack the last k observations (or add an explicit latency token) so the policy can compensate for the action-latency-1 seam hop-9 flagged; this directly targets the timeout/missed-gate failure mode, at a small MCU deploy-size cost (watch the flag). (b) **PIVOT to the first n_agents>1 SWARM task** — the core objective expansion (novel/creative policies, swarms); racing is otherwise excellent (2.60s, near the feasible floor, DR-off 0.92–0.96) and the reliability gap is now well-characterized; accept DR-on 0.80 as good-enough for now. **Recommend a human steer here**: (a) keeps mining a hard, well-understood reliability gap with the last sensible single-drone lever; (b) opens the larger, higher-novelty swarm frontier. Deprioritized: width knee; DiffAero SHAC/BPTT (reserved).