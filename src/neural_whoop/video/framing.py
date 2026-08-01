"""One framing per maneuver, derived from a measurement rather than typed into a shell.

The look (``neural_whoop.video.look``) is fixed for every clip in the repo. Exactly two quantities
are allowed to vary per clip, and both are *derived*:

* **how much framing room the shot needs** — from the worst measured separation between the ghost
  reference and the policy tracking it. That number is the result being reported, so a shot that
  guesses at it is not showing the result;
* **how much smoothing the follow rig may use** — from the maneuver's own periodicity. This one is
  a measured limit of the rig rather than a preference; see ``TRACK_SMOOTH`` below.

The plan is computed **once per maneuver, from that maneuver's comparison shot, and reused by all
three of its clips**. That is what makes the reference clip literally "the comparison with the
policy removed": same camera path, same airframe size, same horizon. Rendering the reference at the
look's own single-subject framing instead would put the same drone on screen at a different size in
two clips that are meant to be read against each other.

Pure stdlib — no numpy, no renderer, no simulator.
"""

from __future__ import annotations

from dataclasses import dataclass

from .look import VIDEO_LOOK
from .names import MANEUVERS

#: True airframe footprint (m), tip to tip — an Air65 II / 65 mm-class whoop measured across.
AIRFRAME_M = 0.082

#: Glyph exaggeration for a two-drone shot. The true 82 mm airframe against a divergence of order
#: 1 m is an 11:1 ratio, so a frame containing both drones renders each at ~3 % of frame height
#: (~30 px at 1080) — too small to read which way either one is rotating, which is most of what the
#: clip is for. The Studio already does this (~7x) for the same reason.
#: POSITIONS ARE UNTOUCHED: only the glyph is scaled, so every gap you see is the real gap.
GLYPH_SCALE = 3.0

#: The follow rig's resting subject height, in NDC. **Imported, not copied.** The framing algebra
#: below is a statement about where the look parks the subject, so a copy that silently disagreed
#: with the look would compute room for a shot nobody renders.
SUBJECT_Y: float = VIDEO_LOOK["subject_y"]

#: Per-maneuver smoothing half-window, with the reason. Absent -> the look's own value.
#:
#: The orbit is the measured exception and the reason this is a per-maneuver field rather than a
#: constant. The follow rig holds a constant offset from a *smoothed* subject track, and the look's
#: ``track_smooth = 20`` is a +-0.4 s window at 50 Hz. The orbit's revolution period is 0.898 s, so
#: that window averages very nearly a whole revolution: the smoothed track collapses onto the
#: circle's centre and the rig silently degenerates into a **tripod**, with the drone circling
#: toward and away from a stationary camera. It never leaves frame (worst |NDC| 0.65) — what it
#: fails is the other guarantee, apparent size, which swings 117%. At 6 (+-0.12 s, ~13% of a
#: revolution) the track actually follows the circle and the spread drops to ~10%.
#:
#: The look is deliberately NOT retuned to 6: that is a decision about every other clip in the repo.
#: Putting the exception here, with its number, is what keeps it out of a shell history.
TRACK_SMOOTH: dict[str, int] = {"orbit": 6}

TRACK_SMOOTH_REASONS: dict[str, str] = {
    "orbit": ("0.898 s revolution vs the look's +-0.4 s smoothing window: at track_smooth 20 the "
              "smoothed track collapses to the circle's centre and the follow rig degenerates "
              "into a tripod (apparent size swings 117%). 6 is +-0.12 s, ~13% of a revolution."),
}


def derive_drone_frac(separation_m: float, *, glyph_scale: float = 1.0,
                      margin: float = 1.15) -> float:
    """``--drone-frac`` that keeps BOTH drones in frame, derived from their worst separation.

    The look frames a single subject: it holds the airframe at 22 % of the frame height, which
    spans ~0.37 m of world — a tenth of what an overlay needs. Rather than eyeball a number per
    clip (the failure mode this whole module exists to prevent), derive it: the follow rig parks
    the subject at NDC :data:`SUBJECT_Y`, so a drone ``sep`` metres away sits at
    ``SUBJECT_Y - sep / (frame_height / 2)`` and has to stay inside |NDC| < 1 once padded by the
    airframe's own angular radius.

    Everything else still comes from the look. Only the framing room is clip-dependent, because
    only it depends on a quantity — how badly the policy diverges — that is the result itself.
    """
    pad_ndc = 0.08 * glyph_scale        # the drawn airframe's own half-width, in NDC
    room = max(0.15, 1.0 - abs(SUBJECT_Y) - pad_ndc)
    frame_height = margin * 2.0 * max(separation_m, 1e-3) / room
    return round(AIRFRAME_M * glyph_scale / frame_height, 4)


@dataclass(frozen=True)
class FramingPlan:
    """The derived, per-maneuver framing — every field a consequence of ``separation_m``.

    Frozen because it is a *record*: the same object is handed to all three of a maneuver's renders
    and then written into ``manifest.json``, so what shipped and what was measured are the same
    thing rather than two things that were supposed to match.
    """

    maneuver: str
    #: The measured worst on-screen separation between the ghost reference and the policy (m).
    separation_m: float
    #: ``--drone-frac``: the fraction of frame height the airframe fills. Derived from the above.
    drone_frac: float
    #: ``--scale``: the drawn airframe footprint (m) = the true 82 mm times the glyph exaggeration.
    render_scale_m: float
    glyph_scale: float
    #: ``--track-smooth``: the follow rig's half-window, in frames.
    track_smooth: int
    #: Why ``track_smooth`` is what it is — carried so the manifest explains itself.
    track_smooth_reason: str

    def flags(self) -> list[str]:
        """The derived flags, as argv. Nothing here was typed; everything was measured."""
        return [
            "--drone-frac", str(self.drone_frac),
            "--scale", str(self.render_scale_m),
            "--track-smooth", str(self.track_smooth),
        ]

    def to_dict(self) -> dict:
        """A JSON-able record for ``run.json`` / ``manifest.json``."""
        return {
            "maneuver": self.maneuver,
            "separation_m": self.separation_m,
            "drone_frac": self.drone_frac,
            "render_scale_m": self.render_scale_m,
            "glyph_scale_x": self.glyph_scale,
            "airframe_m": AIRFRAME_M,
            "track_smooth": self.track_smooth,
            "track_smooth_reason": self.track_smooth_reason,
            "note": ("one framing per maneuver, derived from that maneuver's COMPARISON shot and "
                     "reused by all three of its clips — so the reference clip is literally the "
                     "comparison with the policy removed: same camera path, same airframe size"),
        }


def plan_framing(maneuver: str, separation_m: float, *,
                 glyph_scale: float = GLYPH_SCALE,
                 track_smooth: int | None = None) -> FramingPlan:
    """The framing for every clip of ``maneuver``, from its comparison shot's worst separation.

    Args:
        maneuver: one of :data:`neural_whoop.video.names.MANEUVERS`.
        separation_m: the measured worst separation between reference and policy (m), from
            ``scripts/reference_vs_policy.py::build_overlay``'s ``max_separation_m``.
        glyph_scale: airframe exaggeration; positions are never scaled, only the drawn glyph.
        track_smooth: override the per-maneuver smoothing. Pass one only with a measurement.
    """
    if maneuver not in MANEUVERS:
        raise ValueError(f"unknown maneuver {maneuver!r}; expected one of {list(MANEUVERS)}")
    smooth = track_smooth if track_smooth is not None else TRACK_SMOOTH.get(
        maneuver, VIDEO_LOOK["track_smooth"])
    reason = (f"explicit override ({smooth})" if track_smooth is not None
              else TRACK_SMOOTH_REASONS.get(
                  maneuver, f"the standard look's track_smooth ({VIDEO_LOOK['track_smooth']})"))
    return FramingPlan(
        maneuver=maneuver,
        separation_m=round(float(separation_m), 4),
        drone_frac=derive_drone_frac(float(separation_m), glyph_scale=glyph_scale),
        render_scale_m=round(AIRFRAME_M * glyph_scale, 4),
        glyph_scale=glyph_scale,
        track_smooth=int(smooth),
        track_smooth_reason=reason,
    )
