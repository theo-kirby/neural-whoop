from typing import Tuple

import torch
from diffaero.utils import p3d_compat as p3d_transforms  # neural-whoop: pure-torch shim
from omegaconf import DictConfig

class BaseController:
    """Convert the action from RL agent to force and torques to be applied on the drone."""
    def __init__(
        self,
        mass: torch.Tensor,
        inertia: torch.Tensor,
        gravity: torch.Tensor,
        cfg: DictConfig,
        device: torch.device
    ):
        self.cfg = cfg
        self.device = device
        self.mass = mass
        self.inertia = inertia
        self.gravity = gravity
        self.thrust_ratio: float = cfg.thrust_ratio
        self.torque_ratio: float = cfg.torque_ratio
        
        # lower bound of controller output (actual normed force & torque)
        self.min_thrust = torch.tensor(cfg.min_normed_thrust, device=device)
        self.min_torque = torch.tensor(list(cfg.min_normed_torque), device=device)
        
        # upper bound of controller output (actual normed force & torque)
        self.max_thrust = torch.tensor(cfg.max_normed_thrust, device=device)
        self.max_torque = torch.tensor(list(cfg.max_normed_torque), device=device)
    
    def __call__(self, *args, **kwargs) -> Tuple[torch.Tensor, torch.Tensor]:
        raise NotImplementedError

    def postprocess(self, normed_thrust, normed_torque):
        # type: (torch.Tensor, torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]
        normed_torque = normed_torque * self.torque_ratio
        normed_thrust = normed_thrust * self.thrust_ratio
        # compensate gravity
        if self.cfg.compensate_gravity:
            normed_thrust += 1.
        thrust = normed_thrust * self.gravity * self.mass
        torque = normed_torque * self.inertia
        return thrust, torque


class RateController(BaseController):
    """
    Body Rate Controller.
    
    Take desired thrust, roll rate, picth rate, and yaw rate as input
    and output actual force and torque to be applied on the robot.
    """
    def __init__(
        self,
        mass: torch.Tensor,
        inertia: torch.Tensor,
        gravity: torch.Tensor,
        cfg: DictConfig,
        device: torch.device
    ):
        super().__init__(mass, inertia, gravity, cfg, device)
        self.K_angvel = torch.tensor(cfg.K_angvel, device=device)
        
        # lower bound of controller input (action)
        self.min_action = torch.tensor([
            cfg.min_normed_thrust,
            cfg.min_roll_rate,
            cfg.min_pitch_rate,
            cfg.min_yaw_rate
        ], device=device)
        
        # upper bound of controller input (action)
        self.max_action = torch.tensor([
            cfg.max_normed_thrust,
            cfg.max_roll_rate,
            cfg.max_pitch_rate,
            cfg.max_yaw_rate
        ], device=device)
    
    def __call__(self, q_xyzw, w, action):
        # type: (torch.Tensor, torch.Tensor, torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]

        # NEURAL-WHOOP EDIT (2026-08-01): ``w`` is ALREADY body-frame, so the upstream
        # ``actual_angvel_b = R_i2b @ w`` rotated it a second time. The closed loop was
        # ``w_dot = K(u - R w)`` instead of ``K(u - w)``, whose eigenvalues are -K and
        # -K*exp(+-i*theta) -- real part ``-K*cos(theta)``, i.e. DIVERGENT past 90 deg of
        # attitude. Level flight has R ~ I so nothing noticed; a non-planar acro maneuver
        # does. Measured on the hand-authored orbit reference (docs/REFERENCE_MANEUVER.md):
        # 17.65 m of position error on a 1 m circle, flat across 20/5/1 ms control steps
        # (instability, not discretization), versus 1.80 cm with this line corrected.
        # ``w`` is body-frame at the call site by construction: quadrotor.py:123 applies
        # ``M = tau - w x Jw`` and quadrotor.py:137 integrates ``q_dot = 0.5 q (x) [w,0]``,
        # both body-frame conventions. See CLAUDE.md "Vendored DiffAero edits".
        desired_angvel_b = action[:, 1:]
        actual_angvel_b = w
        angvel_err = desired_angvel_b - actual_angvel_b
        
        # Ω × JΩ
        cross = torch.cross(actual_angvel_b, (self.inertia @ actual_angvel_b.unsqueeze(-1)).squeeze(-1), dim=1)
        cross.div_(torch.max(cross.norm(dim=-1, keepdim=True) / 100,
                             torch.tensor(1., device=cross.device)).detach())
        angacc = self.torque_ratio * self.K_angvel * angvel_err
        torque = (self.inertia @ angacc.unsqueeze(-1)).squeeze(-1) + cross
        thrust = action[:, 0] * self.thrust_ratio * self.gravity * self.mass
        return thrust, torque