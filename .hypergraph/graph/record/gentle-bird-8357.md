---
node_id: a30d17a6-b511-5009-b5da-aac8f7796e3f
slug: gentle-bird-8357
title: 'Idea/north-star: deploy a trained policy on the real ~32 g whoop MCU (the actual objective)'
created_at: '2026-06-27T15:03:20.251940+00:00'
parents:
- sparkling-limit-8154
- shrill-limit-5398
summary: 'The whole project exists to fly a real tiny-whoop, yet the graph has no hardware-deployment node — every result stops at a sim metric + an export-clean ONNX. This frames that gap and a path: quantize a deployable baseline (the [128,128]@120M racer 8db85abb, ~19k params, or the scale-generalist) to int8, run it on a flight-controller-class MCU as a CTBR inner loop, and bridge the real obs-v4 estimator -> act-v2 rate setpoints. The branch the MCU-LOCKED policy-size discipline has been protecting all along.'
origin:
  backend: flywheel
  node_id: a30d17a6-b511-5009-b5da-aac8f7796e3f
  slug: gentle-bird-8357
  revision: 9
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Status: NORTH-STAR IDEA / integration branch (not a sim experiment)

## The gap
CLAUDE.md's premise is a real ~32 g tiny-whoop running a tiny, quantization-friendly policy on a microcontroller. The graph has driven policy size down and kept every actor export-clean for exactly this — but there is **no node about putting one on hardware**. Every result terminates at a sim metric plus a `policy.onnx`. This node opens that branch so it stops being implicit.

## The path (sketch)
- **Pick the deploy policy.** The single-drone racer `8db85abb` ([128,128]@120M, ~19k params, ONNX round-trips ~3e-7, DR-on 2.67s/0.80) is the natural first target; the scale-generalist (`b4c3466f`) if varied real courses matter; swarm later.
- **Quantize.** int8 post-training quant (~19 KB weights) — verify the deploy-policy still flies in sim after quant (an honest pre-deploy gate), not just that it exports.
- **Target a board.** Flight-controller-class MCU (ESP32-S3 / STM32-class) running the policy at the control rate (50 Hz today) as the outer loop, feeding the existing rate (CTBR) inner loop. Runtime TBD: TFLite-Micro vs a hand-rolled int8 GEMM (the net is small enough that hand-rolling may win on footprint/latency).
- **Bridge the contract.** obs-v4 (body-frame, heading-invariant) must be produced by the REAL estimator — the render-free oracle is a sim stand-in; on hardware it's VIO / external mocap / an onboard detector. act-v2 -> the FC's rate setpoints via `action_to_diffaero`'s real-hardware analogue.

## Open questions (what makes this a research branch, not just an export)
1. Which obs estimator closes the loop on a 32 g board, and how much does its noise/latency cost vs the trained DR seam? (The DR seam was chosen to bracket exactly this.)
2. Board + runtime + control-rate budget — does 50 Hz inference fit, or does the rate drop?
3. Does int8 quant hold the DR-on reliability (0.80), or does it need quant-aware training?

## Lineage
- builds-on `8db85abb` (the deployable single-drone racing baseline + its export-clean ONNX).
- builds-on `69c82afe` (the [128,128] capacity probe that set, and flagged, the ~19k-param MCU deploy-size budget this must respect).