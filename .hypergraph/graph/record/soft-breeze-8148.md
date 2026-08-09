---
node_id: e61f6f4a-c807-500d-823c-71615e80229f
slug: soft-breeze-8148
title: 'Desk-Hover arm 2 (vxy_penalty 0 → 0.5): buys the drift it targeted (0.047 → 0.036 m clean, hold_rate 1.000) and pays for it in FLOOR MARGIN — floor exits 98 → 311. NO-GO'
created_at: '2026-08-08T16:11:33.814493+00:00'
parents:
- dawn-bonus-9868
- black-salad-4817
summary: 'ONE FACTOR vs arm 1 (dawn-bonus-9868): task.vxy_penalty 0.0 -> 0.5, a privileged -k*||v_xy|| term calibrated against the observed 0.205 m/s M1-live drift (0.10/step, ~2.4x the upright term''s entire dynamic range, matching R4''s vz_penalty 0.5). Same battery, 2048 drones, 30 s, seed 12345. IT WORKS ON ITS OWN TARGET: clean pure-hold mean_xy_error 0.0472 -> 0.0356 m (-25%) and hold_rate 0.913 -> 1.000 (perfect), plus mean_z_error improves under noise (m1live 0.0178 -> 0.0128, full DR 0.0438 -> 0.0318). BUT the gain is confined to the CLEAN condition and is paid for in the safety-critical direction: mean_height 0.0824 -> 0.0786 m, which flips gate 2 by 1.4 mm (|0.0786-0.10| = 0.0214 > 0.020); floor exits 98 -> 311 (m2sensor 29 -> 120, full DR 69 -> 191); m2sensor 30 s survival 0.9834 -> 0.9380 (-4.5 pts). And under sensor noise the drift is WORSE, not better: purehold_noise 0.1336 -> 0.1634, m1live 0.1857 -> 0.2069. Battery 2 of 4 vs arm 1''s 3 of 4. VERDICT NO-GO: penalizing ||v_xy|| discourages exactly the corrective lateral moves the policy needs when its attitude estimate is noisy, so it holds tighter when clean and responds less when not; and pressing toward stillness biases the hover lower, eating the 8 cm floor margin that is already the binding constraint at desk scale. Arm 1 remains the recommended Desk-Hover policy. This confirms the pre-registered caveat that drift credit assignment is episode-level and high-variance. The named arm 3 (upright_scale 1.5 -> 2.5) is untouched and remains the open alternative.'
origin:
  backend: flywheel
  node_id: e61f6f4a-c807-500d-823c-71615e80229f
  slug: soft-breeze-8148
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 3f4c77ec-a03b-5cbd-a8cb-c718a4d8a2fc
  slug: calm-forest-5543
  revision: 0
  pushed_at: '2026-08-09T21:28:32+00:00'
  content_sha256: 00623dace922cb611c180ec87f0eb3609779906ad386ad8ce00b6ebfd94b53a9
---
## Hypothesis

Horizontal drift is the failure mode this operating point actually has — obs carries no position or
velocity, there is no flow deck, so drift is open-loop and set entirely by leveling quality.
`vxy_penalty` gives PPO a direct gradient against commanding sideways velocity, the only lever
available.

**Magnitude, calibrated rather than guessed:** against the observed 0.205 m/s M1-live drift, 0.5
costs 0.10/step — ~2.4x the *entire dynamic range* of the upright term over realistic tilts
(0.042) — and it matches R4's `vz_penalty 0.5`, the only calibrated privileged-term precedent in
the repo.

## Setup

**ONE FACTOR** vs arm 1 (`dawn-bonus-9868`): `task.vxy_penalty` 0.0 -> 0.5. The two configs differ
by exactly two lines (`run.name` and this), diff-verified. Same 3.2e9 steps, same battery, 2048
drones, 30 s, deterministic mean, seed 12345.

## Results

### It works on its own target — in the clean condition

| clean pure-hold | arm 1 | **arm 2** | Δ |
|---|---|---|---|
| `mean_xy_error` | 0.0472 m | **0.0356 m** | **−25%** |
| `hold_rate` | 0.913 | **1.000** | perfect |
| `mean_tilt_deg` | 0.391° | 0.448° | +15% |
| `mean_height` (setpoint 0.10) | 0.0824 m | **0.0786 m** | −0.4 cm |

And the vertical channel genuinely improves under noise: `mean_z_error` m1live 0.0178 ->
**0.0128**, m2sensor 0.0270 -> **0.0220**, full DR 0.0438 -> **0.0318**.

### But the drift gain does not survive sensor noise

| `mean_xy_error` | arm 1 | arm 2 |
|---|---|---|
| pure-hold clean | 0.0472 | **0.0356** |
| pure-hold + noise | **0.1336** | 0.1634 |
| m1live | **0.1857** | 0.2069 |
| m2sensor | **0.1986** | 0.2038 |
| full DR | 0.2905 | **0.2865** |

The *only* condition where the term wins on drift is the one with no sensor noise at all — i.e.
the one that does not exist in deployment.

### And it is paid for in floor margin

| exits | arm 1 floor / xy | **arm 2** floor / xy | survival Δ |
|---|---|---|---|
| m1live | 0 / 1 | 0 / 10 | 0.9995 -> 0.9951 |
| m2sensor | 29 / 5 | **120** / 7 | 0.9834 -> **0.9380** |
| full DR | 69 / 1238 | **191** / 1152 | 0.3618 -> 0.3442 |
| **total floor** | **98** | **311** | **3.2x** |

### Battery

| gate | bar | arm 1 | arm 2 |
|---|---|---|---|
| 1 — clean drift | <= 0.10 m | 0.0472 PASS | **0.0356 PASS** |
| 2 — clean `mean_height` | 0.10 +/- 0.02 | 0.0824 PASS | **0.0786 FAIL** (by 1.4 mm) |
| 3 — peak <= 0.30 + zero floor exits | HARD | 98 FAIL | **311 FAIL** |
| 4 — m1live survival | >= 0.98 | 0.9995 PASS | 0.9951 PASS |
| | | **3 of 4** | **2 of 4** |

## Verdict: NO-GO

Arm 1 remains the recommended Desk-Hover policy.

**The mechanism is coherent and worth stating, because it is the reason a bigger weight will not
help either.** `vxy_penalty` penalizes horizontal *speed*, and the corrective move a hovering
policy makes against a perceived drift **is** horizontal speed. With a clean attitude estimate the
policy barely needs those moves, so the penalty is nearly free and it collects the drift
reduction. Once the gyro/attitude channels are noisy the same penalty suppresses the corrections
it needs, and drift gets *worse*. Separately, pressing toward stillness biases the hover lower —
less of the throttle envelope is spent on tilt-compensating climb — and at desk scale the thing
below the policy is 8 cm of floor. That is why the term's cost shows up as **floor exits** rather
than as a drift regression.

Gate 2 failing by **1.4 mm** should not be read as a near-miss to be waved through: the same 0.4 cm
of downward bias is what tripled the floor exits, so the gate is measuring the real thing.

## Honesty

- **The term did what it was designed to do.** This is not a failed implementation; the drift
  number moved 25% in the right direction and the hold rate hit 1.000. It is a genuine
  **trade**, and the trade is bad at this operating point.
- The pre-registered caveat holds: *"drift credit assignment is episode-level and high-variance —
  expect a weak, noisy gradient."* What we got instead was a *strong* gradient pointed at a proxy
  (horizontal speed) that is not the same thing as the objective (horizontal *position*).
- **The R4 precedent read correctly.** `docs/TASK_CATALOG.md` records R4 (`vz_penalty` +
  `thrust_const_penalty`) at 0.0% M1 while its hold time improved monotonically — i.e. "the term
  helped the thing it was aimed at, on a substrate that failed for an unrelated reason." Arm 2 is
  the same shape: helped its target, cost something else.
- **Single-arm, single-seed.** No seed replication; a 0.4 cm height difference is small enough that
  seed variance is a live alternative explanation for gate 2 specifically — though not for a 3.2x
  change in floor exits.
- **`arm 3 is untouched and remains open:** `upright_scale` 1.5 -> 2.5, the control the parent's own
  `probes.json` verdict asks for. Arm 2's mechanism argues *for* it: if drift is a leveling-quality
  problem before it is a velocity one, attacking leveling directly avoids the proxy trap that sank
  this arm.

## Lineage

- `dawn-bonus-9868` — arm 1, the one-factor parent and the baseline column throughout.
- `black-salad-4817` — the design, which pre-registered both this arm's magnitude calibration and
  the caveat it ran into.