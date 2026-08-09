---
node_id: 24595e77-1647-530b-8a33-c93e38591d70
slug: icy-base-2242
title: 'Full-drone rewire bring-up: ToF needed 400→100 kHz and the "dead UART pin" was a T1-to-ground solder bridge — plus three probe tools (i2c_scan / uart_scan / bench checkup)'
created_at: '2026-07-30T00:22:59.818631+00:00'
parents:
- aged-firefly-8064
- young-fire-2086
- snowy-heart-2157
summary: 'Post-rewire bring-up of the Air65 II + XIAO bridge, with two faults found and fixed and three probe tools built. (1) ToF: Wire error 263 (ESP_ERR_TIMEOUT) at boot survived a full rewire of the sensor''s three wires; the discriminator was that i2c_scan reaches 0x29 at 100 kHz while the bridge failed at 400 kHz on the SAME pins — longer harness capacitance vs rise time through the breakout''s ~10k pull-ups. setClock 400000->100000 (52eacdc) restored it (~2 ms/poll vs 0.6, inside the 25 ms period). (2) FC UART: Betaflight showed uart1=MSP@115200, FC powered, bridge answering its own ToF id, yet D9 read dead LOW. Adding an INPUT_PULLUP sample turned ''LOW'' into ''a 45k pull-up cannot lift it'' = something low-impedance ties the line to ground, whereas an idle MSP TX pad idles HIGH. Decisive evidence: the fault FOLLOWED THE WIRE — D9 dead LOW with T1 on it, then D1 stuck once T1 moved there, with D9 reading open/healthy. Bisection (wire off -> D1 open; wire on XIAO end only, FC end dangling -> unstable/floating, so the wire conducts end-to-end) left exactly one joint: a T1-to-ground solder bridge. Clearing it gave 24 4D 3E 03 01 00 01 30 33 = MSP_API_VERSION API 1.48, which proves BOTH directions and retired the never-tested D0->R1 leg. Pinout of record now D0/D1 (1a8f494). Tooling: i2c_scan (5396454), uart_scan (5497be0/7711126), bench.py checkup (cf513cd), actionable link hints incl. EHOSTDOWN (36484dc). Verdict GREEN. Honesty: three invalid tests each cost a battery window (battery out; probe firmware still flashed; WiFi antenna popped out) and all first read as hardware faults; my own tools gave two wrong leads (Wire.end() leaves pins routed in the GPIO matrix so every pair with the right SDA seemed to ACK; pass 1 called a ROM pull-up ''driven'' and blamed the wrong direction); pass 1 CANNOT confirm a working link because this FC''s TX idles through a weak ~40k pull-up that the 45k pull-down cancels — only ''stuck low even with pull-up'' is conclusive; two of my hypotheses were wrong (board contamination from a multimeter reading 5-6 ohm across two known-good boards, and no-common-ground); and the ToF capacitance mechanism is INFERRED, not measured — a marginal joint fits equally well, and i2c_scan was never actually run against the failing sensor.'
origin:
  backend: flywheel
  node_id: 24595e77-1647-530b-8a33-c93e38591d70
  slug: icy-base-2242
  revision: 5
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 9b4339dd-c001-5257-9b37-b459907a7f6a
  slug: young-bonus-7460
  revision: 0
  pushed_at: '2026-08-09T21:28:03+00:00'
  content_sha256: 0e9141c1d0778632c8a7737516a39c78fe8bb0a230652b8d2cad0de575d137ff
---
# Full-drone rewire bring-up — Air65 II + XIAO bridge, 2026-07-29/30

**Trigger.** The operator rewired the whole drone (new XIAO board; ToF wires redone; FC 5V and GND moved to different pads; signal wires nominally on their original pads). Nothing worked afterwards: no MSP, no ToF. This node is the fault localisation and the two fixes, plus the tooling built to get there.

## Setup
- Air65 II (Matrix 1S 5IN1 II, STM32G473CEU6, Betaflight API 1.48) + XIAO ESP32-S3 `xiao_bridge`.
- Constraint that shaped the whole session: **the flight battery comes out between tests** (FC overheats on the bench), so every powered window is scarce — and the bridge is powered by USB *or* the FC BEC, which makes "is this layer even energised?" a live question at every step.
- Diagnosis was bottom-up: bridge-local MSP id (needs no FC power) → FC MSP → link budget.

## Results

### Fault 1 — ToF: bus speed, not wiring (FIXED)
`Wire.cpp` error 263 (`ESP_ERR_TIMEOUT`) at boot, reproducible across a full rewire of the sensor's three wires. The discriminator was that `i2c_scan` reaches 0x29 at **100 kHz** while the bridge failed at **400 kHz** on the *same pins*. Longer harness → more bus capacitance → rise time through the breakout's ~10k pull-ups exceeds the 400 kHz budget. `setClock(400000)→100000` (commit `52eacdc`); `tof: VL53L1X up` and live range confirmed. Cost ~2 ms/poll vs ~0.6 ms, inside the 25 ms period but blocking.

### Fault 2 — FC UART: a solder bridge, not a pin (FIXED)
Betaflight `serial` showed `uart1` function 1 @115200, the FC was powered, the bridge answered its own ToF id — yet D9 read dead LOW. Adding an **INPUT_PULLUP** sample to `uart_scan` turned an ambiguous "LOW" into **"stuck low — a 45k pull-up cannot lift it"**, i.e. something low-impedance ties the line to ground. An idle MSP UART TX pad sits HIGH, so that joint was electrically ground.

The decisive evidence is that **the fault followed the wire**: D9 was dead LOW while T1 sat on it; after moving T1 to D1, D9 read `open`/healthy and D1 became the stuck pin. Bisection finished it — wire fully off → D1 `open` (GPIO2 fine); wire on the XIAO end only, FC end dangling → `unstable/floating`, the signature of a free wire whose internal pulls work end-to-end (so the wire conducts and isn't shorted along its length). That left exactly one joint. Clearing the short produced `24 4D 3E 03 01 00 01 30 33` = `MSP_API_VERSION`, API 1.48 — and a reply proves **both** directions, retiring the never-tested D0→R1 outbound leg. Pinout of record moved to **D0/D1** (commit `1a8f494`).

### Tooling shipped
- **`i2c_scan`** (`5396454`) — idle levels + address sweep over every candidate pin pair; the idle-level pass isolates a dead VIN without touching pin order.
- **`uart_scan`** (`5497be0`, `7711126`) — three-mode idle levels + MSP probe; always probes the configured pair.
- **`bench.py checkup`** (`cf513cd`) — the whole host→bridge→FC ladder in one battery window, refusing to blame an upper layer for a lower layer's failure.
- **`bench.py` link hints** (`36484dc`) — actionable triage instead of tracebacks, including the `OSError`/`EHOSTDOWN` case (ARP failure ≠ MSP timeout).

## Verdict / honesty
**GREEN**: the rewire is fully functional — ToF at 100 kHz, MSP round-trip on D0/D1, bridge running off the FC BEC on the new power/ground pads. But the honest content of this node is mostly about **how much of the session was wasted on invalid tests and bad tooling inferences**:

1. **Three invalid tests**, each burning a battery window and pushing the diagnosis sideways: `info` run with the battery out; `tof` run while a probe firmware (no WiFi) was still flashed; `tof` run with the XIAO's WiFi antenna popped out. Every one initially read as a hardware fault.
2. **My own tools produced two wrong leads.** `i2c_scan`'s `Wire.end()` does not detach pins from the I2C peripheral in the GPIO matrix, so a pin used as SCL kept clocking in later pairs and *every* pair with the right SDA appeared to ACK — reported as "SDA=D5 works with any SCL". And `uart_scan` pass 1 called D7/GPIO44 "driven" when it was only a ROM pull-up, spending all 8 probes on an unconnected pin and concluding the wrong direction was at fault.
3. **Pass 1 is not conclusive for a working link.** This FC's TX idles through a weak (~40k) pull-up rather than driving push-pull, so the 45k internal pull-down cancels it and a *good* link reports "weak high". Pass 1 would have vetoed the correct pinout; the always-probe-the-configured-pair rule is what found it. Only "stuck low even with pull-up" is a conclusive pass-1 verdict.
4. **Two hypotheses I pushed were wrong**, and both would have caused needless rework: board-wide contamination (from a multimeter reading 5–6 Ω between arbitrary pins on *two* known-good boards — a systematic instrument error, contradicted by a board that boots and joins WiFi), and no-common-ground (killed when the bridge booted off the FC BEC, which requires that ground).
5. **The ToF mechanism is inferred, not measured.** No scope on the rise time; a marginal joint that only matters at 400 kHz fits the data equally well. The fix is verified, the cause is not. The `i2c_scan` firmware was written for this fault but never actually run against it.
6. D7/GPIO44's "ESD-dead input" verdict in the README belongs to a **since-replaced XIAO** and should not be assumed for this board — it measured healthy here.

## Lineage
Parents: **aged-firefly-8064** (the VL53L1X-on-the-bridge method whose I2C bus speed this corrects), **young-fire-2086** (the `xiao_bridge` firmware the probes were added to), **snowy-heart-2157** (the 2026-07-10 D9/D10 UART pinout this supersedes with D0/D1 — and whose "D7 is ESD-dead" note is now scoped to the old board). Commits: `5396454`, `52eacdc`, `36484dc`, `5497be0`, `7711126`, `cf513cd`, `1a8f494`.