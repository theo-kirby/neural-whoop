"""Course geometry: batched procedural generation + segment-sphere gate passing."""

import torch

from neural_whoop.course import ArenaSpec, gate_passed, random_courses, random_courses_batched


def test_random_courses_shapes_and_bounds():
    arena = ArenaSpec(radius=4.0, z_min=0.7, z_max=2.0)
    pos, rad = random_courses(64, 5, arena, device="cpu", generator=torch.Generator().manual_seed(0))
    assert pos.shape == (64, 5, 3) and rad.shape == (64, 5)
    # Horizontal radius inside the arena; heights inside the band.
    assert (pos[..., :2].norm(dim=-1) <= arena.radius + 1e-4).all()
    assert (pos[..., 2] >= arena.z_min - 1e-4).all() and (pos[..., 2] <= arena.z_max + 1e-4).all()


def test_random_courses_reproducible():
    a = random_courses(8, 4, device="cpu", generator=torch.Generator().manual_seed(1))[0]
    b = random_courses(8, 4, device="cpu", generator=torch.Generator().manual_seed(1))[0]
    assert torch.allclose(a, b)


def test_batched_scalar_matches_random_courses():
    # The per-env batched core with all-scalar args is byte-identical to random_courses (same RNG
    # draw order) -> existing seeded courses are unchanged.
    arena = ArenaSpec(radius=4.5)
    a = random_courses(32, 5, arena, device="cpu", generator=torch.Generator().manual_seed(3))[0]
    b = random_courses_batched(
        32, 5, radius=arena.radius, step_min=arena.step_min, step_max=arena.step_max,
        z_min=arena.z_min, z_max=arena.z_max, gate_radius=arena.gate_radius,
        max_turn_deg=arena.max_turn_deg, start_xy=arena.start_xy,
        device="cpu", generator=torch.Generator().manual_seed(3),
    )[0]
    assert torch.equal(a, b)


def test_batched_per_env_scale_varies_spacing():
    # Per-env radius/step tensors -> courses of different scales in one call. Bigger-radius envs get
    # proportionally bigger gate hops, and each stays inside its own radius.
    n = 256
    radius = torch.linspace(4.5, 12.0, n)
    pos, _ = random_courses_batched(
        n, 6, radius=radius, step_min=0.34 * radius, step_max=0.62 * radius,
        z_min=0.7, z_max=3.0, gate_radius=0.45, device="cpu",
        generator=torch.Generator().manual_seed(0),
    )
    # Each env's gates stay within its own radius.
    assert (pos[..., :2].norm(dim=-1) <= radius.unsqueeze(-1) + 1e-3).all()
    # Mean inter-gate hop grows with radius (small-radius envs vs large-radius envs).
    hop = (pos[:, 1:] - pos[:, :-1]).norm(dim=-1).mean(dim=-1)
    assert hop[:32].mean() < hop[-32:].mean() - 1.5


def test_gate_passed_segment_hits():
    center = torch.tensor([[1.0, 0.0, 1.0]])
    rad = torch.tensor([0.3])
    # Segment passing straight through the center -> pass.
    assert gate_passed(center, torch.tensor([[0.0, 0.0, 1.0]]), torch.tensor([[2.0, 0.0, 1.0]]), rad).item()
    # Segment far away -> no pass.
    assert not gate_passed(center, torch.tensor([[0.0, 5.0, 1.0]]), torch.tensor([[2.0, 5.0, 1.0]]), rad).item()


def test_gate_passed_no_tunneling():
    # A fast step that jumps past a small gate still registers (segment, not endpoint, test).
    center = torch.tensor([[1.0, 0.0, 1.0]])
    rad = torch.tensor([0.2])
    prev = torch.tensor([[-3.0, 0.0, 1.0]])
    curr = torch.tensor([[5.0, 0.0, 1.0]])  # both endpoints outside the sphere
    assert gate_passed(center, prev, curr, rad).item()
