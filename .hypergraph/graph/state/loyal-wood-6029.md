---
node_id: d109d91b-ceaf-5aad-82b4-37f175488e09
slug: loyal-wood-6029
title: 'Agility: reward-shaped flip discovery is refuted; tracking a hand-authored reference works for two maneuvers of three'
created_at: '2026-08-09T18:42:32+00:00'
parents:
- cold-pebble-7468
summary: acro_flip v1 is GREEN on both axes and has flown once for real. v2 is RED as an exploration failure, which is the direct argument for reference_track. Tracking the authored swing and orbit is GREEN; the tracked flip is RED, and a control seed showed every single-seed result in this line carries an error bar wide enough to flip crash/survive.
---
Status: open

## Current

Two approaches to the same capability [rec: calm-fog-9257], and the second exists because the first
failed.

**Reward-shaped discovery.** `acro_flip` v1 is GREEN on both axes — roll
flip_success_rate 0.845, pitch 0.840, crash 0.000, a clean axis ablation
[rec: shiny-violet-1747] [rec: cold-leaf-0762]. It has flown for real once: a full 366
degree roll with recovery and landing, one of six attempts, with three stalls parked
inverted at idle throttle [rec: soft-sky-1694].

**Hand-authored references.** `reference/` authors a maneuver by hand,
deterministically, deriving every physical quantity rather than guessing it — pure
numpy, no torch and no simulator. Three maneuvers needed three different authoring
mechanisms, and that is the result: differential flatness cannot author the flip
(inversion would demand negative thrust) so its commands are authored and closed with
a damped Newton shoot to residuals about 1e-8; the swing closes on its own start
point at machine precision and needs no shoot at all; the orbit is the first
genuinely 3D maneuver and breaks the yaw-identically-zero assumption
[rec: sparkling-shadow-0034] [rec: ancient-river-4144].

**Tracking them.** `reference_track` grades a policy against the authored table, so
the shaping problem moves out of the reward and into the authoring where it is
algebra with a closed form. Over the maneuver window: **swing 0.114 m / 1.92 degrees
GREEN**, **orbit 0.172 m / 6.82 degrees GREEN — the lab's first non-planar policy**,
flip 0.455 m / 12.73 degrees RED [rec: calm-fog-9257]. The ordering was predicted by
the reference package's own authoring numbers.

**Open and named** [rec: square-art-3812]**:** phase-weighted RSI. With `rsi_frac 0.8`, 80% of episodes start
placed mid-maneuver and never have to generate the pop, and the pop is about 10 of
110 steps. Oversampling the early phases is the obvious next experiment and is
untested (`docs/TASK_CATALOG.md`).

## Negative knowledge

- [scope: describing a maneuver's shape in reward penalty terms | confidence: high | evidence: lucky-wind-7057] acro_flip v2 is RED and does not learn the flip at all: flip_success_rate 0.000 final against v1's 0.845, having never attempted the maneuver. The cause is structural, not a tuning miss — `lat_scale` and `sink_scale` make 'sit at the spawn point collecting alive_bonus' a strong local optimum, and a policy that never inverts never discovers the far side pays. This is an EXPLORATION failure, so re-weighting is not guaranteed to fix it. It is the direct argument for tracking an authored reference instead.
- [scope: the tracked flip's position reward | confidence: high | evidence: square-art-3812] The pre-registered position-gradient hypothesis is largely refuted by its own falsifier. No arm gets near the authored 3.80 pop or the 0.680 m apex (all 2.17-2.86 against a 4.0 ceiling), so the position gradient is not what limits the flip's shape. The flip is UNWILLING to pop rather than unable — it uses about half the authority it has.
- [scope: every single-seed reference_track result, including the two GREENs | confidence: high | evidence: square-art-3812] The control arm is the finding: the parent config at seed 1 survives where seed 0 crashed, so v1's crash was seed variance and not the reward. Every single-seed result in this line therefore carries an unmeasured error bar wide enough to flip crash/survive, and v2's win is smaller than the spread between two parent seeds.
- [scope: acro_flip v2's pop_allow setting | confidence: high | evidence: lucky-wind-7057] `pop_allow: 0.4` contradicts the reference's own measured `peak_climb` of 0.617 m (0.680 deployable) — the shape the docs say we want collects a rise penalty under this reward. Flagged, not changed, because raising it is a training decision.

## Provenance

- shiny-violet-1747 — the first agility task, GREEN from pure reward-shaped discovery
- cold-leaf-0762 — the roll-to-pitch axis ablation
- soft-sky-1694 — the first real blind flip, and its three inverted stalls
- sparkling-shadow-0034 — the first hand-authored reference maneuver
- ancient-river-4144 — the second and third, and why three mechanisms were needed
- lucky-wind-7057 — acro_flip v2 trained and RED, with the exploration-failure attribution
- calm-fog-9257 — the first reference_track results across all three maneuvers
- square-art-3812 — the position-gradient refutation and the control seed
