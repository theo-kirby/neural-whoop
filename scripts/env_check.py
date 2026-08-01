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
    # CUDA guarantees binary compatibility *forward* within a major compute capability: an sm_86
    # cubin runs on sm_89 (Ada), but not the reverse. So the gate is "some cubin of the same major
    # with a minor <= ours", not an exact string match — an exact match would fail on the 4070 box
    # against a wheel that ships sm_86 but not sm_89, even though every kernel runs fine.
    usable = [
        a for a in archs
        if a.startswith("sm_") and a[3:].isdigit()
        and int(a[3:-1] or 0) == cap[0] and int(a[3:][-1]) <= cap[1]
    ]
    assert usable, (
        f"{sm} has no compatible kernels in this torch build (arch_list={archs}) — need the "
        f"cu128 index; see pyproject's [[tool.uv.index]] pytorch-cu128"
    )
    if sm not in archs:
        print(f"[ok] no exact {sm} cubin, but {usable[-1]} is binary-compatible with it")
    # Run a real kernel and read it back (not just is_available()) — this is what actually proves
    # the compatibility argument above, so it matters more than the arch-list check.
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
    import torch
    dev = torch.cuda.get_device_name(0)
    cap = torch.cuda.get_device_capability(0)
    print(f"\n[PASS] environment is green — torch sm_{cap[0]}{cap[1]}, DiffAero, and the env all "
          f"run on the {dev}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
