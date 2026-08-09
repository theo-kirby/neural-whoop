---
node_id: fd6a3569-382b-5af5-84bc-20fefc071387
slug: fragrant-hill-8742
title: 'Idea: dynamic DR testing in the Studio — live sweep of the disturbance seam during playback'
created_at: '2026-06-27T16:18:01.157550+00:00'
parents:
- wispy-dust-3157
- royal-firefly-3187
summary: 'Idea (placeholder, not started): replace the Studio''s binary DR on/off toggle with a live DR panel — per-seam sliders (wind, rate-gain, thrust-scale, action-latency, obs-noise, detector noise) that re-run the fixed-course rollout on change, so you can watch a policy hold or break as you sweep each disturbance and see which seam dominates. It is the interactive, visual version of the static DR-on reliability measurement, and pairs with the ad-hoc interactive-perturbation idea (this one sweeps the trained DR seam; that one applies arbitrary physical pushes). Sketch: expose DomainRandomizationConfig fields through the /api/rollout request and a frontend panel, optionally showing live aggregate completion/crash.'
origin:
  backend: flywheel
  node_id: fd6a3569-382b-5af5-84bc-20fefc071387
  slug: fragrant-hill-8742
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: ffb347bd-9653-5014-98fb-fc38ae7662f7
  slug: empty-mouse-7691
  revision: 0
  pushed_at: '2026-08-09T21:26:51+00:00'
  content_sha256: 297fb6d30c8536559ee600bbb9dd22f754d8fabcfdddd6c0c12280d194226696
---
## Status: PLACEHOLDER (Studio feature, not started)

## Idea
The Studio's `dr` toggle is binary and uses the default `DomainRandomizationConfig` magnitudes. Turn it into a **live DR panel**: per-seam sliders (wind accel, rate-gain frac, thrust-scale frac, action-latency steps, obs-noise std, and the detector seam) that re-run the fixed-course rollout on change, so you can *watch* a policy hold or break as you sweep each disturbance. Effectively an interactive, visual version of the DR-on reliability measurement (`8403a22c`) — turn the knobs, see where the policy falls apart, which seam dominates.

## Sketch
- `studio/rollout.py` already builds a `DomainRandomizationConfig`; expose its fields through the `/api/rollout` request and the frontend panel instead of a single bool.
- Optionally show live aggregate completion/crash next to the playback so the degradation is quantified, not just watched.
- Pairs naturally with the interactive-perturbation editor idea (ad-hoc impulses) — this one sweeps the *trained* DR seam; that one applies *arbitrary* physical pushes.

## Lineage
- builds-on `e0d57844` (the Studio — the surface this extends).
- builds-on `8403a22c` (DR-on reliability measurement — the static analysis this makes interactive).