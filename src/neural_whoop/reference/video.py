"""The **reference video contract**: one invocation, the same picture, any maneuver.

``--preset hero`` is the deliverable, not a flag someone happened to type. Every reference
maneuver's MP4 comes out of *this* command and no other, so the swing, the orbit and the flip are
directly comparable pictures rather than three separately-tuned clips that happen to look similar.

The invocation is written down exactly once, here::

    scripts/capture_video.py --replay <replay.json.gz> --out <out.mp4>
        --preset hero --width 1080 --height 1080

There is deliberately **no per-clip flag**. If a maneuver defeats the follow rig, the answer is not
a bespoke camera tune — it is to walk the documented fallback ladder (lower ``--drone-frac``, then
raise ``--max-drift``, then ``--shot fit``), record which rung was taken, and treat that as a
finding about the preset's reach. ``tests/test_capture_preset.py`` pins both the preset's fields
and this command.

Pure stdlib (``subprocess`` + ``pathlib``): the reference package must stay importable without the
``capture`` extra, and this module only ever *spawns* the capturer.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CAPTURE_SCRIPT = REPO_ROOT / "scripts" / "capture_video.py"

#: The standardized look, verbatim. 1080x1080 because the hero shot is square: the follow rig holds
#: apparent size constant, so a 16:9 frame spends its extra width on cyclorama.
HERO_VIDEO_ARGS = ["--preset", "hero", "--width", "1080", "--height", "1080"]

#: ``capture_video.py`` prints its framing check on stdout; this lifts the two numbers out so the
#: generator can put them in ``run.json`` rather than leaving them in a terminal scrollback.
_FRAMING_RE = re.compile(
    r"framing: worst \|NDC\| ([\d.]+) \(x ([\d.]+), y ([\d.]+)\)"
    r"(?:.*?size ([\d.]+)-([\d.]+)% of frame height)?"
)
_WARN_RE = re.compile(r"WARNING: the drone leaves frame \(worst \|NDC\| ([\d.]+)")


def hero_video_command(replay: Path, out: Path) -> list[str]:
    """The exact argv for a reference video. No maneuver may add to it."""
    return [
        sys.executable, str(CAPTURE_SCRIPT),
        "--replay", str(replay), "--out", str(out),
        *HERO_VIDEO_ARGS,
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


def render_hero_video(replay: Path, out: Path, *, echo: bool = True) -> dict:
    """Run the standard invocation and return the reproducibility record for ``run.json``.

    Returns:
        ``{"command": [...], "returncode": int, "framing": {...}, "output": str}``. The command is
        recorded whether or not it succeeded — a video that failed to render is a fact about the
        maneuver, and burying it would defeat the point of the contract.
    """
    cmd = hero_video_command(replay, out)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    text = (proc.stdout or "") + (proc.stderr or "")
    if echo:
        print(text.rstrip())
    return {
        "command": cmd,
        "args": list(HERO_VIDEO_ARGS),
        "returncode": proc.returncode,
        "output_path": str(out),
        "framing": parse_framing(text),
        "note": (
            "The reference video contract: every maneuver's MP4 comes out of THIS invocation and "
            "no other, so the clips are comparable pictures rather than separate tunes. "
            "framing.worst_ndc is the subject's worst distance from frame centre (1.0 = the frame "
            "edge); apparent_size_spread is how much the airframe's on-screen height varied "
            "(a follow rig should be ~flat)."
        ),
    }
