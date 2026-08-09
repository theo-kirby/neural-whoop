---
node_id: 40c1b736-3562-5948-bb57-28d458d5f322
slug: gentle-sound-6612
title: 'hover_tof_air65_w128 ([128,128]): capacity CONFIRMED at nominal noise — M1-live 1.0× 75.2→98.9% (gate met) — but the noise tail collapses: 1.2× 55%, m2sensor 42→20%; 2 of 4 deploy gates failed'
created_at: '2026-07-13T15:22:04.352174+00:00'
parents:
- dry-mud-9424
summary: 'hover_tof_air65_w128 3.2B (ONE factor vs dry-mud-9424''s hover_tof_air65: ppo.hidden_sizes [64,64]→[128,128], ~24k params): the capacity-contention hypothesis is CONFIRMED at nominal noise — M1-live 1.0× leveling 75.2→98.9% (gate ≥98 MET; curve 100/100/98.9/55.0% across 0.5–1.2×), no-DR survival 100%, z err 0.042 m, tilt 1.23→0.41°, exit probe still 0 floor / 0 ceiling (22 residual 1.0× failures are slow horizontal drift-outs, median 15.7 s vs the parent''s fast 1.68 s departures). But the width TRADES AWAY the noise tail: M1-live 1.2× 68.8→55.0% (gate ≥85 FAILED), m2sensor 42.1→20.5% (gate ≥42 FAILED, halved), full-DR 19.2→10.8%. Mixed, not deployable → ladder arm 2 = w128 + upright_scale 1.0→1.5 (reward-side leveling pressure), training as of this node. Commits a8d37dc/9359479; battery in runs/hover_tof_air65_w128/probes.json.'
origin:
  backend: flywheel
  node_id: 40c1b736-3562-5948-bb57-28d458d5f322
  slug: gentle-sound-6612
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 73672786-b354-56b3-925a-b4c7d8f9aefa
  slug: restless-cell-8415
  revision: 0
  pushed_at: '2026-08-09T21:28:03+00:00'
  content_sha256: 9080e9ed9421f9ea185b558b404effdab9e742931fcef07d8ea19e2157a9cb65
---
# hover_tof_air65_w128: width fixes the nominal leveling regression — and buys it by over-trusting noisy channels

**Hypothesis (from dry-mud-9424's decode).** The M1-live leveling regression (99.9→75.2%) is capacity contention — the ToF channel grew stack-8 input 40→48 on the same [64,64] trunk — so widening to [128,128] (ONE factor) should recover leveling without touching the solved altitude loop.

**Setup.** `configs/hover_tof_air65_w128.yaml` = hover_tof_air65 + `ppo.hidden_sizes [64,64]→[128,128]` (~24k params, still trivially cheap for the pure-Python 50 Hz pilot); 3.2B steps, ~53 min @ ~1.0M sps (config commit a8d37dc, results commit 9359479). Same battery as the parent: `survival_probe.py` + `exit_probe.py`, 2048 pure-hold drones, 30 s, deterministic mean, seed 12345; M1-live scaled twins at 0.5/0.8/1.2× the per-channel noise. Deploy gates agreed with the user: no-DR 100% + z err ≤0.05 m; M1-live ≥98% @1.0× and ≥85% across 0.8–1.2×; m2sensor ≥42%; zero floor/ceiling exits.

**Results (Δ vs parent hover_tof_air65 = dry-mud-9424).**

| metric | tof [64,64] | tof [128,128] | gate | Δ |
|---|---|---|---|---|
| no-DR z err / survival | 0.043 m / 100% | **0.042 m / 100%** | ≤0.05 / 100% | ✅ held |
| no-DR tilt / speed | 1.23° / 0.070 | **0.41° / 0.033** | — | much cleaner hover |
| M1-live 0.5/0.8× | 99.9 / 82.3% | **100 / 100%** | — | ✅ |
| M1-live 1.0× | 75.2% | **98.9%** | ≥98% | ✅ **+23.7 pts — the hypothesis's prediction** |
| M1-live 1.2× | 68.8% | **55.0%** | ≥85% | ❌ **−13.8 pts** |
| m2sensor | 42.1% | **20.5%** | ≥42% | ❌ **halved** (median exit 2.6 s) |
| full training DR | 19.2% | 10.8% | — | ❌ |
| exit probe @1.0× | 0 floor / 0 ceiling / 507 xy, median 1.68 s | **0 / 0 / 22 xy, median 15.72 s** | 0/0 | ✅ altitude loop still closed |

**Decode.**
1. Capacity contention was real: at the trained noise level the wider trunk restores (and beats) the blind parent's leveling, and the failure *mode* softens — the few residual exits are slow drifts, not the parent's 1.7 s departures.
2. But the extra capacity fits the *trained* noise distribution more sharply: everything ≥1.2× amplitude or with bias+rate-gain+latency stacked (m2sensor) got substantially worse. The [64,64] arm was more conservative under noise it hadn't seen; the [128,128] arm trusts its attitude channels too much.
3. Deploy read: still not flyable at the bar — the real bench has exactly the m2sensor character (bias, latency). Two of four gates failed.

**Verdict / Honesty.** MIXED, no outcome tag: GREEN on the capacity hypothesis at nominal noise (gate met with margin), RED on high-noise robustness (two gates failed). (1) The m2sensor/1.2× regressions are large and consistent across three independent probes — not seed noise. (2) The h-channel noise is still the datasheet placeholder (unmeasured until a ToF-equipped flight); knockouts on the parent showed the leveling story doesn't hinge on it. (3) Full battery JSON in `runs/hover_tof_air65_w128/probes.json` (attached).

**Lineage.** Parent: dry-mud-9424 (the regression this arm answers; its decode nominated width first). Next: ladder arm 2 = `hover_tof_air65_w128u15.yaml` — ONE factor vs this arm, `task.upright_scale 1.0→1.5`, reward-side leveling pressure so the wider trunk earns return by staying level instead of chasing noisy tilt estimates (also from the parent's decode candidates). Max 3 arms before regrouping with the user.