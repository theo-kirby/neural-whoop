---
node_id: 3917c0a7-3fe0-5e33-8f56-ecc409942cc4
slug: young-fire-2086
title: 'Method: xiao_bridge firmware — transparent UDP↔UART MSP proxy + MspUdpClient (bench.py --udp)'
created_at: '2026-07-04T09:45:33.258915+00:00'
parents:
- frosty-pond-8115
- long-queen-3431
summary: 'Built branch B''s radio (commit c6c5253): firmware/xiao_bridge/ — a PlatformIO Arduino app for the XIAO ESP32-S3 that forwards raw MSP frames host↔FC verbatim over WiFi UDP (DroneBridge pattern; WiFi power-save off; LED = link state). Safety by construction: the bridge never fabricates frames — on link loss it just stops forwarding and Betaflight''s 300 ms MSP freshness window + msp_override_failsafe policy own the outcome; the Pocket keeps arm/kill. Host side: bench/msp.py refactored to a transport-agnostic _MspEndpoint (framing/retry/typed getters shared), MspClient (serial) + new MspUdpClient (stdlib UDP); scripts/bench.py gains --udp HOST[:PORT], so the ENTIRE Stage-0 instrument works over the bridge unchanged — including ''latency --udp'', which will measure the real WiFi round trip the hover_air65_bridge DR band (0–60 ms) currently estimates. Tested via an in-process fake-bridge UDP round trip (suite 127→128 green). Firmware compiles on paper but is UNFLASHED — hardware validation is the user''s next bench session (wiring: XIAO D6/D7 ↔ FC UART1 pads, 5V, GND).'
origin:
  backend: flywheel
  node_id: 3917c0a7-3fe0-5e33-8f56-ecc409942cc4
  slug: young-fire-2086
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 20e1aab1-110e-5d0c-946d-bba3f8351baf
  slug: autumn-math-2469
  revision: 0
  pushed_at: '2026-08-09T21:27:05+00:00'
  content_sha256: cd5a65b3696f5fd4b2a14f185beb9da6d867b6aac8016836beb230dad536d6dd
---
# Method: xiao_bridge firmware + UDP transport

**Why.** Branch B (ESP32 bridge) is the first-flight uplink now that the ELRS TX module is backordered. This is its software: the XIAO becomes the drone's radio, and the existing bench toolkit becomes wireless. Commit `c6c5253` (theo-kirby/neural-whoop).

**Design choice — transparent proxy.** The bridge forwards raw MSP frames verbatim in both directions (the DroneBridge pattern) instead of defining a custom packet format. Consequences: (1) the host reuses the exact MSP codec from the bench toolkit — one protocol, two transports; (2) every bench subcommand (info/monitor/latency/rc-test/motor-test) works over WiFi via `--udp`; (3) the bridge holds no state to get wrong.

**Firmware** (`firmware/xiao_bridge/`, PlatformIO, seeed_xiao_esp32s3): STA WiFi with `WiFi.setSleep(false)` (power save = 100 ms+ latency spikes), UDP :14550 → UART1-on-GPIO43/44 @115200; FC bytes stream back to the last commander. '$' header sanity check; 512 B buffers; LED solid = commands fresh (<250 ms), blink = idle; auto-reconnect. Wiring + Betaflight port/override config + props-off smoke sequence in the README.

**Safety model.** The bridge NEVER fabricates a frame: link loss ⇒ nothing forwarded ⇒ Betaflight's own 300 ms MSP-RC freshness window + `msp_override_failsafe` policy decide (documented trap: default off = RC-loss failsafe even with live MSP). Arm/kill stays on the Pocket's channels, outside the override mask — flipping the MSPRCOVERRIDE mode switch returns manual control instantly.

**Host side.** `bench/msp.py`: `_MspEndpoint` base owns framing/matching/retries/typed getters; `MspClient` (pyserial) and `MspUdpClient` (pure stdlib socket) are ~15-line transport shims. `scripts/bench.py --udp HOST[:PORT]`. The `latency --udp` subcommand is the payoff instrument: it will measure the true host→WiFi→XIAO→UART→FC round trip — the number the `hover_air65_bridge` DR band (0–60 ms, node `icy-flower-1085`) currently estimates from web benchmarks.

**Verification.** UDP round-trip test against an in-process fake bridge (a UDP socket answering MSP — faithful because the real bridge is transparent); suite 127→128 green; ruff clean; CLI imports. **Honesty: the firmware itself is unflashed and unvalidated on hardware** — pin mapping (GPIO43/44 = D6/D7) and UART wiring are from Seeed docs; first flash + loopback is the user's next bench session.

**Next.** (1) User: flash + wire + `bench.py rc-test --udp` — that empirical result becomes the child node; (2) measure real link latency → re-pin the DR band; (3) ESP-NOW variant (second XIAO as host dongle) if WiFi jitter disappoints; (4) TFLM TinyPolicy benchmark firmware (branch D groundwork).

**Lineage.** Extends the Stage-0 MSP bench toolkit (`frosty-pond-8115` — same codec, new transport) within the branch map's branch B (`long-queen-3431`). The `hover_air65_bridge` policy (`icy-flower-1085`) is what this link will eventually carry.