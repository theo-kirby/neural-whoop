"""Standard visual pack: rollout -> replay -> Flywheel-native artifacts, in one place.

This is the orchestration the autonomous loop and both CLIs (``scripts/viz.py``,
``scripts/eval.py --viz``) share, so every empirical node attaches the *same* pack. It ties
together the capture seam (:func:`neural_whoop.eval.rollout.evaluate_and_record`), the replay
schema (:mod:`neural_whoop.viz.replay`), and the lazy renderer
(:mod:`neural_whoop.viz.render`).

The renderer (the ``viz`` extra: matplotlib/Pillow/tbparse) is imported **lazily inside**
:func:`build_pack`, so :func:`record_rollout` works with core deps alone (you can always
record the portable ``replay.json.gz`` even without the viz extra installed).

A pack is a directory of files mapped to Flywheel artifact types (see
``docs/VISUAL_CONTRACT.md``):
- ``replay.json.gz`` -> ``json`` (gzipped replay; the durable, portable record)
- ``trajectory.png`` / ``fpv_*.png`` / ``training_curves.png`` / ``comparison.png`` -> ``image``
- ``eval.json`` -> ``json`` (aggregate metrics)
- ``table.csv`` -> ``table`` (leaderboard vs the baseline)
"""

from __future__ import annotations

import json
from pathlib import Path

from neural_whoop.eval.rollout import evaluate_and_record, select_heroes, select_swarm_heroes
from neural_whoop.viz.replay import RunRecorder, build_meta


def policy_label(agent, ckpt: str | None = None) -> str:
    """Human-readable policy label: param count + source checkpoint name."""
    try:
        n = agent.actor.num_parameters()
        base = f"TinyPolicy ({n:,} params)"
    except Exception:
        base = "TinyPolicy"
    return f"{base} · {Path(ckpt).name}" if ckpt else base


def record_rollout(
    env,
    agent,
    out_path: str | Path,
    *,
    config: str = "rollout",
    ckpt: str | None = None,
    n_heroes: int = 4,
    steps: int = 1500,
    deterministic: bool = True,
    record_obs: bool = False,
) -> tuple[Path, dict]:
    """Run a recording rollout and save the replay; return ``(replay_path, metrics)``.

    Uses core deps only (no viz extra). The aggregate ``metrics`` are identical to
    :func:`neural_whoop.eval.rollout.evaluate`.
    """
    meta = build_meta(env, config=config, policy=policy_label(agent, ckpt))
    recorder = RunRecorder(meta)
    # Swarm tasks (n_agents>1): record all agents of one env so they render as a coexisting group;
    # single-drone tasks spread n_heroes across the population for course diversity.
    swarm = int(getattr(env, "n_agents", 1)) > 1
    heroes = select_swarm_heroes(env) if swarm else select_heroes(env, n_heroes)
    metrics = evaluate_and_record(
        env, agent, recorder, heroes=heroes, steps=steps,
        deterministic=deterministic, record_obs=record_obs, group=swarm,
    )
    path = recorder.save(out_path)
    return path, metrics


def build_pack(
    replay_path: str | Path,
    out_dir: str | Path,
    *,
    run_dir: str | Path | None = None,
    baseline: str | Path | None = None,
    eval_metrics: dict | None = None,
    fpv: bool = True,
    gif: bool = False,
) -> dict[str, str]:
    """Render the standard visual pack from a saved replay (needs the ``viz`` extra).

    Args:
        replay_path: The ``replay.json.gz`` produced by :func:`record_rollout`.
        out_dir: Directory to write the pack into.
        run_dir: A training run dir (with ``events.out.tfevents.*``) for the curves plot.
        baseline: A baseline replay to compare against (-> ``comparison.png`` + ``table.csv``).
        eval_metrics: Aggregate metrics to dump as ``eval.json``.
        fpv: Render synthetic FPV keyframes.
        gif: Stitch the FPV keyframes into a GIF (needs ``imageio``).

    Returns:
        Mapping ``{relative_filename: flywheel_artifact_type}`` for everything written.
    """
    from neural_whoop.viz import render

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    replay_path = Path(replay_path)
    artifacts: dict[str, str] = {}

    # The replay itself travels with the pack (json artifact; gz-compressed payload).
    artifacts[replay_path.name] = "json"

    if eval_metrics is not None:
        (out_dir / "eval.json").write_text(json.dumps(eval_metrics, indent=2))
        artifacts["eval.json"] = "json"

    render.plot_trajectory(replay_path, out_dir / "trajectory.png")
    artifacts["trajectory.png"] = "image"

    if fpv:
        paths = render.render_fpv_keyframes(replay_path, out_dir, prefix="fpv", gif=gif)
        for p in paths:
            artifacts[p.name] = "image"
        if gif and (out_dir / "fpv.gif").exists():
            artifacts["fpv.gif"] = "binary"

    if run_dir is not None:
        curves = render.plot_training_curves(run_dir, out_dir / "training_curves.png")
        if curves is not None:
            artifacts["training_curves.png"] = "image"

    if baseline is not None:
        render.plot_time_trial_comparison(
            [replay_path, baseline],
            out_dir / "comparison.png",
            labels=["this", "baseline"],
            table_path=out_dir / "table.csv",
        )
        artifacts["comparison.png"] = "image"
        artifacts["table.csv"] = "table"

    (out_dir / "pack_manifest.json").write_text(json.dumps(artifacts, indent=2))
    return artifacts
