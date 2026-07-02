# System comparison: PufferLib `drone` (tensaur) vs neural-whoop

*2026-07-02. Competitive deep-dive of PufferLib 4.0's Ocean `drone` environment
(github.com/PufferAI/PufferLib @ `7b11311`, upstream project github.com/tensaur/drone by
Sam Turner & Finlay Sanders, MIT), installed and benchmarked locally on the 5090.
Flywheel branch: `cluster:system-comparison` + `topic:pufferlib` off the root.*

## What they built

An end-to-end RL drone stack with a **proven sim2real deployment** on a Crazyflie 2.1
Brushless (+ Flow Deck v2, no mocap): C SIMD simulator → fused CUDA PPO → pure-C onboard
inference in the Crazyflie firmware. Presented at Warwick AI summits '25/'26
(`docs/summit-26.pdf` in their repo is a candid lessons-learned deck).

### Simulator (`ocean/drone/`, ~1.5k lines of C)

- **Airframe**: Crazyflie 2.1 constants (27 g — same weight class as our whoop) cited
  from `arplaboratory/learning-to-fly`. Mass/inertia/arm/k_thrust/k_drag/k_mot.
- **Dynamics**: RK4 (RK2 option) at **500 Hz with 5 substeps → 100 Hz control**; quaternion
  attitude; per-motor **first-order RPM lag** (`k_mot` = 0.15 s); linear body drag +
  yaw drag torque; gyroscopic/inertia cross terms. **Velocity and body rates clamped
  every substep** — the exact stabilization fix we independently made in
  `dynamics/whoop.py` (they hit the same instability we did).
- **Vectorization**: hand-written SoA SIMD, 8 float lanes per block
  (`vf = float __attribute__((vector_size(32)))`, clang `__builtin_elementwise_*`),
  CPU-side. 2048 total agents = 32 env instances × 64 drones.
- **No wind, no sensor noise, no action latency.** DR is a flat **±5 % uniform** on all
  physical params (gravity ±1 %).

### Obs / action contract

- **Obs (21, float)**: body-frame velocity (normalized by max_vel·√3), body rates
  (normalized), **full world quaternion (4)**, body-frame vector-to-target encoded at
  **two tanh scales** — `tanh(0.1·x)` (coarse, ±10 m range) *and* `tanh(10·x)` (fine,
  ±10 cm resolution) — target ring normal in body frame (3), task one-hot (2).
  *Not heading-invariant* (unlike our obs-v4): the full quat exposes absolute yaw.
- **Actions (4)**: **per-motor target RPMs** in [-1,1], mapped to
  `[rpm_min_for_centered_hover, max_rpm]` so **action 0 = hover** (their deck: random
  init then explores around hover, not around free-fall). End-to-end — **no inner rate
  controller at all** (vs our act-v2 CTBR through DiffAero's rate loop).

### Tasks (multi-task, one policy)

Five tasks share one net via the obs one-hot, mixed across env instances by config
fractions (default: hover 55 % / race 45 %):

- **hover**: fly to a random point from ≤5 m spawn; reward = smooth score
  `1/(1+0.05·(0.7·d/0.01 + 0.15·v/0.01 + 0.15·ω/0.01))` + delta-distance shaping;
  done if drift > target_dist+1 m. Metrics: EMA dist/vel/ω.
- **race**: 10 random rings (r=0.5 m) in a 20×20×10 m box, inter-ring gap band
  [2.5, 8] m, ring normals = smoothed path direction, course centered; plane-crossing
  detection with ±10 % radius margin (annulus hit = collision counter); **+2.45 per
  ring** + delta-distance shaping (2.86/m); metric = rings-passed/10, not lap time.
- **sphere / cube / flag**: hover variants with per-agent slot targets (Fibonacci
  sphere, lattice cube, flag grid) — *swarm-formation-looking demos with zero
  inter-drone physics* (no collisions, no relative obs).

### Trainer (the headline)

Default backend `_C` = **the entire PPO loop in C++/CUDA** (`src/pufferlib.cu`,
~2.3k lines): rollout storage, advantage, optimizer, all fused; Python only
orchestrates. `torch_pufferl.py` is a readable reference impl (`--slowly`).

- **"puff advantage"**: GAE hybridized with V-trace ρ/c importance clipping (works with
  stale data), custom kernel.
- **Advantage-prioritized minibatch sampling** (α≈0.21, β₀≈0.75 annealed) with
  **replay_ratio 2.25** — each rollout trained on ~2.25×.
- **Muon optimizer** (both backends implement it; CUDA `muon.cu`).
- Policy: Linear(21→64) → 2×(Linear 64→64 + GELU) → Gaussian head (learned
  state-independent logstd) + value. **26.2K params** (hidden 64). MinGRU/LSTM available.
- Every hyperparameter in `config/drone.ini` is machine-tuned (their gpytorch-based
  Pareto sweep; log-normal priors declared per-param in the same ini).

### Sim2real (proven; ours is still pending first flight)

- **Onboard** inference on the Crazyflie's STM32F405 (Cortex-M4F @ 168 MHz):
  `puffernet.c` (pure C, no deps) runs an **LSTM** policy variant at **100 Hz**
  (= sim ACTION_DT), motors written at 1 kHz from the latest action. Weights are
  `bin2h`-compiled into the firmware. A ground-station param (`pufferdrone.use_rl`)
  toggles RL vs stock PID — their safety fallback.
- Obs from the stock Kalman estimator (Flow Deck v2 + IMU); target = commander setpoint.
- Their lessons deck (summit-26): sim2real failed **for 3 months**; breakthrough =
  "hover badly, then compare sim-vs-real trajectories side by side". Details that
  mattered: **rotor spin directions, control-frequency match, coordinate frames**.
  Philosophy: *don't model everything* — model what you can well (motor lag), DR the
  rest, use **memory (LSTM) as implicit system-ID** on top of DR.

## Measured head-to-head (this machine, RTX 5090)

| | PufferLib drone | neural-whoop (gate_race Air65) |
|---|---|---|
| Steps/s (train) | **6.4 M** | ~437 k |
| Full run wall-clock | 88.6 M steps in **~14 s** | 120 M steps in ~4.6 min |
| Params | 26.2 K (64×2 MLP) | comparable tiny MLP class |
| VRAM | 1.4 GB (GPU 93 % busy) | multi-GB (batched torch dynamics) |
| Result | race perf 0.876 (9.0/10 rings, 47.8 % full completions), hover EMA dist **4 cm** | best lap ~2.9 s on tight course |

Caveats for honesty: not apples-to-apples. Their env is CPU SIMD with 21-dim obs and a
fused CUDA trainer; ours is GPU torch dynamics with a Python PPO loop, wind/latency/noise
DR, differentiable dynamics (SHAC option), replay recording, and a task-plugin layer.
Their metric is rings-passed (random courses); ours is lap time (fixed, authored courses).

## Where they are better / worse for our purposes

**Better:**
1. **Wall-clock iteration**: ~15× step throughput; a full experiment in 14 s changes
   *how you do research* (their deck: "training needs to be fast — nothing else comes
   close").
2. **Deploy path exists and is proven**: C inference on a 168 MHz M4 at 100 Hz incl.
   LSTM — strong evidence for our eventual onboard phase, and that end-to-end RPM
   policies transfer with thin DR (±5 %) *if* motor lag is modeled and details match.
3. **Sweep discipline**: machine-tuned hypers with declared priors, checked into the
   config next to the env.
4. **Trainer algorithms**: V-trace-clipped advantage + prioritized replay + Muon buy
   sample reuse we don't have.
5. Multi-task conditioning in one tiny net.

**Worse / gaps (from where we stand):**
1. **Thin robustness story**: no wind, no obs noise, no action latency in DR — we model
   all three (they compensate with onboard low-latency inference + LSTM; our offboard
   link *forces* us to model latency).
2. **Not heading-invariant** (world quat in obs); fine for their box arena, weaker prior
   for arbitrary courses.
3. **No real swarm**: formation tasks are independent agents flying to static slots — no
   collision physics, no relative-neighbor obs (our swarm_race/formation layer is ahead).
4. **No lap-time objective / course authoring**: random rings each episode, perf =
   rings/10 — nothing like our seeded course geometry, curriculum knobs, Studio editor.
5. **No visual contract**: live raylib viewer only; no portable replay artifact, no
   baseline comparison packs.
6. CPU env has no path to camera/depth observations (we keep a lazy door open to
   DiffAero's renderer).
7. Sample efficiency explicitly deprioritized ("our data is cheap") — fine for sim-only,
   costly if env steps ever get expensive (rendering, contact-rich swarms).

## Transferable ideas (adopt / test / defer)

| # | Idea | Verdict |
|---|---|---|
| 1 | **Dual-scale tanh target encoding** (coarse+fine channels of the same vector) | **Experiment** — cheap obs-v5 candidate; plausible gate-precision win at range |
| 2 | **puff-advantage** (V-trace ρ/c clip on GAE) + **advantage-prioritized minibatches** + replay_ratio ≈ 2 | **Experiment** — port into our torch PPO; candidate 1.5–3× wall-clock-to-quality win |
| 3 | **Muon optimizer** for tiny policies | **Experiment** — trivial to try on gate_race |
| 4 | **Tiny recurrent core (minGRU/LSTM) as implicit system-ID under DR** | **Hypothesis** — should absorb latency/thrust-scale DR better than MLP; they prove MCU-deployability, and our offboard host makes it free |
| 5 | Hover **score-style smooth reward** (bounded 1/(1+penalty) mixing dist/vel/ω) | **Experiment** for hover/follow tasks — better-conditioned than raw distance |
| 6 | Multi-task one-hot conditioning (hover+race one policy) | **Defer** — aligns with task catalog end-state; revisit after single-task beachheads |
| 7 | Config-adjacent **sweep priors + Pareto sweep harness** | **Method** — adopt the pattern (declared distributions in config); our autonomy loop can drive it |
| 8 | **puffernet pattern**: raw-weights .bin + dependency-free C forward pass for firmware | **Reference** for the phase-2 onboard path (Air65 II offboard remains the locked plan) |
| 9 | Motor first-order lag in dynamics (they model it; DiffAero's CTBR loop hides it) | **Check** — verify what DiffAero's motor model does at our rate limits; add k_mot DR if absent |
| 10 | Control-frequency match discipline (sim ACTION_DT == real loop rate, exactly) | **Check** — pin our offboard loop rate and assert it in the sim2real contract doc |
| 11 | Action mapping centered on hover (0 ⇒ hover) | **Already ours** (act-v2 thrust 1.0 = hover) — independent confirmation of the choice |
| 12 | Vel/ω clamping per substep | **Already ours** (whoop.py saturation) — independent confirmation |

## Bottom line

PufferLib's drone stack is the strongest open evidence that (a) tiny end-to-end
RPM policies sim2real onto sub-30 g quads with thin DR when motor lag + loop-rate +
frame details are right, and (b) fused-trainer throughput (not sample efficiency) is
the highest-leverage research accelerant. Their weaknesses are exactly our strengths
(robustness DR, swarm coupling, course/lap-time rigor, visual contract), which makes the
idea flow mostly one-directional: import their trainer tricks and obs encodings; keep
our substrate, contract, and observability.
