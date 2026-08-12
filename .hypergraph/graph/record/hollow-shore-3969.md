---
node_id: 07b29f16-77d1-5eca-aee9-748918757646
slug: hollow-shore-3969
title: 'Width arm: capacity contention CONFIRMED as the altitude sink''s mechanism, and the remedy is NO-GO — [192,192] fixes the trim and loses 8.6 points of survival'
created_at: '2026-08-12T14:54:11+00:00'
parents:
- staid-moon-7407
- keen-mist-5478
summary: ''
---
## What

`flow-hover-w192` — one factor off `flow-hover`: `hidden_sizes` [128,128] -> [192,192], same seed,
same everything else. Trained to the full 3.2e9 budget (50 min) and put through the same two
probes as its parent.

**The capacity-contention mechanism is CONFIRMED. The remedy is NO-GO.**

## Why

`keen-mist-5478` measured a ~0.10 m DC altitude sink on the flow arm; `staid-moon-7407`'s knockout
localized it to the weights rather than to the channel values (zeroing flow moved the height 1.4 mm
on a 97 mm offset), leaving exactly two candidates: capacity contention (the same [128,128] net now
takes 64 stacked inputs instead of 48) or the documented H2 thrust-trim coupling (noisy obs channels
bias the learned mean hover thrust). The two make opposite predictions about width, which is what
makes this a discriminating experiment rather than a tuning pass.

## Method

`scripts/eval.py --no-dr` (2048 envs, 1500 steps) and `scripts/exit_probe.py` (2048 envs, full DR,
pure-hold cohort). Identical invocations to the parent's, so the rows are directly comparable.

## Result

**Contention confirmed, on the nose.** Clean conditions, against the [128,128] arm and the
`noflow` control:

| no-DR | flow [128,128] | flow [192,192] | noflow control |
|---|---|---|---|
| `mean_z_error` | 0.0994 | **0.0537** | 0.0530 |
| `mean_height` (setpoint 0.40) | 0.303 | **0.348** | 0.347 |
| `mean_tilt_deg` | 1.054 | 0.249 | 0.266 |
| `mean_speed` | 0.0628 | 0.0201 | 0.0228 |
| `mean_xy_error` | 0.1747 | 0.1860 | 0.2397 |
| `hold_rate` | 0.717 | 0.750 | 0.564 |

Width returns the height to within 1 mm of the control's and the tilt to within 0.02 deg, while
keeping most of the horizontal win. The H2 coupling predicted width would NOT help, because the
coupling is to the noise rather than to the parameter count. It helped, and it landed on the
control's value rather than somewhere in between. Contention it is.

**And the remedy is a net loss.** Full-DR pure-hold survival:

| | survival | xy | floor | ceiling | median exit |
|---|---|---|---|---|---|
| flow [128,128] | **62.0%** | 776 | 3 | 0 | 21.6 s |
| flow [192,192] | 53.4% | 949 | 5 | 1 | 20.5 s |
| noflow control | 25.6% | 1518 | 5 | 0 | 14.8 s |

8.6 points on 2048 drones is ~8 sigma of the binomial, so the direction is not noise. The calmer,
better-trimmed, better-holding policy is the worse one where it counts.

The reading that fits every column: the [128,128] arm's activity (2.5x the speed, 4x the tilt, and
the ~0.07 m limit cycle visible in `runs/flow-hover/viz/comparison.png`) is **load-bearing under
DR**. It looks like sloppiness in still air and behaves like active drift-fighting under wind and
impulses. Extra capacity bought a policy that trusts its own trim, which is the right strategy in
the clean eval and the wrong one in the probe that stands in for a real room.

**Width also only relocated the altitude error, it did not remove it.** The sink is fixed in the
*clean* eval; under full DR the wide arm is worse — `survivor_mean_z_err` 0.075 vs 0.069, training
`mean_z_error` 0.077 vs 0.065, `ep_peak_z_m` 0.624 vs 0.591, and it produced this family's first
ceiling exit. So "capacity contention explains the clean-air sink" is the claim; "width fixes
altitude" is not.

**Verdict: [128,128] stays the recommended arm.** The altitude sink is now explained rather than
fixed, and buying the fix costs 8.6 points of the deployable metric.

**Honesty.** One training seed per arm. The 8.6-point gap is one sample from a distribution that
has not been measured, and this ladder has no seed-variance estimate at any width — the same
caveat applies to every single-factor comparison in it. A seed sweep is the control that would
settle it and it has not been run.

Named, not run: the noise-knockout control that would close out the H2 mechanism completely
(zero the flow channels' DR *noise* rather than their values); and an intermediate width, since
[128] -> [192] is a 2.25x parameter jump and the trade may not be monotonic.

## Repo

- repo: git@github.com:theo-kirby/neural-whoop.git
- branch: main
- commit: e38e4ea9eced92bd75de59f48aaf9f770871cdb8

## State Impact

- target: NEW optical-flow-calibration — the altitude sink is explained (capacity contention, not the H2 trim coupling) but deliberately not fixed: [192,192] restores the clean-air trim to the control's value and costs 8.6 points of full-DR survival, so [128,128] remains the recommended arm. Open caveat: one seed per arm, no seed-variance estimate anywhere in this ladder.
- target: cold-pebble-7468 — configs/flow-hover-w192.yaml added as the one-factor capacity arm.
