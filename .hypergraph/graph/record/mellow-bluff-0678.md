---
node_id: 6dc71195-e086-526b-9bbd-bb5ee7a8e0af
slug: mellow-bluff-0678
title: 'Dongle-candidate triage RED: MH-ET MiniKit is a 26 MHz-crystal clone (serial decodes at 74880, radio reset-loops) — dongle stays the XIAO; wifi_scan RF-health probe added'
created_at: '2026-08-22T11:16:32+00:00'
parents:
- curious-fox-5831
summary: ''
---
## What

Dongle-candidate triage, negative result: the MH-ET LIVE ESP32 MiniKit on hand is a **26 MHz
crystal clone** and cannot serve as the ESP-NOW dongle with the prebuilt Arduino toolchain.
The dongle remains the XIAO ESP32-S3. Deliverables kept from the attempt: portable
`espnow_dongle_minikit`/`mac_probe_minikit` envs (any genuine 40 MHz classic-ESP32 devkit
would work — the dongle source is board-agnostic, confirmed) and a new `wifi_scan` RF-health
probe that turns this failure class into a two-minute check. Commit `a18c7cb`.

## Why

The Operator wanted to repurpose a spare board as the desk dongle before the drone XIAO takes
its one final USB flash (MTF-02P work, [curious-fox-5831]). Any ESP32-family board can be the
dongle in principle — ESP-NOW interoperates across the family and the dongle firmware uses
only `Serial`, `LED_BUILTIN` and esp_now — so the question was purely whether this specific
unit is healthy.

## Method

1. Flashed `mac_probe` built for `mhetesp32minikit` (classic WROOM-32, CP2104 bridge) — upload
   succeeded, so the chip type is genuinely ESP32-classic (esptool verifies chip magic).
2. Serial at the configured 115200 returned only repeating garbage. Baud sweep with a hard
   RTS reset: output decodes **100% clean at 74880 baud** — MAC 68:25:DD:45:8C:14 printed
   stably every 5 s. 74880 = 115200 × 26/40, the classic signature of a 26 MHz crystal driven
   by firmware assuming 40 MHz. Notably the installed Arduino core has
   `CONFIG_ESP32_XTAL_FREQ_AUTO=y`, and the detection still did not save it.
3. The mis-clock hits the radio PLL too, so the decisive test is RF: new `wifi_scan.cpp`
   probe (WiFi scan + `rtc_clk_xtal_freq_get()` report). Result: the board never returned a
   single readable scan line — powering the radio threw it into a **continuous reset loop**
   (identical crash fragment repeating several times a second at any read baud), where the
   scan-free mac_probe had idled stably.

## Result

- **RED / refuted for this unit**: wrong-crystal serial (proven by exact-ratio decode) plus a
  radio that cannot even initialize. Off-frequency RF could never hold ESP-NOW channel 11
  against the XIAO even if it ran. Unfixable at our layer: the crystal frequency is baked into
  the prebuilt Arduino/IDF libs; retargeting means a custom IDF build, which this project will
  not maintain for a clone board.
- Standing value: the `wifi_scan` probe + the two minikit envs make the next candidate board a
  two-minute accept/reject (flash `wifi_scan_minikit` with the right `board =`; APs found =
  radio usable; verdict comment left in `platformio.ini` where the next person will look).
- The pre-solder checklist for the drone XIAO is unchanged and still open: final
  `xiao_bridge_espnow` flash, MAC match against `espnow_config.h`, air-path `tof`/`flow`
  through the (XIAO) dongle, one proven OTA cycle — then solder.

## Lineage

Part of the pre-solder hardening thread that follows [curious-fox-5831] (MTF-02P integration:
"the drone XIAO's next USB flash is its last").

## Repo

- repo: git@github.com:theo-kirby/neural-whoop.git
- branch: main
- commit: a18c7cb3c63a7bdd2ebd7605f4433f6408b41d76

## State Impact

- target: modest-raven-7153 — the ESP-NOW dongle remains the XIAO ESP32-S3: the candidate MiniKit refuted as a 26 MHz clone (off-frequency RF, reset loop on radio-up); board-agnostic dongle envs + a wifi_scan RF-health probe now make any future candidate a two-minute accept/reject
