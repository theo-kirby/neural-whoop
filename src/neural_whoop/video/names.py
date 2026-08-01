"""The video vocabulary, in one place: ``<maneuver> maneuver <kind> video``.

The repo grew four different meanings for the word "hero" — a camera preset, the concept clip, the
*recorded subject drone*, and the Studio's picture-in-picture layout boxes — and filenames to match
(``flip.mp4``, ``flip_policy.mp4``, ``vs_reference.mp4``, ``hero.mp4``). None of them said what the
clip actually was.

So a video is now named by two axes and nothing else:

* **maneuver** — which hand-authored reference the clip is about (``flip`` / ``swing`` / ``orbit``);
* **kind** — what is *in* it:

  ``reference``   the hand-authored trajectory alone. No policy, no simulator, no training: pure
                  numpy out of ``scripts/reference_maneuver.py``. "The one we want."
  ``policy``      what a trained policy actually flew, from the zero-RSI eval twin.
  ``comparison``  both at once, in one replay: the reference as a translucent ghost and the camera
                  subject, the policy solid beside it. The gap between them is the result.

**"hero" is retired from the VIDEO vocabulary only.** The replay schema's *hero drone* / *hero
episode* / ``heroFrames`` / ``--n-heroes`` mean "the recorded subject drone" — a real and useful
concept documented in ``docs/VISUAL_CONTRACT.md`` — and they stay exactly as they are. Do not
"finish" this rename into the schema.

Pure stdlib; no torch, no numpy, no renderer.
"""

from __future__ import annotations

#: The hand-authored reference maneuvers. Moved here from ``scripts/reference_maneuver.py`` so the
#: generator, the comparison script and the example renderer all read one list.
MANEUVERS: tuple[str, ...] = ("flip", "swing", "orbit")

#: What a clip contains. Ordered as the story reads: what we wanted, what we got, the two together.
KINDS: tuple[str, ...] = ("reference", "policy", "comparison")

#: One line each, for a README or a ``--help``.
KIND_BLURBS: dict[str, str] = {
    "reference": "the hand-authored trajectory alone — no policy and no simulator",
    "policy": "what the trained policy actually flew (the zero-RSI eval twin)",
    "comparison": "both in one frame: ghost reference + solid policy, camera on the reference",
}


def _check(maneuver: str, kind: str) -> None:
    """Reject an unknown maneuver or kind loudly.

    A typo'd kind would otherwise produce a plausible filename that no convention covers, which is
    how the ad-hoc names got there in the first place.
    """
    if maneuver not in MANEUVERS:
        raise ValueError(f"unknown maneuver {maneuver!r}; expected one of {list(MANEUVERS)}")
    if kind not in KINDS:
        raise ValueError(f"unknown video kind {kind!r}; expected one of {list(KINDS)}")


def video_stem(maneuver: str, kind: str) -> str:
    """``flip_maneuver_reference`` — the filename stem, no extension."""
    _check(maneuver, kind)
    return f"{maneuver}_maneuver_{kind}"


def video_filename(maneuver: str, kind: str) -> str:
    """``flip_maneuver_reference.mp4`` — the only filename any of these clips may have."""
    return f"{video_stem(maneuver, kind)}.mp4"


def video_title(maneuver: str, kind: str) -> str:
    """``flip maneuver reference video`` — how to say it out loud, and in a caption."""
    _check(maneuver, kind)
    return f"{maneuver} maneuver {kind} video"
