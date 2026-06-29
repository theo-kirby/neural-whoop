#!/usr/bin/env python
"""Eval a checkpoint across COURSE SCALES — the generalization yardstick for studio policies.

    uv run python scripts/eval_scales.py --from runs/<run>/ckpt_final.pt

Rolls the policy over *random* courses of each named scale (tight / spread / big / giant), measured
exactly like the official ``evaluate`` (random per-env courses, episode_len < steps so completion
is a valid cycled metric, DR off). This is the apples-to-apples way to compare a tight-only baseline
against a scale-generalist — the single-fixed-course completion in the studio summary is
phase-sensitive and NOT a fair score (see the studio notes).

Holds ``gate_radius`` and ``n_gates`` at the training values so only the arena scale varies.
"""

from __future__ import annotations

import argparse
import json

#: Arena scales (radius m, gate hop m, ceiling m) + crash bounds sized to each. Matches
#: ``neural_whoop.course.ARENA_PRESETS`` so the table lines up with the studio course dropdown.
SCALES = {
    "tight":  dict(arena_radius=4.5,  step_min=1.5, step_max=2.8,  z_max=2.3, bound_xy=6.0,  bound_z_max=4.0),
    "spread": dict(arena_radius=8.0,  step_min=3.0, step_max=5.5,  z_max=3.0, bound_xy=10.0, bound_z_max=5.0),
    "big":    dict(arena_radius=12.0, step_min=4.5, step_max=7.5,  z_max=3.5, bound_xy=15.0, bound_z_max=5.0),
    "giant":  dict(arena_radius=18.0, step_min=6.0, step_max=10.0, z_max=4.0, bound_xy=21.0, bound_z_max=6.0),
}


def main() -> int:
    p = argparse.ArgumentParser(description="Eval a policy across course scales.")
    p.add_argument("--from", dest="ckpt", required=True, help="Checkpoint path.")
    p.add_argument("--n-envs", type=int, default=4096)
    p.add_argument("--steps", type=int, default=1500, help="Rollout length (control steps).")
    p.add_argument("--episode-len", type=int, default=600, help="Per-episode horizon (< steps).")
    p.add_argument("--n-gates", type=int, default=5)
    p.add_argument("--gate-radius", type=float, default=0.45)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--device", default="cuda")
    p.add_argument("--dr", action="store_true", help="Eval with DR on (default off).")
    p.add_argument("--config", default=None,
                   help="Optional YAML config: use its `whoop` airframe + `dr` so the eval matches "
                        "the policy's training env (e.g. a sim2real re-centered airframe + latency). "
                        "`--dr` still toggles whether seam DR is enabled.")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    import dataclasses
    from neural_whoop.envs.base import MultiAgentDroneEnv
    from neural_whoop.envs.registry import make_task
    import neural_whoop.tasks  # noqa: F401 - register tasks
    from neural_whoop.eval.rollout import evaluate
    from neural_whoop.randomization import DomainRandomizationConfig
    from neural_whoop.training.ppo import load_agent

    # Airframe + DR: default whoop/DR, or pulled from a config so the eval env matches training.
    whoop_params = None
    if args.config is not None:
        from neural_whoop.experiment import load_config, make_whoop, make_dr
        cfg = load_config(args.config)
        whoop_params = make_whoop(cfg)
        dr_cfg = dataclasses.replace(make_dr(cfg), enabled=args.dr)
    else:
        dr_cfg = DomainRandomizationConfig(enabled=args.dr)

    agent = load_agent(args.ckpt, device=args.device)
    out: dict[str, dict] = {}
    rows = []
    for name, kw in SCALES.items():
        task = make_task("gate_race", n_gates=args.n_gates, gate_radius=args.gate_radius,
                         episode_len=args.episode_len, **kw)
        env_kw = {} if whoop_params is None else {"whoop_params": whoop_params}
        env = MultiAgentDroneEnv(task, n_envs=args.n_envs, device=args.device, seed=args.seed,
                                 dr_cfg=dr_cfg, **env_kw)
        m = evaluate(env, agent, steps=args.steps)
        out[name] = m
        rows.append((name, m["lap_completion_rate"], m["best_lap_time"],
                     m["crash_rate_per_step"], m["laps_completed_mean"]))

    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"\n{'scale':>7} | completion | best_lap | crash/step | laps/ep")
        print("-" * 56)
        for name, comp, lap, crash, laps in rows:
            lap_s = f"{lap:.2f}s" if lap == lap else "  —  "
            print(f"{name:>7} |    {comp:.2f}    |  {lap_s:>6} | {crash*1e3:>7.2f}e-3 | {laps:.1f}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
