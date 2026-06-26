#!/usr/bin/env python
"""Build the standard visual pack for a checkpoint — the artifacts a Flywheel node uploads.

Runs a recording rollout and emits, to an out dir: a portable ``replay.json.gz`` (the visual
contract), ``trajectory.png`` (flown path + gate-loop reference overlay), ``fpv_*.png``
synthetic onboard keyframes (+ optional ``fpv.gif``), ``training_curves.png`` (if the run dir
has TensorBoard events), ``eval.json``, and — with ``--baseline`` — a parent ``comparison.png``
plus a leaderboard ``table.csv``.

    uv run python scripts/viz.py --config configs/gate_race.yaml \
        --from runs/gate_race_tp005/ckpt_final.pt --no-dr \
        --baseline runs/gate_race_tp002/replay.json.gz --out runs/gate_race_tp005/viz

Rendering needs the viz extra:  uv pip install -e '.[viz]'  (the replay itself does not).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description="Build a neural-whoop visual pack.")
    p.add_argument("--from", dest="ckpt", type=str, required=True, help="Checkpoint path.")
    p.add_argument("--config", type=str, default=None)
    p.add_argument("--task", type=str, default=None)
    p.add_argument("--out", type=str, default=None, help="Pack output dir (default: <ckpt dir>/viz).")
    p.add_argument("--n-envs", type=int, default=2048)
    p.add_argument("--steps", type=int, default=1500, help="Recording rollout length (control steps).")
    p.add_argument("--n-heroes", type=int, default=4, help="Drones to record full telemetry for.")
    p.add_argument("--seed", type=int, default=12345)
    p.add_argument("--device", type=str, default="cuda")
    p.add_argument("--no-dr", action="store_true", help="Disable domain randomization (clean eval).")
    p.add_argument("--stochastic", action="store_true", help="Sample actions instead of the mean.")
    p.add_argument("--record-obs", action="store_true", help="Also store the obs vector per frame.")
    p.add_argument("--baseline", type=str, default=None, help="Baseline replay (.json[.gz]) to compare.")
    p.add_argument("--run-dir", type=str, default=None, help="Run dir for training curves (default: ckpt dir).")
    p.add_argument("--no-fpv", action="store_true", help="Skip synthetic FPV keyframes.")
    p.add_argument("--gif", action="store_true", help="Stitch FPV keyframes into a GIF (needs imageio).")
    args = p.parse_args()

    from neural_whoop.eval.pack import build_pack, record_rollout
    from neural_whoop.experiment import build_env, load_config
    from neural_whoop.training.ppo import load_agent

    cfg: dict = load_config(args.config) if args.config else {}
    if args.task:
        cfg.setdefault("task", {})["name"] = args.task
    if not cfg.get("task", {}).get("name"):
        print("[error] no task: pass --config or --task.")
        return 2

    ckpt_dir = Path(args.ckpt).parent
    out_dir = Path(args.out) if args.out else ckpt_dir / "viz"
    run_dir = Path(args.run_dir) if args.run_dir else ckpt_dir
    config_name = cfg.get("run", {}).get("name", cfg["task"]["name"])

    env = build_env(
        cfg, device=args.device, n_envs=args.n_envs, seed=args.seed,
        dr_enabled=(False if args.no_dr else None),
    )
    agent = load_agent(args.ckpt, device=args.device)

    print(f"=== recording {config_name} | ckpt={args.ckpt} | {env.n_drones} drones "
          f"| {args.steps} steps | {args.n_heroes} heroes | DR={'off' if args.no_dr else 'on'} ===")
    replay_path, metrics = record_rollout(
        env, agent, out_dir / "replay.json.gz",
        config=config_name, ckpt=args.ckpt, n_heroes=args.n_heroes,
        steps=args.steps, deterministic=not args.stochastic, record_obs=args.record_obs,
    )
    print(f"[replay] {replay_path}")
    for k, v in metrics.items():
        print(f"  {k:24s} {v:.4f}" if isinstance(v, float) else f"  {k:24s} {v}")

    artifacts = build_pack(
        replay_path, out_dir,
        run_dir=run_dir, baseline=args.baseline, eval_metrics=metrics,
        fpv=not args.no_fpv, gif=args.gif,
    )
    print(f"[pack] {len(artifacts)} artifacts -> {out_dir}")
    for name, kind in artifacts.items():
        print(f"  {kind:7s} {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
