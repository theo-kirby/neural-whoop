"""``reference_track`` — fly the hand-authored reference maneuver, graded against it step by step.

Every other task in this lab is **reward-shaped discovery**: we describe a maneuver in penalty
terms and hope the optimum is the shape we meant. ``acro_flip`` is the cautionary tale — v1's
reward had no lateral term, so "maximise rotation, ignore translation" produced a wide barrel roll,
and v2 is a second guess at the same prose. This task is the other approach: the maneuver already
exists as data (:mod:`neural_whoop.reference`), exactly derived, so **track it** rather than
re-deriving it from a reward.

That inverts what the reward has to encode. Instead of "spin, but don't drift, but do pop, but not
too much" — four hand-tuned weights whose optimum nobody can predict — the reward is one thing:
*be where the reference is, pointing where it points, turning how it turns.* The shaping problem
moves out of the reward and into the authoring, where it is algebra with a closed form
(``docs/REFERENCE_MANEUVER.md``).

**One task, three maneuvers.** ``reference/`` is a ``ManeuverSpec`` protocol with three
implementations emitting one format, so this task inherits all of them by pointing ``reference:``
at a different ``reference.json``: the flip, the swing (the U), and the orbit (the revolve). No new
task per maneuver, and a fourth authored maneuver needs no code here at all.

Observation (obs_dim 13, deploy-honest — IMU + the pilot's own clock + the authored target)::

    [gravity_body(3), p, q, r, maneuver_phase(1), gravity_body_ref(3), omega_ref(3)]

The first seven are exactly ``acro_flip``'s sensor set minus ``rotation_remaining`` (which is
flip-specific and meaningless for a swing). The last six are the **reference's own attitude and
body rate at the current phase** — authored signals, not measurements, in the same class as
``maneuver_phase``: they are a deterministic function of the clock, so at deploy they ship with the
policy as a small table rather than needing a sensor. They are given explicitly instead of left for
the net to memorise because a ``[64, 64]`` policy should spend its capacity on *control*, not on
storing a trajectory it is handed for free.

Note what is deliberately **absent**: reference *position*. A whoop has no onboard position sensor,
so ``pos_ref − pos`` cannot be an observation. Position tracking lives in the reward only — the
standard privileged-critic split, and the same line ``acro_flip`` draws for its station-keeping.

Reward — a weighted sum of tracking bells, each ``exp(−(err/σ)²)`` so it is bounded, smooth, and
saturates rather than exploding on a bad frame::

    w_att·att + w_rate·rate + w_pos·pos + w_vel·vel + alive − smoothness − crash

**Reference State Initialization (RSI) is the load-bearing trick**, not a detail. A fraction
``rsi_frac`` of episodes start at a *random phase of the reference, in the reference's own state* —
mid-inversion, mid-swing, wherever. Without it the policy must discover the pop before it ever
observes inverted flight, which is precisely the exploration barrier that makes reward-shaped acro
fragile (and which this run watched ``acro_flip_v2`` fall into: it converged to station-keeping and
stopped attempting the flip at all). With RSI, every part of the maneuver gets gradient from the
first update. This is the DeepMimic result (Peng et al. 2018) and it transfers directly.

Early termination on a tracking blow-up is the other half: once the drone is hopelessly off the
reference, further samples teach nothing, so the episode ends and the slot is reused.

Metrics deliberately reuse ``AcroFlipTask``'s names — ``max_lateral_drift``, ``peak_climb``,
``altitude_loss``, ``settle_pos_error`` — measured against the reference's own station, so a
tracked flip and a reward-shaped flip are directly comparable.

**The headline tracking numbers are the per-step ones**: ``pos_err_m``, ``att_err_deg``,
``rate_err_rps`` and ``tracking_ok``, emitted through ``info["metrics"]`` so ``eval/rollout.py``
aggregates them over the *full* horizon. The episode-windowed accumulators in :meth:`metrics` are
prefixed ``ep_`` and are reset-biased in the flattering direction (2.4× on the trained flip) — see
that method. Quote ``pos_err_m``, not ``ep_pos_rmse_m``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import torch
from torch import Tensor

from neural_whoop.contract import world_to_body
from neural_whoop.envs.registry import DroneTask, register_task
from neural_whoop.reference.track import STAGECRAFT_PHASES, load_reference_track
from neural_whoop.reward import Bounds, is_crashed, smoothness_penalty


@dataclass
class ReferenceTrackConfig:
    """Config for :class:`ReferenceTrackTask` (``task:`` block of the YAML)."""

    #: Path to a ``reference.json`` (the 1 kHz data artifact from scripts/reference_maneuver.py).
    #: NOT a replay.json.gz — that is decimated to 50 Hz and aliases the maneuver.
    reference: str = ""
    #: Phase labels dropped as stagecraft (the take-off / hover / landing the deploy split gives to
    #: the hover policy). See reference/track.py.
    exclude_phases: tuple[str, ...] = STAGECRAFT_PHASES
    #: Explicit phase whitelist; overrides exclude_phases when set.
    include_phases: tuple[str, ...] | None = None
    #: Steps of free settle after the reference ends (hold the final state — "and stop there").
    settle_steps: int = 25

    # --- Reference State Initialization ---
    #: Fraction of episodes that start at a random phase of the reference, in its own state. The
    #: rest start at phase 0. 0.0 disables RSI (and reproduces the exploration barrier).
    rsi_frac: float = 0.8
    #: Latest phase fraction RSI will spawn at — past this there is not enough maneuver left to
    #: learn anything from.
    rsi_max_frac: float = 0.9
    #: Per-drone spawn jitter around the reference state, so the policy learns to *correct* toward
    #: the reference rather than only to continue from exactly on it.
    rsi_pos_jitter: float = 0.03      # m
    rsi_vel_jitter: float = 0.05      # m/s
    rsi_omega_jitter: float = 0.10    # rad/s
    rsi_tilt_jitter: float = 0.03     # rad

    # --- Reward: tracking bells, exp(-(err/sigma)^2) ---
    att_scale: float = 2.0
    att_sigma: float = 0.40      # rad of geodesic attitude error
    rate_scale: float = 0.5
    rate_sigma: float = 3.0      # rad/s
    pos_scale: float = 2.0
    pos_sigma: float = 0.25      # m
    vel_scale: float = 0.5
    vel_sigma: float = 1.0       # m/s
    alive_bonus: float = 0.02
    smoothness_penalty: float = 0.001
    crash_penalty: float = 10.0

    # --- Early termination ---
    #: Position error past which the episode is abandoned (m). Generous: the point is to cut
    #: hopeless rollouts, not to punish an honest transient.
    fail_pos_err: float = 1.0

    #: Spawn jitter applied to the *whole* maneuver's world placement, so the policy does not
    #: memorise one absolute position (the reference is authored at a fixed station).
    station_jitter_xy: float = 0.5
    station_jitter_z: float = 0.3

    # Crash bounds.
    bound_xy: float = 6.0
    bound_z_min: float = 0.15
    bound_z_max: float = 4.0

    #: Success threshold for ``track_success_rate``: mean position error over the episode (m).
    success_pos_rmse: float = 0.20


@register_task("reference_track")
class ReferenceTrackTask(DroneTask):
    """Track a hand-authored reference maneuver step by step (flip / swing / orbit)."""

    n_agents = 1
    obs_dim = 13  # [gravity_body(3), p, q, r, phase, gravity_body_ref(3), omega_ref(3)]
    config_cls = ReferenceTrackConfig

    def __init__(self, **kwargs):
        kwargs.pop("_", None)
        self.cfg = self.config_cls(**kwargs)
        if not self.cfg.reference:
            raise ValueError(
                "reference_track needs a `reference:` path to a reference.json — generate one with "
                "scripts/reference_maneuver.py --maneuver flip|swing|orbit."
            )
        if not 0.0 <= self.cfg.rsi_frac <= 1.0:
            raise ValueError(f"rsi_frac must be in [0,1], got {self.cfg.rsi_frac}.")
        self._ref_path = Path(self.cfg.reference)
        self._track = None  # loaded in setup(), where env.dt is known
        self._bounds = Bounds(
            xy=self.cfg.bound_xy, z_min=self.cfg.bound_z_min, z_max=self.cfg.bound_z_max
        )

    # --- lifecycle ---
    def setup(self, env) -> None:
        if env.n_agents != 1:
            raise ValueError("reference_track is single-drone (n_agents must be 1).")
        c = self.cfg
        # The control step is the env's, so the reference is resampled to match it here rather
        # than at construction — the same reference file serves any control rate.
        tr = load_reference_track(
            self._ref_path, dt=env.dt,
            exclude_phases=tuple(c.exclude_phases),
            include_phases=tuple(c.include_phases) if c.include_phases else None,
        )
        self._track = tr
        n, dev = env.n_drones, env.device
        self._dev = dev
        self._down = torch.tensor([0.0, 0.0, -1.0], device=dev)

        def T(a, dtype=torch.float32):
            return torch.as_tensor(a, device=dev, dtype=dtype)

        # The reference tables, GPU-resident. Indexed by each drone's own phase step.
        self.ref_pos = T(tr.pos)                      # (T, 3) world, relative to ref station below
        self.ref_vel = T(tr.vel)
        self.ref_quat = T(tr.quat)
        self.ref_omega = T(tr.omega)
        self.ref_grav_b = T(tr.gravity_body())        # (T, 3) the observable attitude channel
        self.ref_station = T(tr.station)              # (3,)
        # Position table re-expressed as an offset from the station, so a jittered spawn just
        # translates the whole maneuver.
        self.ref_offset = self.ref_pos - self.ref_station
        self.T_ref = int(tr.n_steps)
        self.episode_len = self.T_ref + int(c.settle_steps)

        # Per-drone state.
        self.step_idx = torch.zeros(n, device=dev, dtype=torch.long)   # phase step into the ref
        self.station = torch.zeros(n, 3, device=dev)                   # this episode's placement
        self.steps = torch.zeros(n, device=dev, dtype=torch.long)
        self.crash_sum = torch.zeros(n, device=dev, dtype=torch.long)
        # Tracking accumulators (sum + count → RMSE at log cadence, no CPU sync in the hot path).
        self.pos_err_sq_sum = torch.zeros(n, device=dev)
        self.att_err_sq_sum = torch.zeros(n, device=dev)
        self.err_count = torch.zeros(n, device=dev)
        self.last_pos_err = torch.zeros(n, device=dev)
        self.last_att_err = torch.zeros(n, device=dev)
        self.tracked_steps = torch.zeros(n, device=dev, dtype=torch.long)
        # acro_flip-comparable shape metrics, against the reference's own station.
        self.max_lat_drift = torch.zeros(n, device=dev)
        self.peak_climb = torch.zeros(n, device=dev)
        self.max_alt_loss = torch.zeros(n, device=dev)
        self.settle_err = torch.zeros(n, device=dev)

    def reset(self, env, env_idx: Tensor) -> None:
        c = self.cfg
        k = env_idx.numel()
        gen, dev = env.gen, self._dev
        d_idx = env.drone_idx(env_idx)

        def rnd(*shape):
            return torch.rand(*shape, device=dev, generator=gen)

        # Where this episode's maneuver sits in the world (the reference is authored at one fixed
        # station; jitter stops the policy memorising absolute coordinates).
        jitter = torch.stack([
            (rnd(k) * 2 - 1) * c.station_jitter_xy,
            (rnd(k) * 2 - 1) * c.station_jitter_xy,
            (rnd(k) * 2 - 1) * c.station_jitter_z,
        ], dim=-1)
        station = self.ref_station.unsqueeze(0) + jitter
        self.station[d_idx] = station

        # --- Reference State Initialization ---
        use_rsi = rnd(k) < c.rsi_frac
        max_start = max(1, int(self.T_ref * c.rsi_max_frac))
        start = (rnd(k) * max_start).long().clamp_(0, max_start - 1)
        start = torch.where(use_rsi, start, torch.zeros_like(start))
        self.step_idx[d_idx] = start

        pos = station + self.ref_offset[start]
        vel = self.ref_vel[start].clone()
        quat = self.ref_quat[start].clone()
        omega = self.ref_omega[start].clone()
        # Jitter only the RSI spawns: a phase-0 start is the honest "begin the maneuver from
        # hover" condition and should stay clean, matching how the pilot hands over at the trigger.
        j = use_rsi.float().unsqueeze(-1)
        pos = pos + j * (rnd(k, 3) * 2 - 1) * c.rsi_pos_jitter
        vel = vel + j * (rnd(k, 3) * 2 - 1) * c.rsi_vel_jitter
        omega = omega + j * (rnd(k, 3) * 2 - 1) * c.rsi_omega_jitter
        # Attitude jitter as a small-angle perturbation applied to the reference quaternion. Done
        # as a quaternion product rather than via euler angles because the flip spawns inverted,
        # where the ZYX triple is degenerate (quaternion_to_euler clamps pitch to +-90 deg).
        dv = j * (rnd(k, 3) * 2 - 1) * c.rsi_tilt_jitter
        dq = torch.cat([dv * 0.5, torch.ones(k, 1, device=dev)], dim=-1)
        dq = dq / dq.norm(dim=-1, keepdim=True)
        quat = _quat_mul_xyzw(quat, dq)

        env.spawn(d_idx, pos, vel=vel, ang_vel=omega, quat=quat)

        self.steps[d_idx] = 0
        self.crash_sum[d_idx] = 0
        self.pos_err_sq_sum[d_idx] = 0.0
        self.att_err_sq_sum[d_idx] = 0.0
        self.err_count[d_idx] = 0.0
        self.last_pos_err[d_idx] = 0.0
        self.last_att_err[d_idx] = 0.0
        self.tracked_steps[d_idx] = 0
        self.max_lat_drift[d_idx] = 0.0
        self.peak_climb[d_idx] = 0.0
        self.max_alt_loss[d_idx] = 0.0
        self.settle_err[d_idx] = 0.0

    # --- observation ---
    def _gravity_body(self, env) -> Tensor:
        R = env.dyn.R
        return world_to_body(self._down.expand(R.shape[0], 3), R)

    def _ref_idx(self) -> Tensor:
        """Current phase step, clamped to the last reference sample (the settle holds it)."""
        return self.step_idx.clamp(0, self.T_ref - 1)

    def _maneuver_phase(self) -> Tensor:
        """The clock, ``1 → 0`` across the reference, pinned at 0 through the settle tail."""
        return (1.0 - self.step_idx.float() / max(1, self.T_ref - 1)).clamp(0.0, 1.0)

    def observe(self, env) -> Tensor:
        i = self._ref_idx()
        obs = torch.cat([
            self._gravity_body(env),
            env.dyn.ang_vel_body,
            self._maneuver_phase().unsqueeze(-1),
            self.ref_grav_b[i],
            self.ref_omega[i],
        ], dim=-1)
        return obs.to(torch.float32)

    # --- reward / termination ---
    def reward_and_done(self, env, action: Tensor) -> tuple[Tensor, Tensor, dict]:
        c = self.cfg
        i = self._ref_idx()
        pos, vel = env.dyn.pos, env.dyn.vel_world
        quat, w = env.dyn.quat_xyzw, env.dyn.ang_vel_body

        tgt_pos = self.station + self.ref_offset[i]
        pos_err = (pos - tgt_pos).norm(dim=-1)
        vel_err = (vel - self.ref_vel[i]).norm(dim=-1)
        rate_err = (w - self.ref_omega[i]).norm(dim=-1)
        att_err = _quat_geodesic(quat, self.ref_quat[i])   # rad, in [0, pi]

        reward = (
            c.att_scale * torch.exp(-((att_err / c.att_sigma) ** 2))
            + c.rate_scale * torch.exp(-((rate_err / c.rate_sigma) ** 2))
            + c.pos_scale * torch.exp(-((pos_err / c.pos_sigma) ** 2))
            + c.vel_scale * torch.exp(-((vel_err / c.vel_sigma) ** 2))
            + c.alive_bonus
        )
        reward = reward - smoothness_penalty(action, env.prev_action, c.smoothness_penalty)
        crashed = is_crashed(pos, self._bounds)
        lost = pos_err > c.fail_pos_err
        reward = reward - c.crash_penalty * crashed.float()

        # --- bookkeeping (ground truth) ---
        live = ~(crashed | lost)
        self.pos_err_sq_sum = self.pos_err_sq_sum + pos_err * pos_err
        self.att_err_sq_sum = self.att_err_sq_sum + att_err * att_err
        self.err_count = self.err_count + 1.0
        self.last_pos_err = pos_err
        self.last_att_err = att_err
        self.tracked_steps = self.tracked_steps + live.long()
        # acro_flip-comparable shape numbers, against this episode's station.
        lat = (pos[..., :2] - self.station[..., :2]).norm(dim=-1)
        alt = pos[..., 2] - self.station[..., 2]
        self.max_lat_drift = torch.maximum(self.max_lat_drift, lat)
        self.peak_climb = torch.maximum(self.peak_climb, alt.clamp_min(0.0))
        self.max_alt_loss = torch.maximum(self.max_alt_loss, (-alt).clamp_min(0.0))
        self.settle_err = (pos - self.station).norm(dim=-1)

        self.steps = self.steps + 1
        self.step_idx = self.step_idx + 1
        self.crash_sum = self.crash_sum + crashed.long()

        terminated_env = crashed | lost
        info = {
            "crashed": crashed,
            "metrics": {
                "pos_err_m": pos_err,
                "att_err_deg": att_err * (180.0 / math.pi),
                "rate_err_rps": rate_err,
                "tracking_ok": live.float(),
                # The acro_flip-comparable shape names.
                "lateral_drift": lat,
                "climb": alt.clamp_min(0.0),
                "altitude_loss": (-alt).clamp_min(0.0),
                "settle_pos_error": self.settle_err,
            },
        }
        return reward, terminated_env, info

    def metrics(self, env) -> dict:
        """Episode-windowed metrics. **The headline tracking numbers are NOT here** — see below.

        These accumulators zero on every episode auto-reset, so a read at log cadence catches most
        drones part-way through their current episode and systematically *under*-reports error: the
        hard middle of the maneuver is averaged against however much easy tail happens to be in the
        window. Measured on the trained flip, the same rollout reads 0.186 m through this path and
        **0.448 m** through the honest one — a 2.4× difference, in the flattering direction.

        ``eval/rollout.py`` already solves this: it aggregates the per-step tensors in
        ``info["metrics"]`` over the *full* horizon and overrides any key of the same name. So the
        decision metrics are emitted there, under ``pos_err_m`` / ``att_err_deg`` / ``tracking_ok``,
        and the values below are prefixed ``ep_`` to make it impossible to quote one for the other.
        A previous version of this method published bare ``pos_rmse_m`` / ``att_rmse_deg``, which
        the override could not reach and which therefore silently disagreed with the honest number.
        """
        n = self.err_count.clamp_min(1.0)
        pos_rmse = (self.pos_err_sq_sum / n).sqrt()
        att_rmse = (self.att_err_sq_sum / n).sqrt()
        return {
            # Episode-windowed (reset-biased, optimistic) — useful as a training *curve*, never as
            # a reported result. The full-horizon truth is pos_err_m / att_err_deg.
            "ep_pos_rmse_m": float(pos_rmse.mean()),
            "ep_att_rmse_deg": float(att_rmse.mean()) * (180.0 / math.pi),
            "ep_track_success_rate": float((pos_rmse < self.cfg.success_pos_rmse).float().mean()),
            "ep_tracked_frac": float(
                (self.tracked_steps.float() / self.steps.clamp_min(1).float()).mean()
            ),
            "max_lateral_drift": float(self.max_lat_drift.mean()),
            "peak_climb": float(self.peak_climb.mean()),
            "mean_altitude_loss": float(self.max_alt_loss.mean()),
            "settle_pos_error": float(self.settle_err.mean()),
            "crash_rate_per_step": float(self.crash_sum.float().mean() / self.steps.clamp_min(1).float().mean()),
        }

    # --- visual scene (replay `scene` channel) ---
    def scene_objects(self, env) -> dict:
        """Draw the reference's own target pose, so a replay shows the policy *against* it."""
        i = self._ref_idx()
        return {
            "target": self.station + self.ref_offset[i],   # where it SHOULD be, this frame
            "anchor": self.station,                        # the station it returns to
            "command": self._maneuver_phase(),
        }

    def scene_info(self) -> dict:
        tr = self._track
        return {
            "target_label": f"reference {tr.maneuver if tr else ''} pose (the trajectory we WANT)",
            "anchor_label": "maneuver station",
            "command_label": "maneuver phase (remaining)",
            "reference_source": tr.source if tr else "",
            "reference_metrics": tr.metrics if tr else {},
        }


def _quat_mul_xyzw(a: Tensor, b: Tensor) -> Tensor:
    """Hamilton product for real-last quaternions, ``(k,4) x (k,4) -> (k,4)``."""
    ax, ay, az, aw = a.unbind(-1)
    bx, by, bz, bw = b.unbind(-1)
    return torch.stack([
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    ], dim=-1)


def _quat_geodesic(q: Tensor, r: Tensor) -> Tensor:
    """Geodesic angle between two attitudes, ``(k,)`` rad in ``[0, π]``.

    ``2·acos|⟨q, r⟩|`` — the absolute value is what makes it sign-agnostic, which matters here
    because ``q`` and ``−q`` are the same rotation and the reference's quaternion stream is
    continuity-enforced (it deliberately does *not* stay in one hemisphere through a 2π flip). A
    signed comparison would read a perfectly tracked inversion as 2π of error.
    """
    dot = (q * r).sum(-1).abs().clamp(0.0, 1.0)
    return 2.0 * torch.acos(dot)
