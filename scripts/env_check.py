#!/usr/bin/env python
"""Milestone-0 smoke test: torch+cu128 on the 5090, DiffAero steps, a short env train loop.

Run this first (and after any environment change). It fails loudly with a non-zero exit if the
GPU/substrate isn't healthy, so we never build on a broken foundation.

    uv run python scripts/env_check.py
"""

from __future__ import annotations

import sys
import time


def check_torch_gpu() -> None:
    import torch

    print(f"torch {torch.__version__}")
    assert torch.cuda.is_available(), "CUDA not available"
    name = torch.cuda.get_device_name(0)
    cap = torch.cuda.get_device_capability(0)
    archs = torch.cuda.get_arch_list()
    print(f"device: {name}  capability sm_{cap[0]}{cap[1]}  arch_list={archs}")
    sm = f"sm_{cap[0]}{cap[1]}"
    assert sm in archs, f"{sm} kernels missing from this torch build — need the cu128 index"
    # Run a real kernel and read it back (not just is_available()).
    a = torch.randn(4096, 4096, device="cuda")
    val = (a @ a).sum().item()
    torch.cuda.synchronize()
    assert val == val, "matmul produced NaN"
    print(f"[ok] real sm_{cap[0]}{cap[1]} kernel ran (matmul sum={val:.1f})")


def check_diffaero(n_envs: int = 4096) -> None:
    import torch

    import neural_whoop  # noqa: F401 - vendored diffaero on path
    from neural_whoop.dynamics.whoop import WhoopDynamics

    dyn = WhoopDynamics(n_envs, device="cuda")
    ctbr = torch.zeros(n_envs, 4, device="cuda")
    ctbr[:, 0] = 1.0  # ~hover thrust
    for _ in range(50):
        dyn.step(ctbr)
    torch.cuda.synchronize()
    t0 = time.time()
    for _ in range(500):
        dyn.step(ctbr)
    torch.cuda.synchronize()
    sps = 500 * n_envs / (time.time() - t0)
    assert torch.isfinite(dyn.model._state).all(), "DiffAero produced NaN/Inf state"
    print(f"[ok] DiffAero stepped {n_envs} parallel whoops at {sps / 1e6:.2f}M env-steps/s")


def check_env_train(n_envs: int = 2048, steps: int = 1000) -> None:
    import torch

    from neural_whoop.envs.base import MultiAgentDroneEnv
    from neural_whoop.envs.registry import make_task
    import neural_whoop.tasks  # noqa: F401

    env = MultiAgentDroneEnv(make_task("gate_race"), n_envs=n_envs, device="cuda", seed=0)
    obs = env.reset_all()
    assert obs.shape == (n_envs, env.obs_dim) and torch.isfinite(obs).all()
    t0 = time.time()
    for _ in range(steps):
        a = torch.randn(env.n_drones, env.act_dim, device="cuda") * 0.3
        obs, r, term, trunc, info = env.step(a)
        assert torch.isfinite(obs).all() and torch.isfinite(r).all(), "env produced NaN"
    torch.cuda.synchronize()
    sps = steps * n_envs / (time.time() - t0)
    print(f"[ok] {steps}-step gate_race loop on {n_envs} envs ran clean at {sps / 1e6:.2f}M env-steps/s")


def main() -> int:
    print("=== neural-whoop env_check (Milestone-0 gate) ===")
    try:
        check_torch_gpu()
        check_diffaero()
        check_env_train()
    except Exception as e:  # noqa: BLE001
        print(f"\n[FAIL] {type(e).__name__}: {e}")
        return 1
    print("\n[PASS] environment is green — torch sm_120, DiffAero, and the env all run on the 5090.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
