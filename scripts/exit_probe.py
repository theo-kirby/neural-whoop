#!/usr/bin/env python
"""Exit-direction decomposition for the hover family: floor vs ceiling vs horizontal exits.

Pure-hold cohort (hold_fraction forced 1.0, like survival_probe.py), deterministic mean, DR from
the given config. Splits every first crash by which bound it hit — the question a bare survival
number can't answer ("does the failure sink, climb, or fly away sideways?").

Usage:
  uv run python scripts/exit_probe.py <config.yaml> <ckpt.pt>

**FIXED 2026-08-08 — every result this script printed before that date was wrong.** It read
``env.dyn.pos`` *after* ``env.step()``, but ``step()`` auto-resets crashed drones in place
(``envs/base.py``: ``reset_idx`` runs inside ``step``). So the position it classified was the
*respawn*, which is by construction inside the bounds — making ``floor`` and ``ceiling``
**unreachable** and every exit fall through to ``xy``. The script could only ever print
``floor: 0, ceiling: 0``, which is precisely the "all failures are horizontal / the altitude loop
is closed" finding that was then quoted into docs/TASK_CATALOG.md and docs/SIM2REAL.md. Measured
on the parent (``hover_tof_air65_w128u15_r25`` on its own full-DR config): 793 exits, all reported
``xy``. The fix stashes the post-dynamics / pre-reset position at the moment ``is_crashed`` sees
it, by spying on ``task.reward_and_done``.

``survivor_mean_z_err`` used the same stale read (its old docstring flagged the symptom without
the cause) and is now taken from the stashed pre-reset position too, so it is meaningful even when
the horizon equals ``episode_len``.
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

# The post-dynamics, PRE-RESET position — the one is_crashed actually judged. See the module
# docstring: reading env.dyn.pos after step() gives the respawn and makes floor/ceiling unreachable.
_real_reward_and_done = env.task.reward_and_done
_stash = {}


def _spy(e, a):
    _stash["pos"] = e.dyn.pos.clone()
    return _real_reward_and_done(e, a)


env.task.reward_and_done = _spy

obs = env.reset_all()
with torch.no_grad():
    for t in range(1500):
        a = agent.act_deterministic(obs)
        obs, _r, term, _tr, info = env.step(a)
        crashed = info.get("crashed", term).bool()
        pos = _stash["pos"]
        newly = crashed & ~ever
        if newly.any():
            floor = pos[:, 2] <= bounds.z_min + 1e-3
            ceil = pos[:, 2] >= bounds.z_max - 1e-3
            k = torch.where(floor, 1, torch.where(ceil, 2, 3))
            kind = torch.where(newly, k, kind)
            first_exit = torch.where(newly, torch.full_like(first_exit, t * env.dt), first_exit)
        ever |= crashed

surv = (~ever).float().mean().item()
final_pos = _stash["pos"]
out = {
    "config": cfg_path, "survival": surv,
    "floor": int((kind == 1).sum()), "ceiling": int((kind == 2).sum()),
    "xy": int((kind == 3).sum()),
    "median_exit_s": (float(first_exit[first_exit >= 0].median()) if ever.any() else None),
    "survivor_mean_z_err": float(
        (env.task.setpoint[~ever, 2] - final_pos[~ever, 2]).abs().mean()
    ) if (~ever).any() else None,
}
print(json.dumps(out))
