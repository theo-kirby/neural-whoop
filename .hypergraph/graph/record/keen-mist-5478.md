---
node_id: 44ef7643-1fa1-5b3d-bc7f-670f9cd34d39
slug: keen-mist-5478
title: 'GREEN: the flow channel more than doubles pure-hold survival (25.6% -> 62.0% full-DR), halves horizontal exits, and pays ~0.10 m of altitude trim'
created_at: '2026-08-12T12:39:37+00:00'
parents:
- shy-light-3409
- soft-breeze-8148
summary: ''
---
## What

Both arms of the flow experiment trained to the full 3.2e9-step budget (44 min each on the 5090,
~1.2M steps/s) and were evaluated. One factor separates them: `hover_flow` (obs 8) vs `hover_tof`
(obs 6) at an identical 0.40 m operating point — same reward, arena, DR, mass band, PPO block and
seed (`configs/flow-hover.yaml` vs `configs/flow-hover-noflow.yaml`, diff is the task name, the
ten `flow_*` knobs, and the two DR array entries).

**GREEN on the claim the channel was built for**, with an honest altitude trade.

## Why

`soft-breeze-8148` showed that attacking drift with a privileged reward proxy for an unobservable
quantity (`vxy_penalty`) trades margin for the metric — NO-GO. The premise of this experiment is
that measuring the quantity instead should work where shaping against it did not. That is a real
prediction and it could have failed: the channel could have been too noisy, too often invalid, or
simply ignored by PPO in favour of the existing leveling strategy.

## Method

Two evaluations, because they answer different questions and disagree in an informative way.

- **`scripts/eval.py --no-dr`** (2048 envs, 1500 steps, deterministic mean): the clean-conditions
  readout — how well does it hold when nothing is wrong.
- **`scripts/exit_probe.py`** (2048 envs, full DR, `hold_fraction` forced to 1.0, deterministic):
  the pure-hold survival battery, split by which bound the first crash crossed. This is the probe
  that matters, and note it is the *post-`shy-butterfly-3991`* version — the one that can actually
  report a vertical exit.

Visual pack: `runs/flow-hover/viz/` (9 artifacts; `--baseline runs/flow-hover-noflow/replay.json.gz`,
so `comparison.png` overlays the two hero trajectories). The `best lap time` panel of that figure is
empty — the renderer is gate-race-shaped and degrades gracefully on a hover task.

## Result

**Full-DR pure-hold survival (`exit_probe`, the headline):**

| | flow-hover | noflow | Δ |
|---|---|---|---|
| survival (30 s) | **62.0%** | 25.6% | **+142% rel** |
| xy exits | 776 | 1518 | −49% |
| floor exits | 3 | 5 | — |
| ceiling exits | 0 | 0 | — |
| median exit | 21.6 s | 14.8 s | +46% |
| `survivor_mean_z_err` | 0.069 m | 0.060 m | +15% |

**Clean (`--no-dr`):** `mean_xy_error` 0.2397 → **0.1747** m (−27%); `hold_rate` 0.564 → **0.717**
(+27%); `mean_pos_error` 0.249 → 0.211 (−15%); `flow_valid_rate` **0.980**.

The failure mode is horizontal in both arms (xy dominates floor+ceiling by ~200:1), which is the
axis the channel addresses, and it halves it. Survival more than doubling on a one-factor obs
change is the largest single-factor effect on this metric in the hover ladder.

**The honest trade — altitude.** Clean `mean_z_error` 0.053 → **0.099** m (+88%) and the flow arm
hovers at 0.303 m against its 0.40 m setpoint, a steady ~0.10 m DC sink (0.40 − 0.303 = 0.097 ≈ the
z error, so it is a trim offset, not noise). It is also a busier policy: `mean_speed` 0.023 → 0.063,
`mean_tilt_deg` 0.27 → 1.05. Two candidate mechanisms, neither tested here: the documented H2
thrust-trim coupling (`tasks/hover.py` — noisy obs channels bias the learned mean hover thrust, and
this arm has two more of them), and capacity contention in the same [128,128] net now taking 64
stacked inputs instead of 48 — the same suspicion `hover_tof`'s own ladder raised and attributed by
knockout. **It does not manifest as floor exits** (3 vs 5 of 2048) and `survivor_mean_z_err` under
DR is nearly unchanged (0.069 vs 0.060), so the sink is real but is not eating the margin the 0.40 m
setpoint was chosen for. Naming it because a 0.10 m sink at a 0.40 m setpoint would be a 0.10 m sink
onto the desk at Desk-Hover's setpoint.

**`comparison.png` shows the mechanism**: the flow hero closes a bounded ~0.07 m circle near the
setpoint; the control's track opens out to x ≈ 0.26 m and never closes. Bounded versus unbounded is
exactly the claim. But the bounded track is a **limit cycle, not a still hover** — the policy orbits
rather than settles, which is consistent with the 2.8× speed and 4× tilt, and is its own finding.

**A metric bug found by the eval and fixed (`31bd044`).** `flow_valid_rate` initially lived only in
`metrics()`, whose episode accumulators zero on reset; `eval/rollout.py` runs exactly one
`episode_len` horizon, so the final auto-reset clobbered it right before the read and the eval
reported **0.0** for a channel that was live 98% of the time. The metric that exists to catch a
faded-out channel claimed a fully faded one — i.e. it would have made a genuine GREEN look like the
exact fraud it was written to detect. Every other `*_rate` avoids this by riding the per-step
`info["metrics"]`; `hover.py`'s own comment documents the trap. Fix is reporting-only: the re-run
eval is bit-identical (`mean_xy_error` 0.17469146847724915 both times). Pinned by
`test_flow_valid_rate_rides_the_per_step_metrics_dict`.

**What this does NOT establish.** It is a sim result against four placeholder constants
(`flow_rate_hz`, `flow_dropout_prob`, `flow_scale_frac`, `flow_gyro_residual`) and a
`rad_per_count` that does not exist yet. If the true scale error is much wider than the ±10%
trained, this arm's robustness is overstated by that gap. Nothing here has touched hardware.
Absolute survival of 62% is also not "good" — it is 2.4× the control on a demanding probe, and it
is not comparable to Desk-Hover's numbers, which are a different box at a different scale.

Named next probes, none run: (1) **knockout** — feed this policy zeroed flow channels to attribute
the altitude regression between the H2 trim mechanism and capacity contention; (2) **width** —
[192,192], the control that capacity contention predicts; (3) `vxy_penalty` arm now that the
quantity is observable, the natural rerun of `soft-breeze-8148` with its premise repaired.

## Repo

- repo: git@github.com:theo-kirby/neural-whoop.git
- branch: main
- commit: 31bd0447868083b99e2e3078ced288128ae4f31b

## State Impact

- target: NEW optical-flow-calibration — the sim side is now ANSWERED and GREEN: measured horizontal velocity in obs beats its one-factor ablation at the same operating point (survival 25.6% -> 62.0% full-DR pure-hold, mean_xy_error 0.240 -> 0.175 m no-DR). The calibration debt is unchanged and is now the whole remaining gap: four placeholder constants plus a rad_per_count that does not exist yet.
- target: cold-pebble-7468 — hover_flow trained to budget and evaluated; flow_valid_rate fixed to ride the per-step metrics dict after the eval reported 0.0 for a channel live 98% of the time (reporting-only, re-run bit-identical).
- target: lucky-lodge-5696 — a second hover operating point exists with a measured survival number (0.40 m, 62.0% full-DR pure-hold, floor exits 3/2048). Does NOT supersede the 1.0 m finding and has not been flown; note the flow arm carries a ~0.10 m DC altitude sink that would matter more at a lower setpoint.
