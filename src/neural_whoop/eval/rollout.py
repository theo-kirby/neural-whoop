"""Batched rollout + metrics: the deterministic eval used to report lap times.

Runs a trained policy (deterministic = ``clip(actor_mean)``) across many parallel envs for a
fixed horizon and aggregates the task's metrics (for ``gate_race``: lap time, laps completed,
completion rate, and the oracle baseline). No rendering on the training path — honest
camera-only eval (DiffAero depth render, Blackwell-OK) is a later hook (``render_depth``).

:func:`evaluate_and_record` is the **visual-observability** sibling: it runs the identical
deterministic rollout (returning a byte-identical aggregate metric dict) while additionally
feeding a small set of *hero* drones' per-step telemetry into a
:class:`~neural_whoop.viz.replay.RunRecorder`. Recording only a handful of heroes keeps the
capture cheap; aggregate metrics still cover the full population. The fast path
(:func:`evaluate`) is unchanged.
"""

from __future__ import annotations

import torch

from neural_whoop.contract import action_to_diffaero
from neural_whoop.envs.base import MultiAgentDroneEnv
from neural_whoop.training.ppo import ActorCritic


@torch.no_grad()
def evaluate(
    env: MultiAgentDroneEnv,
    agent: ActorCritic,
    steps: int = 1500,
    deterministic: bool = True,
) -> dict:
    """Roll out ``agent`` on ``env`` for ``steps`` control steps and return aggregated metrics.

    Args:
        env: The evaluation env (typically built with DR off or eval-DR for an honest number).
        agent: Trained :class:`ActorCritic`.
        steps: Control steps to roll (long enough for several laps).
        deterministic: Use the actor mean (clipped) instead of sampling.

    Returns:
        A metrics dict: the task ``metrics`` plus rollout-wide ``mean_reward``, ``crash_rate``,
        and ``gates_passed_total``.
    """
    dev = env.device
    obs = env.reset_all()
    rew_sum = torch.zeros(env.n_drones, device=dev)
    crashes = torch.zeros(env.n_drones, device=dev)
    gates = torch.zeros(env.n_drones, device=dev)
    for _ in range(steps):
        mean = agent.actor(obs)
        action = mean.clamp(-1.0, 1.0) if deterministic else agent.get_action_and_value(obs)[0]
        obs, reward, term, trunc, info = env.step(action)
        rew_sum += reward
        if "crashed" in info:
            crashes += info["crashed"].float()
        if "passed" in info:
            gates += info["passed"].float()

    m = dict(env.task.metrics(env))
    m["mean_reward"] = (rew_sum / steps).mean().item()
    m["crash_rate_per_step"] = (crashes / steps).mean().item()
    m["gates_passed_total"] = gates.sum().item()
    return m


def select_heroes(env: MultiAgentDroneEnv, n_heroes: int = 4) -> list[int]:
    """Pick a small, representative set of drone indices to record full telemetry for.

    Spread evenly across the population so the recorded courses are diverse (each env carries
    its own procedurally-generated course). ``plot_trajectory`` later promotes the *best* of
    the recorded episodes (most laps / gates) to the foreground, so this need only be a good
    candidate set, not the literal best-by-laps (which isn't known until after the rollout).

    Args:
        env: The evaluation env.
        n_heroes: Number of heroes to record (clamped to ``[1, n_drones]``).

    Returns:
        A sorted list of distinct flat drone indices.
    """
    n = env.n_drones
    k = max(1, min(int(n_heroes), n))
    idx = torch.linspace(0, n - 1, k).round().long().unique()
    return sorted(int(i) for i in idx.tolist())


def _dr_dict(env: MultiAgentDroneEnv, d: int) -> dict | None:
    """Serialize the live per-drone seam DR params for drone ``d``, or ``None`` if DR is off."""
    dr = env.dr
    if not dr.cfg.enabled:
        return None
    det = dr.cfg.detector
    return {
        "wind_vec": [float(v) for v in dr.wind[d].tolist()],
        "rate_gain_scale": float(dr.rate_gain[d, 0]),
        "thrust_scale": float(dr.thrust_scale[d, 0]),
        "latency_steps": int(dr.latency[d]),
        "obs_noise_std": float(dr.cfg.obs_noise_std),
        "detector": None if det.is_identity else {
            "bearing_deg": float(dr.cfg.detector_bearing_deg),
            "range_frac": float(dr.cfg.detector_range_frac),
            "dropout_prob": float(dr.cfg.detector_dropout_prob),
            "fov_deg": float(dr.cfg.detector_fov_deg),
        },
    }


@torch.no_grad()
def evaluate_and_record(
    env: MultiAgentDroneEnv,
    agent: ActorCritic,
    recorder,
    heroes: list[int] | None = None,
    steps: int = 1500,
    deterministic: bool = True,
    record_obs: bool = False,
) -> dict:
    """Roll out like :func:`evaluate`, additionally recording hero telemetry into ``recorder``.

    Each hero records exactly its **first** episode — from rollout start until that drone's
    first ``done`` (crash or time-limit truncation), or the end of the window. Frames are the
    post-step in-flight state; the terminal/reset step itself is not recorded (its state is
    already the next episode's spawn), and the crash/timeout is captured in the episode summary
    instead. Tensors are sliced per step and moved to CPU only for the heroes (a handful of
    rows), so the population stays GPU-resident.

    Args:
        env: The evaluation env (build with DR off / eval-DR for an honest number).
        agent: Trained :class:`ActorCritic`.
        recorder: A :class:`~neural_whoop.viz.replay.RunRecorder` (already built with meta).
        heroes: Flat drone indices to record (``None`` -> :func:`select_heroes`).
        steps: Control steps to roll.
        deterministic: Use the actor mean (clipped) instead of sampling.
        record_obs: Also store the flat observation vector per frame.

    Returns:
        The same aggregate metric dict :func:`evaluate` returns.
    """
    dev = env.device
    task = env.task
    heroes = heroes if heroes is not None else select_heroes(env)
    h = torch.tensor(heroes, device=dev, dtype=torch.long)
    n_h = len(heroes)
    num_gates = int(task.cfg.n_gates) if hasattr(task, "cfg") else 0

    obs = env.reset_all()

    def _gates_for(d: int):
        """``(ng, 4)`` [x,y,z,radius] gate rows for drone ``d`` (or empty if not a gate task)."""
        if not hasattr(task, "gate_pos"):
            return torch.empty(0, 4)
        return torch.cat([task.gate_pos[d], task.gate_rad[d].unsqueeze(-1)], dim=-1).cpu()

    # Per-hero recording state buffered in memory (the recorder holds one episode at a time, so
    # we flush all heroes' first episodes into it sequentially after the rollout). Each hero's
    # course / DR / oracle are captured at the post-reset start, before any auto-reset.
    hero_meta = [
        {
            "gates": _gates_for(d),
            "dr": _dr_dict(env, d),
            "oracle_lap": float(task.oracle_lap[d]) if hasattr(task, "oracle_lap") else None,
            "drone": d,
        }
        for d in heroes
    ]
    hero_frames: list[list[dict]] = [[] for _ in range(n_h)]
    cum = [0.0] * n_h
    gates_passed = [0] * n_h
    best_lap: list[float | None] = [None] * n_h
    last_laps = [0] * n_h
    ended = ["max_steps"] * n_h
    open_ep = [True] * n_h

    # Aggregate accumulators (full population) — identical to ``evaluate``.
    rew_sum = torch.zeros(env.n_drones, device=dev)
    crashes = torch.zeros(env.n_drones, device=dev)
    gates = torch.zeros(env.n_drones, device=dev)

    for step in range(steps):
        mean = agent.actor(obs)
        action = mean.clamp(-1.0, 1.0) if deterministic else agent.get_action_and_value(obs)[0]
        obs, reward, term, trunc, info = env.step(action)

        rew_sum += reward
        passed = info.get("passed")
        crashed = info.get("crashed")
        if crashed is not None:
            crashes += crashed.float()
        if passed is not None:
            gates += passed.float()

        if not any(open_ep):
            continue

        # Per-hero CPU snapshots (small: only the hero rows).
        ctbr = action_to_diffaero(action[h], env.limits)
        pos = env.dyn.pos[h].cpu()
        quat = env.dyn.quat_xyzw[h].cpu()
        rpy = env.dyn.rpy[h].cpu()
        vel = env.dyn.vel_world[h].cpu()
        angvel = env.dyn.ang_vel_body[h].cpu()
        act_n = action[h].cpu()
        act_d = ctbr.cpu()
        rew_h = reward[h].cpu()
        sim_t = float(env.sim_time[0]) if env.sim_time.numel() else step * env.dt
        done = (term | trunc)[h].cpu()
        crashed_h = crashed[h].cpu() if crashed is not None else torch.zeros(n_h, dtype=torch.bool)
        passed_h = passed[h].cpu() if passed is not None else torch.zeros(n_h, dtype=torch.bool)
        tgt = task.target[h].cpu() if hasattr(task, "target") else torch.zeros(n_h, dtype=torch.long)
        dist = task.prev_dist[h].cpu() if hasattr(task, "prev_dist") else torch.zeros(n_h)
        laps_h = task.laps[h].cpu() if hasattr(task, "laps") else torch.zeros(n_h, dtype=torch.long)
        bl_h = task.best_lap[h].cpu() if hasattr(task, "best_lap") else torch.full((n_h,), float("inf"))
        obs_h = obs[h].cpu() if record_obs else None

        for j in range(n_h):
            if not open_ep[j]:
                continue
            if bool(done[j]):
                # First done: close this hero's episode (don't record the reset frame).
                ended[j] = "crash" if bool(crashed_h[j]) else "max_steps"
                open_ep[j] = False
                continue

            cum[j] += float(rew_h[j])
            if bool(passed_h[j]):
                gates_passed[j] += 1
            last_laps[j] = int(laps_h[j])
            if torch.isfinite(bl_h[j]):
                blv = float(bl_h[j])
                best_lap[j] = blv if best_lap[j] is None else min(best_lap[j], blv)
            hero_frames[j].append({
                "t": sim_t,
                "step": len(hero_frames[j]) + 1,
                "pos": pos[j],
                "quat": quat[j],
                "rpy": rpy[j],
                "vel": vel[j],
                "angvel": angvel[j],
                "action": act_n[j],
                "action_diffaero": act_d[j],
                "reward": float(rew_h[j]),
                "cum_reward": cum[j],
                "gate_idx": int(tgt[j]),
                "dist_to_gate": float(dist[j]),
                "laps": last_laps[j],
                "passed": bool(passed_h[j]),
                "crashed": bool(crashed_h[j]),
                "obs": obs_h[j] if obs_h is not None else None,
            })

    # Flush each hero's buffered episode into the (single-open-episode) recorder.
    for j in range(n_h):
        recorder.begin_episode(
            j + 1,
            hero_meta[j]["gates"],
            drone=hero_meta[j]["drone"],
            dr=hero_meta[j]["dr"],
            oracle_lap=hero_meta[j]["oracle_lap"],
        )
        for fr in hero_frames[j]:
            recorder.add_frame(**fr)
        recorder.end_episode({
            "steps": len(hero_frames[j]),
            "total_reward": cum[j],
            "laps": last_laps[j],
            "best_lap": best_lap[j],
            "gates_passed": gates_passed[j],
            "num_gates": num_gates,
            "ended": ended[j],
        })

    m = dict(env.task.metrics(env))
    m["mean_reward"] = (rew_sum / steps).mean().item()
    m["crash_rate_per_step"] = (crashes / steps).mean().item()
    m["gates_passed_total"] = gates.sum().item()
    return m
