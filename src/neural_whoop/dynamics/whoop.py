"""WhoopDynamics: the DiffAero adapter — whoop-scale airframe + CTBR control allocation.

Wraps DiffAero's differentiable batched :class:`QuadrotorModel` (RK4 rigid body with drag,
inertia, gyroscopic coupling, and a body-rate controller — CTBR-native) with:

- **Whoop-scale parameters** (a ~32 g tiny-whoop, not DiffAero's ~1 kg default), exposed as a
  :class:`WhoopParams` dataclass that builds the OmegaConf config DiffAero expects.
- **Agent flattening**: multi-agent envs flatten ``(n_envs, n_agents)`` into a single
  ``n_drones = n_envs * n_agents`` dynamics batch with ``n_agents=1`` inside DiffAero. This
  sidesteps DiffAero's single-batch rate controller (its ``bmm`` path is 3-D only) and keeps
  multi-agent coupling (collisions, relative observations) in *our* env/task layer. The
  baseline gate-race task runs ``n_agents=1``; swarm tasks just raise it.
- **Airframe domain randomization** refreshed per-episode *in place* (preserving tensor
  identity so the controller's mass/inertia references stay live).

State layout (DiffAero ``QuadrotorModel``, per drone, length 13): ``[p(3), q_xyzw(4),
v_world(3), w_body(3)]``. The body angular velocity ``w`` is the gyro signal the obs uses.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import Tensor

import neural_whoop  # noqa: F401 - ensures third_party/diffaero is importable
from diffaero.dynamics.quadrotor import QuadrotorModel
from diffaero.utils.math import quaternion_to_euler
from omegaconf import OmegaConf


def _uniform(default: float, lo: float, hi: float, enabled: bool = True) -> dict:
    return {"default": default, "enabled": enabled, "min": lo, "max": hi}


@dataclass
class WhoopParams:
    """Whoop-scale airframe + controller parameters (a ~32 g tiny-whoop).

    Ranges are the airframe domain-randomization band (build tolerance). Inertias and drag are
    order-of-magnitude estimates for a 65 mm-class quad; the autonomous agent is free to
    retune these (it's part of the sim2real optimization playground). The controller block is
    DiffAero's :class:`RateController` (CTBR): ``K_angvel`` is the rate-loop bandwidth.
    """

    # Airframe (SI units): mass kg, arm length m, torque constant, inertias kg·m^2, drag.
    mass: tuple[float, float, float] = (0.032, 0.028, 0.036)
    arm_l: tuple[float, float, float] = (0.032, 0.028, 0.036)
    c_tau: tuple[float, float, float] = (0.0066, 0.005, 0.008)
    J_xy: tuple[float, float, float] = (2.3e-5, 2.0e-5, 2.6e-5)
    J_z: tuple[float, float, float] = (4.0e-5, 3.5e-5, 4.5e-5)
    D_xy: tuple[float, float, float] = (0.10, 0.08, 0.12)
    D_z: tuple[float, float, float] = (0.10, 0.08, 0.12)
    g: float = 9.81
    # State clamps (generous; kept above commanded rates so they don't bite).
    max_w_xy: float = 40.0
    max_w_z: float = 16.0
    max_T: float = 1.0
    min_T: float = 0.0
    # Integration.
    dt: float = 0.02            # 50 Hz control
    n_substeps: int = 2         # -> 100 Hz physics
    solver_type: str = "rk4"
    alpha: float = 1.0          # gradient-decay factor (for differentiable RL; PPO detaches)
    # Controller (CTBR / body-rate). Rate limits here must cover the policy's commanded range.
    K_angvel: tuple[float, float, float] = (16.0, 16.0, 8.0)
    max_normed_thrust: float = 6.0
    max_roll_rate: float = 40.0
    max_pitch_rate: float = 40.0
    max_yaw_rate: float = 16.0
    randomize_airframe: bool = True

    def to_diffaero_cfg(self, n_drones: int):
        """Build the OmegaConf ``DictConfig`` DiffAero's ``QuadrotorModel`` consumes."""
        rnd = self.randomize_airframe
        return OmegaConf.create(
            {
                "name": "quadrotor", "n_envs": n_drones, "n_agents": 1,
                "dt": self.dt, "alpha": self.alpha, "g": self.g,
                "action_frame": "body",
                "m": _uniform(*self.mass, enabled=rnd),
                "arm_l": _uniform(*self.arm_l, enabled=rnd),
                "c_tau": _uniform(*self.c_tau, enabled=rnd),
                "J": {"xy": _uniform(*self.J_xy, enabled=rnd), "z": _uniform(*self.J_z, enabled=rnd)},
                "D": {"xy": _uniform(*self.D_xy, enabled=rnd), "z": _uniform(*self.D_z, enabled=rnd)},
                "max_w_xy": self.max_w_xy, "max_w_z": self.max_w_z,
                "max_T": self.max_T, "min_T": self.min_T,
                "solver_type": self.solver_type, "n_substeps": self.n_substeps,
                "controller": {
                    "compensate_gravity": False,
                    "min_normed_thrust": 0.0, "max_normed_thrust": self.max_normed_thrust,
                    "min_roll_rate": -self.max_roll_rate, "max_roll_rate": self.max_roll_rate,
                    "min_pitch_rate": -self.max_pitch_rate, "max_pitch_rate": self.max_pitch_rate,
                    "min_yaw_rate": -self.max_yaw_rate, "max_yaw_rate": self.max_yaw_rate,
                    "thrust_ratio": 1.0, "torque_ratio": 1.0,
                    "min_normed_torque": [-20.0, -20.0, -20.0],
                    "max_normed_torque": [20.0, 20.0, 20.0],
                    "K_angvel": list(self.K_angvel),
                },
            }
        )


class WhoopDynamics:
    """Batched whoop dynamics over ``n_drones = n_envs * n_agents`` flattened drones."""

    def __init__(
        self,
        n_drones: int,
        params: WhoopParams | None = None,
        device: torch.device | str = "cuda",
        generator: torch.Generator | None = None,
    ):
        self.params = params or WhoopParams()
        self.n = n_drones
        self.dev = torch.device(device)
        self.gen = generator
        self.dt = self.params.dt
        cfg = self.params.to_diffaero_cfg(n_drones)
        self.model = QuadrotorModel(cfg, self.dev)
        # State saturation limits. DiffAero defines _X_ub/_X_lb but never applies them in
        # step(); with a whoop's tiny inertia the RK4 rotational dynamics go numerically
        # unstable once body rates random-walk past the stability limit (~stability/dt), so we
        # saturate rates (and velocity, defensively) each step. Physically the gyro/airframe
        # saturates anyway, so this is a faithful guard, not a hack.
        self._w_max = torch.tensor(
            [self.params.max_w_xy, self.params.max_w_xy, self.params.max_w_z], device=self.dev
        )
        self._v_max = 30.0
        # DiffAero zero-initialises the state, including an all-zero (degenerate) quaternion,
        # which blows up the controller's quaternion->matrix on the first step. Initialise to a
        # valid identity attitude at z=1 so raw dynamics are usable before any task reset.
        with torch.no_grad():
            self.model._state.zero_()
            self.model._state[:, 6] = 1.0   # qw (xyzw) = 1 -> identity attitude
            self.model._state[:, 2] = 1.0   # z = 1 m
        # The airframe randomizers (UniformRandomizer instances) we refresh in place per reset.
        self._airframe = [
            self.model._m, self.model._arm_l, self.model._c_tau,
            self.model.J_xy, self.model.J_z, self.model.D_xy, self.model.D_z,
        ]
        if self.params.randomize_airframe:
            self.refresh_airframe(torch.arange(n_drones, device=self.dev))

    # --- state accessors (all detached, shape (n_drones, ...)) ---
    @property
    def pos(self) -> Tensor:
        return self.model._state[:, 0:3].detach()

    @property
    def quat_xyzw(self) -> Tensor:
        return self.model._state[:, 3:7].detach()

    @property
    def vel_world(self) -> Tensor:
        return self.model._state[:, 7:10].detach()

    @property
    def ang_vel_body(self) -> Tensor:
        """Body-frame angular velocity (gyro), ``[p, q, r]`` — the obs uses this directly."""
        return self.model._state[:, 10:13].detach()

    @property
    def R(self) -> Tensor:
        """Body->world rotation matrices, shape ``(n, 3, 3)``."""
        return self.model.R

    @property
    def rpy(self) -> Tensor:
        """Roll/pitch/yaw (radians), shape ``(n, 3)``."""
        return quaternion_to_euler(self.quat_xyzw)

    # --- stepping ---
    def step(self, ctbr: Tensor) -> None:
        """Advance one control step with a DiffAero-convention CTBR action ``(n, 4)``."""
        self.model.step(ctbr)
        with torch.no_grad():
            st = self.model._state
            st[:, 10:13] = st[:, 10:13].clamp(-self._w_max, self._w_max)
            st[:, 7:10] = st[:, 7:10].clamp(-self._v_max, self._v_max)

    def add_velocity(self, dv: Tensor) -> None:
        """Add a world-frame velocity delta (e.g. wind) to every drone, shape ``(n, 3)``."""
        with torch.no_grad():
            self.model._state[:, 7:10] += dv

    def add_body_rate(self, dw: Tensor) -> None:
        """Add a body-frame angular-velocity delta (e.g. an impulse tumble), shape ``(n, 3)``.

        Mirrors :meth:`add_velocity` for the rate channel, then re-clamps to ``±w_max`` so a kick
        can't push the rates past the saturation guard :meth:`step` enforces.
        """
        with torch.no_grad():
            st = self.model._state
            st[:, 10:13] += dw
            st[:, 10:13] = st[:, 10:13].clamp(-self._w_max, self._w_max)

    # --- reset ---
    def set_state(
        self, idx: Tensor, pos: Tensor, vel: Tensor, quat_xyzw: Tensor, ang_vel: Tensor
    ) -> None:
        """Hard-set the full state for drones ``idx`` (used on episode reset)."""
        with torch.no_grad():
            st = self.model._state
            st[idx, 0:3] = pos
            st[idx, 3:7] = quat_xyzw
            st[idx, 7:10] = vel
            st[idx, 10:13] = ang_vel
        self.model.reset_idx(idx)

    def refresh_airframe(self, idx: Tensor) -> None:
        """Resample airframe DR for drones ``idx`` *in place* (preserving tensor identity).

        In-place masked writes keep the controller's live references to mass/inertia valid;
        the controller's cached inertia matrix is then rebuilt from the refreshed values.
        """
        if not self.params.randomize_airframe or idx.numel() == 0:
            return
        with torch.no_grad():
            for r in self._airframe:
                if not getattr(r, "enabled", True):
                    continue
                new = torch.rand(r.value.shape, device=self.dev, generator=self.gen) * (r.high - r.low) + r.low
                r.value[idx] = new[idx]
            # Keep the controller's mass/inertia consistent with the refreshed airframe.
            self.model.controller.mass = self.model._m.value
            self.model.controller.inertia = self.model._J

    def detach(self) -> None:
        """Detach the dynamics graph (call between PPO rollout segments)."""
        self.model.detach()
