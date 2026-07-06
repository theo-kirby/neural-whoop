"""H2 privileged decoupling reward terms (vz_penalty / thrust_const_penalty), default-off.

Both are ground-truth training-only shaping signals: -k*|vz| gives PPO a direct gradient
against the open-loop altitude sink that no noisy obs channel can provide; -k*(a_t[0]-a_{t-1}[0])^2
decouples the throttle channel from honest-amplitude gyro obs noise. Defaults 0.0 must leave every
existing config's reward bit-identical.
"""

import torch

from neural_whoop.envs.base import MultiAgentDroneEnv
from neural_whoop.envs.registry import make_task
from neural_whoop.randomization import DomainRandomizationConfig
import neural_whoop.tasks  # noqa: F401 - register tasks


def _env(**task_kw):
    cfg = DomainRandomizationConfig(enabled=False)
    env = MultiAgentDroneEnv(make_task("hover_blind", episode_len=50, **task_kw),
                             n_envs=16, device="cpu", seed=0, dr_cfg=cfg)
    env.reset_all()
    return env


def _reward_after_steps(env, actions):
    r = None
    for a in actions:
        _obs, r, _t, _tr, _info = env.step(a)
    return r


def test_defaults_leave_reward_unchanged():
    base, h2 = _env(), _env(vz_penalty=0.0, thrust_const_penalty=0.0)
    acts = [torch.full((16, 4), 0.1) for _ in range(3)]
    assert torch.allclose(_reward_after_steps(base, acts), _reward_after_steps(h2, acts))


def test_vz_penalty_reduces_reward_in_proportion_to_vz():
    base, h2 = _env(), _env(vz_penalty=0.5)
    acts = [torch.zeros(16, 4) for _ in range(3)]  # thrust -1 -> falling: |vz| > 0
    rb = _reward_after_steps(base, acts)
    rh = _reward_after_steps(h2, acts)
    vz = h2.dyn.vel_world[..., 2].abs()
    assert (vz > 0.01).any()
    assert torch.allclose(rb - rh, 0.5 * vz, atol=1e-5)


def test_thrust_const_penalty_charges_only_thrust_channel_changes():
    h2 = _env(thrust_const_penalty=0.1)
    base = _env()
    # Step 1 establishes prev_action; step 2 changes ONLY the rate channels -> no extra penalty.
    a1 = torch.zeros(16, 4)
    a2 = torch.zeros(16, 4); a2[:, 1:] = 0.3
    rb = _reward_after_steps(base, [a1, a2])
    rh = _reward_after_steps(h2, [a1, a2])
    assert torch.allclose(rb, rh, atol=1e-6)
    # Now change the thrust channel by 0.4 -> penalty 0.1 * 0.4^2 on top of the base reward.
    h2b, baseb = _env(thrust_const_penalty=0.1), _env()
    a3 = torch.zeros(16, 4); a3[:, 0] = 0.4
    rb2 = _reward_after_steps(baseb, [a1, a3])
    rh2 = _reward_after_steps(h2b, [a1, a3])
    assert torch.allclose(rb2 - rh2, torch.full((16,), 0.1 * 0.4**2), atol=1e-5)
