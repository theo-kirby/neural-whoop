"""The Python -> JavaScript render-options seam, pinned.

``scripts/capture_video.py::page_options`` builds a snake_case -> camelCase dict and injects it as
``window.__CAPTURE_OPTS__``; ``web/capture/capture.js`` spreads it over its own ``DEFAULTS``.
**Nothing at runtime checks that the two agree** — and the failure mode is the worst kind for a
renderer: a key renamed on one side falls back to the other side's default, the render succeeds,
and the video is silently framed with a camera nobody asked for. There is no exception, no warning
and no visual artefact that says "this option was dropped".

So the seam is checked here instead, three ways:

1. every key ``page_options`` emits exists in ``DEFAULTS`` (nothing is silently ignored);
2. every ``DEFAULTS`` key is emitted (nothing on the page is unreachable from Python), except the
   two deliberately conditional ones — ``scale`` and ``roomSize``, whose *absence* is what selects
   the page's own derivation;
3. the shared literal values agree, so "the default" means one thing rather than two.

Check 3 is what caught the drift this file was written for: ``titleFrames`` was 40 in Python and 0
in JS, so ``render()``'s docstring promised an opening card that no render had ever drawn.

Pure stdlib — ``capture_video`` imports playwright / imageio-ffmpeg lazily inside ``render()``, and
``DEFAULTS`` is read out of the JS **source text**, so this runs without the ``capture`` extra and
without a browser.
"""

from __future__ import annotations

import inspect
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import capture_video  # noqa: E402

CAPTURE_JS = REPO_ROOT / "web" / "capture" / "capture.js"

#: The page derives these itself when the key is absent, so Python emits them only when set.
CONDITIONAL = {"scale", "roomSize"}

#: ``key: value,`` on its own line inside the ``DEFAULTS`` object literal.
_ENTRY_RE = re.compile(r"^\s{2}(\w+):\s*(.+?),\s*(?://.*)?$", re.M)


def _js_defaults() -> dict[str, object]:
    """Parse ``DEFAULTS`` out of ``capture.js``'s source.

    Deliberately a text parse rather than a Node evaluation: this test must run in the plain
    pytest environment, and the object literal is one flat block of JSON-compatible scalars
    (plus one identifier, ``TRUE_FOOTPRINT``, which is a conditional key anyway).
    """
    src = CAPTURE_JS.read_text()
    m = re.search(r"const DEFAULTS = \{\n(.*?)\n\};", src, re.S)
    assert m, "could not find the DEFAULTS object literal in capture.js"
    out: dict[str, object] = {}
    for key, raw in _ENTRY_RE.findall(m.group(1)):
        try:
            out[key] = json.loads(raw)          # null/true/false/number/"string"/[a, b, c]
        except json.JSONDecodeError:
            out[key] = _UNPARSEABLE             # an identifier, e.g. TRUE_FOOTPRINT
    return out


class _Unparseable:
    def __repr__(self) -> str:
        return "<js identifier>"


_UNPARSEABLE = _Unparseable()


def _emitted() -> dict[str, object]:
    """What ``page_options`` produces from ``render()``'s own keyword defaults.

    Driving it from ``inspect.signature(render)`` rather than a hand-written dict is the point:
    ``render()``'s defaults are what ``scripts/viz.py`` and the Studio's ``/api/export`` actually
    get, since both call ``render()`` directly instead of going through ``main()``.
    """
    render_defaults = {
        name: p.default for name, p in inspect.signature(capture_video.render).parameters.items()
    }
    kwargs = {}
    for name, p in inspect.signature(capture_video.page_options).parameters.items():
        assert name in render_defaults, f"page_options({name}=) is not a render() parameter"
        assert render_defaults[name] is not inspect.Parameter.empty, (
            f"render()'s {name} has no default, so the page contract has no fixed value")
        kwargs[name] = render_defaults[name]
    return capture_video.page_options(**kwargs)


def test_every_emitted_key_exists_on_the_page():
    """A key the page has never heard of is accepted, ignored, and renders the wrong video."""
    js, emitted = _js_defaults(), _emitted()
    extra = sorted(set(emitted) - set(js))
    assert not extra, (
        f"page_options emits {extra}, absent from capture.js's DEFAULTS — the page would fall "
        f"back to its own value and the flag would do nothing")


def test_every_page_option_is_reachable_from_python():
    """The other direction: a DEFAULTS key Python never sets can only ever hold its default."""
    js, emitted = _js_defaults(), _emitted()
    missing = sorted(set(js) - set(emitted) - CONDITIONAL)
    assert not missing, (
        f"capture.js's DEFAULTS declare {missing}, which page_options never emits — unreachable "
        f"from any flag. Add them to page_options, or drop them from the page")


def test_the_conditional_keys_are_exactly_the_two_documented_ones():
    """``scale``/``roomSize`` are omitted on purpose; their absence selects the page's derivation."""
    js = _js_defaults()
    assert CONDITIONAL <= set(js)
    assert "scale" not in _emitted() and "roomSize" not in _emitted()
    # And they DO appear once asked for, or the conditional path is dead.
    with_both = capture_video.page_options(
        **{**{n: p.default for n, p in
              inspect.signature(capture_video.render).parameters.items()
              if n in inspect.signature(capture_video.page_options).parameters},
           "room_size": 6.0, "scale": 0.25})
    assert with_both["roomSize"] == 6.0
    assert with_both["scale"] == 0.25


def test_the_shared_default_values_agree():
    """One default per option, not two.

    This is the check that caught ``titleFrames`` (40 in Python, 0 in JS). Keys whose JS value is
    an identifier rather than a literal are skipped — they are the conditional ones, where the
    page's value is by definition the fallback.
    """
    js, emitted = _js_defaults(), _emitted()
    mismatched = {
        k: (emitted[k], js[k])
        for k in sorted(set(js) & set(emitted))
        if js[k] is not _UNPARSEABLE and emitted[k] != js[k]
    }
    assert not mismatched, (
        "python default != page default for: "
        + ", ".join(f"{k}: py {py!r} vs js {j!r}" for k, (py, j) in mismatched.items()))


def test_the_page_rejects_an_unknown_injected_option():
    """The runtime half of the contract: capture.js must throw rather than silently ignore.

    A test can pin the two dictionaries, but only the page can catch a caller that hand-builds
    ``__CAPTURE_OPTS__``. Assert the guard is present and keyed on ``DEFAULTS``.
    """
    src = CAPTURE_JS.read_text()
    assert "__CAPTURE_OPTS__" in src
    guard = re.search(r"Object\.keys\(window\.__CAPTURE_OPTS__[^)]*\|\| \{\}\)\.filter\(", src)
    assert guard, "capture.js no longer checks the injected keys against DEFAULTS"
    assert re.search(r"if \(unknown\.length\) \{\s*throw new Error", src), (
        "capture.js must THROW on an unknown injected option, not warn")
