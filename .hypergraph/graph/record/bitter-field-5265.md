---
node_id: ecd233c5-94c2-5745-8c9e-f2033720ff77
slug: bitter-field-5265
title: 'hover_tof_air65_w192u15 ([192,192]): m2sensor gate PASSED for the first time (50.1%) and best 1.2×/full-DR of the line — but nominal tracking degrades past two gates (z err 0.120 m, 1.0× 88.1%); ladder exhausted, no arm dominates'
created_at: '2026-07-13T17:18:17.018036+00:00'
parents:
- calm-base-6054
summary: 'hover_tof_air65_w192u15 3.2B (ladder arm 3, final; ONE factor vs calm-base-6054''s w128u15: hidden_sizes [128,128]→[192,192], ~52k params): the robustness frontier moves out — m2sensor 36.5→50.1% (≥42 gate PASSED, first arm ever, best of the line), M1-live 1.2× 64.9→81.9%, full-DR 18.4→26.3% (both best recorded) — but nominal tracking degrades past the bar: no-DR z err 0.047→0.120 m (≤0.05 gate FAILED), M1-live 1.0× 95.4→88.1% (≥98 FAILED), 0.8× 97.3% (first w-ladder arm to lose points there); failure mode reverts to fast departures (median exit 2.16 s). Exits 0 floor / 0 ceiling everywhere — altitude loop closed across all three arms. MIXED. LADDER VERDICT after 3 one-factor arms: capacity × upright pressure trades along a clean-trim↔noise-robustness frontier, never dominating — w128 owns nominal (1.0× 98.9%), w192u15 owns robustness (m2sensor 50.1%), no arm passes all four gates → regrouping with the user per the agreed max-3 rule. Commits 84919e6/07eec33; battery in runs/hover_tof_air65_w192u15/probes.json.'
origin:
  backend: flywheel
  node_id: ecd233c5-94c2-5745-8c9e-f2033720ff77
  slug: bitter-field-5265
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 1c229fdf-3992-5f93-867c-a405f7efc828
  slug: muddy-bonus-6308
  revision: 0
  pushed_at: '2026-08-09T21:28:03+00:00'
  content_sha256: eb06383b29c2bf9857655b0c83eb00399165040962b34ec54b90e2ea7fe0d77a
---
# hover_tof_air65_w192u15: more capacity keeps buying robustness — and starts selling the setpoint

**Hypothesis (from calm-base-6054's decode).** If the [128,128] trunk can't fit both the clean-trim and the noise-robust behavior at gate level, more width ([192,192], ONE factor on the upright-1.5 recipe) should lift both ends — the pure-capacity read of arm 2 having moved the needle.

**Setup.** `configs/hover_tof_air65_w192u15.yaml` = w128u15 + `hidden_sizes [128,128]→[192,192]` (~52k params); 3.2B steps @ ~0.94M sps (config commit 84919e6, results commit 07eec33). Identical battery, seed 12345.

**Results (Δ vs parent w128u15 = calm-base-6054).**

| metric | w128u15 | w192u15 | gate | Δ |
|---|---|---|---|---|
| no-DR z err / survival | 0.047 m / 100% | **0.120 m / 100%** | ≤0.05 / 100% | ❌ z-err gate LOST (first arm to lose it) |
| no-DR tilt / pos err | 0.22° / 0.394 | 0.69° / 0.596 | — | tracking visibly looser |
| M1-live 0.5/0.8× | 100 / 100% | 100 / **97.3%** | — | 0.8× loses points for the first time |
| M1-live 1.0× | 95.4% | **88.1%** | ≥98% | ❌ −7.2 pts |
| M1-live 1.2× | 64.9% | **81.9%** | ≥85% | ❌ but +17 pts — 3 pts short, flattest curve of the line |
| m2sensor | 36.5% | **50.1%** | ≥42% | ✅ **PASSED — first arm ever, best of the line** |
| full training DR | 18.4% | **26.3%** | — | best recorded |
| exit probe @1.0× | 0/0/95 xy, median 14.8 s | **0/0/243 xy, median 2.16 s** | 0/0 | ✅ vertical closed; fast departures return |

**Decode.**
1. The capacity story half-held: width again bought robustness (every high-noise probe improved, m2sensor crossed its bar for the first time in the hover_tof line) — but this time it paid from the nominal end, and heavily: z err more than doubled, 1.0× dropped 7 pts, even 0.8× dipped. The trade-off didn't dissolve with capacity; it rotated.
2. Reading all three arms together: [64,64]→[128,128]→[192,192] (× upright 1.5) sweeps a clean-trim↔noise-robustness FRONTIER — w128 sits at the nominal end (1.0× 98.9%), w192u15 at the robust end (m2sensor 50.1%), w128u15 between. No point on the sweep passes all four gates; the two gate-passing behaviors live at opposite ends.
3. The altitude result is untouched everywhere: zero floor/ceiling exits in every probe of every arm — the ToF channel's win is robust to all of this.

**Verdict / Honesty.** MIXED, no outcome tag — the arm's hypothesis (lift both ends) is REFUTED in its strong form, while its robustness half delivered the line's first m2sensor pass. (1) The z-err degradation is from the same standard eval construction as every prior arm — directly comparable, not a harness change. (2) Training sps dropped ~6% ([192,192] cost) — still ~57 min/run. (3) Battery JSON attached.

**Lineage.** Parent: calm-base-6054 (whose decode nominated pure capacity). LADDER COMPLETE at the agreed max of 3 one-factor arms; per the plan, regrouping with the user. Candidate directions recorded for that conversation: (a) noise-amp curriculum (train the tail late, keep nominal), (b) intermediate width [160,160] or longer training at [128,128], (c) revisit the 1.2× gate (the blind d50var_s8 held 90% there — the bar is reachable in principle), (d) distill w192u15's robustness into w128 (teacher-student).