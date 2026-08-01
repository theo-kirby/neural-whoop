"""The reference-vs-policy overlay: pin the choices that make the comparison honest.

Each of these encodes a way the overlay could look fine and lie. They are cheap and pure — a
synthetic reference plus a synthetic policy replay, no simulator, no renderer, no GPU.
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import reference_vs_policy as rvp  # noqa: E402

from neural_whoop.viz.replay import REPLAY_FORMAT, REPLAY_VERSION, RunRecorder, load_run  # noqa: E402


DT = 0.02
RATE = 1000                       # the reference stream's own rate (Hz), as shipped
N_REF = 40                        # control steps after resampling to DT
_N_FINE = (N_REF - 1) * int(RATE * DT) + 1


def _write_reference(tmp_path: Path) -> Path:
    """A minimal but *valid* reference.json: a straight climb, two phases, no stagecraft."""
    t = np.arange(_N_FINE) / RATE
    half = _N_FINE // 2
    doc = {
        "format": "neural-whoop-reference", "version": 2, "maneuver": "synthetic",
        "metrics": {},
        "stream": {
            "rate_hz": RATE, "n": _N_FINE, "fields": {}, "phase_labels": ["POP", "COAST"],
            "t": t.tolist(),
            "phase": ([0] * half + [1] * (_N_FINE - half)),
            "pos": np.stack([np.zeros(_N_FINE), np.zeros(_N_FINE), 1.0 + 0.5 * t], -1).tolist(),
            "vel": np.stack([np.zeros(_N_FINE), np.zeros(_N_FINE),
                             np.full(_N_FINE, 0.5)], -1).tolist(),
            "acc": np.zeros((_N_FINE, 3)).tolist(),
            "quat": np.tile([0.0, 0.0, 0.0, 1.0], (_N_FINE, 1)).tolist(),
            "omega": np.zeros((_N_FINE, 3)).tolist(),
            "omega_dot": np.zeros((_N_FINE, 3)).tolist(),
            "normed_thrust": np.full(_N_FINE, 1.5).tolist(),
            "rate_cmd": np.zeros((_N_FINE, 3)).tolist(),
        },
    }
    p = tmp_path / "reference.json"
    p.write_text(json.dumps(doc))
    return p


def _write_policy(tmp_path: Path, n_steps: int, *, ended: str = "crash",
                  drop: float = 0.0) -> Path:
    """A policy replay of ``n_steps`` frames, offset ``drop`` metres below the reference."""
    meta = {
        "task": "reference_track", "obs_version": "obs-v4", "action_version": "act-v2",
        "substrate": "diffaero", "control_hz": int(round(1 / DT)), "sim_hz": 200, "dt": DT,
        "action_limits": {"max_thrust_normed": 4.0, "hover_thrust_normed": 1.0,
                          "max_body_rate_rp_rps": 12.0, "max_body_rate_yaw_rps": 6.0},
    }
    rec = RunRecorder(meta)
    rec.begin_episode(index=1, drone=0, gates=[])
    for i in range(n_steps):
        z = 1.0 + 0.5 * i * DT - drop
        rec.add_frame(
            t=i * DT, step=i + 1, pos=[0.0, 0.0, z], quat=[0.0, 0.0, 0.0, 1.0],
            rpy=[0.0, 0.0, 0.0], vel=[0.0, 0.0, 0.5], angvel=[0.0, 0.0, 0.0],
            action=[0.0, 0.0, 0.0, 0.0], action_diffaero=[1.2, 0.0, 0.0, 0.0],
            reward=0.0, cum_reward=0.0, gate_idx=0, dist_to_gate=0.0, laps=0,
            # A real reference_track replay publishes the reference pose here; the overlay has to
            # strip it, so give the fixture one to strip.
            scene={"target": [0.0, 0.0, 1.0 + 0.5 * i * DT], "anchor": [0.0, 0.0, 1.0]},
        )
    rec.end_episode({"steps": n_steps, "ended": ended, "total_reward": 0.0})
    p = tmp_path / "policy.json.gz"
    rec.save(p)
    return p


@pytest.fixture
def refs(tmp_path):
    return _write_reference(tmp_path)


def test_the_reference_is_drone_zero_so_the_camera_flies_the_ideal_trajectory(tmp_path, refs):
    """``playback.js::heroTrackIndex`` falls back to track 0, and track 0 must be the reference.

    Point the camera at the policy instead and a policy that falls out of the sky is re-centred by
    its own camera — the clip then shows a composed flight and hides the result.
    """
    pol = _write_policy(tmp_path, 15)
    doc, _ = rvp.build_overlay(pol, refs, exclude_phases=())
    drones = doc["episodes"][0]["drones"]
    assert len(drones) == 2
    assert drones[0]["summary"]["ended"] == "reference"
    assert drones[0]["style"]["ghost"], "the reference must be the ghost, not the solid airframe"
    assert "style" not in drones[1], "the policy is the solid subject"


def test_neither_track_carries_a_scene_channel(tmp_path, refs):
    """`scene` must be stripped from BOTH tracks, for two independent reasons.

    It decides the hero (a policy with a `scene.target` would out-score the reference and steal the
    camera), and the follow-task target marker is a metre-scale sphere drawn at the camera's own
    subject, which fills the entire frame.
    """
    pol = _write_policy(tmp_path, 15)
    doc, _ = rvp.build_overlay(pol, refs, exclude_phases=())
    for d in doc["episodes"][0]["drones"]:
        assert all("scene" not in f for f in d["frames"])


def test_a_policy_that_dies_early_is_not_padded(tmp_path, refs):
    """The gap where the policy stopped is the result — filling it in would erase the finding."""
    pol = _write_policy(tmp_path, 15, ended="crash")
    doc, cmp_ = rvp.build_overlay(pol, refs, exclude_phases=())
    ref_track, pol_track = doc["episodes"][0]["drones"]
    assert len(ref_track["frames"]) == N_REF
    assert len(pol_track["frames"]) == 15
    assert cmp_["completed_fraction"] == pytest.approx(15 / N_REF)
    assert cmp_["policy_ended"] == "crash"


def test_a_surviving_policy_is_trimmed_to_the_maneuver_and_never_exceeds_100_percent(tmp_path, refs):
    """A policy that survives runs on to the episode cap; those steps are hold-final-state tail.

    Both halves matter. Leaving the tail in pads the clip AND — the reason it is a correctness bug
    rather than an aesthetic one — averaging a per-step metric over it makes a surviving policy
    beat a crashed one because most of its samples are the trivial part. This is the same class of
    error as the ``ep_``-prefixed accumulators in ``tasks/reference_track.py``.
    """
    pol = _write_policy(tmp_path, N_REF * 4, ended="max_steps")
    doc, cmp_ = rvp.build_overlay(pol, refs, exclude_phases=())
    _, pol_track = doc["episodes"][0]["drones"]
    assert len(pol_track["frames"]) == N_REF, "the policy track must stop at the reference window"
    assert cmp_["completed_fraction"] == 1.0
    assert cmp_["compared_steps"] == N_REF


def test_the_error_numbers_are_measured_over_the_steps_the_policy_actually_flew(tmp_path, refs):
    """A policy dying at step 5 must not average its error over 40 steps it was never alive for."""
    pol = _write_policy(tmp_path, 5, drop=0.4)
    _, cmp_ = rvp.build_overlay(pol, refs, exclude_phases=())
    assert cmp_["compared_steps"] == 5
    assert cmp_["pos_err_m_mean"] == pytest.approx(0.4, abs=1e-6)


def test_phases_never_reached_names_where_the_policy_stopped(tmp_path, refs):
    """The headline finding on the v1 flip was "it never reaches CATCH" — keep that reportable."""
    pol = _write_policy(tmp_path, N_REF // 2 - 1)     # dies inside phase 0
    _, cmp_ = rvp.build_overlay(pol, refs, exclude_phases=())
    assert cmp_["phases_reached"] == ["POP"]
    assert cmp_["phases_never_reached"] == ["COAST"]


def test_derived_framing_actually_keeps_both_drones_inside_the_frame(tmp_path):
    """The framing is derived from the measured separation, not tuned per clip — so check it works.

    ``--preset hero`` frames ONE subject at 22 % of frame height (~0.37 m of world). An overlay
    whose drones separate by a metre needs ~6x that, and the failure is silent: the clip renders,
    and the drone the comparison exists to show is simply not in it.
    """
    for sep in (0.1, 0.5, 0.925, 2.0):
        for glyph in (1.0, rvp.GLYPH_SCALE):
            frac = rvp.derive_drone_frac(sep, glyph_scale=glyph)
            frame_height = rvp.AIRFRAME_M * glyph / frac
            # Where the far drone lands in NDC, given the follow rig's resting subject height.
            ndc = abs(rvp.HERO_SUBJECT_Y) + sep / (frame_height / 2)
            assert ndc < 1.0, f"sep={sep} glyph={glyph}: worst |NDC| {ndc:.2f} leaves frame"


def test_a_bigger_divergence_buys_a_wider_frame(tmp_path):
    """Monotonic by construction: the worse the policy, the more room the shot needs."""
    fracs = [rvp.derive_drone_frac(s) for s in (0.2, 0.5, 1.0, 2.0)]
    assert fracs == sorted(fracs, reverse=True)


def test_the_overlay_is_an_ordinary_replay_the_existing_renderer_can_read(tmp_path, refs):
    """No new format: the Studio, capture_video and load_run all take it as-is."""
    pol = _write_policy(tmp_path, 15)
    doc, _ = rvp.build_overlay(pol, refs, exclude_phases=())
    out = tmp_path / "overlay.json.gz"
    with gzip.open(out, "wt", encoding="utf-8") as fh:
        json.dump(doc, fh)
    back = load_run(out)
    assert back["format"] == REPLAY_FORMAT
    assert back["version"] == REPLAY_VERSION
    ep = back["episodes"][0]
    # v1-reader compatibility: the episode-level mirror is the lead track.
    assert ep["frames"] == ep["drones"][0]["frames"]


def test_style_is_passed_through_add_group_episode_verbatim(tmp_path):
    """`drones[].style` is an additive render hint — the recorder must not drop it."""
    rec = RunRecorder({"task": "t", "dt": DT})
    frame = dict(t=0.0, step=1, pos=[0, 0, 1], quat=[0, 0, 0, 1], rpy=[0, 0, 0],
                 vel=[0, 0, 0], angvel=[0, 0, 0], action=[0] * 4, action_diffaero=[1, 0, 0, 0],
                 reward=0.0, cum_reward=0.0, gate_idx=0, dist_to_gate=0.0, laps=0)
    rec.add_group_episode(index=1, gates=[], tracks=[
        {"drone": 0, "summary": {}, "frames": [frame], "style": {"ghost": {"opacity": 0.3}}},
        {"drone": 1, "summary": {}, "frames": [frame]},
    ])
    drones = rec.to_dict()["episodes"][0]["drones"]
    assert drones[0]["style"] == {"ghost": {"opacity": 0.3}}
    assert "style" not in drones[1], "absent style must stay absent, not become null"
