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
    p.add_argument("--record", nargs="?", const="", default=None, metavar="PATH",
                   help="Record a hero replay to PATH (default: <ckpt dir>/replay.json.gz). "
                        "Portable JSON; works without the viz extra.")
    p.add_argument("--viz", action="store_true",
                   help="Build the standard visual pack (implies --record; needs the viz extra).")
    p.add_argument("--n-heroes", type=int, default=4, help="Drones to record full telemetry for.")
    p.add_argument("--baseline", type=str, default=None, help="Baseline replay to compare in the pack.")
    args = p.parse_args()

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

    do_record = args.viz or (args.record is not None)
    ckpt_dir = Path(args.ckpt).parent
    if do_record:
        from neural_whoop.eval.pack import build_pack, build_run_meta, record_rollout

        config_name = cfg.get("run", {}).get("name", cfg["task"]["name"])
        replay_path = Path(args.record) if args.record else (ckpt_dir / "replay.json.gz")
        replay_path, metrics = record_rollout(
            env, agent, replay_path,
            config=config_name, ckpt=args.ckpt, n_heroes=args.n_heroes,
            steps=args.steps, deterministic=not args.stochastic,
        )
        print(f"[record] replay -> {replay_path}")
        if args.viz:
            run_meta = build_run_meta(
                config=args.config, ckpt=args.ckpt, seed=args.seed, n_envs=args.n_envs,
                steps=args.steps, dr=(not args.no_dr), task=cfg["task"]["name"],
            )
            artifacts = build_pack(
                replay_path, ckpt_dir / "viz",
                run_dir=ckpt_dir, baseline=args.baseline, eval_metrics=metrics, run_meta=run_meta,
            )
            print(f"[viz] {len(artifacts)} artifacts -> {ckpt_dir / 'viz'}")
    else:
        from neural_whoop.eval.rollout import evaluate

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
