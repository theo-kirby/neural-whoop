"""gate_race: single-drone time-optimal gate racing with a speed oracle (the first baseline).

The beachhead task (locked decision #3): state/oracle-based, so it never touches the
Blackwell-broken camera path. The drone flies a procedurally-generated closed gate course as
fast as possible; the episode metric is **lap time** (minimize).

Observation (length 14): obs-v4 (11, body-frame, heading-invariant) where ``[gx, gy, gz]`` is
the body-frame vector to the **current** target gate (via the perception oracle, optionally
detector-corrupted), plus a 3-vector lookahead to the **next** gate (racing-line planning).

Speed oracle: a pragmatic point-mass timing reference. The closed-loop path length divided by
a reference cruise speed gives a **target lap time** (and per-gate split fractions) that both
shapes the reward (a lap-completion bonus scaled by ``oracle_time / actual_time``) and serves
as the eval baseline to beat. The agent is explicitly free to refine the oracle and reward —
that is the optimization playground.

Reward (per step) = progress toward the current gate + gate-pass bonus + lap-completion bonus
(speed-scaled) − time penalty − crash penalty − action-smoothness penalty. Termination = crash
(out of arena / ground / ceiling); truncation = episode time limit (env-applied).
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import Tensor

from neural_whoop import course as course_mod
from neural_whoop import oracle as oracle_mod
from neural_whoop.contract import OBS_DIM, world_to_body
from neural_whoop.envs.registry import DroneTask, register_task
from neural_whoop.perception.estimator import OracleEstimator, apply_detector_noise
from neural_whoop.reward import Bounds, is_crashed, smoothness_penalty


@dataclass
class GateRaceConfig:
    """Tunable config for :class:`GateRaceTask` (the agent's reward/curriculum playground)."""

    n_gates: int = 5
    episode_len: int = 600          # steps; at dt=0.02 -> 12 s, room for several laps
    v_ref: float = 4.0              # m/s reference cruise speed for the timing oracle
    # Timing oracle (lap-time yardstick + lap-bonus speed_factor). "pathlen" = original
    # geometry-blind path-length/v_ref (default; baseline-reproducing). "feasible" = honest
    # accel + corner limited reference (oracle_v_max/a_max/a_lat), calibrated from flown
    # telemetry — flywheel node bd57f350.
    oracle_model: str = "pathlen"
    oracle_v_max: float = 7.0
    oracle_a_max: float = 25.0
    oracle_a_lat: float = 23.0
    # Reward weights.
    progress_scale: float = 1.0
    gate_bonus: float = 5.0
    lap_bonus: float = 20.0         # base bonus for completing a lap (× speed factor)
    crash_penalty: float = 10.0
    time_penalty: float = 0.02
    smoothness_penalty: float = 0.001
    alive_bonus: float = 0.01
    # Arena / course geometry.
    arena_radius: float = 4.5
    gate_radius: float = 0.45
    z_min: float = 0.7
    z_max: float = 2.3
    # Crash bounds.
    bound_xy: float = 6.0
    bound_z_min: float = 0.15
    bound_z_max: float = 4.0
    spawn_height: float = 1.0


@register_task("gate_race")
class GateRaceTask(DroneTask):
    """Time-optimal single-drone gate racing."""

    n_agents = 1
    obs_dim = OBS_DIM + 3  # obs-v4 (11) + next-gate lookahead (3)

    def __init__(self, **kwargs):
        self.cfg = GateRaceConfig(**kwargs)
        self.episode_len = self.cfg.episode_len
        self._oracle = OracleEstimator()
        self._arena = course_mod.ArenaSpec(
            radius=self.cfg.arena_radius, z_min=self.cfg.z_min, z_max=self.cfg.z_max,
            gate_radius=self.cfg.gate_radius,
        )
        self._bounds = Bounds(xy=self.cfg.bound_xy, z_min=self.cfg.bound_z_min, z_max=self.cfg.bound_z_max)
        self._feasible_oracle = oracle_mod.FeasibleOracle(
            v_max=self.cfg.oracle_v_max, a_max=self.cfg.oracle_a_max,
            a_lat=self.cfg.oracle_a_lat, corner_dev=self.cfg.gate_radius,
        )

    # --- lifecycle ---
    def setup(self, env) -> None:
        if env.n_agents != 1:
            raise ValueError("gate_race is single-drone (n_agents must be 1).")
        n, dev, ng = env.n_drones, env.device, self.cfg.n_gates
        self.gate_pos = torch.zeros(n, ng, 3, device=dev)
        self.gate_rad = torch.zeros(n, ng, device=dev)
        self.target = torch.zeros(n, device=dev, dtype=torch.long)   # current gate index
        self.prev_dist = torch.zeros(n, device=dev)
        self.laps = torch.zeros(n, device=dev, dtype=torch.long)
        self.gates_total = torch.zeros(n, device=dev, dtype=torch.long)
        self.lap_start = torch.zeros(n, device=dev)
        self.last_lap = torch.full((n,), float("nan"), device=dev)
        self.best_lap = torch.full((n,), float("inf"), device=dev)
        self.oracle_lap = torch.zeros(n, device=dev)
        self.last_valid = torch.zeros(n, 3, device=dev)              # detector stale-hold
        self._dev = dev

    def reset(self, env, env_idx: Tensor) -> None:
        k = env_idx.numel()
        pos, rad = course_mod.random_courses(
            k, self.cfg.n_gates, self._arena, device=self._dev, generator=env.gen
        )
        self.gate_pos[env_idx] = pos
        self.gate_rad[env_idx] = rad
        self.target[env_idx] = 0
        self.laps[env_idx] = 0
        self.gates_total[env_idx] = 0
        self.lap_start[env_idx] = 0.0
        self.last_lap[env_idx] = float("nan")
        self.best_lap[env_idx] = float("inf")

        # Timing oracle over the closed gate loop -> target lap time (the yardstick).
        if self.cfg.oracle_model == "feasible":
            self.oracle_lap[env_idx] = oracle_mod.feasible_lap_time(pos, self._feasible_oracle)
        else:
            self.oracle_lap[env_idx] = oracle_mod.pathlen_lap_time(pos, self.cfg.v_ref)

        # Spawn near origin facing gate 0.
        d_idx = env.drone_idx(env_idx)
        spawn = torch.zeros(k, 3, device=self._dev)
        spawn[:, 0] = torch.rand(k, device=self._dev, generator=env.gen) * 0.4 - 0.2
        spawn[:, 1] = torch.rand(k, device=self._dev, generator=env.gen) * 0.4 - 0.2
        spawn[:, 2] = self.cfg.spawn_height
        yaw = torch.atan2(pos[:, 0, 1] - spawn[:, 1], pos[:, 0, 0] - spawn[:, 0])
        env.spawn(d_idx, spawn, yaw=yaw)
        self.last_valid[d_idx] = pos[:, 0] - spawn
        self.prev_dist[d_idx] = (pos[:, 0] - spawn).norm(dim=-1)

    # --- observation ---
    def _gate(self, idx: Tensor) -> tuple[Tensor, Tensor]:
        """Current and next gate centers given per-drone target index ``idx`` (n,)."""
        ar = torch.arange(self.gate_pos.shape[0], device=self._dev)
        cur = self.gate_pos[ar, idx]
        nxt = self.gate_pos[ar, (idx + 1) % self.cfg.n_gates]
        return cur, nxt

    def observe(self, env) -> Tensor:
        pos, vel, R, rpy, w = (
            env.dyn.pos, env.dyn.vel_world, env.dyn.R, env.dyn.rpy, env.dyn.ang_vel_body,
        )
        cur, nxt = self._gate(self.target)
        cur_rel_world = cur - pos
        cur_rel_body = world_to_body(cur_rel_world, R)
        cur_rel_body, _ = self._oracle.estimate(cur_rel_body)
        det = env.dr.cfg.detector
        if env.dr.cfg.enabled and not det.is_identity:
            cur_rel_body, _ = apply_detector_noise(cur_rel_body, det, self.last_valid, env.gen)
            self.last_valid = cur_rel_body
        # obs-v4 (rebuild from the body-frame target vector + the rest of the state).
        vel_b = world_to_body(vel, R)
        obs11 = torch.cat([cur_rel_body, vel_b, rpy[..., 0:1], rpy[..., 1:2], w], dim=-1)
        nxt_rel_body = world_to_body(nxt - pos, R)
        return torch.cat([obs11, nxt_rel_body], dim=-1).to(torch.float32)

    # --- reward / termination ---
    def reward_and_done(self, env, action: Tensor) -> tuple[Tensor, Tensor, dict]:
        c = self.cfg
        pos = env.dyn.pos
        cur, _ = self._gate(self.target)
        ar = torch.arange(env.n_drones, device=self._dev)
        cur_rad = self.gate_rad[ar, self.target]

        # Gate pass: robust segment-sphere test over this step's path.
        passed = course_mod.gate_passed(cur, env.prev_pos, pos, cur_rad)
        curr_dist = (cur - pos).norm(dim=-1)

        reward = c.progress_scale * (self.prev_dist - curr_dist) + c.alive_bonus - c.time_penalty
        reward = reward + c.gate_bonus * passed.float()
        reward = reward - smoothness_penalty(action, env.prev_action, c.smoothness_penalty)

        # Advance the gate pointer on a pass; detect lap completion (wrap past the last gate).
        self.gates_total = self.gates_total + passed.long()
        new_target = torch.where(passed, (self.target + 1) % c.n_gates, self.target)
        lap_done = passed & (self.target == c.n_gates - 1)
        if bool(lap_done.any()):
            lap_time = env.sim_time - self.lap_start
            speed_factor = (self.oracle_lap / lap_time.clamp_min(1e-3)).clamp(0.25, 4.0)
            reward = reward + torch.where(lap_done, c.lap_bonus * speed_factor, torch.zeros_like(reward))
            self.last_lap = torch.where(lap_done, lap_time, self.last_lap)
            self.best_lap = torch.where(lap_done, torch.minimum(self.best_lap, lap_time), self.best_lap)
            self.laps = self.laps + lap_done.long()
            self.lap_start = torch.where(lap_done, env.sim_time, self.lap_start)
        self.target = new_target

        # Update progress distance to the (possibly new) target gate.
        cur2, _ = self._gate(self.target)
        self.prev_dist = (cur2 - pos).norm(dim=-1)

        crashed = is_crashed(pos, self._bounds)
        reward = reward - c.crash_penalty * crashed.float()

        terminated_env = crashed  # n_agents == 1 -> per-drone == per-env

        # Tensor-only info (no GPU->CPU sync in the hot path); scalars come from metrics().
        info = {"passed": passed, "crashed": crashed}
        return reward, terminated_env, info

    def metrics(self, env) -> dict:
        finite = self.best_lap[torch.isfinite(self.best_lap)]
        finite_last = self.last_lap[torch.isfinite(self.last_lap)]
        return {
            "best_lap_time": finite.mean().item() if finite.numel() else float("nan"),
            "last_lap_time": finite_last.mean().item() if finite_last.numel() else float("nan"),
            "oracle_lap_time": self.oracle_lap.mean().item(),
            "laps_completed_mean": self.laps.float().mean().item(),
            "lap_completion_rate": (self.laps > 0).float().mean().item(),
        }
