---
node_id: bca67c86-607b-5ecc-bea6-6e72e44cadd1
slug: autumn-bell-7061
title: 'Measurement and documentation integrity: a metric that could only return one value, and several published claims that are now false'
created_at: '2026-08-09T18:42:32+00:00'
parents:
- dusty-pine-0511
summary: exit_probe.py was structurally unable to report the vertical exits it was quoted for, and the corrected tool has not been re-run across the earlier ladder arms. Per-step rates were published without denominators. Four documents carry claims their own repo now contradicts.
---
Status: open

## Current

**Not `broken` — the author's own call** [rec: golden-banner-2676]**.** The `exit_probe.py` defect, the re-measured 9.5% vertical exit rate, the missing denominators and the four contradicted documents all stand exactly as recorded. They describe outstanding cleanup, not a component that fails.

This node exists because the project's own record found these [rec: shy-butterfly-3991], not because an
outsider did. Each item below is cited to the node that found it.

**The metric that could only ever return one value.** `scripts/exit_probe.py`
classified crash direction from `env.dyn.pos` read *after* `env.step()`, but `step()`
auto-resets crashed drones in place — so it classified the **respawn**, which is
inside the bounds by construction. The `floor` and `ceiling` branches were
structurally unreachable and every exit fell through to `xy`. That is exactly the
"zero floor/ceiling exits anywhere in the probe battery" finding quoted into
`docs/TASK_CATALOG.md` and `docs/SIM2REAL.md` and asserted across the whole
`hover_tof` ladder. Re-measured on the same checkpoint and seed after the fix: the
claim **holds on the noise twins** (m1live 100% survival, m2sensor 3 exits all
horizontal) but **fails on the full-DR config** — 72 floor, 3 ceiling, 718 xy of a
793-crash cohort, i.e. 9.5% vertical rather than zero. `survivor_mean_z_err` read
0.0 for the same reason; it is really 0.198-0.218 m [rec: shy-butterfly-3991].

Both documents now carry the correction rather than the conclusion [rec: shy-butterfly-3991]. **What has not
happened is a re-run of the fixed tool across the earlier ladder arms**, whose
`probes.json` batteries still contain the stale numbers.

**Rates without denominators.** A published `crash_rate_per_step` of 0.0227 reads
like "2% of drones crash" and actually means 1/44 — *every* drone crashed, after
about 44 steps. `tracking_ok` 0.9773 is 43/44 steps alive, not 98% of drones
tracking [rec: square-art-3812].

**Single-seed results.** Every single-seed `reference_track` result carries an
unmeasured error bar wide enough to flip crash/survive [rec: square-art-3812].

**Documentation drift** [rec: wandering-water-2720]**.** `docs/ROADMAP.md` (2026-07-11) still describes a four-tab
Bench dashboard (Bench/Player/Live/Editor); `CLAUDE.md` says the Studio has two tabs
and the Live tab is gone. `docs/STUDIO.md` still routes `/api/export` "via nw-viz"
and calls the output a "hero MP4", both retired by `broken-tree-7316`, and still
documents `--room-size` and `--no-room-labels` for a walled greybox room the same
node deleted everywhere; it also calls `fit` "the default" where `VIDEO_LOOK` is
`follow`. `docs/ESPNOW.md` still reads "awaiting hardware bring-up" after the
bring-up and after three flights.

## Negative knowledge

- [scope: any metric script in this repo, and any gate built on one | confidence: high | evidence: shy-butterfly-3991] A metric that can only ever return one value passes every gate built on it, silently and forever. The Desk-Hover four-gate battery's gate 3 — 'zero floor exits', a HARD gate — would have passed unconditionally on the shipped tool. The bug was found only because someone built a new battery around the same number. A gate is only as trustworthy as a demonstration that its metric can fail.
- [scope: metrics read after env.step() in this codebase | confidence: high | evidence: shy-butterfly-3991] `env.step()` runs `reset_idx` in place, so any post-step read of drone state is a read of the respawn, not of the terminal state. The fix is to stash the post-dynamics, pre-reset value at the moment `is_crashed` sees it.
- [scope: per-step rate metrics across the whole catalogue | confidence: high | evidence: square-art-3812] Per-step rates need a denominator before they mean anything, and this is the same failure mode as the `ep_`-prefixed accumulators one level further out. Full-horizon means over an episode that is mostly a hold-station tail also mix two regimes, and mix them differently for a policy that crashed early than for one that survived — which is why reference_track numbers must be quoted over the maneuver window, not the episode.

## Provenance

- shy-butterfly-3991 — the exit_probe defect, its blast radius, and the re-measurement
- square-art-3812 — the denominator correction and the single-seed error bar
- broken-tree-7316 — the video-vocabulary and environment changes that docs/STUDIO.md has not caught up with
