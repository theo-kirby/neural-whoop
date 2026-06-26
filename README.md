# neural-whoop

A **GPU-parallel, swarm-capable whoop RL lab** built on [DiffAero](https://github.com/flyingbitac/diffaero),
developed autonomously on [Flywheel](https://flywheel.paradigma.inc). It is the successor to the
single-drone, PyBullet/SB3 `neural-whoop-lab`: same strong sim2real contract and render-free
perception seam, now trained massively in parallel on one RTX 5090 and built to grow from
single-drone racing to full swarm tasks.

The goal of the lab is to **optimize the RL and discover novel, creative drone policies** across a
broad task catalog, with every experiment recorded as a node in a Flywheel research DAG.

## What's here today (the green foundation)

- **DiffAero substrate** (vendored, BSD-3, pytorch3d-patched): a differentiable, GPU-parallel,
  CTBR-native batched quadrotor — ~32 g whoop-scale params, domain-randomized airframe.
- **`MultiAgentDroneEnv`**: a batched, GPU-resident env (`n_drones = n_envs × n_agents`) with a
  task registry, the render-free perception oracle, and the full sim2real DR seam.
- **`gate_race`**: the first baseline task — single-drone **time-optimal gate racing** with a speed
  oracle. Metric = **lap time** (minimize).
- **Torch-native PPO** over the batched env (GAE with time-limit bootstrap, TensorBoard,
  checkpoints), plus deterministic eval and TorchScript/ONNX export.
- **Tiny, quantization-friendly policies** (the trained racing actor is ~5.4k params).

### Baseline result

On the RTX 5090, 4096 parallel envs, ~40 M steps in **~90 s** (≈ 444 k env-steps/s end-to-end):
ep-return −12 → +85; best lap **3.87 s vs a 3.47 s oracle** (within ~11 %), **91 % lap-completion**,
near-zero crashes (DR-off eval). This is the handoff state for the first autonomous agent.

## Quickstart

```bash
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -e '.[dev,export]'          # torch comes from the cu128 index (sm_120 / 5090)

uv run python scripts/env_check.py         # Milestone-0 gate: GPU + DiffAero + env all green
uv run pytest -q                           # ported pure tests + env smoke

# Train the baseline (TensorBoard + checkpoints under runs/gate_race_baseline/)
uv run python scripts/train.py --config configs/gate_race.yaml --tensorboard

# Evaluate: report lap times; export the deployable policy
python scripts/eval.py --config configs/gate_race.yaml \
    --from runs/gate_race_baseline/ckpt_final.pt --no-dr --export
```

> **GPU note (RTX 5090 / Blackwell):** torch must come from the **cu128** index — the default PyPI
> wheels lack `sm_120` kernels and throw *"no kernel image available"*. `pyproject.toml` pins this;
> `scripts/env_check.py` verifies a real kernel runs. ONNX export additionally needs `onnxscript`
> (in the `export` extra), and `uv run` does not install optional extras — use the activated venv
> for export.

## Docs

- [`CLAUDE.md`](CLAUDE.md) — working brief: architecture, the contract, how to run, key decisions.
- [`AGENTS.md`](AGENTS.md) — the autonomous-agent mandate, Flywheel operating loop, and autonomy bounds.
- [`docs/TASK_CATALOG.md`](docs/TASK_CATALOG.md) — the roadmap of policies/tasks (racing → swarm).
- [`docs/CONTRACT.md`](docs/CONTRACT.md) — obs/act versions, CTBR spec, DR knobs.
- [`docs/FLYWHEEL.md`](docs/FLYWHEEL.md) — how this project maps onto the Flywheel graph.

## License

BSD-3-Clause (matching the vendored DiffAero). See `LICENSE`.
