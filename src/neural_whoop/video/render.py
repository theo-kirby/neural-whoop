"""The one render entry point: ``<maneuver> maneuver <kind> video``, in the standard look.

Every MP4 the repo ships comes out of *this* module and no other, so the nine clips in
``render-examples/`` are comparable *pictures* rather than nine separately-tuned shots that happen
to resemble each other. The invocation is written down exactly once, here::

    scripts/capture_video.py --replay <replay.json.gz> --out <out.mp4> --width 1080 --height 1080

Note what is **not** in it: no camera flag at all. The look is ``capture_video.render()``'s own
default now (``neural_whoop.video.look.VIDEO_LOOK``), so a flag here could only ever be a per-clip
tune. The single exception is a :class:`~neural_whoop.video.framing.FramingPlan`, and it is an
exception with a rule attached — the guarantee is no longer "no per-clip flag ever" (the two-drone
comparison genuinely needs more framing room, and how much *is* the result), it is:

    **no hand-typed flag ever; every flag is derived from one measured quantity and recorded in
    the manifest.**

If a maneuver defeats the follow rig, the answer is still not a bespoke tune — it is to walk the
documented fallback ladder (lower ``--drone-frac``, then raise ``--max-drift``, then lower
``--track-smooth``, then ``--shot fit``), record which rung was taken *and its measurement*, and
treat that as a finding about the look's reach. ``tests/test_video_look.py`` pins both the look and
this command.

Pure stdlib (``subprocess`` + ``pathlib``): this module must stay importable without the ``capture``
extra, and it only ever *spawns* the capturer.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from .framing import FramingPlan
from .names import KIND_BLURBS, video_filename, video_title

REPO_ROOT = Path(__file__).resolve().parents[3]
CAPTURE_SCRIPT = REPO_ROOT / "scripts" / "capture_video.py"

#: The standardized invocation, verbatim — **size only**. 1080x1080 because the shot is square:
#: the follow rig holds apparent size constant, so a 16:9 frame spends its extra width on cyclorama.
BASE_VIDEO_ARGS = ["--width", "1080", "--height", "1080"]

#: ``capture_video.py`` prints its framing check on stdout; this lifts the two numbers out so the
#: caller can put them in a manifest rather than leaving them in a terminal scrollback.
_FRAMING_RE = re.compile(
    r"framing: worst \|NDC\| ([\d.]+) \(x ([\d.]+), y ([\d.]+)\)"
    r"(?:.*?size ([\d.]+)-([\d.]+)% of frame height)?"
)
_WARN_RE = re.compile(r"WARNING: the drone leaves frame \(worst \|NDC\| ([\d.]+)")


def video_command(replay: Path, out: Path, *, framing: FramingPlan | None = None) -> list[str]:
    """The exact argv for a video. Nothing may add to it but a derived framing plan."""
    return [
        sys.executable, str(CAPTURE_SCRIPT),
        "--replay", str(replay), "--out", str(out),
        *BASE_VIDEO_ARGS,
        *(framing.flags() if framing is not None else []),
    ]


def parse_framing(text: str) -> dict:
    """Pull the capturer's framing check out of its stdout.

    Two measured numbers, and both matter for a *standardized* shot: worst ``|NDC|`` (1.0 is the
    frame edge) says the subject stayed in frame, and the apparent-size spread says the follow rig
    actually held it at a constant size — a rig that keeps the drone in frame by letting it shrink
    has not delivered the shot, and only the second number would notice.

    Returns:
        ``{}`` when the capturer printed nothing parseable (e.g. ``--quiet``).
    """
    warn = _WARN_RE.search(text)
    m = _FRAMING_RE.search(text)
    if warn and not m:
        return {"worst_ndc": float(warn.group(1)), "left_frame": True}
    if not m:
        return {}
    out = {
        "worst_ndc": float(m.group(1)),
        "ndc_x": float(m.group(2)),
        "ndc_y": float(m.group(3)),
        "left_frame": bool(warn),
    }
    if m.group(4):
        lo, hi = float(m.group(4)), float(m.group(5))
        out["apparent_size_min_frac"] = lo / 100.0
        out["apparent_size_max_frac"] = hi / 100.0
        out["apparent_size_spread"] = (hi - lo) / max(lo, 1e-9)
    return out


def render_video(replay: Path, out_dir: Path, *, maneuver: str, kind: str,
                 framing: FramingPlan | None = None, echo: bool = True) -> dict:
    """Render one named clip and return the reproducibility record.

    The output filename is not a parameter: it is ``video_filename(maneuver, kind)`` and nothing
    else, because a clip whose name does not say what it is was how ``flip.mp4``,
    ``flip_policy.mp4``, ``vs_reference.mp4`` and ``hero.mp4`` came to sit in four directories
    meaning four different things.

    Args:
        replay: the replay to render (for ``comparison``, the two-drone overlay).
        out_dir: directory to write into; created if absent.
        maneuver / kind: see :mod:`neural_whoop.video.names`.
        framing: the maneuver's derived plan. ``None`` gives the bare invocation.
        echo: print the capturer's own output as it goes.

    Returns:
        ``{"video", "title", "kind", "maneuver", "command", "args", "returncode", "framing",
        "output_path", "note"}``. The command is recorded whether or not it succeeded — a video
        that failed to render is a fact about the maneuver, and burying it would defeat the point.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / video_filename(maneuver, kind)

    cmd = video_command(replay, out, framing=framing)
    if echo:
        print(f"[video] {video_title(maneuver, kind)}: {' '.join(cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    text = (proc.stdout or "") + (proc.stderr or "")
    if echo:
        print(text.rstrip())

    return {
        "video": out.name,
        "title": video_title(maneuver, kind),
        "maneuver": maneuver,
        "kind": kind,
        "kind_is": KIND_BLURBS[kind],
        "replay": str(replay),
        "command": cmd,
        "args": list(BASE_VIDEO_ARGS),
        "framing_plan": framing.to_dict() if framing is not None else None,
        "returncode": proc.returncode,
        "output_path": str(out),
        "framing": parse_framing(text),
        "note": (
            "One render entry point and one look: every MP4 in this repo comes out of this "
            "invocation, so the clips are comparable pictures rather than separate tunes. "
            "framing.worst_ndc is the worst distance from frame centre over EVERY drone (1.0 = "
            "the frame edge); apparent_size_spread is how much the subject's on-screen height "
            "varied (a follow rig should be ~flat)."
        ),
    }
