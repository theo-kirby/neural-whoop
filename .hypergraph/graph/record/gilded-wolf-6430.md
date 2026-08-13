---
node_id: bac358f0-8cd7-5e49-9f97-7936e79e9e9b
slug: gilded-wolf-6430
title: 'OTA escape hatch: the drone XIAO''s USB flash becomes a one-time event — ArduinoOTA command+rescue paths, all solder nets config-defined with a build-time collision check, mac_probe and flow_probe retired to over-the-air equivalents'
created_at: '2026-08-13T14:06:31+00:00'
parents:
- shiny-queen-9632
- snowy-brook-2829
summary: ''
---
## What

Made the drone-side XIAO's USB flash a one-time event (commit `cbd720d`). The bridge firmware
grew an over-the-air reflash path (ArduinoOTA), every solder net became a config define with a
build-time collision check, and the two bring-up rituals that used to require flashing probe
firmwares over USB — MAC discovery and the PMW3901 `rad_per_count` slide calibration — now run
over the normal link (`bench.py ota` / `bench.py flow-cal`).

## Why

The 2026-08-13 new-airframe rebuild (fresh Air65 II, all pads intact; fresh bind + Betaflight
config + clean maiden earlier today) physically buried the XIAO's USB port: the Operator can
reach it "a couple more times without breaking it". The old workflow assumed cheap USB —
`mac_probe`, `flow_probe` calibration, `i2c_scan`/`uart_scan` diagnosis, and every pin move was
a reflash. The rebuild also rewired several nets by chassis-fit necessity, so at least one more
pin-remap flash is guaranteed, and the old config had a live hazard: the retired 2026-08-08
`wifi_config.h` put FC_RX on GPIO4, which is also the flow-CS *default* — two nets on one pin
and nothing complained.

## Method

- **OTA escape hatch** (`firmware/xiao_bridge/src/main.cpp`): WiFi/UDP build serves ArduinoOTA
  full-time beside UDP. ESP-NOW build gets two paths: a *command* path — new bridge-local MSP
  id **194** whose payload must be the 4-byte magic `NWOT` (a link-dropping command must be
  impossible to send bare); the bridge acks (`u8 accepted, u8 will_reboot`), leaves ESP-NOW,
  joins the `wifi_config.h` network as `whoop-bridge.local`, and serves OTA for 3 min (LED:
  10 Hz strobe), rebooting into the new firmware on success or back into service on timeout —
  and a *rescue* path: if no link packet has EVER arrived 2 min after boot (wrong MAC/channel,
  dead dongle — the command path can't reach it either), it opens the same window unprompted,
  forever cycling listen→window→restart, so a battery plug-in always suffices to reflash even
  with a broken `espnow_config.h`. First real packet disarms the fallback for the session.
- **Pins**: ToF I2C pins were hardcoded (`Wire.begin(D5, D6)`) — now `TOF_SDA_PIN`/`TOF_SCL_PIN`
  beside `FC_*`/`FLOW_*` in `wifi_config.h`; `main.cpp` static_asserts all 8 nets pairwise
  distinct (C++11-safe constexpr recursion), so the GPIO4 double-booking class of bug now fails
  the build.
- **Host**: `bench.py ota` (opens the window, prints the exact upload command),
  `bench.py flow-cal --height <m>` (the README slide test computed from two snapshots of the
  bridge's cumulative flow counters — snapshot, slide exactly N mm, snapshot, difference with
  `wrap_delta`; refuses under 50 counts and reports cross-axis contamination). New pio envs
  `xiao_bridge_ota`/`xiao_bridge_espnow_ota` (`upload_protocol = espota`).
- Boot logs in both builds print the board's own STA MAC (replaces the `mac_probe` flash).
- Corollary documented in the firmware README: never flash a radio-less probe firmware onto the
  assembled board — that is the one move that re-requires USB.

## Result

All three firmware envs (`xiao_bridge`, `xiao_bridge_espnow`, `espnow_dongle`) compile: flash
20.2% of the 8 MB part's `0x330000` app slot, and the board's default partition table already
carries the dual OTA slots. `tests/test_msp.py` round-trips the id-194 frame against the
firmware's exact framing (magic at offset 5, size ≥ 4) — 17 passed, 1 skipped (pyserial pty) on
the bench Mac. Unverified until the Operator's one USB flash: the OTA window on real hardware,
and the new drone's actual pin map (placeholder = README-standard layout; the config carries a
loud marker). Related same-day fix, committed separately by the Operator (`b563fba`):
`BF_MAX_RATE_YAW` 345→350 °/s — ACTUAL-rates CLI stores tens of deg/s, so the FC snaps 345→350
and the host constant must match the FC, not the ideal 2×sim value.

Also earlier today, unrecorded hardware context this node depends on: fresh ELRS bind
(`bind_rx` + Lua), full Betaflight config pass (ACTUAL rates 690/690/350, AIRMODE, MSP override
mask 15, UART1 MSP 115200), and a clean manual maiden on the new airframe. The rebuild node
proper (wiring + bench gates + weight) lands when the assembled stack passes `bench.py checkup`.

## Repo

- repo: git@github.com:theo-kirby/neural-whoop.git
- branch: main
- commit: cbd720dbe91b9ed3bac3a7795b1502727e1680d6

## State Impact

- target: modest-raven-7153 — new claim: the assembled deploy stack is field-serviceable without USB — bridge firmware reflashes over the air (command + boot-rescue paths), every solder net is a wifi_config.h define guarded by a build-time GPIO-collision static_assert, and flow rad_per_count calibrates over the link (bench.py flow-cal)
- target: forest-timber-8727 — new claim: the ESP-NOW build carries bridge-local MSP 194 (magic-gated OTA window) plus a never-linked boot fallback, so a mis-configured espnow_config.h is recoverable from a battery plug-in; hardware verification of the window pends the one USB flash
