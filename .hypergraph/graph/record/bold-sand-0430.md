---
node_id: 9b146215-ca4c-508f-90f5-f7fed63bedf7
slug: bold-sand-0430
title: 'Flow breakout convicted: chip-id silent on 12/12 pin configs across two ESPs — wiring, power, RST, config all acquitted; wire_test probe added; FC UART moved to D0/D1; Desk-Flow blocked on a replacement PMW3901'
created_at: '2026-08-16T11:30:45+00:00'
parents:
- vast-fjord-9379
summary: ''
---
## What

Systematic conviction of the replacement PMW3901 flow breakout as defective (or not an SPI
PMW3901 at all), and acquittal of everything else: all six deck wires, both solder ends, CS,
power, RST, the XIAO's GPIO drivers, and the pin configuration. Along the way the bridge probe
family gained `wire_test` (commit `4a2c637`) and the deck's FC UART moved to D0/D1.

## Why

The Operator's retrained Desk-Flow policy needs the optical flow channel, but the transplanted
deck (sensor not from the crash) probed ABSENT on the rebuilt original-Air65 airframe
([vast-fjord-9379]). The bridge's six-permutation hunt already ruled out data-pin ordering, so
the fault had to be a wire, a short, the config, or the part.

## Method

Elimination ladder, each rung a measurement:

1. **Config vs iron mismatch found first**: the resolder had landed flow MOSI on D4 (GPIO5) —
   which was `FC_RX_PIN`. Fixed by moving FC RX to the vacated D1 (GPIO2); collision check
   passed; still ABSENT on the now-correct pins.
2. **`wire_test` probe firmware** (new, `firmware/xiao_bridge/src/wire_test.cpp`): internal
   pullup/pulldown scan per net, pairwise driven-bridge scan, a 50 µs open-drain sink to
   discriminate hard rail ties from resistor pullups, and a 1 Hz per-net toggle paced for a
   multimeter (DC volts only — the bench meter's beep mode is untrustworthy).
3. Scan verdicts: CS/CLK/MIS "tied high" = breakout's own pullups (sink test: soft) — wires
   PROVEN; MOS floats = no pullup on that pad; meter-on-pad during the 1 Hz toggle proved the
   MOS wire end-to-end anyway. No hard ties, no pairwise bridges. An apparent
   "meter-lead-reboots-the-board" clue was traced to the deck's flaky USB connection, not a
   rail short.
4. **RST strap** (VCC→RST on the breakout) removed, redone properly, verified 3.3 V — no
   change.
5. **Transplant**: sensor moved to a spare XIAO (D7-D10), `flow_probe` flashed with `-D` pin
   overrides (its `pmw3901.h` defaults ignore `wifi_config.h` — first probe ran on the wrong
   CS and was discarded), then all six SCK/MISO/MOSI permutations flashed sequentially.

## Result

- Chip-id read `0xFF`/`0x00` (floating bus) on **12/12 pin configurations across two boards
  and two harnesses**; the chip never drove MISO once. Verdict: the breakout does not speak
  SPI — defective, or a non-SPI module (model/silk unconfirmed).
- Deck status: ToF healthy (`VL53L1X up, short mode, 40 Hz`), ESP-NOW paired to dongle
  `68:EE:8F:50:32:00` ch 11, bridge at HEAD, FC UART ready on **D0→R1, D1→T1**. Flow wiring
  proven good, so a replacement PMW3901 on the same wires will be auto-announced by the 5 s
  re-probe with zero flashing; re-measure `rad_per_count` (`bench.py flow-cal`) on the new
  unit before any `--rad-per-count` flight.
- Desk-Flow deploy is blocked on the replacement part only; Desk-Hover/`hover_tof` is not
  blocked.

## Repo

- repo: git@github.com:theo-kirby/neural-whoop.git
- branch: main
- commit: 4a2c63797c0a4332afd1c6e3a01b315522774b81

## State Impact

- target: modest-raven-7153 — flow sensor is DOWN (breakout convicted defective by 12/12-permutation elimination on two boards; deck flow wiring proven good, replacement auto-detects over the air, rad_per_count must be re-measured); FC UART reassigned to D0/D1; wire_test probe firmware added (4a2c637); Desk-Flow deploy blocked on the part, hover_tof path unblocked
