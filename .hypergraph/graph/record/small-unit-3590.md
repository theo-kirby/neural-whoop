---
node_id: a5143fbd-b7db-5277-a9da-e8e06e0994d0
slug: small-unit-3590
title: 'BOM: hardware procurement for the sim2real first flights (Air65 II + ELRS + VRX/capture + flow deck)'
created_at: '2026-06-29T09:45:38.665144+00:00'
parents:
- bitter-fire-0679
summary: 'Bill of materials for the staged plan. Stage 0 needs only: BetaFPV Air65 II (Racing, analog, ELRS 2.4), BetaFPV LAVA 1S batteries + charger, an ELRS radio/TX (bind + manual backup + MSP uplink), spare props/motors/frames. Stage 1 adds: analog 5.8GHz VRX + USB capture card, an optical-flow+ToF module (Matek 3901-L0X over the free UART, or Bitcraze Flow Deck v2 raw-SPI ~1.6g), gate markers. Procurement list, user action.'
origin:
  backend: flywheel
  node_id: a5143fbd-b7db-5277-a9da-e8e06e0994d0
  slug: small-unit-3590
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
---
# BOM — sim2real hardware

Procurement list for the de-risking ladder (full notes in docs/SIM2REAL.md). User action to order. Airframe of record: BetaFPV Air65 II (sparkling-lab-8864).

## Stage 0 (order first — actuation seam, no perception)
- BetaFPV **Air65 II** (Racing edition, 0702 30kKV), Analog, ELRS 2.4GHz.
- BetaFPV **LAVA 1S** 260/300mAh (BT2.0) x6+ and a 1S charger.
- ELRS radio/TX (e.g. RadioMaster Pocket ELRS) — bind + manual-pilot backup + the MSP uplink path.
- Spare GF 1207 props / 0702SE II motors / Air65 II frame.

## Stage 1 (perception + velocity)
- Analog 5.8GHz VRX with USB/AV out + USB capture card (host video in).
- Optical-flow + ToF module: **Matek 3901-L0X** (UART, MSP V2, wire to free UART) or **Bitcraze Flow Deck v2** (PMW3901+VL53L1x, ~1.6g, raw-SPI route).
- Gate markers (AprilTags / LED rings / colored gates) for robust low-res detection.

## Open risks
- Flow on a whoop: BF won't fuse it (we own the host-side estimator); downward sensor mounting unobstructed by battery/frame is fiddly; may need a tiny companion MCU.
- MSP override + failsafe (BF #12790/#13374) — keep manual fallback.
- Analog FPV is low-res/noisy (mark gates); capture adds latency (budget into DR).

**Lineage.** Child of the sim2real plan (bitter-fire-0679); airframe per sparkling-lab-8864. Stage-0 items gate the Stage-0 bench node; Stage-1 items gate the perception/velocity + flow-seam work.