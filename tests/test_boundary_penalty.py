"""Reliability-shaping near-miss penalty (Flywheel hop-11).

``boundary_proximity_penalty`` ramps 0 -> weight per axis as a drone enters the last ``margin``
meters before any crash bound. Default-off (weight 0) must be a no-op; normal flight (well inside
the bounds) must be untouched; the danger band must be penalized monotonically toward the bound.
"""

import torch

from neural_whoop.reward import Bounds, boundary_proximity_penalty

BOUNDS = Bounds(xy=6.0, z_min=0.15, z_max=4.0)
MARGIN = 0.4
W = 1.0


def _pen(p):
    return boundary_proximity_penalty(torch.tensor(p), BOUNDS, MARGIN, W)


def test_weight_zero_is_noop():
    p = torch.tensor([[5.95, 0.0, 0.2]])  # right at a bound
    assert torch.equal(boundary_proximity_penalty(p, BOUNDS, MARGIN, 0.0), torch.zeros(1))


def test_normal_flight_untaxed():
    # Operating region: centered, gate heights z in [0.7, 2.3] -> all > margin from every bound.
    open_pos = [[0.0, 0.0, 1.0], [2.0, -1.5, 0.7], [-3.0, 3.0, 2.3]]
    assert torch.allclose(_pen(open_pos), torch.zeros(3))


def test_floor_approach_is_penalized_and_monotone():
    # z_min 0.15, margin 0.4 -> band is z in (0.15, 0.55). Lower z (closer to floor) = more penalty.
    far = _pen([[0.0, 0.0, 0.55]])   # at the edge of the band -> ~0
    mid = _pen([[0.0, 0.0, 0.35]])
    near = _pen([[0.0, 0.0, 0.16]])  # almost at the floor -> ~weight
    assert far.item() < mid.item() < near.item()
    assert far.item() == 0.0
    assert abs(near.item() - W) < 0.05


def test_wall_approach_is_penalized():
    assert _pen([[5.9, 0.0, 1.0]]).item() > 0.0   # near +x wall
    assert _pen([[0.0, -5.9, 1.0]]).item() > 0.0  # near -y wall


def test_penalty_sums_over_axes_at_a_corner():
    # Near both a wall and the floor: penalty should exceed either single-axis case.
    corner = _pen([[5.9, 0.0, 0.2]]).item()
    wall_only = _pen([[5.9, 0.0, 1.0]]).item()
    floor_only = _pen([[0.0, 0.0, 0.2]]).item()
    assert corner > wall_only and corner > floor_only
