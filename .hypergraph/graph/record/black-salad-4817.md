---
node_id: 938b6198-31cc-5a70-9bd8-5406a47a61f6
slug: black-salad-4817
title: 'Desk-Hover: the 0.10 m desk operating point — the crash mechanism becomes structurally impossible, and the dangerous direction flips from up to down'
created_at: '2026-08-08T15:27:14.002132+00:00'
parents:
- steep-mountain-4778
- noisy-brook-4394
- broken-fire-4858
- tiny-glitter-0842
summary: 'Design node for Desk-Hover (configs/desk-hover.yaml, still task: hover_tof) — executing steep-mountain-4778''s 0.1 m idea. Thesis: change the OPERATING POINT, not the sensor suite. The measured crash chain (climb overshoots ~0.37 m -> past the 1.3 m VL53L1X ceiling -> h_err pins negative -> motors-off open-loop -> ~2 m/s floor impact) cannot occur at 0.10 m, because the same 0.37 m overshoot reaches 0.47 m — 13x INSIDE the ceiling. Steps 3-5 of the mechanism are structurally absent rather than mitigated, and the worst case becomes a 10 cm drop onto a desk. Consequence: the dangerous direction flips from UP to DOWN — 8 cm of floor margin against a measured +23.9 mm static ToF offset (tiny-glitter-0842), which is 2.4% of a 1.0 m setpoint but 24% of this one. Four design calls, each with a stated reason: (1) pos_sigma 0.6 -> 0.10, because at 0.6 a 5 cm bias costs 0.65% of per-step reward and the policy could hover 0.2-0.3 m with every number still looking fine; (2) wind_accel_mps2 1.0 -> 0.15 as an HONESTY fix, since drag tau = D_xy/m = 0.30 s turns U(0,1) m/s^2 into 0.15-0.30 m/s of terminal drift the policy has no channel to see or fight; (3) act.min_thrust_normed 0.25 — the FIRST hover config to mirror the pilot''s min_thrust_frac, a gap open the whole ladder; (4) a tof_min_m near-range gate REJECTED as actively dangerous — the sensor reads a stable 23.9 mm (sigma 2.4 mm) at rest, so a 0.04 m gate against bound_z_min 0.010 would freeze the height channel in a 3 cm dead band exactly where the drone dies, reproducing the confidently-wrong-held-channel failure pointed at the floor. Also establishes the lab''s policy naming convention (task names stay snake_case identifiers because the pilot keys deploy semantics off meta["task"] == "hover_tof" exactly; policy/run names are word-word[-word], config filename == run.name == run dir). NOT an ablation: ~12 factors from its parent, no single-factor attribution. Honest scope: bounded-duration hold, not indefinite station-keep — with no position/velocity obs and no flow deck, horizontal drift is open-loop.'
origin:
  backend: flywheel
  node_id: 938b6198-31cc-5a70-9bd8-5406a47a61f6
  slug: black-salad-4817
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: e1ec91ba-3a85-5a23-b0e8-21ce7ac260d1
  slug: royal-heart-3278
  revision: 0
  pushed_at: '2026-08-09T21:28:32+00:00'
  content_sha256: dd38b9a7d705c569c3b22b7377b3b3a8c8987a0198fc7386b944726a8491a879
---
## Idea

Execute `steep-mountain-4778` ("hover_low — a 0.1 m ultra-still hover") as a **config of
`hover_tof`**, not a new task. Hold **0.10 m over a desk** instead of 1.0 m in a 3.5 m arena.

**Desk-Hover is a config, deliberately.** The pilot keys the 6th obs channel's semantics off
`meta["task"] == "hover_tof"` **exactly** (`pilot/policy.py`), so a new task string would silently
make the deployed drone read `vz` where the policy means `h_err`.

## Why the operating point, rather than the sensor suite

The crash mechanism is measured, not guessed (`docs/SIM2REAL.md`, 2026-07-31; the flights in
`broken-fire-4858`), and it is a five-step chain:

1. the climb crosses the setpoint at 1.2-1.9 m/s and the brake is ~0.13 s late;
2. `act[0] = -1.0` maps to motors off;
3. **the overshoot exits the VL53L1X's ~1.3 m trusted band**;
4. `h_est` is then held indefinitely, so `h_err` pins negative — a dead sensor telling the policy
   "you are far above target";
5. motors-off open-loop into the floor at ~2 m/s.

At a 0.10 m setpoint the same measured **0.37 m overshoot reaches 0.47 m — 13x inside the
ceiling.** Steps 3-5 *cannot occur*. This is not a mitigation stacked on top of the failure; it is
an operating point where the failure has no room to exist. And the worst case becomes a 10 cm drop
onto a desk, which makes real-world iteration cheap while the bridge is still being rewired.

## The dangerous direction flips from UP to DOWN

Everything that mattered at 1.0 m was the ceiling. Here it is the floor: **8 cm of margin**
(`bound_z_min 0.010` ~ `WHOOP_REST_Z_M` 0.0092, the height at which the airframe is touching the
desk) against:

- the **+23.9 mm static ToF offset** (sigma 2.4 mm, 629 pre-liftoff samples — `tiny-glitter-0842`).
  2.4% of a 1.0 m setpoint; **24% of this one**. A drone that trusts the reading sits ~2.4 cm low,
  most of its margin, before any control error at all.
- the `h_err` bias DR of +/-0.03, which is now first-order rather than a rounding error.

**Therefore the highest-value follow-up is a pilot-side `tof_cal`, not a sim change.** The pilot
already learns `az_cal` and `lvl_cal` during the on-floor countdown; a ToF zero-offset in the same
branch is the exact analogue. Deferred, not done.

## Four design calls, each with its reason

1. **`pos_sigma` 0.6 -> 0.10** (and `dist_penalty` 0.2 -> 2.0, `hold_radius` 0.35 -> 0.08). The
   parent's length scales are ~10x too big here. At `pos_sigma 0.6` a 5 cm upward bias costs
   0.017/step against a ~2.6/step reward (0.65%) while a mid-episode crash costs ~1960 return — so
   with only 8 cm of floor under the setpoint **the policy could learn to hover at 0.2-0.3 m and
   every reward number would still look fine.** At 0.10 the same bias costs 0.231/step.
2. **`wind_accel_mps2` 1.0 -> 0.15 — an HONESTY fix, not a concession.** Drag is
   `acc = -(D_xy/m)*v` with `D_xy ~ 0.10`, `m ~ 0.030` -> `tau = 0.30 s`. The parent's `U(0,1)`
   m/s^2 is therefore **0.15-0.30 m/s of terminal drift the policy cannot see and cannot fight**
   (no position or velocity channel), i.e. out of a +/-0.6 m box in 4-8 s. A desk indoors has no
   wind. This is the single load-bearing change.
3. **`act.min_thrust_normed: 0.25`** — the **first hover config in the lab to mirror the pilot's
   `min_thrust_frac`**, which has been clamped at 0.25 since 2026-07-31. Every hover policy to date
   learned a throttle profile the deploy path silently rewrites.
4. **A `tof_min_m` near-range validity gate: CONSIDERED AND REJECTED as actively dangerous.** The
   measurement is a *stable* 23.9 mm mean, sigma 2.4 mm **at rest** — the sensor reads fine at
   near-zero range, so there is no near-range invalidity to model. A 0.04 m gate against
   `bound_z_min 0.010` would create a 3 cm dead band **exactly where the drone dies**: below it the
   height channel freezes and tells the policy "you're at target" while it descends into the desk.
   That is the identical confidently-wrong-held-channel shape as the 2026-07-31 crash, pointed at
   the floor instead of the ceiling.

## Naming convention (new, durable — recorded in CLAUDE.md)

Two namespaces, deliberately different:

- **Task names stay snake_case Python identifiers** — they are `@register_task` keys *and* they key
  the deploy path (see above). Not cosmetic.
- **Policy / run names are `word-word[-word]`**, lowercase-hyphenated on disk, Title-Cased in prose:
  `Desk-Hover` -> `runs/desk-hover/`, `configs/desk-hover.yaml`. **Config filename == `run.name` ==
  run dir.** Third word = "iterating on the one before" (`desk-hover-drift`).
- A new operating point of an existing task is therefore **a config with a policy name**, which is
  exactly what this is. The 163 pre-existing runs keep their names; forward-only.

## Honest scope and caveats

- **This is a bounded-duration hold, not an indefinite station-keep.** No position or velocity
  channel, no flow deck -> horizontal drift is **open-loop**, set entirely by leveling quality. The
  parent's own `probes.json`: clean pure-hold drift 0.069 m (`w128u15`) vs 0.787 m
  (`w128u15_r25`) over 30 s; under **sensor noise alone** both arms drift 0.55-0.77 m. On a
  +/-0.6 m desk that is the whole box. Claiming a station-hold would be dishonest.
- **Arm 1 is NOT an ablation.** ~12 factors from `noisy-brook-4394`. It is a new operating point and
  carries no clean single-factor attribution. Only arm 2 (`vxy_penalty` 0 -> 0.5) is one-factor.
- **`is_crashed` is the entire model of the desk.** There is no ground-contact and no ground-effect
  model anywhere in the dynamics (grep-confirmed). Ground effect is genuinely small here (props
  R ~ 15.5 mm -> z/R ~ 6.5 at 0.10 m, <2% augmentation) and biases *safe*.
- **`arena_radius 0.0` is also a correctness fix at this scale:** `is_crashed` measures `|x|,|y|`
  from the ORIGIN (`reward.py`), so a sampled setpoint makes the crash box asymmetric about it. At
  3.5 m in a 6 m box that is a detail; at 0.6 m it is the whole margin. And the setpoint's xy is
  invisible to this obs anyway, so sampling it was pure unlearnable noise.

## An instruction from the parent idea that this work does NOT carry out

`steep-mountain-4778` says **"refit the DR first"** from flight 2's in-flight calibration
(props-on gyro sd p/q/r = 0.091/0.108/0.082 rad/s, lag1 rho 0.60/0.62/0.82). **These configs do
not do that** — they keep the ladder's `obs_noise_std_channels` gyro terms `[1.25, 1.1, 0.75]`,
i.e. **~10-14x more gyro noise than that flight measured**. (An earlier campaign measured ~2.53
rad/s, so the two flight measurements themselves disagree by ~28x and the discrepancy is
unresolved.) Recorded as an open item rather than silently skipped; it is the obvious next probe
and it is orthogonal to everything above.

The `h_err` noise *was* revised: 0.02 -> 0.010, since 0.02 was a documented datasheet placeholder
and the measurement gives a 2.4 mm static sigma plus an airborne trace monotone in ~10 mm steps.
With `amp_range [0.5, 2.0]` that spans 5-20 mm and brackets both. Note that **there is no
quantization seam in `randomization.py`** — a real modeling gap a Gaussian does not fix.

## Code changes this required (all default-preserving, verified bit-identical)

- `tasks/hover.py`: `spawn_z_margin` (was a hard-coded 0.2 m — **a real bug at desk scale**, since
  it clamps every spawn to >= 0.21 m and silently deletes the pure-hold cohort), with an
  `__init__` guard because `torch.clamp(min>max)` returns `max` silently; `vxy_penalty`;
  `band_ceiling_m`; and four metrics (`mean_xy_error`, `mean_height`, `above_band_rate` per-step,
  `ep_peak_z_m` as an `ep_`-prefixed accumulator — `eval/rollout.py` MEANS every per-step tensor,
  so a per-step peak would silently report mean height).
- `studio/rollout.py`: `hover_tof` / `hover_blind_v2` were missing from `GATELESS_TASKS`.
- Verified additive: the parent's `--no-dr` eval reproduces `mean_pos_error 0.9458888173103333`,
  `mean_z_error 0.060028351843357086`, `hold_rate 0.15269465744495392` **bit-identically** before
  and after. Tests 405 -> 423.

## Lineage

- `steep-mountain-4778` — the 0.1 m idea this executes (and whose DR-refit instruction it does not).
- `noisy-brook-4394` — `hover_tof_air65_w128u15_r25`, the config this forks from.
- `broken-fire-4858` — the real flights whose crash this operating point makes impossible.
- `tiny-glitter-0842` — the ToF characterization the entire floor-margin analysis rests on.