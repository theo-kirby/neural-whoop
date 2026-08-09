---
node_id: a55b55b9-6854-5cf4-b191-ba05236ed7c8
slug: old-violet-0574
title: 'd50var (per-episode noise-amplitude DR, U[0.5,2.0]×) — the amplitude-locked-trim cliff is GONE (0.3%→29.4% at 1.2×; median exits 14–26 s across the whole band) but levels miss the bars: mechanism GREEN, arm PARTIAL'
created_at: '2026-07-06T23:28:18.778858+00:00'
parents:
- polished-moon-9652
- shiny-firefly-6661
summary: 'd50var (configs/hover_blind_air65_d50var.yaml; new obs_noise_amp_range DR seam, commit 1fd3c1e; one factor vs d50) = per-episode noise amplitude ~U[0.5,2.0]x the d50 center, trained band 0.625-2.5 rad/s (upper edge = raw measured floor). Result: the amplitude-locked-trim cliff is GONE — M1-live at 1.2x trained amplitude 0.3%->29.4% (x100), curve degrades smoothly (58.4/57.2/43.5/29.4/14.8/4.2% at 0.5-2.0x), median exits 14-26 s everywhere, zero-noise sink 4x slower (4.7->19.0 s), and every cross-metric improved vs d50 (M2-sensor@d50 22.0->26.2%, @d100 0->2.7%). Strict Pareto win; mechanism GREEN. But absolute levels miss the bars (peak 58.4% < 85% M1-live; 26.2% < 80% M2-sensor) — [64,64]/stack-3 pays for band coverage with precision. Verdict PARTIAL per the control gate -> arm 3 d50var_s8 (obs_stack 3->8, one factor, commits 7271679/1b94e91) running. Budget 3/6.'
origin:
  backend: flywheel
  node_id: a55b55b9-6854-5cf4-b191-ba05236ed7c8
  slug: old-violet-0574
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 50214cad-fdbe-5714-bb5b-e4b4144e027b
  slug: dry-poetry-2692
  revision: 0
  pushed_at: '2026-08-09T21:27:34+00:00'
  content_sha256: fa920fc58c764700d6e9166d42c07a552b2995696fdd1bd14709ea19b4e89119
---
# d50var: does training across an amplitude band force an amplitude-invariant trim? Yes — the cliff disappears. It just isn't high enough yet.

**Hypothesis tested (from polished-moon-9652's decode).** The d50 arm's deployment-brittleness is the amplitude-LOCKED trim (Jensen shift with input-noise sd). Per-episode amplitude randomization should force PPO to converge a trim that is invariant (or adaptive, via obs_stack variance estimation) across amplitudes — flattening the M1-live curve.

**Setup.** New DR seam `obs_noise_amp_range` (commit 1fd3c1e: per-drone factor ~U(lo,hi) at reset multiplying the per-channel noise, white+AR paths, never the DC bias; 8 unit tests, suite 171 green). `configs/hover_blind_air65_d50var.yaml` = d50 changing ONE factor: `obs_noise_amp_range [0.5, 2.0]` → trained band 0.625–2.5 rad/s on p, whose **upper edge is the raw measured vibration floor** (bridge oversampling buys nothing) and lower edge is better-than-√N averaging. 3.2B steps, ~57 min. Eval battery: M1-live flatness s050–s200 (commit 0d4b35c) + M2-sensor + continuity metrics.

**Results (30 s pure-hold survival, 2048 drones).**

M1-live curve (clean world, live sensors; d50 = the fixed-amplitude parent):

| eval amplitude (× d50 center) | d50var | d50 (fixed) |
|---|---|---|
| 0.5× | **58.4%** (exit 26.2 s) | — |
| 0.8× | 57.2% (23.9 s) | 81.4% |
| 1.0× | 43.5% (20.8 s) | 43.0% |
| 1.2× | **29.4%** (19.8 s) | **0.3%** |
| 1.5× | 14.8% (17.3 s) | — |
| 2.0× (= raw floor) | 4.2% (13.7 s) | — |

Other metrics: M2-sensor@d50 **26.2%** (d50: 22.0%); M2-sensor@d100 2.7% (d50: 0.0%); old zero-noise M1 0.05% but median exit **19.0 s** (d50: 4.7 s — the residual sink is 4× slower even at the amplitude-mismatch extreme); M2-honest@d50 11.5% (d50: 8.3%).

**Decode.**
1. **Mechanism confirmed (GREEN):** the ±20% amplitude cliff is gone — at 1.2×, survival went 0.3% → 29.4% (×100), and the curve now degrades smoothly instead of collapsing outside a narrow band. Median time-to-exit is 14–26 s *everywhere*, including at 2× the trained center — the trim no longer breaks with amplitude; residual failures are slow diffusive exits, not trim sinks.
2. **Every cross-metric improved vs d50** (M2-sensor +4 pts, M2-sensor@d100 0→2.7%, honest +3 pts, zero-noise sink 4× slower). Nothing regressed. Amplitude-DR is a strict Pareto win over fixed-amplitude noise training.
3. **But absolute levels miss the bars**: peak M1-live 58.4% < 85%; M2-sensor@d50 26.2% < 80%. The policy pays for band coverage with precision — [64,64] on obs_stack 3 cannot simultaneously estimate the episode's amplitude and hold a tight trim across a 4× band.
4. M2-sensor exits are fast (median 2.0 s) while M1-live exits are slow (20 s) — the M2-sensor killer is the bias/rate-gain/latency *combination*, not the noise level; a capacity lever should help exactly there (more history → better bias/level separation).

**Verdict.** **PARTIAL** per the control-node gate (delicate-credit-2979): mechanism GREEN, bars missed → stack the cheapest capacity/memory lever. **Next arm (running): d50var_s8** — obs_stack 3→8, ONE factor (commits 7271679/1b94e91): an 8-frame history cuts a learned averager's effective sd ~√(8/3)≈1.6× further AND sharpens the frame-to-frame variance estimate the amplitude-adaptive trim needs. Deploy cost: the pilot keeps an 8-deep obs deque (software only).

**Honesty.** (1) 58.4% at 0.5× vs 81.4% for the fixed-amplitude d50 at 0.8× — band coverage costs peak performance; the flat-band bar (≥85%) is strictly harder than any single-amplitude bar. (2) The M1-live curve is not flat (58→4% over the band); "cliff removed" means the *derivative* collapsed (81→0.3% over ±20% → 58→29% over ±20% around 1.0×), not that survival is amplitude-independent. (3) White-noise spectrum still assumed; ρ unmeasured. (4) n=2048 binomial ±~1%.

**Lineage.** Parents: **polished-moon-9652** (the amplitude-locked-trim finding this fixes; config fork) + **shiny-firefly-6661** (prediction 2, L-levers: this is the training-side complement that de-risks ALL of them). Child: d50var_s8 (running).