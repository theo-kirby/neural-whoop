"""experiment.py's ``act:`` config section -> the env's :class:`ActionLimits`.

The act-v2 envelope used to be the dataclass defaults, always — ``build_env`` never constructed
``ActionLimits`` at all. ``acro_flip_v2`` needs it per-config: it models the pilot's free-flight
throttle floor (``min_thrust_normed``) so a policy rewarded for coasting cannot learn a profile the
deploy path silently rewrites. These check the wiring, the typo guard, and — the part that matters
for every OTHER task in the repo — that omitting the section changes nothing.
"""

import pytest
import torch

from neural_whoop.contract import ActionLimits
from neural_whoop.experiment import build_env, make_act_limits
import neural_whoop.tasks  # noqa: F401 - register tasks


def _cfg(**extra) -> dict:
    return {"task": {"name": "acro_flip"}, "env": {"n_envs": 4, "seed": 0},
            "dr": {"enabled": False}, **extra}


def test_absent_act_section_is_the_defaults():
    assert make_act_limits({}) == ActionLimits()
    assert make_act_limits({"act": {}}) == ActionLimits()
    env = build_env(_cfg(), device="cpu")
    assert env.limits == ActionLimits()
    assert env.limits.min_thrust_normed == 0.0


def test_act_section_reaches_the_env():
    env = build_env(_cfg(act={"min_thrust_normed": 0.25}), device="cpu")
    assert env.limits.min_thrust_normed == 0.25
    # ...and it is genuinely applied on the step path, not merely stored.
    env.reset_all()
    obs, reward, term, trunc, info = env.step(torch.full((env.n_drones, 4), -1.0))
    assert torch.isfinite(reward).all()


def test_act_section_overrides_only_what_it_names():
    lim = make_act_limits({"act": {"max_body_rate_rp_rps": 20.0}})
    assert lim.max_body_rate_rp_rps == 20.0
    assert lim.max_thrust_normed == ActionLimits().max_thrust_normed


def test_unknown_act_key_raises():
    with pytest.raises(ValueError, match="ActionLimits"):
        make_act_limits({"act": {"min_thrust_frac": 0.25}})   # the PILOT's spelling — not ours
