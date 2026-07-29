# xiao_bridge — WiFi↔UART MSP proxy (sim2real branch B)

Turns a Seeed XIAO ESP32-S3 wired to the Air65 II's free UART into the drone's radio:
the host sends raw MSP frames over UDP, the bridge forwards them verbatim to the flight
controller and ships the FC's replies back. Protocol-transparent by design — the whole
`scripts/bench.py` toolkit works through it unchanged via `--udp`. One deliberate
exception: the bridge owns a downward **VL53L1X ToF** (below) and answers MSP cmd **192**
(`MSP_BRIDGE_TOF`) itself; that id is consumed, never forwarded to the FC.

## Wiring (Matrix 1S 5IN1 II)

| XIAO | FC |
|---|---|
| D10 / MOSI (GPIO9) | UART1 RX pad (R1) |
| D9 / MISO (GPIO8) | UART1 TX pad (T1) |
| GND | GND |
| 5V | 5V pad (FC BEC) |

## ToF wiring (CJMCU-531 / VL53L1X, optional)

| XIAO | CJMCU-531 |
|---|---|
| D5 (GPIO6) | SDA |
| D6 (GPIO43) | SCL |
| 3V3 | VIN |
| GND | GND |

(The XIAO's stock I²C pins are D4/SDA + D5/SCL; our unit is wired one pin over — D5/SDA +
D6/SCL — and `initTof()` passes those to `Wire.begin(D5, D6)` explicitly. Note D6/GPIO43 is
also U0TXD: the ROM bootloader chirps boot logs on it for a moment at power-up, which the
sensor ignores, but keep it in mind if SCL ever looks noisy at boot.)

Mount the sensor **facing down** (it is the measured-height channel: `tof_m` in the pilot
flight CSV, real z in the flight-report replay). Firmware runs it in short-distance mode at
~40 Hz (ambient-robust to ~1.3 m — the whoop's hover band; switch to `Medium` in `initTof()`
for higher ceilings at a slower rate). Leave XSHUT/GPIO1 unwired. The sensor is fully
optional: with nothing on the I²C the bridge boots and proxies exactly as before, and
`MSP_BRIDGE_TOF` replies carry `sensor_ok=0`.

Desk bring-up after wiring (before mounting anything):

```bash
pio run -e xiao_bridge -t upload
python3 scripts/bench.py --udp <bridge-ip> tof     # wave a hand over it; range should track
```

The natural RX choice would be D7/GPIO44, but on our unit that input is dead (line idles at a
healthy 3.3 V, yet neither UART1-matrix nor native-UART0 reception ever sees a byte — presumed
ESD/heat casualty). Any free GPIO works as UART TX/RX via the ESP32-S3 matrix; the wiring was
moved to the SPI-side pins D9/D10 on 2026-07-10. Match `FC_TX_PIN`/`FC_RX_PIN` in
`wifi_config.h` to wherever the FC's R1/T1 wires actually land.

Mount with the antenna clear of the frame; the plain (camera-less) XIAO is enough for the
bridge (~3 g + wiring).

## Flash

```bash
cp include/wifi_config.h.example include/wifi_config.h   # fill in SSID/pass
pio run -t upload && pio device monitor                   # prints the bridge IP on boot
```

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

When `initTof()` reports `no VL53L1X on I2C`, run the bus probe — no WiFi, no FC, no battery,
USB power alone:

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

Three helper firmwares share `wifi_config.h`: `pio run -e blink_test -t upload` (WiFi/UDP
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
