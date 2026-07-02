"""Uplink obs staleness (the onboard-hybrid split) — pure DomainRandomizer semantics.

The uplink channels must be delayed per-drone and zero-order-held between sender periods,
never read across an episode reset, and leave the local (non-uplink) channels untouched.
"""

import torch

from neural_whoop.randomization import DomainRandomizationConfig, DomainRandomizer


def _dr(n=3, lat=2, interval=1, slices=(slice(0, 2),), obs_dim=4, **kw):
    cfg = DomainRandomizationConfig(
        enabled=True,
        wind_accel_mps2=0.0,
        rate_gain_frac=0.0,
        thrust_scale_frac=0.0,
        obs_noise_std=0.0,
        action_latency_steps=0,
        uplink_latency_steps=lat,
        uplink_interval_steps=interval,
        **kw,
    )
    dr = DomainRandomizer(cfg, n, act_dim=4, dt=0.02, device="cpu", uplink_slices=slices)
    return dr, obs_dim


def _obs(step: float, n: int, obs_dim: int) -> torch.Tensor:
    """Observation whose every entry encodes the step it was computed at."""
    return torch.full((n, obs_dim), float(step))


def test_uplink_delay_and_local_freshness():
    dr, obs_dim = _dr(n=3, lat=2, interval=1)
    dr.uplink_lat[:] = torch.tensor([0, 1, 2])
    dr._ufloor[:] = 0
    for t in range(6):
        out = dr.delay_uplink(_obs(t, 3, obs_dim))
        # Local channels always fresh.
        assert (out[:, 2:] == float(t)).all()
        # Uplink channels stale by each drone's latency (clamped to the first packet).
        expect = [max(t - 0, 0), max(t - 1, 0), max(t - 2, 0)]
        assert out[:, 0].tolist() == [float(e) for e in expect]


def test_uplink_zero_order_hold():
    dr, obs_dim = _dr(n=1, lat=0, interval=3)
    dr.uplink_lat[:] = 0
    dr._ufloor[:] = 0
    seen = [dr.delay_uplink(_obs(t, 1, obs_dim))[0, 0].item() for t in range(7)]
    # Sender computes at steps 0, 3, 6; the value holds in between.
    assert seen == [0.0, 0.0, 0.0, 3.0, 3.0, 3.0, 6.0]


def test_uplink_never_reads_across_reset():
    dr, obs_dim = _dr(n=2, lat=2, interval=1)
    dr.uplink_lat[:] = 2
    dr._ufloor[:] = 0
    for t in range(4):
        dr.delay_uplink(_obs(t, 2, obs_dim))
    # Reset drone 0 only: its floor moves to the current step; drone 1 keeps its history.
    dr.reset(torch.tensor([0]))
    dr.uplink_lat[:] = 2  # re-pin after reset resampled it
    out = dr.delay_uplink(_obs(4, 2, obs_dim))
    assert out[0, 0].item() == 4.0  # holds its first post-reset value, no stale pre-reset read
    assert out[1, 0].item() == 2.0  # unreset drone still lagging by 2


def test_uplink_noop_when_unconfigured():
    cfg = DomainRandomizationConfig(enabled=True, uplink_latency_steps=0, uplink_interval_steps=1)
    dr = DomainRandomizer(cfg, 2, act_dim=4, dt=0.02, device="cpu", uplink_slices=(slice(0, 3),))
    obs = torch.randn(2, 5)
    assert torch.equal(dr.delay_uplink(obs), obs)
