---
node_id: a8233a85-5813-537d-a36c-1a50bf1a4529
slug: aged-firefly-8064
title: 'Method: measured height — VL53L1X (CJMCU-531) on the bridge: MSP_BRIDGE_TOF seam, tof_m flight channel, measured replay z'
created_at: '2026-07-13T08:06:56.922038+00:00'
parents:
- still-flower-6355
- young-fire-2086
- royal-bar-2003
summary: 'The CJMCU-531 (VL53L1X ToF) arrived — the $4 half of the still-flower-6355 one-module decision, ahead of the XIAO Sense/PMW3901 — and is integrated end-to-end as the project''s first MEASURED (non-IMU-integrated) state channel. Change vs parents: the xiao_bridge (young-fire-2086) gains a downward VL53L1X on its free stock I2C (D4/SDA D5/SCL; short mode ~40 Hz) and answers a bridge-local MSP v1 cmd 192 (MSP_BRIDGE_TOF) itself — consumed, never forwarded, FC untouched, still a pure proxy with no sensor wired. Host side: decode_bridge_tof (validity-gated: sensor_ok + status 0 + age<200 ms), bench.py tof desk bring-up, Telemetry.poll(want_tof) every pilot tick, tof_m as flight-CSV col 25 (legacy 24-col logs still load), flight_metrics()[''height''] (hover mean/sd, max, airborne coverage), and flight_to_replay pos z = the measured height (meta.pos_z_measured, NaN gaps interpolated) retiring the ∫vz_est vertical-only stub that let the royal-bar-2003 ceiling crash go unseen. Verified on the fake bridge end-to-end (launch flight → 196/196 rows with tof_m → report prints the height line → replay z measured) + 81 unit tests green + firmware compiles (pio). Telemetry-only by design (NOT in obs, no control coupling — measure before use). Real-sensor wiring/bring-up pending (bench.py --udp <ip> tof). Commits ea6dc57 (firmware+codec+bench) + efcf393 (pilot+report). VERDICT: method shipped, software-verified; the real-hardware range check is the next bench session''s first item.'
origin:
  backend: flywheel
  node_id: a8233a85-5813-537d-a36c-1a50bf1a4529
  slug: aged-firefly-8064
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
---
# Measured height: VL53L1X (CJMCU-531) on the MSP bridge

**Goal.** The CJMCU-531 breakout (VL53L1X time-of-flight rangefinder) arrived — the ~$4 companion half of the `still-flower-6355` one-module decision (the XIAO ESP32-S3 Sense + PMW3901 are still shipping). Integrate it NOW as the project's first *measured* (non-IMU-integrated) state channel: metric height. Motivation is direct: the first real flight (`royal-bar-2003`) crashed into the ceiling on a phantom-sink ∫accel `vz_est` drift, and the flight replay's `pos` has been an honest-but-blind vertical-only ∫vz stub ever since. A downward ToF replaces integration with measurement.

## Setup (what shipped)

**Bridge firmware (`firmware/xiao_bridge`, commit `ea6dc57`).** The VL53L1X rides the XIAO's *stock* I²C pins D4/SDA + D5/SCL — free because the FC UART was rewired to D9/D10 after the GPIO44 ESD casualty. Short-distance mode, 20 ms timing budget, free-running ~40 Hz (ambient-robust to ~1.3 m — the whoop hover band; `Medium` mode is the documented knob for taller spaces). The bridge answers MSP v1 cmd **192** (`MSP_BRIDGE_TOF`, a bridge-local id) itself with `<u16 range_mm, u8 status, u16 age_ms, u8 sensor_ok>` and never forwards that id — the transparent-proxy contract holds for everything else, the FC config is untouched, and with no sensor wired the bridge boots and proxies exactly as before (`sensor_ok=0`). Compiles clean (`pio run -e xiao_bridge`, Pololu VL53L1X lib).

**Host seam (commits `ea6dc57` + `efcf393`).**
- `bench/msp.py`: `MSP_BRIDGE_TOF` + `decode_bridge_tof` — `range_m` is populated only when sensor_ok ∧ status==0 ∧ age<200 ms, so callers never re-derive the validity gating. `bench.py tof` is the wave-a-hand desk bring-up (`python3 scripts/bench.py --udp <bridge-ip> tof`).
- `pilot`: `Telemetry.poll(want_tof=True)` every controller tick (bridge-answered → zero FC UART cost; errors harmlessly over USB); `height_m()` freshness-gated; `tof_m` is **flight-CSV column 25** (all three LOG_COLUMNS copies updated; legacy 24-col logs still load with `tof_m→NaN`); the Bench live frame carries `telemetry.tof_m`.
- `FakeFlightBridge`: synthesizes height from a throttle integral so `--bridge fake` / `NW_FLIGHT_FAKE=1` exercises the entire pipeline with no hardware.
- `analysis/flight_log.py`: `flight_metrics()["height"]` — hover mean/sd (the real height-hold number), max, and airborne coverage (dropout diagnostic). Headline comparison CSV gains `hover_height_m/sd`.
- `viz/replay.py::flight_to_replay`: replay `pos` z is now the **measured** height (NaN gaps linearly interpolated, edges held; `meta.pos_z_measured=true`); the ∫vz_est stub remains the fallback for pre-ToF logs. `tof_m` joins the scene extras for the Studio HUD.

## Results (software verification — fake bridge, no hardware yet)
- End-to-end fake flight (launch → hover → land → RELEASED): **196/196 CSV rows carry tof_m**; `flight_report.py` prints the new height line (`hover 0.41 ± 0.36 m, max 3.00 m, 100% airborne coverage` — the fake's crude throttle-integrated z, not physics); replay `pos_z_measured=true` with z tracking the synthesized height. Artifacts attached are THIS fake-bridge verification pack, labeled as such.
- **81 unit tests green** (msp codec incl. the validity gate, flight_log legacy/height/replay-z, controller, flight-ws, pilot obs, replay, studio, live). The one deselected studio test is the bench Mac venv's missing tensorboard — pre-existing, unrelated.
- Firmware compiles for the XIAO ESP32-S3 target.

## Verdict / honesty
**Method shipped and software-verified; NOT yet validated on the real sensor** — the CJMCU-531 is in hand but unwired. The fake-bridge numbers above verify plumbing, not ranging. Design choices to revisit at bring-up: short-mode's ~1.3 m ambient ceiling (fine for hover heights; `Medium` trades rate for reach), the 200 ms freshness gate, and whether prop-wash/surface texture degrades valid-return rate (the `coverage_airborne` metric exists precisely to measure that). Deliberately **telemetry-only**: not in obs, no control coupling. The planned use ladder: (1) ground-truth the vz_est error, (2) a measured-height damper for the blind pilot, (3) an obs channel for a height-aware hover retrain, (4) flow×height velocity fusion when the PMW3901 lands (ROADMAP #9 plan A).

## Lineage
Parents: `still-flower-6355` (the one-module sensor DECISION this purchase executes — the ToF half arrived first), `young-fire-2086` (the xiao_bridge method this extends with its first sensor), `royal-bar-2003` (the vz_est-drift ceiling crash that makes measured height the right next channel). Docs: SIM2REAL 'Measured height' block, ROADMAP #9 update, firmware README wiring. Next node: real-sensor bring-up + first ToF-instrumented flight (a `kind:measurement` under this).