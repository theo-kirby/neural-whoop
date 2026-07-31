"""acro_flip: a learned single-axis flip/roll — the first *agility* (acro) task.

The hover family solved attitude stabilization + open-loop trim; nothing in the catalog yet asks
the policy to throw the airframe through a large, deliberate rotation and catch it. ``acro_flip``
is that headline capability, and it needs **zero new hardware**: pure IMU + the existing act-v2
CTBR contract. The rate envelope is already acro-capable (``contract.py``
``ActionLimits.max_body_rate_rp_rps = 12`` rad/s ≈ 690°/s; the dynamics saturation at 40 rad/s
never bites), so no dynamics/contract changes are needed — just a new reward that *rewards the
rotation*.

The maneuver is a single learned behaviour discovered by reward shaping (no reference trajectory):
spin about the maneuver ``axis`` (roll → body-rate ``p``; pitch → ``q``) until an accumulated
signed rotation reaches ``Φ = 2π·n_rotations``, then return to stable, level flight. v1 is a fixed
single **barrel roll** (``axis="roll"``, ``n_rotations=1``, fixed direction); a pitch-flip is just
``configs/acro_flip_pitch.yaml``.

Observation (obs_dim 8, deploy-honest — IMU + the pilot's own clock, **no new sensor**)::

    [gravity_body(3), p, q, r, rotation_remaining(1), maneuver_phase(1)]

``gravity_body`` = world-down in the body frame (``Rᵀ·[0,0,-1]``) is unambiguous through a full
inversion, unlike euler roll/pitch which wrap / gimbal-lock mid-flip. ``p,q,r`` are the gyro
(valid even at high acro rates). ``rotation_remaining`` ∈ [1→0] is the *rotation* phase signal
(how much of the maneuver's angle is left), a gyro integral tracked internally here and by the
pilot's maneuver clock at deploy. There is **no altitude channel** — IMU-only has no reliable
onboard altitude, so altitude stays open-loop for the brief maneuver (the RPM thrust anchor
defends it at deploy). The downward VL53L1X is deliberately NOT used: it points sideways and then
up mid-flip, i.e. it is garbage exactly when the maneuver needs it. Altitude is used only in the
*reward* (privileged ground truth, the same pattern as ``hover``'s H2 terms).

``maneuver_phase`` ∈ [1→0] is the new (v2) channel and it is a **clock**, not a sensor:
``clamp(1 − t/T, 0, 1)`` over ``maneuver_len_s``, counting down across the whole window
(pop → rotate → catch). It is the same class of signal as ``rotation_remaining`` — something the
pilot supplies, free, at the trigger — and it exists because without it the maneuver's *start* is
unobservable. With obs-7 a level, at-rest drone is a fixed point: ``gravity_body`` is pure
attitude and carries no specific force, so a vertical thrust burst is INVISIBLE. The policy could
not tell "just spawned" from "0.2 s into a pop", so it could not time a pre-roll pop and had to
begin rotating immediately. Keeping both channels is what makes it robust: the clock lets the
policy *plan* (pop now, rotate now, catch now) while the gyro-integrated rotation signal keeps it
honest when DR makes the roll run long or short (a clock alone would run out mid-inversion under
a low rate-gain draw). In sim the maneuver IS the episode, so ``t_trigger`` = step 0 — which
matches deploy, where the pilot hands the acro policy control at exactly the trigger.

Reward (per step, phased) — v2 makes this a **point-in-space** flip, not a barrel roll:
a monotone, saturating rotation-progress term toward Φ (rewards the spin, can't be farmed by
over-spinning) + a one-time completion bonus on crossing Φ + a recover term (upright bell − spin
penalty, gated to *after* completion) − lateral station-keeping ‖xy − xy₀‖ throughout − an
**asymmetric** altitude penalty (heavy on sinking, light on rising, with ``pop_allow`` metres of
free headroom) − a recover-gated settle/return term − smoothness − crash. Termination = crash
(arena bounds); truncation = ``episode_len``. Spawn = level hover at ``z0``, at rest (the flip is
the *learned* behaviour, not an initial condition).

Why asymmetric altitude is the load-bearing change: a 2π roll at the 12 rad/s rate envelope takes
≥ 0.52 s, and a zero-thrust coast that long falls a long way. Entering with enough ``v_up`` puts the
apex mid-flip, and a few g of net thrust arrests the return. Net: up, then back, with ~zero lateral
(a coast applies no lateral force at all). The symmetric v1 ``alt_scale·|z − z₀|`` punished exactly
the pop that shape needs, while under-punishing the sink; and v1 had NO lateral term at all, so a
wide loop was simply what "maximise rotation, ignore translation" looks like.

**Numbers, corrected (2026-08-01).** This paragraph used to carry a worked example done *without
drag* — "falls ~1 m", ``v_up ≈ 2.4 m/s``, "returns at −2.4 m/s", "~+0.3 m up, ~−0.1 m down". Those
are off by 25-40% for this simulator, because ``D = 0.10`` on 32 g gives a 0.32 s drag time constant
and a 3.14 m/s terminal velocity, so drag steals a big share of the coast — but also caps the return
speed well below the pop speed, making the catch *easier* than the drag-free figure suggests. The
hand-authored reference (``docs/REFERENCE_MANEUVER.md``, ``scripts/reference_flip.py``) solves the
same maneuver exactly against this airframe and measures: pop to **+3.26 m/s**, return at
**−2.19 m/s**, **+0.617 m** of peak climb and **0.000 m** of altitude loss, over a **0.97 s** flip
with **0.180 m** of lateral drift. Use those, not arithmetic.

Note the mismatch that leaves: the reference's ``peak_climb`` (0.617 m, or 0.680 m for the
deployable variant) **exceeds** ``pop_allow`` below (0.4 m), so under the current reward the shape
we say we want collects a small ``rise_scale`` penalty. Raising ``pop_allow`` to ~0.7 is a training
decision, so it is recorded here rather than silently changed.

Metrics (ground truth): ``flip_success_rate`` (reached Φ **and** recovered level, no crash),
``mean_completion_time``, ``mean_altitude_loss`` (max ``z₀ − z``), ``max_lateral_drift``,
``peak_climb``, ``settle_pos_error``, ``post_recovery_tilt_deg``, ``crash_rate_per_step``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch
from torch import Tensor

from neural_whoop.contract import world_to_body
from neural_whoop.envs.registry import DroneTask, register_task
from neural_whoop.reward import Bounds, is_crashed, rotation_progress, smoothness_penalty

_AXIS_IDX = {"roll": 0, "pitch": 1}  # body-rate channel driven for each maneuver axis (p / q)


@dataclass
class AcroFlipConfig:
    """Tunable config for :class:`AcroFlipTask` (the acro reward/curriculum playground)."""

    axis: str = "roll"              # maneuver axis: "roll" (drives p) or "pitch" (drives q)
    n_rotations: float = 1.0        # target rotations → Φ = 2π·n_rotations (1 = a single barrel roll)
    episode_len: int = 200          # steps; at dt=0.02 → 4 s (ample for a sub-second flip + recover)
    # Maneuver clock (obs channel 7). The window the pilot hands the acro policy: pop → rotate →
    # catch. maneuver_phase counts 1→0 across it, then stays 0 for the rest of the episode. Must be
    # ≤ the deploy window (pilot FlightParams.acro_flip_max_s) or the clock outlives its authority.
    maneuver_len_s: float = 1.2
    # Reward weights.
    rot_scale: float = 1.0          # weight on the rotation-progress term (total ≈ rot_scale·Φ over the flip)
    completion_bonus: float = 10.0  # one-time bonus on crossing φ ≥ Φ (the "you did it" signal)
    upright_scale: float = 0.4      # weight on the recover-phase level bell exp(-(tilt/σ)²) (after completion)
    upright_sigma: float = 0.5      # width of the upright bell (rad of tilt from vertical)
    spin_penalty: float = 0.01      # −kw·|ω| recover-phase spin penalty (settle, don't keep spinning)
    # --- station-keeping (v2: "flip in place", the whole point of the retrain) ---
    lat_scale: float = 1.0          # −k·‖xy − xy0‖ lateral drift penalty, THROUGHOUT (v1 had none)
    sink_scale: float = 1.0         # −k·(z0 − z)+ : heavy. Falling out of the flip is the failure mode.
    rise_scale: float = 0.2         # −k·(z − z0 − pop_allow)+ : light, and only past the free headroom
    pop_allow: float = 0.4          # metres of FREE climb above z0 — this is what licenses the pop
    settle_scale: float = 0.2       # recover-gated −k·(‖xy−xy0‖ + |z−z0| + ‖vel‖): come back AND stop
    alive_bonus: float = 0.02       # per-step alive bonus (v1's 0.1 x 200 steps = 20 swamped the shaping)
    smoothness_penalty: float = 0.001
    crash_penalty: float = 10.0
    # Success metric.
    success_tilt_deg: float = 15.0  # a completed flip counts as recovered when tilt < this (deg)
    # Spawn band (level hover, at rest).
    arena_radius: float = 1.0       # horizontal radius the spawn point is sampled in (m)
    z_min: float = 1.2              # spawn height band — headroom below for the flip's altitude loss
    z_max: float = 2.2
    # Crash bounds.
    bound_xy: float = 6.0
    bound_z_min: float = 0.15
    bound_z_max: float = 4.0


@register_task("acro_flip")
class AcroFlipTask(DroneTask):
    """Learned single-axis flip: spin about ``axis`` to Φ = 2π·n_rotations, then recover level."""

    n_agents = 1
    obs_dim = 8  # [gravity_body(3), p, q, r, rotation_remaining, maneuver_phase]
    config_cls = AcroFlipConfig

    def __init__(self, **kwargs):
        self.cfg = self.config_cls(**kwargs)
        if self.cfg.axis not in _AXIS_IDX:
            raise ValueError(f"axis must be one of {sorted(_AXIS_IDX)}, got {self.cfg.axis!r}.")
        if self.cfg.maneuver_len_s <= 0.0:
            raise ValueError(f"maneuver_len_s must be > 0, got {self.cfg.maneuver_len_s}.")
        self.episode_len = self.cfg.episode_len
        self.axis_idx = _AXIS_IDX[self.cfg.axis]
        self.direction = 1.0  # v1: fixed rotation direction
        self.target_phi = 2.0 * math.pi * self.cfg.n_rotations
        self._bounds = Bounds(
            xy=self.cfg.bound_xy, z_min=self.cfg.bound_z_min, z_max=self.cfg.bound_z_max
        )

    # --- lifecycle ---
    def setup(self, env) -> None:
        if env.n_agents != 1:
            raise ValueError("acro_flip is single-drone (n_agents must be 1).")
        n, dev = env.n_drones, env.device
        self._dev = dev
        self._down = torch.tensor([0.0, 0.0, -1.0], device=dev)  # world-down (for gravity_body)
        # Signed accumulated rotation about the maneuver axis, in the intended direction (monotone,
        # no euler wrap). Advanced once per step in reward_and_done; observe() is a pure read.
        self.phi = torch.zeros(n, device=dev)
        # Maneuver clock: steps since the trigger. In sim the maneuver IS the episode, so the
        # trigger is step 0 and this is just the episode step count — kept as its own counter so
        # the clock's meaning ("time since trigger") is explicit and matches the deploy handoff.
        self.man_steps = torch.zeros(n, device=dev, dtype=torch.long)
        # Episode accumulators / trackers (GPU-resident; reset per env, read at log cadence).
        self.z0 = torch.zeros(n, device=dev)               # spawn altitude (altitude-keep reference)
        self.xy0 = torch.zeros(n, 2, device=dev)           # spawn ground position (station-keep reference)
        self.completed = torch.zeros(n, device=dev, dtype=torch.bool)   # reached Φ this episode
        self.succeeded = torch.zeros(n, device=dev, dtype=torch.bool)   # completed AND recovered level
        self.completion_step = torch.zeros(n, device=dev, dtype=torch.long)  # step of first completion
        self.steps = torch.zeros(n, device=dev, dtype=torch.long)
        self.crash_sum = torch.zeros(n, device=dev, dtype=torch.long)
        self.max_alt_loss = torch.zeros(n, device=dev)     # max (z0 − z) over the episode
        self.max_lat_drift = torch.zeros(n, device=dev)    # max ‖xy − xy0‖ over the episode
        self.peak_climb = torch.zeros(n, device=dev)       # max (z − z0) over the episode (the POP)
        self.settle_err = torch.zeros(n, device=dev)       # latest ‖pos − pos0‖ (read at episode end)
        self.last_tilt = torch.zeros(n, device=dev)        # current tilt from vertical (rad)

    def reset(self, env, env_idx: Tensor) -> None:
        c = self.cfg
        k = env_idx.numel()
        gen = env.gen
        d_idx = env.drone_idx(env_idx)
        # Spawn level, at rest, in a small disk within the height band — the flip is the learned
        # behaviour, not an initial condition.
        ang = torch.rand(k, device=self._dev, generator=gen) * (2 * math.pi)
        r = torch.rand(k, device=self._dev, generator=gen).sqrt() * c.arena_radius
        z = torch.rand(k, device=self._dev, generator=gen) * (c.z_max - c.z_min) + c.z_min
        spawn = torch.stack([r * ang.cos(), r * ang.sin(), z], dim=-1)
        env.spawn(d_idx, spawn)  # vel / ang_vel / roll / pitch default to zero (level, at rest)

        self.z0[d_idx] = z
        self.xy0[d_idx] = spawn[..., :2]
        self.phi[d_idx] = 0.0
        self.man_steps[d_idx] = 0
        self.completed[d_idx] = False
        self.succeeded[d_idx] = False
        self.completion_step[d_idx] = 0
        self.steps[d_idx] = 0
        self.crash_sum[d_idx] = 0
        self.max_alt_loss[d_idx] = 0.0
        self.max_lat_drift[d_idx] = 0.0
        self.peak_climb[d_idx] = 0.0
        self.settle_err[d_idx] = 0.0
        self.last_tilt[d_idx] = 0.0

    # --- observation ---
    def _gravity_body(self, env) -> Tensor:
        """World-down in the body frame (``Rᵀ·[0,0,-1]``) — inversion-safe attitude, ``(n, 3)``."""
        R = env.dyn.R
        return world_to_body(self._down.expand(R.shape[0], 3), R)

    def _rotation_remaining(self) -> Tensor:
        """Phase signal ``(Φ − clamp(φ,0,Φ))/Φ`` ∈ [1→0], per drone ``(n,)``."""
        return (self.target_phi - self.phi.clamp(0.0, self.target_phi)) / self.target_phi

    def _maneuver_phase(self, env) -> Tensor:
        """The pilot's maneuver CLOCK, ``clamp(1 − (t − t_trigger)/T, 0, 1)`` ∈ [1→0], ``(n,)``.

        Time-based, unlike :meth:`_rotation_remaining`'s gyro integral — that is the point of
        carrying both. ``t_trigger`` is step 0 here (in sim the maneuver is the episode), matching
        deploy where the pilot hands over control exactly at the trigger. Stays pinned at 0 once
        the window has elapsed, so it never wraps or goes negative.
        """
        elapsed = self.man_steps.float() * env.dt
        return (1.0 - elapsed / self.cfg.maneuver_len_s).clamp(0.0, 1.0)

    def observe(self, env) -> Tensor:
        grav_b = self._gravity_body(env)
        w = env.dyn.ang_vel_body
        remaining = self._rotation_remaining().unsqueeze(-1)
        phase = self._maneuver_phase(env).unsqueeze(-1)
        obs = torch.cat([grav_b, w, remaining, phase], dim=-1)
        return obs.to(torch.float32)

    # --- reward / termination ---
    def reward_and_done(self, env, action: Tensor) -> tuple[Tensor, Tensor, dict]:
        c = self.cfg
        pos, w = env.dyn.pos, env.dyn.ang_vel_body
        z = pos[..., 2]
        lat_err = (pos[..., :2] - self.xy0).norm(dim=-1)   # horizontal distance from the spawn point
        alt_err = z - self.z0                              # signed: >0 climbed, <0 sank
        grav_b = self._gravity_body(env)
        # Tilt from vertical: 0 = level, π = inverted (unambiguous through a full flip).
        tilt = torch.arccos((-grav_b[..., 2]).clamp(-1.0, 1.0))

        Phi = self.target_phi
        # Advance the signed rotation about the maneuver axis in the intended direction.
        rate_axis = w[..., self.axis_idx] * self.direction
        prev_phi = self.phi
        new_phi = prev_phi + rate_axis * env.dt
        self.phi = new_phi

        completed_now = new_phi >= Phi
        newly_completed = completed_now & (~self.completed)
        recover = completed_now.float()  # recover-phase gate (after completion)

        # Rotate phase: monotone, saturating progress toward Φ (can't farm infinite spin).
        reward = rotation_progress(prev_phi, new_phi, Phi, c.rot_scale)
        # Completion bonus (one-time on crossing Φ).
        reward = reward + c.completion_bonus * newly_completed.float()
        # Recover phase (gated): return to level + stop spinning.
        upright = torch.exp(-((tilt / c.upright_sigma) ** 2))
        spin = w.norm(dim=-1)
        reward = reward + recover * (c.upright_scale * upright - c.spin_penalty * spin)
        # --- station-keeping (privileged ground truth — no onboard position/altitude at deploy) ---
        # Lateral, throughout. v1 had NO lateral term, which is exactly why it threw a wide loop:
        # "maximise rotation, ignore translation" IS a barrel roll. A coast applies no lateral
        # force at all, so ~zero drift is achievable and this term is what asks for it.
        reward = reward - c.lat_scale * lat_err
        # Altitude, ASYMMETRIC. Sinking is heavy (falling out of the flip is the failure mode);
        # rising is light and only past `pop_allow` metres of free headroom. This is the term that
        # LICENSES the pre-roll pop — v1's symmetric |z − z0| punished it — while still forbidding
        # the sink. The physics that sets pop_allow is in the module docstring.
        reward = reward - c.sink_scale * (-alt_err).clamp_min(0.0)
        reward = reward - c.rise_scale * (alt_err - c.pop_allow).clamp_min(0.0)
        # Settle / return, gated to the recover phase: come back to the point AND stop there.
        # "Point in space" means both; without the velocity term a drone that sails through the
        # spawn point at speed collects the same reward as one that parks on it.
        reward = reward - recover * c.settle_scale * (
            lat_err + alt_err.abs() + env.dyn.vel_world.norm(dim=-1)
        )
        # Alive − smoothness − crash. The alive bonus is deliberately small: at v1's 0.1 x 200
        # steps it was 20 — the largest term in the episode — and it diluted all of the shaping
        # above while carrying no gradient of its own.
        reward = reward + c.alive_bonus
        reward = reward - smoothness_penalty(action, env.prev_action, c.smoothness_penalty)
        crashed = is_crashed(pos, self._bounds)
        reward = reward - c.crash_penalty * crashed.float()

        # Episode bookkeeping (ground truth).
        tol = math.radians(c.success_tilt_deg)
        success_now = completed_now & (tilt < tol) & (~crashed)
        self.completion_step = torch.where(newly_completed, self.steps + 1, self.completion_step)
        self.completed = self.completed | completed_now
        self.succeeded = self.succeeded | success_now
        alt_loss = (-alt_err).clamp_min(0.0)
        self.max_alt_loss = torch.maximum(self.max_alt_loss, alt_loss)
        self.max_lat_drift = torch.maximum(self.max_lat_drift, lat_err)
        self.peak_climb = torch.maximum(self.peak_climb, alt_err.clamp_min(0.0))
        # Distance from the point we started at — a running value, read at the episode's end (and
        # by the eval rollout every step, which is the honest full-horizon aggregate).
        self.settle_err = (lat_err * lat_err + alt_err * alt_err).sqrt()
        self.last_tilt = tilt
        self.steps = self.steps + 1
        self.man_steps = self.man_steps + 1
        self.crash_sum = self.crash_sum + crashed.long()

        terminated_env = crashed  # n_agents == 1 → per-drone == per-env
        # Per-step metric tensors (no CPU sync): the eval rollout aggregates these over the FULL
        # horizon, immune to the accumulator zeroing at episode auto-resets (see hover.py).
        info = {
            "crashed": crashed,
            "metrics": {
                "flip_success_rate": self.succeeded.float(),
                "rotation_frac": (new_phi / Phi).clamp(0.0, 1.0),
                "altitude_loss": alt_loss,
                # The v2 shape metrics — the numbers the point-in-space claim is graded on.
                "lateral_drift": lat_err,
                "climb": alt_err.clamp_min(0.0),
                "settle_pos_error": self.settle_err,
            },
        }
        return reward, terminated_env, info

    # --- visual scene (replay `scene` channel) ---
    def scene_objects(self, env) -> dict:
        """Surface ``rotation_remaining`` as the on-screen command chip (per-drone scalar)."""
        return {"command": self._rotation_remaining(), "target": self.spawn_point()}

    def spawn_point(self) -> Tensor:
        """The station-keeping reference ``[x0, y0, z0]``, ``(n, 3)`` — what "in place" means.

        Surfaced through the replay's ``scene`` channel so the Studio/capture renderers draw the
        point the flip is supposed to return to; that marker is what makes the v1-vs-v2 difference
        legible on screen rather than only in the metrics.
        """
        return torch.cat([self.xy0, self.z0.unsqueeze(-1)], dim=-1)

    def scene_info(self) -> dict:
        """Descriptor for the command chip (the maneuver-phase scalar) + the station-keep marker."""
        return {
            "command_label": f"{self.cfg.axis}-flip phase (remaining)",
            "target_label": "flip station (spawn point)",
        }

    def metrics(self, env) -> dict:
        steps = self.steps.clamp_min(1).float()
        completed = self.completed.float()
        n_completed = completed.sum().clamp_min(1.0)
        comp_time = (self.completion_step.float() * env.dt * completed).sum() / n_completed
        tilt_completed = (self.last_tilt * completed).sum() / n_completed
        return {
            "flip_success_rate": self.succeeded.float().mean().item(),
            "mean_completion_time": comp_time.item(),
            "mean_altitude_loss": self.max_alt_loss.mean().item(),
            # v2 shape metrics. max_lateral_drift is the term v1 never had; peak_climb SHOULD be
            # nonzero (0.2-0.4 m is the licensed pop, not a regression); settle_pos_error is how
            # far from the start point the drone actually ends up.
            "max_lateral_drift": self.max_lat_drift.mean().item(),
            "peak_climb": self.peak_climb.mean().item(),
            "settle_pos_error": self.settle_err.mean().item(),
            "post_recovery_tilt_deg": math.degrees(tilt_completed.item()),
            "crash_rate_per_step": (self.crash_sum.float() / steps).mean().item(),
        }
