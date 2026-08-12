#!/usr/bin/env python
"""Channel-value knockout: zero chosen obs channels at EVAL time and re-measure.

The sibling of the noise knockout already in the ladder (``runs/hover_tof_air65/probes.json``,
``attribution_knockouts_m1live_1x``), which turned per-channel DR *noise* off. This one is
blunter and answers a different question: not "is this channel's noise responsible" but **"is
this channel's information responsible"**. It takes a trained policy, forces the named base-frame
channels to zero in every stacked frame before the forward, and reports the same metric dict as
``scripts/eval.py``.

Two things it settles, and they are independent:

1. **Did the win come from the channel?** A policy whose advantage survives having the channel
   zeroed did not get that advantage from the channel — it got it from the extra parameters, the
   seed, or something else that differed. This is the causal check on any obs-ablation result.
2. **Is a regression driven by the live values or baked into the weights?** A DC error that
   persists with the channel zeroed is a learned trim, not a response to what the channel is
   saying.

Zeroing is the honest neutral for a *velocity* channel — it is exactly what the deployed pilot
feeds when flow goes blind (``tasks/hover_flow.py``'s grace-then-fade), so a knockout run is also
a real deploy scenario: "the sensor died mid-flight". It is NOT neutral for every channel; zeroing
``h_err`` means "you are exactly at your setpoint", which is a confident lie rather than an
absence. Read the channel's semantics before reading the result.

Usage:
  uv run python scripts/knockout_probe.py <config.yaml> <ckpt.pt> --channels 6,7 [--no-dr]

``--channels`` are indices into the BASE frame (pre-stacking), so ``6,7`` zeroes the flow pair in
each of the ``obs_stack`` frames the policy sees.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import torch

from neural_whoop.eval.rollout import evaluate
from neural_whoop.experiment import build_env, load_config
from neural_whoop.training.ppo import load_agent


class ChannelKnockout(torch.nn.Module):
    """Wraps an ActorCritic and zeroes ``channels`` in every stacked frame before the forward.

    Delegates by ``__getattr__`` rather than subclassing so it stays correct if ActorCritic grows
    methods; only the two entry points ``evaluate`` uses are intercepted.
    """

    def __init__(self, agent, channels: list[int], base_obs_dim: int, obs_stack: int) -> None:
        super().__init__()
        self.agent = agent
        self.base_obs_dim = base_obs_dim
        self.obs_stack = obs_stack
        bad = [c for c in channels if not 0 <= c < base_obs_dim]
        if bad:
            raise SystemExit(f"--channels {bad} out of range for base_obs_dim {base_obs_dim}")
        # Absolute indices into the stacked obs: channel c of every frame.
        self.idx = torch.tensor(
            [f * base_obs_dim + c for f in range(obs_stack) for c in channels], dtype=torch.long
        )

    def _mask(self, obs: torch.Tensor) -> torch.Tensor:
        obs = obs.clone()
        obs[..., self.idx.to(obs.device)] = 0.0
        return obs

    def act_deterministic(self, obs: torch.Tensor) -> torch.Tensor:
        return self.agent.act_deterministic(self._mask(obs))

    def forward(self, obs: torch.Tensor, *a, **kw):
        return self.agent(self._mask(obs), *a, **kw)

    def __getattr__(self, name):
        try:
            return super().__getattr__(name)
        except AttributeError:
            return getattr(self.agent, name)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("config")
    p.add_argument("ckpt")
    p.add_argument("--channels", required=True,
                   help="comma-separated BASE-frame channel indices to zero (e.g. 6,7)")
    p.add_argument("--n-envs", type=int, default=2048)
    p.add_argument("--steps", type=int, default=1500)
    p.add_argument("--seed", type=int, default=12345)
    p.add_argument("--no-dr", action="store_true")
    p.add_argument("--device", default="cuda")
    args = p.parse_args()

    channels = [int(c) for c in args.channels.split(",") if c.strip() != ""]
    cfg = load_config(args.config)
    env = build_env(cfg, device=args.device, n_envs=args.n_envs, seed=args.seed,
                    dr_enabled=(False if args.no_dr else None))
    agent = load_agent(args.ckpt, device=args.device)

    # Same env, same seed, same horizon: the ONLY difference between the two rows is the mask.
    intact = evaluate(env, agent, steps=args.steps)
    env = build_env(cfg, device=args.device, n_envs=args.n_envs, seed=args.seed,
                    dr_enabled=(False if args.no_dr else None))
    knocked = evaluate(
        env, ChannelKnockout(agent, channels, env.base_obs_dim, env.obs_stack), steps=args.steps
    )

    out = {
        "probe": "channel_knockout",
        "config": args.config,
        "ckpt": args.ckpt,
        "channels_zeroed": channels,
        "base_obs_dim": env.base_obs_dim,
        "obs_stack": env.obs_stack,
        "dr": not args.no_dr,
        "intact": intact,
        "knocked_out": knocked,
        "delta": {k: knocked[k] - intact[k] for k in intact if k in knocked},
    }
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
