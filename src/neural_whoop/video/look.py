"""The video look — one set of camera and stage values, used by every render in the repo.

This used to be two things: a plain ``LOOK_DEFAULTS`` and a ``PRESETS["hero"]`` bundle you opted
into with ``--preset hero``. The reference and comparison clips passed the flag; ``scripts/viz.py``
and the Studio's ``/api/export`` did not — they call ``capture_video.render()`` directly and never
went through the CLI at all — so the repo quietly shipped clips in two different environments, one
of them a walled room nobody had chosen on purpose.

Collapsing the two is why this module exists, and why it lives in the *package* rather than in
``scripts/``: ``render()``'s keyword defaults are pinned against it
(``tests/test_video_look.py::test_render_defaults_match_the_video_look``), so the direct callers get
the standardized look without either of them being edited, and the framing planner
(``neural_whoop.video.framing``) can import ``subject_y`` instead of hand-copying the number.

Pure stdlib — a dict literal and nothing else. Every entry carries the measurement behind it.
"""

from __future__ import annotations

from typing import Any

#: The standardized look. The point of it is that the SAME values give the same picture on any
#: replay — a hover, a flip, a gate lap, a two-drone overlay, a real flight log — because every
#: quantity that would otherwise be tuned per clip is *derived* instead:
#:
#:   * ``follow`` holds the airframe at a fixed fraction of the frame height and never re-orients,
#:     so apparent size and the horizon are constant by construction;
#:   * the stage is a fogged cyclorama sized from the camera's own standoff, so nothing in the
#:     background can sweep through frame as the camera travels and the floor never shows its edge;
#:   * the grid subdivision is chosen from the framing, so the drone reads as ~one tile rather than
#:     1/12 of a metre square, while the metre lines still say how big a metre is;
#:   * a steep key puts the cast shadow under the airframe, which is what sells ground contact.
VIDEO_LOOK: dict[str, Any] = {
    # --- the rig -------------------------------------------------------------------------------
    "shot": "follow",
    "theme": "dark",
    # drone_frac is the ONLY lever on framing room, and that is measured rather than assumed: at a
    # fixed drone_frac the standoff is 1/tan(fov/2), so tan(fov/2)*dist — the world-metres one NDC
    # unit spans at the subject — is CONSTANT, and a wider FOV buys exactly nothing. Worst |NDC|
    # across 34/40/46 deg went 0.54 -> 0.56 -> 0.58 (0.64 -> 0.68 -> 0.73 under the older
    # box+hard-clamp filter): it slightly WORSENS either way. So the room came from 0.26 -> 0.22, a
    # slight zoom-out, and this is also the first rung of the fallback ladder.
    "drone_frac": 0.22,
    # 34 -> 40 was bought purely for the flatter, less telephoto perspective — NOT for room.
    "fov": 40.0,
    "cam_dir": (0.85, 0.30, 1.0),
    "cam_dist": 1.15,
    # Smoothing is what SPENDS the room: more smoothing means more lead means more excursion.
    # 14 -> 28 cost worst |NDC| 0.54 -> 0.68 under the Hann window (0.64 -> 0.91 under the old box
    # window). 20 is the calm-but-affordable middle. NOTE the measured limit: this is a +-0.4 s
    # window at 50 Hz, so a periodic maneuver with a comparable period collapses the smoothed track
    # onto its own centre and the follow rig degenerates into a tripod — see
    # neural_whoop.video.framing, which carries a per-maneuver override for exactly that.
    "track_smooth": 20,
    # Slightly below centre, leaving headroom for a climb.
    "subject_y": -0.06,
    # The never-leaves-frame guarantee: how far (NDC) the subject may lead the smoothed camera
    # before the rig stops smoothing and pulls it back.
    "max_drift": 0.26,
    # --- tripod-only, kept so the shot stays switchable ------------------------------------------
    "cam_above": 0.30,
    "track_amount": 1.0,
    # --- the stage -------------------------------------------------------------------------------
    # None = derived. The grid pitch comes from the shot's own framing (web/studio/environment.js
    # ::STAGE_LOOK), and the fog from the camera standoff, which is what keeps the floor running
    # past its own fade at any scale.
    "grid_pitch": None,
    "grid_minor": None,
    "fog": None,
    # A steep key puts the cast shadow UNDER the airframe. The base rig's old (10, 18, 7) sat at
    # 0.68 of its altitude sideways, which at 1.5 m up throws the shadow a full metre clear of an
    # 82 mm drone — it reads as a second object rather than as ground contact.
    "key_dir": (0.22, 1.0, 0.15),
    # The light rig is tuned for a wide view; close up the light theme's near-white gridlines clip
    # to flat white without ACES tone mapping.
    "exposure": 0.95,
    # Keep the baked "1 METER" / "PROTOTYPE" text on the tiles. The grid's pitch is the scale
    # reference for a true-size airframe, and having the floor state its own pitch in words is
    # what makes an 82 mm drone legible in a still frame with nothing else in it.
    "room_labels": True,
    # No title/end cards: a card would make the frame-index-is-the-only-clock contract depend on
    # the card length, and the clips are concept shots, not a titled edit.
    "title_frames": 0,
}
