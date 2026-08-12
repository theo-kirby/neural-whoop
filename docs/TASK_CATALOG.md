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
  vertical loop is closed. **⚠️ UNEARNED AS STATED — `exit_probe.py` was broken until 2026-08-08**
  (it classified the *respawn* position, so `floor`/`ceiling` were structurally unreachable and
  every exit fell through to `xy`; see the script's docstring). Re-measured with the fix, the
  claim *holds on the noise twins* — m1live 100% survival, m2sensor 3 exits all horizontal, 0
  floor — but **fails on the full-DR config: 72 floor / 3 ceiling / 718 xy** of a 793-crash cohort
  (38.7% crashed). So "zero vertical exits" is true where survival is ~100% and false where it
  isn't, and the original battery could not have told the difference either way. `survivor_mean_z_err`
  read 0.0 (junk) for the same reason; it is really **0.198–0.218 m** across those three probes. BUT M1-live leveling robustness regressed: 99.9→**75.2%** at 1.0×
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
  <!-- see the ⚠️ above: exit_probe.py could not report a floor/ceiling exit before 2026-08-08 -->
  probe of every arm: the ToF altitude win is robust to all of it. **Shipped (user decision):
  `hover_tof_air65_w128u15`** as best compromise — deploy target 1.0 m (pilot default), weights +
  selftest parity 6.4e-08 + fake-bridge full flight OK; the ≥1.2×-amplitude tail risk is covered by
  bridge IMU oversampling (effective noise <1.0×) plus the `tof_lost` abort and radio kill. First
  real ToF flight recalibrates the placeholder h-noise DR from CSV cols 25/26.

#### `desk_hover` — **Desk-Hover**, the 0.10 m desk operating point (2026-08-08, a CONFIG not a task)
- **What:** `configs/desk-hover.yaml`, still `task: hover_tof`. Hold **0.10 m over a desk** instead
  of 1.0 m in a 3.5 m arena. It stays a config *deliberately*: the pilot keys the 6th obs channel's
  semantics off `meta["task"] == "hover_tof"` **exactly** (`pilot/policy.py`), so a new task string
  would silently make the deployed drone read `vz` where the policy means `h_err`. First user of the
  new policy-naming convention (`CLAUDE.md`): run name == config name == run dir, hyphenated.
- **Why:** the 2026-07-31 crash chain is *structurally absent* here, not mitigated. The measured
  ~0.37 m climb overshoot reaches 0.47 m from a 0.10 m setpoint — **13× inside the 1.3 m sensor
  ceiling** — so the "exit the band → hold `h_err` → motors-off open-loop" steps cannot occur, and
  the worst case is a 10 cm drop onto a desk. **The dangerous direction flips from up to down:**
  8 cm of floor margin (`bound_z_min 0.010` ≈ `WHOOP_REST_Z_M`) against the measured **+23.9 mm**
  static ToF offset, which is 2.4% of a 1.0 m setpoint but **24%** of this one.
- **Deltas vs `hover_tof_air65_w128u15_r25`** (~12, so **not an ablation** — a new operating point):
  `pos_sigma` 0.6→0.10, `dist_penalty` 0.2→2.0, `hold_radius` 0.35→0.08, `arena_radius` 3.5→0.0,
  `z 0.5–1.1`→`0.08–0.16`, `bound_xy` 6.0→0.60, `bound_z` `0.15–4.0`→`0.010–0.60`,
  `spawn_z_margin 0.005` (new), `band_ceiling_m 0.30` (new, metric only),
  **`act.min_thrust_normed 0.25`** (the first hover config to mirror the pilot's `min_thrust_frac`,
  a gap open the whole ladder), `wind_accel_mps2` 1.0→**0.15**, impulses 2.5→0.5 m/s @ prob 0.01,
  `h_err` noise 0.02→0.010.
- **`wind_accel_mps2` 1.0 → 0.15 is the load-bearing change, and it is an honesty fix.** Drag gives
  `τ = D_xy/m = 0.30 s`, so `U(0,1)` m/s² is 0.15–0.30 m/s of terminal drift the policy has no
  channel to see or fight. Measured on a fixed weight-cancelling action: median time-to-horizontal-
  exit **4.5 s at 1.0 → 20.7 s at 0.15 (4.6×)**.
- **Metric:** the desk four-gate battery, bars fixed before any result (`runs/desk-hover/probes_desk_*.json`):
  clean pure-hold `mean_xy_error` ≤ 0.10 m · clean `mean_height` 0.10 ± 0.02 · `ep_peak_z_m` ≤ 0.30
  **and zero floor exits** (hard) · m1live 30 s survival ≥ 0.98.
- **Result (arm 1, 3.2B — GREEN, 3 of 4; the 1.0 m parent scores 0 of 4 on the same battery):**
  clean pure-hold drift **0.2986 → 0.0472 m (−84%)**, `hold_rate` **0.150 → 0.913**, tilt
  1.017→**0.391°**, `mean_z_error` 0.0576→**0.0177 m**; m1live 30 s survival **0.0625 → 0.9995**,
  m2sensor **0.0396 → 0.9834**. The parent dropped onto a 0.10 m setpoint does not just underperform
  — it **sinks into the desk** (`mean_height` 0.042 m, 598 floor exits).
- **The gate-3 miss is the useful part.** 98 floor exits, and they localize exactly: **0** on clean,
  **0** on m1live, **29** on m2sensor, **69** under full DR — i.e. *every one* appears only once the
  ±0.03 m `h_err` **bias** is on. That is the sim pricing the uncalibrated +23.9 mm ToF offset
  against 8 cm of margin, and it makes a **pilot-side `tof_cal`** (the exact analogue of the
  existing `az_cal`/`lvl_cal`) the blocking item for a real 0.10 m flight — a deploy fix, not a
  sim one.
- **Honesty:** the design premise that a coarse `pos_sigma` would make a policy hover *high*
  (0.2–0.3 m) is **refuted** — the parent sinks to 0.042 m and arm 1 settles 1.8 cm *below* its
  setpoint (0.0824). The rescale is still right on reward-*resolution* grounds, but the bias at desk
  scale runs downward, toward the 8 cm margin. `ep_peak_z_m` is uninformative on the pure-hold twin
  (z is pinned); the meaningful peaks are 0.124/0.127/0.200 on m1live/m2sensor/full-DR, all well
  under the 0.30 ceiling. Full-DR survival is **not** comparable across the two, since each ran on
  its own training config (±0.6 m desk vs ±6.0 m arena). This is a **bounded-duration hold**, not a
  station-keep: drift is open-loop and is 0.186 m on m1live over 30 s.
- **Arm 2 — `vxy_penalty` 0 → 0.5, ONE factor (NO-GO).** It *works on its own target*: clean
  pure-hold drift **0.0472 → 0.0356 m (−25%)**, `hold_rate` 0.913 → **1.000**, and `mean_z_error`
  improves under noise (m1live 0.0178 → 0.0128). But the gain lives **only in the clean condition**
  — under every noise twin the drift is *worse* (purehold+noise 0.1336 → 0.1634, m1live 0.1857 →
  0.2069) — and it is paid for in the direction with 8 cm of room: `mean_height` 0.0824 → **0.0786**
  (flips gate 2 by 1.4 mm), **floor exits 98 → 311** (m2sensor 29 → 120), m2sensor survival 0.9834 →
  **0.9380**. Battery **2 of 4**. *Mechanism, and why a bigger weight won't fix it:* the corrective
  move a hovering policy makes against perceived drift **is** horizontal speed, so the penalty is
  nearly free when the attitude estimate is clean and actively suppresses the needed corrections
  once it is noisy; and pressing toward stillness biases the hover lower. **Arm 1 stays the
  recommended Desk-Hover policy.**
- **Named arm 3, not run:** `upright_scale` 1.5 → 2.5, the control the parent's own `probes.json`
  verdict asks for. Arm 2's mechanism argues *for* it — if drift is a leveling-quality problem
  before it is a velocity one, attacking leveling directly avoids the proxy trap that sank arm 2.
- **Not done, deliberately:** the parent idea node asks to *refit the gyro DR* from flight-2
  calibration (props-on sd 0.091/0.108/0.082 rad/s) before training; these configs keep the ladder's
  `[1.25, 1.1, 0.75]`, ~10–14× larger. Orthogonal to everything above and the obvious next probe.

### 🚧 `hover_flow` — the PMW3901 closes the HORIZONTAL loop (2026-08-12)
- **Why:** every hover task above ends with the same caveat. `hover_blind` is open-loop in all
  three axes, `hover_tof` closed the vertical one, and horizontal drift stayed open-loop —
  Desk-Hover's own config says it out loud ("clean pure-hold drift 0.069 m … under sensor noise
  alone both arms drift 0.55–0.77 m"). The PMW3901 optical-flow sensor on the bridge
  (`MSP_BRIDGE_FLOW`, cmd 193) makes horizontal velocity *measured*, which is the first time a
  policy in this lab can observe the drift it is producing.
- **Obs/oracle:** **[roll, pitch, p, q, r, height_err, vx, vy]** (8) × `obs_stack 8` (deployed
  input 64). Channels 0–5 are byte-identical to `hover_tof` (pinned by a test — the pilot keys
  channel semantics off `meta["task"]`, so a reordered prefix would silently misfeed a deployed
  policy). `vx, vy` are body-frame, matching obs-v4's `vel_body` convention.
- **Velocity, NOT position, deliberately.** Integrating flow to a position is free in sim and
  dishonest on hardware: the integral drifts without bound and nothing in the obs observes the
  drift, so the policy would learn to trust a channel that decays. The consequence is stated
  rather than hidden — this is a **drift-rate controller**: it can learn to stop moving, it
  cannot return to a point it has already left.
- **Four modeled ways the channel lies** (each a way it is *wrong*, not merely noisy):
  **(1) height multiplies straight into the velocity scale** (`v = counts/dt · rad_per_count ·
  height`, and the host has only `h_meas`, so the sim scales by `h_meas/z`) — at a 0.10 m
  setpoint the measured +23.9 mm ToF offset is a **24% velocity error**, which is what drove the
  operating point to 0.40 m; **(2) below 0.08 m the sensor is blind** (PMW3901 working range — an
  optical limit, not a noise floor); **(3) a featureless floor returns no motion at full frame
  rate**, invisible to every freshness check, hence an explicit dropout term and the `squal`
  channel on the wire; **(4) it fails in RUNS, not one frame at a time** — `flow_dropout_prob` is
  an i.i.d. per-step coin, so at 0.02 the chance of losing a whole second is 1e-85 and a policy
  trained on speckle alone meets sustained blindness for the first time in the air.
  `flow_blackout_prob`/`flow_blackout_s` (2026-08-12) model the run explicitly and are sized past
  the pilot's 1 s `flow_lost` abort window, so the losses that end a flight are ones the policy
  has flown before. Default OFF, because every flow result before that date was measured without
  them.
- **Blind handling is grace-then-fade to zero, not hold** — the same guard the deployed pilot
  applies to a stale ToF. Holding a stale velocity forever is the confidently-wrong-held-channel
  shape that flew the 2026-07-31 crash; a faded velocity decays to an honest neutral.
- **Status:** implemented (`tasks/hover_flow.py`, `configs/flow-hover.yaml`,
  `configs/desk-flow.yaml`, `tests/test_hover_flow.py`). Sensor state advances in
  `reward_and_done` (once per step); `observe` is a pure read. The **deploy path exists**
  (`tests/test_pilot_flow.py`, docs/SIM2REAL.md "The obs-8 deploy path"): the pilot builds the
  channel, logs it as `vx`/`vy`, and aborts on `flow_lost`. **Not yet flown** — the bench
  calibration that measures `rad_per_count` is the standing blocker, and the pilot refuses to fly
  a flow policy without it.
- **Two operating points.** `flow-hover` holds **0.40 m** (the widest margin on the floor/scale/
  ceiling constraints at once, but a fall from there is a real crash). **Desk-Flow**
  (`configs/desk-flow.yaml`) holds **0.15 m**: still desk scale, still structurally immune to the
  2026-07-31 saturate-and-hold chain, and the lowest setpoint where both sensors work — at 0.10 m
  the ~1.8 cm hover sink plus the uncalibrated +23.9 mm ToF offset puts the sensor at 0.076 m,
  i.e. *blind*. `desk-flow-noflow` is its one-factor control.
- **Watch `flow_valid_rate`** (new metric). A policy can post a fine `mean_xy_error` while flying
  most of the episode on a faded-to-zero channel — that is an open-loop policy wearing a
  closed-loop metric, and this number is what tells them apart.
- **Open calibration debt, stated:** `flow_rate_hz` / `flow_dropout_prob` / `flow_scale_frac` /
  `flow_gyro_residual` are placeholders until the passive calibration flight. This is exactly the
  debt the ToF carried between 2026-07-13 and the 2026-07-30 characterization — which found the
  nominal rate optimistic by **1.6×**. Treat these the same way.

### 🔜 `acro_flip` — learned single-axis flip / barrel roll (the first *agility* task)
- **Metric:** `flip_success_rate` (reached Φ = 2π·`n_rotations` **and** recovered level, no crash) ↑,
  with the **shape** metrics next to it: `mean_altitude_loss` (max `z0 − z`), `max_lateral_drift`,
  `peak_climb` (the pop — this one *should* be nonzero), `settle_pos_error`, `mean_completion_time`,
  `post_recovery_tilt_deg`, and `crash_rate_per_step` as the guardrail.
- **Obs/oracle:** **[gravity_body(3), p, q, r, rotation_remaining, maneuver_phase]** (8),
  deploy-honest / IMU-only **plus the pilot's own clock — no new sensor**. `gravity_body`
  (`Rᵀ·[0,0,-1]`) is unambiguous through a full inversion where euler roll/pitch wrap/gimbal-lock.
  The two phase channels are complementary and that is the point: `rotation_remaining` ∈ [1→0] is a
  **gyro integral** (how much *angle* is left) and `maneuver_phase` ∈ [1→0] a **time clock** over
  `maneuver_len_s` (how much of the window is left). The clock lets the policy *plan* the
  pop → rotate → catch beats; the rotation signal keeps it honest when DR makes the roll run long or
  short (a clock alone would run out mid-inversion under a low rate-gain draw). Both are tracked
  internally in sim and supplied by the pilot's maneuver clock at deploy. **v2 added the clock
  because the pop is otherwise unlearnable, not merely unrewarded:** with obs-7 a level, at-rest
  drone is a *fixed point* — `gravity_body` is pure attitude and carries no specific force — so a
  vertical thrust burst is invisible and the policy cannot tell "just spawned" from "0.2 s into a
  pop". No altitude channel: altitude is open-loop for the brief maneuver (RPM thrust anchor defends
  it) and used only in the *reward* (privileged). The downward VL53L1X is deliberately **not** used —
  it points sideways then up mid-flip, i.e. it is garbage exactly when the maneuver needs it.
- **Status:** implemented (`tasks/acro_flip.py`; `configs/acro_flip_v2.yaml` is the current roll
  config, `configs/acro_flip.yaml` the v1 baseline expressed in the v2 knobs,
  `configs/acro_flip_pitch.yaml` the axis variant; tiny `[64,64]` net, obs 8). Reward-shaped
  discovery, **no reference trajectory**. v1 (GREEN, `flip_success_rate` 0.845) threw a **wide,
  loopy barrel roll** — ~0.4 m of altitude shed and a long sideways drift — because its reward had
  **no lateral term at all** and a *symmetric* altitude term that punished the very pop a tight flip
  needs. v2 makes it a **point-in-space** flip: rotation-progress toward Φ
  (`reward.rotation_progress`) + one-time completion bonus + a recover term (upright bell − spin,
  gated after completion) − lateral station-keeping ‖xy − xy₀‖ throughout − an **asymmetric**
  altitude penalty (heavy `sink_scale`, light `rise_scale`, past `pop_allow` metres of free
  headroom) − a recover-gated settle/return term − smoothness − crash, with `alive_bonus` cut
  0.1 → 0.02 so shaping is not swamped. The asymmetry is what *licenses* the pop, and the physics
  says that shape is the reward's optimum: a 2π roll at the 12 rad/s envelope takes ≥ 0.52 s and a
  zero-thrust coast that long falls ~1 m, so entering at `v_up ≈ 2.4 m/s` puts the apex mid-flip and
  returns to `z₀` at −2.4 m/s (arrested by ~3 g in 0.08 s / 0.10 m) — net ~+0.3 m up, ~−0.1 m down,
  ~zero lateral, because a coast applies no lateral force at all. Spawn = level hover at rest (the
  flip is the learned behaviour). Config-selectable `axis` (roll→`p` / pitch→`q`) and `n_rotations`.
  Scope this round is **roll only**, A/B'd against the v1 roll baseline; pitch follows if it lands.
- **v2 result (2026-08-01, RTX 4070): RED. `configs/acro_flip_v2.yaml` does not learn the flip.**
  400 M steps, `flip_success_rate` **0.000 final**, best-ever **0.122** — against v1's reported
  0.845. The run oscillates: it reaches ~0.1, collapses back to 0.000, recovers, collapses again,
  and ends never attempting the maneuver (`mean_completion_time` 0.000, `post_recovery_tilt_deg`
  0.000, `peak_climb` 0.44 — it hovers and pops slightly, nothing more). The reason is structural
  rather than a tuning miss, and it is the two terms v2 *added*: `lat_scale` 1.0 and `sink_scale`
  1.0 make "sit at the spawn point collecting `alive_bonus`" a strong local optimum, while the pop
  is punished on the way up and a policy that never inverts never discovers that the far side pays.
  So the shaping meant to produce a *tighter* flip removed the gradient that produced a flip at all.
  **This is an exploration failure, not a capacity one**, which is why re-weighting is not
  guaranteed to fix it — and it is the direct argument for `reference_track` below. The v2 config
  as committed was a stated hypothesis; this is the first time it was measured. `pop_allow: 0.4`
  also still contradicts the reference's measured `peak_climb` of 0.617 m (0.680 deployable), i.e.
  the shape the docs say we want collects a `rise_scale` penalty under this reward.
- **Sim2real basis:** pure IMU + the existing act-v2 CTBR contract → **zero new hardware** (the
  productive agility milestone while the XIAO Sense camera module ships). The acro sim2real risk —
  the attitude estimate degrading mid-flip — is modeled by per-channel obs noise/bias on the
  `gravity_body` channels (config only); both phase channels are noise-free, being the pilot's own
  signals rather than measurements. **v2 adds the one contract change the task family has needed:**
  `ActionLimits.min_thrust_normed` (config `act.min_thrust_normed: 0.25`), the sim-side mirror of
  the pilot's free-flight throttle floor. Rewarding a *coast* means rewarding near-zero throttle
  mid-flip, which the deploy path clamps — so without modeling it the policy learns a profile the
  pilot silently rewrites. Default `0.0` leaves every other task bit-identical. See
  `docs/SIM2REAL.md` for the AIRMODE prerequisite that the floor is insurance against, not a
  guarantee of.

### 🔜 `reference_track` — fly the **hand-authored** maneuver (flip / swing / orbit), graded against it
- **Metric:** `pos_rmse_m` ↓ and `att_rmse_deg` ↓ (did it actually track?) + `track_success_rate`
  (episode-mean position error under `success_pos_rmse`) ↑, with `tracked_frac` (how much of the
  maneuver survived early termination) as the guardrail. The shape names `max_lateral_drift` /
  `peak_climb` / `mean_altitude_loss` / `settle_pos_error` are computed with **`acro_flip`'s own
  definitions**, so a tracked flip and a reward-shaped flip land in one table.
- **Obs/oracle:** **[gravity_body(3), p, q, r, maneuver_phase, gravity_body_ref(3), omega_ref(3)]**
  (13). The first seven are `acro_flip`'s sensor set minus `rotation_remaining` (flip-specific, and
  meaningless for a swing). The last six are the reference's **own attitude and body rate at the
  current phase** — *authored* signals in the same class as `maneuver_phase`, a deterministic
  function of the clock, so at deploy they ship with the policy as a small table rather than needing
  a sensor. They are handed over explicitly rather than left for the net to memorise because a
  `[64,64]` policy should spend capacity on control, not on storing a trajectory it gets for free.
  Reference **position is deliberately absent**: a whoop has no onboard position sensor, so
  `pos_ref − pos` cannot be an observation and position tracking lives in the *reward* only — the
  same privileged line `acro_flip` draws for station-keeping.
- **Status:** implemented (`tasks/reference_track.py` + `reference/track.py`; configs
  `reference_track_{flip,swing,orbit}.yaml` and `_eval` twins). **One task, three maneuvers** —
  `reference/` is a `ManeuverSpec` protocol with three implementations emitting one format, so a
  fourth authored maneuver needs no code here. The reward is a weighted sum of tracking bells
  `exp(−(err/σ)²)` on attitude / rate / position / velocity: bounded, smooth, and it saturates
  rather than exploding on a bad frame. **Reference State Initialization is the load-bearing part,
  not a detail** — `rsi_frac` 0.8 of episodes start at a random phase *in the reference's own
  state*, so inverted flight gets gradient from the first update instead of after a lucky
  exploration sequence (the DeepMimic result, Peng et al. 2018). That is what `env.spawn()` grew a
  `quat=` argument for: a flip spawns inverted, where the ZYX euler triple is degenerate. Early
  termination past `fail_pos_err` reclaims hopeless rollouts. The tracked window drops
  `CLIMB`/`HOVER`/`LAND` as stagecraft, matching the deploy split where `hover_tof` owns take-off
  and landing; a non-contiguous phase selection is **refused**, since a hole would teleport the
  target while still looking smooth on both sides. **Eval twins set `rsi_frac: 0`** — an honest
  rollout, and the only one a hero video should be rendered from, flies the whole maneuver from
  phase 0.
- **Why it exists:** `acro_flip` v2 is the cautionary tale directly above — reward-shaped discovery
  of an acro maneuver is an *exploration* problem, and describing the shape in penalty terms does
  not make its optimum reachable. The maneuver already exists as exactly-derived data
  (`docs/REFERENCE_MANEUVER.md`: differential flatness + a damped-Newton shoot, residuals ~1e-8), so
  the shaping problem moves out of the reward and into the authoring, where it is algebra with a
  closed form.
- **Quote the MANEUVER WINDOW, not the episode.** The `_eval` twins run to the episode cap (499
  steps), while the tracked reference window is 110 (flip) / 268 (swing) / 223 (orbit). Everything
  after it is the trivial hold-the-final-state tail, and `eval/rollout.py`'s full-horizon per-step
  mean averages straight over it — so a reported number is a *mixture* whose blend differs per
  maneuver (flip 78 % tail, swing 46 %, orbit 55 %) and, worse, differs between a policy that
  **crashed early** (all maneuver, no tail) and one that survived (mostly tail). That is what made
  the first flip table below look better than it was. `scripts/reference_vs_policy.py` reports over
  the window and is the number to quote. This is the same failure mode as the `ep_`-prefixed
  accumulators, one level further out.

  | maneuver | reported (full episode) | **maneuver window** | direction |
  |---|---|---|---|
  | swing | 0.195 m / 1.78° | **0.114 m / 1.92°** | the tail made it look *worse* |
  | orbit | 0.239 m / 10.49° | **0.172 m / 6.82°** | the tail made it look *worse* |
  | flip (v1) | 0.448 m / 12.77° | **0.455 m / 12.73°** | ~same — it died before any tail |

- **First results (2026-08-01, RTX 4070, 300 M steps each, ~10 min/run).** DR-off eval through the
  `_eval` twins (`rsi_frac 0`, no station jitter), over the maneuver window:

  | maneuver | `pos_err_m` | `att_err_deg` | flew | verdict |
  |---|---|---|---|---|
  | **swing** | **0.114** | **1.92** | 100 % | **GREEN** |
  | **orbit** | **0.172** | 6.82 | 100 % | **GREEN** (first non-planar policy) |
  | **flip**  | 0.455 | 12.73 | **38 %, crash** | **RED** — see below |

  The ordering is exactly what the reference package predicted from its own authoring numbers: the
  swing is fully powered, planar, 32 % rate headroom and closes at machine precision, and it is the
  one that tracks to under 2°. The orbit is fully powered but genuinely 3D and lands in between.
- **The flip v1 result was worse than "partial".** It does not fly a flatter flip — it **does not
  complete the maneuver**. Every hero episode ends identically at step 42 of 110 (0.84 s of 2.20 s),
  falling through `bound_z_min` during `COAST`; `CATCH` and `RECOVER` are never reached. The
  published `crash_rate_per_step` 0.0227 reads like "2 % of drones crash" and actually means
  1/44 — *every* drone crashes, after ~44 steps — and `tracking_ok` 0.9773 is 43/44 steps alive,
  not 98 % of drones tracking. Per-step rates need a denominator before they mean anything.
- **The flip is UNWILLING to pop, not unable.** The reference commands 3.80 normed thrust through
  `POP`; v1 commands 2.17 against an act-v2 ceiling of **4.0**, and `act[0]` never exceeds +0.087
  of its +1.0 range. It has ~2× the authority it uses. Rate tracking through the roll is fine
  (~9–10 rad/s vs the authored 9.0), so this is a thrust/credit-assignment failure, not an
  attitude one.
- **Flip v2 (position gradient) — the hypothesis is largely REFUTED.** Pre-registered on Flywheel
  (`patient-limit-7117`): the position term is a bell `exp(−(err/0.25)²)` worth 0.04 at the
  achieved error, so widen `pos_sigma` 0.25→0.60 and add a constant-slope `pos_linear` 1.0. Its own
  falsifier — *"if `pos_err_m` does not improve and `peak_climb` stays near 0.21 m, the position
  gradient was not the binding constraint"* — fires. Three arms, all over the maneuver window:

  | arm | flew | `pos_err_m` | `att_err_deg` | peak thrust | peak climb |
  |---|---|---|---|---|---|
  | v1 — parent, seed 0 | 38 %, crash | 0.455 | 12.73 | 2.17 | 0.228 |
  | **control — parent, seed 1** | **100 %** | 0.539 | 3.77 | 2.73 | 0.189 |
  | v2 — pos gradient, seed 0 | 100 % | 0.420 | 2.44 | 2.86 | 0.290 |
  | *reference (authored)* | 100 % | 0 | 0 | **3.80** | **0.680** |

  **The control arm is the finding.** The parent config at seed 1 also survives, so v1's crash was
  **seed variance, not the reward gradient** — and every single-seed `reference_track` result,
  including the two GREENs above, now carries an unmeasured error bar wide enough to flip
  crash/survive. v2 does win on both error channels, but by less than the spread between the two
  parent seeds, so with n=1 per cell the reward change cannot be separated from seed noise.
  What *is* solid: no arm gets near the authored 3.80 pop or the 0.680 m apex, so the position
  gradient is not what limits the flip's shape. `configs/reference_track_flip_v2.yaml`,
  `..._seed1.yaml`.
- **Next lever on the flip — RSI under-samples the `POP`.** With `rsi_frac 0.8`, 80 % of episodes
  start *placed* in the reference's own mid-maneuver state, so they never have to generate the pop
  to get there; only the 20 % that start at phase 0 do, and the pop is ~10 of 110 steps. Phase-
  weighted RSI (oversample the early phases) or a larger phase-0 share is the obvious next
  experiment. **Untested.**
- **Use `--deployable` for the flip.** Its motors-off coast has *zero* rate authority for 10 % of
  the flight (`allocation.min_margin_torqued == 0`), and a policy cannot be trained to track a
  trajectory over an interval where it has no control authority. The swing and the orbit are fully
  powered and need no equivalent — and must **not** inherit the flip's `act.min_thrust_normed`
  floor, since they were not solved against one.
- **The orbit is this lab's first non-planar RL target**, and it only became possible with the
  2026-08-01 vendored rate-loop fix (`CLAUDE.md`, *Vendored DiffAero edits*). Before that a
  non-planar maneuver diverged 17.65 m in this simulator.
- **Sim2real basis:** IMU + the act-v2 CTBR contract + an authored table — **zero new hardware**.
  DR is deliberately lighter than `acro_flip`'s: the reference is authored against the *nominal*
  airframe (`RefModel`, `randomize_airframe=False`), so heavy DR asks the policy to track a
  trajectory that is not physically reachable on the sampled airframe and the tracking error starts
  measuring the DR draw instead of the policy. Harden after the nominal-airframe result is GREEN.
  The reference obs channels carry **no** noise — noising them would model a sensor that does not
  exist.

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
