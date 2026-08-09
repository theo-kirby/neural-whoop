---
node_id: 8e282aad-58b2-5a76-b945-c431fa4085e2
slug: vast-dune-7535
title: Honest camera-only perception is blocked on an upstream Blackwell bug and on hardware that has not been integrated
created_at: '2026-08-09T18:42:33+00:00'
parents:
- long-mountain-5811
summary: 'Training is render-free by design and the detector-noise seam works. The honest camera-only eval path is a stub: render_depth raises NotImplementedError, photoreal RGB waits on Isaac Lab''s Blackwell tiled-camera bug #4951, and the chosen camera module has not been integrated.'
---
Status: blocked

## Current

Perception is deliberately render-free in training: an `OracleEstimator` supplies the
ground-truth body-frame target vector, optionally corrupted by a batched
`DetectorNoise` model, so a policy survives real detection noise without rendering a
pixel. That seam works and is the foundation of the whole follow line.

The **honest** camera-only path does not exist yet:

- `viz/render.py::render_depth` [rec: wandering-water-2720] is a documented stub that raises
  `NotImplementedError` (`docs/VISUAL_CONTRACT.md`). The analytic synthetic FPV in the
  standard pack covers the FPV artifact until then.
- Photoreal RGB via Isaac Lab [rec: morning-feather-7342] is deferred pending **Isaac's tiled-camera Blackwell
  bug #4951** — an upstream defect outside this repo (`docs/TASK_CATALOG.md`,
  deferred branches).

**The hardware decision is made and unexecuted.** A deep-research pass over 15
primary sources and 73 adversarially-verified claims settled the sensing path under
the user's hard constraint of nothing off the drone for sensing
[rec: bitter-sun-1558], and the decision is one module: a XIAO ESP32-S3 Sense
(about $15, ~4 g, OV2640) mounted **downward**, plus a ~$4 VL53L1X on its I2C — the
Sense *replaces* the plain ESP32 bridge rather than adding to it, giving a complete
DIY position deck for about $19 [rec: still-flower-6355]. It has not been integrated.

## Negative knowledge

- [scope: classical monocular VIO on a whoop | confidence: high | evidence: bitter-sun-1558] The fragile path, and it was ruled out on evidence. Scale is unobservable and state-of-the-art VIO fails at racing speed. Learned gate/landmark detection plus a dynamics model and an EKF beats it — MonoRace beat three FPV world champions with a monocular camera and IMU and explicitly not VIO, and a 72 g airframe did whoop-mass onboard monocular racing the same way.
- [scope: alternative sensing hardware for this drone | confidence: high | evidence: bitter-sun-1558, still-flower-6355] Ruled out with reasons: the analog FPV receiver (an inferior forward-facing sensor plus ground gear, about $30), a digital-FPV system (heavy, $70+, needs its own receiver), and UWB (swarm-only, one per drone). docs/ROADMAP.md independently declines stereo or dual whoop cameras (one DVP interface per S3, no frame sync, blows the mass margin), an external accelerometer module (the FC's own is better mounted and free), an NFC tag (1-4 cm range), and WiFi FTM localisation (1-5 m indoor error against a 2-4 m arena).
- [scope: the cost of the chosen route | confidence: medium | evidence: still-flower-6355] Recorded as the real open risk of the decision rather than hidden: streaming video off the ESP32-S3 over WiFi at QVGA 10-25 fps while keeping the MSP bridge alive on the same chip is unproven firmware work.

## Provenance

- tight-limit-5820 — the original framing of the perception sim2real gap and the honest-eval hook
- bitter-sun-1558 — the cited literature synthesis behind the sensing decision
- still-flower-6355 — the one-module decision, its rationale, and its stated open risk
