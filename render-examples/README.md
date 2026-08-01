# render-examples — what this renderer produces

Nine clips: **three maneuvers × three video kinds**. They are here so "show me what this looks
like" needs no GPU, no policy checkpoint, and no `capture` extra — just a browser or a video
player.

Regenerate with:

```bash
uv run python scripts/render_examples.py --dry-run    # print the nine argv lines, render nothing
uv run python scripts/render_examples.py --publish    # 1080² masters + these 720² copies
```

`runs/` is gitignored, so a fresh clone has none of the inputs. The script names the exact command
that produces each missing one rather than raising a `FileNotFoundError`.

---

## The nomenclature

A clip is named **`<maneuver> maneuver <kind> video`** and nothing else. The filename is the same
thing with underscores: `<maneuver>_maneuver_<kind>.mp4`. Both come from
`src/neural_whoop/video/names.py`, which raises on an unknown maneuver or kind so a typo cannot
quietly invent a fourth convention.

| kind | what is in it |
|---|---|
| **`reference`** | The hand-authored trajectory alone — *"this is the one we want."* No policy, no training, and **no simulator**: pure numpy out of `scripts/reference_maneuver.py`, where every physical quantity (attitude, body rates, collective, the IMU's specific force) is *derived* rather than guessed. |
| **`policy`** | What a trained policy actually flew, from the **zero-RSI eval twin** (`configs/reference_track_*_eval.yaml`, `rsi_frac: 0`) — the only honest rollout, since it starts at phase 0 and flies the whole maneuver instead of resuming mid-flight from the reference's own state. |
| **`comparison`** | Both at once, in a single two-drone replay: the reference as a translucent **ghost**, the policy solid beside it. The gap between them is the result. |

### Why the camera flies the reference

In the comparison, the reference is `drones[0]` and therefore the camera's subject. That is a
deliberate choice and it is the whole reason the comparison is worth making.

The follow rig derives its camera from the subject's **own** track. Point it at the policy and a
policy that falls out of the sky is chased down by its own camera and lands in frame looking
composed — the clip is individually honest and the comparison it supports is not. Pointing it at
the *ideal* path instead means deviation is visible as deviation: the policy drifts within the
frame, and a policy that terminates early simply stops while the reference plays on. Neither track
is padded, because the gap where the policy used to be *is* the finding.

(`playback.js::heroTrackIndex` picks, for a gateless task, the drone closest to its own
`scene.target`, falling back to track 0. The overlay carries **no `scene` channel at all**, so the
reference — written first — deterministically wins. Dropping `scene` is also what keeps the picture
legible: the follow-task target marker is a metre-scale sphere, and with the camera sitting on it,
it fills the entire frame.)

### One word that is deliberately **not** renamed

**"hero" is retired from the video vocabulary.** There is no `--preset hero`, no `hero.mp4`, and no
`hero_takeoff_flip_land.py`.

The replay schema's **hero drone** / **hero episode** / `heroFrames` / `--n-heroes` are a different
word with a real meaning — *the recorded subject drone*, the one whose full per-step frames were
kept — documented in `docs/VISUAL_CONTRACT.md`, and they **stay**. Please do not "finish" the
rename into the schema; it would change a wire format to fix a word that is not broken there.

---

## The environment

Every clip in this directory, and every frame the Studio dashboard draws, uses **one** environment.
There is no second look and no flag that selects one.

* **A fogged cyclorama.** A greybox "prototype map" floor fading into the background under scene
  fog, with a sky gradient above the horizon. **No walls, no ceiling** — a bounded box put a corner
  and a ceiling seam in shot the moment the camera moved.
* **Derived, never dialled.** `environment.js::setStage` takes the shot's camera distance and picks
  the fog fade from it, the floor's size from the fog (4× the fade), and the grid's fine
  subdivision from the framing. The floor's own edge is therefore always well past the point it has
  faded to background — "you can never see the stage end" is true by construction, at any scale.
* **One light rig**, with a steep key so the cast shadow sits *under* the airframe rather than a
  metre clear of it, and a shadow map refitted to the flight — the default ±30 m arena ortho gives
  an 82 mm drone about 1.4 texels, i.e. no contact shadow at all.
* **An honest 1 m grid**, with the pitch baked into the tiles as text, plus a finer mesh sized to
  the framing so the airframe sits on something it can be read against.
* **A true 82 mm airframe** — the real Air65 II footprint, not the Studio's ~7× glyph. In these
  clips it is drawn at **3×** (`--scale 0.246`) because a frame holding both drones renders each at
  ~3% of frame height otherwise, too small to read which way either one is rotating.
  **Positions are untouched.** Only the drawn glyph is scaled, so every gap you see is the real gap.

---

## The framing

One framing plan **per maneuver**, derived from that maneuver's **comparison** shot, and reused by
all three of its clips. That is why the reference clip is literally the comparison with the policy
removed: same camera path, same airframe size, same horizon. All three replays are cut from the one
overlay document.

The rule the plan exists to enforce is **no hand-typed flag, ever**. Every flag is derived from one
measured quantity and recorded in `manifest.json`:

| maneuver | worst separation | `--drone-frac` | `--track-smooth` |
|---|---|---|---|
| flip | 0.5449 m | 0.1374 | 20 |
| swing | 0.2014 m | 0.3717 | 20 |
| orbit | 0.3171 m | 0.2361 | **6** — see below |

Measured on the shipped clips (worst `\|NDC\|` is 1.0 at the frame edge, over **every** drone;
apparent size is the subject's on-screen height as a fraction of frame height):

| clip | worst \|NDC\| | apparent size | spread |
|---|---|---|---|
| `flip_maneuver_reference` | 0.25 | 11.7–12.1% | 3% |
| `flip_maneuver_policy` | 0.22 | 11.8–12.2% | 3% |
| `flip_maneuver_comparison` | 0.66 | 11.7–12.1% | 3% |
| `swing_maneuver_reference` | 0.49 | 30.7–34.7% | 13% |
| `swing_maneuver_policy` | 0.49 | 30.6–34.7% | 13% |
| `swing_maneuver_comparison` | 0.71 | 30.7–34.7% | 13% |
| `orbit_maneuver_reference` | 0.26 | 20.2–20.9% | 3% |
| `orbit_maneuver_policy` | 0.26 | 20.2–20.9% | 3% |
| `orbit_maneuver_comparison` | 0.46 | 20.2–20.9% | 3% |

A comparison's larger `|NDC|` is the ghost-to-policy gap — the result being shown — not a worse
shot. The identical size column within each maneuver is the shared plan doing its job.

### The orbit needs `track_smooth 6`, and that is a measurement

The follow rig holds a constant offset from a **smoothed** subject track, and the standard
`track_smooth = 20` is a ±0.4 s window at 50 Hz. The orbit's revolution period is **0.898 s**, so
that window averages very nearly a whole revolution: the smoothed track collapses onto the circle's
centre and the rig silently degenerates into a **tripod**, with the drone circling toward and away
from a stationary camera. It never leaves frame — what it fails is the *other* guarantee.

| orbit reference clip | worst \|NDC\| | apparent size | spread |
|---|---|---|---|
| standard single-subject framing, `track_smooth 20` | 0.65 | 13.9–30.2% | **117%** |
| this maneuver's plan, `track_smooth 20` | 0.46 | 18.1–23.7% | 31% |
| **this maneuver's plan, `track_smooth 6`** (shipped) | 0.26 | 20.2–20.9% | **3%** |

The standard look is **not** retuned to 6 — that is a decision about every other clip in the repo.
The exception lives in `video/framing.py::TRACK_SMOOTH` with its reason attached, so it travels
with the maneuver and lands in every manifest rather than in someone's shell history.

---

## Provenance

Everything below is also in `manifest.json`, per clip, with the full argv.

| maneuver | reference (authored) | policy | tracking over the maneuver window |
|---|---|---|---|
| **flip** | `runs/reference/flip_roll_z09_deployable` — the `--deployable` variant, whose coast runs at the 0.25 deploy throttle floor instead of motors-off | `runs/reference_track_flip_v2` (`configs/reference_track_flip_v2_eval.yaml`) — **v2**, the arm that completes the maneuver | 110 steps, 100% completed, pos err **0.420 m**, att err **2.44°** |
| **swing** | `runs/reference/swing_roll` — authored entirely by differential flatness, **no shoot**; closes on its own start point at machine precision | `runs/reference_track_swing` (`..._swing_eval.yaml`) | 268 steps, 100% completed, pos err **0.114 m**, att err **1.92°** |
| **orbit** | `runs/reference/orbit_z_fixed` — the first genuinely 3D maneuver, the one that breaks `ψ ≡ 0` | `runs/reference_track_orbit` (`..._orbit_eval.yaml`) | 223 steps, 100% completed, pos err **0.172 m**, att err **6.82°** |

Two notes on those choices, since both are the kind of thing that looks arbitrary later:

* **The flip's policy is v2, not the original `reference_track_flip`.** v2 is the arm that reaches
  every phase; the v1 arm never completes the maneuver, so a clip of it would show a failure mode
  rather than a comparison. The v1 result is not hidden — it is the `reference_track` flip node's
  finding — it is just not what an *example* clip should be.
* **The orbit's reference is `orbit_z_fixed`, not `orbit_z`.** The two are byte-identical in
  trajectory (`pos`, `quat` and `omega` all compare equal — the authoring is pure numpy and never
  touched the simulator); only `verify.json`'s rate-loop verdict differs, because `orbit_z` predates
  the 2026-08-01 controller fix and says the maneuver was not flyable. Pointing at the post-fix
  artifact keeps the shipped clip's provenance chain from running through a file that contradicts it.

All three policies survive to the episode cap (`ended: max_steps`), so `completed_fraction` is 1.0
in every case. The clips are trimmed to the **maneuver window** — 110 / 268 / 223 steps against a
499-step episode cap — because the remainder is a hold-station tail, and averaging a per-step metric
over it makes a surviving policy beat a crashed one for the wrong reason.

---

## Known limits

* **These are 720×720, CRF 26 transcodes**, so the whole set fits in a git history (~3–4 MB). The
  1080×1080 masters live in gitignored `runs/render_examples/`; re-render them with
  `scripts/render_examples.py`.
* **The clips are silent, un-titled and un-graded.** `title_frames` is 0 on purpose: a card would
  make the "frame index is the only clock" contract depend on the card length.
* **`policy` and `comparison` are rollouts of one seed, one episode** (the eval twin's episode 1).
  They are illustrations, not statistics — the numbers that carry weight are in the runs' own packs
  and Flywheel nodes, not here.
* **The reference clip drops the ghost styling** the comparison gives it. Translucency is a hint
  about which of *two* drones is the target; alone, the reference is simply the subject. The
  framing — camera path, airframe size, horizon — is unchanged, which is the part that has to match.
* **The `swing` spread is 13%, the largest of the nine.** That is the follow rig's residual depth
  swing along the view axis on a maneuver that travels; it is within spec (<35%) and no rung of the
  fallback ladder was taken.
