---
node_id: 5b123fe7-b23a-57f2-b90f-0984dc9c42c6
slug: curly-dew-8661
title: 'Idea: Studio next — BLE Xbox gamepad (browser Web Gamepad API), real Air65 II chassis mesh, visual polish'
created_at: '2026-07-11T17:09:04.816619+00:00'
parents:
- fancy-rice-9295
- rapid-meadow-0957
- long-queen-3431
summary: 'Three self-contained dashboard/visual upgrades. (1) Gamepad: pair the Xbox pad to the Mac over BLE, poll navigator.getGamepads() in the existing 50 Hz send loop, map sticks → setpoint / CTBR override over the current websocket — zero firmware, dashboard stays the single arbiter + kill-switch. Chosen over the ESP-side Bluepad32 path (BLE/WiFi share one S3 radio → jitters the MSP link; moves safety off-dashboard). Added latency ~30-50 ms, fine for setpoint steering. (2) Chassis mesh: replace the procedural box glyph (drone-model.js) with the actual Air65 II GLTF/STL. (3) Visual polish: whatever raises the bench/player fidelity. Idea/setup.'
origin:
  backend: flywheel
  node_id: 5b123fe7-b23a-57f2-b90f-0984dc9c42c6
  slug: curly-dew-8661
  revision: 1
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 477dd529-eb40-59fb-ba8e-fe8bb333502e
  slug: purple-hat-6732
  revision: 0
  pushed_at: '2026-08-09T21:28:03+00:00'
  content_sha256: d3be3ac81bb0c5adfec9d60c140c930769203b99c32ff8cedecbb236ed371de6
---
# Idea: Studio next — gamepad + real chassis mesh + visuals

## 1. BLE Xbox gamepad — browser path (recommended)
Pair the pad to the Mac over BLE; in the dashboard's existing ~50 Hz send loop, sample `navigator.getGamepads()` right before each websocket send (it's a polling API — no axis events), map sticks → either a `hover` setpoint relocation (reuse the Live-tab click-to-relocate seam) or a direct CTBR override. No new firmware; the dashboard stays the sole arbiter (kill switch, mode logic, logging). Added latency ~8-16 ms BT + ≤20 ms poll + ~1 ms localhost ≈ 30-50 ms — irrelevant for setpoint steering, fine even for direct rate flying at 50 Hz.
**Rejected: ESP-side (Bluepad32).** The S3 is BLE-only and Bluepad32 supports it, but BLE+WiFi share one radio → coexistence jitter on the MSP link (the one thing we want clean), and it moves safety/arbitration off the dashboard. Only worth it for a future Mac-less field mode.

## 2. Real Air65 II chassis mesh
The Studio drone is a procedural THREE.js box (`web/studio/drone-model.js`) — no asset exists in `assets/` (only courses). Bring in a GLTF/STL of the actual Air65 II (or model it), swap the glyph, keep the per-drone tint + heading nav-lights + the gate-detection origin sphere. Self-contained; raises fidelity of every replay/live/bench view at once.

## 3. Visual polish
General bench/player fidelity (lighting, trails, HUD). Also the MP4-export 503 path (needs `../nw-viz` + node) could be smoothed. Grab-bag, low priority.

## Lineage
Parents: roadmap hub (Tier-2.5/2.6), the Unified Bench dashboard (the tooling these extend), and the Air65-II control/compute branch map (which already lists 'gamepad' as a branch).