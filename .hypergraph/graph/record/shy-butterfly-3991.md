---
node_id: d6c4e03c-9575-5651-8258-64f96bc51a46
slug: shy-butterfly-3991
title: exit_probe.py could never report a floor or ceiling exit — the tool that proved "the altitude loop is closed" had those branches unreachable
created_at: '2026-08-08T15:29:53.154901+00:00'
parents:
- noisy-brook-4394
- black-salad-4817
summary: 'METHOD/CORRECTION: scripts/exit_probe.py classified crash direction from env.dyn.pos read AFTER env.step(), but step() auto-resets crashed drones IN PLACE (envs/base.py: reset_idx runs inside step) — so the position it classified was the RESPAWN, which is inside the bounds by construction. The `floor` and `ceiling` branches were structurally unreachable and every exit fell through to `xy`; the script could only ever print floor: 0, ceiling: 0. That is exactly the "ALL M1-live failures are horizontal / the altitude loop is closed" finding quoted into docs/TASK_CATALOG.md and docs/SIM2REAL.md and asserted across the whole hover_tof ladder ("zero floor/ceiling exits anywhere in the probe battery"). Measured before the fix on the shipped-line parent (hover_tof_air65_w128u15_r25, 2048 pure-hold drones, 30 s, seed 12345) on its own full-DR config: 793 exits, floor 0, ceiling 0, xy 793. Fixed by stashing the post-dynamics / pre-reset position at the moment is_crashed sees it. Re-measured, same ckpt and seed: full-DR 72 floor / 3 ceiling / 718 xy (9.5% of the crashed cohort is VERTICAL, not zero); m1live 100% survival so 0/0/0; m2sensor 3 exits all horizontal. So the claim HOLDS on the noise twins — but only because survival there is ~100% and there is almost nothing to classify — and FAILS on the full-DR config. Either way the original battery could not have distinguished the cases, so the conclusion was unearned as stated. survivor_mean_z_err had the same stale read and reported 0.0; it is really 0.198-0.218 m. Both docs now carry the correction rather than the conclusion. Found while building the Desk-Hover four-gate battery, whose gate 3 ("zero floor exits") the shipped tool would have passed unconditionally.'
origin:
  backend: flywheel
  node_id: d6c4e03c-9575-5651-8258-64f96bc51a46
  slug: shy-butterfly-3991
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 917d3430-78a8-5982-990f-d8c59d5b863e
  slug: red-frog-4758
  revision: 0
  pushed_at: '2026-08-09T21:28:32+00:00'
  content_sha256: 0e97a9fd1a8b10bd23c1b3446f4fd769d4ce24ccbbed2ec1d8eea6d0077d8b62
---
## What was wrong

`scripts/exit_probe.py` decomposes hover-family crashes into floor / ceiling / horizontal. It did:

```python
obs, _r, term, _tr, info = env.step(a)
crashed = info.get("crashed", term).bool()
pos = env.dyn.pos                      # <-- AFTER the step
floor = pos[:, 2] <= bounds.z_min + 1e-3
ceil  = pos[:, 2] >= bounds.z_max - 1e-3
k = torch.where(floor, 1, torch.where(ceil, 2, 3))
```

But `MultiAgentDroneEnv.step()` **auto-resets crashed drones in place** — `reset_idx` runs *inside*
`step`, before it returns. So `env.dyn.pos` for exactly the drones being classified is the **fresh
respawn**, and a respawn is inside the bounds *by construction* (the spawn z is clamped into
`[z_min + margin, z_max - margin]`).

**`floor` and `ceil` were therefore unreachable branches.** `k` was always 3. The script could only
ever print `floor: 0, ceiling: 0`, for any policy, on any config, forever.

## Why it matters

That is precisely the finding the script was cited for. Its own docstring: *"committed for the
hover_tof battery, where it showed ALL M1-live failures are horizontal (0 floor / 0 ceiling) — the
altitude loop is closed."* And `docs/TASK_CATALOG.md`: *"**zero floor/ceiling exits anywhere in the
probe battery** (`scripts/exit_probe.py`) — the vertical loop is closed"*, repeated for the 4-arm
ladder (*"Zero floor/ceiling exits in every probe of every arm"*), and echoed in
`docs/SIM2REAL.md`.

**A measurement that cannot produce the negative outcome is not evidence for the positive one.**

## Measurement (before)

Shipped-line parent `hover_tof_air65_w128u15_r25/ckpt_final.pt`, 2048 pure-hold drones, 30 s,
seed 12345, DR on, on its own full-DR training config:

| | survival | floor | ceiling | xy |
|---|---|---|---|---|
| as shipped | 0.6128 | **0** | **0** | **793** |

793 crashes, every one attributed horizontal.

## The fix

Stash the post-dynamics / pre-reset position at the moment `is_crashed` actually sees it, by
spying on `task.reward_and_done` (which the env calls after dynamics and before `reset_idx`):

```python
_real = env.task.reward_and_done
def _spy(e, a):
    _stash["pos"] = e.dyn.pos.clone()
    return _real(e, a)
env.task.reward_and_done = _spy
```

`survivor_mean_z_err` used the same stale read — the old docstring flagged the *symptom* ("treat it
as junk unless the horizon is shorter than the episode") without the cause — and is now taken from
the stashed position too.

## Measurement (after) — same checkpoint, same seed

| config | survival | floor | ceiling | xy | survivor_mean_z_err |
|---|---|---|---|---|---|
| full training DR | 0.6128 | **72** | **3** | 718 | 0.218 m |
| m1live twin | 1.0000 | 0 | 0 | 0 | 0.198 m |
| m2sensor twin | 0.9985 | 0 | 0 | 3 | 0.209 m |

## Verdict / honesty

**The claim holds on the noise twins and fails on the full-DR config.** m1live survives 100%, so
there is essentially nothing to classify there and "0 floor exits" is true but nearly vacuous.
Under full training DR, **9.5% of the crashed cohort exits vertically** (72 floor + 3 ceiling of
793) — the altitude loop is *not* uniformly closed, it is closed in the conditions the twins model.

The deeper point is not which way the number went: it is that **the original battery could not have
told the difference**, so every "zero vertical exits" statement in the record was unearned at the
time it was made. Both docs now carry the correction next to the original claim rather than a
silent edit, so a reader of the older nodes can still interpret them.

`survivor_mean_z_err` reading a flat 0.0 across every probe should itself have been the tell — a
surviving population sitting *exactly* on its setpoint is not a plausible measurement.

## How it was found

Building the Desk-Hover four-gate battery (`black-salad-4817`), whose gate 3 is
*"`ep_peak_z_m` <= 0.30 m AND **zero floor exits**"*. The shipped tool would have passed that gate
unconditionally — on any policy, including one flying straight into the desk. Checking the tool
before trusting the gate is what surfaced it.

## Lineage

- `noisy-brook-4394` — the parent whose probe battery this corrects.
- `black-salad-4817` — the Desk-Hover design work whose safety gate required a trustworthy probe.