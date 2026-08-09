---
node_id: a7771cb2-47e1-5d24-a524-d32e49ced8c1
slug: long-sea-0577
title: 'Hypothesis: accelerometer in obs makes lateral velocity observable → station-keeping hover, no new hardware'
created_at: '2026-07-11T17:07:37.166573+00:00'
parents:
- delicate-credit-2979
- fancy-rice-9295
- polished-band-7171
summary: 'The non-stationary hover is architecturally unfixable from [roll,pitch,p,q,r] — lateral velocity is unobservable from gyro+attitude. But the FC''s accelerometer is free over MSP_RAW_IMU (msg 102), and on a multirotor rotor drag makes lateral specific-force ≈ k·v_body, so velocity IS observable from accel. Prediction: adding an accel channel (sim: specific-force + drag model, with bias/noise DR) converts the marching/drifting hover into a damped, station-keeping one — the #1 SOTA-recommended pre-flow-deck fix. Refutes the earlier ''IMU-only vertical/lateral needs the flow deck'' conclusion for the LATERAL axis specifically. Untested.'
origin:
  backend: flywheel
  node_id: a7771cb2-47e1-5d24-a524-d32e49ced8c1
  slug: long-sea-0577
  revision: 1
  exported_at: '2026-08-09T18:23:28+00:00'
---
# Hypothesis: accel-in-obs → observable velocity → station-keeping (stock hardware)

## Hypothesis
The deployed blind hover (d50var_s8, obs `[roll,pitch,p,q,r]×8`) is non-stationary because translational velocity is **unobservable** from gyro+attitude. The FC already measures acceleration (readable over `MSP_RAW_IMU`, msg 102, ~50-100 Hz). On a multirotor, blade-flapping/rotor drag makes lateral **specific force ≈ k·v_body** — so appending accel to the obs makes lateral velocity observable and should damp the drift, **before** the PMW3901/VL53L1X arrive.

## Setup (planned, 5090)
- DiffAero: synthesize accel = specific force + a rotor-drag term; DR over accel bias/noise/scale (honest sensor floor, per the R-ladder lessons).
- New `hover_accel` task/config (obs = attitude+rates+accel, or an accel-derived vel term).
- Pilot: extend `obs_from_msp` to read msg 102; relax `check_policy_family` (currently refuses base_obs_dim ≠ 5/6).
- Grade with the fiducial-mocap ground-truth XY (sibling idea) — this is what makes 'less drift' measurable rather than vibes.

## SOTA basis
- Learned inertial odometry from thrust+gyro flies racing laps IMU-only (Cioffi/Scaramuzza, RA-L 2023) — inputs almost suffice; accel + action-history is the max blind info.
- Accel+drag observability of velocity (arXiv 1509.03388, 1510.03249).
- RAPTOR (2025): a 2k-param recurrent policy flies 32g Betaflight quads — our exact hardware class.

## Honesty / risk
The v2 sweep RED showed honest gyro-noise DR re-breaks the open-loop VERTICAL trim; that verdict was about the vertical axis and white-noise modeling, not lateral velocity. This hypothesis targets the LATERAL axis via a physically-observable channel. Accel on a whoop is vibration-heavy — the DR fidelity (drag coefficient + noise spectrum) is the make-or-break.

## Lineage
Parents: roadmap hub (Tier-1.1), the wobble-decomposition measurement (the drift/march this predicts a fix for), and the CLOSED IMU-only campaign (whose 'needs flow deck for translation' handoff this partially reopens with zero hardware).