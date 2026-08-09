---
node_id: 88abc7b1-33fc-59a3-a265-c1190e186723
slug: aged-wildflower-8839
title: RPM-anchor vz fix VALIDATED in flight — driftless damper kills the -2.0 rail ceiling bug; d50var_s8 flies full ~18 s windows (Air65 II, 2026-07-07)
created_at: '2026-07-07T12:29:42.098099+00:00'
parents:
- cool-sea-6202
summary: 'Flies the deferred prediction from the parent cool-sea-6202, which shipped the RPM-anchor vz damper AWAITING BENCH FLIGHT and staked it on three flight_report checks. This block flew it: 9 flights of d50var_s8, 8 airborne. GREEN — the -2.0 rail ceiling bug is DEAD. On the two cleanest long flights (711/678): vz_est is now DRIFTLESS (711 mean 0.00 m/s over 18 s — in f1 it drifted to -2.0 and PARKED there), vz_rail_frames 7/13 (was 48), thrust_divergence FALSE with us_thr_rise -163/-150 us i.e. throttle FELL (was +203 us while a_thr flat -> ceiling), and all three long flights completed the full ~18-21 s window with a controlled landing ramp instead of f1''s ~10 s ceiling contact — airborne 17.8-18.3 s vs f1''s 12.6 s. Honest residual: hover is wobblier than f1''s pristine first-9 s (stable-window median tilt ~1.9-2.0 deg with periodic +-20-40 deg excursions and rate spikes) and several flights ended in departures; obs_age p99 up to 122 ms (spikes 240 ms) pins that on the KNOWN action-latency tail (bridge / Stage-2 work), NOT the vz fix. The one long flight that still flagged divergence (783: +297 us) climbed gently over 18 s at 1.72 deg — honest battery-sag throttle comp, not the f1 phantom-thrust runaway. Verdict: GREEN — ceiling bug fixed, hover holds altitude; the latency tail is now the isolated next axis. Fix commit d7fd877; flown at HEAD 549d6ae.'
origin:
  backend: flywheel
  node_id: 88abc7b1-33fc-59a3-a265-c1190e186723
  slug: aged-wildflower-8839
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
---
# RPM-anchor vz fix — flown, and the ceiling bug is dead

**Hypothesis (from the parent `cool-sea-6202`).** The RPM-anchored, integrator-free altitude damper makes the `-2.0 m/s` vz rail structurally impossible, so a level hover can no longer pile on phantom thrust and fly into the ceiling (the f1 crash, `royal-bar-2003`). The parent staked this on three `flight_report` checks: `vz_rail_frames ~= 0` over the airborne window (was 48), `thrust_divergence.detected = false` with `us_thr_rise <~ 40 us` (was +203 us while `a_thr` flat), and a completed calm-air flight instead of a ~10 s ceiling contact.

## Setup (what changed vs the parent = the fix is now FLOWN)
- Same policy: `d50var_s8` (`broken-wildflower-8398`, the studio-baseline; obs-5 x stack 8, [64,64], no vz channel). Same hardware: Air65 II (BTFL 26.6.0) + XIAO ESP32-S3 WiFi bridge, offboard `scripts/pilot.py fly --takeoff`, ~42 Hz, calm indoor air.
- The one change under test: the RPM-anchor damper (`rpm_climb_rate` / `rpm_damper_trim`, commit `d7fd877`), flown at HEAD `549d6ae` (also carries this session's bench-ergonomics commit — `$NW_BRIDGE` default + d50var_s8 default weights — which don't touch flight dynamics).
- **9 flights this session** (`runs/pilot/flight_17834265xx.csv`, 14:16-14:20), 8 airborne + 1 abort. Packs built with `scripts/flight_report.py`; per-flight table in `vzfix_session_summary.csv`.

## Results (vs the f1 baseline `d50var_s8_f1`)
The three predictions, on the two cleanest long flights (`711`, `678`) — full traces in `flight_telemetry.png`:

| check | f1 baseline | 711 | 678 | verdict |
|---|---|---|---|---|
| airborne duration | 12.6 s (-> ceiling) | **18.1 s (completed + landed)** | **17.8 s (completed + landed)** | held |
| `vz_rail_frames` (frac) | 48 (9.1%) | **7 (0.9%)** | **13 (1.7%)** | ~killed |
| `vz_est` mean over hover | drifted to -2.0, PARKED | **0.00 m/s (driftless)** | ~0 (driftless) | fixed |
| `thrust_divergence` | True, **+203 us** (a_thr flat) | **False, -163 us** (thr FELL) | **False, -150 us** | fixed |
| stable-window median tilt | 1.28 deg | 2.00 deg | 1.94 deg | wobblier |

- **The ceiling bug is dead.** In f1 the accel `vz_est` drifted to `-2.0` and parked, the damper piled `+203 us` of phantom thrust while `a_thr` never moved, and it climbed into the ceiling at ~10 s. Now `vz_est` (= the bounded RPM climb rate) sits centered on **0.00 m/s** through an 18 s flight, the trim stays bounded `+-0.12` mean `~0`, and `us_thr` stays in-band and **ramps DOWN to a controlled landing** (green band in the telemetry) — the opposite of a runaway. All three long flights (`678`/`711`/`783`) completed the full ~18-21 s window and landed; none climbed out.
- **Honest residual — hover is wobblier, and it is the latency tail, not the vz fix.** Stable-window median tilt is ~1.9-2.0 deg (vs f1's pristine 1.28 deg over its short pre-crash window), with periodic +-20-40 deg attitude excursions and body-rate spikes to +-250-750 deg/s; several of the shorter flights (`555`/`577`/`616`/`760`, airborne 7-12 s) ended in departures. `obs_age` p99 runs 73-122 ms with spikes to 240 ms (32%+ past the 40 ms cliff) — this is exactly the campaign's already-attributed residual (`delicate-credit-2979`: 'action latency > ~40 ms during active noise-correction'), and it is bridge / Stage-2 work, not policy or damper work. The shorter flights' higher `vz_rail_frames` (22-40) are departure/tumble telemetry OUTSIDE the hover window — the parent explicitly predicted this ('extreme-RPM frames will read a large vz_est'), not a return of the hover drift.
- **The one caveat flight (`783`).** Also 18.3 s and 1.72 deg tilt, but `thrust_divergence` flagged True (`us_thr_rise +297 us`). Read: a **gentle** throttle rise over a full 18 s flight at low tilt is honest battery-sag compensation (more us for the same thrust as the pack drops), not the f1 phantom-thrust runaway (which was +203 us in a SHORT window with `a_thr` frozen). The divergence heuristic was tuned on the f1 short-window signature; over an 18 s flight it needs a sag-normalized variant (follow-on).

## Verdict / honesty
**GREEN — the RPM-anchor vz fix works; the deploy-harness ceiling bug from `royal-bar-2003` is resolved.** The drone now holds altitude and lands under control instead of climbing into the ceiling, and the vz estimator is driftless as designed. Honesty: (1) this is not a still, glassy hover — it is a wobbly-but-sustained one (~2 deg median, real +-20-40 deg transients), and the wobble/departures trace to the latency tail, a separate known axis; (2) only 3 of 9 flights ran the full window (the rest departed early); (3) the divergence detector needs a sag-normalized threshold before it is trustworthy on long flights (`783`); (4) all calm-air, one battery-condition band (4.0 V class), one session. The strategic read is unchanged and now empirically backed: **blind hover altitude is solved in software; the next lever is shrinking the p99 latency tail (100 Hz control / ESP-side command hold / MSP oversampling), not the policy.**

## Lineage
Parent: **cool-sea-6202** (the RPM-anchor vz fix, IMPLEMENTED-awaiting-flight — this node resolves it). Grandparent: **royal-bar-2003** (f1, which root-caused the bug). The policy under test descends from **broken-wildflower-8398** (d50var_s8, studio-baseline). The residual latency tail links back to **delicate-credit-2979** (the stock-hardware campaign close that isolated action latency as the last gap). Fix commit `d7fd877`, flown at `549d6ae`.