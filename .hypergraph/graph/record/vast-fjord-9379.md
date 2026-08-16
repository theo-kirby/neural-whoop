---
node_id: 96618958-41f6-5bc6-92b9-8ad87b9764c3
slug: vast-fjord-9379
title: 'Airframe swap: Air65 II fleet dead (2), replaced by an ORIGINAL Air65 — same G473/ICM42688P/UART1 plan, 5A ESC; FC configured to contract + AIRMODE finally enabled, clean manual maiden 2026-08-16; bridge not yet wired'
created_at: '2026-08-16T08:33:54+00:00'
parents:
- gilded-wolf-6430
- wild-shape-7463
summary: ''
---
## What

Both Air65 II airframes are dead (including the fresh 2026-08-13 rebuild from
[gilded-wolf-6430]). The fleet is now an **original BetaFPV Air65** — bought as an intended
Air65 II replacement, kept after assessment showed the swap is gentle. The Operator configured
its FC to the bridge contract, bound the onboard ELRS to the Pocket, and flew a clean manual
maiden flight on 2026-08-16. The XIAO bridge deck is **not yet wired** to the new FC.

## Why

Two dead airframes ended the Air65 II line here; the replacement arrived as the older model.
Assessment (web specs + repo-assumption inventory): the original Air65's **Air 1S 5IN1 FC is
the same STM32G473CEU6 + ICM42688P** as the Matrix II, with the **same UART map** (UART2=VTX,
UART3=onboard serial ELRS, **UART1 free with exposed T1/R1 pads**) and BB51/Bluejay ESC — so
the entire bridge plan of record transfers. Real deltas: **5A ESC (was 12A)** — the main risk
under the ~6 g companion stack; lower-KV 0702 motors; 17.3 g dry (inside the existing mass-DR
band, so no retraining expected); different PCB pad placement; classic 4-grommet mounting
(the II's 3-point "80% more durable" mount is gone — relevant given the body count).

## Method

Betaflight over USB on the Configurator machine, per `firmware/xiao_bridge/README.md:167-172`:

- Ports: **UART1 → MSP 115200** (verified via CLI `serial`).
- `set msp_override_channels_mask = 15`; **MSP RC Override** mode on the Pocket's override
  switch; `msp_override_failsafe` left at default (off), per the standing open decision.
  (Stock BETAFPVG473 4.5.0 may lack the MSP_RC_OVERRIDE cloud-build define; the fallback was a
  custom cloud build with that define. The mode is present and working; which path was needed
  was not recorded.)
- Rates: **ACTUAL, expo 0, 690 deg/s roll/pitch, 350 yaw** — matches `pilot/config.py:18-26`.
- **AIRMODE permanently enabled** — clearing the deploy prerequisite flagged since the flip
  stall finding (never done on any Air65 II).
- **Bidirectional DShot on**, DSHOT300, motor poles 12; motor order/direction checked props-off.
- ELRS bound via CLI `bind_rx` + Pocket Lua Bind; existing whoop model reused (AETR, same
  arm/override switches).

Then a manual maiden flight on the Pocket: normal handling, no anomalies reported.

## Result

- New airframe is flight-worthy under manual control with the FC configured to the exact
  contract the pilot/bridge stack assumes. AIRMODE prerequisite is now CLEARED.
- Deploy path is **link-down** until the XIAO deck (salvageable from a dead bird; FC-agnostic
  by design) is soldered to the new FC's R1/T1/5V/GND and `wifi_config.h` pins updated.
- Board-specific empirics from the Air65 II are **unverified on this FC** and must be
  re-established before any policy flight: gyro/attitude signs (`pilot.py check`),
  `hover_us` (was 1410), thrust curve/TWR (5A ESC + 27kKV motors will land below the old
  ~4:1), liftoff-seek constants, and a live bidir-DShot RPM confirmation over MSP.
- Docs (`docs/SIM2REAL.md`, bridge README) still describe the Matrix 1S 5IN1 II — read as
  "the plan", not the as-built board, until updated.

## Repo

- repo: git@github.com:theo-kirby/neural-whoop.git
- branch: main
- commit: b6a037e04e2520ff2e9fed5ebcccc54fc7d96915

## State Impact

- target: modest-raven-7153 — fleet is now an original Air65 (Air 1S 5IN1: same G473+ICM42688P+free UART1, but 5A ESC); FC configured to the bridge contract and AIRMODE prerequisite cleared; manual maiden clean; link DOWN until the XIAO deck is re-soldered, and all Air65 II board empirics (attitude/gyro signs, hover_us, TWR, RPM telemetry) are unverified on this FC
