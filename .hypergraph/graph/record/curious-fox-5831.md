---
node_id: 9bccc5d3-9de3-5d4b-b654-d0f7c32dbe45
slug: curious-fox-5831
title: 'MTF-02P bridge integration: one UART module replaces both downward sensors (VL53L1X + PMW3901), reply formats unchanged — built, not yet bench-tested'
created_at: '2026-08-20T12:28:30+00:00'
parents:
- quiet-bramble-1724
- bold-sand-0430
summary: ''
---
## What

The PMW3901's replacement arrived and consolidates: bridge firmware support for the **MicoAir
MTF-02P**, one UART module carrying BOTH downward sensors (ToF rangefinder to a 6 m spec +
optical flow), replacing the VL53L1X + convicted-dead PMW3901 pair. New header-only MSP v2
stream parser (`firmware/xiao_bridge/include/mtf02.h`), `main.cpp` sensor half rewritten around
it, `mtf_probe` bench/calibration firmware added, both old buses (I²C + SPI) deleted from the
main builds. The two bridge-local reply formats (cmd 192 `MSP_BRIDGE_TOF`, cmd 193
`MSP_BRIDGE_FLOW`) are **byte-identical to before**, so the entire host stack — `bench.py
tof/flow/flow-cal/checkup`, `Telemetry.flow_delta`, `flow_to_velocity`, the pilot, the Studio
Real tab — is oblivious to the swap. Commit `818e0f5`; all 16 PlatformIO envs build.

## Why

Direct consequence of the conviction chain ending at [quiet-bramble-1724]: no functioning
PMW3901 was ever attached, and the Operator ordered a replacement. The MTF-02P was chosen over
a bare GY-PMW3901 because it deletes three standing problems at once: (1) it carries its own
ToF, so the VL53L1X and its blocking-I²C budget go with it; (2) that ToF specs to 6 m where the
VL53L1X trusted ~1.3 m — the exact ceiling behind the 0.7 m deploy-height cap and the 1.0 m
setpoint failure; (3) it is a UART *talker* (unsolicited frames, no init handshake, no
register-level bring-up), eliminating the entire class of SPI/I²C bus failure this project just
spent a week convicting.

## Method

- **Protocol**: in MSP mode the module free-runs at 115200 8N1, 50 Hz, pushing MSP v2 sensor
  frames — `MSP2_SENSOR_RANGEFINDER` 0x1F01 (`u8 quality, i32 distance_mm`, negative = out of
  range) and `MSP2_SENSOR_OPTIC_FLOW` 0x1F02 (`u8 quality, i32 motionX, i32 motionY`) — the
  INAV sensor convention; the bridge impersonates an INAV FC and only ever listens. Flow units
  are uncalibrated by design (INAV applies `opflow_scale`), which maps 1:1 onto the existing
  measured `--rad-per-count` seam.
- **Parser** (`mtf02.h`): incremental non-blocking state machine over the UART FIFO
  (`$X<` header, flag/function/size, crc8_dvb_s2 over flag..payload). CRC implementation
  verified against the documented MSP v2 `MSP_IDENT` vector (`24 58 3c 00 64 00 00 00 8f` →
  0x8F, PASS). Oversize/unknown frames are consumed byte-for-byte so they cannot desync the
  stream. Flow counts ACCUMULATE into the running sums (the cumulative, non-destructive
  contract is unchanged); range keeps the freshest sample with the sensor's own out-of-range
  flag mapped onto the old `range_status` slot (0 = valid, 255 = out of range).
- **Liveness replaces init**: there is no handshake to fail, so presence = frames arriving
  (`sensor_ok` = newest frame < 500 ms; the host's `valid` gate at age < 200 ms is unchanged).
- **Self-diagnosis, safest-possible form**: the SPI permutation probe's successor is a
  LISTEN-ONLY pin-swap scan — while zero bytes have ever arrived, the RX alternates between the
  two harness wires each 5 s heartbeat (the firmware never drives either wire), so a
  TX/RX-swapped harness names itself; and a module left in MAVLink/MicoLink mode is detected
  from its header bytes (0xFD/0xFE vs 0xEF) and reported as "set the sensor to MSP", not as a
  dead sensor.
- **Wiring** (`wifi_config.h`): old ToF pads reused — sensor TX → D5/GPIO6 (`MTF_RX_PIN`, the
  only wire read), sensor RX → D6/GPIO43 (`MTF_TX_PIN`, never driven), **5 V** supply (unlike
  both old sensors). Pin-collision static_assert now covers `FC_*` + `MTF_*`; retired
  `TOF_*`/`FLOW_*` defines kept only for the probe builds, which remain buildable as the
  debugging trail.
- **Bench rig**: `pio run -e mtf_probe` prints bytes/s → frames/s → live range + cumulative
  sums at 1 Hz, keypress zeroes the sums — the same slide-calibration ergonomics `flow_probe`
  had. `bench.py flow-cal` over the air is unchanged.
- VL53L1X `lib_deps` dropped from all four main envs. Docs updated: bridge README (wiring +
  bring-up rewritten), `docs/SIM2REAL.md` new section "Downward sensing consolidated",
  CLAUDE.md seam paragraph.

## Result

- All 16 PlatformIO envs build (`xiao_bridge`, `xiao_bridge_espnow`, both `_ota` variants,
  `mtf_probe`, dongle + every retired probe). CRC vector PASS. **Not yet run against the
  physical module** — this node is the integration, not the bring-up; the sensor arrived today
  and gets bench-tested on the spare XIAO next (`mtf_probe`), then wired to the drone and the
  main firmware OTA'd (the drone XIAO is OTA-only).
- **What carries over**: both reply formats, the cumulative-counts contract, the entire obs-8
  deploy path, `flow_scale_frac` DR absorbing a re-measured gain, the trained Desk-Flow policy
  (GREEN at 0.20 m, [restless-oak-1375]) — nothing host-side changed.
- **What does NOT carry over — every measured constant**: `rad_per_count` is per-optics (slide
  calibration mandatory before any flow flight; the pilot still refuses without it); the ToF
  zero offset (+23.9 mm was the VL53L1X's), noise floor and effective rate are unmeasured on
  this module; the flow DR placeholders remain placeholders.
- **Honesty**: the 6 m ToF reach and the 0.7 m deploy-cap relaxation are SPEC, not measurement
  — the height characterization must be re-run before moving the cap or the 0.40 m flow
  operating point. Sequencing note: OTA-ing this firmware before the rewire kills the working
  VL53L1X path (rollback = reflash `aae391b`'s build); flash and rewire in the same session.

## Lineage

Follows [quiet-bramble-1724] (conviction final → replacement part) and consumes the wiring
lessons of [bold-sand-0430] (deck wiring proven good; the swap scan exists because harness
mix-ups happened twice). The policy this hardware ultimately serves is [restless-oak-1375]'s
Desk-Flow.

## Repo

- repo: git@github.com:theo-kirby/neural-whoop.git
- branch: main
- commit: 818e0f5f8363d38a0ff894f9c0039b5354258b00

## State Impact

- target: modest-raven-7153 — downward sensing rebuilt around the MicoAir MTF-02P (one UART, MSP v2 @50 Hz, RX-only): firmware + bench probe + docs shipped and building, cmd 192/193 replies byte-identical so the host stack is untouched; bench bring-up, rewire, OTA and the slide re-calibration (rad_per_count is per-optics) are the open steps before Desk-Flow can fly
- target: lucky-lodge-5696 — the sensor ceiling premise changes: the MTF-02P ToF specs to 6 m vs the VL53L1X's ~1.3 m trusted band behind the 0.7 m deploy cap; spec is not measurement — re-run the height characterization before moving the cap
- target: rapid-hill-4130 — the ToF zero-offset calibration still does not exist and now targets a different sensor: the VL53L1X's +23.9 mm / 2.4 mm / ~25 Hz numbers are void for the MTF-02P
