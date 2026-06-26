#!/usr/bin/env python
"""Train a policy on the batched env with torch-native PPO.

    uv run python scripts/train.py --config configs/gate_race.yaml --tensorboard
    uv run python scripts/train.py --task gate_race --steps 5_000_000 --n-envs 4096
    uv run python scripts/train.py --config configs/gate_race.yaml --export

``--algo shac`` is reserved for DiffAero's differentiable short-horizon actor-critic (a later
optimization lever the autonomous agent can wire in); only ``ppo`` is implemented today.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path



def main() -> int:
    p = argparse.ArgumentParser(description="Train a neural-whoop policy.")
    p.add_argument("--config", type=str, default=None, help="YAML experiment config.")
    p.add_argument("--task", type=str, default=None, help="Task name (if no --config).")
    p.add_argument("--steps", type=int, default=None, help="Override total env steps.")
    p.add_argument("--n-envs", type=int, default=None, help="Override parallel env count.")
    p.add_argument("--seed", type=int, default=None, help="Override seed.")
    p.add_argument("--algo", choices=["ppo", "shac"], default="ppo")
    p.add_argument("--name", type=str, default=None, help="Run name (run dir under runs/).")
    p.add_argument("--device", type=str, default="cuda")
    p.add_argument("--tensorboard", action="store_true", help="Write TensorBoard scalars.")
    p.add_argument("--export", action="store_true", help="Export TorchScript+ONNX after training.")
    args = p.parse_args()

    from neural_whoop.experiment import build_env, load_config, make_ppo
    from neural_whoop.training.ppo import train_ppo

    if args.algo == "shac":
        print("[error] --algo shac is reserved (DiffAero differentiable RL); use ppo for now.")
        return 2

    cfg: dict = load_config(args.config) if args.config else {}
    if args.task:
        cfg.setdefault("task", {})["name"] = args.task
    if not cfg.get("task", {}).get("name"):
        print("[error] no task: pass --config or --task.")
        return 2

    ppo_cfg = make_ppo(cfg)
    if args.steps is not None:
        ppo_cfg.total_steps = args.steps
    if not args.tensorboard:
        pass

    env = build_env(cfg, device=args.device, n_envs=args.n_envs, seed=args.seed)
    name = args.name or cfg.get("run", {}).get("name", cfg["task"]["name"])
    run_dir = Path("runs") / name
    run_dir.mkdir(parents=True, exist_ok=True)

    writer = None
    if args.tensorboard:
        from torch.utils.tensorboard import SummaryWriter

        writer = SummaryWriter(str(run_dir))

    print(f"=== training {cfg['task']['name']} | run={name} | {env.n_drones} drones "
          f"| {ppo_cfg.total_steps:,} steps | device={args.device} ===")
    agent = train_ppo(env, ppo_cfg, str(run_dir), device=args.device, writer=writer)

    if args.export:
        from neural_whoop.training.export import build_deploy_policy, export_onnx, export_torchscript

        policy = build_deploy_policy(agent)
        ts = export_torchscript(policy, env.obs_dim, str(run_dir / "policy.pt"))
        print(f"[export] TorchScript -> {ts}")
        try:
            diff = export_onnx(policy, env.obs_dim, str(run_dir / "policy.onnx"))
            print(f"[export] ONNX -> {run_dir / 'policy.onnx'} (round-trip max diff {diff:.2e})")
        except ImportError:
            print("[export] ONNX skipped (install the 'export' extra: uv pip install -e '.[export]')")

    if writer is not None:
        writer.close()
    print(f"[done] checkpoints + logs in {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
