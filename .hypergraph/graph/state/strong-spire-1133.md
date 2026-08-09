---
node_id: bb72f994-57b7-5964-a0f0-cc9c199d6019
slug: strong-spire-1133
title: 'Perception-in-the-loop following: the EMA precision filter is the reusable primitive'
created_at: '2026-08-09T18:42:32+00:00'
parents:
- cold-pebble-7468
summary: 'Four follow tasks, all landed. The single durable result is an EMA on the noisy body-frame estimate, alpha 0.85: it closes the detector standoff back-off, is Pareto-dominant over the brittle clean policy, and generalises to abrupt motion. Its envelope is measured and it vanishes at about 4.5 m/s.'
---
Status: working

## Current

Training feeds the policy a ground-truth body-frame target vector from an
`OracleEstimator`, optionally corrupted by a batched `DetectorNoise` model
(bearing, range, FOV, dropout, with stale-hold on a miss), so a policy survives real
detection noise without rendering a pixel [rec: tight-limit-5820] [rec: little-feather-5786].
Four tasks ride that seam: `target_follow`, `hand_follow`, `gesture_follow` and
`command_follow` [rec: cool-resonance-0983] [rec: cold-sky-6425] [rec: proud-field-5681] [rec: small-art-6235].

**The primitive.** An in-place exponential moving average on the body-frame estimate
(`estimate_ema_alpha`; the observation stays 11-wide and MCU-clean) takes standoff
from 2.17 m back to 1.54 m against a 1.5 m target, track error 0.91 to 0.25, at a
crash rate 5.6x safer than the brittle clean policy — a Pareto-dominant corner, both
accurate and robust [rec: long-tree-2976]. The alpha sweep found a threshold rather
than a slope: **0.85 is the robust operating point** (both seeds hold), 0.7 is
seed-fragile, and the original single-seed GREEN sat on the knife edge
[rec: flat-waterfall-0121].

It generalises. On `hand_follow`'s abrupt zigzag motion the EMA recovers hold from
0.630 to 0.985 [rec: cold-sky-6425], and `gesture_follow` is the lab's first
command-conditioned policy: stop compliance 0.947 with the safest crash rate in the
catalogue [rec: proud-field-5681].

## Negative knowledge

- [scope: the detector standoff back-off | confidence: high | evidence: royal-wildflower-3231, nameless-bar-9184] Tightening the standoff reward is refuted: it moved standoff 2.17 to 1.97 m only by spending about 8x the crash robustness. The regime sweep then localised the cause — holding the reward identical while sweeping dropout and FOV leaves standoff flat at 2.2-2.5 m, so the back-off is insensitive to detection *availability* and is driven by per-fix bearing and range *precision*. It is a genuine robustness-versus-accuracy frontier, not a reward artifact.
- [scope: temporal filtering beyond an EMA | confidence: high | evidence: autumn-cherry-1696, old-pond-5686] A predictive alpha-beta filter and a world-frame predictive filter both lose to the plain EMA. Body-frame velocity tracking is ill-posed here. The filtering thread is closed: simple temporal filtering tops out at the EMA.
- [scope: the EMA's speed envelope | confidence: high | evidence: rapid-union-8239] The EMA's benefit on abrupt motion decays with target speed and vanishes at about 4.5 m/s. It is an operating envelope, not a universal win.
- [scope: command vocabulary size on a 128x128 net | confidence: high | evidence: small-art-6235] The command channel scales to three commands — the policy demonstrably reads it — but per-command precision degrades badly (stop 0.95 to 0.70, follow 0.58 to 0.25-0.31). Capacity splits three ways and re-acquisition transients compound.

## Provenance

- cool-resonance-0983 — the first detector-hardening result and the back-off it exposed
- royal-wildflower-3231 — the tighter-standoff reward, refuted
- nameless-bar-9184 — the detector-regime sweep that localised precision as the driver
- long-tree-2976 — the EMA primitive and its Pareto-dominant numbers
- flat-waterfall-0121 — the alpha threshold and the seed-fragility of the original result
- cold-sky-6425 — generalisation to abrupt motion
- rapid-union-8239 — the measured speed envelope
- proud-field-5681 — the first command-conditioned policy
- small-art-6235 — how the command channel scales and degrades
