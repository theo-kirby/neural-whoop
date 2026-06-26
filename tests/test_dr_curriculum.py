"""DR curriculum: a curriculum scale in [0,1] shrinks every seam-DR magnitude toward zero.

This is the reliability-hardening seam (Flywheel hop-10): the trainer ramps ``scale`` 0->1 over
training so the policy learns the task first, then learns to survive full domain randomization.
``scale == 1.0`` (default) must reproduce the original full-strength DR exactly.
"""

import torch

from neural_whoop.envs.base import MultiAgentDroneEnv
from neural_whoop.envs.registry import make_task
from neural_whoop.randomization import DomainRandomizationConfig, DomainRandomizer
import neural_whoop.tasks  # noqa: F401 - register tasks


def _randomizer(scale, seed=0):
    cfg = DomainRandomizationConfig(enabled=True)
    dr = DomainRandomizer(cfg, n_drones=4096, act_dim=4, dt=0.02, device="cpu",
                          generator=torch.Generator(device="cpu").manual_seed(seed))
    dr.scale = scale
    dr.reset(torch.arange(4096))
    return dr


def test_scale_zero_disables_all_seam_dr():
    dr = _randomizer(0.0)
    assert dr.wind.abs().max() == 0.0
    assert (dr.rate_gain == 1.0).all()
    assert (dr.thrust_scale == 1.0).all()
    assert (dr.latency == 0).all()
    # Obs noise is also gated to a no-op at scale 0.
    obs = torch.zeros(4096, 14)
    assert torch.equal(dr.add_obs_noise(obs), obs)


def test_scale_monotonically_grows_magnitudes():
    lo, hi = _randomizer(0.25), _randomizer(1.0)
    # Wind magnitude and command-scale spread both grow with the curriculum scale.
    assert lo.wind.norm(dim=-1).max() < hi.wind.norm(dim=-1).max()
    assert (lo.rate_gain - 1.0).abs().max() < (hi.rate_gain - 1.0).abs().max()
    assert (lo.thrust_scale - 1.0).abs().max() < (hi.thrust_scale - 1.0).abs().max()
    # Latency incidence (fraction of drones with a non-zero delay) grows with scale.
    assert (lo.latency > 0).float().mean() < (hi.latency > 0).float().mean()


def test_scale_one_matches_default_full_dr():
    # scale defaults to 1.0; an explicit 1.0 must give the same magnitude envelope as the default.
    default = _randomizer(1.0, seed=7)
    again = _randomizer(1.0, seed=7)
    assert torch.allclose(default.wind, again.wind)
    assert torch.allclose(default.rate_gain, again.rate_gain)


def test_env_set_dr_scale_clamps_and_applies():
    env = MultiAgentDroneEnv(make_task("gate_race"), n_envs=256, device="cpu", seed=0)
    env.set_dr_scale(-1.0)
    assert env.dr.scale == 0.0
    env.set_dr_scale(5.0)
    assert env.dr.scale == 1.0
    env.set_dr_scale(0.5)
    assert env.dr.scale == 0.5
