#!/usr/bin/env python
"""Evaluate a trained checkpoint: roll out and report lap times / success metrics.

    uv run python scripts/eval.py --config configs/gate_race.yaml --from runs/gate_race_baseline/ckpt_final.pt
    uv run python scripts/eval.py --task gate_race --from <ckpt> --no-dr --json

Reports the task metrics (for gate_race: best/last lap time, laps completed, completion rate,
and the oracle baseline). ``--export`` writes the deployable TorchScript/ONNX policy.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path



def main() -> int:
    p = argparse.ArgumentParser(description="Evaluate a neural-whoop policy.")
    p.add_argument("--from", dest="ckpt", type=str, required=True, help="Checkpoint path.")
    p.add_argument("--config", type=str, default=None)
    p.add_argument("--task", type=str, default=None)
    p.add_argument("--n-envs", type=int, default=2048)
    p.add_argument("--steps", type=int, default=1500, help="Eval rollout length (control steps).")
    p.add_argument("--seed", type=int, default=12345)
    p.add_argument("--device", type=str, default="cuda")
    p.add_argument("--no-dr", action="store_true", help="Disable domain randomization (clean eval).")
    p.add_argument("--stochastic", action="store_true", help="Sample actions instead of the mean.")
    p.add_argument("--json", action="store_true", help="Print metrics as JSON only.")
    p.add_argument("--export", action="store_true", help="Export TorchScript+ONNX from this ckpt.")
    args = p.parse_args()

    from neural_whoop.eval.rollout import evaluate
    from neural_whoop.experiment import build_env, load_config
    from neural_whoop.training.ppo import load_agent

    cfg: dict = load_config(args.config) if args.config else {}
    if args.task:
        cfg.setdefault("task", {})["name"] = args.task
    if not cfg.get("task", {}).get("name"):
        print("[error] no task: pass --config or --task.")
        return 2

    env = build_env(
        cfg, device=args.device, n_envs=args.n_envs, seed=args.seed,
        dr_enabled=(False if args.no_dr else None),
    )
    agent = load_agent(args.ckpt, device=args.device)
    metrics = evaluate(env, agent, steps=args.steps, deterministic=not args.stochastic)

    if args.json:
        print(json.dumps(metrics, indent=2))
    else:
        print(f"=== eval {cfg['task']['name']} | ckpt={args.ckpt} | {env.n_drones} drones "
              f"| {args.steps} steps | DR={'off' if args.no_dr else 'on'} ===")
        for k, v in metrics.items():
            print(f"  {k:24s} {v:.4f}" if isinstance(v, float) else f"  {k:24s} {v}")

    if args.export:
        from neural_whoop.training.export import build_deploy_policy, export_onnx, export_torchscript

        out = Path(args.ckpt).parent
        policy = build_deploy_policy(agent)
        print(f"[export] TorchScript -> {export_torchscript(policy, env.obs_dim, str(out / 'policy.pt'))}")
        try:
            diff = export_onnx(policy, env.obs_dim, str(out / "policy.onnx"))
            print(f"[export] ONNX -> {out / 'policy.onnx'} (max diff {diff:.2e})")
        except ImportError:
            print("[export] ONNX skipped (install '.[export]').")
    return 0


if __name__ == "__main__":
    sys.exit(main())
