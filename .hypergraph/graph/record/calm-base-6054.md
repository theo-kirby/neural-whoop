---
node_id: 40601827-a190-5390-85f5-b2f382621695
slug: calm-base-6054
title: 'hover_tof_air65_w128u15 (upright_scale 1.5): recovers most of the width arm''s noise tail — m2sensor 20.5→36.5%, 1.2× 55→65% — at a 3.6 pt nominal cost (1.0× 95.4%, gate missed); cleanest hover of the line, still 0 of 4-gate battery unlocked'
created_at: '2026-07-13T16:18:32.265025+00:00'
parents:
- gentle-sound-6612
summary: 'hover_tof_air65_w128u15 3.2B (ladder arm 2; ONE factor vs gentle-sound-6612''s w128: task.upright_scale 1.0→1.5): reward-side leveling pressure recovers MOST of the noise tail the width arm traded away — m2sensor 20.5→36.5% (+16 pts, still under the ≥42 gate; [64,64] tof arm holds 42.1), M1-live 1.2× 55.0→64.9%, full-DR 10.8→18.4% — and flies the cleanest hover of the whole line (no-DR tilt 0.41→0.22°, speed 0.020, z err 0.047 m ≤ 0.05, survival 100%). Cost: M1-live 1.0× 98.9→95.4% (gate ≥98 FAILED by 2.6 pts); curve 100/100/95.4/64.9 across 0.5–1.2×. Exit probe 0 floor / 0 ceiling (95 xy, median 14.8 s) — altitude loop closed everywhere. MIXED, directionally right; no arm passes all four gates yet → arm 3 (final) = [192,192] + upright 1.5 (pure capacity; decision rule: arm 2 moved the needle). Commits 9359479/84919e6; battery in runs/hover_tof_air65_w128u15/probes.json.'
origin:
  backend: flywheel
  node_id: 40601827-a190-5390-85f5-b2f382621695
  slug: calm-base-6054
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 8498f213-9a31-5625-b6d3-82cbd9f2e481
  slug: little-dawn-9519
  revision: 0
  pushed_at: '2026-08-09T21:28:03+00:00'
  content_sha256: 8869f4b80a4ce94e3719a1a62385603204ba10765b82a4504dc1f67d0dd51359
---
# hover_tof_air65_w128u15: reward-side leveling pressure buys back the noise tail — most of it

**Hypothesis (from gentle-sound-6612's decode).** The width arm's noise-tail collapse comes from the [128,128] trunk over-trusting its attitude channels; raising `upright_scale` 1.0→1.5 makes staying level intrinsically rewarded, so the policy should stop chasing noisy tilt estimates — recovering 1.2×/m2sensor without giving back the nominal-leveling win.

**Setup.** `configs/hover_tof_air65_w128u15.yaml` = w128 + `task.upright_scale 1.0→1.5` (ONE factor); 3.2B steps @ ~1.0M sps (config commit 9359479, results commit 84919e6). Identical battery: `survival_probe.py` + `exit_probe.py`, 2048 pure-hold drones, 30 s, deterministic, seed 12345, scaled M1-live twins.

**Results (Δ vs parent w128 = gentle-sound-6612; [64,64] tof arm in parens where it's the bar).**

| metric | w128 | w128u15 | gate | Δ |
|---|---|---|---|---|
| no-DR z err / survival | 0.042 m / 100% | 0.047 m / 100% | ≤0.05 / 100% | ✅ held (barely) |
| no-DR tilt / speed | 0.41° / 0.033 | **0.22° / 0.020** | — | cleanest hover of the line |
| M1-live 0.5/0.8× | 100 / 100% | **100 / 100%** | — | ✅ |
| M1-live 1.0× | 98.9% | **95.4%** | ≥98% | ❌ −3.6 pts — gate re-lost |
| M1-live 1.2× | 55.0% | **64.9%** | ≥85% | ❌ but +10 pts — right direction |
| m2sensor | 20.5% (42.1%) | **36.5%** | ≥42% | ❌ but +16 pts — most of the tail back |
| full training DR | 10.8% (19.2%) | **18.4%** | — | nearly the [64,64] number |
| exit probe @1.0× | 0 / 0 / 22 xy | **0 / 0 / 95 xy, median 14.8 s** | 0/0 | ✅ altitude loop closed |

**Decode.**
1. The mechanism works as hypothesized: paying the policy to be level (rather than to react) recovers robustness across every high-noise probe at once — and as a side effect produces the stillest no-DR hover in the whole hover line (0.22° mean tilt).
2. But it's a trade along the same frontier, not an escape from it: nominal 1.0× gave back 3.6 pts. The [128,128] trunk appears unable to fit BOTH the clean-trim behavior and the noise-robust behavior at gate level simultaneously — the same capacity story one level up.
3. Bar status across the ladder: [64,64] passes m2sensor but fails 1.0× badly; w128 passes 1.0× but halves m2sensor; w128u15 sits between on both. No arm passes all four gates.

**Verdict / Honesty.** MIXED, no outcome tag — the arm's own hypothesis (recover tail without giving back nominal) is only half-confirmed: tail recovered substantially, nominal partially given back. (1) All deltas are from the same harness/seed as the parent arms — directly comparable. (2) no-DR z err crept 0.042→0.047 m (still ≤ 0.05 gate) — upright pressure competes slightly with position tracking; worth watching if upright_scale rises further. (3) Battery JSON attached (`runs/hover_tof_air65_w128u15/probes.json`).

**Lineage.** Parent: gentle-sound-6612 (the noise-tail collapse this answers; its decode nominated reward-side pressure). Next: ladder arm 3 (final before regrouping with the user, per the agreed max-3 rule) = `hover_tof_air65_w192u15.yaml`, ONE factor vs this arm: `hidden_sizes [128,128]→[192,192]` (~52k params) — the agreed decision rule picked pure capacity because arm 2 moved the needle.