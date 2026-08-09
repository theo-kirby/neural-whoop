---
node_id: b8fb6a5c-370e-5385-b507-13abbeb9cc52
slug: noisy-brook-4394
title: 'hover_tof_air65_w128u15_r25 (tof_rate_hz 40→25, the honest sensor rate): 3 of 4 gates for the FIRST time in the ladder — M1-live 1.0× 95.3→99.4%, 1.2× 64.2→90.2%, m2sensor 36.4→43.5%, crash rate 7.7× lower — but clean tracking breaks (z err 0.047→0.060 m, pure-hold drift 0.07→0.79 m); PARETO'
created_at: '2026-07-30T22:48:59.949221+00:00'
parents:
- tiny-glitter-0842
- calm-base-6054
summary: 'hover_tof_air65_w128u15_r25 3.2B (ONE factor vs the shipped calm-base-6054 w128u15: task.tof_rate_hz 40.0→25.0, the rate tiny-glitter-0842 measured on hardware at 24.8–27.1 Hz). Retraining against the height channel the drone ACTUALLY has takes the ladder from 0 of 4 gates to 3 of 4 — M1-live 1.0× 95.26→99.37% (≥98 ✅, first pass in the line), 1.2× 64.16→90.23% (≥85 ✅), m2sensor 36.38→43.51% (≥42 ✅), full-DR 17.6→21.7%, M1-live crash rate 3.26e-5→4.23e-6 per step. THE CONTROL that makes it credible: on the UNCHANGED 40 Hz twins the retrain wins by the same margin (99.32% / 43.99%) while the parent reproduces its historical numbers to 4 decimals (0.9536 / 0.3647) — so this is a genuinely more robust policy, not a policy scored in its own world. THE COST, and the 4th gate: no-DR z err 0.047→0.060 m (≤0.05 ✅→❌, first failure in the line), and pure-hold clean drift 0.069→0.787 m with hold_rate 1.00→0.23 (0.548→0.765 m under live sensors). hover_tof obs carries no horizontal position channel, so that drift is open-loop and set purely by clean-trim leveling quality — the ToF loop itself is unaffected (z err under live sensors 0.022 m, unchanged). PARETO, no outcome tag: the robustness/precision frontier moved, it did not disappear. n=1 seed. Commits d1d891b (config) / 8fc51b3 (reproducible probe twins); battery in runs/hover_tof_air65_w128u15_r25/probes.json.'
origin:
  backend: flywheel
  node_id: b8fb6a5c-370e-5385-b507-13abbeb9cc52
  slug: noisy-brook-4394
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
---
# hover_tof_air65_w128u15_r25: training against the sensor we actually have

## Hypothesis

From `tiny-glitter-0842`, defect 3: the pilot's genuinely-fresh ToF rate is **24.8–27.1 Hz**, not the 40 Hz every policy in the hover_tof ladder trained against — the VL53L1X free-runs at 25 ms and polling + UDP jitter eats the rest. So every ladder policy saw a height channel ~1.6× fresher than the one it flies. The retrain config predicted a binary: *"if nominal hold_rate survives, this is a free faithfulness win and becomes the new baseline; if it degrades, that degradation was ALWAYS there in deployment and the ladder was measuring an optimistic sim."*

Neither branch is what happened. The honest rate made the policy **more robust and less precise** — the trade the whole ladder has been fighting, relocated.

## Setup

`configs/hover_tof_air65_w128u15_r25.yaml` = the shipped `w128u15` deploy config with `task.tof_rate_hz 40.0 → 25.0`, **one factor**, everything else byte-identical (same [128,128], same DR battery, same 0.5–1.1 m band, same seed 0). 3.2e9 steps @ ~1.00M SPS, ~53 min on the 5090; no divergence (final approx_kl 1e-4, LR fully annealed).

Scored on **honest-rate eval twins** (`configs/hover_tof_air65_{m1live,m2sensor}_r25.yaml`, committed in 84e254e) — because scoring a 25 Hz-trained policy on the 40 Hz twin measures the twin, not the policy. 2048 pure-hold drones, 30 s, deterministic mean, seed 12345.

Two probe twins were **added** this node because the ladder's two most-quoted numbers could not be re-run from the repo — the 1.2× tail came from hand-editing `obs_noise_amp_range` and the pure-hold precision numbers from hand-editing `hold_fraction`. Both are now `configs/hover_tof_air65_m1live_r25_amp12.yaml` and `configs/hover_tof_air65_purehold_r25.yaml`, verified to reproduce the scratch numbers exactly (commit `8fc51b3`).

## Results

### The 4-gate battery: 0 of 4 → 3 of 4

| gate | bar | w128u15 (parent) | **w128u15_r25** | |
|---|---|---|---|---|
| no-DR z err | ≤ 0.05 m | 0.047 | **0.060** | ❌ first failure in the line |
| M1-live 1.0× | ≥ 0.98 | 0.9526 | **0.9937** | ✅ first pass in the line |
| M1-live 1.2× | ≥ 0.85 | 0.6416 | **0.9023** | ✅ +26.1 pts |
| m2sensor | ≥ 0.42 | 0.3638 | **0.4351** | ✅ +7.1 pts |

Also: full-training-DR survival 0.1763 → **0.2168**; no-DR survival 100% both; M1-live crash rate **3.26e-5 → 4.23e-6 per step (7.7× lower)**.

No arm of this ladder had ever passed more than one gate ([192,192] passed m2sensor alone, at the cost of two others).

### The control: it wins in the world it did NOT train in

The obvious objection is that a 25 Hz policy scored on 25 Hz twins is grading itself. So both policies were re-scored on the **unchanged 40 Hz twins**:

| 40 Hz twin | w128u15 (parent) | w128u15_r25 |
|---|---|---|
| M1-live 1.0× | 0.9536 | **0.9932** |
| m2sensor | 0.3647 | **0.4399** |

The parent reproduces its historical ladder numbers (`calm-base-6054`: 0.9536 / 0.3647) **to four decimals**, so the harness is deterministic and none of these deltas are probe noise. And the retrain wins by essentially the same margin at 40 Hz as at 25 Hz — the eval-side rate barely moves any policy's score. **The gain is a training-time effect, not a rate-matching artifact.**

### The cost: clean-world trim

Pure-hold cohort (every drone spawns on the setpoint, level, at rest — the first-flight scenario), 2048 drones, 30 s:

| | parent, clean | **r25, clean** | parent, M1-live 1.0× | **r25, M1-live 1.0×** |
|---|---|---|---|---|
| mean pos error | 0.069 m | **0.787 m** | 0.548 m | **0.765 m** |
| hold_rate | 1.00 | **0.23** | 0.378 | **0.282** |
| mean tilt | 0.078° | **1.035°** | 4.82° | **4.46°** |
| mean z err | 0.045 m | **0.058 m** | 0.022 m | **0.023 m** |
| crash rate/step | 0 | **0** | 3.26e-5 | **4.23e-6** |

Decode: `hover_tof` obs is `[roll, pitch, p, q, r, h_err]` — there is **no horizontal position channel**, so horizontal drift is open-loop and set entirely by how well the policy holds level. The parent is a rock in the clean world (7 cm over 30 s) and the retrain wanders 0.79 m. The **altitude loop is untouched** (live-sensor z err 0.022 → 0.023 m); what regressed is clean-world trim. Under live sensors the retrain actually holds a *lower* mean tilt (4.46° vs 4.82°) while drifting further — consistent with a small residual trim bias rather than noisier attitude control.

## Verdict / Honesty

**PARETO — no `outcome:` tag.** The robustness/precision frontier moved; it did not disappear. Three noise gates for the first time and a 7.7× lower crash rate, paid for with the clean-tracking gate.

Things this node does **not** show:

- **n = 1 seed** per arm. The harness is deterministic (the parent's exact historical reproduction proves it), so the deltas are not *measurement* noise — but seed-to-seed *policy* variance is untested, and a +26 pt swing on the 1.2× tail is large enough to demand a replicate. That is the next control.
- **The mechanism is a hypothesis, not a measurement.** Plausibly the staler height channel acts as a training-time regularizer, forcing the policy onto its 8-frame obs stack instead of an instantaneous `h` — which would also explain why the gain transfers to the 40 Hz world. Untested. Direct test: train the 40 Hz config with the height channel held every other step and see if the same robustness appears.
- **No real flight.** This is sim-side only. `tiny-glitter-0842`'s five bench flights included zero successful hovers, so nothing here is validated against hardware behaviour — only against a hardware *measurement* of one channel's rate.
- **The ladder's clean-hover numbers were partly a fiction.** The parent's celebrated 0.22° / 7 cm hover was measured in a world with a height channel 1.6× fresher than reality. This node does not re-measure the parent's *real* clean hover — it can't; the parent would have to be re-scored against a live drone.
- The 40 Hz twins are kept unchanged and nothing in the parent's record was rewritten.

**Recommendation:** the retrain should become the deploy candidate — for a first real flight a crash is unrecoverable while 0.8 m of drift over 30 s is pilot-correctable in a room. Moving the `★ studio-baseline` pointer is the user's call, not the graph's, and is deliberately left un-moved here.

## Lineage

- Parent `tiny-glitter-0842` (ToF characterized on hardware) — its defect 3 is the entire premise of this node, and its closing line ("train `hover_tof_air65_w128u15_r25` and A/B it against the shipped baseline") is what this node executes.
- Parent `calm-base-6054` (`hover_tof_air65_w128u15`, ladder arm 2) — the policy retrained here and the control in every A/B above; the 4-gate battery is its definition.

Commits: `d1d891b` (rate 40→25 + retrain config), `84e254e` (honest-rate eval twins), `8fc51b3` (reproducible 1.2× / pure-hold probe twins). Battery: `runs/hover_tof_air65_w128u15_r25/probes.json`.

Next: (1) seed replicate of this arm; (2) `upright_scale` on top of r25 — arm 2's lever, which bought leveling before, aimed at recovering the clean-trim gate without giving back the tail; (3) re-flight on hardware with the corrected pilot path, which is the only thing that can tell us whether any of this is real.