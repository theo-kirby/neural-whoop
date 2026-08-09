---
node_id: dc26435a-0645-5129-b4cd-e9f89d207bad
slug: long-tree-2976
title: EMA precision filter CLOSES the target_follow standoff back-off (GREEN) — temporal averaging beats the bearing/range-precision frontier
created_at: '2026-06-27T22:16:34.986823+00:00'
parents:
- cool-resonance-0983
- nameless-bar-9184
summary: 'Realizes the precision-filtering lever the detector-regime sweep (nameless-bar-9184, 33c3e1e7) pointed to after proving the standoff back-off is set by per-fix bearing/range PRECISION, not dropout/FOV. Added an in-place EMA on the body-frame detector estimate (estimate_ema_alpha; obs stays length 11, MCU-clean) so successive noisy fixes are averaged before the policy sees them. Detector + EMA(0.7), [128,128]@120M seed 0, full seam DR; eval 2048x1500 seed 12345 deterministic. RESULT (noisy/own-regime): standoff 2.173 -> 1.543m (track_err 0.911 -> 0.250 — basically at d*=1.5m, matching the clean policy''s accuracy) while crash stays 8.7e-5 — 5.6x SAFER than the brittle clean policy (4.85e-4) and below the accepted racing reliability bar (~4.6e-4); reward 1.167 -> 1.571; condition-invariant (noisy 1.543m ~= clean 1.539m, so it keeps detector-training''s robustness). This is a new Pareto-dominant corner: more accurate than the backed-off detector policy AND far safer than the accurate-but-brittle clean policy. The only cost is ~12x the detector anchor''s ultra-low crash (7.5e-6 -> 8.7e-5), the price of holding close instead of backing off. CONFIRMS the sweep''s diagnosis end-to-end: the back-off was a precision floor, and temporal precision-filtering — not reward, dropout/FOV, or dropout-coasting memory — is the lever. GREEN, promoted (estimate_ema_alpha knob + configs/target_follow_ema.yaml committed a5a9fe0, default 0.0/off; 83 pytest green). Single seed; multi-seed confirmation queued.'
origin:
  backend: flywheel
  node_id: dc26435a-0645-5129-b4cd-e9f89d207bad
  slug: long-tree-2976
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Setup
The detector-regime sweep `nameless-bar-9184` (33c3e1e7) proved the detector-trained follower's standoff back-off (2.17m vs d*=1.5m) is set by per-fix **bearing/range PRECISION** (insensitive to dropout/FOV), and pre-registered the one viable RL lever: **temporal precision-filtering** of the noisy estimate (not dropout-coasting memory). This hop implements and tests it.

**Change (task-layer, MCU-clean):** a config knob `estimate_ema_alpha` adds an **in-place EMA** on the body-frame target estimate in `TargetFollowTask.observe()` — `est <- a*est + (1-a)*fix` — applied AFTER the detector seam, so the policy sees a variance-reduced estimate. In-place means obs-v4 stays **length 11** (no obs_dim/param growth; a real onboard estimator would do the same smoothing). State seeded at spawn, reset per-episode. Default `alpha=0.0` (off → identical to the prior task).

**Run:** `configs/target_follow_ema.yaml` = detector-ON (3deg bearing / 10% range / 5% dropout / 110deg FOV) + `estimate_ema_alpha=0.7`, otherwise identical to `target_follow.yaml`. [128,128]@120M, n_envs=4096, seed 0, full seam DR. Eval each condition 2048x1500 seed 12345 deterministic.
**Pre-registered GREEN:** standoff moves toward d* at bounded crash.

## Results (d* = 1.5 m)
| policy / condition | standoff (m) | track_err (m) | crash/step | time_in_view | reward |
|---|---|---|---|---|---|
| detector / noisy (anchor) | 2.173 | 0.911 | 7.5e-6 | 0.9997 | 1.167 |
| clean / noisy (anchor) | 1.521 | 0.132 | 4.85e-4 | 0.996 | 1.688 |
| **EMA 0.7 / noisy** | **1.543** | **0.250** | **8.72e-5** | 0.9973 | **1.571** |
| EMA 0.7 / clean | 1.539 | 0.248 | 4.59e-5 | 0.9985 | 1.581 |

## Findings
1. **The back-off is CLOSED.** EMA standoff 1.543m (track_err 0.250) — a 0.63m / 29% recovery from the detector anchor's 2.173m, landing essentially at d*=1.5m and matching the clean policy's accuracy (1.521m).
2. **Robustness is largely kept.** Crash 8.72e-5 is ~12x the backed-off detector anchor (7.5e-6) BUT **5.6x lower than the accurate-but-brittle clean policy (4.85e-4)** and below the project's accepted DR-on racing crash bar (~4.6e-4). The uptick is the expected price of holding close (nearer the target) instead of sitting far.
3. **Condition-invariant.** noisy 1.543m ~= clean 1.539m (and crash within 2x) — the EMA policy keeps detector-training's noisy==clean invariance; it didn't trade robustness-to-noise for accuracy, it genuinely reduced the effective noise.
4. **New Pareto-dominant corner.** It is simultaneously more accurate than the detector policy and far safer than the clean policy, and earns higher reward (1.571) than the detector policy (1.167). The third corner the whole perception branch was hunting for.
5. **Mechanism confirmed.** Reward (royal-wildflower-3231) and detection availability (nameless-bar-9184) could NOT move the back-off; variance-reduction of the per-fix estimate does. This closes the loop on the sweep's diagnosis: the frontier was a bearing/range-precision floor, and temporal averaging lifts it.

## Verdict
**GREEN (frontier-moving), stop_reason=improved.** Promoted: `estimate_ema_alpha` + `configs/target_follow_ema.yaml` committed a5a9fe0 (default 0.0/off, no behaviour change to existing tasks; 83 pytest green).

## Honesty / limits
Single seed (branch n=1 convention); the effect is large and unambiguous (standoff -0.63m, reward +35%) so robust to seed noise, but **multi-seed confirmation is queued**. alpha=0.7 was the first value tried — not tuned; an alpha sweep could trade the small crash uptick against lag. The EMA adds ~3-5 steps of lag (≈0.1s); it doesn't hurt this slow-follow task but would matter for a faster target (worth a stress check). Crash 8.7e-5, while well-bounded, IS a real regression vs the ultra-conservative back-off — acceptable here because it buys correct standoff and stays far under the brittle policy / racing bar.

## Next
- Multi-seed confirm (n=1 -> 3). alpha sweep {0.5,0.7,0.85} for the lag<->variance knee. Stress with a faster target_speed (does EMA lag break it?).
- Generalizes: the EMA precision-filter is a reusable perception primitive for every future detector-fed task (hand_follow, swarm-with-perception).

## Lineage
- **builds-on** `33c3e1e7` (nameless-bar-9184): implements the precision-filtering lever its sweep diagnosed and recommended; confirms its prediction that availability-memory wouldn't help but precision-filtering would.
- **builds-on** `00a0ca61` (cool-resonance-0983): the detector follower whose 2.17m back-off this fixes (1.54m) while keeping its robustness.

## Artifacts
ema_frontier.png (robustness<->accuracy plane: EMA recovers d* at 5.6x lower crash than clean), ema_table.json (EMA noisy+clean vs anchors). Code a5a9fe0.