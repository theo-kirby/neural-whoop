"""Live interactive Studio: the LiveSession driver + the /ws/live WebSocket endpoint.

CPU, tiny untrained hover policy — checks the stateful live-stepping path and the browser command
seam (wind / push / drop / setpoint move) without a GPU, plus the websocket handshake, single-flight
guard, and frame schema through FastAPI's TestClient.
"""

from __future__ import annotations

import torch

from neural_whoop.envs.base import MultiAgentDroneEnv
from neural_whoop.envs.registry import make_task
import neural_whoop.tasks  # noqa: F401 - register tasks
from neural_whoop.studio import courses as courses_mod
from neural_whoop.studio.live import LiveSession
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


def _hover_session(tmp_path, drone_count=2):
    ckpt = _make_ckpt(tmp_path, "hover")
    return LiveSession.build(
        ckpt, drone_count=drone_count, dr=False, seed=0, device="cpu",
        courses_dir=tmp_path / "courses", runs_dir=tmp_path / "runs",
    )


def test_live_session_steps_and_frame_schema(tmp_path):
    sess = _hover_session(tmp_path, drone_count=3)
    info = sess.info()
    assert info["task"] == "hover" and info["is_hover"] is True and info["drone_count"] == 3
    frame = sess.step()
    assert frame["step"] == 1
    assert len(frame["drones"]) == 3
    d = frame["drones"][0]
    # The per-frame fields mirror the replay schema (the shared extractor).
    for key in ("pos", "quat", "rpy", "vel", "angvel", "action", "action_diffaero"):
        assert key in d
    assert len(d["pos"]) == 3 and len(d["quat"]) == 4 and len(d["action"]) == 4
    # Hover surfaces its setpoint under the reused `target` scene marker.
    assert "scene" in d and len(d["scene"]["target"]) == 3


def test_set_setpoint_moves_hover_target(tmp_path):
    sess = _hover_session(tmp_path, drone_count=2)
    sess.set_setpoint(1, [2.0, -1.0, 1.5])
    assert torch.allclose(sess.env.task.setpoint[1], torch.tensor([2.0, -1.0, 1.5]), atol=1e-5)
    # The moved setpoint shows up in the streamed frame's scene channel for that drone.
    frame = sess.step()
    assert frame["drones"][1]["scene"]["target"] == [2.0, -1.0, 1.5]


def test_push_and_drop_inject_impulses(tmp_path):
    sess = _hover_session(tmp_path, drone_count=2)
    sess.step()
    # A push queues a one-shot linear velocity kick on the targeted drone; the next step applies it.
    sess.push(0, direction=[1.0, 0.0, 0.0])
    assert sess._dv_queue[sess.heroes[0]].norm() > 0
    sess.step()
    assert sess._dv_queue.abs().sum() == 0      # queue drained after the step
    # A drop adds both a downward velocity kick and a body-rate tumble.
    sess.drop(1)
    assert sess._dv_queue[sess.heroes[1]][2] < 0       # downward
    assert sess._dw_queue[sess.heroes[1]].norm() > 0   # tumble


def test_set_wind_is_continuous(tmp_path):
    sess = _hover_session(tmp_path, drone_count=1)
    sess.set_wind([1.5, 0.0, 0.0])
    assert torch.allclose(sess.wind_vec, torch.tensor([1.5, 0.0, 0.0]), atol=1e-5)
    # Wind persists across steps (continuous), unlike the one-shot impulse queues.
    sess.step()
    sess.step()
    assert torch.allclose(sess.wind_vec, torch.tensor([1.5, 0.0, 0.0]), atol=1e-5)


def test_command_dispatch_and_reset(tmp_path):
    sess = _hover_session(tmp_path, drone_count=2)
    sess.command({"type": "wind", "vec": [0.0, 2.0, 0.0]})
    sess.command({"type": "setpoint", "drone": 0, "pos": [1.0, 1.0, 1.0]})
    sess.step()
    assert sess.step_idx == 1
    sess.command({"type": "reset"})
    assert sess.step_idx == 0
    assert sess.wind_vec.norm() == 0            # reset clears disturbances


def test_ws_live_handshake_and_frames(tmp_path):
    from fastapi.testclient import TestClient

    runs_dir = tmp_path / "repo" / "runs"
    _make_ckpt(runs_dir, "hover")               # -> runs/hover/ckpt_final.pt
    courses_dir = tmp_path / "repo" / "assets" / "courses"
    courses_dir.mkdir(parents=True)

    from neural_whoop.studio.server import create_app

    app = create_app(repo_root=tmp_path / "repo", runs_dir=runs_dir,
                     courses_dir=courses_dir, device="cpu")
    client = TestClient(app)

    pol = next(p for p in client.get("/api/policies").json() if p["name"] == "hover")
    assert pol["family"] == "follow" and pol["needs_course"] is False
    with client.websocket_connect("/ws/live") as ws:
        ws.send_json({"policy": pol["path"], "drone_count": 2, "dr": False})
        ready = ws.receive_json()
        assert ready["type"] == "ready"
        assert ready["info"]["task"] == "hover" and ready["info"]["is_hover"] is True
        frame = ws.receive_json()
        assert frame["type"] == "frame"
        assert len(frame["drones"]) == 2
        # A disturbance command is accepted mid-stream and the stream keeps flowing.
        ws.send_json({"type": "push", "drone": 0, "dir": [1.0, 0.0, 0.0]})
        nxt = ws.receive_json()
        assert nxt["type"] == "frame" and nxt["step"] >= frame["step"]
