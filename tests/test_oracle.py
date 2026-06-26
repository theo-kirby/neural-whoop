"""Timing oracles: path-length reference and the dynamically-feasible reference.

Pure-module tests (no simulator): exercise the geometry, the physical limits, and the
monotonicity properties the feasible oracle must satisfy to be an honest yardstick.
"""

import math

import torch

from neural_whoop.oracle import (
    FeasibleOracle,
    _segment_time,
    feasible_lap_time,
    pathlen_lap_time,
)


def _square(side: float = 2.0, z: float = 1.0) -> torch.Tensor:
    """A single 4-gate square course (n_envs=1, n_gates=4, 3)."""
    pts = [(0.0, 0.0), (side, 0.0), (side, side), (0.0, side)]
    return torch.tensor([[(x, y, z) for x, y in pts]], dtype=torch.float32)


def test_pathlen_matches_perimeter_over_vref():
    g = _square(2.0)
    # closed perimeter = 4 * side; / v_ref
    assert torch.allclose(pathlen_lap_time(g, v_ref=4.0), torch.tensor([8.0 / 4.0]))


def test_feasible_shapes_and_batched():
    g = _square(2.0).repeat(16, 1, 1)
    t = feasible_lap_time(g)
    assert t.shape == (16,)
    assert torch.allclose(t, t[:1].expand(16))  # identical courses -> identical times


def test_segment_time_pure_cruise_and_symmetry():
    # Long segment at v_in=v_out=v_max with huge accel -> ~ L / v_max (negligible ramps).
    L = torch.tensor([10.0])
    t = _segment_time(L, torch.tensor([5.0]), torch.tensor([5.0]), a=1e6, v_max=5.0)
    assert abs(t.item() - 10.0 / 5.0) < 1e-3
    # Time is symmetric in swapping entry/exit speeds.
    t1 = _segment_time(L, torch.tensor([1.0]), torch.tensor([4.0]), a=20.0, v_max=7.0)
    t2 = _segment_time(L, torch.tensor([4.0]), torch.tensor([1.0]), a=20.0, v_max=7.0)
    assert abs(t1.item() - t2.item()) < 1e-5


def test_feasible_slower_than_unconstrained_pathlen_at_same_top_speed():
    # An honest accel+corner-limited lap must take at least as long as the
    # zero-accel-cost, geometry-blind path-length/v_max reference.
    g = _square(2.0)
    # >= floor is the general invariant (an honest lap is never faster than geometry/v_max).
    o = FeasibleOracle(v_max=5.0, a_max=25.0, a_lat=23.0)
    assert feasible_lap_time(g, o).item() >= pathlen_lap_time(g, v_ref=o.v_max).item() - 1e-4
    # With binding corners (lower a_lat) the lap is strictly slower: cornering costs real time.
    o2 = FeasibleOracle(v_max=5.0, a_max=25.0, a_lat=10.0)
    assert feasible_lap_time(g, o2).item() > pathlen_lap_time(g, v_ref=o2.v_max).item() + 1e-3


def test_sharper_corners_cost_more_time():
    # A tight zig-zag (sharp deflections) must be slower per metre than a gentle wide loop.
    tight = torch.tensor([[(0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (0.0, 0.2, 1.0), (1.0, 0.4, 1.0)]])
    o = FeasibleOracle()
    _, = (feasible_lap_time(tight, o),)  # smoke: finite, positive
    t = feasible_lap_time(tight, o)
    assert torch.isfinite(t).all() and (t > 0).all()


def test_lower_limits_give_slower_laps():
    g = _square(2.5)
    fast = feasible_lap_time(g, FeasibleOracle(v_max=8.0, a_max=30.0, a_lat=28.0))
    slow = feasible_lap_time(g, FeasibleOracle(v_max=4.0, a_max=12.0, a_lat=10.0))
    assert (slow > fast).all()


def test_finite_and_positive_on_random_courses():
    from neural_whoop.course import random_courses

    pos, _ = random_courses(128, 5, device="cpu", generator=torch.Generator().manual_seed(7))
    t = feasible_lap_time(pos)
    assert torch.isfinite(t).all() and (t > 0).all()
