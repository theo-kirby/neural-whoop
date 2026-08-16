---
node_id: 7cd12392-2f5d-5970-9a65-5ba1198af84c
slug: quiet-bramble-1724
title: 'Bit-bang coup de grâce: GY-PMW3901 model confirmed, chip silent at 1 kHz hand-rolled SPI on proven wires — conviction final; flow_bitbang + FLOW_SPI_HZ override added'
created_at: '2026-08-16T11:45:27+00:00'
parents:
- bold-sand-0430
summary: ''
---
## What

Evidence-hardening addendum to the flow-breakout conviction ([bold-sand-0430]): the module is
confirmed a standard **GY-PMW3901** (silk `3V3 GND MOS CLK MIS CS RST MOT VRE` — genuinely SPI,
so protocol was never the issue), and a **bit-banged** probe at ~1 kHz convicts it beyond
appeal. Two probe tools added (commit `466e333`).

## Why

After the conviction, the Operator found and reflowed cold joints on the transplant rig and the
chip-id briefly changed character (0xFF → 0x00 → 0xFF across runs on identical config),
raising the possibility of a timing-marginal clone rather than dead silicon. A slower clock and
then a peripheral-free bit-bang read were the two remaining falsifiers.

## Method

- `pmw3901.h` gained a build-time `FLOW_SPI_HZ` override; `flow_probe` re-run at 250 kHz
  (8× under the datasheet ceiling) — still silent.
- New `flow_bitbang` env: hand-rolled SPI mode-3 at ~1 kHz (2000× under spec), 200 µs tSRAD,
  power-on-reset write, then Product_ID (0x00) + Inverse (0x5F) read every 500 ms.
- Run on the spare-XIAO rig immediately after a `wire_test` pull-scan on the same harness
  showed the breakout's own pull-ups visible on CS/CLK/MIS (board electrically present and
  powered) and all wires clean.

## Result

- Bit-bang read: **steady 0xFF/0xFF on every cycle.** No functioning PMW3901 is attached; the
  transient 0x00 was intermittent contact, not a heartbeat. Cumulative: two ESPs, 13 pin
  configurations, three probe methods (2 MHz, 250 kHz, 1 kHz bit-bang) — the chip never
  answered once. Replace the part; the replacement is unambiguous (GY-PMW3901).
- Verdict / honesty: "defective breakout" is now the only surviving hypothesis; the earlier
  "maybe a non-SPI module" caveat in [bold-sand-0430] is retired by the silk readout.

## Repo

- repo: git@github.com:theo-kirby/neural-whoop.git
- branch: main
- commit: 466e3334c80c1b7952b9372575d6564e66127e52

## State Impact

none: evidence hardening only — flow-down state and replacement path already declared by bold-sand-0430; this retires the non-SPI-module caveat and pins the replacement part (GY-PMW3901)
