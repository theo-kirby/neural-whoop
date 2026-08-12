---
node_id: f0e56225-b074-5279-8dd1-28be576f8588
slug: staid-moon-7407
title: 'Knockout: the flow win is causally the channel (62.0% -> 16.8% survival when zeroed, BELOW the 25.6% control) — and fade-to-zero is therefore not a safe fallback'
created_at: '2026-08-12T13:13:38+00:00'
parents:
- keen-mist-5478
summary: ''
---
## What

A channel-value knockout on the trained `flow-hover` policy: zero the two flow channels in every
stacked frame at eval time and re-measure. New instrument, `scripts/knockout_probe.py`, plus an
optional third argument on `scripts/exit_probe.py` so the same mask can be applied to the survival
battery. Three findings, and the third was not what the probe was aimed at.

## Why

`keen-mist-5478` reported GREEN but could not distinguish three explanations for it: the policy
using the channel online, the extra parameters, or the seed. And it named two candidate mechanisms
for the ~0.10 m altitude sink without separating them. A knockout separates "the information did
it" from "the weights did it" — the sibling of the noise knockout already in the ladder
(`runs/hover_tof_air65/probes.json`), which turned per-channel DR *noise* off rather than the
channel's values.

Zeroing is the right mask here specifically because zero is the **deploy value**: it is exactly
what `hover_flow`'s grace-then-fade produces when the sensor goes blind. So the knockout row is a
real scenario — "the flow sensor dies mid-flight" — and not only an attribution device.

## Method

`knockout_probe.py` wraps the `ActorCritic` and zeroes base-frame channels 6,7 across all 8 stacked
frames. Both rows use a freshly built env at the same seed and horizon, so the mask is the only
difference. Regression check: `exit_probe.py` with no channel argument reproduces the prior run
exactly (62.0%, 776 xy, 3 floor), so the new flag does not perturb the default path.

## Result

**1. The horizontal win is causally the channel — decisively.** Full-DR pure-hold survival:

| | survival | xy exits | median exit |
|---|---|---|---|
| intact | 62.0% | 776 | 21.6 s |
| flow zeroed | **16.8%** | 1703 | 13.4 s |
| `noflow` control | 25.6% | 1518 | 14.8 s |

Not "some of the advantage" — blinding the policy drops it **below** the control that never had the
channel. Clean-conditions knockout is milder (`mean_xy_error` 0.175 → 0.217 against the control's
0.240, so ~65% of the gap), which is consistent: with no wind, noise or impulses there is little
drift to observe, and the reliance only shows under DR.

**2. The altitude sink is NOT the channel.** Zeroing it moves `mean_z_error` 0.0994 → 0.0975 and
`mean_height` 0.3028 → 0.3042 — a 1.4 mm change on a ~97 mm offset. The sink is therefore a learned
thrust trim baked into the weights, not a response to what the channel is saying. That rules out any
online mechanism and leaves the documented H2 trim coupling (`tasks/hover.py`: noisy obs channels
bias the learned mean hover thrust — this arm has two more of them) or capacity contention. Both are
addressed by width or trim work; **neither is addressed by a better flow sensor**, so calibrating
the hardware will not fix it.

**3. The finding the probe was not aimed at, and the most important one: fade-to-zero is not a safe
fallback.** A flow-trained policy that loses its sensor survives at 16.8%, worse than the 25.6% of a
policy that never had one. It has learned to depend on the channel, so the graceful-degradation
story built into the task — grace, then fade to an "honest neutral" — degrades to *below baseline*
rather than to baseline. The neutral value is honest; the resulting behaviour is not safe. Three
responses, none taken yet:
- a **`flow_lost` abort** mirroring the deployed `tof_lost` one, which is the existing precedent for
  "a channel this policy owns has gone silent";
- retraining with a far higher `flow_dropout_prob` than the placeholder 0.02, so blindness is
  in-distribution and the policy keeps a fallback strategy;
- keeping a `hover_tof` policy as the designated failover.
This directly amends `configs/flow-hover.yaml`, whose dropout constant was set as an uncalibrated
guess and now turns out to be the knob that governs a safety property rather than a realism detail.

Also: floor exits 3 → 0 and `survivor_mean_z_err` 0.069 → 0.061 under the knockout, both consistent
with finding 2 — the vertical axis simply does not care about these channels either way.

## Repo notes

`scripts/knockout_probe.py` (new), `scripts/exit_probe.py` (optional channels argument). No change
to any trained policy or to the task; this is measurement only.

## Repo

- repo: git@github.com:theo-kirby/neural-whoop.git
- branch: main
- commit: d3ee2de624d9685905cf13d562c7cfe0a9a48814

## State Impact

- target: NEW optical-flow-calibration — the GREEN is now causally attributed to the channel rather than to parameters or seed. New requirement discovered: flow_dropout_prob (set as an uncalibrated realism guess at 0.02) governs a SAFETY property, because a blinded flow policy survives at 16.8% vs the 25.6% of one that never had the channel. The calibration flight must therefore measure dropout, not just scale and rate.
- target: modest-raven-7153 — deploy consequence: hover_flow's grace-then-fade degrades to BELOW the hover_tof baseline, not to it. Named responses, none taken: a flow_lost abort mirroring the deployed tof_lost one; retraining with in-distribution blindness; or a hover_tof failover policy. No hover_flow policy should be flown until one exists.
- target: cold-pebble-7468 — new measurement tooling: scripts/knockout_probe.py (channel-value knockout, the sibling of the existing noise knockout) and an optional channels argument on scripts/exit_probe.py. Default path verified unchanged.
