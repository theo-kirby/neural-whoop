---
node_id: 62c23ace-8a9f-5dec-8240-920d4530e543
slug: patient-limit-7117
title: 'Hypothesis: the tracked flip''s 0.448 m position error is a VANISHING REWARD GRADIENT, not missing control authority — widen the position bell and it drops below 0.30 m'
created_at: '2026-08-01T12:59:51.649420+00:00'
parents:
- calm-fog-9257
summary: 'At the measured pos_err 0.448 m the position bell exp(-(err/0.25)^2) returns ~0.040, ~2% of maximum, with an even smaller derivative — so the policy sits where moving toward the reference buys nothing while the attitude/rate bells still pay. Predicts the observed SHAPE of the failure (under-does the pop, peak_climb 0.212 vs 0.680, flies flatter rather than tracking a wrong path). Competing explanation with real support: through the coast the throttle is floored at 0.25 and the airframe is inverted, so lateral error genuinely cannot be corrected until CATCH — in which case no reshaping helps. Test: pos_sigma 0.25->0.60, bell+linear term, and a second seed as control (0.448 is currently single-seed and its noise is unmeasured). UNTESTED.'
origin:
  backend: flywheel
  node_id: 62c23ace-8a9f-5dec-8240-920d4530e543
  slug: patient-limit-7117
  revision: 1
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 08bbd35b-6359-5948-aab2-5cae6b6eb9b9
  slug: icy-butterfly-7090
  revision: 0
  pushed_at: '2026-08-09T21:28:32+00:00'
  content_sha256: dd961cfbc548b5489705208b0c5b3b8071bc42dafcb7a129878d49a8aa8b1815
---
## Hypothesis

**The tracked flip's position error is limited by a vanishing reward gradient, not by control
authority — and widening the position bell (or adding a term that never saturates) will reduce
`pos_err_m` below 0.30 m without hurting `att_err_deg`.**

## The argument

`calm-fog-9257` measured the tracked flip at `pos_err_m` **0.448** while `att_err_deg` reached
12.77 and the swing hit 1.78. The position reward is

```
pos_scale * exp(-(err / pos_sigma)^2),   pos_scale = 2.0, pos_sigma = 0.25 m
```

At the measured 0.448 m that term returns `exp(-(0.448/0.25)^2) = exp(-3.21) ~= 0.040` — about **2%
of its maximum**, and its *derivative* is smaller still. So the policy sits in a region where moving
toward the reference buys almost nothing, while the attitude and rate bells (which it can satisfy
directly through CTBR) are still paying. The optimizer is behaving correctly; the reward has simply
gone flat exactly where the policy lives.

This predicts the observed *shape* of the failure, which is the part worth testing: the flip
under-does the pop (`peak_climb` 0.212 m vs the reference's 0.680 m) and flies flatter than
authored, rather than tracking a wrong trajectory badly. A saturated position term is indifferent to
0.45 m vs 0.68 m of climb; the attitude term is not.

## Why it is not obviously true

There is a competing explanation with real support, and the experiment has to separate them:
**through the coast the throttle is floored at 0.25 and the airframe is inverted, so lateral
position error genuinely cannot be corrected until `CATCH`.** If that dominates, no reward reshaping
helps and the honest conclusion is that the deployable flip has an irreducible position error. The
swing and orbit — both fully powered, both tracking far better — are consistent with either story.

## Proposed test

Three arms off `calm-fog-9257`, same 300 M budget, same seed:

1. `pos_sigma` 0.25 -> 0.60 (bell still saturates, but not until ~3x further out).
2. Bell + a small **linear** term `-k*err` so the gradient never dies.
3. Control: unchanged reward, second seed — to establish that 0.448 is not seed noise, which is
   currently **unmeasured** (all three results are single-seed).

Discriminator: if arm 1 or 2 moves `pos_err_m` materially while `att_err_deg` holds, the gradient
explanation stands. If all three land near 0.448, the coast-authority explanation stands and the
next lever is the maneuver's authoring (a counter-lean before the pop), not its reward.

## Lineage

Directly from the flip arm of `calm-fog-9257`. Untested — recorded as a prediction with its
falsifier rather than quietly applied, so the result means something either way.
