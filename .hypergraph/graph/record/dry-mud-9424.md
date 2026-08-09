---
node_id: 553a20b7-e88a-54b2-8cda-be9beac3eb7e
slug: dry-mud-9424
title: 'hover_tof_air65 (3.2B): ALTITUDE SOLVED — z err 0.651→0.043 m, no-DR survival 0→100%, zero floor/ceiling exits anywhere; NEW regression: M1-live leveling 99.9→75.2%, all-horizontal fast exits, ToF channel exonerated by knockouts'
created_at: '2026-07-13T14:03:03.214713+00:00'
parents:
- floral-unit-0997
- broken-wildflower-8398
summary: 'hover_tof_air65 3.2B (ONE factor vs d50var_s8: the measured-height obs channel): ALTITUDE SOLVED in sim — no-DR mean_z_error 0.651→0.043 m (−93%), no-DR 30s survival 0→100%, M2-sensor 29.8→42.1%, zero floor/ceiling exits across the whole probe battery (exit_probe.py, committed). NEW regression, cleanly attributed: M1-live leveling 99.9→75.2% at 1.0× (99.9/82/75/69% across 0.5–1.2×), ALL failures fast horizontal departures (median 1.68 s); knockouts exonerate the ToF channel and its noise — the gyro-noise leveling response regressed, capacity contention suspected (input 40→48 on [64,64]; width arm next). Mixed verdict, no outcome tag; NOT deploy-ready. Commits d167886/0b69d7f; battery in runs/hover_tof_air65/probes.json.'
origin:
  backend: flywheel
  node_id: 553a20b7-e88a-54b2-8cda-be9beac3eb7e
  slug: dry-mud-9424
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: c8e5b546-3b3b-5e75-83ee-4437bd8f3034
  slug: hidden-butterfly-3294
  revision: 0
  pushed_at: '2026-08-09T21:28:03+00:00'
  content_sha256: 4b86e76d282a13cf0f760bf9f9fe96a40f7fc8ba4eb4e6bdd2c890419c99ef2c
---
# hover_tof_air65: the measured height closes the vertical loop — and re-opens a horizontal one

**Hypothesis (floral-unit-0997).** Adding the measured ToF height error to the obs (ONE factor on the flight-proven ★ d50var_s8 recipe) lets PPO own the altitude loop, killing the open-loop-z failure class every blind arm carried.

**Setup.** `configs/hover_tof_air65.yaml` (obs-6 × stack 8 = input 48, [64,64]); 3.2B steps, ~53 min @ ~1.0M sps (commit d167886; results commit 0b69d7f). Probe battery: `survival_probe.py` + the newly committed `exit_probe.py` (floor/ceiling/xy decomposition), 2048 pure-hold drones, 30 s, deterministic mean; eval twins `_m1live`/`_m2sensor` mirror the parent's metric family with the h channel added.

**Results (Δ vs parent d50var_s8 = broken-wildflower-8398).**

| metric | d50var_s8 | hover_tof | Δ |
|---|---|---|---|
| no-DR mean_z_error | 0.651 m | **0.043 m** | **−93%** |
| no-DR crash rate /step | 1.05e-3 | 6.5e-7 | ~−1600× |
| no-DR 30 s survival | 0% (noise-tuned trim fails a clean world) | **100%** | closed |
| M1-live 0.5/0.8/1.0/1.2× | 89/100/99.9/90% | **99.9/82/75/69%** | REGRESSED ≥0.8× |
| M2-sensor@d50 | 29.8% | **42.1%** | +12 pts |
| full training DR (wind+impulse+lat+amp) | — | 19.2% | new number |
| no-DR tilt / speed | 1.56° / 0.127 | 1.23° / 0.070 | better |

**Exit-direction decomposition (the decisive measurement).** M1-live@1.0×: 507 failures = **0 floor, 0 ceiling, 507 xy** — fast horizontal departures (median exit 1.68 s), while every survivor tracks z essentially exactly. Zero vertical exits ANYWHERE in the battery: the altitude objective is emphatically met.

**Attribution knockouts (M1-live@1.0×).** h-noise OFF, gyro/att noise on → 74.9% (unchanged); ONLY h noise, IMU clean → 100%. **The ToF channel and its noise are exonerated** — the regression is the gyro/attitude-noise *leveling* response. Raised-band twin (z 0.8–1.1) → 76.0%: floor proximity exonerated too.

**Decode.**
1. The vertical loop is closed — the failure class that ended every real flight so far (vz rail → ceiling; trim sink → floor) is gone in sim, across clean, live-sensor, and sensor-gauntlet worlds. M2-sensor +12 pts despite worse leveling: under latency, closed-loop z rescues what used to compound.
2. The leveling regression is real and new: the parent held 99.9% at the same IMU noise with the same training DR. Suspect: **capacity contention** — the 6th channel grows stack-8 input 40→48 on the same [64,64], and d50var→s8 already showed this recipe is capacity-sensitive (that node's whole story). A width arm ([96,96] or [128,128]) is the obvious one-factor probe; an amp-curriculum or upright_scale bump are the reward-side alternatives.
3. Deploy read: **do not fly this checkpoint** — at the honest noise floor it flies away sideways ~1-in-4 within seconds. The deploy artifacts (policy_weights.json, selftest parity 6.4e-08, corrective-sign checks OK) are ready for whichever descendant fixes leveling.

**Verdict / Honesty.** Mixed — GREEN on the altitude objective (the node's hypothesis is confirmed), RED on M1-live leveling robustness; no outcome tag on purpose. (1) The M1-live/M2 twins put datasheet-placeholder noise (sd 0.02 m) on the h channel — unmeasured until a ToF-equipped flight; the knockouts show the headline numbers don't hinge on it. (2) The parent M1-live row is from its node (1.0× re-reproduced today at 99.85% on this harness — harness sound). (3) full-DR 19.2% has no parent number (blind arms never ran it; recorded for descendants). (4) survivor z-err reads exactly 0 at the horizon because horizon == episode_len auto-resets — noted in exit_probe.py; the no-DR eval's 0.043 m is the trustworthy tracking number.

**Lineage.** Parents: floral-unit-0997 (the hover_tof method this trains), broken-wildflower-8398 (★ d50var_s8 — every Δ above is against it). Next: leveling-regression arm (width first), then the first real ToF flight to calibrate the h-channel DR.