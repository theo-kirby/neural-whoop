---
node_id: e52ddbff-a2c5-5bc6-b8e9-1ec39cefbbfa
slug: fancy-rice-9295
title: 'Roadmap 2026-07-11: sensorless hover+acro polish, gamepad, richer sim, off-drone rig (research-grounded brainstorm)'
created_at: '2026-07-11T17:05:35.230986+00:00'
parents:
- still-flower-6355
- polished-band-7171
- shiny-violet-1747
summary: 'Planning hub after the first Bench-session wobble review. Synthesizes a repo stock-take + a SOTA sweep (blind/IMU-only hover, learned acro, latency-robust RL, optical-flow sim2real) + an off-drone hardware triage into a tiered plan. Headline: the FC''s own accelerometer (MSP_RAW_IMU msg 102, no new hardware) makes lateral velocity observable and is the #1 fix for the non-stationary hover. Tier-1 (this week, no hardware): accel-in-obs hover, action-history+smoothness (kills the 2.5Hz limit cycle), train the coded-but-untrained acro_flip, fiducial mocap for ground-truth XY. Doc: docs/ROADMAP.md @ d48eb3c.'
origin:
  backend: flywheel
  node_id: e52ddbff-a2c5-5bc6-b8e9-1ec39cefbbfa
  slug: fancy-rice-9295
  revision: 1
  exported_at: '2026-08-09T18:23:28+00:00'
---
# Roadmap brainstorm — 2026-07-11

Spawned by the user after the first Bench-dashboard flight session and the wobble review (parent: the wobble-decomposition node): *"get hover and acro working as best as possible without the new sensors"* plus a wishlist — BLE gamepad, heavier 5090 sims, dashboard/visual polish, the real chassis mesh, more SOTA research, other blind policies, and off-drone pieces (ground ESP, NFC, accelerometer, dual cameras).

Three parallel research streams fed this: a repo stock-take, a SOTA literature sweep, and an off-drone hardware-feasibility triage. Full writeup + references in **docs/ROADMAP.md (commit d48eb3c)**.

## The organizing insight
Most near-term wins need **no new hardware**. The PMW3901 flow + VL53L1X ToF are weeks out; almost everything below ships before they arrive.

## Tier 1 — this week, no new hardware (child hypotheses/ideas hang off this node)
1. **Accel in obs** — the FC accel is free over MSP_RAW_IMU; rotor drag makes lateral accel proportional to v_body, so velocity becomes observable. #1 SOTA fix for non-stationary hover.
2. **Action-history + action-rate penalty** — restores Markovness under delay AND is the documented cure for the 2.5 Hz limit cycle.
3. **Train acro_flip** — coded, never trained; blind is sufficient for a single attitude maneuver (Deep Drone Acrobatics ablation).
4. **Fiducial mocap** — webcam + ArUco → ground-truth XY; retires the pos-stub, makes drift measurable so we can prove Tier-1 works.

## Tier 2 — dashboard/UX glue
5. Browser gamepad (Web Gamepad API, not ESP-side). 6. Real Air65 II chassis mesh in Studio. 7. Pilot acro harness.

## Tier 3 — hardware-gated / bigger bets
8. GRU/RMA recurrent tiny-policy (RAPTOR: 2k-param recurrent flies 32g Betaflight). 9. Flow+ToF fuse-to-v_body when they arrive. 10. Measured end-to-end latency in DR. 11. ESP-NOW ground dongle if logs show jitter hurting.

## Declined (recorded so we don't relitigate)
NFC (cm range), stereo/dual whoop cameras (mass+compute), external accel module (FC accel is better+free), WiFi-FTM (error ≈ arena size), ESP-side gamepad (radio contention). See docs/ROADMAP.md.

## Lineage
Parents: the wobble-decomposition measurement (the problem this addresses), acro_flip (the agility beachhead Tier-1.3 trains), and the 'one module' hardware decision (the deploy-hw context Tier-3 builds on).