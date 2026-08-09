---
node_id: cc831803-d6c9-5f39-9c0e-77777fe10409
slug: wispy-wood-0453
title: 'acro_flip v2 setup: the v1 flip MEASURED (0.672 m drift, 0.410 m dropped, 0.000 m climbed) — obs-8 maneuver clock, a point-in-space reward, and the deploy throttle floor the coast walks into'
created_at: '2026-07-31T21:11:27.062414+00:00'
parents:
- hidden-field-0837
- lively-block-9924
summary: 'The hero video showed the v1 flip honestly and what it showed is a real weakness. Measured off that replay (FLIP+RECOVER, referenced to the trigger point): max_lateral_drift 0.672 m, altitude_loss 0.410 m, peak_climb 0.000 m, settle_pos_error 0.764 m. peak_climb is EXACTLY zero — v1 never pops, it only falls. Not a rendering artifact: v1''s reward had NO lateral term at all, a symmetric alt_scale*|z-z0| that punished the very pop a tight flip needs, and an alive_bonus (0.1 x 200 = 20) that was the largest term in the episode. "Maximise rotation, ignore translation" IS a barrel roll. v2, roll axis only: (1) obs-7 -> obs-8 with a maneuver_phase CLOCK, because the blocker is OBSERVATIONAL — with obs-7 a level, at-rest drone is a fixed point (gravity_body is pure attitude, carrying no specific force), so a vertical thrust burst is INVISIBLE and the policy cannot time a pre-roll pop at all. No new sensor: the clock is the pilot''s own, same class as rotation_remaining; the ToF is deliberately unused (it points sideways then up mid-flip). (2) lateral station-keeping. (3) ASYMMETRIC altitude — heavy sink, light rise past pop_allow 0.4 m — which LICENSES the pop; the physics says the desired shape is its optimum. (4) alive_bonus 0.1 -> 0.02. Plus the sim2real item that decides transfer: ActionLimits.min_thrust_normed = 0.25, mirroring the pilot''s free-flight throttle clamp, because we are now rewarding a COAST the deploy path would silently rewrite. Default 0.0 keeps every other task bit-identical. SETUP + BASELINE ONLY — the 400M-step retrain is 5090 work and has NOT run; no outcome tag until it does. CPU smoke (200k steps) runs clean, obs_dim 8, all eight metrics populate, no NaN. Commit 99b7741.'
origin:
  backend: flywheel
  node_id: cc831803-d6c9-5f39-9c0e-77777fe10409
  slug: wispy-wood-0453
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 50c31aea-9aea-5363-bedc-d2f24d8df84c
  slug: shiny-poetry-9440
  revision: 0
  pushed_at: '2026-08-09T21:28:18+00:00'
  content_sha256: 5e9590147f9bc57943bbf9da2098165ea16e6ed8428c358fd1247b1ba096f729
---
## Hypothesis

Theo's description of what the flip should look like: **lift off, a burst of thrust with a nudge of off-centredness at the end of it, coast around the rotation, catch it level at roughly the same point in space.** The v1 policy does not do that, and the claim of this node is that the gap is **the reward and the observation**, not the renderer and not the training budget.

Testable prediction: a reward that (a) penalises lateral drift at all, (b) is *asymmetric* in altitude so a pre-roll pop is free while sinking is not, and (c) is not swamped by an alive bonus, has the pilot's shape as its **optimum** — and the policy can only reach it if it can *see* the start of the maneuver, which obs-7 does not let it do.

## Setup

### The baseline, measured rather than described

`runs/acro_flip/` has no checkpoint (only the exported `policy_weights.json`), and the task is now obs-8, so the v1 policy cannot be re-evaluated in the v2 env. What it *does* have is a replay of the flip it actually flew. The shape metrics v1 never measured — it had no lateral term — are pure geometry over those positions, referenced to the position at the flip trigger, which is exactly what "point in space" means.

Over the FLIP+RECOVER window of `runs/acro_flip/hero_seq/replay.json.gz` (frames 180–315, 136 steps, 2.72 s), reference point `(+0.108, −0.142, 0.951) m`:

| | v1 baseline (measured) | v2 target |
|---|---|---|
| `max_lateral_drift` | **0.672 m** | < 0.20 m |
| `altitude_loss` | **0.410 m** | < 0.15 m |
| `peak_climb` | **0.000 m** | 0.2–0.4 m (the pop — *should* rise) |
| `settle_pos_error` | **0.764 m** | — |
| `flip_success_rate` | 0.845 (GREEN) | ≥ 0.845 (do not regress) |

`peak_climb` is **exactly zero**: v1 never rises during its own maneuver, it only falls. That single number is the clearest statement of the problem.

### Why v1 does this

Reading `tasks/acro_flip.py` as it was: the reward had **no lateral term whatsoever**; the altitude term was `0.1·|z − z0|`, symmetric and described in its own source as "generous", so it both under-punished sinking *and* punished the pop; and `alive_bonus 0.1 × 200 steps = 20` was the largest term in the episode, diluting all shaping. The policy was doing exactly what it was asked. **A wide loop is what "maximise rotation, ignore translation" looks like.**

### The blocker is observational, not only reward

This is the part that would have wasted a 400M-step run. With obs-7 `[gravity_body(3), p, q, r, rotation_remaining]`, a level-and-at-rest drone is a **fixed point**: `gravity_body` is `Rᵀ·[0,0,−1]`, pure attitude, carrying **no specific force**. A vertical thrust burst is therefore **invisible** to the policy — it cannot distinguish "just spawned" from "0.2 s into a pop", so it cannot time a pre-roll pop and must begin rotating immediately. No reward shaping fixes an unobservable state.

So obs-8 adds `maneuver_phase = clamp(1 − (t − t_trigger)/T, 0, 1)` over `maneuver_len_s = 1.2`, counting 1→0 across pop → rotate → catch.

**Constraint honoured: nothing enters the observation that the real drone does not have.** The clock is not a sensor — it is the pilot's own, the same class of signal as `rotation_remaining`, which the v1 docstring already described as "supplied by the pilot's maneuver clock at deploy". Zero new hardware. The downward VL53L1X is deliberately **not** used: it points sideways and then up mid-flip, i.e. it is garbage exactly when the maneuver needs it.

Both phase channels are kept, and the pair is the point: the **clock** lets the policy *plan* (pop now, rotate now, catch now), while the **gyro-integrated rotation** keeps it honest if DR makes the roll run long or short. A clock alone would run out mid-inversion under a low `rate_gain_frac` draw — which is exactly a draw the DR config makes.

## Results

Commit `99b7741`. This node is **setup + baseline**, not a training result.

### The reward (`configs/acro_flip_v2.yaml`)

Kept: `rotation_progress`, `completion_bonus`, the recover-gated upright bell, `spin_penalty`, `smoothness_penalty`, `crash_penalty`. Changed:

| | v1 | v2 |
|---|---|---|
| lateral `−k·‖xy − xy₀‖` | **absent** | `lat_scale 1.0`, throughout |
| altitude | symmetric `0.1·\|z − z₀\|` | `sink_scale 1.0` · (z₀−z)₊, `rise_scale 0.2` · (z−z₀−`pop_allow`)₊, `pop_allow 0.4 m` |
| settle / return | absent | `settle_scale 0.2` · (lat + \|Δz\| + ‖vel‖), recover-gated |
| `alive_bonus` | 0.1 | 0.02 |

**The asymmetry is the load-bearing change**, and the physics says the desired shape is this reward's optimum. A 2π roll at the 12 rad/s envelope takes ≥ 0.52 s; a zero-thrust coast that long falls ~1 m. Entering with `v_up ≈ g·t/2 ≈ 2.4 m/s` puts the apex mid-flip and returns to `z₀` at `−2.4 m/s`, which ~3 g of net thrust arrests in 0.08 s / 0.10 m. Net: **~+0.3 m up, ~−0.1 m down, ~zero lateral** — because a coast applies no lateral force at all. That *is* the shape Theo described.

New metrics next to `altitude_loss`: `max_lateral_drift`, `peak_climb`, `settle_pos_error`. The spawn point also rides the replay's `scene.target` channel, so "in place" is visible on screen and not only in a table.

### The sim2real trap the coast walks into

We are now rewarding **near-zero throttle mid-flip**, and the real drone will not do that:

1. `pilot/controller.py` clamps `t_des = max(p.min_thrust_frac, …)` with `min_thrust_frac = 0.25` in free flight. The sim had **no such floor**, so a policy trained without it learns a profile the pilot **silently rewrites** — divergence exactly where the maneuver is most sensitive.
2. Worse, the floor exists for a recorded reason: at idle throttle **with no AIRMODE** the airframe loses **rate authority**. That is precisely the `AIRMODE flip stall` failure already on the bench record. A coast-based flip walks straight into it.

Fix: `contract.ActionLimits.min_thrust_normed`, applied in `action_to_diffaero`, wired through a new `act:` config section by `experiment.py::make_act_limits`, set to `0.25` in the v2 config — the same number in the same normed units as the deploy clamp. **Default `0.0` keeps every existing task bit-identical** (asserted by test). `scripts/hero_takeoff_flip_land.py` uses the same floor, so the rendered sequence cannot show a maneuver the drone cannot fly; verified the take-off/hover/land half still lands cleanly under it (start and end at rest z, full phase sequence).

> **Deploy prerequisite, flagged not fixed: enable Betaflight AIRMODE before the first real v2 flip.** The sim cannot model loss of rate authority, so the floor is *insurance, not a guarantee*. Consider `min_thrust_frac 0.30` for the first real attempt.

`FlightParams` now enforces `acro_flip_max_s ≥ maneuver_len_s` — the safety window has to *contain* the trained maneuver or it closes mid-catch and hands back a still-tumbling airframe. That moved the backstop 1.0 → 1.4 s for the 1.2 s window; the honest cost is **0.4 s more tumble** before the crash detector re-arms on a failure.

### CPU smoke (not a result)

`scripts/train.py --config configs/acro_flip_v2.yaml --steps 200_000 --n-envs 256 --device cpu`: 32 updates at ~45k sps, checkpoint `obs_dim 8` with actor first layer `(64, 8)`, all eight metrics populate, no NaN, `crash_rate_per_step` 0.000. That is 0.05% of the 400M budget — it proves the seam runs, nothing about whether the trick emerges.

`pytest`: **297 passed**, 1 pre-existing failure (`tensorboard` not installed on this Mac).

## Verdict / Honesty

**No outcome tag. This node resolves nothing** — it is the setup and the baseline measurement. The retrain is 5090 work (this bench Mac has no CUDA) and has not run.

Honest caveats and open risks:

- **The A/B will not be like-for-like.** The v1 baseline numbers come from a *harness replay* of one flip, not from an eval rollout over a population; v2's will come from `task.metrics()` over 8192 envs. Same quantities, different estimators. The v1 checkpoint cannot be re-run (obs-7 vs obs-8, and only the exported JSON weights survive).
- **The reward may not find the pop.** It costs discounted reward up front (γ = 0.99) and pays off ~0.5 s later. Fallback if it doesn't emerge: a short curriculum spawning with upward velocity early in training, annealed to at-rest.
- **Early warning from the smoke run, worth watching:** v2's KL collapses to 0.000 by update 3 where v1 decays 0.008 → 0.001 over the same span, and `ep_ret` sits flat at ~−215 vs v1's ~−10. At an untrained policy's ~1.8 m drift the lateral term dominates the return and flattens the advantage *variance*, which is what shrinks the policy gradient. At 256 envs on CPU this may be nothing; at 8192 it may still be the weight retune the plan already anticipated.
- **`success_tilt_deg` / `completion_bonus` may now dominate the new terms.** Expect one retune; only the 5090 run will show it.
- **obs-8 breaks the deployed acro policy file.** `runs/acro_flip/policy_weights.json` stays obs-7. `check_policy_family_acro` accepts 7 **or** 8 and checks the dim *exactly*, so an old file fails loudly rather than being fed a truncated obs; `hero_takeoff_flip_land.py` asserts 8 outright.
- **Roll axis only.** `configs/acro_flip_pitch.yaml` stays on the v1 reward, expressed in the v2 knobs, and follows only if this lands.
- **v1 remains reproducible.** `configs/acro_flip.yaml` now expresses the v1 reward in the v2 knobs — `sink_scale == rise_scale` with `pop_allow 0` IS the old symmetric term — so the baseline reward is not lost, only the checkpoint.

## Lineage

- `hidden-field-0837` — the hero preset whose render made the wide loop legible; this node is the response to what that video showed. The v1 trajectory it rendered is the one being replaced.
- `lively-block-9924` — the pilot acro-flip harness (obs parity, the bounded FLIP window, the suspended crash detector). obs-8, the maneuver clock and the `acro_flip_max_s ≥ maneuver_len_s` invariant all land in that machinery.
- `divine-heart-1498` — sibling: the camera work that will render the result.

Artifacts: `baseline_shape.txt` (the v1 measurement, verbatim tool output), `smoke_train.log` (the CPU smoke run, all 32 updates with the eight metrics), `run.json` (manifest: git SHA, the full v1-vs-v2 weight diff, the obs layouts, the contract change, the baseline numbers and the v2 targets, and the AIRMODE prerequisite).