---
node_id: ad026c75-660a-5e25-8f32-513b0413ebd4
slug: still-bar-6348
title: 'Idea: Quest 3 apartment scan → SDF obstacle env → same-room sim2real course'
created_at: '2026-07-04T08:38:10.528977+00:00'
parents:
- bitter-fire-0679
- long-queen-3431
summary: 'User idea (2026-07-04, owns a Meta Quest 3): scan the apartment with the Quest''s Scene Mesh, bake the mesh into a ~5 cm voxel SDF (a torch tensor — batched-GPU collision matching the env''s architecture), add an obstacle-field seam (termination + distance penalty + spawn validity), author the course YAML in apartment coordinates, and fly the SAME course in the SAME room — collapsing the Stage-3 sim↔real course gap to ~zero. GLTF doubles as the Studio/nw-viz backdrop (hero MP4s through the actual living room, pre-flight). Sub-ideas: Quest controller as a gate-authoring wand (touch a point → gate pose in scan frame — likely the answer to frame registration), MR ground station, Quest hand-tracking as the real counterpart of hand_follow/gesture_follow. Open problems: Scene Mesh export friction (needs an in-headset app with scene permission; photogrammetry fallback), ~2–3 cm scan accuracy, and drone-frame↔scan-frame registration (wand + known takeoff point). Recorded in docs/SIM2REAL.md @ b6c7b8e. Unscheduled — idea backlog; natural slot is alongside/after Stage 2.'
origin:
  backend: flywheel
  node_id: ad026c75-660a-5e25-8f32-513b0413ebd4
  slug: still-bar-6348
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 872b56b7-fa2a-5bf3-a6e3-bc3c5ffae796
  slug: small-band-6480
  revision: 0
  pushed_at: '2026-08-09T21:26:51+00:00'
  content_sha256: 72a8c4a3583c019aadaa8dcc5c7d33afd3433e3ff0a980f67b6020df5133a0ba
---
# Idea: Quest 3 apartment scan → SDF obstacle env → same-room sim2real course

**Origin.** User idea, 2026-07-04 (owns a Meta Quest 3). Jotted to the roadmap at their request; recorded in `docs/SIM2REAL.md` @ commit `b6c7b8e` (theo-kirby/neural-whoop).

**Hypothesis.** If the training environment's geometry IS the deployment room (Quest 3 scan → collision field in sim), the Stage-3 'real marked track' step loses its course-mismatch risk entirely: the policy trains against the walls, furniture, and ceiling it will actually fly between, and the sim course and real course are the same object in the same coordinates.

**Pipeline sketch.**
1. **Export:** Quest 3 Scene Mesh (depth-sensor room mesh) via a small in-headset app with scene permission → OBJ/GLTF. Fallback: walk-around video → photogrammetry/gaussian splatting on the 5090.
2. **Mesh → SDF:** bake a ~5 cm voxel signed-distance field as a torch tensor — batched, GPU-resident collision queries, matching the env's everything-batched architecture (no mesh-collision library needed).
3. **Env seam:** new obstacle-field seam — SDF-sampled termination + distance-based penalty + spawn-validity mask; course YAML authored in apartment coordinates. DR still applies on top (the room is fixed; the airframe/wind/latency aren't).
4. **Viz:** the GLTF becomes the Studio / nw-viz backdrop (three.js loads GLTF natively) → hero MP4s of the policy flying the actual living room before any real flight.
5. **Real flight:** branch-A offboard on the matching physical course.

**Sub-ideas.**
- **Gate-authoring wand:** Quest controller touch-points in the room → gate poses directly in the scan frame. Doubles as the likely solution to frame registration.
- **MR ground station:** telemetry/intent overlaid on the real drone through the headset.
- **Hand-tracking as real counterpart** of the existing `hand_follow`/`gesture_follow` tasks.

**Open problems (honesty).** Scene Mesh export friction (Meta gates the mesh behind an app with spatial-data permission — needs a small Unity/native exporter or a third-party tool; unverified which is least painful today); scan accuracy is ~2–3 cm class (fine for walls/furniture, marginal for gate-sized detail); **frame registration is the real work** — aligning the drone's world frame (flow-deck odometry origin) to the scan frame; wand-authored gates + a surveyed takeoff point is the current best answer. Nothing here is scheduled — it's idea backlog; the natural slot is alongside/after Stage 2 (closed-loop hover), before/with Stage 3.

**Lineage.** Parents: the control-path branch map `long-queen-3431` (the hardware-in-hand context this extends — an env-geometry branch orthogonal to the control-path branches) and the sim2real plan of record `bitter-fire-0679` (whose Stage 3 this de-risks). Related in-repo seams: course YAML / `neural_whoop.course`, the Studio Editor tab (gate authoring), `viz` GLTF backdrop, `hand_follow`/`gesture_follow` task family.