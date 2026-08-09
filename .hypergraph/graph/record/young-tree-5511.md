---
node_id: ec82a443-8a8d-5092-a436-9479f84107ea
slug: young-tree-5511
title: 'Board-swap bring-up: stale MAC pairing had the drone bridge replying to ITSELF, and a D5/D6 solder bridge read as "powered but silent" — i2c_scan grew the short test that named it'
created_at: '2026-08-08T12:38:38.317339+00:00'
parents:
- icy-base-2242
- black-firefly-9000
summary: 'Bench bring-up after the physical board swap (new XIAO = dongle, ex-dongle = drone bridge, FC UART rewired to D2/D3): two independent faults found and fixed, checkup fully green, first 0.7 m hover_tof flight unblocked. (1) espnow_config.h still held the old pairing, so the drone board — the ex-dongle — was flashed with ESPNOW_DONGLE_MAC equal to its OWN MAC (replying to itself) while the dongle transmitted at the retired board; mac_probe on the new board (68:EE:8F:50:32:00), config repaired, both reflashed → bridge + FC UART (new D2/D3 wiring) PASS. (2) ToF absent on I2C despite idle levels proving power and wires on D5/D6; no ACK at any clock 400k→10k, always Wire err 5 TIMEOUT (never a clean NACK) → new i2c_scan shortTest pass: D5<->D6 BRIDGED at the freshly-soldered XIAO pads. After reflow: 0x29 ACKs at every speed INCLUDING 400 kHz (the July harness maxed at 100 kHz — bus now electrically better than before; initTof() left at 100 kHz). i2c_scan also updated for the UART move (probe must not clock D2/D3 now; D9/D10 rejoin candidates) + clockSweep pass. Standing concern: air-latency gate FAIL on the new board pair — air p50 4.48 ms OK, p99 62.76 ms vs 20 ms gate, tail in the air with ch 11 scanned clean and antennas seated; unexplained, soft blocker at hover ranges. Commit e065931.'
origin:
  backend: flywheel
  node_id: ec82a443-8a8d-5092-a436-9479f84107ea
  slug: young-tree-5511
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: ed73de89-8050-5d02-87f0-3908bf07fae6
  slug: sparkling-tooth-3918
  revision: 0
  pushed_at: '2026-08-09T21:28:18+00:00'
  content_sha256: aa9b85cf278404675e23f15438f4319429a43177f5119eb6284da6d96934480a
---
## Setup

The drone's XIAO and the desk dongle were physically swapped and rewired by Theo: the desk dongle is
now a brand-new XIAO ESP32-S3, the drone bridge is the ex-dongle (MAC D8:3B:DA:44:E4:CC), and the FC
UART moved to D2/D3 (tx=GPIO3 -> FC R1, rx=GPIO4 <- FC T1; wifi_config.h updated, gitignored). Goal:
bring the link + ToF back up and gate toward the first real 0.7 m hover_tof flight
(`white-rice-3299`'s bench handoff, at the corrected height per the 2026-07-31 ToF-ceiling finding).

This is the direct sequel to `icy-base-2242` (the 2026-07-30 rewire bring-up): same probe-tool
philosophy, and — remarkably — the same fault class again, one row of pins over.

## Results

**Fault 1 — stale ESP-NOW MAC pairing (config, not RF).** After the swap, `espnow_config.h` still
named the old pairing, which made the drone board's firmware reply to *its own MAC* (it used to BE
the dongle) while the dongle transmitted at the retired board. No route at all — `checkup` bridge
layer FAIL. `mac_probe` on the new desk board → `68:EE:8F:50:32:00`; config repaired, both boards
reflashed. Bridge PASS + FC-over-UART PASS on the first try — which also validates the new D2/D3
solder work in both directions.

**Fault 2 — VL53L1X silent on a powered, correctly-routed bus.** Boot banner: `no VL53L1X on I2C`.
`i2c_scan` idle levels: D5/D6 both HIGH through the breakout's own pull-ups → power, ground-side
plausible, wires on the right pins. Yet nothing ACKed on any pin pair, and the new clockSweep pass
showed no ACK at 400k/100k/50k/10 kHz in either pin order — always **Wire err 5 (TIMEOUT), never a
clean address-NACK (err 2)**. That distinction is the diagnostic: a healthy empty bus refuses
cleanly; a timeout means the lines interfere *under traffic* while idling high. The one fault with
exactly that signature is SDA and SCL joined — one pull-up holds the joined pair high at idle, and
the master clocks into its own data line under traffic. New `shortTest` pass (drive one line LOW,
read the other): **D5 <-> D6 BRIDGED, both directions** — a solder short at the freshly-soldered
XIAO pads (adjacent pins). After reflow: `0x29 (VL53L1X!)` on SDA=D5/SCL=D6, short test clean, and
ACK at **every clock including 400 kHz** — the July harness couldn't do 400 kHz (that's why
`initTof()` runs 100 kHz, per its comment). The rewired bus is electrically better than the one it
replaced. `initTof()` deliberately left at 100 kHz.

**Final gate:** `bench checkup` — all layers PASS (bridge + ToF present, FC over the new UART, link
budget median 12.8 ms). Clear for the Studio Real tab.

## Verdict / Honesty

GREEN as a bring-up: both faults root-caused to a named physical/config change, each fix verified by
the exact probe that found the fault, and the full ladder passes. The session also hardened the
tooling for the next rewire: `i2c_scan` now tracks the FC-UART move (a bus probe must not clock
D2/D3 anymore; D9/D10 rejoin the candidates) and carries the clockSweep + shortTest passes — the
latter is what converted "nothing ACKed" from a shrug into a named fault. Commit `e065931`.

**Not green:** the air-latency gate re-FAILED on the new board pair — air p50 4.48 ms (gate < 5),
air p99 **62.76 ms vs the 20 ms gate**, tail entirely in the air (the FC path adds nothing).
Measured before the ToF fix; ch 11 scanned clean at the bench today (neighbours on 3/4/6) and
antennas are visually seated, so the tail is *unexplained* — `black-firefly-9000`'s post-CDC-fix
numbers were better on the old pair. Soft blocker at hover ranges (the pilot's stale-frame guards
cover it); remeasure before any latency-sensitive work and before trusting the transport gate as
passed.

## Lineage

- Parent `icy-base-2242` — the 2026-07-30 full-drone rewire bring-up: built i2c_scan/uart_scan/
  checkup, found that session's T1-to-ground solder bridge. Today is its sequel: same tool family,
  extended (clockSweep, shortTest), and again the fault was one solder bridge.
- Parent `black-firefly-9000` — ESP-NOW on hardware + the CDC fix: the latency-gate baseline that
  today's p99 62.76 ms air tail regresses against.
- Unblocks: the `white-rice-3299` bench handoff — first real ToF flight at 0.7 m (in progress on
  the bench as this node is written; results will be a child node).