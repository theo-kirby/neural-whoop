"""Eval twins must measure the arm's OWN arena — pinned config-to-config, not by eye.

``scripts/survival_probe.py`` builds its env from a twin config and overrides exactly one key
(``hold_fraction``). Everything else — bounds, setpoint band, spawn distribution, reward lengths,
the ``act:`` throttle floor, the mass band, the in-task sensor model — comes from the twin. So a
twin that has drifted from its training config silently measures a DIFFERENT ARENA than the policy
trained in and reports the difference as a policy result. That failure is invisible: every number
still comes out, and every one of them is about the wrong world.

The desk-hover twins were kept aligned by hand and by comment ("VERBATIM"); this pins it. The
purehold twins are allowed exactly three deviations, which are their whole definition: the setpoint
band collapses onto the deploy altitude and the cohort becomes pure station-keeping.
"""

from __future__ import annotations

import pytest
import yaml

from neural_whoop.experiment import load_config

#: (training arm, its twins). The twins carry no ``ppo:`` block — they are never trained.
FAMILIES = [
    ("desk-hover", ["desk-hover-purehold", "desk-hover-m1live", "desk-hover-m2sensor"]),
    ("desk-flow", ["desk-flow-purehold", "desk-flow-m1live", "desk-flow-m2sensor"]),
    ("desk-flow-noflow", ["desk-flow-noflow-purehold", "desk-flow-noflow-m1live",
                          "desk-flow-noflow-m2sensor"]),
]

#: The purehold twin's licensed deviations: pin the band on the deploy altitude, hold-only cohort.
PUREHOLD_KEYS = {"z_min", "z_max", "hold_fraction"}


def _cfg(name: str) -> dict:
    return load_config(f"configs/{name}.yaml")


@pytest.mark.parametrize("arm,twins", FAMILIES, ids=[f[0] for f in FAMILIES])
def test_twin_task_geometry_matches_its_training_arm(arm, twins):
    base = _cfg(arm)["task"]
    for twin in twins:
        t = _cfg(twin)["task"]
        allowed = PUREHOLD_KEYS if twin.endswith("purehold") else set()
        diff = {k for k in set(base) | set(t) if base.get(k) != t.get(k)} - allowed
        assert not diff, f"{twin} task geometry drifted from {arm}: {sorted(diff)}"
        if twin.endswith("purehold"):
            assert t["z_min"] == t["z_max"], f"{twin} did not pin the band on one altitude"
            assert t["hold_fraction"] == 1.0


@pytest.mark.parametrize("arm,twins", FAMILIES, ids=[f[0] for f in FAMILIES])
def test_twin_act_and_airframe_match_their_training_arm(arm, twins):
    """The throttle floor and the mass band are as load-bearing as the bounds.

    ``act.min_thrust_normed`` changes what ``act[0] = -1`` MEANS, and the mass band changes the
    airframe: a twin that differs on either is grading the policy on a drone it never flew.
    """
    base = _cfg(arm)
    for twin in twins:
        t = _cfg(twin)
        assert t.get("act") == base.get("act"), f"{twin} act: block drifted from {arm}"
        assert t.get("whoop") == base.get("whoop"), f"{twin} whoop: block drifted from {arm}"
        assert "ppo" not in t, f"{twin} carries a ppo: block — twins are never trained"
        assert t["env"]["obs_stack"] == base["env"]["obs_stack"]
        assert t["env"]["seed"] == base["env"]["seed"]


def test_desk_flow_noflow_is_a_one_factor_control():
    """The control arm may differ from Desk-Flow in the flow channels and NOTHING else.

    Gate 6 reads the difference between these two runs as the flow channel's contribution. That
    reading is only valid if the channel is the only difference — so this test is the gate's
    precondition, checked before either arm is trained rather than argued about after.
    """
    flow, noflow = _cfg("desk-flow"), _cfg("desk-flow-noflow")
    ft, nt = flow["task"], noflow["task"]
    assert ft["name"] == "hover_flow" and nt["name"] == "hover_tof"
    flow_only = {k for k in ft if k.startswith("flow_")}
    assert flow_only, "desk-flow.yaml has no flow_* knobs — did the sensor model move?"
    assert not (set(nt) & flow_only), "the control arm carries flow knobs it cannot use"
    diff = {k for k in set(ft) | set(nt) if ft.get(k) != nt.get(k)} - flow_only - {"name"}
    assert not diff, f"desk-flow-noflow differs from desk-flow beyond the flow channels: {sorted(diff)}"

    for section in ("act", "whoop", "ppo", "env"):
        assert flow[section] == noflow[section], f"{section}: differs between the two arms"

    # The DR blocks differ only by the two flow obs-noise/bias entries (8 channels -> 6).
    fd, nd = dict(flow["dr"]), dict(noflow["dr"])
    for key in ("obs_noise_std_channels", "obs_bias_channels"):
        assert len(fd[key]) == 8 and len(nd[key]) == 6, (key, len(fd[key]), len(nd[key]))
        assert fd.pop(key)[:6] == nd.pop(key), f"{key}: the shared six channels differ"
    assert fd == nd, f"dr: differs beyond the flow channels: {sorted(set(fd.items()) ^ set(nd.items()))}"


def test_desk_flow_setpoint_clears_the_optical_floor():
    """0.20 m is not a taste call — it is the number that keeps the PMW3901 seeing.

    The sensor is blind below ``flow_min_m`` (80 mm, a hard optical limit). Desk-Hover's shipped
    policy sinks ~1.8 cm below its setpoint and the UNCALIBRATED ToF offset is another 2.39 cm, so
    the height the sensor actually sees is the setpoint minus ~4.2 cm. At Desk-Hover's 0.10 m that
    lands at 0.058 m — blind, which the knockout probe measured as the worst state of all. At
    0.20 m it lands at 0.158 m, and the 5 cm bar below is what distinguishes this setpoint from
    the 0.15 m first cut (which cleared the floor by only 2.8 cm — sufficient, but with nothing
    left over for the fact that BOTH subtracted terms are themselves unmeasured on this airframe).
    """
    t = _cfg("desk-flow")["task"]
    setpoint = _cfg("desk-flow-purehold")["task"]["z_min"]   # the pinned DEPLOY altitude
    sink_m, tof_offset_m = 0.018, 0.0239
    flown = setpoint - sink_m - tof_offset_m
    assert flown > t["flow_min_m"], (
        f"the deploy setpoint ({setpoint} m) puts the sensor at {flown:.3f} m, below its "
        f"{t['flow_min_m']} m working range")
    assert flown - t["flow_min_m"] > 0.05, (
        "under 5 cm of optical margin leaves nothing for the fact that the sink and the ToF "
        "offset are both unmeasured on THIS airframe")
    # In sim there is no uncalibrated offset (the h_err BIAS DR models it), so what has to clear
    # the floor across the whole TRAINING band is the band bottom plus the sink — 7.2 cm. The
    # policy still MEETS the blind floor in training, via the spawn spread and the blackout model,
    # rather than via a band that grazes it.
    assert t["z_min"] - sink_m > t["flow_min_m"]
    # ...and the band's top plus the measured ~0.37 m climb overshoot stays inside the ToF ceiling.
    assert t["z_max"] + 0.37 < t["tof_max_m"]


def test_desk_flow_models_sustained_flow_loss():
    """Blackouts must be ON in the training arm, and long enough to span the pilot's abort window.

    ``flow_dropout_prob`` is i.i.d. speckle: at 0.02 the chance of losing a whole second is 1e-85,
    so an arm without blackouts meets sustained blindness for the first time in the air — with a
    policy that (staid-moon-7407) demonstrably depends on the channel.
    """
    t = _cfg("desk-flow")["task"]
    assert t["flow_blackout_prob"] > 0.0
    assert t["flow_blackout_s"] >= 1.0, "a blackout cannot reach the pilot's 1 s flow_lost abort"
    for twin in ("desk-flow-purehold", "desk-flow-m1live", "desk-flow-m2sensor"):
        assert _cfg(twin)["task"]["flow_blackout_prob"] == t["flow_blackout_prob"], \
            f"{twin} grades the policy on an easier sensor than it trained against"


def test_the_configs_are_valid_yaml_and_build():
    """Every desk-flow config constructs an env — the typo guard (_filtered) is the point."""
    from neural_whoop.experiment import build_env

    for name in ["desk-flow", "desk-flow-noflow"] + [t for _, ts in FAMILIES for t in ts]:
        cfg = _cfg(name)
        env = build_env(cfg, device="cpu", n_envs=4)
        expect = 8 if cfg["task"]["name"] == "hover_flow" else 6
        assert env.base_obs_dim == expect, (name, env.base_obs_dim)
        assert yaml.safe_load(open(f"configs/{name}.yaml")) is not None
