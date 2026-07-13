#!/usr/bin/env python
"""Exit-direction decomposition for the hover family: floor vs ceiling vs horizontal exits.

Pure-hold cohort (hold_fraction forced 1.0, like survival_probe.py), deterministic mean, DR from
the given config. Splits every first crash by which bound it hit — the question a bare survival
number can't answer ("does the failure sink, climb, or fly away sideways?"). First used ad-hoc
for the d50var_s8 exit_direction.json; committed for the hover_tof battery, where it showed ALL
M1-live failures are horizontal (0 floor / 0 ceiling) — the altitude loop is closed.

Usage:
  uv run python scripts/exit_probe.py <config.yaml> <ckpt.pt>

Note: survivor_mean_z_err reads pos at the final step, which auto-resets when the horizon equals
episode_len — treat it as junk unless the horizon is shorter than the episode.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import torch

from neural_whoop.experiment import build_env, load_config
from neural_whoop.training.ppo import load_agent

cfg_path, ckpt = sys.argv[1], sys.argv[2]
cfg = load_config(cfg_path)
cfg.setdefault("task", {})["hold_fraction"] = 1.0
env = build_env(cfg, device="cuda", n_envs=2048, seed=12345, dr_enabled=True)
agent = load_agent(ckpt, device="cuda")

n = env.n_drones
ever = torch.zeros(n, dtype=torch.bool, device=env.device)
kind = torch.zeros(n, dtype=torch.long, device=env.device)  # 1 floor, 2 ceiling, 3 xy
first_exit = torch.full((n,), -1.0, device=env.device)
bounds = env.task._bounds

obs = env.reset_all()
with torch.no_grad():
    for t in range(1500):
        a = agent.act_deterministic(obs)
        obs, _r, term, _tr, info = env.step(a)
        crashed = info.get("crashed", term).bool()
        pos = env.dyn.pos
        newly = crashed & ~ever
        if newly.any():
            floor = pos[:, 2] <= bounds.z_min + 1e-3
            ceil = pos[:, 2] >= bounds.z_max - 1e-3
            k = torch.where(floor, 1, torch.where(ceil, 2, 3))
            kind = torch.where(newly, k, kind)
            first_exit = torch.where(newly, torch.full_like(first_exit, t * env.dt), first_exit)
        ever |= crashed

surv = (~ever).float().mean().item()
out = {
    "config": cfg_path, "survival": surv,
    "floor": int((kind == 1).sum()), "ceiling": int((kind == 2).sum()),
    "xy": int((kind == 3).sum()),
    "median_exit_s": (float(first_exit[first_exit >= 0].median()) if ever.any() else None),
    "survivor_mean_z_err": float(
        (env.task.setpoint[~ever, 2] - env.dyn.pos[~ever, 2]).abs().mean()
    ) if (~ever).any() else None,
}
print(json.dumps(out))
