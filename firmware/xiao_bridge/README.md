# xiao_bridge — WiFi↔UART MSP proxy (sim2real branch B)

Turns a Seeed XIAO ESP32-S3 wired to the Air65 II's free UART into the drone's radio:
the host sends raw MSP frames over UDP, the bridge forwards them verbatim to the flight
controller and ships the FC's replies back. Protocol-transparent by design — the whole
`scripts/bench.py` toolkit works through it unchanged via `--udp`.

## Wiring (Matrix 1S 5IN1 II)

| XIAO | FC |
|---|---|
| D6 / TX (GPIO43) | UART1 RX pad |
| D7 / RX (GPIO44) | UART1 TX pad |
| GND | GND |
| 5V | 5V pad (FC BEC) |

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

```bash
uv run python scripts/bench.py info --udp <bridge-ip>          # FC identity over WiFi
uv run python scripts/bench.py latency --udp <bridge-ip>       # the REAL link budget number
uv run python scripts/bench.py rc-test --udp <bridge-ip> --ack-props-off
```

## Safety model

The bridge never fabricates frames: if the WiFi link drops, it simply stops forwarding and
Betaflight's own 300 ms MSP-RC freshness window + `msp_override_failsafe` policy take over.
The Pocket stays the live RC link holding arm/kill — flipping the override mode switch off
returns full manual control instantly. LED: solid = commands flowing, blink = idle.
