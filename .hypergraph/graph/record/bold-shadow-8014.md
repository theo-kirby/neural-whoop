---
node_id: c9ed54ca-446e-52c1-8572-4a16c8399fca
slug: bold-shadow-8014
title: 'd50var_s8jit (measured-link jitter DR) RED at the final gate — +5 pts on its own latency distribution (29.6→34.9%) but loses noise robustness; the latency×noise interaction is not solved by distribution-matching. Campaign stops: d50var_s8 designated best artifact'
created_at: '2026-07-07T02:22:34.777587+00:00'
parents:
- broken-wildflower-8398
- red-fire-4210
summary: 'd50var_s8jit (action_latency_dist measured-link jitter DR, one factor vs s8, commit 7aeceb0) RED at the final gate: M2-sensor-jit 34.9% (bar 80%, partial threshold 50%) — +5.3 pts on its own trained latency distribution but LOSES noise robustness everywhere else (M1-live@1.0x 99.9->78.8%, d100 18.1->12.1%, constant hedge 29.8->24.3%). The latency x noise interaction (40 ms staleness during active noise-correction -> oscillation floor exit in ~1.5 s) survives hedging, inference, and distribution-matching within this recipe. Campaign stops per the persisted gate: stop_reason=no_viable_branch. Designation: d50var_s8 (broken-wildflower-8398) is the best artifact — dominates the old flagship on every deploy-relevant metric (61.1% vs 0.05% at the raw noise floor) — and the latency tail is handed to the bench (age histogram, 100 Hz control rate, ESP-side command hold).'
origin:
  backend: flywheel
  node_id: c9ed54ca-446e-52c1-8572-4a16c8399fca
  slug: bold-shadow-8014
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
---
# d50var_s8jit: train dist == deploy dist was not enough — the final arm and the campaign verdict

**Hypothesis tested (red-fire-4210's decode + the control gate).** s8's latency fragility is physical (29.6% under the measured link). Training the s8 recipe against the measured-link jitter itself (`action_latency_dist`, commit 7aeceb0; ONE factor: latency model) lets PPO learn gains that stay stable through the bridge's actual staleness pattern → M2-sensor-jit toward 80%.

**Setup.** `configs/hover_blind_air65_d50var_s8jit.yaml` = d50var_s8 with `action_latency_dist [0.25,0.45,0.15,0.07,0.04,0.03,0.01]` (ages 0–6 steps, approximating bench p50 24 ms / p99 112 ms) replacing the constant 0–5 hedge. 3.2B steps.

**Results (30 s pure-hold survival, 2048 drones; [s8jit vs s8]):**

| metric | s8jit | s8 |
|---|---|---|
| **M2-sensor-jit@d50 (gate, bar 80%)** | **34.9%** | 29.6% |
| M2-sensor@d50 (constant hedge) | 24.3% | 29.8% |
| M2-sensor@d100 | 12.1% | 18.1% |
| M1-live@1.0× | 78.8% | 99.9% |
| M1-live@2.0× | 42.7% | 61.1% |

**Decode.**
1. Distribution-matching worked *narrowly*: +5.3 pts on exactly the trained latency distribution — a real but small, honest gain.
2. It paid for that with **noise-robustness ground everywhere else** (M1-live 99.9→78.8% at 1.0×; d100 18.1→12.1%; constant hedge 29.8→24.3%). The recipe reallocated capacity toward stale-packet stability and away from the noise filtering that s8 had mastered.
3. **The latency×noise interaction remains the unsolved core**: with fresh packets the noise is beaten (98%+); with 40 ms staleness under active noise-correction the loop still oscillates to the floor within ~1.3–1.8 s. Neither hedging (s8), inferring (s8a), nor distribution-matching (s8jit) cracked it within this recipe/budget.

**Verdict.** **RED at the final gate** (34.9% < the 50% partial threshold; bar 80%). Per the persisted control gate (delicate-credit-2979): **campaign stops, stop_reason = no_viable_branch** — remaining candidates (recurrent policy; deterministic-mean echo fix; 100 Hz control rate) each need multi-run exploration the 1-run budget cannot credibly fund to 80%.

**Campaign designation: `d50var_s8` (broken-wildflower-8398) is the best artifact** and the recommended next-flagship candidate. It dominates the old flagship (cold-night-8900) on every deploy-relevant metric: 61.1% vs 0.05% survival at the RAW measured noise floor; 99.9% vs ~2% at half-amplitude live sensors; and it needs no bridge-averaging assumptions. Its weakness — the >40 ms latency tail — is a **bridge/bench problem as much as a policy problem**: the measured p50 (24 ms) sits in its survivable zone; the tail (p99 112 ms) does not. Bench work that shrinks the tail (100 Hz control rate halves step-quantized staleness; local ESP-side command hold/extrapolation) attacks the same gap from the cheap side.

**Honesty.** (1) The jitter distribution is percentile-approximated, unvalidated. (2) s8jit's +5 pts is within 6σ of binomial noise (±~1%) — real but marginal. (3) The 80% M2-sensor bar was never reached by any arm; the campaign's honest deliverables are the solved noise wall + the isolated, quantified latency gap — not a bar-clearing flagship. (4) All sim numbers; first-flight ground truth pending.

**Lineage.** Parents: **red-fire-4210** (the gate that selected this arm) + **broken-wildflower-8398** (config fork; the checkpoint this arm tried to improve and did not). Campaign control: delicate-credit-2979 (closes with this node).