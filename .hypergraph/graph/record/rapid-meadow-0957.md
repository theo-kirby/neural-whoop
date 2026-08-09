---
node_id: f0111520-dada-528a-8f6f-5797a510f599
slug: rapid-meadow-0957
title: 'Unified bench dashboard: real Air65 II flight + parallel sim from one browser page (Studio Bench tab, 2026-07-08)'
created_at: '2026-07-08T10:48:48.981928+00:00'
parents:
- white-surf-8279
- aged-wildflower-8839
summary: 'Unifies the two disjoint control surfaces — the Studio (sim, /ws/live) and the offboard pilot (real drone, scripts/pilot.py) — into one always-on browser page: the Studio''s new Bench tab. Change vs parents: (1) the pilot.py `fly` 3·2·1→liftoff→hover→land state machine (parent aged-wildflower-8839''s validated RPM-anchor flight engine) is extracted VERBATIM into a steppable, pure-stdlib package `neural_whoop.pilot` (FlightController/config/policy/telemetry; pilot.py is now a thin CLI shim re-exporting the surface) — selftest deploy parity unchanged, sim_vs_real + the 14 vz-damper tests still green; (2) an always-on FlightManager (background thread, ZERO torch/numpy, NOT under the GPU sim''s ROLLOUT_LOCK) serves it over /ws/flight; (3) a Bench frontend tab (bench.js) with a software Start GATED on telemetry showing ARMED + MSP-OVERRIDE (the radio still owns enable + instant kill; software never writes arm/aux — extends parent white-surf-8279''s /ws/live pattern); (4) an opt-in parallel CPU-torch sim of the SAME deployed policy over /ws/live beside the real drone (also fixed a latent bug: hover_blind was missing from GATELESS_TASKS so the Studio couldn''t run it live); (5) auto flight-report on landing. Verified end-to-end headlessly via a self-driving fake bridge (--bridge fake / NW_FLIGHT_FAKE=1): a full takeoff walked countdown→seek→rise→hover→land→released with the real seed policy over /ws/flight, ROLLOUT_LOCK never taken, CSV + report written. +2 test files (test_flight_controller, test_flight_ws), full suite green. No hardware flight yet — the safety interlock is preserved end-to-end but the real-drone bench run is the user''s. Commits ec7c5c3 (engine), 1fdab56 (manager+ws), 0a05e85 (Bench tab), 179e859 (parallel sim), e770d2f (auto-report), 33e26c4 (docs).'
origin:
  backend: flywheel
  node_id: f0111520-dada-528a-8f6f-5797a510f599
  slug: rapid-meadow-0957
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 8cfdbdcd-83ed-5aae-af96-5e87cb35ae2d
  slug: broad-tree-5361
  revision: 0
  pushed_at: '2026-08-09T21:27:48+00:00'
  content_sha256: c01e9d9216699e1b6b8c22b65c9fbe3744ae19384b67803c83194ffec6e710f5
---
# Unified bench dashboard — one page for real flight + parallel sim

**Idea/framing.** The project had two disjoint control surfaces: the **Studio** (GPU sim, `/ws/live`, `white-surf-8279`) and the **offboard pilot** (`scripts/pilot.py`, the real Air65 II over the XIAO MSP bridge — the validated RPM-anchor flight engine, parent `aged-wildflower-8839`). A real flight was a manual grind (export `$NW_BRIDGE`, `pilot.py selftest/check`, `pilot.py fly --takeoff --ack-props-on`, watch a console, re-invoke per flight). This node unifies them into **one always-on browser page** — the Studio's **Bench** tab: open it → the bench is connected → click **Start** to fly the *real* drone → watch live telemetry/metrics → optionally watch a *simulated* copy of the same policy beside it.

## Setup (the change vs the two parents)

Built in 5 phases, one commit each:

1. **Extract the flight engine (`ec7c5c3`).** `cmd_fly`'s inline loop → an importable, steppable `neural_whoop.pilot.FlightController` (+ `config`/`policy`/`telemetry`). Every loop local became an instance attr; `step()` is one 50 Hz tick; `Phase` derives from the *same inline predicates* `cmd_fly` always used. `start_mode="switch"` (CLI, override edge auto-starts) vs `"software"` (UI, `request_start` gated on ARMED + override). Pure stdlib — zero torch/numpy. `scripts/pilot.py` is now a thin CLI shim re-exporting the surface, so `sim_vs_real.py` + `test_pilot_vz_damper.py` keep working and `selftest` is byte-identical.
2. **Always-on FlightManager + `/ws/flight` (`1fdab56`).** A background thread connects-with-retry, runs the controller, publishes each frame under a lock with an incrementing `seq`; **not** wrapped in `ROLLOUT_LOCK` (the MSP link is a different resource from the GPU sim; many viewers may watch one flight). A self-driving `FakeFlightBridge` (`--bridge fake` / `NW_FLIGHT_FAKE=1`) runs the whole backend with no hardware.
3. **Bench frontend tab (`0a05e85`).** `bench.js` (mirrors `live.js`): ARMED/OVERRIDE dots, phase chip, a telemetry HUD + rolling tilt/vz trend, a real-drone attitude glyph, flight-param inputs, Start/Abort.
4. **Parallel CPU-torch sim (`179e859`).** An opt-in toggle opens `/ws/live` flying the SAME deployed policy as a cyan twin beside the real drone; `live.py` frames now carry a `metrics` block (reward + hero tilt/vz + `task.metrics`). Fixed a latent bug — `hover_blind` was missing from `GATELESS_TASKS`, so the Studio passed `n_gates` to its gateless `HoverConfig` and could not run any hover_blind policy live.
5. **Auto flight-report on landing (`e770d2f`).** On a completed (RELEASED) flight the manager detaches `scripts/flight_report.py` (numpy/matplotlib run in ITS OWN process so the manager stays torch/numpy-free) and emits a `{type:report}` headline (hover tilt median, vz-rail flags, link p99, battery sag).

## The safety interlock (non-negotiable, preserved end-to-end)

The software **Start** only sets the flight clock, and is **enabled only when telemetry shows the drone ARMED + MSP-OVERRIDE engaged** on the Pocket radio. The radio still owns **enable + instant kill**: dropping override or disarming aborts instantly via Betaflight's ~300 ms MSP-freshness handback. Software **never** writes arm/aux — stopping the RC stream is the only "stop". `request_start()` is rejected unless `armed_seen and override_on`; the mid-flight override-off / stale-obs / crash aborts fire in both start modes. Enforced by `tests/test_flight_controller.py` (Start-gating, abort on override-drop and on sustained >110° roll, a golden RC-output regression) and `tests/test_flight_ws.py` (the same over the websocket, + `ROLLOUT_LOCK` stays unlocked throughout).

## Results (implementation evidence — no drone on this box)

- **Torch-optional boundary holds:** importing `neural_whoop.pilot` + `studio.flight` loads **zero** torch/numpy.
- **End-to-end fake flight (the attached artifact).** A full `--takeoff` flight driven over `/ws/flight` with the **real deployed seed policy** (`hover_blind_air65_d50var_s8`, obs-5×8) walked the whole phase enum — `countdown → seek → rise → hover → land → released` — 583 frames: the throttle spools at the seek→liftoff transition, the policy holds ~1340 µs through hover at ~1–3° tilt (the fake's scripted wobble), and `us_thr` ramps DOWN to a controlled landing with `vz_est` going negative on descent. `ROLLOUT_LOCK` never taken; a flight CSV + report pack written.
- **Tests:** new `test_flight_controller.py` (5) + `test_flight_ws.py` (5, incl. the auto-report) + extended `test_live.py`; full suite green. `pilot.py selftest` deploy parity unchanged (worst |err| 4.63e-08).

## Verdict / honesty

**GREEN — the dashboard is built and verified headlessly end-to-end; the safety interlock is preserved.** Honesty: (1) **not flown on real hardware from the dashboard yet** — the bench run is the user's; the fake bridge is physically crude (it exists to exercise the pipeline, not to validate flight dynamics). (2) The Bench frontend (`bench.js`) has no JS unit harness — consistent with `live.js`; it's backed by the fake-bridge backend tests. (3) The parallel sim needs a CPU torch wheel on the Mac (opt-in, off by default so the real path stays pure-stdlib). (4) The fake-flight artifact is a *fake-bridge* telemetry trace, not a real flight — the real-flight telemetry contract is unchanged (the same 24-col CSV / `flight_report` pack the RPM-anchor flights used).

## Lineage

- Extends **white-surf-8279** (Live interactive Studio, `/ws/live`): the bench dashboard reuses its websocket/session pattern for the parallel sim and generalizes it to a real-drone `/ws/flight`.
- Extracts + flies the engine validated in **aged-wildflower-8839** (RPM-anchor vz fix VALIDATED in flight) — the same `pilot.py fly` state machine, now steppable.
- The latency tail called out by aged-wildflower-8839 remains the next axis (bridge / Stage-2), untouched here.
- Commits `ec7c5c3`, `1fdab56`, `0a05e85`, `179e859`, `e770d2f`, `33e26c4`.