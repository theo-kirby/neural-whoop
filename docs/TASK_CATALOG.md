# Task catalog (roadmap)

The backlog of policies/tasks the autonomous agent grows, each a `DroneTask` in
`src/neural_whoop/tasks/`. Tasks are ordered roughly by build-up of capability (single-drone →
perception → swarm). Each has a **metric** (what to optimize) and a **loose sim2real basis** (why it
plausibly transfers to a real whoop). Difficulty is relative to the green baseline.

A task is "in the catalog" when it has a registered `DroneTask`, a config, and an eval metric. The
agent picks the next item, opens a Flywheel branch, and iterates (see `AGENTS.md`).

## Status legend
✅ done · 🔜 next · ⬜ planned · 🧊 deferred (Isaac/photoreal RGB)

---

### ✅ `gate_race` — time-optimal single-drone gate racing
- **Metric:** lap time ↓ (guardrails: lap-completion rate, crash rate).
- **Obs/oracle:** obs-v4 + next-gate lookahead; state-based speed oracle (point-mass timing). No
  rendering — avoids the Blackwell camera path.
- **Sim2real basis:** CTBR + body-frame obs + airframe/seam DR; the most-studied transfer regime
  for FPV quads.
- **Baseline:** ~3.87 s best lap vs 3.47 s oracle, ~91 % completion (DR-off eval).

### 🔜 `gate_race` refinements (no new task; pure optimization)
- Better speed oracle (accel/turn-rate-limited point mass → tighter lap-time target).
- Racing-line reward (velocity-direction / minimum-jerk terms), DR/curriculum schedules.
- SHAC/BPTT via DiffAero's differentiable path; compare to PPO at equal wall-clock.

### ✅ `target_follow` — standoff keep-in-view of a moving target through a noisy detector
- **Metric:** `time_in_view_rate` ↑ + `mean_track_error` (|distance − d*|) ↓ (both from ground truth).
- **Status:** implemented (`tasks/target_follow.py`, `configs/target_follow{,_clean}.yaml`). Standoff
  keep-in-view (hold d*=1.5 m, target centered in a 110° FOV) over an orbit/lissajous mover; obs-v4
  unchanged (target estimate replaces the gate vector), run through the perception oracle + the
  `DetectorNoise` seam (bearing/range/FOV/dropout + stale-hold). `target.py` supplies the batched
  motion field. **First empirical result (Flywheel `cool-resonance-0983`, MIXED/Pareto):**
  detector-training gives condition-invariance + ~65× fewer crashes under noise, but bought it by
  backing off (2.17 m vs d*=1.5 m); the naive oracle policy does *not* lose the target under noise
  (in-view 0.996) — the gap is crash-rate, not tracking. The tighter-standoff-reward follow-up
  (`old-leaf-3989`) was **refuted** (`royal-wildflower-3231`, RED): tightening only nudged standoff
  2.17→1.97 m and only by spending crash-robustness (~8×) — the back-off is a genuine
  **robustness↔accuracy frontier set by the perception, not a reward artifact** (same shape as the
  racing tight↔big Pareto). The **detector-regime sweep** (`nameless-bar-9184`, measurement/RED)
  then localized *which* perception axis: sweeping dropout {0→0.10} and FOV {110→150°} with the
  reward held identical leaves standoff **flat at ~2.2–2.5 m** (zero-dropout sits at 2.47 m, *farther*
  than the 0.05 anchor) — the back-off is **insensitive to detection availability** and is driven by
  per-fix **bearing/range precision** (3° / 10%, present on every fix); only removing the detector
  entirely recovers d* (the clean policy, at 10–60× the crash rate). So the lever is **not**
  dropout-coasting memory but precision-*filtering* (EMA/Kalman on the noisy fix) or a better onboard
  detector. **That precision-filtering lever LANDED (`long-tree-2976`, GREEN):** an in-place **EMA**
  on the body-frame estimate (`estimate_ema_alpha`; obs stays 11 / MCU-clean) averages successive
  noisy fixes → standoff **2.17→1.54 m** (track_err 0.91→0.25, ≈ the clean policy) at crash 8.7e-5 —
  **5.6× safer than the brittle clean policy** and below the racing reliability bar, condition-invariant.
  A new Pareto-dominant corner (accurate *and* robust); the EMA is a reusable perception primitive for
  any detector-fed task. The α-sweep follow-up (`flat-waterfall-0121`) found a **threshold**: α=0.85 is
  the *robust* operating point (both seeds hold d*, dominating 0.7), α=0.7 is seed-fragile (1/2 seeds
  back off — the original single-seed GREEN sat on the knife-edge), α=0.5 too weak; the recommended
  default is **0.85** (`configs/target_follow_ema.yaml`). Honest camera-only eval via the DiffAero
  depth render remains a later hook.
- **Sim2real basis:** the render-free seam + detector-error DR is exactly the lab's validated Phase-8
  trick; a cheap onboard blob/depth detector closes the loop on hardware.

### ✅ `hand_follow` — close-follow a jerky hand target through a noisy detector (Flywheel hop-23)
- **Metric:** `follow_hold_rate` ↑ (frac of steps within `hold_tol` of d* — responsiveness) +
  `mean_track_error` ↓ + `time_in_view_rate` ↑ (all ground truth).
- **Status:** implemented (`tasks/hand_follow.py`, subclasses `target_follow`; `configs/hand_follow_*.yaml`).
  Close-follows (d*=0.8 m) a **`KIND_ZIGZAG`** triangle-wave hand mover (sharp, abrupt direction
  reversals — the closed-form stand-in for a held hand), through the same detector seam. **Result
  (Flywheel `<hand_follow>`, GREEN):** the clean policy follows the jerky hand at hold **0.996**
  (track_err 0.11, ~0 crash); detector noise degrades it (hold 0.996→**0.630**, backs off 0.8→1.05 m);
  the **EMA(0.85) primitive RECOVERS it on abrupt motion** (hold 0.630→**0.985**, standoff back to
  ≈d*). The lag concern (EMA failing on sharp reversals) did **not** materialize at target_speed 1.8 —
  variance-reduction still outweighs lag, so the EMA's validated envelope (smooth `target_follow`)
  **extends to jerky motion**. A gesture channel (stop/come) can be added to the obs later.
- **Basis:** same perception seam; the "target" is a hand-held marker. The `KIND_ZIGZAG` mover is the
  first non-smooth motion in `target.py`.

### ✅ `gesture_follow` — command-conditioned hand following (STOP/GO gesture channel) (Flywheel hop-25)
- **Metric:** `follow_hold_rate` (frac of GO steps within `hold_tol` of d*) + `stop_compliance` (frac
  of STOP steps with speed < `stop_speed_thresh`) — a good policy scores high on **both**.
- **Status:** implemented (`tasks/gesture_follow.py`, subclasses `hand_follow`; `configs/gesture_follow.yaml`).
  Appends a discrete **STOP/GO command bit** to the obs (**obs_dim 11→12**, the first follow-seam obs
  growth — MCU note: +1 channel); the shared policy follows the jerky hand on GO and hovers in place on
  STOP. The command is a piecewise-constant per-env bit that flips at random, so within one episode the
  policy must read `obs[-1]` and switch behaviours. **Result (Flywheel `gesture_follow`, GREEN):** the
  first **command-conditioned** policy in the lab works — `stop_compliance` **0.947** (hovers on
  command), `follow_hold_rate` **0.583** (follows on command), balanced exposure (go_fraction 0.495),
  crash 1.6e-5 (safest in the catalog). The policy genuinely *uses* the channel (a pure follower scores
  ~0 stop_compliance; a pure hoverer ~0 follow_hold). Honest cost: GO-follow precision drops vs pure
  `hand_follow` (0.583 vs 0.985) — a **re-acquisition tax** (the hand drifts away during each STOP, so
  resumed-GO steps spend time catching up) plus the tiny net splitting capacity across two behaviours.
- **Basis:** the foundation for gesture-controlled flight; a richer gesture vocabulary (come/go/land)
  is a natural extension of the command channel.

### ⚠️ `command_follow` — 3-way command vocabulary (STOP/NEAR/FAR), scales-but-degrades (Flywheel hop-26)
- **Metric:** `stop_compliance` + `near_hold` (d*=0.7) + `far_hold` (d*=1.8) — a command-ignoring policy
  cannot score on both near AND far (non-overlapping bands).
- **Status:** implemented (`tasks/command_follow.py`, subclasses `hand_follow`; `configs/command_follow.yaml`).
  Extends the gesture channel to a 3-way command via one obs scalar (obs_dim 12). **Result (nuanced):**
  the channel SCALES — three distinguishable behaviors emerge (nonzero near 0.307 AND far 0.255 at
  1.1m-apart bands proves the policy reads the command), STOP 0.698, in_view 0.933, crash 2.5e-5 — but
  per-command PRECISION degrades vs the 2-way `gesture_follow` (stop 0.95→0.70, follow 0.58→0.25-0.31).
  A [128,128] net holds a 3-command vocabulary LOOSELY: capacity split 3 ways + compounded
  re-acquisition transients (each command resample jumps the target while the hand keeps moving).
- **Basis:** characterizes how the command-conditioned capability scales with vocabulary size; bigger
  net or curriculum is the lever to tighten the per-command precision.

### ✅ `hover` — auto-stabilization / station-keeping with disturbance recovery
- **Metric:** `mean_pos_error` (|setpoint − pos|) ↓ + `hold_rate` (frac of steps within `hold_radius`)
  ↑ + `crash_rate_per_step` (guardrail); `mean_speed`/`mean_tilt_deg` characterize the hold.
- **Obs/oracle:** obs-v4 (11), unchanged — the body-frame vector to a world-frame **setpoint**
  replaces the gate/target vector; gateless, single-drone, state-based (no pixels).
- **Status:** implemented (`tasks/hover.py`, `configs/hover.yaml`, tiny `[64,64]` net). Reward =
  position bell + upright + velocity/spin damping + alive − smoothness − crash; mixed
  hold/fly-to-point/recover spawns. Trained against **wind + the impulse DR seam** (push + dropped-
  block tumble) so it survives the live Studio editor's disturbances.
- **Baseline (40M):** clean hold `pos_error` 0.15 m / `hold_rate` 0.91 / tilt 1.7°; under full DR
  (wind 2 + impulses) `pos_error` 0.28 m / `hold_rate` 0.75 / ~0 crashes — leans into wind, arrests
  shoves, recovers from dropped-block tumbles. The policy the **Live** Studio tab pokes at.
- **Sim2real basis:** the impulse seam (`add_velocity`/`add_body_rate`) drives both training and the
  editor, so what the editor throws is exactly what the policy was hardened to reject.

### ✅ `hover_blind` — fully-autonomous IMU-only hover (no-flow-deck first flight)
- **Metric:** same accumulators as `hover`; honest readout is `mean_tilt_deg` + `crash_rate_per_step`
  (what the policy can control) with `pos_error`/`hold_rate` reporting the open-loop drift.
- **Obs/oracle:** **[roll, pitch, p, q, r]** (5) — exactly what the real Air65 II provides over the
  MSP WiFi bridge (MSP_ATTITUDE + MSP_RAW_IMU); no position/velocity/altitude channels exist.
- **Status:** implemented (`tasks/hover_blind.py`, `configs/hover_blind_air65.yaml`) — a pure
  observation ablation of `hover` (reward/spawn/metrics inherited). Tight thrust/mass DR anchored by
  the bench-measured hover throttle (~1410 µs @ 3.6–3.7 V, 2026-07-05).
- **Sim2real basis:** THE first-flight task for sim2real branch B while the flow deck is unfitted.
  Attitude stabilization + tumble recovery are fully observable and closed-loop; altitude/position
  are physically open-loop (see task docstring) — deploys via `scripts/pilot.py`, tethered.
- **Baseline (40M, 2026-07-05):** no-DR tilt **1.14°** (attitude solved); but the raw deterministic
  trim is 12% low (clipped-Gaussian exploration bias — see SIM2REAL Stage 0.5) → steady sink,
  floor-exit median 4 s. One scalar trim (+0.0616 on act[0]) → pure-hold 30 s survival 0→**100%**
  no-DR. Deployment MUST bench-calibrate thrust trim; no constant trim survives full thrust/mass DR
  (open-loop physics).
- **Deploy checkpoint (3.2B `hover_blind_air65_long`, 2026-07-05):** after the effective-mean fix
  (`5c735cd`) + 80× steps with episode_len 1500: σ_thrust 0.478→0.032, steady v_z +0.01 m/s,
  pure-hold 30 s survival **91%** no-DR (0.087 crash), drift speed 0.069 m/s, tilt 1.68°. THE
  first-flight checkpoint; exports are deployment-correct as-is.

### ❌ `hover_blind_v2` — noise-hardened blind hover + a leaky climb-rate channel (2026-07-06, REFUTED)
- **Result (RED, Flywheel `muddy-hill-9397`):** the three-way 3.2B-step sweep is **refuted**. All
  three arms (flagship / `_novz` / `_noiseonly`) **sink to the floor** — no-DR pure-hold 30 s
  survival **0.0%** vs the baseline's 91.6% — despite *better* attitude (no-DR tilt 0.69–1.96°).
  The honest 2.5 rad/s gyro-noise DR (isolated by `_noiseonly`, which keeps the baseline reward and
  drops vz yet still sinks) **re-breaks the open-loop vertical trim** the baseline had solved; the
  reward steepening and the vz channel only *shorten* the sink (median exit 3.98→2.74→1.70 s). The
  vz channel did not rescue altitude — its input carries the honest ±1.5 m/s DC bias, so the leaky
  acc-integrated estimate is unusable. **Verdict: more DR is the wrong lever; blind IMU-only vertical
  hover needs the flow deck (real closed-loop velocity).** `cold-night-8900` (`hover_blind_air65_long`)
  remains the first-flight checkpoint of record; the exported `hover_blind_air65_v2` deploy JSONs
  carry a sinking trim — do not deploy. `scripts/survival_probe.py` (committed) is the metric.
- **Metric:** same as `hover_blind`; the acceptance bar (no-DR 30 s survival ≥ 95%, mean_tilt ≤ 2.5°,
  mean_speed ≤ 0.07, dominate the old policy under honest DR) was **not met** — survival regressed to 0%.
- **Attribution corrected (2026-07-06, Flywheel `quiet-bonus-7296`/`muddy-brook-9314`):** the
  "gyro-noise DR itself" attribution above was confounded (5 factors changed at once). The
  one-factor **R1** arm (`hover_blind_air65_r1.yaml` — white noise kept, thrust 0.12→0.05,
  attitude bias zeroed, curriculum 0.5) still sinks to 0.0% M1 — **trim poisons exonerated; the
  noise as modeled (i.i.d. WHITE at measured amplitude) is the culprit.** New honesty-split metric:
  M2 = calibrated-trim (thrust_scale 0) honest-noise survival, bar ≥ 80% — baseline scores 0.1%,
  white-trained arms 3–4%. Open question: the real gyro is Betaflight-LPF-filtered (spectrum is
  colored, not white) — under test with the AR(1) `obs_noise_ar_channels` seam (R2/R3 arms,
  ρ modeled/unvalidated).
- **Ladder closed (RED, Flywheel `rough-art-1658`):** R3 (colored, one factor vs R1) and R4
  (+privileged `vz_penalty`/`thrust_const_penalty` reward, `tasks/hover.py`) also 0.0% M1 —
  hold time monotonically improves (2.96 → 5.18 → 12.84 s median) but nothing reaches 30 s and
  M2 worsens down the ladder. **Final attribution: the honest noise amplitude itself** (2.5 rad/s
  gyro SD) makes the open-loop trim unlearnable in this recipe. `hover_blind_air65_long` remains
  the flagship; the flow-deck (Stage-1) path is confirmed with clean attribution.
- **SUPERSEDED — stock-hardware campaign (2026-07-07, Flywheel `delicate-credit-2979`, closed):**
  the amplitude verdict above was itself incomplete — the amplitude is *aliased frame vibration*,
  and the killer was the **amplitude-LOCKED trim** of fixed-amplitude training (`polished-moon-9652`:
  a d50-trained policy survives 81/43/0.3% at 0.8/1.0/1.2× its trained sd). **Per-episode
  amplitude-DR (`obs_noise_amp_range U[0.5,2.0]`) + obs_stack 8 SOLVES the noise wall**:
  `hover_blind_air65_d50var_s8` (`broken-wildflower-8398`, now ★ studio-baseline) survives M1-live
  89–100% across 0.5–1.2× and **61.1% at the raw 2.5 rad/s floor** (old flagship: 0.05%) — the
  "needs the flow deck" conclusion is **overturned for the noise axis**. Residual gap = **action
  latency > ~40 ms alone** (knockout 29.8→98.2%); action-echo and jitter-matched-training levers
  both RED (`red-fire-4210`, `bold-shadow-8014`); handed to the bench (link age histogram, 100 Hz
  control rate, ESP command hold). See the SIM2REAL.md campaign block for the full record.
- **Obs/oracle:** **[roll, pitch, p, q, r, vz_est]** (6) × `obs_stack 3` (deployed input 18).
  `vz_est` simulates the deployed pilot's leaky acc-integrated climb-rate estimate exactly
  (leak τ 4 s, clamp ±2 m/s, decay-only past 25° tilt — `scripts/pilot.py`'s VZ_* constants);
  its real-world noise/DC-bias come from the per-channel obs-noise/bias DR, not the task.
- **Status:** implemented (`tasks/hover_blind_v2.py`, `configs/hover_blind_air65_v2.yaml` +
  `_novz`/`_noiseonly` sweep ablations). Estimator state advances in `reward_and_done` (once per
  step); `observe` is a pure read (the env calls it twice on reset steps).
- **Sim2real basis:** the 2026-07-06 flight campaign measured the deployed `hover_blind` stack's
  actual gaps (gyro noise floor ±145 °/s sd — 250× the trained 0.01; obs age p99 112 ms; vz DC
  bias −0.6..−1.6 m/s; ±2° residual level bias) and this task/config trains against all of them:
  per-channel obs noise + per-episode bias DR, `action_latency_steps 5`, steeper upright well
  (σ 0.25) so commanded corrections clear the real noise floor, `obs_stack 3` as the policy's
  averaging path. When the policy consumes vz, the pilot's external climb-damper P/I turn OFF
  (the policy owns vertical damping; the RPM governor stays as the absolute thrust anchor).

### 🚧 `hover_tof` — measured-height hover: the bridge VL53L1X closes the altitude loop (2026-07-13)
- **Why:** every blind flight's remaining ceiling was open-loop altitude (the v2/R-ladder record
  above: an IMU-integrated vz is unusable, the RPM damper only *damps*). The CJMCU-531 ToF soldered
  under the frame is the first *measured* state channel — so the policy can finally observe height
  and own the vertical loop.
- **Obs/oracle:** **[roll, pitch, p, q, r, height_err]** (6) × `obs_stack 8` (deployed input 48).
  `height_err = setpoint_z − h_meas` (the obs-v4 "target minus measurement" sign: + = climb).
  `h_meas` mirrors the deployed estimator exactly: true z when fresh+valid (~40 Hz ranging vs the
  50 Hz loop → per-step Bernoulli refresh), zero-order-held on staleness / >1.3 m slant saturation /
  >45° tilt. Ranging noise (sd 0.02 m) + mount/surface bias (±0.03 m) ride the per-channel DR —
  datasheet-plausible until the first ToF-equipped flight calibrates them.
- **Deploy contract (`neural_whoop.pilot`):** the pilot feeds `--target-height − tof·cosr·cosp`
  (flat-floor tilt correction), last-valid-held; family is task-keyed off the export meta (a 6-dim
  file without `task: hover_tof` stays the vz family). Setup refuses to fly without a live ToF;
  >1 s sensor silence in flight aborts (`tof_lost`). External climb damper OFF (the policy owns
  altitude; RPM governor stays). The exact channel is logged as CSV col 26 `h_err`, so
  `sim_vs_real.py` replays it byte-exactly.
- **Metric:** `mean_z_error` (new, whole hover family) + the standard hover accumulators; the
  deploy-relevant bar is M1-live-style survival with the altitude now *closed-loop* — the sim Δ
  to beat is `d50var_s8`'s open-loop z drift.
- **Status:** implemented (`tasks/hover_tof.py`, `configs/hover_tof_air65.yaml` — d50var_s8 + ONE
  factor: the height channel, setpoint band lowered into the sensor band 0.5–1.1 m).
- **Result (3.2B `hover_tof_air65`, 2026-07-13 — ALTITUDE SOLVED, leveling regressed):**
  no-DR `mean_z_error` **0.651 → 0.043 m** (−93% vs the parent), no-DR pure-hold 30 s survival
  **100%** (parent 0% — its noise-tuned trim fails a clean world), M2-sensor 29.8→**42.1%**, and
  **zero floor/ceiling exits anywhere in the probe battery** (`scripts/exit_probe.py`) — the
  vertical loop is closed. BUT M1-live leveling robustness regressed: 99.9→**75.2%** at 1.0×
  (curve 99.9/82/75/69% at 0.5/0.8/1.0/1.2×), ALL failures fast horizontal departures (median
  1.68 s); knockouts exonerate the ToF channel and its noise — the gyro/attitude-noise response
  is what regressed (hypothesis: the 6th channel × stack 8 grew the input 40→48 on the same
  [64,64], re-opening the d50var capacity contention; a width arm is the obvious next probe).
  **Not deploy-ready until the leveling regression is fixed** — a real flight would flyaway
  sideways ~1-in-4 at the honest noise floor. `runs/hover_tof_air65/probes.json` has the battery.
- **Leveling-regression ladder (4 arms, 2026-07-13 — frontier mapped, compromise shipped):** four
  one-factor arms swept a **clean-trim ↔ noise-robustness frontier** with no gate-dominant point
  (deploy gates: no-DR z err ≤0.05 m; M1-live ≥98% @1.0×, ≥85% @0.8–1.2×; m2sensor ≥42%; zero
  vertical exits — all four batteries in `runs/hover_tof_air65_*/probes.json`):
  `w128` ([128,128]) recovers nominal (1.0× 75.2→**98.9%** — capacity contention CONFIRMED) but
  halves m2sensor (42→20.5%); `w128u15` (+`upright_scale 1.5`) buys most of the tail back
  (m2sensor 36.5%, best-of-line hover stillness 0.22° tilt) at 95.4% @1.0×; `w192u15` ([192,192])
  is the first m2sensor pass (**50.1%**) but loses the setpoint (z err 0.120 m); the amp-curriculum
  arm (`obs_noise_amp_curriculum`, RED) collapses nominal to 69.7% with no tail gain — easing into
  the noise prevents the amplitude-invariant trim from forming. Zero floor/ceiling exits in every
  probe of every arm: the ToF altitude win is robust to all of it. **Shipped (user decision):
  `hover_tof_air65_w128u15`** as best compromise — deploy target 1.0 m (pilot default), weights +
  selftest parity 6.4e-08 + fake-bridge full flight OK; the ≥1.2×-amplitude tail risk is covered by
  bridge IMU oversampling (effective noise <1.0×) plus the `tof_lost` abort and radio kill. First
  real ToF flight recalibrates the placeholder h-noise DR from CSV cols 25/26.

### 🔜 `acro_flip` — learned single-axis flip / barrel roll (the first *agility* task)
- **Metric:** `flip_success_rate` (reached Φ = 2π·`n_rotations` **and** recovered level, no crash) ↑,
  with `mean_altitude_loss` (max `z0 − z`) + `mean_completion_time` + `post_recovery_tilt_deg`
  characterizing the maneuver and `crash_rate_per_step` the guardrail.
- **Obs/oracle:** **[gravity_body(3), p, q, r, rotation_remaining]** (7), deploy-honest / IMU-only.
  `gravity_body` (`Rᵀ·[0,0,-1]`) is unambiguous through a full inversion where euler roll/pitch
  wrap/gimbal-lock; `rotation_remaining` ∈ [1→0] is the maneuver-phase signal (tracked internally in
  sim; supplied by the pilot's maneuver clock at deploy). No altitude channel — altitude is open-loop
  for the brief maneuver (RPM thrust anchor defends it) and used only in the *reward* (privileged).
- **Status:** implemented (`tasks/acro_flip.py`, `configs/acro_flip.yaml` barrel roll +
  `configs/acro_flip_pitch.yaml` axis variant; tiny `[64,64]` net, obs 7). Reward-shaped discovery,
  **no reference trajectory**: a monotone/saturating rotation-progress term toward Φ (`reward.rotation_progress`)
  + one-time completion bonus + a recover term (upright bell − spin, gated after completion) +
  privileged altitude-keep − smoothness − crash. Spawn = level hover at rest (the flip is the learned
  behaviour). Config-selectable `axis` (roll→`p` / pitch→`q`) and `n_rotations`. No env/contract/dynamics
  changes — the rate envelope (`ActionLimits.max_body_rate_rp_rps = 12` rad/s ≈ 690°/s) is already
  acro-capable. Awaiting the first 5090 training run + Studio visual verdict.
- **Sim2real basis:** pure IMU + the existing act-v2 CTBR contract → **zero new hardware** (the
  productive agility milestone while the XIAO Sense camera module ships). The acro sim2real risk —
  the attitude estimate degrading mid-flip — is modeled by per-channel obs noise/bias on the
  `gravity_body` channels (config only). Real acro *flight* (a `scripts/pilot.py` deploy change:
  `obs_from_msp_acro` + a relaxed `check_policy_family` + a maneuver trigger) is a later milestone;
  sim train + eval + Studio need none of it.

### ⬜ `alt_sensor` — alternative-sensor module (e.g. range/flow/lidar-lite)
- **Metric:** task metric under a degraded/alternative sensor suite.
- **Basis:** swap the perception front-end (the seam is explicitly swappable); tests robustness to
  the sensor a given whoop build actually carries.

### ⬜ `explore_map` — mapping / exploration / coverage
- **Metric:** coverage fraction ↑ within a time budget (collision-free).
- **Basis:** DiffAero's depth/LiDAR render (Blackwell-OK) for the occupancy signal; render-free
  proxy oracle for fast training.

### ✅ `swarm_race` — multi-drone shared-track gate racing (first swarm task, Flywheel hop-13)
- **Metric:** swarm lap throughput at a bounded collision rate — `lap_completion_rate` ↑ +
  `collision_rate_per_step` bounded + `best_lap_time` ↓ (guardrail: out-of-arena crash rate).
- **Obs:** the single-drone racing obs (14) + nearest in-env neighbour's body-frame relative
  position (3) and velocity (3) → obs_dim 20 (MCU deploy-size flag). The neighbour channel is what
  lets the tiny shared policy keep separation.
- **Coupling:** `n_agents` drones share one course; a collision (centre-to-centre < `collision_radius`)
  penalizes the involved drones and ends the env episode (shared fate). Pure task-layer — no env
  changes (agent-flattened dynamics; collision/relative-obs in the task).
- **Sim2real basis:** same CTBR + body-frame obs + airframe/seam DR as `gate_race`; a real cheap
  range/relative-bearing estimate stands in for the neighbour vector. Shared policy across agents.

### ✅ `swarm_formation` — N-drone ring formation around a moving anchor (second swarm task, Flywheel hop-15)
- **Metric:** `mean_formation_error` (dist to assigned slot) ↓ + `formation_hold_rate` (frac within
  `hold_tol`) ↑ at bounded `collision_rate_per_step`.
- **Status:** implemented (`tasks/swarm_formation.py`, `configs/swarm_formation.yaml`). N drones each
  hold their **own** slot on a ring around a slowly-moving anchor (reuses the `target.py` mover);
  shared policy + nearest-neighbour obs (obs 17) + collision penalty; no shared track. **First result
  (Flywheel `raspy-moon-0909`, GREEN):** the ring forms+holds tightly — formation_error 0.17 m,
  hold_rate **0.997**, **ZERO collisions**, DR-robust. Confirms the density-curve prediction
  (`proud-wood-6049`): own-slot formation sidesteps the shared-track congestion that capped
  `swarm_race` (0.34 completion / 0.002 collisions/step). Caveat: collisions don't arise here, so it's
  a weak collision-avoidance stress — that lives in shared-track racing / denser formations.
- **Basis:** exercises the `n_agents>1` path (agent-flattened dynamics; relative-observation coupling
  in the task layer). Shared policy across agents. The relative-position-target sibling of
  `swarm_race` (track a desired offset instead of racing a shared track).

### ⬜ `swarm_transport` — cooperative transport / shepherding
- **Metric:** payload/target delivered ↓ time, cooperation required.
- **Basis:** multi-agent coordination with a shared objective; tests emergent cooperation under the
  same tiny per-agent policy.

### ⬜ `swarm_vs_swarm` — competitive multi-agent (self-play)
- **Metric:** win rate vs a population / league.
- **Basis:** self-play over the batched env; the most open-ended discovery target.

### 🧊 Deferred branches
- **Photoreal RGB / Isaac Lab** vision: revisit when Isaac's tiled-camera Blackwell bug (#4951) is
  fixed. Until then, camera tasks train render-free and eval on DiffAero depth.
- **Web studio** (`web/studio/` + `src/neural_whoop/studio/`): **shipped** (first cut) — a
  FastAPI + Three.js viewer to watch saved policies fly selectable courses with a chosen drone
  count (`scripts/serve.py`, `docs/STUDIO.md`). The drag-to-place gate **Editor** and **Metrics**
  charts from the lab studio remain deferred.
- **Spread courses**: gate spacing is now a config knob (`step_min`/`step_max`/`max_turn_deg`) +
  `ARENA_PRESETS`; `configs/gate_race_spread.yaml` trains on far-apart gates (oracle lap ~7 s vs
  ~3–4 s tight). Set up for the autonomous loop; not yet run to convergence.

---

## Adding a task

1. `src/neural_whoop/tasks/<name>.py`: subclass `DroneTask`, set `n_agents` / `obs_dim` /
   `episode_len`, implement `setup / reset / observe / reward_and_done / metrics`, decorate with
   `@register_task("<name>")`.
2. Import it in `src/neural_whoop/tasks/__init__.py`.
3. Add `configs/<name>.yaml`.
4. `uv run python scripts/train.py --config configs/<name>.yaml --tensorboard`, then eval, then open
   a Flywheel node with the artifacts.

The env (`MultiAgentDroneEnv`) needs no changes — it's task-agnostic. Use `env.to_agents` /
`env.to_drones` to reshape between the flat-drone and `(env, agent)` views when a swarm task needs
inter-agent structure.
