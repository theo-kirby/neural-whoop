"""Load a hand-authored ``reference.json`` and resample it onto a control-rate tracking table.

This is the seam that turns the reference package from a **ruler** into a **teacher**. Everything
in :mod:`neural_whoop.reference` up to here authors a maneuver and grades it; nothing consumed the
1 kHz ``reference.json`` "data artifact". :class:`ReferenceTrack` is that consumer — it is what
``tasks/reference_track.py`` trains a policy against.

Pure numpy + stdlib, like the rest of ``reference/`` — no torch, no simulator. The task layer does
the tensor conversion.

Two decisions live here rather than in the task, because they are properties of the *reference*:

**1. The tracked window is the maneuver, not the whole clip.** A reference ships stagecraft around
the maneuver — a ``CLIMB`` from the floor, a ``HOVER`` beat, a ``LAND`` — because it is also a
video. Training a policy to fly those is a different (and already-solved) problem: the deploy split
has the ``hover_tof`` policy own take-off/hover/land and the acro policy own the bounded maneuver
window, and ``scripts/takeoff_flip_land.py`` stitches exactly that handoff. So the default
window drops the phases named in :data:`STAGECRAFT_PHASES`, which picks out the right beats for all
three shipped maneuvers without naming any of them:

===========  ==========================================  ==================================
maneuver     phases                                      tracked
===========  ==========================================  ==================================
``flip``     CLIMB HOVER **POP ROLL-IN COAST CATCH        POP → RECOVER
             RECOVER** LAND
``swing``    CLIMB HOVER **SWING SETTLE** LAND            SWING → SETTLE
``orbit``    CLIMB HOVER **WIND-UP ORBIT WIND-DOWN        WIND-UP → SETTLE
             SETTLE** LAND
===========  ==========================================  ==================================

**2. Resampling is nearest-sample, not interpolated.** The reference is deliberately emitted at
1 kHz because *50 Hz aliases these maneuvers* — the flip's rate brake is under two control steps
and its thrust cut is exactly one (``docs/REFERENCE_MANEUVER.md``). Interpolating a quaternion
across a command step would invent an attitude the authored trajectory never held, and averaging
across the thrust cut would smear the one discontinuity the maneuver is built around. Nearest-
sample keeps every target state a state the reference actually passed through. (The *commands* are
a different story — those are impulse-matched step means, and they are already baked into the
stream by ``emit.step_hold_commands``; we do not re-derive them here.)
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

#: Phase labels treated as stagecraft around the maneuver rather than part of it. Matched
#: case-insensitively against the reference's own ``stream.phase_labels``, so a new maneuver gets
#: the right window for free as long as it names its beats conventionally.
STAGECRAFT_PHASES = ("CLIMB", "HOVER", "LAND")


@dataclass(frozen=True)
class ReferenceTrack:
    """A reference maneuver resampled onto a fixed control step, ready to be tracked.

    All arrays are ``(T, ...)`` over the tracked window, in the same conventions as the replay
    schema and DiffAero: world-frame position/velocity, real-last (xyzw) quaternions, body-frame
    body rates. ``t`` is re-zeroed to the start of the window.
    """

    maneuver: str
    dt: float
    t: np.ndarray             # (T,)   s, from 0 at the window start
    pos: np.ndarray           # (T, 3) world m
    vel: np.ndarray           # (T, 3) world m/s
    quat: np.ndarray          # (T, 4) xyzw
    omega: np.ndarray         # (T, 3) body rad/s
    normed_thrust: np.ndarray  # (T,)  DiffAero units, 1.0 == hover
    rate_cmd: np.ndarray      # (T, 3) body rad/s command
    phase: np.ndarray         # (T,)   index into phase_labels
    phase_labels: tuple[str, ...]
    source: str               # path the reference was loaded from
    metrics: dict             # the reference's own headline metrics (the numbers to beat)

    @property
    def n_steps(self) -> int:
        return int(self.t.shape[0])

    @property
    def duration_s(self) -> float:
        return float(self.n_steps * self.dt)

    @property
    def station(self) -> np.ndarray:
        """The maneuver's station: where it starts, and where it is supposed to come back to.

        All three shipped maneuvers close on their entry point (``settle_pos_error`` is 0.000 for
        every one of them), so this doubles as the station-keeping reference the way ``acro_flip``
        uses its spawn point.
        """
        return self.pos[0].copy()

    def gravity_body(self) -> np.ndarray:
        """World-down expressed in the body frame, ``(T, 3)`` — the reference's *attitude* channel.

        This is what the policy can actually observe onboard (``acro_flip``'s ``gravity_body``), so
        it is the form the reference attitude has to be handed to a deploy-honest observation in.
        A full quaternion would be privileged information the real drone does not have.
        """
        down = np.array([0.0, 0.0, -1.0])
        return np.einsum("tji,j->ti", _rotmat_xyzw(self.quat), down)


def _rotmat_xyzw(q: np.ndarray) -> np.ndarray:
    """Body→world rotation matrices from real-last quaternions, ``(T, 4) → (T, 3, 3)``."""
    x, y, z, w = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    return np.stack([
        np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], axis=-1),
        np.stack([2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], axis=-1),
        np.stack([2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)], axis=-1),
    ], axis=1)


def _read_json(path: Path) -> dict:
    if path.suffix == ".gz":
        with gzip.open(path, "rt") as fh:
            return json.load(fh)
    return json.loads(path.read_text())


def load_reference_track(
    path: str | Path,
    dt: float,
    *,
    exclude_phases: tuple[str, ...] = STAGECRAFT_PHASES,
    include_phases: tuple[str, ...] | None = None,
) -> ReferenceTrack:
    """Load ``reference.json`` and resample the maneuver window onto a ``dt`` control step.

    Args:
        path: a ``reference.json`` (the 1 kHz data artifact) written by
            ``scripts/reference_maneuver.py``. Not the ``replay.json.gz`` — that one is decimated
            to 50 Hz for video and aliases the maneuver.
        dt: the environment's control step (s).
        exclude_phases: phase labels dropped as stagecraft. Ignored if ``include_phases`` is given.
        include_phases: explicit whitelist of phase labels to track, for a maneuver whose beats are
            not named conventionally.

    Raises:
        ValueError: if the file is not a reference artifact, if its sample rate is coarser than
            ``dt`` (which would mean upsampling a stream that was emitted fine *precisely* so it
            would not have to be), or if the phase selection leaves nothing to track.
    """
    p = Path(path)
    doc = _read_json(p)
    fmt = doc.get("format")
    if fmt != "neural-whoop-reference":
        raise ValueError(
            f"{p} is not a hand-authored reference (format={fmt!r}). Expected the "
            f"'neural-whoop-reference' data artifact from scripts/reference_maneuver.py; a "
            f"replay.json.gz is a *rollout* and is decimated to 50 Hz, which aliases the maneuver."
        )
    stream = doc["stream"]
    rate = float(stream["rate_hz"])
    if rate < 1.0 / dt - 1e-9:
        raise ValueError(
            f"reference is {rate:g} Hz but the control step asks for {1.0/dt:g} Hz — refusing to "
            f"upsample. Re-emit the reference at a finer rate."
        )

    labels = tuple(stream["phase_labels"])
    phase = np.asarray(stream["phase"], dtype=np.int64)
    if include_phases is not None:
        wanted = {s.upper() for s in include_phases}
        keep_lbl = [i for i, lbl in enumerate(labels) if lbl.upper() in wanted]
    else:
        drop = {s.upper() for s in exclude_phases}
        keep_lbl = [i for i, lbl in enumerate(labels) if lbl.upper() not in drop]
    mask = np.isin(phase, keep_lbl)
    if not mask.any():
        raise ValueError(
            f"phase selection left nothing to track. Reference phases are {list(labels)}; "
            f"{'include' if include_phases is not None else 'exclude'}="
            f"{include_phases if include_phases is not None else exclude_phases}."
        )
    idx = np.flatnonzero(mask)
    lo, hi = int(idx[0]), int(idx[-1])
    if not mask[lo:hi + 1].all():
        gaps = [labels[i] for i in np.unique(phase[lo:hi + 1][~mask[lo:hi + 1]])]
        raise ValueError(
            f"the tracked phases are not contiguous — {gaps} sit inside the window. A maneuver "
            f"window has to be one interval of time; tracking a stream with a hole in it would "
            f"teleport the target."
        )

    # Nearest-sample decimation onto the control grid (see the module docstring for why not lerp).
    t_fine = np.asarray(stream["t"], dtype=np.float64)
    t0 = float(t_fine[lo])
    n_out = int(np.floor((float(t_fine[hi]) - t0) / dt)) + 1
    want = t0 + np.arange(n_out) * dt
    take = np.clip(np.searchsorted(t_fine, want), 0, len(t_fine) - 1)
    # searchsorted lands on the sample at-or-after; pick whichever neighbour is actually nearer.
    prev = np.clip(take - 1, 0, len(t_fine) - 1)
    take = np.where(np.abs(t_fine[prev] - want) <= np.abs(t_fine[take] - want), prev, take)

    def pick(key: str) -> np.ndarray:
        return np.asarray(stream[key], dtype=np.float64)[take]

    quat = pick("quat")
    quat = quat / np.linalg.norm(quat, axis=-1, keepdims=True)
    return ReferenceTrack(
        maneuver=str(doc.get("maneuver", "unknown")),
        dt=float(dt),
        t=want - t0,
        pos=pick("pos"),
        vel=pick("vel"),
        quat=quat,
        omega=pick("omega"),
        normed_thrust=pick("normed_thrust"),
        rate_cmd=pick("rate_cmd"),
        phase=phase[take],
        phase_labels=labels,
        source=str(p),
        metrics=dict(doc.get("metrics", {})),
    )
