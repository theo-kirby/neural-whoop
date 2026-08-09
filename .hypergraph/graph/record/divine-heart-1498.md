---
node_id: bffd7589-0ddb-573b-9621-ba3d79f3a654
slug: divine-heart-1498
title: 'Camera: Hann window + a soft tanh drift limiter — worst |NDC| 0.64 → 0.54 at matched settings, and the measurement that kills FOV as a framing lever'
created_at: '2026-07-31T20:59:38.727281+00:00'
parents:
- hidden-field-0837
summary: 'Two rough edges left on --preset hero, both now closed, plus one corrected assumption. (1) boxSmooth -> smoothTrack, a raised-cosine (Hann) window: both windows are zero-phase, but a box''s weights step w->0 at the edge so every sample entering/leaving kicks the smoothed velocity — a visible tick over the flip''s roll. (2) The hard drift clamp min(|d|,lim) becomes lim*tanh(d/lim), removing the C0 velocity discontinuity recorded as a known caveat on the parent. At MATCHED settings the two together move worst |NDC| 0.64 -> 0.54 and the apparent-size spread 20.4-28.9% -> 21.3-25.6%: calmer AND better framed on the same budget. Preset retuned fov 34->40, drone_frac 0.26->0.22, track_smooth 14->20; net on the same replay 0.64 -> 0.56 worst |NDC|, size 20.4-28.9% -> 17.6-23.3%. CORRECTED ASSUMPTION: at fixed drone_frac the standoff goes as 1/tan(fov/2), so tan(fov/2)*dist is CONSTANT and a wider FOV buys exactly ZERO framing room — it slightly WORSENS it. Worst |NDC| across 34/40/46 deg: 0.64/0.68/0.73 under the old box+hard-clamp filter, 0.54/0.56/0.58 under the new one; same sign either way. --drone-frac is the only lever on room; fov buys perspective alone. And smoothing is not free calm: 14->28 cost 0.64 -> 0.91 under the box window and 0.54 -> 0.68 under Hann — tamed, not free. GREEN as tooling, 297 passed. Commit 2fe7faf.'
origin:
  backend: flywheel
  node_id: bffd7589-0ddb-573b-9621-ba3d79f3a654
  slug: divine-heart-1498
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: e68665c7-f72b-576f-8c52-669161cb48b9
  slug: black-resonance-4131
  revision: 0
  pushed_at: '2026-08-09T21:28:18+00:00'
  content_sha256: fa8a0717e1ba888892a191aa4884c4dfb8cd6a1bf4126a1e511929c593fa17f3
---
## Hypothesis

The parent (`hidden-field-0837`) shipped `--preset hero` and left two things on the table, one of which it recorded against itself as a caveat:

> **The drift clamp is C0, not C1.** When the subject crosses `--max-drift` the anchor starts tracking it, which is a velocity discontinuity in the camera. It is invisible at `track_smooth 14` on this sequence but a harder manoeuvre could show it.

The hypothesis here is that "a smoother camera" is not bought by *more smoothing* — it is bought by a **smoother filter kernel and a smoother limiter**, at the same drift budget. More lag is a cost, not a feature.

## Setup

One replay throughout — `runs/acro_flip/hero_seq/replay.json.gz`, the take-off → flip → land sequence — so every number below is comparable. The instrument is the capturer's own framing check, which reports worst `|NDC|` (1.0 = frame edge) *and* the apparent-size spread; that instrument was built by the parent precisely so this kind of change could be measured rather than eyeballed.

Three changes, in `web/capture/capture.js` and `scripts/capture_video.py`:

1. **`boxSmooth` → `smoothTrack`, a raised-cosine (Hann) window.** Both windows are zero-phase, so `renderFrame(i)` stays a pure function of `i`. The difference is the *second* derivative: a box's weights jump from `w` to 0 at the window edge, so every time a track sample enters or leaves the window the smoothed velocity takes a step. Hann's weights taper to zero, so samples fade in and out and the acceleration stays continuous. Hann's effective width is ~half the box's at the same half-window, so it is if anything *gentler* on the lead/lag excursion.
2. **Hard clamp → soft `tanh` limiter.** `min(|d|, lim)` has a derivative that steps 1 → 0 the instant the drift saturates — a kink in the camera's velocity, arriving exactly during the fastest part of the shot. `lim·tanh(d/lim)` has the two properties we actually wanted: it is the identity for small drift (`tanh(x) = x − x³/3 + …`, so ordinary lead/lag is untouched) and it asymptotes to `lim` — while being smooth everywhere. It also never quite *reaches* `lim`, which makes the cap a true bound rather than a wall.
3. **`PRESETS["hero"]` retuned:** `fov` 34 → 40, `drone_frac` 0.26 → 0.22, `track_smooth` 14 → 20.

## Results

Commit `2fe7faf`. All on the same replay:

| | fov | drone_frac | track_smooth | window | limiter | worst \|NDC\| | size, % frame height | ratio |
|---|---|---|---|---|---|---|---|---|
| hero v1 (parent) | 34 | 0.26 | 14 | box | hard | **0.64** | 20.4–28.9 | 1.42 |
| **filter change only**, matched settings | 34 | 0.26 | 14 | **hann** | **tanh** | **0.54** | 21.3–25.6 | **1.20** |
| **hero v2** (shipped) | 40 | 0.22 | 20 | hann | tanh | **0.56** | **17.6–23.3** | 1.32 |

The middle row is the honest isolation of the filter work: **0.64 → 0.54 worst |NDC| and a 1.42 → 1.20 size ratio, changing nothing a user passes.** Calmer and better framed on the same budget, which is what the hypothesis predicted. The bottom row then spends part of that back on room and calm.

### The measurement that corrects an assumption

The intuition going in was "a wider lens gives the subject more room to move in frame". **That is false here, and the reason is structural.** At a fixed `--drone-frac` the standoff is `scale / (2·tan(fov/2)·drone_frac)` — so `tan(fov/2)·dist`, which *is* the metres of world one NDC unit spans at the subject, is **constant in fov**. A wider FOV backs the camera off by exactly the amount it widens.

Measured twice, once under each filter — the magnitudes differ, the **sign does not**:

| fov | 34° | 40° | 46° |
|---|---|---|---|
| worst \|NDC\|, box + hard clamp (old preset framing) | 0.64 | 0.68 | 0.73 |
| worst \|NDC\|, hann + tanh (`drone_frac 0.22`, `track_smooth 20`) | 0.54 | 0.56 | 0.58 |

It does not merely fail to help — it slightly *worsens*, from the shorter standoff's stronger perspective. So `--drone-frac` is the **only** lever on framing room; `fov` is bought purely for how flat or telephoto the perspective reads. That is now a comment in both files, because it is exactly the kind of thing that gets re-derived wrongly.

The symmetric finding: **smoothing is not free calm.** More smoothing means more lead means more excursion. `track_smooth` 14 → 28 at `drone_frac 0.26` cost worst |NDC| **0.64 → 0.91** (size spread 19–40%) under the box window, and **0.54 → 0.68** (20.4–30.7%) under Hann — so the new window *tames* the penalty rather than removing it. Hence 20, not 28; the sensitivity is attached (`track_smooth` 16 → 0.51, 20 → 0.56, 24 → 0.59) so the tradeoff is visible rather than asserted.

## Verdict / Honesty

**GREEN** as tooling. `pytest`: 297 passed, 1 pre-existing failure (`tensorboard` not installed on this Mac — identical on a stashed tree, and the same failure the parent recorded).

Honest caveats:

- **0.56 misses the 0.55 target I set myself**, by one hundredth. `track_smooth 16` would land 0.51 with a *tighter* size spread (17.8–22.1%); 20 was kept because the extra calm is the point of the change and the miss is inside the noise of "which frame is worst". Named here rather than rounded away.
- **"Calmer" is argued from the kernel, not measured.** The framing check measures *excursion*, not jerk. The claim that Hann + tanh look smoother rests on the C1/C2 argument above plus the size-ratio drop (1.42 → 1.20); nobody has computed a jerk spectrum, and no A/B was shown to a human.
- **The two fov rows are not a like-for-like pair.** The box row was measured during the earlier session at the *old* preset framing; the hann row at the new one. They are reported separately for that reason — the claim they jointly support is the sign of the trend, not the magnitudes.
- **All numbers are from ONE replay.** The preset's whole premise is portability across clips, and this change has only been re-measured on the take-off/flip/land sequence. A gate lap or a real flight log could land differently.
- **The tanh limiter slightly tightens the effective cap** (it approaches `lim` instead of reaching it), so a like-for-like `--max-drift` now permits marginally less lead than it used to. Left as-is: it moves in the safe direction.
- **The parent's other caveats stand unchanged** — `follow` still trades away the trajectory, and ground contact still cannot be seen during a hover at this standoff.

## Lineage

- `hidden-field-0837` — `--preset hero` itself; this node closes the C0-clamp caveat that node recorded against itself, and retunes the preset it established.
- `late-field-4005` — the in-repo capturer and the framing-check instrument all of these numbers come out of.

The re-rendered concept video is attached; the trajectory is unchanged (still the v1 obs-7 `acro_flip` policy), so this is purely the renderer — and that same v1 trajectory is what `pleasant-*`/the acro_flip v2 sibling node sets out to replace.

Artifacts: `takeoff_flip_land_v3.mp4` (the re-render under the new rig, 1080×1080), `framing.csv` (every variant measured, including both fov sweeps and the track-smooth sensitivity), `run.json` (manifest: git SHA, the full preset before and after, and the framing check for each variant).