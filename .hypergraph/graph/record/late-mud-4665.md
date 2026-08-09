---
node_id: ca2598a4-5354-5b74-b557-7ef6b279a7ca
slug: late-mud-4665
title: 'Design: flow-velocity DR seam — model host-side optical-flow velocity error (vel_body sim2real)'
created_at: '2026-06-29T09:45:13.848994+00:00'
parents:
- bitter-fire-0679
summary: 'Idea/design: vel_body in obs-v4 will come from a PMW3901+ToF flow deck fused to body velocity host-side, so sim must train against realistic flow-velocity error. Add a new DR seam in randomization.py — the velocity counterpart to perception''s DetectorNoise — modeling flow dropout over low-texture floors, height-coupling via ToF, scale error, and estimator latency. Design node; not yet implemented. Closes the one obs-v4 channel the chosen camera+flow hardware can''t deliver cleanly.'
origin:
  backend: flywheel
  node_id: ca2598a4-5354-5b74-b557-7ef6b279a7ca
  slug: late-mud-4665
  revision: 5
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 9e71ec8b-9888-5187-84fc-a57e3c8bd3da
  slug: autumn-dust-5568
  revision: 0
  pushed_at: '2026-08-09T21:26:36+00:00'
  content_sha256: 13aa3de56f0cc690d7bc1c6505db4aae71ec45c9a4429b3bd1b438f27df63175
---
# Flow-velocity DR seam

**Idea.** The Mobula6+camera choice gives `target_rel` (gate detector) but no clean velocity; we get `vel_body` from an optical-flow deck (PMW3901 + ToF) fused on the host. Real flow velocity is noisy and fails in characteristic ways, so the policy must train against that error model — otherwise the sim feeds it ground-truth velocity it won't have in the air.

**Design (planned).** New DR seam in `randomization.py`, the velocity-side counterpart to perception's `DetectorNoise`:
- flow **dropout / degradation over low-texture surfaces** (stale-hold like the detector miss path);
- **height-coupling**: flow->velocity scale depends on ToF range; model ToF noise + range limits (~80mm-inf);
- **scale / bias error** and per-axis noise;
- **estimator latency** (folds into the action/obs latency budget).
Apply to the `vel_body` channels of the obs. Mirror the DetectorNoise structure so the two seams compose.

**Verdict.** Open / not started — design to be fleshed out with the user.

**Lineage.** Child of the sim2real plan (bitter-fire-0679); methodological sibling of the perception-cluster DetectorNoise work (the camera-side seam). Real flow-error statistics get calibrated in Stage 1.