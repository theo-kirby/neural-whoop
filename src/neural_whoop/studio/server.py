"""FastAPI app for the neural-whoop Studio — list policies/courses, run a fixed-course rollout,
serve the resulting replay to the static Three.js frontend.

``create_app`` is a factory (tests redirect the runs/courses/web dirs into a ``tmp_path``). Only
``fastapi`` is imported at module scope (the ``studio`` extra); everything that needs torch/sim is
reached through :func:`neural_whoop.studio.rollout.studio_rollout` (function-local imports), so the
module — and the GET listing routes — import without a GPU. A module-level single-flight lock
guards the rollout route (the batched GPU sim is not re-entrant); the route returns HTTP 409 while
one is running and offloads the blocking work off the event loop.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import anyio
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from neural_whoop.studio import courses as courses_mod

#: Repo root (src/neural_whoop/studio/server.py -> repo).
_REPO_ROOT = Path(__file__).resolve().parents[3]

#: Single-flight guard: only one rollout runs at a time (the batched GPU sim isn't re-entrant).
ROLLOUT_LOCK = asyncio.Lock()


class RolloutRequest(BaseModel):
    """Request to fly a saved policy over a chosen course with a chosen drone count."""

    policy: str                                   # repo-relative ckpt path under runs/
    course: str                                   # "preset:<name>" or a seeded YAML stem
    drone_count: int = Field(default=3, ge=1, le=16)
    dr: bool = False
    max_steps: int = Field(default=1200, ge=1, le=4000)
    n_gates: int = Field(default=6, ge=1, le=24)   # for preset courses
    seed: int = 0


def create_app(
    repo_root: Path | None = None,
    *,
    runs_dir: Path | None = None,
    courses_dir: Path | None = None,
    studio_dir: Path | None = None,
    device: str = "cuda",
) -> FastAPI:
    """Build the Studio FastAPI app. Dirs default to the repo layout; override for tests."""
    root = Path(repo_root) if repo_root is not None else _REPO_ROOT
    runs_dir = (runs_dir or (root / "runs")).resolve()
    courses_dir = (courses_dir or (root / "assets" / "courses")).resolve()
    studio_dir = studio_dir or (root / "web" / "studio")

    app = FastAPI(title="neural-whoop studio", version="0.1.0")

    # ----------------------------------------------------------------- policies
    @app.get("/api/policies")
    def get_policies() -> list[dict]:
        return _list_policies(runs_dir, root)

    # ----------------------------------------------------------------- courses
    @app.get("/api/courses")
    def get_courses() -> dict:
        return {
            "courses": courses_mod.list_courses(courses_dir),
            "presets": courses_mod.list_presets(),
        }

    # ----------------------------------------------------------------- training scalars (TB)
    @app.get("/api/policies/{run}/scalars")
    def get_scalars(run: str) -> dict:
        from neural_whoop.studio import tbscalars

        run_dir = (runs_dir / run).resolve()
        if not run_dir.is_relative_to(runs_dir) or not run_dir.is_dir():
            raise HTTPException(status_code=404, detail=f"no such run: {run!r}")
        return {"run": run, "tags": tbscalars.run_scalars(run_dir)}

    # ----------------------------------------------------------------- runs (replay files)
    @app.get("/api/runs/{path:path}")
    def get_run(path: str) -> FileResponse:
        try:
            target = _resolve_run(runs_dir, path)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        # Serve gzip raw (octet-stream, no Content-Encoding) so the browser doesn't auto-inflate —
        # the frontend's DecompressionStream handles .gz itself.
        return FileResponse(target, media_type="application/octet-stream", filename=target.name)

    # ----------------------------------------------------------------- rollout (sim-backed)
    @app.post("/api/rollout")
    async def rollout(req: RolloutRequest) -> dict:
        from neural_whoop.studio.rollout import studio_rollout

        policy_abs = _resolve_under(root, req.policy)
        if not policy_abs.is_file():
            raise HTTPException(status_code=404, detail=f"no such policy: {req.policy}")
        if ROLLOUT_LOCK.locked():
            raise HTTPException(status_code=409, detail="a rollout is already running")
        async with ROLLOUT_LOCK:
            try:
                _, summary = await anyio.to_thread.run_sync(
                    lambda: studio_rollout(
                        policy_abs, req.course, req.drone_count, dr=req.dr,
                        max_steps=req.max_steps, seed=req.seed, n_gates=req.n_gates,
                        device=device, courses_dir=courses_dir, runs_dir=runs_dir,
                    )
                )
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        return summary

    # ----------------------------------------------------------------- static studio (LAST)
    if studio_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(studio_dir), html=True), name="studio")

    return app


def app_factory() -> FastAPI:
    """Import-string factory for ``uvicorn --reload`` (needs a re-importable target, not an app
    instance). Device comes from ``NW_STUDIO_DEVICE`` (set by ``scripts/serve.py``), default cuda."""
    import os

    return create_app(device=os.environ.get("NW_STUDIO_DEVICE", "cuda"))


# --------------------------------------------------------------------------- helpers
def _rel(path: Path, root: Path) -> str:
    """Repo-relative POSIX path, falling back to the absolute path if outside the repo."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _resolve_under(root: Path, rel: str) -> Path:
    """Resolve a repo-relative path under ``root``, guarding traversal."""
    root = root.resolve()
    target = (root / rel).resolve()
    if not target.is_relative_to(root):
        raise HTTPException(status_code=400, detail=f"path escapes repo: {rel!r}")
    return target


def _resolve_run(runs_dir: Path, rel: str) -> Path:
    """Resolve a runs-relative replay path, guarding traversal; raise ``ValueError`` if missing."""
    runs_dir = runs_dir.resolve()
    target = (runs_dir / rel).resolve()
    if not target.is_relative_to(runs_dir):
        raise ValueError(f"path escapes runs dir: {rel!r}")
    if not target.is_file():
        raise ValueError(f"no such run: {rel!r}")
    return target


def _list_policies(runs_dir: Path, root: Path) -> list[dict]:
    """List ``runs/*/ckpt_final.pt`` policies with display metadata.

    Each entry carries enough for the Studio's policy panel to render without a second round-trip:
    ``task``/``obs_dim``/``act_dim``/``step`` from the meta sidecar, ``created`` (checkpoint mtime,
    epoch seconds), the full ``eval`` metrics dict when an ``eval.json`` exists (``best_lap`` kept as
    a flat convenience for the selector label), and ``has_scalars`` so the UI knows whether to offer
    training charts.
    """
    out: list[dict] = []
    if not runs_dir.exists():
        return out
    for ckpt in sorted(runs_dir.glob("*/ckpt_final.pt")):
        run_name = ckpt.parent.name
        info: dict = {
            "path": _rel(ckpt, root), "name": run_name, "run": run_name,
            "task": "gate_race", "obs_dim": None, "act_dim": None, "step": None,
            "best_lap": None, "eval": None, "created": None, "has_scalars": False,
            "family": "gate", "needs_course": True,
        }
        try:
            info["created"] = ckpt.stat().st_mtime
        except OSError:
            pass
        meta_path = ckpt.with_suffix(ckpt.suffix + ".meta.json")
        if meta_path.is_file():
            try:
                m = json.loads(meta_path.read_text())
                info.update(task=m.get("task", "gate_race"), obs_dim=m.get("obs_dim"),
                            act_dim=m.get("act_dim"), step=m.get("step"))
            except Exception:  # noqa: BLE001 - skip an unreadable sidecar
                pass
        # Family flag drives the UI (gateless tasks hide the course selector). Derived from the task
        # so the frontend never hardcodes task names.
        from neural_whoop.studio.rollout import GATELESS_TASKS, task_family
        info["family"] = task_family(info["task"])
        info["needs_course"] = info["task"] not in GATELESS_TASKS
        # Eval metrics from a recorded eval.json (runs/<run>/eval.json or viz/eval.json).
        for cand in (ckpt.parent / "eval.json", ckpt.parent / "viz" / "eval.json"):
            if cand.is_file():
                try:
                    ev = json.loads(cand.read_text())
                    info["eval"] = ev
                    bl = ev.get("best_lap_time")
                    if bl is not None:
                        info["best_lap"] = float(bl)
                    break
                except Exception:  # noqa: BLE001
                    pass
        info["has_scalars"] = any(ckpt.parent.glob("events.out.tfevents.*"))
        out.append(info)
    return out
