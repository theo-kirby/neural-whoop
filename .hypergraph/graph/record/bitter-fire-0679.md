---
node_id: 69a99f30-4903-570e-ac2b-75c6d2bc53d9
slug: bitter-fire-0679
title: 'Sim2real plan of record: Air65 II + onboard-camera + flow-deck + offboard CTBR-over-MSP'
created_at: '2026-06-29T09:44:11.953236+00:00'
parents:
- blue-mountain-7167
- gentle-bird-8357
summary: 'Concretizes the north-star deploy idea (gentle-bird-8357) into a 4-fork architecture + 4-stage de-risking ladder, decided with the user 2026-06-29. Forks: BetaFPV Air65 II (~25g AUW, chosen over the Mobula6 — see sparkling-lab-8864) airframe / onboard-camera perception (offboard detector) / optical-flow deck fused host-side for velocity / offboard policy streaming CTBR via MSP RC-override over ELRS. REVISES the north-star (offboard-first; onboard-MCU NN deferred) and REALIZES blue-mountain-7167''s RC-channel deployment path. After the dry-vs-AUW weight correction, the airframe gap is modest (~25g real vs 32g sim) and the dominant clearly-wrong gap is action-latency DR. Plan of record, revisable. Full doc: docs/SIM2REAL.md.'
origin:
  backend: flywheel
  node_id: 69a99f30-4903-570e-ac2b-75c6d2bc53d9
  slug: bitter-fire-0679
  revision: 7
  exported_at: '2026-08-09T18:23:28+00:00'
---
# Sim2real plan of record

Where we're going to take neural-whoop policies onto real hardware. Marked as a **plan** — revisable; nothing here is a result yet. Full living doc: `docs/SIM2REAL.md`.

## Framing / change vs parents
The project exists to fly a real tiny-whoop (north-star idea gentle-bird-8357), but the graph stopped at sim metrics + export-clean ONNX. This node turns that gap into a concrete, staged plan, and resolves the open action-space question from blue-mountain-7167.

Two deliberate revisions of the north-star:
- **Offboard-first.** The net runs on the host and streams CTBR over radio; the onboard-MCU NN (G473, RAM-tight; Neuroflight needed an H7) is DEFERRED to a later milestone, not the first flight.
- **A 65mm 1S whoop, not the heavy Meteor75 class.** Airframe of record is the **BetaFPV Air65 II** (~17g dry / **~25g all-up with a 1S pack**) — chosen over the same-mass-class Happymodel Mobula6 (the initial pick) and the heavier Meteor75; see the airframe decision node sparkling-lab-8864. Re-center is to the ~25g AUW.

## The 4 locked forks (decided with the user 2026-06-29)
1. **Airframe:** BetaFPV **Air65 II** — ~17g dry (Racing/Freestyle) / 16.6g (Champion), ~25g AUW with a 1S pack, 65mm, 0702SE II (Racing 30kKV), Matrix 1S 5IN1 II FC (STM32G473, ICM42688P), serial ELRS 2.4, GF 1207 props, analog 5.8G VTX. Chosen for durability (3-pt FC mount, ~80% less crash damage) + BetaFPV ecosystem; see sparkling-lab-8864.
2. **Perception (target_rel):** onboard camera -> OFFBOARD gate/blob detector (real counterpart to the perception oracle; no mocap). Analog FPV -> host VRX + USB capture; gates get visual markers.
3. **Velocity (vel_body):** optical-flow deck (PMW3901 + ToF), fused to body velocity HOST-SIDE. Betaflight does not fuse flow->velocity today (only INAV/ArduPilot, or BF 4.6+), and since the policy is offboard we own the estimator. ~+2g.
4. **Policy execution:** OFFBOARD over radio; CTBR via MSP_SET_RAW_RC over ELRS ~100Hz. This realizes blue-mountain-7167's RC-channel path: feeding the 4 RC channels in acro mode == feeding our CTBR, provided Betaflight rates are flattened/calibrated to our linear +-12/+-6 rad/s act-v2 mapping (so BF's rate curve + PID is the inner loop our sim's RateController stands in for).

This is the most ambitious corner of the option space (light airframe + camera + flow, skipping the mocap and bigger-drone crutches the Crazyflie literature leans on). Staged so each flight isolates one gap.

## The de-risking ladder
- **Stage 0 - Actuation seam bring-up** (bench, drone+USB only, no perception): MSP CTBR injection into Betaflight; calibrate BF rate curve to our linear mapping; measure real rate step-response (vs K_angvel=[16,16,8]), hover throttle, thrust curve/TWR, **AUW (weigh it)**, inertia. Output: re-centered Air65 II airframe DR + matched controller constants.
- **Stage 1 - Perception + velocity pipeline** (offboard, bench/handheld): analog VRX->capture->gate detector->target vector (calibrate DetectorNoise); flow+ToF->host velocity estimator (new DR seam); measure end-to-end latency (widen action_latency DR).
- **Stage 2 - Closed-loop hover/position-hold:** simplest closed-loop flight; validates the full latency budget. Reuses the hover task + impulse DR seam (misty-paper-7383).
- **Stage 3 - gate_race on a real marked track:** lap-time metric vs sim.
- **Deferred:** onboard quantized policy in firmware; honest camera-only perception without the flow deck; swarm.

## Headline sim gaps found (full table in docs/SIM2REAL.md)
- **CORRECTED (dry vs AUW):** the ~17g spec is *dry*; real all-up weight ≈ ~25g (1S pack) / ~27g (with flow deck). So the airframe is only **~20% over** the 32g sim mass (not 2x); inertia scales ~0.8x (not half); arm (~32mm) already right; TWR (~4-5:1) close to the sim 4:1. Modest re-center to ~26g, DR ~22-30g. Landed in configs/gate_race_air65.yaml (57fe87c).
- **Dominant clearly-wrong gap: action_latency DR (0-20ms) far too tight** for offboard+camera (~40-100ms) -> widened to 0-5 steps in the same config.
- BF nonlinear rate curve vs our linear mapping; detector noise currently off; no flow-velocity noise model yet.

## Lineage
Parents: gentle-bird-8357 (north-star deploy idea, this concretizes it) + blue-mountain-7167 (RC-stick action-space idea, this resolves it via MSP). Airframe decision in sparkling-lab-8864 (Air65 II over Mobula6/Meteor75). Relates to the hover/impulse-seam work (misty-paper-7383, Stage 2 target) and the latency reliability lever (wandering-shadow-3679). Children: airframe options + sim re-center (blue-unit-1398), flow-velocity DR seam, Stage 0 bench bring-up, BOM.