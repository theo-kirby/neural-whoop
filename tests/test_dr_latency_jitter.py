"""Jittered-link action latency (action_latency_dist): the honest model of the ESP32 bridge.

The per-episode-CONSTANT latency model (uniform 0..5 held for 30 s) is harsher than the measured
link (obs-age p50 24 ms / p99 112 ms at 50 Hz — mostly-fresh packets with occasional stale ones).
Jitter mode samples each drone's freshest-packet age per STEP and applies the newest received
command monotonically (latest-packet zero-order hold — an applied command is never rolled back).
"""

import pytest
import torch

from neural_whoop.randomization import DomainRandomizationConfig, DomainRandomizer


def _dr(dist, n=8, seed=0, scale=1.0):
    cfg = DomainRandomizationConfig(
        enabled=True, wind_accel_mps2=0.0, rate_gain_frac=0.0, thrust_scale_frac=0.0,
        obs_noise_std=0.0, action_latency_dist=tuple(dist), impulse_prob=0.0,
    )
    gen = torch.Generator().manual_seed(seed)
    dr = DomainRandomizer(cfg, n_drones=n, act_dim=1, dt=0.02, device="cpu", generator=gen)
    dr.scale = scale
    return dr


def _run(dr, steps):
    """Feed action = step index; return (steps, n) applied indices."""
    out = []
    for t in range(steps):
        a = torch.full((dr.n, 1), float(t))
        out.append(dr.delay_action(a).squeeze(-1))
    return torch.stack(out)


def test_all_mass_at_zero_is_identity():
    applied = _run(_dr([1.0]), 10)
    # _max_lat == 0 -> passthrough
    assert torch.equal(applied, torch.arange(10.0).unsqueeze(-1).expand(10, 8))


def test_all_mass_at_age_one_is_constant_one_step_delay():
    applied = _run(_dr([0.0, 1.0]), 10)
    expect = torch.tensor([0.0] + list(range(0, 9)))  # t=0 clamps to 0 (floor), then t-1
    assert torch.equal(applied, expect.unsqueeze(-1).expand(10, 8))


def test_applied_index_is_monotonic_per_drone():
    applied = _run(_dr([0.5, 0.2, 0.15, 0.1, 0.05]), 300)
    assert (applied[1:] >= applied[:-1]).all()


def test_effective_age_bounded_by_support_and_mostly_fresh():
    dist = [0.5, 0.3, 0.1, 0.06, 0.04]
    applied = _run(_dr(dist, n=512), 400)
    t = torch.arange(400.0).unsqueeze(-1)
    age = t - applied
    assert (age >= 0).all() and (age <= len(dist) - 1).all()
    # Monotonic clamp makes effective ages <= sampled: P(age == 0) >= dist[0].
    assert (age[50:] == 0).float().mean() >= 0.5 - 0.05


def test_reset_clears_backlog():
    dr = _dr([0.0, 0.0, 1.0], n=4)  # always 2 steps stale
    _run(dr, 5)
    dr.reset(torch.arange(4))
    a = torch.full((4, 1), 99.0)
    # First post-reset step applies the fresh command (floor = now), not a pre-reset one.
    assert torch.equal(dr.delay_action(a), a)


def test_curriculum_scale_zero_means_fresh():
    dr = _dr([0.0, 0.0, 0.0, 1.0], scale=0.0)  # sampled age 3, but incidence ramp gates it to 0
    applied = _run(dr, 10)
    assert torch.equal(applied, torch.arange(10.0).unsqueeze(-1).expand(10, 8))


def test_validation_rejects_bad_weights():
    with pytest.raises(ValueError, match="non-negative"):
        _dr([0.5, -0.1])
    with pytest.raises(ValueError, match="sum > 0"):
        _dr([0.0, 0.0])
