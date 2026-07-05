# SIM2REAL.md — closing the gap to a real tiny-whoop

Plan of record for taking neural-whoop policies onto real hardware. Companion to `docs/CONTRACT.md`
(the obs/act/DR seam this leans on). Status: **hardware purchased** — Air65 II bought 2026-07-03;
bring-up starts at Stage 0 when it arrives.

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

**Bench ladder complete over the WiFi bridge (2026-07-05, branch B live):** `info` (BTFL
2026.6.0), `latency` (median **2.41 ms**, p99 24 ms — ~100× inside the 300 ms freshness
window), `rc-test` (override seam proven; **MSP_SET_RAW_RC is AETR wire order**, rcData reads
RPYT — see `bench/msp.py`), `motor-test` (indices 0–3 = RR, FR, RL, FL, standard quad-X).
Commits `da0e37a`, `3c5e2bb`. Still open here: rate-curve calibration, step-response/thrust
measurements, and the `msp_override_failsafe` decision.

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

## Control/compute-path branch map (2026-07-03, hardware purchased)

Where the policy runs × how commands reach the FC. Researched (web, sources in the Flywheel node)
now that the Air65 II is bought. Verified I/O facts first:

- **FC I/O (Matrix 1S 5IN1 II, STM32G473CEU6):** 4 UARTs — UART2=VTX, UART3=onboard ELRS RX
  (removable via a resistor), **UART1 + UART4 free** for a companion. Ships with a BF 2026.6.0
  custom build.
- **Betaflight external-control seams:** (a) **MSP override** (`msp_override_channels_mask` +
  MSPRCOVERRIDE mode) — real and current; `msp_override_failsafe` (BF 4.5+, PR #13380) fixes the
  RC-loss failsafe trap; per-channel **300 ms freshness window**; serviced at ~**100 Hz** default
  (`serial_update_rate_hz` raises it). (b) Companion **emulating a CRSF receiver** into the RX
  UART — electrically plausible (416 kbaud, 250 Hz+), **no confirmed working writeup** (BF
  discussion #14064 failed unanswered); treat as unproven. (c) **MAVLink serial-receiver provider**
  (BF 2025.12+, pairs with ELRS MAVLink mode at 460800) — genuine bidirectional RC+telemetry on one
  link.
- **Offboard ELRS uplink is proven:** host/RPi driving an ELRS TX module's CRSF pin directly
  (RC_CHANNELS_PACKED at ~250 Hz, e.g. RadioMaster Ranger Micro at 460800) binds and flies a BF
  quad; single-digit-ms OTA at 250–500 Hz. `elrs-joystick-control` does gamepad→CRSF→module.
- **Pinned weights (BetaFPV spec tables, 2026-07-04):** Air65 II dry = **17.7 g Racing** / 17.8 g
  Freestyle / 16.6 g Champion; LAVA II 1S = **8.2 g (320 mAh)** / 6.8 g (280 mAh), BT2.0. So base
  AUW ≈ 25.9 g (Racing + 320), and the bridge stack ≈ **29.5–31.5 g** (+ ~2 g flow deck + plain
  XIAO ~3 g — the camera-less XIAO suffices for branch B; the Sense (~5 g w/ camera) is a branch-D
  part). No published bare-board XIAO weight exists (retail "14.68 g" is packaged); ~3 g is
  inferred from same-size boards — the one number still worth a real scale eventually.
- **ESP32 companion (Seeed XIAO ESP32-S3 / Sense):** ~3–5 g class (see pinned weights above),
  8 MB PSRAM/flash, camera on Sense (OV2640/OV3660, detection-class vision ~3–10 fps CNN, maybe
  15–30 fps for cheap blob/marker — unbenchmarked). **ESP-NOW ≈ 5.6 ms median** link latency
  (100–200 Hz plausible), WiFi UDP ~9 ms tuned (jittery untuned), BLE floor 7.5 ms. **BLE-only (no
  BT Classic)**: Xbox Series pads pair via Bluepad32 (fw 5.15+ is BLE); PS4/PS5/Switch pads need BT
  Classic (original ESP32). TinyPolicy-size int8 MLP ≈ 0.1–0.4 ms via esp-nn (extrapolated).
  Prior art: DroneBridge/ESP32 (MSP over ESP-NOW/WiFi, the exact companion pattern), esp-drone,
  esp-fc. Payload cost: +4–6 g → ~29–31 g AUW, TWR ~3.5–4:1 — flyable, ironically back inside the
  old Meteor75-massed DR band.

The branches (all share the Stage-0 bench work; latency band is the DR knob that differs):

| Branch | Path | Command seam / rate | Latency band | Status |
|---|---|---|---|---|
| **A. Offboard ELRS** *(plan of record)* | host policy → ELRS TX module → onboard RX | CRSF 250 Hz | ~40–100 ms end-to-end (camera loop) | First flight path — proven, real failsafe, manual takeover on same link |
| **B. ESP32 bridge** | host policy → ESP-NOW → XIAO on UART1 → MSP/CRSF into FC | MSP ~100 Hz (default) | ~20–50 ms | Solves the flow-deck **downlink** (companion reads flow+ToF, ships telemetry back); gateway to D |
| **C1. Gamepad via host** | Xbox pad → PC → CRSF → ELRS module | 250 Hz | ~10–20 ms | The manual-fallback rig; build immediately with A |
| **C2. Gamepad direct-to-drone** | Xbox pad → BLE → onboard XIAO → FC | BLE ≥7.5 ms interval (~133 Hz) | ~15–30 ms | Fun demo (no radio, no PC); off critical path |
| **D1. Fully onboard** | XIAO runs int8 policy; flow (+Sense camera) obs; UART to FC | MSP/CRSF local | ~5–20 ms (**lowest**) | Post-Stage-2 branch: **onboard `hover` needs no camera** — flow+FC-attitude obs only |
| D2. Policy in BF firmware (G473) | — | — | lowest | Stays deferred (RAM-tight) |

Notes: (1) The uplink/action **split-latency DR seam** already in the env (`uplink_latency_steps` /
`uplink_interval_steps`, `docs/CONTRACT.md`) is exactly how these branches differ in sim — each
branch is a DR config, not new code. (2) Branch B directly resolves the "flow forwarding may need a
tiny companion MCU" open risk below. (3) D1's obs problem decomposes: `hover`/position-hold needs
only flow-velocity + attitude (no perception), so "fully onboard hover" is a realistic near-term
milestone; onboard gate perception is the hard tail.

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

**Branches B/C2/D1 (companion, optional — order when branch opens):**
- Seeed **XIAO ESP32-S3 Sense** (~3–5 g w/ camera; weigh it) + a plain XIAO ESP32-S3 as the
  host-side ESP-NOW peer. Xbox Series controller (fw ≥5.15, BLE) for C2.

## Idea backlog: apartment-scan environment via Meta Quest 3 (2026-07-04)

User owns a Quest 3 — scan the apartment, train against the real geometry, then fly the *same*
course in the *same* room (collapses the Stage-3 sim↔real course gap to ~zero). Sketch:

1. **Export the scan.** Quest 3 Scene Mesh (depth-sensor room mesh) via a small in-headset app →
   OBJ/GLTF; fallback: walk-around video → photogrammetry/splatting on the 5090.
2. **Mesh → SDF.** Bake a voxel signed-distance field (~5 cm, a torch tensor) — batched
   GPU-friendly collision the way the env already works; keep the GLTF for viz.
3. **Env seam: obstacle field.** New DR-compatible collision seam (termination + distance penalty +
   spawn validity) sampled from the SDF; course YAML authored in apartment coordinates.
4. **Viz.** Apartment mesh as the Studio / nw-viz backdrop (three.js loads GLTF natively) — hero
   MP4s of the policy flying through *your actual living room*, pre-flight.
5. **Real flight** (branch A offboard) on the matching physical course.

Sub-ideas: Quest controller as a **gate-authoring wand** (touch a point in the room → gate pose in
the scan frame — solves course registration); MR ground station (telemetry overlaid on the real
drone); Quest hand-tracking as the real counterpart of the `hand_follow`/`gesture_follow` tasks.
Open problems: mesh-export friction (Scene Mesh needs an app with scene permission), scan accuracy
(~2–3 cm class), and **frame registration** — aligning the drone's world frame to the scan frame is
the real work (the wand idea + a known takeoff point is the likely answer).

## Open risks / unknowns
- **Flow on a whoop:** Betaflight won't fuse it — we own the estimator host-side; mounting a downward sensor unobstructed by battery/frame is fiddly; may need a tiny companion MCU if UART forwarding is messy.
- **MSP override + failsafe:** known Betaflight pain (issues #12790/#13374); must keep a manual-pilot fallback.
- **Analog FPV** is low-res/noisy — detection wants marked gates; capture card adds latency (budget it into DR).
- **Latency** is the dominant offboard risk; measure early, model honestly.
