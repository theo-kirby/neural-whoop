---
node_id: 2ed708fd-1073-5d0b-9d18-5a6da5505d1b
slug: floral-sunset-3918
title: 'Idea: interactive perturbations in the Studio — push the drone, gust it, drop a ball on it'
created_at: '2026-06-27T16:18:13.582335+00:00'
parents:
- wispy-dust-3157
summary: 'Idea (placeholder, not started): turn the Studio into a live stability sandbox where the user can physically disturb a flying policy mid-playback and watch it recover — click-drag an impulse/kick, fire a directional wind gust, or drop a rigid ball that bumps the drone. It is the intuitive, hands-on complement to the trained DR seam (which only covers disturbances seen in training), and it motivates a dedicated auto-stability objective. Requires upgrading the Studio from pre-recorded playback to a live interactive sim loop plus external-force/impulse and simple-contact hooks in WhoopDynamics.'
origin:
  backend: flywheel
  node_id: 2ed708fd-1073-5d0b-9d18-5a6da5505d1b
  slug: floral-sunset-3918
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: c10da9ed-a8b8-56fb-a546-383990a39098
  slug: dawn-scene-6335
  revision: 0
  pushed_at: '2026-08-09T21:26:51+00:00'
  content_sha256: 71fcb941e19d7ca6155cc94049e322903691d9bd4bad5137b02aa8a8cab50d1c
---
## Status: PLACEHOLDER (Studio feature, not started)

## Idea
Make the Studio a **stability sandbox**: while a policy flies, let the user inject arbitrary physical disturbances and watch recovery —
- **Push / impulse**: click-drag on the drone to apply a force/impulse (a kick).
- **Gust**: fire a directional wind burst of chosen magnitude/duration.
- **Drop a ball**: spawn a small rigid body that falls and bumps the drone (a simple contact/collision impulse).

This is the *intuitive* stability test — you feel how robust the policy is by trying to knock it down — complementing the trained DR seam (which only covers the disturbances seen in training).

## What it needs (bigger than the playback Studio)
The current Studio plays back a PRE-RECORDED rollout. This needs a **live interactive sim loop** (step the env in response to UI events) plus dynamics hooks for **external forces/impulses** and at least **simple contact** (the ball). DiffAero exposes the state; adding an external-wrench input to `WhoopDynamics` is the core new primitive. Likely shares the live-loop infra with the dynamic-DR-studio idea.

## Why it matters
Directly exposes how a racing policy (trained only to chase gates) behaves when shoved — motivating a dedicated auto-stability objective (see the stability branch). A racer may fly beautifully yet recover poorly from a hard external kick it never trained against.

## Lineage
- builds-on `e0d57844` (the Studio — needs upgrading from playback to a live interactive loop).