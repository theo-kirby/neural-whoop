"""Per-episode noise-amplitude randomization (obs_noise_amp_range).

The d50 M1-live diagnostic showed a fixed-amplitude-trained policy's thrust trim is a steep
function of the input-noise sd (81%/43%/0.3% survival at 0.8x/1.0x/1.2x the trained amplitude).
obs_noise_amp_range draws a per-drone scalar factor uniform(lo, hi) at reset that multiplies the
per-channel obs noise (white or AR) for the whole episode — forcing PPO to learn an
amplitude-invariant/adaptive trim. The factor must NOT scale the DC obs_bias, must resample at
reset, and empty () must reproduce the legacy path exactly.
"""

import pytest
import torch

from neural_whoop.randomization import DomainRandomizationConfig, DomainRandomizer

OBS_DIM = 5
STD = (0.02, 0.02, 1.25, 1.1, 0.75)


def _dr(n=256, **kw):
    cfg = DomainRandomizationConfig(
        enabled=True,
        wind_accel_mps2=0.0,
        rate_gain_frac=0.0,
        thrust_scale_frac=0.0,
        obs_noise_std=0.0,
        obs_noise_std_channels=STD,
        action_latency_steps=0,
        **kw,
    )
    gen = torch.Generator().manual_seed(0)
    return DomainRandomizer(cfg, n_drones=n, act_dim=4, dt=0.02, device="cpu", generator=gen,
                            obs_dim=OBS_DIM)


def _empirical_sds(dr, steps=4000):
    """Per-drone empirical noise sd on channel 2 (sigma 1.25) over `steps` reads."""
    obs = torch.zeros(dr.n, OBS_DIM)
    draws = torch.stack([dr.add_obs_noise(obs)[:, 2] for _ in range(steps)])
    return draws.std(dim=0)


def test_fixed_amp_scales_white_noise_sd():
    for amp in (0.5, 1.5):
        dr = _dr(obs_noise_amp_range=(amp, amp))
        sds = _empirical_sds(dr)
        assert torch.allclose(sds.mean(), torch.tensor(1.25 * amp), rtol=0.05)


def test_amp_spread_gives_per_drone_heterogeneous_sds():
    dr = _dr(obs_noise_amp_range=(0.5, 1.5))
    sds = _empirical_sds(dr)
    # Each drone's sd sits at its own drawn amp; the population spans (well inside) the band.
    assert sds.min() < 1.25 * 0.75 and sds.max() > 1.25 * 1.25
    assert (sds > 1.25 * 0.40).all() and (sds < 1.25 * 1.65).all()
    # And matches the drawn factors drone-by-drone.
    assert torch.allclose(sds, 1.25 * dr._noise_amp[:, 0], rtol=0.15)


def test_amp_resamples_at_reset():
    dr = _dr(obs_noise_amp_range=(0.5, 1.5))
    before = dr._noise_amp.clone()
    dr.reset(torch.arange(dr.n))
    assert not torch.allclose(before, dr._noise_amp)
    assert (dr._noise_amp >= 0.5).all() and (dr._noise_amp <= 1.5).all()


def test_amp_scales_ar_marginal_but_not_acf():
    dr = _dr(n=512, obs_noise_amp_range=(2.0, 2.0), obs_noise_ar_channels=(0.0, 0.0, 0.8, 0.8, 0.8))
    obs = torch.zeros(dr.n, OBS_DIM)
    xs = []
    for _ in range(3000):
        dr.step_noise()
        xs.append(dr.add_obs_noise(obs)[:, 2])
    x = torch.stack(xs)
    assert torch.allclose(x.std(), torch.tensor(1.25 * 2.0), rtol=0.05)
    x0, x1 = x[:-1] - x.mean(), x[1:] - x.mean()
    acf1 = (x0 * x1).mean() / x.var()
    assert abs(acf1.item() - 0.8) < 0.05


def test_amp_does_not_scale_dc_bias():
    # Zero noise stds isolate the bias term: output must be obs + obs_bias EXACTLY, i.e. the
    # amp factor (3x here) must never touch the DC bias.
    cfg = DomainRandomizationConfig(
        enabled=True, wind_accel_mps2=0.0, rate_gain_frac=0.0, thrust_scale_frac=0.0,
        obs_noise_std=0.0, obs_noise_std_channels=(0.0,) * OBS_DIM,
        obs_noise_amp_range=(3.0, 3.0), obs_bias_channels=(0.0, 0.0, 0.05, 0.05, 0.05),
        action_latency_steps=0,
    )
    dr = DomainRandomizer(cfg, n_drones=64, act_dim=4, dt=0.02, device="cpu",
                          generator=torch.Generator().manual_seed(0), obs_dim=OBS_DIM)
    obs = torch.zeros(64, OBS_DIM)
    assert torch.equal(dr.add_obs_noise(obs), obs + dr.obs_bias)
    assert (dr.obs_bias[:, 2].abs() <= 0.05 + 1e-6).all() and (dr.obs_bias[:, 2] != 0).any()


def test_empty_range_is_legacy_identity():
    obs = torch.zeros(8, OBS_DIM)
    a, b = _dr(n=8), _dr(n=8, obs_noise_amp_range=())
    assert torch.allclose(a.add_obs_noise(obs), b.add_obs_noise(obs))
    assert (b._noise_amp == 1.0).all()


@pytest.mark.parametrize(
    "kw, msg",
    [
        (dict(obs_noise_amp_range=(0.5, 1.0, 1.5)), "lo, hi"),
        (dict(obs_noise_amp_range=(1.5, 0.5)), "0 <= lo <= hi"),
        (dict(obs_noise_amp_range=(-0.1, 1.0)), "0 <= lo <= hi"),
    ],
)
def test_validation_errors(kw, msg):
    with pytest.raises(ValueError, match=msg):
        _dr(**kw)


def test_requires_std_channels():
    cfg = DomainRandomizationConfig(enabled=True, obs_noise_amp_range=(0.5, 1.5))
    with pytest.raises(ValueError, match="requires obs_noise_std_channels"):
        DomainRandomizer(cfg, n_drones=8, act_dim=4, dt=0.02, device="cpu")
