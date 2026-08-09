---
node_id: 86970b83-e9b0-5833-97a2-5fc54a682d31
slug: hidden-field-0837
title: 'The concept shot, standardized: --preset hero (follow rig + cyclorama + framing-scaled grid) — apparent size 6.7→20.8% under the tripod becomes 20.4→28.9% fixed by construction'
created_at: '2026-07-31T19:20:56.863301+00:00'
parents:
- late-field-4005
summary: 'The tripod shot from `late-field-4005` got close at true scale but read as a security camera and needed hand-tuning per clip. Three things were wrong; all three are now DERIVED rather than dialled in. (1) Apparent size: a fixed camera watching a subject cross the room lets it balloon with range — measured 6.7 → 20.8% of frame height over this 1.1 m climb, a 3.1x swing. `--shot follow` holds a constant offset from a box-smoothed subject track, so size is fixed by construction at --drone-frac: measured 20.4 → 28.9% (1.4x, and that residual is only depth along the view axis). Because position and target translate together the camera''s ORIENTATION never changes, so the horizon is nailed and only the ground parallaxes past. (2) The room: walls+ceiling mean a corner and a seam sweep across any travelling shot; `--backdrop floor` is a cyclorama (floor alone, fogged out, sky gradient above the horizon), keeping ground + contact shadow. (3) The grid: an 82 mm airframe on a bare 1 m grid is 1/12 of a tile; the pitch stays an honest 1 m and gains a framing-sized fine mesh (10 cm here). `--preset hero` bundles it — the SAME invocation on any replay. `--shot fit` (viz.py, /api/export) byte-unchanged. GREEN as tooling. Commit 7fb3de9.'
origin:
  backend: flywheel
  node_id: 86970b83-e9b0-5833-97a2-5fc54a682d31
  slug: hidden-field-0837
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: ad9cd2d5-4a92-5350-a6bf-1a1d02d825c8
  slug: twilight-dream-8863
  revision: 0
  pushed_at: '2026-08-09T21:28:18+00:00'
  content_sha256: 21054a0a73856a0672e89c92f5c9b0fcbb163506e1dbce00071e0846987073fc
---
## Hypothesis

The concept render should be a **preset, not a per-clip tuning session**. If the hero look is going to run across a hover, a flip, a gate lap and a real flight log, then every quantity a human would otherwise dial in — camera distance, what stays in frame, how big the drone reads, how big the room is — has to be *derived from the shot itself*. A look you have to re-tune is not a look, it is a one-off.

The concrete complaint that opened this node: the v2 tripod render (`late-field-4005`, commit `518025c`) was better than the wide box fit but still "weird" — the camera felt off and the sizing was not right.

## Setup

Diagnosed by rendering the shipped v2 MP4 out to stills and measuring, rather than by eye. Three defects, each with a number:

1. **Apparent size is not controlled.** A tripod is a *fixed position* that pans to follow. The subject's range therefore changes as it crosses the room, and its apparent size changes with it: over this 1.1 m climb the airframe measured **6.7% → 20.8%** of frame height — a 3.1x balloon inside one 8-second clip. `--drone-frac` only ever pinned it at one instant.
2. **The background is the moving element.** With the camera parked and the subject travelling, the pan sweeps the *whole* background across frame — horizon, room corner, ceiling seam. That is what "the camera is weird" was: the drone is the still thing and the room is what moves.
3. **The grid cannot measure the drone.** An 82 mm airframe on a 1 m grid is **1/12 of a tile**, with nothing nearer to scale it against. True scale was honest and illegible at the same time.

Two cosmetic bugs fell out on the way: the greybox **walls rendered their baked text in mirror writing** (seen from inside, a `BackSide` face flips U — visible in the v2 hero still, which is looking at a wall, not the floor), and the Studio's key light sits 0.68 of the altitude sideways, which at 1.5 m up throws the cast shadow **a full metre clear of the drone** so it reads as a second object rather than as ground contact.

## Results

Commit `7fb3de9`. `--preset hero` = `--shot follow --backdrop floor --theme dark --drone-frac 0.26 --fov 34 --cam-dir 0.85,0.30,1.0 --track-smooth 14 --subject-y -0.06 --max-drift 0.26 --key-dir 0.22,1.0,0.15 --exposure 0.95 --title-frames 0`. An explicit flag still wins.

**`--shot follow` — the rig.** The camera holds a constant offset from a box-smoothed subject track. Consequences, both structural rather than tuned:

| | `fit` (locked off) | `tripod` (v2) | **`follow` (this node)** |
|---|---|---|---|
| apparent size, % of frame height | 3.3 → 4.7 | 6.7 → **20.8** | **20.4 → 28.9** |
| size swing | 1.4x | **3.1x** | **1.4x** |
| worst \|NDC\| (1.0 = frame edge) | 0.58 | 0.80 | **0.64** |
| camera orientation | fixed | **swings** | **fixed** |

Size is fixed *by construction* — the standoff is `scale / (2·tan(fov/2)·drone_frac)`, which does not reference the flight extent at all, so the number is the same on any replay. The residual 20.4→28.9 is only the subject's own motion along the view axis. And because position and target translate together, the camera's orientation is literally constant: the horizon is nailed to one place in the frame and only the ground parallaxes past.

The subject is deliberately *not* welded to centre. The anchor is the smoothed track, so the drone leads it through fast transients and settles back — a symmetric box filter is zero-phase, so it rounds corners without lagging a steady climb, which is exactly the "operator following" feel. `--max-drift` (NDC) caps the lead, so the flip's 360°/s roll cannot carry it out of frame. The whole track is precomputed, so `renderFrame(i)` stays a pure function of `i` — the reproducibility invariant the capturer is built on survives a *moving* camera.

**`--backdrop floor` — the cyclorama.** Floor alone, run out past the shot (33 m here), fading into the background under fog (1.0 → 8.3 m, derived from the standoff), with a sky gradient above the horizon whose horizon stop is exactly the flat background colour — so the fogged floor still fades seamlessly and only the empty upper half gains shape. No walls and no ceiling means no corner and no seam *can* sweep through a travelling frame. The ground and its contact shadow stay, which was the point of not just floating the drone on a gradient.

**The grid scales to the shot.** The pitch stays an honest **1 m** — that label *is* the scale reference, and shrinking it to "10 CM" only moves the problem — and gains a finer mesh sized to the framing (**10 cm** at this standoff). The drone now sits on a mesh you can read it against while the metre lines still say how big a metre is. A wide arena shot resolves the subdivision to "coarser than the tile", i.e. none, and is byte-identical to before.

**The two bugs.** Walls are now never labelled (the floor is the surface that carries the scale, and it reads correctly because it is a front-facing plane). A steep `--key-dir` puts the shadow back under the airframe. `--exposure` turns on ACES tone mapping, without which the light theme's near-white gridlines clip to flat white a metre from the lens — and leaving it unset means *no* tone mapping at all, so an existing render is untouched.

**The framing check now reports two numbers**, not one: worst `|NDC|` *and* the apparent-size spread. "Is the rig holding its framing?" is now measured rather than scrubbed for — the 3.1x tripod swing above is that instrument reading its own predecessor.

## Verdict / Honesty

**GREEN** as tooling. `pytest`: 274 passed, 1 pre-existing failure (`tensorboard` not installed on this Mac — identical on a stashed tree). `--shot fit`, which is what `scripts/viz.py --video` and `POST /api/export` use, is unchanged including tone mapping; `--track` still works as a spelling of `--shot tripod`.

Honest caveats:

- **You cannot see ground contact during the hover, and that is geometry, not a bug.** At a 0.59 m standoff with a 34° lens, the floor directly beneath a drone hovering at 1 m sits ~70° below the camera axis — far outside a 17° half-frame. The shadow is only ever visible near take-off and touchdown. No lens choice fixes this; a close shot of a small flying object simply cannot hold both the object and the ground a metre under it.
- **`follow` buys constant framing by giving up the trajectory.** You no longer see where the drone went — only what it is doing. `--shot fit` remains the right choice for a course/lap video, and that is why it is still the default rather than being replaced.
- **The drift clamp is C0, not C1.** When the subject crosses `--max-drift` the anchor starts tracking it, which is a velocity discontinuity in the camera. It is invisible at `track_smooth 14` on this sequence (checked frame-by-frame across the flip) but a harder manoeuvre could show it.
- **The look was chosen by eye from four variants**, not by any metric — lens 34/40/46°, camera height, and light vs dark. The variant sheet is attached so the choice is at least auditable. Dark won on contrast against the grey chassis; light is one flag away.
- **The trajectory is unchanged** from `late-field-4005` — this node is purely the renderer. It is still a *sim* trajectory (trained `acro_flip` owns the flip, a PD owns climb/hover/land, the real deploy split), not a recorded real flight.

## Lineage

- `late-field-4005` — the in-repo capturer and the tripod shot this supersedes; the parent whose 6.7→20.8% size swing is the number this node moves.
- `gentle-bonus-7668` — the greybox room + light/dark theme; `geometry.js` / `environment.js` gained the grid pitch, the wall-less cyclorama, the sky gradient and the fog override here, with the Studio's own look preserved by the defaults.
- `gentle-resonance-7390` — the CAD chassis that is the subject.

Artifacts: `before_after.png` (the same four phases under the tripod and under `--preset hero` — the whole result in one image), `takeoff_flip_land.mp4` (the re-render, 1080×1080, 8.2 s), `hero_still.png` (mid-flip), `shot_variants.png` (the four candidate looks that were compared), `run.json` (manifest, with the derived standoff / grid / fog values and all three shots' framing numbers).