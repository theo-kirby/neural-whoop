---
node_id: e134acda-4b6a-5203-82e1-5e2376a2e425
slug: white-hat-1285
title: 'Method: reference_track — the hand-authored maneuver becomes an RL target (RSI + tracking bells), one task for flip / swing / orbit'
created_at: '2026-08-01T12:55:44.775998+00:00'
parents:
- ancient-river-4144
- lucky-wind-7057
- bitter-rain-0437
summary: 'The reference stops being only a ruler: reference/track.py resamples a reference.json onto the control step and tasks/reference_track.py grades a policy on tracking it, moving the shaping problem out of the reward and into the authoring. obs 13-wide and deploy-honest [gravity_body(3), p,q,r, maneuver_phase, gravity_body_ref(3), omega_ref(3)] — reference channels are authored (a shipped table), reference POSITION deliberately absent since a whoop has no position sensor. Reference State Initialization (rsi_frac 0.8, spawning mid-maneuver in the reference''s own state) is the load-bearing part and is what env.spawn()''s new quat= argument exists for. ONE task covers all three maneuvers because ManeuverSpec is a protocol emitting one format: 6 configs, no per-maneuver code. 19 new tests, 387 green.'
origin:
  backend: flywheel
  node_id: e134acda-4b6a-5203-82e1-5e2376a2e425
  slug: white-hat-1285
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 363767fa-99b7-535f-a8a1-88c6725313d5
  slug: mute-term-4702
  revision: 0
  pushed_at: '2026-08-09T21:28:18+00:00'
  content_sha256: b81ee166896e386c1c236ff683cf043f3c8e5f3fa1d07d5e251f358f2e742d24
---
## Idea

The reference package (`sparkling-shadow-0034`, `ancient-river-4144`) produced an exactly-derived
statement of what the drone *should* do — and, until now, **nothing read it.** The 1 kHz
`reference.json` "data artifact" had no consumer; the reference was a *ruler*, used to grade
rollouts by eye and by shared metric names. Meanwhile `lucky-wind-7057` showed the alternative
failing: describing an acro maneuver in penalty terms is an *exploration* problem, and `acro_flip`
v2's own shaping terms made hovering its optimum.

This node is the consumer: **track the maneuver instead of rediscovering it.** The shaping problem
moves out of the reward — where nobody can predict the optimum — and into the authoring, where it
is algebra with a closed form.

## Setup

**`reference/track.py`** (pure numpy, matching the rest of `reference/`): loads a `reference.json`
and resamples the maneuver window onto the env's control step. Two decisions live there because
they are properties of the reference, not the task:

- **The tracked window is the maneuver, not the clip.** `CLIMB`/`HOVER`/`LAND` are dropped as
  stagecraft, which picks out `POP..RECOVER` / `SWING..SETTLE` / `WIND-UP..SETTLE` for the three
  shipped maneuvers *without naming any of them*. It matches the deploy split, where the `hover_tof`
  policy owns take-off and landing and the acro policy owns a bounded window. A non-contiguous
  selection is **refused** rather than spliced — a hole would teleport the target and still look
  smooth on both sides.
- **Resampling is nearest-sample.** The reference is 1 kHz precisely because 50 Hz aliases these
  maneuvers (the flip's thrust cut is one control step wide); interpolating a quaternion across a
  command step would invent an attitude the trajectory never held.

**`tasks/reference_track.py`**: obs is 13-wide and deploy-honest —
`[gravity_body(3), p, q, r, maneuver_phase, gravity_body_ref(3), omega_ref(3)]`. The reference
channels are *authored* signals in the same class as `maneuver_phase`: a deterministic function of
the clock, so at deploy they ship with the policy as a small table rather than needing a sensor.
They are handed over explicitly instead of left for the net to memorise because a `[64,64]` policy
should spend capacity on control, not on storing a trajectory it gets for free. **Reference position
is deliberately absent** — a whoop has no onboard position sensor, so position tracking lives in the
reward only, the same privileged line `acro_flip` draws for station-keeping.

Reward: a weighted sum of tracking bells `exp(-(err/sigma)^2)` on attitude / rate / position /
velocity — bounded, smooth, saturating rather than exploding on a bad frame.

**Reference State Initialization is the load-bearing part, not a detail.** `rsi_frac` 0.8 of
episodes start at a random phase *in the reference's own state*, so inverted flight gets gradient
from the first update instead of after a lucky exploration sequence — directly targeting the failure
mode `lucky-wind-7057` exhibits. That is what `env.spawn()` grew a `quat=` argument for: a flip
spawns inverted, where the ZYX euler triple is degenerate (`quaternion_to_euler` clamps pitch to
+-90 deg), so an euler-only spawn cannot express half the states a flip visits.

**One task covers all three maneuvers** — `ManeuverSpec` is a protocol with three implementations
emitting one format, so this adds six configs (`reference_track_{flip,swing,orbit}` + `_eval` twins)
and *no* per-maneuver code. A fourth authored maneuver needs none.

Eval twins set `rsi_frac: 0` and zero station jitter: an honest rollout flies the whole maneuver
from phase 0, and it is the only one a hero video should be rendered from.

## Verdict

Method node — no metric of its own; the first results are in the child node. 19 new tests, 387
green. Two design choices worth flagging as *untested* rather than settled: the tracking-bell sigmas
(`pos_sigma` 0.25 m in particular) and the deliberately-lighter DR, since the reference is authored
against the *nominal* airframe and heavy DR would ask the policy to track a trajectory that is not
physically reachable on the sampled one.

## Lineage

Consumes the reference package (`ancient-river-4144`, `sparkling-shadow-0034`); motivated by the
reward-shaping failure in `lucky-wind-7057`; the orbit arm is unblocked by the rate-loop fix in
`bitter-rain-0437` and could not have existed before it.
