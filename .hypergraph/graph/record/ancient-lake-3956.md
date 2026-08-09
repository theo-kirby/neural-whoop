---
node_id: b7857e6f-7227-5ede-a5cb-22247594e328
slug: ancient-lake-3956
title: reference vs policy in ONE frame — and a framing check that can see the subject
created_at: '2026-08-01T15:16:53.229629+00:00'
parents:
- white-hat-1285
- calm-fog-9257
summary: 'scripts/reference_vs_policy.py merges the authored reference and the trained policy into a single 2-drone replay (ghost + solid) instead of two hero clips, because the hero follow rig derives its camera from each replay''s own track and so chases a falling policy back into frame. Needed no renderer work (playback.js already draws episodes[].drones[]) beyond an additive per-drone `style` hint. capture.js''s framing check now measures EVERY drone: on the first overlay the old hero-only check read a comfortable |NDC| 0.47 while the policy was 3.16 OUTSIDE the frame. GREEN, +10 tests, 398 pass. Commit eb00b91.'
origin:
  backend: flywheel
  node_id: b7857e6f-7227-5ede-a5cb-22247594e328
  slug: ancient-lake-3956
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Hypothesis

Not a hypothesis — a tool, built because the obvious way to answer "did the policy fly what we
authored?" is wrong in a way that flatters the policy.

## The problem

`scripts/reference_maneuver.py` renders the trajectory we WANT; `scripts/eval.py --record` renders
what a policy DID. Rendering both with `--preset hero` and putting them side by side is the obvious
comparison. It is also the wrong one: the hero preset's follow rig derives its camera from each
replay's **own** track. A policy that falls out of the sky is chased down by its own camera and
lands in frame looking composed. Each clip is individually honest; the comparison between them is
not.

## Setup

`scripts/reference_vs_policy.py` merges the two into a **single replay with two drones**. That
needed no renderer work — `web/studio/playback.js` has drawn the v2 `episodes[].drones[]` group
schema since the swarm tasks, and `web/capture/` imports it verbatim — plus three small additions:

- `viz/replay.py` grows an optional per-drone `style` render hint (additive, so version stays 2 and
  an older reader still gets a correct, merely monochrome, picture). Today's one key is `ghost`.
- `web/studio/drone-model.js` applies it. Materials are **cloned first**: the chassis prototype is
  shared by `proto.clone(true)` across every drone instance, so mutating in place would ghost the
  entire scene rather than one airframe.
- `web/studio/geometry.js` draws a ghost's trail in one muted colour — two turbo speed-ramps in one
  scene read as a single confusing gradient.

Three choices keep the comparison honest rather than flattering:

1. **The reference is `drones[0]`**, so `heroTrackIndex`'s track-0 fallback makes it the camera
   subject. The camera flies the IDEAL trajectory and the policy is seen deviating from it. Point
   the camera at the policy instead and every failure quietly re-centres itself.
2. **A policy that ends early simply stops.** The gap where it used to be is the result.
3. **The framing room is derived, not tuned** — from the measured worst separation between the two
   tracks, because that separation *is* the result and a per-clip eyeball would be the exact failure
   mode the `--preset hero` video contract exists to prevent. The preset itself is untouched.

## Results

`web/capture/capture.js`'s framing check now measures **every** drone, not just the hero. On a
single-drone replay it is the same number as before. On the first overlay built, the old hero-only
check reported a comfortable **worst |NDC| 0.47** while the policy was **3.16 outside the frame** —
it would have passed a video that hides its own subject. That is the concrete bug this node fixes.

The script also reports the numbers over the **maneuver window**, which turned out to matter more
than the video: see the sibling result node.

10 new tests pin the choices that could silently lie (reference is drone 0; `scene` stripped from
both tracks; an early-ending policy is not padded; a surviving policy is trimmed to the window and
never exceeds 100 %; the derived framing actually keeps both drones inside |NDC| < 1). 398 pass.

## Verdict / Honesty

GREEN as tooling. Two honest limitations:

- The overlay draws the airframe at **3x** true scale. At 82 mm against a ~1 m divergence, a frame
  containing both renders each at ~3 % of frame height (~30 px at 1080) — too small to read which
  way either is rotating, which is most of what the clip is for. **Positions are untouched**; only
  the glyph is scaled, so every gap shown is the real gap. It is recorded in `comparison.json`.
- The ghost/solid distinction is the only drone identity cue; there is no on-screen legend.

## Lineage

Parents: the `reference_track` method node (this is what makes its output *readable*), the first
reference_track results (which is what needed reading), and the reference-maneuver package that
authored the trajectories being compared against.
