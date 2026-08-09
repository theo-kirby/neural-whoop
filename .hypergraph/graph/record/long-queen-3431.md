---
node_id: c272fdcf-c209-5b27-98c1-0aaf2c51fa34
slug: long-queen-3431
title: Air65 II purchased — control/compute-path branch map (offboard ELRS · ESP32 bridge · gamepad · fully-onboard)
created_at: '2026-07-03T17:49:12.759237+00:00'
parents:
- bitter-fire-0679
- sparkling-lab-8864
summary: 'Air65 II bought 2026-07-03; researched + mapped the control/compute-path branch space the real hardware opens (docs/SIM2REAL.md @ dbdd70d). Verified: Matrix 1S 5IN1 II has UART1+UART4 free for a companion; BF MSP override is real (~100 Hz default, 300 ms freshness, msp_override_failsafe in 4.5+) while companion-emulated CRSF-RX is unproven; host→ELRS-TX-module CRSF at 250 Hz is proven (single-digit-ms OTA); XIAO ESP32-S3 Sense (~3–5 g) gives ESP-NOW ≈5.6 ms links, BLE-only radio (Xbox pads pair via Bluepad32 fw≥5.15; PS4/PS5 don''t), and sub-ms int8 TinyPolicy inference via esp-nn. Branches: A offboard-ELRS (plan of record, 40–100 ms), B ESP32 ESP-NOW bridge (~20–50 ms; solves the flow-deck downlink risk), C1 gamepad-via-host (the manual fallback), C2 gamepad-BLE-direct (demo), D1 fully-onboard on the XIAO (~5–20 ms; onboard hover needs no camera), D2 in-firmware (stays deferred). Each branch = a split-latency DR config (uplink_latency_steps seam), not new code. Verdict: A stays first-flight; B is the telemetry gateway to D1.'
origin:
  backend: flywheel
  node_id: c272fdcf-c209-5b27-98c1-0aaf2c51fa34
  slug: long-queen-3431
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
---
# Air65 II purchased — control/compute-path branch map

**Hypothesis (framing).** With the airframe bought (2026-07-03), the useful decision space is *where the policy runs × how commands reach the FC*. Each branch should reduce to a domain-randomization config over the existing split-latency seam (`uplink_latency_steps`/`uplink_interval_steps`, docs/CONTRACT.md), so sim work transfers across all of them.

**Setup.** Web research (two sweeps: FC/Betaflight control seams; ESP32 companion facts), folded into `docs/SIM2REAL.md` @ commit `dbdd70d` (theo-kirby/neural-whoop).

## Verified I/O facts
- **Matrix 1S 5IN1 II (STM32G473CEU6):** 4 UARTs — UART2=VTX, UART3=onboard ELRS RX (freed by removing a resistor), **UART1+UART4 free** for a companion. Ships on a BF 2026.6.0 custom build. (betafpv.com product pages)
- **Betaflight external control:** MSP override (`msp_override_channels_mask` + MSPRCOVERRIDE) is current; `msp_override_failsafe` (BF 4.5, PR #13380) fixes the RC-loss failsafe trap; **300 ms per-channel freshness window** in `rx/msp.c`; serviced ~**100 Hz** default (`serial_update_rate_hz`). Companion-emulated CRSF-RX into the RX UART: electrically plausible, **no confirmed working writeup** (BF discussion #14064 failed, unanswered). MAVLink serial-receiver provider (BF 2025.12+ × ELRS MAVLink mode @460800) = bidirectional RC+telemetry on one link.
- **Host→ELRS uplink proven:** driving an ELRS TX module's CRSF pin directly (RC_CHANNELS_PACKED @ ~250 Hz; RadioMaster Ranger Micro @460800) binds + flies a BF quad (Devana project, Jan 2025); `elrs-joystick-control` does gamepad→CRSF→module. Single-digit-ms OTA at 250–500 Hz. MSP-over-CRSF backchannel is slow (telemetry-ratio-gated); MAVLink mode is the real downlink.
- **XIAO ESP32-S3 / Sense:** ~3–5 g class (weigh on arrival — no primary source), 8 MB PSRAM+flash, OV2640/OV3660 camera; **ESP-NOW ≈ 5.6 ms median** (Electric UI benchmark), WiFi UDP ~9 ms tuned, BLE conn-interval floor 7.5 ms. **BLE-only — no BT Classic**: Xbox Series pads pair via Bluepad32 (controller fw ≥5.15 is BLE); PS4/PS5/Switch pads need BT Classic (original ESP32 only). int8 TinyPolicy-size MLP ≈ **0.1–0.4 ms** via esp-nn on S3 (extrapolated from published FC-layer benchmarks); CNN-class camera detection 3–10 fps, cheap blob/marker maybe 15–30 fps (unbenchmarked). Prior art: DroneBridge/ESP32 (MSP over ESP-NOW/WiFi — the exact companion pattern), esp-drone, esp-fc.
- **Payload:** +4–6 g companion → ~29–31 g AUW, TWR ~3.5–4:1 — flyable; lands back inside the old Meteor75-massed DR band (28–36 g). No rigorous 65 mm payload test published (flagged).

## The branches
| Branch | Path | Rate | Latency band | Verdict |
|---|---|---|---|---|
| **A. Offboard ELRS** (plan of record) | host policy → ELRS TX module → onboard RX | CRSF 250 Hz | ~40–100 ms e2e (camera loop) | **First flight.** Proven, real failsafe semantics, manual takeover on the same link. |
| **B. ESP32 bridge** | host → ESP-NOW → XIAO on UART1 → MSP into FC | ~100 Hz (default) | ~20–50 ms | **Solves the flow-deck downlink** (companion reads flow+ToF, ships telemetry) — directly resolves the SIM2REAL 'flow forwarding may need a companion MCU' open risk. Gateway to D1. |
| **C1. Gamepad via host** | Xbox pad → PC → CRSF → module | 250 Hz | ~10–20 ms | The manual-fallback rig; build with A immediately. |
| **C2. Gamepad direct** | Xbox pad → BLE → onboard XIAO → FC | ≥7.5 ms interval | ~15–30 ms | Fun demo (no radio, no PC); off critical path. |
| **D1. Fully onboard** | XIAO runs int8 policy; flow (+camera) obs; UART to FC | local | **~5–20 ms (lowest)** | Post-Stage-2. Decomposes: **onboard `hover` needs no camera** (flow-velocity + FC attitude only) → realistic near-term milestone; onboard gate perception is the hard tail. |
| D2. NN in BF firmware (G473) | — | — | lowest | Stays deferred (RAM-tight). |

## Honesty / unknowns
XIAO exact weight (weigh it); which camera sensor ships (OV2640 vs OV3660); sustained ESP-NOW rate at 100+ Hz; actual on-device MLP latency (10-line TFLM benchmark when hardware arrives); CRSF-RX emulation unproven; no quantitative 65 mm payload test exists.

## Lineage
Parents: airframe-of-record `sparkling-lab-8864` (now **purchased**, upgrading it from decision to hardware-in-hand) and the sim2real plan `bitter-fire-0679` (whose 'policy execution = offboard' fork this expands into a branch space). The split-latency DR seam (uplink_latency_steps, commit 55ff26e) is the sim-side hook each branch maps onto.