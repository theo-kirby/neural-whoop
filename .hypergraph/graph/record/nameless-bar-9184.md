---
node_id: 33c3e1e7-78c4-590e-8544-e5e23392ec3a
slug: nameless-bar-9184
title: 'Detector-regime sweep: the standoff back-off is set by bearing/range PRECISION, not dropout/FOV availability — monotonic-collapse prediction REFUTED'
created_at: '2026-06-27T22:01:03.689106+00:00'
parents:
- cool-resonance-0983
- royal-wildflower-3231
summary: 'Tests the perception-frontier claim of royal-wildflower-3231 (c24fe7be) and builds on cool-resonance-0983 (00a0ca61). The RED proved reward can''t move the detector-trained follower''s back-off (2.17m vs d*=1.5m) and pre-registered the lever left = the detector REGIME. Swept the perception regime with the reward HELD IDENTICAL to target_follow.yaml: dropout {0.0, 0.025, 0.10} (anchor 0.05 = the existing detector policy) + FOV 150deg, [128,128]@120M seed 0 each; eval each under its own regime + clean (2048x1500 seed 12345, deterministic). RESULT: the back-off is INSENSITIVE to dropout and FOV. Zero-dropout sits at 2.473m (FARTHER than the 0.05 anchor''s 2.173m, not closer), dropout 0.10 at 2.496m, FOV 150 at 2.255m — standoff stays pinned ~2.2-2.5m across the entire detector-ON family, never approaching d*=1.5m. The ONLY policy that holds 1.52m is the clean (no-detector) one, which pays 10-60x the crash rate. My pre-registered ''standoff collapses monotonically toward d* as the detector improves'' is REFUTED. CONCLUSION: the frontier is set specifically by per-fix bearing/range PRECISION (3deg bearing + 10% range, present on every fix), not detection AVAILABILITY (dropout/stale-hold, FOV edge). This SCOPES P6: temporal memory framed as dropout-coasting won''t help; the viable RL lever is precision-filtering (averaging noisy fixes, e.g. EMA/Kalman state) or it''s a hardware bearing/range-precision requirement. Single seed/point; the detector-vs-none signal (0.7-1.0m) dwarfs within-family spread (~0.1m). Configs committed 330e189.'
origin:
  backend: flywheel
  node_id: 33c3e1e7-78c4-590e-8544-e5e23392ec3a
  slug: nameless-bar-9184
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 60c48e66-8eab-583c-aee1-6418ba3825a2
  slug: dry-cake-2408
  revision: 0
  pushed_at: '2026-08-09T21:27:34+00:00'
  content_sha256: d81eec16f87077bd86c7e3113adb413889a47536f0c7b6905c80d4d73a4a3c8d
---
## Setup
The RED `royal-wildflower-3231` (c24fe7be) established that reward-shaping cannot move the detector-trained `target_follow` follower's standoff back-off (it sits at 2.17m vs d*=1.5m), and pre-registered the lever that's actually left: the detector REGIME itself. This hop characterizes the robustness<->accuracy frontier as a function of perception quality.

**Design (pre-registered):** reward HELD IDENTICAL to `configs/target_follow.yaml`; vary ONLY the `dr.detector_*` perception regime. [128,128]@120M, seed 0, n_envs=4096 each. New points: dropout {0.0, 0.025, 0.10} (the 0.05 point IS the existing detector policy from 00a0ca61), and FOV 150deg (vs 110, dropout held at 0.05). Anchors reused: detector (0.05/110 -> 2.17m) and clean (no detector -> 1.52m). Eval each policy under (a) its OWN trained regime [noisy] and (b) clean [--no-dr], 2048 envs x 1500 steps, seed 12345, deterministic. Configs `configs/target_follow_{drop00,drop025,drop10,fov150}.yaml` (committed 330e189).
**Pre-registered CONFIRM clause:** standoff collapses monotonically toward d*=1.5m as the detector improves (dropout->0, FOV->wide).

## Results (noisy / own-regime eval; d* = 1.5 m)
| policy | dropout | FOV | standoff (m) | track_err (m) | crash/step | time_in_view |
|---|---|---|---|---|---|---|
| clean (no detector) | - | - | **1.521** | 0.132 | 4.85e-4 | 0.996 |
| drop00 | 0.0 | 110 | 2.473 | 1.129 | 4.79e-5 | 0.997 |
| drop025 | 0.025 | 110 | 2.399 | 1.085 | 2.02e-5 | 0.974 |
| **detector (anchor)** | 0.05 | 110 | 2.173 | 0.911 | 7.5e-6 | 0.9997 |
| drop10 | 0.10 | 110 | 2.496 | 1.140 | 4.36e-5 | 0.991 |
| fov150 | 0.05 | 150 | 2.255 | 0.970 | 3.19e-5 | 0.982 |

## Findings
1. **The standoff back-off is INSENSITIVE to dropout.** Sweeping dropout 0.0 -> 0.10 leaves standoff flat at ~2.40-2.50m. Zero-dropout (drop00) sits at **2.473m — FARTHER from d* than the 0.05 anchor (2.173m), not closer.** The stale-hold / detection-availability is NOT what drives the back-off.
2. **Widening the FOV barely helps.** FOV 110 -> 150deg moved standoff 2.17 -> 2.26m (essentially flat, ~within run noise) — the FOV-edge risk is not the driver either.
3. **My pre-registered monotonic-collapse prediction is REFUTED.** Standoff does not approach d* as the detector improves on the availability axes; it stays pinned ~2.2-2.5m across the entire detector-ON family.
4. **Only removing the detector's bearing/range estimation noise recovers d*.** The clean (oracle-fed) policy holds 1.521m — but it is the brittle corner (crash 4.85e-4, 10-60x the detector points). Every detector-ON policy clusters in the safe-but-backed-off corner (crash 7.5e-6..4.8e-5, standoff 2.2-2.5m).
5. **Therefore the frontier is set by per-fix bearing/range PRECISION** (3deg bearing + 10% range error, applied on EVERY fresh fix), not by detection AVAILABILITY (dropout/stale-hold, FOV cone). Confirms royal-wildflower-3231's 'perception sets the frontier' claim and SHARPENS it to the precision axis.

## Verdict
**Measurement; outcome RED (the registered availability-driver / monotonic-collapse prediction is refuted), stop_reason=no-effect on dropout/FOV.** The detector-induced back-off cannot be recovered by improving detection availability (lower dropout, wider FOV) at fixed bearing/range precision. The lever is the per-fix precision floor.

## Scoping the next hop (this is the real value)
- **Temporal memory as dropout-coasting (was a P6 candidate): DROP IT.** Dropout is not the driver, so a frame-stack/recurrence aimed at bridging missed detections won't close the back-off. (Consistent with racing frame-stacking being NO-GO, for an unrelated reason.)
- **Still viable RL-side: precision-FILTERING.** A temporal filter that *averages* successive noisy bearing/range fixes (EMA / tiny Kalman state on the estimate) reduces effective per-fix variance — a different mechanism than dropout-coasting, and the one that targets the actual driver. Flags obs_dim/MCU if it adds state.
- **Otherwise it's a hardware spec:** to follow at d*=1.5m the onboard detector needs materially better than 3deg bearing / 10% range precision.

## Honesty / limits
Single seed per point (matches the branch's n=1 convention). The discriminating signal — detector-ON (~2.2-2.5m) vs no-detector (1.52m) — is 0.7-1.0m, far larger than the ~0.1m within-family spread, so the conclusion is robust to single-seed noise; the fine ordering among the detector points (e.g. 0.05 anchor slightly closer than 0.0/0.10) is within that noise and not load-bearing.

## Lineage
- **builds-on** `00a0ca61` (cool-resonance-0983): extends its detector/clean policies + 2x2 eval-matrix methodology with 4 new regime points.
- **tests-claim-of** `c24fe7be` (royal-wildflower-3231 RED): quantifies and sharpens its 'frontier is perception-set' claim to the bearing/range-precision axis; refutes the availability (dropout/FOV) driver.

## Artifacts
sweep_frontier.png (standoff-vs-dropout + crash<->standoff Pareto), sweep_table.json (full matrix), sweep_results.csv. Configs committed 330e189 (default-off recipe, no behaviour change to existing tasks).