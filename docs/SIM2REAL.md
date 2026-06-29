# SIM2REAL.md — closing the gap to a real tiny-whoop

Plan of record for taking neural-whoop policies onto real hardware. Companion to `docs/CONTRACT.md`
(the obs/act/DR seam this leans on). Status: **planning** — no hardware in hand yet.

## Locked architecture (decided 2026-06-29 with the user)

| Fork | Choice | Why / implication |
|------|--------|-------------------|
| **Airframe** | **BetaFPV Air65 II** (~17 g racing / 16.6 g champion, 65 mm, 0702SE II 30kKV racing, Matrix G473/ICM42688P, GF 1207 props, analog 5.8G VTX, serial ELRS 2.4) | A true light/twitchy ~17 g tiny-whoop. **Chosen over the same-mass-class Mobula6** (the initial pick) for durability (3-pt FC mount, ~80% less crash damage) + BetaFPV ecosystem, and over the heavier Meteor75. **Forces an airframe-DR re-center** (sim is currently Meteor75-massed). See *Airframe selection* below. |
| **Perception (target_rel)** | **Onboard camera** → offboard gate/blob detector | Real counterpart to the perception oracle (`perception/`). No mocap rig. Analog FPV → host VRX + USB capture; gates need visual markers. |
| **Velocity (vel_body)** | **Optical-flow deck** (PMW3901 + ToF), **fused to velocity on the host** | Betaflight does *not* fuse flow→velocity today (4.6/2025.12 only; INAV/ArduPilot do). Since the policy is offboard, we read raw flow + range and estimate velocity host-side. ~+2 g. |
| **Policy execution** | **Offboard over radio** | Net runs on host, streams CTBR ~100 Hz via MSP (`MSP_SET_RAW_RC`) over ELRS. Matches the Crazyflie sim2real literature and our TorchScript/ONNX export path. Onboard (G473) firmware NN is a later milestone (RAM-tight; Neuroflight needed an H7). |

This is deliberately the **most ambitious corner** of the option space: light airframe + camera perception + flow velocity, skipping the two crutches (mocap, bigger drone) the Crazyflie papers lean on. Staged below so each flight isolates one gap.

## Airframe selection (decided 2026-06-29)

Three 65 mm-class 1S whoops were weighed (Flywheel: airframe-of-record `sparkling-lab-8864`, options `wild-shape-7463` / `black-butterfly-6195`):

- **BetaFPV Air65 II — chosen.** ~17 g, best-reviewed 65 mm whoop, durable 3-pt FC mount (~80% less crash damage — decisive for a crash-heavy autonomous bring-up), BetaFPV/Meteor parts + battery ecosystem.
- **Happymodel Mobula6 2024 V3 — initial pick, superseded.** ~17.6 g, same mass class (so the sim re-center is *identical*); lost on durability + ecosystem, not dynamics.
- **BetaFPV Meteor75 Pro — set aside.** ~31 g; closest to our current sim mass (28–36 g) but the least "true tiny-whoop". Surfaced the finding that our sim is Meteor75-massed.

Because the chosen and runner-up are the same ~17 g class, the dynamics gap below is airframe-switch-invariant.

## The gap: sim today vs. Air65 II (real AUW ~25 g)

Sim values from `dynamics/whoop.py`, `contract.py`, `randomization.py`, `configs/gate_race.yaml`.
**Weight note:** the "~17 g" spec is *dry* (no battery). Real **all-up weight** = ~17 g dry + ~8 g (1S 300 mAh) ≈ **~25 g**, or **~27 g** with the ~2 g flow deck. The sim `mass` is AUW, so that's the number to match.

| Quantity | Sim default / DR | Air65 II reality (AUW) | Action |
|---|---|---|---|
| Mass (AUW) | 32 g, DR **28–36 g** | **~25 g** (27 g w/ flow deck) | Re-center to **~26 g, DR ~22–30 g** (`whoop.py:48`). ~20% lighter — modest, not 2×. |
| Inertia J_xy / J_z | 2.3e-5 / 4.0e-5, ±10% | ~0.8× (mass ~20% lower, same 65 mm geometry) | Scale nominals ~0.8× (`whoop.py:51-52`). |
| Arm length | 32 mm | ~32 mm (65 mm wheelbase ÷ 2) | Already correct; confirm at Stage 0 (`whoop.py:49`). |
| TWR (max thrust) | 4:1 (`max_thrust_normed=4.0`) | ~4–5:1 at ~25 g AUW (0702 30kKV) | Sim is **close**; pin from thrust curve at Stage 0 (`contract.py:96`). |
| Rate-loop `K_angvel` | [16,16,8] fixed | = Betaflight PID tune (unknown) | Measure real rate step-response; this is what `rate_gain_frac` hedges (`whoop.py:67`). |
| Policy/control rate | 50 Hz (dt=0.02) | offboard link ~100 Hz typical | Consider 100 Hz; 50 Hz marginal w/ video round-trip (`whoop.py:62`). |
| **Action latency DR** | **0–1 step (0–20 ms)** | offboard+camera ≈ **40–100 ms** | **Widen to ~0–5 steps (0–100 ms)** — the one clearly-large gap (`randomization.py:56`). |
| Body rates | ±12/±12/±6 rad/s, **linear** | Betaflight nonlinear rate curve | Flatten/calibrate BF rates to linear mapping (`contract.py:98-99`). |
| Detector noise | **off** in gate_race | real gate detector on low-res analog FPV | Turn on + calibrate `DetectorNoise` from real video (`perception/`). |
| **Flow→velocity noise** | none (sim feeds GT vel) | flow dropout over low-texture floor, height-coupling, latency | **New DR seam**: flow-velocity error model (counterpart to `DetectorNoise`). |

Revised headline (after the dry-vs-AUW correction): the **mass gap is modest** (~25 g real vs 32 g sim, ~20%; inertia/TWR scale gently and arm is already right), so the **dominant clearly-wrong gap is the action-latency DR** (0–20 ms vs ~40–100 ms offboard). Final airframe numbers get pinned by weighing the real drone at Stage 0.

## Staged plan (de-risking ladder)

### Stage 0 — Actuation seam bring-up (bench, no perception)
Prove the CTBR seam in isolation. Needs only the drone + USB.
- MSP `MSP_SET_RAW_RC` injection into Betaflight (acro mode); handle the MSP-override/failsafe interaction.
- Calibrate Betaflight rate curve → our linear ±12/±6 rad/s mapping.
- Measure real rate step-response (vs `K_angvel=[16,16,8]`), hover throttle, thrust curve / TWR, mass, inertia.
- **Output:** re-centered Air65 II airframe DR + matched controller constants in `dynamics/whoop.py`.

### Stage 1 — Perception + velocity pipeline (offboard, bench/handheld)
- Analog VRX → USB capture → gate detector → body-frame target vector; measure detector noise → fold into `DetectorNoise`.
- Flow deck → host-side flow+ToF→velocity estimator; measure error → new flow-velocity DR seam.
- Measure full end-to-end latency → widen `action_latency` DR.

### Stage 2 — Closed-loop `hover` / position-hold
Simplest closed-loop flight; validates the full latency budget end-to-end. Reuses the `hover` task + Studio Live disturbance seam (`add_velocity`/`add_body_rate`).

### Stage 3 — `gate_race` on a real marked track
Real gates with visual markers; lap-time metric vs sim.

### Later (deferred)
Onboard quantized policy in firmware (G473); honest camera-only perception without the flow deck; swarm.

## Sim-side work startable now (no hardware)
1. Air65 II airframe DR re-center (mass/inertia/arm/TWR) — config + `whoop.py`.
2. Widen `action_latency` DR to a realistic offboard range; consider 100 Hz control.
3. Add the flow-velocity DR seam (dropout, height-coupling, latency) in `randomization.py` — counterpart to `DetectorNoise`.
4. Turn on `DetectorNoise` for a camera-perception racing config.
5. Re-train + re-eval `hover` and `gate_race` under the new DR; confirm in Studio.

## Bill of materials
**Stage 0 (order first):**
- BetaFPV **Air65 II** (Racing, 0702 30kKV), Analog, ELRS 2.4 GHz.
- 1S batteries (BT2.0/A30, ~300 mAh) ×6+ and a 1S charger.
- ELRS radio/TX for binding + manual-pilot backup (e.g. RadioMaster Pocket ELRS) — also the MSP uplink path.
- Spare props / motors / frames (whoops crash).

**Stage 1 (perception + velocity):**
- Analog 5.8 GHz VRX with USB/AV out + USB capture card (host-side video in).
- Optical-flow + ToF module: **Matek 3901-L0X** (UART, MSP V2) or a Bitcraze Flow Deck v2 (PMW3901+VL53L1x, ~1.6 g) for the raw-SPI route. Wire to the free **UART1**.
- Gate markers (AprilTags / LED rings / colored gates) for robust low-res detection.

## Open risks / unknowns
- **Flow on a whoop:** Betaflight won't fuse it — we own the estimator host-side; mounting a downward sensor unobstructed by battery/frame is fiddly; may need a tiny companion MCU if UART forwarding is messy.
- **MSP override + failsafe:** known Betaflight pain (issues #12790/#13374); must keep a manual-pilot fallback.
- **Analog FPV** is low-res/noisy — detection wants marked gates; capture card adds latency (budget it into DR).
- **Latency** is the dominant offboard risk; measure early, model honestly.
