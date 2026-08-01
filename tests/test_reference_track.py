"""Tests for the reference→RL seam: :mod:`neural_whoop.reference.track` and ``reference_track``.

Split the way the rest of the repo splits: the loader is pure numpy and is tested without the
simulator; the task needs torch and is tested against a real env. The loader tests build a
*synthetic* reference document rather than depending on a generated artifact under ``runs/``, so
they run on a clean checkout.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from neural_whoop.reference.track import (
    STAGECRAFT_PHASES,
    load_reference_track,
)

RATE = 1000.0


def _write_reference(tmp_path, *, labels, phase_plan, rate_hz=RATE, fmt="neural-whoop-reference"):
    """Build a minimal but *valid* reference doc; ``phase_plan`` is [(label_index, n_samples), ...]."""
    phase = np.concatenate([np.full(n, i, dtype=np.int64) for i, n in phase_plan])
    n = len(phase)
    t = np.arange(n) / rate_hz
    # A gentle corkscrew: enough structure that resampling/rotation bugs show up.
    pos = np.stack([np.sin(t), np.cos(t), 0.9 + 0.1 * t], axis=-1)
    vel = np.stack([np.cos(t), -np.sin(t), 0.1 * np.ones_like(t)], axis=-1)
    ang = 0.5 * t
    quat = np.stack([np.sin(ang / 2), np.zeros_like(t), np.zeros_like(t), np.cos(ang / 2)], axis=-1)
    doc = {
        "format": fmt, "version": 2, "maneuver": "synthetic",
        "metrics": {"max_lateral_drift": 0.123},
        "stream": {
            "rate_hz": rate_hz, "n": n, "fields": {}, "phase_labels": list(labels),
            "t": t.tolist(), "phase": phase.tolist(), "pos": pos.tolist(), "vel": vel.tolist(),
            "acc": np.zeros((n, 3)).tolist(), "quat": quat.tolist(),
            "omega": np.stack([0.5 * np.ones_like(t)] + [np.zeros_like(t)] * 2, axis=-1).tolist(),
            "omega_dot": np.zeros((n, 3)).tolist(),
            "normed_thrust": np.ones(n).tolist(), "rate_cmd": np.zeros((n, 3)).tolist(),
        },
    }
    p = tmp_path / "reference.json"
    p.write_text(json.dumps(doc))
    return p


# =================================================================================================
# The loader
# =================================================================================================
def test_the_tracked_window_is_the_maneuver_not_the_stagecraft(tmp_path):
    """CLIMB/HOVER/LAND are dropped; what is left is one contiguous maneuver.

    This is the decision that makes one task serve all three shipped maneuvers without naming any
    of them — the flip's POP..RECOVER, the swing's SWING..SETTLE and the orbit's WIND-UP..SETTLE
    all fall out of the same rule.
    """
    labels = ["CLIMB", "HOVER", "POP", "COAST", "RECOVER", "LAND"]
    p = _write_reference(tmp_path, labels=labels,
                         phase_plan=[(0, 400), (1, 200), (2, 100), (3, 300), (4, 200), (5, 500)])
    tr = load_reference_track(p, dt=0.02)

    kept = {tr.phase_labels[i] for i in np.unique(tr.phase)}
    assert kept == {"POP", "COAST", "RECOVER"}
    assert not (kept & set(STAGECRAFT_PHASES))
    # 600 fine samples at 1 kHz span 0.599 s (599 intervals, not 600) -> 30 control steps at 50 Hz.
    # The off-by-one is worth pinning rather than rounding away: the window is [first, last] fine
    # sample inclusive, so a maneuver's step count is floor(span/dt)+1 and never assumes the span
    # divides evenly.
    assert tr.n_steps == 30
    assert tr.t[0] == pytest.approx(0.0)          # the window's clock is re-zeroed
    assert tr.dt == pytest.approx(0.02)


def test_include_phases_overrides_the_exclude_list(tmp_path):
    labels = ["CLIMB", "SWING", "SETTLE", "LAND"]
    p = _write_reference(tmp_path, labels=labels,
                         phase_plan=[(0, 200), (1, 400), (2, 200), (3, 200)])
    tr = load_reference_track(p, dt=0.02, include_phases=("SWING",))
    assert {tr.phase_labels[i] for i in np.unique(tr.phase)} == {"SWING"}


def test_a_non_contiguous_window_is_refused_rather_than_silently_stitched(tmp_path):
    """A window with a hole would teleport the target mid-episode — the worst kind of silent bug.

    Excluding a phase that sits *between* two tracked ones is a config mistake, not an instruction
    to splice. It has to fail loudly because the resulting reference would still look plausible:
    smooth on either side of a jump the policy can never track.
    """
    labels = ["POP", "HOVER", "RECOVER"]      # HOVER is stagecraft *in the middle*
    p = _write_reference(tmp_path, labels=labels, phase_plan=[(0, 200), (1, 200), (2, 200)])
    with pytest.raises(ValueError, match="not contiguous"):
        load_reference_track(p, dt=0.02)


def test_a_replay_is_refused_because_50hz_aliases_the_maneuver(tmp_path):
    """The video artifact and the data artifact are not interchangeable, and the error says so."""
    p = _write_reference(tmp_path, labels=["POP"], phase_plan=[(0, 100)],
                         fmt="neural-whoop-replay")
    with pytest.raises(ValueError, match="not a hand-authored reference"):
        load_reference_track(p, dt=0.02)


def test_upsampling_is_refused(tmp_path):
    """A reference coarser than the control step would have to be invented, not resampled."""
    p = _write_reference(tmp_path, labels=["POP"], phase_plan=[(0, 100)], rate_hz=25.0)
    with pytest.raises(ValueError, match="refusing to upsample"):
        load_reference_track(p, dt=0.02)


def test_resampling_picks_real_samples_never_interpolated_ones(tmp_path):
    """Every emitted target must be a state the reference actually passed through.

    The reference is 1 kHz *because* 50 Hz aliases these maneuvers — the flip's thrust cut is one
    control step wide. Interpolating a quaternion across a command step invents an attitude the
    trajectory never held, so the loader takes nearest-sample and this pins it.
    """
    p = _write_reference(tmp_path, labels=["POP"], phase_plan=[(0, 1000)])
    tr = load_reference_track(p, dt=0.02)
    fine = json.loads(p.read_text())["stream"]
    fine_pos = np.asarray(fine["pos"])
    for row in tr.pos:
        d = np.linalg.norm(fine_pos - row, axis=-1)
        assert d.min() < 1e-12, "a resampled position is not one of the fine samples"


def test_gravity_body_is_the_observable_attitude_channel(tmp_path):
    """``gravity_body`` must be world-down rotated into the body frame, unit-norm throughout.

    This is what the policy actually gets — a full quaternion would be privileged information the
    real drone has no sensor for — so it is worth pinning that it is derived, not approximated.
    """
    p = _write_reference(tmp_path, labels=["POP"], phase_plan=[(0, 600)])
    tr = load_reference_track(p, dt=0.02)
    g = tr.gravity_body()
    assert g.shape == (tr.n_steps, 3)
    assert np.allclose(np.linalg.norm(g, axis=-1), 1.0, atol=1e-12)
    # The synthetic doc rolls about +x from identity, so world-down stays in the body y-z plane
    # and its x component must be exactly zero.
    assert np.allclose(g[:, 0], 0.0, atol=1e-12)
    assert g[0] == pytest.approx([0.0, 0.0, -1.0], abs=1e-12)


def test_station_is_the_window_start_and_metrics_ride_along(tmp_path):
    p = _write_reference(tmp_path, labels=["CLIMB", "POP"], phase_plan=[(0, 200), (1, 400)])
    tr = load_reference_track(p, dt=0.02)
    assert tr.station == pytest.approx(tr.pos[0])
    assert tr.metrics["max_lateral_drift"] == pytest.approx(0.123)
    assert tr.maneuver == "synthetic"


# =================================================================================================
# The task (needs torch + the simulator)
# =================================================================================================
torch = pytest.importorskip("torch")

from neural_whoop.envs.base import MultiAgentDroneEnv  # noqa: E402
from neural_whoop.envs.registry import make_task  # noqa: E402
from neural_whoop.tasks.reference_track import _quat_geodesic, _quat_mul_xyzw  # noqa: E402


def _env(tmp_path, n_envs=64, **task_kw):
    p = _write_reference(
        tmp_path, labels=["CLIMB", "POP", "COAST", "RECOVER", "LAND"],
        phase_plan=[(0, 400), (1, 200), (2, 400), (3, 200), (4, 400)],
    )
    task = make_task("reference_track", reference=str(p), **task_kw)
    env = MultiAgentDroneEnv(task=task, n_envs=n_envs, device="cpu", seed=0)
    return env, task


def test_the_quaternion_metric_is_sign_agnostic():
    """``q`` and ``−q`` are the same attitude, and the reference stream is continuity-enforced.

    It deliberately does *not* stay in one hemisphere through a 2π flip, so a signed comparison
    would read a perfectly tracked inversion as a full turn of error — the failure would look like
    "the policy cannot flip" rather than "the metric is wrong".
    """
    q = torch.tensor([[0.3, 0.1, -0.2, 0.927]], dtype=torch.float32)
    q = q / q.norm(dim=-1, keepdim=True)
    assert float(_quat_geodesic(q, q)) == pytest.approx(0.0, abs=1e-6)
    assert float(_quat_geodesic(q, -q)) == pytest.approx(0.0, abs=1e-6)
    # A known 90 deg rotation about +x, both ways round.
    a = torch.tensor([[0.0, 0.0, 0.0, 1.0]])
    b = torch.tensor([[math.sin(math.pi / 4), 0.0, 0.0, math.cos(math.pi / 4)]])
    assert float(_quat_geodesic(a, b)) == pytest.approx(math.pi / 2, abs=1e-5)
    assert float(_quat_geodesic(a, -b)) == pytest.approx(math.pi / 2, abs=1e-5)


def test_quat_mul_matches_a_reference_composition():
    """Two 90° rolls compose to a 180° roll — pins the Hamilton convention and the xyzw order."""
    r90 = torch.tensor([[math.sin(math.pi / 4), 0.0, 0.0, math.cos(math.pi / 4)]])
    got = _quat_mul_xyzw(r90, r90)
    assert got[0].tolist() == pytest.approx([1.0, 0.0, 0.0, 0.0], abs=1e-6)


def test_obs_layout_and_width(tmp_path):
    env, task = _env(tmp_path)
    env.reset_all()
    obs = task.observe(env)
    assert obs.shape == (env.n_drones, 13) == (env.n_drones, task.obs_dim)
    assert torch.isfinite(obs).all()
    # Channels 7:10 and 10:13 are the reference's attitude/rate at the current phase — authored,
    # so they must match the table exactly rather than being derived from the drone's own state.
    i = task._ref_idx()
    assert torch.allclose(obs[:, 7:10], task.ref_grav_b[i], atol=1e-6)
    assert torch.allclose(obs[:, 10:13], task.ref_omega[i], atol=1e-6)


def test_rsi_spawns_on_the_reference_at_a_spread_of_phases(tmp_path):
    """RSI is the load-bearing trick, so pin both halves: it is *spread*, and it is *on* the curve.

    Spread — because starting every episode at phase 0 is exactly the exploration barrier this task
    exists to remove (``acro_flip_v2`` reached flip_success_rate 0.000 at 400 M steps under it).
    On the curve — because a "reference" initialization that lands somewhere else teaches the policy
    to recover from states the maneuver never visits.
    """
    env, task = _env(tmp_path, n_envs=512, rsi_frac=1.0, rsi_pos_jitter=0.0, rsi_vel_jitter=0.0,
                     rsi_omega_jitter=0.0, rsi_tilt_jitter=0.0, station_jitter_xy=0.0,
                     station_jitter_z=0.0)
    env.reset_all()
    starts = task.step_idx
    assert starts.max() > starts.min(), "RSI produced no spread of start phases"
    assert starts.max() < task.T_ref, "RSI spawned past the end of the reference"

    # With every jitter zeroed the spawn state must BE the reference state at that phase.
    i = task._ref_idx()
    assert torch.allclose(env.dyn.pos, task.station + task.ref_offset[i], atol=1e-5)
    assert torch.allclose(env.dyn.vel_world, task.ref_vel[i], atol=1e-5)
    assert torch.allclose(env.dyn.ang_vel_body, task.ref_omega[i], atol=1e-5)
    assert float(_quat_geodesic(env.dyn.quat_xyzw, task.ref_quat[i]).max()) < 1e-4


def test_rsi_frac_zero_starts_every_episode_at_the_trigger(tmp_path):
    """The eval twins set this: an honest rollout flies the whole maneuver from phase 0."""
    env, task = _env(tmp_path, n_envs=128, rsi_frac=0.0)
    env.reset_all()
    assert int(task.step_idx.max()) == 0


def test_spawning_inverted_needs_the_quaternion_path_not_euler(tmp_path):
    """A flip passes through inversion, where the ZYX euler triple is degenerate.

    ``env.spawn`` grew a ``quat=`` argument for exactly this: ``quaternion_to_euler`` clamps pitch
    to ±90°, so a roll past vertical cannot be round-tripped through roll/pitch/yaw. If RSI were
    euler-based, half the states a flip visits would spawn as something else — silently.
    """
    n = 4
    env, task = _env(tmp_path, n_envs=n)
    idx = torch.arange(n)
    upside_down = torch.tensor([[1.0, 0.0, 0.0, 0.0]]).repeat(n, 1)   # 180 deg about +x
    env.spawn(idx, torch.zeros(n, 3), quat=upside_down)
    assert float(_quat_geodesic(env.dyn.quat_xyzw, upside_down).max()) < 1e-5
    # World-down now reads +z in the body frame — the unambiguous signature of being inverted.
    from neural_whoop.contract import world_to_body
    down = torch.tensor([0.0, 0.0, -1.0]).expand(n, 3)
    assert world_to_body(down, env.dyn.R)[:, 2].mean() > 0.99

    with pytest.raises(ValueError, match="not both"):
        env.spawn(idx, torch.zeros(n, 3), quat=upside_down, roll=torch.zeros(n))


def test_reward_is_maximal_exactly_on_the_reference(tmp_path):
    """Sitting on the reference must beat being off it — the one property the whole task rests on.

    Compared against a *displaced* drone rather than an arbitrary one, so the test measures the
    tracking gradient rather than incidentally measuring the crash penalty.
    """
    env, task = _env(tmp_path, n_envs=32, rsi_frac=1.0, rsi_pos_jitter=0.0, rsi_vel_jitter=0.0,
                     rsi_omega_jitter=0.0, rsi_tilt_jitter=0.0)
    env.reset_all()
    act = torch.zeros(env.n_drones, 4)
    env.prev_action = act.clone()
    on_ref, _, _ = task.reward_and_done(env, act)

    env.reset_all()
    i = task._ref_idx()
    env.dyn.set_state(
        torch.arange(env.n_drones),
        task.station + task.ref_offset[i] + torch.tensor([0.3, 0.0, 0.0]),
        task.ref_vel[i], task.ref_quat[i], task.ref_omega[i],
    )
    off_ref, _, _ = task.reward_and_done(env, act)
    assert float(on_ref.mean()) > float(off_ref.mean()), "being on the reference paid no more"


def test_a_hopeless_rollout_terminates_early(tmp_path):
    """Past ``fail_pos_err`` the samples teach nothing, so the slot is reclaimed."""
    env, task = _env(tmp_path, n_envs=16, rsi_frac=0.0, fail_pos_err=0.5)
    env.reset_all()
    i = task._ref_idx()
    env.dyn.set_state(
        torch.arange(env.n_drones),
        task.station + task.ref_offset[i] + torch.tensor([2.0, 0.0, 0.0]),
        task.ref_vel[i], task.ref_quat[i], task.ref_omega[i],
    )
    _, done, _ = task.reward_and_done(env, torch.zeros(env.n_drones, 4))
    assert bool(done.all())


def test_episode_length_covers_the_reference_plus_the_settle(tmp_path):
    env, task = _env(tmp_path, settle_steps=25)
    assert task.episode_len == task.T_ref + 25
    assert task.T_ref > 0


def test_metrics_carry_the_acro_flip_names_so_the_two_approaches_compare(tmp_path):
    """The point of reusing the names: a tracked flip and a reward-shaped flip are one table."""
    env, task = _env(tmp_path, n_envs=32)
    env.reset_all()
    task.reward_and_done(env, torch.zeros(env.n_drones, 4))
    m = task.metrics(env)
    for k in ("max_lateral_drift", "peak_climb", "mean_altitude_loss", "settle_pos_error"):
        assert k in m, f"{k} is one of AcroFlipTask's names and must survive"
    for k in ("pos_rmse_m", "att_rmse_deg", "track_success_rate", "tracked_frac"):
        assert k in m
    assert all(isinstance(v, float) and math.isfinite(v) for v in m.values())


def test_a_missing_reference_path_fails_at_construction(tmp_path):
    with pytest.raises(ValueError, match="needs a `reference:` path"):
        make_task("reference_track")
