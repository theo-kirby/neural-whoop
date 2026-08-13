# ESP-NOW link

Status: **implemented, awaiting hardware bring-up.** Firmware, host wiring and tests are in
(2026-07-30); §7 is the operator checklist that decides GREEN/RED. The WiFi/UDP bridge remains the
**default build and the shipping transport** until the acceptance gate in §0 passes.

## 0. Why, and what "done" means

The offboard link is the top blocker. Measured on the desk, motors off, 500 requests each
(`scripts/bench.py --udp <ip> latency`):

| path | median | p90 | p99 | max |
|---|---|---|---|---|
| host→bridge→FC (full trip) | 25.71 ms | 62.21 | 197.36 | 650.56 |
| **host→bridge only (pure air)** | **11.05 ms** | **33.24** | **124.32** | **523.48** |

The FC path adds only ~14 ms of median (ordinary UART + Betaflight MSP scheduling). The air owns
the tail. A 45 Hz control loop budgets **22 ms**; the air's p90 alone is 33 ms, and a local-LAN UDP
round trip should be 2–5 ms, not 11.

Both endpoints are already exonerated by measurement (Flywheel `winter-sun-6292`):
`bridge_loop_max_ms` was 1–13 ms across 8 flights, and the host control loop held 23–25 ms `dt`
through every stall tick. The packets simply aren't arriving. Three earlier hypotheses (I²C
timeout, WiFi modem sleep, `fc.readBytes`) were each refuted by measurement.

**Acceptance criteria — decide GREEN/RED on these numbers, not on vibes:**

| gate | target | current |
|---|---|---|
| air RTT p50 | < 5 ms | 11.05 |
| air RTT p99 | < 20 ms | 124.32 |
| in-flight `obs_age_ms` p99 | < 40 ms | 122–232 |
| ticks over 100 ms | < 0.5% | 2.7–14.9% |

`bench.py latency` prints the first two and evaluates the gate itself ("Air-path gate … PASS/FAIL")
so the verdict isn't eyeballed off a table.

If ESP-NOW lands between "clearly better" and "not enough", say so and keep the WiFi build. See
§9 for the honest failure mode: ESP-NOW removes *AP overhead*, not 2.4 GHz *congestion*.

## 1. Topology

```
was:      Mac ──WiFi/UDP──► mesh AP ──WiFi──► XIAO(drone) ──UART──► FC
                 └─ 2 air hops, association, DHCP, beacons/DTIM, mesh roaming, macOS scans

now:      Mac ──USB CDC──► XIAO#2 (dongle) ──ESP-NOW──► XIAO(drone) ──UART──► FC
                 └─ wired            └─ 1 hop, peer-to-peer, no AP, no IP stack
```

Nothing changes on the drone: same XIAO, same mount, same weight, same ToF wiring. The dongle
sits on the desk on a USB cable.

## 2. Hardware

- **1× spare XIAO ESP32-S3** (in hand) — the dongle. No sensors needed.
- **1× USB-C cable.**

## 3. Wire protocol

- **One MSP frame per ESP-NOW packet, host → drone.** MSP v1 frames are self-delimiting
  (`$M<`/`$M>`, length, checksum), so the dongle re-frames the USB byte stream rather than
  forwarding arbitrary chunks. This is what makes the size guard below natural.
- **The drone → host direction is a byte STREAM**, exactly as it was over UDP: the bridge ships
  whatever the FC UART has waiting, split at the 250 B payload cap. Chunk boundaries are
  meaningless to the host's incremental parser, so nothing is lost — and no frame is ever
  truncated, because on that direction the bridge isn't handling frames at all.
- **250-byte payload cap** (`ESP_NOW_MAX_DATA_LEN`). MSP v1's theoretical max frame is 261 bytes
  (6 + 255), so the cap is real but our command set is nowhere near it: attitude 6 B, raw IMU
  18 B, motor telemetry 53 B, mode ranges ~86 B, `MSP_SET_RAW_RC` 22 B. **The dongle guards,
  drops and COUNTS oversize frames rather than fragmenting or truncating** (`n_oversize`, on the
  debug heartbeat). A silent truncation would fail checksum host-side and read as link noise.
  Fragmentation is a follow-up only if a real command ever needs it.
- **Peering:** fixed peer MACs compiled in via `include/espnow_config.h` (gitignored, with a
  committed `.example` alongside — same pattern as `wifi_config.h`). Broadcast pairing is
  deferred; two boards on a bench do not need discovery. Fixed peers are also immune to a stray
  packet re-pointing the telemetry stream.
- **Channel:** fixed on both ends via `esp_wifi_set_channel()`, no AP association. This and the
  MACs are the *only* things that must match — get either wrong and the link is silently dead.
- **Fire-and-forget, no application-level retry.** ESP-NOW already does link-layer ACK + retry.
  Above that, stale data is worse than missing data — the existing design rule ("the bridge never
  fabricates an FC frame") holds, MSP's own request/retry covers losses, and Betaflight's 300 ms
  MSP-RC failsafe remains the safety net. Send-callback failures are counted, never blocked on.

## 4. Firmware A — the dongle

`firmware/xiao_bridge/src/espnow_dongle.cpp`, built by two envs:

| env | what |
|---|---|
| `espnow_dongle` | the real thing |
| `espnow_loopback` | same source, `-DDONGLE_LOOPBACK`: echoes frames back out USB with the radio bypassed (bring-up step 2) |

Structure mirrors the bridge — a dumb transparent proxy, no state:

```
loop():
  drain USB CDC -> MSP frame parser -> esp_now_send(drone_mac, frame)
  drain RX ring buffer               -> Serial.write(bytes)
```

**The #1 footgun: on the dongle, `Serial` (USB CDC) IS the data path.** Any `Serial.printf`
debug corrupts the MSP stream. Every print is gated behind `-DDONGLE_DEBUG` and routed to a
*separate* UART (`DONGLE_DEBUG_TX_PIN`, default D0/D1) — off by default.

**Second gotcha:** the ESP-NOW receive callback runs in WiFi-task context. It must not block and
must not call `Serial.write`. It only `memcpy`s into a lock-free SPSC ring, drained in `loop()`;
a packet that doesn't fit is dropped whole and counted (`n_ring_drop`), never written partially —
a partial write would splice two MSP frames together and desync the host parser.

`[env:mac_probe]` + `src/mac_probe.cpp` print `WiFi.macAddress()` in exactly the form
`espnow_config.h` wants. Run once per board.

## 5. Firmware B — drone side (transport swap)

`main.cpp` gained a four-call transport seam — `linkBegin` / `linkReceive` / `linkReply` +
`linkPublish` / `linkMaintain` (+ `linkStatus` for the heartbeat) — with the WiFi/UDP and ESP-NOW
implementations side by side behind `#ifdef NW_LINK_ESPNOW`. **Everything below that seam is
byte-for-byte the same code in both builds:** ToF interception (`MSP_BRIDGE_TOF`), the `loop_max`
and per-section instrumentation, the LED, the FC UART path.

Two envs, WiFi first so rollback is a reflash with no code change:

| env | transport |
|---|---|
| `xiao_bridge` | WiFi + UDP (**default**) |
| `xiao_bridge_espnow` | ESP-NOW (`-DNW_LINK_ESPNOW`) |

Keeping the ToF interception matters beyond height: it is what lets `bench.py latency` split the
air path from the FC path, which is how §0's gate is measured at all.

The `linkReply` / `linkPublish` split preserves a subtlety of the UDP build: a host that only asks
for `MSP_BRIDGE_TOF` gets answered but is **not** promoted to the telemetry peer, so a ToF-only
client can't steal the FC stream.

## 6. Host changes

The transport was already abstracted: `_MspEndpoint` owns framing/matching/retries, with
`MspClient` (pyserial) and `MspUdpClient` subclasses. The dongle presents as a USB serial port
carrying raw MSP frames, so **`MspClient` already works**.

1. **`_MspEndpoint.set_nonblocking()` — the one that mattered.** `pilot/telemetry.py` used to do
   `self.fc._sock.settimeout(0.0)`, which is UDP-only. `MspClient._read()` falls back to
   `self._ser.read(1)` with `timeout=0.02`, so the flight loop would have blocked **up to 20 ms
   per tick** — measured at ~30 ms against a pty — fatal against a 22 ms budget. The method is now
   on the base class (no-op), overridden per transport (UDP: `settimeout(0)`; serial:
   `timeout = 0` **and** return only `in_waiting` bytes — both halves are needed), and
   `Telemetry.__init__` calls it instead of reaching into `_sock`. Pinned by
   `tests/test_msp.py::test_serial_read_blocks_until_set_nonblocking`, which opens a pty as a real
   serial port; without it this regression only shows up as a sluggish flight loop.
2. **`scripts/pilot.py --serial PORT`** (+ `--baud`), alongside `--udp`. One `open_link()` helper
   replaced the three hardcoded `MspUdpClient(...)` sites. An explicit `--serial` beats a
   `$NW_BRIDGE` default rather than colliding with it.
3. **`studio/flight.py`** — `_parse_bridge` / the default `client_factory` accept a serial spec
   (`serial:/dev/cu.usbmodemX` or a bare `/dev/…` path) beside `host[:port]` and `fake`, so the
   Real tab — the path the flights actually use — flies the dongle. `scripts/serve.py --bridge`
   takes the same spec.
4. **`scripts/bench.py`** — the "tof needs `--udp`" guard is gone, and the `latency` air/FC split
   is attempted on **both** transports. Over ESP-NOW the bridge sits behind a serial port, so
   `--port` now carries the split; only a direct USB cable to the FC has no bridge, and that shows
   up as the FC rejecting `MSP_BRIDGE_TOF` — reported as "no bridge in this path" rather than as a
   failure. `checkup` layer 1 follows the same rule.

**Dependency note — a stated invariant genuinely changed.** This puts pyserial in the flight path,
and `neural_whoop.pilot` was documented as pure-stdlib. We accepted it (pyserial is small and pure
Python) rather than hand-rolling a `termios` reader, and **corrected the claim** everywhere it was
made: `CLAUDE.md`, `docs/SIM2REAL.md`, `docs/STUDIO.md`, `pilot/__init__.py`, `pilot/telemetry.py`,
`scripts/pilot.py`. The accurate statement is: the engine imports zero torch/numpy and zero
non-stdlib modules; the *serial transport* it can be handed imports pyserial, lazily, only when
that spec is opened. `pyserial` was added to the `studio` extra (it was already in `bench`).

## 7. Bring-up order — each step independently verifiable

1. `pio run -e mac_probe -t upload` on **both** boards; record the MACs into `espnow_config.h`
   (copy `include/espnow_config.h.example`; it is gitignored). Pick `ESPNOW_CHANNEL`.
2. `pio run -e espnow_loopback -t upload` on the dongle. **Loopback first** — the dongle echoes
   whole frames back out USB, confirming CDC framing before ESP-NOW is in the picture. Don't use
   `bench.py` for this: it matches replies by command id, not direction, so it would "succeed" on
   its own echoed request and then choke decoding an empty payload. Check the framer directly:

   ```bash
   python3 -c "
   import sys, serial; sys.path.insert(0, 'src')
   from neural_whoop.bench.msp import MspParser, encode_msp_v1, MSP_ATTITUDE
   s = serial.Serial('/dev/cu.usbmodemXXX', 115200, timeout=1)
   s.write(b'noise' + encode_msp_v1(MSP_ATTITUDE))   # leading garbage: the resync must eat it
   print(MspParser().feed(s.read(64)))"
   # -> [MspFrame(cmd=108, payload=b'', is_error=False)]   one frame, nothing else
   ```

   Then flash `espnow_dongle`, and the drone with `xiao_bridge_espnow`.
3. `python3 scripts/bench.py --port /dev/cu.usbmodemXXX latency --n 500` → **the gate**. Reports
   both paths and prints PASS/FAIL against §0.
4. `bench.py --port ... info` → FC round trip alive.
5. `bench.py --port ... tof` → ToF interception survived the transport swap.
6. `NW_FLIGHT_FAKE=1 uv run python scripts/serve.py` for the dashboard smoke, then
   `scripts/serve.py --bridge /dev/cu.usbmodemXXX` and a real flight on a charged pack.
7. `flight_report.py`, then compare `obs_age_ms` p99 against the 122–232 ms baseline.

## 7.5 OTA — the drone board's USB flash is a one-time event (2026-08-13)

The new-airframe rebuild buried the drone XIAO's USB port, so the firmware grew an over-the-air
escape hatch (ArduinoOTA; full story in `firmware/xiao_bridge/README.md` "OTA reflash"). The
short version: `bench.py --port <dongle> ota` (bridge-local MSP id **194**, magic payload) makes
the ESP-NOW bridge leave the link and serve OTA as `whoop-bridge.local` for ~3 min → `pio run -e
xiao_bridge_espnow_ota -t upload`. A never-linked bridge (bad MACs/channel) opens the same
window by itself ~2 min after boot, so a battery plug-in always suffices to reflash. Transport
swaps (ESP-NOW ↔ WiFi) are just OTA uploads of the other build. The flow `rad_per_count`
calibration also no longer needs the `flow_probe` flash: `bench.py flow-cal --height <m>` runs
the slide test over the air. **Never flash a radio-less probe firmware onto the assembled drone
board** — that is the one move that re-requires USB.

## 8. Rollback

The WiFi build is untouched and stays default. If ESP-NOW disappoints, OTA the WiFi build back
(`bench.py ota` → `pio run -e xiao_bridge_ota -t upload`; only reach for USB `pio run -e
xiao_bridge -t upload` on a bench board) and nothing is lost — the host keeps `--udp`. Keep both
paths until a full flight session passes.

## 9. Risks, honestly

- **ESP-NOW removes AP overhead, not RF congestion.** If the 124 ms tail is neighbours saturating
  2.4 GHz rather than mesh/association behaviour, ESP-NOW improves things but perhaps not 6×.
  Step 3 answers this before any flying. This is the main way the plan underdelivers.
- **250-byte cap** — guarded and counted, not silently truncated (§3).
- **USB CDC debug conflict** on the dongle (§4).
- **pyserial in the flight path** (§6) — accepted, docs corrected.
- **Loses WiFi access to the bridge** — no `bench.py --udp`, no mDNS, while in ESP-NOW mode. The
  build flag keeps both available.
- **Untested premise:** whether the link explains the flight failures at all. 5 of 8 flights ended
  inverted with an overshoot to 1.32–1.37 m against a 1.0 m target. That is *plausibly*
  downstream of a loop eating 200 ms holes, but it is not demonstrated, and fixing the link may
  expose a separate control problem.

## 10. Files

| file | role |
|---|---|
| `firmware/xiao_bridge/src/espnow_dongle.cpp` | desk dongle (USB CDC ↔ ESP-NOW), + loopback mode |
| `firmware/xiao_bridge/src/mac_probe.cpp` | prints a board's STA MAC in config form |
| `firmware/xiao_bridge/src/main.cpp` | drone bridge, transport seam behind `NW_LINK_ESPNOW` |
| `firmware/xiao_bridge/include/espnow_config.h.example` | peer MACs + channel (real file gitignored) |
| `src/neural_whoop/bench/msp.py` | `set_nonblocking()` per transport |
| `src/neural_whoop/pilot/telemetry.py` | calls the seam instead of `_sock` |
| `src/neural_whoop/studio/flight.py` | serial bridge spec → `MspClient` |
| `scripts/pilot.py` / `scripts/bench.py` / `scripts/serve.py` | `--serial` / relaxed guards / `--bridge` spec |
| `tests/test_msp.py` | non-blocking-read contract, both transports |
