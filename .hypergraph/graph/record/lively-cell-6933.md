---
node_id: 0e01acc6-8ffc-59bd-90dd-c48734f4b555
slug: lively-cell-6933
title: 'First Bench-dashboard flight session: new-best 9.0 s continuous stable hover @ 2.2° — but the link p99 tail DOUBLED (137–170 ms) and correlates with a near-LOC excursion (Air65 II, 2026-07-10)'
created_at: '2026-07-10T17:08:16.372681+00:00'
parents:
- snowy-heart-2157
- aged-wildflower-8839
summary: 'First real flights driven end-to-end from the Studio Bench tab (post Start-fix parent snowy-heart-2157): 7 airborne flights of d50var_s8 on the Air65 II, 5.3–15.2 s airborne, all ended by radio kill (throttle still ~1480–1580 µs at last frame → no soft-lands, so no auto-reports — by design, not a bug). vs the Jul 7 vzfix session (parent aged-wildflower-8839): (1) NEW BEST sustained hover — flight 610 holds ONE continuous 9.0 s stable window @ 2.20° median tilt, its entire airborne phase, vs the previous best 3.68 s; session stable-window tilt medians 2.08–3.27° ≈ parity with 1.43–2.71°. (2) vz fix HOLDS: vz_rail_frac 0.9–2.4% on 6/7 (610''s 9.6% is liftoff-climb frames, vz_min only −0.69). (3) REGRESSION: link p99 137–170 ms vs 73–122 ms (p50 unchanged 24 ms, loop still 42 Hz) — and in the 18.3 s flight 739 the obs_age bursts (~150 ms sustained, 10.5–13 s) coincide with a ±90° roll near-loss-of-control at 12.5–15 s: field-grade evidence for the campaign''s latency-tail attribution. Suspects: flights now run inside the Studio server process (uvicorn + /ws/flight broadcast + GIL) vs standalone pilot.py, parallel-sim toggle, or WiFi — unresolved; follow-up = same-pack A/B pilot.py CLI vs dashboard, compare p99. (4) 5/7 flights flag us_thr_rise +306–337 µs with a_thr steady — the known sag-compensation damper drift; the sag-normalized divergence heuristic (flagged on Jul 7 flight 783) is still pending. Verdict: dashboard-as-flight-tool GREEN (7/7 Starts worked); flight quality parity-plus with a real, newly-quantified link-tail regression as the top open axis.'
origin:
  backend: flywheel
  node_id: 0e01acc6-8ffc-59bd-90dd-c48734f4b555
  slug: lively-cell-6933
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
---
# First Bench-dashboard flight session — Air65 II, 2026-07-10

**Question.** Does the unified Bench tab (rapid-meadow-0957, Start path fixed in snowy-heart-2157) actually work as the flight tool for real sessions — and does flight quality hold vs the Jul 7 pilot.py-CLI session (aged-wildflower-8839)?

## Setup
- Same policy (d50var_s8 deploy weights, dashboard default), same Air65 II + XIAO WiFi bridge — now on the rewired UART pins (D10/GPIO9→R1, D9/GPIO8→T1, commit `b27908a`), calm indoor air, ~42 Hz (loop is RTT-bound: dt median 24 ms = link p50, unchanged).
- **New vs parent:** flights driven from the browser (FlightManager inside `scripts/serve.py` on the bench Mac) instead of the standalone `pilot.py fly` CLI.
- 8 Starts, 7 airborne flights (`runs/pilot/flight_17837024xx–7xx.csv`, 18:52–18:59), 5.3–15.2 s airborne. All 7 ended by radio kill (final frames still command 1480–1580 µs) — **no soft-lands, so no auto flight-reports: by design** (they fire only on RELEASED). Packs built offline with `flight_report.py`; per-flight table in `benchfix_session_summary.csv`.

## Results (vs the Jul 7 session)
| metric | Jul 7 (pilot.py CLI) | tonight (Bench dashboard) |
|---|---|---|
| stable-window median tilt | 1.43–2.71° | 2.08–3.27° (parity) |
| best continuous stable window | 3.68 s | **9.0 s @ 2.20° (flight 610 — its ENTIRE airborne phase)** |
| vz_rail_frac (hover) | 0.9–9.8% | 0.9–2.4% on 6/7 — vz fix holds |
| link p50 | 24 ms | 24 ms (unchanged) |
| **link p99** | **73–122 ms** | **137–170 ms — ~2× regression** |

- **New best hover on record.** Flight `610`: one unbroken 9.0 s stable window at 2.20° median tilt, roll/pitch inside ±5° the whole flight, thrust divergence only +92 µs. Its 37 vz-rail frames are all the liftoff climb (vz_max 3.8 at t≈3.5 s; vz_min just −0.69) — not hover drift.
- **The link-tail regression is real and it bites.** Flight `739` (15.2 s airborne, the longest): obs_age runs clean ~20 ms bursts through mid-flight, then sustained ~150 ms bursts from 10.5–13 s — and the attitude departs to ±50–90° roll at 12.5–15 s (rates ±1000°/s+), recovered, wobbling to the kill. p90 tilt 52°. This is the sharpest field evidence yet for the campaign's attribution (delicate-credit-2979 / the parent's honest-residual note): **the p99 latency tail, not the policy, is the destabilizer.**
- **Suspects for the 2× p99 regression** (unresolved — the one confound of this session): (a) the flight engine now runs inside the Studio server process — uvicorn event loop + /ws/flight broadcast + Python GIL sharing a core with the 50 Hz control thread; (b) the parallel-sim toggle (CPU torch stepping in-process); (c) WiFi conditions of the evening. **Follow-up experiment:** same pack, alternating flights pilot.py-CLI vs dashboard, compare link p99 — if (a), the fix is process isolation or a dedicated thread priority, and it's cheap.
- **Damper sag-drift, again.** 5/7 flights flag thrust divergence at +306–337 µs with `a_thr` steady ≈ −0.49 (report annotates: *pilot damper drove it*) — the same gentle battery-sag compensation first seen on Jul 7 flight 783 (+297 µs). The sag-normalized divergence heuristic remains TODO; until then the flag is noise on flights >10 s.

## Verdict / honesty
**Dashboard-as-flight-tool: GREEN** — 7/7 Starts flew after the interlock fix, telemetry/HUD live throughout, CSVs logged, the radio-kill path released cleanly every time. **Flight quality: parity-plus** — tilt medians comparable, one new-best 9 s stable window — **with one real regression: the link p99 tail doubled**, and this session adds field-grade evidence that the tail causes departures. Honesty: (1) single evening, one battery band, calm air; (2) the p99 regression is confounded (in-process serving vs WiFi vs parallel-sim) — measured, not yet attributed; (3) no flight ran to a software soft-land, so the auto-report path is still field-unexercised (fake-bridge-tested only); (4) stable-window medians are slightly WORSE than Jul 7 on 6/7 flights — the 9 s window is one flight, not the session norm.

## Lineage
Parents: **snowy-heart-2157** (the Start interlock fix that made browser-driven flight possible — this session is its field validation) and **aged-wildflower-8839** (the Jul 7 vz-fix session: same policy, same airframe, the direct baseline). Policy lineage: d50var_s8 (broken-wildflower-8398). The latency-tail thread links back to **delicate-credit-2979**. Flown at HEAD `b27908a`.