"""Video: one look, one render entry point, one vocabulary.

Not under ``reference/`` on purpose — a *comparison* video is not a reference concept, and
``scripts/viz.py`` and the Studio's ``/api/export`` are renderers too. This package is what all of
them share:

* :mod:`~neural_whoop.video.look` — ``VIDEO_LOOK``, the standardized camera + stage. It is the
  *default*, not a preset, so a caller that never touches a flag still gets the shipped picture.
* :mod:`~neural_whoop.video.names` — ``<maneuver> maneuver <kind> video``, and the filename rule.
* :mod:`~neural_whoop.video.framing` — one derived framing per maneuver, reused by all its clips.
* :mod:`~neural_whoop.video.render` — the one invocation, and the framing check it records.

Every module here is pure stdlib: no torch, no numpy, no renderer. The heavy work lives behind
``scripts/capture_video.py`` (the ``capture`` extra), which this package only ever spawns.
"""

from .framing import AIRFRAME_M, GLYPH_SCALE, FramingPlan, derive_drone_frac, plan_framing
from .look import VIDEO_LOOK
from .names import KINDS, MANEUVERS, video_filename, video_stem, video_title
from .render import BASE_VIDEO_ARGS, parse_framing, render_video, video_command

__all__ = [
    "AIRFRAME_M", "BASE_VIDEO_ARGS", "GLYPH_SCALE", "KINDS", "MANEUVERS", "VIDEO_LOOK",
    "FramingPlan", "derive_drone_frac", "parse_framing", "plan_framing", "render_video",
    "video_command", "video_filename", "video_stem", "video_title",
]
