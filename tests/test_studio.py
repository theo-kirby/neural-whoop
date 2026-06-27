"""Studio backend: fixed-course rollout (gate_race + swarm), spread-knob spacing, and the API.

CPU, tiny batches, tiny untrained policies — checks the sim-core wiring and the FastAPI routes
without a GPU or a trained checkpoint. The rollout assertions verify the key contract: the flown
drones share ONE course (identical gate hashes) and each produces frames, recorded as a v2 group
episode the viewer renders.
"""

from __future__ import annotations

import torch

from neural_whoop import course as course_mod
from neural_whoop.envs.base import MultiAgentDroneEnv
from neural_whoop.envs.registry import make_task
import neural_whoop.tasks  # noqa: F401 - register tasks
from neural_whoop.studio import courses as courses_mod
from neural_whoop.studio.rollout import studio_rollout
from neural_whoop.training.ppo import ActorCritic, PPOConfig, save_checkpoint


def _make_ckpt(tmp_path, task_name, **task_kw):
    """Build a tiny untrained policy for ``task_name`` and save a real checkpoint; return its path."""
    task = make_task(task_name, **task_kw)
    env = MultiAgentDroneEnv(task, n_envs=2, device="cpu", seed=0)
    cfg = PPOConfig(hidden_sizes=(16, 16))
    agent = ActorCritic(env.obs_dim, env.act_dim, cfg)
    path = tmp_path / f"{task_name}" / "ckpt_final.pt"
    path.parent.mkdir(parents=True, exist_ok=True)
    save_checkpoint(agent, cfg, env, str(path), step=0)
    return path


def _gate_hash(gates):
    """Stable hash of an episode's gate layout (to assert shared courses)."""
    rows = [(round(g["radius"], 4), *[round(x, 4) for x in g["pos"]]) for g in gates]
    return tuple(rows)


def test_spread_preset_widens_gate_spacing():
    # The spread preset must yield inter-gate distances well above the tight default (~1.5–2.8 m).
    gen = torch.Generator(device="cpu").manual_seed(0)
    pos, _ = course_mod.random_courses(8, 6, course_mod.ARENA_PRESETS["spread"], generator=gen)
    hops = (pos[:, 1:] - pos[:, :-1]).norm(dim=-1)
    assert hops.min().item() > 3.0
    # ...and meaningfully larger than the tight preset on the same seed.
    gen2 = torch.Generator(device="cpu").manual_seed(0)
    tight, _ = course_mod.random_courses(8, 6, course_mod.ARENA_PRESETS["tight"], generator=gen2)
    tight_hops = (tight[:, 1:] - tight[:, :-1]).norm(dim=-1)
    assert hops.mean().item() > tight_hops.mean().item() + 1.5


def test_gate_race_rollout_shares_one_course(tmp_path):
    ckpt = _make_ckpt(tmp_path, "gate_race", n_gates=5)
    _, summary = studio_rollout(
        ckpt, "preset:spread", drone_count=3, dr=False, max_steps=40, seed=0,
        n_gates=6, device="cpu", courses_dir=tmp_path / "courses", runs_dir=tmp_path / "runs",
    )
    assert summary["task"] == "gate_race"
    assert summary["drone_count"] == 3

    from neural_whoop.viz.replay import load_run

    doc = load_run((tmp_path / "runs" / summary["run_path"]))
    assert doc["version"] == 2
    ep = doc["episodes"][0]
    assert len(ep["drones"]) == 3                       # one group episode, 3 drones
    hashes = {_gate_hash(ep["gates"])}                  # the shared course
    for d in ep["drones"]:
        assert len(d["frames"]) > 0
    # Every drone flew the SAME course (gates are episode-level + shared) -> one hash.
    assert len(hashes) == 1


def test_swarm_rollout_shares_one_course(tmp_path):
    ckpt = _make_ckpt(tmp_path, "swarm_race", n_agents=3, n_gates=5)
    _, summary = studio_rollout(
        ckpt, "preset:big", drone_count=3, dr=False, max_steps=40, seed=0,
        n_gates=6, device="cpu", courses_dir=tmp_path / "courses", runs_dir=tmp_path / "runs",
    )
    assert summary["task"] == "swarm_race"

    from neural_whoop.viz.replay import load_run

    doc = load_run((tmp_path / "runs" / summary["run_path"]))
    ep = doc["episodes"][0]
    assert len(ep["drones"]) == 3
    for d in ep["drones"]:
        assert len(d["frames"]) > 0


def test_scale_curriculum_grows_course_range():
    # With a curriculum, early training (progress~0) draws only tight courses; late training
    # (progress >= scale_curriculum_frac) opens the full tight->big range.
    task = make_task("gate_race", scale_randomize=True, scale_curriculum_frac=0.5,
                     n_gates=5, bound_xy=14.0, bound_z_max=5.0)
    env = MultiAgentDroneEnv(task, n_envs=512, device="cpu", seed=0)
    env.set_course_scale(0.0)
    env.reset_all()
    early = task.gate_pos[..., :2].norm(dim=-1).max().item()
    env.set_course_scale(1.0)
    env.reset_all()
    late = task.gate_pos[..., :2].norm(dim=-1).max().item()
    assert early < 6.0          # tight-only early (radius ~4.5)
    assert late > early + 3.0   # range widened toward big (radius up to ~12)


def test_seeded_course_roundtrip(tmp_path):
    # A course saved to YAML loads back to tensors the env can fly.
    course = {"name": "t", "gates": [
        {"pos": [1.0, 0.0, 1.0], "radius": 0.45},
        {"pos": [3.0, 1.0, 1.5], "radius": 0.45},
    ]}
    cdir = tmp_path / "courses"
    cdir.mkdir()
    (cdir / "t.yaml").write_text(courses_mod.course_to_yaml(course))
    pos, rad, label = courses_mod.resolve_course("t", cdir, device="cpu")
    assert pos.shape == (2, 3) and rad.shape == (2,)
    assert label == "t"


def test_api_lists_policies_and_courses(tmp_path):
    from fastapi.testclient import TestClient

    # Seed a fake policy + a course under a tmp repo layout.
    runs_dir = tmp_path / "repo" / "runs"
    _make_ckpt(runs_dir, "gate_race", n_gates=5)        # -> runs/gate_race/ckpt_final.pt
    courses_dir = tmp_path / "repo" / "assets" / "courses"
    courses_dir.mkdir(parents=True)
    (courses_dir / "spread-a.yaml").write_text(courses_mod.course_to_yaml(
        {"name": "spread-a", "gates": [{"pos": [1, 0, 1], "radius": 0.45}]}))

    from neural_whoop.studio.server import create_app

    app = create_app(repo_root=tmp_path / "repo", runs_dir=runs_dir,
                     courses_dir=courses_dir, device="cpu")
    client = TestClient(app)

    pols = client.get("/api/policies").json()
    assert any(p["name"] == "gate_race" for p in pols)
    assert all("task" in p for p in pols)

    courses = client.get("/api/courses").json()
    assert any(c["name"] == "spread-a" for c in courses["courses"])
    assert any(c["kind"] == "preset" for c in courses["presets"])
