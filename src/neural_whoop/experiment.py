"""Experiment wiring: YAML config -> env + task + PPO config.

Centralizes the "build the pieces from a config dict" logic so ``scripts/train.py``,
``scripts/eval.py``, and the autonomous agent all construct experiments the same way. A config
is a plain dict (loaded from YAML) with optional sections ``task``, ``env``, ``dr``, ``whoop``,
``ppo``, ``run``; unknown keys in a section raise (typo guard).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import torch
import yaml

from neural_whoop.dynamics.whoop import WhoopParams
from neural_whoop.envs.base import MultiAgentDroneEnv
from neural_whoop.envs.registry import make_task
from neural_whoop.randomization import DomainRandomizationConfig
from neural_whoop.training.ppo import PPOConfig
import neural_whoop.tasks  # noqa: F401 - register built-in tasks


def load_config(path: str | Path) -> dict:
    """Load a YAML experiment config into a dict (empty dict if the file is empty)."""
    return yaml.safe_load(Path(path).read_text()) or {}


def _filtered(cls, d: dict | None):
    """Instantiate dataclass ``cls`` from dict ``d``, rejecting unknown keys (typo guard)."""
    d = dict(d or {})
    valid = {f.name for f in dataclasses.fields(cls)}
    unknown = set(d) - valid
    if unknown:
        raise ValueError(f"Unknown {cls.__name__} keys: {sorted(unknown)}")
    # tuples in dataclasses arrive as lists from YAML — coerce by field default type.
    for f in dataclasses.fields(cls):
        if f.name in d and isinstance(getattr(cls, f.name, None), tuple) and isinstance(d[f.name], list):
            d[f.name] = tuple(d[f.name])
    return cls(**d)


def make_dr(cfg: dict) -> DomainRandomizationConfig:
    return _filtered(DomainRandomizationConfig, cfg.get("dr"))


def make_whoop(cfg: dict) -> WhoopParams:
    return _filtered(WhoopParams, cfg.get("whoop"))


def make_ppo(cfg: dict) -> PPOConfig:
    ppo = _filtered(PPOConfig, cfg.get("ppo"))
    if isinstance(ppo.hidden_sizes, list):
        ppo.hidden_sizes = tuple(ppo.hidden_sizes)
    return ppo


def build_env(
    cfg: dict,
    device: torch.device | str = "cuda",
    n_envs: int | None = None,
    seed: int | None = None,
    dr_enabled: bool | None = None,
) -> MultiAgentDroneEnv:
    """Construct the env + task from a config dict, with optional overrides.

    Args:
        cfg: The full config dict.
        device: Torch device.
        n_envs: Override ``env.n_envs``.
        seed: Override ``env.seed``.
        dr_enabled: Force DR on/off (e.g. ``False`` for an honest eval).
    """
    env_cfg = dict(cfg.get("env", {}))
    task_cfg = dict(cfg.get("task", {}))
    task_name = task_cfg.pop("name", "gate_race")
    task = make_task(task_name, **task_cfg)

    dr = make_dr(cfg)
    if dr_enabled is not None:
        dr = dataclasses.replace(dr, enabled=dr_enabled)
    whoop = make_whoop(cfg)

    return MultiAgentDroneEnv(
        task=task,
        n_envs=n_envs if n_envs is not None else int(env_cfg.get("n_envs", 4096)),
        device=device,
        seed=seed if seed is not None else int(env_cfg.get("seed", 0)),
        dr_cfg=dr,
        whoop_params=whoop,
    )
