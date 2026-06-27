"""swarm_race: the first multi-drone (``n_agents > 1``) swarm task — shared-track gate racing
with collision avoidance.

The pivot off single-drone ``gate_race`` (Flywheel hop-13): ``n_agents`` drones share **one**
procedurally-generated closed course and race it under a shared policy. They spawn spread around
the origin and must fly the same gate sequence *while avoiding each other* — the first task where
the inter-agent coupling (collisions, neighbour observation) is real. The env already flattens
``(n_envs, n_agents) -> n_drones`` and resets per-env, so this is pure task-layer work: a neighbour
observation, a collision penalty, and a swarm metric. No env changes.

Observation (length 20): the single-drone racing obs (obs-v4 11 + next-gate lookahead 3 = 14) plus
the body-frame relative **position** (3) and relative **velocity** (3) of each drone's nearest
in-env neighbour. The neighbour vector is what lets a tiny shared policy reason about closing
geometry and keep separation. (obs_dim grows 14 -> 20 -> MCU deploy-size flag, per CLAUDE.md.)

Reward (per step) = the gate_race racing reward (progress + gate/lap bonuses − time − smoothness −
boundary crash) **minus a collision penalty** when a drone comes within ``collision_radius`` of any
neighbour. Termination is per-env (the env contract): an env's episode ends when **any** of its
drones crashes out of the arena **or** a collision occurs — shared fate, so a collision is costly
for the whole swarm, which is the pressure that makes coordinated, separated racing emerge.

Decision metric = swarm lap throughput at a bounded collision rate: ``lap_completion_rate`` (frac of
drones that lapped), ``collision_rate_per_step`` (must stay bounded), and ``best_lap_time``. GREEN =
coordinated racing emerges (drones lap without collision collapse); RED = collision collapse
(completion ~0 / collisions saturate).
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
class SwarmRaceConfig:
    """Tunable config for :class:`SwarmRaceTask` (extends the gate_race playground to a swarm)."""

    n_agents: int = 3               # drones sharing each course (the swarm size)
    n_gates: int = 5
    episode_len: int = 600          # steps; at dt=0.02 -> 12 s
    v_ref: float = 4.0
    oracle_model: str = "pathlen"
    oracle_v_max: float = 7.0
    oracle_a_max: float = 25.0
    oracle_a_lat: float = 23.0
    # Reward weights (racing terms mirror gate_race; collision is the new swarm term).
    progress_scale: float = 1.0
    gate_bonus: float = 5.0
    lap_bonus: float = 20.0
    crash_penalty: float = 10.0
    time_penalty: float = 0.05
    smoothness_penalty: float = 0.001
    alive_bonus: float = 0.01
    collision_penalty: float = 10.0  # per-drone penalty when inside collision_radius of a neighbour
    collision_radius: float = 0.25   # m centre-to-centre; below this counts as a collision
    # Arena / course geometry.
    arena_radius: float = 4.5
    gate_radius: float = 0.45
    z_min: float = 0.7
    z_max: float = 2.3
    # Gate spacing of the procedural walk (see GateRaceConfig): defaults reproduce the tight
    # course; raise with arena_radius/bound_xy for spread-out swarm tracks.
    step_min: float = 1.5
    step_max: float = 2.8
    max_turn_deg: float = 60.0
    # Crash bounds.
    bound_xy: float = 6.0
    bound_z_min: float = 0.15
    bound_z_max: float = 4.0
    spawn_height: float = 1.0
    spawn_spread: float = 0.6        # radius of the spawn ring so drones start well-separated


@register_task("swarm_race")
class SwarmRaceTask(DroneTask):
    """Multi-drone shared-track gate racing with collision avoidance (first swarm task)."""

    obs_dim = OBS_DIM + 3 + 6  # obs-v4 (11) + next-gate lookahead (3) + neighbour rel pos+vel (6) = 20

    def __init__(self, **kwargs):
        self.cfg = SwarmRaceConfig(**kwargs)
        if self.cfg.n_agents < 2:
            raise ValueError("swarm_race needs n_agents >= 2 (it is a multi-drone task).")
        self.n_agents = self.cfg.n_agents
        self.episode_len = self.cfg.episode_len
        self._oracle = OracleEstimator()
        self._arena = course_mod.ArenaSpec(
            radius=self.cfg.arena_radius, z_min=self.cfg.z_min, z_max=self.cfg.z_max,
            gate_radius=self.cfg.gate_radius, step_min=self.cfg.step_min,
            step_max=self.cfg.step_max, max_turn_deg=self.cfg.max_turn_deg,
        )
        self._bounds = Bounds(xy=self.cfg.bound_xy, z_min=self.cfg.bound_z_min, z_max=self.cfg.bound_z_max)
        self._feasible_oracle = oracle_mod.FeasibleOracle(
            v_max=self.cfg.oracle_v_max, a_max=self.cfg.oracle_a_max,
            a_lat=self.cfg.oracle_a_lat, corner_dev=self.cfg.gate_radius,
        )

    # --- lifecycle ---
    def setup(self, env) -> None:
        if env.n_agents != self.cfg.n_agents:
            raise ValueError(f"swarm_race expects n_agents={self.cfg.n_agents} (env has {env.n_agents}).")
        n, dev, ng = env.n_drones, env.device, self.cfg.n_gates
        # Per-drone racing state (course is shared per env -> replicated to each agent).
        self.gate_pos = torch.zeros(n, ng, 3, device=dev)
        self.gate_rad = torch.zeros(n, ng, device=dev)
        self.target = torch.zeros(n, device=dev, dtype=torch.long)
        self.prev_dist = torch.zeros(n, device=dev)
        self.laps = torch.zeros(n, device=dev, dtype=torch.long)
        self.gates_total = torch.zeros(n, device=dev, dtype=torch.long)
        self.lap_start = torch.zeros(n, device=dev)
        self.last_lap = torch.full((n,), float("nan"), device=dev)
        self.best_lap = torch.full((n,), float("inf"), device=dev)
        self.oracle_lap = torch.zeros(n, device=dev)
        self.last_valid = torch.zeros(n, 3, device=dev)
        # Swarm metrics: collision counter + nearest-neighbour separation snapshot (accumulated
        # across the whole rollout; not zeroed on reset so the rate covers all drone-steps).
        self.collision_count = torch.zeros(n, device=dev)
        self.last_min_sep = torch.full((n,), float("nan"), device=dev)
        self._step_count = 0  # host-side int (no GPU sync); total reward_and_done calls
        self._dev = dev

    def reset(self, env, env_idx: Tensor) -> None:
        k = env_idx.numel()
        na = self.cfg.n_agents
        # One shared course per env, replicated to that env's agents (env-major drone order).
        fc = getattr(env, "fixed_course", None)
        if fc is not None:
            # Studio: every env flies the ONE chosen course (broadcast across envs and agents).
            pos = fc[0].to(self._dev).unsqueeze(0).expand(k, -1, -1).clone()
            rad = fc[1].to(self._dev).unsqueeze(0).expand(k, -1).clone()
        else:
            pos, rad = course_mod.random_courses(
                k, self.cfg.n_gates, self._arena, device=self._dev, generator=env.gen
            )
        d_idx = env.drone_idx(env_idx)                     # (k*na,) env-major
        pos_d = pos.repeat_interleave(na, dim=0)           # (k*na, ng, 3)
        rad_d = rad.repeat_interleave(na, dim=0)
        self.gate_pos[d_idx] = pos_d
        self.gate_rad[d_idx] = rad_d
        self.target[d_idx] = 0
        self.laps[d_idx] = 0
        self.gates_total[d_idx] = 0
        self.lap_start[d_idx] = 0.0
        self.last_lap[d_idx] = float("nan")
        self.best_lap[d_idx] = float("inf")

        if self.cfg.oracle_model == "feasible":
            self.oracle_lap[d_idx] = oracle_mod.feasible_lap_time(pos_d, self._feasible_oracle)
        else:
            self.oracle_lap[d_idx] = oracle_mod.pathlen_lap_time(pos_d, self.cfg.v_ref)

        # Spawn agents spread around a small ring so they start well-separated, all facing gate 0.
        ang = (2.0 * torch.pi / na) * torch.arange(na, device=self._dev)       # (na,)
        ring = torch.stack([ang.cos(), ang.sin(), torch.zeros_like(ang)], dim=-1) * self.cfg.spawn_spread
        jitter = (torch.rand(k, na, 3, device=self._dev, generator=env.gen) - 0.5) * 0.2
        jitter[..., 2] = 0.0
        spawn = ring.unsqueeze(0) + jitter                                     # (k, na, 3)
        spawn[..., 2] += self.cfg.spawn_height
        spawn = spawn.reshape(k * na, 3)
        gate0 = pos_d[:, 0]                                                     # (k*na, 3)
        yaw = torch.atan2(gate0[:, 1] - spawn[:, 1], gate0[:, 0] - spawn[:, 0])
        env.spawn(d_idx, spawn, yaw=yaw)
        self.last_valid[d_idx] = gate0 - spawn
        self.prev_dist[d_idx] = (gate0 - spawn).norm(dim=-1)

    # --- neighbour geometry ---
    def _gate(self, idx: Tensor) -> tuple[Tensor, Tensor]:
        ar = torch.arange(self.gate_pos.shape[0], device=self._dev)
        cur = self.gate_pos[ar, idx]
        nxt = self.gate_pos[ar, (idx + 1) % self.cfg.n_gates]
        return cur, nxt

    def _nearest_neighbour(self, env) -> tuple[Tensor, Tensor, Tensor]:
        """Each drone's nearest in-env neighbour: world rel-pos, rel-vel ``(n_drones, 3)`` and
        the centre-to-centre distance ``(n_drones,)`` (rel = neighbour − self)."""
        na = self.cfg.n_agents
        pos = env.to_agents(env.dyn.pos)         # (E, na, 3)
        vel = env.to_agents(env.dyn.vel_world)   # (E, na, 3)
        diff = pos.unsqueeze(1) - pos.unsqueeze(2)   # [e, j, i] = pos_j - pos_i
        dist = diff.norm(dim=-1)                      # (E, na, na): dist[e, j, i]
        eye = torch.eye(na, device=self._dev, dtype=torch.bool)
        dist = dist.masked_fill(eye.unsqueeze(0), float("inf"))
        min_dist, nn = dist.min(dim=1)               # over j -> nearest neighbour of i: (E, na)
        nn_exp = nn.unsqueeze(-1).expand(-1, -1, 3)
        nbr_pos = torch.gather(pos, 1, nn_exp)
        nbr_vel = torch.gather(vel, 1, nn_exp)
        rel_pos = env.to_drones(nbr_pos - pos)
        rel_vel = env.to_drones(nbr_vel - vel)
        return rel_pos, rel_vel, env.to_drones(min_dist)

    # --- observation ---
    def observe(self, env) -> Tensor:
        pos, vel, R, rpy, w = (
            env.dyn.pos, env.dyn.vel_world, env.dyn.R, env.dyn.rpy, env.dyn.ang_vel_body,
        )
        cur, nxt = self._gate(self.target)
        cur_rel_body = world_to_body(cur - pos, R)
        cur_rel_body, _ = self._oracle.estimate(cur_rel_body)
        det = env.dr.cfg.detector
        if env.dr.cfg.enabled and not det.is_identity:
            cur_rel_body, _ = apply_detector_noise(cur_rel_body, det, self.last_valid, env.gen)
            self.last_valid = cur_rel_body
        vel_b = world_to_body(vel, R)
        obs11 = torch.cat([cur_rel_body, vel_b, rpy[..., 0:1], rpy[..., 1:2], w], dim=-1)
        nxt_rel_body = world_to_body(nxt - pos, R)
        # Nearest-neighbour relative pos/vel in body frame (the swarm-coupling channel).
        rel_pos_w, rel_vel_w, _ = self._nearest_neighbour(env)
        nbr_pos_b = world_to_body(rel_pos_w, R)
        nbr_vel_b = world_to_body(rel_vel_w, R)
        return torch.cat([obs11, nxt_rel_body, nbr_pos_b, nbr_vel_b], dim=-1).to(torch.float32)

    # --- reward / termination ---
    def reward_and_done(self, env, action: Tensor) -> tuple[Tensor, Tensor, dict]:
        c = self.cfg
        pos = env.dyn.pos
        cur, _ = self._gate(self.target)
        ar = torch.arange(env.n_drones, device=self._dev)
        cur_rad = self.gate_rad[ar, self.target]

        passed = course_mod.gate_passed(cur, env.prev_pos, pos, cur_rad)
        curr_dist = (cur - pos).norm(dim=-1)

        reward = c.progress_scale * (self.prev_dist - curr_dist) + c.alive_bonus - c.time_penalty
        reward = reward + c.gate_bonus * passed.float()
        reward = reward - smoothness_penalty(action, env.prev_action, c.smoothness_penalty)

        self.gates_total = self.gates_total + passed.long()
        new_target = torch.where(passed, (self.target + 1) % c.n_gates, self.target)
        lap_done = passed & (self.target == c.n_gates - 1)
        if bool(lap_done.any()):
            lap_time = env.sim_time.repeat_interleave(c.n_agents) - self.lap_start
            speed_factor = (self.oracle_lap / lap_time.clamp_min(1e-3)).clamp(0.25, 4.0)
            reward = reward + torch.where(lap_done, c.lap_bonus * speed_factor, torch.zeros_like(reward))
            self.last_lap = torch.where(lap_done, lap_time, self.last_lap)
            self.best_lap = torch.where(lap_done, torch.minimum(self.best_lap, lap_time), self.best_lap)
            self.laps = self.laps + lap_done.long()
            self.lap_start = torch.where(lap_done, env.sim_time.repeat_interleave(c.n_agents), self.lap_start)
        self.target = new_target

        cur2, _ = self._gate(self.target)
        self.prev_dist = (cur2 - pos).norm(dim=-1)

        # Swarm coupling: collision penalty + bounds crash.
        _, _, min_sep = self._nearest_neighbour(env)
        collided = min_sep < c.collision_radius
        reward = reward - c.collision_penalty * collided.float()
        crashed = is_crashed(pos, self._bounds)
        reward = reward - c.crash_penalty * crashed.float()

        # Swarm metric accumulators (not zeroed on reset -> rate over the whole rollout).
        self.collision_count = self.collision_count + collided.float()
        self.last_min_sep = min_sep
        self._step_count += 1

        # Per-env termination (env contract): an env ends if ANY of its drones fails.
        drone_fail = crashed | collided
        terminated_env = env.to_agents(drone_fail).any(dim=1)

        info = {"passed": passed, "crashed": crashed, "collided": collided}
        return reward, terminated_env, info

    def metrics(self, env) -> dict:
        finite = self.best_lap[torch.isfinite(self.best_lap)]
        finite_last = self.last_lap[torch.isfinite(self.last_lap)]
        sep = self.last_min_sep[torch.isfinite(self.last_min_sep)]
        denom = max(1, self._step_count) * env.n_drones
        return {
            "best_lap_time": finite.mean().item() if finite.numel() else float("nan"),
            "last_lap_time": finite_last.mean().item() if finite_last.numel() else float("nan"),
            "oracle_lap_time": self.oracle_lap.mean().item(),
            "laps_completed_mean": self.laps.float().mean().item(),
            "lap_completion_rate": (self.laps > 0).float().mean().item(),
            "collision_rate_per_step": self.collision_count.sum().item() / denom,
            "mean_min_separation": sep.mean().item() if sep.numel() else float("nan"),
            "n_agents": float(self.cfg.n_agents),
        }
