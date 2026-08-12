---
node_id: e050c359-20d0-51fc-83c0-3bf04f9b4e7a
slug: snowy-brook-2829
title: 'Desk-Flow, before any number: the 0.15 m ToF+flow operating point, sustained blackouts in-distribution, and the obs-8 deploy path a hover_flow policy needs to be flown at all'
created_at: '2026-08-12T16:07:53+00:00'
parents:
- staid-moon-7407
- hollow-shore-3969
- dawn-bonus-9868
summary: ''
---
## What

Everything Desk-Flow needs before a number exists: a **0.15 m** ToF+flow operating point
(`configs/desk-flow.yaml`, task `hover_flow`, obs 8) with its one-factor control
(`desk-flow-noflow.yaml`, task `hover_tof`, obs 6) and six eval twins, a **sustained-blackout**
sensor model in `hover_flow`, and the **obs-8 deploy path** — the first time anything in the pilot
accepts a `hover_flow` policy. Two commits: `e4572ae` (sim) and `64f32ee` (deploy).

No empirical result here. Both arms are training as this is written; the result is a child node.

## Why

`staid-moon-7407` established two things that make the rest of this necessary rather than tidy.
The flow win is **causally the channel** (62.0% → 16.8% survival when zeroed, *below* the 25.6%
arm that never had it), so the policy genuinely depends on a sensor that can go blind — and
**fade-to-zero is therefore not a safe fallback**, it is the worst state measured. A policy that
depends on a channel needs (a) to have flown its loss before, and (b) a deploy path that aborts
rather than continues into it. Neither existed.

`hollow-shore-3969` closed the width question in the other direction: [192,192] fixes the altitude
trim and costs 8.6 points of survival, so Desk-Flow's `ppo:` block stays Desk-Hover's [128,128].

**Why 0.15 m and not Desk-Hover's 0.10.** The setpoint is forced by the sensor, not chosen. The
PMW3901 is optically blind below **80 mm** — a hard limit, not a noise floor — and Desk-Hover's
shipped policy holds **0.0824 m** against its 0.10 m setpoint
(`runs/desk-hover/probes_desk_desk-hover.json`, `purehold_clean`), an ~1.8 cm sink. Add the
**uncalibrated +23.9 mm ToF offset** (`rapid-hill-4130`) and a 0.10 m target puts the real sensor
at ~0.076 m: **blind**, i.e. exactly the state the knockout measured as worst.

| | at 0.10 m | at 0.15 m |
|---|---|---|
| expected hover (1.8 cm sink) | 0.082 m | 0.132 m |
| ...with the uncalibrated ToF offset | **0.076 m — blind** | 0.108 m — 28 mm clear |
| margin above the 80 mm flow floor | 2.4 mm | **52 mm** |
| ToF offset as a velocity-scale error | 24% | **16%** |
| floor margin under the setpoint | 8 cm | 14 cm |
| peak vs the 1.3 m ToF ceiling (0.37 m overshoot) | 13× inside | 2.5× inside |

Still desk scale, still structurally immune to the 2026-07-31 saturate-and-hold chain, and now
inside the band where **both** sensors work.

## Method

**1. Sustained blackout (`tasks/hover_flow.py`).** `flow_dropout_prob` was an i.i.d. per-step coin,
i.e. single-frame speckle: at 0.02 the chance of losing a whole second (50 steps) is 1e-85, so a
policy trained on it has *never* seen sustained blindness — while the deploy failure it will meet
is a run (a bare patch of desk, a shadow, a mat lifting in prop wash), and the pilot deliberately
gives it ~1 s before cutting the flight. New `flow_blackout_prob` / `flow_blackout_s`: a per-drone
timer, duration drawn uniform in `(0, blackout_s]`, suppressing the reading whatever the surface,
tilt and height are doing. **Default OFF** — every flow result before today (`keen-mist-5478`,
`staid-moon-7407`, `hollow-shore-3969`) was measured without it and silently changing their
substrate would make them incomparable.

**2. The config family.** `desk-flow.yaml` + `desk-flow-noflow.yaml` + three eval twins each
(`-purehold` / `-m1live` / `-m2sensor`). Two constants are **derived, not guessed**, and both are
worth stating because a placeholder that looks like a measurement is the failure mode this ladder
already hit once:

- `flow_scale_frac: 0.20` (vs flow-hover's 0.10) — it has to cover the 16% velocity-scale error the
  +23.9 mm ToF offset induces at 0.15 m (height multiplies straight into the velocity scale), *plus*
  the slide test's own error. flow-hover's 0.10 was the bench-calibration error alone at a setpoint
  where the offset was worth 6%.
- `flow_blackout_prob: 0.0005` — derived from **gate 5**. 0.025 blackouts/s against a mean 0.75 s
  length is an 1.8% duty cycle, so the modeled availability ceiling is
  `(1 − 0.02)·(1 − 0.018) = 0.962`, which leaves the `flow_valid_rate ≥ 0.95` bar measuring the
  *policy's* height/tilt excursions rather than my choice of dropout constant. It still puts ~0.8
  sustained losses in every 30 s episode. If the calibration flight measures a higher real rate,
  this number moves **and gate 5's bar moves with it** — the ceiling is arithmetic, not a target.

`vxy_penalty` stays 0 (arm 1): `soft-breeze-8148` measured that privileged proxy NO-GO, and the
policy can now *see* the quantity it was a proxy for, so adding it would confound the one result
this config exists to produce.

**3. `tests/test_config_twins.py` — a guard nobody had.** `scripts/survival_probe.py` overrides
exactly one key (`hold_fraction`) and takes everything else from the twin, so a twin that has
drifted from its training config silently measures a **different arena** and reports the difference
as a policy result. The desk-hover twins were kept aligned by hand and by a comment saying
"VERBATIM". This pins it, for all three families, plus: the control arm differs from Desk-Flow in
the flow channels and nothing else (gate 6's precondition, checked *before* either arm trained),
the setpoint clears the optical floor with the uncalibrated offset included, and the twins grade
the policy on the same sensor model it trained against.

**4. The obs-8 deploy path.** `export_json.py` layout + probe names; task-keyed family detection;
the flow channel in `FlightController`; `vx`/`vy` CSV columns (31 → 33) in all three `LOG_COLUMNS`
copies; `sim_vs_real.py`; the CLI (`selftest` corrective-sign check on the two new channels,
`check`, `fly` flags); the Studio (`_PARAM_FIELDS`, `check_policy_family` on load, a
flow-consistent `FakeFlightBridge`). Documented in docs/SIM2REAL.md "The obs-8 deploy path".
Direct sequel to the passive `--log-flow` work in `e38e4ea`, which added the raw-count columns and
the single `flow_delta` consumer this path had to *move* rather than duplicate.

Verification: `scripts/env_check.py` PASS, `pytest -q` **468 passed, 1 skipped** (was 444/1).

## Result

No metric yet — that is the point of this node being separate. What it establishes:

**Two hazards the deploy path had to be designed around, both real.**

1. **`base_obs_dim == 8` was already the acro-flip obs.** Every gate now branches on
   `meta["task"]` and only then on the dim, in **both** directions — an acro file is refused as a
   hover policy and a hover file as an acro one — because either mistake flies a real drone on
   channels that mean something else. `uses_tof` is **true** for `hover_flow` (channel 5 is still
   the ToF error) and `uses_vz` explicitly excludes it, or an 8-dim flow file falls through the
   `>= 6` fallback and is fed a climb-rate estimate where the policy expects a height error.
2. **`Telemetry.flow_delta()` consumes its interval by contract.** The logging path owned the only
   call; the obs path **moved** it into `_advance_flow` rather than adding one, and a test pins
   exactly one call per tick. Two differencers would each see half the motion.

**Two things the fake bridge caught that reading would not have.**

- **A `hover_flow` policy could not take off at all.** Setup demanded a live flow reading and the
  `flow_lost` abort ran from the override edge — but the countdown, the liftoff seek and the whole
  climb-out happen **under the sensor's 80 mm working range**. Setup now gates the *sensor* and not
  the *surface* (a missing sensor refuses; a poor ground squal warns), and the abort clock starts at
  free flight, giving the policy 1 s from there to acquire the channel. The textureless-floor case
  is still caught — one second into free flight, where the reading means something.
- **The fake's flow was a fixed drift**, so a `hover_flow` rehearsal would have passed with the obs
  path completely dead: sign error, units error and no-op all produce an identical CSV. It now
  inverts the host's own conversion from a crude tilt-and-drag velocity, and goes blind under 80 mm.

**One latent bug found on the way.** The props-off `check` fed a **5-dim frame to a 6-dim ToF
policy** — `Policy.__call__` zips over `len(obs)`, so the last column of every weight row was
silently dropped and nothing failed. `check` is where a sign gets verified before a first flight,
so it was verifying signs on a policy nobody was running. Fixed by building the real obs, with the
counts→velocity conversion in **one** shared function (`flow_to_velocity`) used by both the flight
engine and `check`.

**Design notes worth carrying forward.** The gyro term in that conversion is not optional: a
pitching drone sweeps the ground past the lens with no translation at all, so the raw rate is
`v/h + ω`, and the sim models only the *residual* of the compensation (`flow_gyro_residual`) — i.e.
it presumes the compensation happens host-side. Flow is computed **before** the ToF advance because
`hover_flow` advances its estimator first and reads the pre-refresh `h_meas`; reading the fresh
height would scale the velocity by one the deploy path could not have had yet. And
`--rad-per-count` has **no default**: unmeasured it is the gain of the only loop closing horizontal
drift, and a zero feeds a permanently-zero channel — the exact state the knockout measured as worse
than none. A flow policy refuses to fly without it, which makes the bench calibration
(`rapid-hill-4130`, `modest-raven-7153`) a hard blocker rather than a note.

**The six gates are declared, in the plan and in the battery runner, before any result exists:**
(1) clean pure-hold `mean_xy_error` ≤ 0.05 m; (2) clean mean height 0.15 ± 0.02 m; (3) HARD —
`ep_peak_z_m` ≤ 0.45 m and zero floor exits anywhere in the battery; (4) m1live 30 s survival
≥ 0.98; (5) `flow_valid_rate` ≥ 0.95 on m1live; (6) the knockout degrades survival **and** the flow
arm beats `desk-flow-noflow` on gate 1. Gates 5 and 6 exist because a policy can post a fine
`mean_xy_error` while flying on a faded-to-zero channel — an open-loop policy wearing a closed-loop
metric — and because a GREEN that survives its own knockout was never about the channel.

## Repo

- repo: git@github.com:theo-kirby/neural-whoop.git
- branch: main
- commit: 64f32eef4d9d9f10d32bca741e89e0aff12e2f1b

## State Impact

- target: modest-raven-7153 — the pilot now accepts an obs-8 hover_flow policy end to end (task-keyed family gates in BOTH directions since base_obs_dim 8 was already the acro obs; the flow channel built before the ToF advance to match the sim's order; a single flow_delta consumer; flow_lost abort whose clock starts at FREE FLIGHT because the whole take-off happens under the sensor's 80 mm working range; CSV 31 -> 33 cols with the fed vx/vy). Also fixes a latent bug: props-off `check` fed a 5-dim frame to a 6-dim ToF policy and silently dropped a weight column.
- target: rapid-hill-4130 — the ToF zero-offset now blocks TWICE: at 0.15 m the uncalibrated +23.9 mm offset is 16% of the setpoint AND 16% of the flow velocity scale, because the host multiplies flow counts by the measured height. --rad-per-count has no default and a flow policy refuses to fly without the slide-test measurement.
- target: NEW optical-flow-calibration — the sim now models SUSTAINED loss (flow_blackout_prob/flow_blackout_s), not just single-frame speckle: at dropout 0.02 the chance of losing a whole second is 1e-85, so every prior flow result trained a policy that had never seen the failure the deploy path is built to abort on. Default OFF so those results stay comparable. Two constants derived rather than guessed: flow_scale_frac 0.20 covers the ToF offset's 16% velocity error at 0.15 m plus slide-test error; flow_blackout_prob 0.0005 is set from gate 5's modeled availability ceiling (0.962).
- target: lucky-lodge-5696 — a THIRD hover operating point is configured, at 0.15 m: the lowest setpoint where both bridge sensors work, since Desk-Hover's 0.10 m plus its measured 1.8 cm sink plus the uncalibrated ToF offset puts the flow sensor at 0.076 m, i.e. blind — the state staid-moon-7407 measured as worse than never having the channel. Configured and gated, NOT yet trained or flown.
