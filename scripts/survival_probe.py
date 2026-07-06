#!/usr/bin/env python
"""Pure-hold survival probe: the honest first-flight metric for the hover / hover_blind line.

The standard deterministic eval (``scripts/eval.py``) spawns a MIX of pure-hold and
tumble-recovery episodes, so its ``hold_rate`` / ``crash_rate`` blend station-keeping with the
recovery cohort's fly-in transients (the reason ``hover_blind_air65_long``'s standard hold_rate
reads 0.15 while it survives a real hover fine). This probe isolates the first-flight scenario:
**every** drone spawns exactly on the setpoint, level, at rest (``hold_fraction = 1.0``), and we
measure how many are still airborne after a full horizon — i.e. never left the arena bounds
(the floor ``bound_z_min`` is the one that matters for the open-loop-altitude sink).

``survival`` = fraction of drones that never crash across ``--steps`` control steps. For the
crashed cohort we also report the median time-to-first-exit (seconds), matching how the
trim-bias discovery was characterised ("100% floor exits, median 4.0 s" pre-fix -> "91%
survival" post-fix). Deterministic actor mean, DR off by default (``--dr`` for the DR-on
number, which open-loop altitude physically cannot win — see docs/SIM2REAL.md).

Usage:
  uv run python scripts/survival_probe.py --config configs/hover_blind_air65_long.yaml \
      --from runs/hover_blind_air65_long/ckpt_final.pt --no-dr --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import torch  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--from", dest="ckpt", type=str, required=True, help="Checkpoint path.")
    p.add_argument("--config", type=str, required=True, help="Config YAML (task + DR + airframe).")
    p.add_argument("--n-envs", type=int, default=2048, help="Pure-hold drones to probe.")
    p.add_argument("--steps", type=int, default=1500, help="Horizon in control steps (1500 = 30 s).")
    p.add_argument("--seed", type=int, default=12345)
    p.add_argument("--device", type=str, default="cuda")
    p.add_argument("--no-dr", action="store_true", help="Disable DR (the honest first-flight number).")
    p.add_argument("--dr", dest="force_dr", action="store_true", help="Force DR on (open-loop ceiling).")
    p.add_argument("--json", action="store_true", help="Emit metrics as JSON only.")
    args = p.parse_args()

    from neural_whoop.experiment import build_env, load_config
    from neural_whoop.training.ppo import load_agent

    cfg = load_config(args.config)
    # Force every episode to spawn on-setpoint, level, at rest — the first-flight scenario.
    cfg.setdefault("task", {})["hold_fraction"] = 1.0

    dr_enabled = True if args.force_dr else (False if args.no_dr else None)
    env = build_env(cfg, device=args.device, n_envs=args.n_envs, seed=args.seed, dr_enabled=dr_enabled)
    agent = load_agent(args.ckpt, device=args.device)

    dev = env.device
    n = env.n_drones
    ever_crashed = torch.zeros(n, dtype=torch.bool, device=dev)
    first_exit = torch.full((n,), -1, dtype=torch.long, device=dev)  # step index of first crash

    obs = env.reset_all()
    with torch.no_grad():
        for t in range(args.steps):
            action = agent.act_deterministic(obs)
            obs, _reward, term, _trunc, info = env.step(action)
            crashed = info.get("crashed")
            if crashed is None:
                crashed = term
            newly = crashed.bool() & (~ever_crashed)
            first_exit = torch.where(newly, torch.full_like(first_exit, t), first_exit)
            ever_crashed |= crashed.bool()

    survived = ~ever_crashed
    survival = survived.float().mean().item()
    dt = float(env.dt)
    crashed_steps = first_exit[ever_crashed].float()
    median_exit_s = (crashed_steps.median().item() * dt) if crashed_steps.numel() else None

    out = {
        "config": args.config,
        "ckpt": args.ckpt,
        "n_drones": n,
        "steps": args.steps,
        "horizon_s": round(args.steps * dt, 2),
        "dr": bool(dr_enabled),
        "survival": round(survival, 4),
        "crashed_frac": round(1.0 - survival, 4),
        "median_time_to_exit_s": (round(median_exit_s, 2) if median_exit_s is not None else None),
    }
    if args.json:
        print(json.dumps(out))
    else:
        print(f"=== survival probe | {Path(args.ckpt).name} | {n} pure-hold drones "
              f"| {out['horizon_s']} s | DR={'on' if dr_enabled else 'off'} ===")
        print(f"survival {survival:.1%}  ({int(survived.sum())}/{n} held the full horizon)")
        if median_exit_s is not None:
            print(f"crashed cohort: {int(ever_crashed.sum())}/{n}, median time-to-exit {median_exit_s:.2f} s")


if __name__ == "__main__":
    main()
