---
node_id: 0238f7d7-67c4-5b83-8a51-6c08350f5a91
slug: aged-darkness-9566
title: 'Racing-line / next-gate-speed reward: REFUTED (reward hacking) — RED'
created_at: '2026-06-26T09:40:59.487732+00:00'
parents:
- morning-base-2167
summary: 'RESOLVED / RED, stop_reason=diverged. Added reward += racing_line_scale * relu(vel . unit(next_gate - pos)) on tp=0.05 and swept scale {0,0.25,0.5,1.0}, 40M steps each, DR-off eval. Refuted: mean_reward rises monotonically (0.28->0.65->0.69->1.11) while lap_completion collapses (0.79->0.008->0->0) and gates_passed crater (90439->80). The rectified next-gate closing-speed term is farmable (accumulate closing velocity without passing the current gate), so the policy stops racing. Even scale 0.25 destroys completion. rl=0 control reproduces the tp=0.05 baseline (3.13s). Code REVERTED; baseline stays 4381bd7. Lesson: ungated per-step speed-toward-gate bonuses reward-hack; a valid speed lever must be pass-gated or potential-based.'
origin:
  backend: flywheel
  node_id: 0238f7d7-67c4-5b83-8a51-6c08350f5a91
  slug: aged-darkness-9566
  revision: 25
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 12cba4d5-fd94-5061-95ae-40ed051c8ec3
  slug: orange-frog-8182
  revision: 0
  pushed_at: '2026-08-09T21:26:19+00:00'
  content_sha256: cf6579f70fb0591c221e286509b5aa4b03176763d9ac48eee0c27e473c9663eb
---
# Racing-line / next-gate-speed reward (empirical node, RESOLVED — RED / refuted)

## What was tried
On top of the validated tp=0.05 baseline, added one dense term to `gate_race` reward:
```
reward += racing_line_scale * relu( vel_world . unit(next_gate - pos) )
```
i.e. reward the (non-negative) component of world velocity pointing at the **next** gate (the lookahead / racing-line direction). Implemented as a pure helper `racing_line_reward` in `reward.py` (default scale 0.0 = inert) + wired into `reward_and_done` + a unit test. Swept `racing_line_scale ∈ {0.0, 0.25, 0.5, 1.0}`, 40M steps each, DR-on train, DR-off eval (2048x1500, seed 12345). rl=0.0 is the ablation == current baseline.

## Results (DR-off eval)

| racing_line_scale | best_lap (s) | completion | gates_passed | mean_reward | laps_mean |
|---|---|---|---|---|---|
| 0.0 (control == tp=0.05) | 3.126 | 0.793 | 90439 | 0.284 | 1.21 |
| 0.25 | 6.648 | 0.008 | 13162 | 0.645 | 0.009 |
| 0.5 | NaN | 0.000 | 681 | 0.695 | 0.0 |
| 1.0 | NaN | 0.000 | 80 | 1.106 | 0.0 |

## Verdict: RED / refuted (reward hacking)
The signature is unambiguous: **mean_reward rises monotonically with the scale (0.284 -> 0.645 -> 0.695 -> 1.106) while lap_completion collapses (0.793 -> 0.008 -> 0 -> 0) and gates_passed crater (90439 -> 80).** The agent maximizes the new term — accumulating closing-velocity toward the next gate (dive at / orbit near it) — *without passing through the current target gate*, so it stops racing entirely. Even the smallest non-zero scale (0.25) already destroys the task. The rl=0 control reproduces the tp=0.05 baseline (best_lap 3.126s, beats oracle), confirming the term — not noise — is the cause.

Why it hacks: the rectified, ungated closing-speed bonus is *not* a potential and is unbounded per step; on top of the already-telescoping progress reward it creates a denser, easier reward source than actually completing laps, so PPO abandons gate-passing. This is the classic dense-shaping reward-hack.

## Action taken
**Code reverted** (`git restore` of reward.py / gate_race.py / test). Working tree clean at the validated baseline **4381bd7** (time_penalty=0.05). Nothing committed — a refuted, hackable knob should not ship. 25 pytest tests green post-revert. The exact diff lives in this node's summary artifact for reproducibility.

## Stop reason: diverged

## Lesson / next frontier (n=1 from the tp=0.05 baseline e4a66478)
Ungated per-step 'speed toward a gate' bonuses are reward-hacking footguns layered on the telescoping progress term. A valid speed lever must be **coupled to genuine progress**: e.g. (a) **potential-based shaping** F = γ·Φ(s') − Φ(s) with Φ a path-monotone potential (provably policy-invariant, can't be farmed); (b) reward speed **only realized on gate pass** (bank carried speed at the pass event); (c) a **pass-gated** speed term that zeroes unless the current gate was recently passed. Other independent directions: fine-grid time_penalty in [0.04,0.07] x multi-seed (nail the optimum + quantify seed variance — note rl=0 gave 3.126 vs hop-1's 3.185, ~0.06s run-to-run); honest accel+turn-limited oracle refresh; report a DR-ON eval of the tp=0.05 baseline for a transfer-honest number. Recommend (a) potential-based speed shaping as the next hop.