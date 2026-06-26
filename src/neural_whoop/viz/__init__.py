"""Visual observability seam — the replay schema, recorder, and lazy renderer.

This subpackage is the lab's *visual contract*: a versioned, self-describing replay schema
(:mod:`neural_whoop.viz.replay`, pure ``json`` + ``gzip`` + numpy) plus a lazily-imported
renderer (:mod:`neural_whoop.viz.render`, the ``viz`` extra: matplotlib + Pillow + tbparse)
that turns a replay into Flywheel-native artifacts (trajectory PNGs, synthetic FPV frames,
training curves, policy comparisons).

The schema is the durable, repo-independent seam: the same JSON shape feeds the lab's
``web/replay-viewer/`` Three.js viewer and any external tool. Training stays render-free —
viz is opt-in. Only :mod:`replay` is imported eagerly (it has no heavy deps); :mod:`render`
is imported on demand so core deps never grow.

See ``docs/VISUAL_CONTRACT.md`` for the full spec.
"""

from __future__ import annotations

from neural_whoop.viz.replay import (
    REPLAY_FORMAT,
    REPLAY_VERSION,
    RunRecorder,
    build_meta,
    load_run,
)

__all__ = [
    "REPLAY_FORMAT",
    "REPLAY_VERSION",
    "RunRecorder",
    "build_meta",
    "load_run",
]
