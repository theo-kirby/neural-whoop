---
node_id: 61c80d75-2950-59ac-9947-0f2f1982387d
slug: broken-wildflower-8398
title: 'd50var_s8 (obs_stack 8): NOISE SOLVED — M1-live 89–100% across the trained band, 61% at the raw measured floor; knockout decomposition isolates ACTION LATENCY as the sole residual killer (latency-off: 29.8%→98.2%)'
created_at: '2026-07-07T00:28:33.985915+00:00'
parents:
- old-violet-0574
summary: 'd50var_s8 (obs_stack 3->8 on the amplitude-DR recipe, one factor, commits 7271679/1b94e91): the gyro-noise wall is SOLVED — M1-live 89.3/100/99.9/90.0/75.2/61.1% across 0.5-2.0x the d50 center (d50var: 58/57/44/29/15/4%), including 61% at the RAW measured 2.5 rad/s floor with no bridge-averaging assumptions. M2-sensor@d100 2.7->18.1%. But M2-sensor@d50 stuck at 29.8% (1.28 s median exits); channel-knockout decomposition isolates ACTION LATENCY as the sole residual killer: latency-off 98.2%, bias-off/rate-gain-off no change; per-latency survival ~98/71/10/8/~0% at 0/1/2/3/4+ steps (cliff at 40 ms; bench-measured bridge p50 24 ms / p99 112 ms). Structural cause: obs-5 has no action echo so the delay is unobservable. Verdict GREEN-on-noise; next arm d50var_s8a = append_prev_action action-history obs (commit c621a24, running), frame [obs5, last_sent_action], obs 72. Budget 4/6.'
origin:
  backend: flywheel
  node_id: 61c80d75-2950-59ac-9947-0f2f1982387d
  slug: broken-wildflower-8398
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
---
# d50var_s8: the capacity lever lands — and the residual enemy has a name

**Hypothesis tested (old-violet-0574's decode).** d50var's miss was capacity/precision: [64,64] on obs_stack 3 cannot simultaneously estimate the episode's noise amplitude and hold a tight trim across a 4× band. obs_stack 3→8 (ONE factor, commits 7271679/1b94e91) should lift the whole M1-live curve.

**Setup.** `configs/hover_blind_air65_d50var_s8.yaml` = d50var + obs_stack 8 (input 40 → [64,64]). 3.2B steps, ~57 min. Stack-8 eval twins (commit c621a24).

**Results (30 s pure-hold survival, 2048 drones).**

M1-live curve (clean world, live sensors):

| × d50 center | d50var_s8 | d50var (stack 3) |
|---|---|---|
| 0.5× | 89.3% | 58.4% |
| 0.8× | **100.0%** | 57.2% |
| 1.0× | **99.9%** | 43.5% |
| 1.2× | **90.0%** | 29.4% |
| 1.5× | 75.2% | 14.8% |
| 2.0× (= raw floor 2.5 rad/s) | **61.1%** | 4.2% |

M2-sensor@d50 29.8% (d50var 26.2%), median exit **1.28 s**; M2-sensor@d100 **18.1%** (d50var 2.7%); M2-honest@d50 10.6%; old zero-noise M1 0% (exit 14.7 s).

**The knockout decomposition (the decisive measurement).** M2-sensor differs from M1-live by three channels; turning each off one at a time (configs `_nobias/_norg/_nolat`, commit c621a24):

| knockout | survival |
|---|---|
| full M2-sensor | 29.8% |
| − gyro bias | 29.9% (no change) |
| − rate_gain | 29.9% (no change) |
| **− action latency** | **98.2%** |

Latency cliff (uniform 0..max): 98.2 / 84.5 / 59.5 / 46.6 / 29.8% at max 0/1/2/3/5 → per-latency survival ≈ **98 / 71 / 10 / 8 / ~0%** at 0/1/2/3/4+ steps. The cliff is at 2 steps = **40 ms**.

**Decode.**
1. **The gyro-noise problem — the wall that killed v2, the R-ladder, and d50 — is SOLVED** by amplitude-DR + stack-8: 90–100% in the deploy-relevant core band, and 61% even at the RAW measured vibration floor with zero bridge-averaging assumptions. (For calibration: the un-hardened flagship scores 0.05% there.)
2. **The residual killer is action latency, alone**: bias and rate-gain knockouts move nothing; latency-off recovers 98.2%. The 1.28 s median exits are delayed-feedback oscillation crashes, not trim sinks. Deploy read: the bench-measured bridge is p50 24 ms (≈1 step → ~71% survival) with p99 112 ms spikes (→0%) — the DR's per-episode-constant latency 0–5 is a harsh hedge, but the real link's jitter tail is genuinely in the lethal zone.
3. Why latency is unlearnable here: obs-5 carries **no action echo** — the policy cannot see what it commanded, so delay is unobservable and uncompensable. That is a *structural* obs gap, not a capacity gap.
4. obs_stack 8 vs 3 changed M2-sensor only 26.2→29.8% — consistent with (3): more obs history cannot reveal the delay without the action stream.

**Verdict.** **GREEN on the noise objective** (the campaign's original enemy is beaten at deploy-relevant amplitudes); the remaining gap is a **newly-attributed, structurally-fixable factor**. Next arm (running): **d50var_s8a** = + `append_prev_action` (commit c621a24) — the last commanded action appended to every frame after noise (the pilot knows exactly what it sent; noise-free by construction), giving the stacked history aligned (obs, action) pairs for predictive delay compensation. ONE factor. Deploy contract: frame = `[roll,pitch,p,q,r, a_thrust,a_p,a_q,a_r]`, obs_dim 72.

**Honesty.** (1) M1-live ≥85%-across-band bar still not met at 1.5–2.0× (75/61%) — "solved" means the deploy-relevant core (≤1.2×, i.e. any halfway-functional bridge averaging), not the whole hedge band. (2) M2-sensor's uniform-0..5 latency overweights the tail vs the measured link distribution (p50 1 step); a measured-distribution M2 variant would read higher — not built yet to avoid metric-shopping mid-campaign; the fix being trained attacks the delay itself instead. (3) Per-latency estimates are differences of uniform mixtures (±~2–3%). (4) White-noise spectrum / ρ still unmeasured.

**Lineage.** Parent: **old-violet-0574** (d50var; one-factor capacity fork per its gate). Child: d50var_s8a (running). The knockout probes also retroactively explain d50var's fast M2-sensor exits (same 2.0 s signature).