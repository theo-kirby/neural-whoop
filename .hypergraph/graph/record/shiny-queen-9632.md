---
node_id: 43b92404-c4f5-5b16-a3d4-17f0c81b89cd
slug: shiny-queen-9632
title: ESP-NOW link built end to end — dongle firmware, transport seam, host wiring, and the blocking-serial-read bug the swap would have hidden. Gate UNMEASURED (needs both boards flashed)
created_at: '2026-07-30T21:30:55.013034+00:00'
parents:
- winter-sun-6292
summary: 'Built the ESP-NOW peer-to-peer link end to end off winter-sun-6292''s localization of the tail to the air hop; it tests the specific hypothesis that the tail is AP/association overhead (beacons/DTIM, DHCP, mesh roaming, macOS scans) rather than 2.4 GHz congestion. New espnow_dongle.cpp (USB CDC <-> ESP-NOW, MSP re-framing, oversize frames dropped-and-counted at the 250 B cap, recv callback memcpy-only into a lock-free SPSC ring); main.cpp gained a four-call transport seam behind -DNW_LINK_ESPNOW with MSP_BRIDGE_TOF interception, loop_max/per-section timers, LED and FC UART identical in both builds; WiFi stays the default env so rollback is one reflash. Host: pilot.py --serial, Studio serial bridge specs, bench.py latency/tof/checkup no longer require --udp. Found and fixed a bug the swap would otherwise have hidden: Telemetry made reads non-blocking via fc._sock.settimeout(0), which is UDP-only, so on serial the flight loop would have blocked ~30 ms per tick (measured against a pty) against a 22 ms budget — i.e. the link fix would have shipped with an equivalent stall at the other end and looked like ''ESP-NOW didn''t help''. Now a per-transport set_nonblocking(), pty-backed test. NO outcome tag: the acceptance gate (air p50 < 5 ms vs 11.05, p99 < 20 ms vs 124.32) is UNMEASURED and needs both boards flashed. Verified only: 274 tests pass (1 pre-existing tensorboard failure), 5 pio envs compile clean, fake-bridge flight + Studio smoke. Also corrected the now-false ''pure-stdlib flight path'' claim in 6 places — pyserial is on the serial transport. Commit 06d080b, docs/ESPNOW.md.'
origin:
  backend: flywheel
  node_id: 43b92404-c4f5-5b16-a3d4-17f0c81b89cd
  slug: shiny-queen-9632
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
---
# ESP-NOW link — implementation (2026-07-30)

## Hypothesis this exists to test

Parent `winter-sun-6292` localized the stalls to the air hop and left a ranked list of untested
WiFi suspects. ESP-NOW tests the cheapest structural one: **that the tail is AP/association
overhead — beacons/DTIM, DHCP, mesh roaming, macOS background scans — rather than the 2.4 GHz
band itself.** Peer-to-peer removes every one of those and keeps the band. If the tail survives,
the cause was congestion and this underdelivers; that is the honest failure mode, and step 3 of
the bring-up answers it before any flying.

This node is the **build**, not the answer. No number has moved yet.

## Setup

```
was:  Mac ──WiFi/UDP──► mesh AP ──WiFi──► XIAO(drone) ──UART──► FC
now:  Mac ──USB CDC──► XIAO#2 (dongle) ──ESP-NOW──► XIAO(drone) ──UART──► FC
```

Nothing changes on the drone: same XIAO, same mount, same weight, same ToF wiring. The dongle is
a spare XIAO ESP32-S3 on a desk USB cable.

### Firmware

- `src/espnow_dongle.cpp` (new): USB CDC ↔ ESP-NOW. Re-frames the host byte stream into whole MSP
  v1 packets rather than forwarding arbitrary chunks, so the 250 B `ESP_NOW_MAX_DATA_LEN` cap has
  something meaningful to guard. Oversize frames are **dropped and counted**, never truncated — a
  truncated frame fails checksum host-side and reads as link noise. Two footguns handled by
  construction: `Serial` IS the data path, so every debug print is behind `-DDONGLE_DEBUG` on a
  separate UART (default off); and the recv callback runs in WiFi-task context, so it only
  memcpy's into a lock-free SPSC ring that `loop()` drains — whole packets only, because a partial
  write would splice two MSP frames and desync the host parser.
- `src/main.cpp`: a four-call transport seam (`linkBegin` / `linkReceive` / `linkReply` +
  `linkPublish` / `linkMaintain`), WiFi-UDP and ESP-NOW side by side behind `#ifdef
  NW_LINK_ESPNOW`. **Everything below the seam is the same code in both builds:** `MSP_BRIDGE_TOF`
  interception, `loop_max` + per-section timers, the LED, the FC UART path. Keeping the ToF
  interception is not optional — it is what lets `bench.py latency` split the air path from the FC
  path, which is how the gate below is measured at all.
- `src/mac_probe.cpp` + `include/espnow_config.h.example`: peer MACs and channel, gitignored real
  file, mirroring the `wifi_config.h` pattern.
- Five envs compile warning-free: `xiao_bridge` (**still the default**), `xiao_bridge_espnow`,
  `espnow_dongle`, `espnow_loopback`, `mac_probe`. Rollback is one reflash.

### Host

The transport was already abstracted (`_MspEndpoint` + `MspClient`/`MspUdpClient`), and the dongle
presents as a USB serial port carrying raw MSP, so no new client was needed. Four changes:
`--serial` on `pilot.py`, serial bridge specs in the Studio (`serial:/dev/…` or a bare `/dev/…`),
relaxed `--udp`-only guards in `bench.py` (`latency` / `tof` / `checkup` — over ESP-NOW the bridge
sits *behind* a serial port, so "serial" no longer implies "no bridge"), and the one that mattered:

## The bug the transport swap would have hidden

`Telemetry.__init__` made its reads non-blocking with `self.fc._sock.settimeout(0.0)` — **a
UDP-only reach into a socket attribute.** On a serial transport it would have done nothing, and
`MspClient._read()` falls back to `self._ser.read(1)` against a 20 ms port timeout. Measured
against a pty: **~30 ms per empty read, on a 22 ms control-tick budget.** The link fix would have
shipped with a new stall of the same magnitude as the one it was replacing, sourced at the other
end, and it would have looked exactly like "ESP-NOW didn't help".

Fixed as a transport method — `_MspEndpoint.set_nonblocking()`, no-op in the base, UDP
`settimeout(0)`, serial `timeout = 0` **and** returning only `in_waiting` bytes (both halves are
needed; either alone still blocks). Pinned by a pty-backed test that fails on the old code.

## Results

Nothing empirical yet — deliberately. What is verified:

| check | result |
|---|---|
| test suite | 274 pass, 1 pre-existing failure (no `tensorboard` on the bench Mac) |
| new tests | non-blocking contract on both transports + the Telemetry dispatch |
| firmware | all 5 pio envs compile, no warnings from our sources |
| smoke | fake-bridge `pilot.py fly` (240 frames, 0 stale ticks) + Studio boots and serves |

**The acceptance gate is unmeasured.** It needs both boards flashed with matching MACs:

| gate | target | current (WiFi) |
|---|---|---|
| air RTT p50 | < 5 ms | 11.05 |
| air RTT p99 | < 20 ms | 124.32 |
| flight `obs_age_ms` p99 | < 40 ms | 122–232 |
| ticks > 100 ms | < 0.5% | 2.7–14.9% |

`bench.py latency` now evaluates the first two itself and prints PASS/FAIL, so the verdict is not
eyeballed off a table.

## Verdict / Honesty

**No outcome tag: nothing has been measured.** This is infrastructure plus one real bug fix.

What this does NOT establish:

- **That ESP-NOW is faster.** Unmeasured. It removes AP overhead, not RF congestion, and if the
  neighbours own the band this changes little.
- **That the link explains the flight failures at all.** 5 of 8 flights ended inverted, overshooting
  to 1.32–1.37 m against a 1.0 m target. Plausibly downstream of a loop eating 200 ms holes, but
  not demonstrated — fixing the link may expose a separate control problem.
- **That the drone-side swap works on hardware.** It compiles and preserves the code below the seam
  by construction, but no packet has crossed the air.

A stated invariant genuinely broke and was **corrected rather than left to rot**: this puts pyserial
on the flight path, and `neural_whoop.pilot` was documented as pure-stdlib in six places. The
accurate statement, now written in all of them: the engine imports zero torch/numpy and zero
non-stdlib modules; the *serial transport* imports pyserial, lazily, only when that spec is opened.

## Lineage

Parent `winter-sun-6292` — localized the tail to the air hop and named ESP-NOW as the durable fix.
This node builds it and sets up the measurement that node asked for.

Commit `06d080b`. Design + bring-up checklist: `docs/ESPNOW.md`.

Next: `mac_probe` on both boards → loopback → `bench.py --port <dongle> latency --n 500` (the gate)
→ `info` / `tof` → a dashboard flight → compare `obs_age_ms` p99 against the 122–232 ms baseline.