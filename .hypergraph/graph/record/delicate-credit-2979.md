---
node_id: d5c01cce-095e-50c4-bbf2-f1c0bdddd93b
slug: delicate-credit-2979
title: 'Control (CLOSED, no_viable_branch): stock-hardware IMU-only hover campaign — gyro-noise wall SOLVED (d50var_s8, new ★ studio-baseline); latency×noise tail handed to the bench'
created_at: '2026-07-06T21:24:39.651329+00:00'
parents:
- cold-night-8900
- rough-art-1658
summary: 'CLOSED (stop_reason=no_viable_branch, budget 5/6 spent, run 6 unspent deliberately). Campaign outcome: the gyro-noise wall that produced the ''IMU-only is dead, needs flow deck'' verdict is SOLVED in software — d50var_s8 (broken-wildflower-8398, now ★ studio-baseline) survives 89-100% across the deploy band and 61% at the RAW measured 2.5 rad/s floor vs the old flagship''s 0.05%, via per-episode amplitude-DR + obs_stack 8. Residual gap isolated to a single factor: action latency >40 ms during active noise-correction (knockout 29.8->98.2%). Rejection log: action echo (train/eval mismatch RED), jitter distribution-matching (RED, trades noise robustness), recurrent/[128,128]/echo-fix (budget). Handoff: fly d50var_s8 in calm air; bench = link age histogram, gyro amplitude/rho at 50 Hz, latency-tail reduction (100 Hz control rate, ESP command hold, MSP oversampling).'
origin:
  backend: flywheel
  node_id: d5c01cce-095e-50c4-bbf2-f1c0bdddd93b
  slug: delicate-credit-2979
  revision: 7
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 4420aa32-f4b5-5e96-9600-a93dac0cf5da
  slug: green-recipe-2167
  revision: 0
  pushed_at: '2026-08-09T21:27:34+00:00'
  content_sha256: 9f805bb3850a82cbdd4edc0d21589a587ce813b14d55e34be093bf9614795692
---
# Run contract — flywheel-auto, stock-hardware IMU-only hover — **CLOSED 2026-07-07**

User directive (2026-07-06): "keep pushing. we need to find a path forward with no extra hardware besides the stock drone and esp."

## Run contract (final state)

- **Objective:** IMU-only hover policy + deploy contract for stock Air65 II + ESP32, bars M1-live ≥ 85% across band + M2-sensor ≥ 80%.
- **Budget:** 6 training runs. **Spent: 5/6** (d50, d50var, d50var_s8, d50var_s8a, d50var_s8jit) — run 6 deliberately unspent: no candidate had a credible path from 35% to 80% in one run.
- **Compute:** 0 Flywheel credits (all local, per locked decision 3).
- **Stop reason: `no_viable_branch`** (final gate: s8jit M2-sensor-jit 34.9% < the 50% partial threshold).

## What the campaign PROVED (all nodes carry full packs)

1. **The gyro-noise wall — the finding that killed the v2 sweep, the R-ladder, and the flow-deck-only conclusion — is SOLVED in software** (`broken-wildflower-8398`, ★ studio-baseline): per-episode amplitude-DR (`obs_noise_amp_range`) + obs_stack 8 → M1-live 89–100% across 0.5–1.2× the measured amplitude and **61% at the RAW 2.5 rad/s floor** (old flagship: 0.05%). No bridge-averaging assumptions needed.
2. **Mechanism chain, each step one-factor:** amplitude-locked trim (Jensen; `polished-moon-9652`) → fixed by amplitude-DR (`old-violet-0574`) → leveled up by capacity (`broken-wildflower-8398`) → residual killer isolated to **action latency alone** (knockout: latency-off 29.8→98.2%; bias/rate-gain nil) with the cliff at 40 ms.
3. **Metric corrections** (`odd-hat-1222` + M1-live family): old M2-honest was ~30 pts unwinnable kinematics; old zero-noise M1 is unphysical for a vibration-driven gyro.

## Per-candidate rejection log (required by the terminal clause)

- **Action-history echo (s8a, `red-fire-4210`):** RED — uniform eval regression; corrected mechanism = train/eval mismatch (sampled vs deterministic echo). Fix candidate (deterministic-mean echo in training) identified but unbudgeted.
- **Measured-jitter distribution-matching (s8jit, `bold-shadow-8014`):** RED — +5.3 pts on its own distribution, loses noise robustness everywhere else.
- **Recurrent policy / [128,128] / echo-fix retrain:** each needs multi-run exploration; 1 remaining run cannot credibly reach 80% — rejected on budget, not on principle.
- **Honest re-metric alone:** closed — s8 under the measured link = 29.6% ≈ constant hedge; the fragility is physical.

## Handoff (the path forward, stock hardware only)

- **Fly `d50var_s8`** in the calm-air first-flight scenario: at the measured p50 link (24 ms) its per-latency survival is ~71–98%; the danger is the p99 latency tail, not the noise.
- **Bench checklist (deploy box):** (1) measure the true link age *histogram* (the jitter weights are percentile-approximated); (2) measure calm-hover gyro amplitude at 50 Hz sampling + lag-1 autocorr (ρ still unvalidated); (3) shrink the latency tail in the bridge — 100 Hz control rate halves step-quantized staleness; ESP-side command hold/extrapolation; MSP oversampling still helps (drops the operating point down the amplitude curve where survival is 90–100%).
- **Sim follow-ups (new campaign if reopened):** deterministic-mean echo retrain; recurrent policy; latency curriculum.

All six run configs, the two new DR seams (`obs_noise_amp_range`, `action_latency_dist`), the `append_prev_action` env seam, and 20 new unit tests are on main (commits ad7e8a1…7aeceb0+; suite 183 green).