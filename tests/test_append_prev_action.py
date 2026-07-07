"""Action-history obs (append_prev_action): the latency-compensation seam.

The d50var_s8 M2-sensor knockout decomposition isolated action latency as the sole residual
killer (latency-off: 29.8% -> 98.2% survival; bias/rate-gain-off: no change). obs-5 carries no
action echo, so the delay is unobservable — appending the last COMMANDED action to every frame
(known exactly at deploy; the pilot sent it) turns the stacked history into aligned (obs, action)
pairs the policy can use to infer and predict through the delay. The appended channels must be
noise-free, carry the action that produced the frame, and zero at episode start.
"""

import torch

from neural_whoop.envs.base import MultiAgentDroneEnv
from neural_whoop.envs.registry import make_task
from neural_whoop.randomization import DomainRandomizationConfig
import neural_whoop.tasks  # noqa: F401 - register tasks

OBS5 = 5


def _env(stack=1, append=True, dr=None, n=16):
    cfg = dr or DomainRandomizationConfig(enabled=False)
    env = MultiAgentDroneEnv(make_task("hover_blind", episode_len=40), n_envs=n, device="cpu",
                             seed=0, dr_cfg=cfg, obs_stack=stack, append_prev_action=append)
    env.reset_all()
    return env


def test_obs_dim_grows_by_act_dim_per_frame():
    assert _env(stack=1).obs_dim == OBS5 + 4
    assert _env(stack=3).obs_dim == (OBS5 + 4) * 3
    assert _env(stack=3, append=False).obs_dim == OBS5 * 3


def test_frame_carries_the_action_that_produced_it():
    env = _env(stack=2)
    a = torch.full((16, 4), 0.3)
    obs, *_ = env.step(a)
    # newest frame is the LAST base_obs_dim block; its tail 4 channels are the commanded action
    newest = obs[:, -env.base_obs_dim:]
    assert torch.allclose(newest[:, OBS5:], a)
    # after a second step with a different action, the older frame still carries the first
    b = torch.full((16, 4), -0.2)
    obs2, *_ = env.step(b)
    oldest = obs2[:, :env.base_obs_dim]
    assert torch.allclose(oldest[:, OBS5:], a)
    assert torch.allclose(obs2[:, -4:], b)


def test_action_channels_zero_at_episode_start():
    env = _env(stack=3)
    obs = env.reset_all()
    for k in range(3):
        frame = obs[:, k * env.base_obs_dim:(k + 1) * env.base_obs_dim]
        assert torch.equal(frame[:, OBS5:], torch.zeros(16, 4))


def test_action_channels_bypass_obs_noise():
    dr = DomainRandomizationConfig(
        enabled=True, wind_accel_mps2=0.0, rate_gain_frac=0.0, thrust_scale_frac=0.0,
        obs_noise_std=0.0, obs_noise_std_channels=(2.5, 2.5, 2.5, 2.5, 2.5),
        action_latency_steps=0, impulse_prob=0.0,
    )
    env = _env(stack=1, dr=dr)
    a = torch.full((16, 4), 0.5)
    obs, *_ = env.step(a)
    assert torch.allclose(obs[:, OBS5:], a)  # exact despite heavy noise on the state channels


def test_prev_action_still_a_tminus1_for_reward():
    # thrust_const_penalty reads env.prev_action as a_{t-1}: the reassignment must happen AFTER
    # reward_and_done. Two identical steps -> zero constancy penalty difference vs a base env.
    base = MultiAgentDroneEnv(make_task("hover_blind", episode_len=40, thrust_const_penalty=0.1),
                              n_envs=16, device="cpu", seed=0,
                              dr_cfg=DomainRandomizationConfig(enabled=False))
    app = MultiAgentDroneEnv(make_task("hover_blind", episode_len=40, thrust_const_penalty=0.1),
                             n_envs=16, device="cpu", seed=0,
                             dr_cfg=DomainRandomizationConfig(enabled=False),
                             append_prev_action=True)
    base.reset_all(); app.reset_all()
    a1 = torch.zeros(16, 4); a2 = torch.zeros(16, 4); a2[:, 0] = 0.4
    for e in (base, app):
        e.step(a1)
    rb = base.step(a2)[1]
    ra = app.step(a2)[1]
    assert torch.allclose(rb, ra)
