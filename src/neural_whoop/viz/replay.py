"""Self-describing replay export — the durable **visual contract**, pure stdlib + numpy.

This serializes a rollout (per-step drone telemetry + per-episode gate layouts + run-level
contract metadata) to a single **self-describing JSON** document so an external visualizer —
the lab's ``web/replay-viewer/`` Three.js player, a Unity rig, or any other repo — can replay
a run from data alone, no pixels and no separate format doc. It is deliberately dependency-
light (``json`` + ``gzip`` + ``numpy``, all already core deps): it imports and unit-tests
without DiffAero, torch, or the ``viz`` extra, so ``scripts/eval.py --record`` works anywhere.

Ported faithfully from ``neural-whoop-lab``'s ``viz/replay.py`` so the **same JSON shape** is
produced — the lab's Three.js viewer consumes new-repo rollouts unchanged — with the ``meta``
block re-grounded in *this* repo's real contract (:mod:`neural_whoop.contract`).

Coordinates are written in the **raw simulator frame**: world is right-handed, **Z-up**,
meters; quaternion is real-last ``[qx, qy, qz, qw]`` (xyzw, matching DiffAero); angles in
radians; the body frame is +x forward (camera) / +y left / +z up. ``meta.unity_hint`` tells a
Y-up consumer how to convert. Velocity (``vel``) is world-frame m/s; angular velocity
(``angvel``) is **body-frame** rad/s (the gyro signal) — see ``meta.state_layout``.

JSON schema (version 1)
-----------------------
::

    {
      "format": "neural-whoop-replay",
      "version": 1,
      "meta": {
        "config":         <str>,     # experiment/config name
        "policy":         <str>,     # human-readable policy label (params, source ckpt)
        "task":           <str>,     # registry task name (e.g. "gate_race")
        "obs_version":    "obs-v4",
        "action_version": "act-v2",
        "substrate":      "diffaero",
        "control_hz":     <int>,     # policy decision rate (= round(1/dt))
        "sim_hz":         <int>,     # underlying physics rate (control_hz * n_substeps)
        "dt":             <float>,   # control timestep (s)
        "coordinate_frame": <str>,   # frame/units/quaternion-order/angle-unit description
        "state_layout":     <str>,   # per-frame pose-block layout + frames of vel/angvel
        "action_layout":    <str>,   # act-v2 + action_diffaero semantics
        "action_limits":  {          # the ActionLimits the env mapped the action onto
          "max_thrust_normed": <float>, "hover_thrust_normed": <float>,
          "max_body_rate_rp_rps": <float>, "max_body_rate_yaw_rps": <float>
        },
        "unity_hint":     <str>      # Z-up RH -> Unity Y-up LH conversion hint (VERIFY!)
      },
      "episodes": [
        {
          "index":  <int>,                      # 1-based hero/episode number
          "drone":  <int>,                      # flat drone index this episode recorded
          "gates":  [ {"pos": [x,y,z], "radius": <float>} ],   # this episode's course
          "dr":     { ... } | null,             # live per-drone domain-randomization params
          "oracle_lap": <float>,                # speed-oracle target lap time (s)
          "drones": [                           # OPTIONAL (v2): swarm group sharing one course.
            {                                   # present for n_agents>1 tasks. When present, the
              "drone": <int>, "dr": {...}|null, # episode-level drone/dr/summary/frames mirror
              "summary": {...}, "frames": [...] # drones[0] (the lead) for v1-reader compat.
            }
          ],
          "summary": {                          # filled at end_episode
            "steps": <int>, "total_reward": <float>,
            "laps": <int>, "best_lap": <float|null>,
            "gates_passed": <int>, "num_gates": <int>,
            "ended": <str>                      # "crash" | "max_steps"
          },
          "frames": [
            {
              "t": <float>,                # sim time (s) at this control step
              "step": <int>,              # 1-based control-step index
              "pos":    [x, y, z],        # world frame (m)
              "quat":   [qx, qy, qz, qw],
              "rpy":    [roll, pitch, yaw],   # world frame (rad)
              "vel":    [vx, vy, vz],         # WORLD frame (m/s)
              "angvel": [p, q, r],            # BODY frame (rad/s; gyro)
              "action":          [...],   # act-v2 CTBR normalized [-1, 1]
              "action_diffaero": [...],   # DiffAero CTBR [normed_thrust, wx, wy, wz]
              "reward":     <float>,      # step reward
              "cum_reward": <float>,      # cumulative episode reward through this step
              "gate_idx":   <int>,        # index of the next gate to pass
              "dist_to_gate": <float>,    # distance to that gate's center (m)
              "laps":   <int>,            # laps completed so far this episode
              "passed": <bool>,           # a gate was passed this step
              "crashed": <bool>,          # the drone crashed this step
              "obs": [...]                # optional flat observation vector
            }
          ]
        }
      ]
    }

Read a file back with :func:`load_run` (gzip-transparent).
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import numpy as np

REPLAY_FORMAT = "neural-whoop-replay"
REPLAY_VERSION = 2

#: Coordinate-frame / layout strings baked into every replay's ``meta`` block — the single
#: source of truth so the CLI, eval, and the autonomous loop agree byte-for-byte.
COORDINATE_FRAME = (
    "world: right-handed, Z-up, meters; body: +x forward (camera) / +y left / +z up; "
    "quaternion [qx,qy,qz,qw] (xyzw); angles radians"
)
STATE_LAYOUT = (
    "per-frame: pos[3] world m, quat[4 xyzw], rpy[3] world rad, "
    "vel[3] WORLD m/s, angvel[3] BODY rad/s (gyro)"
)
ACTION_LAYOUT = (
    "act-v2 CTBR normalized [-1,1]: [collective_thrust, roll_rate, pitch_rate, yaw_rate]; "
    "action_diffaero[4] = DiffAero convention [normed_thrust (1.0==hover), "
    "roll_rate, pitch_rate, yaw_rate] (rad/s)"
)
UNITY_HINT = (
    "Z-up RH -> Unity Y-up LH: pos (x,y,z)->(x,z,y); quaternion (qx,qy,qz,qw)->"
    "(qx,qz,qy,-qw) — VERIFY against your rig"
)


def _vec(x: Any) -> list[float]:
    """Coerce a numpy array / torch tensor / sequence / scalar to a plain list of JSON floats."""
    arr = np.asarray(x, dtype=np.float64).reshape(-1)
    return [float(v) for v in arr]


def _build_frame(
    *,
    t: float,
    step: int,
    pos: Any,
    quat: Any,
    rpy: Any,
    vel: Any,
    angvel: Any,
    action: Any,
    action_diffaero: Any,
    reward: float,
    cum_reward: float,
    gate_idx: int,
    dist_to_gate: float,
    laps: int,
    passed: bool = False,
    crashed: bool = False,
    obs: Any = None,
) -> dict[str, Any]:
    """Coerce one control-step frame to plain JSON types (shared by single- and group-episode)."""
    frame: dict[str, Any] = {
        "t": float(t),
        "step": int(step),
        "pos": _vec(pos),
        "quat": _vec(quat),
        "rpy": _vec(rpy),
        "vel": _vec(vel),
        "angvel": _vec(angvel),
        "action": _vec(action),
        "action_diffaero": _vec(action_diffaero),
        "reward": float(reward),
        "cum_reward": float(cum_reward),
        "gate_idx": int(gate_idx),
        "dist_to_gate": float(dist_to_gate),
        "laps": int(laps),
        "passed": bool(passed),
        "crashed": bool(crashed),
    }
    if obs is not None:
        frame["obs"] = _vec(obs)
    return frame


def build_meta(
    env: Any,
    *,
    config: str,
    policy: str,
) -> dict[str, Any]:
    """Assemble the replay ``meta`` block from a config name + the live env contract.

    Reads the real seam off the env: ``ActionLimits`` (``env.limits``), control/sim rates
    (from ``env.dt`` and the dynamics' substeps), the task name, and the obs/act versions.

    Args:
        env: The :class:`~neural_whoop.envs.base.MultiAgentDroneEnv` being rolled out.
        config: Experiment/config name (e.g. ``"gate_race"``).
        policy: Human-readable policy label (params, source checkpoint).

    Returns:
        The ``meta`` dict (all JSON-native types).
    """
    dt = float(env.dt)
    control_hz = int(round(1.0 / dt)) if dt > 0 else 0
    n_substeps = int(getattr(env.dyn.params, "n_substeps", 1))
    lim = env.limits
    return {
        "config": str(config),
        "policy": str(policy),
        "task": str(getattr(env.task, "name", "unknown")),
        "obs_version": "obs-v4",
        "action_version": "act-v2",
        "substrate": "diffaero",
        "control_hz": control_hz,
        "sim_hz": control_hz * n_substeps,
        "dt": dt,
        "coordinate_frame": COORDINATE_FRAME,
        "state_layout": STATE_LAYOUT,
        "action_layout": ACTION_LAYOUT,
        "action_limits": {
            "max_thrust_normed": float(lim.max_thrust_normed),
            "hover_thrust_normed": float(lim.hover_thrust_normed),
            "max_body_rate_rp_rps": float(lim.max_body_rate_rp_rps),
            "max_body_rate_yaw_rps": float(lim.max_body_rate_yaw_rps),
        },
        "unity_hint": UNITY_HINT,
    }


class RunRecorder:
    """Accumulate a rollout's telemetry and serialize it to a self-describing replay file.

    Usage mirrors the rollout loop: build with run-level ``meta`` (see :func:`build_meta`),
    then per recorded **hero** drone call :meth:`begin_episode`, :meth:`add_frame` (once per
    control step), :meth:`end_episode`, and finally :meth:`save`. Frame data is coerced to
    plain JSON floats/ints/bools at ``add_frame`` time, so no torch/numpy types leak into the
    document — callers move tensors to CPU once before feeding rows in.
    """

    def __init__(self, meta: dict[str, Any]) -> None:
        self.meta = dict(meta)
        self._episodes: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None

    @property
    def frame_count(self) -> int:
        """Total frames recorded across all (ended) episodes plus the open one."""
        total = sum(len(ep["frames"]) for ep in self._episodes)
        if self._current is not None:
            total += len(self._current["frames"])
        return total

    @property
    def episode_count(self) -> int:
        """Number of episodes ended so far (the open one isn't counted)."""
        return len(self._episodes)

    def begin_episode(
        self,
        index: int,
        gates: Any,
        *,
        drone: int = 0,
        dr: dict[str, Any] | None = None,
        oracle_lap: float | None = None,
    ) -> None:
        """Start a new episode, serializing its gate layout (random per-episode).

        Args:
            index: 1-based episode/hero number.
            gates: Iterable of ``(pos, radius)`` pairs, or an ``(N, 4)`` array of
                ``[x, y, z, radius]`` rows — the gates for THIS episode.
            drone: Flat drone index this episode records (for traceability).
            dr: Live per-drone domain-randomization params, or ``None`` for a no-op episode.
            oracle_lap: Speed-oracle target lap time (s) for this course.
        """
        self._current = {
            "index": int(index),
            "drone": int(drone),
            "gates": _gates_list(gates),
            "dr": dr,
            "oracle_lap": float(oracle_lap) if oracle_lap is not None else None,
            "summary": {},
            "frames": [],
        }

    def add_frame(
        self,
        *,
        t: float,
        step: int,
        pos: Any,
        quat: Any,
        rpy: Any,
        vel: Any,
        angvel: Any,
        action: Any,
        action_diffaero: Any,
        reward: float,
        cum_reward: float,
        gate_idx: int,
        dist_to_gate: float,
        laps: int,
        passed: bool = False,
        crashed: bool = False,
        obs: Any = None,
    ) -> None:
        """Append one control-step frame to the current episode (see the module schema)."""
        if self._current is None:
            raise RuntimeError("add_frame() called before begin_episode()")
        self._current["frames"].append(_build_frame(
            t=t, step=step, pos=pos, quat=quat, rpy=rpy, vel=vel, angvel=angvel,
            action=action, action_diffaero=action_diffaero, reward=reward,
            cum_reward=cum_reward, gate_idx=gate_idx, dist_to_gate=dist_to_gate,
            laps=laps, passed=passed, crashed=crashed, obs=obs,
        ))

    def add_group_episode(
        self,
        index: int,
        gates: Any,
        tracks: list[dict[str, Any]],
        *,
        oracle_lap: float | None = None,
    ) -> None:
        """Append a **swarm group episode**: several drones flying ONE shared course (v2).

        Used for ``n_agents > 1`` tasks, where the recorded heroes are all agents of a single
        env — so they coexist on the same gates and should render together as one scene. Each
        track's frames are coerced exactly like :meth:`add_frame`. The lead track (``tracks[0]``)
        is mirrored onto the episode-level ``drone``/``dr``/``summary``/``frames`` so a v1 reader
        (e.g. the matplotlib pack) still sees a valid single-drone episode.

        Args:
            index: 1-based episode number.
            gates: The shared course (same accepted forms as :meth:`begin_episode`).
            tracks: One dict per drone: ``{"drone": int, "dr": {...}|None, "summary": {...},
                "frames": [<add_frame kwargs dict>, ...]}``.
            oracle_lap: Speed-oracle target lap time (s) for the shared course.
        """
        if not tracks:
            raise ValueError("add_group_episode() requires at least one track")
        drones = [
            {
                "drone": int(tr["drone"]),
                "dr": tr.get("dr"),
                "summary": dict(tr.get("summary", {})),
                "frames": [_build_frame(**fr) for fr in tr["frames"]],
            }
            for tr in tracks
        ]
        lead = drones[0]
        self._episodes.append({
            "index": int(index),
            "drone": lead["drone"],
            "gates": _gates_list(gates),
            "dr": lead["dr"],
            "oracle_lap": float(oracle_lap) if oracle_lap is not None else None,
            "summary": lead["summary"],
            "frames": lead["frames"],
            "drones": drones,
        })

    def end_episode(self, summary: dict[str, Any]) -> None:
        """Close the current episode, attaching its summary."""
        if self._current is None:
            raise RuntimeError("end_episode() called before begin_episode()")
        self._current["summary"] = dict(summary)
        self._episodes.append(self._current)
        self._current = None

    def to_dict(self) -> dict[str, Any]:
        """Assemble the full replay document (includes any open episode)."""
        episodes = list(self._episodes)
        if self._current is not None:
            episodes.append(self._current)
        return {
            "format": REPLAY_FORMAT,
            "version": REPLAY_VERSION,
            "meta": self.meta,
            "episodes": episodes,
        }

    def save(self, path: str | Path) -> Path:
        """Write the document to ``path`` as JSON (gzip-compressed if it ends in ``.gz``)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self.to_dict())
        if path.suffix == ".gz":
            with gzip.open(path, "wt", encoding="utf-8") as fh:
                fh.write(text)
        else:
            path.write_text(text, encoding="utf-8")
        return path


def _gates_list(gates: Any) -> list[dict[str, Any]]:
    """Serialize gates to ``[{"pos": [x,y,z], "radius": r}, ...]``.

    Accepts either an iterable of ``(pos, radius)`` pairs or an ``(N, 4)`` array of
    ``[x, y, z, radius]`` rows (e.g. torch/numpy from ``gate_pos``/``gate_rad``).
    """
    arr = np.asarray(_to_numpy(gates), dtype=np.float64)
    if arr.ndim == 2 and arr.shape[1] == 4:
        return [{"pos": [float(r[0]), float(r[1]), float(r[2])], "radius": float(r[3])} for r in arr]
    out: list[dict[str, Any]] = []
    for g in gates:
        pos, radius = g
        out.append({"pos": _vec(pos), "radius": float(radius)})
    return out


def _to_numpy(x: Any) -> Any:
    """Best-effort conversion to a numpy array (handles torch tensors without importing torch)."""
    if hasattr(x, "detach"):
        x = x.detach()
    if hasattr(x, "cpu"):
        x = x.cpu()
    if hasattr(x, "numpy"):
        try:
            return x.numpy()
        except Exception:
            pass
    return x


def load_run(path: str | Path) -> dict[str, Any]:
    """Load a replay file written by :class:`RunRecorder` (gzip-transparent)."""
    path = Path(path)
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    return json.loads(path.read_text(encoding="utf-8"))
