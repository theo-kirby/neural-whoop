# xiao_bridge — WiFi↔UART MSP proxy (sim2real branch B)

Turns a Seeed XIAO ESP32-S3 wired to the Air65's free UART into the drone's radio:
the host sends raw MSP frames over UDP, the bridge forwards them verbatim to the flight
controller and ships the FC's replies back. Protocol-transparent by design — the whole
`scripts/bench.py` toolkit works through it unchanged via `--udp`. The deliberate
exceptions: the bridge owns the **downward sensing** and answers two MSP ids itself —
**192** (`MSP_BRIDGE_TOF`, range) and **193** (`MSP_BRIDGE_FLOW`, optical-flow counts).
Since **2026-08-20 both are served by ONE module**: a MicoAir **MTF-02P** (ToF rangefinder +
optical flow, fused, over a single UART), which replaced the VL53L1X + PMW3901 pair — the
reply formats are unchanged, so every host tool is oblivious to the swap. Both ids are
consumed, never forwarded to the FC. The module may be absent; the bridge boots and proxies
regardless and the replies carry `sensor_ok=0`.

## Wiring (Matrix 1S 5IN1 II)

**Every net below is a `#define` in `include/wifi_config.h`** (`FC_*`, `TOF_*`, `FLOW_*`) — the
tables show the reference layout, but the config header is the truth for any given build, and
`main.cpp` **static_asserts that no two nets share a GPIO**, so a config typo fails the build
instead of surfacing as a mystery dead sensor after assembly (the 2026-08-08 config had FC_RX
on the flow-CS default and nothing complained).

| XIAO | FC |
|---|---|
| D0 (GPIO1) | UART1 RX pad (R1) |
| D1 (GPIO2) | UART1 TX pad (T1) |
| GND | GND |
| 5V | 5V pad (FC BEC) |

## Downward sensing — MicoAir MTF-02P (ToF + optical flow, one UART)

Replaced the VL53L1X (I²C) + PMW3901 (SPI) pair on 2026-08-20 — the PMW3901 breakout was
convicted dead on 2026-08-19 (init failed identically under three independent
implementations), and the MTF-02P's ToF specs out to **6 m** where the VL53L1X trusted
~1.3 m, which is exactly the ceiling that forced the 0.7 m deploy-height cap. One module, one
harness, two sensors gone.

| XIAO | MTF-02P | note |
|---|---|---|
| D5 (GPIO6) | TX | the data wire — `MTF_RX_PIN`; **the firmware only ever listens** |
| D6 (GPIO43) | RX | `MTF_TX_PIN`, never driven; wired so the swap scan can listen on it |
| 5V | 5V | **5 V, not 3V3** (unlike both old sensors); logic is 3.3 V LVTTL |
| GND | GND | |

The module is a UART **talker**, not a polled peripheral: in **MSP mode** it free-runs at
**115200 8N1, 50 Hz**, pushing MSP v2 sensor frames (`MSP2_SENSOR_RANGEFINDER` 0x1F01,
`MSP2_SENSOR_OPTIC_FLOW` 0x1F02 — the INAV convention; the bridge impersonates an INAV FC).
`include/mtf02.h` parses the stream non-blocking; there is no init handshake, so **presence =
frames arriving**, re-checked continuously. The old blocking-I²C worries are gone with the
bus: draining a UART FIFO cannot stall `loop()`.

**Set the sensor to MSP mode once, on the bench** (MicoAssistant over a USB-TTL adapter, or
the solder jumper on the back — the jumper wins over software config). A module left in
MAVLink or MicoLink mode is detected and named by the heartbeat/probe (the header bytes
differ), so a wrong mode reads as a printed instruction, not a dead sensor.

Mount **facing down**, lens clean and out of prop wash. Physical constraints that are not
firmware settings: flow needs **>8 cm of height** (working distance), **>60 lux**, and a
*textured* surface — a bare white desk collapses the flow quality byte while frames keep
arriving. ToF dead zone is 2 cm.

Desk bring-up (bench XIAO — **never** flash a probe onto the assembled drone board):

```bash
pio run -e mtf_probe -t upload && pio device monitor   # bytes/s -> frames/s -> live range+counts
```

The probe answers, in order: anything on the wire? (0 B/s = power/harness — it alternates its
listen pin every 5 s, so a TX/RX-swapped harness names itself); right protocol mode? (MAVLink/
MicoLink signatures are called out); and do range + flow behave (wave a hand, slide a page).
The main firmware's 5 s heartbeat carries the same diagnostics for the assembled, OTA-only
drone board, and `bench.py checkup/tof/flow` read the same ids as ever.

The probe is also the **calibration rig**, and running the calibration is not optional before
the sensor closes a control loop. Counts are not velocity: `v = (counts/dt) · rad_per_count ·
height`, and `rad_per_count` is deliberately absent from the MSP sensor protocol (INAV
calibrates it as `opflow_scale`; we measure it). Rest the sensor at a known height over a
printed page, zero the sums (send any character), slide exactly 100 mm, read the total:
`rad_per_count = distance / (height · counts)`. Repeat at a second height — the two must
agree, or the standoff is wrong. That measured number is the pilot's **required**
`--rad-per-count` flag and what `configs/desk-flow.yaml`'s `flow_scale_frac` DR absorbs. The
PMW3901's old number (if one was ever measured) does **not** carry over — different optics,
different counts.

**No-USB alternative:** the same slide test runs over the air against the main firmware's
cumulative counters — `python3 scripts/bench.py --udp <ip>|--port <dongle> flow-cal
--height 0.20` — so the assembled board never needs a probe flash. Same two-height rule.

`MSP_BRIDGE_FLOW` (193) reports **cumulative** count sums plus the bridge's own millisecond
stamp of the newest sample; the host differences two replies to get `(dx, dy, dt)`. That is
deliberate — a "counts since you last asked" reply makes every read destructive, so one dropped
packet silently eats real motion and a second client (a `bench.py flow` window left open beside
a flight) steals it. Differencing is idempotent and safe to do from two places at once.

Any free GPIO works as UART TX/RX via the ESP32-S3 matrix, so match `FC_TX_PIN`/`FC_RX_PIN` in
`wifi_config.h` to wherever the FC's R1/T1 wires actually land. Pin history on this build: the
original D7/GPIO44 was written off on 2026-07-05 as a dead input (idled at a healthy 3.3 V, never
received a byte on either the UART1 matrix or native UART0), the wiring moved to the SPI-side
D9/D10 on 2026-07-10, and to **D0/D1 on 2026-07-30**. That last move was a red herring: D9 and
D10 both measured healthy afterwards (`uart_scan`, `pullup=8/8 open`) and the real fault was a
**solder bridge shorting the T1 line to ground** — it followed the wire from pin to pin, dragging
whichever GPIO it touched low. D7's original verdict belongs to a since-replaced XIAO. Suspect the
joints before the silicon; `uart_scan` distinguishes them.

Mount with the antenna clear of the frame; the plain (camera-less) XIAO is enough for the
bridge (~3 g + wiring).

## Flash

```bash
cp include/wifi_config.h.example include/wifi_config.h   # fill in SSID/pass + the pin block
pio run -t upload && pio device monitor                   # prints the bridge IP on boot
```

## OTA reflash — USB is only needed once (2026-08-13)

After final assembly the drone XIAO's USB port is a mechanical liability to reach, so the USB
flash that installs the 2026-08-13+ firmware is designed to be the **last one**. Every later
firmware change goes over the air (ArduinoOTA, port 3232, hostname `whoop-bridge.local`):

- **WiFi/UDP build:** OTA runs full-time beside UDP. `pio run -e xiao_bridge_ota -t upload`
  whenever the bridge is powered.
- **ESP-NOW build, command path:** `python3 scripts/bench.py --port <dongle> ota` — the bridge
  acks, leaves the flight link, joins the `wifi_config.h` network and serves OTA for ~3 min
  (LED: fast ~10 Hz strobe). Then `pio run -e xiao_bridge_espnow_ota -t upload`. A finished
  upload reboots into the new firmware; a timeout restarts back into normal ESP-NOW service.
- **ESP-NOW build, rescue path:** if *no* link packet has **ever** arrived by ~2 min after boot
  (wrong dongle MAC / wrong channel / dead dongle — the command path can't reach it either),
  the bridge opens the same OTA window on its own, then restarts and listens again, forever. A
  battery plug-in is therefore always enough to make the board flashable, even with a broken
  `espnow_config.h`. Normal flights never see this: the host polls from session start, and the
  first packet disarms the fallback for good. Typing `O` into the USB monitor also opens the
  window, for bench use.

Both boot logs print the board's own **STA MAC**, so a replacement XIAO can be identified for
`espnow_config.h` during its one USB flash — no separate `mac_probe` flash needed.

**Corollary: never flash a probe firmware (`mtf_probe`/`i2c_scan`/`uart_scan`/`flow_probe`/
`uart_probe`) onto the assembled drone board** — they have no radio and no OTA, so the only way back out is
the USB port. Diagnose the assembled board over the air instead (`bench.py checkup/tof/flow`),
edit pins in `wifi_config.h`, and OTA the fix.

## Betaflight config (once, over USB)

- Ports tab: set the UART1 row to **Configuration/MSP**, 115200.
- CLI: `set msp_override_channels_mask = 15` (roll/pitch/yaw/throttle), save; add the
  **MSP RC Override** mode on a Pocket switch (Modes tab). Decide `msp_override_failsafe`
  deliberately (see docs/SIM2REAL.md — default off = RC-loss failsafes even with live MSP).

## Smoke test (props off)

`--udp` is a global flag (before the subcommand). The UDP path is pure stdlib — plain
`python3` works on machines that can't install the CUDA venv (e.g. a macOS laptop):

```bash
python3 scripts/bench.py --udp <bridge-ip> info          # FC identity over WiFi
python3 scripts/bench.py --udp <bridge-ip> latency       # the REAL link budget number
python3 scripts/bench.py --udp <bridge-ip> rc-test --ack-props-off
```

First-flight bench (2026-07-05, Air65 II + XIAO on the same LAN): median RTT 2.4 ms,
p99 24 ms over 500 requests — far inside Betaflight's 300 ms MSP-RC freshness window.

## Debugging the link

When the heartbeat reports `mtf ABSENT`, read its counters before reaching for an iron: they
already discriminate the failure classes (0 bytes = power/harness, and the swap scan has
tried both data pins by then; bytes-but-no-frames = wrong protocol mode or wrong baud, with
MAVLink/MicoLink named outright). On the bench, `pio run -e mtf_probe -t upload` gives the
same view at 1 Hz. The probes below predate the MTF-02P and are kept for their trail — and
`i2c_scan`/`wire_test` remain genuinely useful continuity tools for any harness.

When `initTof()` reported `no VL53L1X on I2C` (retired VL53L1X-era note), the bus probe ran —
no WiFi, no FC, no battery, USB power alone:

```bash
pio run -e i2c_scan -t upload && pio device monitor
```

It prints two passes. First the **idle levels** of every candidate pin with the internal
pull-ups off: the CJMCU-531 carries its own ~10k pull-ups to VIN, so a pin wired to a
*powered* sensor reads HIGH with nothing driving it. If SDA and SCL both read LOW, **3V3→VIN
is the fault** and SDA/SCL order is irrelevant. Then an **address sweep over every ordered
(SDA, SCL) pin pair** (0x08–0x77; a VL53L1X answers at 0x29), so a hit names the pins the
sensor is actually on — feed those to `Wire.begin()`. Nothing ACKing on any pair means
unpowered, unconnected, or dead, independent of pin choice. D9/D10 are excluded (the FC UART
pair — clocking them would drive an unpowered FC). Re-flash `xiao_bridge` when done.

When `tof` works but `info` times out — bridge and WiFi proven, FC not answering — run the UART
probe. This one **needs the flight battery in** (props off), because the FC has to be powered
both to answer and to drive its TX pad:

```bash
pio run -e uart_scan -t upload && pio device monitor
```

Same two-pass shape as `i2c_scan`. Pass 1 reads idle levels: a powered FC holds its TX line
HIGH, so a driven pin is where the FC's T1 landed. **No driven pin at all means the FC→XIAO
wire is open or soldered to a pad on a different UART** — no pin permutation fixes that. Pass 2
sends `MSP_API_VERSION` on each plausible (tx, rx) pair and hex-dumps the answer; a reply
starting `$M>` names the wiring for `FC_TX_PIN`/`FC_RX_PIN`. It only drives pins pass 1 found
*undriven*, so it never fights an FC output, and it skips D5/D6 (the ToF bus). A driven pin but
no MSP reply isolates the fault to the XIAO→FC direction (the FC never hears the request).
Re-flash `xiao_bridge` when done.

Four helper firmwares share `wifi_config.h`: `pio run -e blink_test -t upload` (WiFi/UDP
smoke test, no FC needed: `printf on | nc -u -w1 <ip> 14550` toggles the LED) and
`pio run -e uart_probe -t upload` (sends `ping N` out the FC UART once a second and
hex-dumps received bytes to USB). Pair the probe with Betaflight CLI
`serialpassthrough uart1 115200` — note named port ids — to test each wire direction
independently. If `serial` in the CLI shows no `uart1` row with function 1, the Ports-tab
MSP setting never saved; fix in CLI: `serial uart1 1 115200 57600 0 115200` + `save`.

## Safety model

The bridge never fabricates frames: if the WiFi link drops, it simply stops forwarding and
Betaflight's own 300 ms MSP-RC freshness window + `msp_override_failsafe` policy take over.
The Pocket stays the live RC link holding arm/kill — flipping the override mode switch off
returns full manual control instantly. LED: solid = commands flowing, blink = idle.
