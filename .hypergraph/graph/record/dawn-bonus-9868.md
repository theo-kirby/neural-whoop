---
node_id: 0d7bae3a-2608-5001-9746-c3c9d3fe1f89
slug: dawn-bonus-9868
title: 'Desk-Hover arm 1 TRAINED: the 0.10 m desk hold works — clean drift 0.299 → 0.047 m, hold_rate 0.15 → 0.91, m1live survival 6.3% → 99.95%; 3 of 4 gates, and the one it misses names the ToF calibration'
created_at: '2026-08-08T15:32:21.673650+00:00'
parents:
- black-salad-4817
- noisy-brook-4394
- shy-butterfly-3991
summary: 'Desk-Hover arm 1 (configs/desk-hover.yaml, 3.2e9 steps, [128,128], obs_stack 8) vs the 1.0 m parent hover_tof_air65_w128u15_r25 scored on the SAME desk twins. NOT an ablation — ~12 factors, a new operating point. On the clean pure-hold twin (2048 drones, 30 s, seed 12345): mean_xy_error 0.2986 → 0.0472 m (−84%), hold_rate 0.150 → 0.913 (6.1x), mean_tilt_deg 1.017 → 0.391 (−62%), mean_z_error 0.0576 → 0.0177 m (−69%), mean_height 0.0424 → 0.0824 m against a 0.10 m setpoint. Survival at 30 s: m1live 0.0625 → 0.9995, m2sensor 0.0396 → 0.9834. FOUR-GATE BATTERY (bars fixed in advance): gate 1 clean drift <= 0.10 m → 0.0472 PASS; gate 2 mean_height 0.10 +/- 0.02 → 0.0824 PASS (barely, 1.8 cm low); gate 3 ep_peak_z_m <= 0.30 AND zero floor exits → peak 0.1000 PASS but 98 floor exits FAIL; gate 4 m1live >= 0.98 → 0.9995 PASS. Tally 3 of 4 (parent: 0 of 4). VERDICT GREEN with one named caveat. The gate-3 miss is informative rather than fatal and localizes precisely: floor exits are 0 on clean, 0 on m1live, 29 on m2sensor, 69 under full training DR — i.e. every one of them appears only once the +/-0.03 m h_err BIAS is switched on. That is the sim''s quantitative prediction of what the measured, uncalibrated +23.9 mm static ToF offset does against 8 cm of floor margin, and it converts the deferred pilot-side tof_cal from a nice-to-have into the blocking item for a real 0.10 m flight. Honest caveats: the policy sits 1.8 cm BELOW setpoint when clean (the plan predicted hovering HIGH — refuted; the parent sinks to 0.042 m, so the bias is downward in both); ep_peak_z_m 0.1000 is uninformative on the pure-hold twin because z is pinned; full-DR survival 0.3618 is NOT comparable to the parent''s 0.6128 since each ran on its own training config.'
origin:
  backend: flywheel
  node_id: 0d7bae3a-2608-5001-9746-c3c9d3fe1f89
  slug: dawn-bonus-9868
  revision: 4
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Hypothesis

Moving the operating point to 0.10 m (`black-salad-4817`) makes the desk hold *learnable* — the
crash mechanism that killed the real flights has no room to exist there, and rescaling the reward's
length scales by ~10x restores the resolution the reward needs to see a 5 cm error.

## Setup

- `configs/desk-hover.yaml`, 3.2e9 steps, 8192 drones, `[128,128]`, `obs_stack 8`, ~46 min on the
  5090 at ~1.16M sps. `crash_rate_per_step` stayed 0.000 for the entire run.
- Scored against the parent `hover_tof_air65_w128u15_r25` **on the same desk twins**
  (`desk-hover-{purehold,m1live,m2sensor}.yaml`), 2048 drones, 30 s, deterministic mean, seed
  12345. Exit directions from the **fixed** `exit_probe.py` (`shy-butterfly-3991`).
- **This is not an ablation.** ~12 factors from the parent. It is a new operating point and carries
  no single-factor attribution; arm 2 (`desk-hover-drift`) is the one-factor arm.

## Results

### Clean pure-hold, 30 s (`desk-hover-purehold` `--no-dr`) — the precision number

| | parent (1.0 m policy) | **arm 1** | Δ |
|---|---|---|---|
| `mean_xy_error` | 0.2986 m | **0.0472 m** | **−84%** |
| `hold_rate` | 0.150 | **0.913** | **6.1x** |
| `mean_tilt_deg` | 1.017° | **0.391°** | −62% |
| `mean_z_error` | 0.0576 m | **0.0177 m** | −69% |
| `mean_height` (setpoint 0.10) | 0.0424 m | **0.0824 m** | — |

### Survival at 30 s

| twin | parent | **arm 1** |
|---|---|---|
| m1live (sensor noise only) | 0.0625 | **0.9995** |
| m2sensor (+ bias, rate-gain, latency 5) | 0.0396 | **0.9834** |

### Exit directions (fixed probe)

| twin | parent floor / ceil / xy | **arm 1** floor / ceil / xy |
|---|---|---|
| m1live | 68 / 0 / 1852 | **0 / 0 / 1** |
| m2sensor | 458 / 0 / 1509 | **29 / 0 / 5** |
| own full DR | 72 / 3 / 718 | 69 / 0 / 1238 |

### The four-gate battery (bars declared BEFORE any result was seen)

| gate | bar | value | verdict |
|---|---|---|---|
| 1 — clean pure-hold `mean_xy_error` | <= 0.10 m | **0.0472** | **PASS** |
| 2 — clean pure-hold `mean_height` | 0.10 +/- 0.02 m | **0.0824** | **PASS** |
| 3 — `ep_peak_z_m` <= 0.30 **and** zero floor exits | HARD | peak **0.1000**, floor exits **98** | **FAIL** |
| 4 — m1live 30 s survival | >= 0.98 | **0.9995** | **PASS** |

**3 of 4** (parent on the same battery: **0 of 4**).

## Verdict: GREEN, with one named caveat

The desk hold works, and it is not a marginal win: an 84% drift reduction, a 6.1x hold rate, and
survival going from 6% to 99.95% on the deploy-faithful twin. The parent dropped onto this setpoint
does not merely underperform — it **sinks into the desk** (mean height 0.042 m, 598 floor exits
across the battery).

### The gate-3 miss is the most useful result in the run

Gate 3 fails on the floor-exit clause, and the breakdown localizes it exactly:

- clean pure-hold: **0** floor exits
- m1live (sensor *noise*): **0**
- m2sensor (adds the +/-0.03 m `h_err` **bias**): **29**
- full training DR: **69**

**Every floor exit appears only once the height-channel bias is switched on.** That is the sim
quantifying what the measured, uncalibrated **+23.9 mm static ToF offset** (`tiny-glitter-0842`)
does against **8 cm of floor margin** — the exact risk `black-salad-4817` identified on paper, now
with a number attached. It promotes the deferred **pilot-side `tof_cal`** from a nice-to-have to
**the blocking item for a real 0.10 m flight**: the policy is fine, the *channel* is offset.

## Honesty

- **The plan's hover-high prediction is REFUTED, in both arms of the comparison.** The premise was
  that a coarse `pos_sigma` would let a policy settle at 0.2-0.3 m. The parent instead **sinks** to
  0.042 m, and arm 1 settles **1.8 cm BELOW** its setpoint (0.0824 vs 0.100) — gate 2 passes with
  0.2 cm to spare. The `pos_sigma` rescale is still justified on reward-*resolution* grounds, but
  the specific failure mode it was aimed at is not the one the evidence shows. At desk scale the
  bias is downward, which is the direction with only 8 cm of margin.
- **`ep_peak_z_m 0.1000` on the pure-hold twin is uninformative**, because that twin pins
  `z_min == z_max == 0.10`. The meaningful peaks are m1live 0.124, m2sensor 0.127, full DR 0.200 —
  all far under the 0.30 band ceiling, and `above_band_rate` is 0.0000 / 0.0009 / 0.0065.
- **Full-DR survival 0.3618 vs the parent's 0.6128 is NOT a regression** — the two ran on *their
  own* training configs (a +/-0.6 m desk vs a +/-6.0 m arena), so the comparison is meaningless in
  that column and is reported only for completeness.
- **This remains a bounded-duration hold.** 0.047 m of drift over 30 s clean is excellent, but
  drift is open-loop (no position/velocity obs, no flow deck) and under the m1live twin it is
  0.186 m. Nothing here makes it an indefinite station-keep.
- Arm 1 carries **no single-factor attribution**. Which of the ~12 deltas bought what is unknown;
  the Phase-2 probe (`black-salad-4817`) established only that `wind_accel_mps2` 1.0 → 0.15 is
  load-bearing for *survivability*, at 4.6x median time-to-horizontal-exit.

## Lineage

- `black-salad-4817` — the design and the pre-registered gates.
- `noisy-brook-4394` — the parent policy and config, and the baseline column throughout.
- `shy-butterfly-3991` — the exit-probe fix, without which gate 3 would have passed unconditionally
  and this node would have claimed 4 of 4 while the drone flew into the desk.