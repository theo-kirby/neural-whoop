"""Studio rollout — fly a chosen saved policy over a chosen fixed course with N drones.

The one Studio route that touches the sim. Reuses the eval recording path verbatim
(:func:`neural_whoop.eval.rollout.evaluate_and_record` with ``group=True``) so the produced
file is exactly the v2 group-episode replay the viewer (and nw-viz) already render.

Drone-count maps to the substrate per the policy's task family (see CLAUDE.md / docs/STUDIO.md):

* **gate_race** (gated, single-drone): ``n_envs = drone_count``, ``n_agents = 1`` — N independent
  racers on the SAME fixed course (shared via ``env.fixed_course``), one group episode.
* **swarm_race** (gated swarm): ``n_envs = 1``, ``n_agents = max(2, drone_count)`` — a
  collision-aware shared-track swarm via the task's neighbour observation.
* **follow tasks** (``target/hand/gesture/command_follow``, gateless single-drone):
  ``n_envs = drone_count``, ``n_agents = 1`` — N independent followers, each with its own moving
  target; no course is resolved (the task supplies its arena), the ``scene`` channel records the
  target (+ command) per drone.
* **swarm_formation** (gateless swarm): ``n_envs = 1``, ``n_agents = max(2, drone_count)`` — a ring
  formation around one shared moving anchor; the ``scene`` channel records the anchor + each slot.

Heavy imports (torch/env/agent) are function-local so the server module imports without a GPU.
"""

from __future__ import annotations

import json
from pathlib import Path

#: Default location of seeded course YAMLs and run outputs, relative to the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]

#: Task families that map drone-count to ``n_agents`` (shared env, mutual awareness) rather than
#: ``n_envs`` (independent racers): the swarm tasks.
SWARM_TASKS = frozenset({"swarm_race", "swarm_formation"})
#: Tasks with no gate course — they supply their own arena and a moving target/anchor instead, so
#: course resolution + gate sizing is skipped (the ``scene`` channel carries what they track).
GATELESS_TASKS = frozenset(
    {"target_follow", "hand_follow", "gesture_follow", "command_follow", "swarm_formation", "hover"}
)


def task_family(task_name: str) -> str:
    """Coarse family for the frontend: ``gate`` / ``gate_swarm`` / ``follow`` / ``formation``."""
    if task_name == "swarm_formation":
        return "formation"
    if task_name == "swarm_race":
        return "gate_swarm"
    if task_name in GATELESS_TASKS:
        return "follow"
    return "gate"


#: Human labels for the families (frontend optgroup headers / chips).
FAMILY_LABELS = {
    "gate": "gate racing",
    "gate_swarm": "swarm racing",
    "follow": "target / hand following",
    "formation": "swarm formation",
}

#: Curated **recommended** run per family — the canonical "start here / known-good" policy the
#: Studio surfaces first, so the picker isn't a flat wall of experiment runs. These are the GREEN
#: representatives from the Flywheel record (gate: the 120M scale-generalist; follow: the EMA-precision
#: target_follow + EMA hand_follow; the command-conditioned policies; the formation baseline). Update
#: when a better baseline lands; an entry that no longer exists is simply ignored.
RECOMMENDED_RUNS = frozenset({
    "gate_race_big128_120M_s0",   # best lap time, scale-generalist (studio baseline)
    "swarm_race_s1",              # shared-track swarm
    "target_follow_ema085",       # EMA precision filter closes the standoff back-off (GREEN)
    "hand_follow_ema",            # EMA generalizes to the jerky hand (GREEN)
    "gesture_follow",             # first command-conditioned policy (STOP/GO)
    "command_follow",             # 3-way command vocabulary (STOP/NEAR/FAR)
    "swarm_formation",            # ring formation around a moving anchor (GREEN)
})


def _read_ckpt_meta(policy_path: Path) -> dict:
    """Read the sidecar ``<ckpt>.pt.meta.json`` (task, obs_dim, act_dim, step)."""
    meta_path = policy_path.with_suffix(policy_path.suffix + ".meta.json")
    if meta_path.is_file():
        return json.loads(meta_path.read_text())
    # Fall back to the checkpoint payload itself (carries the same fields).
    import torch

    ckpt = torch.load(policy_path, map_location="cpu", weights_only=False)
    return {"task": ckpt.get("task", "gate_race"), "obs_dim": ckpt.get("obs_dim"),
            "act_dim": ckpt.get("act_dim"), "step": ckpt.get("global_step")}


def studio_rollout(
    policy_path: str | Path,
    course: str,
    drone_count: int,
    *,
    dr: bool = False,
    max_steps: int = 1500,
    seed: int = 0,
    n_gates: int = 6,
    device: str = "cuda",
    courses_dir: str | Path | None = None,
    runs_dir: str | Path | None = None,
) -> tuple[Path, dict]:
    """Run one fixed-course rollout and save a v2 group replay; return ``(path, summary)``.

    Args:
        policy_path: Path to a ``ckpt_*.pt`` checkpoint (with its ``.meta.json`` sidecar).
        course: Course selector — ``preset:<name>`` or a seeded YAML stem under ``courses_dir``.
        drone_count: Number of drones to fly (clamped ``>=2`` for swarm policies).
        dr: Enable seam domain randomization (default off for a clean watch).
        max_steps: Rollout length in control steps.
        seed: RNG seed (also seeds preset course generation).
        n_gates: Gate count when generating a preset course (ignored for seeded files).
        device: Torch device (``"cuda"`` on the 5090; ``"cpu"`` for tests).
        courses_dir / runs_dir: Override the default repo dirs (for tests).

    Returns:
        ``(replay_path, summary)`` where ``summary`` carries the task, drone count, course label,
        the aggregate eval metrics, and the relative run path.
    """
    from neural_whoop.envs.base import MultiAgentDroneEnv
    from neural_whoop.envs.registry import make_task
    import neural_whoop.tasks  # noqa: F401 - register built-in tasks
    from neural_whoop.eval.pack import policy_label
    from neural_whoop.eval.rollout import evaluate_and_record
    from neural_whoop.randomization import DomainRandomizationConfig
    from neural_whoop.studio import courses as courses_mod
    from neural_whoop.training.ppo import load_agent
    from neural_whoop.viz.replay import RunRecorder, build_meta

    policy_path = Path(policy_path)
    courses_dir = Path(courses_dir) if courses_dir is not None else _REPO_ROOT / "assets" / "courses"
    runs_dir = Path(runs_dir) if runs_dir is not None else _REPO_ROOT / "runs"
    meta = _read_ckpt_meta(policy_path)
    task_name = meta.get("task", "gate_race")
    drone_count = max(1, int(drone_count))
    gateless = task_name in GATELESS_TASKS

    if gateless:
        # No gate course: the task carries its own arena + a moving target/anchor (the `scene`
        # channel records what it tracks). We only thread the requested episode length through so the
        # watched clip isn't truncated; bounds stay at the task's own defaults.
        pos = rad = None
        course_gates = 0
        course_label = "arena"
        # episode_len a hair beyond the rollout window so no terminal truncation-reset fires within
        # it: these tasks' holding/tracking rate metrics live in task.metrics() (reset-zeroed
        # accumulators), so a reset on the final step would report them as 0 (gate tasks dodge this
        # by reporting min/total metrics that survive a reset).
        bound_kw = {"episode_len": max(600, int(max_steps)) + 5}
    else:
        # Resolve the chosen course to tensors (shared by every env/agent via env.fixed_course).
        pos, rad, course_label = courses_mod.resolve_course(
            course, courses_dir, n_gates=int(n_gates), seed=int(seed), device=device,
        )
        course_gates = int(pos.shape[0])
        # Size the crash bounds + episode length to the CHOSEN course. Seeded/preset courses can place
        # gates far outside the default tight bounds (bound_xy=6 m), so without this the drone crosses
        # the boundary heading to gate 0 and crashes before reaching it. Add margin for the gate radius
        # and overshoot; never shrink below the tight defaults. episode_len = the requested window so a
        # long spread lap isn't truncated mid-flight.
        horiz_max = float(pos[:, :2].norm(dim=-1).max())
        z_max = float(pos[:, 2].max())
        rad_max = float(rad.max())
        bound_kw = {
            "bound_xy": max(6.0, horiz_max + rad_max + 2.0),
            "bound_z_max": max(4.0, z_max + rad_max + 1.5),
            "episode_len": max(600, int(max_steps)),
        }

    # Map drone-count to the substrate per the policy's task. Swarm tasks raise n_agents (shared env,
    # mutual awareness); the rest fly drone_count independent envs sharing one fixed scene.
    if task_name in SWARM_TASKS:
        n_agents = max(2, drone_count)
        n_envs = 1
        gate_kw = {} if gateless else {"n_gates": course_gates}
        task = make_task(task_name, n_agents=n_agents, **gate_kw, **bound_kw)
    elif gateless:
        n_agents = 1
        n_envs = drone_count
        task = make_task(task_name, **bound_kw)
    else:
        n_agents = 1
        n_envs = drone_count
        task = make_task(task_name, n_gates=course_gates, **bound_kw)

    # Match the checkpoint's frame-stack (obs_dim = base_obs_dim * obs_stack).
    ckpt_obs = int(meta.get("obs_dim") or task.obs_dim)
    obs_stack = max(1, ckpt_obs // int(task.obs_dim)) if task.obs_dim else 1

    dr_cfg = DomainRandomizationConfig(enabled=bool(dr))
    env = MultiAgentDroneEnv(task, n_envs=n_envs, device=device, seed=int(seed),
                             dr_cfg=dr_cfg, obs_stack=obs_stack)
    if env.obs_dim != ckpt_obs:
        raise ValueError(
            f"policy obs_dim {ckpt_obs} != env obs_dim {env.obs_dim} for task {task_name!r}"
        )
    if pos is not None:
        env.fixed_course = (pos.to(device), rad.to(device))

    agent = load_agent(str(policy_path), device=device)

    # Record all flown drones as one group. Swarm tasks (n_agents>1) record env 0's agents; the
    # single-agent tasks (gate_race + follow) record one drone per env (indices 0..n_envs-1).
    heroes = list(range(n_agents)) if task_name in SWARM_TASKS else list(range(n_envs))
    rec_meta = build_meta(env, config=f"studio:{task_name}:{course_label}",
                          policy=policy_label(agent, str(policy_path)))
    recorder = RunRecorder(rec_meta)
    metrics = evaluate_and_record(
        env, agent, recorder, heroes=heroes, steps=int(max_steps),
        deterministic=True, group=True,
    )

    stem = f"{policy_path.parent.name}-{courses_mod.slugify(course_label)}-{drone_count}d-s{seed}"
    out_path = runs_dir / "studio" / f"{stem}.json.gz"
    recorder.save(out_path)
    rel = out_path.resolve().relative_to(runs_dir.resolve()).as_posix()

    # Report only metrics that are MEANINGFUL for a single watched rollout. Gateless follow/formation
    # tasks have no laps — pass through their own holding/tracking metrics (whichever the task emits).
    # Gate tasks: we run one long episode per drone (episode_len == max_steps) so the hero clip is
    # continuous, but that makes the task's snapshot `lap_completion_rate` (laps since the last crash)
    # phase-sensitive and unfair — so we drop it and report episode_len-independent throughput instead:
    # best_lap (a min), total gates passed, and laps-per-drone (= gate passes / gates / drones).
    if gateless:
        keys = (
            "mean_reward", "crash_rate_per_step",
            "time_in_view_rate", "mean_track_error", "mean_distance", "follow_hold_rate",
            "stop_compliance", "near_hold", "far_hold",
            "mean_formation_error", "formation_hold_rate", "collision_rate_per_step",
            "mean_pos_error", "hold_rate", "mean_speed", "mean_tilt_deg",
        )
        studio_metrics = {k: metrics[k] for k in keys if k in metrics}
    else:
        total_drones = n_envs * n_agents
        gates_total = float(metrics.get("gates_passed_total", 0.0) or 0.0)
        studio_metrics = {
            "best_lap_time": metrics.get("best_lap_time"),
            "oracle_lap_time": metrics.get("oracle_lap_time"),
            "gates_passed_total": int(gates_total),
            "laps_per_drone": gates_total / max(1, course_gates * total_drones),
            "crash_rate_per_step": metrics.get("crash_rate_per_step"),
        }
    summary = {
        "run_path": rel,
        "task": task_name,
        "drone_count": drone_count,
        "course": course_label,
        "num_gates": course_gates,
        "dr": bool(dr),
        "metrics": {k: (None if isinstance(v, float) and v != v else v) for k, v in studio_metrics.items()},
    }
    return out_path, summary
