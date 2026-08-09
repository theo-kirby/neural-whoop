---
node_id: 099aa301-86ac-5cf1-9e0f-ede0c899a166
slug: blue-mountain-7167
title: 'Idea: RC-stick action space — NN outputs RX channels into Betaflight (vs CTBR act-v2)'
created_at: '2026-06-27T16:17:48.612096+00:00'
parents:
- winter-sun-1382
- gentle-bird-8357
summary: 'Idea (placeholder, untested): emit RC stick/RX channels into Betaflight as the action space instead of the current CTBR act-v2, so the trained net drives a stock flight controller — letting Betaflight''s own rate curve + PID inner loop + mixer close the loop while the policy acts as a ''virtual pilot'' on unmodified firmware. This is a more directly deployable path to the real ~32 g whoop MCU; it would require modelling Betaflight''s stick→rate mapping and rate PID loop in-sim so training matches deployment. Framing for the hardware-deployment thread; branch opened, not started.'
origin:
  backend: flywheel
  node_id: 099aa301-86ac-5cf1-9e0f-ede0c899a166
  slug: blue-mountain-7167
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 4c45846a-3393-5323-84c1-5a4ace579cc5
  slug: sweet-sun-0284
  revision: 0
  pushed_at: '2026-08-09T21:26:36+00:00'
  content_sha256: b7a12f118d661642e033fbb571f441c911d2302a55afe84d5500e9700dea8edb
---
## Status: PLACEHOLDER (branch opened, not started)

## Idea
Today the policy emits **act-v2 CTBR** (collective thrust + body rates), which `action_to_diffaero` feeds to DiffAero's rate controller. An alternative, deploy-friendly action space: the NN outputs the **4 RC stick channels** (roll/pitch/yaw/throttle — exactly the RX setpoints a human pilot's transmitter sends), and **Betaflight** (or any stock FC) runs its own rate curve + PID inner loop + motor mixer. The policy becomes a ‘virtual pilot’ on unmodified firmware — plausibly the **lowest-friction path onto real hardware** (no custom CTBR firmware bridge).

## What it needs (the catch)
To train a policy that transfers, the sim must model **Betaflight's stick→rate mapping** (RC rates / super-rates / expo curve) AND its rate PID loop + mixer, so the in-sim response to a stick command matches the real FC's. That's a new action-mapping layer (a `BetaflightController` analogue of the CTBR `RateController`) and a small contract variant (act-v3-rc). Open questions: which Betaflight rate-curve params to assume / randomize; whether to also model FC loop rate + filtering; throttle→thrust nonlinearity.

## Why a sibling of MCU-deploy, not the same
The MCU-deploy node (`gentle-bird-8357`) runs the policy's CTBR outer loop ON the board. This branch instead **offloads the inner loop to existing FC firmware** and only sends sticks — a different, arguably easier, deployment architecture worth comparing.

## Lineage
- builds-on `a30d17a6` (MCU-deploy north-star — the sibling hardware path).
- builds-on `ff881809` (the act-v2 CTBR baseline — the action space this replaces).