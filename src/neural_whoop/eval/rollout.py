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
    task_sums: dict[str, torch.Tensor] = {}
    for _ in range(steps):
        action = agent.act_deterministic(obs) if deterministic else agent.get_action_and_value(obs)[0]
        obs, reward, term, trunc, info = env.step(action)
        rew_sum += reward
        if "crashed" in info:
            crashes += info["crashed"].float()
        if "passed" in info:
            gates += info["passed"].float()
        for k, v in info.get("metrics", {}).items():
            task_sums[k] = task_sums[k] + v if k in task_sums else v.clone()

    m = dict(env.task.metrics(env))
    # Rollout-wide per-step means override the task's episode-windowed values: the task's own
    # accumulators zero on episode reset, so with a lockstep population (no crashes) and a horizon
    # that's a multiple of episode_len, the final auto-reset clobbers them right before the read.
    for k, v in task_sums.items():
        m[k] = (v / steps).mean().item()
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


def select_swarm_heroes(env: MultiAgentDroneEnv, env_idx: int = 0) -> list[int]:
    """Pick **all agents of one env** so the heroes share a single course (for swarm tasks).

    Multi-agent envs flatten ``(n_envs, n_agents)`` env-major: env ``e``'s agents are flat drone
    indices ``e*n_agents .. e*n_agents+n_agents-1`` (see ``MultiAgentDroneEnv._agent_indices``).
    Recording those co-env drones together lets the viewer render them coexisting on the same
    gates — unlike :func:`select_heroes`, which spreads across the population (one solo drone per
    env). For ``n_agents == 1`` this is just ``[env_idx]``.

    Args:
        env: The evaluation env.
        env_idx: Which env's agents to record (clamped to ``[0, n_envs)``).

    Returns:
        The flat drone indices of that env's agents, ascending.
    """
    na = int(env.n_agents)
    e = max(0, min(int(env_idx), env.n_envs - 1))
    return [e * na + a for a in range(na)]


def hero_pose_snapshot(env: MultiAgentDroneEnv, action, h) -> dict:
    """CPU snapshots of the generic per-hero pose/action/scene fields for hero drones ``h``.

    The single source of the per-frame pose/action/scene extraction, shared by the recorder
    (:func:`evaluate_and_record`) and the live Studio session (:mod:`neural_whoop.studio.live`)
    so the on-the-wire frame fields can't drift from the recorded replay schema
    (``docs/VISUAL_CONTRACT.md`` / :mod:`neural_whoop.viz.replay`). ``h`` is a ``LongTensor`` of
    flat drone indices; returns a dict of CPU tensors (row ``j`` = hero ``j``) keyed
    ``pos``/``quat``/``rpy``/``vel``/``angvel``/``action``/``action_diffaero`` plus ``scene`` (a
    dict of per-hero CPU tensors, or ``None`` for gate tasks with no scene channel).
    """
    ctbr = action_to_diffaero(action[h], env.limits)
    scene_raw = env.task.scene_objects(env)
    return {
        "pos": env.dyn.pos[h].cpu(),
        "quat": env.dyn.quat_xyzw[h].cpu(),
        "rpy": env.dyn.rpy[h].cpu(),
        "vel": env.dyn.vel_world[h].cpu(),
        "angvel": env.dyn.ang_vel_body[h].cpu(),
        "action": action[h].cpu(),
        "action_diffaero": ctbr.cpu(),
        "scene": {k: v[h].cpu() for k, v in scene_raw.items()} if scene_raw else None,
    }


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
    group: bool | None = None,
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
        heroes: Flat drone indices to record (``None`` -> :func:`select_heroes`, or
            :func:`select_swarm_heroes` when the env is multi-agent).
        steps: Control steps to roll.
        deterministic: Use the actor mean (clipped) instead of sampling.
        record_obs: Also store the flat observation vector per frame.
        group: Record the heroes as one **swarm group episode** (they share a course) rather than
            one episode each. ``None`` -> auto (on when ``env.n_agents > 1`` and >1 hero).

    Returns:
        The same aggregate metric dict :func:`evaluate` returns.
    """
    dev = env.device
    task = env.task
    if heroes is None:
        heroes = select_swarm_heroes(env) if env.n_agents > 1 else select_heroes(env)
    if group is None:
        group = env.n_agents > 1 and len(heroes) > 1
    h = torch.tensor(heroes, device=dev, dtype=torch.long)
    n_h = len(heroes)
    num_gates = int(getattr(getattr(task, "cfg", None), "n_gates", 0))  # 0 for gate-less tasks (e.g. target_follow)

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
    task_sums: dict[str, torch.Tensor] = {}

    for step in range(steps):
        action = agent.act_deterministic(obs) if deterministic else agent.get_action_and_value(obs)[0]
        obs, reward, term, trunc, info = env.step(action)

        rew_sum += reward
        passed = info.get("passed")
        crashed = info.get("crashed")
        if crashed is not None:
            crashes += crashed.float()
        if passed is not None:
            gates += passed.float()
        for k, v in info.get("metrics", {}).items():
            task_sums[k] = task_sums[k] + v if k in task_sums else v.clone()

        if not any(open_ep):
            continue

        # Per-hero CPU snapshots (small: only the hero rows). The generic pose/action/scene fields
        # come from the shared extractor so the recorded schema and the live wire-format can't drift.
        snap = hero_pose_snapshot(env, action, h)
        pos, quat, rpy, vel, angvel = (
            snap["pos"], snap["quat"], snap["rpy"], snap["vel"], snap["angvel"],
        )
        act_n, act_d = snap["action"], snap["action_diffaero"]
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
        # Per-drone scene markers (moving target/anchor/slot + command) for gateless tasks, already
        # sliced to the hero rows by the shared extractor; None for gate tasks.
        scene_h = snap["scene"]

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
                "scene": {k: v[j] for k, v in scene_h.items()} if scene_h else None,
            })

    def _summary(j: int) -> dict:
        return {
            "steps": len(hero_frames[j]),
            "total_reward": cum[j],
            "laps": last_laps[j],
            "best_lap": best_lap[j],
            "gates_passed": gates_passed[j],
            "num_gates": num_gates,
            "ended": ended[j],
        }

    if group and n_h > 1:
        # One swarm group episode: the heroes are co-env agents, so they share heroes[0]'s course.
        recorder.add_group_episode(
            1,
            hero_meta[0]["gates"],
            tracks=[
                {
                    "drone": hero_meta[j]["drone"],
                    "dr": hero_meta[j]["dr"],
                    "summary": _summary(j),
                    "frames": hero_frames[j],
                }
                for j in range(n_h)
            ],
            oracle_lap=hero_meta[0]["oracle_lap"],
        )
    else:
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
            recorder.end_episode(_summary(j))

    m = dict(env.task.metrics(env))
    for k, v in task_sums.items():  # rollout-wide means (see evaluate() for why they override)
        m[k] = (v / steps).mean().item()
    m["mean_reward"] = (rew_sum / steps).mean().item()
    m["crash_rate_per_step"] = (crashes / steps).mean().item()
    m["gates_passed_total"] = gates.sum().item()
    return m
