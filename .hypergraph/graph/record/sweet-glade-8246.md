---
node_id: 91e406bd-0c1e-5ae3-8fff-16e5af9bb35e
slug: sweet-glade-8246
title: 'MTF-02P live on the drone: 49 Hz both frames, 2.26 m valid range past the old ceiling — via OTA transport swap to WiFi, remote diag id 195, and a stale-reply request() fix'
created_at: '2026-08-22T13:18:59+00:00'
parents:
- curious-fox-5831
- mellow-bluff-0678
summary: ''
---
## What

First hardware contact with the MTF-02P **on the assembled drone**, over the air: the sensor
is **healthy** — 49 Hz on both frame types, CRC-clean, and a steady valid **2.264 m** range
reading (the drone staring at the ceiling), which already sits past the VL53L1X's entire
~1.3 m trusted band. Getting to that verdict took three fixes/additions, each recorded in the
work itself: the drone bridge moved to the **WiFi/UDP transport** by OTA rescue (the dongle
XIAO died — ESP-NOW is parked, not abandoned), a new bridge-local diagnostics id **195
`MSP_BRIDGE_MTF_DIAG`** + `bench.py mtf` (the USB heartbeat's triage, remoted), and a real
host bug fixed in `_MspEndpoint.request()`. Commits `7171d42` (diag + fix), `818e0f5`
(integration, [curious-fox-5831]).

## Why

The dongle XIAO fried, stranding the ESP-NOW link; the drone XIAO is soldered in with its USB
buried, so every step had to happen over the air. The sensor initially read as completely
silent (`sensor_ok=0, age=never`), and distinguishing "no power" from "wrong mode" from
"wrong pins" from "host artifact" remotely is exactly what the USB-only heartbeat could not
do — hence id 195. It promptly proved the silence was **not the sensor**.

## Method

1. **Transport swap with no iron:** the ESP-NOW build's boot-rescue fallback (no link packet
   ever → self-opened OTA window ~2 min after battery-in) accepted `xiao_bridge_ota`; 82 s
   upload, `Result: OK`. Betaflight-style A/B partitions make a mid-OTA brownout a retry, not
   a brick — it took several attempts across battery sags before one landed.
2. **Link triage en route:** the board "vanishing" had three superposed causes, now
   separated: a flat first battery (real outages; fresh pack fixed), **ICMP being unreliable
   on this mesh while UDP MSP works** (ping was never a valid liveness probe here — the ARP
   entry answered while ping showed 100% loss), and a 412 ms first-packet warmup on the mesh
   path. Operator observations discriminated board-alive (slow LED blink) from link-dead.
3. **Id 195:** 8×u32 counters (bytes/range-frames/flow-frames/other/crc/mav-like/mico-like/
   last-frame-age) + active/configured RX GPIO; `bench.py mtf` differences two snapshots into
   rates and prints a named verdict (silent-wire / wrong-mode / wrong-baud / swapped-pins /
   healthy). Decode pinned in `tests/test_msp.py`.
4. **The stale-duplicate bug:** first `mtf` runs reported 0 B/s deltas while totals climbed
   between invocations. Root cause in `request()`: a retry (fired by the 412 ms warmup
   exceeding the 0.5 s timeout) leaves its late reply queued in the socket; the next same-cmd
   call returned that duplicate as if fresh — cumulative counters time-traveled. Fix: flush
   pre-send (a reply must postdate its request); the pilot's hot path uses `send()`+drain and
   is untouched. One test fake taught the same physics.

## Result

- `bench.py --udp <ip> mtf`: **1568 B/s, range 49.0 Hz, flow 49.0 Hz, crc_fail 0 → healthy**,
  listening on the configured GPIO6. `bench.py tof`: 2264 mm, status 0, age 13 ms, loop_max
  1 ms. The MTF-02P integration ([curious-fox-5831]) is now hardware-proven on the drone.
- **Protocol finding:** the module **suppresses OPTIC_FLOW frames entirely when it has no
  optical solution** (dark ceiling at 2.3 m → zero flow frames while range streams on) rather
  than emitting zero-quality frames. The pilot's stale-flow grace/fade/abort path already
  models exactly this shape, but any consumer assuming "flow frames always tick" would be
  wrong — the bench probe's 48 Hz was a textured-desk number.
- **Standing costs of the transport swap:** flights now depend on AP reachability (the mesh
  path measured 412 ms warmup and ICMP-dark — a dedicated hotspot at the flying spot remains
  the documented recommendation), and the ESP-NOW obs-age win is parked until a replacement
  dongle board exists ([mellow-bluff-0678] holds the candidate-triage tools).
- **Honesty:** the 2.264 m reading is one point, not a characterization — noise floor, zero
  offset and effective rate at operating heights are still unmeasured ([rapid-hill-4130]),
  and `rad_per_count` remains unmeasured (deliberately deferred by the Operator; blocks only
  flow flights, not `hover_tof`).

## Lineage

Hardware bring-up of [curious-fox-5831]'s integration; uses the OTA escape hatch from
[gilded-wolf-6430]; sibling of [mellow-bluff-0678] (the fried dongle's would-be replacement).

## Repo

- repo: git@github.com:theo-kirby/neural-whoop.git
- branch: main
- commit: 7171d42b2843f89d9c89c8a77cbf94da739d29d5

## State Impact

- target: modest-raven-7153 — MTF-02P hardware-CONFIRMED on the assembled drone over the air (49 Hz range+flow, CRC-clean, 2.264 m valid range); transport is now the WiFi/UDP build (dongle XIAO fried, ESP-NOW parked awaiting a replacement board); new remote sensor-link triage (id 195 / bench.py mtf); request() stale-duplicate bug fixed host-side; flow frames are scene-gated (suppressed with no optical solution) — consumers must not assume they always tick
- target: lucky-lodge-5696 — first direct evidence the sensor-ceiling constraint lifted: a valid 2.264 m reading from the new ToF, past the VL53L1X's whole ~1.3 m trusted band; one point, not a characterization — the height sweep still has to be re-run before the 0.7 m deploy cap moves
