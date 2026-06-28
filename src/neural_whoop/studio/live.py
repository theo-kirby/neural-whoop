"""Live interactive Studio session — step a policy in real time under browser-driven disturbances.

Where :func:`neural_whoop.studio.rollout.studio_rollout` records a whole rollout to completion and
ships a finished replay, a :class:`LiveSession` is **stateful and steppable**: the WebSocket server
(:mod:`neural_whoop.studio.server`) advances it one control step at a time at ~50 Hz, applies the
disturbances the browser sends (wind, pushes, dropped blocks, hover-point moves), and streams each
frame back. It is the auto-stabilization beachhead's payoff: blow wind at the ``hover`` policy, shove
it, drop a (modeled) block on it, click to relocate its hover point, and watch it re-stabilize.

The disturbances ride the **same physics seam the policy trained against** — wind, push, and the
dropped-block tumble are all impulses through :meth:`WhoopDynamics.add_velocity` /
:meth:`~WhoopDynamics.add_body_rate` (the very seam :mod:`neural_whoop.randomization` drives during
training), so what the editor throws is exactly what the policy was hardened to reject.

Built off :func:`neural_whoop.studio.rollout.build_session` so drone-count→substrate mapping,
obs-stack matching, and ``fixed_course`` are identical to the record-then-playback path. Per-frame
fields come from :func:`neural_whoop.eval.rollout.hero_pose_snapshot`, the same extractor the
recorder uses, so the live wire-format can't drift from the replay schema (``docs/VISUAL_CONTRACT``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

#: Default disturbance magnitudes the editor's one-click buttons map to (world frame).
PUSH_SPEED = 3.0      # m/s velocity kick a "push" imparts
DROP_DOWN = 3.5       # m/s downward kick a dropped block imparts
DROP_LATERAL = 1.0    # m/s random lateral component of a dropped block
DROP_TUMBLE = 6.0     # rad/s body-rate tumble a dropped block imparts


class LiveSession:
    """A stateful, steppable live rollout with browser-driven disturbances.

    Construct via :meth:`build` (loads the policy + env off the shared session builder), then call
    :meth:`step` repeatedly; feed disturbances through :meth:`command` (or the typed setters). All
    GPU work stays on the session's device; :meth:`step` returns a JSON-native frame dict.
    """

    def __init__(self, session) -> None:
        import torch

        self._torch = torch
        self.session = session
        self.env = session.env
        self.agent = session.agent
        self.task_name = session.task_name
        self.heroes = session.heroes
        self.dev = self.env.device
        self.dt = float(self.env.dt)
        self.h = torch.tensor(self.heroes, device=self.dev, dtype=torch.long)
        # Mutable disturbance state.
        self.wind_vec = torch.zeros(3, device=self.dev)          # world-frame accel (m/s^2)
        self._dv_queue = torch.zeros(self.env.n_drones, 3, device=self.dev)  # pending linear kicks
        self._dw_queue = torch.zeros(self.env.n_drones, 3, device=self.dev)  # pending rate kicks
        self.paused = False
        self.step_idx = 0
        self.obs = self.env.reset_all()

    @classmethod
    def build(
        cls,
        policy_path: str | Path,
        *,
        drone_count: int = 1,
        dr: bool = False,
        seed: int = 0,
        course: str | None = None,
        device: str = "cuda",
        courses_dir: str | Path | None = None,
        runs_dir: str | Path | None = None,
    ) -> "LiveSession":
        """Build a live session for a chosen policy/drone-count (the same substrate as a rollout).

        ``dr`` defaults off: the **user** is the disturbance source in the editor, so the env's
        automatic seam DR is disabled by default and the live wind/impulses are applied on top of a
        clean baseline. A very long episode length (so the run doesn't auto-truncate mid-watch) is
        threaded through ``max_steps``.
        """
        from neural_whoop.studio.rollout import build_session

        sess = build_session(
            policy_path, course, drone_count, dr=dr, max_steps=200_000, seed=seed,
            device=device, courses_dir=courses_dir, runs_dir=runs_dir,
        )
        return cls(sess)

    @property
    def is_hover(self) -> bool:
        """Whether the policy is the hover task (the only family whose setpoint the editor can move)."""
        return hasattr(self.env.task, "setpoint")

    def info(self) -> dict:
        """Static descriptors the frontend needs to set up the live view (sent once on connect)."""
        si = self.env.task.scene_info() if hasattr(self.env.task, "scene_info") else {}
        return {
            "task": self.task_name,
            "drone_count": len(self.heroes),
            "dt": self.dt,
            "is_hover": self.is_hover,
            "scene_info": si or {},
            "meta": self.session.rec_meta,
        }

    # --- stepping ---
    def step(self) -> dict:
        """Advance one control step under the current disturbances; return a JSON frame dict."""
        torch = self._torch
        with torch.no_grad():
            action = self.agent.actor(self.obs).clamp(-1.0, 1.0)
            # Inject the live wind (continuous) + any queued one-shot impulses BEFORE the dynamics
            # step so they're integrated this step and reflected in the returned pose/obs — the same
            # add_velocity/add_body_rate seam the policy trained against.
            self.env.dyn.add_velocity(self.wind_vec.unsqueeze(0) * self.dt + self._dv_queue)
            self.env.dyn.add_body_rate(self._dw_queue)
            self._dv_queue.zero_()
            self._dw_queue.zero_()
            self.obs, _, _, _, _ = self.env.step(action)
            self.step_idx += 1
            return self._frame(action)

    def _frame(self, action) -> dict:
        from neural_whoop.eval.rollout import hero_pose_snapshot

        snap = hero_pose_snapshot(self.env, action, self.h)
        scene = snap["scene"]
        drones = []
        for j in range(len(self.heroes)):
            d = {
                "pos": snap["pos"][j].tolist(),
                "quat": snap["quat"][j].tolist(),
                "rpy": snap["rpy"][j].tolist(),
                "vel": snap["vel"][j].tolist(),
                "angvel": snap["angvel"][j].tolist(),
                "action": snap["action"][j].tolist(),
                "action_diffaero": snap["action_diffaero"][j].tolist(),
            }
            if scene:
                d["scene"] = {k: v[j].tolist() for k, v in scene.items()}
            drones.append(d)
        return {"step": self.step_idx, "t": self.step_idx * self.dt, "drones": drones}

    # --- command dispatch (browser messages) ---
    def command(self, msg: dict) -> None:
        """Apply one browser command message (dispatched by its ``type``)."""
        t = msg.get("type")
        if t == "wind":
            self.set_wind(msg.get("vec", [0.0, 0.0, 0.0]))
        elif t == "push":
            self.push(int(msg.get("drone", 0)), dv=msg.get("dv"), direction=msg.get("dir"))
        elif t == "drop":
            self.drop(int(msg.get("drone", 0)))
        elif t == "setpoint":
            self.set_setpoint(int(msg.get("drone", 0)), msg.get("pos", [0.0, 0.0, 1.0]))
        elif t == "reset":
            self.reset()
        elif t == "pause":
            self.paused = True
        elif t == "resume":
            self.paused = False

    def set_wind(self, vec) -> None:
        """Set the continuous world-frame wind acceleration (m/s^2)."""
        v = self._torch.as_tensor(vec, dtype=self.wind_vec.dtype, device=self.dev).reshape(-1)[:3]
        self.wind_vec = v

    def _drone_rows(self, drone: int):
        """Flat drone indices a UI ``drone`` selector targets: one drone, or all heroes if ``< 0``."""
        if drone < 0:
            return self.h
        d = max(0, min(int(drone), len(self.heroes) - 1))
        return self._torch.tensor([self.heroes[d]], device=self.dev, dtype=self._torch.long)

    def push(self, drone: int, *, dv=None, direction=None) -> None:
        """Queue a one-shot linear velocity kick (a shove). ``dv`` is an explicit world m/s vector;
        else ``direction`` (any world vector) is normalized to :data:`PUSH_SPEED`; else random horiz."""
        torch = self._torch
        rows = self._drone_rows(drone)
        if dv is not None:
            kick = torch.as_tensor(dv, dtype=torch.float32, device=self.dev).reshape(3)
        elif direction is not None:
            d = torch.as_tensor(direction, dtype=torch.float32, device=self.dev).reshape(3)
            kick = d / d.norm().clamp_min(1e-6) * PUSH_SPEED
        else:
            ang = float(torch.rand(1, device=self.dev) * 6.2831853)
            kick = torch.tensor([PUSH_SPEED * torch.cos(torch.tensor(ang)),
                                 PUSH_SPEED * torch.sin(torch.tensor(ang)), 0.0], device=self.dev)
        self._dv_queue[rows] += kick

    def drop(self, drone: int) -> None:
        """Queue a modeled dropped-block impulse: a downward + lateral velocity kick and a body-rate
        tumble (impulse-only — no real collision), the same shape the training impulse seam injects."""
        torch = self._torch
        rows = self._drone_rows(drone)
        lat = (torch.rand(2, device=self.dev) * 2 - 1) * DROP_LATERAL
        dv = torch.tensor([float(lat[0]), float(lat[1]), -DROP_DOWN], device=self.dev)
        dw = (torch.rand(3, device=self.dev) * 2 - 1) * DROP_TUMBLE
        self._dv_queue[rows] += dv
        self._dw_queue[rows] += dw

    def set_setpoint(self, drone: int, pos) -> None:
        """Relocate the hover setpoint for ``drone`` (hover task only; no-op otherwise)."""
        if not self.is_hover:
            return
        rows = self._drone_rows(drone)
        p = self._torch.as_tensor(pos, dtype=self.env.task.setpoint.dtype, device=self.dev).reshape(3)
        self.env.task.setpoint[rows] = p

    def reset(self) -> None:
        """Reset the env (resamples setpoints/spawns) and clear all live disturbance state."""
        self.obs = self.env.reset_all()
        self.wind_vec = self._torch.zeros(3, device=self.dev)
        self._dv_queue.zero_()
        self._dw_queue.zero_()
        self.step_idx = 0

    def close(self) -> None:
        """Drop references so the env/agent can be GC'd and GPU memory freed on disconnect."""
        self.env = None
        self.agent = None
        self.session = None
