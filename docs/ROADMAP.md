# ROADMAP — sensorless polish, off-drone rig, richer sim (2026-07-11)

A synthesis of where neural-whoop is and what to do next, grounded in (a) a full repo stock-take,
(b) a SOTA sweep of blind/IMU-only RL flight, learned acro, and latency-robust control, and (c) a
hardware-feasibility triage of the off-drone ideas. Written the day after the first Bench-dashboard
flight session exposed the "super wobbly, shaky, non-stationary" hover.

The organizing insight: **most of the near-term wins need no new hardware.** The PMW3901 flow sensor
and VL53L1X ToF are weeks out; almost everything below ships before they arrive, and the ones that
don't are honest research bets, not blockers.

> **Update 2026-07-13:** the VL53L1X arrived first (CJMCU-531 breakout) and is integrated as the
> bridge's downward height sensor — `MSP_BRIDGE_TOF` on the xiao_bridge, `tof_m` in the flight CSV,
> measured z in the flight-report replay (the ∫vz_est stub retired for ToF-equipped flights). See
> `firmware/xiao_bridge/README.md` for wiring + bring-up. Telemetry-only for now (not in obs);
> item 9's flow×height fusion still waits on the PMW3901.

## Where we are

- **Blind hover (`hover_blind`, deploy `d50var_s8`)** — obs `[roll, pitch, p, q, r]×8`. Attitude is
  solved (gyro-noise wall beaten by per-episode noise-amp DR + obs-stacking; RPM-anchor vz damper
  killed the ceiling bug). New best in the Bench session: 9.0 s continuous stable hover @ 2.2°.
  **But** the policy is architecturally blind to translation, so hover is non-stationary — it marches
  (consistent +2.5° pitch trim bias) and shakes (a ~2.5 Hz delay-induced limit cycle) with
  latency-tail excursions. `hover_blind_v2` (added vz + noise DR) is RED — do not deploy.
- **Acro (`acro_flip`)** — obs 7-dim `[gravity_body, p, q, r, rotation_remaining]`, IMU-only/blind.
  **Trained GREEN on both axes** (roll flip_success_rate 0.845, pitch 0.840, crash 0.000 — a clean
  axis ablation). **Pilot harness wired**: a bounded FLIP window at HOVER (the pilot owns
  takeoff/land, the acro policy owns the flip), verified end-to-end on the fake bridge. Real-drone
  flip is still hardware-gated (sim + fake-bridge integration only).
- **Bench dashboard** — 4 tabs shipped (Bench/Player/Live/Editor); Start interlock fixed; auto
  flight-report on landing; parallel CPU-sim twin. Link p99 tail doubled (137-170 ms) vs the CLI —
  an open confound.
- **The "one module" decision (2026-07-07)** already committed to a XIAO ESP32-S3 Sense (downward
  cam) + ToF as the eventual perception master-key. Weigh new hardware ideas against that, not fresh.

## Priority tiers

### Tier 1 — ship this week, no new hardware, highest leverage

1. **Accelerometer in obs → observable lateral velocity → station-keeping.** The FC's accel is free
   over `MSP_RAW_IMU` (msg 102, ~50-100 Hz). Rotor drag makes lateral accel ≈ k·v_body, so velocity
   — unobservable from gyro+attitude — becomes observable. This is the #1 SOTA-recommended fix for
   non-stationary hover and the only one that ships before the flow deck.
   *Work:* DiffAero synthesizes accel = specific force + drag model (bias/noise DR); new
   `hover_accel` task/config; extend `pilot.obs_from_msp` to read msg 102; relax `check_policy_family`;
   retrain on the 5090.
   *SOTA:* Cioffi/Scaramuzza learned inertial odometry (RA-L 2023); accel+drag observability
   (arXiv 1509.03388); RAPTOR (2025) flies 32 g Betaflight quads with a 2 k-param recurrent policy.

2. **Action-history + action-rate smoothness penalty.** Append the last k≈2-4 actions to the obs
   (restores Markovness under delay = the standard latency fix, and is the input implicit-odometry
   needs) and add an action-difference penalty. This is the documented cure for the exact 2.5 Hz
   delayed-derivative limit cycle we measured.
   *SOTA:* SimpleFlight / "What Matters in Zero-Shot Sim-to-Real" (2024) names action-smoothness as
   its anti-oscillation lever; Delay-Aware MDP (action-augmentation restores Markovness).

3. ~~**Train `acro_flip` on the 5090.**~~ **DONE** — roll + pitch both GREEN (0.845 / 0.840
   flip_success_rate, crash 0.000). Blind was *sufficient* for the single attitude maneuver (Deep
   Drone Acrobatics ablation: IMU carries the maneuver, vision only fixes inter-maneuver drift).
   Next agility verdict is the *real-drone* flip (hardware-gated).

4. **Fiducial mocap rig (Mac-only, the measurement backbone).** One fixed webcam + a 6-8 cm
   ArUco/AprilTag on top of the whoop → ground-truth XY at ~0.5-2 cm, 30 fps. Retires the
   vertical-only `pos` stub in `flight_report.py`, gives Studio real trajectories, and — critically —
   makes drift measurable so we can *prove* whether #1/#2 actually reduced it. Do this early; it
   grades everything else.

### Tier 2 — dashboard/UX + near-term glue

5. **Browser gamepad control.** Web Gamepad API in the dashboard: poll `navigator.getGamepads()` in
   the existing 50 Hz send loop, map sticks → setpoint / CTBR override over the current websocket. No
   firmware, dashboard stays the single arbiter/kill-switch. (Not the ESP-side path — see declined.)
6. **Real Air65 II chassis mesh in Studio.** Replace the procedural box glyph with the actual
   airframe. Self-contained tooling-viz win; needs a GLTF/STL of the Air65 II.
7. ~~**Pilot acro harness.**~~ **DONE** — `obs_from_msp_acro` (sim-parity gravity_body) +
   `check_policy_family_acro` + a FLIP phase/maneuver-clock in `pilot/controller.py` (crash detector
   + RPM governor + climb damper all suspended only inside the bounded window). Triggered by
   `request_flip()` (Bench Flip button / `fly --flip-at`), gated to HOVER + fresh link + near-level.
   System take-off->flip->land flies blind on the fake bridge; real-drone flip stays hardware-gated.

### Tier 3 — hardware-gated / bigger research bets

8. **GRU / RMA recurrent tiny-policy.** RAPTOR shows ~2 k-param recurrent policies fly 32 g
   Betaflight quads and adapt in ms; frame-stacks are the weaker form of the same memory. Privileged
   critic + our existing DR seam as the latent (wind/rate-gain/thrust/latency).
9. **When PMW3901 + VL53L1X arrive.** *(VL53L1X arrived + integrated 2026-07-13 — bridge-answered
   `MSP_BRIDGE_TOF`, `tof_m` telemetry, measured replay z; same day: `hover_tof` puts the measured
   height in the obs — the policy owns the altitude loop, docs/TASK_CATALOG.md. The fusion below
   still waits on the PMW3901.)* Plan A (matches all published Crazyflie practice): fuse
   flow×height → v_body on the bridge, feed obs-v4's `vel_body` unchanged. Plan B (novel): raw flow +
   ToF + gyro in obs, DR over flow-scale/dropout — publishable if it works, our seam already supports it.
10. **Measured end-to-end latency in DR.** Identify true latency incl. motor time constant (not just
    the 25 ms link) and bracket DR to the measured value (motor-delay sysID, arXiv 2404.07837).
11. **ESP-NOW ground dongle** — *only if* flight logs show WiFi jitter actually hurting. ESP-NOW is
    ~1-5 ms consistent vs WiFi-UDP's buffering spikes; a USB-CDC↔ESP-NOW dongle removes the router
    from the loop. Data-driven, not speculative.

## Declined (recorded so we don't relitigate)

- **NFC tag** — 1-4 cm read range; useless in flight. Landing-pad ID is better served by things we
  already have.
- **Stereo / dual cameras on the whoop** — one DVP interface per S3, no frame sync, no compute
  budget, blows the 32 g mass margin. Dead end.
- **External accelerometer module** — the FC's IMU accel over MSP is better-mounted, calibrated, and
  free. Leave the spare module in the drawer.
- **WiFi FTM localization** — ~1-5 m indoor error ≈ the whole 2-4 m arena. The fiducial rig (#4) is
  the position ground-truth.
- **ESP-side (Bluepad32) gamepad** — BLE/WiFi share one S3 radio (jitters the MSP link), moves
  safety off the dashboard. Only for a future Mac-less field mode.

## Key references

Blind/IMU: [LIO for racing](https://arxiv.org/abs/2210.15287) · [RAPTOR](https://arxiv.org/abs/2509.11481) · [accel+drag observability](https://arxiv.org/pdf/1509.03388) · [RMA](https://arxiv.org/abs/2107.04034).
Acro: [Deep Drone Acrobatics](https://arxiv.org/pdf/2006.05768) · [Crazyflie-Brushless sysID+backflip](https://arxiv.org/abs/2603.05944) · [TACO](https://arxiv.org/pdf/2503.01125).
Latency: [SimpleFlight](https://arxiv.org/html/2412.11764) · [motor-delay sysID](https://arxiv.org/pdf/2404.07837) · [Delay-Aware MDP](https://arxiv.org/pdf/2005.05440).
Flow/tiny sim2real: [neuromorphic flight (Sci Robotics 2024)](https://research.tudelft.nl/en/publications/fully-neuromorphic-vision-and-control-for-autonomous-drone-flight/) · [Learning to Fly in Seconds](https://arxiv.org/abs/2311.13081) · [Molchanov sim-to-multi-real](https://arxiv.org/pdf/1903.04628).
