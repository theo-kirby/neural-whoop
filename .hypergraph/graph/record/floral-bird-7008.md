---
node_id: df74f163-c1ee-567e-bc44-7f54d18a976c
slug: floral-bird-7008
title: 'Idea: cheap fiducial mocap (webcam + ArUco) — ground-truth XY that retires the pos-stub and grades every sensorless fix'
created_at: '2026-07-11T17:08:39.931725+00:00'
parents:
- fancy-rice-9295
- rapid-meadow-0957
summary: 'The highest-value item in the hardware triage, and it needs NO drone hardware. One fixed webcam (or iPhone Continuity Camera) + a 6-8 cm ArUco/AprilTag on top of the whoop + OpenCV solvePnP gives ~0.5-2 cm lateral position at 30 fps in our 2-4 m bench volume. It replaces the vertical-only pos stub in flight_report.py''s replay (giving Studio real trajectories AND a true sim-vs-real position metric), and — critically — it makes hover DRIFT measurable, so the accel-in-obs and smoothness hypotheses can be PROVEN rather than eyeballed. Do it early; it grades everything else. Gotchas: planar-pose flip (use IPPE_SQUARE + reprojection-error pick or a 2x2 miniboard), motion blur (high shutter + bright light), depth error 2-5x lateral (mount camera perpendicular to the axis you care about). Idea.'
origin:
  backend: flywheel
  node_id: df74f163-c1ee-567e-bc44-7f54d18a976c
  slug: floral-bird-7008
  revision: 1
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 7dfb57af-34b2-556c-ac0f-d94619e0c0b9
  slug: lively-mud-3192
  revision: 0
  pushed_at: '2026-08-09T21:28:03+00:00'
  content_sha256: f8f5beb6934acd4b084e906152ce65d733690505192d2283d175d4d30c92c99e
---
# Idea: fiducial mocap ground-truth rig (Mac-only)

## Why this is the backbone
We currently have no ground-truth position — real-flight replay `pos` is a vertical-only ∫vz_est stub, so 'the hover drifts' is unquantified and sim-vs-real has no position metric. A fiducial rig fixes all of that with a webcam and a printed tag, before any flow/ToF hardware.

## Recipe (validated pattern)
- One fixed 1080p webcam (or iPhone via Continuity Camera), calibrated once (checkerboard).
- A **6-8 cm** ArUco (`DICT_4X4_50`) or AprilTag (`tagStandard41h12`) flat on TOP of the whoop (~1 g on foam/paper).
- `cv2.aruco` / `pupil-apriltags` detect → `solvePnP` (`SOLVEPNP_IPPE_SQUARE`) → timestamped (t, x, y, z).
- Accuracy: lateral ~0.5-2 cm, depth 2-5× worse; 30 fps end-to-end easy on the Mac.

## Integration
Write the (t,x,y,z) CSV alongside the pilot flight CSV; feed it into `flight_report.py` to replace the pos stub → Studio shows real trajectories, and we get a quantitative sim-vs-real position error + a real drift/station-keeping metric to grade the accel-in-obs and action-smoothness fixes.

## Gotchas
(1) single-tag planar-pose ambiguity — IPPE_SQUARE + pick-by-reprojection-error, or a 2x2 miniboard; (2) motion blur / rolling shutter — force high shutter + bright light; (3) depth error → mount the camera perpendicular to the axis you most care about; (4) one camera = pose only while the tag faces it — add a 2nd webcam later to fuse for full-volume coverage. Rejected alternatives (WiFi-FTM ~1-5 m ≈ arena size; Lighthouse trackers 10× the AUW) documented in the hardware-triage sibling.

## Lineage
Parents: roadmap hub (Tier-1.4), and the Unified Bench dashboard (the real-drone tooling this measurement rig plugs into).