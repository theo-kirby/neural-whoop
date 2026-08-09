---
node_id: 03b66510-7893-51ad-b978-2f7c34e8680c
slug: red-fire-4210
title: 'd50var_s8a (action-history obs) RED — uniform eval regression (M2-sensor 29.8→7.3%, latency-OFF 98.2→10.4%); CORRECTED mechanism: train/eval mismatch in the echo channel (sampled vs deterministic actions), not a PPO collapse. Companion probe: s8''s latency fragility is physical (29.6% under the measured link)'
created_at: '2026-07-07T01:27:10.128321+00:00'
parents:
- broken-wildflower-8398
summary: 'd50var_s8a (append_prev_action, one factor vs s8, commit c621a24) RED: uniform eval regression — M2-sensor 7.3% (s8 29.8%), latency-OFF 10.4% (s8 98.2%), M1-live@1.0x 6.9%. CORRECTED mechanism (the original ''PPO training collapse'' claim was wrong — ALL arms end at ep_ret ~200-270 / kl 0.000, incl. healthy s8): hypothesized train/eval mismatch in the echo channel — training appends SAMPLED actions, eval appends the DETERMINISTIC mean, so a policy reading the echo''s sampling statistics loses that signal exactly at deployment; fits the uniform regression across all eval configs. Fix candidate (unbudgeted): append the deterministic mean during training. Companion probe closes the metric-artifact escape: s8 under the measured-link jitter model (action_latency_dist, commit 7aeceb0) = 29.6% ~ constant hedge 29.8% — latency fragility is physical. Next: d50var_s8jit (5/6).'
origin:
  backend: flywheel
  node_id: 03b66510-7893-51ad-b978-2f7c34e8680c
  slug: red-fire-4210
  revision: 4
  exported_at: '2026-08-09T18:23:28+00:00'
---
# d50var_s8a: the right idea meets a train/eval mismatch — and the honest-link probe closes the metric-artifact escape hatch

**Hypothesis tested (broken-wildflower-8398's decode).** s8's sole residual killer is action latency, structurally unobservable because obs-5 has no action echo. Appending the last commanded action per frame (`append_prev_action`, commit c621a24) should enable predictive delay compensation → M2-sensor toward 80%.

**Setup.** `configs/hover_blind_air65_d50var_s8a.yaml` = d50var_s8 + `append_prev_action: true` (ONE factor). Frame = `[obs5, last_sent_a]`, obs_dim 72. New env seam: prev_action commits after `reward_and_done` so a frame carries the command that produced it; action channels appended after noise; ckpt meta records the flag. 5 unit tests. 3.2B steps.

**Results (30 s pure-hold survival, 2048 drones).**

| metric | s8a | s8 (parent) |
|---|---|---|
| M2-sensor@d50 | **7.3%** | 29.8% |
| M2-sensor@d50, latency OFF | **10.4%** | **98.2%** |
| M2-sensor@d50, measured jitter | 6.9% | 29.6% |
| M2-sensor@d100 | 3.4% | 18.1% |
| M1-live@1.0× | 6.9% | 99.9% |
| M1-live@2.0× | 21.4% (inverted vs 1.0×!) | 61.1% |

**⚠ CORRECTION (2026-07-07, after the s8jit run).** The original verdict blamed "PPO training collapse (final ep_ret ~200, kl 0.000 vs healthy ~1500)". That reference was WRONG: **every** arm in this recipe ends at ep_ret ~200–270 with kl 0.000 (s8 itself: 209/0.000; d50var: 251; d50: 272) — that is the full-strength-DR curriculum endgame plus target_kl throttling, normal for the recipe. s8a's training telemetry is indistinguishable from its healthy siblings; **the regression only appears at deterministic eval**. The corrected mechanism hypothesis: **train/eval distribution mismatch in the echo channel** — during training the appended actions are PPO's *sampled* (exploration-noised) actions, at eval they are the *deterministic* mean; a policy that learned to read the echo's sampling statistics (e.g. as a dither/variance cue) loses that signal exactly at deployment. This fits the uniform regression (all eval configs share the deterministic echo) better than an optimizer collapse does. Fix candidates for a future arm: append the deterministic mean action during training, or anneal exploration out of the echo — both untested, out of budget.

**Decode.**
1. **RED as trained — refutes the recipe, not the delay-compensation idea**: even the latency-OFF number collapsed (98.2→10.4%), so the damage is echo-channel-wide, not latency-specific.
2. **The metric-artifact escape hatch is closed** (probe on the PARENT s8): under the new measured-link jitter model (`action_latency_dist`, commit 7aeceb0 — per-step freshest-packet ages, monotonic latest-packet hold, weights approximating the bench p50 24 ms / p99 112 ms), s8 scores **29.6% ≈ the constant-hedge 29.8%**. The latency fragility is PHYSICAL — no honest re-metric rescues s8.
3. Inverted amplitude response (M1-live 6.9% @1.0× vs 21.4% @2.0×) marks a policy in a strange corner — consistent with the echo-statistics read (at higher noise the echo's information content changes less between train and eval).

**Verdict.** **RED**. Rejection recorded for this lever as-built; the mismatch fix (deterministic-mean echo in training) is the identified follow-up, unbudgeted this campaign. Next arm (5/6): **d50var_s8jit** (one factor: latency model — train dist == deploy dist).

**Honesty.** (1) Jitter weights approximated from three percentiles, not a histogram. (2) The correction above supersedes the original collapse claim — cite the mechanism as *hypothesized* train/eval echo mismatch, unverified. (3) n=2048, ±~1%.

**Lineage.** Parent: **broken-wildflower-8398**. Child: d50var_s8jit. The jitter seam + s8-under-jitter probe belong to this node's evidence.