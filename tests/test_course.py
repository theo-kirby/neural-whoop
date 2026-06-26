"""Course geometry: batched procedural generation + segment-sphere gate passing."""

import torch

from neural_whoop.course import ArenaSpec, gate_passed, random_courses


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
