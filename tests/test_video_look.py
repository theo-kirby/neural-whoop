"""The video look is a **deliverable**, not a flag someone happened to type.

The promise is "one invocation, same picture, any replay". It used to live in a
``PRESETS["hero"]`` bundle you had to opt into — which meant the two callers that never went
through the CLI (``scripts/viz.py`` and the Studio's ``/api/export``, both of which call
``capture_video.render()`` directly) silently rendered a *different environment*, and nothing
failed. The promise now lives in :data:`neural_whoop.video.look.VIDEO_LOOK` and in ``render()``'s
own keyword defaults, and this file locks both ends together.

Every assertion below pins a value **together with the reason it has that value**, taken from the
measurements recorded in ``docs/VISUAL_CONTRACT.md`` / ``docs/REFERENCE_MANEUVER.md``. Changing a
number here is allowed — it just has to be a deliberate act that also updates the reason and
re-renders the shipped clips (``scripts/render_examples.py``), which is exactly the bar this file
exists to enforce.

Pure stdlib: ``capture_video`` imports playwright / imageio-ffmpeg lazily inside ``render()``, so
this runs without the ``capture`` extra.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import capture_video  # noqa: E402

from neural_whoop.video.look import VIDEO_LOOK  # noqa: E402


# =============================================================================================
# The look itself, field by field
# =============================================================================================
def test_the_video_look_fields_are_pinned():
    """Field by field, with the reason each value has its value.

    A bare ``assert VIDEO_LOOK == {...}`` would fail just as loudly but teach nothing; the point of
    the split is that whoever breaks it reads *why* the number is what it is.
    """
    # The rig. `follow` holds a constant offset from a smoothed subject track, so apparent size and
    # the horizon are fixed BY CONSTRUCTION rather than by a per-clip tune — a tripod that pans to
    # follow lets an 82 mm airframe balloon 6.7 -> 20.8% of frame height on the same flight.
    assert VIDEO_LOOK["shot"] == "follow"
    assert VIDEO_LOOK["theme"] == "dark"

    # drone_frac is the ONLY measured lever on framing room: at fixed drone_frac the standoff is
    # 1/tan(fov/2), so tan(fov/2)*dist — the world-metres one NDC unit spans at the subject — is
    # constant and a wider FOV buys nothing. 0.26 -> 0.22 is the slight zoom-out that bought the
    # room; it is also the first rung of the fallback ladder.
    assert VIDEO_LOOK["drone_frac"] == 0.22
    # Bought purely for the flatter, less telephoto perspective (34 -> 40), NOT for framing room.
    assert VIDEO_LOOK["fov"] == 40.0
    assert VIDEO_LOOK["cam_dir"] == (0.85, 0.30, 1.0)

    # Smoothing is what SPENDS the room: 14 -> 28 costs worst |NDC| 0.54 -> 0.68 under the Hann
    # window (0.64 -> 0.91 under the old box window). 20 is the calm-but-affordable middle.
    assert VIDEO_LOOK["track_smooth"] == 20
    # Slightly below centre, leaving headroom for a climb.
    assert VIDEO_LOOK["subject_y"] == -0.06
    # The never-leaves-frame guarantee: how far (NDC) the subject may lead the smoothed camera
    # before the rig stops smoothing and pulls it back.
    assert VIDEO_LOOK["max_drift"] == 0.26

    # A steep key puts the cast shadow UNDER the airframe, which is what sells ground contact.
    assert VIDEO_LOOK["key_dir"] == (0.22, 1.0, 0.15)
    # The scene's light rig is tuned for the wide Studio view; a close shot clips its highlights to
    # flat white without ACES tone mapping.
    assert VIDEO_LOOK["exposure"] == 0.95
    # No title/end cards: a card would make the frame-index-is-the-only-clock contract depend on
    # the card length.
    assert VIDEO_LOOK["title_frames"] == 0

    # The stage is DERIVED, never dialled: fog from the camera standoff, floor size from the fog,
    # grid subdivision from the framing (web/studio/environment.js::STAGE_LOOK). `None` is what
    # selects that derivation, so these three being None is the actual assertion.
    assert VIDEO_LOOK["fog"] is None
    assert VIDEO_LOOK["grid_pitch"] is None
    assert VIDEO_LOOK["grid_minor"] is None


def test_there_is_no_walled_backdrop_option_left_anywhere():
    """One environment, no dead branch — the whole point of retiring the preset.

    ``--backdrop room`` used to be the *default*, so every caller that didn't pass ``--preset hero``
    got the walled greybox. Its removal has to be total: a lingering key would let it back in.
    """
    assert "backdrop" not in VIDEO_LOOK
    assert "backdrop" not in inspect.signature(capture_video.render).parameters
    assert not hasattr(capture_video, "PRESETS")
    assert not hasattr(capture_video, "LOOK_DEFAULTS")
    geometry = (REPO_ROOT / "web" / "studio" / "geometry.js").read_text()
    assert "buildRoom" not in geometry, "the walled-room builder must be gone, not renamed around"
    assert "walls" not in geometry.split("export function buildStageFloor")[1]


# =============================================================================================
# The two ends of the lock: render()'s defaults, and the CLI's "you didn't say" convention
# =============================================================================================
def test_render_defaults_match_the_video_look():
    """``render()``'s keyword defaults must BE the look, field for field.

    This is the assertion that closes the hole the preset left open. ``scripts/viz.py`` and
    ``src/neural_whoop/studio/server.py`` both do ``from capture_video import render`` and call it
    with only size/fps/crf — they never see ``main()``, so whatever ``render()`` declares is the
    picture they produce. Pinning the signature is what lets those two files carry no look code at
    all and still render the standard clip.
    """
    sig = inspect.signature(capture_video.render).parameters
    missing = sorted(k for k in VIDEO_LOOK if k not in sig)
    assert not missing, f"VIDEO_LOOK keys absent from render(): {missing}"
    mismatched = {
        key: (sig[key].default, value)
        for key, value in VIDEO_LOOK.items()
        if sig[key].default != value
    }
    assert not mismatched, (
        "render() defaults have drifted from VIDEO_LOOK: "
        + ", ".join(f"{k}: render {r!r} vs look {lk!r}" for k, (r, lk) in mismatched.items()))


def test_every_look_flag_declares_no_argparse_default():
    """``main()`` uses ``None`` to mean "you didn't say", so a flag with its own default would win.

    Same invariant the preset needed, and it survives the preset's removal unchanged: a look flag
    that declares an argparse default can never fall through to ``VIDEO_LOOK``, and the failure is
    silent — the CLI just quietly renders something else.
    """
    parser_defaults = _parser_defaults()
    for key in VIDEO_LOOK:
        assert key in parser_defaults, f"VIDEO_LOOK key {key!r} has no CLI flag"
        assert parser_defaults[key] is None, (
            f"--{key.replace('_', '-')} declares an argparse default "
            f"({parser_defaults[key]!r}); it must be None or VIDEO_LOOK can never win."
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
# The standard invocation the generators shell out to
# =============================================================================================
def test_the_standard_video_command_carries_no_camera_flag():
    """The generators' ``--video`` must emit the bare invocation: size only, no look.

    This is the other half of the lock. Pinning the look is useless if a generator quietly passes a
    per-clip override alongside it — that is precisely how a "standardized" shot stops being one.
    ``BASE_VIDEO_ARGS`` is the single place the invocation is written down, and
    ``docs/REFERENCE_MANEUVER.md`` quotes it verbatim.
    """
    from neural_whoop.video.render import BASE_VIDEO_ARGS, video_command

    assert BASE_VIDEO_ARGS == ["--width", "1080", "--height", "1080"]
    cmd = video_command(Path("a/replay.json.gz"), Path("a/out.mp4"))
    assert cmd[:2] == [sys.executable, str(REPO_ROOT / "scripts" / "capture_video.py")]
    tail = cmd[2:]
    assert tail == ["--replay", "a/replay.json.gz", "--out", "a/out.mp4", *BASE_VIDEO_ARGS]
    # No camera flag of any kind — not "no preset flag", NO look flag. The look is the default now,
    # so anything here would be a per-clip tune by definition.
    look_flags = {f"--{k.replace('_', '-')}" for k in VIDEO_LOOK}
    assert not look_flags & set(cmd), f"per-clip camera flags leaked in: {look_flags & set(cmd)}"


def test_a_framing_plan_derives_its_flags_and_never_hand_types_them():
    """The one exception to "no flags": a framing plan, whose every flag comes from a measurement.

    The old guarantee was "no per-clip flag ever". The overlay broke it honestly — a two-drone
    comparison genuinely needs more framing room than a one-drone shot, and how much is the *result*
    being reported. So the guarantee became: no HAND-TYPED flag ever; every flag is derived from one
    measured quantity and recorded in the manifest.
    """
    from neural_whoop.video.framing import plan_framing
    from neural_whoop.video.render import video_command

    plan = plan_framing("flip", separation_m=0.9)
    cmd = video_command(Path("a.json.gz"), Path("b.mp4"), framing=plan)
    assert "--drone-frac" in cmd and "--scale" in cmd
    # Derived, not typed: both follow from separation_m and the glyph scale.
    assert float(cmd[cmd.index("--drone-frac") + 1]) == plan.drone_frac
    assert float(cmd[cmd.index("--scale") + 1]) == plan.render_scale_m


@pytest.mark.parametrize("key", ["shot", "drone_frac", "max_drift", "track_smooth"])
def test_the_documented_fallback_ladder_is_reachable(key):
    """The fallbacks the docs name must be things the look actually sets, in that order.

    If a maneuver defeats the follow rig the documented ladder is: lower ``--drone-frac``, then
    raise ``--max-drift``, then drop ``--track-smooth`` (the rung the orbit actually needed), then
    ``--shot fit``. Each rung has to be a live look field, or the ladder is fiction.
    """
    assert key in VIDEO_LOOK
