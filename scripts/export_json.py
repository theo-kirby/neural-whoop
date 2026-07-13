#!/usr/bin/env python
"""Export a trained TinyPolicy checkpoint to the pilot's pure-Python JSON deploy format.

Replaces the never-committed ad-hoc extraction snippet: emits, next to the checkpoint,

  policy_weights.json      meta (task, dims, stacking, log_std, layouts) + actor W/b lists —
                           exactly what ``scripts/pilot.py``'s dependency-free Policy loads.
  policy_ref_outputs.json  named probe observations + the deploy-exact actions (forwarded
                           through ``training.ppo.clipped_gaussian_mean``), the parity oracle
                           for ``pilot.py selftest``. Ref *inputs* are single BASE frames; a
                           stacked policy (obs_stack > 1) sees each frame tiled across the
                           whole stack — repeated frame == the env's reset semantics
                           (envs/base.py), and exactly how the pilot seeds its obs deque.

Works for old pre-stacking checkpoints too (base_obs_dim/obs_stack absent -> derived from the
task registry; plain 5-dim hover_blind ckpts export with obs_stack 1, byte-compatible with the
hand-extracted files already deployed).

Usage:
  uv run python scripts/export_json.py --ckpt runs/<run>/ckpt_final.pt [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import torch  # noqa: E402

from neural_whoop.training.ppo import clipped_gaussian_mean  # noqa: E402

# Human-readable channel layouts per task family (documentation for whoever reads the JSON).
OBS_LAYOUTS = {
    "hover_blind": "hover_blind: [roll, pitch, p, q, r] (rad, rad/s; frame x fwd/y left/z up)",
    "hover_blind_v2": "hover_blind_v2: [roll, pitch, p, q, r, vz_est] (rad, rad/s, m/s; "
                      "frame x fwd/y left/z up; vz_est = leaky acc-integrated climb rate)",
    "hover_tof": "hover_tof: [roll, pitch, p, q, r, height_err] (rad, rad/s, m; frame x fwd/"
                 "y left/z up; height_err = target_height - measured height, tilt-corrected "
                 "bridge ToF held at the last valid reading)",
}
ACT_LAYOUT = "act-v2: [thrust(-1..1 -> 0..4x hover), roll_rate, pitch_rate, yaw_rate]"


def _stack_dims(d: dict) -> tuple[int, int]:
    """(base_obs_dim, obs_stack) — from the ckpt if recorded, else derived via the registry."""
    obs_dim = int(d["obs_dim"])
    if "base_obs_dim" in d:
        return int(d["base_obs_dim"]), int(d.get("obs_stack", 1))
    import neural_whoop.tasks  # noqa: F401 - register tasks
    from neural_whoop.envs.registry import TASK_REGISTRY

    base = TASK_REGISTRY[d["task"]].obs_dim
    if obs_dim % base != 0:
        raise ValueError(f"ckpt obs_dim {obs_dim} is not a multiple of task obs_dim {base}")
    return base, obs_dim // base


def _probes(base_dim: int, task: str = "", seed: int = 0) -> dict[str, list[float]]:
    """Named single-frame probe observations (base dim, not stacked)."""
    named = [
        ("level_still", None, 0.0),
        ("roll_right_0.1rad", 0, 0.1),
        ("pitch_nose_down_0.1rad", 1, 0.1),
        ("roll_rate_p_1rps", 2, 1.0),
        ("yaw_rate_r_1rps", 4, 1.0),
    ]
    if task == "hover_tof":  # channel 5 = height_err (m, + = climb), not vz
        named += [
            ("below_target_err_+0.3m", 5, 0.3),
            ("above_target_err_-0.3m", 5, -0.3),
        ]
    else:
        named += [
            ("sink_vz_-0.5mps", 5, -0.5),
            ("climb_vz_+0.5mps", 5, 0.5),
        ]
    probes: dict[str, list[float]] = {}
    for name, idx, val in named:
        if idx is not None and idx >= base_dim:
            continue
        v = [0.0] * base_dim
        if idx is not None:
            v[idx] = val
        probes[name] = v
    gen = torch.Generator().manual_seed(seed)
    for k in range(3):
        probes[f"random_{k}"] = (torch.randn(base_dim, generator=gen) * 0.3).tolist()
    return probes


def export_json(ckpt_path: str, out_dir: str | None = None) -> dict:
    d = torch.load(ckpt_path, map_location="cpu", weights_only=True)
    sd = d["model"]
    obs_dim, act_dim = int(d["obs_dim"]), int(d["act_dim"])
    base_dim, stack = _stack_dims(d)
    assert base_dim * stack == obs_dim, (base_dim, stack, obs_dim)
    act_name = dict(d.get("ppo_cfg", {})).get("activation", "tanh")
    log_std = sd["log_std"]

    # Actor Linear layers in order (actor.net.<i>.weight, torch layout [out, in]) — the same
    # collection scripts/export_c.py uses.
    idxs = sorted({int(k.split(".")[2]) for k in sd if k.startswith("actor.net.") and k.endswith(".weight")})
    layers = [(sd[f"actor.net.{i}.weight"], sd[f"actor.net.{i}.bias"]) for i in idxs]
    assert layers[0][0].shape[1] == obs_dim and layers[-1][0].shape[0] == act_dim

    out = Path(out_dir) if out_dir else Path(ckpt_path).parent
    out.mkdir(parents=True, exist_ok=True)

    task = d.get("task", "?")
    weights = {
        "meta": {
            "task": task,
            "obs_dim": obs_dim,
            "base_obs_dim": base_dim,
            "obs_stack": stack,
            "act_dim": act_dim,
            "global_step": int(d.get("global_step", -1)),
            "activation": act_name,
            "log_std": log_std.tolist(),
            "output": "clipped_gaussian_mean",
            "obs_layout": OBS_LAYOUTS.get(task, f"{task}: see the task module")
                          + (f" x {stack} stacked frames, oldest->newest" if stack > 1 else ""),
            "act_layout": ACT_LAYOUT,
            "source_ckpt": str(ckpt_path),
        },
        "layers": [{"W": w.tolist(), "b": b.tolist()} for w, b in layers],
    }
    with open(out / "policy_weights.json", "w") as f:
        json.dump(weights, f)

    # Reference outputs through the exact deploy semantics: tiled frame -> linears+activation
    # -> clipped-Gaussian effective mean (the trim-bias fix; training/ppo.py).
    probes = _probes(base_dim, task)
    ref: dict = {"inputs": {}, "outputs": {},
                 "meta": {"base_obs_dim": base_dim, "obs_stack": stack,
                          "note": "inputs are single base frames; tile x obs_stack (repeat) "
                                  "before the forward pass (reset semantics)"}}
    with torch.no_grad():
        std = log_std.exp()
        for name, frame in probes.items():
            h = torch.tensor(frame * stack, dtype=torch.float32)
            for j, (w, b) in enumerate(layers):
                h = h @ w.T + b
                if j < len(layers) - 1:
                    h = torch.tanh(h) if act_name == "tanh" else torch.relu(h)
            act = clipped_gaussian_mean(h, std)
            ref["inputs"][name] = frame
            ref["outputs"][name] = act.tolist()
    with open(out / "policy_ref_outputs.json", "w") as f:
        json.dump(ref, f, indent=1)

    n_params = sum(w.numel() + b.numel() for w, b in layers)
    return {"task": task, "obs_dim": obs_dim, "base_obs_dim": base_dim, "obs_stack": stack,
            "act_dim": act_dim, "n_params": n_params, "out": str(out)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--out", default=None, help="output dir (default: next to the ckpt)")
    args = ap.parse_args()
    info = export_json(args.ckpt, args.out)
    print(f"wrote {info['out']}/policy_weights.json + policy_ref_outputs.json")
    for k, v in info.items():
        print(f"  {k}: {v}")
