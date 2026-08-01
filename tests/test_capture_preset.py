"""``--preset hero`` is a **deliverable**, not a flag someone happened to type.

The reference-maneuver package's promise is "one invocation, same picture, any replay". That
promise lives entirely in :data:`scripts.capture_video.PRESETS` — so if a future edit retunes a
field, the videos silently stop matching each other and nothing fails. This file makes that edit a
failing test instead.

Every assertion below pins a value **together with the reason it has that value**, taken from the
measurements recorded in ``docs/VISUAL_CONTRACT.md`` / ``docs/REFERENCE_MANEUVER.md``. Changing a
number here is allowed — it just has to be a deliberate act that also updates the reason and
re-renders the shipped clips, which is exactly the bar this file exists to enforce.

Pure stdlib: ``capture_video`` imports playwright / imageio-ffmpeg lazily inside ``render()``, so
this runs without the ``capture`` extra.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import capture_video  # noqa: E402


HERO = capture_video.PRESETS["hero"]


# =============================================================================================
# The preset itself, field by field
# =============================================================================================
def test_hero_preset_fields_are_pinned():
    """Field-by-field, with the reason each value has its value.

    A bare ``assert PRESETS["hero"] == {...}`` would fail just as loudly but teach nothing; the
    point of the split is that whoever breaks it reads *why* the number is what it is.
    """
    # The rig. `follow` holds a constant offset from a smoothed subject track, so apparent size and
    # the horizon are fixed BY CONSTRUCTION rather than by a per-clip tune — a tripod that pans to
    # follow lets an 82 mm airframe balloon 6.7 -> 20.8% of frame height on the same flight.
    assert HERO["shot"] == "follow"
    # `floor` is a fogged cyclorama: no wall corner or ceiling seam can sweep through a moving shot.
    assert HERO["backdrop"] == "floor"
    assert HERO["theme"] == "dark"

    # drone_frac is the ONLY measured lever on framing room: at fixed drone_frac the standoff is
    # 1/tan(fov/2), so tan(fov/2)*dist — the world-metres one NDC unit spans at the subject — is
    # constant and a wider FOV buys nothing. 0.26 -> 0.22 is the slight zoom-out that bought the
    # room; it is also the fallback lever if a maneuver ever defeats the rig.
    assert HERO["drone_frac"] == 0.22
    # Bought purely for the flatter, less telephoto perspective (34 -> 40), NOT for framing room.
    assert HERO["fov"] == 40.0
    assert HERO["cam_dir"] == "0.85,0.30,1.0"

    # Smoothing is what SPENDS the room: 14 -> 28 costs worst |NDC| 0.54 -> 0.68 under the Hann
    # window (0.64 -> 0.91 under the old box window). 20 is the calm-but-affordable middle.
    assert HERO["track_smooth"] == 20
    # Slightly below centre, leaving headroom for a climb.
    assert HERO["subject_y"] == -0.06
    # The never-leaves-frame guarantee: how far (NDC) the subject may lead the smoothed camera
    # before the rig stops smoothing and pulls it back.
    assert HERO["max_drift"] == 0.26

    # A steep key puts the cast shadow UNDER the airframe, which is what sells ground contact.
    assert HERO["key_dir"] == "0.22,1.0,0.15"
    # The scene's light rig is tuned for the wide Studio view; a close shot clips its highlights to
    # flat white without ACES tone mapping.
    assert HERO["exposure"] == 0.95
    # No title/end cards: the hero preset is a clean concept shot, and a card would make the
    # frame-index-is-the-only-clock contract depend on the card length.
    assert HERO["title_frames"] == 0


def test_hero_preset_has_no_extra_keys():
    """A preset may only fill in flags ``LOOK_DEFAULTS`` declares.

    ``main()`` resolves the look as ``{**LOOK_DEFAULTS, **PRESETS[preset]}`` and then only copies
    keys that exist as argparse attributes, so a preset key not in ``LOOK_DEFAULTS`` would be
    accepted at import and then **silently ignored** at render time — the worst possible failure
    for a standardized shot.
    """
    for name, preset in capture_video.PRESETS.items():
        extra = set(preset) - set(capture_video.LOOK_DEFAULTS)
        assert not extra, f"preset {name!r} sets keys absent from LOOK_DEFAULTS: {sorted(extra)}"


def test_look_defaults_cover_every_preset_key_and_the_render_signature():
    """``LOOK_DEFAULTS`` is the contract between the CLI and ``render()``; both ends are checked.

    Every preset-able key must (a) be a real ``render()`` keyword, so the value actually reaches
    the page, and (b) declare **no argparse default**, because ``main()`` uses ``None`` to mean
    "you didn't say" — a flag with its own default would silently outrank the preset.
    """
    import inspect

    sig = inspect.signature(capture_video.render).parameters
    for key in capture_video.LOOK_DEFAULTS:
        assert key in sig, f"LOOK_DEFAULTS key {key!r} is not a render() parameter"

    parser_defaults = _parser_defaults()
    for key in capture_video.LOOK_DEFAULTS:
        assert key in parser_defaults, f"LOOK_DEFAULTS key {key!r} has no CLI flag"
        assert parser_defaults[key] is None, (
            f"--{key.replace('_', '-')} declares an argparse default "
            f"({parser_defaults[key]!r}); it must be None or the preset can never win."
        )


def _parser_defaults() -> dict:
    """The argparse defaults, by dest, without running the CLI."""
    import argparse

    holder: dict = {}
    real = argparse.ArgumentParser.parse_args

    def capture(self, *a, **kw):                       # noqa: ANN001, ANN002, ANN003
        holder["defaults"] = {act.dest: act.default for act in self._actions}
        raise SystemExit(0)

    argparse.ArgumentParser.parse_args = capture
    try:
        capture_video.main()
    except SystemExit:
        pass
    finally:
        argparse.ArgumentParser.parse_args = real
    return holder["defaults"]


# =============================================================================================
# The standard invocation the reference generator shells out to
# =============================================================================================
def test_standard_reference_video_command_is_the_hero_preset():
    """The generator's ``--video`` must emit exactly the documented invocation.

    This is the other half of the lock: pinning the preset is useless if the generator quietly
    passes a per-clip override alongside it. ``HERO_VIDEO_ARGS`` is the single place that
    invocation is written down, and ``docs/REFERENCE_MANEUVER.md`` quotes it verbatim.
    """
    from neural_whoop.reference.video import HERO_VIDEO_ARGS, hero_video_command

    assert HERO_VIDEO_ARGS == ["--preset", "hero", "--width", "1080", "--height", "1080"]
    cmd = hero_video_command(Path("a/replay.json.gz"), Path("a/out.mp4"))
    assert cmd[:2] == [sys.executable, str(REPO_ROOT / "scripts" / "capture_video.py")]
    assert "--preset" in cmd and cmd[cmd.index("--preset") + 1] == "hero"
    # Nothing beyond the replay/out pair and the standardized look — no per-clip tuning.
    tail = cmd[2:]
    assert tail == ["--replay", "a/replay.json.gz", "--out", "a/out.mp4", *HERO_VIDEO_ARGS]


@pytest.mark.parametrize("key", ["shot", "backdrop", "drone_frac", "max_drift"])
def test_the_documented_fallback_ladder_is_reachable(key):
    """The fallbacks the docs name must be things ``hero`` actually sets, in that order.

    If a maneuver defeats the follow rig the documented ladder is: lower ``--drone-frac``, then
    raise ``--max-drift``, then ``--shot fit``. Each rung has to be a live preset field or an
    accepted flag value, or the ladder is fiction.
    """
    assert key in capture_video.LOOK_DEFAULTS
    assert key in HERO or key in capture_video.LOOK_DEFAULTS
